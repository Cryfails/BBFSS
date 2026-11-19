// SPDX-License-Identifier: GPL-2.0-or-later
#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"
#include "video_core/renderer_vulkan/vk_sewer_display_bridge.h"
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
#include <limits>
#include "video_core/renderer_vulkan/vk_bottle_raw_search_b177.h"
#include "video_core/renderer_vulkan/vk_bottle_display_evidence_b182.h"
#include "video_core/renderer_vulkan/vk_bottle_raw_apply_b180.h"
#endif
#include "engine/loading.h"
#include <bit>
#include "video_core/renderer_vulkan/vk_bottle_caustic.h"
#include "video_core/renderer_vulkan/vk_workflow_present.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "video_core/renderer_vulkan/motion_history.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/ui_composition.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>

#include <vk_mem_alloc.h>

#include "bbport_sections.h"
#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "bbport_test_goto_walk.h" // bbport (r112o_hang-safe-goto, TOOL): BB_TEST_GOTO holds a capture while the target is not framed
#include "bbport_test_camera.h" // bbport (r120_test-camera-lookat, TOOL): BB_TEST_CAMERA holds a capture while its camera is not at its place
#include "ffx_vk_portable.h"
#include "video_core/host_shaders/upscale_merge_comp.h"
#include "video_core/host_shaders/upscale_debug_comp.h"
#include "video_core/host_shaders/upscale_debug_ldr_comp.h"
#include "video_core/host_shaders/upscale_reactive_comp.h"
#include "video_core/host_shaders/taa_comp.h"
#include "video_core/host_shaders/taa_sharpen_comp.h"
#include "video_core/host_shaders/taa_sharpen_ldr_comp.h"
#include "video_core/host_shaders/fsr4_decode_comp.h"
#include "video_core/host_shaders/fsr4_encode_comp.h"
#include "video_core/host_shaders/fsr4_reactive_comp.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/drawn_look_params.h" // bbport (r55_drawn-look-lines)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_frame_capture.h"
#include "video_core/renderer_vulkan/vk_frame_generation.h"
#include "video_core/renderer_vulkan/vk_hdr_native.h"
#include "video_core/renderer_vulkan/vk_interior_exposure.h" // bbport (r99_interior-exposure)
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
#ifdef BB_TEST_SHARED_POST_GRAPH
#include "shader_recompiler/native/gt7_tonemap.h"
#endif

namespace Vulkan {

struct SewerMotion::VendorCapture {
    explicit VendorCapture(std::shared_ptr<Checkpoint> sample) : checkpoint(std::move(sample)) {}
    ~VendorCapture() {
        if (buffer) vmaDestroyBuffer(allocator, buffer, allocation);
    }

    const std::shared_ptr<Checkpoint> checkpoint;
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    VkBuffer buffer{};
    const std::byte* mapped{};
    const char* refused{};
    bool copied{}, successful{};
    u64 tick{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    Fsr4Upscaler::Image consumed_color{}, actual_output{};
#endif

    static constexpr vk::DeviceSize InputBytes = sizeof(Samples);
    static constexpr vk::DeviceSize OutputBytes = sizeof(Patches);
    static constexpr vk::DeviceSize Bytes = InputBytes + OutputBytes;
    static_assert(InputBytes == 24 && OutputBytes == 216 && sizeof(HalfPixel) == 8);

    bool Allocate(VmaAllocator vma) {
        allocator = vma;
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                    .size = Bytes, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(allocator, &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) return false;
        mapped = static_cast<const std::byte*>(info.pMappedData);
        return mapped != nullptr;
    }

    static void Copy(vk::CommandBuffer cmd, vk::Image image, vk::Buffer destination,
                     const std::array<vk::BufferImageCopy, 3>& regions) {
        constexpr auto all = vk::PipelineStageFlagBits2::eAllCommands;
        constexpr auto all_transfer = vk::PipelineStageFlagBits2::eAllTransfer;
        constexpr auto rw = vk::AccessFlagBits2::eMemoryWrite | vk::AccessFlagBits2::eMemoryRead;
        constexpr auto transfer_read = vk::AccessFlagBits2::eTransferRead;
        const vk::ImageMemoryBarrier2 entering{
            .srcStageMask = all, .srcAccessMask = rw,
            .dstStageMask = all_transfer, .dstAccessMask = transfer_read,
            .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eTransferSrcOptimal,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image, .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &entering});
        cmd.copyImageToBuffer(image, entering.newLayout, destination, regions);
        auto leaving = entering;
        leaving.srcStageMask = all_transfer;
        leaving.srcAccessMask = transfer_read;
        leaving.dstStageMask = all;
        leaving.dstAccessMask = rw;
        leaving.oldLayout = entering.newLayout;
        leaving.newLayout = entering.oldLayout;
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &leaving});
    }

    void Read(const Fsr4Upscaler::Frame& frame, bool output) const {
        std::array<vk::BufferImageCopy, 3> regions{};
        for (u32 i = 0; i < regions.size(); ++i) {
            const auto& pixel = checkpoint->warp.px[i];
            const auto& centre = checkpoint->pose.output[i];
            const s32 x = output ? static_cast<s32>(centre[0]) - 1 : pixel.x;
            const s32 y = output ? static_cast<s32>(centre[1]) - 1 : pixel.y;
            const u32 side = output ? 3 : 1;
            regions[i] = {
                .bufferOffset = (output ? InputBytes : 0) + i * side * side * sizeof(HalfPixel),
                .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                .imageOffset = {x, y, 0},
                .imageExtent = {side, side, 1},
            };
        }
        Copy(frame.cmdbuf, output ? frame.output.image : frame.color.image, vk::Buffer(buffer), regions);
    }

    void Begin(VmaAllocator vma, const Fsr4Upscaler::Frame& frame, bool is_dlss, u64 at_tick,
               const vk::ImageCreateInfo& output_info, int model_hint) {
        tick = at_tick;
        if (!is_dlss || frame.reset || frame.preset != BbSettings::Performance ||
            (model_hint != BbSettings::DlssPresetAuto && model_hint != BbSettings::DlssPresetM) ||
            !frame.color.view || !frame.depth.view || !frame.motion.view ||
            !frame.output.image || !frame.output.view ||
            frame.output.image == frame.color.image ||
            frame.output.format != vk::Format::eR16G16B16A16Sfloat ||
            output_info.format != frame.output.format || output_info.extent != vk::Extent3D{3840, 2160, 1} ||
            output_info.mipLevels != 1 || output_info.arrayLayers != 1 ||
            output_info.samples != vk::SampleCountFlagBits::e1 ||
            !(output_info.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
            refused = !is_dlss ? "vendor-fallback" : frame.reset ? "vendor-history-reset" : "actual-vendor-resources";
            return;
        }
        if (!Allocate(vma)) {
            refused = "vendor-staging-allocation";
            return;
        }
        copied = true;
        Read(frame, false);
        const auto raw_image = [](vk::Image image) { return std::bit_cast<u64>(VkImage(image)); };
        const auto raw_view = [](vk::ImageView view) { return std::bit_cast<u64>(VkImageView(view)); };
        fmt::print("[sewer-motion] event=vendor-input request={} checkpoint={} frame={} tick={} "
                   "hdr={}/{}:{:x}/{:x} depth={}/{}:{:x}/{:x} motion={:x}/{:x} "
                   "output={:x}/{:x} input={}x{} output_size={}x{} "
                   "reset={} preset={} model_hint={} jitter={:.9g},{:.9g} subresources=mip0-layer0-general\n",
                   checkpoint->key.request, checkpoint->key.checkpoint, checkpoint->key.frame, tick,
                   checkpoint->warp.color.id, checkpoint->warp.color.uid, raw_image(frame.color.image),
                   raw_view(frame.color.view), checkpoint->warp.depth.id, checkpoint->warp.depth.uid,
                   raw_image(frame.depth.image), raw_view(frame.depth.view), raw_image(frame.motion.image),
                   raw_view(frame.motion.view), raw_image(frame.output.image), raw_view(frame.output.view),
                   frame.render_width, frame.render_height, frame.output.width, frame.output.height,
                   unsigned(frame.reset), frame.preset, model_hint, frame.jitter[0], frame.jitter[1]);
    }

    void Finish(const Fsr4Upscaler::Frame& frame, bool ok) {
        if (!copied) return;
        successful = ok;
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (ok && checkpoint->needs_present) {
            consumed_color = frame.color;
            actual_output = frame.output;
        }
#endif
        if (ok) Read(frame, true);
        else refused = "dlss-evaluate-failed";
        const vk::MemoryBarrier2 memory{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        frame.cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &memory});
    }

    void Report() const {
        if (!successful) {
            checkpoint->vendor_error = refused ? refused : "vendor-evaluate-unissued";
        } else if (vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            checkpoint->vendor_error = "vendor-host-invalidate";
        } else {
            std::memcpy(checkpoint->vendor_input.data(), mapped, InputBytes);
            std::memcpy(checkpoint->vendor_output.data(), mapped + InputBytes, OutputBytes);
            checkpoint->vendor_values = true;
            for (u32 point = 0; point < checkpoint->vendor_input.size(); ++point) {
                const auto& pixel = checkpoint->warp.px[point];
                const auto& centre = checkpoint->pose.output[point];
                const auto& words = checkpoint->vendor_input[point];
                fmt::print("[sewer-motion] event=vendor-tap request={} checkpoint={} frame={} point={} "
                           "pixel={},{} half={:04x},{:04x},{:04x},{:04x} q={},{}\n",
                           checkpoint->key.request, checkpoint->key.checkpoint, checkpoint->key.frame, point,
                           pixel.x, pixel.y, words[0], words[1], words[2], words[3],
                           s32(centre[0]), s32(centre[1]));
                for (u32 i = 0; i < 9; ++i) {
                    const auto& half = checkpoint->vendor_output[point][i];
                    fmt::print("[sewer-motion] event=vendor-patch request={} checkpoint={} frame={} "
                               "point={} index={} half={:04x},{:04x},{:04x},{:04x}\n",
                               checkpoint->key.request, checkpoint->key.checkpoint, checkpoint->key.frame,
                               point, i, half[0], half[1], half[2], half[3]);
                }
            }
        }
    }
};

namespace {

// bbport: BB_GPU_PROFILE sub-labels inside TemporalUpscaler::Run, so that its row is not read as
// the upscaler alone: motion vectors, frame generation inputs, reactive mask, evaluation, merge,
// and what follows Run up to the next label. Profiling only; nothing else changes.
void MarkUpscalerPart(u64 part, const char* name) {
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0xF5A2'0000ull | part, [name] { return std::string{name}; });
    }
}

FfxVkPortableImage Describe(vk::Image image, vk::Format format, u32 width, u32 height,
                            vk::ImageUsageFlags usage, vk::ImageAspectFlags aspect,
                            FfxVkPortableResourceState state) {
    FfxVkPortableImage out{};
    out.structSize = sizeof(out);
    out.image = image;
    out.format = static_cast<VkFormat>(format);
    out.extent = {width, height};
    out.mipCount = 1;
    out.arrayLayers = 1;
    out.usage = static_cast<VkImageUsageFlags>(usage);
    out.aspect = static_cast<VkImageAspectFlags>(aspect);
    out.state = state;
    return out;
}

/// bbport: with sub-pixel jitter, the game's full-screen passes leave the scene's last row and
/// column brighter in some phases (a shimmering line at the right and bottom edges once upscaled,
/// GitHub issue 43). The row and column before them are copied over them before the upscaler
/// reads the scene: one edge pixel, and jitter keeps its full detail.
void ClampSceneEdges(Scheduler& scheduler, vk::Image image, u32 width, u32 height
#ifdef BB_TEST_SHARED_POST_GRAPH
                     , const std::shared_ptr<SewerBridge::ProxyAlpha>& observe = {}
#endif
                     ) {
    if (width < 2 || height < 2) {
        return;
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (observe) {
        observe->clamp_expected = true;
        observe->strips.queued_tick = scheduler.CurrentTick();
        observe->strips.cookie = PostProxyProof::NextCookie();
    }
#endif
    auto record = [image, width, height
#ifdef BB_TEST_SHARED_POST_GRAPH
                   , observe
#endif
                   ](vk::CommandBuffer cmdbuf
#ifdef BB_TEST_SHARED_POST_GRAPH
                     , NativeWriteSuffix::Encoder* encoder
#endif
                   ) {
        const vk::MemoryBarrier2 before{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .dstAccessMask = vk::AccessFlagBits2::eTransferRead | vk::AccessFlagBits2::eTransferWrite,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
        const vk::ImageSubresourceLayers layers{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
        const vk::ImageCopy row{
            .srcSubresource = layers,
            .srcOffset = {0, s32(height - 2), 0},
            .dstSubresource = layers,
            .dstOffset = {0, s32(height - 1), 0},
            .extent = {width, 1, 1},
        };
        constexpr auto layout = vk::ImageLayout::eGeneral;
        cmdbuf.copyImage(image, layout, image, layout, row);
        const vk::MemoryBarrier2 between{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .dstAccessMask = vk::AccessFlagBits2::eTransferRead | vk::AccessFlagBits2::eTransferWrite,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &between});
        const vk::ImageCopy column{
            .srcSubresource = layers,
            .srcOffset = {s32(width - 2), 0, 0},
            .dstSubresource = layers,
            .dstOffset = {s32(width - 1), 0, 0},
            .extent = {1, height, 1},
        };
        cmdbuf.copyImage(image, layout, image, layout, column);
        const vk::MemoryBarrier2 after{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (observe) {
            using namespace NativeWriteSuffix;
            static std::atomic<u64> issued_strips{};
            const u64 version = issued_strips.fetch_add(1, std::memory_order_relaxed) + 1;
            bool noted = false;
            if (encoder && observe->edge_order) {
                const auto& binding = observe->source.binding;
                noted = encoder->NoteProxyEdges(observe->edge_order,
                    {.proxy = SewerBridge::ScopedProxyImage(binding, 0), .result_version = version,
                     .owner = {binding.owner, binding.generation}, .source = image, .destination = image,
                     .source_layout = layout, .destination_layout = layout, .row = row, .column = column,
                     .before = before, .between = between, .after = after});
            } else if (encoder) {
                encoder->Note(Kind::NativeOperation, observe->strips.cookie);
            }
            observe->strips.Publish(cmdbuf, image, layout, layout, row, column, before, between, after,
                                    version, noted);
        }
#endif
    };
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (observe && observe->edge_order) {
        scheduler.RecordPostNative(observe->edge_order, [record = std::move(record)](
                                   vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
            record(cmd, &encoder);
        });
    } else if (observe && observe->strips.cookie) {
        scheduler.RecordNativeWriteSuffix([record = std::move(record)](
                                         vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
            record(cmd, &encoder);
        });
    } else {
        scheduler.Record([record = std::move(record)](vk::CommandBuffer cmd) { record(cmd, nullptr); });
    }
#else
    scheduler.Record(std::move(record));
#endif
}

/// bbport: BB_DUMP_TRIGGER=<file> BB_DUMP_DIR=<dir> (default out/dump): creating the file dumps
/// the upscaler's images of the next BB_DUMP_FRAMES (8) frames as raw files
/// <dir>/fNNN_<name>_<w>x<h>_<format>.raw, for checking temporal stability offline.
/// Returns the frame number to dump, or -1.
int DumpFrame() {
    static const char* trigger = std::getenv("BB_DUMP_TRIGGER");
    static int remaining = 0, index = 0, polls = 0;
    if (!trigger) {
        return -1;
    }
    if (remaining == 0) {
        if (++polls % 30 != 0 || std::remove(trigger) != 0) {
            return -1;
        }
        const char* frames = std::getenv("BB_DUMP_FRAMES");
        remaining = frames ? std::max(1, std::atoi(frames)) : 8;
        index = 0;
    }
    --remaining;
    return index++;
}

struct DumpImage {
    vk::Image image; ///< in layout General
    u32 width, height, bytes_per_pixel;
    const char* name;
    const char* format;
    vk::ImageAspectFlagBits aspect = vk::ImageAspectFlagBits::eColor;
};

/// Copies `images` into host buffers after the commands recorded so far and writes them to
/// files once the GPU is done.
void DumpImages(const Instance& instance, Scheduler& scheduler, vk::CommandBuffer cmdbuf,
                int frame, std::initializer_list<DumpImage> images) {
    static const std::string dir = [] {
        const char* env = std::getenv("BB_DUMP_DIR");
        return std::string{env && env[0] ? env : "out/dump"};
    }();
    const vk::MemoryBarrier2 before{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
        .dstAccessMask = vk::AccessFlagBits2::eTransferRead,
    };
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
    for (const auto& image : images) {
        const VkDeviceSize size = VkDeviceSize(image.width) * image.height * image.bytes_per_pixel;
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = size,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT |
                     VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VkBuffer buffer{};
        VmaAllocation allocation{};
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation,
                            &info) != VK_SUCCESS) {
            std::printf("Dump: no host memory for %s\n", image.name);
            continue;
        }
        const vk::BufferImageCopy region{
            .imageSubresource = {image.aspect, 0, 0, 1},
            .imageExtent = {image.width, image.height, 1},
        };
        cmdbuf.copyImageToBuffer(image.image, vk::ImageLayout::eGeneral, buffer, region);
        char path[512];
        std::snprintf(path, sizeof(path), "%s/f%03d_%s_%ux%u_%s.raw", dir.c_str(), frame,
                      image.name, image.width, image.height, image.format);
        scheduler.DeferPriorityOperation(
            [allocator = instance.GetAllocator(), buffer, allocation, info, size,
             file = std::string{path}] {
                vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE);
                if (FILE* f = std::fopen(file.c_str(), "wb")) {
                    std::fwrite(info.pMappedData, 1, size, f);
                    std::fclose(f);
                }
                vmaDestroyBuffer(allocator, buffer, allocation);
            });
    }
    const vk::MemoryBarrier2 after{
        .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
        .srcAccessMask = vk::AccessFlagBits2::eNone,
        .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .dstAccessMask = vk::AccessFlagBits2::eNone,
    };
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
    std::printf("Dump: frame %d -> %s\n", frame, dir.c_str());
}

void PrintIssues(const char* what, u64 issues) {
    std::printf("Upscaler: %s invalid:", what);
    for (u32 bit = 0; bit < 64; ++bit) {
        if (issues & (1ull << bit)) {
            std::printf(" %s", ffxVkPortableValidationIssueName(1ull << bit));
        }
    }
    std::printf("\n");
}

} // namespace

void DumpFinalFrameIfDue(const Instance& instance, Scheduler& scheduler, vk::CommandBuffer cmdbuf,
                         vk::Image image, u32 width, u32 height, vk::Format format) {
    static const char* trigger = std::getenv("BB_FINAL_DUMP_TRIGGER");
    static int index = 0;
    if (!trigger || std::remove(trigger) != 0) {
        return;
    }
    const bool bgra = format == vk::Format::eB8G8R8A8Unorm || format == vk::Format::eB8G8R8A8Srgb;
    DumpImages(instance, scheduler, cmdbuf, index++,
               {{image, width, height, 4, "final", bgra ? "bgra" : "rgba"}});
}

