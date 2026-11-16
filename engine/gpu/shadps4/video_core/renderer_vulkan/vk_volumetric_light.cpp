// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_volumetric_light.h"

#include <algorithm>
#include <utility>
#include <array>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring> // bbport (r76_sun-fog-outdoors)
#include <string>  // bbport (r76_sun-fog-outdoors)
#include <vector>

#include "bbport_settings.h"
#include "common/assert.h"
#include "video_core/host_shaders/volumetric_light_integrate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_comp.h"
#include "video_core/host_shaders/volumetric_light_tint_comp.h"
#include "bbport_toggles.h"
#include "video_core/host_shaders/volumetric_light_composite_comp.h"
#include "video_core/host_shaders/volumetric_light_filter_comp.h"
#include "video_core/host_shaders/point_volumetric_comp.h"
// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS: the lamp fog's shadow maps (ray queries) and
// the march's builds reading them
#include "video_core/host_shaders/lamp_fog_shaft_map_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
// bbport (r51b_volumetric-rt-check): the ray traced sun gate and the march's builds reading it
#include "video_core/host_shaders/volumetric_light_integrate_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_comp.h"
// bbport (r76_sun-fog-outdoors): the gate's diagnostics (BB_VOLUMETRIC_GATE_PROBE / _VIEW)
#include "video_core/host_shaders/volumetric_light_composite_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_view_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
// bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1)
#include "video_core/host_shaders/volumetric_area_gate_apply_comp.h"
#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
// bbport (r85_area-with-rt-gate): the march's AREA+GATE builds
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
// bbport (r115_sun-fog-indoors): the gate's and the march's DUAL builds (BB_VOLUMETRIC_AREA_GATE=2)
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_dual_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_dual_comp.h"
// bbport (r82_wind-stage1): the shared wind's knobs and the march's WIND builds (BB_WIND=1 only)
#include <cstddef>
#include "bbport_wind.h"
#include "video_core/host_shaders/volumetric_light_integrate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_wind_comp.h"
#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
// bbport (r88_wind-lamp-fog): the lamp fog's WIND builds (BB_WIND=1 only)
#include "video_core/host_shaders/point_volumetric_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_wind_comp.h"
#include "../host_shaders/lamp_wind_layout.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr u32 FogLightsAt = 256, FogMaxLights = 64;
constexpr u32 FogBytes = FogLightsAt + FogMaxLights * 64;
static_assert(FogBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
// bbport (r88_wind-lamp-fog): BB_WIND=1 only: where the lamp fog's wind words sit in fog_data
// (host_shaders/lamp_wind_layout.h, which point_volumetric.comp's WIND builds include too: five
// rows from word LAMP_WIND_AT) and the bytes the constants range then covers
constexpr u32 LampWindAt = LAMP_WIND_AT * 4;
constexpr u32 LampWindBytes = LampWindAt + LAMP_WIND_WORDS * 4;
static_assert(LampWindAt >= 16 * 4 && LampWindBytes <= FogLightsAt,
              "the wind words lie after the inverse projection and before the lights");
static_assert(LAMP_WIND_WORDS == 5 * LAMP_WIND_ROW &&
                  sizeof(LampFog::Camera::view_to_world) == 3 * LAMP_WIND_ROW * sizeof(float),
              "three view to world rows, then off1 and off2");
// bbport (r80_lamp-fog-shafts): a shadow map layer for every light record the lamp fog can draw
static_assert(FogMaxLights == LampFogShafts::MaxMaps && LampFog::AsListedLimit <= FogMaxLights);
constexpr vk::ImageSubresourceRange ShaftRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0,
                                               LampFogShafts::MaxMaps};
struct Params {
    u32 offsets, steps;
    float reach, density, strength, anisotropy, bias;
    u32 cascades; // VolumetricOcclusion::Pack (r51_volumetric-leak): count, mask, knob
};
static_assert(sizeof(Params) == 32);
// bbport (r82_wind-stage1): the push constants of the WIND builds (BB_WIND=1 only): Params as it
// is, then the camera's view to world matrix at the Integrate call (3x4 rows) and the noise
// offsets in cells (off1[3] = contrast, off2[3] = 1 for the BB_WIND_VIEW=1 view).
// volumetric_light.comp reads them as five vec4 after the plain words, so the tail must start at
// a multiple of 16 bytes. Vulkan guarantees 128 bytes of push constants.
struct WindParams {
    Params head;
    std::array<float, 12> view_to_world;
    std::array<float, 4> off1, off2;
};
static_assert(sizeof(Params) % 16 == 0, "the WIND tail's vec4 start at a multiple of 16");
static_assert(offsetof(WindParams, view_to_world) == sizeof(Params) &&
              offsetof(WindParams, off1) == sizeof(Params) + 48 &&
              offsetof(WindParams, off2) == sizeof(Params) + 64 &&
              sizeof(WindParams) == sizeof(Params) + 80);
static_assert(sizeof(WindParams) <= 128, "Vulkan guarantees 128 bytes of push constants");
// bbport (r94_fog-noise): the push constants of the NOISE builds (BB_FOG_NOISE above 0 only):
// Params as it is, then VolumetricFogNoise::Tail (volumetric_light.comp reads six vec4 after the
// plain words: the camera's view to world rows, the octaves' offsets with the amplitude, the gain
// and 1 / scale in [3]). PushBlock holds the bytes Integrate pushes, NoiseParams, WindParams or
// Params, of which it pushes as many as the bound build takes (push_size).
struct NoiseParams {
    Params head;
    VolumetricFogNoise::Tail tail;
};
static_assert(offsetof(NoiseParams, tail) == sizeof(Params) &&
                  sizeof(NoiseParams) == VolumetricFogNoise::PushBytes,
              "the NOISE tail's vec4 start right after Params; NoisePasses makes the builds with "
              "PushBytes");
struct PushBlock {
    std::array<u32, 32> words{};
    template <typename T>
    static PushBlock Of(const T& value) {
        static_assert(sizeof(T) <= sizeof(std::array<u32, 32>) && sizeof(T) % 4 == 0);
        PushBlock block;
        std::memcpy(block.words.data(), &value, sizeof(T));
        return block;
    }
};

// bbport (r82_wind-stage1): the drift's knobs, read once at the first SetWind (so only with
// BB_WIND=1), which logs them once: BB_WIND_FOG the contrast (BbWind::SanitizeContrast:
// 0-MaxContrast; missing or not a number: BbWind::DefaultContrast), BB_WIND_VIEW=1 the test
// view. BB_WIND_SHOW comes with SetWind (the rasterizer reads it once for both wind lines).
struct WindKnobs {
    float contrast;
    bool view;
};

const WindKnobs& WindFogKnobs() {
    static const WindKnobs knobs = [] {
        const char* fog = std::getenv("BB_WIND_FOG");
        float contrast = BbWind::DefaultContrast;
        if (fog != nullptr && fog[0] != 0) {
            char* end = nullptr;
            const float value = std::strtof(fog, &end);
            contrast = end != fog ? value : BbWind::DefaultContrast;
        }
        const char* view = std::getenv("BB_WIND_VIEW");
        return WindKnobs{BbWind::SanitizeContrast(contrast), view != nullptr && view[0] == '1'};
    }();
    return knobs;
}
// bbport (r87_live-flip-knobs): TOOL: BB_WIND_FOG asked again at every SetWind (a live knob), so one
// running game can show the drift's patches against even fog (0); WindFogKnobs' rule
float WindFogContrastLive() {
    static BbLiveKnobs::Knob<float> contrast{
        "BB_WIND_FOG", [](const char* text) -> float {
            float value = BbWind::DefaultContrast;
            if (text != nullptr && text[0] != 0) {
                char* end = nullptr;
                const float parsed = std::strtof(text, &end);
                value = end != text ? parsed : BbWind::DefaultContrast;
            }
            return BbWind::SanitizeContrast(value);
        }};
    return contrast.Get();
}
// bbport (r51b_volumetric-rt-check): the ray traced sun gate's cells (columns, rows, depth slices),
// the same whatever the resolution, and how far its rays look for a hit (the ray traced sun's).
constexpr u32 GateWidth = 160, GateHeight = 90, GateSlices = 32;
constexpr float GateMaxDistance = 800.0f;
// bbport (r76_sun-fog-outdoors): volumetric_rt_gate.comp's workgroup is a 2x2 block of columns with
// all their slices (local_size 2, 2, 32), so that it finds each column's first open slice; the
// shader's local size and RecordGate's dispatch hold only together with these sizes.
static_assert(GateSlices == 32 && GateWidth % 2 == 0 && GateHeight % 2 == 0);
// bbport (r76_sun-fog-outdoors): the gate probe's buffer: its words (volumetric_rt_gate.comp's
// block GateProbe, VolumetricOcclusion::GateProbe*), then the instances' masks, a byte each
static_assert(GateSlices == VolumetricOcclusion::GateProbeSlices);
constexpr u32 GateProbeHeaderBytes = VolumetricOcclusion::GateProbeWords * 4;
constexpr u32 GateProbeBytes = GateProbeHeaderBytes + VolumetricOcclusion::GateProbeInstancesMost;
static_assert(GateProbeBytes - GateProbeHeaderBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
struct GateParams {
    u32 offsets;
    float reach;
    u32 mask;
    float max_distance;
};
static_assert(sizeof(GateParams) == 16);
struct TintParams {
    u32 offset_bytes, record_count;
    float blend;
    u32 skip_fallback;
    u32 serial; // 1: the old one-thread loop (experiment bit 134217728)
};
static_assert(sizeof(TintParams) == 20);
// The fog's color moves 95% of the way to a new value in about 1.5 s (three time constants). After
// a longer gap than this (the first frame, a load) there is no earlier color worth fading from.
constexpr float TintFadeConstant = 0.5f, TintSnapAfter = 1.0f;

void Before(vk::CommandBuffer cmd) {
    const vk::MemoryBarrier2 b{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
        .dstStageMask = Compute,
        .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite};
    cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &b});
}

void After(vk::CommandBuffer cmd) {
    const vk::MemoryBarrier2 b{
        .srcStageMask = Compute,
        .srcAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite};
    cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &b});
}
}

VolumetricLight::VolumetricLight(const Instance& instance_, Scheduler& scheduler_,
                               VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                               SceneTargets& scene_targets_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_} {
}

bool VolumetricLight::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    bool made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
                EffectPass::StorageFormat(instance, vk::Format::eR32Sfloat) &&
                EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest);
    made = made &&
           CreatePass(integrate,
                      {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                       eStorageImage, eStorageImage},
                      VOLUMETRIC_LIGHT_INTEGRATE_COMP, sizeof(Params), "Volumetric integrate") &&
           CreatePass(repair,
                      {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                       eStorageImage, eStorageImage, eStorageImage},
                      VOLUMETRIC_LIGHT_REPAIR_COMP, sizeof(Params), "Volumetric repair") &&
           CreatePass(tint, {eStorageBuffer, eStorageBuffer},
                      VOLUMETRIC_LIGHT_TINT_COMP, sizeof(TintParams), "Volumetric tint") &&
           CreatePass(filter, {eCombinedImageSampler, eStorageImage},
                      VOLUMETRIC_LIGHT_FILTER_COMP, sizeof(u32), "Volumetric filter") &&
           CreatePass(composite,
                      {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageBuffer,
                       eCombinedImageSampler, eCombinedImageSampler},
                      VOLUMETRIC_LIGHT_COMPOSITE_COMP, sizeof(u32), "Volumetric composite") &&
           CreatePass(point,
                      {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
                      POINT_VOLUMETRIC_COMP, 3 * sizeof(u32), "Point volumetric");
    if (!made) {
        failed = true;
        std::printf("Volumetric lighting: off - this GPU cannot run the passes\n");
        return false;
    }
    tint_state = std::make_unique<VideoCore::Buffer>(
        instance, 0, 16, VideoCore::MemoryType::DeviceLocal, "Volumetric sky colour");
    fog_data = std::make_unique<VideoCore::Buffer>(
        instance, 0, FogBytes, VideoCore::MemoryType::DeviceLocal, "Lamp fog lights");
    return true;
}

VolumetricLight::~VolumetricLight() = default;

bool VolumetricLight::Enabled() {
    const auto& settings = BbSettings::Get();
    return !failed &&
           (settings.effects[BbSettings::EffectVolumetricLight].load(std::memory_order_relaxed) ||
            settings.effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) &&
           Ready();
}

bool VolumetricLight::CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                                 std::span<const u32> code, u32 push_size, const char* name,
                                 bool dispatch_base) {
    return EffectPass::Create(instance, pass.set, pass.layout, pass.pipeline, types, push_size,
                              code, name, dispatch_base);
}

// bbport (r51b_volumetric-rt-check): made at the gate's first use: the first march with a ray
// traced scene while BB_VOLUMETRIC_RT_GATE is not 0 (r76_sun-fog-outdoors: not set is 1), so a GPU
// without ray queries never makes them. Failing leaves the march as stage A left it.
bool VolumetricLight::GateReady() {
    if (gate_tried) {
        return !gate_failed;
    }
    gate_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) &&
        // bbport (r76_sun-fog-outdoors): and the column image, a byte a column
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * (GateSlices + 1)) &&
        EffectPass::CreateSampler(instance, gate_sampler, vk::Filter::eLinear) &&
        CreatePass(gate_volume, {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                                 eStorageImage}, // bbport (r76_sun-fog-outdoors): gate_first
                   VOLUMETRIC_RT_GATE_COMP, sizeof(GateParams), "Volumetric sun gate") &&
        CreatePass(integrate_gated,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP, sizeof(Params), "Volumetric integrate (gate)") &&
        CreatePass(repair_gated,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_COMP, sizeof(Params), "Volumetric repair (gate)");
    if (!made) {
        gate_failed = true;
        std::printf("Volumetric lighting (r51b): ray traced sun gate off - its passes could not be "
                    "made; the march stays as stage A\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_view = Check<"create volumetric sun gate view">(device.createImageViewUnique({
        .image = vk::Image(gate), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate), "Volumetric sun gate (ray traced)");
    // bbport (r76_sun-fog-outdoors): each column's first open slice (volumetric_rt_gate.comp)
    gate_first = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_first.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_first_view = Check<"create volumetric sun gate column view">(device.createImageViewUnique({
        .image = vk::Image(gate_first), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_first), "Volumetric sun gate: first open slice");
    std::printf("Volumetric lighting (r51b): ray traced sun gate, %ux%ux%u cells, one ray each, "
                "scene mask 0x%x (BB_VOLUMETRIC_RT_GATE %u, %s); r76: a pixel's march starts at "
                "the first open cell of its columns\n",
                GateWidth, GateHeight, GateSlices, sun_scene_mask, VolumetricOcclusion::RtGateMask(),
                VolumetricOcclusion::RtGateByDefault() ? "the default" : "set");
    return true;
}

