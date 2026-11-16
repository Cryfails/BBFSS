# r80_lamp-fog-shafts: FEATURE patch (branch visual/lamp-fog-shafts). Lamp and torch shafts
# through fog, the FIRST EXPERIMENT of method D (bbfss-ctx-lamp-fog-shafts.md): the lamp fog is
# cut where the frame's ray traced scene stands between a light and the fog. Off by default.
#
# Why: the owner's work order item 3, "Lamp and torch shafts through fog", for the lights "not
# just from the hunter". The lamp fog (point_volumetric.comp, every light the game lists: the
# street and wall lamps, candles, the hunter's torch and hand lantern) binds no shadow at all: a
# pillar or the hunter between a light and the fog does not cut its glow. One game run with this
# knob shows whether the fog of a light then has the shadow of what stands in front of it.
#
# What:
# 1. BB_LAMP_FOG_SHAFTS (environment, read once; unset, empty or anything but "0" to "3" is 0):
#    0 off, the lamp fog's pass and shader build of before and nothing of this made or run;
#    1 on (128x128 maps, 6 segments a half chord as before); 2 on (256x256 maps, 12 segments);
#    3 as 1 with the lamp fog drawn as a debug view (orange the light that reaches the fog, blue
#    the light the maps cut off, both 4x). Pure parts in renderer_vulkan/lamp_fog_shafts.h
#    (Parse, MapSize, Segments, MapBytes, MapRays, Blind, OctEncode/OctDecode, EnergyMiddle, Lit),
#    tested by tests/test_lamp_fog_shafts.cpp (CMake lamp-fog-shafts-test and build.sh --test).
# 2. With the knob set and a ray traced scene this frame, VolumetricLight::RecordLampFog records
#    RecordShafts in place of its pass: the light records go to the GPU as before; then the new
#    pass lamp_fog_shaft_map.comp builds one octahedral map per light record (layer = record
#    index, camera view space, the space of the records and of the TLAS instances): one ray per
#    texel from the light's centre, blind within min(0.35 m, radius / 2) (the lamp shadows'
#    LAMP_CLEARANCE), out to the light's radius, instance mask 4 (what the lamp shadows trace:
#    everything but cut-out cards, the hunter included), to the nearest hit; the texel keeps the
#    hit's distance over the radius (R16F), 1 where nothing is hit. Records the march skips or
#    whose sphere lies wholly behind the camera trace no ray. Every map is rebuilt every frame:
#    no history, nothing cached, no trails. Then the march's SHAFTS build (point_volumetric.comp
#    SHAFTS=1 for 1 and 2, SHAFTS=1 VIEW=1 for 3) multiplies each segment's light by the share of
#    the four gathered map texels around the direction from the light to the segment's sample point
#    whose free distance reaches it (less Bias, 1% of the radius); the sample point halves the
#    segment's exact inverse-square energy (along + q tan((a0 + a1) / 2)). The SHAFTS builds take
#    the bias and the segment count (6, 12 for 2) from their push constants (LampFogShafts::Bias,
#    Segments), so host and shader cannot disagree. The build without SHAFTS is the default and
#    its SPIR-V is byte-identical to before.
# 3. The rasterizer passes the scene (RtShadow::PrepareScene, Scene) to VolumetricLight::
#    SetLampScene right before both Composite calls, only with the knob set and lamp fog
#    (effect_point_fog) on. RtShadow::SceneWanted is also true then. effect_ray_tracing itself is
#    derived from the ray traced sun, lamp shadows, bounced light and the virtual shadow maps
#    (BbSettings::DeriveRayTracing), so the knob never turns ray tracing on: it adds a scene only
#    where ray tracing is on for the virtual shadow maps alone (then r76's sun gate, which runs
#    whenever a scene exists, starts too). Without ray tracing the lamp fog stays as before.
# 4. GPU profile: a pinned row "Lighting: lamp fog shafts" (EffectPass::Mark 80) holds the maps'
#    upload and rays; the march stays under "Lighting: lamp fog". Log: one once-line at the first
#    lamp fog with lights that says the knob's state ("Volumetric lighting (r80): lamp fog shafts
#    off ..." or "... on ..."), and with the knob set, every 600 lamp fog frames, in how many the
#    maps ran, the frame's light count and its map rays at most.
# 5. Docs and tests: README (a "Lamp fog shafts" table), effect-pipelines-test (the two SHAFTS
#    builds; the map pass needs ray queries, which that test's device does not turn on), the new
#    lamp-fog-shafts-test, build.sh --test.
#
# Review fixes (2026-11-15, adversarial review of the draft): the shader's SHAFT_BIAS and the HIGH
# build's 12 segments were written twice (header and shader, tied by a comment only; the
# maintainer's rule wants such pairs tied), now pushed from LampFogShafts::Bias/Segments and the
# HIGH build is gone; PrepareScene at the composite and SceneWanted also need lamp fog on (with
# lamp fog off the knob made a scene and a TLAS rebuild nothing reads); the README and these notes
# no longer claim the knob builds a scene with every other ray traced effect off (it cannot: see 3).
#
# Cost (NOT MEASURED; estimates at 1080p internal, RTX 4090): knob 0: nothing (one branch and one
# once-line on the host). Knob 1: map rays 16384 per light in front of the camera, short (at most
# the light's radius) nearest-hit rays: the torch alone (about 2 records) 33k rays, 0.01-0.02 ms;
# 16 lights 262k rays, 0.04-0.1 ms; the most, 64 lights, 1.05M rays, 0.2-0.4 ms. The march adds a
# tan and a 4-texel gather of a 2 MB array per segment it already evaluates: +0.03-0.2 ms on top of
# the measured 0.13 ms "Lighting: lamp fog", most with many overlapping lights. Knob 2: 4x the map
# rays (0.15-0.4 ms with 16 lights) and twice the march's segments. Memory: 2 MB (1, 3) or 8 MB (2)
# made at the first use. Only with the virtual shadow maps as the one ray traced feature does the
# scene's upkeep (0.9-1.2 ms measured earlier) come with it; PrepareScene at the composite rebuilds
# or refits the TLAS only when entries arrived since the frame's last build (watch r17's
# tlas_prepared per frame; such a second build in one frame writes the same instance ring slot as
# the first, a hazard RtShadow already has with SSGI's late PrepareScene: watch the sun and lamp
# shadows for one-frame flicker with the knob set). Saved
# against a ray per fog sample per light (the first design): about 25M rays a frame for the torch
# alone at 1080p (2 records x 12 samples x 2.07M pixels) against 33k here.
#
# Not done (the full method D differs): maps in world directions cached across frames with a
# round-robin refresh (4 lamps a frame, the torch every frame, new lamps at once), records within
# 1 cm sharing a map, at most 8 shadowed lamps a pixel, the half-resolution ratio folded into the
# march, the S0 speed-ups, the menu setting graphics_lamp_fog_shafts with its launchers and eight
# translation tables, a separate clearance knob, cut-out leaves in the map rays (S4), the sun leak
# stages. Known limits of the experiment: the octahedral map's fold edges can show a thin seam in
# the gather; the maps are in view space, so their texel grid turns with the camera and a shaft's
# edge may crawl while the camera turns (world-direction maps of method D do not); a wall lamp within 0.35 m of its wall still lights the room behind; the fog density
# stays the fixed 0.025/m; lamp fog needs the game's sun shadow resolve (no lamp fog at all where
# it does not run).
#
# Files: host_shaders/point_volumetric.comp, host_shaders/lamp_fog_shaft_map.comp (new),
# renderer_vulkan/lamp_fog_shafts.h (new), vk_volumetric_light.h, vk_volumetric_light.cpp,
# vk_rasterizer_effects.cpp, vk_rt_shadow.cpp, engine/gpu/CMakeLists.txt, engine/build.sh,
# engine/tests/test_lamp_fog_shafts.cpp (new), engine/tests/test_effect_pipelines.cpp, README.md.
#
# Use: cd <tree> && python -I -X utf8 r80_lamp-fog-shafts.py check | apply | revert (root from
# R80_ROOT, else the current directory). Files keep their line ends (CRLF in the tree); new files
# are written with CRLF. Originals are kept in r80_backup/ next to this script; revert removes the
# new files. Needs r76 (and r76b) applied; touches no line r76 or r76b wrote (its anchors are the
# lamp fog's own lines, see ANCHORS in the report).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r80_backup")
ROOT = os.environ.get("R80_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
T = "engine/tests/"

NEW_FILES = {
    R + "lamp_fog_shafts.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r80_lamp-fog-shafts): lamp and torch shafts through fog, a first experiment. The lamp
// fog (point_volumetric.comp: every light the game lists, the hunter's torch and hand lantern
// included) is unshadowed: a pillar or the hunter between a light and the fog does not cut its
// glow. With BB_LAMP_FOG_SHAFTS set, every frame with lamp fog and a ray traced scene first builds
// one octahedral shadow map per light record of the lamp fog's list (lamp_fog_shaft_map.comp:
// from the light's centre, one ray per texel through the frame's ray traced scene, instance mask
// SceneMask, blind within Blind(radius) of the centre, out to the light's radius; the texel keeps
// the nearest hit's distance over the radius, 1 where nothing is hit). The march's SHAFTS builds
// then multiply each segment's light by Lit(): the share of the four map texels around the
// direction from the light to the segment's sample point whose free distance reaches the point
// (less Bias of the radius). The sample point is the place where the segment's inverse-square
// energy is split in half (EnergyMiddle). The SHAFTS builds take Bias and Segments from their
// push constants (VolumetricLight::RecordShafts). No Vulkan here: tests/test_lamp_fog_shafts.cpp
// builds this header alone.
//
// BB_LAMP_FOG_SHAFTS, read once at start; unset, empty or any text but "0" to "3" is 0:
//   0 off: the lamp fog's pass and build of before; nothing of this runs or is made
//   1 on: 128x128 maps, 6 segments a half chord (the march's count of before)
//   2 on: 256x256 maps, 12 segments a half chord
//   3 as 1, the lamp fog drawn as a debug view: orange the light that reaches the fog, blue the
//     light the maps cut off, both 4 times as bright as the fog
// The maps exist only while the ray traced scene is built (effect_ray_tracing on, which the
// settings derive from the ray traced sun, lamp shadows, bounced light and virtual shadow maps; a
// set knob with lamp fog on also makes RtShadow::SceneWanted true) and only in frames that draw
// lamp fog, which needs the game's sun shadow resolve (VolumetricLight::Integrate). Every map is
// rebuilt every frame, in the camera's view space (the space of the light records and of the TLAS
// instances), so its texel grid turns with the camera.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace Vulkan::LampFogShafts {

inline constexpr std::uint32_t Off = 0, Medium = 1, High = 2, View = 3;

/// The knob's text: exactly one character "0" to "3"; anything else is Off.
inline std::uint32_t Parse(const char* text) {
    return text && text[0] >= '0' && text[0] <= '3' && text[1] == '\0'
               ? std::uint32_t(text[0] - '0')
               : Off;
}

/// BB_LAMP_FOG_SHAFTS, read once.
inline std::uint32_t Level() {
    static const std::uint32_t level = Parse(std::getenv("BB_LAMP_FOG_SHAFTS"));
    return level;
}

inline const char* Name(std::uint32_t level) {
    switch (level) {
    case Medium:
        return "on";
    case High:
        return "on (high)";
    case View:
        return "on (debug view)";
    default:
        return "off";
    }
}

/// A map's side in texels; 0 when off.
inline constexpr std::uint32_t MapSize(std::uint32_t level) {
    return level == High ? 256u : (level == Medium || level == View) ? 128u : 0u;
}

/// Segments a half chord of the march's SHAFTS builds for the level, pushed to them
/// (point_volumetric.comp shaft_segments); 6 is the count of the build without SHAFTS.
inline constexpr std::uint32_t Segments(std::uint32_t level) {
    return level == High ? 12u : 6u;
}

/// Map layers: one per light record the lamp fog takes (vk_volumetric_light.cpp FogMaxLights,
/// tied there by a static_assert).
inline constexpr std::uint32_t MaxMaps = 64;

/// The instance mask the map rays trace: 4, what the ray traced lamp shadows trace
/// (vk_rt_shadow.cpp LampMask, point_shadow_ray.comp's 0x04): everything but cut-out cards.
inline constexpr std::uint32_t SceneMask = 4;

/// The blind sphere at the light's centre, m (point_shadow_ray.comp LAMP_CLEARANCE): what lies
/// closer to the flame than this (a torch's stick, the lantern's cage, the hand) casts nothing.
inline constexpr float Clearance = 0.35f;

/// lamp_fog_shaft_map.comp's ray start: Clearance, at most half the light's radius.
inline float Blind(float radius) {
    return std::min(Clearance, 0.5f * radius);
}

/// A texel lets the light through to a point whose distance from the centre over the radius is
/// at most its free distance over the radius plus this (pushed: point_volumetric.comp shaft_bias).
inline constexpr float Bias = 0.01f;

/// Bytes of the map image (R16F, MaxMaps layers) for the level.
inline constexpr std::uint64_t MapBytes(std::uint32_t level) {
    return std::uint64_t(MapSize(level)) * MapSize(level) * 2u * MaxMaps;
}

/// Map rays in a frame with `lights` records, at most (records the march skips or whose sphere
/// lies wholly behind the camera trace none).
inline constexpr std::uint64_t MapRays(std::uint32_t level, std::uint32_t lights) {
    return std::uint64_t(MapSize(level)) * MapSize(level) * std::min(lights, MaxMaps);
}

/// The octahedral map (point_volumetric.comp OctEncode, lamp_fog_shaft_map.comp OctDecode): a
/// direction to a point of [-1, 1]^2 (+z at the centre, -z at the four corners) and back.
inline std::array<float, 2> OctEncode(std::array<float, 3> n) {
    const float sum = std::abs(n[0]) + std::abs(n[1]) + std::abs(n[2]);
    const float x = n[0] / sum, y = n[1] / sum, z = n[2] / sum;
    if (z < 0.0f) {
        return {(1.0f - std::abs(y)) * (x >= 0.0f ? 1.0f : -1.0f),
                (1.0f - std::abs(x)) * (y >= 0.0f ? 1.0f : -1.0f)};
    }
    return {x, y};
}

inline std::array<float, 3> OctDecode(std::array<float, 2> e) {
    float x = e[0], y = e[1];
    const float z = 1.0f - std::abs(x) - std::abs(y);
    if (z < 0.0f) {
        const float ox = x, oy = y;
        x = (1.0f - std::abs(oy)) * (ox >= 0.0f ? 1.0f : -1.0f);
        y = (1.0f - std::abs(ox)) * (oy >= 0.0f ? 1.0f : -1.0f);
    }
    const float length = std::sqrt(x * x + y * y + z * z);
    return {x / length, y / length, z / length};
}

/// Where a segment's sample of the map lies along the view ray (m): the march integrates the
/// inverse-square core per segment exactly as the difference of atan((t - along) / q) between the
/// segment's ends (`previous`, `angle`); the point where half of that lies on either side.
inline float EnergyMiddle(float along, float q, float previous, float angle) {
    return along + q * std::tan(0.5f * (previous + angle));
}

/// The share of the four gathered texels (free distance over the radius) that let the light
/// reach a point at `distance_ratio` (its distance from the centre over the radius).
inline float Lit(const std::array<float, 4>& free_ratio, float distance_ratio) {
    float lit = 0.0f;
    for (const float f : free_ratio) {
        lit += f >= distance_ratio - Bias ? 0.25f : 0.0f;
    }
    return lit;
}

} // namespace Vulkan::LampFogShafts
''',
    H + "lamp_fog_shaft_map.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2 or 3 only (made only then): the lamp
// fog's shadow maps (lamp_fog_shafts.h). Layer k is light record k of the lamp fog's list (the
// march's own records, camera view space). Texel (x, y) of a layer: the direction from the
// light's centre that the texel's centre decodes to (OctDecode); one ray along it through the
// frame's ray traced scene (instance mask `mask`, 4: what the ray traced lamp shadows trace),
// from the blind sphere (`clearance`, at most half the radius) out to the light's radius, to the
// nearest hit; the texel keeps the hit's distance over the radius, 1 where nothing is hit. A
// record the march skips (not finite, inverse radius squared not positive) or whose sphere lies
// wholly behind the camera (the march's view rays have z > 0 and never meet it) gets 1 in every
// texel and traces no ray. Every layer below `count` is written whole every frame.
#version 460
#extension GL_EXT_scalar_block_layout : require
#extension GL_EXT_ray_query : require

layout(local_size_x = 8, local_size_y = 8) in;
layout(scalar, binding = 0) readonly buffer Lights { uint d[]; } lights;
layout(binding = 1) uniform accelerationStructureEXT scene;
layout(binding = 2, r16f) uniform writeonly image2DArray maps;
layout(push_constant) uniform Params {
    uint count;      // light records (layers written)
    uint mask;       // the scene's instance mask (low 8 bits)
    float clearance; // the blind sphere at the centre, m
};

bool finite3(vec3 v) { return !any(isnan(v)) && !any(isinf(v)); }

// [-1, 1]^2 to a unit direction: +z at the centre, -z at the four corners (lamp_fog_shafts.h
// OctDecode; point_volumetric.comp's OctEncode is its inverse).
vec3 OctDecode(vec2 e) {
    vec3 v = vec3(e, 1.0 - abs(e.x) - abs(e.y));
    if (v.z < 0.0) {
        v.xy = (1.0 - abs(e.yx)) * vec2(e.x >= 0.0 ? 1.0 : -1.0, e.y >= 0.0 ? 1.0 : -1.0);
    }
    return normalize(v);
}

void main() {
    ivec3 texel = ivec3(gl_GlobalInvocationID);
    ivec2 size = imageSize(maps).xy;
    if (any(greaterThanEqual(texel.xy, size)) || uint(texel.z) >= count) return;
    uint at = uint(texel.z) * 16u;
    vec3 centre = uintBitsToFloat(uvec3(lights.d[at], lights.d[at + 1u], lights.d[at + 2u]));
    float inverse_radius_squared = uintBitsToFloat(lights.d[at + 3u]);
    float free_ratio = 1.0;
    if (finite3(centre) && !isnan(inverse_radius_squared) && !isinf(inverse_radius_squared) &&
        inverse_radius_squared > 0.0) {
        float radius = inversesqrt(inverse_radius_squared);
        if (centre.z + radius > 0.0) {
            vec2 e = (vec2(texel.xy) + 0.5) / vec2(size) * 2.0 - 1.0;
            vec3 direction = OctDecode(e);
            rayQueryEXT query;
            // every instance opaque: one proceed walks the whole ray to the nearest hit
            rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, mask & 255u, centre,
                                  min(clearance, 0.5 * radius), direction, radius);
            rayQueryProceedEXT(query);
            if (rayQueryGetIntersectionTypeEXT(query, true) !=
                gl_RayQueryCommittedIntersectionNoneEXT) {
                free_ratio = rayQueryGetIntersectionTEXT(query, true) / radius;
            }
        }
    }
    imageStore(maps, texel, vec4(free_ratio));
}
''',
    T + "test_lamp_fog_shafts.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r80_lamp-fog-shafts): the lamp fog shafts' pure parts (lamp_fog_shafts.h): the knob's
// text, the sizes and ray counts of each level, the octahedral map's encode and decode (every
// texel centre of both map sizes comes back to its own texel), the segment's sample point (it
// halves the segment's inverse-square energy) and the share of lit texels with the bias.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string_view>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shafts.h"

using namespace Vulkan::LampFogShafts;

int main() {
    // The knob: exactly "0" to "3"; anything else (also unset and empty) is off.
    assert(Parse(nullptr) == Off && Parse("") == Off);
    assert(Parse("0") == Off && Parse("1") == Medium && Parse("2") == High && Parse("3") == View);
    assert(Parse("4") == Off && Parse("10") == Off && Parse("1x") == Off && Parse(" 1") == Off &&
           Parse("on") == Off && Parse("-1") == Off);
    assert(std::string_view(Name(Off)) == "off" && std::string_view(Name(Medium)) == "on" &&
           std::string_view(Name(7)) == "off");

    // Sizes: 128 texels for 1 and 3, 256 for 2; segments 12 only for 2.
    assert(MapSize(Off) == 0 && MapSize(Medium) == 128 && MapSize(High) == 256 &&
           MapSize(View) == 128 && MapSize(4) == 0);
    assert(Segments(Medium) == 6 && Segments(High) == 12 && Segments(View) == 6);
    assert(MapBytes(Medium) == 2u * 1024 * 1024 && MapBytes(High) == 8u * 1024 * 1024 &&
           MapBytes(Off) == 0);
    assert(MapRays(Medium, 2) == 2u * 16384 && MapRays(High, 16) == 16u * 65536 &&
           MapRays(Medium, 100) == 64u * 16384 && MapRays(Off, 8) == 0);
    assert(SceneMask == 4 && MaxMaps == 64);

    // The blind sphere: 0.35 m, at most half the radius.
    assert(Blind(10.0f) == Clearance && Blind(0.4f) == 0.2f && Blind(0.7f) == Clearance);

    // The octahedral map: +z at the centre, -z at the corners, the axes on the edges' middles.
    {
        const auto c = OctEncode({0.0f, 0.0f, 1.0f});
        assert(c[0] == 0.0f && c[1] == 0.0f);
        const auto x = OctEncode({1.0f, 0.0f, 0.0f});
        assert(x[0] == 1.0f && x[1] == 0.0f);
        const auto y = OctEncode({0.0f, -1.0f, 0.0f});
        assert(y[0] == 0.0f && y[1] == -1.0f);
        const auto back = OctEncode({0.0f, 0.0f, -1.0f});
        assert(std::abs(back[0]) == 1.0f && std::abs(back[1]) == 1.0f);
        const auto down = OctDecode({1.0f, 1.0f});
        assert(std::abs(down[2] + 1.0f) < 1e-6f);
    }
    // Every texel centre of both sizes decodes to a unit direction that encodes into the same
    // texel.
    for (const std::uint32_t size : {128u, 256u}) {
        for (std::uint32_t ty = 0; ty < size; ++ty) {
            for (std::uint32_t tx = 0; tx < size; ++tx) {
                const std::array<float, 2> e{(float(tx) + 0.5f) / float(size) * 2.0f - 1.0f,
                                             (float(ty) + 0.5f) / float(size) * 2.0f - 1.0f};
                const auto d = OctDecode(e);
                assert(std::abs(d[0] * d[0] + d[1] * d[1] + d[2] * d[2] - 1.0f) < 1e-5f);
                const auto back = OctEncode(d);
                const auto bx = std::uint32_t((back[0] * 0.5f + 0.5f) * float(size));
                const auto by = std::uint32_t((back[1] * 0.5f + 0.5f) * float(size));
                assert(bx == tx && by == ty);
            }
        }
    }

    // A segment's sample point lies in the segment and halves its inverse-square energy.
    for (const float along : {-3.0f, 0.5f, 4.0f, 12.0f}) {
        for (const float q : {0.05f, 0.4f, 2.0f}) {
            for (const float t0 : {0.0f, 1.5f, 6.0f}) {
                const float t1 = t0 + 1.25f;
                const float a0 = std::atan((t0 - along) / q), a1 = std::atan((t1 - along) / q);
                const float m = EnergyMiddle(along, q, a0, a1);
                assert(m >= t0 - 1e-3f && m <= t1 + 1e-3f);
                const float am = std::atan((m - along) / q);
                assert(std::abs((am - a0) - (a1 - am)) < 1e-4f);
            }
        }
    }

    // The lit share of four texels; a point up to Bias beyond a texel's free distance is lit.
    assert(Lit({1.0f, 1.0f, 1.0f, 1.0f}, 0.5f) == 1.0f);
    assert(Lit({0.2f, 0.2f, 0.2f, 0.2f}, 0.5f) == 0.0f);
    assert(Lit({0.2f, 1.0f, 0.2f, 1.0f}, 0.5f) == 0.5f);
    assert(Lit({0.5f, 0.5f, 0.5f, 0.5f}, 0.5f + 0.5f * Bias) == 1.0f);
    assert(Lit({0.5f, 0.5f, 0.5f, 0.5f}, 0.5f + 2.0f * Bias) == 0.0f);

    std::printf("lamp fog shafts: all checks passed\n");
    return 0;
}
''',
}

EDITS = {
    H + "point_volumetric.comp": [
        (r'''layout(binding = 3, rgba16f) uniform image2D fog_out;
''', r'''layout(binding = 3, rgba16f) uniform image2D fog_out;
#ifdef SHAFTS
// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2 or 3 only (the builds made with SHAFTS,
// VIEW for 3; the build without it is the pass of before, word for word): the lamp fog's shadow
// maps (lamp_fog_shaft_map.comp), layer k for light record k, each texel the free distance from
// the light's centre along its direction over the light's radius
layout(binding = 4) uniform sampler2DArray shaft_maps;
#endif
'''),
        (r'''    float glow_size;
};
''', r'''    float glow_size;
#ifdef SHAFTS
    // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS only, from the host (lamp_fog_shafts.h
    // Bias and Segments): Lit()'s bias over the radius and inscatterShadowed()'s segments
    float shaft_bias;
    uint shaft_segments;
