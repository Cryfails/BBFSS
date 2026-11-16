# r62e_leaf-cards-usable: FEATURE patch (lamp ray tracing work, item 1 of the owner's order: leaf
# shadows, since 2026-11-15 22:10 "cut-out shadows (true shape)": the owner wants every thing whose
# shape a textured card cuts out by its alpha - foliage, a wall lantern's hook, a grille, a chain - to
# cast its true shape). Off by default: everything here runs only with BB_RT_CARD_ALPHA on (1 or 2),
# the lamp part only with BB_RT_CARD_LAMPS=1 as well. New knob BB_RT_CARD_SAFE=0 turns r62e off again
# (to compare in one build).
#
# What it fixes (the three blockers of the 2026-11-15 20:46 readiness check):
# (1) With the knobs on, skinned cut-out entries of vs c77a0097 (the player's coat or hair: drawn at
#     dark-alley, church-candles and dream-house with ps a89e01e9 and a 256x1024 texture; 1258 and
#     988 triangles) reach the BLAS with corners that are not numbers or edges up to 3.4e38 m, also in
#     builds that stored no UVs. The code does not show the cause: the capture vertex shader with the
#     card UVs (MotionVectors::CaptureUv, lifter Lift_::VertexCapture since r62c) stores the position
#     exactly as without them, and r62d's DIAG runs put it on the CaptureUv pipeline variant (DIAG 2,
#     no variant: clean; DIAG 1, the variant without any UV store: bad). So the conservative rule:
#     (a) a cut-out gets card UVs and a lamp card bit only while STILL: no skeleton and not moving, or a
#         skeleton r46b's lone sign takes for the thing's own motion (no sun shadow pass draws it: a
#         bed of plants; r89's wind sway only ever moves such lone streams). Hair, cloth, a moving
#         rigid cut-out (a palette, the still check): no card UVs stored, no CARD_LAMP_MASK
#         (RtShadow::CardCaptureCan, PrepareScene's lamp_card). Their capture pipeline stays the
#         CaptureUv variant (the pipeline key is made from the draw state before the entry is known),
#         so this is not all of the knob-off handling: the guard (b) covers the rest.
#     (b) the guard (new rt_card_guard.comp): every BLAS build of an entry ever drawn as a cut-out
#         (Entry::card_uv: its capture pipelines are the CaptureUv variants) is checked on the GPU after
#         rt_unproject.comp and before the build; a triangle naming a vertex past the build's, a corner
#         that is not a number or an edge over 200 m marks the build, and then every vertex of it is put
#         at the world origin: the entry casts nothing for that build (triangles without area are never
#         hit) and stays valid for a later refit (no triangle turns inactive). Counted, keys recorded.
#         Limits: a dropped build of a STILL cut-out is not captured again, so it casts nothing (sun,
#         lamps) until the entry is rebuilt; a moving one refit from a dropped full build keeps that
#         build's BVH (slow traces) until its next full rebuild (r17, about 120 frames).
# (2) Card mask flips (full TLAS builds): a moving rigid cut-out is no lamp card any more (old_pose and
#     stale alternate only for moving entries), and a stale copy of a still one (a plant bed's shared
#     copy between its turns) never carries the bit (its old pose would cast r41's second, displaced
#     shadow) and stays without it CardLampHoldFrames (120) after its last stale record
#     (CardStaleHoldOff): one flip off and at most one back per 120 frames. First turn-ons and later
#     flips are counted apart.
# Review fixes (r62e .fixed): stale hold turned into a hold-off (above); an execution barrier before the
# guard's flag fill (the previous call's COLLAPSE read them); the lines start "Ray traced lamps (r62e)"
# with the counts first (the slot worker keeps that prefix in its evidence); comments and README say
# the limits; apply checks the new files' folders before it writes anything.
# (3) dream-house's knob-off bad builds (6a833138 shared copies of instanced skinned beds, 428.2-428.3 m
#     every run; ce7e5857 sun-only statics 293-444 m; 4aaa195a 207 m) are finite, repeatable lengths:
#     another fault, not touched here. With the knobs on the guard drops such a build of a cut-out (the
#     6a833138 beds are cut-outs) instead of letting its 428 m slivers in.
#
# Off (the defaults): card_uv_on is false, no entry has card_uv, card_lamps is false: CardCaptureCan,
# CardStillFor, the flip split and the guard push are never reached; CardGuardSetup is not called (no
# pipeline, no buffer, no line); job->guard stays empty, so the recorded commands are those of before.
# The only work left is `card_safe_now = {}` (three words) per TLAS record write and one bool test per
# 600 frames (CardSafeLog). No existing shader changes (the new shader is its own build).
#
# Files: vk_rt_shadow.cpp, vk_rt_shadow.h, CMakeLists.txt (gpu), tests/test_rt_lamp_cards.cpp, README.md;
# new: renderer_vulkan/rt_card_still.h, host_shaders/rt_card_guard_layout.h, host_shaders/rt_card_guard.comp.
# Use: python -I -X utf8 r62e_leaf-cards-usable.py check | apply | revert
# Root: R62E_LEAF_CARDS_USABLE_ROOT, else <tree>. Line ends kept (CRLF). Backups in r62e_backup
# next to this script. Every edit refuses unless its anchor (or, on revert, its own text) is found
# exactly once; new files are removed by revert (only when they are byte-identical to what apply wrote).
import os, sys, shutil

