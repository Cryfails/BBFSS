// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r120_test-camera-lookat, TOOL; goes to the test-tools branch, never a feature branch): BB_TEST_CAMERA, a live test
// knob (set:/unset: in a slot job, or the environment) that puts the follow camera at a place of the test's choosing and holds it
// there, so that the same actions give the same picture in every run. The pure half: the knob's text, the look-at arithmetic,
// the aim-and-place controller (Session), the hold the game thread applies and the capture gate. The render side that drives it
// (the knobs, the camera read from the engine, the mailbox to the world-at read) is bbport_test_camera_run.h.
//
//   BB_TEST_CAMERA=lookat:x,y,z[,dist,yaw_deg,elev_deg]   the camera ends dist metres (default 3) from the world point x,y,z, its
//                                          view heading yaw_deg (0 looks toward +z, 90 toward +x; default: the bearing from where
//                                          the camera is when the knob is set), the point in the middle of the picture
//   BB_TEST_CAMERA=lookat:centre[,dist,yaw,elev]   the world point under the middle of the picture when the knob is set (read from
//                                          the depth buffer, BB_TEST_WORLD_AT's read), remembered as the "kept" point
//   BB_TEST_CAMERA=lookat:kept[,dist,yaw,elev]     the remembered point again (after unset and set: the same place twice)
//   BB_TEST_CAMERA=aim:x,y,z | aim:centre | aim:kept | aim:hang   (r120b) ONLY turns the camera (the two angle fields) from where it
//                                          stands: the hunter is never moved. The follow camera turns about the hunter, so the view that
//                                          looks at the target is the one along the line from that pivot to it. lookat and hang do the
//                                          same when the target is within reach of the camera as it stands (no heading asked, the
//                                          target within 25 m, the look inside the game's pitch limits, and either no distance asked or
//                                          the place it asks for under 1 m away: a hop that short is not worth the floor's risk).
//   BB_TEST_CAMERA=pose:x,y,z,yaw_deg,pitch_deg    the camera at x,z (the hunter is placed so that it ends there; its height
//                                          follows the ground the hunter stands on, the log says how far it is off) looking along
//                                          yaw_deg with pitch_deg (up positive)
//   BB_TEST_CAMERA=hang[,dist,yaw,elev]    the lantern BB_TEST_GOTO=hang locked (dist default 4 m, elev default 30 degrees)
// The separators are , / | _ ; and spaces (the slot runner splits its actions at commas: write lookat:centre/1.5/0/30 there).
//
// What the camera can do: the game's follow camera turns around the hunter by two angle fields (the ones MouseCamera turns), and
// its distance from him and height follow from the angles; it cannot be put in the air. So yaw and pitch are held through the
// fields (HoldApply, in the follow camera's own update), the horizontal place comes from putting the hunter where the camera
// then ends (BbTestGoto's walk, the engine's own co-op bring-to-host call), and the camera's height is whatever the ground the
// hunter stands on gives. dist is the 3 D distance to the target when the height allows it: horizontal = sqrt(dist^2 - dy^2)
// (dy: the target's height over the camera), never less than dy / tan(elev) for a target above the camera (elev: the steepest
// look-up the camera may need; the game's own pitch limit lowers it when the camera cannot look up that far). The hunter stands in
// the view's direction about 3 m past the camera, so a target nearer than that would have him standing beyond it, in the wall: the
// distance is then raised to put him 0.5 m in front of it (the log says so). Which way and how
// far a field turns the view is not known from the code: the first run of a game PROBES it (the fields are turned and the view
// read back from the engine's camera matrices) and the loop then closes on the measured view.
//
// Off (the default; BB_TEST_CAMERA unset or not understood): the game thread's cost is one relaxed load of a false flag in the
// follow camera's update; the render side's is one acquire load of the knobs generation a frame (Wanted); the capture gate is one
// relaxed load of a false flag before any file is touched. Nothing is held, posted or read.

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#include "bbport_test_goto_walk.h"

namespace BbTestCamera {

inline constexpr float kRad = 0.017453292519943295f;
inline constexpr float kDeg = 57.29577951308232f;
inline constexpr float kPi = 3.14159265358979f;

inline constexpr float kDistDefault = 3.0f, kHangDist = 4.0f, kDistLeast = 0.5f, kDistMost = 30.0f; ///< camera to target (3 D, m)
inline constexpr float kElevDefault = 30.0f, kElevLeast = 5.0f, kElevMost = 80.0f; ///< the steepest look-up wanted (degrees)
inline constexpr float kCapFloor = 4.0f;       ///< the pitch limit never lowers the look-up cap below this (degrees)
inline constexpr float kTolPos = 0.35f;        ///< the camera this near its place counts as there (m; the walk's own 'arrived' is 0.3)
inline constexpr float kTolAngle = 1.0f;       ///< heading and pitch this near count as aimed (degrees)
inline constexpr float kCloseAngle = 3.0f;     ///< the hunter is moved only when the angles are this near
inline constexpr float kDriftAngle = 2.5f, kDriftPos = 0.7f; ///< a READY camera that strays this far aims again
inline constexpr float kGain = 0.9f;           ///< the share of an angle error corrected in one step
inline constexpr float kBehind = 0.5f;         ///< the hunter stands at least this far in front of a target (m, horizontal)
inline constexpr float kProbeYaw = 0.35f, kProbePitch = 0.2f; ///< the probe's turns of the fields (radians)
inline constexpr float kRatioLeast = 0.25f, kRatioMost = 4.0f;  ///< a field must turn the view by this many degrees a degree
inline constexpr unsigned kStepFrames = 15, kProbeFrames = 25, kTriesMost = 6, kDriftsMost = 3;
inline constexpr std::uint64_t kTargetWait = 600, kSeenWait = 300, kWalkWait = 1800, kGiveUp = 3600; ///< frames
inline constexpr float kFrameMargin = 0.10f, kFrameMinPx = 6.0f; ///< framed: the middle 80 percent, a box of 6 px at least
inline constexpr unsigned kPictureW = 1920, kPictureH = 1080;    ///< the picture the pixel lists are given in
inline constexpr unsigned kPixelsMost = 8;     ///< BB_TEST_WORLD_AT's pixels
inline constexpr unsigned kCentreCount = 11;   ///< the centre read's pixels (r120c): the middle, four around it, six more (above it and wider)
inline constexpr float kWorldMost = 300.0f;    ///< a depth that gives a view z over this is sky
// r120b_test-camera-aim:
inline constexpr float kReachFar = 25.0f;      ///< a target this near (m, 3 D) counts as within reach of a camera that only turns
inline constexpr float kReachSlack = 1.0f;     ///< lookat with a distance turns only when its place is this near where the camera is (m)
inline constexpr float kPitchRoom = 1.5f;      ///< a look this near the game's pitch limit (degrees) is not counted as reachable
inline constexpr float kPivotDefault = 3.3f;   ///< where the camera turns about, when the hunter is not read: this far past the camera (m)
inline constexpr float kPivotLeast = 0.5f;     ///< a target nearer than this to the pivot has no direction (m)
inline constexpr float kHopMost = 15.0f;       ///< the hunter is never walked farther than this in one hop (m)
inline constexpr float kFallMost = 3.0f;       ///< the hunter this far below where the hold began fell through the floor (m)
inline constexpr float kFarMost = 40.0f;       ///< a camera this far (horizontally, m) from a target it must walk to is not where it was
inline constexpr float kHighMost = 15.0f;      ///< a camera this far (height, m) over or under the target is not where it was
inline constexpr double kFreshSeconds = 3.0;   ///< a READY observation older than this does not take a capture
// r120c_test-camera-aim-fix:
inline constexpr float kCentreMinView = 5.0f;  ///< the centre read skips a world point nearer than this to the camera (the hunter stands 2.7 to 3.6 m ahead)
inline constexpr float kHunterHalf = 0.55f;    ///< the hunter's half width seen from behind, arms and weapon included (m)
inline constexpr float kHunterMargin = 4.0f;   ///< degrees of clear picture between the hunter's edge and an aim: target
inline constexpr float kHunterOffsetMost = 40.0f; ///< the heading is never turned more than this off the target (degrees)
inline constexpr float kHunterBoxHalf = 0.4f, kHunterBoxDown = 0.3f, kHunterBoxUp = 2.2f; ///< the hunter's world box around his place (m), for the cover test
inline constexpr float kStepRoom = 5.0f;       ///< aim:hang backs away until the look-up is this far (degrees) under the game's pitch limit
inline constexpr float kStepFloor = 5.0f;     ///< ... and wants at least this much look-up room (degrees)
inline constexpr float kStepSlack = 0.5f;      ///< a step back shorter than this (m) is not made

// ---- small arithmetic ---------------------------------------------------------------------------------------------------
[[nodiscard]] inline float WrapDeg(float d) {
    d = std::fmod(d + 180.0f, 360.0f);
    if (d < 0.0f) {
        d += 360.0f;
    }
    return d - 180.0f;
}

[[nodiscard]] inline float WrapRad(float r) {
    r = std::fmod(r + kPi, 2.0f * kPi);
    if (r < 0.0f) {
        r += 2.0f * kPi;
    }
    return r - kPi;
}

/// The view's heading (degrees): 0 looks toward +z, 90 toward +x.
[[nodiscard]] inline float HeadingDeg(const float fwd[3]) {
    return std::atan2(fwd[0], fwd[2]) * kDeg;
}

[[nodiscard]] inline float BearingDeg(const float from[3], const float to[3]) {
    return std::atan2(to[0] - from[0], to[2] - from[2]) * kDeg;
}

[[nodiscard]] inline float Dist3(const float a[3], const float b[3]) {
    return std::sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2]));
}

