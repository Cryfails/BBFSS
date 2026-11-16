# r112n_hang-teleport-camera: on top of r112m_hang-close-proof (r112l ... r112 all applied in the tree, build 58) and r86l (build 59).
# GRADES: (1) BB_TEST_GOTO is a TOOL (a test aid: it goes to dev/test-tools, never a feature branch); (2) the moving reasons are
# part of r112's own log (FEATURE branch, log text only, nothing changes when BB_WIND_HANG is off or the FIND lines are off).
#
# THE EVIDENCE (b58: slot_b58_result.txt, b58_s4.log graveyard, b58_reports.txt hang section)
#  - r112m fixed what the log says about the lanterns: lantern A (0.21 m) is now PUSHED at scale 0.17, its bottom 0.040-0.069 m, B
#    0.047-0.080 m, 0 'too tall' lines. But the r112m-grave walk went the wrong way (it ended near x -41.9 z 87), the 97f2d384
#    lanterns stayed 25-40 m away and left the view; the lantern in view was e859b6d9 (1.32 m on a post, 2.2 m away), 'held as
#    moving by r112's book' with 'keys span not read': so the gain-1 pair and the cyan proof showed nothing on a lantern.
#  - e859b6d9, read in the b58 log (b58_s4.log lines 1324-1327 and 1795-1800): stream 471d9d50 is drawn at 4 places (a, E, F, H:
#    x -41.9 z 87.0, -41.1 85.8, -37.6 79.1, -34.0 81.4), the one at 2.2 m on route O (static, book candidate) and the others on
#    route S (SKINNED, idx 4680, 1907 verts). 'Held as moving' is r112's book (BbWindHang::Entry::moving); it is set in 4 places
#    only (Book::Note twice: a palette it draws with could not be read, or its palette bytes changed; the GPU judge's Moved state;
#    r112h's rule) and no field said which. 'keys span not read' is by design: a held stream's keys are never measured (Measure
#    stops at the moving verdict). A stream drawn at several places with other palettes at one address is the case Note's second
#    set (bytes changed) fits; THAT IS NOT PROVEN: this patch makes the log say which of the four it is (see (2)).
#
# WHAT THIS CHANGES
#  (1) BB_TEST_GOTO (TOOL): the camera 3-5 m from a PUSHED lantern, with no walk.
#      - the test tools have NO teleport (scout mode is on its own branch in <tree2>, not in this tree; it travels to lamps
#        by the load call, not to a position). What the engine has: OnlineFixes::MoveBodyToSafeSpot (the call that brings a co-op
#        guest to the host's side: warp entry kWarp 0x13cb4f0 checked against 1.09's bytes, then the body's own move virtual), the
#        hunter's physics position (world_player_position) and the camera's position and view (the ray traced scene's camera and
#        camera_motion's matrices, the hang survey's BoxSet). The patch joins them:
#          bbport_test_goto.h (new): the knobs, the mailbox between the render thread and the game thread, and the plan's arithmetic;
#          bbport_test_goto_hang.h (new): Observe, the render side's state machine and its report lines;
#          online_fixes.cpp / .h: TestGotoTick (the game thread moves the living hunter; one relaxed load a frame when off);
#          features.cpp: ONE line, the call, after OnlineFixes::Tick() in OnFrame;
#          vk_rasterizer_effects.cpp: one include, and ONE block at the end of WindHangFindRefresh (the hang survey's own function).
#      - Observe, every time the box set is read (every 60 frames while hang draws come): waits for a pushed candidate (the survey's
#        own class, BB_TEST_GOTO_VS narrows it to one vertex shader hash), locks its box, plans where the hunter must stand so that
#        the camera, which keeps its heading and its offset from the hunter, ends BB_TEST_GOTO_DIST m (3 D, default 4.9) from the mesh
#        with the mesh straight ahead (and no steeper a look-up than BB_TEST_GOTO_ELEV, default 55 degrees: a lantern 6.3 m up
#        needs 68 degrees at 4.9 m, which the game's camera may not give; the stand point is then 3.2 m away horizontally, 5.5 m in
#        3 D), posts it, waits for the game thread, waits 120 frames, READS THE CAMERA AGAIN and, if it is not there, plans
#        another move (4 at most). BB_TEST_GOTO=x,y,z puts the hunter at a world position instead.
#      - the report, one line per observation, numbers first, prefix 'GLINT-PROOF hang goto (r112n)' (the slot runner keeps all of
#        these lines uncut, the first 24 and the last 24 of a run): camera to target 3 D and horizontal and height, target elevation
#        and the camera's pitch (how much more look-up the pad must give: pad ry=0), bearing off, the mesh's screen box and whether
#        its middle is IN VIEW, the hunter, the target, the warps. So every capture has the camera-to-lantern distance and the
#        lantern's screen box of the observation before it (<= 60 frames old; the camera holds still between captures).
#  (2) WHY e859b6d9 IS HELD AS MOVING: BbWindHang::Entry gets why_moving (1 a palette could not be read, 2 its bytes changed, 3 the
#      GPU judge, 4 r112h's rule) and moved_after (the frames counted, or the rule's number), set where `moving` is set (Book::Note x2,
#      the Moved case in WindHangWord, WindHangActorsClear) and only when it was not set before (the FIRST reason). The candidate
#      line says it in words after 'held as moving by r112's book:' and says 'keys span not read (held)'; it also names the
#      mesh's middle and the ground under it ('6.29 m up (middle x y z, ground y y)'), which the survey's lines lacked.
#
# Shared lines touched: vk_rasterizer_effects.cpp: the include after r112h's, the two moving setters (WindHangWord, WindHangActorsClear:
# hang functions), the end of WindHangFindRefresh. NOT touched: the pick (twigs and glass), the sway files, lift_stage.cpp, vk_rasterizer.h,
# vk_rasterizer.cpp. features.cpp, online_fixes.cpp and .h: the engine side of the tool.
#
# Off: BB_TEST_GOTO unset or not understood: BbTestGoto::On() is a static bool (tested once every 60 frames, only with the hang
# survey's draws); TestGotoTick returns at one relaxed load of a false atomic (the mailbox flag; the game thread, once a frame);
# Observe returns at its first line. The moving reasons are two small fields of an entry and a few lines of log with BB_WIND_HANG_FIND=1.
# Cost on: Observe walks the scene's boxes (about 400, a hash lookup each) until the target is locked, then three vector reads and
# a log line every 60 frames. GPU: none. Memory: a Session of about 120 bytes.
#
# Use: python -I -X utf8 r112n_hang-teleport-camera.py check | apply | revert
# Root: R112N_ROOT, else <tree>. CRLF kept (the new files take CRLF). apply backs the originals up in r112n_backup next to
# this script; revert takes out exactly what apply put in and removes the two new files. Needs r112m applied (the anchors are its texts).
import os, re, sys