// bbport (r51b_volumetric-rt-check): one ray toward the sun from the centre of every cell, before
// the march (volumetric_rt_gate.comp). bbport (r76_sun-fog-outdoors): and each column's first open
// slice (gate_first); the gate's profile row is pinned (printed below the BB_GPU_PROFILE_ROWS cut).
// With `probing` or `viewing` (BB_VOLUMETRIC_GATE_PROBE / _VIEW) the DIAG build traces instead: the
// same cells, to the nearest hit; probing also writes this frame's instance masks before it and
// copies the probe's words to the host after it (ReadGateProbe once the GPU is past this tick).
// `depth`: the march's camera depth (its depth_tex), which the DIAG build reads so that the probe
// counts only the cells in front of the visible surface.
void VolumetricLight::RecordGate(const ContactShadow::Inputs& in, u32 offsets, bool probing,
                                 bool viewing, const vk::DescriptorImageInfo& depth) {
    const bool diag = probing || viewing;
    const u32 diag_bits = (probing ? VolumetricOcclusion::GateDiagProbe : 0u) |
                          (viewing ? VolumetricOcclusion::GateDiagBand : 0u);
    // bbport (r76c_sun-fog-shells): with BB_VOLUMETRIC_GATE_SHELLS the records' gate bits for the
    // knob's mask (GateRayMask: 0x20 for the sun's casters, 0x40 for the camera pass's geometry,
    // shells left out); without it the knob's mask, as before
    const GateParams params{offsets, reach,
                            VolumetricOcclusion::GateRayMask(sun_scene_mask,
                                                             VolumetricOcclusion::GateShells().on) |
                                diag_bits |
                                // bbport (r115_sun-fog-indoors): a DUAL gate's second mask in bits
                                // 16-23 (the first ray's cull mask takes the low 8 bits only)
                                (gate_dual_on ? VolumetricOcclusion::GateRayMask(
                                                    sun_scene_mask | 2u,
                                                    VolumetricOcclusion::GateShells().on)
                                                    << 16
                                              : 0u),
                            GateMaxDistance};
    const vk::DescriptorBufferInfo cb{in.constants, in.constants_offset, in.constants_range};
    const vk::DescriptorBufferInfo ub{in.uniforms, in.uniforms_offset, in.uniforms_range};
    const vk::DescriptorImageInfo out{{}, *gate_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo first_out{{}, *gate_first_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): the DIAG build's band image and probe words (bound whenever it
    // runs; DiagReady made both)
    // bbport (r115_sun-fog-indoors): a DUAL gate writes its wider answer at binding 5 instead
    const vk::DescriptorImageInfo band_out{{}, gate_dual_on ? *gate_open_view : *gate_band_view,
                                           vk::ImageLayout::eGeneral};
    const vk::DescriptorBufferInfo probe_info{diag ? probe_buffer->Handle() : vk::Buffer{}, 0,
                                              GateProbeBytes};
    // bbport (r76c_sun-fog-shells): the DIAG build's words per instance (binding 8), zeroed before a
    // probe and, for the instances of the table, copied for the host after it
    const vk::DescriptorBufferInfo stats_info{diag ? probe_stats->Handle() : vk::Buffer{}, 0,
                                              VolumetricOcclusion::GateStatBytes};
    const std::size_t stats_instances =
        probing ? std::min<std::size_t>(probe_table.size(), VolumetricOcclusion::GateProbeInstancesMost)
                : 0;
    const u32 stats_bytes = u32(stats_instances * VolumetricOcclusion::GateStatWords * sizeof(u32));
    const vk::Buffer stats_back = probing ? probe_stats_readback->Handle() : vk::Buffer{};
    if (probing) {
        probe_stats_count = stats_instances;
    }
    std::vector<u32> masks =
        probing ? VolumetricOcclusion::PackGateMasks(probe_table) : std::vector<u32>{};
    const u32 mask_bytes = u32(masks.size() * sizeof(u32)); // before the capture moves `masks`
    EffectPass::Mark(51, "volumetric sun gate", true);
    scheduler.RecordCrumb(
        {.name = "Volumetric sun gate (ray traced)"},
        [params, cb, ub, out, first_out, band_out, probe_info, depth, diag, probing, mask_bytes,
         stats_info, stats_bytes, stats_back, // bbport (r76c_sun-fog-shells)
         masks = std::move(masks), readback = probing ? probe_readback->Handle() : vk::Buffer{},
         scene = sun_scene, image = vk::Image(gate), first_image = vk::Image(gate_first),
         band_image = gate_dual_on ? vk::Image(gate_open) : vk::Image(gate_band),
         dual = gate_dual_on, // bbport (r115_sun-fog-indoors)
         pipeline = diag           ? *gate_diag.pipeline
                    : gate_dual_on ? *gate_dual.pipeline // bbport (r115_sun-fog-indoors)
                                   : *gate_volume.pipeline,
         layout = diag           ? *gate_diag.layout
                  : gate_dual_on ? *gate_dual.layout
                                 : *gate_volume.layout](vk::CommandBuffer cmd) {
            if (probing) {
                // bbport (r76_sun-fog-outdoors): the probe's words from 0 and this frame's masks
                // (after the last probe's copy; Before() orders the dispatch after these writes)
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eAllCommands,
                                          vk::AccessFlagBits2::eMemoryRead |
                                              vk::AccessFlagBits2::eMemoryWrite,
                                          vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite);
                cmd.fillBuffer(probe_info.buffer, 0, GateProbeHeaderBytes, 0);
                cmd.fillBuffer(stats_info.buffer, 0, VolumetricOcclusion::GateStatBytes, 0); // (r76c)
                if (mask_bytes != 0) {
                    cmd.updateBuffer(probe_info.buffer, GateProbeHeaderBytes, mask_bytes,
                                     masks.data());
                }
            }
            Before(cmd);
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ColorRange,
            };
            // bbport (r76_sun-fog-outdoors): the column image is written whole every frame too; the
            // DIAG build's band image as well (whole when the view asks; unread otherwise)
            auto first_barrier = barrier;
            first_barrier.image = first_image;
            auto band_barrier = barrier;
            band_barrier.image = band_image;
            const std::array<vk::ImageMemoryBarrier2, 3> barriers{barrier, first_barrier, band_barrier};
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = diag || dual ? 3u : 2u, // (r115)
                                  .pImageMemoryBarriers = barriers.data()});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const std::array<vk::WriteDescriptorSet, 9> writes{{ // (r76c: 9 with binding 8)
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cb},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ub},
                {.pNext = &scene_info, .dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &first_out},
                // bbport (r76_sun-fog-outdoors): the DIAG build's own three
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &band_out},
                {.dstBinding = 6, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &probe_info},
                {.dstBinding = 7, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                // bbport (r76c_sun-fog-shells): the words per instance
                {.dstBinding = 8, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &stats_info},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), diag ? 9u : dual ? 6u : 5u}); // (r115)
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch(GateWidth / 2, GateHeight / 2, GateSlices / 32); // (r76) 2x2x32 groups
            if (probing) {
                // bbport (r76_sun-fog-outdoors): the probe's words to the host
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferRead);
                cmd.copyBuffer(probe_info.buffer, readback,
                               vk::BufferCopy{0, 0, GateProbeHeaderBytes});
                if (stats_bytes != 0) { // bbport (r76c_sun-fog-shells)
                    cmd.copyBuffer(stats_info.buffer, stats_back, vk::BufferCopy{0, 0, stats_bytes});
                }
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost,
                                          vk::AccessFlagBits2::eHostRead);
            }
            After(cmd);
        });
    if (probing) {
        probe_pending = true;
        probe_tick = scheduler.CurrentTick();
    }
}

// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_PROBE=1 or BB_VOLUMETRIC_GATE_VIEW=1 only, made
// at the first gated march with either set: the gate's DIAG build (ray queries, which the gate's
// own build has proven), its band image and the probe's buffers, and the march's and the
// composite's GATE_VIEW builds (bbport (r84_live-test-knobs): whichever knob asked first, so that the
// view may come on later through the live knobs file). Failing leaves the gate as it is without them.
bool VolumetricLight::DiagReady() {
    if (diag_tried) {
        return !diag_failed;
    }
    diag_tried = true;
    using enum vk::DescriptorType;
    bool made =
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices + GateProbeBytes +
                                          GateProbeHeaderBytes +
                                          2ull * VolumetricOcclusion::GateStatBytes) &&
        CreatePass(gate_diag,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage, eStorageBuffer, eCombinedImageSampler,
                    eStorageBuffer}, // bbport (r76c_sun-fog-shells): binding 8, words per instance
                   VOLUMETRIC_RT_GATE_DIAG_COMP, sizeof(GateParams), "Volumetric sun gate (diag)");
    // bbport (r84_live-test-knobs): the view's builds whichever of the two knobs asked first, so
    // that BB_VOLUMETRIC_GATE_VIEW may come on later through the live knobs file
    if (made) {
        made = EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
               CreatePass(integrate_gated_view,
                          {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                           eCombinedImageSampler, eStorageImage, eStorageImage,
                           eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                           eCombinedImageSampler},
                          VOLUMETRIC_LIGHT_INTEGRATE_GATE_VIEW_COMP, sizeof(Params),
                          "Volumetric integrate (gate view)") &&
               CreatePass(composite_view,
                          {eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                           eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                           eCombinedImageSampler},
                          VOLUMETRIC_LIGHT_COMPOSITE_GATE_VIEW_COMP, sizeof(u32),
                          "Volumetric composite (gate view)");
    }
    if (made) {
        probe_buffer = std::make_unique<VideoCore::Buffer>(
            instance, 0, GateProbeBytes, VideoCore::MemoryType::DeviceLocal,
            "Volumetric sun gate probe");
        probe_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, GateProbeHeaderBytes, VideoCore::MemoryType::HostCached,
            "Volumetric sun gate probe readback");
        made = probe_readback->mapped_data.size() >= GateProbeHeaderBytes;
        // bbport (r76c_sun-fog-shells): the DIAG build's words per instance and their host copy
        probe_stats = std::make_unique<VideoCore::Buffer>(
            instance, 0, VolumetricOcclusion::GateStatBytes, VideoCore::MemoryType::DeviceLocal,
            "Volumetric sun gate probe instances");
        probe_stats_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, VolumetricOcclusion::GateStatBytes, VideoCore::MemoryType::HostCached,
            "Volumetric sun gate probe instances readback");
        made = made && probe_stats_readback->mapped_data.size() >= VolumetricOcclusion::GateStatBytes;
    }
    if (!made) {
        diag_failed = true;
        std::printf("Volumetric lighting (r76): gate probe and view off - their passes or buffers "
                    "could not be made; the gate runs as without them\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate_band = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_band.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_band_view = Check<"create volumetric sun gate band view">(device.createImageViewUnique({
        .image = vk::Image(gate_band), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_band), "Volumetric sun gate: hit distance band");
    std::printf("Volumetric lighting (r76): gate diagnostics made (nearest-hit gate build, %ux%ux%u "
                "band cells%s)\n",
                GateWidth, GateHeight, GateSlices,
                ", the view's march and composite builds"); // bbport (r84_live-test-knobs): always
    return true;
}

// bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the view's image at the march's size
// (RGBA8), made again when that changes. False: no room, no view this march.
bool VolumetricLight::EnsureGateView() {
    if (gate_view_image && gate_view_width == width && gate_view_height == height) {
        return true;
    }
    if (gate_view_image) {
        scheduler.DeferOperation([image = std::move(gate_view_image),
                                  view = std::move(gate_view_image_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    gate_view_width = gate_view_height = 0;
    if (width == 0 || height == 0 || !EffectPass::HasRoom(instance, 4ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    gate_view_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_view_image.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR8G8B8A8Unorm,
        .extent = {width, height, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_view_image_view = Check<"create volumetric sun gate view image view">(
        device.createImageViewUnique({
            .image = vk::Image(gate_view_image), .viewType = vk::ImageViewType::e2D,
            .format = vk::Format::eR8G8B8A8Unorm, .subresourceRange = ColorRange,
        }));
    SetObjectName(device, vk::Image(gate_view_image), "Volumetric sun gate view");
    gate_view_width = width;
    gate_view_height = height;
    return true;
}

// bbport (r76_sun-fog-outdoors): the probe's line from the words the GPU copied back (the march
// RecordGate probed): the light's direction (the GPU's own, view space, turned to world with that
// frame's camera), the shut cells in front of the visible surface by the nearest hit's distance and
// of them the camera-only ones, and the centre column's surface and all its slices with the hit
// instance's key, triangles and record mask (the
// instance id is its index in the TLAS records, RtShadow::GateTable). Last, how far the host's
// copy of the direction (SetSunLight) lies from the GPU's.
void VolumetricLight::ReadGateProbe() {
    using namespace VolumetricOcclusion;
    probe_pending = false;
    std::array<u32, GateProbeWords> w{};
    probe_readback->Invalidate(0, sizeof(w));
    std::memcpy(w.data(), probe_readback->mapped_data.data(), sizeof(w));
    const std::array<float, 3> view{std::bit_cast<float>(w[GateProbeDirectionAt]),
                                    std::bit_cast<float>(w[GateProbeDirectionAt + 1]),
                                    std::bit_cast<float>(w[GateProbeDirectionAt + 2])};
    const std::array<float, 3> world =
        probe_light.camera ? ToWorld(probe_light.view_to_world, view) : std::array<float, 3>{};
    char light[160];
    if (world != std::array<float, 3>{}) {
        const auto angles = ElevationAzimuth(world);
        std::snprintf(light, sizeof(light), "light world (%.3f,%.3f,%.3f) elevation %.1f deg azimuth %.1f",
                      world[0], world[1], world[2], angles[0], angles[1]);
    } else {
        std::snprintf(light, sizeof(light), "light world unknown (view %.3f,%.3f,%.3f, camera %s)",
                      view[0], view[1], view[2], probe_light.camera ? "known" : "unknown");
    }
    std::string column;
    for (u32 s = 0; s < GateProbeSlices;) {
        const u32 t = w[GateProbeColumnAt + 2 * s];
        const u32 id = w[GateProbeColumnAt + 2 * s + 1];
        char part[96];
        if (t == GateColumnOpen || t == GateColumnNotAsked) {
            u32 end = s + 1;
            while (end < GateProbeSlices && w[GateProbeColumnAt + 2 * end] == t) {
                ++end;
            }
            const char* what = t == GateColumnOpen ? "open" : "-";
            if (end - s > 1) {
                std::snprintf(part, sizeof(part), " %u-%u:%s", s, end - 1, what);
            } else {
                std::snprintf(part, sizeof(part), " %u:%s", s, what);
            }
            s = end;
        } else {
            const float distance = std::bit_cast<float>(t);
            if (id < probe_table.size()) {
                const GateInstance& e = probe_table[id];
                std::snprintf(part, sizeof(part), " %u:%.1f m:%016llx:%u:0x%02x", s, distance,
                              static_cast<unsigned long long>(e.key), e.triangles, u32(e.mask));
            } else {
                std::snprintf(part, sizeof(part), " %u:%.1f m:instance %u not in the table", s,
                              distance, id);
            }
            ++s;
        }
        column += part;
    }
    char host[64];
    if (probe_light.valid && view != std::array<float, 3>{}) {
        std::snprintf(host, sizeof(host), "%.2f deg", AngleDeg(probe_light.view, view));
    } else {
        std::snprintf(host, sizeof(host), "unknown");
    }
    // The centre column's visible surface (its slices beyond it are not counted above)
    const float surface = std::bit_cast<float>(w[GateProbeSurfaceAt]);
    char surface_text[32];
    if (!(surface >= 0.0f)) {
        std::snprintf(surface_text, sizeof(surface_text), "none");
    } else if (surface >= 1e29f) {
        std::snprintf(surface_text, sizeof(surface_text), "sky");
    } else {
        std::snprintf(surface_text, sizeof(surface_text), "%.1f m", surface);
    }
    std::printf("Volumetric lighting (r76): gate probe: %s; shut cells in front of the surface "
                "<5/5-15/15-40/40-150/150-800 m = %u/%u/%u/%u/%u, camera-only %u/%u/%u/%u/%u; "
                "centre column (surface %s)%s; %u cells in front of the surface asked, "
                "mask 0x%x, %llu instances in the table; host light differs by %s\n",
                light, w[GateProbeShutAt], w[GateProbeShutAt + 1], w[GateProbeShutAt + 2],
                w[GateProbeShutAt + 3], w[GateProbeShutAt + 4], w[GateProbeCameraOnlyAt],
                w[GateProbeCameraOnlyAt + 1], w[GateProbeCameraOnlyAt + 2],
                w[GateProbeCameraOnlyAt + 3], w[GateProbeCameraOnlyAt + 4], surface_text,
                column.c_str(), w[GateProbeAskedAt], probe_mask,
                static_cast<unsigned long long>(probe_table.size()), host);
    ReadGateInstances(w); // bbport (r76c_sun-fog-shells)
}

// bbport (r76c_sun-fog-shells): the probe's second line, "gate instances": the instances of the
// scene that shut the most cells in front of the visible surface (GateTopMost, the DIAG build's
// words per instance), and the one most rays straight up hit first when it is not among them
// ("above"). Per instance: n cells shut, ff the share hit on a front face, t the nearest and
// farthest hit (m), eye the nearest and farthest hit point from the camera (m), dy the lowest and
// highest hit point above the camera (world y, m), up the cells whose ray straight up hit it first
// with the nearest such hit (m), tri its triangles, m its record mask; then from the capture of its
// last draw: pass (cam or sun), vs and ps program hashes, z (t test, w write, compare function),
// vp the depth range its viewport maps to, clamp the depth clamp bounds ("off": the viewport
// clamp is off), cull (and zc: z clip on), ord its place among the frame's capture draws, cam0 how
// far (m) the camera moved between the first and last camera pass draw recorded for it ("-": none),
// dyn 1 when its ray traced copy is moving, and "shell" when BB_VOLUMETRIC_GATE_SHELLS takes it. With
// BB_VOLUMETRIC_GATE_PROBE_FILE the line also goes to that file (written anew at the run's first
// probe, appended after).
void VolumetricLight::ReadGateInstances(
    const std::array<u32, VolumetricOcclusion::GateProbeWords>& w) {
    using namespace VolumetricOcclusion;
    const std::size_t n = std::min<std::size_t>(probe_stats_count, probe_table.size());
    std::vector<u32> stats(n * GateStatWords, 0u);
    if (!stats.empty()) {
        const std::size_t bytes = stats.size() * sizeof(u32);
        probe_stats_readback->Invalidate(0, bytes);
        std::memcpy(stats.data(), probe_stats_readback->mapped_data.data(), bytes);
    }
    std::vector<u32> top = GateTopInstances(stats, GateTopMost);
    const std::size_t listed = top.size();
    u32 above = 0xFFFFFFFFu, above_cells = 0, shutting = 0;
    for (std::size_t i = 0; i < n; ++i) {
        shutting += stats[i * GateStatWords + GateStatCount] != 0 ? 1 : 0;
        const u32 up = stats[i * GateStatWords + GateStatUp];
        if (up > above_cells) {
            above_cells = up;
            above = u32(i);
        }
    }
    if (above != 0xFFFFFFFFu && std::ranges::find(top, above) == top.end()) {
        top.push_back(above);
    }
    const auto& m = probe_light.view_to_world;
    char part[384];
    std::string line = "Volumetric lighting (r76c): gate instances: ";
    if (probe_light.camera) {
        // (the view looks along +z, as the gate's cells take it: its world y is row 1, column 2)
        std::snprintf(part, sizeof(part), "camera world (%.1f,%.1f,%.1f) looking %+.0f deg up",
                      m[3], m[7], m[11], std::asin(std::clamp(m[6], -1.0f, 1.0f)) * 57.29578f);
    } else {
        std::snprintf(part, sizeof(part), "camera unknown");
    }
    line += part;
    if (probe_light.valid) {
        std::snprintf(part, sizeof(part), ", light elevation %.1f deg",
                      ElevationAzimuth(probe_light.world)[0]);
        line += part;
    }
    std::snprintf(part, sizeof(part),
                  "; shut <5/5-15/15-40/40-150/150-800 m = %u/%u/%u/%u/%u of %u asked; ray mask "
                  "0x%x%s; %u of %llu instances shut cells; marches %llu",
                  w[GateProbeShutAt], w[GateProbeShutAt + 1], w[GateProbeShutAt + 2],
                  w[GateProbeShutAt + 3], w[GateProbeShutAt + 4], w[GateProbeAskedAt],
                  GateRayMask(probe_mask, GateShells().on),
                  GateShells().on ? " (shell rule on)" : "", shutting,
                  static_cast<unsigned long long>(probe_table.size()),
                  static_cast<unsigned long long>(light_marches));
    line += part;
    static constexpr std::array<const char*, 8> Funcs{"N", "L", "E", "LE", "G", "NE", "GE", "A"};
    static constexpr std::array<const char*, 4> Culls{"none", "front", "back", "both"};
    for (std::size_t k = 0; k < top.size(); ++k) {
        const u32 i = top[k];
        const u32* s = &stats[std::size_t(i) * GateStatWords];
        const GateInstance& e = probe_table[i];
        const u32 count = s[GateStatCount];
        std::snprintf(part, sizeof(part), " | %s%llu id=%u n=%u", k < listed ? "#" : "above #",
                      static_cast<unsigned long long>(k + 1), i, count);
        line += part;
        if (count != 0) {
            std::snprintf(part, sizeof(part),
                          " ff=%u%% t=%.1f-%.1f eye=%.1f-%.1f dy=%+.1f..%+.1f",
                          u32(u64(s[GateStatFront]) * 100 / count), GateMinFloat(s[GateStatNear]),
                          GateMaxFloat(s[GateStatFar]), GateMinFloat(s[GateStatEyeNear]),
                          GateMaxFloat(s[GateStatEyeFar]), GateMinOrdered(s[GateStatLow]),
                          GateFromOrdered(s[GateStatHigh]));
            line += part;
        }
        std::snprintf(part, sizeof(part), " up=%u@%.1f tri=%u m=0x%02x", s[GateStatUp],
                      GateMinFloat(s[GateStatUpNear]), e.triangles, u32(e.mask));
        line += part;
        if (i < probe_caps.size() && probe_caps[i].known) {
            const GateCapture& c = probe_caps[i];
            char moved[24] = "-";
            if (c.eye_known) {
                std::snprintf(moved, sizeof(moved), "%.1f",
                              std::hypot(c.camera[0] - c.first_camera[0],
                                         c.camera[1] - c.first_camera[1],
                                         c.camera[2] - c.first_camera[2]));
            }
            std::snprintf(part, sizeof(part),
                          " %s vs=%016llx ps=%016llx z=%s%s/%s vp=%.3f-%.3f clamp=%.3f-%.3f%s "
                          "cull=%s%s ord=%u cam0=%s dyn=%d%s",
                          c.camera_pass ? "cam" : "sun", static_cast<unsigned long long>(c.vs),
                          static_cast<unsigned long long>(c.ps),
                          (c.depth & GateDepthTest) != 0 ? "t" : "-",
                          (c.depth & GateDepthWrite) != 0 ? "w" : "-", Funcs[GateDepthFunc(c.depth)],
                          c.dmin, c.dmax, c.zmin, c.zmax,
                          (c.raster & GateDepthClamp) != 0 ? "" : "(off)",
                          Culls[c.raster & (GateCullFront | GateCullBack)],
                          (c.raster & GateZclip) != 0 ? "/zc" : "", c.order, moved,
                          c.moving ? 1 : 0, GateShell(GateShells(), c) ? " shell" : "");
        } else {
            std::snprintf(part, sizeof(part), " capture unknown");
        }
        line += part;
    }
    std::printf("%s\n", line.c_str());
    if (const char* path = std::getenv("BB_VOLUMETRIC_GATE_PROBE_FILE"); path && path[0] != '\0') {
        if (std::FILE* file = std::fopen(path, probe_file_begun ? "a" : "w")) {
            probe_file_begun = true;
            std::fputs(line.c_str(), file);
            std::fputc('\n', file);
            std::fclose(file);
        }
    }
}

// bbport (r76_sun-fog-outdoors): the direction toward the sun or moon as the host read it at this
// resolve (SetSunLight), said at the first march that knows it and again when it moved by more
// than 1 degree from the one said last: at most one line in 60 marches and 100 lines in all (a
// fault in the turn to world space would show as a line at every camera turn).
void VolumetricLight::SayLight() {
    using namespace VolumetricOcclusion;
    ++light_marches;
    if (!sun_light.valid) {
        return;
    }
    float change = 0.0f;
    if (light_lines > 0) {
        change = AngleDeg(sun_light.world, light_said);
        if (!(change > 1.0f) || light_marches - light_said_at < 60) {
            return;
        }
        if (light_lines >= 100) {
            if (light_lines == 100) {
                ++light_lines;
                std::printf("Volumetric lighting (r76): light direction changed again; no more "
                            "lines of it\n");
            }
            return;
        }
    }
    ++light_lines;
    light_said = sun_light.world;
    light_said_at = light_marches;
    const auto angles = ElevationAzimuth(sun_light.world);
    char why[48];
    if (light_lines == 1) {
        std::snprintf(why, sizeof(why), "first march");
    } else {
        std::snprintf(why, sizeof(why), "moved by %.1f deg", change);
    }
    std::printf("Volumetric lighting (r76): light direction world (%.3f, %.3f, %.3f) elevation "
                "%.1f deg azimuth %.1f deg, toward the sun or moon (%s)\n",
                sun_light.world[0], sun_light.world[1], sun_light.world[2], angles[0], angles[1],
                why);
}

// bbport (r81_sun-fog-no-rt): the area light gate's push constants (volumetric_area_gate.comp)
namespace {
struct AreaParams {
    u32 offset_bytes, record_count;
    float blend;
    u32 flags; // VolumetricAreaGate::FlagRecords, FlagProbe
};
static_assert(sizeof(AreaParams) == 16);
// The table as Tint reads it (its RecordBytes = 72 floats a record, at most 256 records) and as
// volumetric_light.comp's TINT build reads light 0's colour (dwords 16-18).
static_assert(VolumetricAreaGate::RecordBytes == 72 * sizeof(float) &&
              VolumetricAreaGate::Records == 256 && VolumetricAreaGate::RecordColour == 16);
}

// bbport (r81_sun-fog-no-rt): made at the first march while BB_VOLUMETRIC_AREA_GATE=1 (bbport
// (r85_area-with-rt-gate): with the ray traced gate or without it; with it AreaGatedReady then
// makes the AREA+GATE builds): the march's AREA builds (the bindings and push constants of the
// plain ones), the gate's CAMERA and APPLY passes, its state and the probe's copy of it. Failing
// leaves the march as without the gate.
bool VolumetricLight::AreaReady() {
    if (area_tried) {
        return !area_failed;
    }
    area_tried = true;
    using enum vk::DescriptorType;
    using namespace VolumetricAreaGate;
    bool made =
        EffectPass::HasRoom(instance, 2ull * StateBytes) &&
        CreatePass(integrate_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage},
                   VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP, sizeof(Params),
                   "Volumetric integrate (area gate)") &&
        CreatePass(repair_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage},
                   VOLUMETRIC_LIGHT_REPAIR_AREA_COMP, sizeof(Params),
                   "Volumetric repair (area gate)") &&
        CreatePass(area_camera,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_AREA_GATE_CAMERA_COMP, sizeof(AreaParams),
                   "Volumetric area gate (camera)") &&
        CreatePass(area_apply, {eStorageBuffer, eCombinedImageSampler, eStorageImage},
                   VOLUMETRIC_AREA_GATE_APPLY_COMP, sizeof(AreaParams),
                   "Volumetric area gate (apply)");
    if (made) {
        area_state = std::make_unique<VideoCore::Buffer>(
            instance, 0, StateBytes, VideoCore::MemoryType::DeviceLocal, "Volumetric area gate");
        area_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, StateBytes, VideoCore::MemoryType::HostCached,
            "Volumetric area gate probe readback");
        made = area_readback->mapped_data.size() >= StateBytes;
    }
    if (!made) {
        area_failed = true;
        std::printf("Volumetric lighting (r81): area light gate off - its passes or buffers could "
                    "not be made; the march stays as without it\n");
        return false;
    }
    std::printf("Volumetric lighting (r81): area light gate made (the camera's light sets from a "
                "%ux%u grid, at most %u records, each ray's last %.0f m weighed by its surface's "
                "light set)\n",
                GridX, GridY, Records, FarMetres);
    return true;
}

// bbport (r85_area-with-rt-gate): made at the first march with the ray traced gate while
// BB_VOLUMETRIC_AREA_GATE=1, after AreaReady (the gate's passes and state): the march's AREA+GATE
// builds, with the GATE builds' bindings (the pass's own, then the gate and each column's first
// open slice) and push constants (Params, 32 bytes). Failing leaves marches with the ray traced
// gate as without the area gate; those without it keep it.
bool VolumetricLight::AreaGatedReady() {
    if (area_rt_tried) {
        return !area_rt_failed;
    }
    area_rt_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        CreatePass(integrate_gated_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_COMP, sizeof(Params),
                   "Volumetric integrate (gate, area gate)") &&
        CreatePass(repair_gated_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_COMP, sizeof(Params),
                   "Volumetric repair (gate, area gate)");
    area_rt_failed = !made;
    std::printf(made ? "Volumetric lighting (r85): area light gate's builds for marches with the "
                       "ray traced sun gate made\n"
                     : "Volumetric lighting (r85): area light gate's builds for marches with the "
                       "ray traced sun gate could not be made; those marches stay without it\n");
    return made;
}

// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE as the engine reads it, live (the live
// knobs file of a test run may change it between two marches): 0 off, 1 r81's and r85's rule, 2 with
// r115's (VolumetricAreaGate::ParseMode).
u32 VolumetricLight::AreaMode() {
    static BbLiveKnobs::Knob<u32> mode{"BB_VOLUMETRIC_AREA_GATE", VolumetricAreaGate::ParseMode};
    return mode.Get();
}

// bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF as the engine reads it, live: 1 is
// on (VolumetricRoof::ParseMode), anything else off.
u32 VolumetricLight::RoofMode() {
    static BbLiveKnobs::Knob<u32> mode{"BB_VOLUMETRIC_ROOF", VolumetricRoof::ParseMode};
    return mode.Get();
}

// bbport (r115b_sun-fog-out-of-sewer-library): the factor of this march's sun fog strength: 1.0f with
// the knob off (one live knob read; `strength * 1.0f` is the same float, so nothing changes), else
// VolumetricRoof::Keep of the cover the rasterizer gave (the wind shelter's overhead cover; no field:
// 1). Says the rule once, and every 600 marches the counts.
float VolumetricLight::RoofKeep() {
    const u32 mode = RoofMode();
    if (mode != roof_mode_seen) {
        if (mode != 0) {
            std::printf("Volumetric lighting (r115b, BB_VOLUMETRIC_ROOF=1): on; the sun fog's strength is "
                        "scaled by 1 - smoothstep(%.2f, %.2f, the camera's roof share) (r115c: the wind shelter "
                        "field: BB_WIND=1 and BB_WIND_SHELTER above 0): none under a roof, whole in the open; "
                        "lamp fog unchanged\n",
                        double(VolumetricRoof::CoverLo), double(VolumetricRoof::CoverHi));
        } else if (roof_mode_seen != ~0u) {
            std::printf("Volumetric lighting (r115b): BB_VOLUMETRIC_ROOF now off (live knobs)\n");
        }
        roof_mode_seen = mode;
        roof_counts = {};
        roof_said_no_field = false;
    }
    if (mode == 0) {
        return 1.0f;
    }
    const float keep = VolumetricRoof::Keep(roof_cover);
    VolumetricRoof::Tally(roof_counts, roof_cover, keep);
    if (!(roof_cover >= 0.0f) && !roof_said_no_field) {
        roof_said_no_field = true;
        std::printf("Volumetric lighting (r115b): no overhead cover yet (the wind shelter field is not made "
                    "or its pass has not run: BB_WIND=1 and BB_WIND_SHELTER above 0 make it); the sun fog "
                    "stays whole until it does\n");
    }
    if (roof_counts.marches % 600 == 0) {
        std::printf("Volumetric lighting (r115b): roof rule on %llu marches: sun fog off %llu, dimmed %llu, "
                    "whole %llu (no cover known %llu); mean roof share %.2f\n",
                    static_cast<unsigned long long>(roof_counts.marches),
                    static_cast<unsigned long long>(roof_counts.off),
                    static_cast<unsigned long long>(roof_counts.dimmed),
                    static_cast<unsigned long long>(roof_counts.marches - roof_counts.off -
                                                    roof_counts.dimmed - roof_counts.no_field),
                    static_cast<unsigned long long>(roof_counts.no_field),
                    roof_counts.marches > roof_counts.no_field
                        ? roof_counts.cover_sum / double(roof_counts.marches - roof_counts.no_field)
                        : 0.0);
        roof_counts = {};
    }
    return keep;
}

// bbport (r115_sun-fog-indoors): made at the first march of BB_VOLUMETRIC_AREA_GATE=2 with the ray
// traced gate and the area gate (after GateReady, AreaReady and AreaGatedReady): the gate's DUAL
// build (its own bindings, then the wider answer at binding 5), the march's two DUAL builds (the
// AREA+GATE bindings, then the wider answer) and the wider answer's image, as the gate's. Failing
// leaves those marches with r85's rule (and the near rule).
static_assert((VolumetricOcclusion::Pack(4u, 0xFu, 0xFFu) & VolumetricAreaGate::NearMark) == 0u,
              "the near mark lies above the march's cascade word");
bool VolumetricLight::DualReady() {
    if (dual_tried) {
        return !dual_failed;
    }
    dual_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices) &&
        CreatePass(gate_dual,
                   {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage,
                    eStorageImage, eStorageImage},
                   VOLUMETRIC_RT_GATE_DUAL_COMP, sizeof(GateParams), "Volumetric sun gate (dual)") &&
        CreatePass(integrate_dual,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler, eCombinedImageSampler,
                    eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_DUAL_COMP, sizeof(Params),
                   "Volumetric integrate (gate, area gate, dual)") &&
        CreatePass(repair_dual,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler,
                    eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_DUAL_COMP, sizeof(Params),
                   "Volumetric repair (gate, area gate, dual)");
    if (!made) {
        dual_failed = true;
        std::printf("Volumetric lighting (r115): the dual sun gate could not be made; marches with "
                    "the ray traced gate keep r85's rule with the near rule\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate_open = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate_open.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_open_view = Check<"create volumetric sun gate wider view">(device.createImageViewUnique({
        .image = vk::Image(gate_open), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate_open), "Volumetric sun gate: wider answer (r115)");
    std::printf("Volumetric lighting (r115): dual sun gate made: a second ray from each of the "
                "%ux%ux%u cells the first leaves open, mask 0x%x, and the march's dual builds\n",
                GateWidth, GateHeight, GateSlices,
                VolumetricOcclusion::GateRayMask(sun_scene_mask | 2u,
                                                 VolumetricOcclusion::GateShells().on));
    return true;
}

// bbport (r115_sun-fog-indoors): once a march with the volumetric sunlight on: the mode when it
// changes (the rule once when it is 2), and while it is 2 every 600 marches how many were area gate
// marches and of them how many had the dual gate, no ray traced gate (light sets and the near rule)
// or the ray traced gate with r85's rule (fog noise or gate probe on, or the dual gate not made).
void VolumetricLight::SayAreaMode(u32 mode, bool area, bool gated, bool dual) {
    if (mode != area_mode_seen) {
        if (mode == 2) {
            std::printf("Volumetric lighting (r115): BB_VOLUMETRIC_AREA_GATE 2: surfaces nearer than "
                        "%.0f m leave the camera's light sets and take its weight; with the ray "
                        "traced gate a second ray per cell (camera geometry too) keeps open air and "
                        "window beams whole, the light sets weigh what it shuts\n",
                        double(VolumetricAreaGate::NearMetres));
        } else if (area_mode_seen != ~0u) {
            std::printf("Volumetric lighting (r115): BB_VOLUMETRIC_AREA_GATE now %u (live knobs)\n",
                        mode);
        }
        area_mode_seen = mode;
        r115_marches = r115_area = r115_dual = r115_plain = 0;
    }
    if (mode != 2) {
        return;
    }
    r115_area += area ? 1 : 0;
    r115_dual += dual ? 1 : 0;
    r115_plain += area && !gated ? 1 : 0;
    if (++r115_marches % 600 == 0) {
        std::printf("Volumetric lighting (r115): area gate 2 on %llu of 600 marches: %llu with the "
                    "dual ray traced gate, %llu without ray tracing, %llu with the ray traced gate "
                    "as r85 (fog noise or gate probe on)\n",
                    static_cast<unsigned long long>(r115_area),
                    static_cast<unsigned long long>(r115_dual),
                    static_cast<unsigned long long>(r115_plain),
                    static_cast<unsigned long long>(r115_area - r115_dual - r115_plain));
        r115_area = r115_dual = r115_plain = 0;
    }
}

// bbport (r115_sun-fog-indoors): after r81's probe line of a march with the near mark: how many of
// the grid's surface points were near and left out of the camera's weight.
void VolumetricLight::SayAreaNearProbe(const u32* w) {
    std::printf("Volumetric lighting (r115): area gate probe: %u of %u surface points of the grid "
                "nearer than %.0f m left out of the camera's light sets (weight %.2f)%s\n",
                w[VolumetricAreaGate::StateNear], w[AREA_STATE_SURFACE],
                double(VolumetricAreaGate::NearMetres),
                double(std::bit_cast<float>(w[AREA_STATE_CAMERA])),
                (area_probe_flags & VolumetricAreaGate::FlagDual) != 0u
                    ? "; dual march: the sun share above is the share the wider ray keeps"
                    : "");
}

// bbport (r81_sun-fog-no-rt): the area light gate, right after Tint at the game's directional
// light draw (the G-buffer and this frame's lighting table are there): CAMERA weighs the records
// and the camera's light sets, then APPLY turns the march's near, far and lit share into the fog,
// in the half resolution image and in the full resolution repair image, before Composite's filter
// reads either. On a probe march (the 120th, then every 600th) CAMERA also writes the grid's
// records and every record's rows 0-7, copied to the host for ReadAreaProbe.
void VolumetricLight::AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,
                               const vk::DescriptorImageInfo& records) {
    using namespace VolumetricAreaGate;
    if (area_probe_pending && scheduler.IsFree(area_probe_tick)) {
        ReadAreaProbe();
    }
    if (!std::exchange(area_pending, false) || !ready || !tinted || !Enabled()) {
        return;
    }
    const u32 record_count =
        records.imageView && lighting.buffer ? RecordCount(lighting.range, offset_bytes) : 0u;
    const bool has_records = record_count != 0;
    const auto now = std::chrono::steady_clock::now();
    const float seconds = std::chrono::duration<float>(now - area_time).count();
    area_time = now;
    const bool probing = !area_probe_pending && area_clock.Next();
    // The camera's weight fades as the fog's colour does (Tint).
    const AreaParams params{
        offset_bytes, record_count,
        seconds <= TintSnapAfter ? 1.0f - std::exp(-seconds / TintFadeConstant) : 1.0f,
        (has_records ? FlagRecords : 0u) | (probing ? FlagProbe : 0u) |
            // bbport (r115_sun-fog-indoors): the last Integrate's near mark and DUAL build
            (area_near_pending ? FlagNear : 0u) | (area_dual_pending ? FlagDual : 0u)};
    const vk::DescriptorBufferInfo state{area_state->Handle(), 0, StateBytes};
    // Without the table or texture 0 the state buffer and the march's depth copy stand in (the
    // passes do not read them then: every weight is 1)
    const vk::DescriptorBufferInfo table = has_records ? lighting : state;
    const vk::DescriptorImageInfo record_info{
        *sampler, has_records ? records.imageView : *depth_view,
        has_records ? records.imageLayout : vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_read{*sampler, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_half{{}, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_full{{}, *repair_view, vk::ImageLayout::eGeneral};
    scheduler.EndRendering();
    EffectPass::Mark(81, "volumetric area gate", true);
    scheduler.RecordCrumb(
        {.name = "Volumetric area gate"},
        [params, table, state, record_info, fog_read, fog_half, fog_full, probing,
         readback = probing ? area_readback->Handle() : vk::Buffer{}, half_w = width,
         half_h = height, full_w = depth_width, full_h = depth_height,
         camera_pipeline = *area_camera.pipeline, camera_layout = *area_camera.layout,
         apply_pipeline = *area_apply.pipeline,
         apply_layout = *area_apply.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 4> camera_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &record_info},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &fog_read},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, camera_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, camera_layout, 0,
                                    camera_writes);
            cmd.pushConstants(camera_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
            cmd.dispatch(1, 1, 1);
            EffectPass::ComputeBarrier(cmd);
            if (probing) {
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferRead);
                cmd.copyBuffer(state.buffer, readback, vk::BufferCopy{0, 0, StateBytes});
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost,
                                          vk::AccessFlagBits2::eHostRead);
            }
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, apply_pipeline);
            cmd.pushConstants(apply_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
            for (u32 image = 0; image < 2; ++image) {
                const bool half = image == 0;
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                     .pImageInfo = &record_info},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageImage,
                     .pImageInfo = half ? &fog_half : &fog_full},
                }};
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, apply_layout, 0, writes);
                cmd.dispatch(((half ? half_w : full_w) + 7) / 8, ((half ? half_h : full_h) + 7) / 8,
                             1);
            }
            After(cmd);
        });
    if (probing) {
        area_probe_pending = true;
        area_probe_tick = scheduler.CurrentTick();
        area_probe_light = sun_light;
        area_probe_flags = params.flags; // bbport (r115_sun-fog-indoors): SayAreaNearProbe
    }
}

