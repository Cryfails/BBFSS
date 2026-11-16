// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r105_cloud-shadows): FEATURE. Slow moving cloud shadows (BB_CLOUD_SHADOWS): the knobs,
// the direction rule, the drift and the push words of host_shaders/cloud_shadow.comp. Pure: no
// Vulkan, no settings, no environment (vk_cloud_shadow.cpp reads the variables once and passes
// their text to MakeKnobs). Tested by tests/test_cloud_shadows.cpp.
//
// The mask (cloud_shadow.comp's cloud_light): a world point p goes along the light to a plane,
// q = p.xz - p.y * Slope(L) (Plane), and n = 0.5 + the sum of Weight[k] (N_k - 0.5) of the three
// value noises of r94's fog noise lattice (volumetric_fog_noise.h, host_shaders/fog_noise.glsl),
// read at (q.x, 0, q.y) / size minus each octave's offset (Drift::Cells). The light kept there is
// Light(n) = 1 - depth * smoothstep(low, high, n): 1 (no cloud) below low, 1 - depth (a full
// cloud) above high. depth = strength * FullDepth. Over the world n has a mean of 0.50 and a
// spread (sd) of 0.13 (CPU probe of 60000 points, scratch r105_noise_sim.py); with the default
// edges (r105b) 41% of the ground is clear, 25% under a full cloud, 34% in between, and the
// mean light kept at strength 1 is 0.75 of the sun term (with BB_CLOUD_SHADOWS_SHOW: 28% clear,
// 39% full, mean 0.53). r105b chose the size and edges by what a viewer sees (scratch
// r105b_noise_sim.py, 1500 random 60 m stretches of ground): half of them hold an edge of 0.30
// of the light or more (r105's 160 m, 0.48-0.64 and 0.45: a fifth, so its stills showed an
// even dimming or none).
//
// The drift (r105b: one wind for the sun fog, the plants and the clouds): Drift (r94's, shared)
// is advanced with a "wind" of SpeedRatio times the wind's mean speed (BB_WIND_SPEED, else
// BbWind::DefaultSpeed, read by the rule of Rasterizer::WindOnFrameEnd: Number, then
// BbWind::Sanitize, whether BB_WIND is on or not) toward the clouds' direction across xz and, in
// its third axis, a morph rate that moves the largest octave one lattice cell every MorphSeconds
// (the finer ones 1.3 and 1.7 times as fast, divided by their ratio, as Drift moves them), so
// the shapes change slowly while they pass. The wind's gusts do not move the clouds.
// The direction (deg, 0 = +x, 90 = +z, the way the clouds move, as the wind's): with BB_WIND=1
// the wind's own direction at that frame (its wander included), whatever BB_CLOUDS_DIR says, so
// the sun fog's drift, the plants' sway and the cloud shadows go one way; else BB_CLOUDS_DIR
// when it is a number; else, when it is "auto", across the light, atan2(L.z, L.x) + 90 deg
// (the clouds cross the moon or sun sideways in the view toward it), eased toward that with an
// 8 s time constant along the shorter arc (which side "+90" is on screen is not checked: the
// handedness of the game's world); else (missing or other text) the direction the wind would
// blow: BB_WIND_DIR, else BbWind::DefaultDirection, with BbWind::WanderDeg's wander on the
// clouds' own clock.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring> // bbport (r105b_clouds-visible): strcmp
#include <limits>

#include "volumetric_fog_noise.h"
// bbport (r105b_clouds-visible): the shared wind's defaults, sanitizer and wander (a path
// relative to this file, so the pure test still builds with -I. only)
#include "../../../shim/bbport_wind.h"

