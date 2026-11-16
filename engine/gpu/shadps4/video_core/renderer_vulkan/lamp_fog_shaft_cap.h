// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r106_lamp-fog-shaft-cap): a hard ray budget for the lamp fog shafts (r80,
// lamp_fog_shafts.h). r80 rebuilt the shadow map of every light record every frame: up to 64 maps,
// 1,048,576 rays a frame at 128x128 (4,194,304 at 256x256). Here a map belongs to a lamp, not to a
// record index, and is kept across frames: its texels are WORLD directions (the march turns the
// direction from the light to a fog sample with the composite camera's view to world rotation) and
// hold the free distance in metres (SHAFT_FREE where the ray hit nothing), so a map made in an
// earlier frame stays right while the lamp stands still. Each frame Planner::Run decides which
// maps are built, at most MapsPerFrame(Budget(...)) of them:
//   1. a lamp in view that has no map, has moved more than Still() since its map was made, or
//      whose radius grew past ReachSlack times the map's reach, wants a fresh map; these go first,
//      the lamp with the most fog first (LampFog::Importance: near and bright first). The hunter's
//      torch and lantern move with him and so are rebuilt in every frame they move;
//   2. with maps left, at most RefreshPerFrame still lamps in view are rebuilt, the one whose map
//      is oldest first, lamps whose light can reach the hunter (camera distance below their radius
//      plus NearReach) counting NearWeight times their age (a walking hunter's shadow in the fog of
//      a still lamp lags by a few frames, not by the whole round);
//   3. a lamp that wants a map and gets none this frame (over budget) fades to the unshadowed fog
//      of the lamp fog without shafts in FadeOut seconds, reading its old map meanwhile (no pop);
//      when it gets a map it fades back in over FadeIn seconds. A lamp mapped in a frame in which
//      none of its unshadowed fog was on screen (it is new, or was out of view) starts at full
//      strength, as in r80. A standing lamp (Standing(): one of the map's own lights, which cannot
//      move) that wants a map only for having moved, by no more than SameLamp() from where its
//      map was made, keeps that map at full strength meanwhile instead of fading: the light
//      records' positions wobble while the camera moves (LampFog::Memory::SameLight's reason), so
//      in a turn whole lists of standing lamps seem to move. Among the lamps that want a map,
//      those that would fade (no map, or not such a standing lamp) go before those that keep one.
// Records whose centres lie within ShareDistance of each other (the torch's two spheres) share one
// map with the larger reach. A lamp is followed from frame to frame by its world position, within
// LampFog::Memory's SameLight distance. Lamps whose sphere lies outside the view pyramid (InView)
// want no map. Without a camera (LampFog::Camera::valid false) nothing is known about directions:
// every map is dropped and the frame's lamp fog is unshadowed.
//
// BB_LAMP_FOG_SHAFTS_RAYS (read once): the budget in map rays a frame, decimal digits only.
// Unset, empty, 0 or other text: DefaultMaps maps of the level's size (131,072 rays at 128x128,
// 524,288 at 256x256). Else limited to RaysMin..RaysMax. The maps a frame are the budget over one
// map's rays, at least 1 and at most 64; the rays a frame are at most that many maps' rays, so at
// most max(budget, one map's rays).
//
// No Vulkan here: tests/test_lamp_fog_shaft_cap.cpp builds this header alone.

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <span>
#include <vector>

#include "../host_shaders/lamp_fog_shaft_layout.h"
#include "lamp_fog_lights.h"
#include "lamp_fog_shafts.h"

