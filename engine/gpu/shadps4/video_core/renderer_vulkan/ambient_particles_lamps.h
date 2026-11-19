// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r98c_particles-visible): the lamps the ambient motes take their light from and the
// flames that throw embers, without Vulkan (tests/test_ambient_particles.cpp builds it alone;
// vk_ambient_particles.cpp hands LampBlock to ambient_particles.vert, binding 2).
//
// The lamps are the records of the game's lamp pass (16 words: place in view space, 1 / reach
// squared, colour; lamp_fog_lights.h), handed over tile by tile as drawn (Rasterizer::
// EffectsBeforeBind, after the lamp flicker) and started anew at each G-buffer pass
// (EffectsAfterTargets), so the last pass's are kept (the scene's, not a mirrored pass's). Once a
// frame (AmbientParticles::Draw) LampSet::Update takes them into the world with the frame's
// camera and drops them; it keeps each lamp it has seen (matched by place and reach), fades it in
// over FadeIn s while listed and out over FadeOut s once unlisted for Hold s, and fills the block:
// the flames first (Burns, once and for as long as the lamp is kept, with a share of embers above
// 0; nearest first, at most AP_MAX_FLAMES nearer than AP_SPARK_FAR1 m), then the lamps whose
// reach meets the motes' box (nearer than AP_FAR1 + reach), the brightest for their distance
// first, AP_MAX_LAMPS in all. Records farther from the camera than either use (Useful) are not
// gathered at all. The lamps are handed over only while the effects pass runs (Rasterizer::
// effects_wanted: an engine effect such as GTAO is on); without it the block stays empty.
//
// Knob BB_PARTICLES_LAMPS (read once): the lamps' light on the dust times this, 0 to MaxLampGain;
// unset or unreadable: DefaultLampGain; 0 or below: off (no lamp gathered, no ember thrown: the
// motes look as before r98c).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <initializer_list>
#include <vector>

#include "../host_shaders/ambient_particles_layout.h"
#include "ambient_particles.h"
#include "lamp_fog_lights.h"

