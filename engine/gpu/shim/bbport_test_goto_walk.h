// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112o_hang-safe-goto, TOOL; goes to the test-tools branch, never a feature branch): the second half of BB_TEST_GOTO
// (bbport_test_goto.h has the knobs and the mailbox).
//   1. Walker: the game thread walks the hunter to the goal in HOPS (BB_TEST_GOTO_HOP metres, default 5, 1 to 15), each hop landing
//      2 m over the last place the hunter was seen standing still, so that the floor at the next stop is as near to loaded ground
//      as a hop is long. One warp 37 m away left the hunter falling through ground that was drawn but had no floor (build 60).
//      Pure logic: it is given the hunter's position once a frame and answers with a warp to make, or that it arrived or failed.
//   2. The framing the render side publishes every observation and the gate the engine's capture trigger asks: a capture is
//      held back while a locked target is not framed (see CaptureHeld).

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <system_error>

#include "bbport_test_goto.h"

namespace BbTestGoto {

inline constexpr float HopDefault = 5.0f, HopLeast = 1.0f, HopMost = 15.0f; ///< metres a hop is long (horizontal)
inline constexpr float FallGuard = 8.0f;        ///< render side: a hunter this far under the ground under the target fell
inline constexpr float FramedMaxDist = 12.0f;   ///< a target farther than this from the camera (3 D) is not framed
inline constexpr float FramedMargin = 0.10f;    ///< the target's middle must lie in the middle 80 percent of the picture
inline constexpr float FramedMinPx = 6.0f;      ///< and its screen box at least this wide or tall
inline constexpr double FreshSeconds = 30.0;    ///< an observation older than this does not count as framed
inline constexpr double HoldLogSeconds = 2.0;   ///< 'capture refused' is printed this often at most

[[nodiscard]] inline float ParseHop(const char* text) {
    if (text == nullptr || *text == 0) {
        return HopDefault;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    if (end == text || *end != 0 || !std::isfinite(v)) {
        return HopDefault;
    }
    return std::clamp(v, HopLeast, HopMost);
}

[[nodiscard]] inline float HopOnce() {
    static const float hop = ParseHop(std::getenv("BB_TEST_GOTO_HOP"));
    return hop;
}

// ---- the walk (pure) ---------------------------------------------------------------------------------------------------
struct WalkParams {
    float hop = HopDefault;    ///< the first hop (m, horizontal)
    float least = HopLeast;    ///< a failed hop halves the next one, never under this
    float lift = 2.0f;         ///< a hop lands this far over the last place the hunter stood (m; review: 1 m put him inside ground rising over 11 deg on a 5 m hop)
    float fall = 6.0f;         ///< a hunter this far under the last place he stood has no floor (m; review: 2.5 m failed good hops down a slope over 27 deg; a void fall passes 6 m in a few frames)
    float still = 0.03f;       ///< frame to frame change of y that counts as standing still (m)
    float arrive = 0.3f;       ///< within this of the goal (horizontal, m) the walk is done
    float near_ask = 0.5f;     ///< the hunter counts as at the asked place within this (horizontal, m): the warp was applied (under the shortest hop)
    unsigned settle_min = 10;  ///< frames after a hop before the hunter may count as standing
    unsigned still_ticks = 8;  ///< frames in a row he must stand still
    unsigned timeout = 240;    ///< frames a hop may take
    unsigned fails_most = 4;   ///< failed hops a walk survives
    unsigned hops_most = 60;
};

enum class WalkEv : std::uint8_t { None, Warp, Arrived, Failed };

struct WalkOut {
    WalkEv ev = WalkEv::None;
    float pos[3] = {};      ///< the warp's place (ev Warp)
    char say[400] = {};     ///< one log line (empty: none)
};

inline void Put(WalkOut& o, const char* body) {
    std::snprintf(o.say, sizeof o.say, "GLINT-PROOF hang goto (r112o): %s", body);
}

class Walker {
    enum class St : std::uint8_t { Idle, Start, Plan, Wait };

public:
    explicit Walker(const WalkParams& p = WalkParams{}) : p_(p) {}

    [[nodiscard]] bool Active() const {
        return st_ != St::Idle;
    }
    [[nodiscard]] unsigned Hops() const {
        return hops_;
    }
    [[nodiscard]] unsigned Fails() const {
        return fails_;
    }
    [[nodiscard]] float Hop() const {
        return hop_;
    }

    void Begin(const float goal[3]) {
        std::memcpy(goal_, goal, sizeof goal_);
        st_ = St::Start;
        hops_ = 0;
        fails_ = 0;
        hop_ = p_.hop;
        recovering_ = false;
        since_ = 0;
        still_ = 0;
        have_prev_ = false;
    }

    void Abort() {
        st_ = St::Idle;
    }

    /// A loading screen: the settle count starts again, nothing else changes.
    void Pause() {
        since_ = 0;
        still_ = 0;
        have_prev_ = false;
    }

    /// Once a frame with the hunter's position as the game keeps it (the caller has made sure he lives and no loading
    /// screen is up).
    [[nodiscard]] WalkOut Tick(const float cur[3]) {
        WalkOut o;
        if (st_ == St::Idle || !Finite3(cur)) {
            return o;
        }
        char b[300];
        if (st_ == St::Start) {
            std::memcpy(good_, cur, sizeof good_);
            st_ = St::Plan;
            std::snprintf(b, sizeof b,
                          "walk begun: hunter %.2f %.2f %.2f to %.2f %.2f %.2f, %.1f m horizontally, in hops of %.1f m, each "
                          "landing %.1f m over a place where the hunter stood still",
                          double(cur[0]), double(cur[1]), double(cur[2]), double(goal_[0]), double(goal_[1]),
                          double(goal_[2]), double(Horizontal(cur, goal_)), double(hop_), double(p_.lift));
            Put(o, b);
            return o;
        }
        if (st_ == St::Plan) {
            PlanHop(o);
            return o;
        }
        WaitTick(o, cur);
        return o;
    }

private:
    void PlanHop(WalkOut& o) {
        char b[300];
        const float rem = Horizontal(good_, goal_);
        if (rem <= p_.arrive) {
            st_ = St::Idle;
            o.ev = WalkEv::Arrived;
            std::snprintf(b, sizeof b,
                          "walk done: arrived after %u hop%s (%u failed): hunter %.2f %.2f %.2f, %.2f m from the goal, "
                          "standing still on ground that was loaded there",
                          hops_, hops_ == 1 ? "" : "s", fails_, double(good_[0]), double(good_[1]), double(good_[2]),
                          double(rem));
            Put(o, b);
            return;
        }
        if (hops_ >= p_.hops_most) {
            st_ = St::Idle;
            o.ev = WalkEv::Failed;
            std::snprintf(b, sizeof b, "walk gave up: more than %u hops, %.1f m still to go", p_.hops_most, double(rem));
            Put(o, b);
            return;
        }
        const float step = std::min(hop_, rem);
        const float k = step / rem;
        o.pos[0] = good_[0] + (goal_[0] - good_[0]) * k;
        o.pos[1] = good_[1] + p_.lift;
        o.pos[2] = good_[2] + (goal_[2] - good_[2]) * k;
        o.ev = WalkEv::Warp;
        Ask(o.pos);
        recovering_ = false;
        std::snprintf(b, sizeof b, "hop %u: %.1f m of the %.1f m left: hunter to %.2f %.2f %.2f, %.1f m over where he stood",
                      hops_ + 1, double(step), double(rem), double(o.pos[0]), double(o.pos[1]), double(o.pos[2]),
                      double(p_.lift));
        Put(o, b);
    }

    void Ask(const float pos[3]) {
        std::memcpy(asked_, pos, sizeof asked_);
        since_ = 0;
        still_ = 0;
        have_prev_ = false;
        st_ = St::Wait;
    }

    void WaitTick(WalkOut& o, const float cur[3]) {
        char b[300];
        char why[200];
        ++since_;
        const float dy = have_prev_ ? std::fabs(cur[1] - prev_y_) : 1.0e9f;
        prev_y_ = cur[1];
        have_prev_ = true;
        const bool near_ask = Horizontal(cur, asked_) <= p_.near_ask;
        if (near_ask && cur[1] < good_[1] - p_.fall) {
            std::snprintf(why, sizeof why, "fell to y %.2f, %.2f m under the last place he stood: no floor %.1f m from there",
                          double(cur[1]), double(good_[1] - cur[1]), double(Horizontal(good_, asked_)));
            Fail(o, why);
            return;
        }
        if (since_ >= p_.timeout) {
            std::snprintf(why, sizeof why, "no rest in %u frames (y %.2f, %.1f m from the asked place)", p_.timeout,
                          double(cur[1]), double(Horizontal(cur, asked_)));
            Fail(o, why);
            return;
        }
        still_ = (near_ask && dy <= p_.still) ? still_ + 1 : 0;
        if (since_ >= p_.settle_min && still_ >= p_.still_ticks) {
            std::memcpy(good_, cur, sizeof good_);
            if (!recovering_) {
                ++hops_;
            }
            std::snprintf(b, sizeof b,
                          "%s: the hunter stands still at %.2f %.2f %.2f after %u frames (y within %.2f m for %u frames: the "
                          "floor there is loaded)",
                          recovering_ ? "back on the last good place" : "hop done", double(cur[0]), double(cur[1]),
                          double(cur[2]), since_, double(p_.still), still_);
            Put(o, b);
            st_ = St::Plan;
        }
    }

    void Fail(WalkOut& o, const char* why) {
        char b[320];
        ++fails_;
        if (fails_ > p_.fails_most) {
            st_ = St::Idle;
            o.ev = WalkEv::Failed;
            std::snprintf(b, sizeof b,
                          "walk gave up after %u failed hops (%s); the last good place is %.2f %.2f %.2f, %.1f m from the goal",
                          fails_, why, double(good_[0]), double(good_[1]), double(good_[2]),
                          double(Horizontal(good_, goal_)));
            Put(o, b);
            return;
        }
        hop_ = std::max(p_.least, hop_ * 0.5f);
        o.ev = WalkEv::Warp;
        o.pos[0] = good_[0];
        o.pos[1] = good_[1] + p_.lift;
        o.pos[2] = good_[2];
        Ask(o.pos);
        recovering_ = true;
        std::snprintf(b, sizeof b, "hop failed (%s): back to the last good place %.2f %.2f %.2f, the next hop %.1f m", why,
                      double(good_[0]), double(good_[1]), double(good_[2]), double(hop_));
        Put(o, b);
    }

    WalkParams p_;
    St st_ = St::Idle;
    float goal_[3] = {};
    float good_[3] = {};   ///< where the hunter was last seen standing still
    float asked_[3] = {};  ///< where the last warp put him
    float hop_ = HopDefault;
    float prev_y_ = 0.0f;
    bool have_prev_ = false, recovering_ = false;
    unsigned hops_ = 0, fails_ = 0, since_ = 0, still_ = 0;
};

inline std::atomic<bool> g_walking{false};   ///< a walk is on (the render side does not time its request out while it is)

[[nodiscard]] inline bool Walking() {
    return g_walking.load(std::memory_order_relaxed);
}

inline void SetWalking(bool on) {
    g_walking.store(on, std::memory_order_relaxed);
}

/// The game thread's one walker (BB_TEST_GOTO_HOP read once).
[[nodiscard]] inline Walker& TheWalker() {
    static Walker w = [] {
        WalkParams p;
        p.hop = HopOnce();
        return Walker(p);
    }();
    return w;
}

// ---- the framing, published by the render side, asked by the capture trigger ---------------------------------------------
struct Shared {
    bool engaged = false;    ///< a target is locked: there is something to frame
    bool framed = false;
    bool seen = false;       ///< an observation came
    std::chrono::steady_clock::time_point at{};
    std::chrono::steady_clock::time_point last_log{};
    std::string text, why;
    unsigned taken = 0, refused = 0;
};

[[nodiscard]] inline std::mutex& SharedLock() {
    static std::mutex m;
    return m;
}

[[nodiscard]] inline Shared& SharedState() {
    static Shared s;
    return s;
}

inline void PublishFraming(bool engaged, bool framed, const std::string& text, const std::string& why) {
    std::lock_guard lock(SharedLock());
    Shared& s = SharedState();
    s.engaged = engaged;
    s.framed = framed;
    s.seen = true;
    s.at = std::chrono::steady_clock::now();
    s.text = text;
    s.why = why;
}

inline void Counts(unsigned* taken, unsigned* refused) {
    std::lock_guard lock(SharedLock());
    *taken = SharedState().taken;
    *refused = SharedState().refused;
}

enum class Gate : std::uint8_t { Free, Take, HoldNotFramed, HoldStale };

/// The capture trigger's verdict (pure): with nothing locked the picture is free; a framed and fresh observation takes it.
[[nodiscard]] inline Gate GateOf(bool engaged, bool seen, bool framed, double age_seconds) {
    if (!engaged) {
        return Gate::Free;
    }
    if (!seen || age_seconds > FreshSeconds) {
        return Gate::HoldStale;
    }
    return framed ? Gate::Take : Gate::HoldNotFramed;
}

/// The engine's capture trigger asks before it consumes its file (`trigger`: BB_PRESENT_DUMP_TRIGGER): true holds the capture
/// (the file stays; the slot runner times out after 20 s and notes it). Without BB_TEST_GOTO, or without a trigger file
/// waiting, false at once.
[[nodiscard]] inline bool CaptureHeld(const char* trigger) {
    if (!On() || trigger == nullptr || *trigger == 0) {
        return false;
    }
    std::error_code ec;
    if (!std::filesystem::exists(std::filesystem::path(trigger), ec) || ec) {
        return false;
    }
    const std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now();
    std::lock_guard lock(SharedLock());
    Shared& s = SharedState();
    const double age = s.seen ? std::chrono::duration<double>(now - s.at).count() : 1.0e9;
    const Gate g = GateOf(s.engaged, s.seen, s.framed, age);
    if (g == Gate::Free) {
        return false;
    }
    if (g == Gate::Take) {
        ++s.taken;
        std::printf("GLINT-PROOF hang goto (r112o): capture taken: %s (the observation is %.1f s old)\n", s.text.c_str(), age);
        return false;
    }
    ++s.refused;
    if (std::chrono::duration<double>(now - s.last_log).count() >= HoldLogSeconds) {
        s.last_log = now;
        std::printf("GLINT-PROOF hang goto (r112o): capture refused: not framed (%s; the observation is %.1f s old): %s\n",
                    g == Gate::HoldStale ? "no fresh observation" : s.why.c_str(), age, s.text.c_str());
    }
    return true;
}

} // namespace BbTestGoto
