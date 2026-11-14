// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <memory>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"

#include <vk_mem_alloc.h>

namespace Vulkan {
class CameraMotion;
class Instance;
class ObjectMotion;
class Scheduler;
class SunVsm;

// bbport (r19_draw-cost): experiment bit: set = the old per-draw paths (read at each draw):
// RtShadow::PrepareDraw's memos, Rasterizer's sun atlas early return and Motion block reuse.
inline constexpr u64 R19DrawCostOffBit = 17592186044416ull;

// bbport (r41_lamp-shadows): experiment bit 45: set = ray traced lamp shadows as before their
// repair (read at every lamp pass and every scene build): the old weights, a point lamp, no
// grazing self skip (PointShadow::Flush, point_shadow_ray.comp MODE_REPAIR), and moving shared
// copies with an old pose still in lamp rays (RtShadow::PrepareScene, Entry::lamp_out). Set
// brings picture faults back, so it is not one of BbSettings::PreviousPathsBits.
inline constexpr u64 LampRepairOffBit = 35184372088832ull;

// Two layers:
//  1. Caster capture and cache (needs ray tracing on at launch): the game's sun shadow pass draws
//     (and camera pass draws) are keyed into `entries`; a position capture vertex shader variant
//     stores their clip space positions into `positions`, which are unprojected to world space and
//     kept per entry as a lasting `world` copy with a triangle list. This feeds the sun virtual
//     shadow map (SunVsm).
//  2. Ray tracing: per entry bottom level acceleration structures, a top level one and the ray
//     query pipelines.
class RtShadow {
public:
    RtShadow(const Instance& instance, Scheduler& scheduler, CameraMotion& camera_motion,
             const ObjectMotion& object_motion);
    ~RtShadow();

    [[nodiscard]] bool Capturing() const noexcept {
        return capturing;
    }
    // Ray tracing is set up, has not failed and is switched on.
    [[nodiscard]] bool RayTracing() const;
    [[nodiscard]] bool Wanted() const;
    [[nodiscard]] bool Complete() const;
    // The sun's shadow is replaced by the VSM or the ray traced sun rather than left to the game.
    [[nodiscard]] bool SunWanted() const;

    struct Draw {
        u64 shader = 0;
        u64 geometry = 0;
        u64 positions = 0;
        u64 indices = 0;
        u64 palette = 0;
        // bbport (r17_rt-upkeep): BB_RT_UNCHANGED: a hash of what the vertex shader reads (see
        // EffectsCaptureDraw); 0: not hashed or not provable.
        u64 inputs = 0;
        const float* constants = nullptr;
        u32 index_size = 0;
        u32 index_count = 0;
        u32 first_vertex = 0;
        u32 first_instance = 0;
        u32 instances = 1;
        bool restart = false;
        bool strip = false;
        bool triangles = false;
        bool shadow_pass = false;
        bool camera_pass = false;
        bool solid = false;
        bool skinned = false;
        bool alpha = false;
        // The pixel shader samples a texture. In the shadow pass that is a cut-out: a caster
        // drawn whole needs none.
        bool textured = false;
        // bbport (r14_cascade_rt): the guest viewport (centre x, y, half size x, y) and the depth
        // target's side: the sun cascade (atlas quadrant) of a shadow pass draw.
        std::array<float, 4> viewport{};
        u32 target = 0;
        // bbport (r19_draw-cost): the caller (EffectsCaptureDraw) found Wanted() true for this
        // draw just before: PrepareDraw does not ask again.
        bool r19_wanted = false;
    };
    u32 PrepareDraw(const Draw& draw);
    // bbport (r19_draw-cost): draws that took each short path since the last call (the
    // rasterizer prints them every 600 frames).
    struct R19Counters {
        u64 calls = 0, wanted_skipped = 0, mesh_made = 0, world_in_place = 0, camera_cached = 0,
            shared_known = 0, shared_memo = 0, entry_memo = 0, entry_filled = 0,
            far_book_skipped = 0;
    };
    R19Counters TakeR19Counters() {
        const R19Counters counters = r19_stats;
        r19_stats = {};
        return counters;
    }
    void BindAddresses(vk::PipelineLayout layout, u32 mode);
    // bbport (r17_rt-upkeep): whether PrepareDraw wants Draw::inputs (BB_RT_UNCHANGED set).
    [[nodiscard]] bool InputsWanted() const;

