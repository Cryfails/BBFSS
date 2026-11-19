// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <initializer_list>

#include <span>
#ifdef BB_TEST_SHARED_POST_GRAPH
#include "video_core/buffer_cache/post_geometry_witness.h"
#include "video_core/renderer_vulkan/vk_bottle_motion_adapter_t203.h"
#include "video_core/renderer_vulkan/vk_native_write_suffix.h"
#include "video_core/renderer_vulkan/vk_post_image_barriers.h"
#include "video_core/renderer_vulkan/vk_post_proxy_proof.h"
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include "video_core/renderer_vulkan/vk_bottle_cut_present.h"
#endif
#endif
#include "video_core/renderer_vulkan/vk_sewer_motion_present.h"
#ifdef BB_TEST_SHARED_POST_GRAPH
#include "video_core/renderer_vulkan/vk_post_present_retirement.h"
#endif
#include "video_core/texture_cache/image.h"

namespace Vulkan::SewerBridge {

constexpr u64 TonemapHash = 0xccbf44a6;
constexpr auto Color = vk::ImageAspectFlagBits::eColor;

enum class Step { None, Tonemap, UiCopy, DisjointUi, Display };
enum class Planned { Merge, Tonemap, UiCopy, DisplayExpected, Display };

struct Native {
    SewerMotion::Resource res{};
    u64 write{};
    VAddr begin{}, end{};
    const void* backing{};
    VmaAllocation allocation{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    vk::Format format{};
#endif
};

inline bool SameNative(const Native& a, const Native& b) {
    return SewerPresent::SameBacking(a.res, b.res) && a.write == b.write && a.begin == b.begin &&
           a.end == b.end && a.backing == b.backing && a.allocation == b.allocation;
}
inline bool Separate(const Native& a, const Native& b) {
    return a.res.image != b.res.image && a.allocation != b.allocation &&
           (a.end <= b.begin || b.end <= a.begin);
}

#ifdef BB_TEST_SHARED_POST_GRAPH
namespace PostGeometry = VideoCore::PostGeometry;
namespace Graph = BottleAncestry;
namespace Order = NativeWriteSuffix;

struct ProxyStrips {
    vk::Image image{};
    vk::CommandBuffer command{};
    vk::ImageCopy row{}, column{};
    vk::ImageLayout src_layout{}, dst_layout{};
    vk::MemoryBarrier2 before{}, between{}, after{};
    u64 cookie{}, queued_tick{};
    u64 issued_version{}; // Identity of the two actual copies, separate from the prior content.
    bool encoder_note{};
    std::atomic_flag claimed{};
    std::atomic<bool> issued{}, repeated{};

