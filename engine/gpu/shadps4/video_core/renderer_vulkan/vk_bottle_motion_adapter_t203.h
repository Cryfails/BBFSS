// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <atomic>
#include <bit>
#include <cstdlib>
#include <mutex>
#include <thread>

#include "bbport_live_knobs.h"
#include "vk_bottle_ancestry_t203.h"
#include "vk_bottle_motion_schedule_t203.h"
#include "vk_common.h"
#include "video_core/texture_cache/image.h"

namespace Vulkan::BottleMotion203 {

namespace Graph = BottleAncestry;
namespace Setup = BottleMotionSetup;
using Graph::Proof;

inline unsigned long long P(u64 x) { return static_cast<unsigned long long>(x); }

template <typename T>
u64 Id(T value) {
    return std::bit_cast<u64>(static_cast<typename T::CType>(value));
}

inline u16 Run() {
    static const u16 run = [] {
        const char* value = std::getenv("BB_BOTTLE_MOTION_T203");
        u16 parsed = 0;
        if (!value || !Setup::Decimal(value, parsed) || !parsed) {
            return u16{0};
        }
        if (std::getenv("BB_BOTTLE_MOTION_T198")) {
            std::printf("[bottle-motion-t203] event=setup-conflict run=%u\n", unsigned(parsed));
            return u16{0};
        }
        return parsed;
    }();
    return run;
}

inline Graph::Format Format(vk::Format format) {
    switch (format) {
    case vk::Format::eUndefined: return Graph::Format::Unknown;
    case vk::Format::eR16G16B16A16Sfloat: return Graph::Format::Rgba16Float;
    case vk::Format::eR8G8B8A8Unorm: return Graph::Format::Rgba8Unorm;
    default: return Graph::Format::Other;
    }
}

// Transfers supply their own view namespace. Keep an observed range separate from any VkImageView.
inline u64 Transfer(vk::Image image) {
    return Id(image) ^ (u64{1} << 63);
}

struct Native {
    u64 generation{}, color_uid{}, depth_uid{}, timeline{}, tick{};
    u32 color_id{}, depth_id{}, width{}, height{}, ordinal{};
    vk::Image color{}, depth{};
    vk::ImageView color_view{}, depth_view{};
    std::array<float, 12> view{};
    std::array<float, 4> projection{};
    std::array<float, 2> jitter{};
    bool ordinary{};
};

struct Ticket {
    u64 scene{}, ready_from{}, issued_ns{}, address{};
    vk::Semaphore timeline{};
    vk::Image image{};
    vk::Format format{};
    std::thread::id writer{};
    Graph::ImageVersion version{};

