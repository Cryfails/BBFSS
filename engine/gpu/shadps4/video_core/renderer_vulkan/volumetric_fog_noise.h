// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r94_fog-noise): FEATURE. The sun fog's world anchored noise (BB_FOG_NOISE): its knobs,
// the shaping of the density factor m, the octaves' drift with the wind, and the push words of
// volumetric_light.comp's NOISE builds. Pure: no Vulkan, no settings, no environment
// (vk_volumetric_fog_noise.cpp reads the variables once and passes their text to MakeKnobs). The
// numbers the shader shares are host_shaders/fog_noise_layout.h's. Tested by
// tests/test_volumetric_fog_noise.cpp.
//
// The noise N_k of octave k (0 the largest, 2 the finest) is value noise in [0, 1) on a lattice of
// FOG_NOISE_PERIOD cells a side (host_shaders/fog_noise.glsl), read at LatticePoint(world point, k,
// scale) minus the octave's offset (Drift::Cells). d = the sum of Weight[k] (N_k - 0.5), the
// finest octave faded out between FineFrom and FineTo scales from the camera. m = Factor(d,
// Amplitude(s), Gain(s)) = 1 + a clamp(2 g d, -1, 1): odd in d around 1, and d is symmetric around
// 0 (the corner values are uniform in [0, 1) and the interpolation is linear in them), so the mean
// of m over the world is 1 at every strength. The march multiplies a lit sample's in-scattered
// light by m and keeps the extinction at the mean density, so the fog's mean light stays the
// plain march's (a CPU probe of 2500 rays of 32 steps over 40 m: 1.00 +- 0.01 at strength 1 and 3).
//
// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 swaps that shaping for banks of fog with
// clearer air between them (BankFactor); MakeTail marks it with a gain below 0.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdlib>

#include "../host_shaders/fog_noise_layout.h"

namespace VolumetricFogNoise {

inline constexpr float MaxStrength = 2.0f;        ///< BB_FOG_NOISE's clamp
inline constexpr float ShowStrength = 3.0f;       ///< BB_FOG_NOISE_SHOW=1: past that clamp
inline constexpr float SuggestedStrength = 1.0f;  ///< the README's value for a first look
inline constexpr float DefaultScale = 10.0f;      ///< m: BB_FOG_NOISE_SCALE, the largest cell
inline constexpr float MinScale = 2.0f, MaxScale = 100.0f; ///< BB_FOG_NOISE_SCALE's clamp
/// g at strength 1 and below. With it, at strength 1, m has a spread (sd) of 0.5 and 5% of the
/// samples sit at the clamp (0 or 2); a 40 m ray's fog light varies by 25% (sd), a 6 m sun shaft's
/// by 45% (CPU probe).
inline constexpr float BaseGain = 2.0f;
inline constexpr double MaxStep = 1.0;            ///< s of wind time one Drift::Advance takes at most
inline constexpr double Period = FOG_NOISE_PERIOD; ///< cells after which the lattice repeats
/// The NOISE builds' push constants: the plain Params (32 bytes), then Tail. Vulkan guarantees 128.
inline constexpr unsigned PushBytes = 128;

inline constexpr std::array<float, 3> Ratio{float(FOG_NOISE_RATIO0), float(FOG_NOISE_RATIO1),
                                            float(FOG_NOISE_RATIO2)};
inline constexpr std::array<float, 3> Weight{float(FOG_NOISE_WEIGHT0), float(FOG_NOISE_WEIGHT1),
                                             float(FOG_NOISE_WEIGHT2)};
inline constexpr std::array<float, 3> YawCos{float(FOG_NOISE_YAW_COS0), float(FOG_NOISE_YAW_COS1),
                                             float(FOG_NOISE_YAW_COS2)};
inline constexpr std::array<float, 3> YawSin{float(FOG_NOISE_YAW_SIN0), float(FOG_NOISE_YAW_SIN1),
                                             float(FOG_NOISE_YAW_SIN2)};
inline constexpr float Squash = float(FOG_NOISE_SQUASH);
inline constexpr float FineFrom = float(FOG_NOISE_FINE_FROM), FineTo = float(FOG_NOISE_FINE_TO);
/// How fast each octave's offset moves, in wind speeds: the largest patches travel exactly with the
/// wind, the finer swirls 1.3 and 1.7 times as fast, so they change while the patches pass.
inline constexpr std::array<float, 3> Speed{1.0f, 1.3f, 1.7f};
/// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1, the banks look (fog_noise_layout.h): w =
/// smoothstep(BankFrom, BankTo, d), m = BankClear(s) + BankGain(s) w (BankFactor), so about a third
/// of space holds banks (m 2.51 in a bank's core at strength 1) and the clear air between them has
/// m = BankClearShare (0.15); the mean of m over the world is 1, w's mean being BankMean. The banks
/// are BankSquash times wider than tall and, unless BB_FOG_NOISE_SCALE says otherwise, BankScale m
/// across. A CPU probe of a graveyard-like view (six places, every sample lit) gave the fog
/// light of the upper half of the picture a spread (sd) of 0.36 of its mean (0.15 with r94's
/// look at strength 1), and a pixel's fog light changed by 0.50 of the mean in 6 s of 1.5 m/s
/// wind (0.21).
inline constexpr float BankFrom = float(FOG_NOISE_BANK_FROM), BankTo = float(FOG_NOISE_BANK_TO);
inline constexpr float BankMean = float(FOG_NOISE_BANK_MEAN);
inline constexpr float BankClearShare = float(FOG_NOISE_BANK_CLEAR);
inline constexpr float BankSquash = float(FOG_NOISE_BANK_SQUASH);
inline constexpr float BankScale = 14.0f; ///< m: BB_FOG_NOISE_SCALE's default with the banks look

/// The value of `text` when it starts with a finite number (strtof), else `fallback` (also for a
/// missing or empty text).
inline float Number(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

/// BB_FOG_NOISE: 0 (off) when missing, empty, not a number or not finite; else clamped to
/// 0-MaxStrength.
inline float ParseStrength(const char* text) {
    return std::clamp(Number(text, 0.0f), 0.0f, MaxStrength);
}

/// BB_FOG_NOISE_SCALE (m): DefaultScale when missing, empty, not a number or not finite; else
/// clamped to MinScale-MaxScale.
inline float ParseScale(const char* text) {
    return std::clamp(Number(text, DefaultScale), MinScale, MaxScale);
}

struct Knobs {
    float strength = 0.0f; ///< 0: off
    float scale = DefaultScale;
    bool show = false;
    bool banks = false; ///< bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1
    bool On() const {
        return strength > 0.0f;
    }
};

/// The knobs from the variables' text (null: not set). BB_FOG_NOISE_SHOW starting with 1 turns the
/// noise on at ShowStrength whatever BB_FOG_NOISE says.
inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show) {
    Knobs knobs;
    knobs.show = show != nullptr && show[0] == '1';
    knobs.strength = knobs.show ? ShowStrength : ParseStrength(strength);
    knobs.scale = ParseScale(scale);
    return knobs;
}

/// bbport (r94b_fog-noise-visible): the knobs with BB_FOG_NOISE_BANKS's text too (null: not set).
/// Starting with 1 it turns the banks look on (it acts only while the noise is on) and the scale
/// then defaults to BankScale; anything else leaves the knobs exactly as the three-text MakeKnobs
/// makes them (r94's look).
inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show,
                       const char* banks) {
    Knobs knobs = MakeKnobs(strength, scale, show);
    knobs.banks = banks != nullptr && banks[0] == '1';
    if (knobs.banks) {
        knobs.scale = std::clamp(Number(scale, BankScale), MinScale, MaxScale);
    }
    return knobs;
}

