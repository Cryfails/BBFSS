// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r107_caustics): water caustics from the sun or moon: the moving net of light that water
// reflects onto the walls and undersides beside it, where the game's sun shadow says the water is
// lit. The pass (vk_caustics.cpp, host_shaders/caustics.comp) runs at the first blended draw
// after the opaque scene, in frames whose G-buffer passes are the world and its mirror image in a
// water plane (the game's planar reflection: the sewers, Gascoigne's arena). This header holds
// the knob, the push words, the pattern's drift and a C++ twin of the shader's pattern; no Vulkan
// here: tests/test_caustics.cpp builds it alone.
//
// Knobs (environment, read once at the rasterizer's start; Parse):
//   BB_CAUSTICS         unset, empty, 0, a negative number or text: off (nothing is made);
//                       1: on; a number above 0: the strength (above MaxStrength counts as it);
//                       "show": the test view at strength 1 (ShowGain times the pattern, tints)
//   BB_CAUSTICS_LAMPS   bbport (r107b_caustics-visible): the lamps' caustics, as BB_CAUSTICS reads
//                       its text (show: the test view at strength 1); on without BB_CAUSTICS too.
//                       r107d: above 1 the lamps' light stays at 1 and the rest is the look
//                       (LookOf; caustics_layout.h CAUSTICS_LOOK_MAX)
//
// A receiver's colour is multiplied by 1 + Gain * strength * w * (c - 1), c the pattern (mean 1),
// w its weight (caustics.comp): light moved, not added. The lamps' caustics add light (LampGain).
// bbport (r107c_caustics-lamp-gain): a lamp adds its own direct light at the reflected path's
// length and angle times the water's share LampShare (below 1; caustics_layout.h).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "../host_shaders/caustics_layout.h"