ROOT = os.environ.get("R112N_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112n_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
SH = "engine/gpu/shim/"
NF = SH + "bbport_wind_hang_find.h"
NH = SH + "bbport_wind_hang.h"
TG = SH + "bbport_test_goto.h"
TH = SH + "bbport_test_goto_hang.h"
OF = SH + "engine/online_fixes.cpp"
OH = SH + "engine/online_fixes.h"
FE = SH + "engine/features.cpp"
NT = "engine/tests/test_wind_hang_find.cpp"
RM = "README.md"

# ---- new files ---------------------------------------------------------------------------------------
NEW_FILES = {
    TG: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112n_hang-teleport-camera, TOOL; goes to the test-tools branch, never a feature branch): BB_TEST_GOTO puts the
// hunter, and so the follow camera, at a place of the test's choosing, without a walk. For the hang tests (a lantern that
// hangs 6 m up and is 25 m away from where the save starts); the render side (bbport_test_goto_hang.h) chooses the place
// from the scene's pushed hanging meshes, the game thread (OnlineFixes::TestGotoTick) moves the hunter with the call the
// engine already uses to bring a co-op guest to the host (MoveBodyToSafeSpot). This header has no game and no renderer
// code: the knobs, the mailbox between the two threads and the plan's arithmetic.
//
//   BB_TEST_GOTO=hang       the nearest PUSHED hanging mesh of the scene (BB_TEST_GOTO_VS=<8 hex digits> narrows it to one
//                           vertex shader hash); the hunter is put where the camera, which keeps its direction, stands
//                           BB_TEST_GOTO_DIST metres (3 D, 1 to 20, default 4.9) from the mesh's middle and looks at it
//                           along the ground (the pad's right stick up, ry=0, tilts it up the rest of the way); a mesh hung
//                           high would then need a steeper look-up than the game's camera gives, so the camera is put no
//                           closer (horizontally) than the mesh's height over it divided by tan(BB_TEST_GOTO_ELEV), 20 to
//                           80 degrees, default 55: the 3 D distance is then more than BB_TEST_GOTO_DIST for a high mesh
//   BB_TEST_GOTO=x,y,z      the hunter is put at the world position x,y,z (y up, the game's physics frame: the scene's)
//
// The two threads share only the mailbox: Post (render thread, once a try), Take and Done (game thread).

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>

namespace BbTestGoto {

inline constexpr float DistDefault = 4.9f, DistLeast = 1.0f, DistMost = 20.0f; ///< camera to target (3 D, m)
inline constexpr float ElevDefault = 55.0f, ElevLeast = 20.0f, ElevMost = 80.0f; ///< the steepest look-up wanted (degrees)
inline constexpr float HorizLeast = 1.0f;     ///< the camera is never put closer than this to the target's vertical (m)
inline constexpr float GroundLift = 0.3f;     ///< the hunter is put this far above the ground under the target (m)
inline constexpr float MoveMost = 150.0f;     ///< no move longer than this (m): a frame mismatch, not a lantern
inline constexpr float NearHunter = 12.0f;    ///< the camera and the hunter must lie this near each other (horizontal, m)
inline constexpr float TolDist = 0.6f;        ///< a camera this near its horizontal distance counts as there (m)
inline constexpr float TolAngleDeg = 10.0f;   ///< and this near the target's bearing (degrees)
inline constexpr unsigned TriesMost = 4;      ///< warps one run tries
inline constexpr std::uint64_t SettleFrames = 120;   ///< frames after a warp before the camera is judged
inline constexpr std::uint64_t WaitFrames = 900;     ///< frames a posted request may stay unserved (a loading screen)
inline constexpr std::uint64_t StartFrame = 240;     ///< no request before this frame
inline constexpr unsigned LinesMost = 400;    ///< log lines a run at most (the slot runner's digest keeps the first 24 and last 24)
inline constexpr float RadToDeg = 57.29577951308232f;

struct Knobs {
    bool on = false;
    bool hang = true;         ///< false: a fixed position
    float pos[3] = {};        ///< the fixed position
    bool vs_set = false;
    std::uint32_t vs = 0;     ///< the vertex shader hash (the low 32 bits) the target must have
    float dist = DistDefault; ///< camera to target (m)
    float elev = ElevDefault; ///< the steepest look-up from the camera to the target's middle (degrees)
};

/// Exactly 8 hexadecimal digits (a vs hash as the logs print it); anything else is no filter.
[[nodiscard]] inline bool ParseVs(const char* text, std::uint32_t* out) {
    if (text == nullptr || std::strlen(text) != 8) {
        return false;
    }
    std::uint32_t v = 0;
    for (int i = 0; i < 8; ++i) {
        const char c = text[i];
        const int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) {
            return false;
        }
        v = v << 4 | static_cast<std::uint32_t>(d);
    }
    *out = v;
    return true;
}

/// "x,y,z" (three finite numbers, nothing after).
[[nodiscard]] inline bool ParsePos(const char* text, float out[3]) {
    if (text == nullptr) {
        return false;
    }
    char* end = nullptr;
    float v[3];
    const char* at = text;
    for (int i = 0; i < 3; ++i) {
        v[i] = std::strtof(at, &end);
        if (end == at || !std::isfinite(v[i])) {
            return false;
        }
        at = end;
        if (i < 2) {
            if (*at != ',') {
                return false;
            }
            ++at;
        }
    }
    if (*at != 0) {
        return false;
    }
    std::memcpy(out, v, sizeof v);
    return true;
}

[[nodiscard]] inline float ClampDist(float d) {
    return std::isnan(d) ? DistDefault : std::clamp(d, DistLeast, DistMost);
}

[[nodiscard]] inline float ClampElev(float e) {
    return std::isnan(e) ? ElevDefault : std::clamp(e, ElevLeast, ElevMost);
}

[[nodiscard]] inline Knobs ParseKnobs(const char* go, const char* vs, const char* dist, const char* elev) {
    Knobs k;
    if (go == nullptr || *go == 0) {
        return k;
    }
    if (std::strcmp(go, "hang") == 0) {
        k.on = true;
        k.hang = true;
    } else if (ParsePos(go, k.pos)) {
        k.on = true;
        k.hang = false;
    } else {
        return k; // not understood: off
    }
    k.vs_set = ParseVs(vs, &k.vs);
    if (dist != nullptr && *dist != 0) {
        k.dist = ClampDist(std::strtof(dist, nullptr));
    }
    if (elev != nullptr && *elev != 0) {
        k.elev = ClampElev(std::strtof(elev, nullptr));
    }
    return k;
}

[[nodiscard]] inline const Knobs& KnobsOnce() {
    static const Knobs k = ParseKnobs(std::getenv("BB_TEST_GOTO"), std::getenv("BB_TEST_GOTO_VS"),
                                      std::getenv("BB_TEST_GOTO_DIST"), std::getenv("BB_TEST_GOTO_ELEV"));
    return k;
}

[[nodiscard]] inline bool On() {
    return KnobsOnce().on;
}

// ---- the mailbox: the render thread asks, the game thread moves the hunter -----------------------------------------
struct Request {
    std::uint32_t seq = 0;
    float pos[3] = {};
};

inline std::atomic<bool> g_pending{false};   ///< a request waits (the game thread's one relaxed load a frame)
inline std::atomic<std::uint32_t> g_done_seq{0};
inline std::atomic<bool> g_done_ok{false};

[[nodiscard]] inline std::mutex& MailLock() {
    static std::mutex m;
    return m;
}

[[nodiscard]] inline Request& MailSlot() {
    static Request r;
    return r;
}

/// The render thread: a new request (the old one, unserved, is dropped). Returns its sequence number.
inline std::uint32_t Post(const float pos[3]) {
    std::lock_guard lock(MailLock());
    Request& r = MailSlot();
    ++r.seq;
    std::memcpy(r.pos, pos, sizeof r.pos);
    g_pending.store(true, std::memory_order_release);
    return r.seq;
}

/// The render thread: the request is not wanted any more.
inline void Cancel() {
    std::lock_guard lock(MailLock());
    g_pending.store(false, std::memory_order_release);
}

[[nodiscard]] inline bool Pending() {
    return g_pending.load(std::memory_order_relaxed);
}

/// The game thread: takes the waiting request (false: none).
[[nodiscard]] inline bool Take(Request* out) {
    std::lock_guard lock(MailLock());
    if (!g_pending.load(std::memory_order_acquire)) {
        return false;
    }
    *out = MailSlot();
    g_pending.store(false, std::memory_order_release);
    return true;
}

/// The game thread: the request `seq` was served (ok: the move was made) or refused.
inline void Done(std::uint32_t seq, bool ok) {
    g_done_ok.store(ok, std::memory_order_relaxed);
    g_done_seq.store(seq, std::memory_order_release);
}

// ---- the plan's arithmetic (pure) ------------------------------------------------------------------------------------
[[nodiscard]] inline float Horizontal(const float a[3], const float b[3]) {
    return std::hypot(a[0] - b[0], a[2] - b[2]);
}

[[nodiscard]] inline bool Finite3(const float v[3]) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}

/// The angle (degrees) between the camera's horizontal heading `fwd` (world, y up) and the direction from the camera to the
/// target, horizontal. 180 when either has no horizontal part.
[[nodiscard]] inline float BearingOffDeg(const float cam[3], const float fwd[3], const float target[3]) {
    const float fl = std::hypot(fwd[0], fwd[2]);
    const float dx = target[0] - cam[0], dz = target[2] - cam[2];
    const float dl = std::hypot(dx, dz);
    if (!(fl > 1e-4f) || !(dl > 1e-4f)) {
        return 180.0f;
    }
    const float c = std::clamp((fwd[0] * dx + fwd[2] * dz) / (fl * dl), -1.0f, 1.0f);
    return std::acos(c) * RadToDeg;
}