ROOT = os.environ.get("R62E_LEAF_CARDS_USABLE_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62e_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
CPP = RV + "vk_rt_shadow.cpp"
HDR = RV + "vk_rt_shadow.h"
CMK = "engine/gpu/CMakeLists.txt"
TST = "engine/tests/test_rt_lamp_cards.cpp"
RDM = "README.md"

NEW = {}

NEW[HS + "rt_card_guard_layout.h"] = r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62e_leaf-cards-usable): the layout the cut-out shadows' guard (rt_card_guard.comp) shares
// with the engine (renderer_vulkan/rt_card_still.h, RtShadow::RecordBuilds and CardSafeLog). Plain
// #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text says where every word lies for both.
#ifndef RT_CARD_GUARD_LAYOUT_H
#define RT_CARD_GUARD_LAYOUT_H

// Threads a group: one triangle each (detect), one vertex each (collapse).
#define CARD_GUARD_GROUP 64
// A build is dropped when a triangle of its list names a vertex past the build's, has a corner that
// is not a finite number, or has an edge longer than this many metres (world space, after
// rt_unproject.comp): the ray tracing geometry check's default bound (BB_RT_GEOMETRY_CHECK_EDGE).
#define CARD_GUARD_EDGE_M 200.0
// The guarded builds one RecordBuilds call holds (one flag word each); more are left unguarded and
// counted on the host.
#define CARD_GUARD_SLOTS 1024
// The push constants' mode word.
#define CARD_GUARD_DETECT 0
#define CARD_GUARD_COLLAPSE 1
// The guard buffer's words (host visible; the counts add up from the start of the run): builds
// dropped, bad triangles, of them not a number or past the vertices, records written, the first
// CARD_GUARD_RECORDS dropped builds' keys (low and high word), the longest finite bad edge's bits,
// then the flags of one call's builds.
#define CARD_GUARD_W_DROPPED 0
#define CARD_GUARD_W_BAD 1
#define CARD_GUARD_W_NOT_FINITE 2
#define CARD_GUARD_W_RECORDS 3
#define CARD_GUARD_W_FIRST_RECORD 4
#define CARD_GUARD_RECORDS 8
#define CARD_GUARD_W_LONGEST 20
#define CARD_GUARD_W_FLAGS 32
#define CARD_GUARD_WORDS (CARD_GUARD_W_FLAGS + CARD_GUARD_SLOTS)

#endif
"""

NEW[HS + "rt_card_guard.comp"] = r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62e_leaf-cards-usable): the guard of the cut-out shadows (true shape): BB_RT_CARD_ALPHA on
// and BB_RT_CARD_SAFE not 0 only (never recorded otherwise). For each BLAS build of
// RtShadow::RecordBuilds whose entry was ever drawn as a cut-out (it has card data, so its capture
// pipelines are the CaptureUv variants), after rt_unproject.comp put its vertices in world space and
// before the build reads them.
// DETECT: one invocation a triangle of the entry's own list (the indices the build reads). A triangle
// that names a vertex past the build's, has a corner that is not a finite number, or an edge longer
// than `edge` metres sets the build's flag and is counted.
// COLLAPSE: one invocation a vertex of the build. When the build's flag is set every vertex goes to the
// world origin: each triangle then has no area, so no ray hits the entry (it casts nothing for this
// build) and the build stays valid for a later refit (no triangle turns inactive, which a refit may not
// do). The first vertex counts the build and records its key (the first CARD_GUARD_RECORDS of the run).

#version 460
#extension GL_EXT_buffer_reference : require
#extension GL_GOOGLE_include_directive : require

#include "rt_card_guard_layout.h"

layout(local_size_x = CARD_GUARD_GROUP) in;

layout(buffer_reference, std430, buffer_reference_align = 4) readonly buffer Indices { uint i[]; };

layout(std430, set = 0, binding = 0) buffer Positions { vec4 p[]; } positions;
layout(std430, set = 0, binding = 1) buffer Guard { uint w[]; } guard;

layout(push_constant) uniform Constants {
    Indices indices;   // the entry's triangle list, relative to `store`
    uint store;        // its first vertex in `positions`
    uint triangles;    // triangles in the list
    uint vertex_count; // vertices of the build (its maxVertex + 1)
    uint slot;         // its flag: word CARD_GUARD_W_FLAGS + slot
    uint mode;         // CARD_GUARD_DETECT or CARD_GUARD_COLLAPSE
    float edge;        // metres
    uint key_lo;       // the entry's key (Entry::base), for the record
    uint key_hi;
};

shared uint g_flag;

bool Finite(vec3 v) {
    return !any(equal(floatBitsToUint(v) & uvec3(0x7f800000u), uvec3(0x7f800000u)));
}

void main() {
    const uint t = gl_GlobalInvocationID.x;
    const uint flag_at = uint(CARD_GUARD_W_FLAGS) + slot;
    if (mode == uint(CARD_GUARD_DETECT)) {
        if (t >= triangles) {
            return;
        }
        const uint a = indices.i[3u * t];
        const uint b = indices.i[3u * t + 1u];
        const uint c = indices.i[3u * t + 2u];
        bool bad = true;
        bool not_finite = true;
        float longest = 0.0;
        if (a < vertex_count && b < vertex_count && c < vertex_count) {
            const vec3 pa = positions.p[store + a].xyz;
            const vec3 pb = positions.p[store + b].xyz;
            const vec3 pc = positions.p[store + c].xyz;
            if (Finite(pa) && Finite(pb) && Finite(pc)) {
                not_finite = false;
                longest = max(distance(pa, pb), max(distance(pb, pc), distance(pc, pa)));
                // An edge that overflowed to infinity is not <= edge either.
                bad = !(longest <= edge);
            }
        }
        if (bad) {
            atomicAdd(guard.w[CARD_GUARD_W_BAD], 1u);
            if (not_finite) {
                atomicAdd(guard.w[CARD_GUARD_W_NOT_FINITE], 1u);
            } else {
                atomicMax(guard.w[CARD_GUARD_W_LONGEST], floatBitsToUint(min(longest, 3.4028235e38)));
            }
            atomicOr(guard.w[flag_at], 1u);
        }
        return;
    }
    // COLLAPSE (`mode` is a push constant: the whole group takes this branch)
    if (gl_LocalInvocationIndex == 0u) {
        g_flag = guard.w[flag_at];
    }
    barrier();
    if (g_flag == 0u) {
        return;
    }
    if (t == 0u) {
        atomicAdd(guard.w[CARD_GUARD_W_DROPPED], 1u);
        const uint at = atomicAdd(guard.w[CARD_GUARD_W_RECORDS], 1u);
        if (at < uint(CARD_GUARD_RECORDS)) {
            guard.w[CARD_GUARD_W_FIRST_RECORD + 2u * at] = key_lo;
            guard.w[CARD_GUARD_W_FIRST_RECORD + 2u * at + 1u] = key_hi;
        }
    }
    if (t < vertex_count) {
        positions.p[store + t].xyz = vec3(0.0);
    }
}
"""

