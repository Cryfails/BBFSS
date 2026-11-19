// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#ifdef BB_TEST_SHARED_POST_GRAPH
#include <vector>
#include "video_core/renderer_vulkan/vk_sewer_motion_present.h"
#ifdef BB_TEST_POST_PRESENT_RESOURCES
#include "video_core/renderer_vulkan/vk_native_write_suffix.h"
#endif

namespace Vulkan::SewerPresent {

struct CandidateIdentity {
    SewerMotion::MergeToken merge{};
    Override display{};
    vk::ImageView attachment{};
    u64 generation{}, write{}, allocation{};

    bool Same(const CandidateIdentity& other) const {
        return SameMerge(merge, other.merge) && display.address == other.display.address &&
               display.image == other.display.image && display.format == other.display.format &&
               display.extent == other.display.extent && display.draw_timeline == other.display.draw_timeline &&
               display.draw_tick == other.display.draw_tick && attachment == other.attachment &&
               generation == other.generation && write == other.write && allocation == other.allocation;
    }

    bool MatchesOverride(const Override& actual) const {
        return actual.address == display.address && actual.image == display.image &&
               actual.format == display.format && actual.extent == display.extent &&
               actual.draw_timeline == display.draw_timeline && actual.draw_tick >= display.draw_tick;
    }
};

struct CandidateLease {};

#ifdef BB_TEST_POST_PRESENT_RESOURCES
} // namespace Vulkan::SewerPresent

namespace Vulkan::PostPresentResources {

inline constexpr vk::Extent2D OrdinaryExtent{3840, 2160};

struct OrderTokens {
    NativeWriteSuffix::PostToken display{}, barrier{}, postprocess{};

    bool Valid() const {
        using enum NativeWriteSuffix::PostRole;
        return display && display.role == Display &&
               barrier && barrier.role == PrepareBarrier &&
               postprocess && postprocess.role == PreparePostprocess &&
               display.capture == barrier.capture && barrier.capture == postprocess.capture &&
               display.operation != barrier.operation && barrier.operation != postprocess.operation &&
               display.operation != postprocess.operation;
    }

    bool Empty() const { return display == NativeWriteSuffix::PostToken{} &&
                                barrier == NativeWriteSuffix::PostToken{} &&
                                postprocess == NativeWriteSuffix::PostToken{}; }
};

struct PreparedBinding {
    vk::Image image{};
    vk::ImageView view{};
    vk::Fence fence{};
    vk::Semaphore ready{};
    u64 ready_tick{}, incarnation{};
    vk::Format format{};

    template <typename Source>
    static PreparedBinding From(const Source& source, u64 incarnation) {
        return {source.image, source.view, source.fence, source.ready, source.ready_tick,
                incarnation, source.format};
    }
};

struct ResourceImage {
    vk::Image image{};
    vk::ImageView view{};
    u64 allocation{}, backing{}, write{};
    vk::Format format{};
    vk::Extent2D extent{};
    bool operator==(const ResourceImage&) const = default;
    bool Valid() const {
        return image && view && allocation && backing && write && format != vk::Format::eUndefined &&
               extent == OrdinaryExtent;
    }
};

struct DriverSubmission {
    using Semaphore = NativeWriteSuffix::QueueSubmit::Semaphore;
    vk::Queue queue{};
    vk::Fence fence{};
    vk::Semaphore timeline{};
    vk::Result result{};
    vk::CommandBuffer command{};
    u64 tick{}, order{};
    u32 family{}, submitted_index{}, segment{}, wait_count{}, signal_count{};
    std::array<Semaphore, 4> waits{}, signals{};
    bool observed{}, shaped{}, found{};

