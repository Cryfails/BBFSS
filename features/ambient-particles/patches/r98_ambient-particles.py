# r98_ambient-particles: FEATURE patch (order item 6, "Ambient particles and maybe metal sparks
# from transforming weapons", stage 1 only). Ambient motes in the air: dust and ash and a few
# embers, from a hashed lattice of 0.75 m cells around the camera (no buffer, no CPU simulation;
# one 128-byte push block a frame), drawn as soft round points after the upscale into the
# output-size frame before the UI. A mote's light is the frame before the UI around it (so the sun
# or moon light on the surfaces behind it, the sun fog and lamp fog and the lamps' light the game
# composed); embers glow orange by themselves. The field drifts with the shared wind when
# BB_WIND=1 (shim/bbport_wind.h, the Rasterizer's BbWind::State), else at a calm drift.
# One look indoors and outdoors: the engine has no cheap per-frame interior test for this pass
# (the sun fog's area gate, r81, is a pass of the sun fog and exists only with it; the roof rule
# r76e was an experiment and is reverted). The light taken from the frame does the rest: motes
# show where there is light (dust in a window's light, ash in lit fog) and fade in the dark.
# Off by default: BB_PARTICLES (density 0-2, unset/0 off), BB_PARTICLES_EMBERS (0-1, 0.08),
# BB_PARTICLES_SHOW=1 (test exaggeration). Stage 2 (weapon transform sparks) is a study only, in
# the context file bbfss-ctx-ambient-particles.md; nothing of it is here.
# Review 2026-11-15 (this .fixed copy): the default light gain is 1.5 (was 0.9: a mote reached at
# most about 1.5 times its background at its centre, too faint for a still); BB_PARTICLES_SHOW's
# size scale also scales the drawn-size limits (the 3 px cap of small windows ate it); the README
# and comments say 5 pixels with the centre counted twice (not "6 pixels") and the gain.
#
# DLSS: drawn AFTER the upscale (TemporalUpscaler::RunScaled, the path of every output other
# than 1920x1080: 4K, and the slot runs' small windows), not before it with motion vectors: the
# motes move against the surfaces behind them; before DLSS they would need vectors of their own
# written over the surfaces' vectors, and the half-covered surface pixels would get wrong
# history; drawn without vectors DLSS takes them from a history that follows the surfaces, which
# dims and smears small moving points. After the upscale they are sharp at the output size and
# need nothing from DLSS. A 1920x1080 output upscales before the game's post-processing and has
# no such place: nothing is drawn there (said in the README). Frame generation's in-between
# frames move them with the surfaces behind them (not checked).
#
# New files: host_shaders/ambient_particles_layout.h, ambient_particles.vert, ambient_particles.frag;
# renderer_vulkan/ambient_particles.h (pure: knobs, drift, push block), vk_ambient_particles.h/.cpp
# (the pass); tests/test_ambient_particles.cpp. Hooks in shared files (text inserted only, nothing
# replaced; the anchor in brackets):
#  - vk_temporal_upscaler.h: #include <functional> [after <memory>]; the UpscaledFrame struct and
#    the after_upscale std::function [after SetFrameGenerator's body];
#  - vk_temporal_upscaler.cpp: one call in each of RunScaled's two success ends [before
#    "done_this_frame = true;" + "if (ok4) {" and before "done_this_frame = true; // the UI is
#    not jittered"];
#  - vk_rasterizer.h: the include [before vk_bind_helper.h's] and the member [after sky_zenith];
#  - vk_rasterizer.cpp: making it and setting after_upscale [before the constructor's
#    "if (!EmulatorSettings.IsNullGPU()) {" + BindRasterizer, so after the upscaler is made];
#  - engine/gpu/CMakeLists.txt: the include rule [before "^sun_vsm"'s], 2 shader builds [before
#    camera_motion_debug_comp's], the test target [after volumetric-area-gate-test's include line];
#  - engine/build.sh: the test [after "out/frame-gen-cap-test"];
#  - README.md: a section "Ambient particles (in development)" [after the last row of the
#    "Volumetric sunlight" table, BB_VOLUMETRIC_GATE_PROBE_FILE, so before "### Wind"].
# The anchors were chosen so that no other patch drafted in this wave (r86-r102 as of 20:35)
# inserts at them: the patches that insert by replacing "anchor" with "anchor + text" stay
# contiguous whatever the order (proved on a copy with r94, r95, r97 and r99).
# No existing shader source or build changes (no edit in an existing host shader, no define of an
# existing add_host_shader line), so every existing SPIR-V build is byte-identical by construction.
#
# Off guarantee: with BB_PARTICLES unset, 0 or unreadable the Rasterizer makes no
# AmbientParticles (no pipeline, no shader module, no image, view or buffer) and after_upscale
# stays empty: RunScaled's two hooks are one test of an empty std::function a frame and record
# nothing, so the picture is bit-identical. The knobs are read once (AmbientMotes::Get, a
# function-local static) in the Rasterizer's constructor.
#
# Use: python -I -X utf8 r98_ambient-particles.py check | apply | revert. Root from R98_ROOT,
# else <tree>. Edited files keep their line ends (CRLF in the tree); new files are written
# with CRLF and removed by revert (refused when changed since). Originals of edited files are
# copied to r98_backup/ next to this script at apply. Each insertion's anchor must be found
# exactly once (else nothing is written); revert removes each inserted block (found exactly once),
# so patches that insert at the same anchors before or after this one stay intact.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r98_backup")
ROOT = os.environ.get("R98_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    H + "ambient_particles_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): the numbers the ambient motes' shaders (ambient_particles.vert,
// ambient_particles.frag) share with the engine (renderer_vulkan/ambient_particles.h, which ties
// them with static_asserts and tests/test_ambient_particles.cpp). Preprocessor only, so GLSL and
// C++ both include it.
#ifndef AMBIENT_PARTICLES_LAYOUT_H
#define AMBIENT_PARTICLES_LAYOUT_H

// The lattice: AP_NX x AP_NY x AP_NZ cells of AP_CELL m around the camera, one instance a cell (at
// most one mote), y up. A cell's hash takes its index modulo AP_PERIOD on each axis, so the field
// repeats every AP_PERIOD * AP_CELL = 768 m and the drift can wrap there without a jump.
#define AP_CELL 0.75
#define AP_NX 24
#define AP_NY 18
#define AP_NZ 24
#define AP_PERIOD 1024

// Fades (m): nearer than AP_NEAR0 view depth nothing, full from AP_NEAR1; full up to AP_FAR0 from
// the camera and nothing from AP_FAR1, vertical distances counted AP_FAR_Y times.
#define AP_NEAR0 0.45
#define AP_NEAR1 1.2
#define AP_FAR0 5.5
#define AP_FAR1 7.5
#define AP_FAR_Y 1.6
// A mote fades out over this distance (m) in front of the surface behind it (soft points).
#define AP_SOFT 0.25

// Motes (dust and ash, the one look) and embers: radius (m), life (s, from MIN to MAX by the
// cell's hash), vertical speed (m/s, + up) over the life, wobble amplitude (m).
#define AP_MOTE_RADIUS 0.010
#define AP_MOTE_LIFE_MIN 9.0
#define AP_MOTE_LIFE_MAX 15.0
#define AP_MOTE_RISE -0.05
#define AP_MOTE_WOBBLE 0.10
#define AP_EMBER_RADIUS 0.014
#define AP_EMBER_LIFE_MIN 4.0
#define AP_EMBER_LIFE_MAX 7.0
#define AP_EMBER_RISE 0.30
#define AP_EMBER_WOBBLE 0.22
// The wobble's vertical part is this share of the amplitude.
#define AP_WOBBLE_Y 0.6