#endif
};
'''),
        (r'''    return energy * 0.025;
}

void main() {
''', r'''    return energy * 0.025;
}

#ifdef SHAFTS
// bbport (r80_lamp-fog-shafts): a direction to the octahedral map's [-1, 1]^2 (+z at the centre,
// -z at the four corners; lamp_fog_shafts.h OctEncode; lamp_fog_shaft_map.comp's OctDecode is its
// inverse).
vec2 OctEncode(vec3 n) {
    n /= abs(n.x) + abs(n.y) + abs(n.z);
    if (n.z < 0.0) {
        return (1.0 - abs(n.yx)) * vec2(n.x >= 0.0 ? 1.0 : -1.0, n.y >= 0.0 ? 1.0 : -1.0);
    }
    return n.xy;
}

// How much of light `layer` reaches the fog at p (view space): the share of the four map texels
// around the direction from the light's centre to p whose free distance reaches p's distance less
// shaft_bias of the radius (lamp_fog_shafts.h Lit and Bias). A point at the centre is lit; so is
// any point within the maps' blind sphere (no hit is kept nearer than it).
float Lit(vec3 p, vec3 centre, float radius, uint layer) {
    vec3 v = p - centre;
    float d = length(v);
    if (!(d > 0.0)) return 1.0;
    vec2 uv = OctEncode(v / d) * 0.5 + 0.5;
    vec4 free_ratio = textureGather(shaft_maps, vec3(uv, float(layer)), 0);
    return dot(step(vec4(d / radius - shaft_bias), free_ratio), vec4(0.25));
}

