// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's GPU passes (vk_wind_shelter.h; the numbers in
// bbport_wind_shelter.h, the passes in host_shaders/wind_shelter.comp). The structure of
// vk_heat_haze.cpp: one effect pass pipeline (two builds of one shader), push descriptors, a crumb
// recorded at the place before the upscaler, a host copy of the counters for the log.

#include "video_core/renderer_vulkan/vk_wind_shelter.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/host_shaders/wind_shelter_comp.h"
#include "video_core/host_shaders/wind_shelter_show_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_volumetric_light.h" // bbport (r115c_roof-rule-not-trees): VolumetricLight::RoofMode
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u32 LineFrames = 300; ///< r117e: was 600 (a 40 s test run never reached the second line)
constexpr u32 FirstLineFrames = 60; ///< the first line comes sooner, for short test runs (r117f: was 120 passes)
constexpr u32 FirstLineSure = 240;  ///< r117f: or after this many frames, once ReportMinPasses passes were made
constexpr u32 ReportMinPasses = 20; ///< r117f: no report from loading frames (a line with 0 samples is not a view)
constexpr u64 ProfileRow = 117;      ///< EffectPass::Mark: the row "Lighting: wind shelter"
constexpr float MaxStep = 0.1f;      ///< s: the longest dt a pass is given

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = info};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = info};
}
} // namespace

bool WindShelter::Wanted() {
    return BbWindShelter::KnobOnce().on;
}

WindShelter::WindShelter(const Instance& instance_, Scheduler& scheduler_,
                         VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                         SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_},
      knobs{BbWindShelter::KnobOnce()} {
    using enum vk::DescriptorType;
    made = EffectPass::Create(instance, set_layout, layout, pipeline,
                              {eSampledImage, eStorageBuffer, eStorageBuffer},
                              sizeof(BbWindShelter::Push), WIND_SHELTER_COMP, "Wind shelter") &&
           MakeBuffer(state_buffer,
                      (vk::DeviceSize(WS_M) * WS_M * (WS_CELL_WORDS + WS_FRESH_WORDS) + WS_GLOBAL_WORDS) *
                          4,
                      false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_buffer, WS_COUNTER_WORDS * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferSrc |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_host, WS_COUNTER_WORDS * 4, true,
                      vk::BufferUsageFlagBits::eTransferDst);
    if (made) {
        std::memset(counter_host.mapped, 0, WS_COUNTER_WORDS * 4);
    }
    show_made = made && knobs.show != 0 &&
                EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
                EffectPass::Create(instance, show_set_layout, show_layout, show_pipeline,
                                   {eSampledImage, eStorageBuffer, eStorageBuffer, eStorageImage},
                                   sizeof(BbWindShelter::Push), WIND_SHELTER_SHOW_COMP,
                                   "Wind shelter view");
    BbReport::Printf("Wind shelter (r117, BB_WIND_SHELTER=%.2f): %s; a field of %ux%u cells of %.0f "
                     "m around the camera from the scene depth (no ray tracing), %u upwind rays "
                     "of %u m with a median, roofs; read per vertex by the plants, at the camera "
                     "by the fog drift and the particles; drawn right before the upscaler; test "
                     "view %s\n",
                     double(knobs.strength), made ? "on" : "off - the passes could not be made",
                     BbWindShelter::N, BbWindShelter::N, double(BbWindShelter::Cell), 3u,
                     BbWindShelter::Steps,
                     knobs.show == 0 ? "off"
                     : show_made     ? (knobs.show == 2 ? "on (alone on black)" : "on (over the scene)")
                                     : "requested but not made");
}

WindShelter::~WindShelter() {
    FreeBuffer(state_buffer);
    FreeBuffer(counter_buffer);
    FreeBuffer(counter_host);
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool WindShelter::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void WindShelter::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

void WindShelter::NoSceneHooks() {
    BbReport::Printf("Wind shelter (r117): not drawn - the upscaler is not available "
                     "(BB_UPSCALER=none, or this GPU cannot run it), and the field is made right "
                     "before it: nothing reads a field, the wind is as it was\n");
}

float WindShelter::CameraOpen() const {
    if (!made || !counter_host.mapped || frame == 0) {
        return 1.0f;
    }
    std::uint32_t word = 0;
    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_CAMERA * 4, 4);
    return BbWindShelter::Open(BbWindShelter::CameraShelter(word));
}