// bbport (r81_sun-fog-no-rt): the probe's lines from the state the GPU copied back. First a summary:
// the camera's weight, the grid's fog before and after the gate, and whether the host's copy of the
// weight rule (volumetric_area_gate.h) gives the GPU's weights. Then one line for each of the
// records the most grid points showed (ranked first to fourth): its weight, its light 0 against
// the brightest record's as the rule takes it (colours scaled to at most 1 a channel), light 0's
// colour and the luminance of its four lights as the table holds them (which shows whether that
// scaling matters), and their directions' angles to the light the march marches (view and world
// space, -1: unknown), which tells which of them is the sun and in which space the table holds them.
// Every line stays under 300 characters, and the rank is a word: the slot runner keeps evidence
// lines up to 300 characters, the first and last line of each shape (digits aside).
void VolumetricLight::ReadAreaProbe() {
    using namespace VolumetricAreaGate;
    area_probe_pending = false;
    std::vector<u32> w(StateWords);
    area_readback->Invalidate(0, StateBytes);
    std::memcpy(w.data(), area_readback->mapped_data.data(), StateBytes);
    const auto word = [&w](u32 at) { return std::bit_cast<float>(w[at]); };
    const float best = word(AREA_STATE_BEST);
    const u32 counted = w[AREA_STATE_RECORD_COUNT];
    std::vector<std::string> lines;
    float differs = 0.0f;
    for (const u32 id : TopRecords(w.data() + AREA_STATE_COUNTS)) {
        if (id >= Records) {
            break;
        }
        std::array<float, ProbeRowFloats> row{};
        std::memcpy(row.data(), w.data() + AREA_STATE_ROWS + id * ProbeRowFloats, sizeof(row));
        const float gpu = word(AREA_STATE_WEIGHTS + id);
        const float scaled = SunLuminance(row.data() + RecordColour);
        const float host = id < counted && !IsFallback(row.data()) ? SunWeight(scaled, best) : 1.0f;
        differs = std::max(differs, std::abs(host - gpu));
        std::array<float, 4> stored{}, view{}, world{};
        for (u32 s = 0; s < 4; ++s) {
            stored[s] = RawLuminance(row.data() + RecordColour + 4 * s);
            const std::array<float, 3> dir{row[4 * s], row[4 * s + 1], row[4 * s + 2]};
            view[s] = area_probe_light.valid ? VolumetricOcclusion::AngleDeg(dir, area_probe_light.view)
                                             : -1.0f;
            world[s] = area_probe_light.valid
                           ? VolumetricOcclusion::AngleDeg(dir, area_probe_light.world)
                           : -1.0f;
        }
        char part[300];
        std::snprintf(part, sizeof(part),
                      "Volumetric lighting (r81): area gate record ranked %s: #%u on %u points, "
                      "weight %.2f, light 0 at %.2f of the brightest, rgb %.3g/%.3g/%.3g; lights "
                      "0-3 luminance %.3g/%.3g/%.3g/%.3g; angles view %.0f/%.0f/%.0f/%.0f world "
                      "%.0f/%.0f/%.0f/%.0f deg",
                      RankName(u32(lines.size())), id, w[AREA_STATE_COUNTS + id], gpu,
                      best > 0.0f ? scaled / best : 0.0f, row[RecordColour], row[RecordColour + 1],
                      row[RecordColour + 2], stored[0], stored[1], stored[2], stored[3], view[0],
                      view[1], view[2], view[3], world[0], world[1], world[2], world[3]);
        lines.emplace_back(part);
    }
    const float before = word(AREA_STATE_BEFORE), after = word(AREA_STATE_AFTER);
    char check[48];
    if (lines.empty()) {
        std::snprintf(check, sizeof(check), "no records seen");
    } else if (differs < 1e-3f) {
        std::snprintf(check, sizeof(check), "agree");
    } else {
        std::snprintf(check, sizeof(check), "differ by %.4f", differs);
    }
    std::printf("Volumetric lighting (r81): area gate probe: on %llu of %llu marches since the last; "
                "camera weight %.2f (now %.2f); brightest light 0 %.3f of %u records; grid %u "
                "surface %u sky, fog kept %.0f%% (%.4f of %.4f), sun share %.2f; host weights %s\n",
                static_cast<unsigned long long>(area_gated),
                static_cast<unsigned long long>(area_marches), word(AREA_STATE_CAMERA),
                word(AREA_STATE_CAMERA_NOW), best, counted, w[AREA_STATE_SURFACE],
                w[AREA_STATE_SKY], before > 0.0f ? 100.0f * after / before : 100.0f, after, before,
                word(AREA_STATE_LIT), check);
    for (const std::string& line : lines) {
        std::printf("%s\n", line.c_str());
    }
    if ((area_probe_flags & VolumetricAreaGate::FlagNear) != 0u) {
        SayAreaNearProbe(w.data()); // bbport (r115_sun-fog-indoors)
    }
    area_gated = area_marches = 0;
}