    static DriverSubmission Copy(const NativeWriteSuffix::QueueSubmitInput& actual, u64 tick,
                                 std::span<const vk::CommandBuffer> commands,
                                 std::span<const vk::CommandBuffer> segments, vk::CommandBuffer expected) {
        DriverSubmission out{};
        out.queue = actual.queue;
        out.family = actual.family;
        out.fence = actual.fence;
        out.timeline = actual.timeline;
        out.result = actual.result;
        out.command = expected;
        out.tick = tick;
        out.order = actual.graphics_sequence;
        out.observed = true;
        out.shaped = actual.metadata_complete && actual.waits.size() == actual.wait_values.size() &&
                     actual.waits.size() == actual.wait_stages.size() &&
                     actual.signals.size() == actual.signal_values.size() &&
                     actual.waits.size() <= out.waits.size() && actual.signals.size() <= out.signals.size();
        if (expected && std::ranges::count(commands, expected) == 1 &&
            std::ranges::count(segments, expected) == 1) {
            out.found = true;
            out.submitted_index = u32(std::ranges::find(commands, expected) - commands.begin());
            out.segment = u32(std::ranges::find(segments, expected) - segments.begin());
        }
        if (!out.shaped) return out;
        out.wait_count = u32(actual.waits.size());
        out.signal_count = u32(actual.signals.size());
        for (u32 i = 0; i < out.wait_count; ++i)
            out.waits[i] = {actual.waits[i], actual.wait_values[i], actual.wait_stages[i]};
        for (u32 i = 0; i < out.signal_count; ++i)
            out.signals[i] = {actual.signals[i], actual.signal_values[i], {}};
        return out;
    }

    bool Valid() const {
        return observed && shaped && found && queue && timeline && tick && order &&
               wait_count <= waits.size() && signal_count <= signals.size() && result == vk::Result::eSuccess;
    }

    const Semaphore* Wait(vk::Semaphore handle, u64 value) const {
        if (!handle || wait_count > waits.size()) return nullptr;
        const Semaphore* found_wait = nullptr;
        for (const auto& wait : std::span(waits).first(wait_count)) {
            if (wait.handle == handle) {
                if (found_wait || wait.value != value || !wait.stages) return nullptr;
                found_wait = &wait;
            }
        }
        return found_wait;
    }

    bool Signal(vk::Semaphore handle, u64 value) const {
        if (!handle || signal_count > signals.size()) return false;
        const auto rows = std::span(signals).first(signal_count);
        return std::ranges::count_if(rows, [handle](const Semaphore& s) { return s.handle == handle; }) == 1 &&
               std::ranges::any_of(rows, [handle, value](const Semaphore& s) {
                   return s.handle == handle && s.value == value;
               });
    }
};

struct ResourcePosition {
    using Position = NativeWriteSuffix::Position;
    Position where{};
    vk::Queue queue{};
    vk::Semaphore timeline{};
    u64 order{};
    u32 family{};
    bool submitted{};

    static ResourcePosition From(const NativeWriteSuffix::PostReceipt& receipt,
                                 NativeWriteSuffix::PostToken token, NativeWriteSuffix::PostKey key) {
        const auto& where = receipt.where;
        const auto& actual = receipt.submission;
        const bool joined = token && receipt.token == token && receipt.key == key && where.submitted &&
            receipt.stream_joined && receipt.gaps == 0 &&
            (receipt.phase == NativeWriteSuffix::PostPhase::Submitted ||
             receipt.phase == NativeWriteSuffix::PostPhase::Retired) && where.tick && where.buffer && where.encoding &&
            actual.tick == where.tick && actual.result == vk::Result::eSuccess && actual.input_joined &&
            actual.queue && actual.timeline && actual.graphics_sequence &&
            where.submitted_index < actual.buffer_count &&
            actual.buffer_count <= actual.buffers.size() &&
            actual.buffers[where.submitted_index].buffer == where.buffer &&
            actual.buffers[where.submitted_index].segment == where.segment;
        return {where, actual.queue, actual.timeline, actual.graphics_sequence, actual.family, joined};
    }
};

struct FrameResources {
    NativeWriteSuffix::PostKey key{};
    ResourceImage input{}, target{}, retired_target{};
    vk::ImageMemoryBarrier2 display_read{}, target_attachment{}, target_read{};
    vk::CommandBuffer display_barrier_cmd{}, postprocess_cmd{}, blit_cmd{};
    vk::ImageBlit blit{};
    vk::Image swap{};
    ResourcePosition display_order{}, barrier_order{}, postprocess_order{};
    DriverSubmission prepare{}, present{};
    bool epoch{}, postprocess{}, blit_encoded{}, app_present{}, frame_fenced{};

    static bool Whole(vk::ImageSubresourceRange range) {
        return range.aspectMask == vk::ImageAspectFlagBits::eColor && range.baseMipLevel == 0 &&
               range.levelCount == 1 && range.baseArrayLayer == 0 &&
               (range.layerCount == 1 || range.layerCount == VK_REMAINING_ARRAY_LAYERS);
    }

