// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cstdio>
#include <span>
#include <vector>

#include "shader_recompiler/info.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_frame_capture.h"
#include "video_core/renderer_vulkan/vk_shader_hle.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/host_shaders/buffer_multi_copy_comp.h"
#include "bbport_sections.h"
#include "bbport_toggles.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "video_core/renderer_vulkan/vk_gpu_savings.h"
#include "video_core/texture_cache/texture_cache.h"

extern std::unique_ptr<AmdGpu::Liverpool> liverpool;

namespace Vulkan {

static constexpr u64 COPY_SHADER_HASH = 0xfefebf9f;
static constexpr u64 RT_COPY_SHADER_HASH = 0x3d5ebf4e;

/// A range of each buffer a batch reads or writes (barrier checks and access tracking).
struct AccessRange {
    u64 src_min, src_max, dst_min, dst_max;
};

// bbport: the copy shader runs ~57 times per frame with ~1024 small ranges each. As one
// vkCmdCopyBuffer with that many regions it cost ~37 ns of GPU time per range (~2.1 ms per
// frame) plus the recording; buffer_multi_copy.comp copies all ranges in one dispatch.
/// `ranges`: the batches merged into this dispatch (BB_HLE_COPY_MERGE), each checked and
/// tracked on its own; empty: the bounds of all the copies, as one batch.
static bool MultiCopy(Rasterizer& rasterizer, const VideoCore::Buffer* src,
                      const VideoCore::Buffer* dst, std::span<const vk::BufferCopy> copies,
                      std::span<const AccessRange> ranges = {}) {
    if (copies.size() < 8 || BbToggle::Disabled(BbToggle::MultiCopyShader)) {
        return false;
    }
    u64 src_min = ~0ull, src_max = 0, dst_min = ~0ull, dst_max = 0;
    for (const auto& copy : copies) {
        if ((copy.srcOffset | copy.dstOffset | copy.size) & 3) {
            return false; // dword copies only
        }
        src_min = std::min(src_min, copy.srcOffset);
        src_max = std::max(src_max, copy.srcOffset + copy.size);
        dst_min = std::min(dst_min, copy.dstOffset);
        dst_max = std::max(dst_max, copy.dstOffset + copy.size);
    }
    auto& runtime = rasterizer.GetRuntime();
    auto& scheduler = runtime.GetScheduler();
    const auto& instance = runtime.GetInstance();
    const u64 align = instance.StorageMinAlignment();
    src_min = Common::AlignDown(src_min, align);
    dst_min = Common::AlignDown(dst_min, align);
    // Merged batches may span more than a descriptor or a dispatch can hold.
    if (!ranges.empty() &&
        (src_max - src_min > instance.MaxStorageBufferRange() ||
         dst_max - dst_min > instance.MaxStorageBufferRange() ||
         copies.size() > instance.MaxComputeWorkGroupCountX())) {
        return false;
    }

    struct Pipeline {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    static Pipeline pipe = [&] {
        const auto device = instance.GetDevice();
        Pipeline p;
        std::array<vk::DescriptorSetLayoutBinding, 3> bindings{};
        for (u32 i = 0; i < 3; ++i) {
            bindings[i] = {.binding = i,
                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                           .descriptorCount = 1,
                           .stageFlags = vk::ShaderStageFlagBits::eCompute};
        }
        p.set_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = static_cast<u32>(bindings.size()),
            .pBindings = bindings.data(),
        }));
        const vk::PushConstantRange range{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                          .offset = 0,
                                          .size = sizeof(u32)};
        p.layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1,
            .pSetLayouts = &*p.set_layout,
            .pushConstantRangeCount = 1,
            .pPushConstantRanges = &range,
        }));
        const auto module = CompileSPV(BUFFER_MULTI_COPY_COMP, device);
        p.pipeline = Check(device.createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{
                    .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                              .module = module,
                              .pName = "main"},
                    .layout = *p.layout,
                }));
        device.destroyShaderModule(module);
        return p;
    }();

    // The region table goes into the stream buffer (host writes, visible at submission).
    thread_local std::vector<u32> regions;
    regions.resize(copies.size() * 4);
    for (size_t i = 0; i < copies.size(); ++i) {
        regions[i * 4 + 0] = static_cast<u32>((copies[i].srcOffset - src_min) / 4);
        regions[i * 4 + 1] = static_cast<u32>((copies[i].dstOffset - dst_min) / 4);
        regions[i * 4 + 2] = static_cast<u32>(copies[i].size / 4);
        regions[i * 4 + 3] = 0;
    }
    auto& stream = rasterizer.GetBufferCache().GetStreamBuffer();
    const u64 table_size = regions.size() * sizeof(u32);
    const u64 table_offset = stream.Copy(regions.data(), table_size, align);

    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0xC0B1ull, [] { return std::string{"copy shader HLE: barrier + dispatch"}; });
    }
    scheduler.EndRendering();
    const u64 src_size = src_max - src_min, dst_size = dst_max - dst_min;
    auto& savings = GpuSavings::Get();
    savings.hle_dispatches.fetch_add(1, std::memory_order_relaxed);
    bool flush = false;
    if (ranges.empty()) {
        flush = runtime.IsBufferAccessed(src, src_min, src_size) ||
                runtime.IsBufferAccessed(dst, dst_min, dst_size, true);
    } else {
        // The batches of one guest dispatch run unordered on the hardware too: one barrier
        // before all of them, for what came before.
        for (const auto& r : ranges) {
            if (runtime.IsBufferAccessed(src, r.src_min, r.src_max - r.src_min) ||
                runtime.IsBufferAccessed(dst, r.dst_min, r.dst_max - r.dst_min, true)) {
                flush = true;
                break;
            }
        }
    }
    if (flush) {
        savings.hle_barriers.fetch_add(1, std::memory_order_relaxed);
        runtime.FlushBarriers();
    }
    const u32 count = static_cast<u32>(copies.size());
    scheduler.RecordCrumb({.name = "HLE copy shader"}, [src = src->Handle(), dst = dst->Handle(), table = stream.Handle(), src_min,
                      src_size, dst_min, dst_size, table_offset, table_size,
                      count](vk::CommandBuffer cmdbuf) {
        const std::array<vk::DescriptorBufferInfo, 3> infos{{
            {src, src_min, src_size},
            {dst, dst_min, dst_size},
            {table, table_offset, table_size},
        }};
        std::array<vk::WriteDescriptorSet, 3> writes{};
        for (u32 i = 0; i < 3; ++i) {
            writes[i] = {.dstBinding = i,
                         .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &infos[i]};
        }
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *pipe.pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *pipe.layout, 0, writes);
        cmdbuf.pushConstants(*pipe.layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(count),
                             &count);
        cmdbuf.dispatch(count, 1, 1);
    });
    if (ranges.empty()) {
        runtime.AccessBuffer(src, src_min, src_size, vk::PipelineStageFlagBits2::eComputeShader,
                             vk::AccessFlagBits2::eShaderRead);
        runtime.AccessBuffer(dst, dst_min, dst_size, vk::PipelineStageFlagBits2::eComputeShader,
                             vk::AccessFlagBits2::eShaderWrite);
        return true;
    }
    for (const auto& r : ranges) {
        runtime.AccessBuffer(src, r.src_min, r.src_max - r.src_min,
                             vk::PipelineStageFlagBits2::eComputeShader,
                             vk::AccessFlagBits2::eShaderRead);
        runtime.AccessBuffer(dst, r.dst_min, r.dst_max - r.dst_min,
                             vk::PipelineStageFlagBits2::eComputeShader,
                             vk::AccessFlagBits2::eShaderWrite);
    }
    return true;
}