NEW[RV + "rt_card_still.h"] = r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r62e_leaf-cards-usable): cut-out shadows (true shape) made safe to turn on
// (BB_RT_CARD_ALPHA, BB_RT_CARD_LAMPS; BB_RT_CARD_SAFE=0 turns this off). No Vulkan here:
// tests/test_rt_lamp_cards.cpp builds this header alone and runs the code the engine runs.
//
// A cut-out is any draw whose pixel shader discards by a texture's alpha (rt_lamp_cards.h: a sun
// shadow pass draw that samples a texture, a camera pass draw that discards, or one of its mesh):
// leaves and weeds, but just as well a wall lantern's hook, a grille, a railing or a chain drawn as a
// textured card. Nothing here asks what it is, only whether it is still:
// - no skeleton and not moving (Entry::dynamic: a palette, a promoted instance, the still check):
//   still, whatever it shows;
// - a skeleton: still only when r46b's sign takes it for the thing's own motion (its position stream
//   is LampLoneState::Lone: no sun shadow pass draws it while the sun shadow pass draws skeletons, the
//   game gives it no shadow of its own: a bed of plants). r89's wind sway only moves such lone streams
//   (Rasterizer::WindSwayWord asks RtShadow::LonePlant), so a swaying plant stays still here;
// - anything else (a character's hair or coat, a moving rigid prop): not still. It stores no card
//   UVs and gets no lamp card bit (its capture pipeline stays the CaptureUv variant: the pipeline is
//   chosen from the draw state before the entry is known). Of those entries the 15:25 game test
//   found the bad BLAS inputs (vs c77a0097, skinned, the player's coat or hair) and the mask flips
//   (moving rigid cut-outs, whose old pose and stale state alternate).

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "../host_shaders/rt_card_guard_layout.h"

namespace Vulkan {

/// Why an entry of the cut-out sets is or is not still.
enum class CardStillWhy : std::uint8_t { Still, Skinned, Moving };

/// `skinned`: a draw of it had a skeleton; `lone`: its vertices are LampLoneState::Lone;
/// `dynamic`: it counts as moving (a skinned entry always does).
[[nodiscard]] constexpr CardStillWhy CardStillOf(bool skinned, bool lone, bool dynamic) noexcept {
    if (skinned) {
        return lone ? CardStillWhy::Still : CardStillWhy::Skinned;
    }
    return dynamic ? CardStillWhy::Moving : CardStillWhy::Still;
}

/// A still cut-out's copy in an old pose (r41's stale: a shared copy between its rebuild turns)
/// never carries the lamp card bit: its displaced pose would cast a second shadow beside the live
/// copy's (the fault r41 repaired). Once stale it stays without the bit until more than `hold`
/// frames passed since its last stale record, so that the bit does not come and go with every turn
/// (each change makes the TLAS a full build). `last_stale`: the frame + 1 of its last stale record
/// (0: never), kept by the caller. True: the bit may be on.
[[nodiscard]] constexpr bool CardStaleHoldOff(bool stale, std::uint64_t frame,
                                              std::uint64_t& last_stale, std::uint64_t hold) noexcept {
    if (stale) {
        last_stale = frame + 1;
        return false;
    }
    return last_stale == 0 || frame + 1 - last_stale > hold;
}

/// The lamp card bit of an entry's record changed: true for a flip (it had changed before), false
/// for the first turn-on of the entry (`once` then becomes true).
constexpr bool CardMaskTurn(bool& once) noexcept {
    const bool flip = once;
    once = true;
    return flip;
}

inline constexpr float CardGuardEdge = float(CARD_GUARD_EDGE_M);
inline constexpr std::uint32_t CardGuardSlots = CARD_GUARD_SLOTS;
inline constexpr std::uint32_t CardGuardWords = CARD_GUARD_WORDS;
static_assert(CARD_GUARD_W_FIRST_RECORD + 2 * CARD_GUARD_RECORDS <= CARD_GUARD_W_LONGEST &&
              CARD_GUARD_W_LONGEST < CARD_GUARD_W_FLAGS && CARD_GUARD_DETECT != CARD_GUARD_COLLAPSE);

/// rt_card_guard.comp's DETECT test of one triangle on the CPU (4 floats a vertex, `w` not read):
/// a corner past `vertex_count`, a corner that is not a finite number, or an edge that is not at most
/// `edge` metres (an edge that overflows to infinity is not).
[[nodiscard]] inline bool CardGuardBad(const float* positions, std::uint32_t vertex_count,
                                       std::uint32_t a, std::uint32_t b, std::uint32_t c,
                                       float edge) noexcept {
    if (a >= vertex_count || b >= vertex_count || c >= vertex_count) {
        return true;
    }
    const float* const p[3] = {positions + 4 * std::size_t(a), positions + 4 * std::size_t(b),
                               positions + 4 * std::size_t(c)};
    for (const float* v : p) {
        if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) {
            return true;
        }
    }
    const auto length = [](const float* u, const float* v) {
        const float x = u[0] - v[0], y = u[1] - v[1], z = u[2] - v[2];
        return std::sqrt(x * x + y * y + z * z);
    };
    const float longest = std::max(length(p[0], p[1]), std::max(length(p[1], p[2]), length(p[2], p[0])));
    return !(longest <= edge);
}

} // namespace Vulkan
"""

# ---- edits: ("ins", anchor, before, after) keep the anchor; ("rep", old, new) replace it.
EDITS = {}

EDITS[CPP] = [
    ("ins", '#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)\n', "",
     '#include "video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e_leaf-cards-usable)\n'),
    ("ins", '#include "video_core/host_shaders/rt_geometry_check_comp.h" // bbport (r62d_card-uv-diag)\n', "",
     '#include "video_core/host_shaders/rt_card_guard_comp.h" // bbport (r62e_leaf-cards-usable)\n'),
    ("ins", "constexpr float GeoCheckEdgeDefault = 200.0f;\n", "",
     r"""// bbport (r62e_leaf-cards-usable): rt_card_guard.comp's push constants (rt_card_guard_layout.h)
