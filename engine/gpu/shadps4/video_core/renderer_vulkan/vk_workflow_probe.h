// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <memory>
#include <limits>
#include <span>
#include <string>
#include <vector>
#include <fmt/format.h>

#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_lamp_pane_probe.h"
#include "video_core/renderer_vulkan/vk_workflow_consumer.h"
#include "video_core/renderer_vulkan/vk_workflow_capture_proof.h"
#include "video_core/renderer_vulkan/vk_workflow_request.h"
#include "video_core/renderer_vulkan/vk_workflow_skip_reasons.h"

extern "C" int workflow_payload_reserve(size_t bytes);

namespace WorkflowProbe {
using Clock = std::chrono::steady_clock;
inline constexpr u32 QueryLimit = 4096;
inline constexpr u32 HitLimit = 32;

inline bool FreeSpace(const WorkflowProbeConfig& config, u64 bytes) {
    std::error_code error;
    const auto size = std::filesystem::space(config.directory, error);
    return !error && size.available >= bytes;
}

inline bool SaveBlob(const WorkflowProbeConfig& config, const char* name, const void* data, size_t bytes) {
    char path[WORKFLOW_PATH_MAX];
    if (!workflow_path(&config, name, path)) return false;
    FILE* out = std::fopen(path, "wbx");
    if (!out) return false;
    const bool wrote = std::fwrite(data, 1, bytes, out) == bytes;
    if (std::fclose(out) == 0 && wrote) return true;
    std::remove(path);
    return false;
}

struct Camera {
    std::array<u32, 12> view{}, inverse{};
    std::array<u32, 4> projection{}, inverse_projection{};
    std::array<u32, 2> jitter{};
    bool valid = false;

    static Camera From(const Vulkan::CameraMotion::Matrices& m, const std::array<float, 2>& j) {
        const auto finite = [](const auto& values) {
            return std::ranges::all_of(values, [](float x) { return std::isfinite(x); });
        };
        if (!m.valid || !finite(m.view) || !finite(m.inv_view) || !finite(m.proj) || !finite(j) ||
            !m.proj[0] || !m.proj[1] || !m.proj[3]) return {};
        const std::array inv{1.0f / m.proj[0], 1.0f / m.proj[1], 1.0f / m.proj[3], -m.proj[2] / m.proj[3]};
        if (!finite(inv)) return {};
        return {std::bit_cast<std::array<u32, 12>>(m.view), std::bit_cast<std::array<u32, 12>>(m.inv_view),
                std::bit_cast<std::array<u32, 4>>(m.proj), std::bit_cast<std::array<u32, 4>>(inv),
                std::bit_cast<std::array<u32, 2>>(j), true};
    }

    bool SameProjection(const Camera& rhs) const {
        return valid && rhs.valid && projection == rhs.projection && inverse_projection == rhs.inverse_projection;
    }

    bool SamePose(const Camera& rhs) const {
        return SameProjection(rhs) && view == rhs.view && inverse == rhs.inverse && jitter == rhs.jitter;
    }

    static std::string Words(std::span<const u32> words) {
        std::string json = "[";
        for (const u32 word : words) {
            if (json.size() > 1) json += ',';
            json += fmt::format("{}", word);
        }
        return json + ']';
    }

