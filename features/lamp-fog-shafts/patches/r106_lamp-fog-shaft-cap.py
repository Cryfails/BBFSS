# r106_lamp-fog-shaft-cap: FEATURE patch (feature "lamp and torch shafts through fog", order item 3;
# branch visual/lamp-fog-shafts, on top of r80). A hard ray budget for the lamp fog shafts. Off by
# default: it acts only with BB_LAMP_FOG_SHAFTS set (r80's knob, same meaning).
#
# Why: r80 rebuilt a 128x128 shadow map for every lamp fog light record every frame: 22 lights
# 360,448 rays, 52 lights (church-candles) 851,968, 64 lights (church-lantern) 1,048,576 rays a
# frame in the r80 slot batch (4x that at BB_LAMP_FOG_SHAFTS=2). The plan (method D) keeps the
# maps of still lamps across frames and refreshes them round-robin; the owner: "Optimization should
# also be a thing we seek out with each pass through sections we are changing in the engine".
#
# What (lamp_fog_shaft_cap.h holds the rules, tested by tests/test_lamp_fog_shaft_cap.cpp):
# 1. A map belongs to a lamp, not to a record index, and is kept across frames. Its texels are
#    WORLD directions (the map pass turns them into this frame's view space with the composite
#    camera's world to view rows; the march turns the direction from the light to a fog sample with
#    the view to world rows) and keep the free distance in METRES (SHAFT_FREE where the ray hit
#    nothing), so an old map stays right while the lamp stands still, whatever the camera does.
#    Lamps are followed from frame to frame by world position (LampFog::Memory's SameLight
#    distance). Records whose centres lie within 1 cm share one map (the torch's two spheres).
# 2. BB_LAMP_FOG_SHAFTS_RAYS (read once; decimal digits; 16384 to 4194304; unset, 0 or other text:
#    8 maps of the level = 131,072 rays at 1 and 3, 524,288 at 2): the most map rays a frame. The
#    maps a frame are the budget over one map's rays (at least 1, at most 64), so the rays a frame
#    never pass max(budget, one map). Worst case with the default: 131,072 rays (8 maps of 128x128),
#    against r80's 1,048,576 at 64 lights.
# 3. Each frame (Planner::Run): lamps in view (sphere meets the view pyramid) that have no map, moved
#    more than 5 cm + 2 cm per metre of camera distance since their map, or grew past 1.1x its reach,
#    want a fresh map; they go first, the most fog first (LampFog::Importance: near and bright
#    first): the hunter's torch and lantern are rebuilt in every frame they move. Maps left over
#    rebuild up to 4 still lamps, the oldest map first (lamps whose light reaches within 3 m of the
#    camera count their age 4x: the hunter's own shadow in a still lamp's fog lags a few frames).
#    A lamp that wants a map and gets none (over budget) fades to the unshadowed fog in 0.25 s,
#    reading its old map meanwhile, and back in when it gets one (strength per record in the
#    table; the march mixes the unshadowed and shadowed light by it). Review fix: a STANDING lamp
#    (word 7 at least LampFog::Memory::MapLightWord: one of the map's own lights, which cannot
#    move) that only seems to have moved, within LampFog::Memory's SameLight distance of where its
#    map was made, keeps its map at full strength while it waits: the records' positions wobble
#    while the camera moves (lamp_fog_lights.h SameLight), so in a turn or a walk whole lists of
#    standing lamps pass the 5 cm + 2 cm/m test; without this they all faded to the unshadowed fog
#    while the camera moved. Lamps without a usable map (new ones, the torch, enemies' torches) go
#    before those waiting standing lamps. A lamp mapped while none of
#    its unshadowed fog was on screen starts at full strength, as in r80. Without a camera every map
#    is dropped and that frame's lamp fog is unshadowed (counted in the line).
# 4. GPU: a table buffer (592 words, one updateBuffer a frame next to r80's): the view to world
#    rows, a word per record (layer, strength), the frame's map jobs (centre, reach, layer). The map
#    pass dispatches only the jobs (z = jobs; none: no dispatch); the maps' image keeps its layers
#    (General layout after the first frame instead of Undefined each frame). The march (SHAFTS
#    builds only) reads the record's word: strength 0 reads no map.
# 5. Log: a once-line "Volumetric lighting (r106): lamp fog shaft cap: ..." at the first planned
#    frame; with r80's 600-frame line a line of its own (the slot runs keep 300 characters of a
#    line) "Volumetric lighting (r106): shaft cap over N frames: map rays a frame A avg, M max, cap
#    C; lamps a frame: F fresh, R reused, O over budget (X max); K frames without a camera". r80's
#    line now says "N map rays without the r106 cap" (what r80 would have cast) instead of "at most".
#
# Off (BB_LAMP_FOG_SHAFTS unset or 0): nothing of this runs or is made. Every new host statement is
# reached only through VolumetricLight::RecordShafts (called only with the knob set and a ray traced
# scene this frame) or ShaftsReady (same); the table is made in ShaftsReady. The new shader text
# is inside #ifdef SHAFTS of point_volumetric.comp: its default and WIND builds compile to the same
# bytes (checked; the SHAFTS builds and the map pass change).
#
# Picture: with the budget not hit (every lamp in view mapped) the fog is r80's within noise: same
# rays per texel, same bias (1% of the radius, now compared in metres), the texel grid in world
# directions instead of view directions (another sampling of the same shadow, no crawl while the
# camera turns), and a still lamp's map is up to its turn old (moving occluders: the hunter, enemies).
#
# Cost (NOT MEASURED; estimates at 1080p internal, RTX 4090): r80's notes put 1.05M map rays at
# 0.2-0.4 ms, so the default cap of 131,072 rays costs at most 0.025-0.05 ms a frame; a still scene
# with few lamps casts 4 maps a frame (65,536 rays, 0.012-0.025 ms) once all are mapped; the torch
# alone 1 map a frame. The march: a table read per light and pixel, and lamps without a map read no
# texel (cheaper than r80 for them). CPU: one pass over at most 64 records x 64 slots a frame
# (a few microseconds). Memory: the table 2,368 bytes; the maps unchanged (2 MB, 8 MB at 2).
#
# Files: renderer_vulkan/lamp_fog_shaft_cap.h (new), host_shaders/lamp_fog_shaft_layout.h (new),
# tests/test_lamp_fog_shaft_cap.cpp (new), host_shaders/point_volumetric.comp (SHAFTS only),
# host_shaders/lamp_fog_shaft_map.comp, renderer_vulkan/lamp_fog_shafts.h (comments),
# vk_volumetric_light.h, vk_volumetric_light.cpp, engine/gpu/CMakeLists.txt, engine/build.sh,
# tests/test_effect_pipelines.cpp, README.md.
#
# Reviewed 2026-11-15 (r106_lamp-fog-shaft-cap.fixed.py): the standing-lamp rule above, its unit test,
# the README limits and that rule, a once-line under the slot runner's 300 characters, and the r80
# comments in point_volumetric.comp and lamp_fog_shafts.h that still said "layer k for record k",
# "over the radius" and "one map per light record every frame".
#
# Use: python -I -X utf8 r106_lamp-fog-shaft-cap.fixed.py check | apply | revert
# Root: R106_ROOT, else <tree>. Line ends kept (CRLF in the tree); new files are written CRLF.
# apply backs the originals up in r106_backup next to this script; revert takes out exactly what
# apply put in (insertions are found by themselves, replacements by their new text) and removes
# the new files. Needs r80 and r88 applied (anchors on their lines).
import os, sys

ROOT = os.environ.get("R106_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r106_backup")
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
T = "engine/tests/"
P = H + "point_volumetric.comp"
M = H + "lamp_fog_shaft_map.comp"
S = R + "lamp_fog_shafts.h"
VH = R + "vk_volumetric_light.h"
VC = R + "vk_volumetric_light.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
EP = T + "test_effect_pipelines.cpp"
RM = "README.md"

