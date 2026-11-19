// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <limits>
#include <memory>
#include <span>
#include <utility>

#include "common/types.h"

namespace VideoCore::PostGeometry {

constexpr u32 MaxDraws = 32, MaxRecords = 160;
constexpr u32 VertexSlots = 6, IndexSlots = 1, UniformSlots = 8;
constexpr u32 MaxSlices = VertexSlots + IndexSlots + UniformSlots;
constexpr u32 VertexBytes = 256, IndexBytes = 32, UniformBytes = 256, PayloadBytes = 15 * 1024;

enum class Use : u8 { Vertex, Index, Uniform };

constexpr bool RingRegionCurrent(u64 end, u64 absolute, u32 bytes, u64 capacity) {
    if (!capacity || !bytes || absolute >= end || end - absolute > capacity) return false;
    return bytes <= end - absolute && bytes <= capacity - absolute % capacity;
}

constexpr u32 PacketSlot(Use use, u32 slot) {
    switch (use) {
    case Use::Vertex: return slot < VertexSlots ? slot : MaxSlices;
    case Use::Index: return slot < IndexSlots ? VertexSlots + slot : MaxSlices;
    case Use::Uniform: return slot < UniformSlots ? VertexSlots + IndexSlots + slot : MaxSlices;
    }
    return MaxSlices;
}
enum class Route : u8 { None, MapCommit, ReserveInline, ReserveRecorder, ReservePool, ConstantRing, StagedUniform };
enum class State : u8 { NoCopy, Pending, Copying, Complete, Unjoined, Mismatch, Reused, Capacity, Conflict, Resident, Unsupported };

struct Key {
    u64 request{}, scene{}, draw{}, timeline{};
    u32 frame{};
    bool operator==(const Key&) const = default;
    bool Valid() const { return request && scene && draw && timeline; }
};

struct Slice {
    u32 relative{};
    u16 bytes{};
    u8 slot{};
    Use use{};
};

struct Backing {
    const void* buffer{};
    u64 handle{}, allocation{}, cache_generation{};
    bool operator==(const Backing&) const = default;
    bool Valid() const { return buffer && handle && allocation; }
};

struct Reservation {
    Backing backing{};
    u64 guest{}, offset{}, tick{};
    u32 bytes{};
};

struct Ticket {
    u64 serial{};
    u16 row{};
    explicit operator bool() const { return serial != 0; }
};

struct FinalBinding {
    // Supply from the actual bind, with offset/guest advanced by the validated relative byte range.
    Key key{};
    const void* cache{};
    Backing backing{};
    u64 guest{}, offset{}, tick{};
    u16 bytes{};
    u8 slot{};
    Use use{};
};

struct Result {
    State state{};
    Route route{};
    std::span<const u8> bytes{};
};

class DrawWatch;
class UploadWatch;

class Capture {
public:
    struct Copy {
        Capture* owner{};
        Reservation reservation{};
        u64 serial{};
        u16 payload{};
        u16 row{};
        Slice slice{};
        u8 draw{}, batch_count{};
        Route route{};
        std::atomic<State> state{State::NoCopy};
        std::atomic<State> binding{State::Unjoined};
    };

    static std::shared_ptr<Capture> Create(const void* cache) {
        if (!cache) return {};
        return {new Capture(cache), [](Capture* capture) { capture->Release(); }};
    }

    const void* Cache() const { return cache; }

    // The copy pool stores a C-style item. Its original completion must release this reference.
    void Retain() { references.fetch_add(1, std::memory_order_relaxed); }
    void Release() {
        if (references.fetch_sub(1, std::memory_order_acq_rel) == 1) delete this;
    }

    static void SetRoute(Copy& first, Route route) {
        for (u16 i = 0; i < first.batch_count; ++i)
            first.owner->records[first.row + i].route = route;
    }

    static void Complete(Copy& first, Route route, const Reservation& actual, const u8* mapped) {
        auto& self = *first.owner;
        const auto& expected = first.reservation;
        const bool matching = first.route == route && route != Route::None && mapped &&
                              expected.backing == actual.backing && expected.guest == actual.guest &&
                              expected.offset == actual.offset && expected.tick == actual.tick &&
                              expected.bytes == actual.bytes;
        for (u16 i = 0; i < first.batch_count; ++i) {
            auto& row = self.records[first.row + i];
            State pending = State::Pending;
            if (!row.state.compare_exchange_strong(pending, State::Copying, std::memory_order_acq_rel)) continue;
            if (matching) std::memcpy(self.payload.data() + row.payload, mapped + row.slice.relative,
                                      row.slice.bytes);
            State copying = State::Copying;
            row.state.compare_exchange_strong(copying, matching ? State::Complete : State::Mismatch,
                                               std::memory_order_acq_rel);
        }
    }

