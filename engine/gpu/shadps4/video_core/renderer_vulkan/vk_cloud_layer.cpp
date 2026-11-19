// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): FEATURE, the volumetric cloud layer (vk_cloud_layer.h says what
// it is and where it runs; cloud_layer_params.h has the numbers, host_shaders/cloud_layer.comp the
// passes).

#include "video_core/renderer_vulkan/vk_cloud_layer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_CLOUD_LAYER_LIVE 1
#else
#define BB_CLOUD_LAYER_LIVE 0
#endif
#include "video_core/host_shaders/cloud_layer_composite_comp.h"
#include "video_core/host_shaders/cloud_layer_march_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_cloud_shadow.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace CL = CloudLayerParams;

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageBuffer = vk::DescriptorType::eStorageBuffer;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
/// The GPU profile row (BB_GPU_PROFILE=1): "Lighting: volumetric clouds", both passes.
constexpr u64 ProfileRow = 119;

/// The layer's knobs, read once (the first caller: Wanted, at the rasterizer's start).
const CL::Knobs& Load() {
    static const CL::Knobs knobs = CL::MakeKnobs(
        std::getenv("BB_VOLUMETRIC_CLOUDS"), std::getenv("BB_VOLUMETRIC_CLOUDS_COVER"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_DENSITY"), std::getenv("BB_VOLUMETRIC_CLOUDS_HEIGHT"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_SHOW"), std::getenv("BB_VOLUMETRIC_CLOUDS_THICK"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_STEPS"), std::getenv("BB_VOLUMETRIC_CLOUDS_SKYZ"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_SIZE"), std::getenv("BB_VOLUMETRIC_CLOUDS_SPEED"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_CONTRAST"), // bbport (r119e_clouds-real-sky)
        std::getenv("BB_VOLUMETRIC_CLOUDS_TINT"), std::getenv("BB_VOLUMETRIC_CLOUDS_SMEAR"), // bbport (r119g)
        std::getenv("BB_VOLUMETRIC_CLOUDS_PAINTED"), std::getenv("BB_VOLUMETRIC_CLOUDS_HORIZON"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_GLOWMAX"), // bbport (r119i_clouds-behind-painted-sky)
        std::getenv("BB_VOLUMETRIC_CLOUDS_SMOOTH")); // bbport (r119j_clouds-banding)
    return knobs;
}

/// The clock's knobs when the cloud shadows are off: the same variables, read as their
/// CloudShadows::MakeKnobs reads them (strength 0: only the size, the direction and the wind count).
const CloudShadows::Knobs& OwnKnobs() {
    static const CloudShadows::Knobs knobs = CloudShadows::MakeKnobs(
        nullptr, std::getenv("BB_CLOUD_SHADOWS_SCALE"), nullptr, std::getenv("BB_CLOUDS_DIR"),
        std::getenv("BB_WIND_DIR"), std::getenv("BB_WIND_SPEED"));
    return knobs;
}

/// bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT, read once: the frames between the periodic log
/// lines (0: the defaults, FramesFirst then FramesPeriod).
u32 ReportFrames() {
    static const u32 frames = CL::ReportFramesFrom(std::getenv("BB_VOLUMETRIC_CLOUDS_REPORT"));
    return frames;
}

/// BB_VOLUMETRIC_CLOUDS now: asked again at every use with the live knobs, else the start's value.
bool LiveOn() {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<bool> on{"BB_VOLUMETRIC_CLOUDS", CL::ParseOn};
    return on.Get();
#else
    return Load().on;
#endif
}

/// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST now: live knobs with the test tools' header
/// (asked again at every use), else the start's value.
float LiveSpeed([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> speed{"BB_VOLUMETRIC_CLOUDS_SPEED", CL::ParseSpeed};
    return speed.Get();
#else
    return at_start;
#endif
}

float LiveContrast([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> contrast{"BB_VOLUMETRIC_CLOUDS_CONTRAST", CL::ParseContrast};
    return contrast.Get();
#else
    return at_start;
#endif
}

/// bbport (r119g_clouds-smear-and-cover): BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR now (live knobs with the test
/// tools' header, asked again at every use), else the start's value.
float LiveCover([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> cover{"BB_VOLUMETRIC_CLOUDS_COVER", CL::ParseCover};
    return cover.Get();
#else
    return at_start;
#endif
}

float LiveTint([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> tint{"BB_VOLUMETRIC_CLOUDS_TINT", CL::ParseTint};
    return tint.Get();
#else
    return at_start;
#endif
}

bool LiveSmear([[maybe_unused]] bool at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<bool> smear{"BB_VOLUMETRIC_CLOUDS_SMEAR", CL::ParseSmear};
    return smear.Get();
#else
    return at_start;
#endif
}

/// bbport (r119i_clouds-behind-painted-sky): BB_VOLUMETRIC_CLOUDS_PAINTED, _HORIZON and _GLOWMAX now (live knobs with the test
/// tools' header, asked again at every use), else the start's value.
float LivePainted([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> painted{"BB_VOLUMETRIC_CLOUDS_PAINTED", CL::ParsePainted};
    return painted.Get();
#else
    return at_start;
#endif
}

float LiveHorizon([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> horizon{"BB_VOLUMETRIC_CLOUDS_HORIZON", CL::ParseHorizon};
    return horizon.Get();
#else
    return at_start;
#endif
}

float LiveGlow([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> glow{"BB_VOLUMETRIC_CLOUDS_GLOWMAX", CL::ParseGlow};
    return glow.Get();
#else
    return at_start;
#endif
}

/// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE and _MARK now: live knobs with the test tools'
/// header only; without it never frozen and no mark (the feature branch carries none of it).
bool LiveFreeze() {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<bool> freeze{"BB_VOLUMETRIC_CLOUDS_FREEZE", CL::ParseFreeze};
    return freeze.Get();
#else
    return false;
#endif
}

u32 LiveMark() {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<u32> mark{"BB_VOLUMETRIC_CLOUDS_MARK", CL::ParseMark};
    return mark.Get();
#else
    return 0;
#endif
}

/// bbport (r119j_clouds-banding): BB_VOLUMETRIC_CLOUDS_SMOOTH now (a live knob with the test tools' header, asked again at every
/// use), else the start's value.
u32 LiveSoften([[maybe_unused]] u32 at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<u32> soften{"BB_VOLUMETRIC_CLOUDS_SMOOTH", CL::ParseSoften};
    return soften.Get();
#else
    return at_start;
#endif
}

constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? "live knobs on" : "read at the start";

double Seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}

vk::WriteDescriptorSet WriteBuffer(u32 binding, const vk::DescriptorBufferInfo* buffer) {
    return {.dstBinding = binding, .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = buffer};
}
} // namespace

bool CloudLayer::Wanted() {
    return Load().on;
}

CloudLayer::CloudLayer(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{Load()}, live{Load()},
      shared{CloudShadow::Active()} {
    // The pipelines and the three small buffers are made here, at the start (no compile in play);
    // the march image at the first frame that draws, at that scene's size.
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, march_set_layout, march_layout, march_pipeline,
                              {StorageImage, StorageImage, SampledImage, StorageBuffer,
                               StorageBuffer},
                              sizeof(CL::Push), CLOUD_LAYER_MARCH_COMP, "Volumetric clouds march") &&
           EffectPass::Create(instance, composite_set_layout, composite_layout, composite_pipeline,
                              {StorageImage, StorageImage, SampledImage, StorageBuffer},
                              sizeof(CL::Push), CLOUD_LAYER_COMPOSITE_COMP,
                              "Volumetric clouds composite") &&
           MakeBuffer(params_buffer, sizeof(CL::Params), false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_buffer, CL::CounterWords * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferSrc |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_host, CL::CounterWords * 4, true,
                      vk::BufferUsageFlagBits::eTransferDst);
    if (made) {
        std::memset(counter_host.mapped, 0, CL::CounterWords * 4);
    }
    const CloudShadows::Knobs& clk = ClockKnobs();
    const CL::Slab slab = CL::MakeSlab(knobs);
    // under 300 characters (the slab runs keep that much of a line)
    BbReport::Printf("Volumetric clouds (r119, BB_VOLUMETRIC_CLOUDS=1): %s; slab %.0f-%.0f m, "
                     "cover %.2f, density %.2f, %d steps at 1/%d resolution, size %.0f m, %.1f m/s, "
                     "clock %s; drawn before the fog and the upscaler%s\n",
                     made ? "on" : "off - the passes could not be made", double(slab.base),
                     double(slab.Top()), double(knobs.cover), double(knobs.density), knobs.steps,
                     CL_DIV, double(knobs.size), double(CL::LayerSpeed(clk.Velocity(), knobs)),
                     shared ? "the cloud shadows'" : "its own (cloud shadows off)",
                     knobs.show ? "; SHOW" : "");
    // bbport (r119e_clouds-real-sky): the contrast and the live knobs, once (under 300 characters)
    BbReport::Printf("Volumetric clouds (r119e, BB_VOLUMETRIC_CLOUDS=1): contrast %.2f (undersides x%.2f, rims x%.2f), "
                     "BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST (%s)\n",
                     double(knobs.contrast), double(CL::ShadeScale(knobs.contrast)),
                     double(CL::LitScale(knobs.contrast)), LiveText);
    // bbport (r119g_clouds-smear-and-cover): under 300 characters
    BbReport::Printf("Volumetric clouds (r119g, BB_VOLUMETRIC_CLOUDS=1): smear fix %s (%d light taps, shade base %.2f, "
                     "horizon glow %.2f), sky tint %.2f; BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR (%s)\n",
                     knobs.smear ? "on" : "off (BB_VOLUMETRIC_CLOUDS_SMEAR=0)",
                     knobs.smear ? CL::LightTaps : 1, double(knobs.smear ? CL::ShadeBase : CL::OldShadeBase),
                     double(knobs.smear ? CL::HorizonGlow : 0.0f), double(knobs.tint), LiveText);
    // bbport (r119i_clouds-behind-painted-sky): under 300 characters
    BbReport::Printf("Volumetric clouds (r119i, BB_VOLUMETRIC_CLOUDS=1): behind the painted sky: shapes take back %.2f of the opacity (rings %.0f and %.0f px "
                     "at 1080 lines), full cloud from %.0f deg up, colour cap %.2f x the sky, speed x%.2f, tint %.2f; "
                     "BB_VOLUMETRIC_CLOUDS_PAINTED, _HORIZON, _GLOWMAX (%s)\n",
                     double(knobs.painted), double(CL::RingNear), double(CL::RingFar), double(knobs.horizon),
                     double(knobs.glow), double(knobs.speed), double(knobs.tint), LiveText);
    // bbport (r119j_clouds-banding): under 300 characters
    BbReport::Printf("Volumetric clouds (r119j, BB_VOLUMETRIC_CLOUDS=1): banding fix bits %u of 15 (1 hash jitter, 2 coverage edge a step wide, "
                     "4 graded painted rings, 8 soft colour knee; 0 = the r119i march); BB_VOLUMETRIC_CLOUDS_SMOOTH (%s)\n",
                     unsigned(knobs.soften), LiveText);
    if (ReportFrames() != 0) { // bbport (r119f_clouds-open-sky)
        BbReport::Printf("Volumetric clouds (r119f, BB_VOLUMETRIC_CLOUDS_REPORT): the log lines come every %u frames\n",
                         ReportFrames());
    }
}

CloudLayer::~CloudLayer() {
    const auto device = instance.GetDevice();
    FreeBuffer(params_buffer);
    FreeBuffer(counter_buffer);
    FreeBuffer(counter_host);
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool CloudLayer::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                            vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void CloudLayer::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}


const CloudShadows::State& CloudLayer::ClockState() const {
    return shared ? shared->ClockState() : own_state;
}

const CloudShadows::Knobs& CloudLayer::ClockKnobs() const {
    return shared ? shared->ClockKnobs() : OwnKnobs();
}

float CloudLayer::Direction() const {
    return ClockState().Direction();
}

float CloudLayer::Velocity() const {
    return ClockKnobs().Velocity();
}

bool CloudLayer::Active() {
    const bool on = LiveOn();
    if (on != told_on) {
        told_on = on;
        std::printf("Volumetric clouds (r119): %s (BB_VOLUMETRIC_CLOUDS, a live knob)\n",
                    on ? "on again" : "off");
    }
    return on;
}

void CloudLayer::ReadLive() {
    live.speed = LiveSpeed(knobs.speed);
    live.contrast = LiveContrast(knobs.contrast);
    // bbport (r119g_clouds-smear-and-cover): the cover, the tint and the smear fix, said once per change
    live.cover = LiveCover(knobs.cover);
    live.tint = LiveTint(knobs.tint);
    live.smear = LiveSmear(knobs.smear);
    // bbport (r119i_clouds-behind-painted-sky): the painted fade, the horizon and the glow cap, said once per change
    live.painted = LivePainted(knobs.painted);
    live.horizon = LiveHorizon(knobs.horizon);
    live.glow = LiveGlow(knobs.glow);
    // bbport (r119j_clouds-banding): the banding fixes' bits, said once per change
    live.soften = LiveSoften(knobs.soften);
    if (told_soften < 0) {
        told_soften = int(live.soften);
    } else if (int(live.soften) != told_soften) {
        told_soften = int(live.soften);
        std::printf("Volumetric clouds (r119j): live knob BB_VOLUMETRIC_CLOUDS_SMOOTH: %u (jitter %s, coverage edge %s, painted rings %s, "
                    "colour knee %s)\n",
                    unsigned(live.soften), (live.soften & CL_SMOOTH_JITTER) != 0u ? "on" : "off",
                    (live.soften & CL_SMOOTH_EDGE) != 0u ? "on" : "off", (live.soften & CL_SMOOTH_PAINT) != 0u ? "on" : "off",
                    (live.soften & CL_SMOOTH_GLOW) != 0u ? "on" : "off");
    }
    if (told_paint[0] < 0.0f) {
        told_paint = {live.painted, live.horizon, live.glow};
    } else if (live.painted != told_paint[0] || live.horizon != told_paint[1] || live.glow != told_paint[2]) {
        told_paint = {live.painted, live.horizon, live.glow};
        std::printf("Volumetric clouds (r119i): live knobs: painted fade %.2f, full cloud from %.0f deg up, colour cap %.2f\n",
                    double(live.painted), double(live.horizon), double(live.glow));
    }
    if (told_cover < 0.0f) {
        told_cover = live.cover;
        told_tint = live.tint;
        told_smear = live.smear ? 1 : 0;
    } else if (live.cover != told_cover || live.tint != told_tint || (live.smear ? 1 : 0) != told_smear) {
        told_cover = live.cover;
        told_tint = live.tint;
        told_smear = live.smear ? 1 : 0;
        std::printf("Volumetric clouds (r119g): live knobs: cover %.2f, tint %.2f, smear fix %s\n", double(live.cover),
                    double(live.tint), live.smear ? "on" : "off");
    }
    if (told_speed < 0.0f) {
        told_speed = live.speed;
        told_contrast = live.contrast;
        return;
    }
    if (live.speed != told_speed || live.contrast != told_contrast) {
        told_speed = live.speed;
        told_contrast = live.contrast;
        std::printf("Volumetric clouds (r119e): live knobs: speed x%.2f (%.1f m/s), contrast %.2f (undersides x%.2f, "
                    "rims x%.2f)\n",
                    double(live.speed), double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)),
                    double(live.contrast), double(CL::ShadeScale(live.contrast)),
                    double(CL::LitScale(live.contrast)));
    }
}

void CloudLayer::SetSunLight(const std::array<float, 3>& world, bool valid) {
    if (!valid || !std::isfinite(world[0]) || !std::isfinite(world[1]) ||
        !std::isfinite(world[2])) {
        return;
    }
    light = world;
    slope = CloudShadows::Slope(world);
    light_known = true;
}

vk::ImageView CloudLayer::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
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
        .aspect = aspect,
        .view = Check<"create cloud layer view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool CloudLayer::EnsureImage(u32 width, u32 height) {
    if (cloud_image && cloud_width == width && cloud_height == height) {
        return true;
    }
    if (width == refused_width && height == refused_height) {
        return false;
    }
    const vk::DeviceSize bytes = 8ull * width * height;
    if (!EffectPass::HasRoom(instance, bytes)) {
        refused_width = width;
        refused_height = height;
        std::printf("Volumetric clouds (r119): no room in video memory for its march image of "
                    "%ux%u (%llu bytes); asked again when the scene's size changes\n",
                    width, height, static_cast<unsigned long long>(bytes));
        return false;
    }
    refused_width = refused_height = 0;
    if (cloud_image) {
        scheduler.DeferOperation(
            [image = std::move(cloud_image), view = std::move(cloud_view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    cloud_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    cloud_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(cloud_image), "Volumetric clouds march image");
    cloud_view = Check<"create cloud layer march view">(device.createImageViewUnique({
        .image = vk::Image(cloud_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = ColorRange,
    }));
    cloud_width = width;
    cloud_height = height;
    std::printf("Volumetric clouds (r119): march image %ux%u RGBA16F (%llu bytes), 1/%d of a scene "
                "of %ux%u\n",
                width, height, static_cast<unsigned long long>(bytes), CL_DIV, width * CL_DIV,
                height * CL_DIV);
    return true;
}

void CloudLayer::OnFrameEnd(bool wind_on, float wind_deg) {
    if (!shared) {
        // The layer's own clock, stepped as CloudShadow::OnFrameEnd steps the cloud shadows' (the
        // same variables, so the same heading, speed and drift; the offsets start at 0 here).
        const double now = Seconds();
        const double seconds = clock_last < 0.0 ? 0.0 : now - clock_last;
        clock_last = now;
        own_state.Advance(OwnKnobs(), wind_on, wind_deg, light_known, light, seconds);
    }
    if (!Active()) {
        drew_this_frame = false;
        return;
    }
    ReadLive(); // bbport (r119e_clouds-real-sky): the live speed and contrast of this frame
    // bbport (r119c_clouds-gaps): the layer's own offsets move at the one wind's cloud heading and speed (the
    // weather's speed of this frame included) times BB_VOLUMETRIC_CLOUDS_SPEED; Drift clamps a long gap
    // bbport (r119h_clouds-freeze-sheet): TOOL: BB_VOLUMETRIC_CLOUDS_FREEZE=1 (live) gives the offsets a zero wind: Advance
    // keeps its clock and leaves the cells exactly as they are (advect and morph both stop). Not frozen: the call below
    // is the one it always was.
    frozen = LiveFreeze();
    if (frozen != told_frozen) {
        told_frozen = frozen;
        const std::array<float, 3> o = layer_drift.Cells(0);
        std::printf("Volumetric clouds (r119h): live knob BB_VOLUMETRIC_CLOUDS_FREEZE: %s; octave 0 offset %.4f %.4f %.4f cells\n",
                    frozen ? "on, the cloud offsets are held" : "off, the field moves again", double(o[0]), double(o[1]),
                    double(o[2]));
    }
    const u32 mark = LiveMark();
    if (mark != mark_told) {
        mark_told = mark;
        mark_totals = {};
        mark_skip = CL::MarkSkipFrames;
        mark_age = 0;
        mark_left = mark != 0 ? CL::MarkFrames : 0;
    }
    layer_drift.Advance(true, Seconds(),
                        frozen ? std::array<float, 3>{0.0f, 0.0f, 0.0f}
                               : CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), live),
                        live.size);
    ++stats.frames;
    if (drew_this_frame && counter_host.mapped) {
        // The totals the GPU copied after the last passes that finished (a frame or two old; one
        // word is never torn): added once a frame the passes were recorded.
        std::array<u32, CL::CounterWords> words{};
        std::memcpy(words.data(), counter_host.mapped, sizeof(words));
        totals.Add(words);
        if (mark_left > 0) { // bbport (r119h_clouds-freeze-sheet): the sheet mark's own sum
            if (mark_skip > 0) {
                --mark_skip;
            } else {
                mark_totals.Add(words);
                if (--mark_left == 0) {
                    ReportMark(mark_told);
                }
            }
        }
    }
    if (mark_left > 0 && ++mark_age >= CL::MarkTimeoutFrames) {
        ReportMark(mark_told);
    }
    drew_this_frame = false;
    if (!told_no_place && stats.reached == 0 && stats.frames >= CL::FramesNoPlace) {
        told_no_place = true;
        std::printf("Volumetric clouds (r119): not drawn - no frame reached the place before the "
                    "upscaler (BB_UPSCALER=none, or this GPU cannot run it)\n");
    }
    const u32 report_every = ReportFrames(); // bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT
    if (stats.frames >= (report_every != 0 ? report_every
                                           : (reported_once ? CL::FramesPeriod : CL::FramesFirst))) { // bbport (r119d): a first line early
        Report();
    }
}

void CloudLayer::Report() {
    reported_once = true;
    const CL::Shares s = CL::SharesOf(totals);
    const CloudShadows::State& state = ClockState();
    // two lines, each under 300 characters (r119c: the first has the visible share, the size and the speed)
    BbReport::Printf("Volumetric clouds (r119): sky px share %.3f, covered share %.3f, visible share %.3f, "
                     "mean opacity %.3f, march steps %.1f, heading %.0f deg, drift %.1f m/s, size %.0f m "
                     "(heading and speed same as the cloud shadows': %s)\n",
                     s.sky, s.covered, s.visible, s.opacity, s.steps, double(state.Direction()),
                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)), double(knobs.size),
                     shared ? "yes" : "no, they are off: the layer's own clock");
    const CL::Slab slab = CL::MakeSlab(knobs);
    BbReport::Printf("Volumetric clouds (r119): %u of %u frames drawn (%u reached the upscaler; %u "
                     "without a camera, %u without a usable scene, %u without memory), counters of "
                     "%llu frames, slab %.0f-%.0f m, camera y %.0f m, light %s%.0f deg up, "
                     "cover %.2f\n",
                     stats.drawn, stats.frames, stats.reached, stats.no_camera, stats.no_scene,
                     stats.no_memory, static_cast<unsigned long long>(totals.frames),
                     double(slab.base), double(slab.Top()), double(stats.camera_y),
                     light_known ? "" : "unknown, ",
                     light_known ? std::asin(std::clamp(double(light[1]), -1.0, 1.0)) *
                                       57.29577951308232
                                 : 0.0,
                     double(knobs.cover));
    // bbport (r119b_clouds-visible): the picture's depth (the first pixel of each march block), so a place whose
    // sky is not depth 1 shows its view z here; under 300 characters
    const std::array<double, CL::DepthBands> z = CL::DepthShares(totals);
    BbReport::Printf("Volumetric clouds (r119b): picture depth shares: depth 1 %.3f, then view z from %.0f m "
                     "%.3f, from %.0f %.3f, from %.0f %.3f, from %.0f %.3f, from %.0f %.3f, rest %.3f; "
                     "counted as sky from view z %.0f m (0: depth 1 only)\n",
                     z[0], double(CL::DepthEdges[0]), z[1], double(CL::DepthEdges[1]), z[2],
                     double(CL::DepthEdges[2]), z[3], double(CL::DepthEdges[3]), z[4],
                     double(CL::DepthEdges[4]), z[5], z[6], double(knobs.sky_z));
    // bbport (r119d_clouds-contrast): the contrast proof, under 300 characters
    BbReport::Printf("Volumetric clouds (r119d): of the visible cloud pixels %.3f are darker than %.1f of the sky behind "
                     "them and %.3f brighter than %.1f of it; edges %.2f-%.2f at cover %.2f, opacity cap %.2f, "
                     "drift %.1f m/s, contrast %.2f\n",
                     s.dark, double(CL_DARK_RATIO), s.bright, double(CL_BRIGHT_RATIO),
                     double(CL::CoverEdges(CL::LayerLow, CL::LayerHigh, knobs.cover).low),
                     double(CL::CoverEdges(CL::LayerLow, CL::LayerHigh, knobs.cover).high), double(knobs.cover),
                     double(CL::OpacityCap),
                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)),
                     double(live.contrast));
    BbReport::Printf("Volumetric clouds (r119g): cover %.2f, tint %.2f, smear fix %s\n", double(live.cover),
                     double(live.tint), live.smear ? "on" : "off"); // bbport (r119g_clouds-smear-and-cover)
    // bbport (r119i_clouds-behind-painted-sky): under 300 characters
    BbReport::Printf("Volumetric clouds (r119i): painted fade %.2f, full cloud from %.0f deg up, colour cap %.2f; painted share %.3f "
                     "(of the marched sky pixels, those whose opacity the painted sky took %.0f%% or more of), drift %.1f m/s\n",
                     double(live.painted), double(live.horizon), double(live.glow), s.painted,
                     double(CL_PAINTED_SHARE) * 100.0, double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)));
    // bbport (r119j_clouds-banding): under 300 characters
    BbReport::Printf("Volumetric clouds (r119j): banding fix bits %u of 15 (1 jitter, 2 coverage edge, 4 painted rings, 8 colour knee), "
                     "on in %u of %u drawn frames\n",
                     unsigned(live.soften), stats.smoothed, stats.drawn);
    {
        // bbport (r119h_clouds-freeze-sheet): where the drift comes from (under 300 characters): the wind's cloud speed held to
        // 2.5-8 m/s, times the SPEED knob (its floor 0.25), plus the morph, which the knob does not scale
        const float cloud_speed = ClockState().Velocity(ClockKnobs());
        const std::array<float, 3> o = layer_drift.Cells(0);
        BbReport::Printf("Volumetric clouds (r119h): drift: wind cloud speed %.1f m/s held %.1f-%.1f = %.1f, x speed knob %.2f = "
                         "%.2f m/s%s; morph one %.0f m cell per %.0f s (%.1f m/s equivalent, not scaled by the knob); "
                         "octave 0 offset %.4f %.4f %.4f cells\n",
                         double(cloud_speed), double(CL::DriftFloor), double(CL::DriftCeil),
                         double(CL::HeldSpeed(cloud_speed)), double(live.speed),
                         double(CL::LayerSpeed(cloud_speed, live)), frozen ? " (FROZEN: held at 0)" : "",
                         double(live.size), double(CloudShadows::MorphSeconds),
                         double(live.size) / double(CloudShadows::MorphSeconds), double(o[0]), double(o[1]), double(o[2]));
    }
    stats = {};
    totals = {};
}