namespace CloudShadows {

inline constexpr float MaxStrength = 1.0f;     ///< BB_CLOUD_SHADOWS's clamp
// bbport (r105b_clouds-visible): FullDepth, DefaultScale, Low and High are r105b's (r105: 0.45,
// 160 m, 0.48 and 0.64); the speeds are multiples of the wind's.
inline constexpr float FullDepth = 0.60f;      ///< share of the sun term a full cloud takes at strength 1
inline constexpr float ShowDepth = 0.85f;      ///< BB_CLOUD_SHADOWS_SHOW=1: that share
inline constexpr float DefaultScale = 100.0f;  ///< m: BB_CLOUD_SHADOWS_SCALE, the largest cells
inline constexpr float ShowScale = 70.0f;      ///< m: the size with BB_CLOUD_SHADOWS_SHOW=1
inline constexpr float MinScale = 40.0f, MaxScale = 600.0f; ///< BB_CLOUD_SHADOWS_SCALE's clamp
inline constexpr float Low = 0.47f, High = 0.59f;         ///< n's edges (clear below, full above)
inline constexpr float ShowLow = 0.42f, ShowHigh = 0.54f; ///< with BB_CLOUD_SHADOWS_SHOW=1
/// The largest patches travel at this many times the wind's mean speed (6 m/s at
/// BbWind::DefaultSpeed, 1.5 m/s: clouds aloft move faster than the wind at the ground).
inline constexpr float SpeedRatio = BbWind::CloudRatio; // bbport (r116_wind-one-source): one ratio
inline constexpr float ShowSpeedRatio = 10.0f; ///< with BB_CLOUD_SHADOWS_SHOW=1 (15 m/s at 1.5)
inline constexpr double MorphSeconds = 120.0;  ///< s per lattice cell of the largest octave's morph
inline constexpr float MinLightY = 0.1f;       ///< Slope's floor of L.y (a light 6 deg up or lower)
inline constexpr double EaseSeconds = 8.0;     ///< s: the auto direction's time constant
inline constexpr float AutoTurn = 90.0f;       ///< deg: auto is the light's azimuth plus this
inline constexpr float StartDirection = 225.0f; ///< deg: auto before any light (the wind's default)
inline constexpr double MaxStep = 0.1;         ///< s: the longest step one Advance takes
inline constexpr std::uint32_t PeriodFrames = 600; ///< the periodic log line (2 s with SHOW)
inline constexpr double ShowPeriod = 2.0;      ///< s

/// The value of `text` when it starts with a finite number, else `fallback` (r94's Number).
inline float Number(const char* text, float fallback) {
    return VolumetricFogNoise::Number(text, fallback);
}

/// v wrapped into [0, 360); a value that is not finite gives 0.
inline float Wrap360(float v) {
    if (!std::isfinite(v)) {
        return 0.0f;
    }
    float r = std::fmod(v, 360.0f);
    if (r < 0.0f) {
        r += 360.0f;
    }
    return r >= 360.0f ? 0.0f : r;
}

/// BB_CLOUD_SHADOWS: 0 (off) when missing, empty, not a number or not finite; else clamped to
/// 0-MaxStrength.
inline float ParseStrength(const char* text) {
    return std::clamp(Number(text, 0.0f), 0.0f, MaxStrength);
}

/// BB_CLOUD_SHADOWS_SCALE (m): `fallback` when missing or not a number; else clamped to
/// MinScale-MaxScale.
inline float ParseScale(const char* text, float fallback) {
    return std::clamp(Number(text, fallback), MinScale, MaxScale);
}

// bbport (r105b_clouds-visible): auto's start is the wind's default, tied (rule 10)
static_assert(StartDirection == BbWind::DefaultDirection, "the wind's default");

/// Where the clouds' direction comes from (r105b): the wind (BB_WIND=1, whatever BB_CLOUDS_DIR
/// says), BB_CLOUDS_DIR's number, auto (BB_CLOUDS_DIR=auto), or the direction the wind would
/// blow while BB_WIND is off (WindKnob).
enum class Source : std::uint32_t { Env, Wind, Auto, WindKnob };

inline const char* SourceName(Source s) {
    return s == Source::Env    ? "BB_CLOUDS_DIR"
           : s == Source::Wind ? "the wind"
           : s == Source::Auto ? "auto"
                               : "the wind's direction, BB_WIND off";
}

/// BB_CLOUDS_DIR: Env and the degrees wrapped into [0, 360) when it starts with a finite number;
/// Auto when it is exactly "auto"; else (missing, empty or other text) WindKnob (r105b; r105
/// took auto for all of these).
inline Source ParseDirection(const char* text, float* deg) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float v = Number(text, nan);
    if (std::isfinite(v)) {
        *deg = Wrap360(v);
        return Source::Env;
    }
    return text != nullptr && std::strcmp(text, "auto") == 0 ? Source::Auto : Source::WindKnob;
}

struct Knobs {
    float strength = 0.0f; ///< 0: off
    float scale = DefaultScale;
    bool show = false;
    Source dir = Source::WindKnob; ///< BB_CLOUDS_DIR: Env, Auto or WindKnob
    float dir_deg = 0.0f;
    /// r105b: the wind's base direction (deg) and mean speed (m/s) as Rasterizer::WindOnFrameEnd
    /// reads them (BB_WIND_DIR, BB_WIND_SPEED), whether BB_WIND is on or not
    float wind_deg = BbWind::DefaultDirection;
    float wind_speed = BbWind::DefaultSpeed;
    bool On() const {
        return strength > 0.0f;
    }
    float Depth() const {
        return strength * (show ? ShowDepth : FullDepth);
    }
    float LowEdge() const {
        return show ? ShowLow : Low;
    }
    float HighEdge() const {
        return show ? ShowHigh : High;
    }
    /// m/s: SpeedRatio (ShowSpeedRatio with SHOW) times the wind's mean speed (r105b)
    float Velocity() const {
        return wind_speed * (show ? ShowSpeedRatio : SpeedRatio);
    }
};

