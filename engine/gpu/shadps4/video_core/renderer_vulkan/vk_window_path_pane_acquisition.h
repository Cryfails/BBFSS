// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "vk_instance.h"
#include "vk_scheduler.h"
#include "window_path_witness.h"
#include "window_pane_stages.h"
#include "window_pane_natural.h"
#include "vk_lamp_pane_probe.h"
#include "window_pane_owner.h"
#include <bit>
#include <cstdio>
#include <cstdlib>

#include <vk_mem_alloc.h>

namespace Vulkan::WindowPathProbe {

// Exact registry draw already measured by the window task. The runtime still
// requires the active registry entry and the exact submitted index range.
inline constexpr DrawKey WindowPaneDrawKey{0x97f2d384, 0x2390c887, 246, 0};

// t132f TEST-ONLY: one log record for each kind during a pane owner request.
enum class PaneOwnerGap : u8 {
    FastClear = 1 << 0,
    Dispatch = 1 << 1,
    DispatchIndirect = 1 << 2,
    Resolve = 1 << 3,
    DepthStencilCopy = 1 << 4,
    NonresidentTarget = 1 << 5,
    DrawCap = 1 << 6,
};

struct PaneOwnerAcquisition {
    PaneOwnerAcquisition(const Instance& instance, Scheduler& scheduler)
        : instance(instance), scheduler(scheduler) {}

    ~PaneOwnerAcquisition() {
        if (!buffer) return;
        const auto destroy = [allocator = instance.GetAllocator(), buffer = buffer, allocation = allocation] {
            vmaDestroyBuffer(allocator, buffer, allocation);
        };
        if ((final_tick && !scheduler.IsFree(final_tick)) ||
            !material.phases.Retired([&](u64 tick) { return scheduler.IsFree(tick); })) {
            scheduler.DeferOperation(destroy, "window pane owner texels");
        } else {
            destroy();
        }
    }

    bool Allocate() {
        if (buffer) return mapped != nullptr;
        const VkBufferCreateInfo ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = RawFinalAlbedo + RtLampPane::MaterialTexelBytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) {
            return false;
        }
        mapped = static_cast<const std::byte*>(info.pMappedData);
        return mapped != nullptr;
    }

    bool Ready() const {
        return final_tick && scheduler.IsFree(final_tick) &&
               material.phases.Retired([&](u64 tick) { return scheduler.IsFree(tick); });
    }

    bool Read(OwnerTexel& a, OwnerTexel& b, u32& final_albedo) const {
        using namespace RtLampPane;
        if (!Ready() || !mapped ||
            vmaInvalidateAllocation(instance.GetAllocator(), allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            return false;
        }
        const auto read = [&](u32 offset, u32& value) { std::memcpy(&value, mapped + offset, sizeof(value)); };
        read(MaterialOffset(MaterialPhase::Before, RawAlbedo, 0), a.albedo);
        read(MaterialOffset(MaterialPhase::Before, RawDepth, 0), a.depth);
        read(MaterialOffset(MaterialPhase::After, RawAlbedo, 0), b.albedo);
        read(MaterialOffset(MaterialPhase::After, RawDepth, 0), b.depth);
        read(RawFinalAlbedo, final_albedo);
        return true;
    }

    const Instance& instance;
    Scheduler& scheduler;
    LampMaterialState material;
    RtLampPane::Identity stamp;
    VkBuffer buffer{};
    VmaAllocation allocation{};
    const std::byte* mapped = nullptr;
    u64 final_tick = 0, final_depth_tick = 0, directional = 0;
    std::array<u64, 2> after_writes{}, final_writes{};
    u32 draws_before = 0, draws_after = 0, first_writer = 0;
    u8 logged_gap_kinds = 0;
    bool coverage_gap = false, later_clear = false, reported = false;
};

struct PaneAcquisition {
    PaneAcquisition(const Instance& instance, Scheduler& scheduler)
        : instance(instance), scheduler(scheduler) {}
    PaneAcquisition(const PaneAcquisition&) = delete;
    PaneAcquisition& operator=(const PaneAcquisition&) = delete;

    ~PaneAcquisition() {
        if (buffer) {
            const auto allocator = instance.GetAllocator();
            if (tick && !scheduler.IsFree(tick)) {
                scheduler.DeferOperation([allocator, buffer = buffer, allocation = allocation] {
                    vmaDestroyBuffer(allocator, buffer, allocation);
                }, "window pane positions");
            } else {
                vmaDestroyBuffer(allocator, buffer, allocation);
            }
        }
    }

