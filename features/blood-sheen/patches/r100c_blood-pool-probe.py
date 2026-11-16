# r100c_blood-pool-probe: TOOL patch (test aid; goes to dev/test-tools, never to a feature branch or a
# pull request). Blood sheen follow-up: r100 marked the draw 1ea84d9a:bd1d09f0 as the blood pool, and
# the r100b run (2026-11-15 22:22) showed it to be a small object at the hunter's hip (depth-off
# footprint 1112 px, box x 895-930 y 661-706), not the pool (roughly x 1000-1400 y 430-800 on the
# 1920x1080 graveyard-blood picture). This probe finds the draw that puts the VISIBLE pool on screen.
#
# What it does: BB_BLOOD_POOL_PROBE=x0:y0:x1:y1 (a box in scene pixels, corners inside; a side over 256
# is cut to 256) arms the probe; "on"/"1" makes it and waits for a box from the live knobs file
# (BB_LIVE_KNOBS_FILE, the slot runner's set:BB_BLOOD_POOL_PROBE=... action). After 600 frames in a row
# with a G-buffer pass (30 for a live box), it probes 2 frames: right before every draw into targets
# of the scene's size (outside a lamps-apart batch and menu previews) a compute pass keeps a 32-bit
# print of each colour target and the depth at every box pixel and at every 4th pixel of the frame
# each way; right after the draw a second pass counts where they changed and notes the draw as the
# last writer of each box pixel's G-buffer albedo (a), scene colour by draws of more than 6 indices (s)
# and depth (z). When the GPU is past the frames it logs, every line "Blood pool probe (r100c): ...":
# a header (box, scene size, G-buffer draw range, first light draw), counts (draws, probed, skips),
# the owner totals, a legend, then up to 16 lines, one per vertex:pixel shader pair that changed the
# box or owns box pixels, sorted by box pixels owned (a+s+z), then by box pixels changed a frame (so
# that a box's lines fit the slot runner's 30 evidence lines of a job): hashes, box px, own aN sN zN, frame~px,
# draws a frame, probed, index counts, draw numbers in the last frame, phases (P before the G-buffer,
# G G-buffer, B after it before light, L light, A after light), each target as cb:format/role (+b
# blending, m<mask> a partial write mask, =box px changed) and the depth (func, w write, =px).
# Log only: no target is written.
#
# What decides (see the context file section "r100c"): in the pool box against the control box,
# the pair with the most "own a" (the last G-buffer albedo writer) and "own s" (the last scene colour
# writer) and its phase letters.
#
# Off (unset, empty, 0 or off at start): the rasterizer makes no BloodPoolProbe; its five hooks are
# null pointer tests. Made but idle: two compares a draw and one generation look a frame. While
# probing: two dispatches and two render pass splits a scene-sized draw (about 1000-1900 draws a
# frame) for 2 frames: a hitch of about 0.05-0.5 s (estimate, not measured), then nothing.
# Memory once made and a box probed: counters 360 KB and owner maps 768 KB host-visible, prints
# (box px + frame px / 16) * 9 * 4 bytes on the device (2.3 MB + 4.7 MB at 1080p, 18.7 MB frame part
# at 2160p), kept until the game ends.
#
# Files: new renderer_vulkan/blood_pool_probe.h (knob parse and numbers, static_assert tests),
# renderer_vulkan/vk_blood_pool_probe.h/.cpp (the probe; the .cpp also holds
# Rasterizer::BloodPoolProbeBefore; picked up by gpu/CMakeLists.txt's GLOB_RECURSE CONFIGURE_DEPENDS of
# shadps4/video_core/*.cpp), host_shaders/blood_pool_probe.comp and blood_pool_probe_layout.h (shared
# numbers). Edits: vk_rasterizer.h (include; the member and BloodPoolProbeBefore before
# depth_of_field), vk_rasterizer.cpp (made in the constructor before sky_seam; indirect draws' before
# and after hooks), vk_rasterizer_effects.cpp (first in EffectsBeforeResources, first in
# EffectsAfterDraw, first in EffectsOnFrameEnd), gpu/CMakeLists.txt (the layout include rule and two
# add_host_shader lines before volumetric_light's). Not in build.sh's gpu-cache identity list (no
# vk_*pipeline* name): the players' shader and pipeline caches stay. No README row (a TOOL).
#
# Use: python -I -X utf8 r100c_blood-pool-probe.py check | apply | revert
# Root: R100C_ROOT, else <tree>. Line ends kept (CRLF in the tree; the new files are written with
# the line ends of vk_rasterizer.cpp). apply backs the edited originals up in r100c_backup next to this
# script; revert takes out exactly what apply inserted (each inserted text found by itself, exactly
# once) and removes the new files (only when their content is exactly this script's).
import os, sys

ROOT = os.environ.get("R100C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r100c_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
H = RV + "vk_rasterizer.h"
C = RV + "vk_rasterizer.cpp"
E = RV + "vk_rasterizer_effects.cpp"
M = "engine/gpu/CMakeLists.txt"

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
H: [
("#include \"video_core/renderer_vulkan/vk_froyok_bloom.h\"\n",
 "#include \"video_core/renderer_vulkan/vk_blood_pool_probe.h\" // bbport (r100c_blood-pool-probe, TOOL)\n",
 ""),
("    std::unique_ptr<DepthOfField> depth_of_field;\n",
 "    /// bbport (r100c_blood-pool-probe, TOOL): made only with BB_BLOOD_POOL_PROBE not off at start\n"
 "    /// (BloodPoolProbe::Wanted), else null: its hooks are null pointer tests. BloodPoolProbeBefore\n"
 "    /// (vk_blood_pool_probe.cpp) hands it a draw's targets; called only while it is made.\n"
 "    std::unique_ptr<BloodPoolProbe> blood_pool_probe;\n"
 "    void BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light);\n",
 ""),
],
C: [
("    sky_seam = std::make_unique<SkySeam>(instance, scheduler);\n",
 "    // bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE not off at start only\n"
 "    // (BloodPoolProbe::Wanted, read once); its passes and buffers are made at the first probed box.\n"
 "    if (BloodPoolProbe::Wanted()) {\n"
 "        blood_pool_probe = std::make_unique<BloodPoolProbe>(instance, scheduler, texture_cache, runtime,\n"
 "                                                            *scene_targets, *camera_motion);\n"
 "    }\n",
 ""),
("    if (!BindResources(pipeline)) {\n        return;\n    }\n"
 "    auto state = BeginRendering(pipeline); // (SunKeepBeforePass may take its clear over)\n",
 "    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): as EffectsBeforeResources; an\n"
 "        BloodPoolProbeBefore(pipeline, true, false); // indirect draw is never taken for a light draw\n"
 "    }\n",
 ""),
("    DebugState.IncDrawCall();\n\n    ResetBindings(false);\n    scheduler.KickRecording();\n}\n\n"
 "void Rasterizer::DispatchDirect() {\n",
 "    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): as after a direct draw\n"
 "        blood_pool_probe->AfterDraw();\n"
 "    }\n",
 ""),
],
E: [
("void Rasterizer::EffectsOnFrameEnd() {\n",
 "",
 "    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): a new box, the frames, the log\n"
 "        blood_pool_probe->OnFrameEnd();\n"
 "    }\n"),
("void Rasterizer::EffectsBeforeResources(const GraphicsPipeline* pipeline) {\n",
 "",
 "    // bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE only (off: one null pointer test a\n"
 "    // draw). First, so that what the passes below write before this draw counts for it as well.\n"
 "    // A light draw: the shadow resolve, the sun or moon, a lamp of the grid (as r100's kinds).\n"
 "    if (blood_pool_probe) {\n"
 "        const u64 probe_ps = FragmentHash(pipeline);\n"
 "        BloodPoolProbeBefore(pipeline, false,\n"
 "                             PointLightCount(probe_ps) != 0 || probe_ps == DirectionalFragmentShaderHash ||\n"
 "                                 probe_ps == ShadowResolveHash);\n"
 "    }\n"),
("void Rasterizer::EffectsAfterDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,\n"
 "                                  u32 num_indices, u32 num_instances, u32 first_vertex) {\n"
 "    auto& dc = Dc();\n",
 "",
 "    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): the compare right after the draw\n"
 "        blood_pool_probe->AfterDraw();\n"
 "    }\n"),
],
M: [
("    add_custom_command(OUTPUT ${OUT}\n",
 "    # bbport (r100c_blood-pool-probe, TOOL): the probe's numbers, shared with C++ (blood_pool_probe.h)\n"
 "    if (FILENAME MATCHES \"^blood_pool_probe\")\n"
 "        list(APPEND INCLUDES ${SHADER_SRC}/blood_pool_probe_layout.h)\n"
 "    endif()\n",
 ""),
("add_host_shader(volumetric_light.comp volumetric_light_integrate_comp INTEGRATE=1)\n",
 "# bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE only: the probe's snapshot and compare\n"
 "# passes (renderer_vulkan/vk_blood_pool_probe.cpp)\n"
 "add_host_shader(blood_pool_probe.comp blood_pool_probe_snapshot_comp POOL_SNAPSHOT=1)\n"
 "add_host_shader(blood_pool_probe.comp blood_pool_probe_compare_comp POOL_COMPARE=1)\n",
 ""),
],
}

