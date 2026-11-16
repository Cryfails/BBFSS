# r62d_card-uv-diag: a DIAGNOSIS build for the BB_RT_CARD_ALPHA=1 slowdown at the save copy
# "lamp-test-spot" (2-3 FPS instead of 95: "Lighting: point shadows" 64-188 ms, "indirect light"
# 83-239 ms; lamp rays and bounce rays walk something huge, sun rays only 3.5x slower). One knob,
# BB_RT_CARD_UV_DIAG, read once at start; unset or 0 = today's behaviour exactly (the same pipeline
# keys, SPIR-V, commands and log). Plus a geometry check that PROVES or rules out broken BLAS input.
#
# Use: cd <tree> && python -I -X utf8 r62d_card-uv-diag.py check | apply | revert
# (the tree: R62D_ROOT, else the current directory). Every edit is an exact text found exactly
# once; revert gives the files back byte for byte (the new shader file is removed after its bytes
# are checked). Line ends are kept (all touched files are CRLF; the new file is written CRLF).
# Nothing is written before every text of the mode is made. Originals: r62d_orig/, patched (as
# written) r62d_work/, the new shader r62d_src/ beside this script.
#
# On top of <tree> as it is on 2026-11-15 (upstream 78c7449, r62, r61, r65, r64, r67, r68).
# r64b (vk_rt_shadow.h/.cpp, vk_rasterizer*): no hunk here touches a text r64b anchors on;
# checked both orders on a copy. r62b and r63 (later) check and apply before and after this one
# on a copy, none needs re-anchoring (r62d_proof.sh, orders a to f, all round trips byte exact).
#
# THE KNOB  BB_RT_CARD_UV_DIAG (0 to 5; anything else is said once and taken as 0)
#  0  as today.
#  1  RtShadow::CardCaptureCan says no: no UV capture, no UV-only probe, no expand pass, no card
#     ring writes past the first fill. Capture pipelines KEEP CaptureUv (recompiler SPIR-V).
#     Tests candidate A (the UV captures/probes and what they do to the positions and budgets).
#  2  as 1, and no capture pipeline gets CaptureUv: their vertex shaders are the lifter's again,
#     exactly the keys and modules of BB_RT_CARD_ALPHA=0 (the warm-up takes cached knob-0 records,
#     refuses CaptureUv records). Tests candidate B (recompiler instead of lifter for every
#     capture vertex shader, also the ordinary non-card ones).
#  3  FIX A: every RecordBuilds call ends with an execution dependency from its BLAS builds and
#     world copies (they READ the positions) to later vertex shaders and compute passes (captures
#     WRITE the positions again from 0 after the call's reset; today only AsBuild->AsBuild
#     follows, a write-after-read hazard). UV captures as today.
#  4  FIX B: CaptureUv only on capture pipelines whose pixel shader discards (the only draws whose
#     UVs are ever captured: ResolveCardDraw needs has_discard). Every other capture pipeline is
#     the lifter's again, as with the knob off. UV captures as today.
#  5  3 and 4.
# BB_RT_GEOMETRY_CHECK=1: the geometry check without the diag knob (it is on with any diag value
# 1-5 too). BB_RT_GEOMETRY_CHECK_EDGE=<metres> (default 200, 1 to 100000): the "huge" edge; "big"
# is an eighth of it.
#
# THE GEOMETRY CHECK (rt_geometry_check.comp, one dispatch per BLAS build, after the unproject
# pass, before the build): for each triangle of the entry's own index list (what the build reads):
# an index past vertices*instances (the build would read another entry's positions), a corner
# that is not finite, the longest edge over 200 m ("huge") and over 25 m ("big"), and the longest
# finite edge. Workgroups with a bad triangle write a record naming the build (key, vertex shader,
# refit or build, camera/sun mask, moving, shared copy, instance, skinned, card, held, UV capture).
# One line per window: 600 frames OR 10 s, whichever first (at 2.7 FPS a 600-frame window would
# never print in a 30 s run), plus up to 8 "bad build" lines. A due window is copied by the next
# RecordBuilds call, or at frame end on its own when no call comes (nothing built or refit); a
# window without any call prints "0 calls" from the host alone. The check is race-free only with
# fix A (3 or 5): without it nothing orders its reads before later captures' writes either.
#
# CACHE: a capture variant takes the next permutation index of its program, and its records
# (pgm_hash_N, HashCombine(hash, N)) overwrite those another pipeline rule saved at that index.
# Rules: {BB_RT_CARD_ALPHA off, 2}, {0, 1, 3}, {4, 5}. With BB_RT_CARD_UV_DIAG 1-5 the warm-up
# also refuses a capture key whose loaded vertex module's CaptureUv differs from the key's (no
# draw would take it); with 0 the warm-up is as before.
#
# COST. Knob off and no BB_RT_GEOMETRY_CHECK: one int compare per CardCaptureCan, one bool per
# RecordBuilds job, CaptureUvWanted() instead of CardAlphaOn() at pipeline-key time (a cached
# static); nothing recorded, no buffer, no pipeline, no line. With the check: one small dispatch
# per BLAS build (reads indices + 3 positions a triangle; ~0.01-0.05 ms a frame for a few hundred
# thousand triangles, estimate, NOT measured), 544 B device + 544 B host memory, a 544-byte copy
# every window (at frame end, with a render pass end, when no build call copies it), one clock
# read a frame. Fix A: one execution barrier per RecordBuilds call (vertex work after it waits for
# the builds: estimate <= 0.1 ms lost overlap). Fix B: none (fewer recompiler modules).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = (os.environ.get("R62D_ROOT") or os.getcwd()).replace("\\", "/").rstrip("/") + "/"
G = "engine/gpu/"
SR = G + "shadps4/shader_recompiler/ir/passes/"
VK = G + "shadps4/video_core/renderer_vulkan/"
HS = G + "shadps4/video_core/host_shaders/"
TMP = ".r62dtmp"

