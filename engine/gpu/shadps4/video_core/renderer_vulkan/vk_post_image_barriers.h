// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <span>
#include <thread>

#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::PostImageBarriers {

inline constexpr size_t MaxRows = 32;
inline constexpr uint64_t CookiePrefix = 0xd309000000000000ULL;

struct Key {
    uint64_t request{}, checkpoint{}, frame{};
    bool operator==(const Key&) const = default;
};

struct Backing {
    vk::Image image{};
    vk::DeviceMemory memory{};
    uint64_t uid{}, allocation{}, offset{}, bytes{}, requested_write_serial{};
    uint64_t guest_begin{}, guest_end{}, stencil_begin{}, stencil_end{};
    std::array<uint64_t, 3> metadata{};
    vk::Format format{};
    vk::SampleCountFlagBits samples{};
    vk::ImageAspectFlags aspects{};
    uint32_t mips{}, layers{};
    bool bounded{}, alias{}, foreign{}, replacement{};

    bool Known() const {
        return bounded && image && memory && uid && allocation && bytes &&
            offset <= UINT64_MAX - bytes && mips && layers && aspects;
    }
};

enum class Status : uint8_t {
    NativeImage, Discard, Global, Unregistered, AllocationUnknown, Alias, Foreign, Stale, Unsupported
};
enum class Route : uint8_t { DirectRaw, RecordInline, RecordWorker };

struct Raw {
    vk::Image image{};
    vk::ImageSubresourceRange range{};
    vk::ImageLayout old_layout{}, new_layout{};
    vk::PipelineStageFlags2 src_stage{}, dst_stage{};
    vk::AccessFlags2 src_access{}, dst_access{};
    uint32_t src_family{}, dst_family{};
    bool chained{}, global{};

    static Raw Image(const vk::ImageMemoryBarrier2& barrier) {
        return {barrier.image, barrier.subresourceRange, barrier.oldLayout, barrier.newLayout,
            barrier.srcStageMask, barrier.dstStageMask, barrier.srcAccessMask, barrier.dstAccessMask,
            barrier.srcQueueFamilyIndex, barrier.dstQueueFamilyIndex, barrier.pNext != nullptr, false};
    }
    static Raw Memory(const vk::MemoryBarrier2& barrier) {
        return {.src_stage = barrier.srcStageMask, .dst_stage = barrier.dstStageMask,
            .src_access = barrier.srcAccessMask, .dst_access = barrier.dstAccessMask,
            .chained = barrier.pNext != nullptr, .global = true};
    }
    bool operator==(const Raw&) const = default;
};

struct Row : Raw {
    uint64_t cookie{}, command{}, scheduler{}, queue{}, queued_tick{};
    Backing backing{};
    vk::DependencyFlags dependency_flags{};
    uint32_t queue_family{};
    Status status{Status::Unregistered};
    Route route{};
    bool encoded{}, encoder_note{};
};

struct Report {
    Key key{};
    uint64_t window{};
    size_t count{}, pending{};
    bool overflow{}, mismatch{};
    std::array<Row, MaxRows> rows{};
};

struct QueueScope {
    uint64_t scheduler{}, queue{}, tick{};
    uint32_t family{};
    bool alias{}, foreign{};
};

inline bool RangeKnown(const Raw& raw, const Backing& backing) {
    const auto& r = raw.range;
    return r.aspectMask && !(r.aspectMask & ~backing.aspects) &&
        r.baseMipLevel < backing.mips && r.baseArrayLayer < backing.layers &&
        r.levelCount && r.layerCount &&
        (r.levelCount == VK_REMAINING_MIP_LEVELS || r.levelCount <= backing.mips - r.baseMipLevel) &&
        (r.layerCount == VK_REMAINING_ARRAY_LAYERS || r.layerCount <= backing.layers - r.baseArrayLayer);
}

inline Status Classify(const Raw& raw, const Backing& backing, const QueueScope& queue, bool stale) {
    if (raw.global) return Status::Global;
    if (queue.foreign || backing.foreign || !queue.scheduler || !queue.queue || !queue.tick ||
        !((raw.src_family == VK_QUEUE_FAMILY_IGNORED && raw.dst_family == VK_QUEUE_FAMILY_IGNORED) ||
          (raw.src_family == queue.family && raw.dst_family == queue.family))) return Status::Foreign;
    if (stale) return Status::Stale;
    if (!backing.image || backing.image != raw.image) return Status::Unregistered;
    if (queue.alias || backing.alias) return Status::Alias;
    if (!backing.Known()) return Status::AllocationUnknown;
    if (raw.chained || !RangeKnown(raw, backing) || raw.new_layout == vk::ImageLayout::eUndefined)
        return Status::Unsupported;
    return backing.replacement || raw.old_layout == vk::ImageLayout::eUndefined
        ? Status::Discard : Status::NativeImage;
}

// The producer owns the pending sidecar. Workers receive only a retained Session and a ticket
// after the Vulkan operands have been copied by the ordinary Scheduler::RecordData path.
class Session {
public:
    struct Ticket {
        uint64_t cookie{};
        size_t first{}, count{};
        uint32_t image_count{}, memory_count{};
        explicit operator bool() const { return count != 0; }
    };

    Session(Key key, uint64_t window) : packet{.key = key, .window = window},
        producer{std::this_thread::get_id()} {}

    uint64_t Window() const { return packet.window; }

    void Mark(size_t index, vk::Image image, const Backing& backing) {
        std::scoped_lock lock{mutex};
        if (marks_used == marks.size()) return;
        auto& mark = marks[marks_used++];
        mark = {index, image, backing, false};
        mark.backing.foreign |= std::this_thread::get_id() != producer;
    }