    explicit operator bool() const { return scene != 0; }
};

struct Slot {
    vk::ImageView view{};
    u32 binding{};
    vk::DescriptorType type{};
    bool exact{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    vk::DescriptorSet handle{};
    vk::Sampler sampler{};
    vk::ImageLayout layout{};
    Graph::BindStage stage{};
    u32 set{}, element{};
    u64 bind_generation{};
#endif
};

struct Slots {
    std::array<Slot, Graph::MaxInputs> images{};
    std::size_t count{}, omitted{};
    void Add(Slot slot) {
        if (count == images.size()) {
            ++omitted;
        } else {
            images[count++] = slot;
        }
    }
};

inline Slots CopySlots(std::span<const vk::WriteDescriptorSet> writes) {
    Slots snapshot{};
    for (const auto& write : writes) {
        switch (write.descriptorType) {
        case vk::DescriptorType::eSampledImage:
        case vk::DescriptorType::eStorageImage:
        case vk::DescriptorType::eCombinedImageSampler:
            snapshot.Add({write.pImageInfo && write.descriptorCount ? write.pImageInfo->imageView :
                                                                    vk::ImageView{},
                          write.dstBinding, write.descriptorType,
                          write.dstArrayElement == 0 && write.descriptorCount == 1});
            if (write.descriptorCount > 1) {
                snapshot.omitted += write.descriptorCount - 1;
            }
            break;
        default: break;
        }
    }
    return snapshot;
}

#ifdef BB_TEST_SHARED_POST_GRAPH
struct EffectiveBind {
    Graph::BindStage stage{};
    u32 set{};
    u64 generation{};
    Proof actual{}; // Includes resolved deferred and cached/reused bindings.
};

inline Slots CopySlots(std::span<const vk::WriteDescriptorSet> writes, EffectiveBind bind) {
    Slots snapshot{};
    for (const auto& write : writes) {
        const auto type = write.descriptorType;
        if (type != vk::DescriptorType::eSampledImage && type != vk::DescriptorType::eStorageImage &&
            type != vk::DescriptorType::eCombinedImageSampler) continue;
        const auto accepted = std::min<std::size_t>(write.descriptorCount, snapshot.images.size() - snapshot.count);
        snapshot.omitted += write.descriptorCount - accepted;
        for (std::size_t i = 0; i < accepted; ++i) {
            const auto info = write.pImageInfo ? write.pImageInfo[i] : vk::DescriptorImageInfo{};
            const auto element = u64(write.dstArrayElement) + i;
            snapshot.Add({
                .view = info.imageView, .binding = write.dstBinding, .type = type,
                .exact = bind.actual == Proof::Known && bind.generation && info.imageView &&
                    bind.stage != Graph::BindStage::Unknown && info.imageLayout != vk::ImageLayout::eUndefined &&
                    element <= UINT32_MAX &&
                    (type != vk::DescriptorType::eCombinedImageSampler || bool(info.sampler)),
                .handle = write.dstSet, .sampler = info.sampler, .layout = info.imageLayout,
                .stage = bind.stage, .set = bind.set, .element = u32(element), .bind_generation = bind.generation,
            });
        }
    }
    return snapshot;
}

struct EffectiveProgram {
    u32 shader{};
    u64 permutation{}, pipeline{}, fingerprint{};
    Proof resolved{}, rgb_recipe{};
    // A 5c02eaf8 route without a witnessed exact effective variant (including Froyok) is pending.
    u64 admitted_variant{};
    Proof substitution{};
    u32 variant_required{}, variant_base{};
};

struct Reader {
    Graph::ImageVersion image{};
    u64 bind_generation{}, writer_view{};
    u32 set{}, binding{}, element{};
    vk::ImageLayout layout{};
    vk::Sampler sampler{};
    vk::DescriptorSet handle{};
    Graph::BindStage stage{};
    Graph::Role role{};
    Proof owner{}, sampler_state{}; // Includes a separately bound actual sampler when applicable.
    Graph::Coverage read{}, contribution{};
    bool external{};
};

inline Graph::Input EffectiveInput(const Slot& slot, std::span<const Reader> readers) {
    Graph::Input result{};
    result.stage = slot.stage;
    result.set = u8(std::min(slot.set, 255u));
    result.binding = u8(std::min(slot.binding, 255u));
    result.element = slot.element;
    const Reader* found = nullptr;
    for (const auto& reader : readers) {
        if (reader.stage != slot.stage || reader.set != slot.set || reader.binding != slot.binding ||
            reader.element != slot.element) continue;
        if (found) {
            result.access = Proof::Failed;
            return result;
        }
        found = &reader;
    }
    if (!found) return result;
    const auto& proof = *found;
    result.image = proof.image;
    result.role = proof.role;
    result.external = proof.external;
    result.read = proof.read;
    result.contribution = proof.contribution;
    result.sampler = proof.sampler_state;
    if (!slot.exact || slot.set > 255 || slot.binding > 255 || !proof.image.Valid()) return result;
    const bool matched = proof.bind_generation == slot.bind_generation && proof.layout == slot.layout &&
        proof.image.view == Id(slot.view) && proof.handle == slot.handle &&
        (slot.type != vk::DescriptorType::eCombinedImageSampler || proof.sampler == slot.sampler);
    result.access = matched ? proof.owner : Proof::Failed;
    result.writer_view = matched ? proof.writer_view : 0;
    return result;
}

inline void Classify(EffectiveProgram program, Graph::Event& event) {
    using namespace Graph;
    event.shader = program.shader;
    event.permutation = program.permutation;
    event.recipe = All(program.resolved, program.rgb_recipe);
    if (!program.pipeline || !program.fingerprint || !program.permutation)
        event.recipe = All(event.recipe, Proof::Unknown);
    if (program.shader == 0x5c02eaf8) {
        event.step = PostStep::Composite;
        event.recipe = All(event.recipe, program.substitution);
        if (!program.admitted_variant || !program.variant_required || !program.variant_base)
            event.recipe = All(event.recipe, Proof::Unknown);
        else if (program.admitted_variant != program.permutation ||
                 (program.variant_base & program.variant_required) != program.variant_base)
            event.recipe = Proof::Failed;
        event.required_slots = program.variant_required;
        return;
    }
    if (!FindCacheContract(program.shader)) {
        // A foreign raster write can be retained without classifying its colour operation.
        if (event.step != PostStep::Carry) event.step = PostStep::Unknown;
        return;
    }
    switch (program.shader) {
    case 0xccbf44a6: event.step = PostStep::Clamp; break;
    case 0x5e67d866: case 0xccb08339: event.step = PostStep::Composite; break;
    case 0xed4c7668: event.step = PostStep::Grade; break;
    case 0x8c08444c: event.step = PostStep::Glow; break;
    default: event.step = PostStep::Unknown; break;
    }
}

inline bool RecordEffective(Graph::SceneTrace& trace, Graph::Event event, EffectiveProgram program,
                            const Slots& slots, std::span<const Reader> readers,
                            const Graph::Input* prior = nullptr) {
    Classify(program, event);
    std::array<Graph::Input, Graph::MaxInputs> inputs{};
    const auto count = std::min(slots.count, inputs.size());
    for (std::size_t i = 0; i < count; ++i) {
        const auto& slot = slots.images[i];
        auto& input = inputs[i];
        input = EffectiveInput(slot, readers);
        if (slot.type == vk::DescriptorType::eStorageImage && (Graph::FindCacheContract(program.shader) ||
            program.shader == 0x5c02eaf8) && slot.stage == Graph::BindStage::Fragment) {
            input.access = Proof::Failed;
        }
        if (program.shader == 0x5c02eaf8 && program.variant_base && slot.stage == Graph::BindStage::Fragment &&
            !slot.set && !slot.element && slot.binding < 32 &&
            (program.variant_required & (u32{1} << slot.binding))) {
            const bool expected_base = program.variant_base & (u32{1} << slot.binding);
            if (input.role != Graph::Role::Unknown && (input.role == Graph::Role::BaseRgb) != expected_base)
                event.recipe = Proof::Failed;
        }
    }
    auto size = count;
    auto omitted = slots.omitted + slots.count - count;
    if (prior) {
        if (size == inputs.size()) ++omitted;
        else inputs[size++] = *prior;
    }
    return trace.Record(event, std::span(inputs).first(size), omitted);
}

struct UiTransfer {
    Graph::ImageVersion source{};
    vk::Image source_image{}, destination_image{};
    vk::ImageLayout source_layout{}, destination_layout{};
    vk::Extent2D source_extent{}, destination_extent{};
    vk::ImageBlit region{};
    vk::Filter filter{};
    u64 writer_view{}; // Resolved view of the same exact current source version.
    Proof source_owner{}, destination_owner{}, ordinary_scope{}, after_writers{};
};

inline bool RecordUi(Graph::SceneTrace& trace, Graph::Event event, const UiTransfer& copy) {
    using namespace Graph;
    const auto& scope = trace.Registration();
    const vk::Extent2D extent{scope.width, scope.height};
    const vk::ImageSubresourceLayers layers{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
    constexpr Subresource subresource{0, 1, 0, 1, 1};
    event.kind = Kind::Ui;
    event.boundary = All(All(copy.source_owner, copy.destination_owner), All(copy.ordinary_scope, copy.after_writers));
    const bool named = copy.source.Valid() && event.output.Valid() && copy.source_image && copy.destination_image;
    const bool exact = named && copy.source_image != copy.destination_image && !copy.source.Aliases(event.output) &&
        copy.source.format == Format::Rgba8Unorm && copy.source.range == subresource && event.output.range == subresource &&
        extent == vk::Extent2D{3840, 2160} && copy.source_extent == extent && copy.destination_extent == extent &&
        copy.source_layout == vk::ImageLayout::eTransferSrcOptimal &&
        copy.destination_layout == vk::ImageLayout::eTransferDstOptimal &&
        copy.region.srcSubresource == layers && copy.region.dstSubresource == layers &&
        copy.region.srcOffsets == copy.region.dstOffsets && copy.region.dstOffsets[0] == vk::Offset3D{0, 0, 0} &&
        copy.region.dstOffsets[1] == vk::Offset3D{3840, 2160, 1} && copy.filter == vk::Filter::eLinear;
    const auto mapping = exact ? Proof::Known : (!named ? Proof::Unknown : Proof::Failed);
    event.pipeline = All(event.pipeline, mapping);
    event.written.fill(mapping);
    Input input{.image = copy.source, .role = Role::BaseRgb, .stage = BindStage::Transfer,
                .access = copy.source_owner, .writer_view = copy.writer_view, .sampler = mapping};
    input.read.fill(mapping);
    input.contribution.fill(mapping);
    return trace.Record(event, std::span(&input, 1));
}

struct TerminalReceipt {
    Graph::Scope scope{};
    Graph::ImageVersion ui{};
    Graph::ProbeLineage probes{};
    std::span<const Graph::Entry> entries; // Valid while the callback reads this packet.
    Proof fence{};
    u32 omitted_events{}, omitted_inputs{}, foreign_events{};
    bool ready{};
};

struct PostPacket {
    using Callback = void (*)(void*, const TerminalReceipt&);
    Graph::SceneTrace trace;

    bool Begin(Graph::Scope scope, Callback callback, void* user) {
        if (!callback || !trace.Begin(scope)) return false;
        complete = callback;
        context = user;
        return true;
    }

    bool Retire(const Graph::ScopeKey& key, const Graph::ImageVersion& ui, Proof fence,
                u64 timeline, u64 completed_tick) {
        const auto& scope = trace.Registration();
        if (!complete || scope.key != key) return false;
        if (fence == Proof::Known && (!completed_tick || !key.timeline || key.timeline != timeline))
            fence = Proof::Failed;
        for (const auto& row : trace.Entries()) {
            if (fence == Proof::Known && row.event.issued != Proof::Failed && row.event.actual.tick > completed_tick)
                fence = Proof::Failed;
        }
        const auto current = trace.Read(ui);
        auto probes = current.probes;
        bool ready = bool(scope.count) && fence == Proof::Known && !trace.ForeignEvents();
        for (u32 i = 0; i < scope.count; ++i) {
            if (probes[i].stage != Graph::Stage::Ui && probes[i].proof == Proof::Known)
                probes[i].proof = Proof::Failed;
            ready &= probes[i].proof == Proof::Known;
        }
        const TerminalReceipt receipt{scope, ui, probes, trace.Entries(), fence, trace.OmittedEvents(),
                                      trace.OmittedInputs(), trace.ForeignEvents(), ready};
        auto callback = std::exchange(complete, nullptr);
        callback(context, receipt);
        return ready;
    }

private:
    Callback complete{};
    void* context{};
};
#endif

struct Session {
    explicit Session(u16 run) : scheduler(run) {}

    Setup::Scheduler scheduler;
    Graph::SetupTrace traces;
    std::mutex mutex;
    std::atomic<bool> active{};
    u64 scene{}, observed{}, ack_scene{}, knob_generation{}, order{};
    bool have_knob_generation{}, pending{}, display_issued{};
    unsigned applies{};
    Native apply{};
    Setup::Observation selected{};
    Graph::SceneTrace* trace{};
    vk::Image ui{};
    Graph::ImageVersion ui_version{};
    Graph::ImageVersion prepared{};
    Graph::ImageVersion swap{};
    const char* frontier{};
    std::array<u64, Graph::MaxEvents> allocation_keys{};
    std::size_t allocations{};

    void ObserveResult(const Setup::Observation& result) {
        Setup::Log(result);
        if (result.kind == Setup::EventKind::Ack) {
            ack_scene = result.frame.scene;
        } else if (result.kind == Setup::EventKind::Refusal) {
            pending = false;
        }
    }

    bool Match(const Ticket& ticket) const {
        return trace && ticket.scene == selected.frame.scene;
    }

    Graph::Event Write(Graph::Kind kind, Graph::ImageVersion output, Proof issue) {
        Graph::Event event{};
        event.kind = kind;
        event.output = output;
        event.order = ++order;
        event.issued = issue;
        return event;
    }

    u64 Allocation(u64 key) {
        if (!key) {
            return 0;
        }
        for (std::size_t i = 0; i < allocations; ++i) {
            if (allocation_keys[i] == key) {
                return i + 1;
            }
        }
        if (allocations == allocation_keys.size()) {
            if (!frontier) frontier = "allocation-cap";
            return 0;
        }
        allocation_keys[allocations++] = key;
        return allocations;
    }

    Graph::ImageVersion Version(vk::Image image, u64 view, u64 uid, vk::Format format,
                                u64 allocation = 0) const {
        return {Id(image), view, uid, allocation, order + 1, {0, 1, 0, 1, 1}, Format(format)};
    }

    Graph::ImageVersion Find(vk::Image image, u64 view = 0) const {
        if (trace) {
            const auto entries = trace->Entries();
            for (auto it = entries.rbegin(); it != entries.rend(); ++it) {
                const auto& out = it->event.output;
                if ((!image || out.backing == Id(image)) && (!view || out.view == view)) {
                    return out;
                }
            }
        }
        return {};
    }

    static Graph::Input Input(Graph::ImageVersion image, Graph::BindStage stage, Graph::Role role) {
        Graph::Input input{};
        input.image = image;
        input.stage = stage;
        input.role = role;
        return input;
    }

    void Edge(Graph::Event event, Graph::Input input) {
        trace->Record(event, std::span{&input, 1});
    }

    void Finish(u64 now, const char* fallback, bool refused = false) {
        if (!trace) {
            return;
        }
        for (const auto& entry : trace->Entries()) {
            const auto& e = entry.event;
            const auto& f = entry.facts;
            std::printf("[bottle-motion-t203] event=graph scene=%llu seq=%llu stage=%u shader=%08x "
                        "permutation=%llx dst=%llx view=%llx uid=%llu allocation=%llu content=%llu "
                        "format=%u range=%u,%u,%u,%u,%u inputs=%zu issue=%u proof=%u,%u "
                        "known=%x failed=%x unknown=%x\n",
                        P(selected.frame.scene), P(e.order), unsigned(e.kind), e.shader, P(e.permutation),
                        P(e.output.backing), P(e.output.view), P(e.output.uid), P(e.output.allocation),
                        P(e.output.content), unsigned(e.output.format), unsigned(e.output.range.mip),
                        unsigned(e.output.range.mips), unsigned(e.output.range.layer),
                        unsigned(e.output.range.layers), unsigned(e.output.range.aspects),
                        entry.input_count, unsigned(e.issued), unsigned(entry.result[0].proof),
                        unsigned(entry.result[1].proof), f.known, f.failed, f.unknown);
            for (std::size_t i = 0; i < entry.input_count; ++i) {
                const auto& input = entry.inputs[i];
                std::printf("[bottle-motion-t203] event=input scene=%llu seq=%llu slot=%u:%u:%u "
                            "role=%u access=%u src=%llx view=%llx writer_view=%llx uid=%llu "
                            "allocation=%llu content=%llu proof=%u,%u\n",
                            P(selected.frame.scene), P(e.order), unsigned(input.stage),
                            unsigned(input.set), unsigned(input.binding), unsigned(input.role),
                            unsigned(input.access), P(input.image.backing), P(input.image.view),
                            P(input.writer_view), P(input.image.uid), P(input.image.allocation),
                            P(input.image.content), unsigned(entry.input_lineage[i][0].proof),
                            unsigned(entry.input_lineage[i][1].proof));
            }
        }
        std::printf("[bottle-motion-t203] event=close scene=%llu boundary=%s refused=%u\n",
                    P(selected.frame.scene), fallback, unsigned(refused));
        const auto proof = trace->PresentResult();
        const bool good = !frontier && proof[0].proof == Proof::Known && proof[1].proof == Proof::Known;
        std::printf("[bottle-motion-t203] event=graph-budget scene=%llu omitted=%u omitted_inputs=%u\n",
                    P(selected.frame.scene), trace->OmittedEvents(), trace->OmittedInputs());
        std::printf("[bottle-motion-t203] event=setup-result run=%u serial=%u on=%u scene=%llu "
                    "qpc_ns=%llu result=%s why=%s\n", unsigned(selected.arm.run), selected.arm.serial,
                    unsigned(selected.arm.on), P(selected.frame.scene), P(now),
                    good ? "passed" : refused ? "refused" : "unknown",
                    good ? "complete" : trace->Overflowed() ? "graph-overflow" :
                    frontier ? frontier : fallback);
        std::fflush(stdout);
        trace = nullptr;
        active.store(false, std::memory_order_release);
    }

    void Expire(u64 now) {
        ObserveResult(scheduler.Expire(now));
        if (trace && now > selected.frame.qpc_ns + 2'000'000'000) {
            Finish(now, "display-prepare-or-present-timeout");
        }
    }
};

inline Session& State() {
    static Session session{Run()};
    return session;
}

inline bool Active() { return Run() && State().active.load(std::memory_order_acquire); }

inline void Begin(u64 now) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    state.Expire(now);
    ++state.scene;
    state.applies = 0;
    state.apply = {};
    const u64 generation = BbLiveKnobs::Generation();
    if (state.have_knob_generation && generation == state.knob_generation) {
        return;
    }
    const auto text = BbLiveKnobs::Lookup("BB_BOTTLE_MOTION_ARM_T203");
    if (generation != BbLiveKnobs::Generation()) return;
    state.have_knob_generation = true;
    state.knob_generation = generation;
    Setup::Arm arm{};
    if (!text.Get() || !Setup::ParseArm(text.Get(), arm) || arm.mode != Setup::Mode::Setup) {
        return;
    }
    const auto result = state.scheduler.Stage(arm, now);
    if (result == Setup::StageResult::Staged) {
        state.pending = true;
    } else if (result != Setup::StageResult::Repeated) {
        std::printf("[bottle-motion-t203] event=stage-ignored run=%u serial=%u status=%u\n",
                    unsigned(arm.run), arm.serial, unsigned(result));
    }
}

inline void Applied(const Native& native) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (state.pending && ++state.applies == 1) {
        state.apply = native;
    }
}

inline void Merge(Setup::NativeFrame frame, Native input, vk::Image output, vk::ImageView view,
                  bool provider_ok, bool fixture_ok, float tone, float scale, u32 debug, u64 allocation) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.pending || !state.scene || state.observed == state.scene) {
        return;
    }
    state.observed = state.scene;
    frame.scene = state.scene;
    const auto decision = state.scheduler.Observe(frame);
    state.ObserveResult(decision);
    if (decision.kind != Setup::EventKind::Select) {
        return;
    }
    state.pending = false;
    state.trace = state.traces.Select(decision.arm.on ? Graph::SetupTrace::Mode::On :
                                                       Graph::SetupTrace::Mode::Off, frame.scene);
    if (!state.trace) {
        return;
    }
    state.selected = decision;
    state.order = 0;
    state.allocations = 0;
    state.display_issued = false;
    state.ui = nullptr;
    state.ui_version = {};
    state.prepared = {};
    state.swap = {};
    state.frontier = nullptr;
    const auto& apply = state.apply;
    const bool phase2 = decision.arm.on ?
        state.applies == 1 && apply.ordinary && apply.timeline == input.timeline && apply.tick <= input.tick &&
        apply.generation == input.generation && apply.color_id == input.color_id &&
        apply.depth_id == input.depth_id && apply.color_uid == input.color_uid &&
        apply.depth_uid == input.depth_uid && apply.color == input.color && apply.depth == input.depth &&
        apply.color_view == input.color_view && apply.depth_view == input.depth_view &&
        apply.view == input.view && apply.projection == input.projection &&
        apply.jitter == input.jitter && apply.width == frame.input_width &&
        apply.height == frame.input_height : state.applies == 0;
    const bool root = phase2 && provider_ok && fixture_ok && !debug && state.ack_scene + 1 == frame.scene;
    std::printf("[bottle-motion-t203] event=merge scene=%llu ack_scene=%llu dlss=%u fixture=%u "
                "phase2=%u applies=%u ordinal=%u debug=%u tone=%.9g scale=%.9g proxy=%llu "
                "tick=%llu apply_tick=%llu input=%u,%llu,%llx,%llx depth=%u,%llu,%llx,%llx "
                "receiver=%.6f,%.6f opaque=%.6f,%.6f jitter=%.9g,%.9g\n",
                P(frame.scene), P(state.ack_scene), unsigned(provider_ok), unsigned(fixture_ok),
                unsigned(phase2), state.applies, apply.ordinal, debug, double(tone), double(scale),
                P(input.generation), P(input.tick), P(apply.tick), input.color_id, P(input.color_uid),
                P(Id(input.color)), P(Id(input.color_view)), input.depth_id, P(input.depth_uid),
                P(Id(input.depth)), P(Id(input.depth_view)),
                decision.receiver[0], decision.receiver[1], decision.opaque[0], decision.opaque[1],
                double(frame.jitter[0]), double(frame.jitter[1]));
    for (std::size_t r = 0; r < 3; ++r) {
        const auto* v = frame.view.data() + 4 * r;
        std::printf("[bottle-motion-t203] event=view scene=%llu row=%zu values=%.9g,%.9g,%.9g,%.9g\n",
                    P(frame.scene), r, double(v[0]), double(v[1]), double(v[2]), double(v[3]));
    }
    std::printf("[bottle-motion-t203] event=projection scene=%llu values=%.9g,%.9g,%.9g,%.9g\n",
                P(frame.scene), double(frame.projection[0]), double(frame.projection[1]),
                double(frame.projection[2]), double(frame.projection[3]));
    auto version = state.Version(output, Id(view), input.color_uid, vk::Format::eR16G16B16A16Sfloat,
                                 state.Allocation(allocation));
    auto event = state.Write(Graph::Kind::Merge, version, Proof::Known);
    event.boundary = root ? Proof::Known : Proof::Failed;
    event.pipeline = Proof::Known;
    event.written.fill(Proof::Known);
    state.trace->Record(event);
    if (!root) {
        state.Finish(frame.qpc_ns, "merge-native-guard", true);
        return;
    }
    if (!version.Valid()) state.frontier = "merge-allocation-unproved";
    state.active.store(true, std::memory_order_release);
}


