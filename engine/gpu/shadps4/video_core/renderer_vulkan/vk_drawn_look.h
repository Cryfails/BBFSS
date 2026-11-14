// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look, an optional hand-painted look. Brush strokes fixed to
// the world are laid on the scene's solid surfaces before fire, glows, fog and particles are
// drawn, so those stay as the game draws them, and before the upscaler, the game's own colour
// processing and the HUD, which treat the strokes as they treat a texture. Colours are not
// changed. Off by default: graphics_drawn_look in lantern.ini and the menu's Picture tab. While
// it is off, or its strength is 0, the rasterizer calls nothing here but OnFrameEnd: no
// pipeline, no image, no pass.
//
// Built so far (stages 1 and 2 of the design): the switch, the passes' place in the frame, the
// strokes themselves (host_shaders/paint_strokes.comp), and a test view
// (graphics_drawn_look_debug) that paints every stroke in a flat colour of its own. Not built:
// ink lines, painted shadow edges.
//
// The passes, all compute, recorded in Paint:
//   paint_prep.comp     the scene colour and the view depth into the copy (the stroke pass
//                       rewrites the scene in place and must read it as it was)
//   paint_stats.comp    at half size: the copy's level 1 and the marks' level 0 (how much the
//                       picture varies under a stroke, and whether along lines)
//   paint_mips.comp     once a level: the smaller levels of both, down to one texel
//   paint_key.comp      twice: the frame's key (how bright its surfaces are, the sky and single
//                       bright pixels left out), written over the copy's last level
//   paint_strokes.comp  the strokes into the scene colour
//   paint_lock.comp     the painted scene's means (a quarter of the size, and their smaller
//                       levels), then every place scaled back to the mean colour it had

#pragma once

#include <array>
#include <initializer_list>
#include <span>
#include <vector>
#include "common/types.h"
#include "video_core/renderer_vulkan/drawn_look_params.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class ObjectMotion;
class Runtime;
class SceneTargets;
class Scheduler;

class DrawnLook {
public:
    DrawnLook(const Instance& instance, Scheduler& scheduler,
              VideoCore::TextureCache& texture_cache, Runtime& runtime,
              SceneTargets& scene_targets, CameraMotion& camera_motion,
              ObjectMotion& object_motion);
    ~DrawnLook();

    /// The switch is on and the strength is above 0 (the rasterizer asks once a frame).
    [[nodiscard]] static bool Wanted();
    /// The scene's hooks below are never reached (no upscaler: BB_UPSCALER=none, or a GPU it
    /// cannot run on): the menu says so instead of offering a switch that does nothing.
    static void NoSceneHooks();

    /// A G-buffer pass's depth and world normals: the normals belong to the scene whose depth
    /// this is.
    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal);

    /// The three places a frame's strokes can be painted; the first that comes paints. The
    /// first two count only in the scene itself: a frame may draw the world a second time before
    /// it (a reflection in water, from a mirrored camera, with a depth of its own), and strokes
    /// painted there would leave the scene without any.
    /// The first blended draw without depth writes into the scene colour: the solid surfaces
    /// are in, the transparents start. The place the look is designed for. A draw of six
    /// indices or fewer counts when it tests the depth (a particle system of a few particles;
    /// r45b_drawn-look-fixes: it used to be taken for a full-screen pass and painted over):
    /// DrawnLookParams::SmallTransparent.
    void OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                        std::array<float, 2> jitter);
    /// A full-screen pass over the scene colour with fragment shader `hash` (a draw of six
    /// indices or fewer that is not one of the transparents above). On a frame with
    /// transparents the first such pass after them is remembered (the fog composite; another
    /// one takes its place only after it came first on CompositeFrames such frames in a row);
    /// on a frame without any, the strokes are painted before that same pass, so the fog is
    /// left unpainted on both kinds of frame.
    void OnSceneComposite(u64 hash, VideoCore::ImageId color, VideoCore::ImageId depth,
                          std::array<float, 2> jitter);
    /// (r45b_drawn-look-fixes) The draw that OnBlendedScene is called for next is a small one
    /// (DrawnLookParams::SmallTransparent), with fragment shader `hash`: when it is the frame's
    /// first transparent draw the log names it, once a shader.
    void OnSmallTransparent(u64 hash, u32 indices);
    /// Right before the upscaler's trigger: the last chance of a frame that had neither. Fog
    /// and particles are in the scene by now and get painted; such frames are counted.
    void OnBeforeUpscaler(VideoCore::ImageId color, VideoCore::ImageId depth,
                          std::array<float, 2> jitter);

    /// `wanted`: Wanted() as the rasterizer read it for the frame that starts now.
    void OnFrameEnd(bool wanted);

