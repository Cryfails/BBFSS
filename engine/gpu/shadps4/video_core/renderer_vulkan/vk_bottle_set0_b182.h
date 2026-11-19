// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include <array>
#include <atomic>
#include <span>
#include <thread>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::BottleDisplay182 {
struct DescriptorKey {
    u32 request{}, frame{};
    u64 scene{}, epoch{}, address{};
    explicit operator bool() const { return request && frame && scene && epoch && address; }
};

enum class BindRoute : u8 { None, InlinePush, BulkPush, RebasedPush, UpdatedSet };
inline const char* Wire(BindRoute route) {
    switch (route) {
    case BindRoute::InlinePush: return "inline-push";
    case BindRoute::BulkPush: return "bulk-push";
    case BindRoute::RebasedPush: return "rebased-push";
    case BindRoute::UpdatedSet: return "updated-set";
    case BindRoute::None: return "unknown";
    }
    return "unknown";
}

struct DescriptorSlots {
    std::array<vk::DescriptorImageInfo, 3> images{};
    vk::DescriptorBufferInfo clip{};
    u32 count{}, mask{};
    bool valid{};
    bool operator==(const DescriptorSlots&) const = default;
};

inline DescriptorSlots InspectSet0(std::span<const vk::WriteDescriptorSet> writes,
                                   vk::DescriptorSet update = {}) {
    DescriptorSlots out{.count = u32(writes.size())};
    if (writes.size() != 4) return out;
    for (const auto& w : writes) {
        if (w.pNext || w.dstSet != update || w.dstArrayElement || w.descriptorCount != 1 ||
            w.dstBinding > 3 || (out.mask & (1u << w.dstBinding)) || w.pTexelBufferView) return out;
        out.mask |= 1u << w.dstBinding;
        if (w.dstBinding == 3) {
            if (w.descriptorType != vk::DescriptorType::eStorageBuffer || w.pImageInfo || !w.pBufferInfo)
                return out;
            out.clip = *w.pBufferInfo;
            continue;
        }
        if (!w.pImageInfo || w.pBufferInfo) return out;
        const auto& image = *w.pImageInfo;
        if (w.dstBinding < 2) {
            if (w.descriptorType != vk::DescriptorType::eSampledImage || !image.imageView || image.sampler ||
                (image.imageLayout != vk::ImageLayout::eGeneral &&
                 (w.dstBinding != 1 || image.imageLayout != vk::ImageLayout::eShaderReadOnlyOptimal))) return out;
        } else if (w.descriptorType != vk::DescriptorType::eSampler || !image.sampler || image.imageView) {
            return out;
        }
        out.images[w.dstBinding] = image;
    }
    out.valid = out.mask == 15 && out.images[0].imageView != out.images[1].imageView;
    return out;
}

struct DescriptorOrigin {
    const void* scheduler{};
    vk::Semaphore timeline{};
    vk::CommandBuffer command{};
    u64 tick{};
    u32 segment{};
    bool worker{};
    explicit operator bool() const { return scheduler && timeline && command && tick; }
    bool operator==(const DescriptorOrigin&) const = default;
};

struct DescriptorCommit {
    DescriptorOrigin origin{};
    vk::PipelineLayout layout{};
    vk::DescriptorSet set{};
    DescriptorSlots actual{};
    BindRoute route{};
    bool encoded{};
};

struct DescriptorDraw {
    DescriptorOrigin origin{};
    vk::ImageView output{};
    bool ordered{}, operands{}, ancillary{}, physical{};
};

class DescriptorTicket {
public:
    DescriptorTicket(DescriptorKey key_, vk::PipelineLayout layout_, const void* scheduler_,
                     vk::Semaphore timeline_, DescriptorSlots planned_, bool stage_match_, bool clip_disabled_)
        : key(key_), layout(layout_), scheduler(scheduler_), timeline(timeline_),
          producer(std::this_thread::get_id()), planned(planned_), stage_match(stage_match_),
          clip_disabled(clip_disabled_) {}

