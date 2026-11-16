// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): the wind shelter field's GPU passes (bbport_wind_shelter.h says what
// the field is and who reads it; host_shaders/wind_shelter.comp what the passes do). FEATURE, off
// unless BB_WIND=1 and BB_WIND_SHELTER is above 0 (and the plant sway's region exists). Off, the
// rasterizer makes no WindShelter (Wanted), so there is no pipeline, no buffer and no pass, and
// each of its two hooks is one null pointer test.
//
// The passes run right before the upscaler's trigger (Rasterizer::EffectsBeforeUpscaler, after the
// heat haze), when the scene depth is complete: five small dispatches (the depth's splat at one
// pixel in four, the merge into the cache, the rays, the blur and the field's write into the sway
// region's buffer), and with BB_WIND_SHELTER_SHOW the test view. Without the upscaler (BB_UPSCALER=
// none or a GPU it cannot run on) that place is never reached and nothing is drawn (said once).
#pragma once

#include <array>
#include <chrono>

#include "bbport_wind.h"
#include "bbport_wind_shelter.h"
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h> // after vk_common.h (its configuration)
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

class WindShelter {
public:
    /// BB_WIND=1 with BB_WIND_SHELTER above 0 and the plant sway on (read once).
    [[nodiscard]] static bool Wanted();
    WindShelter(const Instance& instance, Scheduler& scheduler,
                VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~WindShelter();
    WindShelter(const WindShelter&) = delete;
    WindShelter& operator=(const WindShelter&) = delete;

    /// The place before the upscaler is never reached: said once.
    void NoSceneHooks();
    /// Right before the upscaler's trigger: this frame's passes. `region`: the device address of the
    /// sway region's first word (ObjectMotion::AddressTable().params + ParamsCapacity * 32; 0: none,
    /// nothing is made), `wind` the shared wind as last advanced.
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               u64 region, const BbWind::Snapshot& wind);
    /// The share of the wind that stays at the camera (BbWindShelter::Open of the field there, as
    /// the GPU wrote it a frame or two ago): 1 before any pass has run.
    [[nodiscard]] float CameraOpen() const;
    /// bbport (r115b, r115c_roof-rule-not-trees): the camera's ROOF share 0-1 (wind_shelter.comp: climbing
    /// view rays that end within WS_ROOF_DIST on a solid surface, the smallest share of the 4 quadrants;
    /// as the GPU wrote it a frame or two ago; only made while BB_VOLUMETRIC_ROOF=1); -1 before any pass.
    [[nodiscard]] float CameraCover() const;

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    void Report();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    BbWindShelter::Knob knobs;
    vk::UniqueDescriptorSetLayout set_layout, show_set_layout;
    vk::UniquePipelineLayout layout, show_layout;
    vk::UniquePipeline pipeline, show_pipeline;
    bool made = false;
    bool show_made = false;
    Buffer state_buffer, counter_buffer, counter_host;
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    u32 frame = 0;                ///< the passes run so far (the push's frame, never 0 once run)
    bool zeroed = false;          ///< the state and counters were cleared (the first pass)
    std::chrono::steady_clock::time_point last_pass{};
    std::array<u32, WS_COUNTER_WORDS> counters_seen{}; ///< as the last line read them

    struct Stats {
        u32 frames = 0;     ///< frames that reached the place before the upscaler
        u32 passes = 0;     ///< of them with the passes recorded
        u32 no_region = 0;  ///< frames without the sway region or with the wind off
        u32 no_camera = 0;  ///< frames without a camera, or a menu's preview
        u32 no_scene = 0;   ///< frames whose scene could not be read or was too small
    } stats;
    bool reported = false;
    bool told_size = false;
};

} // namespace Vulkan