private:
    /// How a frame went: where its strokes were painted, or why they were not.
    enum Result : u32 { AtBlended, AtComposite, AtBeforeUpscaler, Preview, NoCamera, NoRoom,
                        NotReached, ResultCount };
    /// An image with all its levels down to one texel.
    struct OwnImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;                ///< all levels
        std::vector<vk::UniqueImageView> levels; ///< each level alone
        u32 width = 0, height = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    struct ViewEntry {
        vk::Image image;
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view;
        u64 last_use = 0;
    };
    /// A full-screen pass over the scene colour: its fragment shader, and which of that
    /// shader's passes in the frame it is (from 0). In frame_passes `nth` counts them.
    struct FullScreenPass {
        u64 hash = 0;
        u32 nth = 0;
    };

    bool Ready();
    bool CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                    std::span<const u32> code, const char* name);
    void Fail(const char* why);
    void ReleaseAll();
    [[nodiscard]] bool SceneDepth(VideoCore::ImageId depth) const;
    void Paint(Result place, VideoCore::ImageId color, VideoCore::ImageId depth,
               std::array<float, 2> jitter);
    bool EnsureImage(OwnImage& image, u32 width, u32 height, vk::Format format, const char* name);
    void ReleaseImage(OwnImage& image);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    void ReleaseViews();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    ObjectMotion& object_motion;

    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;
    vk::UniqueSampler sampler; ///< linear between texels and between levels, clamped
    OwnImage prep_copy; ///< the scene before the strokes, view depth (paint_prep.comp)
    OwnImage marks;     ///< half the size: what tells plain surfaces from detail (paint_stats.comp)
    /// A quarter of the size: the painted scene's means (paint_lock.comp); before the strokes
    /// its first texels hold the key's sums (paint_key.comp).
    OwnImage lock_means;
    std::array<ViewEntry, 6> view_cache{};
    u64 view_uses = 0;
    VideoCore::ImageId gbuffer_depth, gbuffer_normal;
    /// BB_DRAWN_LOOK_VIEW: a test view that decides instead of the ini's
    /// graphics_drawn_look_debug while the variable is set; -1 without it.
    int env_view = -1;
    bool tried = false;
    bool failed = false;
    bool was_wanted = false;
    /// The scene's size the images were last refused at for want of video memory (0: none).
    /// Not asked again at that size; another size, or the look switched off and on, asks again.
    u32 refused_width = 0, refused_height = 0;
    /// The depths of the last G-buffer pass of recent frames: the scene's own (it is drawn
    /// last; none known yet: any depth counts).
    std::array<VideoCore::ImageId, 4> scene_depths{};
    u32 scene_depth_next = 0;
    Result frame_result = NotReached;
    bool blended_this_frame = false;   ///< OnBlendedScene was reached (painted or not)
    bool composite_this_frame = false; ///< the full-screen pass after it was seen
    /// The full-screen passes of this frame so far, by shader, and the one that follows the
    /// transparents on the frames that have them (hash 0: none seen yet). `candidate` came
    /// first instead on the last `candidate_frames` such frames: a small sprite among the
    /// transparents that does not test the depth is drawn as such a pass too, and must not
    /// take the fog composite's place for being first once.
    static constexpr u32 CompositeFrames = 30;
    std::array<FullScreenPass, 16> frame_passes{};
    u32 frame_pass_count = 0;
    FullScreenPass composite{};
    FullScreenPass candidate{};
    u32 candidate_frames = 0;
    u32 composite_changes = 0;
    /// For the line every 600 frames the look was wanted on.
    std::array<u32, ResultCount> results{};
    u32 frames = 0;
    /// (r45b_drawn-look-fixes) The camera the last frame was painted with, for the frame after
    /// it (DrawnLookParams::Make, `previous`). `last_camera_set`: this frame stored one;
    /// `last_camera_valid`: the frame before did. `previous_frames`: for the line every 600
    /// frames.
    DrawnLookParams::Previous last_camera{};
    bool last_camera_set = false;
    bool last_camera_valid = false;
    u32 previous_frames = 0;
    /// The small transparent draw OnSmallTransparent announced, and the shaders already named.
    u64 small_hash = 0;
    u32 small_indices = 0;
    bool small_pending = false;
    std::array<u64, 8> small_seen{};
    u32 small_seen_count = 0;
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) do: those may come
    /// and go with the place a frame is painted at.
    u32 last_width = 0, last_height = 0, last_view = ~0u, last_inputs = ~0u;
    u32 input_lines = 0;
};

}
