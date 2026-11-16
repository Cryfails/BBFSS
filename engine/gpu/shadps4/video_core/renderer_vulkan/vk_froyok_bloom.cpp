// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_froyok_bloom.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "common/assert.h"
#include "shader_recompiler/info.h"
#include "shader_recompiler/native/froyok_composite.h"
#include "video_core/host_shaders/froyok_bloom_downsample_comp.h"
#include "video_core/host_shaders/froyok_bloom_first_comp.h"
#include "video_core/host_shaders/froyok_bloom_upsample_comp.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};

}

FroyokBloom::FroyokBloom(const Instance& instance_, Scheduler& scheduler_,
                         VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                         SceneTargets& scene_targets_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_} {}

FroyokBloom::~FroyokBloom() {
    // The presenter finished the GPU's work before the rasterizer goes.
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

vk::ImageView FroyokBloom::CachedView(const VideoCore::Image& image) {
    const vk::Image handle = image.GetImage();
    const vk::Format format = image.info.pixel_format;
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format) {
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
        .view = Check<"create Froyok HDR view">(device.createImageView({
            .image = handle, .viewType = vk::ImageViewType::e2D,
            .format = format, .subresourceRange = ColorRange})),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void FroyokBloom::OnFrameEnd() {
    stat_unread += ready ? 1 : 0; // built, and no Froyok composite read it this frame
    ready = false;
    pending = {};
    ++frames;
    if ((BbStats::enabled || GpuProfiler::Get()) && frames % 600 == 0 &&
        (stat_built || stat_waiting || stat_composites)) {
        BbReport::Printf("Froyok bloom, last 600 frames: %u pyramids built (%u of them late, at the "
                    "composite; %u never read), %u not built (no Froyok composite in the last %llu "
                    "frames), %u of the sources read through a scene proxy; %u Froyok composites, "
                    "%u of them without a pyramid (experiment mask 2147483648 %s)\n",
                    stat_built, stat_late, stat_unread, stat_waiting,
                    static_cast<unsigned long long>(LazyFrames), stat_proxy, stat_composites,
                    stat_without,
                    BbToggle::Experiment(2147483648ull) ? "set: built at every recombination"
                                                        : "clear");
        stat_built = stat_late = stat_unread = stat_waiting = stat_proxy = stat_composites =
            stat_without = 0;
    }
}

bool FroyokBloom::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) ||
        !EffectPass::CreateSampler(instance, upsample_sampler, vk::Filter::eLinear)) {
        failed = true;
        return false;
    }
    const auto device = instance.GetDevice();
    auto border = device.createSamplerUnique({
        .magFilter = vk::Filter::eLinear, .minFilter = vk::Filter::eLinear,
        .mipmapMode = vk::SamplerMipmapMode::eNearest,
        .addressModeU = vk::SamplerAddressMode::eClampToBorder,
        .addressModeV = vk::SamplerAddressMode::eClampToBorder,
        .addressModeW = vk::SamplerAddressMode::eClampToBorder,
        .maxLod = 0.0f, .borderColor = vk::BorderColor::eFloatTransparentBlack});
    if (border.result != vk::Result::eSuccess) {
        failed = true;
        return false;
    }
    downsample_sampler = std::move(border.value);
    using enum vk::DescriptorType;
    const std::array codes{std::span<const u32>{FROYOK_BLOOM_DOWNSAMPLE_COMP},
                           std::span<const u32>{FROYOK_BLOOM_FIRST_COMP},
                           std::span<const u32>{FROYOK_BLOOM_UPSAMPLE_COMP}};
    const std::array names{"Froyok bloom downsample", "Froyok bloom first downsample",
                           "Froyok bloom upsample"};
    for (u32 stage = 0; stage < pipelines.size(); ++stage) {
        if (!EffectPass::Create(instance, set_layout, layout, pipelines[stage],
                                {eCombinedImageSampler, eCombinedImageSampler, eStorageImage},
                                sizeof(Push), codes[stage], names[stage])) {
            failed = true;
            return false;
        }
    }
    return true;
}

FroyokBloom::Source FroyokBloom::Access(VideoCore::ImageId id) {
    auto& image = texture_cache.GetImage(id);
    if (image.info.pixel_format != vk::Format::eR16G16B16A16Sfloat ||
        image.info.resources.levels != 1 || image.info.resources.layers != 1) {
        return {};
    }
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info);
        return {proxy.view, scene_targets.Size().width, scene_targets.Size().height};
    }
    const auto view = CachedView(image);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
    runtime.FlushBarriers();
    return {view, image.info.size.width, image.info.size.height};
}

