# r82_wind-stage1: FEATURE patch. Wind, first stage of the judged wind plan: one shared wind state
# (the plan's W1) and its first visible user, the sun fog drifting with it (W2 noise and the test
# view, W3 drift). Off by default behind one knob, BB_WIND=1 (environment, read once). This is
# r56 (wind state) and r59 (sun fog drift), drafted and reviewed earlier on an older tree and never
# applied, merged into one patch and moved onto the tree as it is now (r51, r51b, r76 in the sun
# fog), with the ray traced gate's march builds getting WIND builds too and the noise taken only
# where a sample is lit.
#
# Why: the owner's list "Wind and all it's changes", later "Fog and wind go by cloud direction"
# and "Foliage sway and clouds"; the plan orders the shared wind first and the sun fog as its
# first user. Clouds: the engine reads no cloud direction (nothing in the port knows the sky's
# clouds), so the wind's direction is the BB_WIND_DIR knob for now; following the clouds needs the
# game's sky or WindWorld read first (the plan's probe W0-lite), which is not in this patch.
#
# What:
#  1. engine/gpu/shim/bbport_wind.h (new, pure, header only): direction (wanders 15 deg over 120
#     s), mean speed, gusts (0.3-2, mean 1), two noise offsets advanced by real time (steps clamped
#     to 0-0.1 s, so independent of the frame rate); the fog noise Noise3/Field/Density (value
#     noise, 32-bit integer hash, 12 m x 6 m and 4.5 m octaves), the march step MarchStep and the
#     lit-only step MarchLitStep, ViewToWorld, ViewShade. tests/test_wind.cpp (new, checks a-q):
#     built and run by engine/build.sh --test and a CMake target wind-test.
#  2. host_shaders/wind_noise.glsl (new): the GLSL copy, operation for operation; tests/
#     test_wind_noise.cpp + host_shaders/wind_noise_test.comp (new, Vulkan, wind-noise-test): the
#     GPU copy against the C++ (pins 1e-6, Field 1e-4, march at contrast 0 within 1e-6).
#  3. volumetric_light.comp, only inside #ifdef WIND / WIND_VIEW: five vec4 after the plain push
#     words (the camera's view to world rows at the Integrate call, the offsets, the contrast, the
#     view flag); the march's density is density * m along the ray with its extinction following
#     (exactly the plain step where m = 1), in the plain and in the GATE march; m is taken only
#     where the sample is lit (MarchLitStep); BB_WIND_VIEW=1 writes m's shade instead of fog and
#     the WIND_VIEW composite shows it grey. The plain builds compile to the same SPIR-V words.
#  4. vk_volumetric_light.h/.cpp: SetWind (the offsets and the camera at the Integrate call),
#     WindParams (Params, then 80 bytes), the WIND builds of integrate, repair, gated integrate,
#     gated repair and the view composite, made at the first march that drifts (never with the
#     knob off; a failure leaves the plain march and says so once), WindFogCheck (the BB_WIND_SHOW=1
#     "Wind fog:" line). Off: the plain builds and the same 32 pushed bytes as before.
#  5. vk_rasterizer.h / vk_rasterizer_effects.cpp: the Rasterizer owns the wind, advances it at
#     the top of EffectsOnFrameEnd (BB_WIND=1 only), says the knob's state once (on or off), and
#     hands the snapshot and CameraMotion::PassMatrices() to the sun fog right before Integrate.
#  6. CMakeLists.txt (5 shader builds, the test shader, wind-test, wind-noise-test), build.sh
#     (wind-test), test_effect_pipelines.cpp (the 5 WIND builds), README.md (a Wind section).
#
# Knobs (environment, read once; no ini key, menu row or launcher row yet: the plan adds keys in
# W5 once the owner accepts the look, rule 4 allows env for work in progress):
#   BB_WIND=1 on (the one switch; default off). With it: BB_WIND_DIR (deg the wind blows toward,
#   0 = world +x, 90 = +z; 225), BB_WIND_SPEED (0-4 m/s; 1.5), BB_WIND_GUSTS (0-1; 0.5),
#   BB_WIND_FOG (contrast 0-2; 1), BB_WIND_VIEW=1 (test view), BB_WIND_SHOW=1 (2 s lines).
#   Missing, unreadable or non-finite numbers take the default, then the clamps.
# Log: once at the first frame end "Wind (r82): off (BB_WIND is not 1) ..." or "Wind (r82,
#   BB_WIND=1): toward ..."; once at the first drifting march "Wind fog (r82): ..." and whether
#   the WIND builds were made; with BB_WIND_SHOW=1 the "Wind:" and "Wind fog:" lines every 2 s.
# Profiler: no new pass. The WIND march takes the place of the plain march inside the pinned row
#   "Lighting: volumetric sunlight" (EffectPass::Mark 7), so its cost is that row's difference.
#
# Cost (NOT MEASURED): off: nothing on the GPU (plain builds, the WIND builds never made), on the
#   CPU one static guard and one bool test per frame end and per shadow resolve, and the integrate
#   commands capture 80 bytes more (WindParams is captured whole; 32 bytes are pushed). On: an
#   estimate of 0.15-0.3 ms at 1080p internal (16.6 M march samples, two octaves of 8 hashed
#   corners each), less where samples are in shadow or in front of the gate's first open cell
#   (no noise there: the saving of this patch over r59), about 4x at 2160p internal. The plan's
#   rule: over 0.15 ms measured, switch to a 64^3 noise texture.
#
# Other teams edit volumetric_light.comp and vk_volumetric_light.cpp at the same time. Every edit
# here keeps its anchor text, except these, which replace lines: volumetric_light.comp the two
# march lines `energy += exp(-density * t) * density * ds * v;` and `energy += exp(-density * t) *
# density * ds * visibility(ray * t, texel);` (kept in the #else); vk_volumetric_light.cpp the
# integrate pass choice (`const auto& pass = repairing ? (gated ? repair_gated : repair)` and its
# two lines), the integrate lambda's capture line `[params, di, si, ...`, its pushConstants line,
# and the composite lambda's `pipeline = gate_viewed ? ...` / `layout = gate_viewed ? ...` lines.
# The push block's tail is anchored on the block's closing `};` before `#ifdef REPAIR / #define
# GROUP`, so words another patch appends after `cascades` stay before it (WindParams asserts its
# tail starts at sizeof(Params), which must be a multiple of 16).
# Review (2026-11-15 18:21 CST): the integrate lambda pushes push_size bytes (112 while drifting) to the
# layout of `pass`; the text checks require its capture `pipeline = *pass.pipeline, layout =
# *pass.layout]` unchanged, so this patch refuses a tree where another patch binds a different
# pipeline there (r81_sun-fog-no-rt's AREA builds have a 32-byte layout: with both on, a drifting
# march would push 112 bytes to it). Reconcile by hand: no drift on an AREA march (drift = ... &&
# !area), or AREA builds with WIND. r81 does not apply after this patch either (its anchors in
# volumetric_light.comp's march are replaced here).
#
# Use: cd <tree> && python -I -X utf8 r82_wind-stage1.py check | apply | revert (root from
# R82_ROOT, else the current directory). Files keep their line ends (CRLF in the tree); the new
# files are written with CRLF and removed by revert (only when they are unchanged). Originals are
# kept in r82_backup/ next to this script. Needs r51, r51b and r76 applied (the anchors hold
# their text).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r82_backup")
ROOT = os.environ.get("R82_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    "engine/gpu/shim/bbport_wind.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
#include <cmath>
#include <cstdint>

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
/// The fog density contrast (Density): 1 and at most 2, not the plan's 0.4 and
/// 0.9: at 0.4 the fog light of a 40 m ray varied by 3.6% (sd), too little to see; at 1 it is 9%
/// and m = 2 N, at 2 19% with holes where N < 0.25 (CPU probe, 20000 rays of 32 steps).
inline constexpr float DefaultContrast = 1.0f;
inline constexpr float MaxSpeed = 4.0f, MaxGusts = 1.0f, MaxContrast = 2.0f; ///< clamps from 0

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
    return p;
}

/// The fog density contrast for Density: non-finite gives DefaultContrast, then clamped to
/// 0-MaxContrast.
inline float SanitizeContrast(float contrast) {
    return std::clamp(FiniteOr(contrast, DefaultContrast), 0.0f, MaxContrast);
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
};

class State {
public:
    /// One step: with p.on, wind time moves on by seconds (a non-finite value counts as 0, the
    /// rest is clamped to 0-0.1 s), the direction and gust are taken at the new time, and the
    /// offsets move by wind * step: octave 1 per (12, 6, 12) m, octave 2 1.6 times as fast per
    /// 4.5 m, summed in double and wrapped into [0, 256) after every step. Without p.on nothing
    /// changes.
    void Advance(Params p, double seconds) {
        if (!p.on) {
            return;
        }
        p = Sanitize(p);
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        snapshot.on = true;
        snapshot.time += dt;
        const float deg = WanderDeg(snapshot.time, p.direction_deg);
        const auto dir = DirectionXZ(deg);
        const float gust = Gust(snapshot.time, p.gusts);
        const float u = p.speed * gust;
        float wrapped = std::fmod(deg, 360.0f);
        if (wrapped < 0.0f) {
            wrapped += 360.0f;
        }
        snapshot.direction_deg = wrapped >= 360.0f ? 0.0f : wrapped;
        snapshot.dir_x = dir[0];
        snapshot.dir_z = dir[1];
        snapshot.speed = p.speed;
        snapshot.gust = gust;
        snapshot.wind = {u * dir[0], 0.0f, u * dir[1]};
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

} // namespace BbWind
''',
    H + "wind_noise.glsl": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the GLSL copy of the fog noise, the march step and the view helpers of
// gpu/shim/bbport_wind.h (BbWind::Hash3, Unit, Fade, Lerp, Noise3, Field, Density, MarchStep,
// ViewToWorld, ViewShade). It repeats the C++ operation for operation, so that both compute the
// same formula: as the header asks, a lerp is a + (b - a) t (not mix()), the field DIVIDES the
// world point by 12, 6 and 4.5 m, and a cell is int(floor(x)) & 255 (the same value mod 256 as
// BbWind::Cell for |x| < 2^31). The floats are not bit for bit the CPU's: Vulkan lets a GPU
// division be 2.5 ulp off and a driver may turn x / 12 into a multiply, which can move floor() at
// a cell edge; the value noise is continuous there, so N changes only by that rounding.
// tests/test_wind_noise.cpp runs this file on the GPU: the pinned values within 1e-6, Field
// within 1e-4 of the C++ elsewhere. Only 32-bit unsigned integer and float operations. Included
// by volumetric_light.comp (WIND) and wind_noise_test.comp.

// PCG3D of the cell, each component & 255 (the lattice repeats every 256 cells); its first
// component.
uint wind_hash3(ivec3 cell) {
    uvec3 v = uvec3(cell & 255) * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    return v.x + v.y * v.z;
}

// A hash's top 24 bits as a float in [0, 1).
float wind_unit(uint h) {
    return float(h >> 8u) * (1.0 / 16777216.0);
}

// Quintic fade u^3 (u (6u - 15) + 10).
float wind_fade(float u) {
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0);
}

float wind_lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

// 3D value noise in [0, 1): the eight corners' wind_unit(wind_hash3), trilinear with the quintic
// fade. 0.5 for a non-finite input.
float wind_noise3(vec3 x) {
    if (any(isnan(x)) || any(isinf(x))) return 0.5;
    vec3 f = floor(x);
    ivec3 i = ivec3(f);
    float ux = wind_fade(x.x - f.x), uy = wind_fade(x.y - f.y), uz = wind_fade(x.z - f.z);
    float x00 = wind_lerp(wind_unit(wind_hash3(i)), wind_unit(wind_hash3(i + ivec3(1, 0, 0))), ux);
    float x10 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 1, 0))),
                          wind_unit(wind_hash3(i + ivec3(1, 1, 0))), ux);
    float x01 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 0, 1))),
                          wind_unit(wind_hash3(i + ivec3(1, 0, 1))), ux);
    float x11 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 1, 1))),
                          wind_unit(wind_hash3(i + ivec3(1, 1, 1))), ux);
    return wind_lerp(wind_lerp(x00, x10, uy), wind_lerp(x01, x11, uy), uz);
}

// The fog noise N at world point p (m), in [0, 1): 0.65 of octave 1 (12 m across, 6 m up) plus
// 0.35 of octave 2 (4.5 m), each shifted by its offset (cells, BbWind::Snapshot off1 and off2).
float wind_field(vec3 p, vec3 off1, vec3 off2) {
    float n1 = wind_noise3(vec3(p.x / 12.0 - off1.x, p.y / 6.0 - off1.y, p.z / 12.0 - off1.z));
    float n2 = wind_noise3(vec3(p.x / 4.5 - off2.x, p.y / 4.5 - off2.y, p.z / 4.5 - off2.z));
    return 0.65 * n1 + 0.35 * n2;
}

// The fog density factor m = max(0, 1 + contrast (2N - 1)); exactly 1 at contrast 0.
float wind_density(vec3 p, vec3 off1, vec3 off2, float contrast) {
    return max(0.0, 1.0 + contrast * (2.0 * wind_field(p, off1, off2) - 1.0));
}

// A view space point to world space with the 3x4 view to world matrix as rows (translation in
// .w; CameraMotion::PassMatrices().inv_view).
vec3 wind_view_to_world(vec4 r0, vec4 r1, vec4 r2, vec3 v) {
    vec4 h = vec4(v, 1.0);
    return vec3(dot(r0, h), dot(r1, h), dot(r2, h));
}

// m at view space point v: wind_density at its world point (offsets in cells, the contrast).
float wind_factor_rows(vec4 r0, vec4 r1, vec4 r2, vec3 v, vec3 off1, vec3 off2, float contrast) {
    return wind_density(wind_view_to_world(r0, r1, r2, v), off1, off2, contrast);
}

// One step of the sun fog march through a fog of density `density` * m: in-scatter at t (m) seen
// through the optical depth density * (t + excess + (m - 1) jitter ds), then excess += (m - 1) ds.
// That is the plan's tau + s jitter ds with tau = the sum of s ds before this step (s = density m),
// written so that at m = 1 every added term is +0: in IEEE arithmetic the step then gives the
// floats of the march without wind, exp(-density * t) * density * ds * vis (BbWind::MarchStep,
// wind-test m). A GPU driver may fuse the multiply-adds of the two expressions differently, so on
// the GPU it is within 1e-6 (relative) of them, not bit for bit (wind-noise-test).
void wind_march_step(inout float energy, inout float excess, float density, float t, float ds,
                     float jitter, float m, float vis) {
    energy += exp(-density * (t + excess + (m - 1.0) * jitter * ds)) * (density * m) * ds * vis;
    excess += (m - 1.0) * ds;
}

// The march step at view space distance t along the unit view ray `ray`: m taken at ray * t,
// the point the step's light is taken at (volumetric_light.comp passes visibility(ray * t)).
void wind_ray_step(inout float energy, inout float excess, float density, vec3 ray, float t,
                   float ds, float jitter, float vis, vec4 r0, vec4 r1, vec4 r2, vec3 off1,
                   vec3 off2, float contrast) {
    wind_march_step(energy, excess, density, t, ds, jitter,
                    wind_factor_rows(r0, r1, r2, ray * t, off1, off2, contrast), vis);
}

// The grey of the BB_WIND_VIEW=1 test view, 0-1: m stretched over 1 - contrast to 1 + contrast
// (N where m is not clipped at 0); 0.5 at contrast 0.
float wind_view_shade(float m, float contrast) {
    if (!(contrast > 0.0)) return 0.5;
    return clamp((m - (1.0 - contrast)) / (2.0 * contrast), 0.0, 1.0);
}
''',
    H + "wind_noise_test.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): runs wind_noise.glsl on the GPU for tests/test_wind_noise.cpp, which
// compares it with gpu/shim/bbport_wind.h. One invocation per case; not used by the engine.
#version 450
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 64) in;

