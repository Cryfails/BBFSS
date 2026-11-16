# r98c_particles-visible: FEATURE (ambient particles, work order item 6), on top of
# r98_ambient-particles.fixed and r98b_particles-reduced-scene (apply both first; revert this
# before reverting r98b). Off by default: nothing of it exists unless BB_PARTICLES is above 0.
#
# What it changes for the eye (with BB_PARTICLES above 0):
#  - Dust catches lamp and torch light: each mote is lit by up to 16 lamps of the frame's own lamp
#    pass (the game's light grid records, as drawn, flicker included), with the game's curve
#    (1 - d / reach)^2, a 1.5 m halo and forward scattering (Henyey-Greenstein 0.45, capped at 3),
#    so dust glows around lamps and most where the camera looks toward a lamp through it; a slow
#    twinkle (0.65 to 1). Where lamp light is on a mote, the light of the picture behind it (r98)
#    counts less (down to half); with no lamp light on it, exactly as in r98b.
#  - Burning flames (a warm lamp of a 0.5-20 m reach, the heat haze's colour rule, and bright: one
#    channel 1.2 or more, blue at most 0.45 of red; once burning it stays so while kept) throw
#    embers: up to 8 flames within 16 m, 16 slots each, a slot burning lives of 1.2-2.6 s with the
#    chance 0.5 x density x the flame's share (none at a reach of 4 m or less, all from 8 m),
#    rising at 0.45-0.95 m/s from a disc around the lamp, swirling, going with the calm drift or
#    the wind (BB_WIND=1), cooling from orange to red, seen up to 16 m. The lattice's own slow
#    embers stay near those flames (in full within 1.5 m, none beyond 4 m).
#  - Lamps fade in (0.5 s) and out (0.6 s, after 1 s unlisted), so the game's listing in groups
#    does not pop the light.
#  - BB_PARTICLES_LAMPS: the lamps' gain, 0 to 4, unset 1; 0 gives the r98b look exactly (no lamp
#    is gathered, no ember instance drawn, the old ember rule and light).
# Adversarial review of the draft (2026-11-15 about 23:40), fixed here (data: the r64 probe's
# lamp records, S/probe_<place>.txt):
#  1. Embers came from dim warm lamps that are no fire: at lamp-test-spot both glass street lamps
#     (0.72,0.42,0.26, reach 6, 4.4 m and 13.4 m) took full ember shares, at dark-interior a warm
#     fill light (0.60,0.45,0.30, reach 9) 2 m from the camera, at dark-alley two (1.50,1.12,0.75,
#     reach 9) lights. A flame that throws embers is now also bright and red enough (Burns: the
#     hand torch is 2.3-2.9/1.3-1.6/0.6-0.7, reach 8.4-8.6), sticky so the game's flicker cannot
#     switch it; candles and flames of no share take no flame slot.
#  2. AP_SPARK_REACH0/1 were guesses (2 and 6 m) said to wait for a log; the probe has them:
#     candles 2-4 m, church chandeliers 5.47 m, the hand torch 8.4-8.6 m, bonfire-like lamps 6-10 m.
#     Now 4 and 8 m: candles none, chandeliers about 0.3, the torch all (the owner's question stays).
#  3. With the lamps on, the picture behind every dust mote counted half everywhere, so motes away
#     from lamps were half as bright as in r98b (the owner already found them faint). Now only as
#     much as lamp light is on the mote; no lamp light: the r98b colour exactly.
#  4. CPU: every record of every tile went through the dedupe set (about 1800 a frame at
#     lamp-test-spot by the probe's counts). Records farther from the camera than any use
#     (max(16 m, 7.5 m + reach), view space) are now skipped before the set.
#  5. The lamp loop ran on all 6 vertices of a mote; v_colour is flat, so only the provoking
#     vertex (the first of each triangle) needs it: 2 of 6 now.
#  6. README: the lamps are gathered only while an engine effect runs (effects_wanted), which the
#     row did not say (maintainer rule 7); the new rules and numbers.
#  7. Test: LampSet's new entry without a designated initializer (-Wextra -Werror); cases for the
#     new rules (bright, red enough, sticky, the far-record skip, no-share flames).
#  8. Jobs: the draft's off twin at dark-alley was the whole feature off (BB_PARTICLES=0), not a
#     twin of this change; there was no check of the street lamps (fault 1).
#  9. Look (b23 pictures, slot_r98c-lt1_later.jpg): lamp-lit motes read white, not warm. The curve
#     1 - exp(-x) per channel squeezed a warm light's channels together and the per-channel cap at
#     0.85 flattened them further. Now the largest channel takes the curve with the hue kept, and
#     a lit mote's colour is scaled down, hue kept, until no channel passes 0.85.
# 10. Diagnosis: no ember stream was seen above the torch in b23 although 3 flames were logged.
#     The 10 s line now also gives the nearest flame's place back in view space, to compare with
#     the lamp record's own place (the r64 probe's "at=").
# Review fixes of r98b (adversarial review 2026-11-15 22:40):
#  - RunUiOnly's reduced-scene depth was read through SceneTargets::Read with its defaults (compute
#    stage, shader read) for the motes' vertex and fragment shaders: correct only by chaining with
#    Draw's ALL_COMMANDS barrier, and it records the proxy's last use as a compute read. Now read
#    for the vertex and fragment stages, as the native branch beside it already is.
#  - README: "With a 1920x1080 output nothing is drawn" now names why (the launcher sets no render
#    size there, so neither place is reached).
#
# Files (each edit's text found exactly once, else nothing is written):
#  - new renderer_vulkan/ambient_particles_lamps.h (pure: knob, flame rule, LampSet, LampBlock);
#  - host_shaders/ambient_particles_layout.h: the lamps' and embers' numbers;
#  - host_shaders/ambient_particles.vert: the Lamps block (binding 2), lamp light, flame embers;
#  - renderer_vulkan/vk_ambient_particles.h/.cpp: the block's buffer, binding 2, the upload in the
#    draw's commands, the lamps' update, the once-line and the periodic line;
#  - renderer_vulkan/vk_rasterizer_effects.cpp: two hooks (tile lamps; G-buffer pass clears);
#  - renderer_vulkan/vk_temporal_upscaler.cpp: r98b's depth read stages (review fix);
#  - tests/test_ambient_particles.cpp: checks of the new header;
#  - README.md: the BB_PARTICLES_LAMPS row and three sentences.
# ambient_particles.frag is not changed (its build stays byte-identical).
#
# Use: python -I -X utf8 r98c_particles-visible.py check | apply | revert. Root from R98C_ROOT,
# else <tree>. Line ends of each file kept (CRLF in the tree). Originals of the edited files
# are copied to r98c_fixed_backup/ next to this script at apply; revert removes the new file.
# The tree held the draft with one fix (S/r98c_particles-visible.applied-2314.py, the earlier
# .fixed.py, applied 23:14): revert it with that script first; this one refuses until then.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r98c_fixed_backup")
ROOT = os.environ.get("R98C_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TAG = "r98c_particles-visible"

# ---------------------------------------------------------------- new pure header
LAMPS_H = r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
/// as 0), else CalmDrift (the lattice's calm drift).
inline std::array<float, 3> SparkDrift(bool wind_on, const std::array<float, 3>& wind) {
    std::array<float, 3> d{};
    for (std::size_t i = 0; i < 3; ++i) {
        const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
        d[i] = wind_on ? SparkWindFollow * w : CalmDrift[i];
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
    std::array<float, 4> wind{}; ///< the embers' drift xyz (m/s), unused
    std::array<std::array<float, 4>, AP_MAX_LAMPS> place{};  ///< world xyz (m), reach (m)
    std::array<std::array<float, 4>, AP_MAX_LAMPS> colour{}; ///< rgb as drawn (at most 4), weight
    std::array<std::array<float, 4>, AP_MAX_FLAMES> flame{}; ///< seed, share x weight, 0, 0
};
static_assert(sizeof(LampBlock) == AP_LAMP_BLOCK_BYTES &&
              AP_LAMP_BLOCK_BYTES == 32 + 32 * AP_MAX_LAMPS + 16 * AP_MAX_FLAMES);
static_assert(offsetof(LampBlock, place) == 32 && offsetof(LampBlock, colour) == 32 + 16 * AP_MAX_LAMPS &&
              offsetof(LampBlock, flame) == 32 + 32 * AP_MAX_LAMPS);

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
    }

    LampFog::FrameLights gathered;
    std::vector<Entry> entries;
    std::array<float, 3> last_eye{};
    bool has_eye = false;
    std::uint32_t next_serial = 1;
    Stats stats;
};

} // namespace Vulkan::AmbientMotes
'''

NEW_FILES = {R + "ambient_particles_lamps.h": LAMPS_H}

# ---------------------------------------------------------------- ambient_particles_layout.h
LAYOUT_ANCHOR = "#define AP_FLAG_SCENE_OUTPUT 2\n"
LAYOUT_BLOCK = r'''
// bbport (r98c_particles-visible): the frame's lamps (binding 2 of ambient_particles.vert, the
// Lamps block; renderer_vulkan/ambient_particles_lamps.h fills it). At most AP_MAX_LAMPS lamps
// light the dust, the first of them at most AP_MAX_FLAMES flames that throw embers: AP_FLAME_SLOTS
// instances a flame, after the lattice's AP_LATTICE.
#define AP_LATTICE (AP_NX * AP_NY * AP_NZ)
#define AP_MAX_LAMPS 16
#define AP_MAX_FLAMES 8
#define AP_FLAME_SLOTS 16
#define AP_LAMP_BLOCK_BYTES 672
// Dust lit by a lamp: the lamp pass's colour x the game's curve (1 - d / reach)^2 x a halo
// 1 / (1 + (d / AP_LAMP_HALO)^2) (d in m) x forward scattering (Henyey-Greenstein with AP_PHASE_G,
// 1 seen from the side, at most AP_PHASE_MAX) x AP_LAMP_EXPOSURE x the lamp gain; its largest
// channel L is taken to 1 - exp(-L) with the hue kept (all channels times (1 - exp(-L)) / L), then
// display-encoded (power 1 / 2.2); it twinkles slowly down to 1 - AP_TWINKLE.
// The light of the picture behind a dust mote then counts mix(1, AP_BACK_WITH_LAMPS, its lamp
// light's largest channel / AP_BACK_LAMP_FULL, at most 1) times (no lamp light: as before), and a
// lit mote's colour is scaled down, hue kept, until no channel is above AP_MAX_LIT.
#define AP_LAMP_HALO 1.5
#define AP_PHASE_G 0.45
#define AP_PHASE_MAX 3.0
#define AP_LAMP_EXPOSURE 1.5
#define AP_TWINKLE 0.35
#define AP_BACK_WITH_LAMPS 0.5
#define AP_BACK_LAMP_FULL 0.5
#define AP_MAX_LIT 0.85
// Embers a burning flame throws (a warm lamp with one channel at least AP_SPARK_BRIGHT and blue at
// most AP_SPARK_BLUE of red): a slot burns lives of AP_SPARK_LIFE_MIN..MAX s, each with the chance
// AP_SPARK_BIRTH x density x the flame's share (none at a reach of AP_SPARK_REACH0 m or less, all
// from AP_SPARK_REACH1 m). An ember starts on a disc of AP_SPARK_SPREAD x reach (AP_SPARK_SPREAD_MIN
// to MAX m) around the lamp, rises at AP_SPARK_RISE_MIN..MAX m/s (its height: rise x seconds x
// (1 - 0.35 x age)), swirls up to AP_SPARK_SWIRL m, goes with the drift (the wind with BB_WIND=1),
// cools from orange to red (glow AP_SPARK_GLOW), radius AP_SPARK_RADIUS m; seen up to AP_SPARK_FAR1
// m from the camera (in full to AP_SPARK_FAR0). With the lamps on, the lattice's own embers are
// only near such flames: in full within AP_EMBER_NEAR0 m of one, none beyond AP_EMBER_NEAR1.
#define AP_SPARK_BIRTH 0.5
#define AP_SPARK_LIFE_MIN 1.2
#define AP_SPARK_LIFE_MAX 2.6
#define AP_SPARK_BRIGHT 1.2
#define AP_SPARK_BLUE 0.45
#define AP_SPARK_REACH0 4.0
#define AP_SPARK_REACH1 8.0
#define AP_SPARK_SPREAD 0.02
#define AP_SPARK_SPREAD_MIN 0.05
#define AP_SPARK_SPREAD_MAX 0.25
#define AP_SPARK_RISE_MIN 0.45
#define AP_SPARK_RISE_MAX 0.95
#define AP_SPARK_SWIRL 0.12
#define AP_SPARK_GLOW 0.95
#define AP_SPARK_RADIUS 0.009
#define AP_SPARK_FAR0 10.0
#define AP_SPARK_FAR1 16.0
#define AP_EMBER_NEAR0 1.5
#define AP_EMBER_NEAR1 4.0
'''

# ---------------------------------------------------------------- ambient_particles.vert
VERT_HEAD_ANCHOR = "// is the light behind the mote, not the light at its own place.\n"
VERT_HEAD_BLOCK = r'''// bbport (r98c_particles-visible): with lamp_info.z above 0 (BB_PARTICLES_LAMPS) a dust mote is
// also lit by the frame's lamps (the Lamps block, binding 2: scattered toward the camera), the
// lattice's embers stay near flames, and the instances after the lattice's are embers the flames
// throw (ambient_particles_layout.h has the numbers).
'''
VERT_BIND_ANCHOR = "                                                 // output size (AP_FLAG_SCENE_OUTPUT)\n"
VERT_BIND_BLOCK = r'''// bbport (r98c_particles-visible): the frame's lamps (renderer_vulkan/ambient_particles_lamps.h
// LampBlock, the same order).
layout(std140, binding = 2) uniform Lamps {
    vec4 lamp_info;                 // x: lamps, y: flames (the first of them), z: lamp gain (0:
                                    // off), w: an ember slot's chance to burn a life
    vec4 lamp_wind;                 // xyz: the embers' drift (m/s)
    vec4 lamp_place[AP_MAX_LAMPS];  // world xyz (m), reach (m)
    vec4 lamp_colour[AP_MAX_LAMPS]; // rgb as the lamp pass drew it (at most 4), w: weight 0..1
    vec4 flame_seed[AP_MAX_FLAMES]; // x: seed (24 bits over 2^24), y: share of its slots burning
};
'''

VERT_MAIN_OLD = r'''void main() {
    const vec2 corner = CORNERS[gl_VertexIndex % 6];
    gl_Position = vec4(-4.0, -4.0, 0.0, 1.0);
    v_local = vec2(0.0);
    v_render = vec2(0.0);
    v_colour = vec3(0.0);
    v_z = 0.0;

    // The cell: the lattice is carried by the drift, its box centred on the camera.
    const int index = gl_InstanceIndex;
    const ivec3 local = ivec3(index % AP_NX, (index / AP_NX) % AP_NY, index / (AP_NX * AP_NY));
    const vec3 lattice_camera = camera.xyz - drift.xyz;
    const ivec3 cell = ivec3(floor(lattice_camera / AP_CELL)) -
                       ivec3(AP_NX / 2, AP_NY / 2, AP_NZ / 2) + local;
    const uvec3 key = uvec3(cell) & uvec3(AP_PERIOD - 1);
    const vec3 u = ap_unit(ap_hash(key));
    if (u.x >= drift.w) {
        return; // no mote in this cell
    }
    const bool ember = u.y < look.y;
    const float life = ember ? mix(AP_EMBER_LIFE_MIN, AP_EMBER_LIFE_MAX, u.z)
                             : mix(AP_MOTE_LIFE_MIN, AP_MOTE_LIFE_MAX, u.z);
    // Each life of the cell's mote has its own place in the cell (a new hash at each life).
    const float cycle = camera.w / life + fract(u.x * 13.7 + u.z * 5.3);
    const float lives = floor(cycle);
    const float age = cycle - lives;
    const uvec3 h = ap_hash(key ^ uvec3(uint(lives) * 747796405u));
    const vec3 place = ap_unit(h);
    const vec3 phase = ap_unit(ap_hash(h)) * 6.2831853;
    const float t = camera.w;
    const float rise = ember ? AP_EMBER_RISE : AP_MOTE_RISE;
    const float wobble = ember ? AP_EMBER_WOBBLE : AP_MOTE_WOBBLE;
    const vec3 sway = wobble * vec3(sin(t * 0.83 + phase.x), AP_WOBBLE_Y * sin(t * 0.61 + phase.y),
                                    cos(t * 0.71 + phase.z));
    const vec3 world = (vec3(cell) + place) * AP_CELL + drift.xyz +
                       vec3(0.0, rise * (age - 0.5) * life, 0.0) + sway;

    const vec4 at = vec4(world, 1.0);
    const vec3 view = vec3(dot(view_row[0], at), dot(view_row[1], at), dot(view_row[2], at));
    const float z = view.z;
    if (z < AP_NEAR0) {
        return;
    }
    const vec3 rel = world - camera.xyz;
    const float reach = length(vec3(rel.x, rel.y * AP_FAR_Y, rel.z));
    const float fade = smoothstep(0.0, 0.2, age) * (1.0 - smoothstep(0.75, 1.0, age)) *
                       smoothstep(AP_NEAR0, AP_NEAR1, z) * (1.0 - smoothstep(AP_FAR0, AP_FAR1, reach));
    if (fade <= 0.0) {
        return;
    }
    const vec2 ndc = view.xy * proj.xy / z;
    if (abs(ndc.x) > 1.02 || abs(ndc.y) > 1.02) {
        return;
    }
    const vec2 out_size = vec2(frame.x & 0xffffu, frame.x >> 16u);
    const vec2 render = vec2(frame.y & 0xffffu, frame.y >> 16u);
    const vec2 jitter = unpackSnorm2x16(frame.z);
    const ivec2 last = ivec2(render) - 1;
    const ivec2 centre = clamp(ivec2((ndc * 0.5 + 0.5) * render + jitter), ivec2(0), last);
    if (scene_z(texelFetch(depth_tex, centre, 0).r) < z - AP_SOFT) {
        return; // behind a surface (the pixels' own test softens the edges)
    }

    // Size: a mote smaller than AP_MIN_PX is drawn at that size with its light scaled down by the
    // area, so far motes get fainter instead of flickering.
    const float radius_px = (ember ? AP_EMBER_RADIUS : AP_MOTE_RADIUS) * look.z * abs(proj.y) *
                            0.5 * out_size.y / z;
'''
VERT_MAIN_NEW = r'''// bbport (r98c_particles-visible): the lamps' light scattered by dust at `world` toward the
// camera (linear, in the lamp pass's units; ambient_particles_layout.h).
vec3 lamp_light(vec3 world) {
    vec3 sum = vec3(0.0);
    const int lamps = min(int(lamp_info.x), AP_MAX_LAMPS);
    const vec3 eye = normalize(camera.xyz - world);
    const float g = AP_PHASE_G;
    const float side = pow(1.0 + g * g, 1.5);
    for (int i = 0; i < lamps; ++i) {
        const vec3 d = world - lamp_place[i].xyz;
        const float dist = length(d);
        const float reach = lamp_place[i].w;
        if (!(dist < reach)) {
            continue;
        }
        const float x = 1.0 - dist / reach;
        const float halo = 1.0 / (1.0 + dist * dist * (1.0 / (AP_LAMP_HALO * AP_LAMP_HALO)));
        // The light goes from the lamp through the mote (d); forward is toward the camera.
        const float c = dot(d, eye) / max(dist, 1e-3);
        const float phase = min(side / pow(max(1.0 + g * g - 2.0 * g * c, 1e-4), 1.5), AP_PHASE_MAX);
        sum += lamp_colour[i].rgb * (lamp_colour[i].w * x * x * halo * phase);
    }
    return sum;
}

// bbport (r98c_particles-visible): 0..1, how near `p` is to a flame that throws embers (in full
// within AP_EMBER_NEAR0 m, none beyond AP_EMBER_NEAR1 m), times that flame's share.
float flame_near(vec3 p) {
    float near = 0.0;
    const int flames = min(int(lamp_info.y), AP_MAX_FLAMES);
    for (int f = 0; f < flames; ++f) {
        near = max(near, (1.0 - smoothstep(AP_EMBER_NEAR0, AP_EMBER_NEAR1,
                                            distance(p, lamp_place[f].xyz))) * flame_seed[f].y);
    }
    return near;
}

// bbport (r98c_particles-visible): slot `slot` of flame `f` (ambient_particles_layout.h): false
// while it burns no life (or there is no such flame).
bool flame_ember(int f, int slot, out vec3 world, out float life_fade, out float heat,
                 out float seed) {
    world = vec3(0.0);
    life_fade = 0.0;
    heat = 0.0;
    seed = 0.0;
    if (f >= min(int(lamp_info.y), AP_MAX_FLAMES)) {
        return false;
    }
    const vec4 flame = lamp_place[f];
    const uint key = uint(flame_seed[f].x * 16777216.0);
    const vec3 u = ap_unit(ap_hash(uvec3(key, uint(slot), 0x5bd1e995u)));
    const float life = mix(AP_SPARK_LIFE_MIN, AP_SPARK_LIFE_MAX, u.z);
    const float cycle = camera.w / life + u.x;
    const float lives = floor(cycle);
    const float age = cycle - lives;
    const uvec3 h = ap_hash(uvec3(key, uint(slot), uint(lives) * 747796405u + 1u));
    const vec3 v = ap_unit(h);
    if (v.z >= lamp_info.w * flame_seed[f].y) {
        return false; // this life burns nothing
    }
    const vec3 w = ap_unit(ap_hash(h));
    const float secs = age * life;
    const float spread = clamp(AP_SPARK_SPREAD * flame.w, AP_SPARK_SPREAD_MIN, AP_SPARK_SPREAD_MAX);
    const float angle = 6.2831853 * v.x;
    const vec3 start = flame.xyz + vec3(cos(angle), 0.0, sin(angle)) * (spread * sqrt(v.y));
    const float rise = mix(AP_SPARK_RISE_MIN, AP_SPARK_RISE_MAX, w.x);
    const float t = camera.w;
    const vec3 swirl = (AP_SPARK_SWIRL * age) *
                       vec3(sin(t * (2.1 + w.y) + 6.2831853 * w.z),
                            0.4 * sin(t * 3.3 + 6.2831853 * w.y),
                            cos(t * (1.7 + w.z) + 6.2831853 * w.x));
    world = start + vec3(0.0, rise * secs * (1.0 - 0.35 * age), 0.0) + lamp_wind.xyz * secs + swirl;
    life_fade = smoothstep(0.0, 0.06, age) * (1.0 - smoothstep(0.5, 1.0, age));
    heat = 1.0 - 0.7 * age;
    seed = w.y;
    return true;
}

void main() {
    const vec2 corner = CORNERS[gl_VertexIndex % 6];
    gl_Position = vec4(-4.0, -4.0, 0.0, 1.0);
    v_local = vec2(0.0);
    v_render = vec2(0.0);
    v_colour = vec3(0.0);
    v_z = 0.0;

    const float t = camera.w;
    // bbport (r98c_particles-visible): the lamps' light and the flames' embers while lamp_info.z
    // is above 0 (BB_PARTICLES_LAMPS); else the look of r98 and r98b.
    const bool lamps_on = lamp_info.z > 0.0;
    vec3 world;
    float life_fade;
    float heat = 1.0;
    float seed;
    bool ember;
    bool thrown = false; // an ember a flame threw (the instances after the lattice's)
    vec3 place = vec3(0.5);
    vec3 phase = vec3(0.0);
    if (gl_InstanceIndex >= AP_LATTICE) {
        const int slot = gl_InstanceIndex - AP_LATTICE;
        if (!flame_ember(slot / AP_FLAME_SLOTS, slot % AP_FLAME_SLOTS, world, life_fade, heat,
                         seed)) {
            return;
        }
        ember = true;
        thrown = true;
    } else {
        // The cell: the lattice is carried by the drift, its box centred on the camera.
        const int index = gl_InstanceIndex;
        const ivec3 local = ivec3(index % AP_NX, (index / AP_NX) % AP_NY, index / (AP_NX * AP_NY));
        const vec3 lattice_camera = camera.xyz - drift.xyz;
        const ivec3 cell = ivec3(floor(lattice_camera / AP_CELL)) -
                           ivec3(AP_NX / 2, AP_NY / 2, AP_NZ / 2) + local;
        const uvec3 key = uvec3(cell) & uvec3(AP_PERIOD - 1);
        const vec3 u = ap_unit(ap_hash(key));
        if (u.x >= drift.w) {
            return; // no mote in this cell
        }
        // With the lamps on, the cell's mote is an ember only near a flame that throws embers.
        const float share =
            lamps_on ? look.y * flame_near((vec3(cell) + 0.5) * AP_CELL + drift.xyz) : look.y;
        ember = u.y < share;
        const float life = ember ? mix(AP_EMBER_LIFE_MIN, AP_EMBER_LIFE_MAX, u.z)
                                 : mix(AP_MOTE_LIFE_MIN, AP_MOTE_LIFE_MAX, u.z);
        // Each life of the cell's mote has its own place in the cell (a new hash at each life).
        const float cycle = camera.w / life + fract(u.x * 13.7 + u.z * 5.3);
        const float lives = floor(cycle);
        const float age = cycle - lives;
        const uvec3 h = ap_hash(key ^ uvec3(uint(lives) * 747796405u));
        place = ap_unit(h);
        phase = ap_unit(ap_hash(h)) * 6.2831853;
        const float rise = ember ? AP_EMBER_RISE : AP_MOTE_RISE;
        const float wobble = ember ? AP_EMBER_WOBBLE : AP_MOTE_WOBBLE;
        const vec3 sway = wobble * vec3(sin(t * 0.83 + phase.x), AP_WOBBLE_Y * sin(t * 0.61 + phase.y),
                                        cos(t * 0.71 + phase.z));
        world = (vec3(cell) + place) * AP_CELL + drift.xyz +
                vec3(0.0, rise * (age - 0.5) * life, 0.0) + sway;
        life_fade = smoothstep(0.0, 0.2, age) * (1.0 - smoothstep(0.75, 1.0, age));
        seed = place.x;
    }

    const vec4 at = vec4(world, 1.0);
    const vec3 view = vec3(dot(view_row[0], at), dot(view_row[1], at), dot(view_row[2], at));
    const float z = view.z;
    if (z < AP_NEAR0) {
        return;
    }
    const vec3 rel = world - camera.xyz;
    // An ember a flame threw is seen further (AP_SPARK_FAR0/1), heights counted as they are.
    const float reach = thrown ? length(rel) : length(vec3(rel.x, rel.y * AP_FAR_Y, rel.z));
    const float far0 = thrown ? AP_SPARK_FAR0 : AP_FAR0;
    const float far1 = thrown ? AP_SPARK_FAR1 : AP_FAR1;
    const float fade = life_fade * smoothstep(AP_NEAR0, AP_NEAR1, z) *
                       (1.0 - smoothstep(far0, far1, reach));
    if (fade <= 0.0) {
        return;
    }
    const vec2 ndc = view.xy * proj.xy / z;
    if (abs(ndc.x) > 1.02 || abs(ndc.y) > 1.02) {
        return;
    }
    const vec2 out_size = vec2(frame.x & 0xffffu, frame.x >> 16u);
    const vec2 render = vec2(frame.y & 0xffffu, frame.y >> 16u);
    const vec2 jitter = unpackSnorm2x16(frame.z);
    const ivec2 last = ivec2(render) - 1;
    const ivec2 centre = clamp(ivec2((ndc * 0.5 + 0.5) * render + jitter), ivec2(0), last);
    if (scene_z(texelFetch(depth_tex, centre, 0).r) < z - AP_SOFT) {
        return; // behind a surface (the pixels' own test softens the edges)
    }

    // Size: a mote smaller than AP_MIN_PX is drawn at that size with its light scaled down by the
    // area, so far motes get fainter instead of flickering.
    const float radius_px =
        (thrown ? AP_SPARK_RADIUS : ember ? AP_EMBER_RADIUS : AP_MOTE_RADIUS) * look.z *
        abs(proj.y) * 0.5 * out_size.y / z;
'''

VERT_COLOUR_OLD = r'''    vec3 colour;
    float peak;
    if (ember) {
        // An ember glows by itself, more where the light around it is warm (fire, lamps).
        const float warm = clamp((light.r - light.b) * 4.0 + 0.25, 0.25, 1.0);
        const float flicker = 0.65 + 0.35 * sin(t * (6.0 + 5.0 * place.x) + phase.y);
        colour = vec3(1.0, 0.42, 0.10) * (0.6 * warm * flicker) + 0.3 * hue;
        peak = AP_EMBER_PEAK;
    } else {
        colour = hue * vec3(1.0, 0.96, 0.9);
        peak = AP_MOTE_PEAK;
    }
    colour = min(colour * look.x + look.w, vec3(AP_MAX_COLOUR));
    v_colour = colour * (peak * fade * energy);
'''
VERT_COLOUR_NEW = r'''    vec3 colour;
    float peak;
    if (thrown) {
        // bbport (r98c_particles-visible): it glows by itself, orange cooling to red as it rises,
        // and flickers.
        const float flicker = 0.7 + 0.3 * sin(t * (7.0 + 6.0 * seed) + 6.2831853 * seed);
        colour = min(vec3(1.0, 0.30 + 0.25 * heat, 0.05 + 0.08 * heat) *
                         (AP_SPARK_GLOW * heat * flicker),
                     vec3(AP_MAX_LIT));
        peak = AP_EMBER_PEAK;
    } else if (ember) {
        // An ember glows by itself, more where the light around it is warm (fire, lamps).
        const float warm = clamp((light.r - light.b) * 4.0 + 0.25, 0.25, 1.0);
        const float flicker = 0.65 + 0.35 * sin(t * (6.0 + 5.0 * place.x) + phase.y);
        colour = vec3(1.0, 0.42, 0.10) * (0.6 * warm * flicker) + 0.3 * hue;
        colour = min(colour * look.x + look.w, vec3(AP_MAX_COLOUR));
        peak = AP_EMBER_PEAK;
    } else {
        // bbport (r98c_particles-visible): the lamps' light on it, twinkling slowly (display-
        // encoded). v_colour is flat: only the provoking vertex (the first of each triangle, 0 and
        // 3 of the quad) is used, so the others skip the lamps' loop.
        vec3 lamp_lit = vec3(0.0);
        const int quad_vertex = gl_VertexIndex % 6;
        if (lamps_on && (quad_vertex == 0 || quad_vertex == 3)) {
            const float twinkle =
                1.0 - AP_TWINKLE * (0.5 + 0.5 * sin(t * (1.1 + 1.6 * place.y) + phase.x));
            const vec3 lit = lamp_light(world) * (lamp_info.z * AP_LAMP_EXPOSURE * twinkle);
            // The largest channel takes the curve, the others keep their share of it: a channel
            // by channel curve turned torch light white (slot b23's pictures).
            const float strongest = max(lit.r, max(lit.g, lit.b));
            if (strongest > 1e-6) {
                lamp_lit = pow(lit * ((1.0 - exp(-strongest)) / strongest), vec3(1.0 / 2.2)) *
                           vec3(1.0, 0.97, 0.92);
            }
        }
        // The picture behind counts less only as far as lamp light is on the mote (none: r98b's).
        const float back =
            mix(1.0, AP_BACK_WITH_LAMPS,
                clamp(max(lamp_lit.r, max(lamp_lit.g, lamp_lit.b)) / AP_BACK_LAMP_FULL, 0.0, 1.0));
        colour = min(hue * vec3(1.0, 0.96, 0.9) * (look.x * back) + look.w, vec3(AP_MAX_COLOUR));
        if (lamps_on) {
            // At most AP_MAX_LIT a channel, the hue kept (r98b's colour, at most AP_MAX_COLOUR,
            // is left as it is when no lamp light is on the mote).
            colour += lamp_lit;
            colour *= min(1.0, AP_MAX_LIT / max(max(colour.r, colour.g), max(colour.b, 1e-6)));
        }
        peak = AP_MOTE_PEAK;
    }
    v_colour = colour * (peak * fade * energy);
'''

# ---------------------------------------------------------------- vk_ambient_particles.h
APH_DOC_OLD = r'''// One draw a frame: 6 vertices x AmbientMotes::Instances instances, no vertex buffer, no image
// or buffer of its own; the frame is screened (colour + frame (1 - colour)) through the UI
'''
APH_DOC_NEW = r'''// One draw a frame: 6 vertices x AmbientMotes::Instances instances (r98c_particles-visible: and
// AmbientMotes::FlameInstances while the lamps are on), no vertex buffer, no image of its own;
// r98c: one uniform buffer, the lamps' block (AmbientMotes::LampBlock, 672 bytes, written in the
// draw's own commands); the frame is screened (colour + frame (1 - colour)) through the UI
'''
APH_INC1_ANCHOR = '#include "video_core/renderer_vulkan/ambient_particles.h"\n'
APH_INC1_BLOCK = '#include "video_core/renderer_vulkan/ambient_particles_lamps.h" // bbport (r98c_particles-visible)\n'
APH_INC2_ANCHOR = '#include "video_core/renderer_vulkan/vk_common.h"\n'
APH_INC2_BLOCK = ("// bbport (r98c_particles-visible): after vk_common.h (its Vulkan configuration first)\n"
                  "#include <vk_mem_alloc.h>\n")
APH_API_ANCHOR = "              bool wind_on, const std::array<float, 3>& wind);\n"
APH_API_BLOCK = r'''
    /// bbport (r98c_particles-visible): BB_PARTICLES_LAMPS above 0 (read once): the lamps are
    /// gathered (AddLamps) and light the dust; flames throw embers.
    [[nodiscard]] bool LampsWanted() const noexcept {
        return lamp_gain > 0.0f;
    }
    /// A G-buffer pass begins: the lamps gathered so far were another view's.
    void ClearLamps() {
        lamps.Clear();
    }
    /// One tile's light list of the game's lamp pass, as drawn (`count` records of 16 words).
    void AddLamps(const u32* records, u32 count) {
        lamps.Add(records, count);
    }
'''
APH_MEMBERS_ANCHOR = "    bool first_said = false;\n"
APH_MEMBERS_BLOCK = r'''
    // bbport (r98c_particles-visible): the lamps' block (binding 2), the lamps, and the counters
    // of the r98c line (since `window`).
    const float lamp_gain = AmbientMotes::LampGain();
    vk::Buffer lamp_buffer{};
    VmaAllocation lamp_allocation{};
    AmbientMotes::LampSet lamps;
    struct LampWindow {
        u32 frames = 0;      ///< frames the lamps were updated
        u32 lit = 0;         ///< of them with a lamp in the block
        u32 lamps = 0;       ///< lamps in the block, summed
        u32 flames = 0;      ///< flames in the block, summed
        u32 most_flames = 0; ///< at most in one frame
        u32 most_listed = 0; ///< lamps the game listed, at most in one frame
        u32 left_out = 0;    ///< at most in one frame
        float reach_min = 0.0f, reach_max = 0.0f; ///< the flames' reach (m)
        /// The nearest flame of the last frame with one, back in view space (m): it must equal
        /// its lamp record's place (the r64 probe's "at="), else the embers are misplaced.
        std::array<float, 3> flame_view{};
    } lamp_window;
'''

# ---------------------------------------------------------------- vk_ambient_particles.cpp
APC_INC_ANCHOR = "#include <cstdio>\n"
APC_INC_BLOCK = "#include <algorithm> // bbport (r98c_particles-visible)\n"
APC_ONCE_ANCHOR = '                "the wind when BB_WIND=1, else a calm drift");\n'
APC_ONCE_BLOCK = r'''    // bbport (r98c_particles-visible)
    if (lamp_gain > 0.0f) {
        std::printf("Ambient particles (r98c, BB_PARTICLES_LAMPS=%.2f): dust lit by up to %u lamps "
                    "of the frame's lamp pass (forward scattering, a %.1f m halo), embers thrown by "
                    "up to %u burning flames within %.0f m (warm, a channel %.1f or more; %u slots "
                    "each, chance %.2f a life x the flame's share: none at a reach of %.0f m or "
                    "less, all from %.0f m), the lattice's embers only near them; lamps only while "
                    "an engine effect runs\n",
                    double(lamp_gain), u32(AP_MAX_LAMPS), double(AP_LAMP_HALO), u32(AP_MAX_FLAMES),
                    double(AP_SPARK_FAR1), double(AP_SPARK_BRIGHT), u32(AP_FLAME_SLOTS),
                    double(AmbientMotes::SparkBirth(knobs)), double(AP_SPARK_REACH0),
                    double(AP_SPARK_REACH1));
    } else {
        std::printf("Ambient particles (r98c): lamps off (BB_PARTICLES_LAMPS=0): the light of the "
                    "picture behind a mote only, embers anywhere (the r98b look)\n");
    }
'''
APC_DTOR_OLD = "AmbientParticles::~AmbientParticles() = default;\n"
APC_DTOR_NEW = r'''AmbientParticles::~AmbientParticles() {
    if (lamp_buffer) { // bbport (r98c_particles-visible)
        vmaDestroyBuffer(instance.GetAllocator(), lamp_buffer, lamp_allocation);
    }
}
'''
APC_BIND_OLD = r'''    const auto device = instance.GetDevice();
    const std::array bindings{
        vk::DescriptorSetLayoutBinding{0, vk::DescriptorType::eSampledImage, 1, Stages},
        vk::DescriptorSetLayoutBinding{1, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eVertex},
    };
'''
APC_BIND_NEW = r'''    const auto device = instance.GetDevice();
    // bbport (r98c_particles-visible): the lamps' block (binding 2), written in each draw's own
    // commands (vkCmdUpdateBuffer), so it lives on the GPU only.
    const VkBufferCreateInfo lamp_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(AmbientMotes::LampBlock),
        .usage = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo lamp_alloc{};
    lamp_alloc.usage = VMA_MEMORY_USAGE_AUTO;
    VkBuffer lamp_raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &lamp_ci, &lamp_alloc, &lamp_raw, &lamp_allocation,
                        nullptr) != VK_SUCCESS) {
        return false;
    }
    lamp_buffer = lamp_raw;
    const std::array bindings{
        vk::DescriptorSetLayoutBinding{0, vk::DescriptorType::eSampledImage, 1, Stages},
        vk::DescriptorSetLayoutBinding{1, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eVertex},
        vk::DescriptorSetLayoutBinding{2, vk::DescriptorType::eUniformBuffer, 1,
                                       vk::ShaderStageFlagBits::eVertex},
    };