ORDER = (H, C, E, M)

# The new files (LF here; written with the line ends of vk_rasterizer.cpp).
NEW = {}
NEW[HS + "blood_pool_probe_layout.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). What the blood pool probe's shader (blood_pool_probe.comp) and the engine
// (renderer_vulkan/blood_pool_probe.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef BLOOD_POOL_PROBE_LAYOUT_H
#define BLOOD_POOL_PROBE_LAYOUT_H

// Pixels a side of one workgroup.
#define BLOOD_POOL_PROBE_GROUP 8u
// Targets one pass reads: colour targets 0-7 (texture bindings 0-7) and the depth (binding 8).
#define BLOOD_POOL_PROBE_TARGETS 9u
#define BLOOD_POOL_PROBE_DEPTH 8u
// Buffer bindings: the prints (both passes), the counters and the owner maps (the compare only).
#define BLOOD_POOL_PROBE_PRINTS_BINDING 9u
#define BLOOD_POOL_PROBE_COUNTS_BINDING 10u
#define BLOOD_POOL_PROBE_OWNERS_BINDING 11u
// A draw's counter record (words from the push word `record`): pixels of the box where any target
// read changed; frame samples (every stride-th pixel each way) where any changed; then one word a
// target (colour 0-7, depth) of the box pixels where that target changed.
#define BLOOD_POOL_PROBE_RECORD_WORDS 11u
#define BLOOD_POOL_PROBE_WORD_BOX 0u
#define BLOOD_POOL_PROBE_WORD_FRAME 1u
#define BLOOD_POOL_PROBE_WORD_TARGET0 2u
// The owner maps, one word a box pixel each: the last draw that changed there the G-buffer albedo
// (map 0), the scene colour (map 1, draws of more than six indices only) or the depth (map 2).
#define BLOOD_POOL_PROBE_OWNER_MAPS 3u
// The push word `owner_targets`: byte 0 the albedo target's index, byte 1 the scene colour
// target's, 0xff for none; bit 16: the depth's changes count for map 2.
#define BLOOD_POOL_PROBE_NO_TARGET 255u
#define BLOOD_POOL_PROBE_OWN_DEPTH 65536u

#endif
'''
NEW[HS + "blood_pool_probe.comp"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe): TOOL (branch dev/test-tools). Which draws change a box of the
// scene: right before a draw POOL_SNAPSHOT keeps a 32-bit print of each target the draw has (colour
// targets 0-7 and its depth) at every pixel of the box and at every stride-th pixel of the frame
// each way; right after it POOL_COMPARE counts where the prints changed and notes the draw as the
// last writer of the box pixels whose G-buffer albedo, scene colour or depth it changed.
// renderer_vulkan/blood_pool_probe.h has the knob and the numbers, vk_blood_pool_probe.cpp records
// the passes. Log only: no target is written.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "blood_pool_probe_layout.h"

#if !((defined(POOL_SNAPSHOT) && !defined(POOL_COMPARE)) || (!defined(POOL_SNAPSHOT) && defined(POOL_COMPARE)))
#error "blood_pool_probe.comp: define exactly one of POOL_SNAPSHOT, POOL_COMPARE"
#endif

layout(local_size_x = BLOOD_POOL_PROBE_GROUP, local_size_y = BLOOD_POOL_PROBE_GROUP, local_size_z = 1) in;

// BloodPoolProbeRules::Push, word for word (12 words). Dispatch z 0: the box, z 1: the frame samples.
layout(push_constant) uniform Push {
    ivec4 box;          // x0, y0, width, height (scene pixels)
    ivec4 grid;         // frame sample columns, rows, stride, 0
    uint mask;          // targets read: bit t for texture binding t (8: the depth)
    uint record;        // COMPARE: the draw's first counter word
    uint owner;         // COMPARE: the value the owner maps take where the draw changed them
    uint owner_targets; // COMPARE: BLOOD_POOL_PROBE_NO_TARGET, BLOOD_POOL_PROBE_OWN_DEPTH (layout)
};

layout(binding = 0) uniform texture2D target0;
layout(binding = 1) uniform texture2D target1;
layout(binding = 2) uniform texture2D target2;
layout(binding = 3) uniform texture2D target3;
layout(binding = 4) uniform texture2D target4;
layout(binding = 5) uniform texture2D target5;
layout(binding = 6) uniform texture2D target6;
layout(binding = 7) uniform texture2D target7;
layout(binding = 8) uniform texture2D depth_target;
layout(binding = BLOOD_POOL_PROBE_PRINTS_BINDING, std430) buffer Prints {
    uint prints[];
};
#if defined(POOL_COMPARE)
layout(binding = BLOOD_POOL_PROBE_COUNTS_BINDING, std430) buffer Counts {
    uint counts[];
};
layout(binding = BLOOD_POOL_PROBE_OWNERS_BINDING, std430) buffer Owners {
    uint owners[];
};
#endif

// Every bit of the texel goes into the print (float bits: exact for every float, unorm and srgb
// format); two different texels print alike about once in 2^32.
uint Print(vec4 c) {
    const uvec4 u = floatBitsToUint(c);
    uint h = u.x * 0x9E3779B1u;
    h = (h ^ (h >> 15u) ^ u.y) * 0x85EBCA77u;
    h = (h ^ (h >> 13u) ^ u.z) * 0xC2B2AE3Du;
    h = (h ^ (h >> 16u) ^ u.w) * 0x27D4EB2Fu;
    return h ^ (h >> 15u);
}

uint PrintOf(uint t, ivec2 p) {
    vec4 c = vec4(0.0);
    switch (t) {
    case 0u: c = texelFetch(target0, p, 0); break;
    case 1u: c = texelFetch(target1, p, 0); break;
    case 2u: c = texelFetch(target2, p, 0); break;
    case 3u: c = texelFetch(target3, p, 0); break;
    case 4u: c = texelFetch(target4, p, 0); break;
    case 5u: c = texelFetch(target5, p, 0); break;
    case 6u: c = texelFetch(target6, p, 0); break;
    case 7u: c = texelFetch(target7, p, 0); break;
    default: c = vec4(texelFetch(depth_target, p, 0).x, 0.0, 0.0, 0.0); break;
    }
    return Print(c);
}

#if defined(POOL_COMPARE)
// The group's counts, then one atomic per word for the group.
shared uint group_counts[BLOOD_POOL_PROBE_RECORD_WORDS];
#endif

void main() {
    const ivec2 g = ivec2(gl_GlobalInvocationID.xy);
    const bool in_box = gl_GlobalInvocationID.z == 0u;
    const ivec2 size = in_box ? box.zw : grid.xy;
    const bool inside = all(lessThan(g, size));
    const ivec2 p = in_box ? box.xy + g : g * grid.z;
    const uint box_px = uint(box.z * box.w), frame_px = uint(grid.x * grid.y);
    const uint index = uint(g.y * size.x + g.x);
    // prints: the box's 9 planes of box_px words, then the frame samples' 9 planes of frame_px
    const uint base = in_box ? 0u : BLOOD_POOL_PROBE_TARGETS * box_px;
    const uint plane = in_box ? box_px : frame_px;
#if defined(POOL_SNAPSHOT)
    if (inside) {
        for (uint t = 0u; t < BLOOD_POOL_PROBE_TARGETS; ++t) {
            if ((mask & (1u << t)) != 0u) {
                prints[base + t * plane + index] = PrintOf(t, p);
            }
        }
    }
#else
    uint n[BLOOD_POOL_PROBE_RECORD_WORDS];
    for (uint i = 0u; i < BLOOD_POOL_PROBE_RECORD_WORDS; ++i) {
        n[i] = 0u;
    }
    if (inside) {
        bool any_changed = false;
        for (uint t = 0u; t < BLOOD_POOL_PROBE_TARGETS; ++t) {
            if ((mask & (1u << t)) == 0u) {
                continue;
            }
            const bool changed = PrintOf(t, p) != prints[base + t * plane + index];
            any_changed = any_changed || changed;
            if (in_box && changed) {
                n[BLOOD_POOL_PROBE_WORD_TARGET0 + t] = 1u;
                if (t == (owner_targets & 255u)) {
                    owners[index] = owner;
                }
                if (t == ((owner_targets >> 8u) & 255u)) {
                    owners[box_px + index] = owner;
                }
                if (t == BLOOD_POOL_PROBE_DEPTH && (owner_targets & BLOOD_POOL_PROBE_OWN_DEPTH) != 0u) {
                    owners[2u * box_px + index] = owner;
                }
            }
        }
        if (any_changed) {
            n[in_box ? BLOOD_POOL_PROBE_WORD_BOX : BLOOD_POOL_PROBE_WORD_FRAME] = 1u;
        }
    }
    if (gl_LocalInvocationIndex < BLOOD_POOL_PROBE_RECORD_WORDS) {
        group_counts[gl_LocalInvocationIndex] = 0u;
    }
    memoryBarrierShared();
    barrier();
    for (uint i = 0u; i < BLOOD_POOL_PROBE_RECORD_WORDS; ++i) {
        if (n[i] != 0u) {
            atomicAdd(group_counts[i], n[i]);
        }
    }
    memoryBarrierShared();
    barrier();
    const uint w = gl_LocalInvocationIndex;
    if (w < BLOOD_POOL_PROBE_RECORD_WORDS && group_counts[w] != 0u) {
        atomicAdd(counts[record + w], group_counts[w]);
    }
#endif
}
'''
NEW[RV + "blood_pool_probe.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r100c_blood-pool-probe): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). Which draws put what is on screen inside a box of the scene, for finding how the game
// draws the blood pool at the graveyard (r100 marked the draw 1ea84d9a:bd1d09f0, which the r100b run
// showed to be a small object at the hunter's hip, not the pool).
//
// Knob BB_BLOOD_POOL_PROBE (read at start, and again through the live knobs file, BB_LIVE_KNOBS_FILE,
// when that file changes):
//   unset, empty, "0" or "off" at start: off. No BloodPoolProbe is made: its hooks are null pointer
//                 tests and nothing of it runs.
//   "on" or "1":  made, idle until a box comes (a job's set:BB_BLOOD_POOL_PROBE=x0:y0:x1:y1).
//   "x0:y0:x1:y1" a box in scene pixels, both corners inside (x0 <= x1, y0 <= y1, decimal); a side over
//                 MaxSide pixels is cut to MaxSide (said in the log). Each new box arms the probe: it
//                 waits for ArmFramesStart frames in a row with a G-buffer pass when the box came at
//                 start (the level loads first), ArmFramesLive when it came through the live file,
//                 then probes CaptureFrames frames, then logs when the GPU is past them.
//   other text:   no box (said once); the probe stays as it is.
// While probing, every draw whose targets have the scene's size (the G-buffer pass's depth), outside
// a lamps-apart batch, gets a print of each of its targets (colour 0-7, depth) in the box and at
// every Stride-th pixel of the frame each way right before it, and a compare right after it.
// No Vulkan here: the static_asserts below are the parse's tests (they run at every compile).

#include <cstdint>

#include "../host_shaders/blood_pool_probe_layout.h"

namespace Vulkan::BloodPoolProbeRules {

inline constexpr std::uint32_t Group = BLOOD_POOL_PROBE_GROUP;
inline constexpr std::uint32_t Targets = BLOOD_POOL_PROBE_TARGETS;
inline constexpr std::uint32_t DepthTarget = BLOOD_POOL_PROBE_DEPTH;
inline constexpr std::uint32_t RecordWords = BLOOD_POOL_PROBE_RECORD_WORDS;
inline constexpr std::uint32_t WordBox = BLOOD_POOL_PROBE_WORD_BOX;
inline constexpr std::uint32_t WordFrame = BLOOD_POOL_PROBE_WORD_FRAME;
inline constexpr std::uint32_t WordTarget0 = BLOOD_POOL_PROBE_WORD_TARGET0;
inline constexpr std::uint32_t OwnerMaps = BLOOD_POOL_PROBE_OWNER_MAPS;
inline constexpr std::uint32_t NoTarget = BLOOD_POOL_PROBE_NO_TARGET;
inline constexpr std::uint32_t OwnDepth = BLOOD_POOL_PROBE_OWN_DEPTH;
static_assert(Group == 8u && Targets == 9u && DepthTarget == Targets - 1u);
static_assert(WordBox == 0u && WordFrame == 1u && WordTarget0 == 2u && RecordWords == WordTarget0 + Targets);
static_assert(OwnerMaps == 3u && NoTarget == 255u && OwnDepth == 65536u);
static_assert(BLOOD_POOL_PROBE_PRINTS_BINDING == Targets && BLOOD_POOL_PROBE_COUNTS_BINDING == Targets + 1u &&
              BLOOD_POOL_PROBE_OWNERS_BINDING == Targets + 2u);

/// A box side is at most this many pixels (the owner maps and the box prints are sized by it).
inline constexpr std::uint32_t MaxSide = 256;
/// Frames in a row with a G-buffer pass before probing: a box given at start (the level loads
/// first), one given through the live knobs file (the camera has stopped).
inline constexpr std::uint32_t ArmFramesStart = 600, ArmFramesLive = 30;
/// Frames probed after that, and draws a frame looked at (the rest are counted "over the cap").
inline constexpr std::uint32_t CaptureFrames = 2, MaxDraws = 4096;
/// The frame is sampled at every Stride-th pixel each way (its counts are times Stride squared).
inline constexpr std::uint32_t Stride = 4;
/// Frame ends to wait for the GPU after the last probed frame before logging what is there.
inline constexpr std::uint32_t WaitFrames = 240;
/// Pair lines at most (sorted by box pixels owned, then by box pixels changed); the rest are summed
/// in one line. 16 keeps a box's lines inside the slot runner's 30 evidence lines of a job.
inline constexpr std::uint32_t MaxLines = 16;
/// Owner values: (capture frame + 1) << OwnerFrameShift | draw number in that frame.
inline constexpr std::uint32_t OwnerFrameShift = 16;
static_assert(MaxDraws <= (1u << OwnerFrameShift) && CaptureFrames < 255u);
static_assert(MaxSide * MaxSide * Targets < (1u << 24), "the box prints stay small");

/// BloodPoolProbeRules::Push, word for word with blood_pool_probe.comp's push block.
struct Push {
    std::int32_t box[4];  ///< x0, y0, width, height
    std::int32_t grid[4]; ///< frame sample columns, rows, stride, 0
    std::uint32_t mask = 0;
    std::uint32_t record = 0;
    std::uint32_t owner = 0;
    std::uint32_t owner_targets = 0;
};
static_assert(sizeof(Push) == 48);

enum class Kind : std::uint8_t { Off, On, Box, Bad };
struct Knob {
    Kind kind = Kind::Off;
    std::uint32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0; ///< both corners inside the box
    bool cut = false;                              ///< a side was cut to MaxSide
    [[nodiscard]] constexpr std::uint32_t Width() const { return x1 - x0 + 1; }
    [[nodiscard]] constexpr std::uint32_t Height() const { return y1 - y0 + 1; }
    [[nodiscard]] constexpr bool SameBox(const Knob& o) const {
        return kind == Kind::Box && o.kind == Kind::Box && x0 == o.x0 && y0 == o.y0 && x1 == o.x1 &&
               y1 == o.y1;
    }
};

/// The knob's text (nullptr: not set). Spaces and tabs around it are left out.
constexpr Knob Parse(const char* text) {
    Knob k{};
    if (!text) {
        return k;
    }
    while (*text == ' ' || *text == '\t') {
        ++text;
    }
    const char* end = text;
    while (*end) {
        ++end;
    }
    while (end > text && (end[-1] == ' ' || end[-1] == '\t')) {
        --end;
    }
    if (end == text || (end - text == 1 && *text == '0') ||
        (end - text == 3 && text[0] == 'o' && text[1] == 'f' && text[2] == 'f')) {
        return k; // off
    }
    if ((end - text == 1 && *text == '1') || (end - text == 2 && text[0] == 'o' && text[1] == 'n')) {
        k.kind = Kind::On;
        return k;
    }
    std::uint32_t v[4]{};
    int n = 0;
    const char* c = text;
    while (n < 4) {
        if (c == end || *c < '0' || *c > '9') {
            k.kind = Kind::Bad;
            return k;
        }
        std::uint32_t x = 0;
        while (c != end && *c >= '0' && *c <= '9') {
            x = x * 10u + std::uint32_t(*c - '0');
            if (x > 16383u) {
                k.kind = Kind::Bad;
                return k;
            }
            ++c;
        }
        v[n++] = x;
        if (n < 4) {
            if (c == end || *c != ':') {
                k.kind = Kind::Bad;
                return k;
            }
            ++c;
        }
    }
    if (c != end || v[2] < v[0] || v[3] < v[1]) {
        k.kind = Kind::Bad;
        return k;
    }
    k.kind = Kind::Box;
    k.x0 = v[0];
    k.y0 = v[1];
    k.x1 = v[2];
    k.y1 = v[3];
    if (k.Width() > MaxSide) {
        k.x1 = k.x0 + MaxSide - 1;
        k.cut = true;
    }
    if (k.Height() > MaxSide) {
        k.y1 = k.y0 + MaxSide - 1;
        k.cut = true;
    }
    return k;
}

static_assert(Parse(nullptr).kind == Kind::Off && Parse("").kind == Kind::Off && Parse(" 0 ").kind == Kind::Off &&
              Parse("off").kind == Kind::Off);
static_assert(Parse("on").kind == Kind::On && Parse("1").kind == Kind::On);
static_assert(Parse("1150:620:1329:799").kind == Kind::Box && Parse("1150:620:1329:799").Width() == 180 &&
              Parse("1150:620:1329:799").Height() == 180 && !Parse("1150:620:1329:799").cut);
static_assert(Parse("895:661:930:706").x1 == 930 && Parse("5:5:5:5").Width() == 1);
static_assert(Parse("0:0:1919:1079").cut && Parse("0:0:1919:1079").Width() == MaxSide &&
              Parse("0:0:1919:1079").Height() == MaxSide);
static_assert(Parse("10:10:5:20").kind == Kind::Bad && Parse("1:2:3").kind == Kind::Bad &&
              Parse("1:2:3:4:5").kind == Kind::Bad && Parse("a:b:c:d").kind == Kind::Bad &&
              Parse("1,2,3,4").kind == Kind::Bad && Parse("99999:0:99999:1").kind == Kind::Bad &&
              Parse("on please").kind == Kind::Bad);
static_assert(Parse("1:2:3:4").SameBox(Parse(" 1:2:3:4 ")) && !Parse("1:2:3:4").SameBox(Parse("1:2:3:5")));

/// Phases of a draw in its frame, one bit each (the log prints the letters PGBLA).
enum Phase : std::uint8_t {
    BeforeGbuffer = 1, ///< P: before the frame's first G-buffer pass
    Gbuffer = 2,       ///< G: a G-buffer pass's draw (5 or more colour targets and a depth)
    BeforeLight = 4,   ///< B: after a G-buffer pass, before its first light draw
    Light = 8,         ///< L: a light draw (shadow resolve, sun or moon, a lamp of the grid)
    AfterLight = 16,   ///< A: after the light draws began
};

/// The owner value of draw `ordinal` of capture frame `frame`; 0 is "no owner".
constexpr std::uint32_t OwnerValue(std::uint32_t frame, std::uint32_t ordinal) {
    return ((frame + 1u) << OwnerFrameShift) | ordinal;
}
static_assert(OwnerValue(0, 0) != 0 && (OwnerValue(1, 7) >> OwnerFrameShift) == 2u &&
              (OwnerValue(1, 4095) & 0xffffu) == 4095u);

} // namespace Vulkan::BloodPoolProbeRules
'''
NEW[RV + "vk_blood_pool_probe.h"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). Lists the draws that change a box of the scene (blood_pool_probe.h has the knob and the
// numbers, host_shaders/blood_pool_probe.comp the passes).
//
// Where (each hook a null pointer test while it is off):
//  - Rasterizer::BloodPoolProbeBefore, from EffectsBeforeResources (direct draws) and
//    DrawIndirectRecord (indirect draws), after the draw's targets are found and before its
//    textures, barriers and pass: BeforeDraw notes the draw and, while probing, records SNAPSHOT.
//  - EffectsAfterDraw and DrawIndirectRecord after the draw command: AfterDraw records COMPARE.
//  - EffectsOnFrameEnd: OnFrameEnd takes a new box from the knob, counts the frames before probing,
//    and logs the "Blood pool probe (r100c)" lines when the GPU is past the probed frames.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do. Nothing the game draws is changed: the passes only read its targets.
//
// Off (BB_BLOOD_POOL_PROBE unset, empty, 0 or off at start): the rasterizer makes no BloodPoolProbe
// (Wanted), so nothing of this is made or run. Made but idle (no box, or done): two compares a draw
// and a look at the live knobs generation a frame. While probing (CaptureFrames frames): two passes
// and two render pass splits for every draw into scene-sized targets.
#pragma once

#include <array>
#include <cstddef>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_pool_probe.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace AmdGpu {
union Regs;
}

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class BloodPoolProbe {
public:
    /// BB_BLOOD_POOL_PROBE at start is not off (BloodPoolProbeRules::Parse, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knob once; a box given at start arms the probe.
    BloodPoolProbe(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
                   Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~BloodPoolProbe();
    BloodPoolProbe(const BloodPoolProbe&) = delete;
    BloodPoolProbe& operator=(const BloodPoolProbe&) = delete;

    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target, `light` a light draw (shadow resolve, sun or moon,
    /// lamp grid), `lamps_pending` a lamps-apart batch is open, `indirect` an indirect draw.
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth, bool light,
                    bool lamps_pending, bool indirect);
    /// After every draw command: COMPARE when BeforeDraw recorded SNAPSHOT for it.
    void AfterDraw();
    /// Every frame end.
    void OnFrameEnd();

private:
    enum class State { Idle, Armed, Capturing, Waiting };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// What the log needs of one draw of a probed frame.
    struct DrawInfo {
        u64 vs = 0, ps = 0;
        u32 indices = 0, instances = 0;
        u32 mrt = 0;
        std::array<u32, 8> format{};   ///< vk::Format of each bound colour target
        std::array<u8, 8> role{};      ///< RoleName index
        u32 write_masks = 0;           ///< 4 bits a colour target
        u32 depth_format = 0;
        u32 read_mask = 0;             ///< targets SNAPSHOT read (bit 8: the depth)
        u8 blend = 0;                  ///< a bit a colour target: blending on
        u8 depth_func = 0;
        u8 phase = 0;                  ///< BloodPoolProbeRules::Phase
        bool depth_test = false, depth_write = false, indirect = false, light = false;
        bool probed = false;           ///< COMPARE recorded
        u8 skipped = 0;                ///< Skip reason (0: none)
    };
    enum Skip : u8 { NotSkipped, LampsApart, NotScene, Unreadable, LeftOut, Preview, NoView };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    /// A game image's view for sampling in a pass (the reduced proxy or the image, General layout);
    /// null when it cannot be sampled.
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect);
    void TakeKnob(bool at_start);
    bool StartCapture();
    void EndCapture();
    void Log();
    void Fail(const char* why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, compare_pass;
    Buffer prints, counts, owners;
    vk::DeviceSize prints_size = 0;
    std::array<ViewEntry, 16> view_cache{};
    u64 view_uses = 0;
    bool tried = false, failed = false;

    State state = State::Idle;
    BloodPoolProbeRules::Knob box{};  ///< the box being probed (or last probed)
    BloodPoolProbeRules::Knob next{}; ///< a box that came while the probe was busy
    BloodPoolProbeRules::Knob last_taken{}; ///< the knob's last box (a file change of another knob keeps it)
    bool next_live = false, box_live = false;
    u32 knob_generation = 0;
    u32 arm_need = 0, arm_frames = 0, wait_frames = 0;
    u64 done_tick = 0;

    // This frame.
    bool frame_gbuffer = false;  ///< a G-buffer pass was drawn
    bool frame_lit = false;      ///< a light draw came after the last G-buffer pass
    u32 ordinal = 0;             ///< draws seen this frame
    VideoCore::ImageId scene_depth{};
    u32 scene_width = 0, scene_height = 0;      ///< the scene depth's size
    // The probed frames.
    u32 capture = 0;                            ///< the probed frame being drawn
    bool capture_reduced = false;
    u32 cap_width = 0, cap_height = 0;          ///< the scene depth's size (targets of it are probed)
    u32 pixels_width = 0, pixels_height = 0;    ///< scene pixels (the render size)
    u32 grid_cols = 0, grid_rows = 0;
    std::array<std::vector<DrawInfo>, BloodPoolProbeRules::CaptureFrames> infos;
    std::array<u32, BloodPoolProbeRules::CaptureFrames> over_cap{};
    struct Pending {
        bool on = false;
        u32 ordinal = 0;
        u32 mask = 0;
        std::array<VideoCore::ImageId, BloodPoolProbeRules::Targets> ids{};
        u32 owner_targets = 0;
    } pending;
};

} // namespace Vulkan
'''
NEW[RV + "vk_blood_pool_probe.cpp"] = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe): TOOL (branch dev/test-tools). vk_blood_pool_probe.h says where it
// hooks in and what it costs; blood_pool_probe.h has the knob.
#include "video_core/renderer_vulkan/vk_blood_pool_probe.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <utility>

#include "bbport_live_knobs.h"
#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_pool_probe_compare_comp.h"
#include "video_core/host_shaders/blood_pool_probe_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = BloodPoolProbeRules;
constexpr const char* KnobName = "BB_BLOOD_POOL_PROBE";
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr vk::DeviceSize CountsBytes = vk::DeviceSize(R::CaptureFrames) * R::MaxDraws * R::RecordWords * 4;
constexpr vk::DeviceSize OwnersBytes = vk::DeviceSize(R::OwnerMaps) * R::MaxSide * R::MaxSide * 4;
/// Role names (DrawInfo::role): 1-8 the G-buffer pass's targets 0-7, then a light draw's and the
/// scene colour (RGBA16F with the scene depth).
constexpr const char* RoleNames[] = {"", "nrm", "mat", "alb", "spc", "g4", "g5", "g6", "g7", "lit", "scn"};
constexpr u8 RoleLight = 9, RoleScene = 10;
constexpr const char* FuncNames[] = {"never", "lt", "eq", "le", "gt", "ne", "ge", "always"};

/// A colour target format the passes sample as floats (an integer format would need another
/// texture type): its short name in the log, else null.
const char* ColourName(vk::Format format) {
    switch (format) {
    case vk::Format::eR8G8B8A8Unorm:
        return "8";
    case vk::Format::eR8G8B8A8Srgb:
        return "8s";
    case vk::Format::eB8G8R8A8Unorm:
        return "b8";
    case vk::Format::eB8G8R8A8Srgb:
        return "b8s";
    case vk::Format::eA2B10G10R10UnormPack32:
        return "10";
    case vk::Format::eB10G11R11UfloatPack32:
        return "11f";
    case vk::Format::eR16G16B16A16Sfloat:
        return "16f";
    case vk::Format::eR16G16Sfloat:
        return "rg16f";
    case vk::Format::eR16Sfloat:
        return "r16f";
    case vk::Format::eR32Sfloat:
        return "32f";
    case vk::Format::eR32G32Sfloat:
        return "rg32f";
    case vk::Format::eR32G32B32A32Sfloat:
        return "128f";
    case vk::Format::eR8Unorm:
        return "r8";
    case vk::Format::eR8G8Unorm:
        return "rg8";
    case vk::Format::eR16G16B16A16Unorm:
        return "16u";
    default:
        return nullptr;
    }
}

const char* DepthName(vk::Format format) {
    switch (format) {
    case vk::Format::eD32SfloatS8Uint:
        return "d32s8";
    case vk::Format::eD32Sfloat:
        return "d32";
    case vk::Format::eD24UnormS8Uint:
        return "d24s8";
    case vk::Format::eD16Unorm:
        return "d16";
    default:
        return "d?";
    }
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// What a pass's commands begin with: the game's writes before it are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
}

/// And end with: the game's next work waits for the pass's reads, the next pass for its writes.
void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, ReadWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// Records one pass: the nine targets (unused bindings hold a view of a used one; the mask keeps
/// the shader off them), the prints, and for COMPARE the counters and owner maps.
void RecordPass(vk::CommandBuffer cmd, vk::Pipeline pipeline, vk::PipelineLayout layout,
                const std::array<vk::ImageView, R::Targets>& views, vk::Buffer prints, vk::Buffer counts,
                vk::Buffer owners, const R::Push& push, u32 groups_x, u32 groups_y) {
    BeginBarrier(cmd);
    std::array<vk::DescriptorImageInfo, R::Targets> images{};
    std::array<vk::WriteDescriptorSet, R::Targets + 3> writes{};
    for (u32 t = 0; t < R::Targets; ++t) {
        images[t] = Info(views[t]);
        writes[t] = {.dstBinding = t,
                     .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage,
                     .pImageInfo = &images[t]};
    }
    const std::array<vk::DescriptorBufferInfo, 3> buffers{
        vk::DescriptorBufferInfo{prints, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{counts, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{owners, 0, VK_WHOLE_SIZE}};
    const u32 buffer_count = counts ? 3u : 1u;
    for (u32 b = 0; b < buffer_count; ++b) {
        writes[R::Targets + b] = {.dstBinding = R::Targets + b,
                                  .descriptorCount = 1,
                                  .descriptorType = vk::DescriptorType::eStorageBuffer,
                                  .pBufferInfo = &buffers[b]};
    }
    cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
    cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                             vk::ArrayProxy<const vk::WriteDescriptorSet>(R::Targets + buffer_count,
                                                                          writes.data()));
    cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
    cmd.dispatch(groups_x, groups_y, 2);
    EndBarrier(cmd);
}
} // namespace

bool BloodPoolProbe::Wanted() {
    static const bool wanted = R::Parse(std::getenv(KnobName)).kind != R::Kind::Off;
    return wanted;
}

BloodPoolProbe::BloodPoolProbe(const Instance& instance_, Scheduler& scheduler_,
                               VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                               SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const char* env = std::getenv(KnobName);
    BbReport::Printf("Blood pool probe (r100c, TOOL): on (%s=%.32s); a box x0:y0:x1:y1 in scene pixels "
                     "(this value or the live knobs file) is probed after %u frames with a G-buffer pass "
                     "(%u after a live change): every draw of %u frames\n",
                     KnobName, env ? env : "", R::ArmFramesStart, R::ArmFramesLive, R::CaptureFrames);
    knob_generation = BbLiveKnobs::Generation();
    TakeKnob(true);
}

BloodPoolProbe::~BloodPoolProbe() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(prints);
    FreeBuffer(counts);
    FreeBuffer(owners);
}

