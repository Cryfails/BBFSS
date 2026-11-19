// SPDX-FileCopyrightText: Copyright 2025 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <thread>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <unordered_map>
#include <cstring>
#include <string>
#ifndef _WIN32
#include <dlfcn.h>
#include <execinfo.h>
#include <unistd.h>
#endif
#include <functional>

#include "bbport_copy.h"
#include "bbport_platform.h"
#include "bbport_sections.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "bbport_toggles.h"
#include "bbport_wait_trace.h"
#include "common/assert.h"
#include "common/debug.h"
#include "common/thread.h"
#include "imgui/renderer/texture_manager.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_optiscaler.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
#include "video_core/renderer_vulkan/vk_workflow_probe.h"
#endif
#include "bbport_threads.h"

namespace Vulkan {

std::mutex Scheduler::submit_mutex;

namespace {
// bbport: ProducerScope state of this thread: the producer function it is in (any scheduler).
thread_local const char* producer_scope_where = nullptr;
std::atomic<u32> producer_reports{0};

/// Names a thread of this process (its comm).
std::string ThreadName(u32 tid) {
    char path[64];
    std::snprintf(path, sizeof(path), "/proc/self/task/%u/comm", tid);
    std::string name = "?";
    if (FILE* file = std::fopen(path, "r")) {
        char buffer[32]{};
        if (std::fgets(buffer, sizeof(buffer), file)) {
            name = buffer;
            if (!name.empty() && name.back() == '\n') {
                name.pop_back();
            }
        }
        std::fclose(file);
    }
    return name;
}

void ReportProducer(const char* what, u32 other, const char* other_where, const char* where) {
    if (producer_reports.fetch_add(1, std::memory_order_relaxed) >= 8) {
        return;
    }
    const u32 self = BbPlatform::CurrentThreadId();
    std::fprintf(stderr,
                 "Scheduler: %s: thread %u (%s) entering %s while thread %u (%s) is in %s\n",
                 what, self, ThreadName(self).c_str(), where, other, ThreadName(other).c_str(),
                 other_where ? other_where : "?");
    void* frames[24];
    const int depth = static_cast<int>(BbPlatform::CaptureStack(frames, 24));
#ifdef _WIN32
    for (int i = 0; i < depth; ++i) {
        char description[512];
        BbPlatform::DescribeAddress(frames[i], description, sizeof(description));
        std::fprintf(stderr, "  %s\n", description);
    }
#else
    backtrace_symbols_fd(frames, depth, 2);
#endif
}
} // namespace

void Scheduler::ProducerScope::Enter(const char* where) noexcept {
    previous_where = producer_scope_where;
    static thread_local const u32 tid = BbPlatform::CurrentThreadId();
    producer_scope_where = where;
    u32 expected = 0;
    if (scheduler.producer_tid.compare_exchange_strong(expected, tid,
                                                       std::memory_order_acq_rel)) {
        outer = true;
        scheduler.producer_where.store(where, std::memory_order_relaxed);
        return;
    }
    if (expected != tid) {
        ReportProducer("CONCURRENT recording", expected,
                       scheduler.producer_where.load(std::memory_order_relaxed), where);
    }
}

void Scheduler::ProducerScope::Leave() noexcept {
    producer_scope_where = previous_where;
    if (outer) {
        scheduler.producer_tid.store(0, std::memory_order_release);
    }
}

namespace {

/// bbport: Vulkan recording threads: BB_VK_RECORD_THREADS, else 2 from 8 hardware threads and 3
/// from 12. One thread records ~75% of a core at 200 FPS (4 cores / 8 threads); the segments
/// let the stream use more than one.
u32 RecordingThreadCount() {
    if (const char* env = std::getenv("BB_VK_RECORD_THREADS")) {
        return std::clamp(std::atoi(env), 1, 8);
    }
    const unsigned available = BbThreads::Available();
    return available >= 12 ? 3 : available >= 8 ? 2 : 1;
}

vk::CommandBuffer BeginCommandBuffer(CommandPool& pool) {
    const vk::CommandBuffer cmdbuf = pool.Commit();
    Check(cmdbuf.begin({.flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit}));
    return cmdbuf;
}

} // namespace

Scheduler::Scheduler(const Instance& instance, bool threaded_recording)
    : instance{instance}, work_semaphore{instance}, command_pool{instance, &work_semaphore} {
    crumb_stream = Breadcrumbs::NewStream(
        instance, threaded_recording ? "draws: game and presenter" : "presentation");
    // bbport: BB_VK_RECORD_THREAD=0 records on the calling thread.
    const char* env = std::getenv("BB_VK_RECORD_THREAD");
    if (threaded_recording && !(env && env[0] == '0')) {
        record_chunk = AcquireChunk();
        ordered_chunk = AcquireChunk();
        // A segment of ~64 KiB of closures is ~60 draws: a frame of ~700 draws gives each
        // thread several segments, and the render passes a cut reopens stay few.
        const char* segment_kb = std::getenv("BB_VK_SEGMENT_KB");
        split_bytes = size_t(segment_kb ? std::max(1, std::atoi(segment_kb)) : 64) * 1024;
        const u32 count = RecordingThreadCount();
        for (u32 i = 0; i < count; ++i) {
            auto worker = std::make_unique<Worker>();
            if (i == 0) {
                worker->pool = &command_pool;
            } else {
                worker->own_pool = std::make_unique<CommandPool>(instance, &work_semaphore);
                worker->pool = worker->own_pool.get();
            }
            workers.push_back(std::move(worker));
        }
        for (u32 i = 0; i < count; ++i) {
            // Lambdas, not std::bind_front: clang with libstdc++ (Linux) finds no stop_token call.
            workers[i]->thread = std::jthread(
                [this](std::stop_token stoken, u32 index) { RecorderThread(stoken, index); }, i);
        }
        std::printf("GPU: %u Vulkan recording thread%s, segments of %zu KiB\n", count,
                    count == 1 ? "" : "s", split_bytes / 1024);
    }
#if TRACY_GPU_ENABLED
    profiler_scope = reinterpret_cast<tracy::VkCtxScope*>(std::malloc(sizeof(tracy::VkCtxScope)));
#endif
    // bbport BB_ASYNC_SUBMIT (default on; 0: off): submissions go out from the recording threads
    // once their segments are recorded, instead of this thread waiting for them (~65 us each).
    if (!workers.empty()) {
        const char* async = std::getenv("BB_ASYNC_SUBMIT");
        async_submit = !async || async[0] != '0';
        // OptiScaler's frame generation on: one thread submits (its submit hooks keep global
        // state). Upscaling alone keeps async submit (0.9.33 ran it so at full FPS); =1 forces it.
        async_submit = async_submit && !OptiScaler::SyncSubmit();
        if (async_submit) {
            std::printf("GPU: submissions go out from the recording threads (BB_ASYNC_SUBMIT)\n");
        }
    }
    AllocateWorkerCommandBuffers();
    priority_pending_ops_thread =
        std::jthread([this](std::stop_token stoken) { PriorityPendingOpsThread(stoken); });
}

Scheduler::~Scheduler() {
    if (!workers.empty()) {
        SyncRecording();
        for (auto& worker : workers) {
            worker->thread.request_stop(); // wakes its wait on worker->cv
        }
        for (auto& worker : workers) {
            worker->thread.join();
        }
    }
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    NativeWriteSuffix::Recorder::Get().Detach(this);
#endif
#if TRACY_GPU_ENABLED
    std::free(profiler_scope);
#endif
}

#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
namespace {
// Both callers hold Scheduler::submit_mutex around the actual queue call and this observation.
void NoteNativeSubmit(Scheduler* scheduler, vk::Queue queue, u32 family, vk::Semaphore work_timeline,
                      u64 tick,
                      std::span<const vk::CommandBuffer> sparse, SubmitInfo& info, size_t stage_capacity,
                      const vk::SubmitInfo& submitted, const vk::TimelineSemaphoreSubmitInfo& values,
                      vk::Fence fence, vk::Result result) {
    auto& recorder = NativeWriteSuffix::Recorder::Get();
    const bool armed = recorder.Armed();
#ifdef BB_TEST_SHARED_POST_GRAPH
    static u64 next_graphics_sequence{};
    const auto sequence = ++next_graphics_sequence;
    if (!armed && !info.observe_post_present_submit) {
        return;
    }
#else
    constexpr u64 sequence = 0;
    if (!armed) {
        return;
    }
#endif
    const size_t count = submitted.pCommandBuffers ?
        std::min<size_t>(submitted.commandBufferCount, sparse.size()) : 0;
    const std::span ordered{submitted.pCommandBuffers, count};
    auto raw = NativeWriteSuffix::ActualQueueSubmitInput(
        queue, family, fence, result, work_timeline, sequence, submitted,
        values, info.wait_semas.size(), stage_capacity);
    raw.metadata_complete &= count == submitted.commandBufferCount;
    if (armed) {
        if (!raw.metadata_complete) {
            recorder.Unordered(scheduler, NativeWriteSuffix::Gap::UnjoinedBuffer);
        }
        recorder.Submit(scheduler, tick, ordered, sparse, result == vk::Result::eSuccess, &raw);
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    info.NotifyPostPresentSubmit(scheduler, tick, raw, ordered, sparse);
#endif
}
} // namespace

NativeWriteSuffix::Encoder Scheduler::EncodeNativeWriteSuffix(vk::CommandBuffer cmdbuf) {
    using namespace NativeWriteSuffix;
    auto& recorder = Recorder::Get();
    if (!recorder.Armed()) {
        return {};
    }
    if (const auto* context = worker_segment) {
        if (context->scheduler == this && cmdbuf == context->buffer) {
            return recorder.Encode(this, context->tick, context->segment, cmdbuf);
        }
    } else if (batch && cmdbuf == current_cmdbuf) {
        return recorder.Encode(this, batch->native_suffix_tick, current_segment, cmdbuf);
    }
    recorder.Unordered(this, Gap::UnjoinedBuffer);
    return {};
}
#endif

#ifdef BB_TEST_SHARED_POST_GRAPH
NativeWriteSuffix::CaptureId Scheduler::ArmPostNativeOrder(NativeWriteSuffix::PostKey key) {
    using namespace NativeWriteSuffix;
    ProducerScope producer{*this, "ArmPostNativeOrder"};
    if (!batch || open_post_borrow || thread_sink || fork_open || worker_segment ||
        in_recorded_closure) {
        return 0;
    }
    auto& recorder = Recorder::Get();
    const auto capture = recorder.Arm(this, Consumer::PostOrder, batch->native_suffix_tick,
                                      post_raw_tick > work_semaphore.KnownGpuTick(),
                                      is_rendering || resume_rendering, key);
    if (capture && (host_copies_done.load(std::memory_order_acquire) != host_copies_issued ||
                    deferred_signals_done->load(std::memory_order_acquire) !=
                        deferred_signals_issued.load(std::memory_order_relaxed))) {
        recorder.Unordered(this, Gap::OrderedHost);
    }
    return capture;
}

NativeWriteSuffix::PostToken Scheduler::ReservePostNativeOperation(
    NativeWriteSuffix::CaptureId capture, NativeWriteSuffix::PostRole role, u64 operation) {
    return NativeWriteSuffix::Recorder::Get().ReservePost(this, capture, role, operation);
}

Scheduler::PostNativeBorrow Scheduler::BorrowPostNativeRoot(NativeWriteSuffix::PostToken token) {
    using namespace NativeWriteSuffix;
    ProducerScope producer{*this, "BorrowPostNativeRoot"};
    const bool scoped = token && batch && !open_post_borrow && !thread_sink && !fork_open &&
                        !worker_segment &&
                        !in_recorded_closure && Recorder::Get().OpenPostRoot(this, token);
    if (scoped) {
        open_post_borrow = token.capture;
    }
    const auto buffer = BorrowCommandBuffer(scoped, __builtin_return_address(0));
    return {*this, scoped ? token : PostToken{}, buffer};
}

Scheduler::PostNativeBorrow::PostNativeBorrow(Scheduler& scheduler_, NativeWriteSuffix::PostToken token_,
                                               vk::CommandBuffer buffer_)
    : scheduler{scheduler_}, token{token_}, buffer{buffer_}, producer{std::this_thread::get_id()},
      origin{scheduler.batch ? scheduler.batch->native_suffix_tick : 0,
             scheduler.post_borrow_epoch, scheduler.current_segment, buffer} {}

Scheduler::PostNativeBorrow::~PostNativeBorrow() {
    Close(false);
}

bool Scheduler::PostNativeBorrow::StillCurrent(bool allow_inline_recorded) const {
    using namespace NativeWriteSuffix;
    return producer == std::this_thread::get_id() && scheduler.batch &&
           scheduler.open_post_borrow == token.capture && !thread_sink && !scheduler.fork_open &&
           !worker_segment && (allow_inline_recorded || !in_recorded_closure) &&
           origin.Matches({scheduler.batch->native_suffix_tick, scheduler.post_borrow_epoch,
                           scheduler.current_segment, scheduler.current_cmdbuf});
}

void Scheduler::PostNativeBorrow::Note() {
    if (!token) {
        return;
    }
    if (!StillCurrent()) {
        NativeWriteSuffix::Recorder::Get().ClosePostRoot(&scheduler, token, false);
        return;
    }
    scheduler.NotePostNativeRoot(token, buffer);
}

bool Scheduler::PostNativeBorrow::NoteOverwriteBarrier(
    vk::CommandBuffer issued, const vk::ImageMemoryBarrier2& barrier,
    const NativeWriteSuffix::PostMergeAllocation& backing) {
    using namespace NativeWriteSuffix;
    if (producer != std::this_thread::get_id()) {
        Recorder::Get().Unordered(&scheduler, Gap::UnjoinedBuffer);
        return false;
    }
    if (!token) {
        return false;
    }
    if (overwrite_attempted || overwrite_unclassified || issued != buffer || !StillCurrent(true) ||
        !barrier.image || barrier.pNext || !backing.allocator || !backing.allocation ||
        !backing.memory || !backing.bytes || !backing.epoch ||
        merge_barrier_count == merge_barriers.size()) {
        overwrite_unclassified = true;
        return false;
    }
    merge_barriers[merge_barrier_count++] = {barrier, backing};
    return true;
}

bool Scheduler::PostNativeBorrow::NoteOverwriteRoot(
    vk::CommandBuffer issued, const NativeWriteSuffix::PostMergeRootProof& proof) {
    using namespace NativeWriteSuffix;
    if (producer != std::this_thread::get_id()) {
        Recorder::Get().Unordered(&scheduler, Gap::UnjoinedBuffer);
        return false;
    }
    if (!token) {
        return false;
    }
    overwrite_unclassified |= std::exchange(overwrite_attempted, true);
    if (issued != buffer || !StillCurrent()) {
        overwrite_unclassified = true;
        Recorder::Get().ClosePostRoot(&scheduler, token, false);
        return false;
    }
    auto evidence = overwrite_unclassified ? PostMergeRootEvidence{} :
        CheckPostMergeRoot(origin, proof, scheduler.instance.GetGraphicsQueueFamilyIndex(),
                           std::span{merge_barriers}.first(merge_barrier_count));
    const auto owns_backing = [allocator = scheduler.instance.GetAllocator()](const PostMergeImage& image) {
        if (!allocator || image.allocator != allocator) {
            return false;
        }
        VmaAllocationInfo actual{};
        vmaGetAllocationInfo(allocator, image.allocation, &actual);
        return actual.deviceMemory == VkDeviceMemory(image.memory) &&
               actual.offset == image.allocation_offset && actual.size == image.allocation_bytes;
    };
    if (evidence && (!owns_backing(proof.rgb) || !owns_backing(proof.destination) ||
                     !owns_backing(proof.alpha))) {
        evidence = {};
    }
    return scheduler.NotePostNativeRoot(token, issued, &evidence);
}

void Scheduler::PostNativeBorrow::Close(bool all_raw_uses_classified) {
    CloseImpl(all_raw_uses_classified, NativeWriteSuffix::PostOverwriteTail::Unknown);
}

void Scheduler::PostNativeBorrow::CloseAfterOverwrite(NativeWriteSuffix::PostOverwriteTail tail) {
    using namespace NativeWriteSuffix;
    const bool explained = overwrite_attempted && !overwrite_unclassified &&
                           (tail == PostOverwriteTail::NoRawCommands ||
                            tail == PostOverwriteTail::BreadcrumbOnly);
    CloseImpl(explained, tail);
}

void Scheduler::PostNativeBorrow::CloseImpl(bool fully_classified,
                                           NativeWriteSuffix::PostOverwriteTail tail) {
    if (!token) {
        return;
    }
    const bool exact = fully_classified && StillCurrent();
    const auto closed = std::exchange(token, {});
    const bool joined = NativeWriteSuffix::Recorder::Get().ClosePostRoot(&scheduler, closed, exact, tail);
    if (producer == std::this_thread::get_id() && scheduler.open_post_borrow == closed.capture) {
        scheduler.open_post_borrow = 0;
        if (!joined && scheduler.batch) {
            scheduler.post_raw_tick = std::max(scheduler.post_raw_tick, scheduler.batch->native_suffix_tick);
        }
    }
}

bool Scheduler::NotePostNativeRoot(NativeWriteSuffix::PostToken token, vk::CommandBuffer buffer,
                                   const NativeWriteSuffix::PostMergeRootEvidence* overwrite) {
    auto encoder = EncodeNativeWriteSuffix(buffer);
    encoder.expected_post = token;
    return encoder.NotePost(token, overwrite);
}

bool Scheduler::ReadPostNativeOperation(NativeWriteSuffix::PostToken token,
                                        NativeWriteSuffix::PostReceipt& receipt) {
    return NativeWriteSuffix::Recorder::Get().ReadPost(this, token, work_semaphore.KnownGpuTick(),
                                                       receipt);
}

bool Scheduler::ConfirmPostProxyLifetime(NativeWriteSuffix::PostToken merge,
                                         const NativeWriteSuffix::PostProxyLifetimeProof& proof) {
    return NativeWriteSuffix::Recorder::Get().ConfirmPostProxyLifetime(
        this, merge, work_semaphore.KnownGpuTick(), proof);
}

void Scheduler::DisarmPostNativeOrder(NativeWriteSuffix::CaptureId capture) {
    NativeWriteSuffix::Recorder::Get().Disarm(this, capture);
}
#endif

void Scheduler::BeginRendering(const RenderState& new_state) {
    // bbport (r21_draw-sort): ending and beginning render passes leaves every bind as it is.
    R21Neutral r21_neutral{*this};
    if (is_rendering && render_state == new_state) {
        return;
    }
    // bbport: a cut of the command stream (MaybeSplit) closed this render pass; it continues
    // in the next command buffer without clearing its attachments again.
    const bool resume = resume_rendering && !is_rendering && render_state == new_state;
    resume_rendering = false;
    EndRendering();
    is_rendering = true;
    render_state = new_state;
    ++passes_begun;
    r21_fresh_passes += resume ? 0u : 1u; // bbport (r21_draw-sort): R21FreshPasses()

    std::array<vk::RenderingAttachmentInfo, 8> color_attachments;
    for (u32 i = 0; i < render_state.num_color_attachments; ++i) {
        const auto& cb = render_state.color_attachments[i];
        color_attachments[i] = vk::RenderingAttachmentInfo{
            .imageView = cb.image_view,
            .imageLayout = cb.image_layout,
            .loadOp = cb.is_clear && !resume ? vk::AttachmentLoadOp::eClear
                                             : vk::AttachmentLoadOp::eLoad,
            .storeOp = vk::AttachmentStoreOp::eStore,
            .clearValue = vk::ClearValue{.color = vk::ClearColorValue{.uint32 = cb.clear_value}},
        };
    }

    const auto& db = render_state.depth_stencil_attachment;
    const vk::RenderingAttachmentInfo depth_attachment = {
        .imageView = db.image_view,
        .imageLayout = db.image_layout,
        .loadOp = db.depth_clear && !resume ? vk::AttachmentLoadOp::eClear
                                            : vk::AttachmentLoadOp::eLoad,
        .storeOp = vk::AttachmentStoreOp::eStore,
        .clearValue =
            vk::ClearValue{.depthStencil = vk::ClearDepthStencilValue{.depth = std::bit_cast<float>(
                                                                          db.clear_value[0])}},
    };
    const vk::RenderingAttachmentInfo stencil_attachment = {
        .imageView = db.image_view,
        .imageLayout = db.image_layout,
        .loadOp = db.stencil_clear && !resume ? vk::AttachmentLoadOp::eClear
                                              : vk::AttachmentLoadOp::eLoad,
        .storeOp = vk::AttachmentStoreOp::eStore,
        .clearValue = vk::ClearValue{.depthStencil =
                                         vk::ClearDepthStencilValue{.stencil = db.clear_value[1]}},
    };

    const vk::RenderingInfo rendering_info = {
        .renderArea =
            {
                .offset = {0, 0},
                .extent = {render_state.width, render_state.height},
            },
        .layerCount = render_state.num_layers,
        .colorAttachmentCount = render_state.num_color_attachments,
        .pColorAttachments = color_attachments.data(),
        .pDepthAttachment = db.has_depth ? &depth_attachment : nullptr,
        .pStencilAttachment = db.has_stencil ? &stencil_attachment : nullptr,
    };

    if (workers.empty()) {
        current_cmdbuf.beginRendering(rendering_info);
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        EncodeNativeWriteSuffix(current_cmdbuf).BeginRendering(rendering_info);
#endif
        return;
    }
    // The attachment infos live on this stack frame: the recorded closure keeps copies.
    auto begin = [info = rendering_info, color_attachments, depth_attachment,
                  stencil_attachment](vk::CommandBuffer cmdbuf
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
                                      , NativeWriteSuffix::Encoder& encoder
#endif
                                      ) mutable {
        info.pColorAttachments = color_attachments.data();
        if (info.pDepthAttachment) {
            info.pDepthAttachment = &depth_attachment;
        }
        if (info.pStencilAttachment) {
            info.pStencilAttachment = &stencil_attachment;
        }
        cmdbuf.beginRendering(info);
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        encoder.BeginRendering(info);
#endif
    };
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    RecordNativeWriteSuffix(std::move(begin));
#else
    Record(std::move(begin));
#endif
}

#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
void Scheduler::RecordRenderEnd() {
    RecordNativeWriteSuffix([](vk::CommandBuffer cmdbuf, NativeWriteSuffix::Encoder& encoder) {
        cmdbuf.endRendering();
        encoder.Note(NativeWriteSuffix::Kind::RenderEnd);
    });
}
#endif

void Scheduler::EndRendering() {
    if (!is_rendering) {
        return;
    }
    is_rendering = false;
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
    if (TryPostResidentEnd()) {
        return;
    }
#endif
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    RecordRenderEnd();
#else
    Record([](vk::CommandBuffer cmdbuf) { cmdbuf.endRendering(); });
#endif
}

#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
bool Scheduler::PrepareResidentDraw(PostResidentGeometry::Ticket& ticket) {
    const auto queue = instance.GetGraphicsQueue();
    const auto allocator = instance.GetAllocator();
    if (!batch->resident_tick || !ticket.Check(this, queue, allocator)) {
        return false;
    }
    ticket.scheduler = this;
    ticket.queue = queue;
    ticket.allocator = allocator;
    ticket.tick = batch->resident_tick;
    return true;
}

bool Scheduler::TryPostResidentEnd() {
    using namespace PostResidentGeometry;
    if (thread_sink || !record_chunk) {
        return false;
    }
    ProducerScope producer{*this, "TryPostResidentEnd"};
    auto& chunk = *record_chunk;
    auto ticket = chunk.TakeAdjacentResidentDraw();
    if (!ticket) {
        return false;
    }
    if (!IsRecordingDeferred() || fork_open || !batch || batch->resident_raw ||
        ticket->tick != batch->resident_tick || ticket->incarnation != chunk.ResidentIncarnation()) {
        ticket->Refuse(State::Unordered);
        return false;
    }
    if (batch->resident_count == batch->resident.size()) {
        ticket->Refuse(State::Capacity);
        return false;
    }
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    if (!chunk.Push<NativeWriteSuffix::Handling::Described>(
            [this, owner = &chunk, capture = ticket.get()](vk::CommandBuffer cmd,
                                                          NativeWriteSuffix::Encoder& encoder) {
            cmd.endRendering();
            encoder.Note(NativeWriteSuffix::Kind::RenderEnd);
            EncodePostResident(*owner, *capture, cmd);
        })) {
#else
    if (!chunk.Push([this, owner = &chunk, capture = ticket.get()](vk::CommandBuffer cmd) {
            cmd.endRendering();
            EncodePostResident(*owner, *capture, cmd);
        })) {
#endif
        ticket->Refuse(State::NoAdjacentEnd);
        return false;
    }
    ++r21_serial;
    batch->resident[batch->resident_count++] = std::move(ticket);
    return true;
}

void Scheduler::EncodePostResident(RecordChunk& chunk, PostResidentGeometry::Ticket& ticket,
                                   vk::CommandBuffer cmd) {
    using namespace PostResidentGeometry;
    if (ticket.Get() != State::Issued || !cmd || cmd != ticket.command || !chunk.batch ||
        chunk.batch->resident_tick != ticket.tick || chunk.ResidentIncarnation() != ticket.incarnation ||
        !ticket.Check(this, instance.GetGraphicsQueue(), instance.GetAllocator())) {
        ticket.Refuse(State::NoExactDraw);
        return;
    }
    const auto allocator = instance.GetAllocator();
    const auto stage = WorkflowProbe::AllocateTransfer(allocator, ticket.transfer_bytes);
    if (!stage) {
        ticket.Refuse(State::AllocationFailed);
        return;
    }
    VmaAllocationInfo destination{};
    vmaGetAllocationInfo(allocator, stage->allocation, &destination);
    const auto staging_begin = destination.offset;
    if (!destination.deviceMemory || destination.pMappedData != stage->mapped ||
        stage->bytes > destination.size ||
        !Ticket::Contains(0, std::numeric_limits<u64>::max(), staging_begin, destination.size)) {
        ticket.Refuse(State::AllocationFailed);
        return;
    }
    for (u32 i = 0; i < ticket.count; ++i) {
        const auto& r = ticket.regions[i];
        const auto& b = r.source.binding;
        VmaAllocationInfo backing{};
        vmaGetAllocationInfo(allocator, b.allocation, &backing);
        const u64 source_begin = b.memory_offset + r.begin;
        if (backing.pMappedData || backing.deviceMemory != static_cast<VkDeviceMemory>(b.memory) ||
            backing.offset != b.memory_offset || backing.size != b.allocation_bytes ||
            (backing.deviceMemory == destination.deviceMemory &&
             source_begin < staging_begin + destination.size &&
             staging_begin < source_begin + r.bytes)) {
            ticket.Refuse(State::InvalidProof);
            return;
        }
    }

    // Same write-to-copy, copy-to-host, and copy-before-later-write edges as WorkflowCopyIndex.
    const vk::MemoryBarrier2 before{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands | vk::PipelineStageFlagBits2::eHost,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite | vk::AccessFlagBits2::eHostWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eCopy,
        .dstAccessMask = vk::AccessFlagBits2::eTransferRead,
    };
    cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
    for (u32 i = 0; i < ticket.count; ++i) {
        const auto& r = ticket.regions[i];
        const vk::BufferCopy region{.srcOffset = r.begin, .dstOffset = r.destination, .size = r.bytes};
        cmd.copyBuffer(r.source.binding.buffer, vk::Buffer{stage->buffer}, region);
    }
    const std::array after{
        vk::MemoryBarrier2{.srcStageMask = vk::PipelineStageFlagBits2::eCopy,
                           .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                           .dstStageMask = vk::PipelineStageFlagBits2::eHost,
                           .dstAccessMask = vk::AccessFlagBits2::eHostRead},
        vk::MemoryBarrier2{.srcStageMask = vk::PipelineStageFlagBits2::eCopy,
                           .srcAccessMask = vk::AccessFlagBits2::eTransferRead,
                           .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                           .dstAccessMask = vk::AccessFlagBits2::eMemoryWrite},
    };
    cmd.pipelineBarrier2({.memoryBarrierCount = u32(after.size()), .pMemoryBarriers = after.data()});
    ticket.segment = chunk.segment;
    ticket.transfer = stage;
    ticket.Set(State::Encoded);
}

void Scheduler::SubmitPostResident(SubmissionBatch& submitted, vk::Result result, u64 signal,
                                   std::span<const vk::CommandBuffer> commands) {
    using namespace PostResidentGeometry;
    if (!submitted.resident_count) {
        return;
    }
    // The async recorder must never acquire the ordinary pending-ops mutex. Its callbacks
    // run under that mutex and can depend on recorder progress.
    std::unique_lock lk(resident_pending_ops_mutex);
    for (u32 i = 0; i < submitted.resident_count; ++i) {
        auto ticket = std::move(submitted.resident[i]);
        if (ticket->Get() != State::Encoded) {
            continue;
        }
        if (result != vk::Result::eSuccess) {
            ticket->transfer.reset();
            ticket->Refuse(State::UnjoinedSubmit);
            continue;
        }
        const bool joined = ticket->JoinSubmit(result, signal, commands, submitted.segments,
                                                submitted.resident_raw);
        if (joined) {
            ticket->Set(State::Submitted);
        } else {
            ticket->Set(State::UnjoinedSubmit);
        }
        // A successful queue submit may refer to this staging buffer even if the join fails.
        resident_pending_ops.emplace([this, ticket = std::move(ticket), joined] {
            auto stage = std::static_pointer_cast<WorkflowProbe::Transfer>(std::move(ticket->transfer));
            if (!joined) {
                ticket->Refuse(State::UnjoinedSubmit);
                return;
            }
            if (vmaInvalidateAllocation(stage->allocator, stage->allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
                ticket->Refuse(State::InvalidateFailed);
                return;
            }
            if (!ticket->Complete(work_semaphore.KnownGpuTick(), {
                    static_cast<const std::byte*>(stage->mapped), stage->bytes})) {
                ticket->Refuse(State::UnjoinedSubmit);
            }
        }, signal, "post_resident_geometry", false);
        num_pending_ops.fetch_add(1, std::memory_order_release);
    }
    submitted.resident_count = 0;
}
#endif

void Scheduler::TraceDirectRecording(void* caller) {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_RECORDER_TRACE");
        return env && env[0] == '1';
    }();
    if (!enabled) {
        return;
    }
    static std::mutex mutex;
    static std::unordered_map<void*, u64> callers;
    static u64 calls;
    std::scoped_lock lk{mutex};
    ++callers[caller];
    if (++calls % 2000) {
        return;
    }
    std::vector<std::pair<u64, void*>> top;
    for (const auto& [address, count] : callers) {
        top.emplace_back(count, address);
    }
    std::ranges::sort(top, std::greater{});
    for (size_t i = 0; i < std::min<size_t>(top.size(), 8); ++i) {
#ifdef _WIN32
        char where[512];
        BbPlatform::DescribeAddress(top[i].second, where, sizeof(where));
        std::printf("Recorder sync caller: %llu x %s\n",
                    static_cast<unsigned long long>(top[i].first), where);
        continue;
#else
        Dl_info info{};
        dladdr(top[i].second, &info);
        std::printf("Recorder sync caller: %llu x %s+0x%lx\n",
                    static_cast<unsigned long long>(top[i].first),
                    info.dli_fname ? info.dli_fname : "?",
                    static_cast<unsigned long>(reinterpret_cast<uintptr_t>(top[i].second) -
                                               reinterpret_cast<uintptr_t>(info.dli_fbase)));
#endif
    }
    callers.clear();
}

std::unique_ptr<RecordChunk> Scheduler::AcquireChunk() {
    std::scoped_lock lk{recorder_mutex};
    if (free_chunks.empty()) {
        return std::make_unique<RecordChunk>();
    }
    auto chunk = std::move(free_chunks.back());
    free_chunks.pop_back();
    return chunk;
}

namespace {
/// bbport BB_HOST_WAIT_SPIN_US (default 100; 0: the loops as before): the waits for host copies
/// and deferred signals spin with pause for this long before they yield (Sleep(0) on Windows: a
/// system call each, and the core may go to another thread for a while), and help the copy
/// threads one queued task at a time (BbCopy::HelpOne) instead of BbCopy::WaitAsync, which also
/// waits for copies issued after the signal.
u32 HostWaitSpinUs() {
    static const u32 us = [] {
        const char* env = std::getenv("BB_HOST_WAIT_SPIN_US");
        return env && env[0] ? static_cast<u32>(std::max(0, std::atoi(env))) : 100u;
    }();
    return us;
}

/// Waits until `done()`. `help`: runs queued copy tasks meanwhile (the signals wait for them).
template <typename Done>
void WaitUntil(Done&& done, bool help) {
    const u32 spin_us = HostWaitSpinUs();
    if (spin_us == 0) {
        while (!done()) {
            if (help) {
                BbCopy::WaitAsync();
            }
            std::this_thread::yield();
        }
        return;
    }
    const auto spin_until = std::chrono::steady_clock::now() + std::chrono::microseconds(spin_us);
    bool spinning = true;
    for (u32 spins = 1; !done(); ++spins) {
        if (help && (spins & 63) == 1 && BbCopy::HelpOne()) {
            continue;
        }
        if (!spinning) {
            std::this_thread::yield();
            continue;
        }
        __builtin_ia32_pause();
        // The clock is read every 256 pauses, not per iteration.
        if (!(spins & 255) && std::chrono::steady_clock::now() >= spin_until) {
            spinning = false;
        }
    }
}

/// bbport: a wait that blocked, timed into the "host copies" share of the frame statistics and per
/// call site (the "Stage B waits" line).
struct SiteWait {
    std::atomic<u64>& count;
    std::atomic<u64>& ns;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    ~SiteWait() {
        const u64 spent = static_cast<u64>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                               std::chrono::steady_clock::now() - start)
                                               .count());
        BbStats::host_copies_wait_ns.fetch_add(spent, std::memory_order_relaxed);
        count.fetch_add(1, std::memory_order_relaxed);
        ns.fetch_add(spent, std::memory_order_relaxed);
    }
};

u32 ClampSite(u32 site) {
    return std::min<u32>(site, BbStats::WaitOther);
}

bool FenceOrderEnv() {
    static const bool on = [] {
        // bbport: ordered unless BB_FENCE_ORDER=all (the opt-out after the beta A/B).
        const char* env = std::getenv("BB_FENCE_ORDER");
        const bool ordered = !(env && std::strcmp(env, "all") == 0);
        if (ordered) {
            std::printf("GPU: WriteData and DMA wait only for the fences the command processor "
                        "would have written before them (BB_FENCE_ORDER=all turns it off)\n");
        }
        return ordered;
    }();
    return on;
}
} // namespace

bool Scheduler::FenceOrderScoped() {
    return FenceOrderEnv() || BbToggle::Experiment(8);
}

bool Scheduler::FenceOrderPossible() {
    static const bool possible = FenceOrderEnv() || std::getenv("BB_TOGGLE_FILE") != nullptr;
    return possible;
}

void Scheduler::WaitDeferredSignals(u32 site) {
    WaitDeferredSignalsUpTo(deferred_signals_issued.load(std::memory_order_relaxed), site);
}

void Scheduler::WaitDeferredSignalsUpTo(u64 need, u32 site) {
    if (deferred_signals_done->load(std::memory_order_acquire) >= need ||
        BbToggle::Disabled(BbToggle::OrderedGuestWrites)) {
        return;
    }
    site = ClampSite(site);
    BbSections::Scope scope{BbSections::WaitSignals};
    SiteWait timer{BbStats::signal_waits[site], BbStats::signal_wait_ns[site]};
    KickRecording(true);
    // Helps the copy threads the signals wait for.
    WaitUntil([&] { return deferred_signals_done->load(std::memory_order_acquire) >= need; },
              true);
}

void Scheduler::WaitDeferredSignalsFor(u32 site, u64 address, u64 size, u64 src, u64 src_size) {
    if (!FenceOrderScoped()) {
        WaitDeferredSignals(site);
        return;
    }
    const u64 issued = deferred_signals_issued.load(std::memory_order_relaxed);
    const u64 done = deferred_signals_done->load(std::memory_order_acquire);
    if (done >= issued) {
        return;
    }
    // Signals complete in the order they were issued (BbCopy::AfterCopies keeps it): waiting for
    // the newest one needed covers the ones before it.
    u64 need = std::min(signal_barrier.load(std::memory_order_relaxed), issued);
    need = std::max(need, NewestLabelOverlap(done, address, size));
    if (src_size != 0) {
        need = std::max(need, NewestLabelOverlap(done, src, src_size));
    }
    if (need <= done) {
        BbStats::signal_waits_skipped[ClampSite(site)].fetch_add(1, std::memory_order_relaxed);
        return;
    }
    WaitDeferredSignalsUpTo(need, site);
}

void Scheduler::NoteDeferredLabel(u64 label, u32 label_size, u64 seq) {
    if (label_size == 0) {
        // Not a label write (GPU idle, an interrupt, a GDS store): nothing may overtake it.
        signal_barrier.store(seq, std::memory_order_relaxed);
        return;
    }
    auto& entry = deferred_labels[deferred_label_count++ % DeferredLabels];
    deferred_label_lost = std::max(deferred_label_lost, entry.seq);
    entry = {label, label_size, seq};
}

u64 Scheduler::NewestLabelOverlap(u64 done, u64 address, u64 size) const {
    if (size == 0) {
        return 0;
    }
    // An entry overwritten while its signal may still be pending counts as overlapping.
    u64 newest = deferred_label_lost > done ? deferred_label_lost : 0;
    const u64 count = std::min<u64>(deferred_label_count, DeferredLabels);
    for (u64 i = 0; i < count; ++i) {
        const auto& entry = deferred_labels[(deferred_label_count - 1 - i) % DeferredLabels];
        if (entry.seq <= done) {
            break; // this one and the older ones are written
        }
        if (entry.address < address + size && address < entry.address + entry.size) {
            newest = std::max(newest, entry.seq);
        }
    }
    return newest;
}

namespace {
constexpr u32 HostCopyGranuleShift = 16;
constexpr u64 HostCopyMaxGranules = 64; // larger notes and checks are treated as everywhere
u32 HostCopySlotOf(u64 granule, u32 slots) {
    return u32((granule * 0x9e3779b97f4a7c15ull) >> 40) % slots;
}
} // namespace

void Scheduler::NoteHostCopySource(u64 address, u64 size) {
    if (size == 0) {
        return;
    }
    const u64 first = address >> HostCopyGranuleShift;
    const u64 last = (address + size - 1) >> HostCopyGranuleShift;
    std::scoped_lock lk{host_copy_sources_mutex};
    const u64 seq = ++host_copy_source_seq;
    if (last - first >= HostCopyMaxGranules) {
        host_copy_big_seq = seq;
        return;
    }
    for (u64 g = first; g <= last; ++g) {
        auto& slot = host_copy_slots[HostCopySlotOf(g, HostCopySlots)];
        if (slot.seq > host_copy_sources_done && slot.granule != g) {
            slot.granule = HostCopyWildcard; // two pending granules share it
        } else if (slot.granule != HostCopyWildcard || slot.seq <= host_copy_sources_done) {
            slot.granule = g;
        }
        slot.seq = seq;
    }
}

void Scheduler::WaitHostCopiesFor(u64 address, u64 size, u32 site) {
    {
        std::scoped_lock lk{host_copy_sources_mutex};
        bool overlap = host_copy_big_seq > host_copy_sources_done;
        const u64 first = address >> HostCopyGranuleShift;
        const u64 last = (address + std::max<u64>(size, 1) - 1) >> HostCopyGranuleShift;
        if (last - first >= HostCopyMaxGranules) {
            overlap = true;
        }
        for (u64 g = first; !overlap && g <= last; ++g) {
            const auto& slot = host_copy_slots[HostCopySlotOf(g, HostCopySlots)];
            overlap = slot.seq > host_copy_sources_done &&
                      (slot.granule == g || slot.granule == HostCopyWildcard);
        }
        if (!overlap) {
            BbStats::host_copy_waits_skipped.fetch_add(1, std::memory_order_relaxed);
            return;
        }
    }
    WaitHostCopies(site);
}

void Scheduler::WaitHostCopies(u32 site) {
    u64 sources_seen;
    {
        std::scoped_lock lk{host_copy_sources_mutex};
        sources_seen = host_copy_source_seq;
    }
    // Copies noted after this point may still run when the waits below return.
    struct Forget {
        Scheduler& s;
        u64 seen;
        ~Forget() {
            std::scoped_lock lk{s.host_copy_sources_mutex};
            s.host_copy_sources_done = std::max(s.host_copy_sources_done, seen);
        }
    } forget{*this, sources_seen};
    BbSections::Scope scope{BbSections::WaitCopies};
    if (host_copies_done.load(std::memory_order_acquire) < host_copies_issued) {
        site = ClampSite(site);
        SiteWait timer{BbStats::copy_waits[site], BbStats::copy_wait_ns[site]};
        BbStats::host_copy_waits.fetch_add(1, std::memory_order_relaxed);
        KickRecording(true);
        const u64 issued = host_copies_issued;
        WaitUntil(
            [&] { return host_copies_done.load(std::memory_order_acquire) >= issued; }, false);
    }
    BbStats::WaitTimer timer{BbStats::copy_threads_wait_ns};
    BbCopy::WaitAsync();
}

void Scheduler::KickRecording(bool force) {
    ProducerScope producer{*this, "KickRecording"};
#ifdef BB_TEST_SHARED_POST_GRAPH
    ++post_borrow_epoch;
#endif
    if (workers.empty()) {
        return;
    }
    // Callers kick where nobody holds the raw command buffer: deferral resumes.
    if (direct_segment) {
        LeaveDirectSegment();
    }
    direct_mode = false;
    if (!force) {
        MaybeSplit();
    }
    // Batches of tens of KiB keep the queue handoff cheap relative to the work it carries.
    if (!force && full_chunks.empty() && CurrentChunk().Size() < 32 * 1024) {
        return;
    }
    HandOver();
}

void Scheduler::MaybeSplit() {
    if (fork_open || workers.size() < 2 || current_segment + 1 >= MaxSegments || !IsRecordingDeferred() ||
        BbToggle::Disabled(BbToggle::ParallelRecording)) {
        return;
    }
    // Cutting inside a render pass closes and reopens it: only after a longer stretch.
    const size_t bytes = segment_bytes + CurrentChunk().Size();
    if (bytes < (is_rendering ? 2 * split_bytes : split_bytes)) {
        return;
    }
    if (is_rendering) {
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        RecordRenderEnd();
#else
        Record([](vk::CommandBuffer cmdbuf) { cmdbuf.endRendering(); });
#endif
        is_rendering = false;
        resume_rendering = true;
    }
    if (async_submit) {
        // Its recording thread ends the segment's command buffer (the pool is that thread's).
        RecordImpl<NativeWriteSuffix::Handling::NoNativeWrites>(
            [](vk::CommandBuffer cmdbuf) { Check(cmdbuf.end()); });
    }
    HandOver();
    ++current_segment;
    batch->segments[current_segment] = vk::CommandBuffer{};
    segment_bytes = 0;
    active_worker.store(current_segment % workers.size(), std::memory_order_relaxed);
    static const bool peer_wake = [] {
        const char* env = std::getenv("LANTERN_PEER_WAKE");
        return !(env && env[0] == '0');
    }();
    if (peer_wake) {
        const u32 next_index = current_segment % workers.size();
        Worker& done = *workers[(current_segment - 1) % workers.size()];
        Worker& next = *workers[next_index];
        std::scoped_lock lk{recorder_mutex};
        if (next.sleeping && !next.peer_wakes && !done.queue.empty() && done.wake_next == NoPeer) {
            done.wake_next = next_index;
            next.peer_wakes = true;
        }
    }
    // The next command buffer starts without dynamic state: the next draw sets all of it.
    // Everything else (pipeline, vertex and index buffers, descriptors, push constants) every
    // draw and dispatch records itself (bbport r21_draw-sort: vertex input, vertex and index
    // buffer binds equal to those in force are left out while R21Epoch() is unchanged).
    dynamic_state.Invalidate();
    ++r21_epoch;
}

void Scheduler::HandOver() {
    // Entered from inside Record*() on this thread: a fault handler recording mid-command.
    if (const char* inside = producer_scope_where;
        inside && (std::strcmp(inside, "Record") == 0 || std::strcmp(inside, "RecordData") == 0 ||
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
                   std::strcmp(inside, "RecordPostResidentDraw") == 0 ||
                   std::strcmp(inside, "TryPostResidentEnd") == 0 ||
#endif
                   std::strcmp(inside, "RecordOrdered") == 0 ||
                   std::strcmp(inside, "RetireChunk") == 0)) {
        ReportProducer("REENTERED recording", BbPlatform::CurrentThreadId(), inside, "HandOver");
    }
    ProducerScope producer{*this, "HandOver"};
    if (!record_chunk || !ordered_chunk) {
        // Left behind by another HandOver interrupted between handing a chunk over and
        // taking a new one (see ProducerScope). Recover instead of dereferencing null.
        ReportProducer("HandOver without a current chunk", producer_tid.load(), "?", "HandOver");
        if (!record_chunk) {
            record_chunk = AcquireChunk();
        }
        if (!ordered_chunk) {
            ordered_chunk = AcquireChunk();
        }
    }
    const bool commands = !full_chunks.empty() || !record_chunk->Empty();
    const bool ordered = !ordered_full.empty() || !ordered_chunk->Empty();
    if (!commands && !ordered) {
        return;
    }
    // The chunks that take the current ones' places, taken first (AcquireChunk locks
    // recorder_mutex) and swapped in below: record_chunk and ordered_chunk are never null, not
    // even for a fault handler recording on this thread meanwhile (deadinside28 10baf9d, #100).
    std::unique_ptr<RecordChunk> next_record = record_chunk->Empty() ? nullptr : AcquireChunk();
    std::unique_ptr<RecordChunk> next_ordered = ordered_chunk->Empty() ? nullptr : AcquireChunk();
    Worker& worker = *workers[current_segment % workers.size()];
    bool wake = false;
    {
        std::scoped_lock lk{recorder_mutex};
        if (commands) {
            for (auto& chunk : full_chunks) {
                chunk->segment = current_segment;
                chunk->batch = batch;
                worker.queue.push_back(std::move(chunk));
                ++batch->handed[current_segment];
            }
            if (next_record) {
                record_chunk.swap(next_record); // next_record: the chunk handed over
                segment_bytes += next_record->Size();
                next_record->segment = current_segment;
                next_record->batch = batch;
                worker.queue.push_back(std::move(next_record));
                ++batch->handed[current_segment];
            }
            worker.queued.store(worker.queue.size(), std::memory_order_release);
            wake = worker.sleeping && !worker.peer_wakes;
        }
        if (ordered) {
            // They run after the commands handed over with them (recorded before or among them).
            const auto queue = [&](std::unique_ptr<RecordChunk> chunk) {
                chunk->segment = current_segment;
                chunk->batch = batch;
                chunk->after = batch->handed[current_segment];
                ordered_queue.push_back(std::move(chunk));
            };
            for (auto& chunk : ordered_full) {
                queue(std::move(chunk));
            }
            if (next_ordered) {
                ordered_chunk.swap(next_ordered); // next_ordered: the chunk handed over
                queue(std::move(next_ordered));
            }
            ordered_queued.store(ordered_queue.size(), std::memory_order_release);
            // Any thread may run them; the current segment's thread is woken for them (when it
            // sleeps): it spins for work anyway, and waking another thread per small copy cost
            // a few percent of the frame rate on 4 cores / 8 threads. A thread that is awake
            // picks them up by itself.
            if (!ordered_running) {
                wake |= worker.sleeping && !worker.peer_wakes;
            }
        }
    }
    full_chunks.clear();
    ordered_full.clear();
    // A busy thread picks the new chunks up by itself: waking it is a syscall per draw.
    if (wake) {
        producer_wakes.fetch_add(1, std::memory_order_relaxed);
        worker.cv.notify_one();
    }
    if (!record_chunk) {
        record_chunk = AcquireChunk();
    }
    if (!ordered_chunk) {
        ordered_chunk = AcquireChunk();
    }
}

bool Scheduler::RecordingIdle() const {
    if (!ordered_queue.empty() || ordered_running) {
        return false;
    }
    for (const auto& worker : workers) {
        if (!worker->queue.empty() || worker->busy) {
            return false;
        }
    }
    return true;
}

bool Scheduler::OrderedReady() const {
    if (ordered_queue.empty() || ordered_running) {
        return false;
    }
    const RecordChunk& next = *ordered_queue.front();
    for (u32 i = 0; i < next.segment; ++i) {
        if (next.batch->recorded[i] != next.batch->handed[i]) {
            return false;
        }
    }
    return next.batch->recorded[next.segment] >= next.after;
}

void Scheduler::SyncRecording() {
    if (workers.empty()) {
        return;
    }
    KickRecording(true);
    BbStats::WaitTimer timer{BbStats::sync_recording_ns};
    std::unique_lock lk{recorder_mutex};
    recorder_idle_cv.wait(lk, [this] { return RecordingIdle(); });
}

void Scheduler::EnterDirectMode() {
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
    if (batch) {
        batch->resident_raw = true;
    }
#endif
    // bbport: with submissions going out from the recording threads, the commands recorded
    // here get a segment of their own, from this thread's pool, after the segments handed over:
    // the recording threads go on with those instead of this thread waiting for them (~90 us,
    // the upscaler's passes every frame). BB_DIRECT_SEGMENT=0: the wait.
    static const bool own_segment = [] {
        const char* env = std::getenv("BB_DIRECT_SEGMENT");
        return !(env && env[0] == '0');
    }();
    if (own_segment && async_submit && current_segment + 2 < MaxSegments &&
        !BbToggle::Disabled(BbToggle::ThreadedRecording)) {
        if (is_rendering) {
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
            RecordRenderEnd();
#else
            Record([](vk::CommandBuffer cmdbuf) { cmdbuf.endRendering(); });
#endif
            is_rendering = false;
            resume_rendering = true;
        }
        // A segment nothing was handed to yet is not begun: it becomes the direct one.
        const bool untouched =
            batch->handed[current_segment] == 0 && full_chunks.empty() && CurrentChunk().Empty();
        if (!untouched) {
            // Its recording thread ends the segment's command buffer (the pool is that thread's).
            RecordImpl<NativeWriteSuffix::Handling::NoNativeWrites>(
                [](vk::CommandBuffer cmdbuf) { Check(cmdbuf.end()); });
            HandOver();
            ++current_segment;
        }
        if (!direct_pool) {
            direct_pool = std::make_unique<CommandPool>(instance, &work_semaphore);
        }
        current_cmdbuf = BeginCommandBuffer(*direct_pool);
        batch->segments[current_segment] = current_cmdbuf;
        segment_bytes = 0;
        direct_mode = true;
        direct_segment = true;
        dynamic_state.Invalidate();
        ++r21_epoch; // bbport (r21_draw-sort): another command buffer
        return;
    }
    SyncRecording();
    direct_mode = true;
    // The recording threads are idle: this thread may use the segment's command pool.
    auto& cmdbuf = batch->segments[current_segment];
    if (!cmdbuf) {
        cmdbuf = BeginCommandBuffer(*workers[current_segment % workers.size()]->pool);
    }
    current_cmdbuf = cmdbuf;
}

void Scheduler::LeaveDirectSegment() {
    if (is_rendering) {
        current_cmdbuf.endRendering();
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        EncodeNativeWriteSuffix(current_cmdbuf).Note(NativeWriteSuffix::Kind::RenderEnd);
#endif
        is_rendering = false;
        resume_rendering = true;
    }
    Check(current_cmdbuf.end());
    current_cmdbuf = vk::CommandBuffer{};
    direct_mode = false;
    direct_segment = false;
    ++current_segment;
    batch->segments[current_segment] = vk::CommandBuffer{};
    segment_bytes = 0;
    active_worker.store(current_segment % workers.size(), std::memory_order_relaxed);
    dynamic_state.Invalidate();
    ++r21_epoch; // bbport (r21_draw-sort): another command buffer
}

void Scheduler::RecorderThread(std::stop_token stoken, u32 index) {
    if (index == 0) {
        Common::SetCurrentThreadName("bb:VkRecorder");
    } else {
        char name[16];
        std::snprintf(name, sizeof(name), "bb:VkRecorder%u", index);
        Common::SetCurrentThreadName(name);
    }
    BbThreads::MakeCritical();
    Worker& worker = *workers[index];
    std::vector<std::unique_ptr<RecordChunk>> ordered;
    const auto has_work = [&] {
        return !worker.queue.empty() || OrderedReady();
    };
    while (true) {
        // The thread of the segment being recorded spins briefly before sleeping: its next
        // chunk usually follows within microseconds, and a sleeping thread costs the producer
        // a wake-up syscall per kick. With few hardware threads (Steam Deck: 8) the spin would
        // take time from guest threads. The others sleep until a new segment reaches them.
        if (active_worker.load(std::memory_order_relaxed) == index) {
            static const auto spin_time =
                std::chrono::microseconds(BbThreads::CapSpinUs(BbThreads::Available() >= 12 ? 200 : 20));
            const auto spin_until = std::chrono::steady_clock::now() + spin_time;
            for (u32 spins = 1; worker.queued.load(std::memory_order_acquire) == 0 &&
                                ordered_queued.load(std::memory_order_acquire) == 0;
                 ++spins) {
                __builtin_ia32_pause();
                // The clock is read every 256 pauses, not per iteration.
                if (!(spins & 255) &&
                    (stoken.stop_requested() || std::chrono::steady_clock::now() >= spin_until)) {
                    break;
                }
            }
        }
        std::unique_ptr<RecordChunk> chunk;
        u32 wake_peer = NoPeer;
        {
            std::unique_lock lk{recorder_mutex};
            if (!has_work()) {
                worker.sleeping = true;
                worker.cv.wait(lk, stoken, [&] { return has_work() || worker.peer_wakes; });
                worker.sleeping = false;
                worker.peer_wakes = false;
                if (!has_work()) {
                    if (stoken.stop_requested()) {
                        return;
                    }
                    continue;
                }
            }
            wake_peer = std::exchange(worker.wake_next, NoPeer);
            if (OrderedReady()) {
                // Every chunk whose commands are recorded, in order.
                do {
                    ordered.push_back(std::move(ordered_queue.front()));
                    ordered_queue.pop_front();
                } while (OrderedReady());
                ordered_running = true;
                ordered_queued.store(ordered_queue.size(), std::memory_order_release);
            } else {
                chunk = std::move(worker.queue.front());
                worker.queue.pop_front();
                worker.queued.store(worker.queue.size(), std::memory_order_release);
                worker.busy = true;
            }
        }
        if (wake_peer != NoPeer) {
            peer_wakes_done.fetch_add(1, std::memory_order_relaxed);
            workers[wake_peer]->cv.notify_one();
        }
        if (!ordered.empty()) {
            for (auto& task : ordered) {
                task->Execute({});
            }
            std::scoped_lock lk{recorder_mutex};
            for (auto& task : ordered) {
                free_chunks.push_back(std::move(task));
            }
            ordered.clear();
            ordered_running = false;
            recorder_idle_cv.notify_all();
            continue;
        }
        // The segment's command buffer is begun by the first chunk; it is ended at the
        // submission, after SyncRecording(). Only this thread uses the pool meanwhile.
        auto& cmdbuf = chunk->batch->segments[chunk->segment];
        if (!cmdbuf) {
            cmdbuf = BeginCommandBuffer(*worker.pool);
        }
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        const NativeWriteSuffix::WorkerSegment context{
            this, chunk->batch->native_suffix_tick, chunk->segment, cmdbuf};
        const auto* old_context = std::exchange(NativeWriteSuffix::worker_segment, &context);
#endif
        chunk->Execute(cmdbuf);
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
        NativeWriteSuffix::worker_segment = old_context;
#endif
        {
            std::scoped_lock lk{recorder_mutex};
            ++chunk->batch->recorded[chunk->segment];
            free_chunks.push_back(std::move(chunk));
            worker.busy = false;
            if (worker.queue.empty()) {
                recorder_idle_cv.notify_all();
            }
        }
    }
}

namespace {
// bbport r8 (BbSubmitDiag): Scheduler::Wait calls that blocked, by caller and thread.
struct DiagWaitSite {
    void* caller;
    u32 tid;
    std::string thread;
    u64 count;
    u64 ns;
};
std::mutex diag_wait_mutex;
std::vector<DiagWaitSite> diag_wait_sites;

u64 DiagNowNs() {
    return u64(std::chrono::duration_cast<std::chrono::nanoseconds>(
                   std::chrono::steady_clock::now().time_since_epoch())
                   .count());
}

void NoteBlockedWait(void* caller, u64 ns) {
    const u32 tid = BbPlatform::CurrentThreadId();
    std::scoped_lock lk{diag_wait_mutex};
    for (auto& site : diag_wait_sites) {
        if (site.caller == caller && site.tid == tid) {
            ++site.count;
            site.ns += ns;
            return;
        }
    }
    if (diag_wait_sites.size() < 64) {
        diag_wait_sites.push_back({caller, tid, Common::GetCurrentThreadName(), 1, ns});
    }
}
} // namespace

void Scheduler::NoteSubmitDiag(u64 tick, u32 reason, bool dry, bool waits, u64 flush_ns,
                               u64 since_ns) {
    reason = std::min<u32>(reason, BbSubmitDiag::Reasons - 1);
    BbSubmitDiag::submits[reason].fetch_add(1, std::memory_order_relaxed);
    if (dry) {
        BbSubmitDiag::dry_submits[reason].fetch_add(1, std::memory_order_relaxed);
    }
    if (waits) {
        BbSubmitDiag::waited_submits[reason].fetch_add(1, std::memory_order_relaxed);
    }
    BbSubmitDiag::since_ns[reason].fetch_add(since_ns, std::memory_order_relaxed);
    const u64 queued = DiagNowNs() - flush_ns;
    BbSubmitDiag::queue_ns[reason].fetch_add(queued, std::memory_order_relaxed);
    u64 longest = BbSubmitDiag::queue_max_ns[reason].load(std::memory_order_relaxed);
    while (queued > longest && !BbSubmitDiag::queue_max_ns[reason].compare_exchange_weak(
                                   longest, queued, std::memory_order_relaxed)) {
    }
    submit_diag_ring[tick % SubmitDiagRing].store(
        (tick << 8) | (u64(reason) << 1) | (dry ? 1u : 0u), std::memory_order_release);
}

void Scheduler::SubmitDiagFrame() {
    if (!BbSubmitDiag::On()) {
        return;
    }
    static u64 frames = 0; // the draw recording thread only
    // A block never mixes two experiment masks (A/B phases): the counts so far are dropped when
    // the mask changes.
    static u64 mask = 0;
    const u64 mask_now = __atomic_load_n(&runtime_experiment_bits, __ATOMIC_RELAXED);
    const bool switched = mask_now != mask;
    if (!switched && ++frames < 600) {
        return;
    }
    mask = mask_now;
    const double f = double(std::max<u64>(frames, 1));
    frames = 0;
    std::string out;
    char line[640];
    u64 all = 0, all_dry = 0;
    std::array<u64, BbSubmitDiag::Reasons> n{}, dry{}, waited{}, since{}, queued{}, longest{};
    for (u32 r = 0; r < BbSubmitDiag::Reasons; ++r) {
        n[r] = BbSubmitDiag::submits[r].exchange(0, std::memory_order_relaxed);
        dry[r] = BbSubmitDiag::dry_submits[r].exchange(0, std::memory_order_relaxed);
        waited[r] = BbSubmitDiag::waited_submits[r].exchange(0, std::memory_order_relaxed);
        since[r] = BbSubmitDiag::since_ns[r].exchange(0, std::memory_order_relaxed);
        queued[r] = BbSubmitDiag::queue_ns[r].exchange(0, std::memory_order_relaxed);
        longest[r] = BbSubmitDiag::queue_max_ns[r].exchange(0, std::memory_order_relaxed);
        all += n[r];
        all_dry += dry[r];
    }
    std::snprintf(line, sizeof(line),
                  "Submit diag: over %.0f frames (experiment mask %llu), %.2f submissions/frame "
                  "of the game's scheduler, %.2f/frame reached the queue after the GPU had "
                  "finished the one before (dry: the GPU may have waited for it)\n",
                  f, static_cast<unsigned long long>(mask), double(all) / f,
                  double(all_dry) / f);
    out += line;
    for (u32 r = 0; r < BbSubmitDiag::Reasons; ++r) {
        if (n[r] == 0) {
            continue;
        }
        const double count = double(n[r]);
        std::snprintf(line, sizeof(line),
                      "Submit diag: %6.2f/frame, dry %5.1f%%, %6.3f ms after the previous, "
                      "decision to queue %5.0f us (max %6.0f), %5.2f/frame with semaphore waits: "
                      "%s\n",
                      count / f, 100.0 * double(dry[r]) / count, double(since[r]) / count / 1e6,
                      double(queued[r]) / count / 1e3, double(longest[r]) / 1e3,
                      double(waited[r]) / f, BbSubmitDiag::ReasonNames[r]);
        out += line;
    }
    const double ends = double(BbSubmitDiag::ends.exchange(0, std::memory_order_relaxed));
    const double no_fences =
        double(BbSubmitDiag::ends_no_fences.exchange(0, std::memory_order_relaxed));
    const double held = double(BbSubmitDiag::ends_held.exchange(0, std::memory_order_relaxed));
    const double held_dry =
        double(BbSubmitDiag::ends_held_dry.exchange(0, std::memory_order_relaxed));
    const double busy = double(BbSubmitDiag::near_dry_busy.exchange(0, std::memory_order_relaxed));
    std::snprintf(line, sizeof(line),
                  "Submit diag: guest submission ends %.1f/frame: %.1f without fences pending, "
                  "%.1f held for the batch interval, %.2f of those although the GPU had finished "
                  "everything submitted (64 KiB backlog rule); held ends with the near-dry rule "
                  "off for want of stage B slack: %.1f/frame\n",
                  ends / f, no_fences / f, held / f, held_dry / f, busy / f);
    out += line;
    const double waits = double(BbSubmitDiag::guest_waits.exchange(0, std::memory_order_relaxed));
    const double wait_ns =
        double(BbSubmitDiag::guest_wait_ns.exchange(0, std::memory_order_relaxed));
    const double index =
        double(BbSubmitDiag::guest_wait_index.exchange(0, std::memory_order_relaxed));
    const double guest_submits =
        double(BbSubmitDiag::guest_submits.exchange(0, std::memory_order_relaxed));
    const double guest_frames =
        double(BbSubmitDiag::guest_frames.exchange(0, std::memory_order_relaxed));
    std::snprintf(line, sizeof(line),
                  "Submit diag: game thread blocked on the GPU (sceGnm waits for the previous "
                  "frame) %.2f/frame, %.3f ms/frame, after guest submission %.1f of %.1f a frame "
                  "(BB_SUBMIT_AHEAD)\n",
                  waits / f, wait_ns / 1e6 / f, waits > 0 ? index / waits : 0.0,
                  guest_frames > 0 ? guest_submits / guest_frames : 0.0);
    out += line;
    std::vector<DiagWaitSite> sites;
    {
        std::scoped_lock lk{diag_wait_mutex};
        sites.swap(diag_wait_sites);
    }
    std::ranges::sort(sites, [](const auto& a, const auto& b) { return a.ns > b.ns; });
    if (sites.empty()) {
        out += "Submit diag: GPU waits (Scheduler::Wait that blocked, any thread): none\n";
    }
    for (size_t i = 0; i < std::min<size_t>(sites.size(), 12); ++i) {
        char where[400];
#ifdef _WIN32
        BbPlatform::DescribeAddress(sites[i].caller, where, sizeof(where));
#else
        std::snprintf(where, sizeof(where), "%p", sites[i].caller);
#endif
        std::snprintf(line, sizeof(line),
                      "Submit diag: GPU wait %6.2f/frame %7.3f ms/frame on %s (thread %u) from "
                      "%s\n",
                      double(sites[i].count) / f, double(sites[i].ns) / 1e6 / f,
                      sites[i].thread.c_str(), sites[i].tid, where);
        out += line;
    }
    if (!switched) {
        std::fputs(out.c_str(), stdout);
    }
}

void Scheduler::Flush(SubmitInfo& info) {
    // When flushing, we only send data to the driver; no waiting is necessary.
    SubmitExecution(info);
}

void Scheduler::Flush() {
    SubmitInfo info{};
    Flush(info);
}

void Scheduler::Finish() {
    // When finishing, we need to wait for the submission to have executed on the device.
    // bbport r8: its submission and its wait are counted under Finish and Finish's caller.
    const BbSubmitDiag::Scope diag_reason{BbSubmitDiag::ReasonFinish};
    void* const diag_caller =
        std::exchange(BbSubmitDiag::wait_caller, __builtin_return_address(0));
    const u64 presubmit_tick = CurrentTick();
    SubmitInfo info{};
    SubmitExecution(info);
    Wait(presubmit_tick);
    BbSubmitDiag::wait_caller = diag_caller;
}

void Scheduler::Wait(u64 tick) {
    void* const diag_caller =
        BbSubmitDiag::wait_caller ? BbSubmitDiag::wait_caller : __builtin_return_address(0);
    if (tick >= work_semaphore.CurrentTick()) {
        // Make sure we are not waiting for the current tick without signalling
        const BbSubmitDiag::Scope diag_reason{BbSubmitDiag::ReasonTickWait};
        SubmitInfo info{};
        Flush(info);
    }
    BbWaitTrace::Scope trace;
    BbStats::WaitTimer timer{BbStats::tick_wait_ns};
    // bbport r8: a wait that blocks, by caller and thread ("Submit diag: GPU wait").
    if (BbSubmitDiag::On() && !IsFree(tick)) {
        const u64 start = DiagNowNs();
        work_semaphore.Wait(tick);
        NoteBlockedWait(diag_caller, DiagNowNs() - start);
        return;
    }
    work_semaphore.Wait(tick);
}

namespace {
// bbport (r35_pending-ops): one PopPendingOperations call. With BB_SPIKE_TRACE=1 every operation
// is timed and added to its kind (BbSpike::pending_kinds); the call (its ns from its first
// operation, so the calls that find none read no clock) is published when it is the longest since
// the reader took it. Without the trace only the carryable frees are timed, with the budget on.
constexpr const char* R35Untagged = "untagged (DeferOperation without a kind)";
struct R35Call {
    explicit R35Call(bool trace_) : trace{trace_} {}
    void Start(u64 now) {
        if (trace && start == 0) {
            start = now;
        }
    }
    /// Runs one operation and destroys it (its captures, as the pop did before): its ns when
    /// timed (`clock`, or the trace), else 0.
    u64 Run(Common::UniqueFunction<void>& callback, const char* kind, bool clock) {
        const bool timed = clock || trace;
        const u64 t0 = timed ? BbSpike::NowNs() : 0;
        Start(t0);
        callback();
        callback = Common::UniqueFunction<void>{};
        ++ops;
        if (!timed) {
            return 0;
        }
        const u64 ns = BbSpike::NowNs() - t0;
        if (trace) {
            Note(kind ? kind : R35Untagged, ns);
        }
        return ns;
    }
    void Note(const char* kind, u64 ns) {
        auto& slot = BbSpike::pending_kinds[BbSpike::PendingKindSlot(kind)];
        slot.count.fetch_add(1, std::memory_order_relaxed);
        slot.ns.fetch_add(ns, std::memory_order_relaxed);
        u32 i = 0;
        while (i + 1 < kinds.size() && kinds[i] != nullptr && kinds[i] != kind) {
            ++i;
        }
        if (kinds[i] == nullptr) {
            kinds[i] = kind;
        }
        kind_ns[i] += ns;
        ++kind_ops[i];
        if (ns > longest_ns) {
            longest_ns = ns;
            longest_kind = kind;
        }
    }
    static void StoreMax(std::atomic<u64>& to, u64 value) {
        for (u64 seen = to.load(std::memory_order_relaxed);
             value > seen &&
             !to.compare_exchange_weak(seen, value, std::memory_order_relaxed);) {
        }
    }
    /// `carries`: this Scheduler had or has carried frees (the presenter's, which never carries,
    /// leaves the waiting count to the main one).
    void Publish(u64 waiting, bool carries) {
        if (!trace || (ops == 0 && carried == 0)) {
            return;
        }
        constexpr auto relaxed = std::memory_order_relaxed;
        BbSpike::pending_carried.fetch_add(carried, relaxed);
        if (carries) {
            BbSpike::pending_backlog.store(waiting, relaxed);
        }
        StoreMax(BbSpike::pending_backlog_max, waiting);
        StoreMax(BbSpike::pending_wait_max, waited);
        const u64 ns = BbSpike::NowNs() - start;
        if (ns <= BbSpike::pending_call_ns.load(relaxed)) {
            return;
        }
        u32 top = 0;
        for (u32 i = 1; i < kinds.size(); ++i) {
            top = kind_ns[i] > kind_ns[top] ? i : top;
        }
        BbSpike::pending_call_ops.store(ops, relaxed);
        BbSpike::pending_call_carried.store(carried, relaxed);
        BbSpike::pending_call_kind.store(kinds[top], relaxed);
        BbSpike::pending_call_kind_ops.store(kind_ops[top], relaxed);
        BbSpike::pending_call_kind_ns.store(kind_ns[top], relaxed);
        BbSpike::pending_call_op_kind.store(longest_kind, relaxed);
        BbSpike::pending_call_op_ns.store(longest_ns, relaxed);
        BbSpike::pending_call_ns.store(ns, std::memory_order_release);
    }
    bool trace;
    u64 start = 0;
    u32 ops = 0, carried = 0;
    u64 waited = 0, longest_ns = 0; ///< waited: frames, the longest a carried free ran after
    const char* longest_kind = nullptr;
    std::array<const char*, 8> kinds{}; ///< this call's kinds (a ninth shares the last slot)
    std::array<u64, 8> kind_ns{};
    std::array<u32, 8> kind_ops{};
};
} // namespace

void Scheduler::PopPendingOperations() {
    // bbport (r35_pending-ops): frees carried from an earlier window also bring a call here,
    // except while the window that spent its budget lasts (and experiment 576460752303423488 is
    // clear: set, the next call runs them).
    if (num_pending_ops.load(std::memory_order_acquire) == 0 &&
        (r35_num_carried.load(std::memory_order_acquire) == 0 ||
         (r35_closed_frame.load(std::memory_order_relaxed) ==
              BbStats::gpu_frames.load(std::memory_order_relaxed) &&
          CurrentTick() <
              r35_closed_tick.load(std::memory_order_relaxed) + BbPendingOps::WindowTicks &&
          !BbToggle::Experiment(BbPendingOps::OldBit)))) {
        return; // every draw comes here
    }
    std::unique_lock lk(pending_ops_mutex);
    // bbport: this runs on every draw and dispatch. Querying the timeline semaphore is an
    // ioctl, so it is skipped when nothing waits and done once per 32 calls (~0.3 ms; reading
    // the clock per draw instead was itself a hot spot).
    bool poll = !pending_ops.empty();
    if (poll && !work_semaphore.IsFree(pending_ops.front().gpu_tick)) {
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
        poll = false;
    }
    const auto resident_tick = [this] {
        std::scoped_lock resident_lock(resident_pending_ops_mutex);
        return resident_pending_ops.empty() ? 0 : resident_pending_ops.front().gpu_tick;
    }();
    bool resident_ready = resident_tick && work_semaphore.IsFree(resident_tick);
    if (!poll && !resident_ready && (!pending_ops.empty() || resident_tick)) {
#endif
        if ((++pending_polls & 31) != 0 && !BbToggle::Disabled(BbToggle::PendingPollLimit)) {
            poll = false;
        } else {
            work_semaphore.Refresh();
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
            poll = !pending_ops.empty() && work_semaphore.IsFree(pending_ops.front().gpu_tick);
            resident_ready = resident_tick && work_semaphore.IsFree(resident_tick);
#else
            poll = work_semaphore.IsFree(pending_ops.front().gpu_tick);
#endif
        }
    }
    // bbport (r35_pending-ops): nothing the GPU is past and nothing carried: return here, as the
    // old code did (the per-draw cost stays as before).
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
    if (resident_ready) {
        std::unique_lock resident_lock(resident_pending_ops_mutex);
        while (!resident_pending_ops.empty() &&
               work_semaphore.IsFree(resident_pending_ops.front().gpu_tick)) {
            auto op = std::move(resident_pending_ops.front());
            resident_pending_ops.pop();
            num_pending_ops.fetch_sub(1, std::memory_order_release);
            resident_lock.unlock();
            op.callback();
            resident_lock.lock();
        }
    }
#endif
    if (!poll && r35_carried.empty()) {
        return;
    }
    // bbport (r35_pending-ops): experiment 576460752303423488 set = every operation the GPU is
    // past runs here, as before; clear = carryable frees for BbPendingOps::BudgetNs a window.
    const bool budget = !BbToggle::Experiment(BbPendingOps::OldBit);
    const u64 frame = BbStats::gpu_frames.load(std::memory_order_relaxed);
    r35_budget.Begin(frame, CurrentTick());
    if (!poll && budget && !r35_budget.MayRunCarried(r35_carried.front().frame)) {
        return; // only carried frees, and this window's budget is spent
    }
    R35Call call{BbSpike::on};
    const bool had_carried = !r35_carried.empty();
    // The frees carried from earlier windows first (the GPU is past them), oldest first.
    while (!r35_carried.empty() &&
           (!budget || r35_budget.MayRunCarried(r35_carried.front().frame))) {
        R35Carried op = std::move(r35_carried.front());
        r35_carried.pop_front();
        r35_num_carried.fetch_sub(1, std::memory_order_release);
        call.waited = std::max(call.waited, frame - op.frame);
        r35_budget.Spend(call.Run(op.callback, op.kind, budget));
    }
    while (poll && !pending_ops.empty() && work_semaphore.IsFree(pending_ops.front().gpu_tick)) {
        PendingOp& op = pending_ops.front();
        if (op.carry && budget && r35_budget.Spent()) {
            // bbport (r35_pending-ops): a free past this window's budget: to a later one.
            if (call.trace) {
                call.Start(BbSpike::NowNs());
            }
            r35_carried.push_back({std::move(op.callback), op.kind, frame});
            r35_num_carried.fetch_add(1, std::memory_order_release);
            ++call.carried;
        } else {
            const u64 ns = call.Run(op.callback, op.kind, op.carry && budget);
            if (op.carry) {
                r35_budget.Spend(ns);
            }
        }
        pending_ops.pop();
        num_pending_ops.fetch_sub(1, std::memory_order_release);
    }
    if (!r35_carried.empty()) {
        // Frees left only when the budget is spent: calls return at once until the window ends.
        r35_closed_tick.store(r35_budget.tick, std::memory_order_relaxed);
        r35_closed_frame.store(frame, std::memory_order_relaxed);
    }
    call.Publish(r35_carried.size(), had_carried || !r35_carried.empty());
}

SubmissionBatch* Scheduler::AcquireBatch() {
    std::scoped_lock lk{recorder_mutex};
    SubmissionBatch* next;
    if (free_batches.empty()) {
        next = all_batches.emplace_back(std::make_unique<SubmissionBatch>()).get();
    } else {
        next = free_batches.back();
        free_batches.pop_back();
    }
    next->Reset();
    return next;
}

void Scheduler::AllocateWorkerCommandBuffers() {
    if (async_submit) {
        // BB_ASYNC_SUBMIT: the earlier submissions may still be recorded (and their pools
        // used) on the recording threads: segment 0 is begun there too, on its first chunk,
        // or by EnterDirectMode once they are idle.
        batch = AcquireBatch();
        current_cmdbuf = vk::CommandBuffer{};
        direct_mode = false;
    } else {
        const vk::CommandBufferBeginInfo begin_info = {
            .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit,
        };
        current_cmdbuf = command_pool.Commit();
        Check(current_cmdbuf.begin(begin_info));
        // bbport: the first segment (worker 0, whose pool this is) of the next submission.
        if (!batch) {
            batch = AcquireBatch();
        }
        batch->Reset();
        batch->segments[0] = current_cmdbuf;
    }
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
    batch->resident_tick = work_semaphore.CurrentTick();
#endif
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    batch->native_suffix_tick = work_semaphore.CurrentTick();
#endif
    current_segment = 0;
    segment_bytes = 0;
    active_worker.store(0, std::memory_order_relaxed);

    // Invalidate dynamic state so it gets applied to the new command buffer.
    dynamic_state.Invalidate();
    ++r21_epoch; // bbport (r21_draw-sort): another command buffer

#if TRACY_GPU_ENABLED
    auto* profiler_ctx = instance.GetProfilerContext();
    if (profiler_ctx) {
        static const auto scope_loc =
            GPU_SCOPE_LOCATION("Guest Frame", MarkersPalette::GpuMarkerColor);
        new (profiler_scope) tracy::VkCtxScope{profiler_ctx, &scope_loc, current_cmdbuf, true};
    }
#endif
}

void Scheduler::SubmitExecution(SubmitInfo& info) {
    // bbport (r27_flush-split): this and SubmitAsync's own time, and its steps below (stage B's
    // tasks only, BB_SPIKE_TRACE=1)
    const BbSpike::SplitScope r27_split{BbSpike::SplitSubmit};
    ProducerScope producer{*this, "SubmitExecution"};
    if (async_submit) {
        SubmitAsync(info);
        return;
    }
    std::scoped_lock lk{submit_mutex};
    const u64 signal_value = work_semaphore.NextTick();

#if TRACY_GPU_ENABLED
    auto* profiler_ctx = instance.GetProfilerContext();
    if (profiler_ctx) {
        profiler_scope->~VkCtxScope();
        TracyVkCollect(profiler_ctx, batch->segments[0]);
    }
#endif

    if (on_submit) {
        on_submit(info);
    }

    EndRendering();
    if (auto* profiler = GpuProfiler::Get(); profiler && profiler->Records(this)) {
        // Until the next submission's first timestamp: mostly the GPU waiting for it (r8: a row
        // per reason of the next submission).
        profiler->MarkGap(signal_value + 1);
    }
    // bbport r8: why this submission goes out, and when (BbSubmitDiag; the game's scheduler).
    const bool diag = BbSubmitDiag::On() && !workers.empty();
    const u32 diag_reason = BbSubmitDiag::reason;
    const bool diag_waits = info.num_wait_semas != 0;
    const u64 diag_flush_ns = diag ? DiagNowNs() : 0;
    const u64 diag_since_ns =
        diag && submit_diag_last_ns ? diag_flush_ns - submit_diag_last_ns : 0;
    if (diag) {
        submit_diag_last_ns = diag_flush_ns;
    }
    SyncRecording();
    // Guest memory copies into staging read by this submission (copy threads).
    WaitHostCopies();
    resume_rendering = false;
    // bbport: the segments' command buffers in stream order (the recording threads are idle).
    std::array<vk::CommandBuffer, MaxSegments> cmdbufs;
    u32 num_cmdbufs = 0;
    if (workers.empty()) {
        cmdbufs[num_cmdbufs++] = current_cmdbuf;
    } else {
        for (u32 i = 0; i <= current_segment; ++i) {
            if (batch->segments[i]) {
                cmdbufs[num_cmdbufs++] = batch->segments[i];
            }
        }
        recorded_segments.fetch_add(num_cmdbufs, std::memory_order_relaxed);
        recorded_submissions.fetch_add(1, std::memory_order_relaxed);
    }
    for (u32 i = 0; i < num_cmdbufs; ++i) {
        Check(cmdbufs[i].end());
    }

    const vk::Semaphore timeline = work_semaphore.Handle();
    info.AddSignal(timeline, signal_value);

    static constexpr std::array<vk::PipelineStageFlags, 2> wait_stage_masks = {
        vk::PipelineStageFlagBits::eAllCommands,
        vk::PipelineStageFlagBits::eColorAttachmentOutput,
    };

    const vk::TimelineSemaphoreSubmitInfo timeline_si = {
        .waitSemaphoreValueCount = info.num_wait_semas,
        .pWaitSemaphoreValues = info.wait_ticks.data(),
        .signalSemaphoreValueCount = info.num_signal_semas,
        .pSignalSemaphoreValues = info.signal_ticks.data(),
    };

    const vk::SubmitInfo submit_info = {
        .pNext = &timeline_si,
        .waitSemaphoreCount = info.num_wait_semas,
        .pWaitSemaphores = info.wait_semas.data(),
        .pWaitDstStageMask = wait_stage_masks.data(),
        .commandBufferCount = num_cmdbufs,
        .pCommandBuffers = cmdbufs.data(),
        .signalSemaphoreCount = info.num_signal_semas,
        .pSignalSemaphores = info.signal_semas.data(),
    };

#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    if (!info.before_submit.empty()) {
        NativeWriteSuffix::Recorder::Get().Unordered(this, NativeWriteSuffix::Gap::SubmitCallback);
    }
#endif
    for (auto& operation : info.before_submit) {
        operation();
    }
    ImGui::Core::TextureManager::Submit();
    bool diag_dry = false; // bbport r8: the GPU had finished the submission before this one
    if (diag) {
        work_semaphore.Refresh();
        diag_dry = work_semaphore.IsFree(signal_value - 1);
    }
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
    const auto queue = instance.GetGraphicsQueue();
    const auto fence = info.fence;
    auto submit_result = queue.submit(submit_info, fence);
    NoteNativeSubmit(this, queue, instance.GetGraphicsQueueFamilyIndex(), timeline, signal_value,
                     batch->segments, info, wait_stage_masks.size(), submit_info, timeline_si,
                     fence, submit_result);
#else
    auto submit_result = instance.GetGraphicsQueue().submit(submit_info, info.fence);
#endif
    if (submit_result == vk::Result::eErrorDeviceLost) {
        Breadcrumbs::ReportDeviceLost("submit");
    }
    ASSERT_MSG(submit_result != vk::Result::eErrorDeviceLost, "Device lost during submit");
    submitted_tick.store(signal_value, std::memory_order_release);
    submitted_tick.notify_all();
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
    SubmitPostResident(*batch, submit_result, signal_value, {cmdbufs.data(), num_cmdbufs});
#endif
    if (diag) {
        NoteSubmitDiag(signal_value, diag_reason, diag_dry, diag_waits, diag_flush_ns,
                       diag_since_ns);
    }