    void Publish(vk::CommandBuffer cmd, vk::Image target, vk::ImageLayout source_layout,
                 vk::ImageLayout destination_layout, const vk::ImageCopy& actual_row,
                 const vk::ImageCopy& actual_column, const vk::MemoryBarrier2& first,
                 const vk::MemoryBarrier2& middle, const vk::MemoryBarrier2& last, u64 version, bool note) {
        if (claimed.test_and_set(std::memory_order_acq_rel)) {
            repeated.store(true, std::memory_order_release);
            return;
        }
        command = cmd;
        image = target;
        row = actual_row;
        column = actual_column;
        src_layout = source_layout;
        dst_layout = destination_layout;
        before = first;
        between = middle;
        after = last;
        encoder_note = note;
        issued_version = version;
        issued.store(true, std::memory_order_release);
    }
};

struct ProxyAlpha {
    PostProxyProof::Key key{};
    PostProxyProof::Lease source;
    Order::PostToken transition_order{}, edge_order{};
    PostProxyProof::BackingCheck before_merge{}, after_coherence_drop{};
    ProxyStrips strips;
    Graph::Proof vendor_color_read_only{}, vendor_output_disjoint{};
    bool clamp_expected{};
};

inline Order::PostMergeImage ScopedProxyImage(const PostProxyProof::Binding& binding, u64 version) {
    if (!binding.IsOwned()) return {};
    const auto& owner = binding.proxy;
    return {binding.image, binding.view, owner.allocator, owner.allocation, owner.memory,
            owner.offset, owner.bytes, binding.incarnation, version, binding.range,
            binding.extent, binding.format, binding.layout, binding.samples};
}

struct AlphaFootprint {
    vk::Offset2D first{}, last{};
    Graph::Proof outside{};
};

inline bool IssuedProxyStripShape(const ProxyAlpha& read) {
    const auto& stripes = read.strips;
    const auto& binding = read.source.binding;
    if (!read.clamp_expected || !stripes.issued.load(std::memory_order_acquire) ||
        stripes.repeated.load(std::memory_order_acquire) ||
        !binding.IsOwned() || !stripes.command || !stripes.queued_tick || !stripes.issued_version ||
        stripes.image != binding.image || binding.extent != vk::Extent2D{1920, 1080}) return false;
    constexpr vk::ImageSubresourceLayers color{Color, 0, 0, 1};
    constexpr vk::ImageCopy row{color, {0, 1078, 0}, color, {0, 1079, 0}, {1920, 1, 1}};
    constexpr vk::ImageCopy column{color, {1918, 0, 0}, color, {1919, 0, 0}, {1, 1080, 1}};
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    return stripes.row == row && stripes.column == column &&
           stripes.src_layout == vk::ImageLayout::eGeneral && stripes.dst_layout == vk::ImageLayout::eGeneral &&
           !stripes.before.pNext && !stripes.between.pNext && !stripes.after.pNext &&
           stripes.before.srcStageMask == Stage::eAllCommands && stripes.before.srcAccessMask == Access::eMemoryWrite &&
           stripes.before.dstStageMask == Stage::eTransfer &&
           stripes.before.dstAccessMask == (Access::eTransferRead | Access::eTransferWrite) &&
           stripes.between.srcStageMask == Stage::eTransfer && stripes.between.srcAccessMask == Access::eTransferWrite &&
           stripes.between.dstStageMask == Stage::eTransfer &&
           stripes.between.dstAccessMask == (Access::eTransferRead | Access::eTransferWrite) &&
           stripes.after.srcStageMask == Stage::eTransfer && stripes.after.srcAccessMask == Access::eTransferWrite &&
           stripes.after.dstStageMask == Stage::eAllCommands &&
           stripes.after.dstAccessMask == (Access::eMemoryRead | Access::eMemoryWrite);
}

inline AlphaFootprint DirectMergeAlphaFootprint(const ProxyAlpha& read, u32 sample_mode, vk::Offset2D center) {
    if ((sample_mode != 1 && sample_mode != 2) || !IssuedProxyStripShape(read)) return {};
    constexpr s32 radius = SewerPresent::Side / 2;
    if (center.x < radius || center.y < radius || center.x >= s32(SewerPresent::Extent.width) - radius ||
        center.y >= s32(SewerPresent::Extent.height) - radius) return {};
    const vk::Offset2D first{center.x - radius, center.y - radius};
    const vk::Offset2D last{center.x + radius, center.y + radius};
    // The known 2:1 dimensions give exact binary quarter-pixel coordinates for ProxyAlpha.
    // Linear touches floor((p + .5) / 2 - .5) and its next texel. Nearest touches p / 2.
    const auto limit = [sample_mode](s32 p, s32 edge, bool upper) {
        const s32 texel = p / 2;
        return std::clamp(sample_mode == 1 ? texel - (p % 2 == 0 ? 1 : 0) + s32(upper) : texel, 0, edge);
    };
    AlphaFootprint out{{limit(first.x, 1919, false), limit(first.y, 1079, false)},
                       {limit(last.x, 1919, true), limit(last.y, 1079, true)}};
    // No downstream draw's sample coordinates are inferred from these direct merge rectangles.
    out.outside = out.last.x < 1919 && out.last.y < 1079 ? Graph::Proof::Known : Graph::Proof::Failed;
    return out;
}

struct PostOrder {
    const void* owner{};
    Order::PostKey key{};
    Order::PostToken merge{};
    std::shared_ptr<ProxyAlpha> proxy_alpha;

    ~PostOrder() { Disarm(); }
    void Disarm() {
        if (const auto id = capture.exchange(0, std::memory_order_acq_rel))
            Order::Recorder::Get().Disarm(owner, id);
    }

