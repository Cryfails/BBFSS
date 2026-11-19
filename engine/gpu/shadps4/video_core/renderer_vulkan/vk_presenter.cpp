// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "common/debug.h"
#include "common/elf_info.h"
#include "common/io_file.h"
#include "common/path_util.h"
#include "common/singleton.h"
#include "core/debug_state.h"
#include "core/emulator_settings.h"
#include "sdl_window.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/renderdoc.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "bbport_overlay.h"
#include "bbport_live_knobs.h"
#include "bbport_settings.h"
#include "bbport_timeline.h"
#include "bbport_toggles.h"
#include "face_shot.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "lantern_anti_lag.h"
#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"
#include "video_core/renderer_vulkan/vk_presenter.h"
#include "video_core/renderer_vulkan/vk_sewer_motion_present.h"
#ifdef BB_TEST_SHARED_POST_GRAPH
#include "video_core/renderer_vulkan/vk_post_present_retirement.h"
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include "video_core/renderer_vulkan/vk_bottle_display_evidence_b182.h"
#include "video_core/renderer_vulkan/vk_bottle_cut_present.h"
#endif
#include "engine/loading.h"
#include <bit>
#include <cstddef>
#include <fmt/format.h>
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/texture_cache/image.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <csetjmp>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <optional>
#include <memory>
#include <span>
#include <sstream>
#include <system_error>
#include <thread>
#include <vector>
#include <vk_mem_alloc.h>

namespace Vulkan {
#ifdef BB_TEST_SHARED_POST_GRAPH

namespace SewerPresent {
namespace {
void CompleteCandidate(Candidate& proof, const char* why, u64 serial,
                       std::optional<FencedFrame> frame = {}) {
    auto complete = std::exchange(proof.complete, {});
    proof.lease.reset();
    const auto& key = proof.merge.key;
    if (complete) {
        const bool fenced = frame.has_value();
        if (why) {
            fmt::print("[sewer-motion] event=final-refused request={} checkpoint={} frame={} why={}\n",
                       key.request, key.checkpoint, key.frame, why);
        }
        complete({key, fenced, why, serial}, std::move(frame));
    }
}

class PendingCandidate {
public:
    bool Offer(Candidate& next) {
        std::lock_guard lock(mutex);
        const auto& key = next.merge.key;
        const bool fresh = !accepted || (accepted->request == key.request &&
            accepted->loading == key.loading && accepted->generation == key.generation &&
            accepted->enabled == key.enabled && key.frame > accepted->frame && key.scene > accepted->scene &&
            key.checkpoint > accepted->checkpoint);
        if (pending || !lease.expired() || !fresh) return false;
        next.lease = std::make_shared<CandidateLease>();
        lease = next.lease;
        accepted = key;
        pending = std::move(next);
        return true;
    }

    std::optional<Candidate> Take(u32 frame) {
        std::lock_guard lock(mutex);
        if (!pending || pending->merge.key.frame > frame) return {};
        return std::exchange(pending, {});
    }

    void Cancel() {
        std::optional<Candidate> cancelled;
        {
            std::lock_guard lock(mutex);
            cancelled = std::exchange(pending, {});
        }
        if (cancelled) CompleteCandidate(*cancelled, "presenter-shutdown-before-prepare", 0);
    }

private:
    std::mutex mutex;
    std::optional<Candidate> pending;
    std::optional<SewerMotion::Key> accepted;
    std::weak_ptr<const CandidateLease> lease;
};

PendingCandidate& Candidates() {
    static PendingCandidate candidates;
    return candidates;
}
} // namespace

bool OfferDisplayCandidate(Candidate proof) {
    if (!SewerMotion::Enabled()) return false;
    const auto& key = proof.merge.key;
    const auto current = SewerMotion::CurrentMerge(proof.merge.timeline, key.frame, key.loading, key.generation);
    if (!current || !proof.Valid(*current)) {
        CompleteCandidate(proof, "display-candidate-merge-or-identity", 0);
        return false;
    }
    const auto sample = SewerMotion::Find(proof.merge.timeline, key.frame, key.loading, key.generation);
    if (!sample) {
        CompleteCandidate(proof, "display-candidate-scene-expired", 0);
        return false;
    }
    for (u32 i = 0; i < proof.regions.count; ++i) {
        const auto [role, xy] = proof.regions.points[i];
        const auto index = unsigned(role);
        if (index > unsigned(Role::Dry)) continue;
        const auto& q = sample->pose.output[index];
        if (xy != vk::Offset2D{s32(q[0]), s32(q[1])}) {
            CompleteCandidate(proof, "display-candidate-anchor-mismatch", 0);
            return false;
        }
    }
    if (Candidates().Offer(proof)) return true;
    CompleteCandidate(proof, "display-candidate-repeated-or-capacity", 0);
    return false;
}

bool PublishFinal(FencedFrame frame, const RenderRetirement& render) {
    const auto& identity = frame.identity;
    const auto& key = identity.merge.key;
    if (!render.Joins(frame)) {
        fmt::print("[sewer-motion] event=final-refused request={} checkpoint={} frame={} "
                   "why=postgraph-render-retirement-unjoined\n", key.request, key.checkpoint, key.frame);
        return false;
    }
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    const auto& r = frame.resources;
    const auto* wait = r.present.Wait(frame.source.ready, frame.source.ready_tick);
    const auto* acquire = r.present.Wait(frame.acquire, 1);
    fmt::print("[sewer-motion] event=final-resources request={} checkpoint={} frame={} "
               "source_read={} draw_order={} blit_source={} app_submit={} same_queue_barrier={} "
               "direct_transfer_wait={} draw_wait_stages={:#x} acquire_wait_stages={:#x} "
               "prepare_submit={} app_submit_order={}\n",
               key.request, key.checkpoint, key.frame, r.SourceRead(identity),
               r.DrawOrder(frame.source.ready, frame.source.ready_tick), r.BlitSource(frame.source),
               r.AppSubmission(frame.source, frame.acquire, frame.swap_ready, frame.present_timeline,
                               frame.present_tick),
               r.SameQueueBarrier(frame.source), r.TransferWait(frame.source),
               wait ? u32(VkPipelineStageFlags(wait->stages)) : 0,
               acquire ? u32(VkPipelineStageFlags(acquire->stages)) : 0, r.prepare.order, r.present.order);
    if (!JoinsResources(frame, render)) {
        fmt::print("[sewer-motion] event=final-refused request={} checkpoint={} frame={} "
                   "why=ordinary-present-resource-dependency-unjoined\n",
                   key.request, key.checkpoint, key.frame);
        return false;
    }
#endif
    const auto raw = [](auto handle) {
        return std::bit_cast<u64>(static_cast<typename decltype(handle)::CType>(handle));
    };
    const auto& source = frame.source;
    fmt::print("[sewer-motion] event=final-fenced request={} checkpoint={} frame={} scene={} "
               "present_serial={} draw_tick={} ready_tick={} display={:x}/{:x} display_gen={} "
               "display_write={} merge_write={} tonemap_write={} pp_input={:x} pp_format={} "
               "prepared={:x}/{:x} prepared_gen={} ready_sem={:x} fence={:x} "
               "present_sem={:x} present_tick={} swap_ready={:x} submit_ns={} result_ns={} "
               "swap_epoch={} swap={:x} swap_index={} swap_image={:x} "
               "format=bgra8-unorm colorspace=srgb size=3840x2160 mip=0 layer=0 regions={} "
               "display_alloc={:x} acquire={:x} slot={} render_submit={} render_cmd={:x} render_incarnation={} "
               "render_segment={} render_ordinal={} render_fence_tick={}\n",
               key.request, key.checkpoint, key.frame, key.scene, frame.serial, identity.display.draw_tick,
               source.ready_tick, raw(identity.display.image), raw(identity.attachment), identity.generation,
               identity.write, identity.merge.write, render.tonemap_write, raw(frame.pp_input), u32(frame.pp_format),
               raw(source.image), raw(source.view), source.frame_generation, raw(source.ready), raw(source.fence),
               raw(frame.present_timeline), frame.present_tick, raw(frame.swap_ready), frame.submit_ns, frame.result_ns,
               source.swap_generation, raw(frame.swap), frame.swap_index, raw(frame.swap_image), frame.regions.count,
               identity.allocation, raw(frame.acquire), frame.slot, render.submission, raw(render.command), render.incarnation,
               render.segment, render.ordinal, render.completed_tick);
    std::array<char, 2 * PatchBytes + 1> words{};
    constexpr char hex[] = "0123456789abcdef";
    for (u32 i = 0; i < frame.regions.count; ++i) {
        const auto [role, centre] = frame.regions.points[i];
        for (u32 b = 0; b < PatchBytes; ++b) {
            const auto value = std::to_integer<unsigned>(frame.bytes[i * PatchBytes + b]);
            words[b * 2] = hex[value >> 4];
            words[b * 2 + 1] = hex[value & 15u];
        }
        fmt::print("[sewer-motion] event=final-patch request={} checkpoint={} frame={} present_serial={} "
                   "role={} centre={},{} side={} bgra={}\n",
                   key.request, key.checkpoint, key.frame, frame.serial, unsigned(role),
                   centre.x, centre.y, Side, words.data());
    }
    return true;
}
} // namespace SewerPresent
#endif

#ifdef BB_TEST_POST_PRESENT_RESOURCES
namespace PostPresentResources {
namespace {
ResourceImage PreparedResource(const Frame& frame, u64 incarnation, vk::Format format) {
    return {frame.image, frame.image_view, std::bit_cast<u64>(frame.allocation),
            frame.post_present_backing, incarnation, format, {frame.width, frame.height}};
}

struct ResourceCapture {
    ResourceCapture(NativeWriteSuffix::PostKey key, OrderTokens tokens)
        : key{key}, tokens{tokens} {}

    explicit ResourceCapture(const SewerPresent::Candidate& candidate)
        : ResourceCapture({candidate.merge.key.request, u64(candidate.merge.key.checkpoint), candidate.merge.key.frame},
                          {candidate.display_order, candidate.prepare_barrier_order,
                           candidate.prepare_postprocess_order}) {}

    bool ValidTokens() const { return tokens.Valid(); }

    void ObservePrepare(const PostPresentSubmitObservation& actual, Scheduler& scheduler, u64 expected_tick) {
        if (actual.key != key || actual.scheduler != &scheduler || actual.tick != expected_tick) return;
        facts.prepare = DriverSubmission::Copy(actual.input, actual.tick, actual.ordered, actual.segments,
                                               facts.postprocess_cmd);
        if (ValidTokens()) {
            const auto read = [&](NativeWriteSuffix::PostToken token) {
                NativeWriteSuffix::PostReceipt receipt{};
                return scheduler.ReadPostNativeOperation(token, receipt)
                    ? ResourcePosition::From(receipt, token, key) : ResourcePosition{};
            };
            facts.display_order = read(tokens.display);
            facts.barrier_order = read(tokens.barrier);
            facts.postprocess_order = read(tokens.postprocess);
        }
        prepare_observed.store(true, std::memory_order_release);
    }

    void ObservePresent(const PostPresentSubmitObservation& actual, Scheduler& scheduler, u64 expected_tick) {
        if (actual.key != key || actual.scheduler != &scheduler || actual.tick != expected_tick) return;
        facts.present = DriverSubmission::Copy(actual.input, actual.tick, actual.ordered, actual.segments,
                                               facts.blit_cmd);
        present_observed.store(true, std::memory_order_release);
    }

    FrameResources Fenced(const ResourceImage& retired_target, bool presented) const {
        // Each scheduler publishes only the fields produced on its own path.
        // An absent observation cannot be replaced by the planned SubmitInfo.
        const bool prepare_known = prepare_observed.load(std::memory_order_acquire);
        const bool present_known = present_observed.load(std::memory_order_acquire);
        auto retired = prepare_known && present_known ? facts : FrameResources{};
        retired.key = key;
        if (prepare_known && !present_known) retired.prepare = facts.prepare;
        if (present_known && !prepare_known) retired.present = facts.present;
        retired.retired_target = retired_target;
        retired.app_present = presented;
        retired.frame_fenced = true;
        return retired;
    }

    NativeWriteSuffix::PostKey key;
    OrderTokens tokens;
    std::atomic_bool prepare_observed{}, present_observed{};
    FrameResources facts;
};

void NotePreparedTransfer(ResourceCapture& capture, vk::CommandBuffer cmd, vk::Image swap,
                          const vk::ImageBlit& blit, const vk::ImageMemoryBarrier& barrier,
                          vk::PipelineStageFlags before, vk::PipelineStageFlags after) {
    auto& r = capture.facts;
    r.blit_cmd = cmd;
    r.swap = swap;
    r.blit = blit;
    r.target_read = {
        .srcStageMask = vk::PipelineStageFlags2{VkPipelineStageFlags(before)},
        .srcAccessMask = vk::AccessFlags2{VkAccessFlags(barrier.srcAccessMask)},
        .dstStageMask = vk::PipelineStageFlags2{VkPipelineStageFlags(after)},
        .dstAccessMask = vk::AccessFlags2{VkAccessFlags(barrier.dstAccessMask)},
        .oldLayout = barrier.oldLayout,
        .newLayout = barrier.newLayout,
        .srcQueueFamilyIndex = barrier.srcQueueFamilyIndex,
        .dstQueueFamilyIndex = barrier.dstQueueFamilyIndex,
        .image = barrier.image,
        .subresourceRange = barrier.subresourceRange,
    };
    r.blit_encoded = true;
}
} // namespace
} // namespace PostPresentResources

#endif
struct SewerPresent::Capture {
    explicit Capture(Issued value) : proof(std::move(value)) {}
#ifdef BB_TEST_SHARED_POST_GRAPH
    explicit Capture(Candidate value, u32 frame_slot) : candidate(std::move(value)), slot(frame_slot) {}
#endif
    ~Capture() {
        if (buffer) vmaDestroyBuffer(allocator, buffer, allocation);
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (candidate && candidate->complete)
            CompleteCandidate(*candidate, refusal ? refusal : "present-abandoned-before-submit", serial);
#endif
        if (proof.complete) Finish(proof, false, refusal ? refusal : "present-abandoned-before-submit", serial);
    }