inline void Expire(u64 now) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    state.Expire(now);
}

inline bool Candidate(u32 shader, u64 permutation, vk::ImageView dst,
                      const VideoCore::Image* guest, const Slots& slots, u32 w, u32 h,
                      u32 attachments, u32 count, u32 instances, bool deferred, bool indirect,
                      bool replacement, bool discard, vk::Rect2D scissor) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.trace || state.scene != state.selected.frame.scene || state.display_issued) return false;
    const auto* contract = Graph::FindCacheContract(shader);
    const auto raw_view = Id(dst);
    const auto current = guest ? state.Find(guest->GetImage()) : Graph::ImageVersion{};
    const bool tracked_input = std::ranges::any_of(
        std::span{slots.images.data(), slots.count},
        [&](const Slot& slot) { return slot.view && state.Find({}, Id(slot.view)).backing; });
    if (!contract && !tracked_input && !current.backing &&
        (!dst || !state.Find({}, raw_view).backing)) return false;
    auto output = state.Version({}, raw_view, 0, vk::Format::eUndefined);
    if (guest) {
        const auto* backing = guest->backing;
        for (const auto id : backing->image_view_ids) {
            const auto& bound = (*guest->slot_image_views)[id];
            if (*bound.image_view != dst) continue;
            const auto& range = bound.info.range;
            if (range.base.level > 65535 || range.base.layer > 65535 ||
                range.extent.levels > 65535 || range.extent.layers > 65535) break;
            output = state.Version(guest->GetImage(), raw_view, guest->image_uid, bound.info.format,
                                   state.Allocation(std::bit_cast<u64>(backing->image.allocation)));
            output.range = {u16(range.base.level), u16(range.extent.levels), u16(range.base.layer),
                            u16(range.extent.layers), 1};
            break;
        }
    }
    auto event = state.Write(Graph::Kind::Raster, output, discard ? Proof::Failed : Proof::Unknown);
    event.shader = shader;
    event.permutation = permutation;
    event.pipeline = replacement || attachments != 1 ? Proof::Failed : Proof::Known;
    std::array<Graph::Input, Graph::MaxInputs + 1> inputs{};
    for (std::size_t i = 0; i < slots.count; ++i) {
        const auto& slot = slots.images[i];
        auto& input = inputs[i];
        input.stage = Graph::BindStage::Fragment;
        input.binding = u8(std::min(slot.binding, 255u));
        if (contract && slot.exact && slot.view && slot.binding < 256 &&
            slot.type == vk::DescriptorType::eSampledImage) {
            input.role = Graph::CachedRole(*contract, input);
        }
        if (slot.view) {
            input.image = state.Find({}, Id(slot.view));
            input.image.view = Id(slot.view);
        }
        input.access = input.image.Valid() && slot.exact ? Proof::Known : Proof::Unknown;
    }
    if (!state.trace->Record(event, std::span{inputs.data(), slots.omitted ? inputs.size() : slots.count})) return false;
    std::printf("[bottle-motion-t203] event=raster scene=%llu seq=%llu extent=%ux%u attachments=%u "
                "count=%u instances=%u route=%s deferred=%u substituted=%u discard=%u "
                "scissor=%d,%d,%u,%u guest_uid=%llu intent=%llu\n",
                P(state.scene), P(event.order), w, h, attachments, count, instances,
                indirect ? "indirect" : "direct", unsigned(deferred), unsigned(replacement),
                unsigned(discard), scissor.offset.x, scissor.offset.y, scissor.extent.width,
                scissor.extent.height, P(guest ? guest->image_uid : 0), P(guest ? guest->write_seq : 0));
    if (!state.frontier) state.frontier = !output.Valid() ? "raster-backing-unproved" :
                                           "raster-vertex-footprint-unproved";
    return true;
}

