// SPDX-License-Identifier: GPL-2.0-or-later
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_gpu_savings.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/texture_cache/texture_cache.h"
#include "video_core/host_shaders/depth_resample_frag.h"
#include "video_core/host_shaders/depth_stencil_resample_frag.h"
#include "video_core/host_shaders/depth_stencil_bits_frag.h"
#include "video_core/host_shaders/depth_to_color_frag.h"
#include "video_core/host_shaders/fs_tri_vert.h"
#include "bbport_toggles.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#ifdef BB_TEST_SHARED_POST_GRAPH
#include <vk_mem_alloc.h>
#endif

namespace Vulkan {
SceneTargets::SceneTargets(const Instance& i, Scheduler& s, Runtime& r,
                           VideoCore::TextureCache& t)
    : SceneTargets(i, s, r, [&t](VideoCore::ImageId id, u64 uid) {
        return t.TryGetImage(id, uid);
    }) {}
SceneTargets::SceneTargets(const Instance& i, Scheduler& s, Runtime& r, Lookup get)
    : instance{i}, scheduler{s}, runtime{r}, lookup{std::move(get)} {
    runtime.scene_targets = this;
    const char* force = std::getenv("BB_SCENE_STENCIL_BITS");
    force_stencil_bits = force && force[0] == '1';
    CreateResampleResources();
}
SceneTargets::~SceneTargets() {
    scheduler.Finish();
    runtime.scene_targets = nullptr;
}
vk::FormatFeatureFlags SceneTargets::Features(vk::Format format) const {
    // Called for every attachment of every draw: the driver query was ~5% of the GPU thread.
    // Core formats index a flat table; extension formats (large enum values) use the map.
    const auto index = u32(format);
    if (index < format_table.size() && format_known[index]) return format_table[index];
    if (index >= format_table.size()) {
        if (const auto it = format_features.find(format); it != format_features.end()) {
            return it->second;
        }
    }
    const auto features =
        instance.GetPhysicalDevice().getFormatProperties(format).optimalTilingFeatures;
    if (index < format_table.size()) {
        format_table[index] = features;
        format_known[index] = true;
    } else {
        format_features.emplace(format, features);
    }
    return features;
}
bool SceneTargets::Blittable(vk::Format format) const {
    const auto features = Features(format);
    const auto required = vk::FormatFeatureFlagBits::eBlitSrc | vk::FormatFeatureFlagBits::eBlitDst;
    return (features & required) == required;
}
bool SceneTargets::ShaderResampled(const VideoCore::Image& image) const {
    const auto format = image.backing->image.image_ci.format;
    if (!image.info.props.is_depth || (Blittable(format) && !force_stencil_bits)) return false;
    const auto features = Features(format);
    const auto required = vk::FormatFeatureFlagBits::eSampledImage |
                          vk::FormatFeatureFlagBits::eDepthStencilAttachment;
    // Without shader stencil export (e.g. Pascal) depth/stencil stays native: the eight-draw
    // stencil resampler costs too much on such GPUs. BB_SCENE_STENCIL_BITS=1 forces it (tests).
    return (features & required) == required &&
           (!(image.aspect_mask & vk::ImageAspectFlagBits::eStencil) ||
            instance.IsShaderStencilExportSupported() || force_stencil_bits);
}
// 1 for the scene size, 2 for half resolution (the game's post-processing chain), else 0.
// Half resolution needs a scene size that halves exactly: the proxy keeps the scene's factor,
// so the shaders' FragCoord conversion (1920 / scene width) stays correct for it.
static u32 SizeDivisor(const VideoCore::ImageInfo& i, SceneResolution::Size scene) {
    const auto native = SceneResolution::Native();
    if (i.size.width == native.width && i.size.height == native.height) return 1;
    if (i.size.width == native.width / 2 && i.size.height == native.height / 2 && scene.width % 2 == 0 &&
        scene.height % 2 == 0 && !BbToggle::Disabled(BbToggle::SceneHalfRes)) {
        return 2;
    }
    return 0;
}
bool SceneTargets::Eligible(const VideoCore::Image& image) const {
    const auto& i = image.info;
    const u32 div = SizeDivisor(i, size);
    if (!div || i.size.depth != 1 || i.resources.layers != 1 || i.num_samples != 1 ||
        i.props.is_block || !image.backing || image.backing->num_samples != 1) {
        return false;
    }
    if (i.resources.levels != 1) {
        // Mip chains (the bloom pyramid at half resolution): one blitted proxy per level.
        return div == 2 && i.resources.levels <= 16 && !i.props.is_depth &&
               Blittable(image.backing->image.image_ci.format);
    }
    return Blittable(image.backing->image.image_ci.format) || ShaderResampled(image);
}
bool SceneTargets::EligibleScene(const VideoCore::Image& image) const {
    const auto native = SceneResolution::Native();
    return image.info.size.width == native.width && image.info.size.height == native.height && Eligible(image);
}
SceneResolution::Size SceneTargets::ProxySize(const VideoCore::Image& image, u32 level) const {
    const u32 div = std::max(1u, SizeDivisor(image.info, size));
    return {std::max(1u, size.width / div >> level), std::max(1u, size.height / div >> level)};
}
bool SceneTargets::SetSize(SceneResolution::Size next) {
    if (next == size) return false;
    ResolveAll();
    scheduler.Finish();
    entries.clear(); // no command buffer can still reference these images/views
    tracked.clear();
    ++generation;
    recent = {};
    size = next;
    std::printf("Scene resolution: raster %ux%u, half-resolution targets %ux%u, game targets %ux%u "
                "(live)\n", size.width, size.height, size.width / 2, size.height / 2,
                SceneResolution::Native().width, SceneResolution::Native().height);
    return true;
}
void SceneTargets::ResolveAll() {
    for (auto& [key, entry] : entries) {
        if (entry->state.dirty) {
            if (auto* image = lookup(entry->source, entry->uid)) {
                Copy(*entry, *image, true);
                NoteTrip(TripResolve, *image, entry->level, "scene size change (SetSize)",
                         nullptr);
            }
        }
    }
}
bool SceneTargets::NativeStale(const VideoCore::Image& image) const {
    if (!image.scene_proxy) return false;
    const u32 levels = std::min(16u, image.info.resources.levels);
    for (u32 level = 0; level < levels; ++level) {
        const auto it = entries.find(Key(image.image_uid, level));
        if (it != entries.end() && it->second->state.dirty) return true;
    }
    return false;
}
// bbport: the kind of a native access, for the resolve/fill table (NoteTrip).
static const char* NativeUseKind(vk::AccessFlags2 access, vk::ImageLayout layout) {
    using A = vk::AccessFlagBits2;
    if (access & A::eTransferWrite) return "transfer write";
    if (access & A::eTransferRead) return "transfer read";
    if (layout == vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT) return "feedback loop";
    if (access & A::eColorAttachmentWrite) return "color attachment";
    if (access & A::eDepthStencilAttachmentWrite) return "depth attachment";
    if (access & (A::eShaderWrite | A::eShaderStorageWrite)) return "storage or shader write";
    if (access & (A::eShaderRead | A::eShaderSampledRead | A::eShaderStorageRead)) {
        return "shader read";
    }
    return "other";
}
void SceneTargets::NativeAccess(VideoCore::Image& image, vk::AccessFlags2 access,
                                vk::ImageLayout layout) {
    if (copying || !image.scene_proxy) return; // most images never had a proxy
    constexpr auto writes = vk::AccessFlagBits2::eShaderWrite | vk::AccessFlagBits2::eTransferWrite |
        vk::AccessFlagBits2::eColorAttachmentWrite | vk::AccessFlagBits2::eDepthStencilAttachmentWrite |
        vk::AccessFlagBits2::eMemoryWrite;
    const u32 levels = std::min(16u, image.info.resources.levels);
    // bbport (r9_clear): the level window of Runtime::ClearImage, every level otherwise.
    for (u32 level = std::min(levels, native_level_begin);
         level < std::min(levels, native_level_end); ++level) {
        const auto it = entries.find(Key(image.image_uid, level));
        if (it == entries.end()) continue;
        auto& entry = *it->second;
        if (entry.state.dirty) {
            r10_resolves += entry.copy_made ? 1u : 0u; // bbport (r10_proxy_copies)
            r10_source_resolves += entry.copy_source ? 1u : 0u;
            entry.copy_source = false;
            Copy(entry, image, true);
            NoteTrip(TripResolve, image, entry.level, NativeUseKind(access, layout), nullptr);
            if (BbStats::enabled) {
                // BB_FRAME_STATS: what made the native image needed (GpuSavings::Report).
                const u32 kind =
                    access & (vk::AccessFlagBits2::eTransferRead | vk::AccessFlagBits2::eTransferWrite) ? 0
                    : access & (vk::AccessFlagBits2::eShaderWrite | vk::AccessFlagBits2::eShaderStorageWrite) ? 2
                    : access & (vk::AccessFlagBits2::eColorAttachmentWrite |
                                vk::AccessFlagBits2::eDepthStencilAttachmentWrite) ? 3
                    : access & vk::AccessFlagBits2::eShaderRead ? 1
                    : 4;
                GpuSavings::Get().scene_resolves[kind].fetch_add(1, std::memory_order_relaxed);
            }
        }
        if (access & writes) {
            // bbport: a depth attachment in a read-only layout without clears
            // (SceneUse::keep_proxy) declares a write it cannot do: the native image stays the
            // resolve of the proxy and the proxy stays current, so the next reduced pass needs no
            // fill. Experiment bit 1073741824: dropped as before.
            const auto& use = SceneUseScope::current;
            if (use.keep_proxy && !BbToggle::Experiment(1073741824)) {
                if (entry.state.valid) {
                    NoteTrip(TripProxyKept, image, entry.level, NativeUseKind(access, layout),
                             nullptr);
                }
            } else {
                entry.state.NativeWrite();
                entry.dropped_by = use.what ? use.what : "unlabelled native write";
                entry.dropped_how = NativeUseKind(access, layout);
                entry.dropped_hash = use.hash;
            }
        }
    }
}
void SceneTargets::Transition(Entry& e, vk::ImageAspectFlags aspect, vk::ImageLayout layout,
                               vk::PipelineStageFlags2 stages, vk::AccessFlags2 access,
                               bool discard
#ifdef BB_TEST_SHARED_POST_GRAPH
                               , std::shared_ptr<const PostProxyProof::Trace>* post_trace
#endif
                               ) {
    scheduler.EndRendering();
    const vk::ImageMemoryBarrier2 barrier{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
        .dstStageMask = stages, .dstAccessMask = access,
        // discard: all of it is overwritten next (a clear), its contents need not be kept
        .oldLayout = discard ? vk::ImageLayout::eUndefined : e.layout, .newLayout = layout,
        .image = e.image, .subresourceRange = {aspect, 0, 1, 0, 1},
    };
    // bbport (r22_barriers): at a site that set r22_site the barrier is left out when the last
    // barrier of this proxy already covers this access (same layout, only reads declared since:
    // nothing written; its destination holds these stages and accesses: R22Covered) in a layout
    // nothing can write in (transfer source, shader read only), or for ReadNext in General right
    // after another proxy barrier with these destination stages. Else it is recorded in the call of
    // the flush that follows (R22Copy) or in one call with the other proxy's barrier (R22Pair).
    const u32 r22_at = r22_site;
    r22_site = R22None;
    const auto record_own = [&] {
        if (BbStats::enabled) {
            r22_counts.proxy_issued.fetch_add(1, std::memory_order_relaxed);
        }
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post_trace) {
            if (const auto cookie = PostProxyProof::NextCookie()) {
                auto trace = std::make_shared<PostProxyProof::Trace>(PostProxyProof::Order{
                    reinterpret_cast<u64>(&scheduler), std::bit_cast<u64>(instance.GetGraphicsQueue()),
                    std::bit_cast<u64>(scheduler.GetWorkSemaphore()->Handle()), scheduler.CurrentTick(),
                    cookie, instance.GetGraphicsQueueFamilyIndex()});
                *post_trace = trace;
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
                scheduler.RecordNativeWriteSuffix([barrier, trace](vk::CommandBuffer cmd,
                                                      NativeWriteSuffix::Encoder& encoder) {
                    cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
                    if (trace->Commit(cmd, barrier, true)) {
                        encoder.Note(NativeWriteSuffix::Kind::NativeOperation, trace->order.cookie);
                    } else {
                        encoder.Note(NativeWriteSuffix::Kind::UnknownRecord);
                    }
                });
#else
                scheduler.Record([barrier, trace](vk::CommandBuffer cmd) {
                    cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
                    trace->Commit(cmd, barrier, false);
                });
#endif
                return;
            }
        }
#endif
        scheduler.Record([barrier](vk::CommandBuffer cmd) {
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
        });
    };
    if (r22_at == R22None) {
        record_own();
    } else {
        const bool unwritable = layout == vk::ImageLayout::eTransferSrcOptimal ||
                                layout == vk::ImageLayout::eShaderReadOnlyOptimal;
        const bool after_barrier =
            r22_at == R22EffectRead && layout == vk::ImageLayout::eGeneral && r22_last_dst &&
            (bool(r22_last_dst & vk::PipelineStageFlagBits2::eAllCommands) ||
             !(stages & ~r22_last_dst));
        if (!discard && e.layout == layout && (unwritable || after_barrier) &&
            R22Covered(e.r22_stages, e.r22_access, stages, access)) {
            auto& skipped = r22_at == R22Copy   ? r22_counts.proxy_skipped_resolve
                            : r22_at == R22Pair ? r22_counts.proxy_skipped_copy
                                                : r22_counts.proxy_skipped_read;
            if (BbStats::enabled) {
                skipped.fetch_add(1, std::memory_order_relaxed);
            }
            return; // the layout and the covering destination stay those of its last barrier
        }
        if (r22_at == R22Copy) {
            runtime.QueueImageBarrier(barrier);
            if (BbStats::enabled) {
                r22_counts.proxy_merged_flush.fetch_add(1, std::memory_order_relaxed);
            }
        } else if (r22_at == R22Pair && r22_pair_count < r22_pair.size()) {
            r22_pair[r22_pair_count++] = barrier;
        } else {
            record_own();
        }
    }
    r22_last_dst = stages;
    e.r22_stages = stages;
    e.r22_access = access;
    e.layout = layout;
}
void SceneTargets::Copy(Entry& e, VideoCore::Image& original, bool to_native) {
    copying = true;
    scheduler.EndRendering();
    const Runtime::TransferMark mark{runtime, to_native ? "scene proxy resolve" : "scene proxy fill",
                                     original};
    if (debug) {
        std::printf("Scene %s: %s %ux%u level %u\n", to_native ? "resolve" : "fill",
                    vk::to_string(original.info.pixel_format).c_str(), original.info.size.width,
                    original.info.size.height, e.level);
    }
    const vk::Image src = to_native ? vk::Image(e.image) : original.GetImage();
    const vk::Image dst = to_native ? original.GetImage() : vk::Image(e.image);
    if (ShaderResampled(original)) {
        constexpr auto read_layout = vk::ImageLayout::eShaderReadOnlyOptimal;
        constexpr auto write_layout = vk::ImageLayout::eDepthStencilAttachmentOptimal;
        constexpr auto read_stage = vk::PipelineStageFlagBits2::eFragmentShader;
        constexpr auto write_stage = vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                     vk::PipelineStageFlagBits2::eLateFragmentTests;
        constexpr auto read_access = vk::AccessFlagBits2::eShaderSampledRead;
        constexpr auto write_access = vk::AccessFlagBits2::eDepthStencilAttachmentRead |
                                      vk::AccessFlagBits2::eDepthStencilAttachmentWrite;
        runtime.Transit(&original, to_native ? write_layout : read_layout,
                        to_native ? write_stage : read_stage,
                        to_native ? write_access : read_access);
        // bbport (r22_barriers): the proxy's barrier in the flush's call (R22Copy, see below).
        const bool r22_merge = !BbToggle::Experiment(R22BarriersOffBit);
        if (!r22_merge) {
            runtime.FlushBarriers();
        }
        r22_site = r22_merge ? R22Copy : R22None;
        Transition(e, original.aspect_mask, to_native ? read_layout : write_layout,
                   to_native ? read_stage : write_stage, to_native ? read_access : write_access);
        if (r22_merge) {
            runtime.FlushBarriers();
        }
        const auto& proxy = e.image.image_ci.extent;
        Resample(src, dst, original,
                 to_native ? vk::Extent2D{original.info.size.width, original.info.size.height}
                           : vk::Extent2D{proxy.width, proxy.height});
        // (Depth proxies are single-level: Eligible.)
        if (to_native) e.state.Resolved(); else e.state.CopiedToProxy();
        copying = false;
        return;
    }
    const VideoCore::SubresourceRange level_range{.base = {e.level, 0}, .extent = {1, 1}};
    runtime.Transit(&original, to_native ? vk::ImageLayout::eTransferDstOptimal
                                       : vk::ImageLayout::eTransferSrcOptimal,
                    vk::PipelineStageFlagBits2::eTransfer,
                    to_native ? vk::AccessFlagBits2::eTransferWrite : vk::AccessFlagBits2::eTransferRead,
                    level_range);
    // bbport (r22_barriers): the proxy's barrier is recorded in the call of the flush (nothing
    // is recorded between them, and they are barriers of different images), and left out for a
    // resolve whose proxy is still in the transfer source layout of its last barrier (Transition).
    // Experiment 140737488355328 set: the flush, then the proxy's barrier in a call of its own.
    const bool r22_merge = !BbToggle::Experiment(R22BarriersOffBit);
    if (!r22_merge) {
        runtime.FlushBarriers();
    }
    r22_site = r22_merge ? R22Copy : R22None;
    Transition(e, original.aspect_mask,
               to_native ? vk::ImageLayout::eTransferSrcOptimal : vk::ImageLayout::eTransferDstOptimal,
               vk::PipelineStageFlagBits2::eTransfer,
               to_native ? vk::AccessFlagBits2::eTransferRead : vk::AccessFlagBits2::eTransferWrite);
    if (r22_merge) {
        runtime.FlushBarriers();
    }
    const vk::Offset3D native{s32(std::max(1u, original.info.size.width >> e.level)),
                              s32(std::max(1u, original.info.size.height >> e.level)), 1};
    const vk::Offset3D reduced{s32(e.image.image_ci.extent.width),
                               s32(e.image.image_ci.extent.height), 1};
    // bbport: a resolve of color is a bilinear upscale where the format filters linearly (never
    // integer formats): native-size passes after the upscaler read these images (effects,
    // post-processing), and nearest made them blocky. Fills to the proxy and depth/stencil stay
    // nearest. BB_SCENE_LINEAR_RESOLVE=0 (or experiment bit 1): nearest throughout, as before.
    static const bool linear_resolve = [] {
        const char* env = std::getenv("BB_SCENE_LINEAR_RESOLVE");
        return !(env && env[0] == '0');
    }();
    const bool linear =
        linear_resolve && !BbToggle::Experiment(2) && to_native &&
        original.aspect_mask == vk::ImageAspectFlags{vk::ImageAspectFlagBits::eColor} &&
        bool(Features(original.backing->image.image_ci.format) &
             vk::FormatFeatureFlagBits::eSampledImageFilterLinear);
    for (auto aspect : {vk::ImageAspectFlagBits::eColor, vk::ImageAspectFlagBits::eDepth,
                        vk::ImageAspectFlagBits::eStencil}) {
        if (!(original.aspect_mask & aspect)) continue;
        const vk::ImageBlit region{
            .srcSubresource = {aspect, to_native ? 0u : e.level, 0, 1},
            .srcOffsets = std::array{vk::Offset3D{}, to_native ? reduced : native},
            .dstSubresource = {aspect, to_native ? e.level : 0u, 0, 1},
            .dstOffsets = std::array{vk::Offset3D{}, to_native ? native : reduced},
        };
        // Nearest preserves depth/stencil and avoids assuming linear blit support for
        // integer G-buffer formats. FSR reconstructs color at the HDR scene boundary.
        const vk::Filter filter = linear ? vk::Filter::eLinear : vk::Filter::eNearest;
        scheduler.Record([src,dst,region,filter](vk::CommandBuffer cmd) {
            cmd.blitImage(src, vk::ImageLayout::eTransferSrcOptimal, dst,
                          vk::ImageLayout::eTransferDstOptimal, region, filter);
        });
    }
    if (to_native) e.state.Resolved(); else e.state.CopiedToProxy();
    copying = false;
}
void SceneTargets::Resample(vk::Image src, vk::Image dst, const VideoCore::Image& original,
                            vk::Extent2D dst_size) {
    const auto device = instance.GetDevice();
    const auto format = original.backing->image.image_ci.format;
    const bool stencil = bool(original.aspect_mask & vk::ImageAspectFlagBits::eStencil);
    const bool stencil_bits = stencil && !depth_stencil_frag;
    const auto make_view = [&](vk::Image image, vk::ImageAspectFlags aspect,
                               vk::ImageUsageFlags usage) {
        const vk::ImageViewUsageCreateInfo usage_ci{.usage = usage};
        return Check(device.createImageView({
            .pNext = &usage_ci, .image = image, .viewType = vk::ImageViewType::e2D,
            .format = format, .subresourceRange = {aspect, 0, 1, 0, 1},
        }));
    };
    const auto depth_view = make_view(src, vk::ImageAspectFlagBits::eDepth,
                                      vk::ImageUsageFlagBits::eSampled);
    const auto stencil_view = stencil ? make_view(src, vk::ImageAspectFlagBits::eStencil,
                                                  vk::ImageUsageFlagBits::eSampled)
                                      : vk::ImageView{};
    const auto target_view = make_view(dst, original.aspect_mask,
                                       vk::ImageUsageFlagBits::eDepthStencilAttachment);
    scheduler.DeferOperation([device, depth_view, stencil_view, target_view] {
        device.destroyImageView(depth_view);
        if (stencil_view) device.destroyImageView(stencil_view);
        device.destroyImageView(target_view);
    });
    const auto pipeline = ResamplePipeline(format, stencil);
    const auto layout = *resample_layout;
    scheduler.RecordCrumb({.name = "scene resample"}, [=](vk::CommandBuffer cmd) {
        const vk::RenderingAttachmentInfo attachment{
            .imageView = target_view,
            .imageLayout = vk::ImageLayout::eDepthStencilAttachmentOptimal,
            .loadOp = vk::AttachmentLoadOp::eDontCare,
            .storeOp = vk::AttachmentStoreOp::eStore,
        };
        auto stencil_attachment = attachment;
        if (stencil_bits) {
            stencil_attachment.loadOp = vk::AttachmentLoadOp::eClear;
            stencil_attachment.clearValue.depthStencil = vk::ClearDepthStencilValue{0.f, 0};
        }
        cmd.beginRendering({
            .renderArea = {{0, 0}, dst_size}, .layerCount = 1,
            .pDepthAttachment = &attachment,
            .pStencilAttachment = stencil ? &stencil_attachment : nullptr,
        });
        const std::array infos{
            vk::DescriptorImageInfo{{}, depth_view, vk::ImageLayout::eShaderReadOnlyOptimal},
            vk::DescriptorImageInfo{{}, stencil_view, vk::ImageLayout::eShaderReadOnlyOptimal},
        };
        const std::array writes{
            vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                   .descriptorType = vk::DescriptorType::eSampledImage,
                                   .pImageInfo = &infos[0]},
            vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                   .descriptorType = vk::DescriptorType::eSampledImage,
                                   .pImageInfo = &infos[1]},
        };
        cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eGraphics, layout, 0,
                                 vk::ArrayProxy<const vk::WriteDescriptorSet>(
                                     stencil ? 2u : 1u, writes.data()));
        cmd.bindPipeline(vk::PipelineBindPoint::eGraphics, pipeline);
        cmd.setViewportWithCount(vk::Viewport{0.f, 0.f, float(dst_size.width),
                                              float(dst_size.height), 0.f, 1.f});
        cmd.setScissorWithCount(vk::Rect2D{{0, 0}, dst_size});
        if (stencil_bits) {
            // Copy depth first, then reconstruct all eight stencil bits without needing
            // VK_EXT_shader_stencil_export (e.g. Pascal). Discard keeps unset bits clear.
            for (u32 bit : {0u, 1u, 2u, 4u, 8u, 16u, 32u, 64u, 128u}) {
                cmd.pushConstants(layout, vk::ShaderStageFlagBits::eFragment, 0, sizeof(bit), &bit);
                cmd.setStencilWriteMask(vk::StencilFaceFlagBits::eFrontAndBack, bit);
                cmd.setStencilReference(vk::StencilFaceFlagBits::eFrontAndBack, bit);
                cmd.draw(3, 1, 0, 0);
            }
        } else {
            cmd.draw(3, 1, 0, 0);
        }
        cmd.endRendering();
    });
    // The guest pipelines' dynamic state must be emitted again after this pipeline.
    scheduler.GetDynamicState().Invalidate();
}
void SceneTargets::CreateResampleResources() {
    const auto device = instance.GetDevice();
    fs_tri_vert = vk::UniqueShaderModule(CompileSPV(FS_TRI_VERT, device), device);
    depth_frag = vk::UniqueShaderModule(CompileSPV(DEPTH_RESAMPLE_FRAG, device), device);
    if (instance.IsShaderStencilExportSupported() && !force_stencil_bits) {
        depth_stencil_frag =
            vk::UniqueShaderModule(CompileSPV(DEPTH_STENCIL_RESAMPLE_FRAG, device), device);
    }
    if (!depth_stencil_frag) {
        stencil_bits_frag =
            vk::UniqueShaderModule(CompileSPV(DEPTH_STENCIL_BITS_FRAG, device), device);
    }
    const std::array bindings{
        vk::DescriptorSetLayoutBinding{0, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eFragment},
        vk::DescriptorSetLayoutBinding{1, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eFragment},
    };
    resample_set_layout = Check(device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = u32(bindings.size()), .pBindings = bindings.data(),
    }));
    const auto set_layout = *resample_set_layout;
    const vk::PushConstantRange push{vk::ShaderStageFlagBits::eFragment, 0, sizeof(u32)};
    resample_layout = Check(device.createPipelineLayoutUnique({
        .setLayoutCount = 1, .pSetLayouts = &set_layout,
        .pushConstantRangeCount = 1, .pPushConstantRanges = &push,
    }));
}
vk::Pipeline SceneTargets::ResamplePipeline(vk::Format format, bool stencil) {
    const bool stencil_bits = stencil && !depth_stencil_frag;
    const std::pair key{format, stencil};
    for (const auto& [k, pipeline] : resample_pipelines) if (k == key) return *pipeline;
    const vk::PipelineInputAssemblyStateCreateInfo input_assembly{
        .topology = vk::PrimitiveTopology::eTriangleList,
    };
    const vk::PipelineMultisampleStateCreateInfo multisampling{
        .rasterizationSamples = vk::SampleCountFlagBits::e1,
    };
    // Reference, compare and write masks are static; the exported value replaces the reference.
    const vk::StencilOpState stencil_op{
        .failOp = vk::StencilOp::eReplace, .passOp = vk::StencilOp::eReplace,
        .depthFailOp = vk::StencilOp::eReplace, .compareOp = vk::CompareOp::eAlways,
        .compareMask = 0xff, .writeMask = 0xff, .reference = 0,
    };
    const vk::PipelineDepthStencilStateCreateInfo depth_state{
        .depthTestEnable = true, .depthWriteEnable = true,
        .depthCompareOp = vk::CompareOp::eAlways,
        .stencilTestEnable = stencil, .front = stencil_op, .back = stencil_op,
    };
    const std::array dynamic_states{vk::DynamicState::eViewportWithCount,
                                    vk::DynamicState::eScissorWithCount,
                                    vk::DynamicState::eStencilWriteMask,
                                    vk::DynamicState::eStencilReference};
    const vk::PipelineDynamicStateCreateInfo dynamic_info{
        .dynamicStateCount = stencil_bits ? 4u : 2u, .pDynamicStates = dynamic_states.data(),
    };
    const std::array stages{
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eVertex,
                                          .module = *fs_tri_vert, .pName = "main"},
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eFragment,
                                          .module = stencil ? (stencil_bits ? *stencil_bits_frag :
                                                             *depth_stencil_frag) : *depth_frag,
                                          .pName = "main"},
    };
    const vk::PipelineRenderingCreateInfo rendering{
        .depthAttachmentFormat = format,
        .stencilAttachmentFormat = stencil ? format : vk::Format::eUndefined,
    };
    const vk::PipelineColorBlendStateCreateInfo color_blending{};
    const vk::PipelineViewportStateCreateInfo viewport_info{};
    const vk::PipelineVertexInputStateCreateInfo vertex_input{};
    const vk::PipelineRasterizationStateCreateInfo raster{.lineWidth = 1.f};
    auto pipeline = Check(instance.GetDevice().createGraphicsPipelineUnique(VK_NULL_HANDLE, {
        .pNext = &rendering, .stageCount = u32(stages.size()), .pStages = stages.data(),
        .pVertexInputState = &vertex_input, .pInputAssemblyState = &input_assembly,
        .pViewportState = &viewport_info, .pRasterizationState = &raster,
        .pMultisampleState = &multisampling, .pDepthStencilState = &depth_state,
        .pColorBlendState = &color_blending, .pDynamicState = &dynamic_info,
        .layout = *resample_layout,
    }));
    const auto result = *pipeline;
    resample_pipelines.emplace_back(key, std::move(pipeline));
    return result;
}
// bbport: the game copies its depth block into an R32F texture of the depth's size once a frame
// (vk_shader_hle.cpp, DepthBlockCopy). With reduced targets the current depth is the proxy's,
// and the image copy needed the native depth: the proxy was resolved first (the scene proxy
// resolve) and the whole native image copied (~1.0 ms at 3840x2160), for a texture that holds
// the proxy upscaled by nearest anyway. Here the texture is drawn from the proxy with the
// resolve's mapping (depth_to_color.frag, as depth_resample.frag), and the native depth stays
// unresolved until something needs it. Only for a proxy that is dirty: its native image would be
// exactly its upscale. After a fill (the native image written at full size, CopiedToProxy) the
// proxy is a reduction of it, and copying the native image keeps the detail.
SceneTargets::SewerProxy SceneTargets::InspectSewerProxy(VideoCore::ImageId id, u64 uid,
                                                         vk::ImageView view) const {
    const auto it = entries.find(Key(uid, 0));
    if (!Reduced() || it == entries.end()) return {};
    const auto& e = *it->second;
    const auto* parent = lookup(id, uid);
    if (!parent || parent->image_uid != uid || parent->binding.needs_rebind ||
        !parent->backing || e.source != id || e.uid != uid || e.level != 0 || !e.image.image ||
        parent->info.resources != VideoCore::SubresourceExtent{1, 1}) return {};
    const auto& ci = e.image.image_ci;
    if (ci.imageType != vk::ImageType::e2D || ci.mipLevels != 1 || ci.arrayLayers != 1 ||
        ci.samples != vk::SampleCountFlagBits::e1 || ci.extent.depth != 1) return {};
    if (view && !std::ranges::any_of(e.views, [view](const auto& pair) {
            return *pair.second == view && pair.first.range.base.level == 0 &&
                   pair.first.range.base.layer == 0;
        })) return {};
    SewerProxy result{{e.image, view, e.layout, ci.usage}, ci.extent, ci.format,
                      parent->aspect_mask, e.state.valid, e.state.dirty};
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    result.incarnation = e.post_proxy_incarnation;
#endif
    return result;
}

