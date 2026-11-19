// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <charconv>
#include <cstdio>
#include <cstring>
#include <string_view>

#include "bbport_test_camera_run.h"
#include "vk_camera_motion.h"
#include "vk_instance.h"
#include "vk_runtime.h"
#include "vk_scheduler.h"
#include "vk_shader_util.h"
#include "vk_window_path_probe.h"
#include "vk_window_path_scene.h"
#include "vk_window_path_pane_acquisition.h"
#include "video_core/texture_cache/image.h"
#include "video_core/texture_cache/image_view.h"

namespace Vulkan::WindowPathProbe {

struct ReceiverPixel {
    U32 x, y;
    bool operator==(const ReceiverPixel&) const = default;
};

struct DirectionalPixel {
    ReceiverPixel pixel{};
    Vec world{};
    float raw_depth = 0;
    Direct direct{};
    U32 raw_light_set = WP_NONE;
    bool world_valid = false;
};

struct DirectionalBatch {
    Stamp stamp;
    U64 set_uid = 0;
    U32 count = 0;
    std::array<DirectionalPixel, WP_RECEIVERS> pixels{};
};

struct DirectionalSource {
    Stamp stamp;
    U64 fragment_hash = 0, draw = 0, set_uid = 0, output_uid = 0;
    U32 width = 0, height = 0;
    // The caller checks the actual bound descriptor and native pixel addressing, and
    // matches the original G-buffer depth and pass matrices to the same draw.
    bool matched_native_inputs = false;
    bool depth_only = false;
};

inline bool ValidDirectionalSource(const DirectionalSource& source,
                                   std::span<const ReceiverPixel> pixels) {
    if (!source.stamp.request || !source.stamp.frame || !source.stamp.camera ||
        !source.stamp.depth_uid || !source.matched_native_inputs ||
        (source.depth_only
             ? (source.fragment_hash || source.draw || source.set_uid || source.output_uid)
             : (source.fragment_hash != DirectionalFragmentShaderHash ||
                !source.draw || !source.set_uid || !source.output_uid)) ||
        source.width == 0 || source.height == 0 ||
        pixels.empty() || pixels.size() > WP_RECEIVERS) {
        return false;
    }
    for (U32 i = 0; i < pixels.size(); ++i) {
        if (pixels[i].x >= source.width || pixels[i].y >= source.height ||
            std::ranges::find(pixels.first(i), pixels[i]) != pixels.first(i).end()) {
            return false;
        }
    }
    return true;
}

// One diagnostic transfer, with at most two 32-bit texels per receiver. The returned
// world sample locates the nearest depth only. A separate owner/primitive witness is
// required before using it as Receiver evidence. This path cannot emit IsolatedDelta.
class DirectionalReadback {
public:
    DirectionalReadback(const Instance& instance, Scheduler& scheduler, Runtime& runtime)
        : instance(instance), scheduler(scheduler), runtime(runtime) {}
    DirectionalReadback(const DirectionalReadback&) = delete;
    DirectionalReadback& operator=(const DirectionalReadback&) = delete;

    ~DirectionalReadback() {
        if (buffer && !scheduler.IsFree(tick)) {
            const auto allocator = instance.GetAllocator();
            scheduler.DeferOperation([allocator, buffer = buffer, allocation = allocation] {
                vmaDestroyBuffer(allocator, buffer, allocation);
            }, "window directional sample");
        } else {
            Release();
        }
    }

    Status Submit(const DirectionalSource& source, std::span<const ReceiverPixel> points,
                  const CameraMotion::Matrices& camera, VideoCore::Image& depth,
                  const VideoCore::ImageViewInfo& depth_view, VideoCore::Image* light_set = nullptr,
                  const VideoCore::ImageViewInfo* set_view = nullptr) {
        if (!Wanted()) {
            return Status::Disabled;
        }
        if (buffer) {
            return Status::Busy;
        }
        if (source.stamp.request <= last_request) {
            return Status::Stale;
        }
        const auto can_copy = [&](const VideoCore::Image& image) {
            return image.backing && image.GetImage() &&
                   image.backing->state.layout != vk::ImageLayout::eUndefined && image.info.num_samples == 1 &&
                   image.info.size.width == source.width && image.info.size.height == source.height &&
                   image.info.resources.levels == 1 && image.info.resources.layers == 1 &&
                   bool(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc);
        };
        const auto depth_format = depth.info.pixel_format;
        if (!ValidDirectionalSource(source, points) || !camera.valid ||
            depth.image_uid != source.stamp.depth_uid || !can_copy(depth) ||
            (depth_format != vk::Format::eD32Sfloat && depth_format != vk::Format::eD32SfloatS8Uint) ||
            depth_view.format != depth_format || depth_view.range != VideoCore::SubresourceRange{}) {
            return Status::ReceiverEvidence;
        }
        if ((source.depth_only && (light_set || set_view)) ||
            (!source.depth_only &&
             (!light_set || !set_view || light_set->image_uid != source.set_uid ||
              !can_copy(*light_set) || depth.GetImage() == light_set->GetImage() ||
              light_set->info.pixel_format != vk::Format::eR8G8B8A8Unorm ||
              set_view->format != vk::Format::eR8G8B8A8Unorm ||
              set_view->type != AmdGpu::ImageType::Color2D ||
              (set_view->mapping.a != vk::ComponentSwizzle::eIdentity &&
               set_view->mapping.a != vk::ComponentSwizzle::eA) ||
              set_view->range != VideoCore::SubresourceRange{} || set_view->min_lod || set_view->is_storage))) {
            return Status::ReceiverEvidence;
        }

        const VkBufferCreateInfo ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = points.size() * SampleBytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS ||
            !info.pMappedData) {
            Release();
            return Status::Readback;
        }

