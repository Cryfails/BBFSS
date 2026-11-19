// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

#include "common/types.h"

namespace Vulkan::ReflectionOrdinal3 {

constexpr u32 Bytes = 64;
constexpr u64 VertexStage = 0x000009db8f183ea1ull;
constexpr u64 FragmentStage = 0x00000ca7073f7ac4ull;
constexpr u32 RingTag = 0x80000000u;
constexpr u32 PreparedTag = 0x40000000u;
constexpr u32 RingReasonMask = 0x1fu;
constexpr u32 Mirror = 0;
using Payload = std::array<u8, Bytes>;

enum class Ring : u32 { Absent, Disabled, Special, Empty, Clamped, Writable, Large,
                         GpuModified, PendingWrite, Allocation, Reused, Copied };
enum class Resolver : u8 { None, Object, VertexMemo, Direct };
enum class Route : u8 { None, MapCommit, ReserveInline, ReserveRecorder, ReservePool };
enum Phase : u32 { Published = 1, Bound = 2, Classified = 4 };

inline bool On() {
    static const bool enabled = [] {
        for (const char* name : {"BB_REFLECTION_ORDINAL3_WITNESS", "BB_REFLECTION_FIRST_HIT",
                 "BB_REFLECTION_PLACED_FIRST_HIT", "BB_REFLECTION_PLACED_LIFECYCLE",
                 "BB_REFLECTION_EXACT_EQUIVALENCE", "BB_REFLECTION_FIRST_RETIRE",
                 "BB_REFLECTION_FRAGMENT_DISCARD"}) {
            const char* value = std::getenv(name);
            if (!value || std::string_view{value} != "1") return false;
        }
        return true;
    }();
    return enabled;
}

inline bool ExactKey(u64 vs, u64 ps, u32 count, u32 first) {
    return vs == 0x9da6aacb && ps == 0xca7226ec && count == 24 && first == 2440816;
}

inline const char* Name(Route route) {
    constexpr std::array names{"unobserved", "map-commit", "reserve-inline", "reserve-recorder", "reserve-pool"};
    return names[u32(route)];
}

inline const char* Name(Ring reason) {
    constexpr std::array names{"absent", "disabled", "special", "empty", "clamped", "writable",
        "too-large", "gpu-modified", "pending-gpu-write", "ring-allocation-refused", "ring-reused", "ring-copied"};
    return names[u32(reason)];
}

inline const char* Name(Resolver resolver) {
    constexpr std::array names{"unobserved", "bind-by-object", "bind-vertex-memo", "obtain-buffer"};
    return names[u32(resolver)];
}

inline auto Print(u64 n) { return static_cast<unsigned long long>(n); }

// A selected reservation is never reused. The existing async copy can outlive both
// DrawRecord and this observer's terminal record. Its immutable context owns no draw pointer.
struct Writer {
    std::atomic<bool> claimed{};
    std::atomic<u32> phases{};
    std::atomic<u32> callback_conflict{};
    void* cache{};
    const void* buffer{};
    u64 source{}, offset{}, handle{}, tick{}, cache_generation{}, reservation{};
    u64 sequence{}, generation{}, packet{};
    Route route{};
    bool reserve_failed{};
    Payload copied{};

