// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r120_test-camera-lookat, TOOL; test-tools branch only): the render side of BB_TEST_CAMERA and BB_TEST_WORLD_AT
// (bbport_test_camera.h has the knob's text, the arithmetic, the controller and the hold). Both are LIVE knobs (BbLiveKnobs: set:
// and unset: in a slot job, or the environment).
//   Wanted()   once a frame: has the text of either knob changed (the knobs file's generation moved), is a camera being held?
//   Tick()     once a frame, from the rasterizer's frame end: starts, steps and ends the Session, hands the hold's command to the
//              game thread, posts the hunter's walk (BbTestGoto's mailbox), publishes the capture gate.
//   the world-at mailbox (WorldJob, TakeWorldJob, PublishCentre): what vk_test_world_at.cpp reads and answers. BB_TEST_WORLD_AT's
//              pixels are read once each time the knob's text changes (unset, then set again, reads them again); a Session that
//              starts with lookat:centre asks for the picture's middle and four pixels around it.

#include <array>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#include "bbport_live_knobs.h"
#include "bbport_test_camera.h"

namespace BbTestCamera {

/// What one world-at read has to do: the pixels (BB_TEST_WORLD_AT's, then the centre's five when `centre`).
struct WorldJob {
    std::array<Pixel, kPixelsMost + kCentreCount> px{};
    unsigned n = 0;
    unsigned user = 0;           ///< the first `user` pixels are BB_TEST_WORLD_AT's
    bool centre = false;         ///< pixels user .. user + 4 are the centre read's (the middle first)
    std::uint32_t centre_serial = 0;
};

struct Shared {
    std::mutex m;
    PixelList user;
    std::uint32_t user_serial = 0, user_taken = 0;
    std::uint32_t centre_serial = 0, centre_taken = 0, centre_done = 0;
    bool centre_ok = false;
    float centre[3] = {};
    char centre_why[120] = {};
    bool kept_ok = false;
    float kept[3] = {};
    bool kept_yaw_ok = false;
    float kept_yaw = 0.0f;
};

[[nodiscard]] inline Shared& SharedState() {
    static Shared s;
    return s;
}

inline std::atomic<bool> g_world_wanted{false};

/// The world-at pass: a read is wanted (one relaxed load).
[[nodiscard]] inline bool WorldWanted() {
    return g_world_wanted.load(std::memory_order_relaxed);
}

/// The world-at pass takes what is wanted (false: nothing).
[[nodiscard]] inline bool TakeWorldJob(WorldJob* out) {
    std::lock_guard lock(SharedState().m);
    Shared& s = SharedState();
    WorldJob job;
    if (s.user_serial != s.user_taken) {
        s.user_taken = s.user_serial;
        for (unsigned i = 0; i < s.user.n && job.n < job.px.size(); ++i) {
            job.px[job.n++] = s.user.px[i];
        }
        job.user = job.n;
    }
    if (s.centre_serial != s.centre_taken) {
        s.centre_taken = s.centre_serial;
        job.centre = true;
        job.centre_serial = s.centre_serial;
        const int cx = static_cast<int>(kPictureW / 2), cy = static_cast<int>(kPictureH / 2);
        const int dx = static_cast<int>(kPictureW / 16), dy = static_cast<int>(kPictureH / 16);
        const Pixel five[kCentreCount] = {{cx, cy},          {cx - dx, cy},     {cx + dx, cy},     {cx, cy - dy},     {cx, cy + dy},    {cx, cy - 2 * dy},
                                          {cx, cy - 3 * dy}, {cx - 2 * dx, cy}, {cx + 2 * dx, cy}, {cx, cy - 4 * dy}, {cx, cy + 2 * dy}}; // r120c: 11, the middle first
        for (const Pixel& p : five) {
            if (job.n < job.px.size()) {
                job.px[job.n++] = p;
            }
        }
    }
    g_world_wanted.store(false, std::memory_order_relaxed);
    *out = job;
    return job.n > 0;
}

/// The world-at pass answers a centre read.
inline void PublishCentre(std::uint32_t serial, bool ok, const float world[3], const char* why) {
    std::lock_guard lock(SharedState().m);
    Shared& s = SharedState();
    s.centre_done = serial;
    s.centre_ok = ok;
    if (ok) {
        std::memcpy(s.centre, world, sizeof s.centre);
    }
    std::snprintf(s.centre_why, sizeof s.centre_why, "%s", why != nullptr ? why : "");
}

/// What one render frame knows that the Session needs besides the knobs.
struct TickIn {
    std::uint64_t frame = 0;
    bool matrices_ok = false;
    float view[12] = {}, inv_view[12] = {}, proj[4] = {};
    float width = 0.0f, height = 0.0f;
    bool hunter_ok = false;
    float hunter[3] = {};
    bool hang_ok = false;            ///< BB_TEST_GOTO=hang has locked its target
    float hang_centre[3] = {};
    bool hang_box_ok = false;
    float hang_box[6] = {};
};

/// Facts from the R120 render-thread driver; this does not identify a guest object or a ground draw.
struct SewerHoldEpoch {
    std::uint64_t epoch = 0, begin_frame = 0, ready_frame = 0;
    std::array<float, 3> target{}, hunter{};
    Session::WalkEvidence walks{};
};

struct SewerEpochReceipt {
    SewerHoldEpoch original{}, alternate{};
    std::uint64_t original_release_frame = 0, sample_frame = 0;
    std::array<float, 3> release_hunter{}, hunter{}, eye{}, forward{};
};

class SewerEpochObserver {
public:
    [[nodiscard]] bool NeedsReleasedSample() const { return phase == Phase::Released; }

