// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): the glass registry's counters and the glass view, a test view that paints the pixels the
// registry's draws wrote (glass_registry.h has the table and the rules; host_shaders/glass_view.comp the passes).
//
// Where (hooks, each a null pointer test while BB_GLASS_TABLE is off):
//  - Rasterizer::DrawRecord, every direct draw, right before EffectsBeforeResources (GlassRegistryDraw): the draw's pair
//    hash is looked up in the table; a hit is counted (GlassRegistry::Hit), put in DrawContext::glass_hit (entry index + 1,
//    for RtShadow::Draw::glass_entry, S1's hand-off) and, with the view on, SNAPSHOT is recorded before the draw's pass.
//  - The next registry hook, EffectsBlendedScene (Show) and EffectsOnFrameEnd flush the pending MARK: compare the target
//    and the depth with the snapshot; a G-buffer draw leaves a tag where it wrote, a forward draw paints at once.
//  - EffectsBlendedScene (Show), after each G-buffer pass's opaque lighting: SHOW paints the tagged pixels whose depth is
//    still the draw's (a later draw in front, e.g. the hunter before the mirror, is not tinted) and clears the tags.
//  - EffectsOnFrameEnd: the counters, and every LineFrames frames the "Glass registry (r129a)" lines.
// Each pass ends the game's render pass (the next draw begins a new one), as BloodSheen's passes do. A menu's 3D preview
// frame (CameraMotion::PreviewFrame) and another camera's pass are left alone.
//
// Off (BB_GLASS_TABLE unset): the rasterizer makes no GlassRegistry and no GlassView; nothing of this runs.
// Registry on, view off: counters only. View on: four pipelines and two R32UI images of the scene's size are made at the
// first hit draw with the view on (and again when the scene's size changes); GPU work only for hit draws (at most
// MaxSnapshots a frame).
#pragma once

#include <array>
#include <atomic>

#include "common/types.h"
#include "video_core/renderer_vulkan/glass_registry.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

/// What the registry's hits were, counted per entry; made only when BB_GLASS_TABLE names a valid entry.
class GlassRegistry {
public:
    /// Says the table once (the entries, the errors, the view knob).
    GlassRegistry();
    /// BB_GLASS_TABLE off or without a valid entry: says so when it was asked for (or the view was), else nothing.
    static void SayOff();

    [[nodiscard]] const GlassRegistryRules::Table& Rules() const {
        return table;
    }
    /// A draw of entry `index` (0 based) was recorded. Any thread (a player's draw context).
    void Hit(u8 index) {
        frame_draws[index].fetch_add(1, std::memory_order_relaxed);
        frame_mask.fetch_or(1ull << index, std::memory_order_relaxed);
    }
    /// Every frame end: folds the frame into the window; every LineFrames frames the lines.
    void OnFrameEnd();
    /// For later stages: the entries (bit i = entry i) drawn in the last frame, and how many draws of entry i.
    [[nodiscard]] u64 LastFrameMask() const {
        return last_frame_mask;
    }
    [[nodiscard]] u32 LastFrameDraws(u32 i) const {
        return last_frame_draws[i];
    }

    static constexpr u32 LineFrames = 600;

private:
    const GlassRegistryRules::Table& table;
    std::array<std::atomic<u32>, GlassRegistryRules::MaxEntries> frame_draws{};
    std::atomic<u64> frame_mask{0};
    std::array<u32, GlassRegistryRules::MaxEntries> last_frame_draws{}, window_draws{}, window_frames{};
    u64 last_frame_mask = 0;
    u64 frames = 0;       ///< frame ends so far
    u64 window_start = 0; ///< `frames` when the window began
};

class GlassView {
public:
    /// BB_GLASS_VIEW=1 (read once), or, in a build with the live knobs header, BB_LIVE_KNOBS_FILE set (the view is then
    /// switched with the live knob BB_GLASS_VIEW). The caller also asks for a valid registry.
    [[nodiscard]] static bool Wanted();
    GlassView(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
              SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~GlassView();
    GlassView(const GlassView&) = delete;
    GlassView& operator=(const GlassView&) = delete;

    /// The view is on now (a member bool, set once a frame by OnFrameEnd).
    [[nodiscard]] bool On() const {
        return on;
    }
    /// Before a hit draw's resources and pass: `target0` its colour target 0 (the normal for a G-buffer draw, else the
    /// scene colour), `depth` its depth target, `gbuffer` it is a G-buffer draw (five or more colour targets), `kind`
    /// the entry's, `lamps_pending` a lamps-apart batch is still open.
    void Snapshot(VideoCore::ImageId target0, VideoCore::ImageId depth, bool gbuffer, GlassRegistryRules::Kind kind,
                  bool lamps_pending);
    /// The pending MARK (the draw after a SNAPSHOT), if any.
    void FlushMark();
    /// After a G-buffer pass's opaque lighting: paints and clears the tags. `scene` the lit scene (the pass's depth is the one
    /// the last G-buffer MARK was made with: the scene camera's).
    void Show(VideoCore::ImageId scene, bool lamps_pending);
    /// Every frame end: drops a pending MARK (the hit draw was the frame's last), reads the live knob, counters, and every
    /// LineFrames frames a line.
    void OnFrameEnd();

    /// GlassView::Push, word for word with glass_view.comp (32 bytes).
    struct Push {
        std::array<float, 2> size{};
        u32 kind = 0;
        u32 flags = 0;
        std::array<float, 4> colour{};
    };
    static_assert(sizeof(Push) == 32);

    static constexpr u32 LineFrames = 600;
    static constexpr u32 MaxSnapshots = 8; ///< hit draws a frame that get a SNAPSHOT and a MARK

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// A game image's view for a pass: the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written or read as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    bool Ready();
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    void Fail(const char* why);
    void Mark();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, mark_pass, paint_pass, show_pass;
    /// The tag (a G-buffer hit draw's depth bits and kind where it wrote) and SNAPSHOT's prints: two R32UI images of the
    /// scene's size.
    VideoCore::UniqueImage tag_image, before_image;
    vk::UniqueImageView tag_view, before_view;
    u32 tag_width = 0, tag_height = 0;
    bool tag_fresh = false; ///< made and not yet in the General layout
    bool clear_due = true;  ///< the tag's contents are not known to be zero: the next SNAPSHOT clears it
    bool tag_dirty = false; ///< a G-buffer MARK wrote tags since the last SHOW
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool on = false;
    bool told_on = false;
    u64 frame = 0;

    /// The hit draw a SNAPSHOT was recorded for, until its MARK.
    struct Pending {
        bool active = false;
        bool gbuffer = false;
        GlassRegistryRules::Kind kind = GlassRegistryRules::Kind::None;
        VideoCore::ImageId target0{}, depth{};
        u64 target0_uid = 0, depth_uid = 0; ///< their image_uid at the SNAPSHOT: the MARK runs only if both still are
    } pending;
    VideoCore::ImageId tag_depth{}; ///< the depth image of the last G-buffer MARK
    u64 tag_depth_uid = 0;          ///< its image_uid (SHOW runs only if it still is)
    u32 snapshots_this_frame = 0;
    bool told_show = false;

    struct Stats {
        u32 frames = 0, snapshots = 0, marks = 0, paints = 0, shows = 0;
        u32 skip_cap = 0, skip_preview = 0, skip_lamps = 0, skip_camera = 0, skip_shape = 0;
    } stats;
};

} // namespace Vulkan
