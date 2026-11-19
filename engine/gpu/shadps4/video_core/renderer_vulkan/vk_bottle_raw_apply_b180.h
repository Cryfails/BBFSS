// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include <array>
#include <atomic>
#include <bit>
#include <cstdio>
#include <memory>
#include <optional>
#include "video_core/renderer_vulkan/vk_bottle_cold_source_b177.h"

namespace Vulkan::BottleRawApply180 {
namespace Cold = BottleColdSource177;
namespace Source = BottleCaustic::CutSource;

inline constexpr u32 Capacity = 24 * Cold::Capture::MaxOpportunities;
inline constexpr u32 SearchFrames = 64;
static_assert(Cold::Capture::MaxOpportunities == 64);

template <typename Handle>
u64 Word(Handle value) {
    return std::bit_cast<u64>(static_cast<typename Handle::CType>(value));
}

inline unsigned long long N(u64 word) { return static_cast<unsigned long long>(word); }

struct Key {
    Source::SceneKey scene{};
    u32 frame{};
    u64 opportunity{};
    Source::DrawOrder outer{};
    Source::Camera camera{};
    Cold::Image color{}, depth{};
    Source::MasterRead master{};
};

struct Bind {
    Cold::Image parent{};
    vk::Image proxy{};
    vk::ImageView view{};
    vk::ImageLayout layout{};
    u64 incarnation{}, parent_write_hint{};
    bool Known() const {
        return parent && proxy && proxy != parent.handle && view &&
               incarnation && layout == vk::ImageLayout::eGeneral;
    }
};

struct Phase {
    vk::Semaphore timeline{};
    u64 tick{}, captured_rt{}, current_rt{}, targets{};
    Source::Camera camera{};
    Bind color{}, depth{};
    bool strict_scope_queued{};

    bool Joins(const Key& key) const {
        return timeline == key.outer.timeline && tick >= key.outer.tick &&
               captured_rt == key.scene.rt_frame && current_rt == key.scene.rt_frame &&
               targets == key.scene.target_generation && camera.Valid() && camera == key.camera &&
               color.Known() && depth.Known() && color.parent == key.color && depth.parent == key.depth &&
               color.proxy != depth.proxy && color.view != depth.view &&
               color.incarnation != depth.incarnation;
    }
};

struct Topology {
    bool observed{}, tlas{}, corners{};
    u32 ordinal{};
};

inline void Print(const char* event, const char* result, const Key& key,
                  const Phase& phase = {}, vk::CommandBuffer command = {},
                  const char* reason = "none", Topology topology = {}) {
    const auto& k = key.scene;
    const auto& c = phase.color;
    const auto& d = phase.depth;
    const auto& camera = phase.tick ? phase.camera : key.camera;
    const auto& v = camera.view;
    const auto& p = camera.projection;
    const auto& ov = key.camera.view;
    const auto& op = key.camera.projection;
    std::printf("[bottle-raw-apply] event=%s request=%u scene=%llu frame=%u opportunity=%llu outcome=%s "
                "load=%llu targets=%llu rt=%llu object=%llu primary=%llu master=%u epoch=%llu read=%llu "
                "outer_timeline=%llx outer_tick=%llu outer_draw=%llu phase_timeline=%llx phase_tick=%llu "
                "phase_rt=%llu/%llu phase_targets=%llu command=%llx strict_scope_queued=%u "
                "outer_color=%u/%llu/%llx/%llx outer_depth=%u/%llu/%llx/%llx "
                "color=%u/%llu/%llx/%llx/%llx/%llx/%llu/%llu/%u "
                "depth=%u/%llu/%llx/%llx/%llx/%llx/%llu/%llu/%u "
                "view=%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g "
                "projection=%.9g/%.9g/%.9g/%.9g jitter=%.9g/%.9g "
                "outer_view=%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g/%.9g "
                "outer_projection=%.9g/%.9g/%.9g/%.9g outer_jitter=%.9g/%.9g reason=%s topology_seen=%u tlas=%u corners=%u topology_ordinal=%u\n",
                event, k.request, N(k.scene), key.frame, N(key.opportunity), result,
                N(k.load), N(k.target_generation), N(k.rt_frame), N(k.object_frame), N(k.primary_pass),
                unsigned(key.master.on), N(key.master.epoch), N(key.master.read),
                N(Word(key.outer.timeline)), N(key.outer.tick), N(key.outer.draw),
                N(Word(phase.timeline)), N(phase.tick), N(phase.captured_rt), N(phase.current_rt), N(phase.targets),
                N(Word(command)), unsigned(phase.strict_scope_queued),
                key.color.id, N(key.color.uid), N(Word(key.color.handle)), N(reinterpret_cast<u64>(key.color.allocation)),
                key.depth.id, N(key.depth.uid), N(Word(key.depth.handle)), N(reinterpret_cast<u64>(key.depth.allocation)),
                c.parent.id, N(c.parent.uid), N(Word(c.parent.handle)), N(reinterpret_cast<u64>(c.parent.allocation)),
                N(Word(c.proxy)), N(Word(c.view)), N(c.incarnation), N(c.parent_write_hint), u32(c.layout),
                d.parent.id, N(d.parent.uid), N(Word(d.parent.handle)), N(reinterpret_cast<u64>(d.parent.allocation)),
                N(Word(d.proxy)), N(Word(d.view)), N(d.incarnation), N(d.parent_write_hint), u32(d.layout),
                v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],
                p[0],p[1],p[2],p[3],camera.jitter[0],camera.jitter[1],
                ov[0],ov[1],ov[2],ov[3],ov[4],ov[5],ov[6],ov[7],ov[8],ov[9],ov[10],ov[11],
                op[0],op[1],op[2],op[3],key.camera.jitter[0],key.camera.jitter[1], reason, unsigned(topology.observed), unsigned(topology.tlas),
                unsigned(topology.corners), topology.ordinal);
}

