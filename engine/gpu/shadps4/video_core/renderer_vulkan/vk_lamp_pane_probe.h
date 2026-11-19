// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "rt_lamp_pane_probe.h"
#include "vk_camera_motion.h"
#include "vk_object_motion.h"
#include "vk_scheduler.h"
#include "video_core/texture_cache/image_view.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <optional>
#include <span>
#include <string_view>
#include <vk_mem_alloc.h>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace Vulkan {
class GraphicsPipeline;

struct LampMaterialDelivery {
    const GraphicsPipeline* original{};
    const GraphicsPipeline* raster{};
    vk::Pipeline handle{};
    u32 first = 0, base = 0, first_instance = 0;
    bool indexed = false;

    bool operator==(const LampMaterialDelivery&) const = default;
};

enum class LampMaterialColor { Unsupported, Unorm, Srgb };

constexpr LampMaterialColor LampMaterialEncoding(vk::Format format) {
    switch (format) {
    case vk::Format::eR8G8B8A8Unorm: return LampMaterialColor::Unorm;
    case vk::Format::eR8G8B8A8Srgb: return LampMaterialColor::Srgb;
    default: return LampMaterialColor::Unsupported;
    }
}

constexpr const char* LampMaterialEncodingLabel(LampMaterialColor encoding) {
    switch (encoding) {
    case LampMaterialColor::Unorm: return "RGBA8_UNORM";
    case LampMaterialColor::Srgb: return "RGBA8_SRGB(rgb-encoded,alpha-linear)";
    default: return "unsupported";
    }
}

struct LampMaterialSource {
    RtLampPane::MaterialBacking backing;
    vk::ImageView view{};
    VideoCore::ImageViewInfo info;
    vk::ImageLayout layout{};
    u32 width = 0, height = 0, samples = 0;
    vk::Format created_format{}, effective_view_format{};

    bool operator==(const LampMaterialSource&) const = default;
};

// A renderer-owned attachment remains an attachment only. The four transfer sources are unchanged.
struct LampMaterialMotion {
    ObjectMotion::AttachmentOwner owner;
    RenderAttachment attachment;

    bool operator==(const LampMaterialMotion& other) const {
        return owner == other.owner &&
               std::memcmp(&attachment, &other.attachment, sizeof(attachment)) == 0;
    }

    [[nodiscard]] bool Current(const ObjectMotion* expected, vk::Extent2D extent, u64 scene) const {
        const auto& ci = owner.creation;
        return expected && owner.owner == expected && owner.target && owner.allocation && owner.image && owner.view &&
               owner.extent == extent && extent.width && extent.height &&
               owner.owner_frame == scene && owner.used_frame == scene && owner.written &&
               attachment.image_view == owner.view &&
               attachment.image_layout == vk::ImageLayout::eColorAttachmentOptimal &&
               owner.layout == attachment.image_layout &&
               !ci.pNext && !ci.flags && ci.imageType == vk::ImageType::e2D &&
               ci.format == vk::Format::eR32G32B32A32Sfloat &&
               ci.extent == vk::Extent3D{extent.width, extent.height, 1} &&
               ci.mipLevels == 1 && ci.arrayLayers == 1 && ci.samples == vk::SampleCountFlagBits::e1 &&
               ci.tiling == vk::ImageTiling::eOptimal && ci.sharingMode == vk::SharingMode::eExclusive &&
               bool(ci.usage & vk::ImageUsageFlagBits::eColorAttachment) &&
               !(ci.usage & vk::ImageUsageFlagBits::eTransientAttachment);
    }

    [[nodiscard]] bool SeparateFrom(vk::Image image, VmaAllocation allocation,
                                    const vk::ImageCreateInfo& ci) const {
        using F = vk::ImageCreateFlagBits;
        constexpr auto alias_flags = F::eAlias | F::eSparseBinding | F::eSparseResidency |
                                     F::eSparseAliased | F::eDisjoint;
        return image && allocation && image != owner.image && allocation != owner.allocation &&
               !ci.pNext && !(ci.flags & alias_flags);
    }
};

struct LampMaterialState {
    RtLampPane::MaterialPhases phases;
    std::array<LampMaterialSource, RtLampPane::MaterialTargets> sources{};
    LampMaterialDelivery delivery;
    std::optional<LampMaterialMotion> motion;
    vk::Rect2D scissor;
    std::array<u32, 3> masks{}, blend{};
    std::array<u32, 6> depth_stencil{};
    u32 mrt = 0, logic = 0;
    const char* refusal = nullptr;
    std::array<char, 640> refusal_detail{};
};