// ---- the knob's text ------------------------------------------------------------------------------------------------------
enum class Kind : std::uint8_t { Off, LookAt, Pose, Hang, Aim };

struct Goal {
    Kind kind = Kind::Off;
    bool bad = false;            ///< text was given and is not understood (kind Off)
    const char* why = "";        ///< what is wrong with it (a literal)
    bool centre = false;         ///< lookat:centre
    bool kept = false;           ///< lookat:kept
    bool from_hang = false;      ///< hang, aim:hang: the target is the locked lantern's middle
    bool stepback = false;       ///< r120c: aim:hang may walk the hunter away from the target when the look-up passes the game's limit
    float point[3] = {};         ///< lookat x,y,z
    float dist = kDistDefault;   ///< camera to target (3 D, m)
    bool dist_set = false;       ///< the text gave a distance (else lookat may only turn the camera, see Session::ChooseMode)
    bool yaw_set = false;
    float yaw = 0.0f;            ///< the view's heading (degrees)
    float elev = kElevDefault;   ///< the steepest look-up (degrees)
    float pos[3] = {};           ///< pose
    float pose_yaw = 0.0f, pose_pitch = 0.0f;
};

inline constexpr unsigned kTokensMost = 8, kTokenLen = 32;

struct Tokens {
    char text[kTokensMost][kTokenLen] = {};
    unsigned n = 0;
    bool overflow = false;
};

[[nodiscard]] inline bool IsSep(char c) {
    return c == ',' || c == '/' || c == '|' || c == '_' || c == ';' || c == ' ' || c == '\t';
}

[[nodiscard]] inline Tokens Tokenize(const char* s) {
    Tokens t;
    unsigned len = 0;
    for (; s != nullptr && *s != 0; ++s) {
        if (IsSep(*s)) {
            if (len != 0) {
                ++t.n;
                len = 0;
            }
            continue;
        }
        if (t.n >= kTokensMost) {
            t.overflow = true;
            break;
        }
        if (len + 1 < kTokenLen) {
            t.text[t.n][len++] = *s;
        } else {
            t.overflow = true;
        }
    }
    if (len != 0 && t.n < kTokensMost) {
        ++t.n;
    }
    return t;
}

[[nodiscard]] inline bool Num(const char* s, float* out) {
    if (s == nullptr || *s == 0) {
        return false;
    }
    char* end = nullptr;
    const float v = std::strtof(s, &end);
    if (end == s || *end != 0 || !std::isfinite(v)) {
        return false;
    }
    *out = v;
    return true;
}

[[nodiscard]] inline bool Word(const char* s, const char* word) {
    for (; *s != 0 && *word != 0; ++s, ++word) {
        if (std::tolower(static_cast<unsigned char>(*s)) != *word) {
            return false;
        }
    }
    return *s == 0 && *word == 0;
}

/// The optional tail of lookat and hang: dist, yaw (or "auto"), elev, from token `i` on. False: not understood.
[[nodiscard]] inline bool ParseTail(const Tokens& t, unsigned i, Goal* g) {
    float v = 0.0f;
    if (t.n > i) {
        if (!Num(t.text[i], &v)) {
            g->why = "the distance is not a number";
            return false;
        }
        g->dist = std::clamp(v, kDistLeast, kDistMost);
        g->dist_set = true;
    }
    if (t.n > i + 1 && !Word(t.text[i + 1], "auto")) {
        if (!Num(t.text[i + 1], &v)) {
            g->why = "the yaw is not a number (or auto)";
            return false;
        }
        g->yaw_set = true;
        g->yaw = WrapDeg(v);
    }
    if (t.n > i + 2) {
        if (!Num(t.text[i + 2], &v)) {
            g->why = "the elevation is not a number";
            return false;
        }
        g->elev = std::clamp(v, kElevLeast, kElevMost);
    }
    if (t.n > i + 3) {
        g->why = "too many values";
        return false;
    }
    return true;
}

/// BB_TEST_CAMERA's text. Empty or null: Off, not bad. Not understood: Off, bad, with why.
[[nodiscard]] inline Goal ParseGoal(const char* text) {
    Goal g;
    if (text == nullptr) {
        return g;
    }
    while (*text == ' ' || *text == '\t') {
        ++text;
    }
    if (*text == 0) {
        return g;
    }
    char mode[16] = {};
    unsigned m = 0;
    while (((*text >= 'a' && *text <= 'z') || (*text >= 'A' && *text <= 'Z')) && m + 1 < sizeof mode) {
        mode[m++] = static_cast<char>(std::tolower(static_cast<unsigned char>(*text)));
        ++text;
    }
    if (*text == ':') {
        ++text;
    }
    const Tokens t = Tokenize(text);
    g.bad = true;
    if (t.overflow) {
        g.why = "too many or too long values";
        return g;
    }
    if (std::strcmp(mode, "lookat") == 0) {
        unsigned i = 0;
        if (t.n >= 1 && (Word(t.text[0], "centre") || Word(t.text[0], "center"))) {
            g.centre = true;
            i = 1;
        } else if (t.n >= 1 && (Word(t.text[0], "kept") || Word(t.text[0], "again"))) {
            g.kept = true;
            i = 1;
        } else {
            if (t.n < 3 || !Num(t.text[0], &g.point[0]) || !Num(t.text[1], &g.point[1]) || !Num(t.text[2], &g.point[2])) {
                g.why = "lookat needs x,y,z, centre or kept";
                return g;
            }
            i = 3;
        }
        if (!ParseTail(t, i, &g)) {
            return g;
        }
        g.kind = Kind::LookAt;
    } else if (std::strcmp(mode, "hang") == 0) {
        g.dist = kHangDist;
        g.from_hang = true;
        if (!ParseTail(t, 0, &g)) {
            return g;
        }
        g.kind = Kind::Hang;
    } else if (std::strcmp(mode, "aim") == 0) { // r120b: only turn the camera (yaw and pitch fields) from where it stands
        if (t.n == 1 && (Word(t.text[0], "centre") || Word(t.text[0], "center"))) {
            g.centre = true;
        } else if (t.n == 1 && (Word(t.text[0], "kept") || Word(t.text[0], "again"))) {
            g.kept = true;
        } else if (t.n == 1 && Word(t.text[0], "hang")) {
            g.from_hang = true;
            g.stepback = true; // r120c
        } else if (t.n == 3 && Num(t.text[0], &g.point[0]) && Num(t.text[1], &g.point[1]) && Num(t.text[2], &g.point[2])) {
            g.centre = false;
        } else {
            g.why = "aim needs x,y,z, centre, kept or hang";
            return g;
        }
        g.kind = Kind::Aim;
    } else if (std::strcmp(mode, "pose") == 0) {
        float v[5] = {};
        if (t.n != 5 || !Num(t.text[0], &v[0]) || !Num(t.text[1], &v[1]) || !Num(t.text[2], &v[2]) || !Num(t.text[3], &v[3]) ||
            !Num(t.text[4], &v[4])) {
            g.why = "pose needs x,y,z,yaw,pitch";
            return g;
        }
        std::memcpy(g.pos, v, sizeof g.pos);
        g.pose_yaw = WrapDeg(v[3]);
        g.pose_pitch = std::clamp(v[4], -80.0f, 80.0f);
        g.kind = Kind::Pose;
    } else {
        g.why = "the mode is not lookat, aim, pose or hang";
        return g;
    }
    g.bad = false;
    g.why = "";
    return g;
}

[[nodiscard]] inline const char* KindName(Kind k) {
    switch (k) {
    case Kind::LookAt:
        return "lookat";
    case Kind::Pose:
        return "pose";
    case Kind::Hang:
        return "hang";
    case Kind::Aim:
        return "aim";
    case Kind::Off:
        break;
    }
    return "off";
}