inline void Mutation(const VideoCore::Image& image,
                     std::optional<VideoCore::SubresourceRange> range, vk::AccessFlags2 access) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.trace || state.scene != state.selected.frame.scene || state.display_issued ||
        !(image.aspect_mask & vk::ImageAspectFlagBits::eColor)) return;
    const auto previous = state.Find(image.GetImage());
    if (!previous.backing) return;
    auto output = state.Version(image.GetImage(), Transfer(image.GetImage()), image.image_uid,
                                image.info.pixel_format,
                                state.Allocation(std::bit_cast<u64>(image.backing->image.allocation)));
    if (range && range->base.level <= 65535 && range->base.layer <= 65535 &&
        range->extent.levels <= 65535 && range->extent.layers <= 65535) {
        output.range = {u16(range->base.level), u16(range->extent.levels), u16(range->base.layer),
                        u16(range->extent.layers), 1};
        if (!previous.range.Overlaps(output.range)) return;
    } else {
        output.range = {}; // Possible overlap; Transit alone proves no concrete write or range.
    }
    auto event = state.Write(Graph::Kind::Overwrite, output, Proof::Unknown);
    if (!state.trace->Record(event)) return;
    std::printf("[bottle-motion-t203] event=mutation-intent scene=%llu seq=%llu access=%llx intent=%llu\n",
                P(state.scene), P(event.order), P(static_cast<VkAccessFlags2>(access)), P(image.write_seq));
    if (!state.frontier) state.frontier = "overlapping-write-intent-unresolved";
}