    std::atomic<Order::CaptureId> capture{};
};

inline bool MatchedPostSubmission(const Order::PostReceipt& receipt, Order::PostKey key,
                                  Order::PostToken token, const Graph::IssueOrder& actual) {
    const auto& position = receipt.where;
    const auto& submit = receipt.submission;
    return key.request && key.frame && token && actual.command && actual.tick && actual.queue && actual.timeline &&
           receipt.key == key && receipt.token == token &&
           (receipt.phase == Order::PostPhase::Submitted || receipt.phase == Order::PostPhase::Retired) &&
           position.submitted && position.tick == actual.tick && std::bit_cast<u64>(position.buffer) == actual.command &&
           position.encoding && position.encoding <= std::numeric_limits<u32>::max() &&
           submit.result == vk::Result::eSuccess && submit.tick == position.tick &&
           std::bit_cast<u64>(submit.queue) == actual.queue && std::bit_cast<u64>(submit.timeline) == actual.timeline &&
           position.submitted_index < submit.buffer_count && position.submitted_index < submit.buffers.size() &&
           submit.buffers[position.submitted_index].segment == position.segment &&
           submit.buffers[position.submitted_index].buffer == position.buffer;
}

struct PhysicalImage {
    vk::Image image{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    vk::DeviceMemory memory{};
    u64 offset{}, bytes{}, generation{};
    vk::Format format{};
    vk::Extent3D extent{};
    vk::SampleCountFlagBits samples{};
    vk::ImageSubresourceRange range{};

    bool Valid() const {
        return image && allocator && allocation && memory && bytes && generation &&
               offset <= std::numeric_limits<u64>::max() - bytes && range.aspectMask == Color &&
               range.baseMipLevel == 0 && range.levelCount == 1 && range.baseArrayLayer == 0 &&
               range.layerCount == 1 && samples == vk::SampleCountFlagBits::e1 &&
               format != vk::Format::eUndefined && extent.width && extent.height && extent.depth == 1;
    }
    bool operator==(const PhysicalImage&) const = default;
};

inline Graph::Proof PhysicalSeparation(const PhysicalImage& a, const PhysicalImage& b) {
    if (!a.Valid() || !b.Valid() || a.allocator != b.allocator) return Graph::Proof::Unknown;
    if (a.image == b.image || a.allocation == b.allocation ||
        (a.memory == b.memory && a.offset < b.offset + b.bytes && b.offset < a.offset + a.bytes))
        return Graph::Proof::Failed;
    return Graph::Proof::Known;
}

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
inline u32 BottleRejections(std::initializer_list<bool> flags) {
    u32 mask = 0;
    u32 bit = 1;
    for (const bool rejected : flags) {
        if (rejected) mask |= bit;
        bit <<= 1;
    }
    return mask;
}

struct BottleDrawScope {
    u32 original_mask{}, full_mask{};
    u32 index_count{}, instances{}, viewport_count{}, scissor_count{}, color_mask{}, logic_op{};
    vk::Viewport viewport{};
};

struct BottleDisplay {
    BottleCutPresent::Scene scene{};
    BottleCutPresent::Regions regions{};
    std::optional<BottleCutPresent::RawSearch> raw;
    bool draw_scope_reported{};
    u8 redirect_scope_reported{}, override_scope_reported{};
    u64 raw_close_after_offer{};
    std::shared_ptr<PostOrder> order;
    Order::PostToken display_order{}, barrier_order{}, postprocess_order{};
    PhysicalImage ui{}, target{};
    VAddr address{};
    vk::ImageView attachment{};
    BottleMotion203::Slot requested_slot{};
    vk::Pipeline pipeline{};
    vk::PipelineLayout pipeline_layout{};
    u64 shader{}, permutation{};
    BottleCutPresent::Override display{};
    u64 write{};
    std::atomic<u64> encoded{};

    std::mutex mutex;
    bool offered{}, consumed{}, cancelled{}, renderer_checked{}, app_checked{}, completed{};
    bool renderer_fenced{}, renderer_submitted{};
    Order::Position renderer_position{};
    const char* app_refusal{};
    std::optional<BottleCutPresent::RawFenced> frame;

