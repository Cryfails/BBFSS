// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card alpha layers and the card debug view (vk_card_alpha.h).

#include "video_core/renderer_vulkan/vk_card_alpha.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "shader_recompiler/info.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "video_core/amdgpu/resource.h"
#include "video_core/host_shaders/rt_card_alpha_fill_comp.h"
#include "video_core/host_shaders/rt_card_alpha_fill_colour_comp.h" // bbport (r131a_foliage-translucency)
#include "video_core/renderer_vulkan/foliage_translucency.h"       // bbport (r131a_foliage-translucency)
#include "video_core/host_shaders/rt_card_view_comp.h"
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

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ShaderWrite = vk::AccessFlagBits2::eShaderWrite;
constexpr auto ReadWrite = ShaderRead | ShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u32 LineFrames = 600;
constexpr vk::ImageSubresourceRange LayersRange{vk::ImageAspectFlagBits::eColor, 0, CardLayerMips,
                                                0, CardLayerCount};
// bbport (r131a_foliage-translucency): the colour layers' size and range
constexpr vk::DeviceSize ColourBytes = vk::DeviceSize(CARD_COLOUR_SIZE) * CARD_COLOUR_SIZE * 4 * CardLayerCount;
constexpr vk::ImageSubresourceRange ColourRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, CardLayerCount};

std::atomic<u64> cutout_loaded{0};
std::atomic<u64> cutout_refused{0};

// BB_RT_CARD_ALPHA_VIEW, read once (the first caller: Wanted, at the rasterizer's start).
u32 ViewKnob() {
    static const u32 view = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA_VIEW");
        if (CardViewMisread(env)) {
            std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%.16s is not 0 to %d: off\n",
                        env, CARD_VIEW_MODES);
        }
        return ReadCardView(env);
    }();
    return view;
}

constexpr const char* ViewName(u32 mode) {
    return mode == CARD_VIEW_OVERLAY ? "overlay"
           : mode == CARD_VIEW_ALPHA ? "alpha"
           : mode == CARD_VIEW_UV    ? "coordinates"
                                     : "off";
}

} // namespace

CardCacheCounts CardCacheTally() {
    return {cutout_loaded.load(std::memory_order_relaxed),
            cutout_refused.load(std::memory_order_relaxed)};
}
void NoteCardCutoutLoaded() {
    cutout_loaded.fetch_add(1, std::memory_order_relaxed);
}
void NoteCardCutoutRefused() {
    cutout_refused.fetch_add(1, std::memory_order_relaxed);
}

bool CardAlpha::Wanted() {
    // Both knobs are read once (CardAlphaLevel and ViewKnob keep what they read); the
    // rasterizer asks once, at its start, before the first frame.
    const u32 level = Shader::Optimization::CardAlphaLevel();
    const u32 view = ViewKnob();
    if (level < CardAlphaLayers && view != 0) {
        std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%u needs "
                    "BB_RT_CARD_ALPHA=2: off\n", view);
    }
    return level >= CardAlphaLayers; // unset or 1: no CardAlpha, nothing made, no draw calls in
}

CardAlpha::CardAlpha(const Instance& instance_, Scheduler& scheduler_,
                     VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                     SceneTargets& scene_targets_, CameraMotion& camera_motion_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_} {
    // Made only when Wanted(): the knobs as it read them.
    level = Shader::Optimization::CardAlphaLevel();
    const u32 view = ViewKnob();
    if (level < CardAlphaLayers) {
        return;
    }
    made = Make();
    view_mode = made ? view : 0;
    std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA=2: %s; %u layers of %ux%u R8, %u levels "
                "(%llu bytes), layer info %llu bytes, card rows %llu bytes (made at the first ray traced scene), "
                "at most %u fills a frame; debug view BB_RT_CARD_ALPHA_VIEW=%u (%s); no shadow "
                "reads the layers yet\n",
                made ? "on" : "off - the layers could not be made", CardLayerCount, CardLayerSize,
                CardLayerSize, CardLayerMips, static_cast<unsigned long long>(CardLayersBytes),
                static_cast<unsigned long long>(CardLayerInfoBytes),
                static_cast<unsigned long long>(CardRowsBytes), CardFillsPerFrame, view,
                ViewName(view_mode));
}

