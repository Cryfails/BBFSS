// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r98e_moths-at-lamps): moths round the lit lamps, without Vulkan (tests/test_ambient_particles.cpp
// builds it alone; vk_ambient_particles.cpp uses it, ambient_particles.vert draws them).
//
// The ambient motes' lamp block (ambient_particles_lamps.h: the lamps near the camera, the flames
// first) gets one more vec4 a lamp slot, LampBlock::moth: x how many moths fly round it (0 to
// AP_MOTH_SLOTS, a fraction fades the last one in or out), y the lamp's seed (set by LampSet), z the
// loop's scale from the lamp's reach, w the calm of the air at the camera (1 - the air share of
// r98d). The shader draws AP_MOTH_SLOTS instances a lamp slot after the flames' ember instances and
// flies each moth round its lamp (moth_world).
//
// Which lamps get moths (MothSet::Apply): lit lamps and flames of the block with a weight above 0
// that IsMothLight (warm or white, some light, a reach of MothReachMin to MothReachMax: candles, wall
// lanterns and street lamps; the hunter's torch has reach 8.4 to 8.6 and the big fill lights 9), nearer
// than AP_MOTH_FAR1 m to the camera, not within MothHunterNear m of the hunter's chest (a light he
// carries). The nearest AP_MOTH_LAMPS of them (ties: by seed) carry moths; each lamp's presence follows
// its target (1 chosen, 0 not) over MothFadeIn / MothFadeOut s, so a lamp that enters or leaves the
// nearest few fades its moths in or out instead of popping them.
//
// Knob BB_PARTICLES_MOTHS (read once): 0 or unset or unreadable: off; 1: MothCount 2 to 4 a lamp;
// 2 (above counts as 2): 3 to 6 a lamp. Needs BB_PARTICLES above 0 and the lamps (BB_PARTICLES_LAMPS
// above 0, an engine effect running).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "../host_shaders/ambient_particles_layout.h"
#include "ambient_particles.h"
#include "ambient_particles_lamps.h"