    struct Completion {
        std::optional<BottleCutPresent::RawFenced> frame;
        Order::Position position{};
        const char* refusal{};
        bool submitted{}, fenced{};
    };

    std::optional<Completion> TakeCompletion() {
        std::lock_guard lock(mutex);
        if (completed || !renderer_checked || !app_checked) return {};
        completed = true;
        return Completion{std::move(frame), renderer_position, app_refusal, renderer_submitted, renderer_fenced};
    }

    bool Consume(const BottleCutPresent::Scene& actual_scene, const BottleCutPresent::Override& actual,
                 u64 generation, u64 serial) {
        std::lock_guard lock(mutex);
        if (cancelled || !offered || consumed || actual_scene != scene || target.generation != generation ||
            write != serial || !BottleCutPresent::Compatible(display, actual)) return false;
        consumed = true;
        return true;
    }

    void Cancel() {
        std::lock_guard lock(mutex);
        cancelled = true;
    }

    bool Matches(const BottleCutPresent::Result& result, const BottleCutPresent::RawFenced& raw) const {
        if (!consumed || !result.fenced || result.scene != scene || raw.scene != scene ||
            result.raw_search != bool(this->raw) || raw.raw != this->raw ||
            result.present_serial != raw.attempt.serial ||
            !raw.source.Valid() || !raw.attempt.Valid() || raw.source.ready != display.draw_timeline ||
            raw.source.ready_tick < display.draw_tick || !BottleCutPresent::Compatible(display, raw.display) ||
            raw.display.draw_tick != display.draw_tick || raw.display_attachment != attachment ||
            raw.display_generation != target.generation || raw.display_write != write ||
            raw.display_allocation != reinterpret_cast<u64>(target.allocation) || raw.regions.count != regions.count ||
            regions.count > regions.points.size()) return false;
        for (u32 i = 0; i < regions.count; ++i) {
            if (raw.regions.points[i].role != regions.points[i].role ||
                raw.regions.points[i].centre != regions.points[i].centre) return false;
        }
        return true;
    }
};
#endif

inline bool NativeUiSourceRow(const PostImageBarriers::Row& row, const PhysicalImage& source,
                              u64 queue, u64 scheduler, u64 first_tick, u64 last_tick) {
    using Layout = vk::ImageLayout;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    return source.Valid() && row.backing.Known() && row.encoded && row.command && row.cookie &&
           row.status == PostImageBarriers::Status::NativeImage && row.scheduler == scheduler && row.queue == queue &&
           row.queued_tick >= first_tick && row.queued_tick <= last_tick &&
           row.image == source.image && row.range == source.range && row.backing.image == source.image &&
           row.backing.uid == source.generation && row.backing.format == source.format &&
           row.backing.samples == source.samples && row.backing.allocation == reinterpret_cast<u64>(source.allocation) &&
           row.backing.memory == source.memory && row.backing.offset == source.offset && row.backing.bytes == source.bytes &&
           !row.chained && !row.global && row.old_layout != Layout::eUndefined &&
           row.new_layout == Layout::eTransferSrcOptimal &&
           (row.dst_stage & (Stage::eTransfer | Stage::eAllCommands)) &&
           (row.dst_access & (Access::eTransferRead | Access::eMemoryRead));
}

enum class LocalEdge : u8 { UiDiscard, UiAttachment, DisplayDiscard, UiSample, Count };
enum class EdgeState : u8 { Empty, Writing, Issued, Repeated };

struct LocalEmission {
    vk::ImageMemoryBarrier2 barrier{};
    vk::CommandBuffer command{};
    std::atomic<EdgeState> state{EdgeState::Empty};