#include "wind_noise.glsl"

// Per case eight vec4: (p, contrast), (off1, density), (off2, ds), (jitter, vis seed, zero, -),
// the view to world matrix's three rows, (the unit view ray, -). `zero` is 0 read from the
// buffer, so a contrast of 0 is only known at run time, as BB_WIND_FOG=0 is in the game.
layout(std430, binding = 0) readonly buffer Cases { vec4 v[]; } cases;
// Per case two vec4: (Noise3(p), Field, Density, the factor at view point p through the rows) and
// (p through the rows, the test view's shade of Density).
layout(std430, binding = 1) writeonly buffer Values { vec4 v[]; } values;
// Per case the floats (as bits) of three 32-step marches along the ray: as without wind,
// wind_ray_step at contrast `zero`, wind_ray_step at the contrast; then the last one's excess.
layout(std430, binding = 2) writeonly buffer Marches { uvec4 v[]; } marches;
layout(push_constant) uniform Push { uint count; };

void main() {
    uint id = gl_GlobalInvocationID.x;
    if (id >= count) return;
    vec4 p = cases.v[id * 8u], o1 = cases.v[id * 8u + 1u], o2 = cases.v[id * 8u + 2u];
    vec4 extra = cases.v[id * 8u + 3u];
    vec4 r0 = cases.v[id * 8u + 4u], r1 = cases.v[id * 8u + 5u], r2 = cases.v[id * 8u + 6u];
    vec3 ray = cases.v[id * 8u + 7u].xyz;
    float m = wind_density(p.xyz, o1.xyz, o2.xyz, p.w);
    values.v[id * 2u] = vec4(wind_noise3(p.xyz), wind_field(p.xyz, o1.xyz, o2.xyz), m,
                             wind_factor_rows(r0, r1, r2, p.xyz, o1.xyz, o2.xyz, p.w));
    values.v[id * 2u + 1u] = vec4(wind_view_to_world(r0, r1, r2, p.xyz), wind_view_shade(m, p.w));
    float density = o1.w, ds = o2.w, jitter = extra.x;
    float plain = 0.0, flat_energy = 0.0, flat_excess = 0.0, energy = 0.0, excess = 0.0;
    for (uint i = 0u; i < 32u; ++i) {
        float t = (float(i) + jitter) * ds;
        float vis = fract(float(i) * 0.6180339 + extra.y);
        plain += exp(-density * t) * density * ds * vis;
        wind_ray_step(flat_energy, flat_excess, density, ray, t, ds, jitter, vis, r0, r1, r2,
                      o1.xyz, o2.xyz, extra.z);
        wind_ray_step(energy, excess, density, ray, t, ds, jitter, vis, r0, r1, r2, o1.xyz,
                      o2.xyz, p.w);
    }
    marches.v[id] = uvec4(floatBitsToUint(plain), floatBitsToUint(flat_energy),
                          floatBitsToUint(energy), floatBitsToUint(excess));
}
''',
    "engine/tests/test_wind.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise
// (gpu/shim/bbport_wind.h) and the sun fog's march step (m, n, q). The GLSL copy is
// checked on the GPU by tests/test_wind_noise.cpp.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "gpu/shim/bbport_wind.h"

using namespace BbWind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

template <typename T>
bool SameBits(const T& a, const T& b) {
    return std::memcmp(&a, &b, sizeof(T)) == 0;
}

/// Field by field, so the padding of Snapshot is not compared.
bool Same(const Snapshot& a, const Snapshot& b) {
    return SameBits(a.on, b.on) && SameBits(a.time, b.time) && SameBits(a.direction_deg, b.direction_deg) &&
           SameBits(a.dir_x, b.dir_x) && SameBits(a.dir_z, b.dir_z) && SameBits(a.speed, b.speed) &&
           SameBits(a.gust, b.gust) && SameBits(a.wind, b.wind) && SameBits(a.off1, b.off1) &&
           SameBits(a.off2, b.off2);
}

/// splitmix64: a seeded sequence that is the same with every compiler and library.
struct Random {
    std::uint64_t state;
    std::uint64_t Next() {
        std::uint64_t z = (state += 0x9e3779b97f4a7c15ull);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
        return z ^ (z >> 31);
    }
    double Unit() { // [0, 1)
        return double(Next() >> 11) * (1.0 / 9007199254740992.0);
    }
};

float Circular(float a, float b) {
    const float d = std::fabs(a - b);
    return std::min(d, float(Period) - d);
}

constexpr Params On{.on = true};

struct Run {
    double distance = 0.0; // m: the sum of |wind| * step as the snapshots report it
    Snapshot last{};
};

/// 60 s of wind at a fixed rate (hz > 0) or with seeded random steps in [0, 0.1] s (hz == 0);
/// the last step lands exactly on 60 s.
Run Sixty(double hz, Params p, std::uint64_t seed = 1) {
    State state;
    Random random{seed};
    Run run;
    double t = 0.0;
    const double end = 60.0;
    for (int n = 0; t < end; ++n) {
        const double next = hz > 0.0 ? double(n + 1) / hz : t + random.Unit() * MaxStep;
        const double dt = std::min(next, end) - t;
        state.Advance(p, dt);
        t += dt;
        const Snapshot s = state.Get();
        run.distance += std::hypot(double(s.wind[0]), double(s.wind[2])) * dt;
    }
    run.last = state.Get();
    return run;
}
} // namespace

int main() {
    char what[160];

    // a. The step is clamped to 0.1 s; a NaN, negative or infinite step moves nothing.
    {
        State a, b;
        a.Advance(On, 0.5);
        b.Advance(On, 0.1);
        Expect(Same(a.Get(), b.Get()), "one Advance(0.5) equals one Advance(0.1)");
        Expect(a.Get().time == 0.1, "a 0.5 s step counts as 0.1 s");
        State c;
        for (int i = 0; i < 50; ++i) {
            c.Advance(On, 1.0 / 60.0);
        }
        for (double bad : {std::numeric_limits<double>::quiet_NaN(), -1.0,
                           std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()}) {
            const Snapshot before = c.Get();
            c.Advance(On, bad);
            const Snapshot after = c.Get();
            std::snprintf(what, sizeof(what), "a step of %g leaves the offsets and the time", bad);
            Expect(SameBits(before.off1, after.off1) && SameBits(before.off2, after.off2) &&
                       SameBits(before.time, after.time),
                   what);
        }
    }

    // b. Frame-rate independence: 60 s at 30, 60 and 144 Hz and with random steps.
    for (const float gusts : {0.5f, 1.0f}) {
        Params p = On;
        p.gusts = gusts;
        const Run reference = Sixty(144.0, p);
        Expect(std::fabs(reference.last.time - 60.0) < 1e-9, "144 Hz ends at 60 s");
        for (const double hz : {30.0, 60.0, 0.0}) {
            const Run run = Sixty(hz, p, 7);
            const double rel = std::fabs(run.distance - reference.distance) / reference.distance;
            float worst = 0.0f;
            for (std::size_t i = 0; i < 3; ++i) {
                worst = std::max(worst, Circular(run.last.off1[i], reference.last.off1[i]));
                worst = std::max(worst, Circular(run.last.off2[i], reference.last.off2[i]));
            }
            std::printf("wind-test: gusts %.1f, %s: %.3f m against %.3f m at 144 Hz (%.3f%%), "
                        "offsets differ by %.5f cells at most\n",
                        double(gusts), hz > 0.0 ? (hz == 30.0 ? "30 Hz" : "60 Hz") : "random steps",
                        run.distance, reference.distance, rel * 100.0, double(worst));
            std::snprintf(what, sizeof(what), "gusts %.1f at %g Hz: distance within 1%% of 144 Hz",
                          double(gusts), hz);
            Expect(rel <= 0.01, what);
            std::snprintf(what, sizeof(what), "gusts %.1f at %g Hz: offsets within 0.01 cells of 144 Hz",
                          double(gusts), hz);
            Expect(worst <= 0.01f, what);
            Expect(std::fabs(run.last.time - 60.0) < 1e-9, "the run ends at 60 s");
        }
    }

    // c. Gusts.
    {
        bool exact = true;
        for (int i = 0; i < 1000; ++i) {
            exact = exact && Gust(double(i) * 3.7 + 0.123, 0.0f) == 1.0f;
        }
        Expect(exact, "gusts 0 give exactly 1");
        for (const float g : {0.5f, 1.0f}) {
            double sum = 0.0;
            float lo = 10.0f, hi = -10.0f, jump = 0.0f;
            const int samples = 3600 * 20;
            for (int i = 0; i < samples; ++i) {
                const double t = double(i) / 20.0;
                const float v = Gust(t, g);
                sum += v;
                lo = std::min(lo, v);
                hi = std::max(hi, v);
            }
            for (int i = 0; i < 360000; ++i) {
                const double t = double(i) * 0.01;
                jump = std::max(jump, std::fabs(Gust(t + 0.01, g) - Gust(t, g)));
            }
            const double mean = sum / samples;
            std::printf("wind-test: gusts %.1f: mean over 1 h %.4f, range %.3f-%.3f, largest change "
                        "in 0.01 s %.4f (GustCentre %.4f)\n",
                        double(g), mean, double(lo), double(hi), double(jump), double(GustCentre));
            std::snprintf(what, sizeof(what), "gusts %.1f stay in 0.3-2.0", double(g));
            Expect(lo >= GustMin && hi <= GustMax, what);
            std::snprintf(what, sizeof(what), "gusts %.1f: the 1 h mean is in 0.95-1.05", double(g));
            Expect(mean >= 0.95 && mean <= 1.05, what);
            if (g == 1.0f) {
                Expect(jump <= 0.04f, "gusts 1 change by 0.04 at most in 0.01 s");
            }
        }
    }

    // d. Wander and the direction vector.
    {
        for (const float base : {225.0f, 0.0f, 359.0f}) {
            bool inside = true;
            for (int i = 0; i <= 3600; ++i) {
                const float deg = WanderDeg(double(i), base);
                inside = inside && deg >= base - Wander && deg <= base + Wander;
            }
            std::snprintf(what, sizeof(what), "the direction stays within %g +- 15 deg over 1 h", double(base));
            Expect(inside, what);
        }
        bool unit = true;
        for (float deg = -720.0f; deg <= 720.0f; deg += 0.5f) {
            const auto d = DirectionXZ(deg);
            unit = unit && std::fabs(std::hypot(d[0], d[1]) - 1.0f) <= 1e-6f;
        }
        Expect(unit, "DirectionXZ has length 1");
        const auto east = DirectionXZ(0.0f), north = DirectionXZ(90.0f);
        Expect(std::fabs(east[0] - 1.0f) <= 1e-6f && std::fabs(east[1]) <= 1e-6f, "0 deg is +x");
        Expect(std::fabs(north[0]) <= 1e-6f && std::fabs(north[1] - 1.0f) <= 1e-6f, "90 deg is +z");
        // The snapshot's wind points along the direction.
        State s;
        s.Advance(On, 0.05);
        const Snapshot w = s.Get();
        Expect(w.direction_deg >= DefaultDirection - Wander && w.direction_deg <= DefaultDirection + Wander,
               "the first snapshot's direction is within the wander");
        const float along = w.wind[0] * w.dir_x + w.wind[2] * w.dir_z;
        Expect(std::fabs(along - w.speed * w.gust) <= 1e-5f && w.wind[1] == 0.0f,
               "the wind is speed * gust along (dir_x, 0, dir_z)");
    }

    // e. Off: Advance without on changes nothing.
    {
        State s;
        const Snapshot fresh = s.Get();
        s.Advance(Params{}, 0.05);
        Expect(Same(fresh, s.Get()) && !s.Get().on, "off leaves a fresh state as it is");
        for (int i = 0; i < 30; ++i) {
            s.Advance(On, 0.03);
        }
        const Snapshot before = s.Get();
        s.Advance(Params{.on = false, .direction_deg = 10.0f, .speed = 4.0f, .gusts = 1.0f}, 0.05);
        Expect(Same(before, s.Get()), "off leaves an advanced state as it is");
        s.Reset();
        Expect(Same(fresh, s.Get()), "Reset gives the fresh state");
        // With speed 0 the offsets stay where they are.
        State still;
        Params calm = On;
        calm.speed = 0.0f;
        for (int i = 0; i < 100; ++i) {
            still.Advance(calm, 0.05);
        }
        const Snapshot c = still.Get();
        Expect(c.off1 == std::array<float, 3>{} && c.off2 == std::array<float, 3>{} && c.time > 4.99,
               "speed 0 keeps the offsets at 0");
    }

    // Sanitize.
    {
        const float nan = std::numeric_limits<float>::quiet_NaN();
        const Params a = Sanitize({.on = true, .direction_deg = nan, .speed = nan, .gusts = nan});
        Expect(a.direction_deg == DefaultDirection && a.speed == DefaultSpeed && a.gusts == DefaultGusts,
               "non-finite values become the defaults");
        const Params b = Sanitize({.on = true, .direction_deg = -90.0f, .speed = 9.0f, .gusts = 2.0f});
        Expect(b.direction_deg == 270.0f && b.speed == MaxSpeed && b.gusts == MaxGusts,
               "-90 deg wraps to 270, speed and gusts clamp at their maxima");
        const Params c = Sanitize({.on = true, .direction_deg = 720.0f, .speed = -1.0f, .gusts = -1.0f});
        Expect(c.direction_deg == 0.0f && c.speed == 0.0f && c.gusts == 0.0f,
               "720 deg wraps to 0, speed and gusts clamp at 0");
        const float inf = std::numeric_limits<float>::infinity();
        Expect(Sanitize({.on = true, .direction_deg = inf, .speed = -inf, .gusts = inf}).speed == DefaultSpeed,
               "an infinite speed becomes the default");
        Expect(SanitizeContrast(nan) == DefaultContrast && SanitizeContrast(5.0f) == MaxContrast &&
                   SanitizeContrast(-1.0f) == 0.0f && SanitizeContrast(MaxContrast) == MaxContrast,
               "the contrast clamps to 0-MaxContrast, NaN gives DefaultContrast");
    }

    // f. The noise repeats every 256 cells. The points and offsets lie on a 1/1024 grid that
    // p / 12, p / 6 and p / 4.5 keep exact, so the comparison sees the lattice, not float rounding.
    {
        Random random{11};
        float worst = 0.0f;
        for (int i = 0; i < 100; ++i) {
            std::array<float, 3> p{}, o1{}, o2{}, w1{}, w2{};
            for (std::size_t k = 0; k < 3; ++k) {
                p[k] = 36.0f * float(random.Next() % 5689) / 1024.0f; // 0-200 m
                o1[k] = float(random.Next() % (256 * 1024)) / 1024.0f;
                o2[k] = float(random.Next() % (256 * 1024)) / 1024.0f;
                w1[k] = o1[k] + 256.0f;
                w2[k] = o2[k] - 256.0f;
            }
            worst = std::max(worst, std::fabs(Density(p, o1, o2, 0.4f) - Density(p, w1, w2, 0.4f)));
            worst = std::max(worst, std::fabs(Field(p, o1, o2) - Field(p, w1, o2)));
        }
        std::snprintf(what, sizeof(what), "an offset 256 cells on gives the same density (%.2g)", double(worst));
        Expect(worst <= 1e-5f, what);
    }

    // g. The density's mean.
    {
        Random random{5};
        double field = 0.0, density = 0.0;
        bool flat = true;
        const int count = 100000;
        const std::array<float, 3> o1{17.25f, 3.5f, 101.0f}, o2{44.0f, 200.5f, 9.75f};
        for (int i = 0; i < count; ++i) {
            const std::array<float, 3> p{float(random.Unit() * 200.0), float(random.Unit() * 200.0),
                                         float(random.Unit() * 200.0)};
            const float n = Field(p, o1, o2);
            field += n;
            density += Density(p, o1, o2, 0.4f);
            flat = flat && Density(p, o1, o2, 0.0f) == 1.0f && n >= 0.0f && n < 1.0f;
        }
        field /= count;
        density /= count;
        std::printf("wind-test: over %d points in a 200 m cube the mean of N is %.4f and of the "
                    "density at contrast 0.4 %.4f\n",
                    count, field, density);
        Expect(std::fabs(field - 0.5) <= 0.01, "the mean of N is 0.5 +- 0.01");
        Expect(std::fabs(density - 1.0) <= 0.02, "the mean density at contrast 0.4 is 1 +- 0.02");
        Expect(flat, "contrast 0 gives exactly 1, and N lies in [0, 1)");
    }

    // h. Noise3 at six points: the values the GLSL copy must give (printed by this test's first
    // run; a separate double-precision copy of Hash3 and Noise3 in Python gave them within 1e-7).
    {
        struct Pin {
            float x, y, z, value;
        };
        constexpr std::array<Pin, 6> pins{{
            {0.0f, 0.0f, 0.0f, 0.6081519f},
            {0.5f, 0.5f, 0.5f, 0.5781672f},
            {1.25f, 7.5f, -3.75f, 0.5259736f},
            {255.9f, 0.0f, 0.0f, 0.6062171f},
            {-0.3f, 12.7f, 100.1f, 0.4207422f},
            {3.0f, 3.0f, 3.0f, 0.4130008f},
        }};
        for (const Pin& pin : pins) {
            const float v = Noise3(pin.x, pin.y, pin.z);
            std::printf("wind-test: Noise3(%g, %g, %g) = %.7f\n", double(pin.x), double(pin.y), double(pin.z),
                        double(v));
            std::snprintf(what, sizeof(what), "Noise3(%g, %g, %g) is the pinned %.7f", double(pin.x),
                          double(pin.y), double(pin.z), double(pin.value));
            Expect(std::fabs(v - pin.value) <= 1e-6f, what);
        }
    }

    // i. GustAt with speed 0 (or NaN) does not divide by zero: both use the 0.1 m/s floor.
    {
        const float a = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f, 0.0f);
        const float b = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f,
                               std::numeric_limits<float>::quiet_NaN());
        const float floored = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f, 0.1f);
        Expect(std::isfinite(a) && std::isfinite(b), "GustAt with speed 0 or NaN is finite");
        Expect(a == floored && b == floored,"GustAt with speed 0 or NaN is GustAt at the 0.1 m/s floor");
        Expect(GustAt(12.0, 0.7f, 0.0f, 0.0f, 1.0f, 0.0f, 1.5f) == Gust(12.0, 0.7f),
               "GustAt at the origin is Gust");
        Expect(GustAt(12.0, 0.7f, 3.0f, 0.0f, 1.0f, 0.0f, 1.5f) == Gust(10.0, 0.7f),
               "GustAt 3 m downwind at 1.5 m/s is the gust of 2 s before");
    }

    // j. The offsets' absolute rates, from the plan's numbers written out here (not the header's
    // constants): octave 1 moves by wind / (12, 6, 12) m, octave 2 by wind * 1.6 / 4.5 m. A
    // steady wind (gusts 0) at 1.5 m/s, 20 s of 0.05 s steps; the wander turns it, so the
    // expected offsets sum each step's snapshot wind. With gusts 0 the wind is exactly 1.5 m/s.
    {
        State s;
        Params p = On;
        p.gusts = 0.0f;
        std::array<double, 3> moved{};
        double distance = 0.0;
        for (int i = 0; i < 400; ++i) {
            s.Advance(p, 0.05);
            const Snapshot w = s.Get();
            for (std::size_t k = 0; k < 3; ++k) {
                moved[k] += double(w.wind[k]) * 0.05;
            }
            distance += std::hypot(double(w.wind[0]), double(w.wind[2])) * 0.05;
        }
        const Snapshot w = s.Get();
        const std::array<double, 3> cell1{12.0, 6.0, 12.0};
        float worst = 0.0f;
        for (std::size_t k = 0; k < 3; ++k) {
            worst = std::max(worst, Circular(w.off1[k], float(WrapCells(moved[k] / cell1[k]))));
            worst = std::max(worst, Circular(w.off2[k], float(WrapCells(moved[k] * 1.6 / 4.5))));
        }
        std::printf("wind-test: a steady 1.5 m/s for 20 s: %.4f m, offsets %.4f %.4f / %.4f %.4f "
                    "cells, %.2g from the plan's rates\n",
                    distance, double(w.off1[0]), double(w.off1[2]), double(w.off2[0]), double(w.off2[2]),
                    double(worst));
        Expect(std::fabs(distance - 30.0) <= 1e-4, "a steady 1.5 m/s wind covers 30 m in 20 s");
        Expect(worst <= 1e-4f, "the offsets move by wind / (12, 6, 12) m and wind * 1.6 / 4.5 m");
        Expect(w.off1[1] == 0.0f && w.off2[1] == 0.0f, "the y offsets stay 0");
    }

    // k. Field at world points with non-zero offsets: ties the 12 / 6 / 4.5 m scales, the
    // 0.65 / 0.35 weights and the offsets' sign, beside the Noise3 pins (h). The values the GLSL
    // copy of Field must give (printed by this test's first run; a separate Python copy that
    // rounds the coordinates to float32 the same way and runs Noise3 in double agreed within 1e-7).
    {
        struct Pin {
            std::array<float, 3> p, o1, o2;
            float value;
        };
        const std::array<Pin, 4> pins{{
            {{0.0f, 0.0f, 0.0f}, {0.25f, 0.5f, 0.75f}, {1.5f, 2.25f, 3.0f}, 0.2916170f},
            {{13.0f, 7.0f, -25.0f}, {3.125f, 0.0f, 250.5f}, {17.75f, 0.0f, 128.0f}, 0.4034448f},
            {{101.3f, 2.4f, 57.9f}, {200.0f, 0.0f, 33.3f}, {5.5f, 0.0f, 99.9f}, 0.6770673f},
            {{-48.6f, 15.2f, 211.7f}, {12.75f, 0.0f, 0.5f}, {255.5f, 0.0f, 64.25f}, 0.3751206f},
        }};
        for (const Pin& pin : pins) {
            const float v = Field(pin.p, pin.o1, pin.o2);
            std::printf("wind-test: Field(%g, %g, %g; %g %g %g; %g %g %g) = %.7f, density at 0.4 %.7f\n",
                        double(pin.p[0]), double(pin.p[1]), double(pin.p[2]), double(pin.o1[0]),
                        double(pin.o1[1]), double(pin.o1[2]), double(pin.o2[0]), double(pin.o2[1]),
                        double(pin.o2[2]), double(v), double(Density(pin.p, pin.o1, pin.o2, 0.4f)));
            std::snprintf(what, sizeof(what), "Field at (%g, %g, %g) is the pinned %.7f", double(pin.p[0]),
                          double(pin.p[1]), double(pin.p[2]), double(pin.value));
            Expect(std::fabs(v - pin.value) <= 1e-6f, what);
            const float m = Density(pin.p, pin.o1, pin.o2, 0.4f);
            Expect(std::fabs(m - std::max(0.0f, 1.0f + 0.4f * (2.0f * pin.value - 1.0f))) <= 1e-6f,
                   "Density is max(0, 1 + 0.4 (2 Field - 1))");
        }
    }

    // l. The direction and the gust are taken at the NEW wind time (after the step), as Advance
    // says: after 600 steps of 0.1 s the snapshot equals Gust and WanderDeg at the snapshot's time.
    // Taken at the time before the step they would differ by about the change over 0.1 s, which
    // the test prints.
    {
        State s;
        Params p = On;
        p.gusts = 1.0f;
        for (int i = 0; i < 600; ++i) {
            s.Advance(p, 0.1);
        }
        const Snapshot w = s.Get();
        float deg = std::fmod(WanderDeg(w.time, DefaultDirection), 360.0f);
        if (deg < 0.0f) {
            deg += 360.0f;
        }
        const float old_gust = Gust(w.time - 0.1, 1.0f);
        const float old_deg = WanderDeg(w.time - 0.1, DefaultDirection);
        std::printf("wind-test: at %.1f s the gust %.6f (at the step's start %.6f), direction %.5f "
                    "(at the step's start %.5f)\n",
                    w.time, double(w.gust), double(old_gust), double(w.direction_deg), double(old_deg));
        Expect(std::fabs(w.gust - Gust(w.time, 1.0f)) <= 1e-6f, "the gust is taken at the new time");
        Expect(std::fabs(w.direction_deg - deg) <= 1e-5f, "the direction is taken at the new time");
        Expect(std::fabs(old_gust - w.gust) > 1e-4f && std::fabs(old_deg - w.direction_deg) > 1e-4f,
               "this check can tell the new time from the old one");
    }

    // m. The march step at m = 1 gives the bits of the march without wind
    // (volumetric_light.comp's plain line), for 2000 random rays of 32 steps, and excess stays 0.
    {
        Random random{59};
        bool same = true, zero = true;
        for (int ray = 0; ray < 2000; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            float plain = 0.0f;
            March march;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Next() % 5) * 0.25f;
                plain += std::exp(-density * t) * density * ds * vis;
                MarchStep(march, density, t, ds, jitter, 1.0f, vis);
                same = same && SameBits(plain, march.energy);
                zero = zero && SameBits(march.excess, 0.0f);
            }
        }
        Expect(same, "MarchStep at m = 1 gives the bits of exp(-density t) density ds vis");
        Expect(zero, "MarchStep at m = 1 keeps excess at +0");
    }

    // n. With the noise the step is the plan's: s = density m, energy += exp(-(tau + s jitter ds))
    // s ds vis, tau += s ds (in double here); a constant m = k is a fog k times as dense; the last
    // optical depth density (t_end + excess) is density times the sum of m ds.
    {
        Random random{60};
        double worst = 0.0, worst_k = 0.0, worst_tau = 0.0;
        for (int ray = 0; ray < 500; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            const float contrast = MaxContrast * float(random.Unit());
            const float k = float(0.1 + 1.8 * random.Unit());
            std::array<float, 3> start{}, dir{}, o1{}, o2{};
            double length = 0.0;
            for (std::size_t a = 0; a < 3; ++a) {
                start[a] = float(random.Unit() * 400.0 - 200.0);
                dir[a] = float(random.Unit() * 2.0 - 1.0);
                length += double(dir[a]) * dir[a];
                o1[a] = float(random.Unit() * 256.0);
                o2[a] = float(random.Unit() * 256.0);
            }
            for (auto& d : dir) {
                d = float(d / std::sqrt(length));
            }
            March march, constant;
            float plain_k = 0.0f;
            double energy = 0.0, tau = 0.0, sum = 0.0;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Unit());
                const std::array<float, 3> at{start[0] + dir[0] * t, start[1] + dir[1] * t,
                                              start[2] + dir[2] * t};
                const float m = Density(at, o1, o2, contrast);
                MarchStep(march, density, t, ds, jitter, m, vis);
                const double s = double(density) * m;
                energy += std::exp(-(tau + s * jitter * ds)) * s * ds * vis;
                tau += s * ds;
                sum += double(m) * ds;
                MarchStep(constant, density, t, ds, jitter, k, vis);
                plain_k += std::exp(-(density * k) * t) * (density * k) * ds * vis;
            }
            const double end = 32.0 * ds; // the march's length: t + excess then is the sum of m ds
            worst = std::max(worst, std::fabs(march.energy - energy) / std::max(energy, 1e-12));
            worst_k = std::max(worst_k, std::fabs(double(constant.energy) - plain_k) /
                                            std::max(double(plain_k), 1e-12));
            const double depth = double(density) * (end + march.excess);
            worst_tau = std::max(worst_tau, std::fabs(depth - double(density) * sum) /
                                                std::max(double(density) * sum, 1e-12));
        }
        std::printf("wind-test: march with the noise against the plan's tau form %.2g, constant m "
                    "against a denser fog %.2g, last optical depth %.2g (relative, at most)\n",
                    worst, worst_k, worst_tau);
        Expect(worst <= 1e-5, "MarchStep is the plan's step (tau + s jitter ds) within 1e-5");
        Expect(worst_k <= 1e-5, "a constant m = k marches like a fog k times as dense within 1e-5");
        Expect(worst_tau <= 1e-5, "density (t_end + excess) is density times the sum of m ds");
    }

    // o. The noise's correlation lengths: the lag at which N's autocorrelation along x, y and z
    // falls to 0.5 is within 10% of what 12 m across, 6 m up and 4.5 m give, predicted from
    // Noise3's own autocorrelation on its unit lattice as (0.65^2 r(lag / L1) + 0.35^2
    // r(lag / 4.5 m)) / (0.65^2 + 0.35^2) (the two octaves are independent: other offsets, other
    // cells).
    {
        constexpr int Points = 6000;
        Random random{61};
        std::vector<std::array<float, 3>> base(Points);
        for (auto& b : base) {
            for (auto& c : b) {
                c = float(random.Unit() * 240.0);
            }
        }
        const auto correlation = [&](auto value, std::size_t axis, float lag) {
            double sa = 0.0, sb = 0.0, saa = 0.0, sbb = 0.0, sab = 0.0;
            for (const auto& b : base) {
                auto moved = b;
                moved[axis] += lag;
                const double x = value(b), y = value(moved);
                sa += x;
                sb += y;
                saa += x * x;
                sbb += y * y;
                sab += x * y;
            }
            const double n = Points;
            const double cov = sab / n - sa / n * (sb / n);
            return cov / std::sqrt((saa / n - sa / n * (sa / n)) * (sbb / n - sb / n * (sb / n)));
        };
        // Noise3's own autocorrelation on its lattice, 1/32 cell apart up to 3 cells.
        std::array<double, 97> unit{};
        const auto noise = [](const std::array<float, 3>& p) {
            return double(Noise3(p[0], p[1], p[2]));
        };
        for (std::size_t k = 0; k < unit.size(); ++k) {
            unit[k] = correlation(noise, 0, float(k) / 32.0f);
        }
        const auto unit_at = [&](double cells) {
            const double at = std::min(cells * 32.0, double(unit.size() - 1));
            const std::size_t lo = std::min(std::size_t(at), unit.size() - 2);
            return unit[lo] + (unit[lo + 1] - unit[lo]) * (at - double(lo));
        };
        // The first lag (m, 0.05 m apart) at which a correlation falls under 0.5, interpolated.
        const auto half = [](auto rho) {
            double before = 1.0;
            for (int k = 1; k <= 600; ++k) {
                const double now = rho(k * 0.05);
                if (now < 0.5) {
                    return (k - 1 + (before - 0.5) / (before - now)) * 0.05;
                }
                before = now;
            }
            return 30.0;
        };
        const std::array<float, 3> o1{10.5f, 20.25f, 30.75f}, o2{140.5f, 7.25f, 99.0f};
        const auto field = [&](const std::array<float, 3>& p) { return double(Field(p, o1, o2)); };
        constexpr std::array<double, 3> across{12.0, 6.0, 12.0};
        constexpr const char* names[3] = {"x", "y", "z"};
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double model = half([&](double lag) {
                return (0.4225 * unit_at(lag / across[axis]) + 0.1225 * unit_at(lag / 4.5)) / 0.545;
            });
            // Bisection on the measured correlation, from the model's neighbourhood outwards.
            double lo = 0.0, hi = 3.0 * model;
            for (int step = 0; step < 24; ++step) {
                const double mid = 0.5 * (lo + hi);
                (correlation(field, axis, float(mid)) < 0.5 ? hi : lo) = mid;
            }
            const double measured = 0.5 * (lo + hi);
            std::printf("wind-test: N's autocorrelation along %s falls to 0.5 at %.3f m (the "
                        "wavelengths give %.3f m)\n",
                        names[axis], measured, model);
            std::snprintf(what, sizeof(what),
                          "the correlation length along %s is within 10%% of the wavelengths'",
                          names[axis]);
            Expect(std::fabs(measured / model - 1.0) <= 0.10, what);
        }
    }


    // p. ViewToWorld on a turned and moved camera (rows as
    // CameraMotion::PassMatrices().inv_view stores them, translation in [3], [7], [11]): the view
    // origin goes to the translation, view +z 10 m ahead to translation + 10 times the third
    // column. ViewShade stretches m over 1 - C to 1 + C. The mean of m at the default contrast
    // and at the largest stays 1 +- 0.03 (at 2, m is clipped at 0 where N < 0.25).
    {
        // 90 deg about y: view +x looks toward world -z, view +z toward world +x.
        const std::array<float, 12> rows{0, 0, 1, 5, 0, 1, 0, -2, -1, 0, 0, 7};
        const auto o = ViewToWorld(rows, {0.0f, 0.0f, 0.0f});
        const auto z = ViewToWorld(rows, {0.0f, 0.0f, 10.0f});
        const auto x = ViewToWorld(rows, {3.0f, 0.0f, 0.0f});
        Expect(o == std::array<float, 3>{5.0f, -2.0f, 7.0f}, "ViewToWorld: the origin goes to the translation");
        Expect(z == std::array<float, 3>{15.0f, -2.0f, 7.0f}, "ViewToWorld: view +z goes along the third column");
        Expect(x == std::array<float, 3>{5.0f, -2.0f, 4.0f}, "ViewToWorld: view +x goes along the first column");
        Expect(ViewShade(1.0f, 0.0f) == 0.5f && ViewShade(1.0f, 0.5f) == 0.5f &&
                   ViewShade(0.5f, 0.5f) == 0.0f && ViewShade(1.5f, 0.5f) == 1.0f &&
                   ViewShade(0.0f, 2.0f) == 0.25f && ViewShade(9.0f, 1.0f) == 1.0f &&
                   ViewShade(1.0f, std::numeric_limits<float>::quiet_NaN()) == 0.5f,
               "ViewShade: 1 - C is 0, 1 is 0.5, 1 + C is 1, clamped; 0.5 at contrast 0 or NaN");
        Random random{62};
        const std::array<float, 3> o1{3.5f, 9.25f, 71.0f}, o2{120.0f, 33.5f, 2.75f};
        double at_default = 0.0, at_max = 0.0, shade = 0.0;
        const int count = 100000;
        for (int i = 0; i < count; ++i) {
            const std::array<float, 3> p{float(random.Unit() * 200.0), float(random.Unit() * 200.0),
                                         float(random.Unit() * 200.0)};
            const float m = Density(p, o1, o2, DefaultContrast);
            at_default += m;
            at_max += Density(p, o1, o2, MaxContrast);
            shade += std::fabs(ViewShade(m, DefaultContrast) - Field(p, o1, o2));
        }
        std::printf("wind-test: the mean density at the default contrast %.2f is %.4f, at the "
                    "largest %.2f %.4f\n",
                    double(DefaultContrast), at_default / count, double(MaxContrast), at_max / count);
        Expect(std::fabs(at_default / count - 1.0) <= 0.03, "the mean density at the default contrast is 1 +- 0.03");
        Expect(std::fabs(at_max / count - 1.0) <= 0.03, "the mean density at the largest contrast is 1 +- 0.03");
        Expect(shade / count <= 1e-6, "at the default contrast the view shade is N");
    }

    // q. MarchLitStep, the step the sun fog takes: where the sample is lit it is MarchStep bit for
    // bit; where it is in shadow (vis 0) it changes neither the light nor the excess, whatever m
    // is (2000 random rays of 32 steps, a third of the samples in shadow, m from 0 to 2).
    {
        Random random{63};
        bool lit_same = true, shadow_still = true;
        for (int ray = 0; ray < 2000; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            March march;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Next() % 3) * 0.5f;
                const float m = float(2.0 * random.Unit());
                March full = march;
                const March before = march;
                MarchStep(full, density, t, ds, jitter, m, vis);
                MarchLitStep(march, density, t, ds, jitter, m, vis);
                if (vis > 0.0f) {
                    lit_same = lit_same && SameBits(full.energy, march.energy) &&
                               SameBits(full.excess, march.excess);
                } else {
                    shadow_still = shadow_still && SameBits(before.energy, march.energy) &&
                                   SameBits(before.excess, march.excess);
                }
            }
        }
        Expect(lit_same, "MarchLitStep on a lit sample is MarchStep");
        Expect(shadow_still, "MarchLitStep on a sample in shadow changes nothing");
    }

    if (failures) {
        std::printf("wind-test: %d failure(s)\n", failures);
        return failures != 0;
    }
    std::printf("wind-test: ok\n");
    return 0;
}
''',
    "engine/tests/test_wind_noise.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the GLSL copy of the fog noise, the march step and the view helpers