/// The camera's pitch (degrees, up positive) from its forward vector, and the elevation (degrees) of the target over the
/// camera: how much more look-up the target needs is the difference.
[[nodiscard]] inline float PitchDeg(const float fwd[3]) {
    const float h = std::hypot(fwd[0], fwd[2]);
    return std::atan2(fwd[1], h) * RadToDeg;
}

[[nodiscard]] inline float ElevationDeg(const float cam[3], const float target[3]) {
    return std::atan2(target[1] - cam[1], Horizontal(cam, target)) * RadToDeg;
}

struct Plan {
    bool ok = false;
    const char* why = "";
    float stand[3] = {};   ///< where the hunter is put
    float horiz = 0.0f;    ///< the horizontal camera-to-target distance wanted (m)
    float move = 0.0f;     ///< how far the hunter moves (horizontal, m)
};

/// Where to put the hunter so that the camera, which keeps its heading `fwd` and its offset from the hunter, ends `dist`
/// metres (3 D) from `target` (the mesh's middle) with the mesh straight ahead of its horizontal heading. `ground_y` is
/// the ground under the target. `cam` and `hunter` are as read now. The camera's height over the hunter is kept, so
/// the height difference to the target is known and the horizontal distance follows from `dist`, and is at least what
/// a look-up of `elev_deg` needs.
[[nodiscard]] inline Plan PlanStand(const float target[3], float ground_y, const float cam[3], const float fwd[3],
                                    const float hunter[3], float dist, float elev_deg) {
    Plan p;
    if (!Finite3(target) || !Finite3(cam) || !Finite3(fwd) || !Finite3(hunter) || !std::isfinite(ground_y)) {
        p.why = "a number is not finite";
        return p;
    }
    if (Horizontal(cam, hunter) > NearHunter || std::fabs(cam[1] - hunter[1]) > NearHunter) {
        p.why = "the hunter and the camera are not within 12 m: the two frames disagree";
        return p;
    }
    const float fl = std::hypot(fwd[0], fwd[2]);
    if (!(fl > 0.25f)) {
        p.why = "the camera looks straight up or down";
        return p;
    }
    const float fx = fwd[0] / fl, fz = fwd[2] / fl;
    const float stand_y = ground_y + GroundLift;
    const float cam_y = stand_y + (cam[1] - hunter[1]);
    const float dy = target[1] - cam_y;
    const float h2 = ClampDist(dist) * ClampDist(dist) - dy * dy;
    p.horiz = h2 > HorizLeast * HorizLeast ? std::sqrt(h2) : HorizLeast;
    if (dy > 0.0f) { // a target above the camera: no steeper a look-up than elev_deg
        p.horiz = std::max(p.horiz, dy / std::tan(ClampElev(elev_deg) / RadToDeg));
    }
    const float want_x = target[0] - fx * p.horiz, want_z = target[2] - fz * p.horiz;
    p.stand[0] = hunter[0] + (want_x - cam[0]);
    p.stand[1] = stand_y;
    p.stand[2] = hunter[2] + (want_z - cam[2]);
    p.move = std::hypot(p.stand[0] - hunter[0], p.stand[2] - hunter[2]);
    if (!Finite3(p.stand) || p.move > MoveMost) {
        p.why = "the move is longer than 150 m";
        return p;
    }
    p.ok = true;
    return p;
}