    void Rebind(uint64_t uid, vk::Image old_image, vk::Image new_image) {
        if (!uid || old_image == new_image) return;
        std::scoped_lock lock{mutex};
        for (auto& mark : std::span(marks).first(marks_used)) {
            if (mark.backing.uid == uid && mark.image != new_image) mark.stale = true;
        }
    }

    Ticket Prepare(const vk::DependencyInfo& dependency, QueueScope at) {
        if (!dependency.memoryBarrierCount && !dependency.imageMemoryBarrierCount) return {};
        std::scoped_lock lock{mutex};
        at.foreign |= std::this_thread::get_id() != producer;
        Ticket ticket{.first = packet.count, .image_count = dependency.imageMemoryBarrierCount,
            .memory_count = dependency.memoryBarrierCount};
        if ((ticket.memory_count && !dependency.pMemoryBarriers) ||
            (ticket.image_count && !dependency.pImageMemoryBarriers)) {
            packet.mismatch = true;
            marks_used = 0;
            return {};
        }
        const auto raw_count = size_t(ticket.image_count) + ticket.memory_count;
        packet.overflow |= raw_count > packet.rows.size() - packet.count;
        if (packet.count == packet.rows.size()) {
            marks_used = 0;
            return {};
        }
        constexpr auto sequence_limit = 0x0000ffffffffffffULL;
        const auto sequence = next_cookie.fetch_add(1, std::memory_order_relaxed);
        if (!sequence || sequence > sequence_limit) {
            packet.overflow = true;
            marks_used = 0;
            return {};
        }
        ticket.cookie = CookiePrefix | sequence;
        const auto append = [&](const Raw& raw, const Backing& backing, bool stale) {
            auto& row = packet.rows[packet.count++];
            static_cast<Raw&>(row) = raw;
            row.cookie = ticket.cookie;
            row.scheduler = at.scheduler;
            row.queue = at.queue;
            row.queued_tick = at.tick;
            row.backing = backing;
            row.queue_family = at.family;
            row.dependency_flags = dependency.dependencyFlags;
            row.status = dependency.pNext ? Status::Unsupported : Classify(raw, backing, at, stale);
        };
        for (uint32_t i = 0; i < ticket.memory_count && packet.count < packet.rows.size(); ++i) {
            append(Raw::Memory(dependency.pMemoryBarriers[i]), {}, false);
        }
        size_t next_mark{};
        for (uint32_t i = 0; i < ticket.image_count && packet.count < packet.rows.size(); ++i) {
            while (next_mark < marks_used && marks[next_mark].index < i) ++next_mark;
            const Raw raw = Raw::Image(dependency.pImageMemoryBarriers[i]);
            const auto* mark = next_mark < marks_used && marks[next_mark].index == i &&
                marks[next_mark].image == raw.image ? &marks[next_mark] : nullptr;
            append(raw, mark ? mark->backing : Backing{}, mark && mark->stale);
        }
        marks_used = 0;
        ticket.count = packet.count - ticket.first;
        return ticket;
    }

    bool Commit(Ticket ticket, vk::CommandBuffer command, const vk::DependencyInfo& dependency,
                bool raw_command, bool encoder_note) {
        if (!ticket) return false;
        std::scoped_lock lock{mutex};
        if (!command || ticket.first > packet.count || ticket.count > packet.count - ticket.first ||
            ticket.image_count != dependency.imageMemoryBarrierCount ||
            ticket.memory_count != dependency.memoryBarrierCount ||
            (ticket.memory_count && !dependency.pMemoryBarriers) ||
            (ticket.image_count && !dependency.pImageMemoryBarriers)) {
            packet.mismatch = true;
            return false;
        }
        auto rows = std::span(packet.rows).subspan(ticket.first, ticket.count);
        for (size_t i = 0; i < rows.size(); ++i) {
            const Raw actual = i < ticket.memory_count ? Raw::Memory(dependency.pMemoryBarriers[i])
                : Raw::Image(dependency.pImageMemoryBarriers[i - ticket.memory_count]);
            if (rows[i].encoded || rows[i].cookie != ticket.cookie ||
                rows[i].dependency_flags != dependency.dependencyFlags ||
                actual != static_cast<const Raw&>(rows[i])) {
                packet.mismatch = true;
                return false;
            }
        }
        const auto route = raw_command ? Route::DirectRaw :
            (producer == std::this_thread::get_id() ? Route::RecordInline : Route::RecordWorker);
        for (auto& row : rows) {
            row.command = std::bit_cast<uint64_t>(command);
            row.route = route;
            row.encoded = true;
            row.encoder_note = encoder_note && !raw_command;
        }
        return true;
    }

    bool Read(uint64_t window, Report& out) const {
        std::scoped_lock lock{mutex};
        if (window != packet.window) return false;
        out = {.key = packet.key, .window = packet.window, .overflow = packet.overflow,
            .mismatch = packet.mismatch};
        for (const auto& row : std::span(packet.rows).first(packet.count)) {
            if (row.encoded) out.rows[out.count++] = row;
            else ++out.pending;
        }
        return true;
    }

private:
    struct MarkedImage {
        size_t index{};
        vk::Image image{};
        Backing backing{};
        bool stale{};
    };
    inline static std::atomic<uint64_t> next_cookie{1};
    Report packet;
    const std::thread::id producer;
    std::array<MarkedImage, MaxRows> marks{};
    size_t marks_used{};
    mutable std::mutex mutex;
};

// Commit runs only after the real encoder function returns.
template <class Encode, class After>
void EncodeThenObserve(const vk::DependencyInfo& dependency, Encode&& encode, After&& after) {
    encode(dependency);
    after(dependency);
}

} // namespace Vulkan::PostImageBarriers
