// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>

// bbport (r102_camera-mode-3-4): camera mode's paths (F5 adds a key, Shift+F5 clears the keys, F6
// plays them). A key is a pose of the game's follow camera around the hunter: its yaw and pitch
// (radians, the fields MouseCamera turns) and the orbit's distance factor. Playing starts at the
// camera's pose of the moment and passes through every key on a Catmull-Rom curve, the same time
// per key, easing in over the first and out over the last stretch (at most kEaseMost seconds each).
// MouseCamera plays it in the follow camera's update like the orbit; these rules are pure so
// tests/test_camera_path.cpp can run them.
namespace CameraPath {

constexpr float kPi = 3.14159274f;
constexpr float kRadiansPerDegree = 0.0174532924f;
// Seconds from one key to the next (BB_CAMERA_PATH_S), and the ease at each end of a play.
constexpr float kSecondsDefault = 4.0f, kSecondsLeast = 0.5f, kSecondsMost = 60.0f, kEaseMost = 1.5f;
// Keys kept (F5 refuses more), not counting the pose a play starts from.
constexpr std::size_t kKeysMost = 32;
// The distance factor's range (the orbit's, CameraOrbit::kRadiusLeast..kRadiusMost).
constexpr float kRadiusLeast = 0.5f, kRadiusMost = 1.5f;

struct Key {
    float yaw = 0.0f, pitch = 0.0f, radius = 1.0f;
};

// BB_CAMERA_PATH_S as text: a number inside [kSecondsLeast, kSecondsMost], else the default.
inline float SecondsFrom(const char* text) {
    if (!text || !*text) return kSecondsDefault;
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    if (end == text || !std::isfinite(v) || v < kSecondsLeast || v > kSecondsMost) return kSecondsDefault;
    return v;
}

// Moves each key's yaw by whole turns so that it lies within half a turn of the key before it: the
// camera takes the short way round between keys, as the follow camera's yaw wraps at +-pi.
inline void Unwrap(Key* keys, std::size_t n) {
    for (std::size_t i = 1; i < n; ++i) {
        float d = keys[i].yaw - keys[i - 1].yaw;
        for (int k = 0; k < 64 && d > kPi; ++k) d -= 2 * kPi;
        for (int k = 0; k < 64 && d < -kPi; ++k) d += 2 * kPi;
        keys[i].yaw = keys[i - 1].yaw + d;
    }
}

// Uniform Catmull-Rom between p1 (t = 0) and p2 (t = 1).
inline float CatmullRom(float p0, float p1, float p2, float p3, float t) {
    const float t2 = t * t, t3 = t2 * t;
    return 0.5f * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (3 * p1 - p0 - 3 * p2 + p3) * t3);
}

// The pose at u in [0, n - 1] (key i at u = i), the end keys repeated beyond the ends. The radius
// stays inside the orbit's range; the pitch is clamped by the caller to the game's limits.
inline Key Sample(const Key* keys, std::size_t n, float u) {
    if (n == 0) return {};
    if (n == 1) return keys[0];
    u = std::clamp(u, 0.0f, float(n - 1));
    const std::size_t i = std::min(std::size_t(u), n - 2);
    const float t = u - float(i);
    const Key& a = keys[i ? i - 1 : 0];
    const Key& b = keys[i];
    const Key& c = keys[i + 1];
    const Key& d = keys[std::min(i + 2, n - 1)];
    Key k;
    k.yaw = CatmullRom(a.yaw, b.yaw, c.yaw, d.yaw, t);
    k.pitch = CatmullRom(a.pitch, b.pitch, c.pitch, d.pitch, t);
    k.radius = std::clamp(CatmullRom(a.radius, b.radius, c.radius, d.radius, t), kRadiusLeast, kRadiusMost);
    return k;
}

// The time of a play through n poses (the start pose and the keys), seconds_per_key between two:
// a cruise at one pose per seconds_per_key, with an ease of `ease` seconds at each end in which
// the speed rises from 0 and falls back to 0 evenly (so a play takes `ease` longer than the cruise).
struct Timing {
    float span = 0.0f;    // n - 1: the parameter u runs from 0 to span
    float rate = 0.0f;    // u per second while cruising
    float ease = 0.0f;    // seconds
    float total = 0.0f;   // seconds
};
inline Timing TimingFor(std::size_t n, float seconds_per_key) {
    Timing t;
    if (n < 2 || !(seconds_per_key > 0.0f)) return t;
    t.span = float(n - 1);
    t.rate = 1.0f / seconds_per_key;
    const float cruise = t.span * seconds_per_key;
    t.ease = std::min(kEaseMost, cruise);
    t.total = cruise + t.ease;
    return t;
}

// u at `seconds` into the play: 0 at the start, span from total on; continuous with a continuous
// speed (no step in speed anywhere, so no visible jolt).
inline float Progress(const Timing& t, float seconds) {
    if (t.total <= 0.0f) return t.span;
    if (seconds <= 0.0f) return 0.0f;
    if (seconds >= t.total) return t.span;
    if (t.ease <= 0.0f) return std::min(t.span, t.rate * seconds);
    if (seconds < t.ease) return t.rate * seconds * seconds / (2 * t.ease);
    if (seconds <= t.total - t.ease) return t.rate * (seconds - 0.5f * t.ease);
    const float left = t.total - seconds;
    return t.span - t.rate * left * left / (2 * t.ease);
}

// One key as a line of the path file: yaw and pitch in degrees, then the distance factor.
inline int Format(const Key& k, char* out, std::size_t size) {
    return std::snprintf(out, size, "%.3f %.3f %.3f", double(k.yaw / kRadiansPerDegree),
                         double(k.pitch / kRadiansPerDegree), double(k.radius));
}

// A line of the path file; false for a comment (#), an empty line or anything that is not three
// finite numbers. Yaw is wrapped into [-180, 180) degrees, the radius clamped to its range.
inline bool Parse(const char* line, Key& k) {
    float yaw = 0, pitch = 0, radius = 1;
    if (!line || line[0] == '#' || std::sscanf(line, "%f %f %f", &yaw, &pitch, &radius) != 3) return false;
    if (!std::isfinite(yaw) || !std::isfinite(pitch) || !std::isfinite(radius)) return false;
    if (std::fabs(pitch) > 90.0f) return false;
    yaw = std::fmod(yaw + 180.0f, 360.0f);
    if (yaw < 0) yaw += 360.0f;
    k.yaw = (yaw - 180.0f) * kRadiansPerDegree;
    k.pitch = pitch * kRadiansPerDegree;
    k.radius = std::clamp(radius, kRadiusLeast, kRadiusMost);
    return true;
}

}