    void Advance(const TickIn& t) {
        if (phase == Phase::Idle || phase == Phase::Original) return;
        if (t.frame <= last_frame || t.frame - last_frame != 1 || !SameSample(t) ||
            !MailboxIdle() || (phase == Phase::Released && t.frame - receipt.original_release_frame > 120) ||
            (phase == Phase::Alternate && !receipt.alternate.ready_frame &&
             t.frame - receipt.alternate.begin_frame > 240)) {
            phase = Phase::Idle;
        }
        last_frame = t.frame;
    }

    /// Called before the old session is released. Only an explicit off transition can bridge the holds.
    void Change(const TickIn& t, const Goal& goal, const Session& previous, bool hold_on) {
        if (phase == Phase::OriginalReady && goal.kind == Kind::Off && !goal.bad &&
            previous.GetPhase() == Session::Phase::Ready && hold_on) {
            receipt.original_release_frame = t.frame;
            std::copy_n(t.hunter, 3, receipt.release_hunter.begin());
            phase = Phase::Released;
        } else if (phase == Phase::Released && ExactGoal(goal, Kind::Aim, kAlternate)) {
            receipt.alternate = {++epoch, t.frame};
            phase = Phase::Alternate;
        } else {
            phase = Phase::Idle;
            if (ExactGoal(goal, Kind::LookAt, kOriginal) && goal.dist_set && goal.dist == 7.f &&
                goal.yaw_set && goal.yaw == 147.f && goal.elev == 25.f) {
                receipt = {};
                receipt.original = {++epoch, t.frame};
                phase = Phase::Original;
            }
        }
    }