// ---- BB_TEST_WORLD_AT's text -------------------------------------------------------------------------------------------------
struct Pixel {
    int x = 0, y = 0;
};

struct PixelList {
    std::array<Pixel, kPixelsMost> px{};
    unsigned n = 0;
    bool bad = false;
};

/// "x,y;x,y": whole numbers in pairs, split at any separator (, / | _ ; space), in picture pixels (1920x1080).
[[nodiscard]] inline PixelList ParsePixels(const char* text) {
    PixelList l;
    if (text == nullptr) {
        return l;
    }
    constexpr unsigned most = 2 * kPixelsMost;
    float v[most] = {};
    unsigned count = 0;
    char tok[32] = {};
    unsigned len = 0;
    for (const char* s = text;; ++s) {
        const bool end = *s == 0;
        if (end || IsSep(*s)) {
            if (len != 0) {
                tok[len] = 0;
                float x = 0.0f;
                if (!Num(tok, &x) || count >= most) {
                    l.bad = true;
                    return l;
                }
                v[count++] = x;
                len = 0;
            }
            if (end) {
                break;
            }
            continue;
        }
        if (len + 1 < sizeof tok) {
            tok[len++] = *s;
        } else {
            l.bad = true;
            return l;
        }
    }
    if (count == 0) {
        return l;
    }
    if (count % 2 != 0) {
        l.bad = true;
        return l;
    }
    for (unsigned i = 0; i < count / 2; ++i) {
        l.px[i].x = std::clamp(static_cast<int>(std::lround(v[2 * i])), 0, static_cast<int>(kPictureW) - 1);
        l.px[i].y = std::clamp(static_cast<int>(std::lround(v[2 * i + 1])), 0, static_cast<int>(kPictureH) - 1);
    }
    l.n = count / 2;
    return l;
}

// ---- the camera's matrices (CameraMotion's: 3x4 rows, world to view and back, z forward; projection x and y scales (signed:
// ndc +y down), z scale, z offset; depth = z scale + z offset / view z, as CameraMotion::Near says) -------------------------
struct Screen {
    bool ok = false; ///< the point is in front of the camera
    float x = 0.0f, y = 0.0f, z = 0.0f; ///< pixels of the render size, and the view z
};

[[nodiscard]] inline Screen ScreenOf(const float view[12], const float proj[4], float w, float h, const float p[3]) {
    Screen s;
    const float vx = view[0] * p[0] + view[1] * p[1] + view[2] * p[2] + view[3];
    const float vy = view[4] * p[0] + view[5] * p[1] + view[6] * p[2] + view[7];
    const float vz = view[8] * p[0] + view[9] * p[1] + view[10] * p[2] + view[11];
    if (!(vz > 0.05f) || !std::isfinite(vx + vy + vz)) {
        return s;
    }
    s.ok = true;
    s.z = vz;
    s.x = 0.5f * w * (1.0f + proj[0] * vx / vz);
    s.y = 0.5f * h * (1.0f + proj[1] * vy / vz);
    return s;
}

struct Box {
    bool any = false; ///< at least one corner is in front of the camera
    float x0 = 0.0f, y0 = 0.0f, x1 = 0.0f, y1 = 0.0f;
};

/// The screen rectangle of a world box {min x,y,z, max x,y,z} (its 8 corners that lie in front of the camera).
[[nodiscard]] inline Box BoxOf(const float view[12], const float proj[4], float w, float h, const float b[6]) {
    Box r;
    int in_front = 0;
    for (int i = 0; i < 8; ++i) {
        const float p[3] = {(i & 1) ? b[3] : b[0], (i & 2) ? b[4] : b[1], (i & 4) ? b[5] : b[2]};
        const Screen s = ScreenOf(view, proj, w, h, p);
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
    return r;
}

/// The depth a view z gives (the projection's z scale and offset).
[[nodiscard]] inline float DepthOf(const float proj[4], float view_z) {
    return proj[2] + proj[3] / view_z;
}

/// The world point under a texel: `depth` as the depth buffer holds it, `ndc_x` and `ndc_y` the texel centre's place in the picture
/// (-1 to 1, +y down: 2 (texel + 0.5) / size - 1). False when the depth gives no point in front of the camera within kWorldMost.
[[nodiscard]] inline bool WorldFromDepth(const float inv_view[12], const float proj[4], float depth, float ndc_x, float ndc_y,
                                         float world[3], float* view_z) {
    const float d = depth - proj[2];
    if (!std::isfinite(d) || d == 0.0f || proj[0] == 0.0f || proj[1] == 0.0f) {
        return false;
    }
    const float z = proj[3] / d;
    if (!std::isfinite(z) || !(z > 0.05f) || z > kWorldMost) {
        return false;
    }
    const float vx = ndc_x * z / proj[0], vy = ndc_y * z / proj[1];
    world[0] = inv_view[0] * vx + inv_view[1] * vy + inv_view[2] * z + inv_view[3];
    world[1] = inv_view[4] * vx + inv_view[5] * vy + inv_view[6] * z + inv_view[7];
    world[2] = inv_view[8] * vx + inv_view[9] * vy + inv_view[10] * z + inv_view[11];
    if (view_z != nullptr) {
        *view_z = z;
    }
    return std::isfinite(world[0] + world[1] + world[2]);
}

/// r120c: one pixel of the centre read, worked out (vk_test_world_at.cpp).
struct CentreCandidate {
    bool ok = false;      ///< the depth gave a world point
    float view_z = 0.0f;  ///< m in front of the camera
    float world[3] = {};
};

/// r120c: the centre read's pick. The candidates are in the read's order (the middle first, then the nearest around it, then wider): the first
/// with a world point at least `least` m in front of the camera (the hunter stands 2.7 to 3.6 m ahead and is the middle of the picture); when none
/// is that far, the farthest valid one (`*far_enough` false); -1 when none is valid.
[[nodiscard]] inline int PickCentre(const CentreCandidate* c, unsigned n, float least, bool* far_enough) {
    int best = -1;
    float best_z = 0.0f;
    if (far_enough != nullptr) {
        *far_enough = false;
    }
    for (unsigned i = 0; i < n; ++i) {
        if (!c[i].ok) {
            continue;
        }
        if (c[i].view_z >= least) {
            if (far_enough != nullptr) {
                *far_enough = true;
            }
            return static_cast<int>(i);
        }
        if (c[i].view_z > best_z) {
            best_z = c[i].view_z;
            best = static_cast<int>(i);
        }
    }
    return best;
}

// ---- log lines ------------------------------------------------------------------------------------------------------------
#if defined(__GNUC__) || defined(__clang__)
#define BB_TEST_CAMERA_FORMAT __attribute__((format(printf, 2, 3)))
#else
#define BB_TEST_CAMERA_FORMAT
#endif

BB_TEST_CAMERA_FORMAT inline void Say(std::vector<std::string>& lines, const char* fmt, ...) {
    char body[460];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(body, sizeof body, fmt, ap);
    va_end(ap);
    lines.push_back(std::string("GLINT-PROOF test camera (r120): ") + body);
}

// ---- the aim-and-place controller --------------------------------------------------------------------------------------------
/// Startup-only receipt for the exact sewer R120 hold sequence.
[[nodiscard]] inline bool SewerEpochEnabled() {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_SEWER_R120_EPOCH");
        return value && std::strcmp(value, "1") == 0;
    }();
    return enabled;
}

class Session {
public:
    enum class Phase : std::uint8_t { Idle, Start, Seen, Probe, Aim, Ready, Failed };

    /// What one frame knows (the driver fills it; the tests make it up).
    struct Frame {
        std::uint64_t frame = 0;
        bool cam_ok = false;
        float cam[3] = {}, fwd[3] = {};
        bool view_ok = false;
        float view[12] = {}, proj[4] = {};
        float width = 0.0f, height = 0.0f;
        bool hunter_ok = false;
        float hunter[3] = {};
        bool seen_ok = false; ///< the game thread has published the camera's fields since the hold began
        float seen_yaw = 0.0f, seen_pitch = 0.0f, seen_lowest = 0.0f, seen_highest = 0.0f;
        bool walking = false, pending = false, done_ok = false;
        std::uint32_t done_seq = 0;
        bool centre_ready = false, centre_failed = false, kept_ok = false, kept_yaw_ok = false, hang_ok = false, hang_box_ok = false;
        float centre[3] = {}, kept[3] = {}, kept_yaw = 0.0f, hang_centre[3] = {}, hang_box[6] = {};
        const char* centre_why = "";
    };

