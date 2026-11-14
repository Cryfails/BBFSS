#pragma once
#include <array>
#include <atomic>
#include <csetjmp>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstdarg> // bbport (r29_bursts): BbReport
#include <cstdio>
#include <string>
#include "bbport_settings.h" // bbport (r39_master-debug): DebugSwitchesAtStart, header-only

extern "C" std::uint64_t runtime_disabled_optimizations;
extern "C" std::uint64_t runtime_experiment_bits;
#ifdef _WIN32
struct alignas(16) BbRecoverBuf {
    unsigned char registers[256];
};
extern "C" __thread BbRecoverBuf* runtime_fault_recover;
extern "C" int runtime_setjmp(BbRecoverBuf* buf) __attribute__((returns_twice));
#define BB_RECOVER_SET(buf) runtime_setjmp(&(buf))
#else
typedef sigjmp_buf BbRecoverBuf;
extern "C" __thread BbRecoverBuf* runtime_fault_recover;
#define BB_RECOVER_SET(buf) sigsetjmp(buf, 0)
#endif
inline thread_local bool bb_fault_recovers_only = false;

namespace BbToggle {
enum : std::uint64_t {
    RegionCache = 1,
    FetchShaderCache = 2,
    PageTrackingEarlyExit = 4,
    PendingPollLimit = 8,
    ThreadedRecording = 16,
    ImageDescCache = 32,
    LockFreeUploadCheck = 64,
    FindImageCache = 128,
    DeferredUploads = 256,
    AccessMemo = 512,
    TextureBindingMemo = 1024,
    CoarseReadTracking = 2048,
    PreparedResources = 4096,
    DrawPreparation = 8192,
    DeferredStreamCopies = 16384,
    HotPages = 32768,
    FaultWindow = 65536,
    ParallelCopies = 131072,
    AsyncFences = 262144,
    PoolSmallCopies = 524288,
    RecordPrefetch = 1ull << 32,
    TextureViewMemo = 1ull << 33,
    TextureBindHelper = 1ull << 34,
    EarlyDrawInputs = 1ull << 35,
    ConstantRing = 1ull << 36,
    DrawPipeline = 1ull << 37,
    PipelinedTasks = 1ull << 38,
    PendingFenceWaits = 1ull << 39,
    PipelinedDispatch = 1ull << 40,
    RecorderFences = 1ull << 41,
    PipelinedMemoryWrites = 1ull << 42,
    MultiCopyShader = 1ull << 43,
    RenderStateMemo = 1ull << 44,
    TextureSetMemo = 1ull << 45,
    PipelinedIndirectDraws = 1ull << 46,
    SceneAttachmentsOnly = 1ull << 47,
    SampleSceneProxies = 1ull << 48,
    OrderedGuestWrites = 1ull << 49,
    SceneHalfRes = 1ull << 50,
    UpdateImageFastPath = 1u << 30,
    TextureCollector = 1ull << 31,
    TaaTonemapBlend = 1ull << 51,
    TaaClip = 1ull << 52,
    TaaVariance = 1ull << 53,
    TaaFilter = 1ull << 54,
    TaaKeepNearerHistory = 1ull << 55,
    Fsr4MotionYFlip = 1ull << 56,
    SceneMipBias = 1ull << 57,
    ParallelRecording = 1ull << 58,
    ReadbackQueue = 1ull << 59,
    CameraOwnInverse = 1ull << 60,
    ForcedAniso = 1ull << 61,
    CameraYFlip = 1ull << 62,
    Fsr4EncodedInput = 1ull << 63,
};
inline bool Disabled(std::uint64_t bit) {
    return (__atomic_load_n(&runtime_disabled_optimizations, __ATOMIC_RELAXED) & bit) != 0;
}
inline bool Experiment(std::uint64_t bit) {
    return (__atomic_load_n(&runtime_experiment_bits, __ATOMIC_RELAXED) & bit) != 0;
}
}