bool BloodPoolProbe::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation, &info) !=
        VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void BloodPoolProbe::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodPoolProbe::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_SNAPSHOT_COMP, "Blood pool probe snapshot") &&
        EffectPass::Create(instance, compare_pass.set_layout, compare_pass.layout, compare_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer,
                            eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_COMPARE_COMP, "Blood pool probe compare") &&
        MakeBuffer(counts, CountsBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(owners, OwnersBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void BloodPoolProbe::Fail(const char* why) {
    failed = true;
    state = State::Idle;
    pending = {};
    BbReport::Printf("Blood pool probe (r100c): off - %s\n", why);
}

vk::ImageView BloodPoolProbe::CachedView(const VideoCore::Image& image, vk::Format format,
                                         vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == format &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create blood pool probe view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

vk::ImageView BloodPoolProbe::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect) {
    auto& image = texture_cache.GetImage(id);
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, ShaderRead);
        return (proxy.usage & vk::ImageUsageFlagBits::eSampled) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & vk::ImageUsageFlagBits::eSampled)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, ShaderRead);
    return view;
}

void BloodPoolProbe::TakeKnob(bool at_start) {
    const BbLiveKnobs::Text text = BbLiveKnobs::Lookup(KnobName);
    const char* value = text.Get();
    const R::Knob k = R::Parse(value);
    switch (k.kind) {
    case R::Kind::Box:
        if (!at_start && k.SameBox(last_taken)) {
            return; // (another knob of the file changed)
        }
        last_taken = k;
        next = k;
        next_live = text.in_file;
        return;
    case R::Kind::Off:
    case R::Kind::On:
        last_taken = {};
        next = {};
        if (state == State::Armed) {
            state = State::Idle;
            BbReport::Printf("Blood pool probe (r100c): box x %u-%u y %u-%u dropped before probing (%s=%.16s)\n",
                             box.x0, box.x1, box.y0, box.y1, KnobName, value ? value : "");
        }
        return;
    case R::Kind::Bad:
        BbReport::Printf("Blood pool probe (r100c): %s=%.40s is no box (x0:y0:x1:y1, decimal, x0<=x1, "
                         "y0<=y1); nothing changed\n",
                         KnobName, value ? value : "");
        return;
    }
}

