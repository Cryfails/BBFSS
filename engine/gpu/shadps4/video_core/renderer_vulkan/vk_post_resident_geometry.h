// SPDX-FileCopyrightText: Copyright 2025 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <limits>
#include <memory>
#include <span>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h>

namespace Vulkan {
class RecordChunk;
class Scheduler;
namespace PostResidentGeometry {

class DriverlessFixture;

constexpr u32 MaxRegions = 5;
constexpr u32 MaxBytes = 1056;
constexpr u32 MaxCandidates = 32;
constexpr u32 CheckpointBytes = 33 * 1024;

struct DrawKey {
    u64 request{}, checkpoint{}, draw{};
    bool operator==(const DrawKey&) const = default;
};

enum class Use : u8 { Vertex, Index };
enum class Ownership : u8 { Unknown, DedicatedGpuExclusive };

struct FinalBinding {
    const Scheduler* scheduler{};
    vk::Queue queue{};
    vk::Buffer buffer{};
    const void* cache{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    vk::DeviceMemory memory{};
    u64 memory_offset{}, allocation_bytes{}, allocation_epoch{};
    u64 guest{}, buffer_offset{}, buffer_bytes{}, version{};
    u16 bytes{};
    u8 slot{};
    Use use{};
    bool operator==(const FinalBinding&) const = default;
};

struct SourceProof {
    FinalBinding binding{};
    Ownership ownership{};
    vk::BufferUsageFlags usage{};
    u64 safe_begin{}, safe_bytes{}; // Exact versioned range, including any aligned copy padding.
    // The cache proved this Vulkan-visible resident version after the upload-ticket miss.
    // Its lease excludes recycle, independent queues and CPU access through retirement.
    // Validation and lease release must be safe and nonblocking on the recorder and retire
    // thread. Validate the exact allocation, range version, and padding. Omit absent proof.
    std::shared_ptr<const void> lease;
    bool (*still_exact)(const void*, const FinalBinding&, u64, u64) noexcept{};
};

enum class State : u8 {
    InvalidProof, Capacity, Unordered, NoAdjacentEnd, NoExactDraw, AllocationFailed,
    UnjoinedSubmit, InvalidateFailed, Planned, Recorded, Issued, Encoded, Submitted, Ready,
};

struct Slice {
    u16 offset{}, bytes{};
    u8 slot{};
    Use use{};
};

struct Result {
    State state{};
    u64 tick{};
    std::span<const Slice> slices{};
    std::span<const std::byte> bytes{};
};

class Checkpoint {
public:
    Checkpoint(u64 request_, u64 checkpoint_) : request{request_}, checkpoint{checkpoint_} {}

private:
    friend class Ticket;
    bool Reserve(const Scheduler* owner, DrawKey key, u32 bytes) {
        if (!request || !checkpoint || !key.draw || key.request != request ||
            key.checkpoint != checkpoint || (scheduler && owner != scheduler) ||
            bytes > CheckpointBytes - used ||
            count == draws.size()) {
            return false;
        }
        scheduler = owner;
        if (std::find(draws.begin(), draws.begin() + count, key.draw) != draws.begin() + count) {
            return false;
        }
        draws[count++] = key.draw;
        used += bytes;
        return true;
    }

    // The caller owns one checkpoint object through its request. Only its scheduler's existing
    // single producer may reserve candidates.
    const u64 request, checkpoint;
    const Scheduler* scheduler{};
    u32 used{}, count{};
    std::array<u64, MaxCandidates> draws{};
};

class Issue;

class Ticket {
public:
    static std::shared_ptr<Ticket> Create(const std::shared_ptr<Checkpoint>& checkpoint,
                                          DrawKey key, std::span<const SourceProof> proof) {
        auto result = std::shared_ptr<Ticket>(new Ticket(key));
        if (!result->Plan(proof)) {
            result->Refuse(State::InvalidProof);
            return result;
        }
        if (!checkpoint ||
            !checkpoint->Reserve(proof.front().binding.scheduler, key, result->transfer_bytes)) {
            result->Refuse(State::Capacity);
            return result;
        }
        result->Set(State::Planned);
        return result;
    }