    template <typename Identity>
    bool SourceRead(const Identity& key) const {
        return SourceRead(key.display.image, key.allocation, key.generation, key.write);
    }

    bool SourceRead(vk::Image image, u64 allocation, u64 generation, u64 write) const {
        using Stage = vk::PipelineStageFlagBits2;
        using Access = vk::AccessFlagBits2;
        constexpr vk::ImageSubresourceRange color0{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
        return epoch && input.Valid() && input.image == image &&
               input.allocation == allocation && input.backing == generation && input.write == write &&
               display_barrier_cmd && display_read.image == input.image && display_read.subresourceRange == color0 &&
               display_read.oldLayout == vk::ImageLayout::eGeneral &&
               display_read.newLayout == vk::ImageLayout::eShaderReadOnlyOptimal &&
               display_read.srcQueueFamilyIndex == display_read.dstQueueFamilyIndex &&
               (display_read.srcStageMask & Stage::eColorAttachmentOutput) &&
               (display_read.srcAccessMask & Access::eColorAttachmentWrite) &&
               (display_read.dstStageMask & (Stage::eFragmentShader | Stage::eAllGraphics | Stage::eAllCommands)) &&
               (display_read.dstAccessMask & (Access::eShaderRead | Access::eShaderSampledRead));
    }

    bool DrawOrder(vk::Semaphore timeline, u64 ready_tick) const {
        if (!display_order.submitted || !barrier_order.submitted || !postprocess_order.submitted ||
            !prepare.Valid() || prepare.tick != ready_tick || prepare.timeline != timeline ||
            display_order.timeline != timeline || barrier_order.timeline != timeline ||
            postprocess_order.timeline != timeline || display_order.queue != prepare.queue ||
            barrier_order.queue != prepare.queue || postprocess_order.queue != prepare.queue ||
            display_order.family != prepare.family || barrier_order.family != prepare.family ||
            postprocess_order.family != prepare.family || postprocess_order.order != prepare.order ||
            barrier_order.where.buffer != display_barrier_cmd ||
            postprocess_order.where.buffer != postprocess_cmd || prepare.command != postprocess_cmd ||
            postprocess_order.where.tick != ready_tick ||
            postprocess_order.where.submitted_index != prepare.submitted_index ||
            postprocess_order.where.segment != prepare.segment) return false;
        const auto ordered = [](const ResourcePosition& earlier, const ResourcePosition& later) {
            return earlier.where.StreamKey() < later.where.StreamKey() &&
                   (earlier.where.tick == later.where.tick ? earlier.order == later.order
                                                          : earlier.order < later.order);
        };
        return ordered(display_order, barrier_order) && ordered(barrier_order, postprocess_order) &&
               prepare.Signal(timeline, ready_tick);
    }

    bool BlitSource(const SewerPresent::PresentSource& source) const {
        return BlitSource(PreparedBinding::From(source, source.frame_generation));
    }

    bool BlitSource(const PreparedBinding& source) const {
        using Stage = vk::PipelineStageFlagBits2;
        using Access = vk::AccessFlagBits2;
        constexpr vk::ImageSubresourceLayers layer{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
        constexpr std::array rect{vk::Offset3D{0, 0, 0}, vk::Offset3D{3840, 2160, 1}};
        return postprocess && blit_encoded && blit_cmd && swap && target.Valid() && target == retired_target &&
               target.image == source.image && target.view == source.view && target.write == source.incarnation &&
               target.format == source.format && target.allocation != input.allocation && target.image != input.image &&
               input.image != swap && target.image != swap &&
               target_attachment.image == target.image && Whole(target_attachment.subresourceRange) &&
               target_attachment.newLayout == vk::ImageLayout::eColorAttachmentOptimal &&
               target_attachment.srcQueueFamilyIndex == target_attachment.dstQueueFamilyIndex &&
               (target_attachment.dstStageMask & Stage::eColorAttachmentOutput) &&
               (target_attachment.dstAccessMask & Access::eColorAttachmentWrite) &&
               blit.srcSubresource == layer && blit.dstSubresource == layer &&
               blit.srcOffsets == rect && blit.dstOffsets == rect &&
               target_read.image == target.image && Whole(target_read.subresourceRange) &&
               target_read.oldLayout == vk::ImageLayout::eGeneral &&
               target_read.newLayout == vk::ImageLayout::eTransferSrcOptimal &&
               target_read.srcQueueFamilyIndex == target_read.dstQueueFamilyIndex &&
               (target_read.srcStageMask & (Stage::eAllCommands | Stage::eAllGraphics | Stage::eColorAttachmentOutput)) &&
               (target_read.srcAccessMask & Access::eColorAttachmentWrite) &&
               (target_read.dstStageMask & Stage::eAllTransfer) && (target_read.dstAccessMask & Access::eTransferRead);
    }

    bool AppSubmission(const SewerPresent::PresentSource& source, vk::Semaphore acquire, vk::Semaphore ready,
                       vk::Semaphore timeline, u64 tick) const {
        return AppSubmission(PreparedBinding::From(source, source.frame_generation), acquire, ready, timeline, tick);
    }

    bool AppSubmission(const PreparedBinding& source, vk::Semaphore acquire, vk::Semaphore ready,
                       vk::Semaphore timeline, u64 tick) const {
        using Stage = vk::PipelineStageFlagBits;
        const auto* acquire_wait = present.Wait(acquire, 1);
        return present.Valid() && present.command == blit_cmd && present.timeline == timeline &&
               present.tick == tick && present.fence == source.fence &&
               acquire != source.ready && acquire != ready && ready != source.ready && timeline != source.ready &&
               acquire_wait && (acquire_wait->stages & (Stage::eAllCommands | Stage::eTransfer)) &&
               present.Wait(source.ready, source.ready_tick) && present.Signal(ready, 1) &&
               present.Signal(timeline, tick) && app_present && frame_fenced;
    }

    bool TransferWait(const SewerPresent::PresentSource& source) const {
        return TransferWait(PreparedBinding::From(source, source.frame_generation));
    }

    bool TransferWait(const PreparedBinding& source) const {
        const auto* wait = present.Wait(source.ready, source.ready_tick);
        return wait && bool(wait->stages & (vk::PipelineStageFlagBits::eTransfer |
                                           vk::PipelineStageFlagBits::eAllCommands));
    }

    bool SameQueueBarrier(const SewerPresent::PresentSource& source) const {
        return SameQueueBarrier(PreparedBinding::From(source, source.frame_generation));
    }

    bool SameQueueBarrier(const PreparedBinding& source) const {
        return prepare.Valid() && present.Valid() && prepare.queue == present.queue &&
               prepare.family == present.family && prepare.order < present.order && BlitSource(source);
    }
};

} // namespace Vulkan::PostPresentResources

namespace Vulkan::SewerPresent {
using PostPresentResources::DriverSubmission;
using PostPresentResources::FrameResources;
using PostPresentResources::ResourceImage;
using PostPresentResources::ResourcePosition;
#endif
// Raw presenter result. Only the existing app present and frame fence qualify these bytes.
struct FencedFrame {
    FencedFrame() = default;
    FencedFrame(FencedFrame&&) = default;
    FencedFrame& operator=(FencedFrame&&) = default;
    FencedFrame(const FencedFrame&) = delete;
    FencedFrame& operator=(const FencedFrame&) = delete;