void VolumetricLight::EnsureImage(u32 w, u32 h) {
    if (fog && depth_width == w && depth_height == h) return;
    if (fog) {
        scheduler.DeferOperation(
            [image = std::move(fog), view = std::move(fog_view),
             filtered_image = std::move(filtered_fog), filtered_image_view = std::move(filtered_view),
             repair_image = std::move(repair_fog), repair_image_view = std::move(repair_view),
             point_image = std::move(point_fog), point_image_view = std::move(point_view),
             z = std::move(depth_snapshot), zv = std::move(depth_view)]() mutable {
                view.reset();
                image.Destroy();
                filtered_image_view.reset();
                filtered_image.Destroy();
                repair_image_view.reset();
                repair_image.Destroy();
                point_image_view.reset();
                point_image.Destroy();
                zv.reset();
                z.Destroy();
            });
    }
    depth_width = w;
    depth_height = h;
    width = (w + 1) / 2;
    height = (h + 1) / 2;
    const auto device = instance.GetDevice();
    fog = VideoCore::UniqueImage(device, instance.GetAllocator());
    fog.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    fog_view = Check<"create volumetric image view">(device.createImageViewUnique({
        .image = vk::Image(fog), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat, .subresourceRange = ColorRange,
    }));
    filtered_fog = VideoCore::UniqueImage(device, instance.GetAllocator());
    filtered_fog.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    filtered_view = Check<"create filtered volumetric view">(device.createImageViewUnique({
        .image = vk::Image(filtered_fog), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat, .subresourceRange = ColorRange,
    }));
    repair_fog = VideoCore::UniqueImage(device, instance.GetAllocator());
    repair_fog.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    repair_view = Check<"create volumetric repair view">(device.createImageViewUnique({
        .image = vk::Image(repair_fog), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat, .subresourceRange = ColorRange,
    }));
    point_fog = VideoCore::UniqueImage(device, instance.GetAllocator());
    point_fog.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                 vk::ImageUsageFlagBits::eTransferDst,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    point_view = Check<"create point volumetric view">(device.createImageViewUnique({
        .image = vk::Image(point_fog), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat, .subresourceRange = ColorRange,
    }));
    depth_snapshot = VideoCore::UniqueImage(device, instance.GetAllocator());
    depth_snapshot.Create({
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR32Sfloat,
        .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    depth_view = Check<"create volumetric depth snapshot view">(device.createImageViewUnique({
        .image = vk::Image(depth_snapshot), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR32Sfloat, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(fog), "Directional volumetric scattering");
    SetObjectName(device, vk::Image(depth_snapshot), "Volumetric opaque depth snapshot");
    SetObjectName(device, vk::Image(filtered_fog), "Volumetric filtered scattering");
    SetObjectName(device, vk::Image(repair_fog), "Volumetric thin-surface repair");
    std::printf("Volumetric lighting: %ux%u, %u steps, range %.1f m, strength %.3f\n",
                width, height, steps, reach, strength);
}

void VolumetricLight::Integrate(VideoCore::ImageId shadow_target,
                                const vk::DescriptorImageInfo& depth,
                                const ContactShadow::Inputs& in) {
    Reset();
    atlas_reach = 0.0f;
    if (!Enabled() || !shadow_target || !depth.imageView || !in.shadow_map ||
        !in.constants || !in.uniforms) return;
    if (in.constants_range < (in.constants_offset_word & 255u) + 336u ||
        in.uniforms_range < ((in.constants_offset_word >> 8) & 255u) + 296u) {
        failed = true;
        std::printf("Volumetric lighting: unexpected shadow constant ranges; off\n");
        return;
    }
    auto& target = texture_cache.GetImage(shadow_target);
    u32 w = target.info.size.width, h = target.info.size.height;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(target)) {
        w = scene_targets.Size().width;
        h = scene_targets.Size().height;
    }
    if ((!fog || depth_width != w || depth_height != h) &&
        !EffectPass::HasRoom(instance, 2 * 8ull * ((w + 1) / 2) * ((h + 1) / 2) + 2 * 8ull * w * h + 4ull * w * h)) {
        failed = true;
        std::printf("Volumetric lighting: off - not enough video memory\n");
        return;
    }
    scheduler.EndRendering();
    EnsureImage(w, h);
    const float intensity = BbSettings::Get().graphics_volumetric_intensity.load(
        std::memory_order_relaxed);
    const float live_strength = RoofKeep() * strength * // bbport (r115b_sun-fog-out-of-sewer-library): 1.0f unless BB_VOLUMETRIC_ROOF=1
        std::clamp(std::isfinite(intensity) ? intensity : 1.0f, 0.0f, 3.0f) *
        float(BbSettings::Get().effects[BbSettings::EffectVolumetricLight].load(
            std::memory_order_relaxed));
    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE as this march reads it (live), and with 2
    // the near mark for the AREA builds (bit 24 of `cascades`, which no other build reads)
    const u32 area_mode = AreaMode();
    const Params params{in.constants_offset_word, steps, reach, density, live_strength,
                        anisotropy, 0.02f,
                        VolumetricOcclusion::Pack(atlas_cascades, atlas_valid,
                                                  VolumetricOcclusion::Bits()) |
                            (area_mode == 2 ? VolumetricAreaGate::NearMark : 0u)};
    atlas_reach = live_strength > 0.0f ? reach : 0.0f;
    // bbport (r51b_volumetric-rt-check): with this frame's ray traced scene and a gate mask
    // (SetSunScene; r76_sun-fog-outdoors: the rasterizer passes BB_VOLUMETRIC_RT_GATE's mask, 1 when
    // not set, whenever it prepared a scene), one ray toward the sun from each cell of the gate
    // first; the march then multiplies its atlas answer by the gate. Without them the march is
    // stage A's, unchanged.
    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
    // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1 (read once, said once at the first
    // march): a march without the ray traced gate keeps the AREA layout, which AreaGate weighs at
    // the directional light draw. Off: nothing of it is made or run.
    // bbport (r85_area-with-rt-gate): and a march with the ray traced gate too, through its
    // AREA+GATE builds (AreaGatedReady, made at the first such march): a sample counts only where
    // the atlas and the gate let the sun through, and AreaGate then weighs what is left. Not a
    // march the gate view draws (BB_VOLUMETRIC_GATE_VIEW=1): the GATE_VIEW build has no AREA
    // variant, and that view shows the gate alone. `viewing` below is that test once the view's
    // passes and image exist; the march binds an AREA build and owes AreaGate only with
    // `area && !viewing`, which stays consistent if the live knobs file turns the view on between
    // the two reads.
    const bool area_view = area_mode != 0 && AreaViewKnob(); // (r115: the live mode)
    const bool area = live_strength > 0.0f && area_mode != 0 && !(gated && area_view) &&
                      AreaReady() && (!gated || AreaGatedReady());
    if (live_strength > 0.0f) {
        // bbport (r85_area-with-rt-gate): the once-lines say which case acts: off (r81's line, at
        // the first march); on, r81's line at the first area gate march without the ray traced
        // gate, r85's at the first one with it, and r85's line when the gate view keeps it off
        // (again after the view was off)
        if (!area_said && area_mode == 0) {
            area_said = true;
            std::printf("Volumetric lighting (r81): area light gate off "
                        "(BB_VOLUMETRIC_AREA_GATE not 1 or 2): without the ray traced sun gate "
                        "the sun fog follows the atlas alone and can show indoors\n");
        }
        if (area && !gated && !area_said_plain) {
            area_said_plain = true;
            std::printf("Volumetric lighting (r81): area light gate on "
                        "(BB_VOLUMETRIC_AREA_GATE=%u): a march without the ray traced sun gate "
                        "keeps its sun fog only where the game's light set has sun (the "
                        "surface's for the last %.0f m of each ray, those on screen for the "
                        "rest) or where the air along the view is mostly in the atlas's "
                        "shadow (a beam)\n",
                        area_mode, VolumetricAreaGate::FarMetres); // (r115: the mode, 1 or 2)
        }
        if (area && gated && !area_said_traced) {
            area_said_traced = true;
            std::printf("Volumetric lighting (r85): area light gate on "
                        "(BB_VOLUMETRIC_AREA_GATE=%u) with the ray traced sun gate: a sample counts "
                        "only where the atlas and that gate let the sun through, then the game's "
                        "light sets weigh what is left as without that gate (the surface's for the "
                        "last %.0f m of each ray, those on screen for the rest)\n",
                        area_mode, VolumetricAreaGate::FarMetres); // (r115: the mode, 1 or 2)
        }
        if (area_mode != 0) {
            const bool view_off = gated && area_view;
            if (view_off && !area_said_view) {
                std::printf("Volumetric lighting (r85): area light gate off on marches the gate "
                            "view draws (BB_VOLUMETRIC_GATE_VIEW=1): that view shows the ray traced "
                            "sun gate alone\n");
            }
            area_said_view = view_off || (area_said_view && area_view);
        }
        ++area_marches;
        area_gated += area ? 1 : 0;
    }
    const u32 gate_knob = VolumetricOcclusion::RtGateMask();
    // bbport (r84_live-test-knobs): BB_VOLUMETRIC_RT_GATE changed through the live knobs file: said,
    // and the once-lines of a gate that is off or has no scene and the 600-march count start again
    if (gate_knob != gate_knob_seen) {
        if (gate_knob_seen != ~0u) {
            std::printf("Volumetric lighting (r84): BB_VOLUMETRIC_RT_GATE now %u%s (live knobs)\n",
                        gate_knob, VolumetricOcclusion::RtGateByDefault() ? " (the default)" : "");
        }
        gate_knob_seen = gate_knob;
        gate_off_said = false;
        gate_marches = gate_traced = 0;
    }
    if (live_strength > 0.0f && gate_knob == 0 && !gate_off_said) {
        gate_off_said = true;
        std::printf("Volumetric lighting (r76): ray traced sun gate off (BB_VOLUMETRIC_RT_GATE=0): "
                    "the sun fog follows the sun atlas alone and can show indoors\n");
    }
    if (live_strength > 0.0f && gate_knob != 0) {
        gate_traced += gated ? 1 : 0;
        if (++gate_marches % 600 == 0) {
            // bbport (r76_sun-fog-outdoors): only once a gate was tried (a ray traced scene came at
            // least once); a player without ray tracing gets the once-line below and nothing more
            if (gate_traced != 0 || gate_tried) {
                std::printf("Volumetric lighting (r51b): ray traced sun gate on %llu of 600 marches, "
                            "BB_VOLUMETRIC_RT_GATE %u%s (0 of 600: no ray traced scene, stage A "
                            "only)\n",
                            static_cast<unsigned long long>(gate_traced), gate_knob,
                            VolumetricOcclusion::RtGateByDefault() ? " (the default)" : "");
            }
            // bbport (r76_sun-fog-outdoors): once, at the first 600 marches none of which had a
            // scene (marches during a load lack one too, so not at the first march without one)
            if (gate_traced == 0 && !gate_failed && !gate_off_said) {
                gate_off_said = true;
                std::printf("Volumetric lighting (r76): no ray traced scene in 600 marches "
                            "(effect_ray_tracing off, or the ray traced sun, lamps and bounced "
                            "light all off): the sun fog is not gated and can show indoors, as "
                            "before r76\n");
            }
            gate_traced = 0;
        }
    }
    // bbport (r76_sun-fog-outdoors): the light's direction (SayLight, host only); the probe's line
    // once the GPU is past its copy; BB_VOLUMETRIC_GATE_PROBE / _VIEW (said at the first march and,
    // bbport (r84_live-test-knobs), again at each change through the live knobs file): the
    // gate's DIAG build runs on a probe march (the 120th gated march, then every 600th) and, with
    // the view, on every gated march. Both off: nothing below changes the gate or the march.
    const bool probe_knob = VolumetricOcclusion::GateProbe();
    const bool view_knob = VolumetricOcclusion::GateView();
    // bbport (r84_live-test-knobs): either changed through the live knobs file: the line below is
    // said again (or that both are off now), and a probe that comes on probes after 120 gated
    // marches, as at the start
    if (probe_knob != probe_knob_seen || view_knob != view_knob_seen) {
        if (!probe_knob && !view_knob) {
            std::printf("Volumetric lighting (r84): gate probe and gate view off (live knobs)\n");
        }
        if (probe_knob && !probe_knob_seen) {
            probe_marches = 0;
            probe_due = 120;
        }
        probe_knob_seen = probe_knob;
        view_knob_seen = view_knob;
        diag_said = false;
    }
    if (live_strength > 0.0f) {
        SayLight();
        if ((probe_knob || view_knob) && !diag_said) {
            diag_said = true;
            std::printf("Volumetric lighting (r76): gate probe %s (BB_VOLUMETRIC_GATE_PROBE), gate "
                        "view %s (BB_VOLUMETRIC_GATE_VIEW); they act only on marches the gate runs "
                        "on\n",
                        probe_knob ? "on" : "off", view_knob ? "on" : "off");
        }
    }
    if (probe_pending && scheduler.IsFree(probe_tick)) {
        ReadGateProbe();
    }
    const bool diag = gated && (probe_knob || view_knob) && DiagReady();
    bool probing = false;
    if (diag && probe_knob && !probe_pending && ++probe_marches >= probe_due) {
        probing = true;
        probe_marches = 0;
        // bbport (r76c_sun-fog-shells): 600 unless BB_VOLUMETRIC_GATE_PROBE_EVERY says otherwise
        probe_due = VolumetricOcclusion::GateProbeEvery();
        if (sun_scene_table) {
            probe_table = *sun_scene_table;
        } else {
            probe_table.clear();
        }
        // bbport (r76c_sun-fog-shells): their captures, when they match the table
        if (sun_scene_captures && sun_scene_captures->size() == probe_table.size()) {
            probe_caps = *sun_scene_captures;
        } else {
            probe_caps.clear();
        }
        probe_light = sun_light;
        probe_mask = sun_scene_mask;
    }
    const bool viewing = diag && view_knob && EnsureGateView();
    view_drawn = viewing;
    // bbport (r82_wind-stage1): with BB_WIND=1 and a camera at this call (SetWind, for this call
    // only) the WIND builds march (made here the first time); otherwise the plain ones, which get
    // the same 32 bytes as before. A march the gate view draws (BB_VOLUMETRIC_GATE_VIEW=1) does
    // not drift, nor an area gate march (r81_sun-fog-no-rt): it binds the AREA build, whose
    // layout takes the plain 32 bytes.
    const bool wind_wanted = std::exchange(wind_fog.on, false);
    const bool drift = wind_wanted && !viewing && !area && WindPasses(gated);
    wind_fog.used = drift;
    // bbport (r94_fog-noise): a march with the fog noise (FogNoiseMarch) binds the NOISE build of
    // the pass it would bind (plain, gated, area gate or both) and pushes NoiseParams. `wind_push`
    // keeps r82's name for the bytes pushed: NoiseParams, WindParams while drifting, else Params
    // (each starts with Params). Never noise and drift both: SetFogNoise took back SetWind's
    // request, and a march without a camera has neither.
    const bool noise = FogNoiseMarch(viewing, gated, area && !viewing);
    const PushBlock wind_push =
        noise ? PushBlock::Of(NoiseParams{params, FogNoiseTail()})
              : PushBlock::Of(WindParams{params, wind_fog.view_to_world, wind_fog.off1,
                                         wind_fog.off2});
    const u32 push_size = noise   ? u32(sizeof(NoiseParams))
                          : drift ? u32(sizeof(WindParams))
                                  : u32(sizeof(Params));
    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2 on an area gate march with the ray
    // traced gate: the DUAL builds (DualReady), not while the gate's probe or view runs (their DIAG
    // build has no wider answer) or the fog noise does (no DUAL build of it): r85's rule there
    const bool dual = area && !viewing && gated && area_mode == 2 && !diag && !noise && DualReady();
    gate_dual_on = dual;
    if (live_strength > 0.0f) {
        SayAreaMode(area_mode, area && !viewing, gated, dual);
    }
    const vk::DescriptorImageInfo goi{*gate_sampler, dual ? *gate_open_view : *gate_view,
                                      vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo gi{*gate_sampler, *gate_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): each column's first open slice, read with four gathers
    const vk::DescriptorImageInfo gfi{*gate_sampler, *gate_first_view, vk::ImageLayout::eGeneral};
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1: the view's image and the bands
    const vk::DescriptorImageInfo gvo{{}, *gate_view_image_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo gbi{*gate_sampler, *gate_band_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo di{*sampler, depth.imageView, depth.imageLayout};
    const vk::DescriptorImageInfo si{*sampler, in.shadow_map, in.shadow_layout};
    const vk::DescriptorImageInfo out{{}, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo repaired{{}, *repair_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo zout{{}, *depth_view, vk::ImageLayout::eGeneral};
    scheduler.Record([image = vk::Image(point_fog)](vk::CommandBuffer cmd) {
        const vk::ImageMemoryBarrier2 barrier{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eClear,
            .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image, .subresourceRange = ColorRange,
        };
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
        cmd.clearColorImage(image, vk::ImageLayout::eGeneral,
                            vk::ClearColorValue{std::array<float, 4>{}}, ColorRange);
    });
    // bbport (r76_sun-fog-outdoors): the gate after the lamp fog image's clear (before it in r51b),
    // so that the gate's profile row holds the gate's work alone
    if (gated) {
        RecordGate(in, in.constants_offset_word, probing, viewing, di);
        // bbport (r105_cloud-shadows): the clouds into the gate's cells (null when off)
        if (auto* clouds = CloudShadow::Active()) {
            clouds->Gate(in, *gate_view, GateWidth, GateHeight, GateSlices, reach);
        }
    }
    sun_scene = vk::AccelerationStructureKHR{};
    sun_scene_table = nullptr;
    sun_scene_captures = nullptr; // bbport (r76c_sun-fog-shells)
    for (u32 pass_index = 0; pass_index < 2; ++pass_index) {
        const bool repairing = pass_index == 1;
        // bbport (r51b_volumetric-rt-check): the builds reading the gate (binding 6, repair 7)
        const auto& plain_pass = repairing ? (gated ? repair_gated : repair)
                                           : (gated ? (viewing ? integrate_gated_view : integrate_gated)
                                                    : integrate);
        // bbport (r82_wind-stage1): the WIND build of the same pass while the fog drifts
        const auto& pass = !drift      ? plain_pass
                           : repairing ? (gated ? repair_gated_wind : repair_wind)
                                       : (gated ? integrate_gated_wind : integrate_wind);
        // bbport (r76_sun-fog-outdoors): pinned, so this row and the gate's always show together
        EffectPass::Mark(7, "volumetric sunlight", true);
        scheduler.RecordCrumb(
        {.name = repairing ? "Volumetric thin-surface repair" : "Directional volumetric integration"},
        [wind_push, push_size, di, si, out, repaired, zout, in, repairing, gi, gfi, gated,
         dual, goi, // bbport (r115_sun-fog-indoors)
         viewing = viewing && !repairing, gvo, gbi, view_image = vk::Image(gate_view_image),
         image = repairing ? vk::Image(repair_fog) : vk::Image(fog),
         zimage = vk::Image(depth_snapshot),
         w = repairing ? depth_width : width, h = repairing ? depth_height : height,
         // bbport (r81_sun-fog-no-rt): the AREA builds on an area gate march (same bindings);
         // bbport (r85_area-with-rt-gate): by (gated, repairing), with the ray traced gate the
         // AREA+GATE builds (the GATE builds' bindings, which `gated` writes below); never on a
         // march the gate view draws (`viewing` in these initializers is Integrate's)
         // bbport (r94_fog-noise): with the fog noise the NOISE build of that pass (its bindings)
         pipeline = *(noise              ? NoisePass(gated, area && !viewing, repairing)
                      : area && !viewing ? AreaPass(gated, repairing, dual)
                                         : pass).pipeline,
         layout = *(noise              ? NoisePass(gated, area && !viewing, repairing)
                    : area && !viewing ? AreaPass(gated, repairing, dual)
                                       : pass).layout](
            vk::CommandBuffer cmd) {
            Before(cmd);
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ColorRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            if (!repairing) {
                auto depth_barrier = barrier;
                depth_barrier.image = zimage;
                cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1,
                                      .pImageMemoryBarriers = &depth_barrier});
            }
            if (viewing) { // bbport (r76_sun-fog-outdoors): written whole by the march
                auto view_barrier = barrier;
                view_barrier.image = view_image;
                cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1,
                                      .pImageMemoryBarriers = &view_barrier});
            }
            const vk::DescriptorBufferInfo cb{in.constants, in.constants_offset, in.constants_range};
            const vk::DescriptorBufferInfo ub{in.uniforms, in.uniforms_offset, in.uniforms_range};
            std::array<vk::WriteDescriptorSet, 10> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cb},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ub},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &di},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &si},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage,
                 .pImageInfo = repairing ? &repaired : &out},
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &zout},
                {.dstBinding = 6, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
            }};
            // bbport (r51b_volumetric-rt-check): the gate after the pass's own bindings
            u32 count = repairing ? 7u : 6u;
            if (gated) {
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gi};
                ++count;
                // bbport (r76_sun-fog-outdoors): and each column's first open slice
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gfi};
                ++count;
                // bbport (r115_sun-fog-indoors): a DUAL build's wider answer (binding 8, repair 9)
                if (dual) {
                    writes[count] = vk::WriteDescriptorSet{
                        .dstBinding = count, .descriptorCount = 1,
                        .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                        .pImageInfo = &goi};
                    ++count;
                }
            }
            if (viewing) { // bbport (r76_sun-fog-outdoors): the GATE_VIEW build's 8 and 9
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &gvo};
                ++count;
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gbi};
                ++count;
            }
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), count});
            // bbport (r82_wind-stage1): Params (32 bytes) or, drifting, WindParams (its head is Params)
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, push_size, &wind_push);
            cmd.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            After(cmd);
        });
    }
    // bbport (r81_sun-fog-no-rt): AreaGate is owed at the directional draw; bbport
    // (r85_area-with-rt-gate): not after a march the gate view drew (it bound no AREA build)
    area_pending = area && !viewing;
    area_near_pending = area_mode == 2; // bbport (r115_sun-fog-indoors): AreaGate's flags
    area_dual_pending = dual;
    ready = true;
}

