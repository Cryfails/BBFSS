# r54_leaf-stage2: stage 2 of the ray traced foliage shadows, the card UVs. A DRAFT: not built in
# the tree, not run in the game. Off by default: BB_RT_CARD_ALPHA=1 (read once) turns it on. With
# it on, the position capture of a cut-out entry also stores per vertex the coordinates its pixel
# shader samples the alpha at and the alpha factor it multiplies in, and a compute pass turns
# them into one 16-byte record a BLAS primitive in a pool. Nothing reads the pool yet: no ray,
# mask, TLAS, BLAS or picture changes. (engine/docs/rt_card_alpha.md says what and why.)
#
# The gate is passed: the r50c game log of 2026-11-15 (BB_RT_CARD_ALPHA_LOG=1, 100 s, the plant
# spot and a character) met the GO numbers: 11 of 11 discarding pixel shaders repeatable with the
# draw's constants; with constants plants 4 of 4, hair/cloth (kept whole, a skeleton) 5 of 5,
# static 2 of 2; 769,976 draws, 100 % CPU-written (0 in place, 0 GPU-written, 0 unreadable, 0
# another permutation); every dither 4x4; references cb[20] + 0.5 * cb[21] 0.0392153 to 0.892156
# (camera pass) and 0.196078 (sun shadow pass); dbeccd9c, 1c3953c6 and 92852ef3 checked by hand;
# 0 "(r50" lines with the knob unset.
# r50c's rule and this patch: a ray keeps A >= cb[20] + 0.5 * cb[21] and (the record's nonzero
# term) A != 0; the per-instance fade is left out, so an instance with fade 0 still casts its
# shadow. This patch reads no ignored factor (RepeatableWithConstants() decides) and reads no fade.
# The camera pass's dither coefficient (-cb[21]) is carried apart (CardDraw::dither_scale), not
# in the reference. An entry drawn by both passes takes the sun shadow pass's card (the game's own
# shadow test) while that pass still gives one: a stale sun card, or one no sun shadow pass draw
# gave for more than 17 frames (r14's longest cascade hold), gives way to the camera pass's card.
# The log prints both references once. The alpha factor's 8-bit storage: within 2^-14 of a step
# of k / 255 it is stored as k / 255 (not exact: a few ulps); farther off, or outside [0, 1], it
# is marked and counted (rt_card_uv_layout.h, CARD_UV_TRI_ALPHA_*).
# check|apply|revert (revert restores byte for byte and removes the new files). On top of r50b,
# r57, r50c (r50c_leaf-fade.py), r60 and r53 as <tree> has them, 2026-11-15. The tree: the one
# the environment variable R54_ROOT names; without it the current directory when that is the root
# of a source tree, else <tree>/. Nothing is changed in place: every new text is written
# beside its target and moved over it, and a failure puts back what was already moved and
# removes what was already made. Files keep their line ends (all CRLF); new files are CRLF.
#
# WHAT (file by file):
#  shader_recompiler/runtime_info.h: MotionVectors::CaptureUv (4), CaptureUvStride (12),
#     Kind() (the motion kind, CaptureUv apart).
#  backend/spirv/emit_spirv_special.cpp: equality tests through Kind(); EmitCardUvStore: inside
#     the capture's in-range branch, after the position store, when param word 1 is not 0: u, v
#     and the alpha factor (word 7 says which outputs) stored at ring + (word 1 - 1 + slot) * 12;
#     a value word 7 names but the shader cannot give is stored as NaN (CaptureUvUnset).
#  backend/spirv/spirv_emit_context.cpp: the address block takes the ring's address as its last
#     member with CaptureUv (24 or 40 bytes); without it the block is as before.
#  ir/passes/cutout_analysis.h, cutout_analysis_pass.cpp: CutoutLogOn() (BB_RT_CARD_ALPHA_LOG=1)
#     and CardAlphaOn() (BB_RT_CARD_ALPHA=1, Vulkan::ReadCardAlpha); CutoutAnalysisOn() is either,
#     so the records are made for the card UVs too; r50's, r50b's and r50c's log lines take
#     CutoutLogOn().
#  renderer_vulkan/vk_pipeline_cache.cpp: CaptureUv in the capture's runtime info and key when the
#     knob is on; CompileModule never lifts a vertex shader with CaptureUv (the lifter, on by
#     default, has its own capture without the UV store: its module would leave the ring
#     unwritten). vk_pipeline_serialization.cpp: the warm-up builds no capture key of the other
#     knob setting (no draw asks for it; one with CaptureUv would read past a 16/32-byte block).
#  renderer_vulkan/vk_rasterizer_effects.cpp: Kind() in the two motion param tests;
#     ResolveCardDraw: a cut-out draw's card data (r50b's record as r50c classes it, the draw's
#     input controls, its
#     dwords read on the CPU with r50b's guard, the alpha texture's T#, the sampler's repeat) into
#     RtShadow::Draw::card, only on a CaptureUv pipeline; r50b's draw-time line takes CutoutLogOn().
#  renderer_vulkan/vk_rt_shadow.h/.cpp: Draw::card, Entry::card_uv, Build::uv_base/uv_hash/
#     uv_only; the ring (24 MiB, at setup; filled with NaN by the first RecordBuilds and its used
#     part again after each expand pass), the pool (64 MiB, at the first card; VMA virtual
#     blocks; the coordinates times the scale, the offset left to the reader), the stat slots;
#     CardNoteDraw (at every cut-out draw, beside r50's bookkeeping), CardCapture (the build path
#     and the r47 probe path), CardUvProbe (a capture for the UVs alone after 8 frames, also on a
#     second draw of a frame; every check before its param, within half the frame's params and
#     positions), the expand dispatch and the ring fill in the ray tracing geometry pass (after
#     the still signatures, before the unprojection), CardRelease (Destroy: freed after the
#     tick), CardFrameEnd, CardLog (the 600-frame lines). Kind() in BindAddresses and
#     CaptureLeftOut; CaptureLeftOut drops the UVs of a capture left out, and a UV-only probe
#     left out leaves r47's look state alone. r50's bookkeeping takes CutoutLogOn().
#  host_shaders/rt_card_uv.comp, rt_card_uv_layout.h (new): the expand pass and its layout.
#  renderer_vulkan/rt_card_uv.h (new): the pure parts. tests/test_rt_card_uv.cpp (new) tests them.
#  engine/gpu/CMakeLists.txt: the shader (with its include), the rt-card-uv-test target.
#  engine/build.sh: rt-card-uv-test in --test. engine/docs/rt_card_alpha.md (new): the knobs.
# KNOB OFF: no CaptureUv anywhere: keys, SPIR-V, address blocks (16 and 32 bytes) and cache
# records as before; no buffer made, no dispatch recorded; Draw::card stays null and
# Entry::card_uv empty (8 bytes each). The draw path costs one bit test of the pipeline key.
# KNOB ON: per cut-out draw on the render thread, ResolveCardDraw (a FindCutout lookup under its
# mutex for a cached program, at most seven guarded dword reads (the dither's coefficient is the
# seventh, camera pass draws that dither only), a T# and a sampler fetch, two hashes over 25
# words) and CardNoteDraw; per UV capture two param words; per RecordBuilds call
# with UV captures one more pass and a fill of the ring part used. Allocation: the entry's part
# once per cut-out entry, the job's push list once per call that has UV captures (as the job's
# other lists); nothing per frame. Every capture vertex shader (all ray traced casters, not only
# cut-outs) is then compiled by the recompiler, not the lifter, and compiles in play once (new
# keys): the cost of that is not measured.
# LOG (all tagged "(r54"): at start "Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=1, ..." (or why
# off); once per entry drawn by both passes (the first 32) "drawn by both passes, ..." with both
# references; every 600 frames the counts line and up to four "first entries" lines.
# NOT CHANGED: anything a ray, a pass or a picture uses; point_shadow_ray.comp,
# lamp_shadow_tune.h, vk_point_shadow.h/.cpp, test_lamp_shadow_tune.cpp, test_rt_shadows.cpp,
# docs/renderer-performance-0.9.43.md (r57's), the drawn look's and the volumetric/fog files.
# NOT DONE: nothing reads the pool (stage 3: alpha layers, card table, debug view; 4: lamp rays;
# 4b: lamp card map decision; 5: characters, hair, cloth; 6: sun and bounce; 7: cost levers); no
# CUT1 cache tag (the knob makes discarding pixel shaders compile in play, as r50's does).
# TEST: BB_RT_CARD_ALPHA=1 and BB_RT_CARD_ALPHA_LOG=1, ray tracing on, the r46b plant spot and a
# character, 30-100 s: the "(r54" lines against the list in rt_card_alpha.md ("What the log must
# show"); the picture as with the knob unset; a run with both unset prints no "(r54" line.

import os
import sys