namespace BbCaustics {

inline constexpr float MaxStrength = 4.0f;
/// The pattern's share at weight 1 and strength 1.
inline constexpr float Gain = 0.3f;
/// The test view: the pattern this many times as strong (tints as caustics.comp says).
inline constexpr float ShowGain = 3.0f;
/// The sun or moon must stand this high (the y of its unit direction) to light the water.
inline constexpr float MinSunY = 0.02f;
/// The pattern's drift without wind (m/s, world x and z), layer 1 and layer 2, and the share of
/// the wind's velocity (BB_WIND) each layer takes on top: at the wind's default 1.5 m/s about
/// 0.22 and 0.15 m/s, near the speed of small ripples and a pixel or two a frame on a wall a few
/// metres away (the pattern has no motion vectors: faster drift trails under the upscaler).
inline constexpr std::array<float, 2> Drift1{0.05f, 0.02f}, Drift2{-0.03f, 0.04f};
inline constexpr float WindShare1 = 0.15f, WindShare2 = 0.1f;
/// The longest step one Advance takes (s): a hitch does not jump the pattern.
inline constexpr double MaxStep = 0.1;

/// The shader's numbers (caustics_layout.h), named.
inline constexpr std::uint32_t FlagShow = CAUSTICS_FLAG_SHOW, FlagPlane = CAUSTICS_FLAG_PLANE,
                               FlagMaterial = CAUSTICS_FLAG_MATERIAL;
inline constexpr std::uint32_t SlotWords = CAUSTICS_SLOT_WORDS, Slots = CAUSTICS_SLOTS;
inline constexpr std::uint32_t Group = CAUSTICS_GROUP;
inline constexpr float Lambda1 = CAUSTICS_LAMBDA1, Lambda2 = CAUSTICS_LAMBDA2;
inline constexpr float Sharp = CAUSTICS_SHARP, PatternMean = CAUSTICS_PATTERN_MEAN;
inline constexpr float Evolve = CAUSTICS_EVOLVE;
static_assert(FlagShow == 1u && FlagPlane == 2u && FlagMaterial == 4u);
static_assert(SlotWords == 168u && Slots >= 4u && Group == 8u); // r107d: 32, r107e: 168 (was 16)
// r107e: the workgroup's 64 threads clear and add its words in turns (caustics.comp main).
static_assert(CAUSTICS_MIN_HEIGHT < CAUSTICS_MAX_HEIGHT && CAUSTICS_FADE_START < CAUSTICS_FADE_END);
// bbport (r107b_caustics-visible): the lamps and the data blocks after the counters.
inline constexpr std::uint32_t FlagLamps = CAUSTICS_FLAG_LAMPS, FlagRecords = CAUSTICS_FLAG_RECORDS,
                               FlagAlbedo = CAUSTICS_FLAG_ALBEDO;
inline constexpr std::uint32_t DataWords = CAUSTICS_DATA_WORDS, MaxLamps = CAUSTICS_MAX_LAMPS;
inline constexpr std::uint32_t LampWords = CAUSTICS_LAMP_WORDS;
/// The lamps' light at strength 1 (caustics_layout.h CAUSTICS_LAMP_GAIN).
inline constexpr float LampGain = CAUSTICS_LAMP_GAIN;
static_assert(FlagLamps == 8u && FlagRecords == 16u && FlagAlbedo == 32u);
static_assert(CAUSTICS_DATA_LAMPS + MaxLamps * LampWords <= DataWords && CAUSTICS_DATA_GAIN < CAUSTICS_DATA_LAMPS);
static_assert(CAUSTICS_W_LAMP_RATIO < CAUSTICS_SLOT_WORDS && CAUSTICS_DATA_COUNT >= 8);
// bbport (r107c_caustics-lamp-gain): the new counter and data words fit; a pixel adds at most 1024
// to a sum.
static_assert(CAUSTICS_W_LAMP_UNSEEN < CAUSTICS_SLOT_WORDS && CAUSTICS_W_LAMP_MODEL < CAUSTICS_SLOT_WORDS);
static_assert(CAUSTICS_DATA_CORE2 > CAUSTICS_DATA_GAIN && CAUSTICS_DATA_ENERGY < CAUSTICS_DATA_LAMPS);
static_assert(CAUSTICS_RATIO_MAX * CAUSTICS_RATIO_SCALE <= 1024.0 &&
              CAUSTICS_MODEL_MAX * CAUSTICS_MODEL_SCALE <= 1024.0);
// bbport (r107d_caustics-lamp-look): the bins and the look's words fit after word 15.
static_assert(CAUSTICS_W_BIN_COUNT > CAUSTICS_W_LAMP_MODEL &&
              CAUSTICS_W_BIN_RATIO == CAUSTICS_W_BIN_COUNT + CAUSTICS_BINS &&
              CAUSTICS_W_LOOK == CAUSTICS_W_BIN_RATIO + CAUSTICS_BINS && CAUSTICS_W_LOOK < CAUSTICS_SLOT_WORDS);
static_assert(CAUSTICS_DATA_LOOK > CAUSTICS_DATA_ENERGY && CAUSTICS_DATA_LOOK < CAUSTICS_DATA_LAMPS);
inline constexpr std::uint32_t Bins = CAUSTICS_BINS;
// bbport (r107e_caustics-puddles): the puddle words fit; the heights' bins span the range.
static_assert(CAUSTICS_W_PUDDLE_GROUND > CAUSTICS_W_LOOK && CAUSTICS_W_PUDDLE_WET < CAUSTICS_W_HEIGHTS &&
              CAUSTICS_W_HEIGHTS + CAUSTICS_HEIGHT_BINS == CAUSTICS_SLOT_WORDS);
static_assert(CAUSTICS_FLAG_PUDDLE == 64u && CAUSTICS_FLAG_PUDDLE_PLANE == 128u);
inline constexpr std::uint32_t FlagPuddle = CAUSTICS_FLAG_PUDDLE, FlagPuddlePlane = CAUSTICS_FLAG_PUDDLE_PLANE;
inline constexpr std::uint32_t HeightBins = CAUSTICS_HEIGHT_BINS;
// bbport (r107f_caustics-world-anchored): the world map's words, flag and counters fit; the cells
// wrap by a mask (a power of two). A new plane starts at WorldKeep m from the last; a lamp chosen in
// the last pass is found again within LampKeepRadius m and counts LampKeepBonus times.
static_assert(CAUSTICS_FLAG_WORLD == 256u && CAUSTICS_W_BED > CAUSTICS_W_PUDDLE_WET &&
              CAUSTICS_W_BED_PUDDLE < CAUSTICS_W_HEIGHTS && CAUSTICS_W_MAP_RESCUED_DRY < CAUSTICS_W_BED_PUDDLE);
static_assert(CAUSTICS_DATA_WORLD_GEN > CAUSTICS_DATA_LOOK && CAUSTICS_DATA_BED < CAUSTICS_DATA_LAMPS);
static_assert(CAUSTICS_MAP_WORDS == CAUSTICS_MAP_SIZE * CAUSTICS_MAP_SIZE &&
              (CAUSTICS_MAP_SIZE & (CAUSTICS_MAP_SIZE - 1)) == 0);
inline constexpr std::uint32_t FlagWorld = CAUSTICS_FLAG_WORLD, MapWords = CAUSTICS_MAP_WORDS;
inline constexpr float WorldKeep = 0.08f, LampKeepRadius = 0.15f, LampKeepBonus = 1.6f;
/// The puddle plane (EstimatePuddle): at least PuddleMinShare of the scene's pixels and
/// PuddleMinPixels are candidates; PuddleNear of them lie within 2 bins (8 cm) of the most crowded
/// 3 bins; a later estimate within PuddleKeep m keeps the plane (and its check). The plane is
/// refused while more than PuddleMaxWet of the up-facing pixels on it (at least PuddleMinGround)
/// are candidates: a glossy dry floor, not puddles. Puddles only after PuddleQuietCalls calls
/// without a mirrored water pass (the first pass of a mirrored frame finds no plane either).
inline constexpr float PuddleMinShare = 1e-4f, PuddleNear = 0.5f, PuddleKeep = 0.08f, PuddleMaxWet = 0.6f;
inline constexpr std::uint32_t PuddleMinPixels = 64, PuddleMinGround = 400, PuddleQuietCalls = 16;

struct PuddleEstimate {
    bool found = false;
    float height = 0.0f;         ///< world y of the plane
    std::uint32_t candidates = 0; ///< in all the bins
    std::uint32_t near = 0;       ///< within 2 bins of the most crowded 3
};

/// The puddle plane from a dispatch's height bins (`bins`: HeightBins counts, bin i from
/// CAUSTICS_HEIGHT_RANGE - i x CAUSTICS_HEIGHT_STEP below `camera_y`), `pixels` the scene's size:
/// the count-weighted centre of the most crowded 3 bins (the first of equals), when enough
/// candidates are there.
inline PuddleEstimate EstimatePuddle(const std::uint32_t* bins, float camera_y, std::uint32_t pixels) {
    PuddleEstimate e;
    std::uint32_t best = 0, at = 0;
    for (std::uint32_t i = 0; i < HeightBins; ++i) {
        e.candidates += bins[i];
        const std::uint32_t three = bins[i] + (i > 0 ? bins[i - 1] : 0u) + (i + 1 < HeightBins ? bins[i + 1] : 0u);
        if (three > best) {
            best = three;
            at = i;
        }
    }
    double weight = 0.0, sum = 0.0;
    for (std::uint32_t i = at > 1 ? at - 2 : 0; i <= std::min(at + 2, HeightBins - 1); ++i) {
        e.near += bins[i];
        if (i + 1 >= at && i <= at + 1) {
            weight += double(bins[i]);
            sum += double(bins[i]) * (double(i) + 0.5);
        }
    }
    const float need = std::max(float(PuddleMinPixels), PuddleMinShare * float(pixels));
    e.found = best > 0 && float(e.candidates) >= need && float(e.near) >= PuddleNear * float(e.candidates);
    e.height = camera_y - float(CAUSTICS_HEIGHT_RANGE) +
               float(weight > 0.0 ? sum / weight : 0.0) * float(CAUSTICS_HEIGHT_STEP);
    return e;
}

/// The guard: the up-facing pixels on the plane (`ground`) and the candidates among them (`wet`)
/// say puddles, not a glossy dry floor.
inline bool PuddlesNotFloor(std::uint32_t ground, std::uint32_t wet) {
    return ground >= PuddleMinGround && float(wet) <= PuddleMaxWet * float(ground);
}

struct Knobs {
    float strength = 0.0f; ///< 0: off
    bool show = false;
    bool unreadable = false;  ///< BB_CAUSTICS was set to text that is not a number nor "show"
    float lamp_strength = 0.0f;    ///< BB_CAUSTICS_LAMPS (r107b); 0: off
    bool lamps_unreadable = false; ///< BB_CAUSTICS_LAMPS was set to text that is not a number nor "show"
    float world = 0.0f;            ///< BB_CAUSTICS_WORLD (r107f); 0: off
};

/// One knob's text: unset or empty is 0; "show" is 1 and the test view; a number above 0 is the
/// strength (at most MaxStrength); 0, a negative number is 0; other text is 0 and unreadable.
inline float ParseOne(const char* text, bool& show, bool& unreadable) {
    if (text == nullptr || text[0] == 0) {
        return 0.0f;
    }
    if (std::strcmp(text, "show") == 0) {
        show = true;
        return 1.0f;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    if (end == text || end == nullptr || *end != 0 || !std::isfinite(v)) {
        unreadable = true;
        return 0.0f;
    }
    return v > 0.0f ? std::min(v, MaxStrength) : 0.0f;
}

inline Knobs Parse(const char* caustics, const char* lamps) {
    Knobs k;
    k.strength = ParseOne(caustics, k.show, k.unreadable);
    k.lamp_strength = ParseOne(lamps, k.show, k.lamps_unreadable);
    return k;
}

/// bbport (r107f_caustics-world-anchored): BB_CAUSTICS_WORLD: a number above 0 (at most MaxStrength);
/// unset, empty, 0, negative or other text is 0 (off). "show" is 1 (it has no test view of its own).
inline float WorldOf(const char* text) {
    bool show = false, unreadable = false;
    return ParseOne(text, show, unreadable);
}

/// The push words of caustics.comp, field for field.
struct Push {
    std::array<float, 4> proj{};      ///< x scale, y scale, z scale, z offset
    std::array<float, 4> frame{};     ///< width, height, jitter x, jitter y (pixels)
    std::array<float, 12> inv_view{}; ///< view to world, 3x4 rows
    std::array<float, 4> sun{};       ///< toward the sun or moon (world, unit); the plane's world y
    std::array<float, 4> drift{};     ///< layer 1 offset x, z; layer 2 offset x, z (m)
    float gain = 0.0f;
    float evolve = 0.0f; ///< the pattern's time axis, cells
    std::uint32_t flags = 0;
    std::uint32_t slot = 0;
};
static_assert(sizeof(Push) == 128);

/// The gain the shader takes: Gain x strength, x ShowGain in the test view.
inline float GainOf(const Knobs& k) {
    return Gain * k.strength * (k.show ? ShowGain : 1.0f);
}

/// bbport (r107b_caustics-visible): the lamps' gain: LampGain x lamp strength, x ShowGain in the
/// test view. r107d: the strength counts up to 1 (above it: LookOf).
inline float LampGainOf(const Knobs& k) {
    return LampGain * std::min(k.lamp_strength, 1.0f) * (k.show ? ShowGain : 1.0f);
}

/// bbport (r107d_caustics-lamp-look): the look's amount: 0 up to lamp strength 1, then
/// CAUSTICS_LOOK_MAX x (strength - 1) / (MaxStrength - 1).
inline float LookOf(const Knobs& k) {
    return float(CAUSTICS_LOOK_MAX) * std::clamp((k.lamp_strength - 1.0f) / (MaxStrength - 1.0f), 0.0f, 1.0f);
}

/// bbport (r107d_caustics-lamp-look): the bin of the lamps' modelled light (luminance) the shader
/// counts a pixel in: below 2^-10 bin 0, then 2 stops a bin, 1 and above the last.
inline std::uint32_t BinOf(float light) {
    const int bin = int(std::floor(0.5f * std::log2(std::max(light, 1e-30f)))) + 6;
    return std::uint32_t(std::clamp(bin, 0, int(Bins) - 1));
}

/// bbport (r107b_caustics-visible): a lamp the pass lights the water with: world position, reach
/// (m), colour (r107c: as drawn; only its ranking limits it as the lamp fog does: past 4 only the
/// hue counts).
struct Lamp {
    std::array<float, 3> world{};
    float reach = 0.0f;
    std::array<float, 3> colour{};
    float importance = 0.0f;
};

/// The lamps of a frame's light grid records (16 words each: view position x, y, z, inverse reach
/// squared, colour r, g, b, ...; lamp_fog_lights.h) that light the water plane at `plane_y`: above
/// it by CAUSTICS_LAMP_MIN_HEIGHT to less than their reach. At most MaxLamps of them, the ones
/// that count most first (luminance x (1 - height / reach)^2 x reach / (reach + distance to the
/// camera); ties: the earlier record). `view_to_world`: the pass camera's 3x4 rows.
/// bbport (r107f_caustics-world-anchored): `keep` (null: none) the lamps of the last pass (`keep_count`
/// of them): a lamp within LampKeepRadius m of one of them counts LampKeepBonus times.
inline std::uint32_t ChooseLamps(const std::uint32_t* records, std::size_t count,
                                 const std::array<float, 12>& view_to_world, float plane_y,
                                 std::array<Lamp, MaxLamps>& out,
                                 const std::array<Lamp, MaxLamps>* keep = nullptr,
                                 std::uint32_t keep_count = 0) {
    const auto& m = view_to_world;
    std::uint32_t n = 0;
    for (std::size_t i = 0; i < count; ++i) {
        const std::uint32_t* r = records + i * 16;
        float w[7];
        bool finite = true;
        for (int j = 0; j < 7; ++j) {
            std::memcpy(&w[j], &r[j], sizeof(float));
            finite = finite && std::isfinite(w[j]);
        }
        if (!finite || !(w[3] > 0.0f)) {
            continue;
        }
        Lamp lamp;
        lamp.world = {m[0] * w[0] + m[1] * w[1] + m[2] * w[2] + m[3],
                      m[4] * w[0] + m[5] * w[1] + m[6] * w[2] + m[7],
                      m[8] * w[0] + m[9] * w[1] + m[10] * w[2] + m[11]};
        lamp.reach = 1.0f / std::sqrt(w[3]);
        const float height = lamp.world[1] - plane_y;
        if (!(height >= float(CAUSTICS_LAMP_MIN_HEIGHT)) || !(height < lamp.reach) ||
            !std::isfinite(lamp.reach)) {
            continue;
        }
        const float top = std::max({w[4], w[5], w[6], 0.0f});
        const float over = std::max(1.0f, top / 4.0f);
        lamp.colour = {std::max(w[4], 0.0f), std::max(w[5], 0.0f), std::max(w[6], 0.0f)};
        const float luminance =
            (0.2126f * lamp.colour[0] + 0.7152f * lamp.colour[1] + 0.0722f * lamp.colour[2]) / over;
        const float dx = lamp.world[0] - m[3], dy = lamp.world[1] - m[7], dz = lamp.world[2] - m[11];
        const float share = 1.0f - height / lamp.reach;
        lamp.importance = luminance * share * share * lamp.reach /
                          (lamp.reach + std::sqrt(dx * dx + dy * dy + dz * dz));
        for (std::uint32_t j = 0; keep != nullptr && j < keep_count && j < MaxLamps; ++j) {
            const auto& old = (*keep)[j];
            const float kx = lamp.world[0] - old.world[0], ky = lamp.world[1] - old.world[1],
                        kz = lamp.world[2] - old.world[2];
            if (kx * kx + ky * ky + kz * kz < LampKeepRadius * LampKeepRadius) {
                lamp.importance *= LampKeepBonus; // r107f
                break;
            }
        }
        if (!(lamp.importance > 0.0f)) {
            continue;
        }
        // Insert by importance (stable: an equal one goes after those already in).
        std::uint32_t at = n;
        while (at > 0 && out[at - 1].importance < lamp.importance) {
            --at;
        }
        if (at >= MaxLamps) {
            continue;
        }
        for (std::uint32_t k = std::min<std::uint32_t>(n, MaxLamps - 1); k > at; --k) {
            out[k] = out[k - 1];
        }
        out[at] = lamp;
        n = std::min<std::uint32_t>(n + 1, MaxLamps);
    }
    return n;
}

/// bbport (r107b_caustics-visible): the C++ twin of the shader's water reflectance (Schlick,
/// CAUSTICS_WATER_F0 at normal incidence; `cosine` of the angle to the vertical).
inline float Reflectance(float cosine) {
    const float c = std::clamp(cosine, 0.0f, 1.0f);
    return float(CAUSTICS_WATER_F0) + (1.0f - float(CAUSTICS_WATER_F0)) * std::pow(1.0f - c, 5.0f);
}

/// bbport (r107c_caustics-lamp-gain): the C++ twins of the shader's lamp curve (x = d / reach,
/// below 1; `core2` < 0: (1 - x)^2, else `energy` x (1 / (x^2 + core2) - 1 / (1 + core2))) and of
/// the water's share of a lamp's own light, 1 - exp(-gain x reflectance x pattern): below 1 (in
/// floats at most 1).
inline float LampCurve(float x, float core2, float energy) {
    if (core2 < 0.0f) {
        return (1.0f - x) * (1.0f - x);
    }
    return energy * std::max(1.0f / std::max(x * x + core2, 1e-6f) - 1.0f / (1.0f + core2), 0.0f);
}

inline float LampShare(float gain, float reflectance, float pattern) {
    return 1.0f - std::exp(-gain * reflectance * pattern);
}

/// A direction toward the sun or moon the pass can use: finite, unit after scaling, above the
/// horizon by MinSunY. `out` gets the unit direction.
inline bool SunUsable(const std::array<float, 3>& toward, std::array<float, 3>& out) {
    const float len = std::sqrt(toward[0] * toward[0] + toward[1] * toward[1] + toward[2] * toward[2]);
    if (!std::isfinite(len) || !(len > 1e-6f)) {
        return false;
    }
    out = {toward[0] / len, toward[1] / len, toward[2] / len};
    return out[1] > MinSunY;
}

/// The pattern's drift and time, advanced by real seconds (clamped to MaxStep).
struct Drift {
    std::array<double, 4> off{}; ///< layer 1 x, z; layer 2 x, z (m)
    double time = 0.0;           ///< s
    void Advance(double seconds, const std::array<float, 3>& wind) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        const auto finite = [](float v) { return std::isfinite(v) ? double(v) : 0.0; };
        const double wx = finite(wind[0]), wz = finite(wind[2]);
        off[0] += (Drift1[0] + WindShare1 * wx) * dt;
        off[1] += (Drift1[1] + WindShare1 * wz) * dt;
        off[2] += (Drift2[0] + WindShare2 * wx) * dt;
        off[3] += (Drift2[1] + WindShare2 * wz) * dt;
        // Layer 1 repeats every 1024 cells (the hash's period): kept small for the floats.
        const double period = 1024.0 * double(Lambda1);
        off[0] = std::fmod(off[0], period);
        off[1] = std::fmod(off[1], period);
        time += dt;
    }
    /// The time axis in cells, wrapped at the hash's period of 1024 (layer 2's axis jumps once
    /// then: every 1024 / Evolve s, about 57 minutes).
    [[nodiscard]] float EvolveCells() const {
        return float(std::fmod(time * double(Evolve), 1024.0));
    }
    [[nodiscard]] std::array<float, 4> Offsets() const {
        return {float(off[0]), float(off[1]), float(off[2]), float(off[3])};
    }
};

// The shader's pattern on the CPU (caustics.comp Hash, Corner, Noise, Ridge, Pattern), for the
// test: its mean is 1 and the GLSL copy has fixed values to match.
inline std::uint32_t Hash(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
    x = x * 1664525u + 1013904223u;
    y = y * 1664525u + 1013904223u;
    z = z * 1664525u + 1013904223u;
    x += y * z;
    y += z * x;
    z += x * y;
    x ^= x >> 16u;
    y ^= y >> 16u;
    z ^= z >> 16u;
    x += y * z;
    return x;
}

inline float Corner(std::int32_t x, std::int32_t y, std::int32_t z) {
    return float(Hash(std::uint32_t(x & 1023), std::uint32_t(y & 1023), std::uint32_t(z & 1023)) >> 8u) *
           (1.0f / 16777216.0f);
}

inline float Noise(float px, float py, float pz) {
    const float fx = std::floor(px), fy = std::floor(py), fz = std::floor(pz);
    const auto ix = std::int32_t(fx), iy = std::int32_t(fy), iz = std::int32_t(fz);
    const auto fade = [](float u) { return u * u * u * (u * (u * 6.0f - 15.0f) + 10.0f); };
    const float sx = fade(px - fx), sy = fade(py - fy), sz = fade(pz - fz);
    const auto lerp = [](float a, float b, float t) { return a + (b - a) * t; };
    const float x00 = lerp(Corner(ix, iy, iz), Corner(ix + 1, iy, iz), sx);
    const float x10 = lerp(Corner(ix, iy + 1, iz), Corner(ix + 1, iy + 1, iz), sx);
    const float x01 = lerp(Corner(ix, iy, iz + 1), Corner(ix + 1, iy, iz + 1), sx);
    const float x11 = lerp(Corner(ix, iy + 1, iz + 1), Corner(ix + 1, iy + 1, iz + 1), sx);
    return lerp(lerp(x00, x10, sy), lerp(x01, x11, sy), sz);
}

inline float Ridge(float px, float py, float pz) {
    return 1.0f - std::fabs(2.0f * Noise(px, py, pz) - 1.0f);
}

inline float Pattern(float x, float z, const std::array<float, 4>& drift, float evolve) {
    const float ax = (x + drift[0]) / Lambda1, az = (z + drift[1]) / Lambda1;
    const float mx = x + drift[2], mz = z + drift[3];
    const float bx = (float(CAUSTICS_COS2) * mx - float(CAUSTICS_SIN2) * mz) / Lambda2;
    const float bz = (float(CAUSTICS_SIN2) * mx + float(CAUSTICS_COS2) * mz) / Lambda2;
    const float r1 = Ridge(ax, az, evolve);
    const float r2 = Ridge(bx, bz, evolve * float(CAUSTICS_EVOLVE2) + float(CAUSTICS_EVOLVE2_SHIFT));
    return 0.5f * (std::pow(r1, Sharp) + std::pow(r2, Sharp)) / PatternMean;
}

} // namespace BbCaustics