void BloodPoolProbe::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                                const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                                bool light, bool lamps_pending, bool indirect) {
    if (pending.on) {
        // The draw SNAPSHOT was recorded for was left out (a pipeline still compiling, a cascade
        // nothing samples): no COMPARE for it.
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    if (state == State::Idle || state == State::Waiting) {
        return;
    }
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    const bool gbuffer = std::popcount(mrt) >= 5 && bool(depth);
    const u8 phase = gbuffer                ? R::Gbuffer
                     : light                ? R::Light
                     : !frame_gbuffer       ? R::BeforeGbuffer
                     : frame_lit            ? R::AfterLight
                                            : R::BeforeLight;
    if (gbuffer) {
        frame_gbuffer = true;
        frame_lit = false;
        scene_depth = depth;
        const auto& image = texture_cache.GetImage(depth);
        scene_width = image.info.size.width;
        scene_height = image.info.size.height;
    } else if (light) {
        frame_lit = true;
    }
    if (state != State::Capturing) {
        return;
    }
    const u32 n = ordinal++;
    auto& list = infos[capture];
    if (n >= R::MaxDraws || n != list.size()) {
        ++over_cap[capture];
        return;
    }
    DrawInfo& info = list.emplace_back();
    info.vs = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    info.ps = ps ? ps->pgm_hash : 0;
    info.indices = indirect ? 0u : u32(regs.num_indices);
    info.instances = indirect ? 0u : regs.num_instances.NumInstances();
    info.mrt = mrt;
    info.phase = phase;
    info.indirect = indirect;
    info.light = light;
    info.depth_test = regs.depth_control.depth_enable != 0 && bool(depth);
    info.depth_write = info.depth_test && regs.depth_control.depth_write_enable != 0;
    info.depth_func = u8(u32(regs.depth_control.depth_func) & 7u);
    std::array<VideoCore::ImageId, R::Targets> ids{};
    for (u32 cb = 0; cb < 8; ++cb) {
        if (((mrt >> cb) & 1u) == 0 || !targets[cb]) {
            continue;
        }
        ids[cb] = targets[cb];
        const auto& image = texture_cache.GetImage(targets[cb]);
        info.format[cb] = u32(image.info.pixel_format);
        info.write_masks |= (regs.color_target_mask.GetMask(cb) & 15u) << (4 * cb);
        if (regs.blend_control[cb].enable && !regs.color_buffers[cb].info.blend_bypass) {
            info.blend |= u8(1u << cb);
        }
        info.role[cb] = gbuffer ? u8(1 + cb)
                        : light ? RoleLight
                        : (cb == 0 && image.info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
                           depth && depth == scene_depth)
                            ? RoleScene
                            : u8(0);
    }
    if (depth) {
        ids[R::DepthTarget] = depth;
        info.depth_format = u32(texture_cache.GetImage(depth).info.pixel_format);
    }
    if (camera_motion.PreviewFrame()) {
        info.skipped = Preview;
        return;
    }
    // Lamps apart (vk_point_shadow.h): an open batch's lamps go into images of their own, so the
    // light targets do not hold them yet; those draws are left alone (no read while it is open).
    if (lamps_pending) {
        info.skipped = LampsApart;
        return;
    }
    // The targets of the scene's size (the G-buffer pass's depth, or its reduced proxy) that the
    // passes can sample.
    u32 mask = 0;
    bool other_size = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if (!ids[t]) {
            continue;
        }
        const auto& image = texture_cache.GetImage(ids[t]);
        const bool proxy = scene_targets.Reduced() && scene_targets.EligibleScene(image);
        const bool scene_sized = proxy == capture_reduced &&
                                 (proxy || (image.info.size.width == cap_width &&
                                            image.info.size.height == cap_height));
        if (!scene_sized) {
            other_size = true;
            continue;
        }
        if ((t != R::DepthTarget && !ColourName(image.info.pixel_format)) || image.info.num_samples != 1) {
            continue; // (the passes read single-sample float textures)
        }
        mask |= 1u << t;
    }
    if (!mask) {
        info.skipped = other_size ? NotScene : Unreadable;
        return;
    }
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((mask >> t) & 1u) {
            views[t] = ViewOf(ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                          : vk::ImageAspectFlagBits::eColor);
            if (!views[t]) {
                mask &= ~(1u << t);
            }
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!mask) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    // Owners: the G-buffer's albedo (target 2), the scene colour by a draw of more than six indices
    // (full-screen passes left out; an indirect draw's count is unknown: taken), the depth.
    u32 albedo = R::NoTarget, scene = R::NoTarget;
    if (gbuffer && ((mask >> 2) & 1u)) {
        albedo = 2;
    }
    if (info.role[0] == RoleScene && (mask & 1u) && (indirect || info.indices > 6 || info.instances > 1)) {
        scene = 0;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = mask;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    info.read_mask = mask;
    scheduler.RecordCrumb({.name = "blood pool probe snapshot"},
                          [views, push, gx, gy, prints_buffer = prints.buffer,
                           pipeline_handle = *snapshot_pass.pipeline,
                           layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, {}, {}, push,
                                         gx, gy);
                          });
    pending = {.on = true,
               .ordinal = n,
               .mask = mask,
               .ids = ids,
               .owner_targets = albedo | (scene << 8) | ((mask >> R::DepthTarget) & 1u ? R::OwnDepth : 0u)};
}

