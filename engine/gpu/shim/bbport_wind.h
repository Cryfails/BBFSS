// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r82_wind-stage1): one shared wind for the port's own effects. A direction (degrees in the
// world's xz plane, 0 = +x, 90 = +z, the way the wind blows TOWARD; +y is up), a speed in m/s and
// slow gusts, advanced by real time in Vulkan::Rasterizer::WindOnFrameEnd (only with BB_WIND=1, at
// each pass that copies a finished frame to a display buffer while the camera is tracked, which is
// unless BB_UPSCALER=none without BB_DEBUG_MOTION=1). It also carries the two offsets of the fog
// noise (Field, Density) in noise cells, for the fog passes. The sun fog reads the offsets
// (VolumetricLight::SetWind) and marches with MarchLitStep's GLSL copy. Pure: no
// Vulkan, no settings; tested by tests/test_wind.cpp (the GLSL copy by tests/test_wind_noise.cpp).
//
// Hash1, Hash3, Noise3, Field and Density use only 32-bit unsigned integer operations and float
// arithmetic. The GLSL copy (host_shaders/wind_noise.glsl) repeats them operation
// for operation, so both compute the same formula:
//  - lerps as a + (b - a) * t, not mix();
//  - Field DIVIDES the world point by 12, 6 and 4.5 (p.x / 12.0), as written here. The GPU's
//    floats still differ in the last bits: Vulkan lets a division be 2.5 ulp off and a driver may
//    multiply by a reciprocal, which can move floor() at a cell edge, where the value noise is
//    continuous. tests/test_wind_noise.cpp holds Field within 1e-4 of the C++ (pins 1e-6);
//  - the cell of a coordinate as int(floor(x)) & 255 (Cell keeps the same value mod 256), the
//    fraction as x - floor(x).
// The test pins six Noise3 values and four Field values (world points, non-zero offsets) for that
// copy. Noise1, Gust and WanderDeg run on the CPU only.

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>

