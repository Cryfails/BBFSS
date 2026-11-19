// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef _WIN32
#include <dlfcn.h>
#endif
#include "bbport_platform.h"
#include "engine/gx_records.h"
#include "engine/gx_objects.h"
#include "engine/loading.h"
#include <bit>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <map>
#include <thread>
#include <unordered_set>
#include <xxhash.h>
#include <fmt/format.h>
#include "bbport_live_knobs.h"
#include "video_core/renderer_vulkan/ui_composition.h"
#include "bbport_timeline.h"
#include "bbport_sections.h"
#include "bbport_settings.h"
#include "bbport_copy.h"
#include "bbport_ce_stats.h"
#include "bbport_toggles.h"
#include "bbport_write_log.h"
#include "bbport_free_check.h"
#include "bbport_guest_memory.h"
#include "video_core/renderer_vulkan/vk_frame_capture.h"
#include "common/hash.h"
#include "common/scope_exit.h"
#include "common/debug.h"
#include "core/debug_state.h"
#include "core/emulator_settings.h"
#include "core/memory.h"
#include "shader_recompiler/runtime_info.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/amdgpu/pm4_cmds.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/buffer_cache/buffer_cache.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/pipeline_compile_queue.h"
#include "video_core/renderer_vulkan/vk_effect_shaders.h"
#include "video_core/renderer_vulkan/vk_gpu_savings.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_lamp_pane_probe.h"
#include "video_core/renderer_vulkan/vk_occlusion.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_bottle_set0_b182.h"
#include "video_core/renderer_vulkan/vk_sewer_display_bridge.h"
#include "video_core/renderer_vulkan/vk_reflection_first_retire.h"
#include "video_core/renderer_vulkan/vk_bottle_motion_t198.h"
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
#include "video_core/renderer_vulkan/vk_bottle_cold_source_b177.h"
#endif
#include "video_core/renderer_vulkan/vk_workflow_present.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
#include "video_core/renderer_vulkan/ivy_sample_witness.h"
#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "bbport_threads.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_workflow_probe.h"
#include "bbport_test_exposure_lock.h"
#include "video_core/renderer_vulkan/vk_shader_hle.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/vk_window_path_directional.h"
#include "video_core/renderer_vulkan/water_wetness_probe.h"
#include "video_core/host_shaders/indirect_clamp_comp.h"
#include "video_core/texture_cache/image_view.h"
#include "video_core/texture_cache/overlap_diagnostics.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {

struct Rasterizer::SewerReceiverProbe {
    using Camera = RtLampPane::Camera;
    static constexpr u32 Width = 1920, Height = 1080;
    static constexpr u64 Vs = 0xc829ee58, Ps = 0xdbb222eb;
    static constexpr u32 Indices = 52638, First = 0;
    static constexpr std::array Pixels{RawDrawPixel{780, 670}, RawDrawPixel{700, 810},
                                       RawDrawPixel{1140, 390}};
    static constexpr u32 TexelBytes = sizeof(u32), ChannelBytes = u32(Pixels.size()) * TexelBytes;
    static constexpr u32 StageBytes = 2 * ChannelBytes, Bytes = 3 * StageBytes;
    static constexpr u32 WetPixels = 2, WitnessBytes = Bytes + WetPixels * TexelBytes;
    static_assert(Bytes == 72 && WitnessBytes == 80);

    struct CopyObservation {
        RtLampPane::MaterialBacking source{}, destination{};
        Camera camera{};
        std::array<float, 2> jitter{};
        u64 frame = 0, rt = 0, loading = 0, generation = 0, tick = 0;
        u64 bytes = 0, src_write = 0, dst_write = 0;
        u32 order = 0, pass = 0;

        bool SameDestination(const RtLampPane::MaterialBacking& current, u64 write) const {
            return destination == current && dst_write == write;
        }

        bool native = false, enqueued = false, camera_valid = false;
    };

    struct CopyTrace {
        u64 scene = ~0ULL;
        u32 order = 0, pass = 0, ground = 0, ground_pass = 0, water = 0, apply = 0, consumer = 0;
        u32 consumer_pass = 0;
        u64 ground_write = 0, water_write = 0, consumer_write = 0;
        CopyObservation copy{}, late{};
        bool ambiguous = false, sampled = false;
        const char* refusal = nullptr;

        const char* OrderRefusal() const {
            if (!copy.order) return late.order ? "copy-after-apply" : "no-copy-for-current-pass";
            if (!ground || copy.order <= ground) return "copy-before-ground";
            if (!apply || !consumer || copy.order >= apply || apply >= consumer) return "consumer-order";
            if (!water || water <= ground || water >= apply) return "water-writer-order-unjoined";
            if (copy.order >= water) return "copy-after-water";
            return nullptr;
        }
    } trace;

    bool TraceScene(u64 scene) {
        if (!requested || finished || reason || (stage_count && identity.scene != scene)) {
            return false;
        }
        if (trace.scene != scene) trace = {.scene = scene};
        return true;
    }

    bool SameCopyPass(const CopyObservation& copy) const {
        return trace.ground_pass && copy.pass == trace.ground_pass && copy.camera_valid &&
               copy.camera == camera && copy.jitter == jitter && copy.frame == frame &&
               copy.rt == identity.rt && copy.loading == loading && copy.generation == scene_generation &&
               copy.source == material.sources[RawDepth].backing;
    }

    static RtLampPane::MaterialBacking ImageKey(VideoCore::ImageId id, const VideoCore::Image& image) {
        return {
            .image = image.backing ? std::bit_cast<u64>(VkImage(image.GetImage())) : 0,
            .backing = u64(reinterpret_cast<std::uintptr_t>(image.backing)),
            .begin = image.guest_begin, .end = image.guest_end,
            .stencil_begin = image.info.stencil_addr,
            .stencil_end = image.info.stencil_addr + image.info.stencil_size,
            .id = id.index, .uid = image.image_uid,
        };
    }

    static constexpr std::array<u64, 4> Offsets(u32 phase) {
        return {0, phase * StageBytes, 0, phase * StageBytes + ChannelBytes};
    }

    u32 knob_generation = ~0u;
    bool requested = false, finished = false, apply_seen = false;
    u64 armed_frame = 0, frame = 0, loading = 0, scene_generation = 0, tick = 0;
    RtLampPane::Identity identity{};
    LampMaterialState material;
    Camera camera{};
    std::array<float, 2> jitter{};
    std::array<float, 6> viewport{};
    vk::Rect2D scissor{};
    VkBuffer buffer{};
    VmaAllocation allocation{};
    void* mapped = nullptr;
    VAddr index_base = 0;
    u32 stage_count = 0, flags = 0;
    u64 applied_depth_view = 0, applied_albedo_view = 0;
    float plane_y = 0.0f;
    const char* reason = nullptr;

    bool Allocate(VmaAllocator allocator) {
        if (buffer) return true;
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                    .size = WitnessBytes, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo aci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(allocator, &ci, &aci, &buffer, &allocation, &info) != VK_SUCCESS) {
            return false;
        }
        mapped = info.pMappedData;
        return mapped != nullptr;
    }
};

namespace {
constexpr u32 NativeSampleLimit = 12;
constexpr u32 NativeFollowupLimit = 3;
constexpr u64 NativeFollowupWindow = 6;

bool NativeFollowupTarget(u32 target) {
    return target == 0 || target == 2;
}

void NativeFollowupStatus(u32 target, u64 frame, u64 phase, const char* reason) {
    std::printf("Reflection native retry target=%s frame=%llu phase=%llu status=%s\n",
                ReflectionNativeProbe::labels[target], static_cast<unsigned long long>(frame),
                static_cast<unsigned long long>(phase), reason);
}
} // namespace

static Shader::PushData MakeUserData(const AmdGpu::Regs& regs) {
    // TODO(roamic): Add support for multiple viewports and geometry shaders when ViewportIndex
    // is encountered and implemented in the recompiler.
    Shader::PushData push_data{};
    push_data.xoffset = regs.viewport_control.xoffset_enable ? regs.viewports[0].xoffset : 0.f;
    push_data.xscale = regs.viewport_control.xscale_enable ? regs.viewports[0].xscale : 1.f;
    push_data.yoffset = regs.viewport_control.yoffset_enable ? regs.viewports[0].yoffset : 0.f;
    push_data.yscale = regs.viewport_control.yscale_enable ? regs.viewports[0].yscale : 1.f;
    return push_data;
}

Rasterizer::Rasterizer(const Instance& instance_, Scheduler& scheduler_, Runtime& runtime_,
                       AmdGpu::Liverpool* liverpool_)
    : instance{instance_}, scheduler{scheduler_}, runtime{runtime_}, page_manager{this},
      buffer_cache{instance, scheduler, runtime, liverpool_, texture_cache, page_manager},
      texture_cache{instance, scheduler, runtime, liverpool_, buffer_cache, page_manager},
      liverpool{liverpool_}, memory{Core::Memory::Instance()},
      pipeline_cache{instance, scheduler, liverpool, buffer_cache.GetSparsePageShift()},
      host_markers_enabled{EmulatorSettings.IsVkHostMarkersEnabled()},
      guest_markers_enabled{EmulatorSettings.IsVkGuestMarkersEnabled()} {
    own_buffers_mode = BbEngine::Batch::Switch("LANTERN_GX_OWN_BUFFERS");
    // bbport: the vertex memo is on unless LANTERN_VERTEX_MEMO=0 (see VertexMemoOn).
    vertex_memo_mode = [] {
        const char* env = std::getenv("LANTERN_VERTEX_MEMO");
        return env && env[0] == '0' ? BbEngine::Batch::Off : BbEngine::Batch::On;
    }();
    // Before the rasterizer is bound: Liverpool enqueues buffers only once it sees it.
    draw_prep = std::make_unique<DrawPreparation>(pipeline_cache);
    scene_targets = std::make_unique<SceneTargets>(instance, scheduler, runtime, texture_cache);
    // Allocation is independent of shader compilation, including constructor-time precache.
    object_motion = std::make_unique<ObjectMotion>(instance, scheduler);
    pipeline_cache.SetObjectMotionEnabled(object_motion->Enabled());
    camera_motion = std::make_unique<CameraMotion>(instance, scheduler, texture_cache, runtime);
    camera_motion->SetObjectMotion(object_motion.get());
    // bbport: native HDR output's passes run at points of the frame the upscaler finds.
    hdr_native = std::make_unique<HdrNative>(instance, scheduler, texture_cache, runtime);
    rt_shadow = std::make_unique<RtShadow>(instance, scheduler, *camera_motion, *object_motion);
    window_receiver_enabled = WindowPathProbe::Wanted();
    if (window_receiver_enabled) {
        InitColdWindowPane();
    }
    pipeline_cache.SetPositionCapture(rt_shadow->Capturing());
    ssgi = std::make_unique<ScreenSpaceGI>(instance, scheduler, texture_cache, runtime,
                                           *scene_targets, *camera_motion, *rt_shadow);
    spatial_ao = std::make_unique<SpatialAo>(instance, scheduler, runtime, *scene_targets,
                                             texture_cache);
    ssr_temporal = std::make_unique<SsrTemporal>(instance, scheduler, texture_cache, runtime,
                                                 *scene_targets, *camera_motion);
    contact_shadow = std::make_unique<ContactShadow>(instance, scheduler, texture_cache, runtime,
                                                     *scene_targets, *camera_motion, *rt_shadow);
    // bbport (r105_cloud-shadows): BB_CLOUD_SHADOWS above 0 or BB_CLOUD_SHADOWS_SHOW=1 only
    // (CloudShadow::Wanted, read once); otherwise none is made and its hooks are null tests.
    if (CloudShadow::Wanted()) {
        cloud_shadow = std::make_unique<CloudShadow>(instance, scheduler);
    }
    // bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (CloudLayer::Wanted, read once);
    // otherwise none is made and its hooks are null tests. After the cloud shadows: it shares their
    // clock while they are on. Its pipelines are made here, its march image at the first frame it
    // draws; it is drawn right before the upscaler (without it, said after 300 frames).
    if (CloudLayer::Wanted()) {
        cloud_layer = std::make_unique<CloudLayer>(instance, scheduler, texture_cache, runtime,
                                                   *scene_targets, *camera_motion);
    }
    point_shadow = std::make_unique<PointShadow>(instance, scheduler, texture_cache, runtime,
                                                 *scene_targets, *camera_motion, *rt_shadow);
    volumetric_light = std::make_unique<VolumetricLight>(instance, scheduler, texture_cache,
                                                         runtime, *scene_targets);
    // bbport (r100c_blood-pool-probe, TOOL): BB_BLOOD_POOL_PROBE not off at start only
    // (BloodPoolProbe::Wanted, read once); its passes and buffers are made at the first probed box.
    if (const char* master = std::getenv("BB_SEWER_RECEIVER_WITNESS");
        master && std::string_view(master) == "1") {
        sewer_receiver = std::make_unique<SewerReceiverProbe>();
    }
    if (BloodPoolProbe::Wanted()) {
        blood_pool_probe = std::make_unique<BloodPoolProbe>(instance, scheduler, texture_cache, runtime,
                                                            *scene_targets, *camera_motion);
    }
    sky_seam = std::make_unique<SkySeam>(instance, scheduler);
    sky_zenith = std::make_unique<SkyZenith>(instance, scheduler);
    depth_of_field = std::make_unique<DepthOfField>(instance, scheduler, texture_cache,
                                                    runtime, *scene_targets);
    froyok_bloom = std::make_unique<FroyokBloom>(instance, scheduler, texture_cache, runtime,
                                                 *scene_targets);
    upscaler = std::make_unique<TemporalUpscaler>(instance, scheduler, texture_cache, runtime,
                                                  *camera_motion, *scene_targets, *hdr_native);
    // bbport (r95_halation, r109a_strength-settings-engine): no Halation is made here; it is made
    // at the first frame whose strength is above 0 (EffectsBeforeUpscaler) and kept. Its
    // pipeline, buffers and images are made at that frame; without the upscaler it has no place.
    // bbport (r100_blood-sheen): BB_BLOOD_SHEEN on only (BloodSheen::Wanted, read once); otherwise
    // no BloodSheen is made and nothing of it runs. Its pipelines, buffers and image are made at
    // the first draw of the blood pool (vk_blood_sheen.h).
    if (BloodSheen::Wanted()) {
        blood_sheen = std::make_unique<BloodSheen>(instance, scheduler, texture_cache, runtime,
                                                   *scene_targets, *camera_motion);
    }
    // bbport (r86b_glass-visible): BB_GLASS_GLINT and BB_RT_GLASS on only (GlassGlint::Wanted,
    // read once); otherwise no GlassGlint is made and nothing of it runs.
    // bbport (r129a_glass-registry): BB_GLASS_TABLE naming a valid entry only (read once); otherwise no GlassRegistry and no
    // GlassView are made and the draw hook is one null pointer test. The view is made with BB_GLASS_VIEW=1 or the live knobs
    // file; its pipelines and images are made at the first hit draw with the view on (vk_glass_view.h).
    if (GlassRegistryRules::Load().on) {
        glass_registry = std::make_unique<GlassRegistry>();
        if (GlassView::Wanted()) {
            glass_view = std::make_unique<GlassView>(instance, scheduler, texture_cache, runtime, *scene_targets,
                                                     *camera_motion);
        }
        // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR=1 or the live knobs file only (GlassClear::Wanted, read once); its
        // pipeline, buffer and side images are made at the first redirected pane draw (vk_glass_clear.h).
        if (GlassClear::Wanted()) {
            glass_clear = std::make_unique<GlassClear>(instance, scheduler, texture_cache, runtime, *scene_targets,
                                                       *camera_motion, *rt_shadow);
        }
    } else {
        GlassRegistry::SayOff(); // prints only when the table or BB_GLASS_VIEW was given
    }
    // bbport (t129c_sun-term-view, TOOL): BB_RT_SUN_TERM_VIEW=1 or the live knobs file only (read once); otherwise none is made.
    // Its pipeline and image are made at the first capture with the view on (vk_sun_term_view.h).
    if (SunTermView::Wanted()) {
        sun_term_view = std::make_unique<SunTermView>(instance, scheduler, texture_cache, runtime, *scene_targets,
                                                      *camera_motion);
    }
    if (GlassGlint::Wanted()) {
        glass_glint = std::make_unique<GlassGlint>(instance, scheduler, texture_cache, runtime,
                                                   *scene_targets, *camera_motion, *rt_shadow);
    }
    // bbport (r131a_foliage-translucency): the back-lit glow (FoliageGlow::Wanted, read once: also says the foliage translucency's start line);
    // otherwise none is made and nothing of it runs.
    if (FoliageGlow::Wanted()) {
        if (FoliageMask::Requested() && FoliageMask::Supported(instance)) {
            foliage_mask = std::make_unique<FoliageMask>(instance, scheduler);
            foliage_collect.store(true, std::memory_order_relaxed);
        }
        foliage_glow = std::make_unique<FoliageGlow>(instance, scheduler, texture_cache, runtime, *scene_targets, *camera_motion,
                                                     *point_shadow, *rt_shadow);
    }
    // bbport (r111_footprints): BB_FOOTPRINTS on only (Footprints::Wanted, read once); otherwise
    // no Footprints is made, nothing of it runs and the game's memory is not read. Its pipeline
    // and buffers are made at its first pass (vk_footprints.h).
    if (Footprints::Wanted()) {
        footprints = std::make_unique<Footprints>(instance, scheduler, texture_cache, runtime,
                                                  *scene_targets, *camera_motion);
    }
    // bbport (r45_drawn-look): nothing of Vulkan is made here; its pipelines and its image are
    // made on the first frame the look is wanted on. Its places in the frame are found with the
    // upscaler's scene colour: without the upscaler there are none.
    drawn_look = std::make_unique<DrawnLook>(instance, scheduler, texture_cache, runtime,
                                             *scene_targets, *camera_motion, *object_motion);
    if (!upscaler->Enabled()) {
        DrawnLook::NoSceneHooks();
    }
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the card alpha layers (made here, once);
    // otherwise no CardAlpha is made, RtShadow gets none and no draw calls in. Its debug view
    // runs before the upscaler: without it, the view has no place in the frame (said once).
    if (CardAlpha::Wanted()) {
        card_alpha = std::make_unique<CardAlpha>(instance, scheduler, texture_cache, runtime,
                                                 *scene_targets, *camera_motion, *rt_shadow);
        if (!upscaler->Enabled()) {
            card_alpha->NoSceneHooks();
        }
    }
    card_bound_on = card_alpha && card_alpha->On();
    rt_shadow->SetCardLayers(card_bound_on ? card_alpha.get() : nullptr);
    // bbport (r107_caustics): BB_CAUSTICS above 0 or "show" only: the water caustics, drawn at
    // the first blended draw after the opaque scene, which is reached only with the upscaler on.
    if (Caustics::Wanted()) {
        caustics = std::make_unique<Caustics>(instance, scheduler, texture_cache, runtime,
                                              *scene_targets, *camera_motion, *point_shadow,
                                              upscaler->Enabled());
    }
    // bbport (r97_heat-haze): BB_HEAT_HAZE above 0 only: the shimmer above flames, drawn
    // right before the upscaler; without the upscaler that place is never reached (said once).
    if (HeatHaze::Wanted()) {
        heat_haze = std::make_unique<HeatHaze>(instance, scheduler, texture_cache, runtime,
                                               *scene_targets, *camera_motion);
        if (!upscaler->Enabled()) {
            heat_haze->NoSceneHooks();
        }
    }
    // bbport (r117_wind-shelter): BB_WIND=1 with BB_WIND_SHELTER above 0 only: the wind shelter
    // field, made right before the upscaler (as the heat haze); without the upscaler that place is
    // never reached (said once).
    if (WindShelter::Wanted()) {
        wind_shelter = std::make_unique<WindShelter>(instance, scheduler, texture_cache, runtime,
                                                     *scene_targets, *camera_motion);
        if (!upscaler->Enabled()) {
            wind_shelter->NoSceneHooks();
        }
    }
    // bbport (r98_ambient-particles): BB_PARTICLES above 0 only (AmbientMotes::Get, read once
    // here); otherwise nothing of it is made and the upscaler's after_upscale stays empty.
    if (AmbientMotes::Get().On()) {
        if (!upscaler->Enabled()) {
            std::printf("Ambient particles (r98): the upscaler is off; nothing is drawn\n");
        } else if (auto motes = std::make_unique<AmbientParticles>(instance, scheduler);
                   motes->Ready()) {
            ambient_particles = std::move(motes);
            upscaler->after_upscale = [this](const TemporalUpscaler::UpscaledFrame& frame) {
                const BbWind::Snapshot w = wind.Get();
                // bbport (r116_wind-one-source): the wind at the camera, gust front included
                const CameraMotion::Matrices cam = camera_motion->CameraMatrices();
                // bbport (r98d_particles-still-indoors): the camera's open share of air (r117's
                // field: 0 indoors; 1 without it) is not in Felt's wind, so it goes alongside
                ambient_particles->Draw(frame, cam, w.on,
                                        BbWind::Felt(BbWind::Follower::Motes, w, cam.inv_view),
                                        wind_shelter ? wind_shelter->CameraOpen() : 1.0f);
            };
        }
    }
    if (!EmulatorSettings.IsNullGPU()) {
        liverpool->BindRasterizer(this);
    }
    BbGuestMemory::Install(instance); // bbport: before the runtime maps direct memory
    // bbport: copy threads working for the GPU command or draw recording thread handle their
    // faults as it would (BbCopy::ForGpuSide).
    static Rasterizer* gpu_side_rasterizer = nullptr;
    gpu_side_rasterizer = this;
    BbCopy::SetGpuSideQuery([] { return gpu_side_rasterizer->IsGpuSideThread(); });
    memory->SetRasterizer(this);

    WorkflowProbeConfig workflow_config{};
    if (workflow_config_read(&workflow_config)) {
        workflow = std::make_unique<WorkflowProbe::Renderer>(workflow_config);
    }
    GpuProfiler::Init(instance, scheduler);
    occlusion = Occlusion::Create(instance, scheduler, *this);
    if (DrawPipeWanted()) {
        constant_ring = std::make_unique<ConstantRing>(instance, scheduler);
        draw_pipe = std::make_unique<DrawPipe>(&RunDrawPacket, this);
        BbSpike::stage_b_busy.store(&draw_pipe->busy_cycles, std::memory_order_release); // r23
        BbSpike::stage_b_packets.store(draw_pipe->PacketCounter(), std::memory_order_release); // r29
        // bbport: the lookahead thread (docs/parallel-stageb.md), off unless asked for.
        if (LookaheadWanted()) {
            lookahead_thread = std::jthread([this](std::stop_token stop) { LookaheadLoop(stop); });
            std::printf("Draw pipe: lookahead thread prefetching for stage B, %u packets ahead "
                        "(BB_DRAWREC_WORKERS=1, BB_DRAWREC_LOOKAHEAD, BB_DRAWREC_IDLE)\n",
                        LookaheadWindow());
        }
    }
    // bbport (docs/pipeline_compiles.md): which of the waits for compiles, drains and the texture
    // cache's lock run, once at start.
    LogPipelineCompileMode(instance, scheduler.IsRecordingDeferred());
    std::printf("Waits: GPU command thread drains %s; write faults on pages no image watches %s "
                "(BB_DRAIN_SLEEP, BB_FAULT_SKIP_TEXTURES)\n",
                DrawPipe::SleepEnabled() ? "sleep after a spin (stage B wakes them)" : "spin",
                FaultSkipsTextureCache() ? "leave the texture cache alone"
                                         : "take the texture cache's lock");
    // bbport: this thread joins the texture binding helper before it changes image state.
    runtime.SetImageAccessHook(&JoinBindHelper, this);
    scheduler.SetSubmitCallback([this](Vulkan::SubmitInfo& info) {
        // bbport (r27_flush-split): each part timed (BB_SPIKE_TRACE=1, stage B's tasks only)
        const BbSpike::SplitScope r27_callback{BbSpike::SplitCallback};
        {
            const BbSpike::SplitScope r27_step{BbSpike::SplitMotionSync};
            object_motion->Sync();
        }
        {
            const BbSpike::SplitScope r27_step{BbSpike::SplitBarriers};
            runtime.FlushBarriers();
        }
        const BbSpike::SplitScope r27_step{BbSpike::SplitArenaBinds};
        buffer_cache.SubmitPendingArenaBinds(info);
    });
}

Rasterizer::~Rasterizer() {
    if (sewer_receiver && sewer_receiver->buffer) {
        scheduler.DeferOperation([allocator = instance.GetAllocator(),
                                  buffer = sewer_receiver->buffer,
                                  allocation = sewer_receiver->allocation] {
            vmaDestroyBuffer(allocator, buffer, allocation);
        });
    }
    ReflectionNativeDestroy();
    if (reflection_probe) {
        rt_shadow->ReflectionAttach(nullptr);
    }
}

bool Rasterizer::HonestLabels() {
    static const bool on = [] {
        const char* env = std::getenv("BB_HONEST_LABELS");
        const bool enabled = (env && env[0] == '1') || VideoCore::GuestInPlace();
        if (enabled) {
            std::printf("GPU: fences written when the GPU has finished the work before them "
                        "(BB_HONEST_LABELS=1)\n");
        }
        return enabled;
    }();
    return on;
}

void Rasterizer::PublishSignals() {
    // Only the recording thread, or the GPU command thread while it is idle (drained), touches
    // them; other threads (a guest thread reading back) leave them to those.
    const bool on_b = DrawPipe::OnStageB();
    if (!(on_b || (OnStageA() && DrawPipeIdle()))) {
        return;
    }
    // Fences of the packets before this one (stage B), or of all (stage A, drained).
    const u64 upto = draw_pipe ? (on_b ? draw_pipe->Consumed() : draw_pipe->Head()) : 0;
    if (local_signals.empty()) {
        signals_published_upto.store(upto, std::memory_order_release);
        return;
    }
    bool was_empty;
    {
        std::scoped_lock lk{gpu_signals_mutex};
        if (!gpu_signal_started) {
            gpu_signal_thread =
                std::jthread([this](std::stop_token token) { GpuSignalLoop(token); });
            gpu_signal_started = true;
        }
        was_empty = gpu_signals.empty();
        for (auto& pending : local_signals) {
            gpu_signals.push_back(std::move(pending));
        }
    }
    local_signals.clear();
    local_signal_count.store(0, std::memory_order_release);
    signals_published_upto.store(upto, std::memory_order_release);
    if (was_empty) {
        gpu_signals_cv.notify_one();
    }
}

void Rasterizer::SignalAfterGpu(std::function<void()> signal, VAddr label, u64 value) {
    if (DrawPipe::OnStageB()) {
        // Kept here until the end of the guest submission or the next flush (in tick order).
        local_signals.push_back({scheduler.CurrentTick(), std::move(signal), label, value});
        local_signal_count.store(u32(local_signals.size()), std::memory_order_release);
        return;
    }
    if (OnStageA() && DrawPipeIdle()) {
        PublishSignals(); // the recording thread's come first (it is idle)
    }
    bool was_empty;
    {
        std::scoped_lock lk{gpu_signals_mutex};
        if (!gpu_signal_started) {
            gpu_signal_thread =
                std::jthread([this](std::stop_token token) { GpuSignalLoop(token); });
            gpu_signal_started = true;
        }
        was_empty = gpu_signals.empty();
        gpu_signals.push_back({scheduler.CurrentTick(), std::move(signal), label, value});
    }
    // The signal thread waits on the condition only with nothing queued (else it waits for the
    // GPU and takes the rest when it gets back): no notify per fence (~60 a frame).
    if (was_empty) {
        gpu_signals_cv.notify_one();
    }
}

void Rasterizer::RequestSignalFlush() {
    if (signal_flush_requested.exchange(true, std::memory_order_acq_rel)) {
        return;
    }
    static constexpr u8 none = 0;
    RunInOrder(
        [](Rasterizer& self, const u8*) {
            self.signal_flush_requested.store(false, std::memory_order_release);
            self.PublishSignals();
            if (self.HasUnsubmittedSignals()) {
                const BbSubmitDiag::Scope diag_reason{BbSubmitDiag::ReasonStageAIdle}; // r8
                self.Flush();
            }
        },
        &none, 0, BbToggle::PipelinedTasks, false, "SignalFlush");
}

void Rasterizer::NoteFenceBarrier() {
    if (BbStats::enabled) {
        BbStats::fence_barriers.fetch_add(1, std::memory_order_relaxed);
    }
    // Recorded whenever BB_FENCE_ORDER=ordered may be in effect (also while experiment bit 8 is
    // off: switched on later, the barriers before are known).
    if (!Scheduler::FenceOrderPossible()) {
        return;
    }
    static constexpr u8 none = 0;
    RunInOrder([](Rasterizer& self, const u8*) { self.scheduler.NoteSignalBarrier(); }, &none,
               0, BbToggle::PipelinedTasks, false, "FenceBarrier");
}

bool Rasterizer::SignalsPublished(u64 position) const {
    return !draw_pipe || !HonestLabels() ||
           signals_published_upto.load(std::memory_order_acquire) >= position;
}

bool Rasterizer::HasUnsubmittedSignals() {
    if (local_signal_count.load(std::memory_order_acquire) != 0) {
        return true; // for the current tick, held by the recording thread
    }
    std::scoped_lock lk{gpu_signals_mutex};
    return !gpu_signals.empty() && gpu_signals.back().tick >= scheduler.CurrentTick();
}

bool Rasterizer::WriteGuestMemory(VAddr address, const void* data, u32 size) {
    if (!VideoCore::GuestInPlace() || size == 0 || (address | size) % 4 != 0) {
        return false;
    }
    hang_gpu_watch.Written(0, BbWindHangGpu::WriterGuest, address, size); // bbport (r112q_hang-bracket-route): the palette writer watch
    const auto [buffer, offset] = buffer_cache.ObtainBuffer(address, size, true);
    if (!buffer_cache.IsInPlace(address, size)) {
        return false;
    }
    runtime.UpdateBuffer(buffer, offset, {static_cast<const u8*>(data), size});
    return true;
}

bool Rasterizer::WriteDataOnGpu(VAddr address, const void* data, u32 size) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_GPU_COMMAND_WRITES");
        return !env || env[0] != '0';
    }();
    if (!enabled || !VideoCore::GuestInPlace() || size == 0 || (address | size) % 4 != 0) {
        return false;
    }
    hang_gpu_watch.Written(0, BbWindHangGpu::WriterCommand, address, size); // bbport (r112q_hang-bracket-route): the palette writer watch
    const auto target = buffer_cache.CommandWriteTarget(address, size);
    if (!target) {
        return false;
    }
    runtime.UpdateBuffer(target->first, target->second, {static_cast<const u8*>(data), size});
    if (size <= sizeof(u64) && HonestLabels()) {
        u64 value = 0;
        std::memcpy(&value, data, size);
        SignalAfterGpu([] {}, address, value);
    }
    return true;
}

bool Rasterizer::PipeSignals() const {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_PIPE_SIGNALS");
        return !env || env[0] != '0';
    }();
    return enabled && HonestLabels() && UseDrawPipe() && OnStageA();
}

void Rasterizer::SubmitForSignals() {
    if (!HonestLabels()) {
        return;
    }
    if (PipeSignals()) {
        // Decided (and submitted) on the recording thread after this submission's draws and
        // fences: here they may not even be recorded yet.
        static constexpr u8 none = 0;
        RunInOrder([](Rasterizer& self, const u8*) { self.SubmitForSignalsNow(); }, &none, 0,
                   BbToggle::PipelinedTasks, false, "SubmitForSignals");
        return;
    }
    SubmitForSignalsNow();
}

namespace {
/// bbport r8: an early submission at the end of a guest submission once the GPU has finished
/// everything submitted (BB_NEAR_DRY_DEPTH=1, default; 2: every submission but the newest, it is
/// about to run dry), so it does not wait for the next 2 ms batch (BB_HONEST_FLUSH_US), whatever
/// the draw backlog (the 64 KiB rule). At most one per BB_NEAR_DRY_US (default 300), and
/// only while the draw recording thread had slack: busy under BB_NEAR_DRY_BUSY percent (default
/// 92) of the last >= 8 ms. When it is the limit, a submission costs it ~65 us and the GPU waits
/// for it anyway. Experiment bit 8589934592 restores the old rule.
bool NearDryFlush(Scheduler& scheduler, const DrawPipe* pipe, std::chrono::nanoseconds since) {
    static const auto spacing = std::chrono::microseconds([] {
        const char* env = std::getenv("BB_NEAR_DRY_US");
        return env ? std::max(0ll, std::strtoll(env, nullptr, 10)) : 300ll;
    }());
    static const u64 busy_limit = [] {
        const char* env = std::getenv("BB_NEAR_DRY_BUSY");
        return env ? u64(std::clamp(std::atoi(env), 0, 100)) : u64{92};
    }();
    // 1: the GPU finished all of them (it idles already); 2: every submission but the newest.
    static const u64 depth = [] {
        const char* env = std::getenv("BB_NEAR_DRY_DEPTH");
        return env ? u64(std::clamp(std::atoi(env), 1, 4)) : u64{1};
    }();
    if (!pipe || !DrawPipe::OnStageB() || since < spacing ||
        BbToggle::Experiment(8589934592ull)) {
        return false;
    }
    // The draw recording thread's share of the last window busy running packets (rdtsc cycles).
    static u64 window_tsc = 0, window_busy = 0;
    static std::chrono::steady_clock::time_point window_start{};
    static bool slack = false;
    const auto now = std::chrono::steady_clock::now();
    if (now - window_start >= std::chrono::milliseconds(8)) {
        const u64 tsc = __rdtsc();
        const u64 busy = pipe->busy_cycles.load(std::memory_order_relaxed);
        if (window_tsc != 0 && tsc > window_tsc) {
            slack = (busy - window_busy) * 100 < busy_limit * (tsc - window_tsc);
        }
        window_tsc = tsc;
        window_busy = busy;
        window_start = now;
    }
    if (!slack) {
        if (BbSubmitDiag::On()) {
            BbSubmitDiag::near_dry_busy.fetch_add(1, std::memory_order_relaxed);
        }
        return false;
    }
    const u64 tick = scheduler.CurrentTick();
    return tick > depth && scheduler.IsFree(tick - depth);
}
} // namespace

void Rasterizer::SubmitForSignalsNow() {
    PublishSignals(); // the end of a guest submission
    static const auto interval = std::chrono::microseconds([] {
        const char* env = std::getenv("BB_HONEST_FLUSH_US");
        return env ? std::strtoll(env, nullptr, 10) : 2000ll;
    }());
    const bool diag = BbSubmitDiag::On(); // bbport r8
    if (diag) {
        BbSubmitDiag::ends.fetch_add(1, std::memory_order_relaxed);
    }
    if (!HasUnsubmittedSignals()) {
        if (diag) {
            BbSubmitDiag::ends_no_fences.fetch_add(1, std::memory_order_relaxed);
        }
        return;
    }
    // Batched (one submission per BB_HONEST_FLUSH_US) while the GPU still has work; at once when it
    // has finished everything submitted: holding the work back then only leaves it idle. Not at
    // once while draws are queued for this thread (BB_HONEST_IDLE_BACKLOG bytes, default 64 KiB):
    // it is then what the GPU waits for, and a submission costs it ~65 us (heavy scenes: 13 a
    // frame; 95 -> 100 FPS with half as many).
    static const bool idle_flush = [] {
        const char* env = std::getenv("BB_HONEST_IDLE_FLUSH");
        return !env || env[0] != '0';
    }();
    static const u64 idle_backlog = [] {
        const char* env = std::getenv("BB_HONEST_IDLE_BACKLOG");
        return env ? std::strtoull(env, nullptr, 10) : u64(64 * 1024);
    }();
    const bool gpu_idle =
        idle_flush &&
        (!draw_pipe || !DrawPipe::OnStageB() || draw_pipe->Backlog() < idle_backlog) &&
        scheduler.IsFree(scheduler.CurrentTick() - 1);
    const auto since_flush = std::chrono::nanoseconds(
        std::chrono::steady_clock::now().time_since_epoch().count() -
        last_flush_ns.load(std::memory_order_relaxed));
    if (!gpu_idle && since_flush < interval) {
        // bbport r8: the GPU about to run dry gets the work now (experiment bit 8589934592: not).
        if (NearDryFlush(scheduler, draw_pipe.get(), since_flush)) {
            const BbSubmitDiag::Scope diag_reason{BbSubmitDiag::ReasonNearDry};
            Flush();
            return;
        }
        if (diag) {
            BbSubmitDiag::ends_held.fetch_add(1, std::memory_order_relaxed);
            if (scheduler.IsFree(scheduler.CurrentTick() - 1)) {
                BbSubmitDiag::ends_held_dry.fetch_add(1, std::memory_order_relaxed);
            }
        }
        return;
    }
    if (gpu_idle) {
        BbStats::idle_flushes.fetch_add(1, std::memory_order_relaxed);
    }
    const BbSubmitDiag::Scope diag_reason{gpu_idle ? BbSubmitDiag::ReasonGpuIdle
                                                   : BbSubmitDiag::ReasonBatched}; // r8
    Flush();
}

bool Rasterizer::PendingSignalValue(VAddr address, u64& value) {
    std::scoped_lock lk{gpu_signals_mutex};
    for (auto it = gpu_signals.rbegin(); it != gpu_signals.rend(); ++it) {
        if (it->label == address) {
            value = it->value;
            return true;
        }
    }
    return false;
}

void Rasterizer::GpuSignalLoop(std::stop_token token) {
    Common::SetCurrentThreadName("bb:GpuSignals");
    auto* semaphore = scheduler.GetWorkSemaphore();
    const vk::Semaphore handle = semaphore->Handle();
    while (!token.stop_requested()) {
        u64 tick = 0;
        {
            std::unique_lock lk{gpu_signals_mutex};
            if (!gpu_signals_cv.wait(lk, token, [this] { return !gpu_signals.empty(); })) {
                return;
            }
            tick = gpu_signals.front().tick;
        }
        // Bounded waits: the tick may not be submitted yet (the GPU command thread submits it
        // when it runs out of work), and a stop request must be seen.
        const vk::SemaphoreWaitInfo wait_info = {
            .semaphoreCount = 1,
            .pSemaphores = &handle,
            .pValues = &tick,
        };
        // bbport: a lost device ends the wait with a report (it spun here forever: the game froze
        // with its sound playing, Steam Deck); 10 s without progress prints what is stuck once.
        const auto wait_start = std::chrono::steady_clock::now();
        bool watched = false;
        while (!token.stop_requested()) {
            const vk::Result result = instance.GetDevice().waitSemaphores(&wait_info, 5'000'000);
            if (result == vk::Result::eSuccess) {
                break;
            }
            if (result == vk::Result::eErrorDeviceLost) {
                Breadcrumbs::ReportDeviceLost("waiting for the GPU");
                ASSERT_MSG(false, "Device lost while waiting for the GPU");
            }
            if (!watched && std::chrono::steady_clock::now() - wait_start > std::chrono::seconds(10)) {
                watched = true;
                GpuWatchdog(tick);
            }
            if (watched && std::chrono::steady_clock::now() - wait_start > std::chrono::seconds(60)) {
                std::printf("GPU watchdog: no progress for 60 s: the game ends (exit code 24)\n");
                std::fflush(nullptr);
                BbPlatform::TerminateProcessNow(24);
            }
        }
        semaphore->Refresh();
        BbTimeline::Note(BbTimeline::GpuDone, semaphore->KnownGpuTick());
        while (true) {
            std::function<void()> signal;
            {
                std::scoped_lock lk{gpu_signals_mutex};
                if (gpu_signals.empty() || !semaphore->IsFree(gpu_signals.front().tick)) {
                    break;
                }
                signal = std::move(gpu_signals.front().signal);
                // Kept queued while it runs: PendingSignalValue still sees the fence.
            }
            signal();
            std::scoped_lock lk{gpu_signals_mutex};
            gpu_signals.pop_front();
        }
    }
}

void Rasterizer::GpuWatchdog(u64 tick) {
    auto* semaphore = scheduler.GetWorkSemaphore();
    semaphore->Refresh();
    const u64 done = semaphore->KnownGpuTick(), recording = scheduler.CurrentTick();
    if (tick < recording) {
        std::printf("GPU watchdog: submission %llu not finished after 10 s (the GPU finished %llu, "
                    "recording %llu): the GPU is stuck\n",
                    (unsigned long long)tick, (unsigned long long)done, (unsigned long long)recording);
        Breadcrumbs::ReportStuck("submitted work not finished in 10 s");
        // bbport: the PC memory model hung GPUs of every vendor in player logs, right after a
        // copy pass: the next start leaves it off on this PC (bbport_guest_memory_win.cpp).
        const char* in_place = std::getenv("BB_GUEST_IN_PLACE");
        const char* user = std::getenv("BB_GPU_USER_DIR");
        if (in_place && in_place[0] == '1' && user && *user) {
            if (std::FILE* mark = std::fopen((std::string(user) + "/pc-model-hung").c_str(), "w")) {
                std::fputs("[2] The GPU stopped answering with the PC memory model on. Delete this file to try it again.\n", mark);
                std::fclose(mark);
                std::printf("Guest memory: the next start leaves the PC memory model off on this PC "
                            "(delete user\\pc-model-hung to try it again)\n");
            }
        }
    } else {
        std::printf("GPU watchdog: waited 10 s for submission %llu, not submitted yet (the GPU finished "
                    "%llu, recording %llu, draw pipe backlog %llu bytes): the port's threads are "
                    "waiting for each other\n",
                    (unsigned long long)tick, (unsigned long long)done, (unsigned long long)recording,
                    (unsigned long long)(draw_pipe ? draw_pipe->Backlog() : 0));
    }
    std::fflush(stdout);
}

const AmdGpu::Regs& Rasterizer::Regs() const {
    return stage_regs ? *stage_regs : liverpool->regs;
}

inline AmdGpu::CbDbExtent Rasterizer::CbExtent(u32 index) const {
    auto& dc = Dc();
    return stage_regs ? dc.pipe_cb_extent[index] : liverpool->last_cb_extent[index];
}

inline const AmdGpu::ComputeProgram& Rasterizer::CsRegs() const {
    return stage_cs ? *stage_cs : liverpool->GetCsRegs();
}

inline AmdGpu::CbDbExtent Rasterizer::DbExtent() const {
    auto& dc = Dc();
    return stage_regs ? dc.pipe_db_extent : liverpool->last_db_extent;
}

namespace {
/// magic_enum::enum_contains, from a table: it scans every enumerator (per texture per draw).
bool IsKnownFormat(AmdGpu::DataFormat data_fmt, AmdGpu::NumberFormat num_fmt) {
    static const auto tables = [] {
        std::pair<std::array<bool, 256>, std::array<bool, 256>> t{};
        for (const auto value : magic_enum::enum_values<AmdGpu::DataFormat>()) {
            if (static_cast<u32>(value) < 256) {
                t.first[static_cast<u32>(value)] = true;
            }
        }
        for (const auto value : magic_enum::enum_values<AmdGpu::NumberFormat>()) {
            if (static_cast<u32>(value) < 256) {
                t.second[static_cast<u32>(value)] = true;
            }
        }
        return t;
    }();
    const u32 d = static_cast<u32>(data_fmt), n = static_cast<u32>(num_fmt);
    return d < 256 && n < 256 && tables.first[d] && tables.second[n];
}
} // namespace

bool Rasterizer::FilterDraw() {
    const auto& regs = Regs();
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::EliminateFastClear) {
        // Clears the render target if FCE is launched before any draws
        EffectsEndLampBatch(); // bbport: lamps apart: no draw, so nothing else ends the batch
        EliminateFastClear();
        return false;
    }
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::FmaskDecompress) {
        // TODO: check for a valid MRT1 to promote the draw to the resolve pass.
        LOG_TRACE(Render_Vulkan, "FMask decompression pass skipped");
        ScopedMarkerInsert("FmaskDecompress");
        return false;
    }
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Resolve) {
        LOG_TRACE(Render_Vulkan, "Resolve pass");
        EffectsEndLampBatch(); // bbport
        Resolve();
        return false;
    }
    if (regs.primitive_type == AmdGpu::PrimitiveType::None) {
        LOG_TRACE(Render_Vulkan, "Primitive type 'None' skipped");
        ScopedMarkerInsert("PrimitiveTypeNone");
        return false;
    }

    const bool cb_disabled =
        regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Disable;
    const auto depth_copy =
        regs.depth_render_override.force_z_dirty && regs.depth_render_override.force_z_valid &&
        regs.depth_buffer.DepthValid() && regs.depth_buffer.DepthWriteValid() &&
        regs.depth_buffer.DepthAddress() != regs.depth_buffer.DepthWriteAddress();
    const auto stencil_copy =
        regs.depth_render_override.force_stencil_dirty &&
        regs.depth_render_override.force_stencil_valid && regs.depth_buffer.StencilValid() &&
        regs.depth_buffer.StencilWriteValid() &&
        regs.depth_buffer.StencilAddress() != regs.depth_buffer.StencilWriteAddress();
    if (cb_disabled && (depth_copy || stencil_copy)) {
        // Games may disable color buffer and enable force depth/stencil dirty and valid to
        // do a copy from one depth-stencil surface to another, without a pixel shader.
        // We need to detect this case and perform the copy, otherwise it will have no effect.
        LOG_TRACE(Render_Vulkan, "Performing depth-stencil override copy");
        EffectsEndLampBatch(); // bbport: the pass that shadows the lamps reads the depth
        DepthStencilCopy(depth_copy, stencil_copy);
        return false;
    }

    return true;
}

template <typename Memo>
bool Rasterizer::RevalidateTarget(Memo& memo, u64 generation) {
    // Images were (un)registered since: an exact match still registered is what FindImage
    // would find again (TextureCache::IsExactMatch). ~0: invalidated, never revalidated.
    if (!memo.exact || memo.generation == ~0ULL || !MemoRevalidation() ||
        !texture_cache.IsRegisteredImage(memo.image_id, memo.uid)) {
        return false;
    }
    memo.generation = generation;
    ++target_lookups_revalidated;
    return true;
}

template <typename... Parts>
VideoCore::ImageId Rasterizer::FindTargetMemoized(VideoCore::TextureCache::ImageDesc& desc,
                                                  LastTarget& last, auto&& make_desc,
                                                  const Parts&... parts) {
    static_assert((sizeof(Parts) + ...) <= 256, "target memo key too large");
    std::array<u8, 256> key{};
    u32 key_size = 0;
    const auto append = [&](const auto& part) {
        std::memcpy(key.data() + key_size, &part, sizeof(part));
        key_size += sizeof(part);
    };
    (append(parts), ...);
    const u64 generation = texture_cache.RegistryGeneration();
    const bool memo_enabled = !BbToggle::Disabled(BbToggle::TextureBindingMemo);
    if (memo_enabled && last.key_size == key_size &&
        std::memcmp(last.key.data(), key.data(), key_size) == 0 &&
        (last.generation == generation || RevalidateTarget(last, generation))) {
        texture_cache.MarkFound(last.image_id);
        return last.image_id;
    }
    const auto remember = [&](VideoCore::ImageId image_id, bool exact, u64 uid) {
        last.key = key;
        last.key_size = key_size;
        last.generation = generation;
        last.image_id = image_id;
        last.exact = exact;
        last.uid = uid;
    };
    u64 hash = 0xCBF29CE484222325ull;
    for (u32 i = 0; i < key_size; i += 8) {
        u64 word;
        std::memcpy(&word, key.data() + i, 8);
        hash = (hash ^ word) * 0x100000001B3ull;
        hash ^= hash >> 29;
    }
    auto& memo = target_memo[hash % target_memo.size()];
    if (memo_enabled && memo.key_size == key_size &&
        std::memcmp(memo.key.data(), key.data(), key_size) == 0 &&
        (memo.generation == generation || RevalidateTarget(memo, generation))) {
        desc = memo.desc;
        texture_cache.MarkFound(memo.image_id);
        remember(memo.image_id, memo.exact, memo.uid);
        return memo.image_id;
    }
    make_desc();
    const auto range = desc.view_info.range;
    const VideoCore::ImageId image_id = texture_cache.FindImage(desc);
    if (generation == texture_cache.RegistryGeneration()) {
        // FindImage moved no view into another image's mips or layers, and found the
        // registered image of exactly this description.
        const bool exact =
            desc.view_info.range == range && texture_cache.IsExactMatch(image_id, desc.info);
        memo.key = key;
        memo.key_size = key_size;
        memo.generation = generation;
        memo.image_id = image_id;
        memo.exact = exact;
        memo.uid = texture_cache.ImageUid(image_id);
        memo.desc = desc;
        remember(image_id, exact, memo.uid);
    } else {
        last.generation = ~0ULL;
    }
    return image_id;
}

void Rasterizer::PrepareRenderState(const GraphicsPipeline* pipeline) {
    auto& dc = Dc();
    BB_SECTION(PrepareRenderState);
    // Prefetch render targets to handle overlaps with bound textures (e.g. mipgen)
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = Regs();
    if (foliage_mask) {
        FoliageCheckReceivers();
    }
    EffectsBeforeTargets(pipeline);
    // bbport: a Froyok composite whose pyramid waited since the DoF recombination (FroyokBloom::
    // Generate) has it built here, before this draw's targets and resources.
    froyok_bloom->BeforeComposite(pipeline->GetStages()[u32(Shader::SwStage::Fragment)]);
    if (regs.color_control.degamma_enable) {
        LOG_WARNING(Render_Vulkan, "Color buffers require gamma correction");
    }

    const bool skip_cb_binding =
        regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Disable;
    for (s32 cb = 0; cb < std::bit_width(key.mrt_mask); ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        const auto& col_buf = regs.color_buffers[cb];
        const u32 target_mask = regs.color_target_mask.GetMask(cb);
        if (skip_cb_binding || !col_buf || !target_mask || (key.mrt_mask & (1 << cb)) == 0) {
            image_id = {};
            continue;
        }
        const auto& hint = CbExtent(cb);
        const u32 tag = 1;
        image_id = dc.bound_images.emplace_back(FindTargetMemoized(
            desc, last_targets[cb], [&] { std::construct_at(&desc, col_buf, hint); }, tag,
            col_buf, hint));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
    }

    if ((regs.depth_control.depth_enable && regs.depth_buffer.DepthValid()) ||
        (regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid())) {
        const auto htile_address = regs.depth_htile_data_base.GetAddress();
        const auto& hint = DbExtent();
        auto& [image_id, desc] = db_desc;
        const u32 tag = 2;
        image_id = dc.bound_images.emplace_back(FindTargetMemoized(
            desc, last_targets[AmdGpu::NUM_COLOR_BUFFERS],
            [&] {
                std::construct_at(&desc, regs.depth_buffer, regs.depth_view, regs.depth_control,
                                  htile_address, hint);
            },
            tag, regs.depth_buffer, regs.depth_view, regs.depth_control, htile_address, hint));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
    } else {
        db_desc.first = {};
    }
    // bbport: the G-buffer pass (5+ color targets) holds the scene depth, and its constants the
    // main camera (shadow passes bind the same layout with the light's camera).
    gbuffer_draw = camera_motion->Enabled() && std::popcount(key.mrt_mask) >= 5 && db_desc.first;
    if (gbuffer_draw) {
        if (db_desc.first != camera_motion->Depth()) {
            if (caustics) caustics->ResetNativeBedPass();
            if (sewer_receiver) SewerReceiverGBufferChange();
        }
        const auto& vp = regs.viewports[0];
        camera_motion->OnGBufferPass(db_desc.first, vp.xscale < 0.0f ? -1.0f : 1.0f,
                                     vp.yscale < 0.0f ? -1.0f : 1.0f);
    }
    // bbport (r86l_glint-pick-glass, TOOL): the draws of a pick frame that are narrowed to the patch and given a query: the
    // G-buffer's (as r89j had it) and, with the glass pick armed, the forward draws of the scene (a depth target that is no sun
    // shadow pass, a colour target, the scene's frame running). Off: trees_pick_rect_on is false, nothing else is read.
    trees_pick_draw = trees_pick_rect_on &&
                      (gbuffer_draw ||
                       (trees_pick_glass && scene_started && db_desc.first && key.mrt_mask != 0 &&
                        !(regs.depth_buffer.Pitch() == regs.depth_buffer.Height() && regs.depth_buffer.Height() >= 1024)));
    if (window_receiver && window_receiver->pane && window_receiver->pane->owner) {
        NoteWindowOwnerTargets(pipeline);
    }
    EffectsAfterTargets(pipeline);
    if (upscaler->Enabled() && cb_descs[0].first) {
        upscaler->OnColorTarget(cb_descs[0].first);
    }
    // bbport: scene color: a full-size RGBA16F target drawn with the scene depth.
    if (upscaler->Enabled() && db_desc.first && db_desc.first == camera_motion->Depth() &&
        cb_descs[0].first && std::popcount(key.mrt_mask) <= 2) {
        const auto& color = texture_cache.GetImage(cb_descs[0].first);
        const auto& depth = texture_cache.GetImage(db_desc.first);
        if (color.info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
            color.info.size.width == depth.info.size.width &&
            color.info.size.height == depth.info.size.height) {
            upscaler->OnSceneColor(cb_descs[0].first);
            // Blended geometry without depth writes (not full-screen passes): transparents and
            // effects start. Blended layers writing depth (decals, wet/blood ground) are
            // surfaces and stay in the history.
            if (regs.blend_control[0].enable && !regs.color_buffers[0].info.blend_bypass &&
                !regs.depth_control.depth_write_enable &&
                (regs.num_indices > 6 || regs.num_instances.NumInstances() > 1)) {
                EffectsBlendedScene();
                upscaler->OnBlendedSceneDraw();
            } else if (regs.num_indices <= 6 && regs.num_instances.NumInstances() <= 1) {
                // bbport (r45b_drawn-look-fixes): a particle system of six indices or fewer (a
                // card of fog, a few sparks) is as small a draw as a full-screen pass, and is one
                // of the transparents: blended, no depth written, tested against the scene's
                // depth. The drawn look paints before it as before a larger one (it was painted
                // over: one card of fog a frame at the place this was found, up to fifteen draws
                // in a level's first seconds) and does not take it for the fog composite. Only with
                // the look on; the upscaler's two calls are as they were.
                if (drawn_look_wanted &&
                    DrawnLookParams::SmallTransparent(
                        regs.blend_control[0].enable, regs.color_buffers[0].info.blend_bypass,
                        regs.depth_control.depth_write_enable, regs.depth_control.depth_enable,
                        regs.depth_control.depth_func == AmdGpu::CompareFunc::Always)) {
                    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
                    drawn_look->OnSmallTransparent(ps ? ps->pgm_hash : 0, regs.num_indices);
                    EffectsBlendedScene();
                } else {
                    // A full-screen pass over the scene (the fog composite): the transparents
                    // are in.
                    EffectsSceneComposite(pipeline);
                }
                upscaler->OnSceneComposite();
            }
        }
    }
}

void Rasterizer::NotifyUiDraw(const GraphicsPipeline* pipeline) {
    if (!upscaler->Enabled()) return;
    const auto& key = pipeline->GetGraphicsKey();
    const auto vs_hash = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    const auto& regs = Regs();
    if (!UiComposition::ObserveDraw(key.mrt_mask, vs_hash, regs.depth_control.stencil_enable))
        return;
    auto color = cb_descs[0].first;
    // A stencil-only pipeline does not resolve colour bindings. Reuse a previous
    // colour only if it is still the engine's bound target, never another pass's.
    if (key.mrt_mask == 0 && color &&
        (!regs.color_buffers[0] || texture_cache.GetImage(color).info.guest_address !=
                                      regs.color_buffers[0].Address())) {
        color = {};
    }
    const auto& viewport = regs.viewports[0];
    upscaler->OnDraw(vs_hash, color, db_desc.first,
                     UiComposition::NativeViewport(viewport.xscale * 2, viewport.yscale * 2),
                     UiComposition::WidenedUiViewport(viewport.xscale * 2, viewport.yscale * 2));
}

// bbport (r77_parallel-test-runs): clean shot (BbSettings clean_shot, set at the start by
// BB_CLEAN_SHOT=1, latched per frame at the display pass into clean_shot_frame). In a frame that
// drew the world, from its first UI draw (a Scaleform draw into the frame or a clip mask on a
// stencil buffer of the G-buffer's size, after the G-buffer pass) up to the display pass, every
// draw into the UI's target or onto its stencil buffer is left out before its targets, bindings
// and pass (UiComposition::CleanShotSkip has the exact rule): Scaleform's images and clip masks
// and the UI draws of other shaders (text, the item icons drawn through the masks, the gauges'
// backgrounds). Draws into other targets stay (Scaleform's own caches, the next frame's passes).
// The frame reaches its display pass as one without UI, as with the HUD hidden in the game's
// options; by reading the code the upscale, frame generation's HUD-less image and native HDR's
// map take their existing no-UI paths. A frame without a G-buffer pass (loading screens) keeps
// its UI. Off: one plain bool test per draw. On: a popcount per draw, a few register reads and
// address compares per draw after the world; fewer draws recorded.
static const std::atomic<bool>& clean_shot = BbSettings::Get().clean_shot; // read once a frame
// bbport (r102b_camera-clean-hud): what clean shot did, one log line every 300 frames while it is on
// (CleanShotTally at the display pass): frames whose UI it found and left out, frames that drew the
// world but in which it found no UI (no HUD on screen then, or a HUD drawn without a menu-movie draw:
// that one stays), frames without the world (loading screens keep their UI), the draws left out, and
// the draws onto the finished picture before the UI (in World, onto the target an earlier frame-size
// RGBA8 draw of the same frame wrote). That last count includes the scene's own passes onto the
// tonemapped picture, so it is not 0 in a normal frame; a rise per frame in some state (a prompt, a
// lock-on) over plain standing is a HUD piece drawn before the first movie draw, which stays in the
// picture. Counted only while clean shot is on; recording is single-threaded (as clean_shot_state).
struct CleanShotCounts {
    u32 frames[3] = {}; // by UiComposition::CleanShotPhase at the display pass
    u32 left_out = 0, onto_frame = 0;
};
static_assert(static_cast<u32>(UiComposition::CleanShotPhase::NoWorld) == 0 &&
              static_cast<u32>(UiComposition::CleanShotPhase::World) == 1 &&
              static_cast<u32>(UiComposition::CleanShotPhase::Ui) == 2);
static CleanShotCounts clean_shot_counts;
static void CleanShotTally(UiComposition::CleanShotPhase phase) {
    CleanShotCounts& c = clean_shot_counts;
    ++c.frames[static_cast<u32>(phase)];
    const u32 total = c.frames[0] + c.frames[1] + c.frames[2];
    if (total < 300) {
        return;
    }
    std::printf("Camera: clean shot, last %u frames: %u with the UI left out (%u draws), %u with the "
                "world and no UI found, %u without the world; %u draws onto the finished picture "
                "before the UI\n",
                total, c.frames[2], c.left_out, c.frames[1], c.frames[0], c.onto_frame);
    c = {};
}
bool Rasterizer::CleanShotEarly(const GraphicsPipeline* pipeline) {
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    UiComposition::CleanShotDraw draw;
    draw.world_pass = UiComposition::WorldPass(
        key.mrt_mask, regs.depth_control.depth_enable && regs.depth_buffer.DepthValid());
    if (!draw.world_pass && clean_shot_state.phase == UiComposition::CleanShotPhase::NoWorld) {
        return false;
    }
    const auto& cb = regs.color_buffers[0];
    if ((key.mrt_mask & 1) && cb) {
        const auto extent = CbExtent(0);
        draw.color = cb.Address();
        draw.rgba8 = cb.GetDataFmt() == AmdGpu::DataFormat::Format8_8_8_8;
        draw.display = FrameCapture::IsDisplayBuffer(draw.color);
        draw.width = extent.Valid() ? extent.width : cb.Pitch();
        draw.height = extent.Valid() ? extent.height : cb.Height();
    }
    if (!draw.world_pass) {
        draw.movie = UiComposition::MovieShader(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash);
        const auto& db = regs.depth_buffer;
        if (regs.depth_control.stencil_enable && db.StencilValid()) {
            const auto extent = DbExtent();
            draw.stencil = db.StencilAddress();
            draw.stencil_width = extent.Valid() ? extent.width : db.Pitch();
            draw.stencil_height = extent.Valid() ? extent.height : db.Height();
        }
    }
    // bbport (r102b_camera-clean-hud): counted for CleanShotTally
    const u64 ldr_before = clean_shot_state.ldr;
    const bool skip = UiComposition::CleanShotSkip(clean_shot_state, draw);
    clean_shot_counts.left_out += skip ? 1u : 0u;
    if (!skip && ldr_before != 0 && draw.color == ldr_before &&
        clean_shot_state.phase == UiComposition::CleanShotPhase::World) {
        ++clean_shot_counts.onto_frame;
    }
    return skip;
}

static std::pair<u32, u32> GetDrawOffsets(
    const AmdGpu::Regs& regs, const Shader::Info& info,
    const std::optional<Shader::Gcn::FetchShaderData>& fetch_shader) {
    u32 vertex_offset = regs.index_offset;
    u32 instance_offset = 0;
    if (fetch_shader) {
        if (vertex_offset == 0 && fetch_shader->vertex_offset_sgpr != -1) {
            vertex_offset = info.UserData()[fetch_shader->vertex_offset_sgpr];
        }
        if (fetch_shader->instance_offset_sgpr != -1) {
            instance_offset = info.UserData()[fetch_shader->instance_offset_sgpr];
        }
    }
    return {vertex_offset, instance_offset};
}

void Rasterizer::EliminateFastClear() {
    const bool log_gap = window_receiver && window_receiver->pane && window_receiver->pane->owner &&
                         NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap::FastClear);
    auto& col_buf = Regs().color_buffers[0];
    if (!col_buf || !col_buf.info.fast_clear) {
        if (log_gap) {
            LogWindowOwnerGap("eliminate-fast-clear",
                              fmt::format("mrt=0 no-eligible-target cb={:#x} cmask={:#x}",
                                          col_buf.Address(), col_buf.CmaskAddress()).c_str());
        }
        return;
    }
    VideoCore::TextureCache::ImageDesc desc(col_buf, CbExtent(0));
    if (log_gap) {
        LogWindowOwnerGap("eliminate-fast-clear",
                          fmt::format("mrt=0 dst={:#x}+{:#x} cmask={:#x} slices={}..{}",
                                      desc.info.guest_address, desc.info.guest_size,
                                      col_buf.CmaskAddress(), u32(col_buf.view.slice_start),
                                      u32(col_buf.view.slice_max)).c_str());
    }
    const auto image_id = texture_cache.FindImage(desc);
    const auto& image_view = texture_cache.FindRenderTarget(image_id, desc);
    if (!texture_cache.IsMetaCleared(col_buf.CmaskAddress(), col_buf.view.slice_start)) {
        return;
    }
    for (u32 slice = col_buf.view.slice_start; slice <= col_buf.view.slice_max; ++slice) {
        texture_cache.TouchMeta(col_buf.CmaskAddress(), slice, false);
    }
    auto& image = texture_cache.GetImage(image_id);
    const auto clear_value = LiverpoolToVK::ColorBufferClearValue(col_buf);

    ScopeMarkerBegin(fmt::format("EliminateFastClear:MRT={:#x}:M={:#x}", col_buf.Address(),
                                 col_buf.CmaskAddress()));
    runtime.ClearImage(&image, desc.view_info.range, clear_value);
    ScopeMarkerEnd();
}

// bbport: two-stage draw pipeline (vk_draw_pipe.h). Packet layout, 8-byte aligned parts:
// DrawPacket, u16 block indices, u32 block words (RegDirty::BlockWords each), then per stage a
// PacketStage with its user data and flattened user data, then (verification) the full file.
namespace {
enum class PacketKind : u32 { Draw, Task, Dispatch, Special, Indirect, IndirectDispatch };
namespace Object3 = ReflectionOrdinal3;
struct TaskPacket {
    PacketKind kind;
    u32 size;
    Rasterizer::OrderedTask task;
};
struct DrawPacket {
    PacketKind kind;
    u32 ordinal3_packet_high; ///< occupies the existing pointer alignment slot
    const Pipeline* pipeline;
    const PreparedDraw* prepared;
    u32 index_offset;
    u8 is_indexed;
    u8 regs_reset;
    u16 num_blocks;
    u32 num_stages;
    u32 verify;
    std::array<AmdGpu::CbDbExtent, AmdGpu::NUM_COLOR_BUFFERS> cb_extent;
    AmdGpu::CbDbExtent db_extent;
    u32 num_vsharps; ///< V#s of the vertex streams, after the indirect arguments
    u32 num_gx_registers;
    u64 index_key;
    u32 num_view_keys;
    u32 wall_stream_packet; ///< uses the existing alignment slot before ring_end
    u64 ring_end; ///< constant ring position after this packet's copies
};
struct PacketStage {
    const Shader::Info* info;
    VAddr pgm_base;
    u32 ud_size;
    u32 flat_size;
    u32 num_ring;
    u32 pad;
};
static_assert(offsetof(DrawPacket, ordinal3_packet_high) == 4);
static_assert(offsetof(DrawPacket, pipeline) == 8);
static_assert(sizeof(DrawPacket) == offsetof(DrawPacket, ring_end) + sizeof(u64));
static_assert(sizeof(PacketStage) == 32 && offsetof(PacketStage, pad) == 28);

enum class WallRingReason : u32 {
    None, Disabled, Absent, Empty, Large, GpuModified, PendingWrite, Allocation, Hle, Reused, Copied
};

bool Ordinal3Stages(const GraphicsPipeline& pipeline) {
    const auto& key = pipeline.GetGraphicsKey();
    return !key.foliage_mask && Object3::ExactStages(
        key.stage_hashes[u32(Shader::SwStage::Vertex)],
        key.stage_hashes[u32(Shader::SwStage::Fragment)]);
}

bool WallStreamStages(const GraphicsPipeline& pipeline) {
    const auto& key = pipeline.GetGraphicsKey();
    return !key.foliage_mask &&
           key.stage_hashes[u32(Shader::SwStage::Vertex)] == ReflectionDiscard::Wall.vertex_stage &&
           key.stage_hashes[u32(Shader::SwStage::Fragment)] == ReflectionDiscard::Wall.fragment_stage;
}

bool WallStreamOn() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_WALL_STREAM");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on && ReflectionNativeProbe::ExactEquivalenceOn();
}

const char* WallRingReasonName(u32 reason) {
    constexpr std::array names{"no-packet", "ring-disabled", "object-absent", "empty", "large",
        "gpu-modified", "pending-gpu-write", "ring-allocation-failed", "hle", "ring-reused", "ring-copied"};
    return names[reason];
}
constexpr u32 AlignPacket(u32 size) {
    return (size + 7) & ~7u;
}
u32 VerifyInterval() {
    static const u32 interval = [] {
        const char* env = std::getenv("BB_PIPE_VERIFY");
        return env ? static_cast<u32>(std::strtoul(env, nullptr, 10)) : 0u;
    }();
    return interval;
}
} // namespace

bool Rasterizer::DrawPipeWanted() {
    const char* env = std::getenv("BB_DRAW_PIPE");
    if (env && env[0]) {
        return env[0] == '1';
    }
    // Stage B spins while draws flow. Measured ahead with 16 threads (+19%) and with 4 cores /
    // 8 threads (taskset, Steam Deck-like: +18%).
    return BbThreads::Available() >= 8;
}

bool Rasterizer::UseDrawPipe() const {
    return draw_pipe && !host_markers_enabled && !BbToggle::Disabled(BbToggle::DrawPipeline);
}

bool Rasterizer::OnStageA() const {
    return std::this_thread::get_id() == liverpool->GetGpuCommandProcessorThread();
}

namespace {
/// Stage A: cycles waited per drain site (BB_FRAME_STATS), keyed by function name and line.
std::unordered_map<const char*, std::unordered_map<u32, u64>> drain_sites;
} // namespace

void Rasterizer::DrainDrawPipe(u32 reason, u32 line, const char* function) {
    if (!draw_pipe || !OnStageA()) {
        return;
    }
    static const bool stats = std::getenv("BB_FRAME_STATS") != nullptr;
    if (!stats) {
        draw_pipe->Drain(reason);
        return;
    }
    const u64 before = draw_pipe->drain_cycles;
    draw_pipe->Drain(reason);
    if (const u64 waited = draw_pipe->drain_cycles - before) {
        drain_sites[function][line] += waited;
    }
}

bool Rasterizer::IsGpuSideThread() const {
    // bbport: a copy thread working for one of them (BbCopy::ForGpuSide) too.
    return OnStageA() || DrawPipe::OnStageB() || BbCopy::ForGpuSide();
}

bool Rasterizer::IsGpuSideThreadId(u32 tid) const {
    // The userfaultfd thread handles the fault while the faulting thread waits: without locks
    // only if that thread owns the caches. The GPU command thread does not while the draw
    // recording thread may be running, so its faults take the locked path of guest threads.
    if (draw_pipe) {
        return tid == draw_pipe->StageBThreadId();
    }
    return tid == liverpool->GetGpuCommandProcessorThreadId();
}

void Rasterizer::NotePendingGpuWrite(VAddr address, u64 size) {
    if (!draw_pipe || !size) {
        return;
    }
    BbEngine::GxObjects::NoteGpuWrite(address, size);
    // Numbered by packet (a position, the packet's start, counted as reached once the packet
    // before it had run, while this one was not recorded yet), in hashed granules: a lookup per
    // constant binding instead of a scan of the writes (a list scan was ~5% of this thread).
    newest_pending_write = draw_pipe->NextPacket();
    pending_write_table.Note(address, size, newest_pending_write);
    const u64 first = address >> 20, last = (address + size - 1) >> 20;
    for (u64 g = first; g <= last && g - first < 64; ++g) {
        const u64 at = std::min<u64>(g, gpu_written_granules.size() * 64 - 1);
        gpu_written_granules[at >> 6] |= u64(1) << (at & 63);
    }
}

bool Rasterizer::ReadTrackingFiltered() {
    static const bool filtered = [] {
        const char* env = std::getenv("LANTERN_READ_FILTER");
        return !env || env[0] == '1';
    }();
    return filtered;
}

bool Rasterizer::WaitedOnBefore(VAddr address, u64 size) const {
    const u64 first = address >> WaitedGranuleShift, last = (address + size - 1) >> WaitedGranuleShift;
    if (last - first >= WaitedScanLimit) {
        return true;
    }
    for (u64 granule = first; granule <= last; ++granule) {
        if (waited_on[(granule >> 6) & (waited_on.size() - 1)] & (1ull << (granule & 63))) {
            return true;
        }
    }
    return false;
}

bool Rasterizer::NoteWaitedOn(VAddr address, u64 size) {
    bool fresh = false;
    for (u64 granule = address >> WaitedGranuleShift; granule <= (address + size - 1) >> WaitedGranuleShift; ++granule) {
        u64& word = waited_on[(granule >> 6) & (waited_on.size() - 1)];
        const u64 bit = 1ull << (granule & 63);
        fresh |= (word & bit) == 0;
        word |= bit;
    }
    return fresh;
}

void Rasterizer::NotePendingRead(VAddr address, u64 size) {
    if (draw_pipe && size && OnStageA()) {
        if (ReadTrackingFiltered() && !WaitedOnBefore(address, size)) {
            return;
        }
        pending_reads.Note(address, size, draw_pipe->NextPacket());
    }
}

void Rasterizer::WaitForPendingReads(VAddr address, u64 size) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_CONSTRAM_PIPE");
        return !env || env[0] != '0';
    }();
    if (!draw_pipe || !OnStageA()) {
        return;
    }
    if (!enabled || !UseDrawPipe() || size == 0) {
        DrainDrawPipe(DrawPipe::ReasonConstRam);
        return;
    }
    if (ReadTrackingFiltered() && NoteWaitedOn(address, size)) {
        DrainDrawPipe(DrawPipe::ReasonConstRam);
        return;
    }
    const u64 packet = std::max(untracked_reads_packet, pending_reads.Newest(address, size));
    if (draw_pipe->ReachedPacket(packet)) {
        ++constram_waits_skipped;
        return;
    }
    draw_pipe->WaitForPacket(packet, DrawPipe::ReasonConstRam);
}

void Rasterizer::NoteCommandWriteInOrder(VAddr addr, const void* data, u64 size) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_CONSTRAM_PIPE");
        return !env || env[0] != '0';
    }();
    if (VideoCore::WriteTracking() || !IsMapped(addr, size)) {
        return;
    }
    if (!enabled || !UseDrawPipe() || !OnStageA() || size > 1_MB) {
        NoteCommandWrite(addr, data, size, false);
        return;
    }
    // The caches belong to the recording thread while it has packets: it updates them in order
    // (later packets see the new bytes there; the memory already holds them for this thread).
    struct Header {
        VAddr addr;
        u64 size;
    };
    thread_local std::vector<u8> payload;
    payload.resize(sizeof(Header) + size);
    const Header header{addr, size};
    std::memcpy(payload.data(), &header, sizeof(header));
    std::memcpy(payload.data() + sizeof(header), data, size);
    RunInOrder(
        [](Rasterizer& self, const u8* bytes) {
            Header write;
            std::memcpy(&write, bytes, sizeof(write));
            self.NoteCommandWrite(write.addr, bytes + sizeof(write), write.size, true);
        },
        payload.data(), static_cast<u32>(payload.size()), BbToggle::PipelinedTasks, false,
        "CommandWrite");
}

bool Rasterizer::PendingWriteOverlaps(VAddr address, u64 size) {
    if (!draw_pipe || size == 0) {
        return false;
    }
    if (ReadTrackingFiltered() && draw_pipe->ReachedPacket(newest_pending_write)) {
        return false;
    }
    const u64 packet = pending_write_table.Newest(address, size);
    return packet != 0 && !draw_pipe->ReachedPacket(packet);
}

void Rasterizer::CollectRingBindings(const Shader::Info& stage, const PreparedDraw* prepared,
                           boost::container::static_vector<RingBinding, Shader::NUM_BUFFERS>& out,
                           u32* wall_reason) {
    const bool ordinal3_reason = wall_reason && (*wall_reason & Object3::RingTag);
    const auto record_ordinal3 = [&](u32 ordinal, Object3::Ring result) {
        if (ordinal3_reason && ordinal == 3) {
            *wall_reason = (*wall_reason & ~Object3::RingReasonMask) | u32(result);
        }
    };
    if (wall_reason) {
        *wall_reason = ordinal3_reason ? Object3::RingTag | u32(Object3::Ring::Absent)
                                      : u32(WallRingReason::Absent);
    }
    const PreparedStage* prepared_stage = nullptr;
    if (prepared && !BbToggle::Disabled(BbToggle::PreparedResources)) {
        for (u32 i = 0; i < prepared->num_stages; ++i) {
            const auto& candidate = prepared->stages[i];
            if (&candidate.program->info == &stage &&
                candidate.num_buffers == stage.buffers.size()) {
                prepared_stage = &candidate;
                break;
            }
        }
    }
    if (ordinal3_reason && prepared_stage) *wall_reason |= Object3::PreparedTag;
    const u64 alignment = std::max<u64>(instance.StorageMinAlignment(),
                                        instance.UniformMinAlignment());
    const auto* gx = static_cast<const BbEngine::GxBindings::State*>(gx_state);
    const u32 gx_stage = stage.sw_stage == Shader::SwStage::Vertex     ? 0
                         : stage.sw_stage == Shader::SwStage::Fragment ? 1
                                                                       : 2;
    const bool tracked = gx && gx_stage < 2 && BbEngine::GxRecords::ConstantsTracked();
    std::array<std::pair<VAddr, u32>, 16> versions{};
    u32 num_versions = 0;
    if (tracked) {
        const auto& gs = gx->stages[gx_stage];
        for (u32 slot = 0; slot < 16; ++slot) {
            const u8 at = gs.constants[slot];
            if (at == BbEngine::GxBindings::kUnbound || at >= gx->descriptors) {
                continue;
            }
            const u32* words = gx->words[at];
            versions[num_versions++] = {VAddr(words[0]) | (VAddr(words[1] & 0xfff) << 32),
                                        gs.constant_versions[slot]};
        }
        if (!BbEngine::GxRecords::Intact()) {
            num_versions = 0;
        }
    }
    const auto version_of = [&](VAddr address, u32& version) {
        for (u32 i = 0; i < num_versions; ++i) {
            if (versions[i].first == address) {
                version = versions[i].second;
                return true;
            }
        }
        return false;
    };
    const auto written_by_gpu = [&](VAddr address, u64 size) {
        const u64 first = address >> 20, last = (address + size - 1) >> 20;
        for (u64 g = first; g <= last; ++g) {
            const u64 at = std::min<u64>(g, gpu_written_granules.size() * 64 - 1);
            if (gpu_written_granules[at >> 6] >> (at & 63) & 1) {
                return true;
            }
        }
        return false;
    };
    const auto copy_slot = [&](VAddr address, u64 size) -> ConstantCopy& {
        const u64 key = (address >> 4) ^ (size << 40);
        return constant_copies[(key * 0x9E3779B97F4A7C15ull) >> 52];
    };
    const auto reuse = [&](u32 index, VAddr address, u64 size) {
        u32 version;
        if (!num_versions || !version_of(address, version)) {
            return false;
        }
        auto& memo = copy_slot(address, size);
        const bool known = memo.address == address && memo.size == size && memo.version == version &&
                           constant_ring->Reusable(memo.at) && !written_by_gpu(address, size);
        if (!known) {
            BbEngine::GxRecords::NoteConstant(false, false, true, address, u32(size));
            return false;
        }
        const bool check = memo.hash != 0;
        bool same = true;
        if (check && memory->IsValidGpuMapping(address, size)) {
            same = (XXH3_64bits(reinterpret_cast<const void*>(address), size) | 1) == memo.hash;
            if (same && !BbEngine::GxRecords::Compared()) {
                memo.hash = 0;
            }
        }
        BbEngine::GxRecords::NoteConstant(same, check, same, address, u32(size));
        if (!same) {
            memo.address = 0;
            return false;
        }
        constant_ring->Hold(memo.at);
        out.push_back({index, static_cast<u32>(size),
#ifdef BB_TEST_SHARED_POST_GRAPH
                       memo.at,
#else
                       memo.offset,
#endif
                       address});
        return true;
    };
    const auto copy = [&](u32 index, const void* source, VAddr address, u64 size) {
        const auto offset = constant_ring->Allocate(size, alignment);
        if (!offset) {
            return false;
        }
        u8* dst = constant_ring->Data(*offset);
        if (source) {
            std::memcpy(dst, source, size);
        } else {
            memory->CopySparseMemory(address, dst, size);
        }
        constant_ring->Flush(*offset, size);
        out.push_back({index, static_cast<u32>(size),
#ifdef BB_TEST_SHARED_POST_GRAPH
                       constant_ring->LastAbsolute(),
#else
                       *offset,
#endif
                       address});
        u32 version;
        if (!source && num_versions && version_of(address, version)) {
            const bool hashed = (BbEngine::GxRecords::Compared() || (++constant_checks & 63) == 0) &&
                                memory->IsValidGpuMapping(address, size);
            copy_slot(address, size) = {
                address, static_cast<u32>(size), version, constant_ring->LastAbsolute(), *offset,
                hashed ? XXH3_64bits(reinterpret_cast<const void*>(address), size) | 1 : 0};
        }
        return true;
    };
    // Compute stages may run as HLE copy shaders, which read their buffers on the recording
    // thread whether or not they were copied here.
    const bool hle_candidate = stage.sw_stage == Shader::SwStage::Compute;
    for (u32 index = 0; index < stage.buffers.size(); ++index) {
        const auto& desc = stage.buffers[index];
        if (desc.IsSpecial()) {
            record_ordinal3(index, Object3::Ring::Special);
            if (desc.buffer_type == Shader::BufferType::Flatbuf &&
                !stage.flattened_ud_buf.empty()) {
                copy(index, stage.flattened_ud_buf.data(), 0,
                     stage.flattened_ud_buf.size() * sizeof(u32));
            }
            continue;
        }
        const auto vsharp = prepared_stage ? prepared_stage->buffer_sharps[index]
                                           : desc.GetSharp(stage);
        const VAddr address = vsharp.base_address;
        if (address == 0 || vsharp.GetSize() == 0) {
            record_ordinal3(index, Object3::Ring::Empty);
            continue;
        }
        const u64 size = memory->ClampRangeSize(address, vsharp.GetSize());
        if (desc.is_written) {
            record_ordinal3(index, Object3::Ring::Writable);
            NotePendingGpuWrite(address, size);
            continue;
        }
        if (BbCeStats::Enabled()) {
            BbCeStats::Check(size <= VideoCore::BufferCache::STREAM_THRESHOLD
                                 ? BbCeStats::RingConstants
                                 : BbCeStats::LargeBuffer,
                             address, size);
        }
        // The stream path of BufferCache::ObtainBuffer, taken here: small, read-only, not
        // written by the GPU (now or by work still queued for the recording thread). What is not
        // copied is read on the recording thread: a CPU write over these bytes on this thread
        // waits for the packet (WaitForPendingReads).
        if (!hle_candidate && size != 0 && size <= VideoCore::BufferCache::STREAM_THRESHOLD &&
            reuse(index, address, size)) {
            record_ordinal3(index, size != vsharp.GetSize() ? Object3::Ring::Clamped : Object3::Ring::Reused);
            if (wall_reason && index == 0) {
                *wall_reason = u32(WallRingReason::Reused);
            }
            continue;
        }
        const auto result = size == 0 ? WallRingReason::Empty
            : size > VideoCore::BufferCache::STREAM_THRESHOLD ? WallRingReason::Large
            : buffer_cache.IsRegionGpuModified(address, size) ? WallRingReason::GpuModified
            : PendingWriteOverlaps(address, size) ? WallRingReason::PendingWrite
            : !copy(index, nullptr, address, size) ? WallRingReason::Allocation
            : hle_candidate ? WallRingReason::Hle : WallRingReason::Copied;
        if (wall_reason && index == 0) {
            *wall_reason = u32(result);
        }
        if (ordinal3_reason && index == 3) {
            const auto reason = result == WallRingReason::Empty ? Object3::Ring::Empty :
                result == WallRingReason::Large ? Object3::Ring::Large :
                result == WallRingReason::GpuModified ? Object3::Ring::GpuModified :
                result == WallRingReason::PendingWrite ? Object3::Ring::PendingWrite :
                result == WallRingReason::Allocation ? Object3::Ring::Allocation :
                size != vsharp.GetSize() ? Object3::Ring::Clamped : Object3::Ring::Copied;
            record_ordinal3(index, reason);
        }
        if (result != WallRingReason::Copied) {
            NotePendingRead(address, size);
        }
    }
}

void Rasterizer::PostDraw(const Pipeline* pipeline, const PreparedDraw* used_prepared,
                          bool is_indexed, u32 index_offset, const AmdGpu::ComputeProgram* cs,
                          const IndirectDraw* indirect) {
    auto& dirty = liverpool->pipe_dirty;
    if (!pipe_synced) {
        // Stage B has not run yet: its register copy starts as this one.
        pipe_regs = liverpool->regs;
        dirty.Clear();
        pipe_synced = true;
    }
    std::array<u16, AmdGpu::RegDirty::NumBlocks> blocks;
    u32 num_blocks = 0;
    for (size_t block = dirty.blocks._Find_first(); block < dirty.blocks.size();
         block = dirty.blocks._Find_next(block)) {
        blocks[num_blocks++] = static_cast<u16>(block);
    }
    const auto stages =
        pipeline ? pipeline->GetStages() : std::span<const Shader::Info* const>{};
    const Shader::Info* wall_vertex = nullptr;
    if (pipeline && is_indexed && !cs && !indirect && liverpool->regs.num_indices == 42441 && WallStreamOn()) {
        const auto* vs = stages[u32(Shader::SwStage::Vertex)];
        const auto* ps = stages[u32(Shader::SwStage::Fragment)];
        if (vs && ps && ReflectionNativeProbe::Match({vs->pgm_hash, ps->pgm_hash, 42441, index_offset}) ==
                           u32(ReflectionFirstHit::PlacedSource::Wall)) {
            wall_vertex = vs;
        }
    }
    const Shader::Info* ordinal3_vertex = nullptr;
    if (pipeline && is_indexed && !cs && !indirect && liverpool->regs.num_indices == 24 && Object3::On()) {
        const auto* vs = stages[u32(Shader::SwStage::Vertex)];
        const auto* ps = stages[u32(Shader::SwStage::Fragment)];
        if (vs && ps && Object3::ExactKey(vs->pgm_hash, ps->pgm_hash, 24, index_offset) &&
            Ordinal3Stages(*static_cast<const GraphicsPipeline*>(pipeline))) {
            ordinal3_vertex = vs;
        }
    }
    u32 ordinal3_reason = Object3::RingTag | u32(Object3::Ring::Disabled);
    u32 wall_reason = u32(WallRingReason::Disabled);
    // Constants: copied here into the ring, the recording thread only binds them.
    thread_local std::array<boost::container::static_vector<RingBinding, Shader::NUM_BUFFERS>,
                            Shader::MaxStageTypes>
        rings;
    u32 num_stages = 0;
    u32 size = sizeof(DrawPacket) + AlignPacket(num_blocks * sizeof(u16)) +
               num_blocks * AmdGpu::RegDirty::BlockWords * sizeof(u32);
    for (const auto* stage : stages) {
        if (stage) {
            auto& ring = rings[num_stages];
            if (BbCeStats::Enabled()) {
                const auto ud = stage->UserData();
                for (size_t i = 0; i + 1 < ud.size(); ++i) {
                    const u64 value = u64(ud[i]) | u64(ud[i + 1]) << 32;
                    if (value >= 0x100000000ull && value < (1ull << 40)) {
                        BbCeStats::Check(BbCeStats::UserDataPointer, value, 64);
                    }
                }
                BbCeStats::Get().checks[BbCeStats::DmaStage]++;
                BbCeStats::Get().hits[0][BbCeStats::DmaStage] += stage->uses_dma ? 1 : 0;
            }
            ring.clear();
            if (constant_ring && !BbToggle::Disabled(BbToggle::ConstantRing)) {
                BbSections::ScopeA ring_scope{BbSections::ARing};
                CollectRingBindings(*stage, used_prepared, ring,
                    stage == wall_vertex ? &wall_reason : stage == ordinal3_vertex ? &ordinal3_reason : nullptr);
            } else {
                untracked_reads_packet = draw_pipe->NextPacket(); // bindings not listed
            }
            ++num_stages;
            size += sizeof(PacketStage) +
                    AlignPacket(u32(stage->user_data.size() + stage->flattened_ud_buf.size()) *
                                sizeof(u32)) +
                    u32(ring.size() * sizeof(RingBinding));
        }
    }
    if (cs) {
        size += AlignPacket(sizeof(AmdGpu::ComputeProgram));
    }
    if (indirect) {
        size += AlignPacket(sizeof(IndirectDraw));
        // The arguments are read on the recording thread.
        const u64 args_size = u64(std::max(indirect->stride, 4u)) * std::max(indirect->max_count, 1u);
        if (args_size <= 16_MB) {
            NotePendingRead(indirect->args, args_size);
        } else {
            untracked_reads_packet = draw_pipe->NextPacket();
        }
        if (indirect->count) {
            NotePendingRead(indirect->count, sizeof(u32));
        }
    }
    // bbport: the V#s of the vertex streams, read here from the tables the user data points to:
    // those tables are what the game's constant engine dumps (a ring of ~25 pages rewritten
    // ~14000 times a second). Read on the recording thread instead, a later dump had often
    // replaced them by then: depth of field drew its passes with another draw's vertices (a
    // flipped copy of the scene, streaks and blocks in the sky; issue #44). The streams' data and
    // the index buffer are still read there: a DumpConstRam over them waits for this packet.
    thread_local boost::container::static_vector<AmdGpu::Buffer, Shader::NUM_BUFFERS> vsharps;
    vsharps.clear();
    thread_local boost::container::static_vector<u64, Shader::NUM_BUFFERS> vkeys;
    vkeys.clear();
    const bool by_object = BbEngine::GxRecords::BindsByObject() && gx_state;
    u64 index_key = 0;
    BbSections::ScopeA inputs_scope{BbSections::AInputs};
    if (pipeline && !pipeline->IsCompute()) {
        const auto* graphics = static_cast<const GraphicsPipeline*>(pipeline);
        if (const auto& fetch = graphics->GetFetchShader();
            fetch && fetch->attributes.size() <= vsharps.capacity()) {
            const auto& vs = graphics->GetStage(Shader::SwStage::Vertex);
            const auto* gx = static_cast<const BbEngine::GxBindings::State*>(gx_state);
            for (const auto& attrib : fetch->attributes) {
                u32 words[4];
                const bool recorded = gx && BbEngine::GxBindings::VertexWords(*gx, attrib.dword_offset, words);
                AmdGpu::Buffer buffer{};
                if (recorded) {
                    std::memcpy(&buffer, words, sizeof words);
                    buffer.base_address += attrib.inst_offset;
                    if (attrib.data_format) {
                        buffer.data_format = attrib.data_format;
                        buffer.num_format = attrib.num_format;
                    }
                }
                if (!recorded || BbEngine::GxRecords::Compared() || (draw_pipe->packets & 63) == 0) {
                    const auto old = attrib.GetSharp(vs);
                    if (recorded) {
                        for (u32 w = 0; w < 4; ++w) {
                            BbEngine::GxRecords::NoteWord(2, attrib.dword_offset + w,
                                                          reinterpret_cast<const u32*>(&buffer)[w],
                                                          reinterpret_cast<const u32*>(&old)[w], vs.pgm_hash);
                        }
                    }
                    if (!recorded || BbEngine::GxRecords::Compared()) {
                        buffer = old;
                    }
                }
                vsharps.push_back(buffer);
                vkeys.push_back(recorded && by_object
                                    ? BbEngine::GxBindings::VertexKey(
                                          *static_cast<const BbEngine::GxBindings::State*>(gx_state),
                                          attrib.dword_offset)
                                    : 0);
                if (buffer.base_address != 0 && buffer.GetSize() > 0) {
                    if (BbCeStats::Enabled()) {
                        BbCeStats::Check(BbCeStats::Vertex, buffer.base_address, buffer.GetSize());
                    }
                    NotePendingRead(buffer.base_address, buffer.GetSize());
                }
            }
        }
        if (is_indexed) {
            const auto& regs = liverpool->regs;
            const u32 index_size =
                regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2 : 4;
            const VAddr index_address =
                regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
            const u64 index_bytes = u64(regs.num_indices) * index_size;
            if (BbCeStats::Enabled()) {
                BbCeStats::Check(BbCeStats::Index, index_address, index_bytes);
            }
            NotePendingRead(index_address, index_bytes);
        }
    }
    inputs_scope.End();
    size += AlignPacket(u32(vsharps.size() * sizeof(AmdGpu::Buffer)));
    size += AlignPacket(u32(vsharps.size() * sizeof(u64)));
    if (by_object && is_indexed && !cs && !indirect) {
        const auto* gx = static_cast<const BbEngine::GxBindings::State*>(gx_state);
        if (gx->render.index_known && gx->render.index_base == liverpool->regs.index_base_address.Address<VAddr>()) {
            index_key = gx->index_key;
        }
    }
    u32 num_view_keys = 0;
    thread_local std::array<u64, 2 * BbEngine::GxBindings::kMaxViewKeys> view_keys;
    if (by_object && !cs && !indirect) {
        const auto* gx = static_cast<const BbEngine::GxBindings::State*>(gx_state);
        num_view_keys = std::min(gx->num_view_keys, BbEngine::GxBindings::kMaxViewKeys);
        std::memcpy(view_keys.data(), gx->view_keys, num_view_keys * 2 * sizeof(u64));
    }
    if (by_object && !BbEngine::GxRecords::Intact()) {
        std::fill(vkeys.begin(), vkeys.end(), 0);
        index_key = 0;
        num_view_keys = 0;
    }
    size += AlignPacket(num_view_keys * 2 * u32(sizeof(u64)));
    const u32 gx_count = pipeline && !cs && !indirect ? num_gx_registers : 0;
    size += AlignPacket(u32(gx_count * sizeof(GxRegister)));
    const u32 interval = VerifyInterval();
    const bool verify = interval && (draw_pipe->packets % interval) == 0;
    if (verify) {
        size += sizeof(AmdGpu::Regs);
    }

    BbSections::ScopeA packet_scope{BbSections::APacket};
    u8* out = draw_pipe->Begin(size);
    u8* const start = out;
    auto& packet = *reinterpret_cast<DrawPacket*>(out);
    packet.kind = cs         ? (indirect ? PacketKind::IndirectDispatch : PacketKind::Dispatch)
                  : indirect ? PacketKind::Indirect
                  : pipeline ? PacketKind::Draw
                             : PacketKind::Special;
    packet.pipeline = pipeline;
    packet.prepared = used_prepared;
    packet.index_offset = index_offset;
    packet.is_indexed = is_indexed;
    packet.regs_reset = dirty.reset;
    packet.num_blocks = static_cast<u16>(num_blocks);
    packet.num_stages = num_stages;
    packet.verify = verify;
    packet.cb_extent = liverpool->last_cb_extent;
    packet.db_extent = liverpool->last_db_extent;
    packet.ring_end = constant_ring ? constant_ring->Position() : 0;
    packet.num_vsharps = static_cast<u32>(vsharps.size());
    packet.index_key = index_key;
    packet.num_view_keys = num_view_keys;
    const u64 witness_packet = wall_vertex || ordinal3_vertex ? draw_pipe->NextPacket() : 0;
    packet.wall_stream_packet = u32(witness_packet);
    packet.ordinal3_packet_high = ordinal3_vertex ? u32(witness_packet >> 32) : 0;
    packet.num_gx_registers = gx_count;
    out += sizeof(DrawPacket);
    std::memcpy(out, blocks.data(), num_blocks * sizeof(u16));
    out += AlignPacket(num_blocks * sizeof(u16));
    for (u32 i = 0; i < num_blocks; ++i) {
        std::memcpy(out,
                    liverpool->regs.reg_array.data() + blocks[i] * AmdGpu::RegDirty::BlockWords,
                    AmdGpu::RegDirty::BlockWords * sizeof(u32));
        out += AmdGpu::RegDirty::BlockWords * sizeof(u32);
    }
    u32 stage_index = 0;
    for (const auto* stage : stages) {
        if (!stage) {
            continue;
        }
        const auto& ring = rings[stage_index++];
        auto& header = *reinterpret_cast<PacketStage*>(out);
        header = {stage,
                  stage->pgm_base,
                  static_cast<u32>(stage->user_data.size()),
                  static_cast<u32>(stage->flattened_ud_buf.size()),
                  static_cast<u32>(ring.size()),
                  stage == wall_vertex ? wall_reason : stage == ordinal3_vertex ? ordinal3_reason : 0};
        out += sizeof(PacketStage);
        std::memcpy(out, ring.data(), ring.size() * sizeof(RingBinding));
        out += ring.size() * sizeof(RingBinding);
        std::memcpy(out, stage->user_data.data(), stage->user_data.size_bytes());
        std::memcpy(out + stage->user_data.size_bytes(), stage->flattened_ud_buf.data(),
                    stage->flattened_ud_buf.size() * sizeof(u32));
        out += AlignPacket(u32(stage->user_data.size() + stage->flattened_ud_buf.size()) *
                           sizeof(u32));
    }
    if (cs) {
        std::memcpy(out, cs, sizeof(AmdGpu::ComputeProgram));
        out += AlignPacket(sizeof(AmdGpu::ComputeProgram));
    }
    if (indirect) {
        std::memcpy(out, indirect, sizeof(IndirectDraw));
        out += AlignPacket(sizeof(IndirectDraw));
    }
    std::memcpy(out, vsharps.data(), vsharps.size() * sizeof(AmdGpu::Buffer));
    out += AlignPacket(u32(vsharps.size() * sizeof(AmdGpu::Buffer)));
    std::memcpy(out, vkeys.data(), vkeys.size() * sizeof(u64));
    out += AlignPacket(u32(vsharps.size() * sizeof(u64)));
    std::memcpy(out, view_keys.data(), num_view_keys * 2 * sizeof(u64));
    out += AlignPacket(num_view_keys * 2 * u32(sizeof(u64)));
    std::memcpy(out, gx_registers.data(), gx_count * sizeof(GxRegister));
    out += AlignPacket(u32(gx_count * sizeof(GxRegister)));
    if (verify) {
        std::memcpy(out, &liverpool->regs, sizeof(AmdGpu::Regs));
        out += sizeof(AmdGpu::Regs);
    }
    dirty.Clear();
    draw_pipe->Commit(static_cast<u32>(out - start));
    packet_scope.End();
    PrintPipeStats();
}

void Rasterizer::RetireSubmission() {
    if (!draw_pipe || !OnStageA()) {
        return;
    }
    while (!pipe_keepalive.empty() && draw_pipe->Reached(pipe_keepalive.front().first)) {
        pipe_keepalive.pop_front();
    }
    if (!draw_pipe->Idle()) {
        pipe_keepalive.emplace_back(draw_pipe->Head(), draw_prep->KeepCurrent());
    }
}

namespace {
// BB_SECTIONS: ordered tasks by function (cycles, count), stage B only.
constexpr std::size_t TaskKinds = 16;
std::array<void*, TaskKinds> task_kinds{};
std::array<u64, TaskKinds> task_cycles{}, task_counts{};
/// bbport: the names RunInOrder's callers give their tasks (written by stage A, read with the
/// statistics: racy, diagnostics only).
std::array<std::pair<void*, const char*>, 2 * TaskKinds> task_names{};

void NoteTaskName(void* task, const char* name) {
    for (auto& entry : task_names) {
        if (entry.first == task) {
            return;
        }
        if (!entry.first) {
            entry = {task, name};
            return;
        }
    }
}

const char* TaskName(void* task) {
    for (const auto& entry : task_names) {
        if (entry.first == task) {
            return entry.second;
        }
    }
    return nullptr;
}
} // namespace

bool Rasterizer::RunInOrder(OrderedTask task, const void* data, u32 size, u64 toggle,
                            bool reads_guest_memory, const char* name) {
    if (name && (BbSections::Enabled() || BbSpike::on)) { // r27_flush-split: also its kinds
        NoteTaskName(reinterpret_cast<void*>(task), name);
    }
    if (!UseDrawPipe() || BbToggle::Disabled(toggle)) {
        DrainDrawPipe(DrawPipe::ReasonRasterizer);
        task(*this, static_cast<const u8*>(data));
        return false;
    }
    if (reads_guest_memory) {
        untracked_reads_packet = draw_pipe->NextPacket();
    }
    const u32 total = sizeof(TaskPacket) + AlignPacket(size);
    u8* out = draw_pipe->Begin(total);
    *reinterpret_cast<TaskPacket*>(out) = {PacketKind::Task, size, task};
    std::memcpy(out + sizeof(TaskPacket), data, size);
    draw_pipe->Commit(total);
    return true;
}

bool Rasterizer::NextPacketIsTask(OrderedTask task) const {
    if (!draw_pipe || !DrawPipe::OnStageB()) {
        return false;
    }
    const u8* next = draw_pipe->PeekNext();
    if (!next) {
        return false;
    }
    const auto& packet = *reinterpret_cast<const TaskPacket*>(next);
    return packet.kind == PacketKind::Task && packet.task == task;
}

void Rasterizer::RunDrawPacket(void* context, const u8* data, u32 size) {
    BB_SECTION(Packet);
    auto& self = *static_cast<Rasterizer*>(context);
    auto& dc = self.Dc();
    if (*reinterpret_cast<const PacketKind*>(data) == PacketKind::Task) {
        BB_SECTION(Task);
        self.buffer_cache.NewPacket();
        const auto& task = *reinterpret_cast<const TaskPacket*>(data);
        // bbport (r27_flush-split): a stage B task is what the Flush split adds up (its kind:
        // RunInOrder's name).
        const BbSpike::SplitScope r27_split{
            BbSpike::SplitTask, true,
            BbSpike::on ? TaskName(reinterpret_cast<void*>(task.task)) : nullptr};
        if (BbSections::Enabled()) {
            const u64 t0 = __rdtsc();
            task.task(self, data + sizeof(TaskPacket));
            void* fn = reinterpret_cast<void*>(task.task);
            for (std::size_t k = 0; k < TaskKinds; ++k) {
                if (task_kinds[k] == fn || !task_kinds[k]) {
                    task_kinds[k] = fn;
                    task_cycles[k] += __rdtsc() - t0;
                    ++task_counts[k];
                    break;
                }
            }
            return;
        }
        task.task(self, data + sizeof(TaskPacket));
        return;
    }
    const auto& packet = *reinterpret_cast<const DrawPacket*>(data);
    const u8* in = data + sizeof(DrawPacket);
    const auto* blocks = reinterpret_cast<const u16*>(in);
    in += AlignPacket(packet.num_blocks * sizeof(u16));
    auto& regs = self.pipe_regs;
    if (packet.regs_reset) {
        regs.SetDefaults();
    }
    for (u32 i = 0; i < packet.num_blocks; ++i) {
        std::memcpy(regs.reg_array.data() + blocks[i] * AmdGpu::RegDirty::BlockWords, in,
                    AmdGpu::RegDirty::BlockWords * sizeof(u32));
        in += AmdGpu::RegDirty::BlockWords * sizeof(u32);
    }
    ASSERT(packet.num_stages <= Shader::Info::MaxUdSnapshots);
    dc.wall_stream_packet = packet.wall_stream_packet;
    dc.wall_stream_reason = 0;
    for (u32 i = 0; i < packet.num_stages; ++i) {
        const auto& stage = *reinterpret_cast<const PacketStage*>(in);
        in += sizeof(PacketStage);
        if (stage.pad & Object3::RingTag) {
            Object3::packet = {&self, (u64(packet.ordinal3_packet_high) << 32) | packet.wall_stream_packet, stage.pad};
            dc.wall_stream_packet = 0;
        } else if (stage.pad) {
            dc.wall_stream_reason = stage.pad;
        }
        dc.ring_stages[i] = {stage.info, reinterpret_cast<const RingBinding*>(in),
                               stage.num_ring};
        in += stage.num_ring * sizeof(RingBinding);
        const auto* words = reinterpret_cast<const u32*>(in);
        Shader::Info::ud_snapshots[i] = {stage.info, words, stage.ud_size, words + stage.ud_size,
                                         stage.flat_size, stage.pgm_base};
        in += AlignPacket((stage.ud_size + stage.flat_size) * sizeof(u32));
    }
    Shader::Info::num_ud_snapshots = packet.num_stages;
    dc.num_ring_stages = packet.num_stages;
#ifdef BB_TEST_SHARED_POST_GRAPH
    dc.ring_packet_end = packet.ring_end;
#endif
    const AmdGpu::ComputeProgram* cs = nullptr;
    if (packet.kind == PacketKind::Dispatch || packet.kind == PacketKind::IndirectDispatch) {
        cs = reinterpret_cast<const AmdGpu::ComputeProgram*>(in);
        in += AlignPacket(sizeof(AmdGpu::ComputeProgram));
    }
    const IndirectDraw* indirect = nullptr;
    if (packet.kind == PacketKind::Indirect || packet.kind == PacketKind::IndirectDispatch) {
        indirect = reinterpret_cast<const IndirectDraw*>(in);
        in += AlignPacket(sizeof(IndirectDraw));
    }
    dc.packet_vsharps = {reinterpret_cast<const AmdGpu::Buffer*>(in), packet.num_vsharps};
    in += AlignPacket(u32(packet.num_vsharps * sizeof(AmdGpu::Buffer)));
    dc.packet_vkeys = {reinterpret_cast<const u64*>(in), packet.num_vsharps};
    in += AlignPacket(u32(packet.num_vsharps * sizeof(u64)));
    dc.packet_view_keys = {reinterpret_cast<const u64*>(in), packet.num_view_keys * 2};
    in += AlignPacket(packet.num_view_keys * 2 * u32(sizeof(u64)));
    dc.packet_index_key = packet.index_key;
    thread_local std::array<GxRegister, 160> gx_swapped;
    const u32 gx_count = std::min<u32>(packet.num_gx_registers, gx_swapped.size());
    std::memcpy(gx_swapped.data(), in, gx_count * sizeof(GxRegister));
    in += AlignPacket(u32(packet.num_gx_registers * sizeof(GxRegister)));
    if (packet.verify) {
        // The resource tables the GPU thread walked must read the same now: else a write
        // still queued here (WriteData, DMA) changed them after that thread read them.
        static u32 flat_reports = 0;
        for (u32 i = 0; i < packet.num_stages && flat_reports < 32; ++i) {
            const auto& snapshot = Shader::Info::ud_snapshots[i];
            const auto& srt = snapshot.info->srt_info;
            const auto& plan = snapshot.info->table_plan;
            // bbport: the tables are read again the way RefreshFlatBuf read them (BB_NATIVE_TABLES).
            const bool by_plan = Shader::Native::TablePlan::GetMode() !=
                                     Shader::Native::TablePlan::Mode::Walker &&
                                 plan.valid && Shader::Native::TablePlan::guest_readable;
            // Stages the pipeline selection did not refresh (no user data) keep their tables.
            if ((!srt.walker_func && !by_plan) || snapshot.flat_size == 0 ||
                snapshot.user_data_size == 0) {
                continue;
            }
            std::vector<u32> flat(snapshot.flat_size);
            std::memcpy(flat.data(), snapshot.user_data,
                        std::min(snapshot.user_data_size, snapshot.flat_size) * sizeof(u32));
            if (by_plan && plan.flat_dwords == snapshot.flat_size) {
                // Every read checked: stale pointers read as zeros, nothing to recover from.
                plan.Run(snapshot.user_data, flat.data(), Shader::Native::TablePlan::guest_readable);
            } else {
                if (!srt.walker_func) {
                    continue;
                }
                // Pointers in the tables may be stale by now: a fault only skips the check.
                BbRecoverBuf recover;
                if (BB_RECOVER_SET(recover)) {
                    runtime_fault_recover = nullptr;
                    continue;
                }
                runtime_fault_recover = &recover;
                srt.walker_func(snapshot.user_data, flat.data());
                runtime_fault_recover = nullptr;
            }
            if (std::memcmp(flat.data(), snapshot.flat, snapshot.flat_size * sizeof(u32)) != 0) {
                u32 first = 0, count = 0;
                for (u32 w = 0; w < snapshot.flat_size; ++w) {
                    if (flat[w] != snapshot.flat[w]) {
                        first = count++ ? first : w;
                    }
                }
                std::printf("Draw pipe: resource tables of shader %016llx changed after the GPU "
                            "thread read them (%u of %u words, first %u: %#x -> %#x, user data "
                            "%u words)\n",
                            static_cast<unsigned long long>(snapshot.info->pgm_hash), count,
                            snapshot.flat_size, first, snapshot.flat[first], flat[first],
                            snapshot.user_data_size);
                ++flat_reports;
            }
        }
        const auto* live = reinterpret_cast<const AmdGpu::Regs*>(in);
        in += sizeof(AmdGpu::Regs);
        static u32 reports = 0;
        for (u32 block = 0; block < AmdGpu::RegDirty::NumBlocks && reports < 32; ++block) {
            const u32 at = block * AmdGpu::RegDirty::BlockWords;
            if (std::memcmp(regs.reg_array.data() + at, live->reg_array.data() + at,
                            AmdGpu::RegDirty::BlockWords * sizeof(u32)) != 0) {
                for (u32 w = at; w < at + AmdGpu::RegDirty::BlockWords; ++w) {
                    if (regs.reg_array[w] != live->reg_array[w]) {
                        std::printf("Draw pipe: register copy differs at word %#x (%#x vs %#x)\n",
                                    w, regs.reg_array[w], live->reg_array[w]);
                        ++reports;
                        break;
                    }
                }
            }
        }
    }
    ASSERT(static_cast<u32>(in - data) == size);
    stage_regs = &regs;
    dc.pipe_cb_extent = packet.cb_extent;
    dc.pipe_db_extent = packet.db_extent;
    if (packet.kind == PacketKind::Special) {
        // A draw FilterDraw handles (fast clear elimination, resolve, depth copy, skip).
        FrameCapture::Poll();
        self.scheduler.PopPendingOperations();
        self.FilterDraw();
    } else if (cs) {
        stage_cs = cs;
        const auto* pipeline = static_cast<const ComputePipeline*>(packet.pipeline);
        if (indirect) {
            self.DispatchIndirectRecord(pipeline, indirect->args, indirect->stride);
        } else {
            self.DispatchRecord(pipeline);
        }
        stage_cs = nullptr;
    } else if (indirect) {
        self.DrawIndirectRecord(static_cast<const GraphicsPipeline*>(packet.pipeline),
                                packet.is_indexed, *indirect);
    } else {
        SwapGxRegisters(regs, gx_swapped.data(), gx_count);
        self.DrawRecord(static_cast<const GraphicsPipeline*>(packet.pipeline), packet.prepared,
                        packet.is_indexed, packet.index_offset);
        SwapGxRegisters(regs, gx_swapped.data(), gx_count);
    }
    Shader::Info::num_ud_snapshots = 0;
    dc.num_ring_stages = 0;
#ifdef BB_TEST_SHARED_POST_GRAPH
    dc.ring_packet_end = 0;
#endif
    if (Object3::On()) Object3::packet = {};
    dc.wall_stream_packet = dc.wall_stream_reason = 0;
    dc.packet_vsharps = {};
    dc.packet_vkeys = {};
    dc.packet_view_keys = {};
    dc.packet_index_key = 0;
    if (self.constant_ring) {
        self.constant_ring->Stamp(packet.ring_end);
    }
}

// bbport BB_DRAWREC_WORKERS (docs/parallel-stageb.md): the lookahead thread. Stage B's per-packet
// time is spread over cache misses on the structures a draw consults first (the texture set memo
// slot and its images, the page tracking words and the arena table of each buffer range). This
// thread walks the committed packets a few ahead of stage B and issues prefetches for exactly
// those lines, so that stage B finds them in the shared L3 (or in this core's cache) instead of
// memory. It changes no state and reads only: the packets (committed, below Published, not yet
// overwritten by stage A), their prepared draws (kept alive until stage B passes the packet) and
// the shader infos; every other address is computed and prefetched, never read. A packet stage B
// already passed may point at freed prepared data: that read is covered by the loader's fault
// recovery (BB_RECOVER_SET) and counted.
bool Rasterizer::LookaheadWanted() {
    static const bool wanted = [] {
        // bbport: on by default on CPUs with 8 or more hardware threads (it takes a core of its
        // own while stage B is busy); BB_DRAWREC_WORKERS=0 turns it off, =1 forces it on.
        const char* env = std::getenv("BB_DRAWREC_WORKERS");
        if (env && env[0]) {
            return env[0] != '0';
        }
        return std::thread::hardware_concurrency() >= 8;
    }();
    return wanted;
}

u32 Rasterizer::LookaheadWindow() {
    static const u32 window = [] {
        const char* env = std::getenv("BB_DRAWREC_LOOKAHEAD");
        const long value = env && env[0] ? std::strtol(env, nullptr, 10) : 8;
        return static_cast<u32>(std::clamp<long>(value, 1, 256));
    }();
    return window;
}

void Rasterizer::LookaheadLoop(std::stop_token stop) {
    Common::SetCurrentThreadName("bb:DrawAhead");
    if (const char* env = std::getenv("BB_DRAWREC_IDLE"); env && env[0] == '1') {
        BbThreads::MakeBackground(); // only idle cores; starved on a busy CPU
    }
    const u32 window = LookaheadWindow();
    u64 at = 0;       // ring position of the next packet to prefetch for
    u64 number = 0;   // its number in stage B's count (ConsumedPackets)
    bool synced = false;
    while (!stop.stop_requested()) {
        if (BbToggle::Experiment(16)) {
            // Paused for an A/B while the game runs: it follows stage B again when resumed.
            synced = false;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        const u64 consumed = draw_pipe->Consumed();
        if (!synced || at < consumed) {
            if (synced) {
                BbStats::lookahead_behind.fetch_add(1, std::memory_order_relaxed);
            }
            at = consumed;
            number = draw_pipe->ConsumedPackets();
            synced = true;
        }
        if (number > draw_pipe->ConsumedPackets() + window) {
            // Far enough ahead: lines fetched now would be gone before stage B gets there.
            BbStats::lookahead_waits.fetch_add(1, std::memory_order_relaxed);
            const auto until = std::chrono::steady_clock::now() + std::chrono::microseconds(100);
            // bbport (BB_LOOKAHEAD_SLEEP=0: yields to the end, as before): stage B stuck on one
            // long packet (a compile, a wait for the GPU or for host copies) kept this thread
            // yielding on a core of its own; after 1 ms it sleeps in short steps (a prefetcher:
            // late, it only syncs to stage B again).
            static const bool sleep_on = GpuSavings::EnvOn("BB_LOOKAHEAD_SLEEP");
            const auto sleep_after = until + std::chrono::microseconds(900);
            for (u32 spins = 1; number > draw_pipe->ConsumedPackets() + window; ++spins) {
                if (stop.stop_requested()) {
                    return;
                }
                __builtin_ia32_pause();
                if (!(spins & 255)) {
                    const auto now = std::chrono::steady_clock::now();
                    if (sleep_on && now >= sleep_after) {
                        GpuSavings::Get().lookahead_sleeps.fetch_add(1, std::memory_order_relaxed);
                        std::this_thread::sleep_for(std::chrono::microseconds(250));
                    } else if (now >= until) {
                        std::this_thread::yield();
                    }
                }
            }
            continue;
        }
        if (at >= draw_pipe->Published()) {
            draw_pipe->WaitForCommit(at, stop);
            continue;
        }
        u32 payload = 0;
        u64 next = at;
        if (const u8* data = draw_pipe->PacketAt(at, payload, next)) {
            const u64 start = __rdtsc();
            const bool draw = PrefetchPacket(data, payload);
            BbStats::lookahead_busy_cycles.fetch_add(__rdtsc() - start, std::memory_order_relaxed);
            BbStats::lookahead_packets.fetch_add(1, std::memory_order_relaxed);
            if (draw) {
                BbStats::lookahead_draws.fetch_add(1, std::memory_order_relaxed);
                const u64 run = draw_pipe->ConsumedPackets();
                BbStats::lookahead_lead.fetch_add(number > run ? number - run : 0,
                                                  std::memory_order_relaxed);
            }
            ++number;
        }
        at = next;
    }
}

bool Rasterizer::PrefetchPacket(const u8* data, u32 size) {
    if (*reinterpret_cast<const PacketKind*>(data) != PacketKind::Draw) {
        return false; // tasks, dispatches, indirect and special draws bind without prepared sharps
    }
    // A packet stage B passed meanwhile may point at a retired submission's prepared draws:
    // a fault there only ends this packet's prefetch.
    BbRecoverBuf recover;
    if (BB_RECOVER_SET(recover)) {
        runtime_fault_recover = nullptr;
        BbStats::lookahead_recovered.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
    runtime_fault_recover = &recover;
    const u32 lines = PrefetchDraw(data, size);
    runtime_fault_recover = nullptr;
    BbStats::lookahead_lines.fetch_add(lines, std::memory_order_relaxed);
    return lines != 0;
}

u32 Rasterizer::PrefetchDraw(const u8* data, u32 size) {
    const auto& packet = *reinterpret_cast<const DrawPacket*>(data);
    if (!packet.prepared || !packet.pipeline || packet.num_stages > Shader::Info::MaxUdSnapshots) {
        return 0;
    }
    u32 lines = 0;
    const auto touch = [&lines](const void* address, std::size_t bytes) {
        const auto* p = static_cast<const char*>(address);
        for (std::size_t offset = 0; offset < bytes; offset += 64) {
            __builtin_prefetch(p + offset);
            ++lines;
        }
    };
    // The layout of PostDraw: register blocks, then per stage its header, ring bindings and
    // user data, then (a direct draw) the vertex stream V#s.
    const u8* in = data + sizeof(DrawPacket);
    in += AlignPacket(packet.num_blocks * sizeof(u16));
    in += packet.num_blocks * AmdGpu::RegDirty::BlockWords * sizeof(u32);
    const PreparedDraw& prepared = *packet.prepared;
    for (u32 s = 0; s < packet.num_stages; ++s) {
        if (in + sizeof(PacketStage) > data + size) {
            return lines;
        }
        const auto& stage = *reinterpret_cast<const PacketStage*>(in);
        in += sizeof(PacketStage);
        const auto* rings = reinterpret_cast<const RingBinding*>(in);
        in += stage.num_ring * sizeof(RingBinding);
        in += AlignPacket((stage.ud_size + stage.flat_size) * sizeof(u32));
        if (!stage.info) {
            continue;
        }
        const Shader::Info& info = *stage.info;
        const PreparedStage* ps = FindPreparedStage(&prepared, info);
        if (!ps) {
            continue;
        }
        // Textures: the memoized set's slot (BindTexturesFromSet), then its images; a slot with
        // another key means the full lookup, which starts at the description cache's two ways.
        const u32 count = static_cast<u32>(info.images.size());
        if (count != 0 && count <= TextureSet::MaxImages && ps->image_hashes) {
            bool plain = true;
            for (const auto& image : info.images) {
                plain &= !image.is_written &&
                         image.mip_fallback_mode == Shader::MipStorageFallbackMode::None;
            }
            if (plain) {
                const bool point_native = scene_targets->Reduced() && PointReadsNative(info, ps);
                const u64 key = XXH3_64bits_withSeed(ps->image_hashes, count * sizeof(u64),
                                                     reinterpret_cast<u64>(&info) ^
                                                         (point_native ? 2 : 0)) |
                                1;
                const TextureSet& set = texture_sets[key % texture_sets.size()];
                touch(&set, static_cast<std::size_t>(
                                 reinterpret_cast<const char*>(set.entries.data()) -
                                 reinterpret_cast<const char*>(&set)));
                if (__atomic_load_n(&set.key, __ATOMIC_RELAXED) == key) {
                    touch(set.entries.data(), count * sizeof(TextureSetEntry));
                    for (u32 i = 0; i < count; ++i) {
                        VideoCore::ImageId id{__atomic_load_n(&set.entries[i].id.index,
                                                              __ATOMIC_RELAXED)};
                        if (id) {
                            if (const void* image = texture_cache.ImageSlotAddress(id)) {
                                touch(image, 192); // flags, binding, backing, ticks
                            }
                        }
                    }
                } else {
                    for (u32 i = 0; i < count; ++i) {
                        const u64 hash = ps->image_hashes[i];
                        const auto* ways = &image_desc_cache[(hash % (image_desc_cache.size() / 2)) * 2];
                        touch(ways, 64);
                        touch(ways + 1, 64);
                    }
                }
            }
        }
        // Buffers bound through the cache (BindBuffers): the arena table and the page state.
        if (ps->buffer_sharps) {
            for (u32 i = 0; i < info.buffers.size() && i < ps->num_buffers; ++i) {
                if (info.buffers[i].IsSpecial()) {
                    continue;
                }
                bool ring_bound = false;
                for (u32 r = 0; r < stage.num_ring; ++r) {
                    ring_bound |= rings[r].index == i;
                }
                if (ring_bound) {
                    continue; // copied into the constant ring by stage A: no cache lookup
                }
                const auto& vsharp = ps->buffer_sharps[i];
                if (vsharp.base_address != 0 && vsharp.GetSize() != 0) {
                    lines += buffer_cache.PrefetchBinding(vsharp.base_address, vsharp.GetSize());
                }
            }
        }
    }
    // The vertex streams (ResolveVertexBuffers obtains their merged ranges).
    if (in + packet.num_vsharps * sizeof(AmdGpu::Buffer) <= data + size) {
        const auto* vsharps = reinterpret_cast<const AmdGpu::Buffer*>(in);
        for (u32 i = 0; i < packet.num_vsharps; ++i) {
            if (vsharps[i].base_address != 0 && vsharps[i].GetSize() != 0) {
                lines += buffer_cache.PrefetchBinding(vsharps[i].base_address, vsharps[i].GetSize());
            }
        }
    }
    return lines;
}

void Rasterizer::PrintPipeStats() {
    static const bool stats = std::getenv("BB_FRAME_STATS") != nullptr;
    if (!stats || (draw_pipe->packets & 1023) != 0) {
        return;
    }
    static auto window = std::chrono::steady_clock::now();
    static u64 last_packets = 0, last_drains = 0, last_drain_cycles = 0, last_busy = 0;
    static u64 last_tsc = __rdtsc();
    const auto now = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(now - window).count();
    if (seconds < 5.0) {
        return;
    }
    // bbport (r23_spike-trace): this report's time on stage A
    struct R23Report {
        u64 start = BbSpike::on ? BbSpike::NowNs() : 0;
        ~R23Report() {
            if (start != 0) {
                BbSpike::stage_a_print_ns.fetch_add(BbSpike::NowNs() - start,
                                                    std::memory_order_relaxed);
            }
        }
    } r23_report;
    const u64 tsc = __rdtsc();
    const double cycles = double(tsc - last_tsc);
    const u64 busy = draw_pipe->busy_cycles.load(std::memory_order_relaxed);
    static u64 last_sleeps = 0;
    std::printf("Draw pipe: %.0f draws/s pipelined, %.0f drains/s that waited (%.1f/s slept), "
                "stage A waited %.1f%%, stage B busy %.1f%%\n",
                (draw_pipe->packets - last_packets) / seconds,
                (draw_pipe->drains - last_drains) / seconds,
                (draw_pipe->sleeps - last_sleeps) / seconds,
                100.0 * (draw_pipe->drain_cycles - last_drain_cycles) / cycles,
                100.0 * (busy - last_busy) / cycles);
    last_sleeps = draw_pipe->sleeps;
    std::printf("  drains by reason/s:");
    for (u32 r = 0; r < DrawPipe::NumReasons; ++r) {
        if (const u64 n = draw_pipe->drains_by_reason[r]) {
            static constexpr const char* names[] = {"ConstRam", "commands", "compute",
                                                    "submission end", "draw", "rasterizer"};
            const double share = 100.0 * draw_pipe->cycles_by_reason[r] / cycles;
            draw_pipe->cycles_by_reason[r] = 0;
            if (r < 256) {
                std::printf(" %s=%.0f (%.1f%%)",
                            magic_enum::enum_name(AmdGpu::PM4ItOpcode(r)).data(), n / seconds,
                            share);
            } else {
                std::printf(" %s=%.0f (%.1f%%)", names[r - 256], n / seconds, share);
            }
        }
    }
    if (constram_waits_skipped) {
        std::printf(" ConstRam not waited=%.0f", constram_waits_skipped / seconds);
        constram_waits_skipped = 0;
    }
    if (BbSections::Enabled()) {
        static std::array<u64, BbSections::Count> last_sections{};
        const double packets = double(draw_pipe->packets - last_packets);
        const double tsc_hz = cycles / seconds;
        std::printf("\n  stage B us per packet:");
        for (u32 s = 0; s < BbSections::Count; ++s) {
            const u64 now_cycles = BbSections::cycles[s].load(std::memory_order_relaxed);
            if (packets > 0) {
                std::printf(" %s %.2f", BbSections::Names[s],
                            1e6 * double(now_cycles - last_sections[s]) / tsc_hz / packets);
            }
            last_sections[s] = now_cycles;
        }
        static std::array<u64, 6> last_paths{};
        if (packets > 0) {
            const auto& paths = VideoCore::BufferCache::obtain_paths;
            const auto per = [&](u32 i) { return double(paths[i] - last_paths[i]) / packets; };
            std::printf("\n  stage B buffers per packet: in place %.2f read %.2f written, stream %.2f, "
                        "VRAM %.2f read %.2f written, %.3f with uploads",
                        per(0), per(1), per(2), per(3), per(4), per(5));
            last_paths = paths;
        }
        static std::array<u64, BbSections::ACount> last_a{};
        static u64 last_a_draws = 0;
        const u64 a_draws = BbSections::a_draws.load(std::memory_order_relaxed);
        if (a_draws > last_a_draws) {
            std::printf("\n  stage A us per draw:");
            for (u32 s = 0; s < BbSections::ACount; ++s) {
                const u64 now_cycles = BbSections::a_cycles[s].load(std::memory_order_relaxed);
                std::printf(" %s %.2f", BbSections::ANames[s],
                            1e6 * double(now_cycles - last_a[s]) / tsc_hz /
                                double(a_draws - last_a_draws));
                last_a[s] = now_cycles;
            }
        }
        last_a_draws = a_draws;
        // bbport: the slow paths by shader (program hash): total ms in this window, calls, per call.
        const auto print_top = [&](const char* title, BbSections::ByKey& table) {
            std::printf("\n  %s:", title);
            table.Top(8, [&](const BbSections::ByKey::Entry& e) {
                const double ms = 1e3 * double(e.cycles) / tsc_hz;
                std::printf(" [%016llx %.1f ms %llu x %.1f us]",
                            static_cast<unsigned long long>(e.key & ~1ull), ms,
                            static_cast<unsigned long long>(e.calls), 1e3 * ms / double(e.calls));
            });
        };
        print_top("full texture lookups by shader", BbSections::tex_full_by_shader);
        print_top("dispatches by shader", BbSections::dispatch_by_shader);
        // Racy reads of stage B's counters: diagnostics only.
        std::printf("\n  stage B tasks (us per frame-second, count/s):");
        static std::array<u64, TaskKinds> last_task_cycles{}, last_task_counts{};
        for (std::size_t k = 0; k < TaskKinds && task_kinds[k]; ++k) {
            char name[96];
            if (const char* known = TaskName(task_kinds[k])) {
                std::snprintf(name, sizeof(name), "%s", known);
            } else {
#ifdef _WIN32
                BbPlatform::DescribeAddress(task_kinds[k], name, sizeof(name));
#else
                Dl_info info{};
                dladdr(task_kinds[k], &info);
                std::snprintf(name, sizeof(name), "+0x%llx",
                              (unsigned long long)(reinterpret_cast<u64>(task_kinds[k]) -
                                                   reinterpret_cast<u64>(info.dli_fbase)));
#endif
            }
            const u64 c = task_cycles[k], n = task_counts[k];
            std::printf(" [%s %.0f us/s %.0f/s]", name,
                        1e6 * double(c - last_task_cycles[k]) / tsc_hz / seconds,
                        double(n - last_task_counts[k]) / seconds);
            last_task_cycles[k] = c;
            last_task_counts[k] = n;
        }
    }
    std::printf("\n  fences handed over with the next one: %.0f/s",
                double(merged_fence_kicks.exchange(0, std::memory_order_relaxed)) / seconds);
    std::printf("\n  stage A waits over 0.5%%:");
    for (const auto& [function, lines] : drain_sites) {
        for (const auto& [line, waited] : lines) {
            if (waited * 200 > cycles) {
                std::printf(" %s:%u %.1f%%", function, line, 100.0 * waited / cycles);
            }
        }
    }
    std::printf("\n");
    if (lookahead_thread.joinable()) {
        // bbport: the lookahead thread (BB_DRAWREC_WORKERS); counters since the last window.
        const auto take = [](std::atomic<u64>& counter) {
            return double(counter.exchange(0, std::memory_order_relaxed));
        };
        const double walked = take(BbStats::lookahead_packets);
        const double draws = take(BbStats::lookahead_draws);
        const double lines = take(BbStats::lookahead_lines);
        const double lead = take(BbStats::lookahead_lead);
        const double busy = take(BbStats::lookahead_busy_cycles);
        std::printf("  lookahead: %.0f packets/s walked, %.0f draws/s prefetched, %.0f lines/draw, "
                    "%.1f packets ahead, behind stage B %.1f/s, waited for it %.0f/s, busy %.1f%%, "
                    "%.0f faults recovered\n",
                    walked / seconds, draws / seconds, draws > 0 ? lines / draws : 0.0,
                    draws > 0 ? lead / draws : 0.0, take(BbStats::lookahead_behind) / seconds,
                    take(BbStats::lookahead_waits) / seconds, 100.0 * busy / cycles,
                    take(BbStats::lookahead_recovered));
    }
    drain_sites.clear();
    draw_pipe->drains_by_reason = {};
    window = now;
    last_tsc = tsc;
    last_packets = draw_pipe->packets;
    last_drains = draw_pipe->drains;
    last_drain_cycles = draw_pipe->drain_cycles;
    last_busy = busy;
}

bool Rasterizer::FilterDrawPasses() const {
    // FilterDraw's checks without its side effects: false when it would skip the draw or run
    // a pass of its own (fast clear elimination, resolve, depth/stencil copy).
    const auto& regs = Regs();
    using Mode = AmdGpu::ColorControl::OperationMode;
    const auto mode = regs.color_control.mode;
    if (mode == Mode::EliminateFastClear || mode == Mode::FmaskDecompress ||
        mode == Mode::Resolve || regs.primitive_type == AmdGpu::PrimitiveType::None) {
        return false;
    }
    const bool depth_copy =
        regs.depth_render_override.force_z_dirty && regs.depth_render_override.force_z_valid &&
        regs.depth_buffer.DepthValid() && regs.depth_buffer.DepthWriteValid() &&
        regs.depth_buffer.DepthAddress() != regs.depth_buffer.DepthWriteAddress();
    const bool stencil_copy =
        regs.depth_render_override.force_stencil_dirty &&
        regs.depth_render_override.force_stencil_valid && regs.depth_buffer.StencilValid() &&
        regs.depth_buffer.StencilWriteValid() &&
        regs.depth_buffer.StencilAddress() != regs.depth_buffer.StencilWriteAddress();
    return !(mode == Mode::Disable && (depth_copy || stencil_copy));
}

void Rasterizer::Draw(bool is_indexed, u32 index_offset, const PreparedDraw* prepared,
                      u64 gx_record) {
    RENDERER_TRACE;
    BbSections::ScopeA draw_scope{BbSections::ADraw};
    if (BbSections::Enabled()) {
        BbSections::a_draws.fetch_add(1, std::memory_order_relaxed);
    }
    BbStats::draws.fetch_add(1, std::memory_order_relaxed);
    if (occlusion) {
        occlusion->NoteIssued(); // before anything may drop the draw (vk_occlusion.h)
    }
    // bbport debugging: BB_IMAGE_DUMP_TRIGGER=<file> holding hex guest addresses, one per line;
    // the images registered there are written to BB_CAPTURE_DIR (TextureCache::DumpImagesAt).
    if (static const char* trigger = std::getenv("BB_IMAGE_DUMP_TRIGGER"); trigger) {
        static u32 polls = 0;
        if ((++polls & 1023) == 0 && std::filesystem::exists(trigger)) {
            std::vector<VAddr> addresses;
            if (FILE* f = std::fopen(trigger, "r")) {
                unsigned long long address;
                while (std::fscanf(f, "%llx", &address) == 1) {
                    addresses.push_back(address);
                }
                std::fclose(f);
            }
            std::error_code ec;
            std::filesystem::remove(trigger, ec);
            DrainDrawPipe(DrawPipe::ReasonDraw);
            const char* dir = std::getenv("BB_CAPTURE_DIR");
            for (const VAddr address : addresses) {
                texture_cache.DumpImagesAt(address, dir ? dir : ".");
            }
        }
    }

    // bbport: with the draw pipeline this thread only selects the pipeline and hands the draw
    // to the recording thread (DrawRecord there); draws FilterDraw handles itself run here.
    const bool pipelined = UseDrawPipe();
    if (pipelined && !FilterDrawPasses() &&
        !BbToggle::Disabled(BbToggle::PipelinedMemoryWrites)) {
        PostDraw(nullptr, nullptr, false, 0);
        return;
    }
    if (!pipelined || !FilterDrawPasses()) {
        DrainDrawPipe(DrawPipe::ReasonDraw);
        FrameCapture::Poll();
        scheduler.PopPendingOperations();
        if (!FilterDraw()) {
            return;
        }
    }
    const u32 srt_faults = Shader::Info::srt_walk_faults;
    BbSections::ScopeA pipeline_scope{BbSections::APipeline};
    const GraphicsPipeline* pipeline = pipeline_cache.GetGraphicsPipeline({}, prepared, gx_record);
    pipeline_scope.End();
    const PreparedDraw* used_prepared = pipeline_cache.UsedPrepared();
    if (prepared) {
        draw_prep->Count(pipeline != nullptr &&
                         prepared->state.load(std::memory_order_acquire) == PreparedDraw::Ready &&
                         prepared->reg_checksum == liverpool->gfx_reg_checksum);
    }
    if (!pipeline || Shader::Info::srt_walk_faults != srt_faults) {
        return;
    }
    num_gx_registers = 0;
    gx_state = nullptr;
    if (gx_record && (BbEngine::GxRecords::Compared() || BbEngine::GxRecords::Used())) {
        BbSections::ScopeA record_scope{BbSections::ARecord};
        ApplyGxRecord(pipeline, used_prepared, gx_record, is_indexed);
    }
    if (foliage_collect.load(std::memory_order_relaxed) && !num_gx_registers && !gx_state) {
        pipeline_cache.PrepareFoliageVariant(*pipeline);
    } else if (num_gx_registers || gx_state) {
        pipeline_cache.NoteFoliageNotRequested(*pipeline);
    }
    if (pipelined && FilterDrawPasses()) {
        PostDraw(pipeline, used_prepared, is_indexed, index_offset);
        num_gx_registers = 0;
        gx_state = nullptr;
        return;
    }
    const u32 gx_count = num_gx_registers;
    num_gx_registers = 0;
    gx_state = nullptr;
    SwapGxRegisters(liverpool->regs, gx_registers.data(), gx_count);
    DrawRecord(pipeline, used_prepared, is_indexed, index_offset);
    SwapGxRegisters(liverpool->regs, gx_registers.data(), gx_count);
}

void Rasterizer::SwapGxRegisters(AmdGpu::Regs& regs, GxRegister* list, u32 count) {
    for (u32 i = 0; i < count; ++i) {
        std::swap(regs.reg_array[AmdGpu::Regs::ContextRegWordOffset + list[i].index], list[i].value);
    }
}

void Rasterizer::ApplyGxRecord(const GraphicsPipeline* pipeline, const PreparedDraw*& used_prepared,
                               u64 gx_record, bool is_indexed_draw) {
    namespace Gx = BbEngine::GxBindings;
    static_assert(sizeof(Gx::Entry) == sizeof(Shader::Native::TablePlan::Entry));
    const auto& regs = liverpool->regs;
    static const bool layout = [&] {
        const auto at = [&](const void* field) {
            return u32(reinterpret_cast<const u32*>(field) - regs.reg_array.data()) -
                   AmdGpu::Regs::ContextRegWordOffset;
        };
        const bool same =
            at(&regs.color_target_mask) == 0x8e && at(&regs.blend_control[0]) == 0x1e0 &&
            at(&regs.blend_constants) == 0x105 && at(&regs.depth_control) == 0x200 &&
            at(&regs.stencil_control) == 0x10b && at(&regs.stencil_ref_front) == 0x10c &&
            at(&regs.stencil_ref_back) == 0x10d && at(&regs.clipper_control) == 0x204 &&
            at(&regs.polygon_control) == 0x205 && at(&regs.viewports[0]) == 0x10f &&
            at(&regs.viewport_depths[0]) == 0xb4 && at(&regs.viewport_scissors[0]) == 0x94 &&
            at(&regs.color_buffers[0]) == 0x318 && at(&regs.depth_buffer) == 0x10;
        if (!same) {
            std::printf("GX records: the register layout is not GX's; render state stays with the registers\n");
        }
        return same;
    }();
    constexpr Shader::SwStage kStages[Gx::kStages] = {Shader::SwStage::Vertex,
                                                      Shader::SwStage::Fragment};
    const u32 unfilled = pipeline_cache.GxUnfilled();
    const auto refresh = [&](u32 s) {
        if ((unfilled >> s) & 1) {
            const_cast<Shader::Info*>(pipeline->GetStages()[u32(kStages[s])])->RefreshFlatBuf();
        }
    };
    const Gx::State* state = BbEngine::GxRecords::Taken(gx_record);
    if (!state) {
        refresh(0);
        refresh(1);
        BbEngine::GxRecords::NoteDraw(Gx::NoState, 0, false);
        return;
    }
    const bool compare = BbEngine::GxRecords::Compared();
    struct FillOp {
        u16 flat;
        u8 dynamic;
        Gx::Fill fill;
        u32 offset;
    };
    struct FillPlan {
        const Shader::Info* info = nullptr;
        u64 shader = 0;
        u64 inputs_hash = 0;
        u32 size = 0;
        std::vector<FillOp> ops;
        Gx::Reason reason = Gx::Covered;
    };
    thread_local std::unordered_map<u64, FillPlan> plans;
    thread_local std::vector<Gx::Fill> fills;
    thread_local std::vector<u32> scratch;
    Gx::Reason bindings = Gx::Covered;
    for (u32 s = 0; s < Gx::kStages; ++s) {
        const auto* info = pipeline->GetStages()[u32(kStages[s])];
        if (!info || (!compare && !((unfilled >> s) & 1))) {
            continue;
        }
        const Gx::Stage& stage = state->stages[s];
        auto& flat = const_cast<Shader::Info*>(info)->flattened_ud_buf;
        const auto& table_plan = info->table_plan;
        const u32 size = u32(flat.size());
        if (plans.size() > 8192) {
            plans.clear();
        }
        FillPlan& plan = plans[reinterpret_cast<u64>(info) * 0x9E3779B97F4A7C15ull ^ stage.shader];
        if (plan.info != info || plan.shader != stage.shader || plan.inputs_hash != stage.inputs_hash ||
            plan.size != size) {
            plan.info = info;
            plan.shader = stage.shader;
            plan.inputs_hash = stage.inputs_hash;
            plan.size = size;
            plan.ops.clear();
            fills.assign(size, Gx::Fill{});
            const Gx::Plan entries{reinterpret_cast<const Gx::Entry*>(table_plan.entries.data()),
                                   u32(table_plan.entries.size()), table_plan.valid};
            plan.reason = size > 0xffff ? Gx::Outside : Gx::Prepare(stage, entries, size, fills.data());
            for (u32 f = 0; f < size && plan.reason == Gx::Covered; ++f) {
                if (fills[f].from == Gx::FromNone) {
                    continue;
                }
                const bool table = f >= Shader::Native::TablePlan::FirstFlat;
                const auto* entry = table ? &table_plan.entries[f - Shader::Native::TablePlan::FirstFlat] : nullptr;
                plan.ops.push_back({u16(f), u8(entry && entry->expr_len), fills[f], entry ? entry->offset : 0});
            }
        }
        Gx::Reason reason = state->reason != Gx::Covered ? static_cast<Gx::Reason>(state->reason) : plan.reason;
        u32* out = flat.data();
        if (compare && reason == Gx::Covered) {
            scratch.assign(flat.begin(), flat.end());
            out = scratch.data();
        }
        for (const FillOp& op : plan.ops) {
            if (reason != Gx::Covered) {
                break;
            }
            const u32 offset =
                op.dynamic ? table_plan.Offset(table_plan.entries[op.flat - Shader::Native::TablePlan::FirstFlat], out)
                           : op.offset;
            reason = Gx::Value(*state, s, op.fill, offset, out[op.flat]);
        }
        if (reason != Gx::Covered) {
            bindings = bindings == Gx::Covered ? reason : bindings;
            if (!compare) {
                refresh(s);
            }
            continue;
        }
        if (compare) {
            for (const FillOp& op : plan.ops) {
                BbEngine::GxRecords::NoteWord(s, op.flat, out[op.flat], flat[op.flat], info->pgm_hash);
            }
        }
    }
    if (!compare && !BbEngine::GxRecords::Intact()) {
        for (u32 s = 0; s < Gx::kStages; ++s) {
            if (const auto* info = pipeline->GetStages()[u32(kStages[s])]) {
                const_cast<Shader::Info*>(info)->RefreshFlatBuf();
            }
        }
        BbEngine::GxRecords::NoteDraw(Gx::NoState, 0, false);
        return;
    }
    if (unfilled) {
        used_prepared = nullptr;
    }
    std::array<Gx::Register, Gx::kMaxRegisters> list;
    thread_local u64 last_render = 0;
    thread_local bool last_clean = false;
    const bool unchanged = !compare && last_clean && state->render.hash == last_render;
    const u32 count = layout && !unchanged ? Gx::Registers(state->render, list.data()) : 0;
    gx_state = state;
    if (state->render.index_known && is_indexed_draw) {
        BbEngine::GxRecords::NoteTarget(-2, state->render.index_base, regs.index_base_address.Address());
    }
    u32 differing = 0;
    for (u32 i = 0; i < count; ++i) {
        const u32 old = regs.reg_array[AmdGpu::Regs::ContextRegWordOffset + list[i].index];
        BbEngine::GxRecords::NoteRegister(list[i].index, list[i].value, old);
        if (!compare && old != list[i].value && differing < gx_registers.size()) {
            gx_registers[differing++] = {list[i].index, list[i].value};
        }
    }
    if (compare) {
        for (u32 i = 0; i < AmdGpu::NUM_COLOR_BUFFERS && i < 8; ++i) {
            if (state->render.color[i]) {
                BbEngine::GxRecords::NoteTarget(int(i), state->render.color[i],
                                                regs.color_buffers[i].Address());
            }
        }
        if (state->render.depth) {
            BbEngine::GxRecords::NoteTarget(-1, state->render.depth, regs.depth_buffer.DepthAddress());
        }
    } else {
        num_gx_registers = differing;
    }
    if (count) {
        last_render = state->render.hash;
        last_clean = differing == 0;
    }
    BbEngine::GxRecords::NoteDraw(bindings, 0, layout);
}

// BB_PROXY_TRACE (defined with BindTextures).
static bool ProxyTraceOn();
static void FlushProxyReads(bool reduced, const VideoCore::Image* target);

bool Rasterizer::LampMaterialSample(LampPaneProbe& p, const RenderState& state,
                                    const LampMaterialDelivery& draw, bool after) {
    using namespace RtLampPane;
    const std::array pixels{RawDrawPixel{p.samples[0].x, p.samples[0].y},
                            RawDrawPixel{p.samples[1].x, p.samples[1].y}};
    DrawRawRead read{p.material, p.capture, p.camera, p.jitter, pixels, p.buffer,
                     [&] { return p.Allocate(instance.GetAllocator(), scheduler); }, p.WorldBytes(),
                     p.width, p.height, p.ordinal, p.first_index, p.base_vertex, p.first_instance,
                     0x6a833138, 0xbb10e440, DrawIndices, Instances};
    if (p.lineage) {
        read.lineage = &*p.lineage;
        read.lineage_offset = p.LineageOffset();
    }
    const bool sampled = SampleDrawRaw(read, state, draw, after);
    if (sampled && p.reconstruction) {
        auto& r = *p.reconstruction;
        const auto& dynamic = scheduler.GetDynamicState();
        if (dynamic.viewports.size() != 1 || dynamic.scissors.size() != 1) {
            r.refusal = "effective viewport or scissor count is not one";
            return sampled;
        }
        const auto& v = dynamic.viewports.front();
        const std::array viewport{v.x, v.y, v.width, v.height, v.minDepth, v.maxDepth};
        const auto& scissor = dynamic.scissors.front();
        const auto jitter = Dc().draw_jitter;
        // SampleDrawRaw accepted this delivery. Its raster pipeline issued the sampled draw.
        const auto& key = draw.raster->GetGraphicsKey();
        const u64 vertex_stage = key.stage_hashes[u32(Shader::SwStage::Vertex)];
        if (!after) {
            r.vertex_stage_key = vertex_stage;
            r.raster_motion_flags = key.motion_vectors;
            r.viewport = viewport;
            r.scissor = scissor;
            r.jitter = jitter;
            r.viewport_before = true;
        } else if (r.viewport_before && r.viewport == viewport && r.scissor == scissor &&
                   r.jitter == jitter) {
            r.viewport_after = true;
            r.raster_key_matched = r.vertex_stage_key == vertex_stage &&
                                   r.raster_motion_flags == key.motion_vectors;
        } else {
            r.refusal = "effective viewport, scissor or jitter changed between phases";
        }
    }
    return sampled;
}

bool Rasterizer::SampleDrawRaw(DrawRawRead& p, const RenderState& state,
                               const LampMaterialDelivery& draw, bool after) {
    using namespace RtLampPane;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    auto& material = p.material;
    const auto unknown = [&](const char* reason) {
        material.refusal = reason;
        return false;
    };
    if (material.refusal) {
        return false;
    }
    const auto phase = after ? MaterialPhase::After : MaterialPhase::Before;
    if (!material.phases.MayRecord(phase, p.capture) || !draw.indexed ||
        object_motion->Frame() != p.capture.scene || p.ordinal != p.capture.draw ||
        draw.first != p.first_index || draw.base != p.base_vertex || draw.first_instance != p.first_instance) {
        return unknown("draw delivery or A/B phase identity mismatch");
    }
    const auto* ps = draw.original->GetStages()[u32(Shader::SwStage::Fragment)];
    const auto& regs = Regs();
    const u64 vs = draw.original->GetStage(Shader::SwStage::Vertex).pgm_hash;
    if (!ps || (vs != p.vs || ps->pgm_hash != p.ps || regs.num_indices != p.indices ||
               regs.num_instances.NumInstances() != p.instances) ||
        !draw.handle || (after && material.delivery != draw)) {
        return unknown("exact ready raster specialization unavailable");
    }
    if (scene_targets->Reduced() || attachment_feedback_loop || !scheduler.IsRenderingWith(state) ||
        state.num_layers != 1 || state.num_color_attachments < 4 || !state.depth_stencil_attachment.has_depth ||
        p.width > state.width || p.height > state.height || Dc().draw_jitter != p.jitter ||
        !regs.depth_control.depth_enable || !regs.depth_control.depth_write_enable) {
        return unknown("alias-unproven: unsupported render scope or depth state");
    }
    const auto& key = draw.raster->GetGraphicsKey();
    const auto scissor = DrawScissor(0);
    const auto matrices = camera_motion->PassMatrices();
    if (!matrices.valid || !(Camera{matrices.view, matrices.inv_view, matrices.proj} == p.camera)) {
        return unknown("draw-local camera changed");
    }
    std::array<u32, 3> masks{}, blend{};
    for (u32 i = 0; i < masks.size(); ++i) {
        const u32 target = i + 1;
        masks[i] = u32(VkColorComponentFlags(key.HostWriteMask(target)));
        blend[i] = std::bit_cast<u32>(key.blend_controls[target]);
        if (p.albedo_depth_only && target != 2) continue;
        if (!(key.mrt_mask & (1u << target)) || !MaterialWrites(i, masks[i])) {
            return unknown("sampled MRT or required channel write missing");
        }
    }
    const std::array depth_stencil{
        std::bit_cast<u32>(regs.depth_control), std::bit_cast<u32>(regs.stencil_control),
        std::bit_cast<u32>(regs.stencil_ref_front), std::bit_cast<u32>(regs.stencil_ref_back),
        std::bit_cast<u32>(regs.depth_bounds_min), std::bit_cast<u32>(regs.depth_bounds_max)};
    const u32 logic = u32(key.logic_op);

    // Inspect cached native views only. A Find call here could create a view or resolve an alias.
    const auto native_backing = [&](VideoCore::ImageId id, VideoCore::Image* image) {
        if (!image || !image->backing || !image->GetImage() || image->binding.needs_rebind ||
            !texture_cache.IsRegisteredImage(id, image->image_uid) ||
            image->guest_begin == 0 || image->guest_end <= image->guest_begin ||
            (image->info.stencil_addr &&
             image->info.stencil_addr + image->info.stencil_size <= image->info.stencil_addr)) {
            return MaterialBacking{};
        }
        return MaterialBacking{
            .image = std::bit_cast<u64>(VkImage(image->GetImage())),
            .backing = u64(reinterpret_cast<std::uintptr_t>(image->backing)),
            .begin = image->guest_begin, .end = image->guest_end,
            .stencil_begin = image->info.stencil_addr,
            .stencil_end = image->info.stencil_addr + image->info.stencil_size,
            .id = id.index, .uid = image->image_uid,
        };
    };
    constexpr u32 motion_slot = Shader::MotionVectors::Output;
    static_assert(motion_slot == 7);
    const bool motion_output = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
    if (motion_output && (state.num_color_attachments <= motion_slot ||
                          !state.color_attachments[motion_slot].image_view)) {
        return unknown("alias-unproven: expected ObjectMotion slot 7 view is absent");
    }
    std::optional<LampMaterialMotion> motion;
    std::array<VideoCore::ImageId, 9> active_ids{};
    std::array<MaterialBacking, 9> active{};
    std::array<const VideoCore::Image::BackingImage*, 9> active_backings{};
    std::array<LampMaterialSource, MaterialTargets> sources{};
    std::array<VideoCore::Image*, MaterialTargets> images{};
    const char* unsupported = nullptr;
    for (u32 slot = 0; slot < active.size(); ++slot) {
        const bool depth = slot == active.size() - 1;
        if (!depth && slot >= state.num_color_attachments) {
            continue;
        }
        const auto& raster = depth ? state.depth_stencil_attachment : state.color_attachments[slot];
        const bool sampled = depth || (p.albedo_depth_only ? slot == 2 : slot >= 1 && slot <= 3);
        if (!raster.image_view && !sampled) {
            continue;
        }
        const auto& desc = depth ? db_desc : cb_descs[slot];
        const auto id = desc.first;
        if (!sampled && slot == motion_slot && (!id || motion_output)) {
            constexpr auto rgba = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                                  vk::ColorComponentFlagBits::eB | vk::ColorComponentFlagBits::eA;
            const auto& color = key.color_buffers[motion_slot];
            if (id || regs.color_buffers[motion_slot] || Dc().clear_draw || !motion_output ||
                !(key.mrt_mask & (1u << motion_slot)) || key.num_color_attachments <= motion_slot ||
                color.data_format != AmdGpu::DataFormat::Format32_32_32_32 ||
                color.num_format != AmdGpu::NumberFormat::Float || color.swizzle != AmdGpu::IdentityMapping ||
                key.HostWriteMask(motion_slot) != rgba || key.color_samples[motion_slot] != 1) {
                return unknown("alias-unproven: slot 7 has no eligible host motion raster output");
            }
            const auto owner = object_motion->FindAttachmentOwner(state.width, state.height);
            if (!owner) {
                return unknown("alias-unproven: slot 7 has no ObjectMotion target at the pass extent");
            }
            motion.emplace(LampMaterialMotion{*owner, raster});
            // LampPaneDraw publishes capture.scene from this ObjectMotion::Frame().
            // The target use stamp and owner frame come from that same counter.
            if (!motion->Current(object_motion.get(), {state.width, state.height}, p.capture.scene)) {
                return unknown("alias-unproven: slot 7 view, allocation, layout or frame differs from ObjectMotion");
            }
            continue;
        }
        auto* image = id ? texture_cache.TryGetImage(id, 0) : nullptr;
        const auto identity = native_backing(id, image);
        if (!identity.uid || !raster.image_view || image->binding.is_bound ||
            image->binding.force_general || image->scene_proxy || scene_targets->Tracks(identity.uid)) {
            // Query the existing objects only. The regular report emits this refusal once.
            const auto* backing = image ? image->backing : nullptr;
            const auto native = backing ? image->GetImage() : vk::Image{};
            const bool registered = image && texture_cache.IsRegisteredImage(id, image->image_uid);
            const bool views_known = registered && backing;
            vk::ImageView cached_view{};
            int final_in_native = -1;
            if (views_known) {
                const auto& views = backing->image_view_ids;
                if (backing->last_view < views.size()) {
                    cached_view = texture_cache.GetImageView(views[backing->last_view]).image_view.get();
                }
                final_in_native = raster.image_view && std::ranges::any_of(views, [&](auto view_id) {
                    return texture_cache.GetImageView(view_id).image_view.get() == raster.image_view;
                });
            }
            const bool guest_base_ok = image && image->guest_begin != 0;
            const bool guest_end_ok = image && image->guest_end > image->guest_begin;
            const bool stencil_ok = image && (!image->info.stencil_addr ||
                image->info.stencil_addr + image->info.stencil_size > image->info.stencil_addr);
            auto& detail = material.refusal_detail;
            std::snprintf(detail.data(), detail.size(),
                          "alias-unproven: render attachment lacks an isolated native backing "
                          "phase=%s slot=%u depth=%u sampled=%u id=%u uid=%llu "
                          "image_found=%u registered=%u rebind=%d guest_base_ok=%u guest_end_ok=%u stencil_ok=%u "
                          "final_view=%llx backing=%llx vk_image=%llx cached_view=%llx final_in_native=%d "
                          "is_bound=%d force_general=%d proxy=%d tracked=%d stale=%d",
                          after ? "B" : "A", slot, unsigned(depth), unsigned(sampled), id.index,
                          static_cast<unsigned long long>(image ? image->image_uid : 0),
                          unsigned(image != nullptr), unsigned(registered),
                          image ? int(image->binding.needs_rebind) : -1,
                          unsigned(guest_base_ok), unsigned(guest_end_ok), unsigned(stencil_ok),
                          static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(raster.image_view))),
                          static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(backing)),
                          static_cast<unsigned long long>(std::bit_cast<u64>(VkImage(native))),
                          static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(cached_view))),
                          final_in_native, image ? int(image->binding.is_bound) : -1,
                          image ? int(image->binding.force_general) : -1,
                          image ? int(image->scene_proxy) : -1,
                          image ? int(scene_targets->Tracks(image->image_uid)) : -1,
                          image ? int(scene_targets->NativeStale(*image)) : -1);
            return unknown(detail.data());
        }
        const auto& backing = *image->backing;
        const auto last = backing.last_view;
        if (last >= backing.image_view_ids.size()) {
            return unknown("alias-unproven: native attachment view unavailable");
        }
        const auto& view = texture_cache.GetImageView(backing.image_view_ids[last]);
        if (view.image_view.get() != raster.image_view || view.info != desc.second.view_info ||
            backing.state.layout != raster.image_layout) {
            return unknown("alias-unproven: final raster view differs from native view/layout");
        }
        active_ids[slot] = id;
        active[slot] = identity;
        active_backings[slot] = &backing;
        if (!sampled) {
            continue;
        }
        const u32 target = depth ? 3u : slot - 1;
        const auto format = image->info.pixel_format;
        const auto& range = view.info.range;
        const auto& ci = backing.image.image_ci;
        // Match ImageView's creation rule. GetSupportedFormat uses the cached device format table.
        auto view_format = view.info.format;
        if (((image->aspect_mask & vk::ImageAspectFlagBits::eDepth) &&
             LiverpoolToVK::IsFormatDepthCompatible(view_format)) ||
            ((image->aspect_mask & vk::ImageAspectFlagBits::eStencil) &&
             LiverpoolToVK::IsFormatStencilCompatible(view_format))) {
            view_format = format;
        }
        const auto effective_view = instance.GetSupportedFormat(view_format, image->format_features);
        sources[target] = {identity, raster.image_view, view.info, raster.image_layout,
                           image->info.size.width, image->info.size.height, backing.num_samples,
                           ci.format, effective_view};
        images[target] = image;
        const bool format_ok = depth ? (format == vk::Format::eD32Sfloat || format == vk::Format::eD32SfloatS8Uint)
                                     : LampMaterialEncoding(format) != LampMaterialColor::Unsupported;
        const auto attachment_write = depth ? Access::eDepthStencilAttachmentWrite : Access::eColorAttachmentWrite;
        if (!after && !p.albedo_depth_only) {
            std::printf("Lamp material (t132d): req %u scene %llu draw %u build %u MRT %d image %u/%llu vk=%llx "
                        "view=%llx guest=%llx..%llx format=%u/%u extent=%ux%u samples=%u/%u "
                        "mip=%u+%u layer=%u+%u layout=%u created=%u effective_view=%u\n",
                        p.capture.request, static_cast<unsigned long long>(p.capture.scene), p.capture.draw, p.capture.build,
                        depth ? -1 : int(slot), id.index, static_cast<unsigned long long>(identity.uid),
                        static_cast<unsigned long long>(identity.image),
                        static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(raster.image_view))),
                        static_cast<unsigned long long>(identity.begin), static_cast<unsigned long long>(identity.end),
                        u32(format), u32(view.info.format), image->info.size.width, image->info.size.height,
                        image->info.num_samples, backing.num_samples, range.base.level, range.extent.levels,
                        range.base.layer, range.extent.layers, u32(raster.image_layout),
                        u32(ci.format), u32(effective_view));
        }
        if (!unsupported) {
            struct Check {
                const char* predicate;
                bool passed;
            };
            const Check checks[] = {
                {"declared-image-format", format_ok},
                {"declared-view-format", view.info.format == format},
                {"created-colour-format", depth || ci.format == format},
                {"effective-colour-view-format", depth || effective_view == ci.format},
                {"colour-aspect", depth || image->aspect_mask == vk::ImageAspectFlagBits::eColor},
                {"identity-swizzle", view.info.mapping == vk::ComponentMapping{}},
                {"guest-single-sample", image->info.num_samples == 1},
                {"native-single-sample", backing.num_samples == 1},
                {"creation-single-sample", ci.samples == vk::SampleCountFlagBits::e1},
                {"view-base-mip-layer", range.base == VideoCore::SubresourceBase{}},
                {"view-single-mip-layer", range.extent == VideoCore::SubresourceExtent{1, 1}},
                {"image-single-mip-layer", image->info.resources == VideoCore::SubresourceExtent{1, 1}},
                {"whole-backing-layout", backing.subresource_states.empty()},
                {"image-transfer-src", bool(image->usage_flags & vk::ImageUsageFlagBits::eTransferSrc)},
                {"creation-transfer-src", bool(ci.usage & vk::ImageUsageFlagBits::eTransferSrc)},
                {"non-transient", !(ci.usage & vk::ImageUsageFlagBits::eTransientAttachment)},
                {"attachment-write-access", bool(backing.state.access_mask & attachment_write)},
                {"sample-extent", p.width <= image->info.size.width && p.height <= image->info.size.height},
            };
            if (const auto failed = std::ranges::find(checks, false, &Check::passed); failed != std::end(checks)) {
                const auto& m = view.info.mapping;
                auto& detail = material.refusal_detail;
                std::snprintf(detail.data(), detail.size(),
                              "unsupported sampled attachment phase=%s MRT=%d predicate=%s "
                              "formats=image:%u,view:%u,created:%u,effective:%u aspect=%x swizzle=%u,%u,%u,%u "
                              "samples=%u/%u/%u view_mip=%u+%u view_layer=%u+%u image_mips=%u image_layers=%u "
                              "split_layout=%u usage=%x/%x access=%llx actual=%ux%u sample=%ux%u",
                              after ? "B" : "A", depth ? -1 : int(slot), failed->predicate,
                              u32(format), u32(view.info.format), u32(ci.format), u32(effective_view),
                              u32(VkImageAspectFlags(image->aspect_mask)), u32(m.r), u32(m.g), u32(m.b), u32(m.a),
                              image->info.num_samples, backing.num_samples, u32(ci.samples),
                              range.base.level, range.extent.levels, range.base.layer, range.extent.layers,
                              image->info.resources.levels, image->info.resources.layers,
                              unsigned(!backing.subresource_states.empty()),
                              u32(VkImageUsageFlags(image->usage_flags)), u32(VkImageUsageFlags(ci.usage)),
                              static_cast<unsigned long long>(VkAccessFlags2(backing.state.access_mask)),
                              image->info.size.width, image->info.size.height, p.width, p.height);
                unsupported = detail.data();
            }
        }
        if (depth && (id.index != p.capture.image || identity.uid != p.capture.uid)) {
            return unknown("alias-unproven: sampled depth differs from geometry witness");
        }
    }
    if (after && motion != material.motion) {
        return unknown("alias-unproven: ObjectMotion slot 7 owner or attachment state changed across A/B");
    }
    if (motion) {
        for (const auto* backing : active_backings) {
            if (backing && !motion->SeparateFrom(vk::Image(backing->image), backing->image.allocation,
                                                  backing->image.image_ci)) {
                return unknown("alias-unproven: ObjectMotion slot 7 overlaps or cannot verify an active attachment");
            }
        }

        // Guest IDs alone are insufficient: image_infos holds the views actually bound for set 0.
        // A replacement or proxy view outside the current native backings remains unknown.
        const auto& dc = Dc();
        std::array<bool, Shader::NUM_IMAGES> resolved{};
        for (const auto id : dc.bound_images) {
            const auto* image = id ? texture_cache.TryGetImage(id, 0) : nullptr;
            if (!image || !image->backing || image->binding.needs_rebind ||
                !texture_cache.IsRegisteredImage(id, image->image_uid)) {
                return unknown("alias-unproven: ObjectMotion slot 7 cannot verify a bound image identity");
            }
            const auto& backing = *image->backing;
            if (!motion->SeparateFrom(vk::Image(backing.image), backing.image.allocation, backing.image.image_ci)) {
                return unknown("alias-unproven: ObjectMotion slot 7 overlaps or cannot verify a bound image");
            }
            for (const auto view_id : backing.image_view_ids) {
                const auto view = texture_cache.GetImageView(view_id).image_view.get();
                for (u32 i = 0; i < dc.image_infos.size(); ++i) {
                    resolved[i] |= view && view == dc.image_infos[i].imageView;
                }
            }
        }
        for (u32 i = 0; i < dc.image_infos.size(); ++i) {
            const auto view = dc.image_infos[i].imageView;
            if (view && (!resolved[i] || view == motion->owner.view)) {
                return unknown("alias-unproven: ObjectMotion slot 7 cannot verify a bound descriptor view");
            }
        }
        const auto& owner = motion->owner;
        if (!p.albedo_depth_only) std::printf("Lamp material (t132d): req %u phase=%s slot=7 owner=ObjectMotion scene=%llu owner_frame=%llu "
                    "used_frame=%llu owner_ptr=%llx target=%llx allocation=%llx vk_image=%llx view=%llx "
                    "extent=%ux%u layout=%u clear=%u separate=attachments-and-bound-images\n",
                    p.capture.request, after ? "B" : "A", static_cast<unsigned long long>(p.capture.scene),
                    static_cast<unsigned long long>(owner.owner_frame), static_cast<unsigned long long>(owner.used_frame),
                    static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(owner.owner)),
                    static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(owner.target)),
                    static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(owner.allocation)),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImage(owner.image))),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkImageView(owner.view))),
                    owner.extent.width, owner.extent.height, u32(owner.layout), motion->attachment.is_clear);
    }
    if (unsupported) {
        return unknown(unsupported);
    }

    for (u32 i = 0; i < sources.size(); ++i) {
        if (!images[i]) continue;
        const u32 slot = i == 3 ? u32(active.size() - 1) : i + 1;
        for (u32 j = 0; j < active.size(); ++j) {
            if (j != slot && active[j].uid && MaterialAlias(sources[i].backing, active[j])) {
                return unknown("alias-unproven: overlapping raster attachments");
            }
        }
    }
    for (const auto id : Dc().bound_images) {
        if (std::ranges::find(active_ids, id) != active_ids.end()) {
            continue;
        }
        const auto* image = id ? texture_cache.TryGetImage(id, 0) : nullptr;
        if (!image || !image->backing || image->guest_begin == 0 || image->guest_end <= image->guest_begin) {
            return unknown("alias-unproven: bound image range unavailable");
        }
        const MaterialBacking alias{.image = std::bit_cast<u64>(VkImage(image->GetImage())),
                                    .backing = u64(reinterpret_cast<std::uintptr_t>(image->backing)),
                                    .begin = image->guest_begin, .end = image->guest_end,
                                    .stencil_begin = image->info.stencil_addr,
                                    .stencil_end = image->info.stencil_addr + image->info.stencil_size};
        for (const auto& source : sources) {
            if (source.backing.uid && MaterialAlias(source.backing, alias)) {
                return unknown("alias-unproven: bound resource overlaps a sampled attachment");
            }
        }
    }
    if (after && (material.sources != sources || material.scissor != scissor ||
                  material.masks != masks || material.blend != blend ||
                  material.depth_stencil != depth_stencil || material.mrt != key.mrt_mask ||
                  material.logic != logic)) {
        return unknown("A/B target, view, viewport or write state changed");
    }
    if (!p.allocate()) {
        return unknown("staging unavailable");
    }
    if (!scheduler.SuspendRenderingForReadback(state)) {
        return unknown("open STORE render scope unavailable");
    }
    if (!after) {
        material.sources = sources;
        material.delivery = draw;
        material.motion = motion;
        material.scissor = scissor;
        material.masks = masks;
        material.blend = blend;
        material.depth_stencil = depth_stencil;
        material.mrt = key.mrt_mask;
        material.logic = logic;
        if (!p.albedo_depth_only) std::printf("Lamp material (t132d): req %u scene %llu draw %u build %u pair=%llx:%llx "
                    "raster=%llx first=%u base=%d first_instance=%u count=%u instances=%u "
                    "scissor=%d,%d,%u,%u mrt=%x masks=%x,%x,%x blend=%x,%x,%x logic=%u "
                    "depth_stencil=%x,%x,%x,%x bounds=%x,%x\n",
                    p.capture.request, static_cast<unsigned long long>(p.capture.scene), p.capture.draw, p.capture.build,
                    static_cast<unsigned long long>(vs), static_cast<unsigned long long>(ps->pgm_hash),
                    static_cast<unsigned long long>(std::bit_cast<u64>(VkPipeline(draw.handle))),
                    draw.first, int(s32(draw.base)), draw.first_instance, regs.num_indices,
                    regs.num_instances.NumInstances(), scissor.offset.x, scissor.offset.y,
                    scissor.extent.width, scissor.extent.height, material.mrt, masks[0], masks[1], masks[2],
                    blend[0], blend[1], blend[2], logic, depth_stencil[0], depth_stencil[1],
                    depth_stencil[2], depth_stencil[3], depth_stencil[4], depth_stencil[5]);
    }

    std::array<u64, MaterialTargets> offsets{};
    for (u32 i = 0; i < offsets.size(); ++i) {
        offsets[i] = p.offset + MaterialOffset(phase, i, 0);
    }
    const bool recorded = material.phases.Record(phase, p.capture, scheduler.CurrentTick());
    ASSERT(recorded);
    RecordDrawRaw(images, p.samples, vk::Buffer{p.buffer}, p.compact_offsets ? *p.compact_offsets : offsets);
    if (auto* lineage = p.lineage; lineage && !lineage->refusal) {
        const auto& bound = Dc().index_bind;
        const auto& resolved = lineage->resolved;
        const bool shape = draw.indexed && regs.num_indices == DrawIndices &&
            regs.num_instances.NumInstances() == Instances && !regs.enable_primitive_restart &&
            LiverpoolToVK::PrimitiveType(regs.primitive_type) == vk::PrimitiveTopology::eTriangleList;
        if (!shape || !resolved.checked || !bound.handle || bound.handle != resolved.buffer ||
            bound.offset != resolved.offset || bound.type != vk::IndexType::eUint16) {
            lineage->refusal = "unproved_bound_uint16_span";
        } else if (after) {
            if (!lineage->tick || lineage->before != resolved) {
                lineage->refusal = "A_B_index_binding_changed";
            } else {
                lineage->after = true;
            }
        } else {
            lineage->before = resolved;
            lineage->tick = material.phases.before_tick;
            const auto& cfg = Round2ProbeSettings::Get();
            auto* profiler = cfg.cost ? GpuProfiler::Get() : nullptr;
            const auto previous = profiler && profiler->Records(&scheduler) ?
                profiler->BeginRound2Copy(GpuProfiler::Round2Copy::Index) : std::nullopt;
            const u64 record_start = Round2CostStart(cfg.cost);
            scheduler.Record([source = resolved.buffer, destination = vk::Buffer{p.buffer},
                              src = resolved.offset, dst = p.lineage_offset](vk::CommandBuffer cmd) {
                const vk::MemoryBarrier2 ready{
                    .srcStageMask = Stage::eAllCommands | Stage::eHost,
                    .srcAccessMask = Access::eMemoryWrite | Access::eHostWrite,
                    .dstStageMask = Stage::eCopy, .dstAccessMask = Access::eTransferRead,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &ready});
                const vk::BufferCopy region{.srcOffset = src, .dstOffset = dst, .size = LampIndexLineage::Bytes};
                cmd.copyBuffer(source, destination, region);
                const std::array visibility{
                    vk::MemoryBarrier2{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferWrite,
                                       .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead},
                    vk::MemoryBarrier2{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferRead,
                                       .dstStageMask = Stage::eAllCommands, .dstAccessMask = Access::eMemoryWrite},
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = u32(visibility.size()), .pMemoryBarriers = visibility.data()});
            });
            const u64 record_ns = Round2CostElapsed(record_start);
            if (previous) {
                profiler->Resume(*previous);
            }
            if (cfg.cost) {
                const auto print = [](u64 value) { return static_cast<unsigned long long>(value); };
                std::printf("Round2 cost: {\"schema\":\"round2-host-cost-v1\",\"kind\":\"index\",\"op\":\"record\","
                            "\"session\":\"%s\",\"pid\":%d,\"request\":%u,\"scene\":%llu,\"rt\":%llu,\"tick\":%llu,"
                            "\"elapsed_ns\":%llu,\"index_payload_bytes\":%u,\"lineage_enabled\":true,\"status\":\"ok\"}\n",
                            cfg.session, Round2ProbeSettings::Pid(), p.capture.request, print(p.capture.scene),
                            print(p.capture.rt), print(lineage->tick), print(record_ns), LampIndexLineage::Bytes);
            }
        }
    }
    scheduler.BeginRendering(state);
    return true;
}

void Rasterizer::RecordDrawRaw(const std::array<VideoCore::Image*, 4>& images,
                               std::span<const RawDrawPixel> samples, vk::Buffer buffer,
                               const std::array<u64, 4>& offsets) {
    using namespace RtLampPane;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    // Native sources are held by the texture cache through its scheduler-deferred backing frees.
    // Use the backing tracker directly so observation cannot invoke Runtime::Transit's lazy proxy resolve.
    VideoCore::Image::Barriers to_copy, restore;
    std::array<vk::Image, MaterialTargets> source_images{};
    // The exact sewer witness uses three texels; existing lamp/window probes use at most two.
    std::array<std::array<vk::BufferImageCopy, SewerReceiverProbe::Pixels.size()>, MaterialTargets> regions{};
    ASSERT(samples.size() <= regions.front().size());
    for (u32 target = 0; target < images.size(); ++target) {
        if (!images[target]) continue;
        auto& image = *images[target];
        const auto original = image.backing->state;
        source_images[target] = image.GetImage();
        image.GetBarriers(to_copy, vk::ImageLayout::eTransferSrcOptimal, Access::eTransferRead, Stage::eCopy);
        image.GetBarriers(restore, original.layout, original.access_mask, original.pl_stage);
        const auto aspect = target == 3 ? vk::ImageAspectFlagBits::eDepth : vk::ImageAspectFlagBits::eColor;
        for (u32 pixel = 0; pixel < samples.size(); ++pixel) {
            regions[target][pixel] = {
                .bufferOffset = offsets[target] + pixel * MaterialTexelBytes,
                .imageSubresource = {aspect, 0, 0, 1},
                .imageOffset = {s32(samples[pixel].x), s32(samples[pixel].y), 0},
                .imageExtent = {1, 1, 1},
            };
        }
    }
    scheduler.RecordCrumb({.name = "t132d lamp material texels"},
                          [source_images, regions, buffer, count = u32(samples.size()),
                           copy = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(to_copy.data(), to_copy.size())),
                           resume = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(restore.data(), restore.size()))]
                          (vk::CommandBuffer cmd) {
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = u32(copy.size()), .pImageMemoryBarriers = copy.data()});
        for (u32 i = 0; i < source_images.size(); ++i) {
            if (source_images[i]) {
                cmd.copyImageToBuffer(source_images[i], vk::ImageLayout::eTransferSrcOptimal, buffer,
                    vk::ArrayProxy<const vk::BufferImageCopy>{count, regions[i].data()});
            }
        }
        constexpr auto attachment_stages = Stage::eColorAttachmentOutput | Stage::eEarlyFragmentTests | Stage::eLateFragmentTests;
        constexpr auto attachment_writes = Access::eColorAttachmentWrite | Access::eDepthStencilAttachmentWrite;
        const std::array barriers{
            vk::MemoryBarrier2{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferWrite,
                              .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead},
            vk::MemoryBarrier2{.srcStageMask = attachment_stages, .srcAccessMask = attachment_writes,
                              .dstStageMask = attachment_stages,
                              .dstAccessMask = attachment_writes | Access::eColorAttachmentRead | Access::eDepthStencilAttachmentRead},
        };
        cmd.pipelineBarrier2({.memoryBarrierCount = u32(barriers.size()), .pMemoryBarriers = barriers.data(),
                              .imageMemoryBarrierCount = u32(resume.size()), .pImageMemoryBarriers = resume.data()});
    });
}

namespace {
constexpr auto Round2FrameStage = "native.previous_ldr_scene_target_before_display_copy";

std::string Round2FloatWords(std::span<const float> values) {
    std::string words = "[";
    for (size_t i = 0; i < values.size(); ++i) {
        fmt::format_to(std::back_inserter(words), "{}\"{:08x}\"", i ? "," : "", std::bit_cast<u32>(values[i]));
    }
    words += ']';
    return words;
}

bool Round2Write(std::string_view path, const void* bytes, size_t size) {
    const std::string name(path);
    if (auto* file = std::fopen(name.c_str(), "wbx")) {
        const auto wrote = std::fwrite(bytes, 1, size, file);
        if (!std::fclose(file) && wrote == size) return true;
        std::remove(name.c_str());
    }
    return false;
}
} // namespace

bool Rasterizer::SewerReceiverSample(const RenderState& state, const LampMaterialDelivery& draw,
                                     bool after) {
    auto& p = *sewer_receiver;
    const auto& regs = Regs();
    if (!after) {
        if (!p.requested || p.finished || p.reason || p.stage_count ||
            draw.first != p.First || regs.num_indices != p.Indices) {
            return false;
        }
        const auto* ps = draw.original->GetStages()[u32(Shader::SwStage::Fragment)];
        if (!ps || ps->pgm_hash != p.Ps ||
            draw.original->GetStage(Shader::SwStage::Vertex).pgm_hash != p.Vs) {
            return false;
        }
        const auto camera = camera_motion->PassMatrices();
        const std::array position{camera.inv_view[3], camera.inv_view[7], camera.inv_view[11]};
        const auto ready_pose = [](const std::array<float, 3>& xyz) {
            // p157 and b157 t180 made one walk. p158 made two at the same first waypoint.
            constexpr std::array centers{std::array{13.550f, -27.295f, 108.495f},
                                         std::array{13.762f, -27.284f, 108.167f}};
            constexpr float radius = 0.10f;
            for (u32 i = 0; i < centers.size(); ++i) {
                const auto& c = centers[i];
                if (std::abs(xyz[0] - c[0]) <= radius &&
                    std::abs(xyz[1] - c[1]) <= radius &&
                    std::abs(xyz[2] - c[2]) <= radius) {
                    return i + 1;
                }
            }
            return 0u;
        };
        enum CandidateGate : u32 { Indexed, GBuffer, Extent, Loading, Camera, Depth, Projection, Pose };
        const auto skip = [&](CandidateGate gate, const char* reason) {
            // Only the armed exact shader/count/first can reach this. Remember one row
            // per failed predicate while waiting for a valid full-size draw.
            struct CandidateLog {
                const SewerReceiverProbe* probe = nullptr;
                u64 armed_frame = 0;
                u32 seen = 0;
            };
            static thread_local CandidateLog log;
            if (log.probe != &p || log.armed_frame != p.armed_frame) {
                log = {&p, p.armed_frame, 0};
            }
            const u32 bit = 1u << gate;
            if (!(log.seen & bit)) {
                log.seen |= bit;
                fmt::print("Sewer receiver (t182) candidate refused={} scene={} extent={}x{} "
                           "position={:.5f},{:.5f},{:.5f} camera_depth={} draw_depth={}\n",
                           reason, object_motion->Frame(), state.width, state.height,
                           position[0], position[1], position[2], camera_motion->Depth().index,
                           db_desc.first.index);
            }
            return false;
        };
        if (!draw.indexed) return skip(Indexed, "not-indexed");
        if (!gbuffer_draw) return skip(GBuffer, "not-gbuffer");
        if (state.width != p.Width || state.height != p.Height) return skip(Extent, "not-1920x1080");
        if (BbEngine::Loading::ScreenUp()) return skip(Loading, "loading");
        if (!camera.valid) return skip(Camera, "pass-camera-unavailable");
        if (camera_motion->Depth() != db_desc.first) return skip(Depth, "camera-depth-id-mismatch");
        ::BbCaustics::Push geometry{};
        geometry.proj = camera.proj;
        geometry.inv_view = camera.inv_view;
        geometry.frame = {float(p.Width), float(p.Height), Dc().draw_jitter[0], Dc().draw_jitter[1]};
        if (!::BbCaustics::WetnessProbe::ProjectionValid(geometry, camera.view)) {
            return skip(Projection, "projection-domain-invalid");
        }
        const u32 pose = ready_pose(position);
        if (!pose) return skip(Pose, "outside-known-ready-poses");
        fmt::print("Sewer receiver (t182) candidate pose={} scene={} position={:.5f},{:.5f},{:.5f}\n",
                   pose, object_motion->Frame(), position[0], position[1], position[2]);
        p.frame = BbStats::frame_number.load(std::memory_order_relaxed);
        p.loading = BbEngine::Loading::Generation();
        p.scene_generation = scene_targets->Generation();
        const auto* depth = db_desc.first ? texture_cache.TryGetImage(db_desc.first, 0) : nullptr;
        p.identity = {1, 1, 1, db_desc.first.index, object_motion->Frame(),
                      rt_shadow->WindowDiagnosticFrame(), depth ? depth->image_uid : 0};
        p.camera = {camera.view, camera.inv_view, camera.proj};
        p.jitter = Dc().draw_jitter;
        p.index_base = regs.index_base_address.Address<VAddr>();
    }
    const auto refuse = [&](const char* reason) {
        p.reason = reason;
        return false;
    };
    const auto& ds = state.depth_stencil_attachment;
    const auto& dynamic = scheduler.GetDynamicState();
    if (!p.identity.uid || !gbuffer_draw || camera_motion->Depth() != db_desc.first ||
        p.frame != BbStats::frame_number.load(std::memory_order_relaxed) ||
        p.loading != BbEngine::Loading::Generation() || BbEngine::Loading::ScreenUp() ||
        p.scene_generation != scene_targets->Generation() ||
        p.identity.rt != rt_shadow->WindowDiagnosticFrame()) {
        return refuse("draw-frame-or-generation-mismatch");
    }
    const auto* albedo = cb_descs[2].first ? texture_cache.TryGetImage(cb_descs[2].first, 0) : nullptr;
    const auto* depth = texture_cache.TryGetImage(db_desc.first, p.identity.uid);
    const auto exact_extent = [](const VideoCore::Image* image) {
        return image && image->backing && image->info.size.width == SewerReceiverProbe::Width &&
               image->info.size.height == SewerReceiverProbe::Height && image->backing->image.image_ci.extent ==
                   vk::Extent3D{SewerReceiverProbe::Width, SewerReceiverProbe::Height, 1};
    };
    if (!exact_extent(albedo)) return refuse("native-cb2-extent");
    if (!exact_extent(depth)) return refuse("native-depth-extent");
    if (albedo->info.pixel_format != vk::Format::eR8G8B8A8Srgb) return refuse("native-cb2-format");
    if (depth->info.pixel_format != vk::Format::eD32Sfloat &&
        depth->info.pixel_format != vk::Format::eD32SfloatS8Uint) {
        return refuse("native-d32-format");
    }
    if ((draw.original->GetGraphicsKey().mrt_mask & 0x7f) != 0x3f ||
        state.num_color_attachments < 6 || !ds.image_view || !ds.has_depth) {
        return refuse("native-gbuffer-attachments");
    }
    if (state.color_attachments[2].is_clear || ds.depth_clear || ds.stencil_clear || Dc().clear_draw) {
        return refuse("sampled-attachment-clear");
    }
    if (draw.raster != draw.original || !draw.handle) return refuse("original-raster-unavailable");
    if (draw.first_instance != 0 || regs.num_instances.NumInstances() != 1 ||
        LiverpoolToVK::PrimitiveType(regs.primitive_type) != vk::PrimitiveTopology::eTriangleList ||
        regs.enable_primitive_restart || !Dc().index_bind.handle) {
        return refuse("indexed-draw-shape");
    }
    if (!dynamic.depth_test_enabled || !dynamic.depth_write_enabled ||
        dynamic.depth_compare_op != vk::CompareOp::eLessOrEqual || dynamic.depth_bias_enabled ||
        dynamic.depth_bounds_test_enabled || dynamic.rasterizer_discard_enable) {
        return refuse("opaque-depth-state");
    }
    if (draw.raster->GetGraphicsKey().blend_controls[2].enable) return refuse("cb2-blend-enabled");
    const vk::Viewport v = dynamic.viewports.empty() ? vk::Viewport{} : dynamic.viewports.front();
    const vk::Rect2D scissor = dynamic.scissors.empty() ? vk::Rect2D{} : dynamic.scissors.front();
    const std::array viewport{v.x, v.y, v.width, v.height, v.minDepth, v.maxDepth};
    const auto jitter = Dc().draw_jitter;
    // UpdateViewportScissorState adds draw_jitter after the target transform. Match
    // its exact native forward transform. Subtracting the height from the flipped
    // viewport origin before testing zero would also round at the far edge.
    const auto native_origin = [](float height, bool flipped, std::array<float, 2> j) {
        return std::array{j[0], (flipped ? height : 0.0f) + j[1]};
    };
    const bool flipped = regs.viewports[0].yscale < 0.0f;
    const auto origin = native_origin(float(p.Height), flipped, jitter);
    u32 view_mask = 0, scissor_mask = 0;
    for (u32 i = 0; i < p.Pixels.size(); ++i) {
        const auto pixel = p.Pixels[i];
        const float x = float(pixel.x) + 0.5f, y = float(pixel.y) + 0.5f;
        if (x >= v.x && x < v.x + v.width &&
            y >= std::min(v.y, v.y + v.height) && y < std::max(v.y, v.y + v.height)) {
            view_mask |= 1u << i;
        }
        const s64 sx = s64(pixel.x) - scissor.offset.x, sy = s64(pixel.y) - scissor.offset.y;
        if (sx >= 0 && sy >= 0 && sx < scissor.extent.width && sy < scissor.extent.height) {
            scissor_mask |= 1u << i;
        }
    }
    constexpr u32 all_points = (1u << SewerReceiverProbe::Pixels.size()) - 1;
    struct Check { const char* name; bool ok; };
    const std::array checks{
        Check{"viewport-count", dynamic.viewports.size() == 1},
        Check{"scissor-count", dynamic.scissors.size() == 1},
        Check{"clipping-disabled", !regs.IsClipDisabled()},
        Check{"target-scale", target_scale[0] == 1.0f && target_scale[1] == 1.0f},
        Check{"target-offset", target_offset[0] == 0 && target_offset[1] == 0},
        Check{"jitter-domain", std::abs(jitter[0]) <= 0.5f && std::abs(jitter[1]) <= 0.5f},
        Check{"jitter-changed", jitter == p.jitter},
        Check{"viewport-x", v.x == origin[0]},
        Check{"viewport-y", v.y == origin[1]},
        Check{"viewport-width", v.width == float(p.Width)},
        Check{"viewport-height", v.height == (flipped ? -float(p.Height) : float(p.Height))},
        Check{"viewport-min-depth", v.minDepth == 0.0f},
        Check{"viewport-max-depth", v.maxDepth == 1.0f},
        Check{"viewport-coverage", view_mask == all_points},
        Check{"scissor-coverage", scissor_mask == all_points},
        Check{"viewport-changed", !after || viewport == p.viewport},
        Check{"scissor-changed", !after || scissor == p.scissor},
    };
    std::string failed;
    for (const auto& check : checks) {
        if (!check.ok) {
            if (!failed.empty()) failed += ',';
            failed += check.name;
        }
    }
    const auto& cb = albedo->backing->image.image_ci.extent;
    const auto& db = depth->backing->image.image_ci.extent;
    fmt::print("Sewer receiver (t183) phase={} scene={} failed={} viewport-count={} scissor-count={} "
               "viewport={},{},{},{},{},{} scissor={},{},{},{} expected-xy={},{} clip={} "
               "jitter={},{} target-scale={},{} target-offset={},{} coverage-view={:x} coverage-scissor={:x} "
               "render={}x{} cb2={}x{}->{}x{}x{} depth={}x{}->{}x{}x{}\n",
               after ? "after" : "before", p.identity.scene, failed.empty() ? "none" : failed.c_str(),
               dynamic.viewports.size(), dynamic.scissors.size(), v.x, v.y, v.width, v.height,
               v.minDepth, v.maxDepth, scissor.offset.x, scissor.offset.y, scissor.extent.width,
               scissor.extent.height, origin[0], origin[1], !regs.IsClipDisabled(), jitter[0], jitter[1],
               target_scale[0], target_scale[1], target_offset[0], target_offset[1], view_mask,
               scissor_mask, state.width, state.height, albedo->info.size.width, albedo->info.size.height,
               cb.width, cb.height, cb.depth, depth->info.size.width, depth->info.size.height,
               db.width, db.height, db.depth);
    if (!failed.empty()) {
        return refuse("draw-viewport-or-scissor-mismatch");
    }
    p.viewport = viewport;
    p.scissor = scissor;
    const auto offsets = p.Offsets(after ? 1u : 0u);
    DrawRawRead read{p.material, p.identity, p.camera, p.jitter, p.Pixels, p.buffer,
                     [&] { return p.Allocate(instance.GetAllocator()); }, 0,
                     p.Width, p.Height, 1, p.First, draw.base, draw.first_instance,
                     p.Vs, p.Ps, p.Indices, 1, true};
    read.compact_offsets = &offsets;
    if (!SampleDrawRaw(read, state, draw, after)) {
        return refuse(p.material.refusal);
    }
    p.stage_count = after ? 2 : 1;
    if (!after && caustics) {
        caustics->StartNativeBedTrace(p.frame, p.identity.scene, p.trace.pass, db_desc.first);
    }
    p.tick = after ? p.material.phases.after_tick : p.material.phases.before_tick;
    if (after && p.TraceScene(p.identity.scene)) {
        p.trace.ground = ++p.trace.order;
        p.trace.ground_pass = p.trace.pass;
        p.trace.ground_write = depth->write_seq;
    }
    return true;
}

void Rasterizer::SewerReceiverGBufferChange() {
    auto& p = *sewer_receiver;
    if (!p.TraceScene(object_motion->Frame())) return;
    ++p.trace.pass;
    if (!p.stage_count) {
        p.trace.copy = {};
        p.trace.water = 0;
        p.trace.water_write = 0;
        p.trace.ambiguous = false;
    }
}

void Rasterizer::SewerReceiverWaterDraw(const RenderState& state, const GraphicsPipeline* pipeline) {
    auto& p = *sewer_receiver;
    if (!p.TraceScene(object_motion->Frame()) || p.trace.water || p.trace.apply ||
        !db_desc.first || camera_motion->Depth() != db_desc.first) {
        return;
    }
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps || ps->pgm_hash != 0xa28d2a7a ||
        pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash != 0xe4680233) {
        return;
    }
    // R483 identifies this native direct writer at both wet points. Record the earliest
    // submission in this pass. The existing fenced Apply read still has to confirm the plane.
    const auto& dynamic = scheduler.GetDynamicState();
    const auto* depth = texture_cache.TryGetImage(db_desc.first, 0);
    if (!depth || !state.depth_stencil_attachment.has_depth ||
        state.depth_stencil_attachment.depth_clear || Dc().clear_draw ||
        !dynamic.depth_test_enabled || !dynamic.depth_write_enabled ||
        dynamic.depth_compare_op != vk::CompareOp::eLessOrEqual ||
        dynamic.rasterizer_discard_enable || state.width != p.Width || state.height != p.Height ||
        scene_targets->Reduced() || (p.stage_count &&
            (p.trace.pass != p.trace.ground_pass ||
             p.ImageKey(db_desc.first, *depth) != p.material.sources[RawDepth].backing))) {
        return;
    }
    p.trace.water = ++p.trace.order;
    p.trace.water_write = depth->write_seq;
}

void Rasterizer::NoteSewerDepthBlockCopy(VideoCore::ImageId src_id, const VideoCore::Image& src,
                                         VideoCore::ImageId dst_id, const VideoCore::Image& dst,
                                         u64 bytes, u64 previous_dst_write, bool native) {
    auto& p = *sewer_receiver;
    if (!p.TraceScene(object_motion->Frame()) || !src_id ||
        (p.stage_count ? src_id.index != p.identity.image : src_id != camera_motion->Depth())) {
        return;
    }
    const auto camera = camera_motion->PassMatrices();
    auto& t = p.trace;
    SewerReceiverProbe::CopyObservation copy{
        .source = p.ImageKey(src_id, src), .destination = p.ImageKey(dst_id, dst),
        .camera = {camera.view, camera.inv_view, camera.proj}, .jitter = upscaler->Jitter(),
        .frame = BbStats::frame_number.load(std::memory_order_relaxed),
        .rt = rt_shadow->WindowDiagnosticFrame(), .loading = BbEngine::Loading::Generation(),
        .generation = scene_targets->Generation(), .tick = scheduler.CurrentTick(), .bytes = bytes,
        .src_write = src.write_seq, .dst_write = dst.write_seq, .order = ++t.order, .pass = t.pass,
        .native = native && !src.scene_proxy && !dst.scene_proxy &&
                  !scene_targets->Tracks(src.image_uid) && !scene_targets->Tracks(dst.image_uid),
        .enqueued = dst.write_seq > previous_dst_write,
        .camera_valid = camera.valid && src_id == camera_motion->Depth(),
    };
    if (t.apply) {
        if (!t.late.order && p.SameCopyPass(copy)) t.late = copy;
        return;
    }
    if (t.copy.order && t.copy.destination != copy.destination) t.ambiguous = true;
    t.copy = copy;
}

struct Rasterizer::SewerJoinedDraw {
    std::string stamp, raw, before;
    std::string owner = "?", actual_depth = "?", actual_cb2 = "?";
    int depth_matches = -1, cb2_matches = -1;
    bool product_draw = false, tracker_called = false;

    static u64 Handle(vk::ImageView view) {
        return std::bit_cast<u64>(VkImageView(view));
    }

    static std::string ViewInfo(const VideoCore::ImageViewInfo& info) {
        return fmt::format("{},{},{},{},{},{},{},{},{},{},{},{}",
                           u32(info.type), u32(info.format), info.range.base.level, info.range.base.layer,
                           info.range.extent.levels, info.range.extent.layers, u32(info.mapping.r),
                           u32(info.mapping.g), u32(info.mapping.b), u32(info.mapping.a),
                           info.min_lod, bool(info.is_storage));
    }

    void Motion(const std::optional<ObjectMotion::AttachmentOwner>& existing) {
        owner = existing ? fmt::format("{:x},{:x},{},{},{},{},{},{}",
                                       Handle(existing->view),
                                       std::bit_cast<u64>(VkImage(existing->image)),
                                       existing->extent.width, existing->extent.height,
                                       u32(existing->layout), existing->owner_frame, existing->used_frame,
                                       existing->written) : "none";
    }

    void Report(bool ground, u64 tick, const Caustics& caustics) const {
        std::printf("[sewer-joined-t202] event=%s %s tick=%llu %s before=%s after=%s "
                    "product_draw=%u tracker_called=%u owner=%s "
                    "native_depth=%d native_cb2=%d actual_depth_info=%s actual_cb2_info=%s\n",
                    ground ? "ground" : "water", stamp.c_str(), static_cast<unsigned long long>(tick),
                    raw.c_str(), before.c_str(), caustics.JoinedBedState().c_str(), unsigned(product_draw),
                    unsigned(tracker_called), owner.c_str(), depth_matches, cb2_matches,
                    actual_depth.c_str(), actual_cb2.c_str());
    }
};

namespace {
std::string JoinedCopyImage(VideoCore::ImageId id, const VideoCore::Image& image) {
    const auto base = fmt::format("{}/{}/{:x}/{:x},{},{},{},{},{:x},{},{},{:x},{:x},{:x},{:x}",
                                  id.index, image.image_uid,
                                  image.backing ? std::bit_cast<u64>(VkImage(image.GetImage())) : 0u,
                                  reinterpret_cast<std::uintptr_t>(image.backing),
                                  image.write_seq, u32(image.info.pixel_format),
                                  image.info.size.width, image.info.size.height,
                                  u32(VkImageUsageFlags(image.usage_flags)), bool(image.binding.needs_rebind),
                                  bool(image.scene_proxy), image.guest_begin, image.guest_end,
                                  image.track_addr, image.track_addr_end);
    if (!image.backing) return base + ",?";
    const auto& ci = image.backing->image.image_ci;
    return fmt::format("{},{},{},{},{},{:x},{}", base, u32(ci.format), ci.extent.width, ci.extent.height,
                       u32(ci.samples), u32(VkImageUsageFlags(ci.usage)),
                       u32(image.backing->state.layout));
}
}

std::string Rasterizer::SewerJoinedCopyBefore(VideoCore::ImageId src_id, const VideoCore::Image& src,
                                             VideoCore::ImageId dst_id, const VideoCore::Image& dst) {
    if (!caustics || !caustics->ClaimJoinedBedCopy(src_id)) return {};
    const auto jitter = upscaler->Jitter();
    return fmt::format("{} before={} j_before={:08x},{:08x} src_before={} dst_before={}",
                       caustics->JoinedBedStamp(), caustics->JoinedBedState(),
                       std::bit_cast<u32>(jitter[0]), std::bit_cast<u32>(jitter[1]),
                       JoinedCopyImage(src_id, src), JoinedCopyImage(dst_id, dst));
}

void Rasterizer::SewerJoinedCopyAfter(const std::string& before, VideoCore::ImageId src_id,
                                     const VideoCore::Image& src, VideoCore::ImageId dst_id,
                                     const VideoCore::Image& dst, u64 bytes, bool product_wanted) {
    if (before.empty()) return;
    const auto jitter = upscaler->Jitter();
    std::printf("[sewer-joined-t202] event=copy %s tick=%llu bytes=%llu wanted=%u called=%u "
                "src_after=%s dst_after=%s j_after=%08x,%08x after=%s\n",
                before.c_str(), static_cast<unsigned long long>(scheduler.CurrentTick()),
                static_cast<unsigned long long>(bytes), unsigned(product_wanted), unsigned(product_wanted),
                JoinedCopyImage(src_id, src).c_str(), JoinedCopyImage(dst_id, dst).c_str(),
                std::bit_cast<u32>(jitter[0]), std::bit_cast<u32>(jitter[1]), caustics->JoinedBedState().c_str());
}


bool Rasterizer::SewerReducedBeforeCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                                      VideoCore::ImageId destination, const VideoCore::Image& dst,
                                      u64 bytes) {
    return caustics && caustics->SewerReducedBeforeCopy(source, src, destination, dst, bytes,
                                                       upscaler->Jitter());
}

void Rasterizer::SewerReducedFallbackCopy(VideoCore::ImageId source) {
    if (caustics) caustics->SewerReducedFallbackCopy(source);
}

void Rasterizer::SewerReducedAfterCopy(VideoCore::ImageId source, VideoCore::ImageId destination,
                                       const VideoCore::Image& dst, vk::ImageView sampled, vk::ImageView written) {
    if (caustics) caustics->SewerReducedAfterCopy(source, destination, dst, sampled, written);
}

bool Rasterizer::WantsNativeBedCopy(VideoCore::ImageId src_id) const {
    return caustics && caustics->WantsNativeBedCopy(src_id);
}

void Rasterizer::NoteNativeBedCopy(VideoCore::ImageId src_id, const VideoCore::Image& src,
                                   VideoCore::ImageId dst_id, const VideoCore::Image& dst,
                                   u64 bytes, u64 previous_dst_write) {
    caustics->NoteNativeBedCopy(src_id, src, dst_id, dst, bytes, previous_dst_write,
                                upscaler->Jitter());
}

void Rasterizer::NoteNativeBedDraw(const RenderState& state, const GraphicsPipeline& pipeline,
                                    bool ground, SewerJoinedDraw* joined) {
    if (joined) joined->product_draw = true;
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps || ps->pgm_hash != (ground ? 0xdbb222ebu : 0xa28d2a7au) ||
        pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash !=
            (ground ? 0xc829ee58u : 0xe4680233u)) {
        return;
    }
    const auto& regs = Regs();
    const auto& dynamic = scheduler.GetDynamicState();
    const auto& ds = state.depth_stencil_attachment;
    const char* trace = caustics->TracingNativeBed(db_desc.first) ?
                        (ground ? "ground-raster" : "water-raster") : nullptr;
    const auto gate = [&](bool accepted, const char* predicate) {
        return trace ? caustics->NativeBedTraceGate(accepted, trace, predicate) : accepted;
    };
    if (!gate(bool(db_desc.first), "depth-id-missing") ||
        !gate(camera_motion->Depth() == db_desc.first, "camera-depth-id") ||
        !gate(bool(ds.image_view), "depth-view-missing") || !gate(ds.has_depth, "no-depth-aspect") ||
        !gate(!ds.depth_clear, "depth-clear") || !gate(!ds.stencil_clear, "stencil-clear") ||
        !gate(!Dc().clear_draw, "clear-draw") || !gate(bool(Dc().index_bind.handle), "index-bind") ||
        !gate(state.num_layers == 1, "layer-count") || !gate(!regs.IsClipDisabled(), "clipping-disabled") ||
        !gate(LiverpoolToVK::PrimitiveType(regs.primitive_type) == vk::PrimitiveTopology::eTriangleList,
              "primitive-type") ||
        !gate(!regs.enable_primitive_restart, "primitive-restart") ||
        !gate(dynamic.depth_test_enabled, "depth-test-off") || !gate(dynamic.depth_write_enabled, "depth-write-off") ||
        !gate(dynamic.depth_compare_op == vk::CompareOp::eLessOrEqual, "depth-compare") ||
        !gate(!dynamic.depth_bias_enabled, "depth-bias") ||
        !gate(!dynamic.depth_bounds_test_enabled, "depth-bounds") ||
        !gate(!dynamic.rasterizer_discard_enable, "raster-discard") ||
        !gate(!scene_targets->Reduced(), "reduced-scene")) {
        return;
    }
    const auto& key = pipeline.GetGraphicsKey();
    const auto ground_attachments = [&] {
        if (state.num_color_attachments == 6) return true;
        constexpr u32 slot = Shader::MotionVectors::Output;
        static_assert(slot == 7);
        if (!gate(state.num_color_attachments == slot + 1, "host-colour-attachment-count") ||
            !gate(ps->mrt_mask == 0x3f, "guest-fragment-exports") ||
            !gate(key.mrt_mask == (0x3fu | (1u << slot)) &&
                  key.motion_vectors == Shader::MotionVectors::VertexBoth, "host-motion-specialization") ||
            !gate(!state.color_attachments[6].image_view, "host-slot6-occupied") ||
            !gate(!regs.color_buffers[slot] && !cb_descs[slot].first, "guest-slot7-occupied")) {
            return false;
        }
        const auto owner = object_motion->FindAttachmentOwner(state.width, state.height);
        if (joined) joined->Motion(owner);
        const auto& attachment = state.color_attachments[slot];
        return gate(owner && owner->view && attachment.image_view == owner->view &&
                    owner->written && owner->used_frame == owner->owner_frame &&
                    owner->layout == vk::ImageLayout::eColorAttachmentOptimal &&
                    attachment.image_layout == owner->layout, "host-motion-slot-owner");
    };
    if (ground && (!gate(gbuffer_draw, "not-gbuffer") || !gate(!ps->has_discard, "shader-discard") ||
                   !gate((key.mrt_mask & 0x7f) == 0x3f, "guest-mrt-mask") ||
                   !ground_attachments() ||
                   !gate(bool(state.color_attachments[2].image_view), "cb2-view-missing") ||
                   !gate((u32(VkColorComponentFlags(key.HostWriteMask(2))) & 7u) == 7u, "cb2-rgb-mask") ||
                   !gate(key.logic_op == AmdGpu::ColorControl::LogicOp::Copy, "logic-op") ||
                   !gate(!key.blend_controls[2].enable, "cb2-blend") ||
                   !gate(!std::ranges::any_of(std::span(state.color_attachments).first<6>(),
                                             [](const auto& attachment) { return attachment.is_clear; }),
                         "guest-colour-clear"))) {
        return;
    }
    const auto jitter = Dc().draw_jitter;
    if (!gate(dynamic.viewports.size() == 1, "viewport-count") ||
        !gate(dynamic.scissors.size() == 1, "scissor-count") ||
        !gate(target_scale[0] == 1.0f, "target-scale-x") || !gate(target_scale[1] == 1.0f, "target-scale-y") ||
        !gate(target_offset[0] == 0, "target-offset-x") || !gate(target_offset[1] == 0, "target-offset-y") ||
        !gate(std::abs(jitter[0]) <= 0.5f, "jitter-x") || !gate(std::abs(jitter[1]) <= 0.5f, "jitter-y")) {
        return;
    }
    // The native six-index water draw is unjittered. Ground and the consumer use the frame jitter.
    const auto& v = dynamic.viewports.front();
    const vk::Extent2D extent{state.width, state.height};
    const float width = float(extent.width), height = float(extent.height);
    const bool flip_y = regs.viewports[0].yscale < 0.0f;
    if (!gate(v.x == jitter[0], "viewport-x") ||
        !gate(v.y == (flip_y ? height : 0.0f) + jitter[1], "viewport-y") ||
        !gate(v.width == width, "viewport-width") || !gate(v.height == (flip_y ? -height : height), "viewport-height") ||
        !gate(v.minDepth == 0.0f, "viewport-min-depth") || !gate(v.maxDepth == 1.0f, "viewport-max-depth") ||
        !gate(dynamic.scissors.front() == vk::Rect2D{{0, 0}, extent}, "scissor-rectangle")) {
        return;
    }
    // A same-size redirected attachment can have the native viewport and a different view.
    const auto bound_native = [&](const auto& desc, vk::ImageView bound, bool depth) {
        const auto* image = desc.first ? texture_cache.TryGetImage(desc.first, 0) : nullptr;
        const bool matches = image && image->backing &&
            std::ranges::any_of(image->backing->image_view_ids, [&](auto id) {
                const auto& view = texture_cache.GetImageView(id);
                if (view.image_view.get() != bound) return false;
                if (joined) {
                    auto& observed = depth ? joined->actual_depth : joined->actual_cb2;
                    observed = fmt::format("{}/{}/{:x}:{}", desc.first.index, image->image_uid,
                                           std::bit_cast<u64>(VkImage(image->GetImage())),
                                           SewerJoinedDraw::ViewInfo(view.info));
                }
                return view.info == desc.second.view_info;
            });
        if (joined) (depth ? joined->depth_matches : joined->cb2_matches) = matches;
        return matches;
    };
    if (!gate(bound_native(db_desc, ds.image_view, true), "native-depth-view") ||
        (ground && !gate(bound_native(cb_descs[2], state.color_attachments[2].image_view, false),
                         "native-cb2-view"))) {
        return;
    }
    if (joined) joined->tracker_called = true;
    if (ground) {
        caustics->NoteNativeBedGround(db_desc.first, cb_descs[2].first, extent, jitter);
    } else {
        caustics->NoteNativeBedWater(db_desc.first, extent, upscaler->Jitter());
    }
}

bool Rasterizer::SewerReceiverApply(u64 frame, VideoCore::ImageId depth_id) {
    auto& p = *sewer_receiver;
    if (p.stage_count == 2 && !p.reason && frame == p.frame &&
        object_motion->Frame() == p.identity.scene && depth_id.index == p.identity.image) {
        p.apply_seen = true;
        p.trace.apply = ++p.trace.order;
        return true;
    }
    return false;
}

void Rasterizer::SewerReceiverConsumer(u64 frame, VideoCore::ImageId depth_id,
                                       VideoCore::ImageId albedo_id, VideoCore::Image& depth,
                                       VideoCore::Image* albedo, vk::ImageView depth_view,
                                       vk::ImageView albedo_view, const ::BbCaustics::Push& push,
                                       const std::array<float, 12>& view, bool native) {
    auto& p = *sewer_receiver;
    if (p.reason || p.stage_count != 2 || !p.apply_seen || depth_id.index != p.identity.image ||
        p.frame != frame || object_motion->Frame() != p.identity.scene) {
        return;
    }
    const auto same_source = [&](VideoCore::ImageId id, const VideoCore::Image* image, u32 slot) {
        const auto& source = p.material.sources[slot].backing;
        return image && image->backing && id.index == source.id && image->image_uid == source.uid &&
               texture_cache.IsRegisteredImage(id, source.uid) &&
               std::bit_cast<u64>(VkImage(image->GetImage())) == source.image &&
               u64(reinterpret_cast<std::uintptr_t>(image->backing)) == source.backing &&
               !image->binding.needs_rebind && !image->scene_proxy &&
               !scene_targets->Tracks(source.uid) &&
               image->backing->subresource_states.empty() &&
               image->backing->state.layout == vk::ImageLayout::eGeneral;
    };
    if (!native || !(push.flags & ::BbCaustics::FlagAlbedo) || !depth_view || !albedo_view ||
        camera_motion->Depth() != depth_id ||
        !same_source(depth_id, &depth, RawDepth) || !same_source(albedo_id, albedo, RawAlbedo)) {
        p.reason = "dispatch-binding-1-depth-or-5-albedo-unjoined";
        return;
    }
    if (!(RtLampPane::Camera{view, push.inv_view, push.proj} == p.camera) ||
        push.frame != std::array{float(p.Width), float(p.Height), p.jitter[0], p.jitter[1]} ||
        !std::isfinite(push.sun[3]) || push.inv_view[7] <= push.sun[3] ||
        p.loading != BbEngine::Loading::Generation() || BbEngine::Loading::ScreenUp() ||
        p.scene_generation != scene_targets->Generation() ||
        rt_shadow->WindowDiagnosticFrame() != p.identity.rt) {
        p.reason = "dispatch-camera-frame-or-native-pass-mismatch";
        return;
    }
    // Caustics::CachedView makes identity component mip/layer zero views of these exact images.
    // The dispatch's TexelOf sees the same full native dimensions, so the integer texels agree.
    p.plane_y = push.sun[3];
    p.flags = push.flags;
    p.applied_depth_view = std::bit_cast<u64>(VkImageView(depth_view));
    p.applied_albedo_view = std::bit_cast<u64>(VkImageView(albedo_view));
    const auto offsets = p.Offsets(2);
    RecordDrawRaw({nullptr, albedo, nullptr, &depth}, p.Pixels, vk::Buffer{p.buffer}, offsets);
    auto& t = p.trace;
    t.consumer = ++t.order;
    t.consumer_pass = t.pass;
    t.consumer_write = depth.write_seq;
    const auto& copy = t.copy;
    const VideoCore::ImageId dest_id{copy.destination.id};
    // Use the live registered image without FindTexture, UpdateImage, or a proxy resolve.
    const auto copy_refusal = [&]() -> const char* {
        if (!copy.order) return "no-copy-before-apply";
        if (t.ambiguous) return "multiple-destination-identities";
        if (!copy.native || !copy.enqueued) return "copy-not-native-or-not-enqueued";
        if (t.consumer_pass != t.ground_pass || !p.SameCopyPass(copy) ||
            copy.source != p.ImageKey(depth_id, depth)) {
            return "copy-source-or-pass-mismatch";
        }
        if (!texture_cache.IsRegisteredImage(dest_id, copy.destination.uid)) return "destination-retired";
        auto* dst = texture_cache.TryGetImage(dest_id, copy.destination.uid);
        if (!dst || !dst->backing || !copy.SameDestination(p.ImageKey(dest_id, *dst), dst->write_seq) ||
            dst->binding.needs_rebind ||
            !dst->SafeToDownload() || dst->track_addr != dst->guest_begin ||
            dst->track_addr_end != dst->guest_end || dst->scene_proxy || scene_targets->Tracks(dst->image_uid)) {
            return "destination-rewritten-dirty-or-rebound";
        }
        constexpr auto required = vk::ImageUsageFlagBits::eTransferSrc | vk::ImageUsageFlagBits::eSampled;
        const auto& ci = dst->backing->image.image_ci;
        if (dst->info.pixel_format != vk::Format::eR32Sfloat || ci.format != vk::Format::eR32Sfloat ||
            dst->aspect_mask != vk::ImageAspectFlagBits::eColor ||
            dst->info.resources != VideoCore::SubresourceExtent{1, 1} ||
            ci.mipLevels != 1 || ci.arrayLayers != 1 || ci.samples != vk::SampleCountFlagBits::e1 ||
            ci.extent != vk::Extent3D{p.Width, p.Height, 1} || (ci.usage & required) != required ||
            !dst->backing->subresource_states.empty() ||
            dst->backing->state.layout == vk::ImageLayout::eUndefined) {
            return "destination-format-subresource-or-native-transfer-mismatch";
        }
        const auto aliases = [&](const VideoCore::Image& image, VideoCore::ImageId id) {
            return RtLampPane::MaterialAlias(copy.destination, p.ImageKey(id, image)) ||
                   dst->backing->image.allocation == image.backing->image.allocation;
        };
        if (aliases(depth, depth_id) || aliases(*albedo, albedo_id)) return "destination-aliased";
        bool overlap = false;
        texture_cache.ForEachImageInRegion(copy.destination.begin, copy.bytes,
            [&](VideoCore::ImageId id, VideoCore::Image&) { return overlap = id != dest_id; });
        if (overlap) return "destination-range-overlap";
        RecordDrawRaw({dst, nullptr, nullptr, nullptr}, std::span(p.Pixels).first<p.WetPixels>(),
                      vk::Buffer{p.buffer}, {p.Bytes, 0, 0, 0});
        t.sampled = true;
        return nullptr;
    };
    t.refusal = copy_refusal();
    p.stage_count = 3;
    p.tick = scheduler.CurrentTick();
}

void Rasterizer::SewerReceiverFrameEnd() {
    auto& p = *sewer_receiver;
    if (p.finished) return;
    const u64 scene = object_motion->Frame();
    if (!p.requested) {
        const u32 generation = BbLiveKnobs::Generation();
        if (p.knob_generation != generation) {
            p.knob_generation = generation;
            const auto value = BbLiveKnobs::Lookup("BB_SEWER_RECEIVER_REQUEST");
            if (const char* request = value.Get(); request && std::string_view(request) == "1") {
                p.requested = true;
                p.armed_frame = scene;
                fmt::print("Sewer receiver (t180) armed scene={} first p158 waypoint\n", scene);
            }
        }
        return;
    }
    if (!p.stage_count && !p.reason && scene - p.armed_frame < 90) return;
    if (p.stage_count < 3 && !p.reason) {
        p.reason = !p.stage_count ? "no-exact-draw-at-ready-camera" :
                   p.stage_count == 1 ? "no-exact-after-draw" :
                   p.apply_seen ? "no-matched-ordinary-dispatch" : "no-matched-armed-apply";
    }
    if (p.tick && !scheduler.IsFree(p.tick)) return;
    p.finished = true;
    if (p.stage_count && (p.loading != BbEngine::Loading::Generation() || BbEngine::Loading::ScreenUp())) {
        p.reason = "loading-generation-changed-before-readback";
        p.stage_count = 0;
    }
    if (p.stage_count && (!p.mapped ||
        vmaInvalidateAllocation(instance.GetAllocator(), p.allocation, 0,
                                p.trace.sampled ? p.WitnessBytes : p.Bytes) != VK_SUCCESS)) {
        p.reason = "staging-invalidate-failed";
        p.stage_count = 0;
    }
    fmt::print("Sewer receiver (t180) status={} stages={} reason={} frame={} scene={} rt={} generation={}/{} "
               "readback_tick={} apply_seen={} pair={:08x}:{:08x} indices={} first={} guest_index={:x}\n",
               p.stage_count == 3 ? "complete" : "incomplete", p.stage_count,
               p.reason ? p.reason : "none", p.frame, p.identity.scene, p.identity.rt, p.loading,
               p.scene_generation, p.tick, p.apply_seen, p.Vs, p.Ps, p.Indices, p.First, p.index_base);
    if (p.stage_count) {
        const auto& albedo = p.material.sources[RawAlbedo];
        const auto& depth = p.material.sources[RawDepth];
        fmt::print("Sewer receiver (t180) native={}x{} depth={}/{} image={:x} draw_view={:x} dispatch_view={:x} "
                   "albedo={}/{} image={:x} draw_view={:x} dispatch_view={:x} formats={}/{} flags={:x} plane_y={}\n",
                   p.Width, p.Height, depth.backing.id, depth.backing.uid, depth.backing.image,
                   std::bit_cast<u64>(VkImageView(depth.view)), p.applied_depth_view, albedo.backing.id,
                   albedo.backing.uid, albedo.backing.image, std::bit_cast<u64>(VkImageView(albedo.view)),
                   p.applied_albedo_view, u32(depth.created_format), u32(albedo.created_format), p.flags,
                   p.stage_count == 3 ? p.plane_y : std::numeric_limits<float>::quiet_NaN());
        fmt::print("Sewer receiver (t180) projection_bits={} inverse_bits={} view_bits={} jitter_bits={} "
                   "viewport_bits={} scissor={},{},{},{}\n",
                   Round2FloatWords(p.camera.proj), Round2FloatWords(p.camera.inverse),
                   Round2FloatWords(p.camera.view), Round2FloatWords(p.jitter), Round2FloatWords(p.viewport),
                   p.scissor.offset.x, p.scissor.offset.y, p.scissor.extent.width, p.scissor.extent.height);
        for (u32 i = 0; i < p.Pixels.size(); ++i) {
            const auto pixel = p.Pixels[i];
            u32 before_depth = 0;
            for (u32 stage = 0; stage < p.stage_count; ++stage) {
                constexpr std::array names{"before", "after", "caustics-input"};
                const auto offsets = p.Offsets(stage);
                const auto* bytes = static_cast<const unsigned char*>(p.mapped) + i * p.TexelBytes;
                u32 rgba = 0, raw = 0;
                std::memcpy(&rgba, bytes + offsets[RawAlbedo], sizeof(rgba));
                std::memcpy(&raw, bytes + offsets[RawDepth], sizeof(raw));
                const float depth_value = std::bit_cast<float>(raw);
                const bool valid = std::isfinite(depth_value) && depth_value >= 0.0f && depth_value < 1.0f;
                const auto& proj = p.camera.proj;
                const float z = proj[3] / std::min(depth_value - proj[2], -1e-8f);
                const float vx = ((float(pixel.x) + 0.5f - p.jitter[0]) / float(p.Width) * 2.0f - 1.0f)
                                 * z / proj[0];
                const float vy = ((float(pixel.y) + 0.5f - p.jitter[1]) / float(p.Height) * 2.0f - 1.0f)
                                 * z / proj[1];
                std::array<float, 3> world{};
                for (u32 j = 0; j < world.size(); ++j) {
                    const auto* inv = p.camera.inverse.data() + j * 4;
                    world[j] = valid ? inv[0] * vx + inv[1] * vy + inv[2] * z + inv[3] :
                                       std::numeric_limits<float>::quiet_NaN();
                }
                fmt::print("Sewer receiver (t180) point={} {},{} stage={} rgba8_srgb_le={:08x} d32={:08x} "
                           "domain={} world={:.7g},{:.7g},{:.7g} depth_write={}\n",
                           i < 2 ? "wet" : "dry-control", pixel.x, pixel.y, names[stage], rgba, raw,
                           valid ? "valid" : "clear-or-invalid", world[0], world[1], world[2],
                           stage == 1 ? (raw == before_depth ? "unattributed-unchanged" : "changed-by-draw") : "n/a");
                if (stage == 0) before_depth = raw;
            }
        }
    }
    SewerReceiverCopyReport();
    if (p.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), p.buffer, p.allocation);
        p.buffer = nullptr;
    }
}

void Rasterizer::SewerReceiverCopyReport() {
    const auto& p = *sewer_receiver;
    const auto& t = p.trace;
    const char* order_refusal = t.OrderRefusal();
    const char* contents = "unsampled";
    bool ground = false;
    if (p.stage_count == 3 && t.sampled) {
        const auto word = [&](u64 offset, u32 i) {
            u32 raw = 0;
            const auto* bytes = static_cast<const unsigned char*>(p.mapped);
            std::memcpy(&raw, bytes + offset + i * p.TexelBytes, sizeof(raw));
            return raw;
        };
        const auto height = [&](u32 bits, RawDrawPixel pixel) {
            const float d = std::bit_cast<float>(bits);
            if (!std::isfinite(d) || d < 0.0f || d >= 1.0f) {
                return std::numeric_limits<float>::quiet_NaN();
            }
            const auto& proj = p.camera.proj;
            const float z = proj[3] / std::min(d - proj[2], -1e-8f);
            const float x = ((float(pixel.x) + 0.5f - p.jitter[0]) / float(p.Width) * 2.0f - 1.0f)
                            * z / proj[0];
            const float y = ((float(pixel.y) + 0.5f - p.jitter[1]) / float(p.Height) * 2.0f - 1.0f)
                            * z / proj[1];
            const auto* inv = p.camera.inverse.data() + 4;
            return inv[0] * x + inv[1] * y + inv[2] * z + inv[3];
        };
        ground = true;
        bool water = true;
        for (u32 i = 0; i < p.WetPixels; ++i) {
            const auto pixel = p.Pixels[i];
            const u32 before = word(p.Offsets(0)[RawDepth], i);
            const u32 after = word(p.Offsets(1)[RawDepth], i);
            const u32 applied = word(p.Offsets(2)[RawDepth], i);
            const u32 candidate = word(p.Bytes, i);
            const u32 after_albedo = word(p.Offsets(1)[RawAlbedo], i);
            const u32 applied_albedo = word(p.Offsets(2)[RawAlbedo], i);
            const float ground_y = height(after, pixel), water_y = height(applied, pixel);
            const bool registered = before != after && after > applied && after_albedo != 0 &&
                                    after_albedo == applied_albedo && ground_y < p.plane_y - 0.10f &&
                                    std::abs(water_y - p.plane_y) < 0.01f;
            ground &= registered && candidate == after;
            water &= registered && candidate == applied;
            fmt::print("Sewer copy (t187) scene={} wet={},{} before={:08x} ground={:08x} "
                       "candidate={:08x} apply={:08x} registered={} candidate_y={:.7g}\n",
                       t.scene, pixel.x, pixel.y, before, after, candidate, applied, registered,
                       height(candidate, pixel));
        }
        contents = ground ? "ground" : water ? "water" : "other";
    }
    const bool qualified = p.stage_count == 3 && ground && !order_refusal && !t.refusal;
    fmt::print("Sewer copy (t187) status={} scene={} frame={} rt={} loading={} generation={} "
               "pass={}/{} ground={} water={} apply={} consumer={} contents={} "
               "order_refusal={} ownership_refusal={} witness_refusal={} depth_write_seq={}/{}/{} "
               "readback_tick={} native={}x{} color-mip0-layer0 transform=identity\n",
               qualified ? "existing-copy-qualified" :
                   p.stage_count == 3 ? "retain-ground-fallback" : "witness-incomplete",
               t.scene, p.frame, p.identity.rt, p.loading, p.scene_generation,
               t.ground_pass, t.consumer_pass, t.ground, t.water, t.apply, t.consumer, contents,
               order_refusal ? order_refusal : "none", t.refusal ? t.refusal : "none",
               p.reason ? p.reason : "none", t.ground_write, t.water_write, t.consumer_write,
               p.tick, p.Width, p.Height);
    const auto log = [&](const SewerReceiverProbe::CopyObservation& copy, const char* when) {
        if (!copy.order) return;
        fmt::print("Sewer copy (t187) scene={} {} order={} pass={} tick={} frame={} rt={} loading={} "
                   "generation={} native={} enqueued={} bytes={} source={}/{}:{:x}/{:x}@{:x} "
                   "destination={}/{}:{:x}/{:x}@{:x} write_seq={}/{} jitter={},{}\n",
                   t.scene, when, copy.order, copy.pass, copy.tick, copy.frame, copy.rt, copy.loading,
                   copy.generation, copy.native, copy.enqueued, copy.bytes, copy.source.id,
                   copy.source.uid, copy.source.image, copy.source.backing, copy.source.begin,
                   copy.destination.id, copy.destination.uid, copy.destination.image,
                   copy.destination.backing, copy.destination.begin, copy.src_write, copy.dst_write,
                   copy.jitter[0], copy.jitter[1]);
    };
    log(t.copy, "before-apply");
    log(t.late, "after-apply");
}

void Rasterizer::Round2CaptureFrame(VideoCore::ImageId target) {
    constexpr u32 DefaultFrames = 14, MotionFrames = 96, MotionSeries = 90, MaxInFlight = 3;
    constexpr u32 Width = 1920, Height = 1080;
    constexpr size_t Bytes = size_t(Width) * Height * 4;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    const auto& cfg = Round2ProbeSettings::Get();
    const u32 max_frames = cfg.motion_clip ? MotionFrames : DefaultFrames;
    auto& state = round2_frames;
    const u64 scene = object_motion->Frame(), rt = rt_shadow->WindowDiagnosticFrame();
    const auto reject = [&](u32 ordinal, u32 series, u32 request, const char* reason) {
        std::printf("Round2 frame: {\"schema\":\"round2-native-frame-v1\",\"session\":\"%s\",\"pid\":%d,"
                    "\"status\":\"invalid\",\"reason\":\"%s\",\"ordinal\":%u,\"series\":%u,\"request\":%u,"
                    "\"scene\":%llu,\"rt\":%llu}\n", cfg.session, Round2ProbeSettings::Pid(), reason,
                    ordinal, series, request, static_cast<unsigned long long>(scene), static_cast<unsigned long long>(rt));
    };
    const u32 generation = BbLiveKnobs::Generation();
    if (generation != state.generation) {
        state.generation = generation;
        const auto setting = BbLiveKnobs::Lookup("BB_ROUND2_FRAME_SERIES");
        if (const char* text = setting.Get(); text && *text) {
            std::string_view value(text);
            std::array<u32, 3> words{};
            bool valid = true;
            for (size_t i = 0; i < words.size(); ++i) {
                const auto stop = value.find('/');
                const auto field = value.substr(0, stop);
                const auto [ptr, error] = std::from_chars(field.data(), field.data() + field.size(), words[i]);
                valid &= error == std::errc{} && ptr == field.data() + field.size() &&
                         (stop != std::string_view::npos) == (i + 1 < words.size());
                value = stop == std::string_view::npos ? std::string_view{value.data() + value.size(), 0}
                                                       : value.substr(stop + 1);
            }
            const auto [id, count, stride] = words;
            const bool long_series = count > 8;
            if (!valid || !id || !count || !stride || stride > 30) {
                reject(0, id, 0, "invalid_frame_series");
            } else if (long_series && (!cfg.motion_clip || count != MotionSeries || stride != 1)) {
                reject(0, id, 0, cfg.motion_clip ? "invalid_motion_clip_series" : "invalid_frame_series");
            } else if (id > state.series) {
                if (long_series && state.long_series_used) {
                    reject(0, id, 0, "motion_clip_series_already_used");
                } else if (long_series && state.ordinal + count > max_frames) {
                    reject(0, id, 0, "insufficient_motion_clip_budget");
                } else {
                    if (state.remaining) reject(0, state.series, 0, "series_replaced_before_completion");
                    state.series = id;
                    state.remaining = count;
                    state.stride = stride;
                    state.next_scene = scene;
                    state.long_series_used |= long_series;
                }
            }
        }
    }

    const auto* pick = rt_shadow->ActiveLampPane();
    if (!pick || !pick->Captured() || pick->capture.scene != scene || pick->capture.rt != rt ||
        pick->request.id <= state.last_pick) pick = nullptr;
    const bool series_due = state.remaining && scene >= state.next_scene;
    if (!pick && !series_due) return;
    const u32 request = pick ? pick->request.id : 0;
    const u32 series = series_due ? state.series : 0;
    if (pick) state.last_pick = request;
    if (series_due) {
        --state.remaining;
        state.next_scene = scene + state.stride;
    }
    if (state.ordinal >= max_frames) {
        reject(0, series, request, "frame_budget_exhausted");
        state.remaining = 0;
        return;
    }
    const u32 ordinal = ++state.ordinal;
    const u64 recorder_start = Round2CostStart(cfg.cost);
    const auto matrices = camera_motion->CameraMatrices();
    const auto jitter = camera_motion->Jitter();
    const auto finite = [](const auto& values) {
        return std::ranges::all_of(values, [](float number) { return std::isfinite(number); });
    };
    if (!scene || !rt || !matrices.valid || camera_motion->PreviewFrame() || !finite(matrices.view) ||
        !finite(matrices.inv_view) || !finite(matrices.prev_view) || !finite(matrices.proj) ||
        !finite(matrices.prev_proj) || !finite(jitter) ||
        camera_motion->RenderSize() != std::array<u32, 2>{Width, Height}) {
        reject(ordinal, series, request, "camera_not_native_valid");
        return;
    }
    auto* depth = previous_scene_depth ? texture_cache.TryGetImage(previous_scene_depth, 0) : nullptr;
    auto* image = target ? texture_cache.TryGetImage(target, 0) : nullptr;
    if (!depth || !depth->image_uid || !image || !image->image_uid || !image->backing || scene_targets->Reduced() ||
        !upscaler->Round2NativeLdr(target)) {
        reject(ordinal, series, request, "source_not_native_nondispatched_ldr");
        return;
    }
    if (pick && (pick->capture.image != previous_scene_depth.index || pick->capture.uid != depth->image_uid ||
                 !(RtLampPane::Camera{matrices.view, matrices.inv_view, matrices.proj} == pick->camera) ||
                 pick->jitter != jitter)) {
        reject(ordinal, series, request, "pick_camera_or_depth_mismatch");
        return;
    }
    auto& backing = *image->backing;
    const auto original = backing.state;
    const auto& ci = backing.image.image_ci;
    const auto format = LampMaterialEncoding(image->info.pixel_format);
    if (format == LampMaterialColor::Unsupported || ci.format != image->info.pixel_format ||
        backing.num_samples != 1 || ci.samples != vk::SampleCountFlagBits::e1 ||
        image->aspect_mask != vk::ImageAspectFlagBits::eColor || !backing.subresource_states.empty() ||
        original.layout == vk::ImageLayout::eUndefined || !image->GetImage() ||
        ci.extent.width != Width || ci.extent.height != Height || ci.extent.depth != 1 ||
        image->info.resources != VideoCore::SubresourceExtent{1, 1} ||
        !(ci.usage & vk::ImageUsageFlagBits::eTransferSrc) || (ci.usage & vk::ImageUsageFlagBits::eTransientAttachment)) {
        reject(ordinal, series, request, "unsupported_native_ldr_backing");
        return;
    }
    if (!state.inflight) state.inflight = std::make_shared<Round2FrameReadbacks>();
    constexpr u64 CountUnit = Round2FrameReadbacks::CountUnit;
    if (state.inflight->live.load(std::memory_order_relaxed) / CountUnit >= MaxInFlight) {
        reject(ordinal, series, request, "readback_inflight_limit");
        return;
    }
    const auto allocator = instance.GetAllocator();
    const VkBufferCreateInfo buffer_ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = Bytes,
                                       .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    const VmaAllocationCreateInfo memory{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
    };
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    const u64 allocation_start = Round2CostStart(cfg.cost);
    const auto result = vmaCreateBuffer(allocator, &buffer_ci, &memory, &buffer, &allocation, &info);
    const u64 allocate_ns = Round2CostElapsed(allocation_start);
    const u64 tick = scheduler.CurrentTick();
    u32 live_inflight = 0;
    u64 live_allocated_bytes = 0;
    const auto log_issue = [&](const char* status, u64 record_ns, u64 enqueue_ns, u64 release_ns) {
        const auto print = [](u64 value) { return static_cast<unsigned long long>(value); };
        std::printf("Round2 cost: {\"schema\":\"round2-host-cost-v1\",\"kind\":\"frame\",\"op\":\"issue\","
                    "\"session\":\"%s\",\"pid\":%d,\"ordinal\":%u,\"series\":%u,\"request\":%u,"
                    "\"scene\":%llu,\"rt\":%llu,\"tick\":%llu,\"status\":\"%s\","
                    "\"active_recorder_wall_ns\":%llu,\"allocate_ns\":%llu,\"record_ns\":%llu,\"retirement_enqueue_ns\":%llu,\"release_ns\":%llu,"
                    "\"requested_bytes\":%llu,\"allocated_bytes\":%llu,\"live_count\":%u,"
                    "\"live_payload_bytes\":%llu,\"live_allocated_bytes\":%llu,\"peak_count\":%u,"
                    "\"peak_payload_bytes\":%llu,\"peak_allocated_bytes\":%llu}\n",
                    cfg.session, Round2ProbeSettings::Pid(), ordinal, series, request, print(scene), print(rt),
                    print(tick), status, print(Round2CostElapsed(recorder_start)), print(allocate_ns),
                    print(record_ns), print(enqueue_ns),
                    print(release_ns), print(Bytes), print(info.size), live_inflight,
                    print(live_inflight * Bytes), print(live_allocated_bytes), state.peak_inflight,
                    print(state.peak_inflight * Bytes), print(state.peak_allocated_bytes));
    };
    if (result != VK_SUCCESS) {
        if (cfg.cost) log_issue("frame_staging_allocation", 0, 0, 0);
        reject(ordinal, series, request, "frame_staging_allocation");
        return;
    }
    const u64 charge = CountUnit + (cfg.cost ? info.size : 0);
    if (cfg.cost) {
        const u64 live = state.inflight->live.fetch_add(charge, std::memory_order_relaxed) + charge;
        live_inflight = u32(live / CountUnit);
        live_allocated_bytes = live % CountUnit;
        state.peak_inflight = std::max(state.peak_inflight, live_inflight);
        state.peak_allocated_bytes = std::max(state.peak_allocated_bytes, live_allocated_bytes);
    }
    const auto release = [allocator, buffer, allocation, inflight = state.inflight,
                          cost = cfg.cost, charge](bool counted) {
        const u64 release_start = Round2CostStart(cost);
        vmaDestroyBuffer(allocator, buffer, allocation);
        const u64 release_ns = Round2CostElapsed(release_start);
        if (counted) inflight->live.fetch_sub(charge, std::memory_order_relaxed);
        return release_ns;
    };
    if (!info.pMappedData || !tick) {
        const u64 release_ns = release(cfg.cost);
        if (cfg.cost) log_issue("frame_staging_tick_or_map", 0, 0, release_ns);
        reject(ordinal, series, request, "frame_staging_tick_or_map");
        return;
    }
    const u64 issued = Round2ClockNs();
    const auto sun = sun_term_view ? sun_term_view->Round2Snapshot() : SunTermView::Round2Consumer{};
    const auto id = pick ? pick->capture : RtLampPane::Identity{};
    const auto header = fmt::format(
        "{{\"schema\":\"round2-native-frame-v1\",\"session\":\"{}\",\"pid\":{},\"stage\":\"{}\","
        "\"ordinal\":{},\"series\":{},\"scene\":{},\"rt\":{},\"capture_tick\":{},\"issued_ns\":{},"
        "\"source_id\":{},\"source_uid\":{},\"depth_id\":{},\"depth_uid\":{},\"width\":{},\"height\":{},"
        "\"bytes\":{},\"format\":\"{}\",\"upscaler_dispatched\":false,\"redirected\":false,\"frame_gen\":false,"
        "\"request\":{},\"draw\":{},\"build\":{},\"param\":{},\"camera\":{{\"view\":{},\"inverse\":{},"
        "\"prev_view\":{},\"projection\":{},\"prev_projection\":{},\"jitter\":{}}},\"sun\":{{\"present\":{},"
        "\"on\":{},\"failed\":{},\"have_term\":{},\"frame\":{},\"captures\":{},\"shows\":{},"
        "\"show_id\":{},\"show_uid\":{}}}",
        cfg.session, Round2ProbeSettings::Pid(), Round2FrameStage, ordinal, series, scene, rt, tick, issued,
        target.index, image->image_uid, previous_scene_depth.index, depth->image_uid, Width, Height, Bytes,
        LampMaterialEncodingLabel(format), request, id.draw, id.build, pick ? pick->param : 0,
        Round2FloatWords(matrices.view), Round2FloatWords(matrices.inv_view), Round2FloatWords(matrices.prev_view),
        Round2FloatWords(matrices.proj), Round2FloatWords(matrices.prev_proj), Round2FloatWords(jitter),
        sun.present, sun.on, sun.failed, sun.have_term, sun.frame, sun.captures, sun.shows, sun.show_id, sun.show_uid);
    const auto stem = fmt::format("{}/{}-frame-{:02d}", cfg.directory, cfg.session, ordinal);

    scheduler.EndRendering();
    runtime.FlushBarriers();
    VideoCore::Image::Barriers before, after;
    const auto handle = image->GetImage();
    image->GetBarriers(before, vk::ImageLayout::eTransferSrcOptimal, Access::eTransferRead, Stage::eCopy);
    image->GetBarriers(after, original.layout, original.access_mask, original.pl_stage);
    auto* profiler = cfg.cost ? GpuProfiler::Get() : nullptr;
    const auto previous = profiler && profiler->Records(&scheduler) ?
        profiler->BeginRound2Copy(GpuProfiler::Round2Copy::Frame) : std::nullopt;
    const u64 record_start = Round2CostStart(cfg.cost);
    scheduler.Record([handle, buffer,
                      copy = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(before.data(), before.size())),
                      restore = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(after.data(), after.size()))]
                     (vk::CommandBuffer cmd) {
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = u32(copy.size()), .pImageMemoryBarriers = copy.data()});
        const vk::BufferImageCopy region{.imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                                         .imageExtent = {Width, Height, 1}};
        cmd.copyImageToBuffer(handle, vk::ImageLayout::eTransferSrcOptimal, buffer, region);
        const vk::MemoryBarrier2 host{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferWrite,
                                      .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead};
        cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &host,
                              .imageMemoryBarrierCount = u32(restore.size()), .pImageMemoryBarriers = restore.data()});
    });
    const u64 record_ns = Round2CostElapsed(record_start);
    if (previous) {
        profiler->Resume(*previous);
    }
    if (!cfg.cost) state.inflight->live.fetch_add(charge, std::memory_order_relaxed);
    const u64 enqueue_start = Round2CostStart(cfg.cost);
    scheduler.DeferPriorityOperation([allocator, allocation, mapped = info.pMappedData, release, stem, header,
                                      cost = cfg.cost, session = cfg.session, ordinal, series, request,
                                      scene, rt, tick, allocated_bytes = info.size] {
        const u64 retired = Round2ClockNs();
        const bool mapped_ok = vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE) == VK_SUCCESS;
        const u64 invalidate_ns = cost ? Round2ClockNs() - retired : 0;
        const auto raw = stem + ".rgba";
        const u64 raw_start = Round2CostStart(cost && mapped_ok);
        const bool raw_ok = mapped_ok && Round2Write(raw, mapped, Bytes);
        const u64 complete = Round2ClockNs();
        const u64 raw_write_ns = raw_start ? complete - raw_start : 0;
        const auto sidecar = fmt::format("{},\"status\":\"ok\",\"retired_ns\":{},\"image_written_ns\":{}}}\n",
                                         header, retired, complete);
        const u64 sidecar_start = Round2CostStart(cost && raw_ok);
        const bool sidecar_ok = raw_ok && Round2Write(stem + ".json", sidecar.data(), sidecar.size());
        const u64 sidecar_write_ns = Round2CostElapsed(sidecar_start);
        const char* failure = mapped_ok ? "frame_artifact_write" : "frame_staging_invalidate";
        if (sidecar_ok) {
            std::printf("Round2 frame: %s", sidecar.c_str());
        } else {
            if (raw_ok) std::remove(raw.c_str());
            const auto invalid = fmt::format("{},\"status\":\"invalid\",\"reason\":\"{}\"}}\n", header, failure);
            std::printf("Round2 frame: %s", invalid.c_str());
        }
        const u64 release_ns = release(true);
        if (cost) {
            const auto print = [](u64 value) { return static_cast<unsigned long long>(value); };
            std::printf("Round2 cost: {\"schema\":\"round2-host-cost-v1\",\"kind\":\"frame\",\"op\":\"retire\","
                        "\"session\":\"%s\",\"pid\":%d,\"ordinal\":%u,\"series\":%u,\"request\":%u,"
                        "\"scene\":%llu,\"rt\":%llu,\"tick\":%llu,\"status\":\"%s\","
                        "\"invalidate_ns\":%llu,\"raw_write_ns\":%llu,\"sidecar_write_ns\":%llu,"
                        "\"release_ns\":%llu,\"retire_wall_ns\":%llu,\"requested_bytes\":%llu,\"allocated_bytes\":%llu}\n",
                        session, Round2ProbeSettings::Pid(), ordinal, series, request, print(scene), print(rt),
                        print(tick), sidecar_ok ? "ok" : failure, print(invalidate_ns), print(raw_write_ns),
                        print(sidecar_write_ns), print(release_ns), print(Round2CostElapsed(retired)),
                        print(Bytes), print(allocated_bytes));
        }
    });
    const u64 retirement_enqueue_ns = Round2CostElapsed(enqueue_start);
    if (cfg.cost) log_issue("ok", record_ns, retirement_enqueue_ns, 0);
}

#include "video_core/renderer_vulkan/vk_workflow_probe.inl"

#ifdef BB_TEST_SHARED_POST_GRAPH
static BottleMotion203::Slots PostImageSlots(const GraphicsPipeline& pipeline,
                                               std::span<const vk::WriteDescriptorSet> writes, u64 scope) {
    namespace Graph = BottleAncestry;
    BottleMotion203::Slots result{};
    std::size_t cursor = 0;
    for (const auto* stage : pipeline.GetStages()) {
        if (!stage) continue;
        const auto count = stage->buffers.size() + stage->images.size() + stage->samplers.size();
        if (cursor > writes.size() || count > writes.size() - cursor) {
            ++result.omitted;
            break;
        }
        const auto rows = writes.subspan(cursor, count);
        const bool ordered = std::ranges::all_of(rows, [&](const auto& write) {
            return write.dstBinding == cursor + (&write - rows.data()) && write.descriptorCount == 1 && !write.pNext;
        });
        const auto type = stage->sw_stage == Shader::SwStage::Fragment ? Graph::BindStage::Fragment
                                                                      : Graph::BindStage::Unknown;
        // These are the typed slot requests at the ordinary binder, before any device-commit proof.
        const auto snapshot = BottleMotion203::CopySlots(rows,
            {type, 0, scope, ordered ? Graph::Proof::Known : Graph::Proof::Unknown});
        for (std::size_t i = 0; i < snapshot.count; ++i) result.Add(snapshot.images[i]);
        result.omitted += snapshot.omitted + !ordered;
        cursor += count;
    }
    if (cursor != writes.size()) ++result.omitted;
    return result;
}
#endif

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
struct BottleSet0Draw {
    vk::PipelineLayout layout{};
    vk::ImageView output{}, ui{}, lut{};
    vk::Sampler sampler{};
    bool physical{}, depth_bounds{}, depth_attachment{}, standard_sample_locations{};
    explicit operator bool() const { return layout && output; }
};

static void ReportBottleSet0Draw(Scheduler& scheduler, BottleDisplay182::DescriptorTicket& ticket,
                                vk::CommandBuffer command, const BottleSet0Draw& fact) {
    const auto* worker = NativeWriteSuffix::worker_segment;
    const auto position = BottleDisplay182::NoteOrigin(scheduler, ticket, command,
        worker ? worker->scheduler : nullptr, worker ? worker->buffer : vk::CommandBuffer{},
        worker ? worker->tick : 0, worker ? worker->segment : 0);
    const auto actual = ticket.NoteDraw(position, fact.layout, fact.output, fact.ui, fact.lut, fact.sampler,
                                       fact.physical);
    const auto bind = ticket.Commit();
    const auto& key = ticket.key;
    const auto& seen = bind.actual;
    fmt::print("[bottle-cut] event=prepared-set0-encoded request={} scene={} frame={} epoch={} address={:x} "
               "route={} point=graphics set_index=0 set={:x} expected_layout={:x} bind_layout={:x} draw_layout={:x} "
               "timeline={:x} bind_cmd={:x} draw_cmd={:x} bind_tick={} draw_tick={} bind_segment={} draw_segment={} "
               "bind_worker={} draw_worker={} planned_count={} planned_mask={:x} planned_valid={} "
               "actual_count={} actual_mask={:x} actual_valid={} stage_match={} clip_disabled={} encoded={} ordered={} "
               "operands={} ancillary={} physical={} coexisting={} depth_bounds_enabled={} depth_attachment={} "
               "standard_sample_locations={} "
               "planned_ui={:x}/{} planned_lut={:x}/{} planned_sampler={:x} planned_clip={:x}/{}/{} "
               "ui={:x}/{} lut={:x}/{} sampler={:x} clip={:x}/{}/{} output={:x} texture_version=unknown\n",
               key.request, key.scene, key.frame, key.epoch, key.address, BottleDisplay182::Wire(bind.route),
               std::bit_cast<u64>(bind.set), std::bit_cast<u64>(ticket.layout), std::bit_cast<u64>(bind.layout),
               std::bit_cast<u64>(fact.layout), std::bit_cast<u64>(ticket.timeline),
               std::bit_cast<u64>(bind.origin.command), std::bit_cast<u64>(command), bind.origin.tick,
               actual.origin.tick, bind.origin.segment, actual.origin.segment, bind.origin.worker, actual.origin.worker,
               ticket.planned.count, ticket.planned.mask, ticket.planned.valid, seen.count, seen.mask, seen.valid,
               ticket.stage_match, ticket.clip_disabled, bind.encoded, actual.ordered, actual.operands,
               actual.ancillary, actual.physical,
               actual.ordered && actual.operands && actual.ancillary && actual.physical,
               fact.depth_bounds, fact.depth_attachment, fact.standard_sample_locations,
               std::bit_cast<u64>(ticket.planned.images[0].imageView), u32(ticket.planned.images[0].imageLayout),
               std::bit_cast<u64>(ticket.planned.images[1].imageView), u32(ticket.planned.images[1].imageLayout),
               std::bit_cast<u64>(ticket.planned.images[2].sampler), std::bit_cast<u64>(ticket.planned.clip.buffer),
               ticket.planned.clip.offset, ticket.planned.clip.range,
               std::bit_cast<u64>(seen.images[0].imageView), u32(seen.images[0].imageLayout),
               std::bit_cast<u64>(seen.images[1].imageView), u32(seen.images[1].imageLayout),
               std::bit_cast<u64>(seen.images[2].sampler), std::bit_cast<u64>(seen.clip.buffer),
               seen.clip.offset, seen.clip.range, std::bit_cast<u64>(actual.output));
}

#endif

void Rasterizer::DrawRecord(const GraphicsPipeline* pipeline, const PreparedDraw* used_prepared,
                            bool is_indexed, u32 index_offset) {
    auto& dc = Dc();
    BB_SECTION(DrawRecord);
    const auto& regs = Regs();
    std::optional<ReflectionFirstRetire::Scope> retire_scope;
    ReflectionFirstRetire::Row* retire = nullptr;
    if (is_indexed && ReflectionNativeProbe::Witness(regs.num_indices) != ReflectionNativeProbe::NoWitness &&
        ReflectionFirstRetire::On()) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const ReflectionNativeProbe::Key key{pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
            ps ? ps->pgm_hash : 0, regs.num_indices, index_offset};
        if (ReflectionNativeProbe::Match(key) != ReflectionNativeProbe::NoWitness) {
            retire_scope.emplace(this, &scheduler, key, BbEngine::Loading::Generation(), scheduler.CurrentTick());
            retire = ReflectionFirstRetire::Current(this);
            if (retire) {
                const auto& graphics = pipeline->GetGraphicsKey();
                retire->source = reinterpret_cast<uintptr_t>(pipeline);
                retire->source_key = std::hash<GraphicsPipelineKey>{}(graphics);
                retire->source_vs = graphics.stage_hashes[u32(Shader::SwStage::Vertex)];
                retire->source_ps = graphics.stage_hashes[u32(Shader::SwStage::Fragment)];
                retire->clip = regs.clipper_control.user_clip_plane_enable;
                retire->depth = u32(regs.depth_control.depth_enable) |
                    (u32(regs.depth_control.depth_write_enable) << 1) |
                    (u32(regs.depth_control.depth_func) << 2);
                for (u32 i = 0; i < std::size(regs.blend_control); ++i) {
                    retire->blend |= u32(regs.blend_control[i].enable) << i;
                }
            }
        }
    }
    buffer_cache.NewPacket();
    if (DrawPipe::OnStageB()) {
        FrameCapture::Poll();
        scheduler.PopPendingOperations();
    }
    // bbport: under SET_PREDICATION on a block known to read occluded (vk_occlusion.h).
    if (occlusion && occlusion->SkipDraw()) {
        if (retire) retire->issue = "predication-skipped";
        return;
    }
    // bbport (BB_PREUPLOAD): once a frame, guest GPU memory the CPU wrote and then left alone is
    // uploaded ahead of its use, BB_PREUPLOAD_MB (16) at most per frame.
    if (const u32 frame = BbStats::frame_number.load(std::memory_order_relaxed);
        frame != preupload_frame) {
        preupload_frame = frame;
        BB_SECTION(Preupload);
        static const u64 budget = [] {
            const char* env = std::getenv("BB_PREUPLOAD_MB");
            return (env ? std::strtoull(env, nullptr, 10) : 16ull) << 20;
        }();
        buffer_cache.Preupload(budget);
    }
    // bbport: the pass copying a finished frame to a display buffer; the previous draw's
    // target is that frame.
    if (regs.color_buffers[0] &&
        FrameCapture::IsDisplayBuffer(regs.color_buffers[0].Address())) {
        depth_of_field->Reset();
        // bbport (r77_parallel-test-runs): clean shot is taken for the whole next frame, whose
        // world is not drawn yet
        if (clean_shot_frame) {
            CleanShotTally(clean_shot_state.phase); // bbport (r102b_camera-clean-hud)
        }
        clean_shot_frame = clean_shot.load(std::memory_order_relaxed);
        clean_shot_state = {};
    }
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    BottleDisplay182::DescriptorKey set0_key{};
    u64 set0_load{}, set0_targets{}, set0_object{};
#endif
    if (camera_motion->Enabled() && regs.color_buffers[0] &&
        FrameCapture::IsDisplayBuffer(regs.color_buffers[0].Address())) {
        scene_started = false;
        // bbport: native HDR output: the gain map of the frame this pass copies, for this
        // display buffer (before OnFrameStart forgets the frame's UI phase).
        point_shadow->TagColourProbeDisplay(regs.color_buffers[0].Address());
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        const bool bottle_already_pending = upscaler->BottlePreparedPending();
        if (upscaler->BottleRawSearchRequested()) {
            const auto source = BottleColdSource177::CloseBeforeDisplay(
                *this, scheduler, *scene_targets, *rt_shadow, *object_motion, *camera_motion,
                *upscaler, texture_cache);
            upscaler->BottleObserveRawSearch(source ? &*source : nullptr);
            if (!bottle_already_pending && source && source->ordinary_read && source->first_epoch &&
                source->first_epoch == source->last_epoch) {
                set0_key = {source->frame.request, source->frame.draw_frame, source->source.key.scene,
                            source->first_epoch, regs.color_buffers[0].Address()};
                set0_load = source->frame.load;
                set0_targets = source->frame.targets;
                set0_object = source->frame.object_frame;
            }
        }
#endif
        upscaler->OnDisplayPass(regs.color_buffers[0].Address(), cb_descs[0].first);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (set0_key && !upscaler->BottlePreparedPending()) set0_key = {};
#endif
        previous_scene_depth = camera_motion->Depth(); // the last G-buffer pass's (bbport)
        camera_motion->OnDisplayPass(cb_descs[0].first);
        if (Round2ProbeSettings::Get().frames) Round2CaptureFrame(cb_descs[0].first);
        if (workflow) WorkflowNative(cb_descs[0].first);
        // bbport (r23_spike-trace): stage B's frame end, its 600-frame reports and the GPU
        // profile print (NoteFrameStart) included
        const u64 r23_end_start = BbSpike::on ? BbSpike::NowNs() : 0;
        // bbport (r29_bursts): the reports printed with BbReport::Printf below are written on
        // bb:Stats (experiment 9007199254740992 set: here, as before).
        const BbReport::Capture r29_reports;
        if (sewer_receiver) SewerReceiverFrameEnd();
        if (caustics) caustics->ResetNativeBedPass();
        EffectsOnFrameEnd();
        if (upscaler->OnFrameStart()) {
            object_motion->InvalidateHistory();
            camera_motion->InvalidateHistory();
        }
        camera_motion->SetJitter(upscaler->Jitter());
        object_motion->OnFrameStart();
        NoteFrameStart();
        if (r23_end_start != 0) { // bbport (r23_spike-trace)
            BbSpike::stage_b_end_ns.fetch_add(BbSpike::NowNs() - r23_end_start,
                                              std::memory_order_relaxed);
        }
        static const char* scene_debug = std::getenv("BB_SCENE_DEBUG");
        scene_debug_frame = scene_debug && std::remove(scene_debug) == 0;
        scene_targets->debug = scene_debug_frame;
    }
    // bbport (r7_cascades): a draw into a sun cascade kept from an earlier frame is left out
    // before its targets, bindings, barriers and pass (SunHoldEarly, vk_rasterizer_effects.cpp).
    if (sun_hold.active && SunHoldEarly(pipeline)) {
        return;
    }
    // bbport (r77_parallel-test-runs): clean shot leaves the game's HUD and menus out the same
    // way. Off: one test of a plain bool per draw.
    if (clean_shot_frame && CleanShotEarly(pipeline)) {
        return;
    }
    dc.bind_prepared = used_prepared;
    dc.motion_draw = (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
    dc.capture_draw = (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::VertexCapture) != 0;
    dc.motion_geometry = 0;

    PrepareRenderState(pipeline);
    NotifyUiDraw(pipeline);
    if (glass_registry) { // bbport (r129a_glass-registry): off: this null test alone
        GlassRegistryDraw(pipeline, is_indexed, index_offset);
    }
    EffectsBeforeResources(pipeline);
    std::optional<BloodPoolProbe::BoundIndex> blood_index;
    if (blood_pool_probe && gbuffer_draw && is_indexed &&
        blood_pool_probe->WantsBoundIndex(regs.num_indices, index_offset)) {
        blood_index.emplace();
    }
    dc.blood_index = blood_index ? &*blood_index : nullptr;
    std::unique_ptr<IvyMaterialProbe::Snapshot> ivy;
    if (blood_pool_probe && is_indexed && index_offset == IvyMaterialProbe::First &&
        regs.num_indices == IvyMaterialProbe::Count && !ivy_material_recorded &&
        ivy_material_attempts < IvyMaterialProbe::AttemptLimit && IvyMaterialProbe::Wanted()) {
        const auto token = blood_pool_probe->FoliageNoteToken(is_indexed, index_offset);
        const auto* fs = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (token && token->selected && !token->camera_gbuffer && fs &&
            blood_pool_probe->IvyOwnerAllows(*token) &&
            IvyMaterialProbe::Matches(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                      fs->pgm_hash, index_offset, regs.num_indices, is_indexed)) {
            ++ivy_material_attempts;
            ivy = std::make_unique<IvyMaterialProbe::Snapshot>();
            ivy->serial = token->serial;
            ivy->frame = token->frame;
            ivy->ordinal = token->ordinal;
        }
    }
    const PreparedDraw* draw_prepared = dc.bind_prepared;
    // bbport: vertex and index buffers are resolved while the helper binds textures (their
    // commands are recorded after BeginRendering, as before).
    dc.draw_inputs = {pipeline, draw_prepared, index_offset, is_indexed, true, false};
    std::optional<ReflectionNativeProbe::Draw> native_proof;
    using namespace ReflectionNativeProbe;
    if (reflection_probe && gbuffer_draw && is_indexed &&
        Witness(regs.num_indices) != NoWitness && (On() || ReflectionFirstHit::PlacedOn())) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const Key key{pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps ? ps->pgm_hash : 0,
                      regs.num_indices, index_offset};
        const u32 target = Match(key);
        if (target != NoWitness && On()) {
            auto& pace = reflection_native_pace[target];
            const u64 phase = reflection_probe->last_request;
            const u64 frame = rt_shadow->WindowDiagnosticFrame();
            const u64 generation = BbEngine::Loading::Generation();
            if (pace.phase != phase) {
                if (pace.retries) {
                    NativeFollowupStatus(target, frame, pace.phase, "phase-ended");
                }
                pace.phase_used = 0;
                pace.phase = phase;
                pace.retry_until = 0;
                pace.retries = 0;
            }
            if (pace.retries && (frame > pace.retry_until || generation != pace.retry_generation ||
                                 BbEngine::Loading::ScreenUp())) {
                NativeFollowupStatus(target, frame, phase, frame > pace.retry_until ?
                                     "retry-window-expired" : "load-changed");
                pace.retries = 0;
            }
            const bool followup = pace.retries != 0;
            const bool steady = !NativeFollowupTarget(target) && pace.phase_used < 3 &&
                                frame >= pace.frame && frame - pace.frame >= 45;
            const bool due = (followup || !pace.phase_used || steady) &&
                             (!pace.total || frame > pace.frame);
            if (due) {
                if (pace.total == NativeSampleLimit) {
                    if (!pace.cap_logged) {
                        NativeFollowupStatus(target, frame, phase, "target-sample-limit");
                        pace.cap_logged = true;
                    }
                    pace.retries = 0;
                } else {
                    const auto reserved = std::ranges::count_if(reflection_native_pace, [&](const auto& other) {
                        return &other != &pace && other.phase == phase && other.retries &&
                               other.retry_generation == generation &&
                               other.total < NativeSampleLimit && frame > other.frame &&
                               frame <= other.retry_until;
                    });
                    const auto available = std::ranges::count_if(reflection_native_slots, [](const auto& slot) {
                        return !slot.tick;
                    });
                    // A busy follow-up still observes ordinary capture provenance through t160.
                    // The existing readback path reports ring-busy and touches no occupied slot.
                    if (followup || reserved == 0 || available > reserved) {
                        pace.frame = frame;
                        ++pace.phase_used;
                        ++pace.total;
                        if (followup) {
                            --pace.retries;
                        }
                        native_proof.emplace();
                        native_proof->key = key;
                        native_proof->trace = true;
                        native_proof->serial = ++reflection_native_serial;
                    }
                }
            }
        }
        if (target != NoWitness && !native_proof && ReflectionFirstHit::PlacedOn()) {
            native_proof.emplace();
            native_proof->key = key;
        }
    }
    if (native_proof && ReflectionNativeProbe::ExactEquivalenceOn()) {
        native_proof->exact.emplace();
    }
    dc.reflection_native = native_proof ? &*native_proof : nullptr;
    SCOPE_EXIT {
        dc.reflection_native = nullptr;
        dc.blood_index = nullptr;
        if (dc.wall_stream.receipt && !dc.wall_stream.checked) {
            std::printf("Reflection wall stream event=no-preflight packet=%u\n",
                        dc.wall_stream.receipt->packet);
        }
        dc.wall_stream.receipt = nullptr;
    };
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::shared_ptr<SewerBridge::PostDraw> post_draw;
    std::optional<VideoCore::PostGeometry::DrawWatch> post_watch;
    if (upscaler->HasSewerBridge()) {
        const auto* fs = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        post_draw = upscaler->SewerBeginPostDraw(object_motion->Frame(), fs ? fs->pgm_hash : 0,
                                               cb_descs[0].first, &buffer_cache);
        if (post_draw) {
            const auto& native = pipeline->GetGraphicsKey();
            post_draw->vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
            post_draw->vs_permutation = native.stage_hashes[u32(Shader::SwStage::Vertex)];
            post_draw->ps_permutation = native.stage_hashes[u32(Shader::SwStage::Fragment)];
        }
        if (post_draw && post_draw->geometry) {
            post_watch.emplace(&buffer_cache, post_draw->geometry, post_draw->geometry_key);
            post_draw->watch = &*post_watch;
        }
    }
    dc.shared_post = post_draw.get();
    SCOPE_EXIT {
        if (post_draw) post_draw->watch = nullptr;
        dc.shared_post = nullptr;
    };
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    std::optional<BottleDisplay182::Draw> bottle_operands;
    if (upscaler->BottlePreparedPending() && regs.color_buffers[0] &&
        FrameCapture::IsDisplayBuffer(regs.color_buffers[0].Address())) {
        const auto* fs = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (fs && fs->pgm_hash == BottleDisplay182::Fragment) bottle_operands.emplace();
    }
    dc.bottle_display_operands = bottle_operands ? &*bottle_operands : nullptr;
#endif
    dc.ivy_material = ivy.get();
    const bool bound = BindResources(pipeline);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    dc.bottle_display_operands = nullptr;
#endif
    dc.ivy_material = nullptr;
    dc.bind_prepared = nullptr; // indirect draws and dispatches bind without prepared sharps
    const bool inputs_resolved = dc.draw_inputs.resolved;
    dc.draw_inputs.pending = false;
    if (!bound) {
        if (retire) retire->issue = "resources-skipped";
        return;
    }
    // bbport (r104_cloud-probe): TOOL, BB_CLOUD_PROBE=1 only; reads the sky dome draw's inputs
    if (cloud_probe_on) {
        CloudProbe::OnDraw(regs, *pipeline, dc.bound_images.data(), dc.bound_images.size(),
                           texture_cache, *memory);
    }
    const bool sky_resolved =
        SkyBeforeRendering(regs, pipeline, is_indexed, index_offset, draw_prepared, inputs_resolved);
    if (foliage_mask) {
        FoliageCheckReceivers(); // shader storage bindings may have written the receivers
    }
    if (native_proof) {
        ReflectionNativeBeforeDraw(*native_proof);
    }
    auto state = BeginRendering(pipeline);
    const auto original_foliage_state = foliage_mask ? state : RenderState{};
    if (ProxyTraceOn()) {
        const auto target = cb_descs[0].first ? cb_descs[0].first : db_desc.first;
        FlushProxyReads(dc.push_data.scene_size != 0,
                        target ? &texture_cache.GetImage(target) : nullptr);
    }

    if (!inputs_resolved && !sky_resolved) {
        ResolveVertexBuffers(pipeline, draw_prepared);
        if (is_indexed) {
            ResolveIndexBuffer(index_offset);
        }
    }
    EmitVertexBuffers();
    if (is_indexed) {
        EmitIndexBuffer();
    }

    if (dc.needs_barrier) {
        runtime.FlushBarriers();
    }

    // bbport: screen-space (clip disabled) draws into the upscaler's output-size images.
    dc.push_data.xscale *= target_scale[0];
    dc.push_data.xoffset = dc.push_data.xoffset*target_scale[0]+target_offset[0];
    dc.push_data.yscale *= target_scale[1];
    dc.push_data.yoffset = dc.push_data.yoffset*target_scale[1]+target_offset[1];
    r19_motion.valid = false; // bbport (r19_draw-cost): set by this draw's Motion block only
    u32 sway = 0, draw_motion_slot = 0;
    if (dc.motion_draw && dc.motion_geometry) {
        BB_SECTION(Motion);
        const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
        const auto [base_vertex, first_instance] =
            GetDrawOffsets(regs, vs, pipeline->GetFetchShader());
        const u32 index_size =
            regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
        const VAddr index_address = is_indexed
            ? regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size : 0;
        // Without a character-size skeleton the draw is gated on its bone palette changing
        // since last frame (model constants follow the camera, the palette does not). The
        // check comes first: most gated draws are static world pieces with long index lists.
        static const bool all_motion = [] {
            const char* value = std::getenv("BB_OBJECT_MOTION_ALL");
            return value && value[0] == '1';
        }();
        bool gated = !all_motion;
        Motion::Kind r34_kind = Motion::Kind::Other; // bbport (r34_motion-store)
        bool r19_complete = true; // bbport (r19_draw-cost): the walk below ran to its end
        u64 palette = 0;
        for (const auto& resource : vs.buffers) {
            if (resource.IsSpecial()) continue;
            const auto buffer = resource.GetSharp(vs);
            const u32 size = buffer.GetSize();
            if (!buffer.Valid() || buffer.GetStride() != 16) continue;
            const auto role = Motion::ClassifyBuffer(size);
            if (role == Motion::BufferRole::Skeleton) {
                gated = false;
                r34_kind = Motion::Kind::Skinned; // bbport (r34_motion-store)
                r19_complete = false;
                break;
            }
            const VAddr address = buffer.base_address;
            if (role == Motion::BufferRole::SmallSkeleton &&
                buffer_cache.IsRegionGpuModified(address, size)) {
                gated = false;
                r34_kind = Motion::Kind::GpuPalette; // bbport (r34_motion-store)
                r19_complete = false;
                break;
            }
            if (role == Motion::BufferRole::SmallSkeleton &&
                memory->IsValidGpuMapping(address, 0) &&
                memory->ClampRangeSize(address, size) == size) {
                palette = XXH3_64bits_withSeed(reinterpret_cast<const void*>(address), size,
                                               palette);
            }
        }
        const u32 instances = regs.num_instances.NumInstances();
        const u64 index_bytes = u64(regs.num_indices) * index_size;
        const bool indices_valid = is_indexed && index_address &&
                                   memory->IsValidGpuMapping(index_address, 0) &&
                                   memory->ClampRangeSize(index_address, index_bytes) == index_bytes;
        r19_motion = {true, indices_valid, r19_complete, palette}; // bbport (r19_draw-cost)
        if (BbWindTwigs::TreesWanted()) { // bbport (r89j_twigs-pick-trees): this draw's index range, for WindTreesDraw
            trees_draw = {index_address, regs.num_indices, s32(base_vertex), index_size, indices_valid};
        }
        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): the counters the word below moves
            hang_route_before = WindHangRouteMark();
        }
        if ((pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::GameCut) != 0) { // bbport (r122_game-wind-drive)
            BbWindGame::Count().draws.fetch_add(1, std::memory_order_relaxed);
        }
        // bbport (r89_wind-foliage-sway): a plant's sway word (WindSwayWord); 0 for every other
        // draw, and with the knob off no pipeline has the Sway bit
        sway =
            r34_kind == Motion::Kind::Skinned &&
                    (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0
                ? WindSwayWord(pipeline)
                // bbport (r112i_hang-find-lanterns): an opaque static draw of a sway pipeline may hang
                : ((r34_kind == Motion::Kind::Other || r34_kind == Motion::Kind::GpuPalette) &&
                   BbWindHangFind::WantedCut((pipeline->GetGraphicsKey().motion_vectors &
                                              Shader::MotionVectors::Sway) != 0,
                                             pipeline->GetStages()[u32(Shader::SwStage::Fragment)]) &&
                   // bbport (r112k_hang-lantern-verdict): a GPU-palette draw only when its stream is a hanging
                   // candidate (BB_WIND_HANG_STATIC_GPU); any other falls to the twig rule below as before
                   // bbport (r112l_hang-discard-lanterns): so does a draw of a pipeline whose pixel shader discards
                   // (a cut-out lantern or cage; WantedCut lets it through with BB_WIND_HANG_STATIC_CUT): only an
                   // opaque static draw (Kind::Other) goes on without that question
                   ((r34_kind == Motion::Kind::Other &&
                     !BbWindHangFind::Cuts(pipeline->GetStages()[u32(Shader::SwStage::Fragment)])) ||
                    WindHangGpuStatic(pipeline)))
                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0, true)
                // bbport (r89e_twigs-big-trees): a static cut-out (Kind::Other) is a candidate for the
                // twigs (BB_WIND_TWIGS_SMALL); the palette flag says it read a small bone palette
                : (r34_kind == Motion::Kind::Other && BbWindTwigs::ReachSmall() &&
                   (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0)
                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0)
                // bbport (r89i_twigs-colour-pass): a cut-out whose small bone palette the GPU writes is a twig
                // candidate too (BB_WIND_TWIGS_PALETTE): the rule of the static cut-outs above
                : (r34_kind == Motion::Kind::GpuPalette && BbWindCensus::PaletteOn() &&
                   (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0)
                    ? WindSwayWord(pipeline, 1)
                // bbport (r89d_tree-twigs): 0, counting (twigs on) the draws the sway cannot reach
                : WindTwigSkip(r34_kind == Motion::Kind::Skinned,
                               (pipeline->GetGraphicsKey().motion_vectors &
                                Shader::MotionVectors::Sway) != 0);
        if (BbWindTrees::PickOn()) { // bbport (r89j_twigs-pick-trees, TOOL): the pick names this draw's kind and word
            trees_pick_note = {r34_kind == Motion::Kind::Skinned
                                   ? 0
                                   : (r34_kind == Motion::Kind::GpuPalette ? 1 : 2),
                                   sway};
        }
        if (BbWindCensus::CensusOn()) { // bbport (r89i_twigs-colour-pass, TOOL): this draw's row
            WindTwigCensus(pipeline, regs, is_indexed, index_offset,
                           r34_kind == Motion::Kind::Skinned
                               ? int(BbWindCensus::KindSkinned)
                               : (r34_kind == Motion::Kind::GpuPalette ? int(BbWindCensus::KindPalette)
                                                                       : int(BbWindCensus::KindStatic)),
                               sway, int(base_vertex));
        }
        dc.push_data.motion_param = draw_motion_slot = object_motion->Draw({
            .draw = {.shader = vs.pgm_hash,
                     .geometry = dc.motion_geometry,
                     .indices = index_address,
                     .index_count = regs.num_indices,
                     .instances = instances,
                     .first_instance = first_instance},
            .gate = {.shader = vs.pgm_hash,
                     .geometry = dc.motion_geometry,
                     .indices = index_address,
                     .index_count = regs.num_indices,
                     .instances = instances,
                     .first_instance = first_instance},
            .palette = palette,
            .index_address = index_address,
            .base_vertex = s32(base_vertex),
            .index_size = is_indexed ? index_size : 0u,
            .gated = gated,
            .restart = regs.enable_primitive_restart != 0,
            .indices_valid = indices_valid,
            .kind = r34_kind, // bbport (r34_motion-store)
            .sway = sway,     // bbport (r89_wind-foliage-sway)
        });
        if (BbWindHangFind::FindOn()) { // bbport (r112k_hang-lantern-verdict, TOOL grade): the survey's route
            WindHangFindRoute(pipeline,
                              r34_kind == Motion::Kind::Skinned
                                  ? 'S'
                                  : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                              sway, dc.push_data.motion_param != 0);
        }
        if (BbWindHangRoute::On()) { // bbport (r112q_hang-bracket-route, TOOL): this draw's pair of shaders, kind, word and delivery
            WindHangRouteNote(pipeline,
                              r34_kind == Motion::Kind::Skinned
                                  ? 'S'
                                  : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                              sway, dc.push_data.motion_param != 0);
        }
        if (BbWindHang::ProofOn() || BbWindHangRoute::On()) { // bbport (r112r_hang-bracket-judge, TOOL): the pair's hang words counted, the hide flag
            hang_proof_hide = WindHangProofDraw(pipeline,
                                                r34_kind == Motion::Kind::Skinned
                                                    ? 'S'
                                                    : (r34_kind == Motion::Kind::GpuPalette ? 'P' : 'O'),
                                                sway, dc.push_data.motion_param != 0);
        }
        if (sway != 0 && dc.push_data.motion_param == 0) { // bbport (r112h_hang-not-the-hunter)
            ++hang_actors.no_param; // the word got no motion parameter: it never reaches the shader
        }
    }
    if (BbWindTrees::PickOn() && !(dc.motion_draw && dc.motion_geometry)) { // bbport (r89j_twigs-pick-trees, TOOL)
        trees_pick_note = {3, 0u};
    }
    if (BbWindCensus::CensusOn() && !(dc.motion_draw && dc.motion_geometry)) { // bbport (r89i_twigs-colour-pass, TOOL)
        WindTwigCensus(pipeline, regs, is_indexed, index_offset, int(BbWindCensus::KindNone), 0u,
                       int(GetDrawOffsets(regs, pipeline->GetStage(Shader::SwStage::Vertex),
                                          pipeline->GetFetchShader()).first));
    }
    if (window_receiver || window_cold_pane.Active()) {
        NoteWindowPaneDraw(regs, pipeline, is_indexed, index_offset);
    }
    // Associate the later vkCmdDraw delivery with the invocation that latched the build.
    const auto* owner_candidate = window_receiver && window_receiver->pane && window_receiver->pane->owner &&
        !window_receiver->pane->natural.Latched() ? window_receiver->pane.get() : nullptr;
    u32 capture_word = 0;
    RtShadow::BottleDrawToken bottle_draw;
    RtShadow::ReflectionDrawToken reflection_draw;
    const auto wall_descriptor_current = [&] {
        const auto& bound = dc.wall_stream;
        const auto& write = dc.set_writes[bound.write_index];
        return write.dstBinding == bound.slot && write.pBufferInfo &&
               *write.pBufferInfo == bound.descriptor;
    };
    if (auto* receipt = dc.wall_stream.receipt) {
        const auto& bound = dc.wall_stream;
        const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
        const u64 generation = BbEngine::Loading::Generation();
        const bool descriptor = bound.origin5 && bound.slot == 23 && wall_descriptor_current() &&
            receipt->Match(bound.descriptor.buffer, bound.descriptor.offset, bound.descriptor.range,
                           bound.adjust, bound.guest, generation);
        const bool completed = receipt->CompletedBeforePreflight();
        const auto& stamp = native_proof->stamp;
        const bool qualified = dc.capture_draw && native_proof->stamped && native_proof->placement_safe &&
            stamp.frame == rt_shadow->WindowDiagnosticFrame() && stamp.generation == generation &&
            !BbEngine::Loading::ScreenUp();
        const bool guest_clean = qualified && descriptor && memory->IsValidGpuMapping(receipt->guest, receipt->Bytes) &&
            memory->IsValidMapping(receipt->guest, receipt->Bytes) &&
            !buffer_cache.IsRegionGpuModified(receipt->guest, receipt->Bytes);
        u64 payload_digest = 0, guest_digest = 0;
        bool equal = false;
        if (completed && guest_clean) {
            std::array<u8, VideoCore::BufferCache::WallStreamProbe::Bytes> guest;
            std::memcpy(guest.data(), reinterpret_cast<const void*>(receipt->guest), guest.size());
            payload_digest = XXH3_64bits(receipt->owned.data(), receipt->owned.size());
            guest_digest = XXH3_64bits(guest.data(), guest.size());
            equal = guest == receipt->owned;
        }
        dc.wall_stream.checked = true;
        std::printf("Reflection wall stream event=preflight packet=%u stage_a=%s route=%s "
                    "generation=%llu reserved_generation=%llu frame=%llu pass=%llu "
                    "source=%llx binding_source=%llx buffer=%llx offset=%llu bytes=%u tick=%llu "
                    "cache_generation=%llu "
                    "bound=%llx bound_offset=%llu bound_range=%llu slot=%u adjust=%u origin5=%u "
                    "descriptor=%u completed=%u stamp=%u guest_clean=%u equal=%u digest=%016llx/%016llx\n",
                    receipt->packet, WallRingReasonName(dc.wall_stream_reason),
                    VideoCore::BufferCache::WallStreamRoute(receipt->route), u(generation),
                    u(receipt->generation), u(stamp.frame), u(stamp.pass), u(receipt->guest), u(bound.guest),
                    u(std::bit_cast<u64>(receipt->handle)), u(receipt->offset), receipt->Bytes, u(receipt->tick), u(receipt->cache_generation),
                    u(std::bit_cast<u64>(bound.descriptor.buffer)), u(bound.descriptor.offset),
                    u(bound.descriptor.range), bound.slot, bound.adjust, u32(bound.origin5),
                    u32(descriptor), u32(completed), u32(qualified), u32(guest_clean), u32(equal),
                    u(payload_digest), u(guest_digest));
    }
    vk::Pipeline classified_stock;
    auto original_stock_role = ReflectionDiscard::StockRole::None;
    if (dc.capture_draw) {
        const auto admit = [&](bool accepted, const char* name) {
            if (!accepted && retire) retire->admission = name;
            return accepted;
        };
        BB_SECTION(RtCapture);
        // Ivy is specific to its own material key, and the bottle and sewer samplers
        // require different geometry. The lamp sampler and a pending window owner can
        // be armed independently of this geometry, so leave those invocations alone.
        if (admit(bool(native_proof), "native-probe-absent") &&
            admit(ReflectionFirstHit::On(), "master-off") &&
            admit(ReflectionFirstHit::PlacedOn(), "placed-off")) {
            const auto role = ReflectionDiscard::StockRoleForWitness(Match(native_proof->key));
            if (admit(role != ReflectionDiscard::StockRole::None, "role-uncertified")) {
                const auto* lamp = rt_shadow->ActiveLampPane();
                if (admit(!foliage_mask, "foliage") && admit(!ivy, "ivy") &&
                    admit(!hang_proof_hide, "hang-hide") && admit(!trees_pick_draw, "tree-pick") &&
                    admit(!(occlusion && occlusion->Measuring()), "occlusion") &&
                    admit(!(workflow && workflow->querying), "workflow-query") &&
                    admit(!(lamp && lamp->material_enabled), "lamp-material") &&
                    admit(!owner_candidate, "window-owner") &&
                    admit(!sun_atlas.address || (db_desc.first &&
                        texture_cache.GetImage(db_desc.first).info.guest_address != sun_atlas.address),
                        "sun-atlas")) {
                    original_stock_role = role;
                    if (retire) retire->admission = "passed";
                }
            }
        }
        EffectsCaptureDraw(regs, pipeline, is_indexed, index_offset, bottle_draw, reflection_draw,
                           original_stock_role, classified_stock);
        capture_word = dc.push_data.motion_param;
    }
    const bool owner_latched_here = owner_candidate && owner_candidate->natural.Latched();
    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: the shader pairs of forward blended draws
    // (colour target 0 blended, 1 or 2 targets, a depth target, neither the G-buffer nor a sun
    // shadow pass), for the r83b line when no named pair is seen (rt_glass_probe.h). Off: one
    // test of a static bool.
    static const bool glass_probe_forward = RtGlass().on;
    if (glass_probe_forward && !gbuffer_draw && regs.depth_buffer.DepthValid() &&
        regs.blend_control[0].enable &&
        !(regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
          regs.depth_buffer.Height() >= 1024)) {
        const auto targets = std::popcount(pipeline->GetGraphicsKey().mrt_mask);
        const auto* glass_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (glass_ps && targets >= 1 && targets <= 2) {
            RtGlassProbe::NoteForward(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                      glass_ps->pgm_hash,
                                      regs.depth_control.depth_write_enable != 0);
        }
    }
    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1 (rt_glass_find.h): every forward draw (not the
    // G-buffer, not a sun shadow pass) that is blended on colour target 0 or in the BB_RT_GLASS list,
    // counted by its shader pair, for the log. Off: one test of a static bool.
    static const bool glass_find = RtGlassFind::On();
    if (glass_find && !gbuffer_draw &&
        !(regs.depth_buffer.DepthValid() && regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
          regs.depth_buffer.Height() >= 1024)) {
        const auto* find_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const u64 find_vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
        const bool find_listed = find_ps && RtGlassMatch(find_vs, find_ps->pgm_hash);
        if (find_ps && (regs.blend_control[0].enable || find_listed)) {
            const vk::Rect2D find_box = DrawScissor(0);
            RtGlassFind::DrawNote note;
            note.vs = find_vs;
            note.ps = find_ps->pgm_hash;
            note.index_count = regs.num_indices;
            note.instances = regs.num_instances.NumInstances();
            note.targets = u32(std::popcount(pipeline->GetGraphicsKey().mrt_mask));
            note.flags = (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite
                                                                      : RtGlassFind::FlagNoZWrite) |
                         (regs.depth_control.depth_enable != 0 ? RtGlassFind::FlagZTest : 0u) |
                         (find_ps->has_discard ? RtGlassFind::FlagDiscard : 0u) |
                         (!find_ps->images.empty() ? RtGlassFind::FlagTextured : 0u) |
                         (find_listed ? RtGlassFind::FlagListed : 0u) |
                         (dc.capture_draw ? RtGlassFind::FlagCapture : 0u) |
                         (dc.motion_geometry != 0 ? RtGlassFind::FlagGeometry : 0u) |
                         // bbport (r86h_glint-camera): inside the scene's frame or after it (the HUD), camera voted
                         (scene_started ? RtGlassFind::FlagScene : RtGlassFind::FlagAfter) |
                         (rt_shadow->GlassCameraKnown() ? RtGlassFind::FlagVoted : 0u);
            note.x0 = find_box.offset.x;
            note.y0 = find_box.offset.y;
            note.x1 = find_box.offset.x + s32(find_box.extent.width);
            note.y1 = find_box.offset.y + s32(find_box.extent.height);
            RtGlassFind::NoteDraw(note);
        }
    }
    // bbport (r86i_glint-find-gbuffer): BB_GLASS_FIND=1: the draws of the scene's frame the block above leaves
    // out (every G-buffer draw, forward draws that are not blended), counted by shader pair with what the pixel
    // shader reads: the area lines (rt_glass_find.h). Off: the static bool above.
    if (glass_find && scene_started &&
        (gbuffer_draw || !(regs.depth_buffer.DepthValid() && regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
                           regs.depth_buffer.Height() >= 1024))) {
        const auto* area_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (area_ps && (gbuffer_draw || !regs.blend_control[0].enable)) {
            bool area_cube = false; // the material hint: the game's glossy surfaces read an environment cube map
            for (const auto& image : area_ps->images) {
                area_cube = area_cube || image.post_op == Shader::SharpFetchPostOp::ConvertCubeTo2DArray ||
                            image.GetSharp(*area_ps).IsCube();
            }
            RtGlassFind::DrawNote area_note;
            area_note.vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
            area_note.ps = area_ps->pgm_hash;
            area_note.index_count = regs.num_indices;
            area_note.instances = regs.num_instances.NumInstances();
            area_note.targets = u32(std::popcount(pipeline->GetGraphicsKey().mrt_mask));
            area_note.flags = (gbuffer_draw ? RtGlassFind::FlagGBuffer : 0u) |
                              (regs.blend_control[0].enable ? RtGlassFind::FlagBlend : 0u) |
                              (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite
                                                                          : RtGlassFind::FlagNoZWrite) |
                              (regs.depth_control.depth_enable != 0 ? RtGlassFind::FlagZTest : 0u) |
                              (area_ps->has_discard ? RtGlassFind::FlagDiscard : 0u) |
                              (!area_ps->images.empty() ? RtGlassFind::FlagTextured : 0u) |
                              (area_cube ? RtGlassFind::FlagCube : 0u) |
                              (dc.capture_draw ? RtGlassFind::FlagCapture : 0u);
            RtGlassFind::NoteArea(area_note, u32(area_ps->images.size()));
        }
    }
    // bbport (r64_surface-probe): BB_SURFACE_PROBE=1: what this draw is (its targets, blend,
    // depth, textures and whether the ray traced scene took it), for the log only. Here the
    // textures are bound and the capture has answered; nothing of the draw is changed.
    if (surface_probe_on) {
        SurfaceProbeDraw(pipeline, false);
    }
    if (spark_probe_on) { // bbport (r108_spark-probe, TOOL): BB_SPARK_PROBE=1, log only
        SparkProbeDraw(pipeline, false);
    }
    if (blood_pool_probe) { // bbport (r100d_blood-pool-draws, TOOL): the draw's indices and textures
        BloodPoolProbeNote(pipeline, false, is_indexed, index_offset);
    }
    effect_skip_draw = hang_proof_hide; // bbport (r112r_hang-bracket-judge, TOOL): BB_WIND_HANG_PROOF_HIDE leaves a hang-word draw out
    if (retire) retire->draw_flags |= u32(hang_proof_hide) << 8;
    hang_proof_hide = false;
    if (effects_wanted) {
        const auto [effect_first_vertex, effect_first_instance] =
            GetDrawOffsets(regs, pipeline->GetStage(Shader::SwStage::Vertex), pipeline->GetFetchShader());
        effect_pass = vk::Extent2D{state.width, state.height};
        // Two single-layer colour attachments, neither cleared by this pass.
        effect_plain_pair = state.num_color_attachments == 2 && state.num_layers == 1 &&
                            !state.color_attachments[0].is_clear &&
                            !state.color_attachments[1].is_clear;
        BbSections::Scope effects_bind_scope{BbSections::EffectsBind};
        EffectsBeforeBind(regs, pipeline, is_indexed, index_offset, effect_first_vertex);
        effects_bind_scope.End();
        // bbport: lamps apart (vk_point_shadow.h): this lamp quad goes into the lamp images, with
        // the pipeline, depth and pass size it has.
        if (const auto lamps = point_shadow->TakeLampTargets()) {
            for (u32 i = 0; i < 2; ++i) {
                state.color_attachments[i].image_view = (*lamps)[i];
                state.color_attachments[i].image_layout = vk::ImageLayout::eGeneral;
            }
        }
    }
    // bbport (r131c_cabinet-glass-clear): the cabinet's pane draw is recorded into side images (vk_glass_clear.h): the attachments of
    // `state` are swapped, the pipeline, pass and draw are the game's. dc.clear_draw is false while no GlassClear is made.
    if (dc.clear_draw && upscaler->Enabled()) {
        const auto& depth_state = regs.depth_control;
        const u32 func = u32(depth_state.depth_func);
        const u32 depth_mode =
            !depth_state.depth_enable || !depth_state.depth_write_enable                                    ? 2u
            : func == u32(AmdGpu::CompareFunc::Less) || func == u32(AmdGpu::CompareFunc::LessEqual)         ? 0u
            : func == u32(AmdGpu::CompareFunc::Greater) || func == u32(AmdGpu::CompareFunc::GreaterEqual)   ? 1u
                                                                                                          : 2u;
        const bool stencil_func =
            depth_state.stencil_enable && regs.depth_buffer.StencilValid() &&
            (depth_state.stencil_ref_func != AmdGpu::CompareFunc::Always ||
             (depth_state.backface_enable && depth_state.stencil_bf_func != AmdGpu::CompareFunc::Always));
        glass_clear->Redirect(state, cb_descs[0].first, cb_descs[2].first, db_desc.first, depth_mode, stencil_func,
                              pipeline->GetGraphicsKey());
    }
    const auto* fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const auto* raster_pipeline = foliage_mask
        ? FoliageAttach(pipeline, original_foliage_state, state, FoliageBoundary::Source::Direct)
        : pipeline;
    const bool tagged_foliage = raster_pipeline != pipeline && FoliageClass(*pipeline, is_indexed, index_offset);
    const float froyok_blend = fragment ? froyok_bloom->Composite(*fragment, dc.image_infos) : 0.0f;
    if (BbWindParticles::On()) { // bbport (r122b_game-particles-follow-wind): this draw's lean word
        WindGameParticlesDraw(pipeline, fragment);
    }
    BbSections::Scope descriptor_scope{BbSections::PipelineBind};
    const u64 r21_serial = scheduler.R21Serial(); // bbport (r21_draw-sort): R21Restore below
    const u32 ordinary_motion = dc.push_data.motion_param;
    const u32 motion_mode = pipeline->GetGraphicsKey().motion_vectors;
    if (bottle_draw.private_param && !rt_shadow->BottleCapturePending(bottle_draw.private_param)) {
        bottle_draw.private_param = 0;
    }
    if (bottle_draw.private_param) {
        const bool both = Shader::MotionVectors::Kind(motion_mode) == Shader::MotionVectors::VertexBoth;
        dc.push_data.motion_param = both ? (ordinary_motion & 0xffffu) | (bottle_draw.private_param << 16)
                                         : bottle_draw.private_param;
    }
    if (Object3::On()) {
        const auto* row = ReflectionFirstRetire::Current(this);
        auto& chosen = Object3::state.chosen;
        if (row && chosen.active && chosen.draw.sequence == row->sequence) {
            const auto& bound = chosen.draw.object3;
            const auto& write = dc.set_writes[bound.write_index];
            chosen.bound_match &= raster_pipeline == pipeline && Ordinal3Stages(*raster_pipeline) &&
                write.descriptorType == vk::DescriptorType::eUniformBuffer && write.descriptorCount == 1 &&
                write.dstBinding == bound.slot && write.dstArrayElement == 0 && write.pBufferInfo &&
                std::bit_cast<u64>(write.pBufferInfo->buffer) == bound.handle &&
                write.pBufferInfo->offset == bound.offset && write.pBufferInfo->range == bound.range &&
                dc.push_data.buf_offsets[bound.push_index] == bound.adjust;
        }
    }
    const bool wall_descriptor_submitted = dc.wall_stream.receipt && wall_descriptor_current();
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (post_draw) {
        post_draw->slots = PostImageSlots(*raster_pipeline, dc.set_writes, post_draw->geometry_key.draw);
        post_draw->snapshots_complete = !post_draw->slots.omitted;
        if (post_draw->watch) {
            using namespace VideoCore::PostGeometry;
            for (u32 slot = 0; slot < UniformSlots; ++slot) {
                auto& row = post_draw->bytes[PacketSlot(Use::Uniform, slot)];
                if (!row.ticket) continue;
                if (row.descriptor_write >= dc.set_writes.size() ||
                    row.push_index >= dc.push_data.buf_offsets.size()) {
                    row.state = State::Mismatch;
                    continue;
                }
                const auto& write = dc.set_writes[row.descriptor_write];
                const u64 relative = u64(row.adjust) + row.member;
                if (!write.pBufferInfo || write.dstBinding != row.native_slot || write.dstArrayElement ||
                    write.descriptorCount != 1 || write.descriptorType != vk::DescriptorType::eUniformBuffer ||
                    *write.pBufferInfo != row.descriptor || dc.push_data.buf_offsets[row.push_index] != row.adjust ||
                    row.adjust % sizeof(u32) || row.descriptor.range == VK_WHOLE_SIZE ||
                    relative + row.binding.bytes > row.descriptor.range ||
                    row.descriptor.offset > std::numeric_limits<u64>::max() - relative ||
                    row.descriptor.offset + relative != row.binding.offset) {
                    row.state = State::Mismatch;
                    continue;
                }
                if (row.route == Route::ConstantRing) {
                    const auto actual = Backing{constant_ring.get(), std::bit_cast<u64>(constant_ring->Handle()),
                        reinterpret_cast<u64>(constant_ring->Allocation()), row.binding.backing.cache_generation};
                    if (actual != row.binding.backing ||
                        row.binding.backing.cache_generation >= dc.ring_packet_end ||
                        dc.ring_packet_end - row.binding.backing.cache_generation > ConstantRing::Capacity) {
                        row.state = State::Mismatch;
                        continue;
                    }
                } else {
                    row.binding.backing.cache_generation = buffer_cache.StructureGeneration();
                }
                row.binding.tick = scheduler.CurrentTick();
                row.binding.backing.handle = std::bit_cast<u64>(write.pBufferInfo->buffer);
                row.state = post_draw->watch->Join(row.ticket, row.binding);
            }
        }
        upscaler->SewerPostBindings(*post_draw, dc.bound_images);
    }
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (bottle_operands) {
        auto& observation = *bottle_operands;
        observation.scene_size = dc.push_data.scene_size;
        observation.viewport_push = {dc.push_data.xoffset, dc.push_data.xscale,
                                     dc.push_data.yoffset, dc.push_data.yscale};
    }
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    std::shared_ptr<BottleDisplay182::DescriptorTicket> set0;
    if (set0_key && bottle_operands && raster_pipeline == pipeline) {
        using namespace BottleDisplay182;
        const auto* live = raster_pipeline->BottleDisplayProgram();
        const auto stages = raster_pipeline->GetStages();
        const auto* ps = stages[u32(Shader::SwStage::Fragment)];
        const auto* vs = stages[u32(Shader::SwStage::Vertex)];
        constexpr std::array pins{std::pair{0x231a69d38cc8164cull, 3620u}, std::pair{0x45626c2011285b9full, 2300u},
                                  std::pair{0x498e23ba19976658ull, 956u}, std::pair{0xadf4b0832c8f0f36ull, 4084u}};
        const bool effective = live && pipeline_cache.CaptureProofUnchanged() &&
            std::ranges::equal(live->stages, pins, [](const auto& stage, const auto& pin) {
                return bool(stage) && stage.digest == pin.first && stage.bytes == pin.second;
            });
        const bool ps_shape = ps && ps->pgm_hash == Fragment && ps->buffers.empty() && ps->images.size() == 2 &&
            ps->samplers.size() == 1 && std::ranges::none_of(ps->images, &Shader::ImageResource::is_written);
        const bool vs_shape = vs && vs->pgm_hash == Vertex && vs->images.empty() && vs->samplers.empty() &&
            vs->buffers.size() == 1 && !vs->buffers[0].is_written && !vs->buffers[0].is_uniform &&
            vs->buffers[0].buffer_type == Shader::BufferType::ClipPlanes;
        set0 = std::make_shared<DescriptorTicket>(set0_key, raster_pipeline->GetLayout(), &scheduler,
            scheduler.GetWorkSemaphore()->Handle(), InspectSet0(dc.set_writes), effective && ps_shape && vs_shape,
            regs.clipper_control.user_clip_plane_enable == 0);
    }
#endif
    raster_pipeline->BindResources(dc.set_writes, dc.push_data,
                                   {dc.image_infos.data(), dc.image_infos.size()},
                                   {dc.buffer_infos.data(), dc.buffer_infos.size()}, froyok_blend
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
                                   , set0
#endif
                                   );
    if (bottle_draw.private_param) {
        dc.push_data.motion_param = ordinary_motion;
    }
    if (ivy) {
        const auto push = IvyMaterialProbe::ObjectBytes(dc.push_data);
        std::ranges::copy(push, ivy->push.begin());
        ivy->push_size = push.size();
    }
    if (raster_pipeline != pipeline) {
        scheduler.Record([raster_pipeline, tagged_foliage](vk::CommandBuffer cmd) {
            raster_pipeline->PushFoliageClass(cmd, tagged_foliage);
        });
    }
    if (dc.capture_draw) {
        rt_shadow->BindAddresses(raster_pipeline->GetLayout(), motion_mode, bottle_draw.private_param);
    } else if (dc.motion_draw) {
        object_motion->BindAddresses(raster_pipeline->GetLayout());
    }
    descriptor_scope.End();
    // bbport (r21_draw-sort): push constants and descriptor binds leave vertex input, vertex
    // buffer and index buffer binds as they are.
    if (!bottle_draw.private_param) {
        scheduler.R21Restore(r21_serial);
    }
    // bbport: jitter geometry drawn with the scene depth, not full-screen passes (a shifted
    // full-screen quad leaves an edge column unwritten).
    dc.draw_jitter = {};
    if (upscaler->Enabled() && db_desc.first && db_desc.first == camera_motion->Depth() &&
        (regs.num_indices > 6 || regs.num_instances.NumInstances() > 1)) {
        dc.draw_jitter = upscaler->Jitter();
    }
    UpdateDynamicState(raster_pipeline, is_indexed);
    MarkPass(pipeline, state);
    if (sun_hold.active) {
        SunHoldBeforePass(state); // bbport (r7_cascades): may narrow the atlas's clear
    }
    if (SunKeepGate()) {
        // bbport (r14_cascade_keep): may take the atlas's clear of the whole image over.
        SunKeepBeforePass(state, false);
    }
    scheduler.BeginRendering(state);
    if (sun_hold.atlas_pass) {
        SunHoldInPass(state);
    }
    if (sun_keep.atlas_pass) {
        SunKeepInPass(state); // r14: the draw's quadrant cleared before the first draw into it
    }
    if (effect_skip_draw) {
        if (retire) retire->issue = "effect-skipped";
        // bbport: as for a pipeline still compiling (below): targets, barriers and the pass ran,
        // only the draw is left out (SsrTemporal::OnSsrDraw).
        effect_skip_draw = false;
        ResetBindings(false);
        scheduler.KickRecording();
        return;
    }
    if (SunAtlasSkipDraw(pipeline, state)) {
        if (retire) retire->issue = "sun-atlas-skipped";
        // bbport: a sun atlas cascade nothing samples this frame (vk_rasterizer_effects.cpp):
        // as above, only the draw is left out.
        ResetBindings(false);
        scheduler.KickRecording();
        return;
    }

    const auto& vs_info = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch_shader = pipeline->GetFetchShader();
    const auto [vertex_offset, instance_offset] = GetDrawOffsets(regs, vs_info, fetch_shader);

    // bbport (docs/pipeline_compiles.md): a pipeline still compiling does not hold this thread
    // (nor the GPU command thread and the guest threads that drain behind it): the draw is left
    // out (scene geometry) or a recording thread binds the pipeline once it is there.
    // Everything above ran as for a draw (targets, barriers, render pass): only the draw itself
    // is missing for those frames.
    vk::Pipeline handle = raster_pipeline->HandleIfReady();
    if (!handle) [[unlikely]] {
        if (SkipUncompiledDraw(pipeline)) {
            if (retire) retire->issue = "uncompiled-skipped";
            // bbport (r47_still-check): what this draw was to store for ray tracing
            // (EffectsCaptureDraw, above) is not stored
            if (dc.capture_draw) {
                rt_shadow->CaptureLeftOut(dc.push_data.motion_param,
                                          pipeline->GetGraphicsKey().motion_vectors);
            }
            ResetBindings(false);
            scheduler.KickRecording();
            return;
        }
        handle = BindWhenCompiled(raster_pipeline, vk::PipelineBindPoint::eGraphics);
    }
    if (raster_pipeline != pipeline) {
        foliage_mask->NoteClass(tagged_foliage);
        ++mask_draws;
        mask_tags += tagged_foliage;
        if (pipeline_cache.BoundaryProbe().Active()) {
            FoliageObserveDraw(pipeline, FoliageBoundary::Source::Direct, tagged_foliage);
        }
    }
    const u32 num_indices = regs.num_indices;
    const u32 num_instances = regs.num_instances.NumInstances();
    const u32 first_vertex = vertex_offset;
    const u32 first_instance = instance_offset;
    const auto* ps_info = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const Breadcrumbs::Crumb crumb{
        .kind = is_indexed ? Breadcrumbs::Kind::DrawIndexed : Breadcrumbs::Kind::Draw,
        .hash = {vs_info.pgm_hash, ps_info ? ps_info->pgm_hash : 0},
        .program = {vs_info.ProgramBase(), ps_info ? ps_info->ProgramBase() : 0},
        .count = {num_indices, num_instances, 0},
    };
    // bbport: after a ZPASS dump the draw is measured by an occlusion query around just this
    // vkCmdDraw (inside the open render pass; vk_occlusion.h).
    auto query = occlusion ? occlusion->BeginDraw(dc.push_data.scene_size)
                           : Occlusion::DrawQuery{};
    if (sun_reader.measure_now) {
        // bbport (r12_atlas_skip_live): a water draw sampling the sun atlas gets an occlusion
        // query of its own (SunAtlasReaderQuery, vk_rasterizer_effects.cpp).
        SunAtlasReaderQuery(query.pool, query.index);
    }
    if (trees_pick_draw) { // bbport (r89j_twigs-pick-trees, TOOL): this draw's query, for the pick (r86l: forward draws too)
        trees_pick_indexed = is_indexed;
        WindTreesPickQuery(pipeline, regs, index_offset, s32(vertex_offset), query.pool, query.index);
    }
    LampPaneProbe* material_probe = rt_shadow->ActiveLampPane();
    const LampMaterialDelivery material_draw{pipeline, raster_pipeline, handle, index_offset,
                                             first_vertex, first_instance, is_indexed};
    if (!material_probe || !material_probe->material_enabled || !material_probe->Captured() ||
        material_probe->seen_frame != material_probe->capture.scene ||
        material_probe->ordinal != material_probe->capture.draw ||
        !LampMaterialSample(*material_probe, state, material_draw, false)) {
        material_probe = nullptr;
    }
    const bool owner_sample = owner_latched_here && !material_probe &&
        SampleWindowOwner(state, material_draw, false);
    std::unique_ptr<IvySampleWitness::Sample> ivy_sample;
    constexpr u32 ivy_ps = u32(Shader::SwStage::Fragment);
    const u64 ivy_stage = ivy ? raster_pipeline->GetGraphicsKey().stage_hashes[ivy_ps] : 0;
    const u64 ivy_module = ivy ? raster_pipeline->IvyFragmentModule() : 0;
    if (ivy) {
        const auto& dynamic = scheduler.GetDynamicState();
        const auto draw_jitter = dc.draw_jitter;
        const bool jitter_ok = std::isfinite(draw_jitter[0]) && std::isfinite(draw_jitter[1]) &&
            std::abs(draw_jitter[0]) <= 0.5f && std::abs(draw_jitter[1]) <= 0.5f;
        const bool scope_ok = handle && raster_pipeline == pipeline && !material_probe && !owner_sample &&
            !gbuffer_draw && !dc.clear_draw && !attachment_feedback_loop && !scene_targets->Reduced() &&
            jitter_ok &&
            state.width == IvySampleWitness::Width && state.height == IvySampleWitness::Height &&
            state.num_layers == 1 && state.num_color_attachments == 1 &&
            state.color_attachments[0].image_view && state.depth_stencil_attachment.has_depth &&
            state.depth_stencil_attachment.image_view && scheduler.IsRenderingWith(state) &&
            dynamic.depth_test_enabled && dynamic.depth_write_enabled &&
            dynamic.depth_compare_op == vk::CompareOp::eLessOrEqual && !dynamic.depth_bias_enabled &&
            !dynamic.depth_bounds_test_enabled && !dynamic.stencil_test_enabled &&
            !dynamic.rasterizer_discard_enable &&
            num_instances == 1 && first_vertex == 0 && first_instance == 0 &&
            ivy->tsharps_complete && ivy->images == IvyMaterialProbe::ImageCount;
        if (!scope_ok) {
            std::printf("Ivy sample (t133h): scope serial=%llu handle=%u same-pipeline=%u lamp=%u "
                        "pane=%u gbuffer=%u clear=%u feedback=%u reduced=%u jitter=%.6f,%.6f "
                        "extent=%ux%u layers=%u attachments=%u albedo-view=%u depth=%u depth-view=%u "
                        "rendering=%u depth-test=%u depth-write=%u le=%u bias=%u bounds=%u stencil=%u "
                        "discard=%u instances=%u first-vertex=%lld first-instance=%u tsharps=%u images=%u\n",
                        IvyMaterialProbe::Print64(ivy->serial), u32(bool(handle)),
                        u32(raster_pipeline == pipeline), u32(bool(material_probe)), u32(owner_sample),
                        u32(gbuffer_draw), u32(dc.clear_draw), u32(attachment_feedback_loop),
                        u32(scene_targets->Reduced()), double(draw_jitter[0]), double(draw_jitter[1]),
                        u32(state.width), u32(state.height), u32(state.num_layers),
                        u32(state.num_color_attachments), u32(bool(state.color_attachments[0].image_view)),
                        u32(state.depth_stencil_attachment.has_depth),
                        u32(bool(state.depth_stencil_attachment.image_view)), u32(scheduler.IsRenderingWith(state)),
                        u32(dynamic.depth_test_enabled), u32(dynamic.depth_write_enabled),
                        u32(dynamic.depth_compare_op == vk::CompareOp::eLessOrEqual), u32(dynamic.depth_bias_enabled),
                        u32(dynamic.depth_bounds_test_enabled), u32(dynamic.stencil_test_enabled),
                        u32(dynamic.rasterizer_discard_enable), u32(num_instances),
                        static_cast<long long>(first_vertex), u32(first_instance), u32(ivy->tsharps_complete),
                        u32(ivy->images));
        }
        auto active = scope_ok ? IvyMaterialProbe::Modules().Find(ivy_stage, ivy_module) : nullptr;
        const char* refusal = jitter_ok ? "draw-scope" : "jitter-unsupported";
        if (scope_ok) {
            if (!active) {
                refusal = "active-stage-join-missing";
            } else if (!IvySampleWitness::MatchesEffective(*active)) {
                refusal = "effective-bytes-mismatch";
            } else if (auto variant = raster_pipeline->IvySampleVariant()) {
                ivy_sample = IvySampleWitness::Prepare(instance, std::move(variant));
                if (ivy_sample) {
                    ivy_sample->draw_jitter = draw_jitter;
                }
                refusal = "private-storage-unavailable";
            } else {
                refusal = "exact-private-variant-unavailable";
            }
        }
        if (!ivy_sample) {
            std::printf("Ivy sample (t133h): serial=%llu frame=%u draw=%u stage=%llx "
                        "original_module=%llx effective=%016llx refused=%s ownership=unjoined\n",
                        IvyMaterialProbe::Print64(ivy->serial), ivy->frame, ivy->ordinal,
                        IvyMaterialProbe::Print64(ivy_stage), IvyMaterialProbe::Print64(ivy_module),
                        IvyMaterialProbe::Print64(active ? active->effective_hash : 0), refusal);
        }
    }
    const bool sewer_sample = sewer_receiver && !bottle_draw.private_param && !material_probe &&
        !owner_sample && !ivy_sample && SewerReceiverSample(state, material_draw, false);
    const auto workflow_query = workflow && workflow->querying
        ? WorkflowQueryDraw(raster_pipeline, state, {.indexed = is_indexed, .count = num_indices,
                            .instances = num_instances, .first_vertex = first_vertex, .first_instance = first_instance},
                            bool(query.pool) || material_probe || owner_sample || bool(ivy_sample) || sewer_sample,
                            sway == 0 ? draw_motion_slot : 0, capture_word)
        : WorkflowProbe::ScissorQuery{};
    const vk::Pipeline sample_pipeline = ivy_sample ? *ivy_sample->variant->pipeline : vk::Pipeline{};
    const vk::PipelineLayout sample_layout = ivy_sample ? *ivy_sample->variant->layout : vk::PipelineLayout{};
    const vk::DescriptorSet sample_set = ivy_sample ? ivy_sample->descriptor : vk::DescriptorSet{};
    if (retire) {
        const auto& graphics = raster_pipeline->GetGraphicsKey();
        retire->raster = reinterpret_cast<uintptr_t>(raster_pipeline);
        retire->raster_key = std::hash<GraphicsPipelineKey>{}(graphics);
        retire->raster_vs = graphics.stage_hashes[u32(Shader::SwStage::Vertex)];
        retire->raster_ps = graphics.stage_hashes[u32(Shader::SwStage::Fragment)];
        retire->record_tick = scheduler.CurrentTick();
        retire->handle = std::bit_cast<u64>(handle);
        retire->sample = std::bit_cast<u64>(sample_pipeline);
        retire->vertex = s32(first_vertex);
        retire->instances = num_instances;
        retire->first_instance = first_instance;
        retire->issue = !is_indexed ? "nonindexed" : sample_pipeline ? "sampled" :
            raster_pipeline != pipeline ? "replaced" : !handle ? "deferred-bind" :
            query.pool || workflow_query.pool ? "query" :
            material_probe || owner_sample || sewer_sample || bottle_draw.private_param || trees_pick_draw
            ? "private" : "original";
        retire->original = std::string_view{retire->issue} == "original";
    }
    SewerBridge::Draw sewer_draw;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    std::shared_ptr<SewerBridge::BottleDisplay> bottle_display;
    const bool bottle_prepared = upscaler->BottlePreparedPending();
    std::shared_ptr<SewerBridge::BottleDisplay> observed_bottle;
    BottleSet0Draw set0_draw{};
#endif
    if ((upscaler->HasSewerBridge() && upscaler->SewerBridgeOpen())
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        || bottle_prepared
#endif
    ) {
        const auto& dyn = scheduler.GetDynamicState();
        const auto& key = pipeline->GetGraphicsKey();
        const auto* frag = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        const bool storage_writes = std::ranges::any_of(pipeline->GetStages(), [](const auto* stage) {
            return stage && (std::ranges::any_of(stage->images, &Shader::ImageResource::is_written) ||
                             std::ranges::any_of(stage->buffers, &Shader::BufferResource::is_written));
        });
        const auto rect = dyn.scissors.size() == 1 ? dyn.scissors.front() : vk::Rect2D{};
        const auto viewport = dyn.viewports.size() == 1 ? dyn.viewports.front() : vk::Viewport{};
        const auto& target = state.color_attachments[0];
        const auto write = instance.IsDynamicColorWriteMaskSupported() ?
                           dyn.color_write_masks[0] : key.HostWriteMask(0);
        constexpr auto rgba = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                              vk::ColorComponentFlagBits::eB | vk::ColorComponentFlagBits::eA;
        const bool original = handle && raster_pipeline == pipeline && !sample_pipeline &&
            !workflow_query.pool && !query.pool && !material_probe && !owner_sample && !sewer_sample &&
            !bottle_draw.private_param && !trees_pick_draw && !storage_writes && frag &&
            !dyn.rasterizer_discard_enable && state.num_layers == 1 && state.num_color_attachments == 1;
        const bool full = frag && state.width == 3840 && state.height == 2160 &&
            rect == vk::Rect2D{{0, 0}, {3840, 2160}} &&
            (viewport == vk::Viewport{0.f, 0.f, 3840.f, 2160.f, 0.f, 1.f} ||
             viewport == vk::Viewport{0.f, 2160.f, 3840.f, -2160.f, 0.f, 1.f}) &&
            (num_indices == 3 || num_indices == 4 || num_indices == 6) && num_instances == 1 &&
            !frag->has_discard && !dyn.depth_test_enabled && !dyn.stencil_test_enabled &&
            !key.blend_controls[0].enable && key.logic_op == AmdGpu::ColorControl::LogicOp::Copy &&
            (write & rgba) == rgba && !target.is_clear && !dc.clear_draw;
#ifdef BB_TEST_SHARED_POST_GRAPH
        const bool display_pending = upscaler->SewerPostDisplayPending()
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            || bottle_prepared
#endif
            ;
        const auto display_slots = display_pending
            ? PostImageSlots(*raster_pipeline, dc.set_writes, scheduler.CurrentTick()) : BottleMotion203::Slots{};
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        SewerBridge::BottleDrawScope bottle_scope{};
        if (bottle_prepared) {
            using SewerBridge::BottleRejections;
            bottle_scope = {
                .original_mask = BottleRejections({!handle, raster_pipeline != pipeline, bool(sample_pipeline),
                    bool(workflow_query.pool), bool(query.pool), bool(material_probe), bool(owner_sample),
                    bool(sewer_sample), bool(bottle_draw.private_param), bool(trees_pick_draw), storage_writes,
                    !frag, dyn.rasterizer_discard_enable, state.num_layers != 1, state.num_color_attachments != 1}),
                .full_mask = BottleRejections({!frag, state.width != 3840 || state.height != 2160,
                    rect != vk::Rect2D{{0, 0}, {3840, 2160}},
                    viewport != vk::Viewport{0.f, 0.f, 3840.f, 2160.f, 0.f, 1.f} &&
                    viewport != vk::Viewport{0.f, 2160.f, 3840.f, -2160.f, 0.f, 1.f},
                    num_indices != 3 && num_indices != 4 && num_indices != 6, num_instances != 1,
                    frag && frag->has_discard, dyn.depth_test_enabled, dyn.stencil_test_enabled,
                    key.blend_controls[0].enable, key.logic_op != AmdGpu::ColorControl::LogicOp::Copy,
                    (write & rgba) != rgba, bool(target.is_clear), bool(dc.clear_draw)}),
                .index_count = num_indices, .instances = num_instances, .viewport_count = u32(dyn.viewports.size()),
                .scissor_count = u32(dyn.scissors.size()), .color_mask = u32(VkColorComponentFlags(write)),
                .logic_op = u32(key.logic_op), .viewport = viewport};
        }
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (bottle_operands) {
            auto& observation = *bottle_operands;
            const auto& actual_key = raster_pipeline->GetGraphicsKey();
            const auto* vs = raster_pipeline->GetStages()[u32(Shader::SwStage::Vertex)];
            observation.vs = vs ? vs->pgm_hash : 0;
            observation.vs_permutation = actual_key.stage_hashes[u32(Shader::SwStage::Vertex)];
            observation.ps_permutation = actual_key.stage_hashes[u32(Shader::SwStage::Fragment)];
            if (const auto* live = raster_pipeline->BottleDisplayProgram();
                handle && !sample_pipeline && live && pipeline_cache.CaptureProofUnchanged()) {
                observation.program = *live;
            }
            observation.primitive = u32(actual_key.prim_type);
            observation.elements = num_indices;
            observation.instances = num_instances;
            observation.first_vertex = first_vertex;
            observation.first_instance = first_instance;
            observation.indexed = is_indexed;
            observation.restart = regs.enable_primitive_restart;
            observation.cull = u32(VkCullModeFlags(dyn.cull_mode));
            observation.front_face = u32(dyn.front_face);
            observation.polygon = u32(actual_key.polygon_mode);
            observation.samples = actual_key.num_samples;
            observation.depth_clip = actual_key.depth_clip_enable;
            observation.depth_clamp = actual_key.depth_clamp_enable;
            if (is_indexed) {
                observation.index = dc.index_bind.handle;
                observation.index_offset = dc.index_bind.offset;
                observation.index_type = dc.index_bind.type;
            }
            observation.vertex_buffers = dc.vertex_binds.num_buffers;
            observation.attributes = u32(dc.vertex_binds.attributes.size());
            const auto expected_set = dc.set_writes.empty() ? vk::DescriptorSet{} : dc.set_writes.front().dstSet;
            const auto slots = BottleDisplay182::InspectSet0(dc.set_writes, expected_set);
            observation.binder_shape = slots.valid;
            observation.slot1_matches = slots.valid && observation.lut.known &&
                slots.images[1].imageView == observation.lut.view && slots.images[1].imageLayout == observation.lut.layout;
            observation.sampler_matches = slots.valid && observation.sampler.known &&
                observation.sampler.binding == 2 && slots.images[2].sampler == observation.sampler.handle;
        }
#endif
        const SewerBridge::DrawFacts post_facts{
            .scene = object_motion->Frame(), .ps = frag ? frag->pgm_hash : 0u,
            .color_id = cb_descs[0].first, .output = target.image_view, .layout = target.image_layout,
            .inputs = {dc.image_infos.data(), dc.image_infos.size()},
            .images = {dc.bound_images.data(), dc.bound_images.size()},
            .scissor = rect, .original = original, .full_write = full,
            .disjoint_capable = !target.is_clear && !dc.clear_draw &&
                                state.width == 3840 && state.height == 2160 && dyn.scissors.size() == 1,
#ifdef BB_TEST_SHARED_POST_GRAPH
            .attachment = {target.image_view, target.image_layout, {state.width, state.height},
                           state.num_layers, state.num_color_attachments, bool(target.is_clear)},
            .display_slots = display_slots,
            .pipeline = handle,
            .pipeline_layout = raster_pipeline->GetLayout(),
            .fragment_permutation = raster_pipeline->GetGraphicsKey().stage_hashes[u32(Shader::SwStage::Fragment)],
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            .bottle_scope = bottle_scope,
#endif
#endif
        };
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post_draw) {
            auto& post = *post_draw;
            post.vs = raster_pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
            post.vs_permutation = key.stage_hashes[u32(Shader::SwStage::Vertex)];
            post.ps_permutation = key.stage_hashes[u32(Shader::SwStage::Fragment)];
            post.pipeline = std::bit_cast<u64>(handle);
            post.indexed = is_indexed;
            post.count = num_indices;
            post.instances = num_instances;
            post.first_vertex = first_vertex;
            post.first_instance = first_instance;
            post.viewport = viewport;
            post.clear = target.is_clear || dc.clear_draw;
            post.blends = key.blend_controls[0].enable;
            post.width = state.width;
            post.height = state.height;
            post.scissor_count = u32(dyn.scissors.size());
            post.viewport_count = u32(dyn.viewports.size());
            post.write_mask = u32(VkColorComponentFlags(write));
            post.logic_op = u32(key.logic_op);
            post.topology = u32(LiverpoolToVK::PrimitiveType(regs.primitive_type));
            post.primitive_restart = regs.enable_primitive_restart;
            post.depth_test = dyn.depth_test_enabled;
            post.stencil_test = dyn.stencil_test_enabled;
            post.storage_or_attachment_scope_unknown = storage_writes || state.num_color_attachments != 1;
            const auto& v = dc.vertex_binds;
            post.attribute_count = u32(v.attributes.size());
            post.binding_count = u32(v.bindings.size());
            std::copy_n(v.attributes.begin(), std::min(v.attributes.size(), post.attributes.size()), post.attributes.begin());
            std::copy_n(v.bindings.begin(), std::min(v.bindings.size(), post.bindings.size()), post.bindings.begin());
            post.index_type = dc.index_bind.type;
            if (post.watch) {
                for (u32 i = 0; i < post.bytes.size(); ++i) {
                    auto& row = post.bytes[i];
                    if (!row.ticket) continue;
                    auto& actual = row.binding;
                    using GeometryUse = VideoCore::PostGeometry::Use;
                    if (actual.use == GeometryUse::Uniform) continue; // Joined at the effective descriptor.
                    actual.tick = scheduler.CurrentTick();
                    actual.backing.cache_generation = buffer_cache.StructureGeneration();
                    if (actual.use == GeometryUse::Vertex) {
                        const auto native = row.native_slot;
                        const auto attr = std::ranges::find(v.attributes, actual.slot,
                            &vk::VertexInputAttributeDescription2EXT::location);
                        if (attr == v.attributes.end() || attr->binding != native ||
                            std::ranges::count(v.attributes, actual.slot,
                                &vk::VertexInputAttributeDescription2EXT::location) != 1 ||
                            std::ranges::count(v.bindings, native,
                                &vk::VertexInputBindingDescription2EXT::binding) != 1 ||
                            native >= v.num_buffers || native >= v.host_buffers.size() ||
                            native >= v.host_offsets.size() || native >= v.host_sizes.size() ||
                            actual.bytes > v.host_sizes[native] || actual.offset != v.host_offsets[native]) {
                            row.state = VideoCore::PostGeometry::State::Mismatch;
                            continue;
                        }
                        actual.backing.handle = std::bit_cast<u64>(v.host_buffers[native]);
                    } else if (actual.use == GeometryUse::Index) {
                        if (!is_indexed || actual.offset != dc.index_bind.offset) {
                            row.state = VideoCore::PostGeometry::State::Mismatch;
                            continue;
                        }
                        actual.backing.handle = std::bit_cast<u64>(dc.index_bind.handle);
                    }
                    row.state = post.watch->Join(row.ticket, actual);
                }
            }
            upscaler->SewerPostFinal(post, post_facts);
        }
#endif
        sewer_draw = upscaler->SewerPlanDraw(post_facts);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (bottle_prepared)
            bottle_display = upscaler->BottlePlanPrepared(post_facts, bottle_operands ? &*bottle_operands : nullptr,
                                                           observed_bottle);
        if (set0 && bottle_operands && original && target.image_view &&
            set0_key.frame == BbStats::frame_number.load(std::memory_order_relaxed) &&
            regs.color_buffers[0].Address() == set0_key.address && raster_pipeline->GetLayout() == set0->layout &&
            set0_load == BbEngine::Loading::Generation() && !BbEngine::Loading::ScreenUp() &&
            set0_targets == scene_targets->Generation() && set0_object + 1 == object_motion->Frame()) {
            const auto& slot = display_slots.images.front();
            const bool bound_ui = slot.exact && slot.binding == 0 && slot.view &&
                                  slot.view == bottle_operands->ui_redirect;
            set0_draw = {set0->layout, target.image_view, bound_ui ? slot.view : vk::ImageView{},
                         bottle_operands->lut.view, bottle_operands->sampler.handle, false,
                         dyn.depth_bounds_test_enabled, bool(state.depth_stencil_attachment.image_view),
                         bool(instance.GetPhysicalDevice().getProperties().limits.standardSampleLocations)};
            if (const auto& owner = bottle_display ? bottle_display : observed_bottle;
                owner && owner->address == set0_key.address && owner->scene.key.request == set0_key.request &&
                owner->scene.key.scene == set0_key.scene && owner->scene.draw_frame == set0_key.frame &&
                owner->scene.last_epoch == set0_key.epoch && owner->attachment == target.image_view) {
                const auto& fact = *bottle_operands;
                const auto separated = [&](const auto& image) {
                    return image.Valid() && BottleDisplay182::Disjoint(fact.lut, image.image,
                        reinterpret_cast<u64>(image.allocator), reinterpret_cast<u64>(image.allocation),
                        std::bit_cast<u64>(image.memory), image.offset, image.bytes);
                };
                set0_draw.physical = fact.slot1_matches && set0_draw.ui &&
                    SewerBridge::PhysicalSeparation(owner->target, owner->ui) == BottleAncestry::Proof::Known &&
                    separated(owner->target) && separated(owner->ui);
            }
        }
#endif
    }
    auto record_draw = [=](vk::CommandBuffer cmdbuf) {
        if (sample_pipeline) {
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, sample_pipeline);
            cmdbuf.bindDescriptorSets(vk::PipelineBindPoint::eGraphics, sample_layout,
                                      IvySampleWitness::DescriptorSet, sample_set, {});
        } else if (handle) { // null: bound by the command before (BindWhenCompiled)
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, handle);
        }
        if (query.pool) {
            cmdbuf.beginQuery(query.pool, query.index, query.flags);
        }
        if (is_indexed) {
            cmdbuf.drawIndexed(num_indices, num_instances, 0, s32(first_vertex), first_instance);
        } else {
            cmdbuf.draw(num_indices, num_instances, first_vertex, first_instance);
        }
        if (query.pool) {
            cmdbuf.endQuery(query.pool, query.index);
        }
        if (sample_pipeline) {
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, handle);
        }
    };
#ifdef BB_TEST_SHARED_POST_GRAPH
    const auto native_order = sewer_draw.native_order ? sewer_draw.native_order :
        post_draw ? post_draw->native_order : NativeWriteSuffix::PostToken{};
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    if (bottle_display) {
        const auto token = bottle_display->display_order;
        auto observed = [draw = std::move(record_draw), bottle_display](
                            vk::CommandBuffer cmd, NativeWriteSuffix::Encoder* encoder) {
            draw(cmd);
            if (encoder) encoder->NotePost(bottle_display->display_order);
            bottle_display->encoded.store(std::bit_cast<u64>(cmd), std::memory_order_release);
        };
        if (token) {
            scheduler.RecordPostNative(crumb, token,
                [record = std::move(observed)](vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
                    record(cmd, &encoder);
                });
        } else {
            WorkflowRecordDraw(scheduler, crumb,
                [record = std::move(observed)](vk::CommandBuffer cmd) { record(cmd, nullptr); },
                workflow_query, instance);
        }
        upscaler->BottleEndPrepared(bottle_display);
    } else
#endif
    if (native_order && !workflow_query.pool) {
        scheduler.RecordPostNative(crumb, native_order,
            [draw = std::move(record_draw), sewer_draw, post_draw, native_order]
            (vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
                draw(cmd);
                encoder.NotePost(native_order);
                if (post_draw) post_draw->encoded.store(std::bit_cast<u64>(cmd), std::memory_order_release);
                sewer_draw.Encoded(cmd);
            });
    } else
#endif
    if (sewer_draw.trace) {
        auto observed_draw = [draw = std::move(record_draw), sewer_draw](vk::CommandBuffer cmdbuf) {
            draw(cmdbuf);
            sewer_draw.Encoded(cmdbuf);
        };
        WorkflowRecordDraw(scheduler, crumb, std::move(observed_draw), workflow_query, instance);
#ifdef BB_TEST_SHARED_POST_GRAPH
    } else if (post_draw) {
        auto observed_draw = [draw = std::move(record_draw), post_draw](vk::CommandBuffer cmdbuf) {
            draw(cmdbuf);
            post_draw->encoded.store(std::bit_cast<u64>(cmdbuf), std::memory_order_release);
        };
        WorkflowRecordDraw(scheduler, crumb, std::move(observed_draw), workflow_query, instance);
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    } else if (observed_bottle || (set0 && set0_draw)) {
        const auto ticket = set0_draw ? set0 : nullptr;
        auto ordinary = [draw = std::move(record_draw), observed_bottle, ticket, set0_draw, producer = &scheduler](
                            vk::CommandBuffer cmd) {
            draw(cmd);
            if (observed_bottle) {
                const auto& scene = observed_bottle->scene;
                fmt::print("[bottle-cut] event=prepared-original-encoded request={} scene={} frame={} epoch={} "
                           "command={:x} target_view={:x}\n", scene.key.request, scene.key.scene, scene.draw_frame,
                           scene.last_epoch, std::bit_cast<u64>(cmd), std::bit_cast<u64>(observed_bottle->attachment));
            }
            if (ticket) ReportBottleSet0Draw(*producer, *ticket, cmd, set0_draw);
        };
        WorkflowRecordDraw(scheduler, crumb, std::move(ordinary), workflow_query, instance);
        if (ticket) {
            const u64 retirement_tick = scheduler.CurrentTick();
            scheduler.DeferOperation([ticket, producer = &scheduler, retirement_tick] {
                const auto submitted = producer->SubmittedTick();
                const auto completed = producer->GetWorkSemaphore()->KnownGpuTick();
                const auto& key = ticket->key;
                fmt::print("[bottle-cut] event=prepared-set0-retired request={} scene={} frame={} epoch={} "
                           "address={:x} timeline={:x} retirement_tick={} submitted_tick={} completed_tick={} "
                           "render_fenced={} texture_version=unknown\n",
                           key.request, key.scene, key.frame, key.epoch, key.address,
                           std::bit_cast<u64>(ticket->timeline), retirement_tick, submitted, completed,
                           ticket->Retired(retirement_tick, submitted, completed));
            }, "bottle display descriptor evidence");
        }
#endif
    } else {
        WorkflowRecordDraw(scheduler, crumb, std::move(record_draw), workflow_query, instance);
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (sewer_draw.trace && sewer_draw.trace->post && sewer_draw.step == SewerBridge::Step::Display)
        upscaler->SewerPostEndDisplay(sewer_draw);
#endif
    if (retire && retire->original) {
        ReflectionFirstRetire::ReadModule(*retire, pipeline_cache, *raster_pipeline);
    }
    if (BottleMotion::Run() && cb_descs[0].first) {
        auto& motion=BottleMotion::Scene();
        const auto target_id=cb_descs[0].first;
        const auto* target=texture_cache.TryGetImage(target_id,0);
        const bool issued=handle && raster_pipeline==pipeline && !sample_pipeline && !workflow_query.pool &&
            !material_probe && !owner_sample && !sewer_sample && !bottle_draw.private_param &&
            num_indices>=3 && num_instances==1 && state.width==3840 && state.height==2160 &&
            state.num_color_attachments==1;
        if (target && FrameCapture::IsDisplayBuffer(target->info.guest_address)) {
            upscaler->MotionIssuedDisplay(target->info.guest_address,state.color_attachments[0].image_view,
                                          dc.image_infos,issued);
        } else if (motion.mark && motion.dlss && !motion.bad) {
            const auto* fs=pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            constexpr u64 motion_hdr_post=0xccbf44a6;
            if (fs && fs->pgm_hash==motion_hdr_post) {
                const auto match_view=[&](const VideoCore::Image& image,vk::ImageView view) {
                    return view && image.backing && !image.binding.needs_rebind &&
                        std::ranges::any_of(image.backing->image_view_ids,[&](const auto id) {
                            return texture_cache.GetImageView(id).image_view.get()==view;
                        });
                };
                u32 inputs=0;
                for (const auto id:dc.bound_images) {
                    const auto* image=id?texture_cache.TryGetImage(id,motion.hdr_uid):nullptr;
                    if (!image || image->GetImage()!=motion.hdr || image->write_seq!=motion.hdr_write) continue;
                    for (const auto& in:dc.image_infos) inputs+=match_view(*image,in.imageView);
                }
                if (!issued || motion.tone || inputs!=1 || !target ||
                    target->info.pixel_format!=vk::Format::eR8G8B8A8Unorm ||
                    !match_view(*target,state.color_attachments[0].image_view)) {
                    BottleMotion::Refuse(motion,"actual-tonemap-bind-or-writer");
                } else {
                    motion.tone=true;
                    motion.ldr_id=target_id.index;motion.ldr_uid=target->image_uid;
                    motion.ldr_write=target->write_seq;
                }
            }
        }
    }
    if ((num_indices == 52638 || num_indices == 6) && caustics && scene_targets->Reduced()) {
        const bool ground = num_indices == 52638;
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (ps && ps->pgm_hash == (ground ? 0xdbb222ebu : 0xa28d2a7au) &&
            pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash ==
                (ground ? 0xc829ee58u : 0xe4680233u)) {
            const bool product = caustics->NativeBedWanted();
            const bool observe = caustics->SewerReducedArmed(ground);
            if (product || observe) {
                const auto& ds = state.depth_stencil_attachment;
                const auto& cb2 = state.color_attachments[2];
                const auto& dynamic = scheduler.GetDynamicState();
                const auto& key = pipeline->GetGraphicsKey();
                const auto jitter = upscaler->Jitter();
                const auto draw_jitter = Dc().draw_jitter;
                const vk::Extent2D extent{state.width, state.height};
                const bool flip_y = regs.viewports[0].yscale < 0;
                const vk::Viewport viewport{draw_jitter[0], (flip_y ? 1080.f : 0.f) + draw_jitter[1],
                                            1920.f, flip_y ? -1080.f : 1080.f, 0.f, 1.f};
                const bool motion_shape = state.num_color_attachments == 8 &&
                    key.mrt_mask == 0xbf && key.motion_vectors == Shader::MotionVectors::VertexBoth &&
                    !state.color_attachments[6].image_view && !regs.color_buffers[7] && !cb_descs[7].first;
                bool motion_owner = false;
                if (ground && motion_shape) {
                    const auto owner = object_motion->FindAttachmentOwner(extent.width, extent.height);
                    const auto& bound = state.color_attachments[7];
                    motion_owner = owner && owner->view && owner->view == bound.image_view &&
                        owner->written && owner->used_frame == owner->owner_frame &&
                        owner->layout == vk::ImageLayout::eColorAttachmentOptimal &&
                        bound.image_layout == owner->layout;
                }
                const bool material = !ground || (gbuffer_draw && !ps->has_discard && ps->mrt_mask == 0x3f &&
                    (key.mrt_mask & 0x7f) == 0x3f &&
                    (state.num_color_attachments == 6 || motion_owner) && cb2.image_view &&
                    (u32(VkColorComponentFlags(key.HostWriteMask(2))) & 7u) == 7u &&
                    !key.blend_controls[2].enable && key.logic_op == AmdGpu::ColorControl::LogicOp::Copy &&
                    !std::ranges::any_of(std::span(state.color_attachments).first<6>(),
                                         [](const auto& attachment) { return attachment.is_clear; }));
                struct Check { bool pass; const char* why; };
                const Check gates[] = {
                    {bool(handle) && raster_pipeline == pipeline && !sample_pipeline && !workflow_query.pool &&
                        !material_probe && !owner_sample && !sewer_sample && !bottle_draw.private_param &&
                        !trees_pick_draw && !query.pool, "draw-not-original"},
                    {is_indexed && !index_offset && num_instances == 1 && !first_instance &&
                        Dc().index_bind.handle && !regs.enable_primitive_restart &&
                        LiverpoolToVK::PrimitiveType(regs.primitive_type) == vk::PrimitiveTopology::eTriangleList,
                        "draw-index-shape"},
                    {db_desc.first && db_desc.first == camera_motion->Depth() && ds.image_view && ds.has_depth &&
                        !ds.depth_clear && !ds.stencil_clear && !Dc().clear_draw && state.num_layers == 1 &&
                        !regs.IsClipDisabled() && dynamic.depth_test_enabled && dynamic.depth_write_enabled &&
                        dynamic.depth_compare_op == vk::CompareOp::eLessOrEqual && !dynamic.depth_bias_enabled &&
                        !dynamic.depth_bounds_test_enabled && !dynamic.rasterizer_discard_enable, "draw-depth-state"},
                    {material, "draw-ground-material"},
                    {extent == vk::Extent2D{1920, 1080} && target_scale == std::array{0.5f, 0.5f} &&
                        !target_offset[0] && !target_offset[1] &&
                        draw_jitter == (ground ? jitter : std::array<float, 2>{}) &&
                        std::abs(jitter[0]) <= 0.5f && std::abs(jitter[1]) <= 0.5f &&
                        dynamic.viewports.size() == 1 && dynamic.viewports.front() == viewport &&
                        dynamic.scissors.size() == 1 && dynamic.scissors.front() == vk::Rect2D{{0, 0}, extent},
                        "draw-transform"},
                };
                const auto bad = std::ranges::find_if(gates, [](const Check& gate) { return !gate.pass; });
                if (bad != std::end(gates)) {
                    caustics->RefuseReducedBedDraw(product, bad->why);
                } else {
                    caustics->SewerReducedDraw(ground, product, object_motion->Frame(), db_desc.first,
                                               ds.image_view, cb_descs[2].first, cb2.image_view, jitter);
                }
            }
        }
    }

    if (num_indices == 52638 || num_indices == 6) {
        const bool ground = num_indices == 52638;
        const char* trace = nullptr;
        std::optional<SewerJoinedDraw> joined;
        if (caustics && caustics->TracingNativeBed(db_desc.first)) {
            const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
            if (ps && ps->pgm_hash == (ground ? 0xdbb222ebu : 0xa28d2a7au) &&
                pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash ==
                    (ground ? 0xc829ee58u : 0xe4680233u)) {
                trace = ground ? "ground-draw" : "water-draw";
                if (caustics->ClaimNativeBedDrawTrace(ground)) {
                    const auto& key = pipeline->GetGraphicsKey();
                    const auto& ds = state.depth_stencil_attachment;
                    const auto& dynamic = scheduler.GetDynamicState();
                    if (caustics->TracingJoinedBed(db_desc.first)) {
                        joined.emplace();
                        joined->stamp = caustics->JoinedBedStamp();
                        joined->before = caustics->JoinedBedState();
                        const auto viewport = dynamic.viewports.empty() ? "?" : [&] {
                            const auto& v = dynamic.viewports.front();
                            return fmt::format("{:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g}",
                                               v.x, v.y, v.width, v.height, v.minDepth, v.maxDepth);
                        }();
                        const auto scissor = dynamic.scissors.empty() ? "?" : [&] {
                            const auto& s = dynamic.scissors.front();
                            return fmt::format("{},{},{},{}", s.offset.x, s.offset.y,
                                               s.extent.width, s.extent.height);
                        }();
                        const auto frame_jitter = upscaler->Jitter();
                        joined->raw = fmt::format(
                            "ps_mask={:x} slot6={}/{}/{:x} slot7={}/{}/{:x}/{} primitive={} "
                            "restart={} index_bound={} flip_y={} viewports={} viewport={} scissors={} "
                            "scissor={} scale={:.9g},{:.9g} offset={},{} frame_jitter={:08x},{:08x} "
                            "draw_jitter={:08x},{:08x} depth={}/{:x} depth_info={} cb2={}/{:x} cb2_info={}",
                            u32(ps->mrt_mask), bool(regs.color_buffers[6]), cb_descs[6].first.index,
                            SewerJoinedDraw::Handle(state.color_attachments[6].image_view),
                            bool(regs.color_buffers[7]), cb_descs[7].first.index,
                            SewerJoinedDraw::Handle(state.color_attachments[7].image_view),
                            u32(state.color_attachments[7].image_layout), u32(regs.primitive_type),
                            bool(regs.enable_primitive_restart), bool(Dc().index_bind.handle),
                            regs.viewports[0].yscale < 0.0f, dynamic.viewports.size(), viewport,
                            dynamic.scissors.size(), scissor, target_scale[0], target_scale[1],
                            target_offset[0], target_offset[1], std::bit_cast<u32>(frame_jitter[0]),
                            std::bit_cast<u32>(frame_jitter[1]), std::bit_cast<u32>(Dc().draw_jitter[0]),
                            std::bit_cast<u32>(Dc().draw_jitter[1]), db_desc.first.index,
                            SewerJoinedDraw::Handle(ds.image_view), db_desc.first ? SewerJoinedDraw::ViewInfo(db_desc.second.view_info) : "?",
                            cb_descs[2].first.index, SewerJoinedDraw::Handle(state.color_attachments[2].image_view),
                            cb_descs[2].first ? SewerJoinedDraw::ViewInfo(cb_descs[2].second.view_info) : "?");
                    }
                    u32 clear_mask = 0;
                    for (u32 i = 0; i < 6; ++i) {
                        if (state.color_attachments[i].is_clear) clear_mask |= 1u << i;
                    }
                    std::printf("[sewer-first-gate-t200] event=draw path=%s frame=%u scene=%llu pass=%u "
                                "tick=%llu depth=%u camera_depth=%u count=%u first=%u instances=%u "
                                "first_instance=%u indexed=%u ready=%u original=%u sample=%u tree_pick=%u "
                                "query=%u bottle=%u gbuffer=%u attachments=%u mrt=%x motion=%x "
                                "slot7=%u cb2_view=%u cb2_mask=%x cb2_blend=%u logic=%u clear_mask=%x "
                                "extent=%ux%u layers=%u clip_disabled=%u depth_view=%u depth_clear=%u "
                                "stencil_clear=%u clear_draw=%u depth_test=%u depth_write=%u "
                                "depth_compare=%u depth_bias=%u depth_bounds=%u discard=%u shader_discard=%u "
                                "reduced=%u jitter=%g,%g\n",
                                trace, BbStats::frame_number.load(std::memory_order_relaxed),
                                static_cast<unsigned long long>(object_motion->Frame()),
                                sewer_receiver ? sewer_receiver->trace.pass : 0u,
                                static_cast<unsigned long long>(scheduler.CurrentTick()),
                                db_desc.first.index, camera_motion->Depth().index, num_indices, index_offset,
                                num_instances, first_instance, unsigned(is_indexed), unsigned(bool(handle)),
                                unsigned(raster_pipeline == pipeline), unsigned(bool(sample_pipeline)),
                                unsigned(trees_pick_draw), unsigned(bool(workflow_query.pool)),
                                unsigned(bool(bottle_draw.private_param)), unsigned(gbuffer_draw),
                                u32(state.num_color_attachments), u32(key.mrt_mask), key.motion_vectors,
                                unsigned(bool(state.color_attachments[7].image_view)),
                                unsigned(bool(state.color_attachments[2].image_view)),
                                u32(VkColorComponentFlags(key.HostWriteMask(2))), unsigned(key.blend_controls[2].enable),
                                u32(key.logic_op), clear_mask, state.width, state.height, u32(state.num_layers),
                                unsigned(regs.IsClipDisabled()), unsigned(bool(ds.image_view)),
                                unsigned(ds.depth_clear), unsigned(ds.stencil_clear), unsigned(Dc().clear_draw),
                                unsigned(dynamic.depth_test_enabled), unsigned(dynamic.depth_write_enabled),
                                u32(dynamic.depth_compare_op), unsigned(dynamic.depth_bias_enabled),
                                unsigned(dynamic.depth_bounds_test_enabled), unsigned(dynamic.rasterizer_discard_enable),
                                unsigned(ps->has_discard), unsigned(scene_targets->Reduced()),
                                double(Dc().draw_jitter[0]), double(Dc().draw_jitter[1]));
                }
            }
        }
        const auto gate = [&](bool accepted, const char* predicate) {
            return trace ? caustics->NativeBedTraceGate(accepted, trace, predicate) : accepted;
        };
        if (gate(is_indexed, "not-indexed") && gate(index_offset == 0, "first-index") &&
            gate(num_instances == 1, "instance-count") && gate(first_instance == 0, "first-instance") &&
            gate(bool(handle), "pipeline-unready") && gate(raster_pipeline == pipeline, "replaced-pipeline") &&
            gate(!sample_pipeline, "sample-pipeline") && gate(!trees_pick_draw, "tree-pick") &&
            gate(!workflow_query.pool, "workflow-query") && gate(!bottle_draw.private_param, "bottle-draw") &&
            caustics && (!scene_targets->Reduced() || trace) && caustics->TraceNativeBedWanted(trace) &&
            (ground || gate(caustics->AwaitsNativeBedWater(), "not-awaiting-water"))) {
            NoteNativeBedDraw(state, *pipeline, ground, joined ? &*joined : nullptr);
        }
        if (joined) joined->Report(ground, scheduler.CurrentTick(), *caustics);
    }
    const bool classified_stock_issued = !classified_stock ||
        (classified_stock == handle && raster_pipeline == pipeline &&
         pipeline->GetStockFragmentVerdict(pipeline_cache, original_stock_role, handle) !=
             ReflectionDiscard::Verdict::Unknown &&
         !sample_pipeline &&
         !material_probe && !owner_sample && !sewer_sample && !query.pool && !workflow_query.pool &&
         !bottle_draw.private_param && !trees_pick_draw && is_indexed && num_instances == 1 &&
         first_vertex == 0 && first_instance == 0);
    if (native_proof && native_proof->exact && native_proof->exact->placement) {
        native_proof->exact->submitted = handle && raster_pipeline == pipeline && !sample_pipeline &&
            !material_probe && !owner_sample && !sewer_sample && !workflow_query.pool &&
            !bottle_draw.private_param;
    }
    if (sewer_sample) {
        scheduler.R21NeutralLast();
        SewerReceiverSample(state, material_draw, true);
    } else if (sewer_receiver && is_indexed && num_indices == 6 && num_instances == 1 &&
               !sample_pipeline && raster_pipeline == pipeline && !material_probe && !owner_sample &&
               !workflow_query.pool && !bottle_draw.private_param) {
        SewerReceiverWaterDraw(state, pipeline);
    }
    if (native_proof && (raster_pipeline != pipeline || sample_pipeline || bottle_draw.private_param)) {
        native_proof->placement_safe = false;
    }
    if (bottle_draw.observed) {
        rt_shadow->RecordBottleDraw(bottle_draw);
    }
    if (owner_sample) {
        if (!bottle_draw.private_param) {
            scheduler.R21NeutralLast();
        }
        SampleWindowOwner(state, material_draw, true);
    }
    if (material_probe) {
        LampMaterialSample(*material_probe, state, material_draw, true);
    }
    if (ivy_sample) {
        blood_pool_probe->NoteIvyOwnerSample(ivy->serial, ivy->frame, ivy->ordinal,
                                            scheduler.CurrentTick(), ivy_sample->draw_jitter);
        IvySampleWitness::Retire(scheduler, state, std::move(ivy_sample), *ivy, ivy_stage, ivy_module);
    }
    if (ivy) {
        RecordIvyMaterial(*raster_pipeline, state, *ivy);
    }
    // bbport (r21_draw-sort): the draw command (a pipeline whose vertex input is dynamic, a query,
    // the draw) leaves vertex input, vertex buffer and index buffer binds as they are.
    // The readback has its own command span and must not be marked neutral.
    if (!owner_sample && !sewer_sample && !bottle_draw.private_param) scheduler.R21NeutralLast();
    if (workflow_query.pool && workflow->request.op == WorkflowProbe::Op::Resources)
        WorkflowCopyIndex(state, workflow_query.index);
    if (blood_index) {
        const auto& resolved = *blood_index;
        const auto& bound_index = dc.index_bind;
        const auto& dynamic = scheduler.GetDynamicState();
        const bool original = handle && !native_proof && !owner_sample && !material_probe &&
            !sample_pipeline && !bottle_draw.private_param && !workflow_query.pool &&
            raster_pipeline == pipeline;
        const bool binding_matches = bound_index.handle == resolved.buffer &&
            bound_index.offset == resolved.offset && bound_index.type == resolved.type;
        blood_pool_probe->CopyBoundIndex(state, resolved, {
            .count = num_indices, .guest_first = index_offset, .vk_first = 0,
            .instances = num_instances, .first_instance = first_instance, .vertex_offset = s32(first_vertex),
            .topology = LiverpoolToVK::PrimitiveType(raster_pipeline->GetGraphicsKey().prim_type),
            .restart = dynamic.primitive_restart_enable,
            .confirmed = original && gbuffer_draw && binding_matches && dynamic.depth_test_enabled &&
                dynamic.depth_write_enabled && IsMapped(resolved.guest, resolved.bytes) &&
                (!resolved.sealed || BbEngine::GxObjects::SealedValid(resolved.sealed_id,
                                                                     resolved.generation)),
        });
    }
    if (R21Counting()) {
        R21AfterDraw(pipeline, is_indexed); // BB_DRAW_ORDER=1
    }
    if (sun_hold.draw_cascade < 4) {
        SunHoldDrawn(); // bbport (r7_cascades)
    }
    BbSections::Scope after_draw_scope{BbSections::AfterDraw};
    if (weapon_sparks_on) { // bbport (r110_weapon-sparks): BB_WEAPON_SPARKS only
        WeaponSparksAfterDraw(pipeline, is_indexed, num_indices, num_instances, first_vertex,
                              first_instance);
    }
    // The Froyok pyramid must see the defocused image, so DOF's recombination goes first.
    const auto* epilogue_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (epilogue_ps && epilogue_ps->pgm_hash == DofRecombinePixelShaderHash) {
        DepthOfFieldAfterDraw(pipeline, state);
        EffectsAfterDraw(regs, pipeline, is_indexed, num_indices, num_instances, first_vertex,
                         reflection_draw, *raster_pipeline, classified_stock_issued);
    } else {
        EffectsAfterDraw(regs, pipeline, is_indexed, num_indices, num_instances, first_vertex,
                         reflection_draw, *raster_pipeline, classified_stock_issued);
        DepthOfFieldAfterDraw(pipeline, state);
    }
    if (dc.wall_stream.receipt) {
        const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
        const auto& stamp = native_proof->stamp;
        const u64 generation = BbEngine::Loading::Generation();
        const bool submitted = handle && wall_descriptor_submitted && native_proof->submission_stamp &&
            raster_pipeline == pipeline && WallStreamStages(*raster_pipeline) &&
            !sample_pipeline && !sewer_sample && !material_probe && !owner_sample &&
            !workflow_query.pool && !bottle_draw.private_param && stamp.generation == generation &&
            !BbEngine::Loading::ScreenUp() && dc.draw_jitter == stamp.jitter;
        std::printf("Reflection wall stream event=draw-recorded packet=%u generation=%llu frame=%llu pass=%llu "
                    "cookie=%llu allocation=%llu placement=%016llx original_submit=%u\n",
                    dc.wall_stream.receipt->packet, u(generation), u(stamp.frame), u(stamp.pass),
                    u(reflection_draw.cookie), u(reflection_draw.allocation), u(reflection_draw.placement),
                    u32(submitted));
    }
    if (native_proof && native_proof->trace) {
        ReflectionNativeAfterDraw(*native_proof);
        const auto& draw = *native_proof;
        const u32 target = Match(draw.key);
        if (NativeFollowupTarget(target)) {
            auto& pace = reflection_native_pace[target];
            const auto& stamp = reflection_probe->stamp;
            const bool confirmed = draw.submission_stamp && stamp && *stamp == draw.stamp && gbuffer_draw &&
                draw.stamp.frame == rt_shadow->WindowDiagnosticFrame() &&
                !BbEngine::Loading::ScreenUp() && draw.stamp.generation == BbEngine::Loading::Generation() &&
                dc.draw_jitter == draw.stamp.jitter && dc.draw_inputs.index_offset == draw.key.first;
            const bool attested = draw.native_entry && draw.revision && draw.resident_cookie;
            if (confirmed && !attested && pace.phase_used == 1 && pace.total < NativeSampleLimit) {
                pace.retry_until = draw.stamp.frame + NativeFollowupWindow;
                pace.retry_generation = draw.stamp.generation;
                pace.retries = std::min(NativeFollowupLimit, NativeSampleLimit - pace.total);
                NativeFollowupStatus(target, pace.frame, pace.phase, "armed");
            } else if (confirmed && attested && std::strcmp(draw.readback_reason, "recorded") == 0) {
                pace.retries = 0;
                pace.retry_until = 0;
            } else if ((pace.retry_until || (confirmed && !attested && pace.total == NativeSampleLimit)) &&
                       !pace.retries) {
                NativeFollowupStatus(target, pace.frame, pace.phase, "followup-exhausted");
                pace.retry_until = 0;
                pace.cap_logged = pace.total == NativeSampleLimit;
            }
        }
    }
    if (spatial_ao->Enabled()) {
        HqAoAfterDraw(pipeline, state);
    }
    if (window_receiver && epilogue_ps && epilogue_ps->pgm_hash == DirectionalFragmentShaderHash) {
        CaptureWindowReceiver(regs, epilogue_ps->pgm_hash);
    }
    after_draw_scope.End();
    if (FrameCapture::Active()) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        FrameCapture::Draw(vs_info.pgm_hash, ps ? ps->pgm_hash : 0, num_indices, num_instances);
        if (const auto& bc = regs.blend_control[0]; bc.enable && regs.color_buffers[0]) {
            char note[128];
            std::snprintf(note, sizeof(note), "\n  blend ps %08x idx %u: src %u dst %u func %u z %u%u",
                          u32(ps ? ps->pgm_hash : 0), num_indices, u32(bc.color_src_factor),
                          u32(bc.color_dst_factor), u32(bc.color_func),
                          u32(regs.depth_control.depth_enable),
                          u32(regs.depth_control.depth_write_enable));
            FrameCapture::Note(note);
        }
    }
    DebugState.IncDrawCall();

    BB_SECTION(Kick);
    ResetBindings(false);
    scheduler.KickRecording();
}

void Rasterizer::RecordIvyMaterial(const GraphicsPipeline& pipeline, const RenderState& state,
                                   const IvyMaterialProbe::Snapshot& draw) {
    using namespace IvyMaterialProbe;
    ivy_material_recorded = true;
    const auto& dc = Dc();
    const auto& key = pipeline.GetGraphicsKey();
    constexpr u32 fragment = u32(Shader::SwStage::Fragment);
    const auto* ps = pipeline.GetStages()[fragment];
    const auto stage = key.stage_hashes[fragment];
    const auto module_handle = pipeline.IvyFragmentModule();
    const bool exact_stage = ps && ps->pgm_hash == Fragment;
    const auto selected = Modules().Take(exact_stage ? stage : 0, exact_stage ? module_handle : 0);
    const auto& blend = key.blend_controls[0];
    const auto& dynamic = scheduler.GetDynamicState();

    const bool one_each = ps && dc.card_bound.stage == ps && dc.card_bound.count == ImageCount &&
                          draw.images == ImageCount && draw.tsharps_complete;
    std::printf("Ivy material (t133h): serial=%llu frame=%u draw=%u vs=%08llx ps=%08llx first=%u count=%u "
                "stage=%llx module=%llx route=%s emitter=%s retained=%u dropped=%u "
                "images=%u one_to_one=%u samplers=%u buffers=%u material_texels=absent\n",
                Print64(draw.serial), draw.frame, draw.ordinal, Print64(Vertex), Print64(Fragment),
                First, Count, Print64(stage), Print64(module_handle),
                selected.module ? selected.module->route : "missing-module-join",
                selected.module ? selected.module->emitter : "unknown", selected.retained,
                selected.dropped, draw.images, one_each, draw.samplers, draw.buffers);
    const auto c0 = cb_descs[0].first;
    const auto d0 = db_desc.first;
    std::printf("Ivy material (t133h): render=%ux%ux%u mrt=%x samples=%u color0=%u/%llu/%llx/%u "
                "depth=%u/%llu/%llx/%u blend=%u/%u/%u/%u/%u/%u/%u/%u write=%x logic=%u "
                "depth_state=%u/%u/%u bounds=%u/%.9g/%.9g stencil=%u format=%u/%u\n",
                state.width, state.height, state.num_layers, key.mrt_mask, key.num_samples,
                c0.index, Print64(c0 ? texture_cache.GetImage(c0).image_uid : 0),
                Print64(std::bit_cast<u64>(state.color_attachments[0].image_view)),
                u32(state.color_attachments[0].image_layout),
                d0.index, Print64(d0 ? texture_cache.GetImage(d0).image_uid : 0),
                Print64(std::bit_cast<u64>(state.depth_stencil_attachment.image_view)),
                u32(state.depth_stencil_attachment.image_layout),
                blend.enable, blend.separate_alpha_blend, u32(blend.color_src_factor),
                u32(blend.color_dst_factor), u32(blend.color_func), u32(blend.alpha_src_factor),
                u32(blend.alpha_dst_factor), u32(blend.alpha_func),
                u32(instance.IsDynamicColorWriteMaskSupported() ? dynamic.color_write_masks[0]
                                                                 : key.write_masks[0]),
                u32(key.logic_op), dynamic.depth_test_enabled, dynamic.depth_write_enabled,
                u32(dynamic.depth_compare_op), dynamic.depth_bounds_test_enabled,
                double(dynamic.depth_bounds_min), double(dynamic.depth_bounds_max),
                dynamic.stencil_test_enabled, u32(key.z_format), u32(key.stencil_format));
    const auto stencil = [&](const char* face, const StencilOps& op, u32 ref, u32 read, u32 write) {
        std::printf("Ivy material (t133h): stencil_face=%s fail/pass/depthfail/compare=%u/%u/%u/%u "
                    "ref/read/write=%u/%u/%u\n",
                    face, u32(op.fail_op), u32(op.pass_op), u32(op.depth_fail_op), u32(op.compare_op),
                    ref, read, write);
    };
    if (dynamic.stencil_test_enabled) {
        stencil("front", dynamic.stencil_front_ops, dynamic.stencil_front_reference,
                dynamic.stencil_front_compare_mask, dynamic.stencil_front_write_mask);
        stencil("back", dynamic.stencil_back_ops, dynamic.stencil_back_reference,
                dynamic.stencil_back_compare_mask, dynamic.stencil_back_write_mask);
    }
    PrintBlob("blend-constants", 0, ObjectBytes(dynamic.blend_constants));
    PrintBlob("push", 0, std::span(draw.push).first(draw.push_size));

    unsigned bound_images = 0;
    if (one_each) {
        for (u32 i = 0; i < ImageCount; ++i) {
            const u32 binding = draw.first_image_binding + i;
            const auto w = std::ranges::find(dc.set_writes, binding, &vk::WriteDescriptorSet::dstBinding);
            if (w == dc.set_writes.end() || w->descriptorCount != 1 || w->dstArrayElement != 0 ||
                w->descriptorType != vk::DescriptorType::eSampledImage || !w->pImageInfo) {
                std::printf("Ivy material (t133h): image=%u binding=%u descriptor=unknown\n", i, binding);
                continue;
            }
            const auto id = dc.card_bound.ids[i];
            const auto uid = dc.card_bound.uids[i];
            const auto* image = texture_cache.TryGetImage(id, uid);
            const bool registered = image && texture_cache.IsRegisteredImage(id, uid);
            const auto& info = *w->pImageInfo;
            const VideoCore::ImageViewInfo guest(std::bit_cast<AmdGpu::Image>(draw.tsharps[i]),
                                                ps->images[i]);
            std::printf("Ivy material (t133h): image=%u binding=%u guest_id=%u uid=%llu seq=%llu "
                        "backing=%llx registered=%u host_view=%llx layout=%u guest_view=%u/%u "
                        "mip=%u+%u layer=%u+%u swizzle=%u/%u/%u/%u minlod=%g\n",
                        i, binding, id.index, Print64(uid), Print64(registered ? image->write_seq : 0),
                        Print64(registered ? std::bit_cast<u64>(image->GetImage()) : 0),
                        registered, Print64(std::bit_cast<u64>(info.imageView)), u32(info.imageLayout),
                        u32(guest.type), u32(guest.format), guest.range.base.level, guest.range.extent.levels,
                        guest.range.base.layer, guest.range.extent.layers, u32(guest.mapping.r),
                        u32(guest.mapping.g), u32(guest.mapping.b), u32(guest.mapping.a),
                        double(guest.min_lod));
            PrintBlob("tsharp", binding, ObjectBytes(draw.tsharps[i]));
            bound_images += bool(info.imageView);
        }
    }
    unsigned bound_samplers = 0;
    for (const auto& sampler : draw.sampler) {
        if (!sampler.seen) continue;
        std::printf("Ivy material (t133h): sampler binding=%u handle=%llx depth=%u bias=%.9g\n",
                    sampler.binding, Print64(sampler.handle), sampler.depth, double(sampler.lod_bias));
        PrintBlob("sampler-raw", sampler.binding, ObjectBytes(sampler.raw));
        PrintBlob("sampler-effective", sampler.binding, ObjectBytes(sampler.effective));
        bound_samplers += sampler.handle != 0;
    }
    unsigned retained_constants = 0;
    for (const auto& constants : draw.constants) {
        if (!constants.seen) continue;
        std::printf("Ivy material (t133h): buffer binding=%u guest=%llx handle=%llx range=%llu+%llu "
                    "shader_offset=%u retained=%u source=%s coverage=%s\n",
                    constants.binding, Print64(constants.guest), Print64(constants.handle),
                    Print64(constants.descriptor_offset), Print64(constants.descriptor_range),
                    constants.shader_offset, constants.size, constants.source, constants.Coverage());
        PrintBlob("constants", constants.binding, std::span(constants.bytes).first(constants.size));
        retained_constants += constants.size != 0;
    }

    if (const auto& module = selected.module) {
        std::printf("Ivy material (t133h): effective_hash=%016llx raw_hash=%016llx "
                    "effective_bytes=%zu raw_bytes=%zu raw_equal=%u\n",
                    Print64(module->effective_hash), Print64(module->raw_hash), module->effective.size(),
                    module->raw.empty() ? module->effective.size() : module->raw.size(),
                    module->raw.empty());
        PrintBlob("effective-module", 0, module->effective);
        PrintBlob("raw-module", 0, module->raw);
        PrintBlob("profile", 0, module->profile);
        PrintBlob("runtime", 0, module->runtime);
    }
    std::printf("Ivy material (t133h): end images=%u/%u samplers=%u/%u constants=%u/%u "
                "exact_module=%u complete_material=0\n",
                bound_images, draw.images, bound_samplers, draw.samplers, retained_constants,
                draw.buffers, bool(selected.module));
}

void Rasterizer::DrawIndirect(bool is_indexed, VAddr arg_address, u32 offset, u32 stride,
                              u32 max_count, VAddr count_address, u16 vertex_sgpr_offset,
                              u16 instance_sgpr_offset) {
    RENDERER_TRACE;
    if (occlusion) {
        occlusion->NoteIssued();
    }
    // bbport: like direct draws, handed to the recording thread after the pipeline selection
    // (else the GPU thread waited here for a whole frame of queued draws).
    const bool pipelined = UseDrawPipe() && FilterDrawPasses() &&
                           !BbToggle::Disabled(BbToggle::PipelinedIndirectDraws);
    if (!pipelined) {
        DrainDrawPipe();
        scheduler.PopPendingOperations();
        if (!FilterDraw()) {
            return;
        }
    }

    const DrawIndirectParams params = {
        .vertex_sgpr_offset = vertex_sgpr_offset,
        .instance_sgpr_offset = instance_sgpr_offset,
    };
    const u32 srt_faults = Shader::Info::srt_walk_faults;
    const GraphicsPipeline* pipeline = pipeline_cache.GetGraphicsPipeline(params);
    if (!pipeline || Shader::Info::srt_walk_faults != srt_faults) {
        return;
    }
    if (foliage_collect.load(std::memory_order_relaxed)) {
        pipeline_cache.PrepareFoliageVariant(*pipeline, params);
    }
    const IndirectDraw indirect = {arg_address + offset, count_address, stride, max_count};
    if (pipelined) {
        PostDraw(pipeline, nullptr, is_indexed, 0, nullptr, &indirect);
        return;
    }
    DrawIndirectRecord(pipeline, is_indexed, indirect);
}

void Rasterizer::DrawIndirectRecord(const GraphicsPipeline* pipeline, bool is_indexed,
                                    const IndirectDraw& indirect) {
    auto& dc = Dc();
    buffer_cache.NewPacket();
    if (DrawPipe::OnStageB()) {
        FrameCapture::Poll();
        scheduler.PopPendingOperations();
    }
    if (occlusion && occlusion->SkipDraw()) {
        return;
    }
    const VAddr count_address = indirect.count;
    const u32 stride = indirect.stride;
    const u32 max_count = indirect.max_count;

    // Indirect arguments may be GPU-written: leave these draws on camera fallback.
    dc.motion_draw = false;
    dc.capture_draw = false;
    dc.motion_geometry = 0;
    if (clean_shot_frame && CleanShotEarly(pipeline)) {
        return; // bbport (r77_parallel-test-runs): as in DrawRecord
    }
    if (sun_hold.active) { // r7_cascades
        SunHoldOther(&pipeline->GetStage(Shader::SwStage::Vertex),
                     pipeline->GetStages()[u32(Shader::SwStage::Fragment)], true);
    }
    PrepareRenderState(pipeline);
    NotifyUiDraw(pipeline);
    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): as EffectsBeforeResources; an
        BloodPoolProbeBefore(pipeline, true, false); // indirect draw is never taken for a light draw
    }
    if (!BindResources(pipeline)) {
        return;
    }
    if (foliage_mask) {
        FoliageCheckReceivers();
    }
    auto state = BeginRendering(pipeline); // (SunKeepBeforePass may take its clear over)
    if (surface_probe_on) { // bbport (r64_surface-probe): as for a direct draw, log only
        SurfaceProbeDraw(pipeline, true);
    }
    if (spark_probe_on) { // bbport (r108_spark-probe, TOOL): as for a direct draw, log only
        SparkProbeDraw(pipeline, true);
    }
    if (blood_pool_probe) { // bbport (r100d_blood-pool-draws, TOOL): as for a direct draw
        BloodPoolProbeNote(pipeline, true, is_indexed, 0u);
    }
    if (ProxyTraceOn()) {
        const auto target = cb_descs[0].first ? cb_descs[0].first : db_desc.first;
        FlushProxyReads(dc.push_data.scene_size != 0,
                        target ? &texture_cache.GetImage(target) : nullptr);
    }

    BindVertexBuffers(pipeline);
    if (is_indexed) {
        // bbport: an indirect draw's index count is in GPU memory; NUM_INDICES may be another
        // draw's (smaller) count. The buffer's own size (INDEX_BUFFER_SIZE) bounds what it can
        // read: the larger of the two is synced, so no indices are left stale.
        const auto& regs = Regs();
        const bool is_index16 = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16;
        const u32 index_size = is_index16 ? sizeof(u16) : sizeof(u32);
        // A stale or garbage size register is not trusted past 4M indices.
        const u32 capacity = regs.max_index_size <= (4u << 20) ? regs.max_index_size : 0u;
        const u32 index_bytes = std::max(regs.num_indices, capacity) * index_size;
        const auto [index_buffer, index_offset] = buffer_cache.ObtainBuffer(
            regs.index_base_address.Address<VAddr>(), index_bytes, false);
        dc.needs_barrier |= runtime.IsBufferAccessed(index_buffer, index_offset, index_bytes);
        dc.index_bind = {index_buffer->Handle(), index_offset,
                      is_index16 ? vk::IndexType::eUint16 : vk::IndexType::eUint32};
        EmitIndexBuffer();
    }

    const auto [buffer, base] =
        buffer_cache.ObtainBuffer(indirect.args, stride * max_count, false);
    dc.needs_barrier |= runtime.IsBufferAccessed(buffer, base, stride * max_count);

    const VideoCore::Buffer* count_buffer;
    u64 count_offset;
    if (count_address != 0) {
        std::tie(count_buffer, count_offset) = buffer_cache.ObtainBuffer(count_address, 4, false);
        dc.needs_barrier |= runtime.IsBufferAccessed(count_buffer, count_offset, 4);
    }

    if (dc.needs_barrier) {
        runtime.FlushBarriers();
    }

    // bbport: screen-space (clip disabled) draws into the upscaler's output-size images.
    dc.push_data.xscale *= target_scale[0];
    dc.push_data.xoffset = dc.push_data.xoffset*target_scale[0]+target_offset[0];
    dc.push_data.yscale *= target_scale[1];
    dc.push_data.yoffset = dc.push_data.yoffset*target_scale[1]+target_offset[1];
    if (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::VertexCapture) {
        dc.push_data.motion_param = 0;
    }
    const auto* raster_pipeline = foliage_mask
        ? FoliageAttach(pipeline, state, state, FoliageBoundary::Source::Indirect)
        : pipeline;
    raster_pipeline->BindResources(dc.set_writes, dc.push_data,
                                   {dc.image_infos.data(), dc.image_infos.size()},
                                   {dc.buffer_infos.data(), dc.buffer_infos.size()});
    if (raster_pipeline != pipeline) {
        ++mask_draws;
        scheduler.Record([raster_pipeline](vk::CommandBuffer cmd) {
            raster_pipeline->PushFoliageClass(cmd, false);
        });
    }
    if (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::VertexCapture) {
        rt_shadow->BindAddresses(raster_pipeline->GetLayout(), pipeline->GetGraphicsKey().motion_vectors);
    } else if (pipeline->GetGraphicsKey().motion_vectors) {
        object_motion->BindAddresses(raster_pipeline->GetLayout());
    }
    dc.draw_jitter = {};
    if (upscaler->Enabled() && db_desc.first && db_desc.first == camera_motion->Depth()) {
        dc.draw_jitter = upscaler->Jitter();
    }
    UpdateDynamicState(raster_pipeline, is_indexed);
    MarkPass(pipeline, state);
    if (SunKeepGate()) {
        SunKeepBeforePass(state, true); // bbport (r14_cascade_keep): never taken over here
    }
    scheduler.BeginRendering(state);
    if (sun_keep.atlas_pass) {
        SunKeepInPass(state); // an indirect draw into the atlas: every quadrant cleared first
    }
    // bbport: an indirect draw sampling the sun atlas (vk_rasterizer_effects.cpp).
    const auto* atlas_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    SunAtlasReader("the indirect draw ps", atlas_ps ? atlas_ps->pgm_hash : 0);

    ASSERT(stride == (is_indexed ? sizeof(VkDrawIndexedIndirectCommand)
                                 : sizeof(VkDrawIndirectCommand)));
    // bbport: never left out (what it draws is decided in GPU memory), bound late instead.
    vk::Pipeline handle = raster_pipeline->HandleIfReady();
    if (!handle) [[unlikely]] {
        handle = BindWhenCompiled(raster_pipeline, vk::PipelineBindPoint::eGraphics);
    }
    if (raster_pipeline != pipeline && pipeline_cache.BoundaryProbe().Active()) {
        FoliageObserveDraw(pipeline, FoliageBoundary::Source::Indirect, false);
    }
    const vk::Buffer args = buffer->Handle();
    const u64 args_offset = base;
    const vk::Buffer counts = count_address != 0 ? count_buffer->Handle() : vk::Buffer{};
    const u64 counts_offset = count_address != 0 ? count_offset : 0;
    const auto* vs_crumb = pipeline->GetStages()[u32(Shader::SwStage::Vertex)];
    const auto* ps_crumb = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const Breadcrumbs::Crumb crumb{
        .kind = Breadcrumbs::Kind::DrawIndirect,
        .hash = {vs_crumb ? vs_crumb->pgm_hash : 0, ps_crumb ? ps_crumb->pgm_hash : 0},
        .program = {vs_crumb ? vs_crumb->ProgramBase() : 0,
                    ps_crumb ? ps_crumb->ProgramBase() : 0},
        .address = indirect.args,
        .count = {max_count, stride, 0},
    };
    const auto query = occlusion ? occlusion->BeginDraw(dc.push_data.scene_size)
                                 : Occlusion::DrawQuery{};
    const auto workflow_query = workflow && workflow->querying
        ? WorkflowQueryDraw(raster_pipeline, state, {.indexed = is_indexed, .indirect = true,
                            .count_buffer = bool(counts), .command_limit = max_count, .command_stride = stride},
                            bool(query.pool))
        : WorkflowProbe::ScissorQuery{};
    if (upscaler->HasSewerBridge()) upscaler->SewerIndirectDisplayOrUi(cb_descs[0].first);
    auto record_draw = [=](vk::CommandBuffer cmdbuf) {
        if (handle) { // null: bound by the command before (BindWhenCompiled)
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, handle);
        }
        if (query.pool) {
            cmdbuf.beginQuery(query.pool, query.index, query.flags);
        }
        if (is_indexed) {
            if (counts) {
                cmdbuf.drawIndexedIndirectCount(args, args_offset, counts, counts_offset, max_count,
                                                stride);
            } else {
                cmdbuf.drawIndexedIndirect(args, args_offset, max_count, stride);
            }
        } else if (counts) {
            cmdbuf.drawIndirectCount(args, args_offset, counts, counts_offset, max_count, stride);
        } else {
            cmdbuf.drawIndirect(args, args_offset, max_count, stride);
        }
        if (query.pool) {
            cmdbuf.endQuery(query.pool, query.index);
        }
    };
    WorkflowRecordDraw(scheduler, crumb, std::move(record_draw), workflow_query, instance);
    if (BottleMotion::Run() && cb_descs[0].first) {
        const auto* image=texture_cache.TryGetImage(cb_descs[0].first,0);
        if (image && FrameCapture::IsDisplayBuffer(image->info.guest_address)) {
            upscaler->MotionIssuedDisplay(image->info.guest_address,state.color_attachments[0].image_view,{},false);
        }
    }
    if (workflow_query.pool && workflow->request.op == WorkflowProbe::Op::Resources)
        WorkflowCopyIndex(state, workflow_query.index);
    if (blood_pool_probe) { // bbport (r100c_blood-pool-probe, TOOL): as after a direct draw
        blood_pool_probe->AfterDraw();
    }
    DebugState.IncDrawCall();

    ResetBindings(false);
    scheduler.KickRecording();
}

void Rasterizer::DispatchDirect() {
    RENDERER_TRACE;
    BbStats::dispatches.fetch_add(1, std::memory_order_relaxed);
    // bbport: like draws, handed to the draw recording thread after the pipeline selection.
    const bool pipelined = UseDrawPipe() && !BbToggle::Disabled(BbToggle::PipelinedDispatch);
    if (!pipelined) {
        DrainDrawPipe();
    }
    const u32 srt_faults = Shader::Info::srt_walk_faults;
    const ComputePipeline* pipeline = pipeline_cache.GetComputePipeline();
    if (!pipeline || Shader::Info::srt_walk_faults != srt_faults) {
        return;
    }
    if (pipelined) {
        PostDraw(pipeline, nullptr, false, 0, &CsRegs());
        return;
    }
    DispatchRecord(pipeline);
}

// bbport (r11_native_compute): cs a040875f is the game's rectangle copy between two images. Its
// GCN code (33 dwords): x = group x * 8 + thread x, y likewise; image_load_mip of the source (T#
// in user data 4-11) at (x + cb[0], y + cb[1]); image_store of all four channels to the
// destination (T# read through the pointer in user data 2-3) at (x + cb[4], y + cb[5]) where
// x + cb[4] < cb[8] and y + cb[5] < cb[9] (unsigned); cb = the constant buffer whose V# is user
// data 12-15. The destination is only written. With reduced scene targets it is a proxied image (a
// proxy r10 made for a render-target copy) whose proxy is dirty, and the storage binding's Transit
// resolved it to the native size for the dispatch to overwrite it. A direct dispatch whose stores
// cover every texel of a single-level, single-layer destination (cb[4] = cb[5] = 0, groups * 8 and
// cb[8], cb[9] at least its size) drops the proxy contents without that resolve
// (SceneTargets::NativeOverwritten), as the render-target copy HLE does before its whole-image
// copy: the native image ends with the same bytes, the proxy in the same state (invalid).
// Indirect dispatches (GPU group counts) keep the resolve. Experiment bit 137438953472: resolved
// first, as before.
namespace {
constexpr u64 R11CopyRectHash = 0xa040875full;
/// This thread's direct dispatch of cs a040875f while it binds its images: its stores cover
/// [0, width) x [0, height) of the destination's level 0 when armed.
struct R11Store {
    bool armed = false;
    u32 width = 0, height = 0;
};
thread_local R11Store r11_store;
/// "Scene proxies:" line every 600 dispatches of cs a040875f at the reduced size. Dispatches are
/// recorded by one thread at a time (the draw recording thread, or the GPU command thread after a
/// drain).
struct R11Stats {
    u32 dispatches = 0, indirect = 0, unreadable = 0, not_armed = 0, proxied = 0, whole = 0,
        dropped = 0, clean = 0, not_whole = 0;
    u32 last[6]{}; ///< cb[4], cb[5], cb[8], cb[9], groups x and y of the last direct dispatch
    u32 last_w = 0, last_h = 0; ///< the last proxied destination's size
};
R11Stats r11_stats;
void R11Report() {
    auto& s = r11_stats;
    if (++s.dispatches < 600) {
        return;
    }
    std::printf("Scene proxies: of the last %u dispatches of cs a040875f at the reduced size (r11, "
                "rectangle copy), %u indirect (resolve kept), %u with unreadable constants, %u not "
                "storing from 0,0 in 8x8 groups; %u proxied destinations of the others: %u stored "
                "whole with a dirty proxy, %u of those resolves left out (experiment 137438953472 "
                "%s), %u without a dirty proxy, %u not covered (more levels or layers, a view of "
                "another level, or larger than the stores); last: destination offset %u,%u end "
                "%u,%u, groups %ux%u, destination %ux%u\n",
                s.dispatches, s.indirect, s.unreadable, s.not_armed, s.proxied, s.whole, s.dropped,
                BbToggle::Experiment(137438953472ull) ? "set: resolved first" : "clear", s.clean,
                s.not_whole, s.last[0], s.last[1], s.last[2], s.last[3], s.last[4], s.last[5],
                s.last_w, s.last_h);
    s = {};
}
} // namespace

void Rasterizer::DispatchRecord(const ComputePipeline* pipeline) {
    if (window_receiver && window_receiver->pane && window_receiver->pane->owner &&
        NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap::Dispatch)) {
        const auto& cs = pipeline->GetStage(Shader::SwStage::Compute);
        LogWindowOwnerGap("dispatch", fmt::format("cs={:x}", cs.pgm_hash).c_str());
    }
    auto& dc = Dc();
    BB_SECTION(DispatchRecord);
    buffer_cache.NewPacket();
    FrameCapture::Poll();
    gbuffer_draw = false;
    trees_pick_draw = false; // bbport (r86l_glint-pick-glass, TOOL)

    scheduler.PopPendingOperations();
    // bbport: lamps apart (vk_point_shadow.h): a compute pass may read or write the light targets
    // or the depth (as an image, through a buffer over their memory, as a copy done for it), and
    // only draws are looked at. The batch ends here. (In Bloodborne that is how every frame's
    // batch ends: a compute pass takes the light targets.)
    EffectsEndLampBatch();
    if (sun_hold.active) { // r7_cascades
        SunHoldOther(&pipeline->GetStage(Shader::SwStage::Compute), nullptr, false);
    }

    const auto& cs_program = CsRegs();

    const auto& cs = pipeline->GetStage(Shader::SwStage::Compute);
    BbSections::KeyScope dispatch_by_shader{BbSections::dispatch_by_shader, cs.pgm_hash};
    // After the resource binding: its transfers (image uploads, downloads) mark themselves.
    const auto mark = [&] {
        if (auto* profiler = GpuProfiler::Get()) {
            profiler->Mark(cs.pgm_hash ^ 0xD15Aull, [&] {
                return fmt::format("dispatch cs {:016x} ({}x{}x{} groups)", cs.pgm_hash,
                                   cs_program.dim_x, cs_program.dim_y, cs_program.dim_z);
            });
        }
    };
    if (upscaler->Enabled()) {
        // bbport: engine effects run before the upscaler's trigger (SceneUse; the upscaler
        // names itself inside OnDispatch).
        const SceneUseScope effects_use{"engine effects before the upscaler, at dispatch cs",
                                        cs.pgm_hash};
        EffectsBeforeUpscaler(cs.pgm_hash);
        upscaler->OnDispatch(cs.pgm_hash);
    }
    bool hle;
    {
        BB_SECTION(ShaderHle);
        // bbport: copy and clear HLEs (SceneUse; Runtime's copy and clear name themselves).
        const SceneUseScope hle_use{"shader HLE (copy or clear shader), cs", cs.pgm_hash};
        hle = ExecuteShaderHLE(cs, Regs(), cs_program, *this);
    }
    if (hle) {
        return;
    }

    // bbport (r11_native_compute): whether this dispatch of cs a040875f stores every texel of
    // its destination from 0,0 (R11Store; BindTextures checks the destination's size).
    const bool r11 = cs.pgm_hash == R11CopyRectHash && scene_targets->Reduced();
    r11_store = {};
    if (r11) {
        const auto cb = cs.FlatUserData().size() >= 16 ? cs.ReadUdSharp<AmdGpu::Buffer>(12)
                                                       : AmdGpu::Buffer{};
        const VAddr cb_address = cb.base_address;
        constexpr u32 cb_bytes = 10 * sizeof(u32);
        if (cb_address == 0 || cb.GetSize() < cb_bytes ||
            !memory->IsValidGpuMapping(cb_address, cb_bytes) ||
            buffer_cache.IsRegionGpuModified(cb_address, cb_bytes)) {
            ++r11_stats.unreadable;
        } else {
            std::array<u32, 10> c{};
            std::memcpy(c.data(), reinterpret_cast<const void*>(cb_address), cb_bytes);
            r11_stats.last[0] = c[4];
            r11_stats.last[1] = c[5];
            r11_stats.last[2] = c[8];
            r11_stats.last[3] = c[9];
            r11_stats.last[4] = cs_program.dim_x;
            r11_stats.last[5] = cs_program.dim_y;
            // The code's thread layout: 16 user SGPRs, then the group ids x and y (s16, s17),
            // x = group x * 8 + thread x (and y): groups of at least 8x8 threads leave no gap.
            const bool layout = cs_program.settings.num_user_regs == 16 &&
                                cs_program.IsTgidEnabled(0) && cs_program.IsTgidEnabled(1) &&
                                cs_program.num_thread_x.full >= 8 &&
                                cs_program.num_thread_y.full >= 8 && cs_program.dim_z != 0;
            if (layout && c[4] == 0 && c[5] == 0) {
                r11_store.armed = true;
                r11_store.width = u32(std::min<u64>(u64(cs_program.dim_x) * 8, c[8]));
                r11_store.height = u32(std::min<u64>(u64(cs_program.dim_y) * 8, c[9]));
            } else {
                ++r11_stats.not_armed;
            }
        }
    }
    const bool r11_bound = BindResources(pipeline);
    r11_store = {};
    if (r11) {
        R11Report();
    }
    if (!r11_bound) {
        return;
    }

    if (dc.needs_barrier) {
        runtime.FlushBarriers();
    }

    scheduler.EndRendering();
    mark();
    pipeline->BindResources(dc.set_writes, dc.push_data, {dc.image_infos.data(), dc.image_infos.size()},
                            {dc.buffer_infos.data(), dc.buffer_infos.size()});

    // bbport: dispatches are never left out; a compute pipeline still compiling is bound late.
    vk::Pipeline handle = pipeline->HandleIfReady();
    if (!handle) [[unlikely]] {
        handle = BindWhenCompiled(pipeline, vk::PipelineBindPoint::eCompute);
    }
    const u32 dim_x = cs_program.dim_x, dim_y = cs_program.dim_y, dim_z = cs_program.dim_z;
    if (FrameCapture::Active()) {
        FrameCapture::Dispatch(cs.pgm_hash, dim_x, dim_y, dim_z);
    }
    const Breadcrumbs::Crumb crumb{
        .kind = Breadcrumbs::Kind::Dispatch,
        .hash = {cs.pgm_hash, 0},
        .program = {cs.ProgramBase(), 0},
        .count = {dim_x, dim_y, dim_z},
    };
    scheduler.RecordCrumb(crumb, [=](vk::CommandBuffer cmdbuf) {
        if (handle) { // null: bound by the command before (BindWhenCompiled)
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, handle);
        }
        cmdbuf.dispatch(dim_x, dim_y, dim_z);
    });
    SunAtlasReader("the dispatch cs", cs.pgm_hash);
    DebugState.IncDispatch();
    // bbport BB_GPU_PROFILE_SPLIT=1: what is recorded after the dispatch without a label of its
    // own (barriers, transfers before the next pass or dispatch) gets its own row.
    if (auto* profiler = GpuProfiler::Get(); profiler && GpuProfiler::SplitMarks()) {
        profiler->Mark(cs.pgm_hash ^ 0xAF7Eull, [&] {
            return fmt::format("after dispatch cs {:016x}: unlabelled work until the next label",
                               cs.pgm_hash);
        });
    }

    ResetBindings(true);
    scheduler.KickRecording();
}

void Rasterizer::DispatchIndirect(VAddr address, u32 offset, u32 size) {
    RENDERER_TRACE;
    // bbport: handed to the recording thread like direct dispatches.
    const bool pipelined = UseDrawPipe() && !BbToggle::Disabled(BbToggle::PipelinedIndirectDraws);
    if (!pipelined) {
        DrainDrawPipe();
    }
    const u32 srt_faults = Shader::Info::srt_walk_faults;
    const ComputePipeline* pipeline = pipeline_cache.GetComputePipeline();
    if (!pipeline || Shader::Info::srt_walk_faults != srt_faults) {
        return;
    }
    if (pipelined) {
        const IndirectDraw indirect = {address + offset, 0, size, 1};
        PostDraw(pipeline, nullptr, false, 0, &CsRegs(), &indirect);
        return;
    }
    DispatchIndirectRecord(pipeline, address + offset, size);
}

std::pair<vk::Buffer, u64> Rasterizer::ClampDispatchArgs(const VideoCore::Buffer* buffer, u64 offset) {
    struct ClampPipeline {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
        std::array<u32, 3> limit{};
    };
    static ClampPipeline pipe = [&] {
        const auto device = instance.GetDevice();
        ClampPipeline p;
        std::array<vk::DescriptorSetLayoutBinding, 2> bindings{};
        for (u32 i = 0; i < bindings.size(); ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                           .descriptorCount = 1,
                           .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        p.set_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = static_cast<u32>(bindings.size()),
            .pBindings = bindings.data(),
        }));
        const vk::PushConstantRange range{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                          .offset = 0,
                                          .size = 4 * sizeof(u32)};
        p.layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1,
            .pSetLayouts = &*p.set_layout,
            .pushConstantRangeCount = 1,
            .pPushConstantRanges = &range,
        }));
        const auto module = CompileSPV(INDIRECT_CLAMP_COMP, device);
        p.pipeline = Check(device.createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{
                    .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                              .module = module,
                              .pName = "main"},
                    .layout = *p.layout,
                }));
        device.destroyShaderModule(module);
        const auto& counts = instance.GetPhysicalDevice().getProperties().limits.maxComputeWorkGroupCount;
        constexpr u32 kLargestRealCount = 65535;
        p.limit = {std::min(counts[0], kLargestRealCount), std::min(counts[1], kLargestRealCount),
                   std::min(counts[2], kLargestRealCount)};
        std::printf("GPU: an indirect dispatch whose group counts are over %u x %u x %u runs no groups "
                    "(BB_INDIRECT_CLAMP=0: as the game wrote them)\n",
                    p.limit[0], p.limit[1], p.limit[2]);
        return p;
    }();
    // The source range from an aligned offset; the counts are 3 dwords from `first` in it.
    const u64 align = instance.StorageMinAlignment();
    const u64 src_offset = Common::AlignDown(offset, align);
    const u64 src_size = offset - src_offset + 3 * sizeof(u32);
    auto& stream = buffer_cache.GetStreamBuffer();
    const auto slot = stream.Reserve(4 * sizeof(u32), align);
    if (!slot || (offset & 3) != 0) {
        return {buffer->Handle(), offset};
    }
    const std::array<u32, 4> push{pipe.limit[0], pipe.limit[1], pipe.limit[2],
                                  static_cast<u32>((offset - src_offset) / sizeof(u32))};
    scheduler.Record([src = buffer->Handle(), dst = stream.Handle(), src_offset, src_size,
                      dst_offset = *slot, push](vk::CommandBuffer cmdbuf) {
        const std::array<vk::DescriptorBufferInfo, 2> infos{{
            {src, src_offset, src_size},
            {dst, dst_offset, 4 * sizeof(u32)},
        }};
        std::array<vk::WriteDescriptorSet, 2> writes{};
        for (u32 i = 0; i < writes.size(); ++i) {
            writes[i] = {.dstBinding = i,
                         .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &infos[i]};
        }
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *pipe.pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *pipe.layout, 0, writes);
        cmdbuf.pushConstants(*pipe.layout, vk::ShaderStageFlagBits::eCompute, 0,
                             static_cast<u32>(sizeof(push)), push.data());
        cmdbuf.dispatch(1, 1, 1);
        const vk::MemoryBarrier2 clamped{
            .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eDrawIndirect,
            .dstAccessMask = vk::AccessFlagBits2::eIndirectCommandRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &clamped});
    });
    runtime.AccessBuffer(buffer, offset, 3 * sizeof(u32), vk::PipelineStageFlagBits2::eComputeShader,
                         vk::AccessFlagBits2::eShaderRead);
    return {stream.Handle(), *slot};
}

void Rasterizer::DispatchIndirectRecord(const ComputePipeline* pipeline, VAddr address,
                                        u32 size) {
    if (window_receiver && window_receiver->pane && window_receiver->pane->owner &&
        NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap::DispatchIndirect)) {
        const auto& cs = pipeline->GetStage(Shader::SwStage::Compute);
        LogWindowOwnerGap("dispatch-indirect",
                          fmt::format("cs={:x} args={:#x}+{:#x}", cs.pgm_hash, address, size).c_str());
    }
    auto& dc = Dc();
    buffer_cache.NewPacket();
    scheduler.PopPendingOperations();
    EffectsEndLampBatch(); // bbport: as in DispatchRecord
    if (sun_hold.active) { // r7_cascades
        SunHoldOther(&pipeline->GetStage(Shader::SwStage::Compute), nullptr, false);
    }
    const u32 offset = 0;
    // bbport (r11_native_compute): an indirect dispatch of cs a040875f keeps the resolve of its
    // destination (its group counts are GPU data).
    if (pipeline->GetStage(Shader::SwStage::Compute).pgm_hash == R11CopyRectHash &&
        scene_targets->Reduced()) {
        ++r11_stats.indirect;
        R11Report();
    }

    if (!BindResources(pipeline)) {
        return;
    }

    const auto [buffer, base] = buffer_cache.ObtainBuffer(address + offset, size, false);
    dc.needs_barrier |= runtime.IsBufferAccessed(buffer, base, size);

    if (dc.needs_barrier) {
        runtime.FlushBarriers();
    }

    scheduler.EndRendering();
    // bbport BB_GPU_PROFILE: indirect dispatches had no label, so their time was charged to the
    // label before them (the game's 1x1x1 "dispatch cs a954e79d" writes such arguments).
    if (auto* profiler = GpuProfiler::Get()) {
        const u64 indirect_hash = pipeline->GetStage(Shader::SwStage::Compute).pgm_hash;
        profiler->Mark(indirect_hash ^ 0x1D1E'C700ull, [&] {
            return fmt::format("dispatch indirect cs {:016x}", indirect_hash);
        });
    }
    // bbport: the counts clamped before the game's pipeline and descriptors are bound (the clamp
    // binds its own); the crash report keeps reading the game's counts (CopyArgs).
    static const bool clamp = [] {
        const char* env = std::getenv("BB_INDIRECT_CLAMP");
        return !(env && env[0] == '0');
    }();
    const std::pair<vk::Buffer, u64> dispatch =
        clamp ? ClampDispatchArgs(buffer, base) : std::pair<vk::Buffer, u64>{buffer->Handle(), base};
    const vk::Buffer dispatch_args = dispatch.first;
    const u64 dispatch_offset = dispatch.second;
    pipeline->BindResources(dc.set_writes, dc.push_data, {dc.image_infos.data(), dc.image_infos.size()},
                            {dc.buffer_infos.data(), dc.buffer_infos.size()});

    vk::Pipeline handle = pipeline->HandleIfReady();
    if (!handle) [[unlikely]] {
        handle = BindWhenCompiled(pipeline, vk::PipelineBindPoint::eCompute);
    }
    const vk::Buffer args = buffer->Handle();
    const u64 args_offset = base;
    const auto& cs_crumb = pipeline->GetStage(Shader::SwStage::Compute);
    const u32 args_slot = Breadcrumbs::ArgsSlot();
    const Breadcrumbs::Crumb crumb{
        .kind = Breadcrumbs::Kind::DispatchIndirect,
        .hash = {cs_crumb.pgm_hash, 0},
        .program = {cs_crumb.ProgramBase(), 0},
        .address = address,
        .count = {buffer_cache.IsInPlace(address, size) ? 1u : 0u, 0, 0},
        .args_slot = args_slot,
    };
    scheduler.RecordCrumb(crumb, [=](vk::CommandBuffer cmdbuf) {
        Breadcrumbs::CopyArgs(cmdbuf, args, args_offset, args_slot);
        if (handle) { // null: bound by the command before (BindWhenCompiled)
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, handle);
        }
        cmdbuf.dispatchIndirect(dispatch_args, dispatch_offset);
    });
    SunAtlasReader("the dispatch cs", cs_crumb.pgm_hash);
    DebugState.IncDispatch();

    ResetBindings(true);
    scheduler.KickRecording();
}

bool Rasterizer::SkipUncompiledDraw(const GraphicsPipeline* pipeline) {
    const u64 budget = SkipUncompiledBudgetNs();
    if (budget == 0) {
        return false;
    }
    // Scene geometry only (the draws the upscaler jitters): drawn with the scene depth, which
    // every frame draws again from a clear, and not a full-screen pass. The depth must also have
    // been the scene's the frame before: a G-buffer pass of its own (a reflection, drawn now and
    // then and kept) is not left out. Shadow maps, half-resolution effects, post-processing and
    // UI wait: what they draw may be kept over frames or read as a whole. A draw the game
    // measures (occlusion query) waits as well.
    const auto& regs = Regs();
    if (!db_desc.first || db_desc.first != camera_motion->Depth() ||
        db_desc.first != previous_scene_depth ||
        (regs.num_indices <= 6 && regs.num_instances.NumInstances() <= 1) ||
        (occlusion && occlusion->Measuring()) || FrameCapture::Active()) {
        return false;
    }
    const bool first = pipeline->first_skip_ns == 0;
    const u64 now = u64(std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now().time_since_epoch())
                            .count());
    if (!WithinSkipBudget(pipeline->first_skip_ns, now, budget)) {
        return false;
    }
    pipeline_compile_stats.skipped_draws.fetch_add(1, std::memory_order_relaxed);
    if (first) {
        pipeline_compile_stats.skipped_pipelines.fetch_add(1, std::memory_order_relaxed);
    }
    return true;
}

vk::Pipeline Rasterizer::BindWhenCompiled(const Pipeline* pipeline,
                                          vk::PipelineBindPoint bind_point) {
    if (!LatePipelineBindEnabled() || !scheduler.IsRecordingDeferred()) {
        return pipeline->Handle(); // waits here (and compiles it here when still queued)
    }
    // The recording thread that runs this waits for the compile (or compiles it, when still
    // queued): the draws after it are recorded meanwhile, and drains of the GPU command thread
    // (write faults, readbacks for guest threads) do not wait for the compile.
    pipeline_compile_stats.late_binds.fetch_add(1, std::memory_order_relaxed);
    scheduler.Record([pipeline, bind_point](vk::CommandBuffer cmdbuf) {
        cmdbuf.bindPipeline(bind_point, pipeline->Handle());
    });
    return {};
}

bool Rasterizer::OcclusionDump(VAddr va, u32 pipes) {
    if (!occlusion || (va & 7) != 0) {
        return false;
    }
    // In order with the draws: the dump closes the interval of draws recorded before it.
    const auto task = occlusion->MakeDump(va, pipes);
    RunInOrder(
        [](Rasterizer& self, const u8* data) {
            Occlusion::DumpTask dump;
            std::memcpy(&dump, data, sizeof(dump));
            self.occlusion->Dump(dump);
        },
        &task, sizeof(task), BbToggle::PipelinedTasks, false, "OcclusionDump");
    return true;
}

bool Rasterizer::OcclusionPredication(const u32* body) {
    if (!occlusion) {
        return false;
    }
    // [0] start address lo (16-byte aligned), [1] address hi[7:0] | PRED_BOOL[8] (1: draw if
    // visible) | HINT[12] | PRED_OP[18:16] (0 clear, 1 ZPASS, 2 primitive count) | CONTINUE[31].
    // The game: Gnm's setZPassPredicationEnable(block, hint 0, draw if visible) and Disable.
    const Occlusion::PredicationTask task{
        .block = (VAddr(body[1] & 0xff) << 32) | (body[0] & ~0xfu),
        .op = (body[1] >> 16) & 7,
        .draw_if_visible = u8((body[1] >> 8) & 1),
        .cont = u8(body[1] >> 31),
    };
    static u32 logged = 0;
    if (logged < 4) {
        ++logged;
        std::printf("Occlusion: SET_PREDICATION block %#llx op %u draw-if-visible %u hint %u "
                    "continue %u\n",
                    static_cast<unsigned long long>(task.block), task.op, task.draw_if_visible,
                    (body[1] >> 12) & 1, task.cont);
    }
    occlusion->predication_open = task.op != 0;
    RunInOrder(
        [](Rasterizer& self, const u8* data) {
            Occlusion::PredicationTask set;
            std::memcpy(&set, data, sizeof(set));
            self.occlusion->SetPredication(set);
        },
        &task, sizeof(task), BbToggle::PipelinedTasks, false, "SetPredication");
    return true;
}

bool Rasterizer::OcclusionUnsubmitted() const {
    return occlusion && occlusion->HasUnsubmittedDumps(scheduler.CurrentTick());
}

void Rasterizer::OcclusionSubmissionStart() {
    if (!occlusion || !occlusion->predication_open) {
        return;
    }
    // The predicate bit is per packet in the command buffer that set it: a region does not
    // carry over into the next submission.
    const u32 clear[2] = {0, 0};
    OcclusionPredication(clear);
}

u64 Rasterizer::Flush() {
    BB_SECTION(Flush);
    // bbport (r27_flush-split): timed inside a stage B task, or as its own on stage B
    const BbSpike::SplitScope r27_split{BbSpike::SplitFlush,
                                        BbSpike::on && DrawPipe::OnStageB(),
                                        "Flush outside a task"};
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitDrain};
        DrainDrawPipe();
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitPublish};
        PublishSignals(); // the recording thread's (it is idle here, or this is it)
    }
    last_flush_ns.store(std::chrono::steady_clock::now().time_since_epoch().count(),
                        std::memory_order_relaxed);
    const u64 current_tick = scheduler.CurrentTick();
    SubmitInfo info{};
    scheduler.Flush(info);
    BbTimeline::Note(BbTimeline::VulkanSubmit, current_tick, DrawPipe::OnStageB() ? 1 : 0);
    return current_tick;
}

void Rasterizer::Finish() {
    DrainDrawPipe();
    PublishSignals();
    scheduler.Finish();
}

void Rasterizer::OnSubmit() {
    DrainDrawPipe();
    // bbport (r27_flush-split): each call timed (BB_SPIKE_TRACE=1, stage B's tasks only)
    if (fault_process_pending) {
        fault_process_pending = false;
        const BbSpike::SplitScope r27_step{BbSpike::SplitFaultBuffer};
        buffer_cache.ProcessFaultBuffer();
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitDownloads};
        texture_cache.ProcessDownloadImages();
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitKeyPrompts};
        texture_cache.UpdateKeyPrompts();
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitCollector};
        texture_cache.RunGarbageCollector();
    }
    const BbSpike::SplitScope r27_step{BbSpike::SplitTickFrame};
    runtime.TickFrame();
}

const PreparedStage* Rasterizer::FindPreparedStage(const Shader::Info& stage) const {
    auto& dc = Dc();
    // Sharps a draw-preparation worker read from the same flattened user data.
    if (!dc.bind_prepared || BbToggle::Disabled(BbToggle::PreparedResources)) {
        return nullptr;
    }
    return FindPreparedStage(dc.bind_prepared, stage);
}

const PreparedStage* Rasterizer::FindPreparedStage(const PreparedDraw* prepared,
                                                   const Shader::Info& stage) {
    if (!prepared) {
        return nullptr;
    }
    for (u32 i = 0; i < prepared->num_stages; ++i) {
        const auto& candidate = prepared->stages[i];
        if (&candidate.program->info == &stage &&
            candidate.num_images == stage.images.size() &&
            candidate.num_samplers == stage.samplers.size() &&
            candidate.num_buffers == stage.buffers.size()) {
            return &candidate;
        }
    }
    return nullptr;
}

bool Rasterizer::BindHelperWanted() {
    // A spinning helper pays off only with cores to spare (the recording thread spins too).
    const char* env = std::getenv("BB_TEXTURE_HELPER");
    if (env && env[0]) {
        return env[0] == '1';
    }
    // Measured neutral on 16 threads (docs/parallel_gpu.md): opt-in.
    return false;
}

bool Rasterizer::HelperEligible(const Pipeline* pipeline) const {
    if (pipeline->IsCompute() || !bind_helper.Available() || FrameCapture::Active() ||
        BbToggle::Disabled(BbToggle::TextureBindHelper) ||
        BbToggle::Disabled(BbToggle::TextureBindingMemo) ||
        BbToggle::Disabled(BbToggle::UpdateImageFastPath)) {
        return false;
    }
    for (const auto* stage : pipeline->GetStages()) {
        if (!stage) {
            continue;
        }
        // Mip arrays make the descriptor layout depend on the T#s.
        for (const auto& image : stage->images) {
            if (image.mip_fallback_mode != Shader::MipStorageFallbackMode::None) {
                return false;
            }
        }
        // Storage writes invalidate cached images from the buffer side.
        for (const auto& buffer : stage->buffers) {
            if (!buffer.IsSpecial() && buffer.is_written) {
                return false;
            }
        }
    }
    return true;
}

bool Rasterizer::TexturesBindableOnHelper(const Shader::Info& stage,
                                          const PreparedStage* prepared) {
    const u64 generation = texture_cache.RegistryGeneration();
    for (u32 image_index = 0; image_index < stage.images.size(); ++image_index) {
        const auto& image_desc = stage.images[image_index];
        if (image_desc.is_written) {
            return false;
        }
        const auto tsharp =
            prepared ? prepared->image_sharps[image_index] : image_desc.GetSharp(stage);
        const auto data_fmt = tsharp.GetDataFmt();
        const auto num_fmt = tsharp.GetNumberFmt();
        if (tsharp.Address() == 0 || data_fmt == AmdGpu::DataFormat::FormatInvalid ||
            !memory->IsValidGpuMapping(tsharp.Address(), 0) ||
            !IsKnownFormat(data_fmt, num_fmt)) {
            continue; // null descriptor
        }
        auto& entry =
            prepared ? CachedImageDescEntry(tsharp, image_desc, prepared->image_hashes[image_index])
                     : CachedImageDescEntry(tsharp, image_desc);
        if (!LookupMemoized(entry, generation)) {
            return false;
        }
        VideoCore::ImageId image_id = entry.found_id;
        auto* image = &texture_cache.GetImage(image_id);
        if (const auto depth_image_id = texture_cache.GetAssociatedDepth(*image)) {
            image_id = depth_image_id;
            image = &texture_cache.GetImage(image_id);
        }
        // bbport: a UI replacement made on the UI worker is uploaded by the GPU thread
        // (TextureCache::UiReplacement).
        if (image->binding.needs_rebind || !texture_cache.IsUpToDate(image_id) ||
            scene_targets->Tracks(image->image_uid) ||
            (upscaler->Enabled() && upscaler->RedirectsSampled(image_id)) ||
            (image->ui_key && texture_cache.UiReplacementPending(image->ui_key))) {
            return false;
        }
    }
    return true;
}

void Rasterizer::RunTextureTask(void* context) {
    auto& self = *static_cast<Rasterizer*>(context);
    auto& task = self.texture_task;
    for (u32 i = 0; i < task.count; ++i) {
        auto& stage = task.stages[i];
        if (!self.TexturesBindableOnHelper(*stage.info, stage.prepared)) {
            return;
        }
        auto binding = stage.binding;
        u32 write_index = stage.write_index;
        self.BindTextures(*stage.info, stage.prepared, binding, write_index, task.barrier, true);
        task.completed = i + 1;
    }
}

void Rasterizer::JoinBindHelper(void* context) {
    if (!BindHelper::OnHelper()) {
        static_cast<Rasterizer*>(context)->bind_helper.Join();
    }
}

bool Rasterizer::BindResources(const Pipeline* pipeline) {
    auto& dc = Dc();
    BB_SECTION(BindResources);
    if (IsComputeImageCopy(pipeline) || IsComputeMetaClear(pipeline) ||
        IsComputeImageClear(pipeline)) {
        return false;
    }

    dc.set_write_index = 0;
    dc.set_writes.clear();
    dc.buffer_infos.clear();
    dc.image_infos.clear();
    // bbport: G-buffer passes sample material textures for a scene rendered below the output
    // size; the temporal upscaler restores the detail of the output's mip level (FSR guide:
    // log2(render / output)). Shadows, post-processing and UI keep the guest's bias.
    dc.sampler_lod_bias = 0.0f;
    dc.pipeline_is_compute = pipeline->IsCompute();
    dc.ui_movie_draw = !pipeline->IsCompute() &&
                    (ui_pass.active ||
                     UiComposition::MovieShader(static_cast<const GraphicsPipeline*>(pipeline)
                                                    ->GetStage(Shader::SwStage::Vertex)
                                                    .pgm_hash));
    if (dc.ui_movie_draw) {
        const auto& blend = Regs().blend_control[0];
        // Weighted by the texel's alpha, a transparent gap adds nothing.
        dc.ui_additive = blend.enable &&
                      blend.color_dst_factor == AmdGpu::BlendControl::BlendFactor::One &&
                      blend.color_src_factor != AmdGpu::BlendControl::BlendFactor::SrcAlpha;
    }
    if (!pipeline->IsCompute() && !BbToggle::Disabled(BbToggle::SceneMipBias) &&
        std::popcount(static_cast<const GraphicsPipeline*>(pipeline)->GetGraphicsKey().mrt_mask &
                      0xff) >= 5) {
        dc.sampler_lod_bias = upscaler->SceneMipBias();
        static float reported = 0.0f;
        if (dc.sampler_lod_bias != reported) {
            reported = dc.sampler_lod_bias;
            std::printf("Upscaler: scene texture LOD bias %.2f\n", dc.sampler_lod_bias);
        }
    }

    bool uses_dma = false;

    static const bool stats = std::getenv("BB_FRAME_STATS") != nullptr;
    if (stats && ((helper_full + helper_partial + helper_serial) & 1023) == 0) {
        static auto window = std::chrono::steady_clock::now();
        const auto now = std::chrono::steady_clock::now();
        if (now - window >= std::chrono::seconds(5)) {
            window = now;
            const double forks = std::max<double>(1, helper_full + helper_partial);
            std::printf("Texture helper: %llu binds in parallel, %llu partly, %llu serial; "
                        "per fork %.0f cycles helper task, %.0f cycles GPU thread wait\n",
                        static_cast<unsigned long long>(helper_full),
                        static_cast<unsigned long long>(helper_partial),
                        static_cast<unsigned long long>(helper_serial),
                        bind_helper.task_cycles.exchange(0) / forks,
                        bind_helper.wait_cycles / forks);
            bind_helper.wait_cycles = 0;
            helper_full = helper_partial = helper_serial = 0;
        }
    }

    // Bind resource buffers and textures.
    Shader::Backend::Bindings binding{};
    dc.push_data = MakeUserData(Regs());
    if (!HelperEligible(pipeline)) {
        ++helper_serial;
        for (const auto* stage : pipeline->GetStages()) {
            if (!stage) {
                continue;
            }
            dc.set_writes.resize(dc.set_writes.size() + stage->buffers.size() + stage->images.size() +
                              stage->samplers.size());
            stage->PushUd(binding, dc.push_data);
            const PreparedStage* prepared = FindPreparedStage(*stage);
            BindBuffers(*stage, prepared, binding, dc.push_data, dc.set_write_index);
            BindTextures(*stage, prepared, binding, dc.set_write_index, dc.needs_barrier);
            uses_dma |= stage->uses_dma;
        }
    } else {
        // bbport: textures on the helper, buffers here. Without mip arrays every stage's
        // descriptors are [buffers][images][samplers], one each, so both sides know their
        // binding numbers and descriptor write slots up front.
        struct BufferStage {
            const Shader::Info* info;
            const PreparedStage* prepared;
            Shader::Backend::Bindings binding;
            u32 write_index;
        };
        std::array<BufferStage, Shader::MaxStageTypes> buffer_stages;
        auto& task = texture_task;
        task.count = 0;
        task.completed = 0;
        task.barrier = false;
        for (const auto* stage : pipeline->GetStages()) {
            if (!stage) {
                continue;
            }
            const u32 num_buffers = static_cast<u32>(stage->buffers.size());
            const u32 num_descriptors =
                num_buffers + static_cast<u32>(stage->images.size() + stage->samplers.size());
            dc.set_writes.resize(dc.set_writes.size() + num_descriptors);
            stage->PushUd(binding, dc.push_data);
            const PreparedStage* prepared = FindPreparedStage(*stage);
            buffer_stages[task.count] = {stage, prepared, binding, dc.set_write_index};
            auto texture_binding = binding;
            texture_binding.buffer += num_buffers;
            texture_binding.unified += num_buffers;
            task.stages[task.count] = {stage, prepared, texture_binding,
                                       dc.set_write_index + num_buffers};
            ++task.count;
            binding.buffer += num_buffers;
            binding.unified += num_descriptors;
            dc.set_write_index += num_descriptors;
            uses_dma |= stage->uses_dma;
        }
        bind_helper.Fork(&RunTextureTask, this);
        for (u32 i = 0; i < task.count; ++i) {
            auto& stage = buffer_stages[i];
            BindBuffers(*stage.info, stage.prepared, stage.binding, dc.push_data, stage.write_index);
        }
        if (dc.draw_inputs.pending && !BbToggle::Disabled(BbToggle::EarlyDrawInputs)) {
            ResolveVertexBuffers(dc.draw_inputs.pipeline, dc.draw_inputs.prepared);
            if (dc.draw_inputs.is_indexed) {
                ResolveIndexBuffer(dc.draw_inputs.index_offset);
            }
            dc.draw_inputs.resolved = true;
        }
        bind_helper.Join();
        dc.needs_barrier |= task.barrier;
        ++(task.completed == task.count ? helper_full
                                        : task.completed ? helper_partial : helper_serial);
        // Stages the helper left (an image needing work that records commands).
        for (u32 i = task.completed; i < task.count; ++i) {
            auto& stage = task.stages[i];
            u32 write_index = stage.write_index;
            BindTextures(*stage.info, stage.prepared, stage.binding, write_index, dc.needs_barrier);
        }
    }

    if (uses_dma) {
        buffer_cache.SynchronizeDmaBuffers();
        fault_process_pending = true;
    }

    return true;
}

void Rasterizer::BindVertexBuffers(const GraphicsPipeline* pipeline, const PreparedDraw* prepared) {
    ResolveVertexBuffers(pipeline, prepared);
    EmitVertexBuffers();
}

// bbport (r21_draw-sort): whether this draw's vertex input, vertex buffer and index buffer binds
// may be left out when equal to those in force (experiment 70368744177664 clear; the vertex input
// dynamic in every graphics pipeline). What r21_bound holds is forgotten when a command that may
// have changed it was recorded since (Scheduler::R21Serial), or commands go to another command
// buffer since (R21Epoch).
bool Rasterizer::R21Begin(bool dynamic_input) {
    auto& m = r21_bound;
    const bool on = dynamic_input && !BbToggle::Experiment(R21DrawSortOffBit);
    if (!on || m.serial != scheduler.R21Serial() || m.epoch != scheduler.R21Epoch()) {
        m.input_known = m.buffers_known = m.index_known = false;
    }
    return on;
}

// bbport (r21_draw-sort): after the binds just recorded (`serial`, `epoch`: R21Serial() and
// R21Epoch() before them). A vertex input, vertex buffer or index buffer bind leaves the other two
// as they are: R21Serial() is put back.
void Rasterizer::R21End(bool on, u64 serial, u64 epoch) {
    auto& m = r21_bound;
    if (on) {
        scheduler.R21Restore(serial);
    }
    m.serial = scheduler.R21Serial();
    m.epoch = epoch;
    if (!on || scheduler.R21Epoch() != epoch) { // off, or the binds went into two command buffers
        m.input_known = m.buffers_known = m.index_known = false;
    }
}

// bbport (r21_draw-sort): a direct draw reached its draw command. Counts what its binds did
// (r21_outcome) for all draws and sun atlas draws; for the atlas also its pipeline against the
// atlas draw before it in the same render pass (a pass a cut resumed is the same pass). "Draw
// order (r21)" every 600 frames; a window holds frames of one experiment setting only.
// BB_DRAW_ORDER=1 only (R21Counting).
void Rasterizer::R21AfterDraw(const GraphicsPipeline* pipeline, bool is_indexed) {
    auto& s = r21_stats;
    const R21Outcome outcome = std::exchange(r21_outcome, R21Outcome{});
    const u32 frame = BbStats::frame_number.load(std::memory_order_relaxed);
    if (frame != s.frame) {
        s.frame = frame;
        s.frame_seen_n = 0;
        if (const bool off = BbToggle::Experiment(R21DrawSortOffBit); off != s.window_off) {
            // The bit changed: the counts so far are dropped, a new window starts.
            s.window_off = off;
            s.frames = 0;
            s.c = {};
            s.pass = ~0ull;
        } else if (++s.frames >= 600) {
            const double f = double(s.frames);
            const auto& c = s.c;
            const auto x = [f](u64 value) { return double(value) / f; };
            const auto& a = c.atlas.binds;
            const auto& d = c.all.binds;
            if (off) {
                std::printf("Draw order (r21): experiment 70368744177664 set (every bind recorded "
                            "as before, nothing counted)\n");
            } else {
                std::printf(
                    "Draw order (r21): experiment 70368744177664 clear (equal binds left out); a "
                    "frame: sun atlas %.1f draws in %.1f passes, pipeline changes %.1f (a pass's "
                    "first draw counts), fewest with each pass grouped by pipeline %.1f, distinct "
                    "pipelines %.1f; atlas binds: vertex input left out %.1f, recorded %.1f "
                    "(another in force %.1f, unknown %.1f), vertex buffers left out %.1f, recorded "
                    "%.1f (%.1f, %.1f), index buffer left out %.1f, recorded %.1f (%.1f, %.1f), "
                    "descriptor binds %.1f (each recorded); all %.1f direct draws: vertex input "
                    "left out %.1f, recorded %.1f (%.1f, %.1f), vertex buffers left out %.1f, "
                    "recorded %.1f (%.1f, %.1f), index buffer left out %.1f, recorded %.1f (%.1f, "
                    "%.1f), descriptor binds %.1f\n",
                    x(c.atlas.draws), x(c.atlas_passes), x(c.atlas_changes),
                    x(c.atlas_pass_distinct), x(c.atlas_frame_distinct), x(a[0][1]),
                    x(a[0][2] + a[0][3]), x(a[0][2]), x(a[0][3]), x(a[1][1]),
                    x(a[1][2] + a[1][3]), x(a[1][2]), x(a[1][3]), x(a[2][1]),
                    x(a[2][2] + a[2][3]), x(a[2][2]), x(a[2][3]), x(c.atlas.descriptors),
                    x(c.all.draws), x(d[0][1]), x(d[0][2] + d[0][3]), x(d[0][2]), x(d[0][3]),
                    x(d[1][1]), x(d[1][2] + d[1][3]), x(d[1][2]), x(d[1][3]), x(d[2][1]),
                    x(d[2][2] + d[2][3]), x(d[2][2]), x(d[2][3]), x(c.all.descriptors));
            }
            s.frames = 0;
            s.c = {};
        }
    }
    if (s.window_off) {
        return;
    }
    const u64 pass = scheduler.R21FreshPasses();
    if (pass != s.pass) {
        s.pass = pass;
        s.atlas_pass = sun_atlas.address && db_desc.first &&
                       texture_cache.GetImage(db_desc.first).info.guest_address == sun_atlas.address;
        s.atlas_last = nullptr;
        s.pass_seen_n = 0;
        s.c.atlas_passes += s.atlas_pass ? 1u : 0u;
    }
    const bool descriptors = !Dc().set_writes.empty();
    const auto count = [&](R21Row& row) {
        ++row.draws;
        ++row.binds[0][outcome.input];
        ++row.binds[1][outcome.buffers];
        ++row.binds[2][is_indexed ? outcome.index : 0u];
        row.descriptors += descriptors ? 1u : 0u;
    };
    count(s.c.all);
    if (!s.atlas_pass) {
        return;
    }
    count(s.c.atlas);
    if (pipeline == s.atlas_last) {
        return; // already in both lists below
    }
    s.atlas_last = pipeline;
    ++s.c.atlas_changes;
    // Distinct pipelines (a full list counts every later one as new: an upper bound).
    const auto note = [pipeline](auto& seen, u32& n, u64& distinct) {
        for (u32 i = 0; i < n; ++i) {
            if (seen[i] == pipeline) {
                return;
            }
        }
        if (n < seen.size()) {
            seen[n++] = pipeline;
        }
        ++distinct;
    };
    note(s.pass_seen, s.pass_seen_n, s.c.atlas_pass_distinct);
    note(s.frame_seen, s.frame_seen_n, s.c.atlas_frame_distinct);
}

void Rasterizer::EmitVertexBuffers() {
    auto& dc = Dc();
    BB_SECTION(EmitVertexBuffers);
    // bbport: only the used entries go into the recording chunk (the static vectors hold 32 of
    // each: ~3 KiB copied per draw).
    auto& v = dc.vertex_binds;
    const bool dynamic_input = instance.IsVertexInputDynamicState();
    const u32 num_buffers = v.num_buffers;
    // bbport (r21_draw-sort): a vertex input or vertex buffer bind equal to the one in force is
    // left out (R21Begin); the binds recorded here leave each other and the index buffer's alone.
    auto& m = r21_bound;
    const bool r21 = R21Begin(dynamic_input);
    const u64 r21_serial = scheduler.R21Serial();
    const u64 r21_epoch = scheduler.R21Epoch();
    const bool same_input =
        r21 && m.input_known &&
        std::equal(v.bindings.begin(), v.bindings.end(), m.bindings.begin(), m.bindings.end(),
                   [](const auto& a, const auto& b) {
                       return !a.pNext && !b.pNext && a.binding == b.binding &&
                              a.stride == b.stride && a.inputRate == b.inputRate &&
                              a.divisor == b.divisor;
                   }) &&
        std::equal(v.attributes.begin(), v.attributes.end(), m.attributes.begin(),
                   m.attributes.end(), [](const auto& a, const auto& b) {
                       return !a.pNext && !b.pNext && a.location == b.location &&
                              a.binding == b.binding && a.format == b.format &&
                              a.offset == b.offset;
                   });
    const bool same_buffers =
        r21 && num_buffers != 0 && m.buffers_known && m.num_buffers == num_buffers &&
        std::equal(v.host_buffers.begin(), v.host_buffers.begin() + num_buffers,
                   m.buffers.begin(), m.buffers.end()) &&
        std::equal(v.host_offsets.begin(), v.host_offsets.begin() + num_buffers,
                   m.offsets.begin(), m.offsets.end());
    r21_outcome.input = !r21 ? 0 : same_input ? 1 : m.input_known ? 2 : 3;
    r21_outcome.buffers =
        !r21 || num_buffers == 0 ? 0 : same_buffers ? 1 : m.buffers_known ? 2 : 3;
    if (same_input && (num_buffers == 0 || same_buffers)) {
        return; // r21: nothing to record; r21_bound is still in force
    }
    scheduler.ReserveRecordData(
        v.bindings.size() * sizeof(v.bindings[0]) + v.attributes.size() * sizeof(v.attributes[0]) +
        num_buffers * (sizeof(vk::Buffer) + 3 * sizeof(vk::DeviceSize)) + 128);
    if (dynamic_input && !same_input) {
        scheduler.Record([bindings = scheduler.RecordData(std::span<const vk::VertexInputBindingDescription2EXT>{v.bindings.data(), v.bindings.size()}),
                          attributes = scheduler.RecordData(std::span<const vk::VertexInputAttributeDescription2EXT>{
                              v.attributes.data(), v.attributes.size()})](
                             vk::CommandBuffer cmdbuf) {
            cmdbuf.setVertexInputEXT(bindings, attributes);
        });
        if (r21) {
            m.bindings.assign(v.bindings.begin(), v.bindings.end());
            m.attributes.assign(v.attributes.begin(), v.attributes.end());
            m.input_known = true;
        }
    }
    if (num_buffers == 0 || same_buffers) {
        R21End(r21, r21_serial, r21_epoch);
        return;
    }
    const auto buffers = scheduler.RecordData(std::span<const vk::Buffer>{v.host_buffers.data(), num_buffers});
    const auto offsets = scheduler.RecordData(std::span<const vk::DeviceSize>{v.host_offsets.data(), num_buffers});
    if (dynamic_input) {
        scheduler.Record([num_buffers, buffers, offsets](vk::CommandBuffer cmdbuf) {
            cmdbuf.bindVertexBuffers(0, num_buffers, buffers.data(), offsets.data());
        });
        if (r21) {
            m.buffers.assign(v.host_buffers.begin(), v.host_buffers.begin() + num_buffers);
            m.offsets.assign(v.host_offsets.begin(), v.host_offsets.begin() + num_buffers);
            m.num_buffers = num_buffers;
            m.buffers_known = true;
        }
        R21End(r21, r21_serial, r21_epoch);
        return;
    }
    const auto sizes = scheduler.RecordData(std::span<const vk::DeviceSize>{v.host_sizes.data(), num_buffers});
    const auto strides = scheduler.RecordData(std::span<const vk::DeviceSize>{v.host_strides.data(), num_buffers});
    scheduler.Record([num_buffers, buffers, offsets, sizes, strides](vk::CommandBuffer cmdbuf) {
        cmdbuf.bindVertexBuffers2(0, num_buffers, buffers.data(), offsets.data(), sizes.data(),
                                  strides.data());
    });
    R21End(r21, r21_serial, r21_epoch);
}

void Rasterizer::ResolveVertexBuffers(const GraphicsPipeline* pipeline,
                                      const PreparedDraw* prepared) {
    auto& dc = Dc();
    BB_SECTION(ResolveVertexBuffers);
    const auto& regs = Regs();
    auto& v = dc.vertex_binds;
    v.num_buffers = 0;
    v.host_buffers.clear();
    v.host_offsets.clear();
    v.host_sizes.clear();
    v.host_strides.clear();
    auto& attributes = v.attributes;
    auto& bindings = v.bindings;
    attributes.clear();
    bindings.clear();
    VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT> divisors;
    VertexInputs<AmdGpu::Buffer> guest_buffers;
    // Inputs a draw-preparation worker read from the same registers and (verified) user data.
    const auto& fetch = pipeline->GetFetchShader();
    const bool record_position = workflow && workflow->querying && workflow->request.op == WorkflowProbe::Op::Resources;
    if (record_position) {
        workflow->position = {};
        workflow->position_observation = {};
    }
    const auto remember_position = [&](size_t i, const VideoCore::Buffer* b, u64 offset, u64 size,
                                       const char* route) {
        if (!record_position || i >= attributes.size() || attributes[i].location != 0) return;
        auto& observation = workflow->position_observation;
        auto facts = observation;
        const auto& attribute = attributes[i];
        facts.bind_route = route;
        facts.slot = u32(i);
        facts.binding = attribute.binding;
        facts.format = u32(attribute.format);
        facts.attribute_offset = attribute.offset;
        facts.buffer_present = b != nullptr;
        facts.buffer_valid = b && bool(b->Handle());
        facts.source_offset = offset;
        facts.bound_bytes = size;
        facts.range_known = b && offset <= b->SizeBytes();
        facts.capacity_remaining = facts.range_known ? b->SizeBytes() - offset : 0;
        facts.transfer_src = b &&
            (bool(b->buffer.allocation) || b->mem_type == VideoCore::MemoryType::Sparse);
        if (i < bindings.size()) {
            facts.binding_description = bindings[i].binding;
            facts.rate = u32(bindings[i].inputRate);
            facts.stride = bindings[i].stride;
        }
        const auto refuse = [&](const char* reason) {
            if (observation.slot == WorkflowProbe::PositionObservation::Unknown) {
                facts.reason = reason;
                observation = facts;
            }
        };
        if (!b) return refuse("no_resolved_vertex_buffer");
        if (i >= bindings.size()) return refuse("missing_binding_description");
        if (bindings[i].binding != 0 || attribute.binding != 0) return refuse("nonzero_position_binding");
        if (attribute.offset) return refuse("nonzero_attribute_offset");
        if (bindings[i].inputRate != vk::VertexInputRate::eVertex) return refuse("nonvertex_input_rate");
        if (!bindings[i].stride) return refuse("zero_stride");
        if (offset > b->SizeBytes() || size > b->SizeBytes() - offset) return refuse("source_range_out_of_bounds");
        const auto format = attribute.format;
        if (format != vk::Format::eR32G32B32Sfloat && format != vk::Format::eR32G32B32A32Sfloat)
            return refuse("unsupported_position_format");
        const u32 bytes = format == vk::Format::eR32G32B32Sfloat ? 12u : 16u;
        if (bindings[i].stride < bytes) return refuse("stride_smaller_than_position");
        if (size < bytes) return refuse(size ? "bound_bytes_smaller_than_position" : "zero_bound_bytes");
        workflow->position = {{b->Handle(), offset, b->SizeBytes(), 0,
                               bool(b->buffer.allocation) || b->mem_type == VideoCore::MemoryType::Sparse},
                              size, bindings[i].stride, u32(format)};
        facts.resolved = true;
        facts.reason = "resolved_layout";
        observation = facts;
    };
    const PreparedVertexInputs* ready =
        prepared && prepared->vertex.valid && instance.IsVertexInputDynamicState() && fetch &&
                fetch->attributes.size() == prepared->vertex.count && !FrameCapture::Active() &&
                !BbToggle::Disabled(BbToggle::PreparedResources)
            ? &prepared->vertex
            : nullptr;
    // bbport: the V#s this draw's packet carries are the truth. If the worker's copy differs
    // (the game rewrote the table after the worker read it), its addresses or strides are stale
    // and vertex fetch reads the wrong data ("vertex explosion"): read them here instead.
    if (ready && dc.packet_vsharps.size() == ready->count &&
        std::memcmp(ready->buffers, dc.packet_vsharps.data(),
                    ready->count * sizeof(AmdGpu::Buffer)) != 0) {
        ready = nullptr;
    }
    if (ready) {
        attributes.assign(ready->attributes, ready->attributes + ready->count);
        bindings.assign(ready->bindings, ready->bindings + ready->count);
        guest_buffers.assign(ready->buffers, ready->buffers + ready->count);
        if (BbCeStats::Enabled() && dc.packet_vsharps.size() == ready->count) {
            static u64 compared = 0, differed = 0;
            ++compared;
            differed += std::memcmp(ready->buffers, dc.packet_vsharps.data(),
                                    ready->count * sizeof(AmdGpu::Buffer)) != 0;
            if ((compared & 0xFFFF) == 0) {
                std::printf("CE stats: prepared V#s differed from the packet's in %llu of %llu "
                            "draws\n",
                            (unsigned long long)differed, (unsigned long long)compared);
            }
        }
    } else {
        pipeline->GetVertexInputs(attributes, bindings, divisors, guest_buffers,
                                  regs.vgt_instance_step_rate_0, regs.vgt_instance_step_rate_1,
                                  dc.packet_vsharps);
        if (BbCeStats::Enabled() && !dc.packet_vsharps.empty()) {
            // What reading the V# tables here would have given instead (the old path).
            static u64 compared = 0, differed = 0;
            const auto& fetch = pipeline->GetFetchShader();
            const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
            for (u32 i = 0; fetch && i < fetch->attributes.size() && i < dc.packet_vsharps.size(); ++i) {
                ++compared;
                const auto now = fetch->attributes[i].GetSharp(vs);
                differed += std::memcmp(&now, &dc.packet_vsharps[i], sizeof(now)) != 0;
            }
            if ((compared & 0xFFFF) == 0) {
                std::printf("CE stats: V#s read on the recording thread differed from the "
                            "packet's in %llu of %llu\n",
                            (unsigned long long)differed, (unsigned long long)compared);
            }
        }
    }

    if (record_position) {
        auto& observation = workflow->position_observation;
        observation.layout_source = ready ? "prepared" :
            prepared && prepared->vertex.valid ? "get_vertex_inputs_fallback" : "get_vertex_inputs";
        observation.input_state = instance.IsVertexInputDynamicState() ? "dynamic" : "pipeline_static";
        observation.attribute_count = u32(attributes.size());
        observation.location0_count = u32(std::ranges::count(attributes, 0u,
                                                           &vk::VertexInputAttributeDescription2EXT::location));
        observation.reason = !observation.location0_count ? "location0_missing" :
            bindings.empty() ? "missing_binding_description" : "location0_has_no_bound_slot";
    }
    if (bindings.empty()) {
        // If there are no bindings, there is nothing further to do.
        return;
    }
    if ((dc.motion_draw || dc.capture_draw) && !guest_buffers.empty()) {
        // Include every stream: identical position buffers can be paired with different
        // skinning/instance data. Index topology and base offsets are matched separately.
        dc.motion_geometry = ready ? ready->buffers_hash
                                : XXH3_64bits(guest_buffers.data(),
                                              guest_buffers.size() * sizeof(AmdGpu::Buffer));
    }
    // Object motion research: vertex streams of G-buffer draws.
    if (FrameCapture::Active() && gbuffer_draw) {
        for (const auto& vb : guest_buffers) {
            char note[128];
            std::snprintf(note, sizeof(note), "\n  gb vb at %#llx size %u stride %u",
                          (unsigned long long)vb.base_address, u32(vb.GetSize()),
                          u32(vb.GetStride()));
            FrameCapture::Note(note);
        }
    }

    VertexInputs<std::pair<const VideoCore::Buffer*, u64>> sealed;
    bool all_sealed = own_buffers_mode != BbEngine::Batch::Off && BbEngine::GxObjects::SealingOn() &&
                      !FrameCapture::Active() && buffer_cache.MemoAllowed();
    for (const auto& buffer : guest_buffers) {
        if (!all_sealed) {
            break;
        }
        if (buffer.base_address == 0 || buffer.GetSize() == 0) {
            sealed.emplace_back(nullptr, 0);
            continue;
        }
        const VideoCore::Buffer* found = nullptr;
        u64 offset = 0;
        all_sealed = SealedLookup(buffer.base_address, buffer.GetSize(), found, offset);
        sealed.emplace_back(found, offset);
    }
    if (all_sealed && own_buffers_mode == BbEngine::Batch::On) {
        for (std::size_t i = 0; i < guest_buffers.size(); ++i) {
            const auto& buffer = guest_buffers[i];
            v.host_buffers.emplace_back(sealed[i].first ? sealed[i].first->Handle() : vk::Buffer{});
            v.host_offsets.push_back(sealed[i].second);
            v.host_sizes.push_back(buffer.GetSize());
            v.host_strides.push_back(buffer.GetStride());
            remember_position(i, sealed[i].first, sealed[i].second, buffer.GetSize(), "sealed");
        }
        v.num_buffers = static_cast<u32>(guest_buffers.size());
        return;
    }

    struct BufferRange {
        VAddr base_address;
        VAddr end_address;
        const VideoCore::Buffer* buffer;
        u64 offset;

        [[nodiscard]] size_t GetSize() const {
            return end_address - base_address;
        }
    };

    // Build list of ranges covering the requested buffers
    VertexInputs<BufferRange> ranges{};
    VertexInputs<BufferRange> ranges_merged{};
    if (ready) {
        for (u32 i = 0; i < ready->num_ranges; ++i) {
            ranges_merged.emplace_back(ready->ranges[i].base, ready->ranges[i].end);
        }
    } else {
        for (const auto& buffer : guest_buffers) {
            if (buffer.base_address != 0 && buffer.GetSize() > 0) {
                ranges.emplace_back(buffer.base_address, buffer.base_address + buffer.GetSize());
            }
        }
    }

    // Merge connecting ranges together
    if (!ranges.empty()) {
        std::ranges::sort(ranges, [](const BufferRange& lhv, const BufferRange& rhv) {
            return lhv.base_address < rhv.base_address;
        });
        ranges_merged.emplace_back(ranges[0]);
        for (auto range : ranges) {
            auto& prev_range = ranges_merged.back();
            if (prev_range.end_address < range.base_address) {
                ranges_merged.emplace_back(range);
            } else {
                prev_range.end_address = std::max(prev_range.end_address, range.end_address);
            }
        }
    }

    const auto key_of = [&](VAddr base) -> u64 {
        for (u32 j = 0; j < dc.packet_vsharps.size() && j < dc.packet_vkeys.size(); ++j) {
            if (dc.packet_vsharps[j].base_address == base) {
                return dc.packet_vkeys[j];
            }
        }
        return 0;
    };
    for (auto& range : ranges_merged) {
        const u64 size = memory->ClampRangeSize(range.base_address, range.GetSize());
        u64 key = dc.packet_vkeys.empty() ? 0 : 0x9E3779B97F4A7C15ull;
        for (const auto& buffer : guest_buffers) {
            if (!key) {
                break;
            }
            if (buffer.base_address == 0 || buffer.GetSize() == 0 ||
                buffer.base_address < range.base_address || buffer.base_address >= range.end_address) {
                continue;
            }
            const u64 part = key_of(buffer.base_address);
            key = part ? (key ^ part) * 0x100000001B3ull | 1 : 0;
        }
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (auto* post = dc.shared_post; post && post->watch && size && size <= UINT32_MAX) {
            using namespace VideoCore::PostGeometry;
            std::array<Slice, VertexSlots> slices{};
            std::array<u32, VertexSlots> native_slots{};
            u32 count = 0;
            for (u32 logical = 0; logical < VertexSlots; ++logical) {
                const auto attribute = std::ranges::find(attributes, logical,
                     &vk::VertexInputAttributeDescription2EXT::location);
                if (attribute == attributes.end()) continue;
                const auto native = std::size_t(attribute - attributes.begin());
                if (native >= guest_buffers.size()) continue;
                const auto& input = guest_buffers[native];
                const auto bytes = std::min<u64>(input.GetSize(), VertexBytes);
                if (VideoCore::PostGeometry::Capture::Contains(range.base_address, size, input.base_address, bytes)) {
                    native_slots[count] = attribute->binding;
                    slices[count++] = {u32(input.base_address - range.base_address), u16(bytes), u8(logical), Use::Vertex};
                }
            }
            UploadWatch upload(*post->watch, range.base_address, u32(size), std::span{slices}.first(count));
            std::tie(range.buffer, range.offset) = BindVertexRange(key, range.base_address, size);
            const auto tickets = upload.Tickets();
            for (u32 i = 0; i < count; ++i) {
                const auto [rel, bytes, slot, use] = slices[i];
                auto& row = post->bytes[slot];
                row.native_slot = native_slots[i];
                row.state = upload.Status();
                if (i >= tickets.size() || !range.buffer) continue;
                row.ticket = tickets[i];
                row.binding = {post->geometry_key, &buffer_cache,
                    {range.buffer, std::bit_cast<u64>(range.buffer->Handle()),
                     reinterpret_cast<u64>(range.buffer->buffer.allocation), buffer_cache.StructureGeneration()},
                    range.base_address + rel, range.offset + rel, 0, bytes, slot, use};
            }
        } else
#endif
        {
            std::tie(range.buffer, range.offset) = BindVertexRange(key, range.base_address, size);
        }
        dc.needs_barrier |= runtime.IsBufferAccessed(range.buffer, range.offset, size);
    }

    // Bind vertex buffers
    auto& host_buffers = v.host_buffers;
    auto& host_offsets = v.host_offsets;
    auto& host_sizes = v.host_sizes;
    auto& host_strides = v.host_strides;
    u32 stream_with_memory = 0;
    for (const auto& buffer : guest_buffers) {
        if (buffer.base_address != 0 && buffer.GetSize() > 0) {
            const auto host_buffer_info =
                ready ? ranges_merged.begin() + ready->range_index[stream_with_memory++]
                      : std::ranges::find_if(ranges_merged, [&](const BufferRange& range) {
                            return buffer.base_address >= range.base_address &&
                                   buffer.base_address < range.end_address;
                        });
            ASSERT(host_buffer_info != ranges_merged.cend());
            host_buffers.emplace_back(host_buffer_info->buffer->Handle());
            host_offsets.push_back(host_buffer_info->offset + buffer.base_address -
                                   host_buffer_info->base_address);
            remember_position(host_offsets.size() - 1, host_buffer_info->buffer, host_offsets.back(), buffer.GetSize(),
                              "merged");
        } else {
            host_buffers.emplace_back(VK_NULL_HANDLE);
            host_offsets.push_back(0);
            remember_position(host_offsets.size() - 1, nullptr, 0, buffer.GetSize(), "null_bind");
        }
        host_sizes.push_back(buffer.GetSize());
        host_strides.push_back(buffer.GetStride());
    }

    v.num_buffers = static_cast<u32>(guest_buffers.size());
}

bool Rasterizer::SealedLookup(VAddr base, u64 size, const VideoCore::Buffer*& buffer, u64& offset) {
    auto& e = sealed_binds[((base ^ (size << 40)) * 0x9E3779B97F4A7C15ull) >> 52];
    const u64 layout = buffer_cache.StructureGeneration();
    if (e.base == base && e.size == size && e.layout == layout && BbEngine::GxObjects::SealedValid(e.id, e.generation)) {
        ++sealed_hits;
        buffer = e.buffer;
        offset = e.offset;
        return true;
    }
    u32 id = 0, generation = 0;
    u64 sealed_base = 0;
    if (!BbEngine::GxObjects::SealedFind(base, size, &id, &generation, &sealed_base)) {
        e.base = 0;
        return false;
    }
    ++sealed_misses;
    const auto found = buffer_cache.ObtainBuffer(base, u32(size), false);
    if (!buffer_cache.Persistent(found.first)) {
        e.base = 0;
        return false;
    }
    Dc().needs_barrier |= runtime.IsBufferAccessed(found.first, found.second, size);
    e = {base, size, id, generation, buffer_cache.StructureGeneration(), found.first, found.second};
    buffer = found.first;
    offset = found.second;
    return true;
}

std::pair<const VideoCore::Buffer*, u64> Rasterizer::BindVertexRange(u64 key, VAddr base, u64 size) {
    static const bool by_range = [] {
        const char* env = std::getenv("LANTERN_RANGE_BINDS");
        return env && env[0] == '1';
    }();
    if (key) {
        return BindByObject(key, base, size);
    }
    if (by_range && size != 0) {
        ++range_binds;
        return BindByObject(RangeBindKey, base, size);
    }
    if (VertexMemoOn() && size != 0 && buffer_cache.MemoAllowed()) {
        return BindVertexMemo(base, size);
    }
    return buffer_cache.ObtainBuffer(base, u32(size), false);
}

bool Rasterizer::VertexMemoOn() const {
    // bbport: experiment 2097152 is the old default (memo off).
    return vertex_memo_mode != BbEngine::Batch::Off && !BbToggle::Experiment(2097152);
}

std::pair<const VideoCore::Buffer*, u64> Rasterizer::BindVertexMemo(VAddr base, u64 size) {
    // bbport: what a miss runs first in EnsureResident (pending unmaps, demotions, late writes),
    // before the generation check: a hit must not return a binding such work would replace.
    buffer_cache.MaintainPacket();
    auto& memo = vertex_memo[((base ^ (size << 40)) * 0x9E3779B97F4A7C15ull) >> 52];
    const bool hit = memo.base == base && memo.size == size &&
                     memo.generation == buffer_cache.StructureGeneration() &&
                     buffer_cache.StillClean(base, size, memo.in_place);
    if (hit && vertex_memo_mode == BbEngine::Batch::On) {
        buffer_cache.NoteBound(base, size);
        return {memo.buffer, memo.offset};
    }
    const auto found = buffer_cache.ObtainBuffer(base, u32(size), false);
    if (buffer_cache.Persistent(found.first) && size > VideoCore::BufferCache::STREAM_THRESHOLD) {
        memo = {base, size, buffer_cache.StructureGeneration(), found.first, found.second,
                buffer_cache.InPlaceRange(base, size)};
    } else {
        memo.base = 0;
    }
    return found;
}

std::pair<const VideoCore::Buffer*, u64> Rasterizer::BindByObject(u64 key, VAddr base, u64 size) {
    const u64 slot_key = (key ^ base ^ (size << 32)) * 0x9E3779B97F4A7C15ull;
    auto& bind = object_binds[slot_key >> 52];
    if (bind.key == key && bind.base == base && bind.size == size &&
        bind.generation == buffer_cache.BindGeneration()) {
        if (!BbEngine::GxRecords::Compared() && (++object_bind_checks & 63) != 0) {
            buffer_cache.NoteBound(base, size);
            BbEngine::GxRecords::NoteBind(true, false, true, base, size);
            range_hits += key == RangeBindKey;
            return {bind.buffer, bind.offset};
        }
        const u64 uploads = VideoCore::BufferCache::obtain_paths[5];
        const auto found = buffer_cache.ObtainBuffer(base, u32(size), false);
        const bool same = found.first == bind.buffer && found.second == bind.offset &&
                          VideoCore::BufferCache::obtain_paths[5] == uploads;
        BbEngine::GxRecords::NoteBind(same, true, same, base, size);
        if (key == RangeBindKey) {
            ++range_checked;
            range_differ += !same;
        }
        if (!same) {
            bind.key = 0;
        }
        return found;
    }
    const auto found = buffer_cache.ObtainBuffer(base, u32(size), false);
    BbEngine::GxRecords::NoteBind(false, false, true, base, size);
    if (buffer_cache.Persistent(found.first)) {
        bind = {key, base, size, buffer_cache.BindGeneration(), found.first, found.second};
    }
    return found;
}

void Rasterizer::BindIndexBuffer(u32 index_offset) {
    ResolveIndexBuffer(index_offset);
    EmitIndexBuffer();
}

void Rasterizer::EmitIndexBuffer() {
    auto& dc = Dc();
    // bbport (r21_draw-sort): an index buffer bind equal to the one in force is left out.
    auto& m = r21_bound;
    const bool r21 = R21Begin(instance.IsVertexInputDynamicState());
    const u64 r21_serial = scheduler.R21Serial();
    const u64 r21_epoch = scheduler.R21Epoch();
    const IndexBind& bind = dc.index_bind;
    const bool same = r21 && m.index_known && m.index.handle == bind.handle &&
                      m.index.offset == bind.offset && m.index.type == bind.type;
    r21_outcome.index = !r21 ? 0 : same ? 1 : m.index_known ? 2 : 3;
    if (same) {
        return; // r21: r21_bound is still in force
    }
    scheduler.Record([handle = dc.index_bind.handle, offset = dc.index_bind.offset,
                      type = dc.index_bind.type](vk::CommandBuffer cmdbuf) {
        cmdbuf.bindIndexBuffer(handle, offset, type);
    });
    if (r21) {
        m.index = bind;
        m.index_known = true;
    }
    R21End(r21, r21_serial, r21_epoch);
}

void Rasterizer::ResolveIndexBuffer(u32 index_offset) {
    auto& dc = Dc();
    BB_SECTION(ResolveIndexBuffer);
    if (dc.blood_index) *dc.blood_index = {};
    const auto& regs = Regs();

    // Figure out index type and size.
    const bool is_index16 = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16;
    const vk::IndexType index_type = is_index16 ? vk::IndexType::eUint16 : vk::IndexType::eUint32;
    const u32 index_size = is_index16 ? sizeof(u16) : sizeof(u32);
    const VAddr index_address =
        regs.index_base_address.Address<VAddr>() + index_offset * index_size;

    // Bind index buffer.
    const u32 index_buffer_size = regs.num_indices * index_size;
    const auto note_blood = [&](const VideoCore::Buffer& buffer, u64 offset, bool sealed) {
        if (!dc.blood_index) return;
        auto& index = *dc.blood_index;
        index = {.buffer = buffer.Handle(), .offset = offset, .capacity = buffer.SizeBytes(),
                 .guest = index_address, .bytes = index_buffer_size, .type = index_type,
                 .sealed = sealed,
                 .transfer_src = bool(buffer.buffer.allocation) ||
                     buffer.mem_type == VideoCore::MemoryType::Sparse};
        if (!sealed) return;
        const u64 bytes = index_buffer_size;
        u32 first_id = 0, last_id = 0, first_gen = 0, last_gen = 0;
        u64 first_base = 0, last_base = 0;
        const bool valid = bytes && index_address <= std::numeric_limits<u64>::max() - (bytes - 1) &&
            BbEngine::GxObjects::SealedFind(index_address, 1, &first_id, &first_gen, &first_base) &&
            BbEngine::GxObjects::SealedFind(index_address + bytes - 1, 1, &last_id, &last_gen, &last_base) &&
            first_id == last_id && first_gen == last_gen && first_base == last_base &&
            BbEngine::GxObjects::SealedValid(first_id, first_gen);
        if (valid) {
            index.sealed_id = first_id;
            index.generation = first_gen;
        } else {
            index.transfer_src = false;
        }
    };
    const auto note_workflow = [&](const VideoCore::Buffer& buffer, u64 offset, bool sealed) {
        if (!workflow || !workflow->querying || workflow->request.op != WorkflowProbe::Op::Resources) return;
        u32 generation = 0;
        if (sealed && index_buffer_size && index_address <= std::numeric_limits<u64>::max() - (index_buffer_size - 1)) {
            u32 first = 0, last = 0, first_gen = 0, last_gen = 0;
            u64 first_base = 0, last_base = 0;
            if (BbEngine::GxObjects::SealedFind(index_address, 1, &first, &first_gen, &first_base) &&
                BbEngine::GxObjects::SealedFind(index_address + index_buffer_size - 1, 1, &last, &last_gen, &last_base) &&
                first == last && first_gen == last_gen && first_base == last_base &&
                BbEngine::GxObjects::SealedValid(first, first_gen)) {
                generation = first_gen;
            }
        }
        workflow->resolved = {buffer.Handle(), offset, buffer.SizeBytes(), generation,
                              bool(buffer.buffer.allocation) || buffer.mem_type == VideoCore::MemoryType::Sparse};
    };
    const auto note_lineage = [&](const VideoCore::Buffer& buffer, u64 offset, bool sealed) {
        if (index_buffer_size != LampIndexLineage::Bytes || !is_index16 || !Round2ProbeSettings::Get().lineage) {
            return;
        }
        auto* probe = rt_shadow->ActiveLampPane();
        if (!probe || !probe->lineage) return;
        const u64 capacity = buffer.SizeBytes();
        // Ordinary cache buffers (including sparse arenas) are created with AllFlags.
        // External imports use a different constructor and do not carry a VMA allocation.
        const bool transfer_src = buffer.buffer.allocation || buffer.mem_type == VideoCore::MemoryType::Sparse;
        bool checked = buffer.Handle() && transfer_src && offset % 4 == 0 && offset <= capacity &&
                       index_buffer_size <= capacity - offset;
        if (checked && sealed) {
            u32 first_id = 0, last_id = 0, first_generation = 0, last_generation = 0;
            u64 first_base = 0, last_base = 0;
            checked = index_address <= std::numeric_limits<u64>::max() - (index_buffer_size - 1) &&
                BbEngine::GxObjects::SealedFind(index_address, 1, &first_id, &first_generation, &first_base) &&
                BbEngine::GxObjects::SealedFind(index_address + index_buffer_size - 1, 1, &last_id,
                                               &last_generation, &last_base) &&
                first_id == last_id && first_generation == last_generation && first_base == last_base &&
                BbEngine::GxObjects::SealedValid(first_id, first_generation);
        }
        probe->lineage->resolved = {buffer.Handle(), offset, capacity, checked};
    };
    if (own_buffers_mode == BbEngine::Batch::On && index_buffer_size && BbEngine::GxObjects::SealingOn() &&
        !FrameCapture::Active() && buffer_cache.MemoAllowed()) {
        const VideoCore::Buffer* sealed = nullptr;
        u64 sealed_offset = 0;
        if (SealedLookup(index_address, index_buffer_size, sealed, sealed_offset)) {
            dc.index_bind = {sealed->Handle(), sealed_offset, index_type};
            note_lineage(*sealed, sealed_offset, true);
            note_blood(*sealed, sealed_offset, true);
            note_workflow(*sealed, sealed_offset, true);
            return;
        }
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::optional<VideoCore::PostGeometry::UploadWatch> upload;
    const VideoCore::PostGeometry::Slice slice{0, u16(std::min<u32>(index_buffer_size, 32)), 0,
                                              VideoCore::PostGeometry::Use::Index};
    auto* post = dc.shared_post;
    if (post && post->watch && index_buffer_size)
        upload.emplace(*post->watch, index_address, index_buffer_size, std::span{&slice, 1});
#endif
    const auto [buffer, offset] = BindVertexRange(dc.packet_index_key, index_address, index_buffer_size);
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (upload) {
        auto& row = post->bytes[VideoCore::PostGeometry::PacketSlot(VideoCore::PostGeometry::Use::Index, 0)];
        row.state = upload->Status();
        const auto tickets = upload->Tickets();
        if (!tickets.empty() && buffer) {
            row.ticket = tickets.front();
            row.binding = {post->geometry_key, &buffer_cache,
                {buffer, std::bit_cast<u64>(buffer->Handle()), reinterpret_cast<u64>(buffer->buffer.allocation),
                 buffer_cache.StructureGeneration()}, index_address, offset, 0, slice.bytes, slice.slot, slice.use};
        }
    }
#endif
    dc.needs_barrier |= runtime.IsBufferAccessed(buffer, offset, index_buffer_size);
    dc.index_bind = {buffer->Handle(), offset, index_type};
    note_lineage(*buffer, offset, false);
    note_blood(*buffer, offset, false);
    note_workflow(*buffer, offset, false);
}

void Rasterizer::ResetBindings(bool is_compute) {
    auto& dc = Dc();
    for (auto& image_id : dc.bound_images) {
        texture_cache.GetImage(image_id).binding = {};
    }
    for (const auto [buffer, offset, size, is_written] : dc.bound_buffers) {
        const auto dst_stage = is_compute ? vk::PipelineStageFlagBits2::eComputeShader
                                          : vk::PipelineStageFlagBits2::eAllGraphics;
        const auto write_flag =
            is_written ? vk::AccessFlagBits2::eShaderWrite : vk::AccessFlagBits2::eNone;
        runtime.AccessBuffer(buffer, offset, size, dst_stage,
                             vk::AccessFlagBits2::eShaderRead | write_flag);
    }
    dc.bound_images.clear();
    dc.bound_buffers.clear();
    dc.needs_barrier = false;
}

bool Rasterizer::IsComputeMetaClear(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Most of the time when a metadata is updated with a shader it gets cleared. It means
    // we can skip the whole dispatch and update the tracked state instead. Also, it is not
    // intended to be consumed and in such rare cases (e.g. HTile introspection, CRAA) we
    // will need its full emulation anyways.
    const auto& info = pipeline->GetStage(Shader::SwStage::Compute);

    // Assume if a shader reads metadata, it is a copy shader.
    for (const auto& desc : info.buffers) {
        const VAddr address = desc.GetSharp(info).base_address;
        if (!desc.IsSpecial() && !desc.is_written && texture_cache.IsMeta(address)) {
            return false;
        }
    }

    // Metadata surfaces are tiled and thus need address calculation to be written properly.
    // If a shader wants to encode HTILE, for example, from a depth image it will have to compute
    // proper tile address from dispatch invocation id. This address calculation contains an xor
    // operation so use it as a heuristic for metadata writes that are probably not clears.
    if (!info.has_bitwise_xor) {
        // Assume if a shader writes metadata without address calculation, it is a clear shader.
        for (const auto& desc : info.buffers) {
            const VAddr address = desc.GetSharp(info).base_address;
            if (!desc.IsSpecial() && desc.is_written && texture_cache.ClearMeta(address)) {
                // Assume all slices were updates
                LOG_TRACE(Render_Vulkan, "Metadata update skipped");
                return true;
            }
        }
    }
    return false;
}

bool Rasterizer::IsComputeImageCopy(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Ensure shader only has 2 bound buffers
    const auto& cs_pgm = CsRegs();
    const auto& info = pipeline->GetStage(Shader::SwStage::Compute);
    if (cs_pgm.num_thread_x.full != 64 || info.buffers.size() != 2 || !info.images.empty()) {
        return false;
    }

    // Those 2 buffers must both be formatted. One must be source and another destination.
    const auto& desc0 = info.buffers[0];
    const auto& desc1 = info.buffers[1];
    if (!desc0.is_formatted || !desc1.is_formatted || desc0.is_written == desc1.is_written) {
        return false;
    }

    // Buffers must have the same size and each thread of the dispatch must copy 1 dword of data
    const AmdGpu::Buffer buf0 = desc0.GetSharp(info);
    const AmdGpu::Buffer buf1 = desc1.GetSharp(info);
    if (buf0.GetSize() != buf1.GetSize() || cs_pgm.dim_x != (buf0.GetSize() / 256)) {
        return false;
    }

    // Find images the buffer alias
    const auto image0_id = texture_cache.FindImageFromRange(buf0.base_address, buf0.GetSize());
    if (!image0_id) {
        return false;
    }
    const auto image1_id =
        texture_cache.FindImageFromRange(buf1.base_address, buf1.GetSize(), false);
    if (!image1_id) {
        return false;
    }

    // Image copy must be valid
    VideoCore::Image& image0 = texture_cache.GetImage(image0_id);
    VideoCore::Image& image1 = texture_cache.GetImage(image1_id);
    if (image0.info.guest_size != image1.info.guest_size ||
        image0.info.pitch != image1.info.pitch || image0.info.guest_size != buf0.GetSize() ||
        image0.info.num_bits != image1.info.num_bits) {
        return false;
    }

    // Perform image copy
    VideoCore::Image& src_image = desc0.is_written ? image1 : image0;
    VideoCore::Image& dst_image = desc0.is_written ? image0 : image1;
    runtime.CopyColorAndDepth(&src_image, &dst_image);
    return true;
}

bool Rasterizer::IsComputeImageClear(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Ensure shader only has 2 bound buffers
    const auto& cs_pgm = CsRegs();
    const auto& info = pipeline->GetStage(Shader::SwStage::Compute);
    if (cs_pgm.num_thread_x.full != 64 || info.buffers.size() != 2 || !info.images.empty()) {
        return false;
    }

    // From those 2 buffers, first must hold the clear vector and second the image being cleared
    const auto& desc0 = info.buffers[0];
    const auto& desc1 = info.buffers[1];
    if (desc0.is_formatted || !desc1.is_formatted || desc0.is_written || !desc1.is_written) {
        return false;
    }

    // First buffer must have size of vec4 and second the size of a single layer
    const AmdGpu::Buffer buf0 = desc0.GetSharp(info);
    const AmdGpu::Buffer buf1 = desc1.GetSharp(info);
    const u32 buf1_bpp = AmdGpu::NumBitsPerBlock(buf1.GetDataFmt());
    if (buf0.GetSize() != 16 || (cs_pgm.dim_x * 128ULL * (buf1_bpp / 8)) != buf1.GetSize()) {
        return false;
    }

    // Find image the buffer alias
    const auto image1_id =
        texture_cache.FindImageFromRange(buf1.base_address, buf1.GetSize(), false);
    if (!image1_id) {
        return false;
    }

    // Image clear must be valid
    VideoCore::Image& image1 = texture_cache.GetImage(image1_id);
    // bbport: a clear of the first level of a mip chain only. Each frame the game clears level 0
    // (0x2000000 bytes: 1920x1080 padded to 2048x2048 at 8 bytes) of an R16G16B16A16 chain of 11
    // levels (44.7 MB) with this shader. That is not the image's size, so the shader ran over
    // buffers: the write marked the image GPU-dirty and its next binding detiled all of it and
    // uploaded every level from the buffer cache (BB_GPU_PROFILE "image upload R16G16B16A16Sfloat
    // 1920x1080", ~0.38 ms a frame, plus the detile before it). Here level 0 is cleared as an
    // image. The other levels keep what the GPU last wrote there, as the console's memory does
    // (the upload put the buffer cache's older bytes there). Experiment mask 262144: the shader.
    const bool level0_only =
        image1.info.guest_size != buf1.GetSize() && !BbToggle::Experiment(262144) &&
        image1.info.resources.levels > 1 && image1.info.resources.layers == 1 &&
        !image1.info.props.is_volume && image1.info.mips_layout[0].offset == 0 &&
        image1.info.mips_layout[0].size == buf1.GetSize();
    if ((image1.info.guest_size != buf1.GetSize() && !level0_only) ||
        image1.info.num_bits != buf1_bpp || image1.info.props.is_depth) {
        return false;
    }

    // Perform image clear
    const float* values = reinterpret_cast<float*>(buf0.base_address);
    const vk::ClearValue clear = {
        .color = {.float32 = std::array<float, 4>{values[0], values[1], values[2], values[3]}},
    };
    const VideoCore::SubresourceRange range = {
        .base =
            {
                .level = 0,
                .layer = 0,
            },
        .extent = level0_only ? VideoCore::SubresourceExtent{1, 1} : image1.info.resources,
    };
    // BB_GPU_PROFILE: the level-0 clear has its own label ("image clear HLE level 0 <format>
    // WxH"); the segment it interrupts continues after it (as for uploads).
    std::optional<Runtime::TransferMark> clear_mark;
    if (level0_only) {
        // A pending upload first: the levels this clear leaves must keep it.
        texture_cache.UpdateImage(image1_id);
        clear_mark.emplace(runtime, "image clear HLE level 0", texture_cache.GetImage(image1_id));
        static bool logged = false;
        if (!logged) {
            logged = true;
            const auto& cleared = texture_cache.GetImage(image1_id).info;
            std::printf("Image clear HLE: level 0 of image %#llx %s %ux%u (%u levels, %#x bytes) "
                        "cleared as an image, %#x bytes (experiment mask 262144: the shader)\n",
                        static_cast<unsigned long long>(cleared.guest_address),
                        vk::to_string(cleared.pixel_format).c_str(), cleared.size.width,
                        cleared.size.height, cleared.resources.levels, cleared.guest_size,
                        static_cast<u32>(buf1.GetSize()));
        }
    }
    runtime.ClearImage(&texture_cache.GetImage(image1_id), range, clear);
    return true;
}

namespace {
// bbport: BB_TRACE_SHADER=hash[,hash...] (diagnostics) â€” the buffers those shaders bind: address,
// size, written or read, where the data is (in place: the game's memory over PCIe on a discrete
// GPU; VRAM; partly), how often; printed every 5 s.
// Whether BB_TRACE_SHADER is set (its hash list below is then non-empty): without it, callers
// skip the in-place lookups they would only pass as arguments.
bool TraceShaderOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_TRACE_SHADER");
        return env != nullptr && env[0] != 0;
    }();
    return on;
}

void TraceShaderBinding(const Shader::Info& stage, VAddr addr, u64 size, bool written,
                        bool in_place, bool any_in_place) {
    static const std::vector<u64> hashes = [] {
        std::vector<u64> out;
        const char* env = std::getenv("BB_TRACE_SHADER");
        for (const char* at = env; at && *at;) {
            char* end = nullptr;
            out.push_back(std::strtoull(at, &end, 16));
            at = end && *end == ',' ? end + 1 : nullptr;
        }
        return out;
    }();
    if (hashes.empty() || std::ranges::find(hashes, stage.pgm_hash) == hashes.end()) {
        return;
    }
    struct Key {
        u64 hash, addr, size;
        bool written;
        auto operator<=>(const Key&) const = default;
    };
    struct Entry {
        u64 count = 0;
        int place = 0; // 0 VRAM, 1 in place, 2 partly
    };
    static std::mutex mutex;
    static std::map<Key, Entry> entries;
    static auto report = std::chrono::steady_clock::now();
    std::scoped_lock lk{mutex};
    auto& entry = entries[{stage.pgm_hash, addr, size, written}];
    ++entry.count;
    entry.place = in_place ? 1 : any_in_place ? 2 : 0;
    const auto now = std::chrono::steady_clock::now();
    if (now - report < std::chrono::seconds(5)) {
        return;
    }
    report = now;
    static constexpr const char* Places[] = {"VRAM", "in place", "partly in place"};
    for (const auto& [key, value] : entries) {
        std::printf("Shader %016llx binds %#llx+%#llx %s, %s, x%llu (uses_dma %d)\n",
                    (unsigned long long)key.hash, (unsigned long long)key.addr,
                    (unsigned long long)key.size, key.written ? "written" : "read",
                    Places[value.place], (unsigned long long)value.count, int(stage.uses_dma));
    }
    entries.clear();
}
} // namespace

namespace ReflectionNativeProbe {
bool BeginOrdinalZero(const Draw&);
void RecordOrdinalZero(const Draw&, const Shader::BufferResource&, const AmdGpu::Buffer&,
                       const vk::DescriptorBufferInfo&, u32 slot, u32 adjust, VAddr source_address,
                       bool prepared, std::string_view route, std::span<const u8> owned);
void RecordExactObject(ReflectionFirstRetire::Row*, Draw&, u32 ordinal, const Shader::BufferResource&, const AmdGpu::Buffer&,
                       const vk::DescriptorBufferInfo&, u32 slot, u32 adjust, VAddr source_address,
                       std::string_view route, std::span<const u8> owned);
}

#ifdef BB_TEST_SHARED_POST_GRAPH
static std::span<const VideoCore::PostGeometry::Slice> PostCompositeMembers(
    const Vulkan::SewerBridge::PostDraw& draw, const Shader::Info& stage, u32 binding) {
    using namespace VideoCore::PostGeometry;
    // Offsets are the exact archived SPIR-V member loads, relative to the shader-visible base.
    // Permutation is a capture plan guard. Runtime program/content lineage is a separate receipt.
    constexpr u64 vertex_permutation = 0x000001eae48c13beull;
    const bool composite = (draw.ps == 0x5e67d866 && draw.ps_permutation == 0x000005e77fc38f59ull) ||
                           (draw.ps == 0xccb08339 && draw.ps_permutation == 0x00000ccb7f8692d5ull);
    if (!composite || draw.vs != 0x1ea5a07e || draw.vs_permutation != vertex_permutation) return {};
    if (stage.sw_stage == Shader::SwStage::Vertex && stage.pgm_hash == draw.vs && binding == 9) {
        static constexpr std::array members{Slice{20 * 4, 2 * 4, 0, Use::Uniform}};
        return members;
    }
    if (stage.sw_stage != Shader::SwStage::Fragment || stage.pgm_hash != draw.ps || binding != 0) return {};
    static constexpr std::array<Slice, 7> members{{Slice{616 * 4, 2 * 4, 1, Use::Uniform}, {620 * 4, 4 * 4, 2, Use::Uniform},
        {744 * 4, 5 * 4, 3, Use::Uniform}, {752 * 4, 5 * 4, 4, Use::Uniform},
        {808 * 4, 3 * 4, 5, Use::Uniform}, {832 * 4, 2 * 4, 6, Use::Uniform},
        {840 * 4, 12 * 4, 7, Use::Uniform}}};
    const auto fragments = std::span{members};
    return draw.ps == 0x5e67d866 ? fragments.first(6) : std::span<const Slice>{fragments};
}
#endif

void Rasterizer::BindBuffers(const Shader::Info& stage, const PreparedStage* prepared,
                             Shader::Backend::Bindings& binding,
                             Shader::PushData& push_data, u32& write_index) {
    auto& dc = Dc();
    BB_SECTION(BindBuffers);
    const u64 alignment = instance.StorageMinAlignment();
    const u64 uniform_alignment = std::max<u64>(instance.UniformMinAlignment(), alignment);
    static const u64 max_uniform_range =
        instance.GetPhysicalDevice().getProperties().limits.maxUniformBufferRange;
    auto* ivy = stage.sw_stage == Shader::SwStage::Fragment &&
                        stage.pgm_hash == IvyMaterialProbe::Fragment ? dc.ivy_material : nullptr;
    auto* native = stage.sw_stage == Shader::SwStage::Vertex ? dc.reflection_native : nullptr;
    const auto* object3_row = native && native->exact && Object3::On() && dc.draw_inputs.pipeline &&
        Object3::ExactKey(native->key.vs, native->key.ps, native->key.count, native->key.first) &&
        Ordinal3Stages(*dc.draw_inputs.pipeline) ? ReflectionFirstRetire::Current(this) : nullptr;
    if (object3_row && !Object3::Active(this, object3_row->generation, object3_row->sequence)) {
        object3_row = nullptr;
    }
    if (object3_row && Object3::state.working.sequence != object3_row->sequence) {
        Object3::state.working = {};
        Object3::state.working.sequence = object3_row->sequence;
    }
    if (ivy) ivy->buffers = u32(stage.buffers.size());
    for (u32 buffer_index = 0; buffer_index < stage.buffers.size(); ++buffer_index) {
        auto* witness = ivy && buffer_index < ivy->constants.size() ? &ivy->constants[buffer_index] : nullptr;
        const bool ordinal_zero = native && buffer_index == 0 && ReflectionNativeProbe::BeginOrdinalZero(*native);
        const bool exact_object = native && native->exact && (buffer_index == 0 || buffer_index == 3);
        const bool observe_object = ordinal_zero || exact_object;
        VAddr ordinal_source = 0;
        IvyMaterialProbe::Bytes captured{};
        const char* captured_from = "unknown";
        u64 guest_available = 0;
        const auto& desc = stage.buffers[buffer_index];
#ifdef BB_TEST_SHARED_POST_GRAPH
        using namespace VideoCore::PostGeometry;
        auto* post_uniform = dc.shared_post;
        const auto members = post_uniform && post_uniform->watch && desc.is_uniform && !desc.IsSpecial() &&
                             !desc.is_written && !desc.is_formatted ?
            PostCompositeMembers(*post_uniform, stage, binding.unified) : std::span<const Slice>{};
        const auto take_uniform = [&](const UploadWatch& upload, const Reservation& reserved, Route route) {
            const auto tickets = upload.Tickets();
            for (u32 i = 0; i < members.size(); ++i) {
                const auto member = members[i];
                auto& raw = post_uniform->bytes[PacketSlot(member.use, member.slot)];
                raw.state = upload.Status();
                raw.route = route;
                if (i >= tickets.size()) continue;
                raw.ticket = tickets[i];
                raw.binding = {post_uniform->geometry_key, &buffer_cache, reserved.backing,
                    reserved.guest + member.relative, reserved.offset + member.relative, 0,
                    member.bytes, member.slot, member.use};
            }
        };
        const auto snapshot_uniform = [&](Route route, const Reservation& reserved, const u8* mapped) {
            UploadWatch upload(*post_uniform->watch, reserved.guest, reserved.bytes, members);
            upload.SnapshotUniform(route, reserved, std::bit_cast<u64>(scheduler.GetWorkSemaphore()->Handle()),
                                   mapped);
            take_uniform(upload, reserved, route);
        };
        for (const auto& member : members) {
            auto& raw = post_uniform->bytes[PacketSlot(member.use, member.slot)];
            raw.member = member.relative;
            raw.member_bytes = member.bytes;
            raw.push_index = binding.buffer;
            raw.native_slot = binding.unified;
        }
#endif
        std::optional<AmdGpu::Buffer> native_sharp;
        const VideoCore::Buffer* native_buffer = nullptr;
        const RingBinding* ring = dc.num_ring_stages ? FindRingBinding(stage, buffer_index) : nullptr;
        VideoCore::BufferCache::WallStreamProbe* wall_probe = nullptr;
        if (ring) {
            // Copied by the GPU command thread into the constant ring (read-only).
            if (witness) {
                witness->guest = ring->address;
                captured = {constant_ring->Data(ring->Offset()), ring->size};
                captured_from = "constant-ring";
            }
            if (observe_object && !desc.IsSpecial() && !desc.is_written) {
                ordinal_source = ring->address;
                captured = {constant_ring->Data(ring->Offset()), ring->size};
                captured_from = "constant-ring";
            }
            if (!desc.IsSpecial()) {
                if (ring->size == 864 && gbuffer_draw &&
                    memory->IsValidGpuMapping(ring->address, 0)) {
                    camera_motion->OnConstants(reinterpret_cast<const float*>(ring->address));
                }
                dc.push_data.AddOffset(binding.buffer, 0);
            }
            ubo_stats.ring += desc.is_uniform ? 1 : 0;
            dc.buffer_infos.emplace_back(constant_ring->Handle(), ring->Offset(),
                                      desc.is_uniform ? std::min<u64>(ring->size, max_uniform_range)
                                                      : u64(ring->size));
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (!members.empty() && ring->address && constant_ring->Allocation() &&
                RingRegionCurrent(dc.ring_packet_end, ring->location, ring->size, ConstantRing::Capacity)) {
                snapshot_uniform(Route::ConstantRing,
                    {{constant_ring.get(), std::bit_cast<u64>(constant_ring->Handle()),
                      reinterpret_cast<u64>(constant_ring->Allocation()), ring->location},
                     ring->address, ring->Offset(), scheduler.CurrentTick(), ring->size},
                    constant_ring->Data(ring->Offset()));
            }
#endif
            if (native && !desc.IsSpecial()) {
                native_sharp = prepared ? prepared->buffer_sharps[buffer_index] : desc.GetSharp(stage);
            }
        } else if (desc.IsSpecial()) {
            if (desc.buffer_type == Shader::BufferType::GdsBuffer) {
                const auto* gds_buf = buffer_cache.GetGdsBuffer();
                dc.buffer_infos.emplace_back(gds_buf->Handle(), 0, gds_buf->SizeBytes());
                dc.needs_barrier |= runtime.IsBufferAccessed(gds_buf, 0, gds_buf->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::Flatbuf) {
                auto& vk_buffer = buffer_cache.GetStreamBuffer();
                const u32 ubo_size = stage.FlatUserData().size() * sizeof(u32);
                if (FrameCapture::Active()) {
                    FrameCapture::Buffer(stage.pgm_hash, binding.buffer, 0,
                                         stage.FlatUserData().data(), ubo_size);
                }
                const u64 offset = vk_buffer.Copy(stage.FlatUserData().data(), ubo_size,
                                                  desc.is_uniform ? uniform_alignment : alignment);
                dc.buffer_infos.emplace_back(vk_buffer.Handle(), offset, ubo_size);
                if (witness) {
                    captured = IvyMaterialProbe::Words(stage.FlatUserData());
                    captured_from = "flat-user-data";
                }
            } else if (desc.buffer_type == Shader::BufferType::ClipPlanes) {
                // Permutations compiled without enabled planes never read the buffer, so the
                // declared binding is satisfied with a null descriptor instead of a copy.
                if (Regs().clipper_control.user_clip_plane_enable == 0) {
                    dc.buffer_infos.emplace_back(VK_NULL_HANDLE, 0, VK_WHOLE_SIZE);
                } else {
                    auto& vk_buffer = buffer_cache.GetStreamBuffer();
                    std::array<float, AmdGpu::NUM_CLIP_PLANES * 4> planes{};
                    for (u32 i = 0; i < AmdGpu::NUM_CLIP_PLANES; ++i) {
                        const auto& plane = Regs().clip_user_data[i];
                        planes[i * 4 + 0] = std::bit_cast<float>(plane.data_x);
                        planes[i * 4 + 1] = std::bit_cast<float>(plane.data_y);
                        planes[i * 4 + 2] = std::bit_cast<float>(plane.data_z);
                        planes[i * 4 + 3] = std::bit_cast<float>(plane.data_w);
                    }
                    const u32 ubo_size = static_cast<u32>(sizeof(planes));
                    const u64 offset = vk_buffer.Copy(planes.data(), ubo_size, alignment);
                    dc.buffer_infos.emplace_back(vk_buffer.Handle(), offset, ubo_size);
                }
            } else if (desc.buffer_type == Shader::BufferType::BdaPagetable) {
                const auto* bda_buffer = buffer_cache.GetBdaPageTableBuffer();
                dc.buffer_infos.emplace_back(bda_buffer->Handle(), 0, bda_buffer->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::FaultBuffer) {
                const auto* fault_buffer = buffer_cache.GetFaultBuffer();
                dc.buffer_infos.emplace_back(fault_buffer->Handle(), 0, fault_buffer->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::SharedMemory) {
                auto& lds_buffer = buffer_cache.GetStreamBuffer();
                const auto& cs_program = CsRegs();
                const auto lds_size = cs_program.SharedMemSize() * cs_program.NumWorkgroups();
                const auto [data, offset] = lds_buffer.Map(lds_size, alignment);
                std::memset(data, 0, lds_size);
                lds_buffer.Commit();
                dc.buffer_infos.emplace_back(lds_buffer.Handle(), offset, lds_size);
            } else {
                UNREACHABLE_MSG("Unexpected buffer type {}", u32(desc.buffer_type));
            }
        } else {
            const auto vsharp =
                prepared ? prepared->buffer_sharps[buffer_index] : desc.GetSharp(stage);
            if (native) {
                native_sharp = vsharp;
            }
            if (witness) witness->guest = vsharp.base_address;
            if (observe_object) {
                ordinal_source = vsharp.base_address;
                captured_from = "buffer-cache-unavailable";
            }
            if (vsharp.GetSize() == 864 && gbuffer_draw &&
                memory->IsValidGpuMapping(vsharp.base_address, 0)) {
                camera_motion->OnConstants(reinterpret_cast<const float*>(vsharp.base_address));
            }
            // Object motion research: the vertex shader buffers of G-buffer draws.
            if (FrameCapture::Active() && gbuffer_draw && stage.sw_stage == Shader::SwStage::Vertex &&
                vsharp.base_address != 0 && memory->IsValidGpuMapping(vsharp.base_address, 0)) {
                const auto* f = reinterpret_cast<const float*>(vsharp.base_address);
                char note[192];
                std::snprintf(note, sizeof(note),
                              "\n  gb vs %08x slot %u at %#llx size %u stride %u: %g %g %g %g",
                              u32(stage.pgm_hash), binding.buffer,
                              (unsigned long long)vsharp.base_address, u32(vsharp.GetSize()),
                              u32(vsharp.GetStride()), f[0], f[1], f[2], f[3]);
                FrameCapture::Note(note);
            }
            if (FrameCapture::Active() && vsharp.base_address != 0 && vsharp.GetSize() != 0 &&
                memory->IsValidGpuMapping(vsharp.base_address, 0)) {
                FrameCapture::Buffer(stage.pgm_hash, binding.buffer, vsharp.base_address,
                                     reinterpret_cast<const void*>(vsharp.base_address),
                                     memory->ClampRangeSize(vsharp.base_address, vsharp.GetSize()));
            }
            const bool exact_base =
                desc.is_uniform && pipeline_cache.GetProfile().uniform_exact_base;
            if (vsharp.base_address == 0 || vsharp.GetSize() == 0) {
                dc.buffer_infos.emplace_back(VK_NULL_HANDLE, 0, VK_WHOLE_SIZE);
            } else if (exact_base && vsharp.base_address % uniform_alignment != 0 &&
                       !buffer_cache.IsRegionGpuModified(
                           vsharp.base_address,
                           memory->ClampRangeSize(vsharp.base_address, vsharp.GetSize()))) {
                // bbport: a uniform buffer the shader reads from the V#'s first byte
                // (Profile::uniform_exact_base) that no uniform-aligned offset reaches, with
                // nothing of it written by the GPU: its bytes as the game wrote them, copied now
                // to an aligned place, as stage A copies the constant ring's.
                const u64 range = std::min<u64>(
                    memory->ClampRangeSize(vsharp.base_address, vsharp.GetSize()), max_uniform_range);
                auto& stream = buffer_cache.GetStreamBuffer();
                const auto [data, at] = stream.Map(range, uniform_alignment);
                ASSERT_MSG(data, "no stream buffer space for a uniform buffer copy");
                memory->CopySparseMemory(vsharp.base_address, data, range);
                if (witness || observe_object) {
                    captured = {data, range};
                    captured_from = "staged-cpu-copy";
                }
                stream.Commit();
#ifdef BB_TEST_SHARED_POST_GRAPH
                if (!members.empty() && range && range <= UINT32_MAX && stream.buffer.allocation &&
                    stream.LastTick() == scheduler.CurrentTick() &&
                    Capture::Contains(0, stream.mapped_data.size(), at, range) &&
                    data == stream.mapped_data.data() + at) {
                    snapshot_uniform(Route::StagedUniform,
                        {{&stream, std::bit_cast<u64>(stream.Handle()), reinterpret_cast<u64>(stream.buffer.allocation),
                          buffer_cache.StructureGeneration()}, vsharp.base_address, at, stream.LastTick(), u32(range)},
                        data);
                }
#endif
                dc.push_data.AddOffset(binding.buffer, 0);
                dc.buffer_infos.emplace_back(stream.Handle(), at, range);
                ++ubo_stats.staged;
            } else {
                const u64 size = memory->ClampRangeSize(vsharp.base_address, vsharp.GetSize());
                if (size != vsharp.GetSize()) {
                    LOG_ERROR(Render, "Clamped size from {} to {} for stage {:#x}",
                              vsharp.GetSize(), size, stage.pgm_hash);
                }
                u64 view_key = 0;
                if (!desc.is_written && !desc.is_formatted) {
                    for (u32 k = 0; k + 1 < dc.packet_view_keys.size(); k += 2) {
                        if (dc.packet_view_keys[k] == vsharp.base_address) {
                            view_key = dc.packet_view_keys[k + 1];
                            break;
                        }
                    }
                }
                const bool memo_read = !view_key && !desc.is_written && !desc.is_formatted &&
                                       VertexMemoOn() && size != 0 &&
                                       buffer_cache.MemoAllowed();
                if (exact_object && buffer_index == 0 && WallStreamOn() &&
                    ReflectionNativeProbe::Match(native->key) == u32(ReflectionFirstHit::PlacedSource::Wall) &&
                    dc.draw_inputs.pipeline && WallStreamStages(*dc.draw_inputs.pipeline)) {
                    const auto& stamp = reflection_probe->stamp;
                    const u64 generation = BbEngine::Loading::Generation();
                    if (stamp && stamp->generation == generation &&
                        stamp->frame == rt_shadow->WindowDiagnosticFrame() && !BbEngine::Loading::ScreenUp()) {
                        wall_probe = buffer_cache.WatchWallStream(vsharp.base_address, u32(size), generation,
                            dc.wall_stream_packet);
                    }
                }
                const auto resolve = [&] {
                    return view_key ? BindByObject(view_key, vsharp.base_address, size)
                        : memo_read ? BindVertexMemo(vsharp.base_address, size)
                                    : buffer_cache.ObtainBuffer(vsharp.base_address, size, desc.is_written,
                                                                desc.is_formatted);
                };
                auto* object3_writer = object3_row && buffer_index == 3 && desc.is_uniform &&
                    !desc.IsSpecial() && !desc.is_written && !desc.is_formatted && desc.only_const_reads &&
                    size == Object3::Bytes && vsharp.GetStride() == 16 && vsharp.num_records == 4
                    ? Object3::Select(this, object3_row->generation, object3_row->sequence, &buffer_cache,
                                      vsharp.base_address, view_key ? Object3::Resolver::Object :
                                      memo_read ? Object3::Resolver::VertexMemo : Object3::Resolver::Direct, view_key)
                    : nullptr;
#ifdef BB_TEST_SHARED_POST_GRAPH
                std::optional<UploadWatch> post_upload;
                if (!members.empty() && size && size <= UINT32_MAX)
                    post_upload.emplace(*post_uniform->watch, vsharp.base_address, u32(size), members);
#endif
                const auto [buffer, offset] = [&] {
                    Object3::Watch watch(object3_writer);
                    return resolve();
                }();
                if (object3_writer) {
                    Object3::state.chosen.bound_match = object3_writer->buffer == buffer &&
                        object3_writer->offset == offset;
                }
                if (wall_probe) {
                    buffer_cache.UnwatchWallStream();
                    if (wall_probe->route == VideoCore::BufferCache::WallStreamProbe::Route::None) {
                        wall_probe = nullptr;
                    }
                }
                // bbport: IsInPlace/IsAnyInPlace are only the trace's arguments; without
                // BB_TRACE_SHADER they are not looked up. Experiment bit 32768 = old behaviour
                // (looked up on every binding).
                if (BbToggle::Experiment(32768) || TraceShaderOn()) {
                    TraceShaderBinding(stage, vsharp.base_address, size, desc.is_written,
                                       buffer_cache.IsInPlace(vsharp.base_address, size),
                                       buffer_cache.IsAnyInPlace(vsharp.base_address, size));
                }
                // bbport: a uniform buffer's offset follows the uniform alignment (64 on NVIDIA);
                // the shader adds the remainder (push data, at most 255 bytes).
                const u64 offset_aligned =
                    Common::AlignDown(offset, desc.is_uniform ? uniform_alignment : alignment);
                const u64 adjust = offset - offset_aligned;
                if (adjust % 4 != 0) {
                    LOG_WARNING(Render_Vulkan, "Buffer binding in shader {:#x} isn't dword aligned",
                                stage.pgm_hash);
                }
                if (exact_base && adjust != 0) {
                    // The same for bytes the GPU wrote: copied on the GPU, right before the draw,
                    // so they are what an in-place read would have seen.
                    const u64 range = std::min<u64>(size, max_uniform_range);
                    auto& stream = buffer_cache.GetStreamBuffer();
                    const auto at = stream.Reserve(range, uniform_alignment);
                    ASSERT_MSG(at, "no stream buffer space for a uniform buffer copy");
                    const vk::BufferCopy region{.srcOffset = offset, .dstOffset = *at, .size = range};
                    runtime.CopyBuffer(buffer, &stream, std::span{&region, 1});
                    dc.push_data.AddOffset(binding.buffer, 0);
                    dc.buffer_infos.emplace_back(stream.Handle(), *at, range);
                    dc.bound_buffers.emplace_back(&stream, *at, u32(range), false);
                    native_buffer = &stream;
                    dc.needs_barrier = true;
                    ++ubo_stats.copied;
                    if (witness) witness->source = "gpu-copy-unavailable";
                    if (observe_object) {
                        captured_from = "gpu-copy-unavailable";
                    }
                } else {
                    if (witness && !desc.is_written) guest_available = size;
                    if (desc.is_uniform) {
                        ++(adjust ? ubo_stats.offset : ubo_stats.in_place);
                    }
                    dc.push_data.AddOffset(binding.buffer, adjust);
                    dc.buffer_infos.emplace_back(buffer->Handle(), offset_aligned,
                                              desc.is_uniform ? std::min<u64>(size + adjust, max_uniform_range)
                                                              : size + adjust);
                    dc.bound_buffers.emplace_back(buffer, offset, size, desc.is_written);
                    native_buffer = buffer;
#ifdef BB_TEST_SHARED_POST_GRAPH
                    if (post_upload) {
                        take_uniform(*post_upload,
                            {{buffer, std::bit_cast<u64>(buffer->Handle()),
                              reinterpret_cast<u64>(buffer->buffer.allocation), buffer_cache.StructureGeneration()},
                             vsharp.base_address, offset, 0, u32(size)}, Route::None);
                    }
#endif
                    if (observe_object && buffer == &buffer_cache.GetStreamBuffer()) {
                        // The returned binding alone does not attest completion of a host copy.
                        captured_from = "stream-copy-unproven";
                    }
                }
                if (desc.is_written) {
                    // Raw storage-buffer writes can also make an aliased cached image stale.
                    hang_gpu_watch.Written(stage.pgm_hash, static_cast<u32>(stage.sw_stage), vsharp.base_address, size); // bbport (r112p_hang-gpu-palette-lanterns): palette writers (BB_WIND_HANG)
                    const VideoCore::InvalidateReason reason{"storage buffer"};
                    texture_cache.InvalidateMemoryFromGPU(vsharp.base_address, size);
                    // bbport (BB_FRAME_STATS diagnostics): the shaders that write a large image
                    // through a buffer, which makes its next binding detile and upload all of it.
                    // Each shader and address is looked up once, 64 at most.
                    if (size >= (4ull << 20) && BbStats::enabled) {
                        static std::mutex said_mutex;
                        static std::vector<std::pair<u64, VAddr>> said;
                        const std::pair<u64, VAddr> said_key{stage.pgm_hash, vsharp.base_address};
                        std::scoped_lock said_lock{said_mutex};
                        if (said.size() < 64 && std::ranges::find(said, said_key) == said.end()) {
                            said.push_back(said_key);
                            if (const auto written_id = texture_cache.FindImageFromRange(
                                    vsharp.base_address, size, false)) {
                                const auto& written = texture_cache.GetImage(written_id).info;
                                std::printf(
                                    "Image written through a buffer: shader %016llx writes "
                                    "%#llx+%#llx over image %s %ux%u, %u levels, %#x bytes "
                                    "(level 0 %#x): uploaded whole at its next binding\n",
                                    static_cast<unsigned long long>(stage.pgm_hash),
                                    static_cast<unsigned long long>(vsharp.base_address),
                                    static_cast<unsigned long long>(size),
                                    vk::to_string(written.pixel_format).c_str(),
                                    written.size.width, written.size.height,
                                    written.resources.levels, written.guest_size,
                                    written.mips_layout[0].size);
                            }
                        }
                    }
                }
                dc.needs_barrier |= runtime.IsBufferAccessed(buffer, offset, size, desc.is_written);
            }
        }

        auto& set_write = dc.set_writes[write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified++;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = 1;
        set_write.descriptorType = desc.is_uniform ? vk::DescriptorType::eUniformBuffer
                                                   : vk::DescriptorType::eStorageBuffer;
        set_write.pBufferInfo = &dc.buffer_infos.back();
#ifdef BB_TEST_SHARED_POST_GRAPH
        for (const auto member : members) {
            auto& raw = post_uniform->bytes[PacketSlot(member.use, member.slot)];
            raw.descriptor = *set_write.pBufferInfo;
            raw.descriptor_write = write_index - 1;
            raw.adjust = dc.push_data.buf_offsets[binding.buffer];
        }
#endif
        if (ordinal_zero) {
            ReflectionNativeProbe::RecordOrdinalZero(*native, desc,
                native_sharp.value_or(AmdGpu::Buffer::Null()), *set_write.pBufferInfo,
                set_write.dstBinding, dc.push_data.buf_offsets[binding.buffer], ordinal_source,
                prepared != nullptr, captured_from, captured);
        }
        if (object3_row && exact_object) {
            const auto& bound = *set_write.pBufferInfo;
            const auto sharp = native_sharp.value_or(AmdGpu::Buffer::Null());
            const Object3::Descriptor descriptor{
                .sharp = std::bit_cast<std::array<u32, 4>>(sharp), .guest = ordinal_source,
                .bytes = sharp.GetSize(), .handle = std::bit_cast<u64>(bound.buffer), .offset = bound.offset,
                .range = bound.range, .slot = set_write.dstBinding, .adjust = dc.push_data.buf_offsets[binding.buffer],
                .write_index = write_index - 1, .push_index = binding.buffer,
                .flags = u32(desc.is_uniform) | (u32(desc.is_written) << 1) |
                    (u32(desc.is_formatted) << 2) | (u32(desc.only_const_reads) << 3) | (u32(desc.IsSpecial()) << 4),
            };
            auto& sample = Object3::state.working;
            (buffer_index == 0 ? sample.object0 : sample.object3) = descriptor;
            auto& chosen = Object3::state.chosen;
            if (buffer_index == 3 && chosen.active && chosen.draw.sequence == object3_row->sequence) {
                chosen.draw.object3 = descriptor;
                chosen.expected_descriptor = descriptor.slot == 23 && descriptor.flags == 9 &&
                    std::string_view{captured_from} == "stream-copy-unproven" &&
                    Object3::ReservationMatches(descriptor, &buffer_cache);
            }
        }
        if (exact_object) {
            ReflectionNativeProbe::RecordExactObject(ReflectionFirstRetire::Current(this), *native, buffer_index, desc,
                native_sharp.value_or(AmdGpu::Buffer::Null()), *set_write.pBufferInfo,
                set_write.dstBinding, dc.push_data.buf_offsets[binding.buffer], ordinal_source,
                captured_from, captured);
        }
        if (wall_probe) {
            dc.wall_stream = {wall_probe, *set_write.pBufferInfo, ordinal_source,
                              set_write.dstBinding, dc.push_data.buf_offsets[binding.buffer], write_index - 1,
                              std::string_view{captured_from} == "stream-copy-unproven", false};
        }
        if (native_sharp && native_sharp->Valid() && native_sharp->GetStride() == 16 &&
            Motion::ClassifyBuffer(native_sharp->GetSize()) == Motion::BufferRole::SmallSkeleton) {
            const auto& bound = dc.buffer_infos.back();
            const u32 size = native_sharp->GetSize();
            const auto guest = native_sharp->base_address;
            const bool range_known = memory->IsValidGpuMapping(guest, 0) &&
                                     memory->ClampRangeSize(guest, size) == size;
            const u32 adjust = dc.push_data.buf_offsets[binding.buffer];
            if (native->binding_count == native->bindings.size()) {
                native->overflow = true;
            } else {
                auto& observed = native->bindings[native->binding_count++];
                observed = {
                    .buffer = native_buffer, .handle = bound.buffer,
                    .guest = guest, .descriptor_offset = bound.offset,
                    .descriptor_range = bound.range, .ordinal = buffer_index,
                    .slot = set_write.dstBinding, .adjust = adjust, .guest_bytes = size,
                    .effective_bytes = bound.range == VK_WHOLE_SIZE || bound.range <= adjust
                        ? 0u : u32(std::min<u64>(size, bound.range - adjust)),
                    .range_known = range_known,
                    .gpu_dirty = range_known && buffer_cache.IsRegionGpuModified(guest, size),
                    .in_place = range_known && buffer_cache.IsInPlace(guest, size),
                    .writable = desc.is_written,
                };
            }
        }
        if (witness) {
            const auto& bound = dc.buffer_infos.back();
            witness->seen = true;
            witness->binding = set_write.dstBinding;
            witness->handle = std::bit_cast<u64>(bound.buffer);
            witness->descriptor_offset = bound.offset;
            witness->descriptor_range = bound.range;
            witness->shader_offset = dc.push_data.buf_offsets[binding.buffer];
            if (!captured.empty()) {
                witness->Copy(captured, captured_from);
            } else if (const auto length = witness->Retainable(guest_available); length && witness->guest) {
                if (!memory->IsValidMapping(witness->guest, length)) {
                    witness->source = "guest-unmapped";
                } else if (buffer_cache.IsRegionGpuModified(witness->guest, length)) {
                    witness->source = "gpu-modified-unavailable";
                } else {
                    memory->CopySparseMemory(witness->guest, witness->bytes.data(), length);
                    witness->size = u32(length);
                    // A mapped guest snapshot is less authoritative than owned staging bytes.
                    witness->source = "guest-clean-at-bind";
                }
            }
        }
        ++binding.buffer;
    }
}

Rasterizer::ImageDescCacheEntry& Rasterizer::CachedImageDescEntry(const AmdGpu::Image& sharp,
                                                                   const Shader::ImageResource& res,
                                                                   u64 hash) {
    auto& dc = Dc();
    std::array<u64, 4> key;
    std::memcpy(key.data(), &sharp, sizeof(key));
    const u32 flags = u32(res.is_written) | u32(res.is_depth) << 1 | u32(res.is_array) << 2;
    // Two-way set associative: a frame binds a few thousand distinct T#s.
    auto* set = &image_desc_cache[(hash % (image_desc_cache.size() / 2)) * 2];
    const auto matches = [&](const ImageDescCacheEntry& e) {
        return e.flags == flags && e.sharp == key;
    };
    const bool disabled = BbToggle::Disabled(BbToggle::ImageDescCache);
    ImageDescCacheEntry* slot = nullptr;
    if (!disabled && matches(set[0])) {
        slot = &set[0];
    } else if (!disabled && matches(set[1])) {
        slot = &set[1];
    } else {
        // Replace the least recently used way that no binding of this call points at.
        slot = set[0].last_use <= set[1].last_use ? &set[0] : &set[1];
        if (slot->pinned == bind_epoch) {
            slot = slot == &set[0] ? &set[1] : &set[0];
        }
        if (slot->pinned == bind_epoch) {
            slot = &dc.image_desc_overflow.emplace_back();
        }
    }
    slot->last_use = ++desc_use_counter;
    auto& entry = *slot;
    if (entry.flags != flags || entry.sharp != key ||
        BbToggle::Disabled(BbToggle::ImageDescCache)) {
        entry.desc = VideoCore::TextureCache::ImageDesc{sharp, res};
        entry.sharp = key;
        entry.flags = flags;
        entry.found_generation = ~0ULL;
        entry.found_exact = false;
        entry.view_memo = {};
    }
    return entry;
}

bool Rasterizer::MemoRevalidation() {
    static const bool on = [] {
        const char* env = std::getenv("BB_MEMO_REVALIDATE");
        return !(env && env[0] == '0');
    }();
    return on;
}

bool Rasterizer::LookupMemoized(ImageDescCacheEntry& entry, u64 generation) {
    if (entry.found_generation == generation) {
        return true;
    }
    // An image (un)registered since: an exact match still registered is what FindImage would
    // find again (TextureCache::IsExactMatch).
    if (!entry.found_exact || entry.found_generation == ~0ULL || !MemoRevalidation() ||
        !texture_cache.IsRegisteredImage(entry.found_id, entry.found_uid)) {
        return false;
    }
    entry.found_generation = generation;
    // A view memoized behind a depth redirect: that image may have been replaced in its slot.
    if (entry.view_memo.image_id != entry.found_id) {
        entry.view_memo = {};
    }
    ++texture_lookups_revalidated;
    return true;
}

void Rasterizer::ReportSlowTextureBind(const Shader::Info& stage, u64 start,
                                       std::span<const u64> pass1, std::span<const u64> pass2) {
    auto& dc = Dc();
    static const double cycles_per_us = [] {
        const auto t0 = std::chrono::steady_clock::now();
        const u64 c0 = __rdtsc();
        while (std::chrono::steady_clock::now() - t0 < std::chrono::milliseconds(10)) {
        }
        const double us =
            std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count();
        return double(__rdtsc() - c0) / us;
    }();
    static u32 reports = 0;
    const double total_us = double(pass2.back() - start) / cycles_per_us;
    if (total_us < 300.0 || reports >= 30) {
        return;
    }
    ++reports;
    std::printf("Slow texture bind %u: %s %016llx %.0f us, %zu textures, %zu bindings; first pass us:",
                reports, stage.sw_stage == Shader::SwStage::Compute ? "cs" : "gfx",
                static_cast<unsigned long long>(stage.pgm_hash), total_us, stage.images.size(),
                dc.image_bindings.size());
    for (size_t i = 0; i + 1 < pass1.size(); ++i) {
        std::printf(" %.0f", double(pass1[i + 1] - pass1[i]) / cycles_per_us);
    }
    std::printf("\n");
    for (size_t b = 0; b < dc.image_bindings.size() && b + 1 < pass2.size(); ++b) {
        const double us = double(pass2[b + 1] - pass2[b]) / cycles_per_us;
        const auto& [id, desc] = dc.image_bindings[b];
        if (!id) {
            std::printf("  binding %zu: %.0f us, null\n", b, us);
            continue;
        }
        const auto& image = texture_cache.GetImage(id);
        std::printf("  binding %zu: %.0f us; image %u %s %ux%u mips %u layers %u tile %u at %#llx "
                    "size %u, flags %#x, %s, %s\n",
                    b, us, id.index, vk::to_string(image.info.pixel_format).c_str(),
                    image.info.size.width, image.info.size.height, image.info.resources.levels,
                    image.info.resources.layers, static_cast<u32>(image.info.tile_mode),
                    static_cast<unsigned long long>(image.info.guest_address), image.info.guest_size,
                    static_cast<u32>(image.flags),
                    desc->type == VideoCore::TextureCache::BindingType::Storage ? "storage" : "sampled",
                    image.info.props.is_depth ? "depth" : "color");
    }
    std::fflush(stdout);
}

/// bbport BB_PROXY_TRACE=1 (diagnostics): the first read of each shader and image through a
/// reduced scene proxy, with the shader's sampler filters (0 point, 1 bilinear, 2 aniso point,
/// 3 aniso linear) and the pass reading it (graphics: known once the pass begins, so the reads
/// wait for FlushProxyReads): a point-filtered read of a proxy by a pass at the native size is
/// a nearest-neighbour upscale.
static bool ProxyTraceOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_PROXY_TRACE");
        return env && env[0] == '1';
    }();
    return on;
}
struct PendingProxyRead {
    u64 shader;
    VAddr image;
    std::string text;
};
// Only the draw recording thread binds proxies (never the texture helper). Not thread_local:
// that broke the link of Shader::Info's thread-local snapshots (clang, MinGW).
static std::vector<PendingProxyRead> pending_proxy_reads;

/// kind: 0 compute, 1 reduced pass, 2 native pass (each printed once per shader and image).
static void PrintProxyRead(u64 shader, VAddr image, int kind, const std::string& text,
                           const std::string& pass) {
    static std::mutex mutex;
    static std::vector<std::tuple<u64, VAddr, int>> seen;
    std::scoped_lock lock{mutex};
    const auto key = std::make_tuple(shader, image, kind);
    if (seen.size() >= 400 || std::find(seen.begin(), seen.end(), key) != seen.end()) {
        return;
    }
    seen.push_back(key);
    std::printf("Proxy read: %s; %s\n", text.c_str(), pass.c_str());
}

static void TraceProxyRead(const Shader::Info& stage, const VideoCore::Image& image,
                           SceneResolution::Size proxy) {
    if (!ProxyTraceOn()) {
        return;
    }
    std::string filters;
    bool point = false;
    for (const auto& sampler : stage.samplers) {
        const auto sharp = sampler.GetSharp(stage);
        const u32 mag = u32(sharp.xy_mag_filter.Value()), min = u32(sharp.xy_min_filter.Value());
        filters += fmt::format(" {}/{}", mag, min);
        point |= mag == u32(AmdGpu::Filter::Point) || mag == u32(AmdGpu::Filter::AnisoPoint);
    }
    const bool compute = stage.sw_stage == Shader::SwStage::Compute;
    std::string text = fmt::format("{} {:016x} {} {}x{} from a {}x{} proxy, sampler mag/min:{}{}",
                                   compute ? "cs" : "gfx", stage.pgm_hash,
                                   vk::to_string(image.info.pixel_format), image.info.size.width,
                                   image.info.size.height, proxy.width, proxy.height, filters,
                                   point ? " POINT" : "");
    if (compute) {
        PrintProxyRead(stage.pgm_hash, image.info.guest_address, 0, text, "compute (native size)");
    } else {
        pending_proxy_reads.push_back({stage.pgm_hash, image.info.guest_address, std::move(text)});
    }
}

/// The pass of the graphics reads noted since the last call has begun.
static void FlushProxyReads(bool reduced, const VideoCore::Image* target) {
    if (pending_proxy_reads.empty()) {
        return;
    }
    const std::string pass =
        target ? fmt::format("pass {} {}x{}", reduced ? "reduced" : "NATIVE",
                             target->info.size.width, target->info.size.height)
               : std::string{reduced ? "pass reduced" : "pass NATIVE"};
    for (const auto& read : pending_proxy_reads) {
        PrintProxyRead(read.shader, read.image, reduced ? 1 : 2, read.text, pass);
    }
    pending_proxy_reads.clear();
}

void Rasterizer::BindTextures(const Shader::Info& stage, const PreparedStage* prepared,
                              Shader::Backend::Bindings& binding, u32& write_index,
                              bool& barrier, bool on_helper) {
    auto& dc = Dc();
    BB_SECTION(BindTextures);
    auto* ivy = stage.sw_stage == Shader::SwStage::Fragment &&
                        stage.pgm_hash == IvyMaterialProbe::Fragment ? dc.ivy_material : nullptr;
    if (ivy) {
        ivy->images = u32(stage.images.size());
        ivy->first_image_binding = binding.unified;
        ivy->tsharps_complete = stage.images.size() == IvyMaterialProbe::ImageCount;
    }
    if (window_receiver && !on_helper && stage.sw_stage == Shader::SwStage::Fragment) {
        window_receiver->BeginFragment(stage.pgm_hash);
    }
    static const bool empty_fast = [] {
        const char* env = std::getenv("LANTERN_EMPTY_TEXTURE_STAGES");
        return !(env && env[0] == '0');
    }();
    if (empty_fast && stage.images.empty()) {
        if (!on_helper) {
            ++texture_set_skip[1];
        }
        BindSamplers(stage, prepared, binding, write_index, false);
        return;
    }
    const u32 first_image_idx = dc.image_infos.size();
    TextureSet* set_slot = nullptr;
    // bbport: this stage is the consumer of a resolve its native reads cause (SceneUse; after
    // the return of stages without images, which are most vertex stages).
    const SceneUseScope scene_use{stage.sw_stage == Shader::SwStage::Compute
                                      ? "dispatch textures, cs"
                                      : "draw textures, stage",
                                  stage.pgm_hash};
    // bbport: a stage the draw-preparation workers did not reach reads its T#s and their
    // description hashes here, as PrepareResources does, so it can take the memoized texture set
    // too: in heavy scenes ~40% of draws were unprepared and their full lookups were two thirds of
    // texture binding. BB_LOCAL_TEXTURE_SETS=0: the full lookup for them, as before.
    static const bool local_sets = [] {
        const char* env = std::getenv("BB_LOCAL_TEXTURE_SETS");
        return !(env && env[0] == '0');
    }();
    PreparedStage local{};
    std::array<AmdGpu::Image, TextureSet::MaxImages> local_sharps;
    std::array<u64, TextureSet::MaxImages> local_hashes;
    const PreparedStage* images = prepared;
    if (!prepared && !on_helper && local_sets && !stage.images.empty() &&
        stage.images.size() <= TextureSet::MaxImages) {
        for (u32 i = 0; i < stage.images.size(); ++i) {
            local_sharps[i] = stage.images[i].GetSharp(stage);
            local_hashes[i] = ImageDescHash(local_sharps[i], stage.images[i]);
        }
        local.image_sharps = local_sharps.data();
        local.image_hashes = local_hashes.data();
        local.num_images = static_cast<u32>(stage.images.size());
        images = &local;
    }
    if (!on_helper && BindTexturesFromSet(stage, images, first_image_idx, barrier, set_slot)) {
        // Descriptor writes: one per image (no mip arrays in a memoized set).
        for (u32 i = 0; i < stage.images.size(); ++i) {
            if (ivy && ivy->tsharps_complete) {
                ivy->tsharps[i] = std::bit_cast<std::array<u32, 8>>(images->image_sharps[i]);
            }
            auto& set_write = dc.set_writes[write_index++];
            set_write.dstSet = VK_NULL_HANDLE;
            set_write.dstBinding = binding.unified++;
            set_write.dstArrayElement = 0;
            set_write.descriptorCount = 1;
            set_write.descriptorType = vk::DescriptorType::eSampledImage;
            set_write.pImageInfo = &dc.image_infos[first_image_idx + i];
        }
        BindSamplers(stage, prepared, binding, write_index, false);
        return;
    }
    BB_SECTION(TexFull);
    BbSections::Scope empty_scope{stage.images.empty() ? BbSections::TexFullEmpty : BbSections::Count};
    BbSections::KeyScope full_by_shader{BbSections::tex_full_by_shader, stage.pgm_hash};
    if (!stage.images.empty()) {
        empty_scope.start = 0;
    } else {
        full_by_shader.start = 0;
    }
    dc.image_bindings.clear();
    dc.image_binding_entries.clear();
    dc.image_desc_overflow.clear();
    dc.image_desc_storage.clear();
    ++bind_epoch;
    bool ui_replaced = false; ///< a 4K menus replacement is bound (SmoothUiSampler)
    bool ui_other = false;    ///< and a sampled image that isn't one
    // To emulate storing to explicit mip levels, build a descriptor array with each mip level.
    boost::container::small_vector<u32, 8> image_descriptor_array_sizes;
    // TextureSetMemo: what this call resolves, to remember when the set qualifies.
    std::array<TextureSetEntry, TextureSet::MaxImages> resolved{};
    std::array<u64, TextureSet::MaxImages> resolved_uids{};
    bool set_ok = set_slot != nullptr;
    // Every lookup an exact match without a depth redirect, every null descriptor a null T#
    // (TextureSet::exact).
    bool set_exact = set_ok;
    const auto note_found = [&](u32 binding_index, VideoCore::ImageId found, u64 uid,
                                bool exact) {
        if (binding_index < resolved.size()) {
            resolved[binding_index].found = found;
            resolved_uids[binding_index] = uid;
        }
        set_exact &= exact;
    };
    // SampleSceneProxies: bindings that may read a reduced scene proxy instead of the native
    // image (normalized sampling only; see Shader::ImageResource::needs_native).
    boost::container::small_vector<bool, 16> binding_proxy_ok;
    const bool sample_proxies = !BbToggle::Disabled(BbToggle::SampleSceneProxies) &&
                                !on_helper && scene_targets->Reduced() &&
                                !PointReadsNative(stage, prepared);
    const SceneUseScope point_use{
        !on_helper && scene_targets->Reduced() && !sample_proxies &&
                !BbToggle::Disabled(BbToggle::SampleSceneProxies)
            ? (stage.sw_stage == Shader::SwStage::Compute
                   ? "dispatch textures, point sampler in the stage (PointReadsNative), cs"
                   : "draw textures, point sampler in the stage (PointReadsNative), stage")
            : SceneUseScope::current.what,
        stage.pgm_hash};
    // bbport BB_SECTIONS: a full lookup over 0.3 ms is reported (the first 30) with the time of
    // each texture in both passes, to see which image and which step costs it.
    const bool time_slow = BbSections::Enabled() && BbSections::recording_thread &&
                           !stage.images.empty();
    boost::container::small_vector<u64, 24> pass1_stamps, pass2_stamps;
    const u64 full_start = time_slow ? __rdtsc() : 0;

    for (u32 image_index = 0; image_index < stage.images.size(); ++image_index) {
        if (time_slow) {
            pass1_stamps.push_back(__rdtsc());
        }
        const auto& image_desc = stage.images[image_index];
        const auto tsharp =
            images ? images->image_sharps[image_index] : image_desc.GetSharp(stage);
        if (ivy && ivy->tsharps_complete) {
            ivy->tsharps[image_index] = std::bit_cast<std::array<u32, 8>>(tsharp);
        }
        // bbport: a hash lookup per texture per draw for a diagnostic only.
        static const bool warn_meta = std::getenv("BB_WARN_META_TEXTURE") != nullptr;
        if (warn_meta && texture_cache.IsMeta(tsharp.Address())) {
            LOG_WARNING(Render_Vulkan, "Unexpected metadata read by a shader (texture)");
        }

        const auto data_fmt = tsharp.GetDataFmt();
        const auto num_fmt = tsharp.GetNumberFmt();
        if (tsharp.Address() == 0 || data_fmt == AmdGpu::DataFormat::FormatInvalid) {
            dc.image_bindings.emplace_back(VideoCore::ImageId{}, &dc.image_desc_storage.emplace_back());
            dc.image_binding_entries.push_back(nullptr);
            binding_proxy_ok.push_back(false);
            image_descriptor_array_sizes.push_back(1);
            continue;
        }

        if (!memory->IsValidGpuMapping(tsharp.Address(), 0) ||
            !IsKnownFormat(data_fmt, num_fmt)) {
            LOG_WARNING(Render_Vulkan,
                        "Rejecting invalid T# address={:#x}, pitch={}, width={}, "
                        "data_format={}, num_format={}",
                        tsharp.Address(), tsharp.pitch, tsharp.width, static_cast<u32>(data_fmt),
                        static_cast<u32>(num_fmt));
            set_exact = false; // may resolve once the memory is mapped
            dc.image_bindings.emplace_back(VideoCore::ImageId{}, &dc.image_desc_storage.emplace_back());
            dc.image_binding_entries.push_back(nullptr);
            binding_proxy_ok.push_back(false);
            image_descriptor_array_sizes.push_back(1);
            continue;
        }

        const Shader::MipStorageFallbackMode mip_fallback_mode = image_desc.mip_fallback_mode;
        // Same as image_desc.NumBindings(stage), without fetching the T# again.
        const u32 num_bindings =
            mip_fallback_mode == Shader::MipStorageFallbackMode::DynamicIndex
                ? static_cast<u32>(tsharp.last_level - tsharp.base_level + 1)
                : 1u;
        const bool proxy_candidate = sample_proxies && num_bindings == 1 &&
                                     !image_desc.needs_native && !image_desc.is_written &&
                                     mip_fallback_mode == Shader::MipStorageFallbackMode::None;

        auto& desc_entry =
            images ? CachedImageDescEntry(tsharp, image_desc, images->image_hashes[image_index])
                   : CachedImageDescEntry(tsharp, image_desc);
        // BB_SCENE_DEBUG: proxied scene targets this binding reads at the native size, and why.
        const auto debug_native = [&](const VideoCore::Image& image) {
            if (!scene_debug_frame || proxy_candidate || !image.scene_proxy) return;
            std::printf("Scene native read: %s %016llx %s %ux%u needs_native %d written %d "
                        "bindings %u mip_fallback %d\n",
                        stage.sw_stage == Shader::SwStage::Compute ? "cs" : "gfx",
                        (unsigned long long)stage.pgm_hash,
                        vk::to_string(image.info.pixel_format).c_str(), image.info.size.width,
                        image.info.size.height, int(image_desc.needs_native),
                        int(image_desc.is_written), num_bindings, int(mip_fallback_mode));
        };
        for (auto i = 0; i < num_bindings; i++) {
            // bbport: a plain binding (no mip override) of the same T# resolves to the same image
            // while no image was registered or unregistered.
            if (mip_fallback_mode == Shader::MipStorageFallbackMode::None &&
                !BbToggle::Disabled(BbToggle::TextureBindingMemo) &&
                LookupMemoized(desc_entry, texture_cache.RegistryGeneration())) {
                desc_entry.pinned = bind_epoch;
                note_found(static_cast<u32>(dc.image_bindings.size()), desc_entry.found_id,
                           desc_entry.found_uid, desc_entry.found_exact);
                auto& [image_id, _] =
                    dc.image_bindings.emplace_back(desc_entry.found_id, &desc_entry.found_desc);
                dc.image_binding_entries.push_back(&desc_entry);
                binding_proxy_ok.push_back(proxy_candidate);
                texture_cache.MarkFound(image_id);
                auto* image = &texture_cache.GetImage(image_id);
                if (auto depth_image_id = texture_cache.GetAssociatedDepth(*image)) {
                    image_id = depth_image_id;
                    image = &texture_cache.GetImage(image_id);
                    set_exact = false;
                }
                debug_native(*image);
                if (image->binding.is_bound) {
                    image->binding.force_general |= image_desc.is_written;
                }
                image->binding.is_bound = 1u;
                continue;
            }
            auto& desc = dc.image_desc_storage.emplace_back(desc_entry.desc);
            auto& [image_id, _] = dc.image_bindings.emplace_back(VideoCore::ImageId{}, &desc);
            dc.image_binding_entries.push_back(nullptr);
            binding_proxy_ok.push_back(proxy_candidate);

            if (mip_fallback_mode == Shader::MipStorageFallbackMode::ConstantIndex) {
                ASSERT(num_bindings == 1);
                desc.view_info.range.base.level += image_desc.constant_mip_index;
                desc.view_info.range.extent.levels = 1;
            } else if (mip_fallback_mode == Shader::MipStorageFallbackMode::DynamicIndex) {
                desc.view_info.range.base.level += i;
                desc.view_info.range.extent.levels = 1;
            }

            const u64 generation = texture_cache.RegistryGeneration();
            const u32 binding_index = static_cast<u32>(dc.image_bindings.size() - 1);
            image_id = texture_cache.FindImage(desc);
            // FindImage moved no view into another image's mips or layers, and found the
            // registered image of exactly this description.
            const bool exact = mip_fallback_mode == Shader::MipStorageFallbackMode::None &&
                               desc.view_info.range == desc_entry.desc.view_info.range &&
                               texture_cache.IsExactMatch(image_id, desc.info);
            const u64 uid = texture_cache.ImageUid(image_id);
            if (mip_fallback_mode == Shader::MipStorageFallbackMode::None &&
                generation == texture_cache.RegistryGeneration() &&
                desc_entry.pinned != bind_epoch) {
                desc_entry.found_generation = generation;
                desc_entry.found_id = image_id;
                desc_entry.found_desc = desc;
                desc_entry.found_exact = exact;
                desc_entry.found_uid = uid;
                desc_entry.view_memo = {};
            }
            note_found(binding_index, image_id, uid, exact);
            auto* image = &texture_cache.GetImage(image_id);
            if (auto depth_image_id = texture_cache.GetAssociatedDepth(*image)) {
                // If this image has an associated depth image, it's a stencil attachment.
                // Redirect the access to the actual depth-stencil buffer.
                image_id = depth_image_id;
                image = &texture_cache.GetImage(image_id);
                set_exact = false;
            }
            debug_native(*image);
            if (image->binding.is_bound) {
                // The image is already bound. In case if it is about to be used as storage we
                // need to force general layout on it.
                image->binding.force_general |= image_desc.is_written;
            }
            image->binding.is_bound = 1u;
        }

        image_descriptor_array_sizes.push_back(num_bindings);
    }
    // bbport (r62_leaf-stage3): what this pixel shader's lookups found, for its card's layer
    // (NoteCardLayer). Only when every image took one binding: then a binding's index is its
    // image's.
    if (card_bound_on && stage.sw_stage == Shader::SwStage::Fragment) {
        const bool one_each = dc.image_bindings.size() == stage.images.size() &&
                              stage.images.size() <= resolved.size();
        dc.card_bound.stage = one_each ? &stage : nullptr;
        dc.card_bound.count = one_each ? static_cast<u32>(stage.images.size()) : 0u;
        for (u32 i = 0; i < dc.card_bound.count; ++i) {
            dc.card_bound.ids[i] = resolved[i].found;
            dc.card_bound.uids[i] = resolved_uids[i];
        }
    }

    if (time_slow) {
        pass1_stamps.push_back(__rdtsc());
    }
    // Second pass to re-bind images that were updated after binding
    for (u32 binding_index = 0; binding_index < dc.image_bindings.size(); ++binding_index) {
        if (time_slow) {
            pass2_stamps.push_back(__rdtsc());
        }
        auto& [image_id, desc_ptr] = dc.image_bindings[binding_index];
        auto* memo_entry = dc.image_binding_entries[binding_index];
        const auto& desc = *desc_ptr;
        bool is_storage = desc.type == VideoCore::TextureCache::BindingType::Storage;
        if (!image_id) {
            dc.image_infos.emplace_back(VK_NULL_HANDLE, VK_NULL_HANDLE, vk::ImageLayout::eGeneral);
        } else {
            if (auto& old_image = texture_cache.GetImage(image_id);
                old_image.binding.needs_rebind) {
                old_image.binding = {};
                auto& rebind_desc = dc.image_desc_storage.emplace_back(desc);
                desc_ptr = &rebind_desc;
                image_id = texture_cache.FindImage(rebind_desc);
                memo_entry = nullptr;
                set_ok = false;
            }

            dc.bound_images.emplace_back(image_id);

            auto& image = texture_cache.GetImage(image_id);
            auto& image_view = texture_cache.FindTexture(
                image_id, desc, memo_entry ? &memo_entry->view_memo : nullptr, !on_helper);
            const auto binding = image.binding;

            // bbport: a proxied scene image sampled with normalized coordinates reads the proxy:
            // no resample to the native size (the native image is not touched).
            if (binding_proxy_ok[binding_index] && !is_storage && !binding.force_general &&
                !binding.is_target &&
                !(upscaler->Enabled() && upscaler->RedirectsSampled(image_id))) {
                if (const auto proxy = scene_targets->SampleProxy(image, desc.view_info)) {
                    TraceProxyRead(stage, image, scene_targets->ProxySize(image));
                    image.usage.texture = 1u;
                    dc.image_infos.emplace_back(VK_NULL_HANDLE, proxy->view, proxy->layout);
                    if (set_ok && binding_index < resolved.size()) {
                        resolved[binding_index] = {image_id, resolved[binding_index].found,
                                                   proxy->view, image.backing,
                                                   desc.view_info.range, true};
                    }
                    ++proxy_samples;
                    continue;
                }
            }
            if (image.ui_key && !is_storage && !binding.force_general && !binding.is_target) {
                if (VideoCore::Image* ui = texture_cache.UiReplacement(image)) {
                    barrier |= runtime.Transit(ui, vk::ImageLayout::eShaderReadOnlyOptimal,
                                               vk::PipelineStageFlagBits2::eAllCommands,
                                               vk::AccessFlagBits2::eShaderRead);
                    VideoCore::ImageViewInfo ui_view = desc.view_info;
                    ui_view.format = ui->info.pixel_format;
                    ui_view.type = AmdGpu::ImageType::Color2D;
                    ui_view.range = {};
                    ui_view.range.extent.levels = ui->info.resources.levels;
                    auto& view = ui->FindView(ui_view, false);
                    image.usage.texture = 1u;
                    dc.image_infos.emplace_back(VK_NULL_HANDLE, *view.image_view, ui->backing->state.layout);
                    set_ok = false;
                    ui_replaced = true;
                    continue;
                }
                // bbport: the replacement is still being made (UiReplacement): the game's own art
                // now, and no remembered set, so a later bind takes the replacement.
                if (texture_cache.UiReplacementPending(image.ui_key)) {
                    set_ok = false;
                }
            }
            // bbport (r11_native_compute): the destination of a whole-image store of cs a040875f
            // (R11Store), bound once, drops its proxy contents without the resolve the store
            // would overwrite; the Transit below then finds nothing dirty to resolve.
            if (r11_store.armed && is_storage && !on_helper && image.scene_proxy &&
                !binding.force_general && !binding.is_target &&
                stage.sw_stage == Shader::SwStage::Compute && stage.pgm_hash == R11CopyRectHash) {
                ++r11_stats.proxied;
                r11_stats.last_w = image.info.size.width;
                r11_stats.last_h = image.info.size.height;
                const bool whole =
                    image.info.resources == VideoCore::SubresourceExtent{1, 1} &&
                    image.info.size.depth <= 1 && !image.info.props.is_depth &&
                    desc.view_info.range.base.level == 0 && desc.view_info.range.base.layer == 0 &&
                    image.info.size.width <= r11_store.width &&
                    image.info.size.height <= r11_store.height;
                if (!whole) {
                    ++r11_stats.not_whole;
                } else if (!scene_targets->NativeStale(image)) {
                    ++r11_stats.clean;
                } else {
                    ++r11_stats.whole;
                    if (!BbToggle::Experiment(137438953472ull)) {
                        scene_targets->NativeOverwritten(image);
                        ++r11_stats.dropped;
                    }
                }
            }
            // The image is either bound as storage in a separate descriptor or bound as render
            // target in feedback loop. Depth images are excluded because they can't be bound as
            // storage and feedback loop doesn't make sense for them
            if ((binding.force_general || binding.is_target) && !image.info.props.is_depth) {
                if (instance.IsAttachmentFeedbackLoopLayoutSupported() && image.binding.is_target) {
                    barrier |= runtime.Transit(
                        &image, vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT,
                        vk::PipelineStageFlagBits2::eAllGraphics, vk::AccessFlagBits2::eShaderRead);
                } else {
                    barrier |= runtime.Transit(
                        &image, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eAllCommands,
                        vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
                }
            } else {
                if (is_storage) {
                    barrier |= runtime.Transit(
                        &image, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eAllCommands,
                        vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
                        desc.view_info.range);
                } else {
                    const auto new_layout = image.info.props.is_depth
                                                ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                                : vk::ImageLayout::eShaderReadOnlyOptimal;
                    barrier |= runtime.Transit(
                        &image, new_layout, vk::PipelineStageFlagBits2::eAllCommands,
                        vk::AccessFlagBits2::eShaderRead, desc.view_info.range);
                }
            }
            image.usage.storage |= is_storage;
            image.usage.texture |= !is_storage;
            ui_other |= !is_storage;
            if (FrameCapture::Active()) {
                FrameCapture::Sampled(image.info, is_storage);
            }

            vk::ImageView view = *image_view.image_view;
            vk::ImageLayout layout = image.backing->state.layout;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            const bool redirected = upscaler->Enabled() &&
                upscaler->RedirectSampled(image_id, image_view.info, view, layout);
            if (auto* selected = dc.bottle_display_operands;
                selected && redirected && binding_index == 0 && !is_storage &&
                stage.sw_stage == Shader::SwStage::Fragment && stage.pgm_hash == BottleDisplay182::Fragment &&
                layout == vk::ImageLayout::eGeneral) selected->ui_redirect = view;
#else
            if (upscaler->Enabled()) {
                // bbport: the display pass reads the upscaled frame (scaled presets).
                upscaler->RedirectSampled(image_id, image_view.info, view, layout);
            }
#endif
            dc.image_infos.emplace_back(VK_NULL_HANDLE, view, layout);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
            if (auto* selected = dc.bottle_display_operands;
                selected && stage.sw_stage == Shader::SwStage::Fragment && stage.pgm_hash == BottleDisplay182::Fragment &&
                binding_index == 1 && !is_storage && view == *image_view.image_view &&
                image_view.info.type == AmdGpu::ImageType::Color1DArray && !binding.force_general &&
                !binding.is_target && image.backing->image.allocator && image.backing->image.allocation) {
                const auto& physical = image.backing->image;
                const auto range = image_view.info.range;
                VmaAllocationInfo memory{};
                vmaGetAllocationInfo(physical.allocator, physical.allocation, &memory);
                selected->lut = {
                    .image = image.GetImage(), .view = view, .layout = layout, .format = image_view.info.format,
                    .uid = image.image_uid, .allocator = reinterpret_cast<u64>(physical.allocator),
                    .allocation = reinterpret_cast<u64>(physical.allocation),
                    .memory = std::bit_cast<u64>(memory.deviceMemory), .offset = memory.offset, .bytes = memory.size,
                    .write_hint = image.write_seq,
                    .id = image_id.index, .type = u32(physical.image_ci.imageType),
                    .width = physical.image_ci.extent.width, .levels = physical.image_ci.mipLevels,
                    .layers = physical.image_ci.arrayLayers, .base_level = range.base.level,
                    .base_layer = range.base.layer, .view_levels = range.extent.levels, .view_layers = range.extent.layers,
                    .known = true};
            }
#endif
            if (window_receiver && !on_helper && binding_index == 0 && !is_storage &&
                stage.sw_stage == Shader::SwStage::Fragment && stage.pgm_hash == DirectionalFragmentShaderHash &&
                view == *image_view.image_view) {
                window_receiver->Bind(image_id, image.image_uid, image_view.info);
            }
            if (set_ok && binding_index < resolved.size()) {
                resolved[binding_index] = {image_id, resolved[binding_index].found,
                                           *image_view.image_view, image.backing,
                                           desc.view_info.range};
                set_ok = !is_storage && !binding.force_general && !binding.is_target;
            }
        }
    }
    if (time_slow) {
        pass2_stamps.push_back(__rdtsc());
        ReportSlowTextureBind(stage, full_start, {pass1_stamps.data(), pass1_stamps.size()},
                              {pass2_stamps.data(), pass2_stamps.size()});
    }
    if (set_ok && dc.image_bindings.size() == stage.images.size()) {
        // Remember the set: the same T#s resolve the same way while no image is (un)registered,
        // and with exact matches while their images stay registered (RevalidateTextureSet).
        set_slot->generation = texture_cache.RegistryGeneration();
        set_slot->scene_generation = scene_targets->Generation();
        set_slot->count = static_cast<u32>(stage.images.size());
        set_slot->exact = set_exact;
        std::copy_n(resolved.begin(), set_slot->count, set_slot->entries.begin());
        std::copy_n(resolved_uids.begin(), set_slot->count, set_slot->found_uids.begin());
    } else if (set_slot) {
        set_slot->key = 0;
    }

    u32 image_info_idx = first_image_idx;
    u32 image_binding_idx = 0;
    for (u32 array_size : image_descriptor_array_sizes) {
        const auto& desc = *dc.image_bindings[image_binding_idx].second;
        const bool is_storage = desc.type == VideoCore::TextureCache::BindingType::Storage;
        auto& set_write = dc.set_writes[write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = array_size;
        set_write.descriptorType =
            is_storage ? vk::DescriptorType::eStorageImage : vk::DescriptorType::eSampledImage;
        set_write.pImageInfo = &dc.image_infos[image_info_idx];

        image_info_idx += array_size;
        image_binding_idx += array_size;
        binding.unified += array_size;
    }

    // The samplers aren't tied to the images here: with another image bound, its sampler may be
    // the one changed, so the replacement is then sampled as the game's own textures are.
    BindSamplers(stage, prepared, binding, write_index, ui_replaced && !ui_other);
}

// bbport: the PS4 build samples most scene textures with little or no anisotropic filtering.
// Behind the temporal upscaler the output shows the detail of the output's mip level, and
// surfaces seen at a grazing angle (stairs, floors, walls along the view) stay blurred.
// Mipmapped linear samplers of graphics draws get BB_ANISO (16; 0 = the game's) times.
void Rasterizer::ForceAnisotropy(AmdGpu::Sampler& sharp, bool is_depth) const {
    auto& dc = Dc();
    static const int forced = [] {
        const char* value = std::getenv("BB_ANISO");
        return value ? std::atoi(value) : 16;
    }();
    if (!is_depth && !dc.pipeline_is_compute) {
        // The game's filters, once per kind: min filter, mip filter, ratio.
        static std::atomic<u64> seen{0};
        const u32 kind = u32(sharp.xy_min_filter.Value()) * 3 * 5 + u32(sharp.mip_filter.Value()) * 5 +
                         u32(sharp.max_aniso.Value());
        // A plain load first: the locked read-modify-write ran for every sampler of every draw.
        if (kind < 64 && !(seen.load(std::memory_order_relaxed) & (1ull << kind)) &&
            !(seen.fetch_or(1ull << kind) & (1ull << kind))) {
            std::printf("Sampler: game uses min filter %u, mip filter %u, anisotropy %.0fx\n",
                        u32(sharp.xy_min_filter.Value()), u32(sharp.mip_filter.Value()),
                        sharp.MaxAniso());
        }
    }
    if (forced <= 1 || is_depth || dc.pipeline_is_compute || BbToggle::Disabled(BbToggle::ForcedAniso) ||
        sharp.mip_filter == AmdGpu::MipFilter::None ||
        (sharp.xy_min_filter != AmdGpu::Filter::Bilinear &&
         sharp.xy_min_filter != AmdGpu::Filter::AnisoLinear)) {
        return;
    }
    const auto ratio = forced >= 16 ? AmdGpu::AnisoRatio::Sixteen
        : forced >= 8 ? AmdGpu::AnisoRatio::Eight
        : forced >= 4 ? AmdGpu::AnisoRatio::Four : AmdGpu::AnisoRatio::Two;
    if (AmdGpu::IsAnisoFilter(sharp.xy_min_filter) && sharp.MaxAniso() >= forced) {
        return;
    }
    sharp.xy_min_filter.Assign(AmdGpu::Filter::AnisoLinear);
    if (sharp.xy_mag_filter == AmdGpu::Filter::Bilinear) {
        sharp.xy_mag_filter.Assign(AmdGpu::Filter::AnisoLinear);
    }
    sharp.max_aniso.Assign(ratio);
}

// Scaleform samples its sheets and glyphs with point filtering and no mip filter, made for a 1080p
// stage drawn texel for texel. With 4K menus the art it samples is four times larger and drawn at a
// quarter of its size (and Sharp UI scales the stage to the output): point sampling skipped most of
// its texels and the menus came out blocky. Draws of a replacement filter linearly, between mips
// too. While 4K menus are loaded, the menu draws of the game's own textures (the HUD's sheet is
// never replaced: key prompts are drawn into it) filter linearly as well, as Sharp UI scales them
// up to the output, except additive ones: their sheets' transparent gaps carry colour, and
// filtering read it past the sprite's edge (a faint box around the HUD bars' glows).
// BB_UI_SMOOTH=0 keeps the game's.
float Rasterizer::SmoothUiSampler(AmdGpu::Sampler& sharp, bool is_depth, bool ui_replaced) const {
    auto& dc = Dc();
    static const bool enabled = [] {
        const char* env = std::getenv("BB_UI_SMOOTH");
        return !(env && env[0] == '0');
    }();
    // The replacements' mip bias. A menu draws them at a fraction of their size, between two
    // levels, and the linear mip filter blends in the smaller one, which has hardly more detail
    // than the game's own texture; biased, the sharper level dominates.
    static const float bias = [] {
        const char* env = std::getenv("BB_UI_LOD_BIAS");
        return env && *env ? std::clamp(std::strtof(env, nullptr), -2.0f, 0.0f) : -0.5f;
    }();
    const bool own_texture = dc.ui_movie_draw && !dc.ui_additive && VideoCore::TextureCache::UiReplacementsLoaded();
    if (is_depth || !enabled || !(ui_replaced || own_texture)) {
        return 0.0f;
    }
    const auto smooth = [](AmdGpu::Filter filter) {
        return filter == AmdGpu::Filter::Point       ? AmdGpu::Filter::Bilinear
               : filter == AmdGpu::Filter::AnisoPoint ? AmdGpu::Filter::AnisoLinear
                                                      : filter;
    };
    sharp.xy_min_filter.Assign(smooth(sharp.xy_min_filter));
    sharp.xy_mag_filter.Assign(smooth(sharp.xy_mag_filter));
    if (ui_replaced) {
        // The game's LOD range was set for a single level; the replacement's view bounds the chain.
        sharp.mip_filter.Assign(AmdGpu::MipFilter::Linear);
        sharp.min_lod.Assign(0);
        sharp.max_lod.Assign(0xfff);
        return bias;
    }
    return 0.0f;
}

vk::Sampler Rasterizer::CachedSampler(const AmdGpu::Sampler& sharp, bool is_depth,
                                      float lod_bias) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_SAMPLER_MEMO");
        return !(env && env[0] == '0');
    }();
    if (!enabled) {
        return texture_cache.GetSampler(sharp, Regs().ta_bc_base, is_depth, lod_bias);
    }
    static_assert(sizeof(AmdGpu::Sampler) == sizeof(SamplerMemoEntry::sharp));
    std::array<u64, 2> words;
    std::memcpy(words.data(), &sharp, sizeof(words));
    const u64 variant = u64(is_depth) << 32 | std::bit_cast<u32>(lod_bias);
    u64 hash = (words[0] ^ std::rotl(words[1], 29) ^ variant) * 0x9E3779B97F4A7C15ull;
    hash ^= hash >> 32;
    auto& entry = sampler_memo[hash % sampler_memo.size()];
    // Read here, not after GetSampler: only the collector changes them, never while this runs.
    const u64 generation = texture_cache.SamplerGeneration();
    const u64 tick = texture_cache.GcTick();
    if (entry.generation == generation && entry.sharp == words && entry.variant == variant) {
        if (entry.touched_tick != tick) {
            texture_cache.TouchSampler(entry.lru_id);
            entry.touched_tick = tick;
        }
        ++sampler_memo_hits;
        return entry.handle;
    }
    ++sampler_memo_misses;
    size_t lru_id = 0;
    const vk::Sampler handle =
        texture_cache.GetSampler(sharp, Regs().ta_bc_base, is_depth, lod_bias, &lru_id);
    entry = {words, variant, handle, lru_id, generation, tick};
    return handle;
}

// bbport: a pass at the native size (graphics after the upscaler has run, compute) that reads a
// reduced scene proxy through a point-filtered sampler upscales it nearest-neighbour: 17 such
// post-processing passes made effects and the moon's edge blocky at every reduced preset. The
// stage reads the native images instead, resolved from the proxies with linear filtering
// (SceneTargets::Copy). Bilinear samplers keep reading the proxy (the same upscale, no resolve).
// The sampler that reads each image is not known here: any point sampler counts.
// BB_PROXY_POINT_NATIVE=0 (or experiment bit 0): proxies are read regardless, as before.
bool Rasterizer::PointReadsNative(const Shader::Info& stage, const PreparedStage* prepared) const {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_PROXY_POINT_NATIVE");
        return !(env && env[0] == '0');
    }();
    // Experiment bit 0 of BB_TOGGLE_FILE: proxies read regardless (A/B while the game runs).
    if (!enabled || BbToggle::Experiment(1) ||
        (stage.sw_stage != Shader::SwStage::Compute && upscaler->RasterScaling())) {
        return false;
    }
    for (u32 i = 0; i < stage.samplers.size(); ++i) {
        // A local set (BindTextures, unprepared stage) has image sharps only.
        const auto sharp = prepared && prepared->sampler_sharps ? prepared->sampler_sharps[i]
                                                                : stage.samplers[i].GetSharp(stage);
        if (sharp.xy_mag_filter == AmdGpu::Filter::Point ||
            sharp.xy_mag_filter == AmdGpu::Filter::AnisoPoint) {
            return true;
        }
    }
    return false;
}

void Rasterizer::BindSamplers(const Shader::Info& stage, const PreparedStage* prepared,
                              Shader::Backend::Bindings& binding, u32& write_index,
                              bool ui_replaced) {
    auto& dc = Dc();
    BB_SECTION(Samplers);
    auto* ivy = stage.sw_stage == Shader::SwStage::Fragment &&
                        stage.pgm_hash == IvyMaterialProbe::Fragment ? dc.ivy_material : nullptr;
    if (ivy) ivy->samplers = u32(stage.samplers.size());
    for (u32 sampler_index = 0; sampler_index < stage.samplers.size(); ++sampler_index) {
        const auto& sampler = stage.samplers[sampler_index];
        auto ssharp =
            prepared ? prepared->sampler_sharps[sampler_index] : sampler.GetSharp(stage);
        auto* witness = ivy && sampler_index < ivy->sampler.size() ? &ivy->sampler[sampler_index] : nullptr;
        if (witness) witness->raw = std::bit_cast<std::array<u32, 4>>(ssharp);
        ForceAnisotropy(ssharp, sampler.is_depth);
        const float ui_bias = SmoothUiSampler(ssharp, sampler.is_depth, ui_replaced);
        const auto vk_sampler = CachedSampler(ssharp, sampler.is_depth,
                                              sampler.is_depth ? 0.0f : dc.sampler_lod_bias + ui_bias);
        dc.image_infos.emplace_back(vk_sampler, VK_NULL_HANDLE, vk::ImageLayout::eGeneral);
        auto& set_write = dc.set_writes[write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified++;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = 1;
        set_write.descriptorType = vk::DescriptorType::eSampler;
        set_write.pImageInfo = &dc.image_infos.back();
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (auto* selected = dc.bottle_display_operands;
            selected && stage.sw_stage == Shader::SwStage::Fragment && stage.pgm_hash == BottleDisplay182::Fragment &&
            sampler_index == 0) {
            selected->sampler = {vk_sampler, std::bit_cast<std::array<u32, 4>>(ssharp), set_write.dstBinding,
                sampler.is_depth ? 0.0f : dc.sampler_lod_bias + ui_bias, true};
        }
#endif
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (auto* post = dc.shared_post; post && stage.sw_stage == Shader::SwStage::Fragment) {
            if (post->sampler_count == post->samplers.size()) ++post->omitted_samplers;
            else post->samplers[post->sampler_count++] = {std::bit_cast<std::array<u32, 4>>(ssharp),
                vk_sampler, set_write.dstBinding, sampler.is_depth ? 0.0f : dc.sampler_lod_bias + ui_bias};
        }
#endif
        if (witness) {
            witness->effective = std::bit_cast<std::array<u32, 4>>(ssharp);
            witness->handle = std::bit_cast<u64>(vk_sampler);
            witness->binding = set_write.dstBinding;
            witness->lod_bias = sampler.is_depth ? 0.0f : dc.sampler_lod_bias + ui_bias;
            witness->depth = sampler.is_depth;
            witness->seen = true;
        }
    }
}

Rasterizer::BeginSignature Rasterizer::MakeBeginSignature(const GraphicsPipeline* pipeline) const {
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = Regs();
    BeginSignature sig;
    const u32 num_color = std::bit_width(key.mrt_mask);
    for (u32 cb = 0; cb < num_color && cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        sig.ids[cb] = cb_descs[cb].first;
        if (cb_descs[cb].first) {
            sig.views[cb] = cb_descs[cb].second.view_info;
        }
        sig.color_samples[cb] = key.color_samples[cb];
    }
    sig.ids[AmdGpu::NUM_COLOR_BUFFERS] = db_desc.first;
    if (db_desc.first) {
        sig.views[AmdGpu::NUM_COLOR_BUFFERS] = db_desc.second.view_info;
    }
    sig.mrt_mask = key.mrt_mask;
    sig.num_samples = key.num_samples;
    sig.motion = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
    sig.scene_started = scene_started;
    sig.raster_scaling = upscaler->RasterScaling();
    sig.upscaler_state = upscaler->RedirectState();
    sig.generation = texture_cache.RegistryGeneration();
    std::memcpy(&sig.depth_control, &regs.depth_control, sizeof(u32));
    sig.depth_valid = regs.depth_buffer.DepthValid();
    sig.stencil_valid = regs.depth_buffer.StencilValid();
    return sig;
}

bool Rasterizer::RevalidateTextureSet(TextureSet& set, u64 generation) {
    // Images were (un)registered since the set was remembered. Its lookups were exact matches:
    // FindImage would find the same images again while each is still registered (uids: slots
    // are reused) and has no depth redirect (TextureCache::IsExactMatch). Views and backings
    // belong to those images, so the per-image checks of a hit stay as they are.
    if (!set.exact || set.generation == ~0ull || !MemoRevalidation()) {
        return false;
    }
    for (u32 i = 0; i < set.count; ++i) {
        const auto& entry = set.entries[i];
        if (!entry.id) {
            continue; // a null T#
        }
        if (entry.found != entry.id ||
            !texture_cache.IsRegisteredImage(entry.found, set.found_uids[i]) ||
            texture_cache.GetAssociatedDepth(texture_cache.GetImage(entry.found))) {
            set.exact = false;
            return false;
        }
    }
    set.generation = generation;
    ++texture_set_revalidated;
    return true;
}

bool Rasterizer::BindTexturesFromSet(const Shader::Info& stage, const PreparedStage* prepared,
                                     u32 first_image_idx, bool& barrier, TextureSet*& slot) {
    auto& dc = Dc();
    BB_SECTION(TexSet);
    const u32 count = static_cast<u32>(stage.images.size());
    if (!prepared || count == 0 || count > TextureSet::MaxImages ||
        BbToggle::Disabled(BbToggle::TextureSetMemo) || FrameCapture::Active()) {
        ++texture_set_skip[count == 0 ? 1 : !prepared ? 0 : count > TextureSet::MaxImages ? 2 : 4];
        return false;
    }
    for (const auto& image : stage.images) {
        if (image.is_written || image.mip_fallback_mode != Shader::MipStorageFallbackMode::None) {
            ++texture_set_skip[3];
            return false;
        }
    }
    // Point-sampling stages in native passes read native images (PointReadsNative): sets of
    // their own, whose native entries stand even for images with a current proxy.
    const bool point_native = scene_targets->Reduced() && PointReadsNative(stage, prepared);
    u64 key = XXH3_64bits_withSeed(prepared->image_hashes, count * sizeof(u64),
                                   reinterpret_cast<u64>(&stage) ^ (point_native ? 2 : 0));
    key |= 1; // 0 marks an empty slot
    auto& set = texture_sets[key % texture_sets.size()];
    slot = &set;
    const u64 generation = texture_cache.RegistryGeneration();
    const bool same_set = set.key == key && set.stage == &stage && set.count == count &&
                          set.scene_generation == scene_targets->Generation() &&
                          std::equal(set.hashes.begin(), set.hashes.begin() + count,
                                     prepared->image_hashes);
    const bool match =
        same_set && (set.generation == generation || RevalidateTextureSet(set, generation));
    if (!match) {
        const bool generation_miss = set.key == key && set.stage == &stage && set.count == count &&
                                     set.generation != generation;
        if (generation_miss && VideoCore::ImageOverlapLogging()) {
            static std::atomic<u64> generation_diag_count{0};
            const u64 diag_index =
                generation_diag_count.fetch_add(1, std::memory_order_relaxed);
            if (diag_index < 256 || (diag_index % 1024) == 0) {
                std::printf(
                    "TextureDiag set-generation[%llu]: key=0x%llx old_gen=%llu new_gen=%llu "
                    "old_scene_gen=%llu new_scene_gen=%llu count=%u\n",
                    static_cast<unsigned long long>(diag_index),
                    static_cast<unsigned long long>(key),
                    static_cast<unsigned long long>(set.generation),
                    static_cast<unsigned long long>(generation),
                    static_cast<unsigned long long>(set.scene_generation),
                    static_cast<unsigned long long>(scene_targets->Generation()), set.count);
                for (u32 i = 0; i < set.count; ++i) {
                    const auto& entry = set.entries[i];
                    std::printf(
                        "  TextureDiag entry[%u]: image=%u backing=%p view=0x%llx "
                        "mip=%u+%u layer=%u+%u proxy=%u\n",
                        i, entry.id.index, entry.backing,
                        static_cast<unsigned long long>(
                            reinterpret_cast<uintptr_t>(static_cast<VkImageView>(entry.view))),
                        entry.range.base.level, entry.range.extent.levels,
                        entry.range.base.layer, entry.range.extent.layers,
                        entry.proxy ? 1u : 0u);
                }
                std::fflush(stdout);
            }
        }
        ++texture_set_why[set.key != key ? 0 : set.generation != generation ? 1 : 3];
        ++texture_set_misses;
        set.key = key;
        set.stage = &stage;
        set.count = 0;
        set.generation = ~0ull;
        set.exact = false;
        std::copy_n(prepared->image_hashes, count, set.hashes.begin());
        return false;
    }
    // Every image still has the backing its view belongs to and needs no refresh.
    BbSections::Scope check_scope{BbSections::TexSetCheck};
    for (u32 i = 0; i < count; ++i) {
        const auto& entry = set.entries[i];
        if (!entry.id) {
            continue;
        }
        const auto& image = texture_cache.GetImage(entry.id);
        // Proxy entries need a current proxy; native entries of a proxied image go through
        // BindTextures, which may sample the proxy instead.
        const bool proxies_on = !BbToggle::Disabled(BbToggle::SampleSceneProxies);
        if (image.backing != entry.backing || image.binding.needs_rebind ||
            image.binding.is_target || !texture_cache.IsUpToDate(entry.id) ||
            (entry.proxy ? !proxies_on ||
                               !scene_targets->ProxyCurrent(image, entry.range.base.level,
                                                            entry.range.extent.levels)
                         : image.scene_proxy && proxies_on && !point_native) ||
            (upscaler->Enabled() && upscaler->RedirectsSampled(entry.id))) {
            ++texture_set_why[2];
            ++texture_set_misses;
            set.generation = ~0ull;
            set.exact = false;
            return false;
        }
    }
    check_scope.End();
    ++texture_set_hits;
    // bbport: a hit keeps proxied images native only for point-sampler stages (point_native,
    // else the set is refused above): the resolves of its Transits are theirs (SceneUse).
    const SceneUseScope set_use{
        point_native ? (stage.sw_stage == Shader::SwStage::Compute
                            ? "dispatch textures (texture set), point sampler in the stage (PointReadsNative), cs"
                            : "draw textures (texture set), point sampler in the stage (PointReadsNative), stage")
                     : SceneUseScope::current.what,
        SceneUseScope::current.hash};
    slot = nullptr;
    BB_SECTION(TexSetApply);
    for (u32 i = 0; i < count; ++i) {
        const auto& entry = set.entries[i];
        if (!entry.id) {
            dc.image_infos.emplace_back(VK_NULL_HANDLE, VK_NULL_HANDLE, vk::ImageLayout::eGeneral);
            continue;
        }
        texture_cache.MarkFound(entry.id);
        auto& image = texture_cache.GetImage(entry.id);
        image.binding.is_bound = 1u;
        dc.bound_images.emplace_back(entry.id);
        image.usage.texture = 1u;
        if (entry.proxy) {
            dc.image_infos.emplace_back(VK_NULL_HANDLE, entry.view,
                                     scene_targets->PrepareSample(image, entry.range.base.level));
            ++proxy_samples;
            continue;
        }
        const auto new_layout = image.info.props.is_depth
                                    ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                    : vk::ImageLayout::eShaderReadOnlyOptimal;
        barrier |= runtime.Transit(&image, new_layout, vk::PipelineStageFlagBits2::eAllCommands,
                                   vk::AccessFlagBits2::eShaderRead, entry.range);
        dc.image_infos.emplace_back(VK_NULL_HANDLE, entry.view, image.backing->state.layout);
        if (window_receiver && i == 0 && stage.sw_stage == Shader::SwStage::Fragment &&
            stage.pgm_hash == DirectionalFragmentShaderHash) {
            const auto& resource = stage.images[0];
            const VideoCore::ImageViewInfo view(resource.GetSharp(stage), resource);
            if (view.range == entry.range) {
                window_receiver->Bind(entry.id, image.image_uid, view);
            }
        }
    }
    // bbport (r62_leaf-stage3): what the set holds for each image (FindImage's image and its
    // uid), for a pixel shader's card layer (NoteCardLayer): a set hit leaves the binding memo
    // untouched, so its entries are the only record of this draw's images.
    if (card_bound_on && stage.sw_stage == Shader::SwStage::Fragment) {
        dc.card_bound.stage = &stage;
        dc.card_bound.count = count;
        for (u32 i = 0; i < count; ++i) {
            dc.card_bound.ids[i] = set.entries[i].found;
            dc.card_bound.uids[i] = set.found_uids[i];
        }
    }
    (void)first_image_idx;
    return true;
}

void Rasterizer::RememberBeginTargets() {
    const auto& ids = begin_memo.signature.ids;
    for (u32 i = 0; i < ids.size(); ++i) {
        begin_memo.uids[i] = ids[i] ? texture_cache.ImageUid(ids[i]) : 0;
        begin_memo.backings[i] = ids[i] ? texture_cache.GetImage(ids[i]).backing : nullptr;
    }
    begin_memo.scene_generation = scene_targets->Generation();
}

bool Rasterizer::RevalidateBeginMemo(const BeginSignature& signature) {
    // Images were (un)registered since the memo: it holds when nothing else changed and every
    // target is still the same registered image with the same backing (its views, layouts).
    if (signature.generation == begin_memo.signature.generation || !MemoRevalidation() ||
        begin_memo.scene_generation != scene_targets->Generation()) {
        return false;
    }
    BeginSignature same = signature;
    same.generation = begin_memo.signature.generation;
    if (!(same == begin_memo.signature)) {
        return false;
    }
    for (u32 i = 0; i < signature.ids.size(); ++i) {
        const auto id = signature.ids[i];
        if (id && (!texture_cache.IsRegisteredImage(id, begin_memo.uids[i]) ||
                   texture_cache.GetImage(id).backing != begin_memo.backings[i])) {
            return false;
        }
    }
    begin_memo.signature.generation = signature.generation;
    ++begin_memo_revalidated;
    return true;
}

// bbport: a draw into the upscaler's output-size images (BeginRenderingFull's redirected passes):
// its scale, offset and full scissor from this draw's own viewport. Made for every draw, also
// those the render state memo continues a pass with: a UI pass mixes viewports, and the scale of
// the pass's first draw was kept for all of them.
void Rasterizer::UpdateUiTransform(const GraphicsPipeline* pipeline) {
    target_scale = {1.0f, 1.0f};
    target_offset = {0, 0};
    ui_full_scissor = {};
    if (!ui_pass.active) {
        return;
    }
    const auto& regs = Regs();
    const auto [gw, gh] = ui_pass.guest;
    const auto [ow, oh] = ui_pass.output;
    // The UI movie viewport is now 1920x1080 even when the scene is 960x540.
    // A native viewport (or native window-space UI vertices) must not be doubled
    // again. The final display copy still uses the guest render-size coordinates.
    const auto& viewport = regs.viewports[0];
    const float vw = viewport.xscale * 2, vh = viewport.yscale * 2;
    const bool window_space = regs.IsClipDisabled() && !regs.viewport_control.xscale_enable &&
                              !regs.viewport_control.yscale_enable;
    const bool sharp_ui = UiComposition::StageScale(UiComposition::UiSize()) > 1.0f;
    const bool movie_viewport = UiComposition::NativeViewport(vw, vh);
    // Sharp UI: a viewport of its own inside the UI viewport (an item icon's rectangle, which the
    // game places in the movie viewport's pixels) is in those pixels too. Only the viewport over
    // the whole guest target is in the target's (render-size) pixels; scaled by the output over
    // the render size, the icons came out up to three times their size, spread from the top left.
    const bool inner_viewport =
        sharp_ui && !window_space && UiComposition::InnerViewport(vw, vh, gw, gh);
    const bool native_coordinates =
        ui_pass.native_ui && (movie_viewport || window_space || inner_viewport);
    // The stage's own 1920x1080 viewport is centred; the widened one (UiComposition::UiSize,
    // Widescreen on another screen shape) fills the image, its sides included. Vertices in
    // window space are in the UI viewport's pixels whatever the viewport registers still
    // hold (with Sharp UI the item icons were drawn twice their size from the top left).
    const bool stage_viewport = !(window_space && sharp_ui) &&
                                UiComposition::ViewportIs(vw, vh, {1920.0f, 1080.0f});
    const auto ui = stage_viewport ? std::array<float, 2>{1920.0f, 1080.0f} : UiComposition::UiSize();
    target_scale = UiComposition::Scale(gw, gh, ow, oh, native_coordinates, ui);
    // A 16:9 viewport of the output's size (Sharp UI) is stretched like the 1920x1080 one.
    if (native_coordinates && (BbSettings::Get().widescreen || ui[0] * 1080.0f != ui[1] * 1920.0f)) {
        const auto fit = UiComposition::Fit(ow, oh, ui);
        target_scale = fit.scale;
        target_offset = fit.offset;
        // A scissor over the whole guest target or viewport is the whole image: the
        // widened viewport can be wider than the scene's target it was set from.
        if (!stage_viewport && (ui[0] != 1920.0f || ui[1] != 1080.0f)) {
            ui_full_scissor = {std::min(u32(ui[0]), gw), std::min(u32(ui[1]), gh)};
        }
    }
    // BB_UI_VIEWPORT_LOG=1: each kind of draw of these passes once (vertex shader, viewport, the
    // pixels its vertices are taken in), to see which path a screen's pictures take.
    static const bool log = [] {
        const char* value = std::getenv("BB_UI_VIEWPORT_LOG");
        return value && value[0] == '1';
    }();
    if (log) {
        static std::unordered_set<u64> seen;
        const u32 space = !ui_pass.native_ui ? 0
                          : window_space     ? 1
                          : stage_viewport   ? 2
                          : movie_viewport   ? 3
                          : inner_viewport   ? 4
                                             : 5;
        const u64 vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
        const u64 key = (vs * 0x9E3779B97F4A7C15ull) ^ (u64(std::lround(std::abs(vw))) << 36) ^
                        (u64(std::lround(std::abs(vh))) << 16) ^ space;
        if (seen.size() < 512 && seen.insert(key).second) {
            static constexpr const char* names[] = {
                "display pass",         "window space, UI viewport pixels",
                "stage 1920x1080",      "UI movie viewport",
                "own rectangle, UI viewport pixels", "guest target pixels"};
            std::printf("UI pass: vs %08llx viewport %.0fx%.0f at %.0f,%.0f%s: %s, scale %.3fx%.3f "
                        "offset %.0f,%.0f (guest %ux%u, image %ux%u)\n",
                        static_cast<unsigned long long>(vs), vw, vh,
                        viewport.xoffset - viewport.xscale, viewport.yoffset - viewport.yscale,
                        regs.IsClipDisabled() ? ", clip off" : "", names[space], target_scale[0],
                        target_scale[1], target_offset[0], target_offset[1], gw, gh, ow, oh);
        }
    }
}

RenderState Rasterizer::BeginRendering(const GraphicsPipeline* pipeline) {
    auto& dc = Dc();
    BB_SECTION(BeginRendering);
    // bbport: RenderStateMemo (see BeginMemo).
    const bool memo_on = !BbToggle::Disabled(BbToggle::RenderStateMemo) && !FrameCapture::Active();
    if (BbStats::enabled && ((begin_memo_hits + begin_memo_misses) & 0x3FFFF) == 0x3FFFF) {
        if (range_binds) {
            std::printf("Vertex and index binds by range: %llu looked up, %llu reused (%llu checked, "
                        "%llu differ)\n",
                        static_cast<unsigned long long>(range_binds),
                        static_cast<unsigned long long>(range_hits),
                        static_cast<unsigned long long>(range_checked),
                        static_cast<unsigned long long>(range_differ));
        }
        std::printf("Render state memo: %llu hits (%llu revalidated), %llu misses; texture sets: "
                    "%llu hits (%llu revalidated), %llu misses; lookups revalidated: textures "
                    "%llu, targets %llu\n",
                    static_cast<unsigned long long>(begin_memo_hits),
                    static_cast<unsigned long long>(begin_memo_revalidated),
                    static_cast<unsigned long long>(begin_memo_misses),
                    static_cast<unsigned long long>(texture_set_hits),
                    static_cast<unsigned long long>(texture_set_revalidated),
                    static_cast<unsigned long long>(texture_set_misses),
                    static_cast<unsigned long long>(texture_lookups_revalidated),
                    static_cast<unsigned long long>(target_lookups_revalidated));
        std::printf("  texture set misses: other key %llu, generation %llu, image check %llu, "
                    "other %llu\n",
                    (unsigned long long)texture_set_why[0], (unsigned long long)texture_set_why[1],
                    (unsigned long long)texture_set_why[2], (unsigned long long)texture_set_why[3]);
        std::printf("  texture set skips: unprepared %llu, no images %llu, over 16 images %llu, "
                    "storage or mip override %llu, memo off %llu\n",
                    (unsigned long long)texture_set_skip[0], (unsigned long long)texture_set_skip[1],
                    (unsigned long long)texture_set_skip[2], (unsigned long long)texture_set_skip[3],
                    (unsigned long long)texture_set_skip[4]);
        texture_set_skip = {};
        std::printf("  scene proxies sampled directly: %llu bindings\n",
                    static_cast<unsigned long long>(proxy_samples));
        std::printf("  samplers: %llu memo hits, %llu looked up\n",
                    static_cast<unsigned long long>(sampler_memo_hits),
                    static_cast<unsigned long long>(sampler_memo_misses));
        sampler_memo_hits = sampler_memo_misses = 0;
        proxy_samples = 0;
        texture_set_why = {};
        begin_memo_hits = begin_memo_misses = texture_set_hits = texture_set_misses = 0;
        begin_memo_revalidated = texture_set_revalidated = texture_lookups_revalidated = 0;
        target_lookups_revalidated = 0;
    }
    BeginSignature signature;
    if (memo_on) {
        signature = MakeBeginSignature(pipeline);
        const auto& regs = Regs();
        bool rendering = begin_memo.valid && scheduler.IsRenderingWith(begin_memo.state);
        if (!rendering && begin_memo.valid && foliage_mask && gbuffer_draw &&
            pipeline->FoliageVariant()) {
            auto with_mask = begin_memo.state;
            rendering = foliage_mask->ResumeAttachment(mask_receivers.key, with_mask) &&
                        scheduler.IsRenderingWith(with_mask);
        }
        bool usable = rendering &&
                      !regs.depth_render_control.depth_clear_enable &&
                      !regs.depth_render_control.stencil_clear_enable &&
                      (signature == begin_memo.signature || RevalidateBeginMemo(signature));
        for (const auto id : signature.ids) {
            if (usable && id) {
                const auto& image = texture_cache.GetImage(id);
                usable = !image.binding.is_bound && !image.binding.needs_rebind;
            }
        }
        if (usable) {
            ++begin_memo_hits;
            attachment_feedback_loop = false;
            dc.push_data.scene_size = begin_memo.scene_size;
            target_scale = begin_memo.target_scale;
            target_offset=begin_memo.target_offset;
            ui_full_scissor = begin_memo.ui_full_scissor;
            // The same pass, not the same viewport: a UI pass mixes the movie viewport,
            // window-space vertices, the stage's viewport and item icons' own rectangles.
            ui_pass = begin_memo.ui_pass;
            if (ui_pass.active) {
                UpdateUiTransform(pipeline);
            }
            return begin_memo.state;
        }
        ++begin_memo_misses;
    }
    begin_memo.valid = false;
    RenderState state = BeginRenderingFull(pipeline);
    if (memo_on && !attachment_feedback_loop) {
        // (is_clear of the depth attachment shares its bytes with has_depth.)
        bool clears = state.depth_stencil_attachment.depth_clear ||
                      state.depth_stencil_attachment.stencil_clear;
        for (u32 i = 0; i < state.num_color_attachments; ++i) {
            clears |= state.color_attachments[i].is_clear != 0;
        }
        if (!clears) {
            // Recomputed after the full path: it may have started the scene (scene_started).
            begin_memo = {true, MakeBeginSignature(pipeline), state, dc.push_data.scene_size,
                          target_scale,target_offset,ui_full_scissor};
            begin_memo.ui_pass = ui_pass;
            RememberBeginTargets();
        }
    }
    return state;
}

RenderState Rasterizer::BeginRenderingFull(const GraphicsPipeline* pipeline) {
    auto& dc = Dc();
    attachment_feedback_loop = false;
    using VulkanUpscalerTarget = TemporalUpscaler::Target;
    VulkanUpscalerTarget redirect{};
    bool color_redirected = false, depth_redirected = false;
    std::pair<u32, u32> guest_extent{1, 1};
    std::pair<vk::ImageView, vk::ImageLayout> original_color{};
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    if (std::popcount(key.mrt_mask & 0x7f) >= 5 && db_desc.first &&
        scene_targets->EligibleScene(texture_cache.GetImage(db_desc.first))) {
        if (!scene_started && BottleMotion::Run()) {
            BottleMotion::Begin(BottleCaustic::On(),scheduler.GetWorkSemaphore()->Handle(),WorkflowPresent::Now());
        }
        scene_started=true;
    }
    // A proxy attachment cannot represent MSAA or a feedback loop that reads the
    // same image through the guest's native descriptor during this draw. AO stays at its native
    // target size: reduced proxies warp the projection shared by SSAO and both GTAO variants.
    const auto* fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    const bool ao_pass = fragment && fragment->pgm_hash == EffectShaders::SsaoHash;
    // bbport: this pass is the consumer of the resolves and fills of its targets (SceneUse).
    const SceneUseScope pass_use{
        fragment ? "pass ps" : "pass without ps, vs",
        fragment ? fragment->pgm_hash : pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash};
    bool reduced = scene_started && upscaler->RasterScaling() && key.num_samples == 1 && !ao_pass;
    // BB_SCENE_DEBUG=<file>: once the file exists, why the passes of one frame keep the
    // native size (see NoteFrameStart).
    const bool debug_pass = scene_debug_frame && scene_started;
    std::string why;
    if (debug_pass) {
        why = fmt::format("pass vs {:08x} ps {:08x} mrt {:#x} samples {} raster_scaling {}:",
                          pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                          key.mrt_mask ? pipeline->GetStage(Shader::SwStage::Fragment).pgm_hash
                                       : 0,
                          key.mrt_mask, u32(key.num_samples), upscaler->RasterScaling());
    }
    // Only this pass's attachments: slots past the mask's width keep earlier passes' targets,
    // often the G-buffer images the lighting passes sample (bound), which kept those native.
    const u32 num_attachments = BbToggle::Disabled(BbToggle::SceneAttachmentsOnly)
                                    ? u32(cb_descs.size())
                                    : u32(std::bit_width(key.mrt_mask));
    // All attachments of a reduced pass share one proxy size (scene or half resolution).
    std::optional<SceneResolution::Size> pass_size;
    const auto same_size = [&](const VideoCore::Image& image, u32 level) {
        const auto proxy = scene_targets->ProxySize(image, level);
        if (!pass_size) pass_size = proxy;
        return *pass_size == proxy;
    };
    for (u32 cb = 0; cb < num_attachments; ++cb) {
        const auto& [id, desc] = cb_descs[cb];
        if (id) {
            const auto& image = texture_cache.GetImage(id);
            // Mip levels of eligible chains have their own proxies (SceneTargets::Get).
            if (!scene_targets->Eligible(image) || image.binding.is_bound ||
                image.binding.needs_rebind || desc.view_info.range.base.layer ||
                !same_size(image, desc.view_info.range.base.level)) reduced = false;
            if (debug_pass) {
                why += fmt::format(" [{} {}x{} eligible {} bound {} rebind {} level {} layer {}]",
                                   vk::to_string(image.info.pixel_format), image.info.size.width,
                                   image.info.size.height, scene_targets->Eligible(image),
                                   u32(image.binding.is_bound), u32(image.binding.needs_rebind),
                                   desc.view_info.range.base.level,
                                   desc.view_info.range.base.layer);
            }
        }
    }
    if (db_desc.first && (!scene_targets->Eligible(texture_cache.GetImage(db_desc.first)) ||
                          !same_size(texture_cache.GetImage(db_desc.first), 0))) {
        reduced = false;
    }
    if (debug_pass) {
        if (db_desc.first) {
            const auto& depth = texture_cache.GetImage(db_desc.first);
            why += fmt::format(" depth [{} {}x{} eligible {}]",
                               vk::to_string(depth.info.pixel_format), depth.info.size.width,
                               depth.info.size.height, scene_targets->Eligible(depth));
        }
        std::printf("Scene pass: reduced %d %s\n", reduced, why.c_str());
    }
    dc.push_data.scene_size = reduced ? SceneResolution::Pack(scene_targets->Size()) : 0;
    if (BbStats::enabled) {
        BbStats::reduced_draws.fetch_add(reduced, std::memory_order_relaxed);
        BbStats::scene_draws.fetch_add(scene_started, std::memory_order_relaxed);
    }
    RenderState state;
    state.width = instance.GetMaxFramebufferWidth();
    state.height = instance.GetMaxFramebufferHeight();
    state.num_layers = std::numeric_limits<u16>::max();
    state.num_color_attachments = std::bit_width(key.mrt_mask);
    for (auto cb = 0u; cb < state.num_color_attachments; ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        if (!image_id) {
            state.color_attachments[cb] = {};
            continue;
        }
        auto* image = &texture_cache.GetImage(image_id);
        if (image->binding.needs_rebind) {
            last_targets[cb].generation = ~0ULL; // FindImage may rewrite the description
            image_id = dc.bound_images.emplace_back(texture_cache.FindImage(desc));
            image = &texture_cache.GetImage(image_id);
        }
        texture_cache.UpdateImage(image_id);
        runtime.SetBackingSamples(image, key.color_samples[cb]);
        const auto& image_view = texture_cache.FindRenderTarget(image_id, desc);
        const auto slice = image_view.info.range.base.layer;
        const auto mip = image_view.info.range.base.level;

        const auto& col_buf = regs.color_buffers[cb];
        const bool is_clear = texture_cache.IsMetaCleared(col_buf.CmaskAddress(), slice);
        texture_cache.TouchMeta(col_buf.CmaskAddress(), slice, false);

        // bbport: names a clear in the resolve/fill table: a resolve before it is overwritten.
        const SceneUseScope clear_use{is_clear ? "pass, color attachment cleared by the pass, ps"
                                               : SceneUseScope::current.what,
                                      SceneUseScope::current.hash};
        if (reduced) {
            // The native image is resolved lazily when a shader/copy actually reads it.
        } else if (image->binding.is_bound) {
            ASSERT_MSG(!image->binding.force_general,
                       "Having image both as storage and render target is unsupported");
            runtime.FlushBarriers();
            dc.needs_barrier |=
                runtime.Transit(image,
                                instance.IsAttachmentFeedbackLoopLayoutSupported()
                                    ? vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT
                                    : vk::ImageLayout::eGeneral,
                                vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                vk::AccessFlagBits2::eColorAttachmentWrite |
                                    vk::AccessFlagBits2::eColorAttachmentRead);
            attachment_feedback_loop = true;
        } else {
            dc.needs_barrier |= runtime.Transit(image, vk::ImageLayout::eColorAttachmentOptimal,
                                             vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                             vk::AccessFlagBits2::eColorAttachmentWrite |
                                                 vk::AccessFlagBits2::eColorAttachmentRead,
                                             desc.view_info.range);
        }

        state.width = std::min<u32>(state.width, std::max(image->info.size.width >> mip, 1u));
        state.height = std::min<u32>(state.height, std::max(image->info.size.height >> mip, 1u));
        state.num_layers = std::min<u32>(state.num_layers, image_view.info.range.extent.layers);

        const auto clear_value =
            is_clear ? LiverpoolToVK::ColorBufferClearValue(col_buf) : vk::ClearValue{};
        auto& attachment = state.color_attachments[cb];
        attachment.image_view = *image_view.image_view;
        attachment.image_layout = image->backing->state.layout;
        attachment.clear_value = clear_value.color.uint32;
        attachment.is_clear = is_clear;

        if (reduced) {
            // bbport: the pass clears all of the proxy (load op clear; a reduced pass has the
            // proxy's size): a proxy a native write dropped needs no fill first. Not for a
            // display buffer, which the upscaler may redirect (SceneTargets::Attachment).
            const bool cleared =
                is_clear && !FrameCapture::IsDisplayBuffer(image->info.guest_address);
            const auto target = scene_targets->Attachment(image_id, desc.view_info, cleared);
            attachment.image_view = target.view;
            attachment.image_layout = target.layout;
        }
        image->usage.render_target = 1u;
        if (cb == 0 && upscaler->Enabled()) {
            color_redirected = upscaler->RedirectColor(image_id, desc.view_info, redirect);
            if (color_redirected) {
                guest_extent = {image->info.size.width, image->info.size.height};
                original_color = {attachment.image_view, attachment.image_layout};
                attachment.image_view = redirect.view;
                attachment.image_layout = redirect.layout;
            }
        }
    }
    for (u32 cb = state.num_color_attachments; cb < state.color_attachments.size(); ++cb) {
        state.color_attachments[cb] = {};
    }

    if (auto image_id = db_desc.first; image_id) {
        auto& desc = db_desc.second;
        const auto htile_address = regs.depth_htile_data_base.GetAddress();
        const auto& image_view = texture_cache.FindDepthTarget(image_id, desc);
        auto& image = texture_cache.GetImage(image_id);

        const auto slice = image_view.info.range.base.layer;
        const bool is_depth_clear =
            (regs.depth_render_control.depth_clear_enable && regs.depth_control.depth_enable &&
             regs.depth_control.depth_write_enable) ||
            texture_cache.IsMetaCleared(htile_address, slice);
        const bool is_stencil_clear = regs.depth_render_control.stencil_clear_enable;
        texture_cache.TouchMeta(htile_address, slice, false);
        ASSERT(desc.view_info.range.extent.levels == 1 && !image.binding.needs_rebind);

        const bool has_stencil = image.info.props.has_stencil;
        // Stencil writes can be enabled while depth writes are off.
        const bool stencil_write =
            has_stencil && regs.depth_control.stencil_enable && !desc.view_info.is_storage;
        const auto new_layout = desc.view_info.is_storage
                                    ? has_stencil ? vk::ImageLayout::eDepthStencilAttachmentOptimal
                                                  : vk::ImageLayout::eDepthAttachmentOptimal
                                : stencil_write
                                    ? vk::ImageLayout::eDepthReadOnlyStencilAttachmentOptimal
                                : has_stencil ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                              : vk::ImageLayout::eDepthReadOnlyOptimal;
        // bbport: a depth attachment in a read-only layout that neither the pass nor a clear
        // writes leaves the native image as the proxy's resolve made it: the proxy stays current
        // (SceneUse::keep_proxy; experiment bit 1073741824: dropped as before).
        const SceneUseScope depth_use{is_depth_clear || is_stencil_clear
                                          ? "pass depth, cleared by the pass, ps/vs"
                                          : "pass depth, ps/vs",
                                      SceneUseScope::current.hash,
                                      !desc.view_info.is_storage && !stencil_write &&
                                          !is_depth_clear && !is_stencil_clear};
        if (!reduced) dc.needs_barrier |= runtime.Transit(&image, new_layout,
                                         vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                             vk::PipelineStageFlagBits2::eLateFragmentTests,
                                         vk::AccessFlagBits2::eDepthStencilAttachmentWrite |
                                             vk::AccessFlagBits2::eDepthStencilAttachmentRead,
                                         desc.view_info.range);

        state.width = std::min<u32>(state.width, image.info.size.width);
        state.height = std::min<u32>(state.height, image.info.size.height);
        state.num_layers = std::min<u32>(state.num_layers, image_view.info.range.extent.layers);

        auto& attachment = state.depth_stencil_attachment;
        attachment.image_view = *image_view.image_view;
        attachment.image_layout = image.backing->state.layout;
        attachment.clear_value = {};
        attachment.is_clear = 0;

        if (regs.depth_buffer.DepthValid()) {
            attachment.clear_value[0] = is_depth_clear ? std::bit_cast<u32>(regs.depth_clear) : 0u;
            attachment.has_depth = true;
            attachment.depth_clear = is_depth_clear;
        }
        if (regs.depth_buffer.StencilValid()) {
            attachment.clear_value[1] = is_stencil_clear ? regs.stencil_clear : 0u;
            attachment.has_stencil = true;
            attachment.stencil_clear = is_stencil_clear;
        }

        if (reduced) {
            // bbport: as for colour: the pass clears depth and, if the image has it, stencil.
            const bool cleared =
                attachment.has_depth && attachment.depth_clear &&
                (!(image.aspect_mask & vk::ImageAspectFlagBits::eStencil) ||
                 (attachment.has_stencil && attachment.stencil_clear));
            const auto target = scene_targets->Attachment(image_id, desc.view_info, cleared);
            attachment.image_view = target.view;
            attachment.image_layout = target.layout;
        }
        image.usage.depth_target = true;
        if (upscaler->Enabled()) {
            VulkanUpscalerTarget depth_redirect;
            depth_redirected = upscaler->RedirectDepth(image_id, depth_redirect);
            if (depth_redirected) {
                guest_extent = {image.info.size.width, image.info.size.height};
                attachment.image_view = depth_redirect.view;
                attachment.image_layout = depth_redirect.layout;
                redirect = depth_redirect;
            }
        }
    } else {
        state.depth_stencil_attachment = {};
    }

    // bbport: a pass drawn into the upscaler's output-size images (UI, display pass): every
    // attachment must be redirected, viewports and scissors are scaled.
    target_scale = {1.0f, 1.0f};
    target_offset={0,0};
    ui_full_scissor = {};
    ui_pass = {};
    if (color_redirected || depth_redirected) {
        u32 color_targets = 0;
        for (u32 cb = 0; cb < state.num_color_attachments; ++cb) {
            color_targets += state.color_attachments[cb].image_view ? 1 : 0;
        }
        const bool has_depth = bool(db_desc.first);
        if ((color_targets > 0 && !color_redirected) || (has_depth && !depth_redirected) ||
            color_targets > 1) {
            static u32 warned = 0;
            if (warned < 8) {
                ++warned;
                const auto describe = [&](VideoCore::ImageId id) {
                    if (!id) {
                        return std::string{"-"};
                    }
                    const auto& info = texture_cache.GetImage(id).info;
                    return fmt::format("{:#x} {}x{} {}", info.guest_address, info.size.width,
                                       info.size.height, vk::to_string(info.pixel_format));
                };
                std::printf("Upscaler: pass not redirected (color %s: %s, depth %s: %s, %u "
                            "targets)\n",
                            color_redirected ? "yes" : "no", describe(cb_descs[0].first).c_str(),
                            depth_redirected ? "yes" : "no", describe(db_desc.first).c_str(),
                            state.num_color_attachments);
            }
            if (color_redirected) {
                state.color_attachments[0].image_view = original_color.first;
                state.color_attachments[0].image_layout = original_color.second;
            }
            if (depth_redirected) {
                auto& depth_image = texture_cache.GetImage(db_desc.first);
                state.depth_stencil_attachment.image_view =
                    *texture_cache.FindDepthTarget(db_desc.first, db_desc.second).image_view;
                state.depth_stencil_attachment.image_layout = depth_image.backing->state.layout;
            }
        } else {
            state.width = redirect.width;
            state.height = redirect.height;
            // Viewports and scissors follow each draw's viewport (UpdateUiTransform).
            ui_pass = {true, redirect.native_ui, {guest_extent.first, guest_extent.second},
                       {redirect.width, redirect.height}};
            UpdateUiTransform(pipeline);
        }
    }

    if (state.num_layers == std::numeric_limits<u16>::max()) {
        state.num_layers = 1;
    }
    // bbport (r11_depth_clear): a native pass whose load ops clear a proxied depth image (the
    // game's depth clear, vs 89cda9e4, comes before the G-buffer pass starts the scene, so it is
    // never reduced) clears the proxy too when all of the image ends as the clear values, so the
    // next reduced pass needs no fill (SceneTargets::NativeDepthClear; experiment bit
    // 68719476736: filled as before).
    if (!reduced && db_desc.first && !color_redirected && !depth_redirected &&
        (state.depth_stencil_attachment.depth_clear ||
         state.depth_stencil_attachment.stencil_clear)) {
        const auto& clear_depth = texture_cache.GetImage(db_desc.first);
        const auto& clear_range = db_desc.second.view_info.range;
        const auto& ds = state.depth_stencil_attachment;
        // As UpdateDepthStencilState: a DB clear turns the draws' depth writes off.
        const bool depth_written = regs.depth_control.depth_enable &&
                                   regs.depth_control.depth_write_enable &&
                                   !regs.depth_render_control.depth_clear_enable;
        const bool whole = clear_range.base.layer == 0 && clear_range.base.level == 0 &&
                           state.width >= clear_depth.info.size.width &&
                           state.height >= clear_depth.info.size.height;
        scene_targets->NativeDepthClear(
            clear_depth, ds.has_depth && ds.depth_clear, depth_written,
            ds.has_stencil && ds.stencil_clear,
            vk::ClearDepthStencilValue{std::bit_cast<float>(ds.clear_value[0]), ds.clear_value[1]},
            whole, scheduler.WillRunLoadOps(state));
    }

    if (reduced) {
        // Half-resolution passes keep the scene's factor (proxy / native = scene / 1920).
        const auto size = scene_targets->Size();
        const auto proxy = pass_size.value_or(size);
        state.width = proxy.width;
        state.height = proxy.height;
        const auto native = SceneResolution::Native();
        target_scale = {float(size.width) / float(native.width), float(size.height) / float(native.height)};
        ui_pass.active = false; // the memo keeps this scale for the pass
    }
    if (FrameCapture::Active()) {
        std::array<const VideoCore::ImageInfo*, AmdGpu::NUM_COLOR_BUFFERS> colors{};
        for (u32 cb = 0; cb < state.num_color_attachments; ++cb) {
            if (cb_descs[cb].first) {
                colors[cb] = &texture_cache.GetImage(cb_descs[cb].first).info;
            }
        }
        const auto* depth =
            db_desc.first ? &texture_cache.GetImage(db_desc.first).info : nullptr;
        FrameCapture::BeginPass(colors.data(), state.num_color_attachments, depth);
    }
    // bbport: object motion vector attachment of G-buffer pipelines.
    if (key.motion_vectors & Shader::MotionVectors::VertexOutputs) {
        object_motion->Attach(state, state.width, state.height);
    }
    return state;
}

void Rasterizer::Resolve() {
    const bool log_gap = window_receiver && window_receiver->pane && window_receiver->pane->owner &&
                         NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap::Resolve);
    const auto& mrt0_hint = CbExtent(0);
    const auto& mrt1_hint = CbExtent(1);
    VideoCore::TextureCache::ImageDesc mrt0_desc{Regs().color_buffers[0], mrt0_hint};
    VideoCore::TextureCache::ImageDesc mrt1_desc{Regs().color_buffers[1], mrt1_hint};
    if (log_gap) {
        const auto& range = mrt1_desc.view_info.range;
        LogWindowOwnerGap("resolve",
                          fmt::format("mrt=1 dst={:#x}+{:#x} mip={} layer={} layers={}",
                                      mrt1_desc.info.guest_address, mrt1_desc.info.guest_size,
                                      range.base.level, range.base.layer, range.extent.layers).c_str());
    }
    auto& mrt0_image = texture_cache.GetImage(texture_cache.FindImage(mrt0_desc, true));
    auto& mrt1_image = texture_cache.GetImage(texture_cache.FindImage(mrt1_desc, true));

    if (foliage_mask) FoliageWriter(mrt1_image.guest_begin, mrt1_image.guest_end - mrt1_image.guest_begin);
    ScopeMarkerBegin(fmt::format("Resolve:MRT0={:#x}:MRT1={:#x}",
                                 Regs().color_buffers[0].Address(),
                                 Regs().color_buffers[1].Address()));
    runtime.ResolveImage(&mrt0_image, &mrt1_image, mrt0_desc.view_info.range,
                         mrt1_desc.view_info.range);
    ScopeMarkerEnd();
}

void Rasterizer::DepthStencilCopy(bool is_depth, bool is_stencil) {
    const bool log_gap = window_receiver && window_receiver->pane && window_receiver->pane->owner &&
                         NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap::DepthStencilCopy);
    auto& regs = Regs();

    auto read_desc = VideoCore::TextureCache::ImageDesc(
        regs.depth_buffer, regs.depth_view, regs.depth_control,
        regs.depth_htile_data_base.GetAddress(), DbExtent(), false);
    auto write_desc = VideoCore::TextureCache::ImageDesc(
        regs.depth_buffer, regs.depth_view, regs.depth_control,
        regs.depth_htile_data_base.GetAddress(), DbExtent(), true);

    if (log_gap) {
        const auto& dst = write_desc.info;
        LogWindowOwnerGap("depth-stencil-copy",
                          fmt::format("depth={} stencil={} dst={:#x}+{:#x} stencil-dst={:#x} "
                                      "layer={} layers={}",
                                      u32(is_depth), u32(is_stencil), dst.guest_address, dst.guest_size,
                                      dst.stencil_addr, u32(regs.depth_view.slice_start),
                                      regs.depth_view.NumSlices() - regs.depth_view.slice_start).c_str());
    }
    auto& read_image = texture_cache.GetImage(texture_cache.FindImage(read_desc));
    auto& write_image = texture_cache.GetImage(texture_cache.FindImage(write_desc));
    if (foliage_mask) {
        FoliageWriter(write_image.guest_begin, write_image.guest_end - write_image.guest_begin);
    }

    VideoCore::SubresourceRange sub_range;
    sub_range.base.layer = Regs().depth_view.slice_start;
    sub_range.extent.layers = Regs().depth_view.NumSlices() - sub_range.base.layer;

    ScopeMarkerBegin(fmt::format(
        "DepthStencilCopy:DR={:#x}:SR={:#x}:DW={:#x}:SW={:#x}", regs.depth_buffer.DepthAddress(),
        regs.depth_buffer.StencilAddress(), regs.depth_buffer.DepthWriteAddress(),
        regs.depth_buffer.StencilWriteAddress()));

    runtime.CopyDepthStencil(&read_image, &write_image, sub_range);

    ScopeMarkerEnd();
}

void Rasterizer::FillBuffer(VAddr address, u32 num_bytes, u32 value, bool is_gds, bool waited) {
    DrainDrawPipe();
    ASSERT_MSG(address % 4 == 0 && num_bytes % 4 == 0,
               "FillBuffer address and size must be a multiple of 4 bytes");
    if (!is_gds) {
        if (foliage_mask) FoliageWriter(address, num_bytes);
        texture_cache.ClearMeta(address);
        // bbport BB_GUEST_IN_PLACE: memory the GPU uses in place is filled by the GPU in stream order
        // (a fill on the CPU now would land before earlier draws read the old data). Elsewhere
        // (VRAM copies, unbound memory: shader code, descriptors this thread reads) on the CPU in
        // decode order, as before; the VRAM copy follows through write tracking.
        if (!buffer_cache.IsAnyInPlace(address, num_bytes) &&
            !buffer_cache.IsRegionGpuModified(address, num_bytes)) {
            if (!waited) {
                WaitBeforeDmaStore(address, num_bytes, 0, 0);
            }
            BbFreeCheck::Check(address, num_bytes, &value, BbFreeCheck::DmaFill);
            u32* buffer = std::bit_cast<u32*>(address);
            std::fill(buffer, buffer + (num_bytes / sizeof(u32)), value);
            BbWriteLog::Note(address, buffer, num_bytes, BbWriteLog::Dma);
            if (!VideoCore::WriteTracking()) {
                NoteAssetWrite(address, num_bytes);
            }
            return;
        }
    }
    if (!is_gds) { // bbport (r112q_hang-bracket-route): the palette writer watch hears the fill
        hang_gpu_watch.Written(0, BbWindHangGpu::WriterFill, address, num_bytes);
    }
    const auto [buffer, offset] = [&] -> std::pair<const VideoCore::Buffer*, u64> {
        if (is_gds) {
            return {buffer_cache.GetGdsBuffer(), address};
        }
        return buffer_cache.ObtainBuffer(address, num_bytes, true);
    }();
    runtime.FillBuffer(buffer, offset, num_bytes, value);
}

bool Rasterizer::DmaMayWriteOnCpu(VAddr dst, u32 num_bytes) {
    // The first condition of both: false only where they record a GPU fill or copy. The model
    // of 0.3 keeps its waits (the new memory and translation model only).
    if (!VideoCore::GuestInPlace()) {
        return true;
    }
    return !buffer_cache.IsAnyInPlace(dst, num_bytes) &&
           !buffer_cache.IsRegionGpuModified(dst, num_bytes);
}

bool Rasterizer::DmaWritesOnCpu(VAddr dst, u32 num_bytes, bool fill, VAddr src, bool src_gds) {
    static const bool all = [] {
        const char* env = std::getenv("BB_DMA_WAITS");
        return env && std::string_view{env} == "all";
    }();
    bool on_cpu = true;
    if (!all) {
        // FillBuffer's and CopyBuffer's tests for their CPU store.
        on_cpu = !buffer_cache.IsAnyInPlace(dst, num_bytes) &&
                 !buffer_cache.IsRegionGpuModified(dst, num_bytes) &&
                 (fill || (!src_gds && !buffer_cache.IsRegionGpuModified(src, num_bytes) &&
                           !texture_cache.FindImageFromRange(src, num_bytes)));
    }
    if (BbStats::enabled) {
        (on_cpu ? BbStats::dma_on_cpu : BbStats::dma_on_gpu).fetch_add(1, std::memory_order_relaxed);
    }
    return on_cpu;
}

void Rasterizer::WaitBeforeDmaStore(VAddr dst, u32 num_bytes, VAddr src, u32 src_size) {
    WaitHostCopiesFor(dst, num_bytes, BbStats::WaitDma);
    WaitDeferredSignalsFor(BbStats::WaitDma, dst, num_bytes, src, src_size);
}

void Rasterizer::CopyBuffer(VAddr dst, VAddr src, u32 num_bytes, bool dst_gds, bool src_gds,
                            bool waited) {
    DrainDrawPipe();
    if (foliage_mask && !dst_gds) FoliageWriter(dst, num_bytes);
    // bbport BB_GUEST_IN_PLACE: see FillBuffer (in place: the GPU, in stream order).
    if (!dst_gds && !buffer_cache.IsAnyInPlace(dst, num_bytes) &&
        !buffer_cache.IsRegionGpuModified(dst, num_bytes)) {
        if (!src_gds && !buffer_cache.IsRegionGpuModified(src, num_bytes) &&
            !texture_cache.FindImageFromRange(src, num_bytes)) {
            if (!waited) {
                WaitBeforeDmaStore(dst, num_bytes, src, num_bytes);
            }
            // Both buffers were not transferred to GPU yet. Can safely copy in host memory.
            BbFreeCheck::Check(dst, num_bytes, std::bit_cast<const void*>(src), BbFreeCheck::DmaCopy);
            std::memcpy(std::bit_cast<void*>(dst), std::bit_cast<void*>(src), num_bytes);
            BbWriteLog::Note(dst, std::bit_cast<const void*>(dst), num_bytes, BbWriteLog::Dma);
            if (!VideoCore::WriteTracking()) {
                NoteAssetWrite(dst, num_bytes);
            }
            return;
        }
    }
    {
        const VideoCore::InvalidateReason reason{"DMA copy"};
        texture_cache.InvalidateMemoryFromGPU(dst, num_bytes);
    }
    if (!dst_gds) { // bbport (r112q_hang-bracket-route): the palette writer watch hears the copy
        hang_gpu_watch.Written(0, BbWindHangGpu::WriterCopy, dst, num_bytes);
    }
    const auto* gds_buffer = buffer_cache.GetGdsBuffer();
    const auto [src_buffer, src_offset] = [&] -> std::pair<const VideoCore::Buffer*, u64> {
        if (src_gds) {
            return {gds_buffer, src};
        }
        return buffer_cache.ObtainBuffer(src, num_bytes, false, true);
    }();
    const auto [dst_buffer, dst_offset] = [&] -> std::pair<const VideoCore::Buffer*, u64> {
        if (dst_gds) {
            return {gds_buffer, dst};
        }
        return buffer_cache.ObtainBuffer(dst, num_bytes, true, true);
    }();
    const vk::BufferCopy copy = {
        .srcOffset = src_offset,
        .dstOffset = dst_offset,
        .size = num_bytes,
    };
    runtime.CopyBuffer(src_buffer, dst_buffer, std::span{&copy, 1});
}

u32 Rasterizer::ReadDataFromGds(u32 gds_offset) {
    DrainDrawPipe();
    auto* gds_buf = buffer_cache.GetGdsBuffer();
    u32 value;
    std::memcpy(&value, gds_buf->mapped_data.data() + gds_offset, sizeof(u32));
    return value;
}

bool Rasterizer::InvalidateMemory(VAddr addr, u64 size, bool assume_locks) {
    DrainDrawPipe();
    if (!IsMapped(addr, size)) {
        // Not GPU mapped memory, can skip invalidation logic entirely.
        return false;
    }
    if (foliage_mask) FoliageWriter(addr, size);
    buffer_cache.InvalidateMemory(addr, size, assume_locks);
    texture_cache.InvalidateMemory(addr, size);
    return true;
}

void Rasterizer::NoteAssetWrite(VAddr addr, u64 size) {
    const VideoCore::InvalidateReason reason{"asset or DMA"};
    buffer_cache.NoteAssetWrite(addr, size);
    InvalidateAfterWrite(addr, size);
}

void Rasterizer::InvalidateAfterWrite(VAddr addr, u64 size) {
    if (VideoCore::WriteTracking() || !buffer_cache.IsRegionGpuModified(addr, size)) {
        InvalidateMemory(addr, size);
        return;
    }
    // GPU data beside the bytes the CPU wrote lives in VRAM: an invalidation would read it back
    // (a 512 KiB window, whole pages) and upload pages over what the GPU writes meanwhile.
    // Exactly the CPU's bytes go into VRAM instead; images over them are refreshed.
    DrainDrawPipe();
    if (foliage_mask) FoliageWriter(addr, size);
    buffer_cache.NotePreciseUpload(addr, size);
    texture_cache.InvalidateMemory(addr, size);
}

void Rasterizer::NoteCommandWrite(VAddr addr, const void* data, u64 size, bool recording_thread) {
    const VideoCore::InvalidateReason reason{"command"};
    if (VideoCore::WriteTracking() || !IsMapped(addr, size)) {
        return; // tracking catches it, or the GPU does not use it
    }
    if (!recording_thread) {
        DrainDrawPipe();
    }
    buffer_cache.DropShadows(addr, size);
    // An invalidation would read the GPU's data back over these bytes first (a readback).
    if (!buffer_cache.UpdateGpuWritten(addr, std::span{static_cast<const u8*>(data), size})) {
        buffer_cache.InvalidateMemory(addr, size, recording_thread);
    }
    texture_cache.InvalidateMemory(addr, size);
}

void Rasterizer::OnCpuWrite(VAddr addr, u64 size) {
    const VideoCore::InvalidateReason reason{"CPU note"};
    BbStats::cpu_write_notes.fetch_add(1, std::memory_order_relaxed);
    BbStats::cpu_write_note_bytes.fetch_add(size, std::memory_order_relaxed);
    if (IsMapped(addr, size)) {
        InvalidateAfterWrite(addr, size);
        buffer_cache.NoteCpuWriteRange(addr, size);
    }
}

bool Rasterizer::FaultSkipsTextureCache() {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_FAULT_SKIP_TEXTURES");
        return !(env && env[0] == '0');
    }();
    return enabled;
}

bool Rasterizer::OnWriteFault(VAddr addr, bool assume_locks, u64 guest_rip) {
    const VideoCore::InvalidateReason reason{"page fault"};
    DrainDrawPipe();
    // bbport: within the faulting page. 8 bytes from a write to the last bytes of a mapping
    // reached past its end: IsMapped failed and the fault went unhandled (the game ended).
    const u64 size = std::min<u64>(8, VideoCore::PageManager::GetNextPageAddr(addr) - addr);
    // bbport: a page no tracked image watches (a buffer's page: most faults) needs nothing from
    // the texture cache, whose lock the draw recording thread holds while it creates or uploads
    // an image: a guest thread writing its constants waited for that (0.6 s with memory short:
    // the frame with it). Images learn of CPU writes through their own page protection only
    // (WatchedPages). BB_FAULT_SKIP_TEXTURES=0: the lock is taken for every fault, as before.
    if (FaultSkipsTextureCache() && !texture_cache.WatchesPages(addr, size)) {
        if (!IsMapped(addr, size)) {
            return false;
        }
        buffer_cache.InvalidateMemory(addr, size, assume_locks);
    } else if (!InvalidateMemory(addr, size, assume_locks)) {
        return false;
    }
    buffer_cache.ExtendWriteFault(addr, guest_rip);
    return true;
}

bool Rasterizer::ReadMemory(VAddr addr, u64 size, bool assume_locks) {
    DrainDrawPipe();
    if (!IsMapped(addr, size)) {
        // Not GPU mapped memory, can skip invalidation logic entirely.
        return false;
    }
    buffer_cache.ReadMemory(addr, size, false, assume_locks);
    return true;
}

void Rasterizer::ProcessDownloadImages() {
    DrainDrawPipe();
    texture_cache.ProcessDownloadImages();
}

bool Rasterizer::IsMapped(VAddr addr, u64 size) {
    if (size == 0) {
        // There is no memory, so not mapped.
        return false;
    }
    if (static_cast<u64>(addr) > std::numeric_limits<u64>::max() - size) {
        // Memory range wrapped the address space, cannot be mapped.
        return false;
    }
    const auto range = decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);

    Common::RecursiveSharedLock lock{mapped_ranges_mutex};
    return boost::icl::contains(mapped_ranges, range);
}

void Rasterizer::MapMemory(VAddr addr, u64 size) {
    {
        std::scoped_lock lock{mapped_ranges_mutex};
        mapped_ranges += decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);
    }
    buffer_cache.NotePreuploadMapping(addr, size, true);
}

void Rasterizer::RegisterMemory(VAddr addr, u64 size) {
    page_manager.OnGpuMap(addr, size);
}

void Rasterizer::UnmapMemory(VAddr addr, u64 size) {
    buffer_cache.NotePreuploadMapping(addr, size, false);
    buffer_cache.UnmapInPlace(addr, size);
    buffer_cache.DropTwins(addr, size);
    DrainDrawPipe();
    if (foliage_mask) FoliageWriter(addr, size);
    buffer_cache.InvalidateMemory(addr, size);
    texture_cache.UnmapMemory(addr, size);
    {
        std::scoped_lock lock{mapped_ranges_mutex};
        mapped_ranges -= decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);
    }
}

void Rasterizer::UpdateDynamicState(const GraphicsPipeline* pipeline, const bool is_indexed) const {
    BB_SECTION(UpdateDynamicState);
    // bbport (r21_draw-sort): dynamic state commands leave every bind as it is.
    Scheduler::R21Neutral r21_neutral{scheduler};
    UpdateViewportScissorState();
    UpdateDepthStencilState();
    UpdatePrimitiveState(is_indexed);
    UpdateRasterizationState();
    UpdateColorBlendingState(pipeline);

    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.CommitWith(instance.IsDepthBoundsSupported(),
                             instance.IsDynamicColorWriteMaskSupported(),
                             instance.IsAttachmentFeedbackLoopLayoutSupported(),
                             [&](auto&& command) { scheduler.Record(std::move(command)); });
}

vk::Rect2D Rasterizer::DrawScissor(u32 i) const {
    const auto& regs = Regs();

    const auto combined_scissor_value_tl = [](s16 scr, s16 win, s16 gen, s16 win_offset) {
        return std::max({scr, s16(win + win_offset), s16(gen + win_offset)});
    };
    const auto combined_scissor_value_br = [](s16 scr, s16 win, s16 gen, s16 win_offset) {
        return std::min({scr, s16(win + win_offset), s16(gen + win_offset)});
    };
    const bool enable_offset = !regs.window_scissor.window_offset_disable;

    AmdGpu::Scissor scsr{};
    scsr.top_left_x = combined_scissor_value_tl(
        regs.screen_scissor.top_left_x, s16(regs.window_scissor.top_left_x),
        s16(regs.generic_scissor.top_left_x),
        enable_offset ? regs.window_offset.window_x_offset : 0);
    scsr.top_left_y = combined_scissor_value_tl(
        regs.screen_scissor.top_left_y, s16(regs.window_scissor.top_left_y),
        s16(regs.generic_scissor.top_left_y),
        enable_offset ? regs.window_offset.window_y_offset : 0);
    scsr.bottom_right_x = combined_scissor_value_br(
        regs.screen_scissor.bottom_right_x, regs.window_scissor.bottom_right_x,
        regs.generic_scissor.bottom_right_x,
        enable_offset ? regs.window_offset.window_x_offset : 0);
    scsr.bottom_right_y = combined_scissor_value_br(
        regs.screen_scissor.bottom_right_y, regs.window_scissor.bottom_right_y,
        regs.generic_scissor.bottom_right_y,
        enable_offset ? regs.window_offset.window_y_offset : 0);

    if (regs.mode_control.vport_scissor_enable) {
        scsr.top_left_x = std::max(scsr.top_left_x, s16(regs.viewport_scissors[i].top_left_x));
        scsr.top_left_y = std::max(scsr.top_left_y, s16(regs.viewport_scissors[i].top_left_y));
        scsr.bottom_right_x = std::min(AmdGpu::Scissor::Clamp(scsr.bottom_right_x),
                                       regs.viewport_scissors[i].bottom_right_x);
        scsr.bottom_right_y = std::min(AmdGpu::Scissor::Clamp(scsr.bottom_right_y),
                                       regs.viewport_scissors[i].bottom_right_y);
    }
    if (ui_full_scissor[0] && scsr.top_left_x <= 0 && scsr.top_left_y <= 0 &&
        scsr.top_left_x + s32(scsr.GetWidth()) >= s32(ui_full_scissor[0]) &&
        scsr.top_left_y + s32(scsr.GetHeight()) >= s32(ui_full_scissor[1])) {
        return {.offset = {0, 0}, .extent = {16384, 16384}};
    }
    if (target_scale[0] != 1.0f || target_scale[1] != 1.0f || target_offset[0] || target_offset[1]) {
        const auto scale = [](s32 v, float f) { return s32(std::lround(float(v) * f)); };
        const s32 x0 = std::max(0, scale(scsr.top_left_x, target_scale[0]) + s32(target_offset[0]));
        const s32 y0 = std::max(0, scale(scsr.top_left_y, target_scale[1]) + s32(target_offset[1]));
        const s32 x1 = scale(scsr.top_left_x + s32(scsr.GetWidth()), target_scale[0]) + s32(target_offset[0]);
        const s32 y1 = scale(scsr.top_left_y + s32(scsr.GetHeight()), target_scale[1]) + s32(target_offset[1]);
        return {.offset = {x0, y0}, .extent = {u32(std::max(x1 - x0, 0)), u32(std::max(y1 - y0, 0))}};
    }
    return {.offset = {scsr.top_left_x, scsr.top_left_y},
            .extent = {scsr.GetWidth(), scsr.GetHeight()}};
}

void Rasterizer::UpdateViewportScissorState() const {
    auto& dc = Dc();
    const auto& regs = Regs();

    boost::container::static_vector<vk::Viewport, AmdGpu::NUM_VIEWPORTS> viewports;
    boost::container::static_vector<vk::Rect2D, AmdGpu::NUM_VIEWPORTS> scissors;

    if (regs.polygon_control.enable_window_offset &&
        (regs.window_offset.window_x_offset != 0 || regs.window_offset.window_y_offset != 0)) {
        LOG_ERROR(Render_Vulkan,
                  "PA_SU_SC_MODE_CNTL.VTX_WINDOW_OFFSET_ENABLE support is not yet implemented.");
    }

    const auto& vp_ctl = regs.viewport_control;
    for (u32 i = 0; i < AmdGpu::NUM_VIEWPORTS; i++) {
        const auto& vp = regs.viewports[i];
        const auto& vp_d = regs.viewport_depths[i];
        if (vp.xscale == 0) {
            continue;
        }

        const auto zoffset = vp_ctl.zoffset_enable ? vp.zoffset : 0.f;
        const auto zscale = vp_ctl.zscale_enable ? vp.zscale : 1.f;

        vk::Viewport viewport{};

        // https://gitlab.freedesktop.org/mesa/mesa/-/blob/209a0ed/src/amd/vulkan/radv_pipeline_graphics.c#L688-689
        // https://gitlab.freedesktop.org/mesa/mesa/-/blob/209a0ed/src/amd/vulkan/radv_cmd_buffer.c#L3103-3109
        // When the clip space is ranged [-1...1], the zoffset is centered.
        // By reversing the above viewport calculations, we get the following:
        if (regs.clipper_control.clip_space == AmdGpu::ClipSpace::MinusWToW) {
            viewport.minDepth = zoffset - zscale;
            viewport.maxDepth = zoffset + zscale;
        } else {
            viewport.minDepth = zoffset;
            viewport.maxDepth = zoffset + zscale;
        }

        if (!instance.IsDepthRangeUnrestrictedSupported()) {
            // Unrestricted depth range not supported by device. Restrict to valid range.
            viewport.minDepth = std::max(viewport.minDepth, 0.f);
            viewport.maxDepth = std::min(viewport.maxDepth, 1.f);
        }

        if (regs.IsClipDisabled()) {
            // In case if clipping is disabled we patch the shader to convert vertex position
            // from screen space coordinates to NDC by defining a render space as full hardware
            // window range [0..16383, 0..16383] and setting the viewport to its size.
            viewport.x = 0.f;
            viewport.y = 0.f;
            viewport.width = float(std::min<u32>(instance.GetMaxViewportWidth(), 16_KB));
            viewport.height = float(std::min<u32>(instance.GetMaxViewportHeight(), 16_KB));
        } else {
            const auto xoffset = vp_ctl.xoffset_enable ? vp.xoffset : 0.f;
            const auto xscale = vp_ctl.xscale_enable ? vp.xscale : 1.f;
            const auto yoffset = vp_ctl.yoffset_enable ? vp.yoffset : 0.f;
            const auto yscale = vp_ctl.yscale_enable ? vp.yscale : 1.f;

            // bbport: sub-pixel jitter of scene geometry for the temporal upscaler; the same
            // shift as jittering the projection.
            viewport.x = (xoffset - xscale) * target_scale[0] + target_offset[0]+dc.draw_jitter[0];
            viewport.y = (yoffset - yscale) * target_scale[1] + target_offset[1]+dc.draw_jitter[1];
            viewport.width = xscale * 2.0f * target_scale[0];
            viewport.height = yscale * 2.0f * target_scale[1];
        }

        viewports.push_back(viewport);

        vk::Rect2D scissor = DrawScissor(i);
        if (trees_pick_draw) { // bbport (r89j_twigs-pick-trees, TOOL): only the pick's patch is drawn (r86l: forward draws too)
            // bbport (r89l_twigs-palette-move): the scissors are in raster pixels (the game's scissor times the target scale
            // plus its offset); the patch was made in game-target pixels: scale it the same way. Build 57 read the pixels
            // unscaled at a raster of half the game targets: only a quarter of the picture could be picked, at half the
            // coordinates.
            const BbWindTrees::RasterRect pr = BbWindTrees::PickRectRaster(trees_pick_game, target_scale[0], target_scale[1],
                                                                          target_offset[0], target_offset[1]);
            static bool pick_scale_said = false;
            if (!pick_scale_said && camera_motion != nullptr) {
                pick_scale_said = true;
                const auto game = camera_motion->RenderSize();
                char pick_text[512];
                BbWindTrees::PickRasterText(BbWindTrees::PickOnce().out_w, BbWindTrees::PickOnce().out_h, game[0], game[1],
                                            target_scale[0], target_scale[1], target_offset[0], target_offset[1], pr.x, pr.y,
                                            pr.w, pr.h, pick_text, sizeof(pick_text));
                BbReport::Printf("%s\n", pick_text);
            }
            const s32 x0 = std::max(scissor.offset.x, pr.x);
            const s32 y0 = std::max(scissor.offset.y, pr.y);
            const s32 x1 = std::min(scissor.offset.x + s32(scissor.extent.width), pr.x + pr.w);
            const s32 y1 = std::min(scissor.offset.y + s32(scissor.extent.height), pr.y + pr.h);
            scissor = vk::Rect2D{.offset = {x0, y0}, .extent = {u32(std::max(x1 - x0, 0)), u32(std::max(y1 - y0, 0))}};
            // bbport (r89k_twigs-opaque-word): how many G-buffer scissors met the patch (the pick's note line)
            if (scissor.extent.width != 0 && scissor.extent.height != 0) {
                ++trees_pick_meet;
            } else {
                ++trees_pick_apart;
            }
        }
        scissors.push_back(scissor);
    }

    if (viewports.empty()) {
        // Vulkan requires providing at least one viewport.
        constexpr vk::Viewport empty_viewport = {
            .x = -1.0f,
            .y = -1.0f,
            .width = 1.0f,
            .height = 1.0f,
            .minDepth = 0.0f,
            .maxDepth = 1.0f,
        };
        constexpr vk::Rect2D empty_scissor = {
            .offset = {0, 0},
            .extent = {1, 1},
        };
        viewports.push_back(empty_viewport);
        scissors.push_back(empty_scissor);
    }

    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetViewports(viewports);
    dynamic_state.SetScissors(scissors);
}

void Rasterizer::UpdateDepthStencilState() const {
    const auto& regs = Regs();
    auto& dynamic_state = scheduler.GetDynamicState();

    const auto depth_test_enabled =
        regs.depth_control.depth_enable && regs.depth_buffer.DepthValid();
    dynamic_state.SetDepthTestEnabled(depth_test_enabled);
    if (depth_test_enabled) {
        dynamic_state.SetDepthWriteEnabled(regs.depth_control.depth_write_enable &&
                                           !regs.depth_render_control.depth_clear_enable);
        dynamic_state.SetDepthCompareOp(LiverpoolToVK::CompareOp(regs.depth_control.depth_func));
    }

    const auto depth_bounds_test_enabled = regs.depth_control.depth_bounds_enable;
    dynamic_state.SetDepthBoundsTestEnabled(depth_bounds_test_enabled);
    if (depth_bounds_test_enabled) {
        dynamic_state.SetDepthBounds(regs.depth_bounds_min, regs.depth_bounds_max);
    }

    const auto depth_bias_enabled = regs.polygon_control.NeedsBias();
    dynamic_state.SetDepthBiasEnabled(depth_bias_enabled);
    if (depth_bias_enabled) {
        const bool front = regs.polygon_control.enable_polygon_offset_front;
        dynamic_state.SetDepthBias(
            front ? regs.poly_offset.front_offset : regs.poly_offset.back_offset,
            regs.poly_offset.depth_bias,
            (front ? regs.poly_offset.front_scale : regs.poly_offset.back_scale) / 16.f);
    }

    const auto stencil_test_enabled =
        regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid();
    dynamic_state.SetStencilTestEnabled(stencil_test_enabled);
    if (stencil_test_enabled) {
        const StencilOps front_ops{
            .fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_fail_front),
            .pass_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zpass_front),
            .depth_fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zfail_front),
            .compare_op = LiverpoolToVK::CompareOp(regs.depth_control.stencil_ref_func),
        };
        const StencilOps back_ops = regs.depth_control.backface_enable ? StencilOps{
            .fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_fail_back),
            .pass_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zpass_back),
            .depth_fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zfail_back),
            .compare_op = LiverpoolToVK::CompareOp(regs.depth_control.stencil_bf_func),
        } : front_ops;
        dynamic_state.SetStencilOps(front_ops, back_ops);

        const bool stencil_clear = regs.depth_render_control.stencil_clear_enable;
        const auto front = regs.stencil_ref_front;
        const auto back =
            regs.depth_control.backface_enable ? regs.stencil_ref_back : regs.stencil_ref_front;
        // GCN REPLACE_OP writes DB_STENCILREFMASK.STENCILOPVAL, so a face whose stencil ops
        // include ReplaceOp takes its Vulkan reference from op_val.
        const auto& sc = regs.stencil_control;
        const auto uses_op_val = [](AmdGpu::StencilFunc fail, AmdGpu::StencilFunc zpass,
                                    AmdGpu::StencilFunc zfail) {
            return fail == AmdGpu::StencilFunc::ReplaceOp ||
                   zpass == AmdGpu::StencilFunc::ReplaceOp ||
                   zfail == AmdGpu::StencilFunc::ReplaceOp;
        };
        const bool front_op =
            uses_op_val(sc.stencil_fail_front, sc.stencil_zpass_front, sc.stencil_zfail_front);
        const bool back_op =
            regs.depth_control.backface_enable
                ? uses_op_val(sc.stencil_fail_back, sc.stencil_zpass_back, sc.stencil_zfail_back)
                : front_op;
        const auto ref_conflict = [](AmdGpu::CompareFunc func, const AmdGpu::StencilRefMask& ref) {
            return func != AmdGpu::CompareFunc::Always && func != AmdGpu::CompareFunc::Never &&
                   ref.stencil_test_val != ref.stencil_op_val;
        };
        if ((front_op && ref_conflict(regs.depth_control.stencil_ref_func, front)) ||
            (back_op && regs.depth_control.backface_enable &&
             ref_conflict(regs.depth_control.stencil_bf_func, back))) {
            LOG_WARNING(Render_Vulkan, "Stencil test requires test_val while ReplaceOp requires "
                                       "op_val; the stencil test will use op_val");
        }
        dynamic_state.SetStencilReferences(front_op ? front.stencil_op_val : front.stencil_test_val,
                                           back_op ? back.stencil_op_val : back.stencil_test_val);
        dynamic_state.SetStencilWriteMasks(!stencil_clear ? front.stencil_write_mask : 0U,
                                           !stencil_clear ? back.stencil_write_mask : 0U);
        dynamic_state.SetStencilCompareMasks(front.stencil_mask, back.stencil_mask);
    }
}

void Rasterizer::UpdatePrimitiveState(const bool is_indexed) const {
    const auto& regs = Regs();
    auto& dynamic_state = scheduler.GetDynamicState();

    const auto is_list_topology = [](const AmdGpu::PrimitiveType type) {
        const auto topology = LiverpoolToVK::PrimitiveType(type);
        return topology == vk::PrimitiveTopology::ePointList ||
               topology == vk::PrimitiveTopology::eLineList ||
               topology == vk::PrimitiveTopology::eTriangleList ||
               topology == vk::PrimitiveTopology::eLineListWithAdjacency ||
               topology == vk::PrimitiveTopology::eTriangleListWithAdjacency;
    };
    const auto is_patch_list_topology = [](const AmdGpu::PrimitiveType type) {
        // Quad and rect lists are emulated using tessellation.
        return type == AmdGpu::PrimitiveType::PatchPrimitive ||
               type == AmdGpu::PrimitiveType::QuadList || type == AmdGpu::PrimitiveType::RectList;
    };

    const auto prim_restart =
        (regs.enable_primitive_restart & 1) != 0 &&
        (instance.IsListRestartSupported() || !is_list_topology(regs.primitive_type)) &&
        (instance.IsPatchListRestartSupported() || !is_patch_list_topology(regs.primitive_type));
    ASSERT_MSG(!is_indexed || !prim_restart || regs.primitive_restart_index == 0xFFFF ||
                   regs.primitive_restart_index == 0xFFFFFFFF,
               "Primitive restart index other than -1 is not supported yet");

    const auto cull_mode = LiverpoolToVK::IsPrimitiveCulled(regs.primitive_type)
                               ? LiverpoolToVK::CullMode(regs.polygon_control.CullingMode())
                               : vk::CullModeFlagBits::eNone;
    const auto front_face = LiverpoolToVK::FrontFace(regs.polygon_control.front_face);

    dynamic_state.SetPrimitiveRestartEnabled(prim_restart);
    dynamic_state.SetRasterizerDiscardEnabled(regs.clipper_control.dx_rasterization_kill);
    dynamic_state.SetCullMode(cull_mode);
    dynamic_state.SetFrontFace(front_face);
}

void Rasterizer::UpdateRasterizationState() const {
    const auto& regs = Regs();
    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetLineWidth(regs.line_control.Width());
}

void Rasterizer::UpdateColorBlendingState(const GraphicsPipeline* pipeline) const {
    const auto& regs = Regs();
    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetBlendConstants(regs.blend_constants);
    const auto& key = pipeline->GetGraphicsKey();
    if (key.foliage_mask) {
        auto masks = key.write_masks;
        constexpr u32 slot = Shader::FoliageMaskOutput::Location;
        masks[slot] = key.HostWriteMask(slot);
        dynamic_state.SetColorWriteMasks(masks);
    } else {
        dynamic_state.SetColorWriteMasks(key.write_masks);
    }
    dynamic_state.SetAttachmentFeedbackLoopEnabled(attachment_feedback_loop);
}

void Rasterizer::ScopeMarkerBegin(const std::string_view& str, bool from_guest) {
    DrainDrawPipe();
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.beginDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
    });
}

void Rasterizer::ScopeMarkerEnd(bool from_guest) {
    DrainDrawPipe();
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.endDebugUtilsLabelEXT();
}

void Rasterizer::ScopedMarkerInsert(const std::string_view& str, bool from_guest) {
    DrainDrawPipe();
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.insertDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
    });
}

void Rasterizer::ScopedMarkerInsertColor(const std::string_view& str, const u32 color,
                                         bool from_guest) {
    DrainDrawPipe();
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.insertDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
        .color = std::array<f32, 4>(
            {(f32)((color >> 16) & 0xff) / 255.0f, (f32)((color >> 8) & 0xff) / 255.0f,
             (f32)(color & 0xff) / 255.0f, (f32)((color >> 24) & 0xff) / 255.0f})});
}

std::thread::id Rasterizer::GetGpuCommandProcessorThread() {
    return liverpool->GetGpuCommandProcessorThread();
}

#ifdef __linux__
u32 Rasterizer::GetGpuCommandProcessorThreadId() {
    return liverpool->GetGpuCommandProcessorThreadId();
}
#endif

} // namespace Vulkan

namespace Vulkan {

void Rasterizer::MarkPass(const GraphicsPipeline* pipeline, const RenderState& state) {
    auto* profiler = GpuProfiler::Get();
    if (!profiler) {
        return;
    }
    if (!scheduler.WillBeginRendering(state)) {
        profiler->NoteDraw(); // one more draw in the open pass
        return;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    std::array<u64, AmdGpu::NUM_COLOR_BUFFERS + 6> parts{};
    parts[0] = state.width | u64(state.height) << 32;
    parts[1] = vs.pgm_hash;
    parts[2] = ps ? ps->pgm_hash : 0;
    parts[3] = db_desc.first ? u64(texture_cache.GetImage(db_desc.first).info.pixel_format) : 0;
    for (u32 cb = 0; cb < state.num_color_attachments && cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        parts[4 + cb] = cb_descs[cb].first
                            ? u64(texture_cache.GetImage(cb_descs[cb].first).info.pixel_format) + 1
                            : 0;
    }
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    profiler->Mark(key, [&] {
        std::string targets;
        for (u32 cb = 0; cb < state.num_color_attachments; ++cb) {
            targets += cb_descs[cb].first
                           ? vk::to_string(texture_cache.GetImage(cb_descs[cb].first).info.pixel_format)
                           : std::string{"-"};
            targets += ' ';
        }
        return fmt::format("pass {}x{} [{}] depth {} vs {:016x} ps {:016x}", state.width,
                           state.height, targets,
                           db_desc.first ? vk::to_string(
                                               texture_cache.GetImage(db_desc.first).info.pixel_format)
                                         : std::string{"-"},
                           vs.pgm_hash, ps ? ps->pgm_hash : 0);
    });
    profiler->NoteDraw();
}

void Rasterizer::ReportUboStats() {
    static const bool enabled = std::getenv("BB_FRAME_STATS") != nullptr;
    static u32 frames = 0;
    if (!enabled || ++frames < 300) {
        return;
    }
    const auto& s = ubo_stats;
    BbReport::Printf("Uniform buffers per frame: %.0f from the constant ring, %.0f in place, %.0f in "
                "place with an offset, %.0f copied by the CPU and %.0f by the GPU to an aligned "
                "place\n",
                s.ring / double(frames), s.in_place / double(frames), s.offset / double(frames),
                s.staged / double(frames), s.copied / double(frames));
    ubo_stats = {};
    frames = 0;
}

void Rasterizer::NoteFrameStart() {
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->BeginFrame();
    }
    ReportUboStats();
    const u64 frame = BbStats::gpu_frames.fetch_add(1, std::memory_order_relaxed) + 1;
    // BB_BUFFER_STATS=1: how many earlier frames the GPU has not finished when the GPU thread
    // starts a frame â€” the lag that decides whether guest memory can be read in place.
    static const bool stats = [] {
        const char* value = std::getenv("BB_BUFFER_STATS");
        return value && value[0] == '1';
    }();
    if (!stats) {
        return;
    }
    static std::array<u64, 16> frame_ticks{};
    static std::array<u64, 17> lag_histogram{};
    u32 lag = 0;
    for (u32 back = 1; back < frame_ticks.size() && back < frame; ++back) {
        const u64 tick = frame_ticks[(frame - back) % frame_ticks.size()];
        if (tick && !scheduler.IsFree(tick)) {
            lag = back;
        }
    }
    ++lag_histogram[lag];
    frame_ticks[frame % frame_ticks.size()] = scheduler.CurrentTick();
    if (frame % 600 == 0) {
        std::printf("GPU lag at frame start (frames not finished: count):");
        for (u32 i = 0; i < lag_histogram.size(); ++i) {
            if (lag_histogram[i]) {
                std::printf(" %u:%llu", i, static_cast<unsigned long long>(lag_histogram[i]));
            }
        }
        std::printf("\n");
        lag_histogram = {};
    }
}

bool Rasterizer::SkyBeforeRendering(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
                                    bool is_indexed, u32 index_offset,
                                    const PreparedDraw* prepared, bool inputs_resolved) {
    auto& dc = Dc();
    const auto* sky_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!sky_seam->Enabled() || !sky_ps || sky_ps->pgm_hash != 0xdda49e89 ||
        pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash != 0xb28f5a56 || !is_indexed ||
        regs.num_indices != 1920 || regs.num_instances.NumInstances() != 1 ||
        !instance.IsVertexInputDynamicState()) {
        return false;
    }
    const auto [vertex, instance_index] = GetDrawOffsets(
        regs, pipeline->GetStage(Shader::SwStage::Vertex), pipeline->GetFetchShader());
    if (vertex != 0 || instance_index != 0) {
        return false;
    }
    if (!inputs_resolved) {
        ResolveVertexBuffers(pipeline, prepared);
        ResolveIndexBuffer(index_offset);
    }
    auto& v = dc.vertex_binds;
    const auto position =
        std::ranges::find(v.attributes, 0u, &vk::VertexInputAttributeDescription2EXT::location);
    const auto uv =
        std::ranges::find(v.attributes, 3u, &vk::VertexInputAttributeDescription2EXT::location);
    if (position == v.attributes.end() || uv == v.attributes.end() ||
        position->format != vk::Format::eR32G32B32Sfloat ||
        uv->format != vk::Format::eR16G16Sint || position->offset != 0 || uv->offset != 0 ||
        position->binding >= v.num_buffers || uv->binding >= v.num_buffers) {
        return true;
    }
    const auto pi = position->binding, ui = uv->binding;
    if (v.host_strides[pi] != 24 || v.host_strides[ui] != 24 ||
        v.host_sizes[pi] != v.host_sizes[ui] || v.host_sizes[pi] != 1824 * 24 ||
        !v.host_buffers[pi] || !v.host_buffers[ui]) {
        return true;
    }
    const u32 count = u32(v.host_sizes[pi] / 24);
    const auto result = sky_seam->Correct(
        {v.host_buffers[pi], v.host_offsets[pi], 484 * 24 + 12},
        {v.host_buffers[ui], v.host_offsets[ui], (count - 1) * 24 + 4}, 24, 24, count);
    if (!result) {
        return true;
    }
    if (sky_zenith->Enabled()) {
        u32 first_image = 0;
        for (const auto* stage : pipeline->GetStages()) {
            if (stage == sky_ps) {
                break;
            }
            if (stage) {
                first_image += u32(stage->images.size());
            }
        }
        for (u32 i = 0; i < sky_ps->images.size(); ++i) {
            const auto sharp = sky_ps->images[i].GetSharp(*sky_ps);
            const u32 index = first_image + i;
            if (sharp.base_level != 0 || sharp.last_level != 11 || index >= dc.image_infos.size()) {
                continue;
            }
            const auto image = std::ranges::find_if(dc.bound_images, [&](VideoCore::ImageId id) {
                if (!id) {
                    return false;
                }
                const auto& info = texture_cache.GetImage(id).info;
                return info.guest_address == sharp.Address() &&
                       info.pixel_format == vk::Format::eBc1RgbaSrgbBlock &&
                       info.size.width == 2048 && info.size.height == 512 &&
                       info.resources.layers == 1 && info.resources.levels == 12;
            });
            if (image == dc.bound_images.end()) {
                continue;
            }
            const auto& sky_image = texture_cache.GetImage(*image);
            SkyZenith::SourceKey sky_key{sky_image.GetImage(), sky_image.image_uid, 0,
                                         False(sky_image.flags & VideoCore::ImageFlagBits::Dirty)};
            for (const u64 mip_hash : sky_image.mip_hashes) {
                sky_key.hash = sky_key.hash * 0x9E3779B97F4A7C15ull + mip_hash + 1;
            }
            runtime.FlushBarriers();
            if (const auto view =
                    sky_zenith->Filter(dc.image_infos[index], sky_key, sky_seam->VerificationBuffer(),
                                       count)) {
                dc.image_infos[index].imageView = view;
                dc.image_infos[index].imageLayout = vk::ImageLayout::eGeneral;
            }
            break;
        }
    }
    v.host_buffers[ui] = result;
    v.host_offsets[ui] = 0;
    v.host_sizes[ui] = count * 4;
    v.host_strides[ui] = 4;
    for (auto& binding : v.bindings) {
        if (binding.binding == ui) {
            binding.stride = 4;
        }
    }
    return true;
}

void Rasterizer::DepthOfFieldAfterDraw(const GraphicsPipeline* pipeline, const RenderState& state) {
    auto& dc = Dc();
    const auto* ps_info = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps_info || !cb_descs[0].first ||
        (ps_info->pgm_hash != 0xf55643de && ps_info->pgm_hash != 0xfbe7c4b6 &&
         ps_info->pgm_hash != 0xe80526cc && ps_info->pgm_hash != DofRecombinePixelShaderHash)) {
        return;
    }
    const auto& vs_info = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto first_buffer = [&](const Shader::Info& info) {
        u32 first = 0;
        for (const auto* stage : pipeline->GetStages()) {
            if (stage == &info) {
                break;
            }
            if (stage) {
                first += u32(stage->buffers.size());
            }
        }
        return first;
    };
    const u32 pixel = first_buffer(*ps_info), vertex = first_buffer(vs_info);
    if (ps_info->buffers.empty() || pixel >= dc.buffer_infos.size()) {
        return;
    }
    const auto& constants = dc.buffer_infos[pixel];
    const u32 offset = dc.push_data.buf_offsets[pixel];
    if (ps_info->pgm_hash == 0xf55643de) {
        depth_of_field->Camera(constants, offset);
    } else if (ps_info->pgm_hash == 0xfbe7c4b6 && ps_info->images.size() == 3 &&
               dc.image_infos.size() >= 3) {
        depth_of_field->Encode(cb_descs[0].first, dc.image_infos[1]);
    } else if (ps_info->pgm_hash == 0xe80526cc && vs_info.pgm_hash == 0x7e956bc3 &&
               !vs_info.buffers.empty() && vertex < dc.buffer_infos.size()) {
        depth_of_field->Kernel(texture_cache.GetImage(cb_descs[0].first).info.guest_address,
                               constants, offset, dc.buffer_infos[vertex],
                               dc.push_data.buf_offsets[vertex]);
    } else if (ps_info->pgm_hash == DofRecombinePixelShaderHash && vs_info.pgm_hash == DofRecombineVertexShaderHash &&
               ps_info->images.size() == 2 && dc.image_infos.size() >= 2 &&
               state.num_color_attachments == 1 && state.num_layers == 1) {
        depth_of_field->Composite(cb_descs[0].first,
                                  ps_info->images[0].GetSharp(*ps_info).Address(),
                                  ps_info->images[1].GetSharp(*ps_info).Address(), dc.image_infos[0],
                                  constants, offset);
    }
}
} // namespace Vulkan
