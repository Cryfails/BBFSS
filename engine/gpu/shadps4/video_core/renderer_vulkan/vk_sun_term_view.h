// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (t129c_sun-term-view, TOOL): the ray traced sun and moon shadow term as a grey picture. BB_RT_SUN_TERM_VIEW=1 (live with the
// test tools' live knobs file, else read once; exactly "1" is on): after the sun trace the shadow target's alpha (the visibility the
// directional light reads, before the cloud shadows) is copied to an R8 image (Capture, from ContactShadow::Flush); EffectsBlendedScene
// (Show) then overwrites the lit scene colour with it: white lit, black shadowed. Off: nothing runs, nothing is allocated; the object
// is made only with the variable "1" or the live knobs file (Wanted), and its hooks are null pointer tests.
#pragma once

#include <array>

#include "common/types.h"
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

class SunTermView {
public:
    /// BB_RT_SUN_TERM_VIEW=1 (read once), or the live knobs file exists (the view is then switched with the live knob).
    [[nodiscard]] static bool Wanted();
    /// The one made (null while none is): ContactShadow::Flush asks it for the capture.
    [[nodiscard]] static SunTermView* Active() noexcept;
    SunTermView(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~SunTermView();
    SunTermView(const SunTermView&) = delete;
    SunTermView& operator=(const SunTermView&) = delete;

    [[nodiscard]] bool On() const {
        return on;
    }
    struct Round2Consumer {
        u64 frame = 0, show_uid = 0;
        u32 captures = 0, shows = 0, show_id = 0;
        bool present = false, on = false, failed = false, have_term = false;
    };
    [[nodiscard]] Round2Consumer Round2Snapshot() const noexcept {
        return {frame, round2_consumer.show_uid, round2_consumer.captures, round2_consumer.shows,
                round2_consumer.show_id, true, on, failed, have_term};
    }
    /// The sun trace just wrote the shadow target `target` (RGBA8 storage view, General layout, `width` x `height`): copies its alpha.
    void Capture(vk::ImageView target, u32 width, u32 height);
    /// After a G-buffer pass's opaque lighting: the lit scene `scene` takes the captured term as grey.
    void Show(VideoCore::ImageId scene, bool lamps_pending);
    /// Every frame end: reads the live knob (says a change), drops the frame's capture, counts, and every LineFrames frames a line.
    void OnFrameEnd();

    /// SunTermView::Push, word for word with sun_term_view.comp (8 bytes).
    struct Push {
        std::array<float, 2> size{};
    };
    static_assert(sizeof(Push) == 8);
    static constexpr u32 LineFrames = 600;

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    vk::ImageView SceneView(VideoCore::ImageId id);
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    bool Ready();
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    void Fail(const char* why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass copy_pass, show_pass;
    VideoCore::UniqueImage term_image;
    vk::UniqueImageView term_view;
    u32 term_width = 0, term_height = 0;
    bool term_fresh = false; ///< made and not yet in the General layout
    bool have_term = false;  ///< a capture of this frame is in the image
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    bool tried = false, failed = false, on = false, told_show = false;
    u64 frame = 0;
    Round2Consumer round2_consumer{};
    struct Stats {
        u32 frames = 0, captures = 0, shows = 0, skip_shape = 0;
    } stats;
};

} // namespace Vulkan