    bool PrepareScene();
    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {
        return tlas;
    }

    struct Inputs {
        vk::Buffer constants;
        vk::DeviceSize constants_offset = 0;
        vk::DeviceSize constants_range = 0;
        vk::Buffer uniforms;
        vk::DeviceSize uniforms_offset = 0;
        vk::DeviceSize uniforms_range = 0;
        vk::ImageView depth;
        vk::ImageView target;
        u32 constants_offset_word = 0;
        u32 frame_index = 0;
        u32 width = 0;
        u32 height = 0;
    };
    bool Record(const Inputs& inputs);

    void RecordBuilds();

    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
        u64 address = 0;
    };
    struct Entry {
        Buffer storage;
        Buffer indices;
        Buffer world;
        vk::AccelerationStructureKHR handle;
        u64 address = 0;
        u64 palette = 0;
        u32 first_vertex = 0;
        u32 vertices = 0;
        u32 triangles = 0;
        u32 instances = 1;
        u32 first_instance = 0;
        u64 scratch = 0;
        u64 update_scratch = 0;
        u64 bytes = 0;
        u64 scene_bytes = 0;
        u64 seen_frame = 0;
        u64 built_frame = 0;
        u32 rebuild_every = 120;
        // bbport (r17_rt-upkeep): the BLAS was built with eAllowUpdate (a fast-built shared copy
        // is not); Draw::inputs of the capture the BLAS holds (0: unknown); the frame of the last
        // capture; the last frame drawn by the camera pass, in c0/c1 or outside the sun atlas.
        bool r17_updatable = true;
        u64 r17_inputs = 0;
        u64 r17_capture_frame = 0;
        u64 r17_near_frame = 0;
        u8 mask = 1;
        bool built = false;
        bool dynamic = false;
        bool rebuilt = false;
        bool copied = false;
        // The BLAS holds this entry's geometry (false while the scene is not being built).
        bool blas = false;
        // Unlike the current-pass mask, this survives camera-only frames of a shared entry.
        bool shadow = false;
        // Value of `copies` when the world copy was last written.
        u64 copied_at = 0;
        // World bounds measured by the sun VSM (min xyz, max xyz), when has_box.
        std::array<float, 6> box{};
        bool has_box = false;
        // The replacement test's result for `cull_box` under the camera signature `cull_serial`.
        std::array<float, 6> cull_box{};
        u64 cull_serial = 0;
        bool culled = false;
        // Identity of the mesh without its shader (see PrepareDraw): the camera pass's alpha
        // cut-out meshes are known by it.
        u64 mesh = 0;
        // The shadow pass draws it with a texture: a cut-out card (leaves), which a lamp ray
        // would hit as its whole polygon (see LampMask).
        bool shadow_card = false;
        // The mesh and shader key (see PrepareDraw) and whether this is a promoted per instance
        // entry: a static prop identified by its bone palette, not by its draw order.
        u64 base = 0;
        bool instance = false;
        // The sun VSM's depth verification found nothing rendered where this kept caster's surface
        // is, on `gone_streak` verdicts in a row (three: gone). Cleared when the game draws it.
        bool gone = false;
        u8 gone_streak = 0;
        // bbport (r14_cascade_rt): the frame of its last shadow pass draw and the sun cascades
        // (bit c; bit 4: a draw in no single quadrant) that drew it on that frame; whether it is
        // in `held` (never evicted while it is).
        u64 shadow_frame = 0;
        u8 cascades = 0;
        bool held = false;
        // bbport (r41_lamp-shadows): a moving shared copy (rebuilt and dynamic): draws in a row
        // that went without a rebuild (PrepareDraw's skip, up to one more than counts as
        // starved), rebuilds in a row since it was left out, and whether it is starved: with
        // BB_LAMP_SHADOW_STALE=1 lamp rays leave it out (PrepareScene).
        u8 lamp_skips = 0;
        u8 lamp_builds = 0;
        bool lamp_out = false;
        // bbport (r43_copy-turns): a shared copy's turn to be rebuilt (rt_copy_turns.h): the
        // ticket the end of a frame gave it for its next draw, and the frames from its draw
        // before to its last (1: drawn every frame; CopyTurnGapUnknown: never before, or long
        // ago). For a moving copy, the draws in a row without a rebuild: on frames in a row
        // (turn_run; it starts again at a draw after frames undrawn) and after frames undrawn
        // (turn_back_run). Both feed the 600-frame line only. turn_listed: it is in turn_drawn.
        CopyTurnTicket turn;
        u8 turn_gap = 1;
        bool turn_listed = false;
        u16 turn_run = 0;
        u16 turn_back_run = 0;
    };
    struct Build {
        Entry* entry;
        u32 store;
        bool update;
        std::array<float, 12> to_world;
        bool fast = false; // bbport (r17_rt-upkeep): ePreferFastBuild, no eAllowUpdate
        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
    };