NEW_FILES = {
    R + "lamp_fog_shaft_cap.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
''',
    H + "lamp_fog_shaft_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' table (VolumetricLight's shaft_table, one
// upload a frame), shared by lamp_fog_shaft_map.comp, point_volumetric.comp's SHAFTS builds and
// lamp_fog_shaft_cap.h. Plain #define lines only: the shaders include this file through
// GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds the numbers both
// sides use (as lamp_wind_layout.h does for the wind words).
#ifndef LAMP_FOG_SHAFT_LAYOUT_H
#define LAMP_FOG_SHAFT_LAYOUT_H

// Words 0-11: the composite camera's view to world matrix, 3x4 rows (the march turns the direction
// from a light to a fog sample into the maps' world directions; the translation is not used).
#define SHAFT_TABLE_TO_WORLD 0u
// Words 16-79: one word per light record k of the lamp fog's list: the map layer in the low 8 bits
// (SHAFT_LAYER_MASK), the shadow's strength 0 to 1 as 16 bits in the high half (0: the record is
// marched unshadowed and reads no map).
#define SHAFT_TABLE_RECORDS 16u
#define SHAFT_LAYER_MASK 255u
// From word 80: the frame's map jobs, SHAFT_JOB_WORDS words each: the light's centre (view space,
// this frame), the reach in metres, the layer to write; the other 3 words are 0.
#define SHAFT_TABLE_JOBS 80u
#define SHAFT_JOB_WORDS 8u
// Words in all: the jobs of 64 maps (LampFogShafts::MaxMaps) after word 80.
#define SHAFT_TABLE_WORDS 592u
// What a texel keeps where its ray hit nothing (the largest finite R16F): free to any distance.
#define SHAFT_FREE 65504.0

#endif
''',
    T + "test_lamp_fog_shaft_cap.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' ray budget (lamp_fog_shaft_cap.h): the
// knob, the budget and maps a frame, the table words, the view pyramid test, and the planner: few
// lamps are all rebuilt every frame (as r80), many never take more than the frame's maps and are
// all mapped within a few frames, still lamps then rebuild 4 a frame each in turn, a moving torch
// is rebuilt every frame, shared centres take one map, a lamp over budget fades out and back in,
// no camera shadows nothing, a lamp out of view wants no map, a turning camera rebuilds nothing,
// standing lamps that seem to move keep their maps and wait behind a new lamp (review fix).
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <map>
#include <set>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_cap.h"

using namespace Vulkan::LampFogShaftCap;

namespace {

constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
// (x, y, depth, 1) to (x, y, 1): the view pyramid |x| <= z, |y| <= z.
constexpr std::array<float, 16> Projection{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1};
constexpr float Dt = 1.0f / 60.0f;

LampFog::Light Light(float x, float y, float z, float radius, float colour = 1.0f) {
    LampFog::Light light{};
    light[0] = std::bit_cast<std::uint32_t>(x);
    light[1] = std::bit_cast<std::uint32_t>(y);
    light[2] = std::bit_cast<std::uint32_t>(z);
    light[3] = std::bit_cast<std::uint32_t>(1.0f / (radius * radius));
    for (std::size_t i = 4; i < 7; ++i) {
        light[i] = std::bit_cast<std::uint32_t>(colour);
    }
    return light;
}

LampFog::Camera Camera(const std::array<float, 12>& view_to_world, bool valid = true) {
    LampFog::Camera camera;
    camera.view_to_world = view_to_world;
    camera.valid = valid;
    return camera;
}

std::uint32_t Strength(std::uint32_t entry) {
    return entry >> 16;
}

} // namespace

int main() {
    // The knob: digits only, at most 9; anything else (and 0) is the default.
    assert(ParseRays(nullptr) == 0 && ParseRays("") == 0 && ParseRays("0") == 0);
    assert(ParseRays("131072") == 131072 && ParseRays("12x") == 0 && ParseRays("-5") == 0);
    assert(ParseRays("999999999") == 999999999 && ParseRays("1000000000") == 0);
    assert(RaysPerMap(1) == 16384 && RaysPerMap(2) == 65536 && RaysPerMap(3) == 16384 &&
           RaysPerMap(0) == 0);
    assert(Budget(0, 1) == 131072 && Budget(0, 2) == 524288 && Budget(0, 3) == 131072);
    assert(Budget(5, 1) == RaysMin && Budget(999999999, 1) == RaysMax && Budget(200000, 2) == 200000);
    assert(MapsPerFrame(131072, 1) == 8 && MapsPerFrame(524288, 2) == 8 &&
           MapsPerFrame(16384, 2) == 1 && MapsPerFrame(200000, 1) == 12);
    assert(MapsPerFrame(RaysMax, 1) == 64 && MapsPerFrame(RaysMax, 2) == 64 &&
           MapsPerFrame(131072, 0) == 0);
    // The rays a frame are at most the maps a frame times one map's rays: never more than the
    // budget, except one map when the budget is below a map.
    for (const std::uint32_t level : {1u, 2u, 3u}) {
        for (const std::uint64_t parsed : {0ull, 1ull, 16384ull, 100000ull, 131072ull, 999999ull,
                                           4194304ull, 999999999ull}) {
            const std::uint64_t budget = Budget(parsed, level);
            const std::uint64_t worst = MapsPerFrame(budget, level) * RaysPerMap(level);
            assert(worst <= std::max(budget, RaysPerMap(level)) && worst <= 64 * RaysPerMap(level));
        }
    }
    assert(sizeof(MapPush) == 64 && TableBytes == 592 * 4);

    // A record's word: the layer, the strength as 16 bits; 0 when unshadowed.
    assert(Entry(3, 1.0f) == (3u | (65535u << 16)) && Entry(3, 0.0f) == 0);
    assert(Entry(5, 0.5f) == (5u | (32768u << 16)) && Entry(7, 2.0f) == (7u | (65535u << 16)) &&
           Entry(7, -1.0f) == 0);

    // The view pyramid.
    assert(InView(Projection, {0, 0, 5}, 1) && !InView(Projection, {0, 0, -5}, 1));
    assert(!InView(Projection, {10, 0, 5}, 1) && InView(Projection, {5.5f, 0, 5}, 1) &&
           !InView(Projection, {0, 9, 5}, 1));
    assert(InView(Projection, {0, 0, 0.2f}, 1)); // the camera inside the sphere
    {
        const std::array<float, 16> none{};
        assert(InView(none, {100, 0, -5}, 1)); // no projection: no culling
    }

    // The table: the rotation, a word per record, the jobs.
    {
        Plan plan;
        plan.entries = {Entry(2, 1.0f), 0u};
        plan.jobs.push_back({{1.0f, 2.0f, 3.0f}, 4.5f, 2u});
        const auto table = MakeTable(plan, Identity);
        assert(table.size() == SHAFT_TABLE_WORDS);
        assert(std::bit_cast<float>(table[SHAFT_TABLE_TO_WORLD + 10]) == 1.0f);
        assert(table[SHAFT_TABLE_RECORDS] == Entry(2, 1.0f) && table[SHAFT_TABLE_RECORDS + 1] == 0);
        assert(std::bit_cast<float>(table[SHAFT_TABLE_JOBS + 2]) == 3.0f &&
               std::bit_cast<float>(table[SHAFT_TABLE_JOBS + 3]) == 4.5f &&
               table[SHAFT_TABLE_JOBS + 4] == 2u && table[SHAFT_TABLE_JOBS + 5] == 0u);
        Totals totals;
        totals.Add(plan, 16384);
        assert(totals.frames == 1 && totals.rays == 16384 && totals.rays_most == 16384);
    }

    // 3 still lamps: every map every frame, as r80, all at full strength.
    {
        Planner planner;
        const std::vector<LampFog::Light> lamps{Light(-2, 0, 8, 4), Light(0, 1, 10, 5),
                                                Light(2, 0, 12, 3)};
        for (int f = 0; f < 10; ++f) {
            const Plan plan = planner.Run(lamps, Camera(Identity), Projection, Dt, 8);
            assert(plan.jobs.size() == 3 && plan.fresh == 3 && plan.over == 0 && plan.reused == 0);
            std::set<std::uint32_t> layers;
            for (const std::uint32_t entry : plan.entries) {
                assert(Strength(entry) == 65535);
                layers.insert(entry & SHAFT_LAYER_MASK);
            }
            assert(layers.size() == 3);
        }
    }

    // 40 still lamps, 8 maps a frame: never more than 8 maps; all mapped by frame 5, the late ones
    // fading in; then 4 a frame, every lamp within 10 frames.
    std::vector<LampFog::Light> street;
    for (int i = 0; i < 40; ++i) {
        street.push_back(Light(float(i % 8) - 3.5f, float(i / 8) - 2.0f, 15.0f + float(i), 3));
    }
    {
        Planner planner;
        std::map<std::uint32_t, int> last_built;
        for (int f = 1; f <= 120; ++f) {
            const Plan plan = planner.Run(street, Camera(Identity), Projection, Dt, 8);
            assert(plan.jobs.size() <= 8);
            for (const Job& job : plan.jobs) {
                last_built[job.layer] = f;
            }
            std::size_t full = 0, fading = 0, some = 0;
            for (const std::uint32_t entry : plan.entries) {
                full += Strength(entry) == 65535 ? 1 : 0;
                fading += Strength(entry) > 0 && Strength(entry) < 65535 ? 1 : 0;
                some += entry != 0 ? 1 : 0;
            }
            if (f == 1) {
                assert(plan.fresh == 8 && plan.over == 32 && some == 8);
            }
            if (f == 2) {
                assert(plan.fresh == 8 && plan.over == 24 && full == 8 && fading == 8);
            }
            if (f == 5) {
                assert(plan.over == 0 && some == 40);
            }
            if (f >= 20) {
                assert(plan.over == 0 && plan.jobs.size() == 4 && plan.fresh == 4 &&
                       plan.reused == 36 && full == 40);
                for (const auto& layer_built : last_built) {
                    assert(f - layer_built.second <= 10);
                }
            }
        }
        assert(last_built.size() == 40);
    }

    // A moving torch near the camera and the 40 lamps: the torch is rebuilt every frame.
    {
        Planner planner;
        for (int f = 1; f <= 60; ++f) {
            std::vector<LampFog::Light> lights{Light(0.5f * std::cos(0.3f * float(f)), -0.5f,
                                                     1.5f + 0.5f * std::sin(0.3f * float(f)), 6,
                                                     2.0f)};
            lights.insert(lights.end(), street.begin(), street.end());
            const Plan plan = planner.Run(lights, Camera(Identity), Projection, Dt, 8);
            const std::uint32_t torch = plan.entries[0] & SHAFT_LAYER_MASK;
            bool rebuilt = false;
            for (const Job& job : plan.jobs) {
                rebuilt = rebuilt || job.layer == torch;
            }
            assert(rebuilt && Strength(plan.entries[0]) == 65535 && plan.jobs.size() <= 8);
        }
    }

    // The torch's two spheres share one map with the larger reach.
    {
        Planner planner;
        const std::vector<LampFog::Light> torch{Light(0, -0.5f, 1, 4, 2.0f),
                                                Light(0, -0.5f, 1, 6, 2.0f)};
        const Plan plan = planner.Run(torch, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.size() == 1 && std::abs(plan.jobs[0].reach - 6.0f) < 1e-4f &&
               plan.entries[0] == plan.entries[1] && plan.entries[0] != 0);
    }

    // Over budget: a lamp that loses its map fades out (no pop), then back in.
    {
        Planner planner;
        const auto pair = [](int f) {
            return std::vector<LampFog::Light>{Light(0.3f * float(f), 0, 6, 4, 2.0f),
                                               Light(-0.3f * float(f), 0, 9, 4, 1.0f)};
        };
        for (int f = 1; f < 4; ++f) {
            const Plan plan = planner.Run(pair(f), Camera(Identity), Projection, Dt, 2);
            assert(plan.jobs.size() == 2 && Strength(plan.entries[0]) == 65535 &&
                   Strength(plan.entries[1]) == 65535);
        }
        std::uint32_t previous = 65535;
        Plan plan;
        for (int f = 4; f < 24; ++f) {
            plan = planner.Run(pair(f), Camera(Identity), Projection, Dt, 1);
            assert(plan.jobs.size() == 1 && plan.over == 1 && Strength(plan.entries[0]) == 65535);
            const std::uint32_t strength = Strength(plan.entries[1]);
            if (f == 4) {
                assert(strength > 60000 && strength < 65535);
            }
            assert(strength <= previous);
            previous = strength;
        }
        assert(plan.entries[1] == 0 && plan.reused == 0);
        plan = planner.Run(pair(24), Camera(Identity), Projection, Dt, 2);
        assert(plan.jobs.size() == 2 && Strength(plan.entries[1]) > 0 &&
               Strength(plan.entries[1]) < 10000);
    }

    // Standing lamps (word 7 20: the map's own lights) that seem to move 0.7 m (more than Still,
    // less than SameLamp: the records' wobble in a turn) keep their maps at full strength while
    // over budget, and a new dim lamp (word 7 0) gets its map before them.
    {
        Planner planner;
        std::vector<LampFog::Light> lamps;
        for (int i = 0; i < 20; ++i) {
            LampFog::Light lamp =
                Light(float(i % 5) - 2.0f, float(i / 5) - 1.5f, 8.0f + float(i), 3);
            lamp[7] = std::bit_cast<std::uint32_t>(20.0f);
            lamps.push_back(lamp);
        }
        assert(Standing(lamps[0]) && !Standing(Light(0, 0, 5, 1)));
        for (int f = 0; f < 30; ++f) {
            planner.Run(lamps, Camera(Identity), Projection, Dt, 8);
        }
        std::vector<LampFog::Light> wobbled;
        for (const LampFog::Light& lamp : lamps) {
            LampFog::Light moved = lamp;
            moved[0] = std::bit_cast<std::uint32_t>(std::bit_cast<float>(lamp[0]) + 0.7f);
            wobbled.push_back(moved);
        }
        wobbled.push_back(Light(0, 0, 40, 1, 0.5f));
        for (int f = 0; f < 10; ++f) {
            const Plan plan = planner.Run(wobbled, Camera(Identity), Projection, Dt, 8);
            if (f == 0) {
                assert(plan.jobs.size() == 8 && plan.over == 13 &&
                       Strength(plan.entries[20]) == 65535);
            }
            for (std::size_t k = 0; k < 20; ++k) {
                assert(Strength(plan.entries[k]) == 65535);
            }
        }
    }

    // No camera: nothing shadowed, every map dropped.
    {
        Planner planner;
        const std::vector<LampFog::Light> three(street.begin(), street.begin() + 3);
        planner.Run(three, Camera(Identity), Projection, Dt, 8);
        Plan plan = planner.Run(three, Camera(Identity, false), Projection, Dt, 8);
        assert(!plan.camera && plan.jobs.empty());
        for (const std::uint32_t entry : plan.entries) {
            assert(entry == 0);
        }
        plan = planner.Run(three, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.size() == 3);
    }

    // Out of view: no map wanted and not over budget.
    {
        Planner planner;
        const std::vector<LampFog::Light> beside{Light(20, 0, 5, 1)};
        const Plan plan = planner.Run(beside, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.empty() && plan.over == 0 && plan.entries.size() == 1 &&
               plan.entries[0] == 0);
    }

    // A turning camera: still lamps keep their world-direction maps (4 refreshes a frame).
    {
        Planner planner;
        for (int f = 1; f < 40; ++f) {
            const float a = 0.01f * float(f), c = std::cos(a), s = std::sin(a);
            const std::array<float, 12> to_world{c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0};
            std::vector<LampFog::Light> lights;
            for (int i = 0; i < 10; ++i) {
                const float wx = float(i % 5) - 2.0f, wy = float(i / 5) - 0.5f, wz = 20.0f + float(i);
                lights.push_back(Light(c * wx - s * wz, wy, s * wx + c * wz, 3));
            }
            const Plan plan = planner.Run(lights, Camera(to_world), Projection, Dt, 8);
            if (f >= 3) {
                assert(plan.fresh == 4 && plan.over == 0);
            }
        }
    }

    std::printf("lamp fog shaft cap: all checks passed\n");
    return 0;
}
''',
}

# Edits: ("ins", anchor, before, after) keeps the anchor and puts `before` in front of it and
# `after` behind it; ("rep", old, new) replaces old by new.
EDITS = {
    P: [
        ("rep",
         "// maps (lamp_fog_shaft_map.comp), layer k for light record k, each texel the free distance from\n"
         "// the light's centre along its direction over the light's radius\n",
         "// maps (lamp_fog_shaft_map.comp); bbport (r106): a layer per lamp (the table's record word names\n"
         "// it), each texel the free distance in metres from the light's centre along a world direction\n"),
        ("ins", "layout(local_size_x = 8, local_size_y = 8) in;\n",
         "#ifdef SHAFTS\n"
         "// bbport (r106_lamp-fog-shaft-cap): the shaft table's layout (lamp_fog_shaft_layout.h)\n"
         "#extension GL_GOOGLE_include_directive : require\n"
         "#include \"lamp_fog_shaft_layout.h\"\n"
         "#endif\n"
         "\n", ""),
        ("ins", "layout(binding = 4) uniform sampler2DArray shaft_maps;\n", "",
         "// bbport (r106_lamp-fog-shaft-cap): the shaft table (lamp_fog_shaft_layout.h): the composite\n"
         "// camera's view to world rows (read once in main() into shaft_to_world0..2) and a word per\n"
         "// record (its map layer and the shadow's strength)\n"
         "layout(scalar, binding = 5) readonly buffer ShaftTable { uint d[]; } shaft_table;\n"
         "vec3 shaft_to_world0, shaft_to_world1, shaft_to_world2;\n"
         "vec3 shaftRow(uint i) {\n"
         "    return uintBitsToFloat(\n"
         "        uvec3(shaft_table.d[i], shaft_table.d[i + 1u], shaft_table.d[i + 2u]));\n"
         "}\n"),
        ("rep",
         "    vec2 uv = OctEncode(v / d) * 0.5 + 0.5;\n"
         "    vec4 free_ratio = textureGather(shaft_maps, vec3(uv, float(layer)), 0);\n"
         "    return dot(step(vec4(d / radius - shaft_bias), free_ratio), vec4(0.25));\n",
         "    // bbport (r106_lamp-fog-shaft-cap): the maps are kept across frames, in world directions\n"
         "    // and metres: the direction turned to the world, the free distances compared in metres\n"
         "    vec3 w = vec3(dot(shaft_to_world0, v), dot(shaft_to_world1, v), dot(shaft_to_world2, v));\n"
         "    float w_length = length(w);\n"
         "    if (!(w_length > 0.0)) return 1.0;\n"
         "    vec2 uv = OctEncode(w / w_length) * 0.5 + 0.5;\n"
         "    vec4 free_distance = textureGather(shaft_maps, vec3(uv, float(layer)), 0);\n"
         "    return dot(step(vec4(d - shaft_bias * radius), free_distance), vec4(0.25));\n"),
        ("rep",
         "                        float end, uint layer, inout float unshadowed) {\n",
         "                        float end, uint layer, bool shadowed, inout float unshadowed) {\n"),
        ("rep",
         "            float middle = along + q * tan(0.5 * (previous + angle));\n"
         "            unshadowed += segment;\n"
         "            energy += segment * Lit(ray * middle, centre, radius, layer);\n",
         "            unshadowed += segment;\n"
         "            // bbport (r106_lamp-fog-shaft-cap): a record without a map (`shadowed` false)\n"
         "            // reads none\n"
         "            if (shadowed) {\n"
         "                float middle = along + q * tan(0.5 * (previous + angle));\n"
         "                energy += segment * Lit(ray * middle, centre, radius, layer);\n"
         "            } else {\n"
         "                energy += segment;\n"
         "            }\n"),
        ("ins", "    for (uint k = 0u; k < count; ++k) {\n",
         "#ifdef SHAFTS\n"
         "    // bbport (r106_lamp-fog-shaft-cap): the composite camera's view to world rows (the table)\n"
         "    shaft_to_world0 = shaftRow(SHAFT_TABLE_TO_WORLD);\n"
         "    shaft_to_world1 = shaftRow(SHAFT_TABLE_TO_WORLD + 4u);\n"
         "    shaft_to_world2 = shaftRow(SHAFT_TABLE_TO_WORLD + 8u);\n"
         "#endif\n", ""),
        ("rep",
         "        float lit = inscatterShadowed(ray, centre, radius, along, q, begin, nearest, k, unshadowed) +\n"
         "                    inscatterShadowed(ray, centre, radius, along, q, nearest, end, k, unshadowed);\n",
         "        // bbport (r106_lamp-fog-shaft-cap): the record's map layer and shadow strength (the\n"
         "        // table): 0 reads no map (the unshadowed fog); between 0 and 1 the lamp fades to or\n"
         "        // from it (lamp_fog_shaft_cap.h: over budget, or back in)\n"
         "        uint shaft_entry = shaft_table.d[SHAFT_TABLE_RECORDS + k];\n"
         "        float strength = float(shaft_entry >> 16u) * (1.0 / 65535.0);\n"
         "        uint layer = shaft_entry & SHAFT_LAYER_MASK;\n"
         "        bool shadowed = strength > 0.0;\n"
         "        float lit = inscatterShadowed(ray, centre, radius, along, q, begin, nearest, layer,\n"
         "                                      shadowed, unshadowed) +\n"
         "                    inscatterShadowed(ray, centre, radius, along, q, nearest, end, layer,\n"
         "                                      shadowed, unshadowed);\n"
         "        lit = mix(unshadowed, lit, strength);\n"),
    ],
    M: [
        ("rep",
         "// fog's shadow maps (lamp_fog_shafts.h). Layer k is light record k of the lamp fog's list (the\n"
         "// march's own records, camera view space). Texel (x, y) of a layer: the direction from the\n"
         "// light's centre that the texel's centre decodes to (OctDecode); one ray along it through the\n"
         "// frame's ray traced scene (instance mask `mask`, 4: what the ray traced lamp shadows trace),\n"
         "// from the blind sphere (`clearance`, at most half the radius) out to the light's radius, to the\n"
         "// nearest hit; the texel keeps the hit's distance over the radius, 1 where nothing is hit. A\n"
         "// record the march skips (not finite, inverse radius squared not positive) or whose sphere lies\n"
         "// wholly behind the camera (the march's view rays have z > 0 and never meet it) gets 1 in every\n"
         "// texel and traces no ray. Every layer below `count` is written whole every frame.\n",
         "// fog's shadow maps (lamp_fog_shafts.h), with r106 (lamp_fog_shaft_cap.h) a layer per lamp, kept\n"
         "// across frames. Workgroup z is the frame's map job z of the table (lamp_fog_shaft_layout.h:\n"
         "// the light's centre in this frame's view space, the reach in metres, the layer to write; only\n"
         "// the lamps that get a map this frame within the ray budget). Texel (x, y) of the layer: the\n"
         "// WORLD direction the texel's centre decodes to (OctDecode), turned to view space with the\n"
         "// world to view rows `to_view0..2`; one ray along it through the frame's ray traced scene\n"
         "// (instance mask `mask`, 4: what the ray traced lamp shadows trace), from the blind sphere\n"
         "// (`clearance`, at most half the reach) out to the reach, to the nearest hit; the texel keeps\n"
         "// the hit's distance in metres, SHAFT_FREE where nothing is hit. The job's layer is written\n"
         "// whole; the other layers keep what earlier frames wrote.\n"),
        ("ins", "#extension GL_EXT_ray_query : require\n", "",
         "// bbport (r106_lamp-fog-shaft-cap): the table's layout (lamp_fog_shaft_layout.h)\n"
         "#extension GL_GOOGLE_include_directive : require\n"
         "#include \"lamp_fog_shaft_layout.h\"\n"),
        ("rep",
         "layout(scalar, binding = 0) readonly buffer Lights { uint d[]; } lights;\n",
         "layout(scalar, binding = 0) readonly buffer Table { uint d[]; } table; // bbport (r106)\n"),
        ("rep",
         "    uint count;      // light records (layers written)\n"
         "    uint mask;       // the scene's instance mask (low 8 bits)\n"
         "    float clearance; // the blind sphere at the centre, m\n"
         "};\n",
         "    uint count;      // bbport (r106): the frame's map jobs (lamp_fog_shaft_cap.h MapPush)\n"
         "    uint mask;       // the scene's instance mask (low 8 bits)\n"
         "    float clearance; // the blind sphere at the centre, m\n"
         "    float pad;\n"
         "    vec4 to_view0, to_view1, to_view2; // world to view, 3x4 rows (.w not used)\n"
         "};\n"),
        ("rep",
         "    uint at = uint(texel.z) * 16u;\n"
         "    vec3 centre = uintBitsToFloat(uvec3(lights.d[at], lights.d[at + 1u], lights.d[at + 2u]));\n"
         "    float inverse_radius_squared = uintBitsToFloat(lights.d[at + 3u]);\n"
         "    float free_ratio = 1.0;\n"
         "    if (finite3(centre) && !isnan(inverse_radius_squared) && !isinf(inverse_radius_squared) &&\n"
         "        inverse_radius_squared > 0.0) {\n"
         "        float radius = inversesqrt(inverse_radius_squared);\n"
         "        if (centre.z + radius > 0.0) {\n"
         "            vec2 e = (vec2(texel.xy) + 0.5) / vec2(size) * 2.0 - 1.0;\n"
         "            vec3 direction = OctDecode(e);\n"
         "            rayQueryEXT query;\n"
         "            // every instance opaque: one proceed walks the whole ray to the nearest hit\n"
         "            rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, mask & 255u, centre,\n"
         "                                  min(clearance, 0.5 * radius), direction, radius);\n"
         "            rayQueryProceedEXT(query);\n"
         "            if (rayQueryGetIntersectionTypeEXT(query, true) !=\n"
         "                gl_RayQueryCommittedIntersectionNoneEXT) {\n"
         "                free_ratio = rayQueryGetIntersectionTEXT(query, true) / radius;\n"
         "            }\n"
         "        }\n"
         "    }\n"
         "    imageStore(maps, texel, vec4(free_ratio));\n",
         "    // bbport (r106_lamp-fog-shaft-cap): job texel.z of the table\n"
         "    uint at = SHAFT_TABLE_JOBS + uint(texel.z) * SHAFT_JOB_WORDS;\n"
         "    vec3 centre = uintBitsToFloat(uvec3(table.d[at], table.d[at + 1u], table.d[at + 2u]));\n"
         "    float reach = uintBitsToFloat(table.d[at + 3u]);\n"
         "    uint layer = table.d[at + 4u];\n"
         "    if (layer >= uint(imageSize(maps).z)) return;\n"
         "    float free_distance = SHAFT_FREE;\n"
         "    vec2 e = (vec2(texel.xy) + 0.5) / vec2(size) * 2.0 - 1.0;\n"
         "    vec3 world = OctDecode(e);\n"
         "    vec3 view = vec3(dot(to_view0.xyz, world), dot(to_view1.xyz, world),\n"
         "                     dot(to_view2.xyz, world));\n"
         "    if (finite3(centre) && !isinf(reach) && reach > 0.0 && dot(view, view) > 0.0) {\n"
         "        rayQueryEXT query;\n"
         "        // every instance opaque: one proceed walks the whole ray to the nearest hit\n"
         "        rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, mask & 255u, centre,\n"
         "                              min(clearance, 0.5 * reach), normalize(view), reach);\n"
         "        rayQueryProceedEXT(query);\n"
         "        if (rayQueryGetIntersectionTypeEXT(query, true) !=\n"
         "            gl_RayQueryCommittedIntersectionNoneEXT) {\n"
         "            free_distance = rayQueryGetIntersectionTEXT(query, true);\n"
         "        }\n"
         "    }\n"
         "    imageStore(maps, ivec3(texel.xy, int(layer)), vec4(free_distance));\n"),
    ],
    S: [
        ("rep",
         "// glow. With BB_LAMP_FOG_SHAFTS set, every frame with lamp fog and a ray traced scene first builds\n"
         "// one octahedral shadow map per light record of the lamp fog's list (lamp_fog_shaft_map.comp:\n",
         "// glow. With BB_LAMP_FOG_SHAFTS set, every frame with lamp fog and a ray traced scene first builds\n"
         "// the octahedral shadow maps r106 picks for the lamp fog's lights (lamp_fog_shaft_map.comp:\n"),
        ("rep",
         "// the nearest hit's distance over the radius, 1 where nothing is hit). The march's SHAFTS builds\n",
         "// the nearest hit's distance (r106: metres, SHAFT_FREE where nothing is hit). The SHAFTS builds\n"),
        ("rep",
         "// lamp fog, which needs the game's sun shadow resolve (VolumetricLight::Integrate). Every map is\n"
         "// rebuilt every frame, in the camera's view space (the space of the light records and of the TLAS\n"
         "// instances), so its texel grid turns with the camera.\n",
         "// lamp fog, which needs the game's sun shadow resolve (VolumetricLight::Integrate). With r106\n"
         "// (lamp_fog_shaft_cap.h) a map belongs to a lamp and is kept across frames within a ray budget:\n"
         "// its texels are world directions and keep the free distance in metres (SHAFT_FREE where\n"
         "// nothing is hit); Lit() below takes that distance over the radius, as the march compares it.\n"),
        ("rep",
         "/// Map rays in a frame with `lights` records, at most (records the march skips or whose sphere\n"
         "/// lies wholly behind the camera trace none).\n",
         "/// Map rays in a frame with `lights` records if every record were mapped every frame (r80 without\n"
         "/// r106's cap; r80's 600-frame line prints it beside the cap's rays).\n"),
    ],
    VH: [
        ("ins", "#include \"video_core/renderer_vulkan/lamp_fog_shafts.h\" // bbport (r80_lamp-fog-shafts)\n", "",
         "#include \"video_core/renderer_vulkan/lamp_fog_shaft_cap.h\" // bbport (r106_lamp-fog-shaft-cap)\n"),
        ("ins", "    bool ShaftsReady(u32 level);\n", "",
         "    // bbport (r106_lamp-fog-shaft-cap): in RecordShafts: which lamps get a map this frame within\n"
         "    // BB_LAMP_FOG_SHAFTS_RAYS (shaft_planner), the table both passes read (`table`), the r106\n"
         "    // line's sums; returns the maps to build this frame\n"
         "    u32 PlanShafts(const std::vector<u32>& data, u32 count, std::vector<u32>& table);\n"),
        ("rep",
         "    // maps (a layer per light record, shaft_size texels a side); the 600-frame line's counts and\n",
         "    // maps (a layer per lamp with r106, shaft_size texels a side); the 600-frame line's counts and\n"),
        ("ins", "    bool shafts_tried = false, shafts_failed = false, shafts_said = false;\n", "",
         "    // bbport (r106_lamp-fog-shaft-cap): BB_LAMP_FOG_SHAFTS set only: the lamps' maps from frame\n"
         "    // to frame, the table (made by ShaftsReady), whether the maps hold earlier frames' layers\n"
         "    // (no Undefined layout then), the once-line's flag, the plan's clock, the r106 line's sums\n"
         "    LampFogShaftCap::Planner shaft_planner;\n"
         "    std::unique_ptr<VideoCore::Buffer> shaft_table;\n"
         "    bool shaft_maps_kept = false, shaft_cap_said = false;\n"
         "    std::chrono::steady_clock::time_point shaft_time{};\n"
         "    LampFogShaftCap::Totals shaft_totals;\n"),
    ],
    VC: [
        ("rep",
         "                   LAMP_FOG_SHAFT_MAP_COMP, 3 * sizeof(u32), \"Lamp fog shaft maps\") &&\n",
         "                   LAMP_FOG_SHAFT_MAP_COMP, sizeof(LampFogShaftCap::MapPush), // bbport (r106)\n"
         "                   \"Lamp fog shaft maps\") &&\n"),
        ("rep",
         "        CreatePass(point_shafts,\n"
         "                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "                    eCombinedImageSampler},\n",
         "        CreatePass(point_shafts,\n"
         "                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "                    eCombinedImageSampler, eStorageBuffer}, // bbport (r106): 5 the table\n"),
        ("ins", "    shaft_size = size;\n", "",
         "    // bbport (r106_lamp-fog-shaft-cap): the table both passes read (PlanShafts fills it)\n"
         "    shaft_table = std::make_unique<VideoCore::Buffer>(instance, 0, LampFogShaftCap::TableBytes,\n"
         "                                                      VideoCore::MemoryType::DeviceLocal,\n"
         "                                                      \"Lamp fog shaft table\");\n"),
        ("ins",
         "// bbport (r80_lamp-fog-shafts): in place of RecordLampFog's pass while the shafts run: the light\n",
         "// bbport (r106_lamp-fog-shaft-cap): BB_LAMP_FOG_SHAFTS set, each frame RecordShafts runs: which\n"
         "// lamps get a map this frame within the ray budget (lamp_fog_shaft_cap.h; BB_LAMP_FOG_SHAFTS_RAYS\n"
         "// read once). The table both passes read goes to `table`, the frame is added to the r106\n"
         "// line's sums, and the first call says the cap once. Returns the maps to build this frame.\n"
         "u32 VolumetricLight::PlanShafts(const std::vector<u32>& data, u32 count, std::vector<u32>& table) {\n"
         "    const u32 level = LampFogShafts::Level();\n"
         "    const u64 budget = LampFogShaftCap::Budget(LampFogShaftCap::Rays(), level);\n"
         "    const u32 maps = LampFogShaftCap::MapsPerFrame(budget, level);\n"
         "    const u64 per_map = LampFogShaftCap::RaysPerMap(level);\n"
         "    if (!std::exchange(shaft_cap_said, true)) {\n"
         "        std::printf(\"Volumetric lighting (r106): lamp fog shaft cap: at most %u maps of %ux%u a \"\n"
         "                    \"frame, %llu map rays (BB_LAMP_FOG_SHAFTS_RAYS budget %llu%s); maps kept, %u \"\n"
         "                    \"still lamps rebuilt a frame oldest first, new and moving first; over \"\n"
         "                    \"budget a lamp fades to unshadowed fog in %.2f s\\n\",\n"
         "                    maps, LampFogShafts::MapSize(level), LampFogShafts::MapSize(level),\n"
         "                    static_cast<unsigned long long>(maps * per_map),\n"
         "                    static_cast<unsigned long long>(budget),\n"
         "                    LampFogShaftCap::Rays() == 0 ? \", the default\" : \"\",\n"
         "                    LampFogShaftCap::RefreshPerFrame, double(LampFogShaftCap::FadeOut));\n"
         "    }\n"
         "    const auto now = std::chrono::steady_clock::now();\n"
         "    const float seconds =\n"
         "        shaft_time == std::chrono::steady_clock::time_point{}\n"
         "            ? 0.0f\n"
         "            : std::clamp(std::chrono::duration<float>(now - shaft_time).count(), 0.0f, 0.1f);\n"
         "    shaft_time = now;\n"
         "    std::array<float, 16> inverse_projection{};\n"
         "    for (u32 i = 0; i < 16; ++i) {\n"
         "        inverse_projection[i] = std::bit_cast<float>(data[i]);\n"
         "    }\n"
         "    const u32 lights = std::min(count, LampFogShafts::MaxMaps);\n"
         "    std::vector<LampFog::Light> records(lights);\n"
         "    for (u32 i = 0; i < lights; ++i) {\n"
         "        std::copy_n(data.begin() + FogLightsAt / 4 + i * 16, 16, records[i].begin());\n"
         "    }\n"
         "    const LampFogShaftCap::Plan plan =\n"
         "        shaft_planner.Run(records, fog_camera, inverse_projection, seconds, maps);\n"
         "    table = LampFogShaftCap::MakeTable(plan, fog_camera.view_to_world);\n"
         "    shaft_totals.Add(plan, per_map);\n"
         "    return u32(plan.jobs.size());\n"
         "}\n"
         "\n", ""),
        ("rep",
         "// records to the GPU as there, the shadow maps of the first `count` records (a pinned profile row\n",
         "// records to the GPU as there, the shadow maps PlanShafts picks (r106; a pinned profile row\n"),
        ("rep",
         "    struct MapParams {\n"
         "        u32 count, mask;\n"
         "        float clearance;\n"
         "    };\n"
         "    static_assert(sizeof(MapParams) == 12);\n",
         "    // bbport (r106_lamp-fog-shaft-cap): lamp_fog_shaft_map.comp's push constants (the frame's\n"
         "    // map jobs, the mask, the blind sphere, the camera's world to view rows)\n"
         "    using MapParams = LampFogShaftCap::MapPush;\n"),
        ("rep",
         "    const u32 layers = std::min(count, LampFogShafts::MaxMaps);\n"
         "    const MapParams map_params{layers, LampFogShafts::SceneMask, LampFogShafts::Clearance};\n",
         "    // bbport (r106_lamp-fog-shaft-cap): the frame's plan (PlanShafts): the table both passes\n"
         "    // read and, as `layers`, the maps built this frame (at most LampFogShaftCap::MapsPerFrame);\n"
         "    // `kept`: the maps' image already holds layers of earlier frames (General layout)\n"
         "    std::vector<u32> table;\n"
         "    const u32 layers = PlanShafts(data, count, table);\n"
         "    const MapParams map_params{layers, LampFogShafts::SceneMask, LampFogShafts::Clearance, 0.0f,\n"
         "                               fog_camera.world_to_view};\n"
         "    const vk::Buffer table_buffer = shaft_table->Handle();\n"
         "    const vk::DescriptorBufferInfo table_info{table_buffer, 0, LampFogShaftCap::TableBytes};\n"
         "    const bool kept = std::exchange(shaft_maps_kept, true);\n"),
        ("rep",
         "        [map_params, records, maps_out, buffer, data_bytes, data = std::move(data), groups, layers,\n",
         "        [map_params, table_info, maps_out, buffer, data_bytes, data = std::move(data), groups, layers,\n"
         "         table = std::move(table), table_buffer, kept, // bbport (r106_lamp-fog-shaft-cap)\n"),
        ("rep",
         "            cmd.updateBuffer(buffer, 0, data_bytes, data.data());\n"
         "            Before(cmd);\n"
         "            // The layers below `layers` are written whole every frame; the others are not read.\n",
         "            cmd.updateBuffer(buffer, 0, data_bytes, data.data());\n"
         "            // bbport (r106_lamp-fog-shaft-cap): the table; then only this frame's map jobs: the\n"
         "            // other layers keep what earlier frames wrote. No job and the maps kept: nothing more\n"
         "            // (the march's Before orders both uploads before its reads).\n"
         "            cmd.updateBuffer(table_buffer, 0, LampFogShaftCap::TableBytes, table.data());\n"
         "            if (layers == 0 && kept) {\n"
         "                return;\n"
         "            }\n"
         "            Before(cmd);\n"
         "            // The layers of this frame's jobs are written whole; the march reads only layers\n"
         "            // written in this or an earlier frame (PlanShafts).\n"),
        ("rep",
         "                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,\n"
         "                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,\n"
         "                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,\n"
         "                .image = image, .subresourceRange = ShaftRange,\n",
         "                // bbport (r106_lamp-fog-shaft-cap): Undefined only the first time: kept layers\n"
         "                .oldLayout = kept ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined,\n"
         "                .newLayout = vk::ImageLayout::eGeneral,\n"
         "                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,\n"
         "                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,\n"
         "                .image = image, .subresourceRange = ShaftRange,\n"),
        ("rep",
         "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &records},\n"
         "                {.pNext = &scene_info, .dstBinding = 1, .descriptorCount = 1,\n",
         "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table_info},\n"
         "                {.pNext = &scene_info, .dstBinding = 1, .descriptorCount = 1,\n"),
        ("rep",
         "        [params, constants, records, depth, out, maps_in, w, h,\n",
         "        [params, constants, records, depth, out, maps_in, table_info, w, h, // bbport (r106)\n"),
        ("rep",
         "            const std::array<vk::WriteDescriptorSet, 5> writes{{\n",
         "            const std::array<vk::WriteDescriptorSet, 6> writes{{ // bbport (r106): 5 the table\n"),
        ("ins",
         "                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &maps_in},\n",
         "",
         "                {.dstBinding = 5, .descriptorCount = 1,\n"
         "                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table_info},\n"),
        ("rep",
         "                        \"%ux%u ray traced shadow map per lamp fog light, all rebuilt every frame \"\n",
         "                        \"%ux%u ray traced shadow map per lamp fog light, built within the r106 cap \"\n"),
        ("rep",
         "                        \"this frame %u lights, at most %llu map rays\\n\",\n",
         "                        \"this frame %u lights, %llu map rays without the r106 cap\\n\",\n"),
        ("ins", "            shafts_frames = shafts_shadowed = 0;\n", "",
         "            // bbport (r106_lamp-fog-shaft-cap): the cap's line, a line of its own (the slot runs\n"
         "            // keep 300 characters of a line): over the frames planned since the last line\n"
         "            // (LampFogShaftCap::Totals): map rays a frame on average and at most, against the\n"
         "            // cap (maps a frame x one map's rays); lamps a frame on average with a map built that\n"
         "            // frame, drawn with a kept map, over budget (wanting a map, getting none), the most\n"
         "            // over budget in one frame; frames without a camera (nothing shadowed)\n"
         "            const auto& totals = shaft_totals;\n"
         "            const double planned = double(std::max<u64>(totals.frames, 1));\n"
         "            const u64 cap = LampFogShaftCap::MapsPerFrame(\n"
         "                                LampFogShaftCap::Budget(LampFogShaftCap::Rays(), shaft_level),\n"
         "                                shaft_level) *\n"
         "                            LampFogShaftCap::RaysPerMap(shaft_level);\n"
         "            std::printf(\"Volumetric lighting (r106): shaft cap over %llu frames: map rays a frame \"\n"
         "                        \"%.0f avg, %llu max, cap %llu; lamps a frame: %.1f fresh, %.1f reused, \"\n"
         "                        \"%.1f over budget (%u max); %llu frames without a camera\\n\",\n"
         "                        static_cast<unsigned long long>(totals.frames),\n"
         "                        double(totals.rays) / planned,\n"
         "                        static_cast<unsigned long long>(totals.rays_most),\n"
         "                        static_cast<unsigned long long>(cap), double(totals.fresh) / planned,\n"
         "                        double(totals.reused) / planned, double(totals.over) / planned,\n"
         "                        totals.over_most, static_cast<unsigned long long>(totals.no_camera));\n"
         "            shaft_totals = {};\n"),
        ("rep",
         "            !CreatePass(point_shafts_wind,\n"
         "                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "                         eCombinedImageSampler},\n",
         "            !CreatePass(point_shafts_wind,\n"
         "                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "                         eCombinedImageSampler, eStorageBuffer}, // bbport (r106): 5 the table\n"),
    ],
    CM: [
        ("ins",
         "    # bbport (r88_wind-lamp-fog): and the lamp fog's WIND builds, with the wind words' layout.\n"
         "    if (FILENAME MATCHES \"^point_volumetric\")\n"
         "        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl ${SHADER_SRC}/lamp_wind_layout.h)\n"
         "    endif()\n", "",
         "    # bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' table layout, shared with C++\n"
         "    if (FILENAME MATCHES \"^point_volumetric|^lamp_fog_shaft_map\")\n"
         "        list(APPEND INCLUDES ${SHADER_SRC}/lamp_fog_shaft_layout.h)\n"
         "    endif()\n"),
        ("ins",
         "add_executable(lamp-fog-shafts-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shafts.cpp)\n"
         "target_compile_options(lamp-fog-shafts-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(lamp-fog-shafts-test PRIVATE ..)\n", "",
         "# bbport (r106_lamp-fog-shaft-cap): the shafts' ray budget and planner (lamp_fog_shaft_cap.h)\n"
         "add_executable(lamp-fog-shaft-cap-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_cap.cpp)\n"
         "target_compile_options(lamp-fog-shaft-cap-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(lamp-fog-shaft-cap-test PRIVATE ..)\n"),
    ],
    BS: [
        ("ins", "    out/lamp-fog-shafts-test\n", "",
         "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_lamp_fog_shaft_cap.cpp -o out/lamp-fog-shaft-cap-test\n"
         "    out/lamp-fog-shaft-cap-test\n"),
    ],
    EP: [
        ("ins", "        {\"point volumetric (shafts)\",\n",
         "        // bbport (r106_lamp-fog-shaft-cap): all four shafts builds also bind 5, the shaft table\n", ""),
        ("rep",
         "        {\"point volumetric (shafts)\",\n"
         "         POINT_VOLUMETRIC_SHAFTS_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler},\n",
         "        {\"point volumetric (shafts)\",\n"
         "         POINT_VOLUMETRIC_SHAFTS_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler, eStorageBuffer},\n"),
        ("rep",
         "         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler},\n",
         "         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler, eStorageBuffer},\n"),
        ("rep",
         "         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler},\n",
         "         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler, eStorageBuffer},\n"),
        ("rep",
         "         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler},\n",
         "         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,\n"
         "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
         "          eCombinedImageSampler, eStorageBuffer},\n"),
    ],
    RM: [
        ("rep",
         "| `BB_LAMP_FOG_SHAFTS` | `1`: every frame, a 128x128 ray traced shadow map for each light of the lamp fog (up to 64), and the fog of each light is cut by it;",
         "| `BB_LAMP_FOG_SHAFTS` | `1`: a 128x128 ray traced shadow map for each light of the lamp fog (up to 64), built within the ray budget of `BB_LAMP_FOG_SHAFTS_RAYS` and kept while the light stands still, and the fog of each light is cut by it;"),
        ("ins",
         "| `BB_RT_GLASS` | Groundwork for light through windows,",
         "| `BB_LAMP_FOG_SHAFTS_RAYS` | With `BB_LAMP_FOG_SHAFTS` on: the most map rays a frame, in decimal digits, 16384 to 4194304 (1 to 16383 is taken as 16384, more as 4194304; one map has 16384 rays at `1` and `3`, 65536 at `2`). The maps a frame are this over one map's rays, at least 1 and at most 64, so a frame never casts more than this or one map. A map belongs to a light and is kept from frame to frame while the light stands still (in world directions). Each frame the lights in view that have no map, moved more than 5 cm plus 2 cm for each metre from the camera since their map was made, or grew, get one first, the light with the most fog first (near and bright); maps left over rebuild up to 4 standing lights, the oldest map first (lights that reach within 3 m of the camera count their map's age 4 times). A light that wants a map and gets none fades to its fog without shafts in 0.25 s and back when it gets one; a standing lamp of the map (it cannot move: while the camera moves its position only seems to shift, by up to 0.5 m plus 5 cm for each metre from the camera) keeps its map meanwhile, and the lights that would fade get maps first. Lights within 1 cm of each other (the two lights of the torch) share a map. Not set, `0` or any other text: 8 maps (131072 rays at `1` and `3`, 524288 at `2`). A log line every 600 lamp fog frames, `Volumetric lighting (r106): shaft cap`, gives the rays a frame and the lights with a fresh map, reusing a map and over budget | 8 maps |\n",
         ""),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    P: [("#include \"lamp_fog_shaft_layout.h\"", 1), ("binding = 5) readonly buffer ShaftTable", 1),
        ("lit = mix(unshadowed, lit, strength);", 1), ("d - shaft_bias * radius", 1),
        ("d / radius - shaft_bias", 0), ("inscatterShadowed(ray, centre, radius, along, q, begin, nearest, layer,", 1),
        ("const uint SEGMENTS = 6u;", 1), ("layer k for light record k", 0)],
    M: [("#include \"lamp_fog_shaft_layout.h\"", 1), ("uint at = SHAFT_TABLE_JOBS + uint(texel.z) * SHAFT_JOB_WORDS;", 1),
        ("vec4 to_view0, to_view1, to_view2;", 1), ("lights.d[", 0), ("free_ratio", 0),
        ("imageStore(maps, ivec3(texel.xy, int(layer)), vec4(free_distance));", 1)],
    VC: [("u32 VolumetricLight::PlanShafts(", 1), ("const u32 layers = PlanShafts(data, count, table);", 1),
         ("std::array<vk::WriteDescriptorSet, 6> writes{{", 1), ("std::array<vk::WriteDescriptorSet, 5> writes{{", 0),
         ("eCombinedImageSampler, eStorageBuffer}, // bbport (r106): 5 the table", 2),
         ("sizeof(LampFogShaftCap::MapPush)", 1), ("3 * sizeof(u32), \"Lamp fog shaft maps\"", 0),
         ("Volumetric lighting (r106): shaft cap over %llu frames", 1),
         ("Volumetric lighting (r106): lamp fog shaft cap: at most", 1), ("all rebuilt every frame", 0),
         (".pBufferInfo = &table_info},", 2), ("shaft_table = std::make_unique<VideoCore::Buffer>(", 1)],
    S: [("one octahedral shadow map per light record", 0), ("over the radius, 1 where nothing is hit", 0)],
    VH: [("LampFogShaftCap::Planner shaft_planner;", 1), ("u32 PlanShafts(const std::vector<u32>& data, u32 count, std::vector<u32>& table);", 1)],
    EP: [("eCombinedImageSampler, eStorageBuffer},", 4)],
    RM: [("| `BB_LAMP_FOG_SHAFTS_RAYS` |", 1), ("`1`: every frame, a 128x128", 0)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    VC: ["bool VolumetricLight::ShaftsReady(u32 level) {", "shaft_table = std::make_unique",
         "u32 VolumetricLight::PlanShafts(", "void VolumetricLight::RecordShafts(",
         "const u32 layers = PlanShafts(data, count, table);", "{.name = \"Lamp fog shaft maps\"}",
         "if (layers == 0 && kept) {", "cmd.dispatch(groups, groups, layers);",
         "{.name = \"Lamp fog (shafts)\"}", "{.dstBinding = 5, .descriptorCount = 1,",
         "void VolumetricLight::RecordLampFog(", "shafts_frames = shafts_shadowed = 0;",
         "Volumetric lighting (r106): shaft cap over", "bool VolumetricLight::LampWindPasses("],
    P: ["#include \"lamp_fog_shaft_layout.h\"", "layout(local_size_x = 8, local_size_y = 8) in;",
        "uniform sampler2DArray shaft_maps;", "binding = 5) readonly buffer ShaftTable",
        "float Lit(", "float inscatterShadowed(", "void main() {", "shaft_to_world0 = shaftRow(",
        "for (uint k = 0u; k < count; ++k) {", "lit = mix(unshadowed, lit, strength);"],
}


def shafts_only(text):
    """Every r106 line of point_volumetric.comp and every line of its r106 blocks lies inside an
    #ifdef SHAFTS (the default and WIND builds keep their bytes)."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifdef SHAFTS")
        elif st.startswith("#else"):
            stack[-1] = False
        elif st.startswith("#endif"):
            stack.pop()
        elif ("r106" in line or "shaft_table" in line or "shaft_to_world" in line or
              "shaftRow" in line or "SHAFT_" in line) and not any(stack):
            raise SystemExit("text check: r106 shader line outside #ifdef SHAFTS: %r" % line)


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
    shafts_only(texts[P])
    # the new files' ties: the table words both sides use, the push size, the knob's name
    cap = texts[R + "lamp_fog_shaft_cap.h"]
    for want in ('std::getenv("BB_LAMP_FOG_SHAFTS_RAYS")', "static_assert(sizeof(MapPush) == 64);",
                 "keeps[s] = fresh_wanted && slot.has_map && standing[s] &&",
                 '#include "../host_shaders/lamp_fog_shaft_layout.h"'):
        if cap.count(want) != 1:
            raise SystemExit("text check: lamp_fog_shaft_cap.h lacks %r" % want)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts(edit):
    return [t for t in (edit[2], edit[3]) if t] if edit[0] == "ins" else [edit[2]]


def state_of(cur, eds, path):
    """'applied' or 'clean' for the whole file, else refuse. ins: anchor once and each inserted text
    once (applied) or none (clean). rep: new once and old none (applied), old once and new none
    (clean)."""
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            na, counts = cur.count(e[1]), [cur.count(t) for t in parts(e)]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                                 "times: %r" % (path, na, counts, e[1][:70]))
        else:
            no, nn = cur.count(e[1]), cur.count(e[2])
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %d times: %r"
                                 % (path, no, nn, e[1][:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_state(path, text):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    if load(path)[2] == text:
        return "applied"
    raise SystemExit("%s exists and is not this patch's text" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R106_ROOT)" % ROOT)
    for path, eds in EDITS.items():
        for e in eds:
            if e[0] == "rep" and (e[1] in e[2] or e[2] in e[1]):
                raise SystemExit("script fault: %s: a replacement holds its old text" % path)
    plan = []
    for path, eds in EDITS.items():
        raw, eol, cur = load(path)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    news = [(path, text, new_state(path, text)) for path, text in NEW_FILES.items()]
    states = {p[5] for p in plan} | {n[2] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                     ["%s %s" % (n[0], n[2]) for n in news]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for e in eds:
                if e[0] == "ins":
                    cur = cur.replace(e[1], e[2] + e[1] + e[3])
                else:
                    cur = cur.replace(e[1], e[2])
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update({n[0]: n[1] for n in news})
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update({n[0]: n[1] for n in news})
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on "
                  "the result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(news)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8")) for path, *_ in plan]
        outs += [(path, text.replace("\n", "\r\n").encode("utf-8")) for path, text, _ in news]
        for path, data in outs:
            full = os.path.join(ROOT, path)
            tmp = full + ".r106tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    # all files are worked out before any is written
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for e in reversed(eds):
            if e[0] == "ins":
                for part in (e[3], e[2]):
                    if part:
                        cur = cur.replace(part, "", 1)
            else:
                cur = cur.replace(e[2], e[1], 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r106tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path, text, _ in news:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