CardAlpha::~CardAlpha() {
    const auto device = instance.GetDevice();
    for (auto& e : view_cache) {
        if (e.view) {
            device.destroyImageView(e.view);
        }
    }
    level_views = {};
    layers_view.reset();
    colour_view.reset(); // bbport (r131a_foliage-translucency)
    if (colour_image) {
        vmaDestroyImage(instance.GetAllocator(), colour_image, colour_allocation);
    }
    if (layers_image) {
        vmaDestroyImage(instance.GetAllocator(), layers_image, layers_allocation);
    }
    FreeBuffer(info_buffer);
    FreeBuffer(view_counters);
    FreeBuffer(view_readback);
}

bool CardAlpha::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
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

void CardAlpha::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

// bbport (r131a_foliage-translucency): the colour layers (see the member), cleared to 0 (a = 0: no colour) before the first fill. False: not made
// (no room, or the format cannot be stored): the fill is the plain one and the readers get no colour view.
bool CardAlpha::MakeColour() {
    const auto device = instance.GetDevice();
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) || !EffectPass::HasRoom(instance, ColourBytes)) {
        return false;
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {CARD_COLOUR_SIZE, CARD_COLOUR_SIZE, 1},
        .mipLevels = 1,
        .arrayLayers = CardLayerCount,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(instance.GetAllocator(), &image_ci, &alloc_ci, &raw, &colour_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    colour_image = raw;
    SetObjectName(device, colour_image, "Card colour layers");
    colour_view = Check<"create card colour view">(device.createImageViewUnique({
        .image = colour_image,
        .viewType = vk::ImageViewType::e2DArray,
        .format = vk::Format::eR8G8B8A8Unorm,
        .subresourceRange = ColourRange,
    }));
    scheduler.Record([image = colour_image](vk::CommandBuffer cmd) {
        EffectPass::InitGeneral(cmd, image, ColourRange);
        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
        cmd.clearColorImage(image, vk::ImageLayout::eGeneral, zero, ColourRange);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands, MemoryAll);
    });
    return true;
}

// The layers (CardLayersBytes), their views, the layer info and the fill pass: all once, at
// start. The array is never recreated or resized, so a reader's descriptors never go stale.
bool CardAlpha::Make() {
    const auto device = instance.GetDevice();
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) ||
        !EffectPass::HasRoom(instance, CardLayersBytes)) {
        return false;
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .extent = {CardLayerSize, CardLayerSize, 1},
        .mipLevels = CardLayerMips,
        .arrayLayers = CardLayerCount,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(instance.GetAllocator(), &image_ci, &alloc_ci, &raw, &layers_allocation,
                       nullptr) != VK_SUCCESS) {
        return false;
    }
    layers_image = raw;
    SetObjectName(device, layers_image, "Card alpha layers");
    layers_view = Check<"create card layers view">(device.createImageViewUnique({
        .image = layers_image,
        .viewType = vk::ImageViewType::e2DArray,
        .format = vk::Format::eR8Unorm,
        .subresourceRange = LayersRange,
    }));
    for (u32 k = 0; k < CardLayerMips; ++k) {
        level_views[k] = Check<"create card layer level view">(device.createImageViewUnique({
            .image = layers_image,
            .viewType = vk::ImageViewType::e2DArray,
            .format = vk::Format::eR8Unorm,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, k, 1, 0, CardLayerCount},
        }));
    }
    const auto make_sampler = [&](vk::UniqueSampler& out, float max_lod, vk::SamplerMipmapMode mip) {
        auto made_sampler = device.createSamplerUnique({
            .magFilter = vk::Filter::eLinear,
            .minFilter = vk::Filter::eLinear,
            .mipmapMode = mip,
            .addressModeU = vk::SamplerAddressMode::eClampToEdge,
            .addressModeV = vk::SamplerAddressMode::eClampToEdge,
            .addressModeW = vk::SamplerAddressMode::eClampToEdge,
            .maxLod = max_lod,
        });
        if (made_sampler.result != vk::Result::eSuccess) {
            return false;
        }
        out = std::move(made_sampler.value);
        return true;
    };
    if (!make_sampler(layer_sampler, float(CardLayerMips - 1), vk::SamplerMipmapMode::eLinear) ||
        !make_sampler(source_sampler, VK_LOD_CLAMP_NONE, vk::SamplerMipmapMode::eLinear) ||
        !MakeBuffer(info_buffer, CardLayerInfoBytes, false,
                    vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst)) {
        return false;
    }
    using enum vk::DescriptorType;
    // bbport (r131a_foliage-translucency): with the light through leaves on, the colour layers and the COLOUR build of the fill (a fifth image)
    colour_on = FoliageTranslucency::LightThrough() && MakeColour();
    if (colour_on ? !EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,
                                        {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                        CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COLOUR_COMP, "card alpha fill (colour)")
                  : !EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,
                                        {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},
                                        CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COMP, "card alpha fill")) {
        return false;
    }
    // Every layer starts at 0 (a reader never reads a layer before its fill: the layer info's
    // READY bit) and the info at 0 (no layer READY).
    scheduler.Record([image = layers_image, info = info_buffer.buffer](vk::CommandBuffer cmd) {
        EffectPass::InitGeneral(cmd, image, LayersRange);
        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
        cmd.clearColorImage(image, vk::ImageLayout::eGeneral, zero, LayersRange);
        cmd.fillBuffer(info, 0, CardLayerInfoBytes, 0);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  MemoryAll);
    });
    info_dirty = false;
    return true;
}

