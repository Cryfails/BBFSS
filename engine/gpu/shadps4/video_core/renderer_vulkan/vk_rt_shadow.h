// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <array>
#include <memory>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/rt_lamp_cards.h" // bbport (r46b_plant-rule)
#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
#include "video_core/renderer_vulkan/rt_card_uv.h"     // bbport (r54_leaf-stage2)
#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/rt_card_skinned.h" // bbport (r62n_cutout-skinned-blocker)
#include "video_core/renderer_vulkan/rt_card_sun.h" // bbport (r128c_lrt-cutout-props)
#include "video_core/renderer_vulkan/foliage_translucency.h" // bbport (r131a_foliage-translucency)
#include "video_core/renderer_vulkan/rt_glass.h"       // bbport (r83_glass-water-stage1)
#include "video_core/renderer_vulkan/rt_glass_light.h" // bbport (r86_glass-light-stage2a)
#include "video_core/renderer_vulkan/rt_glass_static.h" // bbport (r121b_glass-pane-hang)
#include "video_core/renderer_vulkan/glass_light_forward.h" // bbport (r130g_glass-light-forward)
#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
#include "video_core/renderer_vulkan/bottle_caustic_topology.h"
#include "video_core/renderer_vulkan/vk_reflection_first_hit.h"
#include "video_core/renderer_vulkan/vk_reflection_native_probe.h"

#include <vk_mem_alloc.h>

namespace Vulkan {
class CameraMotion;
struct LampPaneProbe;
class Instance;
namespace InteriorRoof { class Probe; struct WatchRow; }
namespace WindowPathProbe { struct SceneObservation; struct PaneAcquisition; struct LampSceneIdentity; }
class ObjectMotion;
class Scheduler;
class SunVsm;
namespace RtGlassPick { // bbport (r86l_glint-pick-glass, TOOL): rt_glass_pick.h, included by vk_rt_shadow.cpp
struct EntryView;
struct Texts;
} // namespace RtGlassPick
namespace RtGlassTri { // bbport (r86m_glint-pane-from-triangle, TOOL): rt_glass_tri.h, included by vk_rt_shadow.cpp
struct State;
} // namespace RtGlassTri

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
class CardAlpha; // bbport (r62_leaf-stage3)

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
    // bbport (r130g_glass-light-forward): the rasterizer asks (before r121b's placed palette refusal) whether a pane draw whose
    // registry hit is `hit` (Draw::glass_entry, index + 1) may be taken with a palette the GPU wrote; the lamp pass hands in the
    // glass counter it read back. False at its first test while BB_GLASS_LIGHT is off.
    [[nodiscard]] bool GlassPlacedAllowed(u8 hit) const;
    void GlassRaysSeen(const std::array<u32, 10>& words) noexcept {
        glass_rays_now = words;
    }
    [[nodiscard]] bool SunWanted() const;
    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT (glass_light.h), decided at start (GlassLightStart): the lamp pass makes its
    // GLASS builds, PrepareScene rewrites the records of glass entries. GlassLightActive: this frame's knob is on and the last
    // scene held glass records (the lamp rays then ask the glass query).
    [[nodiscard]] bool GlassLightWanted() const noexcept {
        return glass_light_mode != 0;
    }
    // bbport (r131c_cabinet-glass-clear): the rasterizer says each frame (SetGlassClear) whether BB_GLASS_CLEAR is on: PrepareScene
    // then gives the glass record of a clearing kind (the cabinet's pane) RtGlassMask alone. GlassClearRecords: those records so far.
    void SetGlassClear(bool on) noexcept {
        glass_clear_now = on;
    }
    [[nodiscard]] u64 GlassClearRecords() const noexcept {
        return glass_clear_records;
    }
    [[nodiscard]] bool GlassLightLive() const noexcept {
        return glass_light_live;
    }
    [[nodiscard]] bool GlassLightActive() const noexcept {
        return glass_light_mode != 0 && glass_light_now && glass_light_records_now != 0;
    }
    /// The lamp pass could not make its GLASS builds (no storage format): off for good, as if never asked.
    void GlassLightOff() noexcept {
        glass_light_mode = 0;
    }
    /// One repair pass pushed the glass words (`active`: with the glass flag), for the 600-frame line.
    void NoteGlassLightPass(bool active) noexcept {
        ++glass_counts.passes;
        glass_counts.passes_glass += active ? 1u : 0u;
    }

    struct BottleDrawToken {
        u32 private_param = 0;
        bool observed = false;
    };