    bool Allocate() {
        if (buffer) {
            return true;
        }
        const VkBufferCreateInfo ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = WorldBytes(),
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS ||
            !info.pMappedData) {
            Refuse("world readback allocation");
            return false;
        }
        mapped = static_cast<const float*>(info.pMappedData);
        return true;
    }

    void Refuse(const char* why) {
        refusal = why;
        stages.Refuse(why, source_frame, rt_frame);
    }
    bool CanSample(u64 request, u64 object_frame, u64 rt_frame, u32 frame_budget) const {
        return !natural.Active() || (!refusal && natural.CanSample(request, object_frame, rt_frame) &&
            !natural.Expired(object_frame, frame_budget, NaturalPanePair::Clock::now()));
    }
    bool SameSampleState(u64 uid, const RtLampPane::Camera& matrices, const std::array<float, 2>& sample_jitter) const {
        return !natural.Active() || (depth_uid == uid && camera == matrices && jitter == sample_jitter);
    }
    u64 WorldBytes() const { return u64(vertices) * instances * 16; }
    bool Ready() const { return tick && scheduler.IsFree(tick); }
    std::span<const float> Read() const {
        if (!Ready() || vmaInvalidateAllocation(instance.GetAllocator(), allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            return {};
        }
        const std::span<const float> world{mapped, size_t(WorldBytes() / sizeof(float))};
        ExportWorld(world);
        return world;
    }

private:
    void ExportWorld(std::span<const float> world) const {
        static const bool enabled = [] {
            const char* value = std::getenv("BB_WINDOW_PATH_EXPORT");
            return value && value[0] == '1' && value[1] == '\0';
        }();
        constexpr u32 corner_count = WindowPaneDrawKey.count;
        const auto& build = natural.build;
        if (!enabled || exported || refusal || !natural.Active() || !natural.sampled ||
            build.object_frame != source_frame || !natural.MatchBuild(rt_frame, param, build.ordinal, key) ||
            !depth_uid || instances != 1 || triangles != corner_count / 3 ||
            !vertices || vertices > PaneVerticesMost || world.size() != size_t(vertices) * 4) {
            return;
        }
        const std::span<const u32> corners{indices.data(), corner_count};
        const auto word = [&](u32 index, u32 axis) {
            return std::bit_cast<u32>(world[size_t(index) * 4 + axis]);
        };
        for (const u32 index : corners) {
            if (index >= vertices) {
                return;
            }
            for (u32 axis = 0; axis < 3; ++axis) {
                // IEEE-754 exponent 255 is reserved for infinities and NaNs.
                if ((word(index, axis) & 0x7f800000u) == 0x7f800000u) {
                    return;
                }
            }
        }

        // These are ordered corners from the ordinary build's host index copy.
        exported = true;
        const auto u = [](u64 value) { return static_cast<unsigned long long>(value); };
        std::printf("Window pane export (t173): begin req=%llu obj=%llu rt=%llu param=%u build=%u tick=%llu "
                    "entry=%016llx base=%016llx new_entry=%u depth_uid=%llu pair=%08x:%08x count=%u first=%u "
                    "vertices=%u instances=%u triangles=%u\n",
                    u(natural.request), u(source_frame), u(rt_frame), param, build.ordinal, u(tick),
                    u(build.entry), u(build.base), unsigned(build.new_entry), u(depth_uid), u32(WindowPaneDrawKey.vs),
                    u32(WindowPaneDrawKey.ps), corner_count, WindowPaneDrawKey.first, vertices, instances, triangles);
        for (u32 ordered = 0; ordered < corner_count; ++ordered) {
            const u32 index = corners[ordered];
            std::printf("Window pane export (t173): corner req=%llu tri=%u corner=%u index=%u xyz=%08x,%08x,%08x\n",
                        u(natural.request), ordered / 3, ordered % 3, index,
                        word(index, 0), word(index, 1), word(index, 2));
        }
        std::printf("Window pane export (t173): end req=%llu corners=%u\n", u(natural.request), corner_count);
    }

    mutable bool exported = false;

public:
    const Instance& instance;
    Scheduler& scheduler;
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const float* mapped = nullptr;
    u64 tick = 0, rt_frame = 0, source_frame = 0, depth_uid = 0, key = 0;
    u32 param = 0, vertices = 0, instances = 0, triangles = 0, draw_count = 0;
    RtLampPane::Camera camera{};
    std::array<float, 2> jitter{};
    std::array<u32, WP_TRI_WORDS * 32 * 3> indices{};
    const char* refusal = nullptr;
    std::unique_ptr<PaneOwnerAcquisition> owner;
    PaneStages stages;
    NaturalPanePair natural;
};

} // namespace Vulkan::WindowPathProbe