NEW_SHADER = HS + "rt_geometry_check.comp"

EDITS = {
    # ------------------------------------------------------------------ the knob
    SR + "cutout_analysis.h": [(r"""/// (r62_leaf-stage3) BB_RT_CARD_ALPHA's level, read once (Vulkan::ReadCardAlpha): 0 off, 1 the
/// card UVs, 2 the UVs and the alpha layers (CardAlpha). CardAlphaOn() is level >= 1.
[[nodiscard]] u32 CardAlphaLevel();
""", r"""/// (r62_leaf-stage3) BB_RT_CARD_ALPHA's level, read once (Vulkan::ReadCardAlpha): 0 off, 1 the
/// card UVs, 2 the UVs and the alpha layers (CardAlpha). CardAlphaOn() is level >= 1.
[[nodiscard]] u32 CardAlphaLevel();

/// (r62d_card-uv-diag) BB_RT_CARD_UV_DIAG, read once: the diagnosis of the BB_RT_CARD_ALPHA=1
/// slowdown (RtShadow::GeoCheckSetup prints what the value does). 0 or unset: as before. A
/// value other than 0 to 5 is said once in the log and taken as 0.
[[nodiscard]] u32 CardUvDiag();

/// (r62d_card-uv-diag) Whether a capture pipeline's key and vertex shader get the card UVs
/// (MotionVectors::CaptureUv): CardAlphaOn(), except with BB_RT_CARD_UV_DIAG=2 (never) and 4 or
/// 5 (only when its pixel shader discards: `discards`). With 0, 1 and 3 it is CardAlphaOn().
[[nodiscard]] bool CaptureUvWanted(bool discards);
""")],
    SR + "cutout_analysis_pass.cpp": [(r"""bool CardAlphaOn() {
    return CardAlphaLevel() >= Vulkan::CardAlphaUv; // (r62_leaf-stage3) 2: the UVs and the layers
}
""", r"""bool CardAlphaOn() {
    return CardAlphaLevel() >= Vulkan::CardAlphaUv; // (r62_leaf-stage3) 2: the UVs and the layers
}

// (r62d_card-uv-diag) BB_RT_CARD_UV_DIAG, read once
u32 CardUvDiag() {
    static const u32 diag = [] {
        const char* env = std::getenv("BB_RT_CARD_UV_DIAG");
        if (!env || env[0] == '\0') {
            return 0u;
        }
        if (env[1] == '\0' && env[0] >= '0' && env[0] <= '5') {
            return u32(env[0] - '0');
        }
        std::printf("Ray tracing card UV diagnosis (r62d): BB_RT_CARD_UV_DIAG=%.16s is not 0 to 5: "
                    "taken as 0\n",
                    env);
        return 0u;
    }();
    return diag;
}

bool CaptureUvWanted(bool discards) {
    const u32 diag = CardUvDiag();
    return CardAlphaOn() && diag != 2 && ((diag != 4 && diag != 5) || discards);
}
""")],
    # ------------------------------------------------------------------ candidate B / fix B
    VK + "vk_pipeline_cache.cpp": [(r"""const Shader::RuntimeInfo& PipelineCache::BuildRuntimeInfo(PipelineSelection& sel, HwStage stage,
""", r"""// bbport (r62d_card-uv-diag): whether the selection's pixel shader discards (bound before the
// vertex stage, RefreshGraphicsStages), for CaptureUvWanted
static bool FragmentDiscards(const PipelineSelection& sel) {
    const auto* fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
    return fs && fs->has_discard;
}

const Shader::RuntimeInfo& PipelineCache::BuildRuntimeInfo(PipelineSelection& sel, HwStage stage,
"""), (r"""        info.hw.vs.motion_vectors =
            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0) |
               (sel.capture && Shader::Optimization::CardAlphaOn() ? Shader::MotionVectors::CaptureUv
                                                                    : 0));
""", r"""        // bbport (r62d_card-uv-diag): CaptureUvWanted is CardAlphaOn() unless
        // BB_RT_CARD_UV_DIAG is 2 (never) or 4/5 (with a pixel shader that discards only)
        info.hw.vs.motion_vectors =
            u8((sel.capture ? Shader::MotionVectors::VertexCapture : 0) | (sel.motion ? 1 : 0) |
               (sel.capture && Shader::Optimization::CaptureUvWanted(FragmentDiscards(sel))
                    ? Shader::MotionVectors::CaptureUv
                    : 0));
"""), (r"""        if (Shader::Optimization::CardAlphaOn()) { // bbport (r54_leaf-stage2)
            key.motion_vectors |= Shader::MotionVectors::CaptureUv;
        }
""", r"""        // bbport (r54_leaf-stage2, r62d_card-uv-diag): as the vertex stage's runtime info
        if (Shader::Optimization::CaptureUvWanted(FragmentDiscards(sel))) {
            key.motion_vectors |= Shader::MotionVectors::CaptureUv;
        }
""")],
    VK + "vk_pipeline_serialization.cpp": [(r"""    if (((sel.graphics_key.motion_vectors & Shader::MotionVectors::CaptureUv) != 0) !=
        ((sel.graphics_key.motion_vectors & Shader::MotionVectors::VertexCapture) != 0 &&
         Shader::Optimization::CardAlphaOn())) {
        return false;
    }
""", r"""    // bbport (r62d_card-uv-diag): nor one of another BB_RT_CARD_UV_DIAG rule (CaptureUvWanted:
    // with 0, 1 and 3 the test of before). With 4 or 5 a capture key has the card UVs exactly
    // when its pixel shader discards: checked once the stages are loaded (uv_by_fragment).
    const bool key_uv = (sel.graphics_key.motion_vectors & Shader::MotionVectors::CaptureUv) != 0;
    const bool key_capture =
        (sel.graphics_key.motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
    const bool uv_by_fragment = key_capture && Shader::Optimization::CaptureUvWanted(true) &&
                                !Shader::Optimization::CaptureUvWanted(false);
    if (!uv_by_fragment &&
        key_uv != (key_capture && Shader::Optimization::CaptureUvWanted(true))) {
        return false;
    }
"""), (r"""        expected.unified += warmup_count[stage_idx].unified;
        expected.buffer += warmup_count[stage_idx].buffer;
    }
""", r"""        expected.unified += warmup_count[stage_idx].unified;
        expected.buffer += warmup_count[stage_idx].buffer;
    }
    // bbport (r62d_card-uv-diag): BB_RT_CARD_UV_DIAG=4 or 5, see above (a key without a
    // fragment stage has no pixel shader that discards; sel.infos may hold an earlier key's)
    if (uv_by_fragment) {
        const auto* fs = sel.graphics_key.stage_hashes[u32(Shader::SwStage::Fragment)]
                             ? sel.infos[u32(Shader::SwStage::Fragment)]
                             : nullptr;
        if (key_uv != Shader::Optimization::CaptureUvWanted(fs && fs->has_discard)) {
            return false;
        }
    }
    // bbport (r62d_card-uv-diag): with BB_RT_CARD_UV_DIAG 1 to 5, nor a capture key whose vertex
    // module (the permutation its record names) has the card UVs other than the key: a run of
    // another rule saved its own module at that index. No draw takes that pipeline (a live draw
    // takes only a module of its own specialization, CaptureUv included), so it is not built.
    if (key_capture && Shader::Optimization::CardUvDiag() != 0 &&
        sel.graphics_key.stage_hashes[u32(Shader::SwStage::Vertex)]) {
        const auto& vs_loaded = sel.runtime_infos[u32(Shader::SwStage::Vertex)];
        if (vs_loaded.hw_stage == Shader::HwStage::Vertex &&
            ((vs_loaded.hw.vs.motion_vectors & Shader::MotionVectors::CaptureUv) != 0) != key_uv) {
            return false;
        }
    }
""")],
    # ------------------------------------------------------------------ the new pass's build
    G + "CMakeLists.txt": [(r"""add_host_shader(rt_unproject.comp rt_unproject_comp)
""", r"""add_host_shader(rt_unproject.comp rt_unproject_comp)
# bbport (r62d_card-uv-diag): the geometry check of the BLAS inputs (BB_RT_CARD_UV_DIAG not 0,
# or BB_RT_GEOMETRY_CHECK=1)
add_host_shader(rt_geometry_check.comp rt_geometry_check_comp)
""")],
    # ------------------------------------------------------------------ RtShadow
    VK + "vk_rt_shadow.h": [(r"""        bool fast = false; // bbport (r17_rt-upkeep): ePreferFastBuild, no eAllowUpdate
        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
""", r"""        bool fast = false; // bbport (r17_rt-upkeep): ePreferFastBuild, no eAllowUpdate
        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
        u64 vs_hash = 0;   // bbport (r62d_card-uv-diag): Draw::shader (the geometry check's line)
"""), (r"""    vk::UniqueDescriptorSetLayout card_set;
    vk::UniquePipelineLayout card_layout;
    vk::UniquePipeline card_pipeline;
""", r"""    vk::UniqueDescriptorSetLayout card_set;
    vk::UniquePipelineLayout card_layout;
    vk::UniquePipeline card_pipeline;
    // bbport (r62d_card-uv-diag): card_diag: BB_RT_CARD_UV_DIAG (read at Setup). The geometry
    // check (GeoCheckSetup; on with card_diag not 0 or BB_RT_GEOMETRY_CHECK=1): geo_on when its
    // pass and buffers are there. geo_buffer: the counts its dispatches add to (zeroed at its
    // first use and after each copy); geo_readback: that copy, read by GeoCheckFrameEnd once the
    // GPU is past geo_tick (geo_pending). geo_infos: this window's checked builds by serial;
    // geo_read: those of the window whose copy is awaited. A window: 600 frames or 10 s; it is
    // copied by the RecordBuilds call that finds it due, else by GeoCheckFrameEnd on its own.
    struct GeoCheckInfo {
        u64 key;
        u64 vs_hash;
        u32 triangles;
        u32 flags;
    };
    struct GeoCheckWindow {
        u64 builds = 0, refits = 0, triangles = 0, calls = 0, frames = 0;
    };
    u32 card_diag = 0;
    bool geo_on = false;
    bool geo_clean = false;
    bool geo_pending = false;
    float geo_huge = 200.0f;
    Buffer geo_buffer, geo_readback;
    vk::UniqueDescriptorSetLayout geo_set;
    vk::UniquePipelineLayout geo_layout;
    vk::UniquePipeline geo_pipeline;
    u64 geo_tick = 0;
    u64 geo_frame = 0;
    u64 geo_time = 0; // milliseconds (steady clock)
    std::vector<GeoCheckInfo> geo_infos, geo_read;
    GeoCheckWindow geo_window, geo_read_window;
    void GeoCheckSetup();
    void GeoCheckTakeWindow(u64 now);
    void GeoCheckFrameEnd();
    void GeoCheckPrint();
""")],
    VK + "vk_rt_shadow.cpp": [(r"""#include <bit> // bbport (r54_leaf-stage2)
""", r"""#include <bit> // bbport (r54_leaf-stage2)
#include <chrono> // bbport (r62d_card-uv-diag)
"""), (r"""#include "video_core/host_shaders/rt_unproject_comp.h"
""", r"""#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/rt_geometry_check_comp.h" // bbport (r62d_card-uv-diag)
"""), (r"""constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;
""", r"""constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;

// bbport (r62d_card-uv-diag): rt_geometry_check.comp's push constants and its counts (words 0
// triangles, 1 index out of range, 2 not finite, 3 over "huge", 4 over "big", 5 longest edge's
// bits, 6 records written, 8.. GeoCheckRecords records of 4 words: serial, out of range or not
// finite, over "huge", longest edge's bits), and its knobs (each read once).
struct GeoCheckPush {
    u64 indices;
    u32 store;
    u32 triangles;
    u32 vertex_count;
    u32 serial;
    float huge;
    float big;
};
static_assert(sizeof(GeoCheckPush) == 32 && offsetof(GeoCheckPush, store) == 8 &&
              offsetof(GeoCheckPush, big) == 28);
constexpr u32 GeoCheckRecords = 32;
constexpr u32 GeoCheckWords = 8 + 4 * GeoCheckRecords;
constexpr u32 GeoCheckInfosMost = 1u << 16; // builds named in one window (serial past: unnamed)
constexpr u32 GeoCheckLines = 8;            // "bad build" lines a window
constexpr u64 GeoCheckFrames = 600;
constexpr u64 GeoCheckMs = 10000;
constexpr float GeoCheckEdgeDefault = 200.0f;

static bool GeoCheckKnob() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_GEOMETRY_CHECK");
        return env && std::strcmp(env, "1") == 0;
    }();
    return on;
}

static float GeoCheckEdge() {
    static const float edge = [] {
        const char* env = std::getenv("BB_RT_GEOMETRY_CHECK_EDGE");
        if (!env || env[0] == '\0') {
            return GeoCheckEdgeDefault;
        }
        char* end = nullptr;
        const double metres = std::strtod(env, &end);
        return end && *end == '\0' && metres >= 1.0 && metres <= 100000.0 ? float(metres)
                                                                          : GeoCheckEdgeDefault;
    }();
    return edge;
}

static u64 GeoCheckNowMs() {
    return u64(std::chrono::duration_cast<std::chrono::milliseconds>(
                   std::chrono::steady_clock::now().time_since_epoch())
                   .count());
}

// The counts to the host (after the check's dispatches) and back to 0 (before the next ones).
static void GeoCheckFlush(vk::CommandBuffer cmdbuf, vk::Buffer counts, vk::Buffer readback) {
    constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
    constexpr auto ShaderAccess = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
    constexpr vk::DeviceSize geo_bytes = GeoCheckWords * 4;
    EffectPass::MemoryBarrier(cmdbuf, Compute, ShaderAccess, Transfer,
                              vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
    cmdbuf.copyBuffer(counts, readback, vk::BufferCopy{0, 0, geo_bytes});
    EffectPass::MemoryBarrier(cmdbuf, Transfer,
                              vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite,
                              Transfer | vk::PipelineStageFlagBits2::eHost,
                              vk::AccessFlagBits2::eTransferWrite | vk::AccessFlagBits2::eHostRead);
    cmdbuf.fillBuffer(counts, 0, geo_bytes, 0);
    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                              ShaderAccess);
}
"""), (r"""    Free(still_sigs); // bbport (r47_still-check)
    Free(still_readback);
""", r"""    Free(still_sigs); // bbport (r47_still-check)
    Free(still_readback);
    Free(geo_buffer); // bbport (r62d_card-uv-diag)
    Free(geo_readback);
"""), (r"""    if (card_uv_on) {
        CardSetup();
    }
""", r"""    if (card_uv_on) {
        CardSetup();
    }
    GeoCheckSetup(); // bbport (r62d_card-uv-diag): the knob's line; nothing with it 0
"""), (r"""        builds.back().inputs = draw.inputs;
""", r"""        builds.back().inputs = draw.inputs;
        builds.back().vs_hash = draw.shader; // bbport (r62d_card-uv-diag)
"""), (r"""        std::vector<CardUvPush> card;
        u32 card_stat_mask = 0;
""", r"""        std::vector<CardUvPush> card;
        u32 card_stat_mask = 0;
        // bbport (r62d_card-uv-diag): the geometry check's dispatches (geo_pipeline set: the
        // check is on), its first zeroing, the copy for the host, and fix A's barrier
        std::vector<GeoCheckPush> geo;
        vk::Pipeline geo_pipeline{};
        vk::PipelineLayout geo_layout{};
        vk::Buffer geo_buffer{}, geo_readback{};
        bool geo_clear = false;
        bool geo_flush = false;
        bool war_barrier = false;
"""), (r"""        job->ranges.push_back({.primitiveCount = e.triangles});
        job->pointers.push_back(&job->ranges.back());
""", r"""        job->ranges.push_back({.primitiveCount = e.triangles});
        job->pointers.push_back(&job->ranges.back());
        // bbport (r62d_card-uv-diag): the geometry check of what this build reads
        if (geo_on) {
            u32 serial = 0xffffffffu;
            if (geo_infos.size() < GeoCheckInfosMost) {
                serial = u32(geo_infos.size());
                const u32 flags =
                    (build.update ? 1u : 0u) | (build.fast ? 2u : 0u) |
                    ((e.mask & CameraMask) != 0 ? 4u : 0u) | ((e.mask & ShadowMask) != 0 ? 8u : 0u) |
                    (e.dynamic ? 16u : 0u) | (e.rebuilt ? 32u : 0u) | (e.instance ? 64u : 0u) |
                    (e.skinned ? 128u : 0u) | (e.card_uv != nullptr ? 256u : 0u) |
                    (e.held ? 512u : 0u) | (build.uv_base != 0 ? 1024u : 0u);
                geo_infos.push_back({e.base, build.vs_hash, e.triangles, flags});
            }
            job->geo.push_back({e.indices.address, build.store, e.triangles,
                                e.vertices * e.instances, serial, geo_huge, geo_huge / 8.0f});
            ++geo_window.builds;
            geo_window.refits += build.update ? 1 : 0;
            geo_window.triangles += e.triangles;
        }
"""), (r"""    EffectPass::Mark(16, "ray tracing geometry");
""", r"""    // bbport (r62d_card-uv-diag): BB_RT_CARD_UV_DIAG=3 or 5 (fix A). This call's builds and world
    // copies read the positions; captures recorded after it write them again from 0 (the reset
    // above), and only an AsBuild->AsBuild barrier followed: nothing ordered those writes after
    // the reads. An execution dependency at the end of the call does (a write after a read needs
    // no memory dependency).
    job->war_barrier = card_diag == 3 || card_diag == 5;
    if (geo_on) {
        job->geo_pipeline = *geo_pipeline;
        job->geo_layout = *geo_layout;
        job->geo_buffer = geo_buffer.buffer;
        job->geo_readback = geo_readback.buffer;
        job->geo_clear = !geo_clean;
        geo_clean = true;
        ++geo_window.calls;
        const u64 now = GeoCheckNowMs();
        if (!geo_pending && (frame >= geo_frame + GeoCheckFrames || now >= geo_time + GeoCheckMs)) {
            job->geo_flush = true;
            GeoCheckTakeWindow(now);
        }
    }
    EffectPass::Mark(16, "ray tracing geometry");
"""), (r"""                cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                   AsBuild | vk::PipelineStageFlagBits2::eCopy,
""", r"""                cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
            }
            // bbport (r62d_card-uv-diag): the geometry check of what the builds below read (after
            // the pass above wrote it; it only reads the positions), and once a window the counts
            // to the host and back to 0
            if (job->geo_pipeline) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr auto ShaderAccess =
                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
                constexpr vk::DeviceSize geo_bytes = GeoCheckWords * 4;
                if (job->geo_clear) {
                    cmdbuf.fillBuffer(job->geo_buffer, 0, geo_bytes, 0);
                }
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderAccess);
                if (!job->geo.empty()) {
                    const vk::DescriptorBufferInfo count_info{job->geo_buffer, 0, VK_WHOLE_SIZE};
                    const std::array<vk::WriteDescriptorSet, 2> geo_writes{{
                        {.dstBinding = 0, .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &position_info},
                        {.dstBinding = 1, .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &count_info},
                    }};
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, job->geo_pipeline);
                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, job->geo_layout, 0,
                                                geo_writes);
                    for (const GeoCheckPush& push : job->geo) {
                        cmdbuf.pushConstants(job->geo_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                             sizeof(push), &push);
                        cmdbuf.dispatch((push.triangles + 63) / 64, 1, 1);
                    }
                }
                if (job->geo_flush) {
                    GeoCheckFlush(cmdbuf, job->geo_buffer, job->geo_readback);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                   AsBuild | vk::PipelineStageFlagBits2::eCopy,
"""), (r"""            EffectPass::MemoryBarrier(cmdbuf, AsBuild, vk::AccessFlagBits2::eAccelerationStructureWriteKHR, AsBuild,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR);
        });
""", r"""            EffectPass::MemoryBarrier(cmdbuf, AsBuild, vk::AccessFlagBits2::eAccelerationStructureWriteKHR, AsBuild,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR);
            if (job->war_barrier) { // bbport (r62d_card-uv-diag): fix A (see above)
                EffectPass::MemoryBarrier(cmdbuf, AsBuild | vk::PipelineStageFlagBits2::eCopy, {},
                                          vk::PipelineStageFlagBits2::eVertexShader | Compute, {});
            }
        });
"""), (r"""bool RtShadow::CardCaptureCan(Entry& entry, const Draw& draw) {
    if (!card_uv_ready || !card_ring_clean || !entry.card_uv || !need_scene) {
""", r"""bool RtShadow::CardCaptureCan(Entry& entry, const Draw& draw) {
    // bbport (r62d_card-uv-diag): BB_RT_CARD_UV_DIAG=1 or 2: never (no capture, no probe, so
    // no expand pass)
    if (card_diag == 1 || card_diag == 2) {
        return false;
    }
    if (!card_uv_ready || !card_ring_clean || !entry.card_uv || !need_scene) {
"""), (r"""// Destroy: the block and slot are freed once the GPU is past what was recorded so far (an
""", r"""// bbport (r62d_card-uv-diag): the knob's line, and the geometry check's pass and buffers
// (BB_RT_CARD_UV_DIAG not 0, or BB_RT_GEOMETRY_CHECK=1). Without them nothing is checked.
void RtShadow::GeoCheckSetup() {
    using enum vk::DescriptorType;
    card_diag = Shader::Optimization::CardUvDiag();
    const bool wanted = card_diag != 0 || GeoCheckKnob();
    if (!wanted) {
        return;
    }
    geo_huge = GeoCheckEdge();
    geo_on = EffectPass::Create(instance, geo_set, geo_layout, geo_pipeline,
                                {eStorageBuffer, eStorageBuffer}, sizeof(GeoCheckPush),
                                RT_GEOMETRY_CHECK_COMP, "Ray tracing geometry check") &&
             Make(geo_buffer, GeoCheckWords * 4, false,
                  VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
             Make(geo_readback, GeoCheckWords * 4, true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
             geo_readback.mapped;
    if (geo_on) {
        std::memset(geo_readback.mapped, 0, GeoCheckWords * 4);
        geo_time = GeoCheckNowMs();
        geo_infos.reserve(4096);
    } else {
        Free(geo_buffer);
        Free(geo_readback);
    }
    static constexpr const char* What[] = {
        "as before",
        "no card UV capture, no UV-only probe, no expand pass; capture pipelines keep the card "
        "UVs (recompiler vertex shaders)",
        "no card UV capture, probe or expand pass, and no capture pipeline has the card UVs "
        "(lifter vertex shaders, as with BB_RT_CARD_ALPHA=0)",
        "fix A: an execution barrier from each call's BLAS builds and copies to later vertex "
        "shaders and compute passes; captures as before",
        "fix B: the card UVs only on capture pipelines whose pixel shader discards (the others "
        "are the lifter's); captures as before",
        "fixes A and B"};
    std::printf("Ray tracing card UV diagnosis (r62d): BB_RT_CARD_UV_DIAG=%u: %s; BB_RT_CARD_ALPHA "
                "level %u; geometry check %s (edges over %g m and %g m counted, a line every %llu "
                "frames or %llu s)\n",
                card_diag, What[card_diag < 6 ? card_diag : 0],
                Shader::Optimization::CardAlphaLevel(),
                geo_on ? "on" : "wanted but off - no pipeline or buffer", double(geo_huge),
                double(geo_huge / 8.0f), static_cast<unsigned long long>(GeoCheckFrames),
                static_cast<unsigned long long>(GeoCheckMs / 1000));
}

// bbport (r62d_card-uv-diag): the open window becomes the one whose copy is awaited (from the
// tick recorded now), and a new window starts.
void RtShadow::GeoCheckTakeWindow(u64 now) {
    geo_pending = true;
    geo_tick = scheduler.CurrentTick();
    geo_read.swap(geo_infos);
    geo_infos.clear();
    geo_read_window = geo_window;
    geo_read_window.frames = frame - geo_frame;
    geo_window = {};
    geo_frame = frame;
    geo_time = now;
}

// bbport (r62d_card-uv-diag): a window's counts, once the GPU is past their copy (asked once a
// frame while one is awaited; no wait). The records name the builds by their serial. A window
// that is due while no RecordBuilds call came to copy it (no BLAS built or refit since: a still
// stretch, or the last calls of a loading burst) is copied here on its own; one without any
// call says so on the host alone.
void RtShadow::GeoCheckFrameEnd() {
    if (!geo_on) {
        return;
    }
    if (geo_pending && scheduler.IsFree(geo_tick)) {
        geo_pending = false;
        GeoCheckPrint();
    }
    if (geo_pending) {
        return;
    }
    const u64 now = GeoCheckNowMs();
    if (frame < geo_frame + GeoCheckFrames && now < geo_time + GeoCheckMs) {
        return;
    }
    if (geo_window.calls == 0 || !geo_clean) {
        std::printf("Ray tracing geometry check (r62d, BB_RT_CARD_UV_DIAG=%u, BB_RT_CARD_ALPHA=%u): "
                    "%llu frames, 0 calls: no BLAS built or refit, nothing checked\n",
                    card_diag, Shader::Optimization::CardAlphaLevel(),
                    static_cast<unsigned long long>(frame - geo_frame));
        geo_infos.clear();
        geo_window = {};
        geo_frame = frame;
        geo_time = now;
        return;
    }
    GeoCheckTakeWindow(now);
    scheduler.EndRendering();
    scheduler.Record([counts = geo_buffer.buffer, readback = geo_readback.buffer](
                         vk::CommandBuffer cmdbuf) { GeoCheckFlush(cmdbuf, counts, readback); });
}

// bbport (r62d_card-uv-diag): the line of the window whose copy the GPU is past
void RtShadow::GeoCheckPrint() {
    const auto* w = static_cast<const u32*>(geo_readback.mapped);
    const auto metres = [](u32 bits) { return double(std::bit_cast<float>(bits)); };
    const GeoCheckWindow& g = geo_read_window;
    std::printf("Ray tracing geometry check (r62d, BB_RT_CARD_UV_DIAG=%u, BB_RT_CARD_ALPHA=%u): "
                "%llu frames, %llu calls, %llu BLAS inputs (%llu refits) of %llu triangles sent, "
                "%u checked; index out of range %u, not finite %u, longest edge over %g m %u, "
                "over %g m %u; longest finite edge %.4g m; %u bad records\n",
                card_diag, Shader::Optimization::CardAlphaLevel(),
                static_cast<unsigned long long>(g.frames), static_cast<unsigned long long>(g.calls),
                static_cast<unsigned long long>(g.builds), static_cast<unsigned long long>(g.refits),
                static_cast<unsigned long long>(g.triangles), w[0], w[1], w[2], double(geo_huge),
                w[3], double(geo_huge / 8.0f), w[4], metres(w[5]), w[6]);
    const u32 records = std::min(w[6], GeoCheckRecords);
    std::array<u32, GeoCheckLines> said{};
    u32 lines = 0;
    for (u32 r = 0; r < records && lines < GeoCheckLines; ++r) {
        const u32* rec = w + 8 + 4 * r;
        const u32 serial = rec[0];
        if (std::find(said.begin(), said.begin() + lines, serial) != said.begin() + lines) {
            continue;
        }
        said[lines++] = serial;
        if (serial >= geo_read.size()) {
            std::printf("Ray tracing geometry check (r62d): bad build (not named, serial %u): %u "
                        "out of range or not finite, %u over %g m, longest %.4g m (one workgroup)\n",
                        serial, rec[1], rec[2], double(geo_huge), metres(rec[3]));
            continue;
        }
        const GeoCheckInfo& i = geo_read[serial];
        const u32 f = i.flags;
        std::printf("Ray tracing geometry check (r62d): bad build: key %016llx vs %016llx, %u "
                    "triangles, %s%s, mask%s%s, %s%s%s%s%s%s%s; %u out of range or not finite, %u "
                    "over %g m, longest %.4g m (one workgroup)\n",
                    static_cast<unsigned long long>(i.key),
                    static_cast<unsigned long long>(i.vs_hash), i.triangles,
                    (f & 1u) ? "refit" : "built", (f & 2u) ? " fast" : "",
                    (f & 4u) ? " camera" : "", (f & 8u) ? " sun" : "",
                    (f & 16u) ? "moving" : "not moving", (f & 32u) ? ", shared copy" : "",
                    (f & 64u) ? ", instance" : "", (f & 128u) ? ", skinned" : "",
                    (f & 256u) ? ", card" : "", (f & 512u) ? ", held" : "",
                    (f & 1024u) ? ", UV capture" : "", rec[1], rec[2], double(geo_huge),
                    metres(rec[3]));
    }
    geo_read.clear();
}

// Destroy: the block and slot are freed once the GPU is past what was recorded so far (an
"""), (r"""    CardFrameEnd(); // bbport (r54_leaf-stage2)
""", r"""    CardFrameEnd(); // bbport (r54_leaf-stage2)
    GeoCheckFrameEnd(); // bbport (r62d_card-uv-diag)
""")],
}

