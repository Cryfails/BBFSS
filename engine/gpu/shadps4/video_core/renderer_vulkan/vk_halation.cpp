// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_halation.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "bbport_toggles.h"
#include "bbport_settings.h" // bbport (r109a_strength-settings-engine)
#include "video_core/host_shaders/halation_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace HP = HalationParams;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto Format = vk::Format::eR16G16B16A16Sfloat;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::DeviceSize SlotBytes = HP::KeySlotBytes;

vk::DescriptorImageInfo Info(vk::ImageView view, vk::Sampler sampler = {}) {
    return {.sampler = sampler, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}
} // namespace

// bbport (r109a_strength-settings-engine): the setting's numbers are the header's (one default).
static_assert(BbSettings::HalationStrengthDefault == HP::DefaultStrength &&
              BbSettings::HalationStrengthMax == HP::MaxStrength &&
              BbSettings::HalationStrengthMin == 0.0f);

StrengthKnob::Value Halation::Strength() {
    static const StrengthKnob::Env env =
        StrengthKnob::ReadEnv(std::getenv("BB_HALATION"), HP::MaxStrength);
    return HP::StrengthOf(
        env, BbSettings::Get().graphics_halation_strength.load(std::memory_order_relaxed));
}

void Halation::StrengthLine() {
    static StrengthKnob::Line line;
    const StrengthKnob::Value s = Strength();
    if (line.Due(LineFrames, s)) {
        BbReport::Printf("Halation (r109a): strength %.2f from the %s (%s)%s\n", double(s.value),
                         StrengthKnob::SourceName(s),
                         s.from_env ? "BB_HALATION" : "graphics_halation_strength",
                         s.value > 0.0f ? "" : "; 0: nothing is drawn");
    }
}

Halation::Halation(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_, bool upscaler_on)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    // bbport (r109a_strength-settings-engine): the strength comes with each frame (Apply); the
    // line gives the gain at strength 1.
    HP::Knobs k = HP::Load();
    k.strength = 1.0f;
    BbReport::Printf("Halation (r95): made at the first frame with a strength above 0, kept from "
                     "now on: radius %.2f (a blur of sigma %.1f pixels at 1080 lines), threshold "
                     "%.2f stops over the frame's key, glow gain %.3f at strength 1, show %u; on "
                     "the scene before the upscaler, at its render size\n",
                     double(k.radius), double(HP::SigmaAt1080 * k.radius),
                     double(HP::ThresholdStops(k)), double(HP::GainOf(k)), k.show);
    if (!upscaler_on) {
        BbReport::Printf("Halation (r95): no place in the frame without the upscaler "
                         "(BB_UPSCALER=none, or this GPU cannot run it); nothing is drawn\n");
    }
}

Halation::~Halation() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(key_buffer);
    FreeBuffer(readback);
}

bool Halation::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void Halation::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool Halation::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, Format) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eLinear) &&
        EffectPass::Create(instance, set_layout, layout, pipeline,
                           {eCombinedImageSampler, eStorageImage, eStorageBuffer},
                           sizeof(HP::Push), HALATION_COMP, "Halation") &&
        MakeBuffer(key_buffer, HP::KeySlots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    // No frame before yet: the line reads zeros (no key) until the second pass.
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void Halation::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Halation (r95): off - %s\n", why);
    ReleaseImages();
}

void Halation::ReleaseImages() {
    for (auto& q : quarter) {
        if (q.image) {
            scheduler.DeferOperation(
                [image = std::move(q.image), view = std::move(q.view)]() mutable {
                    view.reset();
                    image.Destroy();
                });
        }
        q.view.reset();
    }
    quarter_width = quarter_height = 0;
}