namespace BbStats {
inline std::atomic<std::uint64_t> tracker_faults{0};
inline std::atomic<std::uint64_t> cpu_write_notes{0}, cpu_write_note_bytes{0};
inline std::atomic<std::uint64_t> gpu_range_allocs{0}, gpu_range_alloc_bytes{0};
inline std::atomic<std::uint64_t> bound_in_place_bytes{0}, bound_vram_bytes{0};
inline std::atomic<std::uint64_t> bound_in_place_written_bytes{0};
inline std::atomic<std::uint64_t> gpu_data_updates{0}, copied_back_blocks{0}, readbacks{0};
inline std::atomic<std::uint64_t> late_vram_writes{0};
inline std::atomic<std::uint64_t> shadow_copies{0}, shadow_bytes{0};
inline std::atomic<std::uint64_t> idle_flushes{0};
inline std::atomic<std::uint64_t> eop_decoded{0}, eop_written{0};
inline std::atomic<std::uint64_t> submits_allowed_queries{0}, submits_refused{0}, submit_done_calls{0};
inline std::atomic<std::uint64_t> gnm_frame_waits{0}, gnm_frame_wait_ns{0};
inline std::atomic<std::uint64_t> asc_submits{0};
inline std::array<std::atomic<std::uint64_t>, 4> range_allocators{}, range_live{}, range_bytes{};
inline std::atomic<std::int64_t> hot_pages{0};
inline std::atomic<std::uint64_t> images_registered{0};
inline std::atomic<std::uint64_t> image_upload_bytes{0};
inline std::atomic<std::uint64_t> buffer_upload_bytes{0};
inline std::atomic<int> gpu_thread_clock{-1};
inline std::atomic<std::uint64_t> draws{0}, dispatches{0}, submissions{0};
inline std::atomic<std::uint64_t> gpu_frames{0};
inline std::atomic<std::uint64_t> t_resident{0}, t_protect{0}, t_image_create{0}, t_refresh{0},
    t_staging{0}, t_host_wait{0}, t_copy{0}, copy_bytes{0}, t_read_faults{0}, read_faults{0},
    t_write_faults{0}, t_copy_cpu{0}, copy_sys_us{0}, copy_minflt{0};
inline std::atomic<std::uint64_t> t_image_query{0}, t_image_alloc{0}, t_refresh_hash{0},
    t_refresh_obtain{0}, t_refresh_detile{0};
inline const bool enabled = [] {
    // bbport (r39_master-debug): this runs during static initialization, before the settings
    // load: lantern.ini's debug_frame_stats=1 becomes the variable first.
    BbSettings::DebugSwitchesAtStart();
    const char* env = std::getenv("BB_FRAME_STATS");
    return env && env[0] == '1';
}();
struct Timer {
    std::atomic<std::uint64_t>& total;
    std::chrono::steady_clock::time_point start =
        enabled ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    ~Timer() {
        if (!enabled) {
            return;
        }
        total.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now() - start)
                            .count(),
                        std::memory_order_relaxed);
    }
};
inline std::atomic<std::uint64_t> gpu_idle_ns{0};
inline std::atomic<std::uint64_t> reduced_draws{0}, scene_draws{0};
inline std::atomic<std::uint64_t> sync_recording_ns{0}, host_copies_wait_ns{0}, tick_wait_ns{0},
    copy_threads_wait_ns{0}, host_copy_waits{0}, host_copy_waits_skipped{0};
inline std::atomic<std::uint64_t> present_wait_ns{0};
inline std::atomic<std::uint32_t> frame_number{0};
inline std::atomic<std::uint64_t> preupload_bytes{0};
inline std::atomic<std::uint64_t> device_alloc_bytes{0}, device_free_bytes{0};
inline std::atomic<std::uint64_t> live_image_bytes{0}, live_images{0};
inline std::atomic<std::uint64_t> vk_image_bytes{0};
inline std::atomic<std::uint64_t> residency_alloc_bytes{0}, residency_unused_bytes{0};
inline std::atomic<std::uint64_t> gc_used_bytes{0}, gc_trigger_bytes{0}, gc_freed_images{0};
inline std::atomic<std::uint32_t> coarse_second{0};
inline std::atomic<std::uint64_t> vram_idle_bytes{0}, vram_unmapped_bytes{0}, vram_chunks_freed_bytes{0};
inline std::atomic<std::uint64_t> residency_chunk_count{0}, evacuations{0}, evac_kept_gpu{0}, evac_kept_other{0};
inline std::atomic<std::uint64_t> gc_kept_images{0};
struct WaitTimer {
    std::atomic<std::uint64_t>& total;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    ~WaitTimer() {
        total.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now() - start).count(),
                        std::memory_order_relaxed);
    }
};
inline std::atomic<std::uint64_t> gpu_sys_us{0}, gpu_user_us{0}, gpu_invol_switches{0},
    gpu_vol_switches{0}, gpu_minor_faults{0};
inline std::atomic<std::uint64_t> gpu_signal_faults{0};
inline std::atomic<std::uint64_t> protect_calls{0}, protect_pages{0}, protect_revoke_calls{0},
    protect_revoke_pages{0};