    /// What the frame decided.
    struct Out {
        bool hold = false; ///< the game thread holds the camera's fields
        bool cmd_valid = false;
        float cmd_yaw = 0.0f, cmd_pitch = 0.0f; ///< radians
        bool post = false;
        float stand[3] = {}; ///< where to put the hunter
        bool want_centre = false;
        bool remember = false;
        float remember_at[3] = {};
        bool remember_yaw = false; ///< lookat:centre fixed its heading: keep it for lookat:kept
        float remember_yaw_deg = 0.0f;
        bool engaged = false; ///< a picture is held back until framed
        bool framed = false;
        bool failed = false;  ///< r120b: FAILED: the picture stays held back, with the reason in `why`, until the knob is changed
        std::string text, why;
        std::vector<std::string> lines;
    };

    [[nodiscard]] Phase GetPhase() const {
        return phase_;
    }

    /// Start..Ready: the camera is being held.
    [[nodiscard]] bool Busy() const {
        return phase_ != Phase::Idle && phase_ != Phase::Failed;
    }

    struct WalkEvidence {
        unsigned posted = 0, marked_ok = 0;
        std::array<std::uint32_t, 2> marked_sequence{};
    };

    [[nodiscard]] WalkEvidence ReadWalkEvidence() const {
        return {walks_, marked_walks_, marked_sequence_};
    }

    void Begin(const Goal& g, std::uint64_t frame, const char* text, std::vector<std::string>& lines) {
        goal_ = g;
        phase_ = Phase::Start;
        started_ = phase_frame_ = step_at_ = post_frame_ = frame;
        heading_fixed_ = false;
        cap_elev_ = g.elev;
        cap_down_ = 70.0f;
        cmd_on_ = false;
        tries_ = walks_ = drifts_ = 0;
        if (SewerEpochEnabled()) {
            marked_walks_ = 0;
            marked_sequence_ = {};
        }
        waiting_ = false;
        have_last_ = false;
        last_limit_ = false;
        ready_said_ = false;
        said_wait_ = false;
        said_raise_ = false;
        cap_said_ = 0;
        aim_only_ = g.kind == Kind::Aim; // r120b
        mode_decided_ = false;
        fail_why_.clear();
        hunter_y0_ok_ = false;
        stepping_ = false; // r120c
        if (g.kind == Kind::Aim) {
            Say(lines, "BB_TEST_CAMERA=%s: aim: only the camera's two angle fields are turned, the hunter is NOT moved (target: %s)", text,
                g.centre ? "the world under the picture's middle" : g.kept ? "the kept point" : g.from_hang ? "the locked hang mesh's middle" : "x,y,z as asked");
        } else if (g.kind == Kind::Pose) {
            Say(lines, "BB_TEST_CAMERA=%s: pose: camera at x %.2f z %.2f (y follows the ground), heading %.1f, pitch %+.1f degrees",
                text, double(g.pos[0]), double(g.pos[2]), double(g.pose_yaw), double(g.pose_pitch));
        } else {
            Say(lines, "BB_TEST_CAMERA=%s: %s%s%s: %.1f m from the target, %s, at most %.0f degrees of look-up", text,
                KindName(g.kind), g.centre ? " (the world under the picture's middle)" : "", g.kept ? " (the kept point)" : "",
                double(g.dist), g.yaw_set ? "heading as asked" : "heading from where the camera is now", double(g.elev));
        }
    }

    void Release(std::vector<std::string>& lines, const char* why) {
        if (phase_ != Phase::Idle) {
            Say(lines, "released (%s): the game's camera again; %u walks, %u tries", why, walks_, tries_);
        }
        phase_ = Phase::Idle;
        cmd_on_ = false;
    }

    /// The driver posted `out.post`'s request as walk `seq` at `frame`.
    void Posted(std::uint32_t seq, std::uint64_t frame) {
        seq_ = seq;
        post_frame_ = frame;
        waiting_ = true;
        ++walks_;
    }

    [[nodiscard]] Out Tick(const Frame& in) {
        Out o;
        if (phase_ == Phase::Failed) { // r120b: a failed camera holds nothing but still holds the PICTURE back, with the reason
            o.engaged = true;
            o.failed = true;
            o.why = fail_why_;
            return o;
        }
        if (phase_ == Phase::Idle) {
            return o;
        }
        if (in.frame - started_ > kGiveUp && phase_ != Phase::Ready) {
            Fail(o, "the camera did not settle in 3600 frames");
        }
        if (phase_ != Phase::Failed && in.hunter_ok) { // r120b: a hunter who fell through the floor ends the hold at once
            if (!hunter_y0_ok_) {
                hunter_y0_ok_ = true;
                hunter_y0_ = in.hunter[1];
            } else if (in.hunter[1] < hunter_y0_ - kFallMost) {
                char b[200];
                std::snprintf(b, sizeof b, "the hunter fell %.1f m below where he stood when the hold began (y %.2f, was %.2f): the floor did not hold him",
                              double(hunter_y0_ - in.hunter[1]), double(in.hunter[1]), double(hunter_y0_));
                Fail(o, b);
            }
        }
        if (phase_ == Phase::Start) {
            DoStart(in, o);
        } else if (phase_ == Phase::Seen) {
            DoSeen(in, o);
        } else if (phase_ == Phase::Probe) {
            DoProbe(in, o);
        } else if (phase_ == Phase::Aim || phase_ == Phase::Ready) {
            Aim(in, o);
        }
        Finish(in, o);
        return o;
    }

    [[nodiscard]] const float* Target() const {
        return target_;
    }
    [[nodiscard]] float RatioYaw() const {
        return ratio_y_;
    }
    [[nodiscard]] float RatioPitch() const {
        return ratio_p_;
    }

private:
    void Fail(Out& o, const char* why) {
        phase_ = Phase::Failed;
        fail_why_ = std::string("FAILED: ") + why; // r120b: the gate quotes it
        Say(o.lines, "FAILED: %s", why);
    }

    void DoStart(const Frame& in, Out& o) {
        bool ready = false;
        if (goal_.kind == Kind::Pose) {
            ready = true;
        } else if (goal_.centre) {
            if (in.centre_ready) {
                std::memcpy(target_, in.centre, sizeof target_);
                std::memcpy(o.remember_at, in.centre, sizeof o.remember_at);
                o.remember = true;
                ready = true;
            } else if (in.centre_failed) {
                char b[200];
                std::snprintf(b, sizeof b, "the world under the picture's middle was not read: %s", in.centre_why);
                Fail(o, b);
                return;
            } else {
                o.want_centre = true;
            }
        } else if (goal_.kept) {
            if (!in.kept_ok) {
                Fail(o, "no kept point: lookat:centre has not been used in this run");
                return;
            }
            std::memcpy(target_, in.kept, sizeof target_);
            ready = true;
        } else if (goal_.from_hang) {
            if (in.hang_ok) {
                std::memcpy(target_, in.hang_centre, sizeof target_);
                ready = true;
            } else if (!said_wait_ && in.frame - started_ >= 60) {
                said_wait_ = true;
                Say(o.lines, "waiting: no hang target is locked yet (BB_TEST_GOTO=hang with BB_WIND_HANG=1 locks the nearest pushed mesh)");
            }
        } else {
            std::memcpy(target_, goal_.point, sizeof target_);
            ready = true;
        }
        if (!ready) {
            if (in.frame - started_ > kTargetWait) {
                Fail(o, "no target in 600 frames");
            }
            return;
        }
        if (goal_.kind != Kind::Pose) {
            Say(o.lines, "target %.2f %.2f %.2f (%s)", double(target_[0]), double(target_[1]), double(target_[2]),
                goal_.from_hang ? "the locked hang mesh's middle" : goal_.centre ? "under the picture's middle" : goal_.kept ? "kept" : "asked");
            if (in.cam_ok) { // r120b: a camera that is nowhere near the target is not where it was (the hunter fell, or this is another place)
                const float far_h = std::hypot(target_[0] - in.cam[0], target_[2] - in.cam[2]);
                const float far_y = target_[1] - in.cam[1];
                if (std::fabs(far_y) > kHighMost || (!aim_only_ && far_h > kFarMost)) {
                    char b[260];
                    std::snprintf(b, sizeof b,
                                  "the camera (%.1f %.1f %.1f) is %.1f m (horizontally) and %.1f m (in height) from the target: the hunter is not where he "
                                  "was (he fell, or this is another place): no walk is planned from there",
                                  double(in.cam[0]), double(in.cam[1]), double(in.cam[2]), double(far_h), double(far_y));
                    Fail(o, b);
                    return;
                }
            }
        }
        phase_ = Phase::Seen;
        phase_frame_ = in.frame;
    }