class Receipt {
public:
    explicit Receipt(Key key_) : key(key_) {}
    ~Receipt() {
        const auto last = state.load(std::memory_order_acquire);
        if (last == State::Entered) Print("outcome", "returned-before-queue", key, {}, {}, reason ? reason : "unclassified", topology);
        if (last == State::Queued) Print("outcome", "queued-without-phase2", key, phase, {}, "none", topology);
    }

    void Refuse(const char* stage) {
        if (state.load(std::memory_order_relaxed) == State::Entered) reason = stage;
    }

    void ObserveTopology(bool tlas, bool corners, u32 ordinal) {
        topology = {true, tlas, corners, ordinal};
    }

    // The caller invokes this on the producer after the original RecordCrumb returns.
    void Recorded() { recorded = true; }

    void Queue(Phase actual) {
        if (state.load(std::memory_order_relaxed) != State::Entered) return;
        phase = actual;
        Print("queued", "pending", key, phase, {}, "none", topology);
        state.store(State::Queued, std::memory_order_release);
    }

    void Encoded(vk::CommandBuffer command) {
        State pending = State::Queued;
        if (!command || !state.compare_exchange_strong(pending, State::Encoded, std::memory_order_acq_rel))
            return;
        Print("outcome", phase.Joins(key) ? "encoded-joined" : "encoded-unjoined", key, phase, command, "none", topology);
    }

private:
    friend class Budget;
    enum class State : u8 { Entered, Queued, Encoded };
    const Key key;
    Phase phase{};
    const char* reason{};
    Topology topology{};
    bool recorded{};
    std::atomic<State> state{State::Entered};
};

inline Source::MasterRead Effective(const Source::Opportunity& opportunity) {
    using enum Source::Guard::Branch;
    const auto& [branch, read] = opportunity.guard;
    if (branch != NoPassObject) {
        return read && read.on == (branch == MasterOn) ? read : Source::MasterRead{};
    }
    const auto& g = opportunity.gbuffer;
    const auto& o = opportunity.order;
    const auto& latest = opportunity.latest;
    if (read || !g.master || g.master.on || g.scene != opportunity.scene || !g.order ||
        g.order.timeline != o.timeline || g.order.tick > o.tick || g.order.draw >= o.draw ||
        !latest || latest.on || latest.epoch != g.master.epoch || latest.read < g.master.read) return {};
    return g.master;
}

enum class Mode : u8 { Disarmed, Cut, AllOff };
struct Selection {
    u32 request{};
    Mode mode{Mode::Disarmed};
    explicit operator bool() const { return request && (mode == Mode::Cut || mode == Mode::AllOff); }
    bool operator==(const Selection&) const = default;
};

// The existing R780 parser is the sole source of the requested mode.
Selection Selected(u32 request);

