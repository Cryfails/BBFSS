// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <cstdlib>

#include "video_core/renderer_vulkan/vk_gpu_profiler.h"

#include "bbport_toggles.h" // bbport: runtime_experiment_bits (the presenter's totals per mask)
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {

void GpuProfiler::Init(const Instance& instance, Scheduler& scheduler) {
    const char* env = std::getenv("BB_GPU_PROFILE");
    if (!env || env[0] != '1' || instance_ptr) {
        return;
    }
    instance_ptr = new GpuProfiler(instance, scheduler);
}

GpuProfiler::GpuProfiler(const Instance& instance, Scheduler& scheduler_)
    : device{instance.GetDevice()}, scheduler{scheduler_} {
    const vk::QueryPoolCreateInfo info = {
        .queryType = vk::QueryType::eTimestamp,
        .queryCount = NumSlices * SliceQueries,
    };
    pool = Check<"create timestamp query pool">(device.createQueryPoolUnique(info));
    const vk::QueryPoolCreateInfo present_info = {
        .queryType = vk::QueryType::eTimestamp,
        .queryCount = PresentSlices * PresentQueries,
    };
    present_pool =
        Check<"create present timestamp query pool">(device.createQueryPoolUnique(present_info));
    device.resetQueryPool(*pool, 0, NumSlices * SliceQueries);
    period_ns = instance.GetPhysicalDevice().getProperties().limits.timestampPeriod;
    for (auto& k : keys) {
        k.reserve(SliceQueries);
    }
    for (auto& k : gap_ticks) {
        k.reserve(SliceQueries);
    }
    std::printf("GPU profile: on (timestamp period %.2f ns)\n", period_ns);
}

void GpuProfiler::WriteTimestamp(u64 key) {
    if (held[slice] || used[slice] + 1 >= SliceQueries) {
        return; // the frame's slice is full: the rest of the frame goes to the last label
    }
    // Outside render passes: radv_CmdWriteTimestamp2 crashed inside some. Marks sit where a
    // pass, dispatch or submission ends anyway.
    scheduler.EndRendering();
    const u32 query = slice * SliceQueries + used[slice]++;
    keys[slice].push_back(key);
    gap_ticks[slice].push_back(gap_tick);
    current = key;
    scheduler.Record([pool = *pool, query](vk::CommandBuffer cmdbuf) {
        cmdbuf.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, pool, query);
    });
}

// bbport (r23_spike-trace): each slice's frame number (BbStats::gpu_frames after the display pass
// that closes it), for BbSpike::NoteGpu when the slice is read.
static std::array<u64, 4> r23_slice_frame{};

void GpuProfiler::BeginFrame() {
    // Close the frame: one more timestamp without a label.
    if (!held[slice] && used[slice] > 0 && used[slice] < SliceQueries) {
        scheduler.EndRendering();
        const u32 query = slice * SliceQueries + used[slice]++;
        scheduler.Record([pool = *pool, query](vk::CommandBuffer cmdbuf) {
            cmdbuf.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, pool, query);
        });
        pending[slice] = true;
        r23_slice_frame[slice % r23_slice_frame.size()] =
            BbStats::gpu_frames.load(std::memory_order_relaxed) + 1; // bbport (r23_spike-trace)
    }
    slice = (slice + 1) % NumSlices;
    // The oldest slice, from four frames ago. Its results are read without waiting: during a
    // load frames pass with no submission, so its timestamps may not have reached the GPU yet
    // (waiting for them here stopped the GPU thread for good). Such a slice stays as it is,
    // unwritten, until they are there; that frame goes unmeasured.
    if (pending[slice] && !Collect(slice)) {
        held[slice] = true;
        ++skipped_frames;
        Print();
        return;
    }
    held[slice] = false;
    if (used[slice]) {
        device.resetQueryPool(*pool, slice * SliceQueries, used[slice]);
    }
    used[slice] = 0;
    keys[slice].clear();
    gap_ticks[slice].clear();
    pending[slice] = false;
    Print();
}