    /// Called after the stock session tick, optional post and capture-gate publication.
    void Observe(const TickIn& t, const Session& session, const Session::Out& o,
                 std::vector<std::string>& lines) {
        if (phase == Phase::Idle || phase == Phase::Released) return;
        const auto walks = session.ReadWalkEvidence();
        const bool ready = session.GetPhase() == Session::Phase::Ready &&
                           o.hold && o.engaged && o.cmd_valid && o.framed && !o.failed && HoldWanted();
        if (phase == Phase::Original) {
            if (o.failed || walks.posted > 2) {
                phase = Phase::Idle;
            } else if (ready && walks.posted == 2 && walks.marked_ok == 2 &&
                       walks.marked_sequence[0] && walks.marked_sequence[1] > walks.marked_sequence[0] &&
                       t.frame > receipt.original.begin_frame && ValidHunter(t)) {
                receipt.original.walks = walks;
                if (!MailboxIdle()) return;
                FillReady(receipt.original, t, session);
                last_frame = t.frame;
                phase = Phase::OriginalReady;
            }
            return;
        }
        if (phase == Phase::OriginalReady) {
            if (!ready || walks.posted != 2 || walks.marked_ok != 2) phase = Phase::Idle;
            return;
        }
        const bool current_view = t.matrices_ok && FiniteView(t);
        if (o.failed || walks.posted || walks.marked_ok ||
            (receipt.alternate.ready_frame && (!ready || !current_view))) {
            phase = Phase::Idle;
            return;
        }
        if (!ready || !current_view) return;
        if (!receipt.alternate.ready_frame) {
            FillReady(receipt.alternate, t, session);
            Say(lines, "[sewer-r120-epoch] original=%llu original_begin=%llu original_ready=%llu original_release=%llu "
                       "original_posted=%u original_marked=%u original_seq=%u,%u "
                       "alternate=%llu alternate_begin=%llu alternate_ready=%llu alternate_posted=%u alternate_marked=%u "
                       "hunter=%.9g,%.9g,%.9g",
                static_cast<unsigned long long>(receipt.original.epoch),
                static_cast<unsigned long long>(receipt.original.begin_frame),
                static_cast<unsigned long long>(receipt.original.ready_frame),
                static_cast<unsigned long long>(receipt.original_release_frame),
                receipt.original.walks.posted, receipt.original.walks.marked_ok,
                receipt.original.walks.marked_sequence[0], receipt.original.walks.marked_sequence[1],
                static_cast<unsigned long long>(receipt.alternate.epoch),
                static_cast<unsigned long long>(receipt.alternate.begin_frame),
                static_cast<unsigned long long>(receipt.alternate.ready_frame), walks.posted, walks.marked_ok,
                double(t.hunter[0]), double(t.hunter[1]), double(t.hunter[2]));
        }
        receipt.sample_frame = t.frame;
        std::copy_n(t.hunter, 3, receipt.hunter.begin());
        receipt.eye = {t.inv_view[3], t.inv_view[7], t.inv_view[11]};
        std::copy_n(t.view + 8, 3, receipt.forward.begin());
    }

    [[nodiscard]] bool Read(std::uint64_t frame, SewerEpochReceipt& out) const {
        if (phase != Phase::Alternate || !receipt.alternate.ready_frame || receipt.sample_frame != frame ||
            last_frame != frame || !HoldWanted() || !MailboxIdle()) return false;
        out = receipt;
        return true;
    }

private:
    enum class Phase { Idle, Original, OriginalReady, Released, Alternate };
    static constexpr std::array<float, 3> kOriginal{17.275f, -29.597f, 102.718f};
    static constexpr std::array<float, 3> kAlternate{16.765f, -29.525f, 101.825f};

    static bool ExactGoal(const Goal& goal, Kind kind, const std::array<float, 3>& target) {
        return goal.kind == kind && !goal.bad && !goal.centre && !goal.kept &&
               !goal.from_hang && !goal.stepback && std::equal(target.begin(), target.end(), goal.point);
    }
    static bool ValidHunter(const TickIn& t) {
        return t.hunter_ok && BbTestGoto::Finite3(t.hunter);
    }
    static bool FiniteView(const TickIn& t) {
        const float eye[]{t.inv_view[3], t.inv_view[7], t.inv_view[11]};
        return BbTestGoto::Finite3(eye) && BbTestGoto::Finite3(t.view + 8);
    }
    bool SameSample(const TickIn& t) const {
        return ValidHunter(t) && Dist3(t.hunter, receipt.original.hunter.data()) <= .01f;
    }
    bool MailboxIdle() const {
        const auto done = BbTestGoto::g_done_seq.load(std::memory_order_acquire);
        return !BbTestGoto::Pending() && !BbTestGoto::Walking() &&
               done == receipt.original.walks.marked_sequence[1] &&
               BbTestGoto::g_done_ok.load(std::memory_order_relaxed);
    }
    static void FillReady(SewerHoldEpoch& stamp, const TickIn& t, const Session& session) {
        stamp.ready_frame = t.frame;
        std::copy_n(session.Target(), 3, stamp.target.begin());
        std::copy_n(t.hunter, 3, stamp.hunter.begin());
    }