struct CardGuardPush {
    u64 indices;
    u32 store;
    u32 triangles;
    u32 vertex_count;
    u32 slot;
    u32 mode;
    float edge;
    u32 key_lo;
    u32 key_hi;
};
static_assert(sizeof(CardGuardPush) == 40 && offsetof(CardGuardPush, mode) == 24 &&
              offsetof(CardGuardPush, key_hi) == 36);
"""),
    ("rep", "    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback, &card_rows}) {\n",
     "    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback, &card_rows,\n"
     "                      &card_guard}) { // bbport (r62e_leaf-cards-usable): card_guard\n"),
    ("ins", "        CardSetup();\n", "",
     "        CardGuardSetup(); // bbport (r62e_leaf-cards-usable)\n"),
    ("ins", "    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;\n", "",
     "    card_safe_now = {}; // bbport (r62e_leaf-cards-usable): of the records written now\n"),
    ("rep",
     "        const bool lamp_card = card_lamps && card && !stale && !leave && !old_pose && mask != 0 &&\n"
     "                               !RtGlassEntry(mask) &&\n"
     "                               (!entry->skinned || lone) && CardLampOn(*entry);\n",
     "        // bbport (r62e_leaf-cards-usable): only a still cut-out (CardStillFor: no moving rigid one,\n"
     "        // a skinned one only when lone); a stale copy never, and the bit stays off\n"
     "        // CardLampHoldFrames after its last stale record (no flip at each turn of a shared copy);\n"
     "        // BB_RT_CARD_SAFE=0: !stale as r63\n"
     "        const bool lamp_card = card_lamps && card && !leave && !old_pose && mask != 0 &&\n"
     "                               !RtGlassEntry(mask) && CardStillFor(*entry, stale) &&\n"
     "                               (!entry->skinned || lone) && CardLampOn(*entry);\n"),
    ("ins", "            ++lamp_flips;                                                   // bit, whatever its cause\n", "",
     "            ++(CardMaskTurn(entry->card_uv->lamp_once) ? card_safe.flips : card_safe.first_on); // (r62e)\n"),
    ("ins", "        bool probe_host = false; // bbport (r64b_surface-probe-more): a probe slot is copied\n", "",
     r"""        // bbport (r62e_leaf-cards-usable): the guard's dispatches (guard_pipeline set: some)
        std::vector<CardGuardPush> guard;
        vk::Pipeline guard_pipeline{};
        vk::PipelineLayout guard_layout{};
        vk::Buffer guard_buffer{};
"""),
    ("ins", "            geo_window.triangles += e.triangles;\n        }\n", "",
     r"""        // bbport (r62e_leaf-cards-usable): a build of an entry ever drawn as a cut-out is guarded
        // (rt_card_guard.comp): dropped from the scene (every vertex at the origin) when it reads a
        // vertex past its own, a corner that is not a number or an edge over CardGuardEdge
        if (card_guard_on && e.card_uv) {
            if (job->guard.size() < CardGuardSlots) {
                job->guard.push_back({e.indices.address, build.store, e.triangles,
                                      e.vertices * e.instances, u32(job->guard.size()),
                                      u32(CARD_GUARD_DETECT), CardGuardEdge, u32(e.base),
                                      u32(e.base >> 32)});
                ++card_safe.guarded;
            } else {
                ++card_safe.unguarded;
            }
        }
"""),
    ("ins", '    EffectPass::Mark(16, "ray tracing geometry");\n',
     r"""    if (!job->guard.empty()) { // bbport (r62e_leaf-cards-usable)
        job->guard_pipeline = *guard_pipeline;
        job->guard_layout = *guard_layout;
        job->guard_buffer = card_guard.buffer;
    }
