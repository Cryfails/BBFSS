// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_precull_outer_sites.h"

namespace BbEngine::GuestPrecull::Outer {
enum Part : u64 { TargetEntry = 1, ChildBefore, ChildAfter, TargetExit, ModelSelected, ReplayEntry };
inline constexpr u32 kChildCall = 0x1d2157a, kModelReturn = 0x21d0f8d, kReplayReturn = 0x26ab705;
inline constexpr u32 kModelRange = 0x21d0f2b;

inline std::array<Hook, 5> hooks{};
inline bool enabled = false;
inline u8* child_return = nullptr;

struct Handoff {
    Window* owner = nullptr;
    u64 visit = 0, parent = 0, context = 0, caller = 0, slot = 0;
    Bounds bounds{};
};
struct Child {
    Handoff handoff{};
    u64 pointer = 0, target = 0, slot = 0;
};
struct Range {
    Window* owner = nullptr;
    u64 frame = 0, stack_at_call = 0, selected = 0, base_record = 0, model_arg = 0, instance_arg = 0;
    u32 count = 0, base_first = 0, local_first = 0;
};
struct Replay {
    Window* owner = nullptr;
    u64 frame = 0, stack_at_call = 0, record = 0, ctx = 0, pending = 0;
    std::array<u32, 4> words{};
};

inline thread_local Handoff tail, target;
inline thread_local Child child;
inline thread_local Range selection;
inline thread_local Replay replay;
inline thread_local bool inside_child = false;

inline u64 GuestStack(const u64* saved, bool entry) {
    return reinterpret_cast<u64>(saved + kPassiveStack + (entry ? 1 : 0));
}
inline bool BCaller(u64 ret) {
    return std::any_of(std::begin(OuterSites::kBReturns), std::end(OuterSites::kBReturns),
                       [ret](u32 rva) { return ret == image + rva; });
}

inline void EnterVisitor() {
    if (!enabled) return;
    tail = {};
    target = {};
    child = {};
    // If re-entered while the child call is on the stack, keep that conflict
    // latched until that native call returns. Another visit cannot inherit it.
}

inline void RememberBounds(Frame& f, u64 classifier) {
    if (!enabled || f.fact.path != 2 || !f.fact.candidate_vtable ||
        f.fact.candidate > std::numeric_limits<u64>::max() - 0x40 ||
        f.fact.operand != f.fact.candidate + 0x40 ||
        WordAt(f.fact.candidate_vtable + 0x28) != image + OuterSites::kBoundsAccessor ||
        (classifier != image + OuterSites::kBoundsA && classifier != image + OuterSites::kBoundsB)) return;
    // Copy the actual vector arguments before the one native classifier call.
    // There is no declared coordinate basis or conservative world bound here.
    std::array<u32, 8> words{};
    if (!Peek(f.fact.operand, words.data(), sizeof words)) return;
    f.bounds = {.operand = f.fact.operand, .classifier = classifier,
                .words = {words[0], words[1], words[2], words[4], words[5], words[6]}, .valid = true};
}
inline void Tail(Frame& f, u64 frame_pointer) {
    if (!enabled || inside_child || !f.return_slot || !f.fact.candidate || !f.fact.context ||
        f.owner != armed.load(std::memory_order_acquire) || f.fact.draw_target != image + OuterSites::kTarget ||
        !BCaller(f.fact.caller) || frame_pointer != f.return_slot - 8 || WordAt(f.return_slot) != f.fact.caller)
        return;
    tail = {.owner = f.owner, .visit = f.fact.id, .parent = f.fact.candidate,
            .context = f.fact.context, .caller = f.fact.caller, .slot = f.return_slot, .bounds = f.bounds};
}

inline void BeginTarget(Window* w, const u64* saved) {
    const Handoff offered = tail;
    tail = {};
    target = {};
    child = {};
    const u64 sp = GuestStack(saved, true);
    if (!inside_child && w && w == offered.owner && offered.slot == sp && saved[kPassiveStack + 1] == offered.caller &&
        saved[5] == offered.parent && saved[4] == offered.context) target = offered;
}

inline void BeginChild(Window* w, const u64* saved) {
    child = {};
    const bool already = inside_child;
    inside_child = true;
    if (already || !w || w != target.owner || !saved[5] ||
        saved[3] != target.parent || saved[4] != target.context || saved[kSavedRbp] != target.slot - 8 ||
        WordAt(target.slot) != target.caller) return;
    const u64 sp = GuestStack(saved, false);
    if (sp < sizeof(u64) || !child_return) return;
    const u64 child_target = WordAt(saved[kPassiveRax] + 0x60);
    if (!WithinImage(child_target, 1) ||
        !Protection(reinterpret_cast<const void*>(child_target), 1, PAGE_EXECUTE_READ)) return;
    child = {.handoff = target, .pointer = saved[5], .target = child_target, .slot = sp - sizeof(u64)};
}

inline void CaptureModel(Window* w, const u64* saved) {
    selection = {};
    const u64 bp = saved[kSavedRbp], sp = GuestStack(saved, false);
    const u64 main = saved[0], offset = saved[5];
    if (!w || bp < 0x110 || sp != bp - 0x110 || main > std::numeric_limits<u64>::max() - offset) return;
    const u64 selected = main + offset;
    if (!selected || selected > std::numeric_limits<u64>::max() - 0x20 ||
        saved[kPassiveRax] != selected + 0x18) return;
    struct Part { u32 count, local_first; u64 record; } part{};
    if (!Peek(selected + 0x10, &part, sizeof part) || !part.record ||
        (part.count != 18282 && part.count != 42441)) return;
    u32 base_first = 0;
    if (!Peek(part.record + 8, &base_first, sizeof base_first) ||
        part.local_first > std::numeric_limits<u32>::max() - base_first) return;
    selection = {.owner = w, .frame = bp, .stack_at_call = sp, .selected = selected,
                 .base_record = part.record, .model_arg = WordAt(bp - 0x80),
                 .instance_arg = WordAt(bp - 0x90), .count = part.count, .base_first = base_first,
                 .local_first = part.local_first};
}

inline void CaptureReplay(Window* w, const u64* saved) {
    replay = {};
    const u64 sp = GuestStack(saved, true);
    std::array<u32, 4> words{};
    if (!w || sp < 16 || !saved[3] || !Peek(saved[3], words.data(), sizeof words) ||
        (words[1] != 18282 && words[1] != 42441)) return;
    replay = {.owner = w, .frame = sp - 8, .stack_at_call = sp - 8,
              .record = saved[3], .ctx = saved[5], .pending = saved[4], .words = words};
}

inline std::int64_t __attribute__((sysv_abi)) Observe(u64 event, const u64* saved) {
    Window* w = armed.load(std::memory_order_acquire);
    switch (event) {
    case TargetEntry: BeginTarget(w, saved); break;
    case ChildBefore: BeginChild(w, saved); break;
    case ChildAfter: inside_child = false; child = {}; break;
    case TargetExit: target = {}; child = {}; break;
    case ModelSelected: CaptureModel(w, saved); break;
    case ReplayEntry: CaptureReplay(w, saved); break;
    default: break;
    }
    return 0;
}

inline const char* Role(u32 count, u32 first) {
    if (count == 18282 && first == 158744) return "fireplace";
    if (count == 42441 && first == 12368) return "wall";
    return nullptr;
}

inline ProducerOwner GxEntry(Window* w, const u64* saved, u32 id, u32 first, u32 count, bool passive) {
    ProducerOwner out{};
    if (!enabled || !passive || !w) return out;
    const auto selected = selection;
    const auto record = replay;
    // The only exact supported returns both lead to plain DrawIndexed; consume
    // once even on mismatch so a recycled address cannot revive a stale ticket.
    const u64 return_pc = saved[kPassiveStack + 1];
    if (return_pc == image + kModelReturn) selection = {};
    if (return_pc == image + kReplayReturn) replay = {};
    if (!Role(count, first)) return out;
    out.entry = true;
    if (WithinImage(return_pc, 1)) out.gx_caller = return_pc - image;
    const u64 frame = saved[kSavedRbp], sp = GuestStack(saved, true);
    const u32 base_vertex = static_cast<u32>(saved[1]);
    out.base_vertex = base_vertex;
    if (return_pc == image + kModelReturn && id == 0) {
        out.route = ProducerRoute::Model;
        if (selected.owner != w || selected.frame != frame || selected.stack_at_call != sp + 8 ||
            selected.count != count || selected.base_first + selected.local_first != first ||
            saved[5] > std::numeric_limits<u64>::max() - 0xb730 || saved[4] != saved[5] + 0xb730) return out;
        out.selected = selected.selected;
        out.base_record = selected.base_record;
        out.model_arg = selected.model_arg;
        out.instance_arg = selected.instance_arg;
        out.range_count = selected.count;
        out.base_first = selected.base_first;
        out.local_first = selected.local_first;
        const Handoff& live = child.handoff;
        if (!inside_child || live.owner != w || !child.pointer || !child_return ||
            sp >= child.slot || child.slot >= live.slot ||
            WordAt(child.slot) != reinterpret_cast<u64>(child_return) ||
            WordAt(live.slot) != live.caller) return out;
        out.visit = live.visit;
        out.parent = live.parent;
        out.child = child.pointer;
        out.child_target = child.target - image;
        out.context = live.context;
        out.b_caller = live.caller - image;
        out.b_slot = live.slot;
        out.child_slot = child.slot;
        out.bounds = live.bounds;
    } else if (return_pc == image + kReplayReturn && id == 0) {
        out.route = ProducerRoute::Replay;
        if (record.owner != w || record.frame != frame || record.stack_at_call != sp + 8 ||
            record.ctx != saved[5] || record.pending != saved[4] ||
            record.words[1] != count || record.words[2] != first || record.words[3] != base_vertex) return out;
        out.replay_record = record.record;
        out.replay_words = record.words;
    }
    return out;
}

inline bool ExactSpan(const GxFact& f) {
    if (f.status != SpanStatus::RawIndexBytes || f.gx.topology != 4 || f.gx.index_format > 1 ||
        f.index_bytes != f.count * (f.gx.index_format == 0 ? 2u : 4u)) return false;
    if (f.count == 18282) {
        return f.ordered_bytes_fnv == (f.gx.index_format == 0 ? 0xe68b31865bd80afaull : 0xd74a7a797f4f927aull);
    }
    return f.ordered_bytes_fnv == (f.gx.index_format == 0 ? 0x3580f61d9eb9d961ull : 0xb66ddbf375040319ull);
}

inline void Dump(const Window& w, const GxFact& f) {
    const char* role = Role(f.count, f.first);
    if (!enabled || !role || !f.issue) return;
    const auto& o = f.outer;
    const bool exact = ExactSpan(f);
    const bool live = exact && o.visit;
    const auto route = o.route == ProducerRoute::Model ? "model" :
                       o.route == ProducerRoute::Replay ? "replay" : "foreign";
    const auto& bounds = live ? o.bounds : Bounds{};
    const auto& b = bounds.words;
    const char* refusal = !o.entry ? "entry-abi" : !exact ? "index-identity" :
                          o.route == ProducerRoute::Replay ? (o.replay_record ? "deferred-writer" : "replay-input") :
                          o.route == ProducerRoute::Model ? (!o.selected ? "selected-range" :
                                                             !live ? "B-lineage" : "none") : "foreign-caller";
    std::printf("G108 outer window=%u issue=%llu worker=%u role=%s gx_caller=%llx route=%s "
                "owner=%s continuation=%s refusal=%s span_exact=%u first=%u count=%u fnv=%llx "
                "packet=%llx gx_context=%llx pending=%llx "
                "selected=%llx base_record=%llx index_count=%u index_base_first=%u index_local_first=%u "
                "model_arg=%llx instance_arg=%llx base_vertex=%u replay_record=%llx "
                "replay_w0=%08x replay_w1=%08x replay_w2=%08x replay_w3=%08x "
                "visit=%llu parent=%llx child=%llx child_target=%llx child_site=%x context=%llx b_caller=%llx b_slot=%llx child_slot=%llx "
                "aabb=%u aabb_operand=%llx classifier=%llx min_x=%08x min_y=%08x min_z=%08x max_x=%08x max_y=%08x max_z=%08x\n",
                u32(w.id), Hex(f.issue), f.worker, role, Hex(o.gx_caller), route,
                live ? "b-child-live" : "unknown", live ? "live" : "none", refusal, unsigned(exact),
                f.first, f.count, Hex(f.ordered_bytes_fnv), Hex(f.gx.cmd), Hex(f.gx.context), Hex(f.gx.pending),
                Hex(o.selected), Hex(o.base_record), o.range_count,
                o.base_first, o.local_first, Hex(o.model_arg), Hex(o.instance_arg), o.base_vertex,
                Hex(o.replay_record), o.replay_words[0], o.replay_words[1], o.replay_words[2], o.replay_words[3],
                Hex(live ? o.visit : 0), Hex(live ? o.parent : 0), Hex(live ? o.child : 0), Hex(live ? o.child_target : 0),
                live ? kChildCall : 0, Hex(live ? o.context : 0), Hex(live ? o.b_caller : 0), Hex(live ? o.b_slot : 0), Hex(live ? o.child_slot : 0),
                unsigned(bounds.valid), Hex(bounds.operand), Hex(bounds.classifier),
                b[0], b[1], b[2], b[3], b[4], b[5]);
}

struct Site { u32 at; std::span<const u8> bytes; };
inline const auto target_stock = std::span<const u8>(OuterSites::kStockTarget);
inline const auto model_stock = std::span<const u8>(OuterSites::kStockModelTail);
inline const auto replay_stock = std::span<const u8>(OuterSites::kStockReplay);
inline const Site patched[] = {
    {OuterSites::kTarget, target_stock.first(16)},
    {0x1d21571, target_stock.subspan(0x1d21571 - OuterSites::kTarget, 19)},
    {0x1d21589, target_stock.subspan(0x1d21589 - OuterSites::kTarget)},
    {kModelRange, model_stock.subspan(kModelRange - OuterSites::kModelTail, 16)},
    {OuterSites::kReplay, replay_stock.first(16)}
};

inline bool Pinned(bool installed) {
    const auto full = [installed](u32 at, std::span<const u8> expected) {
        const auto* code = reinterpret_cast<const u8*>(image + at);
        if (!WithinImage(image + at, expected.size()) ||
            !Protection(code, expected.size(), installed ? PAGE_EXECUTE_READ : PAGE_READWRITE)) return false;
        std::size_t offset = 0;
        for (std::size_t i = 0; installed && i < std::size(patched); ++i) {
            const auto& p = patched[i];
            if (p.at < at || p.at - at >= expected.size()) continue;
            const std::size_t pos = p.at - at;
            if (pos < offset || p.bytes.size() > expected.size() - pos ||
                std::memcmp(code + offset, expected.data() + offset, pos - offset)) return false;
            u8 jump[14] = {0xff, 0x25};
            const u64 dst = reinterpret_cast<u64>(hooks[i].stub);
            std::memcpy(jump + 6, &dst, sizeof dst);
            if (!dst || !Protection(hooks[i].stub, 1, PAGE_EXECUTE_READ) ||
                std::memcmp(code + pos, jump, sizeof jump)) return false;
            offset = pos + p.bytes.size();
            for (std::size_t j = pos + sizeof jump; j < offset; ++j) if (code[j] != 0xcc) return false;
        }
        return std::memcmp(code + offset, expected.data() + offset, expected.size() - offset) == 0;
    };
    using namespace OuterSites;
    for (std::size_t i = 0; i < std::size(kBReturns); ++i)
        if (!full(kBReturns[i] - sizeof kBCalls[i], kBCalls[i])) return false;
    return full(kTarget, kStockTarget) && full(kModelEntry, kStockModelEntry) &&
           full(kModelTail, kStockModelTail) && full(kReplay, kStockReplay) &&
           full(kBoundsAccessor, kStockBoundsAccessor) && full(kBoundsA, kStockBoundsA) &&
           full(kBoundsB, kStockBoundsB) && full(kBoundsMaskA, kStockBoundsMaskA) &&
           full(kBoundsMaskB, kStockBoundsMaskB) && WithinImage(image + kReplaySlot, 8) &&
           WordAt(image + kReplaySlot) == image + kReplay;
}

inline bool Requested() {
    const char* value = std::getenv("BB_GUEST_PRECULL_OUTER");
    return value && std::strcmp(value, "1") == 0;
}
inline void FreeHooks() {
    for (auto& h : hooks) Discard(h);
    child_return = nullptr;
}
inline bool PrepareHooks(u8* base, std::size_t bytes) {
    if (!Pinned(false)) return false;
    const u64 gate = reinterpret_cast<u64>(&armed);
    const auto entry = [&](std::size_t i, Part event) {
        const auto& p = patched[i];
        return PrepareGatedEntryObserver(hooks[i], base, bytes, p.at, p.bytes, Observe, event, gate);
    };
    const auto body = [&](std::size_t i, Part event, std::size_t first, u64 end = 0, std::size_t last = 0) {
        const auto& p = patched[i];
        return PrepareGatedBodyObserver(hooks[i], base, bytes, p.at, p.bytes, Observe, gate, event, first,
                                       end, last, end ? &child_return : nullptr);
    };
    if (entry(0, TargetEntry) && body(1, ChildBefore, 9, ChildAfter, 12) &&
        body(2, TargetExit, 0) && body(3, ModelSelected, 0) && entry(4, ReplayEntry)) return true;
    FreeHooks();
    return false;
}
}
