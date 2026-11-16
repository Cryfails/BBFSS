// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdlib> // bbport (r102b_camera-clean-hud): AutoSpeedFrom

// Camera mode's orbit (F4, or L3 + D-pad Right in play): the game's own follow camera turns around
// the hunter by itself, for turntable shots. MouseCamera applies these rules in the follow camera's
// update (lantern_free_camera_turn); they are pure so tests/test_camera_orbit.cpp can run them.
// Turning speed, pitch and distance each follow a critically damped spring, so a start, a stop or a
// step eases in and out at any frame rate. From rest a spring never overshoots its target; a step
// pressed while it still moves fast toward the last one can carry it a little past the new one.
namespace CameraOrbit {

constexpr float kRadiansPerDegree = 0.0174532924f;
constexpr float kPi = 3.14159274f;

// Turning speed in degrees a second; negative turns the other way, 0 holds the camera still.
constexpr float kSpeedStart = 12.0f, kSpeedStep = 3.0f, kSpeedMost = 45.0f;
// Height: steps of 5 degrees of the camera's pitch from the pitch it had when the orbit started,
// inside the game's own pitch limits.
constexpr float kHeightStep = 5.0f;
constexpr int kHeightStepsMost = 8;
// Radius: a factor on the follow camera's distance (LockCamParam, through Camera::Tick), the same
// range as the Camera distance setting.
constexpr float kRadiusStep = 0.1f, kRadiusLeast = 0.5f, kRadiusMost = 1.5f;
// Smoothing times in seconds; the longest step one update may take.
constexpr float kRateTime = 0.8f, kPitchTime = 0.6f, kRadiusTime = 0.8f, kLongestStep = 0.1f;

struct Spring {
    float value = 0.0f, velocity = 0.0f;
};

// Moves the spring toward target over dt seconds; critically damped, exact for any dt.
inline void Approach(Spring& s, float target, float smooth_time, float dt) {
    const float omega = 2.0f / smooth_time;
    const float x = s.value - target;
    const float e = std::exp(-omega * dt);
    const float t = (s.velocity + omega * x) * dt;
    s.velocity = (s.velocity - omega * t) * e;
    s.value = target + (x + t) * e;
}

inline float Wrap(float angle) {
    for (int i = 0; i < 64 && angle > kPi; ++i) angle -= 2 * kPi;
    for (int i = 0; i < 64 && angle < -kPi; ++i) angle += 2 * kPi;
    return angle;
}

inline float NextSpeed(float speed, int step) {
    return std::clamp(std::round(speed / kSpeedStep + float(step)) * kSpeedStep, -kSpeedMost, kSpeedMost);
}

inline int NextHeight(int steps, int step) { return std::clamp(steps + step, -kHeightStepsMost, kHeightStepsMost); }

// The height steps that keep the pitch inside the game's limits [lowest, highest] from the pitch
// base at the start, and inside kHeightStepsMost either way. Limits not in order (or not numbers),
// or a base that is not a number, leave no steps, as Step then leaves the pitch to the game.
struct HeightRange {
    int least = 0, most = 0;
};
inline HeightRange HeightRangeFrom(float base, float lowest, float highest) {
    if (!std::isfinite(base) || !(lowest <= highest)) return {};
    const float step = kHeightStep * kRadiansPerDegree, most = float(kHeightStepsMost);
    const float up = std::clamp(std::floor((highest - base) / step + 1e-3f), 0.0f, most);
    const float down = std::clamp(std::floor((base - lowest) / step + 1e-3f), 0.0f, most);
    return {-int(down), int(up)};
}

inline float NextRadius(float radius, int step) {
    return std::clamp(std::round(radius / kRadiusStep + float(step)) * kRadiusStep, kRadiusLeast, kRadiusMost);
}

struct Targets {
    bool on = false;      // false eases out: turning to 0, radius to 1, the pitch stays where it is
    float speed = 0.0f;   // degrees a second
    float pitch = 0.0f;   // radians, before the game's limits
    float radius = 1.0f;
};

struct Run {
    Spring rate;              // radians a second
    Spring pitch;             // radians
    Spring radius{1.0f, 0.0f};
};

struct Pose {
    float pitch, yaw;
};

// One camera update: eases the springs toward the targets and turns the yaw by the eased rate.
// The pitch stays inside [lowest, highest]; limits that are not in order leave it as it is.
inline Pose Step(Run& r, const Targets& t, float dt, float pitch, float yaw, float lowest, float highest) {
    dt = std::clamp(dt, 0.0f, kLongestStep);
    Approach(r.rate, t.on ? t.speed * kRadiansPerDegree : 0.0f, kRateTime, dt);
    Approach(r.radius, t.on ? t.radius : 1.0f, kRadiusTime, dt);
    if (lowest <= highest) {
        Approach(r.pitch, t.on ? std::clamp(t.pitch, lowest, highest) : r.pitch.value, kPitchTime, dt);
        pitch = std::clamp(r.pitch.value, lowest, highest);
    }
    return {pitch, Wrap(yaw + r.rate.value * dt)};
}

// The radius is back at rest: within 0.002 of 1, moving less than 0.01 a second.
inline bool RadiusHome(const Spring& radius) {
    return std::fabs(radius.value - 1.0f) < 0.002f && std::fabs(radius.velocity) < 0.01f;
}

// After a stop: the turning and the radius are back at rest (below 0.1 degrees a second, and
// RadiusHome), so the orbit can end without a visible jump.
inline bool Settled(const Run& r) {
    constexpr float kStill = 0.1f * kRadiansPerDegree;
    return std::fabs(r.rate.value) < kStill && std::fabs(r.rate.velocity) < kStill && RadiusHome(r.radius);
}

// bbport (r102b_camera-clean-hud): BB_CAMERA_ORBIT's speed in degrees a second: a number, clamped to
// +-kSpeedMost (below 0 the other way round). 0 (off) for none, an empty value, text after the
// number, or a value that is not a finite number.
inline float AutoSpeedFrom(const char* value) {
    if (!value || !*value) return 0.0f;
    char* end = nullptr;
    const float v = std::strtof(value, &end);
    if (end == value || *end || !std::isfinite(v)) return 0.0f;
    return std::clamp(v, -kSpeedMost, kSpeedMost);
}

// After an early end (the stick or the mouse, or the game took the camera) the yaw and the pitch
// are the game's again at once, and only the radius eases back to 1 over the following updates.
// True once it is home; it is then exactly 1.
inline bool EaseRadiusHome(Spring& radius, float dt) {
    Approach(radius, 1.0f, kRadiusTime, std::clamp(dt, 0.0f, kLongestStep));
    if (!RadiusHome(radius)) return false;
    radius = {1.0f, 0.0f};
    return true;
}

}