/// The shaping's amplitude a = min(s, 1) for strength s: m stays within 0-2.
inline float Amplitude(float strength) {
    return std::clamp(strength, 0.0f, 1.0f);
}

/// The shaping's gain g = BaseGain max(s, 1): above strength 1 the patches get harder edges (more
/// samples at 0 or 2) instead of a wider range, which would need a clamp at 0 that moves the mean.
inline float Gain(float strength) {
    return BaseGain * std::max(strength, 1.0f);
}

/// m from d: 1 + a clamp(2 g d, -1, 1) (fog_noise.glsl's fog_noise_m, last line). Odd in d around
/// 1: Factor(d) + Factor(-d) = 2.
inline float Factor(float d, float amplitude, float gain) {
    return 1.0f + amplitude * std::clamp(2.0f * gain * d, -1.0f, 1.0f);
}

/// bbport (r94b_fog-noise-visible): the banks look's m of the clear air (w = 0) at strength s:
/// 1 - a (1 - BankClearShare), a = Amplitude(s), so strengths above 1 count as 1.
inline float BankClear(float strength) {
    return 1.0f - Amplitude(strength) * (1.0f - BankClearShare);
}

/// The banks look's gain B = a (1 - BankClearShare) / BankMean: the mean of m is then 1.
inline float BankGain(float strength) {
    return Amplitude(strength) * (1.0f - BankClearShare) / BankMean;
}

/// m of the banks look from d: clear + gain smoothstep(BankFrom, BankTo, d) (fog_noise.glsl's
/// banks line).
inline float BankFactor(float d, float clear, float gain) {
    const float t = std::clamp((d - BankFrom) / (BankTo - BankFrom), 0.0f, 1.0f);
    return clear + gain * (t * t * (3.0f - 2.0f * t));
}