    struct ReflectionDrawToken {
        const void* entry{};
        u64 allocation{};
        u64 cookie{};
        u64 placement{};
        u32 first{};
        u32 min_index{};
        u32 max_index{};
        ReflectionFirstHit::PlacedSource placed = ReflectionFirstHit::PlacedSource::None;
        struct {
            u64 key{}, cookie{}, revision{}, pass{};
            bool enabled{}, same_identity{};
        } placement_delta;
    };
    void ReflectionAttach(ReflectionFirstHit::Pass*);
    void ReflectionCloseEpoch();
    bool ReflectionBeginPass(const ReflectionFirstHit::Stamp&);
    bool ReflectionSubmitted(const ReflectionFirstHit::Stamp&, const ReflectionDrawToken&,
                             u64 vs, u64 ps, u32 count, u32 first,
                             const ReflectionNativeProbe::Binding* placed);
    void ReflectionFlush(const ReflectionFirstHit::Stamp&);
    void ReflectionAdmissions(u64 request) const;
    void ReflectionNativeSubmitted(const ReflectionNativeProbe::Draw&);

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
        // bbport (r62n_cutout-skinned-blocker): the bones of the skeleton palette a skinned draw binds (its size / 48; 0: none)
        u32 skeleton_bones = 0;
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
        // bbport (r50_leaf-stage1): the pixel shader's pgm_hash (0: none); read only with
        // BB_RT_CARD_ALPHA_LOG=1 (the cut-out cards' pixel shaders, PrepareDraw)
        u64 pixel_shader = 0;
        // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1 (a capture pipeline with
        // CaptureUv), a cut-out pixel shader's card data as this draw holds it
        // (EffectsCaptureDraw's, valid during the PrepareDraw call); null otherwise
        const CardDraw* card = nullptr;
        // bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's forward draw, given as a
        // solid camera pass draw without cut-out (EffectsCaptureDraw); its entry is its own
        // (RtGlassKey) and takes RtGlassMask alone
        bool glass = false;
        // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1 with a box set: a G-buffer draw PrepareDraw would leave
        // out (a discard, blended) given an entry as a pane to see whether the box holds it (EffectsCaptureDraw sets
        // it with `glass`); and the draw's blend / depth write / discard as RtGlassFind::Flag* bits (find only)
        bool box_candidate = false;
        u32 find_flags = 0;
        // bbport (r129a_glass-registry): the registry entry of this draw, index + 1 (0: none; always 0 while the registry
        // is off). Unread in r129a; S1 reads it in PrepareDraw to withhold LampMask/ShadowMask and for the instance's tint.
        u8 glass_entry = 0;
        // bbport (r130g_glass-light-forward): a registered pane let through r121b's placed palette refusal (set by the rasterizer
        // from RtShadow::GlassPlacedAllowed; PrepareDraw then asks GlassPlacedSteady). Always false while BB_GLASS_LIGHT is off.
        bool glass_placed = false;
        bool lamp_pane_observe = false; // t132d test tool, carries no scene policy
        bool window_pane_observe = false;
        // True only for the ordinary indexed camera variant, with CPU-current bound indices.
        bool lamp_affine_candidate = false;
        bool bottle_candidate = false;
        BottleDrawToken* bottle_delivery = nullptr;
        ReflectionDrawToken* reflection = nullptr;
        ReflectionNativeProbe::Draw* reflection_native = nullptr;
    };
    u32 PrepareDraw(const Draw& draw);
    [[nodiscard]] bool LampAffineAvailable() const noexcept {
        return bool(lamp_affine_pipeline);
    }
    [[nodiscard]] LampPaneProbe* ActiveLampPane() const noexcept;
    void PollLampPane(u64 scene_frame);
    // bbport (r47_still-check): the draw PrepareDraw was last called for is left out by the
    // rasterizer after all (see the definition).
    void CaptureLeftOut(u32 motion_param, u32 mode);
    // bbport (r89_wind-foliage-sway): whether the plant rule takes the position stream at
    // `positions` (an address; 0: none) with `size` bytes bound (0: not known) for lone
    // (LampLoneOf of lone_streams: a cut-out with a skeleton no sun shadow pass draws, a plant),
    // as of the draws so far. Another size than the stream is known with is another mesh: false.
    [[nodiscard]] bool LonePlant(u64 positions, u32 size) const;
    // bbport (r112_wind-more-things): whether a sun shadow pass drew the stream at `positions` with
    // `size` bytes bound (0: not known) with a skeleton (LampLoneState::Sun of lone_streams: the
    // game gives the mesh a sun shadow; characters, and the hanging things of BB_WIND_HANG), as of
    // the draws so far. Another size than the stream is known with is another mesh: false.
    [[nodiscard]] bool SunSkinned(u64 positions, u32 size) const;
    // bbport (r112b_hang-probe, TOOL; BB_WIND_HANG_PROBE=1): the rigid sun-shadowed entries
    // with their world bounds, logged once from OnFrameEnd (the first time at or after 600 capture
    // frames that one is found, retried every 30 frames up to 1800)
    void WindHangProbeReport();
    u32 wind_probe_frames = 0;
    bool wind_probe_done = false;
    // bbport (r112i_hang-find-lanterns): the world boxes of the entries a draw reached in the last 120
    // frames (the sun VSM's, else the still check's bounds; entries with none are left out), whatever
    // they are: the static hanging things are judged against them and the survey lists them; and the
    // camera's world position
    struct HangFindBox {
        u64 stream = 0;
        u32 vertices = 0, triangles = 0;
        std::array<float, 6> box{};
        char src = '?';
        bool skinned = false, dynamic = false, palette = false, shadow = false;
    };
    void WindHangFindBoxes(std::vector<HangFindBox>& out, std::array<float, 3>& camera,
                           bool& camera_ok) const;
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
    void BindAddresses(vk::PipelineLayout layout, u32 mode, u32 bottle_param = 0);
    [[nodiscard]] bool BottleCapturePending(u32 param) const noexcept;
    void RecordBottleDraw(BottleDrawToken token);
    // bbport (r17_rt-upkeep): whether PrepareDraw wants Draw::inputs (BB_RT_UNCHANGED set).
    [[nodiscard]] bool InputsWanted() const;
    // bbport (r47c_review-fixes): BB_RT_PALETTE_PLACE (see the definition): whether a small bone
    // palette in memory the GPU wrote may be known by its address (Draw::palette_placed).
    [[nodiscard]] static bool PalettePlace();

    // Optional diagnostic output from the same natural preparation. Its TLAS must be
    // consumed on this scheduler before any later scene preparation.
    bool PrepareScene(WindowPathProbe::SceneObservation* window = nullptr);
    // Retain one historical CPU snapshot while a receiver capture is armed.
    void WatchWindowScene(WindowPathProbe::SceneObservation* observer) noexcept {
        window_scene_watch = observer;
    }
    bool TryWatchWindowScene(WindowPathProbe::SceneObservation* observer) noexcept {
        if (!observer || (window_scene_watch && window_scene_watch != observer)) {
            return false;
        }
        window_scene_watch = observer;
        return true;
    }
    void UnwatchWindowScene(const WindowPathProbe::SceneObservation* observer) noexcept {
        if (window_scene_watch == observer) {
            window_scene_watch = nullptr;
        }
    }
    [[nodiscard]] bool LampSceneMatches(const WindowPathProbe::SceneObservation& observation,
                                      VideoCore::ImageId depth, u64 uid) const noexcept;
    void WatchWindowPane(WindowPathProbe::PaneAcquisition* observer) noexcept {
        window_pane_watch = observer;
    }
    struct BottleSceneView {
        vk::AccelerationStructureKHR tlas{};
        vk::Buffer corners{};
        u32 ordinal{};
    };
    void ResetBottlePass(const std::array<u64, 3>& targets);
    [[nodiscard]] bool TryBottleDraw();
    void InvalidateBottleGeometry(u64 address);
    [[nodiscard]] bool BottleObserved() const noexcept;
    [[nodiscard]] BottleSceneView BottleScene(const std::array<float, 12>& view);
    [[nodiscard]] u64 WindowDiagnosticFrame() const noexcept { return frame; }
    [[nodiscard]] u64 WindowSceneSerial() const noexcept { return window_scene_active_serial; }
    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {
        return tlas;
    }
    // bbport (r86b_glass-visible): BB_GLASS_GLINT: the pane records of the TLAS last written,
    // whether PrepareScene wrote them this frame, and the camera (world to view, 3x4 rows) they
    // were placed with (the TLAS's view space)
    struct GlassSceneView {
        u32 instances = 0;
        bool this_frame = false;
        std::array<float, 12> view{};
    };
    [[nodiscard]] GlassSceneView GlassScene() const noexcept {
        return {glass_instances, glass_frame == frame, glass_view};
    }
    // bbport (r86f_glass-static-panes): BB_RT_GLASS on: the camera constants (the 864-byte buffer's
    // words, as a G-buffer draw holds them) a pane draw without constants of its own takes: the
    // frame's main camera (the pointer most of its camera pass draws held). nullptr: none seen yet
    // this frame, or BB_GLASS_STATIC_PANES 0.
    [[nodiscard]] const float* GlassCamera();
    // bbport (r86h_glint-camera): whether the frame's camera vote holds a candidate now (a camera pass draw
    // with constants came since the last frame end; the HUD, drawn after it, finds none). No side effect.
    [[nodiscard]] bool GlassCameraKnown() const noexcept {
        return r86f_camera != nullptr;
    }
    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: which PrepareDraw test a pane draw (as the
    // effects hook built it, camera constants given) would fail first, as an RtGlassFind::Verdict
    // (0 = passes all); no side effect. `sample` (size bytes, may be null) gets one line of the draw's
    // numbers: index count, instances, triangles, indices, whose constants, the projection's words 12-15.
    [[nodiscard]] u32 GlassVerdict(const Draw& draw, bool own_constants, char* sample,
                                   std::size_t size) const;
    // bbport (r86i_glint-find-gbuffer): BB_GLASS_FIND=1: called at every frame end. With BB_GLASS_FIND_BOX
    // (x0:y0:x1:y1 of the 1920x1080 picture; also live through a job's set:) it lists, at the find's report
    // frames and 90 frames after a new box, the camera pass entries whose world bounds project into the
    // box, and with BB_GLASS_BOX_PANES=1 takes the small ones inside it by their mesh key.
    void GlassFindBox();
    // bbport (r86i_glint-find-gbuffer): whether this G-buffer draw is of a mesh the box rule took (the key
    // PrepareDraw gives a draw with a position stream); false at once while none was taken.
    [[nodiscard]] bool GlassBoxMatch(const Draw& draw) const;
    // bbport (r86k_glint-box-gbuffer): BB_GLASS_FIND=1: whether this G-buffer draw (`left_out`: PrepareDraw would
    // give it no entry: a discard or not solid) is made a probe entry so the box listing can see it (see the patch
    // header). Counts per frame; false at once while no box is set or BB_GLASS_BOX_PANES is off.
    [[nodiscard]] bool GlassBoxCandidate(const Draw& draw, u64 vs, u64 ps, bool left_out);
    // bbport (r86l_glint-pick-glass, TOOL): the glass pick (BB_GLASS_PICK, vk_rasterizer_effects.cpp). GlassPickTake: a G-buffer
    // draw of this mesh key (the position key PrepareDraw gives a draw with a position stream) becomes a pane: GlassBoxMatch is
    // true for it, in a table of 32 keys apart from the box rule's (a live knob change that clears the box's keys leaves these);
    // false when the key is known or the table is full. GlassPickEntries: the scene's entries of that key (a mesh may have
    // several: palettes, copies); `out` gets at most `most`, the return value counts them all. GlassPickRead: the texts of
    // BB_GLASS_PICK, _SIZE, _FRAME, _REPEAT and _PANES (live where the test tools' knobs file exists, else the environment);
    // true when the knobs' generation changed since the last call (the first call too).
    [[nodiscard]] bool GlassPickTake(u64 key);
    [[nodiscard]] u32 GlassPickEntries(u64 key, RtGlassPick::EntryView* out, u32 most) const;
    [[nodiscard]] bool GlassPickRead(RtGlassPick::Texts& texts);
    // bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the glass pick named this mesh key under a pane pixel
    // (rt_glass_tri.h). The key's solid entry is captured again and its world positions are copied to a host slot; the pane is
    // then cut from the triangles under the pane pixels (GlassTriFrameEnd) and the key taken with them. `note`: the text of a new
    // want or pixel (or why none); the return value is true when a pixel was added.
    [[nodiscard]] bool GlassTriWant(u64 key, s32 x, s32 y, const char*& note);
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2. The card layers (CardAlpha, the rasterizer
    // owns it; null when off or when its layers could not be made), whose fills PrepareCapture
    // records before every reader of the scene: the rows and custom indices only with them. The
    // card table (one row a card slot; null until the first scene with them) and r54's pool, for
    // the readers (rt_cards.glsl). The row counts for CardAlpha's 600-frame line.
    void SetCardLayers(CardAlpha* layers) noexcept {
        card_layers = layers;
        card_layers_on = layers != nullptr;
    }
    struct CardTablesView {
        vk::Buffer rows;
        vk::Buffer pool;
    };
    [[nodiscard]] CardTablesView CardTables() const noexcept {
        return {card_rows.buffer, card_pool.buffer};
    }
    struct CardRowCounts {
        u64 written = 0, ready = 0, deferred = 0;
    };
    CardRowCounts TakeCardRowCounts() noexcept {
        const CardRowCounts counts = card_row_counts;
        card_row_counts = {};
        return counts;
    }
    // bbport (r62m_cutout-name-blocker, TOOL): what the card slot (an instance's custom index; the blocker book of the lamp pass)
    // belongs to: the entry's mesh+shader key (Entry::base), its card's pixel shader and pass, rule (op, reference, layer), size,
    // flags and world box (the sun VSM's, else the still check's bounds; box_src 'v', 's', 'c', '-' none), the box centre in view space.
    // found false: no entry carries the slot (any more). Scans `entries`: called a few times a test, from the lamp pass's window line.
    struct CardBlockerInfo {
        bool found = false;
        u64 key = 0, ps = 0, stream = 0;
        bool camera_pass = false, skinned = false, dynamic = false, instance = false;
        u32 triangles = 0, vertices = 0, op = 0, layer = 0;
        float reference = 0.0f;
        char box_src = '-';
        std::array<float, 6> box{};
        std::array<float, 3> centre_view{};
        // bbport (r62n_cutout-skinned-blocker) TOOL: the most bones of a skeleton palette a draw of it bound (0: none), r46b's sign (lone: no sun
        // shadow pass draws its vertices) and its words
        u32 bones = 0;
        bool lone = false;
        const char* lone_text = "not skinned";
    };
    [[nodiscard]] CardBlockerInfo CardBlockerOf(u32 slot) const;
    // bbport (r62n_cutout-skinned-blocker) TOOL: the hunter (the game's physics position, BbEngine::world_player_position: false while it is not
    // readable) against a point in view space: his place in world and view space, how far the point lies from him sideways (x and z of the world,
    // y up) and how far above him (negative: below). Reads the engine's memory: a few pointer reads, from the lamp pass's window line only.
    struct HunterRel {
        bool known = false;
        std::array<float, 3> world{}, view{};
        float horizontal_m = 0.0f, up_m = 0.0f;
    };
    [[nodiscard]] HunterRel HunterAgainst(const std::array<float, 3>& point_view) const;
    // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_SKINNED (live with the test knobs file when present, else read at start) and
    // BB_RT_CARD_LAMP_BONES (read at start): see rt_card_skinned.h
    [[nodiscard]] static CardSkinnedMode CardSkinnedModeNow();
    [[nodiscard]] static u32 CardSkinnedBonesNow();
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 with BB_RT_CARD_ALPHA=2 (read once, said once):
    // the lamp rays read the cards. PrepareScene gives a plant's or a static cut-out's instance
    // whose row has data CARD_LAMP_MASK and FORCE_NO_OPAQUE (CardLampOn). What a lamp pass binds for
    // its CARDS build (null handles: not yet), with the card instances of the TLAS last written
    // (0: the pass binds its build of before); the counts for PointShadow's 600-frame line.
    [[nodiscard]] static bool CardLampsWanted();
    struct CardLampReaders {
        vk::Buffer rows, pool, info;
        vk::ImageView layers;
        vk::Sampler sampler;
        u32 instances = 0;
        vk::ImageView colour; // bbport (r131a_foliage-translucency): the colour layers (null unless made)
    };
    [[nodiscard]] CardLampReaders CardLampReadersNow() const;
    // bbport (r131a_foliage-translucency): BB_RT_CARD_SUN's own switch, for the foliage translucency's start line and the glow pass; and the
    // sun trace's hue image (the FOLIAGE builds' second output, rt_shadow.comp): its view and size, empty unless the trace wrote it this frame or
    // the one before.
    [[nodiscard]] static bool CardSunOn() {
        return CardSunWanted();
    }
    struct SunHueView {
        vk::ImageView view;
        u32 width = 0, height = 0;
    };
    [[nodiscard]] SunHueView SunHueNow() const noexcept {
        return sun_hue_view && frame <= sun_hue_frame + 1 ? SunHueView{sun_hue_view, sun_hue_width, sun_hue_height} : SunHueView{};
    }
    // A lamp pass that can bind a CARDS build is under way (PointShadow::CardLampSet): the cards
    // take CARD_LAMP_MASK only within CardLampHoldFrames of the last such pass (none: lamp rays
    // off, or no CARDS build made), so that no card is made non-opaque, or forces a full TLAS build,
    // for nothing.
    void NoteCardLampUser() noexcept {
        card_lamp_user_frame = frame;
        card_lamp_user_seen = true;
    }
    struct CardLampCounts {
        u64 records = 0;     ///< instance records written with CARD_LAMP_MASK
        u64 flips = 0;       ///< card instances whose CARD_LAMP_MASK came or went, whatever the cause
        u64 flip_writes = 0; ///< TLAS record writes with at least one such change (each a full build)
        u64 writes = 0;      ///< TLAS record writes
        u32 instances = 0;   ///< in the TLAS last written, with CARD_LAMP_MASK
        u32 plants = 0;      ///< of them skinned (lone: r54's class "plant")
        u32 moving = 0;      ///< of them not skinned but moving (a palette or the still check)
    };
    CardLampCounts TakeCardLampCounts() noexcept {
        CardLampCounts counts = card_lamp_counts;
        counts.instances = card_lamp_instances;
        counts.plants = card_lamp_plants;
        counts.moving = card_lamp_moving;
        card_lamp_counts = {};
        return counts;
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

    // bbport (r64b_surface-probe-more): BB_SURFACE_PROBE=1 only (read once at start, off by
    // default): what the surface probe (vk_rasterizer_effects.cpp) asks of the scene for its log.
    // Nothing here changes the scene or the picture. probe_draw: the entry the last PrepareDraw
    // reached (key 0: none); the rasterizer takes it after each capture draw. A build of it may
    // have its world positions copied to a host slot (ProbeCopyBuild) with the world copies of
    // RecordBuilds, after the unproject pass.
    static bool ProbeWanted();
    const bool probe_on = ProbeWanted();
    struct ProbeDraw {
        u64 key = 0;
        const u32* indices = nullptr; ///< its triangle list (host memory), valid during this draw
        u32 triangles = 0, vertices = 0, instances = 0;
        u32 build = 0; ///< 1 + its index in `builds` when this draw captures it for a build
        u8 mask = 0;
        bool skinned = false, dynamic = false, blas = false;
        u64 guest_hash = 0; ///< a skinned draw's guest index list hashed (0: not this frame)
    };
    ProbeDraw ProbeTakeDraw() noexcept {
        const ProbeDraw draw = probe_draw;
        probe_draw = {};
        return draw;
    }
    /// Set by the rasterizer's probe for a frame in which skinned draws hash their guest index
    /// list (at most the first ProbeHashIndices indices).
    bool probe_hash_skinned = false;
    static constexpr u32 ProbeHashIndices = 16384;
    static constexpr u32 ProbeSlots = 16;
    static constexpr u32 ProbeSlotVertices = 16384;
    // bbport (r86n_glint-aim-panes, TOOL): with BB_GLASS_PICK_TRI=1 the slots from ProbeSlotsSmall up (the triangle route's)
    // hold ProbeBigSlotVertices vertices each; without it every slot holds ProbeSlotVertices as before.
    static constexpr u32 ProbeSlotsSmall = 12;
    static constexpr u32 ProbeBigSlotVertices = 131072;
    [[nodiscard]] static u32 ProbeSlotLimit(u32 slot);
    [[nodiscard]] static std::size_t ProbeSlotFirst(u32 slot);
    [[nodiscard]] static std::size_t ProbeWorldVertices();
    /// A slot's tick when its build was dropped before it was recorded (CaptureLeftOut, or the
    /// frame end came first): the rasterizer gives the slot up and asks again.
    static constexpr u64 ProbeDroppedTick = ~0ull;
    /// The build `build` (ProbeDraw::build) copies its world positions to `slot` when recorded.
    bool ProbeCopyBuild(u32 build, u32 slot);
    /// The slot's world positions (4 floats a vertex) and the tick of their copy (0: none yet;
    /// ProbeDroppedTick: never, the build was dropped).
    const float* ProbeWorld(u32 slot, u64& tick) const noexcept {
        tick = slot < ProbeSlots ? probe_ticks[slot] : 0;
        return probe_world.mapped && slot < ProbeSlots
                   ? static_cast<const float*>(probe_world.mapped) +
                         ProbeSlotFirst(slot) * 4
                   : nullptr;
    }
    void ProbeForget(u32 slot) noexcept {
        if (slot < ProbeSlots) {
            probe_ticks[slot] = 0;
        }
    }
    struct ProbeSkinned {
        u64 key = 0;
        u32 triangles = 0;
        u8 mask = 0;
    };
    struct ProbeScene {
        bool capturing = false, need_scene = false;
        u64 entries = 0, frame_entries = 0, tlas_instances = 0, blas_bytes = 0, blas_limit = 0;
        // Static camera pass entries (not moving, no skeleton, drawn by the camera pass).
        u64 static_alive = 0, static_drawn = 0, static_alive_bytes = 0, static_drawn_bytes = 0,
            static_alive_triangles = 0, static_drawn_triangles = 0;
        u64 shadow_alive = 0, shadow_drawn = 0; ///< static, sun shadow pass only
        u64 moving_alive = 0, moving_drawn = 0; ///< moving, no skeleton
        u64 skinned_alive = 0, skinned_drawn = 0, skinned_drawn_triangles = 0;
        std::vector<ProbeSkinned> skinned; ///< drawn this frame, the most triangles first
    };
    /// This frame's scene (call before OnFrameEnd).
    ProbeScene ProbeSceneNow(u32 skinned_most);
    /// The sun shadow path of this frame's Record: 0 none (the game's), 1 VSM, 2 ray traced, 3 ray
    /// traced at half resolution. The rasterizer's probe clears it at each frame end.
    u8 probe_sun_path = 0;

    // bbport (r76_sun-fog-outdoors): with BB_VOLUMETRIC_GATE_PROBE=1 (bbport (r84_live-test-knobs):
    // as at the last records write with it; emptied at the first write without it; empty otherwise)
    // the instances of the TLAS last written, in record order: index i is the instance id a ray
    // query reports (rayQueryGetIntersectionInstanceIdEXT; the custom index is r62's card slot):
    // the entry's key (Entry::base, the draw's key from PrepareDraw: the surface probe's rt_key
    // for an entry that is neither a shared copy nor a promoted instance), its triangles and the
    // record's mask (1 sun, 2 camera pass, 4 lamps, 8 lamp cards). PrepareScene writes it with the
    // records; where PrepareScene keeps the TLAS as it was, the list stays with it.
    [[nodiscard]] const std::vector<VolumetricOcclusion::GateInstance>& GateTable() const noexcept {
        return gate_table;
    }
    // bbport (r76c_sun-fog-shells): with VolumetricOcclusion::GateCaptureOn (the gate probe or the
    // shell rule) the rasterizer describes each capture draw just before PrepareDraw, which keeps it
    // on the entry the draw reached (Entry::gate_cap). GateCaptures: those of GateTable's
    // instances, in the same order (filled only with BB_VOLUMETRIC_GATE_PROBE=1).
    void SetGateCapture(const VolumetricOcclusion::GateCapture& capture) noexcept {
        gate_next = capture;
    }
    [[nodiscard]] const std::vector<VolumetricOcclusion::GateCapture>& GateCaptures() const noexcept {
        return gate_caps;
    }

private:
    struct Entry;
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
        u64 address = 0;
    };
    // bbport (r54_leaf-stage2): an entry's card UVs (BB_RT_CARD_ALPHA=1; made at its first
    // cut-out draw): the card data and state (rt_card_uv.h), its block of the pool (VMA's
    // virtual allocator; `offset` in records) and card slot (stage 4's custom index), the frame
    // of its last UV capture, whether it is in card_pending.
    BottleCaustic::Topology bottle_topology;
    Buffer bottle_corners{};
    const Entry* bottle_entry = nullptr;
    u64 bottle_entry_address = 0;
    u64 bottle_observed_frame = ~u64{0};
    u64 bottle_pass_frame = ~u64{0};
    u64 bottle_recorded_frame = ~u64{0};
    u64 bottle_index = 0;
    u64 bottle_stream = 0;
    u64 bottle_stream_bytes = 0;
    std::array<u64, 3> bottle_targets{};
    u64 bottle_resident_address = 0;
    u64 bottle_resident_capture = ~u64{0};
    u64 bottle_scene_frame = ~u64{0};
    u32 bottle_scene_ordinal = 0;
    u32 bottle_scene_mask = 0;
    std::array<float, 12> bottle_scene_view{};
    bool bottle_ambiguous = false;
    bool bottle_draw_seen = false;
    bool bottle_refused_logged = false;

    struct CardUvEntry {
        CardUv uv;
        VmaVirtualAllocation block{};
        u32 offset = 0;
        u32 slot = 0;
        u64 taken_frame = 0;
        bool pending = false;
        // bbport (r62_leaf-stage3): the card row last written for this entry's slot (CardRows)
        std::array<u32, CARD_ROW_WORDS> row{};
        bool row_written = false;
        // bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of the entry ran a pixel
        // shader without a discard (or none; its pgm_hash, 0: none): the game's sun shadow of it
        // is solid (CardNoteSunSolid; the row's CARD_ROW_SUN_SOLID). For good, as r46's rules.
        bool sun_solid = false;
        u64 sun_solid_ps = 0;
        // bbport (r63_leaf-stage4): the instance carries CARD_LAMP_MASK by its hold (CardLampOn),
        // the last frame its row had data, and whether the record last written had the bit
        bool lamp_on = false;
        u64 lamp_ready_frame = 0;
        bool lamp_written = false;
        // bbport (r62e_leaf-cards-usable): the bit came once already (a later change is a flip),
        // and the frame + 1 of the last record of a stale copy (CardStaleHoldOff; 0: never)
        bool lamp_once = false;
        u64 lamp_stale = 0;
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
        vk::DeviceSize reflection_creation_size = 0;
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
        // bbport (r62n_cutout-skinned-blocker): the most bones of a skeleton palette any draw of the entry bound (0: none read)
        u32 skeleton_bones = 0;
        bool copied = false;
        // The BLAS holds this entry's geometry (false while the scene is not being built).
        bool blas = false;
        // Unlike the current-pass mask, this survives camera-only frames of a shared entry.
        bool shadow = false;
        // The one upload to indices matched the authoritative bottle topology.
        bool bottle_index_verified = false;
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
        // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders of its last
        // camera pass draw that discards and its last sun shadow pass draw with a texture,
        // and the classes of the r46 rule PrepareScene noted them in (bit per
        // Shader::Optimization::CutoutCardClass; cleared when either shader changes)
        u64 cut_camera_ps = 0;
        u64 cut_sun_ps = 0;
        u8 cut_noted = 0;
        // bbport (r130c_glass-lamp-light): the registry entry of a glass draw of this entry (or of its sun shadow pass twin), index +
        // 1, sticky for the entry's life (0: none; always 0 while BB_GLASS_LIGHT is off); PrepareScene reads it for the record.
        u8 glass_light = 0;
        // bbport (r46b_plant-rule): the position stream of its draws (0: none), and what that
        // stream is taken for (LampLoneOf of lone_streams; Lone: a cut-out with a skeleton that
        // no sun shadow pass draws, a plant), as of lone_gen (looked up again by PrepareScene
        // only while that is not RtShadow::lone_gen).
        u64 stream = 0;
        LampLoneState lone = LampLoneState::None;
        u32 lone_gen = 0;
        // bbport (r86i_glint-find-gbuffer): the shader pair of its last camera pass draw (BB_GLASS_FIND only)
        u64 find_vs = 0, find_ps = 0;
        // bbport (r86k_glint-box-gbuffer): the last draw's index count and RtGlassFind::Flag* bits; a probe entry
        u32 find_indices = 0, find_flags = 0;
        bool box_candidate = false;
        // The mesh and shader key (see PrepareDraw) and whether this is a promoted per instance
        // entry: a static prop identified by its bone palette, not by its draw order.
        u64 base = 0;
        bool instance = false;
        // bbport (r76c_sun-fog-shells): its last draw as the capture described it (GateCaptureOn)
        VolumetricOcclusion::GateCapture gate_cap{};
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
        // bbport (r54_leaf-stage2): its card UVs (empty with BB_RT_CARD_ALPHA off, and until
        // its first cut-out draw)
        std::unique_ptr<CardUvEntry> card_uv;
    };
    InteriorRoof::WatchRow* RoofWatchEntry(const Entry& entry);

    struct Build {
        Entry* entry;
        u32 store;
        bool update;
        std::array<float, 12> to_world;
        bool fast = false; // bbport (r17_rt-upkeep): ePreferFastBuild, no eAllowUpdate
        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
        u64 vs_hash = 0;   // bbport (r62d_card-uv-diag): Draw::shader (the geometry check's line)
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
        // An affine build shares the camera-relative rows with the still signature.
        std::array<float, 2> lamp_affine_depth{};
        bool lamp_affine = false;
        bool bottle = false;
        // bbport (r54_leaf-stage2): the capture also stores the entry's card UVs at ring index
        // uv_base - 1 (0: none), for coordinates of this hash (CardCapture); uv_only: a probe
        // for the UVs alone (CardUvProbe), which r47's looks know nothing of
        u32 uv_base = 0;
        u64 uv_hash = 0;
        bool uv_only = false;
        // bbport (r64b_surface-probe-more): 1 + the probe's host slot its world positions go to
        // (ProbeCopyBuild; 0: none)
        u32 probe_slot = 0;
        u64 reflection_cookie = 0;
        u64 reflection_native_cookie = 0;
        u64 reflection_native_allocation = 0;
    };
    struct ReflectionTrack {
        ReflectionFirstHit::Identity observed{};
        ReflectionFirstHit::Identity resident{};
        u64 placement{};
        u64 address{};
        u64 cookie{};
        u64 confirmed{};
        u64 confirmed_pass{};
        u32 direct_count{};
        u32 pending{};
    };
    struct ReflectionTracker {
        ReflectionFirstHit::Pass* pass{};
        std::optional<ReflectionFirstHit::Stamp> stamp;
        std::unordered_map<const Entry*, ReflectionTrack> tracks;
        u64 allocation{}, revision{}, cookie{}, last_flushed{};
        u32 mirror_direct{}, mirror_joined{}, fireplace_direct{}, wall_shape_direct{};
        std::array<u32, ReflectionFirstHit::PlacedSourceCount> placed_direct{}, placed_joined{};
        u64 direct{}, joined{}, changed{}, dropped{}, scheduled{}, cloned{}, refused{};
        u64 ordinary_evicted{}, invalidated{}, track_limit{};
    };
    std::unique_ptr<ReflectionTracker> reflection_tracker;
    struct ReflectionNativeEntry {
        const Entry* entry{};
        u64 address{}, allocation{}, revision{}, cookie{}, captured_frame{};
        u64 confirmed_cookie{};
        ReflectionNativeProbe::Key key{};
    };
    std::array<ReflectionNativeEntry, 12> reflection_native_entries{};
    u64 reflection_native_epoch = ~u64{0};
    u64 reflection_native_allocation{}, reflection_native_revision{};
    u32 reflection_native_tracked{}, reflection_native_build_logs{};
    void ReflectionNativeObserve(const Entry&, ReflectionNativeProbe::Draw&);
    void ReflectionNativeRecordBuild(const Entry&, const Build&);
    void ReflectionObserve(Entry&, const Draw&, bool eligible);
    void ReflectionQueue(Entry&, const Draw&, Build&);
    void ReflectionDropCapture(const Build&);
    void ReflectionBuild(Entry&, const Build&);
    void ReflectionRetire(Entry&, const char* reason);
    static bool ReflectionStatic(const Entry&, ReflectionFirstHit::PlacedSource);

    bool Setup(const ObjectMotion& object_motion);
    struct BottleEndpoint {
        const Entry* entry = nullptr;
        vk::AccelerationStructureKHR blas{};
        u64 address = 0;
        u64 capture = 0;
        u64 index = 0;
        u64 stream = 0;
        u64 stream_bytes = 0;
        bool operator==(const BottleEndpoint&) const = default;
    };
    struct BottleCold;
    std::unique_ptr<BottleCold> bottle_cold;
    BottleEndpoint bottle_failed;
    BottleEndpoint bottle_scene_endpoint;
    [[nodiscard]] BottleEndpoint BottleGeneration(const Entry& entry) const;
    [[nodiscard]] bool BottleColdEligible(const Entry& entry) const;
    [[nodiscard]] u32 NominateBottleSpan(const Entry& entry, const Draw& draw,
                                        const std::array<float, 12>& to_world);
    bool MakeBottleCold(BottleCold& cold, const Entry& entry);
    void DiscardBottleCold();
    void ConsumeBottleSpan();
    void ValidateBottleCold();
    bool Make(Buffer& out, vk::DeviceSize size, bool host, VkBufferUsageFlags usage);
    void Free(Buffer& buffer);
    void Destroy(Entry& entry, const char* reason);
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
    vk::UniqueDescriptorSetLayout lamp_affine_set;
    vk::UniquePipelineLayout lamp_affine_layout;
    vk::UniquePipeline lamp_affine_pipeline;
    Buffer lamp_affine_bits;
    u64 lamp_affine_raw_hash = 0;
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
    // bbport (r76_sun-fog-outdoors): GateTable, kept only with BB_VOLUMETRIC_GATE_PROBE=1
    bool gate_table_on = false; // bbport (r84_live-test-knobs): read at every records write
    std::vector<VolumetricOcclusion::GateInstance> gate_table;
    // bbport (r76c_sun-fog-shells): GateCaptures; the next draw's description (SetGateCapture); the
    // capture draws of the frame so far that reached an entry; the shell rule (read once) and its
    // counts for the line every 600 scenes
    const bool gate_cap_on = VolumetricOcclusion::GateCaptureOn();
    const VolumetricOcclusion::GateShellRule gate_shell_rule = VolumetricOcclusion::GateShells();
    std::vector<VolumetricOcclusion::GateCapture> gate_caps;
    VolumetricOcclusion::GateCapture gate_next{};
    u64 gate_order_frame = 0;
    u32 gate_order = 0;
    u64 gate_shell_scenes = 0;
    u32 gate_shells_now = 0, gate_shells_sun = 0, gate_shell_records = 0;
    bool gate_shell_bad_said = false;
    bool r17_tlas_valid = false;
    bool r17_blas_dirty = true;
    u32 r17_tlas_age = 0;
    // bbport (r121_tlas-hang-guard): the ring sub slot of the next TLAS write of frame tlas_sub_frame
    // (tlas_subs writes recorded in it), and what the guards caught (the 600 frame line)
    u64 tlas_sub_frame = ~0ull;
    u32 tlas_subs = 0;
    struct TlasGuardCounts {
        u64 writes = 0, later_writes = 0, later_differ = 0, ring_full = 0, bad_view = 0, no_address = 0;
    } tlas_guard;
    // bbport (r121c_tlas-unbound-read): the BLAS that exist, by their Entry (filled by MakeEntry, emptied by Destroy):
    // an instance record is written only for an entry in it, whose address and handle are those it was made with
    std::unordered_map<const Entry*, u64> entry_live;
    struct TlasLiveCounts {
        u64 checked = 0, dangling = 0, moved = 0, no_handle = 0, freed_in_tlas = 0;
        bool said = false;
    } tlas_live;
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
    std::unique_ptr<InteriorRoof::Probe> roof_probe;
    u64 observed_scene_serial = 0;
    u64 window_scene_active_serial = 0;
    [[nodiscard]] WindowPathProbe::LampSceneIdentity LampPhysicalScene() const noexcept;
    WindowPathProbe::SceneObservation* window_scene_watch = nullptr;
    WindowPathProbe::PaneAcquisition* window_pane_watch = nullptr;
    bool R17ToWorld(const float* constants, bool perspective, std::array<float, 12>& out);
    struct UpkeepStats {
        u64 frames = 0, refit = 0, refit_triangles = 0, rebuilt = 0, rebuilt_triangles = 0,
            fast = 0, fast_triangles = 0, same_skipped = 0, same_skipped_triangles = 0,
            same_would = 0, same_would_triangles = 0, same_unknown = 0, far_skipped = 0,
            far_skipped_triangles = 0, far_refit = 0, far_refit_triangles = 0, tlas_built = 0,
            tlas_updated = 0, tlas_skipped = 0, world_computed = 0, world_reused = 0;
    } r17_stats;
    u64 frame = 1;
    // bbport (r83_glass-water-stage1): the window pane draws for the log (NoteGlassDraw)
    RtGlassStats glass_stats{};
    void NoteGlassDraw(const Entry& entry);
    // bbport (r86f_glass-static-panes): GlassCamera's vote (Boyer-Moore over the camera pass draws'
    // constants pointers, cleared at the frame's end) and its counts for the log
    const float* r86f_camera = nullptr;
    u32 r86f_votes = 0;
    u64 r86f_given = 0, r86f_none = 0;
    bool r86f_said = false;
    void GlassCameraVote(const float* constants);
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
    bool LampAffineTopology(const Draw& draw);
    void StillAdmit(Entry& entry, u64 id);
    void ReadStillSigs(u32 slot);
    // bbport (r54_leaf-stage2): the card UVs (BB_RT_CARD_ALPHA=1; rt_card_uv.h, CardSetup and
    // the functions after it). card_uv_on: the knob, read at Setup; card_uv_ready: the ring, the
    // stat slots and the expand pass are there (else no capture stores UVs). card_ring: the
    // captures' UVs (CardRingBytes, made at setup: its address is in the capture address blocks,
    // written once); card_ring_used: its vertices taken since the last RecordBuilds;
    // card_captures: entries given UVs this frame. card_pool: the records (CardPoolBytes, made at
    // the first card) and card_block its blocks (VMA's virtual allocator); card_pool_gen counts
    // the frees (a NoRoom entry tries again after one). card_pending: the entries expanded and
    // not yet Ready (Destroy takes an entry's out); card_frees: the blocks of destroyed entries
    // the GPU may still write. card_stat_*: the stat slots of the first entries expanded after
    // a 600-frame line (CardLog prints them); card_uv_stats: the counts since that line.
    // card_ring_clean: the first RecordBuilds filled all of the ring with CARD_UV_RING_UNSET (no
    // capture stores UVs before); card_ring_dirty: the ring's vertices UV captures no
    // RecordBuilds took wrote (filled again by the next one).
    bool card_uv_on = false;
    bool card_uv_ready = false;
    bool card_pool_failed = false;
    bool card_ring_clean = false;
    u32 card_ring_dirty = 0;
    Buffer card_ring, card_pool, card_stat_buffer, card_readback;
    VmaVirtualBlock card_block{};
    vk::UniqueDescriptorSetLayout card_set;
    vk::UniquePipelineLayout card_layout;
    vk::UniquePipeline card_pipeline;
    // bbport (r62d_card-uv-diag): card_diag: BB_RT_CARD_UV_DIAG (read at Setup). The geometry
    // check (GeoCheckSetup; on with card_diag not 0 or BB_RT_GEOMETRY_CHECK=1): geo_on when its
    // pass and buffers are there. geo_buffer: the counts its dispatches add to (zeroed at its
    // first use and after each copy); geo_readback: that copy, read by GeoCheckFrameEnd once the
    // GPU is past geo_tick (geo_pending). geo_infos: this window's checked builds by serial;
    // geo_read: those of the window whose copy is awaited. A window: 600 frames or 10 s; it is
    // copied by the RecordBuilds call that finds it due, else by GeoCheckFrameEnd on its own.
    struct GeoCheckInfo {
        u64 key;
        u64 vs_hash;
        u32 triangles;
        u32 flags;
    };
    struct GeoCheckWindow {
        u64 builds = 0, refits = 0, triangles = 0, calls = 0, frames = 0;
    };
    u32 card_diag = 0;
    bool geo_on = false;
    bool geo_clean = false;
    bool geo_pending = false;
    float geo_huge = 200.0f;
    Buffer geo_buffer, geo_readback;
    vk::UniqueDescriptorSetLayout geo_set;
    vk::UniquePipelineLayout geo_layout;
    vk::UniquePipeline geo_pipeline;
    u64 geo_tick = 0;
    u64 geo_frame = 0;
    u64 geo_time = 0; // milliseconds (steady clock)
    std::vector<GeoCheckInfo> geo_infos, geo_read;
    GeoCheckWindow geo_window, geo_read_window;
    void GeoCheckSetup();
    void GeoCheckTakeWindow(u64 now);
    void GeoCheckFrameEnd();
    void GeoCheckPrint();
    u32 card_ring_used = 0;
    u32 card_ring_peak = 0; // the most card_ring_used reached since the last 600-frame line
    u32 card_captures = 0;
    u32 card_pool_gen = 0;
    u32 card_pool_blocks = 0;
    u64 card_pool_used = 0;
    CardSlots card_slots;
    std::vector<Entry*> card_pending;
    std::vector<CardFree> card_frees;
    struct CardStatInfo {
        u64 base = 0; // Entry::base
        u64 ps_hash = 0;
        u32 triangles = 0;
        CardClass card_class = CardClass::Static;
        bool camera = false;
        // (r62b) the entry (only compared with what `entries` holds when the line is printed,
        // for its class then) and the selector the capture stored by
        const Entry* entry = nullptr;
        u32 selector = 0;
    };
    std::array<CardStatInfo, CARD_UV_STAT_SLOTS> card_stat_info{};
    u32 card_stat_used = 0;
    u64 card_stat_tick = 0;
    // The "drawn by both passes" lines printed (CardNoteDraw prints the first CardBothLines).
    static constexpr u32 CardBothLines = 32;
    u32 card_both_said = 0;
    // bbport (r62b_leaf-stage3-followups): the keys the once-only card lines printed (both
    // passes, a second reference dword not 0, a sun shadow pass draw without a cut-out:
    // CardSaidKey), so an entry made again after it streamed out is not printed again; and how
    // many of the two new kinds were printed (each at most CardBothLines).
    std::unordered_set<u64> card_said;
    u32 card_ref2_said = 0;
    u32 card_solid_said = 0;
    struct CardUvStats {
        u64 draws = 0, valid = 0, captures = 0, uv_probes = 0, expanded = 0,
            expanded_triangles = 0, dropped = 0, other_draw = 0, budget = 0, no_room = 0,
            left_out = 0, coordinates = 0, constants = 0;
        u64 sun_gave_way = 0; // camera pass cards that replaced a stale or gone sun one (R4-a, R4-b)
        std::array<u64, std::size_t(CardMiss::Count)> miss{};
    } card_uv_stats;
    bool CardSetup();
    bool CardMakePool();
    bool CardTakeBlock(Entry& entry);
    void CardNoteDraw(Entry& entry, const Draw& draw);
    void CardNoteSunSolid(Entry& entry, const Draw& draw); // bbport (r62b)
    [[nodiscard]] const char* CardClassNow(const Entry& entry) const noexcept; // bbport (r62b)
    bool CardCaptureCan(Entry& entry, const Draw& draw);
    void CardCaptureTake(Entry& entry, const Draw& draw, Build& build);
    bool CardCapture(Entry& entry, const Draw& draw, Build& build);
    u32 CardUvProbe(Entry& entry, const Draw& draw);
    void CardRelease(Entry& entry);
    void CardFrameEnd();
    void CardLog();
    // bbport (r62e_leaf-cards-usable): cut-out shadows (true shape) made safe to turn on
    // (rt_card_still.h). CardStillFor: whether an entry of the lamp card set is a still cut-out,
    // counted in card_safe_now (the last record write); card_safe: the counts since the last
    // CardSafeLog line. The guard (CardGuardSetup; BB_RT_CARD_ALPHA on, BB_RT_CARD_SAFE not 0):
    // rt_card_guard.comp over the builds of entries with card data; card_guard: its counts and flags
    // (host visible); card_guard_last: its counts at the last line.
    struct CardSafeCounts {
        u64 refused_skinned = 0, refused_moving = 0, first_on = 0, flips = 0, guarded = 0,
            unguarded = 0;
    };
    struct CardSafeScene {
        u32 still = 0, skinned = 0, moving = 0, stale_off = 0;
    };
    CardSafeCounts card_safe;
    CardSafeScene card_safe_now;
    CardSkinnedScene card_skinned_now; // bbport (r62n_cutout-skinned-blocker): the last scene's lone skinned cut-outs by the rule
    bool card_skinned_said = false;
    bool card_guard_on = false;
    Buffer card_guard;
    std::array<u32, 4> card_guard_last{};
    vk::UniqueDescriptorSetLayout guard_set;
    vk::UniquePipelineLayout guard_layout;
    vk::UniquePipeline guard_pipeline;
    [[nodiscard]] static bool CardSafeOn();
    bool CardStillFor(Entry& entry, bool stale);
    void CardGuardSetup();
    void CardSafeLog();
    void CardSkinnedLog(); // bbport (r62n_cutout-skinned-blocker)
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2 with its layers made (card_layers_on, set by
    // SetCardLayers at the rasterizer's start): the card table (card_rows, CardRowsBytes, made at
    // the first PrepareScene with them; CardRows), the layers to fill before a reader
    // (card_layers), the row counts since CardAlpha's last line.
    bool card_layers_on = false;
    bool card_rows_failed = false;
    CardAlpha* card_layers = nullptr;
    Buffer card_rows;
    CardRowCounts card_row_counts;
    bool CardRowsMake();
    void CardRows();
    // bbport (r63_leaf-stage4): the instances written with CARD_LAMP_MASK into the TLAS last
    // written (and of them plants and moving ones), the counts since the last line, the last
    // frame a lamp pass could bind a CARDS build (NoteCardLampUser), and the mask's hold
    // (CardLampHold)
    u32 card_lamp_instances = 0, card_lamp_plants = 0, card_lamp_moving = 0;
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT: the window pane records in the TLAS last
    // written (and of them those carried from the frame before), the frames whose waiting captures
    // OnFrameEnd built for a pane since the last line, the keys (of `entries`) of the pane entries
    // drawn this frame and of those drawn last frame (CollectHeld carries them into the scene), and
    // the counters' values at Record's last line
    u32 glass_instances = 0, glass_carried = 0, glass_late = 0;
    std::vector<u64> glass_drawn, glass_carry;
    RtGlassStatic::SeenMap glass_seen; // bbport (r121b_glass-pane-hang): what the pane judge knows of each pane key
    std::array<u32, RtGlassLightWords> r86_last{};
    // bbport (r86b_glass-visible): the frame whose PrepareScene last wrote the TLAS records, and
    // its camera (GlassScene)
    u64 glass_frame = 0;
    std::array<float, 12> glass_view{};
    // bbport (r86i_glint-find-gbuffer): the box (x0, y0, x1, y1 of the 1920x1080 picture) and whether it is
    // valid, the live knobs generation it was read at, the frame its report is due (0: none), and the mesh
    // keys the box rule took (glass_box_count of them)
    std::array<s32, 4> glass_box_px{};
    bool glass_box_valid = false;
    u32 glass_box_gen = 0xffffffffu;
    u64 glass_box_due = 0;
    std::array<u64, 64> glass_box_keys{};
    u32 glass_box_count = 0;
    // bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PANES as the last listing read it, the probe entries made in
    // the frame `glass_cand_frame`, and the keys of probe meshes judged outside the box
    bool glass_box_take = false;
    u64 glass_cand_frame = 0;
    u32 glass_cand_used = 0;
    std::array<u64, 128> glass_box_rejected{};
    u32 glass_box_rejected_count = 0;
    // bbport (r86l_glint-pick-glass, TOOL): the mesh keys the glass pick took, and the knobs' generation it was read at
    std::array<u64, 32> glass_pick_keys{};
    u32 glass_pick_count = 0;
    u32 glass_pick_gen = 0xffffffffu;
    // bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route's state (made at the first want), the number of wants
    // that wait for a capture or a copy, and the triangle set MakeEntry keeps for the pane entry it makes now (null: all)
    std::unique_ptr<RtGlassTri::State> glass_tri;
    std::unique_ptr<LampPaneProbe> lamp_pane;
    u32 lamp_pane_generation = ~0u, lamp_pane_last_request = 0;
    void ReportLampPane(const LampPaneProbe& probe);
    u32 glass_tri_active = 0;
    const std::vector<u32>* glass_tri_keep_now = nullptr;
    void GlassTriCopy(Entry& entry, u64 key, u32 build);
    void GlassTriFrameEnd();
    [[nodiscard]] const std::vector<u32>* GlassTriKeep(u64 key) const;
    CardLampCounts card_lamp_counts;
    u64 card_lamp_user_frame = 0;
    bool card_lamp_user_seen = false;
    bool CardLampOn(Entry& entry);
    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT. glass_light_mode: 0 off, 1 made (GlassLightStart); glass_light_live: the live
    // knob decides each frame (glass_light_now); glass_light_records_now: glass records the last scene's TLAS got. glass_geo: the
    // meshes of registry hits ({geometry, indices, index count | entry + 1 << 32}), for the shadow pass twins.
    struct GlassLightCounts {
        u64 window_start = 0, records = 0, twins = 0, kept_cards = 0, passes = 0, passes_glass = 0, live_off = 0, off_frame = 0;
    };
    u8 glass_light_mode = 0;
    bool glass_light_live = false, glass_light_now = false;
    u32 glass_light_records_now = 0;
    GlassLightCounts glass_counts;
    bool glass_clear_now = false; // bbport (r131c_cabinet-glass-clear)
    u64 glass_clear_records = 0;
    std::array<std::array<u64, 3>, 64> glass_geo{};
    u32 glass_geo_n = 0;
    void GlassLightStart();
    bool GlassLightFrame(bool card_lamps);
    void GlassLightNote(Entry& entry, const Draw& draw);
    // bbport (r130g_glass-light-forward): the forward panes and the glass counter. glass_fwd: the 600-frame line's counts.
    // glass_rays_now/last: the lamp pass's glass counter words (PointShadow::OnFrameEnd, GlassRaysSeen): [0] counted passes, then
    // half_counts words GLASS_RAY_FIRST and on (asked, met, tinted, met beyond the old end, entries, view x y z bits, pane mm).
    struct GlassFwdCounts {
        u64 window_start = 0, placed_taken = 0, placed_unsteady = 0, placed_cap = 0, moving_left = 0, carried = 0;
    };
    GlassFwdCounts glass_fwd;
    std::array<u32, 10> glass_rays_now{}, glass_rays_last{};
    bool glass_rays_early = false;
    GlassLight::SteadyMap glass_steady;
    u32 glass_placed_frame_n = 0;
    u64 glass_placed_frame = 0;
    void GlassForwardStart();
    void GlassForwardFrame();
    void GlassRaysText(char* out, std::size_t size, const std::array<u32, 10>& now, const std::array<u32, 10>& last) const;
    bool GlassPlacedSteady(u64 instance);
    /// A TLAS instance's custom index: its card slot once the slot's row is written, else 0.
    [[nodiscard]] u32 CardCustomIndex(const Entry& entry) const noexcept {
        return card_layers_on && entry.card_uv && entry.card_uv->row_written ? entry.card_uv->slot
                                                                             : 0u;
    }
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
    // bbport (r86_glass-light-stage2a): with BB_RT_GLASS_LIGHT on the counters hold
    // RtGlassLightWords words more, from RtGlassLightFirstWord (rt_shadow.comp's GLASS_LIGHT
    // builds)
    static_assert(RtGlassLightFirstWord >= R25Slots);
    static_assert(CardSunFirstWord >= R25Slots); // bbport (r128c_lrt-cutout-props)
    static u32 R25Words() {
        // bbport (r128c_lrt-cutout-props): BB_RT_CARD_SUN=1 (not made with BB_RT_GLASS_LIGHT): the counters hold CardSunWords words more, from
        // CardSunFirstWord
        // bbport (r131a_foliage-translucency): the FOLIAGE builds add CARD_SUN_FOLIAGE_WORDS words after the CARDS ones
        return RtGlassLightOn() ? RtGlassLightCounterWords
               : CardSunWanted() ? CardSunCounterWords + (FoliageTranslucency::SunThrough() ? u32(CARD_SUN_FOLIAGE_WORDS) : 0u)
                                 : R25Slots;
    }
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
    // bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN=1 (needs BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1; not with BB_RT_GLASS_LIGHT): the sun's
    // rays cross the cut-out cards as the lamp rays do (rt_shadow.comp's CARDS builds, rt_shadow_cards_comp and its half form, made when first
    // wanted by CardSunNow). CardSunNow also tells the scene that a reader of the cards exists (NoteCardLampUser), and returns the build for this
    // sun trace with the card tables, or nothing (the plain build is pushed as before).
    struct CardSunUse {
        vk::Pipeline pipeline;
        vk::PipelineLayout layout;
        vk::Buffer rows, pool, info;
        vk::ImageView layers;
        vk::Sampler sampler;
        // bbport (r131a_foliage-translucency): the FOLIAGE build: the colour layers (binding 10) and the hue image (binding 11, cleared first)
        bool foliage = false;
        vk::ImageView colour, hue;
        vk::Image hue_image;
    };
    [[nodiscard]] static bool CardSunWanted();
    [[nodiscard]] CardSunUse CardSunNow(bool half);
    vk::UniqueDescriptorSetLayout card_sun_set, card_sun_half_set;
    vk::UniquePipelineLayout card_sun_layout, card_sun_half_layout;
    vk::UniquePipeline card_sun_pipeline, card_sun_half_pipeline;
    bool card_sun_tried = false, card_sun_half_tried = false;
    u32 card_sun_cards = 0, card_sun_plain = 0; ///< sun traces since the last line that ran the cut-out build / the plain one
    std::array<u32, CardSunWords> card_sun_last{}; ///< the counters' values at the last line
    // bbport (r131a_foliage-translucency): the sun trace's hue image (RGBA8, the trace's size, made by MakeSunHue only with the light through leaves on
    // for the sun), the frame the trace last wrote it, and the FOLIAGE counters at the last line
    vk::Image sun_hue_image;
    VmaAllocation sun_hue_allocation{};
    vk::ImageView sun_hue_view;
    u32 sun_hue_width = 0, sun_hue_height = 0;
    u64 sun_hue_frame = 0;
    std::array<u32, 4> foliage_sun_last{};
    bool MakeSunHue(u32 width, u32 height);
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

    // bbport (r64b_surface-probe-more): see ProbeTakeDraw. probe_world: ProbeSlots slots of
    // ProbeSlotVertices world positions (made at the first ProbeCopyBuild), probe_ticks: the tick of
    // each slot's copy (0: not recorded).
    ProbeDraw probe_draw;
    Buffer probe_world;
    bool probe_world_failed = false;
    std::array<u64, ProbeSlots> probe_ticks{};
    /// A build the probe asked a copy of is dropped before it is recorded.
    void ProbeDropped(const Build& build) noexcept {
        if (build.probe_slot != 0 && build.probe_slot <= ProbeSlots) {
            probe_ticks[build.probe_slot - 1] = ProbeDroppedTick;
        }
    }
};

}