bool Halation::EnsureImages(u32 width, u32 height) {
    if (quarter[0].image && quarter_width == width && quarter_height == height) {
        return true;
    }
    ReleaseImages();
    // Eight bytes a texel, two images.
    if (!EffectPass::HasRoom(instance, 16ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    for (u32 i = 0; i < quarter.size(); ++i) {
        auto& q = quarter[i];
        q.image = VideoCore::UniqueImage(device, instance.GetAllocator());
        q.image.Create(vk::ImageCreateInfo{
            .imageType = vk::ImageType::e2D,
            .format = Format,
            .extent = {width, height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        SetObjectName(device, vk::Image(q.image), "Halation quarter {}", i);
        q.view = Check<"create halation image view">(device.createImageViewUnique({
            .image = vk::Image(q.image),
            .viewType = vk::ImageViewType::e2D,
            .format = Format,
            .subresourceRange = ColorLevel,
        }));
    }
    quarter_width = width;
    quarter_height = height;
    return true;
}

vk::ImageView Halation::CachedView(const VideoCore::Image& image) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid) {
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
        .view = Check<"create halation scene view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = Format,
            .subresourceRange = ColorLevel,
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void Halation::Apply(VideoCore::ImageId color_id, float strength) {
    if (applied || failed || !color_id) {
        return;
    }
    applied = true;
    // A menu's 3D preview: its "scene" is one of the previews (the upscaler leaves it too).
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    if (!Ready()) {
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    if (color.info.pixel_format != Format) {
        Fail("the scene colour is not RGBA16F");
        return;
    }
    // The scene's size: the reduced one while a preset renders below the game's own size, else
    // the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    const u32 qw = HP::Quarter(width), qh = HP::Quarter(height);
    if (width < 16 || height < 16 || !HP::KeyFits(qw, qh)) {
        ++stats.small;
        return;
    }
    if (!EnsureImages(qw, qh)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"halation"};
    scheduler.EndRendering();
    vk::ImageView color_view{};
    if (reduced) {
        VideoCore::ImageViewInfo info;
        info.format = color.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the reduced scene colour is not a storage image");
            return;
        }
        color_view = proxy.view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the scene colour is not a storage image");
            return;
        }
        color_view = CachedView(color);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    HP::Knobs k = HP::Load();
    k.strength = strength; // bbport (r109a_strength-settings-engine): this frame's
    const u32 slot = u32(runs & 1);
    // bbport (r109a): also after a long gap (strength 0, menu previews) both slots are cleared
    const bool first = HP::ClearsKey(runs, frame_ends, ran_at_end);
    ran_at_end = frame_ends;
    ++runs;
    ++stats.ran;
    if (width != last_width || height != last_height) {
        last_width = width;
        last_height = height;
        BbReport::Printf("Halation (r95): on at %ux%u (%s), quarter %ux%u, blur sigma %.2f "
                         "quarter texels, %u a side\n",
                         width, height, reduced ? "reduced scene" : "the game's scene", qw, qh,
                         double(HP::Sigma(k, height)), HP::Taps(HP::Sigma(k, height)));
    }
    std::array<HP::Push, HP::ModeCount> push{};
    for (u32 mode = 0; mode < HP::ModeCount; ++mode) {
        push[mode] = HP::Make(k, width, height, slot, HP::Mode(mode));
    }

    EffectPass::Mark(95, "halation");
    scheduler.RecordCrumb(
        {.name = "halation"},
        [push, width, height, qw, qh, slot, first, color_view, sampler = *sampler,
         a_image = vk::Image(quarter[0].image), b_image = vk::Image(quarter[1].image),
         a_view = *quarter[0].view, b_view = *quarter[1].view, key = key_buffer.buffer,
         host = readback.buffer, pipeline = *pipeline,
         layout = *layout](vk::CommandBuffer cmd) {
            // The scene's writes before this, and the frame before's reads of the images and of
            // the key's slots.
            EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute | Transfer,
                                      ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                          vk::AccessFlagBits2::eTransferWrite);
            std::array<vk::ImageMemoryBarrier2, 2> to_general;
            to_general.fill({
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .subresourceRange = ColorLevel,
            });
            to_general[0].image = a_image;
            to_general[1].image = b_image;
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = u32(to_general.size()),
                                  .pImageMemoryBarriers = to_general.data()});
            // The frame before's slot to the host (the line's numbers); this frame's slot cleared.
            // The first pass has no frame before: both slots cleared.
            if (first) {
                cmd.fillBuffer(key, 0, HP::KeySlots * SlotBytes, 0);
            } else {
                cmd.copyBuffer(key, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
                cmd.fillBuffer(key, slot * SlotBytes, SlotBytes, 0);
            }
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                      Compute | vk::PipelineStageFlagBits2::eHost,
                                      ReadWrite | vk::AccessFlagBits2::eHostRead);
            const vk::DescriptorBufferInfo key_info{key, 0, HP::KeySlots * SlotBytes};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            const auto run = [&](const HP::Push& p, vk::ImageView source, vk::ImageView target,
                                 u32 w, u32 h) {
                using enum vk::DescriptorType;
                const std::array infos{Info(source, sampler), Info(target)};
                const std::array writes{
                    vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                           .descriptorType = eCombinedImageSampler,
                                           .pImageInfo = &infos[0]},
                    vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                           .descriptorType = eStorageImage, .pImageInfo = &infos[1]},
                    vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                           .descriptorType = eStorageBuffer,
                                           .pBufferInfo = &key_info},
                };
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(p), &p);
                cmd.dispatch((w + HP::Group - 1) / HP::Group, (h + HP::Group - 1) / HP::Group, 1);
            };
            run(push[HP::Down], color_view, a_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::BlurX], a_view, b_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::BlurY], b_view, a_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::Add], a_view, color_view, width, height);
            EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

void Halation::OnFrameEnd() {
    applied = false;
    ++frame_ends; // bbport (r109a_strength-settings-engine): HalationParams::ClearsKey
    if (++stats.frames < LineFrames) {
        return;
    }
    // The host copy of a recent frame's key slot (no fence is waited for: a log line).
    std::array<u32, HP::KeySlotWords> words{};
    if (readback.mapped) {
        std::memcpy(words.data(), readback.mapped, sizeof(words));
    }
    const auto& k = HP::Load();
    const double key = HP::KeyOf(words[0], words[1]);
    const double pixels = double(words[1]) * 16.0;
    BbReport::Printf("Halation (r95): of %u frames, the glow drawn on %u at %ux%u; skipped: %u "
                     "menu previews, %u too small or too large, %u for want of video memory; a "
                     "recent frame's key %.4g (log-mean scene luminance), threshold %.4g, %.3f%% "
                     "of its pixels over it%s\n",
                     stats.frames, stats.ran, last_width, last_height, stats.previews, stats.small,
                     stats.no_room, key, key * std::exp2(double(HP::ThresholdStops(k))),
                     pixels > 0.0 ? 100.0 * double(words[2]) / pixels : 0.0,
                     failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