    bool Setup(const ObjectMotion& object_motion);
    bool Make(Buffer& out, vk::DeviceSize size, bool host, VkBufferUsageFlags usage);
    void Free(Buffer& buffer);
    void Destroy(Entry& entry);
    bool EnsureWorld(Entry& entry);
    bool ToWorld(const float* constants, bool perspective, std::array<float, 12>& out) const;
    bool MakeRaw(u32 width, u32 height);
    bool PrepareCapture();
    // Whether anything this frame traces the scene. Off (sun VSM only), captures only feed the
    // VSM's world copies and no acceleration structures are built.
    [[nodiscard]] bool SceneWanted() const;
    [[nodiscard]] bool VsmWanted() const;
    // The ray traced sun is drawn: asked for, or standing in for a VSM that could not be made.
    [[nodiscard]] bool SunRayTraced() const;
    u32 Param(u32 store, const Entry& entry);
    std::unique_ptr<Entry> MakeEntry(const Draw& draw, u8 mask);
    // bbport (r14_cascade_rt): see the definitions.
    u8 SunCascade(const Draw& draw);
    [[nodiscard]] bool Holds(const Entry& entry) const;
    void CollectHeld();
    void UpdateHeld();

    const Instance& instance;
    Scheduler& scheduler;
    CameraMotion& camera_motion;

    bool capturing = false;
    bool tried = false;
    bool failed = false;

    vk::UniqueDescriptorSetLayout address_layout;
    vk::UniqueDescriptorPool address_pool;
    vk::DescriptorSet capture_set;
    vk::DescriptorSet both_set;
    vk::UniqueDescriptorSetLayout trace_set, filter_set, unproject_set;
    vk::UniquePipelineLayout trace_layout, filter_layout, unproject_layout;
    vk::UniquePipeline trace_pipeline, filter_pipeline, unproject_pipeline;
    vk::UniqueSampler sampler;
    std::unique_ptr<SunVsm> vsm;
    bool vsm_tried = false;
    // SceneWanted() at the start of the frame, kept for the whole frame.
    bool need_scene = true;
    // World copies recorded so far, and the count at the last VSM pass (its changed casters).
    u64 copies = 0;
    u64 vsm_copies = 0;
    // Reused each frame: SunVsm::Record reads the casters synchronously.
    std::vector<SunVsm::Caster> vsm_casters;
    // What the replacement test of the kept casters depends on besides their boxes, as of the last
    // frame it ran; `cull_serial` changes whenever it differs (0: none yet).
    std::array<float, 12> cull_view{}, cull_inv_view{};
    std::array<float, 2> cull_proj{};
    std::size_t cull_drawn = 0;
    u64 cull_serial = 0;
    // Meshes the camera pass draws with a discarding pixel shader (alpha cut-outs): their points
    // legitimately float over the scene depth, so kept casters of them are never verified.
    std::unordered_set<u64> cutout_meshes;

    Buffer capture_addresses, both_addresses, params, positions, scratch, instance_data,
        tlas_storage, tlas_scratch;
    vk::AccelerationStructureKHR tlas;
    vk::Image raw_image;
    VmaAllocation raw_allocation{};
    vk::ImageView raw_view;
    u32 raw_width = 0, raw_height = 0;