enum class Decision : u8 { Awaiting, Ready, NoWork, ScopeUnknown, QueueUnjoined, Overflow };
struct Readiness {
    Decision decision{};
    u64 first_frame{}, deadline{}, opportunity{}, phase_tick{};
    u32 expected{}, seen{}, recorded{}, topology_ordinal{};
};

class Budget {
public:
    void Open(Selection selection, const Cold::Frame& frame, const Source::SceneKey& first, u64 last) {
        if (window || !Matches(selection, frame, first) || first.scene > last) return;
        selected = selection;
        owner = frame.owner;
        window = Window{first.scene, last, frame.load, frame.targets, frame.timeline};
        ledger.reset();
    }

    std::shared_ptr<Receipt> Begin(Selection selection, const Source::Opportunity& opportunity,
                                   const Cold::Frame& frame, Cold::Image color, Cold::Image depth) {
        const auto& s = opportunity.scene;
        if (!Matches(selection, frame, s) || !opportunity.camera.Valid() ||
            !opportunity.sequence || !opportunity.order || opportunity.order.timeline != frame.timeline ||
            opportunity.sequence > Cold::Capture::MaxOpportunities || !color.Distinct(depth)) return {};

        const auto master = Effective(opportunity);
        if (window) {
            if (s.scene < window->first || s.scene > window->last || frame.load != window->load ||
                frame.targets != window->targets || frame.timeline != window->timeline) return {};
        } else if (!master || (selection.mode == Mode::Cut) != master.on) {
            // Cold cut startup and unproved reads cannot spend the active receipt budget.
            return {};
        }
        if (selection.mode == Mode::AllOff && master && master.on) return {};
        if (!window && selection.mode == Mode::Cut) {
            if (!search) search = Search{frame.draw_frame, u64{frame.draw_frame} + SearchFrames - 1,
                                         frame.load, frame.targets, master.epoch, frame.timeline};
            if (!search->Owns(frame, master.epoch) || frame.draw_frame > search->deadline) return {};
            if (!ledger) ledger = std::make_unique<Ledger>();
            if (ledger->frame != frame) {
                ledger->frame = frame;
                ledger->scene = s;
                ledger->seen = ledger->returned = ledger->recorded = 0;
                ledger->duplicate = false;
            }
        }
        selected = selection;
        owner = frame.owner;
        if (count >= Capacity) {
            if (count == Capacity) {
                ++count;
                std::printf("[bottle-raw-apply] event=overflow request=%u scene=%llu frame=%u limit=%u\n",
                            s.request, N(s.scene), frame.draw_frame, Capacity);
            }
            return {};
        }
        ++count;
        const Key key{s, frame.draw_frame, opportunity.sequence, opportunity.order,
                      opportunity.camera, color, depth, master};
        if (!master) {
            Print("outcome", "master-unknown", key);
            return {};
        }
        if (!master.on) {
            Print("outcome", opportunity.guard.branch == Source::Guard::Branch::NoPassObject
                             ? "off-cold-null" : "off-master", key);
            return {};
        }
        return std::make_shared<Receipt>(key);
    }

    void Finish(const Receipt& receipt) {
        const auto& key = receipt.key;
        if (window || !search || !ledger || ledger->frame.draw_frame != key.frame ||
            ledger->scene != key.scene || !search->Owns(ledger->frame, key.master.epoch)) return;
        const u64 bit = u64{1} << (key.opportunity - 1);
        if (ledger->seen & bit) {
            ledger->duplicate = true;
            return;
        }
        ledger->seen |= bit;
        if (!receipt.recorded) {
            if (receipt.reason && receipt.state.load(std::memory_order_acquire) == Receipt::State::Entered)
                ledger->returned |= bit;
            return;
        }
        ledger->recorded |= bit;
        const auto& phase = receipt.phase;
        ledger->queue[key.opportunity - 1] = {
            phase.color, phase.depth, phase.camera, phase.tick, receipt.topology.ordinal,
            phase.Joins(key) && receipt.topology.observed && receipt.topology.tlas && receipt.topology.corners};
    }

    void StopSeeking() { ledger.reset(); }