// inscatter() with shaft_segments segments (1 to 32; lamp_fog_shafts.h Segments) and each
// segment's light times Lit() at the point where the segment's exact inverse-square energy is
// split in half (lamp_fog_shafts.h EnergyMiddle); a segment the window gives no light reads no
// texel. `unshadowed` gathers the light without the maps (the debug view's blue is the
// difference).
float inscatterShadowed(vec3 ray, vec3 centre, float radius, float along, float q, float begin,
                        float end, uint layer, inout float unshadowed) {
    if (end <= begin) return 0.0;
    uint segments = clamp(shaft_segments, 1u, 32u);
    float ds = (end - begin) / float(segments);
    float energy = 0.0;
    float previous = atan((begin - along) / q);
    for (uint i = 0u; i < segments; ++i) {
        float t0 = begin + float(i) * ds;
        float angle = atan((t0 + ds - along) / q);
        float t = t0 + 0.5 * ds;
        float x = length(ray * t - centre) / radius;
        float window = clamp(1.0 - x * x * x * x, 0.0, 1.0);
        float segment = (angle - previous) * window * window * exp(-0.025 * t) * 0.025;
        if (segment > 0.0) {
            float middle = along + q * tan(0.5 * (previous + angle));
            unshadowed += segment;
            energy += segment * Lit(ray * middle, centre, radius, layer);
        }
        previous = angle;
    }
    return energy;
}
#endif