namespace Vulkan::AmbientMotes {

inline constexpr float DefaultLampGain = 1.0f;
inline constexpr float MaxLampGain = 4.0f;
/// A flame's ember slot burns a life with the chance SparkBirthPerDensity x density (x ShowSparks
/// with BB_PARTICLES_SHOW=1), at most MaxOccupancy, times the flame's share (SparkShare).
inline constexpr float SparkBirthPerDensity = float(AP_SPARK_BIRTH);
inline constexpr float ShowSparks = 1.6f;
/// The embers go with the wind's velocity times this (BB_WIND=1), else with CalmDrift.
inline constexpr float SparkWindFollow = 1.0f;
inline constexpr std::uint32_t FlameInstances = std::uint32_t(AP_MAX_FLAMES) * AP_FLAME_SLOTS;
static_assert(std::uint32_t(AP_LATTICE) == Instances, "the flames' instances follow the lattice's");
static_assert(AP_MAX_FLAMES <= AP_MAX_LAMPS, "the flames are the first lamps of the block");

/// BB_PARTICLES_LAMPS's text as the gain: unset, empty, unreadable or not finite: DefaultLampGain;
/// clamped to 0..MaxLampGain (0: off).
inline float ParseLampGain(const char* text) {
    return std::clamp(Number(text, DefaultLampGain), 0.0f, MaxLampGain);
}

/// BB_PARTICLES_LAMPS, read once.
inline float LampGain() {
    static const float gain = ParseLampGain(std::getenv("BB_PARTICLES_LAMPS"));
    return gain;
}

inline float SparkBirth(const Knobs& k) {
    return std::min(SparkBirthPerDensity * k.density * (k.show ? ShowSparks : 1.0f), MaxOccupancy);
}

/// The embers' drift (m/s): SparkWindFollow x the wind with `wind_on` (a word not finite counts
/// as 0), else CalmDrift (the lattice's calm drift). bbport (r98d_particles-still-indoors):
/// `share` (0-1, not finite: 1) is the part of the wind that stays, the rest is the calm drift;
/// 1 gives the same floats as before.
inline std::array<float, 3> SparkDrift(bool wind_on, const std::array<float, 3>& wind,
                                       float share = 1.0f) {
    std::array<float, 3> d{};
    const float kept = std::isfinite(share) ? std::clamp(share, 0.0f, 1.0f) : 1.0f;
    for (std::size_t i = 0; i < 3; ++i) {
        const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
        d[i] = wind_on ? SparkWindFollow * w : CalmDrift[i];
        if (wind_on && kept < 1.0f) {
            d[i] = d[i] * kept + (1.0f - kept) * CalmDrift[i];
        }
    }
    return d;
}

/// A flame's lamp: orange to warm yellow (green 0.25 to 0.92 of red, blue at most 0.75 of green
/// and 0.6 of red), some light (luminance 0.02 or more) and a reach of 0.5 to 20 m. The heat
/// haze's rule (heat_haze.h IsFlame), kept here on its own: a warm fill light passes too.
inline bool IsFlame(const std::array<float, 3>& colour, float reach) {
    const float r = colour[0], g = colour[1], b = colour[2];
    return r > 0.0f && b >= 0.0f && g >= 0.25f * r && g <= 0.92f * r && b <= 0.75f * g &&
           b <= 0.6f * r && 0.2126f * r + 0.7152f * g + 0.0722f * b >= 0.02f && reach >= 0.5f &&
           reach <= 20.0f;
}

/// A flame that burns (throws embers): IsFlame, one channel at least AP_SPARK_BRIGHT and blue at
/// most AP_SPARK_BLUE of red. By the r64 probe's records the hand torch (2.3-2.9, 1.3-1.6,
/// 0.6-0.7) and bonfire-like lamps (2.0, 1.18, 0.59) pass; the glass street lamps (0.72, 0.42,
/// 0.26), a warm fill light (0.60, 0.45, 0.30) and the yellow (1.50, 1.12, 0.75) lamps do not.
inline bool Burns(const std::array<float, 3>& colour, float reach) {
    return IsFlame(colour, reach) &&
           std::max({colour[0], colour[1], colour[2]}) >= float(AP_SPARK_BRIGHT) &&
           colour[2] <= float(AP_SPARK_BLUE) * colour[0];
}

inline float SmoothStep(float edge0, float edge1, float x) {
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// How many of its slots a flame burns, 0..1: none at a reach of AP_SPARK_REACH0 m or less (a
/// candle: 2-4 m by the probe), all from AP_SPARK_REACH1 m (the hand torch 8.4-8.6 m), smooth
/// between (the church's chandeliers, 5.47 m: about 0.3).
inline float SparkShare(float reach) {
    return SmoothStep(float(AP_SPARK_REACH0), float(AP_SPARK_REACH1), reach);
}

/// A flame's seed: 24 bits of a hash of its serial, over 2^24 (exact in a float: the shader takes
/// the 24 bits back as uint(seed * 2^24)).
inline float SeedOf(std::uint32_t serial) {
    std::uint32_t h = serial * 0x9e3779b9u;
    h ^= h >> 16;
    h *= 0x85ebca6bu;
    h ^= h >> 13;
    return float(h >> 8) / 16777216.0f;
}

/// ambient_particles.vert's Lamps block (std140: vec4 members and arrays of vec4).
struct LampBlock {
    std::array<float, 4> info{}; ///< lamps, flames (the first of them), lamp gain (0: off), birth
    std::array<float, 4> wind{}; ///< the embers' drift xyz (m/s); w: the indoor shade 0..1
                                 ///< (r98d_particles-still-indoors, AmbientMotes::IndoorShade)
    std::array<std::array<float, 4>, AP_MAX_LAMPS> place{};  ///< world xyz (m), reach (m)
    std::array<std::array<float, 4>, AP_MAX_LAMPS> colour{}; ///< rgb as drawn (at most 4), weight
    std::array<std::array<float, 4>, AP_MAX_FLAMES> flame{}; ///< seed, share x weight, 0, 0
    std::array<std::array<float, 4>, AP_MAX_LAMPS> moth{};   ///< x moths, y seed, z loop scale,
                                                             ///< w calm (r98e_moths-at-lamps)
};
static_assert(sizeof(LampBlock) == AP_LAMP_BLOCK_BYTES &&
              AP_LAMP_BLOCK_BYTES == 32 + 32 * AP_MAX_LAMPS + 16 * AP_MAX_FLAMES + 16 * AP_MAX_LAMPS);
static_assert(offsetof(LampBlock, place) == 32 && offsetof(LampBlock, colour) == 32 + 16 * AP_MAX_LAMPS &&
              offsetof(LampBlock, flame) == 32 + 32 * AP_MAX_LAMPS &&
              offsetof(LampBlock, moth) == 32 + 32 * AP_MAX_LAMPS + 16 * AP_MAX_FLAMES);

class LampSet {
public:
    static constexpr float FadeIn = 0.5f;  ///< s: a listed lamp comes in over this
    static constexpr float FadeOut = 0.6f; ///< s: and goes over this
    static constexpr float Hold = 1.0f;    ///< s unlisted before it starts to go
    /// The same lamp: nearer than SameLight m + SameLightPerMetre per m from the camera to where
    /// it was, its reach within SameReach of the larger.
    static constexpr float SameLight = 0.5f, SameLightPerMetre = 0.05f, SameReach = 0.15f;
    static constexpr float CameraJump = 20.0f; ///< m in one frame (a warp): all forgotten
    static constexpr std::size_t MaxEntries = 64; ///< lamps kept (a bound on bad guest data)

    struct Stats {
        std::uint32_t listed = 0;   ///< distinct readable lamps the pass listed within Useful's reach
        std::uint32_t dropped = 0;  ///< of them not kept (MaxEntries kept already)
        std::uint32_t lamps = 0;    ///< in the block
        std::uint32_t flames = 0;   ///< of them flames
        std::uint32_t left_out = 0; ///< would light the motes or throw embers, found no place
        float reach_min = 0.0f, reach_max = 0.0f; ///< the block's flames' reach (m; 0: none)
    };

    /// A G-buffer pass begins: the lamps gathered since were another view's.
    void Clear() {
        gathered.Clear();
    }
    /// One tile's light list of the lamp pass (`count` records of 16 words); only the Useful ones
    /// go through the gathering's dedupe.
    void Add(const std::uint32_t* records, std::uint32_t count) {
        for (std::uint32_t i = 0; i < count; ++i) {
            const std::uint32_t* record = records + std::size_t(i) * 16;
            if (Useful(record)) {
                gathered.Add(record, 1);
            }
        }
    }
    /// A record (view space: the camera at 0) nearer than any use of it: max(AP_SPARK_FAR1,
    /// AP_FAR1 + reach) m. Not finite, or no reach: false.
    static bool Useful(const std::uint32_t* record) {
        const float x = std::bit_cast<float>(record[0]), y = std::bit_cast<float>(record[1]),
                    z = std::bit_cast<float>(record[2]), inverse = std::bit_cast<float>(record[3]);
        if (!(inverse > 0.0f)) {
            return false;
        }
        const float limit = std::max(float(AP_SPARK_FAR1), float(AP_FAR1) + 1.0f / std::sqrt(inverse));
        return x * x + y * y + z * z < limit * limit;
    }
    [[nodiscard]] const Stats& Last() const noexcept {
        return stats;
    }
    [[nodiscard]] std::size_t Kept() const noexcept {
        return entries.size();
    }

    /// Once a frame: the gathered lamps into the world (`inv_view`: view to world, 3x4 rows),
    /// matched, faded over `seconds` (0..MaxStep; not finite: 0), dropped from the gathering; the
    /// block with `gain` (0: off), `birth` and `drift` (m/s).
    LampBlock Update(const std::array<float, 12>& inv_view, double seconds, float gain, float birth,
                     const std::array<float, 3>& drift) {
        const float dt = std::isfinite(seconds) ? float(std::clamp(seconds, 0.0, MaxStep)) : 0.0f;
        const std::array<float, 3> eye{inv_view[3], inv_view[7], inv_view[11]};
        if (has_eye && Distance2(eye, last_eye) > CameraJump * CameraJump) {
            entries.clear();
        }
        last_eye = eye;
        has_eye = true;
        for (auto& e : entries) {
            e.since_seen += dt;
        }
        stats = {};
        std::vector<bool> matched(entries.size(), false);
        for (const auto& light : gathered.Lights()) {
            if (!LampFog::Readable(light)) {
                continue;
            }
            const std::array<float, 3> world =
                Transform(inv_view, {Word(light, 0), Word(light, 1), Word(light, 2)});
            const float reach = 1.0f / std::sqrt(Word(light, 3));
            std::array<float, 3> colour{std::max(Word(light, 4), 0.0f), std::max(Word(light, 5), 0.0f),
                                        std::max(Word(light, 6), 0.0f)};
            // As the shaders limit it: past 4 only the hue counts (lamp_fog_lights.h).
            const float over = std::max(1.0f, std::max({colour[0], colour[1], colour[2]}) / 4.0f);
            for (auto& c : colour) {
                c /= over;
            }
            if (!Finite(world) || !std::isfinite(reach)) {
                continue;
            }
            ++stats.listed;
            const float same = SameLight + SameLightPerMetre * std::sqrt(Distance2(world, eye));
            std::size_t at = entries.size();
            float best = same * same;
            for (std::size_t i = 0; i < entries.size(); ++i) {
                const float d2 = Distance2(world, entries[i].world);
                if (!matched[i] && d2 <= best &&
                    std::abs(reach - entries[i].reach) <=
                        SameReach * std::max(reach, entries[i].reach)) {
                    at = i;
                    best = d2;
                }
            }
            if (at == entries.size()) {
                if (entries.size() >= MaxEntries) {
                    ++stats.dropped;
                    continue;
                }
                Entry fresh; // (no designated init: -Wextra's missing-field warning under -Werror)
                fresh.serial = next_serial++;
                entries.push_back(fresh);
                matched.push_back(false);
            }
            matched[at] = true;
            Entry& e = entries[at];
            e.world = world;
            e.reach = reach;
            e.colour = colour;
            // Once burning, for as long as it is kept: the game's flicker cannot switch it off.
            e.flame = e.flame || Burns(colour, reach);
            e.since_seen = 0.0f;
        }
        gathered.Clear();
        std::erase_if(entries, [&](Entry& e) {
            if (e.since_seen <= Hold) {
                e.weight = std::min(1.0f, e.weight + dt / FadeIn);
                return false;
            }
            e.weight -= dt / FadeOut;
            return !(e.weight > 0.0f);
        });

        std::vector<Pick> flames, others;
        for (std::size_t i = 0; i < entries.size(); ++i) {
            const Entry& e = entries[i];
            if (!(e.weight > 0.0f)) {
                continue;
            }
            const float d = std::sqrt(Distance2(e.world, eye));
            if (e.flame && SparkShare(e.reach) > 0.0f && d < float(AP_SPARK_FAR1)) {
                flames.push_back({i, d});
            } else if (d < float(AP_FAR1) + e.reach) {
                others.push_back({i, -Score(e, d)});
            }
        }
        const auto order = [&](const Pick& a, const Pick& b) {
            return a.key != b.key ? a.key < b.key : entries[a.index].serial < entries[b.index].serial;
        };
        std::sort(flames.begin(), flames.end(), order); // nearest first
        while (flames.size() > std::size_t(AP_MAX_FLAMES)) {
            const Pick farthest = flames.back();
            flames.pop_back();
            const Entry& e = entries[farthest.index];
            if (farthest.key < float(AP_FAR1) + e.reach) {
                others.push_back({farthest.index, -Score(e, farthest.key)}); // it still lights dust
            } else {
                ++stats.left_out;
            }
        }
        std::sort(others.begin(), others.end(), order); // brightest for its distance first
        const std::size_t room = std::size_t(AP_MAX_LAMPS) - flames.size();
        if (others.size() > room) {
            stats.left_out += std::uint32_t(others.size() - room);
            others.resize(room);
        }

        LampBlock block{};
        block.info = {float(flames.size() + others.size()), float(flames.size()), gain, birth};
        block.wind = {drift[0], drift[1], drift[2], 0.0f};
        std::size_t slot = 0;
        for (const Pick& p : flames) {
            const Entry& e = entries[p.index];
            Fill(block, slot, e);
            block.flame[slot] = {SeedOf(e.serial), SparkShare(e.reach) * e.weight, 0.0f, 0.0f};
            stats.reach_min = slot == 0 ? e.reach : std::min(stats.reach_min, e.reach);
            stats.reach_max = std::max(stats.reach_max, e.reach);
            ++slot;
        }
        for (const Pick& p : others) {
            Fill(block, slot, entries[p.index]);
            ++slot;
        }
        stats.lamps = std::uint32_t(slot);
        stats.flames = std::uint32_t(flames.size());
        return block;
    }

private:
    struct Entry {
        std::array<float, 3> world{};
        float reach = 0.0f;
        std::array<float, 3> colour{};
        bool flame = false;      ///< Burns was true at a listing (kept while the entry is)
        float weight = 0.0f;     ///< 0..1: faded in and out
        float since_seen = 0.0f; ///< s since the pass last listed it
        std::uint32_t serial = 0; ///< its own number while kept (the embers' seed)
    };
    struct Pick {
        std::size_t index = 0;
        float key = 0.0f; ///< sorted ascending
    };

    static float Word(const LampFog::Light& light, std::size_t i) {
        return std::bit_cast<float>(light[i]);
    }
    static std::array<float, 3> Transform(const std::array<float, 12>& m,
                                          const std::array<float, 3>& p) {
        return {m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
                m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
                m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]};
    }
    static float Distance2(const std::array<float, 3>& a, const std::array<float, 3>& b) {
        const float x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2];
        return x * x + y * y + z * z;
    }
    static bool Finite(const std::array<float, 3>& v) {
        return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
    }
    /// A lamp's worth for the dust: its light (luminance x weight) times its reach (at most 10 m)
    /// over its distance (at least 1 m).
    static float Score(const Entry& e, float distance) {
        const float luminance = 0.2126f * e.colour[0] + 0.7152f * e.colour[1] + 0.0722f * e.colour[2];
        return e.weight * luminance * std::min(e.reach, 10.0f) / std::max(distance, 1.0f);
    }
    static void Fill(LampBlock& block, std::size_t slot, const Entry& e) {
        block.place[slot] = {e.world[0], e.world[1], e.world[2], e.reach};
        block.colour[slot] = {e.colour[0], e.colour[1], e.colour[2], e.weight};
        // bbport (r98e_moths-at-lamps): the lamp's seed (its own number while kept), for its moths
        block.moth[slot] = {0.0f, SeedOf(e.serial), 0.0f, 0.0f};
    }

    LampFog::FrameLights gathered;
    std::vector<Entry> entries;
    std::array<float, 3> last_eye{};
    bool has_eye = false;
    std::uint32_t next_serial = 1;
    Stats stats;
};

} // namespace Vulkan::AmbientMotes