    // Call after the existing draw/submission fence. Absence or a pending callback gives no bytes.
    Result Read(Ticket ticket, const FinalBinding& actual) const {
        const auto* row = Find(ticket);
        if (!row || !Matches(*row, actual)) return {State::Mismatch};
        const auto binding = row->binding.load(std::memory_order_acquire);
        if (binding != State::Complete) return {binding, row->route};
        const auto state = row->state.load(std::memory_order_acquire);
        if (state != State::Complete) return {state == State::Copying ? State::Pending : state, row->route};
        return {state, row->route, std::span{payload}.subspan(row->payload, row->slice.bytes)};
    }

    static bool Contains(u64 base, u64 bytes, u64 begin, u64 length) {
        return bytes && length && base <= std::numeric_limits<u64>::max() - bytes &&
               begin >= base && begin - base <= bytes && length <= bytes - (begin - base);
    }

private:
    friend class DrawWatch;
    friend class UploadWatch;
    explicit Capture(const void* owner) : cache{owner} {}

    const Copy* Find(Ticket ticket) const {
        if (!ticket || ticket.row >= records.size()) return nullptr;
        const auto& row = records[ticket.row];
        return row.serial == ticket.serial ? &row : nullptr;
    }

    bool Matches(const Copy& row, const FinalBinding& actual) const {
        const auto& r = row.reservation;
        return actual.key == draws[row.draw] && actual.cache == cache && actual.backing == r.backing &&
               actual.tick == r.tick && actual.guest == r.guest + row.slice.relative &&
               actual.offset == r.offset + row.slice.relative && actual.bytes == row.slice.bytes &&
               actual.slot == row.slice.slot && actual.use == row.slice.use;
    }

    void Invalidate(u8 draw, const Reservation& newer) {
        for (u16 i = 0; i < used_records; ++i) {
            auto& row = records[i];
            const auto& old = row.reservation;
            if (row.draw != draw || old.backing.allocation != newer.backing.allocation) continue;
            if (newer.offset < old.offset + old.bytes && old.offset < newer.offset + newer.bytes)
                row.state.store(State::Reused, std::memory_order_release);
        }
    }

    inline static std::atomic<u64> next_serial{};
    std::atomic<unsigned> references{1};
    const void* const cache;
    std::array<Key, MaxDraws> draws{};
    std::array<Copy, MaxRecords> records{};
    std::array<u8, PayloadBytes> payload{};
    u16 used_records{}, used_bytes{};
    u8 used_draws{};
};

static_assert(sizeof(Capture) <= 33 * 1024);

class DrawWatch {
public:
    DrawWatch(const void* cache, const std::shared_ptr<Capture>& capture, Key key) {
        if (!capture || cache != capture->Cache() || active || !key.Valid()) return;
        if (capture->used_draws) {
            const auto& root = capture->draws[0];
            if (root.request != key.request || root.frame != key.frame || root.timeline != key.timeline) {
                state = State::Mismatch;
                return;
            }
        }
        if (capture->used_draws == MaxDraws) {
            state = State::Capacity;
            return;
        }
        for (u8 i = 0; i < capture->used_draws; ++i) {
            if (capture->draws[i] == key) {
                state = State::Conflict;
                return;
            }
        }
        owner = capture;
        draw = owner->used_draws++;
        owner->draws[draw] = key;
        active = this;
        state = State::Unjoined;
    }
    DrawWatch(const DrawWatch&) = delete;
    ~DrawWatch() { if (active == this) active = nullptr; }

    static DrawWatch* Current(const void* cache) {
        return active && active->owner->Cache() == cache ? active : nullptr;
    }
    State Status() const { return state; }
    const std::shared_ptr<Capture>& Owner() const { return owner; }

    State Join(Ticket ticket, const FinalBinding& actual) {
        if (!owner || active != this) return State::Unjoined;
        const auto* read = owner->Find(ticket);
        if (!read || read->draw != draw) return State::Mismatch;
        auto& row = owner->records[ticket.row];
        const auto joined = owner->Matches(row, actual) ? State::Complete : State::Mismatch;
        State prior = State::Unjoined;
        if (!row.binding.compare_exchange_strong(prior, joined, std::memory_order_acq_rel))
            return State::Conflict;
        return joined;
    }

