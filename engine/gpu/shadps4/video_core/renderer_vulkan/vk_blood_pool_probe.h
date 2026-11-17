// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe, r100d_blood-pool-draws): TOOL (branch dev/test-tools; never a
// feature branch or a pull request). Lists the draws that change a box of the scene (blood_pool_probe.h has the knob and the
// numbers, host_shaders/blood_pool_probe.comp the passes).
//
// Where (each hook a null pointer test while it is off):
//  - Rasterizer::BloodPoolProbeBefore, from EffectsBeforeResources (direct draws) and
//    DrawIndirectRecord (indirect draws), after the draw's targets are found and before its
//    textures, barriers and pass: BeforeDraw notes the draw and, while probing, records SNAPSHOT.
//  - Rasterizer::BloodPoolProbeNote (r100d), from DrawRecord and DrawIndirectRecord once the draw's
//    textures are bound (right after the spark probe's place): Note keeps the probed draw's index
//    range and textures for its draw line (host work only, while probing).
//  - EffectsAfterDraw and DrawIndirectRecord after the draw command: AfterDraw records COMPARE.
//  - EffectsOnFrameEnd: OnFrameEnd takes a new box from the knob, counts the frames before probing,
//    and logs the "Blood pool probe (r100c)" lines when the GPU is past the probed frames.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do. Nothing the game draws is changed: the passes only read its targets.
//
// Off (BB_BLOOD_POOL_PROBE unset, empty, 0 or off at start): the rasterizer makes no BloodPoolProbe
// (Wanted), so nothing of this is made or run. Made but idle (no box, or done): two compares a draw
// and a look at the live knobs generation a frame. While probing (CaptureFrames frames): two passes
// and two render pass splits for every draw into scene-sized targets.
#pragma once

#include <array>
#include <cstddef>
#include <map>
#include <string>
#include <tuple>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_pool_probe.h"
#include "video_core/renderer_vulkan/glass_find.h" // bbport (t86q_glass-finder, TOOL)
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace AmdGpu {
union Regs;
}

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

class BloodPoolProbe {
public:
    /// BB_BLOOD_POOL_PROBE at start is not off (BloodPoolProbeRules::Parse, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knob once; a box given at start arms the probe.
    BloodPoolProbe(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
                   Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~BloodPoolProbe();
    BloodPoolProbe(const BloodPoolProbe&) = delete;
    BloodPoolProbe& operator=(const BloodPoolProbe&) = delete;

    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target, `light` a light draw (shadow resolve, sun or moon,
    /// lamp grid), `lamps_pending` a lamps-apart batch is open, `indirect` an indirect draw.
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth, bool light,
                    bool lamps_pending, bool indirect);
    /// A bound texture as a draw line names it.
    struct Texture {
        u64 address = 0;
        u32 width = 0, height = 0, format = 0;
    };
    /// Once the draw's textures are bound (the draw BeforeDraw saw last): `indexed` with the index
    /// buffer's address `index_address` and first index `first_index` (an indirect draw: none),
    /// the first `count` textures after its own targets, `all` of them, `hash` over all their
    /// addresses. Kept only while probing.
    void Note(bool indexed, u64 index_address, u32 first_index, const std::array<Texture, BloodPoolProbeRules::DrawTextures>& textures,
              u32 count, u32 all, u32 hash);
    /// After every draw command: COMPARE when BeforeDraw recorded SNAPSHOT for it.
    void AfterDraw();
    /// Every frame end.
    void OnFrameEnd();

private:
    enum class State { Idle, Armed, Capturing, Waiting, Finding };
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
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// What the log needs of one draw of a probed frame.
    struct DrawInfo {
        u64 vs = 0, ps = 0;
        u32 indices = 0, instances = 0;
        u32 mrt = 0;
        std::array<u32, 8> format{};   ///< vk::Format of each bound colour target
        std::array<u8, 8> role{};      ///< RoleName index
        u32 write_masks = 0;           ///< 4 bits a colour target
        u32 depth_format = 0;
        u32 read_mask = 0;             ///< targets SNAPSHOT read (bit 8: the depth)
        u8 blend = 0;                  ///< a bit a colour target: blending on
        u8 depth_func = 0;
        u8 phase = 0;                  ///< BloodPoolProbeRules::Phase
        bool depth_test = false, depth_write = false, indirect = false, light = false;
        bool probed = false;           ///< COMPARE recorded
        bool noted = false, indexed = false; ///< r100d: Note came for it; an indexed draw
        u64 index_address = 0;         ///< the index buffer's address (without the first index)
        u32 first_index = 0;
        std::array<Texture, BloodPoolProbeRules::DrawTextures> textures{};
        u32 texture_count = 0, textures_all = 0, texture_hash = 0;
        u8 skipped = 0;                ///< Skip reason (0: none)
        // bbport (t86q_glass-finder, TOOL): the draw's blend state and screen box, for the glass finder.
        u8 blend_cb = 255;             ///< first colour target with blending on (255: none)
        std::array<u8, 6> blend_f{};   ///< colour src, dst, func; alpha src, dst, func (BlendControl values)
        bool blend_separate = false;   ///< alpha blends apart from colour
        s16 vp[4]{};                   ///< viewport 0 as x0, y0, x1, y1 in target pixels
        u16 target_w = 0, target_h = 0; ///< the size of the draw's first target (a colour target, else the depth)
    };
    enum Skip : u8 { NotSkipped, LampsApart, NotScene, Unreadable, LeftOut, Preview, NoView };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    /// A game image's view for sampling in a pass (the reduced proxy or the image, General layout);
    /// null when it cannot be sampled.
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect);
    void TakeKnob(bool at_start);
    bool StartCapture();
    void EndCapture();
    void Log();
    void Fail(const char* why);
    // bbport (t86q_glass-finder, TOOL): the glass finder (vk_blood_pool_probe.cpp, glass_find.h).
    void TakeGlass(bool at_start);
    void FindFrameEnd();
    void FindLog();
    void GlassRectLog();
    static u64 FindSig(const DrawInfo& d);
    static std::string TargetsText(const DrawInfo& d, const u32* counts, u32 frames);
    static std::string BlendText(const DrawInfo& d);
    static std::string DrawText(const DrawInfo& d);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, compare_pass;
    Buffer prints, counts, owners;
    vk::DeviceSize prints_size = 0;
    std::array<ViewEntry, 16> view_cache{};
    u64 view_uses = 0;
    bool tried = false, failed = false;

