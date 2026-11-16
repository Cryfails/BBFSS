// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): a wet film on the blood pool in the game's
// G-buffer, lit by the game's own lights (blood_sheen.h has the knobs, the key, the rule and the
// passes' rules; host_shaders/blood_sheen.comp the passes).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsBeforeResources, every direct draw (BeforeDraw): before its textures, barriers and pass.
//    It notes each G-buffer pass's depth and targets 0 (normal), 1 (gloss), 2 (albedo), 3 (specular); before
//    a keyed draw of that pass (at most MaxKeyedDraws) it records SNAPSHOT; at the first light draw
//    after the pass (shadow resolve, sun or moon, or a lamp) it records EDIT.
//  - EffectsAfterDraw, every draw (AfterDraw): right after a keyed draw, MARK.
//  - EffectsBlendedScene, after the opaque lighting of each G-buffer pass (Show): SHOW over the lit
//    scene colour, once after each EDIT: with "show" the test view, else (r100e) the dimming of the
//    picked pixels (BB_BLOOD_SHEEN_DARKEN above 0).
//  - EffectsOnFrameEnd (OnFrameEnd): the counters and every LineFrames frames two log lines.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do. A menu's 3D preview frame (CameraMotion::PreviewFrame) is left alone.
//
// Off (BB_BLOOD_SHEEN unset or 0): the rasterizer makes no BloodSheen (Wanted), so nothing of this is
// made or run; the frame is as before, bit for bit. On: four pipelines and two small buffers are made
// at the first pass; two R32UI images of the scene's size (8.3 MB each at 1920x1080) then, and anew
// when the scene's size changes. GPU work only in a G-buffer pass with a keyed draw (two passes over
// the scene each) or, with the albedo rule and no key, one EDIT a G-buffer pass.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_sheen.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace AmdGpu {
union Regs;
}

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class BloodSheen {
public:
    /// BB_BLOOD_SHEEN names a strength above 0 or "show" (BloodSheenRules::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    BloodSheen(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~BloodSheen();
    BloodSheen(const BloodSheen&) = delete;
    BloodSheen& operator=(const BloodSheen&) = delete;

    /// What the hook knows of the draw's pixel shader (the hashes live in the effects file).
    struct Kind {
        bool lamp = false;    ///< a draw of the game's light grid (PointLightCount)
        bool sun = false;     ///< the game's sun or moon (DirectionalFragmentShaderHash)
        bool resolve = false; ///< the game's sun shadow resolve (ShadowResolveHash)
    };
    /// Before every direct draw's resources: `targets` its colour targets (only those in its mrt_mask
    /// are this draw's), `depth` its depth target; `lamps_pending`: a lamps-apart batch is still
    /// open. (`jitter`, the frame's viewport shift, is not needed by the G-buffer passes.)
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                    Kind kind, bool lamps_pending, std::array<float, 2> jitter);
    /// After every draw: MARK when it was a keyed draw.
    void AfterDraw();
    /// After the opaque lighting of a G-buffer pass: the test view over the lit scene `scene` (not
    /// while a lamps-apart batch is open, `lamps_pending`: then left out for this pass).
    void Show(VideoCore::ImageId scene, bool lamps_pending);
    /// Every frame end: the counters, and every LineFrames frames the "Blood sheen (r100d):" lines.
    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
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

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    /// The G-buffer pass's albedo and depth stand where the tag does (and its gloss and specular
    /// targets are RGBA8 when `material`); counts and says once what did not fit.
    bool Fits(bool material, u32& width, u32& height, bool& reduced);
    /// Commands every first pass of a frame records first: the last frame's counters to the host,
    /// this frame's slot cleared.
    struct CounterStep {
        bool clear = false, copy_back = false;
        u32 slot = 0;
    };
    CounterStep TakeCounterStep();
    void Snapshot();
    void Mark();
    void Edit();
    void Fail(const char* why);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, mark_pass, edit_pass, show_pass;
    /// MARK's tag (a keyed draw's print where it wrote the pixel; after EDIT what was picked) and
    /// SNAPSHOT's prints before a keyed draw: two R32UI images of the scene's size.
    VideoCore::UniqueImage tag_image, before_image;
    vk::UniqueImageView tag_view, before_view;
    u32 tag_width = 0, tag_height = 0;
    bool tag_fresh = false; ///< made and not yet in the General layout
    /// Two slots of SlotWords counters (this frame's, the one before), and the host copy.
    Buffer counters, readback;
    u64 counter_frame = 0; ///< frame + 1 whose slot was cleared; 0: none yet
    u64 counter_used = 0;  ///< frame + 1 that last used a slot
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    u64 frame = 0;

    // This G-buffer pass, from BeforeDraw.
    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_albedo{}, gbuffer_specular{};
    VideoCore::ImageId gbuffer_normal{}; ///< target 0 (r100e: flattened under the film)
    bool gbuffer_seen = false, edit_tried = false;
    u32 keyed_in_pass = 0;   ///< keyed draws that got SNAPSHOT and MARK in this pass
    bool show_due = false;   ///< EDIT ran in this pass: SHOW may paint once
    bool pending = false;    ///< SNAPSHOT recorded for the draw being made: MARK follows it
    bool told_unfit = false, told_first = false, told_show = false, told_normal = false;

    struct Stats {
        u32 frames = 0, keyed = 0, keyed_frames = 0, over_cap = 0, edits = 0, shows = 0;
        u32 edit_pending = 0, no_key_draw = 0, cannot = 0, no_room = 0, previews = 0, lamps_pending = 0, normals = 0;
        u32 peak_shows = 0; ///< r100k: shows with the luminance ceiling on
    } stats;
    u32 keyed_this_frame = 0;
};

} // namespace Vulkan
