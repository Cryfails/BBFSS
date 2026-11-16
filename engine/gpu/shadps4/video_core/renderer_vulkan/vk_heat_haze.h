// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): a shimmer of rising warm air above flames (torches, candles, lanterns,
// bonfires), where the game draws none. The game's own pictures move no pixel of the scene behind
// a flame: in the surface probe (r64) of eight places, the draws that read the scene colour back
// are full-screen composites only, and its fire sprites read their texture and the depth, no copy
// of the scene. So this adds the haze and doubles nothing.
//
// Off unless BB_HEAT_HAZE is a strength above 0 (environment, read once, heat_haze.h Parse). Off,
// the rasterizer makes no HeatHaze (Wanted), so there is no pipeline, no image and no pass, and
// each of its three hooks is one null pointer test.
//
// The lamps: the light lists of the game's lamp pass (Rasterizer::EffectsBeforeBind, the tile
// lights, as the ray traced lamp pass takes them); a G-buffer pass starts the list anew, so the
// last pass's (the scene's, not a reflection's) are kept; a warm colour marks a flame (IsFlame).
// The pass: right before the upscaler's trigger (Rasterizer::EffectsBeforeUpscaler, after the
// fog composite), on the scene colour at the render size: the upscaler (DLSS, FSR, XeSS, TAA)
// then takes the shimmer as it takes the game's fire, and the HUD, drawn after the upscaler, is
// never moved. Without the upscaler (BB_UPSCALER=none or a GPU it cannot run on) that place is
// never reached and the haze is not drawn (said once).
#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/heat_haze.h"
#include "video_core/renderer_vulkan/heat_haze_flames.h" // bbport (r97f_haze-per-flame)
#include "video_core/renderer_vulkan/strength_knob.h" // bbport (r97e_heat-haze-option)
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h> // bbport (r97b_heat-haze-paths): after vk_common.h (its configuration)
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