    State state = State::Idle;
    BloodPoolProbeRules::Knob box{};  ///< the box being probed (or last probed)
    BloodPoolProbeRules::Knob next{}; ///< a box that came while the probe was busy
    BloodPoolProbeRules::Knob last_taken{}; ///< the knob's last box (a file change of another knob keeps it)
    bool next_live = false, box_live = false;
    u32 knob_generation = 0;
    u32 arm_need = 0, arm_frames = 0, wait_frames = 0;
    u64 done_tick = 0;

    // bbport (t86q_glass-finder, TOOL). A wide find fills infos[0] with each scene frame's draws (capture
    // stays 0) and sums them by (vs, ps, state signature); a rectangle find arms the r100d capture.
    struct FindSum {
        u32 draws = 0, frames = 0, last_frame = 0, idx_min = ~0u, idx_max = 0;
        u8 phases = 0;
        bool have = false;
        DrawInfo rep{};
    };
    std::map<std::tuple<u64, u64, u64>, FindSum> find_sums;
    GlassFindRules::Mode glass_mode = GlassFindRules::Mode::Off; ///< BB_GLASS_FIND as last read
    GlassFindRules::Rect glass_rect{};  ///< the rectangle to probe (armed, or last probed)
    GlassFindRules::Rect glass_taken{}; ///< the knob's last rectangle (a file change of another knob keeps it)
    char glass_text[48] = {};           ///< the rectangle's text, for the log
    bool find_pending = false, find_live = false; ///< a wide find is asked for; it came through the live file
    bool next_glass = false, glass_live = false;   ///< a rectangle is asked for; it came through the live file
    bool arm_find = false, box_glass = false;      ///< what the armed or last probe is: wide find, rectangle
    u32 find_frames = GlassFindRules::DefaultFrames, find_frame = 0;

    // This frame.
    bool frame_gbuffer = false;  ///< a G-buffer pass was drawn
    bool frame_lit = false;      ///< a light draw came after the last G-buffer pass
    u32 ordinal = 0;             ///< draws seen this frame
    bool note_due = false;       ///< r100d: BeforeDraw kept a DrawInfo that Note may complete
    u32 note_ordinal = 0;
    VideoCore::ImageId scene_depth{};
    u32 scene_width = 0, scene_height = 0;      ///< the scene depth's size
    // The probed frames.
    u32 capture = 0;                            ///< the probed frame being drawn
    bool capture_reduced = false;
    u32 cap_width = 0, cap_height = 0;          ///< the scene depth's size (targets of it are probed)
    u32 pixels_width = 0, pixels_height = 0;    ///< scene pixels (the render size)
    u32 grid_cols = 0, grid_rows = 0;
    std::array<std::vector<DrawInfo>, BloodPoolProbeRules::CaptureFrames> infos;
    std::array<u32, BloodPoolProbeRules::CaptureFrames> over_cap{};
    struct Pending {
        bool on = false;
        u32 ordinal = 0;
        u32 mask = 0;
        std::array<VideoCore::ImageId, BloodPoolProbeRules::Targets> ids{};
        u32 owner_targets = 0;
    } pending;
};

} // namespace Vulkan
