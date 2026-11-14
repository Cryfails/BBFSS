// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_point_shadow.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "common/assert.h"
#include "video_core/host_shaders/point_shadow_comp.h"
#include "video_core/host_shaders/point_shadow_ray_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
struct Push {
    u32 first_light;
    u32 frame_index;
    std::array<float, 2> size;
    float length_m;
    float thickness_m;
    float strength;
    float fade_start_m;
    float fade_end_m;
    u32 light_count;
    u32 steps;
    float bias_m;
    std::array<s32, 4> rect;
};
static_assert(sizeof(Push) == 64);

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::ImageSubresourceLayers ColorLayers{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
constexpr auto TargetFormat = vk::Format::eB10G11R11UfloatPack32;
constexpr u32 ConstantWords = 16, LightWords = 16;
// A batch of lamps drawn apart holds a whole frame's lights (16 words each, once per tile and
// lamp quad): 64K words held about 3,800, eight per tile on average, and a batch split for room is
// traced without reuse. 256K words is 1 MB.
constexpr u32 DataWords = 256 * 1024;
constexpr u32 UpdateWords = 16 * 1024;
constexpr u32 WholeImageBatches = 4;
constexpr u32 SnapshotCell = 16;
constexpr u32 HistoryWords = 2 + 12 + 16; // what Flush adds for the first ray traced pass of a frame
constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
// bbport (r32_lamp-half): more bits of the same word, read only by point_shadow_ray_half_comp
// (MODE_HALF_*); its counters (HALF_SLOTS words used); the experiment bit that turns it off.
constexpr u32 ModeHalfFirst = 2, ModeHalfFill = 4, ModeHalfCount = 8;
constexpr u32 HalfSlots = 16;
constexpr u64 HalfOffBit = 72057594037927936ull;
constexpr u32 TileWords = 8;
constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr u32 HistoryRead = 1, HistoryWrite = 2;

std::array<float, 16> Invert(const u32* words, bool& ok) {
    std::array<double, 32> t{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            t[r * 8 + c] = std::bit_cast<float>(words[r * 4 + c]);
        }
        t[r * 8 + 4 + r] = 1.0;
    }
    ok = false;
    std::array<float, 16> out{};
    for (int p = 0; p < 4; ++p) {
        int best = p;
        for (int r = p + 1; r < 4; ++r) {
            if (std::abs(t[r * 8 + p]) > std::abs(t[best * 8 + p])) {
                best = r;
            }
        }
        if (std::abs(t[best * 8 + p]) < 1e-12) {
            return out;
        }
        for (int c = 0; c < 8; ++c) {
            std::swap(t[p * 8 + c], t[best * 8 + c]);
        }
        const double scale = 1.0 / t[p * 8 + p];
        for (int c = 0; c < 8; ++c) {
            t[p * 8 + c] *= scale;
        }
        for (int r = 0; r < 4; ++r) {
            if (r != p) {
                const double f = t[r * 8 + p];
                for (int c = 0; c < 8; ++c) {
                    t[r * 8 + c] -= f * t[p * 8 + c];
                }
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            out[r * 4 + c] = float(t[r * 8 + 4 + c]);
        }
    }
    ok = std::ranges::all_of(out, [](float v) { return std::isfinite(v); });
    return out;
}

std::array<float, 12> Multiply(const std::array<float, 12>& a, const std::array<float, 12>& b) {
    std::array<float, 12> out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) {
            float sum = c == 3 ? a[r * 4 + 3] : 0.0f;
            for (int k = 0; k < 3; ++k) {
                sum += a[r * 4 + k] * b[k * 4 + c];
            }
            out[r * 4 + c] = sum;
        }
    }
    return out;
}

bool Overlaps(const std::array<s32, 4>& a, const std::array<s32, 4>& b) {
    return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}
}

PointShadow::PointShadow(const Instance& instance_, Scheduler& scheduler_,
                         VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                         SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                         RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, rt_shadow{rt_shadow_},
      camera_motion{camera_motion_} {
    fade_start_m = fade_end_m * 0.6f;
    if (const char* env = std::getenv("LANTERN_RT_LAMPS_EXACT"); env && env[0] == '1') {
        lamp_pick = 0;
    }
    // bbport: off unless asked for. Until the tile count reached the pass (Flush) it never ran;
    // now it would cover the whole screen (lamps apart), where a shadow that moves into a settled
    // 8x8 block shows up to three frames late. It saves 0.4 of the pass's 0.8 ms at 1920x1080.
    if (const char* env = std::getenv("LANTERN_RT_LAMP_REUSE")) {
        lamp_reuse = env[0] == '1';
    }
    // bbport (r37_menu-options): set, the variable decides ("1" on, else off); not set,
    // graphics_lamp_shadow_half does (Flush, every pass).
    if (const char* env = std::getenv("BB_LAMP_SHADOW_HALF"); env && env[0]) {
        half_env = env[0] == '1' ? 1 : 0;
    }
    if (half_env == 1) { // bbport (r32_lamp-half)
        std::printf("Ray traced lamps (r32): BB_LAMP_SHADOW_HALF=1, one shadow answer per 2x2 "
                    "block first, then full-resolution rays where the answers around a pixel "
                    "differ (changes the picture; experiment 72057594037927936 set = full "
                    "resolution)\n");
    }
}

bool PointShadow::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        instance.GetPhysicalDevice().getFeatures().shaderStorageImageExtendedFormats &&
        EffectPass::StorageFormat(instance, TargetFormat) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest) &&
        EffectPass::Create(instance, set_layout, layout, pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                            eStorageImage, eStorageImage},
                           sizeof(Push), POINT_SHADOW_COMP, "Point shadows", true);
    if (!made) {
        failed = true;
        std::printf("Point shadows: off - this GPU cannot run the pass\n");
        return false;
    }
    if (rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_COMP, "Ray traced lamps", true)) {
        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
    // bbport (r37_menu-options): the half-resolution build is made by HalfReady, when first wanted.
    constexpr auto Drawn = vk::FormatFeatureFlagBits::eColorAttachment |
                           vk::FormatFeatureFlagBits::eColorAttachmentBlend;
    lamp_format = (instance.GetPhysicalDevice().getFormatProperties(TargetFormat)
                       .optimalTilingFeatures & Drawn) == Drawn;
    light_data = std::make_unique<VideoCore::Buffer>(
        instance, 0, DataWords * sizeof(u32), VideoCore::MemoryType::DeviceLocal, "Point shadow lights");
    return true;
}