void CardAlpha::Miss(CardDraw& card, CardLayerMiss why) {
    card.layer = 0;
    card.layer_gen = 0;
    ++stats.miss[std::size_t(why)];
}

void CardAlpha::NoteNoSource(CardDraw& card) {
    ++stats.draws;
    Miss(card, CardLayerMiss::NoSource);
}

void CardAlpha::NoteDraw(CardDraw& card, const AmdGpu::Image& sharp, const Shader::ImageResource& res,
                         VideoCore::ImageId image, u64 uid) {
    ++stats.draws;
    const auto dst = sharp.DstSelect();
    const CardTexFacts facts{
        .type = u32(sharp.GetType()),
        .num_format = u32(sharp.GetNumberFmt()),
        .conversion = u32(sharp.GetNumberConversion()),
        .dst_select = {u8(dst.r), u8(dst.g), u8(dst.b), u8(dst.a)},
    };
    u8 lane = 0xff;
    if (const CardLayerMiss why = CardSourceCheck(facts, card.stored_channel, lane);
        why != CardLayerMiss::None) {
        Miss(card, why);
        return;
    }
    // Read without touching the texture cache's LRU (the draw's binding just did).
    const VideoCore::Image* found = texture_cache.TryGetImage(image, uid);
    if (!found || !texture_cache.IsRegisteredImage(image, uid)) {
        Miss(card, CardLayerMiss::NoSource);
        return;
    }
    if (found->info.props.is_depth) {
        Miss(card, CardLayerMiss::Depth);
        return;
    }
    const CardLayerSource source{image.index, uid, found->write_seq};
    const CardLayerGet got = table.Get(CardLayerKey(card.tsharp, lane), lane, source, frame);
    if (got.layer == CardNoLayer) {
        Miss(card, CardLayerMiss::Full);
        return;
    }
    stats.given += got.given ? 1 : 0;
    stats.taken += got.taken ? 1 : 0;
    stats.dropped += got.dropped ? 1 : 0;
    // A layer given (new generation) or dropped (no longer READY): the info changes.
    info_dirty = info_dirty || got.given || got.dropped;
    if (table.At(got.layer).queued) {
        // The view the fill samples, as this draw binds the texture (the newest source).
        fill_view[got.layer] = VideoCore::ImageViewInfo(sharp, res);
    }
    card.layer = got.layer + 1;
    card.layer_gen = got.gen;
}