inline void Ui(vk::Image source, const VideoCore::Image& guest, const VideoCore::UniqueImage& ui,
               vk::ImageBlit region, vk::ImageLayout layout, u32 w, u32 h, bool fixture,
               bool after_upscale) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.trace || state.scene != state.selected.frame.scene || state.display_issued) return;
    state.ui = vk::Image(ui);
    state.ui_version = state.Version(state.ui, Transfer(state.ui), Id(state.ui),
                                     guest.info.pixel_format,
                                     state.Allocation(std::bit_cast<u64>(ui.allocation)));
    auto src = state.Find(source);
    const auto observed_view = src.view;
    const vk::ImageSubresourceLayers color{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
    const bool identity = fixture && region.srcSubresource == color &&
        region.dstSubresource == color && region.srcOffsets == region.dstOffsets &&
        region.dstOffsets[0] == vk::Offset3D{0, 0, 0} &&
        region.dstOffsets[1] == vk::Offset3D{3840, 2160, 1};
    src.backing = Id(source);
    src.view = Transfer(source);
    auto input = Session::Input(src, Graph::BindStage::Transfer, Graph::Role::BaseRgb);
    auto event = state.Write(Graph::Kind::Ui, state.ui_version, Proof::Unknown);
    event.pipeline = Proof::Known;
    event.boundary = fixture ? Proof::Known : Proof::Failed;
    if (identity && !after_upscale) {
        event.written.fill(Proof::Known);
        input.read.fill(Proof::Known);
        if (src.Valid() && src.range == state.ui_version.range) {
            input.writer_view = observed_view;
            input.access = Proof::Known;
        }
    }
    state.Edge(event, input);
    std::printf("[bottle-motion-t203] event=ui-source scene=%llu seq=%llu src=%llx cached_view=%llx "
                "uid=%llu intent=%llu layout=%u extent=%ux%u src_rect=%d,%d,%d,%d "
                "dst_rect=%d,%d,%d,%d after_upscale=%u identity_4k=%u\n", P(state.scene), P(event.order),
                P(Id(source)), P(observed_view), P(guest.image_uid), P(guest.write_seq),
                unsigned(layout), w, h, region.srcOffsets[0].x, region.srcOffsets[0].y,
                region.srcOffsets[1].x, region.srcOffsets[1].y, region.dstOffsets[0].x,
                region.dstOffsets[0].y, region.dstOffsets[1].x, region.dstOffsets[1].y,
                unsigned(after_upscale), unsigned(identity));
    if (!state.frontier) state.frontier = "ui-source-writer-unproved";
}