// Draw-local raw reader input. A consumer supplies its own request and lifetime.
struct RawDrawPixel { u32 x, y; };

struct LampIndexLineage;

struct DrawRawRead {
    LampMaterialState& material;
    const RtLampPane::Identity& capture;
    const RtLampPane::Camera& camera;
    const std::array<float, 2>& jitter;
    std::span<const RawDrawPixel> samples;
    VkBuffer& buffer;
    std::function<bool()> allocate;
    u64 offset = 0;
    u32 width = 0, height = 0, ordinal = 0, first_index = 0, base_vertex = 0, first_instance = 0;
    u64 vs = 0, ps = 0;
    u32 indices = 0, instances = 0;
    bool albedo_depth_only = false;
    LampIndexLineage* lineage = nullptr;
    u64 lineage_offset = 0;
    const std::array<u64, 4>* compact_offsets = nullptr;
};

inline constexpr u32 RawAlbedo = 1, RawDepth = 3;
inline constexpr u32 RawFinalAlbedo = RtLampPane::FinalDepthBytes + RtLampPane::MaterialBytes;

struct Round2ProbeSettings {
    const char* session = nullptr;
    const char* directory = nullptr;
    bool lineage = false;
    bool frames = false;
    bool motion_clip = false;
    bool cost = false;

    static const Round2ProbeSettings& Get() {
        static const auto settings = [] {
            Round2ProbeSettings cfg;
            cfg.session = std::getenv("BB_ROUND2_SESSION");
            cfg.directory = std::getenv("BB_ROUND2_CAPTURE_DIR");
            const auto enabled = [](const char* name) {
                const auto* value = std::getenv(name);
                return value && std::string_view(value) == "1";
            };
            const bool motion_clip = enabled("BB_ROUND2_MOTION_CLIP");
            const std::string_view id = cfg.session ? cfg.session : "";
            if (id.empty() || id.size() > 32 || id.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789-") !=
                std::string_view::npos || !cfg.directory || !*cfg.directory) {
                if (motion_clip) {
                    std::puts("Round2 motion clip: refused invalid_session_or_capture_dir");
                }
                return Round2ProbeSettings{};
            }
            cfg.lineage = enabled("BB_ROUND2_LINEAGE");
            cfg.frames = enabled("BB_ROUND2_FRAMES");
            cfg.motion_clip = motion_clip && cfg.frames;
            cfg.cost = enabled("BB_ROUND2_COST");
            if (motion_clip && !cfg.frames) {
                std::puts("Round2 motion clip: refused frame_capture_disabled");
            }
            return cfg;
        }();
        return settings;
    }

    static int Pid() {
#ifdef _WIN32
        return _getpid();
#else
        return getpid();
#endif
    }
};

// These spans measure elapsed host time, including any time blocked inside the called API.
inline u64 Round2ClockNs() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

inline u64 Round2CostStart(bool enabled) {
    return enabled ? Round2ClockNs() : 0;
}

inline u64 Round2CostElapsed(u64 start) {
    return start ? Round2ClockNs() - start : 0;
}

struct LampIndexLineage {
    static constexpr u32 Bytes = RtLampPane::DrawIndices * sizeof(u16);
    static_assert(Bytes == 50592);
    struct Binding {
        vk::Buffer buffer{};
        u64 offset = 0, capacity = 0;
        bool checked = false;

        bool operator==(const Binding&) const = default;
    } resolved, before;
    u64 tick = 0;
    bool after = false;
    const char* refusal = nullptr;
};

struct LampReconstruction {
    static constexpr std::array<u32, 5> Ordinals{2458, 2459, 2460, 2461, 2074};
    static constexpr u32 Slice = 1, Slots = 9, SlotBytes = 16, ClipBytes = Slots * SlotBytes;
    std::array<float, 16> projection{};
    std::array<float, 12> inverse_view{}, rows{}, relative_rows{};
    std::array<float, 3> origin{};
    u64 vertex_stage_key = 0;
    u32 raster_motion_flags = 0;
    bool raster_key_matched = false, affine = false;
    std::array<float, 6> viewport{};
    std::array<float, 2> jitter{};
    vk::Rect2D scissor{};
    std::array<std::array<u32, 3>, Ordinals.size()> triplets{};
    std::array<u32, Slots> expanded{};
    u64 clip_tick = 0, fingerprint = 0;
    u32 indices = 0, instances = 0, index_size = 0, entry_first = 0, raw_min = 0;
    u32 first = 0, count = 0;
    bool viewport_before = false, viewport_after = false, projection_saved = false;
    bool strip = false, restart = false;
    const char* refusal = nullptr;
};

