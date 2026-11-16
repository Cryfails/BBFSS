// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "common/types.h"
#include <array>
#include <memory>
#include <optional>
#include <utility>
#include <vector>
#include "video_core/buffer_cache/buffer.h"
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

class PointShadow {
public:
    PointShadow(const Instance& instance, Scheduler& scheduler,
                VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion, RtShadow& rt_shadow);
    ~PointShadow();

    struct Inputs {
        const u32* constants = nullptr;
        const u32* lights = nullptr;
        u32 count = 0;
        vk::Rect2D tile{};
        /// The draw only adds to its two targets and writes nothing outside `tile`, so it can be
        /// drawn into images of its own (TakeLampTargets).
        bool adds_in_tile = false;
        /// The size of the draw's pass.
        vk::Extent2D pass{};
        /// bbport (r71_lamp-target-log): the draw's pixel shader and colour target mask, only
        /// logged when its targets do not fit.
        u64 ps_hash = 0;
        u32 mrt_mask = 0;
    };

    void OnLightDraw(VideoCore::ImageId color0, VideoCore::ImageId color1, const Inputs& inputs);

    /// Right after OnLightDraw: the two images its draw is to be drawn into in place of the light
    /// targets (layout General), when the draw went into a batch that keeps the lamps' light
    /// apart. Asked once per draw.
    [[nodiscard]] std::optional<std::array<vk::ImageView, 2>> TakeLampTargets() noexcept {
        if (!std::exchange(redirect_draw, false)) {
            return std::nullopt;
        }
        return std::array<vk::ImageView, 2>{*lamp[0].view, *lamp[1].view};
    }
    /// A batch is collected whose lamps are drawn apart: a draw that only adds to the light
    /// targets need not end it.
    [[nodiscard]] bool Apart() const noexcept {
        return apart && !tiles.empty();
    }
    void KeptAdding() noexcept {
        ++kept_adding;
    }
    /// Something that is not a draw (a compute pass, a clear, a copy) may read or write the light
    /// targets or the depth: a batch whose lamps are drawn apart ends here, so that they hold
    /// the lamps' light.
    void EndApart(bool animate_noise) {
        if (Apart()) {
            ++dispatch_flushes;
            Flush(animate_noise);
        }
    }

    void Flush(bool animate_noise);
    [[nodiscard]] bool Pending() const noexcept {
        return !tiles.empty();
    }
    void Ended(u64 hash);
    /// Statistics: Ended() was just called for a draw whose place on screen is not counted yet.
    [[nodiscard]] bool EndingUncounted() const noexcept {
        return ending_uncounted;
    }
    /// BB_RT_LAMP_TRACE=1: the first lamp draws and batch-ending draws of one frame are printed.
    [[nodiscard]] bool Tracing() const noexcept {
        return trace_left != 0;
    }
    /// Another draw begins: the one that ended a batch is past.
    void NextDraw() noexcept {
        ending_uncounted = false;
    }
    /// Statistics: where the draw that ended the batch draws, to count the ones that write none
    /// of the cells the batch took.
    void EndingDraw(const vk::Rect2D& area);
    [[nodiscard]] std::array<VAddr, 2> PendingAddresses() const;
    void Kept() noexcept {
        ++kept_draws;
    }

    void OnFrameEnd();

    void Drop();
    /// At the end of a frame: a batch of lamps drawn apart that no draw ended loses its light.
    void DropUnended() {
        if (Apart()) {
            ++unended;
            Drop();
        }
    }

private:
    bool Ready();
    /// Ray traced lamp shadows: ray tracing on and their own toggle set.
    bool RaysWanted() const;