    std::string Json() const {
        if (!valid) return "null";
        return fmt::format("{{\"view\":{},\"inverse\":{},\"projection\":{},\"inverse_projection\":{},\"jitter\":{}}}",
                           Words(view), Words(inverse), Words(projection), Words(inverse_projection), Words(jitter));
    }
};

struct ResolvedIndex {
    vk::Buffer buffer;
    u64 offset = 0, capacity = 0;
    u32 generation = 0;
    bool transfer_src = false;
};

struct ResolvedPosition {
    ResolvedIndex storage;
    u64 bytes = 0;
    u32 stride = 0, format = 0;
};

inline constexpr u32 SnapshotLimit = 4;

struct PositionObservation {
    static constexpr u32 Unknown = ~u32{0};
    const char* reason = "vertex_inputs_unobserved";
    const char* layout_source = "unobserved";
    const char* input_state = "unobserved";
    const char* bind_route = "unobserved";
    u64 source_offset = 0, bound_bytes = 0, capacity_remaining = 0, aligned_bytes = 0;
    u32 attribute_count = 0, location0_count = 0;
    u32 binding = Unknown, binding_description = Unknown, slot = Unknown, format = Unknown, rate = Unknown;
    u32 attribute_offset = Unknown, stride = Unknown, final_slot = Unknown;
    bool buffer_present = false, buffer_valid = false, range_known = false, transfer_src = false;
    bool final_compared = false, final_buffer_equal = false, final_offset_equal = false, final_size_equal = false;
    bool allocation_attempted = false, resolved = false;
};

struct Transfer {
    VmaAllocator allocator{};
    VkBuffer buffer{};
    VmaAllocation allocation{};
    void* mapped = nullptr;
    u64 bytes = 0, start = 0, payload = 0, tick = 0;

    ~Transfer() {
        if (buffer) vmaDestroyBuffer(allocator, buffer, allocation);
    }
};

inline std::shared_ptr<Transfer> AllocateTransfer(VmaAllocator allocator, u64 bytes) {
    auto stage = std::make_shared<Transfer>();
    const VkBufferCreateInfo info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
                                  .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    const VmaAllocationCreateInfo memory{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
    };
    VmaAllocationInfo mapped{};
    if (vmaCreateBuffer(allocator, &info, &memory, &stage->buffer, &stage->allocation, &mapped) != VK_SUCCESS)
        return {};
    stage->allocator = allocator;
    stage->mapped = mapped.pMappedData;
    stage->bytes = stage->payload = bytes;
    return stage->mapped ? stage : nullptr;
}

inline bool FlushBlob(const WorkflowProbeConfig& config, const Transfer& stage, const char* name) {
    return vmaInvalidateAllocation(stage.allocator, stage.allocation, 0, VK_WHOLE_SIZE) == VK_SUCCESS &&
           SaveBlob(config, name, static_cast<const std::byte*>(stage.mapped) + stage.start, stage.payload);
}

enum class AttachmentKind : u8 { TextureCache, PointShadowLamp };

struct AttachmentFacts {
    u64 id = 0, generation = 0, guest_uid = 0;
    std::array<u32, 4> subresource{};
    u32 width = 0, height = 0, format = 0;
    u8 slot = 0;
    AttachmentKind kind = AttachmentKind::TextureCache;
    bool operator==(const AttachmentFacts&) const = default;
};

struct DrawCommand {
    bool indexed = false, indirect = false, count_buffer = false;
    u32 count = 0, instances = 0, first_vertex = 0, first_instance = 0;
    u32 command_limit = 1, command_stride = 0;