        last_request = source.stamp.request;
        capture = source;
        matrices = camera;
        count = static_cast<U32>(points.size());
        std::ranges::copy(points, pixels.begin());
        std::array<vk::BufferImageCopy, WP_RECEIVERS> depths{}, sets{};
        for (U32 i = 0; i < count; ++i) {
            depths[i] = vk::BufferImageCopy{
                .bufferOffset = i * SampleBytes,
                .imageSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
                .imageOffset = {s32(pixels[i].x), s32(pixels[i].y), 0},
                .imageExtent = {1, 1, 1},
            };
            sets[i] = depths[i];
            sets[i].bufferOffset += 4;
            sets[i].imageSubresource.aspectMask = vk::ImageAspectFlagBits::eColor;
        }
        const auto depth_layout = depth.backing->state.layout;
        const auto set_layout = light_set ? light_set->backing->state.layout : vk::ImageLayout::eUndefined;
        const auto layout = vk::ImageLayout::eTransferSrcOptimal;
        scheduler.EndRendering();
        runtime.Transit(&depth, layout, vk::PipelineStageFlagBits2::eTransfer,
                        vk::AccessFlagBits2::eTransferRead);
        if (light_set) {
            runtime.Transit(light_set, layout, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
        }
        runtime.FlushBarriers();
        const vk::Buffer target{buffer};
        scheduler.RecordCrumb({.name = "Window directional sample"},
                              [depths, sets, target, n = count, depth_image = depth.GetImage(),
                               set_image = light_set ? light_set->GetImage() : vk::Image{}, layout](vk::CommandBuffer cmd) {
            cmd.copyImageToBuffer(depth_image, layout, target, vk::ArrayProxy<const vk::BufferImageCopy>{n, depths.data()});
            if (set_image) {
                cmd.copyImageToBuffer(set_image, layout, target, vk::ArrayProxy<const vk::BufferImageCopy>{n, sets.data()});
            }
            const vk::MemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eHost,
                .dstAccessMask = vk::AccessFlagBits2::eHostRead,
            };
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &barrier});
        });
        // Restore the native layouts for later users, including cached descriptors. These
        // are read dependencies only, so they do not advance the image's write sequence.
        runtime.Transit(&depth, depth_layout, vk::PipelineStageFlagBits2::eAllCommands,
                        vk::AccessFlagBits2::eMemoryRead);
        if (light_set) {
            runtime.Transit(light_set, set_layout, vk::PipelineStageFlagBits2::eAllCommands,
                            vk::AccessFlagBits2::eMemoryRead);
        }
        runtime.FlushBarriers();
        mapped = static_cast<const u8*>(info.pMappedData);
        tick = scheduler.CurrentTick();
        return Status::Ready;
    }

    // Use the original retained identity or a new stamp to discard stale evidence.
    // Busy means no completion yet. A stale/refused result leaves output empty.
    Status Poll(const Stamp& expected, DirectionalBatch& output) {
        output = {};
        if (!buffer) {
            return Status::Readback;
        }
        if (!scheduler.IsFree(tick)) {
            return Status::Busy;
        }
        if (capture.stamp != expected) {
            Release();
            return Status::Stale;
        }
        if (vmaInvalidateAllocation(instance.GetAllocator(), allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            Release();
            return Status::Readback;
        }
        output.stamp = capture.stamp;
        output.set_uid = capture.set_uid;
        output.count = count;
        for (U32 i = 0; i < count; ++i) {
            auto& sample = output.pixels[i];
            sample.pixel = pixels[i];
            const auto [x, y] = pixels[i];
            const float nx = 2.0f * (float(x) + 0.5f) / float(capture.width) - 1.0f;
            const float ny = 2.0f * (float(y) + 0.5f) / float(capture.height) - 1.0f;
            std::memcpy(&sample.raw_depth, mapped + i * SampleBytes, sizeof(float));
            float view_z = 0;
            sample.world_valid = BbTestCamera::WorldFromDepth(
                matrices.inv_view.data(), matrices.proj.data(), sample.raw_depth, nx, ny,
                sample.world.data(), &view_z);
            if (!capture.depth_only) {
                sample.raw_light_set = mapped[i * SampleBytes + 7];
            }
            if (!capture.depth_only && sample.world_valid && capture.stamp.Valid()) {
                sample.direct = Direct{.stamp = capture.stamp, .draw = capture.draw,
                                       .output_uid = capture.output_uid, .x = x, .y = y,
                                       .light_set = sample.raw_light_set,
                                       .kind = DirectKind::LightSetOnly};
            }
        }
        Release();
        return Status::Ready;
    }

private:
    void Release() {
        if (buffer) {
            vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            buffer = VK_NULL_HANDLE;
            mapped = nullptr;
        }
    }

    static constexpr U32 SampleBytes = sizeof(float) + 4;
    static_assert(SampleBytes == 8);
    const Instance& instance;
    Scheduler& scheduler;
    Runtime& runtime;
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    U64 tick = 0, last_request = 0;
    DirectionalSource capture{};
    CameraMotion::Matrices matrices{};
    U32 count = 0;
    std::array<ReceiverPixel, WP_RECEIVERS> pixels{};
};

