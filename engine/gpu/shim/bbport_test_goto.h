// SPDX-License-Identifier: GPL-3.0-or-later
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