// bbport (r32_lamp-half, r37_menu-options): the half-resolution build, made the first time a
// pass wants it: the ray pass's bindings, then the block answers (9) and the counters (10).
bool PointShadow::HalfReady() {
    if (half_tried) {
        return half_made;
    }
    half_tried = true;
    using enum vk::DescriptorType;
    if (ray_pipeline &&
        EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                            eStorageImage, eStorageImage, eStorageImage,
                            eAccelerationStructureKHR, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer},
                           sizeof(Push), POINT_SHADOW_RAY_HALF_COMP,
                           "Ray traced lamps (half resolution)", true)) {
        half_counts = std::make_unique<VideoCore::Buffer>(
            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::DeviceLocal,
            "Ray traced lamp half counters");
        half_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::HostCached,
            "Ray traced lamp half counters readback");
        if (half_readback->mapped_data.size() >= HalfSlots * sizeof(u32)) {
            std::memset(half_readback->mapped_data.data(), 0, HalfSlots * sizeof(u32));
            half_made = true;
        }
    }
    std::printf("Ray traced lamps (r32): half resolution (%s) %s\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
    return half_made;
}

PointShadow::~PointShadow() = default;

bool PointShadow::RaysWanted() const {
    return rt_shadow.Wanted() &&
           BbSettings::Get().graphics_rt_point_shadows.load(std::memory_order_relaxed);
}

bool PointShadow::BeginApart(u32 width, u32 height) {
    if (!rt_shadow.PrepareScene()) {
        return false;
    }
    const bool have = lamp[0].image && lamp[0].width == width && lamp[0].height == height;
    const bool have_history =
        history[0].image && history[0].width == width && history[0].height == height;
    const u64 pixels = u64(width) * height;
    const u64 needed = (have ? 0 : 2 * 4 * pixels) + (have_history ? 0 : 2 * 8 * pixels);
    if (needed && !EffectPass::HasRoom(instance, needed)) {
        return false;
    }
    for (auto& own : lamp) {
        if (EnsureImage(own, width, height, TargetFormat, "Ray traced lamp light",
                        vk::ImageUsageFlagBits::eColorAttachment)) {
            lamp_dirty = true;
            lamp_laid_out = false;
        }
    }
    if (lamp_dirty) {
        // New images, or a batch that ended without its pass (the pass zeroes what it reads).
        const auto old_layout =
            lamp_laid_out ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined;
        lamp_laid_out = true;
        scheduler.RecordCrumb(
            {.name = "Ray traced lamp light clear"},
            [images = std::array{vk::Image(lamp[0].image), vk::Image(lamp[1].image)},
             old_layout](vk::CommandBuffer cmdbuf) {
                std::array<vk::ImageMemoryBarrier2, 2> barriers;
                for (int i = 0; i < 2; ++i) {
                    barriers[i] = {
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                         vk::AccessFlagBits2::eMemoryWrite,
                        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                        .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                        .oldLayout = old_layout,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = images[i],
                        .subresourceRange = ColorRange,
                    };
                }
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = barriers.data()});
                const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                for (const vk::Image image : images) {
                    cmdbuf.clearColorImage(image, vk::ImageLayout::eGeneral, zero, ColorRange);
                }
                const vk::MemoryBarrier2 after{
                    .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
            });
    }
    lamp_dirty = true; // until the batch's pass has moved the light out
    return true;
}