    CandidateIdentity identity{};
    PresentSource source{};
    vk::ImageView pp_input{};
    vk::Format pp_format{};
    vk::SwapchainKHR swap{};
    vk::Image swap_image{};
    vk::Semaphore present_timeline{}, swap_ready{}, acquire{};
    u64 serial{}, submit_ns{}, result_ns{}, present_tick{};
    u32 slot{}, swap_index{};
    Regions regions{};
    std::vector<std::byte> bytes;
    std::shared_ptr<const CandidateLease> lease;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    FrameResources resources{};
#endif

    bool Valid() const {
        return lease && SameSource(source, source) && pp_input && pp_format != vk::Format::eUndefined &&
               swap && swap_image && swap_ready && acquire && present_timeline && serial && present_tick &&
               submit_ns && result_ns >= submit_ns && regions.Valid(identity.merge.key.checkpoint) &&
               bytes.size() == regions.count * PatchBytes && source.image != identity.display.image &&
               source.ready == identity.display.draw_timeline && source.ready_tick >= identity.display.draw_tick;
    }
};

struct Candidate {
    SewerMotion::MergeToken merge{};
    Override display{};
    vk::ImageView display_attachment{};
    u64 display_generation{}, display_write{}, display_allocation{};
    Regions regions{};
    std::function<bool(const Override&, u64 generation, u64 write)> consume_epoch;
    std::function<void(Result, std::optional<FencedFrame>)> complete;
    std::shared_ptr<const CandidateLease> lease; // Presenter-owned bound on pending or held bytes.
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    NativeWriteSuffix::PostToken display_order{}, prepare_barrier_order{}, prepare_postprocess_order{};
#endif

