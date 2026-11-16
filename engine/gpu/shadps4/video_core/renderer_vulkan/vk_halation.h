// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): film halation, a red-orange glow around very bright small sources
// (halation_params.h has the knobs and the passes' rules; host_shaders/halation.comp the passes).
//
// Where: Rasterizer::EffectsBeforeUpscaler, at the upscaler's trigger dispatch, after the drawn
// look and the fog composite, on the scene colour the upscaler is about to take, at the scene's
// render size (the reduced scene while a preset renders below the game's size). So:
//  - the HUD is never touched: the game draws it after its final composite, on the upscaler's
//    output (docs/hdr-scene-path.md, "After the composite"), which this pass never sees;
//  - with DLSS (or FSR, XeSS, the engine's TAA) it runs on the internal frame (1920x1080 for 4K
//    output with DLSS Performance), a quarter of the output's pixels, and the upscaler takes the
//    glow as a smooth part of the scene. Its input is the jittered frame and nothing is
//    un-jittered: the jitter (under a pixel) is small against the blur (a sigma of 12 pixels at
//    1080 lines and radius 1), and the glow is added to the same jittered frame it came from;
//  - the glow is linear light before the game's exposure and tone curve, so it is compressed with
//    the light it comes from, and the game's bloom, added in that composite, stays apart from it;
//  - without the upscaler (BB_UPSCALER=none, or a GPU it cannot run on) the trigger is never
//    reached and nothing is drawn (said once at the start).
// A menu's 3D preview frame (CameraMotion::PreviewFrame) is left alone, as the drawn look does.
//
// The strength (bbport r109a_strength-settings-engine): Strength(), read every frame (the setting
// graphics_halation_strength, or BB_HALATION when it is set; halation_params.h, StrengthOf). At 0
// nothing is drawn. Until the first frame above 0 the rasterizer makes no Halation, so nothing of
// this is made or run and the frame is as before, bit for bit. At that frame the rasterizer makes
// it and keeps it, also when the strength goes back to 0: the pipeline, the sampler and two small
// buffers are made then; two quarter-size RGBA16F images (2.1 MB at a 1920x1080 scene) are made
// then and anew when the scene's size changes.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/halation_params.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
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

class Halation {
public:
    /// bbport (r109a_strength-settings-engine): this frame's strength and its source: BB_HALATION
    /// when it is set (read once), else the setting graphics_halation_strength (read each call).
    [[nodiscard]] static StrengthKnob::Value Strength();
    /// Each frame end: the "Halation (r109a):" line with the strength and its source, at the
    /// first frame and after a change (at most once every LineFrames frames).
    static void StrengthLine();
    /// Says the knobs once; `upscaler_on`: the upscaler runs, so the pass has its place.
    Halation(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
             Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
             bool upscaler_on);
    ~Halation();
    Halation(const Halation&) = delete;
    Halation& operator=(const Halation&) = delete;

    /// The upscaler's trigger: the glow at `strength` (above 0, at most
    /// HalationParams::MaxStrength) into the scene colour `color` (once a frame).
    void Apply(VideoCore::ImageId color, float strength);
    /// Every frame end: the counters, and every LineFrames frames the "Halation (r95):" line.
    void OnFrameEnd();

private:
    struct Quarter {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
    };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageView view{};
        u64 last_use = 0;
    };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    bool EnsureImages(u32 width, u32 height);
    void ReleaseImages();
    vk::ImageView CachedView(const VideoCore::Image& image);
    void Fail(const char* why);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::UniqueSampler sampler; ///< linear, clamped to the edge
    /// The two quarter images: A (the down pass, the blur's end) and B (between the blurs).
    std::array<Quarter, 2> quarter;
    u32 quarter_width = 0, quarter_height = 0;
    /// The key's two slots (HalationParams::KeySlotBytes each), device memory, and the host copy
    /// of the frame before's slot (copied by each pass, read by the line).
    Buffer key_buffer, readback;
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool applied = false; ///< this frame's trigger was handled (ran or skipped)
    u64 runs = 0;         ///< passes recorded; the key slot is runs & 1
    u64 frame_ends = 0;   ///< bbport (r109a): OnFrameEnd calls (HalationParams::ClearsKey)
    u64 ran_at_end = 0;   ///< bbport (r109a): frame_ends at the last pass
    u32 last_width = 0, last_height = 0;

    struct Stats {
        u32 frames = 0, ran = 0, previews = 0, small = 0, no_room = 0;
    } stats;
};

} // namespace Vulkan
