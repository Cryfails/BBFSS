// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r107_caustics): water caustics from the sun or moon, the moving net of light water
// reflects onto the walls and undersides beside it (caustics_params.h says the knob and the
// rule, host_shaders/caustics.comp the pass).
//
// Off unless BB_CAUSTICS or BB_CAUSTICS_LAMPS (r107b) names a strength above 0 or "show"
// (environment, read once). Off, the
// rasterizer makes no Caustics (Wanted), so there is no pipeline, buffer or pass, and each of its
// hooks is one null pointer test.
//
// Inputs, from the rasterizer's hooks: the G-buffer's material target (gloss, for the test view's
// puddle candidates), its albedo and specular targets (r107b: the lamps' light, the light sets)
// at each G-buffer pass; the lamps of the game's light grid (r107b) at its lamp draws; the light
// sets' table at the game's directional light draw (r107b); the game's screen shadow target and the direction
// toward the sun or moon at each shadow resolve (the volumetric light's SunLight); the water
// plane from CameraMotion::MirrorPlane; the scene colour and depth at the first blended draw after
// the opaque scene (Rasterizer::EffectsBlendedScene, which runs only with the upscaler on).
#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/lamp_fog_lights.h" // bbport (r107b_caustics-visible)
#include "video_core/renderer_vulkan/caustics_params.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first (as vk_halation.h)
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class PointShadow;
class Runtime;
class SceneTargets;
class Scheduler;

class Caustics {
public:
    /// BB_CAUSTICS gives a strength above 0 or "show" (read once; the first call says the knobs).
    [[nodiscard]] static bool Wanted();
    Caustics(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
             Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
             PointShadow& point_shadow, bool upscaler_on);
    ~Caustics();
    Caustics(const Caustics&) = delete;
    Caustics& operator=(const Caustics&) = delete;

