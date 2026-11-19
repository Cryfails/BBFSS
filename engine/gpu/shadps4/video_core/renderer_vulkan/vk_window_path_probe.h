// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdio>
#include <cstring>
#include <optional>

#include "video_core/host_shaders/window_path_probe_comp.h"
#include "vk_effect_pass.h"
#include "vk_instance.h"
#include "vk_scheduler.h"
#include "window_path_probe.h"
#include <vk_mem_alloc.h>

namespace Vulkan::WindowPathProbe {

// Integration contract: publish the same guarded TLAS, camera and dense record order used by
// t132e, independent of whether the roof probe is enabled. Add RecordFacts at record emission;
// a registry tag alone is not a witness. Pair exact camera draw/range and used-triangle data
// with the G-buffer owner/depth observations. A shadow twin needs current range identity and
// matching world triangles. Reject unverified publications, including frozen or guard-refused
// builds. Words from an earlier readback need current revalidation before forming a Request.
//
// Call Submit from a natural consumer after the AS-build dependency. Supply a production solid
// ray (origin bias, sample direction and segment) and the measured centre/minimum for r130g.
// The core supports the plain opaque triangle consumers, not cards/alpha tracing. For Direct,
// use the exact d92266b9 draw ordinal and texture 0's receiver set. IsolatedDelta means the
// actual attachment and sample were matched before and after that draw, with blend and pass
// attribution established. If unavailable, keep the status unavailable or light-set-only.
//
// Generate window_path_probe_comp.h with add_host_shader(window_path_probe.comp
// window_path_probe_comp) and track window_path_probe_layout.h as a shader dependency.
// Poll while the caller owns the same request stamp; a changed stamp makes the result stale.
// Shutdown while the scheduler and allocator are still alive. This lane installs no hooks.

inline bool Wanted() {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_WINDOW_PATH_PROBE");
        return value && std::strcmp(value, "1") == 0;
    }();
    return enabled;
}
inline const char* Name(Status status) {
    switch (status) {
    case Status::Ready: return "ready";
    case Status::Disabled: return "disabled";
    case Status::Busy: return "both readback slots busy";
    case Status::Budget: return "bounded request cap exceeded or empty";
    case Status::MissingScene: return "no attested guarded triangle scene";
    case Status::Stale: return "stale or mismatched capture";
    case Status::Registry: return "exact window registry entry absent";
    case Status::RecordOrder: return "emitted record provenance differs";
    case Status::PaneProvenance: return "exact local pane or twin proof unavailable";
    case Status::ReceiverEvidence: return "visible receiver depth/normal unavailable";
    case Status::UnsupportedPath: return "unsupported or invalid consumer segment";
    case Status::Readback: return "probe resource or readback unavailable";
    }
    return "unknown";
}

struct Completion {
    Status status = Status::Readback;
    std::unique_ptr<Packet> packet;
    std::array<Result, WP_SEGMENTS> rays{};
};

class Probe {
public:
    Probe(const Instance& instance, Scheduler& scheduler) : instance(instance), scheduler(scheduler) {}
    ~Probe() {
        if (buffers && std::ranges::any_of(slots, [&](const Slot& slot) {
                return slot.tick && !scheduler.IsFree(slot.tick);
            })) {
            scheduler.DeferOperation([keep = std::move(buffers)]() mutable { keep.reset(); },
                                     "window path probe buffers");
        }
    }