bool FroyokBloom::EnsureImages(u32 w, u32 h) {
    if (width == w && height == h && !downsampled.empty()) {
        return true;
    }
    const u32 levels = std::max(1, int(std::floor(std::log2(std::min(w, h)))) - 3);
    u64 bytes = 0;
    u32 x = w, y = h;
    for (u32 level = 0; level < levels; ++level) {
        x = std::max(1u, x / 2);
        y = std::max(1u, y / 2);
        bytes += 16ull * x * y;
    }
    if (!EffectPass::HasRoom(instance, bytes)) {
        return false;
    }
    for (auto* images : {&downsampled, &upsampled}) {
        for (auto& image : *images) {
            scheduler.DeferOperation(
                [old = std::move(image.image), view = std::move(image.view)]() mutable {
                    view.reset();
                    old.Destroy();
                });
        }
        images->clear();
        images->resize(images == &downsampled ? levels : levels - 1);
    }
    width = w;
    height = h;
    const auto device = instance.GetDevice();
    for (auto* images : {&downsampled, &upsampled}) {
        for (u32 level = 0; level < images->size(); ++level) {
            Image& image = (*images)[level];
            image.width = std::max(1u, (w >> level) / 2);
            image.height = std::max(1u, (h >> level) / 2);
            image.image = VideoCore::UniqueImage(device, instance.GetAllocator());
            image.image.Create({
                .imageType = vk::ImageType::e2D, .format = vk::Format::eR16G16B16A16Sfloat,
                .extent = {image.width, image.height, 1}, .mipLevels = 1, .arrayLayers = 1,
                .samples = vk::SampleCountFlagBits::e1, .tiling = vk::ImageTiling::eOptimal,
                .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
                .initialLayout = vk::ImageLayout::eUndefined});
            image.view = Check<"create Froyok working view">(device.createImageViewUnique({
                .image = vk::Image(image.image), .viewType = vk::ImageViewType::e2D,
                .format = vk::Format::eR16G16B16A16Sfloat, .subresourceRange = ColorRange}));
            scheduler.Record([target = vk::Image(image.image)](vk::CommandBuffer cmd) {
                EffectPass::InitGeneral(cmd, target, ColorRange);
            });
        }
    }
    return true;
}

void FroyokBloom::Dispatch(u32 stage, const Push& push, vk::ImageView current,
                           vk::ImageView previous, const Image& output, bool first, bool last) {
    const vk::DescriptorImageInfo in{stage == 2 ? vk::Sampler(*upsample_sampler)
                                                : vk::Sampler(*downsample_sampler),
                                     current, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo before{*upsample_sampler, previous, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo out{{}, *output.view, vk::ImageLayout::eGeneral};
    const u32 groups_x = (output.width + 7) / 8, groups_y = (output.height + 7) / 8;
    scheduler.Record([push, groups_x, groups_y, in, before, out, first, last,
                      pipeline = *pipelines[stage], layout = *layout](vk::CommandBuffer cmd) {
        if (first) {
            EffectPass::FullBarrier(cmd);
        } else {
            EffectPass::ComputeBarrier(cmd);
        }
        const std::array descriptors{
            vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                   .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                                   .pImageInfo = &in},
            vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                   .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                                   .pImageInfo = &before},
            vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                   .descriptorType = vk::DescriptorType::eStorageImage,
                                   .pImageInfo = &out}};
        cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
        cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, descriptors);
        cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
        cmd.dispatch(groups_x, groups_y, 1);
        if (last) {
            EffectPass::FullBarrier(cmd);
        }
    });
}