    SewerEpochReceipt receipt{};
    Phase phase = Phase::Idle;
    std::uint64_t epoch = 0, last_frame = 0;
};

struct Driver {
    std::uint32_t generation = 0xFFFFFFFFu; ///< the knobs file's generation last read
    char camera_text[LIVE_KNOB_VALUE_MAX] = {};
    char world_text[LIVE_KNOB_VALUE_MAX] = {};
    Goal goal;
    bool goal_changed = false;
    std::vector<std::string> pending_lines;
    Session session;
    bool hold_on = false;
    std::uint64_t updates_base = 0;
    std::uint32_t centre_asked = 0;
    SewerEpochObserver sewer_epoch;

    /// The two knobs' texts as the file or the environment gives them now (null: not set).
    void Refresh(const char* camera, const char* world) {
        const char* c = camera != nullptr ? camera : "";
        const char* w = world != nullptr ? world : "";
        if (std::strcmp(c, camera_text) != 0) {
            std::snprintf(camera_text, sizeof camera_text, "%s", c);
            goal = ParseGoal(c);
            goal_changed = true;
        }
        if (std::strcmp(w, world_text) != 0) {
            std::snprintf(world_text, sizeof world_text, "%s", w);
            const PixelList list = ParsePixels(w);
            if (list.bad) {
                Say(pending_lines, "BB_TEST_WORLD_AT=%s is not understood: whole numbers in pairs, x,y;x,y, in a 1920x1080 picture", w);
            } else if (list.n > 0) {
                std::lock_guard lock(SharedState().m);
                SharedState().user = list;
                ++SharedState().user_serial;
                g_world_wanted.store(true, std::memory_order_relaxed);
            }
        }
    }

    [[nodiscard]] bool Needed() const {
        return goal_changed || !pending_lines.empty() || session.Busy() ||
               (SewerEpochEnabled() && sewer_epoch.NeedsReleasedSample());
    }

    void StopHold() {
        g_cmd_valid.store(false, std::memory_order_release);
        g_hold_want.store(false, std::memory_order_relaxed);
        hold_on = false;
    }