// Drawn radius (output pixels): at least AP_MIN_PX (a smaller mote is drawn at this size with its
// light scaled by the area ratio), at most AP_MAX_PX_4K * output height / 2160 but not under
// AP_MAX_PX_FLOOR, both limits times the size scale (Push::look.z: 1, or BB_PARTICLES_SHOW's).
#define AP_MIN_PX 0.85
#define AP_MAX_PX_4K 8.0
#define AP_MAX_PX_FLOOR 3.0

// The light at a mote: the frame before the UI around it, 5 pixels (the centre counted twice,
// over 6); a mote's colour is at most
// AP_MAX_COLOUR a channel (display-encoded), its peak coverage AP_MOTE_PEAK / AP_EMBER_PEAK.
#define AP_MAX_COLOUR 0.6
#define AP_MOTE_PEAK 0.65
#define AP_EMBER_PEAK 0.85

// The push block (bytes) and its flag bit (Push::frame[3]): the frame before the UI is read
// through an sRGB view (its texels arrive decoded; the shader encodes them again).
#define AP_PUSH_BYTES 128
#define AP_FLAG_SCENE_SRGB 1

#endif
''',

    H + "ambient_particles.vert": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): ambient motes (dust and ash, a few embers), drawn after the
// upscale into the output-size frame before the UI (renderer_vulkan/vk_ambient_particles.cpp).
// One instance a lattice cell around the camera (ambient_particles_layout.h), six vertices a
// quad; everything comes from a hash of the cell, the time and the drift in the push block, so
// there is no buffer and no simulation. A cell without a mote, or a mote outside the view, behind
// a surface or faded out, sends all six vertices to one point outside the view (no area, nothing
// drawn). The mote's light is the frame before the UI around it (5 pixels at the render size, the
// centre counted twice): it
// carries the sun or moon light on the surfaces behind it, the sun fog and lamp fog in front of
// them and the lamps' light, so a mote shows where there is light and fades in the dark. That
// is the light behind the mote, not the light at its own place.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "ambient_particles_layout.h"

layout(binding = 0) uniform texture2D depth_tex; // scene depth, 0 near .. 1 far, render size
layout(binding = 1) uniform texture2D scene_tex; // the frame before the UI, render size

layout(push_constant) uniform Push {
    vec4 view_row[3]; // world to view, rows (view z forward)
    vec4 proj;        // x scale, y scale (ndc +y down the screen), z scale, z offset
    vec4 camera;      // xyz: the camera in the world (m); w: time (s)
    vec4 drift;       // xyz: the lattice's drift (m); w: the chance a cell holds a mote
    vec4 look;        // x: light gain, y: ember share, z: size scale, w: colour floor
    uvec4 frame;      // x: output w | h << 16, y: render w | h << 16, z: jitter (snorm16 x, y),
                      // w: flags (AP_FLAG_SCENE_SRGB)
};

layout(location = 0) out vec2 v_local;       // the corner in drawn radii
layout(location = 1) out vec2 v_render;      // the corner in the depth image (render pixels)
layout(location = 2) flat out vec3 v_colour; // premultiplied colour at the centre
layout(location = 3) flat out float v_z;     // the mote's view depth (m)

const vec2 CORNERS[6] = vec2[6](vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
                                vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0));

// PCG3D (two rounds).
uvec3 ap_hash(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    return v;
}

// Each component's top 24 bits as a float in [0, 1).
vec3 ap_unit(uvec3 h) {
    return vec3(h >> 8u) * (1.0 / 16777216.0);
}

// View depth (m) of a depth value; the sky (1) is far away.
float scene_z(float depth) {
    if (depth >= 1.0) {
        return 1e9;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

vec3 scene_at(ivec2 p, ivec2 last) {
    return texelFetch(scene_tex, clamp(p, ivec2(0), last), 0).rgb;
}

void main() {
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
    const float most = max(AP_MAX_PX_FLOOR, AP_MAX_PX_4K * out_size.y / 2160.0) * look.z;
    const float drawn = clamp(radius_px, AP_MIN_PX * look.z, most);
    const float energy = min(radius_px * radius_px / (drawn * drawn), 1.0);

    // Light: the frame before the UI around the mote.
    const int tap = int(max(3.0, 2.0 * drawn * render.y / out_size.y));
    vec3 light = 2.0 * scene_at(centre, last) + scene_at(centre + ivec2(tap, 0), last) +
                 scene_at(centre - ivec2(tap, 0), last) + scene_at(centre + ivec2(0, tap), last) +
                 scene_at(centre - ivec2(0, tap), last);
    light *= 1.0 / 6.0;
    if ((frame.w & uint(AP_FLAG_SCENE_SRGB)) != 0u) {
        light = pow(max(light, vec3(0.0)), vec3(1.0 / 2.2));
    }
    const float luma = dot(light, vec3(0.2126, 0.7152, 0.0722));
    const vec3 hue = mix(vec3(luma), light, 0.7);
    vec3 colour;
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
    v_z = z;

    const vec2 pos = ndc + corner * ((drawn + 1.0) * 2.0 / out_size);
    v_local = corner * ((drawn + 1.0) / drawn);
    v_render = (pos * 0.5 + 0.5) * render + jitter;
    gl_Position = vec4(pos, 0.0, 1.0);
}
''',

    H + "ambient_particles.frag": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): a mote's pixels (ambient_particles.vert): a soft round point,
// fading out over AP_SOFT m in front of the surface behind the pixel (the scene depth at the
// pixel's place in the render-size depth image). The colour is premultiplied; the pipeline
// screens it over the frame (colour + frame * (1 - colour)), alpha untouched.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "ambient_particles_layout.h"

layout(binding = 0) uniform texture2D depth_tex;

layout(push_constant) uniform Push {
    vec4 view_row[3];
    vec4 proj;
    vec4 camera;
    vec4 drift;
    vec4 look;
    uvec4 frame;
};

layout(location = 0) in vec2 v_local;
layout(location = 1) in vec2 v_render;
layout(location = 2) flat in vec3 v_colour;
layout(location = 3) flat in float v_z;

layout(location = 0) out vec4 out_colour;

float scene_z(float depth) {
    if (depth >= 1.0) {
        return 1e9;
    }
    return proj.w / min(depth - proj.z, -1e-8);
}