void FroyokBloom::Generate(VideoCore::ImageId id) {
    stat_unread += ready ? 1 : 0; // the previous pyramid, built and not read
    ready = false;
    if (!id || BbSettings::Get().startup_bloom_quality != BbSettings::BloomQualityFroyok ||
        !Ready()) {
        return;
    }
    scheduler.EndRendering();
    const Source source = Access(id);
    stat_proxy +=
        (source.view && source.width != texture_cache.GetImage(id).info.size.width) ? 1 : 0;
    // bbport: only a Froyok composite reads the pyramid (Composite: 5c02eaf8 compiled with the
    // Froyok blend). Areas with another composite (ccb08339, 5e67d866) never do, and it was built
    // at every DoF recombination (2 a frame). Without a Froyok composite in the last LazyFrames
    // frames the target is only remembered: BeforeComposite builds the pyramid if one comes, the
    // frame end forgets it otherwise. Access above still ran (its proxy fill and layouts are what
    // later passes sample). Experiment mask 2147483648: built every time, as before.
    if (!BbToggle::Experiment(2147483648ull) && frames - composite_frame > LazyFrames) {
        pending = id;
        pending_uid = texture_cache.GetImage(id).image_uid;
        ++stat_waiting;
        return;
    }
    pending = {};
    if (!source.view || !source.width || !source.height || !EnsureImages(source.width, source.height)) {
        if (!reported) {
            reported = true;
            std::printf("Froyok bloom: unavailable for this HDR target; retaining Original Bloom\n");
        }
        return;
    }
    // bbport BB_GPU_PROFILE: the pyramid's dispatches get a row of their own (they were charged
    // to the DoF recombination's pass); the label open before them resumes after the last one.
    GpuProfiler* const profiler =
        GpuProfiler::Get() && GpuProfiler::Get()->Records(&scheduler) ? GpuProfiler::Get() : nullptr;
    const u64 resume_label = profiler ? profiler->Current() : 0;
    if (profiler) {
        profiler->Mark(0x46524F59'50595231ull,
                       [] { return std::string{"Froyok bloom: pyramid (compute)"}; });
    }
    ++stat_built;
    const u32 total = u32(downsampled.size() * 2 - 1);
    u32 issued = 0;
    const auto run = [&](u32 stage, const Push& push, vk::ImageView current,
                         vk::ImageView previous, const Image& output) {
        const bool first = issued == 0;
        const bool last = ++issued == total;
        Dispatch(stage, push, current, previous, output, first, last);
    };
    Push push{.destination_size = {downsampled[0].width, downsampled[0].height},
              .pixel_size = {1.0f / source.width, 1.0f / source.height}, .blend = 0.0f};
    run(1, push, source.view, source.view, downsampled[0]);
    for (size_t level = 1; level < downsampled.size(); ++level) {
        const Image& previous = downsampled[level - 1];
        const Image& output = downsampled[level];
        push = {.destination_size = {output.width, output.height},
                .pixel_size = {1.0f / previous.width, 1.0f / previous.height}, .blend = 0.0f};
        run(0, push, *previous.view, *previous.view, output);
    }
    for (size_t level = downsampled.size() - 1; level-- > 0;) {
        const Image& current = downsampled[level];
        const Image& previous = level + 1 == downsampled.size() - 1 ? downsampled.back()
                                                                      : upsampled[level + 1];
        const Image& output = upsampled[level];
        push = {.destination_size = {output.width, output.height},
                .pixel_size = {1.0f / output.width, 1.0f / output.height},
                .blend = std::clamp(BbSettings::Get().graphics_froyok_bloom_spread.load(
                                         std::memory_order_relaxed), BbSettings::FroyokSpreadMin,
                                     BbSettings::FroyokSpreadMax)};
        run(2, push, *current.view, *previous.view, output);
    }
    ready = true;
    if (profiler && resume_label) {
        profiler->Resume(resume_label);
    }
}

float FroyokBloom::Composite(const Shader::Info& fragment,
                             std::span<vk::DescriptorImageInfo> image_infos) {
    // image_infos holds the fragment stage's four images followed by their samplers.
    if (fragment.pgm_hash == Shader::Native::FroyokCompositeHash && fragment.uses_froyok_bloom) {
        composite_frame = frames; // a reader: built at every recombination again (Generate)
        ++stat_composites;
        stat_without += ready ? 0 : 1;
    }
    if (!ready || fragment.pgm_hash != Shader::Native::FroyokCompositeHash ||
        !fragment.uses_froyok_bloom || fragment.images.size() != 4 || image_infos.size() < 4 ||
        upsampled.empty()) {
        return 0.0f;
    }
    ready = false;
    image_infos[2].imageView = *upsampled[0].view;
    image_infos[2].imageLayout = vk::ImageLayout::eGeneral;
    return std::clamp(BbSettings::Get().graphics_froyok_bloom_blend.load(std::memory_order_relaxed),
                      BbSettings::FroyokBlendMin, BbSettings::FroyokBlendMax);
}

void FroyokBloom::BeforeComposite(const Shader::Info* fragment) {
    if (!pending || ready || !fragment ||
        fragment->pgm_hash != Shader::Native::FroyokCompositeHash ||
        !fragment->uses_froyok_bloom) {
        return;
    }
    const VideoCore::ImageId id = pending;
    pending = {};
    if (!texture_cache.IsRegisteredImage(id, pending_uid)) {
        return;
    }
    // Called before this draw's targets and resources are bound: Generate's EndRendering ends
    // the previous draw's pass, its layouts are set again by this draw's binding.
    composite_frame = frames;
    Generate(id);
    stat_late += ready ? 1 : 0;
}

} // namespace Vulkan
