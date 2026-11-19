// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <chrono>
#include <cstring>
#include <memory>
#include <vector>

#include "bbport_live_knobs.h"
#include "interior_roof_probe.h"
#include "roof_watch_key.h"

#include <new>
#include "video_core/host_shaders/interior_roof_probe_comp.h"
#include "vk_effect_pass.h"
#include "vk_instance.h"
#include "vk_interior_exposure.h"
#include "vk_scheduler.h"
#include <vk_mem_alloc.h>

namespace Vulkan::InteriorRoof {
struct Counters {
    U64 build, refit, reuse, ring_full, bad_view, no_address, dangling, moved, no_handle;
    U64 over_budget, unsupported;
};
struct Push {
    Matrix view;
    std::array<float, 4> origin;
    U32 count;
};
static_assert(sizeof(Push) == 68);

inline U64 Now() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

class Probe {
public:
    explicit Probe(const Instance& instance, Scheduler& scheduler)
        : instance(instance), scheduler(scheduler) {
        if (const char* key = std::getenv("BB_INTERIOR_ROOF_WATCH")) {
            const auto* keys = std::strcmp(key, "library") == 0 ? &LibraryWatch :
                               std::strcmp(key, "church") == 0 ? &ChurchWatch : nullptr;
            if (keys) {
                watch.reset(new (std::nothrow) KeyWatch);
                if (watch) {
                    watch->Select(*keys);
                }
            }
        }
    }
    // RtShadow's existing teardown drains the scheduler before destroying the probe.
    ~Probe() { Release(); }

    void Reject(const char* reason, bool forget) {
        if (!disabled) {
            unavailable = reason;
        }
        if (forget) {
            scene.reset();
        }
    }
    void Publish(std::shared_ptr<Scene> next) {
        if (next->records.empty()) {
            if (auto* watching = Watch()) {
                watching->SceneRefusal("zero-emitted-records");
            }
            Reject("zero emitted RT records", true);
            return;
        }
        generation = next->serial;
        if (auto* watching = Watch()) {
            watching->Published(*next);
        }
        scene = std::move(next);
    }
    [[nodiscard]] bool Enabled() const noexcept { return !disabled; }
    KeyWatch* Watch() { return Enabled() ? watch.get() : nullptr; }
    void WatchEnd(U64 frame) {
        if (!Watch()) {
            return;
        }
        const auto now = Now();
        const bool report = now >= next_watch_report;
        if (report) {
            next_watch_report = now + 250;
        }
        for (auto& row : watch->rows) {
            row.Seal(frame);
            if (!report) {
                continue;
            }
            if (row.transitions) {
                WatchLine(row, row.first_change, row.first_transition, "first-transition");
                if (row.transitions > 1) {
                    WatchLine(row, row.last_change, row.last_transition, "last-transition");
                }
            }
            WatchLine(row, row.prior, frame, "snapshot");
            row.transitions = 0;
        }
    }

    void RecordGeometry(U64 address, U64 clip_to_world) { revisions.Record(address, clip_to_world); }
    void ForgetGeometry(U64 address) { revisions.Forget(address); }
    [[nodiscard]] GeometryRevision Geometry(U64 address) const { return revisions.Find(address); }