    void DoSeen(const Frame& in, Out& o) {
        if (!in.seen_ok || !in.cam_ok) {
            if (in.frame - phase_frame_ > kSeenWait) {
                Fail(o, "the game's camera fields were not seen (the follow camera's hook is off, a loading screen, or lock-on) or the camera is not read");
            }
            return;
        }
        cmd_yaw_ = in.seen_yaw;
        cmd_pitch_ = in.seen_pitch;
        cmd_on_ = true;
        if (ratio_y_ != 0.0f && ratio_p_ != 0.0f) { // learned in an earlier hold of this run
            EnterAim(in, o);
            return;
        }
        f0y_ = in.seen_yaw;
        f0p_ = in.seen_pitch;
        m0h_ = HeadingDeg(in.fwd);
        m0p_ = PitchOfView(in.fwd);
        float up = 1.0e9f, down = 1.0e9f;
        if (in.seen_lowest <= in.seen_highest) {
            up = in.seen_highest - in.seen_pitch;
            down = in.seen_pitch - in.seen_lowest;
        }
        const float room = std::max(up, down);
        if (!(room >= 0.05f)) {
            Fail(o, "the game's pitch limits leave no room to probe the pitch field");
            return;
        }
        cmd_yaw_ = WrapRad(f0y_ + kProbeYaw);
        cmd_pitch_ = f0p_ + (up >= down ? 1.0f : -1.0f) * std::min(kProbePitch, 0.8f * room);
        phase_ = Phase::Probe;
        phase_frame_ = in.frame;
    }

    void DoProbe(const Frame& in, Out& o) {
        if (in.frame - phase_frame_ < kProbeFrames) {
            return;
        }
        if (!in.cam_ok || !in.seen_ok) {
            return;
        }
        const float dfy = WrapRad(in.seen_yaw - f0y_), dfp = in.seen_pitch - f0p_;
        const float dh = WrapDeg(HeadingDeg(in.fwd) - m0h_), dp = PitchOfView(in.fwd) - m0p_;
        if (std::fabs(dfy) < 0.05f || std::fabs(dfp) < 0.02f) {
            Fail(o, "the follow camera did not take the probe's turn of its fields");
            return;
        }
        const float ry = dh / (dfy * kDeg), rp = dp / (dfp * kDeg);
        if (std::fabs(ry) < kRatioLeast || std::fabs(rp) < kRatioLeast) {
            char b[240];
            std::snprintf(b, sizeof b,
                          "the view did not follow the fields: the heading turned %+.1f degrees for %+.1f of the yaw field, the pitch "
                          "%+.1f for %+.1f of the pitch field",
                          double(dh), double(dfy * kDeg), double(dp), double(dfp * kDeg));
            Fail(o, b);
            return;
        }
        ratio_y_ = std::copysign(std::min(std::fabs(ry), kRatioMost), ry);
        ratio_p_ = std::copysign(std::min(std::fabs(rp), kRatioMost), rp);
        Say(o.lines, "probe: the view's heading turns %+.2f degrees for a degree of the yaw field, its pitch %+.2f for a degree of the pitch field",
            double(ratio_y_), double(ratio_p_));
        EnterAim(in, o);
    }

    void EnterAim(const Frame& in, Out& o) {
        ChooseMode(in, o);
        phase_ = Phase::Aim;
        phase_frame_ = step_at_ = in.frame;
        have_last_ = false;
    }

    /// r120b: where the follow camera turns about (the pivot): the hunter's place at the height the camera's own pitch gives (the camera
    /// stands behind it, so its height is the pivot's less horizontal distance times tan pitch); without the hunter, a default stand past the camera.
    static void PivotOf(const Frame& in, float pv[3]) {
        const float pitch = std::clamp(PitchOfView(in.fwd), -75.0f, 75.0f) * kRad;
        if (in.hunter_ok) {
            const float h = std::hypot(in.cam[0] - in.hunter[0], in.cam[2] - in.hunter[2]);
            pv[0] = in.hunter[0];
            pv[1] = in.cam[1] + h * std::tan(pitch);
            pv[2] = in.hunter[2];
        } else {
            for (int i = 0; i < 3; ++i) {
                pv[i] = in.cam[i] + kPivotDefault * in.fwd[i];
            }
        }
    }

    /// r120b: the view pitch (degrees) the camera can reach by turning its pitch field within the game's limits, from where it is now
    /// (the learned ratio; the view pitch is linear in the field). False when the limits or the ratio are not known.
    [[nodiscard]] bool PitchRange(const Frame& in, float* lowest, float* highest) const {
        if (!(in.seen_lowest <= in.seen_highest) || ratio_p_ == 0.0f) {
            return false;
        }
        const float now = PitchOfView(in.fwd);
        const float a = now + ratio_p_ * (in.seen_lowest - in.seen_pitch) * kDeg;
        const float b = now + ratio_p_ * (in.seen_highest - in.seen_pitch) * kDeg;
        *lowest = std::min(a, b);
        *highest = std::max(a, b);
        return true;
    }

    /// r120b: the heading and the pitch (degrees) the view needs to look from the pivot at the target. False: the target is at the pivot.
    [[nodiscard]] bool AimAngles(const Frame& in, float* heading, float* pitch) const {
        float pv[3];
        PivotOf(in, pv);
        const float v[3] = {target_[0] - pv[0], target_[1] - pv[1], target_[2] - pv[2]};
        const float h = std::hypot(v[0], v[2]);
        if (std::hypot(h, v[1]) < kPivotLeast) {
            return false;
        }
        *heading = std::atan2(v[0], v[2]) * kDeg;
        *pitch = std::atan2(v[1], h) * kDeg;
        return true;
    }

    /// r120b: lookat and hang may only turn the camera when the target is within reach of it as it stands: no explicit heading (that needs a
    /// place), the target within kReachFar, the look inside the game's pitch limits, and either no distance asked (the camera stays where it is)
    /// or the place the distance asks for no more than kReachSlack from where the camera is (a hop that short is not worth the risk of the
    /// floor). Decided once, when the angles are first aimed. aim: is always turn-only.
    void ChooseMode(const Frame& in, Out& o) {
        if (mode_decided_ || goal_.kind == Kind::Pose) {
            return;
        }
        mode_decided_ = true;
        if (aim_only_ || goal_.yaw_set || !in.cam_ok) {
            return;
        }
        float want_h = 0.0f, want_p = 0.0f, lo = 0.0f, hi = 0.0f;
        if (!AimAngles(in, &want_h, &want_p) || !PitchRange(in, &lo, &hi) || Dist3(in.cam, target_) > kReachFar ||
            want_p < lo + kPitchRoom || want_p > hi - kPitchRoom) {
            return;
        }
        if (goal_.dist_set) { // what the plan would ask of the hunter: Plan without its side effects
            const bool saved_fixed = heading_fixed_, saved_raise = said_raise_;
            const float saved_h = heading_want_, saved_p = pitch_want_;
            Out scratch;
            float c[2] = {};
            float horiz = 0.0f;
            Plan(in, scratch, c, &horiz);
            const float place_off = std::hypot(c[0] - in.cam[0], c[1] - in.cam[2]);
            heading_fixed_ = saved_fixed;
            said_raise_ = saved_raise;
            heading_want_ = saved_h;
            pitch_want_ = saved_p;
            if (place_off > kReachSlack) {
                return;
            }
        }
        aim_only_ = true;
        Say(o.lines, "the target is within reach of the camera as it stands (%.1f m away, the view needs pitch %+.1f within the game's %+.1f to %+.1f%s): "
                     "only the angle fields are turned, the hunter is NOT moved",
            double(Dist3(in.cam, target_)), double(want_p), double(lo), double(hi),
            goal_.dist_set ? ", and the asked place is under a metre away" : ", no distance asked");
    }

    /// r120c: aim: the heading is turned off the target by this many degrees (the view's heading minus the pivot's bearing to the target) so that
    /// the hunter, who stands on the line from the camera through the pivot, is not in front of the target: his half width (kHunterHalf) seen from
    /// the camera, kHunterMargin degrees clear. The camera swings about the pivot with the heading, so the offset the target shows at is
    /// atan(R sin delta / (R cos delta + d)) (R pivot to target, d camera to pivot, horizontal): delta = theta + asin(d sin theta / R) gives theta.
    [[nodiscard]] float HunterOffset(const Frame& in) const {
        float pv[3];
        PivotOf(in, pv);
        const float big_r = std::hypot(target_[0] - pv[0], target_[2] - pv[2]);
        const float d = in.hunter_ok ? std::hypot(in.cam[0] - in.hunter[0], in.cam[2] - in.hunter[2]) : kPivotDefault;
        if (!(d > 0.3f)) {
            return 0.0f;
        }
        const float theta = std::atan(kHunterHalf / d) * kDeg + kHunterMargin;
        const float s = std::min(0.95f, d * std::sin(theta * kRad) / std::max(big_r, 0.1f));
        return std::min(kHunterOffsetMost, theta + std::asin(s) * kDeg);
    }