'''
APC_UPDATE_ANCHOR = "    drift.Advance(seconds, wind_on, wind);\n"
APC_UPDATE_BLOCK = r'''    // bbport (r98c_particles-visible): the lamps of this frame's lamp pass, taken into the world
    // with this camera (used and dropped here); none with BB_PARTICLES_LAMPS=0.
    AmbientMotes::LampBlock lamp_block{};
    if (lamp_gain > 0.0f && camera.valid) {
        const auto& lamp_knobs = AmbientMotes::Get();
        lamp_block = lamps.Update(camera.inv_view, seconds,
                                  lamp_gain * (lamp_knobs.show ? AmbientMotes::ShowGain : 1.0f),
                                  AmbientMotes::SparkBirth(lamp_knobs),
                                  AmbientMotes::SparkDrift(wind_on, wind));
        const auto& got = lamps.Last();
        if (got.flames > 0) {
            const bool first = lamp_window.most_flames == 0;
            lamp_window.reach_min = first ? got.reach_min : std::min(lamp_window.reach_min, got.reach_min);
            lamp_window.reach_max = std::max(lamp_window.reach_max, got.reach_max);
            const auto& v = camera.view;
            const auto& p = lamp_block.place[0];
            for (std::size_t r = 0; r < 3; ++r) {
                lamp_window.flame_view[r] =
                    v[4 * r] * p[0] + v[4 * r + 1] * p[1] + v[4 * r + 2] * p[2] + v[4 * r + 3];
            }
        }
        ++lamp_window.frames;
        lamp_window.lit += got.lamps > 0 ? 1 : 0;
        lamp_window.lamps += got.lamps;
        lamp_window.flames += got.flames;
        lamp_window.most_flames = std::max(lamp_window.most_flames, got.flames);
        lamp_window.most_listed = std::max(lamp_window.most_listed, got.listed);
        lamp_window.left_out = std::max(lamp_window.left_out, got.left_out);
    } else {
        lamps.Clear();
    }
    // The lattice's instances, then the flames' ember slots while the lamps are on.
    const u32 lamp_instances =
        AmbientMotes::Instances + (lamp_block.info[2] > 0.0f ? AmbientMotes::FlameInstances : 0u);