namespace {
/// One batch of the copy shader's ranges: the end of its ranges and their bounds.
struct CopyBatch {
    u32 end;
    vk::DeviceSize src_min, src_max, dst_min, dst_max;
};

/// The batches of the greedy merge: consecutive ranges while both their source and their
/// destination bounds stay within `max_distance` bytes.
void FindBatches(std::span<const vk::BufferCopy> copies, vk::DeviceSize max_distance,
                 std::vector<CopyBatch>& batches) {
    batches.clear();
    for (u32 i = 0; i < copies.size();) {
        CopyBatch batch{0, copies[i].srcOffset, copies[i].srcOffset + copies[i].size,
                        copies[i].dstOffset, copies[i].dstOffset + copies[i].size};
        for (++i; i < copies.size(); ++i) {
            const auto& [src_offset, dst_offset, size] = copies[i];
            const auto src_min = std::min(batch.src_min, src_offset);
            const auto src_max = std::max(batch.src_max, src_offset + size);
            if (src_max - src_min > max_distance) {
                break;
            }
            const auto dst_min = std::min(batch.dst_min, dst_offset);
            const auto dst_max = std::max(batch.dst_max, dst_offset + size);
            if (dst_max - dst_min > max_distance) {
                break;
            }
            batch = {0, src_min, src_max, dst_min, dst_max};
        }
        batch.end = i;
        batches.push_back(batch);
    }
}

/// bbport: the guest lists its ranges in its own order and batches merge only neighbours in it,
/// so a shuffled list takes a batch (two ObtainBuffer calls and a dispatch) per few ranges.
/// `grouped` gets them by destination window of 2^window_shift bytes (windows in order of first
/// appearance, the guest's order within each). False, and nothing reordered, when that could
/// change the result: source and destination overlap in guest memory, or a range crosses a
/// window (ranges that may overlap then share a window and keep their order). The hardware runs
/// the ranges as unordered threads of one dispatch anyway.
bool GroupByDestination(std::span<const vk::BufferCopy> copies, u32 window_shift, VAddr src_base,
                        VAddr dst_base, std::vector<vk::BufferCopy>& grouped) {
    constexpr u32 Slots = 512;
    constexpr u32 MaxGroups = 256;
    std::array<u64, Slots> windows;
    windows.fill(~0ull);
    std::array<u16, Slots> ids;
    std::array<u32, MaxGroups + 1> starts{};
    thread_local std::vector<u16> group_of;
    group_of.resize(copies.size());
    u32 groups = 0;
    u64 last_window = ~0ull;
    u16 last_id = 0;
    vk::DeviceSize src_min = ~0ull, src_max = 0, dst_min = ~0ull, dst_max = 0;
    for (u32 i = 0; i < copies.size(); ++i) {
        const auto& [src_offset, dst_offset, size] = copies[i];
        const u64 window = dst_offset >> window_shift;
        if (((dst_offset + size - 1) >> window_shift) != window) {
            return false;
        }
        src_min = std::min(src_min, src_offset);
        src_max = std::max(src_max, src_offset + size);
        dst_min = std::min(dst_min, dst_offset);
        dst_max = std::max(dst_max, dst_offset + size);
        if (window != last_window) {
            u32 slot = static_cast<u32>((window * 0x9E3779B97F4A7C15ull) >> 55);
            while (windows[slot] != ~0ull && windows[slot] != window) {
                slot = (slot + 1) & (Slots - 1);
            }
            if (windows[slot] == ~0ull) {
                if (groups == MaxGroups) {
                    return false;
                }
                windows[slot] = window;
                ids[slot] = static_cast<u16>(groups++);
            }
            last_window = window;
            last_id = ids[slot];
        }
        group_of[i] = last_id;
        ++starts[last_id + 1];
    }
    if (groups < 2 ||
        (src_base + src_min < dst_base + dst_max && dst_base + dst_min < src_base + src_max)) {
        return false;
    }
    for (u32 g = 1; g <= groups; ++g) {
        starts[g] += starts[g - 1];
    }
    grouped.resize(copies.size());
    for (u32 i = 0; i < copies.size(); ++i) {
        grouped[starts[group_of[i]]++] = copies[i];
    }
    return true;
}
/// bbport (BB_HLE_COPY_MERGE): whether ranges of two different batches write the same bytes.
/// Batch after batch, the later one's bytes won; in one dispatch the order would be lost.
bool DestinationsShared(std::span<const vk::BufferCopy> copies,
                        std::span<const CopyBatch> batches) {
    // Cheap first: batches whose destination bounds are disjoint share nothing.
    bool bounds_overlap = false;
    for (size_t i = 0; i < batches.size() && !bounds_overlap; ++i) {
        for (size_t j = i + 1; j < batches.size(); ++j) {
            if (batches[i].dst_min < batches[j].dst_max && batches[j].dst_min < batches[i].dst_max) {
                bounds_overlap = true;
                break;
            }
        }
    }
    if (!bounds_overlap) {
        return false;
    }
    struct Interval {
        vk::DeviceSize begin, end;
        u32 batch;
    };
    thread_local std::vector<Interval> intervals;
    intervals.clear();
    u32 start = 0;
    for (u32 b = 0; b < batches.size(); ++b) {
        for (u32 i = start; i < batches[b].end; ++i) {
            intervals.push_back({copies[i].dstOffset, copies[i].dstOffset + copies[i].size, b});
        }
        start = batches[b].end;
    }
    std::sort(intervals.begin(), intervals.end(),
              [](const Interval& a, const Interval& b) { return a.begin < b.begin; });
    // Sweep: the furthest end so far and its batch, and whether two batches reach it.
    vk::DeviceSize reach = 0;
    u32 reach_batch = 0;
    bool any = false;
    for (const auto& interval : intervals) {
        if (any && interval.begin < reach && interval.batch != reach_batch) {
            return true;
        }
        if (!any || interval.end > reach) {
            // A longer interval of another batch hides the one before; both were checked
            // against everything before them.
            reach = interval.end;
            reach_batch = interval.batch;
            any = true;
        }
    }
    return false;
}

/// bbport (BB_HLE_COPY_MERGE): whether the batches must stay apart: a source range overlaps a
/// destination range in guest memory, or two batches write the same bytes.
bool MergeUnsafe(std::span<const vk::BufferCopy> copies, std::span<const CopyBatch> batches,
                 VAddr src_base, VAddr dst_base) {
    vk::DeviceSize src_lo = ~0ull, src_hi = 0, dst_lo = ~0ull, dst_hi = 0;
    for (const auto& batch : batches) {
        src_lo = std::min(src_lo, batch.src_min);
        src_hi = std::max(src_hi, batch.src_max);
        dst_lo = std::min(dst_lo, batch.dst_min);
        dst_hi = std::max(dst_hi, batch.dst_max);
    }
    return (src_base + src_lo < dst_base + dst_hi && dst_base + dst_lo < src_base + src_hi) ||
           DestinationsShared(copies, batches);
}
} // namespace