    /// r120c: aim:hang only. A look-up (or look-down) that passes the game's pitch limit less kStepRoom degrees cannot be framed by turning: the
    /// hunter is walked AWAY from the target along the ground (on the line from the target through him) until the look is kStepRoom under the
    /// limit. Sets stepping_ and the place (cstar) the camera must be moved to; leaves both alone when no step is needed. `p` is the pitch the
    /// view needs from the pivot (degrees).
    void StepBack(const Frame& in, float p, float cstar[2], float* horiz) {
        float lo = 0.0f, hi = 0.0f;
        if (!goal_.stepback || !in.hunter_ok || tries_ >= kTriesMost || !PitchRange(in, &lo, &hi)) {
            return;
        }
        float pv[3];
        PivotOf(in, pv);
        const float dy = target_[1] - pv[1];
        float hx = pv[0] - target_[0], hz = pv[2] - target_[2]; // from the target to the pivot (the hunter's place)
        const float hp = std::hypot(hx, hz);
        float lim = 0.0f;
        if (p > hi - kStepRoom && dy > 0.0f) {
            lim = std::max(hi - kStepRoom, kStepFloor);
        } else if (p < lo + kStepRoom && dy < 0.0f) {
            lim = std::max(-(lo + kStepRoom), kStepFloor);
        } else {
            return;
        }
        const float need = std::fabs(dy) / std::tan(lim * kRad); // the pivot's horizontal distance from the target that gives the look `lim`
        if (!(need > hp + kStepSlack)) {
            return;
        }
        if (hp < 0.1f) { // right under (or over) the target: away along the camera's side of the hunter
            hx = in.cam[0] - in.hunter[0];
            hz = in.cam[2] - in.hunter[2];
        }
        const float n = std::hypot(hx, hz);
        if (!(n > 0.01f)) {
            hx = 1.0f;
            hz = 0.0f;
        } else {
            hx /= n;
            hz /= n;
        }
        const float step = need - hp;
        cstar[0] = in.cam[0] + step * hx;
        cstar[1] = in.cam[2] + step * hz;
        *horiz = need;
        stepping_ = true;
    }

    /// The plan for this camera: the place the camera should be (x, z), and the heading and pitch it should have.
    void Plan(const Frame& in, Out& o, float cstar[2], float* horiz) {
        if (goal_.kind == Kind::Pose) {
            heading_want_ = goal_.pose_yaw;
            pitch_want_ = goal_.pose_pitch;
            cstar[0] = goal_.pos[0];
            cstar[1] = goal_.pos[2];
            *horiz = 0.0f;
            return;
        }
        if (aim_only_) { // r120b: the camera stays where it is: the view looks from the pivot at the target, planned again each step
            float h = heading_want_, p = pitch_want_;
            if (!AimAngles(in, &h, &p)) {
                char b[160];
                std::snprintf(b, sizeof b, "the target is within %.1f m of the point the camera turns about: no direction to aim along", double(kPivotLeast));
                Fail(o, b);
            }
            heading_want_ = h;
            pitch_want_ = p;
            cstar[0] = in.cam[0];
            cstar[1] = in.cam[2];
            *horiz = std::hypot(target_[0] - in.cam[0], target_[2] - in.cam[2]);
            stepping_ = false; // r120c
            if (goal_.kind == Kind::Aim) {
                heading_want_ = WrapDeg(h + HunterOffset(in)); // the hunter stands beside the line of sight, not in front of the target
                StepBack(in, p, cstar, horiz);
            }
            return;
        }
        if (!heading_fixed_) {
            if (goal_.yaw_set) {
                heading_want_ = goal_.yaw;
            } else if (goal_.kept && in.kept_yaw_ok) {
                heading_want_ = in.kept_yaw; // the heading lookat:centre chose, so that the same place comes twice
            } else {
                heading_want_ = BearingDeg(in.cam, target_);
            }
            heading_fixed_ = true;
            if (goal_.centre) {
                o.remember_yaw = true;
                o.remember_yaw_deg = heading_want_;
            }
        }
        const float dy = target_[1] - in.cam[1];
        const float h2 = goal_.dist * goal_.dist - dy * dy;
        float horizontal = h2 > 1.0f ? std::sqrt(h2) : 1.0f;
        if (dy > 0.0f) {
            horizontal = std::max(horizontal, dy / std::tan(cap_elev_ * kRad));
        } else if (dy < 0.0f) {
            horizontal = std::max(horizontal, -dy / std::tan(cap_down_ * kRad));
        }
        // The hunter stands in the view's direction, as far past the camera as the follow camera keeps it (about 3 m): a target
        // nearer than that would have him standing beyond it, in the wall, so the distance is raised to put him kBehind in front.
        if (in.hunter_ok) {
            const float behind = std::hypot(in.cam[0] - in.hunter[0], in.cam[2] - in.hunter[2]) + kBehind;
            if (horizontal < behind) {
                if (!said_raise_) {
                    said_raise_ = true;
                    Say(o.lines,
                        "the hunter stands %.1f m behind the camera (the follow camera's distance): a target %.1f m away horizontally would have him "
                        "beyond it, in a wall: the camera is put %.1f m from it instead",
                        double(behind - kBehind), double(horizontal), double(behind));
                }
                horizontal = behind;
            }
        }
        cstar[0] = target_[0] - horizontal * std::sin(heading_want_ * kRad);
        cstar[1] = target_[2] - horizontal * std::cos(heading_want_ * kRad);
        pitch_want_ = std::atan2(dy, horizontal) * kDeg;
        *horiz = horizontal;
    }