/// The knobs from the variables' text (null: not set). BB_CLOUD_SHADOWS_SHOW starting with 1 turns
/// the shadows on at MaxStrength with the show look (ShowDepth, the show edges, ShowSpeedRatio
/// and, unless BB_CLOUD_SHADOWS_SCALE says otherwise, ShowScale), whatever BB_CLOUD_SHADOWS says.
/// r105b: wind_dir and wind_speed are BB_WIND_DIR's and BB_WIND_SPEED's text, read as
/// Rasterizer::WindOnFrameEnd reads them (Number with the wind's defaults, then BbWind::Sanitize:
/// the direction wrapped into [0, 360), the speed clamped to 0-BbWind::MaxSpeed).
inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show, const char* dir,
                       const char* wind_dir = nullptr, const char* wind_speed = nullptr) {
    Knobs knobs;
    knobs.show = show != nullptr && show[0] == '1';
    knobs.strength = knobs.show ? MaxStrength : ParseStrength(strength);
    knobs.scale = ParseScale(scale, knobs.show ? ShowScale : DefaultScale);
    knobs.dir = ParseDirection(dir, &knobs.dir_deg);
    BbWind::Params wind{};
    wind.on = true;
    wind.direction_deg = Number(wind_dir, BbWind::DefaultDirection);
    wind.speed = Number(wind_speed, BbWind::DefaultSpeed);
    wind = BbWind::Sanitize(wind);
    knobs.wind_deg = wind.direction_deg;
    knobs.wind_speed = wind.speed;
    return knobs;
}

/// The light kept at noise value n: 1 - depth * smoothstep(low, high, n) (cloud_light's last line).
inline float Light(float n, float depth, float low, float high) {
    const float t = std::clamp((n - low) / (high - low), 0.0f, 1.0f);
    return 1.0f - depth * (t * t * (3.0f - 2.0f * t));
}

/// L.xz / max(L.y, MinLightY): how far a point's plane coordinate moves per metre of height.
inline std::array<float, 2> Slope(const std::array<float, 3>& light) {
    const float y = std::max(light[1], MinLightY);
    return {light[0] / y, light[2] / y};
}

/// The plane coordinate of world point p (cloud_light's first line): p.xz - p.y * slope.
inline std::array<float, 2> Plane(const std::array<float, 3>& p, const std::array<float, 2>& slope) {
    return {p[0] - p[1] * slope[0], p[2] - p[1] * slope[1]};
}

/// "auto": atan2(L.z, L.x) + AutoTurn, wrapped; false when L has no horizontal part to speak of
/// (the light within about half a degree of straight up) or is not finite.
inline bool AutoDeg(const std::array<float, 3>& light, float* deg) {
    const double x = light[0], z = light[2];
    if (!std::isfinite(x) || !std::isfinite(z) || x * x + z * z < 1e-4) {
        return false;
    }
    *deg = Wrap360(float(std::atan2(z, x) * 57.29577951308232) + AutoTurn);
    return true;
}

/// The angle from `from` to `to` along the shorter arc, in (-180, 180].
inline float ArcDeg(float from, float to) {
    float d = Wrap360(to - from);
    return d > 180.0f ? d - 360.0f : d;
}

/// `current` eased toward `target` over dt seconds with time constant tau, along the shorter arc.
inline float EaseDeg(float current, float target, double dt, double tau) {
    const double k = dt > 0.0 && tau > 0.0 ? 1.0 - std::exp(-dt / tau) : 0.0;
    return Wrap360(current + float(k) * ArcDeg(current, target));
}

/// What drives the drift this frame: Drift's "wind" (m/s): speed toward deg across xz and the
/// morph in the third axis (scale / (MorphSeconds Squash), which Drift turns into
/// 1 / MorphSeconds cells a second for the largest octave).
inline std::array<float, 3> DriftVelocity(float deg, float speed, float scale) {
    const double rad = double(deg) * (3.14159265358979323846 / 180.0);
    return {float(speed * std::cos(rad)),
            float(double(scale) / (MorphSeconds * double(VolumetricFogNoise::Squash))),
            float(speed * std::sin(rad))};
}