""", ""),
    ("ins",
     "            for (const UnprojectPush& push : job->unproject) {\n"
     "                cmdbuf.pushConstants(unproject_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),\n"
     "                                     &push);\n"
     "                cmdbuf.dispatch((push.count + 63) / 64, 1, 1);\n"
     "            }\n", "",
     r"""            // bbport (r62e_leaf-cards-usable): the guard of the cut-out builds (rt_card_guard.comp):
            // their flags zeroed, DETECT over their triangles, COLLAPSE over their vertices; after the
            // pass above wrote the positions, before the check and the builds below read them
            if (job->guard_pipeline) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr auto ShaderAccess =
                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
                // the previous call's COLLAPSE read these flags: the fill waits for it
                EffectPass::MemoryBarrier(cmdbuf, Compute, {}, Transfer, {});
                cmdbuf.fillBuffer(job->guard_buffer, vk::DeviceSize(CARD_GUARD_W_FLAGS) * 4,
                                  vk::DeviceSize(job->guard.size()) * 4, 0);
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderAccess);
                const vk::DescriptorBufferInfo guard_info{job->guard_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 2> guard_writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &position_info},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &guard_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, job->guard_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, job->guard_layout, 0,
                                            guard_writes);
                for (const u32 mode : {u32(CARD_GUARD_DETECT), u32(CARD_GUARD_COLLAPSE)}) {
                    for (CardGuardPush push : job->guard) {
                        push.mode = mode;
                        cmdbuf.pushConstants(job->guard_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                             sizeof(push), &push);
                        const u32 items =
                            mode == u32(CARD_GUARD_DETECT) ? push.triangles : push.vertex_count;
                        cmdbuf.dispatch((items + u32(CARD_GUARD_GROUP) - 1) / u32(CARD_GUARD_GROUP), 1,
                                        1);
                    }
                    // DETECT's flags before COLLAPSE reads them; COLLAPSE's positions before the
                    // check and the builds; the counts for the host (CardSafeLog reads them late)
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute | vk::PipelineStageFlagBits2::eHost,
                                              ShaderAccess | vk::AccessFlagBits2::eHostRead);
                }
            }
"""),
    ("ins", "    if (!card_uv_ready || !card_ring_clean || !entry.card_uv || !need_scene) {\n"
            "        return false;\n    }\n", "",
     r"""    // bbport (r62e_leaf-cards-usable): a cut-out with a skeleton not taken for still (not lone),
    // or a moving rigid one, never gets card UVs (rt_card_still.h); BB_RT_CARD_SAFE=0: as before
    if (CardSafeOn()) {
        const CardStillWhy why =
            CardStillOf(entry.skinned, entry.lone == LampLoneState::Lone, entry.dynamic);
        if (why != CardStillWhy::Still) {
            ++(why == CardStillWhy::Skinned ? card_safe.refused_skinned : card_safe.refused_moving);
            return false;
        }
    }
"""),
    ("ins", "// bbport (r62d_card-uv-diag): the knob's line, and the geometry check's pass and buffers\n",
     r"""// bbport (r62e_leaf-cards-usable): BB_RT_CARD_SAFE, read once. 0: r62e's still rule and guard are off
// (the cut-out shadows as r62c, r62b and r63 left them, to compare in one build); unset or anything
// else: on. Read only with BB_RT_CARD_ALPHA on (CardGuardSetup, CardCaptureCan, CardStillFor).
bool RtShadow::CardSafeOn() {
    static const bool on = [] {
        const char* const env = std::getenv("BB_RT_CARD_SAFE");
        return !(env && std::strcmp(env, "0") == 0);
    }();
    return on;
}

// bbport (r62e_leaf-cards-usable): whether an entry of the lamp card set (PrepareScene,
// BB_RT_CARD_LAMPS=1) may carry CARD_LAMP_MASK by what it is: a still cut-out (CardStillOf)
// whose copy is not stale (an old pose) and was not stale within CardLampHoldFrames
// (CardStaleHoldOff). Counted for CardSafeLog. BB_RT_CARD_SAFE=0, or no card data (CardLampOn
// then says no anyway): r63's rule, not stale.
bool RtShadow::CardStillFor(Entry& entry, bool stale) {
    if (!CardSafeOn() || !entry.card_uv) {
        return !stale;
    }
    const CardStillWhy why =
        CardStillOf(entry.skinned, entry.lone == LampLoneState::Lone, entry.dynamic);
    card_safe_now.skinned += why == CardStillWhy::Skinned ? 1 : 0;
    card_safe_now.moving += why == CardStillWhy::Moving ? 1 : 0;
    if (why != CardStillWhy::Still) {
        return false;
    }
    ++card_safe_now.still;
    const bool on = CardStaleHoldOff(stale, frame, entry.card_uv->lamp_stale, CardLampHoldFrames);
    card_safe_now.stale_off += on ? 0 : 1;
    return on;
}