    /// One frame: the lines to print are appended to `lines`.
    void Tick(const TickIn& t, std::vector<std::string>& lines) {
        for (const std::string& l : pending_lines) {
            lines.push_back(l);
        }
        pending_lines.clear();
        const bool observe_epoch = SewerEpochEnabled();
        if (observe_epoch) sewer_epoch.Advance(t);
        if (goal_changed) {
            goal_changed = false;
            if (observe_epoch) sewer_epoch.Change(t, goal, session, hold_on);
            session.Release(lines, goal.kind == Kind::Off ? "BB_TEST_CAMERA unset" : "BB_TEST_CAMERA changed");
            StopHold();
            PublishGate(false, false, std::string(), std::string());
            centre_asked = 0;
            if (goal.bad) {
                Say(lines, "BB_TEST_CAMERA=%s is not understood: %s (lookat:x,y,z[,dist,yaw,elev], lookat:centre, lookat:kept, "
                           "aim:x,y,z, aim:centre, aim:kept, aim:hang, pose:x,y,z,yaw,pitch, hang[,dist,yaw,elev])",
                    camera_text, goal.why);
            } else if (goal.kind != Kind::Off) {
                session.Begin(goal, t.frame, camera_text, lines);
            }
        }
        if (!session.Busy()) {
            return;
        }
        Session::Frame f;
        f.frame = t.frame;
        f.cam_ok = t.matrices_ok;
        if (t.matrices_ok) {
            f.cam[0] = t.inv_view[3];
            f.cam[1] = t.inv_view[7];
            f.cam[2] = t.inv_view[11];
            f.fwd[0] = t.view[8];
            f.fwd[1] = t.view[9];
            f.fwd[2] = t.view[10];
            f.cam_ok = BbTestGoto::Finite3(f.cam) && BbTestGoto::Finite3(f.fwd);
            f.view_ok = true;
            std::memcpy(f.view, t.view, sizeof f.view);
            std::memcpy(f.proj, t.proj, sizeof f.proj);
            f.width = t.width;
            f.height = t.height;
        }
        f.hunter_ok = t.hunter_ok;
        std::memcpy(f.hunter, t.hunter, sizeof f.hunter);
        if (hold_on) {
            const std::uint64_t updates = g_updates.load(std::memory_order_acquire);
            f.seen_ok = updates > updates_base;
            f.seen_yaw = g_seen_yaw.load(std::memory_order_relaxed);
            f.seen_pitch = g_seen_pitch.load(std::memory_order_relaxed);
            f.seen_lowest = g_seen_lowest.load(std::memory_order_relaxed);
            f.seen_highest = g_seen_highest.load(std::memory_order_relaxed);
        }
        f.walking = BbTestGoto::Walking();
        f.pending = BbTestGoto::Pending();
        f.done_seq = BbTestGoto::g_done_seq.load(std::memory_order_acquire);
        f.done_ok = BbTestGoto::g_done_ok.load(std::memory_order_relaxed);
        {
            std::lock_guard lock(SharedState().m);
            const Shared& s = SharedState();
            f.kept_ok = s.kept_ok;
            std::memcpy(f.kept, s.kept, sizeof f.kept);
            f.kept_yaw_ok = s.kept_yaw_ok;
            f.kept_yaw = s.kept_yaw;
            if (centre_asked != 0 && s.centre_done == centre_asked) {
                f.centre_ready = s.centre_ok;
                f.centre_failed = !s.centre_ok;
                std::memcpy(f.centre, s.centre, sizeof f.centre);
                f.centre_why = s.centre_why;
            }
        }
        f.hang_ok = t.hang_ok;
        std::memcpy(f.hang_centre, t.hang_centre, sizeof f.hang_centre);
        f.hang_box_ok = t.hang_box_ok;
        std::memcpy(f.hang_box, t.hang_box, sizeof f.hang_box);
        Session::Out o = session.Tick(f);
        for (const std::string& l : o.lines) {
            lines.push_back(l);
        }
        if (o.want_centre && centre_asked == 0) {
            std::lock_guard lock(SharedState().m);
            centre_asked = ++SharedState().centre_serial;
            g_world_wanted.store(true, std::memory_order_relaxed);
        }
        if (o.remember) {
            std::lock_guard lock(SharedState().m);
            SharedState().kept_ok = true;
            std::memcpy(SharedState().kept, o.remember_at, sizeof SharedState().kept);
        }
        if (o.remember_yaw) {
            std::lock_guard lock(SharedState().m);
            SharedState().kept_yaw_ok = true;
            SharedState().kept_yaw = o.remember_yaw_deg;
        }
        if (o.hold && !hold_on) { // the first frame of a hold: what the game thread publishes from now on counts
            updates_base = g_updates.load(std::memory_order_acquire);
            g_hold_want.store(true, std::memory_order_relaxed);
            hold_on = true;
        }
        if (o.hold) {
            g_cmd_yaw.store(o.cmd_yaw, std::memory_order_relaxed);
            g_cmd_pitch.store(o.cmd_pitch, std::memory_order_relaxed);
            g_cmd_valid.store(o.cmd_valid, std::memory_order_release);
        } else {
            StopHold();
        }
        if (o.post) {
            session.Posted(BbTestGoto::Post(o.stand), t.frame);
        }
        PublishGate(o.engaged, o.framed, o.text, o.why, o.failed);
        if (observe_epoch) sewer_epoch.Observe(t, session, o, lines);
    }
};

[[nodiscard]] inline Driver& TheDriver() {
    static Driver d;
    return d;
}

/// Render thread only. Match the exact R120 frame-end source serial, then independently qualify any later draw.
[[nodiscard]] inline bool ReadSewerEpoch(std::uint64_t source_frame, SewerEpochReceipt& out) {
    if (!SewerEpochEnabled()) return false;
    const Driver& d = TheDriver();
    return !d.goal_changed && d.sewer_epoch.Read(source_frame, out);
}

/// Once a frame: true when Tick has something to do. Reads the two knobs again when the knobs file's generation moved (the
/// first call reads them once, from the environment when there is no file).
[[nodiscard]] inline bool Wanted() {
    Driver& d = TheDriver();
    const std::uint32_t gen = BbLiveKnobs::Generation();
    if (gen != d.generation) {
        d.generation = gen;
        const BbLiveKnobs::Text camera = BbLiveKnobs::Lookup("BB_TEST_CAMERA");
        const BbLiveKnobs::Text world = BbLiveKnobs::Lookup("BB_TEST_WORLD_AT");
        d.Refresh(camera.Get(), world.Get());
    }
    return d.Needed();
}

} // namespace BbTestCamera