void main() {
    const float d2 = dot(v_local, v_local);
    const vec2 render = vec2(frame.y & 0xffffu, frame.y >> 16u);
    const ivec2 p = clamp(ivec2(v_render), ivec2(0), ivec2(render) - 1);
    const float behind = scene_z(texelFetch(depth_tex, p, 0).r) - v_z;
    const float a = exp(-3.0 * d2) * clamp(behind / AP_SOFT, 0.0, 1.0);
    out_colour = vec4(v_colour * a, 0.0);
}
''',

    R + "ambient_particles.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block, without Vulkan
// (tests/test_ambient_particles.cpp builds this header alone; vk_ambient_particles.cpp draws).
//
// Knobs (environment, read once by Get(), at the Rasterizer's construction):
//  - BB_PARTICLES: the density, 0 to 2 (MaxDensity); unset, unreadable, not finite or 0: off.
//    A lattice cell (AP_CELL m) holds a mote with the chance OccupancyPerDensity x density, at
//    most MaxOccupancy. 1 is the intended look.
//  - BB_PARTICLES_EMBERS: the share of the motes that are embers, 0 to 1; DefaultEmbers when
//    unset or unreadable.
//  - BB_PARTICLES_SHOW: "1" (first character) exaggerates for tests: light gain ShowGain times,
//    size ShowSize times, and a colour floor ShowFloor so motes show in the dark too.
// The drift: real time (steps clamped to 0-MaxStep s), wrapped at TimeWrap s; the lattice moves
// with WindFollow x the shared wind (bbport_wind.h) when BB_WIND=1, else at CalmDrift m/s; each
// axis is wrapped into [0, Period) m (the hash's period, so the wrap moves nothing).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "../host_shaders/ambient_particles_layout.h"

namespace Vulkan::AmbientMotes {

inline constexpr float Cell = float(AP_CELL);
inline constexpr std::uint32_t Instances = std::uint32_t(AP_NX) * AP_NY * AP_NZ;
inline constexpr double Period = double(AP_PERIOD) * AP_CELL; ///< m: the field repeats
inline constexpr double MaxStep = 0.1;                        ///< s: the longest step
inline constexpr double TimeWrap = 4096.0;                    ///< s
inline constexpr float MaxDensity = 2.0f;
inline constexpr float OccupancyPerDensity = 0.30f;
inline constexpr float MaxOccupancy = 0.90f;
inline constexpr float DefaultEmbers = 0.08f;
inline constexpr float Gain = 1.5f;      ///< the light around a mote, times this
inline constexpr float ShowGain = 2.5f;  ///< BB_PARTICLES_SHOW=1: the gain times this,
inline constexpr float ShowSize = 1.6f;  ///< the size times this,
inline constexpr float ShowFloor = 0.05f; ///< and this added to the colour (display-encoded)
inline constexpr float WindFollow = 0.8f; ///< share of the wind's velocity the lattice drifts at
inline constexpr std::array<float, 3> CalmDrift{0.06f, 0.0f, 0.04f}; ///< m/s without BB_WIND

static_assert(AP_PERIOD > 0 && (AP_PERIOD & (AP_PERIOD - 1)) == 0, "the hash masks the cell");
static_assert(float(AP_CELL) * AP_PERIOD == 768.0f, "the wrap is exact in floats");
static_assert(AP_NX % 2 == 0 && AP_NY % 2 == 0 && AP_NZ % 2 == 0);
static_assert(AP_NEAR0 < AP_NEAR1 && AP_FAR0 < AP_FAR1 && AP_FAR_Y >= 1.0);
static_assert(AP_MOTE_LIFE_MIN < AP_MOTE_LIFE_MAX && AP_EMBER_LIFE_MIN < AP_EMBER_LIFE_MAX);
// Every place a mote can be seen (inside the fade) is covered by the lattice: the box reaches at
// least (N/2 - 1) cells from the camera on each side, and a mote strays from its cell at most by
// its rise over half a life plus its wobble.
inline constexpr double EmberStrayY =
    AP_EMBER_RISE * AP_EMBER_LIFE_MAX / 2.0 + AP_EMBER_WOBBLE * AP_WOBBLE_Y;
inline constexpr double MoteStrayY =
    -AP_MOTE_RISE * AP_MOTE_LIFE_MAX / 2.0 + AP_MOTE_WOBBLE * AP_WOBBLE_Y;
static_assert((AP_NY / 2 - 1) * AP_CELL - std::max(EmberStrayY, MoteStrayY) >= AP_FAR1 / AP_FAR_Y,
              "the vertical fade ends inside the lattice");
static_assert((AP_NX / 2 - 1) * AP_CELL - AP_EMBER_WOBBLE >= AP_FAR1 &&
                  (AP_NZ / 2 - 1) * AP_CELL - AP_EMBER_WOBBLE >= AP_FAR1,
              "the horizontal fade ends inside the lattice");

struct Knobs {
    float density = 0.0f;         ///< BB_PARTICLES, 0-MaxDensity; 0 is off
    float embers = DefaultEmbers; ///< BB_PARTICLES_EMBERS, 0-1
    bool show = false;            ///< BB_PARTICLES_SHOW=1
    [[nodiscard]] bool On() const {
        return density > 0.0f;
    }
};

/// A number from the environment's text; `fallback` when null, empty, unreadable or not finite.
inline float Number(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

inline Knobs Parse(const char* density, const char* embers, const char* show) {
    Knobs k;
    k.density = std::clamp(Number(density, 0.0f), 0.0f, MaxDensity);
    k.embers = std::clamp(Number(embers, DefaultEmbers), 0.0f, 1.0f);
    k.show = show != nullptr && show[0] == '1';
    return k;
}

/// The knobs, read once.
inline const Knobs& Get() {
    static const Knobs knobs = Parse(std::getenv("BB_PARTICLES"), std::getenv("BB_PARTICLES_EMBERS"),
                                     std::getenv("BB_PARTICLES_SHOW"));
    return knobs;
}

inline double Wrap(double v, double period) {
    double r = std::fmod(v, period);
    if (r < 0.0) {
        r += period;
    }
    return r >= period ? 0.0 : r;
}

/// The time and the lattice's drift.
struct Drift {
    double time = 0.0;               ///< s, in [0, TimeWrap)
    std::array<double, 3> offset{}; ///< m, each in [0, Period)

    /// One step of `seconds` (not finite or negative: 0; at most MaxStep). With `wind_on` the
    /// lattice moves at WindFollow x `wind` (m/s), else at CalmDrift.
    void Advance(double seconds, bool wind_on, const std::array<float, 3>& wind) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        time = Wrap(time + dt, TimeWrap);
        for (std::size_t i = 0; i < 3; ++i) {
            const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
            const double v = wind_on ? double(WindFollow) * double(w) : double(CalmDrift[i]);
            offset[i] = Wrap(offset[i] + v * dt, Period);
        }
    }
};

/// ambient_particles.vert's push block; the layout is the GLSL block's (std430 push constants:
/// six 16-byte members).
struct Push {
    std::array<float, 12> view{};          ///< world to view, rows
    std::array<float, 4> proj{};           ///< x, y scale (ndc +y down), z scale, z offset
    std::array<float, 4> camera{};         ///< camera world xyz (m), time (s)
    std::array<float, 4> drift{};          ///< drift xyz (m), occupancy
    std::array<float, 4> look{};           ///< gain, ember share, size scale, colour floor
    std::array<std::uint32_t, 4> frame{};  ///< output size, render size, jitter, flags
};
static_assert(sizeof(Push) == AP_PUSH_BYTES && AP_PUSH_BYTES <= 128);
static_assert(offsetof(Push, proj) == 48 && offsetof(Push, camera) == 64 &&
              offsetof(Push, drift) == 80 && offsetof(Push, look) == 96 &&
              offsetof(Push, frame) == 112);

/// w | h << 16 (each below 65536).
inline std::uint32_t PackSize(std::uint32_t w, std::uint32_t h) {
    return (w & 0xffffu) | (h & 0xffffu) << 16;
}

/// One float as GLSL's packSnorm2x16 stores it (clamped to -1..1).
inline std::uint32_t Snorm16(float v) {
    const float c = std::isfinite(v) ? std::clamp(v, -1.0f, 1.0f) : 0.0f;
    return std::uint32_t(std::uint16_t(std::int16_t(std::lround(c * 32767.0f))));
}

/// GLSL's unpackSnorm2x16 of one half (the tests' check of Snorm16).
inline float Unsnorm16(std::uint32_t bits) {
    const auto v = std::int16_t(std::uint16_t(bits & 0xffffu));
    return std::clamp(float(v) / 32767.0f, -1.0f, 1.0f);
}

inline float Occupancy(const Knobs& k) {
    return std::min(OccupancyPerDensity * k.density, MaxOccupancy);
}

/// The push block of one draw. `view` and `inv_view`: 3x4 rows (CameraMotion::Matrices), the
/// camera's world place is inv_view's translation ([3], [7], [11]). `jitter`: the depth's
/// sub-pixel shift (render pixels, at most 1 each way). `scene_srgb`: the frame before the UI is
/// read through an sRGB view.
inline Push MakePush(const Knobs& k, const Drift& d, const std::array<float, 12>& view,
                     const std::array<float, 12>& inv_view, const std::array<float, 4>& proj,
                     std::uint32_t out_w, std::uint32_t out_h, std::uint32_t render_w,
                     std::uint32_t render_h, const std::array<float, 2>& jitter, bool scene_srgb) {
    Push p;
    p.view = view;
    p.proj = proj;
    p.camera = {inv_view[3], inv_view[7], inv_view[11], float(d.time)};
    p.drift = {float(d.offset[0]), float(d.offset[1]), float(d.offset[2]), Occupancy(k)};
    p.look = {Gain * (k.show ? ShowGain : 1.0f), k.embers, k.show ? ShowSize : 1.0f,
              k.show ? ShowFloor : 0.0f};
    p.frame = {PackSize(out_w, out_h), PackSize(render_w, render_h),
               Snorm16(jitter[0]) | Snorm16(jitter[1]) << 16,
               scene_srgb ? std::uint32_t(AP_FLAG_SCENE_SRGB) : 0u};
    return p;
}

} // namespace Vulkan::AmbientMotes
''',

    R + "vk_ambient_particles.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): ambient motes (dust and ash, a few embers) drawn into the