[[nodiscard]] inline bool Converged(float horiz_now, float horiz_want, float bearing_off_deg) {
    return std::fabs(horiz_now - horiz_want) <= TolDist && bearing_off_deg <= TolAngleDeg;
}

} // namespace BbTestGoto
''',
    TH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112n_hang-teleport-camera, TOOL; goes to the test-tools branch): the render side of BB_TEST_GOTO
// (bbport_test_goto.h has the knobs, the mailbox and the plan's arithmetic). Every time the hang survey's box set is read
// (WindHangFindRefresh: every 60 frames at most, only with BB_WIND_HANG=1) Observe is asked once:
//   1. it waits for the target (hang mode: the nearest PUSHED hanging mesh of the scene, BB_TEST_GOTO_VS narrows it) and
//      locks its box;
//   2. it plans where the hunter must stand so that the follow camera, which keeps its heading, ends BB_TEST_GOTO_DIST metres
//      from the mesh with the mesh straight ahead, and posts the request (the game thread moves the hunter);
//   3. 120 frames after the move it measures the camera again (the camera is read from the ray traced scene, not guessed) and,
//      when it is not there (BB_TEST_GOTO_DIST, 10 degrees of bearing), plans another move, at most 4 warps;
//   4. from then on it only reports: the numbers of every observation are one line each (the slot runner keeps the lines
//      that start with GLINT-PROOF: the first 24 and the last 24 of a run): the camera's 3 D and horizontal distance to the
//      mesh, the camera's pitch and the target's elevation (how much more look-up the stick must give), the mesh's
//      screen box (the survey's ScreenOf of its 8 corners) and whether its middle lies in the picture, the hunter, the target.
// Fixed position mode (BB_TEST_GOTO=x,y,z) does only step 2 with that position and the reports.
//
// Off (BB_TEST_GOTO unset or not understood): Observe returns at its first line. Nothing here runs without BB_WIND_HANG=1.

#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "bbport_test_goto.h"
#include "bbport_wind_hang_find.h"

namespace BbTestGoto {

enum class Phase : std::uint8_t { Wait, Moving, Settling, Holding, GaveUp };

[[nodiscard]] inline const char* PhaseName(Phase p) {
    switch (p) {
    case Phase::Wait:
        return "waiting";
    case Phase::Moving:
        return "warp asked";
    case Phase::Settling:
        return "settling";
    case Phase::Holding:
        return "holding";
    case Phase::GaveUp:
        return "gave up";
    }
    return "?";
}

struct Session {
    Phase phase = Phase::Wait;
    unsigned tries = 0, calls = 0, mismatches = 0;
    std::uint32_t seq = 0;
    std::uint64_t phase_frame = 0;
    bool locked = false;
    std::uint64_t stream = 0;
    std::uint32_t vs = 0;
    std::array<float, 6> box{};
    float centre[3] = {};
    float ground_y = 0.0f;
    float horiz_want = 0.0f;
    unsigned lines = 0;
};

[[nodiscard]] inline Session& Sess() {
    static Session s;
    return s;
}

struct ScreenBox {
    bool any = false; ///< at least one corner is in front of the camera
    bool all = false; ///< all 8
    float x0 = 0.0f, y0 = 0.0f, x1 = 0.0f, y1 = 0.0f;
};

/// The screen rectangle of a world box (the survey's ScreenOf of its 8 corners that lie in front of the camera).
[[nodiscard]] inline ScreenBox ScreenBoxOf(const BbWindHangFind::BoxSet& set, const std::array<float, 6>& b) {
    ScreenBox r;
    int in_front = 0;
    for (int i = 0; i < 8; ++i) {
        const BbWindHangFind::Screen s = BbWindHangFind::ScreenOf(set, (i & 1) ? b[3] : b[0], (i & 2) ? b[4] : b[1],
                                                                  (i & 4) ? b[5] : b[2]);
        if (!s.ok) {
            continue;
        }
        if (in_front == 0) {
            r.x0 = r.x1 = s.x;
            r.y0 = r.y1 = s.y;
        } else {
            r.x0 = std::min(r.x0, s.x);
            r.x1 = std::max(r.x1, s.x);
            r.y0 = std::min(r.y0, s.y);
            r.y1 = std::max(r.y1, s.y);
        }
        ++in_front;
    }
    r.any = in_front > 0;
    r.all = in_front == 8;
    return r;
}

/// What one observation read.
struct Reading {
    bool cam_ok = false, fwd_ok = false, hunter_ok = false, view_ok = false;
    float cam[3] = {}, fwd[3] = {}, hunter[3] = {};
    ScreenBox sb;
    std::uint32_t width = 0, height = 0;
};

[[nodiscard]] inline Reading ReadingOf(const BbWindHangFind::BoxSet& set, const std::array<float, 6>& box,
                                       const float* hunter) {
    Reading r;
    r.cam_ok = set.camera_ok && Finite3(set.camera.data());
    if (r.cam_ok) {
        std::memcpy(r.cam, set.camera.data(), sizeof r.cam);
    }
    r.view_ok = set.view_ok;
    if (set.view_ok) {
        r.fwd[0] = set.view[8];
        r.fwd[1] = set.view[9];
        r.fwd[2] = set.view[10];
        r.fwd_ok = Finite3(r.fwd);
        r.sb = ScreenBoxOf(set, box);
        r.width = set.render[0];
        r.height = set.render[1];
    }
    if (hunter != nullptr && Finite3(hunter)) {
        r.hunter_ok = true;
        std::memcpy(r.hunter, hunter, sizeof r.hunter);
    }
    return r;
}

/// The report line of one observation: numbers first.
[[nodiscard]] inline std::string LineOf(const Session& s, const Reading& r, std::uint64_t frame) {
    char part[240];
    std::string out;
    std::snprintf(part, sizeof(part), "GLINT-PROOF hang goto (r112n): %s f%llu: ", PhaseName(s.phase),
                  static_cast<unsigned long long>(frame));
    out += part;
    if (r.cam_ok) {
        const float d3 = std::sqrt(std::pow(s.centre[0] - r.cam[0], 2.0f) + std::pow(s.centre[1] - r.cam[1], 2.0f) +
                                   std::pow(s.centre[2] - r.cam[2], 2.0f));
        std::snprintf(part, sizeof(part), "camera to target %.1f m (horizontal %.1f m, %+.1f m up)", double(d3),
                      double(Horizontal(r.cam, s.centre)), double(s.centre[1] - r.cam[1]));
        out += part;
        std::snprintf(part, sizeof(part), ", target elevation %+.0f deg", double(ElevationDeg(r.cam, s.centre)));
        out += part;
    } else {
        out += "camera not read";
    }
    if (r.fwd_ok) {
        std::snprintf(part, sizeof(part), ", view pitch %+.0f deg", double(PitchDeg(r.fwd)));
        out += part;
        if (r.cam_ok) {
            std::snprintf(part, sizeof(part), ", bearing off %.0f deg", double(BearingOffDeg(r.cam, r.fwd, s.centre)));
            out += part;
        }
    }
    if (r.view_ok && r.sb.any) {
        const float cx = 0.5f * (r.sb.x0 + r.sb.x1), cy = 0.5f * (r.sb.y0 + r.sb.y1);
        const bool in_view = cx >= 0.0f && cy >= 0.0f && cx < float(r.width) && cy < float(r.height);
        std::snprintf(part, sizeof(part), "; screen box %.0f,%.0f to %.0f,%.0f of %ux%u (middle %.0f,%.0f: %s%s)",
                      double(r.sb.x0), double(r.sb.y0), double(r.sb.x1), double(r.sb.y1),
                      static_cast<unsigned>(r.width), static_cast<unsigned>(r.height), double(cx), double(cy),
                      in_view ? "IN VIEW" : "OUT OF VIEW", r.sb.all ? "" : ", partly behind the camera");
        out += part;
    } else if (r.view_ok) {
        out += "; screen box: behind the camera";
    } else {
        out += "; screen box: the view is not read";
    }
    if (r.hunter_ok) {
        std::snprintf(part, sizeof(part), "; hunter %.2f %.2f %.2f", double(r.hunter[0]), double(r.hunter[1]),
                      double(r.hunter[2]));
        out += part;
    } else {
        out += "; hunter not read";
    }
    std::snprintf(part, sizeof(part), "; target vs %08x middle %.2f %.2f %.2f ground y %.2f; warps %u",
                  static_cast<unsigned>(s.vs), double(s.centre[0]), double(s.centre[1]), double(s.centre[2]),
                  double(s.ground_y), s.tries);
    out += part;
    return out;
}

/// One observation of the hang survey's box set, with the knobs and the session given (the tests' entry). Returns the lines
/// to print (the caller prints them). `hunter` is the game's physics position (null: not read). `frame` counts the effects'
/// frames.
template <class JudgeBook>
[[nodiscard]] inline std::vector<std::string> ObserveWith(const Knobs& k, Session& s, const BbWindHangFind::BoxSet& set,
                                                          const BbWindHangFind::StaticBook& book,
                                                          BbWindHang::Book& heights, const JudgeBook& judge,
                                                          float tall_m, std::uint64_t frame, const float* hunter) {
    std::vector<std::string> out;
    if (!k.on || s.phase == Phase::GaveUp) {
        return out;
    }
    const auto say = [&](const std::string& text) {
        if (s.lines < LinesMost) {
            ++s.lines;
            out.push_back(BbWindHangFind::Cap(text.c_str()));
        }
    };
    char buf[400];
    ++s.calls;
    if (!s.locked) { // the target: the nearest pushed mesh (the survey's own classes), once
        const std::vector<BbWindHangFind::CandInfo> cands = BbWindHangFind::GatherCands(set, book, heights, judge);
        const BbWindHangFind::CandInfo* target = nullptr;
        for (const BbWindHangFind::CandInfo& c : cands) {
            if (BbWindHangFind::ClassOf(c, tall_m) != BbWindHangFind::CandClass::Pushed) {
                continue;
            }
            if (k.vs_set && static_cast<std::uint32_t>(c.e.vs & 0xffffffffull) != k.vs) {
                continue;
            }
            target = &c;
            break;
        }
        if (target != nullptr) {
            s.locked = true;
            s.stream = target->stream;
            s.vs = static_cast<std::uint32_t>(target->e.vs & 0xffffffffull);
            s.box = target->box;
            s.centre[0] = 0.5f * (s.box[0] + s.box[3]);
            s.centre[1] = 0.5f * (s.box[1] + s.box[4]);
            s.centre[2] = 0.5f * (s.box[2] + s.box[5]);
            s.ground_y = s.box[1] - target->e.above;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): target locked: vs %08x (%u verts, %u place%s), box %.2f m tall "
                          "%.2f m wide, %.2f m up, middle %.2f %.2f %.2f, ground y %.2f, %.1f m from the camera now; "
                          "mode %s, camera distance wanted %.1f m",
                          static_cast<unsigned>(s.vs), target->e.verts, target->places, target->places == 1 ? "" : "s",
                          double(target->e.height), double(target->e.width), double(target->e.above),
                          double(s.centre[0]), double(s.centre[1]), double(s.centre[2]), double(s.ground_y),
                          double(target->dist), k.hang ? "hang" : "fixed position", double(k.dist));
            say(buf);
        } else if (k.hang) {
            if (s.calls % 10 == 1) {
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): waiting: no pushed candidate%s in the scene yet (%zu "
                              "candidates; call %u)",
                              k.vs_set ? " with that vs" : "", cands.size(), s.calls);
                say(buf);
            }
            return out;
        }
    }
    if (!s.locked) { // fixed position without a target: the centre of the position, for the report's numbers only
        std::memcpy(s.centre, k.pos, sizeof s.centre);
        s.box = {k.pos[0], k.pos[1], k.pos[2], k.pos[0], k.pos[1], k.pos[2]};
        s.ground_y = k.pos[1];
        s.locked = true;
    }
    const Reading r = ReadingOf(set, s.box, hunter);
    const std::uint64_t since = frame >= s.phase_frame ? frame - s.phase_frame : 0;

    if (s.phase == Phase::Wait && frame >= StartFrame) {
        float stand[3] = {};
        const char* why = nullptr;
        if (!r.hunter_ok) {
            why = "the hunter's position is not read yet";
        } else if (!k.hang) {
            std::memcpy(stand, k.pos, sizeof stand);
        } else if (!r.cam_ok || !r.fwd_ok) {
            why = "the camera or its view is not read yet";
        } else {
            const Plan p = PlanStand(s.centre, s.ground_y, r.cam, r.fwd, r.hunter, k.dist, k.elev);
            if (p.ok) {
                std::memcpy(stand, p.stand, sizeof stand);
                s.horiz_want = p.horiz;
            } else {
                why = p.why;
                if (++s.mismatches >= 3) {
                    s.phase = Phase::GaveUp;
                    std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): gave up: %s", p.why);
                    say(buf);
                    return out;
                }
            }
        }
        if (why == nullptr) {
            s.seq = Post(stand);
            s.phase = Phase::Moving;
            s.phase_frame = frame;
            ++s.tries;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): warp %u asked (try %u of %u): hunter to %.2f %.2f %.2f from "
                          "%.2f %.2f %.2f, %.1f m horizontally; camera horizontal distance wanted %.1f m",
                          s.seq, s.tries, TriesMost, double(stand[0]), double(stand[1]), double(stand[2]),
                          double(r.hunter[0]), double(r.hunter[1]), double(r.hunter[2]),
                          double(Horizontal(stand, r.hunter)), double(s.horiz_want));
            say(buf);
        } else if (s.calls % 5 == 1) {
            std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): waiting: %s", why);
            say(buf);
        }
    } else if (s.phase == Phase::Moving) {
        if (g_done_seq.load(std::memory_order_acquire) == s.seq) {
            const bool ok = g_done_ok.load(std::memory_order_relaxed);
            s.phase_frame = frame;
            if (ok) {
                s.phase = Phase::Settling;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): warp %u made by the game thread; settling %llu frames",
                              s.seq, static_cast<unsigned long long>(SettleFrames));
            } else {
                s.phase = s.tries >= TriesMost ? Phase::GaveUp : Phase::Wait;
                std::snprintf(buf, sizeof(buf), "GLINT-PROOF hang goto (r112n): warp %u refused by the game thread%s", s.seq,
                              s.phase == Phase::GaveUp ? ": gave up" : ": asking again");
            }
            say(buf);
        } else if (since > WaitFrames) {
            Cancel();
            s.phase_frame = frame;
            s.phase = s.tries >= TriesMost ? Phase::GaveUp : Phase::Wait;
            std::snprintf(buf, sizeof(buf),
                          "GLINT-PROOF hang goto (r112n): warp %u not served in %llu frames (a loading screen, no "
                          "hunter, or the engine hook is missing)%s",
                          s.seq, static_cast<unsigned long long>(WaitFrames),
                          s.phase == Phase::GaveUp ? ": gave up" : ": asking again");
            say(buf);
        }
    } else if (s.phase == Phase::Settling && since >= SettleFrames) {
        if (!k.hang) {
            s.phase = Phase::Holding;
            say("GLINT-PROOF hang goto (r112n): READY at the fixed position (hunter read in the next lines)");
        } else if (r.cam_ok && r.fwd_ok) {
            const float horiz = Horizontal(r.cam, s.centre);
            const float off = BearingOffDeg(r.cam, r.fwd, s.centre);
            if (Converged(horiz, s.horiz_want, off)) {
                s.phase = Phase::Holding;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): READY after %u warp%s: camera %.1f m horizontally from "
                              "the target (wanted %.1f), bearing off %.0f deg",
                              s.tries, s.tries == 1 ? "" : "s", double(horiz), double(s.horiz_want), double(off));
            } else if (s.tries >= TriesMost) {
                s.phase = Phase::GaveUp;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): gave up after %u warps: camera %.1f m horizontally from "
                              "the target (wanted %.1f), bearing off %.0f deg",
                              s.tries, double(horiz), double(s.horiz_want), double(off));
            } else {
                s.phase = Phase::Wait;
                s.phase_frame = frame;
                std::snprintf(buf, sizeof(buf),
                              "GLINT-PROOF hang goto (r112n): camera not there: %.1f m horizontally from the target "
                              "(wanted %.1f), bearing off %.0f deg: another warp",
                              double(horiz), double(s.horiz_want), double(off));
            }
            say(buf);
        }
    }
    if (s.phase != Phase::GaveUp) {
        const bool quiet = s.phase == Phase::Wait && !k.hang;
        if (!quiet) {
            say(LineOf(s, r, frame));
        }
    }
    return out;
}

/// The run's observation: BB_TEST_GOTO's knobs and the one session.
template <class JudgeBook>
[[nodiscard]] inline std::vector<std::string> Observe(const BbWindHangFind::BoxSet& set,
                                                      const BbWindHangFind::StaticBook& book,
                                                      BbWindHang::Book& heights, const JudgeBook& judge, float tall_m,
                                                      std::uint64_t frame, const float* hunter) {
    return ObserveWith(KnobsOnce(), Sess(), set, book, heights, judge, tall_m, frame, hunter);
}

} // namespace BbTestGoto
''',
}