    /// A G-buffer draw: its depth and its material target (cb 1, gloss in .r). It arms the pass:
    /// Apply runs once after each G-buffer pass (at its first blended draw), not at every one; a
    /// draw of a pass Apply already ran for (the same depth in the same frame) does not arm it
    /// again, so a late G-buffer draw cannot apply the pattern twice.
    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId material,
                       VideoCore::ImageId albedo, VideoCore::ImageId records);
    /// bbport (r107b_caustics-visible): a lamp draw of the game's light grid: `count` records of 16
    /// words (lamp_fog_lights.h), kept once each until the next G-buffer pass (BB_CAUSTICS_LAMPS).
    void AddLights(const u32* records, u32 count);
    /// bbport (r107b_caustics-visible): the game's directional light draw: its light sets' table
    /// (`floats` floats, 72 a set; light 0's colour at 16-18 is the sun's) and the guest address of
    /// its texture 0, whose alpha byte names each pixel's set (the G-buffer's specular target).
    void OnLightSets(const float* table, u32 floats, VAddr texture0);
    /// bbport (r107b_caustics-visible): BB_CAUSTICS above 0 (the sun's caustics; the rasterizer
    /// reads the light sets only then), BB_CAUSTICS_LAMPS above 0 (it hands over the lamps only then).
    [[nodiscard]] bool SunWanted() const noexcept { return knobs.strength > 0.0f; }
    [[nodiscard]] bool LampsWanted() const noexcept { return knobs.lamp_strength > 0.0f; }
    /// The game's shadow resolve: its target (the screen shadow target) and the direction toward
    /// the sun or moon in the world (`valid`: known this frame).
    void OnShadowResolve(VideoCore::ImageId target, const std::array<float, 3>& toward, bool valid);
    /// The first blended draw after the opaque scene: the caustics into `color` (the scene colour,
    /// RGBA16F), from `depth` (the scene's). `wind`: m/s in the world (zero without BB_WIND).
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter,
               const std::array<float, 3>& wind);

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

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    PointShadow& point_shadow;

    ::BbCaustics::Knobs knobs;
    ::BbCaustics::Drift drift;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    struct Buffer {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    } counters;
    // bbport (r107f_caustics-world-anchored): the world map (device local; none without
    // BB_CAUSTICS_WORLD), the plane's generation and height it was written for, whether the first
    // dispatch cleared it, the lamps chosen in the last pass that found any.
    Buffer world_map;
    u32 world_gen = 0;
    float world_plane = 0.0f;
    bool world_cleared = false;
    std::array<::BbCaustics::Lamp, ::BbCaustics::MaxLamps> last_lamps{};
    u32 last_lamp_count = 0;
    bool made = false;
    std::array<ViewEntry, 6> view_cache{};
    u64 view_uses = 0;
    std::chrono::steady_clock::time_point last_time = std::chrono::steady_clock::now();

    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{};
    // bbport (r107b_caustics-visible): the G-buffer's albedo and specular targets; the lamps since
    // the last G-buffer draw; the light sets of the last directional draw (bit i of sun_mask: set
    // i has the sun; fresh: a directional draw came since the last Apply that found a plane), the
    // guest address of its texture 0, the sets read, those with sun, the brightest's light 0
    VideoCore::ImageId gbuffer_albedo{}, gbuffer_records{};
    LampFog::FrameLights lamps;
    std::array<u32, 8> sun_mask{};
    bool sets_fresh = false;
    VAddr sets_address = 0;
    u32 sets_count = 0, sets_sunny = 0;
    float sets_best = 0.0f;
    VideoCore::ImageId shadow_target{};
    std::array<float, 3> sun{};
    bool sun_valid = false;
    bool resolved = false; ///< a shadow resolve came since the last Apply that found a plane
    bool armed = false;    ///< a G-buffer draw came since the last Apply
    VideoCore::ImageId applied_depth{}; ///< the depth of the pass Apply last ran for
    u32 applied_frame = 0;              ///< and its frame (BbStats::frame_number)
    u32 dispatches = 0;    ///< the counter slot is dispatches % Slots
    float last_plane = 0.0f, last_sun_y = 0.0f;
    // bbport (r107e_caustics-puddles): each slot's camera y and puddle plane (the counts come back
    // Slots - 1 dispatches late); the puddle plane found (and checked: not a glossy floor); the
    // calls since the last one with a mirrored water pass.
    std::array<float, ::BbCaustics::Slots> slot_camera_y{}, slot_puddle_y{};
    std::array<u32, ::BbCaustics::Slots> slot_puddle{}; ///< 0 none, 1 measured, 2 with a plane
    float puddle_y = 0.0f;
    bool puddle_found = false, puddle_checked = false;
    u32 calls_since_mirror = 0;

    /// For the line after the first 120 calls, then every 600.
    struct Stats {
        u32 calls = 0;     ///< Apply calls (a mirrored frame calls twice: its mirror image too)
        u32 drawn = 0;     ///< dispatches with the caustics (a water plane, the sun and its shadow)
        u32 shown = 0;     ///< test view dispatches with puddle candidates only
        u32 no_plane = 0;  ///< no water plane (no mirrored G-buffer passes): nothing to do
        u32 mirror = 0;    ///< a plane, but this pass's camera is below it (the mirror image)
        u32 no_sun = 0;    ///< a plane, but no sun direction this frame or the sun below MinSunY
        u32 no_shadow = 0; ///< a plane and the sun, but no usable screen shadow target
        u32 no_scene = 0;  ///< the scene colour was not a writable RGBA16F image, or no camera
        u32 lamp_ends = 0; ///< lamps-apart batches this pass ended (it reads the camera depth)
        u32 no_sets = 0;   ///< r107b: the sun skipped: no light sets this frame, or not the G-buffer's
        u32 no_lamps = 0;  ///< r107b: lamps asked, but no lamp of the frame reaches the water
        u32 lamp_draws = 0; ///< r107b: dispatches with the lamps' caustics
        u64 lamps_used = 0; ///< r107b: their lamps, summed
        float colour_top = 0.0f; ///< r107c: the largest colour channel of those lamps
        u32 puddle_measured = 0; ///< r107e: dispatches that counted puddle candidates
        u32 puddle_lamps = 0;    ///< r107e: of them, with lamps over a checked puddle plane
        u32 puddle_none = 0;     ///< r107e: puddle calls without a plane found
        u32 puddle_floor = 0;    ///< r107e: puddle calls whose plane the guard refused (or not yet read)
        u64 puddle_ground = 0, puddle_wet = 0; ///< r107e: the guard's last counts
        u32 world_draws = 0;   ///< r107f: dispatches that used the world map
        u32 world_changes = 0; ///< r107f: new plane generations (the map starts again)
        std::array<u64, ::BbCaustics::SlotWords> pixels{}; ///< the shader's counts, read back late
        u32 read = 0;      ///< dispatches whose counts were read
    } stats;
    bool reported = false;
    bool told_first = false;
};

} // namespace Vulkan