namespace BbWind {

inline constexpr double MaxStep = 0.1;        ///< s: the longest step one Advance takes
inline constexpr float Wander = 15.0f;        ///< deg: the direction wanders this far either way
inline constexpr double WanderPeriod = 120.0; ///< s per noise cell of the wander
inline constexpr double SlowPeriod = 11.0;    ///< s per noise cell of the gust's slow part
inline constexpr double BurstPeriod = 4.3;    ///< s per noise cell of the gust's bursts
inline constexpr float Lambda1XZ = 12.0f;     ///< m per noise cell, octave 1, across (x, z)
inline constexpr float Lambda1Y = 6.0f;       ///< m per noise cell, octave 1, up (y)
inline constexpr float Lambda2 = 4.5f;        ///< m per noise cell, octave 2, every axis
inline constexpr float Octave2Speed = 1.6f;   ///< octave 2's offset moves this many times faster
inline constexpr double Period = 256.0;       ///< noise cells after which the hashes repeat
inline constexpr float GustMin = 0.3f, GustMax = 2.0f; ///< the gust factor's clamp
/// Subtracted inside Gust so that the factor's mean over an hour is near 1 (tests/test_wind.cpp
/// checks 0.95-1.05 for gusts 0.5 and 1), so the speed is the mean speed.
inline constexpr float GustCentre = 0.25f;
inline constexpr float DefaultDirection = 225.0f; ///< deg
inline constexpr float DefaultSpeed = 1.5f;       ///< m/s
inline constexpr float DefaultGusts = 0.5f;       ///< 0: a steady wind, 1: the strongest gusts
/// bbport (r116_wind-one-source): the heading is the cloud layer's and the ground wind's. MaxWander:
/// the most it may wander (BB_WIND_WANDER, deg either way; the default is Wander, 15). CloudRatio: the
/// clouds move at this many times the mean ground wind speed (the ground wind blows at 1 / CloudRatio of
/// the cloud speed, toward the same heading; the clouds feel no gusts).
inline constexpr float MaxWander = 45.0f;
inline constexpr float CloudRatio = 4.0f;
/// The fog density contrast (Density): 1 and at most 2, not the plan's 0.4 and
/// 0.9: at 0.4 the fog light of a 40 m ray varied by 3.6% (sd), too little to see; at 1 it is 9%
/// and m = 2 N, at 2 19% with holes where N < 0.25 (CPU probe, 20000 rays of 32 steps).
inline constexpr float DefaultContrast = 1.0f;
inline constexpr float MaxSpeed = 4.0f, MaxGusts = 1.0f, MaxContrast = 2.0f; ///< clamps from 0
/// bbport (r116b_wind-weather): the weather. One slow signal of the wind's world time sets the mean speed:
/// WeatherSpeed(clock) = WeatherMin + (WeatherMax - WeatherMin) u^4, u = (Noise1(clock / WeatherCell) + 1) / 2,
/// clock = Params::weather_at + Params::weather_rate x wind time. Over one noise period it is below CalmBelow
/// 56% of the time, below LightBelow 79%, below StrongFrom 96% (r116b's Python copy; tests/test_wind.cpp block
/// s). WeatherLine: the proof line's period (weather clock s). The gusts follow the level (0-1, the speed's
/// place in WeatherMin-WeatherMax): their strength is g x (GustGainMin + GustGainSpan x level) and their burst
/// threshold moves GustEdgeShift x (GustNeutral - level). The cloud cover moves CoverGain x (level -
/// CoverNeutral) (CoverShift: the cloud shadows' edges go that much lower).
inline constexpr double WeatherCell = 120.0; ///< s of weather clock per noise cell
inline constexpr float WeatherMin = 0.4f, WeatherMax = 3.9f; ///< m/s
inline constexpr float CalmBelow = 0.7f, LightBelow = 1.5f, StrongFrom = 3.0f; ///< m/s: the states
inline constexpr double WeatherRateMin = 0.05, WeatherRateMax = 100.0, WeatherAtLimit = 1.0e6;
inline constexpr double WeatherLine = 60.0; ///< s of weather clock between the proof lines
inline constexpr float GustGainMin = 0.3f, GustGainSpan = 1.0f, GustEdgeShift = 0.45f, GustNeutral = 0.35f;
inline constexpr float CoverGain = 0.06f, CoverNeutral = 0.3f;
static_assert(WeatherMin > 0.0f && WeatherMin < CalmBelow && CalmBelow < LightBelow && LightBelow < StrongFrom &&
                  StrongFrom < WeatherMax && WeatherMax <= MaxSpeed,
              "the weather's speeds sit inside 0-MaxSpeed");

/// PCG hash (one step of a PCG generator, then its output permutation) of i & 255.
inline std::uint32_t Hash1(std::int32_t i) {
    const std::uint32_t state = std::uint32_t(i & 255) * 747796405u + 2891336453u;
    const std::uint32_t word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

/// PCG3D of (x, y, z), each & 255 (so the lattice repeats every 256 cells); its first component.
inline std::uint32_t Hash3(std::int32_t x, std::int32_t y, std::int32_t z) {
    std::uint32_t a = std::uint32_t(x & 255) * 1664525u + 1013904223u;
    std::uint32_t b = std::uint32_t(y & 255) * 1664525u + 1013904223u;
    std::uint32_t c = std::uint32_t(z & 255) * 1664525u + 1013904223u;
    a += b * c;
    b += c * a;
    c += a * b;
    a ^= a >> 16u;
    b ^= b >> 16u;
    c ^= c >> 16u;
    return a + b * c;
}

/// A hash's top 24 bits as a float in [0, 1).
inline float Unit(std::uint32_t h) {
    return float(h >> 8u) * (1.0f / 16777216.0f);
}

/// Quintic fade u^3 (u (6u - 15) + 10).
inline float Fade(float u) {
    return u * u * u * (u * (u * 6.0f - 15.0f) + 10.0f);
}

inline float Lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

/// The lattice cell of a whole-number float as an int with the same value mod 256 (fmod is exact
/// here; it keeps the cast in range for any finite value).
inline std::int32_t Cell(float whole) {
    return std::int32_t(std::fmod(whole, 256.0f));
}

/// 1D value noise in [-1, 1]: corners 2 Hash1 - 1, quintic fade. 0 for a non-finite x.
inline float Noise1(double x) {
    if (!std::isfinite(x)) {
        return 0.0f;
    }
    const double whole = std::floor(x);
    const float u = Fade(float(x - whole));
    const std::int32_t i = std::int32_t(std::fmod(whole, Period));
    const float a = 2.0f * Unit(Hash1(i)) - 1.0f;
    const float b = 2.0f * Unit(Hash1(i + 1)) - 1.0f;
    return Lerp(a, b, u);
}

/// 3D value noise in [0, 1): the eight corners' Unit(Hash3), trilinear with the quintic fade.
/// 0.5 for a non-finite input.
inline float Noise3(float x, float y, float z) {
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
        return 0.5f;
    }
    const float fx = std::floor(x), fy = std::floor(y), fz = std::floor(z);
    const std::int32_t ix = Cell(fx), iy = Cell(fy), iz = Cell(fz);
    const float ux = Fade(x - fx), uy = Fade(y - fy), uz = Fade(z - fz);
    const auto corner = [&](std::int32_t dx, std::int32_t dy, std::int32_t dz) {
        return Unit(Hash3(ix + dx, iy + dy, iz + dz));
    };
    const float x00 = Lerp(corner(0, 0, 0), corner(1, 0, 0), ux);
    const float x10 = Lerp(corner(0, 1, 0), corner(1, 1, 0), ux);
    const float x01 = Lerp(corner(0, 0, 1), corner(1, 0, 1), ux);
    const float x11 = Lerp(corner(0, 1, 1), corner(1, 1, 1), ux);
    return Lerp(Lerp(x00, x10, uy), Lerp(x01, x11, uy), uz);
}

/// The fog noise N at a world point p (m), in [0, 1): 0.65 of octave 1 (12 m across, 6 m up)
/// plus 0.35 of octave 2 (4.5 m), each shifted by its offset (noise cells, Snapshot::off1/off2).
inline float Field(const std::array<float, 3>& p, const std::array<float, 3>& off1,
                   const std::array<float, 3>& off2) {
    const float n1 =
        Noise3(p[0] / Lambda1XZ - off1[0], p[1] / Lambda1Y - off1[1], p[2] / Lambda1XZ - off1[2]);
    const float n2 = Noise3(p[0] / Lambda2 - off2[0], p[1] / Lambda2 - off2[1], p[2] / Lambda2 - off2[2]);
    return 0.65f * n1 + 0.35f * n2;
}

/// The fog density factor m = max(0, 1 + contrast (2N - 1)); exactly 1 at contrast 0.
inline float Density(const std::array<float, 3>& p, const std::array<float, 3>& off1,
                     const std::array<float, 3>& off2, float contrast) {
    return std::max(0.0f, 1.0f + contrast * (2.0f * Field(p, off1, off2) - 1.0f));
}

/// The sun fog march with a drifting density (volumetric_light.comp with
/// WIND; its GLSL copy is wind_march_step in host_shaders/wind_noise.glsl). The fog's density is
/// density * m, m = Density at the step's world point. The plan's step is: s = density m,
/// energy += exp(-(tau + s jitter ds)) s ds vis, tau += s ds. Here tau + s jitter ds is written as
/// density (t + excess + (m - 1) jitter ds) with t = (i + jitter) ds and excess the sum of
/// (m - 1) ds before the step: the same number, but at m = 1 every added term is +0, so here
/// (IEEE floats) the step gives the floats of the march without wind, exp(-density t) density ds
/// vis. The GPU copy is within 1e-6 of them (a driver may fuse multiply-adds differently).
struct March {
    float energy = 0.0f; ///< in-scattered light so far, before the strength and the phase
    float excess = 0.0f; ///< m: the sum of (m - 1) ds over the steps before
};

inline void MarchStep(March& march, float density, float t, float ds, float jitter, float m,
                      float vis) {
    march.energy += std::exp(-density * (t + march.excess + (m - 1.0f) * jitter * ds)) *
                    (density * m) * ds * vis;
    march.excess += (m - 1.0f) * ds;
}

/// The step the sun fog takes (volumetric_light.comp with WIND): the noise is taken only where
/// the sample is lit (vis > 0), where it is MarchStep. A sample in shadow adds no light whatever m
/// is, and its step leaves the excess as it is, so its stretch of the ray dims the light behind it
/// at the mean density (m = 1) instead of the noisy one: no noise for it, which saves the 16 hashes
/// of Field where the sun atlas or the ray traced gate says shadow. The march's samples skipped in
/// front of the gate's first open cell (r76) count the same way. The GLSL copy is the `v > 0.0`
/// test around wind_ray_step in volumetric_light.comp; `m` is only read when vis > 0.
inline void MarchLitStep(March& march, float density, float t, float ds, float jitter, float m,
                         float vis) {
    if (vis > 0.0f) {
        MarchStep(march, density, t, ds, jitter, m, vis);
    }
}

/// A view space point v to world space with a 3x4 view to world matrix
/// stored as rows (translation in [3], [7], [11]; CameraMotion::PassMatrices().inv_view). The
/// GLSL copy wind_view_to_world takes dot(row, vec4(v, 1)) per row.
inline std::array<float, 3> ViewToWorld(const std::array<float, 12>& rows,
                                        const std::array<float, 3>& v) {
    std::array<float, 3> world{};
    for (std::size_t r = 0; r < 3; ++r) {
        world[r] = rows[r * 4] * v[0] + rows[r * 4 + 1] * v[1] + rows[r * 4 + 2] * v[2] +
                   rows[r * 4 + 3];
    }
    return world;
}

/// The grey of the BB_WIND_VIEW=1 test view, 0-1: m stretched over its range
/// 1 - contrast to 1 + contrast, so the pattern shows at full range whatever the contrast (it is
/// N where m is not clipped at 0). 0.5 at contrast 0, where m is 1 everywhere.
inline float ViewShade(float m, float contrast) {
    if (!(contrast > 0.0f)) {
        return 0.5f;
    }
    return std::clamp((m - (1.0f - contrast)) / (2.0f * contrast), 0.0f, 1.0f);
}

/// The direction (deg) at wind time t: base + 15 Noise1(t / 120 s), not wrapped.
inline float WanderDeg(double t, float base_deg) {
    return base_deg + Wander * Noise1(t / WanderPeriod);
}

/// bbport (r116_wind-one-source): the same with the wander set (BB_WIND_WANDER); at Wander it is the
/// function above.
inline float WanderDeg(double t, float base_deg, float wander) {
    return base_deg + wander * Noise1(t / WanderPeriod);
}

inline float Smoothstep(float edge0, float edge1, float x) {
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The gust factor at wind time t for gusts g (0-1): 1 + g (0.4 Noise1(t / 11 s + 3.1) +
/// 1.2 smoothstep(0.25, 0.75, Noise1(t / 4.3 s + 17.3)) - GustCentre), clamped to 0.3-2.
/// Exactly 1 at g = 0.
inline float Gust(double t, float g) {
    if (g == 0.0f) {
        return 1.0f;
    }
    const float slow = 0.4f * Noise1(t / SlowPeriod + 3.1);
    const float burst = 1.2f * Smoothstep(0.25f, 0.75f, Noise1(t / BurstPeriod + 17.3));
    return std::clamp(1.0f + g * (slow + burst - GustCentre), GustMin, GustMax);
}

/// The gust at world point (x, z) for a front travelling with the wind: Gust at the time the
/// front passed the origin, t - (x dir_x + z dir_z) / max(speed, 0.1); a non-finite speed counts
/// as 0.1. For later patches (plants); the fog uses Gust(t), since a rigidly shifted noise cannot
/// show fronts.
inline float GustAt(double t, float g, float x, float z, float dir_x, float dir_z, float speed) {
    const float floored = std::isfinite(speed) ? std::max(speed, 0.1f) : 0.1f;
    return Gust(t - double(x * dir_x + z * dir_z) / double(floored), g);
}

// bbport (r116b_wind-weather): the weather and what follows it. All pure CPU functions of the wind's world
// time; see the constants above.

/// The weather's mean speed (m/s) at weather clock `clock` (s): WeatherMin-WeatherMax, continuous.
inline float WeatherSpeed(double clock) {
    const float u = std::clamp(0.5f * (Noise1(clock / WeatherCell) + 1.0f), 0.0f, 1.0f);
    const float u2 = u * u;
    return WeatherMin + (WeatherMax - WeatherMin) * (u2 * u2);
}

/// A speed's place between WeatherMin (0) and WeatherMax (1); 0 for a value that is not finite.
inline float WeatherLevel(float speed) {
    if (!std::isfinite(speed)) {
        return 0.0f;
    }
    return std::clamp((speed - WeatherMin) / (WeatherMax - WeatherMin), 0.0f, 1.0f);
}

/// The gust strength Gust gets at weather level `level` for BB_WIND_GUSTS g: g x (0.3 + level), 0-MaxGusts.
inline float GustStrength(float g, float level) {
    return std::clamp(g * (GustGainMin + GustGainSpan * level), 0.0f, MaxGusts);
}

/// Gust with the weather's level: stronger gusts, and bursts above a lower threshold (so more often),
/// when the weather is up; weaker and rarer when it is calm. Exactly 1 at g = 0; the clamp is Gust's.
inline float GustWeather(double t, float g, float level) {
    if (g == 0.0f) {
        return 1.0f;
    }
    const float shift = GustEdgeShift * (GustNeutral - level);
    const float slow = 0.4f * Noise1(t / SlowPeriod + 3.1);
    const float burst = 1.2f * Smoothstep(0.25f + shift, 0.75f + shift, Noise1(t / BurstPeriod + 17.3));
    return std::clamp(1.0f + GustStrength(g, level) * (slow + burst - GustCentre), GustMin, GustMax);
}

/// The cloud cover's shift at weather level `level`: positive means denser (the cloud shadows' edges
/// go that much lower); 0 at CoverNeutral.
inline float CoverShift(float level) {
    return CoverGain * (level - CoverNeutral);
}

/// The weather's states: calm below CalmBelow, light below LightBelow, strong from StrongFrom, between
/// them building (the speed is rising) or easing (falling).
enum class Sky : std::size_t { Calm, Light, Building, Easing, Strong };

inline const char* SkyName(Sky s) {
    return s == Sky::Calm       ? "calm"
           : s == Sky::Light    ? "light"
           : s == Sky::Building ? "building"
           : s == Sky::Easing   ? "easing"
                                : "strong";
}

/// The state at weather clock `clock`.
inline Sky SkyAt(double clock) {
    const float v = WeatherSpeed(clock);
    if (v < CalmBelow) {
        return Sky::Calm;
    }
    if (v < LightBelow) {
        return Sky::Light;
    }
    if (v >= StrongFrom) {
        return Sky::Strong;
    }
    return WeatherSpeed(clock + 2.0) >= WeatherSpeed(clock - 2.0) ? Sky::Building : Sky::Easing;
}

/// The unit vector (x, z) the wind blows toward at deg: (cos, sin).
inline std::array<float, 2> DirectionXZ(float deg) {
    const double rad = double(deg) * (3.14159265358979323846 / 180.0);
    return {float(std::cos(rad)), float(std::sin(rad))};
}

/// What drives the wind. The environment fills it for now (WindOnFrameEnd).
struct Params {
    bool on = false;
    float direction_deg = DefaultDirection; ///< deg, 0 = +x, 90 = +z, the way it blows toward
    float speed = DefaultSpeed;             ///< m/s, 0-4 (the mean; gusts swing around it)
    float gusts = DefaultGusts;             ///< 0-1
    float wander = Wander;                  ///< deg: the heading wanders this far either way (0-MaxWander; 0: fixed)
    bool weather = false;                   ///< r116b: the speed is the weather's (WeatherSpeed), not `speed`
    double weather_rate = 1.0;              ///< r116b: weather clock seconds per wind second (0.05-100)
    double weather_at = 0.0;                ///< r116b: the weather clock at wind time 0 (s)
};

inline float FiniteOr(float v, float fallback) {
    return std::isfinite(v) ? v : fallback;
}

/// A non-finite value becomes its default; the direction is wrapped into [0, 360), the speed
/// clamped to 0-4 m/s and the gusts to 0-1.
inline Params Sanitize(Params p) {
    float deg = std::fmod(FiniteOr(p.direction_deg, DefaultDirection), 360.0f);
    if (deg < 0.0f) {
        deg += 360.0f;
    }
    p.direction_deg = deg >= 360.0f ? 0.0f : deg;
    p.speed = std::clamp(FiniteOr(p.speed, DefaultSpeed), 0.0f, MaxSpeed);
    p.gusts = std::clamp(FiniteOr(p.gusts, DefaultGusts), 0.0f, MaxGusts);
    p.wander = std::clamp(FiniteOr(p.wander, Wander), 0.0f, MaxWander);
    p.weather_rate = std::isfinite(p.weather_rate) ? std::clamp(p.weather_rate, WeatherRateMin, WeatherRateMax) : 1.0;
    p.weather_at = std::isfinite(p.weather_at) ? std::clamp(p.weather_at, -WeatherAtLimit, WeatherAtLimit) : 0.0;
    return p;
}

/// The fog density contrast for Density: non-finite gives DefaultContrast, then clamped to
/// 0-MaxContrast.
inline float SanitizeContrast(float contrast) {
    return std::clamp(FiniteOr(contrast, DefaultContrast), 0.0f, MaxContrast);
}

/// bbport (r88_wind-lamp-fog): the lamp fog's drift strength (BB_WIND_LAMP_FOG): 0 an even lamp
/// fog, DefaultLampFog the default, MaxLampFog the most. The lamp fog multiplies its density by
/// Density at the contrast LampFogContrast(strength) = strength * LampFogGain. The gain is there
/// because a lamp's glow is smaller than the noise's cells (Lambda2, Lambda1XZ), so the same
/// contrast shows less in it than in the sun fog. CPU estimate (Python copy of Field; a 6 m glow
/// 10 m away, wind 1.5 m/s): a pixel's lamp fog light varies over time by 13% (sd) at contrast 1,
/// 20% at 1.5, 26% at 2; a 3 m glow 4 m away by 8%, 11% and 15%. At MaxLampFog (contrast 3) m is 0
/// where N < 1/3 (about 14% of space), which raises the mean of m a few percent (wind-test g).
inline constexpr float DefaultLampFog = 1.0f, MaxLampFog = 2.0f, LampFogGain = 1.5f;

/// The lamp fog's strength: non-finite gives DefaultLampFog, then clamped to 0-MaxLampFog.
inline float SanitizeLampFog(float strength) {
    return std::clamp(FiniteOr(strength, DefaultLampFog), 0.0f, MaxLampFog);
}

/// The contrast the lamp fog gives Density (wind_noise.glsl's wind_density) for a strength.
inline float LampFogContrast(float strength) {
    return strength * LampFogGain;
}

/// v wrapped into [0, Period).
inline double WrapCells(double v) {
    double r = std::fmod(v, Period);
    if (r < 0.0) {
        r += Period;
    }
    return r >= Period ? 0.0 : r;
}

/// The wind after the last Advance. Before the first Advance with Params::on: on is false and
/// the rest is zero (gust 1).
struct Snapshot {
    bool on = false;
    double time = 0.0;          ///< s: the sum of the clamped steps
    float direction_deg = 0.0f; ///< after the wander, wrapped into [0, 360)
    float dir_x = 0.0f, dir_z = 0.0f;
    float speed = 0.0f;         ///< m/s: Params::speed after Sanitize
    float gust = 1.0f;
    std::array<float, 3> wind{}; ///< m/s: speed * gust * (dir_x, 0, dir_z)
    std::array<float, 3> off1{}; ///< octave 1's offset, noise cells, each in [0, 256)
    std::array<float, 3> off2{}; ///< octave 2's offset, noise cells, each in [0, 256)
    float gusts = 0.0f;       ///< Params::gusts after Sanitize (r116: GustAt needs it)
    float wander = 0.0f;      ///< Params::wander after Sanitize: the heading wanders this far either way
    float cloud_speed = 0.0f; ///< m/s: CloudRatio x speed, how fast the clouds move toward the heading
    bool weather_on = false;      ///< r116b: the speed is the weather's
    float weather = 0.0f;         ///< r116b: the weather level, 0 (WeatherMin) to 1 (WeatherMax); 0 without the weather
    float gust_strength = 0.0f;   ///< r116b: the gust strength in use (Params::gusts, or GustStrength with the weather)
    double weather_rate = 1.0;    ///< r116b: Params::weather_rate after Sanitize
    double weather_at = 0.0;      ///< r116b: Params::weather_at after Sanitize
};

class State {
public:
    /// One step: with p.on, wind time moves on by seconds (a non-finite value counts as 0, the
    /// rest is clamped to 0-0.1 s), the direction and gust are taken at the new time, and the
    /// offsets move by wind * step: octave 1 per (12, 6, 12) m, octave 2 1.6 times as fast per
    /// 4.5 m, summed in double and wrapped into [0, 256) after every step. Without p.on nothing
    /// changes.
    void Advance(Params p, double seconds, float open = 1.0f) {
        if (!p.on) {
            return;
        }
        p = Sanitize(p);
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        snapshot.on = true;
        snapshot.time += dt;
        const float deg = WanderDeg(snapshot.time, p.direction_deg, p.wander);
        const auto dir = DirectionXZ(deg);
        // bbport (r116b_wind-weather): with the weather the mean speed is the weather's at this clock and
        // the gusts follow its level; without it p.speed and Gust, the same floats as before
        const float speed = p.weather ? WeatherSpeed(p.weather_at + p.weather_rate * snapshot.time) : p.speed;
        const float level = p.weather ? WeatherLevel(speed) : 0.0f;
        const float gust = p.weather ? GustWeather(snapshot.time, p.gusts, level) : Gust(snapshot.time, p.gusts);
        const float u = speed * gust;
        float wrapped = std::fmod(deg, 360.0f);
        if (wrapped < 0.0f) {
            wrapped += 360.0f;
        }
        snapshot.direction_deg = wrapped >= 360.0f ? 0.0f : wrapped;
        snapshot.dir_x = dir[0];
        snapshot.dir_z = dir[1];
        snapshot.speed = speed; // bbport (r116b): the weather's, or p.speed
        snapshot.gust = gust;
        snapshot.gusts = p.gusts;
        snapshot.wander = p.wander;
        snapshot.cloud_speed = CloudRatio * speed;
        snapshot.weather_on = p.weather;
        snapshot.weather = level;
        snapshot.gust_strength = p.weather ? GustStrength(p.gusts, level) : p.gusts;
        snapshot.weather_rate = p.weather_rate;
        snapshot.weather_at = p.weather_at;
        // bbport (r117_wind-shelter): `open` (0-1) is the share of the wind that stays where the
        // camera is (BbWindShelter::Open); 1 (the default) gives the same floats as before. It
        // takes the wind vector (the particles, the heat haze, the caustics) and the offsets
        // below (the fog's drift), not the direction, the speed or the gust (the plants).
        const float calm = std::isfinite(open) ? std::clamp(open, 0.0f, 1.0f) : 1.0f;
        snapshot.wind = {u * dir[0] * calm, 0.0f, u * dir[1] * calm};
        constexpr std::array<double, 3> cell1{Lambda1XZ, Lambda1Y, Lambda1XZ};
        for (std::size_t i = 0; i < 3; ++i) {
            const double moved = double(snapshot.wind[i]) * dt;
            off1[i] = WrapCells(off1[i] + moved / cell1[i]);
            off2[i] = WrapCells(off2[i] + moved * double(Octave2Speed) / double(Lambda2));
            snapshot.off1[i] = ToFloatCells(off1[i]);
            snapshot.off2[i] = ToFloatCells(off2[i]);
        }
    }

    Snapshot Get() const {
        return snapshot;
    }

    void Reset() {
        *this = State{};
    }

private:
    /// A wrapped double as a float in [0, 256) (a value just under 256 would round up to 256).
    static float ToFloatCells(double v) {
        const float f = float(v);
        return f >= float(Period) ? 0.0f : f;
    }

    std::array<double, 3> off1{}, off2{};
    Snapshot snapshot{};
};

// bbport (r116_wind-one-source): ONE wind for everything that moves with air. The heading
// (Snapshot::direction_deg) is the cloud layer's: the cloud shadows travel toward it, the ground wind
// blows toward it and the gusts come from behind it (GustAt: a gust front reaches the plants upwind first).
// It wanders by slow noise (a new cell every WanderPeriod = 120 s of wind time) at most
// Snapshot::wander deg either way; wind time is the sum of the frame steps (0 at the first frame with
// BB_WIND=1), one value per frame for every follower, so it is the same for all of them and continuous.
// The speeds are tied: the clouds CloudRatio x the mean speed, the ground wind 1 / CloudRatio of that,
// the gust factor at a point GustAt (the clouds feel none). Followers read it through Snapshot or WindAt,
// never through a wind of their own.

/// bbport (r116b_wind-weather): the weather clock at wind time t (s): the clock the weather runs on with
/// the weather, t itself without it.
inline double ClockOf(const Snapshot& s, double t) {
    return s.weather_on ? s.weather_at + s.weather_rate * t : t;
}

/// The ONE gust factor at wind time t (s) for BB_WIND_GUSTS `gusts`: Gust(t, gusts) without the weather,
/// with it GustWeather at the weather's level of THAT time. The plant sway's and the hanging things' gust
/// tables and WindAt (with s.gusts) read it.
inline float GustOf(const Snapshot& s, double t, float gusts) {
    if (!s.weather_on) {
        return Gust(t, gusts);
    }
    return GustWeather(t, gusts, WeatherLevel(WeatherSpeed(s.weather_at + s.weather_rate * t)));
}

/// GustAt for a snapshot: the gust at world point (x, z) for a front travelling with the wind, taken at
/// the time the front passed the origin (as GustAt, so the same floats without the weather).
inline float GustAtSnap(const Snapshot& s, float x, float z) {
    const float floored = std::isfinite(s.speed) ? std::max(s.speed, 0.1f) : 0.1f;
    return GustOf(s, s.time - double(x * s.dir_x + z * s.dir_z) / double(floored), s.gusts);
}

/// The wind (m/s) at world point (x, z): speed x GustAt x the heading's vector (y 0); zero without the
/// wind. At (0, 0) it is Snapshot::wind (the same floats).
inline std::array<float, 3> WindAt(const Snapshot& s, float x, float z) {
    if (!s.on) {
        return {0.0f, 0.0f, 0.0f};
    }
    const float u = s.speed * GustAtSnap(s, x, z); // bbport (r116b): the weather's gust
    return {u * s.dir_x, 0.0f, u * s.dir_z};
}

/// The things that read the shared wind and are named in the 600-step line.
enum class Follower : std::size_t { Fog, FogNoise, Clouds, Plants, Motes, Haze, Sparks, Count };
inline constexpr std::size_t FollowerCount = std::size_t(Follower::Count);
inline constexpr std::array<const char*, FollowerCount> FollowerNames{"fog",   "noise", "clouds", "plants",
                                                                      "motes", "haze",  "sparks"};
static_assert(FollowerNames[FollowerCount - 1] != nullptr, "a name for every follower");

/// The heading (deg, 0 = +x, 90 = +z, in [0, 360)) of the vector (x, z); 0 for the zero vector or a
/// value that is not finite.
inline float HeadingDeg(float x, float z) {
    if (!std::isfinite(x) || !std::isfinite(z)) {
        return 0.0f;
    }
    double deg = std::atan2(double(z), double(x)) * (180.0 / 3.14159265358979323846);
    if (deg < 0.0) {
        deg += 360.0;
    }
    const float f = float(deg);
    return f >= 360.0f ? 0.0f : f;
}

/// What a follower last read: its heading, the gust factor (its speed over share x the mean speed), how
/// many reads since the last line. Relaxed atomics: followers run on several threads.
struct FollowerNote {
    std::atomic<float> heading{0.0f};
    std::atomic<float> gust{0.0f};
    std::atomic<std::uint32_t> uses{0};
};

inline std::array<FollowerNote, FollowerCount>& Notes() {
    static std::array<FollowerNote, FollowerCount> notes;
    return notes;
}

/// A follower read the wind with heading `heading_deg` and speed `speed` (m/s), of which `share` is
/// its own constant (the clouds: CloudRatio; the others 1). Nothing without the wind, without a speed
/// or with values that are not finite.
inline void UseHeading(Follower f, const Snapshot& s, float heading_deg, float speed, float share) {
    if (!s.on || !std::isfinite(heading_deg) || !std::isfinite(speed) || !(speed > 0.0f) ||
        !(share > 0.0f) || !(s.speed > 0.0f)) {
        return;
    }
    FollowerNote& n = Notes()[std::size_t(f)];
    n.heading.store(heading_deg, std::memory_order_relaxed);
    n.gust.store(speed / (share * s.speed), std::memory_order_relaxed);
    n.uses.fetch_add(1, std::memory_order_relaxed);
}

/// A follower was handed the wind vector v (m/s).
inline void Use(Follower f, const Snapshot& s, const std::array<float, 3>& v) {
    UseHeading(f, s, HeadingDeg(v[0], v[2]), std::sqrt(v[0] * v[0] + v[2] * v[2]), 1.0f);
}

/// The wind at the camera (`inv_view`: 3x4 rows, translation in [3], [7], [11]), counted for `f`.
inline std::array<float, 3> Felt(Follower f, const Snapshot& s, const std::array<float, 12>& inv_view) {
    const std::array<float, 3> v = WindAt(s, inv_view[3], inv_view[11]);
    Use(f, s, v);
    return v;
}

/// A world velocity v (m/s) as the pixels a second it moves a point `depth` m in front of the camera
/// in a width x height viewport: the rotation of the view rows (3x4, world to view), then
/// ndc = view.xy x proj.xy / depth (proj as CameraMotion::Matrices::proj, the particles' convention),
/// ndc 1 = half the viewport. {0, 0} for a depth that is not above 0.
inline std::array<float, 2> ScreenVelocity(const std::array<float, 12>& view,
                                           const std::array<float, 4>& proj,
                                           const std::array<float, 3>& v, float depth, float width,
                                           float height) {
    if (!(depth > 0.0f)) {
        return {0.0f, 0.0f};
    }
    const float vx = view[0] * v[0] + view[1] * v[1] + view[2] * v[2];
    const float vy = view[4] * v[0] + view[5] * v[1] + view[6] * v[2];
    return {vx * proj[0] / depth * 0.5f * width, vy * proj[1] / depth * 0.5f * height};
}

/// The 600-step line (at most about 250 characters: the slot runs keep 300): the shared heading, speed
/// and gusts, then each follower's heading and gust factor as read since the last line ("-": it read
/// nothing). Resets the counts. Returns snprintf's result for `out`.
inline int FollowersText(const Snapshot& s, char* out, std::size_t size) {
    char list[256];
    std::size_t at = 0;
    list[0] = '\0';
    for (std::size_t i = 0; i < FollowerCount; ++i) {
        FollowerNote& n = Notes()[i];
        const bool read = n.uses.exchange(0, std::memory_order_relaxed) != 0;
        const int w =
            read ? std::snprintf(list + at, sizeof(list) - at, " %s %.1f/%.2f", FollowerNames[i],
                                 double(n.heading.load(std::memory_order_relaxed)),
                                 double(n.gust.load(std::memory_order_relaxed)))
                 : std::snprintf(list + at, sizeof(list) - at, " %s -", FollowerNames[i]);
        if (w < 0 || std::size_t(w) >= sizeof(list) - at) {
            break;
        }
        at += std::size_t(w);
    }
    return std::snprintf(out, size,
                         "Wind (r116): heading %.1f deg (wanders +-%.0f), speed %.2f m/s, gusts %.2f, "
                         "gust now x%.2f, clouds x%.0f; followers heading/gust:%s",
                         double(s.direction_deg), double(s.wander), double(s.speed), double(s.gusts),
                         double(s.gust), double(CloudRatio), list);
}

/// bbport (r116b_wind-weather): the speeds seen since the last proof line: the sum and count (the mean)
/// and the lowest and highest.
struct WeatherWindow {
    double sum = 0.0;
    std::uint32_t count = 0;
    float lowest = 0.0f, highest = 0.0f;

    void Add(float v) {
        if (!std::isfinite(v)) {
            return;
        }
        lowest = count == 0 ? v : std::min(lowest, v);
        highest = count == 0 ? v : std::max(highest, v);
        sum += double(v);
        ++count;
    }
    float Mean() const {
        return count != 0 ? float(sum / double(count)) : 0.0f;
    }
};

/// The weather's proof line (under 300 characters): the state, the clock, the speed now with its mean and
/// range since the last line, the gust strength, the clouds' speed (`clouds`, m/s: what the cloud layer
/// moves at) and the cover shift. Empties `w`. Returns snprintf's result for `out`.
inline int WeatherText(const Snapshot& s, WeatherWindow& w, float clouds, char* out, std::size_t size) {
    const float mean = w.count != 0 ? w.Mean() : s.speed;
    const float lo = w.count != 0 ? w.lowest : s.speed;
    const float hi = w.count != 0 ? w.highest : s.speed;
    w = WeatherWindow{};
    if (!s.weather_on) {
        return std::snprintf(out, size,
                             "Wind (r116b): weather off (constant speed), speed now %.2f m/s (mean %.2f, range "
                             "%.2f-%.2f), gust strength %.2f (x%.2f now), clouds %.2f m/s",
                             double(s.speed), double(mean), double(lo), double(hi), double(s.gust_strength),
                             double(s.gust), double(clouds));
    }
    const double clock = ClockOf(s, s.time);
    return std::snprintf(out, size,
                         "Wind (r116b): weather %s (clock %.0f s, x%.2f), speed now %.2f m/s (mean %.2f, range "
                         "%.2f-%.2f), gust strength %.2f (x%.2f now), clouds %.2f m/s, cover %+.3f",
                         SkyName(SkyAt(clock)), clock, s.weather_rate, double(s.speed), double(mean), double(lo),
                         double(hi), double(s.gust_strength), double(s.gust), double(clouds),
                         double(CoverShift(s.weather)));
}

} // namespace BbWind