void CardAlpha::RecordFills() {
    if (!made) {
        return;
    }
    if (fills_frame != frame) {
        fills_frame = frame;
        fills_left = CardFillsPerFrame;
    }
    while (fills_left > 0) {
        const u32 layer = table.NextFill();
        if (layer == CardNoLayer) {
            break;
        }
        --fills_left;
        const bool refill = table.At(layer).state == CardLayerState::Ready;
        const FillResult result = Fill(layer);
        if (result == FillResult::Recorded) {
            ++(refill ? stats.refills : stats.fills);
            info_dirty = true;
        } else {
            // Not filled: a Wanted layer waits for the next draw that binds the texture, a
            // Ready one keeps its fill (the next draw asks again if the source differs).
            table.FillFailed(layer);
            if (result == FillResult::NotYet) {
                ++stats.dirty_waits;
            } else {
                ++stats.failed_fills;
                ++stats.miss[std::size_t(CardLayerMiss::Gone)];
            }
        }
    }
    if (!info_dirty) {
        return;
    }
    info_dirty = false;
    std::array<u32, CardLayerCount> info{};
    for (u32 i = 0; i < CardLayerCount; ++i) {
        info[i] = table.Info(i);
    }
    scheduler.EndRendering();
    scheduler.Record([info, buffer = info_buffer.buffer](vk::CommandBuffer cmd) {
        // After every earlier reader of the info (rays of this frame's earlier passes).
        EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Transfer,
                                  vk::AccessFlagBits2::eTransferWrite);
        cmd.updateBuffer(buffer, 0, sizeof(info), info.data());
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
}

// One layer from its source image, as the last draw bound it. The image must still be the
// registered image of that uid (a texture streamed out since: the fill waits for a draw that
// binds a living one). The source's write_seq as read here is what the layer then holds.
// An image with Dirty flags (the CPU wrote its memory after the draw bound it, or a fill put off
// by the budget meets such writes) holds older texels than the guest's: no fill from it; the
// next draw's binding uploads them (a write that bumps write_seq) and asks for the fill again.
CardAlpha::FillResult CardAlpha::Fill(u32 layer) {
    const CardLayer& l = table.At(layer);
    const VideoCore::ImageId id{l.source.image};
    VideoCore::Image* image = texture_cache.TryGetImage(id, l.source.uid);
    if (!image || !texture_cache.IsRegisteredImage(id, l.source.uid) || image->info.props.is_depth) {
        return FillResult::Gone;
    }
    if (True(image->flags & VideoCore::ImageFlagBits::Dirty)) {
        return FillResult::NotYet;
    }
    const CardLayerSource as_read{l.source.image, l.source.uid, image->write_seq};
    const vk::ImageView source = *image->FindView(fill_view[layer]).image_view;
    scheduler.EndRendering();
    runtime.Transit(image, vk::ImageLayout::eShaderReadOnlyOptimal, Compute, ShaderRead);
    runtime.FlushBarriers();
    const std::array<u32, 4> push{layer, l.lane, 0, 0};
    const vk::DescriptorImageInfo src{*source_sampler, source, vk::ImageLayout::eShaderReadOnlyOptimal};
    const vk::DescriptorImageInfo dst0{{}, *level_views[0], vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo dst1{{}, *level_views[1], vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo dst2{{}, *level_views[2], vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo dst3{{}, colour_on ? *colour_view : vk::ImageView{}, vk::ImageLayout::eGeneral}; // bbport (r131a_foliage-translucency)
    constexpr u32 groups = (CardLayerSize + CARD_FILL_GROUP - 1) / CARD_FILL_GROUP;
    EffectPass::Mark(62, "card alpha fill");
    scheduler.RecordCrumb(
        {.name = "Card alpha fill"},
        [push, src, dst0, dst1, dst2, dst3, with_colour = colour_on, pipeline = *fill_pipeline,
         layout = *fill_layout](vk::CommandBuffer cmd) {
            // The layer may be read by rays recorded before (its old texture, or the same one
            // before a refill): they finish first.
            EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Compute, ShaderWrite);
            const std::array writes{
                vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                                       .pImageInfo = &src},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst0},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst1},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst2},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1, // bbport (r131a_foliage-translucency): the colour layers
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst3}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                     vk::ArrayProxy<const vk::WriteDescriptorSet>(with_colour ? 5u : 4u, writes.data()));
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), push.data());
            cmd.dispatch(groups, groups, 1);
            EffectPass::MemoryBarrier(cmd, Compute, ShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead);
        });
    table.Filled(layer, as_read);
    return FillResult::Recorded;
}

void CardAlpha::NoSceneHooks() {
    if (view_mode != 0 && !view_said_no_hooks) {
        view_said_no_hooks = true;
        std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%u has no place in the frame "
                    "without the upscaler (it runs before it): the view stays off\n", view_mode);
    }
}