bool SceneTargets::CanCopyDepthProxyToColor(const VideoCore::Image& depth,
                                            const VideoCore::Image& dst) {
    if (copying || !Reduced() || !depth.scene_proxy || !depth.info.props.is_depth ||
        !depth.backing || !dst.backing || depth.info.num_samples != 1 ||
        depth.info.resources != VideoCore::SubresourceExtent{1, 1}) {
        return false;
    }
    const auto it = entries.find(Key(depth.image_uid, 0));
    if (it == entries.end()) {
        return false;
    }
    const Entry& e = *it->second;
    const auto& proxy = e.image.image_ci;
    if (!e.state.valid || !e.state.dirty || e.level != 0 || !e.image.image ||
        (proxy.format != vk::Format::eD32SfloatS8Uint && proxy.format != vk::Format::eD32Sfloat) ||
        proxy.samples != vk::SampleCountFlagBits::e1 ||
        !(proxy.usage & vk::ImageUsageFlagBits::eSampled) ||
        !(Features(proxy.format) & vk::FormatFeatureFlagBits::eSampledImage)) {
        return false;
    }
    const auto& ci = dst.backing->image.image_ci;
    if (dst.info.props.is_depth || dst.info.pixel_format != vk::Format::eR32Sfloat ||
        ci.format != vk::Format::eR32Sfloat || ci.imageType != vk::ImageType::e2D ||
        ci.samples != vk::SampleCountFlagBits::e1 || dst.backing->num_samples != 1 ||
        dst.info.num_samples != 1 || ci.mipLevels != 1 || ci.arrayLayers != 1 ||
        dst.info.resources != VideoCore::SubresourceExtent{1, 1} ||
        dst.info.size != depth.info.size || ci.extent.width != dst.info.size.width ||
        ci.extent.height != dst.info.size.height ||
        !(ci.usage & vk::ImageUsageFlagBits::eColorAttachment) ||
        !(Features(vk::Format::eR32Sfloat) & vk::FormatFeatureFlagBits::eColorAttachment)) {
        return false;
    }
    return bool(DepthToColorPipeline());
}
bool SceneTargets::CopyDepthProxyToColor(VideoCore::Image& depth, VideoCore::Image& dst,
                                          SewerCopyViews* sewer_views) {
    if (!CanCopyDepthProxyToColor(depth, dst)) {
        return false;
    }
    auto& e = *entries.find(Key(depth.image_uid, 0))->second;
    scheduler.EndRendering();
    // The texture is written as by an image copy: Transit tracks its layout and counts the
    // write (write_seq); a proxy of its own is resolved or dropped there (NativeAccess). The
    // native depth is not touched: an access to it would resolve the proxy.
    runtime.SetBackingSamples(&dst, dst.info.num_samples, false);
    if (runtime.Transit(&dst, vk::ImageLayout::eColorAttachmentOptimal,
                        vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                        vk::AccessFlagBits2::eColorAttachmentWrite)) {
        runtime.FlushBarriers();
    }
    constexpr auto read_layout = vk::ImageLayout::eShaderReadOnlyOptimal;
    if (e.layout != read_layout) {
        Transition(e, depth.aspect_mask, read_layout, vk::PipelineStageFlagBits2::eFragmentShader,
                   vk::AccessFlagBits2::eShaderSampledRead);
    }
    const auto device = instance.GetDevice();
    const vk::ImageViewUsageCreateInfo sampled_usage{.usage = vk::ImageUsageFlagBits::eSampled};
    const auto depth_view = Check(device.createImageView({
        .pNext = &sampled_usage, .image = e.image, .viewType = vk::ImageViewType::e2D,
        .format = e.image.image_ci.format,
        .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
    }));
    const vk::ImageViewUsageCreateInfo attachment_usage{
        .usage = vk::ImageUsageFlagBits::eColorAttachment};
    const auto target_view = Check(device.createImageView({
        .pNext = &attachment_usage, .image = dst.GetImage(), .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR32Sfloat,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    if (sewer_views) *sewer_views = {depth_view, target_view};
    scheduler.DeferOperation([device, depth_view, target_view] {
        device.destroyImageView(depth_view);
        device.destroyImageView(target_view);
    });
    const vk::Extent2D dst_size{dst.info.size.width, dst.info.size.height};
    const auto pipeline = DepthToColorPipeline();
    const auto layout = *resample_layout;
    scheduler.RecordCrumb({.name = "depth proxy to color"}, [=](vk::CommandBuffer cmd) {
        const vk::RenderingAttachmentInfo attachment{
            .imageView = target_view,
            .imageLayout = vk::ImageLayout::eColorAttachmentOptimal,
            .loadOp = vk::AttachmentLoadOp::eDontCare,
            .storeOp = vk::AttachmentStoreOp::eStore,
        };
        cmd.beginRendering({
            .renderArea = {{0, 0}, dst_size}, .layerCount = 1,
            .colorAttachmentCount = 1, .pColorAttachments = &attachment,
        });
        const vk::DescriptorImageInfo info{{}, depth_view, read_layout};
        const vk::WriteDescriptorSet write{.dstBinding = 0, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eSampledImage,
                                           .pImageInfo = &info};
        cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eGraphics, layout, 0, write);
        cmd.bindPipeline(vk::PipelineBindPoint::eGraphics, pipeline);
        cmd.setViewportWithCount(vk::Viewport{0.f, 0.f, float(dst_size.width),
                                              float(dst_size.height), 0.f, 1.f});
        cmd.setScissorWithCount(vk::Rect2D{{0, 0}, dst_size});
        cmd.draw(3, 1, 0, 0);
        cmd.endRendering();
    });
    // The guest pipelines' dynamic state must be emitted again after this pipeline.
    scheduler.GetDynamicState().Invalidate();
    // As Runtime::CopyImage leaves the destination of a copy.
    dst.flags |= (depth.flags & VideoCore::ImageFlagBits::GpuModified);
    dst.flags &= ~VideoCore::ImageFlagBits::Dirty;
    return true;
}
// bbport: the game's render-target copy shader (vk_shader_hle.cpp) copies whole targets. With a
// dirty source proxy the native copy needed a resolve of the source to the native size, a resolve
// of the destination's own dirty proxy that the copy then overwrote, a copy at the native size,
// and a fill back to the proxy when the destination was drawn reduced again. Between the proxies
// it is one copy at the reduced size. A later native reader of the destination resolves its
// proxy: the same upscale of the same contents the native copy carried.
// bbport: the reason a render-target copy is not done between the proxies goes into the
// resolve/fill table (NoteTrip): those copies resolve a dirty source to the native size first.
const char* SceneTargets::ProxyCopyBlocker(const VideoCore::Image& src,
                                           const VideoCore::Image& dst) const {
    const char* why = ProxyCopyBlockerWhy(src, dst);
    if (why && !copying && Reduced()) {
        NoteTrip(TripCopyRefused, src, 0, why, nullptr);
    }
    return why;
}
const char* SceneTargets::ProxyCopyBlockerWhy(const VideoCore::Image& src,
                                              const VideoCore::Image& dst) const {
    if (copying || !Reduced()) {
        return "native scene size";
    }
    if (!src.scene_proxy) {
        return "source without proxy";
    }
    if (!dst.scene_proxy) {
        return "destination without proxy";
    }
    const vk::ImageAspectFlags color{vk::ImageAspectFlagBits::eColor};
    if (src.info.props.is_depth || dst.info.props.is_depth || !(src.aspect_mask == color) ||
        !(dst.aspect_mask == color)) {
        return "not color";
    }
    if (!src.backing || !dst.backing || src.info.num_samples != 1 || dst.info.num_samples != 1 ||
        src.backing->num_samples != 1 || dst.backing->num_samples != 1 ||
        src.info.resources != VideoCore::SubresourceExtent{1, 1} ||
        dst.info.resources != VideoCore::SubresourceExtent{1, 1}) {
        return "not one sample, level and layer";
    }
    if (src.info.pixel_format != dst.info.pixel_format ||
        src.backing->image.image_ci.format != dst.backing->image.image_ci.format ||
        src.info.size != dst.info.size) {
        return "format or size differs";
    }
    const auto s = entries.find(Key(src.image_uid, 0));
    const auto d = entries.find(Key(dst.image_uid, 0));
    if (s == entries.end() || d == entries.end()) {
        return "no proxy of level 0";
    }
    const Entry& se = *s->second;
    const Entry& de = *d->second;
    if (!se.state.valid || !se.state.dirty) {
        return "source proxy not newer than its native image";
    }
    const auto& sc = se.image.image_ci;
    const auto& dc = de.image.image_ci;
    if (!se.image.image || !de.image.image || se.level != 0 || de.level != 0 ||
        sc.format != dc.format || sc.extent.width != dc.extent.width ||
        sc.extent.height != dc.extent.height || sc.mipLevels != 1 || dc.mipLevels != 1 ||
        !(sc.usage & vk::ImageUsageFlagBits::eTransferSrc) ||
        !(dc.usage & vk::ImageUsageFlagBits::eTransferDst)) {
        return "proxies differ";
    }
    return nullptr;
}
// bbport (r10_proxy_copies): the game copies scene targets the scene phase drew at the reduced
// size (dirty proxies) into images it never draws to, so those had no proxy ("destination without
// proxy") and every such copy resolved its source to the native size and copied at the native
// size. The destination gets a proxy here, created like Get's but not filled (the copy overwrites
// all of it; the barrier discards its undefined contents). Its native image becomes the resolve of
// that proxy, made only when a native reader needs it: Copy's linear blit of the texels the source
// resolve blitted before, so native readers read the same bytes. Normalized samplers read the
// proxy, as for every proxied scene target (SampleSceneProxies).
// Experiment bit 34359738368: no proxy is made; a copy into one made before stays native.
const char* SceneTargets::ProxyForCopy(const VideoCore::Image& src, VideoCore::Image& dst,
                                       VideoCore::ImageId dst_id) {
    if (copying || !Reduced()) {
        return nullptr;
    }
    const bool old_way = BbToggle::Experiment(34359738368ull);
    if (old_way != r10_old_way) { // one behaviour per counter window (A/B switch)
        r10_old_way = old_way;
        r10_calls = r10_made = r10_other = r10_no_source = r10_not_eligible = r10_copies =
            r10_resolves = r10_source_resolves = r10_samples = 0;
    }
    const char* refuse = nullptr;
    const auto d = entries.find(Key(dst.image_uid, 0));
    const auto s = src.scene_proxy ? entries.find(Key(src.image_uid, 0)) : entries.end();
    const vk::ImageAspectFlags color{vk::ImageAspectFlagBits::eColor};
    ++r10_calls;
    if (d != entries.end()) {
        if (!d->second->copy_made) {
            ++r10_other;
        } else if (old_way) {
            refuse = "experiment mask 34359738368 (proxy made for copies)";
        }
    } else if (s == entries.end() || !s->second->state.valid || !s->second->state.dirty) {
        ++r10_no_source;
    } else if (!Eligible(dst) || !src.backing || src.info.props.is_depth ||
               // a CPU-written source is uploaded next and loses its proxy: the copy goes native
               True(src.flags & VideoCore::ImageFlagBits::CpuDirty) ||
               dst.info.props.is_depth || !(src.aspect_mask == color) ||
               !(dst.aspect_mask == color) || src.info.num_samples != 1 ||
               src.backing->num_samples != 1 ||
               src.info.resources != VideoCore::SubresourceExtent{1, 1} ||
               dst.info.resources != VideoCore::SubresourceExtent{1, 1} ||
               src.info.pixel_format != dst.info.pixel_format ||
               src.backing->image.image_ci.format != dst.backing->image.image_ci.format ||
               src.info.size != dst.info.size ||
               !(dst.backing->image.image_ci.usage & vk::ImageUsageFlagBits::eTransferDst)) {
        ++r10_not_eligible;
    } else {
        ++r10_made;
        if (!old_way) {
            DropForgotten();
            auto& entry = entries[Key(dst.image_uid, 0)];
            entry = std::make_unique<Entry>();
            entry->source = dst_id;
            entry->uid = dst.image_uid;
            entry->level = 0;
            entry->image = VideoCore::UniqueImage(instance.GetDevice(), instance.GetAllocator());
            auto ci = dst.backing->image.image_ci;
            ci.pNext = nullptr;
            const auto proxy = ProxySize(dst, 0);
            ci.extent = vk::Extent3D{proxy.width, proxy.height, 1};
            ci.mipLevels = 1;
            entry->image.Create(ci);
            entry->copy_made = true;
            entry->dropped_by = "render-target copy into a proxy made for it (r10)";
            entry->dropped_how = "proxy made for a copy";
            dst.scene_proxy = true;
            tracked.insert(dst.image_uid);
        }
    }
    if (r10_calls >= 4096) {
        u32 live = 0;
        for (const auto& [key, entry] : entries) {
            live += entry->copy_made ? 1u : 0u;
        }
        std::printf("Scene proxies: of the last %u render-target copies at the reduced size (r10), "
                    "%u between proxies into proxies made for copies (%u such proxies %s, %u live), "
                    "%u into other proxies, %u without a dirty source proxy, %u destinations not "
                    "eligible; proxies made for copies since resolved %u times by native accesses "
                    "and sampled by %u bindings, %u source resolves after such a copy "
                    "(experiment 34359738368 %s)\n",
                    r10_calls, r10_copies, r10_made, old_way ? "would be made" : "made", live,
                    r10_other, r10_no_source, r10_not_eligible, r10_resolves, r10_samples,
                    r10_source_resolves,
                    old_way ? "set: no proxy made, native copy" : "clear");
        r10_calls = r10_made = r10_other = r10_no_source = r10_not_eligible = r10_copies =
            r10_resolves = r10_source_resolves = r10_samples = 0;
    }
    return refuse;
}
bool SceneTargets::CopyProxy(VideoCore::Image& src, VideoCore::Image& dst) {
    if (ProxyCopyBlocker(src, dst)) {
        return false;
    }
    Entry& se = *entries.find(Key(src.image_uid, 0))->second;
    Entry& de = *entries.find(Key(dst.image_uid, 0))->second;
    runtime.BeforeImageAccess();
    scheduler.EndRendering();
    const vk::ImageAspectFlags color{vk::ImageAspectFlagBits::eColor};
    // bbport (r22_barriers): both barriers in one call (R22Pair); the source's is left out while
    // the source is still in the transfer source layout of its last barrier (nothing can write it
    // there). The destination's (all commands before it) is always recorded and orders the copy
    // after all earlier work. Experiment 140737488355328 set: two calls, as before.
    const bool r22_pair_on = &se != &de && !BbToggle::Experiment(R22BarriersOffBit);
    r22_pair_count = 0;
    r22_site = r22_pair_on ? R22Pair : R22None;
    Transition(se, color, vk::ImageLayout::eTransferSrcOptimal,
               vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferRead);
    // The copy writes all of the destination proxy (same extent: ProxyCopyBlockerWhy), so its
    // old contents need not be kept.
    r22_site = r22_pair_on ? R22Pair : R22None;
    Transition(de, color, vk::ImageLayout::eTransferDstOptimal,
               vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite, true);
    if (r22_pair_count != 0) {
        if (BbStats::enabled) {
            r22_counts.proxy_issued.fetch_add(1, std::memory_order_relaxed);
            r22_counts.proxy_merged_pair.fetch_add(r22_pair_count - 1, std::memory_order_relaxed);
        }
        scheduler.Record([pair = r22_pair, count = r22_pair_count](vk::CommandBuffer cmd) {
            cmd.pipelineBarrier2(
                {.imageMemoryBarrierCount = count, .pImageMemoryBarriers = pair.data()});
        });
        r22_pair_count = 0;
    }
    const vk::ImageSubresourceLayers layers{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
    const vk::ImageCopy region{
        .srcSubresource = layers,
        .dstSubresource = layers,
        .extent = {se.image.image_ci.extent.width, se.image.image_ci.extent.height, 1},
    };
    scheduler.Record([src_image = vk::Image(se.image), dst_image = vk::Image(de.image),
                      region](vk::CommandBuffer cmd) {
        cmd.copyImage(src_image, vk::ImageLayout::eTransferSrcOptimal, dst_image,
                      vk::ImageLayout::eTransferDstOptimal, region);
    });
    de.state.ProxyWrite();
    if (de.copy_made) { // bbport (r10_proxy_copies)
        ++r10_copies;
        se.copy_source = true;
    }
    ++dst.write_seq;
    dst.flags |= (src.flags & VideoCore::ImageFlagBits::GpuModified);
    dst.flags &= ~VideoCore::ImageFlagBits::Dirty;
    return true;
}
void SceneTargets::NativeOverwritten(const VideoCore::Image& image) {
    if (copying || !image.scene_proxy) {
        return;
    }
    const u32 levels = std::min(16u, image.info.resources.levels);
    for (u32 level = 0; level < levels; ++level) {
        const auto it = entries.find(Key(image.image_uid, level));
        if (it != entries.end()) {
            it->second->state.NativeWrite();
            it->second->dropped_by = SceneUseScope::current.what ? SceneUseScope::current.what
                                                                 : "whole-image native overwrite";
            it->second->dropped_how = "whole-image overwrite (no resolve)";
            it->second->dropped_hash = SceneUseScope::current.hash;
        }
    }
}
bool SceneTargets::NativeClearBegin(const VideoCore::Image& image, u32 base_level, u32 levels) {
    if (copying || !image.scene_proxy || image.info.resources.layers != 1 ||
        image.info.props.is_depth ||
        image.aspect_mask != vk::ImageAspectFlags{vk::ImageAspectFlagBits::eColor} ||
        BbToggle::Experiment(17179869184ull)) {
        return false;
    }
    // The Transit that follows resolves and drops these levels only (Runtime::ClearImage puts
    // the window back after it).
    native_level_begin = base_level;
    native_level_end = base_level + levels;
    bool any = false;
    const u32 end = std::min(std::min(16u, image.info.resources.levels), base_level + levels);
    for (u32 level = base_level; level < end; ++level) {
        const auto it = entries.find(Key(image.image_uid, level));
        if (it == entries.end()) {
            continue;
        }
        auto& e = *it->second;
        clear_resolves_saved += e.state.dirty ? 1u : 0u;
        e.state.NativeWrite(); // not dirty now: the Transit that follows resolves nothing
        any = true;
    }
    return any;
}
void SceneTargets::NativeClearEnd(const VideoCore::Image& image, u32 base_level, u32 levels,
                                  const vk::ClearColorValue& color) {
    if (copying || !image.scene_proxy) {
        return;
    }
    const u32 end = std::min(std::min(16u, image.info.resources.levels), base_level + levels);
    for (u32 level = base_level; level < end; ++level) {
        const auto it = entries.find(Key(image.image_uid, level));
        if (it == entries.end()) {
            continue;
        }
        auto& e = *it->second;
        Transition(e, vk::ImageAspectFlagBits::eColor, vk::ImageLayout::eTransferDstOptimal,
                   vk::PipelineStageFlagBits2::eClear, vk::AccessFlagBits2::eTransferWrite, true);
        scheduler.Record([proxy = vk::Image(e.image), color](vk::CommandBuffer cmdbuf) {
            cmdbuf.clearColorImage(proxy, vk::ImageLayout::eTransferDstOptimal, color,
                                   vk::ImageSubresourceRange{vk::ImageAspectFlagBits::eColor, 0,
                                                             1, 0, 1});
        });
        e.state.CopiedToProxy();
        ++clear_proxies;
    }
    if (++clear_calls % 4096 == 0) {
        std::printf("Scene proxies: of the last 4096 image clears of proxied targets, %u proxy "
                    "levels cleared with the image, %u resolves before a clear left out "
                    "(experiment 17179869184: resolve first, fill later)\n",
                    clear_proxies, clear_resolves_saved);
        clear_proxies = clear_resolves_saved = 0;
    }
}
// bbport (r11_depth_clear): the game clears the scene depth with a rectangle (vs 89cda9e4, no
// pixel shader) before the G-buffer pass starts the scene, so that pass runs at the native size:
// its load op clear is a native write and drops the depth proxy, and the reduced G-buffer pass
// filled the proxy back from the native image (a 3840x2160 depth and stencil resample) only to
// find the clear values in it. When the pass clears all of the image, depth and (where the image
// has it) stencil, and its draws write neither (a DB clear: depth writes off, stencil write mask
// 0), the native image holds the clear values only. The proxy is cleared to the same values and
// is current (valid, not dirty), as the fill would have left it (the nearest resample of a
// constant image is that constant). Every later native write drops it again (NativeAccess: each
// draw of a pass with a clear passes BeginRenderingFull and its Transit). The native clear stays.
// Experiment bit 68719476736: the proxy is not cleared, the next reduced pass fills it as before.
void SceneTargets::NativeDepthClear(const VideoCore::Image& image, bool depth_clear,
                                    bool depth_written, bool stencil_clear,
                                    const vk::ClearDepthStencilValue& value, bool whole,
                                    bool load_ops) {
    if (copying || !Reduced() || !image.scene_proxy || !image.info.props.is_depth) {
        return;
    }
    const auto it = entries.find(Key(image.image_uid, 0));
    if (it == entries.end()) {
        return;
    }
    auto& e = *it->second;
    const bool stencil = bool(image.aspect_mask & vk::ImageAspectFlagBits::eStencil);
    const bool old_way = BbToggle::Experiment(68719476736ull);
    ++r11_passes;
    if (!depth_clear) {
        ++r11_no_depth;
    } else if (depth_written) {
        ++r11_depth_written;
    } else if (stencil && !stencil_clear) {
        ++r11_no_stencil;
    } else if (!whole || image.info.resources != VideoCore::SubresourceExtent{1, 1} ||
               e.level != 0 || !e.image.image || !(value.depth >= 0.f && value.depth <= 1.f) ||
               !(e.image.image_ci.usage & vk::ImageUsageFlagBits::eTransferDst)) {
        ++r11_not_whole;
    } else if (!load_ops) {
        ++r11_continued; // this draw's Transit dropped the proxy again: filled as before
    } else if (e.state.dirty) {
        ++r11_other; // not expected: the pass's Transit resolved a dirty proxy
    } else if (old_way) {
        ++r11_old;
    } else {
        scheduler.EndRendering(); // as Copy: the profiler mark outside a render pass
        const Runtime::TransferMark mark{runtime, "scene proxy clear with a native depth clear",
                                         image};
        Transition(e, image.aspect_mask, vk::ImageLayout::eTransferDstOptimal,
                   vk::PipelineStageFlagBits2::eClear, vk::AccessFlagBits2::eTransferWrite, true);
        const vk::ImageSubresourceRange range{image.aspect_mask, 0, 1, 0, 1};
        scheduler.Record([proxy = vk::Image(e.image), value, range](vk::CommandBuffer cmd) {
            cmd.clearDepthStencilImage(proxy, vk::ImageLayout::eTransferDstOptimal, value, range);
        });
        e.state.CopiedToProxy();
        e.r11_cleared = true;
        ++r11_cleared;
    }
    if (r11_passes >= 600) {
        std::printf("Scene proxies: of the last %u native passes clearing a proxied depth image "
                    "(r11), %u proxies cleared with the pass: %u fills left out at the next "
                    "reduced use, %u dropped again before it; not cleared: %u depth not cleared, "
                    "%u depth written by the draws (no DB clear), %u stencil not cleared, %u not "
                    "all of the image, %u pass continued, %u other, %u experiment 68719476736 "
                    "set (fill as before)\n",
                    r11_passes, r11_cleared, r11_fills_saved, r11_dropped, r11_no_depth,
                    r11_depth_written, r11_no_stencil, r11_not_whole, r11_continued, r11_other,
                    r11_old);
        r11_passes = r11_cleared = r11_fills_saved = r11_dropped = r11_no_depth =
            r11_depth_written = r11_no_stencil = r11_not_whole = r11_continued = r11_other =
                r11_old = 0;
    }
}
bool SceneTargets::ResolvesLinear(const VideoCore::Image& image) const {
    static const bool linear_resolve = [] {
        const char* env = std::getenv("BB_SCENE_LINEAR_RESOLVE");
        return !(env && env[0] == '0');
    }();
    return linear_resolve && !BbToggle::Experiment(2) && image.backing &&
           image.aspect_mask == vk::ImageAspectFlags{vk::ImageAspectFlagBits::eColor} &&
           bool(Features(image.backing->image.image_ci.format) &
                vk::FormatFeatureFlagBits::eSampledImageFilterLinear);
}
vk::Pipeline SceneTargets::DepthToColorPipeline() {
    if (depth_to_color_pipeline) {
        return *depth_to_color_pipeline;
    }
    if (depth_to_color_failed) {
        return {};
    }
    depth_to_color_failed = true; // until it exists: one attempt
    const auto device = instance.GetDevice();
    if (!depth_to_color_frag) {
        depth_to_color_frag =
            vk::UniqueShaderModule(CompileSPV(DEPTH_TO_COLOR_FRAG, device), device);
    }
    const vk::PipelineInputAssemblyStateCreateInfo input_assembly{
        .topology = vk::PrimitiveTopology::eTriangleList,
    };
    const vk::PipelineMultisampleStateCreateInfo multisampling{
        .rasterizationSamples = vk::SampleCountFlagBits::e1,
    };
    const vk::PipelineDepthStencilStateCreateInfo depth_state{};
    const std::array dynamic_states{vk::DynamicState::eViewportWithCount,
                                    vk::DynamicState::eScissorWithCount};
    const vk::PipelineDynamicStateCreateInfo dynamic_info{
        .dynamicStateCount = u32(dynamic_states.size()), .pDynamicStates = dynamic_states.data(),
    };
    const std::array stages{
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eVertex,
                                          .module = *fs_tri_vert, .pName = "main"},
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eFragment,
                                          .module = *depth_to_color_frag, .pName = "main"},
    };
    constexpr vk::Format color_format = vk::Format::eR32Sfloat;
    const vk::PipelineRenderingCreateInfo rendering{
        .colorAttachmentCount = 1, .pColorAttachmentFormats = &color_format,
    };
    const vk::PipelineColorBlendAttachmentState blend_attachment{
        .blendEnable = false,
        .colorWriteMask = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                          vk::ColorComponentFlagBits::eB | vk::ColorComponentFlagBits::eA,
    };
    const vk::PipelineColorBlendStateCreateInfo color_blending{
        .attachmentCount = 1, .pAttachments = &blend_attachment,
    };
    const vk::PipelineViewportStateCreateInfo viewport_info{};
    const vk::PipelineVertexInputStateCreateInfo vertex_input{};
    const vk::PipelineRasterizationStateCreateInfo raster{.lineWidth = 1.f};
    auto created = device.createGraphicsPipelineUnique(VK_NULL_HANDLE, {
        .pNext = &rendering, .stageCount = u32(stages.size()), .pStages = stages.data(),
        .pVertexInputState = &vertex_input, .pInputAssemblyState = &input_assembly,
        .pViewportState = &viewport_info, .pRasterizationState = &raster,
        .pMultisampleState = &multisampling, .pDepthStencilState = &depth_state,
        .pColorBlendState = &color_blending, .pDynamicState = &dynamic_info,
        .layout = *resample_layout,
    });
    if (created.result != vk::Result::eSuccess) {
        std::printf("Scene resolution: no depth proxy to color pipeline (%s): the depth block "
                    "copy keeps the native image copy\n",
                    vk::to_string(created.result).c_str());
        return {};
    }
    depth_to_color_pipeline = std::move(created.value);
    depth_to_color_failed = false;
    return *depth_to_color_pipeline;
}
// bbport: fills an invalid proxy from the native image, unless the caller overwrites all of it
// (a reduced pass that clears it): Attachment's ProxyWrite then makes it current, and the clear
// writes every texel the fill would have. Experiment bit 1073741824: filled as before.
void SceneTargets::Fill(Entry& e, VideoCore::Image& original, const char* use, bool overwritten) {
    if (overwritten && !BbToggle::Experiment(1073741824)) {
        NoteTrip(TripFillSkipped, original, e.level, use, &e);
        return;
    }
    NoteTrip(TripFill, original, e.level, use, &e);
    Copy(e, original, false);
}
// bbport: the resolve/fill table. A row: what happened to which image, how often per frame, who
// asked (the innermost SceneUseScope and the kind of access) and, for a fill, the native write
// that dropped the proxy. Rows in the order first seen (about frame order); after each table, one
// frame's events in order. BB_SCENE_TRIPS=1, BB_FRAME_STATS=1 or BB_GPU_PROFILE=1.
void SceneTargets::NoteTrip(TripEvent event, const VideoCore::Image& image, u32 level,
                            const char* how, const Entry* e) const {
    static const bool on = [] {
        for (const char* name : {"BB_SCENE_TRIPS", "BB_FRAME_STATS", "BB_GPU_PROFILE"}) {
            const char* env = std::getenv(name);
            if (env && env[0] == '1') {
                return true;
            }
        }
        return false;
    }();
    if (!on) {
        return;
    }
    static constexpr std::array<const char*, 5> names{
        "resolve", "fill", "fill skipped (the pass clears the proxy)",
        "proxy kept (read-only depth attachment)", "copy not between proxies (source)"};
    const auto hex = [](u64 hash) {
        char buffer[24];
        std::snprintf(buffer, sizeof(buffer), " %016llx", static_cast<unsigned long long>(hash));
        return hash ? std::string{buffer} : std::string{};
    };
    const auto text = [&](const TripRow& r, double per_frame) {
        std::string s = std::string{names[r.event]} + " " + vk::to_string(r.format) + " " +
                        std::to_string(r.width) + "x" + std::to_string(r.height);
        if (r.level) {
            s += " level " + std::to_string(r.level);
        }
        if (per_frame > 0.0) {
            char buffer[32];
            std::snprintf(buffer, sizeof(buffer), ": %.2f/frame", per_frame);
            s += buffer;
        }
        s += std::string{", by "} + r.use + hex(r.use_hash) + " [" + r.how + "]";
        if (r.dropped_by) {
            s += std::string{"; proxy dropped by "} + r.dropped_by + hex(r.dropped_hash) + " [" +
                 r.dropped_how + "]";
        }
        return s;
    };
    const auto same = [](const char* a, const char* b) {
        return a == b || (a && b && std::strcmp(a, b) == 0);
    };
    const std::scoped_lock lock{trip_mutex};
    u64 frame = BbStats::gpu_frames.load(std::memory_order_relaxed);
    if (frame == 0) {
        frame = BbStats::frame_number.load(std::memory_order_relaxed);
    }
    const u64 bit = (BbToggle::Experiment(1073741824) ? 1073741824ull : 0ull) |
                    (BbToggle::Experiment(17179869184ull) ? 17179869184ull : 0ull) |
                    (BbToggle::Experiment(34359738368ull) ? 34359738368ull : 0ull) |
                    (BbToggle::Experiment(68719476736ull) ? 68719476736ull : 0ull); // r11
    if (bit != trip_bit) {
        // The A/B script switched experiment bit 1073741824: a new window, so that every table
        // and sequence holds one behaviour only.
        trip_bit = bit;
        trip_rows.clear();
        trip_sequence.clear();
        trip_window_start = frame;
        trip_sequence_frame = ~0ull;
    }
    const auto& use = SceneUseScope::current;
    const bool dropped = e && event != TripResolve;
    const TripRow row{u32(event),
                      image.info.pixel_format,
                      image.info.size.width,
                      image.info.size.height,
                      level,
                      use.what ? use.what : "unlabelled (engine effect, presenter or other)",
                      use.hash,
                      how ? how : "",
                      dropped ? e->dropped_by : nullptr,
                      dropped ? e->dropped_how : nullptr,
                      dropped ? e->dropped_hash : 0,
                      1};
    if (trip_sequence_frame != ~0ull && frame > trip_sequence_frame) {
        // bbport (r29_bursts): formatted here, written on bb:Stats (experiment
        // 9007199254740992 set: printed here, as before)
        const BbReport::Capture r29_report;
        BbReport::Printf("Scene proxy round trips, one frame in order (%zu):\n",
                         trip_sequence.size());
        for (std::size_t i = 0; i < trip_sequence.size(); ++i) {
            BbReport::Printf("  %2zu %s\n", i + 1, text(trip_sequence[i], 0.0).c_str());
        }
        trip_sequence.clear();
        trip_sequence_frame = ~0ull;
    }
    if (frame == trip_sequence_frame && event != TripProxyKept && trip_sequence.size() < 160) {
        trip_sequence.push_back(row);
    }
    if (trip_window_start == ~0ull || frame < trip_window_start) {
        trip_window_start = frame;
    }
    if (frame - trip_window_start >= 600) {
        const double frames = double(frame - trip_window_start);
        const BbReport::Capture r29_report; // bbport (r29_bursts): as above
        BbReport::Printf("Scene proxy resolves and fills per frame, last %.0f frames, by consumer "
                    "(experiment 1073741824 %s):\n",
                    frames,
                    (trip_bit & 1073741824ull)
                        ? "set: as before"
                        : "clear: no fill of a cleared target, read-only depth keeps its proxy");
        for (const auto& r : trip_rows) {
            BbReport::Printf("  %s\n", text(r, double(r.count) / frames).c_str());
        }
        trip_rows.clear();
        trip_window_start = frame;
        trip_sequence_frame = frame + 1;
    }
    for (auto& r : trip_rows) {
        if (r.event == row.event && r.format == row.format && r.width == row.width &&
            r.height == row.height && r.level == row.level && same(r.use, row.use) &&
            r.use_hash == row.use_hash && same(r.how, row.how) &&
            same(r.dropped_by, row.dropped_by) && same(r.dropped_how, row.dropped_how) &&
            r.dropped_hash == row.dropped_hash) {
            ++r.count;
            return;
        }
    }
    if (trip_rows.size() < 256) {
        trip_rows.push_back(row);
    }
}
void SceneTargets::DropForgotten() {
    const auto uids = releases.Take();
    if (uids.empty()) {
        return;
    }
    std::vector<std::unique_ptr<Entry>> doomed;
    for (const u64 uid : uids) {
        if (!tracked.erase(uid)) {
            continue;
        }
        TakeProxies(entries, uid, 16, Key, doomed);
    }
    if (doomed.empty()) {
        return;
    }
    for (auto& slot : recent) {
        for (const auto& entry : doomed) {
            if (slot.second == entry.get()) {
                slot = {};
            }
        }
    }
    for (const auto& entry : doomed) {
        released_bytes += entry->image.size_bytes;
    }
    released_proxies += doomed.size();
    // bbport (r35_pending-ops): one operation per proxy (was one for the whole batch), each a
    // pure free that may be carried, so a burst after an area load is spread over frames.
    for (auto& entry : doomed) {
        scheduler.DeferOperation([entry = std::move(entry)]() mutable { entry.reset(); },
                                 "scene proxy free (DropForgotten)", true);
    }
    if (released_proxies - release_report_proxies >= 256) {
        release_report_proxies = released_proxies;
        std::printf("Scene resolution: %llu proxies of freed images released (%llu MiB), %zu live\n",
                    static_cast<unsigned long long>(released_proxies),
                    static_cast<unsigned long long>(released_bytes >> 20), entries.size());
    }
}
SceneTargets::Entry& SceneTargets::Get(VideoCore::ImageId id, u32 level, const char* use,
                                       bool overwritten) {
    DropForgotten();
    auto& original = *lookup(id, 0);
    const u64 key = Key(original.image_uid, level);
    // A draw has up to six targets, mostly the same as the previous draw's.
    for (const auto& [recent_key, recent_entry] : recent) {
        if (recent_entry && recent_key == key) {
            R11Use(*recent_entry); // bbport (r11_depth_clear)
            if (!recent_entry->state.valid) Fill(*recent_entry, original, use, overwritten);
            return *recent_entry;
        }
    }
    auto& entry = entries[key];
    original.scene_proxy = true;
    if (!entry) {
        entry = std::make_unique<Entry>();
        entry->source = id;
        entry->uid = original.image_uid;
        entry->level = level;
        entry->image = VideoCore::UniqueImage(instance.GetDevice(), instance.GetAllocator());
        auto ci = original.backing->image.image_ci;
        ci.pNext = nullptr;
        const auto proxy = ProxySize(original, level);
        ci.extent = vk::Extent3D{proxy.width, proxy.height, 1};
        ci.mipLevels = 1;
        entry->image.Create(ci);
#ifdef BB_TEST_SHARED_POST_GRAPH
        entry->post_proxy_incarnation = PostProxyProof::NextIncarnation();
#endif
        tracked.insert(original.image_uid);
    }
    recent[recent_next++ % recent.size()] = {key, entry.get()};
    R11Use(*entry); // bbport (r11_depth_clear)
    if (!entry->state.valid) Fill(*entry, original, use, overwritten);
    return *entry;
}
vk::ImageView SceneTargets::View(Entry& e, const VideoCore::Image& original,
                                 const VideoCore::ImageViewInfo& info) {
    for (const auto& [key,view] : e.views) if (key == info) return *view;
    const auto aspect = original.info.props.is_depth
        ? (info.is_storage ? original.aspect_mask : vk::ImageAspectFlags(vk::ImageAspectFlagBits::eDepth))
        : vk::ImageAspectFlags(vk::ImageAspectFlagBits::eColor);
    const auto format = original.info.props.is_depth ? original.backing->image.image_ci.format : info.format;
    auto view = Check(instance.GetDevice().createImageViewUnique({
        .image = e.image, .viewType = vk::ImageViewType::e2D, .format = format,
        .components = info.mapping, .subresourceRange = {aspect,0,1,0,1},
    }));
    const auto result = *view;
    e.views.emplace_back(info, std::move(view));
    return result;
}
SceneTargets::Target SceneTargets::Attachment(VideoCore::ImageId id,
                                               const VideoCore::ImageViewInfo& info, bool cleared) {
    auto& original = *lookup(id, 0);
    auto& e = Get(id, info.range.base.level,
                  cleared ? "reduced pass attachment, cleared by the pass" : "reduced pass attachment",
                  cleared);
    const bool depth = original.info.props.is_depth;
    const auto layout = depth ? vk::ImageLayout::eDepthStencilAttachmentOptimal
                              : vk::ImageLayout::eColorAttachmentOptimal;
    // Consecutive draws can stay in the same render pass.
    if (e.layout != layout) {
        Transition(e, original.aspect_mask, layout,
            depth ? vk::PipelineStageFlagBits2::eEarlyFragmentTests | vk::PipelineStageFlagBits2::eLateFragmentTests
                  : vk::PipelineStageFlags2(vk::PipelineStageFlagBits2::eColorAttachmentOutput),
            depth ? vk::AccessFlagBits2::eDepthStencilAttachmentRead | vk::AccessFlagBits2::eDepthStencilAttachmentWrite
                  : vk::AccessFlagBits2::eColorAttachmentRead | vk::AccessFlagBits2::eColorAttachmentWrite);
    }
    e.state.ProxyWrite();
    e.copy_source = false; // bbport (r10_proxy_copies): drawn again since a copy
    auto attachment_info = info;
    attachment_info.is_storage = true; // include stencil in attachment views
    return {e.image, View(e, original, attachment_info), e.layout, e.image.image_ci.usage};
}
bool SceneTargets::ProxyCurrent(const VideoCore::Image& image, u32 level, u32 levels) const {
    if (copying || !image.scene_proxy || image.info.props.is_depth || levels != 1) {
        return false;
    }
    const auto it = entries.find(Key(image.image_uid, level));
    return it != entries.end() && it->second->state.valid;
}
vk::ImageLayout SceneTargets::PrepareSample(const VideoCore::Image& image, u32 level) {
    auto& e = *entries.find(Key(image.image_uid, level))->second;
    r10_samples += e.copy_made ? 1u : 0u; // bbport (r10_proxy_copies)
    constexpr auto layout = vk::ImageLayout::eShaderReadOnlyOptimal;
    if (e.layout != layout) {
        Transition(e, image.aspect_mask, layout,
                   vk::PipelineStageFlagBits2::eVertexShader |
                       vk::PipelineStageFlagBits2::eFragmentShader |
                       vk::PipelineStageFlagBits2::eComputeShader,
                   vk::AccessFlagBits2::eShaderSampledRead);
    }
    return layout;
}
std::optional<SceneTargets::Target> SceneTargets::SampleProxy(
    const VideoCore::Image& image, const VideoCore::ImageViewInfo& info) {
    const u32 level = info.range.base.level;
    if (!ProxyCurrent(image, level, info.range.extent.levels)) {
        return std::nullopt;
    }
    auto& e = *entries.find(Key(image.image_uid, level))->second;
    const auto layout = PrepareSample(image, level);
    return Target{e.image, View(e, image, info), layout, e.image.image_ci.usage};
}
#ifdef BB_TEST_SHARED_POST_GRAPH
namespace {
PostProxyProof::Backing OwnPostBacking(const VideoCore::UniqueImage& owned) {
    constexpr auto ambiguous = vk::ImageCreateFlagBits::eSparseBinding |
        vk::ImageCreateFlagBits::eSparseResidency | vk::ImageCreateFlagBits::eSparseAliased |
        vk::ImageCreateFlagBits::eAlias | vk::ImageCreateFlagBits::eDisjoint;
    if (!owned.image || !owned.allocator || !owned.allocation || owned.image_ci.pNext ||
        (owned.image_ci.flags & ambiguous)) return {};
    VmaAllocationInfo memory{};
    vmaGetAllocationInfo(owned.allocator, owned.allocation, &memory);
    return {owned.image, owned.allocator, owned.allocation, memory.deviceMemory, memory.offset, memory.size};
}
} // namespace

PostProxyProof::Binding SceneTargets::SnapshotPostProxy(const Entry& e,
        const VideoCore::Image& original, Target selected, const PostProxyProof::Key& key) const {
    if (!key || !Reduced() || copying || !original.backing || original.binding.needs_rebind ||
        original.image_uid != e.uid || e.level != 0 || selected.image != e.image.image ||
        selected.layout != e.layout || !selected.view || original.info.props.is_depth ||
        original.aspect_mask != vk::ImageAspectFlagBits::eColor) return {};
    const auto owned_view = std::ranges::find_if(e.views, [&](const auto& pair) {
        const auto& info = pair.first;
        return *pair.second == selected.view && info.format == vk::Format::eR16G16B16A16Sfloat &&
            !info.range.base.level && !info.range.base.layer && info.range.extent.levels == 1 &&
            info.range.extent.layers == 1 && info.mapping == vk::ComponentMapping{};
    });
    const auto& ci = e.image.image_ci;
    const auto& native_ci = original.backing->image.image_ci;
    if (owned_view == e.views.end() || ci.imageType != vk::ImageType::e2D || ci.mipLevels != 1 ||
        ci.arrayLayers != 1 || ci.extent.depth != 1 || ci.format != owned_view->first.format ||
        !(ci.usage & vk::ImageUsageFlagBits::eSampled) ||
        native_ci.imageType != vk::ImageType::e2D || native_ci.format != ci.format ||
        native_ci.samples != ci.samples || native_ci.mipLevels != 1 || native_ci.arrayLayers != 1 ||
        ci.extent.width >= native_ci.extent.width || ci.extent.height >= native_ci.extent.height) return {};
    return {.key = key, .owner = reinterpret_cast<u64>(this), .generation = generation,
        .incarnation = e.post_proxy_incarnation, .uid = e.uid, .native_serial = original.write_seq,
        .proxy = OwnPostBacking(e.image), .native = OwnPostBacking(original.backing->image),
        .image = selected.image, .view = selected.view, .layout = selected.layout,
        .extent = {ci.extent.width, ci.extent.height}, .format = ci.format, .samples = ci.samples,
        .range = PostProxyProof::Color0, .valid = e.state.valid, .dirty = e.state.dirty};
}

PostProxyProof::BackingCheck SceneTargets::CheckPostProxyBacking(const PostProxyProof::Lease& lease,
        const PostProxyProof::Key& key, Target selected) const {
    const auto& prior = lease.binding;
    if (!prior.IsOwned() || prior.key != key || prior.owner != reinterpret_cast<u64>(this) ||
        prior.generation != generation) return {};
    const auto it = entries.find(Key(prior.uid, 0));
    if (it == entries.end()) return {};
    const auto& e = *it->second;
    const auto* original = lookup(e.source, e.uid);
    if (!original) return {};
    return PostProxyProof::Recheck(prior, SnapshotPostProxy(e, *original, selected, key));
}
#endif

SceneTargets::Target SceneTargets::Read(VideoCore::ImageId id,
                                       const VideoCore::ImageViewInfo& info,
                                       vk::PipelineStageFlags2 stages, vk::AccessFlags2 access) {
#ifdef BB_TEST_SHARED_POST_GRAPH
    return ReadImpl(id, info, stages, access, {}, nullptr);
}

SceneTargets::Target SceneTargets::ReadPostProxy(VideoCore::ImageId id,
        const VideoCore::ImageViewInfo& info, const PostProxyProof::Key& key,
        PostProxyProof::Lease& lease, vk::PipelineStageFlags2 stages, vk::AccessFlags2 access) {
    lease = {};
    return ReadImpl(id, info, stages, access, key, &lease);
}

SceneTargets::Target SceneTargets::ReadImpl(VideoCore::ImageId id,
        const VideoCore::ImageViewInfo& info, vk::PipelineStageFlags2 stages, vk::AccessFlags2 access,
        const PostProxyProof::Key& key, PostProxyProof::Lease* lease) {
#endif
    auto& original = *lookup(id, 0);
    // bbport (r22_barriers): ReadNext's request, taken before Get (a fill there records
    // Transitions of its own).
    const bool r22_next = r22_read_next && !BbToggle::Experiment(R22BarriersOffBit);
    r22_read_next = false;
    auto& e = Get(id, 0, "proxy read (engine effect or upscaler input)");
    r22_site = r22_next ? R22EffectRead : R22None;
#ifdef BB_TEST_SHARED_POST_GRAPH
    const bool observe = lease && key && e.state.valid && e.state.dirty && (access & R22Reads) == access;
    Transition(e, original.aspect_mask, vk::ImageLayout::eGeneral, stages, access, false,
               observe ? &lease->trace : nullptr);
    const Target target{e.image, View(e, original, info), e.layout, e.image.image_ci.usage};
    if (lease) lease->binding = SnapshotPostProxy(e, original, target, key);
    return target;
#else
    Transition(e, original.aspect_mask, vk::ImageLayout::eGeneral, stages, access);
    return {e.image, View(e, original, info), e.layout, e.image.image_ci.usage};
#endif
}
SceneTargets::Target SceneTargets::ReadNext(VideoCore::ImageId id,
                                           const VideoCore::ImageViewInfo& info) {
    r22_read_next = true; // bbport (r22_barriers)
    return Read(id, info);
}
} // namespace Vulkan
