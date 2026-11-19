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
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <tuple>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_pool_probe.h"
#include "video_core/renderer_vulkan/glass_find.h" // bbport (t86q_glass-finder, TOOL)
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace WorkflowProbe {
struct Transfer;
}

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

struct RenderState;

class BloodPoolProbe {
public:
    /// BB_BLOOD_POOL_PROBE at start is not off (BloodPoolProbeRules::Parse, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knob once; a box given at start arms the probe.
    BloodPoolProbe(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
                   Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    // t178: the physical index bind of one direct draw, with guest first folded into offset.
    struct BoundIndex {
        vk::Buffer buffer{};
        u64 offset{}, capacity{}, guest{}, bytes{};
        vk::IndexType type{};
        u32 sealed_id{}, generation{};
        bool sealed{}, transfer_src{};
    };
    struct IndexCommand {
        u32 count, guest_first, vk_first, instances, first_instance;
        s32 vertex_offset;
        vk::PrimitiveTopology topology;
        bool restart, confirmed;
    };
    [[nodiscard]] bool WantsBoundIndex(u32 count, u32 first) const;
    void CopyBoundIndex(const RenderState& render, const BoundIndex& index, const IndexCommand& command);

    ~BloodPoolProbe();
    BloodPoolProbe(const BloodPoolProbe&) = delete;
    BloodPoolProbe& operator=(const BloodPoolProbe&) = delete;

    // t132a TEST TOOL. Capture-local values only, with an explicit join key for Note.
    struct FoliageToken {
        u64 serial = 0;
        u32 frame = 0, ordinal = 0;
        bool camera_gbuffer = false;
        u8 selected = 0; // one-based startup draw selector, if matched
        bool operator==(const FoliageToken&) const = default;
    };
    struct FoliageView {
        std::array<u32, 4> range{}, swizzle{}; // base mip, mip count, base layer, layer count
        u32 type = 0, format = 0, min_lod = 0;
        bool storage = false;
        static FoliageView From(const VideoCore::ImageViewInfo& view);
        bool operator==(const FoliageView&) const = default;
    };
    struct FoliageTexture {
        enum class Source : u8 { NoBindingFacts, Null, Unverified, Registered };
        u64 uid = 0, write_seq = 0;
        std::array<u32, 8> sharp{};
        FoliageView view{};
        u32 id = VideoCore::ImageId::INVALID_INDEX;
        Source source = Source::NoBindingFacts;
        bool operator==(const FoliageTexture&) const = default;
    };
    struct FoliageFacts {
        u64 vs = 0, ps = 0;
        u64 position_base = 0, index_base = 0;
        u32 position_size = 0, stride = 0, position_data_format = 0, position_number_format = 0;
        u32 index_type = 0, primitive = 0, first_index = 0, count = 0, instances = 0;
        u32 first_vertex = 0, first_instance = 0;
        bool position_valid = false, indexed = false, indirect = false, restart = false;
        bool has_ps = false, discard = false, camera_gbuffer = false, offsets_known = false;
        u32 verdict = 0, num_inputs = 0, default_inputs = 0, flat_inputs = 0;
        std::array<u8, 32> input_offsets{};
        bool resolved = false, card_valid = false;
        u32 miss = 0, selector = 0, stored_channel = 0, card_format = 0, op = 0;
        std::array<u32, 8> tsharp{};
        // Exact float bits, including the two original reference dwords.
        std::array<u32, 8> card_words{}; // affine[4], reference, dither scale, ref_dwords[2]
        bool dither = false, fade_left_out = false, nonzero = false;
        u8 clamp_u = 0, clamp_v = 0;
        u64 uv_hash = 0, constants_hash = 0;
        u32 texture_count = 0, binding_count = 0, alpha_matches = 0;
        bool binding_enabled = false, bindings_exact = false;
        std::array<FoliageTexture, 8> textures{};
        FoliageTexture alpha{};
        u32 alpha_slot = ~0u;
        bool operator==(const FoliageFacts&) const = default;
    };

    using FoliageTargetViews = std::array<const VideoCore::ImageViewInfo*, 9>;
    [[nodiscard]] bool FoliageCapturing() const;
    [[nodiscard]] std::optional<FoliageToken> FoliageNoteToken(bool indexed, u32 first_index) const;
    void NoteFoliageFacts(FoliageToken token, const FoliageFacts& facts);
    [[nodiscard]] bool IvyOwnerAllows(FoliageToken token) const;
    void NoteIvyOwnerSample(u64 serial, u32 frame, u32 ordinal, u64 tick,
                            std::array<float, 2> jitter);

    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target, `light` a light draw (shadow resolve, sun or moon,
    /// lamp grid), `lamps_pending` a lamps-apart batch is open, `indirect` an indirect draw.
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth, bool light,
                    bool lamps_pending, bool indirect, const FoliageTargetViews* foliage_views = nullptr);
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
    void LogIvyOwner(bool gpu_done, u32 wrong, const std::array<u32, 7>& skipped);
    struct FoliageCapture;
    void CensusFoliage(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                       const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                       const FoliageTargetViews& views, u32 n, u8 phase, bool indirect, bool lamps_pending);
    void LogFoliage(const std::map<u32, std::array<u32, BloodPoolProbeRules::OwnerMaps>>& owners,
                    bool gpu_done, u32 wrong_counts, u32 unlisted);
    std::unique_ptr<FoliageCapture> foliage;
    u64 foliage_serial = 0;
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
    void LogBoundIndex(bool gpu_done);

    friend class Rasterizer;
    // References only to the current direct draw context, consumed by the post-submit t178 hook.
    struct BoundLayerInput {
        const std::vector<vk::WriteDescriptorSet>* writes{};
        std::span<const VideoCore::ImageId> images{};
        const GraphicsPipeline* pipeline{};
        u32 frame{}, ordinal{};
    } bound_layer_input;

    struct BoundLayerRow {
        u64 view{}, sampler{}, uid{}, write_seq{}, address{};
        FoliageView view_info{};
        std::array<u64, 16> guest_mip_hash{};
        std::array<u32, 16> guest_mip_size{};
        u32 id{}, width{}, height{}, tile_mode{}, array_mode{}, bank_swizzle{}, flags{}, format{};
        u32 levels{}, layers{}, pitch{}, bits{};
        bool alt_tile{};
        const char* result = "write_missing";
    };
    struct BoundLayerEvidence {
        std::array<BoundLayerRow, 6> rows{};
        u64 serial{}, fragment_key{}, vertex_key{}, pipeline_key{}, permutation{}, tick{};
        u32 frame{}, ordinal{}, issued{};
        const char* refusal = "draw_missing";
    } bound_layer_evidence;
    void NoteBoundLayers(const RenderState& render, const IndexCommand& command,
                         BoundLayerInput input);
    void LogBoundLayers(bool gpu_done, const char* role);
    [[nodiscard]] bool ExactBoundOwner(bool gpu_done, u64 serial, u32 frame, u32 ordinal) const;
    bool bound_layer_enabled = false;

    bool bound_index_enabled = false;
    u8 bound_index_targets = 0;
    u8 bound_index_target = 0;
    u64 bound_index_serial = 0;
    struct IndexEvidence {
        std::shared_ptr<WorkflowProbe::Transfer> transfer;
        IndexCommand command{};
        u64 serial{}, offset{};
        u32 frame{}, ordinal{}, width{}, generation{}, issued{};
        bool sealed{};
        const char* refusal = "draw_missing";
    } bound_index_evidence;

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