void VolumetricLight::Tint(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes) {
    if (!ready || tinted || !Enabled()) return;
    constexpr u32 RecordBytes = 72 * sizeof(float);
    if (!lighting.buffer || lighting.range < offset_bytes + RecordBytes) {
        failed = true;
        std::printf("Volumetric lighting: unexpected directional lighting table; off\n");
        return;
    }
    // BB_VOLUMETRIC_STEADY=0 (More > Engine > Steady sunlight color): the color as it was before the
    // fallback record was skipped and the fade added.
    static const bool steady = [] {
        const char* env = std::getenv("BB_VOLUMETRIC_STEADY");
        return !(env && env[0] == '0');
    }();
    const auto now = std::chrono::steady_clock::now();
    const float seconds = std::chrono::duration<float>(now - tint_time).count();
    tint_time = now;
    const TintParams params{
        offset_bytes, u32(std::min<vk::DeviceSize>((lighting.range - offset_bytes) / RecordBytes, 256)),
        steady && seconds <= TintSnapAfter ? 1.0f - std::exp(-seconds / TintFadeConstant) : 1.0f,
        steady ? 1u : 0u,
        // bbport: one GPU thread per record and a reduction in shared memory, which picks the
        // same record bit for bit. The old single thread walked the records one load round trip
        // after another while the GPU waited (0.09-0.13 ms with ray tracing on). Experiment bit
        // 134217728 restores it.
        BbToggle::Experiment(134217728) ? 1u : 0u};
    static int tint_serial_reported = -1;
    if (tint_serial_reported != int(params.serial)) {
        tint_serial_reported = int(params.serial);
        std::printf("Volumetric lighting: tint over %u records, %s\n", params.record_count,
                    params.serial ? "one thread for all (old)" : "one thread per record");
    }
    scheduler.EndRendering();
    const vk::DescriptorBufferInfo state{tint_state->Handle(), 0, 16};
    EffectPass::Mark(8, "volumetric tint");
    scheduler.RecordCrumb(
        {.name = "Resolved directional volumetric tint"},
        [params, lighting, state, pipeline = *tint.pipeline,
         layout = *tint.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 2> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &lighting},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch(1, 1, 1);
            After(cmd);
        });
    tinted = true;
    if (!tint_reported) {
        tint_reported = true;
        std::printf("Volumetric lighting: resolved primary diffuse RGB, %u region records\n",
                    params.record_count);
        std::printf("Volumetric lighting: steady sunlight color %s\n", steady ? "on" : "off");
    }
}

void VolumetricLight::AddPointLights(const u32* constants, const u32* lights, u32 count) {
    if (!ready || !Enabled() ||
        !BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
        return;
    }
    if (fog_lights.Empty()) {
        std::copy_n(constants, fog_matrix.size(), fog_matrix.begin());
    }
    fog_lights.Add(lights, count);
}

// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS=1, 2 or 3 only, made at the first lamp fog
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
                   LAMP_FOG_SHAFT_MAP_COMP, sizeof(LampFogShaftCap::MapPush), // bbport (r106)
                   "Lamp fog shaft maps") &&
        CreatePass(point_shafts,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
                    eCombinedImageSampler, eStorageBuffer}, // bbport (r106): 5 the table
                   march, 6 * sizeof(u32), "Point volumetric (shafts)"); // bbport (r106c): + shaft_fast
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
    // bbport (r106_lamp-fog-shaft-cap): the table both passes read (PlanShafts fills it)
    shaft_table = std::make_unique<VideoCore::Buffer>(instance, 0, LampFogShaftCap::TableBytes,
                                                      VideoCore::MemoryType::DeviceLocal,
                                                      "Lamp fog shaft table");
    return true;
}