enum ProtectKind : unsigned {
    ProtectUpload,
    ProtectTexture,
    ProtectOther,
    ProtectDeferred,
    ProtectKinds,
};
inline std::array<std::atomic<std::uint64_t>, ProtectKinds> stage_b_protect_calls{},
    stage_b_protect_ns{};
inline std::atomic<std::uint64_t> other_protect_calls{0}, other_protect_ns{0};
inline std::atomic<std::uint64_t> deferred_protect_pages{0}, deferred_protect_calls{0},
    deferred_protect_ns{0}, copy_flushes{0}, deferred_cancelled_pages{0};
enum WaitSite : unsigned {
    WaitWriteData,
    WaitDma,
    WaitFlip,
    WaitEos,
    WaitEop,
    WaitOther,
    WaitSites,
};
inline constexpr const char* WaitSiteNames[WaitSites] = {"WriteData", "DMA", "flip", "EOS", "EOP",
                                                         "other"};
inline std::array<std::atomic<std::uint64_t>, WaitSites> signal_waits{}, signal_wait_ns{},
    signal_waits_skipped{}, copy_waits{}, copy_wait_ns{};
inline std::atomic<std::uint64_t> fence_barriers{0};
inline std::atomic<std::uint64_t> dma_on_cpu{0}, dma_on_gpu{0};
inline std::atomic<std::uint64_t> lookahead_packets{0}, lookahead_draws{0}, lookahead_lines{0},
    lookahead_behind{0}, lookahead_waits{0}, lookahead_lead{0}, lookahead_busy_cycles{0},
    lookahead_recovered{0};
}

// bbport (r23_spike-trace): BB_SPIKE_TRACE=1: where the time of slow frames went
// (lantern_frame_report.cpp, "Spike (r23):" lines every 5 s). Fed only while on (but
// stage_b_busy); read once a flip on bb:VideoOut.
namespace BbSpike {
inline const bool on = [] {
    BbSettings::DebugSwitchesAtStart(); // bbport (r39_master-debug): debug_spike_trace=1 first, as above
    const char* env = std::getenv("BB_SPIKE_TRACE");
    return env && env[0] == '1';
}();
inline std::uint64_t NowNs() {
    return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                             std::chrono::steady_clock::now().time_since_epoch())
                             .count());
}
/// Stage B's packet cycles (DrawPipe::busy_cycles, counted always), published by the rasterizer.
inline std::atomic<const std::atomic<std::uint64_t>*> stage_b_busy{nullptr};
/// ns: stage B's display-pass frame end (EffectsOnFrameEnd to NoteFrameStart: its 600-frame
/// reports and the GPU profile print); stage A's 5 s draw pipe report (PrintPipeStats).
inline std::atomic<std::uint64_t> stage_b_end_ns{0}, stage_a_print_ns{0};
/// Stage A (GpuCommandProcessor) idle waits: ns of those ended, start of the open one (0: busy).
inline std::atomic<std::uint64_t> stage_a_idle_ns{0}, stage_a_idle_since{0};
/// Sparse binds before submissions (BufferCache): calls, those that waited for a submission on
/// the GPU, ns in vkQueueBindSparse.
inline std::atomic<std::uint64_t> binds{0}, bind_waits{0}, bind_ns{0};
/// The game thread at sceGnmSubmitDone: frames, the longest interval between two since the
/// last read (exchanged by the reader), the time of the last one.
inline std::atomic<std::uint64_t> game_frames{0}, game_max_ns{0}, game_last_ns{0};
inline void NoteGameFrame() {
    const std::uint64_t now = NowNs();
    const std::uint64_t before = game_last_ns.exchange(now, std::memory_order_relaxed);
    if (before != 0 && now > before) {
        const std::uint64_t interval = now - before;
        for (std::uint64_t longest = game_max_ns.load(std::memory_order_relaxed);
             interval > longest &&
             !game_max_ns.compare_exchange_weak(longest, interval, std::memory_order_relaxed);) {
        }
    }
    game_frames.fetch_add(1, std::memory_order_relaxed);
}
/// Ray tracing (RtShadow): BLAS full builds recorded (not refits) and their triangles; TLAS
/// full builds of the r17 upkeep path.
inline std::atomic<std::uint64_t> rt_builds{0}, rt_build_triangles{0}, tlas_builds{0};
/// BB_GPU_PROFILE=1 only: per frame the profiler reads (four frames late), its frame number
/// (BbStats::gpu_frames after the display pass closing it), GPU busy ns (gaps between
/// submissions left out) and ns from its first to its last timestamp. A ring written by stage B.
struct Gpu {
    std::atomic<std::uint64_t> frame{0}, busy_ns{0}, span_ns{0};
};
inline std::array<Gpu, 16> gpu{};
inline std::atomic<std::uint64_t> gpu_written{0};
inline void NoteGpu(std::uint64_t frame, std::uint64_t busy_ns, std::uint64_t span_ns) {
    const std::uint64_t at = gpu_written.load(std::memory_order_relaxed);
    Gpu& entry = gpu[at % gpu.size()];
    entry.frame.store(frame, std::memory_order_relaxed);
    entry.busy_ns.store(busy_ns, std::memory_order_relaxed);
    entry.span_ns.store(span_ns, std::memory_order_relaxed);
    gpu_written.store(at + 1, std::memory_order_release);
}
} // namespace BbSpike

