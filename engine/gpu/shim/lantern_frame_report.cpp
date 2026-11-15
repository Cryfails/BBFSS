// SPDX-License-Identifier: GPL-3.0-or-later
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#ifndef _WIN32
#include <dirent.h>
#include <sys/resource.h>
#include <unistd.h>
#endif
#include "bbport_heap_sites.h"
#include "bbport_platform.h"
#include "bbport_sections.h"
#include "bbport_toggles.h"
#include "bbport_wait_trace.h"
#include "common/thread.h"
#include "common/types.h"
#include "core/emulator_settings.h"
#include "lantern_frame_report.h"
#include "sys/video_out.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/page_manager.h"
#include "video_core/renderer_vulkan/pipeline_compile_queue.h"
#include "video_core/renderer_vulkan/vk_breadcrumbs.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

extern "C" void runtime_sleep_stats(uint64_t* calls, uint64_t* ns);
extern "C" void runtime_wait_report(double frames);
extern "C" void sys_rwlock_census(uint64_t* live, uint64_t* found, uint64_t* steps);
extern "C" void sys_sema_census(uint64_t* live, uint64_t* found, uint64_t* steps);
extern "C" void runtime_thread_census(uint64_t* made, uint64_t* finished, uint64_t* found, uint64_t* steps);
extern "C" uint64_t runtime_memory_regions(void);
extern "C" uint64_t runtime_heap_growths(void);

namespace Vulkan {
extern std::atomic<u64> g_bb_compile_ns, g_bb_compile_ns_total;
extern std::atomic<u32> g_bb_compiles, g_bb_compiles_total;
}

namespace AmdGpu {
void OcclusionDumpCounts(u64& dumps, u64& in_order);
}