# ---- bbport_wind_hang.h: why an entry is held as moving ------------------------------------------------
H1 = r"""    bool moving = false;      ///< for good: another palette, an unreadable or GPU-written one
"""
H1N = r"""    std::uint8_t why_moving = 0; ///< bbport (r112n): the first reason `moving` was set: 1 a palette could not be read, 2 its bytes changed, 3 the GPU judge, 4 r112h's rule
    std::uint32_t moved_after = 0; ///< bbport (r112n): the frames counted before the bytes changed (2), or r112h's rule's number (4)
"""

H2 = r"""        if (!readable) {
            e.moving = true;
        } else if (e.frames == 0) {
            e.hash = hash;
            e.frames = 1;
            e.frame = frame;
        } else if (hash != e.hash) {
            e.moving = true;
"""
H2N = r"""        if (!readable) {
            if (!e.moving) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                e.why_moving = 1;
            }
            e.moving = true;
        } else if (e.frames == 0) {
            e.hash = hash;
            e.frames = 1;
            e.frame = frame;
        } else if (hash != e.hash) {
            if (!e.moving) {
                e.why_moving = 2;
                e.moved_after = e.frames;
            }
            e.moving = true;
"""

# ---- bbport_wind_hang_find.h: the candidate lines say why, and where ----------------------------------
F1 = r"""    std::uint64_t judge_draws = 0;
};
"""
F1N = r"""    std::uint64_t judge_draws = 0;
    std::uint8_t moving_why = 0;    ///< bbport (r112n): the hang book's reason for `moving` (BbWindHang::Entry::why_moving)
    std::uint32_t moved_after = 0;  ///< bbport (r112n): and its number (frames counted, or r112h's rule's number)
};
"""

F2 = r"""            c.span = h->judged ? h->top - h->base : 0.0f;
"""
F2N = r"""            c.moving_why = h->why_moving; // bbport (r112n_hang-teleport-camera)
            c.moved_after = h->moved_after;
"""

F3 = r"""enum class CandClass : std::uint8_t { Pushed, Tall, NoJudge, Other };
"""
F3P = r"""// bbport (r112n_hang-teleport-camera): why r112's book holds a stream as moving (BbWindHang::Entry::why_moving, the FIRST reason): a
// palette it draws with could not be read, or its palette bytes changed (an animated skeleton, or instances with other palettes
// sharing the stream's address), or the GPU judge saw its box grow, or r112h's rule refused it (`n`: the rule's number, the
// order of BbWindHangActors::Why). A held stream's keys are never measured: that is why its candidate line says "keys span
// not read".
[[nodiscard]] inline std::string MovingWhy(std::uint8_t why, std::uint32_t n) {
    static constexpr const char* const rules[] = {"ok",     "no hunter read", "near the hunter", "a figure (bones)",
                                                  "indoors", "unplaced",       "no palette"};
    char buf[320];
    switch (why) {
    case 1:
        std::snprintf(buf, sizeof(buf),
                      "a palette it draws with could not be read (GPU-written or not mapped); its keys are never measured "
                      "while it is held");
        break;
    case 2:
        std::snprintf(buf, sizeof(buf),
                      "its palette bytes changed after %u frames counted (an animated skeleton, or instances with other "
                      "palettes at the stream's address); its keys are never measured while it is held",
                      n);
        break;
    case 3:
        std::snprintf(buf, sizeof(buf),
                      "the GPU judge saw its box grow; its keys are never measured while it is held");
        break;
    case 4:
        std::snprintf(buf, sizeof(buf), "r112h's rule refused it (%s); its keys are never measured while it is held",
                      n < sizeof(rules) / sizeof(rules[0]) ? rules[n] : "?");
        break;
    default:
        std::snprintf(buf, sizeof(buf), "the reason was not recorded");
        break;
    }
    return std::string(buf);
}

"""