    void Observe(vk::CommandBuffer cmd, const vk::ImageMemoryBarrier2& actual) {
        auto empty = EdgeState::Empty;
        if (!state.compare_exchange_strong(empty, EdgeState::Writing, std::memory_order_acq_rel)) {
            state.store(EdgeState::Repeated, std::memory_order_release);
            return;
        }
        barrier = actual;
        command = cmd;
        auto writing = EdgeState::Writing;
        state.compare_exchange_strong(writing, EdgeState::Issued, std::memory_order_release);
    }
};

inline Graph::Proof BarrierShape(LocalEdge edge, const LocalEmission& emitted, const PhysicalImage& owner) {
    const auto state = emitted.state.load(std::memory_order_acquire);
    if (state == EdgeState::Repeated) return Graph::Proof::Failed;
    if (state != EdgeState::Issued || !owner.Valid()) return Graph::Proof::Unknown;
    const auto& b = emitted.barrier;
    if (!emitted.command || b.pNext || b.image != owner.image || b.subresourceRange != owner.range ||
        b.srcQueueFamilyIndex != b.dstQueueFamilyIndex) return Graph::Proof::Failed;
    using Layout = vk::ImageLayout;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    bool shape = false;
    switch (edge) {
    case LocalEdge::UiDiscard:
        shape = b.oldLayout == Layout::eUndefined && b.newLayout == Layout::eTransferDstOptimal &&
                b.srcStageMask == Stage::eAllCommands && b.dstStageMask == Stage::eTransfer &&
                b.srcAccessMask == (Access::eMemoryRead | Access::eMemoryWrite) &&
                b.dstAccessMask == Access::eTransferWrite;
        break;
    case LocalEdge::UiAttachment:
        shape = b.oldLayout == Layout::eTransferDstOptimal && b.newLayout == Layout::eGeneral &&
                b.srcStageMask == Stage::eTransfer && b.dstStageMask == Stage::eColorAttachmentOutput &&
                b.srcAccessMask == Access::eTransferWrite &&
                b.dstAccessMask == (Access::eColorAttachmentRead | Access::eColorAttachmentWrite);
        break;
    case LocalEdge::DisplayDiscard:
        shape = b.oldLayout == Layout::eUndefined && b.newLayout == Layout::eGeneral &&
                b.srcStageMask == Stage::eAllCommands && b.dstStageMask == Stage::eColorAttachmentOutput &&
                !b.srcAccessMask && b.dstAccessMask == Access::eColorAttachmentWrite;
        break;
    case LocalEdge::UiSample:
        shape = b.oldLayout == Layout::eGeneral && b.newLayout == Layout::eGeneral &&
                b.srcStageMask == Stage::eColorAttachmentOutput && b.dstStageMask == Stage::eAllCommands &&
                b.srcAccessMask == Access::eColorAttachmentWrite && b.dstAccessMask == Access::eShaderRead;
        break;
    case LocalEdge::Count: break;
    }
    return shape ? Graph::Proof::Known : Graph::Proof::Failed;
}

struct AttachmentRequest {
    vk::ImageView view{};
    vk::ImageLayout layout{};
    vk::Extent2D extent{};
    u32 layers{}, color_count{};
    bool clear{};
    // The stock RenderState has no resolve attachment. Actual pass and coverage are separate.
};

struct TerminalDraw {
    AttachmentRequest color{};
    BottleMotion203::Slots slots{};
    vk::Pipeline pipeline{};
    vk::PipelineLayout layout{};
    vk::ImageView source_view{};
    vk::Format source_format{};
    vk::ComponentMapping source_mapping{};
    u64 shader{}, permutation{}, scene{};
    Graph::Proof requested_slot{}, footprint{};
    bool ordinary{};
};

struct TerminalState {
    PhysicalImage source{}, ui{}, display{};
    std::array<LocalEmission, static_cast<u32>(LocalEdge::Count)> emissions{};
    TerminalDraw draw{};
    SewerPresent::CandidateIdentity issued_candidate{};
    std::atomic<u64> blit_write{};
    u64 runtime_window{};
    Graph::Proof runtime_emission{};
    Graph::Proof source_runtime{}, separate_local_order{}, descriptor_committed{}, app_dependency{};