    Issued proof;
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::optional<Candidate> candidate;
    u32 slot{};
    vk::Semaphore acquire{};
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    std::shared_ptr<PostPresentResources::ResourceCapture> resources;
#endif
    const Regions& CaptureRegions() const { return candidate ? candidate->regions : proof.regions; }
    const Override& CapturedDisplay() const { return candidate ? candidate->display : proof.display; }
    void FailCandidate(const char* why) {
        if (candidate) CompleteCandidate(*candidate, why, serial);
    }
#endif
    PresentSource source{};
    vk::ImageView pp_input{};
    vk::Format pp_input_format{};
    std::atomic<bool> pp_encoded{};
    vk::SwapchainKHR swap{};
    vk::Image swap_image{};
    vk::Semaphore present_timeline{}, swap_ready{};
    u64 serial{}, submit_ns{}, result_ns{}, present_tick{};
    u32 swap_index{};
    bool presented{};
    const char* refusal{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    VkBuffer buffer{};
    const std::byte* mapped{};

    bool Allocate(VmaAllocator vma) {
        allocator = vma;
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
#ifdef BB_TEST_SHARED_POST_GRAPH
                                     .size = CaptureRegions().count * PatchBytes,
#else
                                    .size = proof.regions.count * PatchBytes,
#endif
                                    .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(allocator, &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) return false;
        mapped = static_cast<const std::byte*>(info.pMappedData);
        return mapped != nullptr;
    }

    void Copy(vk::CommandBuffer cmd) const {
        std::array<vk::BufferImageCopy, MaxPatches> regions{};
#ifdef BB_TEST_SHARED_POST_GRAPH
        const auto& captured = CaptureRegions();
        for (u32 i = 0; i < captured.count; ++i) {
            const auto xy = captured.points[i].centre;
#else
        for (u32 i = 0; i < proof.regions.count; ++i) {
            const auto xy = proof.regions.points[i].centre;
#endif
            regions[i] = {
                .bufferOffset = i * PatchBytes,
                .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                .imageOffset = {xy.x - s32(Side / 2), xy.y - s32(Side / 2), 0},
                .imageExtent = {Side, Side, 1},
            };
        }
        cmd.copyImageToBuffer(source.image, vk::ImageLayout::eTransferSrcOptimal, vk::Buffer(buffer),
#ifdef BB_TEST_SHARED_POST_GRAPH
                              std::span(regions).first(captured.count));
#else
                              std::span(regions).first(proof.regions.count));
#endif
        const vk::MemoryBarrier2 memory{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &memory});
    }

#ifdef BB_TEST_POST_PRESENT_RESOURCES
    void Report(const PresentSource& retired, const ResourceImage& retired_target) {
#else
    void Report(const PresentSource& retired) {
#endif
        if (refusal) return;
        if (!SameSource(source, retired) || !pp_encoded.load(std::memory_order_acquire)) {
            refusal = "prepared-pp-source-or-fence-generation";
            return;
        }
        if (!presented || !serial || !swap || !swap_image || !present_timeline || !swap_ready ||
            !present_tick || !submit_ns || result_ns < submit_ns) {
            refusal = "unsuccessful-or-unproved-present";
            return;
        }
        if (vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            refusal = "present-host-invalidate";
            return;
        }
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (candidate) {
            FencedFrame frame;
            frame.identity = candidate->Identity();
            frame.source = source;
            frame.slot = slot;
            frame.pp_input = pp_input;
            frame.pp_format = pp_input_format;
            frame.swap = swap;
            frame.swap_image = swap_image;
            frame.swap_ready = swap_ready;
            frame.acquire = acquire;
            frame.present_timeline = present_timeline;
            frame.serial = serial;
            frame.present_tick = present_tick;
            frame.submit_ns = submit_ns;
            frame.result_ns = result_ns;
            frame.swap_index = swap_index;
            frame.regions = candidate->regions;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            if (resources) frame.resources = resources->Fenced(retired_target, presented);
#endif
            frame.lease = std::move(candidate->lease);
            frame.bytes.assign(mapped, mapped + frame.regions.count * PatchBytes);
            vmaDestroyBuffer(allocator, buffer, allocation);
            buffer = {};
            if (!frame.Valid()) return CompleteCandidate(*candidate, "frame-retirement-payload", serial);
            // The caller retains these bytes until its actual postgraph render fence retires.
            return CompleteCandidate(*candidate, nullptr, serial, std::move(frame));
        }
#endif
        const auto raw = [](auto handle) {
            return std::bit_cast<u64>(static_cast<typename decltype(handle)::CType>(handle));
        };
        const auto& key = proof.merge.key;
        fmt::print("[sewer-motion] event=final-fenced request={} checkpoint={} frame={} scene={} "
                   "present_serial={} draw_tick={} ready_tick={} display={:x}/{:x} display_gen={} "
                   "display_write={} merge_write={} tonemap_write={} pp_input={:x} pp_format={} "
                   "prepared={:x}/{:x} prepared_gen={} ready_sem={:x} fence={:x} "
                   "present_sem={:x} present_tick={} swap_ready={:x} submit_ns={} result_ns={} "
                   "swap_epoch={} swap={:x} swap_index={} swap_image={:x} "
                   "format=bgra8-unorm colorspace=srgb size=3840x2160 mip=0 layer=0 regions={}\n",
                   key.request, key.checkpoint, key.frame, key.scene, serial, proof.display.draw_tick,
                   source.ready_tick, raw(proof.display.image), raw(proof.display_attachment),
                   proof.display_generation, proof.display_write, proof.merge.write,
                   proof.tonemap_output_write, raw(pp_input), u32(pp_input_format), raw(source.image),
                   raw(source.view), source.frame_generation, raw(source.ready), raw(source.fence),
                   raw(present_timeline), present_tick, raw(swap_ready), submit_ns, result_ns, source.swap_generation,
                   raw(swap), swap_index, raw(swap_image), proof.regions.count);
        for (u32 i = 0; i < proof.regions.count; ++i) {
            const auto& point = proof.regions.points[i];
            constexpr char hex[] = "0123456789abcdef";
            std::string encoded(PatchBytes * 2, '\0');
            for (u32 byte = 0; byte < PatchBytes; ++byte) {
                const auto value = std::to_integer<unsigned>(mapped[i * PatchBytes + byte]);
                encoded[byte * 2] = hex[value >> 4];
                encoded[byte * 2 + 1] = hex[value & 15u];
            }
            fmt::print("[sewer-motion] event=final-patch request={} checkpoint={} frame={} present_serial={} "
                       "role={} centre={},{} side={} bgra={}\n",
                       key.request, key.checkpoint, key.frame, serial, unsigned(point.role),
                       point.centre.x, point.centre.y, Side, encoded);
        }
        vmaDestroyBuffer(allocator, buffer, allocation);
        buffer = {};
        Finish(proof, true, "none", serial);
    }
};

static SewerPresent::PresentSource SewerPreparedSource(const Frame& frame, u64 swap_generation) {
    return {frame.image, frame.image_view, frame.present_done, frame.ready_semaphore,
            frame.ready_tick, frame.sewer_prepared_generation, swap_generation,
            {frame.width, frame.height}, frame.sewer_final_format};
}

static bool SewerDisplayFormat(vk::Format backing, vk::Format view) {
    return (view == vk::Format::eB8G8R8A8Srgb &&
            (backing == vk::Format::eB8G8R8A8Srgb || backing == vk::Format::eB8G8R8A8Unorm)) ||
           (view == vk::Format::eR8G8B8A8Srgb &&
            (backing == vk::Format::eR8G8B8A8Srgb || backing == vk::Format::eR8G8B8A8Unorm));
}

static void RetireSewerPresent(Frame& frame, u64 current_swap_generation) {
    auto capture = std::exchange(frame.sewer_present_readback, {});
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    if (capture) capture->Report(SewerPreparedSource(frame, current_swap_generation),
                                 PostPresentResources::PreparedResource(frame, frame.sewer_prepared_generation,
                                                                       frame.sewer_final_format));
#else
    if (capture) capture->Report(SewerPreparedSource(frame, current_swap_generation));
#endif
}
#ifdef BB_TEST_SHARED_POST_GRAPH

void Presenter::InvalidatePostPresentSwap() {
    if (SewerMotion::Enabled()) sewer_swap_generation.fetch_add(1, std::memory_order_acq_rel);
}
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE

namespace BottleCutPresent {
namespace {
std::mutex window_mutex;
std::unique_ptr<Window> window;
bool window_started{};

auto Raw(auto handle) {
    return std::bit_cast<u64>(static_cast<typename decltype(handle)::CType>(handle));
}

void PrintSample(const Scene& scene, const Sample& s) {
    const auto& a = s.attempt;
    const auto count = s.raw ? s.raw->count : s.regions.count;
    fmt::print("[bottle-cut-present] event={} request={} scene={} draw_frame={} present={} "
               "display_address={:x} display={:x}/{:x} gen={} write={} draw_sem={:x} draw_tick={} "
               "pp_input={:x}/{} prepared={:x}/{:x} slot={} incarnation={} ready_sem={:x} ready_tick={} fence={:x} "
               "swap_gen={} swap={:x}/{} image={:x} acquire={:x} swap_ready={:x} "
               "present_sem={:x} present_tick={} submit_ns={} result_ns={} "
               "bgra8-unorm=3840x2160 mip=0 layer=0 regions={}\n",
               s.raw ? "raw-search-fenced" : "fenced", scene.key.request, scene.key.scene, scene.draw_frame,
               a.serial, s.display.address,
               Raw(s.display.image), Raw(s.display_attachment), s.display_generation, s.display_write,
               Raw(s.display.draw_timeline), s.display.draw_tick, Raw(s.sampled), u32(s.sampled_format),
               Raw(s.source.image), Raw(s.source.view), s.source.slot, s.source.incarnation,
               Raw(s.source.ready), s.source.ready_tick, Raw(s.source.fence), s.source.swap_generation,
               Raw(a.swap), a.image_index, Raw(a.swap_image), Raw(a.acquire), Raw(a.ready),
               Raw(a.timeline), a.tick, a.submit_ns, a.result_ns, count);
    if (s.raw) {
        const auto& raw = *s.raw;
        fmt::print("[bottle-cut-present] event=raw-search-native-key request={} scene={} frame={} present={} "
                   "state={} epoch={} native_timeline={:x} outer_tick={} app={} color_uid={} depth_uid={} "
                   "parents={:x}/{:x} allocations={:x}/{:x} ordinary_read_tick={} "
                   "ordinary_color={:x}/{:x}/{} ordinary_depth={:x}/{:x}/{}\n",
                   scene.key.request, scene.key.scene, scene.draw_frame, a.serial, u32(scene.state),
                   scene.last_epoch, Raw(raw.native_timeline), raw.native_tick, raw.native_application,
                   raw.color_uid, raw.depth_uid, Raw(raw.color_parent), Raw(raw.depth_parent),
                   raw.color_allocation, raw.depth_allocation, raw.ordinary_read_tick,
                   Raw(raw.read_color), Raw(raw.read_color_view), raw.read_color_incarnation,
                   Raw(raw.read_depth), Raw(raw.read_depth_view), raw.read_depth_incarnation);
        const auto& camera = raw.camera;
        for (u32 row = 0; row < 3; ++row) {
            const auto* line = camera.view.data() + row * 4;
            fmt::print("[bottle-cut-present] event=raw-search-view request={} scene={} row={} "
                       "values={:.9g}/{:.9g}/{:.9g}/{:.9g}\n",
                       scene.key.request, scene.key.scene, row, line[0], line[1], line[2], line[3]);
        }
        fmt::print("[bottle-cut-present] event=raw-search-projection request={} scene={} "
                   "values={:.9g}/{:.9g}/{:.9g}/{:.9g} jitter={:.9g}/{:.9g}\n",
                   scene.key.request, scene.key.scene, camera.projection[0], camera.projection[1],
                   camera.projection[2], camera.projection[3], camera.jitter[0], camera.jitter[1]);
    }
    constexpr char hex[] = "0123456789abcdef";
    std::array<char, 2 * PatchBytes + 1> words{};
    for (u32 i = 0; i < count; ++i) {
        for (u32 byte = 0; byte < PatchBytes; ++byte) {
            const auto v = std::to_integer<unsigned>(s.bytes[i * PatchBytes + byte]);
            words[2 * byte] = hex[v >> 4];
            words[2 * byte + 1] = hex[v & 15];
        }
        if (s.raw) {
            const auto xy = s.raw->centres[i];
            fmt::print("[bottle-cut-present] event=raw-search-tile request={} scene={} present={} ordinal={} "
                       "centre={},{} side={} bgra={}\n",
                       scene.key.request, scene.key.scene, a.serial, i, xy.x, xy.y, Side, words.data());
        } else {
            const auto [role, xy] = s.regions.points[i];
            fmt::print("[bottle-cut-present] event=patch request={} scene={} present={} role={} "
                       "centre={},{} side={} bgra={}\n",
                       scene.key.request, scene.key.scene, a.serial, u32(role), xy.x, xy.y, Side, words.data());
        }
    }
}

void PublishReady() {
    std::unique_ptr<Window> finished;
    {
        std::lock_guard lock(window_mutex);
        if (window && window->Settled()) finished = std::move(window);
    }
    if (!finished) return;
    auto& w = *finished;
    std::array<const Slot*, Capacity> ordered{};
    u32 count = 0;
    for (const auto& slot : w.slots) {
        if (slot.progress != Progress::Empty) ordered[count++] = &slot;
    }
    const auto selected = std::span(ordered).first(count);
    std::ranges::sort(selected, {}, [](const Slot* slot) { return slot->scene.key.scene; });
    u64 prior_scene = w.evicted_last ? w.evicted_last : w.first_scene - 1;
    u64 prior_attempt{}, prior_submit{};
    for (const auto* slot : selected) {
        const auto& scene = slot->scene;
        const auto ordinal = scene.key.scene;
        if (prior_scene + 1 < ordinal) w.Gap(prior_scene + 1, ordinal - 1);
        prior_scene = ordinal;
        const char* reason = slot->why ? slot->why : "none";
        const auto* sample = slot->sample ? &*slot->sample : nullptr;
        if (sample && (sample->attempt.serial <= prior_attempt || sample->attempt.submit_ns < prior_submit)) {
            reason = "present-attempt-order";
            w.Gap(ordinal, ordinal);
            sample = nullptr;
        }
        if (sample && prior_attempt && sample->attempt.serial > prior_attempt + 1) {
            w.Gap(ordinal, ordinal);
            fmt::print("[bottle-cut-present] event=present-gap request={} before_scene={} first={} last={}\n",
                       w.request, ordinal, prior_attempt + 1, sample->attempt.serial - 1);
        }
        fmt::print("[bottle-cut-present] event={} request={} scene={} load={} rt={} object={} "
                   "targets_gen={} primary_pass={} draw_frame={} state={} epoch={}/{} present={} "
                   "fenced={} reason={}\n",
                   w.raw_search ? "raw-search-scene" : "scene", w.request, ordinal, scene.key.load,
                   scene.key.rt_frame, scene.key.object_frame, scene.key.target_generation, scene.key.primary_pass, scene.draw_frame, u32(scene.state),
                   scene.first_epoch, scene.last_epoch, slot->serial, bool(sample), reason);
        if (sample) {
            prior_attempt = sample->attempt.serial;
            prior_submit = sample->attempt.submit_ns;
            PrintSample(scene, *sample);
        }
    }
    if (w.mode == Mode::Cut && w.last_on && !w.Find(w.last_on)) w.Gap(w.last_on, w.last_on);
    if (prior_scene < w.end_scene) w.Gap(prior_scene + 1, w.end_scene);
    const bool bracket = w.mode == Mode::AllOff ? w.first_off != 0 : w.last_on && w.first_off > w.last_on;
    fmt::print("[bottle-cut-present] event={} request={} mode={} scenes={}/{} retained={} "
               "pretrigger_evicted={}/{} on={}/{} off={}/{} gap={}/{} {}={}\n",
               w.raw_search ? "raw-search-window" : "window", w.request, u32(w.mode), w.first_scene,
               w.end_scene, count, w.evicted_first, w.evicted_last, w.first_on, w.last_on,
               w.first_off, w.last_off, w.first_gap, w.last_gap,
               w.raw_search ? "raw_complete" : "full", bracket && !w.first_gap);
}

void Complete(Issued& proof, const char* reason, u64 serial = 0, std::optional<Sample> sample = {}
#ifdef BB_TEST_POST_PRESENT_RESOURCES
              , std::optional<RawFenced> raw = {}
#endif
) {
    auto callback = std::exchange(proof.complete, {});
    const Result result{proof.scene, bool(sample), reason, serial, bool(proof.raw)};
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    auto resource = std::exchange(proof.resource, {});
    bool retained{};
#endif
    {
        std::lock_guard lock(window_mutex);
        if (window && window->request == proof.scene.key.request) {
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            retained = window->Finish(result, std::move(sample));
#else
            window->Finish(result, std::move(sample));
#endif
        }
    }
    if (reason) {
        fmt::print("[bottle-cut-present] event=refused request={} scene={} draw_frame={} present={} reason={}\n",
                   proof.scene.key.request, proof.scene.key.scene, proof.scene.draw_frame, serial, reason);
    }
    if (callback) callback(result);
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    if (resource && resource->complete) {
        auto complete = std::move(resource->complete);
        if (result.fenced && (!retained || !raw || raw->scene != proof.scene || raw->raw != proof.raw ||
                              raw->attempt.serial != serial)) {
            complete({proof.scene, false, "bottle-raw-retirement-not-owned", serial, bool(proof.raw)}, {});
        } else {
            complete(result, std::move(raw));
        }
    }
#endif
    PublishReady();
}

std::optional<Issued> Take(u32 draw_frame) {
    std::array<std::optional<Issued>, Capacity> stale{};
    u32 count{};
    std::optional<Issued> selected;
    {
        std::lock_guard lock(window_mutex);
        if (!window) return {};
        for (auto& slot : window->slots) {
            if (slot.scene.draw_frame > draw_frame) continue;
            if (slot.progress == Progress::Pending) {
                slot.progress = Progress::Active;
                if (slot.scene.draw_frame == draw_frame) selected = std::exchange(slot.issued, {});
                else stale[count++] = std::exchange(slot.issued, {});
            } else if (slot.progress == Progress::Enrolled) {
                slot.progress = Progress::Refused;
                slot.why = "no-issued-display-before-prepare";
                window->Gap(slot.scene.key.scene, slot.scene.key.scene);
                fmt::print("[bottle-cut-present] event=refused request={} scene={} draw_frame={} reason={}\n",
                           window->request, slot.scene.key.scene, slot.scene.draw_frame, slot.why);
            }
        }
    }
    for (u32 i = 0; i < count; ++i) Complete(*stale[i], "no-matching-prepare-frame");
    PublishReady();
    return selected;
}

void CancelWindow() {
    std::array<std::optional<Issued>, Capacity> stale{};
    u32 count{};
    {
        std::lock_guard lock(window_mutex);
        if (!window) return;
        auto& w = *window;
        if (!w.closed) {
            w.Gap(w.last_scene ? w.last_scene : w.first_scene, w.last_scene ? w.last_scene : w.first_scene);
            w.end_scene = w.last_scene ? w.last_scene : w.first_scene;
            w.closed = true;
        }
        for (auto& slot : w.slots) {
            if (slot.progress == Progress::Pending) {
                slot.progress = Progress::Active;
                stale[count++] = std::exchange(slot.issued, {});
            } else if (slot.progress == Progress::Enrolled || slot.progress == Progress::Active) {
                slot.progress = Progress::Refused;
                slot.why = "presenter-shutdown-before-fence";
                w.Gap(slot.scene.key.scene, slot.scene.key.scene);
            }
        }
    }
    for (u32 i = 0; i < count; ++i) Complete(*stale[i], "presenter-shutdown-before-prepare");
    PublishReady();
}
} // namespace

static bool OpenWindow(u32 request, Mode mode, u64 first_scene, bool raw_search) {
    if (!request || request != BottleCaustic::CutSource::Run() || !first_scene ||
        (mode != Mode::Cut && mode != Mode::AllOff)) return false;
    std::lock_guard lock(window_mutex);
    if (window_started) return false;
    window_started = true;
    window = std::make_unique<Window>();
    window->request = request;
    window->mode = mode;
    window->first_scene = first_scene;
    window->raw_search = raw_search;
    return true;
}

bool BeginWindow(u32 request, Mode mode, u64 first_scene) {
    return OpenWindow(request, mode, first_scene, false);
}

bool BeginRawSearchWindow(u32 request, Mode mode, u64 first_scene) {
    return OpenWindow(request, mode, first_scene, true);
}

static bool Enrol(Scene scene, const RawSearch* raw) {
    if (!BottleCaustic::CutSource::Run()) return false;
    const char* why;
    u64 expected{};
    {
        std::lock_guard lock(window_mutex);
        if (window && window->raw_search == bool(raw)) {
            if (!window->closed && window->request == scene.key.request) {
                expected = window->last_scene ? window->last_scene + 1 : window->first_scene;
            }
            why = raw ? window->EnrolRaw(*raw) : window->Enrol(scene);
        } else {
            why = window ? "window-purpose" : "no-window";
        }
    }
    if (expected && scene.key.scene > expected) {
        fmt::print("[bottle-cut-present] event=scene-gap request={} first={} last={} reason=scene-ordinal-missing\n",
                   scene.key.request, expected, scene.key.scene - 1);
    }
    if (why) {
        fmt::print("[bottle-cut-present] event=enrol-refused request={} scene={} reason={}\n",
                   scene.key.request, scene.key.scene, why);
    }
    return !why;
}

bool EnrolScene(Scene scene) { return Enrol(scene, nullptr); }

bool EnrolRawSearch(const RawSearch& raw) { return Enrol(raw.scene, &raw); }

bool OfferIssuedDisplay(Issued proof) {
    if (!BottleCaustic::CutSource::Run()) return false;
    const char* why = "no-matching-enrolled-scene";
    {
        std::lock_guard lock(window_mutex);
        if (window && window->request == proof.scene.key.request) {
            auto* slot = window->Find(proof.scene.key.scene);
            if (slot && slot->scene == proof.scene && slot->progress == Progress::Enrolled && !window->closed) {
                const Epoch epoch{proof.display.address, proof.display.image, proof.display_generation,
                                  proof.display_write};
                const bool valid = proof.consume_epoch &&
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                    (proof.resource ? proof.resource->Valid() && proof.scene.Known() : bool(proof.complete)) &&
#else
                    proof.complete &&
#endif
                    proof.display_attachment &&
                    epoch.generation && epoch.write && Compatible(proof.display, proof.display) &&
                    window->Accepts(*slot, proof);
                if (valid && std::ranges::none_of(window->slots, [epoch](const Slot& item) {
                        return item.epoch == epoch;
                    })) {
                    slot->epoch = epoch;
                    slot->progress = Progress::Pending;
                    slot->issued = std::move(proof);
                    return true;
                }
                slot->progress = Progress::Refused;
                slot->why = why = valid ? "issued-display-write-epoch-reused" : "invalid-issued-display-or-regions";
                window->Gap(proof.scene.key.scene, proof.scene.key.scene);
            } else if (slot && !window->closed) {
                window->Gap(proof.scene.key.scene, proof.scene.key.scene);
            }
        }
    }
    // A rejected offer owns its own callback. It must not complete another offer's active slot.
    fmt::print("[bottle-cut-present] event=offer-refused request={} scene={} draw_frame={} reason={}\n",
               proof.scene.key.request, proof.scene.key.scene, proof.scene.draw_frame, why);
    if (proof.complete) proof.complete({proof.scene, false, why, 0, bool(proof.raw)});
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    if (proof.resource && proof.resource->complete) {
        auto complete = std::move(proof.resource->complete);
        complete({proof.scene, false, why, 0, bool(proof.raw)}, {});
    }
#endif
    return false;
}

#ifdef BB_TEST_POST_PRESENT_RESOURCES
bool OfferResourceDisplay(Issued issued, ResourceIssue proof) {
    if (!proof.Valid() || issued.resource || !BottleCaustic::CutSource::Run()) {
        const Result refused{issued.scene, false, "invalid-or-disarmed-bottle-resource-offer", 0, bool(issued.raw)};
        if (issued.complete) issued.complete(refused);
        if (proof.complete) proof.complete(refused, {});
        return false;
    }
    issued.resource = std::make_shared<ResourceIssue>(std::move(proof));
    return OfferIssuedDisplay(std::move(issued));
}
#endif

bool CloseWindow(u32 request, u64 last_scene) {
    bool exact{};
    {
        std::lock_guard lock(window_mutex);
        if (!window || window->request != request || window->closed || last_scene < window->first_scene) return false;
        auto& w = *window;
        exact = w.last_scene == last_scene;
        if (!exact) {
            if (!w.last_scene) w.Gap(w.first_scene, last_scene);
            else w.Gap(std::min(w.last_scene, last_scene) + 1, std::max(w.last_scene, last_scene));
        }
        w.end_scene = last_scene;
        w.closed = true;
        for (auto& slot : w.slots) {
            if (slot.progress == Progress::Enrolled) {
                slot.progress = Progress::Refused;
                slot.why = "window-ended-without-issued-display";
                w.Gap(slot.scene.key.scene, slot.scene.key.scene);
            }
        }
    }
    PublishReady();
    return exact;
}

struct Capture {
    explicit Capture(Issued run) : proof(std::move(run)) {}
    ~Capture() {
        Release();
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        if (proof.complete || proof.resource)
#else
        if (proof.complete)
#endif
            Complete(proof, refusal ? refusal : "prepared-frame-abandoned", attempt.serial);
    }

