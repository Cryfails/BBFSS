// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131c_cabinet-glass-clear): the cabinet's glass pane leaves the opaque G-buffer and comes back as a thin glass layer
// over the lit scene. Registry hits of a clearing kind (glass_registry.h: Clears, the cabinet only; the mirror stays as it is)
// are REDIRECTED, not skipped: the draw is recorded as before (its vertex shader still writes the ray traced capture) but into
// side images: colour target 0 (normal) and 2 (albedo) go to two side colour images, the other colour targets to sink images
// of their own format (written, never read), the depth attachment goes to a side depth image. The game's G-buffer, depth and stencil never
// see the pane, so the game's lighting treats what is behind it as it would without the pane, and its material and specular
// targets (the crackle, most likely) are never read. glass_clear.comp then puts a film of the pane's own albedo and a Fresnel
// sheen over the lit scene (EffectsBlendedScene, after the glass view's SHOW).
//
// Where (each a null pointer test while the class is not made):
//  - GlassRegistryDraw (vk_glass_view.cpp): DrawContext::clear_draw = Wants(...) for a hit of a clearing kind.
//  - Rasterizer::DrawRecord, after the lamps-apart swap, before the pass begins: Redirect swaps the attachments of `state`.
//  - EffectsBlendedScene: Composite. EffectsOnFrameEnd: OnFrameEnd (the live knob, counters, the log lines) and the knob's
//    state to RtShadow (SetGlassClear: a clearing kind's glass record then takes RtGlassMask alone).
// Guards (else the draw is drawn as before and counted "kept"): a clear in the pass (not moved to side images); a stencil test
// whose func is not ALWAYS; a depth func that is neither less nor greater kind, or no depth write; another camera's pass; a menu
// preview frame. Forward draws (1 to 4 colour targets) are not redirected: only the G-buffer draw and a depth-only pre-pass.
//
// Off (no BB_GLASS_CLEAR=1 and no live knobs file): no GlassClear is made; a registry hit costs a plain false store.
// Made, knob off: Wants returns false at its first test; nothing else runs. Memory (on, made at the first redirect): side
// albedo and normal 4 bytes a pixel each, side depth 4 to 5 bytes, and a sink of the draw's format for each other colour target
// (fixed (r131c review); 4 to 16 bytes each, the motion target 16): about 60 to 95 MB at 1920x1080.
#pragma once

#include <array>

#include "common/types.h"
#include "../host_shaders/glass_clear_layout.h"
#include "video_core/renderer_vulkan/glass_registry.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
struct GraphicsPipelineKey;
class Instance;
class RtShadow;
class Runtime;
class SceneTargets;

class GlassClear {
public:
    /// The registry is on (the caller asks) and BB_GLASS_CLEAR=1 (read once), or, in a build with the live knobs header,
    /// BB_LIVE_KNOBS_FILE is set (the knob is then switched with the live knob BB_GLASS_CLEAR).
    [[nodiscard]] static bool Wanted();
    GlassClear(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
               SceneTargets& scene_targets, CameraMotion& camera_motion, RtShadow& rt_shadow);
    ~GlassClear();
    GlassClear(const GlassClear&) = delete;
    GlassClear& operator=(const GlassClear&) = delete;