void BloodPoolProbe::AfterDraw() {
    if (!pending.on) {
        return;
    }
    const Pending p = pending;
    pending = {};
    DrawInfo& info = infos[capture][p.ordinal];
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    bool lost = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((p.mask >> t) & 1u) {
            views[t] = ViewOf(p.ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                            : vk::ImageAspectFlagBits::eColor);
            lost = lost || !views[t];
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (lost) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(p.mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = p.mask;
    push.record = (capture * R::MaxDraws + p.ordinal) * R::RecordWords;
    push.owner = R::OwnerValue(capture, p.ordinal);
    push.owner_targets = p.owner_targets;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    scheduler.RecordCrumb({.name = "blood pool probe compare"},
                          [views, push, gx, gy, prints_buffer = prints.buffer, counts_buffer = counts.buffer,
                           owners_buffer = owners.buffer, pipeline_handle = *compare_pass.pipeline,
                           layout = *compare_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, counts_buffer,
                                         owners_buffer, push, gx, gy);
                          });
    info.probed = true;
}

bool BloodPoolProbe::StartCapture() {
    if (!scene_depth || scene_width == 0 || scene_height == 0) {
        return false;
    }
    const auto& depth_image = texture_cache.GetImage(scene_depth);
    cap_width = scene_width;
    cap_height = scene_height;
    capture_reduced = scene_targets.Reduced() && scene_targets.EligibleScene(depth_image);
    pixels_width = cap_width;
    pixels_height = cap_height;
    if (capture_reduced) {
        pixels_width = scene_targets.Size().width;
        pixels_height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        pixels_width = std::min(pixels_width, render[0]);
        pixels_height = std::min(pixels_height, render[1]);
    }
    if (box.x1 >= pixels_width || box.y1 >= pixels_height) {
        BbReport::Printf("Blood pool probe (r100c): box x %u-%u y %u-%u is not inside the %ux%u scene; "
                         "not probed\n",
                         box.x0, box.x1, box.y0, box.y1, pixels_width, pixels_height);
        state = State::Idle;
        return false;
    }
    if (!Ready()) {
        return false;
    }
    grid_cols = (pixels_width + R::Stride - 1) / R::Stride;
    grid_rows = (pixels_height + R::Stride - 1) / R::Stride;
    const vk::DeviceSize need =
        (vk::DeviceSize(box.Width()) * box.Height() + vk::DeviceSize(grid_cols) * grid_rows) * R::Targets * 4;
    if (need > prints_size) {
        if (prints.buffer) {
            scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = prints.buffer,
                                      allocation = prints.allocation] {
                vmaDestroyBuffer(allocator, buffer, allocation);
            });
            prints = {};
            prints_size = 0;
        }
        if (!EffectPass::HasRoom(instance, need) ||
            !MakeBuffer(prints, need, false, vk::BufferUsageFlagBits::eStorageBuffer)) {
            prints = {};
            Fail("no room for the prints");
            return false;
        }
        prints_size = need;
    }
    for (auto& list : infos) {
        list.clear();
        list.reserve(2048);
    }
    over_cap = {};
    capture = 0;
    pending = {};
    // The counters and owner maps start at 0 (the host reads them once the GPU is past the frames).
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe clear"},
                          [counts_buffer = counts.buffer, owners_buffer = owners.buffer](vk::CommandBuffer cmd) {
                              EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryRead,
                                                        Transfer, vk::AccessFlagBits2::eTransferWrite);
                              cmd.fillBuffer(counts_buffer, 0, VK_WHOLE_SIZE, 0);
                              cmd.fillBuffer(owners_buffer, 0, VK_WHOLE_SIZE, 0);
                              EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                                        Compute, ReadWrite);
                          });
    return true;
}