void main() {
'''),
        (r'''    vec3 scattering = vec3(0.0);
''', r'''    vec3 scattering = vec3(0.0);
#ifdef VIEW
    float view_lit = 0.0, view_lost = 0.0; // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=3
#endif
'''),
        (r'''        scattering += rgb * (ENERGY * core * core / q) *
            (inscatter(ray, centre, radius, along, q, begin, nearest) +
             inscatter(ray, centre, radius, along, q, nearest, end));
    }
    vec4 previous = imageLoad(fog_out, px);
    imageStore(fog_out, px, vec4(previous.rgb + scattering * (0.35 * intensity), 0.0));
}
''', r'''#ifdef SHAFTS
        // bbport (r80_lamp-fog-shafts): each segment's light times the share of its map texels
        // that reach the segment's sample point (inscatterShadowed)
        float unshadowed = 0.0;
        float lit = inscatterShadowed(ray, centre, radius, along, q, begin, nearest, k, unshadowed) +
                    inscatterShadowed(ray, centre, radius, along, q, nearest, end, k, unshadowed);
        float weight = ENERGY * core * core / q;
        scattering += rgb * weight * lit;
#ifdef VIEW
        view_lit += luminance * weight * lit;
        view_lost += luminance * weight * max(unshadowed - lit, 0.0);