    void Aim(const Frame& in, Out& o) {
        if (waiting_) {
            if (in.done_seq == seq_) {
                waiting_ = false;
                Say(o.lines, "walk %u %s", seq_, in.done_ok ? "done" : "refused");
                if (!in.done_ok) {
                    Fail(o, "the hunter could not be moved (see the 'hang goto (r112o)' lines)");
                    return;
                }
                if (SewerEpochEnabled()) {
                    if (marked_walks_ < marked_sequence_.size()) {
                        marked_sequence_[marked_walks_] = seq_;
                    }
                    ++marked_walks_;
                }
            } else if (in.frame - post_frame_ > kWalkWait) {
                Fail(o, "the walk was not served in 1800 frames (a loading screen, no hunter, or the engine hook is missing)");
                return;
            }
        }
        const unsigned cadence = phase_ == Phase::Ready ? 2 * kStepFrames : kStepFrames;
        if (in.frame - step_at_ < cadence) {
            return;
        }
        step_at_ = in.frame;
        if (!in.cam_ok || !in.seen_ok) {
            return;
        }
        const bool moved = have_last_ && Dist3(in.cam, last_cam_) > 0.03f;
        std::memcpy(last_cam_, in.cam, sizeof last_cam_);
        have_last_ = true;
        const float heading = HeadingDeg(in.fwd), pitch = PitchOfView(in.fwd);
        float cstar[2] = {};
        float horiz = 0.0f;
        Plan(in, o, cstar, &horiz);
        if (phase_ == Phase::Failed) { // r120b
            return;
        }
        const float eh = WrapDeg(heading_want_ - heading), ep = pitch_want_ - pitch;
        const float e0 = cstar[0] - in.cam[0], e1 = cstar[1] - in.cam[2];
        const float epos = std::hypot(e0, e1);
        if ((!aim_only_ || stepping_) && epos > kHopMost) { // r120b/r120c: no walk of that length (the hunter may have fallen, the camera may be elsewhere)
            char b[240];
            std::snprintf(b, sizeof b, "the camera's place is %.1f m from where the camera is (more than %.0f m): no walk that long is made", double(epos),
                          double(kHopMost));
            Fail(o, b);
            return;
        }
        const bool angles_ok = std::fabs(eh) <= kTolAngle && std::fabs(ep) <= kTolAngle;
        const bool pos_ok = epos <= kTolPos || tries_ >= kTriesMost;
        if (phase_ == Phase::Ready) {
            const bool strayed = std::fabs(eh) > kDriftAngle || std::fabs(ep) > kDriftAngle || epos > kDriftPos;
            if (!strayed || waiting_ || moved) {
                return;
            }
            if (drifts_ >= kDriftsMost) {
                return;
            }
            ++drifts_;
            tries_ = 0;
            phase_ = Phase::Aim;
            ready_said_ = false;
            Say(o.lines, "drifted: heading off %.1f, pitch off %.1f degrees, %.2f m from its place: aiming again", double(eh),
                double(ep), double(epos));
        }
        if (stepping_) { // r120c: aim:hang backs away from the target first (the angles wait: the look passes the game's limit from here)
            if (!waiting_ && !moved && epos > kTolPos && tries_ < kTriesMost && in.hunter_ok) {
                o.post = true;
                o.stand[0] = in.hunter[0] + e0;
                o.stand[1] = in.hunter[1];
                o.stand[2] = in.hunter[2] + e1;
                Say(o.lines,
                    "step back %u: the look at the target needs pitch %+.1f, the game's limit is near: the hunter is walked %.2f m away from it, to %.2f %.2f "
                    "(%.2f m from it horizontally)",
                    tries_ + 1, double(pitch_want_), double(epos), double(o.stand[0]), double(o.stand[2]), double(horiz));
                ++tries_;
            }
            return;
        }

        // the angles: the fields are turned by the error over the learned ratio
        if (std::fabs(eh) > 0.4f) {
            cmd_yaw_ = WrapRad(cmd_yaw_ + kGain * eh * kRad / ratio_y_);
        }
        bool at_limit = false;
        if (std::fabs(ep) > 0.4f) {
            float f = cmd_pitch_ + kGain * ep * kRad / ratio_p_;
            if (in.seen_lowest <= in.seen_highest) {
                const float c = std::clamp(f, in.seen_lowest, in.seen_highest);
                at_limit = c != f;
                f = c;
            }
            cmd_pitch_ = f;
        }
        // the game's pitch limit: two steps in a row at it means the view has settled at its limit; plan for less
        if (at_limit && last_limit_ && std::fabs(ep) > kTolAngle && aim_only_) { // r120b: turning only: no place to back off to
            char b[260];
            std::snprintf(b, sizeof b,
                          "the target needs a view pitch of %+.1f degrees; the game's camera stops at %+.1f (its pitch limit): it cannot be framed by "
                          "turning from here (use lookat with a distance, so that the hunter is moved)",
                          double(pitch_want_), double(pitch));
            Fail(o, b);
            return;
        }
        if (at_limit && last_limit_ && std::fabs(ep) > kTolAngle) {
            if (ep > 0.0f) {
                const float c = std::max(kCapFloor, pitch - 1.0f);
                if (c < cap_elev_ - 0.05f) {
                    cap_elev_ = c;
                    if (cap_said_++ < 3) {
                        Say(o.lines, "the camera looks up %.1f degrees at most (the game's pitch limit): the look-up is planned for %.1f",
                            double(pitch), double(cap_elev_));
                    }
                }
            } else {
                const float c = std::max(kCapFloor, -pitch - 1.0f);
                if (c < cap_down_ - 0.05f) {
                    cap_down_ = c;
                    if (cap_said_++ < 3) {
                        Say(o.lines, "the camera looks down %.1f degrees at most (the game's pitch limit): the look-down is planned for %.1f",
                            double(-pitch), double(cap_down_));
                    }
                }
            }
        }
        last_limit_ = at_limit;
        const bool close = std::fabs(eh) <= kCloseAngle && std::fabs(ep) <= kCloseAngle;
        if (!waiting_ && !moved && epos > kTolPos && close && tries_ < kTriesMost && in.hunter_ok) {
            o.post = true;
            o.stand[0] = in.hunter[0] + e0;
            o.stand[1] = in.hunter[1];
            o.stand[2] = in.hunter[2] + e1;
            Say(o.lines,
                "place %u: the camera at %.2f %.2f %.2f is %.2f m from its place (%.2f, %.2f; %.2f m from the target horizontally): hunter to %.2f %.2f",
                tries_ + 1, double(in.cam[0]), double(in.cam[1]), double(in.cam[2]), double(epos), double(cstar[0]), double(cstar[1]),
                double(horiz), double(o.stand[0]), double(o.stand[2]));
            ++tries_;
            return;
        }
        if (phase_ == Phase::Aim && !waiting_ && !moved && angles_ok && pos_ok) {
            phase_ = Phase::Ready;
            if (!ready_said_) {
                ready_said_ = true;
                char b[220] = "";
                if (goal_.kind != Kind::Pose) {
                    std::snprintf(b, sizeof b, ", %.2f m from the target (horizontal %.2f)", double(Dist3(in.cam, target_)),
                                  double(std::hypot(target_[0] - in.cam[0], target_[2] - in.cam[2])));
                } else {
                    std::snprintf(b, sizeof b, ", y %.2f (the ground's)", double(in.cam[1]));
                }
                Say(o.lines, "READY after %llu frames, %u walk%s%s: camera %.2f %.2f %.2f%s, heading %.1f (asked %.1f), pitch %+.1f (asked %+.1f)",
                    static_cast<unsigned long long>(in.frame - started_), walks_, walks_ == 1 ? "" : "s",
                    epos > kTolPos ? ", the place is only approximate (tries used up)" : "", double(in.cam[0]), double(in.cam[1]),
                    double(in.cam[2]), b, double(heading), double(heading_want_), double(pitch), double(pitch_want_));
            }
        }
    }

    /// The view's pitch (degrees, up positive) from the forward vector.
    [[nodiscard]] static float PitchOfView(const float fwd[3]) {
        return BbTestGoto::PitchDeg(fwd);
    }

    /// Fills the output's hold, command and gate from the state after this frame's decisions.
    void Finish(const Frame& in, Out& o) {
        o.hold = Busy();
        o.cmd_valid = o.hold && cmd_on_;
        o.cmd_yaw = cmd_yaw_;
        o.cmd_pitch = cmd_pitch_;
        o.engaged = Busy() || phase_ == Phase::Failed; // r120b: FAILED holds the picture back too
        o.framed = false;
        if (phase_ == Phase::Failed) {
            o.failed = true;
            o.why = fail_why_;
            return;
        }
        if (!o.engaged) {
            return;
        }
        char b[300];
        if (phase_ != Phase::Ready) {
            o.why = "the camera is not at its place yet";
            return;
        }
        if (goal_.kind == Kind::Pose) {
            std::snprintf(b, sizeof b, "camera %.2f %.2f %.2f, heading %.1f, pitch %+.1f", double(in.cam[0]), double(in.cam[1]),
                          double(in.cam[2]), double(HeadingDeg(in.fwd)), double(PitchOfView(in.fwd)));
            o.text = b;
            o.framed = true;
            return;
        }
        if (!in.view_ok || !(in.width > 0.0f) || !(in.height > 0.0f)) {
            o.why = "the camera's view is not read";
            return;
        }
        const Screen s = ScreenOf(in.view, in.proj, in.width, in.height, target_);
        std::snprintf(b, sizeof b, "camera to target %.2f m (horizontal %.2f m)", double(Dist3(in.cam, target_)),
                      double(std::hypot(target_[0] - in.cam[0], target_[2] - in.cam[2])));
        o.text = b;
        if (!s.ok) {
            o.why = "the target is behind the camera";
            return;
        }
        std::snprintf(b, sizeof b, ", target at pixel %.0f,%.0f of %.0fx%.0f", double(s.x), double(s.y), double(in.width), double(in.height));
        o.text += b;
        if (s.x < kFrameMargin * in.width || s.x > (1.0f - kFrameMargin) * in.width || s.y < kFrameMargin * in.height ||
            s.y > (1.0f - kFrameMargin) * in.height) {
            o.why = "the target's middle is outside the middle 80 percent of the picture";
            return;
        }
        if (goal_.kind == Kind::Aim && in.hunter_ok) { // r120c: the hunter's screen box (his place +-0.4 m, 0.3 m under to 2.2 m over) against the target's pixel
            const float hb[6] = {in.hunter[0] - kHunterBoxHalf, in.hunter[1] - kHunterBoxDown, in.hunter[2] - kHunterBoxHalf,
                                 in.hunter[0] + kHunterBoxHalf, in.hunter[1] + kHunterBoxUp, in.hunter[2] + kHunterBoxHalf};
            const Box hbox = BoxOf(in.view, in.proj, in.width, in.height, hb);
            if (hbox.any) {
                std::snprintf(b, sizeof b, ", hunter box %.0f,%.0f to %.0f,%.0f", double(hbox.x0), double(hbox.y0), double(hbox.x1), double(hbox.y1));
                o.text += b;
                if (s.x >= hbox.x0 && s.x <= hbox.x1 && s.y >= hbox.y0 && s.y <= hbox.y1) {
                    o.why = "the hunter covers the target (its pixel lies inside his screen box)";
                    return;
                }
            }
        }
        if (goal_.from_hang && in.hang_box_ok) {
            const Box box = BoxOf(in.view, in.proj, in.width, in.height, in.hang_box);
            std::snprintf(b, sizeof b, ", lantern box %.0f,%.0f to %.0f,%.0f", double(box.x0), double(box.y0), double(box.x1), double(box.y1));
            o.text += b;
            if (!box.any || std::max(box.x1 - box.x0, box.y1 - box.y0) < kFrameMinPx) {
                o.why = "the lantern's screen box is under 6 px";
                return;
            }
        }
        o.framed = true;
    }