namespace Vulkan::LampFogShaftCap {

inline constexpr std::uint32_t MaxMaps = LampFogShafts::MaxMaps;
static_assert(SHAFT_TABLE_RECORDS >= SHAFT_TABLE_TO_WORLD + 12 &&
              SHAFT_TABLE_JOBS >= SHAFT_TABLE_RECORDS + MaxMaps &&
              SHAFT_TABLE_WORDS == SHAFT_TABLE_JOBS + MaxMaps * SHAFT_JOB_WORDS &&
              SHAFT_JOB_WORDS >= 5 && SHAFT_LAYER_MASK + 1 >= MaxMaps);
inline constexpr std::uint32_t TableBytes = SHAFT_TABLE_WORDS * 4;
inline constexpr float Free = float(SHAFT_FREE);

/// The default budget in maps of the level's size: the torch, RefreshPerFrame still lamps and 3
/// lamps that come into view (the plan's 82k rays a frame for the torch and 4 refreshes, plus room).
inline constexpr std::uint32_t DefaultMaps = 8;
/// The knob's limits: one 128x128 map; 64 maps of 256x256 (r80's every map every frame at 2).
inline constexpr std::uint64_t RaysMin = 16384, RaysMax = 4194304;
/// Still lamps rebuilt a frame at most (method D's round-robin, 4 a frame).
inline constexpr std::uint32_t RefreshPerFrame = 4;
/// Records within this distance (m, world) share one map.
inline constexpr float ShareDistance = 0.01f;
/// A lamp is still while it stays within StillBase + StillPerMetre x its camera distance (m) of
/// where its map was made: the lamp records' positions wobble a little while the camera moves, more
/// the further off they are (LampFog::Memory::SameLight's reason).
inline constexpr float StillBase = 0.05f, StillPerMetre = 0.02f;
/// A map's reach (m) still serves a radius up to this many times it.
inline constexpr float ReachSlack = 1.1f;
/// Seconds of the fade to the unshadowed fog (over budget) and back.
inline constexpr float FadeIn = 0.25f, FadeOut = 0.25f;
/// A lamp reaches the hunter when the camera is within its radius plus this (m) of its centre.
inline constexpr float NearReach = 3.0f;
inline constexpr std::uint64_t NearWeight = 4;
/// InView's slack beyond the sphere's radius, m.
inline constexpr float ViewMargin = 0.01f;

/// BB_LAMP_FOG_SHAFTS_RAYS's text: decimal digits only, at most 9 of them; anything else is 0
/// (the default).
inline std::uint64_t ParseRays(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return 0;
    }
    std::uint64_t value = 0;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (i >= 9 || text[i] < '0' || text[i] > '9') {
            return 0;
        }
        value = value * 10 + std::uint64_t(text[i] - '0');
    }
    return value;
}

/// BB_LAMP_FOG_SHAFTS_RAYS, read once.
inline std::uint64_t Rays() {
    static const std::uint64_t rays = ParseRays(std::getenv("BB_LAMP_FOG_SHAFTS_RAYS"));
    return rays;
}

/// Rays of one map of the level (one per texel); 0 when off.
inline constexpr std::uint64_t RaysPerMap(std::uint32_t level) {
    return std::uint64_t(LampFogShafts::MapSize(level)) * LampFogShafts::MapSize(level);
}

/// The budget in rays a frame for the knob's parsed value (0: the default).
inline constexpr std::uint64_t Budget(std::uint64_t parsed, std::uint32_t level) {
    return parsed == 0 ? DefaultMaps * RaysPerMap(level) : std::clamp(parsed, RaysMin, RaysMax);
}

/// Maps built a frame at most: the budget over one map's rays, at least 1, at most MaxMaps; 0 off.
inline constexpr std::uint32_t MapsPerFrame(std::uint64_t budget, std::uint32_t level) {
    const std::uint64_t per = RaysPerMap(level);
    return per == 0 ? 0u : std::uint32_t(std::clamp<std::uint64_t>(budget / per, 1, MaxMaps));
}

/// lamp_fog_shaft_map.comp's push constants.
struct MapPush {
    std::uint32_t count = 0;   ///< map jobs this frame (layers written)
    std::uint32_t mask = 0;    ///< the scene's instance mask
    float clearance = 0.0f;    ///< the blind sphere at the centre, m (at most half the reach)
    float pad = 0.0f;
    std::array<float, 12> to_view{}; ///< world to view, 3x4 rows (the translation is not used)
};
static_assert(sizeof(MapPush) == 64);