// (host_shaders/wind_noise.glsl, run by wind_noise_test.comp) against gpu/shim/bbport_wind.h on
// the GPU: the pinned Noise3 and Field values of tests/test_wind.cpp to 1e-6, 4096 random points
// against the C++ functions (Noise3 1e-6, Field 1e-4: see there), the view to world rows of a
// turned and moved camera (ViewToWorld), the test view's shade (ViewShade), contrast 0 giving
// exactly 1, and the march along a view ray: at a contrast of 0 read at run time within 1e-6 of
// the march without wind (not bit for bit: the driver may fuse the two expressions' multiply-adds
// differently; a literal 1 was folded at compile time and hid that), and with the noise as the
// C++ MarchStep within 1e-4 of the even fog's light. One dispatch.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "gpu/shim/bbport_wind.h"
#include "video_core/host_shaders/wind_noise_test_comp.h"

namespace {
#define CHECK(call) do { if ((call) != VK_SUCCESS) { std::fprintf(stderr, "%s failed\n", #call); std::abort(); } } while (false)
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

struct Buffer { VkBuffer buffer{}; VkDeviceMemory memory{}; void* data{}; unsigned size{}; };

struct Gpu {
    VkInstance instance{};
    VkPhysicalDevice gpu{};
    VkDevice device{};
    VkQueue queue{};
    VkPhysicalDeviceMemoryProperties memory{};
    VkCommandPool pool{};
    VkCommandBuffer cmd{};
    VkDescriptorSetLayout set{};
    VkPipelineLayout layout{};
    VkPipeline pipeline{};
    PFN_vkCmdPushDescriptorSetKHR descriptors{};
    std::vector<Buffer> buffers;