namespace Vulkan::AmbientMotes {

inline constexpr int MaxMothLevel = 2;
inline constexpr float MothFadeIn = 0.8f;      ///< s: a lamp's moths come in over this
inline constexpr float MothFadeOut = 0.8f;     ///< s: and go over this
inline constexpr float MothHunterNear = 1.5f;  ///< m: a lamp this near the hunter's chest is carried
inline constexpr float MothHunterChest = 1.0f; ///< m above the physics position
inline constexpr float MothReachMin = 1.0f;    ///< m: a lamp's reach, at least
inline constexpr float MothReachMax = 7.5f;    ///< m: and at most (the hand torch is 8.4 to 8.6)
inline constexpr float MothMinLuma = 0.08f;    ///< the lamp's colour luminance, at least
inline constexpr float MothBlueMax = 1.3f;     ///< blue at most this times red (no cold lights)
inline constexpr float MothScaleReach = 6.0f;  ///< m: a lamp of this reach has loops of scale 1
inline constexpr float MothScaleMin = 0.5f, MothScaleMax = 1.3f;
static_assert(AP_MOTH_SLOTS >= 6, "the densest level flies 6 moths a lamp");
static_assert(AP_MOTH_LAMPS >= 1 && AP_MOTH_LAMPS <= AP_MAX_LAMPS, "the cap is a count of lamp slots");
static_assert(AP_MOTH_FAR0 < AP_MOTH_FAR1);
static_assert(std::uint32_t(AP_MOTH_INSTANCES) == std::uint32_t(AP_MAX_LAMPS) * AP_MOTH_SLOTS,
              "one set of instances a lamp slot");

/// BB_PARTICLES_MOTHS's text as the level: unset, empty, unreadable, not finite, or under 0.5: 0
/// (off); 0.5 up to 1.5: 1; from 1.5: 2.
inline int ParseMothLevel(const char* text) {
    const float v = Number(text, 0.0f);
    return v >= 1.5f ? 2 : (v >= 0.5f ? 1 : 0);
}

/// BB_PARTICLES_MOTHS, read once.
inline int MothLevel() {
    static const int level = ParseMothLevel(std::getenv("BB_PARTICLES_MOTHS"));
    return level;
}

/// How many moths a lamp with seed `seed` (0..1) has at `level`: 2 to 4 at level 1, 3 to 6 at level 2,
/// 0 at level 0 (or below).
inline int MothCount(int level, float seed) {
    if (level <= 0) {
        return 0;
    }
    const int lo = level >= 2 ? 3 : 2, hi = level >= 2 ? 6 : 4;
    const float s = std::isfinite(seed) ? std::clamp(seed, 0.0f, 1.0f) : 0.0f;
    std::uint32_t h = std::uint32_t(s * 16777215.0f) * 2654435761u;
    h ^= h >> 15;
    h *= 2246822519u;
    h ^= h >> 13;
    const float f = float(h >> 8) / 16777216.0f;
    return std::clamp(lo + int(f * float(hi - lo + 1)), lo, hi);
}

/// A lit lamp or flame that moths go to: its colour (as the block holds it, at most 4 a channel) warm
/// or white with some light, its reach MothReachMin to MothReachMax m. Not finite: no.
inline bool IsMothLight(const std::array<float, 4>& colour, float reach) {
    const float r = colour[0], g = colour[1], b = colour[2];
    if (!std::isfinite(r) || !std::isfinite(g) || !std::isfinite(b) || !std::isfinite(reach)) {
        return false;
    }
    return r > 0.0f && g >= 0.0f && b >= 0.0f && b <= MothBlueMax * r &&
           0.2126f * r + 0.7152f * g + 0.0722f * b >= MothMinLuma && reach >= MothReachMin &&
           reach <= MothReachMax;
}

/// A lamp (`place` xyz) held by the hunter: within MothHunterNear m of his chest (`hunter` is the
/// physics position, y up).
inline bool NearHunter(const std::array<float, 4>& place, const std::array<float, 3>& hunter) {
    const float x = place[0] - hunter[0], y = place[1] - (hunter[1] + MothHunterChest),
                z = place[2] - hunter[2];
    return x * x + y * y + z * z < MothHunterNear * MothHunterNear;
}

/// The loops' scale for a lamp of reach `reach` (m): reach / MothScaleReach, MothScaleMin to MothScaleMax.
inline float MothScale(float reach) {
    return std::clamp(std::isfinite(reach) ? reach / MothScaleReach : 1.0f, MothScaleMin, MothScaleMax);
}

/// What one Apply did.
struct MothStats {
    std::uint32_t candidates = 0; ///< lamps that could carry moths (lit, in range, not carried)
    std::uint32_t carried = 0;    ///< left out: within MothHunterNear m of the hunter
    std::uint32_t capped = 0;     ///< candidates over the cap of AP_MOTH_LAMPS
    std::uint32_t lamps = 0;      ///< lamps with moths in the block now (fading ones included)
    std::uint32_t shown = 0;      ///< moths drawn (a fading one counts as one)
    bool hunter_known = false;
};

class MothSet {
public:
    /// Fills `block.moth` (x moths, z scale, w calm; y, the seed, stays) for this frame's lamps (the
    /// block's first info[0] slots). `eye` the camera in the world, `hunter` his position (used when
    /// `hunter_known`), `level` BB_PARTICLES_MOTHS, `calm` 0..1 (1 - the air share: 0 in the open),
    /// `seconds` since the last call (0..MaxStep; not finite: 0). Level 0 or lamps off (info[2] not
    /// above 0): nothing, and the presences are forgotten.
    MothStats Apply(LampBlock& block, const std::array<float, 3>& eye, bool hunter_known,
                    const std::array<float, 3>& hunter, int level, float calm, double seconds) {
        MothStats stats;
        stats.hunter_known = hunter_known;
        for (std::size_t i = 0; i < std::size_t(AP_MAX_LAMPS); ++i) {
            block.moth[i][0] = 0.0f;
            block.moth[i][2] = 0.0f;
            block.moth[i][3] = 0.0f;
        }
        if (level <= 0 || !(block.info[0] >= 1.0f) || !(block.info[2] > 0.0f)) {
            seen.clear();
            return stats;
        }
        const std::size_t n = std::size_t(std::min(block.info[0], float(AP_MAX_LAMPS)));
        const float dt = std::isfinite(seconds) ? float(std::clamp(seconds, 0.0, MaxStep)) : 0.0f;
        const float calm_now = std::isfinite(calm) ? std::clamp(calm, 0.0f, 1.0f) : 0.0f;
        struct Candidate {
            std::size_t slot;
            float distance;
            float seed;
        };
        std::vector<Candidate> candidates;
        for (std::size_t i = 0; i < n; ++i) {
            const auto& place = block.place[i];
            const auto& colour = block.colour[i];
            if (!(colour[3] > 0.0f) || !IsMothLight(colour, place[3])) {
                continue;
            }
            const float x = place[0] - eye[0], y = place[1] - eye[1], z = place[2] - eye[2];
            const float distance = std::sqrt(x * x + y * y + z * z);
            if (!(distance < float(AP_MOTH_FAR1))) { // (also false for not finite)
                continue;
            }
            if (hunter_known && NearHunter(place, hunter)) {
                ++stats.carried;
                continue;
            }
            candidates.push_back({i, distance, block.moth[i][1]});
        }
        std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
            return a.distance != b.distance ? a.distance < b.distance : a.seed < b.seed;
        });
        stats.candidates = std::uint32_t(candidates.size());
        std::vector<bool> chosen(n, false);
        for (std::size_t rank = 0; rank < candidates.size(); ++rank) {
            if (rank < std::size_t(AP_MOTH_LAMPS)) {
                chosen[candidates[rank].slot] = true;
            } else {
                ++stats.capped;
            }
        }
        std::vector<Seen> next;
        next.reserve(n);
        for (std::size_t i = 0; i < n; ++i) {
            const float seed = block.moth[i][1];
            float presence = 0.0f;
            for (const Seen& s : seen) {
                if (s.seed == seed) {
                    presence = s.presence;
                }
            }
            const float target = chosen[i] ? 1.0f : 0.0f;
            presence = target > presence ? std::min(target, presence + dt / MothFadeIn)
                                         : std::max(target, presence - dt / MothFadeOut);
            if (!(presence > 0.0f)) {
                continue;
            }
            next.push_back({seed, presence});
            const float count = float(MothCount(level, seed));
            const float x = count * presence * std::clamp(block.colour[i][3], 0.0f, 1.0f);
            block.moth[i][0] = x;
            block.moth[i][2] = MothScale(block.place[i][3]);
            block.moth[i][3] = calm_now;
            ++stats.lamps;
            stats.shown += std::uint32_t(std::max(0.0f, std::ceil(x - 0.001f)));
        }
        seen.swap(next);
        return stats;
    }

    [[nodiscard]] std::size_t Remembered() const noexcept {
        return seen.size();
    }