    LocalEmission& Barrier(LocalEdge edge) { return emissions[static_cast<u32>(edge)]; }
    const LocalEmission& Barrier(LocalEdge edge) const { return emissions[static_cast<u32>(edge)]; }
};

inline bool SameTerminalRegions(const SewerPresent::Regions& a, const SewerPresent::Regions& b) {
    if (a.count != b.count || a.count > a.points.size()) return false;
    for (u32 i = 0; i < a.count; ++i)
        if (a.points[i].role != b.points[i].role || a.points[i].centre != b.points[i].centre) return false;
    return true;
}

inline bool MatchesAppFrame(const SewerPresent::Result& result, const SewerPresent::FencedFrame& frame,
                            const SewerPresent::CandidateIdentity& candidate, const SewerPresent::Regions& regions) {
    return result.fenced && result.present_serial && result.present_serial == frame.serial &&
           SewerPresent::SameKey(result.key, candidate.merge.key) && frame.Valid() &&
           frame.identity.Same(candidate) && SameTerminalRegions(regions, frame.regions);
}

struct JoinedBytes {
    PostGeometry::Ticket ticket{};
    PostGeometry::FinalBinding binding{};
    u32 native_slot{}, descriptor_write{}, push_index{}, adjust{}, member{}, member_bytes{};
    vk::DescriptorBufferInfo descriptor{};
    PostGeometry::Route route{PostGeometry::Route::None};
    PostGeometry::State state{PostGeometry::State::NoCopy};
};

struct SampleState {
    std::array<u32, 4> sharp{};
    vk::Sampler handle{};
    u32 binding{};
    float lod_bias{};
};

struct PostDraw {
    PostGeometry::Key geometry_key{};
    std::shared_ptr<PostGeometry::Capture> geometry;
    PostGeometry::DrawWatch* watch{}; // DrawRecord owner only. Closed before deferred consumption.
    std::array<JoinedBytes, PostGeometry::MaxSlices> bytes{};
    std::array<vk::VertexInputAttributeDescription2EXT, Graph::MaxInputs> attributes{};
    std::array<vk::VertexInputBindingDescription2EXT, Graph::MaxInputs> bindings{};
    BottleMotion203::Slots slots{};
    std::array<Native, Graph::MaxInputs> slot_images{};
    std::array<SampleState, Graph::MaxInputs> samplers{};
    Native destination{};
    AttachmentRequest attachment{};
    Order::PostToken native_order{};
    VideoCore::ImageId color_id{};
    vk::ImageView output{};
    vk::ImageLayout output_layout{};
    vk::Format output_format{};
    vk::Rect2D scissor{};
    vk::Viewport viewport{};
    u64 ps{}, vs{}, ps_permutation{}, vs_permutation{}, pipeline{}, tick{};
    u32 count{}, instances{}, first_instance{}, attribute_count{}, binding_count{};
    u32 width{}, height{}, scissor_count{}, viewport_count{}, sampler_count{}, omitted_samplers{};
    u32 write_mask{}, logic_op{}, topology{};
    s64 first_vertex{};
    vk::IndexType index_type{};
    bool indexed{}, original{}, camera{}, full_write{}, clear{}, blends{}, snapshots_complete{};
    bool storage_or_attachment_scope_unknown{}, depth_test{}, stencil_test{}, primitive_restart{};
    std::atomic<u64> encoded{};
};

struct PostCompletion {
    std::optional<SewerPresent::FencedFrame> frame;
    std::optional<SewerPresent::RenderRetirement> display;
    const char* refusal{};
};

struct PostState {
    BottleMotion203::PostPacket packet;
    std::shared_ptr<PostGeometry::Capture> geometry;
    std::shared_ptr<PostOrder> order;
    static constexpr u64 UiOperation = Order::MaxPostOperations - 5;
    static constexpr u64 DisplayOperation = Order::MaxPostOperations - 4;
    static constexpr u64 PriorProxyOperation = Order::MaxPostOperations - 3;
    static constexpr u64 ProxyClampOperation = Order::MaxPostOperations - 2;
    static constexpr u64 PrepareBarrierOperation = Order::MaxPostOperations - 1;
    static constexpr u64 PreparePostprocessOperation = Order::MaxPostOperations;
    // The two terminal slots are for the same renderer's prepared-frame owner.
    std::array<std::shared_ptr<PostDraw>, Order::MaxPostOperations - 7> draws{};
    Order::PostToken ui_order{}, display_order{};
    bool display_retirement_scheduled{};
    Graph::ImageVersion merge{};
    TerminalState terminal{};
    Native ui_source{};
    Graph::ImageVersion ui_version{};
    vk::Image ui_image{}, blit_source{};
    vk::ImageLayout blit_source_layout{};
    vk::ImageBlit blit{};
    vk::Extent2D blit_source_extent{}, ui_extent{};
    std::atomic<u64> ui_encoded{}, display_encoded{};
    std::atomic<u64> display_tick{};
    u64 merge_command{}, ui_tick{};
    u32 count{}, omitted{};
    bool ui_ordinary{}, ui_after_writer{};
    std::mutex retirement_mutex;
    bool graph_retired{}, graph_ready{}, renderer_checked{}, presentation_received{}, completion_taken{};
    const char* application_refusal{};
    std::optional<SewerPresent::FencedFrame> raw_frame;
    std::optional<SewerPresent::RenderRetirement> render;

