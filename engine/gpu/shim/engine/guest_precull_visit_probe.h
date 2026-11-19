// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "engine_hooks.h"
#if defined(_WIN32) && defined(BB_TEST_GUEST_PRECULL_VISITS)
#include "../bbport_live_knobs.h"
#include "../bbport_native_calls.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <windows.h>

namespace BbEngine::GuestPrecull {
using u8 = std::uint8_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;

enum class Event : u64 {
    None, EnterA, EnterB, VisitorVtable, CandidateVtable, EarlyReject,
    UiBypass, LocalBypass, Classify, Classification, NoQueue, QueueStart,
    CandidateQueued, DrawDisabled, DrawDisabledInverse, DirectBegin, DirectEnd,
    ClassSlot, QueueEnd, TailBegin, Leave
};
}

#include "guest_precull_visit_sites.h"

namespace BbEngine::GuestPrecull {
enum class Basis : u32 { Unknown, Classified, UiBypass, LocalBypass };
enum class Exit : u32 { Unknown, RejectedBeforeOrAfterClassifier, ClassifierZero, NoQueue, DrawDisabled,
                        DirectReturned, TailDispatched, AppendUnresolved, Appended };
enum class WindowId : u32 { Off, Seed, Held };
enum class SpanStatus : u32 { IssuedOnly, RawIndexBytes, NoStaticSpan, ReadRefused, UnprovedProducer };
using Clock = std::chrono::steady_clock;
inline constexpr std::size_t kVisitCapacity = 8192, kGxCapacity = 256, kNesting = 8;
inline constexpr u64 kWindowUs = 250000;
inline constexpr char kIdentity[] = "071df19c8880086d97182dbc057bc8cb37badaca57d9112683836b24a0444c0a";

struct Visit {
    u64 id = 0, enter_us = 0, leave_us = 0;
    u64 caller = 0, visitor = 0, candidate = 0, visitor_vtable = 0, candidate_vtable = 0;
    u64 classifier_object = 0, classifier = 0, operand = 0;
    u64 context = 0, draw_target = 0, queue = 0, candidate_slot = 0, class_slot = 0;
    u32 worker = 0, path = 0, raw_class = 0, queued_class = 0;
    Basis basis = Basis::Unknown;
    Exit exit = Exit::Unknown;
};

struct GxStamp {
    u64 cmd = 0, pending = 0, context = 0, record = 0, sequence = 0;
    u64 index_base = 0, index_key = 0, objects_epoch = 0;
    u32 count = 0, index_format = 0, topology = 0;
    u32 index_available = 0, index_format_gx = 0, topology_gx = 0;
    bool index_known = false;
};

struct Bounds {
    u64 operand = 0, classifier = 0;
    std::array<u32, 6> words{};
    bool valid = false;
};
enum class ProducerRoute : u32 { Foreign, Model, Replay };
struct ProducerOwner {
    u64 gx_caller = 0, selected = 0, base_record = 0, model_arg = 0, instance_arg = 0, replay_record = 0;
    u64 visit = 0, parent = 0, child = 0, child_target = 0, context = 0, b_caller = 0, b_slot = 0, child_slot = 0;
    u32 range_count = 0, base_first = 0, local_first = 0, base_vertex = 0;
    std::array<u32, 4> replay_words{};
    Bounds bounds{};
    ProducerRoute route = ProducerRoute::Foreign;
    bool entry = false;
};
struct GxFact {
    GxStamp gx;
    u64 issue = 0, from = 0;
    u64 visit = 0, us = 0, cb = 0, index = 0, ordered_bytes_fnv = 0;
    u32 index_bytes = 0, worker = 0, kind = 0, first = 0, count = 0, flags = 0, pred = 0;
    u32 base_vertex = 0, instances = 0;
    SpanStatus status = SpanStatus::IssuedOnly;
    ProducerOwner outer{};
};

template <typename T> struct Cell {
    T input{};
    T result{};
    std::atomic<bool> input_ready{false};
    std::atomic<bool> finished{false};
};

struct Window {
    std::array<Cell<Visit>, kVisitCapacity> visits{};
    std::array<Cell<GxFact>, kGxCapacity> gx{};
    std::atomic<u32> visit_count{0}, gx_count{0}, nested_lost{0}, direct_entry_lost{0};
    u64 start_us = 0, stop_us = 0;
    u32 control_generation = 0;
    WindowId id = WindowId::Off;
    bool dumped = false;
};

inline std::array<Window, 2> windows;
inline std::atomic<Window*> armed{nullptr};
static_assert(decltype(armed)::is_always_lock_free);
inline std::atomic<bool> installed{false};
inline std::atomic_flag poll_lock = ATOMIC_FLAG_INIT;
inline constinit std::atomic<u64> draws{0}, issue_serial{0};
inline u32 last_generation = std::numeric_limits<u32>::max();
inline std::uintptr_t image = 0;
inline std::size_t image_bytes = 0;
inline std::array<std::uint8_t*, 2> clones{};
inline constexpr std::size_t kPrefix[] = {15, 20};
inline std::array<std::array<u8, 20>, 2> redirects{};

struct Frame {
    Window* owner = nullptr;
    Cell<Visit>* slot = nullptr;
    Visit fact{};
    Bounds bounds{};
    u64 return_slot = 0;
    bool direct = false;
};
inline thread_local std::array<Frame, kNesting> stack;
inline thread_local std::size_t depth = 0;
inline thread_local u32 worker_id = 0;
inline thread_local GxStamp stamp;
struct GxProducer {
    Window* owner = nullptr;
    u64 pending = 0, context = 0, from = 0;
    u32 count = 0, first = 0;
    ProducerOwner outer{};
};
inline thread_local GxProducer producer;
inline bool Shortlisted(u32 count);

inline u64 NowUs() {
    return std::chrono::duration_cast<std::chrono::microseconds>(Clock::now().time_since_epoch()).count();
}

inline unsigned long long Hex(u64 value) { return static_cast<unsigned long long>(value); }

inline bool Peek(u64 addr, void* out, std::size_t bytes) {
    if (!addr || addr > std::numeric_limits<u64>::max() - bytes) return false;
    SIZE_T read = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(addr),
                             out, bytes, &read) && read == bytes;
}