#endif
#else
        scattering += rgb * (ENERGY * core * core / q) *
            (inscatter(ray, centre, radius, along, q, begin, nearest) +
             inscatter(ray, centre, radius, along, q, nearest, end));
#endif
    }
    vec4 previous = imageLoad(fog_out, px);
#ifdef VIEW
    // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=3: in place of the lamp fog, orange the light
    // that reaches the fog and blue the light the maps cut off, both 4 times as bright
    imageStore(fog_out, px, vec4(previous.rgb + vec3(view_lit, 0.5 * view_lit, view_lost) *
                                                    (4.0 * 0.35 * intensity), 0.0));
#else
    imageStore(fog_out, px, vec4(previous.rgb + scattering * (0.35 * intensity), 0.0));
#endif
}
'''),
    ],
    R + "vk_volumetric_light.h": [
        (r'''#include "video_core/renderer_vulkan/lamp_fog_lights.h"
''', r'''#include "video_core/renderer_vulkan/lamp_fog_lights.h"
#include "video_core/renderer_vulkan/lamp_fog_shafts.h" // bbport (r80_lamp-fog-shafts)
'''),
        (r'''    void SetCamera(const LampFog::Camera& camera) { fog_camera = camera; }
''', r'''    void SetCamera(const LampFog::Camera& camera) { fog_camera = camera; }
    /// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS set only: this frame's ray traced scene
    /// (RtShadow::Scene, in the camera's view space) for the next Composite's lamp fog shadow
    /// maps. Taken (and cleared) by that lamp fog; null: the lamp fog of before.
    void SetLampScene(vk::AccelerationStructureKHR scene_) noexcept { lamp_scene = scene_; }
'''),
        (r'''    void RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h);
''', r'''    void RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h);
    // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS: the shadow maps' pass, the march's SHAFTS
    // build and the maps, made at the first lamp fog with lights and a scene; the maps and the
    // shadowed march in place of RecordLampFog's pass
    bool ShaftsReady(u32 level);
    void RecordShafts(vk::AccelerationStructureKHR shaft_scene, u32 count, float intensity,
                      float glow_size, std::vector<u32> data,
                      const vk::DescriptorBufferInfo& constants,
                      const vk::DescriptorBufferInfo& records, const vk::DescriptorImageInfo& depth,
                      const vk::DescriptorImageInfo& out, u32 w, u32 h);
'''),
        (r'''    LampFog::Camera fog_camera;
''', r'''    LampFog::Camera fog_camera;
    // bbport (r80_lamp-fog-shafts): the scene SetLampScene gave; the passes ShaftsReady made; the
    // maps (a layer per light record, shaft_size texels a side); the 600-frame line's counts and
    // the once-line's flag
    vk::AccelerationStructureKHR lamp_scene{};
    Pass shaft_map, point_shafts;
    VideoCore::UniqueImage shaft_maps;
    vk::UniqueImageView shaft_maps_view;
    u32 shaft_size = 0;
    u64 shafts_frames = 0, shafts_shadowed = 0;
    bool shafts_tried = false, shafts_failed = false, shafts_said = false;
'''),
    ],
    R + "vk_volumetric_light.cpp": [
        (r'''#include "video_core/host_shaders/point_volumetric_comp.h"
