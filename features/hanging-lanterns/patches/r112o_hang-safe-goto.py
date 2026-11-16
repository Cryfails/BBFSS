# r112o_hang-safe-goto (TOOL): on top of r112n_hang-teleport-camera (r112m, r112l ... all applied in the tree, build 60).
# GRADE: a TOOL (a test aid: BB_TEST_GOTO belongs to the test-tools branch, never a feature branch). Nothing here changes a feature.
#
# THE EVIDENCE (b60: b60_s4.log graveyard, b60_s5.log proof, b60_s6.log house, b60_reports.txt hang section)
#  - r112n locked lantern B of 97f2d384 (0.21 x 0.29 m, 6.29 m up, 39.5 m away) and made ONE warp 36.9 m away, to y -41.99, only 0.3 m
#    above the scene box's ground (-42.29). The hunter's y then fell about 1 m a frame (-85 at f748, -182, -300, -414 at f1108): the
#    place 37 m away had a picture (the lantern was drawn from 39 m) but no floor the hunter could stand on yet. The camera followed
#    the falling hunter, the plan said 'camera not there ... another warp', the second plan met 'the hunter and the camera are not
#    within 12 m' and gave up. The pictures show a tree and no lantern. (The push itself works: 7 of 7 candidates pushed 0.054-0.062 m.)
#
# WHAT THIS CHANGES
#  (1) THE HUNTER WALKS THERE IN HOPS (online_fixes.cpp TestGotoTick, bbport_test_goto_walk.h new). The first choice of the task (scout
#      mode's lamp travel) is NOT used: scout mode is not in this tree (it is on dev/scout-mode in <tree2>), the tree has no
#      table of where a lamp stands (a lamp warp is a map load that puts the hunter at the lamp, wherever that is), and a load drops
#      the scene the target was read from. The second choice is done more safely than 'one warp, held': the same call (the engine's
#      own co-op bring-to-host, MoveBodyToSafeSpot, its entry bytes checked) is made in HOPS of BB_TEST_GOTO_HOP metres (default 5,
#      1 to 15) toward the goal. A hop lands 2 m above the last place the hunter was SEEN standing still (read from the game each
#      frame), so the floor at the next stop is as close to ground that is loaded as the hop is long; the hunter falls that metre and
#      the walk waits until his y stays within 0.03 m of itself for 8 frames (at least 10 frames after the hop, within 0.5 m of the
#      asked place: the position was applied). That is how the walk knows the collision there is loaded, and it logs it ('the floor
#      there is loaded'). A hunter that ends 6 m or more under the last place he stood has no floor: the walk puts him back on
#      the last good place (2 m above it), halves the hop (not under 1 m) and goes on; after 4 failures it gives up and says so.
#      No hop is ever planned from a falling hunter: every plan starts from a position the walk saw at rest. The render side does
#      not chase either: the failure of a walk is final (no 'asking again'), a hunter 8 m under the ground under the target is
#      'fell' and ends the run, and a walk in progress is never timed out (the render side waits while it walks).
#  (2) CAPTURES ARE REFUSED WHEN NOT FRAMED (bbport_test_goto_hang.h, vk_temporal_upscaler.cpp, two conditions and one include).
#      Every observation (the box set is read every 60 frames) publishes whether the target is FRAMED: the run has arrived (phase
#      holding), the camera and its view are read, the target's screen box is in front of the camera, its middle lies in the middle
#      80 percent of the picture, the box is 6 px or more and the camera is 12 m or less from it (3 D). A new log line per
#      observation says it ('GLINT-PROOF hang goto (r112o): framing ...: FRAMED|NOT FRAMED: why (camera to target, the screen
#      box); captures taken N, refused polls M'). The slot runner's capture is a trigger FILE that the engine consumes at a present
#      (DisplayOverride, PresentDumpDue in vk_temporal_upscaler.cpp): with BB_TEST_GOTO on and a target locked, the engine leaves
#      the file where it is while the target is not framed (or the observation is more than 30 s old), prints 'capture refused: not
#      framed (why)' at most every 2 s, and takes it the first present after the target is framed, printing 'capture taken: camera
#      to target D m, screen box ...'. The runner waits 20 s for the file to go and then notes 'trigger NOT taken': that is the
#      refusal in its own words. With no target locked (the house: nothing to frame) the gate does nothing.
#  (3) jobs: slot_jobs_r112o_hang-safe-goto.json (3 jobs).
#
# Off: BB_TEST_GOTO unset or not understood: BbTestGoto::On() is a static bool; TestGotoTick returns at one relaxed load of a false
# atomic and one more of the walking flag (both false); the two capture conditions end at On() (a static bool) before any file is
# touched; Observe returns at its first line. On: the walk costs a position read and a few compares a frame on the game thread
# while it walks (a few seconds); the gate costs one file-exists test per present while a capture is waited for. GPU none.
# Memory: a Walker of 100 bytes and a Shared of 300.
#
# Shared files: vk_temporal_upscaler.cpp (one include and two conditions, in the two functions that consume the dump trigger),
# README.md (one sentence of r112n's row, one new row). online_fixes.cpp: only r112n's TestGotoTick (replaced) and its include.
#
# Use: python -I -X utf8 r112o_hang-safe-goto.py check | apply | revert
# Root: R112O_ROOT, else <tree>. CRLF kept (the new file takes CRLF). apply backs the originals up in r112o_backup next to
# this script; revert takes out exactly what apply put in and removes the new file. Needs r112n applied (the anchors are its texts).
import os, re, sys