// bbport (r27_flush-split): BB_SPIKE_TRACE=1: stage B's time inside each task packet, split by the
// steps of Rasterizer::Flush and what it calls (and Rasterizer::OnSubmit's calls). Each step keeps
// its own time (less the timed steps inside it), so one task's steps add up to the task. Timed
// only on a thread whose root is open: a stage B task packet, or Rasterizer::Flush on stage B
// outside one. Off: one branch per step. Read per flip and every 600 flips by
// lantern_frame_report.cpp ("Spike (r23):" lines, "Flush splits (r27):").
namespace BbSpike {
enum Split : std::uint32_t {
    SplitTask,          ///< the task's own code (outside the steps below)
    SplitFlush,         ///< Rasterizer::Flush's own code (Scheduler::Flush included)
    SplitDrain,         ///< DrainDrawPipe in Rasterizer::Flush
    SplitPublish,       ///< PublishSignals in Rasterizer::Flush
    SplitSubmit,        ///< Scheduler::SubmitExecution/SubmitAsync's own code
    SplitCallback,      ///< the submit callback's own code
    SplitMotionSync,    ///< ObjectMotion::Sync: waits for bb:Motion's posted jobs
    SplitBarriers,      ///< runtime.FlushBarriers
    SplitArenaBinds,    ///< BufferCache::SubmitPendingArenaBinds' own code
    SplitCopyBacks,     ///< BufferCache::QueueCopyBacks
    SplitPromotions,    ///< BufferCache::QueuePromotions
    SplitEndRendering,  ///< Scheduler::EndRendering
    SplitCopyBatch,     ///< BbCopy::FlushBatch
    SplitRecordOrdered, ///< RecordOrdered (the submit closure pushed; inline: run)
    SplitCopyWait,      ///< inline submit only: BbCopy::WaitAsync
    SplitQueueSubmit,   ///< inline submit only: submit_mutex, sparse binds, vkQueueSubmit
    SplitKick,          ///< KickRecording
    SplitAllocate,      ///< AllocateWorkerCommandBuffers
    SplitPendingOps,    ///< PopPendingOperations
    SplitFaultBuffer,   ///< OnSubmit: ProcessFaultBuffer
    SplitDownloads,     ///< OnSubmit: ProcessDownloadImages
    SplitKeyPrompts,    ///< OnSubmit: UpdateKeyPrompts
    SplitCollector,     ///< OnSubmit: RunGarbageCollector
    SplitTickFrame,     ///< OnSubmit: TickFrame
    SplitStagingTrim,   ///< r29: StagingBufferPool::TickFrame's TrimRing and TrimLarge
    Splits,
};
inline constexpr const char* SplitNames[Splits] = {
    "task's own code",
    "Flush's own code",
    "DrainDrawPipe",
    "PublishSignals",
    "SubmitExecution/SubmitAsync own code",
    "submit callback's own code",
    "ObjectMotion::Sync",
    "FlushBarriers",
    "SubmitPendingArenaBinds' own code",
    "QueueCopyBacks",
    "QueuePromotions",
    "EndRendering",
    "BbCopy::FlushBatch",
    "RecordOrdered",
    "BbCopy::WaitAsync (inline submit)",
    "vkQueueSubmit and its lock (inline submit)",
    "KickRecording",
    "AllocateWorkerCommandBuffers",
    "PopPendingOperations",
    "ProcessFaultBuffer",
    "ProcessDownloadImages",
    "UpdateKeyPrompts",
    "RunGarbageCollector",
    "TickFrame",
    "staging trim (TrimRing/TrimLarge)",
};
inline constexpr std::uint64_t SplitLongNs = 2000000; ///< a task this long counts as long
/// Cumulative ns by step: all timed tasks; the long ones; long tasks counted by largest step.
inline std::array<std::atomic<std::uint64_t>, Splits> split_ns{}, split_long_ns{}, split_long_by{};
/// Long tasks, and those of them that ran Rasterizer::Flush.
inline std::atomic<std::uint64_t> split_long{0}, split_long_flush{0};
/// The longest timed task since the reader took it (exchange(0) per flip), and its kind.
inline std::atomic<std::uint64_t> split_max_ns{0};
inline std::atomic<const char*> split_max_kind{nullptr};
/// Long tasks by kind (RunInOrder's name; a slot is never freed).
struct SplitKind {
    std::atomic<const char*> name{nullptr};
    std::atomic<std::uint64_t> count{0};
};
inline constexpr std::size_t SplitKinds = 16;
inline std::array<SplitKind, SplitKinds> split_kinds{};
/// bb:Motion's index list rescans (IndexRangeCache misses: min/max scan and XXH3): count and ns.
inline std::atomic<std::uint64_t> motion_scans{0}, motion_scan_ns{0};
/// bb:Motion's time running jobs (a busy run is added when it catches up), and its sleeps that
/// stage B's ObjectMotion::Post woke: count, ns from the first such Post to bb:Motion running
/// again (summed; the longest since the reader exchanged it), the first Post's time (0: none).
/// Tells an ObjectMotion::Sync wait on a busy bb:Motion from one on a bb:Motion not running.
inline std::atomic<std::uint64_t> motion_busy_ns{0}, motion_wakes{0}, motion_wake_ns{0},
    motion_wake_max_ns{0}, motion_wake_at{0};
/// Stage B (ObjectMotion::Post, bb:Motion asleep): the wake delay starts (the first Post only).
/// bb:Motion clears the stamp before each sleep (release: its store of worker_sleeping), so a
/// Post that saw the flag only from an older sleep cannot leave a stale start for a later one.
inline void NoteMotionWakeCall() {
    std::uint64_t none = 0;
    motion_wake_at.compare_exchange_strong(none, NowNs(), std::memory_order_relaxed);
}
/// bb:Motion, back from a sleep: the delay since the first Post that woke it.
inline void NoteMotionWake() {
    const std::uint64_t at = motion_wake_at.exchange(0, std::memory_order_relaxed);
    if (at == 0) {
        return;
    }
    const std::uint64_t now = NowNs();
    const std::uint64_t ns = now > at ? now - at : 0;
    motion_wakes.fetch_add(1, std::memory_order_relaxed);
    motion_wake_ns.fetch_add(ns, std::memory_order_relaxed);
    for (std::uint64_t longest = motion_wake_max_ns.load(std::memory_order_relaxed);
         ns > longest &&
         !motion_wake_max_ns.compare_exchange_weak(longest, ns, std::memory_order_relaxed);) {
    }
}

/// The open steps of this thread (a stack) and the own ns of the task being timed.
struct SplitState {
    std::uint32_t depth = 0;
    std::uint64_t seen = 0; ///< a bit per step entered in this task
    const char* kind = nullptr;
    std::array<std::uint64_t, Splits> self{};
    std::array<std::uint64_t, 8> inner{}; ///< per open step, ns of its closed timed steps
};
inline thread_local SplitState split_state{};

/// The root closed: the task's steps into the shared counters (stage B; relaxed adds).
inline void EndSplit(const SplitState& s, std::uint64_t total) {
    constexpr auto relaxed = std::memory_order_relaxed;
    const char* const kind = s.kind ? s.kind : "unnamed task";
    std::uint32_t largest = 0;
    for (std::uint32_t i = 0; i < Splits; ++i) {
        if (s.self[i] != 0) {
            split_ns[i].fetch_add(s.self[i], relaxed);
            largest = s.self[i] > s.self[largest] ? i : largest;
        }
    }
    if (total > split_max_ns.load(relaxed)) {
        split_max_kind.store(kind, relaxed);
        split_max_ns.store(total, relaxed);
    }
    if (total < SplitLongNs) {
        return;
    }
    split_long.fetch_add(1, relaxed);
    split_long_flush.fetch_add((s.seen >> SplitFlush) & 1, relaxed);
    split_long_by[largest].fetch_add(1, relaxed);
    for (std::uint32_t i = 0; i < Splits; ++i) {
        if (s.self[i] != 0) {
            split_long_ns[i].fetch_add(s.self[i], relaxed);
        }
    }
    for (auto& slot : split_kinds) {
        const char* const name = slot.name.load(relaxed);
        if (name == kind || !name) {
            slot.name.store(kind, relaxed);
            slot.count.fetch_add(1, relaxed);
            break;
        }
    }
}

/// One timed step (a scope). `root`: opens a task on this thread when none is open (with
/// `kind`); otherwise a step is timed only inside an open task.
class SplitScope {
public:
    explicit SplitScope(Split step_, bool root = false, const char* kind = nullptr) noexcept {
        if (on) {
            Enter(step_, root, kind);
        }
    }
    ~SplitScope() {
        Stop();
    }
    SplitScope(const SplitScope&) = delete;
    SplitScope& operator=(const SplitScope&) = delete;
    /// Ends the step before the scope does (it must be the innermost open one).
    void Stop() noexcept {
        if (start != 0) {
            Leave();
        }
    }

private:
    void Enter(Split step_, bool root, const char* kind) noexcept {
        SplitState& s = split_state;
        if (root && step_ == SplitTask) {
            s.depth = 0; // task packets never nest: a step still open here was left by a jump
        }
        if ((s.depth == 0 && !root) || s.depth >= s.inner.size()) {
            return;
        }
        if (s.depth == 0) {
            s.self = {};
            s.seen = 0;
            s.kind = kind;
        }
        s.seen |= std::uint64_t(1) << step_;
        level = s.depth;
        s.inner[s.depth++] = 0;
        step = step_;
        start = NowNs();
    }
    void Leave() noexcept {
        const std::uint64_t elapsed = NowNs() - start;
        start = 0;
        SplitState& s = split_state;
        if (s.depth != level + 1) {
            return; // the stack was reset under this step
        }
        s.depth = level;
        const std::uint64_t inner = s.inner[level] < elapsed ? s.inner[level] : elapsed;
        s.self[step] += elapsed - inner;
        if (level != 0) {
            s.inner[level - 1] += elapsed;
            return;
        }
        EndSplit(s, elapsed);
    }
    std::uint64_t start = 0; ///< 0: not timed
    std::uint32_t level = 0;
    Split step = SplitTask;
};
} // namespace BbSpike

