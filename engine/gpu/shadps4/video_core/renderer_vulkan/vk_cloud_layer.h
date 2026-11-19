// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): FEATURE. A layer of ray marched clouds in front of the painted
// sky dome (BB_VOLUMETRIC_CLOUDS=1; cloud_layer_params.h has the knobs, the slab and the rules,
// host_shaders/cloud_layer.comp the two passes).
//
// What it is: the game paints its sky as one dome with a painted panorama (r104 probe: no time input,
// no cloud layer), so this adds a layer of real clouds between that dome and the world: a slab of
// air (by default 700 to 1000 m above the world's y = 0) marched along the view ray of every sky
// pixel, lit by the sun or moon direction the engine already finds for the sun shadows
// (VolumetricOcclusion::MakeSunLight), tinted by the painted sky behind the pixel, drifting with the
// cloud shadows' own clock. The density is the cloud shadows' field (r105b): the same noise, the
// same offsets, size, edges and direction, so a shadow sweeping the ground belongs to a cloud
// overhead (cloud_layer_params.h says how the two planes line up).
//
// Where in the frame: Rasterizer::EffectsBeforeUpscaler, at the upscaler's trigger dispatch, on the
// scene colour (RGBA16F, linear light before the game's exposure and tone curve) and the scene's
// depth (D32, 1 = far), after the sky dome and the opaque world and the drawn look, before the
// volumetric fog composite (so the fog and its haze lie over the clouds), the tonemap and the
// upscaler; the HUD is drawn later and never touched. Reads: the scene colour (the sky pixels'
// tint), the depth. Writes: the scene colour of the sky pixels only (a pixel that is not sky,
// depth below 1 and nearer than BB_VOLUMETRIC_CLOUDS_SKYZ metres (500) is never written: the game's sky
// dome is drawn a little short of depth 1).
//
// The passes: MARCH at 1 / CL_DIV of the scene a side (RGBA16F image, premultiplied colour and
// opacity; a pixel with no sky under it is marked), COMPOSITE at the scene's size (a bilinear
// filter over the march pixels that have sky under them, so no colour leaks across a silhouette).
// The march jitter is interleaved gradient noise that changes each frame: the upscaler averages
// it; there is no history of its own. Without the upscaler (BB_UPSCALER=none, or a GPU it cannot
// run on) that place is never reached and nothing is drawn (said after 300 frames).
//
// Off unless BB_VOLUMETRIC_CLOUDS starts with 1 (environment, read at the start; with the test tools'
// live knobs file (gpu/shim/bbport_live_knobs.h) it can be switched off and on again while the game
// runs, for an exact twin in one game; a layer not made at the start cannot be switched on). Off, the rasterizer
// makes no CloudLayer (Wanted), so there is no pipeline, no image, no buffer and no pass, and each
// of its three hooks is one null pointer test. On: two pipelines and three small buffers at the
// start; the march image (8 bytes a march pixel: 4.1 MB at a 1920x1080 scene) at the first frame
// that draws, and again when the scene's size changes.
//
// The clock: while the cloud shadows are on (BB_CLOUD_SHADOWS above 0, or SHOW) the layer reads
// THEIR knobs and state (CloudShadow::ClockKnobs / ClockState) so offsets, heading and speed are the
// same objects; else it keeps a clock of its own made from the same variables (BB_CLOUD_SHADOWS_SCALE,
// BB_CLOUDS_DIR, BB_WIND_DIR, BB_WIND_SPEED, and the wind's direction with BB_WIND=1).
//
// bbport (r119c_clouds-gaps): the layer now reads the noise at its own size (BB_VOLUMETRIC_CLOUDS_SIZE, 800 m)
// with its own edges and its own drift (layer_drift, advanced at that heading and speed times
// BB_VOLUMETRIC_CLOUDS_SPEED), so it is no longer the cloud shadows' field and its clouds and the ground
// shadows no longer line up one for one; the heading and speed are still the one wind's.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/cloud_layer_params.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class CloudShadow;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class CloudLayer {
public:
    /// BB_VOLUMETRIC_CLOUDS starts with 1 (read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    CloudLayer(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~CloudLayer();
    CloudLayer(const CloudLayer&) = delete;
    CloudLayer& operator=(const CloudLayer&) = delete;

    /// At each sun shadow resolve: the direction toward the light (world) and whether it is known.
    /// An unknown light leaves the last known one (the layer has no light of its own before one).
    void SetSunLight(const std::array<float, 3>& world, bool valid);
    /// Each frame end: the clock (when the cloud shadows are off), the counters and the log.
    void OnFrameEnd(bool wind_on, float wind_deg);
    /// The upscaler's trigger: the clouds into the sky pixels of `color` (the scene colour), `depth`
    /// the scene's depth, `jitter` the viewport's shift this frame (pixels).
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
    /// The heading (deg) and speed (m/s) the clouds move at now.
    [[nodiscard]] float Direction() const;
    [[nodiscard]] float Velocity() const;
    /// The layer keeps a clock of its own (the cloud shadows are off).
    [[nodiscard]] bool OwnClock() const {
        return shared == nullptr;
    }

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
    bool EnsureImage(u32 width, u32 height);
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    [[nodiscard]] const CloudShadows::State& ClockState() const;
    [[nodiscard]] const CloudShadows::Knobs& ClockKnobs() const;
    void Report();
    /// The knob now (a live knob with the test tools' header, else read once); says each change once.
    bool Active();
    /// bbport (r119e_clouds-real-sky): the speed and the contrast now (live knobs); says each change once.
    void ReadLive();
    /// bbport (r119h_clouds-freeze-sheet): says the sheet mark's line (the frames summed since the mark changed).
    void ReportMark(u32 mark);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    const CloudLayerParams::Knobs knobs;
    CloudLayerParams::Knobs live; ///< bbport (r119e): the knobs with the speed and the contrast as they are now (live knobs)
    CloudShadow* shared = nullptr;         ///< the cloud shadows' object when they are on
    CloudShadows::State own_state;         ///< the layer's clock when they are off
    VolumetricFogNoise::Drift layer_drift; ///< (r119c) the layer's own cloud offsets, in cells of its size
    double clock_last = -1.0;              ///< s (steady clock) at the last own step; below 0: none
    bool made = false;
    vk::UniqueDescriptorSetLayout march_set_layout, composite_set_layout;
    vk::UniquePipelineLayout march_layout, composite_layout;
    vk::UniquePipeline march_pipeline, composite_pipeline;
    VideoCore::UniqueImage cloud_image;
    vk::UniqueImageView cloud_view;
    u32 cloud_width = 0, cloud_height = 0;
    u32 refused_width = 0, refused_height = 0; ///< a march size the image found no room at
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    Buffer params_buffer, counter_buffer, counter_host;

    std::array<float, 3> light{};
    std::array<float, 2> slope{};
    bool light_known = false;
    u32 frame_index = 0;
    bool drew_this_frame = false;
    bool told_size = false;
    bool told_no_place = false;
    bool reported_once = false; ///< bbport (r119d): the first log line comes after FramesFirst frames
    bool told_on = true; ///< what the live knob said last (the constructor's line says on)
    float told_speed = -1.0f, told_contrast = -1.0f; ///< bbport (r119e): the live speed and contrast said last (below 0: none yet)
    float told_cover = -1.0f, told_tint = -1.0f;     ///< bbport (r119g): the live cover and tint said last (below 0: none yet)
    std::array<float, 3> told_paint{-1.0f, -1.0f, -1.0f}; ///< bbport (r119i): the live painted fade, horizon and glow cap said last (below 0: none yet)
    int told_soften = -1;                            ///< bbport (r119j): the live banding fix bits said last (-1: none yet)
    int told_smear = -1;                             ///< bbport (r119g): the live smear fix said last (-1: none yet)
    bool frozen = false, told_frozen = false;        ///< bbport (r119h): BB_VOLUMETRIC_CLOUDS_FREEZE now and said last
    u32 mark_told = 0, mark_skip = 0, mark_left = 0, mark_age = 0; ///< bbport (r119h): BB_VOLUMETRIC_CLOUDS_MARK said last, frames to skip / to sum, frame ends since
    CloudLayerParams::Totals mark_totals;            ///< bbport (r119h): the counters of the frames of the mark

    CloudLayerParams::Totals totals;
    /// The log period's frame counts.
    struct Stats {
        u32 frames = 0;     ///< frame ends
        u32 reached = 0;    ///< frames that reached the place before the upscaler
        u32 drawn = 0;      ///< frames with the passes recorded
        u32 smoothed = 0;   ///< bbport (r119j): of them, with any banding fix bit on (BB_VOLUMETRIC_CLOUDS_SMOOTH not 0)
        u32 no_camera = 0;  ///< reached, but no camera or a menu's preview
        u32 no_scene = 0;   ///< reached, but the scene colour or depth was not usable
        u32 no_memory = 0;  ///< reached, but no room for the march image
        float camera_y = 0.0f;
    } stats;
};

} // namespace Vulkan