class HeatHaze {
public:
    /// The strength is above 0 (r97e: Strength(), this frame's; the first call says the knobs' state).
    [[nodiscard]] static bool Wanted();
    /// (r97e) The strength of the frame, read every frame: BB_HEAT_HAZE when it is set and not empty
    /// (read once), else the setting graphics_heat_haze_strength (default 0: off).
    [[nodiscard]] static StrengthKnob::Value Strength();
    /// (r97e) The strength's line, once a frame at the upscaler's trigger: printed at the first
    /// call, then after a change, at most once every 600 calls.
    static void StrengthLine();
    /// (r97e) At the trigger each frame: whether the lamps of this frame are gathered (the
    /// strength is above 0); at 0 AddLights returns at once.
    void Gather(bool on) {
        gathering = on;
    }
    HeatHaze(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
             Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~HeatHaze();
    HeatHaze(const HeatHaze&) = delete;
    HeatHaze& operator=(const HeatHaze&) = delete;

    /// The place before the upscaler is never reached: said once.
    void NoSceneHooks();
    /// A G-buffer pass begins: the lamps gathered so far were another view's.
    void ClearLights() {
        collector.Clear();
    }
    /// One tile's light list of the lamp pass (`count` records of 16 words).
    void AddLights(const u32* records, u32 count) {
        if (gathering) { // bbport (r97e_heat-haze-option)
            collector.Add(records, count);
        }
    }
    /// Right before the upscaler's trigger: the columns of this frame's flames into `color`
    /// (the scene colour), depth tested against `depth` (the scene's). `wind`: m/s in the world
    /// (zero without BB_WIND).
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
    bool EnsureAtlas(u32 width, u32 height);
    void Report();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    ::BbHeatHaze::Knobs knobs;
    bool gathering = true; ///< (r97e) Gather(): false while the strength is 0
    ::BbHeatHaze::Collector collector;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    bool made = false;
    VideoCore::UniqueImage atlas_image;
    vk::UniqueImageView atlas_view;
    u32 atlas_width = 0, atlas_height = 0;
    u32 refused_width = 0, refused_height = 0; ///< a scene size the atlas found no room at
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    // bbport (r97b_heat-haze-paths): the haze pass's pixel counters (heat_haze_layout.h): 32-bit
    // totals in device memory, copied into the host buffer after each frame's haze passes; the log
    // reads the host copy (a frame or two old, as the GPU left it) and prints the differences.
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    void ReportPixels();
    Buffer counter_buffer, counter_host;
    bool counters_zeroed = false; ///< the first drawing frame's pass filled them with zeros
    std::array<u32, ::BbHeatHaze::CounterWords> counters_seen{}; ///< as the last line read them

    /// For the line after the first 120 frames that reached the upscaler, then every 600.
    struct Stats {
        u32 frames = 0;      ///< frames that reached the place before the upscaler
        u32 lit = 0;         ///< of them with at least one column drawn
        u64 columns = 0;     ///< columns drawn
        u64 flames = 0;      ///< flames kept (distinct, in front, nearer than FadeEnd), a frame
        u64 records = 0;     ///< light records seen
        u64 others = 0;      ///< records not of a flame
        u64 beyond = 0;      ///< flame records behind the camera or beyond FadeEnd
        u64 dropped = 0;     ///< flame records over BbHeatHaze::MaxLamps
        u64 unseen = 0;      ///< kept flames without a column (off screen, too short or small)
        u64 over = 0;        ///< columns beyond BbHeatHaze::MaxColumns
        u64 no_room = 0;     ///< columns the atlas had no room for
        u32 no_camera = 0;   ///< frames with flames but no camera, or a menu's preview
        u32 no_scene = 0;    ///< frames whose scene colour could not be written (not storage)
        u32 no_memory = 0;   ///< frames without room for the atlas
        float nearest = 0.0f;   ///< m: the nearest flame with a column
        float most_px = 0.0f;   ///< the largest shimmer reach of a column, px
        u64 pixels = 0;         ///< pixels under the columns' rectangles (each pass reads them)
    } stats;
    bool reported = false; ///< the first line (after FirstLineFrames) went out
    bool told_size = false;
    // bbport (r97d_heat-haze-real-shimmer)
    float out_scale = 1.0f;    ///< native width / scene width: render pixels -> output pixels
    bool told_image = false;   ///< the line about the image the pass writes went out
    // bbport (r97f_haze-per-flame): the flame finder (host_shaders/heat_haze_find.comp, heat_haze_flames.h):
    // each frame a scan of the 8 nearest lamps' surroundings in the scene colour, read back a frame or two
    // later into the table, which keeps where each lamp's flames are; the columns stand on those
    // (BB_HEAT_HAZE_FLAMES; 0: none of this is made).
    BbHeatHaze::FlameMode flames = BbHeatHaze::FlameMode::Off;
    float blob_min = BbHeatHaze::BlobMinDefault;
    bool find_made = false;
    bool find_zeroed = false; ///< the first scan's frame filled the device buffer with zeros
    vk::UniqueDescriptorSetLayout find_set_layout;
    vk::UniquePipelineLayout find_layout;
    vk::UniquePipeline find_pipeline;
    Buffer find_buffer, find_host;
    BbHeatHaze::FlameTable flame_table;
    u64 find_frame = 0;
    void PrepareFlames(const BbHeatHaze::Camera& view, std::span<const BbHeatHaze::Lamp> lamps,
                       std::vector<BbHeatHaze::ScanJob>& scans, std::vector<BbHeatHaze::Lamp>& sources);
    void ReadFinds(const BbHeatHaze::Camera& view);
    void RecordFind(const std::vector<BbHeatHaze::ScanJob>& scans, vk::ImageView color_view);
    void ReportFlames();
    struct FlameStats {
        u64 scans = 0;       ///< lamps scanned
        u64 answers = 0;     ///< new blocks read
        u64 with_flames = 0; ///< of them with at least one flame found
        u64 none = 0;        ///< of them with none
        u64 torn = 0;        ///< blocks whose check failed (the copy was in flight)
        u64 bad = 0;         ///< blocks with a number out of range
        u64 unknown = 0;     ///< blocks of a lamp the table no longer holds
        u64 anchored = 0;    ///< lamp frames whose columns stand on found flames
        u64 empty = 0;       ///< lamp frames scanned with no flame found
        u64 unscanned = 0;   ///< lamp frames with no answer yet
        u64 flames = 0;      ///< sources made of found flames
        float blob_max = 0.0f, bright_max = 0.0f;
    } flame_stats;
};

} // namespace Vulkan