F4 = r"""        std::snprintf(buf, sizeof(buf), "held as moving by r112's book");
"""
F4N = r"""        std::snprintf(buf, sizeof(buf), "held as moving by r112's book: %s", MovingWhy(c.moving_why, c.moved_after).c_str());
"""

F5 = r"""            std::snprintf(keys, sizeof(keys), "not read");
"""
F5N = r"""            std::snprintf(keys, sizeof(keys), "%s", c.moving ? "not read (held)" : "not read"); // bbport (r112n)
"""

F6 = r"""                      "wide, %.2f m up; keys span %s (the union of its places) vs scene box %.2f m; %s",
"""
F6N = r"""                      "wide, %.2f m up (middle %.2f %.2f %.2f, ground y %.2f); keys span %s (the union of its places) vs "
                      "scene box %.2f m; %s",
"""

F7 = r"""                      c.places == 1 ? "" : "s", c.e.verts, dist, double(c.e.height), double(c.e.width), double(c.e.above),
                      keys, double(c.e.height), state.c_str());
"""
F7N = r"""                      c.places == 1 ? "" : "s", c.e.verts, dist, double(c.e.height), double(c.e.width), double(c.e.above),
                      double(0.5f * (c.box[0] + c.box[3])), double(0.5f * (c.box[1] + c.box[4])),
                      double(0.5f * (c.box[2] + c.box[5])), double(c.box[1] - c.e.above), keys, double(c.e.height),
                      state.c_str());
"""

# ---- the tests ----------------------------------------------------------------------------------------
T0 = r"""#include "gpu/shim/bbport_wind_hang_find.h"
"""
T0N = r"""#include "gpu/shim/bbport_test_goto_hang.h" // bbport (r112n_hang-teleport-camera)
"""

T1 = r"""        const std::string once_m = F::OnceTextM(true, true, F::TallDefault);
"""
T1P = r"""        // bbport (r112n_hang-teleport-camera): why a stream is held as moving, the candidate lines' places, BB_TEST_GOTO
        {
            BbWindHang::Book moving_book;
            moving_book.Note(21, 4096, 7, true, 10, 0xe859b6d9ull);
            moving_book.Note(21, 4096, 8, true, 11, 0xe859b6d9ull); // other palette bytes at the same address
            moving_book.Note(21, 4096, 9, false, 12, 0xe859b6d9ull); // and then unreadable: the first reason stays
            moving_book.Note(22, 4096, 0, false, 10, 0x1234abcdull); // unreadable at once
            const BbWindHang::Entry* const changed = moving_book.Find(21);
            const BbWindHang::Entry* const unread = moving_book.Find(22);
            Expect(changed != nullptr && unread != nullptr && changed->moving && unread->moving &&
                       changed->why_moving == 2 && changed->moved_after == 1 && unread->why_moving == 1,
                   "r112n: the book records why a stream is held as moving (the first reason)");
            Expect(Has(F::MovingWhy(2, 1), "palette bytes changed after 1 frames") && Has(F::MovingWhy(2, 1), "never measured") &&
                       Has(F::MovingWhy(1, 0), "could not be read") && Has(F::MovingWhy(3, 0), "GPU judge") &&
                       Has(F::MovingWhy(4, 3), "r112h's rule refused it (a figure (bones))") &&
                       Has(F::MovingWhy(4, 99), "(?)") && Has(F::MovingWhy(0, 0), "not recorded"),
                   "r112n: the reasons in words");
            F::CandInfo held;
            held.e.height = 1.32f;
            held.hang = true;
            held.moving = true;
            held.moving_why = 2;
            held.moved_after = 4;
            Expect(Has(F::CandState(held, 2.5f, 0.2f, true, 0.1f), "held as moving by r112's book: its palette bytes changed after 4 frames"),
                   "r112n: the moving state carries its reason");
            const std::vector<std::string> place_lines =
                F::CandLines(infos, F::Stats{}, 2.5f, F::GainDefault, true, push_table, true, false);
            Expect(place_lines.size() == 4 && Has(place_lines[2], "6.30 m up (middle -34.00 -35.56 107.40, ground y -42.30)"),
                   "r112n: a candidate line names its middle and the ground under it");

            namespace G = BbTestGoto;
            std::uint32_t vs_value = 0;
            Expect(G::ParseVs("97f2d384", &vs_value) && vs_value == 0x97f2d384u && G::ParseVs("97F2D384", &vs_value) &&
                       !G::ParseVs("97f2d38", &vs_value) && !G::ParseVs("97f2d38g", &vs_value) && !G::ParseVs(nullptr, &vs_value) &&
                       !G::ParseVs("97f2d3844", &vs_value),
                   "r112n: the vs filter is exactly 8 hex digits");
            const G::Knobs hang_knobs = G::ParseKnobs("hang", "97F2D384", "3", nullptr);
            Expect(hang_knobs.on && hang_knobs.hang && hang_knobs.vs_set && hang_knobs.vs == 0x97f2d384u &&
                       std::fabs(hang_knobs.dist - 3.0f) < 1e-6f && std::fabs(hang_knobs.elev - G::ElevDefault) < 1e-6f,
                   "r112n: BB_TEST_GOTO=hang");
            const G::Knobs fixed_knobs = G::ParseKnobs("-34.2,-36,107", nullptr, "99", "70");
            Expect(fixed_knobs.on && !fixed_knobs.hang && std::fabs(fixed_knobs.pos[0] + 34.2f) < 1e-4f &&
                       std::fabs(fixed_knobs.pos[1] + 36.0f) < 1e-4f && std::fabs(fixed_knobs.pos[2] - 107.0f) < 1e-4f &&
                       std::fabs(fixed_knobs.dist - G::DistMost) < 1e-6f && std::fabs(fixed_knobs.elev - 70.0f) < 1e-6f &&
                       !fixed_knobs.vs_set,
                   "r112n: BB_TEST_GOTO=x,y,z, the distance and the elevation are clamped");
            Expect(!G::ParseKnobs(nullptr, nullptr, nullptr, nullptr).on && !G::ParseKnobs("", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("1,2", nullptr, nullptr, nullptr).on && !G::ParseKnobs("1,2,3x", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("nan,1,2", nullptr, nullptr, nullptr).on && !G::ParseKnobs("hang ", nullptr, nullptr, nullptr).on &&
                       !G::ParseKnobs("0", nullptr, nullptr, nullptr).on,
                   "r112n: a knob that is not understood is off");

            // the plan: the graveyard lantern B (middle -34.00 -35.56 107.40, ground y -42.30), the hunter 20 m away, the camera 3 m behind
            // him and 1.9 m up, looking (nearly) along -z
            const float target[3] = {-34.0f, -35.56f, 107.4f};
            const float hunter[3] = {-41.9f, -42.3f, 87.0f};
            const float cam[3] = {-40.81f, -40.4f, 90.0f};
            const float fwd[3] = {-0.3416f, 0.04998f, -0.9385f};
            const G::Plan plan = G::PlanStand(target, -42.3f, cam, fwd, hunter, 4.9f, 55.0f);
            Expect(plan.ok && std::fabs(plan.stand[0] + 34.003f) < 0.02f && std::fabs(plan.stand[1] + 42.0f) < 1e-3f &&
                       std::fabs(plan.stand[2] - 107.387f) < 0.02f && std::fabs(plan.horiz - 3.179f) < 0.01f &&
                       std::fabs(plan.move - 21.86f) < 0.05f,
                   "r112n: the stand point (look-up capped at 55 degrees: 3.18 m horizontally, 5.5 m in 3 D)");
            const G::Plan steep = G::PlanStand(target, -42.3f, cam, fwd, hunter, 4.9f, 80.0f);
            Expect(steep.ok && std::fabs(steep.horiz - 1.843f) < 0.01f && steep.horiz < plan.horiz,
                   "r112n: with a steep look-up allowed the camera is put at 4.9 m in 3 D");
            const float cam_after[3] = {plan.stand[0] + (cam[0] - hunter[0]), plan.stand[1] + (cam[1] - hunter[1]),
                                        plan.stand[2] + (cam[2] - hunter[2])};
            Expect(G::Converged(G::Horizontal(cam_after, target), plan.horiz, G::BearingOffDeg(cam_after, fwd, target)) &&
                       !G::Converged(G::Horizontal(cam, target), plan.horiz, G::BearingOffDeg(cam, fwd, target)) &&
                       std::fabs(G::ElevationDeg(cam_after, target) - 55.0f) < 0.2f,
                   "r112n: a camera that keeps its offset from the hunter is where the plan wants it");
            const float far_hunter[3] = {-41.9f, -42.3f, 20.0f};
            const float down[3] = {0.0f, -1.0f, 0.0f};
            const float far_target[3] = {-34.0f, -35.56f, 407.4f};
            Expect(!G::PlanStand(target, -42.3f, cam, fwd, far_hunter, 4.9f, 55.0f).ok &&
                       Has(G::PlanStand(target, -42.3f, cam, fwd, far_hunter, 4.9f, 55.0f).why, "disagree") &&
                       !G::PlanStand(target, -42.3f, cam, down, hunter, 4.9f, 55.0f).ok &&
                       !G::PlanStand(far_target, -42.3f, cam, fwd, hunter, 4.9f, 55.0f).ok &&
                       !G::PlanStand(target, std::nanf(""), cam, fwd, hunter, 4.9f, 55.0f).ok,
                   "r112n: no plan from frames that disagree, a camera looking down, a move over 150 m, a number that is none");

            // the mailbox between the threads
            const float spot[3] = {1.0f, 2.0f, 3.0f};
            G::Request taken;
            Expect(!G::Take(&taken), "r112n: nothing waits at first");
            const std::uint32_t seq = G::Post(spot);
            Expect(G::Pending() && G::Take(&taken) && taken.seq == seq && taken.pos[2] == 3.0f && !G::Pending() && !G::Take(&taken),
                   "r112n: a request is taken once");
            G::Done(seq, true);
            Expect(G::g_done_seq.load() == seq && G::g_done_ok.load(), "r112n: the answer");
            (void)G::Post(spot);
            G::Cancel();
            Expect(!G::Pending(), "r112n: a request can be withdrawn");

            // the machine: the scene of the lines above (B 5.1 m away is the nearest pushed mesh), a camera looking along +z
            F::BoxSet gset = set;
            gset.view_ok = true;
            gset.view = {1.0f, 0.0f, 0.0f, 34.0f, 0.0f, 1.0f, 0.0f, 33.0f, 0.0f, 0.0f, 1.0f, -103.0f};
            gset.proj = {1.5f, -2.6667f, 1.0f, 0.1f};
            gset.render = {1280u, 720u};
            const float gunter[3] = {-34.0f, -35.0f, 100.0f};
            G::Knobs gk;
            gk.on = true;
            G::Session gs;
            Expect(G::ObserveWith(G::Knobs{}, gs, gset, book, heights, judge, 2.5f, 0, gunter).empty(),
                   "r112n: off, nothing is observed");
            std::vector<std::string> gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 0, gunter);
            Expect(gl.size() == 2 && Has(gl[0], "GLINT-PROOF hang goto (r112n): target locked: vs 97f2d384 (2491 verts, 2 places)") &&
                       Has(gl[1], "waiting f0: camera to target") && gs.phase == G::Phase::Wait && gs.locked,
                   "r112n: the first look locks the nearest pushed mesh and waits for the start frame");
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 300, gunter);
            Expect(gs.phase == G::Phase::Moving && G::Pending() && gl.size() == 2 &&
                       Has(gl[0], "asked (try 1 of 4): hunter to -34.00 -42.00") && Has(gl[1], "warp asked f300"),
                   "r112n: the plan is posted");
            G::Request asked;
            Expect(G::Take(&asked) && std::fabs(asked.pos[1] + 42.0f) < 1e-3f, "r112n: the game thread takes the request");
            G::Done(asked.seq, true);
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 310, gunter);
            Expect(gs.phase == G::Phase::Settling && Has(gl[0], "made by the game thread"), "r112n: the move is seen");
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 310 + G::SettleFrames, gunter);
            Expect(gs.phase == G::Phase::Wait && Has(gl[0], "camera not there") && Has(gl[0], "another warp"),
                   "r112n: a camera that did not arrive is planned again");
            gset.camera = {-34.0f, -33.0f, 107.4f - gs.horiz_want};
            gset.view[11] = -(107.4f - gs.horiz_want);
            gset.view[3] = 34.0f;
            gset.view[7] = 33.0f;
            gs.phase = G::Phase::Settling;
            gs.phase_frame = 1000;
            gl = G::ObserveWith(gk, gs, gset, book, heights, judge, 2.5f, 1000 + G::SettleFrames, gunter);
            Expect(gs.phase == G::Phase::Holding && Has(gl[0], "READY after 1 warp") && Has(gl[1], "holding f1120") &&
                       Has(gl[1], "bearing off 0 deg") && Has(gl[1], "OUT OF VIEW") && Has(gl[1], "view pitch +0 deg"),
                   "r112n: ready, and the level view does not see a mesh 55 degrees up");
        }
"""

