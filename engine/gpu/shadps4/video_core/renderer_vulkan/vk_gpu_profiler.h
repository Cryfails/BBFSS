// SPDX-License-Identifier: GPL-2.0-or-later
// bbport: BB_GPU_PROFILE=1 — GPU time per render pass, dispatch and upscaler run. A timestamp is
// written where each of them starts (and at the frame end); the time to the next timestamp is
// charged to its label, barriers and copies recorded in between included. Results are read four
// frames later and printed every 5 s: GPU ms per frame by label.

#pragma once

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {

class Instance;
class Scheduler;

class GpuProfiler {
public:
    /// The profiler when BB_GPU_PROFILE=1, else null.
    static GpuProfiler* Get() noexcept {
        return instance_ptr;
    }
    /// bbport BB_GPU_PROFILE_SPLIT=1: extra marks after dispatches and HLE copies (and for the
    /// copy shader's vkCmdCopyBuffer batches), so the unlabelled work recorded after them gets a
    /// row of its own instead of being charged to them. Off: the rows are as before.
    static bool SplitMarks() noexcept {
        static const bool on = [] {
            const char* env = std::getenv("BB_GPU_PROFILE_SPLIT");
            return env && env[0] == '1';
        }();
        return on;
    }
    static void Init(const Instance& instance, Scheduler& scheduler);

    /// Starts a segment labelled `key`; `describe` names it the first time the key is seen.
    template <typename Describe>
    void Mark(u64 key, Describe&& describe) {
        if (!described.contains(key)) {
            described.emplace(key, describe());
        }
        WriteTimestamp(key);
    }

    /// The label of the open segment, for Resume after a nested segment (transfers).
    [[nodiscard]] u64 Current() const noexcept {
        return current;
    }
    /// Continues the segment of `key` (a label seen before) where a nested one ends.
    void Resume(u64 key) {
        WriteTimestamp(key);
    }
    /// bbport r8: at the end of a submission: the GPU's time until the next submission starts
    /// (MarkSubmissionStart). Collect charges it to a row per reason of submission `next_tick`
    /// (the one that ends the gap) and whether the GPU had finished this one when it was queued.
    void MarkGap(u64 next_tick) {
        gap_tick = next_tick;
        Mark(GapKey, [] { return std::string{"(between submissions: GPU idle)"}; });
        gap_tick = 0;
    }
    /// bbport r8: at the start of a submission: its commands before its first labelled pass.
    void MarkSubmissionStart() {
        Mark(0x5B318ull,
             [] { return std::string{"(submission start: commands before its first pass)"}; });
    }
    /// bbport: one draw recorded under the open label (same thread as Mark).
    void NoteDraw() {
        ++draws[current];
    }
    /// bbport (r76_sun-fog-outdoors): `key`'s row is printed in every block it has time in, also
    /// below the BB_GPU_PROFILE_ROWS cut, after the first rows and in the same form (a row of a
    /// few hundredths of a ms, as the volumetric sun gate's in a closed room, fell below it).
    void Pin(u64 key) {
        for (const u64 known : pinned) {
            if (known == key) {
                return;
            }
        }
        pinned.push_back(key);
    }

    /// Whether `other` is the scheduler it records into (the presenter has its own).
    [[nodiscard]] bool Records(const Scheduler* other) const noexcept {
        return other == &scheduler;
    }

    /// At the display pass: closes the frame's last segment, reads an old frame's results.
    void BeginFrame();

    /// bbport: the presenter's command buffer (its own scheduler, the swap thread): GPU time of
    /// its parts from timestamps in that buffer, printed every 5 s as "GPU profile, presenter"
    /// (per present; that time is not in the table above, it sits in its idle row).
    enum class PresentPart : u32 {
        Frame,         ///< the frame into the back buffer (blit, HDR encode, menu layer)
        HudlessEncode, ///< DLSS-G in HDR: the HUD-less frame placed and encoded
        UiInputs,      ///< DLSS-G: back buffer copy into final_image (and letterboxed HUD-less)
        UiAlpha,       ///< DLSS-G: the UI alpha pass
        Count,
    };
    /// Swap thread, at the start of a present's recording.
    void PresentBegin(vk::CommandBuffer cmdbuf);
    /// Where `part` starts in it.
    void PresentMark(vk::CommandBuffer cmdbuf, PresentPart part);
    /// Before its submission: the end of its last part.
    void PresentEnd(vk::CommandBuffer cmdbuf);

private:
    GpuProfiler(const Instance& instance, Scheduler& scheduler);
    void WriteTimestamp(u64 key);
    bool Collect(u32 slice);
    /// bbport r8: the row of a segment: a gap's by its next submission, else `key`.
    u64 GapLabel(u64 key, u64 next_tick);
    void Print();
    void PrintPresent();

    static constexpr u32 NumSlices = 4;
    static constexpr u32 SliceQueries = 4096;
    static inline GpuProfiler* instance_ptr = nullptr;

    vk::Device device;
    Scheduler& scheduler;
    vk::UniqueQueryPool pool;
    double period_ns = 1.0;
    u32 slice = 0;
    std::array<std::vector<u64>, NumSlices> keys; ///< label of each timestamp but the last
    /// bbport r8: per timestamp, the submission a gap (MarkGap) ends at; 0 for other labels.
    std::array<std::vector<u64>, NumSlices> gap_ticks;
    u64 gap_tick = 0;
    static constexpr u64 GapKey = 0x5B317ull;
    std::array<u32, NumSlices> used{};
    std::array<bool, NumSlices> pending{};
    /// A slice whose results were not ready when its turn came (its timestamps may sit in a
    /// submission not sent yet, during loads): not written again until they are read.
    std::array<bool, NumSlices> held{};
    u64 skipped_frames = 0;
    std::unordered_map<u64, std::string> described;
    struct Total {
        double ms = 0;
        u64 segments = 0;
    };
    std::unordered_map<u64, Total> totals;
    std::unordered_map<u64, u64> draws; ///< draws recorded under each label since the last print
    std::vector<u64> pinned; ///< bbport (r76_sun-fog-outdoors): Pin
    u64 frames = 0;
    u64 current = 0;
    std::chrono::steady_clock::time_point window = std::chrono::steady_clock::now();

    // bbport: presenter timestamps (swap thread only). Reset by a command in the buffer; a
    // slice is read when its turn comes again, long after its present (presents in flight are
    // bounded by the presentation frames).
    static constexpr u32 PresentSlices = 8;
    static constexpr u32 PresentQueries = 16;
    static constexpr size_t PresentPartCount = static_cast<size_t>(PresentPart::Count);
    vk::UniqueQueryPool present_pool;
    u32 present_slice = 0;
    bool present_open = false;
    std::array<u32, PresentSlices> present_used{};
    std::array<bool, PresentSlices> present_pending{};
    std::array<std::array<u32, PresentQueries>, PresentSlices> present_parts{};
    /// The experiment mask when each slice was recorded: totals are kept per mask, so an A/B
    /// run (-Experiment) gets one block per phase kind.
    std::array<u64, PresentSlices> present_masks{};
    struct PresentTotals {
        std::array<double, PresentPartCount> ms{};
        std::array<u64, PresentPartCount> segments{};
        u64 count = 0;
    };
    std::unordered_map<u64, PresentTotals> present_totals;
    std::chrono::steady_clock::time_point present_window = std::chrono::steady_clock::now();
};

} // namespace Vulkan