/// bbport (r119h_clouds-freeze-sheet): the sheet mark's one line (under 300 characters): the shares of the frames since the
/// mark changed, the look knobs now and octave 0's offset (equal digits in two lines: the field stood still).
void CloudLayer::ReportMark(u32 mark) {
    const CL::Shares s = CL::SharesOf(mark_totals);
    const std::array<float, 3> o = layer_drift.Cells(0);
    BbReport::Printf("Volumetric clouds (r119h): sheet mark %u over %llu frames: sky px share %.3f, covered share %.3f, "
                     "visible share %.3f, mean opacity %.3f; cover %.2f, contrast %.2f, tint %.2f, smear fix %s, frozen %s, "
                     "octave 0 offset %.4f %.4f %.4f\n",
                     mark, static_cast<unsigned long long>(mark_totals.frames), s.sky, s.covered, s.visible, s.opacity,
                     double(live.cover), double(live.contrast), double(live.tint), live.smear ? "on" : "off",
                     frozen ? "yes" : "no", double(o[0]), double(o[1]), double(o[2]));
    mark_left = 0;
}

void CloudLayer::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                       std::array<float, 2> jitter) {
    if (!Active()) {
        return;
    }
    ++stats.reached;
    if (!made || !color_id || !depth_id) {
        ++stats.no_scene;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid) {
        ++stats.no_camera;
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.no_scene;
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        ++stats.no_scene;
        return;
    }
    const u32 march_width = (width + CL_DIV - 1) / CL_DIV;
    const u32 march_height = (height + CL_DIV - 1) / CL_DIV;
    if (!EnsureImage(march_width, march_height)) {
        ++stats.no_memory;
        return;
    }
    const SceneUseScope scene_use{"volumetric clouds"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // Every value is made before the capture list (nothing in it is moved).
    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, layer_drift, live, light,
                                             light_known, slope, jitter); // bbport (r119c): own drift
    CL::Push push;
    push.width = width;
    push.height = height;
    push.frame = frame_index++;
    push.flags = (knobs.show ? u32(CL_FLAG_SHOW) : 0u) | CL::SoftenFlags(live.soften); // bbport (r119j_clouds-banding)
    stats.camera_y = camera.inv_view[7];
    ++stats.drawn;
    if (live.soften != 0u) ++stats.smoothed; // bbport (r119j_clouds-banding)
    drew_this_frame = true;
    if (!told_size) {
        told_size = true;
        std::printf("Volumetric clouds (r119): first frame drawn at a scene of %ux%u (%s)\n", width,
                    height, reduced ? "reduced scene" : "the game's scene");
    }
    EffectPass::Mark(ProfileRow, "volumetric clouds");
    scheduler.RecordCrumb(
        {.name = "volumetric clouds"},
        [params, push, march_width, march_height, width, height, color_view, depth_view,
         cloud_handle = vk::Image(cloud_image), cloud_image_view = *cloud_view,
         pass_march = *march_pipeline, layout_march = *march_layout,
         pass_composite = *composite_pipeline, layout_composite = *composite_layout,
         block = params_buffer.buffer, counters = counter_buffer.buffer,
         host = counter_host.buffer](vk::CommandBuffer cmdbuf) {
            // the transfer stage waits too: last frame's copy of the counters and last frame's passes'
            // reads of the block come before this frame's clear and update of them
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute | vk::PipelineStageFlagBits2::eTransfer,
                                      ReadWrite | vk::AccessFlagBits2::eTransferWrite);
            // this frame's block, and the counters cleared (a transfer, then the passes read them)
            cmdbuf.updateBuffer(block, 0, sizeof(params), &params);
            cmdbuf.fillBuffer(counters, 0, CL::CounterWords * 4, 0);
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            // The march image is written anew where it is read; what it held before is of no use.
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = ReadWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = cloud_handle,
                .subresourceRange = ColorRange,
            };
            cmdbuf.pipelineBarrier2(
                {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            const std::array infos{Info(cloud_image_view), Info(color_view), Info(depth_view)};
            const vk::DescriptorBufferInfo block_info{block, 0, sizeof(CL::Params)};
            const vk::DescriptorBufferInfo counter_info{counters, 0, CL::CounterWords * 4};
            // the march: the scene's sky into the march image
            {
                const std::array writes{Write(0, StorageImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        WriteBuffer(3, &block_info), WriteBuffer(4, &counter_info)};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_march);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_march, 0, writes);
                cmdbuf.pushConstants(layout_march, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch((march_width + CL_WG - 1) / CL_WG, (march_height + CL_WG - 1) / CL_WG,
                                1);
            }
            EffectPass::ComputeBarrier(cmdbuf);
            // the composite: the march image into the scene's sky pixels
            {
                const std::array writes{Write(0, StorageImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        WriteBuffer(3, &block_info)};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_composite);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_composite, 0,
                                            writes);
                cmdbuf.pushConstants(layout_composite, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(push), &push);
                cmdbuf.dispatch((width + CL_WG - 1) / CL_WG, (height + CL_WG - 1) / CL_WG, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            // the counters' totals into the host copy (the log reads it a frame or two later)
            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, CL::CounterWords * 4});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

} // namespace Vulkan