// bbport (r29_bursts): BB_SPIKE_TRACE=1: what the Spike lines need to tell stage A waiting on
// stage B from decoding, more packets from slower ones, and a late stage A from late work.
namespace BbSpike {
/// ns stage A spent in DrawPipe waits for stage B (Drain, WaitForPacket, WaitForSpace).
inline std::atomic<std::uint64_t> stage_a_wait_ns{0};
/// Stage B's packets run (DrawPipe's consumed_packets, counted always), published by the
/// rasterizer next to stage_b_busy.
inline std::atomic<const std::atomic<std::uint64_t>*> stage_b_packets{nullptr};
/// The first guest graphics submission queued while stage A idled (0: none open); the delays from
/// it to stage A leaving its idle wait: count, the longest since the reader exchanged it.
inline std::atomic<std::uint64_t> stage_a_queued_at{0}, stage_a_pickups{0},
    stage_a_pickup_max_ns{0};
/// Staging buffers (ring blocks and large buffers) freed by StagingBufferPool's trims.
inline std::atomic<std::uint64_t> staging_freed{0};
/// bbport (r35_pending-ops): Scheduler::PopPendingOperations (fed only while the trace is on).
/// Per kind (DeferOperation's kind; a slot is never freed, past the last the last one):
/// operations run and their ns, the callback and its destruction.
struct PendingKind {
    std::atomic<const char*> name{nullptr};
    std::atomic<std::uint64_t> count{0}, ns{0};
};
inline constexpr std::size_t PendingKinds = 16;
inline std::array<PendingKind, PendingKinds> pending_kinds{};
/// The longest call since the reader took it (pending_call_ns exchanged per flip, stored last):
/// operations run, frees carried to a later frame, the costliest kind by summed ns (its count
/// and ns), the longest operation (its kind and ns).
inline std::atomic<std::uint64_t> pending_call_ns{0}, pending_call_kind_ns{0},
    pending_call_op_ns{0};
inline std::atomic<std::uint32_t> pending_call_ops{0}, pending_call_carried{0},
    pending_call_kind_ops{0};
inline std::atomic<const char*> pending_call_kind{nullptr}, pending_call_op_kind{nullptr};
/// Frees carried (all), waiting after the last call, the most waiting after a call and the
/// longest wait in frames of one that ran (both exchanged by the 600-flip reader).
inline std::atomic<std::uint64_t> pending_carried{0}, pending_backlog{0}, pending_backlog_max{0},
    pending_wait_max{0};
inline std::uint32_t PendingKindSlot(const char* name) {
    for (std::uint32_t i = 0; i < PendingKinds; ++i) {
        const char* at = pending_kinds[i].name.load(std::memory_order_relaxed);
        if (at == nullptr &&
            pending_kinds[i].name.compare_exchange_strong(at, name, std::memory_order_relaxed)) {
            return i;
        }
        if (at == name) {
            return i;
        }
    }
    return std::uint32_t(PendingKinds - 1);
}
} // namespace BbSpike

