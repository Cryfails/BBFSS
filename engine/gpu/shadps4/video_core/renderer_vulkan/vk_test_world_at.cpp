// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r120_test-camera-lookat, TOOL): BB_TEST_WORLD_AT; see vk_test_world_at.h.
#include "video_core/renderer_vulkan/vk_test_world_at.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include "bbport_test_camera_run.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace TC = BbTestCamera;
constexpr u64 TexelStride = 16; ///< bytes between the texels in the host buffer (each copy lands at a multiple of 4)
} // namespace

/// One read on its way: the wanted pixels, the texels they fell on, the camera of the pass the depth belongs to and the copy's
/// host buffer.
struct TestWorldAt::Job {
    TC::WorldJob want;
    std::array<u32, TC::kPixelsMost + TC::kCentreCount> texel_x{}, texel_y{};
    u32 width = 0, height = 0;
    bool proxy = false;
    std::array<float, 12> inv_view{};
    std::array<float, 4> proj{};
    std::array<float, 3> camera{};
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    u64 tick = 0, frame = 0;
};

TestWorldAt::TestWorldAt(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                         Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    std::printf("GLINT-PROOF world at (r120): BB_TEST_WORLD_AT / BB_TEST_CAMERA=lookat:centre: made; each read copies the depth "
                "buffer's texel under each pixel of a 1920x1080 picture at the upscaler's trigger and prints its world position "
                "at the next frame end (no pipeline, no image: one transfer and a small host buffer a read)\n");
}

TestWorldAt::~TestWorldAt() {
    if (job && job->buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), job->buffer, job->allocation);
    }
}