namespace LanternFrameReport {

static void PrintMemory() {
#ifndef _WIN32
    u64 vram_kib = 0, gtt_kib = 0;
    std::vector<u64> clients;
    if (DIR* dir = opendir("/proc/self/fdinfo")) {
        while (const dirent* entry = readdir(dir)) {
            char path[64];
            std::snprintf(path, sizeof(path), "/proc/self/fdinfo/%s", entry->d_name);
            FILE* file = std::fopen(path, "r");
            if (!file) {
                continue;
            }
            char line[160];
            bool drm = false;
            unsigned long long client = 0, vram = 0, gtt = 0;
            while (std::fgets(line, sizeof(line), file)) {
                drm |= std::strncmp(line, "drm-driver:", 11) == 0;
                std::sscanf(line, "drm-client-id: %llu", &client);
                std::sscanf(line, "drm-memory-vram: %llu", &vram);
                std::sscanf(line, "drm-memory-gtt: %llu", &gtt);
            }
            std::fclose(file);
            if (drm && std::find(clients.begin(), clients.end(), client) == clients.end()) {
                clients.push_back(client);
                vram_kib += vram;
                gtt_kib += gtt;
            }
        }
        closedir(dir);
    }
    unsigned long long size_pages = 0, rss_pages = 0;
    if (FILE* statm = std::fopen("/proc/self/statm", "r")) {
        if (std::fscanf(statm, "%llu %llu", &size_pages, &rss_pages) != 2) {
            rss_pages = 0;
        }
        std::fclose(statm);
    }
    const u64 rss = u64(rss_pages) * u64(sysconf(_SC_PAGESIZE));
    const u64 device = BbStats::device_alloc_bytes.load() - BbStats::device_free_bytes.load();
    u64 vma_blocks = 0, vma_used = 0;
    Vulkan::VmaDeviceUsage(vma_blocks, vma_used);
    std::printf("Memory: VRAM %llu MiB, GTT %llu MiB, RSS %llu MiB; Vulkan memory %llu MiB "
                "allocated (VMA blocks %llu MiB, %llu MiB of them used); Vulkan images %llu MiB; "
                "cached images %llu MiB in %llu; guest blocks in VRAM %llu MiB allocated, "
                "%llu MiB of it unused (%llu MiB moved back idle, %llu MiB unmapped, %llu MiB freed; %llu chunks, %llu emptied, blocks kept: %llu GPU-written, %llu not direct memory); texture collector: usage %llu MiB, starts at %llu MiB, %llu images freed, %llu GPU-written kept\n",
                (unsigned long long)(vram_kib >> 10), (unsigned long long)(gtt_kib >> 10),
                (unsigned long long)(rss >> 20), (unsigned long long)(device >> 20),
                (unsigned long long)(vma_blocks >> 20), (unsigned long long)(vma_used >> 20),
                (unsigned long long)(BbStats::vk_image_bytes.load() >> 20),
                (unsigned long long)(BbStats::live_image_bytes.load() >> 20),
                (unsigned long long)BbStats::live_images.load(),
                (unsigned long long)(BbStats::residency_alloc_bytes.load() >> 20),
                (unsigned long long)(BbStats::residency_unused_bytes.load() >> 20),
                (unsigned long long)(BbStats::vram_idle_bytes.exchange(0) >> 20),
                (unsigned long long)(BbStats::vram_unmapped_bytes.exchange(0) >> 20),
                (unsigned long long)(BbStats::vram_chunks_freed_bytes.exchange(0) >> 20),
                (unsigned long long)BbStats::residency_chunk_count.load(),
                (unsigned long long)BbStats::evacuations.exchange(0),
                (unsigned long long)BbStats::evac_kept_gpu.exchange(0),
                (unsigned long long)BbStats::evac_kept_other.exchange(0),
                (unsigned long long)(BbStats::gc_used_bytes.load() >> 20),
                (unsigned long long)(BbStats::gc_trigger_bytes.load() >> 20),
                (unsigned long long)BbStats::gc_freed_images.exchange(0),
                (unsigned long long)BbStats::gc_kept_images.exchange(0));
#endif
}

static void LogRam() {
    BbPlatform::Memory m;
    if (!BbPlatform::GetMemory(m)) {
        return;
    }
    const auto mib = [](u64 bytes) { return static_cast<unsigned long long>(bytes >> 20); };
    std::printf("Memory: game %llu MiB in RAM (%llu MiB committed, peak %llu MiB); PC %llu of %llu "
                "MiB free, %llu MiB commit left; GPU images %llu MiB, %llu MiB cached in %llu\n",
                mib(m.working_set), mib(m.private_bytes), mib(m.peak_working_set), mib(m.free_phys),
                mib(m.total_phys), mib(m.commit_left), mib(BbStats::vk_image_bytes.load()),
                mib(BbStats::live_image_bytes.load()),
                static_cast<unsigned long long>(BbStats::live_images.load()));
    static int reports = 0;
    if (reports++ % 5 == 0) {
        std::thread([mib] {
            BbPlatform::MemoryBreakdown b;
            if (!BbPlatform::GetMemoryBreakdown(b)) return;
            std::printf("Memory by kind: game memory %llu MiB, other mapped %llu MiB, programs and DLLs %llu MiB, "
                        "engine and driver %llu MiB (shared %llu MiB)\n",
                        mib(b.game_pool), mib(b.mapped), mib(b.images), mib(b.priv), mib(b.shared));
            std::fflush(stdout);
        }).detach();
    }
    std::fflush(stdout);
}

static void LogLoad(double seconds, u64 flips, double worst_ms, u64 slow) {
    struct Snapshot {
        u64 draws, dispatches, cpu_us, faults, tracker_faults, protects, protect_pages;
        u64 rw_found, rw_steps, sema_found, sema_steps, thread_found, thread_steps;
        u64 zpass, zpass_in_order;
    };
    static Snapshot last{};
    Snapshot now{};
    now.draws = BbStats::draws.load(std::memory_order_relaxed);
    now.dispatches = BbStats::dispatches.load(std::memory_order_relaxed);
    if (BbPlatform::Usage usage; BbPlatform::GetUsage(false, usage)) {
        now.cpu_us = usage.user_us + usage.sys_us;
        now.faults = usage.minor_faults;
    }
    now.tracker_faults = BbStats::tracker_faults.load(std::memory_order_relaxed);
    now.protects = BbStats::protect_calls.load(std::memory_order_relaxed);
    now.protect_pages = BbStats::protect_pages.load(std::memory_order_relaxed);
    AmdGpu::OcclusionDumpCounts(now.zpass, now.zpass_in_order);
    u64 rwlocks = 0, semas = 0, made = 0, finished = 0;
    sys_rwlock_census(&rwlocks, &now.rw_found, &now.rw_steps);
    sys_sema_census(&semas, &now.sema_found, &now.sema_steps);
    runtime_thread_census(&made, &finished, &now.thread_found, &now.thread_steps);
    const bool first = last.draws == 0 && last.cpu_us == 0;
    const double frames = static_cast<double>(std::max<u64>(flips, 1));
    const double secs = std::max(seconds, 1.0);
    const auto delta = [](u64 a, u64 b) { return a >= b ? a - b : a; };
    const auto per_s = [&](u64 a, u64 b) { return first ? 0.0 : double(delta(a, b)) / secs; };
    const auto steps = [](u64 found, u64 walked) {
        return found ? double(walked) / double(found) : 0.0;
    };
    std::printf("Load: %.1f FPS (%llu over 33 ms, worst %.0f ms), %.0f draws and %.0f dispatches a "
                "frame; CPU %.1f cores, %.0f page faults/s; write faults %.0f/s, protects %.0f/s "
                "(%.0f pages/s), hot pages %lld; threads %llu live of %llu, rwlocks %llu (%.1f "
                "steps, %.0f/s), semaphores %llu (%.1f steps), memory map %llu regions, heap "
                "growths %llu; occlusion dumps %.1f a frame (%.1f in order)\n",
                double(flips) / secs, static_cast<unsigned long long>(slow), worst_ms,
                first ? 0.0 : double(delta(now.draws, last.draws)) / frames,
                first ? 0.0 : double(delta(now.dispatches, last.dispatches)) / frames,
                per_s(now.cpu_us, last.cpu_us) / 1e6, per_s(now.faults, last.faults),
                per_s(now.tracker_faults, last.tracker_faults), per_s(now.protects, last.protects),
                per_s(now.protect_pages, last.protect_pages),
                static_cast<long long>(BbStats::hot_pages.load(std::memory_order_relaxed)),
                static_cast<unsigned long long>(made - finished),
                static_cast<unsigned long long>(made), static_cast<unsigned long long>(rwlocks),
                steps(delta(now.rw_found, last.rw_found), delta(now.rw_steps, last.rw_steps)),
                per_s(now.rw_found, last.rw_found), static_cast<unsigned long long>(semas),
                steps(delta(now.sema_found, last.sema_found), delta(now.sema_steps, last.sema_steps)),
                static_cast<unsigned long long>(runtime_memory_regions()),
                static_cast<unsigned long long>(runtime_heap_growths()),
                first ? 0.0 : double(delta(now.zpass, last.zpass)) / frames,
                first ? 0.0 : double(delta(now.zpass_in_order, last.zpass_in_order)) / frames);
    last = now;
}

// bbport (r23_spike-trace) ---------------------------------------------------------------------
// BB_SPIKE_TRACE=1: every flip interval (as Frame stats measures it) over 1.4x the median of the
// last 240 is broken down from counters the engine keeps anyway (bbport_toggles.h, BbSpike);
// every 5 s up to 8 "Spike (r23):" lines (the slowest such frames) and one "Spikes (r23):"
// summary, printed on the bb:Stats thread. Off: a branch per flip. On: about 90 relaxed loads a
// flip, nothing allocated per frame.
// Experiment 281474976710656 set (old): the 5 s Frame stats block and the 60 s Load/Memory lines
// run here on bb:VideoOut, in Presentation::Flip between this frame's timestamp and
// sys_video_out_flip_done: their printing time (stdout unbuffered, a pipe to the launcher) delays
// the next flip's pickup, is counted in the next frame interval and holds back the previous
// display buffer's release. Clear (default): the same code on bb:Stats, with the window's values.
// (The 5 s block runs only with BB_FRAME_STATS=1; the 60 s lines in every session.)
namespace R23 {

constexpr u64 AsyncStatsOffBit = 281474976710656ull;

/// One report at a time, on whichever thread it runs. Never destroyed (used up to exit).
static std::mutex& ReportMutex() {
    static std::mutex* const mutex = new std::mutex;
    return *mutex;
}

struct Worker {
    std::mutex mutex;
    std::condition_variable ready;
    std::deque<std::function<void()>> jobs;
    std::atomic<u64> started{0}, busy_ns{0};
    std::atomic<bool> busy{false};
};

/// The bb:Stats thread (started on first use): runs posted reports in order.
static Worker& StatsWorker() {
    static Worker* const worker = [] {
        auto* w = new Worker; // never destroyed: the thread is detached
        std::thread([w] {
            Common::SetCurrentThreadName("bb:Stats");
            for (;;) {
                std::function<void()> job;
                {
                    std::unique_lock lock{w->mutex};
                    w->ready.wait(lock, [w] { return !w->jobs.empty(); });
                    job = std::move(w->jobs.front());
                    w->jobs.pop_front();
                }
                w->busy.store(true, std::memory_order_relaxed);
                w->started.fetch_add(1, std::memory_order_relaxed);
                const u64 start = BbSpike::NowNs();
                {
                    std::scoped_lock lock{ReportMutex()};
                    job();
                }
                w->busy_ns.fetch_add(BbSpike::NowNs() - start, std::memory_order_relaxed);
                w->busy.store(false, std::memory_order_relaxed);
            }
        }).detach();
        return w;
    }();
    return *worker;
}

static void Post(std::function<void()> job) {
    Worker& w = StatsWorker();
    {
        std::scoped_lock lock{w.mutex};
        w.jobs.push_back(std::move(job));
    }
    w.ready.notify_one();
}

/// A report: on bb:Stats; with the experiment bit set here, as before.
static void RunReport(std::function<void()> job) {
    if (BbToggle::Experiment(AsyncStatsOffBit)) {
        std::scoped_lock lock{ReportMutex()};
        job();
        return;
    }
    Post(std::move(job));
}

// bbport (r29_bursts): a BbReport::Capture's text (bbport_toggles.h), written here in one piece
// after the reports posted before it.
static void WriteCaptured(std::string&& text) {
    Post([text = std::move(text)] {
        std::fwrite(text.data(), 1, text.size(), stdout);
        std::fflush(stdout);
    });
}
[[maybe_unused]] static const bool r29_writer =
    (BbReport::writer.store(&WriteCaptured, std::memory_order_release), true);

enum Cause : u32 {
    CauseVideoOut,
    CauseStageB,
    CauseStageBEnd,
    CauseStageA,
    CauseStageAReport,
    CauseGameCpu,
    CauseGameWait,
    CauseWaits,
    CausePresent,
    CauseBinds,
    CauseFaults,
    CauseCompile,
    CauseGpu,
    Causes,
    CauseNone = Causes,
};
constexpr const char* CauseNames[Causes + 1] = {
    "bb:VideoOut's previous flip (its reports)",
    "stage B recording",
    "stage B frame end (its reports)",
    "stage A not idle (decoding, or waiting on stage B)",
    "stage A 5 s report",
    "game thread frame less its GPU waits",
    "game thread waiting for the GPU",
    "CPU waits on the GPU or copies",
    "present wait",
    "sparse binds",
    "write faults",
    "pipeline compiles",
    "GPU busy",
    "none found",
};
enum Flag : u32 {
    FlagResidency = 1,
    FlagToggle = 2,
    FlagStatsThread = 4,
    FlagGameOpen = 8,
    FlagGpu = 16,
    FlagSections = 32,
};

struct Record {
    double t_s = 0, frame_ms = 0, median_ms = 0, excess_ms = 0;
    std::array<double, Causes> ms{}; ///< per cause, ms in the interval
    double stage_b_ms = 0, game_frame_ms = 0, gpu_span_ms = 0, stats_thread_ms = 0;
    u64 gpu_frame = 0, rt_triangles = 0;
    u32 game_frames = 0, binds = 0, bind_waits = 0, compiles = 0, rt_builds = 0, tlas_builds = 0;
    u32 textures_freed = 0, flags = 0, cause = CauseNone;
    std::array<u32, 3> top{};      ///< stage B's largest BB_SECTIONS rows ("packet" left out)
    std::array<float, 3> top_ms{};
    // bbport (r27_flush-split): stage B's three largest Flush split steps in the interval (own
    // ms summed over its tasks), its longest task and that task's kind, bb:Motion's rescans.
    std::array<u32, 3> split_top{};
    std::array<float, 3> split_ms{};
    float split_task_ms = 0, motion_scan_ms = 0, motion_busy_ms = 0, motion_wake_max_ms = 0;
    const char* split_kind = nullptr;
    u32 motion_scans = 0;
    // bbport (r29_bursts): stage A's DrawPipe waits for stage B, stage B's packets run, the
    // longest delay from a guest submission queued while stage A idled to stage A running (and
    // how many), staging buffers freed.
    float a_wait_ms = 0, pickup_ms = 0;
    u32 b_packets = 0, pickups = 0, staging_freed = 0;
    // bbport (r35_pending-ops): the interval's longest PopPendingOperations call: ms, operations
    // run, frees carried, frees waiting after the last call, its costliest kind (count, ms), its
    // longest operation (kind, ms).
    float pend_ms = 0, pend_kind_ms = 0, pend_op_ms = 0;
    u32 pend_ops = 0, pend_carried = 0, pend_kind_ops = 0, pend_waiting = 0;
    const char* pend_kind = nullptr;
    const char* pend_op_kind = nullptr;
};

constexpr u32 MedianFrames = 240;
constexpr u32 MedianBins = 1024; ///< 0.1 ms each; the last one holds everything longer
constexpr u32 Delay = 6;         ///< flips a record waits for its GPU time (four frames late)
constexpr u32 Worst = 8;

struct Trace {
    bool started = false;
    u64 last_ns = 0, ns0 = 0, tsc0 = 0, window_ns = 0, onflip_ns = 0;
    double tsc_per_ns = 0;
    // counters at the last flip
    u64 b_busy = 0, b_end = 0, a_idle = 0, a_print = 0, game_frames = 0, game_wait = 0;
    std::array<u64, 4> waits{};
    u64 present = 0, binds = 0, bind_waits = 0, bind_ns = 0, faults = 0, compile_ns = 0;
    u64 compiles = 0, rt_builds = 0, rt_tris = 0, tlas = 0, textures = 0, gpu_read = 0;
    u64 stats_started = 0, stats_ns = 0, experiments = 0, disabled = 0;
    u32 second = 0;
    std::array<u64, BbSections::Count> sections{};
    // bbport (r27_flush-split): counters at the last flip, and at the 600-flip window's start
    std::array<u64, BbSpike::Splits> split{}, split_w{}, split_long_ns_w{}, split_long_by_w{};
    std::array<u64, BbSpike::SplitKinds> split_kinds_w{};
    u64 motion_scans = 0, motion_scan_ns = 0, motion_scans_w = 0, motion_scan_ns_w = 0;
    u64 motion_busy = 0, motion_busy_w = 0, motion_wakes_w = 0, motion_wake_ns_w = 0;
    float motion_wake_max_w = 0; ///< ms, the longest per-flip value in the 600-flip window
    u64 split_long_w = 0, split_long_flush_w = 0;
    u32 split_frames = 0;
    u64 a_wait = 0, b_packets = 0, pickups = 0, staging_freed = 0; // bbport (r29_bursts)
    // bbport (r35_pending-ops): at the 600-flip window's start
    std::array<u64, BbSpike::PendingKinds> pend_count_w{}, pend_ns_w{};
    u64 pend_carried_w = 0;
    // running median of the last MedianFrames intervals (histogram, the median's bin followed)
    std::array<u16, MedianBins> bins{};
    std::array<u16, MedianFrames> ring{};
    u32 ring_n = 0, ring_at = 0, median_bin = 0, below = 0;
    // records waiting for their GPU time, then judged
    std::array<Record, Delay> delay{};
    u32 delay_n = 0, delay_at = 0;
    std::array<double, Causes> usual{}; ///< running average of each column, non-spike frames
    std::array<bool, Causes> usual_set{};
    // this window
    u32 frames = 0, spikes = 0;
    std::array<u32, Causes + 1> by_cause{};
    std::array<Record, Worst> worst{};
    u32 worst_n = 0;
};
static Trace trace; // bb:VideoOut only

/// Counters the Frame stats block resets (exchange(0)) count from 0 again: the part since then.
static u64 Delta(u64 now, u64& last) {
    const u64 delta = now >= last ? now - last : now;
    last = now;
    return delta;
}

static void AddInterval(Trace& t, double ms) {
    const u32 bin = u32(std::min<double>(ms * 10.0, double(MedianBins - 1)));
    if (t.ring_n == MedianFrames) {
        const u32 old = t.ring[t.ring_at];
        --t.bins[old];
        t.below -= old < t.median_bin ? 1 : 0;
    } else {
        ++t.ring_n;
    }
    t.ring[t.ring_at] = u16(bin);
    t.ring_at = (t.ring_at + 1) % MedianFrames;
    ++t.bins[bin];
    t.below += bin < t.median_bin ? 1 : 0;
    const u32 k = t.ring_n / 2; // sorted[n / 2], as Frame pacing takes it
    while (t.below > k) {
        --t.median_bin;
        t.below -= t.bins[t.median_bin];
    }
    while (t.below + t.bins[t.median_bin] <= k) {
        t.below += t.bins[t.median_bin];
        ++t.median_bin;
    }
}

static double MedianMs(const Trace& t) {
    return (t.median_bin + 0.5) * 0.1;
}

static void Judge(Trace& t, Record& r) {
    ++t.frames;
    if (r.median_ms <= 0.0 || r.frame_ms <= 1.4 * r.median_ms) {
        for (u32 c = 0; c < Causes; ++c) {
            if (c == CauseGpu && !(r.flags & FlagGpu)) {
                continue;
            }
            t.usual[c] = t.usual_set[c] ? t.usual[c] + (r.ms[c] - t.usual[c]) / 64.0 : r.ms[c];
            t.usual_set[c] = true;
        }
        return;
    }
    ++t.spikes;
    double best = 0.0;
    r.cause = CauseNone;
    for (u32 c = 0; c < Causes; ++c) {
        if (c == CauseGpu && !(r.flags & FlagGpu)) {
            continue;
        }
        const double excess = r.ms[c] - (t.usual_set[c] ? t.usual[c] : 0.0);
        if (excess > best) {
            best = excess;
            r.cause = c;
        }
    }
    r.excess_ms = best;
    if (best < 0.25 * (r.frame_ms - r.median_ms)) {
        r.cause = CauseNone; // nothing measured explains a quarter of the extra time
    }
    ++t.by_cause[r.cause];
    if (t.worst_n < Worst) {
        t.worst[t.worst_n++] = r;
        return;
    }
    u32 lowest = 0;
    for (u32 i = 1; i < Worst; ++i) {
        lowest = t.worst[i].frame_ms < t.worst[lowest].frame_ms ? i : lowest;
    }
    if (r.frame_ms > t.worst[lowest].frame_ms) {
        t.worst[lowest] = r;
    }
}

static void PrintSpike(const Record& r) {
    char line[2560]; // bbport (r35_pending-ops): was 2048 (r29_bursts), 1536
    int n = 0;
    const auto put = [&](int written) {
        n = std::min<int>(n + std::max(written, 0), int(sizeof(line)) - 1);
    };
    const auto& m = r.ms;
    put(std::snprintf(line + n, sizeof(line) - n,
                      "Spike (r23): %.1f ms frame at %.1f s, median %.2f ms (%.2fx); largest: %s",
                      r.frame_ms, r.t_s, r.median_ms, r.frame_ms / r.median_ms,
                      CauseNames[r.cause]));
    if (r.cause != CauseNone) {
        put(std::snprintf(line + n, sizeof(line) - n, " (+%.1f ms over its usual)", r.excess_ms));
    }
    put(std::snprintf(line + n, sizeof(line) - n,
                      "; ms in it: VideoOut's previous flip %.1f, stage B %.1f (frame end %.1f)",
                      m[CauseVideoOut], r.stage_b_ms, m[CauseStageBEnd]));
    if (r.flags & FlagSections) {
        for (u32 i = 0; i < 3 && r.top_ms[i] > 0.0f; ++i) {
            put(std::snprintf(line + n, sizeof(line) - n, "%s%s %.1f", i ? ", " : " [",
                              BbSections::Names[r.top[i]], double(r.top_ms[i])));
        }
        put(std::snprintf(line + n, sizeof(line) - n, "%s", r.top_ms[0] > 0.0f ? "]" : ""));
    }
    put(std::snprintf(line + n, sizeof(line) - n,
                      ", stage A not idle %.1f (5 s report %.1f), game frame %.1f%s (less its "
                      "GPU waits %.1f, its GPU waits %.1f, %u ended), waits on the GPU or copies "
                      "%.1f, present wait "
                      "%.1f, sparse binds %u (%u waited) %.1f, write faults %.1f, compiles %u %.1f",
                      m[CauseStageA], m[CauseStageAReport], r.game_frame_ms,
                      (r.flags & FlagGameOpen) ? " still open" : "", m[CauseGameCpu],
                      m[CauseGameWait], r.game_frames, m[CauseWaits], m[CausePresent], r.binds,
                      r.bind_waits, m[CauseBinds], m[CauseFaults], r.compiles, m[CauseCompile]));
    if (r.flags & FlagGpu) {
        put(std::snprintf(line + n, sizeof(line) - n, ", GPU busy %.1f of %.1f", m[CauseGpu],
                          r.gpu_span_ms));
    }
    // bbport (r27_flush-split): stage B's three largest steps by own time in this interval
    put(std::snprintf(line + n, sizeof(line) - n, "; flush split:"));
    for (u32 i = 0; i < 3 && r.split_ms[i] > 0.0f; ++i) {
        put(std::snprintf(line + n, sizeof(line) - n, "%s %s %.2f", i ? "," : "",
                          BbSpike::SplitNames[r.split_top[i]], double(r.split_ms[i])));
    }
    put(std::snprintf(line + n, sizeof(line) - n,
                      "%s (longest stage B task %s %.2f ms), bb:Motion busy %.2f ms, longest "
                      "wake %.2f ms, index rescans %u (%.2f ms)",
                      r.split_ms[0] > 0.0f ? "" : " none",
                      r.split_task_ms > 0.0f && r.split_kind ? r.split_kind : "none",
                      double(r.split_task_ms), double(r.motion_busy_ms),
                      double(r.motion_wake_max_ms), r.motion_scans, double(r.motion_scan_ms)));
    // bbport (r29_bursts)
    put(std::snprintf(line + n, sizeof(line) - n,
                      "; stage A waited for stage B %.1f ms, stage B ran %u packets, stage A "
                      "picked up guest submissions queued while it idled %u times, after %.2f ms "
                      "at most, staging buffers freed %u",
                      double(r.a_wait_ms), r.b_packets, r.pickups, double(r.pickup_ms),
                      r.staging_freed));
    // bbport (r35_pending-ops)
    if (r.pend_ms > 0.0f) {
        put(std::snprintf(line + n, sizeof(line) - n,
                          "; pending ops (r35): longest call %.2f ms ran %u (carried %u to later "
                          "frames, %u waiting), costliest kind %s %u ops %.2f ms, longest one %s "
                          "%.2f ms",
                          double(r.pend_ms), r.pend_ops, r.pend_carried, r.pend_waiting,
                          r.pend_kind ? r.pend_kind : "-", r.pend_kind_ops,
                          double(r.pend_kind_ms), r.pend_op_kind ? r.pend_op_kind : "-",
                          double(r.pend_op_ms)));
    } else {
        put(std::snprintf(line + n, sizeof(line) - n, "; pending ops (r35): none run (%u waiting)",
                          r.pend_waiting));
    }
    put(std::snprintf(line + n, sizeof(line) - n, "; events:"));
    const int before = n;
    if (r.flags & FlagResidency) {
        put(std::snprintf(line + n, sizeof(line) - n, " residency second,"));
    }
    if (r.flags & FlagToggle) {
        put(std::snprintf(line + n, sizeof(line) - n, " toggles changed,"));
    }
    if (r.flags & FlagStatsThread) {
        put(std::snprintf(line + n, sizeof(line) - n, " bb:Stats printing (%.1f ms),",
                          r.stats_thread_ms));
    }
    if (r.rt_builds || r.tlas_builds) {
        put(std::snprintf(line + n, sizeof(line) - n,
                          " ray tracing full builds %u BLAS (%llu triangles) %u TLAS,", r.rt_builds,
                          static_cast<unsigned long long>(r.rt_triangles), r.tlas_builds));
    }
    if (r.textures_freed) {
        put(std::snprintf(line + n, sizeof(line) - n, " textures freed %u,", r.textures_freed));
    }
    if (n == before) {
        put(std::snprintf(line + n, sizeof(line) - n, " none,"));
    }
    line[n - 1] = '\n'; // the last comma
    std::fwrite(line, 1, size_t(n), stdout);
}

static void PrintWindow(std::array<Record, Worst>& worst, u32 count, u32 frames, u32 spikes,
                        const std::array<u32, Causes + 1>& by_cause, double median) {
    std::sort(worst.begin(), worst.begin() + count,
              [](const Record& a, const Record& b) { return a.frame_ms > b.frame_ms; });
    for (u32 i = 0; i < count; ++i) {
        PrintSpike(worst[i]);
    }
    char line[1024];
    int n = 0;
    const auto put = [&](int written) {
        n = std::min<int>(n + std::max(written, 0), int(sizeof(line)) - 1);
    };
    put(std::snprintf(line, sizeof(line),
                      "Spikes (r23): %u frames over 1.4x median (of %u judged, median now %.2f "
                      "ms); by largest cause:",
                      spikes, frames, median));
    std::array<bool, Causes + 1> shown{};
    for (u32 round = 0; round <= Causes; ++round) {
        u32 pick = Causes + 1;
        for (u32 c = 0; c <= Causes; ++c) {
            if (!shown[c] && by_cause[c] && (pick > Causes || by_cause[c] > by_cause[pick])) {
                pick = c;
            }
        }
        if (pick > Causes) {
            break;
        }
        shown[pick] = true;
        put(std::snprintf(line + n, sizeof(line) - n, " %s %u,", CauseNames[pick], by_cause[pick]));
    }
    if (spikes == 0) {
        put(std::snprintf(line + n, sizeof(line) - n, " -,"));
    }
    line[n - 1] = '\n';
    std::fwrite(line, 1, size_t(n), stdout);
    std::fflush(stdout);
}

// bbport (r27_flush-split): every 600 flips, on bb:Stats: the stage B tasks over 2 ms in those
// frames (by largest step, by task, their own ms by step), all stage B tasks' own ms by step, and
// bb:Motion's index rescans.
struct SplitWindow {
    std::array<double, BbSpike::Splits> all_ms{}, long_ms{}, long_by{};
    std::array<double, BbSpike::SplitKinds> kinds{};
    std::array<const char*, BbSpike::SplitKinds> kind_names{};
    u64 tasks = 0, flushed = 0, scans = 0, wakes = 0;
    double scan_ms = 0, busy_ms = 0, wake_ms = 0, wake_max_ms = 0;
    // bbport (r35_pending-ops): PopPendingOperations in the window, by kind; frees carried, the
    // longest wait (frames), the most waiting after a call; the experiment bit at the end.
    std::array<const char*, BbSpike::PendingKinds> pend_names{};
    std::array<u64, BbSpike::PendingKinds> pend_ops{};
    std::array<double, BbSpike::PendingKinds> pend_ms{};
    u64 pend_carried = 0, pend_wait_max = 0, pend_backlog_max = 0;
    bool pend_old = false;
};

/// ", name value" for each value over `floor`, largest first.
template <std::size_t N>
static void PutRanked(std::string& out, const std::array<double, N>& values,
                      const char* const* names, const char* format, double floor) {
    std::array<u32, N> order{};
    u32 count = 0;
    for (u32 i = 0; i < N; ++i) {
        if (values[i] > floor && names[i]) {
            order[count++] = i;
        }
    }
    std::sort(order.begin(), order.begin() + count,
              [&](u32 a, u32 b) { return values[a] > values[b]; });
    char item[192];
    for (u32 k = 0; k < count; ++k) {
        std::snprintf(item, sizeof(item), format, k ? "," : "", names[order[k]],
                      values[order[k]]);
        out += item;
    }
    if (count == 0) {
        out += " -";
    }
}

static void PrintSplits(const SplitWindow& w) {
    char head[256];
    std::snprintf(head, sizeof(head),
                  "Flush splits (r27): %llu stage B tasks over %.0f ms in the last 600 frames "
                  "(%llu with a Flush); by largest step:",
                  static_cast<unsigned long long>(w.tasks), double(BbSpike::SplitLongNs) / 1e6,
                  static_cast<unsigned long long>(w.flushed));
    std::string out = head;
    PutRanked(out, w.long_by, BbSpike::SplitNames, "%s %s %.0f", 0.0);
    out += "; by task:";
    PutRanked(out, w.kinds, w.kind_names.data(), "%s %s %.0f", 0.0);
    out += "; their ms by step:";
    PutRanked(out, w.long_ms, BbSpike::SplitNames, "%s %s %.1f", 0.05);
    out += "; all stage B tasks' ms by step:";
    PutRanked(out, w.all_ms, BbSpike::SplitNames, "%s %s %.1f", 0.05);
    std::snprintf(head, sizeof(head),
                  "; bb:Motion busy %.1f ms, wakes by stage B %llu (%.1f ms, longest in a frame "
                  "%.2f ms), index rescans %llu (%.1f ms)\n",
                  w.busy_ms, static_cast<unsigned long long>(w.wakes), w.wake_ms, w.wake_max_ms,
                  static_cast<unsigned long long>(w.scans), w.scan_ms);
    out += head;
    // bbport (r35_pending-ops)
    {
        u64 ops = 0;
        double ms = 0;
        std::array<u32, BbSpike::PendingKinds> order{};
        u32 count = 0;
        for (u32 k = 0; k < BbSpike::PendingKinds; ++k) {
            ops += w.pend_ops[k];
            ms += w.pend_ms[k];
            if (w.pend_ops[k] != 0 && w.pend_names[k]) {
                order[count++] = k;
            }
        }
        std::sort(order.begin(), order.begin() + count,
                  [&](u32 a, u32 b) { return w.pend_ms[a] > w.pend_ms[b]; });
        char r35[512];
        std::snprintf(r35, sizeof(r35),
                      "Pending ops (r35): %llu run in the last 600 frames (%.1f ms), %llu frees "
                      "carried to a later frame (over %.1f ms a frame; experiment "
                      "576460752303423488 %s), longest wait %llu frames, most waiting %llu; by "
                      "kind (ops, ms):",
                      static_cast<unsigned long long>(ops), ms,
                      static_cast<unsigned long long>(w.pend_carried),
                      double(BbPendingOps::BudgetNs) / 1e6, w.pend_old ? "set: none" : "clear",
                      static_cast<unsigned long long>(w.pend_wait_max),
                      static_cast<unsigned long long>(w.pend_backlog_max));
        out += r35;
        for (u32 i = 0; i < count; ++i) {
            const u32 k = order[i];
            std::snprintf(r35, sizeof(r35), "%s %s %llu %.1f", i ? "," : "", w.pend_names[k],
                          static_cast<unsigned long long>(w.pend_ops[k]), w.pend_ms[k]);
            out += r35;
        }
        out += count ? "\n" : " -\n";
    }
    std::fwrite(out.data(), 1, out.size(), stdout);
    std::fflush(stdout);
}

static void PostSplits(Trace& t) {
    constexpr auto relaxed = std::memory_order_relaxed;
    SplitWindow w;
    const auto take = [](u64 now, u64& last) {
        const u64 delta = now - last;
        last = now;
        return delta;
    };
    for (u32 s = 0; s < BbSpike::Splits; ++s) {
        w.all_ms[s] = double(take(BbSpike::split_ns[s].load(relaxed), t.split_w[s])) / 1e6;
        w.long_ms[s] =
            double(take(BbSpike::split_long_ns[s].load(relaxed), t.split_long_ns_w[s])) / 1e6;
        w.long_by[s] = double(take(BbSpike::split_long_by[s].load(relaxed), t.split_long_by_w[s]));
    }
    for (u32 k = 0; k < BbSpike::SplitKinds; ++k) {
        w.kind_names[k] = BbSpike::split_kinds[k].name.load(relaxed);
        w.kinds[k] = double(take(BbSpike::split_kinds[k].count.load(relaxed), t.split_kinds_w[k]));
    }
    w.tasks = take(BbSpike::split_long.load(relaxed), t.split_long_w);
    w.flushed = take(BbSpike::split_long_flush.load(relaxed), t.split_long_flush_w);
    w.scans = take(BbSpike::motion_scans.load(relaxed), t.motion_scans_w);
    w.scan_ms = double(take(BbSpike::motion_scan_ns.load(relaxed), t.motion_scan_ns_w)) / 1e6;
    w.busy_ms = double(take(BbSpike::motion_busy_ns.load(relaxed), t.motion_busy_w)) / 1e6;
    w.wakes = take(BbSpike::motion_wakes.load(relaxed), t.motion_wakes_w);
    w.wake_ms = double(take(BbSpike::motion_wake_ns.load(relaxed), t.motion_wake_ns_w)) / 1e6;
    w.wake_max_ms = double(std::exchange(t.motion_wake_max_w, 0.0f));
    // bbport (r35_pending-ops)
    for (u32 k = 0; k < BbSpike::PendingKinds; ++k) {
        w.pend_names[k] = BbSpike::pending_kinds[k].name.load(relaxed);
        w.pend_ops[k] = take(BbSpike::pending_kinds[k].count.load(relaxed), t.pend_count_w[k]);
        w.pend_ms[k] =
            double(take(BbSpike::pending_kinds[k].ns.load(relaxed), t.pend_ns_w[k])) / 1e6;
    }
    w.pend_carried = take(BbSpike::pending_carried.load(relaxed), t.pend_carried_w);
    w.pend_wait_max = BbSpike::pending_wait_max.exchange(0, relaxed);
    w.pend_backlog_max = BbSpike::pending_backlog_max.exchange(0, relaxed);
    w.pend_old = BbToggle::Experiment(BbPendingOps::OldBit);
    Post([w] { PrintSplits(w); });
}

/// At the start of each OnFlip (bb:VideoOut): the interval since the last one, broken down.
static u64 Flip() {
    Trace& t = trace;
    const u64 now = BbSpike::NowNs();
    const u64 tsc = __rdtsc();
    Record r;
    const double frame_ms = t.started ? double(now - t.last_ns) / 1e6 : 0.0;
    if (t.started && now - t.ns0 >= 1000000000ull) {
        t.tsc_per_ns = double(tsc - t.tsc0) / double(now - t.ns0);
    }
    const double cycle_ms = t.tsc_per_ns > 0.0 ? 1.0 / (t.tsc_per_ns * 1e6) : 0.0;
    constexpr auto relaxed = std::memory_order_relaxed;
    // Stage B: packet cycles; its display-pass frame end (reports included).
    const auto* busy = BbSpike::stage_b_busy.load(std::memory_order_acquire);
    r.stage_b_ms = double(Delta(busy ? busy->load(relaxed) : 0, t.b_busy)) * cycle_ms;
    r.ms[CauseStageBEnd] = double(Delta(BbSpike::stage_b_end_ns.load(relaxed), t.b_end)) / 1e6;
    r.ms[CauseStageB] = std::max(0.0, r.stage_b_ms - r.ms[CauseStageBEnd]);
    // Stage A: the interval less its idle time (an idle wait still open counts up to now).
    const u64 idle_done = BbSpike::stage_a_idle_ns.load(relaxed);
    const u64 idle_since = BbSpike::stage_a_idle_since.load(relaxed);
    const u64 idle = idle_done + (idle_since && now > idle_since ? now - idle_since : 0);
    const u64 idle_delta = idle > t.a_idle ? idle - t.a_idle : 0;
    t.a_idle = std::max(t.a_idle, idle);
    r.ms[CauseStageAReport] =
        double(Delta(BbSpike::stage_a_print_ns.load(relaxed), t.a_print)) / 1e6;
    r.ms[CauseStageA] =
        std::max(0.0, frame_ms - double(idle_delta) / 1e6 - r.ms[CauseStageAReport]);
    // The game thread: its longest frame (sceGnmSubmitDone to the next) that ended in this
    // interval, else the one still open; its waits for the GPU (WaitPreviousFrame and the like).
    r.game_frames = u32(Delta(BbSpike::game_frames.load(relaxed), t.game_frames));
    const u64 game_longest = BbSpike::game_max_ns.exchange(0, relaxed);
    const u64 game_last = BbSpike::game_last_ns.load(relaxed);
    if (r.game_frames != 0) {
        r.game_frame_ms = double(game_longest) / 1e6;
    } else if (game_last != 0 && now > game_last) {
        r.game_frame_ms = double(now - game_last) / 1e6;
        r.flags |= FlagGameOpen;
    }
    r.ms[CauseGameWait] = double(Delta(BbStats::gnm_frame_wait_ns.load(relaxed), t.game_wait)) / 1e6;
    r.ms[CauseGameCpu] = std::max(0.0, r.game_frame_ms - r.ms[CauseGameWait]);
    // CPU threads blocked: Scheduler::Wait on a tick, fence and copy waits (SiteWait), waits for
    // the recording threads and for the copy threads.
    const u64 waits = Delta(BbStats::tick_wait_ns.load(relaxed), t.waits[0]) +
                      Delta(BbStats::host_copies_wait_ns.load(relaxed), t.waits[1]) +
                      Delta(BbStats::sync_recording_ns.load(relaxed), t.waits[2]) +
                      Delta(BbStats::copy_threads_wait_ns.load(relaxed), t.waits[3]);
    r.ms[CauseWaits] = double(waits) / 1e6;
    r.ms[CausePresent] = double(Delta(BbStats::present_wait_ns.load(relaxed), t.present)) / 1e6;
    r.binds = u32(Delta(BbSpike::binds.load(relaxed), t.binds));
    r.bind_waits = u32(Delta(BbSpike::bind_waits.load(relaxed), t.bind_waits));
    r.ms[CauseBinds] = double(Delta(BbSpike::bind_ns.load(relaxed), t.bind_ns)) / 1e6;
    r.ms[CauseFaults] = double(Delta(BbStats::t_write_faults.load(relaxed), t.faults)) / 1e6;
    r.ms[CauseCompile] =
        double(Delta(Vulkan::g_bb_compile_ns_total.load(relaxed), t.compile_ns)) / 1e6;
    r.compiles = u32(Delta(Vulkan::g_bb_compiles_total.load(relaxed), t.compiles));
    r.rt_builds = u32(Delta(BbSpike::rt_builds.load(relaxed), t.rt_builds));
    r.rt_triangles = Delta(BbSpike::rt_build_triangles.load(relaxed), t.rt_tris);
    r.tlas_builds = u32(Delta(BbSpike::tlas_builds.load(relaxed), t.tlas));
    r.textures_freed = u32(Delta(BbStats::gc_freed_images.load(relaxed), t.textures));
    r.ms[CauseVideoOut] = double(t.onflip_ns) / 1e6; // the last OnFlip, inside this interval
    // Events: a new coarse second (the buffer cache's 1 Hz residency work), a toggle change,
    // bb:Stats printing.
    const u32 second = BbStats::coarse_second.load(relaxed);
    if (second != t.second) {
        r.flags |= FlagResidency;
        t.second = second;
    }
    const u64 experiments = __atomic_load_n(&runtime_experiment_bits, __ATOMIC_RELAXED);
    const u64 disabled = __atomic_load_n(&runtime_disabled_optimizations, __ATOMIC_RELAXED);
    if (experiments != t.experiments || disabled != t.disabled) {
        r.flags |= FlagToggle;
        t.experiments = experiments;
        t.disabled = disabled;
    }
    Worker& w = StatsWorker();
    const u64 jobs = Delta(w.started.load(relaxed), t.stats_started);
    r.stats_thread_ms = double(Delta(w.busy_ns.load(relaxed), t.stats_ns)) / 1e6;
    if (jobs != 0 || w.busy.load(relaxed) || r.stats_thread_ms > 0.0) {
        r.flags |= FlagStatsThread;
    }
    if (BbSections::Enabled()) {
        for (u32 s = 0; s < BbSections::Count; ++s) {
            const double ms = double(Delta(BbSections::cycles[s].load(relaxed), t.sections[s])) *
                              cycle_ms;
            if (s == BbSections::Packet || ms <= 0.0) {
                continue;
            }
            for (u32 i = 0; i < 3; ++i) {
                if (ms > double(r.top_ms[i])) {
                    for (u32 j = 2; j > i; --j) {
                        r.top[j] = r.top[j - 1];
                        r.top_ms[j] = r.top_ms[j - 1];
                    }
                    r.top[i] = s;
                    r.top_ms[i] = float(ms);
                    break;
                }
            }
        }
        r.flags |= cycle_ms > 0.0 ? FlagSections : 0u;
    }
    // bbport (r27_flush-split): stage B's own time by step in this interval (the three largest),
    // its longest task, bb:Motion's index rescans.
    for (u32 s = 0; s < BbSpike::Splits; ++s) {
        const double ms = double(Delta(BbSpike::split_ns[s].load(relaxed), t.split[s])) / 1e6;
        for (u32 i = 0; i < 3; ++i) {
            if (ms > double(r.split_ms[i])) {
                for (u32 j = 2; j > i; --j) {
                    r.split_top[j] = r.split_top[j - 1];
                    r.split_ms[j] = r.split_ms[j - 1];
                }
                r.split_top[i] = s;
                r.split_ms[i] = float(ms);
                break;
            }
        }
    }
    r.split_task_ms = float(double(BbSpike::split_max_ns.exchange(0, relaxed)) / 1e6);
    r.split_kind = BbSpike::split_max_kind.load(relaxed);
    r.motion_scans = u32(Delta(BbSpike::motion_scans.load(relaxed), t.motion_scans));
    r.motion_scan_ms =
        float(double(Delta(BbSpike::motion_scan_ns.load(relaxed), t.motion_scan_ns)) / 1e6);
    r.motion_busy_ms =
        float(double(Delta(BbSpike::motion_busy_ns.load(relaxed), t.motion_busy)) / 1e6);
    r.motion_wake_max_ms = float(double(BbSpike::motion_wake_max_ns.exchange(0, relaxed)) / 1e6);
    t.motion_wake_max_w = std::max(t.motion_wake_max_w, r.motion_wake_max_ms);
    // bbport (r29_bursts): stage A's waits for stage B, stage B's packets, stage A's pickups,
    // staging frees.
    r.a_wait_ms = float(double(Delta(BbSpike::stage_a_wait_ns.load(relaxed), t.a_wait)) / 1e6);
    const auto* packets = BbSpike::stage_b_packets.load(std::memory_order_acquire);
    r.b_packets = u32(Delta(packets ? packets->load(relaxed) : 0, t.b_packets));
    r.pickups = u32(Delta(BbSpike::stage_a_pickups.load(relaxed), t.pickups));
    r.pickup_ms = float(double(BbSpike::stage_a_pickup_max_ns.exchange(0, relaxed)) / 1e6);
    r.staging_freed = u32(Delta(BbSpike::staging_freed.load(relaxed), t.staging_freed));
    // bbport (r35_pending-ops): the longest PopPendingOperations call since the last flip
    r.pend_ms =
        float(double(BbSpike::pending_call_ns.exchange(0, std::memory_order_acquire)) / 1e6);
    if (r.pend_ms > 0.0f) {
        r.pend_ops = BbSpike::pending_call_ops.load(relaxed);
        r.pend_carried = BbSpike::pending_call_carried.load(relaxed);
        r.pend_kind = BbSpike::pending_call_kind.load(relaxed);
        r.pend_kind_ops = BbSpike::pending_call_kind_ops.load(relaxed);
        r.pend_kind_ms = float(double(BbSpike::pending_call_kind_ns.load(relaxed)) / 1e6);
        r.pend_op_kind = BbSpike::pending_call_op_kind.load(relaxed);
        r.pend_op_ms = float(double(BbSpike::pending_call_op_ns.load(relaxed)) / 1e6);
    }
    r.pend_waiting = u32(BbSpike::pending_backlog.load(relaxed));
    // GPU time (BB_GPU_PROFILE=1): frames read since the last flip, given to waiting records.
    r.gpu_frame = BbStats::gpu_frames.load(relaxed);
    const u64 written = BbSpike::gpu_written.load(std::memory_order_acquire);
    if (written - t.gpu_read > BbSpike::gpu.size()) {
        t.gpu_read = written - BbSpike::gpu.size();
    }
    for (; t.gpu_read < written; ++t.gpu_read) {
        const auto& e = BbSpike::gpu[t.gpu_read % BbSpike::gpu.size()];
        const u64 frame = e.frame.load(relaxed);
        for (u32 i = 0; i < t.delay_n; ++i) {
            Record& d = t.delay[i];
            if (d.gpu_frame == frame && !(d.flags & FlagGpu)) {
                d.ms[CauseGpu] = double(e.busy_ns.load(relaxed)) / 1e6;
                d.gpu_span_ms = double(e.span_ns.load(relaxed)) / 1e6;
                d.flags |= FlagGpu;
                break;
            }
        }
    }
    if (!t.started) {
        t.started = true;
        t.ns0 = t.window_ns = t.last_ns = now;
        t.tsc0 = tsc;
        Post([] {
            std::printf("Spike trace (r23): on; a frame is a flip interval on bb:VideoOut over 1.4x "
                        "the median of the last %u, judged %u flips later; stage B sections need "
                        "BB_SECTIONS=1, write faults BB_FRAME_STATS=1, GPU busy BB_GPU_PROFILE=1 "
                        "(frame matched within about one); Frame stats printed on %s "
                        "(experiment 281474976710656)\n",
                        MedianFrames, Delay,
                        BbToggle::Experiment(AsyncStatsOffBit) ? "bb:VideoOut, set" : "bb:Stats, clear");
        });
        Post([] { // bbport (r27_flush-split)
            std::printf("Flush split (r27): on; each Spike line ends with stage B's three largest "
                        "steps by own time (Rasterizer::Flush and what it calls, OnSubmit's calls, "
                        "the tasks' own code; ms summed over the interval's tasks), its longest "
                        "task, bb:Motion's busy time, its longest wake by stage B and its index "
                        "rescans; every 600 flips a \"Flush splits (r27):\" line for the stage B "
                        "tasks over %.0f ms\n",
                        double(BbSpike::SplitLongNs) / 1e6);
        });
        Post([] { // bbport (r29_bursts)
            std::printf("Report writes (r29): stage B's 600-frame reports (frame end: Froyok "
                        "bloom, Draw cost, Sun atlas, Uniform buffers; the two scene proxy tables) "
                        "written on %s (experiment 9007199254740992); each Spike line also gives "
                        "stage A's waits for stage B, stage B's packets, stage A's pickups of "
                        "guest submissions and staging buffers freed; flush split step \"staging "
                        "trim\"\n",
                        BbToggle::Experiment(BbReport::InlineBit) ? "stage B, set"
                                                                  : "bb:Stats, clear");
        });
        Post([] { // bbport (r35_pending-ops)
            std::printf("Pending ops (r35): on; each Spike line gives the interval's longest "
                        "Scheduler::PopPendingOperations call (operations run, frees carried and "
                        "waiting, its costliest kind, its longest operation); every 600 flips a "
                        "\"Pending ops (r35):\" line by kind; frees past %.1f ms a frame carried "
                        "to the next frames: %s (experiment 576460752303423488)\n",
                        double(BbPendingOps::BudgetNs) / 1e6,
                        BbToggle::Experiment(BbPendingOps::OldBit) ? "no, set" : "yes, clear");
        });
        return now;
    }
    r.t_s = double(now - t.ns0) / 1e9;
    r.frame_ms = frame_ms;
    if (t.ring_n >= 60) {
        r.median_ms = MedianMs(t);
    }
    AddInterval(t, frame_ms);
    if (t.delay_n == Delay) {
        Judge(t, t.delay[t.delay_at]);
    } else {
        ++t.delay_n;
    }
    t.delay[t.delay_at] = r;
    t.delay_at = (t.delay_at + 1) % Delay;
    t.last_ns = now;
    if (now - t.window_ns >= 5000000000ull) {
        Post([worst = t.worst, count = t.worst_n, frames = t.frames, spikes = t.spikes,
              by_cause = t.by_cause, median = MedianMs(t)]() mutable {
            PrintWindow(worst, count, frames, spikes, by_cause, median);
        });
        t.worst_n = t.frames = t.spikes = 0;
        t.by_cause = {};
        t.window_ns = now;
    }
    if (++t.split_frames >= 600) { // bbport (r27_flush-split)
        t.split_frames = 0;
        PostSplits(t);
    }
    return now;
}

/// Lives through OnFlip: the trace's flip at its start; its own time at the end (in the next
/// interval: printing here delays the next flip's pickup).
struct FlipScope {
    u64 start = BbSpike::on ? Flip() : 0;
    ~FlipScope() {
        if (start != 0) {
            trace.onflip_ns = BbSpike::NowNs() - start;
        }
    }
};

} // namespace R23

void OnFlip() {
    R23::FlipScope r23_flip; // bbport (r23_spike-trace)
    {
        static auto next_ram = std::chrono::steady_clock::now() + std::chrono::seconds(30);
        static auto load_start = std::chrono::steady_clock::now(), load_last = load_start;
        static u64 load_flips = 0, load_slow = 0;
        static double load_worst_ms = 0.0;
        const auto flip_time = std::chrono::steady_clock::now();
        const double flip_ms =
            std::chrono::duration<double, std::milli>(flip_time - load_last).count();
        load_last = flip_time;
        ++load_flips;
        load_slow += flip_ms > 33.0;
        load_worst_ms = std::max(load_worst_ms, flip_ms);
        if (const auto now = flip_time; now >= next_ram) {
            next_ram = now + std::chrono::seconds(60);
            // bbport (r23_spike-trace): on bb:Stats (experiment 281474976710656 set: here)
            R23::RunReport([seconds = std::chrono::duration<double>(now - load_start).count(),
                            flips = load_flips, worst = load_worst_ms, slow = load_slow] {
                LogRam();
                LogLoad(seconds, flips, worst, slow);
                std::fflush(stdout);
            });
            load_start = now;
            load_flips = load_slow = 0;
            load_worst_ms = 0.0;
        }
    }

    static const bool frame_stats = EmulatorSettingsImpl::Flag("BB_FRAME_STATS", false);
    if (frame_stats) {
        using Clock = std::chrono::steady_clock;
        static Clock::time_point window_start = Clock::now(), last = window_start;
        static u32 frames;
        static double worst_ms;
        const auto now = Clock::now();
        const double frame_ms = std::chrono::duration<double, std::milli>(now - last).count();
        worst_ms = std::max(worst_ms, frame_ms);
        static std::vector<double> intervals;
        intervals.push_back(frame_ms);
        last = now;
        static u64 last_gpu_ns, last_images, last_image_bytes, last_buffer_bytes;
        static u64 last_t[6], last_minflt, last_sigf, last_pc, last_pp, last_rc, last_rp;
        const u64 pc = BbStats::protect_calls.load(), pp = BbStats::protect_pages.load(),
                  rc = BbStats::protect_revoke_calls.load(), rp = BbStats::protect_revoke_pages.load();
        const u64 minflt = BbStats::gpu_minor_faults.load(), sigf = BbStats::gpu_signal_faults.load();
        static u64 last_copy_cpu, last_copy_sys, last_copy_flt;
        const u64 copy_cpu = BbStats::t_copy_cpu.load(), copy_sys = BbStats::copy_sys_us.load(),
                  copy_flt = BbStats::copy_minflt.load();
        static u64 last_proc_flt, last_copy_ns, last_copy_bytes, last_rf, last_trf, last_twf;
        const u64 rf = BbStats::read_faults.load(), trf = BbStats::t_read_faults.load(),
                  twf = BbStats::t_write_faults.load();
        if (frame_ms > 40.0 && last_gpu_ns != 0) {
            std::printf("       fault handlers: %llu read faults %.1f ms, write faults %.1f ms\n",
                        static_cast<unsigned long long>(rf - last_rf), (trf - last_trf) / 1e6,
                        (twf - last_twf) / 1e6);
        }
        last_rf = rf;
        last_trf = trf;
        last_twf = twf;
        const u64 copy_ns = BbStats::t_copy.load(), copy_bytes = BbStats::copy_bytes.load();
        u64 proc_flt = 0;
        if (BbPlatform::Usage usage; BbPlatform::GetUsage(false, usage)) {
            proc_flt = usage.minor_faults;
        }
        const u64 t_now[6] = {BbStats::t_resident.load(), BbStats::t_protect.load(),
                              BbStats::t_image_create.load(), BbStats::t_refresh.load(),
                              BbStats::t_staging.load(), BbStats::t_host_wait.load()};
        static u64 last_draws, last_dispatches, last_subs, last_sys, last_user, last_invol, last_vol;
        const u64 draws = BbStats::draws.load(), dispatches = BbStats::dispatches.load(),
                  subs = BbStats::submissions.load(), sys_us = BbStats::gpu_sys_us.load(),
                  user_us = BbStats::gpu_user_us.load(), invol = BbStats::gpu_invol_switches.load(),
                  vol = BbStats::gpu_vol_switches.load();
        u64 gpu_ns = 0;
        if (const int clock = BbStats::gpu_thread_clock.load(); clock != -1) {
            gpu_ns = BbPlatform::ReadThreadCpuClockNs(clock);
        }
        const u64 images = BbStats::images_registered.load();
        const u64 image_bytes = BbStats::image_upload_bytes.load();
        const u64 buffer_bytes = BbStats::buffer_upload_bytes.load();
        static u64 last_compile_ns_total;
        static u32 last_compiles_total;
        const u64 compile_ns_total = Vulkan::g_bb_compile_ns_total.load();
        const u32 compiles_total = Vulkan::g_bb_compiles_total.load();
        if (frame_ms > 40.0 && last_gpu_ns != 0) {
            const double frame_compile_ms = (compile_ns_total - last_compile_ns_total) / 1e6;
            std::printf("Stall: %.1f ms frame (%s); GPU thread on CPU %.1f ms; %u pipelines "
                        "built, %.1f ms; %llu images registered, %.1f MB image uploads, %.1f MB "
                        "buffer uploads\n",
                        frame_ms,
                        frame_compile_ms >= frame_ms * 0.5 ? "pipelines built"
                        : frame_compile_ms > 0.0           ? "pipelines built, loading"
                                                           : "loading or other work",
                        (gpu_ns - last_gpu_ns) / 1e6, compiles_total - last_compiles_total,
                        frame_compile_ms, static_cast<unsigned long long>(images - last_images),
                        (image_bytes - last_image_bytes) / 1e6,
                        (buffer_bytes - last_buffer_bytes) / 1e6);
            std::printf("       %llu draws, %llu dispatches, %llu submissions; GPU thread user %.1f ms, "
                        "kernel %.1f ms, %llu preempted, %llu waits\n",
                        static_cast<unsigned long long>(draws - last_draws),
                        static_cast<unsigned long long>(dispatches - last_dispatches),
                        static_cast<unsigned long long>(subs - last_subs), (user_us - last_user) / 1e3,
                        (sys_us - last_sys) / 1e3, static_cast<unsigned long long>(invol - last_invol),
                        static_cast<unsigned long long>(vol - last_vol));
        }
        if (frame_ms > 40.0 && last_gpu_ns != 0) {
            std::printf("       ms in: resident %.1f, protect %.1f, image create %.1f, "
                        "image refresh %.1f, staging %.1f, waiting for host copies %.1f\n",
                        (t_now[0] - last_t[0]) / 1e6, (t_now[1] - last_t[1]) / 1e6,
                        (t_now[2] - last_t[2]) / 1e6, (t_now[3] - last_t[3]) / 1e6,
                        (t_now[4] - last_t[4]) / 1e6, (t_now[5] - last_t[5]) / 1e6);
            static u64 last_parts[5];
            const u64 parts[5] = {BbStats::t_image_query.load(), BbStats::t_image_alloc.load(),
                                  BbStats::t_refresh_hash.load(), BbStats::t_refresh_obtain.load(),
                                  BbStats::t_refresh_detile.load()};
            std::printf("       of which: format query %.1f, allocation %.1f; hashing %.1f, "
                        "source data %.1f, detiling %.1f\n",
                        (parts[0] - last_parts[0]) / 1e6, (parts[1] - last_parts[1]) / 1e6,
                        (parts[2] - last_parts[2]) / 1e6, (parts[3] - last_parts[3]) / 1e6,
                        (parts[4] - last_parts[4]) / 1e6);
            std::copy(std::begin(parts), std::end(parts), std::begin(last_parts));
            std::printf("       GPU thread page faults %llu (process %llu), protection faults %llu; "
                        "protect calls %llu (%llu pages), of which write-revoking %llu (%llu pages)\n",
                        static_cast<unsigned long long>(minflt - last_minflt),
                        static_cast<unsigned long long>(proc_flt - last_proc_flt),
                        static_cast<unsigned long long>(sigf - last_sigf),
                        static_cast<unsigned long long>(pc - last_pc),
                        static_cast<unsigned long long>(pp - last_pp),
                        static_cast<unsigned long long>(rc - last_rc),
                        static_cast<unsigned long long>(rp - last_rp));
        }
        last_pc = pc;
        last_pp = pp;
        last_rc = rc;
        last_rp = rp;
        last_minflt = minflt;
        if (frame_ms > 40.0 && last_gpu_ns != 0 && copy_ns > last_copy_ns) {
            std::printf("       guest copies %.1f MB in %.1f thread-ms, %.1f ms on CPU (kernel %.1f ms, "
                        "%llu page faults in large copies) (%.2f GB/s per thread)\n",
                        (copy_bytes - last_copy_bytes) / 1e6, (copy_ns - last_copy_ns) / 1e6,
                        (copy_cpu - last_copy_cpu) / 1e6, (copy_sys - last_copy_sys) / 1e3,
                        static_cast<unsigned long long>(copy_flt - last_copy_flt),
                        double(copy_bytes - last_copy_bytes) / double(copy_ns - last_copy_ns));
        }
        static FILE* const frame_log = [] () -> FILE* {
            const char* path = std::getenv("BB_FRAME_LOG");
            FILE* file = path && *path ? std::fopen(path, "w") : nullptr;
            if (file) {
                std::fprintf(file, "t_s,frame_ms,present_wait_ms,tick_wait_ms,stage_a_cpu_ms,"
                                   "images,image_mb,buffer_mb,protect_ms,resident_ms,create_ms,"
                                   "refresh_ms,write_fault_ms,read_faults,guest_copy_mb,draws,"
                                   "dispatches,submissions,compiles,preupload_mb,kernel_ms,alloc_mb,"
                                   "free_mb\n");
            }
            return file;
        }();
        if (frame_log) {
            static const auto log_start = now;
            static u64 log_twf, log_tick, log_present, log_compiles, log_rf, log_preupload;
            static u64 log_alloc, log_free;
            const u64 tick = BbStats::tick_wait_ns.load(), present = BbStats::present_wait_ns.load();
            const u64 compiles_now = Vulkan::g_bb_compiles.load();
            const auto delta = [](u64 now_value, u64& last_value) {
                const u64 d = now_value >= last_value ? now_value - last_value : now_value;
                last_value = now_value;
                return d;
            };
            std::fprintf(frame_log,
                         "%.4f,%.2f,%.2f,%.2f,%.2f,%llu,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%llu,"
                         "%.2f,%llu,%llu,%llu,%llu,%.2f,%.2f,%.1f,%.1f\n",
                         std::chrono::duration<double>(now - log_start).count(), frame_ms,
                         delta(present, log_present) / 1e6, delta(tick, log_tick) / 1e6,
                         last_gpu_ns ? (gpu_ns - last_gpu_ns) / 1e6 : 0.0,
                         static_cast<unsigned long long>(images - last_images),
                         (image_bytes - last_image_bytes) / 1e6,
                         (buffer_bytes - last_buffer_bytes) / 1e6, (t_now[1] - last_t[1]) / 1e6,
                         (t_now[0] - last_t[0]) / 1e6, (t_now[2] - last_t[2]) / 1e6,
                         (t_now[3] - last_t[3]) / 1e6, delta(twf, log_twf) / 1e6,
                         static_cast<unsigned long long>(delta(rf, log_rf)),
                         (copy_bytes - last_copy_bytes) / 1e6,
                         static_cast<unsigned long long>(draws - last_draws),
                         static_cast<unsigned long long>(dispatches - last_dispatches),
                         static_cast<unsigned long long>(subs - last_subs),
                         static_cast<unsigned long long>(delta(compiles_now, log_compiles)),
                         delta(BbStats::preupload_bytes.load(), log_preupload) / 1e6,
                         last_gpu_ns ? (sys_us - last_sys) / 1e3 : 0.0,
                         delta(BbStats::device_alloc_bytes.load(), log_alloc) / 1e6,
                         delta(BbStats::device_free_bytes.load(), log_free) / 1e6);
            static u32 unflushed = 0;
            if (++unflushed >= 120) {
                std::fflush(frame_log);
                unflushed = 0;
            }
        }
        last_copy_ns = copy_ns;
        last_copy_cpu = copy_cpu;
        last_copy_sys = copy_sys;
        last_copy_flt = copy_flt;
        last_copy_bytes = copy_bytes;
        last_proc_flt = proc_flt;
        last_sigf = sigf;
        std::copy(std::begin(t_now), std::end(t_now), std::begin(last_t));
        last_draws = draws;
        last_dispatches = dispatches;
        last_subs = subs;
        last_sys = sys_us;
        last_user = user_us;
        last_invol = invol;
        last_vol = vol;
        last_gpu_ns = gpu_ns;
        last_images = images;
        last_image_bytes = image_bytes;
        last_buffer_bytes = buffer_bytes;
        last_compile_ns_total = compile_ns_total;
        last_compiles_total = compiles_total;
        ++frames;
        const double window = std::chrono::duration<double>(now - window_start).count();
        if (window >= 5.0) {
            // bbport (r23_spike-trace): the block below, unchanged, runs on bb:Stats with this
            // window's values (experiment 281474976710656 set: here, as before).
            auto r23_report = [frames = frames, window, worst_ms = worst_ms, intervals = intervals] {
            const u32 compiles = Vulkan::g_bb_compiles.exchange(0);
            const u64 compile_ns = Vulkan::g_bb_compile_ns.exchange(0);
            const u64 direct = Vulkan::Scheduler::direct_recordings.exchange(0);
            const u64 faults = BbStats::tracker_faults.exchange(0);
            static u64 window_draws = 0, window_gpu_us = 0;
            const u64 all_draws = BbStats::draws.load();
            const u64 gpu_us = BbStats::gpu_user_us.load() + BbStats::gpu_sys_us.load();
            const double us_per_draw = all_draws > window_draws
                                           ? double(gpu_us - window_gpu_us) / (all_draws - window_draws)
                                           : 0.0;
            const double draws_per_frame = frames ? double(all_draws - window_draws) / frames : 0.0;
            window_draws = all_draws;
            window_gpu_us = gpu_us;
            std::printf("Frame stats: %.1f FPS, worst frame %.1f ms (vblank %u Hz); "
                        "%u shader/pipeline compiles, %.1f ms; %llu recorder syncs; "
                        "%.0f write faults/s, %lld hot pages; GPU thread %.2f us/draw, "
                        "%.0f draws/frame, idle %.1f%%; blocked: recorder %.1f%%, host copies "
                        "%.1f%% (%.0f/frame, %.0f/frame not needed), copy threads %.1f%%, GPU ticks %.1f%%; "
                        "reduced-size draws %.0f/frame of %.0f in the scene\n",
                        frames / window, worst_ms, EmulatorSettings.GetVblankFrequency(), compiles,
                        compile_ns / 1e6, static_cast<unsigned long long>(direct),
                        faults / window, static_cast<long long>(BbStats::hot_pages.load()),
                        us_per_draw, draws_per_frame,
                        BbStats::gpu_idle_ns.exchange(0) / (window * 1e7),
                        BbStats::sync_recording_ns.exchange(0) / (window * 1e7),
                        BbStats::host_copies_wait_ns.exchange(0) / (window * 1e7),
                        frames ? double(BbStats::host_copy_waits.exchange(0)) / frames : 0.0,
                        frames ? double(BbStats::host_copy_waits_skipped.exchange(0)) / frames : 0.0,
                        BbStats::copy_threads_wait_ns.exchange(0) / (window * 1e7),
                        BbStats::tick_wait_ns.exchange(0) / (window * 1e7),
                        frames ? double(BbStats::reduced_draws.exchange(0)) / frames : 0.0,
                        frames ? double(BbStats::scene_draws.exchange(0)) / frames : 0.0);
            {
                const double f = frames ? double(frames) : 1.0;
                const auto per_frame = [&](std::atomic<u64>& counter) {
                    return double(counter.exchange(0)) / f;
                };
                const auto ms_per_frame = [&](std::atomic<u64>& ns) {
                    return double(ns.exchange(0)) / (f * 1e6);
                };
                std::printf("Stage B waits: fences");
                for (u32 s = 0; s < BbStats::WaitSites; ++s) {
                    const double n = per_frame(BbStats::signal_waits[s]);
                    const double ms = ms_per_frame(BbStats::signal_wait_ns[s]);
                    const double skipped = per_frame(BbStats::signal_waits_skipped[s]);
                    if (n + skipped > 0.0) {
                        std::printf(" %s %.1f/frame %.3f ms", BbStats::WaitSiteNames[s], n, ms);
                        if (skipped > 0.0) {
                            std::printf(" (%.1f/frame not needed)", skipped);
                        }
                    }
                }
                std::printf("; copies");
                for (u32 s = 0; s < BbStats::WaitSites; ++s) {
                    const double n = per_frame(BbStats::copy_waits[s]);
                    const double ms = ms_per_frame(BbStats::copy_wait_ns[s]);
                    if (n > 0.0) {
                        std::printf(" %s %.1f/frame %.3f ms", BbStats::WaitSiteNames[s], n, ms);
                    }
                }
                std::printf("; fence barriers %.1f/frame; DMA into memory stored by the CPU "
                            "%.1f/frame, recorded for the GPU %.1f/frame\n",
                            per_frame(BbStats::fence_barriers), per_frame(BbStats::dma_on_cpu),
                            per_frame(BbStats::dma_on_gpu));
                double stage_b_calls = 0.0, stage_b_ms = 0.0;
                std::array<double, BbStats::ProtectKinds> kind_calls{};
                for (u32 k = 0; k < BbStats::ProtectKinds; ++k) {
                    kind_calls[k] = per_frame(BbStats::stage_b_protect_calls[k]);
                    stage_b_calls += kind_calls[k];
                    stage_b_ms += ms_per_frame(BbStats::stage_b_protect_ns[k]);
                }
                const double other_calls = per_frame(BbStats::other_protect_calls);
                const double other_ms = ms_per_frame(BbStats::other_protect_ns);
                const double deferred_pages = per_frame(BbStats::deferred_protect_pages);
                const double deferred_calls = per_frame(BbStats::deferred_protect_calls);
                const double deferred_ms = ms_per_frame(BbStats::deferred_protect_ns);
                std::printf("Stage B protects: %.1f/frame %.3f ms (uploads %.1f, textures %.1f, "
                            "other %.1f); other threads %.1f/frame %.3f ms; deferred %.0f "
                            "pages/frame, applied in %.1f calls/frame %.3f ms (bb:Protect or "
                            "copies), copies that flushed %.1f/frame, cancelled %.0f pages/frame\n",
                            stage_b_calls, stage_b_ms, kind_calls[BbStats::ProtectUpload],
                            kind_calls[BbStats::ProtectTexture], kind_calls[BbStats::ProtectOther],
                            other_calls, other_ms, deferred_pages, deferred_calls, deferred_ms,
                            per_frame(BbStats::copy_flushes),
                            per_frame(BbStats::deferred_cancelled_pages));
            }
            {
                auto& p = Vulkan::pipeline_compile_stats;
                const u64 background = p.background.exchange(0), taken = p.taken.exchange(0);
                const u64 skipped = p.skipped_draws.exchange(0);
                const u64 skipped_pipelines = p.skipped_pipelines.exchange(0);
                const u64 late = p.late_binds.exchange(0), waits = p.waits.exchange(0);
                const u64 wait_ns = p.wait_ns.exchange(0), longest = p.longest_wait_ns.exchange(0);
                if (background + skipped + late + waits != 0) {
                    std::printf("Pipelines: %llu compiled in the background (%llu by the thread "
                                "that needed them); %llu draws of %llu pipelines left out while "
                                "compiling; %llu draws/dispatches bound on the recording threads; "
                                "%llu waits, %.1f ms, longest %.1f ms\n",
                                static_cast<unsigned long long>(background),
                                static_cast<unsigned long long>(taken),
                                static_cast<unsigned long long>(skipped),
                                static_cast<unsigned long long>(skipped_pipelines),
                                static_cast<unsigned long long>(late),
                                static_cast<unsigned long long>(waits), wait_ns / 1e6,
                                longest / 1e6);
                }
            }
            VideoCore::PageManager::ReportFaultSites();
            if (const u64 notes = BbStats::cpu_write_notes.exchange(0)) {
                std::printf("Write notices: %.0f/s, %.2f MB/s (libc copies over pages the GPU side "
                            "watches)\n",
                            notes / window, BbStats::cpu_write_note_bytes.exchange(0) / (window * 1e6));
            }
            Vulkan::Breadcrumbs::PrintProgress();
            PrintMemory();
            if (const u64 in_place = BbStats::bound_in_place_bytes.exchange(0)) {
                std::printf("Buffer bindings: %.1f MB/frame in place (%.1f GPU-written), %.1f MB/frame "
                            "VRAM copies\n",
                            in_place / (frames * 1e6),
                            BbStats::bound_in_place_written_bytes.exchange(0) / (frames * 1e6),
                            BbStats::bound_vram_bytes.exchange(0) / (frames * 1e6));
            }
            {
                const u64 updates = BbStats::gpu_data_updates.exchange(0);
                const u64 copied_back = BbStats::copied_back_blocks.exchange(0);
                const u64 readbacks = BbStats::readbacks.exchange(0);
                const u64 late = BbStats::late_vram_writes.exchange(0);
                if (updates + copied_back + readbacks + late != 0) {
                    std::printf("GPU data in VRAM: %.1f command writes/s put into it, %.1f exact writes/s "
                                "(labels, CPU bytes beside GPU data), %.1f blocks/s copied back, "
                                "%.1f readbacks/s\n",
                                updates / window, late / window, copied_back / window,
                                readbacks / window);
                }
            }
            sys_equeue_report(frames);
            if (static int heap_reports = 0; ++heap_reports % 6 == 1) {
                BbHeapSites::Report();
            }
            runtime_wait_report(frames);
            for (std::size_t i = 0; i < BbStats::range_allocators.size(); ++i) {
                if (const u64 a = BbStats::range_allocators[i].load()) {
                    std::printf("%s %#llx: %llu live, %.1f MB", i ? ";" : "GPU range allocators:",
                                (unsigned long long)a, (unsigned long long)BbStats::range_live[i].load(),
                                BbStats::range_bytes[i].load() / 1e6);
                }
            }
            if (BbStats::range_allocators[0].load()) {
                std::printf("\n");
            }
            std::printf("Gnm: %.1f sceGnmSubmitDone/frame, %.1f sceGnmAreSubmitsAllowed/frame, %.1f refused/frame; "
                        "guest waited for the previous frame %.1fx %.2f ms/frame; %.1f compute queue submissions/frame\n",
                        BbStats::submit_done_calls.exchange(0) / double(frames),
                        BbStats::submits_allowed_queries.exchange(0) / double(frames),
                        BbStats::submits_refused.exchange(0) / double(frames),
                        BbStats::gnm_frame_waits.exchange(0) / double(frames),
                        BbStats::gnm_frame_wait_ns.exchange(0) / (1e6 * double(frames)),
                        BbStats::asc_submits.exchange(0) / double(frames));
            std::printf("EOP fences: %llu decoded, %llu labels written, %lld pending\n",
                        (unsigned long long)BbStats::eop_decoded.load(),
                        (unsigned long long)BbStats::eop_written.load(),
                        (long long)(BbStats::eop_decoded.load() - BbStats::eop_written.load()));
            if (const u64 early = BbStats::idle_flushes.exchange(0)) {
                std::printf("Honest labels: %.1f submissions/frame sent early (GPU idle)\n",
                            early / double(frames));
            }
            {
                uint64_t sleeps = 0, sleep_ns = 0;
                runtime_sleep_stats(&sleeps, &sleep_ns);
                if (sleeps != 0 && frames != 0) {
                    std::printf("Guest sleeps per frame: %.1f, %.2f ms\n", sleeps / double(frames),
                                sleep_ns / (frames * 1e6));
                }
            }
            if (const u64 copies = BbStats::shadow_copies.exchange(0)) {
                std::printf("Shadow copies: %.0f/frame, %.1f MB/frame (in-place data the CPU writes, "
                            "copied into VRAM for reading)\n",
                            copies / double(frames), BbStats::shadow_bytes.exchange(0) / (frames * 1e6));
            }
            if (const u64 allocs = BbStats::gpu_range_allocs.exchange(0)) {
                std::printf("Guest GPU memory: %.0f ranges/s handed out, %.2f MB/s\n", allocs / window,
                            BbStats::gpu_range_alloc_bytes.exchange(0) / (window * 1e6));
            }
            if (const u64 submits = Vulkan::Scheduler::recorded_submissions.exchange(0)) {
                const u64 segments = Vulkan::Scheduler::recorded_segments.exchange(0);
                std::printf("Recording: %.1f submissions/frame, %.2f command buffers each; "
                            "recording threads woken %.1f/frame by stage B, %.1f/frame by the "
                            "thread before them\n",
                            frames ? double(submits) / frames : 0.0, double(segments) / submits,
                            frames ? double(Vulkan::Scheduler::producer_wakes.exchange(0)) / frames : 0.0,
                            frames ? double(Vulkan::Scheduler::peer_wakes_done.exchange(0)) / frames : 0.0);
            }
            BbWaitTrace::Report(window);
            if (intervals.size() > 2) {
                std::vector<double> sorted = intervals;
                std::sort(sorted.begin(), sorted.end());
                const double median = sorted[sorted.size() / 2];
                double sum = 0, sq = 0;
                u32 spikes = 0;
                for (const double ms : intervals) {
                    sum += ms;
                    sq += ms * ms;
                    spikes += ms > 1.5 * median;
                }
                const double mean = sum / intervals.size();
                std::printf("Frame pacing: median %.2f ms, stddev %.2f ms, p99 %.2f ms, "
                            "%u frames over 1.5x median\n",
                            median, std::sqrt(std::max(0.0, sq / intervals.size() - mean * mean)),
                            sorted[std::min(sorted.size() - 1, sorted.size() * 99 / 100)], spikes);
            }
            };
            R23::RunReport(std::move(r23_report));
            intervals.clear();
            window_start = now;
            frames = 0;
            worst_ms = 0;
        }
    }
}

} // namespace LanternFrameReport