'''
APC_CAPTURE_OLD = r'''            [push, extent, target = frame.view, depth = frame.depth, scene = frame.scene,
             bound = *pipeline, bound_layout = *layout](vk::CommandBuffer cmd) {
'''
APC_CAPTURE_NEW = r'''            [push, extent, target = frame.view, depth = frame.depth, scene = frame.scene,
             bound = *pipeline, bound_layout = *layout, lamp_block, lamp_target = lamp_buffer,
             instances = lamp_instances](vk::CommandBuffer cmd) {
'''
APC_UPLOAD_ANCHOR = "                // The depth and the frame before the UI were written by earlier passes; the\n"
APC_UPLOAD_BLOCK = r'''                // bbport (r98c_particles-visible): this frame's lamps' block, after the last
                // frame's draw read it.
                const vk::MemoryBarrier2 to_upload{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_upload});
                cmd.updateBuffer(lamp_target, 0, sizeof(lamp_block), &lamp_block);
'''
APC_ACCESS_OLD = r'''                    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                                     vk::AccessFlagBits2::eColorAttachmentRead |
'''
APC_ACCESS_NEW = r'''                    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                                     vk::AccessFlagBits2::eUniformRead | // r98c: the lamps' block
                                     vk::AccessFlagBits2::eColorAttachmentRead |
'''
APC_WRITES_OLD = r'''                const std::array<vk::WriteDescriptorSet, 2> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[0]},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[1]},
                }};