float WindShelter::CameraCover() const {
    // bbport (r115b_sun-fog-out-of-sewer-library): -1 = no cover known (the sun fog rule then keeps the fog)
    if (!made || !counter_host.mapped || frame == 0) {
        return -1.0f;
    }
    std::uint32_t word = 0;
    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_ROOF * 4, 4); // bbport (r115c): the roof share
    return BbWindShelter::CameraShelter(word);
}

vk::ImageView WindShelter::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create wind shelter view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void WindShelter::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                        std::array<float, 2> jitter, u64 region, const BbWind::Snapshot& wind) {
    ++stats.frames;
    const auto done = [&] {
        // the first line after FirstLineFrames passes (the hook also runs through the loading screen,
        // where nothing is drawn), or after LineFrames frames whatever happened
        // r117f: a report needs ReportMinPasses passes (else only after 4 x LineFrames frames: the diagnostic of an
        // effect that never runs); the first comes after FirstLineFrames passes or FirstLineSure frames
        if (stats.frames >= 4 * LineFrames ||
            (stats.passes >= ReportMinPasses &&
             (stats.frames >= (reported ? LineFrames : FirstLineSure) ||
              (!reported && stats.passes >= FirstLineFrames)))) {
            reported = true;
            Report();
        }
    };
    if (!made || region == 0 || !wind.on || !color_id || !depth_id) {
        ++stats.no_region;
        done();
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid) {
        ++stats.no_camera;
        done();
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    // The scene's size is the reduced one while a preset renders below the game's own size, else
    // the game's render size (its targets may be allocated larger): as the heat haze takes it.
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16 ||
        (show_made && color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat)) {
        ++stats.no_scene;
        done();
        return;
    }
    const bool show = show_made;
    const SceneUseScope scene_use{"wind shelter"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (show && !(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (show && !(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        if (show) {
            color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        }
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    const auto now = std::chrono::steady_clock::now();
    const float dt = last_pass == std::chrono::steady_clock::time_point{}
                         ? 0.0f
                         : std::min(std::chrono::duration<float>(now - last_pass).count(), MaxStep);
    last_pass = now;
    ++frame;
    const auto& iv = camera.inv_view;
    BbWindShelter::Push push{};
    push.region = region;
    push.frame = frame;
    push.row0 = {iv[0], iv[1], iv[2], iv[3]};
    push.row1 = {iv[4], iv[5], iv[6], iv[7]};
    push.row2 = {iv[8], iv[9], iv[10], iv[11]};
    push.proj = camera.proj;
    push.size_jitter = {float(width), float(height), jitter[0], jitter[1]};
    push.wind = {wind.dir_x, wind.dir_z, dt, knobs.strength};
    push.cells = {s32(std::floor(iv[3] / BbWindShelter::Cell)),
                  s32(std::floor(iv[11] / BbWindShelter::Cell)), knobs.show == 2 ? 1 : 0,
                  VolumetricLight::RoofMode() != 0 ? 1 : 0}; // bbport (r115c): the roof rule's measure on
    const bool first = !std::exchange(zeroed, true);
    ++stats.passes;
    if (!told_size) {
        told_size = true;
        BbReport::Printf("Wind shelter (r117): first pass at a scene of %ux%u (%s), %ux%u depth "
                         "samples a frame\n",
                         width, height, reduced ? "reduced scene" : "the game's scene",
                         (width + WS_STRIDE - 1) / WS_STRIDE, (height + WS_STRIDE - 1) / WS_STRIDE);
    }
    EffectPass::Mark(ProfileRow, "wind shelter");
    scheduler.RecordCrumb(
        {.name = "wind shelter"},
        [push, width, height, first, show, depth_view, color_view,
         state = state_buffer.buffer, counters = counter_buffer.buffer,
         host = counter_host.buffer, pass_pipeline = *pipeline, pass_layout = *layout,
         view_pipeline = show ? *show_pipeline : vk::Pipeline{},
         view_layout = show ? *show_layout : vk::PipelineLayout{}](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (first) {
                cmdbuf.fillBuffer(state, 0, VK_WHOLE_SIZE, 0);
                cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute,
                                          ReadWrite);
            }
            const vk::DescriptorImageInfo depth_info{
                {}, depth_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo state_info{state, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};
            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};
            const auto run = [&](vk::PipelineLayout run_layout, u32 mode, u32 gx, u32 gy) {
                BbWindShelter::Push p = push;
                p.mode = mode;
                cmdbuf.pushConstants(run_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(p),
                                     &p);
                cmdbuf.dispatch(gx, gy, 1);
            };
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array writes{
                ImageWrite(0, vk::DescriptorType::eSampledImage, &depth_info),
                BufferWrite(1, &state_info), BufferWrite(2, &counter_info)};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            const u32 group = WS_GROUP;
            const u32 cache_groups = WS_M / group, window_groups = WS_N / group;
            const u32 splat_x = ((width + WS_STRIDE - 1) / WS_STRIDE + group - 1) / group;
            const u32 splat_y = ((height + WS_STRIDE - 1) / WS_STRIDE + group - 1) / group;
            if (first) {
                run(pass_layout, WS_MODE_CLEAR, cache_groups, cache_groups);
                EffectPass::ComputeBarrier(cmdbuf);
            }
            run(pass_layout, WS_MODE_SPLAT, splat_x, splat_y);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_MERGE, cache_groups, cache_groups);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_RAW, window_groups, window_groups);
            EffectPass::ComputeBarrier(cmdbuf);
            run(pass_layout, WS_MODE_FINAL, window_groups, window_groups);
            if (show) {
                EffectPass::ComputeBarrier(cmdbuf);
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, view_pipeline);
                const std::array view_writes{
                    ImageWrite(0, vk::DescriptorType::eSampledImage, &depth_info),
                    BufferWrite(1, &state_info), BufferWrite(2, &counter_info),
                    ImageWrite(3, vk::DescriptorType::eStorageImage, &color_info)};
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, view_layout, 0,
                                            view_writes);
                run(view_layout, WS_MODE_SHOW, (width + group - 1) / group,
                    (height + group - 1) / group);
            }
            // The field (host visible memory the vertex shaders read) and the scene are final.
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, WS_COUNTER_WORDS * 4});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    done();
}

