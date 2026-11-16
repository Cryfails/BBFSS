// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>

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

class ContactShadow {
public:
    ContactShadow(const Instance& instance, Scheduler& scheduler,
                  VideoCore::TextureCache& texture_cache, Runtime& runtime,
                  SceneTargets& scene_targets, CameraMotion& camera_motion, RtShadow& rt_shadow);
    ~ContactShadow();

    struct Inputs {
        vk::Buffer constants;
        vk::DeviceSize constants_offset = 0;
        vk::DeviceSize constants_range = 0;
        vk::Buffer uniforms;
        vk::DeviceSize uniforms_offset = 0;
        vk::DeviceSize uniforms_range = 0;
        vk::ImageView shadow_map;
        vk::ImageLayout shadow_layout = vk::ImageLayout::eUndefined;
        u32 constants_offset_word = 0;
        u32 frame_index = 0;
        /// Copy of the resolve's first 28 constant floats (inverse projection, cascade 0), taken
        /// at draw time; Bend's dispatch layout is built from them on the CPU.
        std::array<float, 28> constants_cpu{};
        bool has_constants_cpu = false;
    };

    void OnShadowDraw(VideoCore::ImageId target, const Inputs& inputs);
    void OnBlurDraw(VideoCore::ImageId target, VAddr source);

    void Flush(bool native_blur = false);

    /// bbport: whether the ray traced sun or the VSM replaced the game's sun shadow (its filter
    /// wrote the shadow target's alpha) since the last call.
    bool TakeSunReplaced() noexcept {
        const bool replaced = sun_replaced;
        sun_replaced = false;
        return replaced;
    }

private:
    bool Ready();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::UniqueSampler sampler;
    VideoCore::ImageId pending;
    Inputs pending_inputs;
    bool use_contact = false;
    bool use_pcss = false;
    bool use_filter = false;
    bool use_rt = false;
    bool sun_replaced = false;
    float surface_thickness = 0.005f;
    float bilinear_threshold = 0.02f;
    float strength = 0.75f;
    float shadow_contrast = 2.0f;
    // Bend shadows fade out with the game's sun-shadow distance fade, stretched this many times
    // further than the shadow map (1.5 was the accepted Elden Ring setting).
    float bend_distance_scale = 1.5f;
    float flip = 1.0f;
    u32 debug = 0;
    float light_tan = 0.02f;
    float max_penumbra_m = 0.3f;
    float min_penumbra_m = 0.0f;
    float bias_m = 0.04f;
    bool tried = false;
    bool failed = false;
};

}