    Status Submit(vk::AccelerationStructureKHR tlas, const Request& request,
                  const GlassRegistryRules::Table& table) {
        if (!Wanted()) {
            return Status::Disabled;
        }
        const U64 request_id = request.publication.stamp.request;
        if (!request_id || request_id <= last_request) {
            return Status::Stale;
        }
        last_request = request_id; // one shot, including explicit refusals
        if (!tlas) {
            return Status::MissingScene;
        }
        if (failed) {
            return Status::Readback;
        }
        auto slot = Roof::FreeSlot(slots);
        if (slot == slots.end()) {
            ++busy;
            return Status::Busy;
        }
        auto packet = std::make_unique<Packet>();
        if (const Status status = Prepare(request, table, *packet); status != Status::Ready) {
            return status;
        }
        if (!buffers && !Make()) {
            failed = true;
            return Status::Readback;
        }
        const U32 index = U32(slot - slots.begin());
        const auto& in = buffers->input[index];
        const auto& out = buffers->output[index];
        std::memcpy(in.mapped, &packet->gpu, sizeof(GpuInput));
        if (vmaFlushAllocation(buffers->allocator, in.memory, 0, sizeof(GpuInput)) != VK_SUCCESS) {
            failed = true;
            return Status::Readback;
        }
        const Push push = packet->counts;
        scheduler.EndRendering();
        scheduler.RecordCrumb({.name = "Window path probe (three visibility queries)"},
            [tlas, input = in.handle, output = out.handle, push,
             pipeline = *buffers->pipeline, layout = *buffers->layout](vk::CommandBuffer cmd) {
                constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
                constexpr auto Build = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;
                constexpr auto Read = vk::AccessFlagBits2::eAccelerationStructureReadKHR;
                constexpr auto Write = vk::AccessFlagBits2::eAccelerationStructureWriteKHR;
                EffectPass::MemoryBarrier(cmd, Build, Write, Compute, Read);
                const vk::WriteDescriptorSetAccelerationStructureKHR as{
                    .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
                const vk::DescriptorBufferInfo input_info{input, 0, sizeof(GpuInput)};
                const vk::DescriptorBufferInfo output_info{output, 0, sizeof(Result) * WP_SEGMENTS};
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.pNext = &as, .dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &input_info},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &output_info},
                }};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
                cmd.dispatch((push.segments + 7) / 8, 1, 1);
                EffectPass::MemoryBarrier(cmd, Compute, Read, Build, Write);
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
            });
        slot->tick = scheduler.CurrentTick();
        slot->packet = std::move(packet);
        return Status::Ready;
    }

    std::optional<Completion> Poll(Stamp expected) {
        if (!buffers) {
            return std::nullopt;
        }
        for (U32 i = 0; i < slots.size(); ++i) {
            auto& slot = slots[i];
            if (!Roof::Ready(slot.tick, [&](U64 tick) { return scheduler.IsFree(tick); })) {
                continue;
            }
            Completion completed;
            completed.packet = std::move(slot.packet);
            slot.tick = 0;
            if (expected != completed.packet->stamp) {
                completed.status = Status::Stale;
                return completed;
            }
            const auto& out = buffers->output[i];
            const auto bytes = completed.packet->counts.segments * sizeof(Result);
            if (vmaInvalidateAllocation(buffers->allocator, out.memory, 0, bytes) != VK_SUCCESS) {
                failed = true;
                return completed;
            }
            std::memcpy(completed.rays.data(), out.mapped, bytes);
            completed.status = Status::Ready;
            return completed;
        }
        return std::nullopt;
    }

    U64 BusyCount() const { return busy; }

private:
    static constexpr U32 Slots = 2;
    struct Slot { U64 tick = 0; std::unique_ptr<Packet> packet; };
    struct Buffer {
        vk::Buffer handle{};
        VmaAllocation memory{};
        void* mapped = nullptr;
    };
    struct Resources {
        VmaAllocator allocator;
        vk::UniqueDescriptorSetLayout set;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
        std::array<Buffer, Slots> input{}, output{};

        ~Resources() {
            for (const auto* bank : {&input, &output}) {
                for (const auto& buffer : *bank) {
                    if (buffer.handle) {
                        vmaDestroyBuffer(allocator, buffer.handle, buffer.memory);
                    }
                }
            }
        }

        bool MakeBuffer(Buffer& buffer, size_t bytes, VmaAllocationCreateFlags access) const {
            const VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                .size = bytes, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
            const VmaAllocationCreateInfo memory{
                .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | access, .usage = VMA_MEMORY_USAGE_AUTO};
            VkBuffer raw{};
            VmaAllocationInfo allocated{};
            if (vmaCreateBuffer(allocator, &info, &memory, &raw, &buffer.memory, &allocated) != VK_SUCCESS) {
                return false;
            }
            buffer.handle = raw;
            buffer.mapped = allocated.pMappedData;
            return buffer.mapped != nullptr;
        }
    };
    const Instance& instance;
    Scheduler& scheduler;
    std::unique_ptr<Resources> buffers;
    std::array<Slot, Slots> slots{};
    U64 last_request = 0, busy = 0;
    bool failed = false;

    bool Make() {
        auto next = std::make_unique<Resources>();
        next->allocator = instance.GetAllocator();
        using Type = vk::DescriptorType;
        if (!instance.IsRayQuerySupported() ||
            !EffectPass::Create(instance, next->set, next->layout, next->pipeline,
                {Type::eAccelerationStructureKHR, Type::eStorageBuffer, Type::eStorageBuffer},
                sizeof(Push), WINDOW_PATH_PROBE_COMP, "Window path probe")) {
            return false;
        }
        for (U32 i = 0; i < Slots; ++i) {
            if (!next->MakeBuffer(next->input[i], sizeof(GpuInput), VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT) ||
                !next->MakeBuffer(next->output[i], sizeof(Result) * WP_SEGMENTS, VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT)) {
                return false;
            }
        }
        buffers = std::move(next);
        return true;
    }
};

inline const char* GeometryName(Geometry geometry) {
    switch (geometry) {
    case Geometry::Unresolved: return "unresolved";
    case Geometry::NoSelectedCrossing: return "no witnessed crossing";
    case Geometry::ClearBeforeSkip: return "already clear";
    case Geometry::StillBlocked: return "still blocked";
    case Geometry::Opened: return "opened in pane-skipped query";
    }
    return "unresolved";
}
inline const char* DirectName(DirectKind kind) {
    switch (kind) {
    case DirectKind::Unavailable: return "unavailable";
    case DirectKind::LightSetOnly: return "light set only";
    case DirectKind::IsolatedDelta: return "isolated draw delta";
    }
    return "unavailable";
}