    UploadWatch* Claim(u64 guest, u32 bytes, bool writable, bool texel);
    Capture::Copy* Reserve(UploadWatch* upload, const Reservation& reservation, u64 timeline, bool conflict);

private:
    friend class UploadWatch;
    inline static thread_local DrawWatch* active{};
    std::shared_ptr<Capture> owner;
    UploadWatch* expected{};
    u16 used_slots{};
    u8 draw{};
    State state{State::Unjoined};
};

class UploadWatch {
public:
    UploadWatch(DrawWatch& draw, u64 guest, u32 bytes, std::span<const Slice> requested)
        : draw{draw}, guest{guest}, bytes{bytes}, slices{requested} {
        if (DrawWatch::active != &draw || draw.expected) return;
        if (!guest || !bytes || requested.empty() || requested.size() > MaxSlices) {
            state = State::Capacity;
            return;
        }
        u16 slots = 0;
        for (const auto& slice : requested) {
            const u32 packet_slot = PacketSlot(slice.use, slice.slot);
            const u32 max_bytes = slice.use == Use::Index ? IndexBytes :
                                  slice.use == Use::Uniform ? UniformBytes : VertexBytes;
            if (packet_slot == MaxSlices || slice.bytes > max_bytes ||
                !Capture::Contains(0, bytes, slice.relative, slice.bytes)) {
                state = State::Capacity;
                return;
            }
            const u16 bit = u16(1u << packet_slot);
            if (slots & bit) {
                state = State::Conflict;
                return;
            }
            slots |= bit;
        }
        slot_mask = slots;
        draw.expected = this;
    }
    UploadWatch(const UploadWatch&) = delete;
    ~UploadWatch() { if (draw.expected == this) draw.expected = nullptr; }

    void Resident() { state = State::Resident; }

    void SnapshotUniform(Route route, const Reservation& reservation, u64 timeline, const u8* mapped) {
        if ((route != Route::ConstantRing && route != Route::StagedUniform) || !mapped ||
            !std::ranges::all_of(slices, [](const Slice& slice) { return slice.use == Use::Uniform; })) {
            state = State::Unsupported;
            return;
        }
        auto* copy = draw.Reserve(draw.Claim(reservation.guest, reservation.bytes, false, false),
                                  reservation, timeline, false);
        if (copy) {
            Capture::SetRoute(*copy, route);
            Capture::Complete(*copy, route, reservation, mapped);
        }
    }

    State Status() const { return state; }
    std::span<const Ticket> Tickets() const {
        if (state != State::Pending) return {};
        return std::span{tickets}.first(slices.size());
    }

private:
    friend class DrawWatch;
    DrawWatch& draw;
    u64 guest;
    u32 bytes;
    std::span<const Slice> slices;
    std::array<Ticket, MaxSlices> tickets{};
    bool claimed{};
    u16 slot_mask{};
    State state{State::NoCopy};
};

inline UploadWatch* DrawWatch::Claim(u64 guest, u32 bytes, bool writable, bool texel) {
    auto* upload = expected;
    if (!upload || guest != upload->guest || bytes != upload->bytes) return nullptr;
    if (writable || texel) {
        upload->state = State::Unsupported;
        return nullptr;
    }
    if (std::exchange(upload->claimed, true)) {
        for (const auto& ticket : upload->Tickets())
            owner->records[ticket.row].state.store(State::Conflict, std::memory_order_release);
        upload->state = State::Conflict;
        return nullptr;
    }
    return upload;
}

inline Capture::Copy* DrawWatch::Reserve(UploadWatch* upload, const Reservation& r, u64 timeline, bool conflict) {
    if (!r.backing.Valid() || !r.tick || !Capture::Contains(r.offset, r.bytes, r.offset, r.bytes)) return nullptr;
    owner->Invalidate(draw, r);
    if (!upload || upload != expected || upload->guest != r.guest || upload->bytes != r.bytes) return nullptr;
    if (timeline != owner->draws[draw].timeline) {
        upload->state = State::Mismatch;
        return nullptr;
    }
    if (conflict || (used_slots & upload->slot_mask)) {
        upload->state = State::Conflict;
        return nullptr;
    }
    if (!Capture::Contains(r.guest, r.bytes, r.guest, r.bytes)) return nullptr;
    u32 required = 0;
    for (const auto& slice : upload->slices) required += slice.bytes;
    if (upload->slices.size() > MaxRecords - owner->used_records || required > PayloadBytes - owner->used_bytes) {
        upload->state = State::Capacity;
        return nullptr;
    }
    used_slots |= upload->slot_mask;
    const u16 first = owner->used_records;
    const u64 serial = Capture::next_serial.fetch_add(1, std::memory_order_relaxed) + 1;
    for (const auto& slice : upload->slices) {
        const u16 index = owner->used_records++;
        auto& row = owner->records[index];
        row.owner = owner.get();
        row.reservation = r;
        row.serial = serial;
        row.payload = owner->used_bytes;
        row.row = index;
        row.slice = slice;
        row.draw = draw;
        row.state.store(State::Pending, std::memory_order_release);
        upload->tickets[index - first] = {serial, index};
        owner->used_bytes += slice.bytes;
    }
    auto& batch = owner->records[first];
    batch.batch_count = static_cast<u8>(upload->slices.size());
    upload->state = State::Pending;
    return &batch;
}

} // namespace VideoCore::PostGeometry
