// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

namespace Vulkan::NativeWriteSuffix {
enum class Handling { Unknown, Described, NoNativeWrites };
}

#if defined(BB_TEST_NATIVE_WRITE_SUFFIX) || defined(BB_TEST_SHARED_POST_GRAPH)
#define BB_HAS_NATIVE_SCHEDULER_RECORDER

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <mutex>
#include <span>
#include <tuple>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#ifdef BB_TEST_SHARED_POST_GRAPH
#include <vk_mem_alloc.h>
#endif

namespace Vulkan {
class Scheduler;
}

namespace Vulkan::NativeWriteSuffix {

using CaptureId = u64;
enum class Consumer { WorldAt, Edit, PostOrder };
enum class Marker {
    WorldAtStart,
    WorldAtCopyEncoded,
    EditRaisedStart,
    EditPoolStart,
    EditOpaqueStart,
    EditPrefixEnd,
    EditDispatchEncoded,
    Count,
};
enum class Kind {
    UnknownRecord,
    RawCommandBuffer,
    RenderBegin,
    RenderAttachment,
    RenderEnd,
    NativeOperation,
#ifdef BB_TEST_SHARED_POST_GRAPH
    PostOperation,
#endif
};
enum class Gap : u32 {
    PriorRawEscape = 1 << 0,
    PriorOpenPass = 1 << 1,
    OrderedHost = 1 << 2,
    ForeignScheduler = 1 << 3,
    Overflow = 1 << 4,
    UnjoinedBuffer = 1 << 5,
    FailedSubmit = 1 << 6,
    DuplicateMarker = 1 << 7,
    UnjoinedRenderInfo = 1 << 8,
    UnknownRecord = 1 << 9,
    RawCommandBuffer = 1 << 10,
    InvalidMarkerOrder = 1 << 11,
    UnclassifiedSink = 1 << 12,
    ReentrantEncoding = 1 << 13,
    SubmitCallback = 1 << 14,
#ifdef BB_TEST_SHARED_POST_GRAPH
    UnclosedPostBorrow = 1 << 15,
    DuplicatePostOperation = 1 << 16,
    InvalidOverwriteRoot = 1 << 17,
    UnjoinedProxyDependency = 1 << 18,
#endif
};

inline thread_local bool in_recorded_closure = false;

struct Position {
    u64 tick{};
    u32 segment{};
    vk::CommandBuffer buffer{};
    u64 encoding{}; // comparable only within this command buffer incarnation
    u32 suborder{};
    u32 submitted_index{};
    bool submitted{};