    bool Cutoff(Phase phase) {
        return (phases.fetch_or(phase, std::memory_order_acq_rel) & Published) != 0;
    }
    bool Available() const {
        return (phases.load(std::memory_order_acquire) & Published) != 0;
    }
    void Complete(const u8* bytes) {
        std::memcpy(copied.data(), bytes, copied.size());
        const u32 old = phases.fetch_or(Published, std::memory_order_acq_rel);
        if (old & Classified) {
            std::printf("Reflection ordinal3 event=callback-late role=mirror reservation=%llu sequence=%llu "
                        "generation=%llu packet=%llu offset=%llu producer=%s\n",
                        Print(reservation), Print(sequence), Print(generation), Print(packet),
                        Print(offset), Name(route));
        }
    }
};

inline constinit Writer writer{};
inline constinit std::atomic<u64> reservation_serial{};
inline constinit thread_local Writer* watch = nullptr;

class Watch {
public:
    explicit Watch(Writer* selected) : owns(selected && !watch) {
        if (owns) watch = selected;
    }
    ~Watch() {
        if (owns) watch = nullptr;
    }
    Watch(const Watch&) = delete;

private:
    bool owns;
};

struct Packet {
    const void* renderer{};
    u64 number{};
    u32 encoded{};
    bool operator==(const Packet&) const = default;
};

inline constinit thread_local Packet packet{};

struct Descriptor {
    std::array<u32, 4> sharp{};
    u64 guest{}, bytes{}, handle{}, offset{}, range{};
    u32 slot{}, adjust{}, write_index{}, push_index{}, flags{};
    bool operator==(const Descriptor&) const = default;
};

struct Pose {
    u64 depth_uid{}, cb0_uid{}, depth_image{}, cb0_image{};
    std::array<float, 12> view{};
    std::array<float, 4> projection{};
    std::array<float, 2> jitter{};
    std::array<u32, 2> extent{};
    bool native{}, preview{}, loading{};
    bool operator==(const Pose&) const = default;
};

struct Sample {
    Descriptor object0{}, object3{}, palette{};
    Pose pose{};
    Payload bytes{};
    u64 frame{}, pass{}, tick{}, sequence{}, generation{}, placement{}, cookie{}, allocation{};
    u64 object0_digest{}, geometry{}, final_key{}, ordinary_object0_prefix{}, ordinary_object3_prefix{};
    u64 fetch_prefix{};
    u32 native_origin0{}, native_origin3{};
    bool object0_complete{}, object3_complete{}, palette_current{}, canonical{}, active_words{};
};

struct Resident {
    const void* scheduler{};
    const void* owner{};
    u64 surface{}, placement{}, allocation{}, revision{}, generation{}, epoch{};
    u64 frame{}, pass{};
    bool live{};
};

struct Event {
    std::string_view name{};
    u64 frame{}, pass{}, cookie{}, a{}, b{}, revision{};
};

struct Candidate {
    Sample draw{};
    Packet packet{};
    u64 resolver_key{}, ready_handle{}, issued_handle{}, source_key{}, raster_key{}, vs_stage{}, ps_stage{};
    u64 pass_build_cookie{}, bank_cookie{}, bank_frame{}, bank_pass{}, last_clone_frame{}, last_clone_pass{};
    u64 loss_sequence{}, capture_tick{};
    u32 count{}, first{}, instances{}, first_instance{}, guest_protections{};
    s32 vertex{};
    Payload guest{};
    Event upstream{}, bank{}, drop{}, ordinary{}, flush{};
    const char* issue = "unreached";
    Resolver resolver{};
    bool active{}, direct{}, competing{}, expected_descriptor{}, bound_match{}, bind_complete{};
    bool classify_seen{}, classify_complete{}, sharp_same{}, guest_available{}, original{}, issued{};
    bool alpha{}, joined{}, finished{}, flushed{};
};

struct State {
    const void* renderer{};
    Resident resident{};
    Sample predecessor{};
    Sample working{};
    Candidate chosen{};
    Event upstream{};
    u64 upstream_sequence{};
    bool terminal{};
};

static_assert(sizeof(State) + sizeof(Writer) <= 4096);
inline constinit thread_local State state{};

inline bool ExactStages(u64 vertex, u64 fragment) {
    return vertex == VertexStage && fragment == FragmentStage;
}

inline bool Active(const void* renderer, u64 generation, u64 sequence) {
    return On() && sequence && !state.terminal && state.resident.live &&
        state.renderer == renderer && state.resident.generation == generation;
}

inline void Clone(const void* renderer, const void* scheduler, const void* owner, u64 epoch,
                  u64 generation, u64 frame, u64 pass, u64 surface, u64 placement,
                  u64 allocation, u64 revision) {
    if (!On() || state.terminal || state.renderer || !renderer || !scheduler || !owner) return;
    state.renderer = renderer;
    state.resident = {scheduler, owner, surface, placement, allocation, revision, generation, epoch,
                      frame, pass, true};
    std::printf("Reflection ordinal3 event=armed role=mirror renderer=%llx generation=%llu epoch=%llu "
                "frame=%llu pass=%llu surface=%llu placement=%llu allocation=%llu revision=%llu\n",
                Print(reinterpret_cast<u64>(renderer)), Print(generation), Print(epoch), Print(frame),
                Print(pass), Print(surface), Print(placement), Print(allocation), Print(revision));
}

inline Writer* Select(const void* renderer, u64 generation, u64 sequence, void* cache,
                      u64 guest, Resolver resolver, u64 key) {
    if (!Active(renderer, generation, sequence)) return nullptr;
    auto& c = state.chosen;
    if (c.active) {
        if (c.draw.sequence == sequence) c.competing = true;
        return nullptr;
    }
    if (writer.claimed.exchange(true, std::memory_order_relaxed)) return nullptr;
    c.active = true;
    c.draw.sequence = sequence;
    c.draw.generation = generation;
    c.packet = packet.renderer == renderer ? packet : Packet{};
    c.resolver = resolver;
    c.resolver_key = key;
    writer.cache = cache;
    writer.source = guest;
    writer.sequence = sequence;
    writer.generation = generation;
    writer.packet = c.packet.number;
    return &writer;
}

inline bool ReservationMatches(const Descriptor& descriptor, const void* cache) {
    return writer.reservation && writer.cache == cache && descriptor.guest == writer.source &&
        descriptor.handle == writer.handle && descriptor.offset == writer.offset &&
        descriptor.range == Bytes && !descriptor.adjust;
}

inline void WordRow(const char* kind, const Payload& bytes, u64 sequence, u64 generation) {
    constexpr char hex[] = "0123456789abcdef";
    char text[Bytes * 2 + 1]{};
    for (u32 i = 0; i < bytes.size(); ++i) {
        text[2 * i] = hex[bytes[i] >> 4];
        text[2 * i + 1] = hex[bytes[i] & 15];
    }
    std::printf("Reflection ordinal3 event=bytes role=mirror sample=%s sequence=%llu generation=%llu "
                "bytes=%s encoding=little-endian-bytes\n", kind, Print(sequence), Print(generation), text);
}

inline void DescriptorRow(const char* sample, u32 ordinal, const Descriptor& d, u64 sequence) {
    std::printf("Reflection ordinal3 event=descriptor role=mirror sample=%s ordinal=%u sequence=%llu "
                "guest=%llx guest_bytes=%llu handle=%llx offset=%llu range=%llu slot=%u adjust=%u "
                "write_index=%u push_index=%u flags=%u sharp=%08x,%08x,%08x,%08x\n",
                sample, ordinal, Print(sequence), Print(d.guest), Print(d.bytes), Print(d.handle),
                Print(d.offset), Print(d.range), d.slot, d.adjust, d.write_index, d.push_index,
                d.flags, d.sharp[0], d.sharp[1], d.sharp[2], d.sharp[3]);
}

inline void MaybeReport(bool missing_flush = false) {
    auto& s = state;
    auto& c = s.chosen;
    auto& old = s.predecessor;
    const auto& r = s.resident;
    if (s.terminal || c.drop.name.empty() ||
        (c.active && c.direct && (!c.finished || (!c.flushed && !missing_flush)))) return;
    s.terminal = true;
    const bool predecessor = old.sequence && old.generation == r.generation &&
        old.allocation == r.allocation && old.placement == r.placement &&
        old.cookie == c.bank_cookie && old.frame == c.bank_frame && old.pass == c.bank_pass &&
        old.frame == c.last_clone_frame && old.pass == c.last_clone_pass;
    const bool consecutive = predecessor && c.drop.frame && old.frame == c.drop.frame - 1;
    const bool completed = writer.Available();
    const bool late = c.classify_seen && !c.classify_complete && completed;
    const bool route = c.expected_descriptor && c.bound_match && !c.competing && writer.reservation &&
        !writer.callback_conflict.load(std::memory_order_acquire);
    const char* outcome = !c.active || !c.direct ? "unmatched-loss" :
        !c.issued || !c.original || !c.joined ? "unissued" :
        !c.flushed || c.flush.name.empty() ? "unobserved-flush" :
        !predecessor ? "missing-predecessor" : !consecutive ? "nonconsecutive-predecessor" :
        !route ? "unwitnessed-reservation" : !c.classify_seen ? "classification-unobserved" :
        !c.draw.final_key || c.draw.placement != c.draw.final_key || c.draw.canonical ||
            c.draw.native_origin3 != 5 ? "unmatched-placement" : "joined";
    const auto sequence = Print(c.draw.sequence);
    const auto generation = Print(r.generation);
    std::printf("Reflection ordinal3 event=producer role=mirror sequence=%llu generation=%llu packet=%llu "
                "packet_present=%u ring=%s prepared=%u resolver=%s resolver_key=%llx reservation=%llu "
                "source=%llx handle=%llx offset=%llu cache_generation=%llu tick=%llu producer=%s "
                "reserve_failed=%u bind_complete=%u classify_seen=%u classify_complete=%u complete=%u "
                "late=%u competing=%u descriptor_match=%u guest_protections=%u guest_available=%u "
                "predecessor_equal=%d guest_equal=%d\n",
                sequence, generation, Print(c.packet.number), u32(bool(c.packet.renderer)),
                c.packet.renderer ? Name(Ring(c.packet.encoded & RingReasonMask)) : "no-packet",
                u32(bool(c.packet.encoded & PreparedTag)), Name(c.resolver), Print(c.resolver_key),
                Print(writer.reservation), Print(writer.source), Print(writer.handle), Print(writer.offset),
                Print(writer.cache_generation), Print(writer.tick), Name(writer.route), u32(writer.reserve_failed),
                u32(c.bind_complete), u32(c.classify_seen), u32(c.classify_complete), u32(completed), u32(late),
                u32(c.competing), u32(route), c.guest_protections, u32(c.guest_available),
                completed && predecessor ? int(writer.copied == old.bytes) : -1,
                completed && c.guest_available ? int(writer.copied == c.guest) : -1);
    if (completed) WordRow("producer", writer.copied, c.draw.sequence, r.generation);
    if (predecessor) WordRow("predecessor", old.bytes, c.draw.sequence, r.generation);
    if (c.guest_available) WordRow("guest", c.guest, c.draw.sequence, r.generation);
    DescriptorRow("selected", 0, c.draw.object0, c.draw.sequence);
    DescriptorRow("selected", 3, c.draw.object3, c.draw.sequence);
    DescriptorRow("selected", 1, c.draw.palette, c.draw.sequence);
    if (predecessor) {
        DescriptorRow("predecessor", 0, old.object0, old.sequence);
        DescriptorRow("predecessor", 3, old.object3, old.sequence);
        DescriptorRow("predecessor", 1, old.palette, old.sequence);
    }
    std::printf("Reflection ordinal3 event=issue role=mirror sequence=%llu generation=%llu frame=%llu "
                "pass=%llu tick=%llu reservation=%llu ready=%llx handle=%llx source_key=%llx raster_key=%llx "
                "vs_stage=%llx ps_stage=%llx count=%u first=%u instances=%u first_instance=%u base=%d "
                "issue=%s original=%u issued=%u alpha=%u allocation=%llu placement=%llu cookie=%llu "
                "joined=%u canonical=%u object0_complete=%u object3_complete=%u origin0=%u origin3=%u "
                "object0_digest=%016llx old_object0_digest=%016llx active_words=%u old_active_words=%u "
                "palette_current=%u sharp_same=%u pose_same=%d geometry_same=%d determinants=partial "
                "capture_tick=%llu native=%u preview=%u loading=%u depth_uid=%llu cb0_uid=%llu "
                "palette_same=%d final_key=%llu object0_prefix=%016llx object3_prefix=%016llx fetch_prefix=%016llx\n",
                sequence, generation, Print(c.draw.frame), Print(c.draw.pass), Print(c.draw.tick),
                Print(writer.reservation), Print(c.ready_handle), Print(c.issued_handle), Print(c.source_key),
                Print(c.raster_key), Print(c.vs_stage), Print(c.ps_stage), c.count, c.first, c.instances, c.first_instance,
                c.vertex, c.issue, u32(c.original), u32(c.issued), u32(c.alpha), Print(c.draw.allocation),
                Print(c.draw.placement), Print(c.draw.cookie), u32(c.joined), u32(c.draw.canonical),
                u32(c.draw.object0_complete), u32(c.draw.object3_complete), c.draw.native_origin0,
                c.draw.native_origin3, Print(c.draw.object0_digest), Print(old.object0_digest),
                u32(c.draw.active_words), u32(old.active_words), u32(c.draw.palette_current), u32(c.sharp_same),
                predecessor ? int(old.pose == c.draw.pose) : -1,
                predecessor && c.draw.geometry && old.geometry ? int(c.draw.geometry == old.geometry) : -1,
                Print(c.capture_tick), u32(c.draw.pose.native), u32(c.draw.pose.preview), u32(c.draw.pose.loading),
                Print(c.draw.pose.depth_uid), Print(c.draw.pose.cb0_uid),
                predecessor ? int(old.palette == c.draw.palette) : -1, Print(c.draw.final_key),
                Print(c.draw.ordinary_object0_prefix), Print(c.draw.ordinary_object3_prefix),
                Print(c.draw.fetch_prefix));
    const auto name = [](std::string_view value) { return value.empty() ? "none" : value.data(); };
    std::printf("Reflection ordinal3 event=terminal role=mirror outcome=%s renderer=%llx generation=%llu "
                "epoch=%llu allocation=%llu revision=%llu surface=%llu old_placement=%llu placement=%llu "
                "frame=%llu pass=%llu sequence=%llu old_sequence=%llu prior_frame=%llu prior_pass=%llu "
                "prior_cookie=%llu build_cookie=%llu cookie=%llu upstream=%s upstream_cookie=%llu "
                "upstream_a=%llu upstream_b=%llu bank=%s drop=%s ordinary=%s ordinary_revision=%llu "
                "flush=%s flush_revision=%llu flush_mask=%llu reservation=%llu producer=%s "
                "bind_complete=%u classify_complete=%u late=%u loss_sequence=%llu ordinary_cookie=%llu "
                "flush_cookie=%llu\n",
                outcome, Print(reinterpret_cast<u64>(s.renderer)), generation, Print(r.epoch),
                Print(r.allocation), Print(r.revision), Print(r.surface), Print(r.placement),
                Print(c.draw.placement), Print(c.drop.frame), Print(c.drop.pass), sequence,
                Print(old.sequence), Print(c.bank_frame), Print(c.bank_pass), Print(c.bank_cookie),
                Print(c.pass_build_cookie), Print(c.draw.cookie), name(c.upstream.name),
                Print(c.upstream.cookie), Print(c.upstream.a), Print(c.upstream.b), name(c.bank.name),
                name(c.drop.name), name(c.ordinary.name), Print(c.ordinary.revision), name(c.flush.name),
                Print(c.flush.revision), Print(c.flush.a), Print(writer.reservation), Name(writer.route),
                u32(c.bind_complete), u32(c.classify_complete), u32(late), Print(c.loss_sequence),
                Print(c.ordinary.cookie), Print(c.flush.cookie));
}

inline void Trace(u32 role, u64 sequence, std::string_view name, u64 frame, u64 pass,
                  u64 allocation, u64 revision, u64 cookie, u64 a, u64 b) {
    auto& s = state;
    auto& c = s.chosen;
    if (!On() || s.terminal || role != Mirror || allocation != s.resident.allocation) return;
    if (s.resident.live && revision == s.resident.revision &&
        (name == "observe-identity-change" || name == "observe-refused" || name == "observe-ineligible-shadow" ||
         name.starts_with("submission-") || name == "palette-observed-identity")) {
        s.upstream = {name, frame, pass, cookie, a, b, revision};
        s.upstream_sequence = sequence;
    }
    if (!c.drop.name.empty() && frame == c.drop.frame && pass == c.drop.pass) {
        if (name.starts_with("ordinary-") && sequence && sequence == c.draw.sequence) {
            c.ordinary = {name, frame, pass, cookie, a, b, revision};
        }
        if (name.starts_with("flush-") && c.draw.cookie && c.draw.cookie == cookie && c.flush.name.empty()) {
            c.flush = {name, frame, pass, cookie, a, b, revision};
        }
    }
}

inline void Invalidate(const void* scheduler, const void* owner, u64 epoch, u32 role, u64 allocation,
                       u64 revision, u64 surface, u64 placement, u64 sequence,
                       std::string_view name, u64 frame, u64 pass, u64 bank_frame, u64 bank_pass,
                       u64 bank_cookie, u64 build_cookie, u64 prior_frame, u64 prior_pass) {
    auto& s = state;
    auto& r = s.resident;
    auto& c = s.chosen;
    if (!On() || s.terminal || !r.live || role != Mirror || r.scheduler != scheduler ||
        r.owner != owner || r.epoch != epoch || r.allocation != allocation ||
        r.revision != revision || r.surface != surface || r.placement != placement) return;
    if (name.starts_with("bank-clear-") && c.bank.name.empty()) {
        c.bank = {name, frame, pass, bank_cookie};
        c.bank_frame = bank_frame;
        c.bank_pass = bank_pass;
        c.bank_cookie = bank_cookie;
        c.pass_build_cookie = build_cookie;
    }
    if (!name.starts_with("clone-drop-") || !c.drop.name.empty()) return;
    c.drop = {name, frame, pass};
    c.loss_sequence = sequence;
    if (c.bank.name.empty()) {
        c.bank_frame = bank_frame;
        c.bank_pass = bank_pass;
        c.bank_cookie = bank_cookie;
        c.pass_build_cookie = build_cookie;
    }
    c.last_clone_frame = prior_frame;
    c.last_clone_pass = prior_pass;
    r.live = false;
    if (s.upstream.frame == frame && s.upstream.pass == pass && s.upstream_sequence == sequence) {
        c.upstream = s.upstream;
    }
    c.direct = c.active && sequence && c.draw.sequence == sequence && !c.upstream.name.empty();
}

template <class Row>
void FinishDraw(const Row& row) {
    auto& c = state.chosen;
    if (!On() || state.terminal || !c.active || c.draw.sequence != row.sequence) return;
    c.finished = true;
    c.draw.frame = row.frame;
    c.draw.pass = row.pass;
    c.draw.tick = row.record_tick;
    c.draw.allocation = row.allocation;
    c.draw.placement = row.placement;
    c.draw.cookie = row.cookie;
    c.issued = row.record_tick != 0;
    c.original = row.original && row.stamped && ExactStages(row.raster_vs, row.raster_ps);
    c.alpha = row.effective;
    c.joined = row.confirmed;
    c.ready_handle = row.ready ? row.ready : c.ready_handle;
    c.issued_handle = row.handle;
    c.source_key = row.source_key;
    c.raster_key = row.raster_key;
    c.vs_stage = row.raster_vs;
    c.ps_stage = row.raster_ps;
    c.issue = row.issue;
    c.instances = row.instances;
    c.first_instance = row.first_instance;
    c.vertex = row.vertex;
    c.count = row.key.count;
    c.first = row.key.first;
    if (c.direct && (row.frame != c.drop.frame || row.pass != c.drop.pass ||
                     row.generation != state.resident.generation)) c.direct = false;
    MaybeReport();
}

inline void FinishFlush(const void* scheduler, u64 generation, u64 frame, u64 pass) {
    if (!On() || state.terminal || state.resident.scheduler != scheduler ||
        state.resident.generation != generation) return;
    auto& c = state.chosen;
    if (!c.drop.name.empty() && c.drop.frame == frame && c.drop.pass == pass) {
        c.flushed = true;
        MaybeReport();
    }
}

} // namespace Vulkan::ReflectionOrdinal3