# The new shader (written with the tree's CRLF line ends), from r62d_src beside this script.
def new_files():
    src = os.path.join(HERE, "r62d_src", "rt_geometry_check.comp")
    text = open(src, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    return {NEW_SHADER: text.replace("\n", "\r\n").encode("utf-8")}

# Texts every patched file must hold (once), so a wrong replacement cannot pass check.
MUSTS = {
    SR + "cutout_analysis_pass.cpp": ["u32 CardUvDiag() {", "bool CaptureUvWanted(bool discards) {"],
    VK + "vk_pipeline_cache.cpp": ["static bool FragmentDiscards(const PipelineSelection& sel) {"],
    VK + "vk_pipeline_serialization.cpp": ["if (uv_by_fragment) {",
                                           "const auto& vs_loaded = sel.runtime_infos["],
    G + "CMakeLists.txt": ["add_host_shader(rt_geometry_check.comp rt_geometry_check_comp)"],
    VK + "vk_rt_shadow.h": ["void GeoCheckFrameEnd();", "void GeoCheckTakeWindow(u64 now);",
                            "void GeoCheckPrint();"],
    VK + "vk_rt_shadow.cpp": ["void RtShadow::GeoCheckSetup() {", "if (job->war_barrier) {",
                              "GeoCheckFrameEnd(); // bbport (r62d_card-uv-diag)",
                              "void RtShadow::GeoCheckTakeWindow(u64 now) {",
                              "void RtShadow::GeoCheckPrint() {",
                              "static void GeoCheckFlush(vk::CommandBuffer cmdbuf,"],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def file_run(rel, mode):
    """One file's text after its edits in this mode (apply's for check), or (None, why)."""
    path = ROOT + rel
    if not os.path.isfile(path):
        return None, "no such file"
    raw = open(path, "rb").read()
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
    if crlf not in (0, lf):
        return None, "mixed line ends"
    nl = "\r\n" if crlf else "\n"
    t = raw.decode("utf-8")
    pairs = EDITS[rel]
    for old, new in (pairs if mode != "revert" else list(reversed(pairs))):
        a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
        n = t.count(a)
        if n != 1:
            return None, "anchor found %d times (want 1): %r" % (n, a[:100])
        t = t.replace(a, b)
    if mode != "revert":
        for needle in MUSTS.get(rel, []):
            if t.count(needle) != 1:
                return None, "patched text holds %r %d times" % (needle, t.count(needle))
    return t.encode("utf-8"), ""


def run(mode):
    out, whys = {}, []
    for rel in EDITS:
        t, why = file_run(rel, mode)
        if t is None:
            whys.append("%s%s: %s" % (ROOT, rel, why))
        else:
            out[rel] = t
    news = new_files()
    for rel, data in news.items():
        path = ROOT + rel
        if mode == "revert":
            if not os.path.isfile(path):
                whys.append("%s%s: missing" % (ROOT, rel))
            elif open(path, "rb").read() != data:
                whys.append("%s%s: not the file this patch writes" % (ROOT, rel))
            else:
                out[rel] = None  # removed
        else:
            if os.path.exists(path):
                whys.append("%s%s: already there" % (ROOT, rel))
            else:
                out[rel] = data
    return (out, []) if not whys else (None, whys)


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r62d_card-uv-diag.py check|apply|revert   (the tree: R62D_ROOT, else the "
              "current directory)")
        return 2
    if not os.path.isfile(ROOT + VK + "vk_rt_shadow.cpp"):
        print("not a source tree: %s (set R62D_ROOT)" % ROOT)
        return 2
    out, whys = run("revert" if mode == "revert" else "apply")
    if out is None:
        if mode != "revert" and run("revert")[0] is not None:
            print("already applied in %s%s" % (ROOT, "" if mode == "check" else ": nothing written"))
            return 1
        if mode == "revert" and run("apply")[0] is not None:
            print("not applied in %s: nothing to revert" % ROOT)
            return 1
        print("neither applied nor clean in %s:" % ROOT)
        for w in whys:
            print("  " + w)
        return 1
    if mode == "check":
        print("anchors OK in %s (applies cleanly: %d files changed, 1 new)" % (ROOT, len(EDITS)))
        return 0
    before = {rel: (open(ROOT + rel, "rb").read() if os.path.isfile(ROOT + rel) else None)
              for rel in out}
    done = []
    try:
        for rel, data in out.items():
            if data is not None:
                with open(ROOT + rel + TMP, "wb") as f:
                    f.write(data)
        for rel, data in out.items():
            if data is None:
                os.remove(ROOT + rel)
            else:
                os.replace(ROOT + rel + TMP, ROOT + rel)
            done.append(rel)
    except OSError as e:
        print("failed in %s (%s); putting back what was changed" % (ROOT, e))
        for rel in done:
            if before[rel] is None:
                os.remove(ROOT + rel)
            else:
                with open(ROOT + rel, "wb") as f:
                    f.write(before[rel])
        for rel in out:
            if os.path.exists(ROOT + rel + TMP):
                os.remove(ROOT + rel + TMP)
        return 1
    print("%s in %s (%d files)" % ("applied" if mode == "apply" else "reverted", ROOT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