// output-size frame right after the upscale and before any UI pixel, on the upscaler's scaled
// path (outputs other than 1080p: TemporalUpscaler::RunScaled calls after_upscale). Made by the
// Rasterizer only with BB_PARTICLES above 0 (ambient_particles.h); otherwise nothing of it
// exists and after_upscale stays empty.
//
// Why after the upscale: the motes move against the surfaces behind them and have no motion
// vectors; drawn before DLSS (or FSR, XeSS, TAA) they would be taken from a history that follows
// the surfaces, which dims and smears small moving points. Drawn after it they are sharp at the
// output size and need no vectors. The depth test reads the render-size scene depth at the
// mote's place (the jitter added back), the light the render-size frame before the UI.
//
// One draw a frame: 6 vertices x AmbientMotes::Instances instances, no vertex buffer, no image
// or buffer of its own; the frame is screened (colour + frame (1 - colour)) through the UI
// image's UNORM view, alpha untouched. A GPU profile row "Ambient particles (r98)".

#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/ambient_particles.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"

namespace Vulkan {

class Instance;
class Scheduler;

class AmbientParticles {
public:
    /// Makes the pipeline (BB_PARTICLES above 0 only: the Rasterizer makes no object otherwise)
    /// and says the knobs once.
    AmbientParticles(const Instance& instance, Scheduler& scheduler);
    ~AmbientParticles();

    /// The pipeline was made; without it Draw records nothing.
    [[nodiscard]] bool Ready() const noexcept {
        return bool(pipeline);
    }

    /// Advances the drift by the real time since the last call and records the draw into
    /// `frame` (TemporalUpscaler::after_upscale). `wind_on`/`wind`: the shared wind's snapshot
    /// (BbWind::Snapshot on and wind, m/s).
    void Draw(const TemporalUpscaler::UpscaledFrame& frame, const CameraMotion::Matrices& camera,
              bool wind_on, const std::array<float, 3>& wind);

private:
    bool CreatePipeline();

    const Instance& instance;
    Scheduler& scheduler;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;