    // bbport: no semaphore query here (an ioctl per submission, ~3% of the recording thread):
    // PopPendingOperations asks when an operation waits, the GPU signal thread on every fence.
    AllocateWorkerCommandBuffers();
    if (auto* profiler = GpuProfiler::Get(); profiler && profiler->Records(this)) {
        profiler->MarkSubmissionStart(); // r8: the gap ends here, not at the first pass
    }

    // Apply pending operations
    PopPendingOperations();
}

void Scheduler::SubmitAsync(SubmitInfo& info) {
    const u64 signal_value = work_semaphore.NextTick();
    if (on_submit) {
        on_submit(info);
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitEndRendering}; // r27_flush-split
        EndRendering();
    }
    if (auto* profiler = GpuProfiler::Get(); profiler && profiler->Records(this)) {
        profiler->MarkGap(signal_value + 1); // r8: a row per reason of the next submission
    }
    // bbport r8: why this submission goes out, and when (BbSubmitDiag).
    const bool diag = BbSubmitDiag::On();
    const u32 diag_reason = BbSubmitDiag::reason;
    const bool diag_waits = info.num_wait_semas != 0;
    const u64 diag_flush_ns = diag ? DiagNowNs() : 0;
    const u64 diag_since_ns =
        diag && submit_diag_last_ns ? diag_flush_ns - submit_diag_last_ns : 0;
    if (diag) {
        submit_diag_last_ns = diag_flush_ns;
    }
    resume_rendering = false;
    // Every segment's command buffer is ended by its recording thread (the pool is its own);
    // MaybeSplit ended the earlier ones. A direct segment is this thread's.
    if (direct_segment) {
        Check(current_cmdbuf.end());
        current_cmdbuf = vk::CommandBuffer{};
        direct_mode = false;
        direct_segment = false;
    } else {
        RecordImpl<NativeWriteSuffix::Handling::NoNativeWrites>(
            [](vk::CommandBuffer cmdbuf) { Check(cmdbuf.end()); });
    }
    // Guest memory copies into staging this submission reads: on the copy threads by then.
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitCopyBatch}; // r27_flush-split
        BbCopy::FlushBatch();
    }
    info.AddSignal(work_semaphore.Handle(), signal_value);
    // Goes out once the commands handed over before it are recorded (an ordered task: in order
    // with the other submissions and after the copies and signals queued before it).
    // bbport (r27_flush-split): pushing the submit closure (when it runs inline on this thread,
    // its copy wait and queue submit are timed inside)
    BbSpike::SplitScope r27_ordered{BbSpike::SplitRecordOrdered};
    RecordOrderedImpl([this, submitted = batch, info = std::move(info), signal_value, diag,
                   diag_reason, diag_waits, diag_flush_ns, diag_since_ns]() mutable {
        {
            const BbSpike::SplitScope r27_step{BbSpike::SplitCopyWait}; // r27_flush-split
            BbCopy::WaitAsync();
        }
        std::array<vk::CommandBuffer, MaxSegments> cmdbufs;
        u32 num_cmdbufs = 0;
        for (u32 i = 0; i < MaxSegments; ++i) {
            if (submitted->segments[i]) {
                cmdbufs[num_cmdbufs++] = submitted->segments[i];
            }
        }
        recorded_segments.fetch_add(num_cmdbufs, std::memory_order_relaxed);
        recorded_submissions.fetch_add(1, std::memory_order_relaxed);
        static constexpr std::array<vk::PipelineStageFlags, 4> wait_stage_masks = {
            vk::PipelineStageFlagBits::eAllCommands,
            vk::PipelineStageFlagBits::eColorAttachmentOutput,
            vk::PipelineStageFlagBits::eAllCommands,
            vk::PipelineStageFlagBits::eAllCommands,
        };
        const vk::TimelineSemaphoreSubmitInfo timeline_si = {
            .waitSemaphoreValueCount = info.num_wait_semas,
            .pWaitSemaphoreValues = info.wait_ticks.data(),
            .signalSemaphoreValueCount = info.num_signal_semas,
            .pSignalSemaphoreValues = info.signal_ticks.data(),
        };
        const vk::SubmitInfo submit_info = {
            .pNext = &timeline_si,
            .waitSemaphoreCount = info.num_wait_semas,
            .pWaitSemaphores = info.wait_semas.data(),
            .pWaitDstStageMask = wait_stage_masks.data(),
            .commandBufferCount = num_cmdbufs,
            .pCommandBuffers = cmdbufs.data(),
            .signalSemaphoreCount = info.num_signal_semas,
            .pSignalSemaphores = info.signal_semas.data(),
        };
        bool diag_dry = false; // bbport r8: the GPU had finished the submission before this one
        if (diag) {
            work_semaphore.Refresh();
            diag_dry = work_semaphore.IsFree(signal_value - 1);
        }
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
        vk::Result resident_result{};
#endif
        {
            const BbSpike::SplitScope r27_step{BbSpike::SplitQueueSubmit}; // r27_flush-split
            std::scoped_lock lk{submit_mutex};
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
            if (!info.before_submit.empty()) {
                NativeWriteSuffix::Recorder::Get().Unordered(this,
                                                            NativeWriteSuffix::Gap::SubmitCallback);
            }
#endif
            for (auto& operation : info.before_submit) {
                operation();
            }
#ifdef BB_HAS_NATIVE_SCHEDULER_RECORDER
            const auto queue = instance.GetGraphicsQueue();
            const auto fence = info.fence;
            const auto result = queue.submit(submit_info, fence);
            NoteNativeSubmit(this, queue, instance.GetGraphicsQueueFamilyIndex(),
                             work_semaphore.Handle(), signal_value,
                             submitted->segments, info, wait_stage_masks.size(), submit_info,
                             timeline_si, fence, result);
#else
            const auto result = instance.GetGraphicsQueue().submit(submit_info, info.fence);
#endif
            if (result == vk::Result::eErrorDeviceLost) {
                Breadcrumbs::ReportDeviceLost("submit");
            }
            ASSERT_MSG(result != vk::Result::eErrorDeviceLost, "Device lost during submit");
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
            resident_result = result;
#endif
        }
        submitted_tick.store(signal_value, std::memory_order_release);
        submitted_tick.notify_all();
#if defined(BB_TEST_POST_RESIDENT_GEOMETRY)
        SubmitPostResident(*submitted, resident_result, signal_value, {cmdbufs.data(), num_cmdbufs});
#endif
        if (diag) {
            NoteSubmitDiag(signal_value, diag_reason, diag_dry, diag_waits, diag_flush_ns,
                           diag_since_ns);
        }
        std::scoped_lock lk{recorder_mutex};
        free_batches.push_back(submitted);
    });
    r27_ordered.Stop(); // bbport (r27_flush-split): the steps below each timed
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitKick};
        KickRecording(true);
    }
    {
        const BbSpike::SplitScope r27_step{BbSpike::SplitAllocate};
        AllocateWorkerCommandBuffers();
    }
    if (auto* profiler = GpuProfiler::Get(); profiler && profiler->Records(this)) {
        profiler->MarkSubmissionStart(); // r8: the gap ends here, not at the first pass
    }
    const BbSpike::SplitScope r27_step{BbSpike::SplitPendingOps};
    PopPendingOperations();
}

void Scheduler::PriorityPendingOpsThread(std::stop_token stoken) {
    Common::SetCurrentThreadName("shadPS4:GpuSchedPriorityPendingOpsRunner");

    while (!stoken.stop_requested()) {
        PendingOp op;
        {
            std::unique_lock lk(priority_pending_ops_mutex);
            priority_pending_ops_cv.wait(lk, stoken,
                                         [this] { return !priority_pending_ops.empty(); });
            if (stoken.stop_requested()) {
                break;
            }

            op = std::move(priority_pending_ops.front());
            priority_pending_ops.pop();
        }

        work_semaphore.Wait(op.gpu_tick);
        if (stoken.stop_requested()) {
            break;
        }

        op.callback();
    }
}

void DynamicState::Commit(const Instance& instance, const vk::CommandBuffer& cmdbuf) {
    // A null command buffer only updates the dirty flags, exactly as recording would.
    CommitWith(instance.IsDepthBoundsSupported(), instance.IsDynamicColorWriteMaskSupported(),
               instance.IsAttachmentFeedbackLoopLayoutSupported(), [&](auto&& command) {
                   if (cmdbuf) {
                       command(cmdbuf);
                   }
               });
}

} // namespace Vulkan
