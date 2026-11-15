// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <memory>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/rt_lamp_cards.h" // bbport (r46b_plant-rule)
#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
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

// bbport (r46_lamp-cards): experiment bit 63: set = lamp rays leave out as cut-out cards only
// what the rule of before did (the entries whose sun shadow pass draw has a texture, while they
// do not count as moving; rt_lamp_cards.h), so plants cast whole-polygon lamp shadows again.
// Read at every scene build (RtShadow::PrepareScene). Set brings the picture fault back, so it
// is not one of BbSettings::PreviousPathsBits. Not bit 63 of the other mask
// (BbToggle::Fsr4EncodedInput).
inline constexpr u64 LampCardsOldBit = 9223372036854775808ull;

// bbport (r47_still-check): experiment bit 62: set = a caster held for still is built once and
// never looked at again, as before (rt_still_check.h): no probes, no signatures, the casters a
// look found moving are held for still again, the list of them is not read. Read at every draw
// and every frame end. Set brings the picture fault back (a lamp shadow that stays where a
// carried torch was first drawn), so it is not one of BbSettings::PreviousPathsBits. Not bit 62
// of the other mask (BbToggle::CameraYFlip).
inline constexpr u64 StillCheckOldBit = 4611686018427387904ull;

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
        // bbport (r47b_casters): `palette` holds the address and size of a small bone palette
        // and not a hash of its bytes: the palette lies in memory the GPU wrote (the game fills
        // its objects' constant buffers with a compute shader), so its bytes in guest memory are
        // not the ones the vertex shader reads. They read the same (zero) for every such prop,
        // so by their bytes all instances of a mesh were one instance entry: one caster at the
        // place of the instance that was drawn first when it was built, none at the others, and
        // a look of r47 that captured another instance found the caster "moved" by the distance
        // between the two. By its address each instance is an entry of its own. An object whose
        // palette alternates between two addresses (the carried torch and weapon) is two
        // entries, each drawn every other frame and both found moving by r47's looks.
        bool palette_placed = false;
        // bbport (r47c_review-fixes): the bytes of the position stream as this draw binds it
        // (0: not known): another size at a known address is another mesh (LampLoneSized).
        u32 positions_size = 0;
    };
    u32 PrepareDraw(const Draw& draw);
    // bbport (r47_still-check): the draw PrepareDraw was last called for is left out by the
    // rasterizer after all (see the definition).
    void CaptureLeftOut(u32 motion_param, u32 mode);
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
    // bbport (r47c_review-fixes): BB_RT_PALETTE_PLACE (see the definition): whether a small bone
    // palette in memory the GPU wrote may be known by its address (Draw::palette_placed).
    [[nodiscard]] static bool PalettePlace();

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
        // bbport (r46_lamp-cards): what any draw of it ever showed, kept for good (PrepareDraw;
        // LampCard in rt_lamp_cards.h reads them): a sun shadow pass draw of it samples a
        // texture; a camera pass draw of it has a discarding pixel shader; the camera pass
        // draws its mesh so in another draw (cutout_meshes, cutout_keys; looked up by
        // PrepareScene, again only while card_gen is not cutout_gen); a draw of it had a
        // skeleton.
        bool card_shadow = false;
        bool card_camera = false;
        bool card_mesh = false;
        bool skinned = false;
        u32 card_gen = 0;
        // bbport (r46b_plant-rule): the position stream of its draws (0: none), and what that
        // stream is taken for (LampLoneOf of lone_streams; Lone: a cut-out with a skeleton that
        // no sun shadow pass draws, a plant), as of lone_gen (looked up again by PrepareScene
        // only while that is not RtShadow::lone_gen).
        u64 stream = 0;
        LampLoneState lone = LampLoneState::None;
        u32 lone_gen = 0;
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
        // bbport (r47_still-check): a caster held for still (not moving, not a shared copy) is
        // looked at again in turn (rt_still_check.h). still_ref: the world bounds of the capture
        // its BLAS was built from, as a camera pass draw gave them ([0]) and as a sun shadow
        // pass draw did ([1]), where still_has_ref; still_ref_frame: the frame of that capture.
        // still_next: the frame of its next look; still_checks: looks since the build (the
        // first ones come early); still_wait: its signatures on their way back from the GPU
        // (still_pending points at it). still_camera_frame: its last camera pass draw.
        // still_moved: a look found it moving and `dynamic` was set for that (taken back while
        // the experiment bit is set); still_seen: found moving at least once (the log's "for
        // the first time"); still_blind: the signature of its last capture held no bounds (a
        // vertex that is not a number): no looks until its BLAS is built anew. still_doubt: the
        // last look found it moved and asked for a second one, which decides (ReadStillSigs).
        std::array<StillBox, 2> still_ref{};
        std::array<bool, 2> still_has_ref{};
        u64 still_ref_frame = 0;
        u64 still_next = 0;
        u64 still_camera_frame = 0;
        u8 still_checks = 0;
        u8 still_wait = 0;
        bool still_moved = false;
        bool still_seen = false;
        bool still_blind = false;
        bool still_doubt = false;
        bool palette_placed = false; // bbport (r47b_casters): see Draw::palette_placed
    };
    struct Build {
        Entry* entry;
        u32 store;
        bool update;
        std::array<float, 12> to_world;
        bool fast = false; // bbport (r17_rt-upkeep): ePreferFastBuild, no eAllowUpdate
        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
        // bbport (r47_still-check): the signature this capture's bounds go to (1 to
        // StillSigsPerFrame; 0: none), drawn by the camera pass (else by a sun shadow pass),
        // whether the BLAS is built from this capture (its bounds are the reference from then
        // on), and whether it is a probe: captured and measured only, nothing is built.
        // still_rows, still_origin: what takes the capture's clip space positions to world space
        // for the signature (StillClipToWorld; set with sig). param: its capture param, and
        // left_out: the rasterizer left its draw out, nothing is done with it (CaptureLeftOut).
        u32 sig = 0;
        bool still_camera = false;
        bool still_first = false;
        bool probe = false;
        bool left_out = false;
        u32 param = 0;
        std::array<float, 12> still_rows{};
        std::array<float, 3> still_origin{};
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
    // bbport (r46_lamp-cards): the same draws by the key entries are known by (Entry::base).
    // `mesh` hashes every vertex stream a draw binds, and a sun shadow pass shader may bind
    // fewer than the camera pass's; the key of a draw with a position stream does not depend on
    // the pass. cutout_gen changes whenever either set does: an entry looks itself up again only
    // then (Entry::card_gen; card_lookups counts the lookups since the last 600-frame line: a
    // camera pass cut-out whose mesh is new on every frame would make every entry look on every
    // frame). card_rule: the rule the scene's instance records were last written with (0 the
    // rule of before, else BB_RT_LAMP_CARDS). card_stats: those records' instances, for the
    // 600-frame line: left out of lamp rays as cut-out cards (of them: known from the sun
    // pass's texture, from their own camera pass draw, only from another camera pass draw of
    // their mesh, with a bone palette, without the sun's mask, counting as moving), skinned
    // cut-outs kept, what each rule would leave out, and the four left out with the most
    // triangles (CardFound, each mesh once). bbport (r46b_plant-rule): and those left out
    // that have a skeleton, and of the skinned cut-outs kept: those whose vertices a sun shadow
    // pass draws, and those still waiting (LampLoneState).
    std::unordered_set<u64> cutout_keys;
    u32 cutout_gen = 1;
    u32 card_rule = 0;
    u64 card_lookups = 0;
    // bbport (r46b_plant-rule): the position streams drawn with a skeleton by a sun shadow pass,
    // or by the camera pass with a discarding pixel shader (rt_lamp_cards.h, LampLone), by
    // their address. lone_gen changes whenever a stream is new to the map or is taken for
    // something else (LampLoneOf), or the map is thinned (Entry::lone_gen). sun_skinned_frame:
    // the last frame on which a sun shadow pass drew a skeleton (sun_skinned_any: one ever
    // did). lone_draws: draws that went through the map since the last 600-frame line.
    std::unordered_map<u64, LampLone> lone_streams;
    u32 lone_gen = 1;
    u64 sun_skinned_frame = 0;
    bool sun_skinned_any = false;
    u64 lone_draws = 0;
    // bbport (r47c_review-fixes): streams found with another size of vertices at their address
    // since the last 600-frame line (LampLoneSized: what was known of them was forgotten)
    u64 lone_resized = 0;
    struct CardFound {
        u64 mesh = 0, key = 0;
        u32 triangles = 0;
        bool by_shadow = false, by_camera = false, by_mesh = false, palette = false,
             instance = false, moving = false, camera_only = false, skinned = false;
        LampLoneState lone = LampLoneState::None;
    };
    struct CardStats {
        u32 out = 0, by_shadow = 0, by_camera = 0, by_mesh = 0, with_palette = 0,
            camera_only = 0, moving = 0, skinned_kept = 0, skinned_out = 0, lone_waiting = 0,
            sun_drawn = 0;
        std::array<u32, 4> rule_out{};
        std::array<CardFound, 4> largest{};
    } card_stats;

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
    // bbport (r47_still-check): the looks at the casters held for still (rt_still_check.h).
    // still_ready: the signature pipeline and its buffers are there (else no looks).
    // still_sigs: a frame's signatures on the GPU (device local, for the shader's atomics);
    // still_readback: their copies for the host, a ring of four frames like the capture
    // params. still_pending: the signatures recorded on each of those frames, and still_ticks
    // the tick of their submission: a frame's list is read once the GPU has passed its tick
    // (at the latest when the ring comes back to it) and points at entries until then, so
    // Destroy takes an entry's out. Per frame: the signatures taken, and the triangles looked
    // at in each lane (StillLanes: an entry's first look after a build, its other early looks,
    // the looks in turn; each lane has its budget, so a level's load, which queues three early
    // looks for every new caster, does not keep the first look of any of them waiting behind
    // the others). still_movers: the casters a look found moving, by the key of their entry
    // (the draw order key, or InstanceKey for an instance's own): one that is evicted and comes
    // back counts as moving at once. still_mover_triangles: those of the living entries so
    // counted, which BB_RT_STILL_MOVERS bounds (they are refit at every draw).
    // still_leave_count: instances BB_RT_LAMP_LEAVE alone left out of lamp rays in the records
    // last written. still_due, still_due_last: the triangles of the casters whose look in turn
    // was due on this frame so far and on the frame before, looked at or kept waiting: the next
    // look of each is put off while they are more than the budget (StillCrowd).
    bool still_ready = false;
    vk::UniqueDescriptorSetLayout still_set;
    vk::UniquePipelineLayout still_layout;
    vk::UniquePipeline still_pipeline;
    Buffer still_sigs, still_readback;
    struct StillPending {
        Entry* entry;
        u64 frame;
        u32 sig;
        bool camera;
        bool first;
    };
    std::array<std::vector<StillPending>, 4> still_pending;
    std::array<u64, 4> still_ticks{};
    static constexpr u32 StillLanes = 4; // bbport (r47c_review-fixes): 3: StillLaneOf's overdue
    u32 still_sig_used = 0;
    std::array<u32, StillLanes> still_used{};
    std::unordered_set<u64> still_movers;
    u64 still_mover_triangles = 0;
    u32 still_leave_count = 0;
    u64 still_due = 0, still_due_last = 0;
    // bbport (r47c_review-fixes): what sets the pace of the looks in turn (StillCrowd; still_due
    // is only printed now): the casters looked at in turn that this frame drew so far, due or
    // not (StillPoolShare of each), and the most a frame drew of late (StillPoolPeak), as of the
    // end of the frame before. placed_drawn: PrepareScene's list of the mesh keys of the moving
    // props known by an address that the frame draws.
    u64 still_pool = 0, still_pool_last = 0;
    StillPoolPeak still_pool_peak;
    std::vector<u64> placed_drawn;
    // What is done now: StillOff (also with the experiment bit set, or not ready), StillCount
    // or StillOn.
    [[nodiscard]] u32 StillNow() const;
    u32 TakeStillSig(Entry& entry);
    bool StillWorld(const float* constants, Build& build) const;
    void StillAdmit(Entry& entry, u64 id);
    void ReadStillSigs(u32 slot);
    // For the 600-frame line: a caster a look found moving (the four that moved farthest are
    // kept, each caster once), and the counts since the last line.
    struct StillFound {
        u64 id = 0, key = 0, mesh = 0, after = 0;
        u32 triangles = 0, checks = 0;
        float moved = 0.0f;
        StillBox then{}, now{};
        bool instance = false, camera = false, cross = false, taken = false;
        // bbport (r47b_casters): for BB_RT_STILL_LIST
        bool palette = false, placed = false, skinned = false;
        u32 finds = 0;
    };
    // bbport (r47b_casters): BB_RT_STILL_LIST: every caster a look found moving since the last
    // 600-frame line (each once, its farthest move), by StillFound::id
    std::unordered_map<u64, StillFound> still_list;
    struct StillStats {
        u64 probe_triangles = 0, waited = 0, no_room = 0, refits = 0, firsts = 0, unread = 0,
            found = 0, found_new = 0, found_instance = 0, found_camera = 0, found_cross = 0,
            taken = 0, not_taken = 0, known = 0, taken_back = 0, other_draw = 0, left_out = 0,
            doubted = 0, longest_wait = 0;
        // bbport (r47b_casters): draws with a small bone palette, those of them known by the
        // palette's address, and instances left without the lamp bit as PlacedOldPose
        u64 palette_draws = 0, placed_draws = 0, placed_old_pose = 0;
        // bbport (r47c_review-fixes): the longest a look has waited for its budget, served or
        // not, and of that look's caster: its triangles, the frames since its draw before, and
        // whether it counts as near (StillNext); held moving props known by an address that kept
        // the lamp bit; looks that found such a prop far away with a box of the same size
        // (StillCarried)
        u64 oldest_waiting = 0, oldest_triangles = 0, oldest_gap = 0, placed_held = 0,
            placed_carried = 0;
        bool oldest_near = false;
        std::array<u64, StillLanes> probes{};
        std::array<StillFound, 4> largest{};
    } still_stats;
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