    AmbientMotes::Drift drift{};
    std::chrono::steady_clock::time_point last{};   ///< the last Draw (zero: none yet)
    std::chrono::steady_clock::time_point window{}; ///< start of the log line's 10 s
    u32 draws = 0;   ///< draws recorded since `window`
    u32 skipped = 0; ///< calls without a usable frame or camera since `window`
    bool first_said = false;
};

} // namespace Vulkan
''',

    R + "vk_ambient_particles.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): see vk_ambient_particles.h.

#include "video_core/renderer_vulkan/vk_ambient_particles.h"

#include <cstdio>
#include <span>
#include <string>

#include "video_core/host_shaders/ambient_particles_frag.h"
#include "video_core/host_shaders/ambient_particles_vert.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {

namespace {
constexpr u64 ProfileKey = 0x4150'0000'0098ull; ///< the GPU profile row "Ambient particles (r98)"
constexpr auto Stages = vk::ShaderStageFlagBits::eVertex | vk::ShaderStageFlagBits::eFragment;

/// The frame before the UI and the UI image (made in its format) must be RGBA8: the motes are
/// screened through the UI image's R8G8B8A8 UNORM view, which reads other byte orders wrongly.
bool Rgba8(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb;
}
} // namespace

AmbientParticles::AmbientParticles(const Instance& instance_, Scheduler& scheduler_)
    : instance{instance_}, scheduler{scheduler_} {
    const auto& knobs = AmbientMotes::Get();
    if (!CreatePipeline()) {
        pipeline.reset();
        std::printf("Ambient particles (r98): the pipeline could not be made; off\n");
        return;
    }
    std::printf("Ambient particles (r98, BB_PARTICLES=%.2f): a cell of %.2f m holds a mote with "
                "chance %.2f (%u cells around the camera), embers %.2f of them, show %s; drawn "
                "after the upscale into the output frame before the UI, on outputs other than "
                "1080p only; drifting with %s\n",
                double(knobs.density), double(AmbientMotes::Cell),
                double(AmbientMotes::Occupancy(knobs)), AmbientMotes::Instances,
                double(knobs.embers), knobs.show ? "on (BB_PARTICLES_SHOW=1)" : "off",
                "the wind when BB_WIND=1, else a calm drift");
}

AmbientParticles::~AmbientParticles() = default;

bool AmbientParticles::CreatePipeline() {
    const auto device = instance.GetDevice();
    const std::array bindings{
        vk::DescriptorSetLayoutBinding{0, vk::DescriptorType::eSampledImage, 1, Stages},
        vk::DescriptorSetLayoutBinding{1, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eVertex},
    };
    auto set = device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = u32(bindings.size()),
        .pBindings = bindings.data(),
    });
    if (set.result != vk::Result::eSuccess) {
        return false;
    }
    set_layout = std::move(set.value);
    const vk::PushConstantRange range{Stages, 0, u32(sizeof(AmbientMotes::Push))};
    const vk::DescriptorSetLayout set_handle = *set_layout;
    auto made_layout = device.createPipelineLayoutUnique({
        .setLayoutCount = 1,
        .pSetLayouts = &set_handle,
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &range,
    });
    if (made_layout.result != vk::Result::eSuccess) {
        return false;
    }
    layout = std::move(made_layout.value);
    const std::span<const u32> vert = AMBIENT_PARTICLES_VERT;
    const std::span<const u32> frag = AMBIENT_PARTICLES_FRAG;
    auto vert_module =
        device.createShaderModuleUnique({.codeSize = vert.size_bytes(), .pCode = vert.data()});
    auto frag_module =
        device.createShaderModuleUnique({.codeSize = frag.size_bytes(), .pCode = frag.data()});
    if (vert_module.result != vk::Result::eSuccess || frag_module.result != vk::Result::eSuccess) {
        return false;
    }
    const std::array stages{
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eVertex,
                                          .module = *vert_module.value, .pName = "main"},
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eFragment,
                                          .module = *frag_module.value, .pName = "main"},
    };
    const vk::PipelineVertexInputStateCreateInfo vertex_input{};
    const vk::PipelineInputAssemblyStateCreateInfo assembly{
        .topology = vk::PrimitiveTopology::eTriangleList};
    const vk::PipelineViewportStateCreateInfo viewport_state{.viewportCount = 1, .scissorCount = 1};
    const vk::PipelineRasterizationStateCreateInfo raster{
        .polygonMode = vk::PolygonMode::eFill,
        .cullMode = vk::CullModeFlagBits::eNone,
        .lineWidth = 1.0f,
    };
    const vk::PipelineMultisampleStateCreateInfo multisample{
        .rasterizationSamples = vk::SampleCountFlagBits::e1};
    const vk::PipelineDepthStencilStateCreateInfo depth_state{};
    // Screen: colour + frame (1 - colour); the frame's alpha is kept.
    const vk::PipelineColorBlendAttachmentState screen{
        .blendEnable = true,
        .srcColorBlendFactor = vk::BlendFactor::eOneMinusDstColor,
        .dstColorBlendFactor = vk::BlendFactor::eOne,
        .colorBlendOp = vk::BlendOp::eAdd,
        .srcAlphaBlendFactor = vk::BlendFactor::eZero,
        .dstAlphaBlendFactor = vk::BlendFactor::eOne,
        .alphaBlendOp = vk::BlendOp::eAdd,
        .colorWriteMask = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                          vk::ColorComponentFlagBits::eB,
    };
    const vk::PipelineColorBlendStateCreateInfo blend{.attachmentCount = 1, .pAttachments = &screen};
    const std::array dynamic_states{vk::DynamicState::eViewport, vk::DynamicState::eScissor};
    const vk::PipelineDynamicStateCreateInfo dynamic{
        .dynamicStateCount = u32(dynamic_states.size()), .pDynamicStates = dynamic_states.data()};
    const vk::Format target_format = vk::Format::eR8G8B8A8Unorm; // the UI image's UNORM view
    const vk::PipelineRenderingCreateInfo rendering{.colorAttachmentCount = 1,
                                                    .pColorAttachmentFormats = &target_format};
    auto made = device.createGraphicsPipelineUnique(
        {}, vk::GraphicsPipelineCreateInfo{
                .pNext = &rendering,
                .stageCount = u32(stages.size()),
                .pStages = stages.data(),
                .pVertexInputState = &vertex_input,
                .pInputAssemblyState = &assembly,
                .pViewportState = &viewport_state,
                .pRasterizationState = &raster,
                .pMultisampleState = &multisample,
                .pDepthStencilState = &depth_state,
                .pColorBlendState = &blend,
                .pDynamicState = &dynamic,
                .layout = *layout,
            });
    if (made.result != vk::Result::eSuccess) {
        return false;
    }
    pipeline = std::move(made.value);
    SetObjectName(device, *pipeline, "Ambient particles (r98)");
    return true;
}

void AmbientParticles::Draw(const TemporalUpscaler::UpscaledFrame& frame,
                            const CameraMotion::Matrices& camera, bool wind_on,
                            const std::array<float, 3>& wind) {
    const auto now = std::chrono::steady_clock::now();
    const double seconds =
        last == std::chrono::steady_clock::time_point{}
            ? 0.0
            : std::chrono::duration<double>(now - last).count();
    last = now;
    if (window == std::chrono::steady_clock::time_point{}) {
        window = now;
    }
    drift.Advance(seconds, wind_on, wind);
    const bool srgb = frame.scene_format == vk::Format::eR8G8B8A8Srgb;
    const bool usable = pipeline && frame.view && frame.depth && frame.scene && camera.valid &&
                        Rgba8(frame.scene_format) &&
                        frame.width > 0 && frame.height > 0 && frame.width <= 0xffffu &&
                        frame.height <= 0xffffu && frame.render_width > 0 &&
                        frame.render_height > 0 && frame.render_width <= 0xffffu &&
                        frame.render_height <= 0xffffu;
    if (!usable) {
        ++skipped;
    } else {
        const auto& knobs = AmbientMotes::Get();
        const AmbientMotes::Push push = AmbientMotes::MakePush(
            knobs, drift, camera.view, camera.inv_view, camera.proj, frame.width, frame.height,
            frame.render_width, frame.render_height, frame.jitter, srgb);
        if (!first_said) {
            first_said = true;
            std::printf("Ambient particles (r98): first draw into %ux%u after the upscale (scene "
                        "%ux%u, frame before the UI read %s)\n",
                        frame.width, frame.height, frame.render_width, frame.render_height,
                        srgb ? "through an sRGB view" : "as stored");
        }
        scheduler.EndRendering();
        auto* profiler = GpuProfiler::Get();
        const u64 resume = profiler ? profiler->Current() : 0;
        if (profiler) {
            profiler->Mark(ProfileKey, [] { return std::string{"Ambient particles (r98)"}; });
        }
        const vk::Extent2D extent{frame.width, frame.height};
        scheduler.RecordCrumb(
            {.name = "Ambient particles"},
            [push, extent, target = frame.view, depth = frame.depth, scene = frame.scene,
             bound = *pipeline, bound_layout = *layout](vk::CommandBuffer cmd) {
                // The depth and the frame before the UI were written by earlier passes; the
                // output image's last barrier (RunScaled) already ends at colour attachment use.
                const vk::MemoryBarrier2 before{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eVertexShader |
                                    vk::PipelineStageFlagBits2::eFragmentShader |
                                    vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                                     vk::AccessFlagBits2::eColorAttachmentRead |
                                     vk::AccessFlagBits2::eColorAttachmentWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
                const vk::RenderingAttachmentInfo attachment{
                    .imageView = target,
                    .imageLayout = vk::ImageLayout::eGeneral,
                    .loadOp = vk::AttachmentLoadOp::eLoad,
                    .storeOp = vk::AttachmentStoreOp::eStore,
                };
                cmd.beginRendering({
                    .renderArea = {{0, 0}, extent},
                    .layerCount = 1,
                    .colorAttachmentCount = 1,
                    .pColorAttachments = &attachment,
                });
                const std::array infos{
                    vk::DescriptorImageInfo{{}, depth, vk::ImageLayout::eGeneral},
                    vk::DescriptorImageInfo{{}, scene, vk::ImageLayout::eGeneral},
                };
                const std::array<vk::WriteDescriptorSet, 2> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[0]},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[1]},
                }};
                cmd.bindPipeline(vk::PipelineBindPoint::eGraphics, bound);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eGraphics, bound_layout, 0, writes);
                cmd.pushConstants(bound_layout, Stages, 0, u32(sizeof(push)), &push);
                cmd.setViewport(0, vk::Viewport{0.0f, 0.0f, float(extent.width),
                                                float(extent.height), 0.0f, 1.0f});
                cmd.setScissor(0, vk::Rect2D{{0, 0}, extent});
                cmd.draw(6, AmbientMotes::Instances, 0, 0);
                cmd.endRendering();
                // The UI draws into the same image next; the frame generation and native HDR
                // copies read it later.
                const vk::MemoryBarrier2 after{
                    .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                    .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask =
                        vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
            });
        // The guest pipelines' dynamic state must be emitted again after this pipeline.
        scheduler.GetDynamicState().Invalidate();
        if (resume) {
            profiler->Resume(resume);
        }
        ++draws;
    }
    // A line every 10 s while frames reach this point, so a test sees that it acted.
    const double elapsed = std::chrono::duration<double>(now - window).count();
    if (elapsed >= 10.0) {
        std::printf("Ambient particles: %u draws and %u frames skipped in the last %.1f s, drift "
                    "%.2f %.2f %.2f m (%s), time %.1f s\n",
                    draws, skipped, elapsed, drift.offset[0], drift.offset[1], drift.offset[2],
                    wind_on ? "with the wind" : "calm", drift.time);
        window = now;
        draws = 0;
        skipped = 0;
    }
}

} // namespace Vulkan
''',

    "engine/tests/test_ambient_particles.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block
// (gpu/shadps4/video_core/renderer_vulkan/ambient_particles.h). Built and run by engine/build.sh
// --test and the CMake target ambient-particles-test.
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <limits>

#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles.h"

using namespace Vulkan::AmbientMotes;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(double a, double b, double tolerance) {
    return std::fabs(a - b) <= tolerance;
}
} // namespace