    Goal goal_{};
    Phase phase_ = Phase::Idle;
    std::uint64_t started_ = 0, phase_frame_ = 0, step_at_ = 0, post_frame_ = 0;
    float target_[3] = {};
    bool heading_fixed_ = false;
    float heading_want_ = 0.0f, pitch_want_ = 0.0f, cap_elev_ = kElevDefault, cap_down_ = 70.0f;
    bool cmd_on_ = false;
    float cmd_yaw_ = 0.0f, cmd_pitch_ = 0.0f;
    float ratio_y_ = 0.0f, ratio_p_ = 0.0f; ///< learned: view degrees per field degree (signed); 0: not learned
    float f0y_ = 0.0f, f0p_ = 0.0f, m0h_ = 0.0f, m0p_ = 0.0f;
    unsigned tries_ = 0, walks_ = 0, drifts_ = 0, cap_said_ = 0;
    unsigned marked_walks_ = 0;
    std::array<std::uint32_t, 2> marked_sequence_{};
    bool waiting_ = false, last_limit_ = false, ready_said_ = false, said_wait_ = false, said_raise_ = false, have_last_ = false;
    bool aim_only_ = false, mode_decided_ = false, hunter_y0_ok_ = false; ///< r120b: turn only (no hunter move); mode chosen; fall guard armed
    bool stepping_ = false; ///< r120c: aim:hang is backing away from its target (the plan's place is not where the camera is)
    float hunter_y0_ = 0.0f;
    std::string fail_why_;
    std::uint32_t seq_ = 0;
    float last_cam_[3] = {};
};

// ---- the hold the game thread applies ---------------------------------------------------------------------------------------
// The render side sets the command (radians); the follow camera's update (lantern_free_camera_turn, MouseCamera) calls HoldApply
// once per update while HoldWanted(): it publishes the fields it found (what the game computed, before the override) and the game's
// pitch limits, then writes the command (pitch clamped to the limits). The offsets are the follow camera's (mouse_camera.cpp has
// the same constants and a static_assert that they agree).
inline constexpr std::size_t kPitchAt = 0x140, kYawAt = 0x144, kHighestAt = 0x1ec, kLowestAt = 0x1f0;

inline std::atomic<bool> g_hold_want{false};
inline std::atomic<bool> g_cmd_valid{false};
inline std::atomic<float> g_cmd_yaw{0.0f}, g_cmd_pitch{0.0f};
inline std::atomic<float> g_seen_yaw{0.0f}, g_seen_pitch{0.0f}, g_seen_lowest{0.0f}, g_seen_highest{0.0f};
inline std::atomic<std::uint64_t> g_updates{0};

[[nodiscard]] inline bool HoldWanted() {
    return g_hold_want.load(std::memory_order_relaxed);
}

/// The game thread, once per follow-camera update while HoldWanted(). True: the camera's fields were written (the caller returns).
[[nodiscard]] inline bool HoldApply(std::uint8_t* camera, std::uint8_t* had_input) {
    float pitch = 0.0f, yaw = 0.0f, highest = 0.0f, lowest = 0.0f;
    std::memcpy(&pitch, camera + kPitchAt, 4);
    std::memcpy(&yaw, camera + kYawAt, 4);
    std::memcpy(&highest, camera + kHighestAt, 4);
    std::memcpy(&lowest, camera + kLowestAt, 4);
    if (!std::isfinite(pitch) || !std::isfinite(yaw)) {
        return false;
    }
    g_seen_yaw.store(yaw, std::memory_order_relaxed);
    g_seen_pitch.store(pitch, std::memory_order_relaxed);
    g_seen_lowest.store(lowest, std::memory_order_relaxed);
    g_seen_highest.store(highest, std::memory_order_relaxed);
    g_updates.fetch_add(1, std::memory_order_release);
    if (!g_cmd_valid.load(std::memory_order_acquire)) {
        return false;
    }
    float new_pitch = g_cmd_pitch.load(std::memory_order_relaxed);
    float new_yaw = g_cmd_yaw.load(std::memory_order_relaxed);
    if (!std::isfinite(new_pitch) || !std::isfinite(new_yaw)) {
        return false;
    }
    if (lowest <= highest) {
        new_pitch = std::clamp(new_pitch, lowest, highest);
    }
    new_yaw = WrapRad(new_yaw);
    std::memcpy(camera + kPitchAt, &new_pitch, 4);
    std::memcpy(camera + kYawAt, &new_yaw, 4);
    *had_input = 1;
    return true;
}

// ---- the capture gate -------------------------------------------------------------------------------------------------------
// While BB_TEST_CAMERA holds a camera, the engine's capture trigger file (BB_PRESENT_DUMP_TRIGGER, what the slot runner's capture:
// writes) is left where it is until the camera is READY and the target framed (the target's middle in the middle 80 percent of the
// picture, with the held camera's matrices, published fresh every frame). r120b: while a camera is held this gate is the only one
// (OwnsGate: r112o's is bypassed, its stale observation refused every capture of a READY camera in b64), and a FAILED camera takes
// no picture either: it is refused with the reason until the knob is changed. A released camera (knob unset) holds nothing. The slot
// runner times the trigger out after 20 s and notes it.
struct GateState {
    std::mutex m;
    bool seen = false, framed = false, failed = false;
    std::chrono::steady_clock::time_point at{}, last_log{};
    std::string text, why;
    unsigned taken = 0, refused = 0;
};

inline std::atomic<bool> g_gate_engaged{false};

[[nodiscard]] inline GateState& Gate() {
    static GateState s;
    return s;
}

inline std::atomic<bool> g_bypass_said{false}; // r120b: the once-line about r112o's gate

inline void PublishGate(bool engaged, bool framed, const std::string& text, const std::string& why, bool failed = false) {
    {
        std::lock_guard lock(Gate().m);
        GateState& s = Gate();
        s.seen = true;
        s.framed = framed && !failed;
        s.failed = failed;
        s.at = std::chrono::steady_clock::now();
        s.text = text;
        s.why = why;
    }
    g_gate_engaged.store(engaged, std::memory_order_relaxed);
    if (!engaged) {
        g_bypass_said.store(false, std::memory_order_relaxed);
    }
}

/// r120b: true while this tool holds a camera (READY or not, and also after FAILED): then the capture trigger is THIS gate's alone. The
/// upscaler's trigger consumers skip r112o's framing gate (BbTestGoto::CaptureHeld) when this is true: its observation of the lantern
/// goes stale (71 s old in b64) and refused every capture of a READY camera. Printed once a hold.
[[nodiscard]] inline bool OwnsGate() {
    if (!g_gate_engaged.load(std::memory_order_relaxed)) {
        return false;
    }
    if (!g_bypass_said.exchange(true, std::memory_order_relaxed)) {
        std::printf("GLINT-PROOF test camera (r120): while a camera is held the capture gate is this tool's alone: r112o's framing gate "
                    "(BB_TEST_GOTO) is bypassed, its observation cannot block a capture\n");
    }
    return true;
}

/// The engine's capture trigger asks before it consumes its file: true holds the capture.
[[nodiscard]] inline bool CaptureHeld(const char* trigger) {
    if (!g_gate_engaged.load(std::memory_order_relaxed) || trigger == nullptr || *trigger == 0) {
        return false;
    }
    std::error_code ec;
    if (!std::filesystem::exists(std::filesystem::path(trigger), ec) || ec) {
        return false;
    }
    const std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now();
    std::lock_guard lock(Gate().m);
    GateState& s = Gate();
    const double age = s.seen ? std::chrono::duration<double>(now - s.at).count() : 1.0e9;
    // r120b: a FAILED camera takes no picture (the reason is quoted); a READY one takes it when its last frame is fresh (the render side
    // publishes every frame while the camera is held) and the target is in the middle 80 percent with the held camera's matrices
    const bool take = !s.failed && s.seen && age <= kFreshSeconds && s.framed;
    if (take) {
        ++s.taken;
        std::printf("GLINT-PROOF test camera (r120): capture taken: %s\n", s.text.c_str());
        return false;
    }
    ++s.refused;
    if (std::chrono::duration<double>(now - s.last_log).count() >= BbTestGoto::HoldLogSeconds) {
        s.last_log = now;
        std::printf("GLINT-PROOF test camera (r120): capture refused: %s%s: %s\n", s.failed ? "" : "not framed: ",
                    s.failed ? s.why.c_str() : (!s.seen || age > kFreshSeconds) ? "the camera's state is not fresh (the render side stopped)" : s.why.c_str(),
                    s.text.c_str());
    }
    return true;
}

} // namespace BbTestCamera