/// One map to build: the light's centre in this frame's view space, the reach (m), the layer.
struct Job {
    std::array<float, 3> centre{};
    float reach = 0.0f;
    std::uint32_t layer = 0;
};

/// A frame's decision.
struct Plan {
    std::vector<std::uint32_t> entries; ///< a word per record (SHAFT_TABLE_RECORDS)
    std::vector<Job> jobs;              ///< the maps built this frame, at most the frame's maps
    std::uint32_t fresh = 0;  ///< lamps in view with a map built this frame
    std::uint32_t reused = 0; ///< lamps in view drawn with a map of an earlier frame
    std::uint32_t over = 0;   ///< lamps in view that wanted a map and got none (over budget)
    bool camera = true;       ///< false: no camera, nothing shadowed
};

/// A record's table word: the layer and the strength (0 to 1 as 16 bits); 0 when unshadowed.
inline std::uint32_t Entry(std::uint32_t layer, float strength) {
    const float s = std::clamp(strength, 0.0f, 1.0f);
    const auto q = std::uint32_t(std::lround(double(s) * 65535.0));
    return q == 0 ? 0u : (layer & SHAFT_LAYER_MASK) | (q << 16);
}

/// Whether a sphere (view space) meets the view pyramid: the four planes through the camera and
/// the screen's edges, from the inverse projection (point_volumetric.comp's words 0-15: the rows
/// of the matrix that takes (x, y, depth, 1) to view space; corners at x, y = -1 or 1, depth 0.5).
/// True when a corner or the centre does not come out finite and in front of the camera.
inline bool InView(std::span<const float, 16> m, const std::array<float, 3>& c, float radius) {
    const auto point = [&](float x, float y, std::array<float, 3>& out) {
        const std::array<float, 4> v{x, y, 0.5f, 1.0f};
        std::array<float, 4> h{};
        for (std::size_t i = 0; i < 4; ++i) {
            h[i] = m[4 * i] * v[0] + m[4 * i + 1] * v[1] + m[4 * i + 2] * v[2] + m[4 * i + 3] * v[3];
        }
        if (!(std::abs(h[3]) >= 1e-8f)) {
            return false;
        }
        out = {h[0] / h[3], h[1] / h[3], h[2] / h[3]};
        return std::isfinite(out[0]) && std::isfinite(out[1]) && std::isfinite(out[2]) &&
               out[2] > 0.0f;
    };
    const std::array<float, 4> xs{-1.0f, 1.0f, 1.0f, -1.0f}, ys{-1.0f, -1.0f, 1.0f, 1.0f};
    std::array<std::array<float, 3>, 4> corner{};
    std::array<float, 3> middle{};
    for (std::size_t i = 0; i < 4; ++i) {
        if (!point(xs[i], ys[i], corner[i])) {
            return true;
        }
    }
    if (!point(0.0f, 0.0f, middle)) {
        return true;
    }
    for (std::size_t i = 0; i < 4; ++i) {
        const auto& a = corner[i];
        const auto& b = corner[(i + 1) % 4];
        std::array<float, 3> n{a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                               a[0] * b[1] - a[1] * b[0]};
        const float length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
        const float side = n[0] * middle[0] + n[1] * middle[1] + n[2] * middle[2];
        if (!(length > 0.0f) || side == 0.0f || !std::isfinite(side)) {
            return true;
        }
        const float sign = side > 0.0f ? -1.0f : 1.0f; // the normal points out of the pyramid
        const float outside = sign * (n[0] * c[0] + n[1] * c[1] + n[2] * c[2]) / length;
        if (outside > radius + ViewMargin) {
            return false;
        }
    }
    return true;
}

/// Where a lamp counts as still: within this of where its map was made (m).
inline float Still(float camera_distance) {
    return StillBase + StillPerMetre * camera_distance;
}