''', r'''#include "video_core/host_shaders/point_volumetric_comp.h"
// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS: the lamp fog's shadow maps (ray queries) and
// the march's builds reading them
#include "video_core/host_shaders/lamp_fog_shaft_map_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
'''),
        (r'''static_assert(FogBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
''', r'''static_assert(FogBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
// bbport (r80_lamp-fog-shafts): a shadow map layer for every light record the lamp fog can draw
static_assert(FogMaxLights == LampFogShafts::MaxMaps && LampFog::AsListedLimit <= FogMaxLights);
constexpr vk::ImageSubresourceRange ShaftRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0,
                                               LampFogShafts::MaxMaps};
'''),
        (r'''void VolumetricLight::RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h) {
''', r'''// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2 or 3 only, made at the first lamp fog
// with lights and a ray traced scene: the shadow maps' pass (ray queries), the march's SHAFTS
// build for the level (the VIEW build for 3; the segment count is a push constant) and the maps
// (R16F, MapSize texels a side, a layer per light record the lamp fog takes). Failing leaves the
// lamp fog unshadowed, as with the knob off.
bool VolumetricLight::ShaftsReady(u32 level) {
    if (shafts_tried) {
        return !shafts_failed;
    }
    shafts_tried = true;
    using enum vk::DescriptorType;
    const u32 size = LampFogShafts::MapSize(level);
    const std::span<const u32> march = level == LampFogShafts::View
                                           ? std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_VIEW_COMP)
                                           : std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_COMP);
    const bool made =
        size != 0 && size % 8 == 0 && EffectPass::StorageFormat(instance, vk::Format::eR16Sfloat) &&
        EffectPass::HasRoom(instance, LampFogShafts::MapBytes(level)) &&
        CreatePass(shaft_map, {eStorageBuffer, eAccelerationStructureKHR, eStorageImage},
                   LAMP_FOG_SHAFT_MAP_COMP, 3 * sizeof(u32), "Lamp fog shaft maps") &&
        CreatePass(point_shafts,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
                    eCombinedImageSampler},
                   march, 5 * sizeof(u32), "Point volumetric (shafts)");
    if (!made) {
        shafts_failed = true;
        std::printf("Volumetric lighting (r80): lamp fog shafts off - their passes or maps could "
                    "not be made; the lamp fog stays unshadowed\n");
        return false;
    }
    const auto device = instance.GetDevice();
    shaft_maps = VideoCore::UniqueImage(device, instance.GetAllocator());
    shaft_maps.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16Sfloat,
        .extent = {size, size, 1}, .mipLevels = 1, .arrayLayers = LampFogShafts::MaxMaps,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    shaft_maps_view = Check<"create lamp fog shaft map view">(device.createImageViewUnique({
        .image = vk::Image(shaft_maps), .viewType = vk::ImageViewType::e2DArray,
        .format = vk::Format::eR16Sfloat, .subresourceRange = ShaftRange,
    }));
    SetObjectName(device, vk::Image(shaft_maps), "Lamp fog shaft maps");
    shaft_size = size;
    return true;
}

// bbport (r80_lamp-fog-shafts): in place of RecordLampFog's pass while the shafts run: the light
// records to the GPU as there, the shadow maps of the first `count` records (a pinned profile row
// of their own, "Lighting: lamp fog shafts"), then the march's SHAFTS build under the lamp fog's
// row. `data`, `constants`, `records`, `depth` and `out` are RecordLampFog's.
void VolumetricLight::RecordShafts(vk::AccelerationStructureKHR shaft_scene, u32 count,
                                   float intensity, float glow_size, std::vector<u32> data,
                                   const vk::DescriptorBufferInfo& constants,
                                   const vk::DescriptorBufferInfo& records,
                                   const vk::DescriptorImageInfo& depth,
                                   const vk::DescriptorImageInfo& out, u32 w, u32 h) {
    struct MapParams {
        u32 count, mask;
        float clearance;
    };
    static_assert(sizeof(MapParams) == 12);
    struct PointParams { // point_volumetric.comp Params with SHAFTS
        u32 count;
        float intensity, glow_size;
        float shaft_bias;
        u32 shaft_segments;
    };
    static_assert(sizeof(PointParams) == 20);
    const u32 layers = std::min(count, LampFogShafts::MaxMaps);
    const MapParams map_params{layers, LampFogShafts::SceneMask, LampFogShafts::Clearance};
    const PointParams params{count, intensity, glow_size, LampFogShafts::Bias,
                             LampFogShafts::Segments(LampFogShafts::Level())};
    const vk::Buffer buffer = fog_data->Handle();
    const vk::DeviceSize data_bytes = data.size() * sizeof(u32); // before the capture moves `data`
    const vk::DescriptorImageInfo maps_out{{}, *shaft_maps_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo maps_in{*sampler, *shaft_maps_view, vk::ImageLayout::eGeneral};
    const u32 groups = shaft_size / 8; // lamp_fog_shaft_map.comp: 8x8 texels a workgroup
    EffectPass::Mark(80, "lamp fog shafts", true);
    scheduler.RecordCrumb(
        {.name = "Lamp fog shaft maps"},
        [map_params, records, maps_out, buffer, data_bytes, data = std::move(data), groups, layers,
         scene = shaft_scene, image = vk::Image(shaft_maps), pipeline = *shaft_map.pipeline,
         layout = *shaft_map.layout](vk::CommandBuffer cmd) {
            const vk::MemoryBarrier2 to_transfer{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
            cmd.updateBuffer(buffer, 0, data_bytes, data.data());
            Before(cmd);
            // The layers below `layers` are written whole every frame; the others are not read.
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ShaftRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const std::array<vk::WriteDescriptorSet, 3> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &records},
                {.pNext = &scene_info, .dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &maps_out},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(map_params),
                              &map_params);
            cmd.dispatch(groups, groups, layers);
            After(cmd);
        });
    EffectPass::Mark(9, "lamp fog");
    scheduler.RecordCrumb(
        {.name = "Lamp fog (shafts)"},
        [params, constants, records, depth, out, maps_in, w, h, pipeline = *point_shafts.pipeline,
         layout = *point_shafts.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 5> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &records},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &maps_in},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            After(cmd);
        });
}