inline Ticket Display(u64 address, vk::ImageView target, const VideoCore::UniqueImage& image,
                      vk::Format format, vk::Image ui, const Slots& slots, vk::ImageView ui_input,
                      vk::Semaphore timeline, u64 tick, u64 now, bool role) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.trace || state.scene != state.selected.frame.scene || state.display_issued) return {};
    // Only correlate a real output-size display draw with the exact selected UI backing.
    const bool cohort = role && target && image && ui && ui == state.ui;
    const auto output = state.Version(vk::Image(image), Id(target), Id(vk::Image(image)), format,
                                      state.Allocation(std::bit_cast<u64>(image.allocation)));
    auto event = state.Write(Graph::Kind::Display, output, Proof::Unknown);
    event.boundary = cohort ? Proof::Known : Proof::Failed;
    std::array<Graph::Input, Graph::MaxInputs + 1> inputs{};
    for (std::size_t i = 0; i < slots.count; ++i) {
        const auto& slot = slots.images[i];
        auto& input = inputs[i];
        input.stage = Graph::BindStage::Fragment;
        input.binding = u8(std::min(slot.binding, 255u));
        if (ui_input && slot.exact && slot.view == ui_input) {
            input.image = state.ui_version;
            input.role = Graph::Role::BaseRgb;
        }
        input.image.view = Id(slot.view);
    }
    state.trace->Record(event, std::span{inputs.data(), slots.omitted ? inputs.size() : slots.count});
    if (!cohort) {
        if (!state.frontier) state.frontier = "display-cohort-unproved";
        return {};
    }
    state.display_issued = true;
    return {state.scene, tick, now, address, timeline, vk::Image(image), format, std::this_thread::get_id(), output};
}