    std::optional<PostCompletion> TakeCompletion() {
        std::lock_guard lock(retirement_mutex);
        if (!graph_retired || !renderer_checked || !presentation_received || completion_taken) return {};
        completion_taken = true;
        const char* refusal = application_refusal;
        if (!refusal && !render) refusal = "shared-post-display-submission-unproved";
        if (!refusal && (!graph_ready || !render->lineage)) refusal = "shared-postgraph-unproved";
        return PostCompletion{std::move(raw_frame), std::move(render), refusal};
    }
};
#endif

struct Trace {
    std::shared_ptr<SewerMotion::Checkpoint> checkpoint;
    const SewerMotion::MergeToken merge;
    const vk::CommandBuffer command;
    const Native hdr;
    const SewerPresent::Regions regions;

    Planned planned = Planned::Merge;
    Native ldr{};
    vk::Image ui{};
    VmaAllocation ui_allocation{};
    u64 ui_generation{};
    vk::ImageView hdr_sample{};
    VAddr display_address{};
    vk::ImageView redirect{};
    u64 tonemap_tick{};
    unsigned ui_expected{};
    std::atomic<unsigned> ui_encoded{};
    std::atomic<Step> encoded{Step::None};
    std::atomic<const char*> encoded_failure{};
    bool offered{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::unique_ptr<PostState> post;
#endif

    Trace(std::shared_ptr<SewerMotion::Checkpoint> sample, vk::CommandBuffer cb,
          Native target, SewerPresent::Regions rois)
        : checkpoint(std::move(sample)), merge(checkpoint->merge), command(cb), hdr(target), regions(rois) {}

    bool Open() const {
        return !offered && !checkpoint->refusal.load(std::memory_order_acquire) &&
               !checkpoint->PresentationRetired();
    }
    void Stop(const char* reason) {
        if (Open()) checkpoint->FinishPresentation(false, reason);
    }
    void EncoderRefusal(const char* reason) {
        const char* empty = nullptr;
        encoded_failure.compare_exchange_strong(empty, reason);
    }
    void Encode(Step next, vk::CommandBuffer cb, u64 tick) {
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (post) {
            if (next == Step::Display && cb && tick) {
                post->display_tick.store(tick, std::memory_order_relaxed);
                post->display_encoded.store(std::bit_cast<u64>(cb), std::memory_order_release);
            } else if (next == Step::DisjointUi && cb && tick) {
                ui_encoded.fetch_add(1, std::memory_order_release);
            }
            return; // Raw candidate only. The graph requires its own actual submitted order.
        }
#endif
        if (!cb || cb != command || tick != merge.tick) {
            EncoderRefusal("unproved-render-segment-or-tick");
            return;
        }
        if (next == Step::DisjointUi) {
            if (encoded.load(std::memory_order_acquire) != Step::UiCopy)
                EncoderRefusal("disjoint-ui-encoded-out-of-order");
            else ui_encoded.fetch_add(1, std::memory_order_release);
            return;
        }
        auto previous = next == Step::Tonemap ? Step::None :
                        next == Step::UiCopy ? Step::Tonemap : Step::UiCopy;
        if (!encoded.compare_exchange_strong(previous, next, std::memory_order_acq_rel))
            EncoderRefusal("display-chain-encoded-out-of-order");
    }
    const char* EncoderFailure() const {
        if (const auto error = encoded_failure.load(std::memory_order_acquire)) return error;
        if (encoded.load(std::memory_order_acquire) != Step::Display ||
            ui_encoded.load(std::memory_order_acquire) != ui_expected) return "display-producer-not-encoded";
        return nullptr;
    }
};

struct Draw {
    std::shared_ptr<Trace> trace;
    Step step{};
    u64 tick{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    Order::PostToken native_order{};
#endif
    void Encoded(vk::CommandBuffer cb) const {
        if (trace) trace->Encode(step, cb, tick);
    }
};

struct DrawFacts {
    u64 scene{}, ps{};
    VideoCore::ImageId color_id{};
    vk::ImageView output{};
    vk::ImageLayout layout{};
    std::span<const vk::DescriptorImageInfo> inputs;
    std::span<const VideoCore::ImageId> images;
    vk::Rect2D scissor{};
    bool original{}, full_write{}, disjoint_capable{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    AttachmentRequest attachment{};
    BottleMotion203::Slots display_slots{};
    vk::Pipeline pipeline{};
    vk::PipelineLayout pipeline_layout{};
    u64 fragment_permutation{};
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    BottleDrawScope bottle_scope{};
#endif
#endif
};

// Private redirected image ownership. Revocation accompanies every subsequent redirect to the
// actual entry. A display-handle match can never consume a later generation or a repeated write.
struct Epoch {
    const SewerPresent::Override display;
    const u64 generation, write;
    const vk::ImageView attachment;
#ifdef BB_TEST_SHARED_POST_GRAPH
    const u64 allocation;
#endif
    const std::shared_ptr<Trace> trace;
    std::mutex mutex;
    bool valid = true;