void TestWorldAt::OnScene(VideoCore::ImageId depth_id, u64 frame) {
    if (job || !depth_id) {
        return;
    }
    TC::WorldJob want;
    if (!TC::TakeWorldJob(&want)) {
        return;
    }
    const auto refuse = [&](const char* why) {
        std::printf("GLINT-PROOF world at (r120): not read (%s)\n", why);
        if (want.centre) {
            const float none[3] = {};
            TC::PublishCentre(want.centre_serial, false, none, why);
        }
    };
    // The camera of the last G-buffer pass (it goes with the depth); the frame's committed camera if that one is not read.
    CameraMotion::Matrices matrices = camera_motion.PassMatrices();
    if (!matrices.valid) {
        matrices = camera_motion.CameraMatrices();
    }
    if (!matrices.valid && matrices.proj[0] == 0.0f) {
        refuse("no camera has been read yet");
        return;
    }
    auto& image = texture_cache.GetImage(depth_id);
    const vk::Format format = image.info.pixel_format;
    if (format != vk::Format::eD32Sfloat && format != vk::Format::eD32SfloatS8Uint) {
        refuse("the depth buffer is not a 32-bit float depth format");
        return;
    }
    if (image.info.num_samples > 1) {
        refuse("the depth buffer is multisampled");
        return;
    }
    const bool proxy = scene_targets.Reduced() && scene_targets.Eligible(image) && scene_targets.ProxyCurrent(image);
    if (!proxy && !(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
        refuse("the depth buffer cannot be copied from (no transfer-source usage)");
        return;
    }
    u32 width = image.info.size.width, height = image.info.size.height;
    if (proxy) {
        const auto size = scene_targets.ProxySize(image);
        width = size.width;
        height = size.height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] != 0 && render[1] != 0) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width == 0 || height == 0) {
        refuse("the depth buffer has no size");
        return;
    }
    auto made = std::make_unique<Job>();
    made->want = want;
    made->width = width;
    made->height = height;
    made->proxy = proxy;
    made->inv_view = matrices.inv_view;
    made->proj = matrices.proj;
    made->camera = {matrices.inv_view[3], matrices.inv_view[7], matrices.inv_view[11]};
    made->frame = frame;
    for (unsigned i = 0; i < want.n; ++i) {
        made->texel_x[i] = u32(std::min<u64>(u64(want.px[i].x) * width / TC::kPictureW, width - 1));
        made->texel_y[i] = u32(std::min<u64>(u64(want.px[i].y) * height / TC::kPictureH, height - 1));
    }
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = u64(want.n) * TexelStride,
        .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    const VmaAllocationCreateInfo alloc_ci{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
    };
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation, &info) != VK_SUCCESS ||
        !info.pMappedData) {
        if (buffer) {
            vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
        }
        refuse("no host memory for the copy");
        return;
    }
    scheduler.EndRendering();
    vk::Image source;
    vk::ImageLayout layout{};
    if (proxy) {
        VideoCore::ImageViewInfo view_info;
        view_info.format = format;
        const auto target = scene_targets.Read(depth_id, view_info, vk::PipelineStageFlagBits2::eTransfer,
                                               vk::AccessFlagBits2::eTransferRead);
        if (!(target.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
            vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            refuse("the reduced scene's depth proxy cannot be copied from");
            return;
        }
        source = target.image;
        layout = target.layout;
    } else {
        runtime.Transit(&image, vk::ImageLayout::eTransferSrcOptimal, vk::PipelineStageFlagBits2::eTransfer,
                        vk::AccessFlagBits2::eTransferRead);
        source = image.GetImage();
        layout = vk::ImageLayout::eTransferSrcOptimal;
    }
    auto regions = std::make_shared<std::vector<vk::BufferImageCopy>>();
    for (unsigned i = 0; i < want.n; ++i) {
        regions->push_back(vk::BufferImageCopy{
            .bufferOffset = u64(i) * TexelStride,
            .imageSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
            .imageOffset = {s32(made->texel_x[i]), s32(made->texel_y[i]), 0},
            .imageExtent = {1, 1, 1},
        });
    }
    runtime.FlushBarriers();
    const vk::Buffer target_buffer{buffer};
    scheduler.RecordCrumb({.name = "Test world at readback"}, [regions, source, layout, target_buffer](vk::CommandBuffer cmdbuf) {
        cmdbuf.copyImageToBuffer(source, layout, target_buffer, *regions);
        const vk::MemoryBarrier2 to_host{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
    });
    made->buffer = buffer;
    made->allocation = allocation;
    made->mapped = static_cast<const u8*>(info.pMappedData);
    made->tick = scheduler.CurrentTick();
    job = std::move(made);
}

void TestWorldAt::OnFrameEnd() {
    if (!job || !scheduler.IsFree(job->tick)) {
        return;
    }
    Job& j = *job;
    vmaInvalidateAllocation(instance.GetAllocator(), j.allocation, 0, VK_WHOLE_SIZE);
    bool centre_ok = false;
    float centre_world[3] = {};
    const char* centre_why = "no world point among the picture's middle pixels (sky, or beyond 300 m)";
    TC::CentreCandidate cand[TC::kCentreCount] = {}; // r120c: the centre read's pixels, picked below
    for (unsigned i = 0; i < j.want.n; ++i) {
        float depth = 0.0f;
        std::memcpy(&depth, j.mapped + u64(i) * TexelStride, sizeof depth);
        const TC::Pixel p = j.want.px[i];
        const float nx = 2.0f * (float(j.texel_x[i]) + 0.5f) / float(j.width) - 1.0f;
        const float ny = 2.0f * (float(j.texel_y[i]) + 0.5f) / float(j.height) - 1.0f;
        float world[3] = {};
        float view_z = 0.0f;
        const bool ok = TC::WorldFromDepth(j.inv_view.data(), j.proj.data(), depth, nx, ny, world, &view_z);
        const bool is_centre = j.want.centre && i >= j.want.user && i < j.want.user + TC::kCentreCount;
        char head[200];
        std::snprintf(head, sizeof head, "pixel %d,%d of %ux%u%s (texel %u,%u of %ux%u%s) at frame %llu: depth %.6f", p.x, p.y,
                      TC::kPictureW, TC::kPictureH, is_centre ? (i == j.want.user ? ", the middle" : ", near the middle") : "",
                      j.texel_x[i], j.texel_y[i], j.width, j.height, j.proxy ? ", reduced scene" : "",
                      static_cast<unsigned long long>(j.frame), double(depth));
        if (ok) {
            std::printf("GLINT-PROOF world at (r120): %s, %.2f m in front of the camera, world %.3f %.3f %.3f (camera %.3f %.3f %.3f)\n",
                        head, double(view_z), double(world[0]), double(world[1]), double(world[2]), double(j.camera[0]),
                        double(j.camera[1]), double(j.camera[2]));
        } else {
            std::printf("GLINT-PROOF world at (r120): %s: no point (sky, or beyond 300 m, or the depth is not a number)\n", head);
        }
        if (is_centre) { // r120c: collected, then picked below: the middle is the hunter (2.7 to 3.6 m ahead of the camera), who is no target
            TC::CentreCandidate& c = cand[i - j.want.user];
            c.ok = ok;
            c.view_z = view_z;
            std::memcpy(c.world, world, sizeof c.world);
        }
    }
    if (j.want.centre) {
        bool far_enough = false;
        const int pick = TC::PickCentre(cand, TC::kCentreCount, TC::kCentreMinView, &far_enough);
        if (pick >= 0) {
            centre_ok = true;
            std::memcpy(centre_world, cand[pick].world, sizeof centre_world);
            const TC::Pixel pp = j.want.px[j.want.user + static_cast<unsigned>(pick)];
            std::printf("GLINT-PROOF world at (r120c): the centre read takes pixel %d,%d: %.2f m in front of the camera, world %.3f %.3f %.3f%s\n", pp.x, pp.y,
                        double(cand[pick].view_z), double(centre_world[0]), double(centre_world[1]), double(centre_world[2]),
                        far_enough ? "" : " (no pixel of the read is 5 m or more away: the farthest one; the hunter may fill the read)");
        }
        TC::PublishCentre(j.want.centre_serial, centre_ok, centre_world, centre_ok ? "" : centre_why);
    }
    vmaDestroyBuffer(instance.GetAllocator(), j.buffer, j.allocation);
    job.reset();
}

} // namespace Vulkan