bool GpuProfiler::Collect(u32 which) {
    const u32 count = used[which];
    std::vector<u64> stamps(count);
    const auto result = device.getQueryPoolResults(
        *pool, which * SliceQueries, count, count * sizeof(u64), stamps.data(), sizeof(u64),
        vk::QueryResultFlagBits::e64);
    if (result != vk::Result::eSuccess) {
        return false; // eNotReady: not all of them executed yet
    }
    for (u32 i = 0; i + 1 < count; ++i) {
        const double ms = double(stamps[i + 1] - stamps[i]) * period_ns / 1e6;
        auto& total = totals[GapLabel(keys[which][i], gap_ticks[which][i])];
        total.ms += ms;
        ++total.segments;
    }
    if (BbSpike::on && count >= 2) { // bbport (r23_spike-trace): the frame's GPU busy and span
        u64 gaps = 0;
        for (u32 i = 0; i + 1 < count; ++i) {
            gaps += keys[which][i] == GapKey ? stamps[i + 1] - stamps[i] : 0;
        }
        const u64 span = stamps[count - 1] - stamps[0];
        BbSpike::NoteGpu(r23_slice_frame[which % r23_slice_frame.size()],
                         u64(double(span - std::min(gaps, span)) * period_ns),
                         u64(double(span) * period_ns));
    }
    ++frames;
    return true;
}

u64 GpuProfiler::GapLabel(u64 key, u64 next_tick) {
    u32 reason = 0;
    bool dry = false;
    if (key != GapKey || next_tick == 0 || !scheduler.SubmitDiagOf(next_tick, reason, dry)) {
        return key;
    }
    reason = std::min<u32>(reason, BbSubmitDiag::Reasons - 1);
    // The gap after the flip submission holds the presenter's command buffer and the present.
    u32 previous = 0;
    bool previous_dry = false;
    const bool after_flip = scheduler.SubmitDiagOf(next_tick - 1, previous, previous_dry) &&
                            previous == BbSubmitDiag::ReasonFlip;
    const u64 split =
        GapKey + 0x100 + u64(reason) * 2 + (dry ? 1 : 0) + (after_flip ? 0x80 : 0);
    if (!described.contains(split)) {
        described.emplace(split, std::string{"(between submissions: GPU idle) before a "} +
                                     BbSubmitDiag::ReasonNames[reason] + " submission, " +
                                     (dry ? "GPU had finished the one before it when it reached "
                                            "the queue"
                                          : "the one before still on the GPU when it reached "
                                            "the queue") +
                                     (after_flip ? ", after the flip (presenter work in it)" : ""));
    }
    return split;
}

void GpuProfiler::Print() {
    const auto now = std::chrono::steady_clock::now();
    if (now - window < std::chrono::seconds(5) || frames == 0) {
        return;
    }
    window = now;
    std::vector<std::pair<u64, Total>> sorted(totals.begin(), totals.end());
    std::ranges::sort(sorted, [](const auto& a, const auto& b) { return a.second.ms > b.second.ms; });
    double sum = 0;
    for (const auto& [key, total] : sorted) {
        sum += total.ms;
    }
    std::printf("GPU profile: %.2f ms/frame over %llu frames, %zu labels (%llu frames not ready, skipped)\n",
                sum / frames, static_cast<unsigned long long>(frames), sorted.size(),
                static_cast<unsigned long long>(skipped_frames));
    skipped_frames = 0;
    // BB_GPU_PROFILE_ROWS: how many labels are printed (default 30; the rest can add up to
    // several ms per frame that no row shows).
    static const size_t rows = [] {
        const char* env = std::getenv("BB_GPU_PROFILE_ROWS");
        const long value = env ? std::strtol(env, nullptr, 10) : 0;
        return value > 0 ? static_cast<size_t>(value) : size_t{30};
    }();
    for (size_t i = 0; i < std::min(sorted.size(), rows); ++i) {
        const auto& [key, total] = sorted[i];
        std::printf("  %6.3f ms/frame %5.1f/frame  %s\n", total.ms / frames,
                    double(total.segments) / frames, described[key].c_str());
    }
    // bbport: where the frame's draws go (the render thread's cost follows the draw count).
    std::vector<std::pair<u64, u64>> by_draws(draws.begin(), draws.end());
    std::ranges::sort(by_draws, [](const auto& a, const auto& b) { return a.second > b.second; });
    u64 all_draws = 0;
    for (const auto& [key, count] : by_draws) {
        all_draws += count;
    }
    std::printf("Draws by pass: %.0f draws/frame in %zu labels\n", double(all_draws) / frames,
                by_draws.size());
    for (size_t i = 0; i < std::min(by_draws.size(), size_t{40}); ++i) {
        std::printf("Draws by pass: %8.1f draws/frame  %s\n", double(by_draws[i].second) / frames,
                    described[by_draws[i].first].c_str());
    }
    draws.clear();
    totals.clear();
    frames = 0;
}