inline u64 WordAt(u64 addr) {
    u64 out = 0;
    return Peek(addr, &out, sizeof out) ? out : 0;
}

inline bool WithinImage(u64 addr, std::size_t count) {
    return addr >= image && count <= image_bytes && addr - image <= image_bytes - count;
}

inline bool Protection(const void* address, std::size_t bytes, DWORD expected) {
    MEMORY_BASIC_INFORMATION info{};
    if (!VirtualQuery(address, &info, sizeof info) || info.State != MEM_COMMIT ||
        info.Protect != expected) return false;
    const auto within = reinterpret_cast<std::uintptr_t>(address) -
                        reinterpret_cast<std::uintptr_t>(info.BaseAddress);
    return bytes <= info.RegionSize && within <= info.RegionSize - bytes;
}

} // namespace BbEngine::GuestPrecull

#include "guest_precull_outer_probe.h"

namespace BbEngine::GuestPrecull {
inline bool PinnedBinding(DWORD protect) {
    const auto valid = [protect](u32 at, std::span<const u8> expected) {
        const auto* code = reinterpret_cast<const u8*>(image + at);
        return WithinImage(image + at, expected.size()) && Protection(code, expected.size(), protect) &&
               std::memcmp(code, expected.data(), expected.size()) == 0;
    };
    return valid(Sites::kBinder, Sites::kStockBinder) &&
           valid(Sites::kTopologyConvert, Sites::kStockTopologyConvert) &&
           valid(Sites::kTopologyWords, Sites::kStockTopologyWords);
}

inline bool LoadedTextPinned() {
    constexpr u32 starts[] = {Sites::kA, Sites::kB};
    const std::span<const u8> bodies[] = {Sites::kStockA, Sites::kStockB};
    for (std::size_t i = 0; i < clones.size(); ++i) {
        const auto* text = reinterpret_cast<const u8*>(image + starts[i]);
        if (!Protection(text, bodies[i].size(), PAGE_EXECUTE_READ) ||
            !Protection(clones[i], 4096, PAGE_EXECUTE_READ) ||
            std::memcmp(text, redirects[i].data(), kPrefix[i]) != 0 ||
            std::memcmp(text + kPrefix[i], bodies[i].data() + kPrefix[i],
                        bodies[i].size() - kPrefix[i]) != 0 ||
            !Protection(reinterpret_cast<const void*>(image + Sites::kSlots[i]), 8, PAGE_READWRITE) ||
            WordAt(image + Sites::kSlots[i]) != image + starts[i]) return false;
    }
    for (std::size_t i = 0; i < std::size(Sites::kGxReturn); ++i) {
        const auto& pin = Sites::kGxCallPins[i];
        const auto* code = reinterpret_cast<const u8*>(image + Sites::kGxReturn[i] - sizeof pin);
        if (!Protection(code, sizeof pin, PAGE_EXECUTE_READ) || std::memcmp(code, pin, sizeof pin)) return false;
    }
    const auto* classifier = reinterpret_cast<const u8*>(image + Sites::kClassifier);
    return (!Outer::enabled || Outer::Pinned(true)) && PinnedBinding(PAGE_EXECUTE_READ) &&
           Protection(classifier, sizeof Sites::kStockClassifier, PAGE_EXECUTE_READ) &&
           std::memcmp(classifier, Sites::kStockClassifier, sizeof Sites::kStockClassifier) == 0;
}

inline void Dump(Window& w) {
    if (!w.start_us || w.dumped) return;
    w.dumped = true;
    const auto visits = w.visit_count.load(std::memory_order_acquire);
    const auto gx = w.gx_count.load(std::memory_order_acquire);
    u32 input_only = 0, missing = 0, joined = 0;
    for (u32 i = 0; i < std::min<std::size_t>(visits, w.visits.size()); ++i) {
        const auto& row = w.visits[i];
        if (!row.input_ready.load(std::memory_order_acquire)) {
            ++missing;
            continue;
        }
        const bool complete = row.finished.load(std::memory_order_acquire);
        input_only += !complete;
        const auto& v = complete ? row.result : row.input;
        std::printf("G108 visit window=%u visit=%llu route=%u worker=%u begin_us=%llu end_us=%llu "
                    "caller=%llx visitor=%llx candidate=%llx vtable=%llx candidate_vtable=%llx "
                    "basis=%u exit=%u raw=%u classifier_object=%llx classifier=%llx operand=%llx "
                    "context=%llx target=%llx queue=%llx candidate_slot=%llx class_slot=%llx "
                    "queued_raw=%u complete=%u\n",
                    u32(w.id), Hex(v.id), v.path, v.worker, Hex(v.enter_us), Hex(v.leave_us),
                    Hex(v.caller), Hex(v.visitor), Hex(v.candidate), Hex(v.visitor_vtable), Hex(v.candidate_vtable),
                    u32(v.basis), u32(v.exit), v.raw_class, Hex(v.classifier_object), Hex(v.classifier), Hex(v.operand),
                    Hex(v.context), Hex(v.draw_target), Hex(v.queue), Hex(v.candidate_slot),
                    Hex(v.class_slot), v.queued_class, unsigned(complete));
    }
    for (u32 i = 0; i < std::min<std::size_t>(gx, w.gx.size()); ++i) {
        const auto& row = w.gx[i];
        if (!row.finished.load(std::memory_order_acquire)) {
            ++missing;
            continue;
        }
        const auto& f = row.result;
        joined += f.visit != 0;
        std::printf("G108 gx window=%u visit=%llu worker=%u time_us=%llu cb=%llx packet=%llx "
                    "pending=%llx gx_context=%llx record=%llx sequence=%llu gx_objects_epoch=%llu issue=%llu gx_return=%llx "
                    "kind=%u first=%u count=%u topology=%u index_format=%u address=%llx bytes=%u topology_gx=%u index_format_gx=%u "
                    "ordered_bytes_fnv=%llx index_key=%llx flags=%u predicate=%u base_vertex=%u instances=%u "
                    "span=%u\n",
                    u32(w.id), Hex(f.visit), f.worker, Hex(f.us), Hex(f.cb), Hex(f.gx.cmd),
                    Hex(f.gx.pending), Hex(f.gx.context), Hex(f.gx.record), Hex(f.gx.sequence),
                    Hex(f.gx.objects_epoch), Hex(f.issue), Hex(f.from), f.kind, f.first, f.count, f.gx.topology, f.gx.index_format,
                    Hex(f.index), f.index_bytes, f.gx.topology_gx, f.gx.index_format_gx, Hex(f.ordered_bytes_fnv), Hex(f.gx.index_key),
                    f.flags, f.pred, f.base_vertex, f.instances, u32(f.status));
        Outer::Dump(w, f);
    }
    std::printf("G108 window tag=%u knob_generation=%u begin_us=%llu end_us=%llu visits=%u "
                "matching_count_issues=%u scoped_issues=%u overflow=%u incomplete=%u missing=%u "
                "nested_lost=%u gx_entry_lost=%u scene_epoch=unknown pass=unknown coverage=open\n",
                u32(w.id), w.control_generation, Hex(w.start_us), Hex(w.stop_us), visits, gx, joined,
                unsigned(visits > w.visits.size() || gx > w.gx.size()), input_only, missing,
                w.nested_lost.load(std::memory_order_relaxed), w.direct_entry_lost.load(std::memory_order_relaxed));
    std::fflush(stdout);
}

inline void Stop(u64 now) {
    if (Window* w = armed.exchange(nullptr, std::memory_order_acq_rel)) w->stop_us = now;
}

inline void FinishProbe() {
    if (poll_lock.test_and_set(std::memory_order_acquire)) return;
    Stop(NowUs());
    for (auto& w : windows) Dump(w);
    poll_lock.clear(std::memory_order_release);
}

inline WindowId Tag(const char* text) {
    if (!text) return WindowId::Off;
    if (std::strcmp(text, "seed") == 0) return WindowId::Seed;
    if (std::strcmp(text, "held") == 0) return WindowId::Held;
    return WindowId::Off;
}

inline void Poll() {
    if ((draws.fetch_add(1, std::memory_order_relaxed) & 255) != 0 ||
        poll_lock.test_and_set(std::memory_order_acquire)) return;
    const u64 now = NowUs();
    if (Window* w = armed.load(std::memory_order_relaxed); w && now - w->start_us >= kWindowUs) Stop(now);
    const u32 generation = BbLiveKnobs::Generation();
    if (generation != last_generation) {
        last_generation = generation;
        const auto knob = BbLiveKnobs::Lookup("BB_GUEST_PRECULL_WINDOW");
        const auto tag = Tag(knob.Get());
        const auto* previous = armed.load(std::memory_order_relaxed);
        if (previous && previous->id != tag) Stop(now);
        if (tag != WindowId::Off) {
            Window& w = windows[u32(tag) - 1];
            const bool ordered = tag == WindowId::Seed || windows[0].start_us;
            if (!w.start_us && ordered && LoadedTextPinned()) {
                w.id = tag;
                w.control_generation = generation;
                w.start_us = NowUs();
                armed.store(&w, std::memory_order_release);
                std::printf("G108 arm tag=%u knob_generation=%u begin_us=%llu text_pins=rx\n",
                            u32(tag), generation, Hex(w.start_us));
                std::fflush(stdout);
            } else if (!w.start_us) {
                std::printf("G108 window refused tag=%u ordered=%u executable_pins_or_order=failed\n",
                            u32(tag), unsigned(ordered));
            }
        } else if (knob.Get() && std::strcmp(knob.Get(), "dump") == 0) {
            for (auto& w : windows) Dump(w);
        }
    }
    poll_lock.clear(std::memory_order_release);
}

inline std::int64_t __attribute__((sysv_abi)) Observe(u64 event_id, const u64* saved) {
    const auto event = static_cast<Event>(event_id);
    if (event == Event::EnterA || event == Event::EnterB) {
        Outer::EnterVisitor();
        Window* w = armed.load(std::memory_order_acquire);
        // A nested visitor could tail-dispatch past its own frame. Refuse to attribute any
        // later GX issue to the outer candidate of that dynamic call.
        if (depth && depth <= stack.size()) stack[depth - 1].direct = false;
        const auto index = depth++;
        if (index >= stack.size()) {
            if (w) w->nested_lost.fetch_add(1, std::memory_order_relaxed);
            return 0;
        }
        auto& f = stack[index];
        f = {};
        if (!w) return 0;
        f.owner = w;
        const u32 ordinal = w->visit_count.fetch_add(1, std::memory_order_relaxed);
        f.fact.id = (u64(w->id) << 32) | (u64(ordinal) + 1);
        f.fact.path = event == Event::EnterA ? 1u : 2u;
        f.fact.visitor = saved[5];
        f.fact.candidate = saved[4];
        f.fact.caller = saved[kPassiveStack + 1];
        f.return_slot = Outer::GuestStack(saved, true);
        f.fact.enter_us = NowUs();
        if (!worker_id) worker_id = GetCurrentThreadId();
        f.fact.worker = worker_id;
        if (ordinal < w->visits.size()) {
            f.slot = &w->visits[ordinal];
            f.slot->input = f.fact;
            f.slot->input_ready.store(true, std::memory_order_release);
        }
        return 0;
    }
    const bool leaving = event == Event::Leave || event == Event::TailBegin;
    if (!depth) return 0;
    if (depth > stack.size()) {
        if (leaving) --depth;
        return 0;
    }
    auto& f = stack[depth - 1];
    if (!f.slot) {
        if (leaving) --depth;
        return 0;
    }
    auto& v = f.fact;
    const auto flags = saved[kPassiveFlags];
    const auto ax = saved[kPassiveRax];
    const bool zero = flags & (u64(1) << 6);
    const bool greater = !zero && ((flags >> 7) & 1) == ((flags >> 11) & 1);
    switch (event) {
    case Event::VisitorVtable: v.visitor_vtable = ax; break;
    case Event::CandidateVtable: v.candidate_vtable = ax; break;
    case Event::EarlyReject: if (zero) v.exit = Exit::RejectedBeforeOrAfterClassifier; break;
    case Event::UiBypass:
        if (!zero) {
            v.basis = Basis::UiBypass;
            if (v.path == 1) v.raw_class = static_cast<u32>(ax);
        }
        break;
    case Event::LocalBypass:
        if (greater) {
            v.basis = Basis::LocalBypass;
            v.raw_class = static_cast<u32>(ax);
        }
        break;
    case Event::Classify:
        v.classifier_object = saved[5];
        v.classifier = ax;
        v.operand = saved[4];
        Outer::RememberBounds(f, ax);
        break;
    case Event::Classification:
        v.basis = Basis::Classified;
        v.raw_class = static_cast<u32>(ax);
        if (!v.raw_class) v.exit = Exit::ClassifierZero;
        break;
    case Event::NoQueue: if (zero) v.exit = Exit::NoQueue; break;
    case Event::DrawDisabled: if (!zero) v.exit = Exit::DrawDisabled; break;
    case Event::DrawDisabledInverse: if (!zero) v.exit = Exit::DrawDisabled; break;
    case Event::QueueStart:
        v.queue = saved[kSavedRbx];
        v.raw_class = static_cast<u32>(ax);
        v.exit = Exit::AppendUnresolved;
        break;
    case Event::CandidateQueued: {
        const u64 tail = WordAt(v.queue + 0x18);
        if (tail >= 8 && WordAt(tail - 8) == v.candidate) v.candidate_slot = tail - 8;
        break;
    }
    case Event::ClassSlot:
        v.class_slot = ax;
        v.queued_class = static_cast<u32>(saved[2]);
        break;
    case Event::QueueEnd:
        if (v.candidate_slot && v.class_slot && v.raw_class == v.queued_class)
            v.exit = Exit::Appended;
        break;
    case Event::DirectBegin:
        v.candidate_vtable = ax;
        v.draw_target = WordAt(ax + 0x10);
        v.context = saved[4];
        f.direct = true;
        break;
    case Event::DirectEnd:
        v.exit = Exit::DirectReturned;
        f.direct = false;
        break;
    case Event::TailBegin:
        v.draw_target = ax;
        v.context = saved[4];
        v.exit = Exit::TailDispatched;
        Outer::Tail(f, saved[kSavedRbp]);
        break;
    default: break;
    }
    if (leaving) {
        v.leave_us = NowUs();
        f.slot->result = v;
        f.slot->finished.store(true, std::memory_order_release);
        --depth;
    }
    return 0;
}

inline bool Shortlisted(u32 count) {
    return count == 18282 || count == 10968 || count == 3651 ||
           count == 42441 || count == 25311 || count == 8088;
}

inline void AttachStamp(const GxStamp& issued) { stamp = issued; }
inline void ClearStamp() { stamp = {}; }

inline bool StaticSpan(const BbNativeCalls::DrawRecord& r, const GxStamp& g, u64& address, u32& bytes) {
    if (!g.index_known || g.index_format > 1 || !Shortlisted(r.index_count)) return false;
    const u64 width = g.index_format == 0 ? 2 : 4;
    const u64 first = r.kind == BbNativeCalls::DrawIndexOffset ? width * r.index_offset : 0;
    if (r.kind != BbNativeCalls::DrawIndexOffset && r.kind != BbNativeCalls::DrawIndex) return false;
    if (g.index_base > std::numeric_limits<u64>::max() - first) return false;
    address = r.kind == BbNativeCalls::DrawIndexOffset ? g.index_base + first : r.index_addr & ~u64(1);
    bytes = r.index_count * static_cast<u32>(width);
    return address && !(address % width) && address <= std::numeric_limits<u64>::max() - bytes &&
           first <= g.index_available && bytes <= g.index_available - first;
}

inline bool DigestSpan(u64 address, u32 bytes, u64& digest) {
    std::array<u8, 4096> block{};
    u64 hash = 14695981039346656037ull;
    while (bytes) {
        const auto take = std::min<std::size_t>(bytes, block.size());
        if (!Peek(address, block.data(), take)) return false;
        for (std::size_t i = 0; i < take; ++i) hash = (hash ^ block[i]) * 1099511628211ull;
        address += take;
        bytes -= static_cast<u32>(take);
    }
    digest = hash;
    return true;
}

inline void OnGxProducer(u32 id, const u64* saved, bool passive = false) {
    producer = {};
    Window* w = armed.load(std::memory_order_acquire);
    const u32 count = static_cast<u32>(saved[3]);
    if (!w || id >= std::size(Sites::kGxReturn) || !Shortlisted(count)) return;
    const u32 first = static_cast<u32>(saved[id == 0 ? 2 : 1]);
    producer = {
        .owner = w, .pending = saved[4], .context = saved[5],
        .from = image + Sites::kGxReturn[id], .count = count,
        .first = first, .outer = Outer::GxEntry(w, saved, id, first, count, passive)
    };
}

inline std::int64_t __attribute__((sysv_abi)) ObserveGxProducer(u64 id, const u64* saved) {
    OnGxProducer(static_cast<u32>(id - 1), saved, true);
    return 0;
}

inline bool MatchProducer(const GxProducer& p, const Window& w, u64 return_pc, u64 cb,
                          const BbNativeCalls::DrawRecord& r) {
    return p.owner == &w && p.pending && p.context &&
           p.context <= std::numeric_limits<u64>::max() - 0x10 &&
           return_pc == p.from && cb == p.context + 0x10 &&
           r.kind == BbNativeCalls::DrawIndexOffset && p.count == r.index_count && p.first == r.index_offset;
}

inline void StaticGxBinding(GxStamp& g) {
    // 26bba30 binds the static base from resource+20 plus pending+1c. It converts
    // the pending primitive via the pinned native table and records INDEX_TYPE=(format==0x2a).
    // Compare the pending object with the cache actual binder updated at context+b518.
    struct Binding {
        u64 base;
        u32 topology, format;
    } last{};
    const u64 resource = WordAt(g.pending + 0x10);
    u8 dynamic = 0;
    u32 byte_offset = 0, size = 0;
    if (!resource || !Peek(resource + 0x40, &dynamic, 1) || dynamic ||
        !Peek(resource + 0x2c, &size, sizeof size) ||
        !Peek(g.pending + 0x08, &g.topology_gx, sizeof g.topology_gx) ||
        !Peek(g.pending + 0x18, &g.index_format_gx, sizeof g.index_format_gx) ||
        !Peek(g.pending + 0x1c, &byte_offset, sizeof byte_offset) || byte_offset > size ||
        !Peek(g.context + 0xb518, &last, sizeof last)) return;
    const u64 base = WordAt(resource + 0x20);
    u32 topology = 0;
    if (g.topology_gx < sizeof(Sites::kStockTopologyWords) / 4)
        std::memcpy(&topology, Sites::kStockTopologyWords + g.topology_gx * 4, sizeof topology);
    if (!base || base > std::numeric_limits<u64>::max() - byte_offset ||
        base + byte_offset != last.base || !topology || topology != last.topology ||
        u32(g.index_format_gx == 0x2a) != last.format) return;
    g.index_base = last.base;
    g.index_format = last.format;
    g.topology = last.topology;
    g.index_available = size - byte_offset;
    g.index_known = true;
}

inline void Issued(u64 packet, u64 cb, const BbNativeCalls::DrawRecord& draw, u64 return_pc) {
    if (!installed.load(std::memory_order_relaxed)) return;
    Poll();
    const GxStamp g = stamp;
    ClearStamp();
    if (!Shortlisted(draw.index_count) || draw.kind == BbNativeCalls::DrawAuto) return;
    const auto p = producer;
    if (draw.kind == BbNativeCalls::DrawIndexOffset) producer = {};
    Window* w = armed.load(std::memory_order_acquire);
    if (!w) return;
    const auto ordinal = w->gx_count.fetch_add(1, std::memory_order_relaxed);
    if (ordinal >= w->gx.size()) return;
    auto& cell = w->gx[ordinal];
    auto& out = cell.result;
    out.us = NowUs();
    out.cb = cb;
    out.kind = draw.kind;
    out.first = draw.index_offset;
    out.count = draw.index_count;
    out.flags = draw.flags;
    out.pred = draw.predicate;
    out.base_vertex = draw.base_vertex;
    out.instances = draw.instances;
    out.from = WithinImage(return_pc, 1) ? return_pc - image : 0;
    if (!worker_id) worker_id = GetCurrentThreadId();
    out.worker = worker_id;
    if (MatchProducer(p, *w, return_pc, cb, draw)) {
        out.issue = issue_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        out.outer = p.outer;
        if ((draw.flags & BbNativeCalls::CarriesBaseVertex) && draw.base_vertex != p.outer.base_vertex) {
            out.outer.selected = 0;
            out.outer.replay_record = 0;
            out.outer.visit = 0;
        }
        if (out.outer.visit &&
            (!Outer::inside_child || Outer::child.handoff.owner != w ||
             Outer::child.handoff.visit != out.outer.visit || Outer::child.pointer != out.outer.child))
            out.outer.visit = 0;
        if (g.cmd == packet && g.count == draw.index_count && g.sequence &&
            g.pending == p.pending && g.context == p.context) out.gx = g;
        else {
            out.gx.cmd = packet;
            out.gx.pending = p.pending;
            out.gx.context = p.context;
            out.gx.count = p.count;
        }
        out.gx.index_known = false;
        StaticGxBinding(out.gx);
        if (depth && depth <= stack.size()) {
            auto& f = stack[depth - 1];
            if (f.direct && f.owner == w && f.slot && f.fact.draw_target) out.visit = f.fact.id;
        }
        if (!StaticSpan(draw, out.gx, out.index, out.index_bytes)) {
            out.status = SpanStatus::NoStaticSpan;
        } else if (DigestSpan(out.index, out.index_bytes, out.ordered_bytes_fnv)) {
            out.status = SpanStatus::RawIndexBytes;
        } else {
            out.status = SpanStatus::ReadRefused;
        }
    } else {
        if (depth && depth <= stack.size() && stack[depth - 1].direct)
            w->direct_entry_lost.fetch_add(1, std::memory_order_relaxed);
        out.gx.cmd = packet;
        out.status = SpanStatus::UnprovedProducer;
    }
    cell.finished.store(true, std::memory_order_release);
}

// Only the two decoded method bodies use this emitter. No run-time instruction discovery.
class CloneCode {
public:
    explicit CloneCode(u8* code) : code_(code) {}

