// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdlib> // bbport (r102b_camera-clean-hud): AutoSpeedFrom

// Camera mode (F4, or L3 + D-pad Right in play): the game's own follow camera turns around the
// hunter, for stills and turntable shots, while the game gets no input. The mouse or the arrow keys
// (the right stick on a pad) turn it by hand; BB_CAMERA_ORBIT adds a turn of its own. MouseCamera
// applies these rules in the follow camera's update (lantern_free_camera_turn); they are pure so
// tests/test_camera_orbit.cpp can run them.
// Turning speed, pitch and distance each follow a critically damped spring, so a start, a stop or a
// step eases in and out at any frame rate. From rest a spring never overshoots its target; a step
// pressed while it still moves fast toward the last one can carry it a little past the new one.
namespace CameraOrbit {

constexpr float kRadiansPerDegree = 0.0174532924f;
constexpr float kPi = 3.14159274f;

// Turning speed in degrees a second (BB_CAMERA_ORBIT); negative turns the other way, 0 holds the camera still.
constexpr float kSpeedMost = 45.0f;
// Radius: a factor on the follow camera's distance (LockCamParam, through Camera::Tick), the same
// range as the Camera distance setting. A wheel notch or a + / - key moves it by kRadiusStep.
constexpr float kRadiusStep = 0.1f, kRadiusLeast = 0.5f, kRadiusMost = 1.5f;
// Smoothing times in seconds; the longest step one update may take.
constexpr float kRateTime = 0.8f, kPitchTime = 0.6f, kRadiusTime = 0.8f, kLongestStep = 0.1f;
// bbport (r124_camera-mode-keys): the hand's look. The arrow keys and the right stick turn at most
// kLookYawDegrees a second sideways and kLookPitchDegrees a second up or down, the triggers move the
// radius factor by kZoomPerSecond a second; their smoothing times are shorter than the orbit's, so
// the view follows the hand. The stick's dead zone is kStickDead of full deflection.
constexpr float kLookYawDegrees = 60.0f, kLookPitchDegrees = 40.0f, kZoomPerSecond = 0.5f;
constexpr float kLookRateTime = 0.2f, kLookPitchTime = 0.15f, kStickDead = 0.15f;

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
// rate_time and pitch_time are the springs' smoothing times (the defaults are the orbit's).
inline Pose Step(Run& r, const Targets& t, float dt, float pitch, float yaw, float lowest, float highest,
                 float rate_time = kRateTime, float pitch_time = kPitchTime) {
    dt = std::clamp(dt, 0.0f, kLongestStep);
    Approach(r.rate, t.on ? t.speed * kRadiansPerDegree : 0.0f, rate_time, dt);
    Approach(r.radius, t.on ? t.radius : 1.0f, kRadiusTime, dt);
    if (lowest <= highest) {
        Approach(r.pitch, t.on ? std::clamp(t.pitch, lowest, highest) : r.pitch.value, pitch_time, dt);
        pitch = std::clamp(r.pitch.value, lowest, highest);
    }
    return {pitch, Wrap(yaw + r.rate.value * dt)};
}

// The radius is back at rest: within 0.002 of 1, moving less than 0.01 a second.
inline bool RadiusHome(const Spring& radius) {
    return std::fabs(radius.value - 1.0f) < 0.002f && std::fabs(radius.velocity) < 0.01f;
}

// After a stop: the turning and the radius are back at rest (below 0.1 degrees a second, and
// RadiusHome), so camera mode can end without a visible jump.
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

// bbport (r124_camera-mode-keys): one stick or trigger reading of SDL (-32768..32767) as -1..1, with
// the dead zone taken off (kStickDead of full deflection reads 0, full deflection reads 1). A trigger
// is read the same way from 0..32767 (0..1).
inline float AxisUnit(int raw) {
    const float v = std::clamp(float(raw) / 32767.0f, -1.0f, 1.0f);
    const float a = std::fabs(v);
    if (a <= kStickDead) return 0.0f;
    const float s = (a - kStickDead) / (1.0f - kStickDead);
    return v < 0.0f ? -s : s;
}

// The two held directions' sum (the arrow keys and the stick), kept in -1..1; not a number reads 0.
inline float LookAxis(float a, float b) {
    const float v = a + b;
    return std::isfinite(v) ? std::clamp(v, -1.0f, 1.0f) : 0.0f;
}

// The turning speed target in degrees a second: BB_CAMERA_ORBIT's speed plus the hand's.
inline float LookSpeed(float auto_speed, float axis) {
    return std::clamp(auto_speed + axis * kLookYawDegrees, -kSpeedMost - kLookYawDegrees, kSpeedMost + kLookYawDegrees);
}

// The pitch target after one update: the held up/down axis (positive looks down, as the mouse
// moving down does) and the mouse's turn down (radians) added, then kept inside the game's limits
// [lowest, highest]; limits not in order leave it unclamped. Anything not a number keeps the old goal.
inline float LookPitch(float goal, float axis, float mouse_down, float dt, float lowest, float highest) {
    dt = std::clamp(dt, 0.0f, kLongestStep);
    const float next = goal + axis * kLookPitchDegrees * kRadiansPerDegree * dt + mouse_down;
    if (!std::isfinite(next)) return goal;
    return lowest <= highest ? std::clamp(next, lowest, highest) : next;
}

// The radius factor after dt seconds of a held zoom axis (positive moves the camera farther), inside
// the radius range.
inline float ZoomRadius(float radius, float axis, float dt) {
    dt = std::clamp(dt, 0.0f, kLongestStep);
    const float next = radius + axis * kZoomPerSecond * dt;
    return std::isfinite(next) ? std::clamp(next, kRadiusLeast, kRadiusMost) : radius;
}

}