struct PixelRequest {
    U32 id = 0, width = 0, height = 0, count = 0;
    std::array<ReceiverPixel, WP_RECEIVERS> pixels{};

    std::span<const ReceiverPixel> Points() const { return {pixels.data(), count}; }
};

// Native texels, no scaled display coordinates. A purely diagnostic request
// can locate a receiving surface before any guarded scene/owner proof is available.
inline bool ParsePixelRequest(std::string_view text, PixelRequest& result) {
    std::array<U32, 3 + 2 * WP_RECEIVERS> fields{};
    U32 n = 0;
    if (text.empty() || text.size() > 12 * fields.size()) {
        return false;
    }
    do {
        const auto split = text.find(':');
        const auto field = text.substr(0, split);
        if (field.empty() || n == fields.size()) {
            return false;
        }
        const auto [end, error] = std::from_chars(field.data(), field.data() + field.size(), fields[n++]);
        if (error != std::errc{} || end != field.data() + field.size()) {
            return false;
        }
        if (split == std::string_view::npos) {
            break;
        }
        text.remove_prefix(split + 1);
    } while (true);
    if (n < 5 || !(n & 1u) || !fields[0] || !fields[1] || !fields[2] ||
        fields[1] > 16384 || fields[2] > 16384) {
        return false;
    }
    PixelRequest parsed{.id = fields[0], .width = fields[1], .height = fields[2]};
    for (U32 i = 3; i < n; i += 2) {
        const ReceiverPixel pt{fields[i], fields[i + 1]};
        if (pt.x >= parsed.width || pt.y >= parsed.height ||
            std::ranges::find(parsed.Points(), pt) != parsed.Points().end()) {
            return false;
        }
        parsed.pixels[parsed.count++] = pt;
    }
    result = parsed;
    return true;
}

struct ReceiverCapture {
    ReceiverCapture(const Instance& instance, Scheduler& scheduler, Runtime& runtime,
                    PixelRequest wanted)
        : request(wanted), copy(instance, scheduler, runtime) {}

    static constexpr U32 FrameBudget = 90;
    PixelRequest request;
    DirectionalReadback copy;
    SceneObservation scene;
    std::unique_ptr<PaneAcquisition> pane;
    U32 pane_sample = WP_NONE;
    RtLampPane::Camera depth_camera{};
    std::array<float, 2> depth_jitter{};
    Stamp pending{};
    U64 ordinal = 0, sampled_draw = 0;
    U32 frames = 0;
    VideoCore::ImageId set_id{};
    U64 set_uid = 0;
    VideoCore::ImageViewInfo set_view{};
    const char* refusal = "no matching native directional pass";

    void BeginFragment(U64 hash) {
        set_id = {};
        set_uid = 0;
        if (hash == DirectionalFragmentShaderHash) {
            ++ordinal;
        }
    }

    void Bind(VideoCore::ImageId id, U64 uid, const VideoCore::ImageViewInfo& view) {
        set_id = id;
        set_uid = uid;
        set_view = view;
    }
};

} // namespace Vulkan::WindowPathProbe