    Issued proof;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    std::shared_ptr<PostPresentResources::ResourceCapture> resources;
#endif
    Source source{};
    Attempt attempt{};
    vk::ImageView pp_view{};
    vk::Format pp_format{};
    std::atomic<bool> pp_encoded{};
    const char* refusal{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    VkBuffer buffer{};
    const std::byte* mapped{};

    u32 Bytes() const { return proof.Count() * PatchBytes; }

    void Release() {
        if (!buffer) return;
        vmaDestroyBuffer(allocator, buffer, allocation);
        buffer = {};
    }

    bool Allocate(VmaAllocator vma) {
        allocator = vma;
        const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                    .size = Bytes(), .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
        const VmaAllocationCreateInfo ai{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(allocator, &ci, &ai, &buffer, &allocation, &info) != VK_SUCCESS) return false;
        mapped = static_cast<const std::byte*>(info.pMappedData);
        return mapped != nullptr;
    }

    void Copy(vk::CommandBuffer cmd) const {
        std::array<vk::BufferImageCopy, MaxPatches> regions{};
        for (u32 i = 0; i < proof.Count(); ++i) {
            const auto xy = proof.Centre(i);
            regions[i] = {.bufferOffset = i * PatchBytes,
                          .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                          .imageOffset = {xy.x - s32(Side / 2), xy.y - s32(Side / 2), 0},
                          .imageExtent = {Side, Side, 1}};
        }
        cmd.copyImageToBuffer(source.image, vk::ImageLayout::eTransferSrcOptimal, vk::Buffer(buffer),
                              std::span(regions).first(proof.Count()));
        const vk::MemoryBarrier2 memory{
            .srcStageMask = vk::PipelineStageFlagBits2::eAllTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &memory});
    }

    void Fail(const char* why) { Complete(proof, why, attempt.serial); }

#ifdef BB_TEST_POST_PRESENT_RESOURCES
    void Retire(const Source& current, const PostPresentResources::ResourceImage& backing) {
#else
    void Retire(const Source& current) {
#endif
        if (refusal) return Fail(refusal);
        if (!ReadyToRead(source, current, pp_encoded.load(std::memory_order_acquire) && bool(pp_view), attempt)) {
            return Fail(attempt.Valid() ? "prepared-postprocess-or-fence-incarnation"
                                        : "unsuccessful-or-unproved-present");
        }
        if (vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
            return Fail("present-host-invalidate");
        }
        Sample sample{source, attempt, proof.display, proof.display_attachment, pp_view, pp_format,
                      proof.display_generation, proof.display_write, proof.regions,
                      std::vector<std::byte>(mapped, mapped + Bytes()), proof.raw};
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        if (proof.resource) {
            RawFenced raw{proof.scene, source, attempt, proof.display, proof.display_attachment,
                          pp_view, pp_format, proof.display_generation, proof.display_write,
                          proof.resource->display_allocation, proof.regions,
                          resources ? resources->Fenced(backing, attempt.success)
                                    : PostPresentResources::FrameResources{}, proof.raw};
            return Complete(proof, nullptr, attempt.serial, std::move(sample), std::move(raw));
        }
#endif
        Complete(proof, nullptr, attempt.serial, std::move(sample));
    }
};
} // namespace BottleCutPresent

static BottleCutPresent::Source BottlePreparedSource(const Frame& frame, u64 swap_generation) {
    return {frame.image, frame.image_view, frame.present_done, frame.ready_semaphore,
            frame.ready_tick, frame.bottle_incarnation, swap_generation, frame.id,
            {frame.width, frame.height}, frame.bottle_final_format};
}

static void RetireBottleCutPresent(Frame& frame, u64 swap_generation) {
    auto capture = std::exchange(frame.bottle_present_readback, {});
    if (capture) {
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        capture->Retire(BottlePreparedSource(frame, swap_generation),
                        PostPresentResources::PreparedResource(frame, frame.bottle_incarnation,
                                                               frame.bottle_final_format));
#else
        capture->Retire(BottlePreparedSource(frame, swap_generation));
#endif
        capture->Release();
    }
}
#endif

bool CanBlitToSwapchain(const vk::PhysicalDevice physical_device, vk::Format format) {
    const vk::FormatProperties props{physical_device.getFormatProperties(format)};
    return static_cast<bool>(props.optimalTilingFeatures & vk::FormatFeatureFlagBits::eBlitDst);
}

[[nodiscard]] vk::ImageSubresourceLayers MakeImageSubresourceLayers() {
    return vk::ImageSubresourceLayers{
        .aspectMask = vk::ImageAspectFlagBits::eColor,
        .mipLevel = 0,
        .baseArrayLayer = 0,
        .layerCount = 1,
    };
}

[[nodiscard]] vk::ImageBlit MakeImageBlit(s32 frame_width, s32 frame_height, s32 dst_width,
                                          s32 dst_height, s32 offset_x, s32 offset_y) {
    return vk::ImageBlit{
        .srcSubresource = MakeImageSubresourceLayers(),
        .srcOffsets =
            std::array{
                vk::Offset3D{
                    .x = 0,
                    .y = 0,
                    .z = 0,
                },
                vk::Offset3D{
                    .x = frame_width,
                    .y = frame_height,
                    .z = 1,
                },
            },
        .dstSubresource = MakeImageSubresourceLayers(),
        .dstOffsets =
            std::array{
                vk::Offset3D{
                    .x = offset_x,
                    .y = offset_y,
                    .z = 0,
                },
                vk::Offset3D{
                    .x = offset_x + dst_width,
                    .y = offset_y + dst_height,
                    .z = 1,
                },
            },
    };
}

[[nodiscard]] vk::ImageBlit MakeImageBlitStretch(s32 frame_width, s32 frame_height,
                                                 s32 swapchain_width, s32 swapchain_height) {
    return MakeImageBlit(frame_width, frame_height, swapchain_width, swapchain_height, 0, 0);
}

static vk::Rect2D FitImage(s32 frame_width, s32 frame_height, s32 swapchain_width,
                           s32 swapchain_height) {
    float frame_aspect = static_cast<float>(frame_width) / frame_height;
    float swapchain_aspect = static_cast<float>(swapchain_width) / swapchain_height;

    u32 dst_width = swapchain_width;
    u32 dst_height = swapchain_height;

    if (frame_aspect > swapchain_aspect) {
        dst_height = static_cast<s32>(swapchain_width / frame_aspect);
    } else {
        dst_width = static_cast<s32>(swapchain_height * frame_aspect);
    }

    const s32 offset_x = (swapchain_width - dst_width) / 2;
    const s32 offset_y = (swapchain_height - dst_height) / 2;

    return vk::Rect2D{{offset_x, offset_y}, {dst_width, dst_height}};
}

[[nodiscard]] vk::ImageBlit MakeImageBlitFit(s32 frame_width, s32 frame_height, s32 swapchain_width,
                                             s32 swapchain_height) {
    const auto& dst_rect = FitImage(frame_width, frame_height, swapchain_width, swapchain_height);

    return MakeImageBlit(frame_width, frame_height, dst_rect.extent.width, dst_rect.extent.height,
                         dst_rect.offset.x, dst_rect.offset.y);
}

// bbport: screenshot capture and ImGui overlays removed; the port presents directly.

static void GrabFace(const Instance& instance, Scheduler& scheduler, vk::Image image, u32 width, u32 height,
                     vk::Format format) {
    float rect[4];
    if (!BbFaceShot::Due(rect) || !width || !height) {
        return;
    }
    const u32 x = u32(rect[0] * float(width)), y = u32(rect[1] * float(height));
    const u32 w = std::min(width - x, u32((rect[2] - rect[0]) * float(width)));
    const u32 h = std::min(height - y, u32((rect[3] - rect[1]) * float(height)));
    if (!w || !h) {
        return;
    }
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = VkDeviceSize(w) * h * 4,
        .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    const VmaAllocationCreateInfo alloc_ci{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
    };
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation, &info) != VK_SUCCESS) {
        return;
    }
    scheduler.EndRendering();
    const vk::CommandBuffer cmdbuf = scheduler.CommandBuffer();
    const vk::MemoryBarrier2 before{
        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
        .dstAccessMask = vk::AccessFlagBits2::eTransferRead,
    };
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
    const vk::BufferImageCopy region{
        .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
        .imageOffset = {s32(x), s32(y), 0},
        .imageExtent = {w, h, 1},
    };
    cmdbuf.copyImageToBuffer(image, vk::ImageLayout::eGeneral, buffer, region);
    const vk::MemoryBarrier2 after{
        .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
        .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
        .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
    };
    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
    const bool bgra = format == vk::Format::eB8G8R8A8Unorm || format == vk::Format::eB8G8R8A8Srgb;
    scheduler.DeferPriorityOperation([allocator = instance.GetAllocator(), buffer, allocation, info, w, h, bgra] {
        vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE);
        BbFaceShot::Deliver(static_cast<const std::uint8_t*>(info.pMappedData), w, h, w * 4, bgra);
        vmaDestroyBuffer(allocator, buffer, allocation);
    });
}

Presenter::Presenter(Frontend::WindowSDL& window_, AmdGpu::Liverpool* liverpool_)
    : window{window_}, liverpool{liverpool_},
      instance{window, EmulatorSettings.GetGpuId(), EmulatorSettings.IsVkValidationEnabled(),
               EmulatorSettings.IsVkCrashDiagnosticEnabled()},
      draw_scheduler{instance, true}, present_scheduler{instance}, flip_scheduler{instance},
      swapchain{instance, window}, runtime{instance, draw_scheduler},
      rasterizer{std::make_unique<Rasterizer>(instance, draw_scheduler, runtime, liverpool)},
      texture_cache{rasterizer->GetTextureCache()} {
    const u32 num_images = swapchain.GetImageCount();
    const vk::Device device = instance.GetDevice();

    // Create presentation frames.
    present_frames.resize(num_images);
    for (u32 i = 0; i < num_images; i++) {
        Frame& frame = present_frames[i];
        frame.id = i;
        auto fence = Check<"create present done fence">(
            device.createFence({.flags = vk::FenceCreateFlagBits::eSignaled}));
        frame.present_done = fence;
        free_queue.push(&frame);
    }
    // bbport: frame generation's frames (images made at their first use).
    for (u32 i = 0; i < generated_frames.size(); ++i) {
        Frame& frame = generated_frames[i];
        frame.id = u8(num_images + i);
        frame.present_done = Check<"create present done fence">(
            device.createFence({.flags = vk::FenceCreateFlagBits::eSignaled}));
    }
    frame_gen = std::make_unique<FrameGenerator>(instance, draw_scheduler);
    rasterizer->GetUpscaler().SetFrameGenerator(frame_gen.get());
    // bbport: DLSS Frame Generation (vk_streamline.h): a slot and a HUD-less frame per
    // presentation frame (images made at their first use).
    dlss_fg = std::make_unique<DlssFrameGen>(instance, num_images);
    dlss_hudless_frames.resize(num_images);
    for (u32 i = 0; i < num_images; ++i) {
        dlss_hudless_frames[i].id = u8(num_images + NumGeneratedFrames + i);
    }

    fsr_settings.enable = EmulatorSettings.IsFsrEnabled();
    fsr_settings.use_rcas = EmulatorSettings.IsRcasEnabled();
    fsr_settings.rcas_attenuation =
        static_cast<float>(EmulatorSettings.GetRcasAttenuation() / 1000.f);

    fsr_pass.Create(device, instance.GetAllocator(), num_images);
    pp_pass.Create(device, swapchain.GetSurfaceFormat().format);
    // bbport: + 2: frame generation presents up to twice per game frame, and adds a swapchain
    // image; the menu's vertex buffers rotate over this many.
    BbOverlay::Init(instance, swapchain.GetSurfaceFormat().format, num_images + 2);
    // bbport: HDR output (hdr in lantern.ini): frames, passes and the menu stay SDR; the encode
    // pass writes the HDR swapchain format chosen at start.
    if (const vk::Format hdr_format = swapchain.GetHdrFormat().format;
        hdr_format != vk::Format::eUndefined) {
        hdr_pass.Create(device, hdr_format);
    }

}

void Presenter::ReportState() {
    const vk::Device device = instance.GetDevice();
    const std::array<std::pair<const char*, Scheduler*>, 3> schedulers{{
        {"draw", &draw_scheduler}, {"present", &present_scheduler}, {"flip", &flip_scheduler}}};
    for (const auto& [name, scheduler] : schedulers) {
        Semaphore* semaphore = scheduler->GetWorkSemaphore();
        const auto [result, value] = device.getSemaphoreCounterValue(semaphore->Handle());
        std::printf("Freeze: %s scheduler: next tick %llu, submitted %llu, GPU done %llu%s\n", name,
                    static_cast<unsigned long long>(semaphore->CurrentTick()),
                    static_cast<unsigned long long>(scheduler->SubmittedTick()),
                    static_cast<unsigned long long>(value),
                    result == vk::Result::eSuccess ? "" : " (query failed)");
    }
    std::unique_lock lock{free_mutex, std::try_to_lock};
    if (lock.owns_lock()) {
        std::printf("Freeze: %zu free presentation frames\n", free_queue.size());
    } else {
        std::printf("Freeze: presentation frames locked\n");
    }
}