    Result Read() const noexcept {
        const State status = Get();
        if (status == State::Submitted) {
            return {status, tick};
        }
        if (status != State::Ready) {
            return {status};
        }
        return {status, tick, std::span{slices}.first(count),
                std::span{payload}.first(payload_bytes)};
    }

private:
    friend class DriverlessFixture;
    friend class Issue;
    friend class ::Vulkan::Scheduler;
    friend class ::Vulkan::RecordChunk;

    struct Region {
        SourceProof source;
        u64 begin{};
        u16 bytes{}, destination{}, prefix{};
    };

    explicit Ticket(DrawKey key_) : key{key_} {}

    static bool Contains(u64 base, u64 size, u64 begin, u64 bytes) noexcept {
        return size && bytes && base <= std::numeric_limits<u64>::max() - size &&
               begin >= base && begin - base < size && bytes <= size - (begin - base);
    }

    bool Plan(std::span<const SourceProof> proof) {
        if (proof.empty() || proof.size() > regions.size()) {
            return false;
        }
        u8 slots = 0;
        for (const auto& source : proof) {
            const auto& b = source.binding;
            const bool index = b.use == Use::Index;
            if ((b.use != Use::Vertex && !index) || b.slot >= (index ? 1 : 4) ||
                b.bytes > (index ? 32 : 256) || !b.scheduler || !b.queue || !b.cache ||
                !b.buffer || !b.allocator || !b.allocation || !b.memory || !b.allocation_epoch || !b.version ||
                !b.guest || !Contains(b.guest, b.bytes, b.guest, b.bytes) ||
                !Contains(b.memory_offset, b.allocation_bytes, b.memory_offset, b.buffer_bytes) ||
                !Contains(0, b.buffer_bytes, source.safe_begin, source.safe_bytes) ||
                !source.lease || !source.still_exact ||
                source.ownership != Ownership::DedicatedGpuExclusive ||
                !(source.usage & vk::BufferUsageFlagBits::eTransferSrc)) {
                return false;
            }
            const auto begin = b.buffer_offset & ~u64{3};
            const auto prefix = static_cast<u16>(b.buffer_offset - begin);
            const auto bytes = static_cast<u16>((prefix + b.bytes + 3) & ~3u);
            const u8 bit = 1u << (index ? 4 : b.slot);
            if (!b.bytes || (slots & bit) || !Contains(source.safe_begin, source.safe_bytes, begin, bytes) ||
                bytes > MaxBytes - transfer_bytes) {
                return false;
            }
            for (u32 i = 0; i < count; ++i) {
                const auto& prior = regions[i];
                const auto& p = prior.source.binding;
                const u64 physical = b.memory_offset + begin;
                const u64 prior_physical = p.memory_offset + prior.begin;
                if (p.cache != b.cache || p.scheduler != b.scheduler || p.queue != b.queue ||
                    p.allocator != b.allocator ||
                    (p.buffer == b.buffer && (p.allocation != b.allocation ||
                                              p.allocation_epoch != b.allocation_epoch)) ||
                    (p.memory == b.memory && physical < prior_physical + prior.bytes &&
                     prior_physical < physical + bytes)) {
                    return false;
                }
            }
            slots |= bit;
            regions[count] = {source, begin, bytes, transfer_bytes, prefix};
            slices[count++] = {payload_bytes, b.bytes, b.slot, b.use};
            transfer_bytes += bytes;
            payload_bytes += b.bytes;
        }
        return true;
    }

    State Get() const noexcept { return state.load(std::memory_order_acquire); }
    void Set(State next) noexcept { state.store(next, std::memory_order_release); }

    void Refuse(State reason) noexcept {
        for (auto& region : regions) {
            region.source.lease.reset();
        }
        Set(reason);
    }