/// bbport (BB_FRAME_STATS): whether Runtime::CopyBuffer flushes barriers before these copies (its
/// own test, repeated; IsBufferAccessed changes nothing).
static bool CopyWouldFlush(Runtime& runtime, const VideoCore::Buffer* src,
                           const VideoCore::Buffer* dst, std::span<const vk::BufferCopy> copies) {
    if (copies.size() > 4) {
        u64 src_min = ~0ULL, src_max = 0, dst_min = ~0ULL, dst_max = 0;
        for (const auto& copy : copies) {
            src_min = std::min<u64>(src_min, copy.srcOffset);
            src_max = std::max<u64>(src_max, copy.srcOffset + copy.size);
            dst_min = std::min<u64>(dst_min, copy.dstOffset);
            dst_max = std::max<u64>(dst_max, copy.dstOffset + copy.size);
        }
        return runtime.IsBufferAccessed(src, src_min, src_max - src_min) ||
               runtime.IsBufferAccessed(dst, dst_min, dst_max - dst_min, true);
    }
    for (const auto& copy : copies) {
        if (runtime.IsBufferAccessed(src, copy.srcOffset, copy.size) ||
            runtime.IsBufferAccessed(dst, copy.dstOffset, copy.size, true)) {
            return true;
        }
    }
    return false;
}

