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
        return goal_changed || !pending_lines.empty() || session.Busy();
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
        if (goal_changed) {
            goal_changed = false;
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
    }
};

[[nodiscard]] inline Driver& TheDriver() {
    static Driver d;
    return d;
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