# ---- vk_rasterizer_effects.cpp ----------------------------------------------------------------------
E0 = r"""#include "engine/engine_state.h" // bbport (r112h_hang-not-the-hunter): the hunter's position
"""
E0N = r"""#include "bbport_test_goto_hang.h" // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO
"""

E1 = r"""                moved->moving = true;
"""
E1N = r"""                if (moved->why_moving == 0) { // bbport (r112n_hang-teleport-camera): the first reason is kept
                    moved->why_moving = 3;
                }
"""

E2 = r"""        entry->moving = true;
"""
E2N = r"""        if (entry->why_moving == 0) { // bbport (r112n_hang-teleport-camera): r112h's rule, its number
            entry->why_moving = 4;
            entry->moved_after = static_cast<u32>(why);
        }
"""

E3 = r"""                                  matrices.proj[1] != 0.0f;
    }
"""
E3N = r"""    if (BbTestGoto::On()) { // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO: the hunter and the camera to the target
        float hunter_pos[3] = {};
        const bool hunter_read = BbEngine::world_player_position(hunter_pos);
        for (const std::string& line : BbTestGoto::Observe(hang_find_boxes, hang_static_book, hang_book, hang_box,
                                                           BbWindHangFind::TallKnob(), frame,
                                                           hunter_read ? hunter_pos : nullptr)) {
            BbReport::Printf("%s\n", line.c_str());
        }
    }
"""

# ---- the engine: the game thread moves the hunter --------------------------------------------------------
O1 = r"""#include "bbport_platform.h"
"""
O1N = r"""#include "bbport_test_goto.h" // bbport (r112n_hang-teleport-camera, TOOL)
"""