// bbport (r106_lamp-fog-shaft-cap): BB_LAMP_FOG_SHAFTS set, each frame RecordShafts runs: which
// lamps get a map this frame within the ray budget (lamp_fog_shaft_cap.h; BB_LAMP_FOG_SHAFTS_RAYS
// read once). The table both passes read goes to `table`, the frame is added to the r106
// line's sums, and the first call says the cap once. Returns the maps to build this frame.
u32 VolumetricLight::PlanShafts(const std::vector<u32>& data, u32 count, std::vector<u32>& table) {
    const u32 level = LampFogShafts::Level();
    const u64 budget = LampFogShaftCap::Budget(LampFogShaftCap::Rays(), level);
    const u32 maps = LampFogShaftCap::MapsPerFrame(budget, level);
    const u64 per_map = LampFogShaftCap::RaysPerMap(level);
    if (!std::exchange(shaft_cap_said, true)) {
        std::printf("Volumetric lighting (r106): lamp fog shaft cap: at most %u maps of %ux%u a "
                    "frame, %llu map rays (BB_LAMP_FOG_SHAFTS_RAYS budget %llu%s); maps kept, %u "
                    "still lamps rebuilt a frame oldest first, new and moving first; over "
                    "budget a lamp fades to unshadowed fog in %.2f s\n",
                    maps, LampFogShafts::MapSize(level), LampFogShafts::MapSize(level),
                    static_cast<unsigned long long>(maps * per_map),
                    static_cast<unsigned long long>(budget),
                    LampFogShaftCap::Rays() == 0 ? ", the default" : "",
                    LampFogShaftCap::RefreshPerFrame, double(LampFogShaftCap::FadeOut));
    }
    const auto now = std::chrono::steady_clock::now();
    const float seconds =
        shaft_time == std::chrono::steady_clock::time_point{}
            ? 0.0f
            : std::clamp(std::chrono::duration<float>(now - shaft_time).count(), 0.0f, 0.1f);
    shaft_time = now;
    std::array<float, 16> inverse_projection{};
    for (u32 i = 0; i < 16; ++i) {
        inverse_projection[i] = std::bit_cast<float>(data[i]);
    }
    const u32 lights = std::min(count, LampFogShafts::MaxMaps);
    std::vector<LampFog::Light> records(lights);
    for (u32 i = 0; i < lights; ++i) {
        std::copy_n(data.begin() + FogLightsAt / 4 + i * 16, 16, records[i].begin());
    }
    const LampFogShaftCap::Plan plan =
        shaft_planner.Run(records, fog_camera, inverse_projection, seconds, maps);
    table = LampFogShaftCap::MakeTable(plan, fog_camera.view_to_world);
    shaft_totals.Add(plan, per_map);
    return u32(plan.jobs.size());
}

// bbport (r80_lamp-fog-shafts): in place of RecordLampFog's pass while the shafts run: the light
// records to the GPU as there, the shadow maps PlanShafts picks (r106; a pinned profile row
// of their own, "Lighting: lamp fog shafts"), then the march's SHAFTS build under the lamp fog's
// row. `data`, `constants`, `records`, `depth` and `out` are RecordLampFog's.
void VolumetricLight::RecordShafts(vk::AccelerationStructureKHR shaft_scene, u32 count,
                                   float intensity, float glow_size, std::vector<u32> data,
                                   const vk::DescriptorBufferInfo& constants,
                                   const vk::DescriptorBufferInfo& records,
                                   const vk::DescriptorImageInfo& depth,
                                   const vk::DescriptorImageInfo& out, u32 w, u32 h) {
    // bbport (r106_lamp-fog-shaft-cap): lamp_fog_shaft_map.comp's push constants (the frame's
    // map jobs, the mask, the blind sphere, the camera's world to view rows)
    using MapParams = LampFogShaftCap::MapPush;
    struct PointParams { // point_volumetric.comp Params with SHAFTS
        u32 count;
        float intensity, glow_size;
        float shaft_bias;
        u32 shaft_segments;
        u32 shaft_fast; // bbport (r106c_shaft-march-cheaper): 1 the fast march, 0 r106's
    };
    static_assert(sizeof(PointParams) == 24);
    // bbport (r106_lamp-fog-shaft-cap): the frame's plan (PlanShafts): the table both passes
    // read and, as `layers`, the maps built this frame (at most LampFogShaftCap::MapsPerFrame);
    // `kept`: the maps' image already holds layers of earlier frames (General layout)
    std::vector<u32> table;
    const u32 layers = PlanShafts(data, count, table);
    const MapParams map_params{layers, LampFogShafts::SceneMask, LampFogShafts::Clearance, 0.0f,
                               fog_camera.world_to_view};
    const vk::Buffer table_buffer = shaft_table->Handle();
    const vk::DescriptorBufferInfo table_info{table_buffer, 0, LampFogShaftCap::TableBytes};
    const bool kept = std::exchange(shaft_maps_kept, true);
    // bbport (r106c_shaft-march-cheaper): BB_LAMP_FOG_SHAFTS_FAST, asked again each frame (a live
    // knob with the test tools); Frame() says it when it changes and counts the frame
    const u32 shaft_segments = LampFogShafts::Segments(LampFogShafts::Level());
    const PointParams params{count, intensity, glow_size, LampFogShafts::Bias, shaft_segments,
                             LampFogShaftSmooth::Pack(LampFogShaftFast::Frame(count, shaft_segments, w, h))};
    const vk::Buffer buffer = fog_data->Handle();
    const vk::DeviceSize data_bytes = data.size() * sizeof(u32); // before the capture moves `data`
    const vk::DescriptorImageInfo maps_out{{}, *shaft_maps_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo maps_in{*sampler, *shaft_maps_view, vk::ImageLayout::eGeneral};
    const u32 groups = shaft_size / 8; // lamp_fog_shaft_map.comp: 8x8 texels a workgroup
    // bbport (r88_wind-lamp-fog): drifting (RecordLampFog's decision), the SHAFTS build with WIND
    // (the same bindings and push constants; the wind words are in `constants`). If it cannot be
    // made, these shafts stay even (counted as even in the "Wind lamp fog (r88)" line).
    const bool shafts_drift = lamp_wind.drift && LampWindPasses(true, LampFogShafts::Level());
    lamp_wind.drifted += shafts_drift ? 1 : 0;
    lamp_wind.shafts_drifted += shafts_drift ? 1 : 0;
    lamp_wind.even += (lamp_wind.drift && !shafts_drift) ? 1 : 0;
    EffectPass::Mark(80, "lamp fog shafts", true);
    scheduler.RecordCrumb(
        {.name = "Lamp fog shaft maps"},
        [map_params, table_info, maps_out, buffer, data_bytes, data = std::move(data), groups, layers,
         table = std::move(table), table_buffer, kept, // bbport (r106_lamp-fog-shaft-cap)
         scene = shaft_scene, image = vk::Image(shaft_maps), pipeline = *shaft_map.pipeline,
         layout = *shaft_map.layout](vk::CommandBuffer cmd) {
            const vk::MemoryBarrier2 to_transfer{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
            cmd.updateBuffer(buffer, 0, data_bytes, data.data());
            // bbport (r106_lamp-fog-shaft-cap): the table; then only this frame's map jobs: the
            // other layers keep what earlier frames wrote. No job and the maps kept: nothing more
            // (the march's Before orders both uploads before its reads).
            cmd.updateBuffer(table_buffer, 0, LampFogShaftCap::TableBytes, table.data());
            if (layers == 0 && kept) {
                return;
            }
            Before(cmd);
            // The layers of this frame's jobs are written whole; the march reads only layers
            // written in this or an earlier frame (PlanShafts).
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                // bbport (r106_lamp-fog-shaft-cap): Undefined only the first time: kept layers
                .oldLayout = kept ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ShaftRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const std::array<vk::WriteDescriptorSet, 3> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table_info},
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
        [params, constants, records, depth, out, maps_in, table_info, w, h, // bbport (r106)
         pipeline = shafts_drift ? *point_shafts_wind.pipeline // bbport (r88_wind-lamp-fog)
                                 : *point_shafts.pipeline,
         layout = shafts_drift ? *point_shafts_wind.layout
                               : *point_shafts.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 6> writes{{ // bbport (r106): 5 the table
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
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table_info},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            After(cmd);
        });
}

void VolumetricLight::RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h) {
    const auto& settings = BbSettings::Get();
    const float intensity = settings.graphics_point_fog_intensity.load(std::memory_order_relaxed);
    if (lights.empty() || !(intensity > 0.0f) || !std::isfinite(intensity)) {
        return;
    }
    const float glow = settings.graphics_point_fog_glow_size.load(std::memory_order_relaxed);
    std::vector<u32> data(FogLightsAt / sizeof(u32) + lights.size() * 16);
    std::copy(fog_matrix.begin(), fog_matrix.end(), data.begin());
    // bbport (r88_wind-lamp-fog): BB_WIND=1: whether this lamp fog drifts (LampWindDrift); if it
    // does, the wind words of fog_data (lamp_wind_layout.h: words 16-35, free: the lights start at
    // FogLightsAt) carry the composite camera's view to world rows (fog_camera, as LampFog::Memory
    // uses it), the noise offsets in cells and the contrast in off1's .w, for the WIND builds of
    // point_volumetric.comp; the constants range below then takes them too. Off: nothing written,
    // range 64.
    lamp_wind.drift = LampWindDrift(u32(lights.size()));
    if (lamp_wind.drift) {
        u32* const words = data.data() + LAMP_WIND_AT;
        for (u32 i = 0; i < 3 * LAMP_WIND_ROW; ++i) {
            words[i] = std::bit_cast<u32>(fog_camera.view_to_world[i]);
        }
        for (u32 i = 0; i < 3; ++i) {
            words[3 * LAMP_WIND_ROW + i] = std::bit_cast<u32>(lamp_wind.off1[i]);
            words[4 * LAMP_WIND_ROW + i] = std::bit_cast<u32>(lamp_wind.off2[i]);
        }
        words[3 * LAMP_WIND_ROW + 3] = std::bit_cast<u32>(lamp_wind.contrast);
        words[4 * LAMP_WIND_ROW + 3] = 0;
    }
    for (u32 i = 0; i < lights.size(); ++i) {
        std::copy(lights[i].begin(), lights[i].end(), data.begin() + FogLightsAt / 4 + i * 16);
    }
    struct PointParams {
        u32 count;
        float intensity;
        float glow_size; // Inverse-square core as a fraction of the light's radius.
    };
    const PointParams params{u32(lights.size()), std::clamp(intensity, 0.0f, 3.0f),
                             std::isfinite(glow) ? std::clamp(glow, 0.03f, 0.20f) : 0.08f};
    const vk::Buffer buffer = fog_data->Handle();
    // bbport (r88_wind-lamp-fog): drifting, the WIND build reads the wind words too
    const vk::DescriptorBufferInfo constants{buffer, 0, lamp_wind.drift ? LampWindBytes : 64u};
    const vk::DescriptorBufferInfo records{buffer, FogLightsAt, lights.size() * 64};
    const vk::DescriptorImageInfo depth{*sampler, *depth_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo out{{}, *point_view, vk::ImageLayout::eGeneral};
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
                        "%ux%u ray traced shadow map per lamp fog light, built within the r106 cap "
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
                        "this frame %u lights, %llu map rays without the r106 cap\n",
                        static_cast<unsigned long long>(shafts_shadowed), params.count,
                        static_cast<unsigned long long>(
                            shadowed ? LampFogShafts::MapRays(shaft_level, params.count) : 0));
            shafts_frames = shafts_shadowed = 0;
            // bbport (r106_lamp-fog-shaft-cap): the cap's line, a line of its own (the slot runs
            // keep 300 characters of a line): over the frames planned since the last line
            // (LampFogShaftCap::Totals): map rays a frame on average and at most, against the
            // cap (maps a frame x one map's rays); lamps a frame on average with a map built that
            // frame, drawn with a kept map, over budget (wanting a map, getting none), the most
            // over budget in one frame; frames without a camera (nothing shadowed)
            const auto& totals = shaft_totals;
            const double planned = double(std::max<u64>(totals.frames, 1));
            const u64 cap = LampFogShaftCap::MapsPerFrame(
                                LampFogShaftCap::Budget(LampFogShaftCap::Rays(), shaft_level),
                                shaft_level) *
                            LampFogShaftCap::RaysPerMap(shaft_level);
            std::printf("Volumetric lighting (r106): shaft cap over %llu frames: map rays a frame "
                        "%.0f avg, %llu max, cap %llu; lamps a frame: %.1f fresh, %.1f reused, "
                        "%.1f over budget (%u max); %llu frames without a camera\n",
                        static_cast<unsigned long long>(totals.frames),
                        double(totals.rays) / planned,
                        static_cast<unsigned long long>(totals.rays_most),
                        static_cast<unsigned long long>(cap), double(totals.fresh) / planned,
                        double(totals.reused) / planned, double(totals.over) / planned,
                        totals.over_most, static_cast<unsigned long long>(totals.no_camera));
            shaft_totals = {};
            LampFogShaftFast::PrintLine(); // bbport (r106c_shaft-march-cheaper): a line of its own
            LampFogShaftSmooth::PrintLine(); // bbport (r80b_shafts-smooth-visible): a line of its own
        }
        if (shadowed) {
            RecordShafts(shaft_scene, params.count, params.intensity, params.glow_size,
                         std::move(data), constants, records, depth, out, w, h);
            return;
        }
    }
    lamp_wind.drifted += lamp_wind.drift ? 1 : 0; // bbport (r88_wind-lamp-fog): the counts' line
    EffectPass::Mark(9, "lamp fog");
    scheduler.RecordCrumb(
        {.name = "Lamp fog"},
        [params, constants, records, depth, out, buffer, data = std::move(data), w, h,
         pipeline = lamp_wind.drift ? *point_wind.pipeline : *point.pipeline, // bbport (r88)
         layout = lamp_wind.drift ? *point_wind.layout : *point.layout](vk::CommandBuffer cmd) {
            const vk::MemoryBarrier2 to_transfer{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
            cmd.updateBuffer(buffer, 0, data.size() * sizeof(u32), data.data());
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 4> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &records},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            After(cmd);
        });
}

// bbport (r82_wind-stage1): the wind for the next Integrate (BB_WIND=1 only): the fog noise's
// offsets in cells and the G-buffer pass's view to world matrix as CameraMotion::PassMatrices
// gives it at this call. Without a camera that Integrate marches the plain way; counted. `show`
// is BB_WIND_SHOW (read once, by Rasterizer's WindShow). The first call logs the knobs.
void VolumetricLight::SetWind(const std::array<float, 3>& off1, const std::array<float, 3>& off2,
                              const std::array<float, 12>& view_to_world, bool camera_valid,
                              bool show) {
    const WindKnobs& knobs = WindFogKnobs();
    if (!wind_fog.wanted) {
        std::printf("Wind fog (r82, BB_WIND=1): the sun fog drifts with the wind while the "
                    "volumetric sunlight is on; contrast %.2f (BB_WIND_FOG), view %d "
                    "(BB_WIND_VIEW), show %d (BB_WIND_SHOW)\n",
                    double(knobs.contrast), knobs.view ? 1 : 0, show ? 1 : 0);
    }
    wind_fog.wanted = true;
    wind_fog.show = show;
    wind_fog.on = camera_valid && !wind_fog.failed;
    // bbport (r88_wind-lamp-fog): the lamp fog (Composite, later in this frame) drifts with the
    // same offsets; its camera is the composite's (SetCamera), so it takes no matrix here
    lamp_wind.wanted = true;
    lamp_wind.off1 = off1;
    lamp_wind.off2 = off2;
    if (!camera_valid) {
        ++wind_fog.no_camera;
        return;
    }
    wind_fog.view_to_world = view_to_world;
    wind_fog.off1 = {off1[0], off1[1], off1[2], WindFogContrastLive()}; // bbport (r87): TOOL, live
    wind_fog.off2 = {off2[0], off2[1], off2[2], knobs.view ? 1.0f : 0.0f};
}