ROOT = os.environ.get("R54_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/shader_recompiler/recompiler.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
SR = G + "shadps4/shader_recompiler/"
SP = SR + "backend/spirv/"
P = SR + "ir/passes/"
R = G + "shadps4/video_core/renderer_vulkan/"
H = G + "shadps4/video_core/host_shaders/"
TESTS = E + "tests/"
DOCS = E + "docs/"

TMP = ".r54tmp"  # a new text waits under this name beside its target (main)

# r57's files (being applied to the tree), the drawn look's and the volumetric/fog files: this
# one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "renderer-performance-0.9.43.md")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or \
        "volumetric" in name or "fog" in name


# New files: (path, text with LF line ends; written with CRLF).
NEW = {
    H + "rt_card_uv_layout.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r54_leaf-stage2): the layout the card UV pass (rt_card_uv.comp) shares with the engine
// (renderer_vulkan/rt_card_uv.h, RtShadow::RecordBuilds). Plain #define lines only: the shader
// includes this file through GL_GOOGLE_include_directive and C++ includes it as it is, so one
// text says where every field lies for both. Stage 3 and later read the pool records with it.
#ifndef RT_CARD_UV_LAYOUT_H
#define RT_CARD_UV_LAYOUT_H

// Threads a group: one triangle each.
#define CARD_UV_GROUP 64

// The capture ring: per captured vertex three floats (u, v and the alpha factor, 1.0 when the
// pixel shader has none), 12 bytes, at ring[(capture param word 1 - 1 + vertex slot) * 3].
#define CARD_UV_RING_FLOATS 3
#define CARD_UV_RING_BYTES 12
// What the ring holds where no capture stored (a quiet NaN's bits): RecordBuilds fills the used
// part with it after each expand pass (and all of it once, before the first UV capture), and the
// capture stores it for a value its selector cannot name. The expand pass then marks the
// triangle not finite (CARD_UV_TRI_NOT_FINITE) instead of keeping an old or a zero value.
#define CARD_UV_RING_UNSET 0x7fc00000u

// The pool: one record of 16 bytes (a uvec4) a BLAS primitive, primitive p of an entry at
// pool[entry offset + p]. Words 0, 1, 2: packHalf2x16(u, v) of corners 0, 1, 2: the input
// coordinates times the draw's scale, minus the shift. The draw's offset is NOT in the pool: its
// reader adds the entry's card offset (CardDraw::affine[2], [3]; for a wrapping axis it may take
// it modulo 1, for a mirrored one modulo 2), so a moving offset (scrolling UVs) keeps the records.
// Word 3: corner alphas as unorm8 in bits 0-7, 8-15, 16-23, the flags below in bits 24-31.
#define CARD_UV_RECORD_BYTES 16
#define CARD_UV_RECORD_WORDS 4
#define CARD_UV_FLAGS_SHIFT 24
// A corner's coordinate is 4.0 or more away from 0 after the shift: half precision there is
// 2^-8 or coarser, so the triangle is marked (not dropped).
#define CARD_UV_TRI_WIDE 1
// The pixel shader multiplies no alpha factor in: the alphas are 255.
#define CARD_UV_TRI_NO_ALPHA 2
// A corner's coordinate is not a finite number, or its alpha factor not a number (a vertex no
// capture stored reads as CARD_UV_RING_UNSET): the triangle is not shifted.
#define CARD_UV_TRI_NOT_FINITE 4
// The alpha factor in 8 bits (r54 review points R7, R7-a, R7-b). The game's A is texel alpha
// times the interpolated factor; a ray's will be texel alpha times the interpolation of the
// stored k / 255. CARD_UV_ALPHA_GRID_EPS is the tolerance, in 8-bit steps: 2^-14 of a step
// (2.4e-7 in alpha; a few float ulps, which k / 255 computed in another order of operations
// stays within). A factor that far or nearer to k / 255 at every corner is not marked and is
// stored as k / 255: a ray then keeps and drops what the game does, except for an A within
// texel alpha * 2.4e-7 of the reference (and float rounding of the interpolation, which a ray
// and the raster may do differently). It is not "exact". Otherwise:
// A corner's factor is below 0 or above 1 by more than the tolerance (2.4e-7): the stored value
// is clamped, a ray's A can be far from the game's. A reader takes the triangle as one without
// card data (as CARD_UV_TRI_NOT_FINITE). A factor 1 + 1 ulp or -1e-9 is not marked: the clamp
// there moves it by less than the tolerance.
#define CARD_UV_TRI_ALPHA_RANGE 8
// A corner's factor is in [0, 1] but more than the tolerance away from k / 255: rounded by at
// most half a step (0.5 / 255), so a ray's A differs from the game's by at most texel alpha *
// 0.5 / 255. A texel whose A lies that close to the reference can fall on the other side
// (examples in test_rt_card_uv.cpp). Kept and counted; a later stage decides (a wider alpha needs
// a larger record).
#define CARD_UV_TRI_ALPHA_ROUNDED 16
#define CARD_UV_ALPHA_GRID_EPS 0.00006103515625
#define CARD_UV_SPAN_LIMIT 4.0

// How an axis repeats (the sampler's clamp mode): wrap shifts by floor(min), mirror by an even
// number, clamp not at all.
#define CARD_UV_MODE_WRAP 0
#define CARD_UV_MODE_MIRROR 1
#define CARD_UV_MODE_CLAMP 2

// Push constants (48 bytes): u64 indices at 0 (the entry's triangle list, buffer reference),
// uint ring_base at 8 (the capture's first ring vertex), uint triangles at 12, uint
// pool_offset at 16 (records), uint flags at 20, two unused words, vec4 affine at 32 (scale u,
// scale v, offset u, offset v: coordinate = input * scale + offset; RecordBuilds passes the
// offset as 0, see the pool above).
#define CARD_UV_PUSH_BYTES 48
#define CARD_UV_PUSH_RING_BASE 8
#define CARD_UV_PUSH_TRIANGLES 12
#define CARD_UV_PUSH_POOL_OFFSET 16
#define CARD_UV_PUSH_FLAGS 20
#define CARD_UV_PUSH_AFFINE 32
// flags: the u axis's mode in bits 0-1, v's in bits 2-3, an alpha factor in bit 4, the stat
// slot + 1 in bits 8-10 (0: none).
#define CARD_UV_PUSH_MODE_V_SHIFT 2
#define CARD_UV_PUSH_HAS_ALPHA 16
#define CARD_UV_PUSH_STAT_SHIFT 8

// The stat slots (the first entries expanded after each 600-frame line): 10 words each. Words
// 0-2 the least u, v, alpha of the corners after the scale, before the shift, as inverted keys
// (atomicMax of ~Key), words 3-5 the greatest as keys, word 6 the triangles marked wide, word 7
// those marked not finite, word 8 those marked CARD_UV_TRI_ALPHA_RANGE, word 9 those marked
// CARD_UV_TRI_ALPHA_ROUNDED. Words 0-5 take atomicMax, 6-9 atomicAdd. Each workgroup gathers its
// own in shared memory first (no subgroup operation is needed).
#define CARD_UV_STAT_SLOTS 4
#define CARD_UV_STAT_WORDS 10
#define CARD_UV_STAT_MAX_WORDS 6

#endif
""",
    H + "rt_card_uv.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r54_leaf-stage2): the card UVs of one captured entry into its block of the pool
// (RtShadow::RecordBuilds, BB_RT_CARD_ALPHA=1 only). One invocation a BLAS primitive: the
// capture stored per vertex (u, v, alpha factor) in the ring as the vertex shader output them;
// here the three corners of the primitive's triangle (the entry's triangle list, in the order
// the BLAS is built from) get the draw's coordinate scale (RecordBuilds passes the offset as 0:
// the pool leaves it to its reader), a shift by whole repeats so they stay small, and are packed
// into the 16-byte record rt_card_uv_layout.h describes (renderer_vulkan/rt_card_uv.h,
// CardPackTriangle, is this on the CPU and its tests). Nothing reads the pool yet: stage 3 adds
// the alpha test of a ray.
// Only the vertices the triangles use were written by the capture, so nothing walks the ring's
// range of the entry as a whole (rt_still_sig.comp says the same of the positions). A vertex no
// capture stored holds CARD_UV_RING_UNSET (a NaN): its triangles are marked not finite.

#version 460
#extension GL_EXT_buffer_reference : require
#extension GL_GOOGLE_include_directive : require

#include "rt_card_uv_layout.h"

layout(local_size_x = CARD_UV_GROUP) in;

layout(buffer_reference, std430, buffer_reference_align = 4) readonly buffer Indices { uint i[]; };

layout(std430, set = 0, binding = 0) readonly buffer Ring { float r[]; } ring;
layout(std430, set = 0, binding = 1) writeonly buffer Pool { uvec4 p[]; } pool;
layout(std430, set = 0, binding = 2) buffer Stats { uint s[]; } stats;

layout(push_constant) uniform Constants {
    Indices indices;  // the entry's triangle list (vertex slots), at 0
    uint ring_base;   // the capture's first ring vertex, at 8
    uint triangles;   // at 12
    uint pool_offset; // the entry's first record, at 16
    uint flags;       // modes, alpha, stat slot, at 20
    uint unused0;
    uint unused1;
    vec4 affine;      // scale u, scale v, offset u, offset v (0 from RecordBuilds), at 32
};

// The stat slot of this workgroup's triangles, gathered here first (CARD_UV_STAT_WORDS words, as
// the slot in `stats`): one global atomic a word a workgroup, no subgroup operation.
shared uint group_stat[CARD_UV_STAT_WORDS];

bool Finite(float v) {
    return (floatBitsToUint(v) & 0x7f800000u) != 0x7f800000u;
}

// Not a number, by its bits (CARD_UV_RING_UNSET is one).
bool NotANumber(float v) {
    return (floatBitsToUint(v) & 0x7fffffffu) > 0x7f800000u;
}

// CardShift: wrap by floor of the least corner, mirror by an even number, clamp not at all.
float Shift(float c0, float c1, float c2, uint mode) {
    const float least = min(c0, min(c1, c2));
    if (mode == CARD_UV_MODE_WRAP) {
        return floor(least);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        return 2.0 * floor(least * 0.5);
    }
    return 0.0;
}

// CardUnorm8: floor(clamp(a, 0, 1) * 255 + 0.5), not a number 0 (clamp of NaN is undefined).
uint Unorm8(float a) {
    if (NotANumber(a)) {
        return 0u;
    }
    return uint(clamp(a, 0.0, 1.0) * 255.0 + 0.5);
}

// CardAlphaMarks: an alpha factor outside [0, 1] by more than the tolerance
// (CARD_UV_TRI_ALPHA_RANGE), or more than CARD_UV_ALPHA_GRID_EPS of a step away from k / 255
// (CARD_UV_TRI_ALPHA_ROUNDED); 0 when unorm8 holds k / 255 and the factor is that close to it.
// Only for a number (the caller tests NotANumber first).
uint AlphaMarks(float a) {
    const float range_tolerance = float(CARD_UV_ALPHA_GRID_EPS) / 255.0;
    if (a < -range_tolerance || a > 1.0 + range_tolerance) {
        return CARD_UV_TRI_ALPHA_RANGE;
    }
    const float steps = a * 255.0;
    return abs(steps - floor(steps + 0.5)) <= CARD_UV_ALPHA_GRID_EPS ? 0u : CARD_UV_TRI_ALPHA_ROUNDED;
}

// A float as an unsigned number of the same order (CardStatKey).
uint Key(float v) {
    const uint bits = floatBitsToUint(v);
    return (bits & 0x80000000u) != 0u ? ~bits : (bits | 0x80000000u);
}

void main() {
    const uint t = gl_GlobalInvocationID.x;
    const uint stat = (flags >> CARD_UV_PUSH_STAT_SHIFT) & 7u;
    if (stat != 0u && gl_LocalInvocationIndex < CARD_UV_STAT_WORDS) {
        group_stat[gl_LocalInvocationIndex] = 0u;
    }
    const bool live = t < triangles;
    const bool has_alpha = (flags & CARD_UV_PUSH_HAS_ALPHA) != 0u;
    bool finite = true;
    uint marks = has_alpha ? 0u : CARD_UV_TRI_NO_ALPHA;
    // The stat slot's bounds are of the corners after the scale, before the shift: what the
    // 600-frame line compares with the texture's repeat.
    vec3 lo = vec3(0.0);
    vec3 hi = vec3(0.0);
    if (live) {
        const uint mode_u = flags & 3u;
        const uint mode_v = (flags >> CARD_UV_PUSH_MODE_V_SHIFT) & 3u;
        vec2 c[3];
        float a[3];
        for (uint k = 0u; k < 3u; ++k) {
            const uint at = (ring_base + indices.i[t * 3u + k]) * CARD_UV_RING_FLOATS;
            c[k] = vec2(ring.r[at], ring.r[at + 1u]) * affine.xy + affine.zw;
            a[k] = has_alpha ? ring.r[at + 2u] : 1.0;
            finite = finite && Finite(c[k].x) && Finite(c[k].y) && !NotANumber(a[k]);
        }
        if (finite) {
            lo = vec3(min(c[0], min(c[1], c[2])), min(a[0], min(a[1], a[2])));
            hi = vec3(max(c[0], max(c[1], c[2])), max(a[0], max(a[1], a[2])));
            const vec2 shift = vec2(Shift(c[0].x, c[1].x, c[2].x, mode_u),
                                    Shift(c[0].y, c[1].y, c[2].y, mode_v));
            for (uint k = 0u; k < 3u; ++k) {
                c[k] -= shift;
                if (any(greaterThanEqual(abs(c[k]), vec2(CARD_UV_SPAN_LIMIT)))) {
                    marks |= CARD_UV_TRI_WIDE;
                }
                if (has_alpha) {
                    marks |= AlphaMarks(a[k]);
                }
            }
        } else {
            marks |= CARD_UV_TRI_NOT_FINITE;
        }
        uvec4 record;
        record.x = packHalf2x16(c[0]);
        record.y = packHalf2x16(c[1]);
        record.z = packHalf2x16(c[2]);
        record.w = (has_alpha ? (Unorm8(a[0]) | (Unorm8(a[1]) << 8) | (Unorm8(a[2]) << 16))
                              : 0xffffffu) |
                   (marks << CARD_UV_FLAGS_SHIFT);
        pool.p[pool_offset + t] = record;
    }

    if (stat == 0u) {
        return; // the same for the whole dispatch (a push constant): barrier() stays uniform
    }
    barrier(); // the group's words are zeroed
    // 0 is below every key, so a triangle that is not finite leaves the bounds as they are.
    if (live) {
        if (finite) {
            atomicMax(group_stat[0], ~Key(lo.x));
            atomicMax(group_stat[1], ~Key(lo.y));
            atomicMax(group_stat[2], ~Key(lo.z));
            atomicMax(group_stat[3], Key(hi.x));
            atomicMax(group_stat[4], Key(hi.y));
            atomicMax(group_stat[5], Key(hi.z));
        } else {
            atomicAdd(group_stat[7], 1u);
        }
        if ((marks & CARD_UV_TRI_WIDE) != 0u) {
            atomicAdd(group_stat[6], 1u);
        }
        if ((marks & CARD_UV_TRI_ALPHA_RANGE) != 0u) {
            atomicAdd(group_stat[8], 1u);
        }
        if ((marks & CARD_UV_TRI_ALPHA_ROUNDED) != 0u) {
            atomicAdd(group_stat[9], 1u);
        }
    }
    barrier(); // the group's words are complete
    const uint w = gl_LocalInvocationIndex;
    if (w < CARD_UV_STAT_WORDS) {
        const uint value = group_stat[w];
        const uint at = (stat - 1u) * CARD_UV_STAT_WORDS + w;
        if (value != 0u) {
            if (w < CARD_UV_STAT_MAX_WORDS) {
                atomicMax(stats.s[at], value);
            } else {
                atomicAdd(stats.s[at], value);
            }
        }
    }
}
""",
    R + "rt_card_uv.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r54_leaf-stage2): stage 2 of the ray traced foliage shadows, the pure parts. No Vulkan
// here: tests/test_rt_card_uv.cpp builds this header alone and runs the code the engine runs.
//
// Stage 1 (r50, r50b: shader_recompiler/ir/passes/cutout_analysis.h) reads from a cut-out pixel
// shader's IR its alpha test: which texture channel, times which input's component (a vertex
// colour's alpha), is compared with which reference, at which coordinates. The game's test
// (decompiled in the stage 1 run, ten of eleven cut-out shaders):
//   camera pass: discard where cb[20] > cb[21] * (dither - 0.5) + A, or A * fade == 0,
//   sun shadow pass: the same with the dither left out (cb[21] * -0.5),
//   A = texel.w * vertex colour.w, texel at uv * cb'[0, 1] + cb'[2, 3].
// A ray repeats the sun shadow pass form: kept where A >= cb[20] + 0.5 * cb[21] and A != 0.
// The per-instance fade is left out (r50c's rule; the sun shadow pass has none), so an instance
// the game hides with fade 0 still casts its shadow. Where an entry is drawn by both passes, its
// card is the sun shadow pass's (CardTakes: that pass is the game's own shadow test) while that
// pass still gives one: a stale sun card, or one no sun shadow pass draw gave for more than
// CardSunFrames frames, gives way to the camera pass's.
// Which buffer and which dwords hold these, whether a vertex alpha is there and where the scale
// and offset come from is what the record says (data, not code here): nothing below knows 20,
// 21 or 0-3.
//
// Stage 2 (this): with BB_RT_CARD_ALPHA=1 a draw of such a shader resolves that record with the
// draw's own constants (CardDraw, read on the CPU from memory the GPU did not write), the
// position capture of the entry's vertices also stores per vertex the coordinates and the alpha
// factor into a ring (12 bytes a vertex), and a compute pass (rt_card_uv.comp) turns them into
// one 16-byte record a BLAS primitive in a pool (RtShadow): the coordinates times the draw's
// scale, shifted by whole repeats; the draw's offset stays in the entry's card (its reader adds
// it). Nothing reads the pool yet: no ray, mask, TLAS or BLAS changes, and the picture is the
// same. Only the recompiler's capture stores the UVs: a capture vertex shader with CaptureUv is
// never lifted (vk_pipeline_cache.cpp, CompileModule).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

// A relative path: the header is also built alone (tests), without the engine's include paths.
#include "../host_shaders/rt_card_uv_layout.h"

namespace Vulkan {

// ---- The knob

/// BB_RT_CARD_ALPHA: unset, "0" or anything else off; "1": the card UVs (capture and pool), all
/// stage 2 does. Later stages take levels above 1. Read once (CardAlphaOn in cutout_analysis.h).
inline constexpr std::uint32_t CardAlphaOff = 0;
inline constexpr std::uint32_t CardAlphaUv = 1;
[[nodiscard]] constexpr std::uint32_t ReadCardAlpha(const char* text) noexcept {
    return text && text[0] == '1' && text[1] == '\0' ? CardAlphaUv : CardAlphaOff;
}
/// Set but neither "0" nor "1": said once in the log, as off.
[[nodiscard]] constexpr bool CardAlphaMisread(const char* text) noexcept {
    return text && !((text[0] == '0' || text[0] == '1') && text[1] == '\0');
}

// ---- Sizes (RtShadow's buffers)

/// Ring vertices: 2M of 12 bytes = 24 MiB, made at setup with the knob on (its address is in
/// the capture's address block, which is written once). A frame's UV captures fit or wait.
inline constexpr std::uint32_t CardRingVertices = 2u << 20;
inline constexpr std::uint64_t CardRingBytes = std::uint64_t(CardRingVertices) * CARD_UV_RING_BYTES;
/// Pool records: 4M triangles of 16 bytes = 64 MiB, made at the first card that gets UVs.
inline constexpr std::uint32_t CardPoolRecords = 4u << 20;
inline constexpr std::uint64_t CardPoolBytes = std::uint64_t(CardPoolRecords) * CARD_UV_RECORD_BYTES;
/// Entries given UVs a frame (a level's load meets many new cards at once).
inline constexpr std::uint32_t CardCapturesPerFrame = 64;
/// Frames an entry waits for UVs, drawn, before it gets a capture of its own (a caster built
/// before its record was there is captured again only for that).
inline constexpr std::uint32_t CardWaitFrames = 8;
/// Card slots (a stable number an entry keeps while it lives; stage 4's instanceCustomIndex
/// has 24 bits, the card table this many rows). 0 is "none".
inline constexpr std::uint32_t CardSlotsMost = 1u << 16;

/// The most triangles one dispatch of the expand pass takes (65535 groups, the least
/// maxComputeWorkGroupCount[0] Vulkan allows): a little below CardPoolRecords.
inline constexpr std::uint32_t CardTrianglesMost = 65535u * CARD_UV_GROUP;
static_assert(CardTrianglesMost <= CardPoolRecords);
/// Whether an entry of `triangles` BLAS primitives can have a block of the pool at all.
[[nodiscard]] constexpr bool CardPoolFits(std::uint32_t triangles) noexcept {
    return triangles != 0 && triangles <= CardTrianglesMost;
}
/// The block's bytes: a record a triangle, so always a multiple of the block's 16-byte alignment.
[[nodiscard]] constexpr std::uint64_t CardPoolSize(std::uint32_t triangles) noexcept {
    return std::uint64_t(triangles) * CARD_UV_RECORD_BYTES;
}
/// Whether a capture of `vertices` fits the ring after `used` and the frame's budget after
/// `captures`.
[[nodiscard]] constexpr bool CardRingFits(std::uint64_t used, std::uint64_t vertices,
                                          std::uint32_t captures) noexcept {
    return captures < CardCapturesPerFrame && vertices != 0 && used + vertices <= CardRingVertices;
}
/// Whether a capture for the UVs alone (RtShadow::CardUvProbe) may take a capture param and
/// `stored` vertices of the positions: only within the first half of the frame's params
/// (`params_most`) and positions (`positions_most`), so the builds after it keep the rest.
[[nodiscard]] constexpr bool CardUvProbeFits(std::uint32_t params_used, std::uint32_t params_most,
                                             std::uint64_t positions_used, std::uint64_t stored,
                                             std::uint64_t positions_most) noexcept {
    return stored != 0 && params_used < params_most / 2 && positions_used + stored <= positions_most / 2;
}

// ---- The selector (capture param word 7)

/// Which vertex shader outputs the capture stores: two components of one (u, v) and one of
/// another (the alpha factor; 1.0 without one).
struct CardSelector {
    std::uint32_t uv_out = 0;
    std::uint32_t comp_u = 0;
    std::uint32_t comp_v = 1;
    std::uint32_t alpha_out = 0;
    std::uint32_t alpha_comp = 3;
    bool has_alpha = false;
    constexpr bool operator==(const CardSelector&) const = default;
};
/// Word 7: bits 0-4 uv_out, 5-6 comp_u, 7-8 comp_v, 9-13 alpha_out, 14-15 alpha_comp, 16
/// has_alpha, 31 valid. 0: nothing (the capture of a draw without card data).
inline constexpr std::uint32_t CardSelectorValid = 1u << 31;
[[nodiscard]] constexpr std::uint32_t PackCardSelector(const CardSelector& s) noexcept {
    return (s.uv_out & 31u) | ((s.comp_u & 3u) << 5) | ((s.comp_v & 3u) << 7) |
           ((s.alpha_out & 31u) << 9) | ((s.alpha_comp & 3u) << 14) | (s.has_alpha ? 1u << 16 : 0u) |
           CardSelectorValid;
}
[[nodiscard]] constexpr bool UnpackCardSelector(std::uint32_t word, CardSelector& out) noexcept {
    if ((word & CardSelectorValid) == 0) {
        return false;
    }
    out.uv_out = word & 31u;
    out.comp_u = (word >> 5) & 3u;
    out.comp_v = (word >> 7) & 3u;
    out.alpha_out = (word >> 9) & 31u;
    out.alpha_comp = (word >> 14) & 3u;
    out.has_alpha = ((word >> 16) & 1u) != 0;
    return true;
}
/// A pixel shader input as the draw's regs.ps_inputs[i] has it: the vertex shader output it
/// reads (input_offset), a default value instead, flat shaded.
struct CardInput {
    std::uint32_t vs_out = 0;
    bool use_default = false;
    bool flat = false;
};
/// The selector of a draw. False (no card data) where an input the record names is a default
/// value (the vertex shader output is not what the pixel shader reads) or flat shaded (it reads
/// the provoking vertex's, which a per-corner record would not repeat), or names an output past
/// the 32 a capture can name, or a component past w.
[[nodiscard]] constexpr bool CardSelectorFor(CardInput uv, std::uint32_t comp_u, std::uint32_t comp_v,
                                             bool has_alpha, CardInput alpha,
                                             std::uint32_t alpha_comp, CardSelector& out) noexcept {
    if (uv.use_default || uv.flat || uv.vs_out > 31 || comp_u > 3 || comp_v > 3) {
        return false;
    }
    if (has_alpha && (alpha.use_default || alpha.flat || alpha.vs_out > 31 || alpha_comp > 3)) {
        return false;
    }
    out = {uv.vs_out, comp_u, comp_v, has_alpha ? alpha.vs_out : 0u, has_alpha ? alpha_comp : 3u,
           has_alpha};
    return true;
}

// ---- The test a ray repeats

/// Where the pixel is kept: alpha <op> reference. The order of Info::Cutout::Op (a static_assert
/// at the conversion in vk_rasterizer_effects.cpp ties the two).
enum class CardOp : std::uint8_t { Less, LessEqual, Greater, GreaterEqual, Equal, NotEqual };

/// The kept side of the test. nonzero: the record's term that keeps a pixel only where the
/// alpha is not 0. The game's term is alpha * fade != 0; the per-instance fade (a float the
/// pixel shader reads from a storage buffer at the instance's row) is left out, as r50c's rule
/// decides and as the game's sun shadow pass has it (no fade). So an instance with fade 0, which
/// the game hides, still casts its shadow; that is the one case where leaving it out changes the
/// result (besides a fade that is not a number, or infinite with alpha 0). The alpha != 0 test
/// stays its own check: reference = cb[20] + 0.5 * cb[21] > 0 is not given for every material,
/// and where it is <= 0 only this test drops the fully transparent texels.
/// Equal to the game's test for every alpha that is a number. A NaN alpha is dropped here, while
/// the game keeps it (its discard compares are ordered, so they fail on a NaN; the record does
/// not say ordered or not): a known difference that a Ready record never meets, since a corner
/// whose alpha factor is not a number is marked CARD_UV_TRI_NOT_FINITE, and a texel is a number.
[[nodiscard]] constexpr bool CardKeeps(float alpha, float reference, CardOp op, bool nonzero) noexcept {
    bool keep = false;
    switch (op) {
    case CardOp::Less:
        keep = alpha < reference;
        break;
    case CardOp::LessEqual:
        keep = alpha <= reference;
        break;
    case CardOp::Greater:
        keep = alpha > reference;
        break;
    case CardOp::GreaterEqual:
        keep = alpha >= reference;
        break;
    case CardOp::Equal:
        keep = alpha == reference;
        break;
    case CardOp::NotEqual:
        keep = alpha != reference;
        break;
    }
    return keep && (!nonzero || alpha != 0.0f);
}

/// A finite float (constexpr: std::isfinite is not, before C++23).
[[nodiscard]] constexpr bool CardFinite(float v) noexcept {
    return (std::bit_cast<std::uint32_t>(v) & 0x7f800000u) != 0x7f800000u;
}

/// What a record says beside its dwords: the immediates, and which of the seven dwords
/// (CutoutDwords' order: scale u, scale v, offset u, offset v, reference's first, reference's
/// second, the dither's coefficient) it names. A coordinate part that names a dword is exactly
/// that dword (its immediate part is 0); one that names none is the immediate.
struct CardRecordValues {
    std::array<float, 2> uv_scale{1.0f, 1.0f};
    std::array<float, 2> uv_offset{0.0f, 0.0f};
    float ref = 0.0f;
    float ref_scale = 0.0f;
    float ref2_scale = 0.0f;
    /// The camera pass's dither (Info::Cutout::dither) and its coefficient's immediate part
    /// (dither_scale: times the dither's dword where named[6], alone where not).
    bool dither = false;
    float dither_scale = 0.0f;
    std::array<bool, 7> named{};
};
inline constexpr std::size_t CardDwordDither = 6;
struct CardResolved {
    /// coordinate = input * (affine[0], affine[1]) + (affine[2], affine[3])
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
    /// ref + ref_scale * d1 + ref2_scale * d2: the camera pass's dither taken as 0, the game's
    /// sun shadow pass form; for its material test cb[20] + 0.5 * cb[21] (ref 0, scales 1 and
    /// 0.5, the coefficient -cb[21] of the dither left out).
    float reference = 0.0f;
    /// The dither's coefficient k (0 without a dither): the camera pass keeps alpha >=
    /// reference + k * dither texel; -cb[21] for the game's materials. Kept apart so a later
    /// stage can choose D = 0 (this reference), the mean (reference + 0.5 * k = cb[20]) or a
    /// per-ray dither. Not in the reference.
    float dither_scale = 0.0f;
    /// The reference's two dwords as read (0 where the record names none): cb[20] and cb[21]
    /// for the game's materials (the 600-frame line prints their ranges).
    std::array<float, 2> ref_dwords{};
    bool finite = false;
};
[[nodiscard]] constexpr CardResolved CardResolve(const CardRecordValues& r,
                                                 const std::array<float, 7>& values) noexcept {
    CardResolved out;
    out.affine = {r.named[0] ? values[0] : r.uv_scale[0], r.named[1] ? values[1] : r.uv_scale[1],
                  r.named[2] ? values[2] : r.uv_offset[0], r.named[3] ? values[3] : r.uv_offset[1]};
    out.reference = r.ref + (r.named[4] ? r.ref_scale * values[4] : 0.0f) +
                    (r.named[5] ? r.ref2_scale * values[5] : 0.0f);
    out.ref_dwords = {r.named[4] ? values[4] : 0.0f, r.named[5] ? values[5] : 0.0f};
    out.dither_scale =
        r.dither ? r.dither_scale * (r.named[CardDwordDither] ? values[CardDwordDither] : 1.0f) : 0.0f;
    // Any finite value is taken (no plausibility band: the log saw 0.039 to 0.892); only a value
    // that is not finite gives no card.
    out.finite = CardFinite(out.reference) && CardFinite(out.dither_scale) &&
                 CardFinite(out.ref_dwords[0]) && CardFinite(out.ref_dwords[1]);
    for (const float v : out.affine) {
        out.finite = out.finite && CardFinite(v);
    }
    return out;
}

// ---- Reading a dword at a draw (the guard of r17 and r50b)

/// A dword's state, worse to the right: read; in a region the GPU wrote that is bound in place
/// (BB_GUEST_IN_PLACE: a write still pending; not read); in a region the GPU wrote, or in a
/// buffer the shader writes (not read); not readable (no such buffer, a special one, an invalid
/// V#, outside the buffer or the mapping).
enum class CardDwordState : std::uint8_t { Read, InPlace, GpuWritten, Unreadable };
[[nodiscard]] constexpr CardDwordState CardWorse(CardDwordState a, CardDwordState b) noexcept {
    return std::uint8_t(b) > std::uint8_t(a) ? b : a;
}
/// What the draw's resource list says of the buffer a dword is in.
struct CardBufferFacts {
    bool bound = false;   ///< the record's buffer index is in the shader's list
    bool special = false; ///< not a guest buffer (BufferResource::IsSpecial)
    bool written = false; ///< the shader writes it (BufferResource::is_written)
    bool valid = false;   ///< its V# at this draw is valid
    std::uint64_t base = 0;
    std::uint64_t size = 0;
};
/// Reads dword `dword` of that buffer into `raw` only where every check passes, in this order:
/// the buffer, its V#, inside it, inside a GPU mapping (Guest::Mapped: IsValidGpuMapping and
/// ClampRangeSize), and in no region the GPU wrote (Guest::GpuModified: such a page may be the
/// GPU's with BB_READBACKS=2, and a read fault here would wait for this thread; its CPU copy is
/// stale otherwise). Guest::Read is never reached for a dword the GPU wrote.
template <class Guest>
[[nodiscard]] CardDwordState ReadCardBufferDword(const CardBufferFacts& b, std::uint32_t dword,
                                                 Guest& guest, std::uint32_t& raw) {
    if (!b.bound || b.special) {
        return CardDwordState::Unreadable;
    }
    if (b.written) {
        return CardDwordState::GpuWritten;
    }
    const std::uint64_t offset = std::uint64_t(dword) * 4;
    if (!b.valid || offset + 4 > b.size) {
        return CardDwordState::Unreadable;
    }
    const std::uint64_t address = b.base + offset;
    if (!guest.Mapped(address, 4)) {
        return CardDwordState::Unreadable;
    }
    if (guest.GpuModified(address, 4)) {
        return guest.InPlace(address, 4) ? CardDwordState::InPlace : CardDwordState::GpuWritten;
    }
    raw = guest.Read(address);
    return CardDwordState::Read;
}
/// A user data or flat user data dword (the draw's own SGPRs as the CPU set them up).
[[nodiscard]] constexpr CardDwordState ReadCardUserDword(std::span<const std::uint32_t> data,
                                                         std::uint32_t dword,
                                                         std::uint32_t& raw) noexcept {
    if (dword >= data.size()) {
        return CardDwordState::Unreadable;
    }
    raw = data[dword];
    return CardDwordState::Read;
}

// ---- A draw's card data

/// Why a cut-out draw has no card data (the 600-frame line's "waiting" counts).
enum class CardMiss : std::uint8_t {
    None,
    NoRecord,         ///< no analysis of its pixel shader this run
    /// a record of its pixel shader (the first compile's), but made with another image or
    /// buffer count than this draw's shader has: none of its dwords is read (judge's item 8:
    /// "a record but no constants read", apart from "no record")
    OtherResources,
    NotRepeatable,    ///< analysed, not RepeatableWithConstants() (or not matched), or a fixed layer
    OtherPermutation, ///< its pixel shader inputs are not those the record was analysed with
    Inputs,           ///< an input the record names is a default value or flat shaded
    Constants,        ///< a dword the GPU wrote, in place, not readable, or not a finite value
    Image,            ///< no valid T# or sampler at the record's index
    Count,
};

/// How an axis repeats, from the sampler's clamp mode (AmdGpu::ClampMode: 0 wrap, 1 mirror,
/// the rest clamp in some way, mirror-once ones included: they repeat nothing).
[[nodiscard]] constexpr std::uint32_t CardAxisMode(std::uint32_t clamp_mode) noexcept {
    return clamp_mode == 0 ? CARD_UV_MODE_WRAP
                           : clamp_mode == 1 ? CARD_UV_MODE_MIRROR : CARD_UV_MODE_CLAMP;
}

/// One draw's card data: a plain value, so nothing points into a shader's Info past the draw.
struct CardDraw {
    bool valid = false;
    bool camera = false; ///< a camera pass draw (else a sun shadow pass draw)
    CardMiss miss = CardMiss::None;
    std::uint64_t ps_hash = 0;
    std::uint32_t selector = 0; ///< PackCardSelector
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
    float reference = 0.0f;
    /// CardResolved::dither_scale: the camera pass keeps alpha >= reference + dither_scale *
    /// dither texel (-cb[21] for the game's materials; 0 for a sun shadow pass draw). The
    /// reference takes the dither as 0; stage 3 or 4 chooses (judge's item 3).
    float dither_scale = 0.0f;
    /// CardResolved::ref_dwords (cb[20], cb[21] for the game's materials)
    std::array<float, 2> ref_dwords{};
    CardOp op = CardOp::GreaterEqual;
    bool nonzero = false;
    bool dither = false; ///< the camera pass dithers (taken as 0 here; stage 4 may choose)
    /// The record's nonzero term has an ignored factor (r50c: the per-instance fade, a buffer
    /// load), left out: an instance with fade 0 still casts (CardKeeps). Counted per entry.
    bool fade_left_out = false;
    std::uint8_t stored_channel = 0xff; ///< the stored channel the test's view lane reads
    std::uint8_t data_format = 0;
    std::uint8_t mode_u = CARD_UV_MODE_WRAP;
    std::uint8_t mode_v = CARD_UV_MODE_WRAP;
    std::array<std::uint32_t, 8> tsharp{}; ///< the alpha texture's T# at this draw
    /// What the pool depends on (the pixel shader, the selector, the scale, the modes): another
    /// value captures again. The pixel shader is in it (R4-c), so a capture made for one pass's
    /// card never becomes Ready for the other pass's card, even with the same selector. The
    /// offset is not in it: the pool leaves the offset to its reader (CardPoolAffine).
    std::uint64_t uv_hash = 0;
    /// All of it, the offset, the dither's coefficient and the reference's dwords included
    /// (stage 3: the alpha layer, the reference, the offset).
    std::uint64_t constants_hash = 0;
};

/// FNV-1a over 32-bit words (the hashes only tell values apart; no table is keyed by them).
[[nodiscard]] constexpr std::uint64_t CardHashWords(std::span<const std::uint32_t> words,
                                                    std::uint64_t seed) noexcept {
    std::uint64_t h = seed ^ 0xcbf29ce484222325ull;
    for (const std::uint32_t w : words) {
        for (std::uint32_t k = 0; k < 4; ++k) {
            h ^= (w >> (8 * k)) & 0xffu;
            h *= 0x100000001b3ull;
        }
    }
    return h;
}
/// Fills uv_hash and constants_hash from the other fields.
constexpr void CardFinishHashes(CardDraw& d) noexcept {
    const std::array<std::uint32_t, 7> uv{d.selector,
                                          std::bit_cast<std::uint32_t>(d.affine[0]),
                                          std::bit_cast<std::uint32_t>(d.affine[1]),
                                          d.mode_u, d.mode_v,
                                          std::uint32_t(d.ps_hash), std::uint32_t(d.ps_hash >> 32)};
    d.uv_hash = CardHashWords(uv, 1);
    const std::array<std::uint32_t, 10> rest{
        std::bit_cast<std::uint32_t>(d.reference),
        std::uint32_t(d.op) | (d.nonzero ? 0x100u : 0u) | (d.dither ? 0x200u : 0u) |
            (d.fade_left_out ? 0x400u : 0u),
        std::uint32_t(d.stored_channel) | (std::uint32_t(d.data_format) << 8),
        std::bit_cast<std::uint32_t>(d.affine[2]), std::bit_cast<std::uint32_t>(d.affine[3]),
        std::bit_cast<std::uint32_t>(d.dither_scale),
        std::bit_cast<std::uint32_t>(d.ref_dwords[0]), std::bit_cast<std::uint32_t>(d.ref_dwords[1]),
        0u, 0u};
    d.constants_hash = CardHashWords(d.tsharp, CardHashWords(rest, d.uv_hash));
}
/// The affine the expand pass applies: the draw's scale, and 0 for the offset. The pool holds
/// input * scale minus whole repeats; its reader adds the card's offset (affine[2], [3]), which
/// for a wrapping axis it may take modulo 1 and for a mirrored one modulo 2. Shifting
/// (input * scale) by k whole repeats and adding the offset later samples the texel that
/// input * scale + offset does, so an offset that moves from draw to draw (scrolling UVs) is a
/// constants change (CardNoted::other), not a new capture.
[[nodiscard]] constexpr std::array<float, 4> CardPoolAffine(const std::array<float, 4>& affine) noexcept {
    return {affine[0], affine[1], 0.0f, 0.0f};
}

/// Frames a sun shadow pass card is preferred after the last sun shadow pass draw that gave it
/// (R4-a): r14's longest hold window, MaxHoldPeriod - 1 + HoldMarginFrames = 16 - 1 + 2
/// (vk_rt_shadow.cpp; a static_assert there ties the two). The game draws a sun cascade only
/// once every `period` frames (up to 16 as r14 holds it), so a caster it still shadows can go
/// that long without a sun shadow pass draw; a shorter wait would hand the card to the camera
/// pass and back at every skipped cascade (each hand-over captures the UVs again). Counted as r14
/// counts: frames, frame - the frame of the last valid sun shadow pass draw.
inline constexpr std::uint64_t CardSunFrames = 17;

/// Whether a draw's valid card replaces the entry's. A sun shadow pass card always does (the
/// last one wins). A camera pass card does where the entry has no card, has a camera pass card,
/// or has a sun shadow pass card that the sun shadow pass no longer gives: `stale` (its last
/// draw had no card data, R4-b) or `sun_gone` (no valid sun shadow pass draw for more than
/// CardSunFrames frames: indoors, at night, out of the cascades, R4-a). The sun shadow pass is the
/// game's own shadow test of the material (no dither, no fade), with that pass's constants; the
/// camera pass's reference may differ (its cb[21] scales a dither). An entry drawn by both keeps
/// both references (CardUv::pass_reference) for the log. When the sun shadow pass draws the
/// entry with card data again, its card is taken back.
[[nodiscard]] constexpr bool CardTakes(bool have, bool have_camera, bool camera, bool stale,
                                       bool sun_gone) noexcept {
    return !camera || !have || have_camera || stale || sun_gone;
}

// ---- An entry's UVs

/// NotCard: no card data yet. Wanted: a capture is to store its UVs (with a block of the pool,
/// or getting one). Pending: the expand pass is recorded, the GPU not past it. Ready: the
/// records hold its UVs. NoRoom: no block fitted; tried again when the pool changes.
enum class CardUvState : std::uint8_t { NotCard, Wanted, Pending, Ready, NoRoom, Count };
struct CardUv {
    CardDraw card;
    /// Why the last draw had no card data (None: it had): with no card, any draw's; with a
    /// card, the last draw of the card's own pass (camera or sun shadow). See CardStale.
    CardMiss miss = CardMiss::None;
    CardUvState state = CardUvState::NotCard;
    std::uint64_t tick = 0;        ///< Pending: the submission of the expand pass
    std::uint32_t wait_frames = 0; ///< Wanted: frames drawn without a capture
    std::uint32_t room_gen = 0;    ///< NoRoom: the pool's generation then
    /// The last valid card's reference and pixel shader of each pass ([0] sun shadow, [1]
    /// camera), taken or not, and which passes had one (bit 0 sun shadow, bit 1 camera): the
    /// log shows both references of an entry drawn by both (R4).
    std::array<float, 2> pass_reference{};
    /// and the second reference dword of each (cb[21] for the game's materials)
    std::array<float, 2> pass_ref2{};
    std::array<std::uint64_t, 2> pass_ps_hash{};
    std::uint8_t passes = 0;
    /// The frame of the last sun shadow pass draw with card data (0: none yet): a sun shadow
    /// pass card gives way to a camera pass card more than CardSunFrames frames after it (R4-a).
    std::uint64_t sun_frame = 0;
};
struct CardNoted {
    bool taken = false;       ///< the entry's card is this draw's now
    bool coordinates = false; ///< and the pool needs it again (Wanted)
    bool other = false;       ///< and only what the pool does not hold changed
    bool both = false;        ///< this draw gave the entry a valid card of its second pass
    /// A camera pass card replaced a sun shadow pass card (stale, or the sun shadow pass gone)
    bool sun_gave_way = false;
};
/// Whether the entry had a valid card from both passes and their references differ.
[[nodiscard]] constexpr bool CardBothDiffer(const CardUv& e) noexcept {
    return e.passes == 3 && e.pass_reference[0] != e.pass_reference[1];
}
/// The entry's card is a sun shadow pass card that no sun shadow pass draw gave for more than
/// CardSunFrames frames, as of `frame` (R4-a). A camera pass card then replaces it; the 600-frame
/// line counts the entries still in this state (drawn by neither pass since, or by no camera
/// pass draw with card data).
[[nodiscard]] constexpr bool CardSunGone(const CardUv& e, std::uint64_t frame) noexcept {
    return e.state != CardUvState::NotCard && !e.card.camera && frame > e.sun_frame + CardSunFrames;
}
/// A draw's card data arrives at the entry in frame `frame`. A draw without card data leaves the
/// card as it is but is remembered (miss) when the entry has no card or the draw is of the card's
/// own pass.
constexpr CardNoted CardNote(CardUv& e, const CardDraw& d, std::uint64_t frame) noexcept {
    CardNoted out;
    const bool have = e.state != CardUvState::NotCard;
    if (!d.valid) {
        if (!have || d.camera == e.card.camera) {
            e.miss = d.miss;
        }
        return out;
    }
    const std::size_t pass = d.camera ? 1 : 0;
    const bool had_both = e.passes == 3;
    e.pass_reference[pass] = d.reference;
    e.pass_ref2[pass] = d.ref_dwords[1];
    e.pass_ps_hash[pass] = d.ps_hash;
    e.passes = std::uint8_t(e.passes | (1u << pass));
    out.both = !had_both && e.passes == 3;
    if (!d.camera) {
        e.sun_frame = frame;
    }
    const bool stale = have && e.miss != CardMiss::None;
    if (!CardTakes(have, e.card.camera, d.camera, stale, CardSunGone(e, frame))) {
        return out;
    }
    out.sun_gave_way = have && !e.card.camera && d.camera;
    out.coordinates = !have || d.ps_hash != e.card.ps_hash || d.uv_hash != e.card.uv_hash;
    out.other = !out.coordinates && d.constants_hash != e.card.constants_hash;
    out.taken = true;
    e.card = d;
    e.miss = CardMiss::None;
    if (out.coordinates && e.state != CardUvState::NoRoom && e.state != CardUvState::Wanted) {
        e.state = CardUvState::Wanted;
        e.wait_frames = 0;
    }
    return out;
}
/// The entry has a card, but the last draw of the card's pass had none (its constants are now
/// GPU-written or unreadable, its pixel shader another permutation, ...): the card, and so the
/// pool's records, may no longer be what the game draws. Counted in the 600-frame line; a later
/// stage must not take such a card as current (stage 3: not ready while stale). A stale sun
/// shadow pass card gives way to the next valid camera pass card (CardTakes, R4-b).
[[nodiscard]] constexpr bool CardStale(const CardUv& e) noexcept {
    return e.state != CardUvState::NotCard && e.miss != CardMiss::None;
}
/// Whether a capture of the entry is to store UVs now: Wanted, or NoRoom with a pool that has
/// changed since (a block was freed).
[[nodiscard]] constexpr bool CardCaptureWanted(const CardUv& e, std::uint32_t pool_gen) noexcept {
    return e.state == CardUvState::Wanted ||
           (e.state == CardUvState::NoRoom && pool_gen != e.room_gen);
}
/// No block fitted: wait for the pool to change.
constexpr void CardNoRoom(CardUv& e, std::uint32_t pool_gen) noexcept {
    e.state = CardUvState::NoRoom;
    e.room_gen = pool_gen;
}
/// A block was had (NoRoom no longer).
constexpr void CardGotRoom(CardUv& e) noexcept {
    if (e.state == CardUvState::NoRoom) {
        e.state = CardUvState::Wanted;
    }
}
/// The expand pass of a capture is recorded in the submission of `tick`.
constexpr void CardRecorded(CardUv& e, std::uint64_t tick) noexcept {
    if (e.state == CardUvState::Wanted) {
        e.state = CardUvState::Pending;
        e.tick = tick;
        e.wait_frames = 0;
    }
}
/// At a frame's end: Pending becomes Ready once the GPU is past its tick. True when it did.
constexpr bool CardSettle(CardUv& e, bool tick_passed) noexcept {
    if (e.state == CardUvState::Pending && tick_passed) {
        e.state = CardUvState::Ready;
        return true;
    }
    return false;
}
/// A frame on which the entry was drawn (its first draw of the frame) while it waits.
constexpr void CardWaitFrame(CardUv& e) noexcept {
    if (CardCaptureWanted(e, e.room_gen + 1) && e.wait_frames < 0xffffu) {
        ++e.wait_frames;
    }
}
/// Whether the entry, drawn with nothing else to capture it for, gets a capture for its UVs.
[[nodiscard]] constexpr bool CardUvOnlyDue(const CardUv& e, std::uint32_t pool_gen) noexcept {
    return CardCaptureWanted(e, pool_gen) && e.wait_frames >= CardWaitFrames;
}

/// A block (and slot) of a destroyed entry: freed once the GPU is past `tick` (an expand pass
/// recorded before may still write the block).
struct CardFree {
    std::uint64_t block = 0; ///< the VmaVirtualAllocation, as a number
    std::uint32_t slot = 0;
    std::uint64_t tick = 0;
};
/// Releases the frees whose tick `passed` says the GPU is past; returns how many.
template <class Passed, class Release>
std::size_t CardReleaseFrees(std::vector<CardFree>& frees, Passed&& passed, Release&& release) {
    const std::size_t before = frees.size();
    std::erase_if(frees, [&](const CardFree& f) {
        if (!passed(f.tick)) {
            return false;
        }
        release(f);
        return true;
    });
    return before - frees.size();
}

/// Stable card slots, 1 to CardSlotsMost - 1: freed ones first, lowest number last freed first.
struct CardSlots {
    std::vector<std::uint32_t> free;
    std::uint32_t next = 1;
    /// 0: none left.
    std::uint32_t Take() {
        if (!free.empty()) {
            const std::uint32_t slot = free.back();
            free.pop_back();
            return slot;
        }
        return next < CardSlotsMost ? next++ : 0u;
    }
    void Give(std::uint32_t slot) {
        if (slot != 0) {
            free.push_back(slot);
        }
    }
};

// ---- A pool record (rt_card_uv.comp does the same on the GPU)

struct CardCorner {
    float u = 0.0f;
    float v = 0.0f;
    float a = 1.0f;
};
/// The affine (applied first; RecordBuilds gives the expand pass CardPoolAffine's, the scale
/// alone).
[[nodiscard]] constexpr CardCorner CardApplyAffine(CardCorner c, const std::array<float, 4>& affine) noexcept {
    return {c.u * affine[0] + affine[2], c.v * affine[1] + affine[3], c.a};
}
/// The shift of one axis of a triangle, subtracted before quantizing: wrap the floor of the
/// least corner, mirror an even number (2 * floor(least / 2): a mirrored repeat is 2 long),
/// clamp none.
[[nodiscard]] inline float CardShift(float c0, float c1, float c2, std::uint32_t mode) {
    const float least = std::min(c0, std::min(c1, c2));
    if (mode == CARD_UV_MODE_WRAP) {
        return std::floor(least);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        return 2.0f * std::floor(least * 0.5f);
    }
    return 0.0f;
}
/// float to IEEE half, round to nearest even (packHalf2x16's rounding on the GPUs measured is
/// the same for normal numbers; the tests bound the error, they do not require the same bits).
[[nodiscard]] constexpr std::uint16_t CardHalf(float f) noexcept {
    const std::uint32_t x = std::bit_cast<std::uint32_t>(f);
    const std::uint32_t sign = (x >> 16) & 0x8000u;
    const std::uint32_t exp = (x >> 23) & 0xffu;
    std::uint32_t man = x & 0x7fffffu;
    if (exp == 0xffu) {
        return std::uint16_t(sign | 0x7c00u | (man != 0 ? 0x200u : 0u));
    }
    const int e = int(exp) - 127 + 15;
    if (e >= 31) {
        return std::uint16_t(sign | 0x7c00u);
    }
    if (e <= 0) {
        if (e < -10) {
            return std::uint16_t(sign);
        }
        man |= 0x800000u;
        const std::uint32_t shift = std::uint32_t(14 - e);
        std::uint32_t half = man >> shift;
        const std::uint32_t rest = man & ((1u << shift) - 1u);
        const std::uint32_t mid = 1u << (shift - 1);
        if (rest > mid || (rest == mid && (half & 1u))) {
            ++half;
        }
        return std::uint16_t(sign | half);
    }
    std::uint32_t half = (std::uint32_t(e) << 10) | (man >> 13);
    const std::uint32_t rest = man & 0x1fffu;
    if (rest > 0x1000u || (rest == 0x1000u && (half & 1u))) {
        ++half; // may carry into the exponent, up to infinity, as it should
    }
    return std::uint16_t(sign | half);
}
[[nodiscard]] constexpr float CardHalfToFloat(std::uint16_t h) noexcept {
    const std::uint32_t sign = std::uint32_t(h & 0x8000u) << 16;
    const std::uint32_t exp = (h >> 10) & 0x1fu;
    const std::uint32_t man = h & 0x3ffu;
    if (exp == 0) {
        // subnormal: man * 2^-24
        const float m = float(man) * (1.0f / 16777216.0f);
        return (h & 0x8000u) ? -m : m;
    }
    if (exp == 31) {
        return std::bit_cast<float>(sign | 0x7f800000u | (man << 13));
    }
    return std::bit_cast<float>(sign | ((exp + 112u) << 23) | (man << 13));
}
/// An alpha as unorm8: floor(clamp(a, 0, 1) * 255 + 0.5); not a number gives 0.
[[nodiscard]] constexpr std::uint32_t CardUnorm8(float a) noexcept {
    if (!(a == a)) {
        return 0;
    }
    const float c = a < 0.0f ? 0.0f : a > 1.0f ? 1.0f : a;
    return std::uint32_t(c * 255.0f + 0.5f);
}
/// The tolerance of CardAlphaMarks's range test, in alpha: the grid's (2^-14 of a step), 2.4e-7.
inline constexpr float CardAlphaRangeTolerance = float(CARD_UV_ALPHA_GRID_EPS) / 255.0f;
/// What 8 bits lose of an alpha factor that is a number (rt_card_uv_layout.h, R7, R7-a, R7-b): 0
/// where it is within CARD_UV_ALPHA_GRID_EPS (2^-14) of a step k / 255 (stored as k / 255; not
/// "exact": a few float ulps may differ), CARD_UV_TRI_ALPHA_ROUNDED where it is in [0, 1] but
/// farther from a step (off by at most half a step), CARD_UV_TRI_ALPHA_RANGE below 0 or above 1
/// by more than CardAlphaRangeTolerance (clamped; 1 + 1 ulp is not marked).
[[nodiscard]] inline std::uint32_t CardAlphaMarks(float a) {
    if (a < -CardAlphaRangeTolerance || a > 1.0f + CardAlphaRangeTolerance) {
        return CARD_UV_TRI_ALPHA_RANGE;
    }
    const float steps = a * 255.0f;
    return std::abs(steps - std::floor(steps + 0.5f)) <= float(CARD_UV_ALPHA_GRID_EPS)
               ? 0u
               : std::uint32_t(CARD_UV_TRI_ALPHA_ROUNDED);
}
/// The record of a triangle from its corners after the affine. A coordinate that is not finite,
/// or an alpha factor that is not a number (a vertex no capture stored holds
/// CARD_UV_RING_UNSET), marks it not finite and unshifted. A finite one gets CardAlphaMarks of
/// its corners' alpha factors.
[[nodiscard]] inline std::array<std::uint32_t, 4> CardPackTriangle(std::array<CardCorner, 3> c,
                                                                  std::uint32_t mode_u,
                                                                  std::uint32_t mode_v,
                                                                  bool has_alpha) {
    std::uint32_t flags = has_alpha ? 0u : std::uint32_t(CARD_UV_TRI_NO_ALPHA);
    bool finite = true;
    for (const CardCorner& k : c) {
        finite = finite && CardFinite(k.u) && CardFinite(k.v) && !(has_alpha && k.a != k.a);
    }
    if (finite) {
        const float su = CardShift(c[0].u, c[1].u, c[2].u, mode_u);
        const float sv = CardShift(c[0].v, c[1].v, c[2].v, mode_v);
        for (CardCorner& k : c) {
            k.u -= su;
            k.v -= sv;
            if (std::abs(k.u) >= float(CARD_UV_SPAN_LIMIT) || std::abs(k.v) >= float(CARD_UV_SPAN_LIMIT)) {
                flags |= CARD_UV_TRI_WIDE;
            }
            if (has_alpha) {
                flags |= CardAlphaMarks(k.a);
            }
        }
    } else {
        flags |= CARD_UV_TRI_NOT_FINITE;
    }
    std::array<std::uint32_t, 4> w{};
    for (std::size_t i = 0; i < 3; ++i) {
        w[i] = std::uint32_t(CardHalf(c[i].u)) | (std::uint32_t(CardHalf(c[i].v)) << 16);
        w[3] |= (has_alpha ? CardUnorm8(c[i].a) : 255u) << (8 * i);
    }
    w[3] |= flags << CARD_UV_FLAGS_SHIFT;
    return w;
}
/// The corners (alpha in [0, 1]) and flags of a record.
inline void CardUnpackTriangle(const std::array<std::uint32_t, 4>& w, std::array<CardCorner, 3>& c,
                               std::uint32_t& flags) {
    for (std::size_t i = 0; i < 3; ++i) {
        c[i].u = CardHalfToFloat(std::uint16_t(w[i] & 0xffffu));
        c[i].v = CardHalfToFloat(std::uint16_t(w[i] >> 16));
        c[i].a = float((w[3] >> (8 * i)) & 0xffu) / 255.0f;
    }
    flags = w[3] >> CARD_UV_FLAGS_SHIFT;
}

// ---- The expand pass's push constants and stat slots

struct CardUvPush {
    std::uint64_t indices = 0;   ///< the entry's triangle list (Entry::indices, device address)
    std::uint32_t ring_base = 0; ///< the capture's first vertex in the ring
    std::uint32_t triangles = 0;
    std::uint32_t pool_offset = 0; ///< records
    std::uint32_t flags = 0;       ///< modes, alpha, stat slot (rt_card_uv_layout.h)
    std::array<std::uint32_t, 2> unused{};
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
};
static_assert(sizeof(CardUvPush) == CARD_UV_PUSH_BYTES &&
              offsetof(CardUvPush, ring_base) == CARD_UV_PUSH_RING_BASE &&
              offsetof(CardUvPush, triangles) == CARD_UV_PUSH_TRIANGLES &&
              offsetof(CardUvPush, pool_offset) == CARD_UV_PUSH_POOL_OFFSET &&
              offsetof(CardUvPush, flags) == CARD_UV_PUSH_FLAGS &&
              offsetof(CardUvPush, affine) == CARD_UV_PUSH_AFFINE);
/// stat_slot: 0 none, else the slot + 1 (at most CARD_UV_STAT_SLOTS).
[[nodiscard]] constexpr std::uint32_t CardPushFlags(std::uint32_t mode_u, std::uint32_t mode_v,
                                                    bool has_alpha, std::uint32_t stat_slot) noexcept {
    return (mode_u & 3u) | ((mode_v & 3u) << CARD_UV_PUSH_MODE_V_SHIFT) |
           (has_alpha ? std::uint32_t(CARD_UV_PUSH_HAS_ALPHA) : 0u) |
           ((stat_slot & 7u) << CARD_UV_PUSH_STAT_SHIFT);
}
/// A float as an unsigned number of the same order (rt_still_sig.comp's Key), and back.
[[nodiscard]] constexpr std::uint32_t CardStatKey(float v) noexcept {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(v);
    return (bits & 0x80000000u) ? ~bits : (bits | 0x80000000u);
}
[[nodiscard]] constexpr float CardStatValue(std::uint32_t key) noexcept {
    return std::bit_cast<float>((key & 0x80000000u) ? (key & 0x7fffffffu) : ~key);
}
struct CardStat {
    bool any = false; ///< a finite corner was seen
    float umin = 0, umax = 0, vmin = 0, vmax = 0, amin = 0, amax = 0;
    std::uint32_t wide = 0, not_finite = 0;
    std::uint32_t alpha_range = 0;   ///< triangles marked CARD_UV_TRI_ALPHA_RANGE
    std::uint32_t alpha_rounded = 0; ///< triangles marked CARD_UV_TRI_ALPHA_ROUNDED
};
[[nodiscard]] constexpr CardStat CardReadStat(const std::uint32_t* w) noexcept {
    CardStat s;
    s.any = w[3] != 0;
    if (s.any) {
        s.umin = CardStatValue(~w[0]);
        s.vmin = CardStatValue(~w[1]);
        s.amin = CardStatValue(~w[2]);
        s.umax = CardStatValue(w[3]);
        s.vmax = CardStatValue(w[4]);
        s.amax = CardStatValue(w[5]);
    }
    s.wide = w[6];
    s.not_finite = w[7];
    s.alpha_range = w[8];
    s.alpha_rounded = w[9];
    return s;
}

/// The class of a cut-out entry as BB_RT_LAMP_CARDS=3 (the default rule) sees it: a skeleton
/// that no sun shadow pass draws (a plant), no skeleton, a skeleton kept (hair, cloth).
enum class CardClass : std::uint8_t { Plant, Static, SkinnedKept, Count };
[[nodiscard]] constexpr CardClass CardClassOf(bool skinned, bool lone) noexcept {
    return !skinned ? CardClass::Static : lone ? CardClass::Plant : CardClass::SkinnedKept;
}

} // namespace Vulkan
""",
    TESTS + "test_rt_card_uv.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r54_leaf-stage2): tests of the pure parts of the card UVs (rt_card_uv.h): the knob, the
// selector, the alpha test a ray repeats against the game's decompiled test, the guard of the
// draw-time dword read, the 16-byte record and what its 8-bit alpha factor keeps of the game's
// decision, the entry states (the sun shadow pass's card preferred), the frees and slots, the
// stat keys.
// Built alone: c++ -std=c++20 -I. tests/test_rt_card_uv.cpp (engine/build.sh --test).

#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_uv.h"

using namespace Vulkan;

namespace {

int failures = 0;
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::printf("FAILED %s:%d: %s\n", __FILE__, __LINE__, #x);                             \
            ++failures;                                                                            \
        }                                                                                          \
    } while (0)

void TestKnob() {
    CHECK(ReadCardAlpha(nullptr) == CardAlphaOff);
    CHECK(ReadCardAlpha("") == CardAlphaOff);
    CHECK(ReadCardAlpha("0") == CardAlphaOff);
    CHECK(ReadCardAlpha("1") == CardAlphaUv);
    CHECK(ReadCardAlpha("2") == CardAlphaOff); // later stages' levels are not this stage's
    CHECK(ReadCardAlpha("10") == CardAlphaOff);
    CHECK(ReadCardAlpha(" 1") == CardAlphaOff);
    CHECK(ReadCardAlpha("yes") == CardAlphaOff);
    CHECK(!CardAlphaMisread(nullptr));
    CHECK(!CardAlphaMisread("0"));
    CHECK(!CardAlphaMisread("1"));
    CHECK(CardAlphaMisread(""));
    CHECK(CardAlphaMisread("2"));
    CHECK(CardAlphaMisread("on"));
}

void TestSizes() {
    CHECK(CardRingBytes == 24ull << 20);
    CHECK(CardPoolBytes == 64ull << 20);
    CHECK(!CardPoolFits(0));
    CHECK(CardPoolFits(1));
    CHECK(CardPoolFits(CardTrianglesMost));
    CHECK(!CardPoolFits(CardTrianglesMost + 1));
    CHECK(!CardPoolFits(CardPoolRecords + 1));
    CHECK((CardTrianglesMost + CARD_UV_GROUP - 1) / CARD_UV_GROUP <= 65535u); // one dispatch
    CHECK(CardPoolSize(3) == 48);
    CHECK(CardPoolSize(1) % 16 == 0);
    CHECK(CardRingFits(0, 3, 0));
    CHECK(!CardRingFits(0, 0, 0));
    CHECK(CardRingFits(CardRingVertices - 3, 3, 0));
    CHECK(!CardRingFits(CardRingVertices - 2, 3, 0));
    CHECK(!CardRingFits(0, 3, CardCapturesPerFrame));
    CHECK(CardRingFits(0, 3, CardCapturesPerFrame - 1));
    // a capture for the UVs alone: within the first half of the frame's params and positions
    CHECK(CardUvProbeFits(0, 8192, 0, 3, 8u << 20));
    CHECK(CardUvProbeFits(4095, 8192, (4u << 20) - 3, 3, 8u << 20));
    CHECK(!CardUvProbeFits(4096, 8192, 0, 3, 8u << 20));
    CHECK(!CardUvProbeFits(0, 8192, (4u << 20) - 2, 3, 8u << 20));
    CHECK(!CardUvProbeFits(0, 8192, 0, 0, 8u << 20));
}

void TestSelector() {
    // every field at its extremes survives the word
    for (std::uint32_t uv = 0; uv < 32; uv += 31) {
        for (std::uint32_t cu = 0; cu < 4; ++cu) {
            for (std::uint32_t cv = 0; cv < 4; ++cv) {
                for (std::uint32_t ao = 0; ao < 32; ao += 7) {
                    for (std::uint32_t ac = 0; ac < 4; ++ac) {
                        for (int ha = 0; ha < 2; ++ha) {
                            const CardSelector s{uv, cu, cv, ao, ac, ha != 0};
                            const std::uint32_t w = PackCardSelector(s);
                            CHECK(w != 0);
                            CHECK((w & CardSelectorValid) != 0);
                            CardSelector back;
                            CHECK(UnpackCardSelector(w, back));
                            CHECK(back == s);
                            // the shader's decode: the same bit fields
                            CHECK((w & 31u) == uv && ((w >> 5) & 3u) == cu && ((w >> 7) & 3u) == cv &&
                                  ((w >> 9) & 31u) == ao && ((w >> 14) & 3u) == ac &&
                                  ((w >> 16) & 1u) == std::uint32_t(ha));
                        }
                    }
                }
            }
        }
    }
    CardSelector none;
    CHECK(!UnpackCardSelector(0, none));
    CHECK(!UnpackCardSelector(0x7fffffffu, none));

    CardSelector s;
    CHECK(CardSelectorFor({4, false, false}, 0, 1, true, {2, false, false}, 3, s));
    CHECK(s == (CardSelector{4, 0, 1, 2, 3, true}));
    CHECK(CardSelectorFor({4, false, false}, 2, 3, false, {9, true, true}, 0, s));
    CHECK(s == (CardSelector{4, 2, 3, 0, 3, false})); // no alpha: its input is not looked at
    CHECK(!CardSelectorFor({4, true, false}, 0, 1, false, {}, 0, s));  // default value
    CHECK(!CardSelectorFor({4, false, true}, 0, 1, false, {}, 0, s));  // flat
    CHECK(!CardSelectorFor({32, false, false}, 0, 1, false, {}, 0, s)); // past 31
    CHECK(!CardSelectorFor({4, false, false}, 4, 1, false, {}, 0, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, true, false}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, false, true}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {40, false, false}, 3, s));
    CHECK(!CardSelectorFor({4, false, false}, 0, 1, true, {2, false, false}, 4, s));
}

// The game's test, as decompiled in the stage 1 run (camera pass): the pixel is discarded where
// cb20 > cb21 * (D - 0.5) + A, or A * fade == 0. Kept otherwise.
bool GameCameraKeeps(float a, float fade, float cb20, float cb21, float d) {
    return !(cb20 > cb21 * (d - 0.5f) + a || a * fade == 0.0f);
}
// The sun shadow pass form: the dither left out, cb21 * -0.5.
bool GameShadowKeeps(float a, float fade, float cb20, float cb21) {
    return !(cb20 > cb21 * -0.5f + a || a * fade == 0.0f);
}

// The record r50b makes of that test (info.h Cutout: reference = ref + ref_scale * d1 +
// ref2_scale * d2, the dither's coefficient -1 * cb21 apart) as the engine resolves it.
CardRecordValues GameRecord() {
    CardRecordValues r;
    r.ref = 0.0f;
    r.ref_scale = 1.0f;  // cb[20]
    r.ref2_scale = 0.5f; // cb[21]
    r.named = {true, true, true, true, true, true, true};
    return r;
}

void TestAlphaRule() {
    const CardRecordValues record = GameRecord();
    // Dyadic grids, where every sum and product here is exact, so both forms decide alike.
    int compared = 0;
    for (int ti = 0; ti <= 64; ++ti) {           // texel alpha
        for (int vi = 0; vi <= 16; vi += 2) {    // vertex colour alpha
            for (int c0 = -8; c0 <= 40; c0 += 3) {       // cb20 in 1/32
                for (int c1 = -16; c1 <= 32; c1 += 4) {  // cb21 in 1/32
                    const float t = float(ti) / 64.0f;
                    const float vc = float(vi) / 16.0f;
                    const float a = t * vc;
                    const float cb20 = float(c0) / 32.0f;
                    const float cb21 = float(c1) / 32.0f;
                    const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, -cb21};
                    const CardResolved r = CardResolve(record, values);
                    CHECK(r.finite);
                    // the shadow form, exactly
                    const bool ray = CardKeeps(a, r.reference, CardOp::GreaterEqual, true);
                    CHECK(ray == GameShadowKeeps(a, 1.0f, cb20, cb21));
                    // the camera form with its dither texel at 0 is the same test
                    CHECK(ray == GameCameraKeeps(a, 1.0f, cb20, cb21, 0.0f));
                    // and the reference is cb20 + 0.5 * cb21
                    CHECK(r.reference == cb20 + 0.5f * cb21);
                    ++compared;
                }
            }
        }
    }
    CHECK(compared > 50000);

    // Random values: the two forms differ only within rounding of the boundary.
    std::mt19937 rng(54);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    std::uniform_real_distribution<float> wide(-1.0f, 2.0f);
    int differ = 0;
    for (int i = 0; i < 200000; ++i) {
        const float a = unit(rng) * unit(rng);
        const float cb20 = wide(rng);
        const float cb21 = wide(rng);
        const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, -cb21};
        const float ref = CardResolve(record, values).reference;
        const bool ray = CardKeeps(a, ref, CardOp::GreaterEqual, true);
        if (ray != GameShadowKeeps(a, 1.0f, cb20, cb21)) {
            ++differ;
            CHECK(std::abs(a - ref) <= 4e-7f * (1.0f + std::abs(cb20) + std::abs(cb21)));
        }
    }
    CHECK(differ < 50);

    // A zero alpha is dropped even under a reference below 0 (the nonzero term); without the
    // term it is kept. A negative alpha is not 0: kept by the term (the game's A == 0 test).
    CHECK(!CardKeeps(0.0f, -1.0f, CardOp::GreaterEqual, true));
    CHECK(CardKeeps(0.0f, -1.0f, CardOp::GreaterEqual, false));
    CHECK(CardKeeps(-0.5f, -1.0f, CardOp::GreaterEqual, true));
    CHECK(CardKeeps(-0.5f, -1.0f, CardOp::GreaterEqual, true) == GameShadowKeeps(-0.5f, 1.0f, -1.5f, 1.0f));
    CHECK(GameShadowKeeps(-0.5f, 1.0f, -1.5f, 1.0f)); // reference -1.5 + 0.5: -1
    // the ops
    CHECK(CardKeeps(0.4f, 0.5f, CardOp::Less, false) && !CardKeeps(0.5f, 0.5f, CardOp::Less, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::LessEqual, false) && !CardKeeps(0.6f, 0.5f, CardOp::LessEqual, false));
    CHECK(CardKeeps(0.6f, 0.5f, CardOp::Greater, false) && !CardKeeps(0.5f, 0.5f, CardOp::Greater, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::GreaterEqual, false) && !CardKeeps(0.4f, 0.5f, CardOp::GreaterEqual, false));
    CHECK(CardKeeps(0.5f, 0.5f, CardOp::Equal, false) && !CardKeeps(0.4f, 0.5f, CardOp::Equal, false));
    CHECK(CardKeeps(0.4f, 0.5f, CardOp::NotEqual, false) && !CardKeeps(0.5f, 0.5f, CardOp::NotEqual, false));
    // A NaN alpha: CardKeeps drops it, the game keeps it (its discard compares are ordered and
    // fail on a NaN). A known difference, pinned here; the expand pass marks a corner whose
    // alpha factor is not a number not finite (TestPack), so a Ready record never holds one.
    CHECK(!CardKeeps(std::nanf(""), 0.5f, CardOp::GreaterEqual, false));
    CHECK(!CardKeeps(std::nanf(""), 0.5f, CardOp::GreaterEqual, true));
    CHECK(GameShadowKeeps(std::nanf(""), 1.0f, 0.25f, 0.5f));
    CHECK(GameCameraKeeps(std::nanf(""), 1.0f, 0.25f, 0.5f, 0.0f));
    // The per-instance fade is left out (r50c): with fade 0 the game drops every pixel of the
    // instance, a ray keeps what the alpha test keeps (the instance still casts its shadow); with
    // any other finite fade the two agree.
    CHECK(!GameShadowKeeps(0.5f, 0.0f, 0.25f, 0.0f) && !GameCameraKeeps(0.5f, 0.0f, 0.25f, 0.0f, 0.0f));
    CHECK(CardKeeps(0.5f, 0.25f, CardOp::GreaterEqual, true));
    for (const float fade : {1e-6f, 0.3f, 1.0f, 7.0f}) {
        for (const float a : {0.0f, 0.1f, 0.25f, 0.5f}) {
            CHECK(GameShadowKeeps(a, fade, 0.25f, 0.0f) == CardKeeps(a, 0.25f, CardOp::GreaterEqual, true));
            CHECK(GameShadowKeeps(a, fade, -0.5f, 0.0f) == CardKeeps(a, -0.5f, CardOp::GreaterEqual, true));
        }
    }

    // Immediates where the record names no dword; a dword where it does.
    CardRecordValues imm;
    imm.uv_scale = {2.0f, 3.0f};
    imm.uv_offset = {0.25f, -0.5f};
    imm.ref = 0.5f;
    imm.ref_scale = 7.0f; // not named: left out
    const std::array<float, 7> junk{9, 9, 9, 9, 9, 9, 9};
    CardResolved ri = CardResolve(imm, junk);
    CHECK(ri.affine == (std::array<float, 4>{2.0f, 3.0f, 0.25f, -0.5f}));
    CHECK(ri.reference == 0.5f);
    CHECK(ri.finite);
    imm.named[1] = true;
    imm.named[2] = true;
    imm.named[4] = true;
    ri = CardResolve(imm, junk);
    CHECK(ri.affine == (std::array<float, 4>{2.0f, 9.0f, 9.0f, -0.5f}));
    CHECK(ri.reference == 0.5f + 7.0f * 9.0f);
    // the second dword of the reference counts by its own name, not the first's
    {
        CardRecordValues two;
        two.ref = 0.125f;
        two.ref_scale = 1.0f;
        two.ref2_scale = 0.5f;
        two.named[5] = true; // the second named, the first not
        const std::array<float, 7> v{1, 1, 0, 0, 100.0f, 0.25f, 0};
        CHECK(CardResolve(two, v).reference == 0.125f + 0.5f * 0.25f);
        two.named[5] = false;
        two.named[4] = true; // the first named, the second not
        CHECK(CardResolve(two, v).reference == 0.125f + 100.0f);
    }
    // the dither dword never enters the reference
    std::array<float, 7> dith{1, 1, 0, 0, 0.25f, 0.5f, 1000.0f};
    CHECK(CardResolve(record, dith).reference == 0.5f);
    CHECK(CardResolve(record, dith).dither_scale == 0.0f); // the record has no dither
    // not finite values make no card
    dith[0] = std::nanf("");
    CHECK(!CardResolve(record, dith).finite);
    dith[0] = 1.0f;
    dith[4] = INFINITY;
    CHECK(!CardResolve(record, dith).finite);
    dith[4] = 0.25f;
    dith[6] = INFINITY; // the dither's, without a dither: not used, no matter
    CHECK(CardResolve(record, dith).finite);
    // no plausibility band (judge's item 5): any finite reference makes a card, also one <= 0
    // or above 1
    for (const float cb20 : {-3.0f, -0.5f, 0.0f, 0.0392153f, 0.892156f, 1.5f, 1e6f}) {
        const std::array<float, 7> v{1, 1, 0, 0, cb20, 0.0f, 0.0f};
        CHECK(CardResolve(record, v).finite && CardResolve(record, v).reference == cb20);
    }
}

// The camera pass's dither kept apart (judge's item 3): the record of the camera form names the
// dither's coefficient -1 * cb[21] (dither_scale -1, its dword cb[21]); the reference stays
// cb20 + 0.5 * cb21 (the dither taken as 0), and reference + dither_scale * D is the game's
// camera pass threshold at any dither texel D.
void TestDitherApart() {
    CardRecordValues record = GameRecord();
    record.dither = true;
    record.dither_scale = -1.0f;
    int compared = 0;
    for (int ti = 0; ti <= 32; ++ti) {
        for (int c0 = -8; c0 <= 40; c0 += 4) {
            for (int c1 = -16; c1 <= 32; c1 += 8) {
                for (int di = 0; di <= 15; ++di) { // the 4x4 dither's 16 levels
                    const float a = float(ti) / 32.0f;
                    const float cb20 = float(c0) / 32.0f;
                    const float cb21 = float(c1) / 32.0f;
                    const float d = float(di) / 16.0f;
                    const std::array<float, 7> values{1.0f, 1.0f, 0.0f, 0.0f, cb20, cb21, cb21};
                    const CardResolved r = CardResolve(record, values);
                    CHECK(r.finite);
                    CHECK(r.reference == cb20 + 0.5f * cb21);
                    CHECK(r.dither_scale == -cb21);
                    CHECK(r.ref_dwords[0] == cb20 && r.ref_dwords[1] == cb21);
                    CHECK(CardKeeps(a, r.reference + r.dither_scale * d, CardOp::GreaterEqual, true) ==
                          GameCameraKeeps(a, 1.0f, cb20, cb21, d));
                    ++compared;
                }
            }
        }
    }
    CHECK(compared > 10000);
    // 998b035e's constants (cb20 0.392156, cb21 1): the reference is the strictest end 0.892156,
    // the threshold runs down to -0.108 at D = 1
    {
        const std::array<float, 7> v{1, 1, 0, 0, 0.392156f, 1.0f, 1.0f};
        const CardResolved r = CardResolve(record, v);
        CHECK(std::abs(r.reference - 0.892156f) < 1e-6f && r.dither_scale == -1.0f);
        CHECK(std::abs(r.reference + r.dither_scale * 1.0f + 0.107844f) < 1e-6f);
    }
    // a coefficient with no dword is the immediate alone; a coefficient that is not finite makes
    // no card
    {
        CardRecordValues imm = record;
        imm.named[CardDwordDither] = false;
        imm.dither_scale = -0.25f;
        const std::array<float, 7> v{1, 1, 0, 0, 0.25f, 0.5f, 99.0f};
        CHECK(CardResolve(imm, v).dither_scale == -0.25f);
        std::array<float, 7> bad = v;
        bad[CardDwordDither] = INFINITY;
        CHECK(!CardResolve(record, bad).finite);
        CHECK(CardResolve(imm, bad).finite); // not named: not used
    }
}

// A guest memory for the guard: records every call, so the order and the reads are checked.
struct FakeGuest {
    std::uint64_t mapped_lo = 0x1000, mapped_hi = 0x2000; // [lo, hi)
    std::uint64_t gpu_lo = 0, gpu_hi = 0;                 // GPU-written region
    bool in_place = false;
    std::vector<char> calls; // 'M', 'G', 'I', 'R'
    int reads = 0;
    bool Mapped(std::uint64_t a, std::uint64_t n) {
        calls.push_back('M');
        return a >= mapped_lo && a + n <= mapped_hi;
    }
    bool GpuModified(std::uint64_t a, std::uint64_t n) {
        calls.push_back('G');
        return a < gpu_hi && a + n > gpu_lo;
    }
    bool InPlace(std::uint64_t, std::uint64_t) {
        calls.push_back('I');
        return in_place;
    }
    std::uint32_t Read(std::uint64_t a) {
        calls.push_back('R');
        ++reads;
        return std::uint32_t(a * 3u);
    }
};

void TestGuard() {
    CardBufferFacts b{true, false, false, true, 0x1000, 0x100};
    {
        FakeGuest g;
        std::uint32_t raw = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::Read);
        CHECK(raw == std::uint32_t((0x1000 + 80) * 3));
        CHECK((g.calls == std::vector<char>{'M', 'G', 'R'}));
    }
    {
        // the GPU wrote it: never read
        FakeGuest g;
        g.gpu_lo = 0x1050;
        g.gpu_hi = 0x1054;
        std::uint32_t raw = 77;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::GpuWritten);
        CHECK(g.reads == 0 && raw == 77);
        // a dword beside it is read
        CHECK(ReadCardBufferDword(b, 21, g, raw) == CardDwordState::Read);
        g.in_place = true;
        g.reads = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::InPlace);
        CHECK(g.reads == 0);
    }
    {
        // outside the mapping: not even asked about the GPU
        FakeGuest g;
        g.mapped_hi = 0x1050;
        std::uint32_t raw = 0;
        CHECK(ReadCardBufferDword(b, 20, g, raw) == CardDwordState::Unreadable);
        CHECK((g.calls == std::vector<char>{'M'}));
    }
    {
        // the buffer's checks come before any memory call
        FakeGuest g;
        std::uint32_t raw = 0;
        CardBufferFacts x = b;
        x.bound = false;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        x.special = true;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        x.written = true;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::GpuWritten);
        x = b;
        x.valid = false;
        CHECK(ReadCardBufferDword(x, 0, g, raw) == CardDwordState::Unreadable);
        x = b;
        CHECK(ReadCardBufferDword(x, 0x40, g, raw) == CardDwordState::Unreadable); // past size
        CHECK(ReadCardBufferDword(x, 0x3f, g, raw) == CardDwordState::Read);       // last dword
        CHECK(g.reads == 1);
    }
    {
        const std::uint32_t user[4] = {1, 2, 3, 4};
        std::uint32_t raw = 0;
        CHECK(ReadCardUserDword(user, 3, raw) == CardDwordState::Read && raw == 4);
        CHECK(ReadCardUserDword(user, 4, raw) == CardDwordState::Unreadable);
    }
    CHECK(CardWorse(CardDwordState::Read, CardDwordState::InPlace) == CardDwordState::InPlace);
    CHECK(CardWorse(CardDwordState::GpuWritten, CardDwordState::InPlace) == CardDwordState::GpuWritten);
    CHECK(CardWorse(CardDwordState::Unreadable, CardDwordState::Read) == CardDwordState::Unreadable);
}

void TestHalf() {
    // every half: back to float and again, the same bits (NaNs stay NaNs)
    for (std::uint32_t h = 0; h < 65536; ++h) {
        const float f = CardHalfToFloat(std::uint16_t(h));
        const std::uint16_t again = CardHalf(f);
        if ((h & 0x7c00u) == 0x7c00u && (h & 0x3ffu) != 0) {
            CHECK(f != f);
            CHECK((again & 0x7c00u) == 0x7c00u && (again & 0x3ffu) != 0);
        } else {
            CHECK(again == h);
        }
    }
#if defined(__FLT16_MAX__)
    // against the compiler's conversion (round to nearest even)
    std::mt19937 rng(16);
    std::uniform_real_distribution<float> d(-70000.0f, 70000.0f);
    std::uniform_real_distribution<float> s(-8.0f, 8.0f);
    for (int i = 0; i < 400000; ++i) {
        const float f = (i & 1) ? d(rng) : s(rng) * std::ldexp(1.0f, -(i % 30));
        const _Float16 ref = _Float16(f);
        std::uint16_t bits;
        std::memcpy(&bits, &ref, 2);
        CHECK(CardHalf(f) == bits);
    }
#endif
    CHECK(CardHalf(1.0f) == 0x3c00u);
    CHECK(CardHalf(-2.0f) == 0xc000u);
    CHECK(CardHalf(65504.0f) == 0x7bffu);
    CHECK(CardHalf(65520.0f) == 0x7c00u); // rounds up to infinity
    CHECK(CardHalf(1e-8f) == 0);
    CHECK(CardHalfToFloat(0x0001u) == std::ldexp(1.0f, -24));
}

void TestPack() {
    // unorm8
    CHECK(CardUnorm8(0.0f) == 0 && CardUnorm8(1.0f) == 255 && CardUnorm8(-1.0f) == 0 &&
          CardUnorm8(2.0f) == 255 && CardUnorm8(std::nanf("")) == 0);
    CHECK(CardUnorm8(0.5f) == 128); // 127.5 + 0.5
    for (int k = 0; k <= 255; ++k) {
        CHECK(CardUnorm8(float(k) / 255.0f) == std::uint32_t(k));
    }
    // shifts
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_WRAP) == 3.0f);
    CHECK(CardShift(-0.2f, 0.5f, 0.1f, CARD_UV_MODE_WRAP) == -1.0f);
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_MIRROR) == 2.0f);
    CHECK(CardShift(5.5f, 6.0f, 5.9f, CARD_UV_MODE_MIRROR) == 4.0f);
    CHECK(CardShift(-0.5f, 0.5f, 0.5f, CARD_UV_MODE_MIRROR) == -2.0f);
    CHECK(CardShift(3.2f, 3.9f, 4.1f, CARD_UV_MODE_CLAMP) == 0.0f);

    std::mt19937 rng(4);
    std::uniform_real_distribution<float> base(-300.0f, 300.0f);
    std::uniform_real_distribution<float> spread(0.0f, 1.5f);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    for (int i = 0; i < 100000; ++i) {
        const std::uint32_t mu = std::uint32_t(i % 3), mv = std::uint32_t((i / 3) % 3);
        const bool has_alpha = (i & 4) != 0;
        const float bu = (mu == CARD_UV_MODE_CLAMP) ? unit(rng) : base(rng);
        const float bv = (mv == CARD_UV_MODE_CLAMP) ? unit(rng) : base(rng);
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            k = {bu + spread(rng), bv + spread(rng), unit(rng)};
        }
        const std::array<std::uint32_t, 4> w = CardPackTriangle(c, mu, mv, has_alpha);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK((flags & CARD_UV_TRI_NOT_FINITE) == 0);
        CHECK(((flags & CARD_UV_TRI_NO_ALPHA) != 0) == !has_alpha);
        const float su = CardShift(c[0].u, c[1].u, c[2].u, mu);
        const float sv = CardShift(c[0].v, c[1].v, c[2].v, mv);
        // the shift keeps the sampled texel: whole repeats (wrap) or pairs (mirror)
        CHECK(su == std::floor(su) && sv == std::floor(sv));
        if (mu == CARD_UV_MODE_MIRROR) {
            CHECK(std::fmod(su, 2.0f) == 0.0f);
        }
        bool wide = false;
        for (std::size_t k = 0; k < 3; ++k) {
            const float eu = c[k].u - su, ev = c[k].v - sv;
            wide = wide || std::abs(eu) >= 4.0f || std::abs(ev) >= 4.0f;
            // half precision of a value below 4: error at most 2^-10 (half an ulp of 2^-9);
            // the shift itself is exact for these magnitudes
            CHECK(std::abs(out[k].u - eu) <= std::ldexp(1.0f, -10) * std::max(1.0f, std::abs(eu)) / 2.0f + 1e-6f);
            CHECK(std::abs(out[k].v - ev) <= std::ldexp(1.0f, -10) * std::max(1.0f, std::abs(ev)) / 2.0f + 1e-6f);
            if (has_alpha) {
                CHECK(std::abs(out[k].a - c[k].a) <= 0.5f / 255.0f + 1e-6f);
            } else {
                CHECK(out[k].a == 1.0f);
            }
        }
        CHECK(((flags & CARD_UV_TRI_WIDE) != 0) == wide);
        // a spread below 1.5 after a wrap shift is never wide
        if (mu == CARD_UV_MODE_WRAP && mv == CARD_UV_MODE_WRAP) {
            CHECK(!wide);
        }
    }
    // a wide one: marked, kept
    {
        const std::array<CardCorner, 3> c{{{0.0f, 0.0f, 1.0f}, {9.5f, 0.0f, 1.0f}, {0.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
        CHECK(out[1].u == 9.5f);
    }
    // exactly 4.0 after the shift is wide; just below is not
    {
        std::array<CardCorner, 3> c{{{0.0f, 0.0f, 1.0f}, {4.0f, 0.0f, 1.0f}, {0.0f, 1.0f, 1.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
        c[1].u = 3.99f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == 0);
        c[1] = {0.5f, -4.0f, 1.0f}; // and on v, below 0 (clamp: no shift)
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_WIDE);
    }
    // an alpha factor that is not a number (a vertex no capture stored: CARD_UV_RING_UNSET)
    // marks the triangle not finite; without an alpha factor the value is not looked at
    {
        float unset = 0.0f;
        const std::uint32_t bits = CARD_UV_RING_UNSET;
        std::memcpy(&unset, &bits, 4);
        CHECK(unset != unset);
        std::array<CardCorner, 3> c{{{0.5f, 0.5f, 1.0f}, {0.6f, 0.5f, unset}, {0.5f, 0.6f, 1.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_NOT_FINITE);
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == CARD_UV_TRI_NO_ALPHA);
        // an unset coordinate too
        c[1] = {unset, unset, 1.0f};
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == (CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_NO_ALPHA));
    }
    // clamp keeps large coordinates as they are (no shift)
    {
        const std::array<CardCorner, 3> c{{{5.0f, 0.5f, 1.0f}, {5.5f, 0.5f, 1.0f}, {5.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, false);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == (CARD_UV_TRI_WIDE | CARD_UV_TRI_NO_ALPHA));
        CHECK(out[0].u == 5.0f && out[1].u == 5.5f);
        CHECK((w[3] & 0xffffffu) == 0xffffffu);
    }
    // not finite: marked, not shifted
    {
        const std::array<CardCorner, 3> c{{{std::nanf(""), 0.5f, 1.0f}, {5.5f, 0.5f, 1.0f}, {5.0f, 1.0f, 1.0f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(w, out, flags);
        CHECK(flags == CARD_UV_TRI_NOT_FINITE);
        CHECK(out[0].u != out[0].u);
        CHECK(out[1].u == 5.5f);
    }
    // the layout: words 0-2 corner (u low half, v high half), word 3 alphas and flags
    {
        const std::array<CardCorner, 3> c{{{0.5f, 0.25f, 0.0f}, {1.0f, 0.75f, 1.0f}, {0.5f, 1.5f, 0.5f}}};
        const auto w = CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true);
        CHECK(sizeof(w) == CARD_UV_RECORD_BYTES);
        CHECK(w[0] == (0x3800u | (0x3400u << 16)));
        CHECK(w[1] == (0x3c00u | (0x3a00u << 16)));
        CHECK(w[2] == (0x3800u | (0x3e00u << 16)));
        // 0.5 is 127.5 steps: off the 8-bit steps, so marked rounded
        CHECK(w[3] == (0u | (255u << 8) | (128u << 16) |
                       (std::uint32_t(CARD_UV_TRI_ALPHA_ROUNDED) << CARD_UV_FLAGS_SHIFT)));
    }
    // the affine comes first
    {
        const CardCorner k = CardApplyAffine({0.5f, 2.0f, 0.3f}, {2.0f, 0.5f, 0.25f, -1.0f});
        CHECK(k.u == 1.25f && k.v == 0.0f && k.a == 0.3f);
    }
}

// R7: the alpha factor in 8 bits. The game's A = texel alpha * the interpolated factor; a ray's
// A = texel alpha * the interpolation of the stored factor. Texel alphas are t / 255 (BC1 gives 0
// or 1, BC7 decodes to 8 bits).
void TestAlphaFactorBits() {
    // the marks: exact steps none, between steps rounded, outside [0, 1] range
    for (int k = 0; k <= 255; ++k) {
        CHECK(CardAlphaMarks(float(k) / 255.0f) == 0u);
        if (k < 255) {
            CHECK(CardAlphaMarks((float(k) + 0.5f) / 255.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
            CHECK(CardAlphaMarks((float(k) + 0.01f) / 255.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        }
    }
    CHECK(CardAlphaMarks(-0.001f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(1.001f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(-0.0f) == 0u);
    // R7-b: the range test has the grid's tolerance: 1 + 1 ulp and -1e-9 are not marked (their
    // clamp moves them by less than 2.4e-7); a little farther out is
    CHECK(CardAlphaMarks(std::nextafter(1.0f, 2.0f)) == 0u);
    CHECK(CardAlphaMarks(-1e-9f) == 0u);
    CHECK(CardAlphaMarks(1.0f + 1e-6f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaMarks(-1e-6f) == CARD_UV_TRI_ALPHA_RANGE);
    CHECK(CardAlphaRangeTolerance > 2.3e-7f && CardAlphaRangeTolerance < 2.5e-7f);
    // R7-a: the grid tolerance is 2^-14 of a step. 3e-6 below 50 / 255 (7.65e-4 of a step) is
    // marked: unmarked, unorm8 would store 50 and a ray would keep what the game drops (texel 1,
    // reference 50 / 255). 2^-12 of a step off is marked too; a few ulps off is not.
    CHECK(CARD_UV_ALPHA_GRID_EPS == 1.0 / 16384.0);
    {
        const float a = 50.0f / 255.0f - 3e-6f;
        CHECK(CardAlphaMarks(a) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(!CardKeeps(1.0f * a, 50.0f / 255.0f, CardOp::GreaterEqual, true)); // the game drops
        CHECK(CardUnorm8(a) == 50u);                                            // stored as 50
    }
    for (int k = 1; k < 255; ++k) {
        const float step = 1.0f / 255.0f;
        CHECK(CardAlphaMarks(float(k) / 255.0f + step / 4096.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(CardAlphaMarks(float(k) / 255.0f - step / 4096.0f) == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(CardAlphaMarks(std::nextafter(std::nextafter(float(k) / 255.0f, 2.0f), 2.0f)) == 0u);
    }
    // a factor a vertex shader made as k / 255 in another order of operations (one ulp off)
    // is still on the step
    for (int k = 1; k < 255; ++k) {
        const float a = float(k) / 255.0f;
        CHECK(CardAlphaMarks(std::nextafter(a, 2.0f)) == 0u);
        CHECK(CardAlphaMarks(std::nextafter(a, -1.0f)) == 0u);
    }
    // the record's flags: range and rounded per triangle, only with an alpha factor
    {
        std::array<CardCorner, 3> c{{{0.5f, 0.5f, 1.0f}, {0.6f, 0.5f, 50.0f / 255.0f}, {0.5f, 0.6f, 0.0f}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == 0);
        c[2].a = 1.25f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_RANGE);
        CHECK(out[2].a == 1.0f); // clamped: why a reader takes it as no card data
        c[2].a = -0.25f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_RANGE);
        c[2].a = 49.7f / 255.0f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        c[1].a = 2.0f;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == (CARD_UV_TRI_ALPHA_RANGE | CARD_UV_TRI_ALPHA_ROUNDED));
        // without an alpha factor the values are not looked at
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, false), out, flags);
        CHECK(flags == CARD_UV_TRI_NO_ALPHA);
    }

    std::mt19937 rng(7);
    std::uniform_int_distribution<int> step(0, 255);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    const float refs[] = {50.0f / 255.0f, 0.2f, 0.3f, 0.5f, 128.0f / 255.0f, 0.75f};
    const auto weights = [&](float& b0, float& b1, float& b2) {
        b0 = unit(rng);
        b1 = unit(rng) * (1.0f - b0);
        b2 = 1.0f - b0 - b1;
    };
    // Factors on the 8-bit steps: the stored factor is the same float, so a ray's A is the
    // game's A bit for bit and every decision is the same (the reference too: 50 / 255).
    int decisions = 0;
    for (int i = 0; i < 200000; ++i) {
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            k = {unit(rng), unit(rng), float(step(rng)) / 255.0f};
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK((flags & (CARD_UV_TRI_ALPHA_RANGE | CARD_UV_TRI_ALPHA_ROUNDED)) == 0);
        float b0, b1, b2;
        weights(b0, b1, b2);
        const float texel = float(step(rng)) / 255.0f;
        const float game = texel * (b0 * c[0].a + b1 * c[1].a + b2 * c[2].a);
        const float ray = texel * (b0 * out[0].a + b1 * out[1].a + b2 * out[2].a);
        CHECK(game == ray);
        for (const float ref : refs) {
            CHECK(CardKeeps(game, ref, CardOp::GreaterEqual, true) == CardKeeps(ray, ref, CardOp::GreaterEqual, true));
            ++decisions;
        }
    }
    CHECK(decisions == 200000 * int(std::size(refs)));
    // Factors between the steps: marked rounded; the difference is at most texel * 0.5 / 255
    // (and float rounding), and only texels that close to the reference can change side.
    int flipped = 0;
    for (int i = 0; i < 200000; ++i) {
        std::array<CardCorner, 3> c{};
        for (CardCorner& k : c) {
            // a quarter to three quarters of a step past k / 255: off the steps, in [0, 1]
            k = {unit(rng), unit(rng), (float(step(rng) % 255) + 0.25f + 0.5f * unit(rng)) / 255.0f};
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        float b0, b1, b2;
        weights(b0, b1, b2);
        const float texel = float(step(rng)) / 255.0f;
        const float game = texel * (b0 * c[0].a + b1 * c[1].a + b2 * c[2].a);
        const float ray = texel * (b0 * out[0].a + b1 * out[1].a + b2 * out[2].a);
        const float bound = texel * 0.5f / 255.0f + 1e-6f;
        CHECK(std::abs(game - ray) <= bound);
        for (const float ref : refs) {
            if (CardKeeps(game, ref, CardOp::GreaterEqual, true) != CardKeeps(ray, ref, CardOp::GreaterEqual, true)) {
                ++flipped;
                CHECK(std::abs(game - ref) <= bound);
            }
        }
    }
    CHECK(flipped > 0); // it happens: why the triangle is marked
    // The example of rt_card_alpha.md: texel alpha 1, factor 49.7 / 255 at all three corners,
    // reference 50 / 255: the game drops it, the stored 50 / 255 keeps it.
    {
        const float a = 49.7f / 255.0f;
        const float ref = 50.0f / 255.0f;
        const std::array<CardCorner, 3> c{{{0.0f, 0.0f, a}, {1.0f, 0.0f, a}, {0.0f, 1.0f, a}}};
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(c, CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true), out, flags);
        CHECK(flags == CARD_UV_TRI_ALPHA_ROUNDED);
        CHECK(!CardKeeps(1.0f * a, ref, CardOp::GreaterEqual, true));
        CHECK(CardKeeps(1.0f * out[0].a, ref, CardOp::GreaterEqual, true));
    }
}

void TestPushAndStats() {
    CardUvPush p;
    CHECK(sizeof(p) == 48);
    const std::uint32_t f = CardPushFlags(CARD_UV_MODE_MIRROR, CARD_UV_MODE_CLAMP, true, 3);
    CHECK((f & 3u) == CARD_UV_MODE_MIRROR);
    CHECK(((f >> CARD_UV_PUSH_MODE_V_SHIFT) & 3u) == CARD_UV_MODE_CLAMP);
    CHECK((f & CARD_UV_PUSH_HAS_ALPHA) != 0);
    CHECK(((f >> CARD_UV_PUSH_STAT_SHIFT) & 7u) == 3u);
    CHECK(CardPushFlags(0, 0, false, 0) == 0);
    CHECK(CARD_UV_STAT_SLOTS + 1 <= 8); // slot + 1 fits three bits

    // keys keep the order of floats
    const float vals[] = {-INFINITY, -1e9f, -2.0f, -0.5f, -0.0f, 0.0f, 1e-30f, 0.5f, 2.0f, 1e9f, INFINITY};
    for (std::size_t i = 0; i + 1 < std::size(vals); ++i) {
        CHECK(CardStatKey(vals[i]) <= CardStatKey(vals[i + 1]));
        CHECK(CardStatValue(CardStatKey(vals[i])) == vals[i]);
    }
    CHECK(CardStatKey(-1.0f) < CardStatKey(1.0f));
    // a slot as the shader fills it: min as atomicMax(~key), max as atomicMax(key)
    std::uint32_t w[CARD_UV_STAT_WORDS] = {};
    CHECK(!CardReadStat(w).any);
    const float us[] = {0.25f, -3.0f, 2.5f};
    for (float u : us) {
        w[0] = std::max(w[0], ~CardStatKey(u));
        w[3] = std::max(w[3], CardStatKey(u));
        w[1] = std::max(w[1], ~CardStatKey(u * 2));
        w[4] = std::max(w[4], CardStatKey(u * 2));
        w[2] = std::max(w[2], ~CardStatKey(0.5f));
        w[5] = std::max(w[5], CardStatKey(0.5f));
    }
    w[6] = 2;
    w[7] = 1;
    w[8] = 4;
    w[9] = 5;
    const CardStat s = CardReadStat(w);
    CHECK(s.any && s.umin == -3.0f && s.umax == 2.5f && s.vmin == -6.0f && s.vmax == 5.0f &&
          s.amin == 0.5f && s.amax == 0.5f && s.wide == 2 && s.not_finite == 1 &&
          s.alpha_range == 4 && s.alpha_rounded == 5);
    // the shader takes atomicMax for the bounds, atomicAdd for the counts
    CHECK(CARD_UV_STAT_WORDS == 10 && CARD_UV_STAT_MAX_WORDS == 6);
    CHECK(CARD_UV_STAT_WORDS <= CARD_UV_GROUP); // one thread a word zeroes and adds the group's
    // the flags fit the record's 8 bits
    CHECK(((CARD_UV_TRI_WIDE | CARD_UV_TRI_NO_ALPHA | CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_ALPHA_RANGE |
            CARD_UV_TRI_ALPHA_ROUNDED) >> 8) == 0);
}

CardDraw MakeDraw(bool camera, std::uint64_t ps, float scale, float ref) {
    CardDraw d;
    d.valid = true;
    d.camera = camera;
    d.ps_hash = ps;
    d.selector = PackCardSelector({4, 0, 1, 2, 3, true});
    d.affine = {scale, scale, 0.0f, 0.0f};
    d.reference = ref;
    d.nonzero = true;
    d.tsharp = {1, 2, 3, 4, 5, 6, 7, 8};
    CardFinishHashes(d);
    return d;
}

void TestStates() {
    // hashes tell the parts apart (a, b, c and scroll are sun shadow pass cards)
    CardDraw a = MakeDraw(false, 10, 1.0f, 0.5f);
    CardDraw b = MakeDraw(false, 10, 1.0f, 0.6f);
    CardDraw c = MakeDraw(false, 10, 2.0f, 0.5f);
    CHECK(a.uv_hash == b.uv_hash && a.constants_hash != b.constants_hash);
    CHECK(a.uv_hash != c.uv_hash);
    CardDraw t = a;
    t.tsharp[3] = 99;
    CardFinishHashes(t);
    CHECK(t.uv_hash == a.uv_hash && t.constants_hash != a.constants_hash);
    t = a;
    t.mode_u = CARD_UV_MODE_MIRROR;
    CardFinishHashes(t);
    CHECK(t.uv_hash != a.uv_hash);
    // the offset is not the pool's: a moving offset changes the constants, not the coordinates
    CardDraw scroll = a;
    scroll.affine[2] = 0.375f;
    scroll.affine[3] = -2.5f;
    CardFinishHashes(scroll);
    CHECK(scroll.uv_hash == a.uv_hash && scroll.constants_hash != a.constants_hash);
    CHECK((CardPoolAffine(scroll.affine) == std::array<float, 4>{1.0f, 1.0f, 0.0f, 0.0f}));
    CHECK((CardPoolAffine({2.0f, 0.5f, 7.0f, 9.0f}) == std::array<float, 4>{2.0f, 0.5f, 0.0f, 0.0f}));
    // and adding the offset to the pooled (scaled, shifted) corner samples the texel the game
    // samples: the difference is whole repeats (wrap) or pairs (mirror)
    for (const std::uint32_t mode : {std::uint32_t(CARD_UV_MODE_WRAP), std::uint32_t(CARD_UV_MODE_MIRROR)}) {
        const std::array<float, 4> affine{2.0f, 2.0f, 0.375f, -2.5f};
        std::array<CardCorner, 3> raw{{{3.25f, 1.5f, 1.0f}, {3.5f, 1.75f, 1.0f}, {3.25f, 2.0f, 1.0f}}};
        std::array<CardCorner, 3> pooled{};
        for (std::size_t k = 0; k < 3; ++k) {
            pooled[k] = CardApplyAffine(raw[k], CardPoolAffine(affine));
        }
        std::array<CardCorner, 3> out{};
        std::uint32_t flags = 0;
        CardUnpackTriangle(CardPackTriangle(pooled, mode, mode, false), out, flags);
        const float period = mode == CARD_UV_MODE_MIRROR ? 2.0f : 1.0f;
        for (std::size_t k = 0; k < 3; ++k) {
            const CardCorner game = CardApplyAffine(raw[k], affine);
            const float du = (out[k].u + affine[2]) - game.u;
            const float dv = (out[k].v + affine[3]) - game.v;
            CHECK(std::fmod(du, period) == 0.0f && std::fmod(dv, period) == 0.0f);
        }
    }

    // R4-c: the pixel shader is in uv_hash: two passes' cards with the same selector, scale and
    // modes have different uv_hash, so a capture made for one is never Ready for the other
    {
        const CardDraw sun = MakeDraw(false, 10, 1.0f, 0.5f);
        const CardDraw camera = MakeDraw(true, 20, 1.0f, 0.5f);
        CHECK(sun.selector == camera.selector && sun.affine == camera.affine);
        CHECK(sun.uv_hash != camera.uv_hash);
        CHECK(MakeDraw(true, 10, 1.0f, 0.5f).uv_hash == sun.uv_hash); // the pass itself is not
    }
    // judge's items 3 and 7: the dither's coefficient, the reference's dwords and the fade flag
    // are constants (not coordinates)
    for (int part = 0; part < 4; ++part) {
        CardDraw k = a;
        if (part == 0) {
            k.dither_scale = -1.0f;
        } else if (part == 1) {
            k.ref_dwords[0] = 0.25f;
        } else if (part == 2) {
            k.ref_dwords[1] = 1.0f;
        } else {
            k.fade_left_out = true;
        }
        CardFinishHashes(k);
        CHECK(k.uv_hash == a.uv_hash && k.constants_hash != a.constants_hash);
    }

    // the sun shadow pass preferred (R4): CardTakes(have, have_camera, camera, stale, sun_gone)
    CHECK(CardTakes(false, false, false, false, false)); // no card: a sun card is taken
    CHECK(CardTakes(false, false, true, false, false));  // no card: a camera card is taken
    CHECK(CardTakes(true, false, false, false, false));  // a sun card replaces a sun card
    CHECK(CardTakes(true, true, false, false, false));   // a sun card replaces a camera card
    CHECK(CardTakes(true, true, true, false, false));    // a camera card replaces a camera card
    CHECK(!CardTakes(true, false, true, false, false));  // not a sun card the sun pass still gives
    CHECK(CardTakes(true, false, true, true, false));    // R4-b: a stale sun card gives way
    CHECK(CardTakes(true, false, true, false, true));    // R4-a: a sun card no longer given
    CHECK(CardTakes(true, false, false, true, true));    // a sun card always replaces

    constexpr std::uint64_t f = 100; // the frame of every draw below (the sun card stays given)
    CardUv e;
    CardDraw miss;
    miss.miss = CardMiss::Constants;
    CHECK(!CardNote(e, miss, f).taken);
    CHECK(e.state == CardUvState::NotCard && e.miss == CardMiss::Constants);
    CHECK(!CardStale(e)); // no card: waiting, not stale
    CHECK(e.passes == 0 && !CardBothDiffer(e));

    // a camera pass card first
    CardDraw cam = MakeDraw(true, 20, 1.0f, 0.45f);
    CardNoted n = CardNote(e, cam, f);
    CHECK(n.taken && n.coordinates && !n.other && !n.both);
    CHECK(e.state == CardUvState::Wanted && e.miss == CardMiss::None);
    CHECK(CardCaptureWanted(e, 0));
    CHECK(e.passes == 2 && e.pass_reference[1] == 0.45f && e.pass_ps_hash[1] == 20);
    CHECK(!CardBothDiffer(e)); // one pass only: nothing to compare
    // the sun shadow pass card replaces it (another pixel shader: coordinates again); the
    // entry now has both passes' references, once
    n = CardNote(e, a, f);
    CHECK(n.taken && n.coordinates && n.both);
    CHECK(!e.card.camera && e.state == CardUvState::Wanted);
    CHECK(e.passes == 3 && e.pass_reference[0] == 0.5f && e.pass_ps_hash[0] == 10);
    CHECK(CardBothDiffer(e)); // 0.5 and 0.45
    // a camera pass card no longer does, but its reference is kept for the log
    CardDraw cam_same = MakeDraw(true, 20, 1.0f, 0.5f);
    n = CardNote(e, cam_same, f);
    CHECK(!n.taken && !n.both);
    CHECK(e.card.ps_hash == 10 && e.pass_reference[1] == 0.5f && !CardBothDiffer(e));
    n = CardNote(e, cam, f);
    CHECK(!n.taken && !n.both && CardBothDiffer(e));
    CHECK(e.card.ps_hash == 10);
    // recorded, then ready once the GPU is past it
    CardRecorded(e, 77);
    CHECK(e.state == CardUvState::Pending && e.tick == 77);
    CHECK(!CardCaptureWanted(e, 0));
    CHECK(!CardSettle(e, false) && e.state == CardUvState::Pending);
    CHECK(CardSettle(e, true) && e.state == CardUvState::Ready);
    CHECK(!CardSettle(e, true));
    // the same card again: nothing
    n = CardNote(e, a, f);
    CHECK(n.taken && !n.coordinates && !n.other && e.state == CardUvState::Ready);
    // only the reference changed: counted, the pool keeps the UVs
    n = CardNote(e, b, f);
    CHECK(n.taken && !n.coordinates && n.other && e.state == CardUvState::Ready);
    // only the offset changed (scrolling UVs): the same, Ready stays
    n = CardNote(e, scroll, f);
    CHECK(n.taken && !n.coordinates && n.other && e.state == CardUvState::Ready);
    CHECK(e.card.affine[2] == 0.375f); // the card has the newest offset for its reader
    // CardGotRoom touches nothing but NoRoom
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Ready);
    {
        CardUv p = e;
        p.state = CardUvState::Pending;
        CardGotRoom(p);
        CHECK(p.state == CardUvState::Pending);
    }
    // stale: a sun shadow pass draw without card data after the sun shadow pass's card; a
    // camera pass draw without card data does not make it stale; the next sun card clears it
    CHECK(!CardStale(e));
    CardDraw lost;
    lost.camera = false;
    lost.miss = CardMiss::Constants;
    CHECK(!CardNote(e, lost, f).taken);
    CHECK(CardStale(e) && e.miss == CardMiss::Constants && e.state == CardUvState::Ready);
    n = CardNote(e, scroll, f);
    CHECK(n.taken && !CardStale(e));
    CardDraw cam_lost;
    cam_lost.camera = true;
    cam_lost.miss = CardMiss::OtherPermutation;
    CHECK(!CardNote(e, cam_lost, f).taken && !CardStale(e));
    // R4-b: a valid camera card while the sun card is stale: taken (the sun card gave way), not
    // stale any more; a later sun draw without card data is of the other pass then: no miss
    CHECK(!CardNote(e, lost, f).taken && CardStale(e));
    n = CardNote(e, cam, f);
    CHECK(n.taken && n.sun_gave_way && n.coordinates && e.card.camera && !CardStale(e));
    CHECK(e.state == CardUvState::Wanted); // another pixel shader: captured again
    CHECK(!CardNote(e, lost, f).taken && !CardStale(e) && e.card.camera);
    // the sun shadow pass gives a card again: taken back
    n = CardNote(e, b, f);
    CHECK(n.taken && !n.sun_gave_way && n.coordinates && !e.card.camera && !CardStale(e));
    // the scale changed: wanted again
    n = CardNote(e, c, f);
    CHECK(n.coordinates && e.state == CardUvState::Wanted && e.wait_frames == 0);
    // a draw of the other pass without card data later changes nothing of a card
    CHECK(!CardNote(e, cam_lost, f).taken && e.state == CardUvState::Wanted && e.miss == CardMiss::None);

    // waiting frames and the UV-only capture
    for (std::uint32_t i = 0; i + 1 < CardWaitFrames; ++i) {
        CardWaitFrame(e);
    }
    CHECK(!CardUvOnlyDue(e, 0));
    CardWaitFrame(e);
    CHECK(CardUvOnlyDue(e, 0));

    // no room: wait for the pool to change
    CardNoRoom(e, 5);
    CHECK(e.state == CardUvState::NoRoom);
    CHECK(!CardCaptureWanted(e, 5));
    CHECK(CardCaptureWanted(e, 6));
    // a new card while NoRoom keeps NoRoom (no block yet)
    n = CardNote(e, a, f);
    CHECK(n.coordinates && e.state == CardUvState::NoRoom);
    CardRecorded(e, 9); // not Wanted: no change
    CHECK(e.state == CardUvState::NoRoom);
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Wanted);
    CardGotRoom(e);
    CHECK(e.state == CardUvState::Wanted);

    CHECK(CardClassOf(true, true) == CardClass::Plant);
    CHECK(CardClassOf(false, true) == CardClass::Static);
    CHECK(CardClassOf(false, false) == CardClass::Static);
    CHECK(CardClassOf(true, false) == CardClass::SkinnedKept);
}

// R4-a, R4-b and the review's T-1: the orders in which the two passes' cards arrive. sun: a sun
// shadow pass card (ps 10), cam: a camera pass card (ps 20, another reference).
void TestSunOrders() {
    const CardDraw sun = MakeDraw(false, 10, 1.0f, 0.196078f);
    const CardDraw cam = MakeDraw(true, 20, 1.0f, 0.50196f);
    CardDraw sun_lost;
    sun_lost.camera = false;
    sun_lost.miss = CardMiss::Constants;
    CHECK(CardSunFrames == 17);
    {
        // camera then sun: the sun card replaces the camera card; the pair is said once
        CardUv e;
        CardNoted n = CardNote(e, cam, 1);
        CHECK(n.taken && e.card.camera && !n.both);
        n = CardNote(e, sun, 1);
        CHECK(n.taken && n.both && n.coordinates && !n.sun_gave_way && !e.card.camera);
        CHECK(e.sun_frame == 1 && e.pass_reference[1] == 0.50196f && e.pass_reference[0] == 0.196078f);
        // each pass's second reference dword (cb[21]) is kept for the log, taken or not
        CardDraw cam21 = cam;
        cam21.ref_dwords = {0.392156f, 1.0f};
        CardFinishHashes(cam21);
        CHECK(!CardNote(e, cam21, 2).taken);
        CHECK(e.pass_ref2[1] == 1.0f && e.pass_ref2[0] == 0.0f);
    }
    {
        // sun then camera (T-1 D): the camera card is not taken, but completes the pair
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        const CardNoted n = CardNote(e, cam, 1);
        CHECK(!n.taken && n.both && !e.card.camera && e.passes == 3);
    }
    {
        // camera card first, then a sun draw without card data (T-1 C): not stale (another pass)
        CardUv e;
        CHECK(CardNote(e, cam, 1).taken);
        CHECK(!CardNote(e, sun_lost, 1).taken);
        CHECK(!CardStale(e) && e.miss == CardMiss::None && e.card.camera);
    }
    {
        // sun stops (R4-a): the camera pass keeps drawing; the sun card holds for CardSunFrames
        // frames after its last sun draw, then the next camera card takes over (once)
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        for (std::uint64_t frame = 2; frame <= 1 + CardSunFrames; ++frame) {
            CHECK(!CardSunGone(e, frame));
            const CardNoted n = CardNote(e, cam, frame);
            CHECK(!n.taken && !e.card.camera);
        }
        CHECK(CardSunGone(e, 2 + CardSunFrames));
        CardNoted n = CardNote(e, cam, 2 + CardSunFrames);
        CHECK(n.taken && n.sun_gave_way && n.coordinates && e.card.camera);
        CHECK(!CardSunGone(e, 2 + CardSunFrames)); // a camera card is never "gone"
        n = CardNote(e, cam, 3 + CardSunFrames);
        CHECK(n.taken && !n.sun_gave_way && !n.coordinates); // the same card again: nothing new
        // sun returns: its card is taken back at once, and holds again
        n = CardNote(e, sun, 40);
        CHECK(n.taken && !n.sun_gave_way && n.coordinates && !e.card.camera && e.sun_frame == 40);
        CHECK(!CardNote(e, cam, 41).taken && !e.card.camera);
        // no draw at all for long, then a camera draw: the sun card gives way
        CHECK(CardSunGone(e, 1000));
        CHECK(CardNote(e, cam, 1000).taken && e.card.camera);
    }
    {
        // a sun shadow pass card that stops (no draw of either pass): counted as gone, kept
        CardUv e;
        CHECK(CardNote(e, sun, 5).taken);
        CHECK(!CardSunGone(e, 5 + CardSunFrames) && CardSunGone(e, 6 + CardSunFrames));
        CHECK(!e.card.camera);
    }
    {
        // r14's longest cascade period (16): the sun pass draws the entry every 16th frame, the
        // camera pass every frame. The card stays the sun's: no hand-over back and forth.
        CardUv e;
        int taken_camera = 0;
        for (std::uint64_t frame = 1; frame <= 400; ++frame) {
            if (frame % 16 == 1) {
                CHECK(CardNote(e, sun, frame).taken);
            }
            taken_camera += CardNote(e, cam, frame).taken ? 1 : 0;
            CHECK(!e.card.camera);
        }
        CHECK(taken_camera == 0);
    }
    {
        // a sun shadow pass card lost for good (stale) while the camera's stays valid (R4-b):
        // the next camera card is taken at once, before CardSunFrames
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        CHECK(!CardNote(e, sun_lost, 2).taken && CardStale(e));
        const CardNoted n = CardNote(e, cam, 2);
        CHECK(n.taken && n.sun_gave_way && e.card.camera && !CardStale(e));
    }
    {
        // a sun draw with card data refreshes the frame whether or not its card is taken
        CardUv e;
        CHECK(CardNote(e, sun, 1).taken);
        CHECK(CardNote(e, sun, 10).taken && e.sun_frame == 10);
        CHECK(!CardNote(e, cam, 27).taken); // 27 = 10 + 17: still given
        CHECK(CardNote(e, cam, 28).taken);
        // a camera draw does not refresh it
        CHECK(e.sun_frame == 10);
    }
}

void TestFreesAndSlots() {
    std::vector<CardFree> frees{{1, 1, 10}, {2, 2, 20}, {3, 3, 30}};
    std::vector<std::uint64_t> released;
    std::size_t n = CardReleaseFrees(
        frees, [](std::uint64_t tick) { return tick <= 20; },
        [&](const CardFree& f) { released.push_back(f.block); });
    CHECK(n == 2 && frees.size() == 1 && frees[0].block == 3);
    CHECK((released == std::vector<std::uint64_t>{1, 2}));
    n = CardReleaseFrees(frees, [](std::uint64_t) { return false; }, [&](const CardFree&) { CHECK(false); });
    CHECK(n == 0 && frees.size() == 1);

    CardSlots slots;
    CHECK(slots.Take() == 1);
    CHECK(slots.Take() == 2);
    CHECK(slots.Take() == 3);
    slots.Give(2);
    slots.Give(0); // none: ignored
    CHECK(slots.Take() == 2);
    CHECK(slots.Take() == 4);
    slots.next = CardSlotsMost - 1;
    CHECK(slots.Take() == CardSlotsMost - 1);
    CHECK(slots.Take() == 0);
    slots.Give(7);
    CHECK(slots.Take() == 7);
}

// The knob off: the engine makes no card data (no CaptureUv pipeline), so a draw's card stays the
// default, and an entry's part the default: nothing is wanted, recorded or due, and a default
// card is never taken.
void TestOffPath() {
    const CardDraw none;
    CHECK(!none.valid && none.miss == CardMiss::None && none.selector == 0);
    CardSelector s;
    CHECK(!UnpackCardSelector(none.selector, s)); // word 7 stays 0: the capture stores nothing
    CardUv e;
    CHECK(e.state == CardUvState::NotCard);
    CHECK(!CardCaptureWanted(e, 0) && !CardCaptureWanted(e, 1));
    CHECK(!CardUvOnlyDue(e, 0));
    CardWaitFrame(e);
    CHECK(e.wait_frames == 0);
    const CardNoted n = CardNote(e, none, 1);
    CHECK(!n.taken && !n.coordinates && !n.other && e.state == CardUvState::NotCard);
    CHECK(!n.both && e.passes == 0); // no reference is kept for a draw without card data
    CardRecorded(e, 5);
    CHECK(e.state == CardUvState::NotCard && e.tick == 0);
    CHECK(!CardSettle(e, true));
}

void TestAxisModes() {
    CHECK(CardAxisMode(0) == CARD_UV_MODE_WRAP);
    CHECK(CardAxisMode(1) == CARD_UV_MODE_MIRROR);
    for (std::uint32_t m = 2; m < 8; ++m) {
        CHECK(CardAxisMode(m) == CARD_UV_MODE_CLAMP);
    }
}

} // namespace

int main() {
    TestKnob();
    TestSizes();
    TestSelector();
    TestAlphaRule();
    TestDitherApart();
    TestGuard();
    TestHalf();
    TestPack();
    TestAlphaFactorBits();
    TestPushAndStats();
    TestStates();
    TestSunOrders();
    TestFreesAndSlots();
    TestAxisModes();
    TestOffPath();
    if (failures != 0) {
        std::printf("rt-card-uv-test: %d failed\n", failures);
        return 1;
    }
    std::printf("rt-card-uv-test: all passed\n");
    return 0;
}
""",
    DOCS + "rt_card_alpha.md": r"""# Ray traced foliage shadows: the card UVs (stage 2, BB_RT_CARD_ALPHA)

Status: a draft (r54). Off by default. It changes no picture, no ray, no mask, no TLAS and no
BLAS. It only gathers what a later stage needs.

Gate: passed. The r50c game log of 2026-11-15 (`BB_RT_CARD_ALPHA_LOG=1`, 100 s, the plant spot
and a character) met the GO numbers: 11 of 11 discarding pixel shaders repeatable with the
draw's constants; with constants plants 4 of 4, hair and cloth (kept whole, a skeleton) 5 of 5,
static 2 of 2; 769,976 draws, 100 % CPU-written (0 in place, 0 GPU-written, 0 unreadable, 0
another permutation); every dither 4x4; three shaders (dbeccd9c, 1c3953c6, 92852ef3) checked by
hand; no `(r50` line with the knob unset. References `cb[20] + 0.5 * cb[21]` seen: 0.196078,
0.50196, 0.0392153 and 0.892156 in the camera pass, 0.196078 in the sun shadow pass.

## The rule a ray will repeat

The game drops a pixel where `cb[20] > cb[21] * (dither - 0.5) + A` or `A * fade == 0`, with
`A` = texel alpha times the vertex colour's alpha. Its sun shadow pass has no dither and no fade.
A ray repeats that form: it keeps a hit where `A >= cb[20] + 0.5 * cb[21]` and, where the record
has the nonzero term, `A != 0`.

- The per-instance fade is left out (r50c's rule). It is a float the pixel shader reads from a
  storage buffer at the instance's row. Leaving it out changes the result only where the fade is
  0 (or not a number). So an instance with fade 0, which the game hides, still casts its shadow.
  How often that happens is not measured.
- The `A != 0` test stays its own check. `cb[20] + 0.5 * cb[21] > 0` is not given for every
  material; where it is not, only this test drops the fully transparent texels.
- The camera pass's dither is taken as 0 (the strictest end where `cb[21] > 0`). Its coefficient
  (`-cb[21]`) is kept apart in the card (`CardDraw::dither_scale`), with both reference dwords,
  so a later stage can choose D = 0, the mean (`cb[20]`) or a per-ray dither. With a per-ray
  dither the threshold can drop to 0 or below; the `A != 0` test then still drops what it must.
- Any finite reference is taken; there is no plausibility band (the log saw 0.039 to 0.892).
  Only a value that is not finite gives no card.
- An entry drawn by both passes (hair, cloth, characters) takes the sun shadow pass's card while
  that pass still gives one: that pass is the game's own shadow test, with that pass's
  constants. The camera pass's reference can differ (its `cb[21]` also scales the dither). Both
  references are logged (below). The sun card gives way to the camera pass's card when the sun
  pass's last draw of the entry had no card data (stale), or when no sun shadow pass draw gave
  one for more than 17 frames (indoors, at night, out of the cascades). 17 is r14's longest hold
  window for a skipped sun cascade (`MaxHoldPeriod - 1 + HoldMarginFrames`): the game draws a
  cascade only every few frames, and a shorter wait would hand the card over and back at each
  skipped cascade (each hand-over captures the UVs again). When the sun pass gives a card again,
  it is taken back.
- This stage reads no ignored factor: `RepeatableWithConstants()` decides which records count.

## Why

A ray cannot run the game's pixel shader. A cut-out card (a leaf, a weed, a strand of hair) is
a quad whose texture alpha decides which pixels are kept. Today a lamp ray hits the whole quad,
so plants threw rectangles of shadow; r46 leaves such cards out of lamp rays instead. To shadow
by the leaf's shape, a ray at a card's hit must repeat the game's alpha test. That needs, per
triangle, the texture coordinates of its corners and the alpha factor the shader multiplies in.
This stage captures them.

## The knobs

| Variable | Values | What it does |
|---|---|---|
| `BB_RT_CARD_ALPHA` | unset, `0`: off. `1`: on. Anything else: off, said once in the log. | Read once at start. With `1` the cut-out cards' UVs are captured into a pool (this page). Later stages will take levels above 1. |
| `BB_RT_CARD_ALPHA_LOG` | `1`: on. Otherwise off. | The analysis log lines of r50, r50b and r50c. With `BB_RT_CARD_ALPHA=1` alone the analysis runs but prints none of them. |

Either knob makes the cut-out analysis run. Then the shader cache leaves discarding pixel
shaders to compile in play (a short stutter the first time each is drawn). A cache tag (stage 3)
is to remove that before the option is offered to players.

## What runs with the knob on

1. Pipelines. Every position capture vertex shader gets a second store
   (`MotionVectors::CaptureUv`, the value 4, bit 2 of the pipeline key's `motion_vectors`). Its
   address block has one more address: the ring. Only the recompiler's capture
   (`EmitVertexCapture`, `EmitCardUvStore`) has this store, so a capture vertex shader with
   `CaptureUv` is never replaced by the lifter's module (`CompileModule`; the lifter is on by
   default). With the knob on, every ray traced caster's capture vertex shader is therefore built
   by the recompiler; its cost against the lifter's is not measured.
2. Draws. For each draw of a discarding pixel shader in the camera pass or a sun shadow pass,
   `ResolveCardDraw` (vk_rasterizer_effects.cpp) resolves the r50b record of the shader with the
   draw's own values: which vertex shader outputs hold the coordinates and the alpha factor, the
   coordinate scale and offset, the reference (`cb[20] + 0.5 * cb[21]` for the game's materials: the
   sun shadow pass form, the camera pass's dither taken as 0), the dither's coefficient and the
   two reference dwords apart, the alpha texture's T# and its sampler's repeat. Which buffer and
   dword each value is in comes from the record, never from fixed numbers (the log saw cb3,
   cb4 and cb1 for the reference, cb1, cb2 and cb0 for the scale and offset). A dword is read on
   the CPU only from the shader's user data or from a guest constant buffer the shader does not
   write, at a valid V#, inside the buffer and a GPU mapping, and in no region the GPU wrote. Any
   other dword: the draw has no card data. A record that samples one fixed layer of an array
   gives no card data either (no layer is carried yet). A record of a cached shader made with
   another image or buffer count than the draw's is counted apart ("a record of other
   resources") from "no record".
3. Entries. The ray tracing entry keeps the card data (the sun shadow pass's while that pass
   gives one, see above; the first time an entry has card data from both passes, one line prints
   both references).
   When its coordinates or scale are new, one capture of the entry also stores per vertex u, v
   and the alpha factor (12 bytes) into the ring. At most 64 entries a frame, and only a draw of
   the card's own pixel shader (the pixel shader is part of the coordinates' hash, so a capture
   made for one pass's card is never taken for the other's). An entry drawn 8 frames without
   such a capture gets a capture for the UVs alone (within half the frame's capture params and
   positions). A later draw of the card's pass without card data marks the entry "stale"
   (counted; a later stage must not use a stale card; a stale sun card gives way to the next
   camera pass card).
4. The expand pass (`rt_card_uv.comp`, in the ray tracing geometry pass) turns the ring's corners
   into one 16-byte record per BLAS primitive in the entry's block of the pool:
   words 0-2 the corners' (u, v) as half floats: the input times the draw's scale, minus a shift
   by whole repeats; word 3 the corners' alpha factors as 8-bit values and flags (wide: a
   coordinate 4.0 or more from 0 after the shift; no alpha factor; not finite; an alpha factor
   outside [0, 1] by more than 2.4e-7; an alpha factor more than 2^-14 of a step off the 8-bit
   steps). The draw's offset is not in the pool:
   its reader adds the entry's card offset, so scrolling UVs do not capture again.

   The alpha factor in 8 bits. A vertex colour stored as 8 bits gives k / 255 at every corner.
   A factor within 2^-14 of a step of k / 255 (2.4e-7 in alpha: a few float ulps) is not marked
   and is stored as k / 255. Then a ray keeps and drops what the game does, except for an `A`
   within texel alpha x 2.4e-7 of the reference, and up to float rounding of the interpolation,
   which a ray and the raster may do differently. It is close, not exact. A factor below 0 or
   above 1 by more than 2.4e-7 is clamped: the triangle is marked and a reader takes it as one
   without card data (1 + 1 ulp is not marked). A factor in [0, 1] farther from a step is rounded
   by at most half a step, so a ray's `A` differs from the game's by at most texel alpha x 0.5 /
   255 (0.00196). A texel that close to the reference can then fall on the other side: for
   example a texel alpha of 1, a factor of 49.7 / 255 (or 50 / 255 - 3e-6) at all three corners
   and the reference 50 / 255 (0.196078, the one logged for the sun shadow pass): the game drops
   it, the stored factor 50 / 255 keeps it. Such triangles are marked and counted; whether to
   widen the record is decided from the log.
5. The ring. Before the first capture may store UVs, the ring is filled with NaN; after each
   expand pass the part used is filled again. The part used by captures drawn after a frame's
   last expand pass (their builds are dropped) is filled by the next one. A vertex no capture
   stored (or a value the vertex shader cannot give) then reads as NaN and its triangle is
   marked not finite, never kept with an old or a zero value. One window stays: a capture of
   the next frame drawn before that fill whose draw skips a vertex index a dropped capture wrote.

Nothing reads the pool yet.

## Memory

| What | Size | When |
|---|---|---|
| Ring | 24 MiB (2M vertices x 12 B) | at start, knob on |
| Pool | 64 MiB (4M triangles x 16 B) | at the first card that gets UVs |
| Stat slots and their readback | 160 B + 160 B (4 slots x 10 words) | at start, knob on |
| Address blocks | +8 B each (24 and 40 B instead of 16 and 32) | at start, knob on |
| Per entry and per draw description | +8 B each (a pointer) | always (null with the knob off) |
| Per cut-out entry | 208 B on the heap (`sizeof(CardUvEntry)`, 64-bit build, measured with the test's compiler; 40 B of it the two passes' references and the sun card's frame) | knob on, once per entry |
| Lists of pending entries and freed blocks | 8 B and 24 B an element | knob on, grown as needed, kept |

The pool holds 16 B a triangle: 1M triangles of cards take 16 MiB. It is made once at 64 MiB
(4M triangles) and does not grow; an entry that does not fit gets no UVs and is counted as
"no room" (it tries again after a block is freed).

## The log (knob on)

Once per entry drawn by both passes (the first 32 such entries): `Ray tracing card UVs (r54):
drawn by both passes, key K (class): sun shadow pass ps P reference R (second dword X), camera
pass ps Q reference S (second dword Y, dither taken as 0), the same|they differ; the card is the
sun shadow|camera pass's`. The second dword is `cb[21]` for the game's materials.

Every 600 frames: `Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=1): ...` with the cut-out entries
by class (plants, static, skinned kept) and state (ready, pending, wanted, no room, no card data);
how many entries both passes draw, whose card they hold (sun shadow pass or camera pass) and how
many have another reference in the camera pass; the sun shadow pass cards no sun shadow pass
draw gave for more than 17 frames; the cards' constants (entries with a card, with the fade left
out, with a second reference dword not 0, the ranges of both reference dwords, the dithered
cards and the range of their dither coefficient); why entries have no card data, how many have
a stale card and why; the pool, the ring's peak and the counts since the last line (among them
the sun shadow pass cards that gave way to the camera pass's). Then up to four lines `Ray
tracing card UVs (r54): first entries, ...` with the coordinate (after the scale; no offset, no
shift) and alpha factor ranges of the first entries expanded since the last line, and per entry
the triangles with an alpha factor outside [0, 1], with one off the 8-bit steps, wide and not
finite.

With the knob unset no `(r54` line is printed.

## What the log must show

A standing test in the plant spot plus a character, 30-100 s, `BB_RT_CARD_ALPHA=1`,
`BB_RT_CARD_ALPHA_LOG=1`, ray tracing on:

- ready plants at least 80 % of the plant entries with a card;
- in the "first entries" lines: 0 not finite; u and v ranges finite and each span non-zero
  (a zero span on every entry means no store reached the ring); alpha factor range within
  [0, 1] (a GO check: 10 of the 11 shaders multiply a vertex alpha in) and 0 triangles with one
  outside [0, 1]; the count off the 8-bit steps noted (0 means every factor was within 2^-14 of
  a step of k / 255, so a ray's decision differs from the game's only for an `A` within about
  2.4e-7 of the reference; many mean a wider alpha is needed before stage 4); wide 0 or a small
  share;
- the "drawn by both passes" lines and count noted: "they differ" means the camera pass's
  material constants give another reference than the sun shadow pass's, which the card uses;
- the cards' constants: the first reference dword within what the r50c log saw (cb[20] 0.0392153
  to 0.50196), the second 0 to 1 (cb[21]); the dithered cards' coefficient -1 to 0; the fade left
  out on the camera pass cards (r50c's 9 shaders); a new value outside these is not an error
  (no plausibility band), but note it;
- pool MiB about triangles x 16 / 2^20;
- "stale" 0 when standing, and the "other constants changed" count 0 when standing; sun shadow
  pass cards not given again 0 outdoors in daylight and few given way (each hand-over captures
  again);
- the picture the same as with the knob unset; a run with both knobs unset prints no `(r54` line.

## Not done in this stage

The alpha layers and the debug view (stage 3), the lamp rays (stage 4), the decision point for a
lamp card map (4b), characters, hair and cloth (5), the sun and the bounced light (6), and the
cost levers (7).
""",
}

EMIT_CARD = r"""// bbport (r54_leaf-stage2): with the card UVs (MotionVectors::CaptureUv, BB_RT_CARD_ALPHA=1) a
// capture whose param names a place in the ring (word 1, the ring index + 1; 0: none) also
// stores per vertex what a cut-out pixel shader samples its alpha at and multiplies it by: two
// components of one output (u, v) and one of another (the alpha factor, 1.0 without one), which
// word 7 names (Vulkan::PackCardSelector: bits 0-4 the uv output, 5-6 and 7-8 its components,
// 9-13 the alpha factor's output, 14-15 its component, 16 an alpha factor at all, 31 set). The
// outputs are the ones this shader wrote, read back before the epilogue's other work; an output
// that is an integer, an array or the emulated clip distances is left out of the choice. Where
// the selector names an output this shader does not have or that is left out, or a component
// past the output's own
// ones, the value stored is MotionVectors::CaptureUvUnset (a NaN, CARD_UV_RING_UNSET), never a
// 0: the expand pass then marks the triangle not finite. (With clip distance emulation the
// clip distances may take a real output's slot, spirv_emit_context.cpp; that output then reads
// as not finite too.) No local variable may be declared here (past the function's first block):
// the choice is a chain of selects. Indexed draws may run a vertex more than once; every run
// stores the same values, as the position store above does. This is the recompiler's capture:
// a capture vertex shader with CaptureUv is never replaced by the lifter's (CompileModule).
static void EmitCardUvStore(EmitContext& ctx, Id ring_address, Id params, Id offsets, Id slot) {
    const Id u32_type = ctx.U32[1];
    const Id f32_type = ctx.F32[1];
    const Id bool_type = ctx.U1[1];
    const Id uv_word = ctx.OpCompositeExtract(u32_type, params, 1u);
    const Id selector = ctx.OpCompositeExtract(u32_type, offsets, 3u);
    const Id wanted = ctx.OpLogicalAnd(
        bool_type, ctx.OpINotEqual(bool_type, uv_word, ctx.u32_zero_value),
        ctx.OpINotEqual(bool_type, ctx.OpBitwiseAnd(u32_type, selector, ctx.ConstU32(0x80000000u)),
                        ctx.u32_zero_value));
    const Id uv_label = ctx.OpLabel();
    const Id uv_merge = ctx.OpLabel();
    ctx.OpSelectionMerge(uv_merge, spv::SelectionControlMask::MaskNone);
    ctx.OpBranchConditional(wanted, uv_label, uv_merge);
    ctx.AddLabel(uv_label);
    const auto field = [&](u32 offset, u32 count) {
        return ctx.OpBitFieldUExtract(u32_type, selector, ctx.ConstU32(offset), ctx.ConstU32(count));
    };
    const Id uv_out = field(0u, 5u);
    const Id comp_u = field(5u, 2u);
    const Id comp_v = field(7u, 2u);
    const Id alpha_out = field(9u, 5u);
    const Id alpha_comp = field(14u, 2u);
    const Id has_alpha = ctx.OpINotEqual(bool_type, field(16u, 1u), ctx.u32_zero_value);
    const Id one = ctx.Constant(f32_type, 1.0f);
    const Id unset = ctx.OpBitcast(f32_type, ctx.ConstU32(MotionVectors::CaptureUvUnset));
    const Id unset4 =
        ctx.OpCompositeConstruct(ctx.F32[4], std::array<Id, 4>{unset, unset, unset, unset});
    Id uv_vector = unset4;
    Id alpha_vector = unset4;
    for (u32 i = 0; i < IR::NumParams; ++i) {
        const auto& output = ctx.output_params[i];
        if (!Sirit::ValidId(output.id) || output.is_integer || output.is_array ||
            output.id.value == ctx.clip_distances.value || output.num_components < 1 ||
            output.num_components > 4) {
            continue;
        }
        const u32 n = output.num_components;
        const Id loaded = ctx.OpLoad(ctx.F32[n], output.id);
        Id vector = loaded;
        if (n != 4) {
            std::array<Id, 4> parts{unset, unset, unset, unset};
            for (u32 c = 0; c < n; ++c) {
                parts[c] = n == 1 ? loaded : ctx.OpCompositeExtract(f32_type, loaded, c);
            }
            vector = ctx.OpCompositeConstruct(ctx.F32[4], parts);
        }
        uv_vector = ctx.OpSelect(ctx.F32[4], ctx.OpIEqual(bool_type, uv_out, ctx.ConstU32(i)), vector,
                                 uv_vector);
        alpha_vector = ctx.OpSelect(ctx.F32[4], ctx.OpIEqual(bool_type, alpha_out, ctx.ConstU32(i)),
                                    vector, alpha_vector);
    }
    const Id u = ctx.OpVectorExtractDynamic(f32_type, uv_vector, comp_u);
    const Id v = ctx.OpVectorExtractDynamic(f32_type, uv_vector, comp_v);
    const Id a = ctx.OpSelect(f32_type, has_alpha,
                              ctx.OpVectorExtractDynamic(f32_type, alpha_vector, alpha_comp), one);
    const Id index = ctx.OpIAdd(u32_type, ctx.OpISub(u32_type, uv_word, ctx.ConstU32(1u)), slot);
    const Id base = ctx.OpIAdd(
        ctx.U64, ring_address,
        ctx.OpIMul(ctx.U64, ctx.OpUConvert(ctx.U64, index),
                   ctx.Constant(ctx.U64, u64(MotionVectors::CaptureUvStride))));
    const Id f32_ptr = ctx.TypePointer(spv::StorageClass::PhysicalStorageBuffer, f32_type);
    const std::array<Id, 3> values{u, v, a};
    for (u32 k = 0; k < 3; ++k) {
        const Id ptr = ctx.OpConvertUToPtr(
            f32_ptr, ctx.OpIAdd(ctx.U64, base, ctx.Constant(ctx.U64, u64(k * 4))));
        ctx.OpStore(ptr, values[k], spv::MemoryAccessMask::Aligned, 4u);
    }
    ctx.OpBranch(uv_merge);
    ctx.AddLabel(uv_merge);
}

"""
FX_CARD = r"""namespace {
// bbport (r54_leaf-stage2): the record's ops in the order the card data keeps them.
static_assert(u8(CardOp::Less) == u8(Shader::Info::Cutout::Op::Less) &&
              u8(CardOp::LessEqual) == u8(Shader::Info::Cutout::Op::LessEqual) &&
              u8(CardOp::Greater) == u8(Shader::Info::Cutout::Op::Greater) &&
              u8(CardOp::GreaterEqual) == u8(Shader::Info::Cutout::Op::GreaterEqual) &&
              u8(CardOp::Equal) == u8(Shader::Info::Cutout::Op::Equal) &&
              u8(CardOp::NotEqual) == u8(Shader::Info::Cutout::Op::NotEqual));

/// The guest memory as ReadCardBufferDword asks about it: the checks r50b's draw-time line makes
/// (LogCutoutConstants above), in the same order.
struct CardGuest {
    Core::MemoryManager& memory;
    VideoCore::BufferCache& buffer_cache;
    bool Mapped(u64 address, u64 size) {
        return memory.IsValidGpuMapping(address, size) && memory.ClampRangeSize(address, size) == size;
    }
    bool GpuModified(u64 address, u64 size) {
        return buffer_cache.IsRegionGpuModified(address, size);
    }
    bool InPlace(u64 address, u64 size) {
        return buffer_cache.IsInPlace(address, size);
    }
    u32 Read(u64 address) {
        u32 raw = 0;
        std::memcpy(&raw, reinterpret_cast<const void*>(address), sizeof(raw));
        return raw;
    }
};

/// bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1, a cut-out pixel shader's test as this draw
/// holds it (rt_card_uv.h, CardDraw): the record of its pixel shader (r50b: matched, repeatable
/// with the draw's constants, this permutation), the vertex shader outputs its inputs read (the
/// selector the capture stores by), the dwords the coordinates and the reference read (from
/// memory the GPU did not write only: a dword it wrote, or one bound in place, is not read and
/// the draw has no card data), the alpha texture's T# and its sampler's repeat. A plain value:
/// nothing in it points into the shader's Info or guest memory. miss says why not valid.
/// RepeatableWithConstants() alone decides which records count. Since r50c it accepts a record
/// whose nonzero term has an ignored factor that is a buffer load with one address a triangle
/// (the game's per-instance fade): that factor is left out, never read here, and ignored_kinds
/// is not looked at (CardKeeps says what leaving it out means); ignored_factor_terms only sets
/// CardDraw::fade_left_out, which the 600-frame line counts (judge's item 7).
CardDraw ResolveCardDraw(const AmdGpu::Regs& regs, const Shader::Info& ps, bool camera,
                         Core::MemoryManager& memory, VideoCore::BufferCache& buffer_cache) {
    namespace Opt = Shader::Optimization;
    using Cutout = Shader::Info::Cutout;
    using Ref = Cutout::Ref;
    CardDraw out;
    out.camera = camera;
    out.ps_hash = ps.pgm_hash;
    const Cutout* cut = &ps.cutout;
    if (cut->verdict == Cutout::Verdict::NotAnalysed) {
        cut = Opt::FindCutout(ps.pgm_hash); // a program from the cache: the first compile's
        if (!cut) {
            out.miss = CardMiss::NoRecord;
            return out;
        }
        // a record, but of another resource list: its dword and image indices are not this
        // draw's, so none is read (counted apart from "no record")
        if (cut->image_count != ps.images.size() || cut->buffer_count != ps.buffers.size()) {
            out.miss = CardMiss::OtherResources;
            return out;
        }
    }
    // A sample of one fixed layer (Layer::Immediate) is repeatable, but the card data has no
    // layer (stage 3 copies one 2D slice of the T#): no card for it until a stage carries one.
    if (!cut->RepeatableWithConstants() || cut->layer != Cutout::Layer::None) {
        out.miss = CardMiss::NotRepeatable;
        return out;
    }
    u32 default_mask = 0, flat_mask = 0;
    for (u32 i = 0; i < regs.num_interp && i < 32 && i < regs.ps_inputs.size(); ++i) {
        default_mask |= regs.ps_inputs[i].use_default ? 1u << i : 0u;
        flat_mask |= regs.ps_inputs[i].flat_shade ? 1u << i : 0u;
    }
    if (!Opt::CutoutSamePermutation(*cut, regs.num_interp, default_mask, flat_mask)) {
        out.miss = CardMiss::OtherPermutation;
        return out;
    }
    const auto input = [&regs](u32 i) {
        if (i >= regs.ps_inputs.size()) {
            return CardInput{0, true, false};
        }
        const AmdGpu::PsInputControl& control = regs.ps_inputs[i];
        return CardInput{u32(control.input_offset), control.use_default != 0,
                         control.flat_shade != 0};
    };
    const bool has_alpha = cut->alpha_input != Cutout::NoInput;
    CardSelector selector;
    if (!CardSelectorFor(input(cut->input), cut->comp_u, cut->comp_v, has_alpha,
                         has_alpha ? input(cut->alpha_input) : CardInput{}, cut->alpha_comp,
                         selector)) {
        out.miss = CardMiss::Inputs;
        return out;
    }
    // The dwords (CutoutDwords' order): every one the record names, the dither's coefficient
    // too (a camera pass draw that dithers: kept apart from the reference, CardDraw::dither_scale).
    // Slots come from the record, never fixed numbers.
    const auto dwords = Opt::CutoutDwords(*cut);
    CardRecordValues record;
    record.uv_scale = cut->uv_scale;
    record.uv_offset = cut->uv_offset;
    record.ref = cut->ref;
    record.ref_scale = cut->ref_scale;
    record.ref2_scale = cut->ref2_scale;
    record.dither = camera && cut->dither;
    record.dither_scale = cut->dither_scale;
    std::array<float, 7> values{};
    CardDwordState state = CardDwordState::Read;
    CardGuest guest{memory, buffer_cache};
    for (size_t i = 0; i < dwords.size(); ++i) {
        const Opt::CutoutDword& d = dwords[i];
        if (d.kind == Ref::Immediate || (i == CardDwordDither && !record.dither)) {
            continue;
        }
        record.named[i] = true;
        u32 raw = 0;
        CardDwordState s = CardDwordState::Unreadable;
        if (d.kind == Ref::UserData || d.kind == Ref::FlatUserData) {
            s = ReadCardUserDword(d.kind == Ref::UserData ? ps.UserData() : ps.FlatUserData(),
                                  d.dword, raw);
        } else if (d.kind == Ref::ConstBuffer) {
            CardBufferFacts facts;
            facts.bound = d.buffer < ps.buffers.size();
            facts.special = facts.bound && ps.buffers[d.buffer].IsSpecial();
            facts.written = facts.bound && ps.buffers[d.buffer].is_written;
            if (facts.bound && !facts.special && !facts.written) {
                const AmdGpu::Buffer sharp = ps.buffers[d.buffer].GetSharp(ps);
                facts.valid = sharp.Valid();
                facts.base = sharp.base_address;
                facts.size = sharp.GetSize();
            }
            s = ReadCardBufferDword(facts, d.dword, guest, raw);
        }
        state = CardWorse(state, s);
        if (s == CardDwordState::Read) {
            values[i] = std::bit_cast<f32>(raw);
        }
    }
    if (state != CardDwordState::Read) {
        out.miss = CardMiss::Constants;
        return out;
    }
    const CardResolved resolved = CardResolve(record, values);
    if (!resolved.finite) {
        out.miss = CardMiss::Constants;
        return out;
    }
    if (cut->image >= ps.images.size() || cut->sampler >= ps.samplers.size()) {
        out.miss = CardMiss::Image;
        return out;
    }
    const AmdGpu::Image image = ps.images[cut->image].GetSharp(ps);
    if (!image.Valid()) {
        out.miss = CardMiss::Image;
        return out;
    }
    static_assert(sizeof(image) == sizeof(out.tsharp));
    std::memcpy(out.tsharp.data(), &image, sizeof(out.tsharp));
    out.stored_channel = u8(image.DstSelect().array[cut->channel & 3]);
    out.data_format = u8(image.GetDataFmt());
    const AmdGpu::Sampler sampler = ps.samplers[cut->sampler].GetSharp(ps);
    out.mode_u = u8(CardAxisMode(u32(sampler.clamp_x.Value())));
    out.mode_v = u8(CardAxisMode(u32(sampler.clamp_y.Value())));
    out.selector = PackCardSelector(selector);
    out.affine = resolved.affine;
    out.reference = resolved.reference;
    out.dither_scale = resolved.dither_scale;
    out.ref_dwords = resolved.ref_dwords;
    out.op = CardOp(u8(cut->op));
    out.nonzero = cut->nonzero;
    out.dither = record.dither;
    out.fade_left_out = cut->nonzero && cut->ignored_factor_terms != 0;
    CardFinishHashes(out);
    out.valid = true;
    return out;
}
} // namespace

"""
RT_CARD = r"""// bbport (r54_leaf-stage2): the card UVs, stage 2 of the ray traced foliage shadows (BB_RT_CARD_ALPHA=1;
// rt_card_uv.h says what, engine/docs/rt_card_alpha.md why). A cut-out entry's capture also stores
// its vertices' coordinates and alpha factors (the vertex shader's capture variant, CaptureUv,
// into card_ring), and RecordBuilds expands them into the entry's block of card_pool: a record of
// 16 bytes a BLAS primitive. Nothing reads the pool yet; no ray, mask, TLAS or BLAS changes.

// The ring, the expand pass and its stat slots (at setup, the knob on). Without them no capture
// stores UVs (CardCapture), and the address blocks hold a ring address of 0 that nothing reads.
// The ring's memory is not known until the first RecordBuilds fills it with CARD_UV_RING_UNSET
// (card_ring_clean); no capture stores UVs before that.
bool RtShadow::CardSetup() {
    using enum vk::DescriptorType;
    const vk::DeviceSize stat_bytes = vk::DeviceSize(CARD_UV_STAT_SLOTS) * CARD_UV_STAT_WORDS * 4;
    card_ring_clean = false;
    card_ring_dirty = 0;
    card_uv_ready =
        EffectPass::Create(instance, card_set, card_layout, card_pipeline,
                           {eStorageBuffer, eStorageBuffer, eStorageBuffer}, sizeof(CardUvPush),
                           RT_CARD_UV_COMP, "Ray tracing card UVs") &&
        Make(card_ring, CardRingBytes, false,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        Make(card_stat_buffer, stat_bytes, false,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                 VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        Make(card_readback, stat_bytes, true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        card_readback.mapped;
    if (!card_uv_ready) {
        Free(card_ring);
        Free(card_stat_buffer);
        Free(card_readback);
        std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=1 but off - no pipeline or "
                    "buffer for them\n");
        return false;
    }
    std::memset(card_readback.mapped, 0, std::size_t(stat_bytes));
    std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=1, the cut-out cards' UVs are captured "
                "(ring %llu MiB now, pool %llu MiB at the first card); no ray reads them yet, the "
                "picture is unchanged\n",
                static_cast<unsigned long long>(CardRingBytes >> 20),
                static_cast<unsigned long long>(CardPoolBytes >> 20));
    return true;
}

bool RtShadow::CardMakePool() {
    if (card_pool_failed) {
        return false;
    }
    const VmaVirtualBlockCreateInfo block_ci{.size = CardPoolBytes};
    if (!Make(card_pool, CardPoolBytes, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        vmaCreateVirtualBlock(&block_ci, &card_block) != VK_SUCCESS) {
        Free(card_pool);
        card_block = VK_NULL_HANDLE;
        card_pool_failed = true;
        std::printf("Ray tracing card UVs (r54): no pool (%llu MiB): no card gets UVs\n",
                    static_cast<unsigned long long>(CardPoolBytes >> 20));
        return false;
    }
    return true;
}

// A block of the pool for the entry's records (and its card slot). Over the pool: NoRoom, tried
// again once a block is freed (card_pool_gen).
bool RtShadow::CardTakeBlock(Entry& entry) {
    CardUvEntry& c = *entry.card_uv;
    if (!CardPoolFits(entry.triangles) || (!card_block && !CardMakePool())) {
        CardNoRoom(c.uv, card_pool_gen);
        ++card_uv_stats.no_room;
        return false;
    }
    const VmaVirtualAllocationCreateInfo alloc_ci{.size = CardPoolSize(entry.triangles),
                                                  .alignment = CARD_UV_RECORD_BYTES};
    VmaVirtualAllocation block{};
    VkDeviceSize offset = 0;
    if (vmaVirtualAllocate(card_block, &alloc_ci, &block, &offset) != VK_SUCCESS) {
        CardNoRoom(c.uv, card_pool_gen);
        ++card_uv_stats.no_room;
        return false;
    }
    c.block = block;
    c.offset = u32(offset / CARD_UV_RECORD_BYTES);
    c.slot = card_slots.Take();
    card_pool_used += alloc_ci.size;
    ++card_pool_blocks;
    CardGotRoom(c.uv);
    return true;
}

// A cut-out draw of the entry (Draw::card): its card data, at every draw (a second draw of the
// frame too, so the sun shadow pass's card is had whichever pass comes first). The entry's part
// is made at its first such draw, once (not on every frame). A sun shadow pass card gives way to
// a camera pass card when it is stale or no sun shadow pass draw gave it for more than
// CardSunFrames frames (CardTakes; counted). The first time an entry has a valid
// card from both passes, both references and both second reference dwords (cb[21]) are printed
// (the first CardBothLines such entries; the 600-frame line counts all), with the pass whose card
// the entry holds then (the sun shadow pass's unless that card was stale), and a tester sees
// whether the camera pass's material constants give another reference.
void RtShadow::CardNoteDraw(Entry& entry, const Draw& draw) {
    const CardDraw& d = *draw.card;
    ++card_uv_stats.draws;
    if (d.valid) {
        ++card_uv_stats.valid;
    } else {
        ++card_uv_stats.miss[std::size_t(d.miss)];
    }
    if (!entry.card_uv) {
        entry.card_uv = std::make_unique<CardUvEntry>();
    }
    CardUvEntry& c = *entry.card_uv;
    if (entry.seen_frame != frame) {
        CardWaitFrame(c.uv);
    }
    const CardNoted noted = CardNote(c.uv, d, frame);
    card_uv_stats.coordinates += noted.taken && noted.coordinates && c.block ? 1 : 0;
    card_uv_stats.constants += noted.other ? 1 : 0;
    card_uv_stats.sun_gave_way += noted.sun_gave_way ? 1 : 0;
    if (noted.both && card_both_said < CardBothLines) {
        ++card_both_said;
        const float sun = c.uv.pass_reference[0];
        const float cam = c.uv.pass_reference[1];
        std::printf("Ray tracing card UVs (r54): drawn by both passes, key %016llx (%s): sun shadow "
                    "pass ps %016llx reference %.6g (second dword %.6g), camera pass ps %016llx "
                    "reference %.6g (second dword %.6g, dither taken as 0), %s; the card is the "
                    "%s pass's\n",
                    static_cast<unsigned long long>(entry.base),
                    entry.skinned ? (entry.lone == LampLoneState::Lone ? "plant" : "skinned kept")
                                  : "static",
                    static_cast<unsigned long long>(c.uv.pass_ps_hash[0]), double(sun),
                    double(c.uv.pass_ref2[0]), static_cast<unsigned long long>(c.uv.pass_ps_hash[1]),
                    double(cam), double(c.uv.pass_ref2[1]), sun == cam ? "the same" : "they differ",
                    c.uv.card.camera ? "camera" : "sun shadow");
    }
}

// Whether a capture of the entry by this draw may store its UVs now: they are wanted, the ring
// was filled once (card_ring_clean), the draw is one of the card's own (its pixel shader and the same
// coordinates, so the same vertex shader outputs) and stores the entry's instances (Param), the
// ring and the frame's budget have room, and the entry has a block of the pool (taken here when
// it has none). Nothing is set yet.
bool RtShadow::CardCaptureCan(Entry& entry, const Draw& draw) {
    if (!card_uv_ready || !card_ring_clean || !entry.card_uv || !need_scene) {
        return false;
    }
    CardUvEntry& c = *entry.card_uv;
    if (!CardCaptureWanted(c.uv, card_pool_gen) || c.taken_frame == frame) {
        return false;
    }
    const CardDraw* d = draw.card;
    if (!d || !d->valid || d->ps_hash != c.uv.card.ps_hash || d->uv_hash != c.uv.card.uv_hash ||
        draw.first_instance != entry.first_instance) {
        ++card_uv_stats.other_draw;
        return false;
    }
    if (!CardRingFits(card_ring_used, u64(entry.vertices) * entry.instances, card_captures)) {
        ++card_uv_stats.budget;
        return false;
    }
    return c.block || CardTakeBlock(entry);
}

// The capture of `build` (a param of its own) stores the entry's UVs (CardCaptureCan said yes):
// the param's word 1 (the ring index + 1) and word 7 (the selector) are set, and build.uv_base,
// uv_hash.
void RtShadow::CardCaptureTake(Entry& entry, const Draw& draw, Build& build) {
    CardUvEntry& c = *entry.card_uv;
    const u64 stored = u64(entry.vertices) * entry.instances;
    build.uv_base = card_ring_used + 1;
    build.uv_hash = draw.card->uv_hash;
    auto* words = static_cast<u32*>(params.mapped) + std::size_t(build.param) * 8;
    words[1] = build.uv_base;
    words[7] = draw.card->selector;
    card_ring_used += u32(stored);
    card_ring_peak = std::max(card_ring_peak, card_ring_used);
    ++card_captures;
    ++card_uv_stats.captures;
    c.taken_frame = frame;
}

// The capture of `build` (its param, made for the build or r47's look) also stores the entry's
// UVs where CardCaptureCan says so. False for none (words 1 and 7 stay 0).
bool RtShadow::CardCapture(Entry& entry, const Draw& draw, Build& build) {
    if (build.param == 0 || !CardCaptureCan(entry, draw)) {
        return false;
    }
    CardCaptureTake(entry, draw, build);
    return true;
}

// A capture for the UVs alone, of an entry that waited CardWaitFrames frames drawn without one
// (a caster built before its card data was there, held for still, drawn by a sun shadow pass
// first on every frame): a probe (Build::probe and uv_only, no signature) that builds and copies
// nothing. Every check comes before its param is taken, so a refused one costs no param; it
// takes params and positions only within the first half of the frame's (CardUvProbeFits), so
// the builds after it keep the rest. Returns its param, 0 for none (the draw then stores
// nothing).
u32 RtShadow::CardUvProbe(Entry& entry, const Draw& draw) {
    if (!card_uv_ready || !entry.card_uv || !need_scene || r26_freeze != 0) {
        return 0;
    }
    const CardUvEntry& c = *entry.card_uv;
    if (!CardUvOnlyDue(c.uv, card_pool_gen) || c.taken_frame == frame || !draw.card ||
        !draw.card->valid || draw.card->ps_hash != c.uv.card.ps_hash ||
        draw.card->uv_hash != c.uv.card.uv_hash) {
        return 0;
    }
    const u64 stored = u64(entry.vertices) * entry.instances;
    if (!CardUvProbeFits(params_used, MaxParams, positions_used, stored, MaxPositions)) {
        ++card_uv_stats.budget;
        return 0;
    }
    if (!CardCaptureCan(entry, draw)) {
        return 0;
    }
    Build probe{&entry, positions_used, false, {}};
    probe.probe = true;
    probe.uv_only = true;
    probe.param = Param(positions_used, entry);
    if (probe.param == 0) {
        return 0; // not reached: CardUvProbeFits left params
    }
    CardCaptureTake(entry, draw, probe);
    builds.push_back(probe);
    positions_used += u32(stored);
    ++card_uv_stats.uv_probes;
    return probe.param;
}

// Destroy: the block and slot are freed once the GPU is past what was recorded so far (an
// expand pass may still write the block).
void RtShadow::CardRelease(Entry& entry) {
    if (!entry.card_uv) {
        return;
    }
    CardUvEntry& c = *entry.card_uv;
    if (c.pending) {
        std::erase(card_pending, &entry);
    }
    if (c.block) {
        card_frees.push_back({std::bit_cast<u64>(c.block), c.slot, scheduler.CurrentTick()});
    }
    entry.card_uv.reset();
}

// At a frame's end: the frame's ring and budget start again, the expanded entries whose tick
// the GPU passed are Ready, and the blocks of destroyed entries it is done with are freed. The
// driver is asked once how far the GPU is (as ReadStillSigs' caller does); no wait. UV captures
// no RecordBuilds took (drawn after the frame's last one; OnFrameEnd drops their builds) wrote
// their part of the ring: card_ring_dirty keeps how far, and the next RecordBuilds fills that
// part too. (A capture of the next frame before that RecordBuilds may meet such a value at a
// vertex it does not store itself: a window this does not close.)
void RtShadow::CardFrameEnd() {
    card_ring_dirty = std::max(card_ring_dirty, card_ring_used);
    card_ring_used = 0;
    card_captures = 0;
    if (card_pending.empty() && card_frees.empty()) {
        return;
    }
    bool asked = false;
    const auto passed = [&](u64 tick) {
        const bool free = asked ? scheduler.GetWorkSemaphore()->IsFree(tick) : scheduler.IsFree(tick);
        asked = true;
        return free;
    };
    std::erase_if(card_pending, [&](Entry* e) {
        CardUvEntry& c = *e->card_uv;
        if (c.uv.state == CardUvState::Pending && !CardSettle(c.uv, passed(c.uv.tick))) {
            return false;
        }
        c.pending = false;
        return true;
    });
    CardReleaseFrees(card_frees, passed, [&](const CardFree& f) {
        const auto block = std::bit_cast<VmaVirtualAllocation>(f.block);
        VmaVirtualAllocationInfo info{};
        vmaGetVirtualAllocationInfo(card_block, block, &info);
        card_pool_used -= std::min<u64>(card_pool_used, info.size);
        card_pool_blocks -= card_pool_blocks != 0 ? 1 : 0;
        vmaVirtualFree(card_block, block);
        card_slots.Give(f.slot);
        ++card_pool_gen;
    });
}

// The 600-frame line (BB_RT_CARD_ALPHA=1): the cut-out entries by class (as BB_RT_LAMP_CARDS=3
// sees them) and state, which pass's card the entries both passes draw hold, the sun shadow pass
// cards no sun shadow pass draw gave again, the cards' constants (judge's items 3 and 7), why
// entries have no card data or a stale one, the pool, the draws since the last line; then the
// stat slots of the first entries expanded since, once the GPU is past them.
void RtShadow::CardLog() {
    if (!card_uv_on) {
        return;
    }
    constexpr std::size_t Classes = std::size_t(CardClass::Count);
    constexpr std::size_t States = std::size_t(CardUvState::Count);
    std::array<std::array<u32, States>, Classes> states{};
    std::array<u32, std::size_t(CardMiss::Count)> waiting{};
    std::array<u32, std::size_t(CardMiss::Count)> stale{};
    u64 ready_triangles = 0;
    u32 card_entries = 0;
    u32 both = 0, both_sun = 0, both_camera = 0, both_differ = 0, sun_gone = 0;
    u32 with_card = 0, fade = 0, second = 0, dithered = 0;
    // the least and greatest of the cards' reference dwords and dither coefficients (NaN: none)
    std::array<float, 6> range{NAN, NAN, NAN, NAN, NAN, NAN};
    const auto widen = [&range](std::size_t at, float v) {
        range[at] = std::isnan(range[at]) ? v : std::min(range[at], v);
        range[at + 1] = std::isnan(range[at + 1]) ? v : std::max(range[at + 1], v);
    };
    for (const auto& [key, e] : entries) {
        if (!e->card_uv) {
            continue;
        }
        const CardUvEntry& c = *e->card_uv;
        const bool has_card = c.uv.state != CardUvState::NotCard;
        if (c.uv.passes == 3) {
            ++both;
            both_sun += has_card && !c.uv.card.camera ? 1 : 0;
            both_camera += has_card && c.uv.card.camera ? 1 : 0;
        }
        both_differ += CardBothDiffer(c.uv) ? 1 : 0;
        sun_gone += CardSunGone(c.uv, frame) ? 1 : 0;
        if (has_card) {
            const CardDraw& d = c.uv.card;
            ++with_card;
            fade += d.fade_left_out ? 1 : 0;
            second += d.ref_dwords[1] != 0.0f ? 1 : 0;
            widen(0, d.ref_dwords[0]);
            widen(2, d.ref_dwords[1]);
            if (d.dither) {
                ++dithered;
                widen(4, d.dither_scale);
            }
        }
        const CardClass card_class = CardClassOf(e->skinned, e->lone == LampLoneState::Lone);
        ++states[std::size_t(card_class)][std::size_t(c.uv.state)];
        if (!has_card) {
            ++waiting[std::size_t(c.uv.miss)];
        } else if (CardStale(c.uv)) {
            ++stale[std::size_t(c.uv.miss)];
        }
        ready_triangles += c.uv.state == CardUvState::Ready ? e->triangles : 0;
        ++card_entries;
    }
    const u32 ring_peak = card_ring_peak;
    card_ring_peak = 0;
    if (card_entries == 0 && card_uv_stats.draws == 0) {
        return; // no cut-out entry and no cut-out draw: nothing to say
    }
    using ull = unsigned long long;
    const auto& s = card_uv_stats;
    const auto& m = s.miss;
    const auto cls = [&](CardClass k, CardUvState st) {
        return states[std::size_t(k)][std::size_t(st)];
    };
    using M = CardMiss;
    const auto why = [](const auto& count, M miss) { return ull(count[std::size_t(miss)]); };
    using enum CardUvState;
    std::printf(
        "Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=1): %u cut-out entries [ready, pending, "
        "wanted, no room, no card data]: plants [%u, %u, %u, %u, %u], static [%u, %u, %u, %u, %u], "
        "skinned kept [%u, %u, %u, %u, %u]; drawn by both passes: %u (the card the sun shadow "
        "pass's %u, the camera pass's %u), %u with another reference in the camera pass; sun "
        "shadow pass cards not given again for more than %llu frames: %u; cards' constants: %u "
        "with a card, %u with the fade left out, %u with a second reference dword not 0, first "
        "reference dword %.6g to %.6g, second %.6g to %.6g, %u dithered with a coefficient %.6g "
        "to %.6g (taken as 0); no card data at the last draw: %llu no record, %llu a record of "
        "other resources, %llu not repeatable, %llu another permutation, %llu inputs, %llu "
        "constants, %llu image; a card but none at the last draw of its pass (stale): %llu no "
        "record, %llu a record of other resources, %llu not repeatable, %llu another "
        "permutation, %llu inputs, %llu constants, %llu image; pool %.1f of %llu "
        "MiB (%llu triangles in %u blocks, %llu ready); ring peak %u vertices (%.1f MiB); since "
        "the last line: %llu cut-out draws, %llu with card data (without: %llu no record, %llu a "
        "record of other resources, %llu not repeatable, %llu another permutation, %llu inputs, "
        "%llu constants, %llu image), %llu sun shadow pass cards given way to the camera pass's, "
        "%llu UV captures (%llu for the UVs alone), %llu expanded (%llu triangles; %llu dropped, "
        "the card changed), %llu from another draw, %llu over the frame's budget, %llu no room, "
        "%llu left out, %llu new coordinates, %llu other constants changed\n",
        card_entries, cls(CardClass::Plant, Ready), cls(CardClass::Plant, Pending),
        cls(CardClass::Plant, Wanted), cls(CardClass::Plant, NoRoom), cls(CardClass::Plant, NotCard),
        cls(CardClass::Static, Ready), cls(CardClass::Static, Pending),
        cls(CardClass::Static, Wanted), cls(CardClass::Static, NoRoom),
        cls(CardClass::Static, NotCard), cls(CardClass::SkinnedKept, Ready),
        cls(CardClass::SkinnedKept, Pending), cls(CardClass::SkinnedKept, Wanted),
        cls(CardClass::SkinnedKept, NoRoom), cls(CardClass::SkinnedKept, NotCard), both, both_sun,
        both_camera, both_differ, ull(CardSunFrames), sun_gone, with_card, fade, second,
        double(range[0]), double(range[1]), double(range[2]), double(range[3]), dithered,
        double(range[4]), double(range[5]), why(waiting, M::NoRecord),
        why(waiting, M::OtherResources), why(waiting, M::NotRepeatable),
        why(waiting, M::OtherPermutation), why(waiting, M::Inputs), why(waiting, M::Constants),
        why(waiting, M::Image), why(stale, M::NoRecord), why(stale, M::OtherResources),
        why(stale, M::NotRepeatable), why(stale, M::OtherPermutation), why(stale, M::Inputs),
        why(stale, M::Constants), why(stale, M::Image), double(card_pool_used) / 1048576.0,
        ull(CardPoolBytes >> 20), ull(card_pool_used / CARD_UV_RECORD_BYTES), card_pool_blocks,
        ull(ready_triangles), ring_peak, double(u64(ring_peak) * CARD_UV_RING_BYTES) / 1048576.0,
        ull(s.draws), ull(s.valid), why(m, M::NoRecord), why(m, M::OtherResources),
        why(m, M::NotRepeatable), why(m, M::OtherPermutation), why(m, M::Inputs),
        why(m, M::Constants), why(m, M::Image),
        ull(s.sun_gave_way), ull(s.captures), ull(s.uv_probes), ull(s.expanded),
        ull(s.expanded_triangles), ull(s.dropped), ull(s.other_draw), ull(s.budget),
        ull(s.no_room), ull(s.left_out), ull(s.coordinates), ull(s.constants));
    card_uv_stats = {};
    if (card_stat_used == 0 || !scheduler.IsFree(card_stat_tick)) {
        return; // none, or the GPU is not past them: the next line reads them
    }
    const auto* words = static_cast<const u32*>(card_readback.mapped);
    static constexpr std::array<const char*, Classes> ClassNames{"plant", "static", "skinned kept"};
    for (u32 i = 0; i < card_stat_used; ++i) {
        const CardStat st = CardReadStat(words + i * CARD_UV_STAT_WORDS);
        const CardStatInfo& info = card_stat_info[i];
        std::printf("Ray tracing card UVs (r54): first entries, %u: key %016llx, ps %016llx (%s "
                    "pass), %s, %u triangles: %s u %.4g to %.4g, v %.4g to %.4g, alpha factor "
                    "%.3g to %.3g (scaled, no offset or shift applied), %u with an alpha factor "
                    "outside [0, 1], %u with one off the 8-bit steps, %u wide, %u not "
                    "finite\n",
                    i + 1, ull(info.base), ull(info.ps_hash), info.camera ? "camera" : "sun shadow",
                    ClassNames[std::size_t(info.card_class)], info.triangles,
                    st.any ? "" : "no finite corner;", double(st.umin), double(st.umax),
                    double(st.vmin), double(st.vmax), double(st.amin), double(st.amax),
                    st.alpha_range, st.alpha_rounded, st.wide, st.not_finite);
    }
    card_stat_used = 0;
}

"""
RT_MEMBERS = r"""    // bbport (r54_leaf-stage2): the card UVs (BB_RT_CARD_ALPHA=1; rt_card_uv.h, CardSetup and
    // the functions after it). card_uv_on: the knob, read at Setup; card_uv_ready: the ring, the
    // stat slots and the expand pass are there (else no capture stores UVs). card_ring: the
    // captures' UVs (CardRingBytes, made at setup: its address is in the capture address blocks,
    // written once); card_ring_used: its vertices taken since the last RecordBuilds;
    // card_captures: entries given UVs this frame. card_pool: the records (CardPoolBytes, made at
    // the first card) and card_block its blocks (VMA's virtual allocator); card_pool_gen counts
    // the frees (a NoRoom entry tries again after one). card_pending: the entries expanded and
    // not yet Ready (Destroy takes an entry's out); card_frees: the blocks of destroyed entries
    // the GPU may still write. card_stat_*: the stat slots of the first entries expanded after
    // a 600-frame line (CardLog prints them); card_uv_stats: the counts since that line.
    // card_ring_clean: the first RecordBuilds filled all of the ring with CARD_UV_RING_UNSET (no
    // capture stores UVs before); card_ring_dirty: the ring's vertices UV captures no
    // RecordBuilds took wrote (filled again by the next one).
    bool card_uv_on = false;
    bool card_uv_ready = false;
    bool card_pool_failed = false;
    bool card_ring_clean = false;
    u32 card_ring_dirty = 0;
    Buffer card_ring, card_pool, card_stat_buffer, card_readback;
    VmaVirtualBlock card_block{};
    vk::UniqueDescriptorSetLayout card_set;
    vk::UniquePipelineLayout card_layout;
    vk::UniquePipeline card_pipeline;
    u32 card_ring_used = 0;
    u32 card_ring_peak = 0; // the most card_ring_used reached since the last 600-frame line
    u32 card_captures = 0;
    u32 card_pool_gen = 0;
    u32 card_pool_blocks = 0;
    u64 card_pool_used = 0;
    CardSlots card_slots;
    std::vector<Entry*> card_pending;
    std::vector<CardFree> card_frees;
    struct CardStatInfo {
        u64 base = 0; // Entry::base
        u64 ps_hash = 0;
        u32 triangles = 0;
        CardClass card_class = CardClass::Static;
        bool camera = false;
    };
    std::array<CardStatInfo, CARD_UV_STAT_SLOTS> card_stat_info{};
    u32 card_stat_used = 0;
    u64 card_stat_tick = 0;
    // The "drawn by both passes" lines printed (CardNoteDraw prints the first CardBothLines).
    static constexpr u32 CardBothLines = 32;
    u32 card_both_said = 0;
    struct CardUvStats {
        u64 draws = 0, valid = 0, captures = 0, uv_probes = 0, expanded = 0,
            expanded_triangles = 0, dropped = 0, other_draw = 0, budget = 0, no_room = 0,
            left_out = 0, coordinates = 0, constants = 0;
        u64 sun_gave_way = 0; // camera pass cards that replaced a stale or gone sun one (R4-a, R4-b)
        std::array<u64, std::size_t(CardMiss::Count)> miss{};
    } card_uv_stats;
    bool CardSetup();
    bool CardMakePool();
    bool CardTakeBlock(Entry& entry);
    void CardNoteDraw(Entry& entry, const Draw& draw);
    bool CardCaptureCan(Entry& entry, const Draw& draw);
    void CardCaptureTake(Entry& entry, const Draw& draw, Build& build);
    bool CardCapture(Entry& entry, const Draw& draw, Build& build);
    u32 CardUvProbe(Entry& entry, const Draw& draw);
    void CardRelease(Entry& entry);
    void CardFrameEnd();
    void CardLog();
"""

BS = chr(92)  # a backslash, for the C escapes written in the plain strings below

EDITS = {
    SR + "runtime_info.h": [
        ("    static constexpr u8 VertexBoth = 3;\n};\n",
         "    static constexpr u8 VertexBoth = 3;\n"
         "    /// bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1 the capture (VertexCapture) also\n"
         "    /// stores per vertex the card UVs of a cut-out pixel shader (RtShadow::CardCapture):\n"
         "    /// capture param word 1 is the ring index + 1 (0: none), word 7 the selector\n"
         "    /// (Vulkan::PackCardSelector), the ring's address the address block's last member;\n"
         "    /// CaptureUvStride bytes a vertex (u, v, the alpha factor). Never set with the knob off:\n"
         "    /// keys, SPIR-V and address blocks are then as before.\n"
         "    static constexpr u8 CaptureUv = 4;\n"
         "    static constexpr u32 CaptureUvStride = 12;\n"
         "    /// What the capture stores for a value its selector cannot name (a quiet NaN's bits,\n"
         "    /// the ring's CARD_UV_RING_UNSET): the expand pass marks such a triangle not finite.\n"
         "    static constexpr u32 CaptureUvUnset = 0x7fc00000u;\n"
         "    /// The kind of motion (VertexOutputs, VertexCapture or VertexBoth), CaptureUv apart:\n"
         "    /// every equality test of a motion_vectors value goes through this.\n"
         "    static constexpr u32 Kind(u32 motion_vectors) {\n"
         "        return motion_vectors & 3u;\n"
         "    }\n"
         "};\n"),
    ],
    SP + "emit_spirv_special.cpp": [
        ("    if (ctx.runtime_info.hw.vs.motion_vectors == MotionVectors::VertexBoth) {\n"
         "        param_index = ctx.OpBitwiseAnd(",
         "    if (MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth) {\n"
         "        param_index = ctx.OpBitwiseAnd("),
        ("    const bool both = ctx.runtime_info.hw.vs.motion_vectors == MotionVectors::VertexBoth;\n",
         "    const bool both =\n"
         "        MotionVectors::Kind(ctx.runtime_info.hw.vs.motion_vectors) == MotionVectors::VertexBoth;\n"),
        ("static void EmitVertexCapture(EmitContext& ctx) {\n",
         EMIT_CARD + "static void EmitVertexCapture(EmitContext& ctx) {\n"),
        ("                position, spv::MemoryAccessMask::Aligned, 16u);\n"
         "    ctx.OpBranch(store_merge);\n"
         "    ctx.AddLabel(store_merge);\n"
         "}\n",
         "                position, spv::MemoryAccessMask::Aligned, 16u);\n"
         "    // bbport (r54_leaf-stage2): and the card UVs (EmitCardUvStore), with CaptureUv only\n"
         "    if ((ctx.runtime_info.hw.vs.motion_vectors & MotionVectors::CaptureUv) != 0) {\n"
         "        EmitCardUvStore(ctx, load_address(both ? 4 : 2), params, offsets, slot);\n"
         "    }\n"
         "    ctx.OpBranch(store_merge);\n"
         "    ctx.AddLabel(store_merge);\n"
         "}\n"),
    ],
    SP + "spirv_emit_context.cpp": [
        ("    const bool both = runtime_info.hw.vs.motion_vectors == MotionVectors::VertexBoth;\n"
         "    const Id type = both ? TypeStruct(U64, U64, U64, U64) : TypeStruct(U64, U64);\n"
         "    Decorate(type, spv::Decoration::Block);\n"
         "    MemberDecorate(type, 0, spv::Decoration::Offset, 0U);\n"
         "    MemberDecorate(type, 1, spv::Decoration::Offset, 8U);\n"
         "    if (both) {\n"
         "        MemberDecorate(type, 2, spv::Decoration::Offset, 16U);\n"
         "        MemberDecorate(type, 3, spv::Decoration::Offset, 24U);\n"
         "    }\n",
         "    const u32 motion_vectors = runtime_info.hw.vs.motion_vectors;\n"
         "    const bool both = MotionVectors::Kind(motion_vectors) == MotionVectors::VertexBoth;\n"
         "    // bbport (r54_leaf-stage2): with the card UVs (CaptureUv) one more address after the\n"
         "    // others, the ring's (RtShadow::Setup writes it). Without, the block is as before.\n"
         "    const bool uv = (motion_vectors & MotionVectors::CaptureUv) != 0;\n"
         "    const Id type = both ? (uv ? TypeStruct(U64, U64, U64, U64, U64) : TypeStruct(U64, U64, U64, U64))\n"
         "                         : (uv ? TypeStruct(U64, U64, U64) : TypeStruct(U64, U64));\n"
         "    Decorate(type, spv::Decoration::Block);\n"
         "    MemberDecorate(type, 0, spv::Decoration::Offset, 0U);\n"
         "    MemberDecorate(type, 1, spv::Decoration::Offset, 8U);\n"
         "    if (both) {\n"
         "        MemberDecorate(type, 2, spv::Decoration::Offset, 16U);\n"
         "        MemberDecorate(type, 3, spv::Decoration::Offset, 24U);\n"
         "    }\n"
         "    if (uv) {\n"
         "        MemberDecorate(type, both ? 4 : 2, spv::Decoration::Offset, both ? 32U : 16U);\n"
         "    }\n"),
    ],
    P + "cutout_analysis.h": [
        ("/// BB_RT_CARD_ALPHA_LOG=1 (read once): pixel shaders are analysed as they compile, and the cache\n"
         "/// warm-up leaves the discarding ones to compile in play. Otherwise off, and none of this runs.\n"
         "[[nodiscard]] bool CutoutAnalysisOn();\n",
         "/// BB_RT_CARD_ALPHA_LOG=1 or (r54) BB_RT_CARD_ALPHA=1 (each read once): pixel shaders are\n"
         "/// analysed as they compile, and the cache warm-up leaves the discarding ones to compile in\n"
         "/// play. Otherwise off, and none of this runs.\n"
         "[[nodiscard]] bool CutoutAnalysisOn();\n"
         "\n"
         "/// (r54_leaf-stage2) BB_RT_CARD_ALPHA_LOG=1 (read once): the log lines of r50 and r50b (the\n"
         "/// shader lines, the draw-time lines, the 600-frame lines) and what only they count.\n"
         "/// BB_RT_CARD_ALPHA=1 alone prints none of them.\n"
         "[[nodiscard]] bool CutoutLogOn();\n"
         "\n"
         "/// (r54_leaf-stage2) BB_RT_CARD_ALPHA=1 (read once; Vulkan::ReadCardAlpha): the capture of\n"
         "/// the cut-out cards' UVs (RtShadow; renderer_vulkan/rt_card_uv.h). A value neither 0 nor 1\n"
         "/// is said once in the log, as off.\n"
         "[[nodiscard]] bool CardAlphaOn();\n"),
    ],
    P + "cutout_analysis_pass.cpp": [
        ('#include "shader_recompiler/ir/program.h"\n',
         '#include "shader_recompiler/ir/program.h"\n'
         '#include "video_core/renderer_vulkan/rt_card_uv.h" // bbport (r54_leaf-stage2): ReadCardAlpha\n'),
        ("bool CutoutAnalysisOn() {\n"
         "    static const bool on = [] {\n"
         "        const char* env = std::getenv(\"BB_RT_CARD_ALPHA_LOG\");\n"
         "        return env && std::strcmp(env, \"1\") == 0;\n"
         "    }();\n"
         "    return on;\n"
         "}\n",
         "bool CutoutLogOn() {\n"
         "    static const bool on = [] {\n"
         "        const char* env = std::getenv(\"BB_RT_CARD_ALPHA_LOG\");\n"
         "        return env && std::strcmp(env, \"1\") == 0;\n"
         "    }();\n"
         "    return on;\n"
         "}\n"
         "\n"
         "bool CardAlphaOn() {\n"
         "    static const bool on = [] {\n"
         "        const char* env = std::getenv(\"BB_RT_CARD_ALPHA\");\n"
         "        if (Vulkan::CardAlphaMisread(env)) {\n"
         "            std::printf(\"Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is neither 0 nor 1: \"\n"
         "                        \"off" + BS + "n\",\n"
         "                        env);\n"
         "        }\n"
         "        return Vulkan::ReadCardAlpha(env) == Vulkan::CardAlphaUv;\n"
         "    }();\n"
         "    return on;\n"
         "}\n"
         "\n"
         "// (r54_leaf-stage2) the records are made for either: the log, or the card UVs a draw reads\n"
         "bool CutoutAnalysisOn() {\n"
         "    static const bool on = CutoutLogOn() || CardAlphaOn();\n"
         "    return on;\n"
         "}\n"),
        ("    std::printf(\"%s" + BS + "n\", CutoutLine(info, runtime_info).c_str());\n}\n",
         "    if (CutoutLogOn()) { // bbport (r54_leaf-stage2): not with BB_RT_CARD_ALPHA=1 alone\n"
         "        std::printf(\"%s" + BS + "n\", CutoutLine(info, runtime_info).c_str());\n"
         "    }\n"
         "}\n"),
        ("void PrintCutoutSummary() {\n    if (!CutoutAnalysisOn()) {\n",
         "void PrintCutoutSummary() {\n    if (!CutoutLogOn()) { // bbport (r54_leaf-stage2)\n"),
    ],
    R + "vk_pipeline_cache.cpp": [
        ('#include "shader_recompiler/recompiler.h"\n',
         '#include "shader_recompiler/recompiler.h"\n'
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r54_leaf-stage2): CardAlphaOn\n'),
        ("        info.hw.vs.motion_vectors =\n"
         "            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0));\n",
         "        // bbport (r54_leaf-stage2): CaptureUv: the capture stores the card UVs too\n"
         "        // (BB_RT_CARD_ALPHA=1, read once; the key below says the same)\n"
         "        info.hw.vs.motion_vectors =\n"
         "            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0) |\n"
         "               (sel.capture && Shader::Optimization::CardAlphaOn() ? Shader::MotionVectors::CaptureUv\n"
         "                                                                    : 0));\n"),
        ("    if (sel.capture) {\n"
         "        key.motion_vectors = Shader::MotionVectors::VertexCapture;\n"
         "    }\n",
         "    if (sel.capture) {\n"
         "        key.motion_vectors = Shader::MotionVectors::VertexCapture;\n"
         "        if (Shader::Optimization::CardAlphaOn()) { // bbport (r54_leaf-stage2)\n"
         "            key.motion_vectors |= Shader::MotionVectors::CaptureUv;\n"
         "        }\n"
         "    }\n"),
        ("    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info)) {\n",
         "    // bbport (r54_leaf-stage2): a capture vertex shader with the card UVs (CaptureUv,\n"
         "    // BB_RT_CARD_ALPHA=1) keeps the recompiler's SPIR-V. Only its EmitVertexCapture stores the\n"
         "    // UVs (EmitCardUvStore); the lifter's capture stores the positions alone, so its module\n"
         "    // would leave the ring unwritten while the CPU names a place in it. With the knob off no\n"
         "    // key has CaptureUv and the lifter is asked as before.\n"
         "    const bool card_uv_capture =\n"
         "        info.hw_stage == HwStage::Vertex &&\n"
         "        (runtime_before.hw.vs.motion_vectors & Shader::MotionVectors::CaptureUv) != 0;\n"
         "    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info) &&\n"
         "        !card_uv_capture) {\n"),
    ],
    R + "vk_pipeline_serialization.cpp": [
        ("    if (sel.graphics_key.motion_vectors &&\n"
         "        !instance.GetPhysicalDevice().getFeatures().vertexPipelineStoresAndAtomics) {\n"
         "        return false;\n"
         "    }\n",
         "    if (sel.graphics_key.motion_vectors &&\n"
         "        !instance.GetPhysicalDevice().getFeatures().vertexPipelineStoresAndAtomics) {\n"
         "        return false;\n"
         "    }\n"
         "    // bbport (r54_leaf-stage2): a capture key of the other BB_RT_CARD_ALPHA setting is not\n"
         "    // built: no draw of this run asks for it, and one with the card UVs (CaptureUv) would read\n"
         "    // an address past the 16 or 32 bytes of the address block the knob off binds.\n"
         "    if (((sel.graphics_key.motion_vectors & Shader::MotionVectors::CaptureUv) != 0) !=\n"
         "        ((sel.graphics_key.motion_vectors & Shader::MotionVectors::VertexCapture) != 0 &&\n"
         "         Shader::Optimization::CardAlphaOn())) {\n"
         "        return false;\n"
         "    }\n"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ('#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50b_leaf-matcher)\n',
         '#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50b_leaf-matcher)\n'
         '#include "video_core/renderer_vulkan/rt_card_uv.h"           // bbport (r54_leaf-stage2)\n'),
        ("void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,\n",
         FX_CARD +
         "void Rasterizer::EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,\n"),
        ("    if (mode == Shader::MotionVectors::VertexBoth) {\n"
         "        dc.push_data.motion_param &= 0xffffu;\n",
         "    if (Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth) {\n"
         "        dc.push_data.motion_param &= 0xffffu;\n"),
        ("    if (mode == Shader::MotionVectors::VertexBoth) {\n"
         "        dc.push_data.motion_param |= param << 16;\n",
         "    if (Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth) {\n"
         "        dc.push_data.motion_param |= param << 16;\n"),
        ("    static const bool cutout_log = Shader::Optimization::CutoutAnalysisOn();\n",
         "    static const bool cutout_log = Shader::Optimization::CutoutLogOn(); // (r54)\n"),
        ("        LogCutoutConstants(regs, *ps, *memory, buffer_cache);\n"
         "    }\n",
         "        LogCutoutConstants(regs, *ps, *memory, buffer_cache);\n"
         "    }\n"
         "    // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1 (a capture pipeline with CaptureUv), a\n"
         "    // cut-out pixel shader's card data as this draw holds it, for RtShadow::PrepareDraw (the\n"
         "    // entry's UV capture). Kept on this stack until PrepareDraw returns: nothing is allocated.\n"
         "    std::optional<CardDraw> card;\n"
         "    if ((mode & Shader::MotionVectors::CaptureUv) != 0 && ps && ps->has_discard &&\n"
         "        (draw.camera_pass || draw.shadow_pass)) {\n"
         "        card = ResolveCardDraw(regs, *ps, draw.camera_pass, *memory, buffer_cache);\n"
         "        draw.card = &*card;\n"
         "    }\n"),
    ],
    R + "vk_rt_shadow.h": [
        ('#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)\n',
         '#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)\n'
         '#include "video_core/renderer_vulkan/rt_card_uv.h"     // bbport (r54_leaf-stage2)\n'),
        ("        u64 pixel_shader = 0;\n"
         "    };\n",
         "        u64 pixel_shader = 0;\n"
         "        // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1 (a capture pipeline with\n"
         "        // CaptureUv), a cut-out pixel shader's card data as this draw holds it\n"
         "        // (EffectsCaptureDraw's, valid during the PrepareDraw call); null otherwise\n"
         "        const CardDraw* card = nullptr;\n"
         "    };\n"),
        ("    struct Entry {\n"
         "        Buffer storage;\n",
         "    // bbport (r54_leaf-stage2): an entry's card UVs (BB_RT_CARD_ALPHA=1; made at its first\n"
         "    // cut-out draw): the card data and state (rt_card_uv.h), its block of the pool (VMA's\n"
         "    // virtual allocator; `offset` in records) and card slot (stage 4's custom index), the frame\n"
         "    // of its last UV capture, whether it is in card_pending.\n"
         "    struct CardUvEntry {\n"
         "        CardUv uv;\n"
         "        VmaVirtualAllocation block{};\n"
         "        u32 offset = 0;\n"
         "        u32 slot = 0;\n"
         "        u64 taken_frame = 0;\n"
         "        bool pending = false;\n"
         "    };\n"
         "    struct Entry {\n"
         "        Buffer storage;\n"),
        ("        bool palette_placed = false; // bbport (r47b_casters): see Draw::palette_placed\n"
         "    };\n",
         "        bool palette_placed = false; // bbport (r47b_casters): see Draw::palette_placed\n"
         "        // bbport (r54_leaf-stage2): its card UVs (empty with BB_RT_CARD_ALPHA off, and until\n"
         "        // its first cut-out draw)\n"
         "        std::unique_ptr<CardUvEntry> card_uv;\n"
         "    };\n"),
        ("        std::array<float, 3> still_origin{};\n"
         "    };\n",
         "        std::array<float, 3> still_origin{};\n"
         "        // bbport (r54_leaf-stage2): the capture also stores the entry's card UVs at ring index\n"
         "        // uv_base - 1 (0: none), for coordinates of this hash (CardCapture); uv_only: a probe\n"
         "        // for the UVs alone (CardUvProbe), which r47's looks know nothing of\n"
         "        u32 uv_base = 0;\n"
         "        u64 uv_hash = 0;\n"
         "        bool uv_only = false;\n"
         "    };\n"),
        ("    void ReadStillSigs(u32 slot);\n",
         "    void ReadStillSigs(u32 slot);\n" + RT_MEMBERS),
    ],
    R + "vk_rt_shadow.cpp": [
        ("#include <algorithm>\n#include <cmath>\n",
         "#include <algorithm>\n#include <bit> // bbport (r54_leaf-stage2)\n#include <cmath>\n"),
        ('#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)\n',
         '#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)\n'
         '#include "video_core/host_shaders/rt_card_uv_comp.h"           // bbport (r54_leaf-stage2)\n'),
        ("              offsetof(StillPush, indices) == 64 && offsetof(StillPush, slot) == 76);\n",
         "              offsetof(StillPush, indices) == 64 && offsetof(StillPush, slot) == 76);\n"
         "\n"
         "// bbport (r54_leaf-stage2): what the capture's vertex shader stores (emit_spirv_special.cpp,\n"
         "// EmitCardUvStore: the stride, the selector's fields) is what the expand pass reads.\n"
         "static_assert(Shader::MotionVectors::CaptureUvStride == CARD_UV_RING_BYTES &&\n"
         "              Shader::MotionVectors::CaptureUvUnset == CARD_UV_RING_UNSET);\n"
         "static_assert(PackCardSelector({31, 3, 3, 31, 3, true}) == 0x8001ffffu &&\n"
         "              PackCardSelector({1, 0, 0, 0, 0, false}) == 0x80000001u &&\n"
         "              PackCardSelector({0, 1, 0, 0, 0, false}) == 0x80000020u &&\n"
         "              PackCardSelector({0, 0, 1, 0, 0, false}) == 0x80000080u &&\n"
         "              PackCardSelector({0, 0, 0, 1, 0, false}) == 0x80000200u &&\n"
         "              PackCardSelector({0, 0, 0, 0, 1, false}) == 0x80004000u);\n"
         "// bbport (r54_leaf-stage2): a sun shadow pass card is preferred for r14's longest hold window\n"
         "// (a cascade the game skips leaves its casters undrawn that long; rt_card_uv.h, CardSunFrames).\n"
         "static_assert(CardSunFrames == u64(MaxHoldPeriod) - 1 + HoldMarginFrames);\n"),
        ("    Free(still_sigs); // bbport (r47_still-check)\n"
         "    Free(still_readback);\n",
         "    Free(still_sigs); // bbport (r47_still-check)\n"
         "    Free(still_readback);\n"
         "    // bbport (r54_leaf-stage2): the card UVs' buffers and blocks (the GPU is done: Finish above)\n"
         "    if (card_block) {\n"
         "        vmaClearVirtualBlock(card_block);\n"
         "        vmaDestroyVirtualBlock(card_block);\n"
         "    }\n"
         "    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback}) {\n"
         "        Free(*b);\n"
         "    }\n"),
        ("    entry.bytes = 0;\n"
         "    entry.scene_bytes = 0;\n",
         "    entry.bytes = 0;\n"
         "    entry.scene_bytes = 0;\n"
         "    CardRelease(entry); // bbport (r54_leaf-stage2): its block, once the GPU is past it\n"),
        ("bool RtShadow::Setup(const ObjectMotion& object_motion) {\n"
         "    tried = true;\n",
         "bool RtShadow::Setup(const ObjectMotion& object_motion) {\n"
         "    tried = true;\n"
         "    card_uv_on = Shader::Optimization::CardAlphaOn(); // bbport (r54_leaf-stage2)\n"),
        ("        !Make(capture_addresses, 16, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||\n"
         "        !Make(both_addresses, 32, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT)) {\n",
         "        // bbport (r54_leaf-stage2): one address more with the card UVs (the ring's)\n"
         "        !Make(capture_addresses, card_uv_on ? 24 : 16, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||\n"
         "        !Make(both_addresses, card_uv_on ? 40 : 32, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT)) {\n"),
        ("    const std::array<u64, 2> capture_table{params.address, positions.address};\n"
         "    std::memcpy(capture_addresses.mapped, capture_table.data(), sizeof(capture_table));\n"
         "    const auto motion_table = object_motion.AddressTable();\n"
         "    const std::array<u64, 4> both_table{motion_table.params, motion_table.positions, params.address,\n"
         "                                        positions.address};\n"
         "    std::memcpy(both_addresses.mapped, both_table.data(), sizeof(both_table));\n",
         "    // bbport (r54_leaf-stage2): with the card UVs the ring's address is the blocks' last\n"
         "    // member (0 where CardSetup failed: no capture then names a place in the ring). Written\n"
         "    // once, here, before any draw binds the blocks.\n"
         "    if (card_uv_on) {\n"
         "        CardSetup();\n"
         "    }\n"
         "    const std::array<u64, 3> capture_table{params.address, positions.address, card_ring.address};\n"
         "    std::memcpy(capture_addresses.mapped, capture_table.data(), card_uv_on ? 24 : 16);\n"
         "    const auto motion_table = object_motion.AddressTable();\n"
         "    const std::array<u64, 5> both_table{motion_table.params, motion_table.positions, params.address,\n"
         "                                        positions.address, card_ring.address};\n"
         "    std::memcpy(both_addresses.mapped, both_table.data(), card_uv_on ? 40 : 32);\n"),
        ("    const vk::DescriptorBufferInfo capture_info{capture_addresses.buffer, 0, 16};\n"
         "    const vk::DescriptorBufferInfo both_info{both_addresses.buffer, 0, 32};\n",
         "    const vk::DescriptorBufferInfo capture_info{capture_addresses.buffer, 0,\n"
         "                                                card_uv_on ? 24u : 16u}; // (r54)\n"
         "    const vk::DescriptorBufferInfo both_info{both_addresses.buffer, 0, card_uv_on ? 40u : 32u};\n"),
        ("    const vk::DescriptorSet set = mode == 3u ? both_set : capture_set;\n",
         "    const vk::DescriptorSet set =\n"
         "        Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth ? both_set\n"
         "                                                                              : capture_set;\n"),
        ("    if (draw.pixel_shader != 0 && Shader::Optimization::CutoutAnalysisOn()) {\n",
         "    if (draw.pixel_shader != 0 && Shader::Optimization::CutoutLogOn()) { // (r54)\n"),
        ("    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key\n",
         "    // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1, a cut-out draw's card data, at every\n"
         "    // draw of the entry (Draw::card)\n"
         "    if (draw.card) {\n"
         "        CardNoteDraw(entry, draw);\n"
         "    }\n"
         "    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key\n"),
        ("            ++stats.merged;\n"
         "        }\n"
         "        return 0;\n"
         "    }\n"
         "    entry.mask = mask;\n",
         "            ++stats.merged;\n"
         "        }\n"
         "        // bbport (r54_leaf-stage2): a second draw of the frame may capture the UVs alone (the\n"
         "        // sun shadow pass's card of an entry the camera pass draws first on every frame)\n"
         "        return CardUvProbe(entry, draw);\n"
         "    }\n"
         "    entry.mask = mask;\n"),
        ("            probe.param = Param(positions_used, entry);\n"
         "            probe.sig = TakeStillSig(entry);\n",
         "            probe.param = Param(positions_used, entry);\n"
         "            (void)CardCapture(entry, draw, probe); // bbport (r54_leaf-stage2): its UVs too\n"
         "            probe.sig = TakeStillSig(entry);\n"),
        ("        builds.back().param = param; // bbport (r47_still-check): see CaptureLeftOut\n",
         "        builds.back().param = param; // bbport (r47_still-check): see CaptureLeftOut\n"
         "        (void)CardCapture(entry, draw, builds.back()); // bbport (r54_leaf-stage2): its UVs too\n"),
        ("    entry.seen_frame = frame;\n"
         "    frame_entries.push_back(&entry);\n"
         "    return param;\n"
         "}\n",
         "    // bbport (r54_leaf-stage2): a draw nothing else captured may capture the UVs alone\n"
         "    if (param == 0) {\n"
         "        param = CardUvProbe(entry, draw);\n"
         "    }\n"
         "    entry.seen_frame = frame;\n"
         "    frame_entries.push_back(&entry);\n"
         "    return param;\n"
         "}\n"),
        ("        std::vector<StillPush> still;\n"
         "        vk::BufferCopy still_copy;\n"
         "    };\n",
         "        std::vector<StillPush> still;\n"
         "        vk::BufferCopy still_copy;\n"
         "        // bbport (r54_leaf-stage2): the expand pass's dispatches, the stat slots they fill,\n"
         "        // and the ring's bytes filled with CARD_UV_RING_UNSET after them (0: none)\n"
         "        std::vector<CardUvPush> card;\n"
         "        u32 card_stat_mask = 0;\n"
         "        vk::DeviceSize card_ring_fill = 0;\n"
         "    };\n"),
        ("        if (build.sig != 0) {\n"
         "            job->still.push_back(",
         "        // bbport (r54_leaf-stage2): this capture also stored the entry's card UVs\n"
         "        // (CardCapture): they are expanded into its block of the pool (the lambda below),\n"
         "        // unless the entry's coordinates changed since the capture (it is captured again).\n"
         "        if (build.uv_base != 0 && e.card_uv && e.card_uv->block) {\n"
         "            CardUvEntry& c = *e.card_uv;\n"
         "            CardSelector selector;\n"
         "            if (c.uv.card.uv_hash != build.uv_hash ||\n"
         "                !UnpackCardSelector(c.uv.card.selector, selector)) {\n"
         "                ++card_uv_stats.dropped;\n"
         "            } else {\n"
         "                u32 stat = 0;\n"
         "                if (card_stat_used < CARD_UV_STAT_SLOTS) {\n"
         "                    stat = ++card_stat_used;\n"
         "                    card_stat_info[stat - 1] = {e.base, c.uv.card.ps_hash, e.triangles,\n"
         "                                                CardClassOf(e.skinned, e.lone == LampLoneState::Lone),\n"
         "                                                c.uv.card.camera};\n"
         "                    job->card_stat_mask |= 1u << (stat - 1);\n"
         "                    card_stat_tick = scheduler.CurrentTick();\n"
         "                }\n"
         "                job->card.push_back({e.indices.address, build.uv_base - 1, e.triangles, c.offset,\n"
         "                                     CardPushFlags(c.uv.card.mode_u, c.uv.card.mode_v,\n"
         "                                                   selector.has_alpha, stat),\n"
         "                                     {}, CardPoolAffine(c.uv.card.affine)});\n"
         "                CardRecorded(c.uv, scheduler.CurrentTick());\n"
         "                if (!c.pending) {\n"
         "                    c.pending = true;\n"
         "                    card_pending.push_back(&e);\n"
         "                }\n"
         "                ++card_uv_stats.expanded;\n"
         "                card_uv_stats.expanded_triangles += e.triangles;\n"
         "            }\n"
         "        }\n"
         "        if (build.sig != 0) {\n"
         "            job->still.push_back("),
        ("    builds.clear();\n"
         "    positions_used = 0;\n"
         "    scratch_used = 0;\n",
         "    builds.clear();\n"
         "    positions_used = 0;\n"
         "    scratch_used = 0;\n"
         "    // bbport (r54_leaf-stage2): the ring is reused as the positions are. What this call's\n"
         "    // captures and those no call took (card_ring_dirty) used of it, or all of it once before\n"
         "    // any capture stores UVs, is filled with CARD_UV_RING_UNSET after the expand pass (the\n"
         "    // lambda below): a vertex a later capture does not store reads as not finite, never as\n"
         "    // an earlier capture's values.\n"
         "    if (card_uv_ready && (card_ring_used != 0 || card_ring_dirty != 0 || !card_ring_clean)) {\n"
         "        job->card_ring_fill =\n"
         "            card_ring_clean\n"
         "                ? vk::DeviceSize(std::max(card_ring_used, card_ring_dirty)) * CARD_UV_RING_BYTES\n"
         "                : vk::DeviceSize(CardRingBytes);\n"
         "        card_ring_clean = true;\n"
         "        card_ring_dirty = 0;\n"
         "    }\n"
         "    card_ring_used = 0;\n"),
        ("         still_layout = *still_layout](vk::CommandBuffer cmdbuf) {\n",
         "         still_layout = *still_layout, card_ring_buffer = card_ring.buffer,\n"
         "         card_pool_buffer = card_pool.buffer, card_stat_buffer = card_stat_buffer.buffer,\n"
         "         card_readback_buffer = card_readback.buffer, card_pipeline = *card_pipeline,\n"
         "         card_layout = *card_layout](vk::CommandBuffer cmdbuf) {\n"),
        ("            const vk::WriteDescriptorSet write{.dstBinding = 0,\n"
         "                                               .descriptorCount = 1,\n"
         "                                               .descriptorType = vk::DescriptorType::eStorageBuffer,\n"
         "                                               .pBufferInfo = &position_info};\n"
         "            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);\n",
         "            // bbport (r54_leaf-stage2): the card UVs of this call's UV captures into the pool\n"
         "            // (rt_card_uv.comp). The captures' vertex shaders wrote the ring before the\n"
         "            // barrier at the top; this reads the ring and the triangle lists and writes the\n"
         "            // pool and the stat slots only: no light target, no camera depth, nothing of the\n"
         "            // positions, so no lamp batch needs to end for it. Nothing reads the pool yet.\n"
         "            if (!job->card.empty()) {\n"
         "                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;\n"
         "                constexpr vk::DeviceSize slot_bytes = CARD_UV_STAT_WORDS * 4;\n"
         "                if (job->card_stat_mask != 0) {\n"
         "                    for (u32 s = 0; s < CARD_UV_STAT_SLOTS; ++s) {\n"
         "                        if (job->card_stat_mask & (1u << s)) {\n"
         "                            cmdbuf.fillBuffer(card_stat_buffer, s * slot_bytes, slot_bytes, 0);\n"
         "                        }\n"
         "                    }\n"
         "                    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,\n"
         "                                              Compute,\n"
         "                                              vk::AccessFlagBits2::eShaderRead |\n"
         "                                                  vk::AccessFlagBits2::eShaderWrite);\n"
         "                }\n"
         "                const vk::DescriptorBufferInfo ring_info{card_ring_buffer, 0, VK_WHOLE_SIZE};\n"
         "                const vk::DescriptorBufferInfo pool_info{card_pool_buffer, 0, VK_WHOLE_SIZE};\n"
         "                const vk::DescriptorBufferInfo stat_info{card_stat_buffer, 0, VK_WHOLE_SIZE};\n"
         "                const std::array<vk::WriteDescriptorSet, 3> card_writes{{\n"
         "                    {.dstBinding = 0, .descriptorCount = 1,\n"
         "                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ring_info},\n"
         "                    {.dstBinding = 1, .descriptorCount = 1,\n"
         "                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &pool_info},\n"
         "                    {.dstBinding = 2, .descriptorCount = 1,\n"
         "                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &stat_info},\n"
         "                }};\n"
         "                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, card_pipeline);\n"
         "                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, card_layout, 0,\n"
         "                                            card_writes);\n"
         "                for (const CardUvPush& push : job->card) {\n"
         "                    cmdbuf.pushConstants(card_layout, vk::ShaderStageFlagBits::eCompute, 0,\n"
         "                                         sizeof(push), &push);\n"
         "                    cmdbuf.dispatch((push.triangles + CARD_UV_GROUP - 1) / CARD_UV_GROUP, 1, 1);\n"
         "                }\n"
         "                // The ring was read (the next call's captures write it again), the pool and\n"
         "                // the stat slots written (for the copy below, and for later readers).\n"
         "                EffectPass::MemoryBarrier(cmdbuf, Compute,\n"
         "                                          vk::AccessFlagBits2::eShaderRead |\n"
         "                                              vk::AccessFlagBits2::eShaderWrite,\n"
         "                                          Compute | vk::PipelineStageFlagBits2::eVertexShader |\n"
         "                                              Transfer,\n"
         "                                          vk::AccessFlagBits2::eShaderRead |\n"
         "                                              vk::AccessFlagBits2::eShaderWrite |\n"
         "                                              vk::AccessFlagBits2::eTransferRead);\n"
         "                if (job->card_stat_mask != 0) {\n"
         "                    for (u32 s = 0; s < CARD_UV_STAT_SLOTS; ++s) {\n"
         "                        if (job->card_stat_mask & (1u << s)) {\n"
         "                            cmdbuf.copyBuffer(card_stat_buffer, card_readback_buffer,\n"
         "                                              vk::BufferCopy{s * slot_bytes, s * slot_bytes,\n"
         "                                                             slot_bytes});\n"
         "                        }\n"
         "                    }\n"
         "                    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,\n"
         "                                              vk::PipelineStageFlagBits2::eHost,\n"
         "                                              vk::AccessFlagBits2::eHostRead);\n"
         "                }\n"
         "            }\n"
         "            // bbport (r54_leaf-stage2): the ring's used part (all of it the first time) back to\n"
         "            // CARD_UV_RING_UNSET: after the captures' writes and the expand pass's reads, before\n"
         "            // the next captures. A vertex a later capture does not store then reads as not finite.\n"
         "            if (job->card_ring_fill != 0) {\n"
         "                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;\n"
         "                constexpr auto Vertex = vk::PipelineStageFlagBits2::eVertexShader;\n"
         "                constexpr auto ShaderAccess =\n"
         "                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;\n"
         "                EffectPass::MemoryBarrier(cmdbuf, Compute | Vertex, ShaderAccess, Transfer,\n"
         "                                          vk::AccessFlagBits2::eTransferWrite);\n"
         "                cmdbuf.fillBuffer(card_ring_buffer, 0, job->card_ring_fill, CARD_UV_RING_UNSET);\n"
         "                EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,\n"
         "                                          Compute | Vertex, ShaderAccess);\n"
         "            }\n"
         "            const vk::WriteDescriptorSet write{.dstBinding = 0,\n"
         "                                               .descriptorCount = 1,\n"
         "                                               .descriptorType = vk::DescriptorType::eStorageBuffer,\n"
         "                                               .pBufferInfo = &position_info};\n"
         "            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);\n"),
        ("            Shader::Optimization::CutoutAnalysisOn()) {\n"
         "            using CardClass = Shader::Optimization::CutoutCardClass;\n",
         "            Shader::Optimization::CutoutLogOn()) { // (r54)\n"
         "            using CardClass = Shader::Optimization::CutoutCardClass;\n"),
        ("void RtShadow::CaptureLeftOut(u32 motion_param, u32 mode) {\n"
         "    const u32 param =\n"
         "        mode == Shader::MotionVectors::VertexBoth ? motion_param >> 16 : motion_param;\n",
         "void RtShadow::CaptureLeftOut(u32 motion_param, u32 mode) {\n"
         "    const u32 param = Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth\n"
         "                          ? motion_param >> 16\n"
         "                          : motion_param;\n"
         "    // bbport (r54_leaf-stage2): nor its card UVs: none are expanded, the entry stays Wanted.\n"
         "    // A capture for the UVs alone (CardUvProbe) is nothing more: r47's looks never counted\n"
         "    // it, so none of their state below changes for it.\n"
         "    if (param != 0 && !builds.empty() && builds.back().param == param) {\n"
         "        Build& last = builds.back();\n"
         "        if (last.uv_base != 0) {\n"
         "            last.uv_base = 0;\n"
         "            ++card_uv_stats.left_out;\n"
         "        }\n"
         "        if (last.uv_only) {\n"
         "            last.left_out = true;\n"
         "            return;\n"
         "        }\n"
         "    }\n"),
        ("void RtShadow::OnFrameEnd() {\n",
         RT_CARD + "void RtShadow::OnFrameEnd() {\n"),
        ("        Shader::Optimization::PrintCutoutSummary();\n"
         "    }\n",
         "        Shader::Optimization::PrintCutoutSummary();\n"
         "        CardLog(); // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1\n"
         "    }\n"),
        ("    params_used = 0;\n"
         "    positions_used = 0;\n"
         "    scratch_used = 0;\n"
         "    new_triangles = 0;\n",
         "    CardFrameEnd(); // bbport (r54_leaf-stage2)\n"
         "    params_used = 0;\n"
         "    positions_used = 0;\n"
         "    scratch_used = 0;\n"
         "    new_triangles = 0;\n"),
    ],
    G + "CMakeLists.txt": [
        ('    if (FILENAME MATCHES "^paint_")\n'
         '        list(APPEND INCLUDES ${SHADER_SRC}/paint_common.glsl)\n'
         '    endif()\n',
         '    if (FILENAME MATCHES "^paint_")\n'
         '        list(APPEND INCLUDES ${SHADER_SRC}/paint_common.glsl)\n'
         '    endif()\n'
         '    # bbport (r54_leaf-stage2): the card UV pass\'s layout, shared with C++ (rt_card_uv.h)\n'
         '    if (FILENAME MATCHES "^rt_card_uv")\n'
         '        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_uv_layout.h)\n'
         '    endif()\n'),
        ("add_host_shader(rt_still_sig.comp rt_still_sig_comp)\n",
         "add_host_shader(rt_still_sig.comp rt_still_sig_comp)\n"
         "# bbport (r54_leaf-stage2): the cut-out cards' UVs into their records (BB_RT_CARD_ALPHA=1)\n"
         "add_host_shader(rt_card_uv.comp rt_card_uv_comp)\n"),
        ("target_include_directories(rt-still-check-test PRIVATE ..)\n",
         "target_include_directories(rt-still-check-test PRIVATE ..)\n"
         "# bbport (r54_leaf-stage2): the card UVs' pure parts (renderer_vulkan/rt_card_uv.h)\n"
         "add_executable(rt-card-uv-test EXCLUDE_FROM_ALL ../tests/test_rt_card_uv.cpp)\n"
         "target_compile_options(rt-card-uv-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(rt-card-uv-test PRIVATE ..)\n"),
    ],
    E + "build.sh": [
        ('    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_motion_history.cpp -o out/motion-history-test\n'
         '    out/motion-history-test\n',
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_motion_history.cpp -o out/motion-history-test\n'
         '    out/motion-history-test\n'
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_card_uv.cpp -o out/rt-card-uv-test\n'
         '    out/rt-card-uv-test\n'),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: text.replace("\r\n", "\n") for path, text in texts.items()}
    ok = True
    if any(foreign(p) for p in list(EDITS) + list(NEW)):
        print("this round would touch a file of another round, the drawn look or the fog")
        ok = False
    for path, text in texts.items():
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in text if ch != "\r"):
            print("%s: not ASCII" % path)
            ok = False
    # Every equality test of a motion_vectors value goes through Kind() in the touched files.
    for path in (SP + "emit_spirv_special.cpp", SP + "spirv_emit_context.cpp",
                 R + "vk_rasterizer_effects.cpp", R + "vk_rt_shadow.cpp"):
        t = texts[path]
        for bad in ("motion_vectors == MotionVectors::VertexBoth", "mode == Shader::MotionVectors::VertexBoth",
                    "mode == 3u"):
            if bad in t:
                print("%s: %s is not a Kind() test" % (path, bad))
                ok = False
    rt = texts[R + "vk_rt_shadow.cpp"]
    if rt.count("Kind(mode) == Shader::MotionVectors::VertexBoth") != 2 or \
            texts[R + "vk_rasterizer_effects.cpp"].count("Kind(mode) == Shader::MotionVectors::VertexBoth") != 2:
        print("the motion param tests are not all Kind() tests")
        ok = False
    # The knob gates: CaptureUv only with CardAlphaOn(), read where the key and the runtime info
    # are made (the same rule for both).
    cache = texts[R + "vk_pipeline_cache.cpp"]
    if cache.count("Shader::Optimization::CardAlphaOn()") != 2 or cache.count("MotionVectors::CaptureUv") != 3:
        print("vk_pipeline_cache.cpp: CaptureUv is not set by the knob in the runtime info and the key")
        ok = False
    # A capture vertex shader with CaptureUv is never lifted (the lifter's capture has no UV store).
    lift = cache.find("    if (Lifter::GetMode() != Lifter::Mode::Off && !EffectShaders::KeepRecompiled(info) &&\n"
                      "        !card_uv_capture) {\n")
    if cache.count("Lifter::Lift(") != 1 or not 0 <= cache.find("const bool card_uv_capture =") < lift < \
            cache.find("Lifter::Lift("):
        print("vk_pipeline_cache.cpp: a capture with the card UVs could still be lifted")
        ok = False
    spv = texts[SP + "spirv_emit_context.cpp"]
    if "TypeStruct(U64, U64, U64, U64) : TypeStruct(U64, U64)" in spv or \
            spv.count("MemberDecorate(type, both ? 4 : 2, spv::Decoration::Offset, both ? 32U : 16U);") != 1:
        print("spirv_emit_context.cpp: the address block's ring member is not there once")
        ok = False
    special = texts[SP + "emit_spirv_special.cpp"]
    if special.count("EmitCardUvStore(") != 2 or \
            special.find("static void EmitCardUvStore(") > special.find("static void EmitVertexCapture("):
        print("emit_spirv_special.cpp: EmitCardUvStore is not defined before the capture and called once")
        ok = False
    # A value the selector cannot name is stored as NaN, never as 0.
    store = special[special.find("static void EmitCardUvStore("):special.find("static void EmitVertexCapture(")]
    if "MotionVectors::CaptureUvUnset" not in store or "0.0f" in store:
        print("emit_spirv_special.cpp: the UV store does not mark what it cannot name")
        ok = False
    if "GL_KHR_shader_subgroup" in texts[H + "rt_card_uv.comp"]:
        print("rt_card_uv.comp: needs subgroup operations")
        ok = False
    cut_h = texts[P + "cutout_analysis.h"]
    cut = texts[P + "cutout_analysis_pass.cpp"]
    for decl in ("bool CutoutLogOn()", "bool CardAlphaOn()"):
        if cut_h.count(decl) != 1 or cut.count(decl) != 1:
            print("cutout_analysis: %s is not declared and defined once" % decl)
            ok = False
    if cut.count('std::getenv("BB_RT_CARD_ALPHA")') != 1 or cut.count('std::getenv("BB_RT_CARD_ALPHA_LOG")') != 1:
        print("cutout_analysis_pass.cpp: a knob is not read once")
        ok = False
    # The r50 and r50b log lines take the log knob only.
    if "void PrintCutoutSummary() {\n    if (!CutoutLogOn()) {" not in cut or \
            "    if (CutoutLogOn()) { // bbport (r54_leaf-stage2): not with BB_RT_CARD_ALPHA=1 alone\n" \
            "        std::printf(\"%s" + BS + "n\", CutoutLine(" not in cut or \
            "CutoutLogOn(); // (r54)" not in texts[R + "vk_rasterizer_effects.cpp"] or \
            rt.count("Shader::Optimization::CutoutLogOn()) { // (r54)") != 2:
        print("the r50 and r50b log lines are not all under CutoutLogOn()")
        ok = False
    # The C escapes must have kept their backslash on the way into this script.
    for name, text, needle in (
            (R + "vk_rt_shadow.cpp", rt, "\"picture is unchanged" + BS + "n\","),
            (R + "vk_rt_shadow.cpp", rt, "%u not \"\n                    \"finite" + BS + "n\","),
            (P + "cutout_analysis_pass.cpp", cut, "\"off" + BS + "n\",\n"),
            (TESTS + "test_rt_card_uv.cpp", texts[TESTS + "test_rt_card_uv.cpp"], "all passed" + BS + "n\");")):
        if needle not in text:
            print("%s: a C escape lost its backslash on the way into the script" % name)
            ok = False
    fx = texts[R + "vk_rasterizer_effects.cpp"]
    helper = fx.find("CardDraw ResolveCardDraw(const AmdGpu::Regs& regs, const Shader::Info& ps, bool camera,")
    capture = fx.find("void Rasterizer::EffectsCaptureDraw(")
    gate = fx.find("    if ((mode & Shader::MotionVectors::CaptureUv) != 0 && ps && ps->has_discard &&\n")
    prepare = fx.find("const u32 param = rt_shadow->PrepareDraw(draw);")
    if not 0 <= helper < capture < gate < prepare or fx.count("ResolveCardDraw(") != 2:
        print("vk_rasterizer_effects.cpp: the card data is not resolved once, under CaptureUv, before PrepareDraw")
        ok = False
    # A dword the GPU wrote is never read: the guard's order in the pure header.
    hdr = texts[R + "rt_card_uv.h"]
    g0 = hdr.find("    if (!guest.Mapped(address, 4)) {")
    g1 = hdr.find("    if (guest.GpuModified(address, 4)) {")
    g2 = hdr.find("    raw = guest.Read(address);")
    if not 0 <= g0 < g1 < g2 or hdr.count("guest.Read(") != 1:
        print("rt_card_uv.h: the dword read is not after the mapping and GPU-write checks")
        ok = False
    for needle in ("memory.IsValidGpuMapping(address, size) && memory.ClampRangeSize(address, size) == size",
                   "buffer_cache.IsRegionGpuModified(address, size)", "buffer_cache.IsInPlace(address, size)",
                   "facts.written = facts.bound && ps.buffers[d.buffer].is_written;"):
        if fx.count(needle) != 1:
            print("vk_rasterizer_effects.cpp: %s is not there once" % needle)
            ok = False
    # Each card function declared once and defined once.
    h = texts[R + "vk_rt_shadow.h"]
    for name in ("CardSetup()", "CardMakePool()", "CardTakeBlock(Entry& entry)",
                 "CardNoteDraw(Entry& entry, const Draw& draw)",
                 "CardCaptureCan(Entry& entry, const Draw& draw)",
                 "CardCaptureTake(Entry& entry, const Draw& draw, Build& build)",
                 "CardCapture(Entry& entry, const Draw& draw, Build& build)",
                 "CardUvProbe(Entry& entry, const Draw& draw)", "CardRelease(Entry& entry)",
                 "CardFrameEnd()", "CardLog()"):
        if h.count(name + ";") != 1 or rt.count("RtShadow::" + name + " {") != 1:
            print("vk_rt_shadow: %s is not declared and defined once" % name)
            ok = False
    if rt.count("CardCapture(entry, draw, ") != 2 or rt.count("CardUvProbe(entry, draw)") != 2 or \
            rt.count("CardCaptureCan(entry, draw)") != 2 or rt.count("CardCaptureTake(entry, draw, ") != 2 or \
            rt.count("CardRelease(entry);") != 1 or rt.count("CardFrameEnd();") != 1 or \
            rt.count("CardLog();") != 1 or rt.count("CardNoteDraw(entry, draw);") != 1:
        print("vk_rt_shadow.cpp: the card hooks are not where they belong")
        ok = False
    # A UV-only probe: every check before its param, and its own budget.
    probe_fn = rt[rt.find("u32 RtShadow::CardUvProbe(Entry& entry, const Draw& draw) {"):]
    probe_fn = probe_fn[:probe_fn.find("\n}\n")]
    if not 0 <= probe_fn.find("CardUvProbeFits(") < probe_fn.find("CardCaptureCan(entry, draw)") < \
            probe_fn.find("Param(positions_used, entry)") < probe_fn.find("CardCaptureTake(entry, draw, probe)") or \
            "probe.uv_only = true;" not in probe_fn:
        print("vk_rt_shadow.cpp: a UV-only probe takes its param before its checks")
        ok = False
    # A left-out UV-only probe returns before r47's look state.
    left = rt[rt.find("void RtShadow::CaptureLeftOut(u32 motion_param, u32 mode) {"):]
    if not 0 <= left.find("        if (last.uv_only) {\n            last.left_out = true;\n            return;\n") < \
            left.find("    const u32 still = StillNow();"):
        print("vk_rt_shadow.cpp: a left-out UV-only probe reaches r47's look state")
        ok = False
    # The ring: filled after the expand pass, before the unprojection; the pool takes the scale.
    fill = rt.find("cmdbuf.fillBuffer(card_ring_buffer, 0, job->card_ring_fill, CARD_UV_RING_UNSET);")
    if rt.count("cmdbuf.fillBuffer(card_ring_buffer,") != 1 or \
            not rt.find("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, card_pipeline);") < fill < \
            rt.find("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);") or \
            rt.count("CardPoolAffine(c.uv.card.affine)") != 1 or rt.count("card_ring_clean = true;") != 1:
        print("vk_rt_shadow.cpp: the ring is not filled after the expand pass, or the pool's affine is wrong")
        ok = False
    # The expand dispatch: after the still signatures, before the unprojection.
    still = rt.find("cmdbuf.copyBuffer(still_sigs, still_readback, job->still_copy);")
    card = rt.find("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, card_pipeline);")
    unproject = rt.find("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);")
    if not 0 <= still < card < unproject:
        print("vk_rt_shadow.cpp: the expand pass is not between the still signatures and the unprojection")
        ok = False
    # R4-a: the sun shadow pass card's wait is r14's hold window, and a draw's note knows the frame.
    if rt.count("static_assert(CardSunFrames == u64(MaxHoldPeriod) - 1 + HoldMarginFrames);") != 1 or \
            rt.count("CardNote(c.uv, d, frame)") != 1 or rt.count("CardSunGone(c.uv, frame)") != 1:
        print("vk_rt_shadow.cpp: the sun shadow pass card's hold is not tied to r14's window")
        ok = False
    cm = texts[G + "CMakeLists.txt"]
    if cm.count("add_host_shader(rt_card_uv.comp rt_card_uv_comp)") != 1 or \
            cm.count("add_executable(rt-card-uv-test EXCLUDE_FROM_ALL ../tests/test_rt_card_uv.cpp)") != 1:
        print("CMakeLists.txt: the shader or the test target is not there once")
        ok = False
    if texts[E + "build.sh"].count("tests/test_rt_card_uv.cpp -o out/rt-card-uv-test") != 1:
        print("build.sh: the test is not in --test once")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts ({path: text}, None for a file to remove), or None with
    the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, text in NEW.items():
        want = fix(text, "\r\n")
        if mode != "revert":
            if os.path.exists(path):
                if not quiet:
                    print("%s is there already" % path)
                return None
            if not os.path.isdir(os.path.dirname(path)):
                if not quiet:
                    print("no such folder: %s" % os.path.dirname(path))
                return None
            out[path] = want
        else:
            if not os.path.isfile(path) or open(path, encoding="utf-8", newline="").read() != want:
                if not quiet:
                    print("%s is not as this script writes it" % path)
                return None
            out[path] = None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r54_leaf-stage2.py check|apply|revert   (the tree: R54_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file); a file to remove is removed last. If a
    # step fails, what was already moved is put back from the texts read at the start, and what
    # was made is removed, so the tree is never left half patched.
    before = {path: open(path, "rb").read() for path in out if os.path.exists(path)}
    done = []
    try:
        for path, t in out.items():
            if t is not None:
                with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                    f.write(t)
        for path, t in out.items():
            if t is not None:
                os.replace(path + TMP, path)
                done.append(path)
        for path, t in out.items():
            if t is None:
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if path in before:
                with open(path, "wb") as f:
                    f.write(before[path])
            elif os.path.exists(path):
                os.remove(path)
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