/// How far a lamp may be from where it was last frame and still be the same lamp (m).
inline float SameLamp(float camera_distance) {
    return LampFog::Memory::SameLight + LampFog::Memory::SameLightPerMetre * camera_distance;
}

/// One of the map's own lights (word 7 at least LampFog::Memory::MapLightWord; the lights the game
/// spawns, torches and lanterns among them, have 1 or less): it stands where it is.
inline bool Standing(const LampFog::Light& light) {
    return std::bit_cast<float>(light[7]) >= LampFog::Memory::MapLightWord;
}

/// The table both passes read: the view to world rows, a word per record, the jobs.
inline std::vector<std::uint32_t> MakeTable(const Plan& plan,
                                            const std::array<float, 12>& view_to_world) {
    std::vector<std::uint32_t> table(SHAFT_TABLE_WORDS, 0u);
    for (std::size_t i = 0; i < view_to_world.size(); ++i) {
        table[SHAFT_TABLE_TO_WORLD + i] = std::bit_cast<std::uint32_t>(view_to_world[i]);
    }
    for (std::size_t k = 0; k < plan.entries.size() && k < MaxMaps; ++k) {
        table[SHAFT_TABLE_RECORDS + k] = plan.entries[k];
    }
    for (std::size_t j = 0; j < plan.jobs.size() && j < MaxMaps; ++j) {
        const std::size_t at = SHAFT_TABLE_JOBS + j * SHAFT_JOB_WORDS;
        const Job& job = plan.jobs[j];
        for (std::size_t i = 0; i < 3; ++i) {
            table[at + i] = std::bit_cast<std::uint32_t>(job.centre[i]);
        }
        table[at + 3] = std::bit_cast<std::uint32_t>(job.reach);
        table[at + 4] = job.layer;
    }
    return table;
}

/// The 600-frame line's sums (VolumetricLight's r106 line).
struct Totals {
    std::uint64_t frames = 0, rays = 0, rays_most = 0, fresh = 0, reused = 0, over = 0;
    std::uint64_t no_camera = 0;
    std::uint32_t over_most = 0;
    void Add(const Plan& plan, std::uint64_t rays_per_map) {
        const std::uint64_t cast = std::uint64_t(plan.jobs.size()) * rays_per_map;
        ++frames;
        rays += cast;
        rays_most = std::max(rays_most, cast);
        fresh += plan.fresh;
        reused += plan.reused;
        over += plan.over;
        over_most = std::max(over_most, plan.over);
        no_camera += plan.camera ? 0 : 1;
    }
};

/// The lamps' maps from frame to frame (one per layer).
class Planner {
public:
    void Clear() {
        slots = {};
    }

