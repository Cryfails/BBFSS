// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints, r111b): the hunter's footprints after he stepped in water or in blood on
// the ground (and, with a test knob, mud), laid into the game's G-buffer so its own lights light
// them (footprints.h has
// the knobs and the rules, host_shaders/footprints.comp the pass).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsBeforeResources, every draw (BeforeDraw): before its textures, barriers and pass. It
//    notes each G-buffer pass's depth and targets 1 (gloss), 2 (albedo) and 3 (specular colour); at
//    the first light draw after each G-buffer pass (the sun's shadow resolve, the sun or moon, or a
//    lamp of the light grid) it takes the frame's water plane (CameraMotion::MirrorPlane) and records
//    the pass over the smallest screen rectangle that holds the boxes of the prints on this pass's
//    screen and of the ground around the hunter (not while a lamps-apart batch is open: the batch's
//    lamps read the G-buffer later; not in a menu's 3D preview). Targets 1 and 3 must be
//    R8G8B8A8_UNORM, target 2 R8G8B8A8_UNORM or _SRGB (the game's: written through a UNORM view,
//    the shader decodes and encodes sRGB).
//  - EffectsOnFrameEnd (OnFrameEnd): the hunter's position (BbEngine::world_player_position), the
//    sense read back from a recent frame, the coat, the step, the prints' fading; every LineFrames
//    frames two log lines.
// The pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do.
//
// Off (BB_FOOTPRINTS unset, 0 or other text): the rasterizer makes no Footprints (Wanted), so nothing
// of this is made or run and the game's memory is not read; the frame is as before, bit for bit.
// On: one pipeline and three small buffers (1.5 KB of prints, 128 B of counters, 64 B host copy),
// made at the first pass; no image. A frame whose prints and hunter are all off this pass's screen
// records nothing. It needs the upscaler's camera (CameraMotion::Enabled): without it, off (said).
#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/footprints.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class Footprints {
public:
    /// BB_FOOTPRINTS is 1 or "show" (FootprintRules::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    Footprints(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~Footprints();
    Footprints(const Footprints&) = delete;
    Footprints& operator=(const Footprints&) = delete;

    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target; `light_draw`: the sun's shadow resolve, the sun or
    /// moon, or a lamp of the light grid; `lamps_pending`: a lamps-apart batch is still open;
    /// `jitter`: this frame's viewport shift.
    void BeforeDraw(const GraphicsPipeline& pipeline, const std::array<VideoCore::ImageId, 8>& targets,
                    VideoCore::ImageId depth, bool light_draw, bool lamps_pending,
                    std::array<float, 2> jitter);
    /// Every frame end: the hunter, the coat, the steps and prints; every LineFrames frames the
    /// "Footprints (r111):" lines.
    void OnFrameEnd();
    /// (r111e) Once a frame at the upscaler's trigger, after the lighting: the prints over the scene
    /// colour `color` (the flat red test view BB_FOOTPRINTS_SHOW, or the post stamp BB_FOOTPRINTS_POST),
    /// depth tested against the scene's depth. Nothing when both are off or no print is on screen.
    void DrawOver(VideoCore::ImageId color, std::array<float, 2> jitter);

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    /// A placed print: where, which way, its kind, its strength when placed and its time.
    struct Placed {
        float x = 0.0f, y = 0.0f, z = 0.0f;
        float dir_x = 0.0f, dir_z = 1.0f, side = 1.0f;
        FootprintRules::Kind kind = FootprintRules::Kind::Wet;
        float strength = 0.0f; ///< when placed
        float now = 0.0f;      ///< faded (OnFrameEnd)
        double born = 0.0;     ///< seconds since the start
    };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    /// A game image's view for the pass, of format `format` (the image's own, or a format of the
    /// same size it may be viewed as): the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::Format format, vk::ImageAspectFlags aspect,
                         bool storage, bool write);
    struct CounterStep {
        bool clear = false, copy_back = false;
        u32 slot = 0;
    };
    /// Commands every first pass of a frame records first: the last frame's counters to the host,
    /// this frame's slot cleared.
    CounterStep TakeCounterStep();
    void Edit(std::array<float, 2> jitter);
    void Fail(const char* why);
    void Place(const FootprintRules::Step& step, FootprintRules::Kind kind, float strength, double now);

    static constexpr u32 LineFrames = 600;
    static constexpr u32 ViewMax = 80, ViewEvery = 120; ///< (r111j) most view lines, and the passes between two

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    vk::UniqueDescriptorSetLayout edit_set_layout;
    vk::UniquePipelineLayout edit_layout;
    vk::UniquePipeline edit_pipeline;
    Buffer prints_buffer, counters, readback;
    u64 counter_frame = 0; ///< frame + 1 whose slot was cleared; 0: none yet
    u64 counter_used = 0;  ///< frame + 1 that last used a slot
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    u64 frame = 0;
    std::chrono::steady_clock::time_point start;

    // The walk, the coat and the prints (OnFrameEnd).
    FootprintRules::Walker walker;
    FootprintRules::Coat coat;
    std::array<Placed, FootprintRules::MaxPrints> placed{};
    u32 placed_count = 0; ///< live prints, the oldest first
    bool hunter_known = false;
    std::array<float, 3> hunter{};
    // This frame, from BeforeDraw.
    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_albedo{}, gbuffer_specular{};
    bool gbuffer_seen = false, edit_tried = false;
    bool plane_seen = false; ///< a water plane this frame (plane_y)
    float plane_y = 0.0f;
    bool told_unfit = false, told_position = false, told_unread = false, told_print = false;
    std::array<bool, 3> told_pickup{}; ///< the first pickup of each kind is told
    bool told_onscreen = false, told_camera = false; ///< (r111c) the first prints on a screen; the camera near
    float told_gain = -1.0f; ///< (r111d) the gain the last "gain now" line said (-1: none yet)

    struct Stats {
        u32 frames = 0, read = 0, unread = 0, steps = 0, dry_steps = 0, in_water = 0, glossy = 0;
        u32 jumps = 0, passes = 0, off_screen = 0, no_camera = 0, cannot = 0, lamps_open = 0;
        u32 previews = 0, sense_fresh = 0, planes = 0;
        std::array<u32, 3> pickups{};  ///< coat pickups by kind (the feet newly in a source)
        std::array<u32, 4> steps_in{}; ///< steps by what the feet stood in (R::Source)
        u32 share_n = 0, share_last = 0, share_max = 0, share_sum = 0; ///< blood share at pickups, %
        // (r111c) prints on a pass's screen, and what a read-back of the pass showed
        u32 sent_prints = 0, print_passes = 0, readbacks = 0, print_px_frames = 0, print_px_max = 0;
        float print_near_m = 0.0f, print_far_m = 0.0f; ///< camera to the prints sent
        int box_w = 0, box_h = 0;                      ///< the largest print box on a screen, px
        u64 stamp_px_sum = 0; ///< (r111h) the post stamp's pixels, summed over the read-backs
        /// (r111i) over the read-backs, [0] wet or mud pixels, [1] blood pixels: their number and the summed lit
        /// luminance before and after the stamp (times FOOTPRINTS_FLAT_LUM_SCALE)
        std::array<u64, 2> lum_px{}, lum_before{}, lum_after{};
        u64 sheen_px = 0; ///< (r111j) over the read-backs, the blood pixels the sheen lifted
        u32 trail_prints = 0, tail_prints = 0, trail_holds = 0; ///< (r111k) prints by the trail rules, in the taper; frames held
        std::array<u32, 3> by_kind{}; ///< prints placed, by kind
        u64 pass_px = 0;
        float near_m = 0.0f, far_m = 0.0f, low_m = 0.0f, high_m = 0.0f; ///< camera to the hunter
        u32 camera_n = 0;
    } stats;
    std::array<u32, FootprintRules::SlotWords> sense{}; ///< the last fresh host copy
    bool sense_fresh = false;

    // (r111e) The draw over the picture: its pipeline and buffers are made at its first pass.
    bool FlatReady();
    vk::UniqueDescriptorSetLayout flat_set_layout;
    vk::UniquePipelineLayout flat_layout;
    vk::UniquePipeline flat_pipeline;
    Buffer flat_prints, flat_counts, flat_host;
    bool flat_tried = false, flat_failed = false, told_flat = false;
    struct Flat {
        u32 frames = 0, passes = 0, off_screen = 0, no_camera = 0, cannot = 0, sent = 0;
        u32 red_last = 0, red_max = 0, post_last = 0, post_max = 0; ///< pixels of the last pass read back
        u64 rect_px = 0;
        u32 read_back = 0, groups_ok = 0; ///< (r111f) passes whose counters came back, with every group run
    } flat;
    // (r111f) The proof that the pass ran, and where the prints are on the screen: a snapshot of each pass
    // (the CPU's numbers) is kept for 4 frames and matched by the frame's stamp to the counters the pass
    // wrote (the GPU's numbers).
    struct FlatSnap {
        u32 stamp = 0, show = 0, count = 0, groups = 0, mode_pass = 0, episode = 0;
        u32 in_frame = 0, behind = 0;     ///< (r111j) of the prints sent: centre inside the picture, behind the camera
        float gain = 0.0f, sheen = 0.0f;  ///< (r111j) the pass's strength and BB_FOOTPRINTS_SHEEN
        std::int32_t rect_w = 0, rect_h = 0;
        std::array<float, 3> camera{};
        struct Point {
            float x = 0.0f, y = 0.0f, z = 0.0f; ///< the print's world position
            FootprintRules::ScreenPoint screen;
        };
        std::array<Point, FootprintRules::FlatProbes> points{};
    };
    struct FlatProbe {
        u32 last_stamp = 0;   ///< the last pass whose counters were taken
        u32 episode = 0;      ///< counts the changes of mode (post stamp / flat view)
        bool show = false;    ///< the mode of this episode
        u32 mode_passes = 0;  ///< passes recorded in this episode
        u32 next_pass = 6;    ///< the pass of this episode to tell next
        u32 told = 0;         ///< probes told, at most FlatProbeMax
        bool told_stamp = false; ///< (r111g) the first stamped pixels were told
    } flat_probe;
    std::array<FlatSnap, 4> flat_snaps{};
    void FlatProbeRead(const std::array<u32, FootprintRules::FlatWords>& counts);
    void LogProbe(const FlatSnap& snap, const std::array<u32, FootprintRules::FlatWords>& counts) const;
    void LogFlat() const;
    void LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const; // (r111g)
    void LogTotals() const; // (r111h)
    void LogLuma() const;   // (r111i)
    // (r111j) one line per view, and the sheen's counter
    void ViewRead(const FlatSnap& snap, const std::array<u32, FootprintRules::FlatWords>& counts);
    void LogView(u64 at_frame, const FlatSnap& snap, u32 px, double lum_before, double lum_after, u32 verdict) const;
    void LogSheen() const;
    void LogTrail() const; // (r111k)
    struct ViewTold { ///< what the last view line said (a line is told when it changes, and every ViewEvery passes)
        u32 lines = 0, since = 0, verdict = 99, in_frame = ~0u;
        float gain = -1.0f, sheen = -1.0f;
    } view_told;
};

} // namespace Vulkan