// bbport (r82_wind-stage1): the WIND builds, made at the first Integrate that drifts (the gated
// two at the first gated one), so a game without BB_WIND=1 never makes them. If the plain two
// cannot be made the sun fog stays as without wind; if the gated two cannot, gated marches do.
bool VolumetricLight::WindPasses(bool gated) {
    using enum vk::DescriptorType;
    if (!wind_fog.tried) {
        wind_fog.tried = true;
        const bool made =
            CreatePass(integrate_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage},
                       VOLUMETRIC_LIGHT_INTEGRATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric integrate (wind)") &&
            CreatePass(repair_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},
                       VOLUMETRIC_LIGHT_REPAIR_WIND_COMP, sizeof(WindParams),
                       "Volumetric repair (wind)") &&
            (!WindFogKnobs().view ||
             CreatePass(composite_wind_view,
                        {eCombinedImageSampler, eCombinedImageSampler, eStorageImage,
                         eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
                        VOLUMETRIC_LIGHT_WIND_VIEW_COMP, sizeof(u32),
                        "Volumetric composite (wind view)"));
        wind_fog.failed = !made;
        std::printf(made ? "Wind fog (r82): drift builds made\n"
                         : "Wind fog (r82): the drift builds could not be made; the sun fog "
                           "marches as without wind\n");
    }
    if (wind_fog.failed) {
        return false;
    }
    if (gated && !wind_fog.gate_tried) {
        wind_fog.gate_tried = true;
        const bool made =
            CreatePass(integrate_gated_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_INTEGRATE_GATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric integrate (gate, wind)") &&
            CreatePass(repair_gated_wind,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_REPAIR_GATE_WIND_COMP, sizeof(WindParams),
                       "Volumetric repair (gate, wind)");
        wind_fog.gate_failed = !made;
        std::printf(made ? "Wind fog (r82): gated drift builds made\n"
                         : "Wind fog (r82): the gated drift builds could not be made; gated "
                           "marches do not drift\n");
    }
    return !gated || !wind_fog.gate_failed;
}

// bbport (r82_wind-stage1): with BB_WIND=1, at each composite: counts the frames that drifted and
// keeps the largest difference between the view to world matrix the march used (taken at
// Integrate) and the one SetCamera gave the composite (0: the G-buffer pass's camera did not
// change in between). With BB_WIND_SHOW=1 it prints them every 2 s and starts the counts again.
void VolumetricLight::WindFogCheck() {
    if (!wind_fog.wanted) {
        return;
    }
    if (wind_fog.used) {
        ++wind_fog.frames;
        if (fog_camera.valid) {
            ++wind_fog.compared;
            for (u32 i = 0; i < 12; ++i) {
                const float gap = std::abs(fog_camera.view_to_world[i] - wind_fog.view_to_world[i]);
                wind_fog.gap = std::max(wind_fog.gap, gap);
            }
        }
    }
    if (!wind_fog.show) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    if (now < wind_fog.next_line) {
        return;
    }
    if (wind_fog.next_line != std::chrono::steady_clock::time_point{}) {
        std::printf("Wind fog: %u frames drifted, %u marched without a camera (no drift), camera "
                    "at the march against at the composite: largest difference %.6f over %u "
                    "frames\n",
                    wind_fog.frames, wind_fog.no_camera, double(wind_fog.gap), wind_fog.compared);
    }
    wind_fog.next_line = now + std::chrono::seconds(2);
    wind_fog.frames = wind_fog.no_camera = wind_fog.compared = 0;
    wind_fog.gap = 0.0f;
}

// bbport (r88_wind-lamp-fog): with BB_WIND=1 (SetWind ran before this frame's march), at each lamp
// fog with lights: whether it drifts this frame. It does with a strength above 0, the plain WIND
// build made (LampWindPasses) and a camera from SetCamera (fog_camera); the SHAFTS one is asked
// for in RecordShafts. The first call reads BB_WIND_LAMP_FOG (BbWind::SanitizeLampFog: 0 to
// MaxLampFog; missing or not a number: DefaultLampFog) and says it once; at the 120th lamp fog
// frame and then every 600th a line of what the drift did. Without BB_WIND=1: false at once.
bool VolumetricLight::LampWindDrift(u32 lights) {
    if (!lamp_wind.wanted) {
        return false;
    }
    static const float lamp_strength = [] {
        const char* text = std::getenv("BB_WIND_LAMP_FOG");
        float value = BbWind::DefaultLampFog;
        if (text != nullptr && text[0] != 0) {
            char* end = nullptr;
            const float parsed = std::strtof(text, &end);
            value = end != text ? parsed : BbWind::DefaultLampFog;
        }
        return BbWind::SanitizeLampFog(value);
    }();
    lamp_wind.contrast = BbWind::LampFogContrast(lamp_strength);
    if (!std::exchange(lamp_wind.said, true)) {
        if (lamp_strength > 0.0f) {
            std::printf("Wind lamp fog (r88, BB_WIND=1): the lamp fog drifts with the sun fog's "
                        "noise, strength %.2f (BB_WIND_LAMP_FOG; contrast %.2f), one noise sample "
                        "per half chord of each light; lamp fog shafts %s\n",
                        double(lamp_strength), double(lamp_wind.contrast),
                        LampFogShafts::Level() == LampFogShafts::Off ? "off" : "on (both apply)");
        } else {
            std::printf("Wind lamp fog (r88, BB_WIND=1): strength 0 (BB_WIND_LAMP_FOG): the lamp "
                        "fog stays even (its pass without wind)\n");
        }
    }
    if (lamp_wind.frames == (lamp_wind.lines == 0 ? 120u : 600u)) {
        std::printf("Wind lamp fog (r88): %llu of %llu lamp fog frames drifted (%llu of them with "
                    "shafts), %llu without a camera, %llu even (strength 0 or no drift build); "
                    "this frame %u lights\n",
                    static_cast<unsigned long long>(lamp_wind.drifted),
                    static_cast<unsigned long long>(lamp_wind.frames),
                    static_cast<unsigned long long>(lamp_wind.shafts_drifted),
                    static_cast<unsigned long long>(lamp_wind.no_camera),
                    static_cast<unsigned long long>(lamp_wind.even), lights);
        ++lamp_wind.lines;
        lamp_wind.frames = lamp_wind.drifted = lamp_wind.shafts_drifted = 0;
        lamp_wind.no_camera = lamp_wind.even = 0;
    }
    ++lamp_wind.frames;
    if (!(lamp_strength > 0.0f) || !LampWindPasses(false, LampFogShafts::Off)) {
        ++lamp_wind.even;
        return false;
    }
    if (!fog_camera.valid) {
        ++lamp_wind.no_camera;
        return false;
    }
    return true;
}

// bbport (r88_wind-lamp-fog): the lamp fog's WIND builds, made at the first lamp fog that drifts
// (the SHAFTS one at the first drifting lamp fog with r80's shadow maps, VIEW for level 3), so a
// game without BB_WIND=1 or with strength 0 never makes them. If the plain one cannot be made the
// lamp fog stays even; if the SHAFTS one cannot, shadowed lamp fog does. Bindings and push
// constants are the plain builds' (RecordLampFog's pass, ShaftsReady's point_shafts).
bool VolumetricLight::LampWindPasses(bool shafts, u32 level) {
    using enum vk::DescriptorType;
    if (!lamp_wind.tried) {
        lamp_wind.tried = true;
        lamp_wind.failed =
            !CreatePass(point_wind,
                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
                        POINT_VOLUMETRIC_WIND_COMP, 3 * sizeof(u32), "Point volumetric (wind)");
        std::printf(lamp_wind.failed ? "Wind lamp fog (r88): the drift build could not be made; "
                                       "the lamp fog stays even\n"
                                     : "Wind lamp fog (r88): drift build made\n");
    }
    if (lamp_wind.failed) {
        return false;
    }
    if (shafts && !lamp_wind.shafts_tried) {
        lamp_wind.shafts_tried = true;
        const std::span<const u32> march =
            level == LampFogShafts::View
                ? std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP)
                : std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_WIND_COMP);
        lamp_wind.shafts_failed =
            !CreatePass(point_shafts_wind,
                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
                         eCombinedImageSampler, eStorageBuffer}, // bbport (r106): 5 the table
                        march, 6 * sizeof(u32), // bbport (r106c): + shaft_fast
                        "Point volumetric (shafts, wind)");
        std::printf(lamp_wind.shafts_failed
                        ? "Wind lamp fog (r88): the shafts drift build could not be made; the "
                          "shadowed lamp fog stays even\n"
                        : "Wind lamp fog (r88): shafts drift build made\n");
    }
    return !shafts || !lamp_wind.shafts_failed;
}

void VolumetricLight::Scene(VideoCore::ImageId color) {
    if (!ready || !Enabled() || !color) return;
    scene = color;
    scene_uid = texture_cache.GetImage(color).image_uid;
}

void VolumetricLight::Composite(VideoCore::ImageId fallback, const char* where) {
    const bool has_result = ready;
    const auto color_id = scene ? scene : fallback;
    const auto uid = scene ? scene_uid : (fallback ? texture_cache.GetImage(fallback).image_uid : 0);
    const bool has_tint = tinted;
    const auto seen_lights = fog_lights.Lights();
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_VIEW=1 and this frame's march wrote the view
    const bool gate_viewed = std::exchange(view_drawn, false);
    Reset();
    if (!has_result || !Enabled() || !color_id) return;
    WindFogCheck(); // bbport (r82_wind-stage1): returns at once without BB_WIND=1
    if (!has_tint) {
        failed = true;
        std::printf("Volumetric lighting: directional tint draw missing; off\n");
        return;
    }
    auto* color_ptr = texture_cache.TryGetImage(color_id, uid);
    if (!color_ptr) {
        failed = true;
        std::printf("Volumetric lighting: HDR scene expired before composite; off\n");
        return;
    }
    auto& color = *color_ptr;
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        failed = true;
        std::printf("Volumetric lighting: scene color is not RGBA16F; off\n");
        return;
    }
    scheduler.EndRendering();
    u32 w = color.info.size.width, h = color.info.size.height;
    vk::ImageView target_view{};
    if (scene_targets.Reduced() && scene_targets.EligibleScene(color)) {
        VideoCore::ImageViewInfo info;
        info.format = color.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, info, Compute,
            vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            failed = true;
            std::printf("Volumetric lighting: scene proxy lacks storage support; off\n");
            return;
        }
        w = scene_targets.Size().width;
        h = scene_targets.Size().height;
        target_view = proxy.view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            failed = true;
            std::printf("Volumetric lighting: scene lacks storage support; off\n");
            return;
        }
        const auto device = instance.GetDevice();
        target_view = Check<"create volumetric scene view">(device.createImageView({
            .image = color.GetImage(), .viewType = vk::ImageViewType::e2D,
            .format = color.info.pixel_format, .subresourceRange = ColorRange,
        }));
        scheduler.DeferOperation([device, target_view] { device.destroyImageView(target_view); });
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        runtime.FlushBarriers();
    }
    if (w != depth_width || h != depth_height) {
        failed = true;
        std::printf("Volumetric lighting: scene and shadow viewport sizes differ; off\n");
        return;
    }
    // bbport: BB_POINT_FOG_STEADY=0 draws the original fog (the first lights the game lists); on
    // unless 0. Read once: the launcher passes it at game start, like the engine's other switches.
    static const bool steady_fog = [] {
        const char* env = std::getenv("BB_POINT_FOG_STEADY");
        return !(env && env[0] == '0');
    }();
    if (!BbSettings::Get().effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) {
        fog_memory.Clear();
    } else if (!steady_fog) {
        fog_memory.Clear();
        if (!std::exchange(fog_mode_logged, true)) {
            std::printf("Lamp fog: steady fog off (draws the first %u lights the game lists)\n",
                        u32(LampFog::AsListedLimit));
        }
        RecordLampFog(LampFog::AsListed(seen_lights), w, h);
    } else {
        const auto now = std::chrono::steady_clock::now();
        // Bounded: a hitch or a menu without the scene should not count as the lights being gone.
        const float seconds = std::clamp(
            std::chrono::duration<float>(now - fog_memory_time).count(), 0.0f, 0.1f);
        fog_memory_time = now;
        // The memory fades lights at the limit; Select is the bound for the game's list as it is,
        // which the memory passes through without a camera.
        const auto drawn_lights = fog_memory.Update(seen_lights, fog_camera, seconds, FogMaxLights);
        const auto lamp_lights = LampFog::Select(drawn_lights, FogMaxLights);
        if (!std::exchange(fog_mode_logged, true)) {
            std::printf("Lamp fog: steady fog on (draws up to %u lights)\n", FogMaxLights);
        }
        RecordLampFog(lamp_lights.lights, w, h);
    }
    const vk::DescriptorImageInfo raw{*sampler, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo filtered{{}, *filtered_view, vk::ImageLayout::eGeneral};
    EffectPass::Mark(10, "volumetric filter");
    scheduler.RecordCrumb(
        {.name = "Directional volumetric filter"},
        [raw, filtered, image = vk::Image(filtered_fog), half_w = width, half_h = height,
         pipeline = *filter.pipeline, layout = *filter.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ColorRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            const std::array<vk::WriteDescriptorSet, 2> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &raw},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &filtered},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.dispatch((half_w + 7) / 8, (half_h + 7) / 8, 1);
            After(cmd);
        });
    const vk::DescriptorImageInfo fi{*sampler, *filtered_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo di{*sampler, *depth_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo out{{}, target_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo repaired{*sampler, *repair_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo points{*sampler, *point_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorBufferInfo state{tint_state->Handle(), 0, 16};
    if (!composite_reported) {
        composite_reported = true;
        std::printf("Volumetric lighting: composite into %ux%u HDR scene at %s\n", w, h, where);
    }
    // bbport (r76_sun-fog-outdoors): the view's image, for the composite's GATE_VIEW build
    const vk::DescriptorImageInfo gvi{*sampler, *gate_view_image_view, vk::ImageLayout::eGeneral};
    // bbport (r82_wind-stage1): BB_WIND_VIEW=1 shows the density factor this frame's march wrote
    const bool wind_view = !gate_viewed && wind_fog.used && WindFogKnobs().view;
    EffectPass::Mark(11, "volumetric composite");
    scheduler.RecordCrumb(
        {.name = "Directional volumetric composite"},
        [fi, di, out, repaired, points, state, w, h, gate_viewed, gvi,
         pipeline = gate_viewed ? *composite_view.pipeline
                    : wind_view ? *composite_wind_view.pipeline // bbport (r82_wind-stage1)
                                : *composite.pipeline,
         layout = gate_viewed ? *composite_view.layout
                  : wind_view ? *composite_wind_view.layout
                              : *composite.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 7> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &fi},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &di},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &repaired},
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &points},
                {.dstBinding = 6, .descriptorCount = 1, // bbport (r76_sun-fog-outdoors): GATE_VIEW
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gvi},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), gate_viewed ? 7u : 6u});
            cmd.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            After(cmd);
        });
}
}