inline void Prepare(const Ticket& ticket, vk::ImageView sampled, vk::Image output, VmaAllocation allocation,
                    vk::ImageView output_view, vk::Format format, vk::Format sampled_format,
                    bool identity, bool guard, float gamma, u32 hdr, u32 srgb) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.Match(ticket)) return;
    state.prepared = state.Version(output, Id(output_view), Id(output), format,
                                   state.Allocation(std::bit_cast<u64>(allocation)));
    auto event = state.Write(Graph::Kind::Prepare, state.prepared, Proof::Known);
    event.pipeline = identity ? Proof::Known : Proof::Failed;
    event.boundary = guard ? Proof::Known : Proof::Failed;
    auto input = Session::Input(ticket.version, Graph::BindStage::Fragment, Graph::Role::BaseRgb);
    input.image.view = Id(sampled);
    // The procedural viewport triangle samples source-texel centres in the 1:1 route.
    // The freshly created sampling view keeps RGB component mapping and forces alpha only.
    const bool mapped = identity && guard && !hdr && std::isfinite(gamma) && gamma > 0 &&
        sampled_format == ticket.format &&
        (sampled_format == vk::Format::eR8G8B8A8Unorm ||
         sampled_format == vk::Format::eB8G8R8A8Unorm) && format == vk::Format::eB8G8R8A8Unorm;
    if (mapped) {
        event.written.fill(Proof::Known);
        input.read.fill(Proof::Known);
        input.access = Proof::Known;
        input.writer_view = ticket.version.view;
    }
    state.Edge(event, input);
    std::printf("[bottle-motion-t203] event=prepare scene=%llu src_view=%llx dst_view=%llx "
                "input_format=%u gamma=%.9g hdr=%u srgb=%u identity=%u mapped=%u\n",
                P(ticket.scene), P(Id(sampled)), P(Id(output_view)), unsigned(sampled_format),
                double(gamma), hdr, srgb, unsigned(identity), unsigned(mapped));
}