    // Only an ordinary successful PrepareScene path calls Use.
    void Use(vk::AccelerationStructureKHR tlas, const Camera& camera, U64 frame,
             const Counters& counters) {
        if (disabled) {
            return;
        }
        natural_frame = frame;
        if (!tlas || !scene || !(scene->camera == camera)) {
            Reject("no matching published TLAS and camera", false);
            return;
        }
        const U64 now = Now();
        const Vec camera_pos = camera.Position();
        static BbLiveKnobs::Knob<bool> freeze{"BB_INTERIOR_ROOF_ORIGIN", [](const char* value) {
            return value && std::strcmp(value, "frozen") == 0;
        }};
        const bool frozen_now = freeze.Get();
        if (frozen_now && !frozen) {
            fixed = camera_pos;
        }
        frozen = frozen_now;
        current_origin = frozen ? fixed : camera_pos;
        origin_frame = frame;
        unavailable = nullptr;
        if (now < next_sample) {
            return;
        }
        next_sample = now + PeriodMs;
        if (!pipeline && !Make()) {
            return;
        }
        auto it = FreeSlot(slots);
        if (it == slots.end()) {
            ++busy;
            Reject("all three result slots pending", false);
            return;
        }
        Slot& slot = *it;
        const auto start = std::chrono::steady_clock::now();
        const U32 count = U32(scene->records.size());
        for (U32 i = 0; i < count; ++i) {
            slot.flags.mapped[i] = scene->records[i].flags;
        }
        if (vmaFlushAllocation(instance.GetAllocator(), slot.flags.allocation, 0,
                               count * sizeof(U32)) != VK_SUCCESS) {
            Disable("sidecar flush failed");
            return;
        }
        const Push push{scene->camera.view, {current_origin[0], current_origin[1], current_origin[2], 1}, count};
        slot.scene = scene;
        slot.sequence = ++sequence;
        slot.frame = frame;
        slot.ms = now;
        slot.frozen = frozen;
        slot.origin = current_origin;
        slot.camera = camera_pos;
        slot.counters = counters;
        slot.exposure = InteriorExposure::ReadRoofEvidence();
        scheduler.EndRendering();
        const U32 query = U32(&slot - slots.data()) * 2u;
        scheduler.RecordCrumb({.name = "Interior roof diagnostic (nine rays)"},
            [push, tlas, flags = slot.flags.buffer, results = slot.results.buffer,
             pipe = *pipeline, pipe_layout = *layout,
             pool = timestamps.get(), query](vk::CommandBuffer cmd) {
                if (pool) {
                    cmd.resetQueryPool(pool, query, 2);
                    cmd.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, pool, query);
                }
                constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
                constexpr auto Build = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;
                constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
                constexpr auto AsRead = vk::AccessFlagBits2::eAccelerationStructureReadKHR;
                constexpr auto AsWrite = vk::AccessFlagBits2::eAccelerationStructureWriteKHR;
                EffectPass::MemoryBarrier(cmd, Build, AsWrite, Compute, AsRead);
                const vk::WriteDescriptorSetAccelerationStructureKHR as{
                    .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
                const vk::DescriptorBufferInfo flag_info{flags, 0, push.count * sizeof(U32)};
                const vk::DescriptorBufferInfo result_info{results, 0, sizeof(Results)};
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.pNext = &as, .dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &flag_info},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &result_info},
                }};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipe);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pipe_layout, 0, writes);
                cmd.pushConstants(pipe_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
                cmd.dispatch(1, 1, 1);
                EffectPass::MemoryBarrier(cmd, Compute, AsRead, Build, AsWrite);
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, Host,
                                          vk::AccessFlagBits2::eHostRead);
                if (pool) {
                    cmd.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, pool, query + 1);
                }
            });
        slot.tick = scheduler.CurrentTick();
        slot.submit_us = Micros(start);
    }

    void Poll(U64 frame, const char* inactive) {
        const U64 now = Now();
        const char* reason = inactive ? inactive :
            (natural_frame == frame ? unavailable : unavailable ? unavailable : "no natural RT scene this frame");
        const bool origin_current = origin_frame == frame && bool(scene);
        for (auto& slot : slots) {
            if (!Ready(slot.tick, [&](U64 tick) { return scheduler.IsFree(tick); })) {
                continue;
            }
            if (!disabled) {
                const auto start = std::chrono::steady_clock::now();
                if (vmaInvalidateAllocation(instance.GetAllocator(), slot.results.allocation, 0,
                                            sizeof(Results)) != VK_SUCCESS) {
                    Disable("result invalidation failed");
                } else {
                    Results result{};
                    std::memcpy(result.data(), slot.results.mapped, sizeof(result));
                    const double gpu_us = GpuMicros(slot);
                    Report(slot, result, now, Micros(start), gpu_us, reason, origin_current);
                    if (slot.sequence > last.sequence) {
                        last = {slot.sequence, slot.ms, slot.scene->serial, slot.origin};
                    }
                }
            }
            slot.tick = 0;
            slot.scene.reset();
        }
        if (disabled) {
            return;
        }
        const auto freshness = CompareSample(last.ms, now, last.generation, CurrentGeneration(),
                                             last.origin, current_origin, reason != nullptr, origin_current);
        const bool stale = last.sequence && freshness.Any();
        if (now >= next_state && (reason || stale || !last.sequence)) {
            next_state = now + PeriodMs;
            std::printf("Roof probe (t132e): at %llu frame %llu available=0 stale=%u last=%llu pending=%u busy=%llu reason=%s"
                        " query-gen=%llu current-gen=%llu stale-age/scene-gen/origin/missing/unavailable=%u/%u/%u/%u/%u origin-current=%u\n",
                        U(now), U(frame), unsigned(stale), U(last.sequence), Pending(), U(busy),
                        reason ? reason : stale ? "last result stale" : "pending first result",
                        U(last.generation), U(CurrentGeneration()),
                        unsigned(last.sequence && freshness.age), unsigned(last.sequence && freshness.generation),
                        unsigned(last.sequence && freshness.origin), unsigned(last.sequence && freshness.scene_missing),
                        unsigned(last.sequence && freshness.unavailable), unsigned(origin_current));
        }
    }

