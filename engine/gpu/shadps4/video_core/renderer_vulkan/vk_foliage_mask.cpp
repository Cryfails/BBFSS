// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_foliage_mask.h"

#include <algorithm>
#include <cstdlib>

#include "shader_recompiler/runtime_info.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {
namespace {
constexpr auto Format = vk::Format::eR8Unorm;
constexpr auto Usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eSampled |
                       vk::ImageUsageFlagBits::eTransferDst;
constexpr vk::ImageSubresourceRange Range{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr auto Attachment = vk::ImageLayout::eColorAttachmentOptimal;
// FoliageGlow descriptors use General, including the dynamically unused fallback.
constexpr auto Read = vk::ImageLayout::eGeneral;
} // namespace

bool FoliageMask::Requested() {
    static const bool on = [] {
        const char* value = std::getenv("BB_FOLIAGE_MASK");
        return value && value[0] == '1' && value[1] == '\0';
    }();
    return on;
}

bool FoliageMask::Supported(const Instance& instance) {
    constexpr auto features = vk::FormatFeatureFlagBits2::eColorAttachment |
                              vk::FormatFeatureFlagBits2::eSampledImage |
                              vk::FormatFeatureFlagBits2::eTransferDst;
    const auto limits = instance.GetPhysicalDevice().getProperties().limits;
    if (!instance.GetPhysicalDevice().getFeatures().independentBlend ||
        !FoliageMaskRules::SupportedLimits(limits.maxPushConstantsSize,
            Shader::FoliageMaskOutput::PushSize, limits.maxColorAttachments,
            Shader::FoliageMaskOutput::Location + 1, instance.IsFormatSupported(Format, features))) {
        return false;
    }
    const auto [result, properties] = instance.GetPhysicalDevice().getImageFormatProperties(
        Format, vk::ImageType::e2D, vk::ImageTiling::eOptimal, Usage, {});
    return result == vk::Result::eSuccess && bool(properties.sampleCounts & vk::SampleCountFlagBits::e1);
}

FoliageMask::FoliageMask(const Instance& instance_, Scheduler& scheduler_)
    : instance{instance_}, scheduler{scheduler_} {}

FoliageMask::~FoliageMask() {
    for (auto& target : targets) {
        if (!target.image) {
            continue;
        }
        const auto device = instance.GetDevice();
        const auto allocator = instance.GetAllocator();
        scheduler.DeferOperation([device, allocator, target] {
            device.destroyImageView(target.view);
            vmaDestroyImage(allocator, target.image, target.allocation);
        }, "foliage mask");
    }
}

void FoliageMask::Destroy(Target& target) {
    if (target.image) {
        instance.GetDevice().destroyImageView(target.view);
        vmaDestroyImage(instance.GetAllocator(), target.image, target.allocation);
        target = {};
    }
}

bool FoliageMask::Allocate(Target& target, vk::Extent2D extent) {
    Destroy(target); // caller checked the last submission tick
    const vk::ImageCreateInfo info{
        .imageType = vk::ImageType::e2D,
        .format = Format,
        .extent = {extent.width, extent.height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = Usage,
    };
    const VmaAllocationCreateInfo allocation{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage image{};
    if (vmaCreateImage(instance.GetAllocator(), &static_cast<const VkImageCreateInfo&>(info),
                       &allocation, &image, &target.allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    target.image = image;
    const auto [result, view] = instance.GetDevice().createImageView({
        .image = target.image,
        .viewType = vk::ImageViewType::e2D,
        .format = Format,
        .subresourceRange = Range,
    });
    if (result != vk::Result::eSuccess) {
        Destroy(target);
        return false;
    }
    target.view = view;
    target.extent = extent;
    return true;
}

bool FoliageMask::BeginEpoch(const Key& key) {
    if (!epoch.Begin(key)) {
        return false;
    }
    active = nullptr;
    needs_clear = false;
    const vk::Extent2D extent{key.width, key.height};
    // Same-extent images can be reused in submission order through Transition.
    auto slot = std::ranges::find(targets, extent, &Target::extent);
    if (slot == targets.end()) {
        slot = std::ranges::find_if(targets, [&](const Target& target) {
            return !target.image || scheduler.IsFree(target.last_tick);
        });
        if (slot == targets.end() || !Allocate(*slot, extent)) {
            Invalidate(Refusal::Allocation);
            return false;
        }
    }
    active = &*slot;
    needs_clear = true;
    return true;
}

void FoliageMask::Transition(Target& target, vk::ImageLayout layout, bool clear) {
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    scheduler.EndRendering();
    const auto barrier = [&](vk::ImageLayout from, vk::ImageLayout to, vk::PipelineStageFlags2 src,
                             vk::AccessFlags2 src_access, vk::PipelineStageFlags2 dst,
                             vk::AccessFlags2 dst_access) {
        return vk::ImageMemoryBarrier2{
            .srcStageMask = src,
            .srcAccessMask = src_access,
            .dstStageMask = dst,
            .dstAccessMask = dst_access,
            .oldLayout = from,
            .newLayout = to,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = target.image,
            .subresourceRange = Range,
        };
    };
    constexpr auto transfer = vk::ImageLayout::eTransferDstOptimal;
    const auto image = target.image;
    const auto attachment_access = Access::eColorAttachmentRead | Access::eColorAttachmentWrite;
    const auto before = barrier(target.layout, transfer, Stage::eAllCommands,
                                Access::eMemoryRead | Access::eMemoryWrite,
                                Stage::eClear, Access::eTransferWrite);
    const auto after = clear
        ? barrier(transfer, layout, Stage::eClear, Access::eTransferWrite,
                  Stage::eColorAttachmentOutput, attachment_access)
        : barrier(target.layout, layout, Stage::eColorAttachmentOutput, attachment_access,
                  Stage::eComputeShader, Access::eShaderSampledRead);
    scheduler.Record([image, clear, before, after](vk::CommandBuffer cmd) {
        if (clear) {
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &before});
            cmd.clearColorImage(image, transfer, vk::ClearColorValue{std::array<float, 4>{}}, Range);
        }
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &after});
    });
    target.layout = layout;
    target.last_tick = scheduler.CurrentTick();
}

bool FoliageMask::Attach(const Key& key, RenderState& state) {
    constexpr auto location = Shader::FoliageMaskOutput::Location;
    if (!active || !epoch.Valid(key) || active->layout == Read && !needs_clear) {
        return false;
    }
    if ((state.num_color_attachments > location && state.color_attachments[location].image_view) ||
        state.width != key.width ||
        state.height != key.height || state.num_layers != 1) {
        Invalidate(Refusal::Targets);
        return false;
    }
    if (needs_clear) {
        Transition(*active, Attachment, true);
        needs_clear = false;
    }
    active->last_tick = scheduler.CurrentTick();
    return ResumeAttachment(key, state);
}

bool FoliageMask::ResumeAttachment(const Key& key, RenderState& state) const {
    constexpr auto location = Shader::FoliageMaskOutput::Location;
    if (!active || !epoch.Valid(key) || needs_clear || active->layout != Attachment) {
        return false;
    }
    for (u32 i = state.num_color_attachments; i < location; ++i) {
        state.color_attachments[i] = {};
    }
    state.color_attachments[location] = {.image_view = active->view, .image_layout = Attachment};
    state.num_color_attachments = std::max<uint16_t>(state.num_color_attachments, location + 1);
    return true;
}

void FoliageMask::NoteClass(bool tagged) {
    if (tagged && active && !needs_clear) {
        epoch.NoteTag();
    }
}

void FoliageMask::Invalidate(Refusal reason) {
    epoch.Refuse(reason);
}

vk::ImageView FoliageMask::ReadableMask(const Key& key) {
    if (!active || needs_clear || !epoch.Readable(key)) {
        return {};
    }
    if (active->layout != Read) {
        Transition(*active, Read, false);
    }
    active->last_tick = scheduler.CurrentTick();
    return active->view;
}

void FoliageMask::OnFrameEnd() {
    Invalidate(Refusal::Boundary);
    active = nullptr;
}

} // namespace Vulkan