    [[nodiscard]] auto StreamKey() const {
        return std::tuple(tick, submitted_index, encoding, suborder);
    }
};

struct Attachment {
    u32 slot{};
    vk::ImageAspectFlagBits aspect{};
    vk::ImageView view{};
    vk::ImageLayout layout{};
    vk::AttachmentLoadOp load{};
    vk::AttachmentStoreOp store{};
    vk::ImageView resolve_view{};
    vk::ImageLayout resolve_layout{};
    vk::ResolveModeFlagBits resolve_mode{};
    std::array<u32, 4> clear_words{};
    vk::Rect2D render_area{};
    u32 layers{};
    u32 view_mask{};
    vk::RenderingFlags flags{};
};

struct Event {
    Position where{};
    Kind kind{};
    Attachment attachment{};
    u64 operation{}; // caller-defined join to immutable native facts
};

inline constexpr size_t MaxEvents = 256;
inline constexpr size_t MarkerCount = static_cast<size_t>(Marker::Count);

struct Report {
    std::array<Event, MaxEvents> events{};
    size_t count{};
    std::array<Position, MarkerCount> markers{};
    u64 excluded_operations{}; // whole capture, not per prefix
    Position first_unclassified{}; // first unresolved positioned span in the requested prefix
    u32 first_unpositioned_gap{};
    u32 gaps{};
    bool retired{};
    bool scheduler_prefix_complete{}; // does not attest GPU dependencies or resource ownership
};

struct QueueSubmitInput {
    vk::Queue queue{};
    u32 family{};
    vk::Fence fence{};
    vk::Result result{};
    std::span<const vk::Semaphore> waits{}, signals{};
    std::span<const u64> wait_values{}, signal_values{};
    std::span<const vk::PipelineStageFlags> wait_stages{};
    vk::Semaphore timeline{};
    u64 graphics_sequence{};
    bool metadata_complete{true};
};

struct QueueSubmit {
    struct Segment {
        u32 segment = ~0u;
        vk::CommandBuffer buffer{};
    };
    struct Semaphore {
        vk::Semaphore handle{};
        u64 value{};
        vk::PipelineStageFlags stages{};
    };
    u64 tick{};
    vk::Queue queue{};
    u32 family{};
    vk::Fence fence{};
    vk::Result result{};
    vk::Semaphore timeline{};
    u64 graphics_sequence{};
    bool input_joined{};
    u32 buffer_count{}, wait_count{}, signal_count{};
    std::array<Segment, 64> buffers{};
    std::array<Semaphore, 4> waits{}, signals{};
};

// Build from the structures that were passed to vkQueueSubmit. The limits describe the real
// backing arrays. Report malformed shape as incomplete and keep only safely readable elements.
inline QueueSubmitInput ActualQueueSubmitInput(
    vk::Queue queue, u32 family, vk::Fence fence, vk::Result result, vk::Semaphore work_timeline,
    u64 graphics_sequence, const vk::SubmitInfo& submit,
    const vk::TimelineSemaphoreSubmitInfo& values, size_t semaphore_capacity, size_t stage_capacity) {
    const auto span = [](auto* data, size_t used, size_t capacity) {
        return std::span{data, data ? std::min(used, capacity) : 0};
    };
    const auto waits = span(submit.pWaitSemaphores, submit.waitSemaphoreCount, semaphore_capacity);
    const auto signals = span(submit.pSignalSemaphores, submit.signalSemaphoreCount, semaphore_capacity);
    const auto wait_values = span(values.pWaitSemaphoreValues, values.waitSemaphoreValueCount,
                                  semaphore_capacity);
    const auto signal_values = span(values.pSignalSemaphoreValues, values.signalSemaphoreValueCount,
                                    semaphore_capacity);
    const auto stages = span(submit.pWaitDstStageMask, submit.waitSemaphoreCount, stage_capacity);
    return {
        .queue = queue,
        .family = family,
        .fence = fence,
        .result = result,
        .waits = waits,
        .signals = signals,
        .wait_values = wait_values,
        .signal_values = signal_values,
        .wait_stages = stages,
        .timeline = work_timeline,
        .graphics_sequence = graphics_sequence,
        .metadata_complete = submit.pNext == &values && waits.size() == submit.waitSemaphoreCount &&
            signals.size() == submit.signalSemaphoreCount && waits.size() == wait_values.size() &&
            signals.size() == signal_values.size() && waits.size() == stages.size() &&
            wait_values.size() == values.waitSemaphoreValueCount &&
            signal_values.size() == values.signalSemaphoreValueCount,
    };
}

struct QueueReport {
    u32 count{};
    bool overflow{};
    std::array<QueueSubmit, MaxEvents> records{};
};

#ifdef BB_TEST_SHARED_POST_GRAPH
inline constexpr size_t MaxPostOperations = 32;
class PostOrderFixture;

enum class PostRole : u8 {
    Merge, Draw, UiBlit, Display, PrepareBarrier, PreparePostprocess,
    PriorProxyTransition, ProxyEdgeClamp,
};
struct PostKey {
    u64 request{}, checkpoint{}, frame{};
    bool operator==(const PostKey&) const = default;
};
struct PostToken {
    CaptureId capture{};
    u64 operation{};
    PostRole role{};
    explicit operator bool() const { return capture && operation; }
    bool operator==(const PostToken&) const = default;
};
struct PostBorrowOrigin {
    u64 tick{}, epoch{};
    u32 segment{};
    vk::CommandBuffer buffer{};
    bool operator==(const PostBorrowOrigin&) const = default;
    bool Matches(const PostBorrowOrigin& current) const { return tick && buffer && *this == current; }
};

enum class PostMergeProgram : u8 { Unknown, UpscaleMerge };
enum class PostPredecessor : u8 { Unknown, None, ScopedVendorUnclassified };
enum class PostOverwriteTail : u8 { Unknown, NoRawCommands, BreadcrumbOnly };

struct PostMergeAllocation {
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    vk::DeviceMemory memory{};
    u64 offset{}, bytes{}, epoch{};
    bool operator==(const PostMergeAllocation&) const = default;
};

struct PostMergeBarrierObservation {
    vk::ImageMemoryBarrier2 issued{};
    PostMergeAllocation backing{};
};

struct PostMergeImage {
    vk::Image image{};
    vk::ImageView view{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    vk::DeviceMemory memory{};
    u64 allocation_offset{}, allocation_bytes{}, allocation_epoch{};
    u64 content_version{};
    vk::ImageSubresourceRange range{};
    vk::Extent2D extent{};
    vk::Format format{};
    vk::ImageLayout layout{};
    vk::SampleCountFlagBits samples{};

    [[nodiscard]] PostMergeAllocation Backing() const noexcept {
        return {allocator, allocation, memory, allocation_offset, allocation_bytes, allocation_epoch};
    }
    bool operator==(const PostMergeImage&) const = default;
};

struct PostProxyOwner {
    u64 owner{}, generation{};
    bool operator==(const PostProxyOwner&) const = default;
};

struct PostProxyTransitionProof {
    PostMergeBarrierObservation barrier{};
    u64 version{};
    PostProxyOwner owner{};
};

struct PostProxyEdgesProof {
    PostMergeImage proxy{}; // Content version at the start of the actual two-copy closure.
    u64 result_version{};
    PostProxyOwner owner{};
    vk::Image source{}, destination{};
    vk::ImageLayout source_layout{}, destination_layout{};
    vk::ImageCopy row{}, column{};
    vk::MemoryBarrier2 before{}, between{}, after{};
};

enum class PostProxyVendorResult : u8 { Unknown, SuccessfulDlss };
struct PostProxyVendorProof {
    PostBorrowOrigin origin{};
    PostMergeImage color{}, output{}; // Actual successful Evaluate resource descriptors.
    PostProxyVendorResult result{};
    bool color_read_write{}, output_read_write{};
    // The caller checked every relevant declared access and the intervening original work for
    // possible writes or backing changes to this exact proxy. Vendor internals stay unclassified.
    bool proxy_writes_excluded{};
};

struct PostPriorProxyProof {
    PostToken transition{}, edges{};
    PostProxyOwner owner{};
    PostProxyVendorProof vendor{};
    explicit operator bool() const { return transition || edges; }
};

struct PostProxyLifetimeProof {
    PostKey key{};
    PostProxyOwner owner{};
    // The owner checked the same proxy allocation/range and version through actual GPU use
    // of the merge. A future allocation with the same public handles is no lease.
    PostMergeImage held{};
};

struct PostMergeRootProof {
    PostBorrowOrigin origin{};
    vk::Pipeline pipeline{};
    vk::PipelineLayout layout{};
    PostMergeImage rgb{}, destination{}, alpha{};
    vk::Extent3D groups{};
    u64 destination_prior_version{};
    u32 mode{}, alpha_source{};
    PostMergeProgram program{};
    // Scoped predecessor commands were all issued on this borrow, before the overwrite.
    // Their recording completed synchronously, with no retained handle or foreign queue work.
    PostPredecessor predecessor{};
    PostPriorProxyProof prior_proxy{};
};

inline constexpr size_t MaxPostMergeBarriers = 8;
struct PostMergeRootEvidence {
    PostMergeRootProof actual{};
    std::array<vk::ImageMemoryBarrier2, 3> readiness{}; // RGB, destination, then alpha.
    PostOverwriteTail tail{};