    /// The knob is on now (a member bool, set once a frame by OnFrameEnd).
    [[nodiscard]] bool On() const {
        return on;
    }
    /// A registry hit `hit` (entry index + 1) was found: is this draw one to redirect? `shape_ok`: a G-buffer draw or a draw with
    /// no colour target; `preview`: a menu's 3D preview frame; `same_camera`: its depth is the scene camera's.
    [[nodiscard]] bool Wants(u8 hit, bool shape_ok, bool preview, bool same_camera);
    /// Before the draw's pass begins: swaps the attachments of `state` for the side images. `normal`, `albedo`, `depth`: the
    /// draw's own images (targets 0 and 2, the depth target); `depth_mode`: 0 less or less-equal, 1 greater or greater-equal,
    /// else the draw is not redirected; `stencil_func`: its stencil test has a func other than ALWAYS; `key`: the draw's
    /// pipeline (its colour formats; no colour target: a depth pre-pass). False: nothing changed (drawn as before).
    /// fixed (r131c review): every other colour target the draw has gets a sink image of the pipeline's format, never a null
    /// view (VK_EXT_dynamic_rendering_unused_attachments is not enabled: a null view with a format is VUID 08912).
    bool Redirect(RenderState& state, VideoCore::ImageId normal, VideoCore::ImageId albedo, VideoCore::ImageId depth,
                  u32 depth_mode, bool stencil_func, const GraphicsPipelineKey& key);
    /// After the opaque lighting: the film and sheen over the lit scene, once for the redirects made since the last time.
    /// `scene` the lit scene colour, `depth` the scene depth, `jitter` the frame's, `lamps_pending` a lamps-apart batch is open.
    void Composite(VideoCore::ImageId scene, VideoCore::ImageId depth, std::array<float, 2> jitter, bool lamps_pending);
    /// Every frame end: the live knob, the GPU counters, and every LineFrames frames (and at each flip) the log line.
    void OnFrameEnd();

    /// GlassClear::Push, word for word with glass_clear.comp (96 bytes).
    struct Push {
        std::array<float, 4> proj{};
        std::array<float, 12> view{};
        std::array<float, 2> size{};
        std::array<float, 2> jitter{};
        float film = 0.0f;
        float f0 = 0.0f;
        float hole_metres = 0.0f;
        u32 flags = 0;
    };
    static_assert(sizeof(Push) == 96);
    static_assert(GLASS_CLEAR_GROUP == GlassRegistryRules::ViewGroup && GLASS_CLEAR_WORDS >= 2);

    static constexpr u32 LineFrames = 600;

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Buffer {
        VkBuffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    bool Ready();
    bool EnsureSize(u32 width, u32 height);
    bool EnsureDepth(vk::Format format, bool stencil);
    bool EnsureColour(vk::Format normal_format, vk::Format albedo_format);
    bool EnsureSink(u32 slot, vk::Format format);
    void ReleaseImages();
    void Fail(const char* why);
    void Line(const char* why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;
    const GlassRegistryRules::Table& table;

    // the pass and the counters (made at the first redirect)
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    Buffer counters; ///< host coherent, GLASS_CLEAR_WORDS words, written by the pass (atomics), read at the frame end
    std::array<u32, 2> counted_last{};
    // the side images (made at the first redirect, again when the pass size or a format changes)
    VideoCore::UniqueImage normal_image, albedo_image, depth_image;
    vk::UniqueImageView normal_view, albedo_view, depth_attach_view, depth_sample_view;
    vk::Format normal_format{}, albedo_format{}, depth_format{};
    // the sinks: the draw's other colour targets (material, specular, ..., motion), written and never read
    std::array<VideoCore::UniqueImage, 8> sink_images;
    std::array<vk::UniqueImageView, 8> sink_views;
    std::array<vk::Format, 8> sink_formats{};
    bool depth_stencil = false;
    u32 side_width = 0, side_height = 0;
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool on = false;
    bool told = false;
    bool told_shape = false;
    bool clear_due = true;          ///< the side depth is not known to be clear: the next redirect clears it first
    bool redirected_frame = false;  ///< a redirect was made this frame (its depth mode is `reverse_z`)
    bool pending_composite = false; ///< redirects since the last Composite
    bool reverse_z = false;
    float f0 = GlassRegistryRules::DefaultF0;
    u64 frame = 0, window_start = 0;

    struct Stats {
        u32 frames = 0, redirected = 0, depth_only = 0, composites = 0;
        u32 kept_clear = 0, kept_stencil = 0, kept_other = 0, kept_camera = 0, kept_preview = 0, skip_shape = 0;
        u64 visible = 0, holes = 0, rt_records = 0;
    } stats;
    u64 rt_records_last = 0;
};

} // namespace Vulkan