private:
    struct Buffer {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        U32* mapped = nullptr;
    };
    struct Slot {
        Buffer flags, results;
        std::shared_ptr<const Scene> scene;
        U64 tick = 0, sequence = 0, frame = 0, ms = 0, submit_us = 0;
        bool frozen = false;
        Vec origin{}, camera{};
        Counters counters{};
        InteriorExposure::RoofEvidence exposure{};
    };
    struct Last { U64 sequence = 0, ms = 0, generation = 0; Vec origin{}; };
    struct RawObservation {
        Record record{};
        bool complete{}, hit{};
    };
    struct RawSample {
        std::array<RawObservation, ROOF_RAYS> rays{};
        U64 sequence{}, generation{};
        Vec origin{};
    };
    const Instance& instance;
    Scheduler& scheduler;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::UniqueQueryPool timestamps;
    U32 timestamp_bits = 0;
    double timestamp_ns = 0;
    std::array<Slot, Slots> slots{};
    std::shared_ptr<const Scene> scene;
    Last last;
    RawSample last_raw;
    GeometryRevisions revisions;
    std::unique_ptr<KeyWatch> watch;
    U64 next_watch_report = 0, next_content_report = 0;

    static void WatchLine(const WatchRow& row, const WatchFrame& value, U64 frame, const char* type) {
        std::printf("Roof watch (t132e): %s frame=%llu key=%016llx mesh=%016llx transitions=%u "
                    "mesh-draws=%u exact-key-draws=%u queued=%u capture-recorded=%u frame-list=%u "
                    "cached=%s/%u lifetime=%llu capture-frame=%llu cache-why=%s mesh-why=%s draw-why=%s "
                    "held-list=%u eligible=%u next=%u held-why=%s "
                    "publication=%s serial=%llu scanned=%u emitted=%u id=%u unassigned-guard=%u emit-why=%s\n",
                    type, U(frame), U(row.target.key), U(row.target.mesh), row.transitions,
                    value.mesh_draws, value.key_draws, value.queued, value.captured, value.listed,
                    value.cache_known ? "observed" : "unknown", value.cache_count,
                    U(value.lifetime), U(value.capture_frame), value.cache_why, value.mesh_why, value.draw_why,
                    value.held_seen, value.held_pick, value.held_next, value.hold_why,
                    value.publication ? "observed" : "unknown", U(value.serial), value.scanned, value.emitted,
                    value.id, value.unassigned_guard, value.emit_why);
    }
    Vec current_origin{}, fixed{};
    U64 origin_frame = ~U64(0);
    bool frozen = false, disabled = false;
    U64 generation = 0, sequence = 0, natural_frame = 0, next_sample = 0, next_state = 0;
    U64 busy = 0, allocated = 0;
    const char* unavailable = "waiting for RT scene";

    [[nodiscard]] U64 CurrentGeneration() const { return scene ? scene->serial : 0; }

    static unsigned long long U(U64 value) { return static_cast<unsigned long long>(value); }
    static U64 Micros(std::chrono::steady_clock::time_point start) {
        return std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now() - start).count();
    }
    [[nodiscard]] unsigned Pending() const {
        return unsigned(std::ranges::count_if(slots, [](const Slot& slot) { return slot.tick != 0; }));
    }
    void Disable(const char* reason) {
        disabled = true;
        scene.reset();
        std::printf("Roof probe (t132e): available=0 disabled: %s\n", reason);
    }
    bool MakeBuffer(Buffer& out, U64 bytes, VmaAllocationCreateFlags access) {
        const VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
                                      .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
        const VmaAllocationCreateInfo memory{.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | access,
                                              .usage = VMA_MEMORY_USAGE_AUTO};
        VkBuffer buffer{};
        VmaAllocationInfo made{};
        if (vmaCreateBuffer(instance.GetAllocator(), &info, &memory, &buffer, &out.allocation,
                            &made) != VK_SUCCESS) {
            return false;
        }
        out.buffer = buffer;
        out.mapped = static_cast<U32*>(made.pMappedData);
        allocated += made.size;
        return out.mapped != nullptr;
    }
    bool Make() {
        using Type = vk::DescriptorType;
        if (!instance.IsRayQuerySupported() ||
            !EffectPass::Create(instance, set_layout, layout, pipeline,
                                {Type::eAccelerationStructureKHR, Type::eStorageBuffer, Type::eStorageBuffer},
                                sizeof(Push), INTERIOR_ROOF_PROBE_COMP, "Interior roof diagnostic")) {
            Disable("ray query or compute pipeline unavailable");
            return false;
        }
        for (auto& slot : slots) {
            if (!MakeBuffer(slot.flags, MaxRecords * sizeof(U32), VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT) ||
                !MakeBuffer(slot.results, sizeof(Results), VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT)) {
                Disable("mapped sidecar or result allocation failed");
                Release();
                return false;
            }
        }
        const auto gpu = instance.GetPhysicalDevice();
        const auto families = gpu.getQueueFamilyProperties();
        const U32 family = instance.GetGraphicsQueueFamilyIndex();
        timestamp_bits = family < families.size() ? families[family].timestampValidBits : 0;
        timestamp_ns = gpu.getProperties().limits.timestampPeriod;
        if (timestamp_bits != 0 && timestamp_ns > 0) {
            auto made = instance.GetDevice().createQueryPoolUnique(
                {.queryType = vk::QueryType::eTimestamp, .queryCount = Slots * 2u});
            if (made.result == vk::Result::eSuccess) {
                timestamps = std::move(made.value);
            }
        }
        std::printf("Roof probe (t132e): nine rays at 4 Hz, %.2f..%.2f m; 3 slots, VMA allocations %llu B; material provenance limited; flags glass/registry/cards/layers/shell/clear/guard bits 0..6\n",
                    double(ROOF_TMIN), double(ROOF_TMAX), U(allocated));
        return true;
    }
    void Release() {
        for (auto& slot : slots) {
            for (Buffer* buffer : {&slot.flags, &slot.results}) {
                if (buffer->buffer) {
                    vmaDestroyBuffer(instance.GetAllocator(), buffer->buffer, buffer->allocation);
                    *buffer = {};
                }
            }
        }
    }

    double GpuMicros(const Slot& slot) const {
        if (!timestamps) {
            return -1;
        }
        std::array<U64, 2> stamp{};
        const auto status = instance.GetDevice().getQueryPoolResults(
            *timestamps, U32(&slot - slots.data()) * 2u, 2, sizeof(stamp), stamp.data(),
            sizeof(U64), vk::QueryResultFlagBits::e64);
        if (status != vk::Result::eSuccess) {
            return -1;
        }
        const U64 mask = timestamp_bits >= 64 ? ~U64(0) : (U64(1) << timestamp_bits) - 1;
        return double((stamp[1] - stamp[0]) & mask) * timestamp_ns * 0.001;
    }

    void ReportRawChange(U64 sequence, U32 ray, const Scene& query, const RawObservation& prior,
                         const RawObservation& current) const {
        if (!prior.complete || !current.complete) {
            return;
        }
        const auto& before = prior.record;
        const auto& after = current.record;
        const bool same_lifetime = before.geometry.lifetime == after.geometry.lifetime ||
                                   !before.geometry.lifetime || !after.geometry.lifetime;
        if (prior.hit == current.hit &&
            (!prior.hit || (before.key == after.key && before.mesh == after.mesh && same_lifetime))) {
            return;
        }
        const auto old_in_query = prior.hit ? FindEmitted(query, before) : EmittedPresence{};
        const auto new_in_current = current.hit && scene ? FindEmitted(*scene, after) : EmittedPresence{};
        const U32 prior_id = old_in_query.Id();
        const U32 latest_id = new_in_current.Id();
        const GeometryRevision prior_revision = prior_id == ROOF_NONE ? GeometryRevision{} :
                                                  query.records[prior_id].geometry;
        const GeometryRevision latest_revision = latest_id == ROOF_NONE ? GeometryRevision{} :
                                                    scene->records[latest_id].geometry;
        std::printf("Roof probe (t132e): seq %llu ray %u raw-change prior-seq=%llu prior-gen=%llu"
                    " prior-hit=%u prior-key=%016llx prior-mesh=%016llx"
                    " prior-query-matches(key/lifetime)=%u/%u prior-query-id=%u"
                    " prior-to-query-rev=%llu/%llu prior-to-query-clip-world=%016llx/%016llx"
                    " new-hit=%u new-key=%016llx new-mesh=%016llx"
                    " current-gen=%llu new-current-matches(key/lifetime)=%u/%u new-current-id=%u"
                    " new-to-current-rev=%llu/%llu new-to-current-clip-world=%016llx/%016llx\n",
                    U(sequence), ray, U(last_raw.sequence), U(last_raw.generation),
                    unsigned(prior.hit), U(before.key), U(before.mesh),
                    old_in_query.matching_key, old_in_query.matching_lifetime, prior_id,
                    U(before.geometry.recorded), U(prior_revision.recorded),
                    U(before.geometry.clip_to_world), U(prior_revision.clip_to_world),
                    unsigned(current.hit), U(after.key), U(after.mesh),
                    U(CurrentGeneration()), new_in_current.matching_key, new_in_current.matching_lifetime, latest_id,
                    U(after.geometry.recorded), U(latest_revision.recorded),
                    U(after.geometry.clip_to_world), U(latest_revision.clip_to_world));
    }

    void Report(const Slot& slot, const Results& result, U64 now, U64 read_us,
                double gpu_us, const char* unavailable_now, bool origin_current) {
        const Scene& snapshot = *slot.scene;
        if (Watch() && Now() >= next_content_report) {
            next_content_report = Now() + 250;
            const auto d = CompareContent(snapshot, scene.get());
            const auto compare = [&](bool changed) {
                return !d.available || d.membership ? "unknown" : changed ? "changed" : "digest-match";
            };
            std::printf("Roof watch (t132e): content query=%llu current=%llu serial-change=%s "
                        "observed=%s membership=%s revision=%s masks=%s clip-map=%s view=%s "
                        "missing-metadata=%u/%u geometry-equivalence=unknown\n",
                        U(snapshot.serial), U(CurrentGeneration()), scene ? (d.serial_changed ? "yes" : "no") : "unknown",
                        d.Name(), !d.available ? "unknown" : d.membership ? "changed" : "digest-match",
                        compare(d.revision), compare(d.masks), compare(d.clip),
                        !d.available ? "unknown" : d.view ? "changed" : "digest-match",
                        d.missing_query, d.missing_current);
        }
        const Vec forward{snapshot.camera.view[8], snapshot.camera.view[9], snapshot.camera.view[10]};
        constexpr float Deg = 57.295779513f;
        const float yaw = std::atan2(forward[0], forward[2]) * Deg;
        const float pitch = std::asin(std::clamp(forward[1], -1.f, 1.f)) * Deg;
        const Vec delta{slot.camera[0] - slot.origin[0], slot.camera[1] - slot.origin[1],
                        slot.camera[2] - slot.origin[2]};
        const auto id = U(slot.sequence);
        const U32 count = U32(snapshot.records.size());
        const auto freshness = CompareSample(slot.ms, now, snapshot.serial, CurrentGeneration(),
                                             slot.origin, current_origin, unavailable_now != nullptr, origin_current);
        const bool stale = freshness.Any();
        const bool forward_in_time = slot.sequence > last_raw.sequence;
        const bool compare_raw = forward_in_time && last_raw.sequence &&
                                 !OriginChanged(slot.origin, last_raw.origin);
        RawSample seen_raw{.sequence = slot.sequence, .generation = snapshot.serial, .origin = slot.origin};
        std::printf("Roof probe (t132e): seq %llu frame %llu ms %llu scene %llu born-frame %llu age-ms %llu readback-ms %llu matrix=valid available=%u stale=%u\n",
                    id, U(slot.frame), U(slot.ms), U(snapshot.serial), U(snapshot.frame),
                    U(slot.ms - snapshot.ms), U(now - slot.ms), unsigned(!stale), unsigned(stale));
        std::printf("Roof probe (t132e): seq %llu query-gen=%llu current-gen=%llu last-published-gen=%llu"
                    " stale-age/scene-gen/origin/missing/unavailable=%u/%u/%u/%u/%u origin-current=%u"
                    " query/current-tlas-view=%016llx/%016llx reason=%s\n",
                    id, U(snapshot.serial), U(CurrentGeneration()), U(generation),
                    unsigned(freshness.age), unsigned(freshness.generation), unsigned(freshness.origin),
                    unsigned(freshness.scene_missing), unsigned(freshness.unavailable), unsigned(origin_current),
                    U(snapshot.tlas_view), U(scene ? scene->tlas_view : 0),
                    unavailable_now ? unavailable_now : "none");
        std::printf("Roof probe (t132e): seq %llu origin=%s (%.3f %.3f %.3f) camera (%.3f %.3f %.3f) delta %.3fm yaw %.2f pitch %.2f\n",
                    id, slot.frozen ? "frozen" : "camera", slot.origin[0], slot.origin[1], slot.origin[2],
                    slot.camera[0], slot.camera[1], slot.camera[2], std::sqrt(Dot(delta, delta)), yaw, pitch);
        const auto& c = slot.counters;
        std::printf("Roof probe (t132e): seq %llu emitted=%u current=%u held=%u requested=%u flags=%#x build/refit/reuse=%llu/%llu/%llu cap=%llu unsupported=%llu pending=%u busy=%llu\n",
                    id, count, count - snapshot.held, snapshot.held, snapshot.requested, snapshot.flags,
                    U(c.build), U(c.refit), U(c.reuse), U(c.over_budget), U(c.unsupported), Pending(), U(busy));
        std::printf("Roof probe (t132e): seq %llu emitted-palette(nz/placed/both)=%u/%u/%u"
                    " geometry-unknown=%u geometry-cap-drops=%llu\n",
                    id, snapshot.palette_nonzero, snapshot.palette_placed, snapshot.palette_both,
                    snapshot.geometry_unknown, U(revisions.Drops()));
        std::printf("Roof probe (t132e): seq %llu guards ring/view/address/dangling/moved/handle=%llu/%llu/%llu/%llu/%llu/%llu cpu-submit/read-us=%llu/%llu gpu-us=%.2f (negative=unavailable)\n",
                    id, U(c.ring_full), U(c.bad_view), U(c.no_address), U(c.dangling), U(c.moved),
                    U(c.no_handle), U(slot.submit_us), U(read_us), gpu_us);
        const auto& e = slot.exposure;
        if (e.valid) {
            std::printf("Roof probe (t132e): seq %llu exposure read-ms=%llu lift-ms=%llu observed-ms=%llu far=%.4f/%.4f open=%.4f/%.4f meter=%.6f target=%.6f indoor=%.4f wanted=%+.4f applied=%+.4f\n",
                        id, U(e.read_ms), U(e.lift_ms), U(e.observed_ms), e.far_raw, e.far_eased, e.open_raw, e.open_eased,
                        e.meter, e.target, e.indoor, e.wanted, e.applied);
        } else {
            std::printf("Roof probe (t132e): seq %llu exposure unavailable (no valid active meter reading)\n", id);
        }
        U32 hits = 0, completed = 0;
        for (U32 i = 0; i < result.size(); ++i) {
            const auto& ray = result[i];
            const Vec dir = Direction(i);
            const bool complete = Complete(ray, count);
            const char* reason = complete ? "completed" :
                ray.status == ROOF_OVERFLOW ? "candidate-cap" : ray.status == ROOF_TYPE ?
                "unsupported-type" : ray.status == ROOF_UNKNOWN ? "unknown-id" : "metadata-mismatch";
            std::printf("Roof probe (t132e): seq %llu ray %u dir=(%.6f %.6f %.6f) range %.2f..%.2f %s candidates=%u reject G/C/S/M/P=%u/%u/%u/%u/%u\n",
                        id, i, dir[0], dir[1], dir[2], double(ROOF_TMIN), double(ROOF_TMAX), reason,
                        ray.candidates, ray.rejected[0], ray.rejected[1], ray.rejected[2], ray.rejected[3], ray.rejected[4]);
            if (!complete) {
                continue;
            }
            ++completed;
            hits += ray.hit_id != ROOF_NONE;
            auto& raw = seen_raw.rays[i];
            raw.complete = true;
            raw.hit = ray.raw_id != ROOF_NONE;
            if (raw.hit) {
                raw.record = snapshot.records[ray.raw_id];
            }
            if (compare_raw) {
                ReportRawChange(slot.sequence, i, snapshot, last_raw.rays[i], raw);
            }
            const auto describe = [&](const char* kind, U32 instance_id, U32 primitive, U32 front, float t) {
                if (instance_id == ROOF_NONE) {
                    std::printf("Roof probe (t132e): seq %llu ray %u %s none-in-segment\n", id, i, kind);
                    return;
                }
                const auto& record = snapshot.records[instance_id];
                std::printf("Roof probe (t132e): seq %llu ray %u %s id=%u key=%016llx mesh=%016llx primitive=%u front=%u distance=%.4f y=%.4f flags=%#x held=%u capture-frame=%llu age-frames=%llu"
                            " palette-nz=%u palette-placed=%u blas-life=%llu geometry-rev=%llu"
                            " clip-to-world=%016llx capture-inputs=%016llx\n",
                            id, i, kind, instance_id, U(record.key), U(record.mesh), primitive, front, t,
                            slot.origin[1] + t * dir[1], record.flags, unsigned(record.held), U(record.capture_frame),
                            U(record.capture_frame && record.capture_frame <= slot.frame ? slot.frame - record.capture_frame : 0),
                            unsigned(record.palette_nonzero), unsigned(record.palette_placed),
                            U(record.geometry.lifetime), U(record.geometry.recorded),
                            U(record.geometry.clip_to_world), U(record.captured_inputs));
            };
            describe("accepted", ray.hit_id, ray.hit_primitive, ray.hit_front, ray.hit_t);
            describe("raw", ray.raw_id, ray.raw_primitive, ray.raw_front, ray.raw_t);
        }
        if (forward_in_time) {
            last_raw = seen_raw;
        }
        std::printf("Roof probe (t132e): seq %llu hits=%u completed=%u unresolved=%u hits/complete=%.4f(valid=%u) hits/9=%.4f unresolved/9=%.4f\n",
                    id, hits, completed, U32(ROOF_RAYS) - completed, completed ? float(hits) / completed : 0.f,
                    unsigned(completed != 0), float(hits) / ROOF_RAYS, float(ROOF_RAYS - completed) / ROOF_RAYS);
    }
};
} // namespace Vulkan::InteriorRoof