    bool Group() const { return command_limit > 1; }
    bool operator==(const DrawCommand&) const = default;
};

struct DrawFacts {
    // This key narrows a fresh query. It does not establish persistent object or material identity.
    u64 vs = 0, ps = 0;
    AttachmentFacts color, depth;
    DrawCommand command;
    u32 width = 0, height = 0;
    u32 index_width = 0, mrt = 0, depth_compare = 0, raster_samples = 0;
    vk::PrimitiveTopology topology{};
    bool gbuffer = false, blend = false, depth_test = false, depth_write = false;
    bool restart = false;
    bool operator==(const DrawFacts&) const = default;
};

struct Draw {
    DrawFacts facts;
    u64 tick = 0, bind_offset = 0, input_geometry = 0, position_bind_offset = 0;
    u32 generation = 0;
    std::array<u32, 2> jitter{};
    const char* copy_reason = "index_not_requested";
    u32 position_stride = 0, position_format = 0;
    u32 capture_slot = 0;
    bool capture_warm = false;
    u8 position_observation_slot = SnapshotLimit;
    std::shared_ptr<Transfer> copy, position;
};

struct Candidate {
    DrawFacts facts;
    u32 token = 0;
    std::array<u32, 2> jitter{};
};

struct ScissorQuery {
    vk::QueryPool pool{};
    vk::Rect2D prior, observed;
    u32 index = 0;
};

struct Native {
    std::shared_ptr<Transfer> copy;
    std::string details;
    std::string name;
};

struct Renderer {
    explicit Renderer(WorkflowProbeConfig config_) : config(config_) {}
    WorkflowProbeConfig config;
    Request request;
    Clock::time_point deadline{};
    Id latest = 0, last_trigger = 0;
    u32 request_count = 0;
    u64 scene = 0, rt = 0, query_tick = 0;
    static constexpr u32 PoseSceneLimit = 120;
    u64 first_pose_rejection = 0, last_pose_rejection = 0;
    u32 pose_rejections = 0;
    bool pose_incompatible_draw = false;

    vk::UniqueQueryPool pool;
    bool querying = false, region = false, try_region = false, discard_query = false;
    u32 skipped = 0, snapshots = 0;
    u32 lamp_owner_lookups = 0, no_framebuffer_output = 0;
    SkipDiagnostics skip_diagnostics;
    std::vector<Draw> draws;
    std::vector<u64> samples;
    Camera camera;
    std::array<Id, 4> pixel{};
    ResolvedIndex resolved;
    ResolvedPosition position;
    PositionObservation position_observation;
    std::array<PositionObservation, SnapshotLimit> position_observations;
    u32 selected = 0;
    Id pick_id = 0;
    std::vector<Candidate> candidates;
    Camera pick_camera;
    std::array<Id, 4> pick_pixel{};
    std::array<u32, 4> aperture{}, pick_aperture{};

    std::vector<Native> native;
    u32 native_issued = 0, native_retired = 0, native_total = 0;
    bool long_native = false;
    u64 next_scene = 0;
    std::vector<std::weak_ptr<Transfer>> transfers;

    void Emit(const Request& which, const char* event, const char* status, const char* reason,
              std::string_view details = {}) const {
        const auto line = fmt::format(
            "\nWorkflow probe: {{\"schema\":\"bb-workflow-probe-v1\",\"session\":\"{}\",\"pid\":{},\"request\":{},"
            "\"op\":\"{}\",\"event\":\"{}\",\"status\":\"{}\",\"reason\":\"{}\"{}}}\n",
            config.session, Vulkan::Round2ProbeSettings::Pid(), which.id, Name(which.op), event, status, reason, details);
        workflow_log_record(line.data(), line.size());
    }

    void End(const char* status, const char* reason) {
        if (request.wait_exact_pose) {
            Emit(request, "end", status, reason,
                 fmt::format(",\"pose_wait\":{{\"mode\":\"wait-exact-pose\",\"scene_limit\":{},"
                             "\"rejected_scenes\":{},\"first_rejected_scene\":{},\"last_rejected_scene\":{},"
                             "\"rejected_reason\":{}}}", PoseSceneLimit, pose_rejections,
                             pose_rejections ? fmt::format("{}", first_pose_rejection) : "null",
                             pose_rejections ? fmt::format("{}", last_pose_rejection) : "null",
                             pose_rejections ? "\"reacquire_camera_mismatch\"" : "null"));
        } else {
            Emit(request, "end", status, reason);
        }
        request = {};
        querying = false;
        discard_query |= query_tick != 0;
        try_region = false;
        draws.clear();
        native.clear();
        TrackConsumers = false;
    }

    bool AdmitTransfer() {
        std::erase_if(transfers, [](const auto& transfer) { return transfer.expired(); });
        return transfers.size() < WORKFLOW_TRANSFER_LIMIT;
    }
};
} // namespace WorkflowProbe