    void NoteBind(DescriptorOrigin position, vk::PipelineBindPoint point, vk::PipelineLayout actual_layout,
                  DescriptorSlots actual, BindRoute route, vk::DescriptorSet set = {}) {
        if (bind_seen.exchange(true, std::memory_order_acq_rel)) {
            duplicate.store(true, std::memory_order_release);
            return;
        }
        bound = {position, actual_layout, set, actual, route,
                 bool(position) && position.scheduler == scheduler && position.timeline == timeline &&
                 point == vk::PipelineBindPoint::eGraphics && layout && actual_layout == layout &&
                 route != BindRoute::None && (route == BindRoute::UpdatedSet) == bool(set)};
        bind_ready.store(true, std::memory_order_release);
    }

    DescriptorDraw NoteDraw(DescriptorOrigin position, vk::PipelineLayout draw_layout, vk::ImageView output,
                            vk::ImageView ui, vk::ImageView lut, vk::Sampler sample, bool physical) {
        if (draw_seen.exchange(true, std::memory_order_acq_rel)) {
            duplicate.store(true, std::memory_order_release);
            return {};
        }
        const auto commit = Commit();
        const bool ordered = commit.encoded && position && position == commit.origin && output &&
            draw_layout == layout;
        const auto& seen = commit.actual;
        const bool operands = ordered && stage_match && planned.valid && seen.valid && planned == seen &&
            ui && lut && sample && seen.images[0].imageView == ui && seen.images[1].imageView == lut &&
            seen.images[2].sampler == sample;
        const bool ancillary = operands && clip_disabled && !seen.clip.buffer &&
            seen.clip.offset == 0 && seen.clip.range == VK_WHOLE_SIZE;
        draw = {position, output, ordered, operands, ancillary, operands && physical};
        draw_ready.store(true, std::memory_order_release);
        return draw;
    }

    DescriptorCommit Commit() const {
        return bind_ready.load(std::memory_order_acquire) && !duplicate.load(std::memory_order_acquire)
            ? bound : DescriptorCommit{};
    }

    bool Retired(u64 scheduled_tick, u64 submitted_tick, u64 completed_tick) const {
        return draw_ready.load(std::memory_order_acquire) && !duplicate.load(std::memory_order_acquire) &&
            draw.ordered && draw.origin.tick == scheduled_tick &&
            submitted_tick >= scheduled_tick && completed_tick >= scheduled_tick;
    }

    const DescriptorKey key;
    const vk::PipelineLayout layout;
    const void* const scheduler;
    const vk::Semaphore timeline;
    const std::thread::id producer;
    const DescriptorSlots planned;
    const bool stage_match, clip_disabled;

private:
    std::atomic<bool> bind_seen{}, bind_ready{}, draw_seen{}, draw_ready{}, duplicate{};
    DescriptorCommit bound{};
    DescriptorDraw draw{};
};

// Worker context is installed by the existing chunk owner. The direct callback can use
// its same producer's current tick only when the original Record really ran inline.
template <typename Scheduler>
DescriptorOrigin NoteOrigin(Scheduler& scheduler, const DescriptorTicket& ticket, vk::CommandBuffer command,
                            const void* worker, vk::CommandBuffer worker_command, u64 worker_tick, u32 segment) {
    if (ticket.scheduler != &scheduler || !ticket.timeline || !command) return {};
    if (worker) {
        if (worker != &scheduler || worker_command != command) return {};
        return {&scheduler, ticket.timeline, command, worker_tick, segment, true};
    }
    if (ticket.producer != std::this_thread::get_id() || scheduler.IsRecordingDeferred()) return {};
    return {&scheduler, ticket.timeline, command, scheduler.CurrentTick(), 0, false};
}
} // namespace Vulkan::BottleDisplay182
#endif