ROOT = os.environ.get("R112O_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112o_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
UP = RV + "vk_temporal_upscaler.cpp"
SH = "engine/gpu/shim/"
TG = SH + "bbport_test_goto.h"
TH = SH + "bbport_test_goto_hang.h"
TW = SH + "bbport_test_goto_walk.h"
OF = SH + "engine/online_fixes.cpp"
NT = "engine/tests/test_wind_hang_find.cpp"
RM = "README.md"

# ---- the new file -----------------------------------------------------------------------------------
NEW_FILES = {
    TW: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
''',
}

# ---- bbport_test_goto_hang.h: the framing, the failure is final, the walk is not timed out ------------------------------
H1 = r"""#include "bbport_wind_hang_find.h"
"""
H1N = r"""#include "bbport_test_goto_walk.h" // bbport (r112o_hang-safe-goto, TOOL)
"""

H2 = r"""/// One observation of the hang survey's box set, with the knobs and the session given (the tests' entry). Returns the lines
"""
H2P = r"""/// bbport (r112o_hang-safe-goto): whether a picture taken now would show the target. Phase holding (the run arrived), the camera and
/// its view read, the target's screen box in front of the camera with its middle in the middle 80 percent of the picture, the box
/// 6 px or more and the camera 12 m or less from it (3 D). A fixed position (BB_TEST_GOTO=x,y,z) is framed when the run holds.
struct Framing {
    bool framed = false;
    std::string why;   ///< what is wrong (empty when framed)
    std::string text;  ///< camera to target and the screen box, for the capture lines
    std::string line;  ///< the observation's own log line
};

[[nodiscard]] inline Framing FramingOf(const Knobs& k, const Session& s, const Reading& r, std::uint64_t frame) {
    Framing f;
    char part[240];
    float d3 = 0.0f;
    if (r.cam_ok) {
        d3 = std::sqrt(std::pow(s.centre[0] - r.cam[0], 2.0f) + std::pow(s.centre[1] - r.cam[1], 2.0f) +
                       std::pow(s.centre[2] - r.cam[2], 2.0f));
        std::snprintf(part, sizeof(part), "camera to target %.1f m (horizontal %.1f m)", double(d3),
                      double(Horizontal(r.cam, s.centre)));
        f.text = part;
    } else {
        f.text = "camera not read";
    }
    const float w = float(r.width), h = float(r.height);
    const float cx = 0.5f * (r.sb.x0 + r.sb.x1), cy = 0.5f * (r.sb.y0 + r.sb.y1);
    if (r.view_ok && r.sb.any) {
        std::snprintf(part, sizeof(part), ", screen box %.0f,%.0f to %.0f,%.0f of %ux%u", double(r.sb.x0), double(r.sb.y0),
                      double(r.sb.x1), double(r.sb.y1), static_cast<unsigned>(r.width), static_cast<unsigned>(r.height));
        f.text += part;
    } else if (r.view_ok) {
        f.text += ", screen box behind the camera";
    }
    if (s.phase != Phase::Holding) {
        f.why = std::string("the run has not arrived (") + PhaseName(s.phase) + ")";
    } else if (!k.hang) {
        f.framed = true;
    } else if (!r.cam_ok || !r.view_ok) {
        f.why = "the camera or its view is not read";
    } else if (!r.sb.any) {
        f.why = "the target is behind the camera";
    } else if (!(w > 0.0f && h > 0.0f)) {
        f.why = "the render size is not read";
    } else if (cx < FramedMargin * w || cx > (1.0f - FramedMargin) * w || cy < FramedMargin * h ||
               cy > (1.0f - FramedMargin) * h) {
        f.why = "the target's middle is outside the middle 80 percent of the picture (the pad's ry=0 looks up)";
    } else if (std::max(r.sb.x1 - r.sb.x0, r.sb.y1 - r.sb.y0) < FramedMinPx) {
        f.why = "the target's screen box is under 6 px";
    } else if (d3 > FramedMaxDist) {
        f.why = "the target is more than 12 m from the camera";
    } else {
        f.framed = true;
    }
    unsigned taken = 0, refused = 0;
    Counts(&taken, &refused);
    std::snprintf(part, sizeof(part), "GLINT-PROOF hang goto (r112o): framing f%llu: %s%s%s (", static_cast<unsigned long long>(frame),
                  f.framed ? "FRAMED" : "NOT FRAMED", f.framed ? "" : ": ", f.why.c_str());
    f.line = part;
    f.line += f.text;
    std::snprintf(part, sizeof(part), "); captures taken %u, refused polls %u", taken, refused);
    f.line += part;
    return f;
}

"""

H3 = r"""        } else if (since > WaitFrames) {
"""
H3N = r"""        } else if (since > WaitFrames && !Walking()) { // bbport (r112o_hang-safe-goto): a walk in progress is waited for
"""

H4 = r"""                s.phase = s.tries >= TriesMost ? Phase::GaveUp : Phase::Wait;
                std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): warp %u refused by the game thread%s", s.seq,
"""
H4N = r"""                s.phase = Phase::GaveUp; // bbport (r112o_hang-safe-goto): a walk that failed is final, no chasing
                std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): warp %u refused by the game thread%s", s.seq,
"""

H5 = r"""        if (!k.hang) {
            s.phase = Phase::Holding;
"""
H5N = r"""        if (r.hunter_ok && r.hunter[1] < s.ground_y - FallGuard) { // bbport (r112o_hang-safe-goto): no second warp from a fallen hunter
            s.phase = Phase::GaveUp;
            PublishFraming(true, false, "gave up", "the hunter fell");
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112o): gave up: the hunter is %.1f m under the ground under the target "
                          "(y %.2f, ground y %.2f): he fell; no second warp from there",
                          double(s.ground_y - r.hunter[1]), double(r.hunter[1]), double(s.ground_y));
            say(buf);
            return out;
        } else if (!k.hang) {
            s.phase = Phase::Holding;
"""

H6 = r"""    if (s.phase != Phase::GaveUp) {
        const bool quiet = s.phase == Phase::Wait && !k.hang;
        if (!quiet) {
            say(LineOf(s, r, frame));
        }
    }
"""
H6N = r"""    const Framing framing = FramingOf(k, s, r, frame); // bbport (r112o_hang-safe-goto): the capture trigger asks this
    PublishFraming(s.locked, framing.framed, framing.text, framing.why);
    if (s.phase != Phase::GaveUp) {
        const bool quiet = s.phase == Phase::Wait && !k.hang;
        if (!quiet) {
            say(LineOf(s, r, frame));
            say(framing.line);
        }
    }
"""

# ---- the engine: the game thread walks the hunter -----------------------------------------------------------------------
O1 = r"""#include "bbport_test_goto.h" // bbport (r112n_hang-teleport-camera, TOOL)
"""
O1N = r"""#include "bbport_test_goto_walk.h" // bbport (r112o_hang-safe-goto, TOOL)
"""

O2 = r"""// bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO. The render thread posts a request (bbport_test_goto.h); here, on the game
// thread once a frame, the living hunter is put there with the call that brings a co-op guest to the host's side
// (MoveBodyToSafeSpot: the engine's own body move; it also writes the position into the transition block's spot, as
// there), keeping the hunter's facing. Not while a loading screen is up, nobody stands in the world or the hunter is dead (the
// request waits; the render side gives up after 900 frames). The warp's entry bytes are checked against 1.09's first. Off: one
// relaxed load of a false flag a frame.
void TestGotoTick() {
    if (!BbTestGoto::Pending() || !g_image) return;
    const std::uint64_t local = LocalPlayer();
    if (!local || Loading() || Hp(local) <= 0) return;
    BbTestGoto::Request r;
    if (!BbTestGoto::Take(&r)) return;
    if (std::memcmp(g_image + kWarp, kWarpEntry, sizeof kWarpEntry) != 0) {
        BbTestGoto::Done(r.seq, false);
        std::printf("GLINT-PROOF hang goto (r112n): warp %u refused: the engine's warp entry is not 1.09's\n", r.seq);
        return;
    }
    float at[3] = {};
    const bool placed = Position(local, at);
    const float yaw = Facing(local);
    const float facing[3] = {0.0f, yaw, 0.0f};
    MoveBodyToSafeSpot(local, r.pos, facing);
    BbTestGoto::Done(r.seq, true);
    std::printf("GLINT-PROOF hang goto (r112n): warp %u made by the game thread: hunter to %.2f %.2f %.2f (was %.2f %.2f "
                "%.2f%s, facing %.3f)\n",
                r.seq, double(r.pos[0]), double(r.pos[1]), double(r.pos[2]), double(at[0]), double(at[1]), double(at[2]),
                placed ? "" : ", not read", double(yaw));
}
"""
O2N = r"""// bbport (r112o_hang-safe-goto, TOOL; r112n's one warp replaced): BB_TEST_GOTO. The render thread posts a request
// (bbport_test_goto.h); here, on the game thread once a frame, the living hunter is WALKED there in hops (bbport_test_goto_walk.h:
// BB_TEST_GOTO_HOP metres, each hop landing 2 m over the last place he was seen standing still, then a wait until his y keeps
// still: the floor there is loaded). A hop is the call that brings a co-op guest to the host's side (MoveBodyToSafeSpot: the
// engine's own body move; it also writes the position into the transition block's spot, as there), keeping the hunter's facing.
// Nothing moves while a loading screen is up (the walk's settle count starts again), nobody stands in the world or the hunter is
// dead (the request waits; a walk stops). The warp's entry bytes are checked against 1.09's first. Off: one relaxed load of a
// false flag and one of the walking flag a frame.
void TestGotoTick() {
    if (!BbTestGoto::Pending() && !BbTestGoto::Walking()) return;
    if (!g_image) return;
    BbTestGoto::Walker& walker = BbTestGoto::TheWalker();
    static std::uint32_t seq = 0;
    const std::uint64_t local = LocalPlayer();
    if (!local || Hp(local) <= 0) {
        if (walker.Active()) {
            walker.Abort();
            BbTestGoto::SetWalking(false);
            BbTestGoto::Done(seq, false);
            std::printf("GLINT-PROOF hang goto (r112o): walk %u stopped: no living hunter in the world\n", seq);
        }
        return;
    }
    if (Loading()) {
        walker.Pause();
        return;
    }
    float at[3] = {};
    const bool placed = Position(local, at);
    if (!walker.Active()) {
        BbTestGoto::Request r;
        if (!BbTestGoto::Take(&r)) return;
        seq = r.seq;
        if (std::memcmp(g_image + kWarp, kWarpEntry, sizeof kWarpEntry) != 0) {
            BbTestGoto::Done(seq, false);
            std::printf("GLINT-PROOF hang goto (r112n): warp %u refused: the engine's warp entry is not 1.09's\n", seq);
            return;
        }
        if (!placed) {
            BbTestGoto::Done(seq, false);
            std::printf("GLINT-PROOF hang goto (r112o): walk %u refused: the hunter's position is not read\n", seq);
            return;
        }
        walker.Begin(r.pos);
        BbTestGoto::SetWalking(true);
    }
    if (!placed) return;
    const BbTestGoto::WalkOut out = walker.Tick(at);
    if (out.say[0] != 0) std::printf("%s\n", out.say);
    if (out.ev == BbTestGoto::WalkEv::Warp) {
        const float facing[3] = {0.0f, Facing(local), 0.0f};
        MoveBodyToSafeSpot(local, out.pos, facing);
    } else if (out.ev == BbTestGoto::WalkEv::Arrived || out.ev == BbTestGoto::WalkEv::Failed) {
        BbTestGoto::SetWalking(false);
        BbTestGoto::Done(seq, out.ev == BbTestGoto::WalkEv::Arrived);
    }
}
"""

# ---- vk_temporal_upscaler.cpp: the capture trigger asks the gate ------------------------------------------------------------
U0 = r"""#include "bbport_toggles.h"
"""
U0N = r"""#include "bbport_test_goto_walk.h" // bbport (r112o_hang-safe-goto, TOOL): BB_TEST_GOTO holds a capture while the target is not framed
"""

U1 = r"""    if (dump && dump_remaining == 0 && std::remove(dump) == 0) {
"""
U1N = r"""    if (dump && dump_remaining == 0 && !BbTestGoto::CaptureHeld(dump) && std::remove(dump) == 0) {
"""

U2 = r"""    if (dump && present_dump_remaining == 0 && std::remove(dump) == 0) {
"""
U2N = r"""    if (dump && present_dump_remaining == 0 && !BbTestGoto::CaptureHeld(dump) && std::remove(dump) == 0) {
"""

# ---- the tests ----------------------------------------------------------------------------------------------------------
T2 = r"""Expect(gl.size() == 2 && Has(gl[0], "GLINT-PROOF hang goto (r112n): target locked"""
T2N = r"""Expect(gl.size() == 3 && Has(gl[0], "GLINT-PROOF hang goto (r112n): target locked"""
T3 = r"""G::Pending() && gl.size() == 2 &&"""
T3N = r"""G::Pending() && gl.size() == 3 &&"""

T1 = r"""        const std::string once_m = F::OnceTextM(true, true, F::TallDefault);
"""
T1P = r"""        // bbport (r112o_hang-safe-goto): the hop walk against a floor that exists only near where the hunter has stood, the framing, the gate
        {
            namespace G = BbTestGoto;
            Expect(std::fabs(G::ParseHop(nullptr) - 5.0f) < 1e-6f && std::fabs(G::ParseHop("") - 5.0f) < 1e-6f &&
                       std::fabs(G::ParseHop("2.5") - 2.5f) < 1e-6f && std::fabs(G::ParseHop("0.1") - G::HopLeast) < 1e-6f &&
                       std::fabs(G::ParseHop("99") - G::HopMost) < 1e-6f && std::fabs(G::ParseHop("x") - 5.0f) < 1e-6f &&
                       std::fabs(G::ParseHop("3x") - 5.0f) < 1e-6f && std::fabs(G::ParseHop("nan") - 5.0f) < 1e-6f,
                   "r112o: BB_TEST_GOTO_HOP is 1 to 15, anything else is 5");
            // the world: y is 0 within `radius` of a place where the hunter stood still; everywhere else he falls 0.9 m a frame
            const auto walk = [&](float hop, float radius, unsigned* hops, unsigned* fails, std::string* last) -> int {
                G::WalkParams p;
                p.hop = hop;
                G::Walker w(p);
                const float goal[3] = {-33.55f, 0.0f, 107.65f};
                float at[3] = {-48.89f, 0.0f, 74.04f};
                std::vector<std::array<float, 2>> loaded;
                loaded.push_back({at[0], at[2]});
                w.Begin(goal);
                for (unsigned tick = 0; tick < 6000; ++tick) {
                    bool floor = false;
                    for (const std::array<float, 2>& l : loaded) {
                        if (std::hypot(at[0] - l[0], at[2] - l[1]) <= radius) {
                            floor = true;
                        }
                    }
                    if (floor) {
                        at[1] = std::max(0.0f, at[1] - 0.3f);
                    } else {
                        at[1] -= 0.9f;
                    }
                    const G::WalkOut o = w.Tick(at);
                    if (o.say[0] != 0) {
                        *last = o.say;
                    }
                    *hops = w.Hops();
                    *fails = w.Fails();
                    if (o.ev == G::WalkEv::Warp) {
                        std::memcpy(at, o.pos, sizeof at);
                    } else if (o.ev == G::WalkEv::Arrived) {
                        return 1;
                    } else if (o.ev == G::WalkEv::Failed) {
                        return 0;
                    }
                    if (floor && at[1] == 0.0f &&
                        std::hypot(at[0] - loaded.back()[0], at[2] - loaded.back()[1]) > 1.0f) {
                        loaded.push_back({at[0], at[2]});
                    }
                }
                return -1;
            };
            unsigned hops = 0, fails = 0;
            std::string last;
            Expect(walk(5.0f, 7.0f, &hops, &fails, &last) == 1 && hops == 8 && fails == 0 &&
                       Has(last, "GLINT-PROOF hang goto (r112o): walk done: arrived after 8 hops (0 failed)"),
                   "r112o: 5 m hops over ground that is loaded 7 m around a standing place: 8 hops, no failure");
            Expect(walk(15.0f, 7.0f, &hops, &fails, &last) == 1 && fails == 2 && hops >= 10 && Has(last, "arrived after"),
                   "r112o: 15 m hops fall twice (15 m, then 7.5 m is too far), halve to 3.75 m and arrive");
            Expect(walk(5.0f, 0.5f, &hops, &fails, &last) == 0 && fails == 5 && Has(last, "walk gave up after 5 failed hops (fell to y"),
                   "r112o: no floor beyond 0.5 m: five failures end the walk, and the line says why");
            // a hunter that never moves after a warp (the warp is not applied): each hop times out and goes back, and in the end the walk gives up
            {
                G::WalkParams p;
                G::Walker w(p);
                const float goal[3] = {10.0f, 0.0f, 0.0f};
                const float at[3] = {0.0f, 0.0f, 0.0f};
                w.Begin(goal);
                int ev_warp = 0;
                int ev_failed = 0;
                std::string text;
                for (unsigned tick = 0; tick < 5000 && ev_failed == 0; ++tick) {
                    const G::WalkOut o = w.Tick(at);
                    ev_warp += o.ev == G::WalkEv::Warp ? 1 : 0;
                    ev_failed += o.ev == G::WalkEv::Failed ? 1 : 0;
                    if (o.ev == G::WalkEv::Failed) {
                        text = o.say;
                    }
                }
                Expect(ev_failed == 1 && ev_warp == 9 && Has(text, "walk gave up after 5 failed hops (no rest in 240 frames"),
                       "r112o: a warp that is never applied times out five times (nine warps: five hops, four ways back) and gives up");
            }
            {
                G::Walker w;
                const float goal[3] = {1.0f, 0.0f, 0.0f};
                const float here[3] = {0.0f, 0.0f, 0.0f};
                Expect(!w.Active() && w.Tick(here).ev == G::WalkEv::None, "r112o: an idle walker does nothing");
                w.Begin(goal);
                w.Pause();
                w.Abort();
                Expect(!w.Active() && w.Tick(here).ev == G::WalkEv::None, "r112o: a walker that was aborted does nothing");
                const float nanpos[3] = {std::nanf(""), 0.0f, 0.0f};
                w.Begin(goal);
                Expect(w.Active() && w.Tick(nanpos).ev == G::WalkEv::None && w.Active(), "r112o: a position that is no number is ignored");
            }

            // the framing
            G::Session fs;
            fs.phase = G::Phase::Holding;
            fs.centre[0] = -34.0f;
            fs.centre[1] = -35.56f;
            fs.centre[2] = 107.4f;
            G::Reading fr;
            fr.cam_ok = true;
            fr.view_ok = true;
            fr.cam[0] = -34.0f;
            fr.cam[1] = -40.0f;
            fr.cam[2] = 104.0f;
            fr.sb.any = true;
            fr.sb.all = true;
            fr.sb.x0 = 600.0f;
            fr.sb.y0 = 300.0f;
            fr.sb.x1 = 650.0f;
            fr.sb.y1 = 340.0f;
            fr.width = 1280;
            fr.height = 720;
            G::Knobs fk;
            fk.on = true;
            const G::Framing in_view = G::FramingOf(fk, fs, fr, 900);
            Expect(in_view.framed && in_view.why.empty() && Has(in_view.text, "camera to target 5.6 m") &&
                       Has(in_view.text, "screen box 600,300 to 650,340 of 1280x720") && Has(in_view.line, "framing f900: FRAMED (") &&
                       Has(in_view.line, "captures taken 0, refused polls 0"),
                   "r112o: a target in the middle of the picture, 5.6 m away, is framed");
            G::Reading edge = fr;
            edge.sb.x0 = 1200.0f;
            edge.sb.x1 = 1250.0f;
            const G::Framing at_edge = G::FramingOf(fk, fs, edge, 900);
            Expect(!at_edge.framed && Has(at_edge.why, "outside the middle 80 percent") && Has(at_edge.line, "NOT FRAMED: the target's middle"),
                   "r112o: a target at the edge of the picture is not framed");
            G::Reading behind = fr;
            behind.sb.any = false;
            G::Reading tiny = fr;
            tiny.sb.x1 = 603.0f;
            tiny.sb.y1 = 303.0f;
            G::Reading far_cam = fr;
            far_cam.cam[2] = 80.0f;
            G::Reading blind = fr;
            blind.cam_ok = false;
            G::Session waiting = fs;
            waiting.phase = G::Phase::Settling;
            Expect(Has(G::FramingOf(fk, fs, behind, 1).why, "behind the camera") && Has(G::FramingOf(fk, fs, tiny, 1).why, "under 6 px") &&
                       Has(G::FramingOf(fk, fs, far_cam, 1).why, "more than 12 m") && Has(G::FramingOf(fk, fs, blind, 1).why, "not read") &&
                       Has(G::FramingOf(fk, waiting, fr, 1).why, "has not arrived (settling)") && !G::FramingOf(fk, waiting, fr, 1).framed,
                   "r112o: behind, tiny, far, unread and not arrived are all not framed, each with its reason");
            G::Knobs fixed = fk;
            fixed.hang = false;
            Expect(G::FramingOf(fixed, fs, blind, 1).framed && !G::FramingOf(fixed, waiting, fr, 1).framed,
                   "r112o: a fixed position is framed when the run holds");

            // the gate
            Expect(G::GateOf(false, false, false, 0.0) == G::Gate::Free && G::GateOf(false, true, true, 99.0) == G::Gate::Free &&
                       G::GateOf(true, true, true, 1.0) == G::Gate::Take && G::GateOf(true, true, false, 1.0) == G::Gate::HoldNotFramed &&
                       G::GateOf(true, true, true, 31.0) == G::Gate::HoldStale && G::GateOf(true, false, true, 0.0) == G::Gate::HoldStale,
                   "r112o: no target: free; framed and fresh: taken; not framed: held; an old or no observation: held");
            Expect(!G::CaptureHeld(nullptr) && !G::CaptureHeld("") && !G::CaptureHeld("no-such-trigger-file.r112o"),
                   "r112o: without BB_TEST_GOTO or a waiting trigger file the capture is never held");
        }
"""

# ---- README.md ----------------------------------------------------------------------------------------------------------
R1 = r"""The request goes to the game thread, which moves the living hunter with the engine's own co-op bring-to-host call (`MoveBodyToSafeSpot`) after checking the warp's entry bytes; 120 frames later"""
R1N = r"""The request goes to the game thread, which WALKS the living hunter there in hops of `BB_TEST_GOTO_HOP` metres (r112o; one warp 37 m away had left him falling through ground that was drawn but had no floor yet) with the engine's own co-op bring-to-host call (`MoveBodyToSafeSpot`, its entry bytes checked first), each hop landing 2 m over the last place he was seen standing still and the next one planned only after his y has stayed within 0.03 m for 8 frames (the floor there is loaded); a hunter that ends 6 m or more below that place is put back, the hop is halved (not under 1 m) and after 4 such failures the walk gives up and says so; once the walk is done, 120 frames later"""

R2 = r"""| `BB_WIND_HANG_PROOF` |"""
R2P = r"""| `BB_TEST_GOTO_HOP` | TOOL (r112o; part of `BB_TEST_GOTO`, test-tools branch; 1 to 15, default `5`; text that is no number gives the default). The length (horizontal metres) of one hop of the hunter's walk to the goal. A shorter hop is safer where the floor loads close to the hunter only; a longer one is quicker. Also from r112o, with `BB_TEST_GOTO` on and a target locked, the engine's capture trigger file (`BB_PRESENT_DUMP_TRIGGER`, what the slot runner's `capture:` writes) is HELD while the target is not framed: the run has not arrived, or the target's screen box is not in front of the camera with its middle inside the middle 80 percent of the picture, at least 6 px, within 12 m (3 D), or the last observation is older than 30 s. Log: `GLINT-PROOF hang goto (r112o)` lines: `walk begun`, each `hop N` and `hop done` (the hunter's y stood still: the floor there is loaded), `hop failed` and `walk done` or `walk gave up`; per observation `framing fN: FRAMED|NOT FRAMED: why (camera to target, screen box); captures taken N, refused polls M`; per capture `capture taken: camera to target D m, screen box ...` or `capture refused: not framed (why)` (every 2 s at most; the runner times the trigger out after 20 s and notes it). Nothing is held when no target is locked (a place with no pushed hanging mesh). Off: one test of a static bool before any file is touched. |
"""

EDITS = {
TH: [
('ins', H1, "", H1N),
('ins', H2, H2P, ""),
('rep', H3, "", H3N),
('rep', H4, "", H4N),
('rep', H5, "", H5N),
('rep', H6, "", H6N),
],
OF: [
('rep', O1, "", O1N),
('rep', O2, "", O2N),
],
UP: [
('ins', U0, "", U0N),
('rep', U1, "", U1N),
('rep', U2, "", U2N),
],
NT: [
('rep', T2, "", T2N),
('rep', T3, "", T3N),
('ins', T1, T1P, ""),
],
RM: [
('rep', R1, "", R1N),
('ins', R2, R2P, ""),
],
}


ORDER = (TH, OF, UP, NT, RM)
NEW_ORDER = (TW,)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def new_state(path):
    """clean: the file is absent; applied: it is there with the patch's text; anything else refuses."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if have != NEW_FILES[path]:
        raise SystemExit("REFUSED %s: the file exists and is not this patch's" % path)
    return "applied"


def balance(text):
    """(braces, parens, brackets) net of a C++ text without comments, strings and char literals."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])'", "' '", text)
    return (text.count("{") - text.count("}"), text.count("(") - text.count(")"),
            text.count("[") - text.count("]"))


def text_checks(texts, olds):
    """The ties a compiler cannot check."""
    th, of_, up, nt = texts[TH], texts[OF], texts[UP], texts[NT]
    tw = NEW_FILES[TW]
    for path in ORDER:
        if path == RM:
            continue
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    # the new file and the replaced function balance on their own (the file-level check above is net of both)
    if balance(tw) != (0, 0, 0):
        raise SystemExit("text check: %s: braces, parens or brackets do not balance: %r" % (TW, balance(tw)))
    if balance(O2) != (0, 0, 0) or balance(O2N) != (0, 0, 0):
        raise SystemExit("text check: the old or the new TestGotoTick does not balance")
    for text in (tw,):
        if "\t" in text:
            raise SystemExit("text check: a tab in the new file")
    for needle in ("class Walker {", "inline Walker& TheWalker()", "inline bool CaptureHeld(", "inline Gate GateOf(",
                   "inline void PublishFraming(", "inline float ParseHop(", "std::atomic<bool> g_walking",
                   "void WaitTick(", "void PlanHop(", "void Fail(", "void Ask("):
        if needle not in tw:
            raise SystemExit("text check: %s missing in the walk header" % needle)
    # use after declaration in the walk header
    for first, second in (("inline float ParseHop(", "inline float HopOnce("), ("struct WalkParams {", "class Walker {"),
                          ("struct WalkOut {", "inline void Put("), ("inline void Put(", "class Walker {"),
                          ("class Walker {", "inline Walker& TheWalker()"), ("struct Shared {", "inline void PublishFraming("),
                          ("inline Gate GateOf(", "inline bool CaptureHeld("), ("inline void PublishFraming(", "inline bool CaptureHeld("),
                          ("enum class Gate", "inline Gate GateOf(")):
        if tw.index(first) > tw.index(second):
            raise SystemExit("text check: %s must precede %s in the walk header" % (first, second))
    # Walker's private enum is declared before the first member that uses it
    if tw.index("enum class St : std::uint8_t") > tw.index("[[nodiscard]] bool Active() const"):
        raise SystemExit("text check: St must be declared before Active()")
    for needle in ("#include \"bbport_test_goto_walk.h\"", "FramingOf(", "PublishFraming(s.locked,", "say(framing.line);",
                   "!Walking()", "s.phase = Phase::GaveUp; // bbport (r112o", "FallGuard"):
        if needle not in th:
            raise SystemExit("text check: %s missing in the render side header" % needle)
    if th.index("inline Framing FramingOf(") > th.index("inline std::vector<std::string> ObserveWith("):
        raise SystemExit("text check: FramingOf must precede ObserveWith")
    if th.index("struct Reading {") > th.index("inline Framing FramingOf(") or th.index("inline const char* PhaseName(") > th.index("inline Framing FramingOf("):
        raise SystemExit("text check: FramingOf uses Reading and PhaseName before their definitions")
    if th.index("#include \"bbport_test_goto_walk.h\"") > th.index("namespace BbTestGoto {"):
        raise SystemExit("text check: the walk header must be included before the namespace")
    if th.count("refused by the game thread") != 1 or "s.tries >= TriesMost ? Phase::GaveUp : Phase::Wait;\n                std::snprintf(buf, sizeof(buf), \"GLINT-PROOF hang goto (r112n): warp %u refused" in th:
        raise SystemExit("text check: the refusal must be final")
    for needle in ("void TestGotoTick() {", "BbTestGoto::TheWalker()", "walker.Tick(at)", "MoveBodyToSafeSpot(local, out.pos, facing);",
                   "std::memcmp(g_image + kWarp, kWarpEntry, sizeof kWarpEntry)", "#include \"bbport_test_goto_walk.h\"",
                   "BbTestGoto::SetWalking(true);", "BbTestGoto::SetWalking(false);"):
        if needle not in of_:
            raise SystemExit("text check: %s missing in the engine side" % needle)
    if of_.count("void TestGotoTick() {") != 1 or "bbport_test_goto.h\" // bbport (r112n" in of_:
        raise SystemExit("text check: TestGotoTick once; the r112n include replaced by the walk header (which includes it)")
    if of_.index("void MoveBodyToSafeSpot(") > of_.index("void TestGotoTick() {") or \
            of_.index("bool Loading() {") > of_.index("void TestGotoTick() {") or \
            of_.index("float Facing(std::uint64_t chr) {") > of_.index("void TestGotoTick() {") or \
            of_.index("bool Position(std::uint64_t chr, float out[3]) {") > of_.index("void TestGotoTick() {"):
        raise SystemExit("text check: TestGotoTick uses a name before its definition")
    if up.count("BbTestGoto::CaptureHeld(dump)") != 2 or up.count("#include \"bbport_test_goto_walk.h\"") != 1:
        raise SystemExit("text check: the capture gate belongs in the two trigger consumers")
    if "the hop walk against a floor that exists only near where the hunter has stood" not in nt or "G::FramingOf(fk, fs, fr, 900)" not in nt:
        raise SystemExit("text check: the tests are missing")
    # the test's sums: 8 hops of 5 m over 36.94 m
    hx, hz = -33.55 - (-48.89), 107.65 - 74.04
    d = (hx * hx + hz * hz) ** 0.5
    if not (35.0 < d < 40.0) or int(d // 5.0) + 1 != 8:
        raise SystemExit("text check: the test's 8 hops do not match the distance %.2f" % d)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112O_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == TH and "FramingOf(" not in cur and "#include \"bbport_test_goto.h\"" not in cur:
            raise SystemExit("REFUSED: r112n_hang-teleport-camera must be applied")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = [(path, new_state(path)) for path in NEW_ORDER]
    states = {p[5] for p in plan} | {n[1] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % n for n in news))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    olds = {p[0]: p[4] for p in plan}
    if cmd == "check":
        if state == "applied":
            text_checks(olds, {p[0]: revert_edits(p[4], p[1]) for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), olds)
            print("not applied; would apply (%d files edited, %d edits, %d new file; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_ORDER)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts, olds)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112otmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path in NEW_ORDER:
            open(os.path.join(ROOT, path), "wb").write(NEW_FILES[path].replace("\n", "\r\n").encode("utf-8"))
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112otmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_ORDER:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