    Readiness Probe(u32 frame, const Cold::Closed* closed) const {
        if (!search || frame < search->first) return {};
        const bool last = frame >= search->deadline;
        Readiness result{Decision::Awaiting, search->first, search->deadline};
        if (count > Capacity) {
            result.decision = Decision::Overflow;
            return result;
        }
        if (last) result.decision = Decision::ScopeUnknown;
        if (frame > search->deadline || !closed || !ledger || closed->frame.draw_frame != frame ||
            ledger->frame != closed->frame || ledger->scene != closed->source.key || ledger->duplicate ||
            !search->Owns(closed->frame, closed->first_epoch) || closed->last_epoch != closed->first_epoch ||
            !closed->camera || !closed->camera->Valid() || !closed->ordinary_read ||
            !closed->color.Distinct(closed->depth) || closed->raw_state != Cold::State::On ||
            !closed->source.closed || !closed->source.last_order ||
            closed->source.last_order.timeline != closed->frame.timeline || closed->raw_refusal) return result;
        const u64 count = closed->source.last_sequence;
        if (!count || count > Cold::Capture::MaxOpportunities) return result;
        result.expected = u32(count);
        result.seen = std::popcount(ledger->seen);
        result.recorded = std::popcount(ledger->recorded);
        const u64 mask = ~u64{} >> (Cold::Capture::MaxOpportunities - count);
        if (ledger->seen != mask || (ledger->returned | ledger->recorded) != mask) return result;
        const auto& read = *closed->ordinary_read;
        if (read.opportunity != count || closed->source.last_order.tick > read.tick) return result;
        if (last) result.decision = ledger->recorded ? Decision::QueueUnjoined : Decision::NoWork;
        for (u64 bits = ledger->recorded; bits; bits &= bits - 1) {
            const auto index = std::countr_zero(bits);
            const auto& actual = ledger->queue[index];
            if (!actual.joined || actual.camera != *closed->camera || actual.tick > read.tick ||
                !actual.Matches(closed->color, read.color, closed->depth, read.depth)) continue;
            result.decision = Decision::Ready;
            result.opportunity = index + 1;
            result.phase_tick = actual.tick;
            result.topology_ordinal = actual.ordinal;
            break;
        }
        return result;
    }

private:
    struct Search {
        u64 first{}, deadline{}, load{}, targets{}, epoch{};
        vk::Semaphore timeline{};
        bool Owns(const Cold::Frame& frame, u64 actual_epoch) const {
            return frame.load == load && frame.targets == targets && frame.timeline == timeline &&
                   actual_epoch == epoch;
        }
    };

    struct Queued {
        Bind color{}, depth{};
        Source::Camera camera{};
        u64 tick{};
        u32 ordinal{};
        bool joined{};

        bool Matches(const Cold::Image& current_color, const Cold::OrdinaryView& read_color,
                     const Cold::Image& current_depth, const Cold::OrdinaryView& read_depth) const {
            const auto same = [](const Bind& phase, const Cold::Image& parent,
                                 const Cold::OrdinaryView& read) {
                return phase.parent == parent && phase.proxy == read.image && phase.view == read.view &&
                       phase.incarnation == read.incarnation;
            };
            return same(color, current_color, read_color) && same(depth, current_depth, read_depth);
        }
    };
    struct Ledger {
        Cold::Frame frame{};
        Source::SceneKey scene{};
        u64 seen{}, returned{}, recorded{};
        bool duplicate{};
        std::array<Queued, Cold::Capture::MaxOpportunities> queue{};
    };

    static_assert(sizeof(Ledger) <= 15 * 1024);

    struct Window {
        u64 first{}, last{}, load{}, targets{};
        vk::Semaphore timeline{};
    };

    bool Matches(Selection selection, const Cold::Frame& frame, const Source::SceneKey& scene) const {
        return selection && (!selected || selected == selection) && (!owner || owner == frame.owner) &&
               frame && frame.draw_frame && scene && selection.request == frame.request &&
               scene.request == frame.request && scene.load == frame.load &&
               scene.target_generation == frame.targets && scene.rt_frame == frame.rt_frame &&
               scene.object_frame == frame.object_frame;
    }

    Selection selected{};
    const void* owner{};
    std::optional<Window> window;
    std::optional<Search> search;
    std::unique_ptr<Ledger> ledger;
    u32 count{};
};

inline Budget& CurrentBudget() {
    static thread_local Budget budget;
    return budget;
}
} // namespace Vulkan::BottleRawApply180
#endif