// bbport (r35_pending-ops): how much of the frees deferred with DeferOperation(..., carry = true)
// a Scheduler runs per window (a frame, BbStats::gpu_frames; or WindowTicks submissions without a
// new frame), the rest carried to the next windows. Used under the scheduler's pending_ops_mutex.
namespace BbPendingOps {
/// Experiment bit: set = every operation the GPU is past runs in the call that finds it (old).
inline constexpr std::uint64_t OldBit = 576460752303423488ull;
/// ns of carryable frees a window runs; the one that crosses it runs whole.
inline constexpr std::uint64_t BudgetNs = 2000000;
/// A free carried this many frames runs whatever the budget (memory is not held longer).
inline constexpr std::uint64_t MaxCarryFrames = 60;
/// Submissions after which a window ends within one frame (no display pass: loading, menus).
inline constexpr std::uint64_t WindowTicks = 64;
struct Budget {
    std::uint64_t frame = ~std::uint64_t(0), tick = 0, spent_ns = 0;
    /// A new window on a new frame, or WindowTicks submissions after this window began.
    void Begin(std::uint64_t now_frame, std::uint64_t now_tick) {
        if (now_frame != frame || now_tick >= tick + WindowTicks) {
            frame = now_frame;
            tick = now_tick;
            spent_ns = 0;
        }
    }
    bool Spent() const {
        return spent_ns >= BudgetNs;
    }
    /// A carried free (carried on `carried_frame`) may run in this window.
    bool MayRunCarried(std::uint64_t carried_frame) const {
        return !Spent() || frame - carried_frame >= MaxCarryFrames;
    }
    void Spend(std::uint64_t ns) {
        spent_ns += ns;
    }
};
} // namespace BbPendingOps