// Shared by the normal capture's copy hook and the rasterizer's depth hook on the render thread.
struct LampPaneProbe {
    RtLampPane::Request request;
    RtLampPane::Identity capture;
    RtLampPane::Camera camera;
    u64 armed_frame = 0, seen_frame = 0, key = 0;
    u64 world_tick = 0, depth_tick = 0;
    u32 ordinal = 0, exact_draws = 0;
    u32 param = 0, vertices = 0, triangles = 0;
    u32 first_index = 0, base_vertex = 0, first_instance = 0;
    u32 width = 0, height = 0;
    bool saw_target = false, sealed = false, reported = false;
    const char* refusal = nullptr;
    std::array<float, 2> jitter{};
    std::array<RtLampPane::Sample, 2> samples{};
    std::vector<u32> indices;
    VkBuffer buffer{};
    VmaAllocation allocation{};
    const std::byte* mapped = nullptr;
    bool material_enabled = false;
    LampMaterialState material;
    std::optional<LampReconstruction> reconstruction;
    std::optional<LampIndexLineage> lineage;
    u64 cost_requested_bytes = 0, cost_allocated_bytes = 0;

    [[nodiscard]] bool Captured() const noexcept { return capture.build != 0; }
    [[nodiscard]] u64 WorldBytes() const noexcept {
        return u64(vertices) * RtLampPane::Instances * 16;
    }
    [[nodiscard]] u64 ClipOffset() const noexcept {
        return WorldBytes() + RtLampPane::FinalDepthBytes +
               (material_enabled ? RtLampPane::MaterialBytes : 0);
    }
    [[nodiscard]] u64 LineageOffset() const noexcept {
        return ClipOffset() + LampReconstruction::ClipBytes;
    }

    void LogStagingCost(const char* operation, u64 tick, u64 elapsed, const char* status) const {
        const auto& cfg = Round2ProbeSettings::Get();
        const auto print = [](u64 value) { return static_cast<unsigned long long>(value); };
        std::printf("Round2 cost: {\"schema\":\"round2-host-cost-v1\",\"kind\":\"index\",\"op\":\"%s\","
                    "\"session\":\"%s\",\"pid\":%d,\"request\":%u,\"scene\":%llu,\"rt\":%llu,\"tick\":%llu,"
                    "\"elapsed_ns\":%llu,\"requested_bytes\":%llu,\"allocated_bytes\":%llu,"
                    "\"index_payload_bytes\":%u,\"shared_pick\":true,\"lineage_enabled\":%s,\"status\":\"%s\"}\n",
                    operation, cfg.session, Round2ProbeSettings::Pid(), request.id, print(capture.scene),
                    print(capture.rt), print(tick), print(elapsed), print(cost_requested_bytes),
                    print(cost_allocated_bytes), lineage ? LampIndexLineage::Bytes : 0,
                    lineage ? "true" : "false", status);
    }

    bool Allocate(VmaAllocator allocator, Scheduler& scheduler) {
        if (buffer) {
            return true;
        }
        const VkBufferCreateInfo info{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = lineage ? LineageOffset() + LampIndexLineage::Bytes :
                    ClipOffset() + (reconstruction ? LampReconstruction::ClipBytes : 0),
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo memory{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO,
        };
        VmaAllocationInfo made{};
        const bool cost = Round2ProbeSettings::Get().cost;
        const u64 start = Round2CostStart(cost);
        const auto result = vmaCreateBuffer(allocator, &info, &memory, &buffer, &allocation, &made);
        const u64 elapsed = Round2CostElapsed(start);
        if (cost) {
            cost_requested_bytes = info.size;
            cost_allocated_bytes = result == VK_SUCCESS ? made.size : 0;
            LogStagingCost("allocate", scheduler.CurrentTick(), elapsed,
                           result != VK_SUCCESS ? "allocation_failed" : made.pMappedData ? "ok" : "unmapped");
        }
        if (result != VK_SUCCESS) {
            refusal = "staging allocation failed";
            return false;
        }
        mapped = static_cast<const std::byte*>(made.pMappedData);
        if (!mapped) {
            refusal = "staging is not mapped";
            return false;
        }
        return true;
    }

    void Free(VmaAllocator allocator, Scheduler& scheduler) {
        if (buffer) {
            const bool cost = Round2ProbeSettings::Get().cost;
            const u64 start = Round2CostStart(cost);
            vmaDestroyBuffer(allocator, buffer, allocation);
            const u64 elapsed = Round2CostElapsed(start);
            buffer = {};
            mapped = nullptr;
            if (cost) {
                LogStagingCost("release", scheduler.CurrentTick(), elapsed, "ok");
            }
        }
    }
};
} // namespace Vulkan
