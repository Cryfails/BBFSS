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
#include <chrono>
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

/// bbport (r128b_lrt-caustics-water): a lantern.ini strength (graphics_water_caustics_sun_strength,
/// graphics_water_caustics_lamps_strength) as a knob strength: not finite or not above 0 is 0, above
/// MaxStrength is MaxStrength.
inline float SettingOf(float setting) {
    return std::isfinite(setting) && setting > 0.0f ? std::min(setting, MaxStrength) : 0.0f;
}

/// bbport (r128b_lrt-caustics-water): the knobs the renderer runs with. `env` is what Parse and WorldOf
/// read from the variables once. A channel whose variable is set and not empty (`sun_env`: BB_CAUSTICS,
/// `lamps_env`: BB_CAUSTICS_LAMPS) keeps the environment's strength, also 0 or unreadable text: the
/// variable decides, as BB_HEAT_HAZE does; else the channel's strength is the setting's (SettingOf).
/// The test view (`show`), `unreadable` and the world map stay the environment's.
inline Knobs WithSettings(const Knobs& env, bool sun_env, bool lamps_env, float sun_setting,
                          float lamps_setting) {
    Knobs k = env;
    if (!sun_env) {
        k.strength = SettingOf(sun_setting);
    }
    if (!lamps_env) {
        k.lamp_strength = SettingOf(lamps_setting);
    }
    return k;
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

// bbport (r130b_water-moves): the moving water (BB_WATER_MOTION, graphics_water_motion_strength). One wave field on the water plane,
// world anchored: 4 travelling waves (heading from the wind, else a slow flow) and rings from the hunter's steps and landings. The
// host keeps its state (the phases summed in double) and writes it to the slot's motion block (WriteBlock); caustics.comp WaveAt
// reads it: it bends and focuses every pattern lookup (mean 1: light is moved, not added) and shimmers the water pixels. Off
// (strength 0): FlagsOf is 0, so no flag, no block, no hunter read, no update. Eval is the C++ twin of WaveAt (in double), for the test.
namespace Motion {

inline constexpr double Pi = 3.14159265358979323846;
inline constexpr std::uint32_t FlagMotion = CAUSTICS_FLAG_MOTION;
inline constexpr std::uint32_t Waves = CAUSTICS_MOTION_WAVES, MaxRings = CAUSTICS_MOTION_MAX_RINGS;
inline constexpr std::uint32_t Words = CAUSTICS_MOTION_WORDS, Base = CAUSTICS_MOTION_BASE;
static_assert(FlagMotion == 512u && CAUSTICS_W_MOTION_WATER < CAUSTICS_W_HEIGHTS && CAUSTICS_W_MOTION_WATER > CAUSTICS_W_BED_PUDDLE);
static_assert(CAUSTICS_MOTION_WAVES_AT + CAUSTICS_MOTION_WAVES * CAUSTICS_MOTION_WAVE_WORDS == CAUSTICS_MOTION_RINGS_AT);
static_assert(CAUSTICS_MOTION_RINGS_AT + CAUSTICS_MOTION_MAX_RINGS * CAUSTICS_MOTION_RING_WORDS <= CAUSTICS_MOTION_WORDS);
static_assert(4 + 4 * 8 + 16 * 4 <= CAUSTICS_MOTION_WORDS && CAUSTICS_MOTION_WAVES == 4 && CAUSTICS_MOTION_MAX_RINGS == 16);
static_assert(CAUSTICS_MOTION_BASE == CAUSTICS_SLOTS * (CAUSTICS_SLOT_WORDS + CAUSTICS_DATA_WORDS) &&
              CAUSTICS_MOTION_RING_PX < CAUSTICS_MOTION_WAVES_AT);

/// The waves: wavelengths (m) and directions from the heading (degrees); capillary-gravity dispersion w^2 = g k + (sigma / rho) k^3,
/// times TimeScale (calmer than open water, and kinder to the upscaler). The heading follows the wind (WindMin m/s or more) or
/// CalmDeg, low-passed with HeadingTau seconds. The steepness k A of the longest wave is SteepPerStrength x strength x the wind's
/// amplitude factor (0.6 calm, 1 at WindFull m/s, 1.4 at most), at most SteepMax; each shorter wave has its share Wavelength / 0.60.
inline constexpr std::array<double, 4> Wavelength{0.60, 0.38, 0.24, 0.15};
inline constexpr std::array<double, 4> DirectionDeg{0.0, 25.0, -40.0, 100.0};
inline constexpr double Gravity = 9.81, Tension = 7.4e-5, TimeScale = 0.6;
inline constexpr double HeadingTau = 2.0, CalmDeg = 30.0, WindMin = 0.2, WindFull = 1.5;
inline constexpr float SteepPerStrength = 0.05f, SteepMax = 0.15f;
/// A ring's amplitude (m) at strength 1; a landing is LandingTimes as much; a drop of LandMinM to DropM in one frame is a landing.
inline constexpr float RingAmp = 0.0008f, LandingTimes = 2.0f, LandMinM = 0.3f;
/// The footprints' walker (footprints.h: StrideM, GaitHalfM, JumpM, DropM, TurnMinM, Walk), copied: that header is on another branch
/// (it pulls the live knobs and blood headers). Keep the numbers the same.
inline constexpr float StrideM = 0.75f, GaitHalfM = 0.11f, JumpM = 2.0f, DropM = 1.0f, TurnMinM = 0.05f;

inline double Omega(double wavelength) {
    const double k = 2.0 * Pi / wavelength;
    return std::sqrt(Gravity * k + Tension * k * k * k) * TimeScale;
}

inline double WrapPi(double a) {
    a = std::fmod(a + Pi, 2.0 * Pi);
    return (a < 0.0 ? a + 2.0 * Pi : a) - Pi;
}

/// BB_WATER_MOTION's text: unset or empty is -1 (the setting decides); else 0..MaxStrength (text that is not a finite number, or
/// not above 0, is 0: the variable decides, as BB_CAUSTICS does).
inline float ParseEnv(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return -1.0f;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    while (end != nullptr && (*end == ' ' || *end == '\t')) {
        ++end;
    }
    if (end == text || end == nullptr || *end != 0 || !std::isfinite(v)) {
        return 0.0f;
    }
    return v > 0.0f ? std::min(v, MaxStrength) : 0.0f;
}

/// The strength in force: the variable's (ParseEnv, 0 or more) when it names one, else the setting's (SettingOf).
inline float Pick(float env, float setting) {
    return env >= 0.0f ? (std::isfinite(env) ? std::min(env, MaxStrength) : 0.0f) : SettingOf(setting);
}

/// The push flag: only for a strength above 0 and a dispatch that runs. Strength 0 (or not finite): never.
inline std::uint32_t FlagsOf(float strength, bool dispatching) {
    return dispatching && std::isfinite(strength) && strength > 0.0f ? FlagMotion : 0u;
}

inline bool Finite3(const float* v) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}

/// The hunter's path since the last step (footprints.h Walk, copied).
struct Walker {
    bool have = false;
    float last[3]{};
    float acc = 0.0f; ///< path across since the last step
    float anchor_x = 0.0f, anchor_z = 0.0f;
    float dir_x = 0.0f, dir_z = 1.0f;
    float side = 1.0f; ///< the next step's side (+1, -1 in turn)
    std::uint32_t jumps = 0;
};

struct Step {
    bool step = false;
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

/// One frame's position: a step when the path since the last one reached StrideM; it stands GaitHalfM to the side. A move of more
/// than JumpM across or DropM up or down in one frame starts the path anew.
inline Step Walk(Walker& w, const float pos[3]) {
    Step s;
    if (!w.have) {
        w.have = true;
        std::copy(pos, pos + 3, w.last);
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    const float dx = pos[0] - w.last[0], dy = pos[1] - w.last[1], dz = pos[2] - w.last[2];
    const float across = std::sqrt(dx * dx + dz * dz);
    std::copy(pos, pos + 3, w.last);
    if (!(across <= JumpM) || !(std::fabs(dy) <= DropM)) { // (a NaN fails both)
        ++w.jumps;
        w.acc = 0.0f;
        w.anchor_x = pos[0];
        w.anchor_z = pos[2];
        return s;
    }
    w.acc += across;
    if (w.acc < StrideM) {
        return s;
    }
    const float ax = pos[0] - w.anchor_x, az = pos[2] - w.anchor_z;
    const float along = std::sqrt(ax * ax + az * az);
    if (along >= TurnMinM) {
        w.dir_x = ax / along;
        w.dir_z = az / along;
    }
    w.acc = w.acc >= 2.0f * StrideM ? 0.0f : w.acc - StrideM; // a run's frame may pass two strides: one step
    w.anchor_x = pos[0];
    w.anchor_z = pos[2];
    s.step = true;
    s.y = pos[1];
    s.x = pos[0] - w.side * GaitHalfM * w.dir_z;
    s.z = pos[2] + w.side * GaitHalfM * w.dir_x;
    w.side = -w.side;
    return s;
}

struct Ring {
    float x = 0.0f, z = 0.0f, age = 0.0f, amp = 0.0f;
};

/// Everything the host keeps: the waves' heading and phases, the rings and the walker.
struct State {
    bool started = false;
    double heading = 0.0;           ///< rad: the waves travel toward (cos, sin) in world (x, z)
    std::array<double, 4> phase{};  ///< rad, 0 to 2 pi, summed in double so floats never grow
    double wind_speed = 0.0;        ///< m/s, horizontal, at the last Advance
    float amp = 0.6f;               ///< the wind's amplitude factor at the last Advance
    float steep = 0.0f;             ///< k A of the longest wave at the last Advance
    std::array<Ring, 16> rings{};
    std::uint32_t count = 0;        ///< rings live (the first `count` of `rings`)
    Walker walker;
};

/// A ring at (x, z): the 17th replaces the oldest.
inline void AddRing(State& s, float x, float z, float amp) {
    std::uint32_t at = s.count;
    if (s.count >= MaxRings) {
        at = 0;
        for (std::uint32_t i = 1; i < MaxRings; ++i) {
            if (s.rings[i].age > s.rings[at].age) {
                at = i;
            }
        }
    } else {
        ++s.count;
    }
    s.rings[at] = {x, z, 0.0f, amp};
}

/// The field's time, by real seconds (clamped to MaxStep, as Drift): the heading toward the wind's (low-passed), the phases, the
/// wind's amplitude factor and the steepness, the rings' ages (a ring of CAUSTICS_RING_LIFE s is gone).
inline double UsedDt(double seconds) {
    return std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
}

inline void Advance(State& s, double seconds, const std::array<float, 3>& wind, float strength,
                    double phase_rate = 1.0) {
    const double dt = UsedDt(seconds);
    const double wx = std::isfinite(wind[0]) ? double(wind[0]) : 0.0, wz = std::isfinite(wind[2]) ? double(wind[2]) : 0.0;
    const double speed = std::sqrt(wx * wx + wz * wz);
    const double target = speed >= WindMin ? std::atan2(wz, wx) : CalmDeg * Pi / 180.0;
    if (!s.started) {
        s.started = true;
        s.heading = target;
    } else {
        s.heading = WrapPi(s.heading + WrapPi(target - s.heading) * (1.0 - std::exp(-dt / HeadingTau)));
    }
    s.wind_speed = speed;
    s.amp = float(0.6 + 0.4 * std::min(speed / WindFull, 2.0));
    const float st = std::isfinite(strength) ? std::max(strength, 0.0f) : 0.0f;
    s.steep = std::min(SteepPerStrength * st * s.amp, SteepMax);
    const double phase_dt = dt * phase_rate;
    for (std::uint32_t i = 0; i < Waves; ++i) {
        s.phase[i] = std::fmod(s.phase[i] + Omega(Wavelength[i]) * phase_dt, 2.0 * Pi);
    }
    std::uint32_t live = 0;
    for (std::uint32_t i = 0; i < s.count; ++i) {
        Ring r = s.rings[i];
        r.age += float(dt);
        if (r.age < float(CAUSTICS_RING_LIFE)) {
            s.rings[live++] = r;
        }
    }
    s.count = live;
}

inline double IndoorRate(const char* text) {
    constexpr double Default = 0.20;
    if (!text) {
        return Default;
    }
    char* end = nullptr;
    const double rate = std::strtod(text, &end);
    return end != text && *end == '\0' && std::isfinite(rate)
               ? std::clamp(rate, 0.0, 1.0) : Default;
}

struct Ambient {
    using Clock = std::chrono::steady_clock;

    State state;
    Clock::time_point last{};
    std::uint32_t frame = 0;
    bool active = false;
    double raw_dt = 0.0;

    // Refresh follows the scene trigger even when the mirror or water is out of view.
    void Tick(std::uint32_t seen, Clock::time_point now, float strength, double rate) {
        if (!(strength > 0.0f)) {
            active = false;
            raw_dt = 0.0;
            return;
        }
        if (active && frame == seen) {
            return;
        }
        raw_dt = active ? std::chrono::duration<double>(now - last).count() : 0.0;
        last = now;
        frame = seen;
        active = true;
        Advance(state, raw_dt, {}, strength, rate);
    }
};

struct Events {
    std::uint32_t steps = 0, landings = 0;
};

/// The hunter's position this frame (world x, y, z; y up): a ring at each step (RingAmp x strength) and, for a drop of LandMinM to
/// DropM in one frame (not a jump), one at the position at LandingTimes the amplitude.
inline Events Observe(State& s, const float pos[3], float strength) {
    Events e;
    const float amp = RingAmp * (std::isfinite(strength) ? std::max(strength, 0.0f) : 0.0f);
    if (s.walker.have) {
        const float dx = pos[0] - s.walker.last[0], dz = pos[2] - s.walker.last[2];
        const float drop = s.walker.last[1] - pos[1];
        if (std::sqrt(dx * dx + dz * dz) <= JumpM && drop >= LandMinM && drop <= DropM) {
            AddRing(s, pos[0], pos[2], amp * LandingTimes);
            ++e.landings;
        }
    }
    const Step st = Walk(s.walker, pos);
    if (st.step) {
        AddRing(s, st.x, st.z, amp);
        ++e.steps;
    }
    return e;
}

/// The waves' heading in degrees, 0 to 360.
inline double HeadingDeg(const State& s) {
    const double d = s.heading * 180.0 / Pi;
    return d < 0.0 ? d + 360.0 : d;
}

/// The motion block of a slot (caustics_layout.h), whole: kind (0 none, 1 mirrored plane, 2 checked puddle plane), the rings, the
/// strength, the waves and the rings. The ring pixel word (the shader's) is 0: the host reads it before this.
inline void WriteBlock(std::uint32_t* b, const State& s, std::uint32_t kind, float strength) {
    std::memset(b, 0, Words * sizeof(std::uint32_t));
    const auto put = [b](std::uint32_t at, float v) { std::memcpy(&b[at], &v, sizeof(float)); };
    b[CAUSTICS_MOTION_KIND] = kind;
    b[CAUSTICS_MOTION_RINGS] = s.count;
    put(CAUSTICS_MOTION_STRENGTH, strength);
    for (std::uint32_t i = 0; i < Waves; ++i) {
        const double k = 2.0 * Pi / Wavelength[i];
        const double dir = s.heading + DirectionDeg[i] * Pi / 180.0;
        const double share = Wavelength[i] / Wavelength[0];
        const std::uint32_t at = CAUSTICS_MOTION_WAVES_AT + i * CAUSTICS_MOTION_WAVE_WORDS;
        put(at, float(k * std::cos(dir)));
        put(at + 1, float(k * std::sin(dir)));
        put(at + 2, float(double(s.steep) * share / k)); // A = (k A) / k
        put(at + 3, float(s.phase[i]));
    }
    for (std::uint32_t i = 0; i < s.count && i < MaxRings; ++i) {
        const std::uint32_t at = CAUSTICS_MOTION_RINGS_AT + i * CAUSTICS_MOTION_RING_WORDS;
        put(at, s.rings[i].x);
        put(at + 1, s.rings[i].z);
        put(at + 2, s.rings[i].age);
        put(at + 3, s.rings[i].amp);
    }
}

/// What the field is at a point: the height, its slope and curvature (the shader's WaveAt, in double); `ring`: a ring packet counted.
struct Sample {
    double eta = 0.0, gx = 0.0, gz = 0.0, lap = 0.0;
    bool ring = false;
};

inline float BitsToFloat(std::uint32_t u) {
    float f = 0.0f;
    std::memcpy(&f, &u, sizeof(f));
    return f;
}

inline Sample Eval(const std::uint32_t* b, double x, double z) {
    Sample r;
    for (std::uint32_t i = 0; i < Waves; ++i) {
        const std::uint32_t at = CAUSTICS_MOTION_WAVES_AT + i * CAUSTICS_MOTION_WAVE_WORDS;
        const double kx = BitsToFloat(b[at]), kz = BitsToFloat(b[at + 1]), amp = BitsToFloat(b[at + 2]);
        const double th = kx * x + kz * z - double(BitsToFloat(b[at + 3]));
        r.eta += amp * std::sin(th);
        r.gx += amp * std::cos(th) * kx;
        r.gz += amp * std::cos(th) * kz;
        r.lap -= amp * (kx * kx + kz * kz) * std::sin(th);
    }
    const std::uint32_t rings = std::min(b[CAUSTICS_MOTION_RINGS], MaxRings);
    const double w = CAUSTICS_RING_WIDTH, w2 = w * w, kk = CAUSTICS_RING_K, r0 = CAUSTICS_RING_R0;
    for (std::uint32_t j = 0; j < rings; ++j) {
        const std::uint32_t at = CAUSTICS_MOTION_RINGS_AT + j * CAUSTICS_MOTION_RING_WORDS;
        const double age = BitsToFloat(b[at + 2]);
        const double dx = x - double(BitsToFloat(b[at])), dz = z - double(BitsToFloat(b[at + 1]));
        const double rr = std::sqrt(dx * dx + dz * dz);
        const double s = rr - CAUSTICS_RING_SPEED * age;
        if (std::fabs(s) >= 3.0 * w || rr < 1e-4 || age >= CAUSTICS_RING_LIFE) {
            continue;
        }
        const double gain = double(BitsToFloat(b[at + 3])) * std::exp(-age / CAUSTICS_RING_TAU) / std::sqrt(1.0 + rr / r0);
        const double e = std::exp(-0.5 * s * s / w2), c = std::cos(kk * s), sn = std::sin(kk * s);
        const double h0 = e * c;
        const double h1 = e * (-(s / w2) * c - kk * sn);
        const double h2 = e * (c * (s * s / (w2 * w2) - 1.0 / w2 - kk * kk) + 2.0 * s * kk * sn / w2);
        const double g1 = -0.5 * gain / (r0 + rr), g2 = 0.75 * gain / ((r0 + rr) * (r0 + rr));
        const double f1 = g1 * h0 + gain * h1, f2 = g2 * h0 + 2.0 * g1 * h1 + gain * h2;
        r.eta += gain * h0;
        r.gx += f1 * dx / rr;
        r.gz += f1 * dz / rr;
        r.lap += f2 + f1 / std::max(rr, 0.02);
        r.ring = true;
    }
    return r;
}

/// The caustic brightness the curvature gives (the shader's Focus; mean 1), and the position the slope moves the net to.
inline float Focus(float lap) {
    return std::clamp(1.0f - float(CAUSTICS_MOTION_FOCUS) * lap, 0.0f, 3.0f);
}

} // namespace Motion

inline float Pattern(float x, float z, const std::array<float, 4>& drift, float evolve) {
    const float ax = (x + drift[0]) / Lambda1, az = (z + drift[1]) / Lambda1;
    const float mx = x + drift[2], mz = z + drift[3];
    const float bx = (float(CAUSTICS_COS2) * mx - float(CAUSTICS_SIN2) * mz) / Lambda2;
    const float bz = (float(CAUSTICS_SIN2) * mx + float(CAUSTICS_COS2) * mz) / Lambda2;
    const float r1 = Ridge(ax, az, evolve);
    const float r2 = Ridge(bx, bz, evolve * float(CAUSTICS_EVOLVE2) + float(CAUSTICS_EVOLVE2_SHIFT));
    return 0.5f * (std::pow(r1, Sharp) + std::pow(r2, Sharp)) / PatternMean;
}

// bbport (r130e_sewer-water-moves): the rippled reflection of a mirrored plane's water (caustics.comp WarpPixel). The host's part:
// the band of rows (WaterTopRow), the dispatch's stamp, the bed light's rule and when the motion runs alone. The twins of the shader's
// shift (ShiftPx) and glint (GlintOf), in float, for the test. Off (strength 0): Alone is false, WorldFor is the variable's value.
namespace Motion::Warp {

inline constexpr std::uint32_t FlagCopy = CAUSTICS_FLAG_WARP_COPY, FlagWarp = CAUSTICS_FLAG_WARP;
inline constexpr std::uint32_t RowMargin = CAUSTICS_MOTION_ROW_MARGIN, RowStep = CAUSTICS_MOTION_ROW_STEP;
inline constexpr float ReflectM = CAUSTICS_MOTION_REFLECT_M, ShiftMax = CAUSTICS_MOTION_SHIFT_MAX;
inline constexpr float Glint = CAUSTICS_MOTION_GLINT, GlintMax = CAUSTICS_MOTION_GLINT_MAX, GlintKnee = CAUSTICS_MOTION_GLINT_KNEE;
/// The bed light's strength when the motion starts it (BB_CAUSTICS_WORLD unset), as the variable "1".
inline constexpr float BedAuto = 1.0f;
/// The stamps run 1 to StampCount: exact in half float (the copy image's alpha).
inline constexpr std::uint32_t StampCount = 2047;
/// The log lines' tag (kept out of vk_caustics.cpp's text: r130b's own check refuses any other line there that holds r130b's tag).
inline constexpr const char* LogTag = "Water motion (r130e)";
static_assert(FlagCopy == 1024u && FlagWarp == 2048u && ((FlagCopy | FlagWarp) & CAUSTICS_FLAG_MOTION) == 0u &&
              (FlagCopy & FlagWarp) == 0u);
static_assert(CAUSTICS_MOTION_RINGS_AT + CAUSTICS_MOTION_MAX_RINGS * CAUSTICS_MOTION_RING_WORDS <= CAUSTICS_MOTION_ROW0 &&
              CAUSTICS_MOTION_ROW0 < CAUSTICS_MOTION_WARP_PX && CAUSTICS_MOTION_WARP_PX < CAUSTICS_MOTION_WARP_KEPT &&
              CAUSTICS_MOTION_WARP_KEPT < CAUSTICS_MOTION_STAMP && CAUSTICS_MOTION_STAMP < CAUSTICS_MOTION_WORDS);
static_assert(StampCount <= 2048u && CAUSTICS_MOTION_GLINT_KNEE > 0.0 && CAUSTICS_MOTION_GLINT_MAX < 1.0);

/// The dispatch's stamp from its number: 1 to StampCount.
inline std::uint32_t Stamp(std::uint32_t dispatch) {
    return dispatch % StampCount + 1u;
}

/// The first row of the band: casts rays at x = 0, w / 2, w - 1 down the rows in RowStep steps and takes the first row where one
/// meets the water plane (world y `plane_y`) nearer than CAUSTICS_FADE_END, minus RowMargin; `h`: none (the camera is not above the
/// plane, or no ray meets it that near). The rays use the push's matrices as the shader's ViewPos and ToWorld.
inline std::uint32_t WaterTopRow(const Push& push, float plane_y, std::uint32_t w, std::uint32_t h) {
    const auto& m = push.inv_view;
    const float cam_y = m[7];
    if (w == 0 || h == 0 || !std::isfinite(plane_y) || !std::isfinite(cam_y) || !(cam_y > plane_y) || !(push.proj[0] != 0.0f) ||
        !(push.proj[1] != 0.0f)) {
        return h;
    }
    const std::array<float, 3> columns{0.5f, 0.5f * float(w), float(w) - 0.5f};
    for (std::uint32_t y = 0; y < h; y += RowStep) {
        const float ndc_y = ((float(y) + 0.5f) - push.frame[3]) / float(h) * 2.0f - 1.0f;
        for (const float cx : columns) {
            const float ndc_x = (cx - push.frame[2]) / float(w) * 2.0f - 1.0f;
            const float vx = ndc_x / push.proj[0], vy = ndc_y / push.proj[1]; // the ray in the view, view z 1
            const float dir_y = m[4] * vx + m[5] * vy + m[6];
            if (dir_y < -1e-6f && (plane_y - cam_y) / dir_y < float(CAUSTICS_FADE_END)) { // t = view z
                return y > RowMargin ? y - RowMargin : 0u;
            }
        }
    }
    return h;
}

inline float SmoothStep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// World to view: the shader's ToView (the view to world rotation's transpose after taking off the camera's position).
inline std::array<float, 3> ToViewOf(const Push& push, const std::array<float, 3>& w) {
    const auto& m = push.inv_view;
    const float dx = w[0] - m[3], dy = w[1] - m[7], dz = w[2] - m[11];
    return {m[0] * dx + m[4] * dy + m[8] * dz, m[1] * dx + m[5] * dy + m[9] * dz, m[2] * dx + m[6] * dy + m[10] * dz};
}

/// The pixel (centre, + 0.5) a view position projects to: the shader's PixelOf.
inline std::array<float, 2> PixelOf(const Push& push, const std::array<float, 3>& v) {
    const float z = std::max(v[2], 1e-4f);
    return {(v[0] * push.proj[0] / z + 1.0f) * 0.5f * push.frame[0] + push.frame[2],
            (v[1] * push.proj[1] / z + 1.0f) * 0.5f * push.frame[1] + push.frame[3]};
}

/// The pixel shift of the reflection at the water point `world` (the shader's): the point moved on the plane by 2 x ReflectM x the
/// slope (gx, gz), projected, times the distance fade, its length at most ShiftMax x the frame's height. Zero behind the camera.
inline std::array<float, 2> ShiftPx(const Push& push, const std::array<float, 3>& world, float gx, float gz) {
    const auto v = ToViewOf(push, world);
    const auto v2 = ToViewOf(push, {world[0] + 2.0f * ReflectM * gx, world[1], world[2] + 2.0f * ReflectM * gz});
    if (!(v2[2] > 0.05f)) {
        return {0.0f, 0.0f};
    }
    const auto a = PixelOf(push, v), b = PixelOf(push, v2);
    const float fade = 1.0f - SmoothStep(float(CAUSTICS_FADE_START), float(CAUSTICS_FADE_END), v[2]);
    std::array<float, 2> s{(b[0] - a[0]) * fade, (b[1] - a[1]) * fade};
    const float lim = ShiftMax * push.frame[1], len = std::hypot(s[0], s[1]);
    if (len > lim) {
        s[0] *= lim / len;
        s[1] *= lim / len;
    }
    return s;
}

/// The glint's factor on a colour of luminance `lum` where the wave field's curvature is `lap` (the shader's): 1 + t, t = Glint x
/// strength x (Focus - 1) x lum / (lum + GlintKnee) within +-GlintMax, times `fade`. It follows the knob; the focus has mean 1.
inline float GlintOf(float lap, float lum, float strength, float fade = 1.0f) {
    const float l = std::max(lum, 0.0f);
    const float t = std::clamp(Glint * strength * (Focus(lap) - 1.0f) * (l / (l + GlintKnee)), -GlintMax, GlintMax) * fade;
    return 1.0f + t;
}

/// The bed light's strength (the world map): the variable's value when it is set and not empty (also 0), else BedAuto while the
/// motion and the lamps' strength are above 0, else the variable's value (0 when unset: nothing new).
inline float WorldFor(bool env_set, float env, float motion, float lamps) {
    if (env_set) {
        return env;
    }
    return motion > 0.0f && lamps > 0.0f ? BedAuto : env;
}

/// The motion runs alone (a dispatch of its own, kind 1) when it is on, a mirrored plane is found, the camera is above it and
/// neither caustics draw this pass.
inline bool Alone(float motion, bool plane, bool camera_above, bool draw, bool lamp_draw) {
    return motion > 0.0f && std::isfinite(motion) && plane && camera_above && !draw && !lamp_draw;
}

} // namespace Motion::Warp

} // namespace BbCaustics