    bool Check(const Scheduler* scheduler, vk::Queue queue, VmaAllocator allocator) const noexcept {
        for (u32 i = 0; i < count; ++i) {
            const auto& r = regions[i];
            const auto& b = r.source.binding;
            if (scheduler != b.scheduler || queue != b.queue || allocator != b.allocator ||
                !r.source.lease ||
                !r.source.still_exact(r.source.lease.get(), b, r.begin, r.bytes)) {
                return false;
            }
        }
        return true;
    }

    bool Match(DrawKey actual, std::span<const FinalBinding> bound) const noexcept {
        if (key != actual || bound.size() != count) {
            return false;
        }
        for (u32 i = 0; i < count; ++i) {
            if (std::count(bound.begin(), bound.end(), regions[i].source.binding) != 1) {
                return false;
            }
        }
        return true;
    }

    bool JoinSubmit(vk::Result result, u64 signal, std::span<const vk::CommandBuffer> commands,
                    std::span<const vk::CommandBuffer> segments, bool raw) const noexcept {
        if (Get() != State::Encoded || result != vk::Result::eSuccess || !signal || signal != tick ||
            raw || !transfer || !command || segment >= segments.size() || segments[segment] != command ||
            std::count(commands.begin(), commands.end(), command) != 1) {
            return false;
        }
        for (const auto segment_cmd : segments) {
            if (segment_cmd) {
                if (commands.empty() || commands.front() != segment_cmd) {
                    return false;
                }
                commands = commands.subspan(1);
            }
        }
        return commands.empty();
    }

    bool Complete(u64 retired_tick, std::span<const std::byte> mapped) noexcept {
        if (Get() != State::Submitted || retired_tick < tick || mapped.size() != transfer_bytes) {
            return false;
        }
        for (u32 i = 0; i < count; ++i) {
            auto& r = regions[i];
            const auto& slice = slices[i];
            std::copy_n(mapped.begin() + r.destination + r.prefix, slice.bytes,
                        payload.begin() + slice.offset);
            r.source.lease.reset();
        }
        Set(State::Ready);
        return true;
    }

    const DrawKey key;
    std::array<Region, MaxRegions> regions{};
    std::array<Slice, MaxRegions> slices{};
    std::array<std::byte, MaxBytes> payload{};
    std::shared_ptr<void> transfer;
    std::atomic<State> state{State::InvalidProof};
    vk::CommandBuffer command{};
    vk::Queue queue{};
    VmaAllocator allocator{};
    const Scheduler* scheduler{};
    u64 tick{}, incarnation{};
    u32 segment{};
    u16 transfer_bytes{}, payload_bytes{};
    u8 count{};
};

// Instantiate only in the actual scheduler closure. Acknowledge once, immediately after the
// original native draw. Check the actual reads and all draw/end writes, including storage, render
// attachments, resolves, and queries. A source range that any of these can alias is unproved.
class Issue {
public:
    Issue(const Issue&) = delete;
    Issue& operator=(const Issue&) = delete;

    void Confirm(DrawKey key, std::span<const FinalBinding> bound,
                 bool draw_and_end_writes_proven_disjoint) noexcept {
        if (!ticket) {
            return;
        }
        if (ticket->Get() != State::Recorded || !draw_and_end_writes_proven_disjoint ||
            !ticket->Match(key, bound) || !ticket->Check(ticket->scheduler, ticket->queue, ticket->allocator)) {
            ticket->Set(State::NoExactDraw);
            return;
        }
        ticket->command = command;
        ticket->Set(State::Issued);
    }

private:
    friend class DriverlessFixture;
    friend class ::Vulkan::Scheduler;
    Issue(Ticket* ticket_, vk::CommandBuffer command_) : ticket{ticket_}, command{command_} {}
    Ticket* ticket;
    vk::CommandBuffer command;
};

} // namespace PostResidentGeometry
} // namespace Vulkan

#endif