TemporalUpscaler::TemporalUpscaler(const Instance& instance_, Scheduler& scheduler_,
                                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                                   CameraMotion& camera_motion_, SceneTargets& scene_targets_,
                                   HdrNative& hdr_native_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, camera_motion{camera_motion_}, scene_targets{scene_targets_},
      hdr_native{hdr_native_} {
    // Reject unsupported shaders before allocating resources or recording a frame.
    if (instance.IsDlssCapable()) {
        dlss = std::make_unique<DlssUpscaler>(instance, scheduler);
    }
    if (instance.IsXessCapable()) {
        xess = std::make_unique<XessUpscaler>(instance, scheduler);
    }
    // bbport: FSR 4.1.1 runs through fsr4vk (shipped in the package, vk_fsr4vk.cpp), or by the
    // replay of an fsr4_411 set built from the player's own AMD DLL: with neither, as on a GPU
    // without its shaders, FSR 4 instead (#22).
    const char* fsr411_dir = std::getenv("BB_FSR411_DIR");
    std::error_code fsr411_error;
    const bool fsr411_assets = std::filesystem::is_directory(
        fsr411_dir && fsr411_dir[0] ? fsr411_dir : "fsr4_411", fsr411_error);
    const char* fsr4_builtin_amd = std::getenv("BB_FSR4_BUILTIN_AMD");
    BbSettings::ConfigureUpscalerSupport(instance.IsFsr4Int8Supported(),
                                         (instance.IsFsr411Supported() && fsr411_assets) ||
                                             instance.IsFsr4VkSupported(),
                                         dlss && dlss->Available(), instance.IsFsrSdkAvailable(),
                                         instance.GetVendorID() == 0x1002 &&
                                             !(fsr4_builtin_amd && fsr4_builtin_amd[0] == '1'),
                                         xess && xess->Available());
    fsr4 = std::make_unique<Fsr4Upscaler>(instance, scheduler);
    // Available unless BB_UPSCALER=none; on/off and the parameters are the menu's settings.
    const char* env = std::getenv("BB_UPSCALER");
    enabled = !(env && std::strcmp(env, "none") == 0);
    if (const char* hash = std::getenv("BB_UPSCALE_BEFORE_CS")) {
        trigger_hash = std::strtoull(hash, nullptr, 16);
    }
    if (const char* hash = std::getenv("BB_UI_TRIGGER_VS")) {
        ui_trigger_vs = std::strtoull(hash, nullptr, 16);
    }
    if (const char* res = std::getenv("BB_OUTPUT_RES")) {
        u32 w = 0, h = 0;
        if (std::sscanf(res, "%ux%u", &w, &h) == 2 && w && h) {
            target_width = w;
            target_height = h;
        }
    }
    // Explicit resolution overrides retain the old compatibility path. Normal presets
    // keep guest allocations/UI native and change only host raster targets at frame boundaries.
    scaled_session = std::getenv("BB_RENDER_RES") && std::getenv("BB_RENDER_RES")[0];
    render_width = 1920;
    render_height = 1080;
    if (const char* res = std::getenv("BB_RENDER_RES")) {
        u32 w = 0, h = 0;
        if (std::sscanf(res, "%ux%u", &w, &h) == 2 && w && h) {
            render_width = w;
            render_height = h;
        }
    }
    const char* early_env = std::getenv("BB_UPSCALE_EARLY");
    early_upscale = scaled_session && early_env && early_env[0] == '1' && render_width == target_width &&
                    render_height == target_height;
    if (early_upscale) {
        SceneResolution::Native() = {render_width, render_height};
        scene_targets.SetSize(SceneResolution::Native());
        std::printf("Upscaler: runs on the scene before post-processing, game targets %ux%u\n", render_width,
                    render_height);
    }
    // FSR 4's model, built in the background from the start (its first build compiles for
    // tens of seconds on some drivers), so it is usually ready when the game's first frame is.
    if (enabled && (BbSettings::Get().upscaler == BbSettings::UpscalerFsr4 ||
                    BbSettings::Get().upscaler == BbSettings::UpscalerFsr)) {
        fsr4->Prewarm(BbSettings::ModelPreset(BbSettings::RenderPreset()), target_width, target_height);
    }
    // Scene depth copied into the output-size UI depth by a blit (depth aspect).
    const auto features = instance.GetPhysicalDevice()
                              .getFormatProperties(vk::Format::eD32SfloatS8Uint)
                              .optimalTilingFeatures;
    depth_blit = (features & vk::FormatFeatureFlagBits::eBlitSrc) &&
                 (features & vk::FormatFeatureFlagBits::eBlitDst);
    if (enabled && !instance.IsStorageImageWriteWithoutFormatEnabled()) {
        std::printf("Upscaler: shaderStorageImageWriteWithoutFormat unsupported, FSR 3 off\n");
        enabled = false;
    }
    if (enabled) {
        std::printf("Upscaler: FSR 3.1 available (%s) on scene color before compute shader "
                    "%016llx\n",
                    BbSettings::Get().upscaler != BbSettings::UpscalerOff ? "on" : "off",
                    static_cast<unsigned long long>(trigger_hash));
    }
}

TemporalUpscaler::~TemporalUpscaler() {
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (sewer_bridge && sewer_bridge->post)
        runtime.DisarmPostImageBarriers(sewer_bridge->post->terminal.runtime_window);
#endif
    if (resources_ready) scheduler.Finish();
    if (context) {
        scheduler.Finish();
        ffxVkPortableUpscaleContextDestroy(context);
    }
}

bool TemporalUpscaler::Active() const {
    // Toggle 1 << 24 switches it off at run time (A/B); history restarts after.
    return enabled && !failed &&
           (BbSettings::Get().upscaler == BbSettings::UpscalerFsr3 ||
            BbSettings::IsFrameUpscaler(BbSettings::Get().upscaler) ||
            BbSettings::Get().upscaler == BbSettings::UpscalerTaa) &&
           !BbToggle::Disabled(1u << 24);
}

bool TemporalUpscaler::ReactiveOn() const {
    // FSR 3.1 takes it as its reactive mask, DLSS as its bias-current-colour mask (RecordFsr4).
    // FSR 4 takes no reactive mask itself: the mask blends its output afterwards
    // (RecordFsr4Reactive). TAA has no use for it.
    return BbSettings::Get().reactive && !BbToggle::Disabled(1u << 27) &&
           BbSettings::Get().upscaler != BbSettings::UpscalerTaa;
}

void TemporalUpscaler::RecordFsr4Reactive(vk::CommandBuffer cmdbuf, vk::ImageView color, u32 w,
                                          u32 h, u32 ow, u32 oh) {
    const auto all = vk::PipelineStageFlagBits2::eAllCommands;
    const vk::MemoryBarrier2 before{
        .srcStageMask = all, .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
        .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite};
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
    const vk::DescriptorImageInfo current{.sampler = *fsr4_linear_sampler, .imageView = color,
                                          .imageLayout = vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo mask{.sampler = *fsr4_linear_sampler, .imageView = *reactive_view,
                                       .imageLayout = vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo out{.imageView = *output_view,
                                      .imageLayout = vk::ImageLayout::eGeneral};
    const std::array<vk::WriteDescriptorSet, 3> writes{{
        {.dstBinding = 0, .descriptorCount = 1,
         .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &current},
        {.dstBinding = 1, .descriptorCount = 1,
         .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &mask},
        {.dstBinding = 2, .descriptorCount = 1,
         .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
    }};
    const std::array<float, 5> push{float(w), float(h), jitter[0], jitter[1], 1.0f};
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *fsr4_reactive_pipeline);
    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *fsr4_reactive_pipeline_layout, 0,
                                writes);
    cmdbuf.pushConstants(*fsr4_reactive_pipeline_layout, vk::ShaderStageFlagBits::eCompute, 0,
                         sizeof(push), push.data());
    cmdbuf.dispatch((ow + 7) / 8, (oh + 7) / 8, 1);
    const vk::MemoryBarrier2 after{
        .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
        .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
        .dstStageMask = all,
        .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite};
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
}

void TemporalUpscaler::OnSceneColor(VideoCore::ImageId color) {
    scene_color = color;
}

namespace {
float Halton(u32 index, u32 base) {
    float f = 1.0f, result = 0.0f;
    for (u32 i = index; i > 0; i /= base) {
        f /= float(base);
        result += f * float(i % base);
    }
    return result;
}
} // namespace

bool TemporalUpscaler::ReducedScene(const VideoCore::Image& color) const {
    return (!scaled_session || early_upscale) && scene_targets.Reduced() && scene_targets.EligibleScene(color);
}

bool TemporalUpscaler::RasterScaling() const {
    return (!scaled_session || early_upscale) && scene_targets.Reduced() && !done_this_frame;
}

bool TemporalUpscaler::OnFrameStart() {
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (bottle_prepared && bottle_prepared->scene.draw_frame != BbStats::frame_number.load(std::memory_order_relaxed)) {
        auto previous = std::exchange(bottle_prepared, {});
        std::lock_guard lock(previous->mutex);
        if (!previous->offered && !previous->completed && !previous->app_checked) {
            previous->cancelled = true;
            previous->order->Disarm();
            fmt::print("[bottle-cut] event=prepared-caller-refused request={} scene={} frame={} why=ordinary-override-missing\n",
                       previous->scene.key.request, previous->scene.key.scene, previous->scene.draw_frame);
        }
    }
#endif
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (sewer_bridge && sewer_bridge->post &&
        sewer_bridge->merge.key.frame != BbStats::frame_number.load(std::memory_order_relaxed)) {
        runtime.DisarmPostImageBarriers(std::exchange(sewer_bridge->post->terminal.runtime_window, 0));
    }
    if (sewer_bridge && sewer_bridge->post && !sewer_bridge->offered &&
        sewer_bridge->merge.key.frame != BbStats::frame_number.load(std::memory_order_relaxed)) {
        sewer_bridge->Stop("shared-post-display-unissued");
        if (sewer_bridge->post->order) sewer_bridge->post->order->Disarm();
    }
#endif
    if (frame_gen) {
        frame_gen->OnFrameStart();
    }
    // bbport: BB_PRESET_FILE=<file> holding a preset number, read about once a second: switches
    // the preset like the menu does (scripted tests of live preset changes).
    static const char* preset_file = std::getenv("BB_PRESET_FILE");
    if (preset_file && ++preset_file_frames % 64 == 0) {
        if (FILE* f = std::fopen(preset_file, "r")) {
            int value = 0;
            int output = -1;
            int provider = -1;
            const int fields = std::fscanf(f, "%d %d %d", &value, &output, &provider);
            if (fields >= 1 && value >= 0 &&
                value < BbSettings::PresetCount) {
                BbSettings::Get().preset.store(value);
            }
            if (fields >= 2 && output >= 0 && output < BbSettings::OutputCount) {
                BbSettings::Get().output_res.store(output);
            }
            if (fields == 3 && provider >= 0 && provider < BbSettings::UpscalerCount) {
                BbSettings::Get().upscaler.store(provider);
            }
            std::fclose(f);
        }
    }
    const auto& settings = BbSettings::Get();
    // The guest's startup resolution patch remains in effect until restart. Keep the FSR
    // model at the applied preset while the menu saves the requested one for run.sh.
    const int preset = BbSettings::RenderPreset();
    // bbport: the Custom preset's ratio (render_scale) moves its render size like a preset change.
    const float preset_scale = BbSettings::PresetScale(preset);
    const bool scale_changed = applied_scale != preset_scale;
    if (applied_preset != preset || scale_changed || settings.upscaler == BbSettings::UpscalerOff) failed = false;
    if (dispatch_failed.exchange(false, std::memory_order_relaxed)) {
        failed = true;
    }
    const bool active = Active();
    const bool jitter_on = active && settings.jitter && !BbToggle::Disabled(1u << 25);
    const int upscaler = settings.upscaler.load();
    const int output = settings.output_res.load();
    const bool output_changed = !scaled_session && applied_output != output;
    if (output_changed) {
        target_width = BbSettings::OutputWidth(output);
        target_height = BbSettings::OutputHeight(output);
        std::printf("Output resolution: %ux%u (live)\n", target_width, target_height);
        failed = false;
        fsr4_failed = false;
    }
    const bool changed = output_changed || applied_preset != preset || scale_changed || active != last_active ||
                         jitter_on != last_jitter || applied_upscaler != upscaler;
    if (applied_upscaler != upscaler) {
        // A failed provider keeps a fatal flag internally; a user retry gets a fresh context.
        scheduler.Finish();
        fsr4 = std::make_unique<Fsr4Upscaler>(instance, scheduler);
        if (BbSettings::IsFrameUpscaler(upscaler)) BbSettings::Get().fsr4_problem = nullptr;
    }
    if (applied_upscaler != upscaler) fsr4_failed = false; // retry after a menu change
    if (applied_upscaler != upscaler) fsr4_building = false; // a new provider object
    if (fsr4_building && !fsr4->Preparing()) {
        fsr4_building = false;
        reset = true;
        std::printf("Upscaler: switching from FSR 3.1 to FSR 4\n");
    }
    // Dynamic scene resolution scaling (live preset switching) works on all GPUs.
    // On GPUs without D32S8 blit support, UI depth is cleared instead of copied from scene.
    if (!scaled_session || early_upscale) {
        // bbport: live scene sizes reduce the game's 1920x1080 targets only. A third-party
        // resolution patch (3440x1440 with a 1080p output) left none to reduce, and a preset
        // change in the menu crashed the driver (nvoglv64, DLSS): such a scene stays native.
        const auto game_size = camera_motion.RenderSize();
        const bool game_1080p =
            game_size[0] == 0 ||
            (game_size[0] == SceneResolution::Native().width && game_size[1] == SceneResolution::Native().height);
        static bool told = false;
        if (!game_1080p && preset != 0 && !told) {
            told = true;
            std::printf("Upscaler: the game renders %ux%u (a resolution patch): presets stay native; "
                        "set Output resolution in the launcher instead\n", game_size[0], game_size[1]);
        }
        scene_targets.SetSize(SceneResolution::ForScale(active && game_1080p ? preset_scale : 1.0,
                                                       {target_width, target_height}));
        if (!early_upscale) {
            render_width = scene_targets.Size().width;
            render_height = scene_targets.Size().height;
        }
    }
    const bool render_is_scene = Scaled() && !early_upscale;
    BbSettings::Get().active_render_width = render_is_scene ? render_width : scene_targets.Size().width;
    BbSettings::Get().active_render_height = render_is_scene ? render_height : scene_targets.Size().height;
    // bbport: outputs other than 1080p upscale the game's finished frame (RunScaled), after its
    // motion blur: the upscaler accumulated the blurred frames along motion vectors that do not
    // describe the blur, a smear over the whole picture (worst at low render sizes). The game's
    // blur is held off then (engine/graphics.cpp); at 1080p the upscale comes before the post and
    // its blur. Opt-in: BB_UPSCALER_NO_BLUR=1 holds it there; =2: held under any upscaler.
    static const int no_blur = [] {
        const char* env = std::getenv("BB_UPSCALER_NO_BLUR");
        return env && env[0] ? std::atoi(env) : 0;
    }();
    BbSettings::Get().motion_blur_held.store(no_blur != 0 && active && (Scaled() || no_blur == 2),
                                             std::memory_order_relaxed);
    if (changed || !dispatched_last_frame) reset = true;
    if (changed) jitter_index = 0;
    reset_frames += reset && dispatched_last_frame ? 1 : 0;
    ++reset_window_frames;
    if (const auto now = std::chrono::steady_clock::now(); now - reset_window >= std::chrono::seconds(5)) {
        if (reset_frames * 10 > reset_window_frames) {
            std::printf("Upscaler: history reset on %u of %u frames in 5 s\n", reset_frames, reset_window_frames);
        }
        reset_window = now;
        reset_frames = reset_window_frames = 0;
    }
    applied_preset = preset;
    applied_scale = preset_scale;
    applied_output = output;
    applied_upscaler = upscaler;
    last_active = active;
    last_jitter = jitter_on;
    dispatched_last_frame = false;

    // The display pass of an upscaled frame reads the upscaled UI image.
    display_redirect = ui_phase;
    ui_phase = false;
    ui_read_barrier = false;
    done_this_frame = false;
    ldr_target = {};
    scene_color = {};
    snapshot_taken = false;
    opaque_valid = false;
    mask_ready = false;
    // Halton(2, 3); the menu or toggle 1 << 25 disables it.
    if (!jitter_on) {
        jitter = {};
        return changed;
    }
    // CameraMotion::OnDisplayPass has already cleared Depth(). Use the context's render
    // size, which survives the frame boundary (Performance 960 -> 1920 needs 32 phases).
    const u32 phases = render_is_scene ? Motion::JitterPhases(render_width, target_width)
        : Motion::JitterPhases(scene_targets.Size().width, SceneResolution::Native().width);
    jitter_index = jitter_index % phases + 1;
    const float amount = JitterAmount();
    jitter = {(Halton(jitter_index, 2) - 0.5f) * amount, (Halton(jitter_index, 3) - 0.5f) * amount};
    return changed;
}

float TemporalUpscaler::CameraSpeed() const {
    const auto camera = camera_motion.CameraMatrices();
    if (!camera.valid) {
        return 0.0f;
    }
    const bool render_is_scene = Scaled() && !early_upscale;
    const float width = float(render_is_scene ? render_width : scene_targets.Size().width);
    const float height = float(render_is_scene ? render_height : scene_targets.Size().height);
    constexpr float z = 5.0f;
    float speed = 0.0f;
    for (const float ndc_x : {0.0f, -0.7f, 0.7f}) {
        const float vx = ndc_x * z / camera.proj[0];
        std::array<float, 3> world;
        for (int r = 0; r < 3; ++r) {
            world[r] = camera.inv_view[r * 4] * vx + camera.inv_view[r * 4 + 2] * z + camera.inv_view[r * 4 + 3];
        }
        std::array<float, 3> before;
        for (int r = 0; r < 3; ++r) {
            before[r] = camera.prev_view[r * 4] * world[0] + camera.prev_view[r * 4 + 1] * world[1] +
                        camera.prev_view[r * 4 + 2] * world[2] + camera.prev_view[r * 4 + 3];
        }
        const float w = std::max(before[2], 1e-4f);
        const float dx = (before[0] * camera.prev_proj[0] / w - ndc_x) * 0.5f * width;
        const float dy = before[1] * camera.prev_proj[1] / w * 0.5f * height;
        const float moved = std::sqrt(dx * dx + dy * dy);
        speed = std::max(speed, std::isfinite(moved) ? moved : 0.0f);
    }
    return speed;
}

float TemporalUpscaler::JitterAmount() {
    const auto& settings = BbSettings::Get();
    if (!settings.dlss_jitter_fade.load(std::memory_order_relaxed) ||
        settings.upscaler != BbSettings::UpscalerDlss) {
        jitter_speed = 0.0f;
        return 1.0f;
    }
    jitter_speed = std::max(CameraSpeed(), jitter_speed * 0.85f);
    return 1.0f - std::clamp((jitter_speed - 0.25f) / 0.75f, 0.0f, 1.0f);
}

void TemporalUpscaler::OnDispatch(u64 cs_hash) {
    if (cs_hash != trigger_hash) {
        return;
    }
    // bbport: the consumer of the fills, resolves and drops below (SceneUse).
    const SceneUseScope scene_use{"upscaler and HDR native at the trigger, cs", cs_hash};
    if (!done_this_frame && !failed && (!Scaled() || early_upscale)) {
        done_this_frame = true;
        // bbport: a frame with several G-buffer passes is a menu's 3D preview (character
        // creation): its "scene" is one of the previews, and accumulating it into the history
        // the result replaces it with held the hunter's old hair and parts on screen after
        // changes, until a restart. Not anti-aliased; the history starts again after it.
        if (!scene_color || !camera_motion.Ready() || !Active() || camera_motion.PreviewFrame()) {
            reset = true;
        } else {
            Run();
        }
    }
    // bbport: native HDR output: the scene color the post-processing starts from, upscaled by
    // now at 1080p output; a reduced scene (scaled presets) is resolved into it, as the game's
    // own compute passes reading it would.
    if (scene_color && HdrNative::Wanted()) {
        hdr_native.OnSceneColor(scene_color);
    }
}

bool TemporalUpscaler::EnsureResources(u32 w, u32 h, u32 ow, u32 oh, bool hdr) {
    const bool use_fsr4 = UseFsr4();
    const bool use_taa = BbSettings::Get().upscaler == BbSettings::UpscalerTaa;
    if (use_taa && (w != ow || h != oh)) {
        std::printf("TAA: remove BB_RENDER_RES to use native-resolution TAA\n");
        return false;
    }
    if (resources_ready && w == width && h == height && ow == out_width && oh == out_height &&
        hdr == context_hdr && use_fsr4 == resources_fsr4 && use_taa == resources_taa) {
        return true;
    }
    const auto device = instance.GetDevice();
    // FSR 4 owns no portable FSR 3 context, but its images can still be in flight.
    scheduler.Finish();
    resources_ready = false;
    if (context) {
        ffxVkPortableUpscaleContextDestroy(context);
        context = nullptr;
        fsr3_tuned = nullptr; // a new context may get the same address
    }
    width = w;
    height = h;
    out_width = ow;
    out_height = oh;
    context_hdr = hdr;

    FfxVkPortableDeviceInfo device_info{};
    device_info.structSize = sizeof(device_info);
    device_info.instance = instance.GetInstance();
    device_info.physicalDevice = instance.GetPhysicalDevice();
    device_info.device = device;
    device_info.getDeviceProcAddr = VULKAN_HPP_DEFAULT_DISPATCHER.vkGetDeviceProcAddr;
    device_info.queue = instance.GetGraphicsQueue();
    device_info.queueFamilyIndex = instance.GetGraphicsQueueFamilyIndex();
    device_info.shaderFloat16Enabled = instance.IsShaderFloat16Enabled();
    device_info.subgroupSizeControlEnabled = instance.IsSubgroupSizeControlEnabled();
    device_info.synchronization2Enabled = VK_TRUE;
    device_info.shaderStorageImageWriteWithoutFormatEnabled = VK_TRUE;

    FfxVkPortableUpscaleCreateInfo create_info{};
    create_info.structSize = sizeof(create_info);
    // Native AA runs on the HDR scene color; scaled presets on the game's tonemapped frame.
    create_info.flags = hdr ? FFX_VK_PORTABLE_CONTEXT_HDR_COLOR_INPUT |
                                  FFX_VK_PORTABLE_CONTEXT_AUTO_EXPOSURE
                            : 0;
    create_info.maxRenderSize = {w, h};
    create_info.maxOutputSize = {ow, oh};
    // FSR 4 has its own model context (vk_fsr4); the images below are shared.
    if (!use_fsr4 && !use_taa) {
        if (const u64 issues = ffxVkPortableValidateUpscaleCreateInfo(&create_info)) {
            PrintIssues("create info", issues);
            return false;
        }
        if (ffxVkPortableUpscaleContextCreate(&device_info, &create_info, &context) !=
            FFX_VK_PORTABLE_OK) {
            std::printf("Upscaler: FSR 3 context creation failed\n");
            context = nullptr;
            return false;
        }
    }

    const auto allocator = instance.GetAllocator();
    motion_view.reset();
    output_view.reset();
    motion_image = VideoCore::UniqueImage(device, allocator);
    motion_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16Sfloat,
        .extent = {w, h, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    output_image = VideoCore::UniqueImage(device, allocator);
    output_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {ow, oh, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                 vk::ImageUsageFlagBits::eTransferSrc,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
#ifdef BB_TEST_SHARED_POST_GRAPH
    ++sewer_output_generation;
#endif
    output_view = Check(device.createImageViewUnique({
        .image = vk::Image(output_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    motion_view = Check(device.createImageViewUnique({
        .image = vk::Image(motion_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16Sfloat,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    const auto make_image = [&](VideoCore::UniqueImage& image, vk::UniqueImageView& view,
                                vk::Format format, vk::ImageUsageFlags usage, u32 iw = 0,
                                u32 ih = 0, vk::ImageAspectFlags aspect =
                                                vk::ImageAspectFlagBits::eColor,
                                vk::ImageCreateFlags flags = {}) {
        view.reset();
        image = VideoCore::UniqueImage(device, allocator);
        image.Create(vk::ImageCreateInfo{
            .flags = flags,
            .imageType = vk::ImageType::e2D,
            .format = format,
            .extent = {iw ? iw : w, ih ? ih : h, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = usage,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        view = Check(device.createImageViewUnique({
            .image = vk::Image(image),
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        }));
    };
    make_image(opaque_image, opaque_view, vk::Format::eR16G16B16A16Sfloat,
               vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst |
                   vk::ImageUsageFlagBits::eTransferSrc);
    make_image(reactive_image, reactive_view, vk::Format::eR8Unorm,
               vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled);
    fsr4_linear_view.reset();
    fsr4_linear_image = VideoCore::UniqueImage{};
    if (use_fsr4) {
        make_image(fsr4_linear_image, fsr4_linear_view, vk::Format::eR16G16B16A16Sfloat,
                   vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled);
    }
    for (u32 i = 0; i < taa_history.size(); ++i) {
        taa_history_views[i].reset();
        taa_history[i] = VideoCore::UniqueImage{};
        if (use_taa) {
            make_image(taa_history[i], taa_history_views[i], vk::Format::eR32G32B32A32Sfloat,
                       vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                           vk::ImageUsageFlagBits::eTransferSrc,
                       ow, oh);
        }
    }
    taa_next = 0;
    CreatePipelines();
    opaque_valid = false;
    // bbport: a mask made earlier in this frame was in the image just replaced: the new one is
    // unwritten (undefined layout), and DLSS took it as its bias mask (noise all over the frame).
    mask_ready = false;
    reset = true;
    resources_ready = true;
    resources_fsr4 = use_fsr4;
    resources_taa = use_taa;
    if (use_taa) {
        std::printf("TAA: context %ux%u -> %ux%u (%s), no FSR model\n", w, h, ow, oh,
                    hdr ? "HDR scene color" : "tonemapped frame");
        return true;
    }
    if (use_fsr4) {
        std::printf("Upscaler: FSR 4 inputs %ux%u -> %ux%u\n", w, h, ow, oh);
        return true;
    }
    FfxVkPortableMemoryUsage usage{};
    usage.structSize = sizeof(usage);
    ffxVkPortableUpscaleContextGetMemoryUsage(context, &usage);
    std::printf("Upscaler: FSR 3 context %ux%u -> %ux%u (%s), %.1f MB\n", w, h, ow, oh,
                hdr ? "HDR scene color" : "tonemapped frame", usage.totalUsageInBytes / 1e6);
    return true;
}

void TemporalUpscaler::CreatePipelines() {
    if (merge_pipeline) {
        return;
    }
    const auto device = instance.GetDevice();
    const auto storage_layout = [&](u32 count, vk::UniqueDescriptorSetLayout& layout,
                                    vk::UniquePipelineLayout& pipeline_layout, u32 push_size) {
        std::array<vk::DescriptorSetLayoutBinding, 3> bindings{};
        for (u32 i = 0; i < count; ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = vk::DescriptorType::eStorageImage,
                           .descriptorCount = 1,
                           .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = count,
            .pBindings = bindings.data(),
        }));
        const vk::PushConstantRange push{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                         .offset = 0,
                                         .size = push_size};
        pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1,
            .pSetLayouts = &*layout,
            .pushConstantRangeCount = 1,
            .pPushConstantRanges = &push,
        }));
    };
    const auto compute = [&](const auto& code, vk::PipelineLayout layout) {
        const auto module = CompileSPV(code, device);
        auto pipeline = Check(device.createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{
                    .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                              .module = module,
                              .pName = "main"},
                    .layout = layout,
                }));
        device.destroyShaderModule(module);
        return pipeline;
    };
    {
        // Merge: three storage images, then the motion and object motion images (debug) and
        // the scene colour's proxy (its alpha).
        std::array<vk::DescriptorSetLayoutBinding, 6> bindings{};
        for (u32 i = 0; i < bindings.size(); ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = i < 3 ? vk::DescriptorType::eStorageImage
                                                   : vk::DescriptorType::eSampledImage,
                           .descriptorCount = 1,
                           .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        merge_desc_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = u32(bindings.size()),
            .pBindings = bindings.data(),
        }));
        const vk::PushConstantRange push{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                         .offset = 0,
                                         .size = 3 * sizeof(u32)}; // mode, sharpen, alpha
        merge_pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1,
            .pSetLayouts = &*merge_desc_layout,
            .pushConstantRangeCount = 1,
            .pPushConstantRanges = &push,
        }));
    }
    merge_pipeline = compute(UPSCALE_MERGE_COMP, *merge_pipeline_layout);
    storage_layout(3, reactive_desc_layout, reactive_pipeline_layout, 3 * sizeof(float));
    reactive_pipeline = compute(UPSCALE_REACTIVE_COMP, *reactive_pipeline_layout);
    storage_layout(2, taa_sharpen_desc_layout, taa_sharpen_pipeline_layout, sizeof(float));
    taa_sharpen_pipeline = compute(TAA_SHARPEN_COMP, *taa_sharpen_pipeline_layout);
    taa_sharpen_ldr_pipeline = compute(TAA_SHARPEN_LDR_COMP, *taa_sharpen_pipeline_layout);
    storage_layout(1, fsr4_encode_desc_layout, fsr4_encode_pipeline_layout, sizeof(u32));
    {
        // Debug view: the target (storage), then the mask, motion and object motion (sampled).
        std::array<vk::DescriptorSetLayoutBinding, 4> bindings{};
        for (u32 i = 0; i < bindings.size(); ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = i == 0 ? vk::DescriptorType::eStorageImage
                                                    : vk::DescriptorType::eSampledImage,
                           .descriptorCount = 1,
                           .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        debug_desc_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = u32(bindings.size()), .pBindings = bindings.data()}));
        const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, 3 * sizeof(u32)};
        debug_pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1, .pSetLayouts = &*debug_desc_layout,
            .pushConstantRangeCount = 1, .pPushConstantRanges = &push}));
        debug_pipeline = compute(UPSCALE_DEBUG_COMP, *debug_pipeline_layout);
        debug_ldr_pipeline = compute(UPSCALE_DEBUG_LDR_COMP, *debug_pipeline_layout);
    }
    fsr4_encode_pipeline = compute(FSR4_ENCODE_COMP, *fsr4_encode_pipeline_layout);
    {
        const std::array<vk::DescriptorSetLayoutBinding, 2> bindings{{
            {.binding = 0, .descriptorType = vk::DescriptorType::eSampledImage,
             .descriptorCount = 1, .stageFlags = vk::ShaderStageFlagBits::eCompute},
            {.binding = 1, .descriptorType = vk::DescriptorType::eStorageImage,
             .descriptorCount = 1, .stageFlags = vk::ShaderStageFlagBits::eCompute},
        }};
        fsr4_decode_desc_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = u32(bindings.size()), .pBindings = bindings.data()}));
        const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, sizeof(u32)};
        fsr4_decode_pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1, .pSetLayouts = &*fsr4_decode_desc_layout,
            .pushConstantRangeCount = 1, .pPushConstantRanges = &push}));
        fsr4_decode_pipeline = compute(FSR4_DECODE_COMP, *fsr4_decode_pipeline_layout);
    }
    {
        std::array<vk::DescriptorSetLayoutBinding, 3> bindings{};
        for (u32 i = 0; i < bindings.size(); ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = i < 2 ? vk::DescriptorType::eCombinedImageSampler
                                                   : vk::DescriptorType::eStorageImage,
                           .descriptorCount = 1, .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        fsr4_reactive_desc_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = u32(bindings.size()), .pBindings = bindings.data()}));
        const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, 5 * sizeof(float)};
        fsr4_reactive_pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1, .pSetLayouts = &*fsr4_reactive_desc_layout,
            .pushConstantRangeCount = 1, .pPushConstantRanges = &push}));
        fsr4_linear_sampler = Check(device.createSamplerUnique({
            .magFilter = vk::Filter::eLinear, .minFilter = vk::Filter::eLinear,
            .mipmapMode = vk::SamplerMipmapMode::eNearest,
            .addressModeU = vk::SamplerAddressMode::eClampToEdge,
            .addressModeV = vk::SamplerAddressMode::eClampToEdge,
            .addressModeW = vk::SamplerAddressMode::eClampToEdge}));
        fsr4_reactive_pipeline = compute(FSR4_REACTIVE_COMP, *fsr4_reactive_pipeline_layout);
    }
    {
        std::array<vk::DescriptorSetLayoutBinding, 7> bindings{};
        for (u32 i = 0; i < bindings.size(); ++i) {
            bindings[i] = {.binding = i,
                .descriptorType = i < 4 ? vk::DescriptorType::eCombinedImageSampler
                                        : vk::DescriptorType::eStorageImage,
                .descriptorCount = 1, .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        taa_desc_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = u32(bindings.size()), .pBindings = bindings.data()}));
        const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, 64};
        taa_pipeline_layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1, .pSetLayouts = &*taa_desc_layout,
            .pushConstantRangeCount = 1, .pPushConstantRanges = &push}));
        taa_sampler = Check(device.createSamplerUnique({
            .magFilter = vk::Filter::eNearest, .minFilter = vk::Filter::eNearest,
            .mipmapMode = vk::SamplerMipmapMode::eNearest,
            .addressModeU = vk::SamplerAddressMode::eClampToEdge,
            .addressModeV = vk::SamplerAddressMode::eClampToEdge,
            .addressModeW = vk::SamplerAddressMode::eClampToEdge}));
        taa_pipeline = compute(TAA_COMP, *taa_pipeline_layout);
    }
}

void TemporalUpscaler::RecordTaa(vk::CommandBuffer cmdbuf, vk::ImageView color,
                                vk::ImageView depth) {
    // Make scene writes and the last storage-image history writes visible to sampled reads.
    const vk::MemoryBarrier2 inputs{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite |
                         vk::AccessFlagBits2::eShaderStorageWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
        .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                         vk::AccessFlagBits2::eShaderStorageWrite,
    };
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1,.pMemoryBarriers = &inputs});
    // Histories alternate between reads and writes. Queue ordering plus this dependency
    // protects both the previous write and a reused destination's previous read.
    std::array<vk::ImageMemoryBarrier2, 2> barriers{};
    for (u32 i = 0; i < barriers.size(); ++i) {
        barriers[i] = {.srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite |
                             vk::AccessFlagBits2::eShaderStorageWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                             vk::AccessFlagBits2::eShaderStorageWrite,
            .oldLayout = reset ? vk::ImageLayout::eUndefined : vk::ImageLayout::eGeneral,
            .newLayout = vk::ImageLayout::eGeneral,
            .image = vk::Image(taa_history[i]),
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
    }
    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = u32(barriers.size()),
                             .pImageMemoryBarriers = barriers.data()});
    const std::array<vk::ImageView, 7> views{
        color, depth, *motion_view, *taa_history_views[1 - taa_next],
        *output_view, *taa_history_views[taa_next], *opaque_view};
    std::array<vk::DescriptorImageInfo, 7> infos{};
    std::array<vk::WriteDescriptorSet, 7> writes{};
    for (u32 i = 0; i < infos.size(); ++i) {
        infos[i] = {.sampler = i < 4 ? *taa_sampler : vk::Sampler{},
                    .imageView = views[i], .imageLayout = vk::ImageLayout::eGeneral};
        writes[i] = {.dstBinding = i, .descriptorCount = 1,
            .descriptorType = i < 4 ? vk::DescriptorType::eCombinedImageSampler
                                    : vk::DescriptorType::eStorageImage,
            .pImageInfo = &infos[i]};
    }
    struct Params {
        std::array<float, 2> jitter;
        u32 reset, pad;
        std::array<std::array<float, 4>, 3> depth;
    } params{jitter, reset ? 1u : 0u, std::getenv("BB_TAA_DIAGNOSTICS") ?
                 u32(std::clamp(std::atoi(std::getenv("BB_TAA_DIAGNOSTICS")),1,3)) : 0u,
             camera_motion.TaaDepthParameters()};
    // Optional techniques for A/B in one run (BB_TOGGLE_FILE bits 51-54): tonemapped blending,
    // YCoCg clipping, variance clipping, 3x3 reconstruction. Measured in game on 2026-10-02
    // (static and panning camera, interleaved captures): none improved stability beyond run
    // noise; YCoCg clipping and the reconstruction made it worse. Default: all off.
    params.pad |= (BbToggle::Disabled(BbToggle::TaaTonemapBlend) ? 1u << 8 : 0u) |
                  (BbToggle::Disabled(BbToggle::TaaClip) ? 2u << 8 : 0u) |
                  (BbToggle::Disabled(BbToggle::TaaVariance) ? 4u << 8 : 0u) |
                  (BbToggle::Disabled(BbToggle::TaaFilter) ? 8u << 8 : 0u) |
                  (BbToggle::Disabled(BbToggle::TaaKeepNearerHistory) ? 16u << 8 : 0u);
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *taa_pipeline);
    if (params.pad & 0xffu) {
        static u32 diagnostic_frames = 0;
        if (diagnostic_frames++ < 16)
            std::printf("TAA diagnostic: reset=%u jitter=%.6f,%.6f mode=%u\n",
                        params.reset, jitter[0], jitter[1], params.pad);
    }
    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *taa_pipeline_layout, 0, writes);
    cmdbuf.pushConstants(*taa_pipeline_layout, vk::ShaderStageFlagBits::eCompute, 0,
                         sizeof(params), &params);
    cmdbuf.dispatch((out_width + 7) / 8, (out_height + 7) / 8, 1);
    const auto& settings = BbSettings::Get();
    const float strength = std::clamp(settings.sharpness.load(), 0.0f, 2.0f);
    if (settings.sharpen && strength > 0.0f && !(params.pad & 0xffu)) {
        const vk::MemoryBarrier2 resolved{
            .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .dstAccessMask = vk::AccessFlagBits2::eShaderStorageRead |
                             vk::AccessFlagBits2::eShaderStorageWrite};
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &resolved});
        const std::array<vk::DescriptorImageInfo, 2> sharpen_infos{{
            {.imageView = *taa_history_views[taa_next], .imageLayout = vk::ImageLayout::eGeneral},
            {.imageView = *output_view, .imageLayout = vk::ImageLayout::eGeneral}}};
        std::array<vk::WriteDescriptorSet, 2> sharpen_writes{};
        for (u32 i = 0; i < sharpen_writes.size(); ++i)
            sharpen_writes[i] = {.dstBinding = i, .descriptorCount = 1,
                .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &sharpen_infos[i]};
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *taa_sharpen_pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute,
                                    *taa_sharpen_pipeline_layout, 0, sharpen_writes);
        cmdbuf.pushConstants(*taa_sharpen_pipeline_layout, vk::ShaderStageFlagBits::eCompute,
                             0, sizeof(strength), &strength);
        cmdbuf.dispatch((out_width + 7) / 8, (out_height + 7) / 8, 1);
    }
    taa_next = 1 - taa_next;
}

// The sharpening applied on top of the upscaler's own (0 = none).
static float ExtraSharpenStrength() {
    const auto& settings = BbSettings::Get();
    // FSR 3 and 4 sharpen up to 1 themselves (RCAS). DLSS has no sharpening of its own (NVIDIA
    // retired its Sharpness parameter), nor has XeSS-SR, so for them this pass applies the whole 0..2.
    const float own = settings.upscaler == BbSettings::UpscalerDlss ||
                              settings.upscaler == BbSettings::UpscalerXess
                          ? 0.0f
                          : 1.0f;
    const float extra = std::clamp(settings.sharpness.load(), 0.0f, 2.0f) - own;
    // bbport (r55_drawn-look-lines): this pass sharpens the drawn look's ink lines as it sharpens
    // any edge; on a frame that recorded them it is lowered, by up to half
    // (DrawnLookParams::InkSharpen; drawn_look_ink_drawn is 0 on every other frame).
    const float ink =
        DrawnLookParams::InkSharpen(settings.drawn_look_ink_drawn.load(std::memory_order_relaxed));
    return settings.sharpen && extra > 0.0f ? extra * ink : 0.0f;
}

void TemporalUpscaler::ExtraSharpen(vk::Image target, bool ldr, u32 w, u32 h) {
    const float extra = ExtraSharpenStrength();
    if (extra <= 0.0f) {
        return;
    }
    const auto device = instance.GetDevice();
    if (extra_sharpen_width != w || extra_sharpen_height != h) {
        // Submitted work may still read the old copy: destroyed once the GPU is past it. (A
        // Finish() here submitted the command buffer Run() goes on recording into.)
        scheduler.DeferOperation([image = std::move(extra_sharpen_image),
                                  view = std::move(extra_sharpen_view)]() mutable {
            view.reset();
            image.Destroy();
        });
        extra_sharpen_image = VideoCore::UniqueImage(device, instance.GetAllocator());
        extra_sharpen_image.Create(vk::ImageCreateInfo{
            .imageType = vk::ImageType::e2D,
            .format = vk::Format::eR32G32B32A32Sfloat,
            .extent = {w, h, 1},
            .mipLevels = 1, .arrayLayers = 1, .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eTransferDst,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        extra_sharpen_view = Check(device.createImageViewUnique({
            .image = vk::Image(extra_sharpen_image), .viewType = vk::ImageViewType::e2D,
            .format = vk::Format::eR32G32B32A32Sfloat,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        }));
        extra_sharpen_width = w;
        extra_sharpen_height = h;
    }
    const vk::ImageView target_view = ldr ? UiStorageView(target) : *output_view;
    // bbport: the commands are recorded through the scheduler (a recording thread for FSR 3).
    scheduler.RecordCrumb({.name = "TAA extra sharpen"}, [target, copy = vk::Image(extra_sharpen_image),
                      copy_view = *extra_sharpen_view, target_view, extra, w, h,
                      pipeline = ldr ? *taa_sharpen_ldr_pipeline : *taa_sharpen_pipeline,
                      layout = *taa_sharpen_pipeline_layout](vk::CommandBuffer cmdbuf) {
        const auto image_barrier = [&](vk::Image image, vk::ImageLayout old_layout,
                                       vk::PipelineStageFlags2 src, vk::AccessFlags2 src_access,
                                       vk::PipelineStageFlags2 dst, vk::AccessFlags2 dst_access) {
            const vk::ImageMemoryBarrier2 b{
                .srcStageMask = src, .srcAccessMask = src_access,
                .dstStageMask = dst, .dstAccessMask = dst_access,
                .oldLayout = old_layout, .newLayout = vk::ImageLayout::eGeneral,
                .image = image, .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b});
        };
        constexpr auto all = vk::PipelineStageFlagBits2::eAllCommands;
        constexpr auto rw = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
        image_barrier(target, vk::ImageLayout::eGeneral, all, rw,
                      vk::PipelineStageFlagBits2::eBlit, vk::AccessFlagBits2::eTransferRead);
        image_barrier(copy, vk::ImageLayout::eUndefined, all, rw,
                      vk::PipelineStageFlagBits2::eBlit, vk::AccessFlagBits2::eTransferWrite);
        const vk::ImageBlit region{
            .srcSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .srcOffsets = std::array{vk::Offset3D{}, vk::Offset3D{s32(w), s32(h), 1}},
            .dstSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .dstOffsets = std::array{vk::Offset3D{}, vk::Offset3D{s32(w), s32(h), 1}},
        };
        cmdbuf.blitImage(target, vk::ImageLayout::eGeneral, copy, vk::ImageLayout::eGeneral,
                         region, vk::Filter::eNearest);
        image_barrier(copy, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eBlit,
                      vk::AccessFlagBits2::eTransferWrite,
                      vk::PipelineStageFlagBits2::eComputeShader,
                      vk::AccessFlagBits2::eShaderStorageRead);
        image_barrier(target, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eBlit,
                      vk::AccessFlagBits2::eTransferRead,
                      vk::PipelineStageFlagBits2::eComputeShader,
                      vk::AccessFlagBits2::eShaderStorageWrite);
        const std::array<vk::DescriptorImageInfo, 2> infos{{
            {.imageView = copy_view, .imageLayout = vk::ImageLayout::eGeneral},
            {.imageView = target_view, .imageLayout = vk::ImageLayout::eGeneral}}};
        std::array<vk::WriteDescriptorSet, 2> writes{};
        for (u32 i = 0; i < writes.size(); ++i)
            writes[i] = {.dstBinding = i, .descriptorCount = 1,
                .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &infos[i]};
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
        cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(extra), &extra);
        cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
        image_barrier(target, vk::ImageLayout::eGeneral,
                      vk::PipelineStageFlagBits2::eComputeShader,
                      vk::AccessFlagBits2::eShaderStorageWrite, all, rw);
    });
}

vk::ImageView TemporalUpscaler::UiStorageView(vk::Image target) {
    if (SewerBridgeOpen() && target == vk::Image(ui_image)) {
        sewer_bridge->Stop("ui-storage-writer-unproved");
    }
    if (!ui_storage_view) {
        // The UI image's own format may be sRGB; FSR 3 writes it through a UNORM view too.
        ui_storage_view = Check(instance.GetDevice().createImageViewUnique({
            .image = target, .viewType = vk::ImageViewType::e2D,
            .format = vk::Format::eR8G8B8A8Unorm,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        }));
    }
    return *ui_storage_view;
}

void TemporalUpscaler::DebugView(vk::Image target, bool ldr, u32 w, u32 h, u32 ow, u32 oh,
                                 bool reactive) {
    // As the 1080p path's merge (Run): the mask (menu or toggle 1 << 28) or the motion vectors.
    const int debug_view = BbSettings::Get().debug_view;
    const u32 mode = reactive && (debug_view == BbSettings::DebugReactive || BbToggle::Disabled(1u << 28))
                         ? 1
                     : debug_view == BbSettings::DebugMotion ? 2
                                                             : 0;
    if (mode == 0) {
        return;
    }
    const vk::ImageView target_view = ldr ? UiStorageView(target) : *output_view;
    const vk::ImageView objects = camera_motion.ObjectMotionView();
    scheduler.RecordCrumb({.name = "TAA debug view"}, [target, target_view, mask = *reactive_view,
                      motion = *motion_view, objects = objects ? objects : *motion_view,
                      push = std::array<u32, 3>{mode, w, h}, ow, oh,
                      pipeline = ldr ? *debug_ldr_pipeline : *debug_pipeline,
                      layout = *debug_pipeline_layout](vk::CommandBuffer cmdbuf) {
        constexpr auto all = vk::PipelineStageFlagBits2::eAllCommands;
        const vk::ImageMemoryBarrier2 before{
            .srcStageMask = all,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .dstAccessMask = vk::AccessFlagBits2::eShaderStorageRead |
                             vk::AccessFlagBits2::eShaderStorageWrite,
            .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eGeneral,
            .image = target, .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &before});
        const std::array<vk::DescriptorImageInfo, 4> infos{{
            {.imageView = target_view, .imageLayout = vk::ImageLayout::eGeneral},
            {.imageView = mask, .imageLayout = vk::ImageLayout::eGeneral},
            {.imageView = motion, .imageLayout = vk::ImageLayout::eGeneral},
            {.imageView = objects, .imageLayout = vk::ImageLayout::eGeneral}}};
        std::array<vk::WriteDescriptorSet, 4> writes{};
        for (u32 i = 0; i < writes.size(); ++i) {
            writes[i] = {.dstBinding = i, .descriptorCount = 1,
                         .descriptorType = i == 0 ? vk::DescriptorType::eStorageImage
                                                  : vk::DescriptorType::eSampledImage,
                         .pImageInfo = &infos[i]};
        }
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
        cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), push.data());
        cmdbuf.dispatch((ow + 7) / 8, (oh + 7) / 8, 1);
        const vk::ImageMemoryBarrier2 after{
            .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
            .dstStageMask = all,
            .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
            .oldLayout = vk::ImageLayout::eGeneral, .newLayout = vk::ImageLayout::eGeneral,
            .image = target, .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &after});
    });
}

void TemporalUpscaler::OnBlendedSceneDraw() {
    // The mask is opt-in (menu, BB_REACTIVE=1): on Bloodborne's thin mist it trades trails for
    // jitter shimmer, which looked worse. Toggle 1 << 27 switches it off.
    if (snapshot_taken || !scene_color || !Active() || !ReactiveOn()) {
        return;
    }
    snapshot_taken = true;
    auto& color = texture_cache.GetImage(scene_color);
    // With a live preset the scene is in the reduced proxy: the mask and the FSR context
    // must use that size, or each frame would recreate the context (native <-> reduced).
    const bool reduced = ReducedScene(color);
    const u32 ow = color.info.size.width, oh = color.info.size.height;
    // Scaled presets: the scene fills the top-left of its aligned targets (see RunScaled).
    const auto scene = Scaled() ? SceneSize(ow, oh) : std::array<u32, 2>{ow, oh};
    const u32 w = reduced ? scene_targets.Size().width : scene[0];
    const u32 h = reduced ? scene_targets.Size().height : scene[1];
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat ||
        !(color.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
        return;
    }
    if (!EnsureResources(w, h, Scaled() ? target_width : ow,
                         Scaled() ? target_height : oh, !Scaled() || early_upscale)) {
        failed = true;
        return;
    }
    scheduler.EndRendering();
    vk::Image source = color.GetImage();
    vk::ImageLayout source_layout = vk::ImageLayout::eTransferSrcOptimal;
    if (reduced) {
        VideoCore::ImageViewInfo ci;
        ci.format = color.info.pixel_format;
        source = scene_targets.Read(scene_color, ci, vk::PipelineStageFlagBits2::eTransfer,
                                    vk::AccessFlagBits2::eTransferRead).image;
        source_layout = vk::ImageLayout::eGeneral;
    } else {
        runtime.Transit(&color, vk::ImageLayout::eTransferSrcOptimal,
                        vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferRead);
        runtime.FlushBarriers();
    }
    const vk::Image opaque = vk::Image(opaque_image);
    const vk::ImageCopy region{
        .srcSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
        .dstSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
        .extent = {w, h, 1},
    };
    // On the recording thread: direct recording here would move the rest of the scene there.
    scheduler.Record([opaque, source, source_layout, region](vk::CommandBuffer cmdbuf) {
        const auto to_general = [&](vk::PipelineStageFlags2 src_stage, vk::AccessFlags2 src_access,
                                    vk::ImageLayout old_layout, vk::PipelineStageFlags2 dst_stage,
                                    vk::AccessFlags2 dst_access) {
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = src_stage,
                .srcAccessMask = src_access,
                .dstStageMask = dst_stage,
                .dstAccessMask = dst_access,
                .oldLayout = old_layout,
                .newLayout = vk::ImageLayout::eGeneral,
                .image = opaque,
                .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
            };
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
        };
        // The previous frame's mask pass read it: wait for that before overwriting.
        to_general(vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eNone,
                   vk::ImageLayout::eUndefined, vk::PipelineStageFlagBits2::eTransfer,
                   vk::AccessFlagBits2::eTransferWrite);
        cmdbuf.copyImage(source, source_layout, opaque, vk::ImageLayout::eGeneral, region);
        to_general(vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite,
                   vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                   vk::AccessFlagBits2::eShaderRead);
    });
    opaque_valid = true;
}