    std::unordered_map<u64, std::unique_ptr<Entry>> entries;
    std::unordered_set<u64> shared_keys;
    // Palette draws (props with a small bone palette) seen by instance key; an instance seen on
    // three distinct frames is promoted to an entry of its own (see PrepareDraw).
    struct Candidate {
        u64 last = 0; // frame + 1
        u32 frames = 0;
    };
    std::unordered_map<u64, Candidate> candidates;
    // (mesh key, palette, mask) of the instances promoted this frame: their stale draw order
    // entries are retired at the end of the frame.
    std::unordered_set<u64> promoted_now;
    std::unordered_map<u64, u32> occurrences;
    // bbport: the same counts without a heap node per draw and frame: open addressing, slots of
    // an older frame (epoch) are free. A full probe run falls back to `occurrences`.
    // Experiment 2097152: `occurrences` only, as before.
    struct OccurrenceSlot {
        u64 hash = 0;
        u32 epoch = 0;
        u32 count = 0;
    };
    static constexpr u32 OccurrenceSlots = 8192; // power of two; ~3,400 keys a frame
    std::array<OccurrenceSlot, OccurrenceSlots> occurrence_slots{};
    u32 occurrence_epoch = 1;
    // Returns the count of `hash` this frame before this draw, and counts the draw.
    u32 NextOccurrence(u64 hash);
    // bbport (r19_draw-cost): a plain draw's Entry (no palette, not a shared copy) by its mesh
    // key, direct mapped. `entry` is what entries[key] held while r19_entries_gen (bumped by
    // every erase or move in `entries`) is unchanged: Entry objects never move (unique_ptr).
    // "Not shared" holds while shared_keys (insert only, never cleared) keeps `shared_size`.
    struct R19EntryMemo {
        u64 key = 0;
        Entry* entry = nullptr; // nullptr: empty
        u64 entries_gen = 0;
        u64 shared_size = 0;
    };
    static constexpr u32 R19EntryMemos = 4096; // power of two; ~1,330 entries drawn a frame
    std::vector<R19EntryMemo> r19_entry_memo = std::vector<R19EntryMemo>(R19EntryMemos);
    u64 r19_entries_gen = 1;
    u32 r19_camera_last = 0; ///< frame_cameras index of the last draw's constants
    R19Counters r19_stats;
    std::vector<const float*> frame_cameras;
    std::vector<Entry*> frame_entries;
    std::vector<Build> builds;
    std::array<u64, 4> slot_ticks{};
    // bbport (r17_rt-upkeep): this frame's instance records, those of the TLAS as last built or
    // refit (valid: by the new path, with eAllowUpdate), refits since its last full build, and
    // whether a BLAS build or refit was recorded since.
    std::vector<vk::AccelerationStructureInstanceKHR> r17_records, r17_tlas_records;
    bool r17_tlas_valid = false;
    bool r17_blas_dirty = true;
    u32 r17_tlas_age = 0;
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE, a measuring probe (off unless set).
    // r26_freeze: what this frame freezes (bit 0: BLAS refits and builds, bit 1: the TLAS; 0:
    // nothing), decided at the end of the frame before. r26_tlas_built: the TLAS was built (or
    // found the same as built) holding only live entries, so it may be traced as it is.
    // r26_tlas_kept: this frame traced it as it was. See R26FrameEnd.
    bool R26FrameEnd();
    u32 r26_freeze = 0;
    u64 r26_level_frames = 0;
    bool r26_tlas_built = false;
    bool r26_tlas_kept = false;
    struct R26Stats {
        u64 frames = 0, frozen = 0, refits_left = 0, refit_triangles = 0, builds_left = 0,
            build_triangles = 0, left_out = 0, recorded = 0, tlas_kept = 0, tlas_prepared = 0,
            evictions_held = 0;
        bool bit = false;
    } r26_stats;
    // bbport (r17_rt-upkeep): recent ToWorld results by their 28 input floats.
    struct ToWorldMemo {
        std::array<float, 28> in{};
        std::array<float, 12> out{};
        bool perspective = false;
        bool ok = false;
        bool used = false;
    };
    std::array<ToWorldMemo, 8> r17_memo{};
    u32 r17_memo_next = 0, r17_memo_last = 0;
    bool R17ToWorld(const float* constants, bool perspective, std::array<float, 12>& out);
    struct UpkeepStats {
        u64 frames = 0, refit = 0, refit_triangles = 0, rebuilt = 0, rebuilt_triangles = 0,
            fast = 0, fast_triangles = 0, same_skipped = 0, same_skipped_triangles = 0,
            same_would = 0, same_would_triangles = 0, same_unknown = 0, far_skipped = 0,
            far_skipped_triangles = 0, far_refit = 0, far_refit_triangles = 0, tlas_built = 0,
            tlas_updated = 0, tlas_skipped = 0, world_computed = 0, world_reused = 0;
    } r17_stats;
    u64 frame = 1;
    u32 params_used = 0;
    u32 positions_used = 0;
    u32 new_triangles = 0;
    u32 rebuilt_triangles = 0;
    // bbport (r43_copy-turns): the turns of the shared copies. PrepareDraw takes them,
    // PlanCopyTurns hands them out at the end of a frame. turn_drawn: the shared copies drawn
    // on this frame, in draw order, each once (Entry::turn_listed); like frame_entries it holds
    // entries only until the frame's end, where PlanCopyTurns empties it before the evictions.
    // turn_items is filled and emptied inside PlanCopyTurns (it points into entries).
    // turn_stats, since the last 600-frame line: the most frames in a row a moving copy drawn
    // every frame went without a rebuild, the most draws in a row one drawn again after frames
    // undrawn did, draws of copies after frames undrawn, and the turns (and their triangles)
    // that went past the budget for the bound.
    CopyTurns copy_turns;
    std::vector<Entry*> turn_drawn;
    std::vector<CopyTurnItem> turn_items;
    void PlanCopyTurns();
    struct TurnStats {
        u64 back = 0, past = 0, past_triangles = 0;
        u32 worst_run = 0, worst_back_run = 0;
    } turn_stats;
    u64 scratch_used = 0;
    u64 entry_bytes = 0;
    u32 missed = 0;
    u32 tlas_count = 0;
    u32 rays = 1;
    // bbport (r25_rt-sun-trace): BB_RT_SUN_HALF=1 (half-resolution sun trace, changes the
    // picture); the counters of rt_shadow.comp and rt_shadow_filter.comp (device local, copied
    // to r25_readback on the counted sun traces, one in 8; Record prints them every 600).
    static constexpr u32 R25Slots = 16;
    bool r25_half = false; ///< this sun trace runs at half resolution (R25HalfWanted)
    // bbport (r37_menu-options): BB_RT_SUN_HALF: -1 not set, 1 for "1", 0 for anything else; not
    // set, lantern.ini's graphics_rt_sun_half decides (read at every sun trace).
    int r25_half_env = -1;
    bool r25_half_tried = false; ///< R25HalfWanted made its attempt at the pipeline
    bool R25HalfWanted();
    bool r25_cleared = false; ///< r25_counts zeroed (by the first sun trace's commands)
    u64 r25_recorded = 0;     ///< sun traces recorded
    u64 r25_frames = 0;       ///< since the last line
    Buffer r25_counts, r25_readback;
    std::array<u32, R25Slots> r25_last{};
    // The half-resolution trace (rt_shadow_half_comp; made by R25HalfWanted when first wanted).
    vk::UniqueDescriptorSetLayout r25_half_set;
    vk::UniquePipelineLayout r25_half_layout;
    vk::UniquePipeline r25_half_pipeline;
    u64 scratch_align = 256;
    u64 blas_bytes = 0;
    u64 blas_limit = 320ull << 20;
    // bbport (r14_cascade_rt): sun shadow entries kept in the scene while the game leaves their
    // cascade undrawn (BbSunCascades::skip_period; a period below 2 or experiment 1099511627776:
    // off, as before). `held`: entries that may be held (Entry::held set); `held_now`: those held
    // at this point of the frame (CollectHeld).
    u64 hold_frames = 0; ///< frames an entry may stay undrawn this frame; 0: off
    u32 atlas_side = 0;  ///< the largest shadow pass depth target seen: the sun atlas
    u8 frame_cascades = 0; ///< cascades whose draws arrived this frame (bit 4: no single quadrant)
    std::vector<Entry*> held, held_next, held_now;
    std::size_t tlas_drawn = 0; ///< frame_entries in the TLAS last built (with tlas_count)
    u8 tlas_cascades = 0;       ///< frame_cascades when it was built
    struct HoldStats {
        u64 frames = 0, kept = 0, lent = 0, dropped = 0, aged = 0;
        std::array<u64, 5> cascade_frames{};
    } hold_stats;

    struct Stats {
        u64 draws = 0, camera_draws = 0, not_ortho = 0, no_camera = 0, alpha = 0, unsupported = 0,
            over_budget = 0, instanced = 0, dynamic_draws = 0, strips = 0, frames = 0, instances = 0,
            triangles = 0, shared_builds = 0, missed = 0, incomplete = 0, vsm_kept = 0,
            vsm_culled = 0, vsm_verified = 0, vsm_gone = 0, promoted = 0, merged = 0,
            cut_characters = 0, built_triangles = 0, evicted = 0, refit_triangles = 0;
    } stats;
};

}