bool CardAlpha::MakeView() {
    if (view_pipeline) {
        return true;
    }
    if (view_failed) {
        return false;
    }
    using enum vk::DescriptorType;
    view_failed = !EffectPass::CreateSampler(instance, depth_sampler, vk::Filter::eNearest) ||
                  !MakeBuffer(view_counters, CARD_VIEW_COUNTERS * 4, false,
                              vk::BufferUsageFlagBits::eStorageBuffer |
                                  vk::BufferUsageFlagBits::eTransferSrc |
                                  vk::BufferUsageFlagBits::eTransferDst) ||
                  !MakeBuffer(view_readback, CARD_VIEW_COUNTERS * 4, true,
                              vk::BufferUsageFlagBits::eTransferDst) ||
                  !EffectPass::Create(instance, view_set, view_layout, view_pipeline,
                                      {eAccelerationStructureKHR, eCombinedImageSampler, eStorageImage,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler, eStorageBuffer},
                                      CARD_VIEW_PUSH_BYTES, RT_CARD_VIEW_COMP, "card debug view");
    if (view_failed) {
        std::printf("Card alpha layers (r62): the debug view is off - its pass could not be made\n");
        return false;
    }
    // Outside rendering: PrepareScene before this need not have ended it (no build, no fill).
    scheduler.EndRendering();
    scheduler.Record([counters = view_counters.buffer](vk::CommandBuffer cmd) {
        cmd.fillBuffer(counters, 0, CARD_VIEW_COUNTERS * 4, 0);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  MemoryAll);
    });
    return true;
}

vk::ImageView CardAlpha::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create card view image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

// The debug view: a frame whose scene is built (PrepareScene; it records the fills first) and
// whose scene colour is RGBA16F with storage, as the drawn look takes it.
void CardAlpha::View(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter) {
    if (!ViewOn() || !color_id || !depth_id || camera_motion.PreviewFrame()) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid || !rt_shadow.PrepareScene() || !MakeView()) {
        ++stats.view_skipped;
        return;
    }
    const auto tables = rt_shadow.CardTables();
    const vk::AccelerationStructureKHR scene = rt_shadow.Scene();
    if (!tables.rows || !tables.pool || !scene) {
        ++stats.view_skipped; // no card yet: no rows, no pool
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.view_skipped;
        return;
    }
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    const SceneUseScope scene_use{"card debug view"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.view_skipped;
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.view_skipped;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    struct Push {
        std::array<float, 4> proj;
        std::array<float, 2> jitter;
        std::array<u32, 2> size;
        u32 mode, flags, unused0, unused1;
        std::array<float, 4> unused2;
    };
    static_assert(sizeof(Push) == CARD_VIEW_PUSH_BYTES);
    const Push push{camera.proj, jitter, {width, height}, view_mode, 0, 0, 0, {}};
    // Copied every CardViewLineFrames view frames: the u32 counters cannot overflow (at 4K, 600
    // frames would). The frames since the last copy are printed with the counts.
    const bool copy = ++view_frames >= CardViewLineFrames && !view_readback_pending;
    if (copy) {
        view_copied_frames = view_frames;
        view_frames = 0;
        view_readback_pending = true;
        view_readback_tick = scheduler.CurrentTick();
    }
    ++stats.views;
    const auto layers = ReaderBindings();
    EffectPass::Mark(63, "card debug view");
    scheduler.RecordCrumb(
        {.name = "Card debug view"},
        [push, scene, color_view, depth_view, tables, layers, copy,
         depth_sampler = *depth_sampler, counters = view_counters.buffer,
         readback = view_readback.buffer, pipeline = *view_pipeline,
         layout = *view_layout](vk::CommandBuffer cmd) {
            EffectPass::FullBarrier(cmd);
            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const vk::DescriptorImageInfo depth_info{depth_sampler, depth_view,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo alpha_info{layers.sampler, layers.layers,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo rows_info{tables.rows, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo pool_info{tables.pool, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo layer_info{layers.info, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = eCombinedImageSampler,
                                       .pImageInfo = &depth_info},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = eStorageImage, .pImageInfo = &color_info},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &rows_info},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &pool_info},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &layer_info},
                vk::WriteDescriptorSet{.dstBinding = 6, .descriptorCount = 1,
                                       .descriptorType = eCombinedImageSampler,
                                       .pImageInfo = &alpha_info},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer,
                                       .pBufferInfo = &counter_info}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((push.size[0] + CARD_VIEW_GROUP - 1) / CARD_VIEW_GROUP,
                         (push.size[1] + CARD_VIEW_GROUP - 1) / CARD_VIEW_GROUP, 1);
            EffectPass::FullBarrier(cmd);
            if (copy) {
                const vk::BufferCopy region{0, 0, CARD_VIEW_COUNTERS * 4};
                cmd.copyBuffer(counters, readback, region);
                EffectPass::FullBarrier(cmd);
                cmd.fillBuffer(counters, 0, CARD_VIEW_COUNTERS * 4, 0);
                EffectPass::FullBarrier(cmd);
            }
        });
}