static bool ExecuteCopyShaderHLE(const Shader::Info& info, const AmdGpu::ComputeProgram& cs_program,
                                 Rasterizer& rasterizer) {
    auto& runtime = rasterizer.GetRuntime();
    auto& buffer_cache = rasterizer.GetBufferCache();
    BbSections::Scope batch_scope{BbSections::HleBatch};

    // Copy shader defines three formatted buffers as inputs: control, source, and destination.
    const auto ctl_buf_sharp = info.buffers[0].GetSharp(info);
    const auto src_buf_sharp = info.buffers[1].GetSharp(info);
    const auto dst_buf_sharp = info.buffers[2].GetSharp(info);
    const auto buf_stride = src_buf_sharp.GetStride();
    ASSERT(buf_stride == dst_buf_sharp.GetStride());

    struct CopyShaderControl {
        u32 dst_idx;
        u32 src_idx;
        u32 end;
    };
    static_assert(sizeof(CopyShaderControl) == 12);
    ASSERT(ctl_buf_sharp.GetStride() == sizeof(CopyShaderControl));
    const auto ctl_buf = reinterpret_cast<const CopyShaderControl*>(ctl_buf_sharp.base_address);

    static std::vector<vk::BufferCopy> copies;
    copies.clear();
    copies.reserve(cs_program.dim_x);

    for (u32 i = 0; i < cs_program.dim_x; i++) {
        const auto& [dst_idx, src_idx, end] = ctl_buf[i];
        const u32 local_dst_offset = dst_idx * buf_stride;
        const u32 local_src_offset = src_idx * buf_stride;
        const u32 local_size = (end + 1) * buf_stride;
        copies.emplace_back(local_src_offset, local_dst_offset, local_size);
    }

    // bbport: 64 KiB instead of 64 MiB. The copies are a few KiB spread over up to 57 MiB, and
    // each batch synchronizes (uploads, marks GPU-modified) its whole range: GPU time of the copy
    // shader 1.5 -> 0.6 ms/frame, GPU busy 85% -> 77%, frame rate no lower.
    // BB_COPY_MERGE_KB overrides it.
    static const vk::DeviceSize MaxDistanceForMerge = [] {
        const char* env = std::getenv("BB_COPY_MERGE_KB");
        return env ? vk::DeviceSize(std::strtoull(env, nullptr, 10)) * 1024 : vk::DeviceSize(64_KB);
    }();
    static std::vector<CopyBatch> batches, grouped_batches;
    static std::vector<vk::BufferCopy> grouped;
    FindBatches(copies, MaxDistanceForMerge, batches);
    // Statistics (BB_FRAME_STATS) and the throttle of the grouping: this runs on one thread at a
    // time (the draw recording thread, or the GPU command thread after a drain).
    static u64 stat_dispatches = 0, stat_ranges = 0, stat_batches = 0, stat_saved = 0;
    static u32 grouping_misses = 0, grouping_pause = 0;
    static u64 stat_copies = 0, stat_copy_flushes = 0, stat_switches = 0, stat_mergeable = 0,
               stat_mergeable_batches = 0, stat_late_uploads = 0, stat_late_upload_bytes = 0;
    // Only with BB_FRAME_STATS=1 and BB_GPU_PROFILE_SPLIT=1: these counters repeat barrier tests
    // and the merge's overlap test, stage B time the other BB_FRAME_STATS runs should not carry.
    static const bool copy_stats = BbStats::enabled && GpuProfiler::SplitMarks();
    const size_t in_order = batches.size();
    // Worth a try with a few batches or more (each costs a few microseconds, the grouping a few
    // nanoseconds per range); paused for a while after attempts that did not help.
    if (in_order >= 4 && !BbToggle::Disabled(BbToggle::MultiCopyShader)) {
        const u32 window_shift =
            static_cast<u32>(std::bit_width(std::max<u64>(MaxDistanceForMerge, 2)) - 1);
        if (grouping_pause) {
            --grouping_pause;
        } else if (GroupByDestination(copies, window_shift, src_buf_sharp.base_address,
                                      dst_buf_sharp.base_address, grouped) &&
                   (FindBatches(grouped, MaxDistanceForMerge, grouped_batches),
                    grouped_batches.size() < in_order)) {
            copies.swap(grouped);
            batches.swap(grouped_batches);
            grouping_misses = 0;
        } else if (++grouping_misses >= 4) {
            grouping_misses = 0;
            grouping_pause = 64;
        }
    }
    batch_scope.End();
    // BB_FRAME_STATS: which ObtainBuffer path the batches take (BufferCache::hle_obtain).
    using VideoCore::BufferCache;
    static std::array<u64, 6> path_calls_before{}, path_bytes_before{};
    if (BbStats::enabled) {
        ++stat_dispatches;
        stat_ranges += copies.size();
        stat_batches += batches.size();
        stat_saved += in_order - batches.size();
        static auto window = std::chrono::steady_clock::now();
        const auto now = std::chrono::steady_clock::now();
        if (now - window >= std::chrono::seconds(5)) {
            const double seconds = std::chrono::duration<double>(now - window).count();
            std::printf("HLE copy shader per second: %.0f dispatches, %.0f ranges, %.0f batches "
                        "(%.0f fewer by destination grouping)\n",
                        stat_dispatches / seconds, stat_ranges / seconds, stat_batches / seconds,
                        stat_saved / seconds);
            // [source, destination] x [in place, stream, VRAM]: calls/s and KiB per call.
            const char* names[6] = {"src in place", "src stream", "src VRAM",
                                    "dst in place", "dst stream", "dst VRAM"};
            std::printf("  HLE copy ObtainBuffer paths:");
            for (u32 i = 0; i < 6; ++i) {
                const u64 calls = BufferCache::hle_path_calls[i] - path_calls_before[i];
                const u64 bytes = BufferCache::hle_path_bytes[i] - path_bytes_before[i];
                if (calls) {
                    std::printf(" %s %.0f/s %.1f KiB,", names[i], calls / seconds,
                                bytes / 1024.0 / calls);
                }
            }
            std::printf("\n");
            path_calls_before = BufferCache::hle_path_calls;
            path_bytes_before = BufferCache::hle_path_bytes;
            window = now;
            stat_dispatches = stat_ranges = stat_batches = stat_saved = 0;
            if (copy_stats) {
                std::printf(
                    "  HLE copy recording per second: %.0f batches as vkCmdCopyBuffer (%.0f with a "
                    "barrier flush before), %.0f switches between them and copy shader dispatches; "
                    "%.0f guest dispatches with %.0f batches the merge can take (BB_HLE_COPY_MERGE "
                    "%s), %.0f merged with uploads recorded before earlier batches' copies (%.1f "
                    "KiB each)\n",
                    stat_copies / seconds, stat_copy_flushes / seconds, stat_switches / seconds,
                    stat_mergeable / seconds, stat_mergeable_batches / seconds,
                    GpuSavings::HleMergeOn() && !BbToggle::Experiment(524288) ? "on" : "off",
                    stat_late_uploads / seconds,
                    stat_late_uploads ? stat_late_upload_bytes / 1024.0 / stat_late_uploads
                                      : 0.0);
            }
            stat_copies = stat_copy_flushes = stat_switches = stat_mergeable = 0;
            stat_mergeable_batches = stat_late_uploads = stat_late_upload_bytes = 0;
        }
    }
    GpuSavings::Get().hle_batches.fetch_add(batches.size(), std::memory_order_relaxed);
    // bbport (BB_HLE_COPY_MERGE): every batch's buffers obtained first (uploads and residency
    // all before the copies), then one barrier check and one dispatch per run of batches on the
    // same buffers, instead of a barrier check and a dispatch per batch. Only when no source
    // range overlaps a destination range in guest memory: the order of the batches cannot
    // matter then (the guest's single dispatch has no order between its ranges either).
    // Experiment bit 524288 (with BB_HLE_COPY_MERGE=1): batch by batch, as without the merge, so
    // one run A/Bs the merge (pictures and GPU time).
    const bool merge = batches.size() > 1 && GpuSavings::HleMergeOn() &&
                       !BbToggle::Experiment(524288) &&
                       !BbToggle::Disabled(BbToggle::MultiCopyShader);
    const bool mergeable =
        (merge || (copy_stats && batches.size() > 1)) &&
        !MergeUnsafe(copies, batches, src_buf_sharp.base_address, dst_buf_sharp.base_address);
    if (copy_stats && mergeable) {
        ++stat_mergeable;
        stat_mergeable_batches += batches.size();
    }
    // BB_FRAME_STATS with BB_GPU_PROFILE_SPLIT: batches recorded as vkCmdCopyBuffer, and
    // switches between those and copy shader dispatches.
    // BB_GPU_PROFILE_SPLIT: the vkCmdCopyBuffer batches get a profiler row of their own.
    u32 last_kind = 0; // 1: copy shader dispatch, 2: vkCmdCopyBuffer
    const auto dispatched = [&] {
        if (copy_stats && last_kind == 2) {
            ++stat_switches;
        }
        last_kind = 1;
    };
    const auto copy_buffer = [&](const VideoCore::Buffer* src, const VideoCore::Buffer* dst,
                                 std::span<const vk::BufferCopy> part) {
        if (copy_stats) {
            ++stat_copies;
            if (last_kind == 1) {
                ++stat_switches;
            }
            if (CopyWouldFlush(runtime, src, dst, part)) {
                ++stat_copy_flushes;
            }
        }
        last_kind = 2;
        if (auto* profiler = GpuProfiler::Get();
            profiler && GpuProfiler::SplitMarks() && profiler->Current() != 0xC0B6ull) {
            profiler->Mark(0xC0B6ull, [] {
                return std::string{"copy shader HLE: batches as vkCmdCopyBuffer"};
            });
        }
        runtime.CopyBuffer(src, dst, part);
    };
    if (merge) {
        const VAddr src_base = src_buf_sharp.base_address;
        const VAddr dst_base = dst_buf_sharp.base_address;
        if (mergeable) {
            struct Obtained {
                const VideoCore::Buffer* src;
                const VideoCore::Buffer* dst;
                AccessRange range;
            };
            static std::vector<Obtained> obtained;
            static std::vector<AccessRange> run_ranges;
            obtained.clear();
            u32 start = 0;
            u64 uploads_after_first = 0;
            for (const auto& batch : batches) {
                BbSections::Scope obtain_scope{BbSections::HleObtain};
                VideoCore::BufferCache::hle_obtain = BbStats::enabled;
                const auto [src_buf, src_buf_offset] = buffer_cache.ObtainBuffer(
                    src_base + batch.src_min, batch.src_max - batch.src_min, false);
                const auto [dst_buf, dst_buf_offset] = buffer_cache.ObtainBuffer(
                    dst_base + batch.dst_min, batch.dst_max - batch.dst_min, true);
                VideoCore::BufferCache::hle_obtain = false;
                obtain_scope.End();
                if (start == 0) {
                    // BB_FRAME_STATS: uploads the later batches' obtains record before the
                    // earlier batches' copies (the order the merge changes).
                    uploads_after_first =
                        BbStats::buffer_upload_bytes.load(std::memory_order_relaxed);
                }
                for (auto& copy : std::span{copies}.subspan(start, batch.end - start)) {
                    copy.srcOffset = copy.srcOffset - batch.src_min + src_buf_offset;
                    copy.dstOffset = copy.dstOffset - batch.dst_min + dst_buf_offset;
                }
                obtained.push_back(
                    {src_buf, dst_buf,
                     {src_buf_offset, src_buf_offset + (batch.src_max - batch.src_min),
                      dst_buf_offset, dst_buf_offset + (batch.dst_max - batch.dst_min)}});
                start = batch.end;
            }
            if (copy_stats) {
                const u64 late = BbStats::buffer_upload_bytes.load(std::memory_order_relaxed) -
                                 uploads_after_first;
                if (late != 0) {
                    ++stat_late_uploads;
                    stat_late_upload_bytes += late;
                }
            }
            BB_SECTION(HleCopy);
            u32 first = 0, copy_start = 0;
            while (first < batches.size()) {
                u32 last = first + 1;
                while (last < batches.size() && obtained[last].src == obtained[first].src &&
                       obtained[last].dst == obtained[first].dst) {
                    ++last;
                }
                const u32 copy_end = batches[last - 1].end;
                run_ranges.clear();
                for (u32 b = first; b < last; ++b) {
                    run_ranges.push_back(obtained[b].range);
                }
                const auto run = std::span{copies}.subspan(copy_start, copy_end - copy_start);
                if (MultiCopy(rasterizer, obtained[first].src, obtained[first].dst, run,
                              run_ranges)) {
                    dispatched();
                } else {
                    // Batch by batch, as without the merge.
                    u32 at = copy_start;
                    for (u32 b = first; b < last; ++b) {
                        const auto part = std::span{copies}.subspan(at, batches[b].end - at);
                        if (MultiCopy(rasterizer, obtained[b].src, obtained[b].dst, part)) {
                            dispatched();
                        } else {
                            copy_buffer(obtained[b].src, obtained[b].dst, part);
                        }
                        at = batches[b].end;
                    }
                }
                first = last;
                copy_start = copy_end;
            }
            return true;
        }
    }
    u32 batch_start = 0;
    for (const auto& batch : batches) {
        const u32 batch_end = batch.end;
        const auto src_offset_min = batch.src_min;
        const auto src_offset_max = batch.src_max;
        const auto dst_offset_min = batch.dst_min;
        const auto dst_offset_max = batch.dst_max;

        // Obtain buffers for the total source and destination ranges.
        BbSections::Scope obtain_scope{BbSections::HleObtain};
        VideoCore::BufferCache::hle_obtain = BbStats::enabled;
        const auto [src_buf, src_buf_offset] = buffer_cache.ObtainBuffer(
            src_buf_sharp.base_address + src_offset_min, src_offset_max - src_offset_min, false);
        const auto [dst_buf, dst_buf_offset] = buffer_cache.ObtainBuffer(
            dst_buf_sharp.base_address + dst_offset_min, dst_offset_max - dst_offset_min, true);
        VideoCore::BufferCache::hle_obtain = false;
        obtain_scope.End();
        BB_SECTION(HleCopy);

        // Apply found buffer base.
        const auto vk_copies = std::span{copies}.subspan(batch_start, batch_end - batch_start);
        for (auto& copy : vk_copies) {
            copy.srcOffset = copy.srcOffset - src_offset_min + src_buf_offset;
            copy.dstOffset = copy.dstOffset - dst_offset_min + dst_buf_offset;
        }

        // Execute buffer copies.
        LOG_TRACE(Render_Vulkan, "HLE buffer copy: src_size = {}, dst_size = {}",
                  src_offset_max - src_offset_min, dst_offset_max - dst_offset_min);
        if (MultiCopy(rasterizer, src_buf, dst_buf, vk_copies)) {
            dispatched();
        } else {
            copy_buffer(src_buf, dst_buf, vk_copies);
        }
        batch_start = batch_end;
    }

    return true;
}