namespace BbSpike {
/// Liverpool::SubmitGfx, under submit_mutex.
inline void NoteStageAQueued() {
    if (stage_a_idle_since.load(std::memory_order_relaxed) != 0) {
        std::uint64_t none = 0;
        stage_a_queued_at.compare_exchange_strong(none, NowNs(), std::memory_order_relaxed);
    }
}
/// Stage A leaving its idle wait, under submit_mutex (before stage_a_idle_since is cleared).
inline void NoteStageAPickup() {
    const std::uint64_t at = stage_a_queued_at.exchange(0, std::memory_order_relaxed);
    if (at == 0) {
        return;
    }
    const std::uint64_t now = NowNs();
    const std::uint64_t ns = now > at ? now - at : 0;
    stage_a_pickups.fetch_add(1, std::memory_order_relaxed);
    for (std::uint64_t longest = stage_a_pickup_max_ns.load(std::memory_order_relaxed);
         ns > longest && !stage_a_pickup_max_ns.compare_exchange_weak(longest, ns,
                                                                     std::memory_order_relaxed);) {
    }
}
/// A scope's ns added to a counter (only while the trace is on).
class NsScope {
public:
    explicit NsScope(std::atomic<std::uint64_t>& to_) noexcept : to{to_}, start{on ? NowNs() : 0} {}
    ~NsScope() {
        if (start != 0) {
            to.fetch_add(NowNs() - start, std::memory_order_relaxed);
        }
    }
    NsScope(const NsScope&) = delete;
    NsScope& operator=(const NsScope&) = delete;

private:
    std::atomic<std::uint64_t>& to;
    std::uint64_t start;
};
} // namespace BbSpike