void VolumetricLight::RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h) {
'''),
        (r'''    const vk::DescriptorImageInfo out{{}, *point_view, vk::ImageLayout::eGeneral};
    EffectPass::Mark(9, "lamp fog");
''', r'''    const vk::DescriptorImageInfo out{{}, *point_view, vk::ImageLayout::eGeneral};
    // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS (lamp_fog_shafts.h; read once, said once at
    // the first lamp fog with lights): with this frame's ray traced scene (SetLampScene) the
    // shadow maps and the march's SHAFTS build (RecordShafts) run in place of the pass below. Off
    // (the default), no scene this frame, or passes that could not be made: the pass below, as
    // before. With the knob set, every 600 lamp fog frames a line of how many had the maps.
    const vk::AccelerationStructureKHR shaft_scene = std::exchange(lamp_scene, {});
    const u32 shaft_level = LampFogShafts::Level();
    if (!std::exchange(shafts_said, true)) {
        if (shaft_level == LampFogShafts::Off) {
            std::printf("Volumetric lighting (r80): lamp fog shafts off (BB_LAMP_FOG_SHAFTS not 1, "
                        "2 or 3): the lamp fog is not shadowed\n");
        } else {
            std::printf("Volumetric lighting (r80): lamp fog shafts %s (BB_LAMP_FOG_SHAFTS %u): a "
                        "%ux%u ray traced shadow map per lamp fog light, all rebuilt every frame "
                        "(scene mask 0x%x, blind within %.2f m of the light), %u segments a half "
                        "chord; only in frames with a ray traced scene\n",
                        LampFogShafts::Name(shaft_level), shaft_level,
                        LampFogShafts::MapSize(shaft_level), LampFogShafts::MapSize(shaft_level),
                        LampFogShafts::SceneMask, double(LampFogShafts::Clearance),
                        LampFogShafts::Segments(shaft_level));
        }
    }
    if (shaft_level != LampFogShafts::Off) {
        const bool shadowed = shaft_scene && ShaftsReady(shaft_level);
        shafts_shadowed += shadowed ? 1 : 0;
        if (++shafts_frames == 600) {
            std::printf("Volumetric lighting (r80): lamp fog shafts in %llu of 600 lamp fog frames "
                        "(the others had no ray traced scene, or the passes could not be made); "
                        "this frame %u lights, at most %llu map rays\n",
                        static_cast<unsigned long long>(shafts_shadowed), params.count,
                        static_cast<unsigned long long>(
                            shadowed ? LampFogShafts::MapRays(shaft_level, params.count) : 0));
            shafts_frames = shafts_shadowed = 0;
        }
        if (shadowed) {
            RecordShafts(shaft_scene, params.count, params.intensity, params.glow_size,
                         std::move(data), constants, records, depth, out, w, h);
            return;
        }
    }
    EffectPass::Mark(9, "lamp fog");
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
''', r'''        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS set and lamp fog on only: this frame's
        // ray traced scene for the lamp fog's shadow maps. PrepareScene returns at once when the
        // TLAS already holds every entry of the frame, else it builds or refits it again (r17
        // tlas_prepared).
        if (LampFogShafts::Level() != LampFogShafts::Off &&
            BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
            scheduler.EndRendering();
            volumetric_light->SetLampScene(rt_shadow->PrepareScene()
                                               ? rt_shadow->Scene()
                                               : vk::AccelerationStructureKHR{});
        }
        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
'''),
        (r'''        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        volumetric_light->Composite();
''', r'''        volumetric_light->SetCamera({camera.view, camera.inv_view, camera.valid});
        // bbport (r80_lamp-fog-shafts): as before the upscaler's composite above
        if (LampFogShafts::Level() != LampFogShafts::Off &&
            BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
            scheduler.EndRendering();
            volumetric_light->SetLampScene(rt_shadow->PrepareScene()
                                               ? rt_shadow->Scene()
                                               : vk::AccelerationStructureKHR{});
        }
        volumetric_light->Composite();
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)
''', r'''#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)
#include "video_core/renderer_vulkan/lamp_fog_shafts.h"  // bbport (r80_lamp-fog-shafts)
'''),
        (r'''    const auto& s = BbSettings::Get();
    return SunRayTraced() || s.graphics_rt_point_shadows.load(std::memory_order_relaxed) ||
''', r'''    const auto& s = BbSettings::Get();
    // bbport (r80_lamp-fog-shafts): and BB_LAMP_FOG_SHAFTS set with lamp fog on: the lamp fog's
    // shadow maps trace the scene (VolumetricLight::RecordShafts)
    return (LampFogShafts::Level() != LampFogShafts::Off &&
            s.effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) ||
           SunRayTraced() || s.graphics_rt_point_shadows.load(std::memory_order_relaxed) ||
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''add_host_shader(point_volumetric.comp point_volumetric_comp)
''', r'''add_host_shader(point_volumetric.comp point_volumetric_comp)
# bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2, 3 only: the lamp fog's shadow maps (ray
# queries) and the march's builds reading them (SHAFTS for 1 and 2; VIEW the debug view for 3);
# the build above is unchanged
add_host_shader(lamp_fog_shaft_map.comp lamp_fog_shaft_map_comp)
add_host_shader(point_volumetric.comp point_volumetric_shafts_comp SHAFTS=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_view_comp SHAFTS=1 VIEW=1)
'''),
        (r'''add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
''', r'''add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
# bbport (r80_lamp-fog-shafts): the lamp fog shafts' knob, sizes and map math (lamp_fog_shafts.h)
add_executable(lamp-fog-shafts-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shafts.cpp)
target_compile_options(lamp-fog-shafts-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-shafts-test PRIVATE ..)
'''),
    ],
    "engine/build.sh": [
        (r'''    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_still_check.cpp -o out/rt-still-check-test
    out/rt-still-check-test
''', r'''    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_still_check.cpp -o out/rt-still-check-test
    out/rt-still-check-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_lamp_fog_shafts.cpp -o out/lamp-fog-shafts-test
    out/lamp-fog-shafts-test
'''),
    ],
    T + "test_effect_pipelines.cpp": [
        (r'''#include "video_core/host_shaders/point_volumetric_comp.h"