void TemporalUpscaler::OnSceneComposite() {
    if (!opaque_valid || mask_ready || failed || !ReactiveOn()) {
        return;
    }
    auto& color = texture_cache.GetImage(scene_color);
    const bool reduced = ReducedScene(color);
    const auto scene = Scaled() ? SceneSize(color.info.size.width, color.info.size.height)
                                : std::array<u32, 2>{color.info.size.width, color.info.size.height};
    const u32 w = reduced ? scene_targets.Size().width : scene[0];
    const u32 h = reduced ? scene_targets.Size().height : scene[1];
    if (w != width || h != height || !(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
        return;
    }
    scheduler.EndRendering();
    if (reduced) {
        VideoCore::ImageViewInfo ci;
        ci.format = color.info.pixel_format;
        const auto proxy = scene_targets.Read(scene_color, ci);
        mask_ready = RecordReactive(proxy.view);
        return;
    }
    const auto device = instance.GetDevice();
    const auto color_view = Check(device.createImageView({
        .image = vk::Image(color.backing->image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    runtime.Transit(&color, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                    vk::AccessFlagBits2::eShaderRead);
    runtime.FlushBarriers();
    mask_ready = RecordReactive(color_view);
    scheduler.DeferOperation([device, color_view] { device.destroyImageView(color_view); });
}

bool TemporalUpscaler::RecordReactive(vk::ImageView color_view) {
    if (!opaque_valid || !ReactiveOn()) {
        return false;
    }
    const vk::Image reactive = vk::Image(reactive_image);
    const vk::ImageView opaque = *opaque_view, mask = *reactive_view;
    const vk::Pipeline pipeline = *reactive_pipeline;
    const vk::PipelineLayout layout = *reactive_pipeline_layout;
    const u32 w = width, h = height;
    // Relative color change times the scale (default 1), zero below the threshold (0.2), at
    // most the maximum (0.9, never fully reactive) â€” the defaults of AMD's mask generator.
    const auto& settings = BbSettings::Get();
    const std::array<float, 3> params{settings.reactive_scale, settings.reactive_max,
                                      settings.reactive_threshold};
    scheduler.RecordCrumb({.name = "TAA reactive mask"}, [=](vk::CommandBuffer cmdbuf) {
        const vk::ImageMemoryBarrier2 to_write{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eNone,
            .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eGeneral,
            .image = reactive,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_write});
        const vk::DescriptorImageInfo opaque_info{.imageView = opaque,
                                                  .imageLayout = vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo scene_info{.imageView = color_view,
                                                 .imageLayout = vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo mask_info{.imageView = mask,
                                                .imageLayout = vk::ImageLayout::eGeneral};
        const std::array<vk::WriteDescriptorSet, 3> writes = {{
            {.dstBinding = 0,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &opaque_info},
            {.dstBinding = 1,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &scene_info},
            {.dstBinding = 2,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &mask_info},
        }};
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    writes);
        cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                             sizeof(params), params.data());
        cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
        const vk::ImageMemoryBarrier2 to_read{
            .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
            .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
            .oldLayout = vk::ImageLayout::eGeneral,
            .newLayout = vk::ImageLayout::eGeneral,
            .image = reactive,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_read});
    });
    return true;
}

// bbport: with reduced scene targets the upscaler reads the proxies of the scene colour and
// depth, but the native images were made current first: a resolve of each dirty proxy to the
// output size (~0.07 ms colour, ~0.14 ms depth at 3840x2160). Only the merge's alpha (native
// colour) and the UI depth blit (native depth) read them. Both now read the proxies: the merge
// upscales the alpha as the resolve does, the UI depth blit is nearest from the proxy (what the
// nearest resolve and the blit after it gave), and the merge's whole-image write leaves the native
// colour current without a resolve. Experiment mask 131072 (or BB_PROXY_UPSCALE_INPUTS=0): the
// native images, as before.
static bool ProxyUpscalerInputs() {
    static const bool env = [] {
        const char* value = std::getenv("BB_PROXY_UPSCALE_INPUTS");
        return !value || value[0] != '0';
    }();
    return env && !BbToggle::Experiment(131072);
}

#ifdef BB_TEST_SHARED_POST_GRAPH
static SewerBridge::PhysicalImage PostPhysical(const VideoCore::UniqueImage& owned, u64 generation);

struct PostBorrowTail {
    Scheduler::PostNativeBorrow* active{};
    bool overwrite_attempted{};
    bool breadcrumbs{};

    ~PostBorrowTail() {
        if (active && overwrite_attempted) {
            using Tail = NativeWriteSuffix::PostOverwriteTail;
            active->CloseAfterOverwrite(breadcrumbs ? Tail::BreadcrumbOnly : Tail::NoRawCommands);
        }
    }
};
#endif

void TemporalUpscaler::Run() {
    BB_SECTION(Upscaler);
    if (auto* profiler = GpuProfiler::Get()) {
        const char* label = BbSettings::Get().upscaler == BbSettings::UpscalerTaa
            ? "upscaler Run (TAA)" : "upscaler Run (FSR)";
        profiler->Mark(0xF5A0'0000ull ^ std::hash<std::string_view>{}(label),
                       [label] { return std::string{label}; });
    }
    auto& color = texture_cache.GetImage(scene_color);
    auto& depth = texture_cache.GetImage(camera_motion.Depth());
    const u32 ow = color.info.size.width, oh = color.info.size.height;
    const bool reduced = ReducedScene(color) && scene_targets.EligibleScene(depth);
    const u32 w = reduced ? scene_targets.Size().width : ow;
    const u32 h = reduced ? scene_targets.Size().height : oh;
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat ||
        depth.info.size.width != ow || depth.info.size.height != oh ||
        !(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
        return;
    }
    if (!EnsureResources(w, h, ow, oh, true)) {
        failed = true;
        return;
    }
    const auto depth_format = depth.info.pixel_format;
    const auto depth_view =
        CachedView(depth, depth_format, vk::ImageAspectFlagBits::eDepth);
    const auto color_view =
        CachedView(color, vk::Format::eR16G16B16A16Sfloat, vk::ImageAspectFlagBits::eColor);

    scheduler.EndRendering();
    // bbport: reduced inputs are the proxies (ProxyUpscalerInputs): the native depth is not read
    // here, nor the native colour while its proxy is newer (the merge takes alpha from the proxy).
    const bool proxy_inputs = reduced && ProxyUpscalerInputs();
    const bool alpha_from_proxy = proxy_inputs && scene_targets.NativeStale(color);
    if (!proxy_inputs) {
        runtime.Transit(&depth, vk::ImageLayout::eGeneral,
                        vk::PipelineStageFlagBits2::eComputeShader,
                        vk::AccessFlagBits2::eShaderRead);
    }
    if (!alpha_from_proxy) {
        runtime.Transit(&color, vk::ImageLayout::eGeneral,
                        vk::PipelineStageFlagBits2::eComputeShader,
                        vk::AccessFlagBits2::eShaderRead);
    }
    runtime.FlushBarriers();
    vk::Image input_color = color.GetImage(), input_depth = depth.GetImage();
    vk::ImageView input_color_view = color_view, input_depth_view = depth_view;
#ifdef BB_TEST_SHARED_POST_GRAPH
    // The selected immutable checkpoint can provisionally own the earlier original proxy read.
    std::shared_ptr<SewerMotion::Checkpoint> post_candidate;
    std::shared_ptr<SewerBridge::PostOrder> post_order;
    SceneTargets::Target selected_proxy{};
    if (SewerMotion::FinalEnabled()) {
        const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
        post_candidate = SewerMotion::Find(scheduler.GetWorkSemaphore()->Handle(), frame,
                                            BbEngine::Loading::Generation(), scene_targets.Generation());
        if (post_candidate && post_candidate->needs_present && !post_candidate->vendor_claimed) {
            const SewerBridge::Order::PostKey key{post_candidate->key.request,
                u64(post_candidate->key.checkpoint), post_candidate->key.frame};
            if (const auto capture = scheduler.ArmPostNativeOrder(key)) {
                post_order = std::make_shared<SewerBridge::PostOrder>();
                post_order->owner = &scheduler;
                post_order->key = key;
                post_order->capture = capture;
                post_order->merge = scheduler.ReservePostNativeOperation(
                    capture, SewerBridge::Order::PostRole::Merge, 1);
                if (post_order->merge && alpha_from_proxy) {
                    post_order->proxy_alpha = std::make_shared<SewerBridge::ProxyAlpha>();
                    auto& alpha = *post_order->proxy_alpha;
                    alpha.key = {key.request, key.checkpoint, key.frame};
                    if (jitter[0] != 0.0f || jitter[1] != 0.0f) {
                        alpha.edge_order = scheduler.ReservePostNativeOperation(capture,
                            SewerBridge::Order::PostRole::ProxyEdgeClamp, SewerBridge::PostState::ProxyClampOperation);
                    }
                }
            }
        }
    }
#endif
    if (reduced) {
        VideoCore::ImageViewInfo ci;
        ci.format = color.info.pixel_format;
#ifdef BB_TEST_SHARED_POST_GRAPH
        const auto alpha = post_order ? post_order->proxy_alpha : nullptr;
        const auto c = alpha ? scene_targets.ReadPostProxy(scene_color, ci, alpha->key, alpha->source)
                             : scene_targets.Read(scene_color, ci);
        if (alpha) selected_proxy = c;
#else
        const auto c = scene_targets.Read(scene_color, ci);
#endif
        ci.format = depth.info.pixel_format;
        const auto d = scene_targets.Read(camera_motion.Depth(), ci);
        input_color = c.image;
        input_depth = d.image;
        input_color_view = c.view;
        input_depth_view = d.view;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (BottleRawSearchRequested() && !BbEngine::Loading::ScreenUp()) {
            const auto actual = camera_motion.PassMatrices();
            const auto depth_id = camera_motion.Depth();
            const auto physical = [](VideoCore::ImageId id, const VideoCore::Image& image) {
                return BottleColdSource177::Image{id.index, image.image_uid, image.GetImage(),
                                                   image.backing->image.allocation};
            };
            const auto owned = [&](VideoCore::ImageId id, const VideoCore::Image& image,
                                   const SceneTargets::Target& issued, bool depth_input) {
                const auto found = scene_targets.InspectSewerProxy(id, image.image_uid, issued.view);
                const auto aspect = depth_input ? vk::ImageAspectFlagBits::eDepth : vk::ImageAspectFlagBits::eColor;
                using enum vk::Format;
                if (!proxy_inputs || !found.valid || found.target.image != issued.image ||
                    found.target.view != issued.view || found.target.layout != issued.layout ||
                    issued.layout != vk::ImageLayout::eGeneral || !(found.aspects & aspect) ||
                    found.extent != vk::Extent3D{1920, 1080, 1} ||
                    (depth_input ? found.format != eD32Sfloat && found.format != eD32SfloatS8Uint
                                 : found.format != eR16G16B16A16Sfloat)) {
                    return BottleColdSource177::OrdinaryView{};
                }
                return BottleColdSource177::OrdinaryView{issued.image, issued.view, found.incarnation};
            };
            BottleColdSource177::Current().ReadOrdinary(
                this, BottleCaustic::CutSource::Run(),
                BbStats::frame_number.load(std::memory_order_relaxed), BbEngine::Loading::Generation(),
                scene_targets.Generation(), scheduler.GetWorkSemaphore()->Handle(), scheduler.CurrentTick(),
                actual.valid ? BottleCaustic::CutSource::Camera{actual.view, actual.proj, jitter}
                             : BottleCaustic::CutSource::Camera{},
                physical(depth_id, depth), physical(scene_color, color),
                owned(scene_color, color, c, false), owned(depth_id, depth, d, true));
        }
#endif
    }
    if (jitter[0] != 0.0f || jitter[1] != 0.0f) {
        ClampSceneEdges(scheduler, input_color, w, h
#ifdef BB_TEST_SHARED_POST_GRAPH
                        , post_order ? post_order->proxy_alpha : nullptr
#endif
                        );
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::unique_ptr<Scheduler::PostNativeBorrow> post_borrow;
    if (post_order && post_order->merge) {
        // A non-movable borrow needs to survive the last raw use, including crumb teardown.
        post_borrow.reset(new Scheduler::PostNativeBorrow(scheduler.BorrowPostNativeRoot(post_order->merge)));
    }
    const auto cmdbuf = post_borrow ? post_borrow->Buffer() : scheduler.CommandBuffer();
    PostBorrowTail post_tail{post_borrow.get(), false, bool(post_borrow) && Breadcrumbs::Enabled()};
    const auto post_rgb = post_borrow ? PostPhysical(output_image, sewer_output_generation) :
                                      SewerBridge::PhysicalImage{};
#else
    const auto cmdbuf = scheduler.CommandBuffer();
#endif
    const Breadcrumbs::Scope crumb{cmdbuf, scheduler.CrumbStream(), "TAA"};

    const auto own_barrier = [&](vk::Image image, vk::ImageLayout old_layout,
                                 vk::PipelineStageFlags2 src_stage, vk::AccessFlags2 src_access,
                                 vk::ImageLayout new_layout, vk::PipelineStageFlags2 dst_stage,
                                 vk::AccessFlags2 dst_access) {
        const vk::ImageMemoryBarrier2 barrier{
            .srcStageMask = src_stage,
            .srcAccessMask = src_access,
            .dstStageMask = dst_stage,
            .dstAccessMask = dst_access,
            .oldLayout = old_layout,
            .newLayout = new_layout,
            .image = image,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post_borrow && post_rgb.Valid() && image == post_rgb.image &&
            old_layout == vk::ImageLayout::eGeneral && new_layout == vk::ImageLayout::eGeneral &&
            dst_access == vk::AccessFlagBits2::eShaderRead) {
            post_borrow->NoteOverwriteBarrier(cmdbuf, barrier, {post_rgb.allocator, post_rgb.allocation,
                post_rgb.memory, post_rgb.offset, post_rgb.bytes, post_rgb.generation});
        }
#endif
    };
    const auto all = vk::PipelineStageFlagBits2::eAllCommands;
    const auto rw = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
    MarkUpscalerPart(1, "upscaler: motion vectors");
    // Previous contents are not needed: the layouts start from undefined every frame.
    own_barrier(vk::Image(motion_image), vk::ImageLayout::eUndefined, all,
                vk::AccessFlagBits2::eNone, vk::ImageLayout::eGeneral,
                vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderWrite);
    own_barrier(vk::Image(output_image), vk::ImageLayout::eUndefined, all,
                vk::AccessFlagBits2::eNone, vk::ImageLayout::eGeneral, all, rw);

    camera_motion.RecordMotion(input_depth_view, *motion_view, w, h);
    own_barrier(vk::Image(motion_image), vk::ImageLayout::eGeneral,
                vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderWrite,
                vk::ImageLayout::eGeneral, all, vk::AccessFlagBits2::eShaderRead);
    MarkUpscalerPart(2, "upscaler: frame generation inputs");
    CaptureFrameGenInputs(input_depth_view, w, h);

    MarkUpscalerPart(3, "upscaler: reactive mask");
    const bool has_reactive = mask_ready || RecordReactive(input_color_view);

    const auto now = std::chrono::steady_clock::now();
    float frame_ms = std::chrono::duration<float, std::milli>(now - last_frame).count();
    if (frame_ms <= 0.0f || frame_ms > 200.0f) {
        frame_ms = 16.6f;
    }
    last_frame = now;

    // bbport (r99_interior-exposure, r99b_interior-brightness): meters this HDR scene and its
    // view depth (the camera's projection) for the interior exposure lift (only with
    // BB_INTERIOR_EXPOSURE=1 or 2; otherwise it returns at once and makes nothing).
    InteriorExposure::Meter(instance, scheduler, camera_motion, input_color_view, input_depth_view,
                            w, h);
    MarkUpscalerPart(4, "upscaler: evaluate (DLSS, FSR, XeSS or TAA)");
    std::shared_ptr<SewerMotion::VendorCapture> sewer_observation;
    if (SewerMotion::Enabled()) {
        const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
        const auto timeline = scheduler.GetWorkSemaphore()->Handle();
        auto sample = SewerMotion::Find(timeline, frame, BbEngine::Loading::Generation(),
                                        scene_targets.Generation());
        if (sample && !sample->vendor_claimed) {
            const auto& warp = sample->warp;
            const auto matrices = camera_motion.PassMatrices();
            const auto target = [&](auto id, const VideoCore::Image& parent, vk::Image image,
                                    vk::ImageView view, const SewerMotion::Resource& previous,
                                    vk::ImageAspectFlagBits aspect) {
                const auto check = scene_targets.InspectSewerProxy(id, parent.image_uid, view);
                return id.index == previous.id && parent.image_uid == previous.uid && image && view &&
                       image == previous.image && aspect == previous.aspect && check.target.image == image &&
                       check.target.view == view && check.valid && check.dirty &&
                       check.target.layout == vk::ImageLayout::eGeneral &&
                       check.extent == vk::Extent3D{1920, 1080, 1} && (check.aspects & aspect) &&
                       (check.target.usage & vk::ImageUsageFlagBits::eSampled) &&
                       (aspect != vk::ImageAspectFlagBits::eColor ||
                        (check.target.usage & vk::ImageUsageFlagBits::eTransferSrc));
            };
            if (!early_upscale || !reduced || !proxy_inputs || (frame_gen && frame_gen->Capturing()) ||
                w != 1920 || h != 1080 || ow != 3840 || oh != 2160 ||
                BbEngine::Loading::ScreenUp() || BbSettings::Get().upscaler != BbSettings::UpscalerDlss ||
                !UseFsr4() || !matrices.valid || matrices.view != sample->pose.camera.view ||
                matrices.proj != sample->pose.camera.proj || matrices.inv_view != sample->pose.camera.inv_view ||
                warp.jitter != jitter || scheduler.CurrentTick() < warp.tick ||
                !target(scene_color, color, input_color, input_color_view, warp.color,
                        vk::ImageAspectFlagBits::eColor) ||
                !target(camera_motion.Depth(), depth, input_depth, input_depth_view, warp.depth,
                        vk::ImageAspectFlagBits::eDepth)) {
                sample->VendorRefused("actual-dlss-input-owner-or-scope");
            } else {
                sample->vendor_claimed = true;
                sewer_observation = std::make_shared<SewerMotion::VendorCapture>(std::move(sample));
            }
        }
    }
    bool dispatched = false;
    BbSections::Scope eval_scope{BbSections::UpscalerEval};
    if (BbSettings::Get().upscaler == BbSettings::UpscalerTaa) {
        RecordTaa(cmdbuf, input_color_view, input_depth_view);
        dispatched = true;
    } else if (UseFsr4()) {
        dispatched = RecordFsr4(cmdbuf, {input_color, input_color_view, w, h, color.info.pixel_format},
                                {input_depth, input_depth_view, w, h, depth_format}, w, h, ow, oh,
                                frame_ms, has_reactive, sewer_observation.get());
        if (dispatched && has_reactive && BbSettings::IsFsr4(BbSettings::Get().upscaler)) {
            RecordFsr4Reactive(cmdbuf, input_color_view, w, h, ow, oh);
        }
    } else {
        FfxVkPortableUpscaleDispatchInfo info{};
        info.structSize = sizeof(info);
        info.commandBuffer = cmdbuf;
        info.color = Describe(input_color, color.info.pixel_format, w, h,
                              color.usage_flags, vk::ImageAspectFlagBits::eColor,
                              FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
        info.depth = Describe(input_depth, depth_format, w, h, depth.usage_flags,
                              vk::ImageAspectFlagBits::eDepth,
                              FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
        info.motionVectors = Describe(vk::Image(motion_image), vk::Format::eR16G16Sfloat, w, h,
                                      vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
                                      vk::ImageAspectFlagBits::eColor,
                                      FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
        info.output = Describe(vk::Image(output_image), vk::Format::eR16G16B16A16Sfloat, ow, oh,
                               vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                                   vk::ImageUsageFlagBits::eTransferSrc,
                               vk::ImageAspectFlagBits::eColor,
                               FFX_VK_PORTABLE_RESOURCE_STATE_UNORDERED_ACCESS);
        // Optional inputs, absent: a described but null image.
        info.exposure.structSize = sizeof(info.exposure);
        info.reactiveMask.structSize = sizeof(info.reactiveMask);
        if (has_reactive) {
            info.reactiveMask = Describe(vk::Image(reactive_image), vk::Format::eR8Unorm, w, h,
                                         vk::ImageUsageFlagBits::eStorage |
                                             vk::ImageUsageFlagBits::eSampled,
                                         vk::ImageAspectFlagBits::eColor,
                                         FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
        }
        info.transparencyAndCompositionMask.structSize = sizeof(info.transparencyAndCompositionMask);
        // Toggle 1 << 26 (tests): the opposite sign convention for FSR.
        const float sign = BbToggle::Disabled(1u << 26) ? -1.0f : 1.0f;
        info.jitterOffset = {sign * jitter[0], sign * jitter[1]};
        info.motionVectorScale = {1.0f, 1.0f};
        info.renderSize = {w, h};
        info.outputSize = {ow, oh};
        info.frameTimeMilliseconds = frame_ms;
        info.preExposure = 1.0f;
        info.cameraNear = camera_motion.Near();
        info.cameraFar = 3000.0f;
        info.cameraVerticalFovRadians = camera_motion.VerticalFov();
        info.viewSpaceToMeters = 1.0f;
        // RCAS strength 0..1 (menu, BB_FSR_SHARPNESS); jitter at 1:1 softens the image slightly.
        // AMD's RCAS ends at 1; ExtraSharpen adds the rest of the menu's 0..2.
        info.sharpness = std::min(BbSettings::Get().sharpness.load(), 1.0f);
        info.enableSharpening = BbSettings::Get().sharpen ? VK_TRUE : VK_FALSE;
        info.reset = reset ? VK_TRUE : VK_FALSE;
        info.frameId = frame_id++;
        ApplyFsr3Tuning();
    
        FfxVkPortableUpscaleCreateInfo create_info{};
        create_info.structSize = sizeof(create_info);
        create_info.flags = FFX_VK_PORTABLE_CONTEXT_HDR_COLOR_INPUT | FFX_VK_PORTABLE_CONTEXT_AUTO_EXPOSURE;
        create_info.maxRenderSize = {w, h};
        create_info.maxOutputSize = {ow, oh};
        if (const u64 issues = ffxVkPortableValidateUpscaleDispatchInfo(&create_info, &info)) {
            static bool printed = false;
            if (!printed) {
                printed = true;
                PrintIssues("dispatch", issues);
            }
            failed = true;
        } else if (ffxVkPortableUpscaleContextRecordDispatch(context, &info) !=
                   FFX_VK_PORTABLE_OK) {
            std::printf("Upscaler: FSR 3 dispatch failed\n");
            failed = true;
        } else {
            dispatched = true;
        }
    }
    eval_scope.End();
    if (dispatched) {
        reset = false;
        dispatched_last_frame = true;
        // bbport: the merge below applies the extra sharpen itself, reading the neighbours from
        // the output (no 4K RGBA32F copy, no separate pass and its barriers). Experiment bit
        // 65536 restores the separate pass.
        const bool fold_sharpen = !BbToggle::Experiment(65536);
        const float merge_sharpen =
            BbSettings::Get().upscaler != BbSettings::UpscalerTaa && fold_sharpen
                ? ExtraSharpenStrength()
                : 0.0f;
        if (BbSettings::Get().upscaler != BbSettings::UpscalerTaa && !fold_sharpen) {
            ExtraSharpen(vk::Image(output_image), false, ow, oh);
        }
        // bbport: BB_DUMP_TRIGGER on this (HDR scene color) path too: the upscaler's inputs and
        // its result, for ghosting and history checks (tools/dump_view.py).
        if (const int dump = DumpFrame(); dump >= 0) {
            camera_motion.PrintState(dump);
            const vk::Format format = color.info.pixel_format;
            const bool rgba16f = format == vk::Format::eR16G16B16A16Sfloat;
            const bool r11g11b10 = format == vk::Format::eB10G11R11UfloatPack32;
            if (rgba16f || r11g11b10) {
                DumpImages(instance, scheduler, cmdbuf, dump,
                           {{input_color, w, h, rgba16f ? 8u : 4u, "input",
                             rgba16f ? "rgba16f" : "r11g11b10f"}});
            }
            DumpImages(instance, scheduler, cmdbuf, dump,
                       {{vk::Image(motion_image), w, h, 4, "motion", "rg16f"},
                        {vk::Image(output_image), ow, oh, 8, "output", "rgba16f"}});
            DumpImages(instance, scheduler, cmdbuf, dump,
                       {{input_depth, w, h, 4, "depth", "f32", vk::ImageAspectFlagBits::eDepth}});
            if (const auto object = camera_motion.ObjectMotionImage(w, h); object) {
                DumpImages(instance, scheduler, cmdbuf, dump,
                           {{object, w, h, 16, "objects", "rgba32f"}});
            }
        }
        MarkUpscalerPart(5, "upscaler: merge");
        // The result replaces the scene color's RGB (its alpha carries data for the post).
        own_barrier(vk::Image(output_image), vk::ImageLayout::eGeneral, all, rw,
                    vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                    vk::AccessFlagBits2::eShaderRead);
        if (alpha_from_proxy) {
            // The merge writes every pixel of it and reads alpha from the proxy.
#ifdef BB_TEST_SHARED_POST_GRAPH
            const auto alpha_read = post_order ? post_order->proxy_alpha : nullptr;
            if (alpha_read && sewer_observation && sewer_observation->successful &&
                post_candidate == sewer_observation->checkpoint) {
                alpha_read->before_merge = scene_targets.CheckPostProxyBacking(alpha_read->source, alpha_read->key,
                                                                                  selected_proxy);
            }
#endif
            scene_targets.NativeOverwritten(color);
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (alpha_read && alpha_read->before_merge.resident) {
                alpha_read->after_coherence_drop = scene_targets.CheckPostProxyBacking(
                    alpha_read->source, alpha_read->key, selected_proxy);
            }
#endif
        }
        runtime.Transit(&color, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                        vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        runtime.FlushBarriers();
        const vk::DescriptorImageInfo out_info{.imageView = *output_view,
                                               .imageLayout = vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo scene_info{.imageView = color_view,
                                                 .imageLayout = vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo mask_info{.imageView = *reactive_view,
                                                .imageLayout = vk::ImageLayout::eGeneral};
        // Sampled for the debug view only; the object image falls back to the motion image.
        const vk::ImageView objects = camera_motion.ObjectMotionView();
        const vk::DescriptorImageInfo motion_info{.imageView = *motion_view,
                                                  .imageLayout = vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo objects_info{
            .imageView = objects ? objects : *motion_view,
            .imageLayout = vk::ImageLayout::eGeneral};
        // The scene colour's proxy for its alpha (alpha_from_proxy); else any image in eGeneral.
        const vk::DescriptorImageInfo proxy_info{
            .imageView = alpha_from_proxy ? input_color_view : *motion_view,
            .imageLayout = vk::ImageLayout::eGeneral};
        const std::array<vk::WriteDescriptorSet, 6> writes = {{
            {.dstBinding = 0,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &out_info},
            {.dstBinding = 1,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &scene_info},
            {.dstBinding = 2,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eStorageImage,
             .pImageInfo = &mask_info},
            {.dstBinding = 3,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eSampledImage,
             .pImageInfo = &motion_info},
            {.dstBinding = 4,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eSampledImage,
             .pImageInfo = &objects_info},
            {.dstBinding = 5,
             .descriptorCount = 1,
             .descriptorType = vk::DescriptorType::eSampledImage,
             .pImageInfo = &proxy_info},
        }};
        // Debug (menu or toggle 1 << 28): the reactive mask in red over a darkened frame;
        // or the motion vectors (menu).
        const int debug_view = BbSettings::Get().debug_view;
        const u32 mode = has_reactive && (debug_view == BbSettings::DebugReactive ||
                                          BbToggle::Disabled(1u << 28))
                             ? 1
                         : debug_view == BbSettings::DebugMotion ? 2
                                                                 : 0;
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *merge_pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *merge_pipeline_layout, 0,
                                    writes);
        // 0: the native scene colour's alpha; 1/2: the proxy's, upscaled linear/nearest as its
        // resolve would.
        const u32 alpha_source =
            alpha_from_proxy ? (scene_targets.ResolvesLinear(color) ? 1u : 2u) : 0u;
        const struct {
            u32 mode;
            float sharpen;
            u32 alpha_source;
        } merge_params{mode, merge_sharpen, alpha_source};
        cmdbuf.pushConstants(*merge_pipeline_layout, vk::ShaderStageFlagBits::eCompute, 0,
                             sizeof(merge_params), &merge_params);
        const vk::Extent3D groups{(ow + 7) / 8, (oh + 7) / 8, 1};
        cmdbuf.dispatch(groups.width, groups.height, groups.depth);
#ifdef BB_TEST_SHARED_POST_GRAPH
        const bool same_post = post_borrow && sewer_observation && sewer_observation->successful &&
                               post_candidate == sewer_observation->checkpoint;
        if (same_post) {
            using namespace NativeWriteSuffix;
            static std::atomic<u64> issued_merges{};
            const auto current_write = issued_merges.fetch_add(1, std::memory_order_relaxed) + 1;
            const auto alpha = alpha_source ? scene_targets.InspectSewerProxy(scene_color, color.image_uid,
                                                                                input_color_view)
                                            : SceneTargets::SewerProxy{};
            PostMergeRootProof observed{
                .origin = post_borrow->Origin(), .pipeline = *merge_pipeline, .layout = *merge_pipeline_layout,
                .rgb = {post_rgb.image, out_info.imageView, post_rgb.allocator, post_rgb.allocation, post_rgb.memory,
                    post_rgb.offset, post_rgb.bytes, post_rgb.generation, 0, post_rgb.range,
                    vk::Extent2D{post_rgb.extent.width, post_rgb.extent.height}, post_rgb.format,
                    out_info.imageLayout, post_rgb.samples},
                .destination = {.image = color.GetImage(), .view = scene_info.imageView,
                    .content_version = current_write, .extent = {ow, oh}, .format = color.info.pixel_format,
                    .layout = scene_info.imageLayout, .samples = color.backing->image.image_ci.samples},
                .alpha = {.image = alpha.target.image, .view = alpha.target.view,
                    .extent = {alpha.extent.width, alpha.extent.height}, .format = alpha.format,
                    .layout = alpha.target.layout},
                .groups = groups, .mode = mode, .alpha_source = alpha_source,
                .program = PostMergeProgram::UpscaleMerge,
                .predecessor = PostPredecessor::Unknown,
            };
            if (const auto& earlier = post_order->proxy_alpha; earlier && earlier->before_merge.resident &&
                earlier->after_coherence_drop.resident) {
                const auto& input = sewer_observation->consumed_color;
                const auto& output = sewer_observation->actual_output;
                const auto& binding = earlier->source.binding;
                const auto& owner = binding.proxy;
                const bool same_color = input.image == binding.image && input.view == binding.view &&
                    input.width == binding.extent.width && input.height == binding.extent.height &&
                    input.format == binding.format && input_color_view == proxy_info.imageView;
                // This is the ordinary NGX resource descriptor's read_only Color operand.
                earlier->vendor_color_read_only = same_color ? SewerBridge::Graph::Proof::Known
                                                             : SewerBridge::Graph::Proof::Failed;
                const PostProxyProof::Backing rgb{post_rgb.image, post_rgb.allocator, post_rgb.allocation,
                                                       post_rgb.memory, post_rgb.offset, post_rgb.bytes};
                const bool same_output = output.image == post_rgb.image && output.view == out_info.imageView &&
                    output.width == post_rgb.extent.width && output.height == post_rgb.extent.height &&
                    output.format == post_rgb.format && post_rgb.Valid();
                if (same_output && owner && binding.native) {
                    earlier->vendor_output_disjoint = PostProxyProof::Distinct(owner, rgb) &&
                        PostProxyProof::Distinct(binding.native, rgb) ? SewerBridge::Graph::Proof::Known
                                                                       : SewerBridge::Graph::Proof::Failed;
                }
                if (same_color) {
                    const auto& strips = earlier->strips;
                    const auto result_version = SewerBridge::IssuedProxyStripShape(*earlier) ? strips.issued_version : 0;
                    observed.alpha = SewerBridge::ScopedProxyImage(binding, result_version);
                    observed.prior_proxy = {
                        .transition = earlier->transition_order, .edges = earlier->edge_order,
                        .owner = {binding.owner, binding.generation},
                        .vendor = {.origin = observed.origin, .color = observed.alpha,
                            .output = same_output ? observed.rgb : PostMergeImage{},
                            .result = PostProxyVendorResult::SuccessfulDlss,
                            .color_read_write = false, .output_read_write = same_output},
                    };
                }
            }
            // Runtime exports later emitted rows. A late copy cannot prove this borrow's alpha
            // allocation, native predecessor version or the two missing before-dispatch barriers.
            post_tail.overwrite_attempted = true;
            post_borrow->NoteOverwriteRoot(cmdbuf, observed);
            fmt::print("[sewer-motion] event=postgraph-merge-shape request={} frame={} checkpoint={} "
                       "mode={} alpha={} rgb_owner={} dst_write={} prior_writer=unknown "
                       "dst_barrier=unknown alpha_same_borrow_barrier=unknown vendor_owner=unknown\n",
                       post_candidate->key.request, post_candidate->key.frame, post_candidate->key.checkpoint,
                       mode, alpha_source, post_rgb.Valid(), current_write);
        }
#endif
        if (sewer_observation && sewer_observation->successful) {
            auto& sample = *sewer_observation->checkpoint;
            const auto& ci = color.backing->image.image_ci;
            if (mode == 0 && color.write_seq && ci.format == vk::Format::eR16G16B16A16Sfloat &&
                ci.extent == vk::Extent3D{3840, 2160, 1} && ci.mipLevels == 1 && ci.arrayLayers == 1 &&
                ci.samples == vk::SampleCountFlagBits::e1 && !color.binding.needs_rebind &&
                color.backing->subresource_states.empty() &&
                color.backing->state.layout == vk::ImageLayout::eGeneral &&
                texture_cache.IsRegisteredImage(scene_color, color.image_uid)) {
                sample.merge = {
                    .key = sample.key,
                    .destination = {scene_color.index, color.image_uid, color.GetImage(), scene_info.imageView,
                                    vk::ImageAspectFlagBits::eColor},
                    .output = vk::Image(output_image), .output_view = out_info.imageView,
                    .timeline = scheduler.GetWorkSemaphore()->Handle(), .tick = scheduler.CurrentTick(),
                    .write = color.write_seq, .mode = mode, .alpha = alpha_source,
                    .sharpen = fold_sharpen ? merge_sharpen : ExtraSharpenStrength(), .folded = fold_sharpen,
                };
                sample.has_merge = true;
                SewerArm(sewer_observation->checkpoint, cmdbuf, scene_color
#ifdef BB_TEST_SHARED_POST_GRAPH
                         , same_post ? post_order : nullptr
#endif
                         );
                fmt::print("[sewer-motion] event=merge request={} checkpoint={} frame={} tick={} "
                           "dst={}/{}:{:x}/{:x} write={} source={:x}/{:x} alpha={} mode={} "
                           "sharp={:.9g} folded={} presentation=pending\n",
                           sample.key.request, sample.key.checkpoint, sample.key.frame, sample.merge.tick,
                           sample.merge.destination.id, sample.merge.destination.uid,
                           std::bit_cast<u64>(VkImage(sample.merge.destination.image)),
                           std::bit_cast<u64>(VkImageView(sample.merge.destination.view)), sample.merge.write,
                           std::bit_cast<u64>(VkImage(sample.merge.output)),
                           std::bit_cast<u64>(VkImageView(sample.merge.output_view)),
                           alpha_source, mode, sample.merge.sharpen, unsigned(fold_sharpen));
            }
        }
        MarkUpscalerPart(6, "upscaler: after Run (unlabelled work up to the next label)");
        if (BottleMotion::Run()) {
            auto& s=BottleMotion::Scene();
            if (s.mark && !s.bad) {
                const auto matrices=camera_motion.PassMatrices();
                const auto tick=scheduler.CurrentTick();
                if (s.dlss || !s.vendor_ok || !early_upscale || !reduced || !proxy_inputs ||
                    BbSettings::Get().upscaler!=BbSettings::UpscalerDlss ||
                    w!=1920 || h!=1080 || ow!=3840 || oh!=2160 || !matrices.valid ||
                    s.mark.on!=u8(BottleCaustic::On()) || s.arm_generation!=BbLiveKnobs::Generation() ||
                    s.mark.timeline!=scheduler.GetWorkSemaphore()->Handle() ||
                    (s.mark.on && (!s.bottle || s.bottle_tick>tick ||
                     s.generation!=scene_targets.Generation() || s.color_id!=scene_color.index ||
                     s.depth_id!=camera_motion.Depth().index ||
                     s.color_uid!=color.image_uid || s.depth_uid!=depth.image_uid ||
                     s.color!=input_color || s.depth!=input_depth || s.color_view!=input_color_view ||
                     s.depth_view!=input_depth_view || s.view!=matrices.view ||
                     s.proj!=matrices.proj || s.jitter!=jitter))) {
                    BottleMotion::Refuse(s,"actual-dlss-scene-inputs");
                } else {
                    s.dlss=true;
                    s.hdr=color.GetImage();s.hdr_uid=color.image_uid;s.hdr_write=color.write_seq;
                    s.generation=scene_targets.Generation();
                    s.view=matrices.view;s.proj=matrices.proj;s.jitter=jitter;
                }
            }
        }
    }
    if (sewer_observation) {
        if (sewer_observation->copied) {
            scheduler.DeferOperation([scope = std::move(sewer_observation)]() mutable {
                auto sample = scope->checkpoint;
                scope->Report();
                scope.reset();
                sample->Retire(SewerMotion::Vendor);
            }, "sewer motion DLSS readback");
        } else {
            sewer_observation->checkpoint->VendorRefused(
                sewer_observation->refused ? sewer_observation->refused : "vendor-copy-unissued");
        }
    }
}

vk::ImageView TemporalUpscaler::CachedView(const VideoCore::Image& image, vk::Format format,
                                           vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
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
        .format = format,
        .aspect = aspect,
        .view = Check(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

} // namespace Vulkan

namespace Vulkan {

std::array<u32, 2> TemporalUpscaler::SceneSize(u32 w, u32 h) const {
    if (!scaled_session) return {render_width, render_height};
    // The game's own render size (scene constants); BB_RENDER_RES until the first camera.
    auto size = camera_motion.RenderSize();
    if (size[0] == 0 || size[1] == 0) {
        size = {render_width, render_height};
    }
    return {std::min(size[0], w), std::min(size[1], h)};
}

float TemporalUpscaler::SceneMipBias() const {
    if (!Active() || BbSettings::Get().upscaler == BbSettings::UpscalerTaa) return 0.0f;
    const float render = float(BbSettings::Get().active_render_width.load());
    const float output = float(Scaled() ? target_width : 1920u);
    const float scale_bias = render > 0.0f && render < output ? std::log2(render / output) : 0.0f;
    // DLSS (DLAA too) wants one more mip level of texture detail than the render/output ratio
    // (NVIDIA's DLSS programming guide). From AwesomeObserver/bloodborne_pc b3164c1
    // (Evgeniy Doronin). dlss_mip_bias=0 (menu, BB_DLSS_MIP_BIAS=0): the ratio only, as before.
    const bool dlss_extra = BbSettings::Get().dlss_mip_bias.load(std::memory_order_relaxed);
    const bool dlss_on = BbSettings::Get().upscaler == BbSettings::UpscalerDlss && UseFsr4();
    // bbport: mip_bias (menu, launcher), the player's own offset on top, as OptiScaler's override.
    const float offset = std::clamp(BbSettings::Get().mip_bias.load(std::memory_order_relaxed),
                                    BbSettings::MipBiasMin, BbSettings::MipBiasMax);
    return scale_bias - (dlss_extra && dlss_on ? 1.0f : 0.0f) + offset;
}

void TemporalUpscaler::ApplyFsr3Tuning() {
    if (!context) {
        return;
    }
    const auto& s = BbSettings::Get();
    const std::array<float, 5> wanted{
        s.fsr3_velocity_factor.load(std::memory_order_relaxed),
        s.fsr3_reactiveness_scale.load(std::memory_order_relaxed),
        s.fsr3_shading_change_scale.load(std::memory_order_relaxed),
        s.fsr3_accumulation.load(std::memory_order_relaxed),
        s.fsr3_min_disocclusion.load(std::memory_order_relaxed),
    };
    if (fsr3_tuned == context && wanted == fsr3_tuning) {
        return;
    }
    // The portable context serializes this with its dispatches (also on the recording threads).
    const FfxVkPortableUpscaleTuning tuning{
        .structSize = sizeof(FfxVkPortableUpscaleTuning),
        .velocityFactor = wanted[0],
        .reactivenessScale = wanted[1],
        .shadingChangeScale = wanted[2],
        .accumulationAddedPerFrame = wanted[3],
        .minDisocclusionAccumulation = wanted[4],
    };
    if (ffxVkPortableUpscaleContextSetTuning(context, &tuning) == FFX_VK_PORTABLE_OK) {
        if (fsr3_tuned == context) {
            std::printf("Upscaler: FSR 3.1 tuning: velocity %.2f, reactiveness %.2f, shading %.2f, "
                        "accumulation %.3f, disocclusion %.3f\n",
                        wanted[0], wanted[1], wanted[2], wanted[3], wanted[4]);
        }
        fsr3_tuning = wanted;
        fsr3_tuned = context;
    }
}

bool TemporalUpscaler::Scaled() const {
    return scaled_session || target_width != 1920 || target_height != 1080;
}

void TemporalUpscaler::OnColorTarget(VideoCore::ImageId color) {
    if (ui_phase || !camera_motion.Depth()) {
        return;
    }
    const auto& image = texture_cache.GetImage(color);
    const auto& depth = texture_cache.GetImage(camera_motion.Depth());
    if (image.info.pixel_format == vk::Format::eR8G8B8A8Unorm &&
        image.info.size.width == depth.info.size.width &&
        image.info.size.height == depth.info.size.height) {
        ldr_target = color;
    }
}

void TemporalUpscaler::OnDraw(u64 vs_hash, VideoCore::ImageId color,
                              VideoCore::ImageId depth, bool native_viewport,
                              bool widened_ui_viewport) {
    // bbport: frame generation: the game's finished frame before the first UI pixel (as for
    // native HDR below); the scaled presets copy the output-size UI image after the upscale.
    if (frame_gen && frame_gen->WantsHudless() && !Scaled() &&
        (vs_hash == ui_trigger_vs || UiComposition::MovieShader(vs_hash))) {
        CaptureFrameGenHudless(LdrFrame(color)        ? color
                               : LdrFrame(ldr_target) ? ldr_target
                                                      : VideoCore::ImageId{});
    }
    if (!Scaled() && vs_hash == ui_trigger_vs) done_this_frame = true;
    // bbport: native HDR output: the game's tonemapped frame before the first UI pixel (the
    // first Scaleform draw of any kind). A stencil-only first pass binds no colour: the last
    // frame-size RGBA8 target then. (WantsUiStart first: two flags, false unless native HDR saw
    // this frame's scene and no UI yet.)
    if (hdr_native.WantsUiStart() && !Scaled() &&
        (vs_hash == ui_trigger_vs || UiComposition::MovieShader(vs_hash)) &&
        HdrNative::Wanted()) {
        hdr_ui_target = LdrFrame(color)        ? color
                        : LdrFrame(ldr_target) ? ldr_target
                                               : VideoCore::ImageId{};
        hdr_native.OnUiStart(hdr_ui_target
                                 ? hdr_native.Guest(hdr_ui_target, vk::Format::eR8G8B8A8Unorm)
                                 : HdrNative::Source{});
    }
    if (!Scaled()) {
        return;
    }
    if (ui_phase) {
        // A UI movie can start without stencil and enable it for later text/masks.
        if ((color == ui_color || (!color && UiComposition::MovieShader(vs_hash))) &&
            depth && depth != ui_depth) {
            EnsureUiResources(ui_width, ui_height, ui_format,
                              texture_cache.GetImage(depth).info.pixel_format);
            PrepareUiDepth(depth);
            ui_depth = depth;
        }
        return;
    }
    if (!color) {
        return;
    }
    const auto& image = texture_cache.GetImage(color);
    // A UI movie's viewport marks a UI draw only while the scene is of another size: at the same
    // size every full-screen post pass has it too (Sharp UI with Native AA), and the UI then
    // starts with the game's Scaleform shaders instead.
    // The widened UI viewport (a 4K UI over a scene near 1920x1080) still marks one: the post
    // passes then have the 1920x1080 one, never the widened one (0.9.34 beta 9.8 to 0.9.37 beta 3:
    // the title screen's movie drew its 4K layout into the scene target, a quarter of it shown).
    const bool movie = vs_hash == ui_trigger_vs || UiComposition::MovieShader(vs_hash) ||
                       (scaled_session && native_viewport &&
                        !UiComposition::SceneHasUiViewportSize(render_width, render_height)) ||
                       (scaled_session && widened_ui_viewport &&
                        !UiComposition::SceneNearUiSize(render_width, render_height));
    const bool ui_draw = movie &&
        (image.info.pixel_format == vk::Format::eR8G8B8A8Unorm ||
         image.info.pixel_format == vk::Format::eR8G8B8A8Srgb) &&
        RenderTarget(image.info.size.width, image.info.size.height) &&
        !FrameCapture::IsDisplayBuffer(image.info.guest_address);
    switch (UiComposition::Choose(Scaled(), ui_draw,
                                  camera_motion.Ready() && ldr_target == color,
                                  Active() && !failed && !early_upscale)) {
    case UiComposition::Background::None:
        return;
    case UiComposition::Background::Temporal:
        RunScaled();
        if (ui_phase) {
            break;
        }
        // A failed FSR dispatch must not force UI text back to the scene resolution.
        [[fallthrough]];
    case UiComposition::Background::Copy:
        RunUiOnly(color, depth, ldr_target && ldr_target == color);
        break;
    }
    if (ui_phase) {
        CaptureFrameGenUiImage();
    }
    // bbport: native HDR output: the output-size frame the UI is about to be drawn into.
    if (ui_phase && hdr_native.WantsUiStart() && HdrNative::Wanted()) {
        hdr_native.OnUiStart(HdrUiImage());
    }
}

bool TemporalUpscaler::LdrFrame(VideoCore::ImageId id) const {
    if (!id) {
        return false;
    }
    const auto& image = texture_cache.GetImage(id);
    return (image.info.pixel_format == vk::Format::eR8G8B8A8Unorm ||
            image.info.pixel_format == vk::Format::eR8G8B8A8Srgb) &&
           RenderTarget(image.info.size.width, image.info.size.height) &&
           !FrameCapture::IsDisplayBuffer(image.info.guest_address);
}

bool TemporalUpscaler::Round2NativeLdr(VideoCore::ImageId frame) const {
    return !Scaled() && !ui_phase && !display_redirect && !dispatched_last_frame &&
           BbSettings::Get().frame_gen.load(std::memory_order_relaxed) == BbSettings::FrameGenOff &&
           (!frame_gen || !frame_gen->Capturing()) && !HdrNative::Wanted() && LdrFrame(frame);
}

HdrNative::Source TemporalUpscaler::HdrUiImage() {
    // The upscaler's own image, in General layout (written by FSR or the background copy, then
    // the UI draws): the native passes' barriers order their reads against both.
    return {vk::Image(ui_image),
            Mirror(vk::Image(ui_image), ui_views, vk::Format::eR8G8B8A8Unorm, {}), ui_width,
            ui_height};
}

SewerBridge::Native TemporalUpscaler::SewerNative(VideoCore::ImageId id, vk::Format format,
                                                  vk::ImageView view) {
    using namespace SewerBridge;
    const auto* image = id ? texture_cache.TryGetImage(id, 0) : nullptr;
    if (!image || !image->backing || !image->GetImage() || image->binding.needs_rebind ||
        !texture_cache.IsRegisteredImage(id, image->image_uid) || !image->SafeToDownload() ||
        scene_targets.NativeStale(*image) || image->info.pixel_format != format ||
        image->aspect_mask != Color || image->info.resources != VideoCore::SubresourceExtent{1, 1} ||
        !image->guest_begin || image->guest_begin >= image->guest_end ||
        image->track_addr != image->guest_begin || image->track_addr_end != image->guest_end ||
        !image->backing->image.allocation || !image->backing->subresource_states.empty()) return {};
    const auto& ci = image->backing->image.image_ci;
    if (ci.imageType != vk::ImageType::e2D || ci.format != format ||
        ci.extent != vk::Extent3D{3840, 2160, 1} || ci.mipLevels != 1 || ci.arrayLayers != 1 ||
        ci.samples != vk::SampleCountFlagBits::e1 || image->info.num_samples != 1) return {};
    if (view) {
        unsigned joined = 0;
        for (const auto key : image->backing->image_view_ids) {
            const auto& candidate = texture_cache.GetImageView(key);
            const auto& range = candidate.info.range;
            joined += candidate.image_view.get() == view && candidate.info.format == format &&
                      !candidate.info.is_storage && range.base.level == 0 && range.base.layer == 0 &&
                      range.extent == VideoCore::SubresourceExtent{1, 1};
        }
        if (joined != 1) return {};
    }
    bool exclusive = true;
    texture_cache.ForEachImageInRegion(image->guest_begin, image->guest_end - image->guest_begin,
        [&](VideoCore::ImageId other, VideoCore::Image&) { exclusive &= id == other; });
    if (!exclusive) return {};
    return {{id.index, image->image_uid, image->GetImage(), view, Color}, image->write_seq,
            image->guest_begin, image->guest_end, image->backing, image->backing->image.allocation
#ifdef BB_TEST_SHARED_POST_GRAPH
            , format
#endif
            };
}

static bool SewerSameCamera(const SewerBridge::Trace& tap, const CameraMotion::Matrices& camera,
                            std::array<float, 2> jitter) {
    const auto& original = tap.checkpoint->pose.camera;
    return camera.valid && camera.view == original.view && camera.inv_view == original.inv_view &&
           camera.proj == original.proj && tap.checkpoint->warp.jitter == jitter;
}

void TemporalUpscaler::SewerArm(const std::shared_ptr<SewerMotion::Checkpoint>& sample,
                                 vk::CommandBuffer cmdbuf, VideoCore::ImageId id
#ifdef BB_TEST_SHARED_POST_GRAPH
                                 , std::shared_ptr<SewerBridge::PostOrder> order
#endif
                                 ) {
    using namespace SewerBridge;
    if (!sample->needs_present) return;
    if (sewer_bridge && sewer_bridge->Open()) {
        sewer_bridge->Stop("unretired-display-scope");
        sample->FinishPresentation(false, "previous-display-scope-active");
        return;
    }
    const auto hdr = SewerNative(id, vk::Format::eR16G16B16A16Sfloat, {});
    if (!hdr.res.image || !SewerPresent::SameBacking(hdr.res, sample->merge.destination) ||
        hdr.write != sample->merge.write || !cmdbuf || !sample->merge.timeline) {
        sample->FinishPresentation(false, "native-hdr-merge-owner");
        return;
    }
    SewerPresent::Regions regions{};
    const auto push = [&](SewerPresent::Role role, vk::Offset2D p) {
        regions.points[regions.count++] = {role, p};
    };
    const auto point = [](SewerMotion::Vec2 p) { return vk::Offset2D{s32(p[0]), s32(p[1])}; };
    for (u32 i = 0; i < 3; ++i) push(SewerPresent::Role(i), point(sample->pose.output[i]));
    if (sample->key.checkpoint == 'A') {
        sewer_a_request = sample->key.request;
        sewer_a_points = {regions.points[0].centre, regions.points[1].centre};
    } else if (sewer_a_request == sample->key.request) {
        push(SewerPresent::Role::Vacated0, sewer_a_points[0]);
        push(SewerPresent::Role::Vacated1, sewer_a_points[1]);
    }
    const auto a = OpaquePoint(sample->pose.camera, {17.314748f, -28.674114f, 101.997937f});
    const auto b = OpaquePoint(sample->pose.camera, {14.954797f, -28.333264f, 103.857976f});
    if (!a || !b) {
        sample->FinishPresentation(false, "opaque-landmark-projection");
        return;
    }
    push(SewerPresent::Role::Opaque0, *a);
    push(SewerPresent::Role::Opaque1, *b);
    if (!regions.Valid(sample->key.checkpoint)) {
        sample->FinishPresentation(false, "invalid-final-region-set");
        return;
    }
    sewer_bridge = std::make_shared<Trace>(sample, cmdbuf, hdr, regions);
#ifdef BB_TEST_SHARED_POST_GRAPH
    auto& trace = *sewer_bridge;
    auto post = std::make_unique<PostState>();
    Graph::Scope scope{};
    scope.key = {sample->key.request, sample->key.scene, sample->key.loading, sample->key.generation,
                 std::bit_cast<u64>(instance.GetGraphicsQueue()), std::bit_cast<u64>(sample->merge.timeline),
                 sample->key.frame, Graph::Client::Sewer, sample->key.enabled ? Graph::Arm::On : Graph::Arm::Off,
                 sample->key.checkpoint};
    scope.width = SewerPresent::Extent.width;
    scope.height = SewerPresent::Extent.height;
    scope.count = regions.count;
    constexpr std::array roles{Graph::ProbeRole::Wet0, Graph::ProbeRole::Wet1, Graph::ProbeRole::Dry,
        Graph::ProbeRole::Vacated0, Graph::ProbeRole::Vacated1, Graph::ProbeRole::Opaque0, Graph::ProbeRole::Opaque1};
    for (u32 i = 0; i < regions.count; ++i) {
        const auto region = regions.points[i];
        scope.probes[i] = {roles[unsigned(region.role)], u32(region.centre.x - SewerPresent::Side / 2),
            u32(region.centre.y - SewerPresent::Side / 2), SewerPresent::Side, SewerPresent::Side};
    }
    if (!post->packet.Begin(scope, +[](void*, const BottleMotion203::TerminalReceipt& receipt) {
        fmt::print("[sewer-motion] event=postgraph request={} frame={} checkpoint={} entries={} "
                   "omitted_events={} omitted_inputs={} foreign={} fence={} ready={}\n",
                   receipt.scope.key.request, receipt.scope.key.frame, receipt.scope.key.checkpoint,
                   receipt.entries.size(), receipt.omitted_events, receipt.omitted_inputs,
                   receipt.foreign_events, unsigned(receipt.fence), unsigned(receipt.ready));
        for (const auto& row : receipt.entries) {
            fmt::print("[sewer-motion] event=postgraph-entry request={} ordinal={} kind={} step={} "
                       "shader={:08x} permutation={:x} backing={:x} view={:x} format={} writer={} "
                       "command={:x} tick={} inputs={} known={:x} failed={:x} unknown={:x}\n",
                       receipt.scope.key.request, row.event.order, unsigned(row.event.kind),
                       unsigned(row.event.step), row.event.shader, row.event.permutation,
                       row.event.output.backing, row.event.output.view, unsigned(row.event.output.format),
                       row.event.output.content, row.event.actual.command, row.event.actual.tick, row.input_count,
                       row.facts.known, row.facts.failed, row.facts.unknown);
        }
    }, nullptr)) {
        trace.Stop("postgraph-scope-unavailable");
        return;
    }
    post->merge = {reinterpret_cast<u64>(hdr.allocation), std::bit_cast<u64>(sample->merge.destination.view),
                   hdr.res.uid, hdr.res.uid, sample->merge.write, {0, 1, 0, 1, 1}, Graph::Format::Rgba16Float};
    post->merge_command = std::bit_cast<u64>(cmdbuf);
    post->order = std::move(order);
    if (post->order) {
        post->terminal.runtime_window = runtime.ArmPostImageBarriers({
            scope.key.request, u64(scope.key.checkpoint), scope.key.frame});
    }
    if (!post->order) {
        fmt::print("[sewer-motion] event=postgraph-order-refused request={} checkpoint={} frame={} "
                   "reason=early-scheduler-owner-unavailable\n",
                   scope.key.request, scope.key.checkpoint, scope.key.frame);
    }
    trace.post = std::move(post);
#endif
}

#ifdef BB_TEST_SHARED_POST_GRAPH
static SewerBridge::PhysicalImage PostPhysical(const VideoCore::UniqueImage& owned, u64 generation) {
    const auto& ci = owned.image_ci;
    if (!owned || !owned.allocator || !owned.allocation || !generation || ci.imageType != vk::ImageType::e2D ||
        ci.mipLevels != 1 || ci.arrayLayers != 1 || ci.extent.depth != 1) return {};
    VmaAllocationInfo range{};
    vmaGetAllocationInfo(owned.allocator, owned.allocation, &range);
    return {vk::Image(owned), owned.allocator, owned.allocation, vk::DeviceMemory(range.deviceMemory),
            range.offset, range.size, generation, ci.format, ci.extent, ci.samples,
            {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
}

bool TemporalUpscaler::SewerPostDisplayPending() const {
    return SewerBridgeOpen() && sewer_bridge->post &&
           sewer_bridge->planned == SewerBridge::Planned::DisplayExpected;
}

static bool PostProgram(u64 ps) {
    return ps == 0xccbf44a6 || ps == 0xed4c7668 || ps == 0x8c08444c ||
           Shader::Native::IsKnownComposite(ps);
}

std::shared_ptr<SewerBridge::PostDraw> TemporalUpscaler::SewerBeginPostDraw(
    u64 scene, u64 ps, VideoCore::ImageId target, const void* buffer_cache) {
    using namespace SewerBridge;
    if (!SewerBridgeOpen() || !sewer_bridge->post) return {};
    auto& trace = *sewer_bridge;
    auto& post = *trace.post;
    if (post.ui_tick) return {};
    const bool candidate = PostProgram(ps);
    const auto* image = target ? texture_cache.TryGetImage(target, 0) : nullptr;
    const bool possible_writer = image && image->info.size.width == 3840 && image->info.size.height == 2160 &&
        (image->info.pixel_format == vk::Format::eR16G16B16A16Sfloat ||
         image->info.pixel_format == vk::Format::eR8G8B8A8Unorm);
    if (!candidate && !possible_writer) return {};
    if (post.count == post.draws.size()) {
        ++post.omitted;
        return {};
    }
    if (candidate && !post.geometry) post.geometry = PostGeometry::Capture::Create(buffer_cache);
    auto draw = std::make_shared<PostDraw>();
    draw->geometry_key = {trace.merge.key.request, scene, post.count + 1, std::bit_cast<u64>(trace.merge.timeline),
                          BbStats::frame_number.load(std::memory_order_relaxed)};
    if (candidate) draw->geometry = post.geometry;
    draw->color_id = target;
    draw->ps = ps;
    if (post.order) {
        draw->native_order = scheduler.ReservePostNativeOperation(
            post.order->capture.load(std::memory_order_acquire), Order::PostRole::Draw, post.count + 2);
    }
    post.draws[post.count++] = draw;
    return draw;
}

void TemporalUpscaler::SewerPostBindings(SewerBridge::PostDraw& draw, std::span<const VideoCore::ImageId> images) {
    for (u32 i = 0; i < draw.slots.count; ++i) {
        const auto& slot = draw.slots.images[i];
        if (!slot.exact || !slot.view) continue;
        for (const auto id : images) {
            const auto* image = id ? texture_cache.TryGetImage(id, 0) : nullptr;
            if (!image) continue;
            if (draw.slot_images[i].res.id == id.index) continue; // same exact image in one draw can repeat
            const auto source = SewerNative(id, image->info.pixel_format, slot.view);
            if (!source.res.image) continue;
            if (draw.slot_images[i].res.image) {
                draw.slot_images[i] = {};
                draw.slots.images[i].exact = false;
                break;
            }
            draw.slot_images[i] = source;
        }
    }
}

void TemporalUpscaler::SewerPostFinal(SewerBridge::PostDraw& draw, const SewerBridge::DrawFacts& facts) {
    const auto& root = *sewer_bridge;
    draw.tick = scheduler.CurrentTick();
    if (draw.geometry_key.request != root.merge.key.request ||
        draw.geometry_key.frame != root.merge.key.frame ||
        draw.geometry_key.timeline != std::bit_cast<u64>(root.merge.timeline)) return;
    draw.camera = SewerSameCamera(root, camera_motion.PassMatrices(), jitter);
    draw.original = facts.original && draw.color_id == facts.color_id && draw.ps == facts.ps;
    draw.full_write = facts.full_write;
    draw.attachment = facts.attachment;
    draw.scissor = facts.scissor;
    draw.output = facts.output;
    draw.output_layout = facts.layout;
    if (const auto* image = facts.color_id ? texture_cache.TryGetImage(facts.color_id, 0) : nullptr) {
        draw.output_format = image->info.pixel_format;
        draw.destination = SewerNative(facts.color_id, image->info.pixel_format, facts.output);
    }
}

static BottleAncestry::ImageVersion PostImage(const SewerBridge::Native& image, vk::Format format, u64 write) {
    if (!image.res.view || !image.allocation || !write) return {};
    return {reinterpret_cast<u64>(image.allocation), std::bit_cast<u64>(image.res.view), image.res.uid,
            image.res.uid, write, {0, 1, 0, 1, 1}, BottleMotion203::Format(format)};
}

static bool SewerPostOrderReceipt(Scheduler& scheduler, const SewerBridge::PostOrder* scope,
                                  NativeWriteSuffix::PostToken token, BottleAncestry::IssueOrder& actual,
                                  u64* completed_tick = nullptr) {
    using namespace SewerBridge;
    Order::PostReceipt receipt{};
    const bool found = scope && token && scheduler.ReadPostNativeOperation(token, receipt);
    const bool matched = found && MatchedPostSubmission(receipt, scope->key, token, actual);
    const bool fenced = matched && receipt.phase == Order::PostPhase::Retired;
    if (completed_tick && fenced) *completed_tick = receipt.completed_tick;
    if (matched) {
        actual.submission = receipt.submission.tick;
        actual.incarnation = receipt.where.tick;
        actual.segment = receipt.where.submitted_index;
        actual.ordinal = u32(receipt.where.encoding);
        actual.submitted = Graph::Proof::Known;
    }
    // A scheduler position does not attest which barriers protect a particular image version.
    if (scope) {
        fmt::print("[sewer-motion] event=postgraph-order request={} checkpoint={} frame={} "
                   "operation={} role={} phase={} joined={} matched={} gaps={:x} command={:x} tick={} "
                   "submission={} segment={} ordinal={} queue={:x} timeline={:x} fence={:x} "
                   "fence_tick={} waits={} signals={} overwrite={} prior_proxy_phase={} resource_dependencies=unknown\n",
                   scope->key.request, scope->key.checkpoint, scope->key.frame, token.operation,
                   unsigned(token.role), unsigned(receipt.phase), receipt.stream_joined, matched,
                   receipt.gaps, matched ? actual.command : 0, matched ? actual.tick : 0, actual.submission,
                   actual.segment, actual.ordinal, std::bit_cast<u64>(receipt.submission.queue),
                   std::bit_cast<u64>(receipt.submission.timeline), std::bit_cast<u64>(receipt.submission.fence),
                   receipt.completed_tick, receipt.submission.wait_count, receipt.submission.signal_count,
                   bool(receipt.overwrite), unsigned(receipt.proxy.phase));
    }
    return fenced;
}

static void LogPostLocalBarrier(u64 request, const SewerBridge::TerminalState& facts, SewerBridge::LocalEdge role) {
    using namespace SewerBridge;
    const auto& emission = facts.Barrier(role);
    const auto& image = role == LocalEdge::DisplayDiscard ? facts.display : facts.ui;
    const auto shape = BarrierShape(role, emission, image);
    const auto state = emission.state.load(std::memory_order_acquire);
    if (state != EdgeState::Issued) {
        fmt::print("[sewer-motion] event=postgraph-local-barrier request={} role={} shape={} state={}\n",
                   request, unsigned(role), unsigned(shape), unsigned(state));
        return;
    }
    const auto& b = emission.barrier;
    fmt::print("[sewer-motion] event=postgraph-local-barrier request={} role={} shape={} state={} "
               "cmd={:x} image={:x} allocation={:x} memory={:x} offset={} bytes={} "
               "old={} new={} src_stage={:x} dst_stage={:x} src_access={:x} dst_access={:x} "
               "src_family={} dst_family={} aspect={} mip={} levels={} layer={} layers={}\n",
               request, unsigned(role), unsigned(shape), unsigned(state),
               std::bit_cast<u64>(emission.command), std::bit_cast<u64>(b.image), reinterpret_cast<u64>(image.allocation),
               std::bit_cast<u64>(image.memory), image.offset, image.bytes, u32(b.oldLayout), u32(b.newLayout),
               u64(VkPipelineStageFlags2(b.srcStageMask)), u64(VkPipelineStageFlags2(b.dstStageMask)),
               u64(VkAccessFlags2(b.srcAccessMask)), u64(VkAccessFlags2(b.dstAccessMask)),
               b.srcQueueFamilyIndex, b.dstQueueFamilyIndex, u32(VkImageAspectFlags(b.subresourceRange.aspectMask)),
               b.subresourceRange.baseMipLevel, b.subresourceRange.levelCount,
               b.subresourceRange.baseArrayLayer, b.subresourceRange.layerCount);
}

static bool SewerRetirePost(Scheduler& scheduler, SewerBridge::Trace& trace, u64 fence_tick) {
    using namespace BottleAncestry;
    namespace Geometry = VideoCore::PostGeometry;
    auto& post = *trace.post;
    auto& graph = post.packet.trace;
    const auto scope = graph.Registration();
    // Exact submitted positions may be available even when there are native or resource gaps.
    Event merge{.output = post.merge, .order = 1, .kind = Kind::Merge, .issued = Proof::Known,
                .pipeline = Proof::Known, .boundary = Proof::Known};
    merge.scope = scope.key;
    merge.actual = {.queue = scope.key.queue, .timeline = scope.key.timeline, .tick = trace.merge.tick,
                    .command = post.merge_command};
    if (post.order) SewerPostOrderReceipt(scheduler, post.order.get(), post.order->merge, merge.actual);
    if (post.order && post.order->proxy_alpha) {
        using namespace SewerBridge;
        const auto& alpha = *post.order->proxy_alpha;
        const auto& binding = alpha.source.binding;
        const auto read = alpha.source.Emission(alpha.key, binding.image, binding.view);
        const bool same_read = read && read->order.queue == scope.key.queue &&
            read->order.scheduler == reinterpret_cast<u64>(&scheduler) &&
            read->order.timeline == scope.key.timeline && read->order.queued_tick <= trace.merge.tick;
        fmt::print("[sewer-motion] event=postgraph-alpha-source request={} frame={} checkpoint={} "
                   "image={:x} view={:x} allocation={:x} native_alloc={:x} incarnation={} "
                   "read_emitted={} read_cmd={:x} queued_tick={} cookie={:x} note={} "
                   "before_resident={} after_resident={} coherence_same={} native_requested_same={} "
                   "dlss_color={}:{} upstream_vendor=unknown earlier_submitted=unknown\n",
                   scope.key.request, scope.key.frame, scope.key.checkpoint, std::bit_cast<u64>(binding.image),
                   std::bit_cast<u64>(binding.view), reinterpret_cast<u64>(binding.proxy.allocation),
                   reinterpret_cast<u64>(binding.native.allocation), binding.incarnation, same_read,
                   same_read ? std::bit_cast<u64>(read->command) : 0, same_read ? read->order.queued_tick : 0,
                   same_read ? read->order.cookie : 0, same_read && read->encoder_note,
                   alpha.before_merge.resident, alpha.after_coherence_drop.resident,
                   alpha.after_coherence_drop.coherence_same, alpha.after_coherence_drop.native_serial_same,
                   unsigned(alpha.vendor_color_read_only), unsigned(alpha.vendor_output_disjoint));
        const auto& stripes = alpha.strips;
        const bool staged = IssuedProxyStripShape(alpha);
        IssueOrder strip_order{.queue = scope.key.queue, .timeline = scope.key.timeline,
            .tick = stripes.queued_tick, .command = staged ? std::bit_cast<u64>(stripes.command) : 0};
        const auto strip_fenced = SewerPostOrderReceipt(scheduler, post.order.get(), alpha.edge_order, strip_order);
        if (staged) {
            fmt::print("[sewer-motion] event=postgraph-alpha-strips request={} frame={} checkpoint={} "
                       "cmd={:x} tick={} cookie={:x} note={} version={} layout={}->{} "
                       "rowsrc={},{} rowdst={},{} rowsize={}x{} colsrc={},{} coldst={},{} colsize={}x{} "
                       "src_stage={:x} dst_stage={:x} src_access={:x} dst_access={:x} "
                       "prior_version=unknown submitted={} retired={}\n",
                       scope.key.request, scope.key.frame, scope.key.checkpoint, std::bit_cast<u64>(stripes.command),
                       stripes.queued_tick, stripes.cookie, stripes.encoder_note, stripes.issued_version,
                       u32(stripes.src_layout), u32(stripes.dst_layout), stripes.row.srcOffset.x, stripes.row.srcOffset.y,
                       stripes.row.dstOffset.x, stripes.row.dstOffset.y, stripes.row.extent.width, stripes.row.extent.height,
                       stripes.column.srcOffset.x, stripes.column.srcOffset.y, stripes.column.dstOffset.x,
                       stripes.column.dstOffset.y, stripes.column.extent.width, stripes.column.extent.height,
                       u64(VkPipelineStageFlags2(stripes.after.srcStageMask)), u64(VkPipelineStageFlags2(stripes.after.dstStageMask)),
                       u64(VkAccessFlags2(stripes.after.srcAccessMask)), u64(VkAccessFlags2(stripes.after.dstAccessMask)),
                       unsigned(strip_order.submitted), strip_fenced);
        } else {
            fmt::print("[sewer-motion] event=postgraph-alpha-strips request={} frame={} checkpoint={} "
                       "expected={} issued={} repeated={} shape=unknown\n",
                       scope.key.request, scope.key.frame, scope.key.checkpoint, alpha.clamp_expected,
                       stripes.issued.load(std::memory_order_acquire),
                       stripes.repeated.load(std::memory_order_acquire));
        }
        for (u32 i = 0; i < trace.regions.count; ++i) {
            const auto& point = trace.regions.points[i];
            const auto result = staged && alpha.before_merge.resident && alpha.after_coherence_drop.resident
                ? DirectMergeAlphaFootprint(alpha, trace.merge.alpha, point.centre) : AlphaFootprint{};
            fmt::print("[sewer-motion] event=postgraph-alpha-footprint request={} frame={} checkpoint={} "
                       "role={} mode={} center={},{} proxy_bounds={},{},{},{} outside={} downstream=unknown\n",
                       scope.key.request, scope.key.frame, scope.key.checkpoint, unsigned(point.role), trace.merge.alpha,
                       point.centre.x, point.centre.y, result.first.x, result.first.y, result.last.x, result.last.y,
                       unsigned(result.outside));
        }
    }
    for (u32 i = 0; i < scope.count; ++i) merge.written[i] = Proof::Known;
    graph.Record(merge);
    for (u32 i = 0; i < post.count; ++i) {
        const auto& draw = *post.draws[i];
        const u64 command = draw.encoded.load(std::memory_order_acquire);
        Event event{.output = PostImage(draw.destination, draw.output_format, draw.destination.write),
            .order = i + 2, .kind = Kind::Raster, .issued = command ? Proof::Known : Proof::Unknown,
            .pipeline = draw.original ? Proof::Known : Proof::Unknown,
            .boundary = draw.camera && draw.geometry_key.scene == scope.key.scene &&
                        draw.geometry_key.frame == scope.key.frame ? Proof::Known : Proof::Unknown,
            .prior = draw.blends ? Prior::Blend : Prior::Unknown};
        event.scope = scope.key;
        event.actual = {.queue = scope.key.queue, .timeline = scope.key.timeline, .tick = draw.tick, .command = command};
        SewerPostOrderReceipt(scheduler, post.order.get(), draw.native_order, event.actual);
        if (command && draw.original && draw.scissor_count == 1 && !draw.clear &&
            !draw.storage_or_attachment_scope_unknown && draw.destination.res.image) {
            const auto& rect = draw.scissor;
            for (u32 point = 0; point < scope.count; ++point) {
                const auto& roi = scope.probes[point];
                if (s64(rect.offset.x) >= s64(roi.x) + roi.width ||
                    s64(rect.offset.y) >= s64(roi.y) + roi.height ||
                    s64(rect.offset.x) + rect.extent.width <= roi.x ||
                    s64(rect.offset.y) + rect.extent.height <= roi.y) event.untouched[point] = Proof::Known;
            }
        }
        std::array<BottleMotion203::Reader, MaxInputs> readers{};
        for (u32 n = 0; n < draw.slots.count; ++n) {
            const auto& slot = draw.slots.images[n];
            const auto& raw = draw.slot_images[n];
            const auto image = PostImage(raw, raw.format, raw.write);
            // The exact owner snapshot is retained even if its producer view/recipe does not join.
            readers[n] = {.image = image, .bind_generation = slot.bind_generation, .set = slot.set,
                .binding = slot.binding, .element = slot.element, .layout = slot.layout, .sampler = slot.sampler,
                .handle = slot.handle, .stage = slot.stage,
                .owner = Proof::Unknown}; // Pre-rebase observation has no immutable final set receipt yet.
            fmt::print("[sewer-motion] event=postgraph-bind request={} ordinal={} stage={} set={} binding={} "
                       "element={} layout={} image={:x} view={:x} format={} uid={} allocation={:x} write_intent={}\n",
                       scope.key.request, event.order, unsigned(slot.stage), slot.set, slot.binding, slot.element,
                       u32(slot.layout), std::bit_cast<u64>(raw.res.image), std::bit_cast<u64>(slot.view),
                       u32(raw.format), raw.res.uid, reinterpret_cast<u64>(raw.allocation), raw.write);
        }
        BottleMotion203::RecordEffective(graph, event,
            {.shader = u32(draw.ps), .permutation = draw.ps_permutation, .pipeline = draw.pipeline,
             .resolved = draw.original && command ? Proof::Known : Proof::Unknown},
             draw.slots, std::span{readers}.first(draw.slots.count));
        u32 geometry_done = 0;
        if (draw.geometry) {
            for (u32 i = 0; i < draw.bytes.size(); ++i) {
                const auto& row = draw.bytes[i];
                const auto completed = row.ticket && row.state == Geometry::State::Complete ?
                    draw.geometry->Read(row.ticket, row.binding) : Geometry::Result{row.state};
                std::array<char, 2 * Geometry::VertexBytes> bytes{};
                static constexpr char Hex[] = "0123456789abcdef";
                for (u32 n = 0; n < completed.bytes.size(); ++n) {
                    const u8 value = completed.bytes[n];
                    bytes[2 * n] = Hex[value >> 4];
                    bytes[2 * n + 1] = Hex[value & 15];
                }
                geometry_done += completed.state == Geometry::State::Complete;
                fmt::print("[sewer-motion] event=postgraph-geometry request={} ordinal={} slot={} native_slot={} "
                           "state={} route={} reservation={} buffer={:x} offset={} index_type={} "
                           "member={} member_bytes={} adjust={} desc_buffer={:x} desc_range={} desc_offset={} "
                           "guest={:x} allocation={:x} cache_generation={} bytes={}\n",
                           scope.key.request, event.order, i, row.native_slot,
                           unsigned(completed.state), unsigned(completed.route),
                           row.ticket.serial, row.binding.backing.handle, row.binding.offset,
                           u32(draw.index_type), row.member, row.member_bytes, row.adjust,
                           std::bit_cast<u64>(row.descriptor.buffer), row.descriptor.range, row.descriptor.offset,
                           row.binding.guest, row.binding.backing.allocation, row.binding.backing.cache_generation,
                           std::string_view(bytes.data(), completed.bytes.size() * 2));
            }
            for (u32 i = 0; i < std::min<std::size_t>(draw.attribute_count, draw.attributes.size()); ++i) {
                const auto& a = draw.attributes[i];
                fmt::print("[sewer-motion] event=postgraph-vertex request={} ordinal={} location={} binding={} "
                           "format={} attribute_offset={}\n", scope.key.request, event.order, a.location,
                           a.binding, u32(a.format), a.offset);
            }
            for (u32 i = 0; i < std::min<std::size_t>(draw.binding_count, draw.bindings.size()); ++i) {
                const auto& b = draw.bindings[i];
                fmt::print("[sewer-motion] event=postgraph-vertex-binding request={} ordinal={} binding={} "
                           "stride={} rate={} divisor={}\n", scope.key.request, event.order,
                           b.binding, b.stride, u32(b.inputRate), b.divisor);
            }
        }
        for (u32 n = 0; n < draw.sampler_count; ++n) {
            const auto& s = draw.samplers[n];
            fmt::print("[sewer-motion] event=postgraph-sampler request={} ordinal={} binding={} sampler={:x} "
                       "sharp={:08x},{:08x},{:08x},{:08x} lod_bias={:.9g}\n", scope.key.request, event.order,
                       s.binding, std::bit_cast<u64>(s.handle), s.sharp[0], s.sharp[1], s.sharp[2], s.sharp[3], s.lod_bias);
        }
        fmt::print("[sewer-motion] event=postgraph-draw request={} ordinal={} vs={:x} vp={:x} ps={:x} "
                   "original={} raster_scope={} camera={} geometry={} streams={} descriptors={} storage_unknown={}\n",
                   scope.key.request, event.order, draw.vs, draw.vs_permutation, draw.ps,
                   draw.original, draw.full_write, draw.camera, geometry_done, draw.binding_count,
                   draw.snapshots_complete, draw.storage_or_attachment_scope_unknown);
        fmt::print("[sewer-motion] event=postgraph-raster request={} ordinal={} size={}x{} scissors={} "
                   "scissor={},{},{},{} viewports={} viewport={:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g} "
                   "indices={} count={} instances={} first_vertex={} first_instance={} primitive={} restart={} "
                   "depth={} stencil={} blend={} logic={} mask={} clear={} omitted_samplers={} "
                   "attachment_layers={} attachments={} load_request={} store=unknown resolve=unknown\n",
                   scope.key.request, event.order, draw.width, draw.height, draw.scissor_count,
                   draw.scissor.offset.x, draw.scissor.offset.y, draw.scissor.extent.width, draw.scissor.extent.height,
                   draw.viewport_count, draw.viewport.x, draw.viewport.y, draw.viewport.width, draw.viewport.height,
                   draw.viewport.minDepth, draw.viewport.maxDepth, draw.indexed, draw.count, draw.instances,
                   draw.first_vertex, draw.first_instance, draw.topology, draw.primitive_restart, draw.depth_test,
                   draw.stencil_test, draw.blends, draw.logic_op, draw.write_mask, draw.clear, draw.omitted_samplers,
                   draw.attachment.layers, draw.attachment.color_count,
                   draw.attachment.clear ? "clear" : "load");
    }
    const auto ui = post.ui_encoded.load(std::memory_order_acquire);
    Event copy{.output = post.ui_version, .order = post.count + 2u, .kind = Kind::Ui,
               .issued = ui ? Proof::Known : Proof::Unknown};
    copy.scope = scope.key;
    copy.actual = {.queue = scope.key.queue, .timeline = scope.key.timeline, .tick = post.ui_tick, .command = ui};
    const bool ui_fenced = SewerPostOrderReceipt(scheduler, post.order.get(), post.ui_order, copy.actual);
    // An observed 1:1 transfer has an exact source range but no VkImageView. Preserve its
    // transfer identity separately from any sampled or producing view.
    const auto& ui_source = post.ui_source;
    const auto& terminal = post.terminal;
    const bool same_closure = terminal.Barrier(SewerBridge::LocalEdge::UiDiscard).state.load(std::memory_order_acquire)
            == SewerBridge::EdgeState::Issued &&
        terminal.Barrier(SewerBridge::LocalEdge::UiAttachment).state.load(std::memory_order_acquire)
            == SewerBridge::EdgeState::Issued &&
        std::bit_cast<u64>(terminal.Barrier(SewerBridge::LocalEdge::UiDiscard).command) == ui &&
        std::bit_cast<u64>(terminal.Barrier(SewerBridge::LocalEdge::UiAttachment).command) == ui;
    const auto local_ui = same_closure
        ? All(BarrierShape(SewerBridge::LocalEdge::UiDiscard, terminal.Barrier(SewerBridge::LocalEdge::UiDiscard), terminal.ui),
              BarrierShape(SewerBridge::LocalEdge::UiAttachment, terminal.Barrier(SewerBridge::LocalEdge::UiAttachment), terminal.ui))
        : Proof::Unknown;
    auto ui_output = post.ui_version;
    if (ui_fenced && local_ui == Proof::Known)
        ui_output.content = terminal.blit_write.load(std::memory_order_acquire);
    copy.output = ui_output;
    LogPostLocalBarrier(scope.key.request, terminal, SewerBridge::LocalEdge::UiDiscard);
    LogPostLocalBarrier(scope.key.request, terminal, SewerBridge::LocalEdge::UiAttachment);
    // The native source has no VkImageView in BlitImage. Its current issued writer must come from
    // the graph and certified Runtime edge, independently of the requested cache write ordinal.
    const ImageVersion source{reinterpret_cast<u64>(ui_source.allocation), BottleMotion203::Transfer(ui_source.res.image),
        ui_source.res.uid, ui_source.res.uid, 0, {0, 1, 0, 1, 1}, Format::Rgba8Unorm};
    fmt::print("[sewer-motion] event=postgraph-ui-edge request={} frame={} checkpoint={} source={:x} "
               "source_alloc={:x} source_uid={} source_requested={} source_writer=unknown ui_write={} "
               "source_runtime={} separation={} local_order={} fence={}\n",
               scope.key.request, scope.key.frame, scope.key.checkpoint, std::bit_cast<u64>(post.blit_source),
               reinterpret_cast<u64>(terminal.source.allocation), terminal.source.generation, ui_source.write,
               ui_output.content, unsigned(terminal.source_runtime),
               unsigned(PhysicalSeparation(terminal.source, terminal.ui)), unsigned(local_ui), ui_fenced);
    BottleMotion203::RecordUi(graph, copy, {
        .source = source, .source_image = post.blit_source, .destination_image = post.ui_image,
        .source_layout = post.blit_source_layout, .destination_layout = vk::ImageLayout::eTransferDstOptimal,
        .source_extent = post.blit_source_extent, .destination_extent = post.ui_extent, .region = post.blit,
        .filter = vk::Filter::eLinear, .source_owner = terminal.source_runtime,
        .destination_owner = ui_output.Valid() ? Proof::Known : Proof::Unknown,
        .ordinary_scope = post.ui_ordinary ? Proof::Known : Proof::Unknown,
        .after_writers = post.ui_after_writer ? Proof::Unknown : Proof::Known,
    });
    if (post.omitted) {
        fmt::print("[sewer-motion] event=postgraph-draw-cap request={} omitted={}\n", scope.key.request, post.omitted);
    }
    return post.packet.Retire(scope.key, ui_output, ui_fenced ? Proof::Known : Proof::Unknown,
                              scope.key.timeline, fence_tick) && !post.omitted;
}

// Render and app-present owners finish independently. Never promote an encoded handle
// to submitted order or let a raw contender retire a different checkpoint.
static void SewerCompletePost(SewerBridge::Trace& trace) {
    auto& post = *trace.post;
    auto result = post.TakeCompletion();
    if (!result) return;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    if (result->frame && result->display) {
        fmt::print("[sewer-motion] event=postgraph-present-resource request={} frame={} ready={} lineage={}\n",
            trace.merge.key.request, trace.merge.key.frame,
            SewerPresent::JoinsResources(*result->frame, *result->display), result->display->lineage);
    }
#endif
    const bool fenced = !result->refusal && result->frame && result->display &&
        SewerPresent::PublishFinal(std::move(*result->frame), *result->display);
    if (post.order) post.order->Disarm();
    trace.checkpoint->FinishPresentation(fenced,
        fenced ? nullptr : result->refusal ? result->refusal : "shared-post-present-resource-unproved");
}

void TemporalUpscaler::SewerPostEndDisplay(const SewerBridge::Draw& draw) {
    using namespace SewerBridge;
    auto& post = *draw.trace->post;
    if (post.display_retirement_scheduled) return;
    post.display_retirement_scheduled = true;
    auto& terminal = post.terminal;
    if (terminal.runtime_window) {
        // The Runtime session belongs to this original producer. Copy the emitted rows here.
        PostImageBarriers::Report report{};
        const auto& key = draw.trace->merge.key;
        const auto& scope = post.packet.trace.Registration().key;
        if (runtime.ReadPostImageBarriers(terminal.runtime_window, report) &&
            report.window == terminal.runtime_window && report.count <= report.rows.size() &&
            report.key == PostImageBarriers::Key{key.request, u64(key.checkpoint), key.frame}) {
            const PostImageBarriers::Row* selected = nullptr;
            u32 matches = 0;
            for (const auto& row : std::span{report.rows}.first(report.count)) {
                if (!NativeUiSourceRow(row, terminal.source, scope.queue, reinterpret_cast<u64>(&scheduler),
                                       draw.trace->merge.tick, post.ui_tick)) continue;
                ++matches;
                selected = &row;
            }
            if (selected && matches == 1 && !report.pending && !report.overflow && !report.mismatch) {
                terminal.runtime_emission = Graph::Proof::Known;
            } else if (report.overflow || report.mismatch) {
                terminal.runtime_emission = Graph::Proof::Failed;
            }
            fmt::print("[sewer-motion] event=postgraph-runtime-ui-source request={} frame={} checkpoint={} "
                       "window={} rows={} pending={} overflow={} mismatch={} matches={} emission={} "
                       "cookie={:x} command={:x} queued_tick={} note={} issued_writer=unknown dependency=unknown\n",
                       key.request, key.frame, key.checkpoint, report.window, report.count, report.pending,
                       report.overflow, report.mismatch, matches, unsigned(terminal.runtime_emission),
                       selected ? selected->cookie : 0, selected ? selected->command : 0,
                       selected ? selected->queued_tick : 0, selected && selected->encoder_note);
        }
        runtime.DisarmPostImageBarriers(std::exchange(terminal.runtime_window, 0));
    }
    scheduler.DeferOperation([active = draw.trace, token = draw.native_order, owner = &scheduler] {
        auto& post = *active->post;
        const auto& scope = post.packet.trace.Registration();
        const u64 command = post.display_encoded.load(std::memory_order_acquire);
        Graph::IssueOrder actual{.queue = scope.key.queue, .timeline = scope.key.timeline,
                                 .tick = post.display_tick.load(std::memory_order_relaxed), .command = command};
        u64 completed_tick = 0;
        const bool fenced = SewerPostOrderReceipt(*owner, post.order.get(), token, actual, &completed_tick);
        const auto& facts = post.terminal;
        fmt::print("[sewer-motion] event=postgraph-display-edge request={} frame={} checkpoint={} "
                   "source_view={:x} source_format={} output_view={:x} output_format={} output_alloc={:x} "
                   "generation={} write={} slot={} footprint={} native_order={} local_order={} committed={} "
                   "app_dependency={} separation={} ui_issued={}/{} load_clear={} layers={} attachments={}\n",
                   scope.key.request, scope.key.frame, scope.key.checkpoint, std::bit_cast<u64>(facts.draw.source_view),
                   u32(facts.draw.source_format), std::bit_cast<u64>(facts.draw.color.view), u32(facts.display.format),
                   reinterpret_cast<u64>(facts.display.allocation), facts.issued_candidate.generation,
                   facts.issued_candidate.write, unsigned(facts.draw.requested_slot), unsigned(facts.draw.footprint),
                   fenced, unsigned(facts.separate_local_order), unsigned(facts.descriptor_committed),
                   unsigned(facts.app_dependency), unsigned(PhysicalSeparation(facts.ui, facts.display)),
                   active->ui_encoded.load(std::memory_order_acquire), active->ui_expected,
                   facts.draw.color.clear, facts.draw.color.layers, facts.draw.color.color_count);
        LogPostLocalBarrier(scope.key.request, facts, LocalEdge::DisplayDiscard);
        LogPostLocalBarrier(scope.key.request, facts, LocalEdge::UiSample);
        for (u32 i = 0; i < facts.draw.slots.count; ++i) {
            const auto& slot = facts.draw.slots.images[i];
            const auto& map = facts.draw.source_mapping;
            fmt::print("[sewer-motion] event=postgraph-display-bind request={} stage={} set={} slot={} element={} "
                       "type={} layout={} view={:x} descriptor={:x} sampler={:x} "
                       "pipeline={:x} pipeline_layout={:x} shader={:x} permutation={:x} swizzle={},{},{},{}\n",
                       scope.key.request, unsigned(slot.stage), slot.set, slot.binding, slot.element, u32(slot.type),
                       u32(slot.layout), std::bit_cast<u64>(slot.view), std::bit_cast<u64>(slot.handle),
                       std::bit_cast<u64>(slot.sampler), std::bit_cast<u64>(facts.draw.pipeline),
                       std::bit_cast<u64>(facts.draw.layout), facts.draw.shader, facts.draw.permutation,
                       u32(map.r), u32(map.g), u32(map.b), u32(map.a));
        }
        {
            std::lock_guard lock(post.retirement_mutex);
            const auto& issued = facts.issued_candidate;
            if (fenced && actual.tick == issued.display.draw_tick && issued.attachment == facts.draw.color.view &&
                SewerPresent::SameMerge(issued.merge, active->merge)) {
                post.render = SewerPresent::RenderRetirement{
                    .merge = issued.merge, .display = issued.display, .display_attachment = issued.attachment,
                    .display_generation = issued.generation, .display_write = issued.write,
                    .display_allocation = issued.allocation,
                    .command = std::bit_cast<vk::CommandBuffer>(actual.command),
                    .submission = actual.submission, .incarnation = actual.incarnation,
                    .ordinal = actual.ordinal, .segment = actual.segment, .submitted_tick = actual.tick,
                    .completed_tick = completed_tick, .submitted = true, .fenced = true,
                    .regions = active->regions,
                };
            }
            post.renderer_checked = true;
        }
        SewerCompletePost(*active);
    }, "shared post display order");
}
#endif

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
static void FinishBottlePrepared(SewerBridge::BottleDisplay& pending) {
    const auto completion = pending.TakeCompletion();
    if (!completion) return;
    const auto& frame = completion->frame;
    const auto& position = completion->position;
    const bool present_joined = frame && completion->fenced && frame->ResourcesJoined() &&
        frame->resources.display_order.where.StreamKey() == position.StreamKey() &&
        frame->resources.display_order.where.segment == position.segment &&
        frame->resources.display_order.where.buffer == position.buffer;
    const auto& scene = pending.scene;
    fmt::print("[bottle-cut] event={} request={} scene={} frame={} raw_fenced={} "
               "present_serial={} renderer_submitted={} renderer_fenced={} resources={} "
               "app_refusal={} first_lineage_refusal={}\n",
               pending.raw ? "raw-search-caller-retired" : "prepared-caller-retired",
               scene.key.request, scene.key.scene, scene.draw_frame, bool(frame),
               frame ? frame->attempt.serial : 0, completion->submitted, completion->fenced, present_joined,
               completion->refusal ? completion->refusal : "none",
               pending.raw ? "raw-search-only" : "starting-proxy-writer-unproved");
    pending.order->Disarm();
}

static const std::optional<BottleRawSearch177::Options>& BottleRawOptions() {
    static const auto options = [] {
        const auto* text = std::getenv("BB_BOTTLE_RAW_SEARCH");
        return text ? BottleRawSearch177::Parse(text, BottleCaustic::CutSource::Run()) : std::nullopt;
    }();
    return options;
}

BottleRawApply180::Selection BottleRawApply180::Selected(u32 request) {
    const auto& options = BottleRawOptions();
    if (!options || options->request != request) return {};
    return {request, options->mode == BottleCutPresent::Mode::Cut ? Mode::Cut : Mode::AllOff};
}

bool TemporalUpscaler::BottleRawSearchRequested() const {
    return !bottle_raw_closed && BottleRawOptions().has_value() && !BottleMotion::Run();
}

void TemporalUpscaler::BottleCloseRawSearch() {
    if (bottle_raw_closed || !bottle_raw_end) return;
    bottle_raw_closed = true;
    BottleCutPresent::CloseWindow(BottleCaustic::CutSource::Run(), bottle_raw_end);
}

static void ReportBottleApplySelection(u32 request, u32 frame, const BottleColdSource177::Closed* closed,
                                       const BottleRawApply180::Readiness& observed, const char* result) {
    fmt::print("[bottle-raw-apply] event=selection request={} scene={} frame={} outcome={} epoch={} "
               "first_frame={} deadline={} expected={} seen={} recorded={} opportunity={} phase_tick={} "
               "topology_ordinal={}\n",
               request, closed ? closed->source.key.scene : 0, frame, result, closed ? closed->first_epoch : 0,
               observed.first_frame, observed.deadline, observed.expected, observed.seen, observed.recorded,
               observed.opportunity, observed.phase_tick, observed.topology_ordinal);
}

void TemporalUpscaler::BottleObserveRawSearch(const BottleColdSource177::Closed* closed) {
    using namespace BottleCutPresent;
    if (!BottleRawSearchRequested()) return;
    const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
    if (!frame || frame == bottle_raw_boundary_frame) return;
    if (bottle_raw_end && !bottle_raw_remaining) {
        BottleCloseRawSearch();
        return;
    }
    bottle_raw_boundary_frame = frame;
    if (bottle_raw_end) --bottle_raw_remaining;

    const auto& options = *BottleRawOptions();
    constexpr std::array search{BottleMotion::Receiver, BottleMotion::Opaque};
    const auto candidate = closed ? BottleRawSearch177::Project(*closed, options, search) : std::nullopt;
    const bool source_valid = candidate && candidate->scene.draw_frame == frame &&
        candidate->native_timeline == scheduler.GetWorkSemaphore()->Handle();
    const bool display_scope = source_valid && ui_phase && !SewerBridgeOpen();
    using BottleRawApply180::Decision;
    BottleRawApply180::Readiness application{};
    const bool selecting = !bottle_raw_end && options.mode == Mode::Cut;
    if (selecting) {
        application = BottleRawApply180::CurrentBudget().Probe(frame, source_valid ? closed : nullptr);
        const char* terminal = nullptr;
        switch (application.decision) {
        case Decision::NoWork: terminal = "no-work"; break;
        case Decision::ScopeUnknown: terminal = "scope-unknown"; break;
        case Decision::QueueUnjoined: terminal = "queue-unjoined"; break;
        case Decision::Overflow: terminal = "active-cap"; break;
        case Decision::Ready:
            if (!display_scope && frame >= application.deadline) terminal = "display-scope-unavailable";
            break;
        case Decision::Awaiting: break;
        }
        if (terminal) {
            ReportBottleApplySelection(options.request, frame, source_valid ? closed : nullptr, application, terminal);
            BottleRawApply180::CurrentBudget().StopSeeking();
            bottle_raw_closed = true;
            return;
        }
    }
    if (!display_scope) {
        if (!std::exchange(bottle_raw_source_refused, true)) {
            fmt::print("[bottle-cut] event=raw-search-source-refused request={} frame={} reason={}\n",
                       options.request, frame, closed && closed->raw_refusal ? closed->raw_refusal : "current-source-or-ui-scope");
        }
        return;
    }
    if (selecting && application.decision != Decision::Ready) return;
    const auto& raw = *candidate;
    const auto ordinal = raw.scene.key.scene;
    if (!bottle_raw_end) {
        if ((options.mode == Mode::Cut && raw.scene.state != State::On) ||
            ordinal > std::numeric_limits<u64>::max() - options.span ||
            !BeginRawSearchWindow(options.request, options.mode, ordinal)) return;
        if (selecting) ReportBottleApplySelection(options.request, frame, closed, application, "recorded");
        bottle_raw_end = ordinal + options.span - 1;
        bottle_raw_remaining = options.span - 1;
        BottleRawApply180::CurrentBudget().Open(BottleRawApply180::Selected(options.request),
                                               closed->frame, raw.scene.key, bottle_raw_end);
    }
    if (ordinal > bottle_raw_end) {
        BottleCloseRawSearch();
        return;
    }
    if (EnrolRawSearch(raw)) {
        fmt::print("[bottle-raw-apply] event=coverage request={} scene={} frame={} expected={} epoch={}\n",
                   options.request, ordinal, frame, closed->source.last_sequence, raw.scene.last_epoch);
        if (BottleBeginPrepared(raw.scene, options.mode, {}, &raw) && !bottle_raw_remaining)
            bottle_prepared->raw_close_after_offer = bottle_raw_end;
    }
}

bool TemporalUpscaler::BottleBeginPrepared(const BottleCutPresent::Scene& scene, BottleCutPresent::Mode mode,
                                            const BottleCutPresent::Regions& regions) {
    return BottleBeginPrepared(scene, mode, regions, nullptr);
}

bool TemporalUpscaler::BottleBeginPrepared(const BottleCutPresent::Scene& scene, BottleCutPresent::Mode mode,
                                            const BottleCutPresent::Regions& regions,
                                            const BottleCutPresent::RawSearch* raw) {
    using namespace NativeWriteSuffix;
    const auto& options = BottleRawOptions();
    const bool coordinates = raw ? options && options->request == scene.key.request && options->mode == mode &&
        raw->scene == scene && raw->Valid() && !regions.count : regions.Valid(scene.state, mode);
    if (!scene.Known() || scene.key.request != BottleCaustic::CutSource::Run() ||
        !coordinates || BottleMotion::Run() || SewerBridgeOpen() ||
        !scene.draw_frame || scene.draw_frame != BbStats::frame_number.load(std::memory_order_relaxed) ||
        scene.key.load != BbEngine::Loading::Generation() || scene.key.target_generation != scene_targets.Generation() ||
        BbEngine::Loading::ScreenUp() || (bottle_prepared && bottle_prepared->scene.draw_frame == scene.draw_frame)) return false;
    const auto key = BottleCutPresent::ResourceKey(scene);
    auto order = std::make_shared<SewerBridge::PostOrder>();
    order->owner = &scheduler;
    order->key = key;
    order->capture = scheduler.ArmPostNativeOrder(key);
    auto selected = std::make_shared<SewerBridge::BottleDisplay>();
    selected->scene = scene;
    selected->regions = regions;
    if (raw) selected->raw = *raw;
    selected->order = std::move(order);
    bottle_prepared = std::move(selected);
    return true;
}

bool TemporalUpscaler::BottlePreparedPending() const {
    return bottle_prepared && bottle_prepared->address && !SewerBridgeOpen() &&
           bottle_prepared->scene.draw_frame == BbStats::frame_number.load(std::memory_order_relaxed);
}

std::shared_ptr<SewerBridge::BottleDisplay> TemporalUpscaler::BottlePlanPrepared(
    const SewerBridge::DrawFacts& draw, const BottleDisplay182::Draw* actual,
    std::shared_ptr<SewerBridge::BottleDisplay>& observed) {
    using namespace SewerBridge;
    if (!BottlePreparedPending()) return {};
    const auto selected = bottle_prepared;
    const auto* guest = draw.color_id ? texture_cache.TryGetImage(draw.color_id, 0) : nullptr;
    if (!guest || guest->info.guest_address != selected->address) return {};
    std::lock_guard owner(display_mutex);
    const auto found = displays.find(selected->address);
    const auto& key = selected->scene.key;
    const auto fail = [&](const char* why) -> std::shared_ptr<BottleDisplay> {
        selected->Cancel();
        fmt::print("[bottle-cut] event=prepared-caller-refused request={} scene={} frame={} why={}\n",
                   key.request, key.scene, selected->scene.draw_frame, why);
        return {};
    };
    const bool report_scope = selected->raw && !std::exchange(selected->draw_scope_reported, true);
    const bool found_display = found != displays.end();
    const auto* actual_epoch = found_display ? found->second.bottle_epoch.get() : nullptr;
    const bool epoch_matches = actual_epoch == selected.get();
    const bool display_valid = found_display && found->second.valid;
    const auto load = BbEngine::Loading::Generation();
    const auto targets = scene_targets.Generation();
    const bool basic_refusal = !found_display || !epoch_matches || !display_valid ||
        selected->write || !selected->attachment || selected->attachment != draw.output ||
        !draw.original || !draw.full_write || draw.scene != key.object_frame + 1 ||
        key.load != load || key.target_generation != targets ||
        draw.attachment.extent != BottleCutPresent::Extent || draw.layout != vk::ImageLayout::eGeneral ||
        draw.attachment.layers != 1 || draw.attachment.color_count != 1 || draw.attachment.clear;
    const bool target_valid = selected->target.Valid();
    const bool inspect_target = found_display && (report_scope || (!basic_refusal && target_valid));
    const auto current_target = inspect_target ? PostPhysical(found->second.image, selected->target.generation)
                                               : PhysicalImage{};
    const bool target_matches = inspect_target && selected->target == current_target;
    const bool inspect_ui = report_scope || (!basic_refusal && target_valid && target_matches);
    const auto current_ui = inspect_ui ? PostPhysical(ui_image, bottle_ui_generation) : PhysicalImage{};
    const bool ui_matches = inspect_ui && selected->ui == current_ui;
    const auto separation = PhysicalSeparation(selected->target, selected->ui);
    const bool attachment_failed = basic_refusal || !target_valid || !target_matches || !ui_matches ||
        separation != Graph::Proof::Known;
    if (report_scope) {
        const auto attachment_mask = BottleRejections({
            !found_display, !epoch_matches, !display_valid, selected->write != 0, !selected->attachment,
            selected->attachment != draw.output, !draw.original, !draw.full_write,
            draw.scene != key.object_frame + 1, key.load != load, key.target_generation != targets,
            draw.attachment.extent != BottleCutPresent::Extent, draw.layout != vk::ImageLayout::eGeneral,
            draw.attachment.layers != 1, draw.attachment.color_count != 1, draw.attachment.clear,
            !target_valid, !target_matches, !ui_matches, separation != Graph::Proof::Known});
        const auto& slot = draw.display_slots.images.front();
        const auto& r = draw.scissor;
        const auto& shape = draw.bottle_scope;
        const auto& v = shape.viewport;
        const bool ui_slot = slot.view &&
            std::ranges::any_of(ui_views, [&](const auto& view) { return *view.view == slot.view; });
        const auto physical = [](const PhysicalImage& image) {
            return fmt::format("{:x}/{:x}/{:x}/{:x}/{}/{}/{}/{}/{}x{}x{}",
                std::bit_cast<u64>(image.image), reinterpret_cast<u64>(image.allocator),
                reinterpret_cast<u64>(image.allocation), std::bit_cast<u64>(image.memory),
                image.offset, image.bytes, image.generation, u32(image.format),
                image.extent.width, image.extent.height, image.extent.depth);
        };
        fmt::print("[bottle-cut] event=prepared-draw-scope request={} scene={} frame={} epoch={} "
                   "address={:x} color={} tick={} timeline={:x} "
                   "attachment_mask={:x} original_mask={:x} full_mask={:x} "
                   "display_found={} display_epoch={} display_valid={} writer={} actual_epoch={}/{} "
                   "selected_view={:x} output={:x} "
                   "load={}/{} targets={}/{} object={}/{} rt={} primary={} "
                   "attachment={}x{}/{}/{}/{} layout={} scissor={}/{}/{}x{}/{} "
                   "viewport={}/{}/{}/{}/{}/{}/{} elements={} instances={} write_mask={:x} logic_op={} "
                   "target_inspected={} ui_inspected={} target_valid={} physical_separation={} "
                   "target={}/actual:{} ui={}/actual:{} pipeline={:x} pipeline_layout={:x} ps={:x} permutation={:x} "
                   "slot_count={} slot_omitted={} slot_view={:x} slot_exact={} slot_stage={} slot_set={} "
                   "slot_binding={} slot_element={} slot_layout={} slot_type={} slot_handle={:x} slot_sampler={:x} "
                   "slot_generation={} ui_slot={} descriptor_commit=unknown coverage=unknown\n",
                   key.request, key.scene, selected->scene.draw_frame, selected->scene.last_epoch,
                   selected->address, draw.color_id.index, scheduler.CurrentTick(),
                   std::bit_cast<u64>(scheduler.GetWorkSemaphore()->Handle()),
                   attachment_mask, shape.original_mask, shape.full_mask,
                   found_display, epoch_matches, display_valid, selected->write,
                   actual_epoch ? actual_epoch->target.generation : 0, actual_epoch ? actual_epoch->write : 0,
                   std::bit_cast<u64>(selected->attachment), std::bit_cast<u64>(draw.output),
                   key.load, load, key.target_generation, targets, key.object_frame, draw.scene,
                   key.rt_frame, key.primary_pass, draw.attachment.extent.width, draw.attachment.extent.height,
                   draw.attachment.layers, draw.attachment.color_count, draw.attachment.clear, u32(draw.layout),
                   r.offset.x, r.offset.y, r.extent.width, r.extent.height, shape.scissor_count,
                   v.x, v.y, v.width, v.height, v.minDepth, v.maxDepth, shape.viewport_count, shape.index_count,
                   shape.instances, shape.color_mask, shape.logic_op, inspect_target, inspect_ui, target_valid,
                   u32(separation), physical(selected->target), physical(current_target), physical(selected->ui),
                   physical(current_ui), std::bit_cast<u64>(draw.pipeline), std::bit_cast<u64>(draw.pipeline_layout),
                   draw.ps, draw.fragment_permutation, draw.display_slots.count, draw.display_slots.omitted,
                   std::bit_cast<u64>(slot.view), slot.exact, u32(slot.stage), slot.set, slot.binding,
                   slot.element, u32(slot.layout), u32(slot.type), std::bit_cast<u64>(slot.handle),
                   std::bit_cast<u64>(slot.sampler), slot.bind_generation, ui_slot);
    }
    if (report_scope && actual) {
        const auto& lut = actual->lut;
        const auto& sampler = actual->sampler;
        const auto& clip = actual->viewport_push;
        const auto& first = draw.display_slots.images[0];
        const auto& second = draw.display_slots.images[1];
        const bool ui = draw.display_slots.count && first.exact && first.binding == 0 && first.view &&
            std::ranges::any_of(ui_views, [&](const auto& view) { return *view.view == first.view; });
        const auto distinct = [&](const PhysicalImage& target) {
            return actual->slot1_matches && target.Valid() &&
               BottleDisplay182::Disjoint(lut, target.image, reinterpret_cast<u64>(target.allocator),
                   reinterpret_cast<u64>(target.allocation), std::bit_cast<u64>(target.memory),
                   target.offset, target.bytes);
        };
        const auto stage = [](const BottleDisplay182::Module& m) {
            return fmt::format("{:x}/{:x}/{:x}/{:x}/{}/{}", std::bit_cast<u64>(m.handle), m.guest,
                               m.permutation, m.digest, m.bytes, m.route ? m.route : "unknown");
        };
        const auto& modules = actual->program.stages;
        const auto sequence = !actual->indexed && actual->elements == 3 &&
            actual->first_vertex <= std::numeric_limits<u32>::max() - 2
            ? fmt::format("{}/{}/{}", actual->first_vertex, actual->first_vertex + 1, actual->first_vertex + 2)
            : "unknown";
        fmt::print("[bottle-cut] event=prepared-original-operands request={} scene={} frame={} epoch={} "
                   "output={:x} primitive={} indexed={} elements={} instances={} first_vertex={} first_instance={} "
                   "index_buffer={:x} index_offset={} index_type={} index_bytes={} index_sequence={} "
                   "attributes={} vertex_buffers={} "
                   "restart={} cull={} front={} polygon={} samples={} depth_clip={} depth_clamp={} "
                   "scene_push={:x} viewport_push={}/{}/{}/{} vs={:x} vs_permutation={:x} ps_permutation={:x} "
                   "modules={},{},{},{} "
                   "ui_exact={} ui_view={:x} lut_view={:x} lut_layout={} lut_known={} lut_slot={} "
                   "lut_parent={:x}/{}/{} lut_memory={:x}/{:x}/{:x}/{}/{} lut_format={} "
                   "lut_shape={}/{}/{}/{}/{}/{}/{}/{} lut_incarnation=unknown lut_write_hint={} disjoint_ui={} disjoint_display={} "
                   "sampler={:x} sampler_known={} sampler_slot={} sampler_words={:x}/{:x}/{:x}/{:x} sampler_bias={} "
                   "binder_shape={} descriptor_commit=unknown footprint=unknown\n",
                   key.request, key.scene, selected->scene.draw_frame, selected->scene.last_epoch,
                   std::bit_cast<u64>(draw.output), actual->primitive, actual->indexed, actual->elements,
                   actual->instances, actual->first_vertex, actual->first_instance, std::bit_cast<u64>(actual->index),
                   actual->index_offset, u32(actual->index_type), actual->indexed ? "unavailable" : "implicit",
                   sequence, actual->attributes, actual->vertex_buffers, actual->restart,
                   actual->cull, actual->front_face,
                   actual->polygon, actual->samples, actual->depth_clip, actual->depth_clamp, actual->scene_size,
                   clip[0], clip[1], clip[2], clip[3], actual->vs, actual->vs_permutation, actual->ps_permutation,
                   stage(modules[0]), stage(modules[1]), stage(modules[2]), stage(modules[3]), ui,
                   std::bit_cast<u64>(first.view), std::bit_cast<u64>(second.view), u32(second.layout), lut.known,
                   actual->slot1_matches, std::bit_cast<u64>(lut.image), lut.uid, lut.id, lut.allocator,
                   lut.allocation, lut.memory, lut.offset, lut.bytes, u32(lut.format), lut.type, lut.width,
                   lut.levels, lut.layers, lut.base_level, lut.base_layer, lut.view_levels, lut.view_layers, lut.write_hint,
                   distinct(current_ui), distinct(current_target), std::bit_cast<u64>(sampler.handle), sampler.known,
                   actual->sampler_matches, sampler.words[0], sampler.words[1], sampler.words[2], sampler.words[3],
                   sampler.lod_bias, actual->binder_shape);
        if (attachment_failed && draw.original && draw.output && selected->attachment == draw.output && epoch_matches)
            observed = selected;
    }
    if (attachment_failed) return fail("ordinary-display-attachment");
    if (draw.display_slots.omitted || draw.display_slots.count != 1) return fail("ordinary-display-slot");
    const auto& slot = draw.display_slots.images.front();
    if (!slot.exact || slot.stage != Graph::BindStage::Fragment || slot.set != 0 || slot.element ||
        slot.layout != vk::ImageLayout::eGeneral || slot.type == vk::DescriptorType::eStorageImage ||
        std::ranges::none_of(ui_views, [&](const auto& item) { return *item.view == slot.view; }))
        return fail("ordinary-display-ui-binding");
    auto& scheduler_order = *selected->order;
    if (const auto capture = scheduler_order.capture.load(std::memory_order_acquire)) {
        selected->display_order = scheduler.ReservePostNativeOperation(
            capture, Order::PostRole::Display, PostState::DisplayOperation);
    }
    selected->requested_slot = slot;
    selected->pipeline = draw.pipeline;
    selected->pipeline_layout = draw.pipeline_layout;
    selected->shader = draw.ps;
    selected->permutation = draw.fragment_permutation;
    selected->display = {selected->address, selected->target.image, selected->target.format, BottleCutPresent::Extent,
                         scheduler.GetWorkSemaphore()->Handle(), scheduler.CurrentTick()};
    selected->write = ++bottle_display_write;
    return selected;
}

void TemporalUpscaler::BottleEndPrepared(const std::shared_ptr<SewerBridge::BottleDisplay>& selected) {
    scheduler.DeferOperation([selected, owner = &scheduler, queue = instance.GetGraphicsQueue()] {
        using namespace SewerBridge;
        Order::PostReceipt receipt{};
        const Graph::IssueOrder actual{
            .queue = std::bit_cast<u64>(queue), .timeline = std::bit_cast<u64>(selected->display.draw_timeline),
            .tick = selected->display.draw_tick, .command = selected->encoded.load(std::memory_order_acquire)};
        const bool submitted = selected->display_order && owner->ReadPostNativeOperation(selected->display_order, receipt) &&
                               MatchedPostSubmission(receipt, selected->order->key, selected->display_order, actual);
        {
            std::lock_guard lock(selected->mutex);
            selected->renderer_checked = true;
            selected->renderer_submitted = submitted;
            selected->renderer_fenced = submitted && receipt.phase == Order::PostPhase::Retired;
            if (submitted) selected->renderer_position = receipt.where;
        }
        const auto& slot = selected->requested_slot;
        fmt::print("[bottle-cut] event=prepared-renderer-display request={} scene={} frame={} "
                   "command={:x} tick={} view={:x} allocation={:x} writer={} "
                   "input={:x} slot={} layout={} set={:x} pipeline={:x} pipeline_layout={:x} "
                   "shader={:x} permutation={:x} native_submitted={} descriptor_commit=unknown coverage=unknown\n",
                   selected->scene.key.request, selected->scene.key.scene, selected->scene.draw_frame,
                   actual.command, actual.tick, std::bit_cast<u64>(selected->attachment),
                   reinterpret_cast<u64>(selected->target.allocation), selected->write, std::bit_cast<u64>(slot.view),
                   slot.binding, u32(slot.layout), std::bit_cast<u64>(slot.handle), std::bit_cast<u64>(selected->pipeline),
                   std::bit_cast<u64>(selected->pipeline_layout), selected->shader, selected->permutation, submitted);
        FinishBottlePrepared(*selected);
    }, "bottle prepared renderer order");
}

void TemporalUpscaler::BottleOfferPrepared(const std::shared_ptr<SewerBridge::BottleDisplay>& selected) {
    using namespace BottleCutPresent;
    bool offer = false;
    {
        std::lock_guard lock(selected->mutex);
        if (selected->offered || selected->cancelled || !selected->write ||
            selected->scene.draw_frame != BbStats::frame_number.load(std::memory_order_relaxed) ||
            selected->scene.key.load != BbEngine::Loading::Generation() ||
            selected->scene.key.target_generation != scene_targets.Generation() || BbEngine::Loading::ScreenUp() ||
            selected->display.draw_timeline != scheduler.GetWorkSemaphore()->Handle() || SewerBridgeOpen()) return;
        offer = selected->encoded.load(std::memory_order_acquire) != 0;
        if (offer) selected->offered = true;
        else {
            selected->cancelled = true;
            selected->app_checked = true;
            selected->app_refusal = "ordinary-display-unencoded-at-override";
        }
    }
    if (!offer) {
        if (selected->raw)
            fmt::print("[bottle-cut] event=prepared-offer-scope request={} scene={} frame={} epoch={} "
                       "outcome=unencoded-at-override\n", selected->scene.key.request, selected->scene.key.scene,
                       selected->scene.draw_frame, selected->scene.last_epoch);
        FinishBottlePrepared(*selected);
        return;
    }
    using namespace NativeWriteSuffix;
    if (selected->display_order) {
        const auto capture = selected->order->capture.load(std::memory_order_acquire);
        selected->barrier_order = scheduler.ReservePostNativeOperation(capture, PostRole::PrepareBarrier,
            SewerBridge::PostState::PrepareBarrierOperation);
        selected->postprocess_order = scheduler.ReservePostNativeOperation(capture, PostRole::PreparePostprocess,
            SewerBridge::PostState::PreparePostprocessOperation);
    }
    const bool full_order = selected->display_order && selected->barrier_order && selected->postprocess_order;
    const bool offered = OfferResourceDisplay(
        {.scene = selected->scene, .display = selected->display, .display_attachment = selected->attachment,
         .display_generation = selected->target.generation, .display_write = selected->write, .regions = selected->regions,
         .consume_epoch = [selected](const Scene& scene, const Override& actual, u64 generation, u64 write) {
             return selected->Consume(scene, actual, generation, write);
         }, .raw = selected->raw},
        {.display_allocation = reinterpret_cast<u64>(selected->target.allocation),
         .display_order = full_order ? selected->display_order : PostToken{},
         .prepare_barrier_order = full_order ? selected->barrier_order : PostToken{},
         .prepare_postprocess_order = full_order ? selected->postprocess_order : PostToken{},
         .complete = [selected](Result result, std::optional<RawFenced> frame) {
             {
                 std::lock_guard lock(selected->mutex);
                 if (selected->app_checked) return;
                 selected->app_checked = true;
                 if (frame && selected->Matches(result, *frame)) selected->frame = std::move(frame);
                 else selected->app_refusal = result.reason ? result.reason : "ordinary-present-unjoined";
             }
             FinishBottlePrepared(*selected);
         }});
    if (selected->raw)
        fmt::print("[bottle-cut] event=prepared-offer-scope request={} scene={} frame={} epoch={} "
                   "outcome={} native_order={}\n", selected->scene.key.request, selected->scene.key.scene,
                   selected->scene.draw_frame, selected->scene.last_epoch,
                   offered ? "offer-enrolled" : "offer-refused", full_order);
    // The offer already owns its immutable final epoch. The existing window keeps pending
    // and active records alive under its mutex through actual application fence retirement.
    if (selected->raw_close_after_offer)
        CloseWindow(selected->scene.key.request, selected->raw_close_after_offer);
    if (!offered) {
        {
            std::lock_guard lock(selected->mutex);
            if (!selected->app_checked) {
                selected->app_checked = true;
                selected->app_refusal = "prepared-resource-offer-unavailable";
            }
        }
        FinishBottlePrepared(*selected);
    }
}
#endif

SewerBridge::Draw TemporalUpscaler::SewerPlanDraw(const SewerBridge::DrawFacts& draw) {
    using namespace SewerBridge;
    const auto active = sewer_bridge;
    if (!active || !active->Open()) return {};
    auto& trace = *active;
    const auto& key = trace.merge.key;
    const auto tick = scheduler.CurrentTick();
    const auto fail = [&](const char* why) -> Draw { trace.Stop(why); return {}; };
    const bool tick_matches =
#ifdef BB_TEST_SHARED_POST_GRAPH
        trace.post ? tick >= trace.merge.tick :
#endif
        tick == trace.merge.tick;
    if (BbStats::frame_number.load(std::memory_order_relaxed) != key.frame ||
        BbEngine::Loading::Generation() != key.loading ||
        scene_targets.Generation() != key.generation ||
        scheduler.GetWorkSemaphore()->Handle() != trace.merge.timeline || !tick_matches) {
        return fail("display-render-epoch");
    }
    if (trace.redirect) {
        const bool target = std::exchange(trace.redirect, {}) == draw.output;
        if (!target || draw.scene != key.scene || !draw.original || !draw.disjoint_capable ||
            !Outside(draw.scissor, trace.regions) || trace.planned != Planned::UiCopy ||
            trace.ui != vk::Image(ui_image) || trace.ui_allocation != ui_image.allocation ||
            trace.ui_generation != sewer_ui_generation) {
            return fail("unproved-ui-attachment-write");
        }
        ++trace.ui_expected;
        return {active, Step::DisjointUi, tick};
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (!trace.post && draw.ps == TonemapHash) {
#else
    if (draw.ps == TonemapHash) {
#endif
        if (trace.planned != Planned::Merge || draw.scene != key.scene || !draw.original ||
            !draw.full_write || !SewerSameCamera(trace, camera_motion.PassMatrices(), jitter)) {
            return fail("original-tonemap-scope");
        }
        u32 joined = 0;
        Native source{};
        for (const auto id : draw.images) {
            if (id.index != trace.hdr.res.id) continue;
            for (const auto& input : draw.inputs) {
                if (!input.imageView || (input.imageLayout != vk::ImageLayout::eGeneral &&
                                         input.imageLayout != vk::ImageLayout::eShaderReadOnlyOptimal)) continue;
                const auto sampled = SewerNative(id, vk::Format::eR16G16B16A16Sfloat, input.imageView);
                if (sampled.res.image && SameNative(sampled, trace.hdr)) {
                    source = sampled;
                    ++joined;
                }
            }
        }
        const auto ldr = SewerNative(draw.color_id, vk::Format::eR8G8B8A8Unorm, draw.output);
        if (joined != 1 || !source.res.view || !ldr.res.image || !ldr.write || !Separate(source, ldr)) {
            return fail("actual-tonemap-bindings-or-write");
        }
        trace.ldr = ldr;
        trace.hdr_sample = source.res.view;
        trace.tonemap_tick = tick;
        trace.planned = Planned::Tonemap;
        return {active, Step::Tonemap, tick};
    }

    if (trace.planned != Planned::DisplayExpected) return {};
    const auto* guest = draw.color_id ? texture_cache.TryGetImage(draw.color_id, 0) : nullptr;
    if (!guest || guest->info.guest_address != trace.display_address) return {};
    std::scoped_lock lock{display_mutex};
    const auto found = displays.find(trace.display_address);
    if (found == displays.end() || !found->second.valid || !display_redirect ||
        found->second.sewer_target != draw.output || !found->second.sewer_generation ||
        draw.scene != key.scene + 1 || !draw.original || !draw.full_write ||
        draw.layout != vk::ImageLayout::eGeneral || trace.ui != vk::Image(ui_image) ||
        trace.ui_allocation != ui_image.allocation || trace.ui_generation != sewer_ui_generation) {
        return fail("actual-display-draw-or-target");
    }
    u32 sampled = 0, ui = 0;
    for (const auto& input : draw.inputs) {
        if (!input.imageView) continue;
        ++sampled;
        if (input.imageLayout == vk::ImageLayout::eGeneral &&
            std::ranges::any_of(ui_views, [&](const auto& it) { return *it.view == input.imageView; }))
            ++ui;
    }
    auto& display = found->second;
    const auto& ci = display.image.image_ci;
    if (sampled != 1 || ui != 1 || display.width != 3840 || display.height != 2160 ||
        ci.extent != vk::Extent3D{3840, 2160, 1} || ci.samples != vk::SampleCountFlagBits::e1 ||
        ci.mipLevels != 1 || ci.arrayLayers != 1 || !SewerPresent::DisplayColor(display.format)) {
        return fail("actual-display-sampled-ui");
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (trace.post) {
        auto& terminal = trace.post->terminal;
        const auto physical_display = PostPhysical(display.image, display.sewer_generation);
        const auto physical_ui = PostPhysical(ui_image, sewer_ui_generation);
        if ((terminal.display.Valid() && terminal.display != physical_display) ||
            (terminal.ui.Valid() && terminal.ui != physical_ui) ||
            PhysicalSeparation(physical_ui, physical_display) == Graph::Proof::Failed) {
            return fail("shared-post-display-backing");
        }
        auto& selected = terminal.draw;
        selected.color = draw.attachment;
        selected.slots = draw.display_slots;
        selected.pipeline = draw.pipeline;
        selected.layout = draw.pipeline_layout;
        selected.shader = draw.ps;
        selected.permutation = draw.fragment_permutation;
        selected.scene = draw.scene;
        selected.ordinary = draw.original;
        for (const auto& input : draw.inputs) {
            const auto view = std::ranges::find_if(ui_views, [&](const auto& it) {
                return input.imageView && *it.view == input.imageView;
            });
            if (view != ui_views.end()) {
                selected.source_view = input.imageView;
                selected.source_format = view->format;
                selected.source_mapping = view->mapping;
            }
        }
        if (!selected.slots.omitted && selected.slots.count == 1) {
            const auto& slot = selected.slots.images.front();
            selected.requested_slot = slot.stage != Graph::BindStage::Unknown && slot.view
                ? (slot.exact && slot.stage == Graph::BindStage::Fragment && slot.view == selected.source_view &&
                   slot.layout == vk::ImageLayout::eGeneral && slot.set == 0 && slot.element == 0 &&
                   slot.type != vk::DescriptorType::eStorageImage ? Graph::Proof::Known : Graph::Proof::Failed)
                : Graph::Proof::Unknown;
        }
        // Full viewport, scissor and write mask are range constraints. Triangle coverage is separate.
        selected.footprint = draw.full_write ? Graph::Proof::Unknown : Graph::Proof::Failed;
        if (selected.requested_slot == Graph::Proof::Failed) return fail("shared-post-display-slot");
    }
#endif
    display.sewer_epoch = std::make_shared<Epoch>(
        SewerPresent::Override{trace.display_address, vk::Image(display.image), display.format,
                               SewerPresent::Extent, trace.merge.timeline, tick},
        display.sewer_generation, ++sewer_display_write, draw.output, active
#ifdef BB_TEST_SHARED_POST_GRAPH
        , reinterpret_cast<u64>(display.image.allocation)
#endif
        );
    trace.planned = Planned::Display;
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (trace.post) {
        const auto& epoch = *display.sewer_epoch;
        trace.post->terminal.issued_candidate = {trace.merge, epoch.display, epoch.attachment,
                                                 epoch.generation, epoch.write, epoch.allocation};
    }
    if (trace.post && trace.post->order) {
        trace.post->display_order = scheduler.ReservePostNativeOperation(
            trace.post->order->capture.load(std::memory_order_acquire), Order::PostRole::Display,
            PostState::DisplayOperation);
        return {active, Step::Display, tick, trace.post->display_order};
    }
#endif
    return {active, Step::Display, tick};
}

void TemporalUpscaler::SewerOffer(const std::shared_ptr<SewerBridge::Epoch>& epoch) {
    if (!epoch || !epoch->trace->Open()) return;
    auto& trace = *epoch->trace;
    const auto& key = trace.merge.key;
    if (trace.planned != SewerBridge::Planned::Display ||
        BbStats::frame_number.load(std::memory_order_relaxed) != key.frame ||
        BbEngine::Loading::ScreenUp() || BbEngine::Loading::Generation() != key.loading ||
        scene_targets.Generation() != key.generation ||
        scheduler.GetWorkSemaphore()->Handle() != trace.merge.timeline) {
        trace.Stop("prepare-override-scope");
        return;
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (trace.post) {
        if (!trace.post->display_encoded.load(std::memory_order_acquire) ||
            trace.post->display_tick.load(std::memory_order_relaxed) != epoch->display.draw_tick) {
            trace.Stop("shared-post-display-not-encoded");
            return;
        }
        trace.offered = true;
        const auto sample = trace.checkpoint;
        sample->present_claimed.store(true, std::memory_order_release);
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        NativeWriteSuffix::PostToken prepare_barrier{}, prepare_postprocess{};
        if (trace.post->order && trace.post->display_order) {
            const auto capture = trace.post->order->capture.load(std::memory_order_acquire);
            prepare_barrier = scheduler.ReservePostNativeOperation(capture,
                NativeWriteSuffix::PostRole::PrepareBarrier, SewerBridge::PostState::PrepareBarrierOperation);
            prepare_postprocess = scheduler.ReservePostNativeOperation(capture,
                NativeWriteSuffix::PostRole::PreparePostprocess, SewerBridge::PostState::PreparePostprocessOperation);
        }
#endif
        const bool accepted = SewerPresent::OfferDisplayCandidate({
            .merge = trace.merge, .display = epoch->display, .display_attachment = epoch->attachment,
            .display_generation = epoch->generation, .display_write = epoch->write,
            .display_allocation = epoch->allocation, .regions = trace.regions,
            .consume_epoch = [epoch](const SewerPresent::Override& actual, u64 generation, u64 write) {
                return epoch->Consume(actual, generation, write);
            },
            .complete = [active = epoch->trace, candidate = trace.post->terminal.issued_candidate](
                            SewerPresent::Result result, std::optional<SewerPresent::FencedFrame> frame) {
                auto& post = *active->post;
                {
                    std::lock_guard lock(post.retirement_mutex);
                    if (post.presentation_received) return;
                    post.presentation_received = true;
                    if (frame && SewerBridge::MatchesAppFrame(result, *frame, candidate, active->regions))
                        post.raw_frame = std::move(frame);
                    else
                        post.application_refusal = result.reason ? result.reason : "shared-post-present-unproved";
                }
                SewerCompletePost(*active);
            },
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            .display_order = trace.post->display_order,
            .prepare_barrier_order = prepare_barrier,
            .prepare_postprocess_order = prepare_postprocess,
#endif
        });
        if (!accepted) {
            {
                std::lock_guard lock(trace.post->retirement_mutex);
                if (!trace.post->presentation_received) {
                    trace.post->presentation_received = true;
                    trace.post->application_refusal = "display-candidate-unavailable";
                }
            }
            SewerCompletePost(trace);
        }
        return;
    }
#endif
    if (const auto why = trace.EncoderFailure()) {
        trace.Stop(why);
        return;
    }
    auto hdr = trace.hdr.res;
    hdr.view = trace.hdr_sample;
    trace.offered = true;
    trace.checkpoint->present_claimed.store(true, std::memory_order_release);
    const auto sample = trace.checkpoint;
    SewerPresent::OfferIssuedDisplay({
        .merge = trace.merge, .tonemap_input = hdr, .tonemap_output = trace.ldr.res,
        .tonemap_input_write = trace.hdr.write, .tonemap_output_write = trace.ldr.write,
        .tonemap_tick = trace.tonemap_tick,
        .display = epoch->display, .display_attachment = epoch->attachment,
        .display_generation = epoch->generation, .display_write = epoch->write,
        .regions = trace.regions,
        .consume_epoch = [epoch](const SewerPresent::Override& source, u64 generation, u64 write) {
            return epoch->Consume(source, generation, write);
        },
        .complete = [sample](const SewerPresent::Result& result) {
            sample->FinishPresentation(result.fenced, result.reason, false);
        },
    });
}

bool TemporalUpscaler::SewerBridgeOpen() const {
    return sewer_bridge && sewer_bridge->Open();
}

void TemporalUpscaler::SewerIndirectDisplayOrUi(VideoCore::ImageId color) {
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (BottlePreparedPending()) {
        const auto* output = color ? texture_cache.TryGetImage(color, 0) : nullptr;
        if (output && output->info.guest_address == bottle_prepared->address) bottle_prepared->Cancel();
    }
#endif
    if (!SewerBridgeOpen()) return;
    const auto* output = color ? texture_cache.TryGetImage(color, 0) : nullptr;
    if (sewer_bridge->redirect || (output && output->info.guest_address == sewer_bridge->display_address)) {
        sewer_bridge->Stop("indirect-final-ui-or-display-writer");
    }
}

void TemporalUpscaler::OnDisplayPass(VAddr address, VideoCore::ImageId frame) {
    // bbport: a frame with no UI draw at all (the HUD hidden in the game's options, #23) reaches
    // its display pass without the upscale its first UI draw would start: run it here, so the
    // display pass reads the upscaled frame instead of the render-size one.
    if (Scaled() && !early_upscale && !ui_phase && ldr_target && camera_motion.Ready() && Active() && !failed) {
        RunScaled();
        if (ui_phase && hdr_native.WantsUiStart() && HdrNative::Wanted()) {
            hdr_native.OnUiStart(HdrUiImage());
        }
    }
    // bbport (r98b_particles-reduced-scene): with the upscale before the game's post (Run) a
    // frame without UI (the HUD hidden, BB_CLEAN_SHOT) reaches its display pass with no
    // output-size copy of its frame. Only while after_upscale is set (the ambient motes on) the
    // copy is made here as the first UI draw would make it (RunUiOnly, which calls
    // after_upscale), and the display pass reads it as it does a frame with UI.
    if (after_upscale && early_upscale && !ui_phase && LdrFrame(ldr_target) &&
        dispatched_last_frame && camera_motion.Ready() && Active() && !failed) {
        RunUiOnly(ldr_target, camera_motion.Depth(), true);
        if (ui_phase && hdr_native.WantsUiStart() && HdrNative::Wanted()) {
            hdr_native.OnUiStart(HdrUiImage());
        }
    }
    // bbport: frame generation: a frame without UI is its own frame without UI.
    if (frame_gen && frame_gen->WantsHudless()) {
        if (ui_phase) {
            CaptureFrameGenUiImage();
        } else if (!Scaled() && LdrFrame(frame)) {
            CaptureFrameGenHudless(frame);
        }
    }
    HdrNative::Source source{};
    if (HdrNative::Wanted()) {
        if (ui_phase) {
            // The scaled presets: the display pass is redirected to the output-size UI image.
            source = HdrUiImage();
        } else if (!Scaled()) {
            // The game's UI target: the one the UI-free copy came from, else (no UI pass) the
            // previous draw's target. Another frame-size RGBA8 target there (the display pass
            // could read either) is a mismatch: no gain map for this frame.
            const VideoCore::ImageId id = hdr_ui_target ? hdr_ui_target : frame;
            if (LdrFrame(id) && (!LdrFrame(frame) || frame == id)) {
                source = hdr_native.Guest(id, vk::Format::eR8G8B8A8Unorm);
            }
        }
    }
    hdr_native.OnDisplayPass(address, source);
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (bottle_prepared && !bottle_prepared->address && address && ui_phase && !SewerBridgeOpen() &&
        bottle_prepared->scene.draw_frame == BbStats::frame_number.load(std::memory_order_relaxed) &&
        bottle_prepared->scene.key.load == BbEngine::Loading::Generation() &&
        bottle_prepared->scene.key.target_generation == scene_targets.Generation()) {
        bottle_prepared->address = address;
        bottle_prepared->ui = PostPhysical(ui_image, bottle_ui_generation);
    } else if (const auto request = BottleCaustic::CutSource::Run(); request && address &&
               (!bottle_prepared || bottle_prepared->scene.key.request != request ||
                bottle_prepared->scene.draw_frame != BbStats::frame_number.load(std::memory_order_relaxed))) {
        const u32 frame = BbStats::frame_number.load(std::memory_order_relaxed);
        if (frame && !std::exchange(bottle_source_refusal_reported, true)) {
            fmt::print("[bottle-cut] event=prepared-caller-refused request={} frame={} why=ordinary-scene-not-enrolled\n",
                       request, frame);
        }
    }
#endif
    if (SewerBridgeOpen()) {
        auto& trace = *sewer_bridge;
        const auto tick = scheduler.CurrentTick();
        const bool tick_matches =
#ifdef BB_TEST_SHARED_POST_GRAPH
            trace.post ? trace.post->ui_tick && tick >= trace.post->ui_tick :
#endif
            tick == trace.merge.tick;
        if (trace.planned == SewerBridge::Planned::UiCopy && ui_phase && !trace.redirect && address &&
            trace.ui == vk::Image(ui_image) && trace.ui_allocation == ui_image.allocation &&
            trace.ui_generation == sewer_ui_generation && tick_matches &&
            SewerSameCamera(trace, camera_motion.PassMatrices(), jitter)) {
            trace.display_address = address;
            trace.planned = SewerBridge::Planned::DisplayExpected;
        } else {
            trace.Stop("ordinary-display-finishing-scope");
        }
    }
    if (BottleMotion::Run()) {
        auto& s=BottleMotion::Scene();
        motion_finish={};
        motion_finish_ui=vk::Image{};
        if (s.mark && !s.bad) {
            if (!s.dlss || !s.tone || !s.ui || !ui_phase || s.ui_image!=vk::Image(ui_image) ||
                s.mark.on!=u8(BottleCaustic::On()) || s.arm_generation!=BbLiveKnobs::Generation() ||
                !BottleMotion::MarkerClear(s)) {
                BottleMotion::Refuse(s,"finishing-ui-identity");
            } else {
                motion_finish=s.mark;
                motion_finish.address=address;
                motion_finish_ui=s.ui_image;
                using BottleMotion::P;
                std::printf("[bottle-motion-t198] event=scene run=%u id=%u arm=%u scene=%llu qpc_ns=%llu "
                            "on=%u input=1920x1080 proxy=%llu\n",u32(s.mark.run),u32(s.mark.id),
                            s.mark.arm,P(s.mark.scene),P(s.mark.scene_ns),u32(s.mark.on),P(s.generation));
                for (u32 i=0;i<3;++i) {
                    const auto* r=s.view.data()+i*4;
                    std::printf("[bottle-motion-t198] event=view id=%u row=%u values=(%.9g,%.9g,%.9g,%.9g)\n",
                                u32(s.mark.id),i,r[0],r[1],r[2],r[3]);
                }
                std::printf("[bottle-motion-t198] event=projection id=%u values=(%.9g,%.9g,%.9g,%.9g) "
                            "jitter=(%.9g,%.9g)\n",u32(s.mark.id),s.proj[0],s.proj[1],s.proj[2],s.proj[3],
                            s.jitter[0],s.jitter[1]);
            }
        }
        BottleMotion::ClearScene(s);
    }
    hdr_ui_target = {};
}

void TemporalUpscaler::CaptureFrameGenInputs(vk::ImageView depth_view, u32 w, u32 h) {
    if (!frame_gen) {
        return;
    }
    // The jitter as the upscaler gives it to FSR (toggle 1 << 26 flips the sign for tests).
    const float sign = BbToggle::Disabled(1u << 26) ? -1.0f : 1.0f;
    frame_gen->CaptureInputs(scheduler, depth_view, vk::Image(motion_image), w, h,
                             {sign * jitter[0], sign * jitter[1]}, camera_motion.Near(),
                             camera_motion.VerticalFov(), camera_motion.CameraMatrices());
}

void TemporalUpscaler::CaptureFrameGenHudless(VideoCore::ImageId id) {
    if (!frame_gen || !id || !frame_gen->WantsHudless()) {
        return;
    }
    scheduler.EndRendering();
    auto& image = texture_cache.GetImage(id);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eTransfer,
                    vk::AccessFlagBits2::eTransferRead);
    runtime.FlushBarriers();
    frame_gen->CaptureHudless(scheduler, image.GetImage(), image.info.pixel_format,
                              image.info.size.width, image.info.size.height);
}

void TemporalUpscaler::CaptureFrameGenUiImage() {
    if (!frame_gen || !frame_gen->WantsHudless() || !ui_image) {
        return;
    }
    // General layout: written by the upscale (or the background copy), no UI drawn yet.
    scheduler.EndRendering();
    frame_gen->CaptureHudless(scheduler, vk::Image(ui_image), ui_format, ui_width, ui_height);
}

void TemporalUpscaler::EnsureUiResources(u32 w, u32 h, vk::Format color, vk::Format depth) {
    const bool resized = w != ui_width || h != ui_height;
    const bool new_color = !ui_image || resized || color != ui_format;
    const bool new_depth = !ui_depth_image || resized || depth != ui_depth_format;
    if (!new_color && !new_depth) {
        return;
    }
    scheduler.Finish();
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    ui_width = w;
    ui_height = h;
    if (new_color) {
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        ++bottle_ui_generation;
#endif
        if (SewerMotion::FinalEnabled()) ++sewer_ui_generation;
        if (SewerBridgeOpen() && sewer_bridge->planned != SewerBridge::Planned::Tonemap
#ifdef BB_TEST_SHARED_POST_GRAPH
            && !sewer_bridge->post
#endif
        ) {
            sewer_bridge->Stop("ui-backing-recreated");
        }
        ui_views.clear();
        ui_view.reset();
        ui_storage_view.reset();
        ui_image = VideoCore::UniqueImage(device, allocator);
        ui_image.Create(vk::ImageCreateInfo{
            .flags = vk::ImageCreateFlagBits::eMutableFormat | vk::ImageCreateFlagBits::eExtendedUsage,
            .imageType = vk::ImageType::e2D,
            .format = color,
            .extent = {w, h, 1},
            .mipLevels = 1, .arrayLayers = 1, .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                     vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eTransferDst |
                     vk::ImageUsageFlagBits::eTransferSrc,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        ui_format = color;
    }
    if (new_depth) {
        ui_depth_view.reset();
        ui_depth_image = VideoCore::UniqueImage(device, allocator);
        ui_depth_image.Create(vk::ImageCreateInfo{
            .imageType = vk::ImageType::e2D,
            .format = depth,
            .extent = {w, h, 1},
            .mipLevels = 1, .arrayLayers = 1, .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eDepthStencilAttachment |
                     vk::ImageUsageFlagBits::eTransferDst,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        const auto aspect = vk::ImageAspectFlagBits::eDepth |
            (depth == vk::Format::eD32SfloatS8Uint ? vk::ImageAspectFlagBits::eStencil
                                                : vk::ImageAspectFlags{});
        ui_depth_view = Check(device.createImageViewUnique({
            .image = vk::Image(ui_depth_image), .viewType = vk::ImageViewType::e2D,
            .format = depth, .subresourceRange = {aspect, 0, 1, 0, 1},
        }));
        ui_depth_format = depth;
    }
    std::printf("UI: native composition %ux%u (scene %ux%u), independent of FSR history\n",
                w, h, render_width, render_height);
}

void TemporalUpscaler::PrepareUiDepth(VideoCore::ImageId depth_id) {
    scheduler.EndRendering();
    const auto aspect = vk::ImageAspectFlagBits::eDepth |
        (ui_depth_format == vk::Format::eD32SfloatS8Uint ? vk::ImageAspectFlagBits::eStencil
                                                      : vk::ImageAspectFlags{});
    // Copy depth if blit is supported; otherwise just clear it (UI depth test still works).
    const bool copy = depth_id && depth_blit &&
        texture_cache.GetImage(depth_id).info.pixel_format == ui_depth_format;
    // bbport: a scene depth whose proxy is newer is blitted from the proxy (ProxyUpscalerInputs):
    // nearest from the proxy is what the nearest resolve and the blit after it gave.
    const bool from_proxy = copy && ProxyUpscalerInputs() && scene_targets.Reduced() &&
                            scene_targets.EligibleScene(texture_cache.GetImage(depth_id)) &&
                            scene_targets.NativeStale(texture_cache.GetImage(depth_id));
    vk::Image proxy_source{};
    if (from_proxy) {
        VideoCore::ImageViewInfo view;
        view.format = texture_cache.GetImage(depth_id).info.pixel_format;
        proxy_source = scene_targets.Read(depth_id, view, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferRead).image;
    } else if (copy) {
        runtime.Transit(&texture_cache.GetImage(depth_id), vk::ImageLayout::eTransferSrcOptimal,
                        vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferRead);
        runtime.FlushBarriers();
    }
    const vk::ImageSubresourceRange range{aspect, 0, 1, 0, 1};
    // Without blit support, UI depth is cleared but not copied from the scene.
    // UI elements will still depth-test correctly against the cleared buffer.
    vk::Image source{};
    vk::ImageBlit region{};
    if (copy) {
        const auto& image = texture_cache.GetImage(depth_id);
        const auto proxy = scene_targets.ProxySize(image);
        source = from_proxy ? proxy_source : vk::Image(image.backing->image);
        region = {
            .srcSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
            .srcOffsets = std::array{vk::Offset3D{0, 0, 0},
                from_proxy ? vk::Offset3D{s32(proxy.width), s32(proxy.height), 1}
                           : vk::Offset3D{s32(image.info.size.width),
                                          s32(image.info.size.height), 1}},
            .dstSubresource = {vk::ImageAspectFlagBits::eDepth, 0, 0, 1},
            .dstOffsets = std::array{vk::Offset3D{0, 0, 0},
                vk::Offset3D{s32(ui_width), s32(ui_height), 1}},
        };
    }
    // bbport: recorded on the recording thread (direct recording here waited for it to finish
    // everything queued, every frame).
    const vk::ImageLayout source_layout =
        from_proxy ? vk::ImageLayout::eGeneral : vk::ImageLayout::eTransferSrcOptimal;
    scheduler.Record([depth = vk::Image(ui_depth_image), range, source, source_layout,
                      region](vk::CommandBuffer cmd) {
        vk::ImageMemoryBarrier2 barrier{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eTransferDstOptimal,
            .image = depth, .subresourceRange = range,
        };
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
        cmd.clearDepthStencilImage(depth, vk::ImageLayout::eTransferDstOptimal,
                                   {.depth = 1.0f, .stencil = 0}, range);
        if (source) {
            barrier.srcStageMask = vk::PipelineStageFlagBits2::eTransfer;
            barrier.srcAccessMask = vk::AccessFlagBits2::eTransferWrite;
            barrier.oldLayout = vk::ImageLayout::eTransferDstOptimal;
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            cmd.blitImage(source, source_layout, depth,
                          vk::ImageLayout::eTransferDstOptimal, region, vk::Filter::eNearest);
        }
        barrier.srcStageMask = vk::PipelineStageFlagBits2::eTransfer;
        barrier.srcAccessMask = vk::AccessFlagBits2::eTransferWrite;
        barrier.dstStageMask = vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                               vk::PipelineStageFlagBits2::eLateFragmentTests;
        barrier.dstAccessMask = vk::AccessFlagBits2::eDepthStencilAttachmentRead |
                                vk::AccessFlagBits2::eDepthStencilAttachmentWrite;
        barrier.oldLayout = vk::ImageLayout::eTransferDstOptimal;
        barrier.newLayout = vk::ImageLayout::eGeneral;
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
    });
}

void TemporalUpscaler::RunUiOnly(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                                 bool world) {
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0xF5A1'0000ull, [] { return std::string{"upscaler RunUiOnly"}; });
    }
    const auto& color = texture_cache.GetImage(color_id);
    const auto depth_format = depth_id ? texture_cache.GetImage(depth_id).info.pixel_format
                                      : vk::Format::eD32SfloatS8Uint;
    EnsureUiResources(target_width, target_height, color.info.pixel_format, depth_format);
    PrepareUiDepth(depth_id);
    // Copy only the background already drawn. The subsequent menu/HUD/text draws execute
    // directly at output resolution, including frames with no scene or camera at all.
    vk::Image source = color.GetImage();
    auto source_layout = vk::ImageLayout::eTransferSrcOptimal;
    u32 source_width = color.info.size.width, source_height = color.info.size.height;
    if (!scaled_session && camera_motion.Depth() && scene_targets.Reduced() &&
        scene_targets.EligibleScene(color)) {
        VideoCore::ImageViewInfo view;
        view.format = color.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, view,
                                              vk::PipelineStageFlagBits2::eTransfer,
                                              vk::AccessFlagBits2::eTransferRead);
        source = proxy.image;
        source_layout = proxy.layout;
        source_width = render_width;
        source_height = render_height;
    } else {
        runtime.Transit(&texture_cache.GetImage(color_id), vk::ImageLayout::eTransferSrcOptimal,
                        vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferRead);
        runtime.FlushBarriers();
    }
    // bbport: with Widescreen on another screen shape (BB_UI_SIZE), a frame without the 3D world
    // (title, loading and item screens) is the game's 16:9 stage in the middle; what lies beside it
    // in the game's target is not drawn and showed as grey bars (#18). Black there instead: only
    // the stage is copied, over a cleared image. UI the game draws past the stage still shows.
    // A frame of the world is copied whole: with no upscaler every frame comes here, and the
    // world's sides were cut to black bars (widescreen worked only with an upscaler on).
    // With the menus' movies widened (BB_WIDE_UI_MOVIES or the PC options' BB_WIDE_OPTION_MOVIE,
    // start/main.cpp) the menus' full-screen pictures, dims and fades are drawn beside the stage
    // too, so such a frame is copied whole as well: a loading screen's frames alternate between this
    // copy and the upscaler's, and its picture flickered between the full width and the stage.
    static const bool wide_movies = [] {
        const char* movies = std::getenv("BB_WIDE_UI_MOVIES");
        const char* options = std::getenv("BB_WIDE_OPTION_MOVIE");
        return (movies && *movies) || (options && *options);
    }();
    s32 x0 = 0, y0 = 0, x1 = s32(ui_width), y1 = s32(ui_height);
    if (const auto ui = UiComposition::UiSize();
        !world && !wide_movies && (ui[0] != 1920.0f || ui[1] != 1080.0f)) {
        const auto fit = UiComposition::Fit(ui_width, ui_height, ui);
        const float stage = UiComposition::StageScale(ui), w = 1920.0f * stage, h = 1080.0f * stage;
        x0 = std::clamp(s32(std::lround(fit.offset[0] + fit.scale[0] * (ui[0] - w) / 2)), 0, s32(ui_width));
        y0 = std::clamp(s32(std::lround(fit.offset[1] + fit.scale[1] * (ui[1] - h) / 2)), 0, s32(ui_height));
        x1 = std::clamp(s32(std::lround(x0 + fit.scale[0] * w)), x0, s32(ui_width));
        y1 = std::clamp(s32(std::lround(y0 + fit.scale[1] * h)), y0, s32(ui_height));
    }
    const bool bars = x0 > 0 || y0 > 0 || x1 < s32(ui_width) || y1 < s32(ui_height);
    const auto from = [&](s32 v, u32 dst, u32 src) { return s32(std::lround(double(v) * src / dst)); };
    const vk::ImageBlit region{
        .srcSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
        .srcOffsets = std::array{vk::Offset3D{from(x0, ui_width, source_width), from(y0, ui_height, source_height), 0},
            vk::Offset3D{from(x1, ui_width, source_width), from(y1, ui_height, source_height), 1}},
        .dstSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
        .dstOffsets = std::array{vk::Offset3D{x0, y0, 0}, vk::Offset3D{x1, y1, 1}},
    };
    SewerBridge::Draw sewer_copy;
    if (SewerBridgeOpen()) {
        using namespace SewerBridge;
        auto& trace = *sewer_bridge;
        const auto stamp = SewerNative(color_id, vk::Format::eR8G8B8A8Unorm, {});
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (trace.post && trace.post->ui_tick) {
            trace.Stop("shared-post-ui-copy-repeated");
        } else if (trace.post) {
            auto& post = *trace.post;
            post.ui_source = stamp;
            if (const auto* actual = stamp.res.image == source ?
                    texture_cache.TryGetImage(color_id, stamp.res.uid) : nullptr;
                actual && actual->backing == stamp.backing && actual->GetImage() == source) {
                post.terminal.source = PostPhysical(actual->backing->image, stamp.res.uid);
            }
            post.terminal.ui = PostPhysical(ui_image, sewer_ui_generation);
            // Transfer ranges have no bound view. Keep a distinct canonical transfer identity.
            if (stamp.res.image) post.ui_source.res.view = vk::ImageView{};
            post.blit_source = source;
            post.blit_source_layout = source_layout;
            post.blit = region;
            post.blit_source_extent = vk::Extent2D{source_width, source_height};
            post.ui_extent = vk::Extent2D{ui_width, ui_height};
            post.ui_image = vk::Image(ui_image);
            post.ui_tick = scheduler.CurrentTick();
            post.ui_ordinary = post.ui_tick >= trace.merge.tick && scheduler.GetWorkSemaphore()->Handle() == trace.merge.timeline &&
                early_upscale && world && dispatched_last_frame && !bars && source == stamp.res.image &&
                source_layout == vk::ImageLayout::eTransferSrcOptimal &&
                SewerSameCamera(trace, camera_motion.PassMatrices(), jitter) &&
                post.ui_extent == SewerPresent::Extent && post.blit_source_extent == post.ui_extent && stamp.allocation &&
                ui_image && ui_image.allocation && stamp.allocation != ui_image.allocation &&
                PhysicalSeparation(post.terminal.source, post.terminal.ui) != Graph::Proof::Failed;
            post.ui_after_writer = bool(after_upscale);
            if (post.ui_ordinary && !post.ui_after_writer && !trace.redirect && trace.planned == Planned::Merge) {
                trace.planned = Planned::UiCopy;
                trace.ui = post.ui_image;
                trace.ui_allocation = ui_image.allocation;
                trace.ui_generation = sewer_ui_generation;
                post.ui_version = {reinterpret_cast<u64>(ui_image.allocation), BottleMotion203::Transfer(post.ui_image),
                    sewer_ui_generation, sewer_ui_generation, 0, {0, 1, 0, 1, 1},
                    BottleMotion203::Format(ui_format)};
                sewer_copy = {sewer_bridge, Step::UiCopy, post.ui_tick};
            }
        } else
#endif
        if (trace.planned != Planned::Tonemap || !early_upscale || !world || !dispatched_last_frame ||
            !SewerSameCamera(trace, camera_motion.PassMatrices(), jitter) ||
            !SameNative(trace.ldr, stamp) || source != stamp.res.image ||
            source_layout != vk::ImageLayout::eTransferSrcOptimal ||
            bars || source_width != 3840 || source_height != 2160 ||
            ui_width != 3840 || ui_height != 2160 || !ui_image || !ui_image.allocation ||
            source == vk::Image(ui_image) || stamp.allocation == ui_image.allocation ||
            scheduler.CurrentTick() != trace.merge.tick ||
            scheduler.GetWorkSemaphore()->Handle() != trace.merge.timeline) {
            trace.Stop("ordinary-ui-copy-source-or-route");
        } else if (after_upscale) {
            trace.Stop("ui-compositor-writer-uncertified");
        } else {
            trace.planned = Planned::UiCopy;
            trace.ui = vk::Image(ui_image);
            trace.ui_allocation = ui_image.allocation;
            trace.ui_generation = sewer_ui_generation;
            sewer_copy = {sewer_bridge, Step::UiCopy, scheduler.CurrentTick()};
        }
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    const auto post_copy = SewerBridgeOpen() && sewer_bridge->post ? sewer_bridge : nullptr;
    if (post_copy && post_copy->post->order) {
        auto& post = *post_copy->post;
        post.ui_order = scheduler.ReservePostNativeOperation(
            post.order->capture.load(std::memory_order_acquire), SewerBridge::Order::PostRole::UiBlit,
            SewerBridge::PostState::UiOperation);
    }
    const auto post_token = post_copy ? post_copy->post->ui_order : NativeWriteSuffix::PostToken{};
#endif
    auto record_ui_copy = [source, source_layout, ui = vk::Image(ui_image), bars, region, sewer_copy
#ifdef BB_TEST_SHARED_POST_GRAPH
                           , post_copy, post_token
#endif
                           ](vk::CommandBuffer cmd
#ifdef BB_TEST_SHARED_POST_GRAPH
                             , NativeWriteSuffix::Encoder* encoder
#endif
                           ) {
        vk::ImageMemoryBarrier2 barrier{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eTransferDstOptimal,
            .image = ui,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post_copy) post_copy->post->terminal.Barrier(SewerBridge::LocalEdge::UiDiscard).Observe(cmd, barrier);
#endif
        if (bars) {
            const vk::ImageSubresourceRange all{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
            cmd.clearColorImage(ui, vk::ImageLayout::eTransferDstOptimal,
                                vk::ClearColorValue{std::array{0.0f, 0.0f, 0.0f, 1.0f}}, all);
            vk::MemoryBarrier2 cleared{
                .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
            };
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &cleared});
        }
        cmd.blitImage(source, source_layout, ui, vk::ImageLayout::eTransferDstOptimal, region,
                      vk::Filter::eLinear);
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (encoder) encoder->NotePost(post_token);
        if (post_copy) {
            static std::atomic<u64> issued_blits{};
            post_copy->post->terminal.blit_write.store(issued_blits.fetch_add(1, std::memory_order_relaxed) + 1,
                                                       std::memory_order_release);
        }
#endif
        barrier.srcStageMask = vk::PipelineStageFlagBits2::eTransfer;
        barrier.srcAccessMask = vk::AccessFlagBits2::eTransferWrite;
        barrier.dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput;
        barrier.dstAccessMask = vk::AccessFlagBits2::eColorAttachmentRead |
                                vk::AccessFlagBits2::eColorAttachmentWrite;
        barrier.oldLayout = vk::ImageLayout::eTransferDstOptimal;
        barrier.newLayout = vk::ImageLayout::eGeneral;
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
        sewer_copy.Encoded(cmd);
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post_copy) {
            post_copy->post->terminal.Barrier(SewerBridge::LocalEdge::UiAttachment).Observe(cmd, barrier);
            post_copy->post->ui_encoded.store(std::bit_cast<u64>(cmd), std::memory_order_release);
        }
#endif
    };
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (post_token) {
        scheduler.RecordPostNative(post_token,
            [record = std::move(record_ui_copy)](vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
                record(cmd, &encoder);
            });
    } else {
        scheduler.Record([record = std::move(record_ui_copy)](vk::CommandBuffer cmd) { record(cmd, nullptr); });
    }
    if (post_copy) {
        const u64 fence = scheduler.CurrentTick();
        scheduler.DeferOperation([trace = post_copy, fence, owner = &scheduler] {
            const bool ready = SewerRetirePost(*owner, *trace, fence);
            {
                std::lock_guard lock(trace->post->retirement_mutex);
                trace->post->graph_retired = true;
                trace->post->graph_ready = ready;
            }
            SewerCompletePost(*trace);
        }, "shared post graph");
    }
#else
    scheduler.Record(std::move(record_ui_copy));
#endif
    // bbport (r98b_particles-reduced-scene): with the upscale before the game's post (Run, at
    // the trigger dispatch) RunScaled never runs: the output-size frame before the UI is this
    // copy of the game's finished frame. Only for a frame of the world Run upscaled this frame.
    // The light is read from the game's frame (output size, no jitter), the depth from the scene
    // depth as Run read it (its reduced proxy at the scene size, jittered by `jitter`).
    if (after_upscale && early_upscale && world && dispatched_last_frame &&
        camera_motion.Ready()) {
        auto& frame = texture_cache.GetImage(color_id);
        auto& scene_depth = texture_cache.GetImage(camera_motion.Depth());
        const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(scene_depth);
        const u32 dw = reduced ? scene_targets.Size().width : scene_depth.info.size.width;
        const u32 dh = reduced ? scene_targets.Size().height : scene_depth.info.size.height;
        // Output pixels address the game's frame: it must have the output size (else the call
        // has no view and counts as a skipped frame).
        const bool fits = frame.info.size.width == ui_width &&
                          frame.info.size.height == ui_height &&
                          scene_depth.info.size.width == ui_width &&
                          scene_depth.info.size.height == ui_height;
        vk::ImageView depth_view{}, frame_view{};
        if (fits) {
            if (reduced) {
                VideoCore::ImageViewInfo di;
                di.format = scene_depth.info.pixel_format;
                // r98c_particles-visible: read by the motes' vertex and fragment shaders
                depth_view = scene_targets
                                 .Read(camera_motion.Depth(), di,
                                       vk::PipelineStageFlagBits2::eVertexShader |
                                           vk::PipelineStageFlagBits2::eFragmentShader,
                                       vk::AccessFlagBits2::eShaderSampledRead)
                                 .view;
            } else {
                depth_view = CachedView(scene_depth, scene_depth.info.pixel_format,
                                        vk::ImageAspectFlagBits::eDepth);
                runtime.Transit(&scene_depth, vk::ImageLayout::eGeneral,
                                vk::PipelineStageFlagBits2::eVertexShader |
                                    vk::PipelineStageFlagBits2::eFragmentShader,
                                vk::AccessFlagBits2::eShaderSampledRead);
            }
            frame_view =
                CachedView(frame, frame.info.pixel_format, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(&frame, vk::ImageLayout::eGeneral,
                            vk::PipelineStageFlagBits2::eVertexShader,
                            vk::AccessFlagBits2::eShaderSampledRead);
            runtime.FlushBarriers();
        }
        after_upscale({fits ? UiStorageView(vk::Image(ui_image)) : vk::ImageView{}, depth_view,
                       frame_view, frame.info.pixel_format, ui_width, ui_height, dw, dh, jitter,
                       true,
                       "into RunUiOnly's output-size copy of the game's finished frame (upscaled "
                       "before its post by Run)"});
    }
    if (!early_upscale || !dispatched_last_frame) {
        reset = true; // returning to 3D must not reuse history from before a menu/loading screen
    }
    done_this_frame = ui_phase = true;
    if (BottleMotion::Run()) {
        auto& s=BottleMotion::Scene();
        if (s.mark && !s.bad) {
            if (!early_upscale || !world || !dispatched_last_frame || !s.dlss || !s.tone || s.ui ||
                s.ldr_id!=color_id.index || s.ldr_uid!=color.image_uid || s.ldr_write!=color.write_seq ||
                source!=color.GetImage() || source_width!=3840 || source_height!=2160 || bars ||
                ui_width!=3840 || ui_height!=2160 || !ui_image) {
                BottleMotion::Refuse(s,"ui-source-not-proved-world-tonemap");
            } else {
                s.ui=true;
                s.ui_image=vk::Image(ui_image);
            }
        }
    }
    ui_color = color_id;
    ui_depth = depth_id;
}

void TemporalUpscaler::RunScaled() {
    if (auto* profiler = GpuProfiler::Get()) {
        const char* label = BbSettings::Get().upscaler == BbSettings::UpscalerTaa
            ? "upscaler RunScaled (TAA)" : "upscaler RunScaled (FSR)";
        profiler->Mark(0xF5A0'0000ull ^ std::hash<std::string_view>{}(label),
                       [label] { return std::string{label}; });
    }
    auto& color = texture_cache.GetImage(ldr_target);
    auto& depth = texture_cache.GetImage(camera_motion.Depth());
    // The scene fills the top-left w x h of its targets (iw x ih, aligned by the game).
    const u32 iw = color.info.size.width, ih = color.info.size.height;
    const auto [w, h] = SceneSize(iw, ih);
    const u32 ow = target_width, oh = target_height;
    if (depth.info.size.width != iw || depth.info.size.height != ih || w > ow || h > oh) {
        return;
    }
    if (!EnsureResources(w, h, ow, oh, false)) {
        failed = true;
        return;
    }
    EnsureUiResources(ow, oh, color.info.pixel_format, depth.info.pixel_format);
    PrepareUiDepth(camera_motion.Depth());
    const auto depth_format = depth.info.pixel_format;
    // Views kept across frames: FSR 4 registers images by view in a registry of eight.
    vk::Image depth_image = depth.GetImage(), color_image = color.GetImage();
    vk::ImageView depth_view{}, color_view{};
    u32 source_width = iw, source_height = ih;
    if (!scaled_session) {
        VideoCore::ImageViewInfo ci, di;
        ci.format = color.info.pixel_format;
        di.format = depth_format;
        const auto cp = scene_targets.Read(ldr_target, ci);
        const auto dp = scene_targets.Read(camera_motion.Depth(), di);
        color_image = cp.image;
        color_view = cp.view;
        depth_image = dp.image;
        depth_view = dp.view;
        source_width = w;
        source_height = h;
    } else {
        depth_view = CachedView(depth, depth_format, vk::ImageAspectFlagBits::eDepth);
        color_view = CachedView(color, color.info.pixel_format, vk::ImageAspectFlagBits::eColor);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eComputeShader,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }

    scheduler.EndRendering();
    // bbport: the motion pass and FSR 3 are recorded through the scheduler, on a recording
    // thread (recording them here cost the draw recording thread ~5% of its time, plus a wait
    // for the recording thread every frame). FSR 4 and TAA keep their frame bookkeeping on
    // this thread and record directly below.
    const auto barrier = [&](vk::Image image, vk::ImageAspectFlags aspect,
                             vk::ImageLayout old_layout, vk::PipelineStageFlags2 src_stage,
                             vk::AccessFlags2 src_access, vk::ImageLayout new_layout,
                             vk::PipelineStageFlags2 dst_stage, vk::AccessFlags2 dst_access) {
        const vk::ImageMemoryBarrier2 b{
            .srcStageMask = src_stage,
            .srcAccessMask = src_access,
            .dstStageMask = dst_stage,
            .dstAccessMask = dst_access,
            .oldLayout = old_layout,
            .newLayout = new_layout,
            .image = image,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        };
        scheduler.Record([b](vk::CommandBuffer cmdbuf) {
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b});
        });
    };
    const auto all = vk::PipelineStageFlagBits2::eAllCommands;
    const auto color_access = vk::AccessFlagBits2::eColorAttachmentRead |
                              vk::AccessFlagBits2::eColorAttachmentWrite;
    const auto rw = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
    if (jitter[0] != 0.0f || jitter[1] != 0.0f) {
        ClampSceneEdges(scheduler, color_image, source_width, source_height);
    }
    // The previous frame's display pass read it: all commands before.
    barrier(vk::Image(ui_image), vk::ImageAspectFlagBits::eColor, vk::ImageLayout::eUndefined,
            all, vk::AccessFlagBits2::eNone, vk::ImageLayout::eGeneral, all, rw);
    barrier(vk::Image(motion_image), vk::ImageAspectFlagBits::eColor, vk::ImageLayout::eUndefined,
            all, vk::AccessFlagBits2::eNone, vk::ImageLayout::eGeneral,
            vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderWrite);
    camera_motion.RecordMotion(depth_view, *motion_view, w, h);
    barrier(vk::Image(motion_image), vk::ImageAspectFlagBits::eColor, vk::ImageLayout::eGeneral,
            vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderWrite,
            vk::ImageLayout::eGeneral, all, vk::AccessFlagBits2::eShaderRead);
    CaptureFrameGenInputs(depth_view, w, h);

    const auto now = std::chrono::steady_clock::now();
    float frame_ms = std::chrono::duration<float, std::milli>(now - last_frame).count();
    if (frame_ms <= 0.0f || frame_ms > 200.0f) {
        frame_ms = 16.6f;
    }
    last_frame = now;

    // bbport: FSR 4 writes its HDR-format output, copied into the output-size UI image.
    if (UseFsr4() || BbSettings::Get().upscaler == BbSettings::UpscalerTaa) {
        const auto cmdbuf = scheduler.CommandBuffer(); // after the commands recorded above
        barrier(vk::Image(output_image), vk::ImageAspectFlagBits::eColor,
                vk::ImageLayout::eUndefined, all, vk::AccessFlagBits2::eNone,
                vk::ImageLayout::eGeneral, all, rw);
        bool ok4 = true;
        if (BbSettings::Get().upscaler == BbSettings::UpscalerTaa) {
            RecordTaa(cmdbuf, color_view, depth_view);
        } else {
            // bbport: DLSS and XeSS take the frame as it is (XeSS with its LDR input flag).
            if (BbSettings::Get().upscaler == BbSettings::UpscalerDlss ||
                BbSettings::Get().upscaler == BbSettings::UpscalerXess) {
            ok4 = RecordFsr4(cmdbuf,
                             {color_image, color_view, source_width, source_height,
                              color.info.pixel_format},
                             {depth_image, depth_view, source_width, source_height, depth_format},
                             w, h, ow, oh, frame_ms, mask_ready && ReactiveOn());
            } else {
            // bbport: FSR 4 treats its colour as linear light; this frame is the game's
            // tonemapped, sRGB-encoded one. Decoded first, the output encoded again below.
            // BB_FSR4_LINEAR=0 or toggle bit 63: the encoded frame as before (A/B).
            static const bool linear_env = [] {
                const char* env = std::getenv("BB_FSR4_LINEAR");
                return !env || env[0] != '0';
            }();
            // An sRGB-format frame is decoded by its view already (and encoded by the blit).
            const bool srgb_format =
                vk::to_string(color.info.pixel_format).find("Srgb") != std::string::npos;
            fsr4_linear_frame = linear_env && fsr4_linear_image && !srgb_format &&
                                !BbToggle::Disabled(BbToggle::Fsr4EncodedInput);
            Fsr4Upscaler::Image input{color_image, color_view, source_width, source_height};
            {
                static int reported = -1;
                if (int(fsr4_linear_frame) != reported) {
                    reported = int(fsr4_linear_frame);
                    std::printf("Upscaler: FSR 4 input %s (%s)\n",
                                fsr4_linear_frame ? "decoded to linear light" : "as it is",
                                vk::to_string(color.info.pixel_format).c_str());
                }
            }
            if (fsr4_linear_frame) {
                const vk::ImageMemoryBarrier2 to_write{
                    .srcStageMask = all, .srcAccessMask = vk::AccessFlagBits2::eNone,
                    .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                    .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                    .image = vk::Image(fsr4_linear_image),
                    .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}};
                const vk::MemoryBarrier2 source_ready{
                    .srcStageMask = all, .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &source_ready,
                                         .imageMemoryBarrierCount = 1,
                                         .pImageMemoryBarriers = &to_write});
                const vk::DescriptorImageInfo src{.imageView = color_view,
                                                  .imageLayout = vk::ImageLayout::eGeneral};
                const vk::DescriptorImageInfo dst{.imageView = *fsr4_linear_view,
                                                  .imageLayout = vk::ImageLayout::eGeneral};
                const std::array<vk::WriteDescriptorSet, 2> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &src},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &dst},
                }};
                const u32 unused = 0;
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *fsr4_decode_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute,
                                            *fsr4_decode_pipeline_layout, 0, writes);
                cmdbuf.pushConstants(*fsr4_decode_pipeline_layout,
                                     vk::ShaderStageFlagBits::eCompute, 0, sizeof(unused), &unused);
                cmdbuf.dispatch((source_width + 7) / 8, (source_height + 7) / 8, 1);
                const vk::MemoryBarrier2 decoded{
                    .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                    .dstStageMask = all,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderRead};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &decoded});
                input = {vk::Image(fsr4_linear_image), *fsr4_linear_view, source_width,
                         source_height};
            }
            ok4 = RecordFsr4(cmdbuf, input,
                            {depth_image, depth_view, source_width, source_height}, w, h, ow,
                            oh, frame_ms);
            if (ok4 && fsr4_linear_frame) {
                const vk::MemoryBarrier2 upscaled{
                    .srcStageMask = all, .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderStorageRead |
                                     vk::AccessFlagBits2::eShaderStorageWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &upscaled});
                const vk::DescriptorImageInfo out{.imageView = *output_view,
                                                  .imageLayout = vk::ImageLayout::eGeneral};
                const vk::WriteDescriptorSet write{.dstBinding = 0, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out};
                const u32 unused = 0;
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *fsr4_encode_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute,
                                            *fsr4_encode_pipeline_layout, 0, write);
                cmdbuf.pushConstants(*fsr4_encode_pipeline_layout,
                                     vk::ShaderStageFlagBits::eCompute, 0, sizeof(unused), &unused);
                cmdbuf.dispatch((ow + 7) / 8, (oh + 7) / 8, 1);
                const vk::MemoryBarrier2 encoded{
                    .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .srcAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                    .dstStageMask = all,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &encoded});
            }
            // The game's (encoded) frame, as the output is encoded again by now.
            if (ok4 && mask_ready) {
                RecordFsr4Reactive(cmdbuf, color_view, w, h, ow, oh);
            }
            }
        }
        if (ok4) {
            if (BbSettings::Get().upscaler != BbSettings::UpscalerTaa) {
                ExtraSharpen(vk::Image(output_image), false, ow, oh);
            }
            DebugView(vk::Image(output_image), false, w, h, ow, oh, mask_ready && ReactiveOn());
            barrier(vk::Image(output_image), vk::ImageAspectFlagBits::eColor,
                    vk::ImageLayout::eGeneral, all, rw, vk::ImageLayout::eGeneral,
                    vk::PipelineStageFlagBits2::eBlit, vk::AccessFlagBits2::eTransferRead);
            barrier(vk::Image(ui_image), vk::ImageAspectFlagBits::eColor,
                    vk::ImageLayout::eGeneral, all, rw, vk::ImageLayout::eGeneral,
                    vk::PipelineStageFlagBits2::eBlit, vk::AccessFlagBits2::eTransferWrite);
            const vk::ImageBlit region{
                .srcSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                .srcOffsets = std::array{vk::Offset3D{0, 0, 0},
                                         vk::Offset3D{s32(ow), s32(oh), 1}},
                .dstSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                .dstOffsets = std::array{vk::Offset3D{0, 0, 0},
                                         vk::Offset3D{s32(ow), s32(oh), 1}},
            };
            cmdbuf.blitImage(vk::Image(output_image), vk::ImageLayout::eGeneral,
                             vk::Image(ui_image), vk::ImageLayout::eGeneral, region,
                             vk::Filter::eNearest);
            barrier(vk::Image(ui_image), vk::ImageAspectFlagBits::eColor,
                    vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eBlit,
                    vk::AccessFlagBits2::eTransferWrite, vk::ImageLayout::eGeneral,
                    vk::PipelineStageFlagBits2::eColorAttachmentOutput, color_access);
            reset = false;
            dispatched_last_frame = true;
            if (const int dump = DumpFrame(); dump >= 0) {
                camera_motion.PrintState(dump);
                DumpImages(instance, scheduler, cmdbuf, dump,
                           {{color_image, source_width, source_height, 4, "input", "rgba"},
                            {vk::Image(motion_image), w, h, 4, "motion", "rg16f"},
                            {vk::Image(output_image), ow, oh, 8, "output", "rgba16f"}});
                DumpImages(instance, scheduler, cmdbuf, dump,
                           {{depth_image, source_width, source_height, 4, "depth", "f32",
                             vk::ImageAspectFlagBits::eDepth}});
                if (BbSettings::Get().upscaler == BbSettings::UpscalerTaa &&
                    std::getenv("BB_TAA_DIAGNOSTICS")) {
                    DumpImages(instance, scheduler, cmdbuf, dump,
                               {{vk::Image(taa_history[taa_next]),ow,oh,16,
                                 "previous_history","rgba32f"},
                                {vk::Image(opaque_image),ow,oh,8,"history_sample","rgba16f"}});
                }
                // ObjectMotion's attachment can be in a different resolution from the FSR
                // inputs: only dump it when it matches, to avoid an out-of-bounds GPU copy.
                if (const auto object = camera_motion.ObjectMotionImage(w, h); object) {
                    DumpImages(instance, scheduler, cmdbuf, dump,
                               {{object, w, h, 16, "objects", "rgba32f"}});
                }
            }
        }
        if (ok4 && after_upscale) { // bbport (r98_ambient-particles): before the UI
            after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                           color.info.pixel_format, ow, oh, w, h, jitter, false,
                           "after RunScaled's upscale of the game's finished frame (DLSS, FSR 4, "
                           "XeSS or TAA)"});
        }
        done_this_frame = true;
        if (ok4) {
            ui_phase = true;
            ui_color = ldr_target;
            ui_depth = camera_motion.Depth();
        }
        return;
    }

    const auto& settings = BbSettings::Get();
    FfxVkPortableUpscaleDispatchInfo info{};
    info.structSize = sizeof(info);
    info.color = Describe(color_image, color.info.pixel_format, source_width, source_height,
                          color.usage_flags, vk::ImageAspectFlagBits::eColor,
                          FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
    info.depth = Describe(depth_image, depth_format, source_width, source_height, depth.usage_flags,
                          vk::ImageAspectFlagBits::eDepth,
                          FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
    info.motionVectors = Describe(vk::Image(motion_image), vk::Format::eR16G16Sfloat, w, h,
                                  vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
                                  vk::ImageAspectFlagBits::eColor,
                                  FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
    info.output = Describe(vk::Image(ui_image), vk::Format::eR8G8B8A8Unorm, ow, oh,
                           vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled |
                               vk::ImageUsageFlagBits::eColorAttachment,
                           vk::ImageAspectFlagBits::eColor,
                           FFX_VK_PORTABLE_RESOURCE_STATE_UNORDERED_ACCESS);
    info.exposure.structSize = sizeof(info.exposure);
    info.reactiveMask.structSize = sizeof(info.reactiveMask);
    if (mask_ready && ReactiveOn()) {
        info.reactiveMask = Describe(vk::Image(reactive_image), vk::Format::eR8Unorm, w, h,
            vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
            vk::ImageAspectFlagBits::eColor, FFX_VK_PORTABLE_RESOURCE_STATE_GENERIC_READ);
    }

    info.transparencyAndCompositionMask.structSize = sizeof(info.transparencyAndCompositionMask);
    const float sign = BbToggle::Disabled(1u << 26) ? -1.0f : 1.0f;
    info.jitterOffset = {sign * jitter[0], sign * jitter[1]};
    info.motionVectorScale = {1.0f, 1.0f};
    info.renderSize = {w, h};
    info.outputSize = {ow, oh};
    info.frameTimeMilliseconds = frame_ms;
    info.preExposure = 1.0f;
    info.cameraNear = camera_motion.Near();
    info.cameraFar = 3000.0f;
    info.cameraVerticalFovRadians = camera_motion.VerticalFov();
    info.viewSpaceToMeters = 1.0f;
    info.sharpness = std::min(settings.sharpness.load(), 1.0f);
    info.enableSharpening = settings.sharpen ? VK_TRUE : VK_FALSE;
    info.reset = reset ? VK_TRUE : VK_FALSE;
    info.frameId = frame_id++;

    FfxVkPortableUpscaleCreateInfo create_info{};
    create_info.structSize = sizeof(create_info);
    create_info.maxRenderSize = {w, h};
    create_info.maxOutputSize = {ow, oh};
    // The command buffer is the recording thread's, known when the dispatch is recorded: the
    // check sees a placeholder.
    auto checked = info;
    checked.commandBuffer = reinterpret_cast<VkCommandBuffer>(uintptr_t{1});
    bool ok = false;
    if (const u64 issues = ffxVkPortableValidateUpscaleDispatchInfo(&create_info, &checked)) {
        PrintIssues("scaled dispatch", issues);
        failed = true;
    } else {
        ApplyFsr3Tuning();
        // The context is only used here and destroyed after scheduler.Finish(); a dispatch
        // that fails sets `failed` at the next frame (the UI then draws over this one).
        scheduler.Record([this, ctx = context, info](vk::CommandBuffer cmdbuf) mutable {
            info.commandBuffer = cmdbuf;
            if (ffxVkPortableUpscaleContextRecordDispatch(ctx, &info) != FFX_VK_PORTABLE_OK) {
                std::printf("Upscaler: FSR 3 scaled dispatch failed\n");
                dispatch_failed.store(true, std::memory_order_relaxed);
            }
        });
        ok = true;
        reset = false;
        dispatched_last_frame = true;
        ExtraSharpen(vk::Image(ui_image), true, ow, oh);
        DebugView(vk::Image(ui_image), true, w, h, ow, oh, mask_ready && ReactiveOn());
    }
    barrier(vk::Image(ui_image), vk::ImageAspectFlagBits::eColor, vk::ImageLayout::eGeneral, all,
            rw, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eColorAttachmentOutput,
            color_access);

    if (ok && after_upscale) { // bbport (r98_ambient-particles): before the UI
        after_upscale({UiStorageView(vk::Image(ui_image)), depth_view, color_view,
                       color.info.pixel_format, ow, oh, w, h, jitter, false,
                       "after RunScaled's upscale of the game's finished frame (FSR 3)"});
    }
    done_this_frame = true; // the UI is not jittered
    if (ok) {
        ui_phase = true;
        ui_color = ldr_target;
        ui_depth = camera_motion.Depth();
    }
}

vk::ImageView TemporalUpscaler::Mirror(vk::Image image, std::vector<MirrorView>& views,
                                       vk::Format format, vk::ComponentMapping mapping) {
    for (const auto& entry : views) {
        if (entry.format == format && entry.mapping == mapping) {
            return *entry.view;
        }
    }
    const vk::ImageViewUsageCreateInfo usage{
        .usage = vk::ImageUsageFlagBits::eSampled | vk::ImageUsageFlagBits::eColorAttachment,
    };
    auto view = Check(instance.GetDevice().createImageViewUnique({
        .pNext = &usage,
        .image = image,
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .components = mapping,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    const vk::ImageView handle = *view;
    views.push_back({format, mapping, std::move(view)});
    return handle;
}

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
enum class BottleRedirect : u8 { Fallback = 1, Reserved = 2, Repeated = 4, UiUnavailable = 8 };

static void ReportBottleRedirect(SewerBridge::BottleDisplay& selected, BottleRedirect status,
                                 const char* result, bool display_valid, const TemporalUpscaler::Target& target,
                                 vk::Image image, vk::Format format, u64 tick) {
    const auto bit = u8(status);
    if (selected.redirect_scope_reported & bit) return;
    selected.redirect_scope_reported |= bit;
    fmt::print("[bottle-cut] event=prepared-redirect-scope request={} scene={} frame={} epoch={} address={:x} "
               "outcome={} tick={} display_valid={} image={:x} format={} view={:x} layout={} extent={}x{} "
               "reserved_view={:x} generation={} writer={}\n",
               selected.scene.key.request, selected.scene.key.scene, selected.scene.draw_frame,
               selected.scene.last_epoch, selected.address, result, tick, display_valid, std::bit_cast<u64>(image),
               u32(format), std::bit_cast<u64>(target.view), u32(target.layout), target.width, target.height,
               std::bit_cast<u64>(selected.attachment), selected.target.generation, selected.write);
}

static TemporalUpscaler::Display::BottleScope ReportBottleOverride(
    SewerBridge::BottleDisplay& selected, const char* result, bool display_valid,
    vk::Image image, vk::Format format, u64 tick, VAddr address, u32 frame, u64 load, u64 targets) {
    if (!selected.raw) return {};
    const bool same_scope = selected.address == address && selected.scene.draw_frame == frame &&
        selected.scene.key.load == load && selected.scene.key.target_generation == targets;
    const u8 bit = same_scope ? 1 : 2;
    if (selected.override_scope_reported & bit) return {};
    selected.override_scope_reported |= bit;
    fmt::print("[bottle-cut] event=prepared-override-scope request={} scene={} frame={} epoch={} "
               "address={:x} actual_address={:x} actual_frame={} actual_load={} actual_targets={} "
               "scope_match={} outcome={} tick={} display_valid={} image={:x} format={} view={:x} "
               "generation={} writer={} encoded={:x}\n",
               selected.scene.key.request, selected.scene.key.scene, selected.scene.draw_frame,
               selected.scene.last_epoch, selected.address, address, frame, load, targets, same_scope, result,
               tick, display_valid, std::bit_cast<u64>(image), u32(format), std::bit_cast<u64>(selected.attachment),
               selected.target.generation, selected.write, selected.encoded.load(std::memory_order_acquire));
    if (!same_scope) return {};
    return {selected.scene.key.request, selected.scene.draw_frame, selected.scene.key.scene,
            selected.scene.last_epoch, selected.address};
}
#endif

bool TemporalUpscaler::RedirectColor(VideoCore::ImageId color,
                                     const VideoCore::ImageViewInfo& view_info, Target& target) {
    if (ui_phase && color == ui_color) {
        target = {Mirror(vk::Image(ui_image), ui_views, view_info.format, {}),
                  vk::ImageLayout::eGeneral, ui_width, ui_height, true};
        if (SewerBridgeOpen()) {
            if (sewer_bridge->redirect) sewer_bridge->Stop("missing-issued-ui-before-next-redirect");
            else sewer_bridge->redirect = target.view;
        }
        return true;
    }
    const auto& image = texture_cache.GetImage(color);
    const VAddr address = image.info.guest_address;
    if (!FrameCapture::IsDisplayBuffer(address)) {
        display_redirect = false;
        return false;
    }
    std::scoped_lock lock{display_mutex};
    auto& display = displays[address];
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    auto* observed_bottle = BottlePreparedPending() && bottle_prepared->address == address &&
                            bottle_prepared->raw ? bottle_prepared.get() : nullptr;
    if (display.bottle_epoch) {
        display.bottle_epoch->Cancel();
        display.bottle_epoch.reset();
    }
#endif
    if (display.sewer_epoch) {
        display.sewer_epoch->Cancel();
        display.sewer_epoch->trace->Stop("display-written-or-rebound-after-sample");
        display.sewer_epoch.reset();
    }
    display.sewer_target = vk::ImageView{};
    if (BottleMotion::Run()) {
        if (display.motion && motion_finish && display.motion.id==motion_finish.id) motion_finish={};
        display.motion={};
        display.motion_target=vk::ImageView{};
    }
    if (!display_redirect) {
        display.valid = false; // not upscaled: the presenter shows the guest buffer
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (observed_bottle)
            ReportBottleRedirect(*observed_bottle, BottleRedirect::Fallback, "guest-fallback", display.valid,
                                 {}, vk::Image(display.image), display.format, scheduler.CurrentTick());
#endif
        return false;
    }
    if (!display.image || display.format != image.info.pixel_format ||
        display.width != ui_width || display.height != ui_height) {
        const auto device = instance.GetDevice();
        scheduler.Finish();
        display.views.clear();
        std::printf("Display: host buffer %ux%u (live)\n", ui_width, ui_height);
        display.format = image.info.pixel_format;
        display.width = ui_width;
        display.height = ui_height;
        display.image = VideoCore::UniqueImage(device, instance.GetAllocator());
        display.image.Create(vk::ImageCreateInfo{
            .flags = vk::ImageCreateFlagBits::eMutableFormat,
            .imageType = vk::ImageType::e2D,
            .format = display.format,
            .extent = {ui_width, ui_height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eSampled |
                     vk::ImageUsageFlagBits::eTransferSrc,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        display.views.clear();
        display.sewer_generation = 0;
    }
    scheduler.EndRendering();
    const vk::ImageMemoryBarrier2 b{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eNone,
        .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
        .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
        .oldLayout = vk::ImageLayout::eUndefined,
        .newLayout = vk::ImageLayout::eGeneral,
        .image = vk::Image(display.image),
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    };
#ifdef BB_TEST_SHARED_POST_GRAPH
    const auto post = SewerPostDisplayPending() && sewer_bridge->display_address == address ? sewer_bridge : nullptr;
    if (post) {
        if (!display.sewer_generation) display.sewer_generation = ++sewer_display_generation;
        auto& physical = post->post->terminal.display;
        const auto current = PostPhysical(display.image, display.sewer_generation);
        if (physical.image && physical != current)
            post->post->terminal.Barrier(SewerBridge::LocalEdge::DisplayDiscard).state.store(
                SewerBridge::EdgeState::Repeated, std::memory_order_release);
        if (!physical.image) physical = current;
    }
#endif
    scheduler.Record([b
#ifdef BB_TEST_SHARED_POST_GRAPH
                      , post
#endif
                      ](vk::CommandBuffer cmd) {
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b});
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post) post->post->terminal.Barrier(SewerBridge::LocalEdge::DisplayDiscard).Observe(cmd, b);
#endif
    });
    display.valid = true;
    target = {Mirror(vk::Image(display.image), display.views, view_info.format, {}),
              vk::ImageLayout::eGeneral, ui_width, ui_height};
    if (BottleMotion::Run()) display.motion_target=target.view;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (BottlePreparedPending() && bottle_prepared->address == address && bottle_prepared->ui.Valid()) {
        // Every original redirect of this candidate gets its own epoch, including same-image writes.
        if (bottle_prepared->attachment) {
            bottle_prepared->Cancel();
            if (observed_bottle)
                ReportBottleRedirect(*observed_bottle, BottleRedirect::Repeated, "repeated-cancelled", display.valid,
                                     target, vk::Image(display.image), display.format, scheduler.CurrentTick());
        } else {
            bottle_prepared->attachment = target.view;
            bottle_prepared->target = PostPhysical(display.image, ++bottle_display_generation);
            display.bottle_epoch = bottle_prepared;
            if (observed_bottle)
                ReportBottleRedirect(*observed_bottle, BottleRedirect::Reserved, "epoch-reserved", display.valid,
                                     target, vk::Image(display.image), display.format, scheduler.CurrentTick());
        }
    } else if (observed_bottle) {
        ReportBottleRedirect(*observed_bottle, BottleRedirect::UiUnavailable, "ui-owner-unavailable", display.valid,
                             target, vk::Image(display.image), display.format, scheduler.CurrentTick());
    }
#endif
    if (SewerBridgeOpen() && sewer_bridge->display_address == address) {
        if (!display.sewer_generation) display.sewer_generation = ++sewer_display_generation;
        display.sewer_target = target.view;
    }
    return true;
}

void TemporalUpscaler::MotionIssuedDisplay(VAddr address,vk::ImageView target,
                                           std::span<const vk::DescriptorImageInfo> inputs,bool issued) {
    std::scoped_lock lock{display_mutex};
    const auto got=displays.find(address);
    if (got==displays.end()) {
        if (motion_finish.address==address) motion_finish={};
        return;
    }
    auto& display=got->second;
    // A second draw to this attachment cannot inherit the previous accepted producer.
    display.motion={};
    if (!motion_finish || motion_finish.address!=address) return;
    const auto pending=std::exchange(motion_finish,{});
    u32 sampled=0,ui=0;
    for (const auto& in:inputs) {
        if (!in.imageView) continue;
        ++sampled;
        if (in.imageLayout==vk::ImageLayout::eGeneral &&
            std::ranges::any_of(ui_views,[&](const auto& item){return *item.view==in.imageView;})) ++ui;
    }
    if (!issued || !display.valid || !display_redirect || !target || target!=display.motion_target ||
        display.width!=3840 || display.height!=2160 || vk::Image(ui_image)!=motion_finish_ui ||
        sampled!=1 || ui!=1 || pending.timeline!=scheduler.GetWorkSemaphore()->Handle()) {
        std::printf("[bottle-motion-t198] event=refused id=%u why=actual-display-draw sampled=%u ui=%u\n",
                    u32(pending.id),sampled,ui);
        return;
    }
    display.motion=pending;
    display.motion.image=vk::Image(display.image);
    display.motion.draw_tick=scheduler.CurrentTick();
    display.motion.draw_ns=WorkflowPresent::Now();
    display.motion.write=++motion_display_write;
}

bool TemporalUpscaler::MotionConsume(const BottleMotion::Mark& mark) {
    std::scoped_lock lock{display_mutex};
    const auto found=displays.find(mark.address);
    if (found==displays.end() || !found->second.valid ||
        !BottleMotion::Same(mark,found->second.motion) || vk::Image(found->second.image)!=mark.image) return false;
    found->second.motion={};
    return true;
}

bool TemporalUpscaler::RedirectDepth(VideoCore::ImageId depth, Target& target) {
    if (!ui_phase || depth != ui_depth) {
        return false;
    }
    target = {*ui_depth_view, vk::ImageLayout::eGeneral, ui_width, ui_height, true};
    return true;
}

bool TemporalUpscaler::RedirectSampled(VideoCore::ImageId image,
                                       const VideoCore::ImageViewInfo& info, vk::ImageView& view,
                                       vk::ImageLayout& layout) {
    if (!display_redirect || image != ui_color) {
        return false;
    }
    if (!ui_read_barrier) {
        ui_read_barrier = true;
        scheduler.EndRendering();
        const vk::ImageMemoryBarrier2 b{
            .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
            .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
            .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
            .oldLayout = vk::ImageLayout::eGeneral,
            .newLayout = vk::ImageLayout::eGeneral,
            .image = vk::Image(ui_image),
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
#ifdef BB_TEST_SHARED_POST_GRAPH
        const auto post = SewerPostDisplayPending() && sewer_bridge->ui == b.image &&
            sewer_bridge->ui_allocation == ui_image.allocation &&
            sewer_bridge->ui_generation == sewer_ui_generation ? sewer_bridge : nullptr;
#endif
        scheduler.Record([b
#ifdef BB_TEST_SHARED_POST_GRAPH
                          , post
#endif
                          ](vk::CommandBuffer cmd) {
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b});
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (post) post->post->terminal.Barrier(SewerBridge::LocalEdge::UiSample).Observe(cmd, b);
#endif
        });
    }
    view = Mirror(vk::Image(ui_image), ui_views, info.format, info.mapping);
    layout = vk::ImageLayout::eGeneral;
    return true;
}

bool TemporalUpscaler::DisplayOverride(VAddr address, Display& display, vk::Format view_format) {
    std::scoped_lock lock{display_mutex};
    const auto it = displays.find(address);
    if (it == displays.end() || !it->second.valid) {
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (it != displays.end() && it->second.bottle_epoch)
            display.bottle_scope = ReportBottleOverride(*it->second.bottle_epoch, "guest-fallback", false,
                vk::Image(it->second.image), it->second.format, scheduler.CurrentTick(), address,
                BbStats::frame_number.load(std::memory_order_relaxed), BbEngine::Loading::Generation(),
                scene_targets.Generation());
#endif
        if (SewerBridgeOpen()) sewer_bridge->Stop("ordinary-display-override-fallback");
        return false;
    }
    display = {vk::Image(it->second.image), it->second.format, it->second.width, it->second.height};
    if (BottleMotion::Run()) display.motion=it->second.motion;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (const auto& bottle = it->second.bottle_epoch; bottle && bottle->target.Valid()) {
        const bool same = PostPhysical(it->second.image, bottle->target.generation) == bottle->target;
        display.bottle_scope = ReportBottleOverride(*bottle, same ? "override-bound" : "epoch-rebound", true,
            display.image, display.format, scheduler.CurrentTick(), address,
            BbStats::frame_number.load(std::memory_order_relaxed), BbEngine::Loading::Generation(),
            scene_targets.Generation());
        if (same && bottle->raw) display.bottle_backing_flags = it->second.image.image_ci.flags;
        if (same)
            BottleOfferPrepared(bottle);
        else
            bottle->Cancel();
    }
#endif
    if (it->second.sewer_epoch) {
#ifdef BB_TEST_SHARED_POST_GRAPH
        auto& epoch = *it->second.sewer_epoch;
        if (epoch.trace->post && epoch.trace->post->terminal.display.Valid() &&
            PostPhysical(it->second.image, it->second.sewer_generation) != epoch.trace->post->terminal.display) {
            epoch.Cancel();
            epoch.trace->Stop("shared-post-override-backing");
        } else
#endif
        SewerOffer(it->second.sewer_epoch);
    } else if (SewerBridgeOpen()) sewer_bridge->Stop("display-override-without-issued-source");
    // Diagnostic capture of the actual completed display buffer, including native UI.
    // BB_PRESENT_DUMP_COUNT=N: the trigger dumps N consecutive frames (temporal stability).
    static const char* dump = std::getenv("BB_PRESENT_DUMP_TRIGGER");
    static const int dump_count = [] {
        const char* env = std::getenv("BB_PRESENT_DUMP_COUNT");
        return env ? std::max(1, std::atoi(env)) : 1;
    }();
    static int dump_index = 0;
    static int dump_remaining = 0;
    if (dump && dump_remaining == 0 && (BbTestCamera::OwnsGate() || !BbTestGoto::CaptureHeld(dump)) && !BbTestCamera::CaptureHeld(dump) && std::remove(dump) == 0) {
        dump_remaining = dump_count;
    }
    if (dump_remaining > 0) {
        --dump_remaining;
        scheduler.EndRendering();
        // bbport (r75_present-dump-label): the label names the byte order the presenter reads
        // (its view format: B8G8R8A8 for the game's A8R8G8B8 buffer), not the image's create
        // format (R8G8B8A8, ConvertPixelFormat), which named these BGRA bytes "rgba".
        const bool bgra = view_format == vk::Format::eB8G8R8A8Unorm ||
                          view_format == vk::Format::eB8G8R8A8Srgb;
        PointShadow::NoteColourProbeCapture(address, dump_index, true);
        DumpImages(instance, scheduler, scheduler.CommandBuffer(), dump_index++,
                   {{display.image, display.width, display.height, 4, "present",
                     bgra ? "bgra" : "rgba"}});
    }
    return true;
}

bool TemporalUpscaler::PresentDumpDue() {
    // Diagnostic capture of the actual completed display buffer, including native UI.
    // BB_PRESENT_DUMP_COUNT=N: the trigger dumps N consecutive frames (temporal stability).
    static const char* dump = std::getenv("BB_PRESENT_DUMP_TRIGGER");
    static const int dump_count = [] {
        const char* env = std::getenv("BB_PRESENT_DUMP_COUNT");
        return env ? std::max(1, std::atoi(env)) : 1;
    }();
    if (dump && present_dump_remaining == 0 && (BbTestCamera::OwnsGate() || !BbTestGoto::CaptureHeld(dump)) && !BbTestCamera::CaptureHeld(dump) && std::remove(dump) == 0) {
        present_dump_remaining = dump_count;
    }
    if (present_dump_remaining == 0) {
        return false;
    }
    --present_dump_remaining;
    return true;
}

void TemporalUpscaler::DumpPresented(vk::Image image, u32 width, u32 height, vk::Format format, VAddr address) {
    PointShadow::NoteColourProbeCapture(address, present_dump_index, false);
    scheduler.EndRendering();
    const bool bgra = format == vk::Format::eB8G8R8A8Unorm || format == vk::Format::eB8G8R8A8Srgb;
    DumpImages(instance, scheduler, scheduler.CommandBuffer(), present_dump_index++,
               {{image, width, height, 4, "present", bgra ? "bgra" : "rgba"}});
}

} // namespace Vulkan

namespace Vulkan {

bool TemporalUpscaler::UseFsr4() const {
    const int selected = BbSettings::Get().upscaler;
    if (selected == BbSettings::UpscalerDlss) {
        return dlss && dlss->Available() && !fsr4_failed;
    }
    if (selected == BbSettings::UpscalerXess) {
        return xess && xess->Available() && !fsr4_failed;
    }
    const bool supported = selected == BbSettings::UpscalerFsr      ? instance.IsFsrSdkAvailable()
                           : selected == BbSettings::UpscalerFsr411 ? instance.IsFsr411Available() // the replay or fsr4vk
                                                                    : instance.IsFsr4Int8Supported();
    return BbSettings::IsFsr4(selected) && supported && !fsr4_failed && !fsr4_building;
}

bool TemporalUpscaler::Fsr4TooSlow(float frame_ms) {
    static const bool guard = [] {
        const char* env = std::getenv("BB_FSR4_SLOW_GUARD");
        return !(env && env[0] == '0');
    }();
    const u32 selected = 1u << BbSettings::Get().upscaler.load();
    if (!guard || reset || (slow_guard_used & selected)) {
        slow_window_ms = 0.0f;
        slow_window_frames = slow_frames = 0;
        return false;
    }
    slow_window_ms += frame_ms;
    ++slow_window_frames;
    slow_frames += frame_ms >= 50.0f ? 1 : 0;
    if (slow_window_ms < 5000.0f) {
        return false;
    }
    const bool slow = slow_frames * 10 >= slow_window_frames * 9;
    slow_window_ms = 0.0f;
    slow_window_frames = slow_frames = 0;
    slow_guard_used |= slow ? selected : 0u;
    return slow;
}

bool TemporalUpscaler::RecordFsr4(vk::CommandBuffer cmdbuf, Fsr4Upscaler::Image color,
                                  Fsr4Upscaler::Image depth, u32 w, u32 h, u32 ow, u32 oh,
                                  float frame_ms, bool reactive,
                                  SewerMotion::VendorCapture* sewer_observation) {
    const auto& settings = BbSettings::Get();
    // Same jitter convention as FSR 3; the menu (or toggle 1 << 26) flips it for tests.
    const float sign =
        BbToggle::Disabled(1u << 26) != settings.fsr4_invert_jitter.load() ? -1.0f : 1.0f;
    const bool use_dlss = settings.upscaler == BbSettings::UpscalerDlss && dlss;
    const bool use_xess = settings.upscaler == BbSettings::UpscalerXess && xess;
    const bool vendor = use_dlss || use_xess; // DLSS or XeSS, not the FSR 4 paths
    if (use_dlss && CameraSpeed() > float(w) * 0.5f) {
        reset = true;
    }
    const Fsr4Upscaler::Frame frame{
        .cmdbuf = cmdbuf,
        .color = color,
        .depth = depth,
        .motion = {vk::Image(motion_image), *motion_view, w, h, vk::Format::eR16G16Sfloat},
        .output = {vk::Image(output_image), *output_view, ow, oh,
                   vk::Format::eR16G16B16A16Sfloat},
        .render_width = w,
        .render_height = h,
        .preset = BbSettings::ModelPreset(applied_preset), // Custom: the nearest preset's model
        .jitter = {sign * jitter[0], sign * jitter[1]},
        .frame_ms = frame_ms,
        .near_plane = camera_motion.Near(),
        .far_plane = 3000.0f,
        .vertical_fov = camera_motion.VerticalFov(),
        .sharpness = std::min(settings.sharpness.load(), 1.0f),
        .sharpen = settings.sharpen,
        .reset = reset,
        .auto_exposure = settings.fsr4_auto_exposure,
        .reactive = reactive && vendor
                        ? Fsr4Upscaler::Image{vk::Image(reactive_image), *reactive_view, w, h,
                                              vk::Format::eR8Unorm}
                        : Fsr4Upscaler::Image{},
    };
    if (sewer_observation) {
        sewer_observation->Begin(instance.GetAllocator(), frame, use_dlss, scheduler.CurrentTick(),
                                 output_image.image_ci, settings.dlss_preset.load(std::memory_order_relaxed));
    }
    const bool ok = use_dlss ? dlss->Record(frame) : use_xess ? xess->Record(frame) : fsr4->Record(frame);
    if (sewer_observation) sewer_observation->Finish(frame, use_dlss && ok);
    if (BottleMotion::Run() && BottleMotion::Scene().mark) {
        auto& s=BottleMotion::Scene();
        if (s.vendor_ok || !use_dlss || !ok) {
            BottleMotion::Refuse(s,"actual-dlss-dispatch-failed-fallback-or-duplicate");
        } else {
            s.vendor_ok=true;
        }
    }
    if (ok && !vendor && Fsr4TooSlow(frame_ms)) {
        static const std::string slow =
            "too slow on this GPU (under 20 FPS for 5 s); you can select it again to retry";
        BbSettings::Get().fsr4_problem = slow.c_str();
        const bool to_sdk = settings.upscaler != BbSettings::UpscalerFsr && instance.IsFsrSdkAvailable();
        std::printf("Upscaler: FSR 4 too slow on this GPU (under 20 FPS for 5 s); falling back to %s "
                    "(BB_FSR4_SLOW_GUARD=0 keeps it)\n", to_sdk ? "FSR (AMD FSR SDK)" : "FSR 3.1");
        BbSettings::Get().upscaler = to_sdk ? BbSettings::UpscalerFsr : BbSettings::UpscalerFsr3;
        fsr4_failed = !to_sdk;
        reset = true;
        return ok;
    }
    // The menu shows the reason; it outlives this frame (FSR 4 keeps its last message).
    static std::string shown;
    const char* problem = use_dlss ? dlss->Problem() : use_xess ? xess->Problem() : fsr4->Problem();
    if (!problem) {
        BbSettings::Get().fsr4_problem = nullptr;
    } else if (shown != problem) {
        shown = problem;
        static std::array<std::string, 8> kept;
        static u32 next = 0;
        kept[next] = shown;
        BbSettings::Get().fsr4_problem = kept[next].c_str();
        next = (next + 1) % kept.size();
    }
    if (!ok && !vendor && fsr4->Preparing()) {
        // Its model is being built: FSR 3.1 meanwhile (EnsureResources makes its context next
        // frame), and FSR 4 again when the build is done (the per-frame settings above).
        fsr4_building = true;
        reset = true;
    } else if (!ok && !vendor && fsr4->Fatal() &&
               settings.upscaler == BbSettings::UpscalerFsr411 && instance.IsFsrSdkAvailable()) {
        std::printf("Upscaler: FSR 4.1.1 (fsr4vk) failed; falling back to FSR (AMD FSR SDK)\n");
        BbSettings::Get().upscaler = BbSettings::UpscalerFsr;
        fsr4->ClearFailure();
        reset = true;
    } else if (!ok && !vendor && fsr4->Fatal() &&
               settings.upscaler == BbSettings::UpscalerFsr411 && instance.IsFsr4Int8Supported()) {
        // bbport: FSR 4.1.1 cannot run here (fsr4vk failed on this driver): the built-in FSR 4
        // model next, which needs only the GPU features this one has; FSR 3.1 if that fails too.
        std::printf("Upscaler: FSR 4.1.1 failed; falling back to FSR 4 (built-in model)\n");
        BbSettings::Get().upscaler = BbSettings::UpscalerFsr4;
        fsr4->ClearFailure();
        reset = true;
    } else if (!ok && (use_dlss ? dlss->Fatal() : use_xess ? xess->Fatal() : fsr4->Fatal())) {
        std::printf("Upscaler: falling back to FSR 3.1\n");
        BbSettings::Get().upscaler = BbSettings::UpscalerFsr3;
        fsr4_failed = true; // EnsureResources creates the FSR 3 context next frame
        reset = true;
    }
    return ok;
}

} // namespace Vulkan