void BloodPoolProbe::EndCapture() {
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe done"}, [](vk::CommandBuffer cmd) {
        EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                  vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
    });
    done_tick = scheduler.CurrentTick();
}

void BloodPoolProbe::OnFrameEnd() {
    if (pending.on) {
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    if (const u32 generation = BbLiveKnobs::Generation(); generation != knob_generation) {
        knob_generation = generation;
        TakeKnob(false);
    }
    switch (state) {
    case State::Idle:
        if (next.kind == R::Kind::Box && !failed) {
            box = next;
            box_live = next_live;
            next = {};
            arm_need = box_live ? R::ArmFramesLive : R::ArmFramesStart;
            arm_frames = 0;
            state = State::Armed;
            BbReport::Printf("Blood pool probe (r100c): box x %u-%u y %u-%u (%u px)%s armed (%s); probed "
                             "after %u frames in a row with a G-buffer pass\n",
                             box.x0, box.x1, box.y0, box.y1, box.Width() * box.Height(),
                             box.cut ? ", a side cut to 256" : "", box_live ? "live knobs file" : "at start",
                             arm_need);
        }
        break;
    case State::Armed:
        arm_frames = frame_gbuffer && !camera_motion.PreviewFrame() ? arm_frames + 1 : 0;
        if (arm_frames >= arm_need && StartCapture()) {
            state = State::Capturing;
        }
        break;
    case State::Capturing:
        if (++capture >= R::CaptureFrames) {
            capture = R::CaptureFrames - 1;
            EndCapture();
            state = State::Waiting;
            wait_frames = 0;
        }
        break;
    case State::Waiting:
        if (scheduler.IsFree(done_tick) || ++wait_frames >= R::WaitFrames) {
            Log();
            state = State::Idle;
        }
        break;
    }
    frame_gbuffer = frame_lit = false;
    ordinal = 0;
}

void BloodPoolProbe::Log() {
    const bool gpu_done = scheduler.IsFree(done_tick);
    const auto* c = static_cast<const u32*>(counts.mapped);
    const auto* o = static_cast<const u32*>(owners.mapped);
    const u32 frames = R::CaptureFrames;
    const u32 box_px = box.Width() * box.Height();
    struct Sum {
        u64 vs = 0, ps = 0;
        u32 draws = 0, probed = 0, box_draws = 0, box_max = 0;
        u64 box = 0, frame = 0;
        std::array<u64, R::Targets> by_target{};
        std::array<u32, R::OwnerMaps> own{};
        u32 idx_min = ~0u, idx_max = 0, inst_max = 0;
        u8 phases = 0;
        bool indirect = false;
        const DrawInfo* rep = nullptr;
        bool rep_changed = false;
        int first = -1, last = -1;
    };
    std::vector<Sum> sums;
    std::map<std::pair<u64, u64>, std::size_t> where;
    std::array<u32, 7> skipped{};
    u32 probed = 0;
    int gb_first = -1, gb_last = -1, light_first = -1;
    const u32 last_frame = frames - 1;
    for (u32 f = 0; f < frames; ++f) {
        for (u32 i = 0; i < infos[f].size(); ++i) {
            const DrawInfo& d = infos[f][i];
            const auto [it, added] = where.try_emplace({d.vs, d.ps}, sums.size());
            if (added) {
                sums.push_back({.vs = d.vs, .ps = d.ps});
            }
            Sum& s = sums[it->second];
            ++s.draws;
            s.phases |= d.phase;
            s.indirect = s.indirect || d.indirect;
            if (!d.indirect) {
                s.idx_min = std::min(s.idx_min, d.indices);
                s.idx_max = std::max(s.idx_max, d.indices);
                s.inst_max = std::max(s.inst_max, d.instances);
            }
            if (f == last_frame) {
                s.first = s.first < 0 ? int(i) : s.first;
                s.last = int(i);
                if (d.phase == R::Gbuffer) {
                    gb_first = gb_first < 0 ? int(i) : gb_first;
                    gb_last = int(i);
                } else if (d.phase == R::Light && light_first < 0) {
                    light_first = int(i);
                }
            }
            u32 changed = 0;
            if (d.probed) {
                ++probed;
                ++s.probed;
                const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
                changed = r[R::WordBox];
                s.box += changed;
                s.frame += r[R::WordFrame];
                s.box_max = std::max(s.box_max, changed);
                s.box_draws += changed != 0 ? 1u : 0u;
                for (u32 t = 0; t < R::Targets; ++t) {
                    s.by_target[t] += r[R::WordTarget0 + t];
                }
            } else if (d.skipped < skipped.size()) {
                ++skipped[d.skipped];
            }
            if (!s.rep || (!s.rep_changed && changed != 0)) {
                s.rep = &d;
                s.rep_changed = changed != 0;
            }
        }
    }
    // The owner maps: the last change of each box pixel over the probed frames.
    std::array<u32, R::OwnerMaps> owned{}, owner_pairs{};
    std::vector<std::array<bool, R::OwnerMaps>> owns(sums.size());
    for (u32 m = 0; m < R::OwnerMaps; ++m) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || f >= frames || n >= infos[f].size()) {
                continue;
            }
            const DrawInfo& d = infos[f][n];
            const std::size_t k = where[{d.vs, d.ps}];
            ++sums[k].own[m];
            ++owned[m];
            if (!owns[k][m]) {
                owns[k][m] = true;
                ++owner_pairs[m];
            }
        }
    }
    std::vector<std::size_t> order;
    for (std::size_t k = 0; k < sums.size(); ++k) {
        const Sum& s = sums[k];
        if (s.box != 0 || s.own[0] != 0 || s.own[1] != 0 || s.own[2] != 0) {
            order.push_back(k);
        }
    }
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        const Sum &x = sums[a], &y = sums[b];
        const u64 ox = u64(x.own[0]) + x.own[1] + x.own[2], oy = u64(y.own[0]) + y.own[1] + y.own[2];
        // owners first: full-screen passes change the whole box but own none of it
        return ox != oy ? ox > oy : x.box != y.box ? x.box > y.box : a < b;
    });
    char line[280];
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100c): box x %u-%u y %u-%u (%u px)%s of the %ux%u scene%s, %u frames, logged "
                  "%s; last frame: G-buffer draws #%d-%d, light draws from #%d",
                  box.x0, box.x1, box.y0, box.y1, box_px, box.cut ? " (cut)" : "", pixels_width, pixels_height,
                  capture_reduced ? " (reduced)" : "", frames,
                  gpu_done ? "after the GPU" : "BEFORE the GPU was done (counts may be short)", gb_first, gb_last,
                  light_first);
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100c): %u draws in the last frame (%u over the cap of %u), %u probed in %u "
                  "frames; not probed: %u lamps apart, %u not scene-sized, %u unreadable, %u left out, %u menu "
                  "preview, %u no view; %zu pairs changed the box",
                  u32(infos[last_frame].size()) + over_cap[last_frame], over_cap[last_frame], R::MaxDraws,
                  probed, frames, skipped[LampsApart], skipped[NotScene], skipped[Unreadable], skipped[LeftOut],
                  skipped[Preview], skipped[NoView], order.size());
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100c): last writer of each box pixel (a G-buffer albedo, s scene colour by "
                  "draws over 6 indices, z depth): a %u px by %u pairs, s %u by %u, z %u by %u; none: a %u, s %u, "
                  "z %u",
                  owned[0], owner_pairs[0], owned[1], owner_pairs[1], owned[2], owner_pairs[2], box_px - owned[0],
                  box_px - owned[1], box_px - owned[2]);
    BbReport::Printf("%s\n", line);
    BbReport::Printf("Blood pool probe (r100c): pair lines by own, then box: box px changed a frame, own = last writer, "
                     "frame~ px changed a frame, n draws a frame, p probed, #first-last draw in the last frame, "
                     "P pre-G-buffer G G-buffer B pre-light L light A after; cb:format/role+b blend=box px\n");
    static constexpr const char* PhaseLetters = "PGBLA";
    const u32 shown = std::min<u32>(u32(order.size()), R::MaxLines);
    u64 rest_px = 0;
    for (u32 rank = 0; rank < order.size(); ++rank) {
        const Sum& s = sums[order[rank]];
        if (rank >= shown) {
            rest_px += s.box;
            continue;
        }
        char phases[8] = {};
        for (u32 b = 0, n = 0; b < 5; ++b) {
            if ((s.phases >> b) & 1u) {
                phases[n++] = PhaseLetters[b];
            }
        }
        char idx[40];
        if (s.idx_max == 0 && s.indirect) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (s.idx_min == s.idx_max) {
            std::snprintf(idx, sizeof(idx), "%u%s", s.idx_max, s.indirect ? "+ind" : "");
        } else {
            std::snprintf(idx, sizeof(idx), "%u-%u%s", s.idx_min, s.idx_max, s.indirect ? "+ind" : "");
        }
        if (s.inst_max > 1) {
            const std::size_t used = std::strlen(idx);
            std::snprintf(idx + used, sizeof(idx) - used, "x%u", s.inst_max);
        }
        // The representative draw's targets: cb:format/role, +b blending, m<mask> a partial write
        // mask, =box pixels a frame where that target changed; then the depth.
        std::string targets;
        const DrawInfo& d = *s.rep;
        for (u32 cb = 0; cb < 8; ++cb) {
            if (((d.mrt >> cb) & 1u) == 0 || d.format[cb] == 0) {
                continue;
            }
            const char* name = ColourName(vk::Format(d.format[cb]));
            const u32 mask = (d.write_masks >> (4 * cb)) & 15u;
            char part[48];
            std::snprintf(part, sizeof(part), " %u:%s%s%s%s", cb, name ? name : "int",
                          d.role[cb] ? "/" : "", RoleNames[d.role[cb]], (d.blend >> cb) & 1u ? "+b" : "");
            targets += part;
            if (mask != 15u) {
                std::snprintf(part, sizeof(part), "m%x", mask);
                targets += part;
            }
            std::snprintf(part, sizeof(part), "=%llu", static_cast<unsigned long long>(s.by_target[cb] / frames));
            targets += part;
        }
        {
            char part[48];
            if (d.depth_test) {
                std::snprintf(part, sizeof(part), " d:%s %s%s=%llu", DepthName(vk::Format(d.depth_format)),
                              FuncNames[d.depth_func], d.depth_write ? " w" : "",
                              static_cast<unsigned long long>(s.by_target[R::DepthTarget] / frames));
            } else {
                std::snprintf(part, sizeof(part), " d:-");
            }
            targets += part;
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100c): %u/%zu %08llx:%08llx box %llu/f max %u own a%u s%u z%u "
                      "frame~%llu n%u/f p%u%s idx %s #%d-%d %s |%s",
                      rank + 1, order.size(), static_cast<unsigned long long>(s.vs),
                      static_cast<unsigned long long>(s.ps), static_cast<unsigned long long>(s.box / frames),
                      s.box_max, s.own[0], s.own[1], s.own[2],
                      static_cast<unsigned long long>(s.frame * R::Stride * R::Stride / frames), s.draws / frames,
                      s.probed, s.rep_changed ? "" : " (none)", idx, s.first, s.last, phases,
                      targets.c_str());
        BbReport::Printf("%s\n", line);
    }
    if (order.size() > shown) {
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100c): %zu more pairs changed the box (%llu px a frame together), not "
                      "listed",
                      order.size() - shown, static_cast<unsigned long long>(rest_px / frames));
        BbReport::Printf("%s\n", line);
    }
}