    unsigned Memory(unsigned bits, VkMemoryPropertyFlags flags) {
        for (unsigned i = 0; i < memory.memoryTypeCount; ++i)
            if ((bits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) return i;
        std::abort();
    }
    Buffer MakeBuffer(unsigned size) {
        Buffer b{.size = size};
        VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = size,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
        CHECK(vkCreateBuffer(device, &info, nullptr, &b.buffer));
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, b.buffer, &req);
        VkMemoryAllocateInfo alloc{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = req.size, .memoryTypeIndex = Memory(req.memoryTypeBits,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
        CHECK(vkAllocateMemory(device, &alloc, nullptr, &b.memory));
        CHECK(vkBindBufferMemory(device, b.buffer, b.memory, 0));
        CHECK(vkMapMemory(device, b.memory, 0, VK_WHOLE_SIZE, 0, &b.data));
        std::memset(b.data, 0, size);
        buffers.push_back(b);
        return b;
    }
    Gpu() {
        VkApplicationInfo app{.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "wind-noise-test", .apiVersion = VK_API_VERSION_1_3};
        VkInstanceCreateInfo ci{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
        CHECK(vkCreateInstance(&ci, nullptr, &instance));
        unsigned count = 0;
        CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
        if (count == 0) {
            std::fprintf(stderr, "no Vulkan device\n");
            std::abort();
        }
        std::vector<VkPhysicalDevice> devices(count);
        CHECK(vkEnumeratePhysicalDevices(instance, &count, devices.data()));
        gpu = devices[0];
        vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
        unsigned families_count = 0, family = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families_count, nullptr);
        std::vector<VkQueueFamilyProperties> families(families_count);
        vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families_count, families.data());
        while (family < families_count && !(families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) ++family;
        if (family == families_count) std::abort();
        const float priority = 1;
        VkDeviceQueueCreateInfo qi{.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
        const char* extension = VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
        VkDeviceCreateInfo di{.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi,
            .enabledExtensionCount = 1, .ppEnabledExtensionNames = &extension};
        CHECK(vkCreateDevice(gpu, &di, nullptr, &device));
        vkGetDeviceQueue(device, family, 0, &queue);
        descriptors = reinterpret_cast<PFN_vkCmdPushDescriptorSetKHR>(
            vkGetDeviceProcAddr(device, "vkCmdPushDescriptorSetKHR"));
        if (!descriptors) std::abort();
        VkCommandPoolCreateInfo pi{.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .queueFamilyIndex = family};
        CHECK(vkCreateCommandPool(device, &pi, nullptr, &pool));
        VkCommandBufferAllocateInfo ai{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        CHECK(vkAllocateCommandBuffers(device, &ai, &cmd));
        std::array<VkDescriptorSetLayoutBinding, 3> bindings{};
        for (unsigned i = 0; i < bindings.size(); ++i)
            bindings[i] = {i, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr};
        VkDescriptorSetLayoutCreateInfo si{.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
            .bindingCount = unsigned(bindings.size()), .pBindings = bindings.data()};
        CHECK(vkCreateDescriptorSetLayout(device, &si, nullptr, &set));
        VkPushConstantRange range{VK_SHADER_STAGE_COMPUTE_BIT, 0, 4};
        VkPipelineLayoutCreateInfo li{.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
            .setLayoutCount = 1, .pSetLayouts = &set, .pushConstantRangeCount = 1, .pPushConstantRanges = &range};
        CHECK(vkCreatePipelineLayout(device, &li, nullptr, &layout));
        VkShaderModule module;
        VkShaderModuleCreateInfo mi{.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
            .codeSize = sizeof(WIND_NOISE_TEST_COMP), .pCode = WIND_NOISE_TEST_COMP};
        CHECK(vkCreateShaderModule(device, &mi, nullptr, &module));
        VkComputePipelineCreateInfo pc{.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
            .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = layout};
        CHECK(vkCreateComputePipelines(device, {}, 1, &pc, nullptr, &pipeline));
        vkDestroyShaderModule(device, module, nullptr);
    }
    void Run(const Buffer& cases, const Buffer& values, const Buffer& marches, unsigned count) {
        VkCommandBufferBeginInfo begin{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        CHECK(vkBeginCommandBuffer(cmd, &begin));
        const std::array<VkDescriptorBufferInfo, 3> infos{{{cases.buffer, 0, cases.size},
                                                           {values.buffer, 0, values.size},
                                                           {marches.buffer, 0, marches.size}}};
        std::array<VkWriteDescriptorSet, 3> writes{};
        for (unsigned i = 0; i < writes.size(); ++i)
            writes[i] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = i,
                         .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                         .pBufferInfo = &infos[i]};
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
        descriptors(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 3, writes.data());
        vkCmdPushConstants(cmd, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 4, &count);
        vkCmdDispatch(cmd, (count + 63) / 64, 1, 1);
        VkMemoryBarrier host{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
            0, 1, &host, 0, nullptr, 0, nullptr);
        CHECK(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit{.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmd};
        CHECK(vkQueueSubmit(queue, 1, &submit, {}));
        CHECK(vkQueueWaitIdle(queue));
    }
    ~Gpu() {
        vkDeviceWaitIdle(device);
        for (auto b : buffers) {
            vkUnmapMemory(device, b.memory);
            vkDestroyBuffer(device, b.buffer, nullptr);
            vkFreeMemory(device, b.memory, nullptr);
        }
        vkDestroyPipeline(device, pipeline, nullptr);
        vkDestroyPipelineLayout(device, layout, nullptr);
        vkDestroyDescriptorSetLayout(device, set, nullptr);
        vkDestroyCommandPool(device, pool, nullptr);
        vkDestroyDevice(device, nullptr);
        vkDestroyInstance(instance, nullptr);
    }
};

/// splitmix64, as in tests/test_wind.cpp.
struct Random {
    std::uint64_t state;
    std::uint64_t Next() {
        std::uint64_t z = (state += 0x9e3779b97f4a7c15ull);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
        return z ^ (z >> 31);
    }
    float Unit() { // [0, 1)
        return float(Next() >> 40) * (1.0f / 16777216.0f);
    }
};

struct Case {
    std::array<float, 3> p, o1, o2;
    float contrast, density, ds, jitter, seed;
    std::array<float, 12> rows;  ///< view to world, 3x4 rows
    std::array<float, 3> ray;    ///< unit view ray of the march
};

constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};

/// The C++ side of the shader's third march: MarchStep with m = Density at ViewToWorld(ray t),
/// as wind_ray_step takes it.
float CpuMarch(const Case& c) {
    BbWind::March march;
    for (unsigned i = 0; i < 32; ++i) {
        const float t = (float(i) + c.jitter) * c.ds;
        const float scaled = float(i) * 0.6180339f + c.seed;
        const float vis = scaled - std::floor(scaled);
        const std::array<float, 3> v{c.ray[0] * t, c.ray[1] * t, c.ray[2] * t};
        const float m = BbWind::Density(BbWind::ViewToWorld(c.rows, v), c.o1, c.o2, c.contrast);
        BbWind::MarchStep(march, c.density, t, c.ds, c.jitter, m, vis);
    }
    return march.energy;
}
} // namespace

int main() {
    char what[200];
    std::vector<Case> cases;
    // The six Noise3 pins and the four Field pins of tests/test_wind.cpp (h, k).
    constexpr std::array<std::array<float, 4>, 6> noise_pins{{
        {0.0f, 0.0f, 0.0f, 0.6081519f},
        {0.5f, 0.5f, 0.5f, 0.5781672f},
        {1.25f, 7.5f, -3.75f, 0.5259736f},
        {255.9f, 0.0f, 0.0f, 0.6062171f},
        {-0.3f, 12.7f, 100.1f, 0.4207422f},
        {3.0f, 3.0f, 3.0f, 0.4130008f},
    }};
    struct FieldPin {
        std::array<float, 3> p, o1, o2;
        float value;
    };
    const std::array<FieldPin, 4> field_pins{{
        {{0.0f, 0.0f, 0.0f}, {0.25f, 0.5f, 0.75f}, {1.5f, 2.25f, 3.0f}, 0.2916170f},
        {{13.0f, 7.0f, -25.0f}, {3.125f, 0.0f, 250.5f}, {17.75f, 0.0f, 128.0f}, 0.4034448f},
        {{101.3f, 2.4f, 57.9f}, {200.0f, 0.0f, 33.3f}, {5.5f, 0.0f, 99.9f}, 0.6770673f},
        {{-48.6f, 15.2f, 211.7f}, {12.75f, 0.0f, 0.5f}, {255.5f, 0.0f, 64.25f}, 0.3751206f},
    }};
    for (const auto& pin : noise_pins)
        cases.push_back({{pin[0], pin[1], pin[2]}, {}, {}, 0.4f, 0.025f, 1.25f, 0.5f, 0.25f,
                         Identity, {1.0f, 0.0f, 0.0f}});
    for (const auto& pin : field_pins)
        cases.push_back({pin.p, pin.o1, pin.o2, 0.4f, 0.025f, 1.25f, 0.5f, 0.75f, Identity,
                         {0.0f, 0.0f, 1.0f}});
    Random random{2026};
    // 0 (an even fog), the plan's 0.4, the default and the largest.
    const std::array<float, 4> contrasts{0.0f, 0.4f, BbWind::DefaultContrast, BbWind::MaxContrast};
    for (unsigned i = 0; i < 4096; ++i) {
        Case c{};
        for (unsigned k = 0; k < 3; ++k) {
            c.p[k] = random.Unit() * 600.0f - 300.0f;
            c.o1[k] = random.Unit() * 256.0f;
            c.o2[k] = random.Unit() * 256.0f;
        }
        c.contrast = contrasts[i % contrasts.size()];
        c.density = 0.01f + 0.04f * random.Unit();
        c.ds = 0.1f + 1.4f * random.Unit();
        c.jitter = random.Unit();
        c.seed = random.Unit();
        // A camera turned by yaw and pitch, placed up to 300 m from the origin: a matrix whose
        // rows all differ, so a swapped row or a lost translation changes the world point.
        const float yaw = random.Unit() * 6.2831853f, pitch = (random.Unit() - 0.5f) * 1.5f;
        const float cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
        c.rows = {cy, sy * sp, sy * cp, random.Unit() * 600.0f - 300.0f,
                  0.0f, cp, -sp, random.Unit() * 40.0f - 20.0f,
                  -sy, cy * sp, cy * cp, random.Unit() * 600.0f - 300.0f};
        const float a = random.Unit() * 6.2831853f, e = (random.Unit() - 0.5f) * 1.2f;
        c.ray = {std::cos(a) * std::cos(e), std::sin(e), std::sin(a) * std::cos(e)};
        cases.push_back(c);
    }
    const unsigned count = unsigned(cases.size());
    Gpu gpu;
    const Buffer in = gpu.MakeBuffer(count * 128), values = gpu.MakeBuffer(count * 32),
                 marches = gpu.MakeBuffer(count * 16);
    auto* words = static_cast<float*>(in.data);
    for (unsigned i = 0; i < count; ++i) {
        const Case& c = cases[i];
        const std::array<float, 32> v{c.p[0], c.p[1], c.p[2], c.contrast, c.o1[0], c.o1[1], c.o1[2],
                                      c.density, c.o2[0], c.o2[1], c.o2[2], c.ds, c.jitter, c.seed,
                                      0.0f, 0.0f, c.rows[0], c.rows[1], c.rows[2], c.rows[3],
                                      c.rows[4], c.rows[5], c.rows[6], c.rows[7], c.rows[8],
                                      c.rows[9], c.rows[10], c.rows[11], c.ray[0], c.ray[1],
                                      c.ray[2], 0.0f};
        std::memcpy(words + i * 32, v.data(), sizeof(v));
    }
    gpu.Run(in, values, marches, count);
    const auto* out = static_cast<const float*>(values.data);
    const auto* bits = static_cast<const std::uint32_t*>(marches.data);

    for (unsigned i = 0; i < noise_pins.size(); ++i) {
        const float got = out[i * 8];
        std::printf("wind-noise-test: GPU Noise3(%g, %g, %g) = %.7f (pinned %.7f)\n",
                    double(noise_pins[i][0]), double(noise_pins[i][1]), double(noise_pins[i][2]),
                    double(got), double(noise_pins[i][3]));
        std::snprintf(what, sizeof(what), "GPU Noise3 pin %u within 1e-6", i);
        Expect(std::fabs(got - noise_pins[i][3]) <= 1e-6f, what);
    }
    for (unsigned i = 0; i < field_pins.size(); ++i) {
        const float got = out[(noise_pins.size() + i) * 8 + 1];
        std::printf("wind-noise-test: GPU Field pin %u = %.7f (pinned %.7f)\n", i, double(got),
                    double(field_pins[i].value));
        std::snprintf(what, sizeof(what), "GPU Field pin %u within 1e-6", i);
        Expect(std::fabs(got - field_pins[i].value) <= 1e-6f, what);
    }
    float worst_noise = 0.0f, worst_field = 0.0f, worst_density = 0.0f, worst_march = 0.0f;
    float worst_rows = 0.0f, worst_world = 0.0f, worst_shade = 0.0f, worst_flat = 0.0f;
    unsigned same_bits = 0, flat_exact = 0, flat_cases = 0;
    for (unsigned i = 0; i < count; ++i) {
        const Case& c = cases[i];
        const float* o = out + i * 8;
        const float noise = BbWind::Noise3(c.p[0], c.p[1], c.p[2]);
        const float field = BbWind::Field(c.p, c.o1, c.o2);
        const float density = BbWind::Density(c.p, c.o1, c.o2, c.contrast);
        const std::array<float, 3> world = BbWind::ViewToWorld(c.rows, c.p);
        const float through_rows = BbWind::Density(world, c.o1, c.o2, c.contrast);
        worst_noise = std::max(worst_noise, std::fabs(o[0] - noise));
        worst_field = std::max(worst_field, std::fabs(o[1] - field));
        worst_density = std::max(worst_density, std::fabs(o[2] - density));
        worst_rows = std::max(worst_rows, std::fabs(o[3] - through_rows));
        for (unsigned k = 0; k < 3; ++k)
            worst_world = std::max(worst_world, std::fabs(o[4 + k] - world[k]));
        // The shade of the GPU's own m: this checks wind_view_shade alone.
        worst_shade = std::max(worst_shade, std::fabs(o[7] - BbWind::ViewShade(o[2], c.contrast)));
        if (c.contrast == 0.0f) {
            ++flat_cases;
            flat_exact += o[2] == 1.0f;
        }
        same_bits += bits[i * 4] == bits[i * 4 + 1];
        float plain_energy, flat_energy, gpu_energy;
        std::memcpy(&plain_energy, &bits[i * 4], 4);
        std::memcpy(&flat_energy, &bits[i * 4 + 1], 4);
        std::memcpy(&gpu_energy, &bits[i * 4 + 2], 4);
        worst_flat = std::max(worst_flat, std::fabs(flat_energy - plain_energy) /
                                              std::max(plain_energy, 1e-12f));
        // Against the even fog's light, not the drifting one's: at contrast 2 a ray can run
        // through holes (m = 0) almost all the way, and a tiny energy makes a relative error
        // meaningless.
        const float cpu_energy = CpuMarch(c);
        worst_march = std::max(worst_march, std::fabs(gpu_energy - cpu_energy) /
                                                std::max({cpu_energy, plain_energy, 1e-12f}));
    }
    std::printf("wind-noise-test: %u points against bbport_wind.h: Noise3 %.2g, Field %.2g, "
                "Density %.2g, Density through the view to world rows %.2g, the world point %.2g "
                "m, the view shade %.2g at most; contrast 0 gave exactly 1 at %u of %u; the ray "
                "step at a contrast of 0 read at run time is %.2g (relative) from the march "
                "without wind, the same bits at %u of %u; with the noise it is %.2g (of the even "
                "fog's light) from MarchStep\n",
                count, double(worst_noise), double(worst_field), double(worst_density),
                double(worst_rows), double(worst_world), double(worst_shade), flat_exact,
                flat_cases, double(worst_flat), same_bits, count, double(worst_march));
    // Noise3 takes the coordinates as they are: 1e-6. Field divides them first, and Vulkan lets a
    // GPU's division be 2.5 ulp off (a driver may also multiply by a reciprocal), so at |p| up to
    // 300 m and offsets up to 256 cells the cell coordinate's last bits (up to 3e-5 cells) can
    // differ from the C++ division: 1e-4. Density: 2 times the largest contrast times that. The
    // world point: |p| and the translation up to 300 m each, a few float ulps of 600 m (the GPU
    // may fuse the dot product's multiply-adds): 1e-3 m. The pins above, nearer the origin,
    // hold 1e-6.
    const float density_tolerance = 2.0f * BbWind::MaxContrast * 1e-4f;
    Expect(worst_noise <= 1e-6f, "the GPU Noise3 is the C++ Noise3 within 1e-6");
    Expect(worst_field <= 1e-4f && worst_density <= density_tolerance,
           "the GPU Field and Density are the C++ ones within 1e-4 and 2 MaxContrast 1e-4");
    Expect(worst_rows <= density_tolerance,
           "the GPU factor through the rows is Density(ViewToWorld) within 2 MaxContrast 1e-4");
    Expect(worst_world <= 1e-3f, "the GPU view to world point is ViewToWorld's within 1e-3 m");
    Expect(worst_shade <= 1e-6f, "the GPU view shade is ViewShade within 1e-6");
    Expect(flat_exact == flat_cases, "contrast 0 gives exactly 1 on the GPU");
    Expect(worst_flat <= 1e-6f,
           "at a run-time contrast of 0 the GPU ray step is the plain march within 1e-6");
    Expect(worst_march <= 1e-4f,
           "the GPU march with the noise is MarchStep's within 1e-4 of the even fog's light");
    if (failures) {
        std::printf("wind-noise-test: %d failure(s)\n", failures);
        return 1;
    }
    std::printf("wind-noise-test: ok\n");
    return 0;
}
''',
}

EDITS = {
    H + "volumetric_light.comp": [
        (r'''#version 450
#extension GL_EXT_scalar_block_layout : require
''', r'''#version 450
#extension GL_EXT_scalar_block_layout : require
#ifdef WIND
#extension GL_GOOGLE_include_directive : require
#endif
'''),
        (r'''
};

#ifdef REPAIR
#define GROUP
''', r'''
#ifdef WIND
    // bbport (r82_wind-stage1): BB_WIND=1 only (VolumetricLight::WindParams; the words above are
    // the plain Params): the view to world matrix (3x4 rows) of the G-buffer pass's camera as it
    // was at the Integrate call, and the fog noise's offsets in cells (wind_off1.w = contrast,
    // wind_off2.w = 1 for the BB_WIND_VIEW=1 test view).
    vec4 wind_row0, wind_row1, wind_row2;
    vec4 wind_off1, wind_off2;
#endif
};

#ifdef REPAIR
#define GROUP
'''),
        (r'''GROUP uint shared_valid;
''', r'''GROUP uint shared_valid;
#ifdef WIND
#include "wind_noise.glsl"

// bbport (r82_wind-stage1): the fog density factor m at view space point v: wind_factor_rows
// (tested by wind-noise-test) with this pass's rows, offsets and contrast.
float wind_factor(vec3 v) {
    return wind_factor_rows(wind_row0, wind_row1, wind_row2, v, wind_off1.xyz, wind_off2.xyz,
                            wind_off1.w);
}
#endif
'''),
        (r'''    bool sky = depth == 1.0;
''', r'''    bool sky = depth == 1.0;
#ifdef WIND
    // bbport (r82_wind-stage1): BB_WIND_VIEW=1: the view shade of m on the surface instead of fog
    // (0 on the sky), grey in the WIND_VIEW composite. Before the strength and sun tests, so it
    // shows also at a volumetric intensity of 0 or without a sun direction. With BB_WIND_SPEED=0
    // it must stay on the walls while the camera turns: that proves the matrix taken at the
    // Integrate call.
    if (wind_off2.w != 0.0) {
        vec4 at = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, depth, 1.0);
        float shade = 0.0;
        if (depth > 0.0 && depth < 1.0 && abs(at.w) >= 1e-8) {
            shade = wind_view_shade(wind_factor(at.xyz / at.w), wind_off1.w);
        }
        imageStore(fog_out, px, vec4(vec3(shade), 1.0 - depth));
        return;
    }
#endif
'''),
        (r'''    local_splits = shared_splits;
''', r'''    local_splits = shared_splits;
#ifdef WIND
    // bbport (r82_wind-stage1): the fog's density is density * m along the ray, m at ray * t
    // (wind_ray_step), taken only where the sample is lit (BbWind::MarchLitStep): a sample in
    // shadow adds no light and its stretch dims the light behind it at the mean density. At m = 1
    // the step is the plain line within float rounding. Samples the gate skips (r76) count as m = 1.
    float excess = 0.0;
#endif
'''),
        (r'''        energy += exp(-density * t) * density * ds * v;
''', r'''#ifdef WIND
        if (v > 0.0) {
            wind_ray_step(energy, excess, density, ray, t, ds, jitter, v, wind_row0, wind_row1,
                          wind_row2, wind_off1.xyz, wind_off2.xyz, wind_off1.w);
        }
#else
        energy += exp(-density * t) * density * ds * v;
#endif
'''),
        (r'''        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
''', r'''#ifdef WIND
        float vis = visibility(ray * t, texel);
        if (vis > 0.0) {
            wind_ray_step(energy, excess, density, ray, t, ds, jitter, vis, wind_row0, wind_row1,
                          wind_row2, wind_off1.xyz, wind_off2.xyz, wind_off1.w);
        }
#else
        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
#endif
'''),
        (r'''    vec4 color = imageLoad(scene, px);
''', r'''    vec4 color = imageLoad(scene, px);
#ifdef WIND_VIEW
    // bbport (r82_wind-stage1): BB_WIND_VIEW=1: the fog image holds the view shade of m (0-1),
    // shown as linear grey 0-0.5 in place of the HDR scene (no tint, no lamp fog).
    imageStore(scene, px, vec4(vec3(0.5 * scattering.r), color.a));
    return;
#endif
'''),
    ],
    R + "vk_volumetric_light.h": [
        (r'''    void SetCamera(const LampFog::Camera& camera) { fog_camera = camera; }
''', r'''    void SetCamera(const LampFog::Camera& camera) { fog_camera = camera; }
    /// bbport (r82_wind-stage1): BB_WIND=1 only, right before Integrate: the fog noise's offsets
    /// (cells, BbWind::Snapshot) and the camera's view to world matrix (3x4 rows) at that call.
    /// The next Integrate marches with the drifting density; without a camera, the plain way.
    /// `show`: BB_WIND_SHOW=1 (read once by the rasterizer) for the "Wind fog:" line.
    void SetWind(const std::array<float, 3>& off1, const std::array<float, 3>& off2,
                 const std::array<float, 12>& view_to_world, bool camera_valid, bool show);
'''),
        (r'''    void SayLight();
''', r'''    void SayLight();
    // bbport (r82_wind-stage1): makes the WIND builds once (the gated ones at the first gated
    // march that drifts); false: the march stays plain. WindFogCheck: the BB_WIND_SHOW=1 line.
    bool WindPasses(bool gated);
    void WindFogCheck();
'''),
        (r'''    bool ready = false;
    bool tinted = false;
''', r'''    // bbport (r82_wind-stage1): the WIND builds of the march (plain and gated), the view
    // composite (BB_WIND_VIEW=1), and the drift's state: the next Integrate's input (SetWind: on,
    // the matrix, the offsets with the contrast and the view flag in [3]), whether the last
    // Integrate drifted (used), and the counts of the BB_WIND_SHOW=1 line (WindFogCheck).
    Pass integrate_wind, repair_wind, integrate_gated_wind, repair_gated_wind, composite_wind_view;
    struct WindFog {
        bool wanted = false, on = false, used = false, show = false;
        bool tried = false, failed = false, gate_tried = false, gate_failed = false;
        std::array<float, 12> view_to_world{};
        std::array<float, 4> off1{}, off2{};
        u32 frames = 0, no_camera = 0, compared = 0;
        float gap = 0.0f;
        std::chrono::steady_clock::time_point next_line{};
    } wind_fog;
    bool ready = false;
    bool tinted = false;
'''),
    ],
    R + "vk_volumetric_light.cpp": [
        (r'''#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
''', r'''#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
// bbport (r82_wind-stage1): the shared wind's knobs and the march's WIND builds (BB_WIND=1 only)
#include <cstddef>
#include "bbport_wind.h"
#include "video_core/host_shaders/volumetric_light_integrate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
'''),
        (r'''static_assert(sizeof(Params) == 32);
''', r'''static_assert(sizeof(Params) == 32);
// bbport (r82_wind-stage1): the push constants of the WIND builds (BB_WIND=1 only): Params as it
// is, then the camera's view to world matrix at the Integrate call (3x4 rows) and the noise
// offsets in cells (off1[3] = contrast, off2[3] = 1 for the BB_WIND_VIEW=1 view).
// volumetric_light.comp reads them as five vec4 after the plain words, so the tail must start at
// a multiple of 16 bytes. Vulkan guarantees 128 bytes of push constants.
struct WindParams {
    Params head;
    std::array<float, 12> view_to_world;
    std::array<float, 4> off1, off2;
};
static_assert(sizeof(Params) % 16 == 0, "the WIND tail's vec4 start at a multiple of 16");
static_assert(offsetof(WindParams, view_to_world) == sizeof(Params) &&
              offsetof(WindParams, off1) == sizeof(Params) + 48 &&
              offsetof(WindParams, off2) == sizeof(Params) + 64 &&
              sizeof(WindParams) == sizeof(Params) + 80);
static_assert(sizeof(WindParams) <= 128, "Vulkan guarantees 128 bytes of push constants");

// bbport (r82_wind-stage1): the drift's knobs, read once at the first SetWind (so only with
// BB_WIND=1), which logs them once: BB_WIND_FOG the contrast (BbWind::SanitizeContrast:
// 0-MaxContrast; missing or not a number: BbWind::DefaultContrast), BB_WIND_VIEW=1 the test
// view. BB_WIND_SHOW comes with SetWind (the rasterizer reads it once for both wind lines).
struct WindKnobs {
    float contrast;
    bool view;
};

const WindKnobs& WindFogKnobs() {
    static const WindKnobs knobs = [] {
        const char* fog = std::getenv("BB_WIND_FOG");
        float contrast = BbWind::DefaultContrast;
        if (fog != nullptr && fog[0] != 0) {
            char* end = nullptr;
            const float value = std::strtof(fog, &end);
            contrast = end != fog ? value : BbWind::DefaultContrast;
        }
        const char* view = std::getenv("BB_WIND_VIEW");
        return WindKnobs{BbWind::SanitizeContrast(contrast), view != nullptr && view[0] == '1'};
    }();
    return knobs;
}
'''),
        (r'''    const bool viewing = diag && view_knob && EnsureGateView();
    view_drawn = viewing;
''', r'''    const bool viewing = diag && view_knob && EnsureGateView();
    view_drawn = viewing;
    // bbport (r82_wind-stage1): with BB_WIND=1 and a camera at this call (SetWind, for this call
    // only) the WIND builds march (made here the first time); otherwise the plain ones, which get
    // the same 32 bytes as before. A march the gate view draws (BB_VOLUMETRIC_GATE_VIEW=1) does
    // not drift.
    const bool wind_wanted = std::exchange(wind_fog.on, false);
    const bool drift = wind_wanted && !viewing && WindPasses(gated);
    wind_fog.used = drift;
    const WindParams wind_push{params, wind_fog.view_to_world, wind_fog.off1, wind_fog.off2};
    const u32 push_size = drift ? u32(sizeof(WindParams)) : u32(sizeof(Params));
'''),
        (r'''        const auto& pass = repairing ? (gated ? repair_gated : repair)
                                     : (gated ? (viewing ? integrate_gated_view : integrate_gated)
                                              : integrate);
''', r'''        const auto& plain_pass = repairing ? (gated ? repair_gated : repair)
                                           : (gated ? (viewing ? integrate_gated_view : integrate_gated)
                                                    : integrate);
        // bbport (r82_wind-stage1): the WIND build of the same pass while the fog drifts
        const auto& pass = !drift      ? plain_pass
                           : repairing ? (gated ? repair_gated_wind : repair_wind)
                                       : (gated ? integrate_gated_wind : integrate_wind);
'''),
        (r'''        [params, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
''', r'''        [wind_push, push_size, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
'''),
        (r'''                                    std::span{writes.data(), count});
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
''', r'''                                    std::span{writes.data(), count});
            // bbport (r82_wind-stage1): Params (32 bytes) or, drifting, WindParams (its head is Params)
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, push_size, &wind_push);
'''),
        (r'''void VolumetricLight::Scene(VideoCore::ImageId color) {
''', r'''// bbport (r82_wind-stage1): the wind for the next Integrate (BB_WIND=1 only): the fog noise's
// offsets in cells and the G-buffer pass's view to world matrix as CameraMotion::PassMatrices
// gives it at this call. Without a camera that Integrate marches the plain way; counted. `show`
// is BB_WIND_SHOW (read once, by Rasterizer's WindShow). The first call logs the knobs.
void VolumetricLight::SetWind(const std::array<float, 3>& off1, const std::array<float, 3>& off2,
                              const std::array<float, 12>& view_to_world, bool camera_valid,
                              bool show) {
    const WindKnobs& knobs = WindFogKnobs();
    if (!wind_fog.wanted) {
        std::printf("Wind fog (r82, BB_WIND=1): the sun fog drifts with the wind while the "
                    "volumetric sunlight is on; contrast %.2f (BB_WIND_FOG), view %d "
                    "(BB_WIND_VIEW), show %d (BB_WIND_SHOW)\n",
                    double(knobs.contrast), knobs.view ? 1 : 0, show ? 1 : 0);
    }
    wind_fog.wanted = true;
    wind_fog.show = show;
    wind_fog.on = camera_valid && !wind_fog.failed;
    if (!camera_valid) {
        ++wind_fog.no_camera;
        return;
    }
    wind_fog.view_to_world = view_to_world;
    wind_fog.off1 = {off1[0], off1[1], off1[2], knobs.contrast};
    wind_fog.off2 = {off2[0], off2[1], off2[2], knobs.view ? 1.0f : 0.0f};
}

// bbport (r82_wind-stage1): the WIND builds, made at the first Integrate that drifts (the gated
// two at the first gated one), so a game without BB_WIND=1 never makes them. If the plain two
// cannot be made the sun fog stays as without wind; if the gated two cannot, gated marches do.
bool VolumetricLight::WindPasses(bool gated) {
    using enum vk::DescriptorType;
    if (!wind_fog.tried) {
        wind_fog.tried = true;
        const bool made =
            CreatePass(integrate_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage},
                       VOLUMETRIC_LIGHT_INTEGRATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric integrate (wind)") &&
            CreatePass(repair_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},
                       VOLUMETRIC_LIGHT_REPAIR_WIND_COMP, sizeof(WindParams),
                       "Volumetric repair (wind)") &&
            (!WindFogKnobs().view ||
             CreatePass(composite_wind_view,
                        {eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                         eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
                        VOLUMETRIC_LIGHT_WIND_VIEW_COMP, sizeof(u32),
                        "Volumetric composite (wind view)"));
        wind_fog.failed = !made;
        std::printf(made ? "Wind fog (r82): drift builds made\n"
                         : "Wind fog (r82): the drift builds could not be made; the sun fog "
                           "marches as without wind\n");
    }
    if (wind_fog.failed) {
        return false;
    }
    if (gated && !wind_fog.gate_tried) {
        wind_fog.gate_tried = true;
        const bool made =
            CreatePass(integrate_gated_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_INTEGRATE_GATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric integrate (gate, wind)") &&
            CreatePass(repair_gated_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_REPAIR_GATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric repair (gate, wind)");
        wind_fog.gate_failed = !made;
        std::printf(made ? "Wind fog (r82): gated drift builds made\n"
                         : "Wind fog (r82): the gated drift builds could not be made; gated "
                           "marches do not drift\n");
    }
    return !gated || !wind_fog.gate_failed;
}

// bbport (r82_wind-stage1): with BB_WIND=1, at each composite: counts the frames that drifted and
// keeps the largest difference between the view to world matrix the march used (taken at
// Integrate) and the one SetCamera gave the composite (0: the G-buffer pass's camera did not
// change in between). With BB_WIND_SHOW=1 it prints them every 2 s and starts the counts again.
void VolumetricLight::WindFogCheck() {
    if (!wind_fog.wanted) {
        return;
    }
    if (wind_fog.used) {
        ++wind_fog.frames;
        if (fog_camera.valid) {
            ++wind_fog.compared;
            for (u32 i = 0; i < 12; ++i) {
                const float gap = std::abs(fog_camera.view_to_world[i] - wind_fog.view_to_world[i]);
                wind_fog.gap = std::max(wind_fog.gap, gap);
            }
        }
    }
    if (!wind_fog.show) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    if (now < wind_fog.next_line) {
        return;
    }
    if (wind_fog.next_line != std::chrono::steady_clock::time_point{}) {
        std::printf("Wind fog: %u frames drifted, %u marched without a camera (no drift), camera "
                    "at the march against at the composite: largest difference %.6f over %u "
                    "frames\n",
                    wind_fog.frames, wind_fog.no_camera, double(wind_fog.gap), wind_fog.compared);
    }
    wind_fog.next_line = now + std::chrono::seconds(2);
    wind_fog.frames = wind_fog.no_camera = wind_fog.compared = 0;
    wind_fog.gap = 0.0f;
}

void VolumetricLight::Scene(VideoCore::ImageId color) {
'''),
        (r'''    if (!has_result || !Enabled() || !color_id) return;
''', r'''    if (!has_result || !Enabled() || !color_id) return;
    WindFogCheck(); // bbport (r82_wind-stage1): returns at once without BB_WIND=1
'''),
        (r'''    EffectPass::Mark(11, "volumetric composite");
''', r'''    // bbport (r82_wind-stage1): BB_WIND_VIEW=1 shows the density factor this frame's march wrote
    const bool wind_view = !gate_viewed && wind_fog.used && WindFogKnobs().view;
    EffectPass::Mark(11, "volumetric composite");
'''),
        (r'''         pipeline = gate_viewed ? *composite_view.pipeline : *composite.pipeline,
         layout = gate_viewed ? *composite_view.layout : *composite.layout](vk::CommandBuffer cmd) {
''', r'''         pipeline = gate_viewed ? *composite_view.pipeline
                    : wind_view ? *composite_wind_view.pipeline // bbport (r82_wind-stage1)
                                : *composite.pipeline,
         layout = gate_viewed ? *composite_view.layout
                  : wind_view ? *composite_wind_view.layout
                              : *composite.layout](vk::CommandBuffer cmd) {
'''),
    ],
    R + "vk_rasterizer.h": [
        (r'''#include "engine/batch.h"
''', r'''#include "engine/batch.h"
#include "bbport_wind.h" // bbport (r82_wind-stage1)
'''),
        (r'''    void EffectsOnFrameEnd();
''', r'''    void EffectsOnFrameEnd();
    void WindOnFrameEnd(); ///< bbport (r82_wind-stage1): first in EffectsOnFrameEnd
'''),
        (r'''    std::unique_ptr<VolumetricLight> volumetric_light;
''', r'''    std::unique_ptr<VolumetricLight> volumetric_light;
    /// bbport (r82_wind-stage1): the shared wind (bbport_wind.h) and the steady clock at its
    /// last advance (zero: not advanced yet); both change only with BB_WIND=1 (WindOnFrameEnd).
    BbWind::State wind;
    std::chrono::steady_clock::time_point wind_time{};
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''void Rasterizer::EffectsOnFrameEnd() {
''', r'''// bbport (r82_wind-stage1): BB_WIND_SHOW=1, read once at the first call: the "Wind:" line and
// the sun fog's "Wind fog:" line. Both callers sit behind the wind's on, so it is read only with
// BB_WIND=1.
static bool WindShow() {
    static const bool show = [] {
        const char* env = std::getenv("BB_WIND_SHOW");
        return env != nullptr && env[0] == '1';
    }();
    return show;
}

// bbport (r82_wind-stage1): the shared wind (bbport_wind.h), advanced by the steady clock each
// time EffectsOnFrameEnd runs (the display pass, while camera_motion->Enabled(): not with
// BB_UPSCALER=none unless BB_DEBUG_MOTION=1), only with BB_WIND=1. The environment is read once,
// at the first call, and its state said once (on or off): BB_WIND (on when it starts with 1),
// BB_WIND_DIR (deg, 0 = +x, 90 = +z, the way it blows toward), BB_WIND_SPEED (m/s) and
// BB_WIND_GUSTS; a missing, unreadable or non-finite number takes BbWind::DefaultDirection /
// DefaultSpeed / DefaultGusts, then BbWind::Sanitize applies the clamps (MaxSpeed, MaxGusts).
// With BB_WIND on, BB_WIND_SHOW (1: a "Wind:" line each time the wind time passes a multiple of
// 2 s) is read too. Without BB_WIND this returns after the static parameters' initialisation guard
// and one bool test: no clock read, the state stays as constructed. The sun fog reads the wind
// right before each Integrate (EffectsAfterDraw). The wind time is real time (steps clamped to
// 0.1 s), so it also runs in pause menus.
void Rasterizer::WindOnFrameEnd() {
    static const BbWind::Params params = [] {
        const auto number = [](const char* name, float fallback) {
            const char* env = std::getenv(name);
            if (env == nullptr || env[0] == 0) {
                return fallback;
            }
            char* end = nullptr;
            const float value = std::strtof(env, &end);
            return end != env && std::isfinite(value) ? value : fallback;
        };
        const char* on = std::getenv("BB_WIND");
        BbWind::Params p{
            .on = on != nullptr && on[0] == '1',
            .direction_deg = number("BB_WIND_DIR", BbWind::DefaultDirection),
            .speed = number("BB_WIND_SPEED", BbWind::DefaultSpeed),
            .gusts = number("BB_WIND_GUSTS", BbWind::DefaultGusts),
        };
        p = BbWind::Sanitize(p);
        if (p.on) {
            BbReport::Printf("Wind (r82, BB_WIND=1): toward %.0f deg, %.2f m/s, gusts %.2f; the "
                             "sun fog drifts with it while the volumetric sunlight is on\n",
                             double(p.direction_deg), double(p.speed), double(p.gusts));
        } else {
            BbReport::Printf("Wind (r82): off (BB_WIND is not 1); nothing drifts\n");
        }
        return p;
    }();
    if (!params.on) {
        return;
    }
    const bool show = WindShow();
    const auto now = std::chrono::steady_clock::now();
    const double seconds = wind_time == std::chrono::steady_clock::time_point{}
                               ? 0.0
                               : std::chrono::duration<double>(now - wind_time).count();
    wind_time = now;
    const double before = wind.Get().time;
    wind.Advance(params, seconds);
    const BbWind::Snapshot s = wind.Get();
    if (show && std::floor(s.time / 2.0) != std::floor(before / 2.0)) {
        BbReport::Printf("Wind: toward %.0f deg (x %.2f z %.2f), %.2f m/s, gust %.2f, offsets %.2f %.2f "
                         "%.2f / %.2f %.2f %.2f\n",
                         double(s.direction_deg), double(s.dir_x), double(s.dir_z), double(s.speed),
                         double(s.gust), double(s.off1[0]), double(s.off1[1]), double(s.off1[2]),
                         double(s.off2[0]), double(s.off2[1]), double(s.off2[2]));
    }
}

void Rasterizer::EffectsOnFrameEnd() {
    WindOnFrameEnd(); // bbport (r82_wind-stage1): BB_WIND=1 only
'''),
        (r'''        volumetric_light->Integrate(cb_descs[0].first, dc.image_infos[0],
''', r'''        // bbport (r82_wind-stage1): with BB_WIND=1 the march drifts with the wind. The view to
        // world matrix is the G-buffer pass's camera as it stands at this call, not at the
        // composite.
        if (const BbWind::Snapshot w = wind.Get(); w.on) {
            const auto camera = camera_motion->PassMatrices();
            volumetric_light->SetWind(w.off1, w.off2, camera.inv_view, camera.valid, WindShow());
        }
        volumetric_light->Integrate(cb_descs[0].first, dc.image_infos[0],
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''    if (FILENAME MATCHES "^paint_")
''', r'''    # bbport (r82_wind-stage1): the WIND builds and the noise test include the fog noise.
    if (FILENAME MATCHES "^volumetric_light|^wind_noise")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl)
    endif()
    if (FILENAME MATCHES "^paint_")
'''),
        (r'''add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
''', r'''add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
# bbport (r82_wind-stage1): BB_WIND=1 only (made at the first march that drifts): the sun fog
# march with a density drifting with the wind, plain and reading the gate, the BB_WIND_VIEW=1
# composite, and the shader of wind-noise-test.
add_host_shader(volumetric_light.comp volumetric_light_integrate_wind_comp INTEGRATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_wind_comp REPAIR=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_wind_comp INTEGRATE=1 GATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_wind_comp REPAIR=1 GATE=1 WIND=1)
add_host_shader(volumetric_light.comp volumetric_light_wind_view_comp COMPOSITE=1 WIND_VIEW=1)
add_host_shader(wind_noise_test.comp wind_noise_test_comp)
'''),
        (r'''target_include_directories(lamp-fog-lights-test PRIVATE ..)
''', r'''target_include_directories(lamp-fog-lights-test PRIVATE ..)
# bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise and march step
# (shim/bbport_wind.h; wind-noise-test checks the GLSL copy); also built and run by
# engine/build.sh --test.
add_executable(wind-test EXCLUDE_FROM_ALL ../tests/test_wind.cpp)
target_compile_options(wind-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-test PRIVATE ..)
'''),
        (r'''        "point-volumetric-test;test_point_volumetric.cpp"
''', r'''        "point-volumetric-test;test_point_volumetric.cpp"
        "wind-noise-test;test_wind_noise.cpp"
'''),
        (r'''target_include_directories(rt-shadow-test PRIVATE ..)
''', r'''target_include_directories(rt-shadow-test PRIVATE ..)
# bbport (r82_wind-stage1): wind-noise-test compares the GPU with gpu/shim/bbport_wind.h
target_include_directories(wind-noise-test PRIVATE ..)
'''),
    ],
    "engine/build.sh": [
        (r'''    out/frame-gen-cap-test
''', r'''    out/frame-gen-cap-test
    # bbport (r82_wind-stage1): the shared wind state, the fog noise and the march step
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind.cpp -o out/wind-test
    out/wind-test
'''),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        (r'''#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
''', r'''#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
// bbport (r82_wind-stage1): the BB_WIND=1 builds
#include "video_core/host_shaders/volumetric_light_integrate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
'''),
        (r'''         POINT_VOLUMETRIC_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
''', r'''         POINT_VOLUMETRIC_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
        // bbport (r82_wind-stage1): as VolumetricLight::WindPasses makes them (WindParams: 112
        // bytes); the gated two have the gate builds' bindings
        {"volumetric integrate (wind)",
         VOLUMETRIC_LIGHT_INTEGRATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         112},
        {"volumetric repair (wind)",
         VOLUMETRIC_LIGHT_REPAIR_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         112},
        {"volumetric integrate (gate, wind)",
         VOLUMETRIC_LIGHT_INTEGRATE_GATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
         112},
        {"volumetric repair (gate, wind)",
         VOLUMETRIC_LIGHT_REPAIR_GATE_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
          eCombinedImageSampler},
         112},
        {"volumetric composite (wind view)",
         VOLUMETRIC_LIGHT_WIND_VIEW_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
          eCombinedImageSampler, eCombinedImageSampler},
         4},
'''),
    ],
    "README.md": [
        (r'''
## Sponsors
''', r'''
### Wind (in development)

One shared wind for the engine's own effects; its first user is the sun fog (`effect_volumetric_light`), which then drifts in patches. Off unless `BB_WIND=1`. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing and are part of no look; no ini key yet.

| Variable | What it does | Default |
|---|---|---|
| `BB_WIND` | `1` turns the wind on. It advances by real time at each display pass while the camera is tracked (so not with `BB_UPSCALER=none`, unless `BB_DEBUG_MOTION=1`), also in pause menus: a direction that wanders up to 15 degrees either way over minutes, a mean speed, and gusts that scale the speed by a factor kept between 0.3 and 2. The sun fog's density is multiplied by m = max(0, 1 + C (2 N - 1)), N in [0, 1) being 0.65 of a noise 12 m across and 6 m tall plus 0.35 of a 4.5 m noise, the first carried at the wind's speed times the gust factor and the second 1.6 times as fast; the fog's extinction follows the same density. The noise is taken only where a fog sample is lit (a sample in shadow adds no light and dims the light behind it at the mean density). The lamp fog does not drift yet. Cost: an estimate of 0.15 to 0.3 ms at 1080p internal, about four times that at 2160p internal, not measured; read it on the `Lighting: volumetric sunlight` row of `BB_GPU_PROFILE=1` | off |
| `BB_WIND_DIR` | Direction the wind blows toward, degrees: 0 is world +x, 90 is +z | `225` |
| `BB_WIND_SPEED` | Mean speed, 0 to 4 m/s (the fog patches move at up to 2 times that with gusts, the fine ones 1.6 times faster still) | `1.5` |
| `BB_WIND_GUSTS` | Gusts, 0 (steady) to 1 | `0.5` |
| `BB_WIND_FOG` | Contrast C of the fog patches, 0 (an even fog) to 2; at 2 the fog has holes where N < 0.25 | `1` |
| `BB_WIND_VIEW` | Debug only: `1` shows m on the surfaces in grey in place of the picture, stretched from 1 - C (black) to 1 + C (grey 0.5), the sky black, from the camera the sunlight pass used; with `BB_WIND_SPEED=0` the pattern must stay fixed on walls and ground while the camera turns. It needs the volumetric sunlight on (any intensity); a march the gate view (`BB_VOLUMETRIC_GATE_VIEW=1`) draws does not drift | off |
| `BB_WIND_SHOW` | Debug only: `1` prints a `Wind:` line every 2 s of wind time (direction, speed, gust, noise offsets) and a `Wind fog:` line every 2 s (frames that drifted, frames without a camera, the largest difference between the camera matrix the sunlight pass used and the one the composite gets) | off |

## Sponsors
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "volumetric_light.comp": [("#ifdef WIND\n", 7), ("#ifdef WIND_VIEW", 1),
                                  ("wind_ray_step(", 2), ("float excess = 0.0;", 1),
                                  ('#include "wind_noise.glsl"', 1),
                                  ("energy += exp(-density * t) * density * ds * v;", 1),
                                  ("energy += exp(-density * t) * density * ds * visibility(ray * t, texel);", 1),
                                  ("vec4 wind_row0, wind_row1, wind_row2;", 1),
                                  ("    vec4 wind_off1, wind_off2;\n#endif\n};\n", 1)],
    R + "vk_volumetric_light.cpp": [("VOLUMETRIC_LIGHT_INTEGRATE_WIND_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_REPAIR_WIND_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_INTEGRATE_GATE_WIND_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_REPAIR_GATE_WIND_COMP", 1),
                                    ("VOLUMETRIC_LIGHT_WIND_VIEW_COMP", 1),
                                    ("push_size, &wind_push", 1),
                                    ('std::getenv("BB_WIND_FOG")', 1), ('std::getenv("BB_WIND_VIEW")', 1),
                                    ('std::getenv("BB_WIND', 2),
                                    ("WindFogCheck(); // bbport (r82_wind-stage1)", 1),
                                    ("const bool drift = wind_wanted && !viewing && WindPasses(gated);", 1),
                                    ("pipeline = *pass.pipeline, layout = *pass.layout](vk::CommandBuffer cmd) {", 1)],
    R + "vk_rasterizer_effects.cpp": [('std::getenv("BB_WIND', 2), ("WindOnFrameEnd(); // bbport", 1),
                                      ("volumetric_light->SetWind(", 1),
                                      ("Wind (r82): off (BB_WIND is not 1)", 1)],
    "engine/gpu/CMakeLists.txt": [(" WIND=1)", 4), (" WIND_VIEW=1)", 1), ("wind_noise_test_comp", 1),
                                  ('"wind-noise-test;test_wind_noise.cpp"', 1),
                                  ("add_executable(wind-test", 1)],
    "engine/build.sh": [("tests/test_wind.cpp -o out/wind-test", 1)],
    "engine/tests/test_effect_pipelines.cpp": [("_WIND_COMP,", 4), ("VOLUMETRIC_LIGHT_WIND_VIEW_COMP,", 1)],
    "README.md": [("| `BB_WIND` |", 1), ("| `BB_WIND_FOG` |", 1), ("| `BB_WIND_VIEW` |", 1),
                  ("| `BB_WIND_SHOW` |", 1), ("| `BB_WIND_DIR` | Direction", 1),
                  ("| `BB_WIND_SPEED` | Mean speed, 0 to 4 m/s", 1), ("| `BB_WIND_GUSTS` | Gusts, 0 (steady) to 1 | `0.5` |", 1),
                  ("| `BB_WIND_FOG` | Contrast C of the fog patches, 0 (an even fog) to 2;", 1)],
}

# README numbers tied to the header's constants (rule 10: defaults written twice).
TIES = [("DefaultDirection = 225.0f", "| `BB_WIND_DIR` |", "| `225` |"),
        ("DefaultSpeed = 1.5f", "| `BB_WIND_SPEED` |", "| `1.5` |"),
        ("DefaultGusts = 0.5f", "| `BB_WIND_GUSTS` |", "| `0.5` |"),
        ("DefaultContrast = 1.0f", "| `BB_WIND_FOG` |", "| `1` |"),
        ("MaxSpeed = 4.0f, MaxGusts = 1.0f, MaxContrast = 2.0f", "| `BB_WIND_SPEED` |", "0 to 4 m/s")]

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    H + "volumetric_light.comp": ["uint cascades;", "vec4 wind_off1, wind_off2;", "#define GROUP",
                                  "GROUP uint shared_valid;", '#include "wind_noise.glsl"',
                                  "bool sky = depth == 1.0;", "if (wind_off2.w != 0.0)",
                                  "if (shared_valid == 0u ||", "float excess = 0.0;",
                                  "float shut_to = GateShutTo", "wind_ray_step(", "wind_ray_step("],
    R + "vk_volumetric_light.cpp": ["const bool viewing =", "const bool drift =", "RecordGate(in,",
                                    "const auto& plain_pass", "const auto& pass = !drift",
                                    "[wind_push, push_size,", "push_size, &wind_push"],
    R + "vk_rasterizer_effects.cpp": ["void Rasterizer::WindOnFrameEnd()", "void Rasterizer::EffectsOnFrameEnd() {\n    WindOnFrameEnd();",
                                      "volumetric_light->SetWind(", "volumetric_light->Integrate(cb_descs[0].first"],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")

def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    header = NEW["engine/gpu/shim/bbport_wind.h"]
    for const, row, value in TIES:
        line = [l for l in texts["README.md"].split("\n") if l.startswith(row)]
        if header.count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R82_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full): state = "clean"
        elif open(full, "rb").read() == new_bytes(text): state = "applied"
        else: raise SystemExit("%s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in edited:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r82tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r82tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in edited:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")

main()
