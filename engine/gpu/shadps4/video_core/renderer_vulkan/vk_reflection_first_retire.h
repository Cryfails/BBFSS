// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <bit>
#include <cstdio>
#include <string_view>

#include "video_core/renderer_vulkan/vk_reflection_fragment_discard.h"
#include "video_core/renderer_vulkan/vk_reflection_ordinal3.h"
#include "video_core/renderer_vulkan/vk_reflection_native_probe.h"

namespace Vulkan {
class GraphicsPipeline;
namespace ReflectionFirstRetire {

using ReflectionFirstHit::Identity;
using ReflectionFirstHit::PlacedSource;
using ReflectionFirstHit::Stamp;
using ReflectionNativeProbe::Key;

inline bool On() {
    static const bool armed = [] {
        const char* flag = std::getenv("BB_REFLECTION_FIRST_RETIRE");
        const char* lifecycle = std::getenv("BB_REFLECTION_PLACED_LIFECYCLE");
        return flag && std::string_view{flag} == "1" && lifecycle &&
            std::string_view{lifecycle} == "1" && ReflectionFirstHit::On() &&
            ReflectionNativeProbe::ExactEquivalenceOn() && ReflectionDiscard::On();
    }();
    return armed;
}

inline auto Print(u64 number) { return static_cast<unsigned long long>(number); }

struct Object {
    u64 buffer{}, offset{}, range{}, guest{}, guest_bytes{}, digest{};
    u32 slot{}, adjust{}, origin{}, count{};
    bool complete{}, hashed{};
    std::string_view route{"unreached"};
};

struct Palette {
    u64 buffer{}, offset{}, range{}, guest{};
    u32 ordinal{}, slot{}, adjust{}, guest_bytes{}, effective_bytes{}, count{}, flags{};
    // Flags 0..9: stamped, safe, overflow, known, dirty, in-place, writable,
    // has backing, eligible, current handle. Eligibility is the production result.
};

struct Row {
    Key key{};
    Object objects[2]{};
    Palette palette{};
    ReflectionDiscard::Pipeline proof{.fragment = {}, .vertex = nullptr, .handle = nullptr};
    u64 sequence{}, generation{}, frame{}, pass{}, tick{}, record_tick{}, depth_uid{}, cb0_uid{};
    u64 source{}, raster{}, source_key{}, raster_key{}, source_vs{}, source_ps{}, raster_vs{}, raster_ps{};
    u64 ready{}, handle{}, sample{}, allocation{}, placement{}, cookie{};
    u32 instances{}, first_instance{}, clip{}, depth{}, blend{}, draw_flags{};
    s32 vertex{};
    const char* admission = "unreached";
    const char* candidate = "unreached";
    const char* decision = "unreached";
    std::string_view capture = "unreached";
    const char* exact = "unreached";
    const char* issue = "unresolved";
    const char* module = "unreached";
    ReflectionDiscard::Verdict verdict{};
    ReflectionDiscard::Verdict observed_certificate{};
    bool shared{}, effective{}, defer_card{}, stamped{}, original{}, confirmed{};
};

struct Resident {
    Identity id{};
    u64 generation{}, epoch{}, frame{}, pass{};
    bool current{};
};

struct Lifecycle {
    std::string_view event{};
    u64 frame{}, pass{}, cookie{}, a{}, b{};
};

struct Loss {
    Lifecycle first{}, paired{}, upstream{};
    u64 sequence{}, prior_frame{}, prior_pass{}, prior_cookie{}, build_cookie{};
    u64 drop_prior_frame{}, drop_prior_pass{};
    bool drop_seen{};
};

struct Receipt {
    const void* scheduler{};
    const void* renderer{};
    const void* pass_owner{};
    u64 sequence{};
    Row* active{};
    Row predecessor{}, wall{}, mirror{};
    Resident fireplace{}, wall_resident{}, mirror_resident{};
    Loss loss{};
    Lifecycle upstream{};
    u64 upstream_sequence{};
    bool emitted{};
};

static_assert(sizeof(Receipt) + sizeof(Row) <= 8192);
inline constinit thread_local Receipt receipt{};

inline Row* Current(const void* renderer) {
    return On() && receipt.renderer == renderer ? receipt.active : nullptr;
}

inline bool Match(const Resident& resident, const Identity& id, u64 epoch) {
    return resident.current && resident.epoch == epoch && resident.id.allocation == id.allocation &&
        resident.id.revision == id.revision && resident.id.surface == id.surface &&
        resident.id.placement == id.placement;
}

inline void ReportObject(const char* name, u32 ordinal, const Object& object) {
    std::printf("Reflection first-retire object=%u row=%s descriptors=%u slot=%u handle=%llx offset=%llu "
                "range=%llu adjust=%u guest=%llx guest_bytes=%llu route=%.*s origin=%u complete=%u "
                "digest=%016llx hashed=%u\n", ordinal, name, object.count, object.slot,
                Print(object.buffer), Print(object.offset), Print(object.range), object.adjust,
                Print(object.guest), Print(object.guest_bytes), int(object.route.size()),
                object.route.data(), object.origin, u32(object.complete), Print(object.digest),
                u32(object.hashed));
}

inline void ReportRow(const char* name, const Row& row, const char* status, u64 age) {
    const auto& module = row.proof.fragment;
    std::printf("Reflection first-retire row=%s status=%s sequence=%llu generation=%llu frame=%llu "
                "pass=%llu tick=%llu record_tick=%llu age=%llu vs=%llx ps=%llx count=%u first=%u "
                "vk_first=0 vertex=%d instances=%u first_instance=%u source=%llx raster=%llx "
                "source_key=%llx raster_key=%llx source_vs=%llx source_ps=%llx raster_vs=%llx raster_ps=%llx "
                "ready=%llx handle=%llx sample=%llx admission=%s candidate=%s verdict=%u certificate=%u decision=%s "
                "shared=%u alpha=%u defer_card=%u stamped=%u depth_uid=%llu cb0_uid=%llu depth=%u "
                "blend=%u clip=%u flags=%u exact=%s hashed_objects=%u,%u capture=%.*s draw_allocation=%llu "
                "placement=%llu cookie=%llu "
                "issue=%s original=%u confirmed=%u proof=%s permutation=%zu module=%llx module_gen=%llu "
                "vertex_module=%llx route=%s bytes=%zu xxh3=%016llx raw_shared=%d scanned=%u "
                "kill=%u terminate=%u demote=%u\n",
                name, status, Print(row.sequence), Print(row.generation), Print(row.frame), Print(row.pass),
                Print(row.tick), Print(row.record_tick), Print(age), Print(row.key.vs), Print(row.key.ps),
                row.key.count, row.key.first, row.vertex, row.instances, row.first_instance, Print(row.source),
                Print(row.raster), Print(row.source_key), Print(row.raster_key), Print(row.source_vs),
                Print(row.source_ps), Print(row.raster_vs), Print(row.raster_ps), Print(row.ready),
                Print(row.handle), Print(row.sample), row.admission, row.candidate, u32(row.verdict),
                u32(row.observed_certificate), row.decision, u32(row.shared), u32(row.effective),
                u32(row.defer_card), u32(row.stamped),
                Print(row.depth_uid), Print(row.cb0_uid), row.depth, row.blend, row.clip, row.draw_flags,
                row.exact, u32(row.objects[0].hashed), u32(row.objects[1].hashed),
                int(row.capture.size()), row.capture.data(), Print(row.allocation),
                Print(row.placement), Print(row.cookie), row.issue, u32(row.original), u32(row.confirmed),
                row.module, module.permutation, Print(module.id.handle), Print(module.id.generation),
                Print(std::bit_cast<u64>(row.proof.vertex)),
                module.id.handle ? ReflectionDiscard::Name(module.route) : "unknown",
                module.bytes, Print(module.effective_xxh3),
                module.warm_raw_discard ? int(*module.warm_raw_discard) : -1, u32(module.opcodes.valid),
                module.opcodes.kill, module.opcodes.terminate, module.opcodes.demote);
    ReportObject(name, 0, row.objects[0]);
    ReportObject(name, 3, row.objects[1]);
    const auto& palette = row.palette;
    std::printf("Reflection first-retire palette=%s count=%u ordinal=%u slot=%u buffer=%llx offset=%llu "
                "range=%llu adjust=%u guest=%llx guest_bytes=%u effective_bytes=%u flags=%u\n",
                name, palette.count, palette.ordinal, palette.slot, Print(palette.buffer),
                Print(palette.offset), Print(palette.range), palette.adjust, Print(palette.guest),
                palette.guest_bytes, palette.effective_bytes, palette.flags);
}

inline const char* Name(std::string_view event) {
    return event.empty() ? "none" : event.data(); // Lifecycle reasons are static strings.
}

inline void Emit(const Row* loss, bool stop = false) {
    auto& r = receipt;
    if (r.emitted || (!stop && r.loss.first.event.empty())) {
        return;
    }
    r.emitted = true;
    const auto& f = r.fireplace;
    const auto& l = r.loss;
    const u64 frame = stop ? f.frame : l.first.frame;
    const u64 pass = stop ? f.pass : l.first.pass;
    const auto age = [frame](const Row& row) {
        return row.sequence && frame >= row.frame ? frame - row.frame : ~u64{};
    };
    const bool predecessor = r.predecessor.confirmed && r.predecessor.original && l.prior_cookie &&
        l.drop_seen && l.prior_frame == l.drop_prior_frame && l.prior_pass == l.drop_prior_pass &&
        r.predecessor.generation == f.generation && r.predecessor.allocation == f.id.allocation &&
        r.predecessor.placement == f.id.placement &&
        r.predecessor.frame == l.prior_frame && r.predecessor.pass == l.prior_pass &&
        r.predecessor.cookie == l.prior_cookie;
    const bool joined = loss && loss->sequence == l.sequence && loss->stamped &&
        loss->generation == f.generation && loss->frame == frame && loss->pass == pass;
    const char* outcome = stop ? "no-selected-loss" : !joined ? "foreign-unjoined" :
        !loss->original ? "loss-unjoined" : !loss->proof.fragment.opcodes.valid ? "module-unjoined" :
        !predecessor ? "predecessor-unjoined" : "joined";
    const char* finding = "unresolved";
    if (std::string_view{outcome} == "joined" && r.predecessor.proof.fragment.opcodes.valid) {
        const auto& opcodes = loss->proof.fragment.opcodes;
        if (loss->effective && loss->capture == "discard") {
            finding = opcodes.kill || opcodes.terminate || opcodes.demote ? "actual-discard" :
                loss->observed_certificate == ReflectionDiscard::Verdict::CertifiedClear
                ? "certified-clear-alpha-one" : "clear-outside-certificate";
        } else if (!loss->effective && l.upstream.event == "observe-identity-change" && l.upstream.b) {
            finding = "placement-identity-changed";
        }
    }
    ReportRow("predecessor", predecessor ? r.predecessor : Row{},
              predecessor ? "matched" : "predecessor-unjoined", age(r.predecessor));
    ReportRow("loss", loss ? *loss : Row{}, joined ? "matched" : "unjoined", 0);
    auto control = [&](const char* name, const Row& row, const Resident& resident) {
        const bool current = resident.current && row.sequence && row.confirmed &&
            row.generation == f.generation && row.frame == frame && row.pass == pass &&
            row.placement == resident.id.placement;
        ReportRow(name, row, !row.sequence ? "missing" : current ? "current" :
                  resident.current ? "resident-prior-draw" : "nonresident", age(row));
    };
    control("wall", r.wall, r.wall_resident);
    control("mirror", r.mirror, r.mirror_resident);
    std::printf("Reflection first-retire outcome=%s allocation=%llu revision=%llu placement=%llu "
                "generation=%llu frame=%llu pass=%llu event=%s paired=%s upstream=%s failures=%llu "
                "state=%llu prior_frame=%llu prior_pass=%llu prior_cookie=%llu build_cookie=%llu "
                "upstream_cookie=%llu paired_frame=%llu paired_pass=%llu finding=%s renderer=%llx "
                "epoch=%llu surface=%llu drop_prior_frame=%llu drop_prior_pass=%llu\n",
                outcome, Print(f.id.allocation), Print(f.id.revision), Print(f.id.placement),
                Print(f.generation), Print(frame), Print(pass), Name(l.first.event), Name(l.paired.event),
                Name(l.upstream.event), Print(l.upstream.a), Print(l.upstream.b), Print(l.prior_frame),
                Print(l.prior_pass), Print(l.prior_cookie), Print(l.build_cookie),
                Print(l.upstream.cookie), Print(l.paired.frame), Print(l.paired.pass), finding,
                Print(reinterpret_cast<uintptr_t>(r.renderer)), Print(f.epoch), Print(f.id.surface),
                Print(l.drop_prior_frame), Print(l.drop_prior_pass));
}

class Scope {
public:
    Scope(const void* renderer, const void* scheduler, Key key, u64 generation, u64 tick) {
        auto& r = receipt;
        if (!r.renderer) {
            r.renderer = renderer;
            r.scheduler = scheduler;
        }
        if (r.renderer == renderer && !r.active && !r.emitted) {
            row.key = key;
            row.sequence = ++r.sequence;
            row.generation = generation;
            row.tick = tick;
            r.active = &row;
        }
    }
    Scope(const Scope&) = delete;
    ~Scope() {
        auto& r = receipt;
        if (r.active != &row) {
            return;
        }
        r.active = nullptr;
        ReflectionOrdinal3::FinishDraw(row);
        if (ReflectionOrdinal3::On() && !ReflectionOrdinal3::state.chosen.direct) ReflectionOrdinal3::MaybeReport();
        if (!r.loss.first.event.empty()) {
            Emit(r.loss.sequence == row.sequence ? &row : nullptr);
            return;
        }
        if (!row.original || !row.stamped) {
            return;
        }
        switch (PlacedSource(ReflectionNativeProbe::Match(row.key))) {
        case PlacedSource::Fireplace:
            if (row.confirmed && (!r.fireplace.current ||
                (row.generation == r.fireplace.generation && row.allocation == r.fireplace.id.allocation &&
                 row.placement == r.fireplace.id.placement))) {
                r.predecessor = row;
            }
            break;
        case PlacedSource::Wall:
            if (row.confirmed && row.proof.fragment.opcodes.valid && row.shared && !row.effective &&
                row.verdict == ReflectionDiscard::Verdict::CertifiedClear) {
                r.wall = row;
            }
            break;
        case PlacedSource::Mirror:
            if (row.proof.fragment.opcodes.valid && !row.shared && !row.effective && !row.proof.fragment.opcodes.kill &&
                !row.proof.fragment.opcodes.terminate && !row.proof.fragment.opcodes.demote) {
                r.mirror = row;
            }
            break;
        default:
            break;
        }
    }

private:
    Row row{};
};

inline bool Owned(const void* scheduler, const void* owner) {
    auto& r = receipt;
    return On() && !r.emitted && r.scheduler == scheduler && r.pass_owner == owner;
}

inline void Clone(const void* scheduler, const void* owner, const Stamp& stamp,
                  u64 epoch, const Identity& id) {
    auto& r = receipt;
    if (!On() || r.emitted || r.scheduler != scheduler || id.placed == PlacedSource::None) return;
    if (!r.pass_owner) r.pass_owner = owner;
    if (!Owned(scheduler, owner)) return;
    const Resident resident{id, stamp.generation, epoch, stamp.frame, stamp.pass, true};
    if (id.placed == PlacedSource::Wall) r.wall_resident = resident;
    if (id.placed == PlacedSource::Mirror) {
        r.mirror_resident = resident;
        ReflectionOrdinal3::Clone(r.renderer, scheduler, owner, epoch, stamp.generation, stamp.frame,
                                  stamp.pass, id.surface, id.placement, id.allocation, id.revision);
    }
    if (id.placed == PlacedSource::Fireplace && !r.fireplace.current) {
        r.fireplace = resident;
        std::printf("Reflection first-retire armed allocation=%llu revision=%llu placement=%llu "
                    "generation=%llu frame=%llu pass=%llu\n", Print(id.allocation), Print(id.revision),
                    Print(id.placement), Print(stamp.generation), Print(stamp.frame), Print(stamp.pass));
    }
}

inline void Upstream(PlacedSource role, std::string_view reason, u64 frame, u64 pass,
                     u64 allocation, u64 revision, u64 cookie, u64 a, u64 b) {
    auto& r = receipt;
    ReflectionOrdinal3::Trace(u32(role), r.active ? r.active->sequence : 0, reason,
                              frame, pass, allocation, revision, cookie, a, b);
    if (!On() || r.emitted || !r.fireplace.current || role != PlacedSource::Fireplace ||
        allocation != r.fireplace.id.allocation || revision != r.fireplace.id.revision ||
        (reason != "observe-refused" && reason != "observe-ineligible-shadow" &&
         reason != "observe-identity-change" && !reason.starts_with("submission-") &&
         !reason.starts_with("flush-") && !reason.starts_with("ordinary-") &&
         reason != "palette-observed-identity")) {
        return;
    }
    r.upstream = {reason, frame, pass, cookie, a, b};
    r.upstream_sequence = r.active ? r.active->sequence : 0;
}

inline void Invalidate(const void* scheduler, const void* owner, const Identity& id, u64 epoch,
                       Lifecycle event, const Stamp& bank, u64 prior_cookie, u64 build_cookie,
                       u64 prior_frame = 0, u64 prior_pass = 0) {
    auto& r = receipt;
    if (!Owned(scheduler, owner)) return;
    if (Match(r.wall_resident, id, epoch)) r.wall_resident.current = false;
    ReflectionOrdinal3::Invalidate(scheduler, owner, epoch, u32(id.placed), id.allocation, id.revision,
                                   id.surface, id.placement, r.active ? r.active->sequence : 0, event.event,
                                   event.frame, event.pass, bank.frame, bank.pass, prior_cookie, build_cookie,
                                   prior_frame, prior_pass);
    if (Match(r.mirror_resident, id, epoch)) r.mirror_resident.current = false;
    if (!Match(r.fireplace, id, epoch)) return;
    auto& l = r.loss;
    if (l.first.event.empty()) {
        l.first = event;
        if (r.upstream.frame == event.frame && r.upstream.pass == event.pass &&
            r.upstream_sequence == (r.active ? r.active->sequence : 0)) {
            l.upstream = r.upstream;
            if (r.active && ReflectionNativeProbe::Match(r.active->key) == u32(PlacedSource::Fireplace) &&
                (l.upstream.event.starts_with("observe-") || l.upstream.event.starts_with("submission-") ||
                 l.upstream.event == "palette-observed-identity")) {
                l.sequence = r.active->sequence;
            }
        }
        l.prior_frame = bank.frame;
        l.prior_pass = bank.pass;
        l.prior_cookie = prior_cookie;
        l.build_cookie = build_cookie;
    } else if (l.paired.event.empty()) {
        l.paired = event;
    }
    if (event.event.starts_with("clone-drop-")) {
        l.drop_seen = true;
        l.drop_prior_frame = prior_frame;
        l.drop_prior_pass = prior_pass;
    }
}

inline void FinishOperation(const void* scheduler, const void* owner) {
    if (ReflectionOrdinal3::On() && Owned(scheduler, owner) && !receipt.active &&
        !ReflectionOrdinal3::state.chosen.direct) ReflectionOrdinal3::MaybeReport();
    if (Owned(scheduler, owner) && !receipt.active) Emit(nullptr);
}

inline void Stop(const void* scheduler, const void* owner) {
    if (ReflectionOrdinal3::On() && Owned(scheduler, owner)) ReflectionOrdinal3::MaybeReport(true);
    if (Owned(scheduler, owner) && receipt.fireplace.current) {
        Emit(nullptr, receipt.loss.first.event.empty());
    }
}

void ReadModule(Row& row, const PipelineCache& cache, const GraphicsPipeline& pipeline);

} // namespace ReflectionFirstRetire
} // namespace Vulkan