    bool Build(std::size_t id, u32 start, std::span<const u8> original,
               std::span<const Sites::Instruction> instructions) {
        // Read the one process-owned enable word while leaving the guest state untouched.
        Emit({0x48, 0x8d, 0x64, 0x24, 0x80, 0x9c, 0x50}); // skip red zone, pushfq, push rax
        Emit({0x48, 0xb8});
        Value(reinterpret_cast<u64>(&armed));
        Emit({0x48, 0x83, 0x38, 0x00, 0x0f, 0x84}); // cmp [rax],0; jz fallback
        const auto cold = position_;
        Value(u32(0));
        Restore();

        for (const auto& inst : instructions) {
            const auto offset = inst.at - start;
            if (offset >= labels_.size() || offset + inst.bytes > original.size()) return false;
            labels_[offset] = position_;
            if (inst.op != Sites::Op::Classifier && !Probe(inst.event)) return false;
            const auto native = original.subspan(offset, inst.bytes);
            switch (inst.op) {
            case Sites::Op::Raw: Copy(native); break;
            case Sites::Op::Branch:
                if (branch_count_ >= branches_.size()) return false;
                if (inst.condition == 0xff) Emit({0xe9});
                else Emit({0x0f, u8(0x80 | inst.condition)});
                branches_[branch_count_++] = {position_, inst.target};
                Value(u32(0));
                break;
            case Sites::Op::Rip:
                if (!Rip(native, inst.target)) return false;
                break;
            case Sites::Op::Call:
                if (!WithinImage(image + inst.target, 1)) return false;
                Emit({0xff, 0x15, 0x02, 0, 0, 0, 0xeb, 0x08});
                Value(image + inst.target);
                break;
            case Sites::Op::Classifier:
                // The pinned helper loads the real object and real vtable target, then tail jumps.
                // Load those same operands and observe them before the one call.
                Copy(std::span<const u8>(Sites::kStockClassifier).first(11));
                if (!Probe(inst.event)) return false;
                Emit({0xff, 0xd0});
                break;
            }
        }
        Rel(cold, position_);
        Restore();
        if (id == 0) Copy(original.first(kPrefix[id]));
        else {
            Copy(original.first(13));
            if (!Rip(original.subspan(13, 7), 0x54b0874)) return false;
        }
        Jump(image + start + kPrefix[id]);

        for (std::size_t i = 0; i < branch_count_; ++i) {
            const auto [at, target] = branches_[i];
            if (target < start || target - start >= labels_.size() || !labels_[target - start])
                return false;
            Rel(at, labels_[target - start]);
        }
        return !overflow_;
    }

