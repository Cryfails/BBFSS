// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <span>
#include "common/types.h"
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

class ScreenSpaceGI {
public:
    ScreenSpaceGI(const Instance& instance, Scheduler& scheduler,
                  VideoCore::TextureCache& texture_cache, Runtime& runtime,
                  SceneTargets& scene_targets, CameraMotion& camera_motion, RtShadow& rt_shadow);
    ~ScreenSpaceGI();

    void OnOpaqueScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                       std::array<float, 2> jitter);

    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId albedo,
                       VideoCore::ImageId normal, VideoCore::ImageId material,
                       VideoCore::ImageId specular);

    void OnAoDraw(VideoCore::ImageId ao);

    void OnFrameEnd();

private:
    struct OwnImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
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

    bool Ready();
    bool CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                    std::span<const u32> code, const char* name);

    bool EnsureImage(OwnImage& image, u32 width, u32 height, vk::Format format, const char* name);
    void ReleaseImage(OwnImage& image);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    RtShadow& rt_shadow;
    CameraMotion& camera_motion;

    Pass prep, gather, gather_ray, denoise, composite, probe_trace, probe_composite;
    Pass probe_reflect, probe_resolve;
    // bbport (r30_ssgi-half, r37_menu-options): the full-resolution glossy rays traced once per
    // flat 2x2 block (ssgi_probe.comp REFLECT and RESOLVE with HALF; changes the picture), while
    // BB_SSGI_HALF=1 or, with the variable not set, while lantern.ini's
    // graphics_gi_reflections_fewer_rays is (read every frame; HalfReady makes the pipelines the
    // first time a frame wants them). Counters in a device-local buffer,
    // copied to the host on counted frames (1 in 8); a line every 600 frames.
    struct HalfBuffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    static constexpr u32 HalfSlots = 16;
    int half_env = -1;       ///< BB_SSGI_HALF: -1 not set, 1 for "1", 0 for anything else
    bool half_tried = false; ///< HalfReady made its attempt
    bool half_made = false;  ///< the half pipelines and counters exist
    bool HalfReady();
    bool half_cleared = false;
    u64 half_recorded = 0;
    u32 half_frames = 0;
    Pass probe_reflect_half, probe_resolve_half;
    HalfBuffer half_counts, half_readback;
    std::array<u32, HalfSlots> half_last{};
    OwnImage geo;
    std::array<OwnImage, 2> light;
    std::array<OwnImage, 2> filtered;
    std::array<OwnImage, 2> probe_geo;
    std::array<OwnImage, 2> probe_light;
    std::array<std::array<OwnImage, 3>, 2> probe_sh;
    std::array<OwnImage, 2> probe_diffuse;
    std::array<OwnImage, 2> probe_specular;
    OwnImage probe_ray;
    OwnImage probe_ray_dist;
    std::array<OwnImage, 2> probe_reflection;
    bool probe_history_valid = false;
    bool reflection_history_valid = false;
    std::array<float, 12> prev_view{};
    std::array<float, 2> prev_proj{};
    std::array<float, 2> prev_jitter{};
    bool prev_camera_valid = false;
    u32 frame = 0;
    bool done_this_frame = false;
    bool probes_ran = false;
    bool rays_ran = false;
    u32 probe_idle_frames = 0;
    u32 ray_idle_frames = 0;
    bool history_valid = false;
    bool failed = false;
    bool tried = false;
    VideoCore::ImageId gbuffer_depth, gbuffer_albedo, gbuffer_normal;
    VideoCore::ImageId gbuffer_material, gbuffer_specular;
    VideoCore::ImageId ao_image;
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
};

}
