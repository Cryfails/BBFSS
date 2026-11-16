// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced
// scene (glass_glint.h has the knobs and the rules, host_shaders/glass_glint.comp the passes).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsAfterTargets, at a G-buffer draw (ClearLights): the lamps of the last G-buffer pass
//    only (they are in its view space).
//  - EffectsBeforeBind, at a lamp draw of the light grid (AddLights, after its OnLightDraw):
//    its records, as drawn.
//  - EffectsCaptureDraw notes a pane draw it admitted (its pipeline); EffectsAfterDraw, right after
//    that draw (AfterGlassDraw): the passes COARSE and SHADE, once the gate lets them (glass_glint.h).
//    A pane draw left out before it is made (an uncompiled pipeline) never reaches AfterDraw: the
//    note names the pipeline, AfterDraw compares it and always clears it, the frame end too.
//  - EffectsOnFrameEnd (OnFrameEnd): the counters, and every LineFrames frames the log line.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do.
//
// Off (BB_GLASS_GLINT unset or 0, or BB_RT_GLASS off): the rasterizer makes no GlassGlint
// (Wanted), so nothing of this is made or run, and RtShadow carries no pane (RtGlassCarryOn is
// BB_RT_GLASS_LIGHT's own test then); the frame is as before. On: two pipelines and a 6 KB host
// buffer (counters and lamps) are made at the start; a buffer of a word per 4x4 block (518 KB at
// 1920x1080, 2.1 MB at 3840x2160) at the first pass, and anew when the scene grows. A pass that
// cannot get that buffer is counted as "shape".
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/glass_glint.h"
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
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

class GlassGlint {
public:
    /// BB_GLASS_GLINT names a strength above 0 or "show", and BB_RT_GLASS is on (read once).
    [[nodiscard]] static bool Wanted();
    /// Makes the pipelines and the counters; says the knobs once.
    GlassGlint(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
               RtShadow& rt_shadow);
    ~GlassGlint();
    GlassGlint(const GlassGlint&) = delete;
    GlassGlint& operator=(const GlassGlint&) = delete;

    /// A lamp draw of the game's light grid: `count` records of 16 words (lamp_fog_lights.h).
    void AddLights(const u32* records, u32 count);
    /// A G-buffer draw: the lamps gathered so far are another pass's.
    void ClearLights();
    /// Right after a pane's forward draw: its target 0 (`color`) and depth; `jitter` this frame's
    /// viewport shift; `lamps_open` a lamps-apart batch is still open (PointShadow::Pending).
    void AfterGlassDraw(VideoCore::ImageId color, VideoCore::ImageId depth,
                        std::array<float, 2> jitter, bool lamps_open,
                        const ::BbGlassGlint::PaneDraw& pane); // bbport (r86e_glint-hit-distance)
    /// Every frame end: the frame's counts, and every LineFrames frames the log line.
    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    /// The block flags' buffer holds at least `bytes` (the old one is freed after the GPU is done).
    bool EnsureWork(vk::DeviceSize bytes);
    void Count(::BbGlassGlint::Skip skip);
    void Report();

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;

    const ::BbGlassGlint::Knobs& knobs;
    Pass coarse, shade;
    Buffer counters;    ///< host coherent: Slots counter slots, then their data blocks
    Buffer work;        ///< device local: a word a block
    vk::DeviceSize work_bytes = 0;
    bool made = false;
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    LampFog::FrameLights lights;

    // This frame.
    u32 frame_passes = 0;
    std::array<VideoCore::ImageId, ::BbGlassGlint::MaxPasses> frame_depths{};
    u64 passes = 0; ///< all passes: the slot is passes % Slots

    struct Stats {
        u32 frames = 0, glass_draws = 0, passes = 0;
        u32 no_pane = 0, other_camera = 0, no_lamps = 0, lamps_open = 0, shape = 0, cap = 0;
        u32 gate_off = 0; // bbport (r86j_glint-same-game): pane draws asked while the live setting was 0
        u32 read = 0; ///< passes whose counts were read (Slots - 1 passes late)
        u64 lamps = 0;
        std::array<u64, ::BbGlassGlint::CounterWords> words{};
        float max_add = 0.0f;
        // bbport (r86c_glass-glint-visible): the log's second line: the largest over the passes read
        // (the brightest term, the highest N.H, the nearest distance as the shader stores it) and
        // the lamps as pushed
        float best_max = 0.0f, nh_max = 0.0f;
        u32 dist_stored = 0;
        float lamp_colour_max = 0.0f, reach_min = 0.0f, reach_max = 0.0f;
    } stats;
    u64 first_pass_frame = 0; ///< BbStats::frame_number of the first pass, + 1; 0: none yet
    bool told_first = false;
    /// bbport (r86j_glint-same-game): the live strength seen at the last frame end (negative: test view);
    /// -2 before the first frame. A change prints the GLINT-PROOF gate line and the counts so far.
    float gate_last = -2.0f;
};

} // namespace Vulkan