// bbport (r29_bursts): text formatted on one thread and written on bb:Stats. While a Capture
// lives on a thread, Printf appends to it; when the Capture ends its text goes to the writer
// (lantern_frame_report.cpp: R23::Post, one fwrite). Without an open Capture, before the writer
// is set, or with experiment 9007199254740992 set when the Capture opened: Printf is printf.
// For stage B's 600-frame reports, whose printing (stdout unbuffered into a pipe) held stage B.
namespace BbReport {
inline constexpr std::uint64_t InlineBit = 9007199254740992ull; ///< set: printed in place (old)
inline std::atomic<void (*)(std::string&&)> writer{nullptr};
inline thread_local std::string* capture_text = nullptr;

class Capture {
public:
    Capture() noexcept {
        if (capture_text == nullptr && writer.load(std::memory_order_acquire) != nullptr &&
            !BbToggle::Experiment(InlineBit)) {
            capture_text = &text;
        }
    }
    ~Capture() {
        if (capture_text != &text) {
            return;
        }
        capture_text = nullptr;
        if (!text.empty()) {
            writer.load(std::memory_order_acquire)(std::move(text));
        }
    }
    Capture(const Capture&) = delete;
    Capture& operator=(const Capture&) = delete;

private:
    std::string text;
};

__attribute__((format(printf, 1, 2))) inline void Printf(const char* format, ...) {
    va_list args;
    va_start(args, format);
    if (std::string* out = capture_text) {
        va_list again;
        va_copy(again, args);
        const int size = std::vsnprintf(nullptr, 0, format, again);
        va_end(again);
        if (size > 0) {
            const std::size_t at = out->size();
            out->resize(at + std::size_t(size) + 1);
            std::vsnprintf(out->data() + at, std::size_t(size) + 1, format, args);
            out->resize(at + std::size_t(size));
        }
    } else {
        std::vprintf(format, args);
    }
    va_end(args);
}
} // namespace BbReport

// bbport r8 (diagnostic; BB_SUBMIT_DIAG=1 or BB_GPU_PROFILE=1): why each submission of the game's
// Vulkan scheduler goes out, whether the GPU had already finished the one before when it reached
// the queue, and how long threads block on the GPU; printed every 600 frames ("Submit diag:").
namespace BbSubmitDiag {
enum Reason : unsigned {
    ReasonOther,
    ReasonBatched,
    ReasonGpuIdle,
    ReasonNearDry,
    ReasonStageAIdle,
    ReasonFrameEnd,
    ReasonSubmitDone,
    ReasonFenceSpin,
    ReasonFlip,
    ReasonFinish,
    ReasonTickWait,
    Reasons,
};
inline constexpr const char* ReasonNames[Reasons] = {
    "other (a direct Flush)",
    "batched (guest submission end, BB_HONEST_FLUSH_US over)",
    "GPU idle (guest submission end, GPU done with all)",
    "near dry (r8: guest submission end, BB_NEAR_DRY_DEPTH)",
    "GPU command thread idle 0.2 ms (SignalFlush)",
    "frame end (FramesRetired)",
    "sceGnmSubmitDone (OnSubmit)",
    "fence spin (WAIT_REG_MEM)",
    "flip (presenter frame)",
    "Finish (the CPU waits for it)",
    "Wait on the open tick",
};
inline bool On() {
    static const bool on = [] {
        const char* diag = std::getenv("BB_SUBMIT_DIAG");
        const char* profile = std::getenv("BB_GPU_PROFILE");
        return (diag && diag[0] == '1') || (profile && profile[0] == '1');
    }();
    return on;
}
/// The reason given to the submissions made on this thread while a Scope lives.
inline thread_local unsigned reason = ReasonOther;
struct Scope {
    unsigned previous;
    explicit Scope(unsigned r) noexcept : previous{reason} {
        reason = r;
    }
    ~Scope() {
        reason = previous;
    }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
/// Scheduler::Finish's caller, for the wait it makes (Scheduler::Wait).
inline thread_local void* wait_caller = nullptr;
/// Per reason: submissions, those that reached the queue after the GPU had finished the one
/// before, those with semaphore waits (sparse binds), ns since the previous submission (stage B),
/// ns from the decision to vkQueueSubmit (recording threads), the longest of those.
inline std::array<std::atomic<std::uint64_t>, Reasons> submits{}, dry_submits{}, waited_submits{},
    since_ns{}, queue_ns{}, queue_max_ns{};
/// Ends of guest submissions (SubmitForSignalsNow): all, without fences pending, held for the
/// batch, held although the GPU had finished everything submitted, near-dry flushes left out
/// because the draw recording thread had no slack.
inline std::atomic<std::uint64_t> ends{0}, ends_no_fences{0}, ends_held{0}, ends_held_dry{0},
    near_dry_busy{0};
/// The game thread: waits for the previous frame (sceGnm: the GPU to finish it), their ns, the
/// sum of the frame's guest submission count at each wait; guest submissions and frames.
inline std::atomic<std::uint64_t> guest_waits{0}, guest_wait_ns{0}, guest_wait_index{0},
    guest_submits{0}, guest_frames{0};
} // namespace BbSubmitDiag