// bbport (r105b_clouds-visible): Source and SourceName are above ParseDirection now.
/// The clouds' state: the direction, its source, the drift's offsets and the clamped real time.
class State {
public:
    /// One step of `seconds` (not finite: 0; clamped to 0-MaxStep). The direction (r105b): the
    /// wind's (wind_on: BB_WIND=1; wind_deg its direction this frame), else BB_CLOUDS_DIR's
    /// number, else with BB_CLOUDS_DIR=auto auto from `light` (light_valid), eased (the first
    /// light sets it at once; without a light auto keeps its last value), else the wind's base
    /// direction with BbWind::WanderDeg's wander at this state's time. Then the drift moves.
    /// bbport (r116b_wind-weather): `wind_speed` (m/s, the wind's mean speed this frame; below 0 or not
    /// finite: the knobs') and `cover_shift` (BbWind::CoverShift: the edges go that much lower) come
    /// from the wind's weather; with the wind off they are ignored.
    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,
                 const std::array<float, 3>& light, double seconds, float wind_speed = -1.0f,
                 float cover_shift = 0.0f) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        time += dt;
        float target = 0.0f;
        if (wind_on) {
            source = Source::Wind;
            direction = Wrap360(wind_deg);
        } else if (knobs.dir == Source::Env) {
            source = Source::Env;
            direction = knobs.dir_deg;
        } else if (knobs.dir == Source::Auto) {
            source = Source::Auto;
            if (light_valid && AutoDeg(light, &target)) {
                direction = auto_known ? EaseDeg(direction, target, dt, EaseSeconds) : target;
                auto_known = true;
            }
        } else {
            source = Source::WindKnob;
            direction = Wrap360(BbWind::WanderDeg(time, knobs.wind_deg));
        }
        // bbport (r116b_wind-weather): the clouds' speed is the ratio times the wind's mean speed of this frame
        const bool weather = wind_on && std::isfinite(wind_speed) && wind_speed >= 0.0f;
        speed_now = weather ? wind_speed * (knobs.show ? ShowSpeedRatio : SpeedRatio) : knobs.Velocity();
        cover_shift_now = weather && std::isfinite(cover_shift) ? cover_shift : 0.0f;
        drift.Advance(true, time, DriftVelocity(direction, speed_now, knobs.scale), knobs.scale);
    }

    float Direction() const {
        return direction;
    }
    Source From() const {
        return source;
    }
    double Time() const {
        return time;
    }
    /// bbport (r116b_wind-weather): m/s the clouds move at now (the knobs' before the first Advance)
    float Velocity(const Knobs& knobs) const {
        return speed_now >= 0.0f ? speed_now : knobs.Velocity();
    }
    /// The edges' shift of the cloud cover now (0: none)
    float CoverShift() const {
        return cover_shift_now;
    }
    const VolumetricFogNoise::Drift& Offsets() const {
        return drift;
    }

private:
    VolumetricFogNoise::Drift drift;
    double time = 0.0;
    float direction = StartDirection;
    Source source = Source::Auto;
    bool auto_known = false;
    float speed_now = -1.0f;       ///< r116b: Advance's speed (below 0: none yet)
    float cover_shift_now = 0.0f;  ///< r116b: Advance's cover shift
};

/// cloud_shadow.comp's push constants (its Params block, in order).
struct Push {
    std::array<float, 12> view_to_world{}; ///< 3x4 rows, translation in [3], [7], [11]
    std::array<float, 4> off0{};           ///< octave 0's offset; w: depth
    std::array<float, 4> off1{};           ///< octave 1's offset; w: 1 / scale
    std::array<float, 4> off2{};           ///< octave 2's offset; w: the low edge
    std::array<float, 2> slope{};
    float high = 0.0f;
    std::uint32_t offsets = 0; ///< the shadow constants' byte offset (bits 0-7), the uniforms' (8-15)
    float reach = 0.0f;        ///< the gate build: the march's reach (m)
    std::uint32_t unused = 0;
};
static_assert(sizeof(Push) == 120 && sizeof(Push) <= 128, "Vulkan guarantees 128 push bytes");

inline Push MakePush(const std::array<float, 12>& rows, const State& state, const Knobs& knobs,
                     const std::array<float, 3>& light, std::uint32_t offsets, float reach) {
    Push push;
    push.view_to_world = rows;
    const auto& drift = state.Offsets();
    const std::array<float, 3> c0 = drift.Cells(0), c1 = drift.Cells(1), c2 = drift.Cells(2);
    push.off0 = {c0[0], c0[1], c0[2], knobs.Depth()};
    push.off1 = {c1[0], c1[1], c1[2], 1.0f / knobs.scale};
    push.off2 = {c2[0], c2[1], c2[2], knobs.LowEdge() - state.CoverShift()}; // bbport (r116b)
    push.slope = Slope(light);
    push.high = knobs.HighEdge() - state.CoverShift(); // bbport (r116b)
    push.offsets = offsets;
    push.reach = reach;
    return push;
}

} // namespace CloudShadows