// bbport (r100c_blood-pool-probe, TOOL): the probe's before-draw hook (direct and indirect draws).
void Rasterizer::BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light) {
    static_assert(AmdGpu::NUM_COLOR_BUFFERS == 8);
    std::array<VideoCore::ImageId, 8> targets{};
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        targets[cb] = cb_descs[cb].first;
    }
    blood_pool_probe->BeforeDraw(Regs(), *pipeline, targets, db_desc.first, light, point_shadow->Pending(),
                                 indirect);
}

} // namespace Vulkan
'''


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def need(path, text, want, k=1):
    if text.count(want) != k:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), k))


def in_order(path, text, *parts):
    """Each part is found after the one before it (searching on from there)."""
    at = text.find(parts[0])
    for p in parts[1:]:
        at = text.find(p, at + 1) if at >= 0 else -1
    if at < 0:
        raise SystemExit("text check: %s does not hold these in this order: %r" % (path, [q[:60] for q in parts]))


# Text checks on the result: the ties a compiler cannot check, and the names the new code uses.
def text_checks(t):
    probe, probe_h, rules = t[RV + "vk_blood_pool_probe.cpp"], t[RV + "vk_blood_pool_probe.h"], t[RV + "blood_pool_probe.h"]
    comp, layout = t[HS + "blood_pool_probe.comp"], t[HS + "blood_pool_probe_layout.h"]
    # the tree's names the hooks and the probe use
    need(E, t[E], "u64 FragmentHash(const GraphicsPipeline* pipeline) {")
    need(E, t[E], "constexpr u32 PointLightCount(u64 hash) {")
    need(E, t[E], "constexpr u64 ShadowResolveHash = ")
    need("vk_shader_util.h", load(RV + "vk_shader_util.h")[2], "inline constexpr u64 DirectionalFragmentShaderHash = ")
    need(H, t[H], "    std::array<RenderTargetInfo, AmdGpu::NUM_COLOR_BUFFERS> cb_descs;\n")
    need(H, t[H], "    std::pair<VideoCore::ImageId, VideoCore::TextureCache::ImageDesc> db_desc;\n")
    need(H, t[H], "    std::unique_ptr<PointShadow> point_shadow;\n")
    need(H, t[H], "    const AmdGpu::Regs& Regs() const;\n")
    knobs = load("engine/gpu/shim/bbport_live_knobs.h")[2]
    for want in ("inline std::uint32_t Generation() noexcept {", "inline Text Lookup(const char* name) noexcept {",
                 "    bool in_file = false;", "    [[nodiscard]] const char* Get() const noexcept {"):
        need("bbport_live_knobs.h", knobs, want)
    need("bbport_toggles.h", load("engine/gpu/shim/bbport_toggles.h")[2], "inline void Printf(const char* format, ...) {")
    need("vk_point_shadow.h", load(RV + "vk_point_shadow.h")[2], "    [[nodiscard]] bool Pending() const noexcept {")
    sheen = load(RV + "vk_blood_sheen.cpp")[2]
    for want in ("scene_targets.Read(id, info, Compute, access)", "EffectPass::HasRoom(instance, ",
                 "camera_motion.RenderSize()", "camera_motion.PreviewFrame()", "const SceneUseScope scene_use{"):
        if want not in sheen:
            raise SystemExit("text check: vk_blood_sheen.cpp (the model) no longer uses %r" % want)
    # CMake: new .cpp files are globbed; the include rule and the two builds once, the rule before the command
    need(M, t[M], "file(GLOB_RECURSE VIDEO_CORE CONFIGURE_DEPENDS shadps4/video_core/*.cpp)")
    need(M, t[M], "if (FILENAME MATCHES \"^blood_pool_probe\")")
    need(M, t[M], "add_host_shader(blood_pool_probe.comp ", 2)
    in_order(M, t[M], "function(add_host_shader FILENAME SHADER_NAME)", "if (FILENAME MATCHES \"^blood_pool_probe\")",
             "    add_custom_command(OUTPUT ${OUT}\n", "endfunction()",
             "add_host_shader(blood_pool_probe.comp blood_pool_probe_snapshot_comp POOL_SNAPSHOT=1)")
    # the shader's defines are the ones its builds give, the C++ symbols the ones they make
    for d in ("POOL_SNAPSHOT", "POOL_COMPARE"):
        need(M, t[M], " %s=1)" % d)
        need("blood_pool_probe.comp", comp, "defined(%s)" % d, 3 if d == "POOL_SNAPSHOT" else 4)
    for sym in ("BLOOD_POOL_PROBE_SNAPSHOT_COMP", "BLOOD_POOL_PROBE_COMPARE_COMP"):
        need("vk_blood_pool_probe.cpp", probe, sym + ",")
        need("vk_blood_pool_probe.cpp", probe, '#include "video_core/host_shaders/%s.h"' % sym.lower())
    need("blood_pool_probe.comp", comp, '#include "blood_pool_probe_layout.h"')
    need("blood_pool_probe.h", rules, '#include "../host_shaders/blood_pool_probe_layout.h"')
    # every #define of the layout is tied in blood_pool_probe.h
    for line in layout.split("\n"):
        if line.startswith("#define BLOOD_POOL_PROBE_") and not line.startswith("#define BLOOD_POOL_PROBE_LAYOUT_H"):
            name = line.split()[1]
            if name not in rules:
                raise SystemExit("text check: %s of the layout is not used in blood_pool_probe.h" % name)
    # the hooks, each in its function, the direct before hook before r100's
    in_order(E, t[E], "void Rasterizer::EffectsBeforeResources(", "BloodPoolProbeBefore(pipeline, false,",
             "    if (blood_sheen) {\n        std::array<VideoCore::ImageId, AmdGpu::NUM_COLOR_BUFFERS> sheen_targets{};")
    in_order(E, t[E], "void Rasterizer::EffectsAfterDraw(", "blood_pool_probe->AfterDraw();",
             "blood_sheen->AfterDraw();")
    in_order(E, t[E], "void Rasterizer::EffectsOnFrameEnd() {", "blood_pool_probe->OnFrameEnd();", "WindOnFrameEnd();")
    in_order(C, t[C], "void Rasterizer::DrawIndirectRecord(", "    PrepareRenderState(pipeline);\n",
             "BloodPoolProbeBefore(pipeline, true, false);", "    if (!BindResources(pipeline)) {",
             "cmdbuf.drawIndirect(args, args_offset, max_count, stride);", "blood_pool_probe->AfterDraw();",
             "void Rasterizer::DispatchDirect() {")
    in_order(C, t[C], "    point_shadow = std::make_unique<PointShadow>(", "blood_pool_probe = std::make_unique<BloodPoolProbe>(",
             "    sky_seam = std::make_unique<SkySeam>(instance, scheduler);")
    need(C, t[C], "    EffectsBeforeResources(pipeline);\n")
    need(probe, probe, "void Rasterizer::BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light) {")
    need(H, t[H], "    void BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light);\n")
    # the member is declared after the objects the probe holds references to (destroyed before them)
    in_order(H, t[H], "    Scheduler& scheduler;", "    Runtime& runtime;", "    VideoCore::TextureCache texture_cache;",
             "    std::unique_ptr<CameraMotion> camera_motion;", "    std::unique_ptr<SceneTargets> scene_targets;",
             "    std::unique_ptr<BloodPoolProbe> blood_pool_probe;")
    # every log line carries "Blood pool probe (r100c" and fits 280 characters as a format
    for i, part in enumerate(probe.split("Printf(")[1:]):
        if "Blood pool probe (r100c" not in part[:120] and '"%s\\n", line' not in part[:20]:
            raise SystemExit("text check: Printf %d of the probe has no \"Blood pool probe (r100c\" tag" % (i + 1))
    if "char line[280];" not in probe or probe.count("std::snprintf(line, sizeof(line),") != 5:
        raise SystemExit("text check: the long lines are not all built in char line[280]")
    added = list(NEW.values()) + [x for eds in EDITS.values() for e in eds for x in e[1:]]
    if any(ord(ch) > 127 for text in added for ch in text):
        raise SystemExit("text check: a new file or an inserted text is not plain ASCII")


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [x for x in (before, after) if x]
        na, counts = cur.count(anchor), [cur.count(x) for x in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_state(path, eol):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    if open(full, "rb").read() == NEW[path].replace("\n", eol).encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s exists with other content" % path)


def write(path, data):
    full = os.path.join(ROOT, path)
    tmp = full + ".r100ctmp"
    open(tmp, "wb").write(data)
    os.replace(tmp, full)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r100c_blood-pool-probe.py check | apply | revert")
        sys.exit(2)
    cmd = sys.argv[1]
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R100C_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    new_eol = [p[3] for p in plan if p[0] == C][0]
    news = {path: new_state(path, new_eol) for path in NEW}
    states = {p[5] for p in plan} | set(news.values())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % kv for kv in news.items()))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update(NEW)
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update(NEW)
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            write(path, texts[path].replace("\n", eol).encode("utf-8"))
        for path in NEW:
            write(path, NEW[path].replace("\n", new_eol).encode("utf-8"))
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        write(path, out[path])
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
