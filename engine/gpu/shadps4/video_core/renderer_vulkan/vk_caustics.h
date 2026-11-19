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
#include <memory>
#include <string>

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
class Rasterizer;
class Runtime;
class SceneTargets;
class Scheduler;
namespace SewerMotion { struct Series; }

class Caustics {
public:
    /// BB_CAUSTICS gives a strength above 0 or "show" (read once; the first call says the knobs).
    [[nodiscard]] static bool Wanted();
    /// bbport (r128b_lrt-caustics-water): Wanted reads the strengths in force at each call (the
    /// variable where set and not empty, else the lantern.ini setting), so the rasterizer makes the
    /// object at the first frame one is above 0. Refresh takes the two strengths again (once a
    /// frame); StrengthLine says them (first frame, after a change, at most once every 600).
    static void StrengthLine();
    void Refresh();
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
               const std::array<float, 3>& wind, Rasterizer* sewer_witness = nullptr);

    bool SewerReducedArmed(bool ground);
    void RefuseReducedBedDraw(bool product, const char* reason);
    void SewerReducedDraw(bool ground, bool product, u64 scene,
                          VideoCore::ImageId depth, vk::ImageView depth_view,
                          VideoCore::ImageId cb2, vk::ImageView cb2_view, std::array<float, 2> jitter);
    bool SewerReducedBeforeCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                                VideoCore::ImageId destination, const VideoCore::Image& dst,
                                u64 bytes, std::array<float, 2> jitter);
    void SewerReducedFallbackCopy(VideoCore::ImageId source);
    void SewerReducedAfterCopy(VideoCore::ImageId source, VideoCore::ImageId destination,
                               const VideoCore::Image& dst, vk::ImageView sampled, vk::ImageView written);

    [[nodiscard]] bool NativeBedWanted() const noexcept {
        return native_bed_enabled && made && knobs.world > 0.0f && LampsWanted() && world_map.buffer;
    }
    void ResetNativeBedPass();

    // t200 reuses the accepted t180 pre-ground request. No trace is active on ordinary frames.
    void StartNativeBedTrace(u64 frame, u64 scene, u32 pass, VideoCore::ImageId depth);
    [[nodiscard]] bool TracingNativeBed(VideoCore::ImageId depth) const noexcept {
        return bed_trace.active && bed_trace.depth == depth;
    }
    bool NativeBedTraceGate(bool accepted, const char* path, const char* predicate) const;
    [[nodiscard]] bool TraceNativeBedWanted(const char* path) const;
    bool ClaimNativeBedDrawTrace(bool ground) noexcept;
    [[nodiscard]] bool TracingJoinedBed(VideoCore::ImageId depth) const noexcept {
        return bed_trace.joined_enabled && TracingNativeBed(depth);
    }
    bool ClaimJoinedBedCopy(VideoCore::ImageId depth) noexcept {
        if (!TracingJoinedBed(depth) || bed_trace.joined_copy) return false;
        bed_trace.joined_copy = true;
        return true;
    }
    std::string JoinedBedStamp() const;
    std::string JoinedBedState() const;
    void NoteNativeBedGround(VideoCore::ImageId depth, VideoCore::ImageId albedo,
                             vk::Extent2D extent, std::array<float, 2> jitter);
    [[nodiscard]] bool WantsNativeBedCopy(VideoCore::ImageId source) const;
    void NoteNativeBedCopy(VideoCore::ImageId source_id, const VideoCore::Image& source,
                           VideoCore::ImageId dest_id, const VideoCore::Image& dest, u64 bytes,
                           u64 previous_write, std::array<float, 2> jitter);
    [[nodiscard]] bool AwaitsNativeBedWater() const noexcept {
        return native_bed.stage == NativeBedStage::Ground || native_bed.stage == NativeBedStage::Copy;
    }
    void NoteNativeBedWater(VideoCore::ImageId depth, vk::Extent2D extent,
                            std::array<float, 2> jitter);