bool PointShadow::EnsureImage(OwnImage& own, u32 width, u32 height, vk::Format format,
                              const char* name, vk::ImageUsageFlags more_usage) {
    if (own.image && own.width == width && own.height == height) {
        return false;
    }
    if (own.image) {
        scheduler.DeferOperation(
            [image = std::move(own.image), view = std::move(own.view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    own.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    own.image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst |
                 more_usage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(own.image), name);
    own.view = Check<"create point shadow snapshot view">(device.createImageViewUnique({
        .image = vk::Image(own.image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = ColorRange,
    }));
    own.width = width;
    own.height = height;
    return true;
}

void PointShadow::OnFrameEnd() {
    ++frame_index;
    if (history_written) {
        history_index ^= 1u;
        last_view = pending_view;
        last_proj = pending_proj;
        last_valid = pending_valid;
        history_fresh = true;
    } else {
        history_fresh = false;
    }
    history_written = false;
    if (batches != 0 && (!reported || frame_index % 1800 == 0)) {
        reported = true;
        std::printf("Point shadows: %u light tiles in %u batches this frame; %u draws between tiles "
                    "kept the batch, %u ended it (%08llx %08llx %08llx %08llx); snapshots: %u "
                    "copies, %.1f MB%s",
                    frame_tiles, batches, kept_draws, ended_by_draws,
                    (unsigned long long)ending_hashes[0], (unsigned long long)ending_hashes[1],
                    (unsigned long long)ending_hashes[2], (unsigned long long)ending_hashes[3],
                    snapshot_copies, double(snapshot_pixels) * 4.0 / (1024.0 * 1024.0),
                    tile_snapshots ? " (by tile, BB_RT_LAMP_SNAPSHOT)" : "");
        if (tile_snapshots) {
            std::printf("; %u of the %u ending draws with a known place drew away from the "
                        "batch's cells",
                        ended_apart, ended_placed);
        }
        if (apart_draws) {
            std::printf("; lamps apart: %u draws in %u passes, %u adding draws kept a batch, %u "
                        "batches ended by a compute pass (BB_RT_LAMP_APART)",
                        apart_draws, apart_passes, kept_adding, dispatch_flushes);
        }
        std::printf("\n");
    }
    // bbport (r32_lamp-half): every 600 frames, what the two passes did: means per counted
    // pass (one in 8; u32 differences survive the wrap; read while the GPU may still copy a later
    // pass's counters, which then fall in the next line). half_readback: made by HalfReady
    // (bbport r37_menu-options), the first time a pass wants the half resolution.
    if (half_made && half_readback && ++half_frames >= 600) {
        std::array<u32, HalfSlots> now{};
        half_readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), half_readback->mapped_data.data(), sizeof(now));
        const u32 counted = now[0] - half_last[0];
        std::array<double, HalfSlots> d{};
        for (u32 i = 0; i < HalfSlots && counted != 0; ++i) {
            d[i] = double(u32(now[i] - half_last[i])) / double(counted);
        }
        half_last = now;
        std::printf("Ray traced lamps (r32): %u frames: %u passes at half resolution, %u at full "
                    "resolution (experiment 72057594037927936 set); a counted pass (mean of %u): "
                    "first pass (pixel 2x,2y of each block) %.0f pixels traced with %.0f rays, "
                    "%.0f from history; second pass (the other three) %.0f pixels took the "
                    "block's answer, %.0f traced at full resolution with %.0f rays (%.0f a block "
                    "near them had no answer, %.0f the answers differed, %.0f another surface), "
                    "%.0f from history; second-pass workgroups with no ray %.0f of %.0f\n",
                    half_frames, half_line_passes, half_line_full, counted, d[1], d[2], d[3],
                    d[4], d[5], d[6], d[10], d[11], d[12], d[7], d[9], d[8]);
        half_frames = 0;
        half_line_passes = 0;
        half_line_full = 0;
    }
    dispatch_flushes = 0;
    if ((unended || lost_passes || flushed_in_draw > 60) && frame_index % 300 == 0) {
        // Each of the first two is a frame without (part of) its lamp light.
        static u32 lines = 0;
        if (lines < 20) {
            ++lines;
            std::printf("Lamps apart: since the last line %u batches were still open at the end "
                        "of a frame and %u passes could not run (their lamp light is lost); %u "
                        "batches were ended by a lamp draw\n",
                        unended, lost_passes, flushed_in_draw);
        }
        unended = lost_passes = flushed_in_draw = 0;
    }
    apart_last_frame = apart_draws != 0;
    apart_passes = 0;
    apart_draws = 0;
    kept_adding = 0;
    ended_placed = 0;
    static const bool trace_wanted = [] {
        const char* env = std::getenv("BB_RT_LAMP_TRACE");
        return env && env[0] == '1';
    }();
    trace_left = 0;
    if (trace_wanted && !traced && batches > 100) {
        traced = true;
        trace_left = 90; // of the next frame
    }
    ended_apart = 0;
    snapshot_copies = 0;
    snapshot_pixels = 0;
    batches = 0;
    frame_tiles = 0;
    kept_draws = 0;
    ended_by_draws = 0;
    ending_hashes = {};
}

std::array<VAddr, 2> PointShadow::PendingAddresses() const {
    std::array<VAddr, 2> out{};
    for (int i = 0; i < 2; ++i) {
        if (pending[i]) {
            if (const auto* image = texture_cache.TryGetImage(pending[i], pending_uid[i])) {
                out[i] = image->info.guest_address;
            }
        }
    }
    return out;
}

void PointShadow::Ended(u64 hash) {
    if (tiles.empty()) {
        return;
    }
    ++ended_by_draws;
    ending_uncounted = tile_snapshots;
    ending_hash = hash;
    for (u64& slot : ending_hashes) {
        if (slot == hash) {
            return;
        }
        if (slot == 0) {
            slot = hash;
            return;
        }
    }
}

void PointShadow::EndingDraw(const vk::Rect2D& area) {
    // The cells are those of the batch that ended: they stay until the next batch begins.
    ending_uncounted = false;
    const s32 width = s32(snapshot[0].width), height = s32(snapshot[0].height);
    const s32 x0 = std::clamp(area.offset.x, 0, width);
    const s32 y0 = std::clamp(area.offset.y, 0, height);
    const s32 x1 = std::clamp(area.offset.x + s32(area.extent.width), x0, width);
    const s32 y1 = std::clamp(area.offset.y + s32(area.extent.height), y0, height);
    if (snapshot_cells.empty() || snapshot_cells_wide != (u32(width) + SnapshotCell - 1) / SnapshotCell) {
        return;
    }
    bool apart = true;
    for (u32 cy = u32(y0) / SnapshotCell; apart && cy * SnapshotCell < u32(y1); ++cy) {
        for (u32 cx = u32(x0) / SnapshotCell; apart && cx * SnapshotCell < u32(x1); ++cx) {
            const u32 index = cy * snapshot_cells_wide + cx;
            apart = index >> 6 < snapshot_cells.size() &&
                    !(snapshot_cells[index >> 6] & (1ull << (index & 63)));
        }
    }
    ++ended_placed;
    ended_apart += apart;
    if (trace_left) {
        --trace_left;
        std::printf("Lamp trace: batch ended by ps %08llx at %d,%d %dx%d, %s\n",
                    (unsigned long long)ending_hash, x0, y0, x1 - x0, y1 - y0,
                    apart ? "away from the batch's cells" : "over the batch's cells");
    }
}

void PointShadow::Drop() {
    ending_uncounted = false;
    apart = false; // its lamp light is lost; the lamp images are cleared before their next use
    redirect_draw = false;
    tiles.clear();
    pending[0] = pending[1] = {};
    merged = false;
    history_fresh = false;
}

void PointShadow::OnLightDraw(VideoCore::ImageId color0, VideoCore::ImageId color1,
                              const Inputs& inputs) {
    ending_uncounted = false;
    redirect_draw = false;
    if (failed || !color0 || !color1 || !inputs.constants || !inputs.lights || inputs.count == 0 ||
        (!BbSettings::Get().effects[BbSettings::EffectPointShadows].load(
             std::memory_order_relaxed) &&
         !RaysWanted()) ||
        !Ready()) {
        return;
    }
    const auto depth_id = camera_motion.Depth();
    if (!depth_id) {
        return;
    }
    const bool reduced = scene_targets.Reduced() &&
                         scene_targets.Eligible(texture_cache.GetImage(depth_id));
    const std::array ids{color0, color1};
    std::array<VideoCore::Image*, 2> targets{};
    for (int i = 0; i < 2; ++i) {
        targets[i] = &texture_cache.GetImage(ids[i]);
        const auto& info = targets[i]->info;
        if (info.pixel_format != TargetFormat ||
            (!reduced && !(targets[i]->usage_flags & vk::ImageUsageFlagBits::eStorage)) ||
            (!reduced && !(targets[i]->usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) ||
            (reduced && !scene_targets.Eligible(*targets[i])) ||
            info.size.width != targets[0]->info.size.width ||
            info.size.height != targets[0]->info.size.height) {
            failed = true;
            std::printf("Point shadows: the light targets are not matching B10G11R11 storage "
                        "images; off\n");
            return;
        }
    }
    u32 width = targets[0]->info.size.width, height = targets[0]->info.size.height;
    if (reduced) {
        const auto size = scene_targets.ProxySize(*targets[0]);
        width = size.width;
        height = size.height;
    }
    const s32 x0 = std::clamp(inputs.tile.offset.x, 0, s32(width));
    const s32 y0 = std::clamp(inputs.tile.offset.y, 0, s32(height));
    const s32 x1 = std::clamp(inputs.tile.offset.x + s32(inputs.tile.extent.width), x0, s32(width));
    const s32 y1 = std::clamp(inputs.tile.offset.y + s32(inputs.tile.extent.height), y0, s32(height));
    if (x0 == x1 || y0 == y1) {
        return;
    }
    const std::array<s32, 4> rect{x0, y0, x1, y1};
    if (trace_left) {
        --trace_left;
        std::printf("Lamp trace: lamp draw, %u lights at %d,%d %dx%d, %zu tiles pending\n",
                    inputs.count, x0, y0, x1 - x0, y1 - y0, tiles.size());
    }
    const u32 words = inputs.count * LightWords;
    const auto add_lights = [&] {
        data.insert(data.end(), inputs.lights, inputs.lights + words);
        ++frame_tiles;
        redirect_draw = apart;
        apart_draws += apart;
    };
    static const bool apart_on = [] {
        const char* env = std::getenv("BB_RT_LAMP_APART");
        return !env || env[0] != '0';
    }();
    // A light that takes light away cannot be drawn apart: the lamp images hold nothing below
    // zero, where the light target would have been lowered.
    const auto darkens = [&] {
        for (u32 k = 0; k < inputs.count; ++k) {
            for (u32 c = 4; c < 7; ++c) {
                if (std::bit_cast<float>(inputs.lights[k * LightWords + c]) < 0.0f) {
                    return true;
                }
            }
        }
        return false;
    };
    // Whether this draw can go into a batch that keeps the lamps' light apart.
    const bool can_apart = apart_on && inputs.adds_in_tile && lamp_format && ray_pipeline &&
                           RaysWanted() && inputs.pass.width == width &&
                           inputs.pass.height == height && apart_refused != frame_index &&
                           !BbToggle::Experiment(128) && !darkens();
    if (!tiles.empty()) {
        const bool same_targets = pending[0] == color0 && pending[1] == color1 &&
                                  pending_uid[0] == targets[0]->image_uid &&
                                  pending_uid[1] == targets[1]->image_uid;
        // (An apart batch's pass always has the history words after the tiles.)
        const bool room = data.size() + words + TileWords * (tiles.size() + 1) +
                              (apart || merged ? HistoryWords : 0) <= DataWords;
        const OwnImage& before = apart ? lamp[0] : snapshot[0];
        const bool same_size = before.width == width && before.height == height;
        if (same_targets && same_size && apart == can_apart && (merged || !one_tile_batches) &&
            room) {
            if (tiles.back().rect == rect) {
                tiles.back().count += inputs.count;
                add_lights();
                return;
            }
            if (merged ||
                std::ranges::none_of(tiles, [&](const Tile& t) { return Overlaps(t.rect, rect); })) {
                if (tile_snapshots) {
                    // Before this tile's lamps are drawn: the cells no earlier tile of the batch
                    // took still hold what they held when the batch began. Each copy ends the
                    // render pass and three of them cost more than one copy of the whole image
                    // (about 5 against 15 microseconds of GPU time), so a batch's third copy
                    // takes every cell left: a long batch then stays in one pass, as before.
                    const std::array<s32, 4> whole{0, 0, s32(width), s32(height)};
                    auto regions =
                        TakeSnapshotCells(batch_copies >= 2 ? whole : rect, width, height);
                    if (!regions.empty()) {
                        ++batch_copies;
                        if (!CopySnapshot(ids, targets, reduced, std::move(regions), true)) {
                            Drop();
                            return;
                        }
                    }
                }
                tiles.push_back({rect, u32(data.size()), inputs.count});
                add_lights();
                return;
            }
        }
        // This draw's render state is computed already (Rasterizer::BeginRendering), with the
        // layouts its attachments had then: the pass leaves the light targets and the depth
        // readable by compute, so they go back to what the draw expects.
        auto* depth_image = texture_cache.TryGetImage(depth_id, 0);
        const auto depth_layout =
            depth_image ? depth_image->backing->state.layout : vk::ImageLayout::eUndefined;
        flushed_in_draw += apart;
        Flush(false);
        if (failed) {
            return;
        }
        // (A batch with snapshots puts the light targets back itself: CopySnapshot.)
        if (reduced) {
            VideoCore::ImageViewInfo target_info, depth_info;
            target_info.format = TargetFormat;
            if (can_apart) {
                scene_targets.Attachment(ids[0], target_info);
                scene_targets.Attachment(ids[1], target_info);
            }
            if (depth_image) {
                depth_info.format = depth_image->info.pixel_format;
                scene_targets.Attachment(depth_id, depth_info);
            }
        } else {
            for (auto* target : targets) {
                if (!can_apart) {
                    break;
                }
                runtime.Transit(target, vk::ImageLayout::eColorAttachmentOptimal,
                                vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                vk::AccessFlagBits2::eColorAttachmentWrite |
                                    vk::AccessFlagBits2::eColorAttachmentRead);
            }
            if (depth_image && depth_layout != vk::ImageLayout::eUndefined &&
                depth_image->backing->state.layout != depth_layout) {
                runtime.Transit(depth_image, depth_layout,
                                vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                    vk::PipelineStageFlagBits2::eLateFragmentTests,
                                vk::AccessFlagBits2::eDepthStencilAttachmentRead |
                                    vk::AccessFlagBits2::eDepthStencilAttachmentWrite);
            }
            runtime.FlushBarriers();
        }
    }
    static bool printed = false;
    if (!printed) {
        printed = true;
        std::printf("Point shadows: %ux%u, length %.2f m, thickness %.2f m, strength %.2f, "
                    "%u steps, first tile %dx%d\n",
                    width, height, length_m, thickness_m, strength, steps, x1 - x0, y1 - y0);
    }

    scheduler.EndRendering();
    merged = ray_pipeline && RaysWanted();
    apart = can_apart && BeginApart(width, height);
    if (can_apart && !apart) {
        apart_refused = frame_index; // not asked again this frame: the batches stay as they are
    }
    tile_snapshots = false;
    if (!apart) {
        if ((!snapshot[0].image || snapshot[0].width != width || snapshot[0].height != height) &&
            !EffectPass::HasRoom(instance, 2ull * 4 * width * height)) {
            failed = true;
            std::printf("Point shadows: off - not enough video memory\n");
            return;
        }
        for (auto& own : snapshot) {
            if (EnsureImage(own, width, height, TargetFormat, "Point shadow snapshot")) {
                snapshot_laid_out = false;
            }
        }
    }
    one_tile_batches = ++batches > WholeImageBatches;
    static const bool by_tile = [] {
        const char* env = std::getenv("BB_RT_LAMP_SNAPSHOT");
        return !env || env[0] != '0';
    }();
    tile_snapshots = !apart && merged && by_tile && !BbToggle::Experiment(64);
    std::vector<vk::ImageCopy> regions;
    if (apart) {
        // No snapshot: the lamps' light is drawn apart.
    } else if (tile_snapshots) {
        snapshot_cells_wide = (width + SnapshotCell - 1) / SnapshotCell;
        const u32 cells = snapshot_cells_wide * ((height + SnapshotCell - 1) / SnapshotCell);
        snapshot_cells.assign((cells + 63) / 64, 0);
        batch_copies = 1;
        regions = TakeSnapshotCells(rect, width, height);
    } else {
        const std::array<s32, 4> copied = one_tile_batches && !merged
                                              ? rect
                                              : std::array<s32, 4>{0, 0, s32(width), s32(height)};
        regions.push_back({.srcSubresource = ColorLayers,
                           .srcOffset = {copied[0], copied[1], 0},
                           .dstSubresource = ColorLayers,
                           .dstOffset = {copied[0], copied[1], 0},
                           .extent = {u32(copied[2] - copied[0]), u32(copied[3] - copied[1]), 1}});
    }
    if (!apart && !CopySnapshot(ids, targets, reduced, std::move(regions), tile_snapshots)) {
        return;
    }

    pending[0] = color0;
    pending[1] = color1;
    pending_uid = {targets[0]->image_uid, targets[1]->image_uid};
    data.assign(inputs.constants, inputs.constants + ConstantWords);
    tiles.push_back({rect, u32(data.size()), inputs.count});
    add_lights();
}

std::vector<vk::ImageCopy> PointShadow::TakeSnapshotCells(const std::array<s32, 4>& rect, u32 width,
                                                          u32 height) {
    std::vector<vk::ImageCopy> regions;
    const u32 cx0 = u32(rect[0]) / SnapshotCell, cy0 = u32(rect[1]) / SnapshotCell;
    const u32 cx1 = (u32(rect[2]) + SnapshotCell - 1) / SnapshotCell;
    const u32 cy1 = (u32(rect[3]) + SnapshotCell - 1) / SnapshotCell;
    // Whether the cell was taken already; it is now.
    const auto take = [&](u32 cx, u32 cy) {
        const u32 index = cy * snapshot_cells_wide + cx;
        u64& word = snapshot_cells[index >> 6];
        const u64 mask = 1ull << (index & 63);
        const bool taken = (word & mask) != 0;
        word |= mask;
        return taken;
    };
    // open: the regions that end at the row of cells being walked, so that a run over the same
    // columns makes one of them taller instead of starting another.
    auto& open = cell_rows[0];
    auto& next = cell_rows[1];
    open.clear();
    for (u32 cy = cy0; cy < cy1; ++cy) {
        next.clear();
        const s32 y = s32(cy * SnapshotCell);
        const u32 h = std::min((cy + 1) * SnapshotCell, height) - cy * SnapshotCell;
        for (u32 cx = cx0; cx < cx1; ++cx) {
            if (take(cx, cy)) {
                continue;
            }
            u32 end = cx + 1;
            while (end < cx1 && !take(end, cy)) {
                ++end;
            }
            const s32 x = s32(cx * SnapshotCell);
            const u32 w = std::min(end * SnapshotCell, width) - cx * SnapshotCell;
            const auto same = std::ranges::find_if(open, [&](u32 i) {
                return regions[i].srcOffset.x == x && regions[i].extent.width == w;
            });
            if (same != open.end()) {
                regions[*same].extent.height += h;
                next.push_back(*same);
            } else {
                next.push_back(u32(regions.size()));
                regions.push_back({.srcSubresource = ColorLayers,
                                   .srcOffset = {x, y, 0},
                                   .dstSubresource = ColorLayers,
                                   .dstOffset = {x, y, 0},
                                   .extent = {w, h, 1}});
            }
            cx = end; // the cell at `end` is taken, or past the tile
        }
        std::swap(open, next);
    }
    return regions;
}

bool PointShadow::CopySnapshot(const std::array<VideoCore::ImageId, 2>& ids,
                               const std::array<VideoCore::Image*, 2>& targets, bool reduced,
                               std::vector<vk::ImageCopy> regions, bool keep) {
    scheduler.EndRendering();
    VideoCore::ImageViewInfo target_info;
    target_info.format = TargetFormat;
    std::array<vk::Image, 2> src{};
    vk::ImageLayout src_layout = vk::ImageLayout::eTransferSrcOptimal;
    if (reduced) {
        src_layout = vk::ImageLayout::eGeneral;
        for (int i = 0; i < 2; ++i) {
            const auto proxy = scene_targets.Read(ids[i], target_info, vk::PipelineStageFlagBits2::eCopy,
                                                  vk::AccessFlagBits2::eTransferRead);
            if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage) ||
                !(proxy.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                failed = true;
                scene_targets.Attachment(ids[0], target_info);
                scene_targets.Attachment(ids[1], target_info);
                std::printf("Point shadows: the reduced light targets cannot be used; off\n");
                return false;
            }
            src[i] = proxy.image;
        }
    } else {
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eTransferSrcOptimal,
                            vk::PipelineStageFlagBits2::eCopy, vk::AccessFlagBits2::eTransferRead);
        }
        runtime.FlushBarriers();
        src = {targets[0]->GetImage(), targets[1]->GetImage()};
    }
    const std::array<vk::Image, 2> dst{vk::Image(snapshot[0].image),
                                       vk::Image(snapshot[1].image)};
    // Undefined lets the driver drop what the snapshots hold.
    const auto old_layout =
        keep && snapshot_laid_out ? vk::ImageLayout::eGeneral : vk::ImageLayout::eUndefined;
    snapshot_laid_out = true;
    ++snapshot_copies;
    for (const auto& region : regions) {
        snapshot_pixels += 2ull * region.extent.width * region.extent.height;
    }
    EffectPass::Mark(5, "point shadow snapshots");
    scheduler.RecordCrumb({.name = "Point shadows snapshot"},
                          [src, dst, regions = std::move(regions), src_layout,
                           old_layout](vk::CommandBuffer cmdbuf) {
        std::array<vk::ImageMemoryBarrier2, 2> to_dst;
        for (int i = 0; i < 2; ++i) {
            to_dst[i] = {
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                 vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eCopy,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .oldLayout = old_layout,
                .newLayout = vk::ImageLayout::eTransferDstOptimal,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = dst[i],
                .subresourceRange = ColorRange,
            };
        }
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = to_dst.data()});
        for (int i = 0; i < 2; ++i) {
            cmdbuf.copyImage(src[i], src_layout, dst[i],
                             vk::ImageLayout::eTransferDstOptimal, regions);
        }
        std::array<vk::ImageMemoryBarrier2, 2> to_general;
        for (int i = 0; i < 2; ++i) {
            to_general[i] = to_dst[i];
            to_general[i].srcStageMask = vk::PipelineStageFlagBits2::eCopy;
            to_general[i].srcAccessMask = vk::AccessFlagBits2::eTransferWrite;
            to_general[i].dstStageMask = Compute;
            to_general[i].dstAccessMask = vk::AccessFlagBits2::eShaderRead;
            to_general[i].oldLayout = vk::ImageLayout::eTransferDstOptimal;
            to_general[i].newLayout = vk::ImageLayout::eGeneral;
        }
        cmdbuf.pipelineBarrier2(
            {.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = to_general.data()});
    });
    if (reduced) {
        scene_targets.Attachment(ids[0], target_info);
        scene_targets.Attachment(ids[1], target_info);
    } else {
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eColorAttachmentOptimal,
                            vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                            vk::AccessFlagBits2::eColorAttachmentWrite |
                                vk::AccessFlagBits2::eColorAttachmentRead);
        }
        runtime.FlushBarriers();
    }
    return true;
}