'''
APC_WRITES_NEW = r'''                // bbport (r98c_particles-visible): binding 2, the lamps' block.
                const vk::DescriptorBufferInfo lamp_info{lamp_target, 0, sizeof(lamp_block)};
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[0]},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[1]},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eUniformBuffer, .pBufferInfo = &lamp_info},
                }};
'''
APC_DRAW_OLD = "                cmd.draw(6, AmbientMotes::Instances, 0, 0);\n"
APC_DRAW_NEW = "                cmd.draw(6, instances, 0, 0); // r98c: the lattice's, then the flames' slots\n"
APC_LINE_ANCHOR = '                    wind_on ? "with the wind" : "calm", drift.time);\n'
APC_LINE_BLOCK = r'''        // bbport (r98c_particles-visible): the lamps of the same 10 s.
        if (lamp_gain > 0.0f) {
            const double frames = lamp_window.frames > 0 ? double(lamp_window.frames) : 1.0;
            std::printf("Ambient particles (r98c): lamps in %u of %u frames, %.1f lamps and %.1f "
                        "flames a frame, at most %u flames (reach %.1f to %.1f m), at most %u lamps "
                        "listed near the camera, at most %u left out (over %u lamps or %u flames), "
                        "nearest flame at view %.2f %.2f %.2f m\n",
                        lamp_window.lit, lamp_window.frames, double(lamp_window.lamps) / frames,
                        double(lamp_window.flames) / frames, lamp_window.most_flames,
                        double(lamp_window.reach_min), double(lamp_window.reach_max),
                        lamp_window.most_listed, lamp_window.left_out, u32(AP_MAX_LAMPS),
                        u32(AP_MAX_FLAMES), double(lamp_window.flame_view[0]),
                        double(lamp_window.flame_view[1]), double(lamp_window.flame_view[2]));
        }
        lamp_window = {};