// One bounded report on completion. Raw ray statuses retain cap/unknown failures even when
// the combined geometry verdict is unresolved. The caller reports failed Submit statuses once.
inline void Report(const Completion& completion) {
    if (!completion.packet) {
        return;
    }
    const Packet& p = *completion.packet;
    const auto u = [](U64 value) { return static_cast<unsigned long long>(value); };
    std::printf("Window path (t132f): req=%llu frame=%llu generation=%llu camera=%llu depth=%llu %s "
                "entry=%u %llx:%llx idx=%u first=%u segments=%u\n",
                u(p.stamp.request), u(p.stamp.frame), u(p.stamp.generation), u(p.stamp.camera),
                u(p.stamp.depth_uid), Name(completion.status), p.registry, u(p.exact.vs), u(p.exact.ps),
                p.exact.count, p.exact.first, p.counts.segments);
    if (completion.status != Status::Ready) {
        return;
    }
    for (const auto& s : std::span(p.gpu.selected).first(p.counts.selected)) {
        const auto& record = p.scene->records[s.info[0]];
        std::printf("Window path (t132f): req=%llu selected-record=%u camera-record=%u key=%016llx "
                    "captured=%llu entry=%u tag=%u\n",
                    u(p.stamp.request), s.info[0], s.info[1], u(record.key),
                    u(record.capture_frame), s.info[2], s.info[3]);
    }
    for (U32 i = 0; i < p.counts.segments; ++i) {
        const auto& segment = p.segments[i];
        const auto& receiver = p.receivers[segment.receiver];
        const auto& r = completion.rays[i];
        const auto e = Resolve(p, i, r, p.stamp);
        std::printf("Window path (t132f): req=%llu segment=%u receiver=%u px=%u,%u "
                    "world=%.4f,%.4f,%.4f normal=%.4f,%.4f,%.4f owner=%llx prim=%u geometry=%s\n",
                    u(p.stamp.request), i, segment.receiver, receiver.x, receiver.y,
                    receiver.world[0], receiver.world[1], receiver.world[2],
                    receiver.normal[0], receiver.normal[1], receiver.normal[2],
                    u(receiver.owner_key), receiver.surface.primitive, GeometryName(e.geometry));
        const auto& pane = p.pane_rays[i];
        std::printf("Window path (t132f): req=%llu segment=%u %s source=%u (%.4f %.4f %.4f) range=%.3f "
                    "rgb=%.4f/%.4f/%.4f solid=%.4f..%.4f pane=%.4f..%.4f\n",
                    u(p.stamp.request), i, segment.path == Path::SunOpaque ? "sun-direction" : "lamp-centre",
                    segment.light, segment.source[0], segment.source[1], segment.source[2], segment.range,
                    segment.rgb[0], segment.rgb[1], segment.rgb[2], segment.solid.minimum, segment.solid.maximum,
                    pane.minimum, pane.maximum);
        const auto line = [&](const char* label, const Hit& hit, const Ray& ray, U32 mask, U32 mode) {
            if (!MatchHit(p, hit, ray, mask, mode) || hit.id == WP_NONE) {
                std::printf("Window path (t132f): req=%llu segment=%u %s %s status=%u candidates=%u mask=%#x\n",
                            u(p.stamp.request), i, label, MatchHit(p, hit, ray, mask, mode) ? "miss" : "unresolved",
                            hit.status, hit.looked, mask);
                return;
            }
            const auto& record = p.scene->records[hit.id];
            const auto world = At(ray, hit.distance);
            std::printf("Window path (t132f): req=%llu segment=%u %s id=%u key=%016llx prim=%u custom=%#x "
                        "mask=%#x front=%u t=%.5f xyz=%.4f,%.4f,%.4f captured=%llu candidates=%u\n",
                        u(p.stamp.request), i, label, hit.id, u(record.key), hit.primitive, hit.custom,
                        record.flags & 0xffu, hit.front, hit.distance, world[0], world[1], world[2],
                        u(record.capture_frame), hit.looked);
        };
        const auto& masks = p.gpu.segments[i].masks;
        line("pane", r.pane, pane, masks[1], WP_PANE);
        line("actual", r.actual, segment.solid, masks[0], WP_ACTUAL);
        line("pane-skipped", r.skipped, segment.solid, masks[0], WP_SKIP);
        if (segment.path == Path::SunOpaque) {
            const auto& d = receiver.direct;
            std::printf("Window path (t132f): req=%llu segment=%u directional-evidence=%s "
                        "set=%u draw=%llu output=%llu delta=%.6f/%.6f/%.6f\n",
                        u(p.stamp.request), i, DirectName(e.direct),
                        e.direct == DirectKind::Unavailable ? WP_NONE : d.light_set,
                        u(d.draw), u(d.output_uid), e.delta[0], e.delta[1], e.delta[2]);
        }
    }
}

} // namespace Vulkan::WindowPathProbe