/// The lattice point of world point p (m) for an octave (fog_noise.glsl: fog_noise_cells of the
/// world point times 1 / scale, y also times Squash), before the octave's offset is taken off.
inline std::array<float, 3> LatticePoint(const std::array<float, 3>& p, std::size_t octave,
                                         float scale) {
    const float inv = 1.0f / scale;
    const float qx = p[0] * inv, qy = p[1] * Squash * inv, qz = p[2] * inv;
    const float c = YawCos[octave], s = YawSin[octave], r = Ratio[octave];
    return {(c * qx - s * qz) / r, qy / r, (s * qx + c * qz) / r};
}

/// v wrapped into [0, Period).
inline double WrapCells(double v) {
    double r = std::fmod(v, Period);
    if (r < 0.0) {
        r += Period;
    }
    return r >= Period ? 0.0 : r;
}

/// The three octaves' offsets in lattice cells. Advance moves them by the wind's velocity (m/s;
/// the r82 wind snapshot's `wind`, gusts included) times the wind time passed since the last call
/// with the wind on (clamped to 0-MaxStep s; the first such call only takes the time), turned and
/// scaled as LatticePoint turns and scales a world point and times Speed[k]: the noise read at
/// world point p + Speed[k] w T after T seconds is the one read at p before, so the pattern travels
/// with the wind. Without the wind nothing moves: the noise stands still in the world. Summed in
/// double and wrapped into [0, Period) after every step (the lattice repeats there).
class Drift {
public:
    void Advance(bool wind_on, double wind_time, const std::array<float, 3>& wind, float scale) {
        if (!wind_on || !std::isfinite(wind_time)) {
            return;
        }
        if (!started) {
            started = true;
            time = wind_time;
            return;
        }
        const double dt = std::clamp(wind_time - time, 0.0, MaxStep);
        time = wind_time;
        if (!std::isfinite(wind[0]) || !std::isfinite(wind[1]) || !std::isfinite(wind[2]) ||
            !(scale > 0.0f)) {
            return;
        }
        const double inv = 1.0 / double(scale);
        const double mx = double(wind[0]) * dt * inv;
        const double my = double(wind[1]) * dt * double(Squash) * inv;
        const double mz = double(wind[2]) * dt * inv;
        for (std::size_t k = 0; k < 3; ++k) {
            const double c = YawCos[k], s = YawSin[k];
            const double f = double(Speed[k]) / double(Ratio[k]);
            cells[k][0] = WrapCells(cells[k][0] + (c * mx - s * mz) * f);
            cells[k][1] = WrapCells(cells[k][1] + my * f);
            cells[k][2] = WrapCells(cells[k][2] + (s * mx + c * mz) * f);
        }
    }

    /// The octave's offset as floats in [0, Period).
    std::array<float, 3> Cells(std::size_t octave) const {
        return {ToFloat(cells[octave][0]), ToFloat(cells[octave][1]), ToFloat(cells[octave][2])};
    }

private:
    /// A wrapped double as a float in [0, Period) (a value just under Period would round up to it).
    static float ToFloat(double v) {
        const float f = float(v);
        return f >= float(Period) ? 0.0f : f;
    }

    std::array<std::array<double, 3>, 3> cells{};
    double time = 0.0;
    bool started = false;
};

/// The NOISE builds' push words after the plain Params (volumetric_light.comp: noise_row0-2,
/// noise_off0-2; six vec4 starting at byte 32).
struct Tail {
    std::array<float, 12> view_to_world{}; ///< 3x4 rows, translation in [3], [7], [11]
    std::array<float, 4> off0{}, off1{}, off2{}; ///< xyz: the octave's offset; w: a, g, 1 / scale
};
static_assert(sizeof(Tail) == 96 && 32 + sizeof(Tail) == PushBytes,
              "six vec4 after the 32 bytes of Params");

/// The tail for a march: the camera's rows, the drift's offsets, the knobs' amplitude, gain and
/// 1 / scale.
inline Tail MakeTail(const std::array<float, 12>& rows, const Drift& drift, const Knobs& knobs) {
    Tail tail;
    tail.view_to_world = rows;
    const std::array<float, 3> c0 = drift.Cells(0), c1 = drift.Cells(1), c2 = drift.Cells(2);
    tail.off0 = {c0[0], c0[1], c0[2], Amplitude(knobs.strength)};
    tail.off1 = {c1[0], c1[1], c1[2], Gain(knobs.strength)};
    tail.off2 = {c2[0], c2[1], c2[2], 1.0f / knobs.scale};
    // bbport (r94b_fog-noise-visible): the banks look: w of off0 is the clear air's m, w of off1
    // minus the gain (below 0: the shader's mark of the look), and the up row of the matrix (row 1)
    // is times BankSquash / Squash, so the shader's up times Squash comes out times BankSquash. The
    // wind has no up part, so the drift's offsets need nothing.
    if (knobs.banks) {
        tail.off0[3] = BankClear(knobs.strength);
        tail.off1[3] = -BankGain(knobs.strength);
        for (std::size_t i = 4; i < 8; ++i) {
            tail.view_to_world[i] *= BankSquash / Squash;
        }
    }
    return tail;
}

} // namespace VolumetricFogNoise