'''

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
# After r96's `flickered` (the lamps as drawn), before r107b's caustics block: r107b's and r86b's
# edits end at (or anchor on) the OnLightDraw line, which stays next to theirs.
FX_LAMPS_ANCHOR = "                    LampFlicker::On() ? LampFlickerBind(pipeline, ps, lights, tile_lights) : nullptr;\n"
FX_LAMPS_BLOCK = r'''                // bbport (r98c_particles-visible): the lamps the ambient motes take light from
                if (ambient_particles && ambient_particles->LampsWanted()) {
                    ambient_particles->AddLamps(
                        flickered ? flickered : reinterpret_cast<const u32*>(lights), tile_lights);
                }
'''
# After the drawn look's G-buffer block, the last one of the G-buffer branch: r107's caustics block
# (which ends at the drawn look's `if` line) and r86b's glass block (after the heat haze's) stay
# whole.
FX_CLEAR_ANCHOR = ("            drawn_look->OnGBufferDraw(db_desc.first, cb_descs[0].first);\n"
                   "        }\n")
FX_CLEAR_BLOCK = r'''        if (ambient_particles) { // bbport (r98c_particles-visible): the last pass's lamps only
            ambient_particles->ClearLamps();
        }
'''

# ---------------------------------------------------------------- vk_temporal_upscaler.cpp
UP_READ_OLD = "                depth_view = scene_targets.Read(camera_motion.Depth(), di).view;\n"
UP_READ_NEW = r'''                // r98c_particles-visible: read by the motes' vertex and fragment shaders
                depth_view = scene_targets
                                 .Read(camera_motion.Depth(), di,
                                       vk::PipelineStageFlagBits2::eVertexShader |
                                           vk::PipelineStageFlagBits2::eFragmentShader,
                                       vk::AccessFlagBits2::eShaderSampledRead)
                                 .view;