    struct OwnImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
        u32 width = 0, height = 0;
    };
    bool EnsureImage(OwnImage& own, u32 width, u32 height, vk::Format format, const char* name,
                     vk::ImageUsageFlags more_usage = {});
    /// Whether a batch starting now can keep its lamps' light apart; the lamp images are then
    /// there, all zero.
    bool BeginApart(u32 width, u32 height);
    /// Copies `regions` of both light targets to the same places in the snapshots. keep: the rest
    /// of the snapshots keeps what earlier copies put there. False: the pass turned itself off.
    bool CopySnapshot(const std::array<VideoCore::ImageId, 2>& ids,
                      const std::array<VideoCore::Image*, 2>& targets, bool reduced,
                      std::vector<vk::ImageCopy> regions, bool keep);
    /// Marks the snapshot cells `rect` touches as taken by the batch being collected and returns
    /// the ones that were not yet, as copy regions.
    std::vector<vk::ImageCopy> TakeSnapshotCells(const std::array<s32, 4>& rect, u32 width,
                                                 u32 height);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    RtShadow& rt_shadow;
    vk::UniqueDescriptorSetLayout ray_set_layout;
    vk::UniquePipelineLayout ray_layout;
    vk::UniquePipeline ray_pipeline;
    CameraMotion& camera_motion;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::UniqueSampler sampler;
    OwnImage snapshot[2];
    // bbport: ray traced lamps took a copy of both whole light targets at the start of every batch,
    // though the pass reads the copy only inside the batch's tiles: several hundred batches a frame
    // where another light's draw follows each tile's lamps, 7 ms of GPU time at 1920x1080. Now a
    // tile's part is copied when the tile joins the batch, unless an earlier tile of the batch
    // already took it. The parts are whole cells of SnapshotCell pixels, so a lamp draw is always
    // preceded by the copy of every cell it can write. BB_RT_LAMP_SNAPSHOT=0 or experiment mask 64
    // (BB_TOGGLE_FILE): whole-image copies again.
    // bbport: lamps apart. The game draws each tile of its light grid as the tile's lamps and
    // then another light's quad over the same tile, which ended the batch: one batch, one
    // snapshot copy and one shadow pass per tile, 480 a frame (6.4 ms of GPU time at 1920x1080),
    // and only the first of them reused last frame's result. A lamp quad only adds light, inside
    // its scissor. So the lamps of a ray traced batch are drawn into two images of their own
    // (lamp, all zero between batches) with the pipeline and depth they would have had; draws
    // that only add to the light targets no longer end the batch (Rasterizer::
    // EffectsBeforeTargets), and one pass adds the lamps' light, shadowed, to the light targets
    // and zeroes it. No snapshots. BB_RT_LAMP_APART=0 or experiment mask 128 (BB_TOGGLE_FILE):
    // snapshots again.
    OwnImage lamp[2];
    bool apart = false;          ///< the batch being collected draws its lamps into `lamp`
    bool lamp_dirty = true;      ///< `lamp` holds something: to be cleared before the next batch
    bool lamp_laid_out = false;
    bool lamp_format = false;    ///< the light targets' format can be drawn into and blended
    bool redirect_draw = false;  ///< OnLightDraw's draw goes into `lamp`
    u32 apart_refused = ~0u;     ///< the frame in which a batch could not be started apart
    u32 apart_draws = 0;         ///< this frame
    u32 kept_adding = 0;         ///< this frame: adding draws that did not end a batch
    bool apart_last_frame = false; ///< the last frame drew lamps apart
    u32 flushed_in_draw = 0;     ///< since the last report: batches ended by a lamp draw
    u32 unended = 0;             ///< since the last report: batches lost at the end of a frame
    u32 lost_passes = 0;         ///< since the last report: apart batches whose pass was not run
    u32 dispatch_flushes = 0;    ///< this frame: batches ended by a compute pass, a clear or a copy
    u32 apart_passes = 0;        ///< this frame: passes run for lamps drawn apart
    bool tile_snapshots = false;    ///< the batch being collected copies its snapshot by tile
    bool snapshot_laid_out = false; ///< the snapshots have been through a copy since they were made
    std::vector<u64> snapshot_cells; ///< one bit per cell: taken by the batch being collected
    u32 snapshot_cells_wide = 0;
    std::array<std::vector<u32>, 2> cell_rows; ///< scratch of TakeSnapshotCells
    bool ending_uncounted = false;
    u64 ending_hash = 0;
    u32 trace_left = 0;
    bool traced = false;
    u32 batch_copies = 0;     ///< snapshot copies of the batch being collected
    u32 ended_placed = 0;     ///< this frame: batch-ending draws whose place on screen is known
    u32 ended_apart = 0;      ///< this frame: those of them that drew away from the batch's cells
    u32 snapshot_copies = 0;  ///< this frame
    u64 snapshot_pixels = 0;  ///< this frame, both images
    std::array<VideoCore::ImageId, 2> pending{};
    std::array<u64, 2> pending_uid{};
    struct Tile {
        std::array<s32, 4> rect;
        u32 first_light;
        u32 count;
    };
    std::vector<Tile> tiles;
    std::vector<u32> data;
    std::unique_ptr<VideoCore::Buffer> light_data;
    u32 frame_index = 0;
    u32 batches = 0;
    u32 frame_tiles = 0;
    bool one_tile_batches = false;
    bool merged = false;
    u32 kept_draws = 0;
    u32 lamp_pick = 1;
    bool lamp_reuse = false; ///< LANTERN_RT_LAMP_REUSE=1
    OwnImage history[2];
    std::array<bool, 2> history_laid_out{};
    u32 history_index = 0;
    bool history_written = false;
    bool history_fresh = false;
    // bbport (r52_follow-soft): the follow state beside the history (point_shadow_ray.comp
    // follow_prev, follow_cur), one R32F a pixel, taken in turn with it (history_index); made
    // with the history, laid out and zeroed on first use.
    std::array<OwnImage, 2> follow;
    std::array<bool, 2> follow_laid_out{};
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 and its builds made (Ready): the
    // pass that averages runs as a trace and a resolve (point_shadow_ray.comp MODE_TRACE,
    // MODE_RESOLVE), with every pixel's answer in `answers` (RG32UI, 8 bytes a pixel; made by
    // Flush only while `centred`, sized by the pass that splits, laid out on first use, never
    // cleared). half_centred: HalfReady made the half-resolution build's centred form (else its
    // plain one, and the half-resolution pass does not split). answers_short: a pass that would
    // split had no room for the image (logged once).
    bool centred = false;
    bool half_centred = false;
    OwnImage answers;
    bool answers_laid_out = false;
    bool answers_short = false;
    // bbport (r61_lamp-window-cost): the resolves' own builds (point_shadow_ray_resolve_comp, made by
    // Ready, and point_shadow_ray_half_resolve_comp, made by HalfReady, beside the centred builds,
    // with the same bindings): the centred build in which every dispatch is a resolve, so its ray
    // code cannot be reached. resolve_wanted: BB_LAMP_SHADOW_RESOLVE_BUILD is not 0 (read once, by
    // Ready). A build that is null (not wanted or not made): its resolves run the centred build, which
    // r60 ran them in.
    bool resolve_wanted = false;
    vk::UniqueDescriptorSetLayout resolve_set_layout, half_resolve_set_layout;
    vk::UniquePipelineLayout resolve_layout, half_resolve_layout;
    vk::UniquePipeline resolve_pipeline, half_resolve_pipeline;
    // bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR=1 (LampShadowTune::colour, read at start).
    // colour_mode: Ready and HalfReady made the lamp builds in their COLOUR form (and the CARDS builds'
    // layouts with its binding). colour_image: point_shadow_ray.comp's colour image, three parts of the
    // pass's size stacked (A2B10G10R10, 4 bytes a pixel each; made by Flush at the pass's size, laid
    // out on first use, never cleared). colour_wrote_frame: the frame of the last pass that wrote a
    // history, when it wrote that history's colour too (~0u: it did not, or none since the image).
    // For the r92 line after the lamp line (TrackLamps): passes shadowed in colour, those of them
    // that read their colour history, and passes with the COLOUR builds that stayed grey.
    bool colour_mode = false;
    OwnImage colour_image;
    bool colour_laid_out = false;
    u32 colour_wrote_frame = ~0u;
    u32 line_colour = 0, line_colour_read = 0, line_colour_grey = 0;
    std::array<float, 12> last_view{}, pending_view{};
    std::array<float, 16> last_proj{}, pending_proj{};
    bool last_valid = false, pending_valid = false;
    u32 ended_by_draws = 0;
    std::array<u64, 4> ending_hashes{};
    bool reported = false;
    float length_m = 2.5f;
    float thickness_m = 0.6f;
    float strength = 0.85f;
    float fade_start_m = 18.0f;
    float fade_end_m = 30.0f;
    float bias_m = 0.03f;
    u32 steps = 16;
    // bbport (r41_lamp-shadows): the ray traced pass's tuning (BB_LAMP_SHADOW_*, read once), which
    // Flush hands the shader while experiment 35184372088832 (LampRepairOffBit) is clear; whether
    // the last ray traced pass had it (-1: none yet), for the log line at each change.
    LampShadowTune tune;
    int repair_state = -1;
    // bbport (r42_lamp-soft): the area lamp. The lamps of the pass that takes the history, told
    // apart and followed from frame to frame (TrackLamps; track_index: the lamp of each record
    // of that pass, track_frame: the frame it last ran on); whether the history written on this
    // frame, and the one the frame before left, hold ratios averaged over the frames
    // (HistoryBlend) and not LANTERN_RT_LAMP_REUSE's; what the lamps were on the last pass that
    // could take the history (-1: none yet), for the log line at each change; frames since the
    // line that says where the lamps are (the first one comes two seconds in).
    LampTrack track;
    std::vector<s8> track_index;
    u32 track_frame = ~0u;
    bool history_blend = false, history_blended = false;
    // bbport (r48_lamp-softness): the lamp's radius of the pass that wrote the history (-1: none
    // yet; a history written at another radius is not read), and the radius the log last told.
    float history_radius_m = -1.0f, told_radius_m = -1.0f;
    int soft_state = -1;
    u32 soft_lines = 0;       ///< lines that said what the lamps are (at most SoftLines)
    u32 blend_unread = 0;     ///< frames in a row on which the averaging pass could not read its history
    // Since the last line that says where the lamps are: frames the pass averaged on, those of
    // them on which it read its history, camera cuts it did not read across, and ray traced
    // lamp passes that ran beside it with point lamps. bbport (r44_half-area-lamp): line_half:
    // the frames of line_blend on which the pass ran at half resolution.
    u32 line_blend = 0, line_read = 0, line_cuts = 0, line_beside = 0, line_half = 0;
    // bbport (r93_lamp-shadow-spatial): the frames of line_blend whose pass ran its resolve with word 0
    // bit 26 (BB_LAMP_SHADOW_SPATIAL=1 and the centred window); said in the r93 line after the r42 line
    u32 line_spatial = 0;
    u32 lamp_line_frames = 480;
    void TrackLamps(u32 end, bool blend, bool read, bool line);
    // bbport (r68_lamp-target-mismatch): light draws skipped because their targets did not fit
    u64 target_mismatches = 0;
    // bbport (r71_lamp-target-log): the combinations of skipped light draws already logged (at
    // most TargetMismatchKinds; further ones are counted in mismatch_unlisted, not logged).
    // misfit bits: 1 format, 2 no storage use, 4 no transfer-source use, 8 not eligible for the
    // reduced path, 16 size differs from target 0.
    struct TargetMismatch {
        std::array<u32, 2> format{}, usage{}, width{}, height{}, misfit{};
        std::array<u64, 2> address{};
        u64 ps_hash = 0;
        u32 mrt_mask = 0;
        bool adds_in_tile = false;
        bool reduced = false;
        bool operator==(const TargetMismatch&) const = default;
    };
    static constexpr u32 TargetMismatchKinds = 16;
    std::array<TargetMismatch, TargetMismatchKinds> mismatch_kinds{};
    std::array<u64, TargetMismatchKinds> mismatch_kind_draws{};
    std::array<u32, TargetMismatchKinds> mismatch_kind_frame{};
    u32 mismatch_kind_count = 0;
    u64 mismatch_unlisted = 0;
    u32 mismatch_line_frame = 0; ///< the frame of the first skip, then of the last draws line
    void LogTargetMismatch(const std::array<VideoCore::Image*, 2>& targets,
                           const std::array<u32, 2>& misfit, bool reduced, const Inputs& inputs);
    bool tried = false;
    bool failed = false;
    // bbport (r65_lamp-half-at-start): Ready is running from the constructor (only its log
    // lines differ: they say "at start")
    bool at_start = false;
    // bbport (r32_lamp-half, r37_menu-options): the lamps-apart pass traces pixel (2x, 2y) of
    // each 2x2 block first, then the other three where the answers around them differ
    // (point_shadow_ray_half_comp; changes the picture). On while BB_LAMP_SHADOW_HALF=1 or, with
    // the variable not set, while lantern.ini's graphics_lamp_shadow_half is (read every pass);
    // HalfReady makes the pipeline the first time a pass wants it. Experiment 72057594037927936
    // set: the full-resolution pass, as before.
    // bbport (r65_lamp-half-at-start): Ready runs at start (the constructor) when the lamp pass
    // is wanted then and BB_LAMP_SHADOW_AT_START is not 0, else at the first lamp draw; at start
    // it also calls HalfReady when HalfWanted and ray traced lamps are wanted then. Otherwise,
    // and for a switch to the half resolution later, the build is made on first use, as before.
    // bbport (r44_half-area-lamp): the half-resolution pass has the area lamp too, averaged in
    // the history like the full-resolution pass's (Flush). Experiment 2305843009213693952 set:
    // point lamps without a history at half resolution, as before r44.
    int half_env = -1;        ///< BB_LAMP_SHADOW_HALF: -1 not set, 1 for "1", 0 for anything else
    bool half_tried = false;  ///< HalfReady made its attempt
    bool half_made = false;   ///< the half-resolution pipeline and its counters exist
    bool HalfReady();
    /// bbport (r65_lamp-half-at-start): BB_LAMP_SHADOW_HALF when set, else
    /// graphics_lamp_shadow_half as it is now (Flush's test and Ready's, so they cannot differ)
    bool HalfWanted() const;
    /// bbport (r65_lamp-half-at-start): a pass has asked for the half resolution (Flush). The
    /// counters line (OnFrameEnd) waits for it, as it waited for HalfReady before r65, so a build
    /// made at start does not print lines of zeros from the title screen on.
    bool half_asked = false;
    bool half_laid_out = false;
    bool half_cleared = false;  ///< half_counts zeroed (by the first half pass's commands)
    u32 half_passes = 0;        ///< half-resolution passes recorded
    u32 half_frames = 0;        ///< frames since the last counter line
    u32 half_line_passes = 0;   ///< since the last line: half-resolution passes
    u32 half_line_full = 0;     ///< since the last line: apart passes at full resolution
    u32 half_line_soft = 0;     ///< since the last line: half-resolution passes that averaged area lamps (radius not zeroed)
    OwnImage half_answers;
    std::unique_ptr<VideoCore::Buffer> half_counts, half_readback;
    std::array<u32, 16> half_last{};
    vk::UniqueDescriptorSetLayout half_set_layout;
    vk::UniquePipelineLayout half_layout;
    vk::UniquePipeline half_pipeline;
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 (with BB_RT_CARD_ALPHA=2): the lamp rays read the
    // cut-out cards. The ray pass's build and the half-resolution build in their CARDS form
    // (CardLampsReady, from Ready and HalfReady: never compiled in play); their set 1 (rows, pool,
    // layer info, layers, counters): card_set is written once for the handles card_set_*, and a
    // new one is made from card_pool only when one of them changes (at most CardSetsMost); the
    // counters (one pass in CardCountEvery counts the rays of one pixel in 64; card_readback: a copy
    // taken before each counted pass) and the 600-frame line (CardLampsLine). A pass binds a CARDS
    // build only while the TLAS holds a card instance with CARD_LAMP_MASK (CardLampSet), else the
    // build of before. card_cap_bits: BB_RT_CARD_LAMP_CAP as tuning word 0 bits 12-17;
    // card_texel_scale: BB_RT_CARD_LAMP_TEXELS (CardRayTexelScale), the builds' specialization
    // constant.
    void CardLampsReady(bool half);
    vk::DescriptorSet CardLampSet(bool half);
    void CardLampsLine();
    vk::UniqueDescriptorSetLayout card_set_layout;
    vk::UniqueDescriptorPool card_pool;
    vk::DescriptorSet card_set{};
    vk::Buffer card_set_rows, card_set_pool, card_set_info;
    vk::ImageView card_set_layers;
    vk::Sampler card_set_sampler;
    u32 card_sets_made = 0;
    u32 card_cap_bits = 0;
    float card_texel_scale = 1.0f;
    vk::UniqueDescriptorSetLayout card_ray_set_layout, card_half_set_layout;
    vk::UniquePipelineLayout card_ray_layout, card_half_layout;
    vk::UniquePipeline card_ray_pipeline, card_half_pipeline;
    std::unique_ptr<VideoCore::Buffer> card_counts, card_readback;
    std::array<u32, 72> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32, then 48; r62k: was 48, then 64; r62l: was 64)
    bool card_counts_clear = true;
    u32 card_passes = 0, card_frames = 0, card_line_passes = 0, card_line_counted = 0,
        card_line_plain = 0;
};

}