    std::size_t observers = 0;
    std::array<u8*, 32> pages{};

private:
    void Restore() {
        Emit({0x58, 0x9d, 0x48, 0x8d, 0xa4, 0x24, 0x80, 0, 0, 0}); // pop rax, popfq, lea rsp,[rsp+128]
    }
    void Copy(std::span<const u8> bytes) {
        if (bytes.size() > 4096 - position_) {
            overflow_ = true;
            return;
        }
        std::memcpy(code_ + position_, bytes.data(), bytes.size());
        position_ += bytes.size();
    }
    void Emit(std::initializer_list<u8> bytes) { Copy(bytes); }
    template <typename T> void Value(T value) {
        Copy({reinterpret_cast<const u8*>(&value), sizeof value});
    }
    void Rel(std::size_t at, std::size_t target) {
        if (at > 4096 - sizeof(std::int32_t)) {
            overflow_ = true;
            return;
        }
        const auto delta = static_cast<std::int32_t>(target) -
                           static_cast<std::int32_t>(at + sizeof(std::int32_t));
        std::memcpy(code_ + at, &delta, sizeof delta);
    }
    void Jump(u64 address) {
        Emit({0xff, 0x25, 0, 0, 0, 0});
        Value(address);
    }
    bool Rip(std::span<const u8> raw, u32 target) {
        if (!WithinImage(image + target, sizeof(u64))) return false;
        if (raw[0] == 0x48 && raw[1] == 0x8d && raw[2] == 0x05) {
            Emit({0x48, 0xb8}); // lea rax,[rip+rel] -> movabs rax,target
            Value(image + target);
            return true;
        }
        if (raw[0] == 0x4c && raw[1] == 0x8b && raw[2] == 0x3d) {
            Emit({0x49, 0xbf}); // mov r15,[rip+rel] -> movabs r15,target; mov r15,[r15]
            Value(image + target);
            Emit({0x4d, 0x8b, 0x3f});
            return true;
        }
        return false;
    }
    bool Probe(Event event) {
        if (event == Event::None) return true;
        if (position_ > 4096 - 14 || observers == pages.size()) return false;
        const bool entry = event == Event::EnterA || event == Event::EnterB;
        u8* stub = PreparePassiveObserver(Observe, static_cast<u64>(event),
                                          reinterpret_cast<u64>(code_ + position_ + 14), entry);
        if (!stub) return false;
        pages[observers++] = stub;
        Jump(reinterpret_cast<u64>(stub));
        return true;
    }

