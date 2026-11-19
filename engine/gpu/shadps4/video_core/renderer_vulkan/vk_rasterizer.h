// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include "video_core/renderer_vulkan/vk_foliage_mask.h"

#include <chrono>
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include "common/recursive_lock.h"
#include "engine/batch.h"
#include "bbport_wind.h" // bbport (r82_wind-stage1)
#include "bbport_wind_sway.h" // bbport (r89_wind-foliage-sway)
#include "bbport_wind_game.h" // bbport (r122_game-wind-drive)
#include "bbport_wind_game_particles.h" // bbport (r122b_game-particles-follow-wind)
#include "video_core/renderer_vulkan/vk_wind_shelter.h" // bbport (r117_wind-shelter)
#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)
#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)
#include "bbport_wind_census.h" // bbport (r89i_twigs-colour-pass)
#include "bbport_wind_trees.h" // bbport (r89j_twigs-pick-trees)
#include "bbport_wind_hang_still.h" // bbport (r112d_hang-still-test)
#include "bbport_wind_hang_actors.h" // bbport (r112h_hang-not-the-hunter)
#include "bbport_wind_hang_gpu.h" // bbport (r112p_hang-gpu-palette-lanterns)
#include "bbport_wind_hang_find.h" // bbport (r112i_hang-find-lanterns)
#include "bbport_wind_hang_route.h" // bbport (r112q_hang-bracket-route)
#include "bbport_wind_hang_probe.h" // bbport (r112b_hang-probe, TOOL)
#include "common/shared_first_mutex.h"
#include "video_core/buffer_cache/buffer_cache.h"
#include "video_core/page_manager.h"
#include "video_core/renderer_vulkan/vk_ambient_particles.h" // bbport (r98_ambient-particles)
#include "video_core/renderer_vulkan/vk_bind_helper.h"
#include "video_core/renderer_vulkan/cloud_probe.h" // bbport (r104_cloud-probe): TOOL
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_contact_shadow.h"
#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)
#include "video_core/renderer_vulkan/vk_cloud_layer.h" // bbport (r119_volumetric-clouds)
#include "video_core/renderer_vulkan/vk_depth_of_field.h"
#include "video_core/renderer_vulkan/vk_drawn_look.h"
#include "video_core/renderer_vulkan/vk_footprints.h" // bbport (r111_footprints)
#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/vk_heat_haze.h" // bbport (r97_heat-haze)
#include "video_core/renderer_vulkan/vk_halation.h" // bbport (r95_halation)
#include "video_core/renderer_vulkan/window_pane_cold.h"
#include "video_core/renderer_vulkan/vk_test_world_at.h" // bbport (r120_test-camera-lookat, TOOL): BB_TEST_WORLD_AT
#include "video_core/renderer_vulkan/vk_blood_sheen.h" // bbport (r100_blood-sheen)
#include "video_core/renderer_vulkan/vk_glass_view.h" // bbport (r129a_glass-registry)
#include "video_core/renderer_vulkan/vk_glass_clear.h" // bbport (r131c_cabinet-glass-clear)
#include "video_core/renderer_vulkan/vk_sun_term_view.h" // bbport (t129c_sun-term-view)
#include "video_core/renderer_vulkan/vk_glass_glint.h" // bbport (r86b_glass-visible)
#include "video_core/renderer_vulkan/vk_foliage_glow.h" // bbport (r131a_foliage-translucency)
#include "video_core/renderer_vulkan/vk_bottle_caustic.h"
#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)
#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle, TOOL)
#include "video_core/renderer_vulkan/vk_caustics.h" // bbport (r107_caustics)
#include "video_core/renderer_vulkan/vk_blood_pool_probe.h" // bbport (r100c_blood-pool-probe, TOOL)
#include "video_core/renderer_vulkan/vk_froyok_bloom.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_sky_seam.h"
#include "video_core/renderer_vulkan/vk_sky_zenith.h"
#include "video_core/renderer_vulkan/vk_ssgi.h"
#include "video_core/renderer_vulkan/vk_ao_spatial.h"
#include "video_core/renderer_vulkan/vk_ssr_temporal.h"
#include "video_core/renderer_vulkan/vk_volumetric_light.h"
#include "video_core/renderer_vulkan/vk_constant_ring.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_draw_pipe.h"
#include "video_core/renderer_vulkan/vk_draw_prep.h"
#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"
#include "video_core/renderer_vulkan/ui_composition.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/ivy_material_probe.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace AmdGpu {
struct Liverpool;
}

namespace Core {
class MemoryManager;
}

namespace WorkflowProbe {
struct DrawCommand;
struct Renderer;
struct ScissorQuery;
}

namespace Vulkan {
#ifdef BB_TEST_SHARED_POST_GRAPH
namespace SewerBridge { struct PostDraw; }
namespace BottleDisplay182 { struct Draw; }
#endif
namespace WindowPathProbe {
enum class PaneOwnerGap : u8;
struct ReceiverCapture;
}

class GraphicsPipeline;
class Occlusion;
class Runtime;

class Rasterizer {
public:
    explicit Rasterizer(const Instance& instance, Scheduler& scheduler, Runtime& runtime,
                        AmdGpu::Liverpool* liverpool);
    ~Rasterizer();

    [[nodiscard]] bool HasSewerReceiverWitness() const noexcept {
        return bool(sewer_receiver);
    }
    void NoteSewerDepthBlockCopy(VideoCore::ImageId src_id, const VideoCore::Image& src,
                                 VideoCore::ImageId dst_id, const VideoCore::Image& dst,
                                 u64 bytes, u64 previous_dst_write, bool native);

    std::string SewerJoinedCopyBefore(VideoCore::ImageId src_id, const VideoCore::Image& src,
                                      VideoCore::ImageId dst_id, const VideoCore::Image& dst);
    void SewerJoinedCopyAfter(const std::string& before, VideoCore::ImageId src_id,
                              const VideoCore::Image& src, VideoCore::ImageId dst_id,
                              const VideoCore::Image& dst, u64 bytes, bool product_wanted);
    bool SewerReducedBeforeCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                                VideoCore::ImageId destination, const VideoCore::Image& dst, u64 bytes);
    void SewerReducedFallbackCopy(VideoCore::ImageId source);
    void SewerReducedAfterCopy(VideoCore::ImageId source, VideoCore::ImageId destination,
                               const VideoCore::Image& dst, vk::ImageView sampled, vk::ImageView written);
    [[nodiscard]] bool WantsNativeBedCopy(VideoCore::ImageId src_id) const;
    void NoteNativeBedCopy(VideoCore::ImageId src_id, const VideoCore::Image& src,
                           VideoCore::ImageId dst_id, const VideoCore::Image& dst, u64 bytes,
                           u64 previous_dst_write);

    [[nodiscard]] Runtime& GetRuntime() noexcept {
        return runtime;
    }

    [[nodiscard]] VideoCore::BufferCache& GetBufferCache() noexcept {
        return buffer_cache;
    }

    [[nodiscard]] TemporalUpscaler& GetUpscaler() noexcept {
        return *upscaler;
    }

    /// bbport: native HDR output's gain maps (vk_hdr_native.h), taken by the presenter.
    [[nodiscard]] HdrNative& GetHdrNative() noexcept {
        return *hdr_native;
    }

    [[nodiscard]] VideoCore::TextureCache& GetTextureCache() noexcept {
        return texture_cache;
    }

    void Draw(bool is_indexed, u32 index_offset = 0, const PreparedDraw* prepared = nullptr,
              u64 gx_record = 0);

    /// bbport: draw preparation workers (vk_draw_prep.h), fed and consumed by Liverpool.
    DrawPreparation& GetDrawPreparation() {
        return *draw_prep;
    }
    void DrawIndirect(bool is_indexed, VAddr arg_address, u32 offset, u32 size, u32 max_count,
                      VAddr count_address, u16 vertex_sgpr_offset, u16 instance_sgpr_offset);

    void DispatchDirect();
    void DispatchIndirect(VAddr address, u32 offset, u32 size);

    /// bbport (GPU command thread): a ZPASS_DONE dump of `pipes` DBs to `va`, handed to the
    /// recording side in order; false when the real counts are off (the caller writes the fake).
    bool OcclusionDump(VAddr va, u32 pipes);
    /// bbport (GPU command thread): SET_PREDICATION (its two body words); false when off.
    bool OcclusionPredication(const u32* body);
    /// bbport (GPU command thread): a guest submission starts: a predication region left open
    /// by the previous one is closed.
    void OcclusionSubmissionStart();
    /// bbport (GPU command thread, drained): dumps wait for the submission being recorded.
    bool OcclusionUnsubmitted() const;

    void ScopeMarker(fmt::string_view fmt, fmt::format_args args, auto&& func) {
        if (host_markers_enabled) {
            ScopeMarkerBegin(fmt::vformat(fmt, args));
            func();
            ScopeMarkerEnd();
        } else {
            func();
        }
    }

    void ScopeMarkerBegin(const std::string_view& str, bool from_guest = false);
    void ScopeMarkerEnd(bool from_guest = false);
    void ScopedMarkerInsert(const std::string_view& str, bool from_guest = false);
    void ScopedMarkerInsertColor(const std::string_view& str, const u32 color,
                                 bool from_guest = false);

    /// bbport: `waited` false: the caller (RunDmaData) skipped the waits a CPU store needs, as
    /// DmaWritesOnCpu said the GPU writes it; should the store be made on the CPU after all,
    /// they are made here first.
    void FillBuffer(VAddr address, u32 num_bytes, u32 value, bool is_gds, bool waited = true);
    void CopyBuffer(VAddr dst, VAddr src, u32 num_bytes, bool dst_gds, bool src_gds,
                    bool waited = true);
    /// bbport: whether FillBuffer/CopyBuffer into guest memory at `dst` may write it on the CPU
    /// now (otherwise the GPU writes it, in stream order).
    [[nodiscard]] bool DmaMayWriteOnCpu(VAddr dst, u32 num_bytes);
    /// bbport (BB_DMA_WAITS, default: only when needed; =all: every DMA into memory waits as
    /// before): whether a DMA into guest memory at `dst` will store with the CPU: the same tests
    /// FillBuffer (`fill`) and CopyBuffer make. Recorded for the GPU it writes no guest memory now
    /// and lands after the submission, which goes out after the copies and fences before it: it
    /// needs neither WaitHostCopiesFor nor WaitDeferredSignals. Stage B owns what it tests.
    [[nodiscard]] bool DmaWritesOnCpu(VAddr dst, u32 num_bytes, bool fill, VAddr src,
                                      bool src_gds);
    /// bbport: what a DMA stored by the CPU into [dst, dst + num_bytes) waits for first: host
    /// copies still reading it, and the deferred fences it must follow (reading [src, src +
    /// src_size) for a copy).
    void WaitBeforeDmaStore(VAddr dst, u32 num_bytes, VAddr src, u32 src_size);
    u32 ReadDataFromGds(u32 gsd_offset);
    bool InvalidateMemory(VAddr addr, u64 size, bool assume_locks = false);
    /// bbport: data written into GPU memory by a path we hear of (file reads, the game's resource
    /// loaders, DMA on the CPU): invalidated, and an asset for the buffer cache.
    void NoteAssetWrite(VAddr addr, u64 size);
    /// bbport: the CPU has written [addr, addr + size): invalidated, its bytes kept over GPU data that
    /// is read back first.
    void InvalidateAfterWrite(VAddr addr, u64 size);
    /// bbport (any thread): the command processor wrote these bytes outside the command stream
    /// (labels, timestamps, occlusion results): VRAM copies of them get them too.
    void NoteLateCommandWrite(VAddr addr, const void* data, u64 size) {
        buffer_cache.NoteLateCommandWrite(addr, data, size);
    }
    /// bbport: the command processor wrote `size` bytes of `data` at addr with the CPU in decode order
    /// (WriteData, a constant RAM dump; the decoder reads them there). Where the GPU's own data there
    /// is in VRAM the bytes go into it in stream order, else the caches are invalidated (no write
    /// tracking). `recording_thread`: the draw recording thread, which owns the caches (no drain).
    void NoteCommandWrite(VAddr addr, const void* data, u64 size, bool recording_thread);
    /// bbport (stage A, BB_CONSTRAM_PIPE, default on): before the command processor writes guest
    /// memory with the CPU (a constant RAM dump), waits until the recording thread has run the
    /// queued packets that read those bytes (their buffer bindings, DMA), not all of them.
    void WaitForPendingReads(VAddr address, u64 size);
    /// NoteCommandWrite for a write made on stage A: handed to the recording thread in order (a copy
    /// of the bytes) instead of draining it first.
    void NoteCommandWriteInOrder(VAddr addr, const void* data, u64 size);
    /// bbport: a guest thread wrote [addr, addr + size) with a libc import (memcpy, memset, memmove)
    /// over pages the caches watch (no write tracking): what a write fault did.
    void OnCpuWrite(VAddr addr, u64 size);
    /// GPU thread, before a write the guest can observe (see Scheduler::WaitHostCopies).
    /// `site`: the caller (BbStats::WaitSite, frame statistics).
    void WaitHostCopies(u32 site = BbStats::WaitOther) {
        DrainDrawPipe();
        scheduler.WaitHostCopies(site);
    }
    /// Before a write into [address, address + size): waits only when a host copy may still read
    /// it (Scheduler::WaitHostCopiesFor). BB_HOST_COPY_WAITS=all: always (the old behaviour).
    void WaitHostCopiesFor(VAddr address, u64 size, u32 site = BbStats::WaitOther) {
        DrainDrawPipe();
        static const bool all = [] {
            const char* env = std::getenv("BB_HOST_COPY_WAITS");
            return env && std::string_view{env} == "all";
        }();
        if (all) {
            scheduler.WaitHostCopies(site);
        } else {
            scheduler.WaitHostCopiesFor(address, size, site);
        }
    }
    /// Notes the guest memory a host copy issued now reads (see Scheduler::NoteHostCopySource).
    void NoteHostCopySource(VAddr address, u64 size) {
        scheduler.NoteHostCopySource(address, size);
    }