    Epoch(SewerPresent::Override target, u64 gen, u64 seq, vk::ImageView view,
          std::shared_ptr<Trace> owner
#ifdef BB_TEST_SHARED_POST_GRAPH
          , u64 alloc
#endif
          )
        : display(target), generation(gen), write(seq), attachment(view),
#ifdef BB_TEST_SHARED_POST_GRAPH
          allocation(alloc),
#endif
          trace(std::move(owner)) {}

    bool Consume(const SewerPresent::Override& actual, u64 gen, u64 seq) {
        std::lock_guard lock(mutex);
        if (!valid || actual.address != display.address || actual.image != display.image ||
            actual.format != display.format || actual.extent != display.extent ||
            actual.draw_timeline != display.draw_timeline || actual.draw_tick < display.draw_tick ||
            generation != gen || write != seq) return false;
        valid = false;
        return true;
    }
    void Cancel() {
        std::lock_guard lock(mutex);
        valid = false;
    }
};

// Keep a one-texel margin around the 25x25 display patch for the ordinary 1:1 sampling footprint.
inline bool Outside(vk::Rect2D rectangle, const SewerPresent::Regions& regions) {
    if (!rectangle.extent.width || !rectangle.extent.height) return false;
    const auto x1 = s64(rectangle.offset.x) + rectangle.extent.width;
    const auto y1 = s64(rectangle.offset.y) + rectangle.extent.height;
    constexpr s32 radius = SewerPresent::Side / 2 + 1;
    for (u32 i = 0; i < regions.count; ++i) {
        const auto p = regions.points[i].centre;
        if (rectangle.offset.x <= p.x + radius && x1 > p.x - radius &&
            rectangle.offset.y <= p.y + radius && y1 > p.y - radius) return false;
    }
    return true;
}

inline std::optional<vk::Offset2D> OpaquePoint(const CameraMotion::Matrices& camera,
                                                SewerMotion::Vec3 p) {
    const auto axis = [&](u32 row) {
        const auto* m = &camera.view[4 * row];
        return m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3];
    };
    const float z = axis(2);
    if (!(z > .1f && z < 45.f)) return {};
    const float x = (axis(0) * camera.proj[0] / z + 1.f) * 1920.f;
    const float y = (axis(1) * camera.proj[1] / z + 1.f) * 1080.f;
    if (!(x >= 12.f && x < 3828.f && y >= 12.f && y < 2148.f)) return {};
    return vk::Offset2D{s32(x), s32(y)};
}

} // namespace Vulkan::SewerBridge