    struct Branch { std::size_t at; u32 target; };
    u8* code_;
    std::array<std::size_t, 384> labels_{};
    std::array<Branch, 48> branches_{};
    std::size_t position_ = 0, branch_count_ = 0;
    bool overflow_ = false;
};

inline bool Requested() {
    const char* opt_in = std::getenv("BB_GUEST_PRECULL_COLLECT");
    return opt_in && std::strcmp(opt_in, "1") == 0;
}

inline bool Install(u8* base, std::size_t bytes) {
    if (!Requested()) return false;
    const char* identity = std::getenv("BB_ENGINE_IMAGE_SHA256");
    bool pinned = identity && std::strcmp(identity, kIdentity) == 0 && __builtin_cpu_supports("avx");
    image = reinterpret_cast<u64>(base);
    image_bytes = bytes;
    constexpr u32 starts[] = {Sites::kA, Sites::kB};
    const std::span<const u8> original[] = {Sites::kStockA, Sites::kStockB};
    const std::span<const Sites::Instruction> instructions[] = {Sites::kInstructionsA, Sites::kInstructionsB};
    const auto same = [](u64 at, std::span<const u8> src) {
        return WithinImage(at, src.size()) &&
               Protection(reinterpret_cast<const void*>(at), src.size(), PAGE_READWRITE) &&
               std::memcmp(reinterpret_cast<const void*>(at), src.data(), src.size()) == 0;
    };
    for (std::size_t i = 0; pinned && i < clones.size(); ++i) {
        const u64 slot = image + Sites::kSlots[i];
        pinned = same(image + starts[i], original[i]) && WithinImage(slot, 8) &&
                 WordAt(slot) == image + starts[i];
    }
    for (std::size_t i = 0; pinned && i < std::size(Sites::kGxReturn); ++i) {
        const auto& pin = Sites::kGxCallPins[i];
        pinned = same(image + Sites::kGxReturn[i] - sizeof pin, pin);
    }
    if (!pinned || !PinnedBinding(PAGE_READWRITE) || !same(image + Sites::kClassifier, Sites::kStockClassifier)) {
        std::puts("G108 probe refusal: stock image, AVX support or startup byte/relocation pins");
        return false;
    }

    const bool outer = Outer::Requested();
    if (outer && !Outer::PrepareHooks(base, bytes)) {
        std::puts("G108 outer_probe refusal=patched-sites-or-stock-pins");
        return false;
    }
    std::array<std::array<u8*, 32>, 2> observer_pages{};
    for (std::size_t i = 0; i < clones.size(); ++i) {
        clones[i] = static_cast<u8*>(VirtualAlloc(nullptr, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        CloneCode emitter(clones[i]);
        DWORD before = 0;
        const bool ready = clones[i] && emitter.Build(i, starts[i], original[i], instructions[i]) &&
                           VirtualProtect(clones[i], 4096, PAGE_EXECUTE_READ, &before) &&
                           FlushInstructionCache(GetCurrentProcess(), clones[i], 4096);
        observer_pages[i] = emitter.pages;
        if (!ready) {
            for (auto& set : observer_pages) for (auto* page : set) if (page) FreeStub(page);
            for (auto* page : clones) if (page) VirtualFree(page, 0, MEM_RELEASE);
            if (outer) Outer::FreeHooks();
            std::puts("G108 probe refusal: gated visitor clone could not be prepared");
            return false;
        }
        auto& patch = redirects[i];
        std::fill(patch.begin() + 14, patch.end(), 0xcc);
        patch[0] = 0xff;
        patch[1] = 0x25;
        std::memcpy(patch.data() + 6, &clones[i], sizeof(u64));
    }

    // This entry point runs inside the private image loader, before final RX protection and
    // before entry, module init or any native job. Publish the redirects only after both validate.
    for (std::size_t i = 0; i < clones.size(); ++i)
        std::memcpy(base + starts[i], redirects[i].data(), kPrefix[i]);
    if (!FlushInstructionCache(GetCurrentProcess(), base + starts[0], starts[1] - starts[0] + kPrefix[1]) ||
        std::atexit(FinishProbe) != 0) {
        for (std::size_t i = 0; i < clones.size(); ++i)
            std::memcpy(base + starts[i], original[i].data(), kPrefix[i]);
        FlushInstructionCache(GetCurrentProcess(), base + starts[0], starts[1] - starts[0] + kPrefix[1]);
        for (auto& set : observer_pages) for (auto* page : set) if (page) FreeStub(page);
        for (auto* page : clones) if (page) VirtualFree(page, 0, MEM_RELEASE);
        if (outer) Outer::FreeHooks();
        std::puts("G108 probe refusal: startup redirect could not be committed");
        return false;
    }
    if (outer) {
        Commit(Outer::hooks);
        Outer::enabled = true;
        std::puts("G108 outer_probe installed=1");
    }
    installed.store(true, std::memory_order_relaxed);
    std::puts("G108 probe installed: seed/held windows require matching loaded RX pins");
    return true;
}
} // namespace BbEngine::GuestPrecull
#endif