inline void Swap(const Ticket& ticket, vk::Image source, vk::Image acquired, vk::Format format,
                 vk::SwapchainKHR chain, u32 frame_index, u64 ready_tick, bool guard) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.Match(ticket)) return;
    state.swap = state.Version(acquired, Transfer(acquired), Id(acquired), format,
                               state.Allocation(Id(chain)));
    auto event = state.Write(Graph::Kind::Swapchain, state.swap, Proof::Known);
    event.boundary = guard ? Proof::Known : Proof::Failed;
    auto input = Session::Input(state.prepared, Graph::BindStage::Transfer, Graph::Role::BaseRgb);
    input.image.backing = Id(source);
    input.image.view = Transfer(source);
    if (guard) {
        event.pipeline = Proof::Known;
        event.written.fill(Proof::Known);
        input.read.fill(Proof::Known);
        input.access = Proof::Known;
        input.writer_view = state.prepared.view;
    }
    state.Edge(event, input);
    std::printf("[bottle-motion-t203] event=swap scene=%llu chain=%llx image=%llx "
                "frame_index=%u ready_tick=%llu guard=%u\n", P(ticket.scene), P(Id(chain)),
                P(Id(acquired)), frame_index, P(ready_tick), unsigned(guard));
}

inline void Present(const Ticket& ticket, vk::Image acquired, u64 submit, u64 result,
                    bool success, bool real, bool same_chain) {
    auto& state = State();
    std::scoped_lock lock{state.mutex};
    if (!state.Match(ticket)) return;
    const bool valid = acquired && Id(acquired) == state.swap.backing && real && same_chain;
    auto event = state.Write(Graph::Kind::Present, state.swap, success ? Proof::Known : Proof::Failed);
    event.boundary = valid ? Proof::Known : Proof::Failed;
    event.pipeline = Proof::Known;
    event.written.fill(Proof::Known);
    auto input = Session::Input(state.swap, Graph::BindStage::Host, Graph::Role::BaseRgb);
    input.access = Proof::Known;
    input.read.fill(Proof::Known);
    state.Edge(event, input);
    std::printf("[bottle-motion-t203] event=app-present scene=%llu submit_ns=%llu result_ns=%llu "
                "success=%u real=%u same_chain=%u acquired=%llx\n", P(ticket.scene), P(submit),
                P(result), unsigned(success), unsigned(real), unsigned(same_chain), P(Id(acquired)));
    state.Finish(result, "present-ancestry-unproved", !success || !valid);
}

} // namespace Vulkan::BottleMotion203
