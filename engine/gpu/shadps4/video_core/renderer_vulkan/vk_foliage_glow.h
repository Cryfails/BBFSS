// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the back-lit glow of leaves and grass (host_shaders/foliage_glow.comp) and the knobs of the foliage
// translucency as a whole (foliage_translucency.h has the rules and the pure parts; the functions it declares are made in vk_foliage_glow.cpp).
//
// Off (graphics_foliage_translucency 0 and no BB_FOLIAGE_TRANSLUCENCY, or the glow not asked, or no BB_RT_CARD_ALPHA=2 with BB_RT_CARD_LAMPS=1): the
// rasterizer makes no FoliageGlow (Wanted), so there is no pipeline, buffer or pass, and each of its hooks is one null pointer test.
//
// Inputs, from the rasterizer's hooks (vk_rasterizer_effects.cpp), as the water caustics takes them (vk_caustics.h):
//  - EffectsAfterTargets, at a G-buffer draw (OnGBufferDraw): the depth, the world normal (cb 0) and the albedo (cb 2) of the pass; the lamps
//    gathered so far are another pass's.
//  - EffectsBeforeBind, at a lamp draw of the light grid (AddLights): its records, as drawn (up to FG_MAX_LAMPS, the nearest kept).
//  - The game's shadow resolve (OnSun): the direction toward the sun or moon in the world; its directional light draw (OnLightSets): the light
//    sets' table, of which the brightest set's light 0 is the sun's colour.
//  - EffectsBlendedScene, right after the caustics (Apply): the glow, once after each G-buffer pass's opaque lighting.
// The pass reads the ray traced scene's cut-out cards (RtShadow::CardLampReadersNow: needs BB_RT_CARD_LAMPS=1) and, with the light through leaves on,
// the sun trace's hue image (RtShadow::SunHueNow) and the colour layers.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/foliage_translucency.h"
#include "video_core/renderer_vulkan/lamp_fog_lights.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class PointShadow;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

class FoliageGlow {
public:
    /// The glow is wanted (FoliageTranslucency::Glow: read once, the first call says the knobs).
    [[nodiscard]] static bool Wanted();
    FoliageGlow(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion, PointShadow& point_shadow, RtShadow& rt_shadow);
    ~FoliageGlow();
    FoliageGlow(const FoliageGlow&) = delete;
    FoliageGlow& operator=(const FoliageGlow&) = delete;

    /// A G-buffer draw: its depth, world normal and albedo; the lamps gathered so far are another pass's. Arms the pass.
    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo);
    /// A lamp draw of the game's light grid: `count` records of 16 words (lamp_fog_lights.h), kept once each until the next G-buffer pass.
    void AddLights(const u32* records, u32 count);
    /// The game's shadow resolve: the direction toward the sun or moon in the world (`valid`: known this frame).
    void OnSun(const std::array<float, 3>& toward, bool valid);
    /// The game's directional light draw: its light sets' table (`floats` floats, 72 a set; light 0's colour at 16-18): the brightest set's colour is
    /// the sun's.
    void OnLightSets(const float* table, u32 floats);
    /// The first blended draw after the opaque scene: the glow into `color` (the scene colour, RGBA16F) from `depth`.
    // The ordered renderer supplies only a matching production mask view, in GENERAL.
    // Diagnostic views are consumed by the overlay and are never forwarded here.
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               vk::ImageView receiver_mask, vk::ImageView diagnostic_mask,
               vk::Extent2D mask_extent);
    /// Every frame end; every LineFrames frames the log line.
    void OnFrameEnd();

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    void Report();

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    PointShadow& point_shadow;
    RtShadow& rt_shadow;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    struct Buffer {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    } data; ///< host coherent: the counters, then a data block a dispatch (foliage_glow_layout.h)
    bool made = false;
    bool mask_mode = false;
    bool mask_shader = false;
    std::array<ViewEntry, 6> view_cache{};
    u64 view_uses = 0;

    VideoCore::ImageId gbuffer_depth{}, gbuffer_normal{}, gbuffer_albedo{};
    LampFog::FrameLights lamps;
    std::array<float, 3> sun_world{};
    bool sun_valid = false;
    std::array<float, 3> sun_colour{};
    bool sun_colour_valid = false;
    bool armed = false;
    VideoCore::ImageId applied_depth{};
    u32 applied_frame = 0;
    u32 dispatches = 0; ///< the data block is dispatches % FG_SLOTS
    u32 frames = 0;
    bool told_first = false;

    struct Stats {
        u32 calls = 0, passes = 0;
        u32 switched_off = 0, no_scene = 0, no_gbuffer = 0, no_cards = 0, no_light = 0, no_hue = 0;
        u64 lamps = 0;
    } stats;
    std::array<u32, 8> last{}; ///< the counters at the last line
};

} // namespace Vulkan