int main() {
    // a. BB_PARTICLES: unset, empty, 0, negative, unreadable and not finite are off; clamped to 2.
    for (const char* off : {static_cast<const char*>(nullptr), "", "0", "-1", "abc", "nan", "inf"}) {
        Expect(!Parse(off, nullptr, nullptr).On(), "an unset, 0 or unreadable BB_PARTICLES is off");
    }
    Expect(Parse("1", nullptr, nullptr).density == 1.0f, "BB_PARTICLES=1 is density 1");
    Expect(Parse("0.5", nullptr, nullptr).density == 0.5f, "BB_PARTICLES=0.5 is density 0.5");
    Expect(Parse("7", nullptr, nullptr).density == MaxDensity, "BB_PARTICLES above 2 is 2");
    // b. BB_PARTICLES_EMBERS and BB_PARTICLES_SHOW.
    Expect(Parse("1", nullptr, nullptr).embers == DefaultEmbers, "unset embers take the default");
    Expect(Parse("1", "x", nullptr).embers == DefaultEmbers, "unreadable embers take the default");
    Expect(Parse("1", "0.5", nullptr).embers == 0.5f, "BB_PARTICLES_EMBERS=0.5");
    Expect(Parse("1", "3", nullptr).embers == 1.0f && Parse("1", "-2", nullptr).embers == 0.0f,
           "embers clamp to 0-1");
    Expect(Parse("1", nullptr, "1").show && !Parse("1", nullptr, "0").show &&
               !Parse("1", nullptr, nullptr).show,
           "BB_PARTICLES_SHOW is on with a leading 1 only");

    // c. Occupancy: 0.3 a density, at most 0.9.
    Expect(Near(Occupancy(Parse("1", nullptr, nullptr)), 0.3, 1e-6), "density 1 fills 30% of cells");
    Expect(Near(Occupancy(Parse("2", nullptr, nullptr)), 0.6, 1e-6), "density 2 fills 60% of cells");

    // d. Drift: steps clamped, bad steps move nothing, wraps.
    {
        Drift a, b;
        a.Advance(0.5, false, {});
        b.Advance(MaxStep, false, {});
        Expect(a.time == b.time && a.offset == b.offset && a.time == MaxStep,
               "a 0.5 s step counts as 0.1 s");
        for (const double bad : {std::numeric_limits<double>::quiet_NaN(), -1.0,
                                 std::numeric_limits<double>::infinity()}) {
            Drift c = b;
            c.Advance(bad, true, {1.0f, 0.0f, 1.0f});
            Expect(c.time == b.time && c.offset == b.offset, "a bad step moves nothing");
        }
        Drift calm;
        for (int i = 0; i < 100; ++i) {
            calm.Advance(0.05, false, {9.0f, 9.0f, 9.0f});
        }
        Expect(Near(calm.offset[0], 5.0 * CalmDrift[0], 1e-9) && Near(calm.offset[1], 0.0, 1e-12) &&
                   Near(calm.offset[2], 5.0 * CalmDrift[2], 1e-9),
               "without the wind the lattice drifts at CalmDrift");
        Drift windy;
        for (int i = 0; i < 100; ++i) {
            windy.Advance(0.05, true, {2.0f, 0.0f, -1.0f});
        }
        Expect(Near(windy.offset[0], 5.0 * 2.0 * WindFollow, 1e-6) &&
                   Near(windy.offset[2], Period - 5.0 * WindFollow, 1e-6),
               "with the wind the lattice drifts at WindFollow x the wind, wrapped into [0, Period)");
        Drift bad_wind;
        bad_wind.Advance(0.05, true, {std::numeric_limits<float>::quiet_NaN(), 0.0f, 0.0f});
        Expect(bad_wind.offset[0] == 0.0, "a wind that is not finite counts as 0");
        Drift late;
        late.time = TimeWrap - 0.01;
        late.Advance(0.05, false, {});
        Expect(Near(late.time, 0.04, 1e-9), "the time wraps at TimeWrap");
        Expect(Period == 768.0 && Wrap(-1.0, Period) == Period - 1.0 && Wrap(Period, Period) == 0.0,
               "the period is 768 m and Wrap stays in [0, Period)");
    }

    // e. The push block.
    {
        std::array<float, 12> view{}, inv{};
        for (int i = 0; i < 12; ++i) {
            view[i] = float(i);
            inv[i] = float(100 + i);
        }
        Drift d;
        d.time = 12.5;
        d.offset = {1.0, 2.0, 3.0};
        const Push p = MakePush(Parse("1", "0.25", "1"), d, view, inv, {1.5f, -2.0f, 1.0f, -0.1f},
                                3840, 2160, 1920, 1080, {0.25f, -0.5f}, true);
        Expect(p.view == view && p.proj[1] == -2.0f, "view rows and projection as given");
        Expect(p.camera[0] == 103.0f && p.camera[1] == 107.0f && p.camera[2] == 111.0f &&
                   p.camera[3] == 12.5f,
               "the camera is inv_view's translation, then the time");
        Expect(p.drift[0] == 1.0f && p.drift[2] == 3.0f && Near(p.drift[3], 0.3, 1e-6),
               "drift and occupancy");
        Expect(Near(p.look[0], Gain * ShowGain, 1e-6) && p.look[1] == 0.25f &&
                   p.look[2] == ShowSize && p.look[3] == ShowFloor,
               "BB_PARTICLES_SHOW=1 exaggerates gain and size and adds the floor");
        Expect(p.frame[0] == (3840u | 2160u << 16) && p.frame[1] == (1920u | 1080u << 16),
               "sizes packed as w | h << 16");
        Expect(Near(Unsnorm16(p.frame[2]), 0.25, 1e-4) && Near(Unsnorm16(p.frame[2] >> 16), -0.5, 1e-4),
               "the jitter round-trips through snorm16");
        Expect(p.frame[3] == std::uint32_t(AP_FLAG_SCENE_SRGB), "the sRGB flag");
        const Push plain = MakePush(Parse("1", nullptr, nullptr), d, view, inv, {}, 1280, 720, 640,
                                    360, {0.0f, 0.0f}, false);
        Expect(plain.look[0] == Gain && plain.look[2] == 1.0f && plain.look[3] == 0.0f &&
                   plain.frame[2] == 0u && plain.frame[3] == 0u,
               "without show: the plain look, no flags");
        Expect(Unsnorm16(Snorm16(5.0f)) == 1.0f && Unsnorm16(Snorm16(-5.0f)) == -1.0f,
               "the jitter clamps to -1..1");
    }

    std::printf("ambient-particles-test: %u cells, %s\n", Instances,
                failures == 0 ? "all checks pass" : "FAILED");
    return failures == 0 ? 0 : 1;
}
''',

}

# (where, anchor, inserted text): the text goes right "after" or "before" the anchor.
EDITS = {
    R + "vk_temporal_upscaler.h": [
        ("after", "#include <memory>\n",
         "#include <functional> // bbport (r98_ambient-particles): TemporalUpscaler::after_upscale\n"),
        ("after",
         "    void SetFrameGenerator(FrameGenerator* generator) noexcept {\n"
         "        frame_gen = generator;\n"
         "    }\n",
         "\n"
         "    /// bbport (r98_ambient-particles): the upscaled frame before its UI, for a pass drawn\n"
         "    /// after the upscale (vk_ambient_particles.h). `view`: the output-size UI image's\n"
         "    /// R8G8B8A8 UNORM view (General layout, its last barrier ends at colour attachment use);\n"
         "    /// `depth` and `scene`: the scene depth (depth aspect) and the frame before the UI the\n"
         "    /// upscaler read (General), the scene in their top-left render_width x render_height;\n"
         "    /// `scene_format`: that frame's format (the UI image's too); `jitter`: the depth's\n"
         "    /// sub-pixel shift in render pixels (Jitter()'s convention).\n"
         "    struct UpscaledFrame {\n"
         "        vk::ImageView view, depth, scene;\n"
         "        vk::Format scene_format{};\n"
         "        u32 width = 0, height = 0, render_width = 0, render_height = 0;\n"
         "        std::array<float, 2> jitter{};\n"
         "    };\n"
         "    /// Called by RunScaled (outputs other than 1920x1080) after a successful upscale, before\n"
         "    /// any UI pixel; empty unless a pass set it (the Rasterizer, BB_PARTICLES above 0 only).\n"
         "    std::function<void(const UpscaledFrame&)> after_upscale;\n"),
    ],
    R + "vk_temporal_upscaler.cpp": [
        ("before", "        done_this_frame = true;\n        if (ok4) {\n",
         "        if (ok4 && after_upscale) { // bbport (r98_ambient-particles): before the UI\n"
         "            after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,\n"
         "                           color.info.pixel_format, ow, oh, w, h, jitter});\n"
         "        }\n"),
        ("before", "    done_this_frame = true; // the UI is not jittered\n",
         "    if (ok && after_upscale) { // bbport (r98_ambient-particles): before the UI\n"
         "        after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,\n"
         "                       color.info.pixel_format, ow, oh, w, h, jitter});\n"
         "    }\n"),
    ],
    R + "vk_rasterizer.h": [
        ("before", '#include "video_core/renderer_vulkan/vk_bind_helper.h"\n',
         '#include "video_core/renderer_vulkan/vk_ambient_particles.h" // bbport (r98_ambient-particles)\n'),
        ("after", "    std::unique_ptr<SkyZenith> sky_zenith;\n",
         "    /// bbport (r98_ambient-particles): made only with BB_PARTICLES above 0 and the upscaler\n"
         "    /// on, else null; it draws through TemporalUpscaler::after_upscale.\n"
         "    std::unique_ptr<AmbientParticles> ambient_particles;\n"),
    ],
    R + "vk_rasterizer.cpp": [
        ("before", "    if (!EmulatorSettings.IsNullGPU()) {\n        liverpool->BindRasterizer(this);\n",
         "    // bbport (r98_ambient-particles): BB_PARTICLES above 0 only (AmbientMotes::Get, read once\n"
         "    // here); otherwise nothing of it is made and the upscaler's after_upscale stays empty.\n"
         "    if (AmbientMotes::Get().On()) {\n"
         "        if (!upscaler->Enabled()) {\n"
         "            std::printf(\"Ambient particles (r98): the upscaler is off; nothing is drawn\\n\");\n"
         "        } else if (auto motes = std::make_unique<AmbientParticles>(instance, scheduler);\n"
         "                   motes->Ready()) {\n"
         "            ambient_particles = std::move(motes);\n"
         "            upscaler->after_upscale = [this](const TemporalUpscaler::UpscaledFrame& frame) {\n"
         "                const BbWind::Snapshot w = wind.Get();\n"
         "                ambient_particles->Draw(frame, camera_motion->CameraMatrices(), w.on, w.wind);\n"
         "            };\n"
         "        }\n"
         "    }\n"),
    ],
    "engine/gpu/CMakeLists.txt": [
        ("before", '    if (FILENAME MATCHES "^sun_vsm")\n',
         "    # bbport (r98_ambient-particles): the motes' numbers, shared with C++ (ambient_particles.h)\n"
         '    if (FILENAME MATCHES "^ambient_particles")\n'
         "        list(APPEND INCLUDES ${SHADER_SRC}/ambient_particles_layout.h)\n"
         "    endif()\n"),
        ("before", "add_host_shader(camera_motion.comp camera_motion_debug_comp DEBUG_OVERLAY=1)\n",
         "# bbport (r98_ambient-particles): BB_PARTICLES above 0 only: the ambient motes, drawn after\n"
         "# the upscale (vk_ambient_particles.cpp)\n"
         "add_host_shader(ambient_particles.vert ambient_particles_vert)\n"
         "add_host_shader(ambient_particles.frag ambient_particles_frag)\n"),
        ("after", "target_include_directories(volumetric-area-gate-test PRIVATE ..)\n",
         "# bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block\n"
         "# (ambient_particles.h); also built and run by engine/build.sh --test.\n"
         "add_executable(ambient-particles-test EXCLUDE_FROM_ALL ../tests/test_ambient_particles.cpp)\n"
         "target_compile_options(ambient-particles-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(ambient-particles-test PRIVATE ..)\n"),
    ],
    "engine/build.sh": [
        ("after", "    out/frame-gen-cap-test\n",
         "    # bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_ambient_particles.cpp -o out/ambient-particles-test\n'
         "    out/ambient-particles-test\n"),
    ],
    "README.md": [
        ("after", "| `BB_VOLUMETRIC_GATE_PROBE_FILE` | Debug only, with `BB_VOLUMETRIC_GATE_PROBE=1`: a file "
         "the \"gate instances\" lines also go to (written anew at the run's first probe, then "
         "appended) | not set |\n",
         "\n"
         "### Ambient particles (in development)\n"
         "\n"
         "Dust and ash motes and a few embers in the air around the camera, drawn by the engine (not the game's own particles). Off unless `BB_PARTICLES` is above 0. These environment variables are read once when the game starts; they are for testing and are part of no look; no ini key yet. The motes are drawn after the upscaler (DLSS, FSR, XeSS or TAA) into the output-size frame, before the game's UI, so they need no motion vectors and stay sharp; that place exists only when the output is not 1920x1080: with a 1920x1080 output, or with `BB_UPSCALER=none`, nothing is drawn. One look indoors and outdoors (the engine has no cheap test for an interior here); a mote takes its light from the picture behind it, so it shows where there is light and fades in the dark.\n"
         "\n"
         "| Variable | What it does | Default |\n"
         "|---|---|---|\n"
         "| `BB_PARTICLES` | Density, 0 to 2 (above 2 counts as 2); unset, 0 or unreadable is off. The air around the camera is cut into cells of 0.75 m, 24 x 18 x 24 of them centred on the camera; a cell holds one mote with the chance 0.3 x density (at most 0.9), its place, life (9 to 15 s for a mote, 4 to 7 s for an ember, fading in and out) and wobble taken from a hash of the cell and the time, so nothing is simulated or uploaded. A mote is seen from 0.45 m in front of the camera (in full from 1.2 m) up to 7.5 m away (in full up to 5.5 m, heights counted 1.6 times); one behind a surface is not drawn, and it fades out over its last 0.25 m in front of the surface behind it. Its colour is the frame before the UI around it (5 pixels of the render-size frame, the centre counted twice) times 1.5: the sun or moon light on the surfaces behind it, the sun fog and lamp fog and the lamps' light; it is screened over the frame (at most 0.6 a channel, display-encoded). Embers glow orange by themselves, more where the light around them is warm. Motes sink at 0.05 m/s and embers rise at 0.3 m/s; the whole field drifts at 0.06 m/s along x and 0.04 m/s along z, or with `BB_WIND=1` at 0.8 times the wind's velocity (gusts included). The log says the knobs once when on, the first draw once, and every 10 s `Ambient particles: <n> draws and <m> frames skipped in the last <s> s` with the drift. Cost: an estimate of 0.05 ms or less at a 4K output from 1080p internal (one draw of 10368 instances of 6 vertices, a few hundred motes on screen at most), not measured; read it on the `Ambient particles (r98)` row of `BB_GPU_PROFILE=1` | off |\n"
         "| `BB_PARTICLES_EMBERS` | Share of the motes that are embers, 0 to 1 | `0.08` |\n"
         "| `BB_PARTICLES_SHOW` | Test only: `1` multiplies the motes' light by 2.5 (still at most 0.6 a channel) and their size and its drawn limits by 1.6, and adds 0.05 to their colour, so they show in the dark too | off |\n"),
    ],
}

# README numbers tied to the header that sets them: (text in a NEW file, text in the README row
# that starts with the given cell).
TIES = [
    (R + "ambient_particles.h", "inline constexpr float MaxDensity = 2.0f;", "| `BB_PARTICLES` |", "Density, 0 to 2"),
    (R + "ambient_particles.h", "inline constexpr float OccupancyPerDensity = 0.30f;", "| `BB_PARTICLES` |", "chance 0.3 x density"),
    (R + "ambient_particles.h", "inline constexpr float MaxOccupancy = 0.90f;", "| `BB_PARTICLES` |", "(at most 0.9)"),
    (R + "ambient_particles.h", "inline constexpr float WindFollow = 0.8f;", "| `BB_PARTICLES` |", "0.8 times the wind"),
    (R + "ambient_particles.h", "CalmDrift{0.06f, 0.0f, 0.04f}", "| `BB_PARTICLES` |", "0.06 m/s along x and 0.04 m/s along z"),
    (R + "ambient_particles.h", "inline constexpr float DefaultEmbers = 0.08f;", "| `BB_PARTICLES_EMBERS` |", "`0.08`"),
    (R + "ambient_particles.h", "inline constexpr float ShowGain = 2.5f;", "| `BB_PARTICLES_SHOW` |", "light by 2.5"),
    (R + "ambient_particles.h", "inline constexpr float ShowSize = 1.6f;", "| `BB_PARTICLES_SHOW` |", "drawn limits by 1.6"),
    (R + "ambient_particles.h", "inline constexpr float Gain = 1.5f;", "| `BB_PARTICLES` |", "counted twice) times 1.5"),
    (H + "ambient_particles.vert", "* out_size.y / 2160.0) * look.z;", "| `BB_PARTICLES_SHOW` |", "drawn limits by 1.6"),
    (R + "ambient_particles.h", "inline constexpr float ShowFloor = 0.05f;", "| `BB_PARTICLES_SHOW` |", "adds 0.05"),
    (H + "ambient_particles_layout.h", "#define AP_CELL 0.75\n", "| `BB_PARTICLES` |", "cells of 0.75 m"),
    (H + "ambient_particles_layout.h", "#define AP_NX 24\n#define AP_NY 18\n#define AP_NZ 24\n", "| `BB_PARTICLES` |", "24 x 18 x 24"),
    (H + "ambient_particles_layout.h", "#define AP_NEAR0 0.45\n#define AP_NEAR1 1.2\n", "| `BB_PARTICLES` |", "0.45 m in front of the camera (in full from 1.2 m)"),
    (H + "ambient_particles_layout.h", "#define AP_FAR0 5.5\n#define AP_FAR1 7.5\n#define AP_FAR_Y 1.6\n", "| `BB_PARTICLES` |", "up to 7.5 m away (in full up to 5.5 m, heights counted 1.6 times)"),
    (H + "ambient_particles_layout.h", "#define AP_SOFT 0.25\n", "| `BB_PARTICLES` |", "last 0.25 m"),
    (H + "ambient_particles_layout.h", "#define AP_MOTE_LIFE_MIN 9.0\n#define AP_MOTE_LIFE_MAX 15.0\n#define AP_MOTE_RISE -0.05\n", "| `BB_PARTICLES` |", "9 to 15 s for a mote"),
    (H + "ambient_particles_layout.h", "#define AP_EMBER_LIFE_MIN 4.0\n#define AP_EMBER_LIFE_MAX 7.0\n#define AP_EMBER_RISE 0.30\n", "| `BB_PARTICLES` |", "4 to 7 s for an ember"),
    (H + "ambient_particles_layout.h", "#define AP_MAX_COLOUR 0.6\n", "| `BB_PARTICLES` |", "at most 0.6 a channel"),
    (H + "ambient_particles_layout.h", "#define AP_MOTE_RISE -0.05\n", "| `BB_PARTICLES` |", "Motes sink at 0.05 m/s"),
    (H + "ambient_particles_layout.h", "#define AP_EMBER_RISE 0.30\n", "| `BB_PARTICLES` |", "embers rise at 0.3 m/s"),
    (R + "vk_ambient_particles.cpp", "elapsed >= 10.0", "| `BB_PARTICLES` |", "every 10 s"),
    (R + "vk_ambient_particles.cpp", 'std::string{"Ambient particles (r98)"}', "| `BB_PARTICLES` |", "`Ambient particles (r98)` row"),
]

# After apply, each file holds these texts this many times (the hooks and what they call).
CHECKS = {
    R + "vk_temporal_upscaler.cpp": [("after_upscale(", 2), ("r98_ambient-particles", 2)],
    R + "vk_temporal_upscaler.h": [("std::function<void(const UpscaledFrame&)> after_upscale;", 1)],
    R + "vk_rasterizer.cpp": [("upscaler->after_upscale = ", 1), ("ambient_particles->Draw(", 1)],
    "engine/gpu/CMakeLists.txt": [("add_host_shader(ambient_particles.", 2), ("ambient-particles-test", 3)],
}
# Texts that must come in this order (the hooks sit before the UI phase starts).
ORDER = {
    R + "vk_temporal_upscaler.cpp": ["void TemporalUpscaler::RunScaled()", "if (ok4 && after_upscale)",
                                    "        done_this_frame = true;\n        if (ok4) {",
                                    "if (ok && after_upscale)",
                                    "    done_this_frame = true; // the UI is not jittered",
                                    "vk::ImageView TemporalUpscaler::Mirror("],
    R + "vk_rasterizer.cpp": ["upscaler = std::make_unique<TemporalUpscaler>(",
                              "rt_shadow->SetCardLayers(", "if (AmbientMotes::Get().On()) {"],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def insert(text, where, anchor, block, path):
    n = text.count(anchor)
    if n != 1:
        raise SystemExit("%s: anchor found %d times, wanted once: %r" % (path, n, anchor[:70]))
    i = text.index(anchor)
    at = i + len(anchor) if where == "after" else i
    return text[:at] + block + text[at:]


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
    rows = texts["README.md"].split("\n")
    for path, const, row, value in TIES:
        line = [l for l in rows if l.startswith(row)]
        if NEW[path].count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    for path, edits in EDITS.items():
        for where, anchor, block in edits:
            if not all(ord(c) < 128 for c in block):
                raise SystemExit("%s: inserted text must be ASCII" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R98_ROOT)" % ROOT)
    plan, states = [], set()
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(block) == 1 for _, _, block in edits)
        todo = sum(cur.count(block) == 0 and cur.count(anchor) == 1 for _, anchor, block in edits)
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d insertions present, %d anchors found once"
                             % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur))
        states.add(state)
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            states.add("clean")
        elif open(full, "rb").read() == new_bytes(text):
            states.add("applied")
        else:
            raise SystemExit("%s exists and is not this patch's file" % path)
    if len(states) != 1:
        raise SystemExit("mixed state: some parts applied, some not")
    state = states.pop()
    if cmd == "check" or cmd == "apply":
        texts = {}
        for path, edits, raw, eol, cur in plan:
            if state == "clean":
                for where, anchor, block in edits:
                    cur = insert(cur, where, anchor, block, path)
            texts[path] = cur
        text_checks(texts)
        if cmd == "check":
            if state == "applied":
                print("applied (text checks pass)")
            else:
                print("not applied; would apply (%d files edited, %d new; text checks on the result "
                      "pass)" % (len(plan), len(NEW)))
            return
        if state == "applied":
            print("already applied")
            return
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8"), raw)
                for path, edits, raw, eol, cur in plan]
        outs += [(path, new_bytes(text), None) for path, text in NEW.items()]
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r98tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r98tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d new)" % (len(plan), len(NEW)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    for path, edits, raw, eol, cur in plan:
        for where, anchor, block in reversed(edits):
            if cur.count(block) != 1:
                raise SystemExit("%s: inserted block not found once" % path)
            cur = cur.replace(block, "", 1)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