    /// One frame: `lights` the lamp fog's records (view space, at most MaxMaps are looked at),
    /// `inverse_projection` its words 0-15 as floats, `seconds` since the last frame (for the
    /// fades), `maps` the maps this frame may build (MapsPerFrame).
    Plan Run(std::span<const LampFog::Light> lights, const LampFog::Camera& camera,
             std::span<const float, 16> inverse_projection, float seconds, std::uint32_t maps) {
        ++frame;
        const std::size_t n = std::min<std::size_t>(lights.size(), MaxMaps);
        Plan plan;
        plan.entries.assign(n, 0u);
        if (!camera.valid || maps == 0) {
            plan.camera = camera.valid;
            Clear();
            return plan;
        }
        seconds = std::isfinite(seconds) ? std::clamp(seconds, 0.0f, 1.0f) : 0.0f;
        struct Info {
            std::array<float, 3> view{}, world{};
            float radius = 0.0f, distance = 0.0f, importance = 0.0f;
            bool visible = false, standing = false;
            int slot = -1;
        };
        std::vector<Info> info(n);
        std::vector<std::size_t> order;
        order.reserve(n);
        for (std::size_t k = 0; k < n; ++k) {
            Info& r = info[k];
            r.importance = LampFog::Importance(lights[k]);
            if (!(r.importance > 0.0f)) {
                continue; // the march skips it or no view ray meets it
            }
            for (std::size_t i = 0; i < 3; ++i) {
                r.view[i] = std::bit_cast<float>(lights[k][i]);
            }
            r.radius = 1.0f / std::sqrt(std::bit_cast<float>(lights[k][3]));
            r.world = Transform(camera.view_to_world, r.view);
            r.distance = std::sqrt(DistanceSquared(r.view, {0.0f, 0.0f, 0.0f}));
            r.visible = InView(inverse_projection, r.view, r.radius);
            r.standing = Standing(lights[k]);
            order.push_back(k);
        }
        std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
            return info[a].importance > info[b].importance;
        });

        // Each record to a slot, the most fog first: a record sharing a centre with one already
        // placed takes its slot; else the nearest slot of last frame within SameLamp; records left
        // over then take a free slot or the one seen longest ago (so a lamp of this frame's list
        // never loses its slot to a new one).
        std::array<bool, MaxMaps> taken{}, visible{}, standing{};
        std::array<float, MaxMaps> reach{}, distance{}, importance{};
        std::array<std::size_t, MaxMaps> primary{};
        std::vector<std::size_t> placed, left_over;
        placed.reserve(n);
        const auto place = [&](std::size_t k, bool make) {
            Info& r = info[k];
            for (const std::size_t j : placed) {
                if (DistanceSquared(info[j].world, r.world) <= ShareDistance * ShareDistance) {
                    r.slot = info[j].slot;
                    const auto s = std::size_t(r.slot);
                    reach[s] = std::max(reach[s], r.radius);
                    visible[s] = visible[s] || r.visible;
                    standing[s] = standing[s] && r.standing;
                    placed.push_back(k);
                    return true;
                }
            }
            int best = -1;
            if (!make) {
                float best_distance = SameLamp(r.distance) * SameLamp(r.distance);
                for (std::size_t s = 0; s < MaxMaps; ++s) {
                    if (slots[s].used && !taken[s]) {
                        const float d = DistanceSquared(r.world, slots[s].seen);
                        if (d <= best_distance) {
                            best = int(s);
                            best_distance = d;
                        }
                    }
                }
                if (best < 0) {
                    return false;
                }
            } else {
                for (std::size_t s = 0; s < MaxMaps; ++s) {
                    if (taken[s]) {
                        continue;
                    }
                    if (!slots[s].used) {
                        best = int(s);
                        break;
                    }
                    if (best < 0 || slots[s].seen_frame < slots[std::size_t(best)].seen_frame) {
                        best = int(s);
                    }
                }
                if (best < 0) {
                    return false; // cannot happen: at most MaxMaps records take slots
                }
                slots[std::size_t(best)] = Slot{};
                slots[std::size_t(best)].used = true;
            }
            const auto s = std::size_t(best);
            taken[s] = true;
            r.slot = best;
            slots[s].seen = r.world;
            slots[s].seen_frame = frame;
            reach[s] = r.radius;
            distance[s] = r.distance;
            importance[s] = r.importance;
            visible[s] = r.visible;
            standing[s] = r.standing;
            primary[s] = k;
            placed.push_back(k);
            return true;
        };
        for (const std::size_t k : order) {
            if (!place(k, false)) {
                left_over.push_back(k);
            }
        }
        for (const std::size_t k : left_over) {
            place(k, true);
        }

        // Which maps are built: first the lamps that want one, the most fog first, those that would
        // fade before the standing lamps that keep their map meanwhile (`keeps`); then still
        // lamps, oldest map first (near lamps NearWeight times their age).
        std::vector<std::size_t> wants, still;
        std::array<bool, MaxMaps> keeps{};
        for (std::size_t s = 0; s < MaxMaps; ++s) {
            if (!taken[s] || !visible[s]) {
                continue;
            }
            const Slot& slot = slots[s];
            const float moved = DistanceSquared(slot.seen, slot.built);
            const bool fresh_wanted = !slot.has_map ||
                                      moved > Still(distance[s]) * Still(distance[s]) ||
                                      reach[s] > slot.reach * ReachSlack;
            keeps[s] = fresh_wanted && slot.has_map && standing[s] &&
                       moved <= SameLamp(distance[s]) * SameLamp(distance[s]);
            (fresh_wanted ? wants : still).push_back(s);
        }
        std::stable_sort(wants.begin(), wants.end(), [&](std::size_t a, std::size_t b) {
            return keeps[a] != keeps[b] ? keeps[b] : importance[a] > importance[b];
        });
        const auto priority = [&](std::size_t s) {
            const std::uint64_t age = frame - slots[s].built_frame;
            return age * (distance[s] < reach[s] + NearReach ? NearWeight : 1);
        };
        std::stable_sort(still.begin(), still.end(), [&](std::size_t a, std::size_t b) {
            const std::uint64_t pa = priority(a), pb = priority(b);
            return pa != pb ? pa > pb : importance[a] > importance[b];
        });
        std::array<bool, MaxMaps> built{}, over{};
        std::size_t left = maps;
        for (const std::size_t s : wants) {
            if (left > 0) {
                built[s] = true;
                --left;
            } else {
                over[s] = true;
            }
        }
        std::size_t refresh = std::min<std::size_t>(left, RefreshPerFrame);
        for (const std::size_t s : still) {
            if (refresh == 0) {
                break;
            }
            built[s] = true;
            --refresh;
        }

        for (std::size_t s = 0; s < MaxMaps; ++s) {
            Slot& slot = slots[s];
            if (!taken[s] || !visible[s]) {
                slot.unshadowed_shown = false;
                continue;
            }
            if (built[s]) {
                plan.jobs.push_back({info[primary[s]].view, reach[s], std::uint32_t(s)});
                slot.strength =
                    slot.unshadowed_shown ? std::min(1.0f, slot.strength + seconds / FadeIn) : 1.0f;
                slot.has_map = true;
                slot.built = slot.seen;
                slot.reach = reach[s];
                slot.built_frame = frame;
                ++plan.fresh;
            } else if (!slot.has_map) {
                slot.strength = 0.0f;
                ++plan.over;
            } else if (over[s]) {
                // a standing lamp that only seems to have moved keeps its map (`keeps`)
                slot.strength = keeps[s] ? std::min(1.0f, slot.strength + seconds / FadeIn)
                                         : std::max(0.0f, slot.strength - seconds / FadeOut);
                ++plan.over;
            } else {
                slot.strength = std::min(1.0f, slot.strength + seconds / FadeIn);
            }
            if (!built[s] && slot.has_map && slot.strength > 0.0f) {
                ++plan.reused;
            }
            slot.unshadowed_shown = slot.strength < 1.0f;
        }
        for (std::size_t k = 0; k < n; ++k) {
            if (info[k].slot >= 0) {
                const Slot& slot = slots[std::size_t(info[k].slot)];
                plan.entries[k] = slot.has_map ? Entry(std::uint32_t(info[k].slot), slot.strength)
                                               : 0u;
            }
        }
        return plan;
    }

private:
    struct Slot {
        bool used = false, has_map = false;
        bool unshadowed_shown = false; ///< last frame in view with a strength below 1
        std::array<float, 3> seen{};   ///< world position last frame
        std::array<float, 3> built{};  ///< world position when its map was made
        float reach = 0.0f, strength = 0.0f;
        std::uint64_t built_frame = 0, seen_frame = 0;
    };

    static std::array<float, 3> Transform(const std::array<float, 12>& m,
                                          const std::array<float, 3>& p) {
        return {m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
                m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
                m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]};
    }

    static float DistanceSquared(const std::array<float, 3>& a, const std::array<float, 3>& b) {
        const float x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2];
        return x * x + y * y + z * z;
    }

    std::array<Slot, MaxMaps> slots{};
    std::uint64_t frame = 0;
};

} // namespace Vulkan::LampFogShaftCap