void Presenter::WaitForSubmittedWork(u64 timeout_ns) {
    // bbport: exit only. One deadline for the whole wait (it was timeout_ns per scheduler, up to
    // 3x). Every queue submission and present goes out under Scheduler::submit_mutex: taking it
    // (and never giving it back - the process is ending) stops the guest from queueing more
    // frames while the GPU drains, so the process does not end with fresh work in flight. Only
    // ticks already in the queue are waited for (CurrentTick-1 may never be submitted once the
    // lock is held; waiting for it just ran into the timeout). BB_EXIT_BLOCK_SUBMIT=0: old wait.
    using Clock = std::chrono::steady_clock;
    const auto deadline = Clock::now() + std::chrono::nanoseconds(timeout_ns);
    const char* block_env = std::getenv("BB_EXIT_BLOCK_SUBMIT");
    if (!(block_env && block_env[0] == '0')) {
        while (!Scheduler::submit_mutex.try_lock()) {
            if (Clock::now() >= deadline) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
    const vk::Device device = instance.GetDevice();
    for (Scheduler* scheduler : {&draw_scheduler, &present_scheduler, &flip_scheduler}) {
        const u64 value = scheduler->SubmittedTick();
        if (value == 0) {
            continue;
        }
        const auto now = Clock::now();
        if (now >= deadline) {
            return;
        }
        const vk::Semaphore handle = scheduler->GetWorkSemaphore()->Handle();
        const vk::SemaphoreWaitInfo wait_info{
            .semaphoreCount = 1,
            .pSemaphores = &handle,
            .pValues = &value,
        };
        const u64 remaining = u64(
            std::chrono::duration_cast<std::chrono::nanoseconds>(deadline - now).count());
        (void)device.waitSemaphores(wait_info, remaining);
    }
}

Presenter::~Presenter() {

    draw_scheduler.Finish();
    present_scheduler.Finish();
    flip_scheduler.Finish();
    if (SewerMotion::Enabled()) {
        SewerPresent::pending.Cancel("presenter-destroyed-before-prepare");
#ifdef BB_TEST_SHARED_POST_GRAPH
        SewerPresent::Candidates().Cancel();
#endif
        for (auto& frame : present_frames) {
            frame.sewer_prepared.reset();
            if (frame.sewer_present_readback) {
                if (instance.GetDevice().getFenceStatus(frame.present_done) == vk::Result::eSuccess) {
                    RetireSewerPresent(frame, sewer_swap_generation.load(std::memory_order_acquire));
                } else {
                    frame.sewer_present_readback->refusal = "present-fence-unavailable-at-shutdown";
                    frame.sewer_present_readback.reset();
                }
            }
        }
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (BottleCaustic::CutSource::Run()) {
        const auto epoch = bottle_swap_generation.load(std::memory_order_acquire);
        for (auto& frame : present_frames) {
            if (frame.bottle_prepared) frame.bottle_prepared->Fail("presenter-shutdown-before-present");
            frame.bottle_prepared.reset();
            if (frame.bottle_present_readback) {
                if (instance.GetDevice().getFenceStatus(frame.present_done) == vk::Result::eSuccess) {
                    RetireBottleCutPresent(frame, epoch);
                } else {
                    frame.bottle_present_readback->Fail("present-fence-unavailable-at-shutdown");
                    frame.bottle_present_readback.reset();
                }
            }
        }
        BottleCutPresent::CancelWindow();
    }
#endif
    ReportMotionAttempts();
    if (motion_buffer) vmaDestroyBuffer(instance.GetAllocator(),motion_buffer,motion_allocation);
    Check(draw_scheduler.CommandBuffer().reset());
    Check(present_scheduler.CommandBuffer().reset());
    Check(flip_scheduler.CommandBuffer().reset());

    const vk::Device device = instance.GetDevice();
    for (auto& frame : present_frames) {
        vmaDestroyImage(instance.GetAllocator(), frame.image, frame.allocation);
        device.destroyImageView(frame.image_view);
        device.destroyFence(frame.present_done);
    }
    frame_gen.reset();
    for (auto& frame : generated_frames) {
        if (frame.image) {
            vmaDestroyImage(instance.GetAllocator(), frame.image, frame.allocation);
            device.destroyImageView(frame.image_view);
        }
        device.destroyFence(frame.present_done);
    }
    dlss_fg.reset();
    for (auto& frame : dlss_hudless_frames) {
        if (frame.image) {
            vmaDestroyImage(instance.GetAllocator(), frame.image, frame.allocation);
            device.destroyImageView(frame.image_view);
        }
    }
    DestroyHdrTarget(hdr_game);
    DestroyHdrTarget(hdr_overlay);
    DestroyHdrTarget(dlss_hdr_composite);
    DestroyHdrTarget(dlss_hdr_hudless);
}

void Presenter::CreateHdrTarget(HdrTarget& target, vk::Extent2D extent, const char* name,
                                vk::Format format) {
    const vk::Device device = instance.GetDevice();
    // The SDR format: the blit's and the menu pipeline's (BbOverlay::Init); sRGB encoded values,
    // decoded by the encode pass. Format support is checked by Swapchain::FindPresentFormat.
    // Another format (DLSS-G's HDR HUD-less frame) is the swapchain's HDR one, read by DLSS-G.
    const bool sdr = format == vk::Format::eUndefined;
    const vk::ImageCreateInfo image_info = {
        .imageType = vk::ImageType::e2D,
        .format = sdr ? swapchain.GetSurfaceFormat().format : format,
        .extent = {extent.width, extent.height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eTransferDst |
                 vk::ImageUsageFlagBits::eSampled |
                 (sdr ? vk::ImageUsageFlags{} : vk::ImageUsageFlagBits::eTransferSrc),
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    const VmaAllocationCreateInfo alloc_info = {
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE,
    };
    VkImage image{};
    const VkImageCreateInfo unsafe_image_info = static_cast<VkImageCreateInfo>(image_info);
    const VkResult result = vmaCreateImage(instance.GetAllocator(), &unsafe_image_info,
                                           &alloc_info, &image, &target.allocation, nullptr);
    if (result != VK_SUCCESS) [[unlikely]] {
        LOG_CRITICAL(Render_Vulkan, "Failed allocating the HDR output image with error {}",
                     vk::to_string(vk::Result{result}));
        UNREACHABLE();
    }
    target.image = vk::Image{image};
    SetObjectName(device, target.image, "HDR output {}", name);
    target.view = Check<"create HDR output image view">(device.createImageView({
        .image = target.image,
        .viewType = vk::ImageViewType::e2D,
        .format = image_info.format,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
}

void Presenter::DestroyHdrTarget(const HdrTarget& target) {
    if (target.view) {
        instance.GetDevice().destroyImageView(target.view);
    }
    if (target.image) {
        vmaDestroyImage(instance.GetAllocator(), target.image, target.allocation);
    }
}

void Presenter::EnsureHdrTargets(vk::Extent2D extent) {
    if (hdr_game.image && hdr_extent == extent) {
        return;
    }
    if (hdr_game.image) {
        // Presents still in flight may read the old size's images: they go once the GPU has
        // finished this present's submission (later than every earlier one, same queue).
        present_scheduler.DeferOperation(
            [this, game = hdr_game, overlay = hdr_overlay] {
                DestroyHdrTarget(game);
                DestroyHdrTarget(overlay);
            });
    }
    CreateHdrTarget(hdr_game, extent, "composite");
    CreateHdrTarget(hdr_overlay, extent, "menu layer");
    hdr_extent = extent;
}

void Presenter::EnsureDlssHdrTargets(vk::Extent2D extent) {
    if (dlss_hdr_hudless.image && dlss_hdr_extent == extent) {
        return;
    }
    if (dlss_hdr_hudless.image) {
        present_scheduler.DeferOperation(
            [this, composite = dlss_hdr_composite, hudless = dlss_hdr_hudless] {
                DestroyHdrTarget(composite);
                DestroyHdrTarget(hudless);
            });
    }
    CreateHdrTarget(dlss_hdr_composite, extent, "DLSS-G HUD-less composite");
    CreateHdrTarget(dlss_hdr_hudless, extent, "DLSS-G HUD-less", swapchain.GetHdrFormat().format);
    dlss_hdr_extent = extent;
}

void Presenter::PresentHdr(vk::CommandBuffer cmdbuf, Frame* frame, vk::Extent2D extent,
                           bool dlss_inputs) {
    EnsureHdrTargets(extent);
    const vk::Image swapchain_image = swapchain.Image();
    const bool overlay = BbOverlay::Visible();
    const vk::ImageSubresourceRange color_range{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
    const auto barrier = [&](vk::Image image, vk::ImageLayout old_layout,
                             vk::ImageLayout new_layout, vk::PipelineStageFlags2 src_stage,
                             vk::AccessFlags2 src_access, vk::PipelineStageFlags2 dst_stage,
                             vk::AccessFlags2 dst_access) {
        return vk::ImageMemoryBarrier2{
            .srcStageMask = src_stage,
            .srcAccessMask = src_access,
            .dstStageMask = dst_stage,
            .dstAccessMask = dst_access,
            .oldLayout = old_layout,
            .newLayout = new_layout,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image,
            .subresourceRange = color_range,
        };
    };
    const auto barriers = [&](std::span<const vk::ImageMemoryBarrier2> image_barriers) {
        cmdbuf.pipelineBarrier2(vk::DependencyInfo{
            .imageMemoryBarrierCount = static_cast<u32>(image_barriers.size()),
            .pImageMemoryBarriers = image_barriers.data(),
        });
    };
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    using Layout = vk::ImageLayout;

    // bbport: a frame of the back buffer's size is encoded from its own image: the clear and the
    // 1:1 blit into hdr_game made an exact copy of it (same format, hdr_output.frag reads it texel
    // for texel). Experiment bit 33554432: the copy as before.
    const bool direct = frame->width == extent.width && frame->height == extent.height &&
                        !BbToggle::Experiment(33554432);
    {
        static int logged = -1;
        if (int(direct) != logged) {
            logged = int(direct);
            std::printf("HDR output: the frame is encoded %s (%ux%u into %ux%u)\n",
                        direct ? "from its own image (no composite clear and copy)"
                               : "from a copy in the composite (clear + blit)",
                        frame->width, frame->height, extent.width, extent.height);
            std::fflush(stdout);
        }
    }
    // The composite and the menu layer are rewritten whole: their old contents (read by the
    // previous present's encode, same queue: the all-commands source scope orders it) go.
    // The frame as in the SDR path: General -> transfer source -> General.
    std::array<vk::ImageMemoryBarrier2, 3> pre{
        barrier(hdr_game.image, Layout::eUndefined, Layout::eTransferDstOptimal,
                Stage::eAllCommands, Access::eNone, Stage::eTransfer, Access::eTransferWrite),
        barrier(frame->image, Layout::eGeneral, Layout::eTransferSrcOptimal, Stage::eAllCommands,
                Access::eColorAttachmentWrite, Stage::eTransfer, Access::eTransferRead),
        barrier(hdr_overlay.image, Layout::eUndefined, Layout::eTransferDstOptimal,
                Stage::eAllCommands, Access::eNone, Stage::eTransfer, Access::eTransferWrite),
    };
    if (direct) {
        // The frame: General -> sampled by the encode -> General; no composite.
        pre[0] = barrier(frame->image, Layout::eGeneral, Layout::eShaderReadOnlyOptimal,
                         Stage::eAllCommands, Access::eMemoryWrite, Stage::eFragmentShader,
                         Access::eShaderSampledRead);
        pre[1] = pre[2];
    }
    barriers(std::span{pre.data(), (overlay ? 3u : 2u) - (direct ? 1u : 0u)});
    const vk::ClearColorValue black{std::array<float, 4>{0.0f, 0.0f, 0.0f, 1.0f}};
    if (!direct) {
        cmdbuf.clearColorImage(hdr_game.image, Layout::eTransferDstOptimal, black, color_range);
    }
    if (overlay) {
        const vk::ClearColorValue transparent{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
        cmdbuf.clearColorImage(hdr_overlay.image, Layout::eTransferDstOptimal, transparent,
                               color_range);
    }
    const vk::MemoryBarrier2 clear_done{
        .srcStageMask = Stage::eTransfer,
        .srcAccessMask = Access::eTransferWrite,
        .dstStageMask = Stage::eTransfer,
        .dstAccessMask = Access::eTransferWrite,
    };
    if (!direct) {
        cmdbuf.pipelineBarrier2(vk::DependencyInfo{
            .memoryBarrierCount = 1,
            .pMemoryBarriers = &clear_done,
        });
        cmdbuf.blitImage(frame->image, Layout::eTransferSrcOptimal, hdr_game.image,
                         Layout::eTransferDstOptimal,
                         MakeImageBlitFit(frame->width, frame->height, extent.width, extent.height),
                         vk::Filter::eLinear);
    }

    std::array<vk::ImageMemoryBarrier2, 4> post{
        barrier(hdr_game.image, Layout::eTransferDstOptimal, Layout::eShaderReadOnlyOptimal,
                Stage::eTransfer, Access::eTransferWrite, Stage::eFragmentShader,
                Access::eShaderSampledRead),
        barrier(frame->image, Layout::eTransferSrcOptimal, Layout::eGeneral, Stage::eTransfer,
                Access::eTransferRead, Stage::eAllCommands, Access::eColorAttachmentWrite),
        // The acquire semaphore is waited on at all commands: this transition comes after it.
        barrier(swapchain_image, Layout::eUndefined, Layout::eColorAttachmentOptimal,
                Stage::eColorAttachmentOutput, Access::eNone, Stage::eColorAttachmentOutput,
                Access::eColorAttachmentWrite),
        barrier(hdr_overlay.image, Layout::eTransferDstOptimal, Layout::eColorAttachmentOptimal,
                Stage::eTransfer, Access::eTransferWrite, Stage::eColorAttachmentOutput,
                Access::eColorAttachmentRead | Access::eColorAttachmentWrite),
    };
    if (direct) {
        post[0] = post[2]; // the back buffer
        post[1] = post[3]; // the menu layer
    }
    barriers(std::span{post.data(), (overlay ? 4u : 3u) - (direct ? 2u : 0u)});

    // bbport: the settings menu / FPS counter, at display resolution, into its own layer: the
    // encode shows it at paper white over the (possibly expanded) frame.
    if (overlay) {
        BbOverlay::Render(cmdbuf, hdr_overlay.view, extent);
        const std::array menu_done{
            barrier(hdr_overlay.image, Layout::eColorAttachmentOptimal,
                    Layout::eShaderReadOnlyOptimal, Stage::eColorAttachmentOutput,
                    Access::eColorAttachmentWrite, Stage::eFragmentShader,
                    Access::eShaderSampledRead),
        };
        barriers(menu_done);
    }

    const auto& settings = BbSettings::Get();
    const bool scrgb =
        swapchain.GetHdrFormat().colorSpace == vk::ColorSpaceKHR::eExtendedSrgbLinearEXT;
    // bbport: native mode (hdr_mode, live): the frame's gain map when it has one (made for the
    // frame this display buffer holds, vk_hdr_native.h), else plain SDR at paper white for this
    // frame (title, menus, loading, movies: nothing in them is meant to be brighter).
    const int mode = std::clamp(settings.hdr_mode.load(), 0, BbSettings::HdrModeCount - 1);
    // A generated frame (FSR 3.1 frame generation) has no gain map of its own: it takes the
    // real frame's it was interpolated towards (PresentGenerated), or every other frame would
    // fall back to plain SDR.
    const Frame* gain = hdr_gain_source ? hdr_gain_source : frame;
    const bool native = mode == BbSettings::HdrModeNative && gain->hdr_native && gain->hdr_gain;
    LogHdrState(scrgb, mode, native);
    // BB_HDR_DEBUG=1: the gain as a heat map over a grey picture (hdr_output.frag).
    static const bool debug = [] {
        const char* env = std::getenv("BB_HDR_DEBUG");
        return env && env[0] == '1';
    }();
    // The gain map covers the frame, which the blit above letterboxed into this rectangle.
    const vk::Rect2D fit = FitImage(s32(frame->width), s32(frame->height), s32(extent.width),
                                    s32(extent.height));
    const HostPasses::HdrOutputPass::Settings hdr{
        .paper_white = std::clamp(settings.hdr_paper_white.load(), BbSettings::HdrPaperWhiteMin,
                                  BbSettings::HdrPaperWhiteMax),
        .peak = BbSettings::HdrPeakNits(settings),
        .boost = mode == BbSettings::HdrModeNative && !native
                     ? 0.0f
                     : std::clamp(settings.hdr_boost.load(), 0.0f, 1.0f),
        .flags = (scrgb ? HostPasses::HdrOutputPass::FlagScRgb : 0u) |
                 (overlay ? HostPasses::HdrOutputPass::FlagOverlay : 0u) |
                 (native ? HostPasses::HdrOutputPass::FlagNative : 0u) |
                 (debug ? HostPasses::HdrOutputPass::FlagDebug : 0u) |
                 (mode == BbSettings::HdrModeNative && !native ? HostPasses::HdrOutputPass::FlagUiFrame : 0u) |
                 (settings.hdr_compare.load(std::memory_order_relaxed) ? HostPasses::HdrOutputPass::FlagCompare : 0u),
        .gain_offset = {float(fit.offset.x), float(fit.offset.y)},
        .gain_scale = {1.0f / float(std::max(fit.extent.width, 1u)),
                       1.0f / float(std::max(fit.extent.height, 1u))},
        .ui_white = mode == BbSettings::HdrModeNative
                        ? std::clamp(settings.hdr_ui_brightness.load(), BbSettings::HdrUiBrightnessMin,
                                     BbSettings::HdrUiBrightnessMax)
                        : 1.0f,
        .ui_vivid = mode == BbSettings::HdrModeNative ? std::clamp(settings.hdr_ui_color.load(), 0.0f, 1.0f) : 0.0f,
    };
    // bbport: MaxCLL, the brightest the content gets: native mode's highlights reach the peak;
    // expand mode's SDR white goes to boost's share of it. It changes with the settings, not
    // per frame: a display re-mapping its tone curve on every fallback would pump.
    const float expand_white =
        std::max(1.0f + (hdr.peak / hdr.paper_white - 1.0f) * hdr.boost, 1.0f);
    const float content_peak = mode == BbSettings::HdrModeNative
                                   ? hdr.peak
                                   : std::min(hdr.peak, hdr.paper_white * expand_white);
    swapchain.SetHdrMetadata(hdr.peak, content_peak, hdr.paper_white);
    if (native) {
        // Written on the draw scheduler's queue before this submission's wait (Present).
        const std::array gain_ready{
            barrier(vk::Image(gain->hdr_gain->image), Layout::eGeneral, Layout::eGeneral,
                    Stage::eAllCommands, Access::eMemoryWrite, Stage::eFragmentShader,
                    Access::eShaderSampledRead),
        };
        barriers(gain_ready);
    }
    const vk::ImageView game_view = direct ? frame->image_view : hdr_game.view;
    hdr_pass.Render(cmdbuf, game_view, overlay ? hdr_overlay.view : game_view,
                    native ? *gain->hdr_gain->view : game_view,
                    native ? Layout::eGeneral : Layout::eShaderReadOnlyOptimal,
                    swapchain.ImageView(), extent, hdr);

    const std::array to_present{
        barrier(swapchain_image, Layout::eColorAttachmentOptimal, Layout::ePresentSrcKHR,
                Stage::eColorAttachmentOutput, Access::eColorAttachmentWrite,
                Stage::eBottomOfPipe, Access::eNone),
        // Direct: the frame back to General (the UI alpha below may sample it; the next game
        // frame writes it).
        barrier(frame->image, Layout::eShaderReadOnlyOptimal, Layout::eGeneral,
                Stage::eFragmentShader, Access::eShaderSampledRead, Stage::eAllCommands,
                Access::eMemoryRead | Access::eMemoryWrite),
    };
    barriers(std::span{to_present.data(), direct ? 2u : 1u});

    // bbport: DLSS Frame Generation in HDR: the frame without its UI, placed and encoded as the
    // back buffer's frame was (same pass and settings, without the menu layer), so the two differ
    // only in the UI and the menu; DLSS-G takes it and the UI alpha made from the difference.
    if (!dlss_inputs || !DlssFrameGenHdr()) {
        return;
    }
    const Frame& hudless = dlss_hudless_frames[frame->id];
    if (!hudless.image) {
        return;
    }
    EnsureDlssHdrTargets(extent);
    if (auto* profiler = GpuProfiler::Get()) {
        profiler->PresentMark(cmdbuf, GpuProfiler::PresentPart::HudlessEncode);
    }
    auto hudless_hdr = hdr;
    hudless_hdr.flags &= ~HostPasses::HdrOutputPass::FlagOverlay;
    // bbport: a HUD-less frame of the back buffer's size is encoded from its own image: the
    // clear and the 1:1 blit into dlss_hdr_composite made an exact copy of it (same format, read
    // texel for texel). Experiment bit 1048576: the copy as before.
    const bool fill = hudless.width == extent.width && hudless.height == extent.height;
    if (fill && !BbToggle::Experiment(1048576)) {
        const std::array to_encode{
            barrier(hudless.image, Layout::eGeneral, Layout::eShaderReadOnlyOptimal,
                    Stage::eAllCommands, Access::eMemoryWrite, Stage::eFragmentShader,
                    Access::eShaderSampledRead),
            barrier(dlss_hdr_hudless.image, Layout::eUndefined, Layout::eColorAttachmentOptimal,
                    Stage::eAllCommands, Access::eNone, Stage::eColorAttachmentOutput,
                    Access::eColorAttachmentWrite),
        };
        barriers(to_encode);
        hdr_pass.Render(cmdbuf, hudless.image_view, hudless.image_view,
                        native ? *frame->hdr_gain->view : hudless.image_view,
                        native ? Layout::eGeneral : Layout::eShaderReadOnlyOptimal,
                        dlss_hdr_hudless.view, extent, hudless_hdr);
        const std::array encoded{
            barrier(dlss_hdr_hudless.image, Layout::eColorAttachmentOptimal, Layout::eGeneral,
                    Stage::eColorAttachmentOutput, Access::eColorAttachmentWrite,
                    Stage::eAllCommands, Access::eMemoryRead),
            barrier(hudless.image, Layout::eShaderReadOnlyOptimal, Layout::eGeneral,
                    Stage::eFragmentShader, Access::eShaderSampledRead, Stage::eAllCommands,
                    Access::eMemoryRead),
        };
        barriers(encoded);
    } else {
        const std::array to_copy{
            barrier(dlss_hdr_composite.image, Layout::eUndefined, Layout::eTransferDstOptimal,
                    Stage::eAllCommands, Access::eNone, Stage::eTransfer, Access::eTransferWrite),
            barrier(hudless.image, Layout::eGeneral, Layout::eTransferSrcOptimal,
                    Stage::eAllCommands, Access::eMemoryWrite, Stage::eTransfer,
                    Access::eTransferRead),
        };
        barriers(to_copy);
        cmdbuf.clearColorImage(dlss_hdr_composite.image, Layout::eTransferDstOptimal, black,
                               color_range);
        cmdbuf.pipelineBarrier2(vk::DependencyInfo{
            .memoryBarrierCount = 1,
            .pMemoryBarriers = &clear_done,
        });
        cmdbuf.blitImage(hudless.image, Layout::eTransferSrcOptimal, dlss_hdr_composite.image,
                         Layout::eTransferDstOptimal,
                         MakeImageBlitFit(hudless.width, hudless.height, extent.width,
                                          extent.height),
                         vk::Filter::eLinear);
        const std::array to_encode{
            barrier(dlss_hdr_composite.image, Layout::eTransferDstOptimal,
                    Layout::eShaderReadOnlyOptimal, Stage::eTransfer, Access::eTransferWrite,
                    Stage::eFragmentShader, Access::eShaderSampledRead),
            barrier(hudless.image, Layout::eTransferSrcOptimal, Layout::eGeneral,
                    Stage::eTransfer, Access::eTransferRead, Stage::eAllCommands,
                    Access::eMemoryRead),
            barrier(dlss_hdr_hudless.image, Layout::eUndefined, Layout::eColorAttachmentOptimal,
                    Stage::eAllCommands, Access::eNone, Stage::eColorAttachmentOutput,
                    Access::eColorAttachmentWrite),
        };
        barriers(to_encode);
        hdr_pass.Render(cmdbuf, dlss_hdr_composite.view, dlss_hdr_composite.view,
                        native ? *frame->hdr_gain->view : dlss_hdr_composite.view,
                        native ? Layout::eGeneral : Layout::eShaderReadOnlyOptimal,
                        dlss_hdr_hudless.view, extent, hudless_hdr);
        const std::array encoded{
            barrier(dlss_hdr_hudless.image, Layout::eColorAttachmentOptimal, Layout::eGeneral,
                    Stage::eColorAttachmentOutput, Access::eColorAttachmentWrite,
                    Stage::eAllCommands, Access::eMemoryRead),
        };
        barriers(encoded);
    }
    // bbport: the UI alpha from the frame and its HUD-less copy before the encode (both General,
    // the back buffer's size) instead of a copy of the back buffer: the encode is per pixel with
    // the same settings and gain for both, so where they are equal the encoded ones are too.
    // Not with the menu layer (it is in the back buffer only). Experiment bit 1048576: the copy.
    const bool ui_direct = fill && !overlay && frame->width == extent.width &&
                           frame->height == extent.height && !BbToggle::Experiment(1048576);
    dlss_fg->RecordPresent(cmdbuf, frame->dlss, dlss_hdr_hudless.image, dlss_hdr_hudless.view,
                           extent, swapchain_image, swapchain.GetHdrFormat().format, extent,
                           vk::Rect2D{{0, 0}, extent},
                           ui_direct ? frame->image_view : vk::ImageView{},
                           ui_direct ? hudless.image_view : vk::ImageView{});
}

void Presenter::LogHdrState(bool scrgb, int mode, bool native_frame) {
    if (mode != hdr_logged_mode) {
        hdr_logged_mode = mode;
        hdr_native_state = hdr_logged_native = -1;
        std::printf("HDR output: %s, mode %s (%s)\n",
                    scrgb ? "scRGB (FP16)" : "HDR10 (PQ, BT.2020)", BbSettings::HdrModeNames[mode],
                    mode == BbSettings::HdrModeNative
                        ? "highlights from the game's HDR scene, plain SDR where a frame has none"
                        : "highlights expanded from the SDR picture");
    }
    if (mode != BbSettings::HdrModeNative) {
        return;
    }
    // Menus, loading screens and movies have no scene: frames come and go without a gain map.
    const int state = native_frame ? 1 : 0;
    if (state != hdr_native_state) {
        hdr_native_state = state;
        ++hdr_native_switches;
    }
    const auto now = std::chrono::steady_clock::now();
    if (hdr_native_state == hdr_logged_native || now < hdr_next_log) {
        return;
    }
    std::printf("HDR native: %s",
                state ? "gain maps from the game's scene"
                      : "no gain map (no scene: title, menu, loading, movie), SDR");
    if (hdr_native_switches > 1) {
        std::printf(" (%u switches since the last line)", hdr_native_switches);
    }
    std::printf("\n");
    hdr_logged_native = state;
    hdr_native_switches = 0;
    hdr_next_log = now + std::chrono::seconds(5);
}

bool Presenter::IsVideoOutSurface(const AmdGpu::ColorBuffer& color_buffer) const {
    return std::ranges::find(vo_buffers_addr, color_buffer.Address()) != vo_buffers_addr.cend();
}

void Presenter::RecreateFrame(Frame* frame, u32 width, u32 height) {
    const vk::Device device = instance.GetDevice();
    if (frame->image_view) {
        device.destroyImageView(frame->image_view);
    }
    if (frame->image) {
        vmaDestroyImage(instance.GetAllocator(), frame->image, frame->allocation);
    }

    const vk::Format format = swapchain.GetSurfaceFormat().format;
    const vk::ImageCreateInfo image_info = {
        .flags = vk::ImageCreateFlagBits::eMutableFormat,
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eTransferDst |
                 vk::ImageUsageFlagBits::eTransferSrc | vk::ImageUsageFlagBits::eSampled,
    };

    const VmaAllocationCreateInfo alloc_info = {
        .flags = VMA_ALLOCATION_CREATE_WITHIN_BUDGET_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE,
        .requiredFlags = 0,
        .preferredFlags = 0,
        .pool = VK_NULL_HANDLE,
        .pUserData = nullptr,
    };

    VkImage unsafe_image{};
    VkImageCreateInfo unsafe_image_info = static_cast<VkImageCreateInfo>(image_info);

    VkResult result = vmaCreateImage(instance.GetAllocator(), &unsafe_image_info, &alloc_info,
                                     &unsafe_image, &frame->allocation, nullptr);
    if (result != VK_SUCCESS) [[unlikely]] {
        LOG_CRITICAL(Render_Vulkan, "Failed allocating texture with error {}",
                     vk::to_string(vk::Result{result}));
        UNREACHABLE();
    }
    frame->image = vk::Image{unsafe_image};
    SetObjectName(device, frame->image, "Frame image #{}", frame->id);

    const vk::ImageViewCreateInfo view_info = {
        .image = frame->image,
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange{
            .aspectMask = vk::ImageAspectFlagBits::eColor,
            .baseMipLevel = 0,
            .levelCount = 1,
            .baseArrayLayer = 0,
            .layerCount = 1,
        },
    };
    auto view = Check<"create frame image view">(device.createImageView(view_info));
    frame->image_view = view;
    if (SewerMotion::Enabled()) frame->sewer_final_format = image_info.format;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    bool resource_enabled = SewerMotion::Enabled();
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    resource_enabled |= BottleCaustic::CutSource::Run() != 0;
#endif
    if (resource_enabled)
        frame->post_present_backing = post_present_next_backing.fetch_add(1, std::memory_order_relaxed) + 1;
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (BottleCaustic::CutSource::Run()) frame->bottle_final_format = image_info.format;
#endif
    frame->width = width;
    frame->height = height;

    frame->is_hdr = swapchain.GetHDR();
}

Frame* Presenter::PrepareLastFrame() {
    if (last_submit_frame == nullptr) {
        return nullptr;
    }

    Frame* frame = last_submit_frame;

    while (true) {
        vk::Result result = instance.GetDevice().waitForFences(frame->present_done, false,
                                                               std::numeric_limits<u64>::max());
        if (result == vk::Result::eSuccess) {
            break;
        }
        if (result == vk::Result::eTimeout) {
            continue;
        }
        if (result == vk::Result::eErrorDeviceLost) {
            Breadcrumbs::ReportDeviceLost("waiting for a frame");
        }
        ASSERT_MSG(result != vk::Result::eErrorDeviceLost,
                   "Device lost during waiting for a frame");
    }

    if (frame->sewer_present_readback)
        RetireSewerPresent(*frame, sewer_swap_generation.load(std::memory_order_acquire));
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (frame->bottle_present_readback)
        RetireBottleCutPresent(*frame, bottle_swap_generation.load(std::memory_order_acquire));
#endif
    auto& scheduler = flip_scheduler;
    scheduler.EndRendering();
    const auto cmdbuf = scheduler.CommandBuffer();

    const auto frame_subresources = vk::ImageSubresourceRange{
        .aspectMask = vk::ImageAspectFlagBits::eColor,
        .baseMipLevel = 0,
        .levelCount = 1,
        .baseArrayLayer = 0,
        .layerCount = VK_REMAINING_ARRAY_LAYERS,
    };

    const auto pre_barrier =
        vk::ImageMemoryBarrier2{.srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentRead,
                                .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                                .oldLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
                                .newLayout = vk::ImageLayout::eGeneral,
                                .image = frame->image,
                                .subresourceRange{frame_subresources}};

    cmdbuf.pipelineBarrier2(vk::DependencyInfo{
        .imageMemoryBarrierCount = 1,
        .pImageMemoryBarriers = &pre_barrier,
    });

    // Flush frame creation commands.
    frame->ready_semaphore = scheduler.GetWorkSemaphore()->Handle();
    frame->ready_tick = scheduler.CurrentTick();
    SubmitInfo info{};
    scheduler.Flush(info);
    return frame;
}

static vk::Format GetFrameViewFormat(const Libraries::VideoOut::PixelFormat format) {
    switch (format) {
    case Libraries::VideoOut::PixelFormat::A8B8G8R8Srgb:
        return vk::Format::eR8G8B8A8Srgb;
    case Libraries::VideoOut::PixelFormat::A8R8G8B8Srgb:
        return vk::Format::eB8G8R8A8Srgb;
    case Libraries::VideoOut::PixelFormat::A2R10G10B10:
    case Libraries::VideoOut::PixelFormat::A2R10G10B10Srgb:
    case Libraries::VideoOut::PixelFormat::A2R10G10B10Bt2020Pq:
        return vk::Format::eA2R10G10B10UnormPack32;
    default:
        break;
    }
    UNREACHABLE_MSG("Unknown format={}", static_cast<u32>(format));
    return {};
}

Frame* Presenter::PrepareFrame(const Libraries::VideoOut::BufferAttributeGroup& attribute,
                               VAddr cpu_address) {
    BbTimeline::Note(BbTimeline::PipeTask, 4, draw_scheduler.CurrentTick());
    // bbport: scaled upscaler presets: the output-size display buffer drawn by the port.
    TemporalUpscaler::Display display{};
    // bbport (r75_present-dump-label): the view format names the byte order of a present dump.
    const bool upscaled = rasterizer->GetUpscaler().DisplayOverride(
        cpu_address, display, GetFrameViewFormat(attribute.attrib.pixel_format));
    VideoCore::ImageId image_id{};
    if (!upscaled) {
        auto desc = VideoCore::TextureCache::ImageDesc{attribute, cpu_address};
        image_id = texture_cache.FindImage(desc);
        texture_cache.UpdateImage(image_id);
    }

    Frame* frame = GetRenderFrame();
    frame->motion={};
    frame->motion_swap_epoch=0;
    // bbport: native HDR output: the gain map made at this display buffer's display pass (for
    // the frame it holds, a frame earlier in the command stream) goes with the frame to the
    // present thread; the frame's old one, presented (its fence was waited above), goes back.
    frame->hdr_native = rasterizer->GetHdrNative().TakeGainMap(cpu_address, frame->hdr_gain);

    const auto frame_subresources = vk::ImageSubresourceRange{
        .aspectMask = vk::ImageAspectFlagBits::eColor,
        .baseMipLevel = 0,
        .levelCount = 1,
        .baseArrayLayer = 0,
        .layerCount = VK_REMAINING_ARRAY_LAYERS,
    };

    // bbport: recorded like draws, on the recording threads. CommandBuffer() would first wait
    // for them to record everything handed over before (~90 us a frame of the draw recording
    // thread) and then submit from this thread.
    draw_scheduler.EndRendering();

    VideoCore::ImageViewInfo view_info{};
    view_info.format = GetFrameViewFormat(attribute.attrib.pixel_format);
    // Exclude alpha from output frame to avoid blending with UI.
    view_info.mapping.a = vk::ComponentSwizzle::eOne;

#ifdef BB_TEST_POST_PRESENT_RESOURCES
    std::optional<SewerPresent::Candidate> resource_candidate;
    std::shared_ptr<PostPresentResources::ResourceCapture> resources;
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    std::optional<BottleCutPresent::Issued> bottle_candidate;
    std::shared_ptr<PostPresentResources::ResourceCapture> bottle_resources;
    if (BottleCaustic::CutSource::Run()) {
        bottle_candidate = BottleCutPresent::Take(BbStats::frame_number.load(std::memory_order_relaxed));
        if (bottle_candidate && bottle_candidate->resource && upscaled) {
            bottle_resources = std::make_shared<PostPresentResources::ResourceCapture>(
                BottleCutPresent::ResourceKey(bottle_candidate->scene), bottle_candidate->resource->Tokens());
        }
    }
#endif
    if (SewerMotion::Enabled()) {
        resource_candidate = SewerPresent::Candidates().Take(BbStats::frame_number.load(std::memory_order_relaxed));
        if (resource_candidate && upscaled)
            resources = std::make_shared<PostPresentResources::ResourceCapture>(*resource_candidate);
    }
#endif
    vk::ImageView image_view{};
    vk::Extent2D image_size{};
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    // Only DisplayOverride can transfer a selected diagnostic epoch into this preparation.
    vk::Image prepared_source = display.image;
    bool bottle_mutable_view{};
#endif
    if (upscaled) {
        const auto device = instance.GetDevice();
        const vk::ImageViewCreateInfo view_create{
            .image = display.image,
            .viewType = vk::ImageViewType::e2D,
            .format = view_info.format,
            .components = {vk::ComponentSwizzle::eIdentity, vk::ComponentSwizzle::eIdentity,
                           vk::ComponentSwizzle::eIdentity, vk::ComponentSwizzle::eOne},
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        };
        image_view = Check(device.createImageView(view_create));
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
        if (display.bottle_scope.request || (bottle_candidate && bottle_candidate->raw)) {
            bottle_mutable_view = BottleDisplay182::RawMutableView(
                display.image, display.format, display.bottle_backing_flags, image_view, view_create);
        }
#endif
        draw_scheduler.DeferOperation([device, image_view] { device.destroyImageView(image_view); });
        image_size = vk::Extent2D{display.width, display.height};
        GrabFace(instance, draw_scheduler, display.image, display.width, display.height, display.format);
#ifdef BB_TEST_POST_PRESENT_RESOURCES
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        const auto& display_resources = resources ? resources : bottle_resources;
#else
        const auto& display_resources = resources;
#endif
        auto record_display_read = [image = display.image, resources = display_resources](vk::CommandBuffer cmdbuf) {
#else
        draw_scheduler.Record([image = display.image](vk::CommandBuffer cmdbuf) {
#endif
            const vk::ImageMemoryBarrier2 to_read{
                .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
                .oldLayout = vk::ImageLayout::eGeneral,
                .newLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
                .image = image,
                .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
            };
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_read});
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            if (resources) {
                resources->facts.display_read = to_read;
                resources->facts.display_barrier_cmd = cmdbuf;
            }
        };
        if (display_resources && display_resources->ValidTokens()) {
            draw_scheduler.RecordPostNative(display_resources->tokens.barrier,
                [record = std::move(record_display_read), token = display_resources->tokens.barrier](
                    vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
                    record(cmd);
                    encoder.NotePost(token);
                });
        } else {
            draw_scheduler.Record(std::move(record_display_read));
        }
#else
        });
#endif
    } else {
        auto& image = texture_cache.GetImage(image_id);
        image_view = *image.FindView(view_info).image_view;
        image_size = vk::Extent2D{image.info.size.width, image.info.size.height};
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
        if (display.bottle_scope.request) prepared_source = image.GetImage();
#endif
        // bbport: BB_PRESENT_DUMP_TRIGGER for the game's own display buffer too.
        if (auto& upscaler = rasterizer->GetUpscaler(); upscaler.PresentDumpDue()) {
            runtime.Transit(&image, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            runtime.FlushBarriers();
            upscaler.DumpPresented(image.GetImage(), image_size.width, image_size.height,
                                   view_info.format, cpu_address);
        }
        if (BbFaceShot::Pending()) {
            runtime.Transit(&image, vk::ImageLayout::eGeneral, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            runtime.FlushBarriers();
            GrabFace(instance, draw_scheduler, image.GetImage(), image_size.width, image_size.height, view_info.format);
        }
        runtime.Transit(&image, vk::ImageLayout::eShaderReadOnlyOptimal,
                        vk::PipelineStageFlagBits2::eFragmentShader,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_POST_PRESENT_RESOURCES) && defined(BB_TEST_SHARED_POST_GRAPH)
    if (const auto& selected = display.bottle_scope; selected.request) {
        const bool acquired = bottle_candidate && bottle_candidate->raw &&
            bottle_candidate->scene.key.request == selected.request && bottle_candidate->scene.key.scene == selected.scene &&
            bottle_candidate->scene.draw_frame == selected.frame && bottle_candidate->scene.last_epoch == selected.epoch;
        fmt::print("[bottle-cut] event=prepared-presenter-scope request={} scene={} frame={} epoch={} "
                   "selected_address={:x} prepare_address={:x} override={} candidate={} matched={} "
                   "image={:x} view={:x} format={} extent={}x{} prepare_tick={} backing_format={} "
                   "backing_flags={:x} raw_mutable_view={}\n",
                   selected.request, selected.scene, selected.frame, selected.epoch, selected.address,
                   cpu_address, upscaled, bool(bottle_candidate), acquired, std::bit_cast<u64>(prepared_source),
                   std::bit_cast<u64>(image_view), u32(view_info.format), image_size.width, image_size.height,
                   draw_scheduler.CurrentTick(), u32(display.format),
                   u32(VkImageCreateFlags(display.bottle_backing_flags)), bottle_mutable_view);
    }
#endif
    if (workflow_present.Armed()) {
        frame->workflow_display_override = upscaled;
        frame->workflow_input_width = image_size.width;
        frame->workflow_input_height = image_size.height;
    }
    expected_ratio = static_cast<float>(image_size.width) / static_cast<float>(image_size.height);

    // Vulkan has no sRGB variant of the 10-bit format, so an A2R10G10B10Srgb buffer reaches
    // the post process pass still sRGB encoded and has to be decoded there instead.
    pp_settings.srgb_input =
        attribute.attrib.pixel_format == Libraries::VideoOut::PixelFormat::A2R10G10B10Srgb;

    // bbport: frame generation: this frame's generated one, shown before it. Without a free
    // generated frame the interpolation still runs (its history stays whole) but none is shown.
    frame->generated = nullptr;
    std::optional<FrameGenerator::Job> gen_job;
    Frame* generated = nullptr;
    {
        const bool hdr = BbSettings::Get().hdr_output.load(std::memory_order_relaxed) !=
                             BbSettings::HdrOutputOff ||
                         frame->is_hdr;
        gen_job = frame_gen->Prepare(image_size, view_info.format, hdr, fsr_settings.enable,
                                     draw_scheduler.CurrentTick());
        if (gen_job && gen_job->present) {
            generated = TakeGeneratedFrame();
            if (generated) {
                if (generated->width != frame->width || generated->height != frame->height ||
                    generated->is_hdr != frame->is_hdr) {
                    RecreateFrame(generated, frame->width, frame->height);
                }
                std::atomic_ref<bool>(generated->generated_ok).store(false);
            } else {
                gen_job->present = false;
            }
        }
    }

    // bbport: DLSS Frame Generation: this game frame's number (its Reflex markers) and, with a
    // DLSS job, its inputs: the captures into the frame's slot and the frame without its UI
    // through the same post process as the frame (vk_streamline.h).
    frame->dlss = {};
    frame->dlss.index = dlss_fg->CurrentFrame();
    Frame* dlss_hudless = nullptr;
    if (gen_job && gen_job->dlss && dlss_fg->Available()) {
        dlss_hudless = &dlss_hudless_frames[frame->id];
        if (dlss_hudless->width != frame->width || dlss_hudless->height != frame->height ||
            dlss_hudless->is_hdr != frame->is_hdr || !dlss_hudless->image) {
            RecreateFrame(dlss_hudless, frame->width, frame->height);
        }
        dlss_fg->EnsureSlot(frame->id, gen_job->render_width, gen_job->render_height);
        frame->dlss.inputs = true;
        frame->dlss.slot = frame->id;
        frame->dlss.render_width = gen_job->render_width;
        frame->dlss.render_height = gen_job->render_height;
        frame->dlss.jitter = gen_job->jitter;
        frame->dlss.near_plane = gen_job->near_plane;
        frame->dlss.vertical_fov = gen_job->vertical_fov;
        frame->dlss.reset = gen_job->reset;
        frame->dlss.camera = gen_job->camera;
    }
    const bool dlss_srgb = view_info.format == vk::Format::eR8G8B8A8Srgb ||
                           view_info.format == vk::Format::eB8G8R8A8Srgb;

    // Numbered here, in command order; marked where the commands are recorded.
    const u32 stream = draw_scheduler.CrumbStream();
    const bool crumbs = Breadcrumbs::Enabled();
    const u32 fsr_crumb = crumbs ? Breadcrumbs::Note(stream, {.name = "presenter FSR"}) : 0;
    const u32 pp_crumb = crumbs ? Breadcrumbs::Note(stream, {.name = "presenter post process"}) : 0;
    // bbport: BB_GPU_PROFILE: the presenter's passes under labels of their own (they were
    // charged to the game's last pass).
    GpuProfiler* const profiler =
        GpuProfiler::Get() && GpuProfiler::Get()->Records(&draw_scheduler) ? GpuProfiler::Get()
                                                                            : nullptr;
    if (profiler) {
        profiler->Mark(0xF6E0'0003ull, [] { return std::string{"presenter: post process"}; });
    }
    if (upscaled && display.motion) {
        const auto& m=display.motion;
        const auto now=WorkflowPresent::Now();
        if (m.draw_ns && now>=m.draw_ns && now-m.draw_ns<=33'333'334ull &&
            m.writer==std::this_thread::get_id() &&
            m.timeline==draw_scheduler.GetWorkSemaphore()->Handle() &&
            m.draw_tick<=draw_scheduler.CurrentTick() && m.address==cpu_address &&
            m.image==display.image && image_size==vk::Extent2D{3840,2160} &&
            frame->width==3840 && frame->height==2160 && !frame->is_hdr && !fsr_settings.enable &&
            rasterizer->GetUpscaler().MotionConsume(m)) {
            frame->motion=m;
            frame->motion_swap_epoch=motion_swap_epoch.load(std::memory_order_relaxed);
        } else {
            std::printf("[bottle-motion-t198] event=refused id=%u why=prepared-source-epoch\n",u32(m.id));
        }
    }
    if (SewerMotion::Enabled()) {
        const u32 draw_frame = BbStats::frame_number.load(std::memory_order_relaxed);
        const auto draw_timeline = draw_scheduler.GetWorkSemaphore()->Handle();
        const SewerPresent::Override source{
            cpu_address, upscaled ? display.image : vk::Image{}, upscaled ? display.format : vk::Format{},
            image_size, draw_timeline, draw_scheduler.CurrentTick(),
        };
        auto proof = SewerPresent::pending.Take(source, draw_frame);
#ifdef BB_TEST_SHARED_POST_GRAPH
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        if (auto candidate = std::move(resource_candidate)) {
#else
        if (auto candidate = SewerPresent::Candidates().Take(draw_frame)) {
#endif
            using namespace SewerPresent;
            if (proof) {
                Finish(*proof, false, "legacy-and-provisional-display-conflict");
                proof.reset();
                CompleteCandidate(*candidate, "legacy-and-provisional-display-conflict", 0);
            } else {
                const auto& key = candidate->merge.key;
                const auto current_merge = SewerMotion::CurrentMerge(draw_timeline, draw_frame, key.loading, key.generation);
                const bool match = key.frame == draw_frame && current_merge &&
                    SameMerge(*current_merge, candidate->merge) && upscaled &&
                    candidate->Identity().MatchesOverride(source) && !BbEngine::Loading::ScreenUp() &&
                    key.loading == BbEngine::Loading::Generation() &&
                    SewerDisplayFormat(display.format, view_info.format) &&
                    image_view && frame->image && frame->image_view && frame->present_done &&
                    frame->image != display.image && frame->sewer_final_format == Format &&
                    frame->width == Extent.width && frame->height == Extent.height &&
                    workflow_present.Armed() && !frame->is_hdr && !frame->hdr_native && !gen_job && !frame->motion &&
                    !frame_gen->Enabled() && !FrameGenerator::DlssWanted() && !fsr_settings.enable &&
                    pp_settings.gamma == 1.0f && pp_settings.hdr == 0 && pp_settings.srgb_input == 0;
                if (!match) {
                    CompleteCandidate(*candidate, "provisional-prepared-source-stale-or-replaced", 0);
                } else if (!candidate->consume_epoch(source, candidate->display_generation, candidate->display_write)) {
                    CompleteCandidate(*candidate, "provisional-prepared-write-epoch-replaced", 0);
                } else {
                    candidate->consume_epoch = {};
                    frame->sewer_prepared_generation = ++sewer_next_frame_generation;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                    if (resources) {
                        resources->facts.input = {display.image, image_view, candidate->display_allocation,
                            candidate->display_generation, candidate->display_write, view_info.format, image_size};
                        resources->facts.epoch = true;
                    }
#endif
                    frame->sewer_prepared = std::make_shared<Capture>(std::move(*candidate), frame->id);
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                    frame->sewer_prepared->resources = std::move(resources);
#endif
                    frame->sewer_prepared->source.swap_generation = sewer_swap_generation.load(std::memory_order_acquire);
                }
            }
        }
#endif
        if (proof) {
            const bool match = upscaled && !BbEngine::Loading::ScreenUp() &&
                proof->merge.key.loading == BbEngine::Loading::Generation() &&
                SewerDisplayFormat(display.format, view_info.format) &&
                image_view && frame->image && frame->image_view && frame->present_done &&
                frame->image != display.image && frame->sewer_final_format == SewerPresent::Format &&
                frame->width == SewerPresent::Extent.width && frame->height == SewerPresent::Extent.height &&
                workflow_present.Armed() && !frame->is_hdr && !frame->hdr_native && !gen_job &&
                !frame_gen->Enabled() && !FrameGenerator::DlssWanted() && !fsr_settings.enable &&
                pp_settings.gamma == 1.0f && pp_settings.hdr == 0 && pp_settings.srgb_input == 0;
            if (match) {
                frame->sewer_prepared_generation = ++sewer_next_frame_generation;
                frame->sewer_prepared = std::make_shared<SewerPresent::Capture>(std::move(*proof));
                frame->sewer_prepared->source.swap_generation = sewer_swap_generation.load(std::memory_order_acquire);
            } else {
                SewerPresent::Finish(*proof, false, "ordinary-prepared-frame-scope");
            }
        }
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (BottleCaustic::CutSource::Run()) {
        using namespace BottleCutPresent;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        if (auto proof = std::move(bottle_candidate)) {
#else
        const u32 draw_frame = BbStats::frame_number.load(std::memory_order_relaxed);
        if (auto proof = Take(draw_frame)) {
#endif
            const Override actual{cpu_address, display.image, display.format, image_size,
                                  draw_scheduler.GetWorkSemaphore()->Handle(), draw_scheduler.CurrentTick()};
            const bool display_view = SewerDisplayFormat(display.format, view_info.format)
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
                || (proof->raw && bottle_mutable_view)
#endif
                ;
            const bool ordinary = upscaled && !BbEngine::Loading::ScreenUp() &&
                proof->scene.key.load == BbEngine::Loading::Generation() &&
                Compatible(proof->display, actual) && display_view &&
                image_view && frame->image && frame->image_view && frame->present_done &&
                frame->image != display.image && frame->bottle_final_format == Format &&
                frame->width == Extent.width && frame->height == Extent.height &&
                !frame->is_hdr && !frame->hdr_native && !gen_job && !frame->motion && !frame->sewer_prepared &&
                !frame_gen->Enabled() && !FrameGenerator::DlssWanted() && !fsr_settings.enable &&
                pp_settings.gamma == 1.0f && pp_settings.hdr == 0 && pp_settings.srgb_input == 0;
            if (!ordinary) {
                Complete(*proof, "ordinary-prepared-display-scope");
            } else if (!proof->consume_epoch(proof->scene, actual, proof->display_generation, proof->display_write)) {
                Complete(*proof, "prepared-display-epoch-replaced");
            } else {
                proof->consume_epoch = {};
                frame->bottle_incarnation = ++bottle_next_incarnation;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                if (bottle_resources) {
                    bottle_resources->facts.input = {display.image, image_view, proof->resource->display_allocation,
                        proof->display_generation, proof->display_write, view_info.format, image_size};
                    bottle_resources->facts.epoch = true;
                }
#endif
                frame->bottle_prepared = std::make_shared<Capture>(std::move(*proof));
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                frame->bottle_prepared->resources = std::move(bottle_resources);
#endif
                frame->bottle_prepared->source.swap_generation =
                    bottle_swap_generation.load(std::memory_order_acquire);
            }
        }
    }
#endif
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    auto prepared_resources = frame->sewer_prepared ? frame->sewer_prepared->resources : nullptr;
    auto target = prepared_resources
        ? PostPresentResources::PreparedResource(*frame, frame->sewer_prepared_generation, frame->sewer_final_format)
        : PostPresentResources::ResourceImage{};
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (frame->bottle_prepared && frame->bottle_prepared->resources) {
        prepared_resources = frame->bottle_prepared->resources;
        target = PostPresentResources::PreparedResource(*frame, frame->bottle_incarnation, frame->bottle_final_format);
    }
#endif
    auto record_postprocess = [this, frame, image_view, image_size, frame_subresources, stream,
                               prepared_resources, target,
#else
    draw_scheduler.Record([this, frame, image_view, image_size, frame_subresources, stream,
#endif
                           fsr_crumb, pp_crumb, fsr = fsr_settings, pp = pp_settings,
                           sewer = frame->sewer_prepared, sewer_image = frame->image,
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
                           bottle = frame->bottle_prepared,
#endif
#ifdef BB_TEST_POST_PRESENT_RESOURCES
                           sewer_view = frame->image_view, sewer_input_format = view_info.format](
                               vk::CommandBuffer cmdbuf, NativeWriteSuffix::Encoder* encoder) {
#else
                           sewer_view = frame->image_view, sewer_input_format = view_info.format](vk::CommandBuffer cmdbuf) {
#endif
        // Frames of different submissions may be recorded on two threads at once.
        std::scoped_lock lock{passes_mutex};
        const auto pre_barrier = vk::ImageMemoryBarrier2{
            .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
            .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentRead,
            .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
            .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eColorAttachmentOptimal,
            .image = frame->image,
            .subresourceRange{frame_subresources},
        };
        cmdbuf.pipelineBarrier2(vk::DependencyInfo{
            .imageMemoryBarrierCount = 1,
            .pImageMemoryBarriers = &pre_barrier,
        });
        if (fsr_crumb) {
            Breadcrumbs::Mark(cmdbuf, stream, fsr_crumb, false);
        }
        const vk::ImageView input = fsr_pass.Render(cmdbuf, image_view, image_size,
                                                    {frame->width, frame->height}, fsr,
                                                    frame->is_hdr);
        if (fsr_crumb) {
            Breadcrumbs::Mark(cmdbuf, stream, fsr_crumb, true);
            Breadcrumbs::Mark(cmdbuf, stream, pp_crumb, false);
        }
        pp_pass.Render(cmdbuf, input, image_size, *frame, pp);
        if (sewer && input && input == image_view && frame->image == sewer_image &&
            frame->image_view == sewer_view) {
            sewer->pp_input = input;
            sewer->pp_input_format = sewer_input_format;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            if (sewer->resources && target == PostPresentResources::PreparedResource(
                    *frame, frame->sewer_prepared_generation, frame->sewer_final_format)) {
                auto& facts = prepared_resources->facts;
                facts.target = target;
                facts.target_attachment = pre_barrier;
                facts.postprocess_cmd = cmdbuf;
                facts.postprocess = true;
                if (encoder) encoder->NotePost(prepared_resources->tokens.postprocess);
            }
#endif
            sewer->pp_encoded.store(true, std::memory_order_release);
        }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle && input && input == image_view && image_size == BottleCutPresent::Extent &&
            frame->image == sewer_image && frame->image_view == sewer_view) {
            bottle->pp_view = input;
            bottle->pp_format = sewer_input_format;
#ifdef BB_TEST_POST_PRESENT_RESOURCES
            if (bottle->resources && target == PostPresentResources::PreparedResource(
                    *frame, frame->bottle_incarnation, frame->bottle_final_format)) {
                auto& facts = prepared_resources->facts;
                facts.target = target;
                facts.target_attachment = pre_barrier;
                facts.postprocess_cmd = cmdbuf;
                facts.postprocess = true;
                if (encoder) encoder->NotePost(prepared_resources->tokens.postprocess);
            }
#endif
            bottle->pp_encoded.store(true, std::memory_order_release);
        }
#endif
        if (pp_crumb) {
            Breadcrumbs::Mark(cmdbuf, stream, pp_crumb, true);
        }
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    };
    if (prepared_resources && prepared_resources->ValidTokens()) {
        draw_scheduler.RecordPostNative(prepared_resources->tokens.postprocess,
            [record = std::move(record_postprocess)](vk::CommandBuffer cmd, NativeWriteSuffix::Encoder& encoder) {
                record(cmd, &encoder);
            });
    } else {
        draw_scheduler.Record([record = std::move(record_postprocess)](vk::CommandBuffer cmd) {
            record(cmd, nullptr);
        });
    }
#else
    });
#endif
    if (profiler && (dlss_hudless || gen_job)) {
        profiler->Mark(0xF6E0'0004ull, [] {
            return std::string{"presenter: frame generation (DLSS-G slot copies and HUD-less "
                               "post process, or FSR 3.1)"};
        });
    }
    draw_scheduler.Record([this, frame, image_view, image_size, frame_subresources,
                           pp = pp_settings, generated, gen_job, dlss_hudless, dlss_srgb,
                           dlss = dlss_fg.get(), fg = frame_gen.get()](vk::CommandBuffer cmdbuf) {
        std::scoped_lock lock{passes_mutex};
        // bbport: DLSS Frame Generation's inputs for this frame: copies of the captures, and the
        // frame without its UI through the same post process (its capture stays in General).
        if (dlss_hudless) {
            dlss->RecordInputs(cmdbuf, frame->id, fg->DepthImage(), fg->MotionImage(),
                               gen_job->render_width, gen_job->render_height);
            const auto hudless_barrier = [&](vk::ImageLayout from, vk::ImageLayout to) {
                const vk::ImageMemoryBarrier2 barrier{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                     vk::AccessFlagBits2::eMemoryWrite,
                    .oldLayout = from,
                    .newLayout = to,
                    .image = fg->HudlessImage(),
                    .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
                };
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            };
            const auto to_target = vk::ImageMemoryBarrier2{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eColorAttachmentOptimal,
                .image = dlss_hudless->image,
                .subresourceRange{frame_subresources},
            };
            cmdbuf.pipelineBarrier2(
                vk::DependencyInfo{.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_target});
            hudless_barrier(vk::ImageLayout::eGeneral, vk::ImageLayout::eShaderReadOnlyOptimal);
            pp_pass.Render(cmdbuf, fg->HudlessView(dlss_srgb), image_size, *dlss_hudless, pp);
            hudless_barrier(vk::ImageLayout::eShaderReadOnlyOptimal, vk::ImageLayout::eGeneral);
        }
        // bbport: frame generation: interpolated and composed, then the same post process
        // into the generated frame's image.
        if (gen_job && frame_gen->Record(cmdbuf, *gen_job, image_view) && generated) {
            const auto to_target = vk::ImageMemoryBarrier2{
                .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eColorAttachmentOptimal,
                .image = generated->image,
                .subresourceRange{frame_subresources},
            };
            cmdbuf.pipelineBarrier2(vk::DependencyInfo{
                .imageMemoryBarrierCount = 1,
                .pImageMemoryBarriers = &to_target,
            });
            pp_pass.Render(cmdbuf, frame_gen->ComposedView(), image_size, *generated, pp);
            std::atomic_ref<bool>(generated->generated_ok).store(true, std::memory_order_release);
        }
    });

    // Flush frame creation commands.
    BbStats::frame_number.fetch_add(1, std::memory_order_relaxed); // bbport: game frames shown
    frame->ready_semaphore = draw_scheduler.GetWorkSemaphore()->Handle();
    frame->ready_tick = draw_scheduler.CurrentTick();
    if (frame->sewer_prepared) {
        auto& sample = *frame->sewer_prepared;
        sample.source = SewerPreparedSource(*frame, sample.source.swap_generation);
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (sample.source.ready != sample.CapturedDisplay().draw_timeline ||
            sample.source.ready_tick < sample.CapturedDisplay().draw_tick) {
#else
        if (sample.source.ready != sample.proof.display.draw_timeline ||
            sample.source.ready_tick < sample.proof.display.draw_tick) {
#endif
            sample.refusal = "prepared-render-wait-epoch";
            frame->sewer_prepared.reset();
        }
    }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (frame->bottle_prepared) {
        auto& sample = *frame->bottle_prepared;
        sample.source = BottlePreparedSource(*frame, sample.source.swap_generation);
        if (!sample.source.Valid() || sample.source.ready != sample.proof.display.draw_timeline ||
            sample.source.ready_tick < sample.proof.display.draw_tick) {
            sample.Fail("prepared-render-wait-incarnation");
            frame->bottle_prepared.reset();
        }
    }
#endif
    if (generated) {
        if (workflow_present.Armed()) {
            generated->workflow_display_override = frame->workflow_display_override;
            generated->workflow_input_width = frame->workflow_input_width;
            generated->workflow_input_height = frame->workflow_input_height;
        }
        generated->ready_semaphore = frame->ready_semaphore;
        generated->ready_tick = frame->ready_tick;
        generated->hdr_native = false;
        frame->generated = generated;
    }
    SubmitInfo info{};
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    if (prepared_resources && (frame->sewer_prepared
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
                               || frame->bottle_prepared
#endif
                               )) {
        info.post_present_key = prepared_resources->key;
        info.observe_post_present_submit =
            [prepared_resources, owner = &draw_scheduler, tick = frame->ready_tick](
                const PostPresentSubmitObservation& actual) {
                prepared_resources->ObservePrepare(actual, *owner, tick);
            };
    }
#endif
    draw_scheduler.Flush(info);
    BbTimeline::Note(BbTimeline::PipeTask, 5, frame->ready_tick);
    dlss_fg->OnFrameSubmitted(); // bbport: Reflex: this frame's render submit ended

    // bbport: the GPU command thread runs at most BB_FRAMES_AHEAD (default 1) guest frames
    // ahead of the GPU: it waits here for the frame that many flips back. When the GPU is the
    // bottleneck it finishes frames at an even rate; without this bound the command thread ran
    // ahead and then blocked wherever a resource ran out, so flips (and the guest's frame
    // timing) came in bursts: 12.5/25 ms alternation at 80 FPS. 0 turns it off.
    static const u32 frames_ahead = [] {
        const char* env = std::getenv("BB_FRAMES_AHEAD");
        return env ? u32(std::max(0, std::atoi(env))) : 1u;
    }();
    if (frames_ahead) {
        recent_frame_ticks.push_back(frame->ready_tick);
        while (recent_frame_ticks.size() > frames_ahead) {
            const u64 tick = recent_frame_ticks.front();
            recent_frame_ticks.pop_front();
            if (recent_frame_ticks.size() == frames_ahead) {
                BbStats::WaitTimer timer{BbStats::present_wait_ns};
                draw_scheduler.Wait(tick);
            }
        }
    }
    return frame;
}

Frame* Presenter::PrepareBlankFrame(bool present_thread) {
    // Request a free presentation frame.
    Frame* frame = GetRenderFrame();
    frame->sewer_prepared.reset();
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (frame->bottle_prepared) frame->bottle_prepared->Fail("prepared-frame-replaced-by-blank");
    frame->bottle_prepared.reset();
#endif
    frame->motion={};
    frame->motion_swap_epoch=0;
    if (workflow_present.Armed()) {
        frame->workflow_display_override = false;
        frame->workflow_input_width = 0;
        frame->workflow_input_height = 0;
    }
    frame->hdr_native = false; // bbport: no game frame, no gain map

    auto& scheduler = present_thread ? present_scheduler : draw_scheduler;
    scheduler.EndRendering();

    const auto cmdbuf = scheduler.CommandBuffer();

    constexpr vk::ImageSubresourceRange simple_subresource = {
        .aspectMask = vk::ImageAspectFlagBits::eColor,
        .levelCount = 1,
        .layerCount = 1,
    };
    const auto pre_barrier = vk::ImageMemoryBarrier2{
        .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
        .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentRead,
        .dstStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
        .dstAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
        .oldLayout = vk::ImageLayout::eUndefined,
        .newLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .image = frame->image,
        .subresourceRange = simple_subresource,
    };

    const auto post_barrier = vk::ImageMemoryBarrier2{
        .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
        .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
        .dstStageMask = vk::PipelineStageFlagBits2::eFragmentShader,
        .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
        .oldLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .newLayout = vk::ImageLayout::eGeneral,
        .image = frame->image,
        .subresourceRange = simple_subresource,
    };

    const vk::RenderingAttachmentInfo attachment = {
        .imageView = frame->image_view,
        .imageLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .loadOp = vk::AttachmentLoadOp::eClear,
        .storeOp = vk::AttachmentStoreOp::eStore,
    };
    const vk::RenderingInfo rendering_info = {
        .renderArea =
            {
                .extent = {frame->width, frame->height},
            },
        .layerCount = 1,
        .colorAttachmentCount = 1u,
        .pColorAttachments = &attachment,
    };

    cmdbuf.pipelineBarrier2(vk::DependencyInfo{
        .imageMemoryBarrierCount = 1,
        .pImageMemoryBarriers = &pre_barrier,
    });

    cmdbuf.beginRendering(rendering_info);
    cmdbuf.endRendering();

    cmdbuf.pipelineBarrier2(vk::DependencyInfo{
        .imageMemoryBarrierCount = 1,
        .pImageMemoryBarriers = &post_barrier,
    });

    // Flush frame creation commands.
    frame->ready_semaphore = scheduler.GetWorkSemaphore()->Handle();
    frame->ready_tick = scheduler.CurrentTick();
    SubmitInfo info{};
    scheduler.Flush(info);
    return frame;
}

Frame* Presenter::TakeGeneratedFrame() {
    const vk::Device device = instance.GetDevice();
    for (u32 i = 0; i < generated_frames.size(); ++i) {
        Frame& frame = generated_frames[i];
        if (generated_busy[i].load(std::memory_order_acquire) ||
            device.getFenceStatus(frame.present_done) != vk::Result::eSuccess) {
            continue;
        }
        generated_busy[i].store(true, std::memory_order_release);
        return &frame;
    }
    return nullptr;
}

bool Presenter::PresentGenerated(Frame* frame, Frame* generated) {
    // Its commands went out with the real frame's submission.
    if (frame->ready_semaphore == draw_scheduler.GetWorkSemaphore()->Handle()) {
        draw_scheduler.WaitSubmitted(frame->ready_tick);
    }
    bool shown = false;
    if (std::atomic_ref<bool>(generated->generated_ok).load(std::memory_order_acquire) &&
        frame_gen->ShouldPresentGenerated()) {
        const auto start = FrameGenerator::Clock::now();
        hdr_gain_source = frame; // HDR output: the real frame's gain map (PresentHdr)
        Present(generated, true, false);
        hdr_gain_source = nullptr;
        shown = true;
        frame_gen->WaitForRealSlot(start);
    }
    const auto index = size_t(generated - generated_frames.data());
    generated_busy[index].store(false, std::memory_order_release);
    return shown;
}

bool Presenter::MotionMarker(vk::CommandBuffer cb,vk::Image target,const BottleMotion::Mark& mark) {
    using namespace BottleMotion;
    if (!motion_buffer) {
        const VkBufferCreateInfo ci{.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=512,
            .usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
        const VmaAllocationCreateInfo ai{.flags=VMA_ALLOCATION_CREATE_MAPPED_BIT|VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT,
            .usage=VMA_MEMORY_USAGE_AUTO_PREFER_HOST};
        VmaAllocationInfo map{};
        if (vmaCreateBuffer(instance.GetAllocator(),&ci,&ai,&motion_buffer,&motion_allocation,&map)!=VK_SUCCESS) {
            motion_buffer=VK_NULL_HANDLE;
            return false;
        }
        std::array<u32,128> words{};
        std::fill_n(words.begin(),64,0xff202020u);
        std::fill_n(words.begin()+64,64,0xffe0e0e0u);
        if (!map.pMappedData) {
            vmaDestroyBuffer(instance.GetAllocator(),motion_buffer,motion_allocation);
            motion_buffer=VK_NULL_HANDLE;
            return false;
        }
        std::memcpy(map.pMappedData,words.data(),sizeof(words));
        if (vmaFlushAllocation(instance.GetAllocator(),motion_allocation,0,sizeof(words))!=VK_SUCCESS) {
            vmaDestroyBuffer(instance.GetAllocator(),motion_buffer,motion_allocation);
            motion_buffer=VK_NULL_HANDLE;
            return false;
        }
    }
    const vk::ImageMemoryBarrier2 barrier{
        .srcStageMask=vk::PipelineStageFlagBits2::eAllTransfer,.srcAccessMask=vk::AccessFlagBits2::eTransferWrite,
        .dstStageMask=vk::PipelineStageFlagBits2::eAllTransfer,.dstAccessMask=vk::AccessFlagBits2::eTransferWrite,
        .oldLayout=vk::ImageLayout::eTransferDstOptimal,.newLayout=vk::ImageLayout::eTransferDstOptimal,
        .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
        .image=target,.subresourceRange={vk::ImageAspectFlagBits::eColor,0,1,0,1},
    };
    cb.pipelineBarrier2({.imageMemoryBarrierCount=1,.pImageMemoryBarriers=&barrier});
    const u64 bits=Tile(mark.run,mark.id);
    std::array<vk::BufferImageCopy,64> regions{};
    for (u32 i=0;i<regions.size();++i) {
        regions[i]={.bufferOffset=((bits>>(63-i))&1u)*256,
                   .imageSubresource={vk::ImageAspectFlagBits::eColor,0,0,1},
                   .imageOffset={TileX+s32(i%8)*Cell,TileY+s32(i/8)*Cell,0},
                   .imageExtent={u32(Cell),u32(Cell),1}};
    }
    cb.copyBufferToImage(motion_buffer,target,vk::ImageLayout::eTransferDstOptimal,regions);
    return true;
}

void Presenter::ReportMotionAttempts() {
    using BottleMotion::P;
    for (u32 i=0;i<motion_attempts_count;++i) {
        const auto& a=motion_attempts[i];
        const auto& m=a.mark;
        std::printf("[bottle-motion-t198] event=present run=%u id=%u arm=%u scene=%llu ready_tick=%llu "
                    "draw_tick=%llu submit_ns=%llu result_ns=%llu success=%u address=%llx write=%llu "
                    "display_image=%llx swap=%llx swap_image=%llx swap_epoch=%llu swap_index=%u\n",
                    u32(m.run),u32(m.id),m.arm,P(m.scene),P(a.ready_tick),P(m.draw_tick),P(a.submit_ns),
                    P(a.result_ns),u32(a.success),P(m.address),P(m.write),
                    P(std::bit_cast<u64>(VkImage(m.image))),P(std::bit_cast<u64>(VkSwapchainKHR(a.swap))),
                    P(std::bit_cast<u64>(VkImage(a.swap_image))),P(a.swap_epoch),a.swap_index);
    }
    motion_attempts_count=0;
}


void Presenter::Present(Frame* frame, bool is_reusing_frame, bool is_game_frame) {
    const auto motion=std::exchange(frame->motion,{});
    auto sewer = std::exchange(frame->sewer_prepared, {});
    bool sewer_copy_recorded = false;
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    auto bottle = std::exchange(frame->bottle_prepared, {});
    bool bottle_copy_recorded = false;
#endif
    vk::SwapchainKHR marker_swap{};
    vk::Image marker_image{};
    u32 marker_index{};
    if (workflow_present.Armed()) {
        static BbLiveKnobs::Knob<bool> finalize{"BB_WORKFLOW_PRESENT_FINALIZE", [](const char* value) {
            return value && std::strcmp(value, "1") == 0;
        }};
        if (finalize.Get()) {
            std::scoped_lock lock{Scheduler::submit_mutex};
            workflow_present.Finalize();
            ReportMotionAttempts();
        }
    }
    static FILE* const present_log = []() -> FILE* {
        const char* path = std::getenv("BB_PRESENT_LOG");
        if (!path || !*path) return nullptr;
        FILE* file = std::fopen(path, "w");
        if (!file) {
            std::perror("Cannot open BB_PRESENT_LOG");
            return nullptr;
        }
        std::fprintf(file, "t_s,interval_ms,acquire_ms,record_ms,submit_ms,present_ms,total_ms,game_frame,ready_tick\n");
        return file;
    }();
    // bbport: frame generation: one more swapchain image while it is on; the generated frame
    // goes first, the real one half a game frame later.
    const bool real_game_frame = !is_reusing_frame && is_game_frame;
    const auto present_start = FrameGenerator::Clock::now();
    bool generated_made = false, generated_shown = false;
    if (real_game_frame) {
        if (swapchain.SetExtraImages(frame_gen->WantsExtraImage() ? 1 : 0) &&
            window.GetWidth() != 0 && window.GetHeight() != 0) {
            dlss_fg->BeforeSwapchainChange();
            swapchain.Recreate(window.GetWidth(), window.GetHeight());
            if (SewerMotion::Enabled()) sewer_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (BottleCaustic::CutSource::Run()) bottle_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#endif
        if (BottleMotion::Run()) motion_swap_epoch.fetch_add(1,std::memory_order_relaxed);
            std::printf("Frame generation: swapchain of %u images\n", swapchain.GetImageCount());
        }
        if (Frame* generated = std::exchange(frame->generated, nullptr)) {
            generated_made = true;
            generated_shown = PresentGenerated(frame, generated);
        }
    }
    const auto note_real = [&] {
        if (real_game_frame && frame_gen->Enabled()) {
            frame_gen->OnRealPresented(present_start, generated_shown, generated_made);
        }
    };

    // Free the frame for reuse
    const auto free_frame = [&] {
        if (!is_reusing_frame) {
            last_submit_frame = frame;
            std::scoped_lock fl{free_mutex};
            free_queue.push(frame);
            free_cv.notify_one();
        }
    };

    // bbport: nothing to present to while the window is minimised (a 0x0 surface, issue #31).
    if (window.GetWidth() == 0 || window.GetHeight() == 0) {
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (sewer) sewer->FailCandidate("provisional-present-minimized");
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle) bottle->Fail("minimized-before-present");
#endif
        free_frame();
        return;
    }
    // Recreate the swapchain if the window was resized (or was minimised at the last try).
    if (window.GetWidth() != swapchain.GetWidth() || window.GetHeight() != swapchain.GetHeight() ||
        !swapchain.IsPresentable()) {
        dlss_fg->BeforeSwapchainChange();
        swapchain.Recreate(window.GetWidth(), window.GetHeight());
        if (SewerMotion::Enabled()) sewer_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (BottleCaustic::CutSource::Run()) bottle_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#endif
        if (BottleMotion::Run()) motion_swap_epoch.fetch_add(1,std::memory_order_relaxed);
        if (!swapchain.IsPresentable()) {
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (sewer) sewer->FailCandidate("provisional-swapchain-unavailable");
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (bottle) bottle->Fail("swapchain-unavailable-before-present");
#endif
            free_frame();
            return;
        }
    }

    const auto acquire_start = present_log ? FrameGenerator::Clock::now() : present_start;
    if (!swapchain.AcquireNextImage()) {
        dlss_fg->BeforeSwapchainChange();
        swapchain.Recreate(window.GetWidth(), window.GetHeight());
        if (SewerMotion::Enabled()) sewer_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (BottleCaustic::CutSource::Run()) bottle_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#endif
        if (BottleMotion::Run()) motion_swap_epoch.fetch_add(1,std::memory_order_relaxed);
        if (!swapchain.AcquireNextImage()) {
            // User resizes the window too fast and GPU can't keep up. Skip this frame.
            LOG_WARNING(Render_Vulkan, "Skipping frame!");
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (sewer) sewer->FailCandidate("provisional-swap-image-not-acquired");
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            if (bottle) bottle->Fail("acquire-failed-dropped-frame");
#endif
            free_frame();
            return;
        }
    }
    const auto acquire_end = present_log ? FrameGenerator::Clock::now() : present_start;

    // Reset fence for queue submission. Do it here instead of GetRenderFrame() because we may
    // skip frame because of slow swapchain recreation. If a frame skip occurs, we skip signal
    // the frame's present fence and future GetRenderFrame() call will hang waiting for this frame.
    const auto reset_result = instance.GetDevice().resetFences(frame->present_done);
    ASSERT_MSG(reset_result == vk::Result::eSuccess,
               "Unexpected error resetting present done fence: {}", vk::to_string(reset_result));

    // bbport: the game frame is blitted (letterboxed) straight into the swapchain image.
    const vk::Image swapchain_image = swapchain.Image();
    auto& scheduler = present_scheduler;
    const auto cmdbuf = scheduler.CommandBuffer();
    // bbport: BB_GPU_PROFILE: this present's parts, timed in its own command buffer.
    GpuProfiler* const present_profiler = GpuProfiler::Get();
    if (present_profiler) {
        present_profiler->PresentBegin(cmdbuf);
        present_profiler->PresentMark(cmdbuf, GpuProfiler::PresentPart::Frame);
    }
    DumpFinalFrameIfDue(instance, scheduler, cmdbuf, frame->image, frame->width, frame->height,
                        swapchain.GetSurfaceFormat().format);

    if (EmulatorSettings.IsVkHostMarkersEnabled()) {
        cmdbuf.beginDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
            .pLabelName = "Present",
        });
    }

    // bbport: HDR output (hdr in lantern.ini) while the swapchain has the HDR format.
    const bool hdr_output = swapchain.IsHdrOutput() && hdr_pass.IsCreated();
    BbSettings::Get().hdr_output.store(
        !hdr_output ? BbSettings::HdrOutputOff
        : swapchain.GetHdrFormat().colorSpace == vk::ColorSpaceKHR::eExtendedSrgbLinearEXT
            ? BbSettings::HdrOutputScRgb
            : BbSettings::HdrOutputHdr10,
        std::memory_order_relaxed);
    if (hdr_output) {
        if (sewer) sewer->refusal = "actual-hdr-presentation";
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle) bottle->refusal = "actual-hdr-presentation";
#endif
        const vk::Extent2D extent = swapchain.GetExtent();
        SetExpectedGameSize(s32(extent.width), s32(extent.height));
        PresentHdr(cmdbuf, frame, extent, real_game_frame && frame->dlss.inputs);
    } else {
        const vk::Extent2D extent = swapchain.GetExtent();
        SetExpectedGameSize(s32(extent.width), s32(extent.height));
        const vk::ImageSubresourceRange color_range{
            .aspectMask = vk::ImageAspectFlagBits::eColor,
            .baseMipLevel = 0,
            .levelCount = 1,
            .baseArrayLayer = 0,
            .layerCount = VK_REMAINING_ARRAY_LAYERS,
        };
        const std::array pre_barriers{
            vk::ImageMemoryBarrier{
                .srcAccessMask = vk::AccessFlagBits::eNone,
                .dstAccessMask = vk::AccessFlagBits::eTransferWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eTransferDstOptimal,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = swapchain_image,
                .subresourceRange = color_range,
            },
            vk::ImageMemoryBarrier{
                .srcAccessMask = vk::AccessFlagBits::eColorAttachmentWrite,
                .dstAccessMask = vk::AccessFlagBits::eTransferRead,
                .oldLayout = vk::ImageLayout::eGeneral,
                .newLayout = vk::ImageLayout::eTransferSrcOptimal,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = frame->image,
                .subresourceRange = color_range,
            },
        };
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        constexpr auto before_blit = vk::PipelineStageFlagBits::eAllCommands;
        constexpr auto during_blit = vk::PipelineStageFlagBits::eTransfer;
        cmdbuf.pipelineBarrier(before_blit, during_blit, vk::DependencyFlagBits::eByRegion,
                               {}, {}, pre_barriers);
#else
        cmdbuf.pipelineBarrier(vk::PipelineStageFlagBits::eAllCommands,
                               vk::PipelineStageFlagBits::eTransfer, vk::DependencyFlagBits::eByRegion,
                               {}, {}, pre_barriers);
#endif
        // bbport: the black bars are only needed where the fitted blit leaves part of the image
        // uncovered; a frame of the swapchain's aspect (the usual case: the game renders at the
        // window size) overwrites every pixel, and the full-screen clear plus its barrier were
        // one more full-resolution write each present. BB_PRESENT_ALWAYS_CLEAR=1: always clear.
        static const bool always_clear = [] {
            const char* env = std::getenv("BB_PRESENT_ALWAYS_CLEAR");
            return env && env[0] == '1';
        }();
        const vk::Rect2D fit = FitImage(s32(frame->width), s32(frame->height), s32(extent.width),
                                        s32(extent.height));
        const bool covers = fit.offset.x == 0 && fit.offset.y == 0 &&
                            fit.extent.width == extent.width && fit.extent.height == extent.height;
        if (always_clear || !covers) {
            const vk::ClearColorValue black{std::array<float, 4>{0.0f, 0.0f, 0.0f, 1.0f}};
            cmdbuf.clearColorImage(swapchain_image, vk::ImageLayout::eTransferDstOptimal, black,
                                   color_range);
            const vk::MemoryBarrier clear_done{
                .srcAccessMask = vk::AccessFlagBits::eTransferWrite,
                .dstAccessMask = vk::AccessFlagBits::eTransferWrite,
            };
            cmdbuf.pipelineBarrier(vk::PipelineStageFlagBits::eTransfer,
                                   vk::PipelineStageFlagBits::eTransfer,
                                   vk::DependencyFlagBits::eByRegion, clear_done, {}, {});
        }
        const bool sewer_overlay = sewer && BbOverlay::Visible();
        if (sewer) {
            using namespace SewerPresent;
            const Gate gate{
                .real = real_game_frame,
                .blank = !is_game_frame,
                .reused = is_reusing_frame,
                .generated = generated_made || frame->generated || hdr_gain_source ||
                             frame_gen->Enabled() || FrameGenerator::DlssWanted(),
                .hdr = hdr_output || frame->is_hdr,
                .overlays = sewer_overlay || bool(motion),
                .secondary = fsr_settings.enable || always_clear,
                .full_cover = covers,
                .output = extent,
                .surface = swapchain.GetSurfaceFormat(),
            };
            const auto current = SewerPreparedSource(*frame, sewer_swap_generation.load(std::memory_order_acquire));
            if (!workflow_present.Armed() || !Ordinary(gate) || !SameSource(sewer->source, current) ||
                sewer->source.ready != draw_scheduler.GetWorkSemaphore()->Handle() ||
                !swapchain_image || swapchain_image == current.image || frame->sewer_present_readback) {
                sewer->refusal = "ordinary-1to1-sdr-present-source";
            } else if (instance.GetGraphicsQueueFamilyIndex() != instance.GetPresentQueueFamilyIndex()) {
                sewer->refusal = "unproved-present-queue-family";
            } else {
                const auto swap = swapchain.GetHandle();
                const auto [status, images] = instance.GetDevice().getSwapchainImagesKHR(swap);
                const auto it = std::ranges::find(images, swapchain_image);
                if (status != vk::Result::eSuccess || it == images.end() ||
                    std::ranges::count(images, swapchain_image) != 1) {
                    sewer->refusal = "actual-acquired-swap-image";
                } else if (!sewer->Allocate(instance.GetAllocator())) {
                    sewer->refusal = "present-staging-allocation";
                } else {
                    sewer->swap = swap;
                    sewer->swap_image = swapchain_image;
                    sewer->swap_index = u32(it - images.begin());
                    sewer->present_timeline = scheduler.GetWorkSemaphore()->Handle();
                    sewer->present_tick = scheduler.CurrentTick();
                    sewer->swap_ready = swapchain.GetPresentReadySemaphore();
#ifdef BB_TEST_SHARED_POST_GRAPH
                    if (sewer->candidate) sewer->acquire = swapchain.GetImageAcquiredSemaphore();
#endif
                    sewer->Copy(cmdbuf);
                    sewer_copy_recorded = true;
                }
            }
        }
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle) {
            using namespace BottleCutPresent;
            const Gate gate{
                .real = real_game_frame,
                .blank = !is_game_frame,
                .reused = is_reusing_frame,
                .generated = generated_made || frame->generated || hdr_gain_source ||
                             frame_gen->Enabled() || FrameGenerator::DlssWanted(),
                .hdr = hdr_output || frame->is_hdr,
                .overlay = BbOverlay::Visible() || bool(motion) || bool(sewer),
                .secondary = fsr_settings.enable || always_clear,
                .full_cover = covers,
                .output = extent,
                .surface = swapchain.GetSurfaceFormat(),
            };
            const auto current = BottlePreparedSource(*frame, bottle_swap_generation.load(std::memory_order_acquire));
            if (!gate.Ordinary() || !current.Valid() || bottle->source != current ||
                current.ready != draw_scheduler.GetWorkSemaphore()->Handle() ||
                !swapchain_image || swapchain_image == current.image || frame->bottle_present_readback) {
                bottle->refusal = "ordinary-prepared-1to1-sdr-present";
            } else if (instance.GetGraphicsQueueFamilyIndex() != instance.GetPresentQueueFamilyIndex()) {
                bottle->refusal = "unproved-present-queue-family";
            } else {
                const auto swap = swapchain.GetHandle();
                const auto [status, images] = instance.GetDevice().getSwapchainImagesKHR(swap);
                const auto it = std::ranges::find(images, swapchain_image);
                if (status != vk::Result::eSuccess || it == images.end() ||
                    std::ranges::count(images, swapchain_image) != 1) {
                    bottle->refusal = "unproved-actual-acquired-image";
                } else if (!bottle->Allocate(instance.GetAllocator())) {
                    bottle->refusal = "present-staging-allocation";
                } else {
                    bottle->attempt = {.swap = swap, .swap_image = swapchain_image,
                                       .acquire = swapchain.GetImageAcquiredSemaphore(),
                                       .ready = swapchain.GetPresentReadySemaphore(),
                                       .timeline = scheduler.GetWorkSemaphore()->Handle(),
                                       .tick = scheduler.CurrentTick(), .image_index = u32(it - images.begin())};
                    bottle->Copy(cmdbuf);
                    bottle_copy_recorded = true;
                }
            }
        }
#endif
#ifdef BB_TEST_POST_PRESENT_RESOURCES
        const auto blit_region = MakeImageBlitFit(frame->width, frame->height, extent.width, extent.height);
        cmdbuf.blitImage(frame->image, vk::ImageLayout::eTransferSrcOptimal, swapchain_image,
                         vk::ImageLayout::eTransferDstOptimal, blit_region, vk::Filter::eLinear);
        if (sewer_copy_recorded && sewer->resources)
            PostPresentResources::NotePreparedTransfer(*sewer->resources, cmdbuf, swapchain_image,
                                                       blit_region, pre_barriers[1], before_blit, during_blit);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle_copy_recorded && bottle->resources)
            PostPresentResources::NotePreparedTransfer(*bottle->resources, cmdbuf, swapchain_image,
                                                       blit_region, pre_barriers[1], before_blit, during_blit);
#endif
#else
        cmdbuf.blitImage(frame->image, vk::ImageLayout::eTransferSrcOptimal, swapchain_image,
                         vk::ImageLayout::eTransferDstOptimal,
                         MakeImageBlitFit(frame->width, frame->height, extent.width, extent.height),
                         vk::Filter::eLinear);
#endif
        // bbport: the settings menu / FPS counter over the frame, at display resolution.
        const bool overlay = BbOverlay::Visible();
        if (sewer_copy_recorded && overlay) sewer->refusal = "overlay-appeared-after-sample";
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (bottle_copy_recorded && overlay) bottle->refusal = "overlay-appeared-after-sample";
#endif
        if (motion) {
            const auto surface=swapchain.GetSurfaceFormat();
            if (workflow_present.Armed() && real_game_frame && !generated_made && !frame->generated &&
                motion.timeline==frame->ready_semaphore && motion.draw_tick<=frame->ready_tick &&
                frame->motion_swap_epoch==motion_swap_epoch.load(std::memory_order_relaxed) &&
                !overlay && !frame->is_hdr && !fsr_settings.enable &&
                !frame_gen->Enabled() && !FrameGenerator::DlssWanted() &&
                covers && extent==vk::Extent2D{3840,2160} && frame->width==3840 && frame->height==2160 &&
                surface.format==vk::Format::eB8G8R8A8Unorm &&
                surface.colorSpace==vk::ColorSpaceKHR::eSrgbNonlinear &&
                motion_attempts_count<motion_attempts.size() && swapchain_image) {
                const auto [status,images]=instance.GetDevice().getSwapchainImagesKHR(swapchain.GetHandle());
                const auto it=std::ranges::find(images,swapchain_image);
                if (status==vk::Result::eSuccess && it!=images.end() &&
                    MotionMarker(cmdbuf,swapchain_image,motion)) {
                    marker_swap=swapchain.GetHandle();
                    marker_image=swapchain_image;
                    marker_index=u32(it-images.begin());
                }
            }
            if (!marker_image) {
                std::printf("[bottle-motion-t198] event=refused id=%u why=present-sdr-marker-gate\n",u32(motion.id));
            }
        }
        const std::array post_barriers{
            vk::ImageMemoryBarrier{
                .srcAccessMask = vk::AccessFlagBits::eTransferWrite,
                .dstAccessMask = overlay ? vk::AccessFlagBits::eColorAttachmentRead |
                                               vk::AccessFlagBits::eColorAttachmentWrite
                                         : vk::AccessFlagBits::eNone,
                .oldLayout = vk::ImageLayout::eTransferDstOptimal,
                .newLayout = overlay ? vk::ImageLayout::eColorAttachmentOptimal
                                     : vk::ImageLayout::ePresentSrcKHR,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = swapchain_image,
                .subresourceRange = color_range,
            },
            vk::ImageMemoryBarrier{
                .srcAccessMask = vk::AccessFlagBits::eTransferRead,
                .dstAccessMask = vk::AccessFlagBits::eColorAttachmentWrite,
                .oldLayout = vk::ImageLayout::eTransferSrcOptimal,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = frame->image,
                .subresourceRange = color_range,
            },
        };
        cmdbuf.pipelineBarrier(vk::PipelineStageFlagBits::eTransfer,
                               vk::PipelineStageFlagBits::eAllCommands,
                               vk::DependencyFlagBits::eByRegion, {}, {}, post_barriers);
        if (overlay) {
            BbOverlay::Render(cmdbuf, swapchain.ImageView(), extent);
            const vk::ImageMemoryBarrier to_present{
                .srcAccessMask = vk::AccessFlagBits::eColorAttachmentWrite,
                .dstAccessMask = vk::AccessFlagBits::eNone,
                .oldLayout = vk::ImageLayout::eColorAttachmentOptimal,
                .newLayout = vk::ImageLayout::ePresentSrcKHR,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = swapchain_image,
                .subresourceRange = color_range,
            };
            cmdbuf.pipelineBarrier(vk::PipelineStageFlagBits::eColorAttachmentOutput,
                                   vk::PipelineStageFlagBits::eBottomOfPipe,
                                   vk::DependencyFlagBits::eByRegion, {}, {}, to_present);
        }
        // bbport: DLSS Frame Generation: the frame without its UI at the back buffer's size and
        // the UI alpha image, from the finished back buffer (vk_streamline.h).
        if (real_game_frame && frame->dlss.inputs) {
            const Frame& hudless = dlss_hudless_frames[frame->id];
            // bbport: without the menu layer a frame filling the back buffer is the back
            // buffer (a 1:1 blit): the UI alpha compares it with its HUD-less copy directly,
            // the same mask without the copy (Experiment bit 1048576: the copy).
            const bool ui_direct = !overlay && !BbToggle::Experiment(1048576);
            dlss_fg->RecordPresent(cmdbuf, frame->dlss, hudless.image, hudless.image_view,
                                   {frame->width, frame->height}, swapchain_image,
                                   swapchain.GetSurfaceFormat().format, extent, fit,
                                   ui_direct ? frame->image_view : vk::ImageView{},
                                   ui_direct ? hudless.image_view : vk::ImageView{});
        }
    }
    if (EmulatorSettings.IsVkHostMarkersEnabled()) {
        cmdbuf.endDebugUtilsLabelEXT();
    }

    if (present_profiler) {
        present_profiler->PresentEnd(cmdbuf);
    }

    // Flush vulkan commands.

    // bbport: the frame's submission goes out from a recording thread (BB_ASYNC_SUBMIT); this
    // one, waiting for it on the same queue, must not get there first.
    const auto record_end = present_log ? FrameGenerator::Clock::now() : present_start;
    if (frame->ready_semaphore == draw_scheduler.GetWorkSemaphore()->Handle()) {
        draw_scheduler.WaitSubmitted(frame->ready_tick);
    }
    SubmitInfo info{};
    info.AddWait(swapchain.GetImageAcquiredSemaphore());
    info.AddWait(frame->ready_semaphore, frame->ready_tick);
    const auto swap_ready = swapchain.GetPresentReadySemaphore();
    if (sewer_copy_recorded && sewer->swap_ready != swap_ready)
        sewer->refusal = "present-ready-semaphore-replaced";
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (sewer_copy_recorded && sewer->candidate &&
        (sewer->acquire != swapchain.GetImageAcquiredSemaphore() || sewer->slot != frame->id ||
         sewer->source.fence != frame->present_done || sewer->source.ready != frame->ready_semaphore ||
         sewer->source.ready_tick != frame->ready_tick || sewer->present_tick != scheduler.CurrentTick())) {
        sewer->refusal = "provisional-actual-submit-sync-replaced";
    }
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (bottle_copy_recorded && (bottle->attempt.ready != swap_ready ||
        bottle->attempt.acquire != swapchain.GetImageAcquiredSemaphore() ||
        bottle->source.ready_tick != frame->ready_tick || bottle->source.ready != frame->ready_semaphore ||
        bottle->source.fence != frame->present_done || bottle->attempt.tick != scheduler.CurrentTick())) {
        bottle->refusal = "actual-submit-sync-replaced";
    }
#endif
    info.AddSignal(swap_ready);
    info.AddSignal(frame->present_done);
#ifdef BB_TEST_POST_PRESENT_RESOURCES
    const auto observe = [&](const std::shared_ptr<PostPresentResources::ResourceCapture>& resources, u64 tick) {
        info.post_present_key = resources->key;
        info.observe_post_present_submit =
            [resources, owner = &scheduler, tick](
                const PostPresentSubmitObservation& actual) {
                resources->ObservePresent(actual, *owner, tick);
            };
    };
    if (sewer_copy_recorded && !sewer->refusal && sewer->resources)
        observe(sewer->resources, sewer->present_tick);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (bottle_copy_recorded && !bottle->refusal && bottle->resources)
        observe(bottle->resources, bottle->attempt.tick);
#endif
#endif
    scheduler.Flush(info);
    const auto submit_end = present_log ? FrameGenerator::Clock::now() : present_start;

    // Present to swapchain. bbport: DLSS Frame Generation's constants, tags and markers for
    // this frame go out right before (none for a frame shown again).
    const DlssFrameInfo* dlss_info = real_game_frame ? &frame->dlss : nullptr;
    dlss_fg->BeforePresent(dlss_info, BbOverlay::MenuOpen(), hdr_output);
    if (real_game_frame) {
        LanternAntiLag::BeforePresent();
    }
    bool presented;
    {
        std::scoped_lock submit_lock{Scheduler::submit_mutex};
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        const bool bottle_same_swap = bottle_copy_recorded &&
            bottle->source.swap_generation == bottle_swap_generation.load(std::memory_order_acquire) &&
            bottle->attempt.swap == swapchain.GetHandle() && bottle->attempt.swap_image == swapchain.Image() &&
            bottle->attempt.ready == swapchain.GetPresentReadySemaphore();
        const auto note_bottle_attempt = [&](u64 start, u64 end) {
            if (BottleCaustic::CutSource::Run()) ++bottle_present_serial;
            if (bottle) {
                bottle->attempt.serial = bottle_present_serial;
                bottle->attempt.submit_ns = start;
                bottle->attempt.result_ns = end;
                bottle->attempt.success = presented && bottle_same_swap && bottle->attempt.swap == swapchain.GetHandle();
            }
        };
#endif
        if (workflow_present.Armed()) {
            const auto output = swapchain.GetExtent();
            const auto surface = swapchain.GetSurfaceFormat();
            const auto mode = swapchain.GetPresentMode();
            const char* role = hdr_gain_source ? "internal-generated"
                             : real_game_frame ? "real"
                             : is_reusing_frame ? "reuse" : "blank";
#ifdef BB_TEST_SHARED_POST_GRAPH
            const bool current_candidate_swap = sewer_copy_recorded && sewer->candidate &&
                sewer->swap == swapchain.GetHandle() && sewer->swap_image == swapchain.Image() &&
                sewer->swap_ready == swapchain.GetPresentReadySemaphore() &&
                sewer->source.swap_generation == sewer_swap_generation.load(std::memory_order_acquire);
#endif
            const auto submit_ns = WorkflowPresent::Now();
            presented = swapchain.Present();
            const auto result_ns = WorkflowPresent::Now();
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            note_bottle_attempt(submit_ns, result_ns);
#endif
            if (SewerMotion::Enabled()) ++sewer_present_serial;
            if (sewer_copy_recorded) {
                sewer->serial = sewer_present_serial;
                sewer->submit_ns = submit_ns;
                sewer->result_ns = result_ns;
                sewer->presented = presented && sewer->swap == swapchain.GetHandle();
#ifdef BB_TEST_SHARED_POST_GRAPH
                if (sewer->candidate) {
                    sewer->presented &= current_candidate_swap;
                    if (!sewer->refusal && !sewer->presented) {
                        sewer->refusal = presented ? "provisional-present-swap-replaced"
                                                    : "provisional-app-present-failed";
                    }
                }
#endif
            }
            if (marker_image) {
                motion_attempts[motion_attempts_count++]={motion,frame->ready_tick,submit_ns,result_ns,
                    frame->motion_swap_epoch,marker_swap,marker_image,marker_index,presented};
            }
            workflow_present.Record({frame->ready_tick, submit_ns, result_ns, presented, role,
                output.width, output.height, u32(surface.format), u32(surface.colorSpace), u32(mode),
                hdr_output, frame->workflow_input_width, frame->workflow_input_height,
                frame->workflow_display_override, fsr_settings.enable, frame_gen->Enabled(),
                FrameGenerator::DlssWanted(), BbSettings::Get().upscaler.load(std::memory_order_relaxed)});
        } else {
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            const auto bottle_start = bottle ? WorkflowPresent::Now() : 0;
#endif
            presented = swapchain.Present();
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
            note_bottle_attempt(bottle_start, bottle ? WorkflowPresent::Now() : 0);
#endif
            if (SewerMotion::Enabled()) ++sewer_present_serial;
        }
    }
    if (sewer_copy_recorded) frame->sewer_present_readback = std::move(sewer);
#ifdef BB_TEST_SHARED_POST_GRAPH
    else if (sewer && sewer->candidate) {
        sewer->FailCandidate(is_reusing_frame ? "provisional-frame-reused" :
                             sewer->refusal ? sewer->refusal : "provisional-frame-not-encoded");
    }
#endif
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (bottle_copy_recorded) {
        if (!bottle->refusal && !bottle->attempt.success) {
            bottle->refusal = presented ? "actual-present-swap-replaced" : "ordinary-present-failed";
        }
        frame->bottle_present_readback = std::move(bottle);
    } else if (bottle) {
        bottle->Fail(bottle->refusal ? bottle->refusal : "no-prepared-sdr-copy");
    }
#endif
    dlss_fg->AfterPresent(dlss_info);
    if (present_log) {
        const auto now = FrameGenerator::Clock::now();
        static auto first = present_start, previous = present_start;
        static unsigned unflushed = 0;
        const auto ms = [](auto duration) {
            return std::chrono::duration<double, std::milli>(duration).count();
        };
        std::fprintf(present_log, "%.6f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%u,%llu\n",
                     std::chrono::duration<double>(now - first).count(), ms(now - previous),
                     ms(acquire_end - acquire_start), ms(record_end - acquire_end),
                     ms(submit_end - record_end), ms(now - submit_end), ms(now - present_start),
                     unsigned(real_game_frame), static_cast<unsigned long long>(frame->ready_tick));
        previous = now;
        if (++unflushed >= 120) {
            std::fflush(present_log);
            unflushed = 0;
        }
    }
    // bbport: recreated after the lock: its device wait takes it (Swapchain::WaitIdle).
    if (!presented) {
        dlss_fg->BeforeSwapchainChange();
        swapchain.Recreate(window.GetWidth(), window.GetHeight());
        if (SewerMotion::Enabled()) sewer_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
        if (BottleCaustic::CutSource::Run()) bottle_swap_generation.fetch_add(1, std::memory_order_acq_rel);
#endif
        if (BottleMotion::Run()) motion_swap_epoch.fetch_add(1,std::memory_order_relaxed);
    }

    free_frame();
    if (!is_reusing_frame && is_game_frame) {
        DebugState.IncFlipFrameNum();
    }
    note_real();
}

namespace {
// bbport: BB_FRAME_STATS: how long GetRenderFrame waits for a free presentation frame and then
// for its present fence, printed every 300 frames. Called from the flip step, these waits block
// the GPU command thread (with frame generation, while the swap thread is in Streamline).
void NoteFrameWaits(std::chrono::steady_clock::duration free_wait,
                    std::chrono::steady_clock::duration fence_wait) {
    static const bool on = [] {
        const char* env = std::getenv("BB_FRAME_STATS");
        return env && env[0] == '1';
    }();
    if (!on) {
        return;
    }
    static std::mutex mutex;
    static double free_ms = 0.0, fence_ms = 0.0, worst_ms = 0.0;
    static u32 calls = 0;
    const double a = std::chrono::duration<double, std::milli>(free_wait).count();
    const double b = std::chrono::duration<double, std::milli>(fence_wait).count();
    std::scoped_lock lock{mutex};
    free_ms += a;
    fence_ms += b;
    worst_ms = std::max(worst_ms, a + b);
    if (++calls == 300) {
        std::printf("Presenter: over %u frames, %.2f ms a frame waiting for a free presentation "
                    "frame and %.2f ms for its present fence (worst %.2f ms)\n",
                    calls, free_ms / calls, fence_ms / calls, worst_ms);
        std::fflush(stdout);
        free_ms = fence_ms = worst_ms = 0.0;
        calls = 0;
    }
}
} // namespace

Frame* Presenter::GetRenderFrame() {
    // Wait for free presentation frames
    Frame* frame;
    const auto wait_start = std::chrono::steady_clock::now(); // bbport: NoteFrameWaits
    {
        std::unique_lock lock{free_mutex};
        free_cv.wait(lock, [this] { return !free_queue.empty(); });
        LOG_DEBUG(Render_Vulkan, "Got render frame, remaining {}", free_queue.size() - 1);

        // Take the frame from the queue
        frame = free_queue.front();
        free_queue.pop();
    }
    const auto got_frame = std::chrono::steady_clock::now(); // bbport

    const vk::Device device = instance.GetDevice();
    vk::Result result{};

    const auto wait = [&]() {
        result = device.waitForFences(frame->present_done, false, std::numeric_limits<u64>::max());
        return result;
    };

    // Wait for the presentation to be finished so all frame resources are free
    while (wait() != vk::Result::eSuccess) {
        if (result == vk::Result::eErrorDeviceLost) {
            Breadcrumbs::ReportDeviceLost("waiting for a frame");
        }
        ASSERT_MSG(result != vk::Result::eErrorDeviceLost,
                   "Device lost during waiting for a frame");
        // Retry if the waiting times out
        if (result == vk::Result::eTimeout) {
            continue;
        }
    }
    if (frame->sewer_present_readback)
        RetireSewerPresent(*frame, sewer_swap_generation.load(std::memory_order_acquire));
#ifdef BB_TEST_BOTTLE_CUT_SOURCE
    if (frame->bottle_present_readback)
        RetireBottleCutPresent(*frame, bottle_swap_generation.load(std::memory_order_acquire));
#endif
    NoteFrameWaits(got_frame - wait_start, std::chrono::steady_clock::now() - got_frame); // bbport

    if (frame->width != expected_frame_width || frame->height != expected_frame_height ||
        frame->is_hdr != swapchain.GetHDR()) {
        RecreateFrame(frame, expected_frame_width, expected_frame_height);
    }

    return frame;
}

void Presenter::SetExpectedGameSize(s32 width, s32 height) {
    if (width <= 0 || height <= 0) {
        return; // minimised: keep the last size (a 0x0 frame image cannot be made, issue #31)
    }
    const float ratio = (float)width / (float)height;

    expected_frame_height = height;
    expected_frame_width = width;
    if (ratio > expected_ratio) {
        expected_frame_width = static_cast<s32>(height * expected_ratio);
    } else {
        expected_frame_height = static_cast<s32>(width / expected_ratio);
    }
}

} // namespace Vulkan


// Keep Windows macros out of renderer and Vulkan headers above.
#ifdef _WIN32
#include <windows.h>
#endif

unsigned long long Vulkan::WorkflowPresent::Now() {
#ifdef _WIN32
    static const auto frequency = [] {
        LARGE_INTEGER value{};
        return QueryPerformanceFrequency(&value) && value.QuadPart > 0 ? value.QuadPart : 0;
    }();
    LARGE_INTEGER now{};
    if (!frequency || !QueryPerformanceCounter(&now) || now.QuadPart < 0) return 0;
    return (now.QuadPart / frequency) * 1'000'000'000ull +
           (now.QuadPart % frequency) * 1'000'000'000ull / frequency;
#else
    return static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
#endif
}