private:
    struct Seen {
        float seed;     ///< the lamp's seed (LampSet's, 24 bits over 2^24)
        float presence; ///< 0..1
    };
    std::vector<Seen> seen;
};

/// What the 10 s line of r98e says.
struct MothWindow {
    std::uint32_t frames = 0;         ///< draws with the moths on
    std::uint32_t with_moths = 0;     ///< of them with a moth shown
    std::uint32_t carried_frames = 0; ///< with a lamp kept off by the hunter's nearness
    std::uint32_t unknown_frames = 0; ///< with the hunter's position unread
    std::uint32_t shown_sum = 0, lamps_sum = 0;
    std::uint32_t shown_max = 0, lamps_max = 0, candidates_max = 0, capped_max = 0;

    void Add(const MothStats& s) {
        ++frames;
        with_moths += s.shown > 0 ? 1u : 0u;
        carried_frames += s.carried > 0 ? 1u : 0u;
        unknown_frames += s.hunter_known ? 0u : 1u;
        shown_sum += s.shown;
        lamps_sum += s.lamps;
        shown_max = std::max(shown_max, s.shown);
        lamps_max = std::max(lamps_max, s.lamps);
        candidates_max = std::max(candidates_max, s.candidates);
        capped_max = std::max(capped_max, s.capped);
    }
    /// The line (under 320 characters: the slot runs keep that many); `window` s since the last.
    int Text(char* out, std::size_t size, double window) const {
        const double n = frames > 0 ? double(frames) : 1.0;
        return std::snprintf(out, size,
                             "Ambient particles (r98e): moths in %u of %u frames, %.1f moths on %.1f lamps a "
                             "frame (at most %u on %u; cap %u lamps), %u lamps could carry moths at most, %u "
                             "over the cap, the hunter's own light kept out in %u frames, his position "
                             "unread in %u, in %.1f s",
                             with_moths, frames, double(shown_sum) / n, double(lamps_sum) / n, shown_max,
                             lamps_max, std::uint32_t(AP_MOTH_LAMPS), candidates_max, capped_max,
                             carried_frames, unknown_frames, window);
    }
};

} // namespace Vulkan::AmbientMotes