'''

# ---------------------------------------------------------------- tests/test_ambient_particles.cpp
T_INC_ANCHOR = "#include <limits>\n"
T_INC_BLOCK = "#include <bit>    // bbport (r98c_particles-visible)\n#include <vector> // bbport (r98c_particles-visible)\n"
T_HDR_ANCHOR = '#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles.h"\n'
T_HDR_BLOCK = '#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles_lamps.h" // r98c\n'
T_BODY_ANCHOR = '    std::printf("ambient-particles-test: %u cells, %s\\n", Instances,\n'
T_BODY_BLOCK = r'''    // f. bbport (r98c_particles-visible): the lamps (ambient_particles_lamps.h).
    {
        Expect(ParseLampGain(nullptr) == DefaultLampGain && ParseLampGain("x") == DefaultLampGain,
               "an unset or unreadable BB_PARTICLES_LAMPS is 1");
        Expect(ParseLampGain("0") == 0.0f && ParseLampGain("-1") == 0.0f &&
                   ParseLampGain("9") == MaxLampGain && ParseLampGain("0.5") == 0.5f,
               "BB_PARTICLES_LAMPS clamps to 0-4, 0 is off");
        Expect(IsFlame({1.0f, 0.5f, 0.15f}, 6.0f) && !IsFlame({1.0f, 1.0f, 1.0f}, 6.0f) &&
                   !IsFlame({0.2f, 0.4f, 1.0f}, 6.0f) && !IsFlame({1.0f, 0.5f, 0.15f}, 30.0f),
               "a warm lamp of a flame's reach is a flame; white, cold or far-reaching ones are not");
        // The r64 probe's records: the hand torch burns; the glass street lamp, a warm fill light
        // and the yellow lamps of the alley do not.
        Expect(Burns({2.6f, 1.45f, 0.65f}, 8.5f) && Burns({2.0f, 1.18f, 0.59f}, 8.0f) &&
                   !Burns({0.72f, 0.42f, 0.26f}, 6.0f) && !Burns({0.60f, 0.45f, 0.30f}, 9.0f) &&
                   !Burns({1.50f, 1.12f, 0.75f}, 9.0f),
               "a flame burns when bright and red enough");
        Expect(SparkShare(4.0f) == 0.0f && SparkShare(8.0f) == 1.0f && SparkShare(5.47f) > 0.25f &&
                   SparkShare(5.47f) < 0.35f,
               "no embers at a reach of 4 m, all from 8 m, about 0.3 for the church's chandeliers");
        const float seed = SeedOf(7);
        Expect(seed >= 0.0f && seed < 1.0f &&
                   float(std::uint32_t(seed * 16777216.0f)) == seed * 16777216.0f &&
                   SeedOf(7) != SeedOf(8),
               "a seed is a 24-bit fraction, its own for each serial");
        Expect(SparkBirth(Parse("1", nullptr, nullptr)) == SparkBirthPerDensity &&
                   SparkBirth(Parse("2", nullptr, "1")) == MaxOccupancy,
               "the ember chance follows the density, at most MaxOccupancy");
        const auto calm = SparkDrift(false, {9.0f, 9.0f, 9.0f});
        const auto windy = SparkDrift(true, {2.0f, std::numeric_limits<float>::quiet_NaN(), -1.0f});
        Expect(calm == CalmDrift && windy[0] == 2.0f * SparkWindFollow && windy[1] == 0.0f &&
                   windy[2] == -SparkWindFollow,
               "the embers go with the calm drift, or with the wind (not finite: 0)");

        const auto record = [](float x, float y, float z, float reach, float r, float g, float b) {
            std::array<std::uint32_t, 16> w{};
            const std::array<float, 7> f{x, y, z, 1.0f / (reach * reach), r, g, b};
            for (std::size_t i = 0; i < f.size(); ++i) {
                w[i] = std::bit_cast<std::uint32_t>(f[i]);
            }
            return w;
        };
        // The camera at (10, 0, 0) looking along +z: view = world - camera.
        const std::array<float, 12> inv{1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0};
        LampSet set;
        const auto torch = record(0.0f, 1.0f, 3.0f, 8.0f, 2.4f, 1.3f, 0.6f);
        const auto white = record(1.0f, 0.0f, 2.0f, 5.0f, 1.0f, 1.0f, 1.0f);
        const auto distant = record(0.0f, 0.0f, 40.0f, 6.0f, 2.4f, 1.3f, 0.6f);
        Expect(LampSet::Useful(torch.data()) && !LampSet::Useful(distant.data()),
               "a record beyond max(16 m, 7.5 m + reach) of the camera is not gathered");
        set.Add(torch.data(), 1);
        set.Add(white.data(), 1);
        set.Add(distant.data(), 1);
        set.Add(torch.data(), 1); // one lamp in two tiles
        LampBlock b = set.Update(inv, 0.1, 1.0f, 0.5f, {0.06f, 0.0f, 0.04f});
        Expect(b.info[0] == 2.0f && b.info[1] == 1.0f && b.info[2] == 1.0f && b.info[3] == 0.5f &&
                   set.Last().listed == 2,
               "two lamps (one listed twice, a far one skipped), one flame, the gain and the chance");
        Expect(b.place[0][0] == 10.0f && b.place[0][1] == 1.0f && b.place[0][2] == 3.0f &&
                   Near(b.place[0][3], 8.0, 1e-4) && b.place[1][0] == 11.0f,
               "the flame first, then the lamp, in the world");
        Expect(Near(b.colour[0][3], 0.1 / LampSet::FadeIn, 1e-6) && b.colour[1][1] == 1.0f,
               "a new lamp fades in; the colour as drawn");
        Expect(b.flame[0][0] == SeedOf(1) && b.flame[0][1] == SparkShare(8.0f) * b.colour[0][3] &&
                   b.flame[1][1] == 0.0f,
               "the flame's seed and share; no flame in the next slot");
        Expect(b.wind[0] == 0.06f && b.wind[2] == 0.04f, "the embers' drift");
        // Listed again a little moved and dimmed by its flicker below the bright limit: the same
        // lamp (its seed stays), still burning.
        const auto moved = record(0.05f, 1.0f, 3.0f, 8.0f, 1.1f, 0.6f, 0.28f);
        set.Add(moved.data(), 1);
        b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == 2.0f && b.info[1] == 1.0f && b.flame[0][0] == SeedOf(1) &&
                   Near(b.place[0][0], 10.05, 1e-5) && set.Kept() == 2,
               "a lamp listed again near its place is the same lamp, and it keeps burning");
        // Unlisted: held for Hold s (still fading in), then fading out over FadeOut s, then gone.
        for (int i = 0; i < 5; ++i) {
            b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        }
        Expect(b.info[0] == 2.0f && b.colour[0][3] == 1.0f, "held while unlisted");
        for (int i = 0; i < 20; ++i) {
            b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        }
        Expect(b.info[0] == 0.0f && set.Kept() == 0, "faded out and dropped");
        // More lamps than places: the flames (at most 8, nearest first), then the brightest.
        for (int i = 0; i < 12; ++i) {
            const auto flame = record(float(i) * 0.6f, 0.0f, 2.0f, 6.0f, 2.0f, 1.18f, 0.59f);
            const auto lamp = record(float(i) * 0.6f, 2.0f, 2.0f, 6.0f, 0.5f + 0.1f * float(i),
                                     0.5f + 0.1f * float(i), 0.5f + 0.1f * float(i));
            set.Add(flame.data(), 1);
            set.Add(lamp.data(), 1);
        }
        b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == float(AP_MAX_LAMPS) && b.info[1] == float(AP_MAX_FLAMES) &&
                   set.Last().left_out == std::uint32_t(24 - AP_MAX_LAMPS) && b.place[0][0] == 10.0f,
               "16 lamps in the block, the 8 nearest flames first");
        // A warp: all forgotten.
        const std::array<float, 12> away{1, 0, 0, 500, 0, 1, 0, 0, 0, 0, 1, 0};
        b = set.Update(away, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == 0.0f && set.Kept() == 0, "a camera jump forgets the lamps");
        // A candle (bright, reach 2 m: no share of embers) lights the dust but takes no flame slot.
        LampSet candles;
        const auto candle = record(0.0f, 0.0f, 2.0f, 2.0f, 2.67f, 1.83f, 0.96f);
        candles.Add(candle.data(), 1);
        b = candles.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(Burns({2.67f, 1.83f, 0.96f}, 2.0f) && b.info[0] == 1.0f && b.info[1] == 0.0f &&
                   b.flame[0][1] == 0.0f,
               "a flame with no share of embers is a lamp, not a flame slot");
        Expect(sizeof(LampBlock) == AP_LAMP_BLOCK_BYTES && FlameInstances == 128u,
               "the block's bytes and the flames' instances");
    }