''', r'''#include "video_core/host_shaders/point_volumetric_comp.h"
// bbport (r80_lamp-fog-shafts): the lamp fog march's builds that read the shadow maps
#include "video_core/host_shaders/point_volumetric_shafts_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
'''),
        (r'''        {"point volumetric",
         POINT_VOLUMETRIC_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
''', r'''        {"point volumetric",
         POINT_VOLUMETRIC_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
        // bbport (r80_lamp-fog-shafts): as VolumetricLight::ShaftsReady makes them: the pass's own
        // bindings, then the shadow maps (2D array); 20 bytes of push constants (the bias and the
        // segment count added). The maps' own pass needs ray queries, which this test's device
        // does not turn on: not built here.
        {"point volumetric (shafts)",
         POINT_VOLUMETRIC_SHAFTS_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
        {"point volumetric (shafts view)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
'''),
    ],
    "README.md": [
        (r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |
''', r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |

### Lamp fog shafts

A test of shadows in the lamp fog (`effect_point_fog`): the glow of every lamp, candle and of the hunter's torch or lantern is then cut where something in the ray traced scene stands between the light and the fog, the hunter included. Read once when the game starts; text that is not one of the values below leaves it off. It runs only while ray traced lighting is on (`effect_ray_tracing`, which is on while the ray traced sun, lamp shadows or bounced light, or the virtual shadow maps are on; the variable never turns it on) and only where there is lamp fog (`effect_point_fog` on). With the virtual shadow maps as the only ray traced feature, setting it builds the ray traced scene for the lamp fog alone.

| Variable | What it does | Default |
|---|---|---|
| `BB_LAMP_FOG_SHAFTS` | `1`: every frame, a 128x128 ray traced shadow map for each light of the lamp fog (up to 64), and the fog of each light is cut by it; `2`: 256x256 maps and twice the samples along each view ray; `3`: as `1`, with the lamp fog shown as a debug view (orange where the light reaches the fog, blue where the maps cut it off); `0` off | `0` |
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "point_volumetric.comp": [("#ifdef SHAFTS", 4), ("#ifdef VIEW", 3), ("#ifdef HIGH", 0),
                                  ("layout(binding = 4) uniform sampler2DArray shaft_maps;", 1),
                                  ("const uint SEGMENTS = 6u;", 1), ("uint shaft_segments;", 1), ("float shaft_bias;", 1),
                                  ("uint segments = clamp(shaft_segments, 1u, 32u);", 1),
                                  ("d / radius - shaft_bias", 1), ("SHAFT_BIAS", 0),
                                  ("textureGather(shaft_maps", 1),
                                  ("inscatterShadowed(ray, centre, radius, along, q, begin, nearest, k, unshadowed)", 1),
                                  ("inscatter(ray, centre, radius, along, q, begin, nearest) +", 1),
                                  ("imageStore(fog_out, px, vec4(previous.rgb + scattering * (0.35 * intensity), 0.0));", 1)],
    H + "lamp_fog_shaft_map.comp": [("#extension GL_EXT_ray_query : require", 1),
                                    ("layout(binding = 2, r16f) uniform writeonly image2DArray maps;", 1),
                                    ("rayQueryProceedEXT(query);", 1)],
    R + "lamp_fog_shafts.h": [("inline constexpr std::uint32_t MaxMaps = 64;", 1),
                              ("inline constexpr std::uint32_t SceneMask = 4;", 1),
                              ("inline constexpr float Clearance = 0.35f;", 1),
                              ("inline constexpr float Bias = 0.01f;", 1),
                              ('std::getenv("BB_LAMP_FOG_SHAFTS")', 1)],
    R + "vk_volumetric_light.h": [("void SetLampScene(vk::AccelerationStructureKHR scene_) noexcept { lamp_scene = scene_; }", 1),
                                  ("bool ShaftsReady(u32 level);", 1), ("Pass shaft_map, point_shafts;", 1)],
    R + "vk_volumetric_light.cpp": [("EffectPass::Mark(80, \"lamp fog shafts\", true);", 1),
                                    ("EffectPass::Mark(9, \"lamp fog\");", 2),
                                    ("static_assert(FogMaxLights == LampFogShafts::MaxMaps", 1),
                                    ("RecordShafts(shaft_scene, params.count, params.intensity, params.glow_size,", 1),
                                    ("const vk::AccelerationStructureKHR shaft_scene = std::exchange(lamp_scene, {});", 1),
                                    ("cmd.dispatch(groups, groups, layers);", 1),
                                    ("POINT_VOLUMETRIC_SHAFTS_HIGH_COMP", 0), ("POINT_VOLUMETRIC_SHAFTS_VIEW_COMP", 1),
                                    ("march, 5 * sizeof(u32), \"Point volumetric (shafts)\");", 1),
                                    ("static_assert(sizeof(PointParams) == 20);", 1),
                                    ("LampFogShafts::Segments(LampFogShafts::Level())};", 1),
                                    ("LAMP_FOG_SHAFT_MAP_COMP", 1),
                                    ("Volumetric lighting (r80): lamp fog shafts off (BB_LAMP_FOG_SHAFTS not 1, ", 1)],
    R + "vk_rasterizer_effects.cpp": [("volumetric_light->SetLampScene(rt_shadow->PrepareScene()", 2),
                                      ("if (LampFogShafts::Level() != LampFogShafts::Off &&\n            BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {", 2)],
    R + "vk_rt_shadow.cpp": [("return (LampFogShafts::Level() != LampFogShafts::Off &&\n            s.effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) ||", 1),
                             ('#include "video_core/renderer_vulkan/lamp_fog_shafts.h"', 1)],
    "engine/gpu/CMakeLists.txt": [("add_host_shader(point_volumetric.comp point_volumetric_comp)", 1),
                                  ("add_host_shader(lamp_fog_shaft_map.comp lamp_fog_shaft_map_comp)", 1),
                                  ("point_volumetric_shafts_comp SHAFTS=1)", 1),
                                  ("HIGH=1", 0),
                                  ("point_volumetric_shafts_view_comp SHAFTS=1 VIEW=1)", 1),
                                  ("add_executable(lamp-fog-shafts-test", 1)],
    "engine/build.sh": [("tests/test_lamp_fog_shafts.cpp -o out/lamp-fog-shafts-test", 1)],
    T + "test_lamp_fog_shafts.cpp": [('#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shafts.h"', 1)],
    T + "test_effect_pipelines.cpp": [("POINT_VOLUMETRIC_SHAFTS_COMP,", 1),
                                      ("POINT_VOLUMETRIC_SHAFTS_HIGH_COMP", 0),
                                      ("POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,", 1)],
    "README.md": [("| `BB_LAMP_FOG_SHAFTS` |", 1), ("### Lamp fog shafts", 1),
                  ("the variable never turns it on", 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    R + "vk_volumetric_light.cpp": ["bool VolumetricLight::ShaftsReady(u32 level) {",
                                    "void VolumetricLight::RecordShafts(",
                                    "void VolumetricLight::RecordLampFog(",
                                    "const vk::DescriptorImageInfo out{{}, *point_view",
                                    "std::exchange(lamp_scene, {});",
                                    "            return;\n        }\n    }\n    EffectPass::Mark(9, \"lamp fog\");",
                                    "scheduler.RecordCrumb(\n        {.name = \"Lamp fog\"},"],
    R + "vk_rasterizer_effects.cpp": ["volumetric_light->SetLampScene(",
                                      "volumetric_light->Composite(upscaler->SceneColor(), \"the upscaler\");",
                                      "volumetric_light->SetLampScene(",
                                      "volumetric_light->Composite();"],
    H + "point_volumetric.comp": ["layout(binding = 3, rgba16f) uniform image2D fog_out;",
                                  "uniform sampler2DArray shaft_maps;", "float inscatter(",
                                  "float inscatterShadowed(", "void main() {"],
}


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


def new_state(path, text):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw, eol, cur = load(path)
    if cur == text:
        return "applied"
    raise SystemExit("%s exists and is not this patch's text" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R80_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    news = [(path, text, new_state(path, text)) for path, text in NEW_FILES.items()]
    states = {p[5] for p in plan} | {n[2] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                     ["%s %s" % (n[0], n[2]) for n in news]))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update({n[0]: n[1] for n in news})
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in plan:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            texts.update({n[0]: n[1] for n in news})
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(plan), len(news)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        for path, text, _ in news:
            texts[path] = text
            outs.append((path, text.replace("\n", "\r\n").encode("utf-8"), None))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r80tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r80tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path, text, _ in news:
        os.remove(os.path.join(ROOT, path))
    print("reverted")

main()