O2 = r"""void SetCameraYaw(float yaw) {
    g_camera_yaw = yaw;
    g_camera_known = true;
}
"""
O2N = r"""
// bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO. The render thread posts a request (bbport_test_goto.h); here, on the game
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

OH1 = r"""std::string LampPlace(std::uint32_t lamp);
"""
OH1N = r"""void TestGotoTick(); // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO, once a frame on the game thread
"""

FE1 = r"""    OnlineFixes::Tick();
    return 0;
}
"""
FE1N = r"""    OnlineFixes::Tick();
    OnlineFixes::TestGotoTick(); // bbport (r112n_hang-teleport-camera, TOOL): BB_TEST_GOTO (one relaxed load when off)
    return 0;
}
"""

# ---- README.md -------------------------------------------------------------------------------------
R1 = r"""| `BB_WIND_HANG_PROOF` |"""
R1P = r"""| `BB_TEST_GOTO` | TOOL (r112n; goes to the test-tools branch with the other test aids; off by default; needs `BB_WIND_HANG=1`). Puts the hunter, and so the follow camera, at a place without a walk, for the hanging-things tests: `hang` the camera ends `BB_TEST_GOTO_DIST` metres (3 D, 1 to 20, default 4.9) from the middle of the nearest PUSHED hanging mesh of the scene (`BB_TEST_GOTO_VS=<8 hex digits>` narrows it to one vertex shader hash, e.g. the graveyard lantern `97f2d384`) with the mesh straight ahead of the camera's own heading, and never closer than a look-up of `BB_TEST_GOTO_ELEV` degrees (20 to 80, default 55) needs; or `x,y,z` the hunter is put at that world position (y up, the scene's frame). The request goes to the game thread, which moves the living hunter with the engine's own co-op bring-to-host call (`MoveBodyToSafeSpot`) after checking the warp's entry bytes; 120 frames later the camera is read from the ray traced scene and, if it is not within 0.6 m of its horizontal distance and 10 degrees of the mesh's bearing, another warp follows (4 at most). Log: lines starting `GLINT-PROOF hang goto (r112n)`: the target locked, each warp asked and made, and every 60 frames the camera's 3 D and horizontal distance to the mesh, the camera's pitch and the mesh's elevation, the mesh's screen box and whether its middle is in the picture, the hunter and the target. The pad's right stick up (`ry=0`) gives the rest of the look-up. Off: one relaxed load of a false flag a frame on the game thread, one test of a static bool every 60 frames on the render thread. |
"""

EDITS = {
NH: [
('ins', H1, "", H1N),
('rep', H2, "", H2N),
],
NF: [
('rep', F1, "", F1N),
('ins', F2, "", F2N),
('ins', F3, F3P, ""),
('rep', F4, "", F4N),
('rep', F5, "", F5N),
('rep', F6, "", F6N),
('rep', F7, "", F7N),
],
NT: [
('ins', T0, "", T0N),
('ins', T1, T1P, ""),
],
RE: [
('ins', E0, "", E0N),
('ins', E1, "", E1N),
('ins', E2, "", E2N),
('ins', E3, "", E3N),
],
OF: [
('ins', O1, "", O1N),
('ins', O2, "", O2N),
],
OH: [
('ins', OH1, "", OH1N),
],
FE: [
('rep', FE1, "", FE1N),
],
RM: [
('ins', R1, R1P, ""),
],
}


ORDER = (NH, NF, NT, RE, OF, OH, FE, RM)
NEW_ORDER = (TG, TH)


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
    nf, nh, nt, re_, of_, oh, fe = texts[NF], texts[NH], texts[NT], texts[RE], texts[OF], texts[OH], texts[FE]
    tg, th = NEW_FILES[TG], NEW_FILES[TH]
    for path in ORDER:
        if path == RM:
            continue
        if balance(texts[path]) != balance(olds[path]):
            raise SystemExit("text check: %s: braces, parens or brackets changed by %r" %
                             (path, tuple(a - b for a, b in zip(balance(texts[path]), balance(olds[path])))))
    for path, text in ((TG, tg), (TH, th)):
        if balance(text) != (0, 0, 0):
            raise SystemExit("text check: %s: braces, parens or brackets do not balance: %r" % (path, balance(text)))
    for needle in ("inline std::string MovingWhy(", "std::uint8_t moving_why = 0;", "std::uint32_t moved_after = 0;",
                   "c.moving_why = h->why_moving;", "MovingWhy(c.moving_why, c.moved_after)",
                   "(middle %.2f %.2f %.2f, ground y %.2f)", '"%s", c.moving ? "not read (held)" : "not read"'):
        if needle not in nf:
            raise SystemExit("text check: %s missing in the find header" % needle)
    if nf.index("inline std::string MovingWhy(") > nf.index("inline std::string CandState("):
        raise SystemExit("text check: MovingWhy must precede CandState")
    for needle in ("std::uint8_t why_moving = 0;", "std::uint32_t moved_after = 0;", "e.why_moving = 1;",
                   "e.why_moving = 2;", "e.moved_after = e.frames;"):
        if needle not in nh:
            raise SystemExit("text check: %s missing in the hang header" % needle)
    if nh.count("why_moving = ") != 3:
        raise SystemExit("text check: the book declares its reason and sets it in two places")
    if nh.index("std::uint8_t why_moving = 0;") > nh.index("e.why_moving = 1;"):
        raise SystemExit("text check: why_moving is used before its declaration")
    for needle in ("#include \"bbport_test_goto_hang.h\"", "moved->why_moving = 3;", "entry->why_moving = 4;",
                   "entry->moved_after = static_cast<u32>(why);", "BbTestGoto::On()", "BbTestGoto::Observe(hang_find_boxes, hang_static_book, hang_book, hang_box,"):
        if needle not in re_:
            raise SystemExit("text check: %s missing in the effects file" % needle)
    if re_.index("hang_find_boxes.view_ok = ") > re_.index("BbTestGoto::Observe("):
        raise SystemExit("text check: the goto block must follow the box set's camera and view")
    if re_.index("void Rasterizer::WindHangFindRefresh(u64 frame) {") > re_.index("BbTestGoto::Observe("):
        raise SystemExit("text check: the goto block belongs to WindHangFindRefresh")
    if re_.index("BbTestGoto::Observe(") > re_.index("bool Rasterizer::WindHangStaticAllowed("):
        raise SystemExit("text check: the goto block must end WindHangFindRefresh")
    if "#include \"bbport_test_goto.h\"" not in of_ or "void TestGotoTick() {" not in of_ or \
            "std::memcmp(g_image + kWarp, kWarpEntry, sizeof kWarpEntry)" not in of_ or \
            "MoveBodyToSafeSpot(local, r.pos, facing);" not in of_:
        raise SystemExit("text check: the engine side is missing")
    if of_.index("void MoveBodyToSafeSpot(") > of_.index("void TestGotoTick() {") or \
            of_.index("constexpr std::size_t kWarp = ") > of_.index("void TestGotoTick() {") or \
            of_.index("bool Loading() {") > of_.index("void TestGotoTick() {") or \
            of_.index("float Facing(std::uint64_t chr) {") > of_.index("void TestGotoTick() {") or \
            of_.index("bool Position(std::uint64_t chr, float out[3]) {") > of_.index("void TestGotoTick() {"):
        raise SystemExit("text check: TestGotoTick uses a name before its definition")
    if of_.count("void TestGotoTick() {") != 1 or "void TestGotoTick();" not in oh:
        raise SystemExit("text check: TestGotoTick is declared once and defined once")
    if "OnlineFixes::TestGotoTick();" not in fe or fe.index("OnlineFixes::Tick();") > fe.index("OnlineFixes::TestGotoTick();"):
        raise SystemExit("text check: the frame hook")
    if fe.count("TestGotoTick") != 1:
        raise SystemExit("text check: one hook line in features.cpp")
    for needle in ("inline std::uint32_t Post(", "inline bool Take(", "inline void Done(", "inline Plan PlanStand(",
                   "inline Knobs ParseKnobs(", "inline bool Converged(", "std::atomic<bool> g_pending"):
        if needle not in tg:
            raise SystemExit("text check: %s missing in the test goto header" % needle)
    for needle in ("inline std::vector<std::string> ObserveWith(", "inline std::vector<std::string> Observe(",
                   "inline ScreenBox ScreenBoxOf(", "inline std::string LineOf(", "BbWindHangFind::GatherCands(",
                   "BbWindHangFind::ClassOf(", "GLINT-PROOF hang goto (r112n)"):
        if needle not in th:
            raise SystemExit("text check: %s missing in the render side header" % needle)
    if th.index("inline ScreenBox ScreenBoxOf(") > th.index("inline Reading ReadingOf("):
        raise SystemExit("text check: ScreenBoxOf must precede ReadingOf")
    if th.index("inline std::string LineOf(") > th.index("inline std::vector<std::string> ObserveWith("):
        raise SystemExit("text check: LineOf must precede ObserveWith")
    if th.index("inline std::vector<std::string> ObserveWith(") > th.index("inline std::vector<std::string> Observe("):
        raise SystemExit("text check: ObserveWith must precede Observe")
    for text in (tg, th):
        if "\t" in text:
            raise SystemExit("text check: a tab in a new file")
    if "r112n: the first look locks the nearest pushed mesh" not in nt or \
            '#include "gpu/shim/bbport_test_goto_hang.h"' not in nt:
        raise SystemExit("text check: the tests are missing")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112N_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NF and "OnceTextM(" not in cur:
            raise SystemExit("REFUSED: r112m_hang-close-proof must be applied (OnceTextM)")
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
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
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
            tmp = full + ".r112ntmp"
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
        tmp = full + ".r112ntmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_ORDER:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