// bbport (r62e_leaf-cards-usable): the guard's pass and counts (BB_RT_CARD_ALPHA on, at setup), and
// the knob's line, once.
void RtShadow::CardGuardSetup() {
    using enum vk::DescriptorType;
    if (!CardSafeOn()) {
        std::printf("Ray traced lamps (r62e): cut-out shadows (true shape): BB_RT_CARD_SAFE=0: the "
                    "still rule and the guard are off (the cut-outs as r63 left them)\n");
        return;
    }
    card_guard_on =
        EffectPass::Create(instance, guard_set, guard_layout, guard_pipeline,
                           {eStorageBuffer, eStorageBuffer}, sizeof(CardGuardPush),
                           RT_CARD_GUARD_COMP, "Cut-out shadows guard") &&
        Make(card_guard, vk::DeviceSize(CardGuardWords) * 4, true,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        card_guard.mapped;
    if (card_guard_on) {
        std::memset(card_guard.mapped, 0, std::size_t(CardGuardWords) * 4);
    } else {
        Free(card_guard);
    }
    std::printf("Ray traced lamps (r62e): cut-out shadows (true shape), BB_RT_CARD_ALPHA=%u: a "
                "cut-out (a draw whose pixel shader discards by a texture's alpha: leaves, a "
                "lantern's hook, a grille, a chain) stores card UVs, and with BB_RT_CARD_LAMPS=1 "
                "casts its true shape in lamp shadows, only while still (no skeleton and never "
                "moved, or a skeleton no sun shadow pass draws) and not a stale copy (nor within "
                "120 frames of one); guard %s (a cut-out's build with a corner that is not a "
                "number, a vertex past its own or an edge over %g m is dropped from the scene); "
                "BB_RT_CARD_SAFE=0 turns this off\n",
                Shader::Optimization::CardAlphaLevel(),
                card_guard_on ? "on" : "wanted but off - no pipeline or buffer", double(CardGuardEdge));
}

// bbport (r62e_leaf-cards-usable): every 600 frames with BB_RT_CARD_ALPHA on: the lamp card set of the
// last record write by rule, the card mask's first turn-ons and flips, the card UVs refused, and the
// guard (its GPU counts are read as the GPU left them: a frame or two late).
void RtShadow::CardSafeLog() {
    if (!card_uv_on) {
        return;
    }
    const auto* w = card_guard_on ? static_cast<const u32*>(card_guard.mapped) : nullptr;
    std::array<u32, 4> now{};
    char keys[CARD_GUARD_RECORDS * 18 + 1] = "";
    float longest = 0.0f;
    if (w) {
        now = {w[CARD_GUARD_W_DROPPED], w[CARD_GUARD_W_BAD], w[CARD_GUARD_W_NOT_FINITE],
               w[CARD_GUARD_W_RECORDS]};
        std::memcpy(&longest, &w[CARD_GUARD_W_LONGEST], sizeof(longest));
        std::size_t at = 0;
        for (u32 i = 0; i < std::min<u32>(now[3], CARD_GUARD_RECORDS); ++i) {
            const u64 key = u64(w[CARD_GUARD_W_FIRST_RECORD + 2 * i]) |
                            (u64(w[CARD_GUARD_W_FIRST_RECORD + 2 * i + 1]) << 32);
            at += std::size_t(std::snprintf(keys + at, sizeof(keys) - at, " %016llx",
                                            static_cast<unsigned long long>(key)));
        }
    }
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    // The counts a test reads first (the slot worker keeps 300 characters of a line)
    std::printf("Ray traced lamps (r62e): 600 frames: card mask flips %llu (first turn-ons %llu); "
                "guard %s dropped %u builds (%u bad triangles, %u not a number or past the vertices; "
                "%u since the start) of %llu checked (%llu unchecked, over %u a call); lamp card set "
                "of the last write %u still, left out %u with a skeleton not taken for still, %u "
                "moving rigid, %u stale copies held off; card UVs refused %llu with a skeleton, %llu "
                "moving; longest finite bad edge %.4g m; first dropped keys:%s\n",
                ull(card_safe.flips), ull(card_safe.first_on), card_guard_on ? "on" : "off",
                now[0] - card_guard_last[0], now[1] - card_guard_last[1],
                now[2] - card_guard_last[2], now[0], ull(card_safe.guarded),
                ull(card_safe.unguarded), CardGuardSlots, card_safe_now.still,
                card_safe_now.skinned, card_safe_now.moving, card_safe_now.stale_off,
                ull(card_safe.refused_skinned), ull(card_safe.refused_moving), double(longest),
                now[3] != 0 ? keys : " none");
    card_guard_last = now;
    card_safe = {};
}

""", ""),
    ("ins", "        CardLog(); // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1\n", "",
     "        CardSafeLog(); // bbport (r62e_leaf-cards-usable): with BB_RT_CARD_ALPHA on\n"),
]

EDITS[HDR] = [
    ("ins", "        bool lamp_written = false;\n", "",
     r"""        // bbport (r62e_leaf-cards-usable): the bit came once already (a later change is a flip),
        // and the frame + 1 of the last record of a stale copy (CardStaleHoldOff; 0: never)
        bool lamp_once = false;
        u64 lamp_stale = 0;
"""),
    ("ins", "    void CardLog();\n", "",
     r"""    // bbport (r62e_leaf-cards-usable): cut-out shadows (true shape) made safe to turn on
    // (rt_card_still.h). CardStillFor: whether an entry of the lamp card set is a still cut-out,
    // counted in card_safe_now (the last record write); card_safe: the counts since the last
    // CardSafeLog line. The guard (CardGuardSetup; BB_RT_CARD_ALPHA on, BB_RT_CARD_SAFE not 0):
    // rt_card_guard.comp over the builds of entries with card data; card_guard: its counts and flags
    // (host visible); card_guard_last: its counts at the last line.
    struct CardSafeCounts {
        u64 refused_skinned = 0, refused_moving = 0, first_on = 0, flips = 0, guarded = 0,
            unguarded = 0;
    };
    struct CardSafeScene {
        u32 still = 0, skinned = 0, moving = 0, stale_off = 0;
    };
    CardSafeCounts card_safe;
    CardSafeScene card_safe_now;
    bool card_guard_on = false;
    Buffer card_guard;
    std::array<u32, 4> card_guard_last{};
    vk::UniqueDescriptorSetLayout guard_set;
    vk::UniquePipelineLayout guard_layout;
    vk::UniquePipeline guard_pipeline;
    [[nodiscard]] static bool CardSafeOn();
    bool CardStillFor(Entry& entry, bool stale);
    void CardGuardSetup();
    void CardSafeLog();
"""),
]

EDITS[CMK] = [
    ("ins", "    if (FILENAME MATCHES \"^rt_card_uv\")\n        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_uv_layout.h)\n    endif()\n", "",
     "    # bbport (r62e_leaf-cards-usable): the cut-out guard's layout, shared with C++ (rt_card_still.h)\n"
     "    if (FILENAME MATCHES \"^rt_card_guard\")\n"
     "        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_guard_layout.h)\n"
     "    endif()\n"),
    ("ins", "add_host_shader(rt_card_view.comp rt_card_view_comp)\n", "",
     "# bbport (r62e_leaf-cards-usable): the guard of the cut-out builds (BB_RT_CARD_ALPHA on)\n"
     "add_host_shader(rt_card_guard.comp rt_card_guard_comp)\n"),
]

EDITS[TST] = [
    ("ins", '#include "gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h"\n', "",
     '#include <limits>\n#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e)\n'),
    ("ins", '    std::printf("rt lamp cards: ok (of the 64 combinations',
     r"""    {
        // bbport (r62e_leaf-cards-usable): cut-out shadows (true shape). The rule asks only whether a
        // cut-out is still, never what it shows. A wall lantern's hook, a grille or a railing drawn as
        // a textured card (a camera pass draw that discards, no skeleton, never moved): a card at the
        // default level and still, so it gets card UVs and its true shape in lamp shadows.
        Facts hook;
        hook.card_camera = true;
        assert(Card(false, LampCardLevelDefault, hook));
        assert(CardStillOf(hook.skinned, hook.lone, hook.dynamic) == CardStillWhy::Still);
        Facts grille_by_sun;
        grille_by_sun.card_shadow = true;
        assert(Card(false, LampCardLevelDefault, grille_by_sun));
        assert(CardStillOf(false, false, false) == CardStillWhy::Still);
        // The same grille on a moving door or a carried lantern (dynamic): still a card for the lamp
        // rule of before (no lamp shadow, as with the knobs off), but no card UVs and no lamp card bit.
        Facts moving;
        moving.dynamic = true;
        moving.card_camera = true;
        assert(Card(false, LampCardLevelDefault, moving));
        assert(CardStillOf(moving.skinned, moving.lone, moving.dynamic) == CardStillWhy::Moving);
        // Hair or a coat (a skeleton a sun shadow pass draws, or not settled yet): never.
        assert(CardStillOf(true, false, true) == CardStillWhy::Skinned);
        // A bed of plants (a skeleton no sun shadow pass draws: lone; r89's sway moves only these):
        // still, whatever its skeleton does.
        assert(CardStillOf(true, true, true) == CardStillWhy::Still);
        // A stale copy (an old pose) never has the bit, and the bit stays off for `hold` frames
        // after its last stale record (r41's second shadow stays out; no flip at each turn).
        std::uint64_t last_stale = 0;
        bool on = CardStaleHoldOff(false, 5, last_stale, 120);
        assert(on && last_stale == 0);
        on = CardStaleHoldOff(true, 10, last_stale, 120);
        assert(!on && last_stale == 11);
        on = CardStaleHoldOff(false, 130, last_stale, 120);
        assert(!on); // 120 frames after the stale record: still off
        on = CardStaleHoldOff(false, 131, last_stale, 120);
        assert(on);
        on = CardStaleHoldOff(true, 200, last_stale, 120);
        assert(!on && last_stale == 201);
        // The first change of an entry's bit is its turn-on, every later one a flip.
        bool once = false;
        const bool first = CardMaskTurn(once);
        assert(!first && once);
        const bool second = CardMaskTurn(once);
        const bool third = CardMaskTurn(once);
        assert(second && third);
        // The guard's test of a triangle (rt_card_guard.comp DETECT).
        const float inf = std::numeric_limits<float>::infinity();
        const float nan = std::numeric_limits<float>::quiet_NaN();
        float p[16] = {0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1};
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        assert(CardGuardBad(p, 3, 0, 1, 3, CardGuardEdge)); // a vertex past the build's
        p[4] = 199.0f;
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // edges 199 and 199.0025 m
        p[4] = 300.0f;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // an edge of 300 m
        p[4] = inf;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        p[4] = nan;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        p[4] = 3e38f;
        p[8] = -3e38f;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // finite corners, the edge overflows
        p[4] = 1.0f;
        p[8] = 0.0f;
        p[7] = nan; // w is not read
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        // A dropped build (every vertex at the origin) reads as good: nothing for the check to name.
        const float origin[12] = {};
        assert(!CardGuardBad(origin, 3, 0, 1, 2, CardGuardEdge));
        static_assert(CardGuardEdge == 200.0f && CardGuardSlots == 1024 &&
                      CardGuardWords == 32 + 1024);
        std::printf("rt card still (r62e): ok\n");
    }
""", ""),
]

ROW = ("| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` | Cut-out shadows (true shape), in "
       "testing. A cut-out is a draw whose pixel shader discards by a texture's alpha: leaves and weeds, but "
       "also a lantern's hook, a grille or a chain drawn as a textured card. `BB_RT_CARD_ALPHA=2` with "
       "`BB_RT_CARD_LAMPS=1`: lamp rays test a cut-out's texels, so its lamp shadow has the cut-out's shape "
       "instead of none (`BB_RT_CARD_ALPHA=1`: the cut-outs' UVs only; the picture changes only where a "
       "cut-out's build is dropped, below). Only still cut-outs take part: no skeleton and never moved, or "
       "a skeleton that no sun shadow pass draws (a bed of plants, with the game's own sway), and not a "
       "copy in an old pose (nor for 120 frames after one); a moving rigid cut-out and a character's hair "
       "or cloth store no UVs and cast no lamp shadow, as with the knobs off. With `BB_RT_CARD_ALPHA` on, "
       "a cut-out's ray tracing build whose positions hold a corner that is not a number, a vertex past "
       "its own or an edge over 200 m is dropped from the ray traced scene (all its points at the origin: "
       "it casts nothing; a still one until it is rebuilt), counted in the `Ray traced lamps (r62e)` line "
       "every 600 frames. `BB_RT_CARD_SAFE=0`: that rule and the drop off, to compare. About 101 MiB of "
       "GPU memory with `BB_RT_CARD_ALPHA=2`. Read at start | off |\n")
EDITS[RDM] = None  # the README row goes after the BB_RT_GLASS_LIGHT row (the whole line is the anchor)


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_RT_GLASS_LIGHT` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_GLASS_LIGHT row is there %d times, wanted 1" % len(lines))
    return [("ins", lines[0] + "\n", "", ROW)]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def texts_of(e):
    if e[0] == "ins":
        return [t for t in (e[2], e[3]) if t]
    return [e[2]]


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        anchor = e[1]
        mine = texts_of(e)
        counts = [cur.count(t) for t in mine]
        na = cur.count(anchor)
        if e[0] == "rep":
            if counts == [1] and na == 0:
                done += 1
            elif counts == [0] and na == 1:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %s times: %r" % (path, na, counts, anchor[:70]))
            continue
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


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            cur = cur.replace(e[1], e[2] + e[1] + e[3])
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            for t in texts_of(e):
                if cur.count(t) != 1:
                    raise SystemExit("REFUSED revert: inserted text found %d times: %r" % (cur.count(t), t[:70]))
                cur = cur.replace(t, "")
        else:
            if cur.count(e[2]) != 1:
                raise SystemExit("REFUSED revert: new text found %d times: %r" % (cur.count(e[2]), e[2][:70]))
            cur = cur.replace(e[2], e[1])
    return cur


def text_checks(texts):
    c = texts[CPP]
    for want in ("CardGuardSetup(); // bbport (r62e_leaf-cards-usable)", "CardStillFor(*entry, stale)",
                 "bool RtShadow::CardSafeOn()", "void RtShadow::CardSafeLog()", "RT_CARD_GUARD_COMP"):
        if want not in c:
            raise SystemExit("text check: %s lacks %r" % (CPP, want))
    if "card_lamps && card && !stale" in c:
        raise SystemExit("text check: the old lamp_card rule is still there")
    # review fixes: the hold-off, the barrier before the flag fill, the kept line prefix
    for want in ("CardStaleHoldOff(stale, frame, entry.card_uv->lamp_stale, CardLampHoldFrames)",
                 "EffectPass::MemoryBarrier(cmdbuf, Compute, {}, Transfer, {});\n"
                 "                cmdbuf.fillBuffer(job->guard_buffer",
                 '"Ray traced lamps (r62e): 600 frames: card mask flips'):
        if want not in c:
            raise SystemExit("text check: %s lacks %r" % (CPP, want[:60]))
    # the guard runs after the unproject dispatches and before the geometry check
    a = c.find("for (const UnprojectPush& push : job->unproject)")
    b = c.find("if (job->guard_pipeline) {")
    g = c.find("if (job->geo_pipeline) {")
    if not (0 <= a < b < g):
        raise SystemExit("text check: the guard is not between the unproject pass and the check")
    if "CARD_GUARD_W_FLAGS 32" not in texts[HS + "rt_card_guard_layout.h"]:
        raise SystemExit("text check: layout")
    if texts[RDM].count("| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` |") != 1:
        raise SystemExit("text check: README row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62E_LEAF_CARDS_USABLE_ROOT)" % ROOT)
    plan = []
    for path in (CPP, HDR, CMK, TST, RDM):
        raw, eol, cur = load(path)
        if path == RDM:
            EDITS[RDM] = readme_edits(cur)
        plan.append((path, raw, eol, cur, state_of(cur, EDITS[path], path)))
    new_state = []
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            new_state.append("clean")
        else:
            on_disk = open(full, "rb").read()
            if on_disk == text.replace("\n", "\r\n").encode("utf-8"):
                new_state.append("applied")
            else:
                raise SystemExit("REFUSED %s exists and is not this patch's text" % path)
    states = {p[4] for p in plan} | set(new_state)
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan) +
                         "; new files " + ", ".join(new_state))
    state = states.pop()
    if cmd == "check":
        texts = {}
        for path, raw, eol, cur, st in plan:
            texts[path] = cur if st == "applied" else apply_text(cur, EDITS[path])
            if state_of(texts[path], EDITS[path], path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
        texts.update(NEW)
        text_checks(texts)
        print("applied (text checks pass)" if state == "applied" else
              "not applied; would apply (%d files, %d edits, %d new files; text checks on the result pass)"
              % (len(plan), sum(len(EDITS[p[0]]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state != "clean":
            raise SystemExit("REFUSED apply: already applied")
        for path in NEW:  # nothing is written unless every new file can be
            if not os.path.isdir(os.path.dirname(os.path.join(ROOT, path))):
                raise SystemExit("REFUSED apply: no folder for %s" % path)
        os.makedirs(BACKUP, exist_ok=True)
        outs = []
        for path, raw, eol, cur, st in plan:
            out = apply_text(cur, EDITS[path])
            if state_of(out, EDITS[path], path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            outs.append((path, raw, out.replace("\n", eol).encode("utf-8")))
        texts = {p: o.decode("utf-8").replace("\r\n", "\n") for p, r, o in outs}
        texts.update(NEW)
        text_checks(texts)
        for path, raw, data in outs:
            bk = os.path.join(BACKUP, path.replace("/", "__"))
            open(bk, "wb").write(raw)
            open(os.path.join(ROOT, path), "wb").write(data)
        for path, text in NEW.items():
            open(os.path.join(ROOT, path), "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
        print("applied: %d files edited, %d new files; backups in %s" % (len(outs), len(NEW), BACKUP))
        return
    if state != "applied":
        raise SystemExit("REFUSED revert: not applied")
    for path, raw, eol, cur, st in plan:
        out = revert_text(cur, EDITS[path])
        if state_of(out, EDITS[path], path) != "clean":
            raise SystemExit("%s: the revert does not read as clean" % path)
        open(os.path.join(ROOT, path), "wb").write(out.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted: %d files, %d new files removed" % (len(plan), len(NEW)))


if __name__ == "__main__":
    main()
