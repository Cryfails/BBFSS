// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string_view>

namespace WorkflowProbe {
enum class SkipReason : std::uint8_t {
    CompetingProbe,
    LegacyScissor,
    ScissorCount,
    TargetLayers,
    MissingFragment,
    ShaderStorageWrite,
    InvalidRasterMapping,
    QueryLimit,
    InvalidCamera,
    CameraViewMismatch,
    ApertureMismatch,
    ReacquireCameraMismatch,
    ColorViewUnowned,
    DepthViewUnowned,
    IndirectSceneDepth,
    MotionCaptureWrite,
    MotionSwayWrite,
    UserShaderPatch,
    CaptureFallback,
    CaptureUv,
    CaptureSway,
    CaptureDynamic,
    CaptureScope,
    CaptureUnknown,
    Count,
};

using SkipInputs = std::array<std::uint32_t, 8>;
using SkipInputNames = std::array<std::string_view, SkipInputs{}.size()>;

struct SkipReasonInfo {
    std::string_view name;
    SkipInputNames inputs;
};

inline constexpr SkipInputNames LayoutInputs{
    "competing_probe", "legacy_scissor", "scissor_count", "layers", "fragment_present", "storage_writes",
};
inline constexpr SkipInputNames CameraInputs{
    "reference_valid", "view_changed", "inverse_changed", "projection_changed", "aperture_changed",
};
inline constexpr SkipInputNames OwnerInputs{
    "image_present", "uid_present", "backing_present", "bound_view_present", "cached_view_count", "slot",
};
inline constexpr SkipInputNames MotionInputs{
    "mode", "motion_slot", "capture_slot", "sway_off_slot", "final_capture_word_attested",
};
inline constexpr auto SkipReasons = std::array{
    SkipReasonInfo{"competing_probe", LayoutInputs},
    SkipReasonInfo{"legacy_scissor", LayoutInputs},
    SkipReasonInfo{"scissor_count", LayoutInputs},
    SkipReasonInfo{"target_layers", LayoutInputs},
    SkipReasonInfo{"missing_fragment", LayoutInputs},
    SkipReasonInfo{"shader_storage_write", LayoutInputs},
    SkipReasonInfo{"invalid_raster_mapping", {"game_width", "game_height", "scale_x_word", "scale_y_word",
                                              "offset_x_word", "offset_y_word", "raster_width", "raster_height"}},
    SkipReasonInfo{"query_limit", {"queries", "limit"}},
    SkipReasonInfo{"invalid_camera", {"pass_matrices_valid", "fallback_matrices_valid", "phase_camera_valid"}},
    SkipReasonInfo{"camera_view_mismatch", CameraInputs},
    SkipReasonInfo{"aperture_mismatch", {"prior_x", "prior_y", "prior_width", "prior_height",
                                         "draw_x", "draw_y", "draw_width", "draw_height"}},
    SkipReasonInfo{"reacquire_camera_mismatch", CameraInputs},
    SkipReasonInfo{"color_view_unowned", OwnerInputs},
    SkipReasonInfo{"depth_view_unowned", OwnerInputs},
    SkipReasonInfo{"indirect_scene_depth", {"indexed", "max_count", "stride", "count_buffer_present",
                                             "color_attachments", "target_width", "target_height"}},
    SkipReasonInfo{"motion_capture_write", MotionInputs},
    SkipReasonInfo{"motion_sway_write", MotionInputs},
    SkipReasonInfo{"user_shader_patch", {"shader_patches_enabled"}},
    SkipReasonInfo{"capture_fallback_nonatomic", MotionInputs},
    SkipReasonInfo{"capture_uv_possible", MotionInputs},
    SkipReasonInfo{"capture_sway_unproved", MotionInputs},
    SkipReasonInfo{"capture_dynamic_inputs", MotionInputs},
    SkipReasonInfo{"capture_scope_unsupported", MotionInputs},
    SkipReasonInfo{"capture_effective_module_unknown", MotionInputs},
};
static_assert(SkipReasons.size() == std::size_t(SkipReason::Count));

struct NullColorSkip {
    struct StencilFace {
        std::uint32_t write_mask = 0;
        std::uint8_t fail_op = 0, pass_op = 0, depth_fail_op = 0, compare_op = 0;
    };

    std::uint64_t depth_id = 0, depth_generation = 0;
    std::array<std::uint32_t, 4> depth_subresource{};
    StencilFace front, back;
    std::uint32_t depth_layout = 0, depth_compare = 0;
    std::uint16_t declared_colors = 0;
    bool depth_view_present = false, depth_test = false, depth_write = false;
    bool stencil_attachment_present = false, stencil_test = false;
};

struct SkipContext {
    std::uint64_t tick = 0, vs = 0, ps = 0;
    SkipInputs inputs{};
    std::optional<NullColorSkip> null_color;
    SkipReason reason{};
    bool indirect = false;
};

struct SkipDiagnostics {
    static constexpr std::size_t ContextLimit = 4;
    std::array<std::uint32_t, SkipReasons.size()> counts{};
    std::array<SkipContext, ContextLimit> contexts{};
    std::size_t captured = 0;

    // The aggregate remains the original coverage gate. All skipping sites use this single increment.
    SkipContext* Note(std::uint32_t& skipped, SkipReason reason) {
        ++skipped;
        ++counts[std::size_t(reason)];
        if (captured == contexts.size()) return nullptr;
        auto& context = contexts[captured++];
        context.reason = reason;
        context.null_color.reset();
        return &context;
    }

    void Reset(std::uint32_t& skipped) {
        skipped = 0;
        counts.fill(0);
        captured = 0;
    }

    std::uint32_t Overflow(std::uint32_t skipped) const {
        return skipped - std::uint32_t(captured);
    }
};
static_assert(sizeof(SkipDiagnostics) <= 648);
} // namespace WorkflowProbe