// bbport: the game copies its whole depth target block with the render-target copy shader (the
// depth plane, the padding and the stencil plane after it) into memory it then samples as an R32F
// texture the size of the depth plane, once per frame. Neither image's size is the byte count,
// so the copy ran as the guest's shader over buffers: the depth image was downloaded and tiled
// into the buffer cache for the source, and the texture, marked GPU-dirty by the write, was
// detiled and uploaded again at its next binding (BB_GPU_PROFILE at 3840x2160: "image download
// D32SfloatS8Uint" ~1.0 ms and "image upload R32Sfloat" ~0.55 ms per frame, plus the two
// dispatches in between). Here it is one copy of the depth aspect into the texture. The bytes
// after the depth plane have no image at the destination (checked), so nothing reads them as one.
// The texture becomes a GPU-written image (Runtime::CopyImage), as it must: the image is then the
// only holder of the data, and the collector treats it like a render target (it stays while there
// is room).
// BB_RT_DEPTH_COPY=0 or experiment mask 32 (BB_TOGGLE_FILE): the old path.
// With reduced scene targets and a dirty depth proxy the texture is drawn from the proxy instead
// (SceneTargets::CopyDepthProxyToColor): no resolve of the native depth, no 4K image copy.
// Experiment mask 2048: the image copy from the resolved native depth, as before.
static bool DepthBlockCopy(Rasterizer& rasterizer, VideoCore::ImageId src_id, VAddr dst_address,
                           u64 bytes) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_RT_DEPTH_COPY");
        return !env || env[0] != '0';
    }();
    if (!enabled || BbToggle::Experiment(32) || !src_id) {
        return false;
    }
    auto& textures = rasterizer.GetTextureCache();
    auto& runtime = rasterizer.GetRuntime();
    const auto& source = textures.GetImage(src_id).info;
    if (!source.props.is_depth || source.guest_size >= bytes) {
        return false; // not a depth block: the checks below ExecuteRtCopyShaderHLE's lookups apply
    }
    // Each outcome is logged once, with what decided it.
    static std::atomic<u32> logged{0};
    const auto report = [&](u32 bit, const char* outcome, const VideoCore::ImageInfo* destination) {
        if (logged.fetch_or(bit, std::memory_order_relaxed) & bit) {
            return;
        }
        std::printf("Render-target copy HLE: depth block of 0x%llx bytes %s; source 0x%llx+0x%x "
                    "%ux%u %s stencil 0x%llx+0x%x pitch %u tile %u",
                    static_cast<unsigned long long>(bytes), outcome,
                    static_cast<unsigned long long>(source.guest_address), source.guest_size,
                    source.size.width, source.size.height,
                    vk::to_string(source.pixel_format).c_str(),
                    static_cast<unsigned long long>(source.stencil_addr), source.stencil_size,
                    source.pitch, static_cast<u32>(source.tile_mode));
        if (destination) {
            std::printf("; destination 0x%llx+0x%x %ux%u %s pitch %u tile %u",
                        static_cast<unsigned long long>(destination->guest_address),
                        destination->guest_size, destination->size.width,
                        destination->size.height,
                        vk::to_string(destination->pixel_format).c_str(), destination->pitch,
                        static_cast<u32>(destination->tile_mode));
        }
        std::printf(" (BB_RT_DEPTH_COPY)\n");
    };
    if (!runtime.GetInstance().IsMaintenance8Supported()) {
        report(1, "left to the shader: no VK_KHR_maintenance8 for a depth to color copy", nullptr);
        return false;
    }
    if ((source.pixel_format != vk::Format::eD32SfloatS8Uint &&
         source.pixel_format != vk::Format::eD32Sfloat) ||
        source.num_samples != 1 || source.resources != VideoCore::SubresourceExtent{1, 1}) {
        report(2, "left to the shader: the source is not a plain 32-bit float depth image",
               nullptr);
        return false;
    }
    // The texture is only sampled, so it is not a GPU-written image: any image at the address.
    const VideoCore::ImageId dst_id = textures.FindImageFromRange(dst_address, bytes, false);
    if (!dst_id) {
        report(4, "left to the shader: no single image at the destination", nullptr);
        return false;
    }
    const auto& destination = textures.GetImage(dst_id).info;
    if (destination.pixel_format != vk::Format::eR32Sfloat ||
        destination.guest_size != source.guest_size || destination.size != source.size ||
        destination.type != source.type || destination.resources != source.resources ||
        destination.num_samples != 1 || destination.pitch != source.pitch ||
        destination.num_bits != source.num_bits || destination.tile_mode != source.tile_mode) {
        report(8, "left to the shader: the destination image does not match the depth plane",
               &destination);
        return false;
    }
    // Nothing else may be an image in the copied range: its contents would come from the bytes
    // after the depth plane, which this copy does not carry.
    bool shared = false;
    textures.ForEachImageInRegion(dst_address, bytes,
                                  [&](VideoCore::ImageId id, VideoCore::Image&) {
                                      shared |= id != dst_id;
                                  });
    if (shared) {
        report(16, "left to the shader: another image lies in the destination range",
               &destination);
        return false;
    }
    textures.UpdateImage(src_id);
    auto& src_image = textures.GetImage(src_id);
    auto& dst_image = textures.GetImage(dst_id);
    auto* const scene = runtime.scene_targets;
    if (!BbToggle::Experiment(2048) && scene && scene->Reduced() &&
        scene->CanCopyDepthProxyToColor(src_image, dst_image)) {
        if (auto* profiler = GpuProfiler::Get()) {
            profiler->Mark(0xC0B4ull, [] {
                return std::string{"render-target copy HLE: depth block from proxy (shader)"};
            });
        }
        if (scene->CopyDepthProxyToColor(src_image, dst_image)) {
            static bool proxy_logged = false;
            if (!proxy_logged) {
                proxy_logged = true;
                const auto proxy = scene->ProxySize(src_image);
                std::printf("Render-target copy HLE: depth block written from the %ux%u depth "
                            "proxy by a shader (experiment mask 2048: the image copy)\n",
                            proxy.width, proxy.height);
            }
            return true;
        }
    }
    report(32, "copied as an image", &destination);
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->Mark(0xC0B3ull, [] {
            return std::string{"render-target copy HLE: depth block to R32F image copy"};
        });
    }
    runtime.CopyColorAndDepth(&src_image, &dst_image);
    return true;
}