void GpuProfiler::PresentBegin(vk::CommandBuffer cmdbuf) {
    present_open = false;
    present_slice = (present_slice + 1) % PresentSlices;
    const u32 s = present_slice;
    if (present_pending[s]) {
        const u32 count = present_used[s];
        std::array<u64, PresentQueries> stamps{};
        const auto result = device.getQueryPoolResults(
            *present_pool, s * PresentQueries, count, count * sizeof(u64), stamps.data(),
            sizeof(u64), vk::QueryResultFlagBits::e64);
        if (result != vk::Result::eSuccess) {
            return; // still in flight (not expected): this present goes unmeasured
        }
        PresentTotals& sums = present_totals[present_masks[s]];
        for (u32 i = 0; i + 1 < count; ++i) {
            const u32 part = present_parts[s][i];
            sums.ms[part] += double(stamps[i + 1] - stamps[i]) * period_ns / 1e6;
            ++sums.segments[part];
        }
        ++sums.count;
        present_pending[s] = false;
    }
    cmdbuf.resetQueryPool(*present_pool, s * PresentQueries, PresentQueries);
    present_used[s] = 0;
    present_masks[s] = __atomic_load_n(&runtime_experiment_bits, __ATOMIC_RELAXED);
    present_open = true;
    PrintPresent();
}

void GpuProfiler::PresentMark(vk::CommandBuffer cmdbuf, PresentPart part) {
    const u32 s = present_slice;
    if (!present_open || present_used[s] + 1 >= PresentQueries) {
        return; // the last query is PresentEnd's
    }
    present_parts[s][present_used[s]] = static_cast<u32>(part);
    cmdbuf.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, *present_pool,
                           s * PresentQueries + present_used[s]);
    ++present_used[s];
}

void GpuProfiler::PresentEnd(vk::CommandBuffer cmdbuf) {
    const u32 s = present_slice;
    if (!present_open) {
        return;
    }
    present_open = false;
    if (present_used[s] == 0 || present_used[s] >= PresentQueries) {
        return;
    }
    cmdbuf.writeTimestamp2(vk::PipelineStageFlagBits2::eAllCommands, *present_pool,
                           s * PresentQueries + present_used[s]);
    ++present_used[s];
    present_pending[s] = true;
}

void GpuProfiler::PrintPresent() {
    const auto now = std::chrono::steady_clock::now();
    if (now - present_window < std::chrono::seconds(5) || present_totals.empty()) {
        return;
    }
    present_window = now;
    static constexpr std::array<const char*, PresentPartCount> names{
        "present: frame into the back buffer (blit or HDR encode, menu layer)",
        "present: DLSS-G HUD-less frame placed and HDR-encoded",
        "present: DLSS-G UI inputs (back buffer copy into final_image, letterbox)",
        "present: DLSS-G UI alpha",
    };
    // One write for the whole block (other threads print too). Every line is indented and none
    // says "ms/frame": the test script's table parser ends a frame block at the first unindented
    // line, so this block, printed at about the same moment as the frame table (both every 5 s
    // from the same start), neither counts as a frame block nor cuts one it lands inside.
    std::string out;
    char line[256];
    for (const auto& [mask, sums] : present_totals) {
        if (sums.count == 0) {
            continue;
        }
        double sum = 0;
        for (const double ms : sums.ms) {
            sum += ms;
        }
        std::snprintf(line, sizeof(line),
                      "  GPU profile, presenter, experiment mask %llu (own command buffer, within "
                      "the idle row): %.3f ms per present over %llu presents\n",
                      static_cast<unsigned long long>(mask), sum / double(sums.count),
                      static_cast<unsigned long long>(sums.count));
        out += line;
        for (size_t i = 0; i < names.size(); ++i) {
            if (sums.segments[i] != 0) {
                std::snprintf(line, sizeof(line), "  %6.3f ms/present %5.1f/present  %s\n",
                              sums.ms[i] / double(sums.count),
                              double(sums.segments[i]) / double(sums.count), names[i]);
                out += line;
            }
        }
    }
    present_totals.clear();
    std::fputs(out.c_str(), stdout);
}

} // namespace Vulkan