void CardAlpha::OnFrameEnd() {
    if (!made) {
        return;
    }
    ++frame;
    if (view_readback_pending && scheduler.IsFree(view_readback_tick)) {
        view_readback_pending = false;
        // A copy of the GPU's counters in our own readback buffer (not guest memory). Summed in
        // 64 bits.
        const auto* c = static_cast<const u32*>(view_readback.mapped);
        const u64 tested = u64(c[CARD_VIEW_AGREE_KEPT]) + c[CARD_VIEW_AGREE_DROPPED] +
                           c[CARD_VIEW_RAY_KEPT_GAME_DROPPED] + c[CARD_VIEW_RAY_DROPPED_GAME_KEPT];
        const u64 agreed = u64(c[CARD_VIEW_AGREE_KEPT]) + c[CARD_VIEW_AGREE_DROPPED];
        const double agree = tested > 0 ? 100.0 * double(agreed) / double(tested) : 0.0;
        std::printf("Card debug view (r62): %u frames, %u pixels: %u on a card candidate; judged "
                    "(camera pass cards without dither, game mip within the layers): %u agree "
                    "kept, %u agree dropped, %u ray kept where the game dropped, %u ray dropped "
                    "where the game kept (%.2f %% agree); not judged: %u fully clear (r62b: the "
                    "rule keeps no alpha, drawn white), %u sun pass cards, %u "
                    "dithered, %u game mip coarser than the layers; %u no data; %u no card, %u "
                    "sky\n",
                    view_copied_frames, c[CARD_VIEW_PIXELS], c[CARD_VIEW_CARD_HITS],
                    c[CARD_VIEW_AGREE_KEPT], c[CARD_VIEW_AGREE_DROPPED],
                    c[CARD_VIEW_RAY_KEPT_GAME_DROPPED], c[CARD_VIEW_RAY_DROPPED_GAME_KEPT], agree,
                    c[CARD_VIEW_CLEAR], c[CARD_VIEW_SUN_CARD], c[CARD_VIEW_DITHERED],
                    c[CARD_VIEW_COARSE],
                    c[CARD_VIEW_NO_DATA], c[CARD_VIEW_NO_CARD], c[CARD_VIEW_SKY]);
    }
    if (++line_frames < LineFrames) {
        return;
    }
    line_frames = 0;
    const auto rows = rt_shadow.TakeCardRowCounts();
    const auto cache = CardCacheTally();
    const auto& m = stats.miss;
    std::printf("Card alpha layers (r62): %u frames: %llu card draws (%llu found by the hint), %llu "
                "layers given (%llu taken from another texture, %llu dropped: another image), "
                "%llu fills, %llu refills, %llu failed, %llu put off (CPU writes not uploaded); "
                "layers %u ready, %u "
                "wanted, %u free, %u queued; no layer: %llu no source, %llu not 2D, %llu "
                "multisampled, %llu conversion, %llu format, %llu constant, %llu no lane, %llu depth, "
                "%llu full, %llu gone; rows %llu written (%llu ready), %llu deferred; views %llu "
                "(%llu skipped); cache CUT1 %llu loaded, %llu refused\n",
                LineFrames, static_cast<unsigned long long>(stats.draws),
                static_cast<unsigned long long>(table.TakeHintHits()),
                static_cast<unsigned long long>(stats.given),
                static_cast<unsigned long long>(stats.taken),
                static_cast<unsigned long long>(stats.dropped),
                static_cast<unsigned long long>(stats.fills),
                static_cast<unsigned long long>(stats.refills),
                static_cast<unsigned long long>(stats.failed_fills),
                static_cast<unsigned long long>(stats.dirty_waits),
                table.Count(CardLayerState::Ready), table.Count(CardLayerState::Wanted),
                table.Count(CardLayerState::Free), table.Queued(),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NoSource)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NotTwoD)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Multisample)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Conversion)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Format)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Constant)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NoLane)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Depth)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Full)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Gone)]),
                static_cast<unsigned long long>(rows.written),
                static_cast<unsigned long long>(rows.ready),
                static_cast<unsigned long long>(rows.deferred),
                static_cast<unsigned long long>(stats.views),
                static_cast<unsigned long long>(stats.view_skipped),
                static_cast<unsigned long long>(cache.loaded),
                static_cast<unsigned long long>(cache.refused));
    stats = {};
}

} // namespace Vulkan