void WindShelter::Report() {
    std::array<u32, WS_COUNTER_WORDS> now{};
    if (counter_host.mapped) {
        std::memcpy(now.data(), counter_host.mapped, sizeof(now));
    }
    const auto c = BbWindShelter::CountsBetween(now.data(), counters_seen.data());
    counters_seen = now;
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    const double cells = std::max(1.0, double(c.cells));
    // r117b: the camera's smoothed covered share (WS_C_COVER) and the cover it maps to
    const float cover_share = BbWindShelter::CameraShelter(now[WS_C_COVER]);
    // Two lines, each under 300 characters (the slot runs keep that much of a line).
    BbReport::Printf("Wind shelter (r117): %u frames before the upscaler, %u passes; the view: "
                     "%.1f%% of %llu depth samples sheltered (field above 0.5), %.1f%% indoors "
                     "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f); "
                     "hits %llu: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall %.0f%% far\n",
                     stats.frames, stats.passes, 100.0 * BbWindShelter::ViewSheltered(c),
                     ull(c.pixels), 100.0 * BbWindShelter::ViewIndoor(c),
                     BbWindShelter::ViewMean(c), double(1.0f - CameraOpen()),
                     double(BbWindShelter::CoverIndoors(cover_share)), double(cover_share),
                     ull(c.thin_seen), // r117d/r117e numbers on the line every run keeps
                     100.0 * double(c.thin_low) / std::max(1.0, double(c.thin_seen)),
                     100.0 * double(c.thin_narrow) / std::max(1.0, double(c.thin_seen - c.thin_low)),
                     100.0 * double(c.thin_kept) / std::max(1.0, double(c.thin_seen)),
                     100.0 * double(c.thin_tall) / std::max(1.0, double(c.thin_kept)),
                     100.0 * double(c.far_cut) / std::max(1.0, double(c.thin_seen))); // r117f: of all hits (at most 100%)
    // r117g: its own line, with the view line (the first report too: the runner keeps the first and the last of a kind)
    BbReport::Printf("Wind shelter (r117g): %.1f%% of the %llu hits cut by the cell's own height, %.1f%% of the seen cells "
                     "are tall (%.0f m+); a low thing's lee %.1f m, keep %.1f\n",
                     100.0 * double(c.self_cut) / std::max(1.0, double(c.thin_seen)), ull(c.thin_seen),
                     100.0 * double(c.self_cells) / std::max(1.0, double(c.cells_seen)), double(WS_SELF_H_HI),
                     double(WS_SHORT_REACH), double(WS_SELF_KEEP));
    // bbport (r115c_roof-rule-not-trees): BB_VOLUMETRIC_ROOF=1 only: what the roof rule reads (the smoothed roof share, the
    // share of all climbing rays that are roof, and the old overhead share beside them)
    if (VolumetricLight::RoofMode() != 0) {
        BbReport::Printf("Wind shelter (r115c): roof share %.2f (all climbing rays %.2f; the wind's overhead share %.2f); "
                         "a roof ray ends within %.0f m on a solid surface, the share is the smallest of the 4 quadrants\n",
                         double(BbWindShelter::CameraShelter(now[WS_C_ROOF])),
                         double(BbWindShelter::CameraShelter(now[WS_C_ROOF_ALL])), double(cover_share),
                         double(WS_ROOF_DIST));
    }
    // r117f: the first report is the view line alone (the runner keeps 30 lines of the features under test, in the
    // order they first appear: the view line must be early and one kind); the others come with the second report
    static bool view_told = false;
    if (!std::exchange(view_told, true)) {
        stats = {};
        return;
    }
    BbReport::Printf("Wind shelter (r117): the window: %.0f of %llu cells with depth data a frame "
                     "(%.1f%%), %.1f%% of the cells sheltered, mean %.3f; %.0f cache cells "
                     "updated a frame; skipped %u without the region or wind, %u without a "
                     "camera, %u without a usable scene\n",
                     double(c.cells_seen) / std::max(1.0, double(stats.passes)), ull(c.cells),
                     100.0 * double(c.cells_seen) / cells, 100.0 * double(c.cells_sheltered) / cells,
                     double(c.cells_sum) / 1000.0 / cells,
                     double(c.merged) / std::max(1.0, double(stats.passes)), stats.no_region,
                     stats.no_camera, stats.no_scene);
    // r117c: where the climbing view rays ended (the camera's cover is made from the ones in the first two
    // groups); the rest ended on the sky, a dome or beyond 80 m
    const double up = std::max(1.0, double(c.climb_up));
    BbReport::Printf("Wind shelter (r117c): %llu climbing view rays: %.1f%% ended within %.0f m, %.1f%% on "
                     "a surface facing down (to %.0f m), %.1f%% on another surface within %.0f m, %.1f%% "
                     "on the sky or beyond\n",
                     ull(c.climb_up), 100.0 * double(c.climb_close) / up, double(WS_COVER_CLOSE),
                     100.0 * double(c.climb_down) / up, double(WS_COVER_DIST),
                     100.0 * double(c.climb_mid) / up, double(WS_COVER_DIST),
                     100.0 * (up - double(c.climb_close + c.climb_down + c.climb_mid)) / up);
    // r117d: the obstacle cells the raw pass's rays met that would have raised a ray's value: how many were low
    // (a height weight under 0.5), and of the rest how many were thin (a width weight under 0.5)
    const double met = std::max(1.0, double(c.thin_seen));
    BbReport::Printf("Wind shelter (r117d): %llu obstacle cells met by the rays, %.1f%% low (under 1.6 m), "
                     "%.1f%% of the rest thin (one or two cells wide)\n",
                     ull(c.thin_seen), 100.0 * double(c.thin_low) / met,
                     100.0 * double(c.thin_narrow) / std::max(1.0, double(c.thin_seen - c.thin_low)));
    stats = {};
}

} // namespace Vulkan