'''

# ---------------------------------------------------------------- README.md
README_1080_OLD = "With a 1920x1080 output, or with `BB_UPSCALER=none`, nothing is drawn."
README_1080_NEW = ("With a 1920x1080 output (the launcher then sets no render size, so neither place is "
                   "reached), or with `BB_UPSCALER=none`, nothing is drawn.")
README_LOOK_OLD = "a mote takes its light from the picture behind it, so it shows where there is light and fades in the dark."
README_LOOK_NEW = ("a mote takes its light from the picture behind it and from the lamps near it "
                   "(`BB_PARTICLES_LAMPS`), so it shows where there is light and fades in the dark; "
                   "flames throw embers.")
README_EMBERS_OLD = "| `BB_PARTICLES_EMBERS` | Share of the motes that are embers, 0 to 1 | `0.08` |"
README_EMBERS_NEW = ("| `BB_PARTICLES_EMBERS` | Share of the motes that are embers, 0 to 1; with the lamps' "
                     "light on (`BB_PARTICLES_LAMPS` above 0) only near a flame that throws embers (in full "
                     "within 1.5 m of it, none beyond 4 m, times its share) | `0.08` |")
README_LAMPS_ROW = ("| `BB_PARTICLES_LAMPS` | The lamps' light on the dust, times this, 0 to 4; unset or "
                    "unreadable is 1; 0 turns it off (the look before it: the light of the picture behind a "
                    "mote only, embers anywhere, no lamp gathered). The lamps are the lights of the game's lamp "
                    "pass as drawn (the last G-buffer pass's), gathered only while the engine's effects pass "
                    "runs (one of its effects on, such as GTAO; with all of them off no lamp lights the dust "
                    "and no flame throws embers) and only within max(16 m, 7.5 m + reach) of the camera, each "
                    "kept once, fading in over 0.5 s and out over "
                    "0.6 s once unlisted for 1 s. Up to 16 light the dust: the flames first, then the lamps that "
                    "reach the motes' 7.5 m, the brightest for their distance first; a lamp's colour times "
                    "(1 - distance / reach)^2, times 1 / (1 + (distance / 1.5 m)^2), times forward scattering "
                    "(Henyey-Greenstein 0.45: 1 from the side, 0.43 with the lamp behind the camera, at most 3 "
                    "with the lamp behind the mote), times 1.5 and this gain (2.5 times more with "
                    "`BB_PARTICLES_SHOW=1`), its largest channel taken as 1 - exp(-light) with the hue kept, "
                    "display-encoded, twinkling slowly "
                    "down to 0.65; the picture behind a mote then counts less, down to half where the lamp light "
                    "on it reaches 0.5 in a channel (no lamp light on it: as without the lamps), and a lit "
                    "mote's colour is scaled down, hue kept, until no channel passes 0.85. Up to 8 are burning flames that throw embers (a warm "
                    "colour with one channel 1.2 or more and blue at most 0.45 of red, a reach of 0.5 to 20 m, "
                    "a share of embers above 0; once burning, for as long as the lamp is kept; the nearest "
                    "within 16 m): 16 slots each, a slot burning lives of 1.2 to 2.6 s, each "
                    "with the chance 0.5 x density (x 1.6 with `BB_PARTICLES_SHOW=1`, at most 0.9) x the "
                    "flame's share (none at a reach of 4 m or less, all from 8 m); an ember starts on a disc "
                    "around the lamp (0.02 x reach, 0.05 to 0.25 m), rises at 0.45 to 0.95 m/s (its height "
                    "rise x seconds x (1 - 0.35 x its age)), swirls, goes with the calm drift or the wind "
                    "(`BB_WIND=1`), cools from orange to red and is seen up to 16 m (in full to 10 m). The log "
                    "says it once when on, and every 10 s `Ambient particles (r98c): lamps in <n> of <m> "
                    "frames` with the lamps and flames a frame, the flames' reach and the nearest flame's place "
                    "in view space. Cost: 128 more instances "
                    "(most end after one hash), a loop over at most 16 lamps at 2 of the 6 corners of each "
                    "dust mote on screen, a 672-byte upload a frame; an estimate under 0.02 ms more, not "
                    "measured. With 0 no lamp is gathered and no ember instance is drawn | `1` |\n")

# (kind, old or anchor, new or block): "replace" old by new; "after"/"before": the block goes
# right after/before the anchor.
EDITS = {
    H + "ambient_particles_layout.h": [("after", LAYOUT_ANCHOR, LAYOUT_BLOCK)],
    H + "ambient_particles.vert": [
        ("after", VERT_HEAD_ANCHOR, VERT_HEAD_BLOCK),
        ("after", VERT_BIND_ANCHOR, VERT_BIND_BLOCK),
        ("replace", VERT_MAIN_OLD, VERT_MAIN_NEW),
        ("replace", VERT_COLOUR_OLD, VERT_COLOUR_NEW),
    ],
    R + "vk_ambient_particles.h": [
        ("replace", APH_DOC_OLD, APH_DOC_NEW),
        ("after", APH_INC1_ANCHOR, APH_INC1_BLOCK),
        ("after", APH_INC2_ANCHOR, APH_INC2_BLOCK),
        ("after", APH_API_ANCHOR, APH_API_BLOCK),
        ("after", APH_MEMBERS_ANCHOR, APH_MEMBERS_BLOCK),
    ],
    R + "vk_ambient_particles.cpp": [
        ("before", APC_INC_ANCHOR, APC_INC_BLOCK),
        ("after", APC_ONCE_ANCHOR, APC_ONCE_BLOCK),
        ("replace", APC_DTOR_OLD, APC_DTOR_NEW),
        ("replace", APC_BIND_OLD, APC_BIND_NEW),
        ("after", APC_UPDATE_ANCHOR, APC_UPDATE_BLOCK),
        ("replace", APC_CAPTURE_OLD, APC_CAPTURE_NEW),
        ("before", APC_UPLOAD_ANCHOR, APC_UPLOAD_BLOCK),
        ("replace", APC_ACCESS_OLD, APC_ACCESS_NEW),
        ("replace", APC_WRITES_OLD, APC_WRITES_NEW),
        ("replace", APC_DRAW_OLD, APC_DRAW_NEW),
        ("after", APC_LINE_ANCHOR, APC_LINE_BLOCK),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("after", FX_LAMPS_ANCHOR, FX_LAMPS_BLOCK),
        ("after", FX_CLEAR_ANCHOR, FX_CLEAR_BLOCK),
    ],
    R + "vk_temporal_upscaler.cpp": [("replace", UP_READ_OLD, UP_READ_NEW)],
    "engine/tests/test_ambient_particles.cpp": [
        ("after", T_INC_ANCHOR, T_INC_BLOCK),
        ("after", T_HDR_ANCHOR, T_HDR_BLOCK),
        ("before", T_BODY_ANCHOR, T_BODY_BLOCK),
    ],
    "README.md": [
        ("replace", README_1080_OLD, README_1080_NEW),
        ("replace", README_LOOK_OLD, README_LOOK_NEW),
        # The new row goes right after the embers row (inside this one edit): r110 inserts its rows
        # after the BB_PARTICLES_SHOW row, which stays untouched and next to them.
        ("replace", README_EMBERS_OLD, README_EMBERS_NEW + "\n" + README_LAMPS_ROW.rstrip("\n")),
    ],
}

# After apply each file holds these texts this many times.
CHECKS = {
    R + "vk_ambient_particles.cpp": [(TAG, 8), ("lamp_block", 8), ("cmd.draw(6, instances, 0, 0);", 1),
                                     ("AmbientMotes::Instances, 0, 0", 0)],
    R + "vk_ambient_particles.h": [(TAG, 5), ("AmbientMotes::LampSet lamps;", 1)],
    R + "vk_rasterizer_effects.cpp": [(TAG, 2), ("ambient_particles->AddLamps(", 1),
                                      ("ambient_particles->ClearLamps();", 1)],
    R + "vk_temporal_upscaler.cpp": [("scene_targets.Read(camera_motion.Depth(), di).view", 0),
                                     ("after_upscale(", 3)],
    H + "ambient_particles_layout.h": [("#define AP_LAMP_BLOCK_BYTES 672\n", 1), ("#define AP_MAX_LAMPS 16\n", 1),
                                       # the README's numbers (rule 7)
                                       ("#define AP_SPARK_BRIGHT 1.2\n", 1), ("#define AP_SPARK_BLUE 0.45\n", 1),
                                       ("#define AP_SPARK_REACH0 4.0\n", 1), ("#define AP_SPARK_REACH1 8.0\n", 1),
                                       ("#define AP_BACK_WITH_LAMPS 0.5\n", 1),
                                       ("#define AP_BACK_LAMP_FULL 0.5\n", 1)],
    H + "ambient_particles.vert": [("binding = 2", 1), ("lamp_info", 9), ("thrown", 7)],
    "engine/tests/test_ambient_particles.cpp": [("LampSet set;", 1)],
    "README.md": [("`BB_PARTICLES_LAMPS`", 3),
                  ("one channel 1.2 or more and blue at most 0.45 of red", 1),
                  ("none at a reach of 4 m or less, all from 8 m", 1),
                  ("down to half where the lamp light on it reaches 0.5 in a channel", 1),
                  ("its largest channel taken as 1 - exp(-light) with the hue kept", 1),
                  ("scaled down, hue kept, until no channel passes 0.85", 1),
                  ("the nearest flame's place", 1)],
}
# Texts that must come in this order.
ORDER = {
    R + "vk_rasterizer_effects.cpp": [
        "void Rasterizer::EffectsAfterTargets(", "if (gbuffer) {", "depth_of_field->Reset();",
        "if (drawn_look_wanted) {", "ambient_particles->ClearLamps();", "    if (!effects_wanted) {",
        "void Rasterizer::EffectsBeforeBind(", "const u32* flickered =",
        "ambient_particles->AddLamps(", "caustics->AddLights(",
        "point_shadow->OnLightDraw(cb_descs[0].first"],
    R + "vk_ambient_particles.cpp": [
        "AmbientParticles::AmbientParticles(", "Ambient particles (r98c, BB_PARTICLES_LAMPS",
        "AmbientParticles::~AmbientParticles() {", "bool AmbientParticles::CreatePipeline() {",
        "vmaCreateBuffer(", "DescriptorType::eUniformBuffer, 1,", "void AmbientParticles::Draw(",
        "drift.Advance(seconds, wind_on, wind);", "lamps.Update(", "scheduler.RecordCrumb(",
        "lamp_target = lamp_buffer", "cmd.updateBuffer(lamp_target", "const vk::MemoryBarrier2 before{",
        "eUniformRead", "cmd.beginRendering(", ".pBufferInfo = &lamp_info", "cmd.draw(6, instances",
        "Ambient particles (r98c): lamps in", "nearest flame at view", "lamp_window = {};",
        "        window = now;"],
    H + "ambient_particles.vert": [
        "layout(binding = 1) uniform texture2D scene_tex;", "uniform Lamps {", "vec3 lamp_light(vec3 world)",
        "float flame_near(vec3 p)", "bool flame_ember(", "void main() {", "if (gl_InstanceIndex >= AP_LATTICE)",
        "const vec3 u = ap_unit(ap_hash(key));", "if (thrown) {", "lamp_light(world)"],
    "README.md": ["| `BB_PARTICLES_EMBERS` |", "| `BB_PARTICLES_LAMPS` |", "| `BB_PARTICLES_SHOW` |",
                  "### Wind (in development)"],
}


def pairs(path):
    out = []
    for kind, a, b in EDITS[path]:
        if kind == "replace":
            out.append((a, b))
        elif kind == "after":
            out.append((a, a + b))
        else:
            out.append((a, b + a))
    return out


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


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
    for path in EDITS:
        for old, new in pairs(path):
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: text must be ASCII with LF in the script" % path)
    for path, text in NEW_FILES.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: text must be ASCII with LF in the script" % path)


def new_file_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if raw == NEW_FILES[path]:
        return "applied"
    if "r98c_particles-visible" in raw:
        raise SystemExit("%s holds another r98c (the .fixed applied 23:14, kept as "
                         "r98c_particles-visible.applied-2314.py, or the draft): revert it with its "
                         "own script first (python -I -X utf8 r98c_particles-visible.applied-2314.py "
                         "revert), then use this script: refused" % path)
    raise SystemExit("%s exists with other content: refused" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R98C_ROOT)" % ROOT)
    plan, states = [], set()
    for path in NEW_FILES: # first: another r98c in the tree is named before any edit's state
        states.add(new_file_state(path))
    for path in EDITS:
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("%s missing: apply r98_ambient-particles and r98b first" % path)
        raw, eol, cur = load(path)
        ps = pairs(path)
        done = sum(cur.count(new) == 1 for old, new in ps)
        todo = sum(cur.count(new) == 0 and cur.count(old) == 1 for old, new in ps)
        if done == len(ps):
            state = "applied"
        elif todo == len(ps):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits present, %d could be made (mixed or changed)"
                             % (path, done, len(ps), todo))
        plan.append((path, ps, raw, eol, cur))
        states.add(state)
    if len(states) != 1:
        raise SystemExit("mixed state: some files have this patch, some not")
    state = states.pop()
    if cmd in ("check", "apply"):
        texts = {}
        for path, ps, raw, eol, cur in plan:
            if state == "clean":
                for old, new in ps:
                    if cur.count(old) != 1 or cur.count(new) != 0:
                        raise SystemExit("%s: edit text not found once: %r" % (path, old[:70]))
                    cur = cur.replace(old, new, 1)
                for old, new in ps:
                    if cur.count(new) != 1:
                        raise SystemExit("%s: edits overlap: %r" % (path, new[:70]))
            texts[path] = cur
        text_checks(texts)
        if cmd == "check":
            if state == "applied":
                print("applied (text checks pass)")
            else:
                print("not applied; would apply (%d files edited, %d edits, %d new file; text checks "
                      "on the result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
            return
        if state == "applied":
            print("already applied")
            return
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8"), raw)
                for path, ps, raw, eol, cur in plan]
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written, created = [], []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r98ctmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
            for path, text in NEW_FILES.items():
                full = os.path.join(ROOT, path)
                open(full, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
                created.append(full)
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r98ctmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            for full in created:
                os.remove(full)
            raise
        print("applied (%d files edited, %d new)" % (len(plan), len(NEW_FILES)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path, ps, raw, eol, cur in plan:
        for old, new in reversed(ps):
            if cur.count(new) != 1:
                raise SystemExit("%s: edited text not found once" % path)
            cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files, %d new removed)" % (len(outs), len(NEW_FILES)))


main()