    /// bbport: GPU command thread: waits until the draw recording thread has recorded every
    /// draw handed to it (vk_draw_pipe.h); no-op on other threads.
    /// `line`/`function`: the caller, for the statistics of where stage A waits.
    void DrainDrawPipe(u32 reason = DrawPipe::ReasonRasterizer, u32 line = __builtin_LINE(),
                       const char* function = __builtin_FUNCTION());
    /// Runs `task(rasterizer, copy of data)` in order with the draws: on the draw recording
    /// thread while the draw pipeline is in use (PipelinedTasks), else here after a drain.
    using OrderedTask = void (*)(Rasterizer& rasterizer, const u8* data);
    /// Returns true when the task was handed to the recording thread (not run yet).
    /// `reads_guest_memory`: the task may read guest memory (a CPU write on stage A over memory
    /// waits for it, WaitForPendingReads); false for fences, flips and signals.
    /// `name`: the task in the "stage B tasks" statistics (BB_SECTIONS).
    bool RunInOrder(OrderedTask task, const void* data, u32 size,
                    u64 toggle = BbToggle::PipelinedTasks, bool reads_guest_memory = true,
                    const char* name = nullptr);
    /// Stage A: the draw pipe position after the last handed-over packet, and whether the
    /// recording thread has run everything before a position.
    [[nodiscard]] u64 DrawPipeHead() const {
        return draw_pipe ? draw_pipe->Head() : 0;
    }
    [[nodiscard]] bool DrawPipeReached(u64 position) const {
        return !draw_pipe || draw_pipe->Reached(position);
    }
    /// Stage A: no draws waiting for the recording thread.
    [[nodiscard]] bool DrawPipeIdle() const {
        return !draw_pipe || draw_pipe->Idle();
    }
    /// Stage A, end of a submission: its prepared draws stay alive until the recording thread
    /// has recorded them (instead of a drain).
    void RetireSubmission();
    /// Stage A: guest memory the recording thread will write for work handed to it (storage
    /// buffers, DMA, WriteData, fences); constants overlapping it are bound there, not copied here.
    void NotePendingGpuWrite(VAddr address, u64 size);
    /// Stage A: guest memory the recording thread will read for the next packet (buffer bindings).
    void NotePendingRead(VAddr address, u64 size);
    /// Before a guest-visible write: fences deferred earlier are written first.
    void WaitDeferredSignals(u32 site = BbStats::WaitOther) {
        scheduler.WaitDeferredSignals(site);
    }
    /// bbport: before a CPU write of the command processor (WriteData, DMA): only the deferred
    /// fences it must follow (Scheduler::WaitDeferredSignalsFor, BB_FENCE_ORDER).
    void WaitDeferredSignalsFor(u32 site, VAddr address, u64 size, VAddr src = 0,
                                u64 src_size = 0) {
        scheduler.WaitDeferredSignalsFor(site, address, size, src, src_size);
    }
    /// bbport (stage A): a WaitRegMem was met by a fence still deferred: the command processor
    /// would have waited for it here (Scheduler::NoteSignalBarrier, in order on stage B).
    void NoteFenceBarrier();
    /// Runs `signal` after the guest memory copies issued so far, without waiting here.
    /// `kick` false: another one is queued right after (Scheduler::SignalAfterHostCopies).
    /// `label`, `label_size`: the guest memory it writes (none: unknown).
    template <typename Func>
    void SignalAfterHostCopies(Func&& signal, bool kick = true, VAddr label = 0,
                               u32 label_size = 0) {
        scheduler.SignalAfterHostCopies(std::forward<Func>(signal), kick, label, label_size);
    }
    /// Stage B, running a packet: whether the next one is already committed and is ordered
    /// task `task` (it runs right after this one).
    [[nodiscard]] bool NextPacketIsTask(OrderedTask task) const;
    /// Stage B: fences handed to the recording threads together with the next one (statistics).
    std::atomic<u64> merged_fence_kicks{0};
    /// bbport BB_HONEST_LABELS=1: runs `signal` once the GPU has finished every command recorded
    /// before this call (the submission of the current tick), in call order, on a thread that
    /// waits on the work semaphore: fences the guest sees when the work is done, not when it is
    /// recorded. `label` and `value`: the fence it writes (PendingSignalValue).
    void SignalAfterGpu(std::function<void()> signal, VAddr label = 0, u64 value = 0);
    /// Whether signals wait for work not submitted yet (the GPU command thread submits it when
    /// it runs out of work, or the guest could wait for them forever).
    bool HasUnsubmittedSignals();
    /// bbport BB_GUEST_IN_PLACE (draw recording thread): `data` written into the game's memory by the
    /// GPU in stream order, like the command processor's writes; false when the range is not
    /// bound in place (the caller writes it with the CPU).
    bool WriteGuestMemory(VAddr address, const void* data, u32 size);
    /// bbport BB_GUEST_IN_PLACE (in stream order: the recording thread): a WRITE_DATA performed by
    /// the GPU, as the command processor does, instead of a CPU store now (ahead of the GPU work
    /// recorded before it). Values of up to 8 bytes are registered for WAIT_REG_MEM until the GPU
    /// has written them. False: not in place (or BB_GPU_COMMAND_WRITES=0), the caller stores it.
    bool WriteDataOnGpu(VAddr address, const void* data, u32 size);
    /// End of a guest submission: submits the work recorded so far when signals wait for it and
    /// the last submission is BB_HONEST_FLUSH_US (1000) old: the GPU starts on it as the hardware
    /// would, instead of at the end of the frame, and the guest's mid-frame waits end sooner.
    void SubmitForSignals();
    /// bbport BB_PIPE_SIGNALS (default on with honest labels; 0: off): on the GPU command thread with
    /// the draw pipe, fences, the GPU idle and frame signals and the submissions for them are
    /// handed to the draw recording thread as ordered tasks instead of that thread being drained
    /// first (the GPU command thread waited for it ~15 times a frame and the GPU ran dry meanwhile).
    bool PipeSignals() const;
    /// Stage A: the fences the recording thread ran up to `position` are in the signal queue (or
    /// written): a fence it ran but holds still (PublishSignals) is not visible there yet.
    bool SignalsPublished(u64 position) const;
    /// Stage A (BB_PIPE_SIGNALS): the recording thread hands over its signals and submits the work
    /// they wait for, in order, when it gets there (one request in flight at a time).
    void RequestSignalFlush();
    u64 CurrentTick() const {
        return scheduler.CurrentTick();
    }
    /// The newest queued value of the fence at `address` (a WaitRegMem in the same stream is met
    /// by it in stream order).
    bool PendingSignalValue(VAddr address, u64& value);
    static bool HonestLabels();
    /// The GPU command thread or the draw recording thread (fault handling runs inline there).
    bool IsGpuSideThread() const;
    bool IsGpuSideThreadId(u32 tid) const;
    /// A guest write hit a protected page.
    /// `guest_rip`: the guest instruction that wrote (0: unknown), see BufferCache::NoteCpuWrite.
    bool OnWriteFault(VAddr addr, bool assume_locks, u64 guest_rip = 0);
    /// bbport: write faults on pages no tracked image watches skip the texture cache
    /// (BB_FAULT_SKIP_TEXTURES=0: they take its lock as before).
    static bool FaultSkipsTextureCache();
    bool ReadMemory(VAddr addr, u64 size, bool assume_locks = false);
    void ProcessDownloadImages();
    bool IsMapped(VAddr addr, u64 size);
    void MapMemory(VAddr addr, u64 size);
    void RegisterMemory(VAddr addr, u64 size);
    void UnmapMemory(VAddr addr, u64 size);

    u64 Flush();
    void Finish();
    void OnSubmit();

    PipelineCache& GetPipelineCache() {
        return pipeline_cache;
    }

    template <typename Func>
    void ForEachMappedRangeInRange(VAddr addr, u64 size, Func&& func) {
        const auto range = decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);
        Common::RecursiveSharedLock lock{mapped_ranges_mutex};
        for (const auto& mapped_range : (mapped_ranges & range)) {
            func(mapped_range);
        }
    }

    std::thread::id GetGpuCommandProcessorThread();
#ifdef __linux__
    u32 GetGpuCommandProcessorThreadId();
#endif