    explicit operator bool() const { return actual.origin.tick != 0; }
};

inline bool SamePostImageSubresource(const PostMergeImage& a, const PostMergeImage& b) {
    return a.image == b.image && a.view == b.view && a.Backing() == b.Backing() &&
           a.range == b.range && a.extent == b.extent && a.format == b.format &&
           a.layout == b.layout && a.samples == b.samples;
}

inline bool ValidPostPriorProxy(const PostMergeRootProof& proof) {
    const auto& prior = proof.prior_proxy;
    const auto& vendor = prior.vendor;
    return prior.transition && prior.edges && prior.owner.owner &&
           prior.transition.capture == prior.edges.capture &&
           prior.transition.role == PostRole::PriorProxyTransition &&
           prior.edges.role == PostRole::ProxyEdgeClamp &&
           proof.predecessor == PostPredecessor::ScopedVendorUnclassified &&
           proof.alpha.content_version && vendor.origin.Matches(proof.origin) &&
           vendor.result == PostProxyVendorResult::SuccessfulDlss &&
           vendor.color == proof.alpha && SamePostImageSubresource(vendor.output, proof.rgb) &&
           !vendor.color_read_write && vendor.output_read_write && vendor.proxy_writes_excluded;
}

inline bool ValidPostProxyTransition(const PostProxyTransitionProof& transition,
                                     const PostMergeImage& alpha, u32 graphics_family) {
    using Access = vk::AccessFlagBits2;
    using Stage = vk::PipelineStageFlagBits2;
    const auto& barrier = transition.barrier.issued;
    return transition.version && transition.barrier.backing == alpha.Backing() &&
           !barrier.pNext && barrier.image == alpha.image && barrier.subresourceRange == alpha.range &&
           barrier.newLayout == alpha.layout && barrier.oldLayout != vk::ImageLayout::eUndefined &&
           bool(barrier.srcStageMask & Stage::eAllCommands) &&
           bool(barrier.srcAccessMask & Access::eMemoryWrite) &&
           bool(barrier.dstStageMask & (Stage::eComputeShader | Stage::eAllCommands)) &&
           bool(barrier.dstAccessMask &
                (Access::eMemoryRead | Access::eShaderRead | Access::eShaderSampledRead)) &&
           barrier.srcQueueFamilyIndex == barrier.dstQueueFamilyIndex &&
           (barrier.srcQueueFamilyIndex == VK_QUEUE_FAMILY_IGNORED ||
            barrier.srcQueueFamilyIndex == graphics_family);
}

inline bool ValidPostProxyEdges(const PostProxyEdgesProof& edges, const PostMergeImage& alpha,
                                u64 prior_version) {
    using Access = vk::AccessFlagBits2;
    using Stage = vk::PipelineStageFlagBits2;
    const auto [width, height] = alpha.extent;
    if (!SamePostImageSubresource(edges.proxy, alpha) || !prior_version ||
        edges.proxy.content_version != prior_version || edges.result_version <= prior_version ||
        edges.result_version != alpha.content_version || edges.source != alpha.image ||
        edges.destination != alpha.image || edges.source_layout != vk::ImageLayout::eGeneral ||
        edges.destination_layout != vk::ImageLayout::eGeneral || width < 2 || height < 2 ||
        width > 0x7fffffffu || height > 0x7fffffffu) {
        return false;
    }
    const vk::ImageSubresourceLayers layer{vk::ImageAspectFlagBits::eColor, 0, 0, 1};
    const vk::ImageCopy row{layer, {0, s32(height - 2), 0}, layer, {0, s32(height - 1), 0},
                            {width, 1, 1}};
    const vk::ImageCopy column{layer, {s32(width - 2), 0, 0}, layer, {s32(width - 1), 0, 0},
                               {1, height, 1}};
    if (edges.row != row || edges.column != column) {
        return false;
    }
    const auto covers = [](const vk::MemoryBarrier2& barrier, Stage src_stage,
                           Access src_access, Stage dst_stage, vk::AccessFlags2 dst_access) {
        return !barrier.pNext && bool(barrier.srcStageMask & src_stage) &&
               bool(barrier.srcAccessMask & src_access) && bool(barrier.dstStageMask & dst_stage) &&
               (barrier.dstAccessMask & dst_access) == dst_access;
    };
    constexpr auto transfer = Access::eTransferRead | Access::eTransferWrite;
    return covers(edges.before, Stage::eAllCommands, Access::eMemoryWrite, Stage::eTransfer, transfer) &&
           covers(edges.between, Stage::eTransfer, Access::eTransferWrite, Stage::eTransfer, transfer) &&
           covers(edges.after, Stage::eTransfer, Access::eTransferWrite, Stage::eAllCommands,
                  Access::eMemoryRead);
}

inline PostMergeRootEvidence CheckPostMergeRoot(
    const PostBorrowOrigin& origin, const PostMergeRootProof& proof, u32 graphics_family,
    std::span<const PostMergeBarrierObservation> emitted) {
    const bool prior_proxy = bool(proof.prior_proxy);
    if (emitted.size() < (prior_proxy ? 2 : 3) || emitted.size() > MaxPostMergeBarriers ||
        !origin.Matches(proof.origin) || !proof.pipeline || !proof.layout || proof.mode != 0 ||
        !proof.destination_prior_version ||
        proof.destination.content_version <= proof.destination_prior_version ||
        proof.program != PostMergeProgram::UpscaleMerge ||
        (proof.alpha_source != 1 && proof.alpha_source != 2) ||
        (proof.predecessor != PostPredecessor::None &&
         proof.predecessor != PostPredecessor::ScopedVendorUnclassified) ||
        (prior_proxy && !ValidPostPriorProxy(proof))) {
        return {};
    }
    constexpr vk::ImageSubresourceRange color0{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
    const std::array images{proof.rgb, proof.destination, proof.alpha};
    for (const auto& image : images) {
        if (!image.image || !image.view || !image.allocator || !image.allocation || !image.memory ||
            !image.allocation_epoch || !image.allocation_bytes ||
            image.allocation_offset > ~u64{} - image.allocation_bytes ||
            image.range != color0 || !image.extent.width || !image.extent.height ||
            image.format != vk::Format::eR16G16B16A16Sfloat ||
            image.layout != vk::ImageLayout::eGeneral || image.samples != vk::SampleCountFlagBits::e1) {
            return {};
        }
    }
    for (size_t i = 0; i < images.size(); ++i) {
        for (size_t j = i + 1; j < images.size(); ++j) {
            const auto& a = images[i];
            const auto& b = images[j];
            if (a.image == b.image || a.view == b.view || a.allocator != b.allocator ||
                a.allocation == b.allocation ||
                (a.memory == b.memory &&
                 a.allocation_offset < b.allocation_offset + b.allocation_bytes &&
                 b.allocation_offset < a.allocation_offset + a.allocation_bytes)) {
                return {};
            }
        }
    }
    const auto extent = proof.destination.extent;
    const auto groups = [](u32 pixels) { return pixels / 8 + u32(pixels % 8 != 0); };
    if (proof.rgb.extent != extent || proof.alpha.extent.width >= extent.width ||
        proof.alpha.extent.height >= extent.height ||
        proof.groups != vk::Extent3D{groups(extent.width), groups(extent.height), 1}) {
        return {};
    }

    using Access = vk::AccessFlagBits2;
    using Stage = vk::PipelineStageFlagBits2;
    constexpr auto writes = Access::eMemoryWrite | Access::eShaderWrite | Access::eShaderStorageWrite |
                            Access::eColorAttachmentWrite | Access::eTransferWrite;
    const auto visible_write = [writes](const vk::ImageMemoryBarrier2& barrier) {
        const auto stage = barrier.srcStageMask;
        const auto access = barrier.srcAccessMask;
        return ((stage & Stage::eAllCommands) && (access & writes)) ||
               ((stage & (Stage::eComputeShader | Stage::eFragmentShader | Stage::eAllGraphics)) &&
                (access & (Access::eMemoryWrite | Access::eShaderWrite | Access::eShaderStorageWrite))) ||
               ((stage & (Stage::eColorAttachmentOutput | Stage::eAllGraphics)) &&
                (access & (Access::eMemoryWrite | Access::eColorAttachmentWrite))) ||
               ((stage & (Stage::eAllTransfer | Stage::eCopy | Stage::eBlit | Stage::eResolve |
                          Stage::eClear)) &&
                (access & (Access::eMemoryWrite | Access::eTransferWrite)));
    };
    constexpr std::array<vk::AccessFlags2, 3> accesses{
        Access::eMemoryRead | Access::eShaderRead | Access::eShaderStorageRead,
        Access::eMemoryWrite | Access::eShaderWrite | Access::eShaderStorageWrite,
        Access::eMemoryRead | Access::eShaderRead | Access::eShaderSampledRead,
    };
    PostMergeRootEvidence evidence{.actual = proof};
    for (size_t i = 0; i < images.size(); ++i) {
        const auto& image = images[i];
        // Use the last actual observed transition for this exact backing. An intervening
        // layout/ownership change invalidates an earlier acceptable barrier.
        const auto found = std::find_if(emitted.rbegin(), emitted.rend(),
            [&](const PostMergeBarrierObservation& note) { return note.issued.image == image.image; });
        if (i == 2 && prior_proxy && found == emitted.rend()) {
            continue; // Its exact earlier position and later writes must join at retirement.
        }
        if (i == 2 && prior_proxy) {
            return {}; // Keep the two evidence paths distinct, including changed layouts.
        }
        if (found == emitted.rend() || found->backing != image.Backing()) {
            return {};
        }
        const auto& barrier = found->issued;
        if (barrier.pNext || barrier.subresourceRange != image.range || barrier.newLayout != image.layout ||
            !barrier.srcStageMask || !(barrier.dstStageMask & (Stage::eComputeShader | Stage::eAllCommands)) ||
            !(barrier.dstAccessMask & accesses[i]) || barrier.srcQueueFamilyIndex != barrier.dstQueueFamilyIndex ||
            (barrier.srcQueueFamilyIndex != VK_QUEUE_FAMILY_IGNORED &&
             barrier.srcQueueFamilyIndex != graphics_family) ||
            (i != 1 && (!visible_write(barrier) || barrier.oldLayout == vk::ImageLayout::eUndefined))) {
            return {};
        }
        evidence.readiness[i] = barrier;
    }
    return evidence;
}

enum class PostPhase : u8 { Pending, Encoded, Submitted, Retired, Refused };
enum class PostProxyPhase : u8 { Unused, Pending, Retired, Refused };
struct PostProxyReceipt {
    PostToken transition{}, edges{};
    Position transition_at{}, edges_at{};
    PostProxyPhase phase{};
};
struct PostReceipt {
    PostKey key{};
    PostToken token{};
    Position where{};
    QueueSubmit submission{};
    u64 completed_tick{};
    u32 gaps{};
    PostPhase phase{};
    bool stream_joined{}; // Only scheduler order. Resource/barrier dependency proof is separate.
    PostMergeRootEvidence overwrite{}; // Starts after independently unclassified predecessors.
    PostProxyReceipt proxy{};
};
#endif

class Encoder;

class Recorder {
public:
    static Recorder& Get() {
        static Recorder recorder;
        return recorder;
    }

    [[nodiscard]] bool Armed() const noexcept {
        return published_id.load(std::memory_order_acquire) != 0;
    }

    CaptureId Arm(const void* scheduler, Consumer requested, u64 tick, bool escaped_raw,
                  bool open_pass
#ifdef BB_TEST_SHARED_POST_GRAPH
                  , PostKey requested_post = {}
#endif
                  ) {
        std::scoped_lock lock{mutex};
        if (id != 0 || tick == 0) {
            return 0;
        }
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (requested == Consumer::PostOrder && (!requested_post.request || !requested_post.frame)) {
            return 0;
        }
        post_key = requested_post;
        post_count = 0;
        post_borrowed = post_closed = false;
        post_overwrite = {};
        post_proxy_transition = {};
        post_proxy_edges = {};
        post_proxy_lease_joined = false;
#endif
        capture = {};
        submissions.count = 0;
        submissions.overflow = false;
        owner = scheduler;
        consumer = requested;
        first_tick = tick;
        expected_tick = tick;
        next_encoding = 0;
        if (escaped_raw) {
            AddGap(Gap::PriorRawEscape);
        }
        if (open_pass) {
            AddGap(Gap::PriorOpenPass);
        }
        id = ++next_id;
        published_id.store(id, std::memory_order_release);
        return id;
    }

#ifdef BB_TEST_SHARED_POST_GRAPH
    PostToken ReservePost(const void* scheduler, CaptureId target, PostRole role, u64 operation) {
        std::scoped_lock lock{mutex};
        if (!IsPost(scheduler, target) || !operation || role > PostRole::ProxyEdgeClamp) {
            return {};
        }
        if (post_count == post_tokens.size()) {
            AddGap(Gap::Overflow);
            return {};
        }
        for (const auto& reserved : std::span{post_tokens}.first(post_count)) {
            if (reserved.operation == operation ||
                (reserved.role == role && (role == PostRole::Merge ||
                  role == PostRole::PriorProxyTransition || role == PostRole::ProxyEdgeClamp))) {
                AddGap(Gap::DuplicatePostOperation);
                return {};
            }
        }
        return post_tokens[post_count++] = {target, operation, role};
    }

    bool OpenPostRoot(const void* scheduler, PostToken token) {
        std::scoped_lock lock{mutex};
        if (!IsPost(scheduler, token.capture) || token.role != PostRole::Merge ||
            !HasPostToken(token) || post_borrowed) {
            return false;
        }
        post_borrowed = true;
        return true;
    }

    bool ClosePostRoot(const void* scheduler, PostToken token, bool fully_classified,
                       PostOverwriteTail tail = PostOverwriteTail::Unknown) {
        std::scoped_lock lock{mutex};
        if (IsPost(scheduler, token.capture) && post_borrowed && HasPostToken(token)) {
            const bool known_tail = tail == PostOverwriteTail::NoRawCommands ||
                                    tail == PostOverwriteTail::BreadcrumbOnly;
            if (fully_classified && FindPost(token.operation) &&
                (post_overwrite ? known_tail : tail == PostOverwriteTail::Unknown)) {
                post_closed = true;
                post_overwrite.tail = tail;
                return true;
            } else {
                AddGap(Gap::UnclosedPostBorrow);
            }
        }
        return false;
    }

    bool ConfirmPostProxyLifetime(const void* scheduler, PostToken merge, u64 completed_tick,
                                 const PostProxyLifetimeProof& proof) {
        std::scoped_lock lock{mutex};
        if (!IsPost(scheduler, merge.capture) || !HasPostToken(merge) ||
            merge.role != PostRole::Merge || !post_overwrite.actual.prior_proxy || !post_closed) {
            return false;
        }
        const auto* root = FindPost(merge.operation);
        const auto* submit = root && root->where.submitted ? FindSubmit(root->where.tick) : nullptr;
        if (!submit || !ValidPostSubmission(*submit) || completed_tick < root->where.tick) {
            return false;
        }
        PostProxyReceipt joined{};
        if (JoinPriorProxy(root->where, completed_tick, joined) == PostProxyPhase::Refused) {
            return false;
        }
        const auto& actual = post_overwrite.actual;
        if (proof.key != post_key || proof.owner != actual.prior_proxy.owner ||
            proof.held != actual.alpha) {
            AddGap(Gap::UnjoinedProxyDependency);
            return false;
        }
        post_proxy_lease_joined = true;
        return true;
    }

    bool ReadPost(const void* scheduler, PostToken token, u64 completed_tick, PostReceipt& out) {
        std::scoped_lock lock{mutex};
        if (!IsPost(scheduler, token.capture) || !HasPostToken(token)) {
            return false;
        }
        out = {.key = post_key, .token = token, .completed_tick = completed_tick, .gaps = capture.gaps};
        const auto& prior_proxy = post_overwrite.actual.prior_proxy;
        if (prior_proxy) {
            out.proxy = {prior_proxy.transition, prior_proxy.edges, {}, {}, PostProxyPhase::Pending};
        } else {
            out.overwrite = post_overwrite;
        }
        if (submissions.overflow) {
            out.gaps |= static_cast<u32>(Gap::Overflow);
        }
        const auto* event = FindPost(token.operation);
        const auto tokens = std::span{post_tokens}.first(post_count);
        const auto root_token = std::ranges::find_if(tokens,
            [](const PostToken& op) { return op.role == PostRole::Merge; });
        const auto* root = root_token == tokens.end() ? nullptr : FindPost(root_token->operation);
        if (!event) {
            const bool recorded_without_note =
                std::ranges::any_of(std::span{capture.events}.first(capture.count), [&](const Event& e) {
                    return e.kind == Kind::UnknownRecord && e.operation == token.operation;
                });
            if (recorded_without_note) {
                out.gaps |= static_cast<u32>(Gap::UnknownRecord);
            }
            if (out.gaps & (static_cast<u32>(Gap::Overflow) |
                            static_cast<u32>(Gap::UnknownRecord) |
                            static_cast<u32>(Gap::DuplicatePostOperation) |
                            static_cast<u32>(Gap::UnclosedPostBorrow) |
                            static_cast<u32>(Gap::InvalidOverwriteRoot))) {
                out.phase = PostPhase::Refused;
            }
            return true;
        }
        out.where = event->where;
        if (out.gaps & static_cast<u32>(Gap::DuplicatePostOperation)) {
            out.phase = PostPhase::Refused;
            if (prior_proxy) {
                out.proxy.phase = PostProxyPhase::Refused;
            }
            return true;
        }
        const auto* submit = FindSubmit(event->where.tick);
        if (!submit) {
            out.phase = expected_tick > event->where.tick ? PostPhase::Refused : PostPhase::Encoded;
            if (prior_proxy && out.phase == PostPhase::Refused) {
                out.proxy.phase = PostProxyPhase::Refused;
            }
            return true;
        }
        out.submission = *submit;
        if (!event->where.submitted || !ValidPostSubmission(*submit)) {
            out.phase = PostPhase::Refused;
            if (prior_proxy) {
                out.proxy.phase = PostProxyPhase::Refused;
            }
            return true;
        }
        out.phase = completed_tick >= event->where.tick ? PostPhase::Retired : PostPhase::Submitted;
        if (!root || !root->where.submitted || !post_closed ||
            event->where.StreamKey() < root->where.StreamKey()) {
            out.gaps |= static_cast<u32>(Gap::UnclosedPostBorrow);
            if (prior_proxy && root && root->where.submitted && !post_closed) {
                out.proxy.phase = PostProxyPhase::Refused;
            }
            return true;
        }
        if (prior_proxy) {
            out.proxy.phase = JoinPriorProxy(root->where, completed_tick, out.proxy);
            if (out.proxy.phase == PostProxyPhase::Retired) {
                out.overwrite = post_overwrite;
                out.overwrite.readiness[2] = post_proxy_transition.barrier.issued;
            } else {
                out.gaps |= static_cast<u32>(Gap::UnjoinedProxyDependency);
            }
        }
        for (const auto& batch : std::span{submissions.records}.first(submissions.count)) {
            if (batch.tick >= root->where.tick && batch.tick <= event->where.tick &&
                (!ValidPostSubmission(batch) || batch.queue != submit->queue ||
                 batch.timeline != submit->timeline)) {
                out.gaps |= static_cast<u32>(Gap::UnjoinedBuffer);
            }
        }
        for (const auto& current : std::span{capture.events}.first(capture.count)) {
            if (current.kind == Kind::RawCommandBuffer &&
                (current.where.submitted ? current.where.StreamKey() <= event->where.StreamKey() :
                                           current.where.tick <= event->where.tick)) {
                out.gaps |= static_cast<u32>(Gap::RawCommandBuffer);
            }
            if ((current.kind == Kind::UnknownRecord || current.kind == Kind::NativeOperation) &&
                current.where.tick >= root->where.tick &&
                current.where.tick <= event->where.tick &&
                (!current.where.submitted ||
                 (root->where.StreamKey() < current.where.StreamKey() &&
                  current.where.StreamKey() < event->where.StreamKey()))) {
                out.gaps |= static_cast<u32>(Gap::UnknownRecord);
            }
        }
        out.stream_joined = out.gaps == 0;
        return true;
    }
#endif

    void Disarm(const void* scheduler, CaptureId target) {
        std::scoped_lock lock{mutex};
        if (owner == scheduler && id == target) {
            Stop();
        }
    }

    void Detach(const void* scheduler) {
        std::scoped_lock lock{mutex};
        if (owner == scheduler) {
            Stop();
        }
    }

    Encoder Encode(const void* scheduler, u64 tick, u32 segment, vk::CommandBuffer buffer);

    void Unordered(const void* scheduler, Gap why) {
        const CaptureId observed = published_id.load(std::memory_order_acquire);
        if (observed == 0) {
            return;
        }
        std::scoped_lock lock{mutex};
        if (observed == id) {
            AddGap(scheduler == owner ? why : Gap::ForeignScheduler);
        }
    }

    // Called while the graphics queue submit lock is held. The ordered array is the one actually
    // submitted. The sparse array names the segment incarnations that produced its commands.
    void Submit(const void* scheduler, u64 tick, std::span<const vk::CommandBuffer> ordered,
                std::span<const vk::CommandBuffer> sparse, bool success,
                const QueueSubmitInput* input = nullptr) {
        const CaptureId observed = published_id.load(std::memory_order_acquire);
        if (observed == 0) {
            return;
        }
        std::scoped_lock lock{mutex};
        if (observed != id) {
            return;
        }
        if (scheduler != owner) {
            AddGap(Gap::ForeignScheduler);
            return;
        }
        if (tick < first_tick) {
            if (expected_tick != first_tick) {
                AddGap(Gap::UnjoinedBuffer);
            }
            return; // submissions already staged when this request armed
        }
        if (input) {
            StoreSubmit(tick, ordered, sparse, *input);
        }
        if (tick != expected_tick) {
            AddGap(Gap::UnjoinedBuffer);
            if (tick < expected_tick) {
                return;
            }
        }
        expected_tick = tick + 1;
        if (!success) {
            AddGap(Gap::FailedSubmit);
            return;
        }
        size_t index = 0;
        for (size_t segment = 0; segment < sparse.size(); ++segment) {
            const auto buffer = sparse[segment];
            if (!buffer) {
                continue;
            }
            if (index == ordered.size() || buffer != ordered[index] ||
                std::ranges::find(ordered.first(index), buffer) != ordered.first(index).end()) {
                AddGap(Gap::UnjoinedBuffer);
                return;
            }
            ++index;
        }
        if (index != ordered.size()) {
            AddGap(Gap::UnjoinedBuffer);
            return;
        }
        const auto join = [&](Position& position) {
            if (position.encoding == 0 || position.tick != tick) {
                return;
            }
            if (position.segment >= sparse.size() || !position.buffer ||
                position.buffer != sparse[position.segment]) {
                AddGap(Gap::UnjoinedBuffer);
                return;
            }
            position.submitted_index = static_cast<u32>(
                std::ranges::find(ordered, position.buffer) - ordered.begin());
            position.submitted = true;
        };
        for (auto& marker : capture.markers) {
            join(marker);
        }
        for (auto& event : std::span{capture.events}.first(capture.count)) {
            join(event.where);
        }
    }

    bool ReadSubmissions(const void* scheduler, CaptureId target, QueueReport& out) {
        std::scoped_lock lock{mutex};
        if (!target || target != id || scheduler != owner) {
            return false;
        }
        out.count = submissions.count;
        out.overflow = submissions.overflow;
        std::ranges::copy(std::span{submissions.records}.first(submissions.count),
                          out.records.begin());
        return true;
    }

    // Read only after the ordinary completion path. For T06, the caller must separately check
    // invalidation and join the actual copied source; T07 must join the actual EDIT descriptors.
    bool Read(const void* scheduler, CaptureId target, u64 completed_tick, Report& report) {
        std::scoped_lock lock{mutex};
        if (target == 0 || target != id || scheduler != owner || consumer == Consumer::PostOrder) {
            return false;
        }
        report = capture;
        const auto markers = std::span{report.markers};
        const auto at = [&](Marker marker) -> const Position& {
            return markers[static_cast<size_t>(marker)];
        };
        const auto& lower = at(consumer == Consumer::WorldAt ? Marker::WorldAtStart :
                                                              Marker::EditRaisedStart);
        const auto& upper = at(consumer == Consumer::WorldAt ? Marker::WorldAtCopyEncoded :
                                                              Marker::EditPrefixEnd);
        const auto& encoded = at(consumer == Consumer::WorldAt ? Marker::WorldAtCopyEncoded :
                                                                Marker::EditDispatchEncoded);
        const auto before = [](const Position& a, const Position& b) {
            return a.submitted && b.submitted && a.StreamKey() < b.StreamKey();
        };
        auto first = lower;
        if (!lower.submitted || !upper.submitted || !encoded.submitted) {
            return true;
        }
        bool valid_order = before(lower, upper);
        if (consumer == Consumer::Edit) {
            for (const auto marker : {Marker::EditPoolStart, Marker::EditOpaqueStart}) {
                const auto& start = at(marker);
                if (!start.submitted) {
                    return true;
                }
                valid_order &= before(start, upper);
                if (before(start, first)) {
                    first = start;
                }
            }
            valid_order &= before(upper, encoded) && upper.tick == encoded.tick &&
                           upper.segment == encoded.segment && upper.encoding == encoded.encoding;
        }
        if (!valid_order) {
            report.gaps |= static_cast<u32>(Gap::InvalidMarkerOrder);
            return true;
        }
        report.retired = completed_tick >= encoded.tick;
        report.count = 0;
        for (const auto& event : std::span{capture.events}.first(capture.count)) {
            const auto& pos = event.where;
            if (!pos.submitted && pos.tick >= first.tick && pos.tick <= upper.tick) {
                report.gaps |= static_cast<u32>(Gap::UnjoinedBuffer);
            }
            // A raw handle may have escaped before the lower marker. Do not infer when its
            // recipient stopped using it, even when subsequent segments reuse that same value.
            const bool in_prefix = before(first, pos) && before(pos, upper);
            const bool raw = event.kind == Kind::RawCommandBuffer && before(pos, upper);
            const bool unknown = event.kind == Kind::UnknownRecord && in_prefix;
            if (raw) {
                report.gaps |= static_cast<u32>(Gap::RawCommandBuffer);
            }
            if (unknown) {
                report.gaps |= static_cast<u32>(Gap::UnknownRecord);
            }
            if ((raw || unknown) &&
                (!report.first_unclassified.submitted || before(pos, report.first_unclassified))) {
                report.first_unclassified = pos;
            }
            if (in_prefix) {
                report.events[report.count++] = event;
            }
        }
        std::ranges::sort(std::span{report.events}.first(report.count),
                          [](const Event& a, const Event& b) {
                              return a.where.StreamKey() < b.where.StreamKey();
                          });
        report.scheduler_prefix_complete = report.retired && report.gaps == 0;
        return true;
    }

private:
    friend class Encoder;

#ifdef BB_TEST_SHARED_POST_GRAPH
    bool IsPost(const void* scheduler, CaptureId target) const {
        return target && target == id && owner == scheduler && consumer == Consumer::PostOrder;
    }

    bool HasPostToken(PostToken token) const {
        auto reserved = std::span{post_tokens}.first(post_count);
        return token && std::ranges::find(reserved, token) != reserved.end();
    }

    const Event* FindPost(u64 operation) const {
        for (const auto& event : std::span{capture.events}.first(capture.count)) {
            if (event.kind == Kind::PostOperation && event.operation == operation) {
                return &event;
            }
        }
        return nullptr;
    }

    const QueueSubmit* FindSubmit(u64 tick) const {
        for (const auto& submit : std::span{submissions.records}.first(submissions.count)) {
            if (submit.tick == tick) {
                return &submit;
            }
        }
        return nullptr;
    }

    static bool ValidPostSubmission(const QueueSubmit& submit) {
        if (!submit.input_joined || !submit.timeline || submit.result != vk::Result::eSuccess) {
            return false;
        }
        const auto waits = std::span{submit.waits}.first(submit.wait_count);
        const auto signals = std::span{submit.signals}.first(submit.signal_count);
        return std::ranges::all_of(waits, [](const QueueSubmit::Semaphore& wait) {
                   return wait.handle && wait.stages;
               }) &&
               std::ranges::all_of(signals, [](const QueueSubmit::Semaphore& signal) {
                   return bool(signal.handle);
               }) &&
               std::ranges::count_if(signals, [&](const QueueSubmit::Semaphore& signal) {
                   return signal.handle == submit.timeline;
               }) == 1 &&
               std::ranges::any_of(signals, [&](const QueueSubmit::Semaphore& signal) {
                   return signal.handle == submit.timeline && signal.value == submit.tick;
               });
    }

    PostProxyPhase JoinPriorProxy(Position root, u64 completed_tick, PostProxyReceipt& out) const {
        const auto& actual = post_overwrite.actual;
        const auto& prior = actual.prior_proxy;
        const auto* transition = FindPost(prior.transition.operation);
        const auto* edges = FindPost(prior.edges.operation);
        const auto* root_submit = FindSubmit(root.tick);
        if (transition) {
            out.transition_at = transition->where;
        }
        if (edges) {
            out.edges_at = edges->where;
        }
        if (!transition || !edges || !root_submit || !transition->where.submitted ||
            !edges->where.submitted || capture.gaps || submissions.overflow ||
            !(transition->where.StreamKey() < edges->where.StreamKey() &&
              edges->where.StreamKey() < root.StreamKey()) ||
            post_proxy_transition.owner != prior.owner || post_proxy_edges.owner != prior.owner ||
            !ValidPostProxyTransition(post_proxy_transition, actual.alpha, root_submit->family) ||
            !ValidPostProxyEdges(post_proxy_edges, actual.alpha, post_proxy_transition.version)) {
            return PostProxyPhase::Refused;
        }
        u64 expected = transition->where.tick;
        u64 sequence = 0;
        for (const auto& submit : std::span{submissions.records}.first(submissions.count)) {
            if (submit.tick < transition->where.tick || submit.tick > root.tick) {
                continue;
            }
            if (submit.tick != expected || submit.graphics_sequence <= sequence ||
                !ValidPostSubmission(submit) || submit.queue != root_submit->queue ||
                submit.family != root_submit->family || submit.timeline != root_submit->timeline) {
                return PostProxyPhase::Refused;
            }
            ++expected;
            sequence = submit.graphics_sequence;
        }
        if (expected != root.tick + 1) {
            return PostProxyPhase::Refused;
        }
        for (const auto& event : std::span{capture.events}.first(capture.count)) {
            if (event.where.tick > root.tick || &event == transition || &event == edges) {
                continue;
            }
            // Any raw escape at or before this borrow remains unbounded. For known scheduled
            // operations, inspect the whole interval from the prior transition to the merge.
            if (event.kind == Kind::RawCommandBuffer &&
                (!event.where.submitted || event.where.StreamKey() <= root.StreamKey())) {
                return PostProxyPhase::Refused;
            }
            if (event.where.tick >= transition->where.tick && (!event.where.submitted ||
                (transition->where.StreamKey() < event.where.StreamKey() &&
                 event.where.StreamKey() < root.StreamKey()))) {
                return PostProxyPhase::Refused;
            }
        }
        return completed_tick >= root.tick && post_proxy_lease_joined ? PostProxyPhase::Retired :
                                                                      PostProxyPhase::Pending;
    }
#endif

    void StoreSubmit(u64 tick, std::span<const vk::CommandBuffer> ordered,
                     std::span<const vk::CommandBuffer> sparse, const QueueSubmitInput& input) {
        if (submissions.count == submissions.records.size()) {
            submissions.overflow = true;
            return;
        }
        auto& record = submissions.records[submissions.count++];
        record = {.tick = tick, .queue = input.queue, .family = input.family, .fence = input.fence,
                  .result = input.result, .timeline = input.timeline,
                  .graphics_sequence = input.graphics_sequence};
        record.input_joined = input.metadata_complete && bool(input.queue) &&
            ordered.size() <= record.buffers.size() &&
            input.waits.size() == input.wait_values.size() &&
            input.waits.size() == input.wait_stages.size() &&
            input.waits.size() <= record.waits.size() &&
            input.signals.size() == input.signal_values.size() &&
            input.signals.size() <= record.signals.size();
        record.buffer_count = u32(std::min(ordered.size(), record.buffers.size()));
        for (u32 i = 0; i < record.buffer_count; ++i) {
            const auto buffer = ordered[i];
            const auto found = std::ranges::find(sparse, buffer);
            const bool unique = buffer && found != sparse.end() &&
                std::ranges::find(std::ranges::next(found), sparse.end(), buffer) == sparse.end() &&
                std::ranges::find(ordered.first(i), buffer) == ordered.first(i).end();
            const auto segment = unique ? u32(found - sparse.begin()) : ~0u;
            record.input_joined &= unique && (!i || record.buffers[i - 1].segment < segment);
            record.buffers[i] = {segment, buffer};
        }
        record.wait_count = u32(std::min({input.waits.size(), input.wait_values.size(),
                                         input.wait_stages.size(), record.waits.size()}));
        for (u32 i = 0; i < record.wait_count; ++i) {
            record.waits[i] = {input.waits[i], input.wait_values[i], input.wait_stages[i]};
        }
        record.signal_count = u32(std::min({input.signals.size(), input.signal_values.size(),
                                           record.signals.size()}));
        for (u32 i = 0; i < record.signal_count; ++i) {
            record.signals[i] = {input.signals[i], input.signal_values[i], {}};
        }
    }

    void Stop() {
        published_id.store(0, std::memory_order_release);
        id = 0;
        owner = nullptr;
    }

    void AddGap(Gap gap) {
        if (capture.first_unpositioned_gap == 0) {
            capture.first_unpositioned_gap = static_cast<u32>(gap);
        }
        capture.gaps |= static_cast<u32>(gap);
    }

    bool Store(CaptureId target, const Event& event
#ifdef BB_TEST_SHARED_POST_GRAPH
               , PostToken post = {}, const PostMergeRootEvidence* overwrite = nullptr,
               const PostProxyTransitionProof* transition = nullptr,
               const PostProxyEdgesProof* edges = nullptr
#endif
               ) {
        std::scoped_lock lock{mutex};
        if (target != id) {
            return false;
        }
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (event.kind == Kind::PostOperation &&
            (consumer != Consumer::PostOrder || !HasPostToken(post) || post.capture != target ||
             post.operation != event.operation || FindPost(event.operation) ||
             ((post.role == PostRole::PriorProxyTransition) != bool(transition)) ||
             ((post.role == PostRole::ProxyEdgeClamp) != bool(edges)) ||
             (post.role == PostRole::Merge && (!post_borrowed || post_closed)))) {
            AddGap(Gap::DuplicatePostOperation);
            return false;
        }
#endif
        if (capture.count == MaxEvents) {
            AddGap(Gap::Overflow);
            return false;
        }
        capture.events[capture.count++] = event;
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (overwrite) {
            const auto& prior = overwrite->actual.prior_proxy;
            if (!*overwrite || (prior &&
                (prior.transition.capture != target || !HasPostToken(prior.transition) ||
                 !HasPostToken(prior.edges)))) {
                AddGap(Gap::InvalidOverwriteRoot);
                return false;
            }
            post_overwrite = *overwrite;
        }
        if (transition) {
            post_proxy_transition = *transition;
        }
        if (edges) {
            post_proxy_edges = *edges;
        }
#endif
        return true;
    }

    void StoreMarker(CaptureId target, Marker kind, Position position) {
        std::scoped_lock lock{mutex};
        if (target != id) {
            return;
        }
        const auto index = static_cast<size_t>(kind);
        const bool world = kind == Marker::WorldAtStart || kind == Marker::WorldAtCopyEncoded;
        if (index >= MarkerCount || consumer == Consumer::PostOrder ||
            world != (consumer == Consumer::WorldAt)) {
            AddGap(Gap::InvalidMarkerOrder);
        } else if (capture.markers[index].encoding != 0) {
            AddGap(Gap::DuplicateMarker);
        } else {
            capture.markers[index] = position;
        }
    }

    void StoreGap(CaptureId target, Gap gap) {
        std::scoped_lock lock{mutex};
        if (target == id) {
            AddGap(gap);
        }
    }

    void Exclude(CaptureId target) {
        std::scoped_lock lock{mutex};
        if (target == id) {
            ++capture.excluded_operations;
        }
    }

    std::mutex mutex;
    std::atomic<CaptureId> published_id{};
    CaptureId next_id{};
    CaptureId id{};
    const void* owner{};
    Consumer consumer{};
    u64 first_tick{};
    u64 expected_tick{};
    u64 next_encoding{};
    Report capture{};
    QueueReport submissions{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    PostKey post_key{};
    std::array<PostToken, MaxPostOperations> post_tokens{};
    size_t post_count{};
    bool post_borrowed{}, post_closed{};
    PostMergeRootEvidence post_overwrite{};
    PostProxyTransitionProof post_proxy_transition{};
    PostProxyEdgesProof post_proxy_edges{};
    bool post_proxy_lease_joined{};
#endif
};

class Encoder {
public:
    Encoder() = default;
    Encoder(const Encoder&) = delete;
    Encoder& operator=(const Encoder&) = delete;

    void Note(Kind kind, u64 operation = 0) {
#ifdef BB_TEST_SHARED_POST_GRAPH
        Note(kind, operation, {});
#else
        if (id) {
            recorder.Store(id, {Next(), kind, {}, operation});
        }
#endif
    }

#ifdef BB_TEST_SHARED_POST_GRAPH
    void NotePost(PostToken token) {
        NotePost(token, nullptr);
    }

    bool NoteProxyTransition(PostToken token, const PostProxyTransitionProof& transition) {
        return NotePost(token, nullptr, &transition);
    }

    bool NoteProxyEdges(PostToken token, const PostProxyEdgesProof& edges) {
        return NotePost(token, nullptr, nullptr, &edges);
    }
#endif

    // Match the request the producer latched when queuing the marker.
    void Mark(CaptureId capture, Marker marker) {
        if (id && capture == id) {
            recorder.StoreMarker(id, marker, Next());
        }
    }

    // The emitter must have proved disjointness from every watched plane and resource alias.
    void ExcludeOperation() {
        if (id) {
            recorder.Exclude(id);
        }
    }

    void BeginRendering(const vk::RenderingInfo& info) {
        if (!id) {
            return;
        }
        if (info.pNext) {
            recorder.StoreGap(id, Gap::UnjoinedRenderInfo);
        }
        recorder.Store(id, {Next(),
                            Kind::RenderBegin,
                            {.render_area = info.renderArea,
                             .layers = info.layerCount,
                             .view_mask = info.viewMask,
                             .flags = info.flags}});
        const auto record = [&](const vk::RenderingAttachmentInfo& plane,
                                vk::ImageAspectFlagBits aspect, u32 slot) {
            if (plane.pNext || (!plane.imageView && plane.resolveImageView)) {
                recorder.StoreGap(id, Gap::UnjoinedRenderInfo);
            }
            if (!plane.imageView) {
                return;
            }
            Attachment attachment{
                .slot = slot,
                .aspect = aspect,
                .view = plane.imageView,
                .layout = plane.imageLayout,
                .load = plane.loadOp,
                .store = plane.storeOp,
                .resolve_view = plane.resolveImageView,
                .resolve_layout = plane.resolveImageLayout,
                .resolve_mode = plane.resolveMode,
                .render_area = info.renderArea,
                .layers = info.layerCount,
                .view_mask = info.viewMask,
                .flags = info.flags,
            };
            if (plane.loadOp == vk::AttachmentLoadOp::eClear) {
                static_assert(sizeof(attachment.clear_words) == sizeof(plane.clearValue));
                std::memcpy(attachment.clear_words.data(), &plane.clearValue,
                            sizeof(attachment.clear_words));
            }
            recorder.Store(id, {Next(), Kind::RenderAttachment, attachment});
        };
        for (u32 i = 0; i < info.colorAttachmentCount; ++i) {
            record(info.pColorAttachments[i], vk::ImageAspectFlagBits::eColor, i);
        }
        if (info.pDepthAttachment) {
            record(*info.pDepthAttachment, vk::ImageAspectFlagBits::eDepth, 0);
        }
        if (info.pStencilAttachment) {
            record(*info.pStencilAttachment, vk::ImageAspectFlagBits::eStencil, 0);
        }
    }

private:
    friend class ::Vulkan::Scheduler;
    friend class Recorder;
#ifdef BB_TEST_SHARED_POST_GRAPH
    friend class PostOrderFixture;

    bool Note(Kind kind, u64 operation, PostToken token,
              const PostMergeRootEvidence* overwrite = nullptr,
              const PostProxyTransitionProof* transition = nullptr,
              const PostProxyEdgesProof* edges = nullptr) {
        return id && recorder.Store(id, {Next(), kind, {}, operation}, token, overwrite,
                                    transition, edges);
    }

    bool NotePost(PostToken token, const PostMergeRootEvidence* overwrite,
                  const PostProxyTransitionProof* transition = nullptr,
                  const PostProxyEdgesProof* edges = nullptr) {
        if (!id || !token || token.capture != id) {
            return false;
        }
        if (token != expected_post || (overwrite && token.role != PostRole::Merge)) {
            recorder.StoreGap(id, Gap::DuplicatePostOperation);
            return false;
        }
        post_attested = true;
        return Note(Kind::PostOperation, token.operation, token, overwrite, transition, edges);
    }
#endif
    Encoder(Recorder& source, CaptureId target, Position where)
        : recorder{source}, id{target}, base{where} {}

    Position Next() {
        ++base.suborder;
        return base;
    }

    Recorder& recorder = Recorder::Get();
    CaptureId id{};
    Position base{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    PostToken expected_post{};
    bool post_attested{};
#endif
};

inline Encoder Recorder::Encode(const void* scheduler, u64 tick, u32 segment,
                                vk::CommandBuffer buffer) {
    const CaptureId observed = published_id.load(std::memory_order_acquire);
    if (observed == 0) {
        return {};
    }
    std::scoped_lock lock{mutex};
    if (observed != id) {
        return {};
    }
    if (scheduler != owner) {
        AddGap(Gap::ForeignScheduler);
        return {};
    }
    if (tick < first_tick) {
        return {};
    }
    if (in_recorded_closure) {
        AddGap(Gap::ReentrantEncoding);
        return {};
    }
    if (!buffer || tick < expected_tick) {
        AddGap(Gap::UnjoinedBuffer);
        return {};
    }
    return Encoder{*this, id, {tick, segment, buffer, ++next_encoding}};
}

// A worker installs this only while it encodes a real command-buffer chunk.
struct WorkerSegment {
    const void* scheduler;
    u64 tick;
    u32 segment;
    vk::CommandBuffer buffer;
};
inline thread_local const WorkerSegment* worker_segment = nullptr;

inline Encoder EncodeOnWorker(vk::CommandBuffer buffer) {
    auto& recorder = Recorder::Get();
    if (!recorder.Armed()) {
        return {};
    }
    if (worker_segment && worker_segment->buffer == buffer) {
        return recorder.Encode(worker_segment->scheduler, worker_segment->tick,
                               worker_segment->segment, buffer);
    }
    recorder.Unordered(nullptr, Gap::UnjoinedBuffer);
    return {};
}

template <Handling handling, typename Func, typename GetEncoder>
void Run(vk::CommandBuffer buffer, Func& func, GetEncoder&& get_encoder) {
    if constexpr (handling == Handling::NoNativeWrites) {
        func(buffer);
    } else {
        auto encoder = get_encoder();
        struct Restore {
            bool previous;
            ~Restore() {
                in_recorded_closure = previous;
            }
        } restore{in_recorded_closure};
        in_recorded_closure = true;
        if constexpr (handling == Handling::Described) {
            func(buffer, encoder);
        } else {
            encoder.Note(Kind::UnknownRecord);
            func(buffer);
        }
    }
}

} // namespace Vulkan::NativeWriteSuffix

#endif // BB_TEST_NATIVE_WRITE_SUFFIX