private:
    struct SewerReducedReceipt;
    bool sewer_reduced_master{}, sewer_reduced_claimed{};
    std::shared_ptr<SewerReducedReceipt> sewer_reduced;
    std::unique_ptr<SewerMotion::Series> sewer_motion;
    void RefreshSewerMotion();
    void SewerReducedRefused(const char* reason);
    bool SewerReducedConsume(VideoCore::ImageId color, vk::ImageView color_view, vk::Image color_image,
                             VideoCore::ImageId depth, vk::ImageView depth_view, vk::Image depth_image,
                             VideoCore::ImageId cb2, vk::ImageView cb2_view, vk::Image cb2_image,
                             const ::BbCaustics::Push& push, vk::ImageView bed_view, bool observe_bed);
    enum class NativeBedStage { Empty, Ground, Copy, Water, Closed, CopyPending };
    struct NativeBedImage {
        VideoCore::ImageId id{};
        u64 uid = 0;
        vk::Image handle{};
        const VideoCore::Image::BackingImage* backing = nullptr;
        VAddr begin = 0, end = 0;

        static NativeBedImage Of(VideoCore::ImageId id, const VideoCore::Image& image);
        bool operator==(const NativeBedImage&) const = default;
    };
    struct NativeBedPass {
        NativeBedStage stage = NativeBedStage::Empty;
        bool reduced = false;
        u64 serial = 0, frame = 0, loading = 0, generation = 0;
        NativeBedImage depth, albedo, copy;
        u64 copy_write = 0, copied_source_write = 0, water_write = 0, copy_bytes = 0;
        vk::Extent2D extent{}, copy_extent{};
        u64 scene = 0;
        vk::Image depth_proxy{}, albedo_proxy{};
        vk::ImageView ground_view{}, ground_albedo_view{};
        std::array<float, 4> proj{};
        std::array<float, 12> view{}, inv_view{};
        std::array<float, 2> jitter{};

        void Ground();
        void Copied();
        void Water();
    };
    NativeBedPass native_bed;
    const char* reduced_bed_refusal = nullptr;
    void CloseReducedBed(const char* reason);
    void TrackReducedBedCopy(VideoCore::ImageId source, const VideoCore::Image& src,
                             VideoCore::ImageId destination, const VideoCore::Image& dst,
                             u64 bytes, std::array<float, 2> jitter);
    u64 native_bed_pass_serial = 0;
    bool native_bed_enabled = false;
    struct BedTrace {
        bool active = false, used = false, draw_ground = false, draw_water = false;
        u64 frame = 0, scene = 0;
        u32 pass = 0, rows = 0;
        VideoCore::ImageId depth{};
        const char* first_path = nullptr;
        const char* first_failure = nullptr;
        bool first_reset = false, joined_enabled = false, joined_copy = false;
    };
    mutable BedTrace bed_trace;
    void NativeBedTraceEvent(const char* event, const char* path, const char* detail) const;
    void NativeBedTraceClose(const char* path, const char* detail) const;
    void FinishNativeBedTrace(bool joined, VideoCore::ImageId depth, NativeBedStage returned);
    [[nodiscard]] bool CurrentNativeBed(const NativeBedPass& pass, const char* trace = nullptr) const;
    [[nodiscard]] bool NativeBedCamera(const NativeBedPass& pass, std::array<float, 2> jitter,
                                       const char* trace = nullptr) const;
    [[nodiscard]] bool NativeBedImageFits(const VideoCore::Image* image, vk::Extent2D extent,
                                          const char* trace = nullptr) const;
    NativeBedPass TakeNativeBed();
    struct JoinedBedBind;
    vk::ImageView BindNativeBed(const NativeBedPass& pass, VideoCore::ImageId color_id,
                                const VideoCore::Image& color, VideoCore::ImageId depth_id,
                                const VideoCore::Image& depth, const VideoCore::Image* albedo,
                                vk::ImageView depth_view, vk::ImageView albedo_view,
                                vk::Extent2D extent, std::array<float, 2> jitter, float plane, JoinedBedBind* joined);
    struct ReducedBedTargets;
    vk::ImageView BindReducedBed(const NativeBedPass& pass, VideoCore::ImageId color_id,
                                 const VideoCore::Image& color, VideoCore::ImageId depth_id,
                                 const VideoCore::Image& depth, const VideoCore::Image* albedo,
                                 const ReducedBedTargets& targets, vk::Extent2D extent,
                                 std::array<float, 2> jitter, float plane);
    vk::ImageView BindBedCopy(const NativeBedPass& pass, VideoCore::ImageId color_id,
                             const VideoCore::Image& color, VideoCore::ImageId depth_id,
                             const VideoCore::Image& depth, const VideoCore::Image& albedo,
                             const ReducedBedTargets* targets, JoinedBedBind* joined);

    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    void Report();
    class WetnessProbe;
    std::unique_ptr<WetnessProbe> wetness_probe;
    class BedObserver;
    std::unique_ptr<BedObserver> bed_observer;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    PointShadow& point_shadow;

    ::BbCaustics::Knobs knobs;
    ::BbCaustics::Drift drift;
    // bbport (r130b_water-moves): the moving water: its state, the strength in force (0: nothing runs) and where it came from
    ::BbCaustics::Motion::State motion;
    ::BbCaustics::Motion::Ambient ambient;
    std::array<bool, ::BbCaustics::Slots> slot_ambient_warp{};
    float motion_strength = 0.0f;
    bool motion_env = false;
    // bbport (r130e_sewer-water-moves): the copy of the water's colours (RGBA16F, the scene's size; made at the first warp, remade
    // on a size change), whether the copy's contents were cleared, the world map's maker, the bed light's lines
    struct WarpImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
        u32 width = 0, height = 0;
        bool cleared = false;
    } warp;
    bool world_env_set = false; ///< r130e: BB_CAUSTICS_WORLD is set and not empty (it decides the bed light, also 0)
    bool world_tried = false;   ///< r130e: the world map was tried (once)
    bool EnsureWarpImage(u32 width, u32 height);
    bool MakeWorldMap();
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
    std::array<ViewEntry, 7> view_cache{};
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
        u32 motion_dispatches = 0, steps = 0, landings = 0; ///< r130b: dispatches with the motion, the hunter's steps and landings
        u64 ring_px = 0;                                    ///< r130b: the water pixels the rings reached, summed
        bool hunter_read = false;                           ///< r130b: the last frame's position read worked
        u32 warp_dispatches = 0, motion_only = 0, warp_reads = 0; ///< r130e: warp dispatches, those alone, those whose counts were read
        u64 warp_px = 0, warp_kept = 0;                           ///< r130e: the water pixels warped and those kept, summed over the reads
        u64 warp_rows = 0, warp_height = 0;                       ///< r130e: the band's rows and the frames' rows, summed
        std::array<u64, ::BbCaustics::SlotWords> pixels{}; ///< the shader's counts, read back late
        u32 read = 0;      ///< dispatches whose counts were read
    } stats;
    bool reported = false;
    bool told_first = false;
    bool told_motion = false; ///< r130b: the first moving dispatch was said
    u32 motion_changes = 0;   ///< r130b: Refresh found another strength
    bool told_warp = false, told_bed = false, warp_failed = false; ///< r130e: the first warp, the bed light and a failed copy were said
    std::chrono::steady_clock::time_point warp_retry_at{}; // r132b: copy-image retry deadline
    u32 strength_changes = 0; ///< r128b: Refresh found another strength (setting moved)
    u32 idle_passes = 0;      ///< r128b: Apply calls skipped with both strengths 0
};

} // namespace Vulkan