private:
    void PrepareRenderState(const GraphicsPipeline* pipeline);
    void NotifyUiDraw(const GraphicsPipeline* pipeline);
    /// bbport (r77_parallel-test-runs): clean shot leaves this draw of the game's UI out.
    bool CleanShotEarly(const GraphicsPipeline* pipeline);
    RenderState BeginRendering(const GraphicsPipeline* pipeline);
    RenderState BeginRenderingFull(const GraphicsPipeline* pipeline);
    /// bbport: a pass drawn into the upscaler's output-size images (UI, display pass): what its
    /// draws' transform is made from. The scale, offset and full scissor follow each draw's own
    /// viewport (UpdateUiTransform), also for draws the render state memo continues the pass with.
    struct UiPass {
        bool active = false;
        bool native_ui = false;
        std::array<u32, 2> guest{1, 1};  ///< the guest target's size
        std::array<u32, 2> output{1, 1}; ///< the redirected image's size
    };
    void UpdateUiTransform(const GraphicsPipeline* pipeline);
    /// bbport: a draw continuing the open render pass with the same inputs gets the same render
    /// state (RenderStateMemo); nothing can have broken the pass in between (barriers, copies and
    /// dispatches end it).
    struct BeginSignature {
        std::array<VideoCore::ImageId, AmdGpu::NUM_COLOR_BUFFERS + 1> ids{};
        std::array<VideoCore::ImageViewInfo, AmdGpu::NUM_COLOR_BUFFERS + 1> views{};
        u32 mrt_mask = 0;
        u32 num_samples = 0;
        std::array<u8, AmdGpu::NUM_COLOR_BUFFERS> color_samples{};
        bool motion = false;
        bool scene_started = false;
        bool raster_scaling = false;
        u64 upscaler_state = 0;
        u64 generation = 0;
        u32 depth_control = 0;
        bool depth_valid = false;
        bool stencil_valid = false;
        bool operator==(const BeginSignature&) const = default;
    };
    BeginSignature MakeBeginSignature(const GraphicsPipeline* pipeline) const;
    struct BeginMemo {
        bool valid = false;
        BeginSignature signature;
        RenderState state;
        u32 scene_size = 0;
        std::array<float, 2> target_scale{};
        std::array<float,2> target_offset{};
        std::array<u32, 2> ui_full_scissor{};
        /// The targets' images as memoized (signature.ids): after other images were
        /// (un)registered the memo still holds while each is the same registered image with
        /// the same backing (RevalidateBeginMemo).
        std::array<u64, AmdGpu::NUM_COLOR_BUFFERS + 1> uids{};
        std::array<const void*, AmdGpu::NUM_COLOR_BUFFERS + 1> backings{};
        u64 scene_generation = 0; ///< SceneTargets::Generation (proxy attachments)
        UiPass ui_pass{}; ///< active: the transform is made again for each draw
    } begin_memo;
    u64 begin_memo_hits = 0, begin_memo_misses = 0;
    u64 begin_memo_revalidated = 0; ///< hits after a registry generation change
    /// Takes begin_memo into `signature`'s registry generation when nothing else differs and
    /// its targets are unchanged.
    bool RevalidateBeginMemo(const BeginSignature& signature);
    void RememberBeginTargets();
    /// bbport: BB_MEMO_REVALIDATE=0 drops memoized texture/target lookups on every image
    /// (un)registration as before, instead of revalidating them (IsExactMatch).
    static bool MemoRevalidation();
    void Resolve();
    void DepthStencilCopy(bool is_depth, bool is_stencil);
    void EliminateFastClear();

    void UpdateDynamicState(const GraphicsPipeline* pipeline, bool is_indexed) const;
    void UpdateViewportScissorState() const;
    vk::Rect2D DrawScissor(u32 viewport) const;
    void EffectsOnFrameEnd();
    void WindOnFrameEnd(); ///< bbport (r82_wind-stage1): first in EffectsOnFrameEnd
    /// bbport (r122b_game-particles-follow-wind): called only while BbWindParticles::On(), before a draw binds its
    /// resources (vk_wind_game_particles.cpp): sets the push constant word (PushData::motion_param) the patched
    /// particle vertex stage 4cd21a0f reads: the lean of this frame's wind for the particle pairs, else 0
    void WindGameParticlesDraw(const GraphicsPipeline* pipeline, const Shader::Info* fragment);
    /// bbport (r89_wind-foliage-sway): a skinned draw of a pipeline with MotionVectors::Sway: its
    /// motion param word 7 (BbWindSway::PackWord; 0: no sway); the log lines at each frame end
    /// bbport (r89e_twigs-big-trees): small_palette 0 or 1 for a static cut-out candidate of the twigs
    /// (1: it read a small bone palette), -1 for a skinned draw
    /// bbport (r112i_hang-find-lanterns): hang_static: an opaque static draw (small_palette 0 or 1, its
    /// palette flag) that may hang (BB_WIND_HANG_STATIC): no plant, no tree, no twig candidate
    u32 WindSwayWord(const GraphicsPipeline* pipeline, int small_palette = -1,
                     bool hang_static = false);
    void WindSwayFrameEnd();
    /// bbport (r89d_tree-twigs, bbport_wind_twigs.h): whether a skinned sway draw's stream may be a
    /// tree a sun shadow pass draws, its sway word once it has its slot, the Motion block's draws the
    /// sway cannot reach (counted; returns 0) and the twigs' line every 600 frames.
    bool WindTwigTree(u64 positions, u32 positions_size);
    /// bbport (r89e_twigs-big-trees): static cut-out candidates (BB_WIND_TWIGS_SMALL)
    bool WindTwigSmall(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,
                       u32 stride, bool floats, bool palette);
    void WindTwigSmallVerdict(BbWindTwigs::Entry& entry, u64 positions);
    u32 WindTwigWord(u32* words, u32 frame_slot, u32 view, const BbWindSway::Slots::Taken& taken,
                     u64 positions, u32 positions_size, u64 frame, double time, bool small = false);
    u32 WindTwigSkip(bool skinned, bool sway_bit);
    void WindTwigsReport();
    /// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of a colour pass for the census
    /// (kind_slot: BbWindCensus::KindSkinned .. KindNone; sway: its sway word; base_vertex: its base vertex)
    void WindTwigCensus(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, bool is_indexed,
                        u32 index_offset, int kind_slot, u32 sway, int base_vertex);
    /// bbport (r89j_twigs-pick-trees; BB_WIND_TWIGS_TREES=1): whether the candidate draw (trees_draw) is a tree-shaped
    /// mesh of its own and the camera is outdoors; true: positions and positions_size become its vertex range
    /// bbport (r89k_twigs-opaque-word): `opaque` (the pixel shader does not discard): a draw the shape rule refuses may
    /// then be taken as a limb piece of a tree (BbWindTrees::LimbOf; BB_WIND_TWIGS_LIMBS)
    bool WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats, bool opaque);
    /// bbport (r89j_twigs-pick-trees, TOOL; BB_WIND_TWIGS_PICK): a G-buffer draw of a pick frame gets an occlusion query
    void WindTreesPickQuery(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, u32 index_offset,
                            s32 base_vertex, vk::QueryPool& pool, u32& index);
    /// the trees' line every report, the pick's frames and results (once a frame)
    void WindTreesPickFrameEnd();
    /// bbport (r112_wind-more-things): with BB_WIND_HANG=1, whether a skinned draw that is no plant
    /// is a hanging thing's (bbport_wind_hang.h), and once it has a slot its sway word (0, or one
    /// with HangBit: a ramp of 0 while its height is read); a view's push table is filled at its
    /// first pushed draw of a frame
    /// bbport (r112i_hang-find-lanterns): hang_static and stride: an opaque static draw's stream, judged
    /// by the ray traced scene's boxes (WindHangStaticAllowed) and the GPU's keys, with no palette
    bool WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,
                         bool hang_static = false, u32 stride = 0);
    /// bbport (r112h_hang-not-the-hunter): a stream whose box keys read as still: may it hang (not the
    /// hunter's gear, not a figure, not indoors, placed)? False: it is refused and held as moving.
    bool WindHangActorsClear(u64 positions, u64 frame, bool hang_static = false);
    /// bbport (r112i_hang-find-lanterns): an opaque static draw's stream: may it hang (BB_WIND_HANG_STATIC:
    /// small, a box of 0.15-2 m in the ray traced scene, hanging, not the ground)? The scene's boxes are
    /// read every RefreshFrames frames for the verdicts; the survey (BB_WIND_HANG_FIND) every 600 frames
    bool WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame, u64 vs = 0);
    void WindHangFindRefresh(u64 frame);
    void WindHangFindReport();
    /// bbport (r112k_hang-lantern-verdict): whether a GPU-palette draw's stream is a static candidate
    /// (BB_WIND_HANG_STATIC_GPU), and, for the survey (BB_WIND_HANG_FIND), what the Motion block made of a draw
    bool WindHangGpuStatic(const GraphicsPipeline* pipeline);
    void WindHangFindRoute(const GraphicsPipeline* pipeline, char kind, u32 sway, bool delivered);
    u32 WindHangWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions,
                     u64 frame, const BbWind::Snapshot& now);
    /// bbport (r112q_hang-bracket-route, TOOL; BB_WIND_HANG_FIND=1): the counters a draw's sway word moves, the draw's note (its pair of
    /// shaders, kind, word and delivery), the report every 600 frames, and the word of BB_WIND_HANG_FORCE
    BbWindHangRoute::Mark WindHangRouteMark();
    void WindHangRouteNote(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered);
    void WindHangRouteReport();
    bool WindHangProofDraw(const GraphicsPipeline* pipeline, char kind, u32 word, bool delivered); // bbport (r112r_hang-bracket-judge, TOOL)
    u32 WindPostWord(u32* words, u32 frame_slot, u32 view, u32 slot, bool reset, u64 positions, u32 positions_size, u32 positions_stride, u64 frame,
                     const BbWind::Snapshot& now); // bbport (r112s_hang-bracket-move)
    u32 WindHangForceWord(u32* words, u32 frame_slot, u32 view, u32 slot, const BbWind::Snapshot& now);
    /// bbport (r112b_hang-probe, TOOL; BB_WIND_HANG_PROBE=1): a skinned sway draw's first bone
    /// palette goes to hang_probe (from WindHangVerdict); the report goes out once, with r112's
    /// 600-frame lines
    void WindHangProbeSkin(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size);
    void WindHangProbeReport();
    /// bbport (r7_cascades): far sun cascades kept from an earlier frame (sun_hold,
    /// vk_rasterizer_effects.cpp). All run on the thread recording draws (stage B).
    bool SunHoldEarly(const GraphicsPipeline* pipeline);
    void SunHoldBeforePass(RenderState& state);
    void SunHoldInPass(const RenderState& state);
    void SunHoldDrawn();
    void SunHoldOther(const Shader::Info* first, const Shader::Info* second, bool graphics);
    void SunHoldFlush();
    void SunHoldClear(u32 quadrants);
    bool SunHoldImageIntact();
    void SunHoldOff(const char* why);
    void SunHoldFrameEnd();
    /// bbport (r14_cascade_keep): the atlas quadrants of cascades the game left undrawn keep their
    /// depth (sun_keep, vk_rasterizer_effects.cpp). On the thread recording draws.
    bool SunKeepGate() const;
    void SunKeepBeforePass(RenderState& state, bool indirect);
    void SunKeepInPass(const RenderState& state);
    /// bbport: the game's sun shadow atlas (sun_atlas, vk_rasterizer_effects.cpp).
    void SunAtlasResolve(const Shader::Info& ps);
    bool SunAtlasSkipDraw(const GraphicsPipeline* pipeline, const RenderState& state);
    void SunAtlasReader(const char* what, u64 hash);
    void SunAtlasFrameEnd();
    /// bbport (r12_atlas_skip_live): readers of the atlas while far cascades are left out.
    bool SunAtlasLiveReader(const GraphicsPipeline* pipeline, const RenderState& state,
                            u64 ps_hash);
    void SunAtlasReaderQuery(vk::QueryPool& pool, u32& index);
    void SunAtlasQueriesFrameEnd();
    /// r7 diagnostics of the sun atlas (vk_rasterizer_effects.cpp); they change nothing drawn.
    void SunAtlasLight(const GraphicsPipeline* pipeline, u32 cascade, float width, float height);
    void SunAtlasDescribeReader(const GraphicsPipeline* pipeline, const RenderState& state);
    void SunAtlasStatsFrameEnd();
    void SunAtlasStatsReport(double frames);
    /// bbport (r64_surface-probe): BB_SURFACE_PROBE=1 (read once at start, off by default) logs how
    /// the game draws each pair of vertex and pixel shaders, so that one short walk tells how window
    /// panes, lantern glass, small water and blood are drawn (vk_rasterizer_effects.cpp). Log only:
    /// nothing is drawn, bound, measured or compiled for it. Called only while surface_probe_on.
    static bool SurfaceProbeWanted();
    void SurfaceProbeDraw(const GraphicsPipeline* pipeline, bool indirect);
    void SurfaceProbeLamps(const u32* lights, u32 count);
    void SurfaceProbeWater(const u64* counts, u32 count);
    void SurfaceProbeFrameEnd();
    /// bbport (r64b_surface-probe-more): the readback at the first blended scene draw, and the ray
    /// traced scene's counts before its frame end. Called only while surface_probe_on.
    void SurfaceProbeBlendedScene();
    void SurfaceProbeRtScene();
    /// bbport (t70b_mirror-probe, TOOL): BB_REFLECT_PROBE_HIDE / BB_REFLECT_PROBE_RECT (only with
    /// BB_SURFACE_PROBE=1, log only): the rectangle's readback (false, at a blended draw) and its lines (true,
    /// at the frame end).
    void SurfaceProbeRect(bool frame_end);
    const bool surface_probe_on = SurfaceProbeWanted(); ///< bbport (r64_surface-probe)
    const bool cloud_probe_on = CloudProbe::Wanted(); ///< bbport (r104_cloud-probe): TOOL
    /// bbport (r108_spark-probe, TOOL): BB_SPARK_PROBE=1 (read once at start, off by default) logs, a
    /// second after each press of the transform button (L1), the draws new against the second before
    /// the press and those whose largest draw grew (vk_spark_probe.cpp). Log only. Called only while
    /// spark_probe_on.
    static bool SparkProbeWanted();
    void SparkProbeDraw(const GraphicsPipeline* pipeline, bool indirect);
    const bool spark_probe_on = SparkProbeWanted(); ///< bbport (r108_spark-probe, TOOL)
    /// bbport (r110_weapon-sparks): BB_WEAPON_SPARKS=1|2 (read once at start, off by default) draws
    /// the game's own trick weapon transform effect again for 1.5 s after each press of the transform
    /// button (L1): brighter, and with 2 also falling copies (vk_weapon_sparks.cpp). Called only
    /// while weapon_sparks_on, right after the draw command.
    static bool WeaponSparksWanted();
    void WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 num_indices,
                               u32 num_instances, u32 first_vertex, u32 first_instance);
    const bool weapon_sparks_on = WeaponSparksWanted(); ///< bbport (r110_weapon-sparks)
    /// Lamps apart (vk_point_shadow.h): something that is not a draw may touch the light targets.
    void EffectsEndLampBatch();
    void NoteWindowPaneDraw(const AmdGpu::Regs&, const GraphicsPipeline*, bool indexed, u32 first);
    void EffectsCaptureDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                            u32 index_offset, RtShadow::BottleDrawToken& bottle,
                            RtShadow::ReflectionDrawToken& reflection,
                            ReflectionDiscard::StockRole original_stock_role,
                            vk::Pipeline& classified_stock);
    void EffectsBeforeTargets(const GraphicsPipeline* pipeline);
    void EffectsAfterTargets(const GraphicsPipeline* pipeline);
    void LampPaneTargets(const GraphicsPipeline* pipeline, bool gbuffer);
    bool LampPaneDraw(LampPaneProbe& probe, const AmdGpu::Regs& regs,
                      const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset,
                      const RtShadow::Draw& draw);
    void LampPaneDepth(LampPaneProbe& probe);
    bool LampMaterialSample(LampPaneProbe& probe, const RenderState& state,
                            const struct LampMaterialDelivery& delivery, bool after);
    bool SampleDrawRaw(struct DrawRawRead&, const RenderState&,
                       const struct LampMaterialDelivery&, bool after);
    void RecordDrawRaw(const std::array<VideoCore::Image*, 4>& images,
                       std::span<const struct RawDrawPixel> samples, vk::Buffer buffer,
                       const std::array<u64, 4>& offsets);
    struct SewerReceiverProbe;
    std::unique_ptr<SewerReceiverProbe> sewer_receiver;
    friend class Caustics;
    struct SewerJoinedDraw;
    void NoteNativeBedDraw(const RenderState& state, const GraphicsPipeline& pipeline,
                           bool ground, SewerJoinedDraw* joined);
    void SewerReceiverFrameEnd();
    void SewerReceiverGBufferChange();
    void SewerReceiverWaterDraw(const RenderState&, const GraphicsPipeline*);
    void SewerReceiverCopyReport();
    bool SewerReceiverSample(const RenderState&, const struct LampMaterialDelivery&, bool after);
    bool SewerReceiverApply(u64 frame, VideoCore::ImageId depth_id);
    void SewerReceiverConsumer(u64 frame, VideoCore::ImageId depth_id, VideoCore::ImageId albedo_id,
                               VideoCore::Image& depth, VideoCore::Image* albedo,
                               vk::ImageView depth_view, vk::ImageView albedo_view,
                               const ::BbCaustics::Push& push, const std::array<float, 12>& view,
                               bool native);
    bool SampleWindowOwner(const RenderState&, const struct LampMaterialDelivery&, bool after);
    void NoteWindowOwnerTargets(const GraphicsPipeline*);
    bool NoteWindowOwnerGap(WindowPathProbe::PaneOwnerGap kind);
    void LogWindowOwnerGap(const char* kind, const char* identity);
    void FinalWindowOwner(u64 direction_draw, u64 depth_uid, u64 depth_tick);
    void EffectsBlendedScene();
    void EffectsSceneComposite(const GraphicsPipeline* pipeline); // bbport (r45_drawn-look)
    void EffectsBeforeUpscaler(u64 compute_hash);
    void EffectsBeforeResources(const GraphicsPipeline* pipeline);
    void EffectsBeforeBind(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                           u32 index_offset, u32 first_vertex);
    /// bbport (r96_lamp-flicker-colour): BB_LAMP_FLICKER: a light draw's records with its flame
    /// lamps flickered, its buffer 1 bound to them (null: the draw is left as it is).
    const u32* LampFlickerBind(const GraphicsPipeline* pipeline, const Shader::Info& ps,
                               VAddr lights, u32 count);
    vk::Rect2D EffectTile(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                          u32 index_offset, u32 first_vertex) const;
    void EffectsAfterDraw(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed, u32 num_indices,
                          u32 num_instances, u32 first_vertex,
                          const RtShadow::ReflectionDrawToken& reflection,
                          const GraphicsPipeline& raster_pipeline, bool classified_stock_issued);
    bool ReflectionStamp(const AmdGpu::Regs&);
    bool ReflectionCapture(const AmdGpu::Regs&, const GraphicsPipeline&, const RtShadow::Draw&,
                           u32 index_offset, RtShadow::ReflectionDrawToken&);
    void ReflectionBlendedScene();
    void ReflectionFrameEnd();
    void ReflectionNativeBeforeDraw(ReflectionNativeProbe::Draw&);
    void ReflectionNativeAfterDraw(const ReflectionNativeProbe::Draw&);
    void ReflectionNativePoll();
    void ReflectionNativeDestroy();
    void ReflectionPollRequest();
    /// Sky dome seam/zenith correction before the dome draw; true when it resolved the inputs.
    bool SkyBeforeRendering(const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline, bool is_indexed,
                            u32 index_offset, const PreparedDraw* prepared, bool inputs_resolved);
    void DepthOfFieldAfterDraw(const GraphicsPipeline* pipeline, const RenderState& state);
    void HqAoAfterDraw(const GraphicsPipeline* pipeline, const RenderState& state);
    void UpdateDepthStencilState() const;
    void UpdatePrimitiveState(bool is_indexed) const;
    void UpdateRasterizationState() const;
    void UpdateColorBlendingState(const GraphicsPipeline* pipeline) const;

    bool FilterDraw();
    bool FilterDrawPasses() const;
    /// Everything of a direct draw after the pipeline selection (GPU thread or stage B).
    void DrawRecord(const GraphicsPipeline* pipeline, const PreparedDraw* used_prepared,
                    bool is_indexed, u32 index_offset);
    struct GxRegister {
        u16 index;
        u32 value;
    };
    std::array<GxRegister, 160> gx_registers{};
    u32 num_gx_registers = 0;
    const void* gx_state = nullptr;
    void ApplyGxRecord(const GraphicsPipeline* pipeline, const PreparedDraw*& used_prepared, u64 gx_record,
                       bool is_indexed_draw);
    static void SwapGxRegisters(AmdGpu::Regs& regs, GxRegister* list, u32 count);
    static bool DrawPipeWanted();
    bool UseDrawPipe() const;
    bool OnStageA() const;
    /// Arguments of an indirect draw: `args` holds `max_count` commands `stride` apart.
    struct IndirectDraw {
        VAddr args;
        VAddr count; ///< the draw count, or 0 for max_count draws
        u32 stride;
        u32 max_count;
    };
    /// Everything of an indirect draw after the pipeline selection (GPU thread or stage B).
    void DrawIndirectRecord(const GraphicsPipeline* pipeline, bool is_indexed,
                            const IndirectDraw& indirect);
    /// Everything of an indirect dispatch after the pipeline selection.
    void DispatchIndirectRecord(const ComputePipeline* pipeline, VAddr args, u32 size);
    /// bbport (BB_INDIRECT_CLAMP, on by default): the group counts at `offset` in `buffer` copied
    /// by the GPU into the stream buffer, each clamped to maxComputeWorkGroupCount; returns where
    /// the dispatch reads them (the game's own counts when the stream buffer has no room).
    std::pair<vk::Buffer, u64> ClampDispatchArgs(const VideoCore::Buffer* buffer, u64 offset);
    /// Hands a draw (or, with `cs`, a dispatch) to the recording thread.
    void PostDraw(const Pipeline* pipeline, const PreparedDraw* used_prepared, bool is_indexed,
                  u32 index_offset, const AmdGpu::ComputeProgram* cs = nullptr,
                  const IndirectDraw* indirect = nullptr);
    /// Everything of a direct dispatch after the pipeline selection (GPU thread or stage B).
    void DispatchRecord(const ComputePipeline* pipeline);
    /// bbport (docs/pipeline_compiles.md): whether the direct draw being recorded, whose
    /// pipeline is still compiling, is left out: scene geometry, for a bounded time.
    bool SkipUncompiledDraw(const GraphicsPipeline* pipeline);
    /// bbport: for a pipeline still compiling, records its bind as a command of its own, which a
    /// recording thread runs once the pipeline is there (it waits for it): returns null, the
    /// draw or dispatch command binds nothing. Recording on this thread: waits here and returns
    /// the handle.
    vk::Pipeline BindWhenCompiled(const Pipeline* pipeline, vk::PipelineBindPoint bind_point);
    /// The compute registers of the dispatch being recorded.
    const AmdGpu::ComputeProgram& CsRegs() const;
    static void RunDrawPacket(void* rasterizer, const u8* packet, u32 size);
    struct RingBinding;
    void CollectRingBindings(const Shader::Info& stage, const PreparedDraw* prepared,
                             boost::container::static_vector<RingBinding, Shader::NUM_BUFFERS>& out,
                             u32* wall_reason);
    void PrintPipeStats();
    /// The registers of the draw being recorded: stage B's copy there, else Liverpool's.
    const AmdGpu::Regs& Regs() const;
    AmdGpu::CbDbExtent CbExtent(u32 index) const;
    AmdGpu::CbDbExtent DbExtent() const;

    void BindBuffers(const Shader::Info& stage, const PreparedStage* prepared,
                     Shader::Backend::Bindings& binding,
                     Shader::PushData& push_data, u32& write_index);
    /// `on_helper`: run by the texture binding helper; out-of-date images are not refreshed.
    void BindTextures(const Shader::Info& stage, const PreparedStage* prepared,
                      Shader::Backend::Bindings& binding, u32& write_index, bool& barrier,
                      bool on_helper = false);
    /// BB_SECTIONS: a full texture lookup over 0.3 ms, per texture (BindTextures' timestamps).
    void ReportSlowTextureBind(const Shader::Info& stage, u64 start, std::span<const u64> pass1,
                               std::span<const u64> pass2);
    bool BindResources(const Pipeline* pipeline);
    void ForceAnisotropy(AmdGpu::Sampler& sharp, bool is_depth) const;
    float SmoothUiSampler(AmdGpu::Sampler& sharp, bool is_depth, bool ui_replaced) const;
    void BindSamplers(const Shader::Info& stage, const PreparedStage* prepared,
                      Shader::Backend::Bindings& binding, u32& write_index, bool ui_replaced);
    /// bbport: whether stage reads reduced scene proxies through their native images instead:
    /// it has a point-filtered sampler and its pass is at the native size (BindTextures).
    bool PointReadsNative(const Shader::Info& stage, const PreparedStage* prepared) const;
    /// bbport (SamplerMemo): TextureCache::GetSampler hashed, locked and looked the sampler up
    /// for every sampler of every draw. Direct-mapped by the S# (after ForceAnisotropy), the
    /// depth flag and the extra bias: what GetSampler returned for them, while no sampler was
    /// freed since (SamplerGeneration), touched for the collector once per GC period. Only the
    /// thread binding textures uses it (stage B, or the bind helper while stage B waits for it).
    /// BB_SAMPLER_MEMO=0: GetSampler every time.
    struct SamplerMemoEntry {
        std::array<u64, 2> sharp{};
        u64 variant = ~0ull; ///< is_depth << 32 | the extra bias's bits
        vk::Sampler handle{};
        size_t lru_id = 0;
        u64 generation = ~0ull;   ///< TextureCache::SamplerGeneration when looked up
        u64 touched_tick = ~0ull; ///< TextureCache::GcTick of the last LRU touch
    };
    std::array<SamplerMemoEntry, 1024> sampler_memo{};
    u64 sampler_memo_hits = 0, sampler_memo_misses = 0;
    vk::Sampler CachedSampler(const AmdGpu::Sampler& sharp, bool is_depth, float lod_bias);
    /// bbport: a stage's resolved textures remembered by its prepared T# hashes
    /// (TextureSetMemo): a hit only redoes the per-draw effects (binding flags, transitions).
    struct TextureSetEntry {
        VideoCore::ImageId id{}; ///< after the depth redirect; null descriptor when invalid
        VideoCore::ImageId found{}; ///< what FindImage returned (before the depth redirect)
        vk::ImageView view;
        const void* backing = nullptr;
        VideoCore::SubresourceRange range;
        bool proxy = false; ///< sampled from the scene proxy (view: SampleProxy on each use)
    };
    struct TextureSet {
        u64 key = 0;
        const Shader::Info* stage = nullptr;
        u64 generation = ~0ull;
        u64 scene_generation = 0; ///< SceneTargets::Generation of the proxy views
        u32 count = 0;
        /// Every lookup was an exact match (TextureCache::IsExactMatch) and every null
        /// descriptor a null T#: the set survives other images' (un)registration while its
        /// images stay registered (RevalidateTextureSet).
        bool exact = false;
        static constexpr u32 MaxImages = 16; ///< larger sets are not memoized
        std::array<u64, MaxImages> hashes{};
        std::array<TextureSetEntry, MaxImages> entries{};
        std::array<u64, MaxImages> found_uids{}; ///< image uids of entries[].found
    };
    std::array<TextureSet, 32768> texture_sets{};
    u64 texture_set_hits = 0, texture_set_misses = 0;
    std::array<u64, 4> texture_set_why{}; ///< misses: other key, generation, image check, new
    /// bbport: stages that did not try the set: unprepared, no images, over MaxImages, a storage
    /// image or mip override, memo off (toggle, frame capture).
    std::array<u64, 5> texture_set_skip{};
    /// Hits after a registry generation change: texture sets, and single texture lookups
    /// (ImageDescCacheEntry) outside them.
    u64 texture_set_revalidated = 0, texture_lookups_revalidated = 0;
    bool RevalidateTextureSet(TextureSet& set, u64 generation);
    /// Returns true when the stage's images were bound from the memo.
    bool BindTexturesFromSet(const Shader::Info& stage, const PreparedStage* prepared,
                             u32 first_image_idx, bool& barrier, TextureSet*& slot);
    /// The prepared sharps of `stage` in the current prepared draw, if they fit it.
    const PreparedStage* FindPreparedStage(const Shader::Info& stage) const;
    /// The same for any prepared draw (the lookahead thread).
    static const PreparedStage* FindPreparedStage(const PreparedDraw* prepared,
                                                  const Shader::Info& stage);
    /// Whether the helper may bind textures for this pipeline at all (fixed descriptor layout,
    /// no storage writes that invalidate cached images).
    bool HelperEligible(const Pipeline* pipeline) const;
    /// Whether every texture of `stage` takes the memoized path without refreshing, creating or
    /// redirecting anything that records commands or touches the buffer cache.
    bool TexturesBindableOnHelper(const Shader::Info& stage, const PreparedStage* prepared);
    static void RunTextureTask(void* rasterizer);
    static void JoinBindHelper(void* rasterizer);

    /// Display pass: counts the frame (BbStats::gpu_frames) and, with BB_BUFFER_STATS, the lag.
    void NoteFrameStart();
    /// BB_GPU_PROFILE: a timestamp where a render pass starts (vk_gpu_profiler.h).
    void MarkPass(const GraphicsPipeline* pipeline, const RenderState& state);
    void BindVertexBuffers(const GraphicsPipeline* pipeline,
                           const PreparedDraw* prepared = nullptr);
    void BindIndexBuffer(u32 index_offset = 0);
    /// bbport: BindVertexBuffers/BindIndexBuffer in two halves: obtaining the buffers
    /// (vertex_binds, index_bind) and recording the binds.
    void ResolveVertexBuffers(const GraphicsPipeline* pipeline, const PreparedDraw* prepared);
    void EmitVertexBuffers();
    void ResolveIndexBuffer(u32 index_offset);
    void EmitIndexBuffer();

    void ResetBindings(bool is_compute);

    bool IsComputeMetaClear(const Pipeline* pipeline);
    bool IsComputeImageCopy(const Pipeline* pipeline);
    bool IsComputeImageClear(const Pipeline* pipeline);