    CandidateIdentity Identity() const {
        return {merge, display, display_attachment, display_generation, display_write, display_allocation};
    }

    bool Valid(const SewerMotion::MergeToken& current) const {
        const auto& key = current.key;
        return key.request && key.scene && key.frame && key.loading && key.generation &&
               key.checkpoint >= 'A' && key.checkpoint <= 'C' && SameMerge(merge, current) &&
               current.destination.id && current.destination.uid && current.destination.image &&
               current.destination.view && current.destination.aspect == vk::ImageAspectFlagBits::eColor &&
               current.output && current.output_view && current.mode == 0 && current.write &&
               current.timeline && current.tick && display.address && display.image && display_attachment &&
               DisplayColor(display.format) && display.extent == Extent &&
               display.draw_timeline == current.timeline && display.draw_tick >= current.tick &&
               display_generation && display_write && display_allocation &&
               regions.Valid(key.checkpoint) && consume_epoch && complete;
    }
};

// Caller copies these from actual issued and immutable submitted command facts. The positive
// lineage includes the exact original tonemap, UI and display version for this candidate.
struct RenderRetirement {
    SewerMotion::MergeToken merge{};
    Override display{};
    vk::ImageView display_attachment{};
    u64 display_generation{}, display_write{}, display_allocation{};
    vk::CommandBuffer command{};
    u64 submission{}, incarnation{};
    u32 ordinal{}, segment{};
    u64 submitted_tick{}, completed_tick{}, tonemap_write{};
    bool submitted{}, fenced{}, lineage{};
    Regions regions{};

    CandidateIdentity Identity() const {
        return {merge, display, display_attachment, display_generation, display_write, display_allocation};
    }

    bool Joins(const FencedFrame& frame) const {
        if (!submitted || !fenced || !lineage || !command || !submission || !incarnation || !ordinal ||
            !submitted_tick || submitted_tick != display.draw_tick || completed_tick < submitted_tick ||
            !tonemap_write || !frame.Valid() || !frame.identity.Same(Identity()) ||
            submitted_tick > frame.source.ready_tick || regions.count != frame.regions.count) return false;
        for (u32 i = 0; i < regions.count; ++i) {
            if (regions.points[i].role != frame.regions.points[i].role ||
                regions.points[i].centre != frame.regions.points[i].centre) return false;
        }
        return true;
    }
};

#ifdef BB_TEST_POST_PRESENT_RESOURCES
inline bool JoinsResources(const FencedFrame& frame, const RenderRetirement& render) {
    const auto& r = frame.resources;
    const auto& display = r.display_order.where;
    return r.SourceRead(frame.identity) && r.input.view == frame.pp_input && r.input.format == frame.pp_format &&
           r.DrawOrder(frame.source.ready, frame.source.ready_tick) &&
           display.buffer == render.command && display.tick == render.submitted_tick &&
           display.tick == render.submission && display.tick == render.incarnation && display.encoding == render.ordinal &&
           display.submitted_index == render.segment && r.swap == frame.swap_image &&
           r.AppSubmission(frame.source, frame.acquire, frame.swap_ready, frame.present_timeline, frame.present_tick) &&
           r.SameQueueBarrier(frame.source);
}

#endif
bool OfferDisplayCandidate(Candidate);

// Only the caller invokes this after receiving both retirements. Moving the raw packet releases
// its lease and pixels on either outcome. The caller owns Checkpoint::FinishPresentation.
bool PublishFinal(FencedFrame frame, const RenderRetirement& render);

} // namespace Vulkan::SewerPresent
#endif