void PointShadow::Flush(bool animate_noise) {
    if (tiles.empty()) {
        return;
    }
    const auto ids = pending;
    const auto uids = pending_uid;
    auto batch = std::move(tiles);
    tiles.clear();
    pending[0] = pending[1] = {};
    // Every return before the pass is recorded loses an apart batch's lamp light for this frame
    // (lamp_dirty stays set: the lamp images are cleared before their next use).
    const bool batch_apart = std::exchange(apart, false);
    redirect_draw = false;
    // Counts the batch as lost on every return before its pass is recorded.
    struct Lost {
        u32& count;
        bool armed;
        ~Lost() {
            count += armed;
        }
    } lost{lost_passes, batch_apart};
    const auto depth_id = camera_motion.Depth();
    if (!depth_id) {
        return;
    }
    auto* depth_ptr = texture_cache.TryGetImage(depth_id, 0);
    auto* target0 = texture_cache.TryGetImage(ids[0], uids[0]);
    auto* target1 = texture_cache.TryGetImage(ids[1], uids[1]);
    if (!depth_ptr || !target0 || !target1) {
        return;
    }
    auto& depth = *depth_ptr;
    std::array<VideoCore::Image*, 2> targets{target0, target1};
    const bool reduced = scene_targets.Reduced() && scene_targets.Eligible(depth) &&
                         scene_targets.Eligible(*targets[0]);
    u32 width = targets[0]->info.size.width, height = targets[0]->info.size.height;
    if (reduced) {
        const auto size = scene_targets.ProxySize(*targets[0]);
        width = size.width;
        height = size.height;
    }
    // What the pass reads beside the light targets: their snapshots, or the lamps' light.
    const OwnImage* before = batch_apart ? lamp : snapshot;
    if (before[0].width != width || before[0].height != height) {
        return;
    }

    scheduler.EndRendering();
    const bool batch_merged = merged;
    merged = false;
    // (An apart batch was begun for rays: the setting going off meanwhile does not drop it.)
    const bool use_rays =
        ray_pipeline && (batch_apart || RaysWanted()) && rt_shadow.PrepareScene();
    if (!use_rays &&
        (batch_merged ||
         !BbSettings::Get().effects[BbSettings::EffectPointShadows].load(std::memory_order_relaxed))) {
        return;
    }
    std::array<s32, 4> covered{s32(width), s32(height), 0, 0};
    u32 table = 0;
    if (use_rays) {
        table = u32(data.size());
        for (const Tile& tile : batch) {
            covered = {std::min(covered[0], tile.rect[0]), std::min(covered[1], tile.rect[1]),
                       std::max(covered[2], tile.rect[2]), std::max(covered[3], tile.rect[3])};
            data.insert(data.end(), {u32(tile.rect[0]), u32(tile.rect[1]), u32(tile.rect[2]),
                                     u32(tile.rect[3]), tile.first_light, tile.count, 0u, 0u});
        }
        if (data.size() > DataWords || covered[0] >= covered[2] || covered[1] >= covered[3]) {
            data.clear();
            return;
        }
        bool made = false;
        if (!history[0].image || history[0].width != width || history[0].height != height) {
            if (!EffectPass::HasRoom(instance, 2ull * 8 * width * height)) {
                data.clear();
                return;
            }
            for (int i = 0; i < 2; ++i) {
                EnsureImage(history[i], width, height, HistoryFormat, "Ray traced lamp history");
                history_laid_out[i] = false;
            }
            made = true;
        }
        if (made) {
            history_fresh = false;
            history_written = false; // the new images hold nothing: this frame's history starts again
        }
    }
    u32 history_at = 0;
    bool clear_history = false;
    std::array<bool, 2> lay_out{};
    // One pass a frame can use the history. While the lamps are drawn apart that is their pass, the
    // one that covers the screen: a small batch before it (a lamp quad that could not go apart)
    // does not take it.
    const bool history_ours = batch_apart || (apart_draws == 0 && !apart_last_frame);
    if (use_rays && !history_written && history_ours) {
        const auto camera = camera_motion.PassMatrices();
        bool ok = false;
        const auto proj = Invert(data.data(), ok);
        u32 flags = lamp_reuse ? HistoryWrite : 0u;
        if (lamp_reuse && history_fresh && last_valid && camera.valid && ok) {
            flags |= HistoryRead;
        }
        history_at = u32(data.size());
        data.push_back(flags);
        data.push_back(frame_index);
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const auto reproject = (flags & HistoryRead) ? Multiply(last_view, camera.inv_view) : Identity;
        for (const float v : reproject) {
            data.push_back(std::bit_cast<u32>(v));
        }
        for (const float v : last_proj) {
            data.push_back(std::bit_cast<u32>(v));
        }
        if (data.size() > DataWords) {
            data.clear();
            return;
        }
        pending_view = camera.view;
        pending_proj = proj;
        pending_valid = camera.valid && ok;
        history_written = lamp_reuse;
        clear_history = lamp_reuse;
    }
    if (use_rays) {
        lay_out = {!history_laid_out[0], !history_laid_out[1]};
        history_laid_out = {true, true};
    }
    const vk::ImageView history_prev = use_rays ? *history[history_index ^ 1u].view : vk::ImageView{};
    const vk::ImageView history_cur = use_rays ? *history[history_index].view : vk::ImageView{};
    const vk::Image history_cur_image = use_rays ? vk::Image(history[history_index].image) : vk::Image{};
    const std::array<vk::Image, 2> history_images{
        use_rays ? vk::Image(history[0].image) : vk::Image{},
        use_rays ? vk::Image(history[1].image) : vk::Image{}};
    const auto device = instance.GetDevice();
    std::array<vk::ImageView, 2> target_views;
    vk::ImageView depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo target_info, depth_info;
        target_info.format = TargetFormat;
        depth_info.format = depth.info.pixel_format;
        for (int i = 0; i < 2; ++i) {
            target_views[i] = scene_targets
                                  .Read(ids[i], target_info, Compute,
                                        vk::AccessFlagBits2::eShaderRead |
                                            vk::AccessFlagBits2::eShaderWrite)
                                  .view;
        }
        // bbport (r22_barriers): right after the targets' barriers (their Read, compute stage)
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        for (int i = 0; i < 2; ++i) {
            target_views[i] = Check<"create point shadow target view">(device.createImageView({
                .image = targets[i]->GetImage(),
                .viewType = vk::ImageViewType::e2D,
                .format = TargetFormat,
                .subresourceRange = ColorRange,
            }));
        }
        depth_view = Check<"create point shadow depth view">(device.createImageView({
            .image = depth.GetImage(),
            .viewType = vk::ImageViewType::e2D,
            .format = depth.info.pixel_format,
            .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
        }));
        scheduler.DeferOperation([device, target_views, depth_view] {
            device.destroyImageView(target_views[0]);
            device.destroyImageView(target_views[1]);
            device.destroyImageView(depth_view);
        });
        for (auto* target : targets) {
            runtime.Transit(target, vk::ImageLayout::eGeneral, Compute,
                            vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        }
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }

    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
    // lamps-apart pass in two halves (point_shadow_ray_half_comp), with the block answers in an
    // image of half the size.
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    const bool half_on = half_env >= 0 ? half_env == 1
                                       : BbSettings::Get().graphics_lamp_shadow_half.load(
                                             std::memory_order_relaxed);
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
    if (use_half && BbToggle::Experiment(HalfOffBit)) {
        use_half = false;
        ++half_line_full;
    }
    if (use_half) {
        const u32 half_width = (width + 1) / 2, half_height = (height + 1) / 2;
        if (half_answers.width != half_width || half_answers.height != half_height) {
            if (!EffectPass::HasRoom(instance, 8ull * half_width * half_height)) {
                use_half = false;
            } else if (EnsureImage(half_answers, half_width, half_height, HistoryFormat,
                                   "Ray traced lamp half answers")) {
                half_laid_out = false;
            }
        }
    }
    const bool half_lay_out = use_half && !std::exchange(half_laid_out, true);
    const bool half_count = use_half && (half_passes++ & 7u) == 0;
    const bool half_clear = use_half && !std::exchange(half_cleared, true);
    half_line_passes += use_half;
    Push push{
        .first_light = 0,
        .frame_index = animate_noise ? frame_index : 0u,
        .size = {float(width), float(height)},
        .length_m = use_rays ? std::bit_cast<float>(history_at) : length_m,
        .thickness_m = use_rays ? std::bit_cast<float>(batch_apart ? ModeApart : 0u) : thickness_m,
        .strength = use_rays ? 1.0f : strength,
        .fade_start_m = use_rays ? 60.0f : fade_start_m,
        .fade_end_m = use_rays ? 100.0f : fade_end_m,
        .light_count = 0,
        .steps = use_rays ? lamp_pick : steps,
        .bias_m = bias_m,
        .rect = {},
    };
    // bbport: counted here. As a capture after `batch = std::move(batch)` it was the size of the
    // emptied vector, zero: the ray traced pass then found no tile in any group and left the
    // lamps unshadowed, for the full cost of its batches.
    const u32 tile_count = u32(batch.size());
    EffectPass::Mark(6, "point shadows");
    if (batch_apart) {
        lamp_dirty = false; // the pass zeroes every lamp texel that holds light
        ++apart_passes;
        lost.armed = false;
    }
    scheduler.RecordCrumb(
        {.name = "Point shadows"},
        [push, target_views, depth_view, sampler = *sampler, snap0 = *before[0].view,
         snap1 = *before[1].view, batch = std::move(batch), words = std::move(data),
         buffer = light_data->Handle(), pipeline = use_rays ? *ray_pipeline : *pipeline,
         layout = use_rays ? *ray_layout : *layout, use_rays, scene = rt_shadow.Scene(), covered,
         table, tile_count, history_prev, history_cur, history_cur_image,
         history_images, lay_out, clear_history,
         // bbport (r32_lamp-half): null unless this pass runs in two halves
         half_pipe = use_half ? *half_pipeline : vk::Pipeline{},
         half_pipe_layout = use_half ? *half_layout : vk::PipelineLayout{},
         half_view = use_half ? *half_answers.view : vk::ImageView{},
         half_image = use_half ? vk::Image(half_answers.image) : vk::Image{},
         half_count_buffer = use_half ? half_counts->Handle() : vk::Buffer{},
         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{}, half_lay_out,
         half_count, half_clear](vk::CommandBuffer cmdbuf) mutable {
            for (int i = 0; i < 2; ++i) {
                if (!lay_out[i]) {
                    continue;
                }
                const vk::ImageMemoryBarrier2 to_general{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = history_images[i],
                    .subresourceRange = ColorRange,
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            const vk::MemoryBarrier2 to_transfer{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
            if (clear_history) {
                const vk::MemoryBarrier2 history_free{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &history_free});
                const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
            }
            for (u32 at = 0; at < words.size(); at += UpdateWords) {
                const u32 count = std::min<u32>(UpdateWords, u32(words.size()) - at);
                cmdbuf.updateBuffer(buffer, at * sizeof(u32), count * sizeof(u32), words.data() + at);
            }
            const vk::MemoryBarrier2 before{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                 vk::AccessFlagBits2::eShaderWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            const vk::DescriptorBufferInfo lights{buffer, 0, words.size() * sizeof(u32)};
            const vk::DescriptorImageInfo depth_info{sampler, depth_view,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur0{{}, target_views[0], vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo old0{{}, snap0, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur1{{}, target_views[1], vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo old1{{}, snap1, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 6> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &lights},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cur0},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &old0},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cur1},
                {.dstBinding = 5, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &old1},
            }};
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const vk::DescriptorImageInfo prev_info{{}, history_prev, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cur_info{{}, history_cur, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 9> ray_writes{
                writes[0], writes[1], writes[2], writes[3], writes[4], writes[5],
                vk::WriteDescriptorSet{.pNext = &scene_info, .dstBinding = 6, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &prev_info},
                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &cur_info}};
            // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1: pixel (2x, 2y) of each 2x2 block
            // (16x16 pixels a workgroup), then the other three, each taking its block's answer
            // or tracing; then what the full-resolution pass does after its dispatch.
            if (half_pipe) {
                if (half_lay_out) {
                    const vk::ImageMemoryBarrier2 to_general{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                         vk::AccessFlagBits2::eShaderWrite,
                        .oldLayout = vk::ImageLayout::eUndefined,
                        .newLayout = vk::ImageLayout::eGeneral,
                        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                        .image = half_image,
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2(
                        {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                if (half_clear) { // the counters start at zero
                    cmdbuf.fillBuffer(half_count_buffer, 0, VK_WHOLE_SIZE, 0);
                    EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                              vk::AccessFlagBits2::eTransferWrite, Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                const vk::DescriptorImageInfo half_info{{}, half_view, vk::ImageLayout::eGeneral};
                const vk::DescriptorBufferInfo count_info{half_count_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 11> half_writes{
                    ray_writes[0], ray_writes[1], ray_writes[2], ray_writes[3], ray_writes[4],
                    ray_writes[5], ray_writes[6], ray_writes[7], ray_writes[8],
                    vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &half_info},
                    vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                                           .pBufferInfo = &count_info}};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipe);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_pipe_layout, 0,
                                            half_writes);
                push.first_light = table;
                push.light_count = tile_count;
                push.rect = covered;
                const u32 mode = std::bit_cast<u32>(push.thickness_m) |
                                 (half_count ? ModeHalfCount : 0u);
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(Push), &push);
                const u32 hx0 = u32(covered[0]) / 16, hy0 = u32(covered[1]) / 16;
                const u32 hx1 = (u32(covered[2]) + 15) / 16, hy1 = (u32(covered[3]) + 15) / 16;
                cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(Push), &push);
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                const vk::MemoryBarrier2 half_after{
                    .srcStageMask = Compute,
                    .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &half_after});
                if (half_count) { // to the host (OnFrameEnd reads it); later counting waits
                    const vk::BufferCopy region{0, 0, HalfSlots * sizeof(u32)};
                    cmdbuf.copyBuffer(half_count_buffer, half_read_buffer, region);
                    EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy,
                                              vk::AccessFlagBits2::eTransferWrite |
                                                  vk::AccessFlagBits2::eTransferRead,
                                              vk::PipelineStageFlagBits2::eHost | Compute,
                                              vk::AccessFlagBits2::eHostRead |
                                                  vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                return;
            }
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            if (use_rays) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, ray_writes);
            } else {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            }
            if (use_rays) {
                push.first_light = table;
                push.light_count = tile_count;
                push.rect = covered;
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                batch.clear();
            }
            for (const Tile& tile : batch) {
                push.first_light = tile.first_light;
                push.light_count = tile.count;
                push.rect = tile.rect;
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push),
                                     &push);
                const u32 gx0 = u32(tile.rect[0]) / 8, gy0 = u32(tile.rect[1]) / 8;
                const u32 gx1 = (u32(tile.rect[2]) + 7) / 8, gy1 = (u32(tile.rect[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            }
            const vk::MemoryBarrier2 after{
                .srcStageMask = Compute,
                .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                 vk::AccessFlagBits2::eMemoryWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        });
}

}