private:
    friend class VideoCore::BufferCache;

    const Instance& instance;
    Scheduler& scheduler;
    Runtime& runtime;
    VideoCore::PageManager page_manager;
    VideoCore::BufferCache buffer_cache;
    VideoCore::TextureCache texture_cache;
    AmdGpu::Liverpool* liverpool;
    Core::MemoryManager* memory;
    boost::icl::interval_set<VAddr> mapped_ranges;
    Common::SharedFirstMutex mapped_ranges_mutex;
    PipelineCache pipeline_cache;
    std::unique_ptr<DrawPreparation> draw_prep;
    std::unique_ptr<CameraMotion> camera_motion; // bbport: motion vectors (docs/upscaler.md)
    std::unique_ptr<SceneTargets> scene_targets;
    std::unique_ptr<ScreenSpaceGI> ssgi;
    std::unique_ptr<SpatialAo> spatial_ao; // bbport: graphics_ao_quality=1 (High GTAO)
    std::unique_ptr<SsrTemporal> ssr_temporal;
    std::unique_ptr<RtShadow> rt_shadow;
    std::unique_ptr<ContactShadow> contact_shadow;
    /// bbport (r105_cloud-shadows): made only with BB_CLOUD_SHADOWS above 0 or
    /// BB_CLOUD_SHADOWS_SHOW=1 (CloudShadow::Wanted), else null.
    std::unique_ptr<CloudShadow> cloud_shadow;
    /// bbport (r119_volumetric-clouds): made only with BB_VOLUMETRIC_CLOUDS=1 (CloudLayer::Wanted), else
    /// null: its hooks are null pointer tests. Declared after cloud_shadow: it reads that one's clock.
    std::unique_ptr<CloudLayer> cloud_layer;
    std::unique_ptr<PointShadow> point_shadow;
    std::unique_ptr<VolumetricLight> volumetric_light;
    /// bbport (r82_wind-stage1): the shared wind (bbport_wind.h) and the steady clock at its
    /// last advance (zero: not advanced yet); both change only with BB_WIND=1 (WindOnFrameEnd).
    BbWind::State wind;
    std::chrono::steady_clock::time_point wind_time{};
    /// bbport (r89_wind-foliage-sway): the plants' base slots, this frame's views (their 28
    /// constants, sway_views of them, of ObjectMotion frame sway_frame), the log's counts and
    /// the frame ends counted (all only with BB_WIND=1 and BB_WIND_SWAY above 0)
    BbWindSway::Slots sway_slots;
    std::array<BbWindSway::ViewKey, BbWindSway::Views> sway_keys{};
    u32 sway_views = 0;
    u64 sway_frame = ~u64{0};
    BbWindSway::Stats sway_stats;
    /// bbport (r89b_wind-sway-ripple): the ripple's wave phases (BB_WIND_SWAY_RIPPLE above 0)
    BbWindSway::Ripple sway_ripple;
    /// bbport (r117_wind-shelter): made only with BB_WIND=1 and BB_WIND_SHELTER above 0
    /// (WindShelter::Wanted, read once), else null: its hooks are null pointer tests.
    std::unique_ptr<WindShelter> wind_shelter;
    u64 sway_frames = 0;
    BbWindTwigs::Book twig_book;   // bbport (r89d_tree-twigs): sun-drawn streams judged
    BbWindTwigs::Stats twig_stats; // and the line's counts
    BbWindCensus::Book twig_census; // bbport (r89i_twigs-colour-pass, TOOL): the colour passes' rows
    /// bbport (r89j_twigs-pick-trees): the index range of the candidate draw being recorded (WindTreesDraw), the verdicts
    /// on draw ranges, the counters; the pick's note of the draw (kind, sway word), queries and patch
    struct TreesDraw {
        u64 index_address = 0;
        u32 num_indices = 0;
        s32 base_vertex = 0;
        u32 index_size = 0;
        bool valid = false;
    } trees_draw;
    BbWindTrees::Book trees_book;
    BbWindTrees::Stats trees_stats;
    unsigned trees_lines = 0;
    bool trees_last_limb = false; ///< bbport (r89k_twigs-opaque-word): the draw WindTreesDraw took last is a limb piece
    u64 trees_frames = 0;
    struct TreesPickNote {
        int kind = 3;
        u32 sway = 0;
    } trees_pick_note;
    struct TreesPickGroup {
        u32 used = 0;
        bool pending = false;
        u64 tick = 0;
        u32 point = 0;
        u32 skipped = 0;
        u32 meet = 0, apart = 0; ///< bbport (r89k): G-buffer scissors that met / missed the patch
        u64 frame = 0;           ///< the frame it was drawn in
        bool cam_ok = false;
        std::array<float, 3> cam{};
        BbWindTrees::Rect rect{};
        std::vector<BbWindTrees::PickDraw> draws;
    };
    struct TreesPick {
        vk::UniqueQueryPool pool{};
        bool tried = false;
        bool said = false;
        u32 group = 0;
        u64 frame = 0;
        std::array<TreesPickGroup, BbWindTrees::PickGroups> groups;
    } trees_pick;
    bool trees_pick_rect_on = false; ///< this frame draws only the pick's patch of the G-buffer
    vk::Rect2D trees_pick_rect{};
    /// bbport (r89k): scissors that met / missed this frame's patch; mutable: UpdateViewportScissorState is const
    mutable u32 trees_pick_meet = 0, trees_pick_apart = 0;
    // bbport (r86l_glint-pick-glass, TOOL): the glass pick. trees_pick_draw: this draw is narrowed to the patch and given a query
    // (the G-buffer's, as r89j had it, and with the glass pick armed the forward draws of the scene); trees_pick_glass: the glass
    // pick is armed (its draw facts are kept); trees_pick_indexed: the draw is indexed; glass_pick_note: the capture hook's facts
    // of the draw the query site asks about
    bool trees_pick_draw = false;
    bool trees_pick_glass = false;
    bool trees_pick_indexed = false;
    RtGlassPick::PaneSpec glass_pick_panes{};
    struct GlassPickNote {
        bool valid = false;
        u64 positions = 0, key = 0;
        u32 index_count = 0;
        u32 flags = 0;
    } glass_pick_note;
    void GlassPickPoll();
    void GlassPickStash(const RtShadow::Draw& draw);
    void GlassPickGroup(const TreesPickGroup& g, const std::vector<u64>& counts, vk::Result result,
                        const BbWindTrees::Point& pt);
    // bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the G-buffer's texels at the pick pixels, once when the
    // pick is armed. glass_tri_read: wanted at the next blended draw of a frame that is no pick frame; glass_tri_gb, glass_tri_depth:
    // the targets of the last G-buffer pass (EffectsAfterTargets); glass_tri_job: the copy on its way (GlassTriReadPoll).
    const bool glass_tri_on = RtGlassTri::On();
    bool glass_tri_read = false;
    std::array<VideoCore::ImageId, 5> glass_tri_gb{};
    VideoCore::ImageId glass_tri_depth{};
    struct GlassTriJob;
    std::shared_ptr<GlassTriJob> glass_tri_job;
    void GlassTriReadback();
    void GlassTriReadPoll();
    BbWindTrees::Rect trees_pick_game{}; ///< bbport (r89l_twigs-palette-move): this frame's patch in game-target pixels
    /// bbport (r112_wind-more-things): the hanging things' streams, the log's counts, the push
    /// tables' follower, and which views of ObjectMotion frame hang_frame have their table
    BbWindHang::Book hang_book;
    BbWindHang::Stats hang_stats;
    BbWindHangStill::Book hang_still; // bbport (r112d_hang-still-test): palettes' content
    BbWindHangStill::BoxBook hang_box; // bbport (r112f_hang-gpu-judge): the GPU keys' verdicts
    bool hang_judge = false; // set by WindHangVerdict: this draw's stream wants the judging word
    /// bbport (r112p_hang-gpu-palette-lanterns): the streams the CPU palette test refuses (census), the pages of the first
    /// GPU-written palettes watched for a shader write (watch; fed by BindBuffers), the counts of the report window
    BbWindHangGpu::Census hang_gpu_census;
    BbWindHangGpu::Watch hang_gpu_watch;
    BbWindHangGpu::Stats hang_gpu_stats;
    /// bbport (r112h_hang-not-the-hunter): who may hang: the tests, the hunter, the facts of the judging
    /// draws, the sway words lost for want of a motion parameter
    BbWindHangActors::Book hang_actors;
    /// bbport (r112i_hang-find-lanterns): the static streams' verdicts, the ray traced scene's boxes they
    /// are measured against, the capture draws' shaders (the survey) and the counts
    BbWindHangFind::StaticBook hang_static_book;
    BbWindHangFind::BoxSet hang_find_boxes;
    BbWindHangFind::Draws hang_find_draws;
    BbWindHangFind::Routes hang_find_routes; // bbport (r112k_hang-lantern-verdict, TOOL grade): the survey's routes
    BbWindHangFind::Stats hang_find_stats;
    BbWindHang::Push hang_push;
    u64 hang_frame = ~u64{0};
    std::array<bool, BbWindSway::Views> hang_filled{};
    BbWindHangRoute::TintBook hang_tint; // bbport (r112r_hang-bracket-judge, TOOL): the pairs' hang words since the start
    bool hang_proof_hide = false; // the Motion block's verdict for the draw in flight: leave it out (BB_WIND_HANG_PROOF_HIDE)
    BbWindHang::PostBook hang_post; // bbport (r112s_hang-bracket-move): the bracket lanterns' posts (BB_WIND_HANG_POST)
    BbWindHangRoute::Book hang_route; // bbport (r112q_hang-bracket-route, TOOL): the stream groups' routes
    BbWindHangRoute::Mark hang_route_before; // the counters before the draw's word
    std::unique_ptr<BbWindHangProbe::Skin> hang_probe; // bbport (r112b, TOOL): null when off
    std::unique_ptr<SkySeam> sky_seam;
    std::unique_ptr<SkyZenith> sky_zenith;
    /// bbport (r98_ambient-particles): made only with BB_PARTICLES above 0 and the upscaler
    /// on, else null; it draws through TemporalUpscaler::after_upscale.
    std::unique_ptr<AmbientParticles> ambient_particles;
    /// bbport (r100c_blood-pool-probe, TOOL): made only with BB_BLOOD_POOL_PROBE not off at start
    /// (BloodPoolProbe::Wanted), else null: its hooks are null pointer tests. BloodPoolProbeBefore
    /// (vk_blood_pool_probe.cpp) hands it a draw's targets; called only while it is made.
    std::unique_ptr<BloodPoolProbe> blood_pool_probe;
    void BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light);
    /// bbport (r100d_blood-pool-draws, TOOL): a probed draw's index range and textures once they are
    /// bound (vk_blood_pool_probe.cpp); called only while blood_pool_probe is made.
    [[nodiscard]] BloodPoolProbe::FoliageFacts FoliageProbeFacts(
        const GraphicsPipeline& pipeline, bool camera_gbuffer, bool indirect, bool is_indexed,
        u32 index_offset);
    void BloodPoolProbeNote(const GraphicsPipeline* pipeline, bool indirect, bool is_indexed,
                            u32 index_offset);
    std::unique_ptr<DepthOfField> depth_of_field;
    std::unique_ptr<FroyokBloom> froyok_bloom;
    /// bbport (r95_halation, r109a): null until the first frame with a strength above 0
    /// (Halation::Strength), then made (EffectsBeforeUpscaler) and kept.
    std::unique_ptr<Halation> halation;
    /// bbport (r120_test-camera-lookat, TOOL): null until the first BB_TEST_WORLD_AT read (or BB_TEST_CAMERA=lookat:centre), then made
    /// (EffectsBeforeUpscaler) and kept; its hooks are null pointer tests.
    std::unique_ptr<TestWorldAt> test_world_at;
    std::unique_ptr<WindowPathProbe::ReceiverCapture> window_receiver;
    WindowPathProbe::ColdPaneWatch window_cold_pane;
    void InitColdWindowPane();
    void ExpireColdWindowPane();
    void ArmWindowPane(WindowPathProbe::ReceiverCapture&, bool wait_for_natural);
    bool window_receiver_enabled = false;
    u32 window_receiver_generation = 0, window_receiver_last_request = 0;
    void CaptureWindowReceiver(const AmdGpu::Regs&, u64 ps_hash);
    void CaptureWindowDepth();
    void PollWindowReceiver();
    /// bbport (r100_blood-sheen): made only with BB_BLOOD_SHEEN on (BloodSheen::Wanted), else
    /// null: its hooks are null pointer tests.
    std::unique_ptr<BloodSheen> blood_sheen;
    /// bbport (r129a_glass-registry): made only with BB_GLASS_TABLE naming a valid entry (GlassRegistryRules::Load), else null:
    /// the draw hook is one null pointer test. glass_view: also BB_GLASS_VIEW=1 or the live knobs file (GlassView::Wanted).
    std::unique_ptr<GlassRegistry> glass_registry;
    std::unique_ptr<GlassView> glass_view;
    /// bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR=1 or the live knobs file, with a valid registry (GlassClear::Wanted);
    /// otherwise none is made and the hooks are null pointer tests.
    std::unique_ptr<GlassClear> glass_clear;
    /// bbport (t129c_sun-term-view, TOOL): made only with BB_RT_SUN_TERM_VIEW=1 or the live knobs file (SunTermView::Wanted), else
    /// null: its hooks are null pointer tests.
    std::unique_ptr<SunTermView> sun_term_view;
    /// bbport (r129a_glass-registry): from DrawRecord, right before EffectsBeforeResources, only with glass_registry:
    /// looks the draw up, counts a hit, sets DrawContext::glass_hit and, with the view on, records the SNAPSHOT.
    void GlassRegistryDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset);
    /// bbport (r86b_glass-visible): made only with BB_GLASS_GLINT and BB_RT_GLASS on
    /// (GlassGlint::Wanted), else null: its hooks are null pointer tests. glint_pending: the
    /// pipeline of the pane draw EffectsCaptureDraw admitted, for its EffectsAfterDraw.
    std::unique_ptr<GlassGlint> glass_glint;
    /// bbport (r131a_foliage-translucency): made only with the back-lit glow on (FoliageGlow::Wanted: BB_FOLIAGE_GLOW or the setting, with BB_RT_CARD_ALPHA=2
    /// and BB_RT_CARD_LAMPS=1), else null: its hooks are null pointer tests.
    std::unique_ptr<FoliageGlow> foliage_glow;
    std::unique_ptr<BottleCaustic::Pass> bottle_caustic;
    struct ReflectionProbe {
        ReflectionProbe(const Instance& instance, Scheduler& scheduler,
                        VideoCore::TextureCache& textures, Runtime& runtime)
            : pass(instance, scheduler, textures, runtime) {}
        ReflectionFirstHit::Pass pass;
        std::optional<ReflectionFirstHit::Stamp> stamp;
        std::optional<ReflectionFirstHit::Request> request;
        u64 pass_serial{}, last_request{}, blended_pass{}, input_frame{};
        u64 input_bytes{}, input_refused{}, source_attempts{}, bad_stamp{};
        u32 knob_generation = ~u32{0};
        u64 request_frame{};
        bool tainted{};
    };
    std::unique_ptr<ReflectionProbe> reflection_probe;
    struct ReflectionNativeSlot {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        void* mapped{};
        u64 bytes{}, tick{}, generation{}, serial{};
        ReflectionNativeProbe::Key key{};
        std::array<u32, ReflectionNativeProbe::MaxBindings> binding_bytes{};
        bool confirmed{};
    };
    std::array<ReflectionNativeSlot, 8> reflection_native_slots{};
    struct ReflectionNativePace {
        u64 frame{}, phase{}, retry_until{}, retry_generation{};
        u32 phase_used{}, total{}, retries{};
        bool cap_logged{};
    };
    std::array<ReflectionNativePace, ReflectionNativeProbe::WitnessCount> reflection_native_pace{};
    u64 reflection_native_serial{};
    std::unique_ptr<FoliageMask> foliage_mask;
    std::atomic<bool> foliage_collect{};
    struct MaskReceivers {
        FoliageMask::Key key{};
        std::array<VideoCore::ImageId, 3> ids{};
        std::array<vk::ImageView, 3> views{};
        std::array<u64, 3> writes{};
        std::array<VAddr, 3> starts{}, ends{};
        std::array<float, 12> view{};
        std::array<float, 4> projection{};
        std::array<float, 2> jitter{};
        u64 proxy_generation{};
    } mask_receivers;
    u64 mask_serial{}, mask_frame{}, mask_capture{}, mask_diag_started{};
    bool mask_diagnostic{}, mask_diag_requested{}, mask_frame_started{}, mask_finished{};
    u32 mask_draws{}, mask_tags{};
    struct MaskWriterEvidence {
        const char* guard{};
        u32 subject{};
        u64 observed{}, expected{};
    } mask_writer_evidence;
    void FoliageRefuseWriter(const char* guard, u32 subject = 0, u64 observed = 0, u64 expected = 0);
    void FoliageCheckReceivers();
    void FoliageWriter(VAddr address, u64 size,
                       FoliageBoundary::Source source = FoliageBoundary::Source::NonDraw);
    void FoliageObserveDraw(const GraphicsPipeline* pipeline, FoliageBoundary::Source source,
                            bool tagged);
    void FoliageFrameEnd();
    bool FoliageClass(const GraphicsPipeline& pipeline, bool is_indexed, u32 index_offset);
    const GraphicsPipeline* FoliageAttach(const GraphicsPipeline* pipeline, const RenderState& original,
                                          RenderState& state, FoliageBoundary::Source source);
    vk::ImageView FoliageDiagnosticView();
    const GraphicsPipeline* glint_pending = nullptr;
    /// bbport (r86i_glint-find-gbuffer): a pane drawn by the G-buffer (BB_GLASS_BOX_PANES): its glint waits
    /// for the lit scene (EffectsBlendedScene); the draw's pair and counts for the log; cleared at the frame end.
    ::BbGlassGlint::PaneDraw glint_gpane{};
    bool glint_gpane_on = false;
    /// bbport (r111_footprints): made only with BB_FOOTPRINTS on (Footprints::Wanted), else null:
    /// its two hooks are null pointer tests.
    std::unique_ptr<Footprints> footprints;
    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)
    // bbport (r107_caustics): made only while BB_CAUSTICS gives a strength above 0 or "show"
    // (Caustics::Wanted, read once), else null: its three hooks are null pointer tests.
    std::unique_ptr<Caustics> caustics;
    // bbport (r97_heat-haze): made only while BB_HEAT_HAZE gives a strength above 0
    // (HeatHaze::Wanted, read once), else null: its hooks are null pointer tests.
    std::unique_ptr<HeatHaze> heat_haze;
    // bbport (r62_leaf-stage3): made only with BB_RT_CARD_ALPHA=2 (CardAlpha::Wanted), else null;
    // card_bound_on: it is made and on (set once, at the start; read by the binding helper too):
    // BindTextures notes what a pixel shader's binding found (DrawContext::card_bound) and a
    // cut-out draw asks for its card's layer.
    std::unique_ptr<CardAlpha> card_alpha;
    bool card_bound_on = false;
    bool effects_wanted = false;
    /// bbport (r45_drawn-look): DrawnLook::Wanted() as EffectsOnFrameEnd read it. Apart from
    /// effects_wanted: wanting the look starts none of the other effects' work on every draw.
    bool drawn_look_wanted = false;
    u32 ssr_frame = 0;
    u32 shadow_frame = 0;
    vk::Rect2D effect_tile{};
    /// bbport: of the draw EffectsBeforeBind is called for: its pass's size, and whether its first
    /// two colour targets are cleared when the pass begins (lamps apart, vk_point_shadow.h).
    vk::Extent2D effect_pass{};
    bool effect_plain_pair = false;
    bool effect_skip_draw = false; ///< bbport: EffectsBeforeBind left this draw out
    /// bbport: the game's sun shadow atlas while the ray traced sun or the VSM replaces the
    /// game's sun shadow: draws into cascades nothing samples are left out (SunAtlasSkipDraw;
    /// experiment 8192 draws them all, as before).
    struct SunAtlas {
        VAddr address = 0;             ///< the shadow resolve's image 1 (0: none seen)
        std::array<float, 3> splits{}; ///< the resolve's cascade splits (constants 80..82)
        bool splits_valid = false;
        float coverage = 0.0f;         ///< the resolve's uniforms 72 (shadow distance)
        float reach = 0.0f;            ///< the volumetric march's this frame (0: not sampled)
        bool resolved = false;         ///< a resolve was seen this frame
        bool other_reader = false;     ///< sampled by something else: never left out again
        bool any_skipped = false;      ///< a draw was left out this frame
        u32 steady = 0;                ///< frames in a row whose sun shadow was replaced
        u32 needed = 4;                ///< cascades the volumetric march samples
        u32 skip_from = 4;             ///< first cascade left out (4: none)
        u32 skipped_mask = 0;          ///< cascades with draws left out since the last resolve
        u32 drawn_mask = 0;            ///< cascades with draws this frame
        // bbport (r51_volumetric-leak): the cascades the volumetric march read at the last resolve
        // (VolumetricOcclusion::Valid), and in how many of the frames it marched; the r19 path
        // counts draws into drawn_mask while the march wants it (mask_wanted), looking the depth
        // target up once a pass (mask_pass, mask_atlas); mask_spread counts this frame's atlas
        // draws across quadrants or without a single viewport (all four for the mask, as r14
        // counts them), spread_frames the frames with one. mask_wanted ends with a frame
        // without a resolve.
        u32 valid_mask = 0xF;
        std::array<u32, 4> valid_frames{};
        u32 march_frames = 0;
        bool mask_wanted = false;
        u64 mask_pass = ~0ull;
        bool mask_atlas = false;
        u32 mask_spread = 0, spread_frames = 0;
        u32 frames = 0, left_out_frames = 0;
        std::array<u64, 4> cascade_draws{}, cascade_skipped{}, cascade_frames{};
        // r7 (diagnostics only): every draw into the atlas is counted, whatever is left out.
        u64 reader_vs = 0, reader_ps = 0; ///< the other reader's shaders (0: none, or a dispatch)
        u64 reader_draws = 0;             ///< its draws since the last report
        u64 last_pass = ~0ull;            ///< Scheduler::PassesBegun at the last atlas draw
        const GraphicsPipeline* last_pipeline = nullptr;
        u64 atlas_draws = 0, atlas_passes = 0, clear_passes = 0, clear_draws = 0;
        u64 no_viewport = 0, spanning = 0, same_pipeline = 0, no_constants = 0;
        struct PassNote {
            u8 cascade = 0; ///< 0..3; 4 across cascades, 5 no single viewport, 6 mixed
            u8 clear = 0;   ///< 1: the pass begins with a clear, 2: a DB clear draw in it
            u16 draws = 0;
            s16 x = 0, y = 0;
            u16 w = 0, h = 0;
        };
        std::array<PassNote, 64> pass_notes{};
        u32 pass_count = 0, pass_logs = 0;
        bool pass_log = false, note_open = false, check_frame = false;
        u64 stats_frame = 0;
        struct Light {
            std::array<float, 28> m{};         ///< projection (4x4 rows), view to world (3x4 rows)
            float width = 0.0f, height = 0.0f; ///< the cascade's viewport
            bool valid = false;
        };
        std::array<Light, 4> light{}, previous_light{};
        u32 light_mask = 0; ///< cascades whose light matrix was read this frame
        struct LightStats {
            u64 compared = 0, same = 0, turned = 0, moved = 0, measured = 0, whole = 0;
            u64 checked = 0, other_matrix = 0;
            double sum_texels = 0.0, max_texels = 0.0, max_delta = 0.0;
        };
        std::array<LightStats, 4> light_stats{};
    } sun_atlas;
    /// bbport (r19_draw-cost): what this draw's Motion block found (DrawRecord), for
    /// EffectsCaptureDraw of the same draw: its index range check and, when its buffer walk met
    /// no skeleton and no GPU-written palette (complete), its bone palette hash.
    struct R19Motion {
        bool valid = false;
        bool indices_valid = false;
        bool palette_complete = false;
        u64 palette = 0;
    } r19_motion;
    /// bbport (r19_draw-cost): short path counters, printed every 600 frames (EffectsOnFrameEnd).
    struct R19Stats {
        u64 frames = 0, sun_short = 0, motion_indices = 0, motion_palettes = 0;
    } r19_stats;
    /// bbport (r12_atlas_skip_live, experiment bit 549755813888 clear): who else samples the sun
    /// atlas. The water (ps e3021062) is measured by occlusion queries of its own around its draws,
    /// read without waiting once the GPU is past the frame; far cascades are left out only while it
    /// showed no samples for QuietFrames frames. Any other draw reader, or a dispatch or indirect
    /// draw using the atlas, keeps every cascade for the rest of the session (as before).
    struct SunReader {
        static constexpr u32 Groups = 8;      ///< frames of water queries in flight at most
        static constexpr u32 PerGroup = 8;    ///< water draws measured in a frame at most
        static constexpr u64 QuietFrames = 8; ///< frames without water samples before leaving out
        static constexpr u64 MaxLag = 4;      ///< an answer later than this: the water counts as seen
        vk::UniqueQueryPool pool{};
        bool pool_tried = false;
        bool measure_now = false; ///< the draw being recorded is a water draw (SunAtlasSkipDraw)
        bool latched = false;     ///< another reader: every cascade is drawn from now on
        bool water_noted = false;
        bool cleared = false; ///< this frame's atlas pass began with a clear of the whole image
        VideoCore::ImageId cleared_image{}; ///< the image that clear was of
        bool quiet = false;   ///< no water samples (nor unmeasured water draws) lately
        bool blocked = false; ///< this frame's query group still waits for its answer
        bool water_now = false, unmeasured_now = false; ///< this frame
        bool water_before = false; ///< the frame before drew the water
        u32 group = 0;                    ///< this frame's group of queries
        std::array<u32, Groups> used{};   ///< queries begun in a group's frame
        std::array<u64, Groups> tick{};   ///< the scheduler tick at that frame's end
        std::array<u64, Groups> frame{};  ///< that frame's frame_index
        std::array<bool, Groups> pending{}; ///< its answers not read yet
        u64 frame_index = 0;
        u64 last_seen = 0; ///< the last frame whose water had samples or was not measured
        // Report (every 600 frames, with the "Sun atlas:" lines).
        u64 water_draws = 0, measured = 0, unmeasured = 0, water_frames = 0;
        u64 seen_frames = 0, hidden_frames = 0, late = 0, blocked_frames = 0, other_draws = 0;
        u64 clear_kept = 0, colour_kept = 0, motion_kept = 0;
        std::array<u64, 4> capture_kept{};
    } sun_reader;
    /// bbport (r7_cascades): far sun cascades kept from an earlier frame. A cascade whose caster
    /// draws carry the light matrix, viewport and scissor its quadrant was drawn with is not drawn
    /// again (BB_SUN_CASCADE_EVERY; experiment 268435456 draws every cascade every frame).
    struct SunHold {
        struct Light {
            std::array<float, 28> m{}; ///< projection (4x4 rows), view to world (3x4 rows)
            u64 view = 0;              ///< SunViewKey of its draws (viewport, scissor registers)
            bool valid = false;
        };
        struct ViewEntry {
            u64 key = 0;
            u8 cascade = 4; ///< 0..3; 4: more than one quadrant, or no single viewport
            bool used = false;
        };
        bool active = false;       ///< asked for, experiment 268435456 clear, not off for good
        bool off_for_good = false; ///< something it does not handle was seen (printed)
        std::array<u32, 4> every{1, 1, 1, 1}; ///< BB_SUN_CASCADE_EVERY
        VAddr atlas = 0;     ///< sun_atlas.address at the last frame end
        VAddr z_address = 0; ///< the atlas's depth base register (learned from its passes)
        VideoCore::ImageId image{};
        u64 image_uid = 0;
        const void* backing = nullptr;
        VideoCore::SubresourceRange range{};
        u32 width = 0, height = 0;
        RenderState last_state{}; ///< an atlas pass drawing depth, loading it (SunHoldFlush)
        bool last_state_valid = false;
        std::array<ViewEntry, 16> views{};
        u32 next_view = 0;
        // The draw being recorded (SunHoldEarly, SunHoldInPass, SunHoldDrawn).
        u64 draw_key = 0;
        u8 draw_cascade = 4; ///< a classified atlas draw going to be drawn (4: none)
        u8 draw_learned = 4;
        bool draw_known = false;
        bool atlas_pass = false;
        // This frame.
        u32 plan = 0, plan_start = 0; ///< cascades to keep (drawn after all if their matrix moved)
        u32 decided = 0, confirmed = 0, spared = 0, pending_clear = 0, stale = 0;
        float clear_depth = 1.0f;
        bool image_checked = false, force = false;
        const char* why = "";
        u32 atlas_draws = 0, unknown_draws = 0, spanning_draws = 0;
        std::array<u32, 4> arrived{}, drawn{};
        std::array<Light, 4> frame_light{};
        std::array<VAddr, 4> const_address{};
        std::array<bool, 4> match{}, multi{}, special{}, no_constants{};
        // Across frames.
        std::array<Light, 4> held{}; ///< what each quadrant was last drawn in full with
        std::array<u32, 4> age{};    ///< frames it has been kept since
        std::array<float, 3> splits{};
        bool splits_valid = false;
        Light previous_c0{};
        u32 steady = 0;
        u64 frame = 0, frames_total = 0;
        // Report (every 600 frames).
        u32 frames = 0, kept_frames = 0, forced_frames = 0;
        const char* last_why = "none";
        std::array<u64, 4> skipped{}, kept{}, planned{}, broke{}, flushed{};
        u64 converted = 0, unconverted = 0, flush_failed = 0, mismatched = 0, lost = 0;
        u64 stale_draws = 0, unknown_total = 0, spanning_total = 0;
    } sun_hold;
    /// bbport (r14_cascade_keep): while the game leaves sun cascades undrawn on some frames
    /// (BbSunCascades::skip_period > 1, experiment 1099511627776 clear) the atlas's clear of the
    /// whole image is taken over: each quadrant is cleared right before the first draw into it, so
    /// a quadrant its cascade did not draw into keeps its depth (the game keeps that cascade's
    /// matrices too). Learned from the draws that arrive; an atlas frame runs from one clear of
    /// the whole image to the next.
    struct SunKeep {
        bool active = false;  ///< at the last clear of the whole image: clears are taken over
        bool open = false;    ///< this atlas frame's clear was taken over
        bool tracked = false; ///< `image` was cleared whole or by quadrants since it was made
        u32 linger = 0;       ///< atlas frames still taken over once the game stops skipping
        u32 period = 0;       ///< skip_period when last asked
        VideoCore::ImageId image{}; ///< the atlas image at the last atlas draw
        u64 image_uid = 0;
        const void* backing = nullptr;
        u64 write_seq = 0;         ///< its write_seq then (one count per pass begun on it)
        u32 width = 0, height = 0; ///< the size of the pass the clear was taken over in
        float clear_depth = 1.0f;
        u64 clear_pass = ~0ull; ///< PassesBegun() of the pass whose clear was taken over
        // The draw being recorded (SunKeepBeforePass, SunKeepInPass).
        bool atlas_pass = false, indirect = false, take_clear = false;
        // This atlas frame.
        u32 cleared = 0xFu;     ///< quadrants cleared (or owed a clear: pending) since its clear
        u32 drawn = 0;          ///< quadrants with draws
        u32 pending = 0;        ///< clears owed: recorded with the next draw in a pass that can
        bool whole_now = false; ///< a fallback cleared every quadrant: nothing kept
        // Across atlas frames.
        std::array<u32, 4> age{}; ///< atlas frames in a row a quadrant kept its depth
        u32 blank = 0;            ///< quadrants holding only the clear value
        // Report (every 600 atlas frames).
        u32 frames = 0, mode_frames = 0;
        u64 taken = 0, whole = 0, rects = 0, deferred = 0;
        const char* last_whole = "none";
        std::array<u64, 4> clears{}, expired{}, kept{};
    } sun_keep;
    bool scene_started = false;
    /// bbport (r77_parallel-test-runs): clean shot as the last display pass read it, for the
    /// whole frame (a change never splits a frame's UI), and where that frame is and its UI's
    /// targets (CleanShotEarly).
    bool clean_shot_frame = false;
    UiComposition::CleanShotFrame clean_shot_state;
    /// bbport: the scene depth of the frame before (SkipUncompiledDraw).
    VideoCore::ImageId previous_scene_depth{};
    void Round2CaptureFrame(VideoCore::ImageId target);
    void WorkflowFrameEnd();
    void WorkflowNative(VideoCore::ImageId target);
    WorkflowProbe::ScissorQuery WorkflowQueryDraw(const GraphicsPipeline* pipeline, const RenderState& state,
                                                  const WorkflowProbe::DrawCommand& command, bool competing_probe,
                                                  u32 sway_off_slot = 0, u32 capture_word = 0);
    void WorkflowCopyIndex(const RenderState& state, u32 row);
    std::unique_ptr<WorkflowProbe::Renderer> workflow;
    struct Round2FrameReadbacks {
        // A single atomic tracks count and VMA bytes at the same acquisition/release point.
        // At most three 1080p staging buffers occupy the lower 60 bits.
        static constexpr u64 CountUnit = 1ull << 60;
        std::atomic<u64> live{0};
    };
    struct Round2FrameSeries {
        u32 generation = ~0u, series = 0, remaining = 0, stride = 1, last_pick = 0, ordinal = 0;
        u64 next_scene = 0;
        bool long_series_used = false;
        u32 peak_inflight = 0;
        u64 peak_allocated_bytes = 0;
        std::shared_ptr<Round2FrameReadbacks> inflight;
    } round2_frames;
    std::unique_ptr<ObjectMotion> object_motion;
    bool gbuffer_draw = false;
    std::unique_ptr<HdrNative> hdr_native; // bbport: native HDR output (docs/hdr.md); before
                                           // the upscaler, which uses it
    std::unique_ptr<TemporalUpscaler> upscaler; // bbport: FSR (docs/upscaler.md)
    std::array<float,2> target_offset{};
    std::array<float, 2> target_scale{1.0f, 1.0f}; ///< pass drawn into the upscaler's output-size images
    std::array<u32, 2> ui_full_scissor{}; ///< widened UI pass: a scissor this large (guest) is the whole image
    UiPass ui_pass{}; ///< the open pass's (BeginRenderingFull, or the memo's)
    const bool host_markers_enabled;
    const bool guest_markers_enabled;

    using RenderTargetInfo = std::pair<VideoCore::ImageId, VideoCore::TextureCache::ImageDesc>;
    std::array<RenderTargetInfo, AmdGpu::NUM_COLOR_BUFFERS> cb_descs;
    std::pair<VideoCore::ImageId, VideoCore::TextureCache::ImageDesc> db_desc;
    struct BoundBuffer {
        const VideoCore::Buffer* buffer;
        u64 offset;
        u32 size;
        bool is_written;
    };
    /// bbport: uniform buffers bound by BindBuffers outside the constant ring (BB_FRAME_STATS):
    /// at an aligned offset, with an offset in the push data, or copied by the CPU or the GPU to an
    /// aligned place
    /// (Profile::uniform_exact_base). Ring bindings are counted too.
    struct UboStats {
        u64 ring = 0;
        u64 in_place = 0;
        u64 offset = 0;
        u64 staged = 0;
        u64 copied = 0;
    } ubo_stats;
    void ReportUboStats();


    // bbport: bindings point at their description instead of copying it (a hot spot): into
    // image_desc_cache for memoized lookups (pinned for the current BindTextures call), else
    // into image_desc_storage.
    using ImageBindingInfo = std::pair<VideoCore::ImageId, const VideoCore::TextureCache::ImageDesc*>;
    // bbport: texture descriptions depend only on the T# and three resource flags; building
    // them (mip layout sizes) for every binding of every draw was a hot spot.
    struct ImageDescCacheEntry {
        std::array<u64, 4> sharp{};
        u32 flags = ~0u;
        VideoCore::TextureCache::ImageDesc desc;
        // Memoized FindImage for bindings without mip overrides (TextureBindingMemo).
        u64 found_generation = ~0ULL;
        VideoCore::ImageId found_id{};
        /// found_id was an exact match (TextureCache::IsExactMatch, found_desc unchanged by
        /// FindImage): the memo outlives other images' (un)registration while image found_uid
        /// stays registered (LookupMemoized).
        bool found_exact = false;
        u64 found_uid = 0;
        VideoCore::TextureCache::ImageDesc found_desc;
        u64 pinned = 0; ///< bind_epoch of the BindTextures call referencing found_desc
        u64 last_use = 0;
        // Memoized FindView for found_id (after the depth redirect): valid while the entry's
        // FindImage memo holds and the image keeps this backing (TextureViewMemo).
        VideoCore::TextureCache::ViewMemo view_memo;
    };
    std::array<ImageDescCacheEntry, 4096> image_desc_cache{};
    u64 desc_use_counter = 0;
    /// Entries replacing pinned cache slots during one BindTextures call.
    u64 bind_epoch = 0;
    // bbport: render/depth target lookups memoized by their raw register bytes while image
    // registrations are unchanged (the descriptions depend only on those registers).
    // An exact match (TextureCache::IsExactMatch, description unchanged by FindImage) outlives
    // other images' (un)registration while image `uid` stays registered (RevalidateTarget).
    struct TargetMemo {
        std::array<u8, 256> key{};
        u32 key_size = 0;
        u64 generation = ~0ULL;
        VideoCore::ImageId image_id{};
        bool exact = false;
        u64 uid = 0;
        VideoCore::TextureCache::ImageDesc desc;
    };
    std::array<TargetMemo, 64> target_memo{};
    // bbport: consecutive draws mostly keep their targets; the slot's description (cb_descs,
    // db_desc) is then still the right one and is neither looked up nor copied.
    struct LastTarget {
        std::array<u8, 256> key{};
        u32 key_size = 0;
        u64 generation = ~0ULL; ///< ~0: invalid (FindImage may have rewritten the description)
        VideoCore::ImageId image_id{};
        bool exact = false;
        u64 uid = 0;
    };
    std::array<LastTarget, AmdGpu::NUM_COLOR_BUFFERS + 1> last_targets{}; ///< CBs, then DB
    u64 target_lookups_revalidated = 0;
    template <typename Memo>
    bool RevalidateTarget(Memo& memo, u64 generation);
    template <typename... Parts>
    VideoCore::ImageId FindTargetMemoized(VideoCore::TextureCache::ImageDesc& desc,
                                          LastTarget& last, auto&& make_desc,
                                          const Parts&... parts);
    /// The prepared draw whose pipeline the current Draw uses (its sharps are valid), or null.
    /// `hash` is ImageDescHash(sharp, res), computed by a draw-preparation worker or here.
    ImageDescCacheEntry& CachedImageDescEntry(const AmdGpu::Image& sharp,
                                              const Shader::ImageResource& res, u64 hash);
    /// Whether the entry's FindImage memo holds in registry generation `generation`: memoized
    /// in it, or an exact match still registered (then taken into it).
    bool LookupMemoized(ImageDescCacheEntry& entry, u64 generation);
    /// bbport (r62_leaf-stage3): a cut-out draw's card gets its alpha layer (CardAlpha::NoteDraw)
    /// from the image this draw's pixel shader binding found for the card's T# (card_bound).
    void NoteCardLayer(CardDraw& card, const Shader::Info& ps);
    ImageDescCacheEntry& CachedImageDescEntry(const AmdGpu::Image& sharp,
                                              const Shader::ImageResource& res) {
        return CachedImageDescEntry(sharp, res, ImageDescHash(sharp, res));
    }
    const VideoCore::TextureCache::ImageDesc& CachedImageDesc(const AmdGpu::Image& sharp,
                                                              const Shader::ImageResource& res) {
        return CachedImageDescEntry(sharp, res).desc;
    }
    struct VertexBinds {
        VertexInputs<vk::VertexInputAttributeDescription2EXT> attributes;
        VertexInputs<vk::VertexInputBindingDescription2EXT> bindings;
        VertexInputs<vk::Buffer> host_buffers;
        VertexInputs<vk::DeviceSize> host_offsets;
        VertexInputs<vk::DeviceSize> host_sizes;
        VertexInputs<vk::DeviceSize> host_strides;
        u32 num_buffers = 0;
    };
    struct IndexBind {
        vk::Buffer handle;
        u64 offset;
        vk::IndexType type;
    };
    /// bbport (r21_draw-sort): experiment bit: set = the old binds (every draw records its
    /// vertex input, vertex buffers and index buffer) and nothing counted for "Draw order (r21)".
    static constexpr u64 R21DrawSortOffBit = 70368744177664ull;
    /// bbport (r21_draw-sort): the vertex input, vertex buffers and index buffer last recorded;
    /// in force while Scheduler::R21Serial() and R21Epoch() are still `serial` and `epoch`.
    struct R21Bound {
        u64 serial = ~0ull;
        u64 epoch = ~0ull;
        bool input_known = false, buffers_known = false, index_known = false;
        VertexInputs<vk::VertexInputAttributeDescription2EXT> attributes;
        VertexInputs<vk::VertexInputBindingDescription2EXT> bindings;
        VertexInputs<vk::Buffer> buffers;
        VertexInputs<vk::DeviceSize> offsets;
        u32 num_buffers = 0;
        IndexBind index{};
    } r21_bound;
    /// What the current draw's binds did: 0 nothing to bind (or experiment set), 1 left out
    /// (equal to the bind in force), 2 recorded (another in force), 3 recorded (unknown what).
    struct R21Outcome {
        u8 input = 0, buffers = 0, index = 0;
    } r21_outcome;
    struct R21Row {
        u64 draws = 0, descriptors = 0;
        std::array<std::array<u64, 4>, 3> binds{}; ///< vertex input, vertex buffers, index buffer
    };
    struct R21Stats {
        u32 frame = 0;
        u64 frames = 0;
        bool window_off = false; ///< the experiment bit for every frame of this window
        u64 pass = ~0ull;        ///< Scheduler::R21FreshPasses of the last counted draw
        bool atlas_pass = false; ///< that pass draws into the sun atlas
        const GraphicsPipeline* atlas_last = nullptr;
        std::array<const GraphicsPipeline*, 64> pass_seen{};
        u32 pass_seen_n = 0;
        std::array<const GraphicsPipeline*, 256> frame_seen{};
        u32 frame_seen_n = 0;
        struct Counts {
            R21Row all, atlas;
            u64 atlas_passes = 0, atlas_changes = 0, atlas_pass_distinct = 0,
                atlas_frame_distinct = 0;
        } c;
    } r21_stats;
    /// bbport (r21_draw-sort): BB_DRAW_ORDER=1: R21AfterDraw counts and prints "Draw order
    /// (r21)". Off: nothing counted (the bind skip does not depend on it).
    static bool R21Counting() noexcept {
        static const bool on = [] {
            const char* env = std::getenv("BB_DRAW_ORDER");
            return env && env[0] == '1';
        }();
        return on;
    }
    bool R21Begin(bool dynamic_input);
    void R21End(bool on, u64 serial, u64 epoch);
    void R21AfterDraw(const GraphicsPipeline* pipeline, bool is_indexed);
    /// The direct draw whose vertex/index buffers BindResources may resolve early.
    struct DrawInputs {
        const GraphicsPipeline* pipeline;
        const PreparedDraw* prepared;
        u32 index_offset;
        bool is_indexed;
        bool pending;
        bool resolved;
    };
    // bbport: textures of a draw bound on the helper thread while this thread binds buffers.
    static bool BindHelperWanted();
    BindHelper bind_helper{BindHelperWanted()};
    struct TextureTask {
        struct Stage {
            const Shader::Info* info;
            const PreparedStage* prepared;
            Shader::Backend::Bindings binding;
            u32 write_index;
        };
        std::array<Stage, Shader::MaxStageTypes> stages;
        u32 count = 0;
        u32 completed = 0; ///< stages the helper bound; the rest are bound after the join
        bool barrier = false;
    } texture_task;
    /// Draws whose textures the helper bound completely, partly or not at all (BB_FRAME_STATS).
    u64 helper_full = 0, helper_partial = 0, helper_serial = 0;
    /// The memoized cache entry of each image binding (FindImage memo taken), else null.
    bool fault_process_pending{};
    bool attachment_feedback_loop{};
    // bbport: two-stage draw pipeline (stage B state; the thread is the last member so it
    // stops first).
    static inline thread_local const AmdGpu::Regs* stage_regs = nullptr;
    static inline thread_local const AmdGpu::ComputeProgram* stage_cs = nullptr;
    AmdGpu::Regs pipe_regs{};
    bool pipe_synced = false;
    /// Stage A: small read-only guest buffers copied into the constant ring for a packet.
    struct RingBinding {
        u32 index;  ///< buffer resource of the stage
        u32 size;
        u64 location; ///< Physical offset in ordinary builds, absolute allocation in observer builds.
        VAddr address;

        u64 Offset() const {
#ifdef BB_TEST_SHARED_POST_GRAPH
            return location % ConstantRing::Capacity;
#else
            return location;
#endif
        }
    };
    /// Stage A: the newest draw pipe packet that reads guest memory, hashed per granule: 256 bytes
    /// for bindings up to 4 KiB, 16 KiB up to 256 KiB, 1 MiB above (a note costs a few granules,
    /// a lookup checks all three). A collision only makes a write wait longer.
    /// bbport: a note also goes into the coarser levels' rollups (rollups[0]: 16 KiB granules of
    /// level 0 notes, rollups[1]: 1 MiB granules of level 0 and 1 notes). A lookup spanning more
    /// than RollupAbove granules of a level reads the rollup instead, so a large range costs a few
    /// slots, not one per 256 bytes (1 MiB was 4096 slots, ~5% of the GPU command thread). A
    /// rollup only ever reads newer, so a write may wait longer, never too little.
    struct PendingReads {
        static constexpr u64 Shifts[3] = {8, 14, 20};
        static constexpr u64 Limits[2] = {4_KB, 256_KB};
        static constexpr u32 Bits = 16;
        static constexpr u64 RollupAbove = 32;
        std::array<std::vector<u64>, 3> tables{std::vector<u64>(1u << Bits),
                                               std::vector<u64>(1u << Bits),
                                               std::vector<u64>(1u << Bits)};
        std::array<std::vector<u64>, 2> rollups{std::vector<u64>(1u << Bits),
                                                std::vector<u64>(1u << Bits)};
        static u64 Slot(u64 granule, u32 level) {
            return ((granule * 4 + level) * 0x9E3779B97F4A7C15ull) >> (64 - Bits);
        }
        static void Raise(std::vector<u64>& table, u32 level, u32 shift, VAddr address, u64 size,
                          u64 packet) {
            for (u64 g = address >> shift; g <= (address + size - 1) >> shift; ++g) {
                u64& slot = table[Slot(g, level)];
                slot = std::max(slot, packet);
            }
        }
        static u64 Max(const std::vector<u64>& table, u32 level, u32 shift, VAddr address,
                       u64 size) {
            u64 newest = 0;
            for (u64 g = address >> shift; g <= (address + size - 1) >> shift; ++g) {
                newest = std::max(newest, table[Slot(g, level)]);
            }
            return newest;
        }
        static u64 Granules(VAddr address, u64 size, u32 shift) {
            return ((address + size - 1) >> shift) - (address >> shift) + 1;
        }
        void Note(VAddr address, u64 size, u64 packet) {
            const u32 level = size <= Limits[0] ? 0 : size <= Limits[1] ? 1 : 2;
            Raise(tables[level], level, Shifts[level], address, size, packet);
            if (level == 0) {
                Raise(rollups[0], 0, Shifts[1], address, size, packet);
            }
            if (level <= 1) {
                Raise(rollups[1], 1, Shifts[2], address, size, packet);
            }
        }
        u64 Newest(VAddr address, u64 size) const {
            u64 newest = Max(tables[2], 2, Shifts[2], address, size);
            // Level 1 notes: exact up to RollupAbove granules, else the 1 MiB rollup.
            const bool coarse1 = Granules(address, size, Shifts[1]) > RollupAbove;
            newest = std::max(newest, coarse1 ? Max(rollups[1], 1, Shifts[2], address, size)
                                              : Max(tables[1], 1, Shifts[1], address, size));
            // Level 0 notes: exact, the 16 KiB rollup, or (already read) the 1 MiB one.
            if (Granules(address, size, Shifts[0]) <= RollupAbove) {
                newest = std::max(newest, Max(tables[0], 0, Shifts[0], address, size));
            } else if (!coarse1) {
                newest = std::max(newest, Max(rollups[0], 0, Shifts[1], address, size));
            }
            return newest;
        }
    };
    static constexpr u32 WaitedGranuleShift = 16;
    static constexpr u64 WaitedScanLimit = 4096;
    static bool ReadTrackingFiltered();
    bool WaitedOnBefore(VAddr address, u64 size) const;
    bool NoteWaitedOn(VAddr address, u64 size);
    std::array<u64, 1u << 16> waited_on{};
    u64 newest_pending_write = 0;
    PendingReads pending_reads;
    struct ConstantCopy {
        VAddr address;
        u32 size;
        u32 version;
        u64 at;
        u64 offset;
        u64 hash;
    };
    std::array<ConstantCopy, 4096> constant_copies{};
    std::vector<u64> gpu_written_granules = std::vector<u64>(1u << 14);
    u64 constant_checks = 0;
    PendingReads pending_write_table; ///< the same per granule for GPU writes queued (NotePendingGpuWrite)
    u64 untracked_reads_packet = 0; ///< newest packet reading guest memory it does not list
    u64 constram_waits_skipped = 0; ///< statistics: CPU writes that did not have to wait
    u64 proxy_samples = 0; ///< texture bindings that read a scene proxy (statistics)
    bool scene_debug_frame = false; ///< BB_SCENE_DEBUG: this frame's passes are printed
    u32 preupload_frame = ~0u; ///< bbport: frame of the last background pre-upload
    bool PendingWriteOverlaps(VAddr address, u64 size);
    /// Stage B: the ring bindings of the stages of the packet being recorded.
    struct RingStage {
        const Shader::Info* info;
        const RingBinding* bindings;
        u32 count;
    };
    /// bbport: the vertex stream V#s of the packet being recorded (stage B; empty elsewhere).
    struct ObjectBind {
        u64 key;
        VAddr base;
        u64 size;
        u64 generation;
        const VideoCore::Buffer* buffer;
        u64 offset;
    };
    std::array<ObjectBind, 4096> object_binds{};
    u64 object_bind_checks = 0;
    std::pair<const VideoCore::Buffer*, u64> BindByObject(u64 key, VAddr base, u64 size);
    std::pair<const VideoCore::Buffer*, u64> BindVertexRange(u64 key, VAddr base, u64 size);
    struct VertexMemo {
        VAddr base = 0;
        u64 size = 0;
        u64 generation = 0;
        const VideoCore::Buffer* buffer = nullptr;
        u64 offset = 0;
        bool in_place = false;
    };
    std::array<VertexMemo, 4096> vertex_memo{};
    BbEngine::Batch::Mode vertex_memo_mode = BbEngine::Batch::Off;
    std::pair<const VideoCore::Buffer*, u64> BindVertexMemo(VAddr base, u64 size);
    /// bbport: the vertex memo is used (on unless LANTERN_VERTEX_MEMO=0; experiment 2097152: off).
    [[nodiscard]] bool VertexMemoOn() const;
    struct SealedBind {
        VAddr base = 0;
        u64 size = 0;
        u32 id = 0, generation = 0;
        u64 layout = 0;
        const VideoCore::Buffer* buffer = nullptr;
        u64 offset = 0;
    };
    std::array<SealedBind, 4096> sealed_binds{};
    BbEngine::Batch::Mode own_buffers_mode = BbEngine::Batch::Off;
    u64 sealed_hits = 0, sealed_misses = 0, sealed_draws = 0, unsealed_draws = 0;
    bool SealedLookup(VAddr base, u64 size, const VideoCore::Buffer*& buffer, u64& offset);
    static constexpr u64 RangeBindKey = 0x52414e4745ull;
    u64 range_binds = 0, range_hits = 0, range_checked = 0, range_differ = 0;
    unsigned ivy_material_attempts{};
    bool ivy_material_recorded{};
    void RecordIvyMaterial(const GraphicsPipeline& pipeline, const RenderState& state,
                           const IvyMaterialProbe::Snapshot& draw);

    struct DrawContext {
#ifdef BB_TEST_SHARED_POST_GRAPH
        SewerBridge::PostDraw* shared_post{};
#endif
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    BottleDisplay182::Draw* bottle_display_operands{};
#endif
        IvyMaterialProbe::Snapshot* ivy_material{};
        bool motion_draw = false;
        bool capture_draw = false;
        u64 motion_geometry{};
        std::array<float, 2> draw_jitter{};
        boost::container::static_vector<vk::DescriptorImageInfo, Shader::NUM_IMAGES> image_infos;
        boost::container::static_vector<vk::DescriptorBufferInfo, Shader::NUM_BUFFERS> buffer_infos;
        boost::container::static_vector<VideoCore::ImageId, Shader::NUM_IMAGES> bound_images;
        boost::container::static_vector<BoundBuffer, Shader::NUM_BUFFERS> bound_buffers;
        u32 set_write_index{};
        Pipeline::DescriptorWrites set_writes;
        Shader::PushData push_data;
        boost::container::static_vector<ImageDescCacheEntry, Shader::NUM_IMAGES> image_desc_overflow;
        boost::container::static_vector<VideoCore::TextureCache::ImageDesc, Shader::NUM_IMAGES * 2> image_desc_storage;
        const PreparedDraw* bind_prepared = nullptr;
        boost::container::static_vector<ImageBindingInfo, Shader::NUM_IMAGES> image_bindings;
        boost::container::static_vector<ImageDescCacheEntry*, Shader::NUM_IMAGES> image_binding_entries;
        bool needs_barrier{};
        std::array<AmdGpu::CbDbExtent, AmdGpu::NUM_COLOR_BUFFERS> pipe_cb_extent{};
        AmdGpu::CbDbExtent pipe_db_extent{};
        float sampler_lod_bias = 0.0f;
        bool pipeline_is_compute = false;
        bool ui_movie_draw = false;
        bool ui_additive = false;
        std::array<RingStage, Shader::MaxStageTypes> ring_stages{};
        u32 num_ring_stages = 0;
#ifdef BB_TEST_SHARED_POST_GRAPH
        u64 ring_packet_end{};
#endif
        std::span<const AmdGpu::Buffer> packet_vsharps;
        std::span<const u64> packet_vkeys;
        std::span<const u64> packet_view_keys;
        u64 packet_index_key = 0;
        VertexBinds vertex_binds;
        BloodPoolProbe::BoundIndex* blood_index = nullptr; // t178, direct draw scope
        IndexBind index_bind{};
        DrawInputs draw_inputs{};
        ReflectionNativeProbe::Draw* reflection_native{};
        u32 wall_stream_packet{}, wall_stream_reason{};
        struct {
            VideoCore::BufferCache::WallStreamProbe* receipt{};
            vk::DescriptorBufferInfo descriptor{};
            VAddr guest{};
            u32 slot{}, adjust{}, write_index{};
            bool origin5{}, checked{};
        } wall_stream;
        /// bbport (r129a_glass-registry): the registry entry of the draw being recorded, index + 1 (0: none); set by
        /// GlassRegistryDraw only, so 0 while the registry is off; valid to the end of DrawRecord.
        u8 glass_hit = 0;
        /// bbport (r131c_cabinet-glass-clear): this draw is the cabinet's pane and goes into side images (set by GlassRegistryDraw,
        /// false while no GlassClear is made); read by DrawRecord before the pass begins.
        bool clear_draw = false;
        // bbport (r62_leaf-stage3): with card_bound_on, what the pixel shader's texture binding
        // of this draw found, image by image (a texture set hit: the set's entries; otherwise its
        // lookups, before any depth redirect), with the image uids, for NoteCardLayer. stage:
        // the pixel shader it is for (null: not known, as when an image took several bindings).
        // 208 bytes a draw context, made for every player; written only with the knob.
        struct CardBound {
            const Shader::Info* stage = nullptr;
            u32 count = 0;
            std::array<VideoCore::ImageId, TextureSet::MaxImages> ids{};
            std::array<u64, TextureSet::MaxImages> uids{};
        } card_bound;
    };
    std::unique_ptr<DrawContext> main_context = std::make_unique<DrawContext>();
    static inline thread_local DrawContext* thread_context = nullptr;
    DrawContext& Dc() const {
        DrawContext* context = thread_context;
        return context ? *context : *main_context;
    }
    const RingBinding* FindRingBinding(const Shader::Info& stage, u32 index) const {
        for (u32 i = 0; i < Dc().num_ring_stages; ++i) {
            if (Dc().ring_stages[i].info == &stage) {
                for (u32 j = 0; j < Dc().ring_stages[i].count; ++j) {
                    if (Dc().ring_stages[i].bindings[j].index == index) {
                        return &Dc().ring_stages[i].bindings[j];
                    }
                }
                return nullptr;
            }
        }
        return nullptr;
    }
    std::unique_ptr<ConstantRing> constant_ring;
    /// Submissions (prepared draws) kept alive until stage B reaches the position.
    std::deque<std::pair<u64, std::shared_ptr<const void>>> pipe_keepalive;
    /// bbport: real occlusion query results (vk_occlusion.h); null with BB_OCCLUSION=0. Before
    /// the draw pipe: its thread (which runs the dumps) stops first.
    std::unique_ptr<Occlusion> occlusion;
    std::unique_ptr<DrawPipe> draw_pipe;
    /// bbport BB_DRAWREC_WORKERS=1 (docs/parallel-stageb.md): the lookahead thread bb:DrawAhead
    /// walks the draw pipe a few packets ahead of stage B and asks the cache for the lines its
    /// next draws read first (texture set memo slots, image slots, page tracking words, the
    /// arena table). It reads the packets and their prepared draws only and changes nothing:
    /// stage B's work and order are as without it. After draw_pipe: it stops before the ring goes.
    static bool LookaheadWanted();
    static u32 LookaheadWindow();
    void LookaheadLoop(std::stop_token stop);
    /// The prefetches for one packet; false when it holds nothing to prefetch for.
    bool PrefetchPacket(const u8* data, u32 size);
    u32 PrefetchDraw(const u8* data, u32 size);
    std::jthread lookahead_thread;

    /// BB_HONEST_LABELS (SignalAfterGpu). Last: its thread stops before the scheduler goes.
    struct GpuSignal {
        u64 tick;
        std::function<void()> signal;
        VAddr label;
        u64 value;
    };
    void GpuSignalLoop(std::stop_token token);
    /// bbport: GpuSignalLoop has waited 10 s for `tick`: prints whether the GPU or the port is stuck.
    void GpuWatchdog(u64 tick);
    std::mutex gpu_signals_mutex;
    std::condition_variable_any gpu_signals_cv;
    std::deque<GpuSignal> gpu_signals;
    /// bbport: signals registered on the draw recording thread since it last handed them over
    /// (PublishSignals: at the end of each guest submission and at every flush), one lock per
    /// batch instead of per fence (~450 fences a frame).
    std::vector<GpuSignal> local_signals;
    std::atomic<u32> local_signal_count{0};
    void PublishSignals();
    /// Draw pipe position up to which the recording thread's signals are handed over: fences
    /// handed to it before are in gpu_signals (or written).
    std::atomic<u64> signals_published_upto{0};
    std::atomic<bool> signal_flush_requested{false};
    std::jthread gpu_signal_thread;
    bool gpu_signal_started = false;
    void SubmitForSignalsNow();
    /// steady_clock nanoseconds of the last submission (written by both pipeline stages).
    std::atomic<s64> last_flush_ns{0};
};

} // namespace Vulkan