bool ExecuteRtCopyShaderHLE(const Shader::Info& info, const AmdGpu::ComputeProgram& cs_program,
                            Rasterizer& rasterizer) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_RT_IMAGE_COPY");
        return !env || env[0] != '0';
    }();
    if (!enabled || info.buffers.size() != 2 || cs_program.dim_y != 1 || cs_program.dim_z != 1) {
        return false;
    }
    const auto src = info.buffers[0].GetSharp(info);
    const auto dst = info.buffers[1].GetSharp(info);
    if (src.GetStride() != sizeof(u32) || dst.GetStride() != sizeof(u32)) {
        return false;
    }
    const u64 bytes = u64(cs_program.dim_x) * 64 * sizeof(u32);
    if (bytes == 0 || bytes > src.GetSize() || bytes > dst.GetSize()) {
        return false;
    }
    auto& textures = rasterizer.GetTextureCache();
    if (VideoCore::TextureCache::TestDepthAliasOn()) [[unlikely]] {
        textures.TestDepthAlias(src.base_address, bytes); // BB_TEST_DEPTH_ALIAS (test only)
    }
    const VideoCore::ImageId src_id = textures.FindImageFromRange(src.base_address, bytes);
    if (DepthBlockCopy(rasterizer, src_id, dst.base_address, bytes)) {
        return true;
    }
    VideoCore::ImageId dst_id = textures.FindImageFromRange(dst.base_address, bytes);
    if (src_id && !dst_id && textures.GetImage(src_id).info.guest_size == bytes) {
        VideoCore::TextureCache::ImageDesc desc;
        desc.info = textures.GetImage(src_id).info;
        desc.info.guest_address = dst.base_address;
        desc.info.meta_info = {};
        desc.info.stencil_addr = 0;
        desc.info.stencil_size = 0;
        desc.type = desc.info.props.is_depth ? VideoCore::TextureCache::BindingType::DepthTarget
                                             : VideoCore::TextureCache::BindingType::RenderTarget;
        dst_id = textures.FindImage(desc);
    }
    if (!src_id || !dst_id) {
        return false;
    }
    const auto& source = textures.GetImage(src_id);
    const auto& destination = textures.GetImage(dst_id);
    if (source.info.guest_size != bytes || destination.info.guest_size != bytes ||
        source.info.size != destination.info.size || source.info.type != destination.info.type ||
        source.info.resources != destination.info.resources ||
        source.info.num_samples != destination.info.num_samples) {
        return false;
    }
    if (source.info.pixel_format != destination.info.pixel_format &&
        source.info.props.is_depth == destination.info.props.is_depth) {
        return false;
    }
    if (src_id == dst_id) {
        return true;
    }
    // bbport: with reduced scene targets, a colour copy whose source proxy holds writes its
    // native image has not seen is done between the proxies at the reduced size
    // (SceneTargets::CopyProxy): no resolve of the source, none of the overwritten destination,
    // no copy at the native size, no fill of the destination proxy afterwards. A native reader of
    // the destination resolves its proxy later, to what the native copy held.
    // Experiment mask 131072 (or BB_SCENE_PROXY_COPY=0): the native copy, as before.
    static const bool proxy_copy_env = [] {
        const char* env = std::getenv("BB_SCENE_PROXY_COPY");
        return !env || env[0] != '0';
    }();
    auto* const scene = rasterizer.GetRuntime().scene_targets;
    // bbport (r10_proxy_copies): a destination without a proxy gets one for the copy
    // (SceneTargets::ProxyForCopy), so the copy below goes between the proxies. Experiment bit
    // 34359738368: none is made, and a copy into one made before stays native.
    const char* const proxy_for_copy =
        proxy_copy_env && !BbToggle::Experiment(131072) && scene && scene->Reduced() &&
                !FrameCapture::IsDisplayBuffer(destination.info.guest_address)
            ? scene->ProxyForCopy(source, textures.GetImage(dst_id), dst_id)
            : nullptr;
    const char* const blocker =
        proxy_for_copy ? proxy_for_copy
        : !proxy_copy_env || BbToggle::Experiment(131072) ? "experiment mask 131072"
        : !scene || !scene->Reduced()                    ? "native scene size"
                                                         : scene->ProxyCopyBlocker(source, destination);
    if (scene && scene->debug) {
        std::printf("Scene RT copy: %s %ux%u 0x%llx -> 0x%llx: %s\n",
                    vk::to_string(source.info.pixel_format).c_str(), source.info.size.width,
                    source.info.size.height,
                    static_cast<unsigned long long>(source.info.guest_address),
                    static_cast<unsigned long long>(destination.info.guest_address),
                    blocker ? blocker : "proxy to proxy");
    }
    if (auto* profiler = GpuProfiler::Get()) {
        if (blocker) {
            profiler->Mark(0xC0B2ull,
                           [] { return std::string{"render-target copy HLE: image copy"}; });
        } else {
            profiler->Mark(0xC0B5ull,
                           [] { return std::string{"render-target copy HLE: proxy copy"}; });
        }
    }
    textures.UpdateImage(src_id);
    auto& src_image = textures.GetImage(src_id);
    auto& dst_image = textures.GetImage(dst_id);
    const bool src_stale = scene && scene->NativeStale(src_image);
    const bool dst_stale = scene && scene->NativeStale(dst_image);
    const bool proxied = !blocker && scene->CopyProxy(src_image, dst_image);
    // bbport: the native copy below writes every level of the destination at its full extent
    // when both are colour of one format, size, type, levels and layers, with one sample
    // (CopyColorAndDepth -> CopyImage). A dirty destination proxy would be resolved into the
    // native image first (NativeAccess on the transfer write), only for the copy to overwrite it
    // in the same command buffer. Drop it instead, as the merge does before its whole-image
    // write: the proxy ends as the resolve plus the copy left it (invalid, not dirty).
    // Experiment mask 67108864: resolve it first, as before.
    const vk::ImageAspectFlags color_aspect{vk::ImageAspectFlagBits::eColor};
    const bool whole_color =
        !src_image.info.props.is_depth && !dst_image.info.props.is_depth &&
        src_image.aspect_mask == color_aspect && dst_image.aspect_mask == color_aspect &&
        src_image.info.num_samples == 1 && dst_image.info.num_samples == 1 &&
        src_image.info.pixel_format == dst_image.info.pixel_format &&
        src_image.info.size == dst_image.info.size && src_image.info.type == dst_image.info.type &&
        src_image.info.resources == dst_image.info.resources;
    const bool drop_resolve =
        !proxied && dst_stale && whole_color && !BbToggle::Experiment(67108864);
    if (BbStats::enabled) {
        // BB_FRAME_STATS: why the copies are not done between the proxies, and what they resolve.
        static u32 copies = 0, between = 0, src_dirty = 0, dst_dirty = 0, dropped = 0;
        static std::array<std::pair<const char*, u32>, 8> reasons{};
        ++copies;
        between += proxied ? 1 : 0;
        src_dirty += !proxied && src_stale ? 1 : 0;
        dst_dirty += !proxied && dst_stale ? 1 : 0;
        dropped += drop_resolve ? 1 : 0;
        if (!proxied) {
            const char* const reason = blocker ? blocker : "proxy copy refused";
            for (auto& slot : reasons) {
                if (!slot.first || slot.first == reason) {
                    slot.first = reason;
                    ++slot.second;
                    break;
                }
            }
        }
        if (copies >= 4096) {
            std::string why;
            for (const auto& [reason, count] : reasons) {
                if (reason) {
                    why += std::string{" "} + reason + " " + std::to_string(count) + ",";
                }
            }
            if (!why.empty()) {
                why.pop_back();
            }
            std::printf("Render-target copy HLE, last %u copies: %u between proxies, %u native; of "
                        "the native ones %u with a dirty source proxy (resolved), %u with a dirty "
                        "destination proxy, %u of those resolves dropped (experiment mask "
                        "67108864 %s); not between proxies:%s\n",
                        copies, between, copies - between, src_dirty, dst_dirty, dropped,
                        BbToggle::Experiment(67108864) ? "set: kept" : "clear", why.c_str());
            copies = between = src_dirty = dst_dirty = dropped = 0;
            reasons = {};
        }
    }
    if (proxied) {
        return true;
    }
    if (drop_resolve) {
        scene->NativeOverwritten(dst_image);
    }
    rasterizer.GetRuntime().CopyColorAndDepth(&src_image, &dst_image);
    return true;
}

bool ExecuteShaderHLE(const Shader::Info& info, const AmdGpu::Regs& regs,
                      const AmdGpu::ComputeProgram& cs_program, Rasterizer& rasterizer) {
    switch (info.pgm_hash) {
    case COPY_SHADER_HASH: {
        const bool done = ExecuteCopyShaderHLE(info, cs_program, rasterizer);
        // bbport BB_GPU_PROFILE_SPLIT=1: what follows (the next draw's barriers and transfers)
        // gets a row of its own instead of being charged to the copies.
        if (auto* profiler = GpuProfiler::Get(); profiler && GpuProfiler::SplitMarks()) {
            profiler->Mark(0xC0B7ull, [] {
                return std::string{"after copy shader HLE: unlabelled work until the next label"};
            });
        }
        return done;
    }
    case RT_COPY_SHADER_HASH:
        return ExecuteRtCopyShaderHLE(info, cs_program, rasterizer);
    default:
        return false;
    }
}

} // namespace Vulkan
