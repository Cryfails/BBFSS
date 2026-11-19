// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_reflection_ordinal3.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_bottle_caustic.h"
#include "../../../../tools/engine/sha256.h"

#include <algorithm>
#include <bit> // bbport (r54_leaf-stage2)
#include <chrono> // bbport (r62d_card-uv-diag)
#include <cmath>
#include <cstddef> // bbport (r47_still-check): offsetof
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <span>

#include <fmt/format.h>
#include <xxhash.h>

#include "common/scope_exit.h"
#include "bbport_sections.h"
#include "bbport_settings.h"
#include "bbport_sun_cascades.h"
#include "bbport_toggles.h"
#include "bbport_wind_hang_probe.h" // bbport (r112b_hang-probe, TOOL)
#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)
#include "shader_recompiler/runtime_info.h"
#include "video_core/host_shaders/bottle_cold_validate_comp.h"
#include "video_core/host_shaders/rt_shadow_coverage_comp.h"
#include "video_core/host_shaders/rt_shadow_filter_r25_comp.h" // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_glass_comp.h"      // bbport (r86_glass-light-stage2a)
#include "video_core/host_shaders/rt_shadow_half_glass_comp.h" // bbport (r86_glass-light-stage2a)
#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)
#include "video_core/host_shaders/rt_card_uv_comp.h"           // bbport (r54_leaf-stage2)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/rt_unproject_lamp_affine_comp.h"
#include "video_core/host_shaders/rt_geometry_check_comp.h" // bbport (r62d_card-uv-diag)
#include "video_core/host_shaders/rt_card_guard_comp.h" // bbport (r62e_leaf-cards-usable)
#include "video_core/host_shaders/rt_shadow_cards_comp.h"      // bbport (r128c_lrt-cutout-props)
#include "video_core/host_shaders/rt_shadow_half_cards_comp.h" // bbport (r128c_lrt-cutout-props)
#include "video_core/host_shaders/rt_shadow_cards_foliage_comp.h"      // bbport (r131a_foliage-translucency)
#include "video_core/host_shaders/rt_shadow_half_cards_foliage_comp.h" // bbport (r131a_foliage-translucency)
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
#include "video_core/renderer_vulkan/bottle_cold_spans.h"
#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)
#include "video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e_leaf-cards-usable)
#include "engine/engine_state.h" // bbport (r62n_cutout-skinned-blocker) TOOL: the hunter's position for the blocker lines
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // bbport (r62n_cutout-skinned-blocker): the test tools' (r84) live knobs, when present
#define BB_R62N_LIVE_KNOBS 1
#endif
#include "video_core/renderer_vulkan/lamp_fog_shafts.h"  // bbport (r80_lamp-fog-shafts)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)
#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)
#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle, TOOL)
#include "video_core/renderer_vulkan/vk_lamp_pane_probe.h"
#include "bbport_test_camera.h"
#include "video_core/renderer_vulkan/glass_light.h" // bbport (r130c_glass-lamp-light)
#include "video_core/renderer_vulkan/vk_interior_roof_probe.h"
#include "video_core/renderer_vulkan/vk_window_path_scene.h"
#include "video_core/renderer_vulkan/vk_window_path_pane_acquisition.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r86f_glass-static-panes): the test tools' live knobs (branch dev/test-tools) when the build has
// them: BB_GLASS_STATIC_PANES is then asked again at every use; without them it is always on.
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h"
#define BB_GLASS_STATIC_LIVE 1
#else
#define BB_GLASS_STATIC_LIVE 0
#endif

namespace Vulkan {
namespace {
constexpr u32 MaxParams = 8192;
static_assert(1 + 4 * MaxParams == Shader::MotionVectors::CaptureParamsCapacity);
constexpr u32 MaxPositions = 8u << 20;
constexpr u32 MaxInstances = 8192;
// bbport (r76_sun-fog-outdoors): the sun gate's probe takes every instance's mask
static_assert(VolumetricOcclusion::GateProbeInstancesMost >= MaxInstances);
constexpr u32 MaxInstancesPerDraw = 64;
constexpr u32 MaxTrianglesPerBlas = 2u << 20;
constexpr u32 NewTrianglesPerFrame = 200000;
constexpr u32 RebuiltTrianglesPerFrame = 300000;
constexpr u32 RebuildEveryFrames = 120;
constexpr u32 RebuildSpread = 32;
constexpr u64 UnusedFrames = 240;
constexpr u64 KeptFrames = 2;
// bbport (r14_cascade_rt): a cascade drawn once every `period` frames leaves its casters undrawn
// for period - 1 frames in a row; they stay in the scene HoldMarginFrames longer: one for a frame
// with no shadow pass at all inside such a gap (the game's schedule does not advance), one for
// frames still arriving under a longer period after the game thread published a shorter one.
// The window only bounds frames in which a cascade is not drawn at all: a cascade drawn without
// an entry drops it at once. Periods above MaxHoldPeriod are held as MaxHoldPeriod.
constexpr u64 HoldMarginFrames = 2;
constexpr u32 MaxHoldPeriod = 16;
// The game culls its sun shadow casters to its own short cascades; the virtual shadow map reaches
// further, so static casters keep drawing from their world copies long after the game stops
// submitting them (about an hour at 60 fps); the entry memory cap evicts the oldest first.
constexpr u64 VsmKeepFrames = 60ull * 60 * 60;
// A prop seen unchanged (same mesh, same bone palette) on this many distinct frames gets an
// entry of its own; candidates not seen for CandidateFrames are dropped.
constexpr u32 PromoteFrames = 3;
constexpr u64 CandidateFrames = 120;
constexpr std::size_t MaxCandidates = 32768;
// Captured geometry shares video memory with the texture cache, which evicts (and stalls) long
// before the driver budget runs out, so the geometry gets its own cap.
constexpr u64 MaxEntryBytes = 1536ull << 20;
constexpr vk::DeviceSize ScratchBytes = 192ull << 20;
constexpr VkBufferUsageFlags InputUsage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR;
constexpr u8 ShadowMask = 1, CameraMask = 2;
// bbport: what lamp rays hit (point_shadow_ray.comp). A ray cannot test a texture, so a cut-out
// card (a leaf on a vine) shadows as its whole polygon: rectangles of shadow on the ground. The
// cards stay out and cast no lamp shadow, as in the game; skinned meshes keep theirs (cloth).
// bbport (r46_lamp-cards): a card is known by any draw of it that ever showed a cut-out: a sun
// shadow pass draw with a texture, or a camera pass draw with a discarding pixel shader, its
// own or another draw of the same mesh (Entry::card_shadow, card_camera, card_mesh; LampCard in
// rt_lamp_cards.h). Before, only by the texture of a sun shadow pass draw that was the entry's
// first of a frame, and only while the entry did not count as moving (Entry::shadow_card): the
// plants kept their lamp bit. That rule is still the one with experiment LampCardsOldBit set or
// BB_RT_LAMP_CARDS=0.
constexpr u8 LampMask = 4;
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: a plant's or a static cut-out's card with data
// (CardLampOn), traced by the lamp rays as its texels say (point_shadow_ray.comp's CARDS builds
// trace LampMask | CardLampMask; the instance is built FORCE_NO_OPAQUE). Every other ray traces
// with the opaque ray flag and a mask without this bit, or 0xff with that flag: as before.
constexpr u8 CardLampMask = 8;
static_assert(CardLampMask == CARD_LAMP_MASK && (CardLampMask & (ShadowMask | CameraMask | LampMask)) == 0);
static_assert(LampMask == GLASS_GLINT_LAMP_MASK); // bbport (r86b_glass-visible): its shadow rays
// bbport (r46_lamp-cards, r46b_plant-rule): BB_RT_LAMP_CARDS, read once (default
// LampCardLevelDefault, 3; at most LampCardLevelMost, 3). 0: the rule of before. 1: cut-outs
// without a skeleton stay out of lamp rays. 2: every cut-out stays out, skinned ones too (hair
// and cloth then cast no lamp shadow). 3: as 1, and of the skinned cut-outs those whose vertices
// no sun shadow pass draws (Entry::lone): the plants that threw the rectangles are drawn with a
// skeleton, and the game gives them no sun shadow, while it gives one to every character.
// bbport (r46b_plant-rule): position streams known at most (lone_streams), and the frames a
// stream that is not lone stays known undrawn once the map is full.
constexpr std::size_t LoneStreamsMost = 16384;
constexpr u64 LoneStreamKeep = 600;
u32 LampCardLevel() {
    static const u32 level = ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_CARDS"),
                                              LampCardLevelDefault, LampCardLevelMost);
    return level;
}
// bbport (r47_still-check): the knobs of the looks at casters held for still (rt_still_check.h),
// each read once. BB_RT_STILL: on (the default), count (the looks and the 600-frame line, but
// nothing is counted as moving: the picture and every structure as before, with the proof in the
// log) or off. BB_RT_STILL_BUDGET: triangles a frame looked at again in turn (default
// StillBudget, 60,000; at most StillBudgetMost; 0: none). BB_RT_STILL_EARLY: the same for the
// first look after a build, and once more for the other early looks (the first StillEarlyChecks;
// default StillEarly, 100,000). A caster whose turn finds its budget used up waits for the next
// frame. So that those drawn first do not take the budget again at every period while those
// drawn last wait for good, a look in turn does not come again before every caster looked at in
// turn could have had its own at the budget (StillCrowd of still_pool_last): where a scene
// holds more casters than the budget lets through at the usual pace, all of them are looked
// at, more rarely. (bbport (r47c_review-fixes): at first only the casters DUE on the frame
// before were counted, a few frames' worth, which put nothing off.) And a look in turn that
// has waited BB_RT_STILL_OVERDUE frames (StillOverdueFrames below) is served from a second
// budget of the same size: a caster that only every 8th frame draws (a far sun cascade's)
// found the first one used up by those drawn before it every time, and in the game such looks
// waited without end. The caster that
// crosses a budget is still looked at. BB_RT_STILL_TOLERANCE: metres its bounds may differ by
// (default StillTolerance, 0.004; StillToleranceLeast to StillToleranceMost).
// BB_RT_STILL_MOVERS: the most triangles of living casters the looks count as moving, which are
// refit at every draw (default StillMovers, 400,000; at most StillMoversMost; 0: none is taken).
u32 StillMode() {
    static const u32 mode = ReadStillMode(std::getenv("BB_RT_STILL"));
    return mode;
}
u32 StillLane(bool early) {
    static const u32 turn =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_BUDGET"), StillBudget, StillBudgetMost);
    static const u32 first =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_EARLY"), StillEarly, StillBudgetMost);
    return early ? first : turn;
}
float StillLimit() {
    static const float limit = ReadStillTolerance(std::getenv("BB_RT_STILL_TOLERANCE"));
    return limit;
}
u32 StillMoverCap() {
    static const u32 cap =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_MOVERS"), StillMovers, StillMoversMost);
    return cap;
}
// bbport (r47b_casters): BB_RT_STILL_LIST=<n>, read once (default 0: no list; at most 1024): a
// diagnostic. Under the still check's 600-frame line, one line "still mover:" for every caster a
// look found moving since the last line (up to n, each caster once with its farthest move):
// mesh, key, triangles, how far, on how many looks, both boxes and their sizes, its class
// (an instance's own entry or known by draw order; palette none, by its bytes or by its address;
// skinned or not), the pass of the capture, taken as moving or not. Needs BB_RT_STILL=count or
// on. A far move with an unchanged box size is one caster captured at two instances' places.
// bbport (r47c_review-fixes): BB_RT_STILL_OVERDUE=<frames>, read once (default StillOverdue, 64;
// at most StillOverdueMost; 0: no second budget, as before): a look in turn that has waited this
// long for a budget that is used up when its draw comes is served from a second budget of the
// same size (rt_still_check.h, StillLaneOf).
u32 StillOverdueFrames() {
    static const u32 frames =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_OVERDUE"), StillOverdue, StillOverdueMost);
    return frames;
}
constexpr u32 StillListCap = 1024;
u32 StillListMost() {
    static const u32 most = ReadCopyTurnKnob(std::getenv("BB_RT_STILL_LIST"), 0, StillListCap);
    return most;
}
// BB_RT_LAMP_LEAVE, read once (default 0: nothing; at most StillLeaveMost): a diagnostic that
// tells which kind of caster throws a lamp shadow. Lamp rays leave out the instances of the
// classes it names (StillLeaveClasses: 1 not drawn by the camera pass, 2 held for a sun cascade,
// 4 shared copies, 8 instances' own entries, 16 held for still by draw order, 32 moving and not
// shared, 64 r46's cut-out cards). It acts whatever BB_RT_STILL and the experiment bits say.
u32 LampLeave() {
    static const u32 classes =
        ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_LEAVE"), 0, StillLeaveMost);
    return classes;
}
// bbport (r41_lamp-shadows): a moving copy of a mesh drawn more than once in a pass (a "shared"
// entry, see PrepareDraw) is never refit, only rebuilt, within RebuiltTrianglesPerFrame and in
// draw order. Where a frame's copies hold more triangles than that, the same ones go without
// every frame: they keep the pose of their last build and stay in the scene, beside the live
// copy of the same mesh. A lamp ray then finds two casters, the second one displaced: a second
// hard shadow. Such a copy is left out of lamp rays (Entry::lamp_out) once it was drawn and went
// without more than LampStaleSkips times in a row, and comes back once it was rebuilt on
// LampFreshBuilds draws in a row: a copy at the edge of the budget does not blink in and out
// (and each change of an instance's mask makes the TLAS a full build). Counted in draws that
// went without, not in the age of the BLAS: a copy the far cascades hold undrawn
// (graphics_sun_far_shadows) ages without being starved and keeps its lamp shadow. A copy whose
// draw is known to read what its BLAS was built from (Draw::inputs, with BB_RT_UNCHANGED set)
// holds the right pose and stays in. The sun's rays keep every copy, as before. Experiment
// LampRepairOffBit set: all stay in lamp rays (the counting goes on).
// bbport (r43_copy-turns): "the same ones go without every frame" was the budget's first-come
// rule, and is repaired where it arose: the copies take turns (rt_copy_turns.h; CopyTurnsOn
// below), and a moving copy that is drawn every frame is rebuilt before it was drawn more than
// CopyWait() frames in a row without. With turns on a copy therefore counts as starved only
// past that many draws (LampStaleAfter), and no longer at the first rebuild that came in time
// (no more draws than that went without since the rebuild before): a copy that takes turns is
// never rebuilt on LampFreshBuilds draws in a row. One whose turns come too late every time
// (more copies than two budgets a frame keep within the bound) stays starved between them: it
// does not change sides at every turn, and neither does its instance's mask. With
// BB_RT_COPY_WAIT=0 no bound is asked for, and a copy counts as starved only past
// CopyTurnWaitMost draws. With BbCopyTurns::OldBit set both rules are as r41 made them.
constexpr u32 LampStaleSkips = 2;
constexpr u32 LampFreshBuilds = 3;
// bbport (r42_lamp-soft): BB_LAMP_SHADOW_STALE, read once. 1: such copies are left out of lamp
// rays, as r41 did. 0, the default: they stay in, as before r41. Nothing here shows that a
// starved copy is never the only caster a lamp ray would find where it stands (the live copy
// "beside it" is another draw of the same mesh, not known to be the same object), and in the
// game the band the rule was aimed at stayed with 18 copies left out. The counting goes on
// either way, and the 600-frame line names the copies.
bool LampStaleOut() {
    static const bool out =
        ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); }).stale;
    return out;
}

// bbport: experiment mask 256 (a diagnostic): copies of a mesh drawn more than once in a pass
// ("shared" entries, see PrepareDraw) are built once and then not refreshed, which shows what
// their refresh costs and whether anything visibly depends on it.
// bbport (r43_copy-turns): BB_RT_COPY_BUDGET, read once: the triangles of shared copies rebuilt
// a frame (default RebuiltTrianglesPerFrame, at most CopyTurnBudgetMost; 0: none, as experiment
// 256). A tool to prove a picture fault on the budget: far above what a scene's copies hold,
// every copy is rebuilt on every draw.
u32 RebuiltBudget() {
    static const u32 budget = ReadCopyTurnKnob(std::getenv("BB_RT_COPY_BUDGET"),
                                               RebuiltTrianglesPerFrame, CopyTurnBudgetMost);
    return BbToggle::Experiment(256) ? 0u : budget;
}
// bbport (r43_copy-turns): experiment BbCopyTurns::OldBit clear = the shared copies take turns
// at being rebuilt, the oldest build first (rt_copy_turns.h); set = the first in draw order
// take the budget, as before. Read at each use.
bool CopyTurnsOn() {
    return !BbToggle::Experiment(BbCopyTurns::OldBit);
}
// BB_RT_COPY_WAIT, read once: the most frames in a row a moving copy that is drawn every frame
// goes without a rebuild; past that its turn comes whatever the budget says, up to two budgets
// a frame (default CopyTurnWait, 4; at most CopyTurnWaitMost; 0: no turn goes past the budget,
// and the wait is what the budget gives).
u32 CopyWait() {
    static const u32 wait =
        ReadCopyTurnKnob(std::getenv("BB_RT_COPY_WAIT"), CopyTurnWait, CopyTurnWaitMost);
    return wait;
}
// Draws in a row without a rebuild past which a moving copy counts as starved (LampStaleSkips).
// With turns on: the bound the turns keep, never fewer than r41's 2; with no bound asked for
// (BB_RT_COPY_WAIT=0, the wait is what the budget gives) the longest that can be asked for.
u32 LampStaleAfter() {
    if (!CopyTurnsOn()) {
        return LampStaleSkips;
    }
    return CopyWait() != 0 ? std::max(LampStaleSkips, CopyWait()) : CopyTurnWaitMost;
}

// bbport: only the sun VSM reads the casters' world copies (Record's VSM branch, the kept
// casters and their eviction guard). With it off they are neither allocated nor filled: no
// copyBuffer per build, no copy barrier, no buffer per caster. Experiment mask 16777216 restores
// the copies whatever the VSM setting.
bool WorldCopies() {
    return BbToggle::Experiment(16777216) ||
           BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed);
}
// Builds recorded, world copies recorded (and their bytes), sun shadow builds whose copy was not
// made, since the last "Ray tracing world copies:" line.
struct WorldCopyStats {
    u64 builds = 0, copies = 0, bytes = 0, skipped = 0, skipped_bytes = 0;
    u64 printed_frame = 0;
};
WorldCopyStats world_copy_stats;

// bbport (r17_rt-upkeep): experiment 4398046511104 set = the old upkeep (TLAS built in full every
// frame without eAllowUpdate, shared copies rebuilt for fast tracing, ToWorld for every draw, the
// opt-ins off). Read at each use.
bool UpkeepOn() {
    return !BbToggle::Experiment(4398046511104ull);
}
// BB_RT_UNCHANGED: 0 off (default), 1 count, 2 skip.
u32 UnchangedMode() {
    static const u32 mode = [] {
        const char* env = std::getenv("BB_RT_UNCHANGED");
        if (!env) {
            return 0u;
        }
        return std::strcmp(env, "skip") == 0 ? 2u : std::strcmp(env, "count") == 0 ? 1u : 0u;
    }();
    return mode;
}
// BB_RT_REFIT_EVERY: 2..16, else 0 (off). bbport (r37_menu-options): set, it decides; not set,
// lantern.ini's graphics_rt_far_refit does (8 on, 0 off), read at each use. Turned on while the
// game runs, the near draws of the frame before were not booked (r19_far_book): a caster whose far
// draw comes first can miss one refit in that one frame.
constexpr u32 FarRefitSetting = 8;
u32 RefitEvery() {
    static const s32 env_every = [] {
        const char* env = std::getenv("BB_RT_REFIT_EVERY");
        if (!env || !env[0]) {
            return -1;
        }
        const u32 n = u32(std::strtoul(env, nullptr, 10));
        return n >= 2 && n <= 16 ? s32(n) : 0;
    }();
    if (env_every >= 0) {
        return u32(env_every);
    }
    return BbSettings::Get().graphics_rt_far_refit.load(std::memory_order_relaxed) ? FarRefitSetting
                                                                                  : 0u;
}
// bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE, a measuring probe of ray tracing upkeep, off
// unless set: "blas" 1 (BLAS refits and builds left out), "tlas" 2 (the TLAS traced as last
// built), "all" 3 (both); else 0. Read once.
u32 UpkeepProbeMode() {
    static const u32 mode = [] {
        const char* env = std::getenv("BB_RT_UPKEEP_FREEZE");
        if (!env) {
            return 0u;
        }
        const u32 m = std::strcmp(env, "all") == 0    ? 3u
                      : std::strcmp(env, "tlas") == 0 ? 2u
                      : std::strcmp(env, "blas") == 0 ? 1u
                                                      : 0u;
        if (m == 0) {
            std::printf("Ray tracing upkeep probe (r26): BB_RT_UPKEEP_FREEZE=%s not understood "
                        "(all, blas or tlas): off\n",
                        env);
        }
        return m;
    }();
    return mode;
}
// Frames in a row with casters in the ray tracing scene before the probe acts (scene built).
constexpr u64 R26AfterFrames = 300;
// Experiment bit set = the probe does nothing (normal upkeep); read at each frame end.
constexpr u64 R26ProbeOffBit = 2251799813685248ull; // 1 << 51
// TLAS refits in a row before a full build.
constexpr u32 TlasRefitsBetweenBuilds = 30;
// bbport (r121_tlas-hang-guard): TLAS writes of one frame that each have a ring slot of their own
// (instance_data holds 4 frames x TlasSubSlots slots of MaxInstances records)
constexpr u32 TlasSubSlots = 3;
// bbport (r121_tlas-hang-guard): BB_RT_TLAS_GUARD, default 1; 0 = as before (read once)
bool TlasGuardOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_TLAS_GUARD");
        const bool value = !env || std::strcmp(env, "0") != 0;
        std::printf("Ray tracing scene guard (r121): BB_RT_TLAS_GUARD %s: a TLAS write of a frame has "
                    "its own instance ring slot (up to %u a frame), a view that is not finite or past "
                    "1e5 and a record without a BLAS address are left out\n",
                    value ? "on" : "0 (off, the ring slot of a frame shared by its writes)", TlasSubSlots);
        return value;
    }();
    return on;
}
// bbport (r121_tlas-hang-guard): the 12 floats every record takes as its transform: NaN fails both tests
template <class View>
bool TlasViewSane(const View& view) {
    for (const float v : view) {
        if (!(v <= 1e5f && v >= -1e5f)) {
            return false;
        }
    }
    return true;
}
static_assert(sizeof(vk::AccelerationStructureInstanceKHR) == 64);

struct TracePush {
    u32 buf_off;
    u32 frame_index;
    std::array<float, 2> size;
    u32 rays;
    float light_tan;
    float bias_m;
    float max_distance;
    s32 far_radius; // rt_shadow.comp COVERAGE_SKIP: the filter's radius, < 0 traces every pixel
    u32 r25_flags;  // bbport (r25_rt-sun-trace): R25Exact | R25Count | R25HalfFirst | R25HalfFill
    // bbport (r131a_foliage-translucency): the FOLIAGE builds' T, hue mix and floor (rt_shadow.comp). The other builds' blocks end at r25_flags; the
    // range pushed is wider, which is allowed.
    float pass_share, pass_tint, pass_floor;
    u32 pass_pad;
};
static_assert(sizeof(TracePush) == 56);

struct FilterPush {
    u32 buf_off;
    s32 radius;
    std::array<float, 2> size;
    u32 r25_flags; // bbport (r25_rt-sun-trace): R25Exact | R25Count (rt_shadow_filter.comp R25)
};
static_assert(sizeof(FilterPush) == 20);

// bbport (r25_rt-sun-trace): experiment bit: set = the old sun trace and filter paths (read at
// every sun trace). Push constant bits, as in rt_shadow.comp and rt_shadow_filter.comp.
constexpr u64 R25SunTraceOffBit = 1125899906842624ull;
constexpr u32 R25Exact = 1, R25Count = 2, R25HalfFirst = 4, R25HalfFill = 8;

struct UnprojectPush {
    std::array<float, 12> rows;
    u32 first;
    u32 count;
};
static_assert(sizeof(UnprojectPush) == 56);

struct BottleValidatePush {
    std::array<float, 12> view;
    u32 ordinal;
    u32 mask;
};
static_assert(sizeof(BottleValidatePush) == 56);
constexpr u32 BottleCornerBytes = BottleCaustic::BottleCorners * 16;
constexpr u32 BottlePositionBytes = BottleCaustic::ColdVertices * 16;
constexpr u32 BottleParamBytes = (BottleCaustic::ColdSpans.size() + 1) * 32;

constexpr u32 LampAffineVertices = 10796;
constexpr u32 LampAffineBitWords = (LampAffineVertices + 31) / 32;
constexpr u64 LampAffineTopologyHash = 0x8a4174f8bb90a2ccull;

struct LampAffinePush {
    std::array<float, 12> legacy, relative;
    std::array<float, 3> origin;
    u32 first, count, vertices;
    float a, b;
};
static_assert(sizeof(LampAffinePush) == 128 && offsetof(LampAffinePush, relative) == 48 &&
              offsetof(LampAffinePush, origin) == 96 && offsetof(LampAffinePush, first) == 108 &&
              offsetof(LampAffinePush, count) == 112 && offsetof(LampAffinePush, vertices) == 116 &&
              offsetof(LampAffinePush, a) == 120 && offsetof(LampAffinePush, b) == 124);

bool LampAffineProjection(const float* projection) {
    const auto finite = [](float value) { return std::isfinite(value); };
    return std::ranges::all_of(std::span{projection, 16}, finite) &&
           projection[0] != 0.f && projection[5] != 0.f && projection[11] < 0.f &&
           projection[1] == 0.f && projection[2] == 0.f && projection[3] == 0.f &&
           projection[4] == 0.f && projection[6] == 0.f && projection[7] == 0.f &&
           projection[8] == 0.f && projection[9] == 0.f &&
           projection[12] == 0.f && projection[13] == 0.f &&
           projection[14] == 1.f && projection[15] == 0.f;
}

// bbport (r47_still-check): rt_still_sig.comp's push constants: what takes a capture's clip
// space positions to world space (StillClipToWorld), the mesh's first vertex in `positions`,
// the address of its triangle list, its indices, its signature's place.
struct StillPush {
    std::array<float, 12> rows;
    std::array<float, 3> origin;
    u32 first;
    u64 indices;
    u32 count;
    u32 slot;
};
static_assert(sizeof(StillPush) == 80 && offsetof(StillPush, first) == 60 &&
              offsetof(StillPush, indices) == 64 && offsetof(StillPush, slot) == 76);

// bbport (r54_leaf-stage2): what the capture's vertex shader stores (emit_spirv_special.cpp,
// EmitCardUvStore: the stride, the selector's fields) is what the expand pass reads.
static_assert(Shader::MotionVectors::CaptureUvStride == CARD_UV_RING_BYTES &&
              Shader::MotionVectors::CaptureUvUnset == CARD_UV_RING_UNSET);
// bbport (r62b_leaf-stage3-followups): the fourth value a vertex, and the stat slot's words
static_assert(Shader::MotionVectors::CaptureUvOther(0) == 1 &&
              Shader::MotionVectors::CaptureUvOther(1) == 0 &&
              Shader::MotionVectors::CaptureUvOther(3) == 0 && CARD_UV_RING_FLOATS == 4 &&
              CARD_UV_STAT_RAW + 2 * CARD_UV_STAT_RAW_CORNERS == CARD_UV_STAT_WORDS);
static_assert(PackCardSelector({31, 3, 3, 31, 3, true}) == 0x8001ffffu &&
              PackCardSelector({1, 0, 0, 0, 0, false}) == 0x80000001u &&
              PackCardSelector({0, 1, 0, 0, 0, false}) == 0x80000020u &&
              PackCardSelector({0, 0, 1, 0, 0, false}) == 0x80000080u &&
              PackCardSelector({0, 0, 0, 1, 0, false}) == 0x80000200u &&
              PackCardSelector({0, 0, 0, 0, 1, false}) == 0x80004000u);
// bbport (r54_leaf-stage2): a sun shadow pass card is preferred for r14's longest hold window
// (a cascade the game skips leaves its casters undrawn that long; rt_card_uv.h, CardSunFrames).
static_assert(CardSunFrames == u64(MaxHoldPeriod) - 1 + HoldMarginFrames);

// The key of an instance's own entry (see PrepareDraw): its mesh key and its bone palette.
u64 InstanceKey(u64 key, u64 palette) {
    return XXH3_64bits_withSeed(&palette, sizeof(palette), key ^ 0xa24baed4963ee407ull);
}

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;

// bbport (r62d_card-uv-diag): rt_geometry_check.comp's push constants and its counts (words 0
// triangles, 1 index out of range, 2 not finite, 3 over "huge", 4 over "big", 5 longest edge's
// bits, 6 records written, 8.. GeoCheckRecords records of 4 words: serial, out of range or not
// finite, over "huge", longest edge's bits), and its knobs (each read once).
struct GeoCheckPush {
    u64 indices;
    u32 store;
    u32 triangles;
    u32 vertex_count;
    u32 serial;
    float huge;
    float big;
};
static_assert(sizeof(GeoCheckPush) == 32 && offsetof(GeoCheckPush, store) == 8 &&
              offsetof(GeoCheckPush, big) == 28);
constexpr u32 GeoCheckRecords = 32;
constexpr u32 GeoCheckWords = 8 + 4 * GeoCheckRecords;
constexpr u32 GeoCheckInfosMost = 1u << 16; // builds named in one window (serial past: unnamed)
constexpr u32 GeoCheckLines = 8;            // "bad build" lines a window
constexpr u64 GeoCheckFrames = 600;
constexpr u64 GeoCheckMs = 10000;
constexpr float GeoCheckEdgeDefault = 200.0f;
// bbport (r62e_leaf-cards-usable): rt_card_guard.comp's push constants (rt_card_guard_layout.h)
struct CardGuardPush {
    u64 indices;
    u32 store;
    u32 triangles;
    u32 vertex_count;
    u32 slot;
    u32 mode;
    float edge;
    u32 key_lo;
    u32 key_hi;
};
static_assert(sizeof(CardGuardPush) == 40 && offsetof(CardGuardPush, mode) == 24 &&
              offsetof(CardGuardPush, key_hi) == 36);

static bool GeoCheckKnob() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_GEOMETRY_CHECK");
        return env && std::strcmp(env, "1") == 0;
    }();
    return on;
}

static float GeoCheckEdge() {
    static const float edge = [] {
        const char* env = std::getenv("BB_RT_GEOMETRY_CHECK_EDGE");
        if (!env || env[0] == '\0') {
            return GeoCheckEdgeDefault;
        }
        char* end = nullptr;
        const double metres = std::strtod(env, &end);
        return end && *end == '\0' && metres >= 1.0 && metres <= 100000.0 ? float(metres)
                                                                          : GeoCheckEdgeDefault;
    }();
    return edge;
}

static u64 GeoCheckNowMs() {
    return u64(std::chrono::duration_cast<std::chrono::milliseconds>(
                   std::chrono::steady_clock::now().time_since_epoch())
                   .count());
}

// The counts to the host (after the check's dispatches) and back to 0 (before the next ones).
static void GeoCheckFlush(vk::CommandBuffer cmdbuf, vk::Buffer counts, vk::Buffer readback) {
    constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
    constexpr auto ShaderAccess = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
    constexpr vk::DeviceSize geo_bytes = GeoCheckWords * 4;
    EffectPass::MemoryBarrier(cmdbuf, Compute, ShaderAccess, Transfer,
                              vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
    cmdbuf.copyBuffer(counts, readback, vk::BufferCopy{0, 0, geo_bytes});
    EffectPass::MemoryBarrier(cmdbuf, Transfer,
                              vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite,
                              Transfer | vk::PipelineStageFlagBits2::eHost,
                              vk::AccessFlagBits2::eTransferWrite | vk::AccessFlagBits2::eHostRead);
    cmdbuf.fillBuffer(counts, 0, geo_bytes, 0);
    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                              ShaderAccess);
}

std::array<float, 16> Invert(const float* m, bool& ok) {
    std::array<double, 32> t{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            t[r * 8 + c] = m[r * 4 + c];
        }
        t[r * 8 + 4 + r] = 1.0;
    }
    ok = false;
    std::array<float, 16> out{};
    for (int p = 0; p < 4; ++p) {
        int best = p;
        for (int r = p + 1; r < 4; ++r) {
            if (std::abs(t[r * 8 + p]) > std::abs(t[best * 8 + p])) {
                best = r;
            }
        }
        if (std::abs(t[best * 8 + p]) < 1e-12) {
            return out;
        }
        for (int c = 0; c < 8; ++c) {
            std::swap(t[p * 8 + c], t[best * 8 + c]);
        }
        const double scale = 1.0 / t[p * 8 + p];
        for (int c = 0; c < 8; ++c) {
            t[p * 8 + c] *= scale;
        }
        for (int r = 0; r < 4; ++r) {
            if (r != p) {
                const double f = t[r * 8 + p];
                for (int c = 0; c < 8; ++c) {
                    t[r * 8 + c] -= f * t[p * 8 + c];
                }
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            out[r * 4 + c] = float(t[r * 8 + 4 + c]);
        }
    }
    ok = true;
    return out;
}

template <class Index>
bool AppendTriangles(std::span<const Index> source, bool strip, bool restart, u32 lo,
                     std::vector<u32>& out) {
    const Index cut = std::numeric_limits<Index>::max();
    const auto emit = [&](u32 a, u32 b, u32 c) {
        if (a != b && b != c && a != c) {
            out.insert(out.end(), {a - lo, b - lo, c - lo});
        }
    };
    if (!strip) {
        for (std::size_t i = 0; i + 2 < source.size(); i += 3) {
            if (restart && (source[i] == cut || source[i + 1] == cut || source[i + 2] == cut)) {
                return false;
            }
            emit(source[i], source[i + 1], source[i + 2]);
        }
        return true;
    }
    u32 run = 0;
    u32 a = 0, b = 0;
    for (const Index index : source) {
        if (restart && index == cut) {
            run = 0;
            continue;
        }
        if (run >= 2) {
            emit(a, b, index);
        }
        a = b;
        b = index;
        ++run;
    }
    return true;
}
}

struct RtShadow::BottleCold {
    BottleEndpoint endpoint;
    Buffer positions{};
    Buffer params{};
    Buffer capture_addresses{};
    Buffer both_addresses{};
    Buffer order{};
    Buffer corners{};
    Buffer result{};
    vk::UniqueDescriptorPool address_pool;
    vk::DescriptorSet capture_set;
    vk::DescriptorSet both_set;
    vk::UniqueDescriptorSetLayout validate_set;
    vk::UniquePipelineLayout validate_layout;
    vk::UniquePipeline validate_pipeline;
    std::array<u64, BottleCaustic::ColdSpans.size()> sample_frames{};
    UnprojectPush unproject{};
    u64 result_tick = 0;
    u32 spans = 0;
    bool recorded_span = false;
    bool ready = false;
};

RtShadow::RtShadow(const Instance& instance_, Scheduler& scheduler_, CameraMotion& camera_motion_,
                   const ObjectMotion& object_motion)
    : instance{instance_}, scheduler{scheduler_}, camera_motion{camera_motion_} {
    if (InteriorExposure::RoofEvidenceWanted()) {
        roof_probe = std::make_unique<InteriorRoof::Probe>(instance, scheduler);
    }
    if (!BbSettings::Get().startup_effects[BbSettings::EffectRayTracing]) {
        return;
    }
    if (!instance.IsRayQuerySupported()) {
        std::printf("Ray tracing: off - this GPU or driver has no ray query\n");
        return;
    }
    if (!instance.GetPhysicalDevice().getFeatures().vertexPipelineStoresAndAtomics) {
        std::printf("Ray tracing: off - no vertex shader stores\n");
        return;
    }
    if (!camera_motion.Enabled()) {
        std::printf("Ray tracing: off - the camera is not tracked (BB_UPSCALER=none)\n");
        return;
    }
    if (const char* env = std::getenv("LANTERN_RT_SCENE_MB"); env && env[0]) {
        blas_limit = u64(std::clamp(std::strtoul(env, nullptr, 10), 64ul, 4096ul)) << 20;
    }
    if (const char* env = std::getenv("LANTERN_RT_SHADOW_RAYS"); env && env[0]) {
        rays = std::clamp(u32(std::strtoul(env, nullptr, 10)), 1u, 16u);
    }
    // bbport (r37_menu-options): set, BB_RT_SUN_HALF decides ("1" on, else off); not set,
    // graphics_rt_sun_half does (R25HalfWanted, at every sun trace).
    if (const char* env = std::getenv("BB_RT_SUN_HALF"); env && env[0]) {
        r25_half_env = env[0] == '1' ? 1 : 0;
    }
    if (r25_half_env == 1) { // bbport (r25_rt-sun-trace)
        std::printf("Ray traced sun (r25): BB_RT_SUN_HALF=1, one ray per 2x2 block first, then "
                    "full-resolution rays where those differ (changes the picture)\n");
    }
    capturing = Setup(object_motion);
    if (capturing) {
        const char* affine = std::getenv("BB_RT_LAMP_PANE_AFFINE");
        if (affine && std::strcmp(affine, "1") == 0) {
            using enum vk::DescriptorType;
            EffectPass::Create(instance, lamp_affine_set, lamp_affine_layout, lamp_affine_pipeline,
                               {eStorageBuffer, eStorageBuffer}, sizeof(LampAffinePush),
                               RT_UNPROJECT_LAMP_AFFINE_COMP, "Ray tracing lamp affine positions");
        }
        std::printf("Ray tracing: on, sun %u rays a pixel, lamps and bounced light\n", rays);
        // bbport (r83_glass-water-stage1): BB_RT_GLASS's state (rt_glass.h), said once
        static_assert((RtGlassMask & (ShadowMask | CameraMask | LampMask | CardLampMask)) == 0);
        const RtGlassKnob& glass = RtGlass();
        if (!glass.on) {
            const char* text = std::getenv("BB_RT_GLASS");
            const bool named = text && text[0] && !(text[0] == '0' && text[1] == '\0');
            std::printf("Ray tracing glass (r83): BB_RT_GLASS off%s%.80s%s: window panes stay out of "
                        "the ray traced scene, as before\n",
                        named ? " (its text \"" : "", named ? text : "",
                        named ? "\" names no shader pair vs:ps, hex, at most 8)" : "");
        } else {
            char list[RtGlassPairsMost * 36 + 1] = {};
            std::size_t used = 0;
            for (u32 i = 0; i < glass.count && used < sizeof(list); ++i) {
                const int n = std::snprintf(list + used, sizeof(list) - used, "%s%llx:%llx",
                                            i ? "," : "",
                                            static_cast<unsigned long long>(glass.pairs[i].vs),
                                            static_cast<unsigned long long>(glass.pairs[i].ps));
                used += n > 0 ? std::size_t(n) : 0;
            }
            std::printf("Ray tracing glass (r83): BB_RT_GLASS on, %s pairs %s: their forward draws "
                        "go into the ray traced scene as window panes under instance mask 0x%x "
                        "alone, which no ray traces yet; bounced light leaves it out (the picture "
                        "is as before)\n",
                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));
        }
        // bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto and BB_GLASS_FIND, said once
        if (glass.on && glass.automatic) {
            std::printf("Ray tracing glass (r86g): BB_RT_GLASS=auto: a forward draw alpha blended on colour target 0 with depth write on and %u to %u indices (BB_GLASS_AUTO_MIN, BB_GLASS_AUTO_INDICES), a pixel shader that reads a texture and does not discard, drawn inside the scene's frame (r86h: not the HUD), is a window pane (a skinned one is left out); no shader pair list\n",
                        RtGlassAutoMin(), RtGlassAutoIndices());
        }
        if (RtGlassFind::On()) {
            std::printf("Ray tracing glass find (r86g): BB_GLASS_FIND=1: forward blended and listed shader pairs and what became of their pane draws are logged at frames 300, 600 ... 1800, then every 1800\n");
        }
        // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT's state (rt_glass_light.h), said once
        // when the variable is set
        if (const char* text = std::getenv("BB_RT_GLASS_LIGHT");
            text && text[0] && !(text[0] == '0' && text[1] == '\0')) {
            const RtGlassLightMode light = RtGlassLight();
            if (light != RtGlassLightMode::Off) {
                std::printf("Ray tracing glass light (r86): BB_RT_GLASS_LIGHT=%s: %s; where a "
                            "pixel's sun ray reaches the sun, one more ray asks the window panes "
                            "(instance mask 0x%x alone, at most %u triangles), only while panes are "
                            "in the scene; a frame's pane captures are built at its end and its "
                            "panes are carried into the next frame's scene\n",
                            RtGlassLightName(light),
                            light == RtGlassLightMode::View
                                ? "the view, half the sun per pane triangle crossed (a debug "
                                  "look, no colour)"
                            : light == RtGlassLightMode::Probe
                                ? "the picture is as before; counted frames also ask whether a "
                                  "shadowed pixel's blocker is a pane's own copy in the sun's scene"
                                : "the picture is as before (counted only)",
                            unsigned(RtGlassMask), unsigned(RtGlassLightCap));
            } else {
                std::printf("Ray tracing glass light (r86): BB_RT_GLASS_LIGHT=%.40s off (%s)\n",
                            text,
                            ParseRtGlassLight(text) == RtGlassLightMode::Off
                                ? "not understood: 1, view or probe"
                                : "it needs BB_RT_GLASS on");
            }
        }
    } else {
        std::printf("Ray tracing: off - setup failed\n");
    }
    GlassLightStart(); // bbport (r130c_glass-lamp-light): reads BB_GLASS_LIGHT once; unset: nothing
    GlassForwardStart(); // bbport (r130g_glass-light-forward): its once line, only with BB_GLASS_LIGHT on
}

namespace {
const char* LampReconstructionIndices(LampPaneProbe& p) {
    auto& r = *p.reconstruction;
    using namespace RtLampPane;
    if ((r.index_size != 2 && r.index_size != 4) || r.strip || r.restart ||
        r.indices != DrawIndices || r.instances != Instances ||
        p.indices.size() != std::size_t(DrawIndices) * Instances ||
        p.triangles != DrawIndices || s64(r.raw_min) + s32(p.base_vertex) != r.entry_first) {
        return "unsupported index normalization";
    }
    const std::span first{p.indices.data(), DrawIndices};
    if (*std::ranges::min_element(first) != 0) {
        return "first RT slice is not normalized by minimum";
    }
    for (u32 i = 0; i < first.size(); ++i) {
        const u32 index = first[i];
        if (index >= p.vertices || p.indices[DrawIndices + i] != index + p.vertices ||
            p.indices[2 * DrawIndices + i] != index + 2 * p.vertices) {
            return "RT instance index slices disagree";
        }
    }
    if constexpr (std::endian::native != std::endian::little) {
        return "index fingerprint requires little-endian host";
    }
    r.fingerprint = XXH64(first.data(), first.size_bytes(), 0);

    std::size_t count = 0;
    for (std::size_t t = 0; t < r.triplets.size(); ++t) {
        const auto at = LampReconstruction::Slice * DrawIndices + 3 * LampReconstruction::Ordinals[t];
        for (std::size_t k = 0; k < r.triplets[t].size(); ++k) {
            const u32 index = p.indices[at + k];
            if (index / p.vertices != LampReconstruction::Slice) {
                return "corner is outside its diagnostic instance";
            }
            r.triplets[t][k] = index;
            const auto known_end = r.expanded.begin() + count;
            if (std::find(r.expanded.begin(), known_end, index) == known_end) {
                if (count == r.expanded.size()) {
                    return "more than nine distinct diagnostic vertices";
                }
                r.expanded[count++] = index;
            }
        }
    }
    return count == r.expanded.size() ? nullptr : "fewer than nine distinct diagnostic vertices";
}

void LampReconJsonString(std::string& line, const char* text) {
    if (!text) {
        line += "null";
        return;
    }
    line.push_back('"');
    for (const unsigned char c : std::string_view(text)) {
        if (c == '"' || c == '\\') line.push_back('\\');
        if (c < 0x20) fmt::format_to(std::back_inserter(line), "\\u{:04x}", unsigned(c));
        else line.push_back(char(c));
    }
    line.push_back('"');
}

void ReportLampReconstruction(const LampPaneProbe& p, const char* failure,
                              const char* pick_status, const char* pick_reason,
                              bool corners_emitted = false) {
    if (!p.reconstruction) return;
    const auto& r = *p.reconstruction;
    const auto& id = p.capture;
    const auto& phases = p.material.phases;
    const char* why = failure ? failure : r.refusal;
    if (!why && (!p.mapped || !p.allocation || !r.projection_saved || !r.viewport_after ||
                 !id.request || id.request != p.request.id || !id.scene || !id.rt || !id.draw || !id.build ||
                 id.image == std::numeric_limits<u32>::max() || !id.uid || !p.key || !p.param ||
                 !r.clip_tick || r.clip_tick != p.world_tick || !p.depth_tick ||
                 p.material.refusal || !phases.Complete(id) ||
                 phases.before_tick > phases.after_tick || phases.after_tick > p.depth_tick)) {
        why = "incomplete reconstruction identity, viewport or phase ordering";
    }
    if (!why && r.affine && (!r.vertex_stage_key || !r.raster_key_matched)) {
        why = "delivered raster stage or motion flags not stable across A/B";
    }
    const auto finite = [](std::span<const float> values) {
        return std::ranges::all_of(values, [](float v) { return std::isfinite(v); });
    };
    if (!why && (!finite(r.projection) || !finite(r.inverse_view) || !finite(r.rows) ||
                 !finite(r.viewport) || !finite(r.jitter) || !finite(p.camera.view) ||
                 !finite(p.camera.inverse) || !finite(p.camera.proj) ||
                 r.viewport[2] <= 0.f || r.viewport[3] == 0.f ||
                 r.viewport[4] < 0.f || r.viewport[4] > 1.f ||
                 r.viewport[5] < 0.f || r.viewport[5] > 1.f)) {
        why = "nonfinite or unsupported reconstruction projection";
    }
    std::array<std::array<float, 4>, LampReconstruction::Slots> clip{}, world{};
    std::array<float, 2> b{}, c{};
    if (!why) {
        for (std::size_t i = 0; i < r.expanded.size(); ++i) {
            if (r.expanded[i] >= r.count || u64(r.expanded[i] + 1) * 16 > p.WorldBytes()) {
                why = "reconstruction staging vertex is out of range";
                break;
            }
            std::memcpy(clip[i].data(), p.mapped + p.ClipOffset() + i * 16, 16);
            std::memcpy(world[i].data(), p.mapped + u64(r.expanded[i]) * 16, 16);
            if (!finite(clip[i]) || !finite(world[i]) || world[i][3] != 1.f) {
                why = "nonfinite clip/world or incorrect output W";
                break;
            }
        }
        if (!why) {
            using namespace RtLampPane;
            for (u32 i = 0; i < b.size(); ++i) {
                std::memcpy(&b[i], p.mapped + p.WorldBytes() + MaterialOffset(MaterialPhase::After, 3, i), 4);
                std::memcpy(&c[i], p.mapped + p.WorldBytes() + i * 4, 4);
            }
            const auto d32 = [](float v) { return v >= 0.f && v <= 1.f; };
            if (!std::ranges::all_of(b, d32) || !std::ranges::all_of(c, d32)) {
                why = "invalid reconstruction depth values";
            }
        }
    }

    std::string line;
    line.reserve(4096);
    fmt::format_to(std::back_inserter(line),
        "Lamp reconstruction (t132d): {{\"schema\":\"t132d-lamp-reconstruction-v{}\","
        "\"capture_status\":\"{}\",\"identity\":{{\"request\":{},\"scene\":{},\"rt\":{},"
        "\"draw\":{},\"build\":{},\"key\":\"{:016x}\",\"param\":{},\"present\":null}},"
        "\"depth_attachment\":{{\"index\":{},\"uid\":{}}},"
        "\"ticks\":{{\"a\":{},\"b\":{},\"c\":{},\"world\":{},\"clip\":{}}},"
        "\"resource_generation\":null,\"reason\":",
        r.affine ? 2 : 1, why ? "invalid" : "valid", p.request.id, id.scene, id.rt, id.draw,
        id.build, p.key, p.param,
        id.image, id.uid, phases.before_tick, phases.after_tick, p.depth_tick, p.world_tick, r.clip_tick);
    LampReconJsonString(line, why);
    line += ",\"pick\":{\"status\":";
    LampReconJsonString(line, pick_status);
    line += ",\"reason\":";
    LampReconJsonString(line, pick_reason);
    fmt::format_to(std::back_inserter(line), ",\"corners_v1_emitted\":{}}}", corners_emitted);
    if (!why) {
        const auto words = [&](std::span<const float> values) {
            line.push_back('[');
            for (std::size_t i = 0; i < values.size(); ++i) {
                fmt::format_to(std::back_inserter(line), "{}\"{:08x}\"", i ? "," : "",
                               std::bit_cast<u32>(values[i]));
            }
            line.push_back(']');
        };
        fmt::format_to(std::back_inserter(line),
            ",\"mesh\":{{\"pair\":\"6a833138:bb10e440\",\"indices\":{},\"instances\":{},"
            "\"index_size\":{},\"strip\":{},\"restart\":{},\"first_index\":{},\"base_vertex\":{},"
            "\"first_instance\":{},\"entry_first\":{},\"raw_min\":{},\"vertices_per_instance\":{},"
            "\"index_fingerprint\":\"{:016x}\"}},\"unproject\":{{\"first\":{},\"count\":{},\"rows\":",
            r.indices, r.instances, r.index_size, r.strip, r.restart, p.first_index, s32(p.base_vertex),
            p.first_instance, r.entry_first, r.raw_min, p.vertices, r.fingerprint, r.first, r.count);
        words(r.rows);
        if (r.affine) {
            line += ",\"representation\":\"affine\",\"relative_rows\":";
            words(r.relative_rows);
            line += ",\"origin\":";
            words(r.origin);
            fmt::format_to(std::back_inserter(line),
                           ",\"vertex_stage_key\":\"{:016x}\",\"raster_motion_flags\":{}",
                           r.vertex_stage_key, r.raster_motion_flags);
        }
        line += "},\"draw_projection\":";
        words(r.projection);
        line += ",\"draw_inverse_view\":";
        words(r.inverse_view);
        line += ",\"pass_view\":";
        words(p.camera.view);
        line += ",\"pass_inverse_view\":";
        words(p.camera.inverse);
        line += ",\"pass_projection\":";
        words(p.camera.proj);
        line += ",\"viewport\":";
        words(r.viewport);
        line += ",\"jitter\":";
        words(r.jitter);
        fmt::format_to(std::back_inserter(line),
            ",\"scissor\":[{},{},{},{}],\"request_extent\":[{},{}],\"raster\":[{},{}],"
            "\"requested_texels\":[[{},{}],[{},{}]],\"native_texels\":[[{},{}],[{},{}]],\"depth_b\":",
            r.scissor.offset.x, r.scissor.offset.y, r.scissor.extent.width, r.scissor.extent.height,
            p.request.width, p.request.height, p.width, p.height, p.request.pixels[0].x,
            p.request.pixels[0].y, p.request.pixels[1].x, p.request.pixels[1].y, p.samples[0].x,
            p.samples[0].y, p.samples[1].x, p.samples[1].y);
        words(b);
        line += ",\"depth_c\":";
        words(c);
        line += ",\"triplets\":[";
        for (std::size_t i = 0; i < r.triplets.size(); ++i) {
            fmt::format_to(std::back_inserter(line), "{}{{\"local\":{},\"expanded\":[{},{},{}]}}",
                           i ? "," : "", LampReconstruction::Ordinals[i],
                           r.triplets[i][0], r.triplets[i][1], r.triplets[i][2]);
        }
        line += "],\"vertices\":[";
        for (std::size_t i = 0; i < r.expanded.size(); ++i) {
            fmt::format_to(std::back_inserter(line), "{}{{\"expanded\":{},\"clip\":",
                           i ? "," : "", r.expanded[i]);
            words(clip[i]);
            line += ",\"world\":";
            words(world[i]);
            if (r.affine) {
                // These nine indices are referenced by the captured triangles. The clip and
                // world words let the reader independently check the actual shader output.
                const float expected = std::fma(r.projection[10], clip[i][3], r.projection[11]);
                const auto key = [](float v) {
                    const u32 bits = std::bit_cast<u32>(v);
                    return (bits & 0x80000000u) ? 0u - bits : bits ^ 0x80000000u;
                };
                const auto [z, fma_z] = std::pair{key(clip[i][2]), key(expected)};
                const u32 steps = std::max(z, fma_z) - std::min(z, fma_z);
                fmt::format_to(std::back_inserter(line), ",\"clip_contract\":{}",
                               clip[i][3] > 0.f && std::isfinite(expected) && steps <= 1);
            }
            line.push_back('}');
        }
        line.push_back(']');
    }
    line += "}\n";
    std::fwrite(line.data(), 1, line.size(), stdout);
}
} // namespace

RtShadow::~RtShadow() {
    if (lamp_pane && !lamp_pane->reported) {
        ReportLampReconstruction(*lamp_pane, "shutdown before a completed report", "not-evaluated", nullptr);
    }
    if (!tried) {
        return;
    }
    DiscardBottleCold();
    scheduler.Finish();
    vsm.reset();
    const auto device = instance.GetDevice();
    for (auto& [key, entry] : entries) {
        device.destroyAccelerationStructureKHR(entry->handle);
        Free(entry->storage);
        Free(entry->indices);
        Free(entry->world);
    }
    if (tlas) {
        device.destroyAccelerationStructureKHR(tlas);
    }
    Free(bottle_corners);
    Free(lamp_affine_bits);
    Free(r25_counts); // bbport (r25_rt-sun-trace)
    Free(r25_readback);
    Free(probe_world); // bbport (r64b_surface-probe-more)
    if (lamp_pane) {
        lamp_pane->Free(instance.GetAllocator(), scheduler);
    }
    Free(still_sigs); // bbport (r47_still-check)
    Free(still_readback);
    Free(geo_buffer); // bbport (r62d_card-uv-diag)
    Free(geo_readback);
    // bbport (r54_leaf-stage2): the card UVs' buffers and blocks (the GPU is done: Finish above)
    if (card_block) {
        vmaClearVirtualBlock(card_block);
        vmaDestroyVirtualBlock(card_block);
    }
    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback, &card_rows,
                      &card_guard}) { // bbport (r62e_leaf-cards-usable): card_guard
        Free(*b);
    }
    if (raw_view) {
        device.destroyImageView(raw_view);
    }
    if (raw_image) {
        vmaDestroyImage(instance.GetAllocator(), raw_image, raw_allocation);
    }
    if (sun_hue_view) { // bbport (r131a_foliage-translucency)
        device.destroyImageView(sun_hue_view);
    }
    if (sun_hue_image) {
        vmaDestroyImage(instance.GetAllocator(), sun_hue_image, sun_hue_allocation);
    }
    for (Buffer* b : {&capture_addresses, &both_addresses, &params, &positions, &scratch,
                      &instance_data, &tlas_storage, &tlas_scratch}) {
        Free(*b);
    }
}

LampPaneProbe* RtShadow::ActiveLampPane() const noexcept {
    return lamp_pane && !lamp_pane->refusal && !lamp_pane->sealed ? lamp_pane.get() : nullptr;
}

namespace {
void ReportLampIndexLineage(const LampPaneProbe& p, VmaAllocator allocator) {
    if (!p.lineage) return;
    const auto& lineage = *p.lineage;
    const auto& cfg = Round2ProbeSettings::Get();
    const auto& selected = p.material.phases;
    const char* why = lineage.refusal;
    u64 raw_hash = 0;
    u64 invalidate_ns = 0, hash_ns = 0, index_write_ns = 0;
    if (!why && (p.refusal || !p.Captured() || !p.mapped || !lineage.tick || !lineage.after ||
                 !selected.Complete(p.capture) || selected.before_tick != lineage.tick ||
                 selected.after_tick < lineage.tick)) {
        why = "incomplete_bound_index_witness";
    }
    if (!why) {
        const u64 start = Round2CostStart(cfg.cost);
        const auto result = vmaInvalidateAllocation(allocator, p.allocation, 0, VK_WHOLE_SIZE);
        invalidate_ns = Round2CostElapsed(start);
        if (result != VK_SUCCESS) why = "bound_index_invalidate";
    }
    if (!why) {
        const auto* bytes = p.mapped + p.LineageOffset();
        const auto size = LampIndexLineage::Bytes;
        const u64 hash_start = Round2CostStart(cfg.cost);
        raw_hash = XXH64(bytes, size, 0);
        hash_ns = Round2CostElapsed(hash_start);
        char path[1024];
        const int n = std::snprintf(path, sizeof(path), "%s/%s-index-%u.u16", cfg.directory, cfg.session, p.request.id);
        const bool valid_path = n > 0 && size_t(n) < sizeof(path);
        const u64 write_start = Round2CostStart(cfg.cost && valid_path);
        auto* out = valid_path ? std::fopen(path, "wbx") : nullptr;
        if (!out) {
            why = "bound_index_output_open";
        } else {
            const auto wrote = std::fwrite(bytes, 1, size, out);
            if (std::fclose(out) || wrote != size) why = "bound_index_output_write";
        }
        index_write_ns = Round2CostElapsed(write_start);
    }
    const auto print = [](u64 x) { return static_cast<unsigned long long>(x); };
    if (cfg.cost) {
        std::printf("Round2 cost: {\"schema\":\"round2-host-cost-v1\",\"kind\":\"index\",\"op\":\"retire\","
                    "\"session\":\"%s\",\"pid\":%d,\"request\":%u,\"scene\":%llu,\"rt\":%llu,\"tick\":%llu,"
                    "\"invalidate_ns\":%llu,\"hash_ns\":%llu,\"index_write_ns\":%llu,"
                    "\"index_payload_bytes\":%u,\"lineage_enabled\":true,\"status\":\"%s\"}\n",
                    cfg.session, Round2ProbeSettings::Pid(), p.request.id, print(p.capture.scene),
                    print(p.capture.rt), print(lineage.tick), print(invalidate_ns), print(hash_ns),
                    print(index_write_ns), LampIndexLineage::Bytes, why ? why : "ok");
    }
    std::printf("Round2 index: {\"schema\":\"round2-bound-index-v1\",\"session\":\"%s\",\"pid\":%d,"
                "\"status\":\"%s\",\"reason\":\"%s\",\"request\":%u,\"scene\":%llu,\"rt\":%llu,"
                "\"draw\":%u,\"build\":%u,\"param\":%u,\"depth_id\":%u,\"depth_uid\":%llu,"
                "\"pair\":\"6a833138:bb10e440\",\"source_offset\":%llu,\"source_capacity\":%llu,"
                "\"count\":%u,\"index_bytes\":%u,\"raw_u16_xxh64\":\"%016llx\","
                "\"cached_normalized_u32_xxh64\":\"%016llx\",\"index_tick\":%llu,\"after_tick\":%llu,"
                "\"first_index\":%u,\"base_vertex\":%d,\"first_instance\":%u}\n",
                cfg.session, Round2ProbeSettings::Pid(), why ? "invalid" : "ok", why ? why : "retired_actual_bind_span",
                p.request.id, print(p.capture.scene), print(p.capture.rt), p.capture.draw, p.capture.build,
                p.param, p.capture.image, print(p.capture.uid), print(lineage.before.offset), print(lineage.before.capacity),
                RtLampPane::DrawIndices, LampIndexLineage::Bytes, print(raw_hash),
                print(p.reconstruction ? p.reconstruction->fingerprint : 0), print(lineage.tick), print(selected.after_tick),
                p.first_index, int(s32(p.base_vertex)), p.first_instance);
}
} // namespace

void RtShadow::PollLampPane(u64 scene_frame) {
    static const bool enabled = [] {
        const char* value = std::getenv("BB_LAMP_PANE_PROBE");
        return value && std::string_view(value) == "1";
    }();
    if (!enabled) {
        return;
    }

    if (lamp_pane) {
        LampPaneProbe& p = *lamp_pane;
        if (!p.refusal && !p.Captured() && scene_frame - p.armed_frame >= RtLampPane::FrameBudget) {
            p.refusal = p.saw_target ? "target seen, no eligible ordinary RT capture"
                                     : "exact target draw absent";
        }
        if (p.Captured() && !p.sealed && scene_frame >= p.capture.scene) {
            p.sealed = true;
            if (!p.refusal && (!p.depth_tick || !p.world_tick)) {
                p.refusal = !p.world_tick ? "normal capture was not recorded"
                                          : "same-frame depth trigger absent";
            }
        }
        if (!p.refusal && p.Captured() && scene_frame - p.capture.scene >= RtLampPane::FrameBudget) {
            p.refusal = "readback fence timeout";
        }
        if (p.refusal || p.sealed) {
            if (p.refusal && !p.reported) {
                std::printf("Lamp pane (t132d): request %u scene %llu draw %u build %u refused: %s\n",
                            p.request.id, static_cast<unsigned long long>(p.capture.scene),
                            p.capture.draw, p.capture.build, p.refusal);
                if (p.material_enabled) {
                    std::printf("Lamp material (t132d): req %u unknown: %s\n", p.request.id,
                                p.material.refusal ? p.material.refusal : p.refusal);
                }
                ReportLampReconstruction(p, p.refusal, "not-evaluated", nullptr);
                p.reported = true;
            }
            const bool material_ready = p.material.phases.Retired([&](u64 tick) { return scheduler.IsFree(tick); });
            const bool world_ready = !p.world_tick || scheduler.IsFree(p.world_tick);
            const bool depth_ready = !p.depth_tick || scheduler.IsFree(p.depth_tick);
            const bool clip_ready = !p.reconstruction || !p.reconstruction->clip_tick ||
                                    scheduler.IsFree(p.reconstruction->clip_tick);
            const bool index_ready = !p.lineage || !p.lineage->tick || scheduler.IsFree(p.lineage->tick);
            if (world_ready && depth_ready && material_ready && clip_ready && index_ready) {
                ReportLampIndexLineage(p, instance.GetAllocator());
                if (!p.refusal) {
                    ReportLampPane(p);
                }
                p.Free(instance.GetAllocator(), scheduler);
                lamp_pane.reset();
            }
        }
    }

    const u32 generation = BbLiveKnobs::Generation();
    if (generation == lamp_pane_generation) {
        return;
    }
    lamp_pane_generation = generation;
    const auto text = BbLiveKnobs::Lookup("BB_LAMP_PANE_PICK");
    const char* value = text.Get();
    if (!value || !*value) {
        return;
    }
    RtLampPane::Request request;
    if (!RtLampPane::Parse(value, request)) {
        std::printf("Lamp pane (t132d): refused invalid ID/W/H/PX/PY/MX/MY\n");
        return;
    }
    if (request.id <= lamp_pane_last_request) {
        return;
    }
    lamp_pane_last_request = request.id;
    if (lamp_pane) {
        std::printf("Lamp pane (t132d): request %u refused: previous request still active\n", request.id);
        return;
    }
    lamp_pane = std::make_unique<LampPaneProbe>();
    lamp_pane->request = request;
    lamp_pane->armed_frame = scene_frame;
    const char* reconstruct = std::getenv("BB_LAMP_PANE_RECON");
    if (reconstruct && std::string_view(reconstruct) == "1") {
        lamp_pane->reconstruction.emplace();
    }
    if (Round2ProbeSettings::Get().lineage) {
        lamp_pane->lineage.emplace();
    }
    static const bool material = [] {
        const char* text = std::getenv("BB_LAMP_PANE_MATERIAL");
        return text && std::string_view(text) == "1";
    }();
    lamp_pane->material_enabled = material;
    if (material) {
        std::printf("Lamp material (t132d): req %u armed for two A/B texels\n", request.id);
    }
    std::printf("Lamp pane (t132d): armed %u at scene %llu, %ux%u pane %d,%d metal %d,%d\n",
                request.id, static_cast<unsigned long long>(scene_frame), request.width,
                request.height, request.pixels[0].x, request.pixels[0].y,
                request.pixels[1].x, request.pixels[1].y);
}

namespace {
// D265 TEST ONLY. The R323 draw and both depth seeds have already been witnessed by t132d.
const char* ReportLampCorners(const LampPaneProbe& p, const RtGlassTri::Mesh& mesh,
                              const RtGlassTri::Panel& panel,
                              const std::array<RtLampPane::Hit, 2>& hits) {
    constexpr std::array<u32, 4> panel_ids{2458, 2459, 2460, 2461};
    constexpr u32 metal_id = 2074, instance = 1;
    constexpr u32 tris_per_instance = RtLampPane::DrawIndices / 3;
    const auto& id = p.capture;
    const auto& phases = p.material.phases;
    if (!id.request || id.request != p.request.id || !id.scene || !id.rt || !id.draw || !id.build ||
        id.image == std::numeric_limits<u32>::max() || !id.uid ||
        !p.world_tick || !p.depth_tick || !phases.Complete(id)) {
        return "incomplete capture identity";
    }
    if (!RtLampPane::MeshSize(p.vertices, mesh.triangles, RtLampPane::Instances) ||
        mesh.triangles != tris_per_instance * RtLampPane::Instances ||
        mesh.vertices != p.vertices * RtLampPane::Instances || !mesh.world || !mesh.indices ||
        p.indices.size() != std::size_t(mesh.triangles) * 3 ||
        u64(p.first_instance) + instance > std::numeric_limits<u32>::max()) {
        return "invalid R323 instance expansion";
    }
    if (!panel.ok || !std::ranges::equal(panel.tris, panel_ids) || RtLampPane::ValidatePair(hits) ||
        hits[0].instance != instance || hits[1].instance != instance ||
        !std::binary_search(panel_ids.begin(), panel_ids.end(), hits[0].local) ||
        hits[1].local != metal_id ||
        hits[0].expanded != instance * tris_per_instance + hits[0].local ||
        hits[1].expanded != instance * tris_per_instance + metal_id) {
        return "accepted triangles do not identify the R323 panel and control";
    }
    const auto finite = [](float value) { return std::isfinite(value); };
    const auto& [view, inverse, proj] = p.camera;
    if (!p.width || !p.height || p.width > 8192 || p.height > 8192 ||
        u64(p.width) * p.height > 3840u * 2160u ||
        !std::ranges::all_of(view, finite) || !std::ranges::all_of(inverse, finite) ||
        !std::ranges::all_of(proj, finite) || !proj[0] || !proj[1] || !(proj[3] < 0.f) ||
        !std::ranges::all_of(p.jitter, [](float j) { return std::abs(j) <= 1.f; })) {
        return "invalid captured camera or raster";
    }

    constexpr std::array local{panel_ids[0], panel_ids[1], panel_ids[2], panel_ids[3], metal_id};
    std::array<std::array<RtGlassTri::V3, 3>, local.size()> corners{};
    const auto& [scissor_offset, scissor_extent] = p.material.scissor;
    for (std::size_t t = 0; t < local.size(); ++t) {
        const u32 expanded = instance * tris_per_instance + local[t];
        std::array<RtGlassFind::ScreenPoint, 3> screen{};
        for (std::size_t k = 0; k < 3; ++k) {
            const u32 index = mesh.indices[std::size_t(expanded) * 3 + k];
            if (index / p.vertices != instance) {
                return "corner outside the accepted instance slice";
            }
            const auto world = RtGlassTri::At(mesh, index);
            const auto q = RtGlassFind::ProjectToPicture(view, proj, world.x, world.y, world.z);
            const float vz = view[8] * world.x + view[9] * world.y + view[10] * world.z + view[11];
            const float z = proj[2] + proj[3] / vz;
            const float x = q.x * float(p.width) / RtGlassFind::PictureWidth + p.jitter[0];
            const float y = q.y * float(p.height) / RtGlassFind::PictureHeight + p.jitter[1];
            if (!finite(world.x) || !finite(world.y) || !finite(world.z) || !finite(vz) ||
                !q.front || !(z >= 0.f && z <= 1.f) ||
                !(x >= 0.f && x < float(p.width) && y >= 0.f && y < float(p.height)) ||
                !(x >= float(scissor_offset.x) && y >= float(scissor_offset.y) &&
                  x < float(s64(scissor_offset.x) + scissor_extent.width) &&
                  y < float(s64(scissor_offset.y) + scissor_extent.height))) {
                return "non-finite or clipped projected corner";
            }
            corners[t][k] = world;
            screen[k] = q;
        }
        const auto [a, b, c] = screen;
        const float area = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
        if (!finite(area) || std::abs(area) < 1e-6f) {
            return "degenerate projected triangle";
        }
    }

    // Format one complete event, with locale-independent, round-trip float values.
    std::string line;
    line.reserve(4096);
    fmt::format_to(std::back_inserter(line),
        "Lamp corners (t132d): {{\"schema\":\"t132d-lamp-corners-v1\",\"identity\":{{"
        "\"request\":{},\"scene\":{},\"rt\":{},\"draw\":{},\"build\":{},\"key\":\"{:016x}\",\"present\":null}},"
        "\"readback\":{{\"depth_image\":{},\"depth_uid\":{},\"world_tick\":{},\"a_tick\":{},\"b_tick\":{},\"c_tick\":{}}},"
        "\"raster\":[{},{}],\"mesh\":{{\"pair\":\"6a833138:bb10e440\",\"index_count\":{},\"instances\":{},"
        "\"first_index\":{},\"base_vertex\":{},\"first_instance\":{},\"instance\":{},"
        "\"vertices_per_instance\":{},\"triangles_per_instance\":{}}},",
        id.request, id.scene, id.rt, id.draw, id.build, p.key, id.image, id.uid,
        p.world_tick, phases.before_tick, phases.after_tick, p.depth_tick, p.width, p.height,
        RtLampPane::DrawIndices, RtLampPane::Instances, p.first_index, s32(p.base_vertex),
        p.first_instance, instance, p.vertices, tris_per_instance);
    const auto vector = [&](std::span<const float> values) {
        line.push_back('[');
        for (std::size_t i = 0; i < values.size(); ++i) {
            fmt::format_to(std::back_inserter(line), "{}{:.16e}", i ? "," : "", double(values[i]));
        }
        line.push_back(']');
    };
    line += "\"view\":";
    vector(view);
    line += ",\"inverse\":";
    vector(inverse);
    line += ",\"proj\":";
    vector(proj);
    line += ",\"jitter\":";
    vector(p.jitter);
    line += ",\"triangles\":[";
    for (std::size_t t = 0; t < local.size(); ++t) {
        fmt::format_to(std::back_inserter(line),
            "{}{{\"role\":\"{}\",\"local\":{},\"expanded\":{},\"corners\":[",
            t ? "," : "", t < panel_ids.size() ? "panel" : "metal", local[t],
            instance * tris_per_instance + local[t]);
        for (std::size_t k = 0; k < 3; ++k) {
            if (k) line.push_back(',');
            const auto [x, y, z] = corners[t][k];
            vector(std::array{x, y, z});
        }
        line += "]}";
    }
    line += "]}\n";
    std::fwrite(line.data(), 1, line.size(), stdout);
    return nullptr;
}
} // namespace

void RtShadow::ReportLampPane(const LampPaneProbe& p) {
    const auto& id = p.capture;
    struct ReconstructionReport {
        const LampPaneProbe& probe;
        const char* failure = "mapped readback was not validated";
        const char* pick_status = "not-evaluated";
        const char* pick_reason = nullptr;
        bool corners_emitted = false;
        ~ReconstructionReport() {
            ReportLampReconstruction(probe, failure, pick_status, pick_reason, corners_emitted);
        }
    } reconstruction{p};
    std::printf("Lamp pane (t132d): request %u scene %llu RT %llu draw %u build %u key %016llx depth %u/%llu ticks %llu/%llu\n",
                id.request, static_cast<unsigned long long>(id.scene),
                static_cast<unsigned long long>(id.rt), id.draw, id.build,
                static_cast<unsigned long long>(p.key), id.image,
                static_cast<unsigned long long>(id.uid), static_cast<unsigned long long>(p.world_tick),
                static_cast<unsigned long long>(p.depth_tick));
    std::printf("Lamp pane (t132d): request %u 6a833138:bb10e440 idx25296 x3 first %u base %d first instance %u "
                "vertices/instance %u expanded tris %u raster %ux%u jitter %.4f,%.4f\n",
                id.request, p.first_index, int(s32(p.base_vertex)), p.first_instance, p.vertices,
                p.triangles, p.width, p.height, p.jitter[0], p.jitter[1]);
    const auto material_unknown = [&](const char* why) {
        reconstruction.pick_status = "refused";
        reconstruction.pick_reason = why;
        std::printf("Lamp material (t132d): req %u unknown: %s\n", id.request, why);
    };
    const auto refused = [&](const char* why) {
        reconstruction.pick_status = "refused";
        reconstruction.pick_reason = why;
        std::printf("Lamp pane (t132d): request %u inconclusive: %s\n", id.request, why);
        if (p.material_enabled) {
            material_unknown(p.material.refusal ? p.material.refusal : why);
        }
    };
    if (vmaInvalidateAllocation(instance.GetAllocator(), p.allocation, 0, VK_WHOLE_SIZE) != VK_SUCCESS) {
        reconstruction.failure = "could not invalidate mapped readback";
        refused("could not invalidate mapped readback");
        return;
    }
    const RtGlassTri::Mesh mesh{
        reinterpret_cast<const float*>(p.mapped), p.vertices * RtLampPane::Instances,
        p.indices.data(), p.triangles};
    if (!RtLampPane::MeshValid(mesh, p.vertices)) {
        reconstruction.failure = "invalid expanded indices or nonfinite captured vertices";
        refused("invalid expanded indices or non-finite captured vertices");
        return;
    }
    reconstruction.failure = nullptr;
    std::array<RtLampPane::Hit, 2> hits{};
    for (u32 i = 0; i < hits.size(); ++i) {
        float raw = 0;
        std::memcpy(&raw, p.mapped + p.WorldBytes() + sizeof(float) * i, sizeof raw);
        const auto& sample = p.samples[i];
        const auto depth = RtLampPane::ReadDepth(raw, p.camera, sample, BbTestCamera::WorldFromDepth);
        const char* label = i == 0 ? "pane" : "metal";
        if (depth.refusal) {
            std::printf("Lamp pane (t132d): request %u %s texel %u,%u raw %.9g: %s\n",
                        id.request, label, sample.x, sample.y, double(raw), depth.refusal);
            refused(depth.refusal);
            return;
        }
        const auto hit = RtLampPane::Pick(mesh, p.vertices, p.camera, sample, depth);
        hits[i] = hit;
        std::printf("Lamp pane (t132d): request %u %s texel %u,%u raw %.9g depth %.5f predicted %.5f "
                    "residual %.5f tolerance %.5f inside %u fits %u slice %u instance %llu tri %u local %u\n",
                    id.request, label, sample.x, sample.y, double(raw), double(depth.metres),
                    double(hit.predicted), double(hit.residual), double(depth.tolerance),
                    hit.inside, hit.consistent, hit.instance,
                    static_cast<unsigned long long>(u64(p.first_instance) + hit.instance),
                    hit.expanded, hit.local);
    }
    if (const char* why = RtLampPane::ValidatePair(hits)) {
        refused(why);
        return;
    }
    const auto panel = RtLampPane::Grow(mesh, p.vertices, hits[0]);
    if (!panel.ok) {
        refused(panel.why);
        return;
    }
    if (std::binary_search(panel.tris.begin(), panel.tris.end(), hits[1].local)) {
        refused("metal control is in the connected panel");
        return;
    }
    std::printf("Lamp pane (t132d): request %u geometry candidate, %zu local tris, AABB "
                "(%.4f %.4f %.4f)-(%.4f %.4f %.4f), %.4fx%.4f m, n=(%.4f %.4f %.4f) plane %.4f, "
                "metal local %u outside panel; material unresolved\n",
                id.request, panel.tris.size(), panel.box[0], panel.box[1], panel.box[2],
                panel.box[3], panel.box[4], panel.box[5], panel.width, panel.height,
                panel.normal[0], panel.normal[1], panel.normal[2], panel.offset, hits[1].local);
    constexpr std::size_t PerLine = 12;
    for (std::size_t first = 0; first < panel.tris.size(); first += PerLine) {
        std::printf("Lamp pane (t132d): request %u panel IDs %zu:", id.request, first);
        for (std::size_t i = first; i < std::min(first + PerLine, panel.tris.size()); ++i) {
            std::printf(" %u", panel.tris[i]);
        }
        std::printf("\n");
    }
    if (!p.material_enabled) {
        reconstruction.pick_status = "final-depth-pair";
        return;
    }
    const auto& m = p.material;
    if (m.refusal || !m.phases.Complete(p.capture)) {
        material_unknown(m.refusal ? m.refusal : "exact draw did not deliver both A/B phases");
        return;
    }

    using namespace RtLampPane;
    using Bytes = std::array<std::uint8_t, MaterialTexelBytes>;
    std::array<std::array<Bytes, 3>, MaterialPixels> a{}, b{};
    bool distinct = false;
    std::array<bool, MaterialPixels> changed{};
    for (u32 i = 0; i < MaterialPixels; ++i) {
        std::array<float, 2> z{};
        for (u32 phase = 0; phase < z.size(); ++phase) {
            std::memcpy(&z[phase], p.mapped + p.WorldBytes() + MaterialOffset(MaterialPhase(phase), 3, i),
                        sizeof(float));
        }
        const auto& sample = p.samples[i];
        const auto before = ReadDepth(z[0], p.camera, sample, BbTestCamera::WorldFromDepth);
        const auto after = ReadDepth(z[1], p.camera, sample, BbTestCamera::WorldFromDepth);
        const auto hit = Pick(mesh, p.vertices, p.camera, sample, after);
        const char* label = i == 0 ? "pane-seed" : "metal-control";
        std::printf("Lamp material (t132d): req %u %s texel %u,%u A-depth %.9g A-view-valid=%u A-view=%.6f "
                    "B-depth %.9g B-view-valid=%u B-view=%.6f B-fits=%u B-tri=%u C-tri=%u\n",
                    id.request, label, sample.x, sample.y, double(z[0]), unsigned(!before.refusal),
                    before.refusal ? 0.0 : double(before.metres), double(z[1]), unsigned(!after.refusal),
                    after.refusal ? 0.0 : double(after.metres), hit.consistent, hit.expanded, hits[i].expanded);
        if (after.refusal || hit.consistent != 1 || hit.expanded != hits[i].expanded) {
            material_unknown("immediate and final depth do not witness the same unique candidate");
            return;
        }
        for (u32 target = 0; target < a[i].size(); ++target) {
            std::memcpy(a[i][target].data(),
                        p.mapped + p.WorldBytes() + MaterialOffset(MaterialPhase::Before, target, i), MaterialTexelBytes);
            std::memcpy(b[i][target].data(),
                        p.mapped + p.WorldBytes() + MaterialOffset(MaterialPhase::After, target, i), MaterialTexelBytes);
            const u32 delta = MaterialChanged(a[i][target], b[i][target]);
            if (delta & ~m.masks[target]) {
                material_unknown("observed a changed byte outside the raster channel mask");
                return;
            }
            changed[i] |= delta != 0;
        }
    }
    const auto normalized = [](std::uint8_t c) { return double(c) / 255.0; };
    const u32 rgb[] = {1u, 7u, 7u};
    for (u32 target = 0; target < a[0].size(); ++target) {
        const auto encoding = LampMaterialEncoding(m.sources[target].created_format);
        const char* encoding_label = LampMaterialEncodingLabel(encoding);
        const auto& p0 = b[0][target];
        const auto& p1 = b[1][target];
        const u32 difference = MaterialChanged(p0, p1);
        distinct |= (difference & m.masks[target] & rgb[target]) != 0;
        std::printf("Lamp material (t132d): req %u MRT %u encoding=%s immediate-post-draw pane-minus-metal bytes %d,%d,%d,%d mask=%x\n",
                    id.request, target + 1, encoding_label, int(p0[0]) - int(p1[0]), int(p0[1]) - int(p1[1]),
                    int(p0[2]) - int(p1[2]), int(p0[3]) - int(p1[3]), difference);
        for (u32 i = 0; i < MaterialPixels; ++i) {
            const char* label = i == 0 ? "pane-seed" : "metal-control";
            const auto& x = a[i][target];
            const auto& y = b[i][target];
            std::printf("Lamp material (t132d): req %u %s MRT %u encoding=%s A=%u,%u,%u,%u B=%u,%u,%u,%u "
                        "B-A=%d,%d,%d,%d changed=%x\n",
                        id.request, label, target + 1, encoding_label,
                        unsigned(x[0]), unsigned(x[1]), unsigned(x[2]), unsigned(x[3]),
                        unsigned(y[0]), unsigned(y[1]), unsigned(y[2]), unsigned(y[3]),
                        int(y[0]) - int(x[0]), int(y[1]) - int(x[1]), int(y[2]) - int(x[2]), int(y[3]) - int(x[3]),
                        MaterialChanged(x, y));
            // CopyImageToBuffer retains encoded sRGB bytes. Only UNORM gets the existing derived metrics.
            if (encoding != LampMaterialColor::Unorm) {
                continue;
            }
            const double r = normalized(y[0]), g = normalized(y[1]), b = normalized(y[2]);
            if (target == 0) {
                std::printf("Lamp material (t132d): req %u %s B gloss R=%.6f exponent estimate=%.4f\n",
                            id.request, label, r, std::exp2(13.0 * r));
            } else if (target == 1) {
                std::printf("Lamp material (t132d): req %u %s B albedo RGB=%.6f,%.6f,%.6f\n",
                            id.request, label, r, g, b);
            } else {
                std::printf("Lamp material (t132d): req %u %s B specular root RGB=%.6f,%.6f,%.6f F0 estimate=%.6f,%.6f,%.6f\n",
                            id.request, label, r, g, b, r * r, g * g, b * b);
            }
        }
    }
    const bool composited = m.logic != u32(AmdGpu::ColorControl::LogicOp::Copy) ||
                            std::ranges::any_of(m.blend, [](u32 raw) {
                                return std::bit_cast<AmdGpu::BlendControl>(raw).enable;
                            });
    std::printf("Lamp material (t132d): req %u result=%s scene %llu draw %u build %u ticks A/B/C=%llu/%llu/%llu "
                "pane_changed=%u metal_changed=%u response=%s material=unknown alpha=uninterpreted\n",
                id.request, changed[0] || changed[1]
                                ? (distinct ? "draw-changed-bytes; post-values-differ"
                                            : "draw-changed-bytes; post-values-match")
                                : "no-change-proven; post-values-unattributed",
                static_cast<unsigned long long>(id.scene), id.draw, id.build,
                static_cast<unsigned long long>(m.phases.before_tick), static_cast<unsigned long long>(m.phases.after_tick),
                static_cast<unsigned long long>(p.depth_tick), unsigned(changed[0]), unsigned(changed[1]),
                composited ? "composited" : "stored");
    static const bool corners = [] {
        const char* value = std::getenv("BB_LAMP_PANE_CORNERS");
        return value && std::string_view(value) == "1";
    }();
    reconstruction.pick_status = "accepted";
    if (corners) {
        if (const char* why = ReportLampCorners(p, mesh, panel, hits)) {
            std::printf("Lamp corner refusal (t132d): request %u: %s\n", id.request, why);
            reconstruction.pick_status = "refused";
            reconstruction.pick_reason = why;
        } else {
            reconstruction.corners_emitted = true;
        }
    }
}

bool RtShadow::Make(Buffer& out, vk::DeviceSize size, bool host, VkBufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = usage | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
    if (host) {
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT |
                         VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT;
    } else {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    out.address = instance.GetDevice().getBufferAddress({.buffer = out.buffer});
    return out.address != 0;
}

void RtShadow::Free(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

InteriorRoof::WatchRow* RtShadow::RoofWatchEntry(const Entry& entry) {
    auto* watch = roof_probe ? roof_probe->Watch() : nullptr;
    if (!watch) {
        return nullptr;
    }
    const auto live = entry_live.find(&entry);
    if (live == entry_live.end() || !live->second || live->second != entry.address || !entry.handle) {
        return nullptr;
    }
    return watch->Exact(entry.base, entry.mesh);
}

void RtShadow::Destroy(Entry& entry, const char* reason) {
    if (reflection_native_tracked) {
        for (auto& probe : reflection_native_entries) {
            if (probe.entry == &entry) {
                probe = {};
                --reflection_native_tracked;
                break;
            }
        }
    }
    if (reflection_tracker) {
        ReflectionRetire(entry, reason);
    }
    InvalidateBottleGeometry(entry.address);
    if (entry.address != 0 && entry.address == bottle_entry_address) {
        bottle_entry = nullptr;
        bottle_entry_address = 0;
        bottle_ambiguous = true;
    }
    // bbport (r121c_tlas-unbound-read): no record is written for it from here. When the TLAS last built still holds
    // its address (it was in the records of the last scene) the next scene is a build and the free is counted; the
    // free itself waits for the GPU below (DeferOperation: the tick of the command buffer being recorded, never
    // before a TLAS or BLAS build recorded earlier).
    if (auto* row = RoofWatchEntry(entry)) {
        row->Forget(entry.address, reason);
    }
    entry_live.erase(&entry);
    if (roof_probe) {
        roof_probe->ForgetGeometry(entry.address);
    }
    if (TlasGuardOn() && r17_tlas_valid && entry.address != 0 &&
        std::ranges::any_of(r17_tlas_records, [&](const vk::AccelerationStructureInstanceKHR& record) {
            return record.accelerationStructureReference == entry.address;
        })) {
        ++tlas_live.freed_in_tlas;
        r17_blas_dirty = true;
    }
    entry_bytes -= std::min(entry_bytes, entry.bytes);
    blas_bytes -= std::min(blas_bytes, entry.scene_bytes);
    entry.bytes = 0;
    entry.scene_bytes = 0;
    CardRelease(entry); // bbport (r54_leaf-stage2): its block, once the GPU is past it
    // bbport (r47_still-check): its signatures still on their way back are not read (the lists
    // point at the entry), and it no longer counts against the cap of the casters found moving.
    if (entry.still_wait != 0) {
        for (auto& list : still_pending) {
            std::erase_if(list, [&](const StillPending& item) { return item.entry == &entry; });
        }
        entry.still_wait = 0;
    }
    if (entry.still_moved) {
        still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        entry.still_moved = false;
    }
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    // bbport (r35_pending-ops): a pure free (the entry is gone from the scene): may be carried.
    scheduler.DeferOperation(
        [device, allocator, handle = entry.handle, storage = entry.storage,
         indices = entry.indices, world = entry.world] {
            device.destroyAccelerationStructureKHR(handle);
            vmaDestroyBuffer(allocator, storage.buffer, storage.allocation);
            vmaDestroyBuffer(allocator, indices.buffer, indices.allocation);
            if (world.buffer) {
                vmaDestroyBuffer(allocator, world.buffer, world.allocation);
            }
        },
        "BLAS free (RtShadow::Destroy)", true);
}

bool RtShadow::EnsureWorld(Entry& entry) {
    if (entry.world.buffer) {
        return true;
    }
    const vk::DeviceSize world_bytes = vk::DeviceSize(entry.vertices) * entry.instances * 16;
    if (entry_bytes + world_bytes > MaxEntryBytes || !EffectPass::HasRoom(instance, world_bytes)) {
        return false;
    }
    if (!Make(entry.world, world_bytes, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)) {
        Free(entry.world);
        return false;
    }
    entry.bytes += world_bytes;
    entry_bytes += world_bytes;
    return true;
}

// bbport (r37_menu-options): the half-resolution sun trace (r25) while BB_RT_SUN_HALF=1 or, with
// the variable not set, while graphics_rt_sun_half is on. Read at every sun trace: both ways write
// every pixel the filter reads within the trace (rt_shadow.comp Shade), nothing is kept from the
// frame before, so it can change from one frame to the next. The pipeline is made the first time.
bool RtShadow::R25HalfWanted() {
    // bbport (r39_master-debug): engine_previous_paths on: full resolution as before r25,
    // whatever the setting and BB_RT_SUN_HALF say (this mode has no experiment bit of its own).
    const bool wanted =
        !BbSettings::Get().engine_previous_paths.load(std::memory_order_relaxed) &&
        (r25_half_env >= 0 ? r25_half_env == 1
                           : BbSettings::Get().graphics_rt_sun_half.load(std::memory_order_relaxed));
    if (wanted && !r25_half_tried) {
        r25_half_tried = true;
        using enum vk::DescriptorType;
        const bool made =
            EffectPass::Create(instance, r25_half_set, r25_half_layout, r25_half_pipeline,
                               {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                eAccelerationStructureKHR, eStorageBuffer, eStorageBuffer},
                               // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the
                               // build that also asks the panes (same bindings and push constants)
                               sizeof(TracePush),
                               RtGlassLightOn() ? std::span<const u32>{RT_SHADOW_HALF_GLASS_COMP}
                                                : std::span<const u32>{RT_SHADOW_HALF_COMP},
                               "Ray traced shadows (half resolution)");
        std::printf("Ray traced sun (r25): half resolution (%s) %s\n",
                    r25_half_env == 1 ? "BB_RT_SUN_HALF=1" : "graphics_rt_sun_half=1",
                    made ? "ready" : "ignored - no pipeline");
    }
    return wanted && r25_half_pipeline;
}

bool RtShadow::Setup(const ObjectMotion& object_motion) {
    tried = true;
    card_uv_on = Shader::Optimization::CardAlphaOn(); // bbport (r54_leaf-stage2)
    const auto device = instance.GetDevice();
    using enum vk::DescriptorType;
    const VkBufferUsageFlags as_storage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) ||
        !EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) ||
        !EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest) ||
        !EffectPass::Create(instance, trace_set, trace_layout, trace_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                             eAccelerationStructureKHR, eStorageBuffer,
                             eStorageBuffer}, // r25: counters
                            // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the build
                            // that also asks the panes (same bindings and push constants)
                            sizeof(TracePush),
                            RtGlassLightOn() ? std::span<const u32>{RT_SHADOW_GLASS_COMP}
                                             : std::span<const u32>{RT_SHADOW_COVERAGE_COMP},
                            "Ray traced shadows") ||
        !EffectPass::Create(instance, filter_set, filter_layout, filter_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                             eStorageImage, eStorageBuffer, eStorageBuffer}, // r25: counters
                            sizeof(FilterPush), RT_SHADOW_FILTER_R25_COMP,
                            "Ray traced shadow filter") ||
        !EffectPass::Create(instance, unproject_set, unproject_layout, unproject_pipeline,
                            {eStorageBuffer}, sizeof(UnprojectPush), RT_UNPROJECT_COMP,
                            "Ray tracing positions")) {
        return false;
    }
    if (!Make(params, vk::DeviceSize(1 + 4 * MaxParams) * 32, true, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        !Make(positions, vk::DeviceSize(MaxPositions) * 16, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | InputUsage) ||
        !Make(scratch, ScratchBytes, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        !Make(instance_data,
              vk::DeviceSize(4 * TlasSubSlots * MaxInstances) * // bbport (r121_tlas-hang-guard)
                  sizeof(vk::AccelerationStructureInstanceKHR), true,
              InputUsage) ||
        // bbport (r54_leaf-stage2): one address more with the card UVs (the ring's)
        !Make(capture_addresses, card_uv_on ? 24 : 16, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||
        !Make(both_addresses, card_uv_on ? 40 : 32, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT)) {
        return false;
    }
    std::memset(params.mapped, 0, 32);
    // bbport (r25_rt-sun-trace): the pass counters (zeroed on the GPU by the first sun trace).
    // bbport (r86_glass-light-stage2a): R25Words: R25Slots, or more with BB_RT_GLASS_LIGHT on
    if (!Make(r25_counts, R25Words() * sizeof(u32), false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                  VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(r25_readback, R25Words() * sizeof(u32), true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !r25_readback.mapped) {
        return false;
    }
    std::memset(r25_readback.mapped, 0, R25Words() * sizeof(u32));
    // bbport (r47_still-check): the signature pass and its buffers, unless BB_RT_STILL=off.
    // Without them there are no looks; ray tracing is as before. The copies the host reads lie
    // in memory it reads fast (Make's host buffers are for writing, as the sun VSM's Make notes
    // for its own readback).
    if (StillMode() != StillOff) {
        const vk::DeviceSize sig_bytes = vk::DeviceSize(StillSigsPerFrame) * StillSigWords * 4;
        const VkBufferCreateInfo readback_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = 4 * sig_bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo readback_alloc{.usage = VMA_MEMORY_USAGE_AUTO};
        readback_alloc.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        readback_alloc.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer readback{};
        VmaAllocationInfo readback_info{};
        // rt_still_sig.comp gathers a subgroup's bounds before one of its threads writes them:
        // the arithmetic subgroup operations in a compute shader, which a device need not have.
        const auto subgroup =
            instance.GetPhysicalDevice()
                .getProperties2<vk::PhysicalDeviceProperties2, vk::PhysicalDeviceSubgroupProperties>()
                .get<vk::PhysicalDeviceSubgroupProperties>();
        const bool subgroups =
            (subgroup.supportedStages & vk::ShaderStageFlagBits::eCompute) &&
            (subgroup.supportedOperations & vk::SubgroupFeatureFlagBits::eArithmetic);
        still_ready =
            subgroups &&
            EffectPass::Create(instance, still_set, still_layout, still_pipeline,
                               {eStorageBuffer, eStorageBuffer}, sizeof(StillPush),
                               RT_STILL_SIG_COMP, "Ray tracing still check") &&
            Make(still_sigs, sig_bytes, false,
                 VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                     VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
            vmaCreateBuffer(instance.GetAllocator(), &readback_ci, &readback_alloc, &readback,
                            &still_readback.allocation, &readback_info) == VK_SUCCESS;
        still_readback.buffer = readback;
        still_readback.mapped = readback_info.pMappedData;
        still_ready = still_ready && still_readback.mapped;
        if (still_ready) {
            std::memset(still_readback.mapped, 0, std::size_t(4 * sig_bytes));
        } else {
            std::printf("Ray tracing still check (r47): off - %s\n",
                        subgroups ? "no signature pipeline or buffer"
                                  : "this GPU has no subgroup arithmetic in compute shaders");
        }
    }
    // bbport (r37_menu-options): the half-resolution trace is made by R25HalfWanted, when first wanted.
    // bbport (r54_leaf-stage2): with the card UVs the ring's address is the blocks' last
    // member (0 where CardSetup failed: no capture then names a place in the ring). Written
    // once, here, before any draw binds the blocks.
    if (card_uv_on) {
        CardSetup();
        CardGuardSetup(); // bbport (r62e_leaf-cards-usable)
    }
    GeoCheckSetup(); // bbport (r62d_card-uv-diag): the knob's line; nothing with it 0
    const std::array<u64, 3> capture_table{params.address, positions.address, card_ring.address};
    std::memcpy(capture_addresses.mapped, capture_table.data(), card_uv_on ? 24 : 16);
    const auto motion_table = object_motion.AddressTable();
    const std::array<u64, 5> both_table{motion_table.params, motion_table.positions, params.address,
                                        positions.address, card_ring.address};
    std::memcpy(both_addresses.mapped, both_table.data(), card_uv_on ? 40 : 32);
    address_layout = ObjectMotion::CreateAddressLayout(device);
    const vk::DescriptorPoolSize pool_size{vk::DescriptorType::eUniformBuffer, 2};
    auto [pool_result, pool] = device.createDescriptorPoolUnique(
        {.maxSets = 2, .poolSizeCount = 1, .pPoolSizes = &pool_size});
    if (pool_result != vk::Result::eSuccess) {
        return false;
    }
    address_pool = std::move(pool);
    const std::array<vk::DescriptorSetLayout, 2> layouts{*address_layout, *address_layout};
    auto [set_result, sets] = device.allocateDescriptorSets(
        {.descriptorPool = *address_pool, .descriptorSetCount = 2, .pSetLayouts = layouts.data()});
    if (set_result != vk::Result::eSuccess) {
        return false;
    }
    capture_set = sets[0];
    both_set = sets[1];
    const vk::DescriptorBufferInfo capture_info{capture_addresses.buffer, 0,
                                                card_uv_on ? 24u : 16u}; // (r54)
    const vk::DescriptorBufferInfo both_info{both_addresses.buffer, 0, card_uv_on ? 40u : 32u};
    const std::array<vk::WriteDescriptorSet, 2> writes{{
        {.dstSet = capture_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer,
         .pBufferInfo = &capture_info},
        {.dstSet = both_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer,
         .pBufferInfo = &both_info},
    }};
    device.updateDescriptorSets(writes, {});

    const vk::AccelerationStructureGeometryKHR geometry{
        .geometryType = vk::GeometryTypeKHR::eInstances,
        .geometry = {.instances = vk::AccelerationStructureGeometryInstancesDataKHR{}},
        .flags = vk::GeometryFlagBitsKHR::eOpaque,
    };
    const vk::AccelerationStructureBuildGeometryInfoKHR info{
        .type = vk::AccelerationStructureTypeKHR::eTopLevel,
        .flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace,
        .mode = vk::BuildAccelerationStructureModeKHR::eBuild,
        .geometryCount = 1,
        .pGeometries = &geometry,
    };
    const u32 max_instances = MaxInstances;
    auto sizes = device.getAccelerationStructureBuildSizesKHR(
        vk::AccelerationStructureBuildTypeKHR::eDevice, info, max_instances);
    { // bbport (r17_rt-upkeep): room for builds with eAllowUpdate and for refits (PrepareScene)
        vk::AccelerationStructureBuildGeometryInfoKHR updatable = info;
        updatable.flags |= vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate;
        const auto more = device.getAccelerationStructureBuildSizesKHR(
            vk::AccelerationStructureBuildTypeKHR::eDevice, updatable, max_instances);
        sizes.accelerationStructureSize =
            std::max(sizes.accelerationStructureSize, more.accelerationStructureSize);
        sizes.buildScratchSize =
            std::max({sizes.buildScratchSize, more.buildScratchSize, more.updateScratchSize});
    }
    if (!Make(tlas_storage, sizes.accelerationStructureSize, false, as_storage) ||
        !Make(tlas_scratch, sizes.buildScratchSize, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)) {
        return false;
    }
    const auto [result, handle] = device.createAccelerationStructureKHR({
        .buffer = tlas_storage.buffer,
        .size = sizes.accelerationStructureSize,
        .type = vk::AccelerationStructureTypeKHR::eTopLevel,
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    tlas = handle;
    scratch_align = std::max<u64>(
        1, instance.GetPhysicalDevice()
               .getProperties2<vk::PhysicalDeviceProperties2,
                               vk::PhysicalDeviceAccelerationStructurePropertiesKHR>()
               .get<vk::PhysicalDeviceAccelerationStructurePropertiesKHR>()
               .minAccelerationStructureScratchOffsetAlignment);
    return true;
}

// bbport (r89_wind-foliage-sway): see the declaration (the plant sway asks for each skinned draw
// of a sway pipeline; the same map PrepareDraw keeps, on the same thread)
bool RtShadow::LonePlant(u64 positions, u32 size) const {
    if (positions == 0) {
        return false;
    }
    const auto known = lone_streams.find(positions);
    return known != lone_streams.end() && LampLoneOf(known->second) == LampLoneState::Lone &&
           (size == 0 || known->second.size == 0 || known->second.size == size);
}

// bbport (r112_wind-more-things): see the declaration (as LonePlant, for LampLoneState::Sun)
bool RtShadow::SunSkinned(u64 positions, u32 size) const {
    if (positions == 0) {
        return false;
    }
    const auto known = lone_streams.find(positions);
    return known != lone_streams.end() && LampLoneOf(known->second) == LampLoneState::Sun &&
           (size == 0 || known->second.size == 0 || known->second.size == size);
}

// bbport (r112b_hang-probe, TOOL): see the declaration. Entries a sun shadow pass drew
// (Entry::shadow) that no draw gave a skeleton, seen in the last SeenFrames frames, with their
// world bounds: the sun
// VSM's box, else the still check's bounds of the sun shadow pass's capture, else the camera
// pass's. The camera's world position is the translation of inv_view (ToWorld's matrix).
void RtShadow::WindHangProbeReport() {
    std::vector<BbWindHangProbe::Rigid> items;
    std::uint32_t sun_rigid = 0, no_bounds = 0;
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || !e->shadow || e->skinned || e->gone || e->vertices == 0 ||
            e->seen_frame + BbWindHangProbe::SeenFrames < frame) {
            continue;
        }
        ++sun_rigid;
        BbWindHangProbe::Rigid r;
        if (e->has_box) {
            r.box = e->box;
            r.src = 'v';
        } else if (e->still_has_ref[1]) {
            r.box = e->still_ref[1];
            r.src = 's';
        } else if (e->still_has_ref[0]) {
            r.box = e->still_ref[0];
            r.src = 'c';
        } else {
            ++no_bounds;
            continue;
        }
        if (!(r.box[0] <= r.box[3] && r.box[1] <= r.box[4] && r.box[2] <= r.box[5])) {
            ++no_bounds;
            continue;
        }
        r.stream = e->stream;
        r.vertices = e->vertices;
        r.triangles = e->triangles;
        r.palette = e->palette != 0;
        r.instance = e->instance;
        r.dynamic = e->dynamic;
        items.push_back(r);
    }
    if (items.empty() && wind_probe_frames < 1800) {
        return; // nothing seen yet: look again later
    }
    wind_probe_done = true;
    const auto matrices = camera_motion.CameraMatrices();
    const std::array<float, 3> position{matrices.inv_view[3], matrices.inv_view[7],
                                        matrices.inv_view[11]};
    const bool camera = std::isfinite(position[0]) && std::isfinite(position[1]) &&
                        std::isfinite(position[2]) &&
                        (matrices.inv_view[0] != 0.0f || matrices.inv_view[5] != 0.0f);
    for (const std::string& line :
         BbWindHangProbe::RigidLines(items, sun_rigid, no_bounds, camera, position,
                                     wind_probe_frames)) {
        BbReport::Printf("%s\n", line.c_str());
    }
}

// bbport (r112i_hang-find-lanterns): see the declaration. The boxes and sources of WindHangProbeReport
// (the sun VSM's box, else the still check's bounds of the sun pass's capture, else of the camera pass's),
// for every entry seen in the last 120 frames that is not gone.
void RtShadow::WindHangFindBoxes(std::vector<HangFindBox>& out, std::array<float, 3>& camera,
                                 bool& camera_ok) const {
    out.clear();
    out.reserve(entries.size());
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || e->gone || e->vertices == 0 || e->seen_frame + 120 < frame) {
            continue;
        }
        HangFindBox r;
        if (e->has_box) {
            r.box = e->box;
            r.src = 'v';
        } else if (e->still_has_ref[1]) {
            r.box = e->still_ref[1];
            r.src = 's';
        } else if (e->still_has_ref[0]) {
            r.box = e->still_ref[0];
            r.src = 'c';
        } else {
            continue;
        }
        if (!(r.box[0] <= r.box[3] && r.box[1] <= r.box[4] && r.box[2] <= r.box[5]) ||
            !std::isfinite(r.box[0] + r.box[1] + r.box[2] + r.box[3] + r.box[4] + r.box[5])) {
            continue;
        }
        r.stream = e->stream;
        r.vertices = e->vertices;
        r.triangles = e->triangles;
        r.skinned = e->skinned;
        r.dynamic = e->dynamic;
        r.palette = e->palette != 0;
        r.shadow = e->shadow;
        out.push_back(r);
    }
    const auto matrices = camera_motion.CameraMatrices();
    camera = {matrices.inv_view[3], matrices.inv_view[7], matrices.inv_view[11]};
    camera_ok = std::isfinite(camera[0]) && std::isfinite(camera[1]) && std::isfinite(camera[2]) &&
                (matrices.inv_view[0] != 0.0f || matrices.inv_view[5] != 0.0f);
}

bool RtShadow::RayTracing() const {
    return capturing && !failed &&
           BbSettings::Get().effects[BbSettings::EffectRayTracing].load(std::memory_order_relaxed);
}

bool RtShadow::VsmWanted() const {
    // A VSM that could not be made leaves nothing to capture for.
    return RayTracing() && BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed) &&
           !(vsm_tried && (!vsm || !vsm->Ready()));
}

bool RtShadow::SunRayTraced() const {
    if (!RayTracing()) {
        return false;
    }
    const auto& s = BbSettings::Get();
    return s.graphics_rt_sun.load(std::memory_order_relaxed) ||
           (s.graphics_sun_vsm.load(std::memory_order_relaxed) && vsm_tried &&
            (!vsm || !vsm->Ready()));
}

bool RtShadow::SunWanted() const {
    return VsmWanted() || SunRayTraced();
}

bool RtShadow::Wanted() const {
    // Ray tracing on with nothing using the scene or the VSM captures nothing.
    return RayTracing() && (VsmWanted() || SceneWanted());
}

bool RtShadow::Complete() const {
    return Wanted() && !frame_entries.empty() &&
           camera_motion.PassMatrices().valid;
}

void RtShadow::BindAddresses(vk::PipelineLayout layout, u32 mode, u32 bottle_param) {
    const bool both = Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth;
    const vk::DescriptorSet set = bottle_param ? (both ? bottle_cold->both_set : bottle_cold->capture_set)
                                               : (both ? both_set : capture_set);
    scheduler.Record([layout, set](vk::CommandBuffer command) {
        command.bindDescriptorSets(vk::PipelineBindPoint::eGraphics, layout,
                                   Shader::MotionVectors::DescriptorSet, set, {});
    });
}

bool RtShadow::ToWorld(const float* constants, bool perspective, std::array<float, 12>& out) const {
    const float* proj = constants + 52;
    const bool ortho = proj[12] == 0.0f && proj[13] == 0.0f && proj[14] == 0.0f && proj[15] == 1.0f;
    if (!ortho && !perspective) {
        return false;
    }
    bool ok = false;
    const auto inverse = Invert(proj, ok);
    if (!ok) {
        return false;
    }
    const float* inv_view = constants + 180;
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) {
            float sum = inv_view[r * 4 + 3] * inverse[12 + c];
            for (int k = 0; k < 3; ++k) {
                sum += inv_view[r * 4 + k] * inverse[k * 4 + c];
            }
            out[r * 4 + c] = sum;
        }
    }
    return std::ranges::all_of(out, [](float v) { return std::isfinite(v); });
}

// bbport (r17_rt-upkeep): ToWorld's result kept for the same inputs: the 16 projection floats at
// word 52, the 12 view-to-world floats at word 180 (all it reads) and the pass kind. The draws of
// one cascade share one camera, so the double precision inverse ran ~3,400 times a frame for a
// handful of cameras. Matched on the bytes, so a camera rewritten in place is computed again.
bool RtShadow::R17ToWorld(const float* constants, bool perspective, std::array<float, 12>& out) {
    if (!UpkeepOn()) {
        ++r17_stats.world_computed;
        return ToWorld(constants, perspective, out);
    }
    const u32 n = u32(r17_memo.size());
    // bbport (r19_draw-cost): the memo compared with the constants where they are (the same 112
    // bytes, the same order of memos); copied only on a miss, to fill a memo.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    for (u32 i = 0; r19 && i < n; ++i) {
        const u32 at = (r17_memo_last + i) % n;
        const ToWorldMemo& memo = r17_memo[at];
        if (memo.used && memo.perspective == perspective &&
            std::memcmp(memo.in.data(), constants + 52, 16 * sizeof(float)) == 0 &&
            std::memcmp(memo.in.data() + 16, constants + 180, 12 * sizeof(float)) == 0) {
            r17_memo_last = at;
            ++r17_stats.world_reused;
            ++r19_stats.world_in_place;
            out = memo.out;
            return memo.ok;
        }
    }
    std::array<float, 28> in;
    std::memcpy(in.data(), constants + 52, 16 * sizeof(float));
    std::memcpy(in.data() + 16, constants + 180, 12 * sizeof(float));
    for (u32 i = 0; !r19 && i < n; ++i) {
        const u32 at = (r17_memo_last + i) % n;
        const ToWorldMemo& memo = r17_memo[at];
        if (memo.used && memo.perspective == perspective &&
            std::memcmp(memo.in.data(), in.data(), sizeof(in)) == 0) {
            r17_memo_last = at;
            ++r17_stats.world_reused;
            out = memo.out;
            return memo.ok;
        }
    }
    ToWorldMemo& memo = r17_memo[r17_memo_next];
    r17_memo_last = r17_memo_next;
    r17_memo_next = (r17_memo_next + 1) % n;
    memo.used = true;
    memo.perspective = perspective;
    memo.in = in;
    memo.out = {};
    memo.ok = ToWorld(constants, perspective, memo.out);
    ++r17_stats.world_computed;
    out = memo.out;
    return memo.ok;
}

bool RtShadow::InputsWanted() const {
    return capturing && UnchangedMode() != 0 && UpkeepOn();
}

u32 RtShadow::Param(u32 store, const Entry& entry) {
    if (params_used >= MaxParams) {
        return 0;
    }
    const u32 slot = u32(frame % 4);
    const u32 index = 1 + slot * MaxParams + params_used++;
    auto* param = static_cast<u32*>(params.mapped) + index * 8;
    param[0] = store;
    param[1] = 0;
    param[2] = entry.vertices;
    param[3] = Shader::MotionVectors::FlagStore;
    param[4] = entry.first_vertex;
    param[5] = entry.first_instance;
    param[6] = entry.instances;
    param[7] = 0;
    slot_ticks[slot] = scheduler.CurrentTick();
    return index;
}

std::unique_ptr<RtShadow::Entry> RtShadow::MakeEntry(const Draw& draw, u8 mask) {
    const auto device = instance.GetDevice();
    u32 lo = UINT32_MAX, hi = 0;
    const auto scan = [&]<class Index>(const Index* data) {
        const Index cut = std::numeric_limits<Index>::max();
        for (u32 i = 0; i < draw.index_count; ++i) {
            if (draw.restart && data[i] == cut) {
                continue;
            }
            lo = std::min(lo, u32(data[i]));
            hi = std::max(hi, u32(data[i]));
        }
    };
    std::vector<u32> list;
    list.reserve(std::size_t(draw.index_count) * (draw.strip ? 3 : 1));
    const void* source = reinterpret_cast<const void*>(draw.indices);
    bool good = false;
    if (draw.index_size == 2) {
        scan(static_cast<const u16*>(source));
        good = lo <= hi && AppendTriangles<u16>({static_cast<const u16*>(source), draw.index_count},
                                                draw.strip, draw.restart, lo, list);
    } else {
        scan(static_cast<const u32*>(source));
        good = lo <= hi && AppendTriangles<u32>({static_cast<const u32*>(source), draw.index_count},
                                                draw.strip, draw.restart, lo, list);
    }
    if (good && glass_tri_keep_now != nullptr) { // bbport (r86m_glint-pane-from-triangle, TOOL): a pane cut from some triangles
        std::vector<u32> kept;
        kept.reserve(glass_tri_keep_now->size() * 3);
        for (const u32 t : *glass_tri_keep_now) {
            if (std::size_t(t) * 3 + 2 < list.size()) {
                kept.insert(kept.end(), list.begin() + std::ptrdiff_t(t) * 3, list.begin() + std::ptrdiff_t(t) * 3 + 3);
            }
        }
        std::printf("GLINT-PROOF glass pick (r86m): pane entry made from %zu of %zu triangles of the draw\n", kept.size() / 3,
                    list.size() / 3);
        list.swap(kept);
    }
    const u64 vertex_count = u64(hi - lo + 1);
    if (!good || list.empty() || list.size() / 3 * draw.instances > MaxTrianglesPerBlas ||
        vertex_count * draw.instances > MaxPositions / 4) {
        ++stats.unsupported;
        return nullptr;
    }
    const std::size_t per_instance = list.size();
    list.resize(per_instance * draw.instances);
    for (u32 i = 1; i < draw.instances; ++i) {
        for (std::size_t k = 0; k < per_instance; ++k) {
            list[i * per_instance + k] = list[k] + i * u32(vertex_count);
        }
    }
    auto entry = std::make_unique<Entry>();
    entry->first_vertex = u32(s64(lo) + s64(s32(draw.first_vertex)));
    entry->vertices = u32(vertex_count);
    entry->instances = draw.instances;
    entry->first_instance = draw.first_instance;
    entry->triangles = u32(list.size() / 3);
    entry->palette = draw.palette;
    entry->palette_placed = draw.palette_placed; // bbport (r47b_casters)
    entry->dynamic = draw.skinned;
    entry->mask = mask;
    entry->shadow = mask == ShadowMask;
    const vk::DeviceSize world_bytes = vk::DeviceSize(entry->vertices) * entry->instances * 16;
    const vk::DeviceSize world_estimate = entry->shadow && WorldCopies() ? world_bytes : 0;
    const bool scene_over = need_scene && blas_bytes + vk::DeviceSize(entry->triangles) * 64 > blas_limit;
    if (scene_over ||
        entry_bytes + vk::DeviceSize(entry->triangles) * 96 + world_estimate > MaxEntryBytes ||
        !EffectPass::HasRoom(instance, vk::DeviceSize(entry->triangles) * 96) ||
        !Make(entry->indices, list.size() * sizeof(u32), true, InputUsage)) {
        ++stats.over_budget;
        ++missed;
        return nullptr;
    }
    // Ordinary draw variants can share this entry. Shortlist by the common key
    // fields and prove the ordered upload while it is still in CPU memory.
    if (draw.index_count == BottleCaustic::IndexCount && entry->instances == 1 &&
        list.size() == BottleCaustic::IndexCount) {
        static const bool bottle_can_enable = [] {
#if __has_include("bbport_live_knobs.h")
            const char* live = std::getenv("BB_LIVE_KNOBS_FILE");
            if (live && *live) {
                return true;
            }
#endif
            return BottleCaustic::On();
        }();
        entry->bottle_index_verified = bottle_can_enable && bottle_topology.Verify(list);
    }
    std::memcpy(entry->indices.mapped, list.data(), list.size() * sizeof(u32));
    vk::AccelerationStructureGeometryKHR geometry{
        .geometryType = vk::GeometryTypeKHR::eTriangles,
        .geometry = {.triangles = vk::AccelerationStructureGeometryTrianglesDataKHR{
            .vertexFormat = vk::Format::eR32G32B32Sfloat,
            .vertexStride = 16,
            .maxVertex = entry->vertices * entry->instances - 1,
            .indexType = vk::IndexType::eUint32,
        }},
        .flags = vk::GeometryFlagBitsKHR::eOpaque,
    };
    const vk::AccelerationStructureBuildGeometryInfoKHR info{
        .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
        .flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace |
                 vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate,
        .mode = vk::BuildAccelerationStructureModeKHR::eBuild,
        .geometryCount = 1,
        .pGeometries = &geometry,
    };
    auto sizes = device.getAccelerationStructureBuildSizesKHR(
        vk::AccelerationStructureBuildTypeKHR::eDevice, info, entry->triangles);
    { // bbport (r17_rt-upkeep): a shared copy's refresh builds use ePreferFastBuild alone (see
      // RecordBuilds): storage and scratch fit both flag sets, whatever the experiment bit.
        vk::AccelerationStructureBuildGeometryInfoKHR fast = info;
        fast.flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastBuild;
        const auto other = device.getAccelerationStructureBuildSizesKHR(
            vk::AccelerationStructureBuildTypeKHR::eDevice, fast, entry->triangles);
        sizes.accelerationStructureSize =
            std::max(sizes.accelerationStructureSize, other.accelerationStructureSize);
        sizes.buildScratchSize = std::max(sizes.buildScratchSize, other.buildScratchSize);
    }
    entry->scratch = sizes.buildScratchSize;
    entry->update_scratch = sizes.updateScratchSize;
    entry->reflection_creation_size = sizes.accelerationStructureSize;
    entry->scene_bytes = sizes.accelerationStructureSize + list.size() * sizeof(u32);
    entry->bytes = entry->scene_bytes;
    if (!Make(entry->storage, sizes.accelerationStructureSize, false,
              VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR)) {
        Free(entry->indices);
        ++stats.over_budget;
        ++missed;
        return nullptr;
    }
    const auto [result, handle] = device.createAccelerationStructureKHR({
        .buffer = entry->storage.buffer,
        .size = sizes.accelerationStructureSize,
        .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
    });
    if (result != vk::Result::eSuccess) {
        Free(entry->indices);
        Free(entry->storage);
        failed = true;
        return nullptr;
    }
    entry->handle = handle;
    entry->address = device.getAccelerationStructureAddressKHR({.accelerationStructure = handle});
    entry_live[entry.get()] = entry->address; // bbport (r121c_tlas-unbound-read): the BLAS exists until Destroy
    entry_bytes += entry->bytes;
    blas_bytes += entry->scene_bytes;
    // The shared positions buffer is reused every frame; static VSM casters keep this world copy.
    if (entry->shadow && WorldCopies()) {
        EnsureWorld(*entry);
    }
    return entry;
}

u32 RtShadow::NextOccurrence(u64 hash) {
    if (BbToggle::Experiment(2097152)) {
        return occurrences[hash]++;
    }
    for (u32 probe = 0; probe < 32; ++probe) {
        OccurrenceSlot& slot = occurrence_slots[(hash + probe) & (OccurrenceSlots - 1)];
        if (slot.epoch != occurrence_epoch) {
            slot = OccurrenceSlot{hash, occurrence_epoch, 1u};
            return 0;
        }
        if (slot.hash == hash) {
            return slot.count++;
        }
    }
    return occurrences[hash]++;
}

// bbport (r14_cascade_rt): the sun cascade of a shadow pass draw: the quadrant of the sun atlas
// (the largest square shadow target; lamp shadow maps are smaller) holding its viewport, numbered
// as SunAtlasSkipDraw does (bit 0 east, bit 1 south); 4: another target or no single quadrant.
u8 RtShadow::SunCascade(const Draw& draw) {
    atlas_side = std::max(atlas_side, draw.target);
    if (draw.target == 0 || draw.target != atlas_side) {
        return 4;
    }
    const float half = 0.5f * float(draw.target);
    const float sx = std::abs(draw.viewport[2]), sy = std::abs(draw.viewport[3]);
    const float x0 = draw.viewport[0] - sx, x1 = draw.viewport[0] + sx;
    const float y0 = draw.viewport[1] - sy, y1 = draw.viewport[1] + sy;
    if (!(x1 > x0) || !(y1 > y0)) {
        return 4;
    }
    const bool east = x0 >= half - 0.5f, south = y0 >= half - 0.5f;
    if ((!east && x1 > half + 0.5f) || (!south && y1 > half + 0.5f)) {
        return 4;
    }
    return u8((east ? 1u : 0u) | (south ? 2u : 0u));
}

// bbport (r14_cascade_rt): an entry last drawn into sun cascades none of which drew this frame
// (so far), within the window: the game left its cascade undrawn, so it still casts the sun's
// shadow. Its BLAS and world copy are the ones of its last draw (a moving caster's last pose).
// Only the four sun cascades count: a draw in no single quadrant (bit 4) is never held.
bool RtShadow::Holds(const Entry& entry) const {
    return hold_frames && entry.shadow_frame != frame &&
           frame - entry.shadow_frame <= hold_frames &&
           (entry.cascades & ~frame_cascades & 0x0f) != 0 && !entry.gone;
}

// bbport (r14_cascade_rt): the held entries not drawn this frame, as of now (entries drawn later
// in the frame move to frame_entries; cascades drawn later drop theirs).
void RtShadow::CollectHeld() {
    held_now.clear();
    for (Entry* entry : held) {
        const bool pick = entry->seen_frame != frame && Holds(*entry);
        if (auto* row = RoofWatchEntry(*entry)) {
            ++row->now.held_seen;
            row->now.held_pick += pick;
            row->now.hold_why = pick ? "cascade-held" :
                entry->seen_frame == frame ? "already-in-current-draw-list" :
                !hold_frames ? "cascade-hold-off" :
                entry->shadow_frame == frame ? "cascade-current" :
                frame - entry->shadow_frame > hold_frames ? "cascade-hold-expired" :
                !(entry->cascades & ~frame_cascades & 0x0f) ? "no-undrawn-matching-cascade" :
                entry->gone ? "entry-marked-gone" : "unknown";
        }
        if (pick) {
            held_now.push_back(entry);
        }
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the window panes drawn last frame and
    // not yet this frame, with a BLAS (built at that frame's end, OnFrameEnd). The game draws them
    // forward, after the sun's trace and the lamp pass, and the frame's entries are forgotten at
    // its end: without this no traced scene holds a pane. Their records keep RtGlassMask alone
    // (PrepareScene). Off: glass_carry stays empty.
    for (const u64 key : glass_carry) {
        const auto it = entries.find(key);
        if (it != entries.end() && it->second && it->second->blas &&
            it->second->seen_frame != frame && RtGlassEntry(it->second->mask)) {
            held_now.push_back(it->second.get());
            if (auto* row = RoofWatchEntry(*it->second)) {
                ++row->now.held_seen;
                ++row->now.held_pick;
                row->now.hold_why = "existing-glass-carry";
            }
        }
    }
}

// bbport (r14_cascade_rt): at the end of a frame, the entries that may be held next frame: those
// drawn into a cascade this frame, and those held this frame still inside the window. One drawn
// neither this frame nor by a cascade that drew is dropped; so is one whose cascades all drew
// without it (it left them), or that the VSM or a promotion declared gone.
void RtShadow::UpdateHeld() {
    const u32 period = BbToggle::Experiment(BbSunCascades::kOffBit)
                           ? 0u
                           : BbSunCascades::skip_period.load(std::memory_order_relaxed);
    const u64 window = period > 1 ? u64(std::min(period, MaxHoldPeriod)) - 1 + HoldMarginFrames : 0;
    for (Entry* entry : held) {
        entry->held = false;
    }
    held_next.clear();
    if (hold_frames) {
        ++hold_stats.frames;
        for (u32 c = 0; c < 5; ++c) {
            hold_stats.cascade_frames[c] += (frame_cascades >> c) & 1u;
        }
        for (Entry* entry : held) {
            if (entry->held || entry->shadow_frame == frame) {
                continue; // drawn into a cascade this frame: taken below with the frame's entries
            }
            if (!Holds(*entry)) {
                if (auto* row = RoofWatchEntry(*entry)) {
                    row->now.hold_why = frame - entry->shadow_frame > hold_frames ? "cascade-hold-expired" :
                                            entry->gone ? "entry-marked-gone" : "no-undrawn-matching-cascade";
                }
                if (frame - entry->shadow_frame > hold_frames) {
                    ++hold_stats.aged;
                } else {
                    ++hold_stats.dropped;
                }
                continue;
            }
            if (entry->seen_frame == frame) {
                ++hold_stats.lent; // drawn by the camera pass only: kept in the sun's ray mask
            } else {
                ++hold_stats.kept;
            }
            if (frame + 1 - entry->shadow_frame > window) {
                ++hold_stats.aged;
                if (auto* row = RoofWatchEntry(*entry)) {
                    row->now.hold_why = "next-cascade-window-expired";
                }
                continue;
            }
            entry->held = true;
            held_next.push_back(entry);
            if (auto* row = RoofWatchEntry(*entry)) {
                ++row->now.held_next;
            }
        }
        if (window) {
            for (Entry* entry : frame_entries) {
                if (!entry->held && entry->shadow_frame == frame && (entry->cascades & 0x0f)) {
                    entry->held = true;
                    held_next.push_back(entry);
                    if (auto* row = RoofWatchEntry(*entry)) {
                        ++row->now.held_next;
                    }
                }
            }
        }
    }
    std::swap(held, held_next);
    held_next.clear();
    held_now.clear();
    if (hold_frames && frame % 600 == 0 && hold_stats.frames) {
        const double f = double(hold_stats.frames);
        std::printf("Ray tracing held sun casters (r14): skip period %u, held up to %llu frames "
                    "undrawn; %.1f entries kept a frame, %.1f more drawn by the camera pass only "
                    "kept in the sun's mask; %llu dropped (their cascades drawn without them, or "
                    "gone) and %llu aged out since the last line; %zu held now; frames with draws "
                    "in c0 %llu c1 %llu c2 %llu c3 %llu, in no single quadrant %llu, of %llu\n",
                    period, static_cast<unsigned long long>(window), double(hold_stats.kept) / f,
                    double(hold_stats.lent) / f,
                    static_cast<unsigned long long>(hold_stats.dropped),
                    static_cast<unsigned long long>(hold_stats.aged), held.size(),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[0]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[1]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[2]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[3]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[4]),
                    static_cast<unsigned long long>(hold_stats.frames));
        hold_stats = {};
    }
    if (!window) {
        hold_stats = {};
    }
    hold_frames = window;
    frame_cascades = 0;
}

// bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT, read once at start. Unset or empty: nothing (no line, no state). "0" without
// the live knobs file is as unset. Otherwise the mode is made and the lamp pass (PointShadow::Ready) says the rest; off for a
// reason here (not 0 or 1, no registry, no ray traced lamps) is said once. With the live file the knob is read each frame.
void RtShadow::GlassLightStart() {
    const char* text = std::getenv("BB_GLASS_LIGHT");
    if (text == nullptr || text[0] == '\0') {
        return;
    }
    const u8 parsed = GlassLight::ParseLight(text);
    bool live = false;
#if BB_GLASS_STATIC_LIVE
    const char* file = std::getenv("BB_LIVE_KNOBS_FILE");
    live = file != nullptr && file[0] != '\0';
#endif
    if (parsed == 0 && !live) {
        return;
    }
    const char* why = parsed == 2                         ? "is neither 0 nor 1"
                      : !GlassRegistryRules::Load().on ? "needs BB_GLASS_TABLE"
                      : !capturing                      ? "no ray traced lamps"
                                                        : nullptr;
    if (why != nullptr) {
        std::printf("Glass light (r130c): BB_GLASS_LIGHT=%.16s: off (%s)\n", text, why);
        return;
    }
    glass_light_mode = 1;
    glass_light_live = live;
    glass_light_now = parsed == 1 || !live;
    glass_counts.window_start = frame;
}

// bbport (r130c_glass-lamp-light): once a scene's records are written (PrepareScene, only while the mode is made): the knob now
// (live: each frame), the live flips and the 600-frame line. True: this scene's glass entries get glass records (not with the
// lamp cards on, whose CARDS builds have no glass form: the records stay as before, counted).
bool RtShadow::GlassLightFrame(bool card_lamps) {
    bool now = true;
#if BB_GLASS_STATIC_LIVE
    if (glass_light_live) {
        static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_LIGHT", GlassLight::ParseLight};
        now = knob.Get() == 1;
    }
#endif
    if (now != glass_light_now) {
        std::printf("Glass light (r130c): live %s at frame %llu\n", now ? "on" : "off",
                    static_cast<unsigned long long>(frame));
        glass_light_now = now;
    }
    if (!now && glass_counts.off_frame != frame + 1) {
        glass_counts.off_frame = frame + 1;
        ++glass_counts.live_off;
    }
    if (frame - glass_counts.window_start >= 600) {
        std::printf("Glass light (r130c): frames %llu-%llu: glass records %llu (twins %llu), kept blocking (lamp cards) %llu, "
                    "passes with glass %llu of %llu, live off %llu frames\n",
                    static_cast<unsigned long long>(glass_counts.window_start + 1), static_cast<unsigned long long>(frame),
                    static_cast<unsigned long long>(glass_counts.records), static_cast<unsigned long long>(glass_counts.twins),
                    static_cast<unsigned long long>(glass_counts.kept_cards),
                    static_cast<unsigned long long>(glass_counts.passes_glass),
                    static_cast<unsigned long long>(glass_counts.passes), static_cast<unsigned long long>(glass_counts.live_off));
        glass_counts = {};
        glass_counts.window_start = frame;
    }
    glass_light_records_now = 0;
    return now && !card_lamps;
}

// bbport (r130c_glass-lamp-light): a draw reached its entry (PrepareDraw, only while the mode is made). A registry hit of a
// transmitting kind marks the entry (sticky) and remembers the mesh; a sun shadow pass draw of a remembered mesh (the twin: the
// pass that draws the pane for the sun) is marked with the same entry, so that both records carry the glass index.
void RtShadow::GlassLightNote(Entry& entry, const Draw& draw) {
    const u64 count = draw.index_count;
    if (draw.glass_entry != 0) {
        const auto& table = GlassRegistryRules::Load();
        const u32 index = u32(draw.glass_entry) - 1u;
        if (index >= table.count || !GlassLight::Transmits(table.entries[index].kind)) {
            return;
        }
        entry.glass_light = draw.glass_entry;
        const u64 packed = count | u64(draw.glass_entry) << 32;
        for (u32 i = 0; i < glass_geo_n; ++i) {
            if (glass_geo[i][0] == draw.geometry && glass_geo[i][1] == draw.indices && (glass_geo[i][2] & 0xffffffffull) == count) {
                glass_geo[i][2] = packed;
                return;
            }
        }
        if (glass_geo_n < glass_geo.size()) {
            glass_geo[glass_geo_n++] = {draw.geometry, draw.indices, packed};
        }
    } else if (draw.shadow_pass && entry.glass_light == 0) {
        for (u32 i = 0; i < glass_geo_n; ++i) {
            if (glass_geo[i][0] == draw.geometry && glass_geo[i][1] == draw.indices && (glass_geo[i][2] & 0xffffffffull) == count) {
                entry.glass_light = u8(glass_geo[i][2] >> 32);
                ++glass_counts.twins;
                return;
            }
        }
    }
}

// bbport (r130g_glass-light-forward): the once line (BB_GLASS_LIGHT on only).
void RtShadow::GlassForwardStart() {
    if (glass_light_mode == 0) {
        return;
    }
    glass_fwd.window_start = frame;
    std::printf("Glass light (r130g): forward panes %s (BB_RT_GLASS %s): a registered pane drawn with a GPU-placed palette is "
                "taken when drawn %u frames in a row (at most %u a frame) and carried into the next frame's scene; the glass "
                "query reaches %.2f m short of the lamp's centre (before: the solid ray's blind end, 0.18 m or more); counted in "
                "half-resolution passes (one in 8; full resolution counts nothing)\n",
                RtGlassOn() ? "possible" : "none", RtGlassOn() ? "on" : "off", GlassLight::SteadyFrames,
                GlassLight::PlacedPerFrame, double(GlassLight::LampClear));
}

// bbport (r130g_glass-light-forward): the glass counter as text: `now` less `last` (the words of GlassRaysSeen), for the first
// look and the 600-frame line.
void RtShadow::GlassRaysText(char* out, std::size_t size, const std::array<u32, 10>& now, const std::array<u32, 10>& last) const {
    const u32 counted = now[0] - last[0];
    if (counted == 0) {
        std::snprintf(out, size, "lamp rays: no counted pass (full resolution, or no half resolution pass was counted yet)");
        return;
    }
    char lamp[160] = "no lamp met";
    if (now[9] != 0) {
        float v[3];
        for (u32 i = 0; i < 3; ++i) {
            const u32 bits = now[6 + i];
            std::memcpy(&v[i], &bits, sizeof(float));
        }
        std::snprintf(lamp, sizeof(lamp), "a lamp met at %.2f m from the camera (view %.2f %.2f %.2f), its pane %.3f m from the "
                      "lamp's centre", std::sqrt(double(v[0]) * v[0] + double(v[1]) * v[1] + double(v[2]) * v[2]), double(v[0]),
                      double(v[1]), double(v[2]), double(now[9]) * 0.001);
    }
    std::snprintf(out, size, "lamp rays in %u counted passes: asked %u, met glass %u, tinted %u, met inside the old blind end %u; "
                  "entries met 0x%x; %s", counted, now[1] - last[1], now[2] - last[2], now[3] - last[3], now[4] - last[4], now[5],
                  lamp);
}

// bbport (r130g_glass-light-forward): called each scene while the mode is made, right after r130c's GlassLightFrame: the first look
// at the glass counter (once, when four passes were counted) and, every 600 frames, the forward panes and the counter.
void RtShadow::GlassForwardFrame() {
    char text[480];
    if (!glass_rays_early && glass_rays_now[0] >= 4u) {
        glass_rays_early = true;
        GlassRaysText(text, sizeof(text), glass_rays_now, std::array<u32, 10>{});
        std::printf("Glass light (r130g): first look, since start: %s\n", text);
    }
    if (frame - glass_fwd.window_start < 600) {
        return;
    }
    GlassRaysText(text, sizeof(text), glass_rays_now, glass_rays_last);
    std::printf("Glass light (r130g): frames %llu-%llu: placed panes taken %llu, not steady %llu, over the cap %llu, moving left "
                "out %llu; glass records carried %llu; %s\n",
                static_cast<unsigned long long>(glass_fwd.window_start + 1), static_cast<unsigned long long>(frame),
                static_cast<unsigned long long>(glass_fwd.placed_taken), static_cast<unsigned long long>(glass_fwd.placed_unsteady),
                static_cast<unsigned long long>(glass_fwd.placed_cap), static_cast<unsigned long long>(glass_fwd.moving_left),
                static_cast<unsigned long long>(glass_fwd.carried), text);
    glass_rays_last = glass_rays_now;
    glass_fwd = {};
    glass_fwd.window_start = frame;
}

// bbport (r130g_glass-light-forward): may a pane draw with a palette the GPU wrote be taken? Only with BB_GLASS_LIGHT on and a
// registry hit (Draw::glass_entry, index + 1) of a kind that lets light through. Off: false at the first test.
bool RtShadow::GlassPlacedAllowed(u8 hit) const {
    if (glass_light_mode == 0 || hit == 0) {
        return false;
    }
    const auto& table = GlassRegistryRules::Load();
    return hit <= table.count && GlassLight::Transmits(table.entries[hit - 1u].kind);
}

// bbport (r130g_glass-light-forward): the steady rule for such a pane instance (GlassLight::JudgeSteady: drawn on 3 frames in a
// row), and at most PlacedPerFrame of them a frame. False: the draw is left out (PrepareDraw returns 0, as for r121b's verdicts).
bool RtShadow::GlassPlacedSteady(u64 instance) {
    if (!GlassLight::JudgeSteady(glass_steady, instance, frame)) {
        ++glass_fwd.placed_unsteady;
        return false;
    }
    if (glass_placed_frame != frame) {
        glass_placed_frame = frame;
        glass_placed_frame_n = 0;
    }
    if (glass_placed_frame_n >= GlassLight::PlacedPerFrame) {
        ++glass_fwd.placed_cap;
        return false;
    }
    ++glass_placed_frame_n;
    ++glass_fwd.placed_taken;
    return true;
}

// bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's draw reached its entry
// (RtGlassMask alone). The first pane draw of the run is said at once; then every
// RtGlassWindowFrames frames in which panes drew, one line with their draws and triangles.
void RtShadow::NoteGlassDraw(const Entry& entry) {
    RtGlassProbe::Add(RtGlassProbe::Note); // bbport (r83b_glass-pane-probe)
    const int say = RtGlassNote(glass_stats, frame, entry.triangles);
    if (say == 1) {
        std::printf("Ray tracing glass (r83): first window pane draw at frame %llu: %u triangles, "
                    "%u instances, instance mask 0x%x alone\n",
                    static_cast<unsigned long long>(frame), entry.triangles, entry.instances,
                    unsigned(RtGlassMask));
    } else if (say == 2) {
        std::printf("Ray tracing glass (r83): %llu window pane draws (%llu triangles) in the last "
                    "%llu frames; instance mask 0x%x alone, which no ray traces yet\n",
                    static_cast<unsigned long long>(glass_stats.draws),
                    static_cast<unsigned long long>(glass_stats.triangles),
                    static_cast<unsigned long long>(frame - glass_stats.window_start),
                    unsigned(RtGlassMask));
    }
    // bbport (r86f_glass-static-panes): with r83's window line, what the static panes got
    if (say == 2 && (r86f_given != 0 || r86f_none != 0)) {
        std::printf("Ray tracing glass (r86f): pane draws without camera constants of their own (static panes): the frame camera was given to %llu, none was known for %llu (all since the start)\n",
                    static_cast<unsigned long long>(r86f_given),
                    static_cast<unsigned long long>(r86f_none));
    }
    if (say != 0) {
        RtGlassWindowNext(glass_stats, frame);
    }
}

// bbport (r86f_glass-static-panes): one vote of a camera pass draw's constants (Boyer-Moore: the
// pointer most draws hold is left when it has more than half; no allocation, no search).
void RtShadow::GlassCameraVote(const float* constants) {
    if (r86f_votes == 0) {
        r86f_camera = constants;
        r86f_votes = 1;
    } else if (r86f_camera == constants) {
        ++r86f_votes;
    } else {
        --r86f_votes;
    }
}

// bbport (r86f_glass-static-panes): the constants a pane draw without its own takes (see the header).
const float* RtShadow::GlassCamera() {
#if BB_GLASS_STATIC_LIVE
    // 1 unless the text starts with 0 (a test knob: flips the fix in one running game)
    static BbLiveKnobs::Knob<bool> on{"BB_GLASS_STATIC_PANES",
                                      [](const char* text) { return text == nullptr || text[0] != '0'; }};
    if (!on.Get()) {
        return nullptr;
    }
#endif
    if (r86f_camera == nullptr) {
        ++r86f_none;
        return nullptr;
    }
    ++r86f_given;
    if (!r86f_said) {
        r86f_said = true;
        std::printf("Ray tracing glass (r86f): a pane draw without camera constants of its own (a static pane: the bottles, jars and windows) took the constants of the frame's main camera, at frame %llu (BB_GLASS_STATIC_PANES 0 leaves such panes out, as before)\n",
                    static_cast<unsigned long long>(frame));
    }
    return r86f_camera;
}

// bbport (r86g_glint-find-bottles): the tests PrepareDraw makes of a pane draw after the glass hook,
// in its order, without their side effects (see the header). 0 (RtGlassFind::Pane): passes them all.
u32 RtShadow::GlassVerdict(const Draw& draw, bool own_constants, char* sample, std::size_t size) const {
    std::array<float, 12> world{};
    const bool camera = draw.constants != nullptr && ToWorld(draw.constants, draw.camera_pass, world);
    if (sample != nullptr && size != 0) {
        const float* p = draw.constants != nullptr ? draw.constants + 52 : nullptr;
        std::snprintf(sample, size, "e.g. idx %u inst %u tri %d ind %d cam %s %s p12-15 %.3g %.3g %.3g %.3g",
                      draw.index_count, draw.instances, draw.triangles ? 1 : 0, draw.indices != 0 ? 1 : 0,
                      draw.constants == nullptr ? "none" : own_constants ? "own" : "voted",
                      camera ? "ok" : "bad", p ? p[12] : 0.0f, p ? p[13] : 0.0f, p ? p[14] : 0.0f,
                      p ? p[15] : 0.0f);
    }
    if (!Wanted()) {
        return RtGlassFind::NotWanted;
    }
    if (draw.camera_pass && !need_scene) {
        return RtGlassFind::NoScene;
    }
    if (draw.constants == nullptr) {
        return RtGlassFind::NoCamera;
    }
    if (!camera) {
        return RtGlassFind::NoWorld;
    }
    if (!draw.triangles) {
        return RtGlassFind::NotTriangles;
    }
    if (draw.indices == 0) {
        return RtGlassFind::NoIndices;
    }
    if (draw.instances == 0) {
        return RtGlassFind::NoInstances;
    }
    if (draw.instances > MaxInstancesPerDraw) {
        return RtGlassFind::ManyInstances;
    }
    return RtGlassFind::Pane;
}

// bbport (r86i_glint-find-gbuffer): see the declaration. The key is the one PrepareDraw makes of a draw with a
// position stream (position_key there): the stream, the index list, the count and first vertex, the instances.
bool RtShadow::GlassBoxMatch(const Draw& draw) const {
    if ((glass_box_count == 0 && glass_pick_count == 0) || draw.skinned || draw.positions == 0) { // bbport (r86l): and the pick's keys
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return true;
        }
    }
    for (u32 i = 0; i < glass_pick_count; ++i) { // bbport (r86l_glint-pick-glass, TOOL): taken by the glass pick
        if (glass_pick_keys[i] == key) {
            return true;
        }
    }
    return false;
}

// bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PAIR, read once.
static const RtGlassFind::BoxPairSpec& BoxPairOfEnv() {
    static const RtGlassFind::BoxPairSpec spec = RtGlassFind::ParseBoxPair(std::getenv("BB_GLASS_BOX_PAIR"));
    return spec;
}

constexpr u32 GlassCandidatesMost = 48; // bbport (r86k): probe entries a frame

// bbport (r86k_glint-box-gbuffer): see the declaration.
bool RtShadow::GlassBoxCandidate(const Draw& draw, u64 vs, u64 ps, bool left_out) {
    if (!glass_box_valid || !glass_box_take) {
        return false;
    }
    const RtGlassFind::BoxPairSpec& pair = BoxPairOfEnv();
    if (pair.set && vs == pair.vs && ps == pair.ps) {
        RtGlassFind::Chain().pair_draws.fetch_add(1, std::memory_order_relaxed);
    }
    if (!left_out || draw.skinned || draw.palette != 0 || draw.positions == 0 || draw.index_count < 24 ||
        draw.index_count > 3000) {
        return false;
    }
    if (frame != glass_cand_frame) {
        glass_cand_frame = frame;
        glass_cand_used = 0;
    }
    if (glass_cand_used >= GlassCandidatesMost) {
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return false; // taken: GlassBoxMatch makes it a box pane
        }
    }
    for (u32 i = 0; i < glass_pick_count; ++i) { // bbport (r86l_glint-pick-glass, TOOL): taken by the glass pick
        if (glass_pick_keys[i] == key) {
            return false;
        }
    }
    for (u32 i = 0; i < glass_box_rejected_count; ++i) {
        if (glass_box_rejected[i] == key) {
            return false;
        }
    }
    ++glass_cand_used;
    RtGlassFind::Chain().probes.fetch_add(1, std::memory_order_relaxed);
    return true;
}

// bbport (r86l_glint-pick-glass, TOOL): see the declaration. A pane taken by the glass pick is a box pane by its key.
bool RtShadow::GlassPickTake(u64 key) {
    if (key == 0) {
        return false;
    }
    for (u32 i = 0; i < glass_pick_count; ++i) {
        if (glass_pick_keys[i] == key) {
            return false;
        }
    }
    if (glass_pick_count >= glass_pick_keys.size()) {
        return false;
    }
    glass_pick_keys[glass_pick_count++] = key;
    return true;
}

// bbport (r86l_glint-pick-glass, TOOL): the entries of a mesh key, plain (the position key) or a pane's (RtGlassKey of it, the
// base PrepareDraw stores). Called from the frame end, on the thread that draws.
u32 RtShadow::GlassPickEntries(u64 key, RtGlassPick::EntryView* out, u32 most) const {
    if (key == 0) {
        return 0;
    }
    const u64 glass_key = RtGlassKey(key);
    u32 total = 0;
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || (e->base != key && e->base != glass_key)) {
            continue;
        }
        if (out != nullptr && total < most) {
            RtGlassPick::EntryView& v = out[total];
            v = {};
            v.mask = e->mask;
            v.glass = (e->mask & RtGlassMask) != 0;
            v.shadow = e->shadow;
            v.moving = e->dynamic;
            v.palette = e->palette != 0;
            v.skinned = e->skinned;
            v.probe = e->box_candidate;
            v.vertices = e->vertices;
            v.triangles = e->triangles;
            v.instances = e->instances;
            v.drawn_recently = e->still_camera_frame + StillNearFrames >= frame;
            const std::array<float, 6>* bounds = nullptr;
            if (e->still_has_ref[0]) {
                bounds = &e->still_ref[0];
                v.source = 'c';
            } else if (e->has_box) {
                bounds = &e->box;
                v.source = 'b';
            } else if (e->still_has_ref[1]) {
                bounds = &e->still_ref[1];
                v.source = 's';
            }
            if (bounds != nullptr && (*bounds)[0] <= (*bounds)[3] && (*bounds)[1] <= (*bounds)[4] &&
                (*bounds)[2] <= (*bounds)[5]) {
                v.has_bounds = true;
                v.bounds = *bounds;
            }
        }
        ++total;
    }
    return total;
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route of the glass pick (rt_glass_tri.h). GlassTriWant: the pick
// named this mesh key under a pane pixel (its last G-buffer draw has a scene entry). The key's solid entry is captured again at
// its next draw (PrepareDraw: a static one is made unbuilt for it) and the build's world positions go to a host slot of the
// surface probe's copy (GlassTriCopy); GlassTriFrameEnd reads them once the GPU is past the copy and the pick's pixels have all
// come (RtGlassTri::GatherFrames after the last), cuts the panels and takes the key (GlassPickTake) with the pane's triangle set
// (GlassTriKeep, which MakeEntry reads). `note` is a line's text for a new want or pixel (null: nothing to say). Frame end, on
// the thread that draws.
bool RtShadow::GlassTriWant(u64 key, s32 x, s32 y, const char*& note) {
    note = nullptr;
    if (!RtGlassTri::On() || key == 0) {
        return false;
    }
    if (!glass_tri) {
        glass_tri = std::make_unique<RtGlassTri::State>();
        char once[1100];
        RtGlassTri::OnceText(once, sizeof(once));
        std::printf("%s\n", once);
        RtGlassTri::OnceTextAim(once, sizeof(once)); // bbport (r86n_glint-aim-panes, TOOL)
        std::printf("%s\n", once);
    }
    RtGlassTri::Want* want = nullptr;
    for (RtGlassTri::Want& w : glass_tri->wants) {
        if (w.stage != 0 && w.key == key) {
            want = &w;
            break;
        }
    }
    if (want == nullptr) {
        for (RtGlassTri::Want& w : glass_tri->wants) {
            if (w.stage == 0) {
                want = &w;
                break;
            }
        }
        if (want == nullptr) {
            note = "not wanted: the table of 4 mesh keys is full";
            return false;
        }
        *want = RtGlassTri::Want{};
        want->key = key;
        want->stage = 1;
        want->since = frame;
        ++glass_tri->asked;
        ++glass_tri_active;
        note = "wanted: its solid entry is captured again at its next draw and its world positions are copied to a host "
               "slot; the panel is cut from the triangle under each pane pixel once the pick's pixels are all in";
    }
    for (u32 i = 0; i < want->pixel_count; ++i) {
        if (want->pixels[i].x == x && want->pixels[i].y == y) {
            return false;
        }
    }
    if (want->stage >= 3) {
        note = "the pane of this mesh key is cut (or failed) already: this pixel is not used (set the pick again after a "
               "new game start)";
        return false;
    }
    if (want->pixel_count >= RtGlassTri::PixelsMost) {
        note = "not used: 8 pixels a mesh key at most";
        return false;
    }
    want->pixels[want->pixel_count++] = {x, y};
    want->last_pixel = frame;
    if (note == nullptr) {
        note = "pixel added to the want";
    }
    return true;
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the triangle set of the pane of a mesh key (its plain key), or null. MakeEntry
// reads it for a pane entry's first draw.
const std::vector<u32>* RtShadow::GlassTriKeep(u64 key) const {
    if (!glass_tri) {
        return nullptr;
    }
    for (const RtGlassTri::Want& w : glass_tri->wants) {
        if (w.stage == 3 && w.key == key) {
            return &w.keep;
        }
    }
    return nullptr;
}

// bbport (r86m_glint-pane-from-triangle, TOOL): this capture build is of the solid entry a want waits for: its world positions
// go to the want's probe slot (ProbeCopyBuild: with the world copies of RecordBuilds, after the unproject pass), and the entry's
// triangle list and the camera of this frame are kept for the pixel projection (the committed camera when no pass camera is
// open). Not for an entry of several instances or more vertices than a slot holds. Asked again at the next capture while the
// copy could not be asked (a slot busy); the wait ends in RtGlassTri::BuildWaitFrames.
void RtShadow::GlassTriCopy(Entry& entry, u64 key, u32 build) {
    for (u32 i = 0; i < RtGlassTri::WantsMost; ++i) {
        RtGlassTri::Want& w = glass_tri->wants[i];
        if (w.stage != 1 || w.key != key) {
            continue;
        }
        if (w.skip != 0) {
            --w.skip;
            continue;
        }
        if (entry.instances != 1 || entry.triangles == 0 || entry.indices.mapped == nullptr ||
            u64(entry.vertices) * entry.instances > ProbeSlotLimit(RtGlassTri::SlotFirst + i)) {
            w.stage = 4;
            ++glass_tri->failed;
            std::printf("GLINT-PROOF glass pick (r86m): mesh key %016llx: its entry cannot be copied (%u instances, %u "
                        "triangles, %u vertices; a slot holds %u vertices and one instance): nothing is taken\n",
                        static_cast<unsigned long long>(key), entry.instances, entry.triangles, entry.vertices,
                        ProbeSlotLimit(RtGlassTri::SlotFirst + i));
            continue;
        }
        const u32 slot = RtGlassTri::SlotFirst + i;
        if (!ProbeCopyBuild(build, slot)) {
            continue;
        }
        const CameraMotion::Matrices pass = camera_motion.PassMatrices();
        const CameraMotion::Matrices committed = pass.valid ? pass : camera_motion.CameraMatrices();
        w.view = committed.view;
        w.proj = committed.proj;
        w.camera_ok = pass.valid || committed.valid;
        w.slot = slot;
        w.vertices = entry.vertices;
        w.triangles = entry.triangles;
        const u32* list = static_cast<const u32*>(entry.indices.mapped);
        w.indices.assign(list, list + std::size_t(entry.triangles) * 3);
        w.stage = 2;
        w.since = frame;
        ++glass_tri->copies;
    }
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the frame end of the triangle route: a want whose copy the GPU has passed (and
// whose pixels have all come) is solved (RtGlassTri::Solve: a panel from the triangle under each pixel, one line each) and its
// mesh key is taken with the union of the panels; a want that waits too long for a capture or a copy is asked again (at most
// RtGlassTri::TriesMost times) or fails with a line. The counters' line every 600 frames.
void RtShadow::GlassTriFrameEnd() {
    RtGlassTri::State& s = *glass_tri;
    const auto fail = [&](RtGlassTri::Want& w, const char* why) {
        w.stage = 4;
        ++s.failed;
        std::printf("GLINT-PROOF glass pick (r86m): mesh key %016llx: %s\n", static_cast<unsigned long long>(w.key), why);
    };
    const auto again = [&](RtGlassTri::Want& w, const char* why) {
        ProbeForget(w.slot);
        if (++w.tries > RtGlassTri::TriesMost) {
            fail(w, why);
            return;
        }
        w.stage = 1;
        w.since = frame;
        w.skip = w.tries; // a mesh drawn several times: the next copy is of a later capture, maybe the instance at the pixel
        ++s.retried;
    };
    for (RtGlassTri::Want& w : s.wants) {
        if (w.stage == 1) {
            if (frame > w.since + RtGlassTri::BuildWaitFrames) {
                fail(w, "no capture of the entry's draw came in 600 frames (the entry is not drawn by the camera pass, or "
                        "nothing could be built): nothing is taken");
            }
            continue;
        }
        if (w.stage != 2) {
            continue;
        }
        u64 tick = 0;
        const float* world = ProbeWorld(w.slot, tick);
        if (tick == ProbeDroppedTick) {
            again(w, "the build kept being dropped before it was recorded: nothing is taken");
            continue;
        }
        if (world == nullptr || tick == 0 || !scheduler.IsFree(tick)) {
            if (frame > w.since + RtGlassTri::CopyWaitFrames) {
                again(w, "the copy of the world positions did not come: nothing is taken");
            }
            continue;
        }
        if (frame < w.last_pixel + RtGlassTri::GatherFrames) {
            continue; // more pixels of the pick may still come
        }
        const RtGlassTri::Solved solved =
            RtGlassTri::Solve(w, world, [](const char* text) { std::printf("%s\n", text); });
        ProbeForget(w.slot);
        s.panels += solved.panels;
        if (solved.panels == 0 && solved.refused == 0 && solved.same == 0 && solved.missed == w.pixel_count) {
            again(w, "no triangle of the copied instances covers a pixel of the pick (tried the next capture of the mesh each "
                     "time): nothing is taken");
            continue;
        }
        if (solved.keep.empty()) {
            fail(w, "no panel could be cut from the pixels (see the lines above): nothing is taken");
            continue;
        }
        if (!RtGlassOn()) {
            fail(w, "BB_RT_GLASS is off: nothing is taken (set it, for example auto)");
            continue;
        }
        for (const RtGlassTri::PaneInfo& pane : solved.panes) { // bbport (r86n_glint-aim-panes, TOOL): for the glint pass's lamp log
            RtGlassTri::AddPane(pane);
        }
        w.keep = solved.keep;
        w.stage = 3;
        s.kept += static_cast<u32>(w.keep.size());
        const bool joined = GlassPickTake(w.key);
        std::printf("GLINT-PROOF glass pick (r86m): pane taken: mesh key %016llx keeps %zu of %u triangles in %u panel(s) (%u "
                    "pixels, %u in a panel already, %u without a triangle, %u refused); %s: its next draws are pane records "
                    "of those triangles only, the solid entry of the mesh is replaced by them\n",
                    static_cast<unsigned long long>(w.key), w.keep.size(), w.triangles, solved.panels, w.pixel_count,
                    solved.same, solved.missed, solved.refused,
                    joined ? "the key joined the pane keys" : "the key was a pane key already");
    }
    glass_tri_active = 0;
    for (const RtGlassTri::Want& w : s.wants) {
        glass_tri_active += w.stage == 1 || w.stage == 2 ? 1u : 0u;
    }
    if (frame % 600 == 0) {
        char line[300];
        RtGlassTri::CounterLine(s, frame, line, sizeof(line));
        std::printf("%s\n", line);
    }
}

// bbport (r86l_glint-pick-glass, TOOL): the five knobs' texts, asked again when the live knobs' generation changed (without the
// test tools' knobs file: once, from the environment).
bool RtShadow::GlassPickRead(RtGlassPick::Texts& texts) {
#if BB_GLASS_STATIC_LIVE
    const u32 generation = BbLiveKnobs::Generation();
#else
    const u32 generation = 0;
#endif
    if (generation == glass_pick_gen) {
        return false;
    }
    glass_pick_gen = generation;
    static const char* const names[5] = {"BB_GLASS_PICK", "BB_GLASS_PICK_SIZE", "BB_GLASS_PICK_FRAME", "BB_GLASS_PICK_REPEAT",
                                         "BB_GLASS_PICK_PANES"};
    char* const dest[5] = {texts.list, texts.size, texts.frame, texts.repeat, texts.panes};
    const std::size_t room[5] = {sizeof(texts.list), sizeof(texts.size), sizeof(texts.frame), sizeof(texts.repeat),
                                 sizeof(texts.panes)};
    for (int i = 0; i < 5; ++i) {
#if BB_GLASS_STATIC_LIVE
        const BbLiveKnobs::Text text = BbLiveKnobs::Lookup(names[i]);
        const char* value = text.Get();
#else
        const char* value = std::getenv(names[i]);
#endif
        std::snprintf(dest[i], room[i], "%s", value != nullptr ? value : "");
    }
    return true;
}

// bbport (r86i_glint-find-gbuffer): see the declaration. The entries are those of the ray traced scene (solid
// draws): a cut-out or blended draw has none, the area lines are for those. Their world bounds: the camera
// pass capture's first look (BB_RT_STILL), else the sun VSM's, else the sun pass's; the pass camera projects
// them (CameraMotion::PassMatrices: world to view and the projection's scales).
void RtShadow::GlassFindBox() {
    // bbport (r86j_glint-same-game): BB_GLASS_BOX_PANES asked again with the live knobs (a job's set:), else once
#if BB_GLASS_STATIC_LIVE
    static BbLiveKnobs::Knob<bool> take_knob{"BB_GLASS_BOX_PANES", [](const char* text) {
                                                 return text != nullptr && text[0] == '1' && text[1] == '\0';
                                             }};
    const bool take = take_knob.Get();
#else
    const bool take = RtGlassFind::BoxPanes();
#endif
    glass_box_take = take; // bbport (r86k_glint-box-gbuffer): GlassBoxCandidate reads it
#if BB_GLASS_STATIC_LIVE
    const u32 generation = BbLiveKnobs::Generation();
#else
    const u32 generation = 0;
#endif
    if (generation != glass_box_gen) {
        glass_box_gen = generation;
#if BB_GLASS_STATIC_LIVE
        const BbLiveKnobs::Text text = BbLiveKnobs::Lookup("BB_GLASS_FIND_BOX");
        const char* box_text = text.Get();
#else
        const char* box_text = std::getenv("BB_GLASS_FIND_BOX");
#endif
        const RtGlassFind::PictureBox box = RtGlassFind::ParseBox(box_text);
        // (review) another box or none: the meshes the old box took are forgotten (an unrelated live
        // knob that leaves the box as it was keeps them)
        if (!take || box.valid != glass_box_valid || // bbport (r86j): panes switched off: the keys go
            (box.valid && glass_box_px != std::array<s32, 4>{box.x0, box.y0, box.x1, box.y1})) {
            glass_box_count = 0;
            glass_box_rejected_count = 0; // bbport (r86k_glint-box-gbuffer)
        }
        glass_box_valid = box.valid;
        glass_box_px = {box.x0, box.y0, box.x1, box.y1};
        if (box.valid) {
            glass_box_due = frame + 90;
            std::printf("GLINT-PROOF box set: BB_GLASS_FIND_BOX %d,%d-%d,%d of the 1920x1080 picture: the camera pass entries in it are listed at frame %llu (and at every find report frame)\n",
                        box.x0, box.y0, box.x1, box.y1, static_cast<unsigned long long>(glass_box_due));
        } else if (box_text != nullptr && box_text[0] != '\0') {
            std::printf("GLINT-PROOF box set: BB_GLASS_FIND_BOX '%s' is not x0:y0:x1:y1 (x0 < x1 <= 1920, y0 < y1 <= 1080): ignored\n",
                        box_text);
        }
    }
    // bbport (r86j_glint-same-game): every 300 frames, once the box is set or a box pane was drawn: the chain
    {
        static u64 chain_last = 0;
        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();
        const auto load_of = [](const std::atomic<std::uint64_t>& v) {
            return static_cast<unsigned long long>(v.load(std::memory_order_relaxed));
        };
        if ((glass_box_valid || load_of(chain.matched) != 0) && frame / 300 != chain_last / 300) {
            chain_last = frame;
            std::printf("GLINT-PROOF chain at frame %llu: box %s, mesh keys %u | G-buffer draws of those meshes %llu: pane record made %llu, none made %llu | camera pass draws without camera constants %llu | glint noted %llu, run after the blended draws %llu, at the fog composite %llu (all since the start)\n",
                        static_cast<unsigned long long>(frame), glass_box_valid ? "set" : "not set", glass_box_count,
                        load_of(chain.matched), load_of(chain.recorded), load_of(chain.not_recorded),
                        load_of(chain.no_constants), load_of(chain.noted), load_of(chain.after_blended),
                        load_of(chain.after_composite));
            // bbport (r86k_glint-box-gbuffer): the probe entries
            std::printf("GLINT-PROOF chain probes at frame %llu: G-buffer draws made probe entries %llu (a cut-out or not solid, which PrepareDraw gives no entry; at most %u a frame), probe meshes judged outside the box %u; draws of the BB_GLASS_BOX_PAIR pair seen with a box set %llu (all since the start)\n",
                        static_cast<unsigned long long>(frame), load_of(chain.probes), GlassCandidatesMost,
                        glass_box_rejected_count, load_of(chain.pair_draws));
        }
    }
    if (!glass_box_valid) {
        return;
    }
    if (!RtGlassFind::ReportFrame(frame) && !(glass_box_due != 0 && frame >= glass_box_due)) {
        return;
    }
    const bool due_report = glass_box_due != 0 && frame >= glass_box_due; // bbport (r86j_glint-same-game)
    glass_box_due = 0;
    // bbport (r86k_glint-box-gbuffer): this runs at the frame end, after CameraMotion::OnDisplayPass committed the
    // frame's camera and closed the pass camera (pass_has_camera false): PassMatrices() was never valid here (b52:
    // "no camera pass matrices yet" at every report). The committed camera is the last G-buffer pass's: the view and
    // projection the pass had.
    auto camera = camera_motion.PassMatrices();
    bool committed_camera = false;
    if (!camera.valid) {
        camera = camera_motion.CameraMatrices();
        camera.valid = camera.proj[0] != 0.0f && camera.proj[1] != 0.0f && std::isfinite(camera.proj[0]) &&
                       std::isfinite(camera.proj[1]) &&
                       std::ranges::all_of(camera.view, [](float v) { return std::isfinite(v); });
        committed_camera = camera.valid;
    }
    if (!camera.valid) {
        std::printf("GLINT-PROOF box at frame %llu: no camera matrices yet (the scene holds %zu entries)\n",
                    static_cast<unsigned long long>(frame), entries.size());
        return;
    }
    static bool committed_said = false;
    if (committed_camera && !committed_said) {
        committed_said = true;
        std::printf("GLINT-PROOF box camera: the pass camera is closed at the frame end (r86j read it there: never valid); the frame's committed camera is used, from frame %llu\n",
                    static_cast<unsigned long long>(frame));
    }
    // bbport (r86j_glint-same-game): `take` is read at the top of the function (live)
    static const float size_max = RtGlassFind::ParseBoxSize(std::getenv("BB_GLASS_BOX_SIZE"));
    const RtGlassFind::PictureBox picture{glass_box_px[0], glass_box_px[1], glass_box_px[2], glass_box_px[3], true};
    struct Row {
        const Entry* entry;
        const std::array<float, 6>* bounds;
        RtGlassFind::BoxHit hit;
        float diagonal;
        bool pane;
        bool cand; // bbport (r86k_glint-box-gbuffer): a probe entry
    };
    std::vector<Row> rows;
    u32 drawn = 0, bounded = 0, behind = 0;
    // bbport (r86k_glint-box-gbuffer): a probe mesh seen outside the box is not probed again; the pair the
    // report says something of (BB_GLASS_BOX_PAIR)
    const auto reject = [&](const Entry& e) {
        const u64 key = RtGlassKey(e.base); // a probe entry is a glass entry: its base carries the salt
        for (u32 i = 0; i < glass_box_rejected_count; ++i) {
            if (glass_box_rejected[i] == key) {
                return;
            }
        }
        if (glass_box_rejected_count < glass_box_rejected.size()) {
            glass_box_rejected[glass_box_rejected_count++] = key;
        }
    };
    const RtGlassFind::BoxPairSpec& pair = BoxPairOfEnv();
    u32 pair_drawn = 0, pair_bounded = 0, pair_front = 0, pair_overlap = 0, pair_inside = 0, pair_shown = 0;
    std::array<RtGlassFind::BoxHit, 4> pair_hit{};
    std::array<float, 4> pair_diag{};
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || e->gone || e->skinned || e->vertices == 0 ||
            e->still_camera_frame + StillNearFrames < frame) {
            continue;
        }
        ++drawn;
        const bool pair_entry = pair.set && e->find_vs == pair.vs && e->find_ps == pair.ps; // bbport (r86k)
        pair_drawn += pair_entry ? 1u : 0u;
        const std::array<float, 6>* bounds = e->still_has_ref[0] ? &e->still_ref[0]
                                             : e->has_box          ? &e->box
                                             : e->still_has_ref[1] ? &e->still_ref[1]
                                                                   : nullptr;
        if (bounds == nullptr || !((*bounds)[0] <= (*bounds)[3] && (*bounds)[1] <= (*bounds)[4] &&
                                   (*bounds)[2] <= (*bounds)[5])) {
            continue;
        }
        ++bounded;
        const RtGlassFind::BoxHit hit = RtGlassFind::BoxOfBounds(camera.view, camera.proj, *bounds, picture);
        if (pair_entry) { // bbport (r86k_glint-box-gbuffer)
            ++pair_bounded;
            if (hit.seen) {
                ++pair_front;
                pair_overlap += hit.inside > 0.0f ? 1u : 0u;
                pair_inside += hit.inside >= 0.6f ? 1u : 0u;
                if (pair_shown < pair_hit.size()) {
                    pair_hit[pair_shown] = hit;
                    pair_diag[pair_shown++] = std::sqrt(((*bounds)[3] - (*bounds)[0]) * ((*bounds)[3] - (*bounds)[0]) +
                                                       ((*bounds)[4] - (*bounds)[1]) * ((*bounds)[4] - (*bounds)[1]) +
                                                       ((*bounds)[5] - (*bounds)[2]) * ((*bounds)[5] - (*bounds)[2]));
                }
            }
        }
        if (!hit.seen) {
            ++behind;
            continue;
        }
        if (!(hit.inside > 0.0f)) {
            if (e->box_candidate && take) { // bbport (r86k_glint-box-gbuffer): seen, bounds known, outside the box
                reject(*e);
            }
            continue;
        }
        const float dx = (*bounds)[3] - (*bounds)[0], dy = (*bounds)[4] - (*bounds)[1],
                    dz = (*bounds)[5] - (*bounds)[2];
        rows.push_back({e, bounds, hit, std::sqrt(dx * dx + dy * dy + dz * dz), (e->mask & RtGlassMask) != 0,
                        e->box_candidate});
    }
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        return a.hit.inside != b.hit.inside ? a.hit.inside > b.hit.inside : a.diagonal < b.diagonal;
    });
    u32 small_inside = 0, taken_now = 0;
    for (const Row& r : rows) {
        if ((r.pane && !r.cand) || !RtGlassFind::BoxTakes(r.hit, r.diagonal, size_max, r.entry->triangles)) {
            if (r.cand && take) { // bbport (r86k_glint-box-gbuffer): a probe mesh the box rule does not take
                reject(*r.entry);
            }
            continue;
        }
        ++small_inside;
        if (!take || r.entry->base == 0) {
            continue;
        }
        // bbport (r86k_glint-box-gbuffer): a probe entry is a glass entry (its base has RtGlassKey's salt); the
        // box keys are the plain position keys GlassBoxMatch makes of a draw
        const u64 take_key = r.cand ? RtGlassKey(r.entry->base) : r.entry->base;
        bool known = false;
        for (u32 i = 0; i < glass_box_count; ++i) {
            known = known || glass_box_keys[i] == take_key;
        }
        if (!known && glass_box_count < glass_box_keys.size()) {
            glass_box_keys[glass_box_count++] = take_key;
            ++taken_now;
        }
    }
    std::printf("GLINT-PROOF box %d,%d-%d,%d at frame %llu: mesh keys taken %u (+%u), %zu entries overlap it, %u of them mostly inside and under %.2f m across (%s); the scene holds %zu entries in all, the camera pass drew %u of them in the last %u frames, %u have bounds, %u of those are behind or at the camera; camera pass draws left out for no camera constants %llu so far\n",
                picture.x0, picture.y0, picture.x1, picture.y1, static_cast<unsigned long long>(frame),
                glass_box_count, taken_now, rows.size(), small_inside, size_max,
                take ? "BB_GLASS_BOX_PANES takes them" : "BB_GLASS_BOX_PANES off: log only", entries.size(), drawn,
                StillNearFrames, bounded, behind,
                static_cast<unsigned long long>(RtGlassFind::Chain().no_constants.load(std::memory_order_relaxed)));
    // bbport (r86j): the report a new box asked for lists 12 entries, the periodic ones 3 (the log keeps few)
    for (std::size_t n = 0; n < rows.size() && n < (due_report ? std::size_t{12} : std::size_t{3}); ++n) {
        const Row& r = rows[n];
        const Entry& e = *r.entry;
        const std::array<float, 6>& b = *r.bounds;
        std::printf("GLINT-PROOF box entry %llx:%llx key %llx: %.0f%% inside, %.2f m (%.2f x %.2f x %.2f), rect %.0f,%.0f-%.0f,%.0f, %u triangles %u vertices %u instances%s%s%s%s | draw: %u indices%s%s%s%s\n",
                    static_cast<unsigned long long>(e.find_vs), static_cast<unsigned long long>(e.find_ps),
                    static_cast<unsigned long long>(e.base), double(r.hit.inside) * 100.0, r.diagonal,
                    b[3] - b[0], b[4] - b[1], b[5] - b[2], r.hit.x0, r.hit.y0, r.hit.x1, r.hit.y1, e.triangles,
                    e.vertices, e.instances, r.pane ? " pane" : "", e.palette != 0 ? " palette" : "",
                    e.shadow ? " sun pass too" : "", e.dynamic ? " moving" : "", e.find_indices,
                    (e.find_flags & RtGlassFind::FlagBlend) != 0 ? " blend" : "",
                    (e.find_flags & RtGlassFind::FlagZWrite) != 0 ? " zwrite" : (e.find_flags & RtGlassFind::FlagNoZWrite) != 0 ? " nozwrite" : "",
                    (e.find_flags & RtGlassFind::FlagDiscard) != 0 ? " discard" : "",
                    e.box_candidate ? " (probe entry: PrepareDraw gives such a draw none)" : "");
    }
    // bbport (r86k_glint-box-gbuffer): is the BB_GLASS_BOX_PAIR pair in the box
    if (pair.set) {
        std::printf("GLINT-PROOF box pair %llx:%llx at frame %llu: G-buffer draws of it seen with a box set %llu; entries of it the camera pass drew in the last %u frames %u (%u with bounds, %u in front of the camera, %u overlap the box, %u mostly inside it)%s\n",
                    static_cast<unsigned long long>(pair.vs), static_cast<unsigned long long>(pair.ps),
                    static_cast<unsigned long long>(frame),
                    static_cast<unsigned long long>(RtGlassFind::Chain().pair_draws.load(std::memory_order_relaxed)),
                    StillNearFrames, pair_drawn, pair_bounded, pair_front, pair_overlap, pair_inside,
                    pair_drawn == 0 ? " (no entry: the pair is not a solid G-buffer draw, or is blended, or is a forward draw)" : "");
        for (u32 n = 0; n < pair_shown; ++n) {
            std::printf("GLINT-PROOF box pair entry %u: rect %.0f,%.0f-%.0f,%.0f, %.0f%% inside the box, %.2f m across\n",
                        n, pair_hit[n].x0, pair_hit[n].y0, pair_hit[n].x1, pair_hit[n].y1,
                        double(pair_hit[n].inside) * 100.0, double(pair_diag[n]));
        }
    }
}

bool RtShadow::LampAffineTopology(const Draw& draw) {
    static_assert(std::endian::native == std::endian::little);
    const std::span raw{reinterpret_cast<const u16*>(draw.indices), RtLampPane::DrawIndices};
    const u64 raw_hash = XXH64(raw.data(), raw.size_bytes(), 0);
    if (lamp_affine_bits.buffer) {
        return raw_hash == lamp_affine_raw_hash;
    }
    // Verify the normalized index list used by MakeEntry before a raw hash can be reused.
    const auto [lo, hi] = std::ranges::minmax(raw);
    if (lo != 0 || hi != LampAffineVertices - 1) {
        return false;
    }
    std::vector<u32> normalized;
    normalized.reserve(raw.size());
    if (!AppendTriangles(raw, false, false, lo, normalized) || normalized.size() != raw.size() ||
        XXH64(normalized.data(), normalized.size() * sizeof(u32), 0) != LampAffineTopologyHash) {
        return false;
    }
    if (!Make(lamp_affine_bits, LampAffineBitWords * sizeof(u32), true,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) || !lamp_affine_bits.mapped) {
        Free(lamp_affine_bits);
        lamp_affine_pipeline.reset();
        return false;
    }
    std::array<u32, LampAffineBitWords> bits{};
    for (const u32 index : normalized) {
        bits[index / 32] |= 1u << (index % 32);
    }
    // This coherent allocation is immutable after publication. Queue submission makes the
    // initial mapped writes visible to the affine compute shader.
    std::memcpy(lamp_affine_bits.mapped, bits.data(), sizeof(bits));
    lamp_affine_raw_hash = raw_hash;
    return true;
}

void RtShadow::ResetBottlePass(const std::array<u64, 3>& targets) {
    if (bottle_cold && (bottle_pass_frame == frame || bottle_targets != targets)) {
        DiscardBottleCold();
    }
    bottle_targets = targets;
    bottle_pass_frame = frame;
    bottle_entry = nullptr;
    bottle_entry_address = 0;
    bottle_recorded_frame = ~u64{0};
    bottle_scene_frame = ~u64{0};
    bottle_ambiguous = false;
    bottle_draw_seen = false;
}

namespace ReflectionFirstHit {
bool PlacedLifecycleOn();
void TracePlacedLifecycle(PlacedSource, std::string_view reason, u64 frame, u64 pass,
                          u64 allocation, u64 revision, u64 cookie, u64 a, u64 b);
}

namespace {
constexpr u32 ReflectionTrackLimit = 512;

bool ExactMirror(u64 vs, u64 ps, u32 count, u32 first) {
    return vs == 0x9da6aacb && ps == 0xca7226ec && count == 24 && first == 2440816;
}

bool ExactFireplace(u64 vs, u64 ps, u32 count, u32 first) {
    return vs == 0x9da6aacb && ps == 0xbb10e440 && count == 18282 && first == 158744;
}

constexpr std::string_view ReflectionFireplaceDigest =
    "be38ecf6afb2e8b90791cf61011ce8d5c7098fcd6ba3bb20b668cef4a73fd26f";
constexpr std::string_view ReflectionWallDigest =
    "00f7ea51aaf41a8ea9faffd22caee1da5bb04737f9fc0f6790f042af31d54e4f";
constexpr std::string_view ReflectionMirrorDigest =
    "c4ba3f63d6523b00006da56b37d1e4a93bcca6e6d6d73e3cc5d33d6cb0068773";

template <typename Index>
bool BoundReflectionIndices(const RtShadow::Draw& draw, u32 lo, std::span<const u32> built) {
    const auto* raw = reinterpret_cast<const Index*>(draw.indices);
    for (std::size_t i = 0; i < built.size(); ++i) {
        if (u32(raw[i]) < lo || u32(raw[i]) - lo != built[i]) {
            return false;
        }
    }
    return true;
}

u8 HexNybble(char c) {
    return u8(c >= 'a' ? c - 'a' + 10 : c - '0');
}
} // namespace

void RtShadow::ReflectionAttach(ReflectionFirstHit::Pass* pass) {
    if (!pass) {
        reflection_tracker.reset();
    } else if (!reflection_tracker) {
        reflection_tracker = std::make_unique<ReflectionTracker>();
        reflection_tracker->pass = pass;
        reflection_tracker->tracks.reserve(ReflectionTrackLimit);
    }
}

void RtShadow::ReflectionCloseEpoch() {
    auto& tracking = *reflection_tracker;
    tracking.pass->CloseEpoch();
    tracking.stamp.reset();
    tracking.tracks.clear();
    tracking.last_flushed = 0;
}

bool RtShadow::ReflectionBeginPass(const ReflectionFirstHit::Stamp& stamp) {
    auto& tracking = *reflection_tracker;
    if (tracking.stamp && tracking.stamp->generation != stamp.generation) {
        ReflectionCloseEpoch();
    }
    if (!tracking.pass->BeginPass(stamp)) {
        ReflectionCloseEpoch();
        return false;
    }
    if (!tracking.stamp || tracking.stamp->pass != stamp.pass) {
        tracking.stamp = stamp;
        tracking.mirror_direct = 0;
        tracking.mirror_joined = 0;
        tracking.fireplace_direct = 0;
        tracking.wall_shape_direct = 0;
        tracking.placed_direct = {};
        tracking.placed_joined = {};
        tracking.direct = 0;
        tracking.joined = 0;
    }
    return true;
}

bool RtShadow::ReflectionStatic(const Entry& entry, ReflectionFirstHit::PlacedSource source) {
    const bool placed = source != ReflectionFirstHit::PlacedSource::None;
    return entry.handle && entry.address && entry.reflection_creation_size && entry.instances == 1 &&
           !entry.shadow && !entry.dynamic && !entry.rebuilt && !entry.copied &&
           !entry.skinned && !entry.skeleton_bones && entry.palette_placed == placed &&
           (placed ? entry.palette != 0 : (!entry.palette || entry.instance)) &&
           !entry.card_shadow && !entry.card_camera && !entry.card_mesh && !entry.card_uv &&
           !entry.glass_light && !entry.still_moved && !entry.still_doubt && !entry.gone;
}

void RtShadow::ReflectionObserve(Entry& entry, const Draw& draw, bool eligible) {
    auto& tracking = *reflection_tracker;
    auto found = tracking.tracks.find(&entry);
    auto* token = draw.reflection;
    const bool good = tracking.stamp && tracking.stamp->frame == frame && token && token->placement &&
                      eligible && ReflectionStatic(entry, token->placed) && draw.indices && entry.indices.mapped &&
                      draw.index_count == entry.triangles * 3 &&
                      entry.first_vertex == u32(s64(token->min_index) + s32(draw.first_vertex)) &&
                      entry.vertices == token->max_index - token->min_index + 1 &&
                      entry.palette == draw.palette &&
                      (draw.index_size == 2 || draw.index_size == 4);
    if (!good) {
        if (ReflectionFirstHit::PlacedLifecycleOn()) {
            using ReflectionFirstHit::PlacedSource;
            const auto* proof = found == tracking.tracks.end() ? nullptr : &found->second;
            const auto role = proof && proof->observed.placed != PlacedSource::None ? proof->observed.placed
                            : token ? token->placed : PlacedSource::None;
            if (role != PlacedSource::None) {
                // value_a: stamp, token, eligibility, static, ranges, count, base vertex, span,
                // palette and index width. value_b: actual ordinary draw/entry state.
                const u32 failures = u32(!tracking.stamp || tracking.stamp->frame != frame) |
                    (u32(!token || !token->placement) << 1) | (u32(!eligible) << 2) |
                    (u32(!ReflectionStatic(entry, role)) << 3) | (u32(!draw.indices || !entry.indices.mapped) << 4) |
                    (u32(draw.index_count != entry.triangles * 3) << 5) |
                    (u32(token && entry.first_vertex != u32(s64(token->min_index) + s32(draw.first_vertex))) << 6) |
                    (u32(token && entry.vertices != token->max_index - token->min_index + 1) << 7) |
                    (u32(entry.palette != draw.palette) << 8) |
                    (u32(draw.index_size != 2 && draw.index_size != 4) << 9);
                const u32 state = u32(draw.camera_pass) | (u32(draw.shadow_pass) << 1) |
                    (u32(entry.built) << 2) | (u32(entry.blas) << 3) | (u32(entry.instance) << 4) |
                    (u32(entry.shadow) << 5) | (u32(entry.dynamic) << 6) | (u32(entry.rebuilt) << 7) |
                    (u32(entry.copied) << 8) | (u32(entry.skinned || entry.skeleton_bones) << 9) |
                    (u32(entry.card_shadow || entry.card_camera || entry.card_mesh || entry.card_uv) << 10) |
                    (u32(entry.glass_light) << 11) | (u32(entry.still_moved) << 12) |
                    (u32(entry.still_doubt) << 13) | (u32(entry.gone) << 14) |
                    (u32(entry.palette_placed) << 15) | (u32(entry.seen_frame == frame) << 16);
                const char* why = !eligible && draw.shadow_pass ? "observe-ineligible-shadow" : "observe-refused";
                ReflectionFirstHit::TracePlacedLifecycle(role, why, frame, tracking.stamp ? tracking.stamp->pass : 0,
                    proof ? proof->observed.allocation : 0, proof ? proof->resident.revision : 0,
                    proof ? proof->cookie : 0, failures, state);
            }
        }
        if (found != tracking.tracks.end()) {
            tracking.pass->InvalidateAllocation(found->second.observed.allocation);
            found->second.resident = {};
            found->second.cookie = 0;
            ++tracking.changed;
        }
        return;
    }
    const auto built = std::span{static_cast<const u32*>(entry.indices.mapped), draw.index_count};
    const bool topology = draw.index_size == 2
        ? BoundReflectionIndices<u16>(draw, token->min_index, built)
        : BoundReflectionIndices<u32>(draw, token->min_index, built);
    if (!topology) {
        const auto* proof = found == tracking.tracks.end() ? nullptr : &found->second;
        ReflectionFirstHit::TracePlacedLifecycle(token->placed, "observe-normalized-indices", frame,
            tracking.stamp->pass, proof ? proof->observed.allocation : 0,
            proof ? proof->resident.revision : 0, proof ? proof->cookie : 0,
            draw.index_count, draw.index_size);
        if (found != tracking.tracks.end()) {
            tracking.pass->InvalidateAllocation(found->second.observed.allocation);
            found->second.resident = {};
            found->second.cookie = 0;
        }
        ++tracking.changed;
        return;
    }
    const std::array<u64, 5> source{entry.base, entry.mesh, draw.indices, draw.positions, token->first};
    const u64 surface = XXH3_64bits(source.data(), sizeof(source));
    if (surface == 0) {
        return;
    }
    if (found == tracking.tracks.end()) {
        if (tracking.tracks.size() == ReflectionTrackLimit) {
            ++tracking.track_limit;
            return;
        }
        found = tracking.tracks.try_emplace(&entry).first;
        found->second.observed.allocation = ++tracking.allocation;
    }
    auto& attestation = found->second;
    if (attestation.placement != token->placement || attestation.observed.surface != surface ||
        attestation.observed.vs != draw.shader || attestation.observed.ps != draw.pixel_shader ||
        attestation.observed.placed != token->placed || attestation.address != entry.address) {
        const u64 allocation = attestation.observed.allocation;
        if (token->placement_delta.enabled && attestation.resident.revision &&
            attestation.placement != token->placement) {
            auto& prior = token->placement_delta;
            prior.key = attestation.placement;
            prior.cookie = attestation.cookie;
            prior.revision = attestation.resident.revision;
            prior.pass = attestation.confirmed_pass;
            prior.same_identity = attestation.observed.surface == surface &&
                attestation.observed.vs == draw.shader && attestation.observed.ps == draw.pixel_shader &&
                attestation.observed.placed == token->placed && attestation.address == entry.address;
        }
        ReflectionFirstHit::TracePlacedLifecycle(token->placed,
            attestation.observed.surface ? "observe-identity-change" : "observe-track-created", frame,
            tracking.stamp->pass, allocation, attestation.resident.revision, attestation.cookie,
            attestation.observed.surface != surface, attestation.placement != token->placement);
        tracking.pass->InvalidateAllocation(allocation);
        tracking.pass->ObserveSurface(surface, token->placement);
        attestation.resident = {};
        attestation.address = entry.address;
        attestation.placement = token->placement;
        auto& id = attestation.observed;
        id = {.surface = surface, .allocation = allocation, .placement = token->placement,
              .vs = u32(draw.shader), .ps = u32(draw.pixel_shader), .count = draw.index_count,
              .first = token->first,
              .receiver = ExactMirror(draw.shader, draw.pixel_shader, draw.index_count, token->first),
              .placed = token->placed};
        const auto hash = sha256_hex(reinterpret_cast<const u8*>(built.data()), built.size_bytes());
        id.wall_witness = id.count == 42441 && hash == ReflectionWallDigest;
        for (u32 i = 0; i < id.topology_sha256.size(); ++i) {
            id.topology_sha256[i] = u8((HexNybble(hash[2 * i]) << 4) | HexNybble(hash[2 * i + 1]));
        }
        if ((id.receiver && hash != ReflectionMirrorDigest) ||
            (ExactFireplace(id.vs, id.ps, id.count, id.first) && hash != ReflectionFireplaceDigest) ||
            (id.vs != 0x9da6aacb && !id.wall_witness)) {
            ReflectionFirstHit::TracePlacedLifecycle(token->placed, "observe-topology-fingerprint", frame,
                tracking.stamp->pass, allocation, 0, attestation.cookie, id.count, id.first);
            attestation.observed.surface = 0;
            ++tracking.refused;
            return;
        }
    }
    token->entry = &entry;
    token->allocation = attestation.observed.allocation;
    attestation.cookie = token->cookie = ++tracking.cookie;
}

void RtShadow::ReflectionQueue(Entry& entry, const Draw& draw, Build& build) {
    const auto found = reflection_tracker->tracks.find(&entry);
    if (found == reflection_tracker->tracks.end()) {
        return;
    }
    auto& proof = found->second;
    ++proof.pending;
    if (proof.observed.placed != ReflectionFirstHit::PlacedSource::None) {
        // A queued replacement makes the prior placement uncertain even if capture is later dropped.
        const auto& stamp = reflection_tracker->stamp;
        ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "ordinary-queue", frame,
            stamp ? stamp->pass : 0, proof.observed.allocation, proof.resident.revision,
            draw.reflection ? draw.reflection->cookie : 0, build.param, build.update);
        reflection_tracker->pass->InvalidateAllocation(proof.observed.allocation);
        proof.resident = {};
    }
    if (draw.reflection) {
        build.reflection_cookie = draw.reflection->cookie;
    }
}

void RtShadow::ReflectionDropCapture(const Build& build) {
    const auto found = reflection_tracker->tracks.find(build.entry);
    if (found != reflection_tracker->tracks.end() && found->second.pending) {
        const auto& proof = found->second;
        const auto& stamp = reflection_tracker->stamp;
        const u32 state = u32(build.left_out) | (u32(build.probe) << 1) |
                          (u32(build.uv_only) << 2) | (u32(need_scene) << 3);
        ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "ordinary-build-dropped", frame,
            stamp ? stamp->pass : 0, proof.observed.allocation, proof.resident.revision,
            build.reflection_cookie, build.param, state);
        --found->second.pending;
        ++reflection_tracker->dropped;
    }
}

void RtShadow::ReflectionBuild(Entry& entry, const Build& build) {
    auto& tracking = *reflection_tracker;
    const auto found = tracking.tracks.find(&entry);
    if (found == tracking.tracks.end()) {
        return;
    }
    auto& proof = found->second;
    proof.pending -= proof.pending != 0;
    // Runs only for a real native build/refit appended to the immutable ordinary job.
    tracking.pass->InvalidateAllocation(proof.observed.allocation);
    const u64 revision = ++tracking.revision;
    proof.resident = {};
    ++tracking.scheduled;
    if (!tracking.stamp || !build.reflection_cookie || build.reflection_cookie != proof.confirmed ||
        proof.confirmed_pass != tracking.stamp->pass || proof.direct_count != 1 ||
        build.lamp_affine || build.uv_only || !ReflectionStatic(entry, proof.observed.placed) ||
        proof.address != entry.address || !proof.observed.surface) {
        if (proof.observed.placed != ReflectionFirstHit::PlacedSource::None && ReflectionFirstHit::PlacedLifecycleOn()) {
            const u32 failures = u32(!tracking.stamp) | (u32(!build.reflection_cookie) << 1) |
                (u32(build.reflection_cookie != proof.confirmed) << 2) |
                (u32(tracking.stamp && proof.confirmed_pass != tracking.stamp->pass) << 3) |
                (u32(proof.direct_count != 1) << 4) | (u32(build.lamp_affine) << 5) |
                (u32(build.uv_only) << 6) | (u32(!ReflectionStatic(entry, proof.observed.placed)) << 7) |
                (u32(proof.address != entry.address) << 8) | (u32(!proof.observed.surface) << 9);
            ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "ordinary-build-attestation-refused",
                frame, tracking.stamp ? tracking.stamp->pass : 0, proof.observed.allocation,
                revision, build.reflection_cookie, failures, proof.confirmed);
        }
        return;
    }
    auto resident = proof.observed;
    resident.revision = revision;
    if (resident.placed != ReflectionFirstHit::PlacedSource::None) {
        const u32 target = u32(resident.placed);
        if (build.update || tracking.placed_direct[target] != 1 || tracking.placed_joined[target] != 1 ||
            !tracking.pass->BuildPlaced(*tracking.stamp, resident, build.reflection_cookie)) {
            ReflectionFirstHit::TracePlacedLifecycle(resident.placed, "ordinary-placed-build-refused",
                frame, tracking.stamp->pass, resident.allocation, revision, build.reflection_cookie,
                build.update, (u64(tracking.placed_direct[target]) << 32) | tracking.placed_joined[target]);
            return;
        }
        ReflectionFirstHit::TracePlacedLifecycle(resident.placed, "ordinary-placed-build-attested",
            frame, tracking.stamp->pass, resident.allocation, revision, build.reflection_cookie,
            build.param, entry.instance);
    }
    proof.resident = resident;
}

bool RtShadow::ReflectionSubmitted(const ReflectionFirstHit::Stamp& stamp,
                                   const ReflectionDrawToken& token, u64 vs, u64 ps, u32 count,
                                   u32 first, const ReflectionNativeProbe::Binding* placed) {
    auto& tracking = *reflection_tracker;
    const u32 target = ReflectionFirstHit::PlacedOn()
        ? ReflectionNativeProbe::Match({vs, ps, count, first}) : ReflectionNativeProbe::NoWitness;
    bool joined_placed = false;
    const char* placement_refusal = "submission-stamp-refused";
    const ReflectionTrack* traced = nullptr;
    // An unqualified exact submission invalidates retained geometry even when this pass
    // has already flushed or never reaches the blended-scene hook.
    SCOPE_EXIT {
        if (target != ReflectionNativeProbe::NoWitness && !joined_placed) {
            ReflectionFirstHit::TracePlacedLifecycle(ReflectionFirstHit::PlacedSource(target), placement_refusal,
                stamp.frame, stamp.pass, traced ? traced->observed.allocation : token.allocation,
                traced ? traced->resident.revision : 0, token.cookie, tracking.last_flushed,
                tracking.stamp ? tracking.stamp->pass : 0);
            tracking.pass->InvalidatePlaced(ReflectionFirstHit::PlacedSource(target));
        }
    };
    if (!tracking.stamp || *tracking.stamp != stamp || tracking.last_flushed == stamp.pass) {
        if (tracking.stamp && *tracking.stamp == stamp && tracking.last_flushed == stamp.pass) {
            placement_refusal = "submission-after-flush";
        }
        return false;
    }
    ++tracking.direct;
    const bool mirror = ExactMirror(vs, ps, count, first);
    tracking.mirror_direct += mirror;
    tracking.fireplace_direct += ExactFireplace(vs, ps, count, first);
    tracking.wall_shape_direct += count == 42441;
    if (target != ReflectionNativeProbe::NoWitness) {
        ++tracking.placed_direct[target];
    }
    if (!token.cookie || !token.entry) {
        placement_refusal = token.placement ? "submission-unjoined-entry" : "submission-no-placement-token";
        return false;
    }
    const auto found = tracking.tracks.find(static_cast<const Entry*>(token.entry));
    if (found == tracking.tracks.end()) {
        placement_refusal = "submission-no-track";
        return false;
    }
    auto& proof = found->second;
    traced = &proof;
    const auto& id = proof.observed;
    if (id.allocation != token.allocation || proof.cookie != token.cookie || id.vs != vs ||
        id.ps != ps || id.count != count || id.first != first || id.receiver != mirror) {
        placement_refusal = "submission-identity";
        return false;
    }
    placement_refusal = "submission-no-placed-identity";
    if (id.placed != ReflectionFirstHit::PlacedSource::None) {
        if (u32(id.placed) != target || tracking.placed_direct[target] != 1 || !placed ||
            !tracking.pass->ObservePlaced(stamp, id, token.cookie, *placed->buffer,
                                          placed->descriptor_offset)) {
            placement_refusal = u32(id.placed) != target ? "submission-role" :
                               tracking.placed_direct[target] != 1 ? "submission-duplicate" :
                               !placed ? "submission-binding" : "submission-observation";
            return false;
        }
        joined_placed = true;
        ++tracking.placed_joined[target];
    }
    if (proof.confirmed_pass != stamp.pass) {
        proof.confirmed_pass = stamp.pass;
        proof.direct_count = 0;
    }
    ++proof.direct_count;
    proof.confirmed = token.cookie;
    ++tracking.joined;
    tracking.mirror_joined += mirror;
    return joined_placed;
}

void RtShadow::ReflectionFlush(const ReflectionFirstHit::Stamp& stamp) {
    auto& tracking = *reflection_tracker;
    if (!tracking.stamp || *tracking.stamp != stamp || tracking.last_flushed == stamp.pass) {
        return;
    }
    tracking.last_flushed = stamp.pass;
    if (tracking.mirror_direct != 1 || tracking.mirror_joined != 1) {
        tracking.pass->RejectReceiver(stamp);
    }
    using Row = std::pair<const Entry*, const ReflectionTrack*>;
    std::vector<Row> candidates;
    candidates.reserve(tracking.tracks.size());
    for (auto& [entry, proof] : tracking.tracks) {
        const auto live = entry_live.find(entry);
        if (live == entry_live.end() || proof.address != live->second ||
            !ReflectionStatic(*entry, proof.observed.placed)) {
            ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "flush-entry-ineligible",
                stamp.frame, stamp.pass, proof.observed.allocation, proof.resident.revision,
                proof.confirmed, live != entry_live.end(), live != entry_live.end() && proof.address == live->second);
            tracking.pass->InvalidateAllocation(proof.observed.allocation);
            proof.resident = {};
            continue;
        }
        // The ordinary first build can precede promotion. Keep that exact build witness
        // on the same allocation, but admit geometry only after ordinary promotion.
        if (proof.observed.placed != ReflectionFirstHit::PlacedSource::None && !entry->instance) {
            ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "flush-before-promotion",
                stamp.frame, stamp.pass, proof.observed.allocation, proof.resident.revision,
                proof.confirmed, entry->r17_capture_frame, entry->built && entry->blas);
            continue;
        }
        if (proof.confirmed_pass == stamp.pass && proof.direct_count == 1 && !proof.pending &&
            proof.resident.revision && entry->built && entry->blas &&
            (proof.resident.placed == ReflectionFirstHit::PlacedSource::None ||
             tracking.pass->CurrentPlaced(stamp, proof.resident, proof.confirmed))) {
            tracking.pass->Submitted(stamp, proof.resident);
            candidates.emplace_back(entry, &proof);
        } else if (proof.observed.placed != ReflectionFirstHit::PlacedSource::None &&
                   proof.confirmed_pass == stamp.pass) {
            const u32 failures = u32(proof.direct_count != 1) | (u32(proof.pending != 0) << 1) |
                                 (u32(!proof.resident.revision) << 2) | (u32(!entry->built) << 3) |
                                 (u32(!entry->blas) << 4);
            ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "flush-current-candidate-refused",
                stamp.frame, stamp.pass, proof.observed.allocation, proof.resident.revision,
                proof.confirmed, failures, entry->r17_capture_frame);
        }
    }
    // The three independent geometry witnesses get a bounded first opportunity to clone.
    // The ray always considers all admitted opaque geometry in its distance ordering.
    const auto order = [](const Row& row) {
        const auto& id = row.second->resident;
        const int priority = id.receiver ? 0 : ExactFireplace(id.vs, id.ps, id.count, id.first) ?
                             1 : id.wall_witness ? 2 : 3;
        return std::pair{priority, id.surface};
    };
    std::ranges::sort(candidates, {}, order);
    for (const auto& [entry, proof] : candidates) {
        const auto result = tracking.pass->Clone(stamp, proof->resident, entry->handle,
                                                 entry->reflection_creation_size);
        if (result != ReflectionFirstHit::Status::AlreadyCloned) {
            ReflectionFirstHit::TracePlacedLifecycle(proof->resident.placed,
                result == ReflectionFirstHit::Status::Recorded ? "clone-created" : "clone-refused",
                stamp.frame, stamp.pass, proof->resident.allocation, proof->resident.revision,
                proof->confirmed, u32(result), entry->reflection_creation_size);
        }
        if (result == ReflectionFirstHit::Status::Recorded) {
            ++tracking.cloned;
        } else if (result != ReflectionFirstHit::Status::AlreadyCloned) {
            ++tracking.refused;
        }
        if (result == ReflectionFirstHit::Status::NoRoom ||
            (result == ReflectionFirstHit::Status::CloneLimit && tracking.pass->GetUsage().clones_this_frame >= 2)) {
            break;
        }
    }

    if (ReflectionOrdinal3::On()) ReflectionOrdinal3::FinishFlush(&scheduler, stamp.generation, stamp.frame, stamp.pass);
}

void RtShadow::ReflectionRetire(Entry& entry, const char* reason) {
    auto& tracking = *reflection_tracker;
    const auto it = tracking.tracks.find(&entry);
    if (it == tracking.tracks.end()) {
        return;
    }
    const std::string_view why = reason ? reason : "";
    if (it->second.observed.placed == ReflectionFirstHit::PlacedSource::None &&
        (why == "cache-age-expiry" || why == "scene-memory-budget-eviction" ||
         why == "entry-memory-budget-eviction")) {
        ++tracking.ordinary_evicted;
        const auto& id = it->second.resident;
        if (id.revision && (id.receiver || ExactFireplace(id.vs, id.ps, id.count, id.first) ||
                            id.wall_witness)) {
            std::printf("Reflection ordinary retire reason=%s frame=%llu surface=%016llx allocation=%llu revision=%llu\n",
                        reason, static_cast<unsigned long long>(frame),
                        static_cast<unsigned long long>(id.surface),
                        static_cast<unsigned long long>(id.allocation),
                        static_cast<unsigned long long>(id.revision));
        }
    } else {
        const auto& proof = it->second;
        ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, "ordinary-entry-retired", frame,
            tracking.stamp ? tracking.stamp->pass : 0, proof.observed.allocation, proof.resident.revision,
            proof.confirmed, entry.r17_capture_frame, why == "cache-age-expiry");
        tracking.pass->InvalidateAllocation(it->second.observed.allocation);
        ++tracking.invalidated;
    }
    tracking.tracks.erase(it);
}

void RtShadow::ReflectionAdmissions(u64 request) const {
    const auto& t = *reflection_tracker;
    const auto usage = t.pass->GetUsage();
    const auto u = [](u64 x) { return static_cast<unsigned long long>(x); };
    if (ReflectionFirstHit::PlacedOn()) {
        std::printf("Reflection placed request=%llu mirror=%u/%u fireplace=%u/%u wall=%u/%u\n",
                    u(request), t.placed_joined[0], t.placed_direct[0],
                    t.placed_joined[1], t.placed_direct[1], t.placed_joined[2], t.placed_direct[2]);
    }
    std::printf("Reflection admission request=%llu direct=%llu joined=%llu mirror_direct=%u "
                "mirror_joined=%u fireplace_direct=%u wall_count_direct=%u tracks=%zu "
                "retained=%u bytes=%llu admitted_total=%llu refused_total=%llu changed_total=%llu "
                "dropped_builds=%llu actual_builds=%llu ordinary_evicted=%llu invalidated=%llu "
                "track_limit=%llu expiry=%llu pressure_evicted=%llu copy_count=%u copy_bytes=%llu\n",
                u(request), u(t.direct), u(t.joined), t.mirror_direct, t.mirror_joined,
                t.fireplace_direct, t.wall_shape_direct, t.tracks.size(), usage.records, u(usage.bytes),
                u(t.cloned), u(t.refused), u(t.changed), u(t.dropped), u(t.scheduled),
                u(t.ordinary_evicted), u(t.invalidated), u(t.track_limit), u(usage.expired),
                u(usage.pressure_evicted), usage.clones_this_frame, u(usage.cloned_payload_this_frame));
}

void RtShadow::ReflectionNativeObserve(const Entry& entry, ReflectionNativeProbe::Draw& draw) {
    if (!draw.stamped || draw.stamp.frame != frame) {
        return;
    }
    if (reflection_native_epoch != draw.stamp.generation) {
        reflection_native_epoch = draw.stamp.generation;
        reflection_native_entries = {};
        reflection_native_tracked = 0;
    }
    const auto live = entry_live.find(&entry);
    if (live == entry_live.end() || !entry.address || !entry.handle || live->second != entry.address) {
        return;
    }
    auto found = std::ranges::find(reflection_native_entries, &entry, &ReflectionNativeEntry::entry);
    if (found == reflection_native_entries.end()) {
        found = std::ranges::find(reflection_native_entries, nullptr, &ReflectionNativeEntry::entry);
        if (found == reflection_native_entries.end()) {
            return;
        }
        *found = {.entry = &entry, .address = entry.address,
                  .allocation = ++reflection_native_allocation, .key = draw.key};
        ++reflection_native_tracked;
    }
    if (found->key != draw.key || found->address != entry.address) {
        return;
    }
    draw.native_entry = true;
    draw.allocation = found->allocation;
    if (entry.built && entry.blas) {
        draw.resident_frame = entry.r17_capture_frame;
        if (found->captured_frame == draw.resident_frame) {
            draw.revision = found->revision;
            draw.resident_cookie = found->cookie;
        }
    }
}

void RtShadow::ReflectionNativeSubmitted(const ReflectionNativeProbe::Draw& draw) {
    if (!draw.native_entry || !draw.capture_param) {
        return;
    }
    for (auto& watched : reflection_native_entries) {
        if (watched.entry && watched.allocation == draw.allocation && watched.key == draw.key) {
            watched.confirmed_cookie = draw.serial;
            return;
        }
    }
}

void RtShadow::ReflectionNativeRecordBuild(const Entry& entry, const Build& build) {
    const auto found = std::ranges::find(reflection_native_entries, &entry, &ReflectionNativeEntry::entry);
    if (found == reflection_native_entries.end() || found->address != entry.address) {
        return;
    }
    found->revision = ++reflection_native_revision;
    found->captured_frame = frame;
    found->cookie = build.reflection_native_allocation == found->allocation && build.reflection_native_cookie &&
                    found->confirmed_cookie == build.reflection_native_cookie ? build.reflection_native_cookie : 0;
    if (found->cookie && reflection_native_build_logs++ < 24) {
        const auto u = [](u64 n) { return static_cast<unsigned long long>(n); };
        const auto target = ReflectionNativeProbe::Match(found->key);
        std::printf("Reflection native build target=%s generation=%llu allocation=%llu revision=%llu "
                    "frame=%llu native_cookie=%llu param=%u update=%u build_tick=%llu\n",
                    ReflectionNativeProbe::labels[target], u(reflection_native_epoch), u(found->allocation),
                    u(found->revision), u(frame), u(found->cookie), build.param, u32(build.update),
                    u(scheduler.CurrentTick()));
    }
}

bool RtShadow::TryBottleDraw() {
    if (std::exchange(bottle_draw_seen, true)) {
        bottle_ambiguous = true;
        DiscardBottleCold();
        return false;
    }
    return true;
}

void RtShadow::InvalidateBottleGeometry(u64 address) {
    if (address != 0 && bottle_cold && address == bottle_cold->endpoint.address) {
        DiscardBottleCold();
    }
    if (address != 0 && address == bottle_failed.address) {
        bottle_failed = {};
    }
    if (address != 0 && address == bottle_scene_endpoint.address) {
        bottle_scene_frame = ~u64{0};
    }
    if (address != 0 && address == bottle_resident_address) {
        bottle_resident_address = 0;
        bottle_resident_capture = ~u64{0};
        bottle_scene_frame = ~u64{0};
    }
}

bool RtShadow::BottleObserved() const noexcept {
    return bottle_entry && bottle_entry_address != 0 && bottle_observed_frame == frame && !bottle_ambiguous;
}

RtShadow::BottleEndpoint RtShadow::BottleGeneration(const Entry& entry) const {
    return {&entry, entry.handle, entry.address, entry.r17_capture_frame, bottle_index, bottle_stream,
            bottle_stream_bytes};
}

bool RtShadow::BottleColdEligible(const Entry& entry) const {
    if (!BottleObserved() || bottle_entry != &entry || !entry.built || !entry.blas || !entry.handle ||
        entry.r17_capture_frame >= frame || entry.instances != 1 || entry.dynamic || entry.rebuilt ||
        entry.skinned || ((entry.palette != 0) != entry.palette_placed) || entry.still_doubt ||
        entry.still_moved || entry.gone || !need_scene || r26_freeze || !TlasGuardOn() || camera_motion.PreviewFrame()) {
        return false;
    }
    const auto live = entry_live.find(&entry);
    return live != entry_live.end() && live->second == entry.address;
}

bool RtShadow::MakeBottleCold(BottleCold& cold, const Entry& entry) {
    BottleCaustic::ColdCornerMap map{};
    if (!BottleCaustic::MakeColdCornerMap(bottle_topology.Corners(), entry.vertices,
                                        s32(entry.first_vertex), map) ||
        !EffectPass::HasRoom(instance, BottlePositionBytes + BottleCornerBytes + sizeof(map) +
                                              BottleParamBytes + 8 * sizeof(u64) + sizeof(u32))) {
        return false;
    }
    constexpr auto Storage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    constexpr auto Uniform = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;
    if (!Make(cold.positions, BottlePositionBytes, false, Storage | VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(cold.params, BottleParamBytes, true, Storage) ||
        !Make(cold.capture_addresses, 3 * sizeof(u64), true, Uniform) ||
        !Make(cold.both_addresses, 5 * sizeof(u64), true, Uniform) ||
        !Make(cold.order, sizeof(map), true, Storage)) {
        return false;
    }
    std::memcpy(cold.order.mapped, map.data(), sizeof(map));
    using ParamWords = std::array<u32, 8>;
    std::array<ParamWords, BottleCaustic::ColdSpans.size() + 1> words{};
    for (u32 i = 0; i < BottleCaustic::ColdSpans.size(); ++i) {
        const auto& span = BottleCaustic::ColdSpans[i];
        // This is EmitVertexCapture's existing 32-byte record. UV count/base are zero.
        words[i + 1] = {span.store, 0, span.count, 0, entry.first_vertex + span.first,
                        entry.first_instance, 1, 0};
    }
    static_assert(sizeof(words) == BottleParamBytes);
    std::memcpy(cold.params.mapped, words.data(), sizeof(words));
    const auto* motion = static_cast<const u64*>(both_addresses.mapped);
    const std::array<u64, 3> capture_table{cold.params.address, cold.positions.address, card_ring.address};
    const std::array<u64, 5> both_table{motion[0], motion[1], cold.params.address,
                                       cold.positions.address, card_ring.address};
    std::memcpy(cold.capture_addresses.mapped, capture_table.data(), sizeof(capture_table));
    std::memcpy(cold.both_addresses.mapped, both_table.data(), sizeof(both_table));
    const auto device = instance.GetDevice();
    const vk::DescriptorPoolSize pool_size{vk::DescriptorType::eUniformBuffer, 2};
    auto [pool_result, pool] = device.createDescriptorPoolUnique(
        {.maxSets = 2, .poolSizeCount = 1, .pPoolSizes = &pool_size});
    if (pool_result != vk::Result::eSuccess) {
        return false;
    }
    cold.address_pool = std::move(pool);
    const std::array layouts{*address_layout, *address_layout};
    const auto [set_result, sets] = device.allocateDescriptorSets(
        {.descriptorPool = *cold.address_pool, .descriptorSetCount = 2, .pSetLayouts = layouts.data()});
    if (set_result != vk::Result::eSuccess) {
        return false;
    }
    cold.capture_set = sets[0];
    cold.both_set = sets[1];
    const std::array<vk::DescriptorBufferInfo, 2> infos{{
        {cold.capture_addresses.buffer, 0, card_uv_on ? 24u : 16u},
        {cold.both_addresses.buffer, 0, card_uv_on ? 40u : 32u},
    }};
    const std::array<vk::WriteDescriptorSet, 2> writes{{
        {.dstSet = cold.capture_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer, .pBufferInfo = &infos[0]},
        {.dstSet = cold.both_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer, .pBufferInfo = &infos[1]},
    }};
    device.updateDescriptorSets(writes, {});

    // Any corner the original vertex draw failed to write must fail validation.
    scheduler.EndRendering();
    scheduler.Record([positions = cold.positions.buffer](vk::CommandBuffer cmd) {
        cmd.fillBuffer(positions, 0, BottlePositionBytes, 0x7fc00000u);
        EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite,
                                  vk::PipelineStageFlagBits2::eVertexShader | Compute,
                                  vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
    });
    return true;
}

void RtShadow::DiscardBottleCold() {
    if (!bottle_cold) {
        return;
    }
    scheduler.DeferOperation([allocator = instance.GetAllocator(), cold = std::move(bottle_cold)] {
        for (const Buffer* buffer : {&cold->positions, &cold->params, &cold->capture_addresses,
                                    &cold->both_addresses, &cold->order, &cold->corners, &cold->result}) {
            if (buffer->buffer) {
                vmaDestroyBuffer(allocator, buffer->buffer, buffer->allocation);
            }
        }
    }, "bottle cold capture");
}

u32 RtShadow::NominateBottleSpan(const Entry& entry, const Draw& draw, const std::array<float, 12>& to_world) {
    if (!BottleColdEligible(entry) || !draw.positions || !draw.positions_size ||
        draw.first_vertex != entry.first_vertex || draw.first_instance != entry.first_instance ||
        (bottle_resident_address == entry.address && bottle_resident_capture == entry.r17_capture_frame)) {
        DiscardBottleCold();
        return 0;
    }
    const auto endpoint = BottleGeneration(entry);
    if (bottle_cold && bottle_cold->endpoint != endpoint) {
        DiscardBottleCold();
    }
    if (bottle_failed == endpoint || (bottle_cold && bottle_cold->spans == BottleCaustic::ColdSpans.size())) {
        return 0;
    }
    if (!bottle_cold) {
        bottle_cold = std::make_unique<BottleCold>();
        bottle_cold->endpoint = endpoint;
        if (!MakeBottleCold(*bottle_cold, entry)) {
            if (BottleCaustic::LogNow()) {
                std::printf("Bottle caustics: cold capture bounds or allocation refused\n");
            }
            bottle_failed = endpoint;
            DiscardBottleCold();
            return 0;
        }
    }
    const auto& span = BottleCaustic::ColdSpans[bottle_cold->spans];
    bottle_cold->unproject = {to_world, span.store, span.count};
    return bottle_cold->spans + 1;
}

void RtShadow::RecordBottleDraw(BottleDrawToken token) {
    if (!token.observed || !BottleObserved()) {
        return;
    }
    bottle_recorded_frame = frame;
    if (token.private_param && bottle_cold && token.private_param == bottle_cold->spans + 1) {
        bottle_cold->recorded_span = true;
    }
}

bool RtShadow::BottleCapturePending(u32 param) const noexcept {
    return BottleObserved() && bottle_cold && !bottle_cold->recorded_span &&
           param == bottle_cold->spans + 1 && BottleGeneration(*bottle_entry) == bottle_cold->endpoint;
}

void RtShadow::ConsumeBottleSpan() {
    if (!bottle_cold || !bottle_cold->recorded_span) {
        return;
    }
    auto& cold = *bottle_cold;
    if (!BottleCaustic::On() || !BottleObserved() || bottle_recorded_frame != frame ||
        !BottleColdEligible(*bottle_entry) || BottleGeneration(*bottle_entry) != cold.endpoint) {
        DiscardBottleCold();
        return;
    }
    cold.recorded_span = false;
    cold.sample_frames[cold.spans++] = frame;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "Bottle cold unproject"},
        [push = cold.unproject, positions = cold.positions.buffer,
         pipeline = *unproject_pipeline, layout = *unproject_layout](vk::CommandBuffer cmd) {
            using enum vk::AccessFlagBits2;
            EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eVertexShader, eShaderWrite,
                                      Compute, eShaderRead | eShaderWrite);
            const vk::DescriptorBufferInfo position{positions, 0, BottlePositionBytes};
            const vk::WriteDescriptorSet write{.dstBinding = 0, .descriptorCount = 1,
                .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &position};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, write);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((push.count + 63) / 64, 1, 1);
            EffectPass::MemoryBarrier(cmd, Compute, eShaderWrite, Compute, eShaderRead);
        });
}

void RtShadow::ValidateBottleCold() {
    auto& cold = *bottle_cold;
    if (cold.result_tick) {
        if (scheduler.IsFree(cold.result_tick)) {
            const u32 passed = *static_cast<const u32*>(cold.result.mapped);
            cold.ready = passed == BottleCaustic::BottleTriangles;
            if (BottleCaustic::LogNow()) {
                std::printf("Bottle caustics: cold validated %u/%u triangles, BLAS capture %llu, samples %llu/%llu/%llu\n",
                            passed, BottleCaustic::BottleTriangles, static_cast<unsigned long long>(cold.endpoint.capture),
                            static_cast<unsigned long long>(cold.sample_frames[0]),
                            static_cast<unsigned long long>(cold.sample_frames[1]),
                            static_cast<unsigned long long>(cold.sample_frames[2]));
            }
            if (!cold.ready) {
                bottle_failed = cold.endpoint;
                DiscardBottleCold();
            }
        }
        return;
    }
    using enum vk::DescriptorType;
    const VkBufferCreateInfo ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = sizeof(u32),
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    const VmaAllocationCreateInfo ai{.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO, .requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT};
    VkBuffer result{};
    VmaAllocationInfo info{};
    if (!EffectPass::Create(instance, cold.validate_set, cold.validate_layout, cold.validate_pipeline,
                           {eAccelerationStructureKHR, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer},
                           sizeof(BottleValidatePush), BOTTLE_COLD_VALIDATE_COMP, "Bottle cold validate") ||
        vmaCreateBuffer(instance.GetAllocator(), &ci, &ai, &result, &cold.result.allocation, &info) != VK_SUCCESS) {
        bottle_failed = cold.endpoint;
        DiscardBottleCold();
        return;
    }
    cold.result.buffer = result;
    cold.result.mapped = info.pMappedData;
    // Natural copies can arrive before this validation retires. Each path owns its output.
    if (!cold.result.mapped || !Make(cold.corners, BottleCornerBytes, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)) {
        bottle_failed = cold.endpoint;
        DiscardBottleCold();
        return;
    }
    const BottleValidatePush push{bottle_scene_view, bottle_scene_ordinal, bottle_scene_mask & CameraMask};
    const std::array<vk::DescriptorBufferInfo, 4> buffers{{
        {cold.positions.buffer, 0, BottlePositionBytes}, {cold.order.buffer, 0, sizeof(BottleCaustic::ColdCornerMap)},
        {cold.corners.buffer, 0, BottleCornerBytes}, {cold.result.buffer, 0, sizeof(u32)},
    }};
    scheduler.EndRendering();
    cold.result_tick = scheduler.CurrentTick();
    scheduler.RecordCrumb({.name = "Bottle cold validate"},
        [push, buffers, scene = tlas, layout = *cold.validate_layout,
         pipeline = *cold.validate_pipeline](vk::CommandBuffer cmd) {
            using enum vk::AccessFlagBits2;
            constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
            cmd.fillBuffer(buffers.back().buffer, 0, sizeof(u32), 0);
            // Order the prior position writes and result clear before this dispatch.
            // PrepareScene already makes AS writes visible to compute.
            EffectPass::MemoryBarrier(cmd, Compute | Transfer, eShaderRead | eShaderWrite | eTransferWrite,
                                      Compute, eShaderRead | eShaderWrite);
            const vk::WriteDescriptorSetAccelerationStructureKHR as{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            std::array<vk::WriteDescriptorSet, 5> writes{};
            writes[0] = {.pNext = &as, .dstBinding = 0, .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eAccelerationStructureKHR};
            for (u32 i = 0; i < buffers.size(); ++i) {
                writes[i + 1] = {.dstBinding = i + 1, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &buffers[i]};
            }
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((BottleCaustic::BottleTriangles + 31) / 32, 1, 1);
            EffectPass::MemoryBarrier(cmd, Compute, eShaderWrite, Compute | vk::PipelineStageFlagBits2::eHost,
                                      eShaderRead | eHostRead);
        });
}

RtShadow::BottleSceneView RtShadow::BottleScene(const std::array<float, 12>& view) {
    if (!BottleObserved() || bottle_recorded_frame != frame || bottle_scene_frame != frame ||
        bottle_scene_view != view || !tlas || r26_freeze || !TlasGuardOn() ||
        bottle_scene_endpoint != BottleGeneration(*bottle_entry) || !BottleCaustic::On()) {
        return {};
    }
    const bool warm = bottle_entry_address == bottle_resident_address &&
                      bottle_entry->r17_capture_frame == bottle_resident_capture;
    if (!warm) {
        if (!bottle_cold || bottle_cold->spans != BottleCaustic::ColdSpans.size() ||
            bottle_cold->endpoint != bottle_scene_endpoint || !BottleColdEligible(*bottle_entry)) {
            return {};
        }
        if (!bottle_cold->ready) {
            ValidateBottleCold();
        }
        if (!bottle_cold || !bottle_cold->ready) {
            return {};
        }
        return {tlas, bottle_cold->corners.buffer, bottle_scene_ordinal};
    }
    return {tlas, bottle_corners.buffer, bottle_scene_ordinal};
}

u32 RtShadow::PrepareDraw(const Draw& draw) {
    using WindowPathProbe::PaneStages;
    auto* pane = draw.window_pane_observe ? window_pane_watch : nullptr;
    auto* stage = pane ? &pane->stages : nullptr;
    bool pane_new_entry = false;
    if (stage) {
        PaneStages::Count(stage->prepare);
    }
    const auto pane_result = [&](const char* why, bool refusal = false) {
        if (stage) {
            stage->PrepareResult(why);
            if (refusal) {
                stage->Refuse(why, pane->source_frame, frame);
            }
        }
    };
    // bbport (r19_draw-cost): experiment 17592186044416 clear: the short paths marked r19 below,
    // each giving what the old code computes from the same inputs; set: the old code.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    if (r19 && draw.r19_wanted) {
        ++r19_stats.wanted_skipped;
    } else if (!Wanted()) {
        pane_result("rt-unwanted", true);
        return 0;
    }
    if (!draw.shadow_pass && !draw.camera_pass) {
        pane_result("non-capture-pass", true);
        return 0;
    }
    auto* watching = roof_probe ? roof_probe->Watch() : nullptr;
    u64 observed_mesh = 0;
    InteriorRoof::WatchRow* mesh_watch = nullptr;
    if (watching) {
        const std::array<u64, 4> parts{draw.geometry, draw.indices, draw.index_count, draw.first_vertex};
        observed_mesh = XXH3_64bits(parts.data(), sizeof(parts));
        mesh_watch = watching->ByMesh(observed_mesh);
        if (mesh_watch) {
            ++mesh_watch->now.mesh_draws;
            if (std::string_view(mesh_watch->now.mesh_why) == "unknown") {
                mesh_watch->now.mesh_why = "mesh-only-before-key";
            }
        }
    }
    const auto mesh_reason = [&](const char* why) {
        if (mesh_watch) {
            mesh_watch->now.mesh_why = why;
        }
    };
    r19_stats.calls += r19 ? 1u : 0u;
    // bbport (r86f_glass-static-panes): the vote for GlassCamera (BB_RT_GLASS on only)
    if (draw.camera_pass && !draw.glass && draw.constants && (RtGlassOn() || RtGlassFind::On())) { // (r86h: and the find alone)
        GlassCameraVote(draw.constants);
    }
    // bbport (r14_cascade_rt): with sun cascades left undrawn on some frames, the cascade of each
    // shadow pass draw and the cascades drawn this frame, learned from the draws that arrive (the
    // game thread runs frames ahead: its schedule is not assumed).
    u8 cascade = 4;
    if (hold_frames && draw.shadow_pass) {
        cascade = SunCascade(draw);
        frame_cascades |= u8(1u << cascade);
    }
    // The mesh without its shader: the camera pass and the shadow pass draw it with different
    // ones, and only the camera pass shows whether its pixel shader cuts the surface out.
    // bbport (r19_draw-cost): the mesh hash is made only where it is read (a camera pass cut-out,
    // a new entry); the old path makes it for every draw.
    const auto mesh_of = [&] {
        r19_stats.mesh_made += r19 ? 1u : 0u;
        const std::array<u64, 4> mesh_parts{draw.geometry, draw.indices, draw.index_count,
                                            draw.first_vertex};
        return XXH3_64bits(mesh_parts.data(), sizeof(mesh_parts));
    };
    const u64 mesh = r19 ? 0 : mesh_of();
    // bbport (r46_lamp-cards): the key of a draw with a position stream (the entries are known
    // by it, below): it depends neither on the pass nor on the shader.
    const auto position_key = [&] {
        const std::array<u64, 4> parts{draw.positions, draw.indices,
                                       (u64(draw.index_count) << 32) | draw.first_vertex,
                                       draw.instances};
        return XXH3_64bits(parts.data(), sizeof(parts));
    };
    if (draw.camera_pass && draw.alpha) {
        // bbport (r46_lamp-cards): cutout_gen tells the entries that a set changed (PrepareScene)
        if (cutout_meshes.size() >= 65536) {
            cutout_meshes.clear();
            ++cutout_gen;
        }
        if (cutout_meshes.insert(r19 ? mesh_of() : mesh).second) {
            ++cutout_gen;
        }
        // The same draw by the key as well, which the sun shadow pass's entries of the mesh
        // have too where `mesh` differs between the passes (see cutout_keys). Here, before the
        // filters below: a cut-out without skeleton or palette is dropped there and gets no
        // entry from the camera pass, so its sun shadow pass entry knows itself as a card
        // through these sets alone.
        if (draw.positions && draw.indices) {
            if (cutout_keys.size() >= 65536) {
                cutout_keys.clear();
                ++cutout_gen;
            }
            if (cutout_keys.insert(position_key()).second) {
                ++cutout_gen;
            }
        }
    }

    // bbport (r46b_plant-rule): the position streams drawn with a skeleton, by a sun shadow
    // pass (the game gives the mesh a shadow: a character's, for good) or by the camera pass with
    // a discarding pixel shader (LampLoneCameraDraw counts the frames on which the sun shadow
    // pass draws skeletons but not this one). By the stream's address and not by the key: a pass
    // may draw another index list of the same vertices (a coarser level of detail). Here,
    // before the filters below, so a sun shadow pass draw counts whatever becomes of it. A map
    // at its cap first forgets the streams not drawn for LoneStreamKeep frames that are not
    // lone (vertices written to a new address on every frame would fill it), then everything.
    if (draw.skinned && draw.positions != 0 && (draw.shadow_pass || draw.alpha)) {
        ++lone_draws;
        if (lone_streams.size() >= LoneStreamsMost) {
            std::erase_if(lone_streams, [&](const auto& item) {
                return LampLoneOf(item.second) != LampLoneState::Lone &&
                       item.second.seen + LoneStreamKeep < frame;
            });
            if (lone_streams.size() >= LoneStreamsMost) {
                lone_streams.clear();
            }
            ++lone_gen;
        }
        const auto [known, fresh] = lone_streams.try_emplace(draw.positions);
        bool changed = fresh;
        // bbport (r47c_review-fixes): another size of vertices bound at the address: the game
        // gave the memory to another mesh, what was known of the stream is forgotten
        const u32 sized = known->second.size;
        changed |= LampLoneSized(known->second, draw.positions_size);
        lone_resized += sized != 0 && sized != known->second.size ? 1 : 0;
        if (draw.shadow_pass) {
            sun_skinned_frame = frame;
            sun_skinned_any = true;
            changed |= LampLoneSunDraw(known->second, frame);
        } else {
            changed |= LampLoneCameraDraw(known->second, frame, sun_skinned_any,
                                          sun_skinned_frame);
        }
        lone_gen += changed ? 1 : 0;
    }

    // Camera pass casters only serve the ray traced scene (lamp shadows, bounced light).
    if (draw.camera_pass && !need_scene) {
        mesh_reason("mesh-only-no-natural-camera-scene");
        pane_result("no-natural-camera-scene", true);
        return 0;
    }
    draw.camera_pass ? ++stats.camera_draws : ++stats.draws;
    if (!draw.solid) {
        mesh_reason("mesh-only-nonsolid");
        pane_result("nonsolid", true);
        return 0;
    }
    // Sun shadow shaders discard even for opaque casters; camera-pass characters also need
    // their cut-out geometry in the ray traced scene.
    if (draw.alpha) {
        const bool character = draw.skinned || draw.palette != 0;
        if (character) {
            ++stats.cut_characters;
        } else {
            ++stats.alpha;
        }
        if (!draw.shadow_pass && !character) {
            mesh_reason("mesh-only-alpha");
            pane_result("alpha", true);
            return 0;
        }
    }
    if (!draw.constants) {
        mesh_reason("mesh-only-missing-camera-constants");
        pane_result("camera-constants-missing", true);
        ++stats.no_camera;
        if (draw.camera_pass && RtGlassFind::On()) { // bbport (r86j_glint-same-game): the bottles may be here
            RtGlassFind::Chain().no_constants.fetch_add(1, std::memory_order_relaxed);
        }
        return 0;
    }
    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw had the camera constants
        RtGlassProbe::Add(RtGlassProbe::Constants);
    }
    std::array<float, 12> to_world{};
    if (!R17ToWorld(draw.constants, draw.camera_pass, to_world)) { // bbport (r17_rt-upkeep)
        ++stats.not_ortho;
        mesh_reason("mesh-only-clip-to-world-refused");
        pane_result("clip-to-world", true);
        return 0;
    }
    if (!draw.triangles || !draw.indices || draw.instances == 0 ||
        draw.instances > MaxInstancesPerDraw) {
        draw.instances > MaxInstancesPerDraw ? ++stats.instanced : ++stats.unsupported;
        mesh_reason("mesh-only-draw-topology-or-range-refused");
        pane_result("capture-topology-or-range", true);
        return 0;
    }
    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw goes on to its entry
        RtGlassProbe::Add(RtGlassProbe::ToEntry);
    }
    stats.strips += draw.strip ? 1 : 0;
    // bbport (r83_glass-water-stage1): a window pane's draw (BB_RT_GLASS, Draw::glass) has an
    // entry of its own (RtGlassKey below) under RtGlassMask alone
    const u8 mask = draw.glass ? RtGlassMask : draw.camera_pass ? CameraMask : ShadowMask;
    u64 key;
    if (draw.positions) {
        key = position_key(); // bbport (r46_lamp-cards): as the camera pass's cut-outs above
    } else {
        key = draw.geometry ^ (draw.shader * 0x9e3779b97f4a7c15ull);
        key = XXH3_64bits_withSeed(&draw.indices, sizeof(draw.indices), key);
        const std::array<u32, 4> parts{draw.index_count, draw.first_vertex, draw.instances,
                                       draw.camera_pass ? 1u : 0u};
        key = XXH3_64bits_withSeed(parts.data(), sizeof(parts), key);
    }
    if (draw.glass) { // bbport (r83_glass-water-stage1): apart from a pass's entry of the mesh
        key = RtGlassKey(key);
    }
    auto* key_watch = watching ? watching->Exact(key, observed_mesh) : nullptr;
    const auto watch_reason = [&](const char* why) {
        if (key_watch) {
            key_watch->now.draw_why = why;
        }
    };
    const auto watch_list = [&](const char* why) {
        if (key_watch) {
            ++key_watch->now.listed;
            key_watch->now.draw_why = why;
        }
    };
    if (key_watch) {
        ++key_watch->now.key_draws;
        watch_reason("exact-key-selected-for-lookup");
    }
    // bbport (r130g_glass-light-forward): a registered pane let through with a GPU-placed palette must be steady (3 frames in a
    // row, at most 16 a frame); the torch's palette alternates two addresses and never is. r121b's judge below runs as before.
    // (draw.glass too: a draw a later r121b test refused keeps glass_placed but is no pane, and goes on as before.)
    if (draw.glass && draw.glass_placed && !GlassPlacedSteady(draw.palette != 0 ? InstanceKey(key, draw.palette) : key)) {
        watch_reason("glass-placement-guard");
        pane_result("glass-placement-guard", true);
        return 0;
    }
    // bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC: a pane is a still thing. The judge (rt_glass_static.h)
    // lets a pane instance (the key, mixed with the palette hash as InstanceKey keys a palette draw's entry)
    // through once it was drawn on RtGlassStatic::StableFrames frames; a new one (a held torch or a swinging
    // lantern has new palette bytes each frame) is left out before any entry, BLAS, refit or carry of it
    // exists: not in frame_entries and, glass_drawn not given its key, not carried into the next frame.
    if (draw.glass && RtGlassStatic::On()) {
        const RtGlassStatic::Reason verdict = RtGlassStatic::Judge(
            glass_seen, draw.palette != 0 ? InstanceKey(key, draw.palette) : key, frame);
        RtGlassStatic::Add(verdict);
        if (verdict != RtGlassStatic::Taken) {
            watch_reason("glass-static-guard");
            pane_result("glass-static-guard", true);
            return 0;
        }
    }

    // bbport (r14_cascade_rt): a shadow pass draw's copies are known by its cascade, not by the
    // order its camera arrived in this frame (which shifts when an earlier cascade is not drawn);
    // far above any index of frame_cameras, which the other draws still use.
    u32 camera_index = cascade < 4 ? 0x80000000u + cascade : 0u;
    // bbport (r19_draw-cost): the draws of one pass share their constants: the last draw's index
    // when frame_cameras holds the same pointer there. A pointer is in frame_cameras once (pushed
    // only when the scan does not find it, cleared only at the frame's end): the scan stops there.
    if (cascade >= 4 && r19 && r19_camera_last < frame_cameras.size() &&
        frame_cameras[r19_camera_last] == draw.constants) {
        camera_index = r19_camera_last;
        ++r19_stats.camera_cached;
    } else {
        for (; cascade >= 4 && camera_index < frame_cameras.size(); ++camera_index) {
            if (frame_cameras[camera_index] == draw.constants) {
                break;
            }
        }
        if (cascade >= 4 && camera_index == frame_cameras.size()) {
            frame_cameras.push_back(draw.constants);
        }
    }
    if (cascade >= 4) {
        r19_camera_last = camera_index;
    }
    // A small bone palette holds world space bones, so with the mesh key it identifies one
    // object in one pose whatever the camera or the draw order: a prop seen unchanged on three
    // frames gets an entry of its own, so the game drawing other instances first, or not drawing
    // this one, neither re-captures it nor makes it look moving.
    const bool palette_draw = draw.palette != 0 && !draw.skinned;
    u64 instance_key = 0;
    bool instance_entry = false;
    bool promote = false;
    if (palette_draw) {
        instance_key = InstanceKey(key, draw.palette);
        instance_entry = entries.contains(instance_key);
        if (!instance_entry) {
            if (candidates.size() >= MaxCandidates) {
                candidates.clear();
            }
            auto& candidate = candidates[instance_key];
            if (candidate.last != frame + 1) {
                candidate.last = frame + 1;
                ++candidate.frames;
            }
            promote = candidate.frames >= PromoteFrames && new_triangles < NewTrianglesPerFrame;
        }
    }
    u64 entry_key = key;
    bool shared = false;
    // bbport (r19_draw-cost): the memo slot of a draw without a palette (never an instance entry,
    // never promoted: its entry_key is `key` unless shared), see R19EntryMemo.
    R19EntryMemo* r19_memo = nullptr;
    if (!instance_entry) {
        const std::array<u64, 2> occurrence_key{key, camera_index};
        const u64 occurrence_hash = XXH3_64bits(occurrence_key.data(), sizeof(occurrence_key));
        const u32 occurrence = NextOccurrence(occurrence_hash);
        if (occurrence > 0) {
            shared_keys.insert(key);
        }
        if (r19 && !palette_draw) {
            r19_memo = &r19_entry_memo[key & (R19EntryMemos - 1)];
        }
        if (r19 && occurrence > 0) {
            shared = true; // in the set: inserted just above
            ++r19_stats.shared_known;
        } else if (r19_memo && r19_memo->entry && r19_memo->key == key &&
                   r19_memo->shared_size == shared_keys.size()) {
            shared = false; // not in it when the memo was filled; an insert-only set of the same
            ++r19_stats.shared_memo; // size is the same set
        } else {
            shared = shared_keys.contains(key);
        }
        if (shared) {
            const std::array<u64, 3> copy{key, camera_index, occurrence};
            entry_key = XXH3_64bits(copy.data(), sizeof(copy));
        }
        if (promote) {
            // The draw order entry of this very instance, when unchanged, becomes the instance's.
            if (auto old = entries.find(entry_key);
                old != entries.end() && old->second && !old->second->dynamic &&
                old->second->palette == draw.palette &&
                old->second->mask == (draw.camera_pass ? CameraMask : ShadowMask)) {
                auto adopted = std::move(old->second);
                entries.erase(old);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                adopted->rebuilt = false;
                adopted->instance = true;
                StillAdmit(*adopted, instance_key); // bbport (r47_still-check)
                entries[instance_key] = std::move(adopted);
                ++stats.promoted;
            }
            instance_entry = true;
            entry_key = instance_key;
            shared = false;
            const std::array<u64, 3> retired{key, draw.palette, draw.camera_pass ? 1u : 0u};
            promoted_now.insert(XXH3_64bits(retired.data(), sizeof(retired)));
        }
    } else {
        entry_key = instance_key;
    }

    // bbport (r19_draw-cost): a plain draw whose key's Entry is in its memo slot with no erase or
    // move in `entries` since: the Entry that entries[key] holds.
    Entry* r19_entry = nullptr;
    if (r19_memo && !shared && r19_memo->entry && r19_memo->key == key &&
        r19_memo->entries_gen == r19_entries_gen) {
        r19_entry = r19_memo->entry;
        ++r19_stats.entry_memo;
    }
    if (!r19_entry) {
        auto& slot = entries[entry_key];
        if (!slot) {
            if (new_triangles >= NewTrianglesPerFrame) {
                watch_reason("new-entry-triangle-budget");
                pane_result("new-entry-triangle-budget", true);
                ++stats.over_budget;
                ++missed;
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            // bbport (r26_upkeep-probe): BLAS and TLAS frozen: no new caster (nothing would
            // build it, the TLAS traced as it was would not hold it), so no memory is taken.
            if (r26_freeze == 3u) {
                watch_reason("new-entry-upkeep-freeze");
                pane_result("new-entry-upkeep-freeze", true);
                ++r26_stats.left_out;
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            // bbport (r86m_glint-pane-from-triangle, TOOL): a pane the triangle route cut is made from its triangles only
            glass_tri_keep_now = draw.glass && glass_tri ? GlassTriKeep(RtGlassKey(key)) : nullptr;
            slot = MakeEntry(draw, mask);
            glass_tri_keep_now = nullptr;
            if (!slot) {
                watch_reason("make-entry-refused-unspecified");
                pane_result("make-entry-refused", true);
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            pane_new_entry = pane && pane->natural.Active();
            slot->rebuilt = shared;
            slot->mesh = r19 ? mesh_of() : mesh;
            slot->base = key;
            slot->instance = instance_entry;
            slot->rebuild_every = RebuildEveryFrames + u32(entry_key % RebuildSpread);
            stats.promoted += promote ? 1 : 0;
            // bbport (r47_still-check): a caster a look found moving before it was evicted
            // counts as moving from its first draw
            StillAdmit(*slot, entry_key);
        }
        r19_entry = slot.get();
        if (r19_memo && !shared) { // entry_key == key here
            *r19_memo = {key, r19_entry, r19_entries_gen, u64(shared_keys.size())};
            ++r19_stats.entry_filled;
        }
    }
    Entry& entry = *r19_entry;
    const auto trace_reflection_reuse = [&](const char* why) {
        if (!reflection_tracker || !ReflectionFirstHit::PlacedLifecycleOn()) {
            return;
        }
        const auto& tracker = *reflection_tracker;
        const auto found = tracker.tracks.find(&entry);
        if (found == tracker.tracks.end()) {
            return;
        }
        const auto& proof = found->second;
        const u32 state = u32(draw.camera_pass) | (u32(draw.shadow_pass) << 1) |
                          (u32(entry.built) << 2) | (u32(entry.blas) << 3) |
                          (u32(entry.instance) << 4) | (u32(entry.palette == draw.palette) << 5);
        ReflectionFirstHit::TracePlacedLifecycle(proof.observed.placed, why, frame,
            tracker.stamp ? tracker.stamp->pass : 0, proof.observed.allocation, proof.resident.revision,
            proof.confirmed, entry.r17_capture_frame, state);
    };
    if (draw.reflection_native && draw.reflection_native->trace && draw.camera_pass && mask == CameraMask) {
        ReflectionNativeObserve(entry, *draw.reflection_native);
    }
    if (reflection_tracker && (draw.reflection || reflection_tracker->tracks.contains(&entry))) {
        ReflectionObserve(entry, draw, !shared && mask == CameraMask && !draw.glass && !draw.skinned);
    }
    if (stage) {
        stage->entry = entry_key;
        stage->base = entry.base;
    }
    if (draw.bottle_candidate && need_scene && mask == CameraMask && entry.address &&
        !entry.skinned && entry.instances == 1 && entry.triangles == BottleCaustic::IndexCount / 3 &&
        entry.indices.mapped) {
        if (bottle_entry_address != 0) {
            bottle_ambiguous = true;
            DiscardBottleCold();
        } else {
            const std::span raw{reinterpret_cast<const u32*>(draw.indices), BottleCaustic::IndexCount};
            if (bottle_topology.Verify(raw) && entry.bottle_index_verified) {
                bottle_entry = &entry;
                bottle_entry_address = entry.address;
                bottle_observed_frame = frame;
                bottle_index = draw.indices;
                bottle_stream = draw.positions;
                bottle_stream_bytes = draw.positions_size;
                if (draw.bottle_delivery) {
                    draw.bottle_delivery->observed = true;
                }
            } else if (BottleCaustic::LogNow() && !bottle_refused_logged) {
                bottle_refused_logged = true;
                std::printf("Bottle caustics: refused ordered guest or BLAS topology\n");
            }
        }
    }
    const auto pane_entry = [&] {
        if (stage) {
            stage->entry_flags = (entry.built ? PaneStages::Built : 0u) |
                                 (entry.dynamic ? PaneStages::Dynamic : 0u) |
                                 (entry.rebuilt ? PaneStages::Rebuilt : 0u) |
                                 (entry.blas ? PaneStages::Blas : 0u);
        }
    };
    pane_entry();
    if (key_watch) {
        if (auto* row = RoofWatchEntry(entry)) {
            row->Cache(entry.address, roof_probe->Geometry(entry.address), entry.r17_capture_frame, "guarded-cache");
        } else {
            key_watch->now.cache_why = "lookup-lifetime-unattested";
        }
    }
    if (glass_light_mode != 0) { // bbport (r130c_glass-lamp-light): off: this byte test alone
        GlassLightNote(entry, draw);
    }
    if (draw.glass) { // bbport (r83_glass-water-stage1): for the log
        NoteGlassDraw(entry);
        if (draw.glass_placed && entry.dynamic) { // bbport (r130g_glass-light-forward): a moving placed pane is not carried
            ++glass_fwd.moving_left;
        } else if (RtGlassCarryOn() || (glass_light_mode != 0 && entry.glass_light != 0)) { // bbport (r86, r86b, r130g): carried
            glass_drawn.push_back(entry_key);
        }
    }
    if (probe_on) { // bbport (r64b_surface-probe-more): the entry this draw reached, for the log
        probe_draw = {entry_key, static_cast<const u32*>(entry.indices.mapped), entry.triangles,
                      entry.vertices, entry.instances, 0, mask, entry.skinned || draw.skinned,
                      entry.dynamic, entry.blas};
        // A skinned draw's index list as the game holds it now (the entry keeps its own copy
        // from when it was made), in the frames the probe names: does it stay the same?
        if (probe_hash_skinned && probe_draw.skinned && draw.indices && draw.index_count) {
            const u64 bytes = u64(std::min(draw.index_count, ProbeHashIndices)) *
                              (draw.index_size == 2 ? 2u : 4u);
            probe_draw.guest_hash =
                XXH3_64bits_withSeed(reinterpret_cast<const void*>(draw.indices), bytes,
                                     draw.index_count) |
                1ull;
        }
    }
    if (palette_draw) { // bbport (r47b_casters): for the 600-frame line
        ++still_stats.palette_draws;
        still_stats.placed_draws += draw.palette_placed ? 1 : 0;
    }
    if (hold_frames && draw.shadow_pass) { // bbport (r14_cascade_rt): see Holds
        if (entry.shadow_frame != frame) {
            entry.shadow_frame = frame;
            entry.cascades = 0;
        }
        entry.cascades |= u8(1u << cascade);
    }
    // bbport (r17_rt-upkeep): a draw in sun cascade c2/c3 is far; any other (camera pass, c0/c1,
    // not the atlas) is near. A moving caster's first draw this frame is "far only" when it is
    // far and the caster had no near draw last frame (BB_RT_REFIT_EVERY, its counters).
    // bbport (r19_draw-cost, r37_menu-options): with RefitEvery() 0 (BB_RT_REFIT_EVERY and
    // graphics_rt_far_refit, read at each use) r17_far only feeds the far_refit counters and
    // r17_near_frame only r17_far: neither is kept up then (turned on while running: RefitEvery).
    // SunCascade's learning of the atlas side (r14) is kept.
    const bool r19_far_book = !r19 || RefitEvery() != 0;
    u8 r17_cascade = 4;
    if (draw.shadow_pass) {
        if (cascade < 4) {
            r17_cascade = cascade;
        } else if (r19_far_book) {
            r17_cascade = SunCascade(draw);
        } else {
            atlas_side = std::max(atlas_side, draw.target);
            ++r19_stats.far_book_skipped;
        }
    }
    const bool r17_far_draw =
        r19_far_book && draw.shadow_pass && (r17_cascade == 2 || r17_cascade == 3);
    // bbport (r47c_review-fixes): a moving prop known by its palette's address may be two
    // entries, each drawn every other frame (Draw::palette_placed): its near draw of two frames
    // ago is its last one. Counted as "no near draw last frame", such an entry was far only
    // whenever c2/c3 drew it first on a frame, although the camera pass draws it, and its refit
    // was left out (RefitEvery) with the lamp bit kept.
    const u64 r17_near_gap = entry.instance && entry.palette_placed ? 2 : 1;
    const bool r17_far = r17_far_draw && entry.seen_frame != frame &&
                         entry.r17_near_frame + r17_near_gap < frame;
    if (!r17_far_draw && r19_far_book) {
        entry.r17_near_frame = frame;
    }
    // bbport (r46_lamp-cards): what this draw shows of a cut-out card, at every draw of the
    // entry (a second draw of the frame returns just below) and for good: whichever pass comes
    // first, and whether or not the entry counts as moving, lamp rays leave a card out
    // (PrepareScene). Entry::shadow_card below is the rule of before, kept as it was.
    entry.skinned = entry.skinned || draw.skinned;
    entry.skeleton_bones = std::max(entry.skeleton_bones, draw.skeleton_bones); // bbport (r62n_cutout-skinned-blocker)
    entry.card_shadow = entry.card_shadow || (draw.shadow_pass && draw.textured);
    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
    // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders that showed
    // it a cut-out (the 600-frame line of the cut-out cards' pixel shaders)
    if (draw.pixel_shader != 0 && Shader::Optimization::CutoutLogOn()) { // (r54)
        if (draw.camera_pass && draw.alpha && entry.cut_camera_ps != draw.pixel_shader) {
            entry.cut_camera_ps = draw.pixel_shader;
            entry.cut_noted = 0;
        }
        if (draw.shadow_pass && draw.textured && entry.cut_sun_ps != draw.pixel_shader) {
            entry.cut_sun_ps = draw.pixel_shader;
            entry.cut_noted = 0;
        }
    }
    // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1, a cut-out draw's card data, at every
    // draw of the entry (Draw::card)
    if (draw.card) {
        CardNoteDraw(entry, draw);
    }
    // bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry whose pixel
    // shader does not discard (or that has none): the game's sun shadow of it is solid
    if (card_uv_on && draw.shadow_pass && !draw.alpha && entry.card_uv) {
        CardNoteSunSolid(entry, draw);
    }
    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key
    if (draw.camera_pass && RtGlassFind::On()) { // bbport (r86i_glint-find-gbuffer): the box lines name the pair
        entry.find_vs = draw.shader;
        entry.find_ps = draw.pixel_shader;
        entry.find_indices = draw.index_count; // bbport (r86k_glint-box-gbuffer)
        entry.find_flags = draw.find_flags;
        entry.box_candidate = entry.box_candidate || draw.box_candidate;
    }
    // bbport (r76c_sun-fog-shells): with the gate probe or the shell rule on (GateCaptureOn), this
    // draw as the rasterizer described it just before (SetGateCapture), its place among the frame's
    // capture draws that reached an entry, and, from camera pass draws only (a sun pass draw's
    // constants hold the light's camera), the camera's world position (the draw's view-to-world
    // rows at word 180, as ToWorld reads them) now and at the entry's first camera pass draw
    if (gate_cap_on) {
        if (gate_order_frame != frame) {
            gate_order_frame = frame;
            gate_order = 0;
        }
        const bool eye_known = entry.gate_cap.known && entry.gate_cap.eye_known;
        const std::array<float, 3> last_eye = entry.gate_cap.camera;
        const std::array<float, 3> first_eye = entry.gate_cap.first_camera;
        entry.gate_cap = gate_next;
        entry.gate_cap.order = gate_order++;
        entry.gate_cap.eye_known = eye_known;
        entry.gate_cap.camera = last_eye;
        entry.gate_cap.first_camera = first_eye;
        if (draw.camera_pass) {
            const std::array<float, 3> eye{draw.constants[183], draw.constants[187],
                                           draw.constants[191]};
            entry.gate_cap.camera = eye;
            entry.gate_cap.first_camera = eye_known ? first_eye : eye;
            entry.gate_cap.eye_known = true;
        }
    }
    // bbport (r47_still-check): the last camera pass draw of it, also when a sun cascade drew
    // it first on the frame (a caster the camera pass draws is looked at more often)
    if (draw.camera_pass) {
        entry.still_camera_frame = frame;
    }
    if (entry.seen_frame == frame) {
        if ((entry.mask & mask) == 0) {
            entry.mask |= mask;
            tlas_count = 0;
            ++stats.merged;
        }
        // bbport (r54_leaf-stage2): a second draw of the frame may capture the UVs alone (the
        // sun shadow pass's card of an entry the camera pass draws first on every frame)
        pane_result("same-frame-entry-already-selected");
        trace_reflection_reuse(draw.shadow_pass ? "ordinary-same-frame-reuse-shadow" : "ordinary-same-frame-reuse");
        return CardUvProbe(entry, draw);
    }
    entry.mask = mask;
    // Drawn by the game again: the object is back.
    entry.gone = false;
    entry.gone_streak = 0;
    if (mask == ShadowMask) {
        entry.shadow_card = draw.textured;
        entry.shadow = true;
        if (WorldCopies()) {
            EnsureWorld(entry);
        }
    }
    entry.rebuilt = entry.rebuilt || shared;
    // bbport (r43_copy-turns): the frames since a shared copy's draw before (seen_frame is still
    // that draw's here): a copy that is not drawn every frame takes its turn another way. And
    // the copy is listed for the plan at the frame's end (PlanCopyTurns), once.
    if (entry.rebuilt) {
        entry.turn_gap = entry.seen_frame == 0
                             ? u8(CopyTurnGapUnknown)
                             : u8(std::min<u64>(frame - entry.seen_frame, CopyTurnGapUnknown));
        if (!entry.turn_listed) {
            entry.turn_listed = true;
            turn_drawn.push_back(&entry);
        }
    }
    // bbport (r47_still-check): what is done about casters held for still on this draw. With
    // the experiment bit set while the game runs, a caster the looks found moving is held for
    // still again, as before: its BLAS keeps the pose of its last refit. No bounds were taken
    // of that pose (a moving caster's captures are not measured), so what the looks knew of the
    // caster no longer holds: with the bit clear again it is refit once and looked at anew.
    const u32 still = StillNow();
    if (entry.still_moved && still != StillOn) {
        entry.dynamic = false;
        entry.still_moved = false;
        entry.still_has_ref = {};
        entry.still_doubt = false;
        entry.still_checks = 0;
        entry.still_next = frame;
        still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        ++still_stats.taken_back;
    }
    if (entry.palette != draw.palette) {
        entry.palette = draw.palette;
        entry.palette_placed = draw.palette_placed; // bbport (r47b_casters)
        entry.dynamic = true;
        // bbport (r47_still-check): moving by its palette from now on, whatever the looks found
        // (nothing to take back, and not counted under their cap)
        if (entry.still_moved) {
            entry.still_moved = false;
            still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        }
    }
    if (glass_tri_active != 0 && !draw.glass) { // bbport (r86m_glint-pane-from-triangle, TOOL): a mesh a want waits for is captured once more
        for (const RtGlassTri::Want& want : glass_tri->wants) {
            if (want.stage == 1 && want.key == key) {
                entry.built = false;
                break;
            }
        }
    }
    bool needs_data = !entry.built || entry.dynamic || entry.rebuilt ||
                      (need_scene && !entry.blas) ||
                      (entry.shadow && entry.world.buffer && !entry.copied && WorldCopies());
    // bbport (r47_still-check): a caster held for still (built, not moving, not a shared copy,
    // nothing else to capture it for) whose look is due is captured once more as a probe: its
    // vertices go to the positions like any capture's and RecordBuilds measures their bounds
    // (rt_still_sig.comp), but nothing is built or copied from them: the BLAS, the world copy
    // and the entry stay as they are, so the scene and the picture are those of a frame without
    // the look. A probe takes a capture param and room in the positions, never scratch or a
    // budget of builds; where its own budget (StillLane) or that room is used up it waits for
    // the next frame with its turn kept. Not while BB_RT_UPKEEP_FREEZE measures (r26).
    // still_refit: nothing is known of the capture its BLAS holds (it was built while the
    // experiment bit was set, as a shared copy before an instance's entry took it over, or its
    // signature was lost), so a look would have nothing to compare with. With BB_RT_STILL=on it
    // is refit once instead, as a moving caster is at every draw: the BLAS then holds the pose
    // of this frame and that capture's bounds are its reference. (With count it stays a probe,
    // whose bounds become the reference: no structure changes.)
    // Two kinds of capture are never measured, neither for a look nor for a reference: a mesh
    // of more indices than one dispatch of rt_still_sig.comp takes (still_fits), and a draw that
    // starts at another instance than the entry was made with (Param tells the vertex shader to
    // store the entry's instances: such a draw stores nothing, its range of the positions would
    // hold an earlier frame's and read as a move).
    bool still_refit = false;
    const bool still_fits = u64(entry.triangles) * 3 <= StillSigIndicesMost;
    const bool still_stored = draw.first_instance == entry.first_instance;
    // bbport (r47c_review-fixes): the casters looked at in turn that this frame draws, due or
    // not: the pace of their looks is set by all of them (StillCrowd in StillNext below).
    if (still != StillOff && still_fits && !needs_data && need_scene && !entry.still_blind &&
        r26_freeze == 0 && entry.still_checks >= StillEarlyChecks) {
        still_pool += StillPoolShare(
            entry.triangles,
            entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame);
    }
    if (still != StillOff && still_fits && !needs_data && need_scene && entry.still_wait == 0 &&
        !entry.still_blind && frame >= entry.still_next && r26_freeze == 0) {
        // The lane: the first look after a build, the other early looks, the looks in turn.
        // bbport (r47c_review-fixes): and lane 3, a second budget of the looks in turn's size
        // for a look in turn that has waited StillOverdueFrames() frames or more and finds the
        // budget used up once again (StillLaneOf): the budgets go in draw order, and a caster
        // that only every 8th frame draws, after the others, found it used up every time.
        const u32 lane = StillLaneOf(entry.still_checks, still_used[2] >= StillLane(false),
                                     frame - entry.still_next, StillOverdueFrames());
        u32& used = still_used[lane];
        const u64 stored = u64(entry.vertices) * entry.instances;
        // What the looks in turn would need on this frame, looked at or not (StillCrowd).
        still_due += lane >= 2 ? entry.triangles : 0;
        Build probe{&entry, positions_used, true, to_world};
        probe.probe = true;
        if (used >= StillLane(lane < 2)) {
            ++still_stats.waited;
            // bbport (r47c_review-fixes): for the line: the longest wait, served or not, and
            // whose it is (seen_frame is still its draw before)
            if (frame - entry.still_next >= still_stats.oldest_waiting) {
                still_stats.oldest_waiting = frame - entry.still_next;
                still_stats.oldest_triangles = entry.triangles;
                still_stats.oldest_gap = frame - entry.seen_frame;
                still_stats.oldest_near =
                    entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame;
            }
        } else if (!still_stored) {
            ++still_stats.other_draw;
        } else if (still_sig_used >= StillSigsPerFrame || params_used >= MaxParams ||
                   positions_used + stored > MaxPositions ||
                   !StillWorld(draw.constants, probe)) {
            ++still_stats.no_room;
        } else if (still == StillOn && !entry.still_has_ref[0] && !entry.still_has_ref[1]) {
            used += entry.triangles;
            still_refit = true;
            needs_data = true;
        } else {
            used += entry.triangles;
            still_stats.longest_wait =
                std::max(still_stats.longest_wait, frame - entry.still_next);
            probe.param = Param(positions_used, entry);
            (void)CardCapture(entry, draw, probe); // bbport (r54_leaf-stage2): its UVs too
            probe.sig = TakeStillSig(entry);
            probe.still_camera = draw.camera_pass;
            builds.push_back(probe);
            positions_used += u32(stored);
            const bool nearby =
                entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame;
            entry.still_checks += entry.still_checks != 0xff ? 1 : 0;
            entry.still_next =
                frame + StillNext(entry.still_checks, entry.base, nearby,
                                  StillCrowd(still_pool_last, StillLane(false)));
            ++still_stats.probes[lane];
            still_stats.probe_triangles += entry.triangles;
            entry.seen_frame = frame;
            frame_entries.push_back(&entry);
            watch_list("still-signature-only");
            if (stage) {
                PaneStages::Count(stage->ordinary_reuse);
            }
            pane_result("still-signature-only");
            return probe.param;
        }
    }
    // Over budget, a caster built before keeps last frame's BLAS and world copy (exact for static
    // props drawn several times, a frame late for moving ones) rather than vanishing.
    const auto skip = [&](const char* why) {
        pane_result(why, true);
        watch_reason(why);
        ++stats.over_budget;
        if (!entry.built) {
            ++missed;
            return 0u;
        }
        // bbport (r41_lamp-shadows): a moving shared copy drawn without a rebuild (see
        // LampStaleSkips); at most once a frame (a second draw of an entry returns above).
        if (entry.rebuilt && entry.dynamic) {
            entry.lamp_builds = 0;
            const u32 stale_after = LampStaleAfter(); // bbport (r43_copy-turns)
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                entry.lamp_skips = 0; // the BLAS holds this very pose
                entry.lamp_out = false;
                entry.turn_run = entry.turn_back_run = 0;
            } else {
                if (entry.lamp_skips > stale_after || ++entry.lamp_skips > stale_after) {
                    entry.lamp_out = true;
                }
                // bbport (r43_copy-turns): for the 600-frame line, the wait the turns bound:
                // frames in a row without a rebuild while drawn every frame, and draws in a
                // row without one after frames undrawn.
                if (entry.turn_gap == 1) {
                    entry.turn_run += entry.turn_run != 0xffff ? 1 : 0;
                    turn_stats.worst_run = std::max<u32>(turn_stats.worst_run, entry.turn_run);
                } else {
                    entry.turn_run = 0;
                    entry.turn_back_run += entry.turn_back_run != 0xffff ? 1 : 0;
                    turn_stats.worst_back_run =
                        std::max<u32>(turn_stats.worst_back_run, entry.turn_back_run);
                }
            }
        }
        entry.seen_frame = frame;
        frame_entries.push_back(&entry);
        watch_list(why);
        return 0u;
    };
    u32 param = 0;
    pane_entry();
    if (stage) {
        PaneStages::Count(needs_data ? stage->ordinary_needs : stage->ordinary_reuse);
    }
    if (needs_data) {
        // bbport (r47_still-check): still_refit: a refit whatever the age of the build
        const bool update = need_scene && entry.blas && entry.built && !entry.rebuilt &&
                            (still_refit || frame - entry.built_frame < entry.rebuild_every) &&
                            entry.r17_updatable; // bbport (r17_rt-upkeep): not fast-built
        // bbport (r17_rt-upkeep): opt-in refit skips of moving casters, keeping the BLAS (as the
        // over-budget skip does). BB_RT_UNCHANGED=skip: what the vertex shader reads hashes the
        // same as for the capture the BLAS holds. BB_RT_REFIT_EVERY: far only, refit recently.
        if (update && entry.dynamic) {
            const bool on = UpkeepOn();
            const auto keep = [&](const char* why) {
                pane_result(why);
                entry.seen_frame = frame;
                frame_entries.push_back(&entry);
                watch_list("upkeep-reused-capture");
                return 0u;
            };
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                if (on && UnchangedMode() == 2) {
                    ++r17_stats.same_skipped;
                    r17_stats.same_skipped_triangles += entry.triangles;
                    return keep("unchanged-upkeep-reuse");
                }
                ++r17_stats.same_would;
                r17_stats.same_would_triangles += entry.triangles;
            } else if (draw.inputs == 0 && on && UnchangedMode() != 0) {
                ++r17_stats.same_unknown;
            }
            if (r17_far) {
                const u32 every = RefitEvery();
                if (on && every > 1 && frame - entry.r17_capture_frame < every) {
                    ++r17_stats.far_skipped;
                    r17_stats.far_skipped_triangles += entry.triangles;
                    return keep("far-upkeep-reuse");
                }
                ++r17_stats.far_refit;
                r17_stats.far_refit_triangles += entry.triangles;
            }
        }
        const bool refresh = entry.rebuilt && entry.built;
        // With no ray tracing scene nothing is built: a caster captured before is only captured
        // again, which must not use up the budget that lets new casters in.
        const bool recapture = !need_scene && entry.built && !refresh;
        const u64 stored = u64(entry.vertices) * entry.instances;
        const u64 needed = need_scene ? (update ? entry.update_scratch : entry.scratch) + 256 : 0;
        // bbport (r43_copy-turns): a shared copy's refresh takes its turn. With a ticket of the
        // last frame's end (PlanCopyTurns) it is rebuilt; without one only with what the ticket
        // holders still to come leave of the budget. The ticket is used up here, whatever the
        // limits below say: a holder they cut gets a new one by its age. Experiment
        // BbCopyTurns::OldBit set: the first copies in draw order take the budget, as before.
        bool refresh_over = false;
        if (refresh) {
            const u32 budget = RebuiltBudget();
            refresh_over = CopyTurnsOn() ? !copy_turns.Take(entry.turn, entry.triangles, frame,
                                                            rebuilt_triangles, budget)
                                         : rebuilt_triangles >= budget;
            turn_stats.back += entry.turn_gap != 1 ? 1 : 0;
        }
        const bool over = refresh ? refresh_over
                                  : !update && !recapture && new_triangles >= NewTrianglesPerFrame;
        if (positions_used + stored > MaxPositions || scratch_used + needed > ScratchBytes || over) {
            return skip(positions_used + stored > MaxPositions ? "positions-budget" :
                        scratch_used + needed > ScratchBytes ? "scratch-budget" : "triangle-or-copy-turn-budget");
        }
        // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE with BLAS work frozen: this refit or
        // build is left out. A caster with a BLAS keeps it as it is, as skip() does (no capture
        // param, positions or scratch); with the TLAS frozen too, one without stays out of this
        // frame (the TLAS traced as it was could not hold it).
        if (r26_freeze != 0) {
            if ((r26_freeze & 1u) && entry.built && entry.blas) {
                // Counted as today's cadence would record it: a kept BLAS ages past its rebuild
                // window only because of the freeze, and today it is refit on every frame but
                // each rebuild_every-th (where it is built again).
                const bool refit =
                    update || (entry.r17_updatable && !entry.rebuilt &&
                               (frame - entry.built_frame) % entry.rebuild_every != 0);
                if (refit) {
                    ++r26_stats.refits_left;
                    r26_stats.refit_triangles += entry.triangles;
                } else {
                    ++r26_stats.builds_left;
                    r26_stats.build_triangles += entry.triangles;
                }
                entry.seen_frame = frame;
                frame_entries.push_back(&entry);
                watch_list("upkeep-freeze-kept-capture");
                pane_result("upkeep-freeze-kept-capture", true);
                return 0;
            }
            if (r26_freeze == 3u) {
                watch_reason("upkeep-freeze-dropped-build");
                pane_result("upkeep-freeze-dropped-build", true);
                ++r26_stats.left_out;
                return 0;
            }
            ++r26_stats.recorded;
        }
        param = Param(positions_used, entry);
        if (!param) {
            return skip("capture-params-budget");
        }
        builds.push_back({&entry, positions_used, update, to_world});
        if (key_watch) {
            ++key_watch->now.queued;
        }
        builds.back().param = param; // bbport (r47_still-check): see CaptureLeftOut
        if (draw.reflection_native && draw.reflection_native->native_entry) {
            auto& proof = *draw.reflection_native;
            proof.capture_param = param;
            builds.back().reflection_native_cookie = proof.serial;
            builds.back().reflection_native_allocation = proof.allocation;
        }
        if (reflection_tracker) {
            ReflectionQueue(entry, draw, builds.back());
        }
        builds.back().bottle = draw.bottle_candidate && BottleObserved() && entry.address == bottle_entry_address;
        if (stage) {
            stage->param = param;
            stage->build = u32(builds.size());
            PaneStages::Count(stage->build_added);
            pane_result("ordinary-build-added");
        }
        if (draw.window_pane_observe && window_pane_watch) {
            auto& pane = *window_pane_watch;
            if (pane.natural.Active()) {
                pane.natural.Latch({pane.source_frame, frame, entry_key, entry.base, param,
                                    u32(builds.size()), pane_new_entry});
            }
            if (entry.indices.mapped && entry.vertices &&
                u64(entry.vertices) * entry.instances <= WindowPathProbe::PaneVerticesMost &&
                entry.triangles <= WP_TRI_WORDS * 32 && entry.instances &&
                u64(entry.triangles) * 3 == u64(draw.index_count) * entry.instances) {
                pane.param = param;
                pane.rt_frame = frame;
                pane.key = entry.base;
                pane.vertices = entry.vertices;
                pane.instances = entry.instances;
                pane.triangles = entry.triangles;
                std::copy_n(static_cast<const u32*>(entry.indices.mapped),
                            size_t(entry.triangles) * 3, pane.indices.begin());
            } else {
                pane.refusal = "expanded indices or ordinary build size unsupported";
                pane.stages.Refuse(pane.refusal, pane.source_frame, frame);
            }
        }
        if (draw.lamp_pane_observe) { // t132d: attach to this ordinary capture only
            LampPaneProbe& p = *lamp_pane;
            p.capture.build = u32(builds.size());
            p.capture.rt = frame;
            p.param = param;
            p.key = key;
            if (!entry.indices.mapped || !RtLampPane::MeshSize(entry.vertices, entry.triangles, entry.instances)) {
                p.refusal = "invalid normal RT entry or world/index limits exceeded";
            } else {
                p.vertices = entry.vertices;
                p.triangles = entry.triangles;
                p.first_instance = entry.first_instance;
                const auto* indices = static_cast<const u32*>(entry.indices.mapped);
                p.indices.assign(indices, indices + std::size_t(p.triangles) * 3);
                if (p.reconstruction) {
                    auto& r = *p.reconstruction;
                    r.indices = draw.index_count;
                    r.instances = draw.instances;
                    r.index_size = draw.index_size;
                    r.strip = draw.strip;
                    r.restart = draw.restart;
                    r.entry_first = entry.first_vertex;
                    r.raw_min = entry.first_vertex - draw.first_vertex;
                    r.refusal = LampReconstructionIndices(p);
                }
            }
        }
        if (probe_on) { // bbport (r64b_surface-probe-more): this draw builds the entry
            probe_draw.build = u32(builds.size());
        }
        if (glass_tri_active != 0 && !draw.glass) { // bbport (r86m_glint-pane-from-triangle, TOOL): its world positions for a want
            GlassTriCopy(entry, key, u32(builds.size()));
        }
        (void)CardCapture(entry, draw, builds.back()); // bbport (r54_leaf-stage2): its UVs too
        stats.refit_triangles += update ? entry.triangles : 0;
        // bbport (r17_rt-upkeep): a shared copy's refresh (never refit) is built for speed
        builds.back().fast = UpkeepOn() && refresh;
        builds.back().inputs = draw.inputs;
        builds.back().vs_hash = draw.shader; // bbport (r62d_card-uv-diag)
        // bbport (r47_still-check): the BLAS of a caster held for still is built from this
        // capture: its bounds are what the looks compare with (they arrive with the signature;
        // those of the capture before no longer hold), and its looks start again. Where the
        // capture cannot be measured (still_fits, still_stored above) nothing is known of it.
        if (still != StillOff && need_scene && !entry.dynamic && !entry.rebuilt) {
            if (still_fits && still_stored && StillWorld(draw.constants, builds.back())) {
                builds.back().sig = TakeStillSig(entry);
                builds.back().still_camera = draw.camera_pass;
                builds.back().still_first = true;
            }
            entry.still_has_ref = {};
            entry.still_blind = false;
            entry.still_doubt = false;
            entry.still_checks = 0;
            still_stats.refits += still_refit ? 1 : 0;
            entry.still_next = frame + StillNext(0, entry.base, true);
        }
        // Keep the stock first capture and all of its later membership merges. Only an
        // ordinary build admitted above can choose the affine position producer.
        auto& build = builds.back();
        if (draw.lamp_affine_candidate && LampAffineAvailable() &&
            entry.first_vertex == 0 && entry.vertices == LampAffineVertices &&
            entry.instances == RtLampPane::Instances && entry.first_instance == 0 &&
            entry.triangles == RtLampPane::DrawIndices && entry.indices.mapped &&
            LampAffineProjection(draw.constants + 52) &&
            XXH64(entry.indices.mapped, RtLampPane::DrawIndices * sizeof(u32), 0) ==
                LampAffineTopologyHash &&
            (build.sig != 0 || StillWorld(draw.constants, build)) && LampAffineTopology(draw)) {
            build.lamp_affine = true;
            build.lamp_affine_depth = {draw.constants[62], draw.constants[63]};
        }
        positions_used += u32(stored);
        scratch_used += needed;
        if (!update) {
            if (refresh) {
                rebuilt_triangles += entry.triangles;
                ++stats.shared_builds;
            } else if (!recapture) {
                new_triangles += entry.triangles;
            }
            if (need_scene) {
                stats.built_triangles += entry.triangles;
            }
        }
        if (!update) {
            entry.built_frame = frame;
            // bbport (r41_lamp-shadows): rebuilt: back in lamp rays after LampFreshBuilds in a row
            // bbport (r43_copy-turns): with turns on at the first rebuild that came in time: no
            // more draws went without since the rebuild before than count as starved. A copy
            // whose every turn comes too late stays starved (see LampStaleSkips).
            const bool in_time = entry.lamp_skips <= LampStaleAfter();
            entry.lamp_skips = 0;
            entry.turn_run = entry.turn_back_run = 0;
            if (entry.lamp_out &&
                (CopyTurnsOn() ? in_time : ++entry.lamp_builds >= LampFreshBuilds)) {
                entry.lamp_out = false;
                entry.lamp_builds = 0;
            }
        }
        stats.dynamic_draws += entry.dynamic ? 1 : 0;
    }
    // bbport (r54_leaf-stage2): a draw nothing else captured may capture the UVs alone
    if (param == 0) {
        param = CardUvProbe(entry, draw);
    }
    entry.seen_frame = frame;
    frame_entries.push_back(&entry);
    watch_list(key_watch && key_watch->now.queued ? "ordinary-capture-queued" : "listed-retained-or-auxiliary");
    if (!needs_data) {
        pane_result("ordinary-cached-reuse");
        trace_reflection_reuse(draw.shadow_pass ? "ordinary-cached-reuse-shadow" : "ordinary-cached-reuse");
        if (!param && draw.bottle_delivery && draw.bottle_delivery->observed) {
            draw.bottle_delivery->private_param = NominateBottleSpan(entry, draw, to_world);
        }
    }
    return param;
}

void RtShadow::RecordBuilds() {
    if (window_scene_active_serial) {
        window_scene_active_serial = 0;
    }
    ConsumeBottleSpan();
    if (builds.empty()) {
        return;
    }
    BB_SECTION(RtBuilds);
    const bool world_copies = WorldCopies();
    // bbport (r47_still-check): a probe builds nothing; a call that holds probes alone leaves
    // the scene as it is (no build to wait for, the instance records as written).
    const bool built_any = std::ranges::any_of(
        builds, [](const Build& b) { return !b.probe && !b.left_out; });
    if (need_scene && built_any) {
        r17_blas_dirty = true; // bbport (r17_rt-upkeep): the TLAS cannot be skipped
    }
    struct Job {
        struct ClipCopy {
            vk::Buffer destination{};
            std::array<vk::BufferCopy, LampReconstruction::Slots> regions{};
        };
        std::unique_ptr<ClipCopy> clip;
        vk::Buffer bottle{};
        std::vector<vk::BufferCopy> bottle_regions;
        std::vector<vk::AccelerationStructureGeometryKHR> geometries;
        std::vector<vk::AccelerationStructureBuildGeometryInfoKHR> infos;
        std::vector<vk::AccelerationStructureBuildRangeInfoKHR> ranges;
        std::vector<const vk::AccelerationStructureBuildRangeInfoKHR*> pointers;
        std::vector<UnprojectPush> unproject;
        std::vector<LampAffinePush> lamp_affine;
        vk::Pipeline lamp_affine_pipeline;
        vk::PipelineLayout lamp_affine_layout;
        vk::Buffer lamp_affine_bits;
        std::vector<std::pair<vk::Buffer, vk::BufferCopy>> copies;
        // bbport (r47_still-check): the captures whose bounds are measured, and their
        // signatures' bytes in still_sigs (source) and in the frame's part of still_readback
        std::vector<StillPush> still;
        vk::BufferCopy still_copy;
        // bbport (r54_leaf-stage2): the expand pass's dispatches, the stat slots they fill,
        // and the ring's bytes filled with CARD_UV_RING_UNSET after them (0: none)
        std::vector<CardUvPush> card;
        u32 card_stat_mask = 0;
        // bbport (r62d_card-uv-diag): the geometry check's dispatches (geo_pipeline set: the
        // check is on), its first zeroing, the copy for the host, and fix A's barrier
        std::vector<GeoCheckPush> geo;
        vk::Pipeline geo_pipeline{};
        vk::PipelineLayout geo_layout{};
        vk::Buffer geo_buffer{}, geo_readback{};
        bool geo_clear = false;
        bool geo_flush = false;
        bool war_barrier = false;
        vk::DeviceSize card_ring_fill = 0;
        bool probe_host = false; // bbport (r64b_surface-probe-more): a probe slot is copied
        // bbport (r62e_leaf-cards-usable): the guard's dispatches (guard_pipeline set: some)
        std::vector<CardGuardPush> guard;
        vk::Pipeline guard_pipeline{};
        vk::PipelineLayout guard_layout{};
        vk::Buffer guard_buffer{};
    };
    auto job = std::make_shared<Job>();
    job->geometries.reserve(builds.size());
    job->ranges.reserve(builds.size());
    job->unproject.reserve(builds.size());
    u64 scratch_at = 0;
    const auto align = [&](u64 v) { return (v + scratch_align - 1) / scratch_align * scratch_align; };
    const u32 still_slot = u32(frame % 4);
    u32 sig_first = UINT32_MAX, sig_last = 0;
    for (const Build& build : builds) {
        if (auto* pane = window_pane_watch; pane && pane->param && pane->rt_frame == frame &&
            pane->param == build.param) {
            WindowPathProbe::PaneStages::Count(pane->stages.matching_build);
            if (build.left_out) {
                WindowPathProbe::PaneStages::Count(pane->stages.build_left_out);
                pane->stages.Refuse("record-build-left-out", pane->source_frame, frame);
            }
            if (build.probe) {
                WindowPathProbe::PaneStages::Count(pane->stages.probe_only);
            }
        }
        Entry& e = *build.entry;
        // The compact copy belongs to one actual ordinary BLAS generation. Drop it before
        // any replacement attempt, even when an ordinary capture later fails its checks.
        if (!build.probe) {
            InvalidateBottleGeometry(e.address);
        }
        // bbport (r47_still-check): the draw of this capture was left out (CaptureLeftOut): its
        // range of the positions was not written. Nothing is measured, built or copied from it;
        // like a build that was never recorded (OnFrameEnd), the entry is built at its next
        // draw.
        if (build.left_out) {
            if (reflection_tracker) {
                ReflectionDropCapture(build);
            }
            if (probe_on) { // bbport (r64b_surface-probe-more): no copy for the surface probe
                ProbeDropped(build);
            }
            if (!build.probe) {
                e.built = e.built && build.update;
                e.r17_inputs = 0;
            }
            continue;
        }
        // bbport (r47_still-check): the bounds of this capture are measured over the vertices
        // its triangles use, as it was stored (clip space, before the pass below brings it to
        // world space); the host reads them at a frame's end (ReadStillSigs). A probe is done
        // with that: its positions are read by nothing else.
        // bbport (r54_leaf-stage2): this capture also stored the entry's card UVs
        // (CardCapture): they are expanded into its block of the pool (the lambda below),
        // unless the entry's coordinates changed since the capture (it is captured again).
        if (build.uv_base != 0 && e.card_uv && e.card_uv->block) {
            CardUvEntry& c = *e.card_uv;
            CardSelector selector;
            if (c.uv.card.uv_hash != build.uv_hash ||
                !UnpackCardSelector(c.uv.card.selector, selector)) {
                ++card_uv_stats.dropped;
            } else {
                u32 stat = 0;
                if (card_stat_used < CARD_UV_STAT_SLOTS) {
                    stat = ++card_stat_used;
                    card_stat_info[stat - 1] = {e.base, c.uv.card.ps_hash, e.triangles,
                                                CardClassOf(e.skinned, e.lone == LampLoneState::Lone),
                                                c.uv.card.camera, &e, c.uv.card.selector};
                    job->card_stat_mask |= 1u << (stat - 1);
                    card_stat_tick = scheduler.CurrentTick();
                }
                job->card.push_back({e.indices.address, build.uv_base - 1, e.triangles, c.offset,
                                     CardPushFlags(c.uv.card.mode_u, c.uv.card.mode_v,
                                                   selector.has_alpha, stat),
                                     {}, CardPoolAffine(c.uv.card.affine)});
                CardRecorded(c.uv, scheduler.CurrentTick());
                if (!c.pending) {
                    c.pending = true;
                    card_pending.push_back(&e);
                }
                ++card_uv_stats.expanded;
                card_uv_stats.expanded_triangles += e.triangles;
            }
        }
        if (build.sig != 0) {
            job->still.push_back({build.still_rows, build.still_origin, build.store,
                                  e.indices.address, e.triangles * 3, build.sig - 1});
            still_pending[still_slot].push_back(
                {&e, frame, build.sig, build.still_camera, build.still_first});
            sig_first = std::min(sig_first, build.sig);
            sig_last = std::max(sig_last, build.sig);
        }
        if (build.probe) {
            continue;
        }
        const UnprojectPush unproject{build.to_world, build.store, e.vertices * e.instances};
        if (build.bottle && need_scene && BottleObserved() && e.address == bottle_entry_address &&
            (e.mask & CameraMask) != 0 && e.seen_frame == frame) {
            const auto corners = bottle_topology.Corners();
            if (std::ranges::all_of(corners, [&](u32 index) { return index < e.vertices; })) {
                constexpr u64 CornerBytes = 16;
                if (!bottle_corners.buffer) {
                    Make(bottle_corners, corners.size() * CornerBytes, false,
                         VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT);
                }
                if (bottle_corners.buffer) {
                    job->bottle = bottle_corners.buffer;
                    job->bottle_regions.clear();
                    job->bottle_regions.reserve(corners.size());
                    for (std::size_t i = 0; i < corners.size(); ++i) {
                        job->bottle_regions.push_back({(u64(build.store) + corners[i]) * CornerBytes,
                                                       i * CornerBytes, CornerBytes});
                    }
                    bottle_resident_address = e.address;
                    bottle_resident_capture = frame;
                }
            }
        }
        if (build.lamp_affine) {
            job->lamp_affine.push_back({unproject.rows, build.still_rows, build.still_origin,
                                        unproject.first, unproject.count, e.vertices,
                                        build.lamp_affine_depth[0], build.lamp_affine_depth[1]});
            job->lamp_affine_pipeline = *lamp_affine_pipeline;
            job->lamp_affine_layout = *lamp_affine_layout;
            job->lamp_affine_bits = lamp_affine_bits.buffer;
        } else {
            job->unproject.push_back(unproject);
        }
        e.built = true;
        e.blas = need_scene;
        // bbport (r17_rt-upkeep): what the BLAS now holds and how it was built
        e.r17_inputs = need_scene ? build.inputs : 0;
        if (need_scene) {
            e.r17_updatable = !build.fast;
            e.r17_capture_frame = frame; // BB_RT_REFIT_EVERY: the BLAS holds this frame's pose
            if (build.update) {
                ++r17_stats.refit;
                r17_stats.refit_triangles += e.triangles;
            } else {
                ++r17_stats.rebuilt;
                r17_stats.rebuilt_triangles += e.triangles;
                r17_stats.fast += build.fast ? 1 : 0;
                r17_stats.fast_triangles += build.fast ? e.triangles : 0;
            }
        }
        const vk::DeviceSize world_bytes = vk::DeviceSize(e.vertices) * e.instances * 16;
        ++world_copy_stats.builds;
        if (e.world.buffer && world_copies) {
            job->copies.push_back({e.world.buffer,
                                   vk::BufferCopy{u64(build.store) * 16, 0, world_bytes}});
            e.copied = true;
            e.copied_at = ++copies;
            ++world_copy_stats.copies;
            world_copy_stats.bytes += world_bytes;
        } else {
            // A copy made before the VSM was switched off is stale from now on: turning it back
            // on recaptures this caster (PrepareDraw's needs_data).
            if (e.world.buffer) {
                e.copied = false;
            }
            if (e.shadow) {
                ++world_copy_stats.skipped;
                world_copy_stats.skipped_bytes += world_bytes;
            }
        }
        // bbport (r64b_surface-probe-more): the surface probe asked for this build's world
        // positions (ProbeCopyBuild): copied to its host slot with the world copies below
        if (probe_on && build.probe_slot != 0) {
            if (probe_world.buffer && world_bytes <= vk::DeviceSize(ProbeSlotLimit(build.probe_slot - 1)) * 16) {
                job->copies.push_back(
                    {probe_world.buffer,
                     vk::BufferCopy{u64(build.store) * 16,
                                    u64(ProbeSlotFirst(build.probe_slot - 1)) * 16,
                                    world_bytes}});
                probe_ticks[build.probe_slot - 1] = scheduler.CurrentTick();
                job->probe_host = true;
            } else {
                ProbeDropped(build);
            }
        }
        if (auto* pane = window_pane_watch; pane && !pane->refusal && !pane->tick &&
            pane->param && pane->rt_frame == frame && pane->param == build.param &&
            (!pane->natural.Active() ||
             (pane->natural.MatchBuild(frame, build.param, u32(&build - builds.data() + 1), e.base) &&
              WindowPathProbe::NaturalPanePair::Clock::now() < pane->natural.deadline))) {
            if (world_bytes != pane->WorldBytes()) {
                pane->Refuse("ordinary build span changed");
            } else {
                WindowPathProbe::PaneStages::Count(pane->stages.span_ok);
                if (pane->Allocate()) {
                    job->copies.push_back({vk::Buffer{pane->buffer},
                                           vk::BufferCopy{u64(build.store) * 16, 0, world_bytes}});
                    job->probe_host = true;
                    pane->tick = scheduler.CurrentTick();
                    WindowPathProbe::PaneStages::Count(pane->stages.queued);
                }
            }
        }
        if (lamp_pane && !lamp_pane->refusal && lamp_pane->Captured() && !lamp_pane->world_tick &&
            lamp_pane->capture.rt == frame && lamp_pane->param == build.param) {
            auto& p = *lamp_pane;
            if (p.reconstruction && p.capture.build == u32(&build - builds.data() + 1)) {
                auto& r = *p.reconstruction;
                r.affine = build.lamp_affine;
                if (r.affine) {
                    r.relative_rows = build.still_rows;
                    r.origin = build.still_origin;
                }
            }
            if (world_bytes != p.WorldBytes()) {
                p.refusal = "recorded world span differs from capture";
            } else if (p.Allocate(instance.GetAllocator(), scheduler)) {
                job->copies.push_back({vk::Buffer{p.buffer},
                                       vk::BufferCopy{u64(build.store) * 16, 0, world_bytes}});
                job->probe_host = true;
                p.world_tick = scheduler.CurrentTick();
                if (p.reconstruction && !p.reconstruction->refusal) {
                    auto& r = *p.reconstruction;
                    const bool card_collapse = need_scene && card_guard_on && e.card_uv &&
                                               job->guard.size() < CardGuardSlots;
                    if (card_collapse) {
                        r.refusal = "card collapse may overwrite the unprojected output";
                    } else if (p.capture.build != u32(&build - builds.data() + 1) ||
                               p.key != e.base || p.vertices != e.vertices ||
                               p.triangles != e.triangles || p.first_instance != e.first_instance ||
                               r.instances != e.instances || r.entry_first != e.first_vertex ||
                               !p.world_tick || job->clip || unproject.first != build.store ||
                               u64(unproject.count) * 16 != world_bytes ||
                               u64(unproject.first) + unproject.count > MaxPositions) {
                        r.refusal = "ordinary reconstruction build identity or position span changed";
                    } else {
                        auto copy = std::make_unique<Job::ClipCopy>();
                        copy->destination = vk::Buffer{p.buffer};
                        for (std::size_t i = 0; i < r.expanded.size(); ++i) {
                            const u32 index = r.expanded[i];
                            if (index >= unproject.count) {
                                r.refusal = "pre-unproject corner index is out of bounds";
                                break;
                            }
                            copy->regions[i] = vk::BufferCopy{
                                (u64(unproject.first) + index) * 16,
                                p.ClipOffset() + i * 16, 16};
                        }
                        if (!r.refusal) {
                            r.rows = unproject.rows;
                            r.first = unproject.first;
                            r.count = unproject.count;
                            r.clip_tick = p.world_tick;
                            job->clip = std::move(copy);
                        }
                    }
                }
            }
        }
        if (!need_scene) {
            if (reflection_tracker) {
                ReflectionDropCapture(build);
            }
            continue;
        }
        job->geometries.push_back({
            .geometryType = vk::GeometryTypeKHR::eTriangles,
            .geometry = {.triangles = vk::AccelerationStructureGeometryTrianglesDataKHR{
                .vertexFormat = vk::Format::eR32G32B32Sfloat,
                .vertexData = {.deviceAddress = positions.address + u64(build.store) * 16},
                .vertexStride = 16,
                .maxVertex = e.vertices * e.instances - 1,
                .indexType = vk::IndexType::eUint32,
                .indexData = {.deviceAddress = e.indices.address},
            }},
            .flags = vk::GeometryFlagBitsKHR::eOpaque,
        });
        job->infos.push_back({
            .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
            // bbport (r17_rt-upkeep): a shared copy's refresh: rebuilt next time, never refit
            .flags = build.fast ? vk::BuildAccelerationStructureFlagsKHR(
                                      vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastBuild)
                                : vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace |
                                      vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate,
            .mode = build.update ? vk::BuildAccelerationStructureModeKHR::eUpdate
                                 : vk::BuildAccelerationStructureModeKHR::eBuild,
            .srcAccelerationStructure = build.update ? e.handle : vk::AccelerationStructureKHR{},
            .dstAccelerationStructure = e.handle,
            .geometryCount = 1,
            .pGeometries = &job->geometries.back(),
            .scratchData = {.deviceAddress = scratch.address + scratch_at},
        });
        scratch_at += align(build.update ? e.update_scratch : e.scratch);
        if (BbSpike::on && !build.update) { // bbport (r23_spike-trace)
            BbSpike::rt_builds.fetch_add(1, std::memory_order_relaxed);
            BbSpike::rt_build_triangles.fetch_add(e.triangles, std::memory_order_relaxed);
        }
        job->ranges.push_back({.primitiveCount = e.triangles});
        job->pointers.push_back(&job->ranges.back());
        if (reflection_native_tracked) {
            ReflectionNativeRecordBuild(e, build);
        }
        if (reflection_tracker) {
            ReflectionBuild(e, build);
        }
        if (roof_probe && roof_probe->Enabled()) {
            const u64 legacy_hash = XXH3_64bits(build.to_world.data(), sizeof(build.to_world));
            u64 geometry_hash = legacy_hash;
            if (build.lamp_affine) {
                // The only admitted topology was verified against this build's bound indices.
                constexpr std::string_view representation = "lamp-affine-v1";
                const std::array<u64, 6> parts{
                    XXH3_64bits(representation.data(), representation.size()),
                    legacy_hash,
                    XXH3_64bits(build.still_rows.data(), sizeof(build.still_rows)),
                    XXH3_64bits(build.still_origin.data(), sizeof(build.still_origin)),
                    XXH3_64bits(build.lamp_affine_depth.data(), sizeof(build.lamp_affine_depth)),
                    LampAffineTopologyHash,
                };
                geometry_hash = XXH3_64bits(parts.data(), sizeof(parts));
            }
            roof_probe->RecordGeometry(e.address, geometry_hash);
            if (auto* row = RoofWatchEntry(e)) {
                ++row->now.captured;
                row->Cache(e.address, roof_probe->Geometry(e.address), e.r17_capture_frame, "guarded-cache");
            }
        }
        // bbport (r62d_card-uv-diag): the geometry check of what this build reads
        if (geo_on) {
            u32 serial = 0xffffffffu;
            if (geo_infos.size() < GeoCheckInfosMost) {
                serial = u32(geo_infos.size());
                const u32 flags =
                    (build.update ? 1u : 0u) | (build.fast ? 2u : 0u) |
                    ((e.mask & CameraMask) != 0 ? 4u : 0u) | ((e.mask & ShadowMask) != 0 ? 8u : 0u) |
                    (e.dynamic ? 16u : 0u) | (e.rebuilt ? 32u : 0u) | (e.instance ? 64u : 0u) |
                    (e.skinned ? 128u : 0u) | (e.card_uv != nullptr ? 256u : 0u) |
                    (e.held ? 512u : 0u) | (build.uv_base != 0 ? 1024u : 0u);
                geo_infos.push_back({e.base, build.vs_hash, e.triangles, flags});
            }
            job->geo.push_back({e.indices.address, build.store, e.triangles,
                                e.vertices * e.instances, serial, geo_huge, geo_huge / 8.0f});
            ++geo_window.builds;
            geo_window.refits += build.update ? 1 : 0;
            geo_window.triangles += e.triangles;
        }
        // bbport (r62e_leaf-cards-usable): a build of an entry ever drawn as a cut-out is guarded
        // (rt_card_guard.comp): dropped from the scene (every vertex at the origin) when it reads a
        // vertex past its own, a corner that is not a number or an edge over CardGuardEdge
        if (card_guard_on && e.card_uv) {
            if (job->guard.size() < CardGuardSlots) {
                job->guard.push_back({e.indices.address, build.store, e.triangles,
                                      e.vertices * e.instances, u32(job->guard.size()),
                                      u32(CARD_GUARD_DETECT), CardGuardEdge, u32(e.base),
                                      u32(e.base >> 32)});
                ++card_safe.guarded;
            } else {
                ++card_safe.unguarded;
            }
        }
    }
    builds.clear();
    positions_used = 0;
    scratch_used = 0;
    // bbport (r54_leaf-stage2): the ring is reused as the positions are. What this call's
    // captures and those no call took (card_ring_dirty) used of it, or all of it once before
    // any capture stores UVs, is filled with CARD_UV_RING_UNSET after the expand pass (the
    // lambda below): a vertex a later capture does not store reads as not finite, never as
    // an earlier capture's values.
    if (card_uv_ready && (card_ring_used != 0 || card_ring_dirty != 0 || !card_ring_clean)) {
        job->card_ring_fill =
            card_ring_clean
                ? vk::DeviceSize(std::max(card_ring_used, card_ring_dirty)) * CARD_UV_RING_BYTES
                : vk::DeviceSize(CardRingBytes);
        card_ring_clean = true;
        card_ring_dirty = 0;
    }
    card_ring_used = 0;
    if (frame >= world_copy_stats.printed_frame + 600) {
        std::printf("Ray tracing world copies: %llu builds, %llu copied (%.1f MB), %llu sun shadow "
                    "builds not copied (%.1f MB) since the last line; copies %s (sun VSM %s, "
                    "experiment 16777216 %s)\n",
                    static_cast<unsigned long long>(world_copy_stats.builds),
                    static_cast<unsigned long long>(world_copy_stats.copies),
                    double(world_copy_stats.bytes) / 1048576.0,
                    static_cast<unsigned long long>(world_copy_stats.skipped),
                    double(world_copy_stats.skipped_bytes) / 1048576.0,
                    world_copies ? "on" : "off",
                    BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed) ? "on" : "off",
                    BbToggle::Experiment(16777216) ? "set" : "clear");
        world_copy_stats = {};
        world_copy_stats.printed_frame = frame;
    }
    // bbport: its own row in the GPU profile (BB_GPU_PROFILE=1); before, its time went to the
    // pass recorded before it (with the ray traced sun: the game's shadow blur, ps 11ffdfb5).
    // bbport (r47_still-check): this call's signatures (taken one after the other, so one run
    // of slots) and the tick the host waits for before it reads them
    if (!job->still.empty()) {
        const vk::DeviceSize sig_bytes = StillSigWords * 4;
        job->still_copy = vk::BufferCopy{
            (sig_first - 1) * sig_bytes,
            (vk::DeviceSize(still_slot) * StillSigsPerFrame + sig_first - 1) * sig_bytes,
            (sig_last - sig_first + 1) * sig_bytes};
        still_ticks[still_slot] = scheduler.CurrentTick();
    }
    // bbport (r62d_card-uv-diag): BB_RT_CARD_UV_DIAG=3 or 5 (fix A). This call's builds and world
    // copies read the positions; captures recorded after it write them again from 0 (the reset
    // above), and only an AsBuild->AsBuild barrier followed: nothing ordered those writes after
    // the reads. An execution dependency at the end of the call does (a write after a read needs
    // no memory dependency).
    job->war_barrier = card_diag == 3 || card_diag == 5;
    if (geo_on) {
        job->geo_pipeline = *geo_pipeline;
        job->geo_layout = *geo_layout;
        job->geo_buffer = geo_buffer.buffer;
        job->geo_readback = geo_readback.buffer;
        job->geo_clear = !geo_clean;
        geo_clean = true;
        ++geo_window.calls;
        const u64 now = GeoCheckNowMs();
        if (!geo_pending && (frame >= geo_frame + GeoCheckFrames || now >= geo_time + GeoCheckMs)) {
            job->geo_flush = true;
            GeoCheckTakeWindow(now);
        }
    }
    if (!job->guard.empty()) { // bbport (r62e_leaf-cards-usable)
        job->guard_pipeline = *guard_pipeline;
        job->guard_layout = *guard_layout;
        job->guard_buffer = card_guard.buffer;
    }
    EffectPass::Mark(16, "ray tracing geometry");
    scheduler.RecordCrumb(
        {.name = "Ray tracing geometry"},
        [job, positions = positions.buffer, unproject_pipeline = *unproject_pipeline,
         unproject_layout = *unproject_layout, still_sigs = still_sigs.buffer,
         still_readback = still_readback.buffer, still_pipeline = *still_pipeline,
         still_layout = *still_layout, card_ring_buffer = card_ring.buffer,
         card_pool_buffer = card_pool.buffer, card_stat_buffer = card_stat_buffer.buffer,
         card_readback_buffer = card_readback.buffer, card_pipeline = *card_pipeline,
         card_layout = *card_layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eAllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute,
                   vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            const vk::DescriptorBufferInfo position_info{positions, 0, VK_WHOLE_SIZE};
            // bbport (r47_still-check): the signatures: their slots zeroed, the bounds of each
            // capture gathered from its vertices as they were stored (before the pass below
            // overwrites them with their world space places), and the slots copied to where the
            // host reads them. Nothing here writes the positions.
            if (!job->still.empty()) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                cmdbuf.fillBuffer(still_sigs, job->still_copy.srcOffset, job->still_copy.size, 0);
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
                const vk::DescriptorBufferInfo sig_info{still_sigs, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 2> still_writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &position_info},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &sig_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, still_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, still_layout, 0,
                                            still_writes);
                for (const StillPush& push : job->still) {
                    cmdbuf.pushConstants(still_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(push), &push);
                    cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
                }
                // The slots are written (for the copy), and the positions were read: the pass
                // below writes them only after these dispatches.
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferRead);
                cmdbuf.copyBuffer(still_sigs, still_readback, job->still_copy);
                // The host reads the copy after the submission's tick; the next call's fill
                // comes after this copy.
                EffectPass::MemoryBarrier(cmdbuf, Transfer,
                                          vk::AccessFlagBits2::eTransferRead |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost | Transfer,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eTransferWrite);
            }
            // bbport (r54_leaf-stage2): the card UVs of this call's UV captures into the pool
            // (rt_card_uv.comp). The captures' vertex shaders wrote the ring before the
            // barrier at the top; this reads the ring and the triangle lists and writes the
            // pool and the stat slots only: no light target, no camera depth, nothing of the
            // positions, so no lamp batch needs to end for it. Nothing reads the pool yet.
            if (!job->card.empty()) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr vk::DeviceSize slot_bytes = CARD_UV_STAT_WORDS * 4;
                if (job->card_stat_mask != 0) {
                    for (u32 s = 0; s < CARD_UV_STAT_SLOTS; ++s) {
                        if (job->card_stat_mask & (1u << s)) {
                            cmdbuf.fillBuffer(card_stat_buffer, s * slot_bytes, slot_bytes, 0);
                        }
                    }
                    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                              Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                const vk::DescriptorBufferInfo ring_info{card_ring_buffer, 0, VK_WHOLE_SIZE};
                const vk::DescriptorBufferInfo pool_info{card_pool_buffer, 0, VK_WHOLE_SIZE};
                const vk::DescriptorBufferInfo stat_info{card_stat_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 3> card_writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ring_info},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &pool_info},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &stat_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, card_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, card_layout, 0,
                                            card_writes);
                for (const CardUvPush& push : job->card) {
                    cmdbuf.pushConstants(card_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(push), &push);
                    cmdbuf.dispatch((push.triangles + CARD_UV_GROUP - 1) / CARD_UV_GROUP, 1, 1);
                }
                // The ring was read (the next call's captures write it again), the pool and
                // the stat slots written (for the copy below, and for later readers).
                EffectPass::MemoryBarrier(cmdbuf, Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite,
                                          Compute | vk::PipelineStageFlagBits2::eVertexShader |
                                              Transfer,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferRead);
                if (job->card_stat_mask != 0) {
                    for (u32 s = 0; s < CARD_UV_STAT_SLOTS; ++s) {
                        if (job->card_stat_mask & (1u << s)) {
                            cmdbuf.copyBuffer(card_stat_buffer, card_readback_buffer,
                                              vk::BufferCopy{s * slot_bytes, s * slot_bytes,
                                                             slot_bytes});
                        }
                    }
                    EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                              vk::PipelineStageFlagBits2::eHost,
                                              vk::AccessFlagBits2::eHostRead);
                }
            }
            // bbport (r54_leaf-stage2): the ring's used part (all of it the first time) back to
            // CARD_UV_RING_UNSET: after the captures' writes and the expand pass's reads, before
            // the next captures. A vertex a later capture does not store then reads as not finite.
            if (job->card_ring_fill != 0) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr auto Vertex = vk::PipelineStageFlagBits2::eVertexShader;
                constexpr auto ShaderAccess =
                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
                EffectPass::MemoryBarrier(cmdbuf, Compute | Vertex, ShaderAccess, Transfer,
                                          vk::AccessFlagBits2::eTransferWrite);
                cmdbuf.fillBuffer(card_ring_buffer, 0, job->card_ring_fill, CARD_UV_RING_UNSET);
                EffectPass::MemoryBarrier(cmdbuf, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                          Compute | Vertex, ShaderAccess);
            }
            if (job->clip) {
                constexpr auto Vertex = vk::PipelineStageFlagBits2::eVertexShader;
                constexpr auto Copy = vk::PipelineStageFlagBits2::eCopy;
                using Access = vk::AccessFlagBits2;
                EffectPass::MemoryBarrier(cmdbuf, Vertex, Access::eShaderWrite, Copy,
                                          Access::eTransferRead);
                cmdbuf.copyBuffer(positions, job->clip->destination, job->clip->regions);
                EffectPass::MemoryBarrier(cmdbuf, Copy, Access::eTransferRead, Compute,
                                          Access::eShaderWrite);
            }
            const vk::WriteDescriptorSet write{.dstBinding = 0,
                                               .descriptorCount = 1,
                                               .descriptorType = vk::DescriptorType::eStorageBuffer,
                                               .pBufferInfo = &position_info};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, unproject_layout, 0, write);
            for (const UnprojectPush& push : job->unproject) {
                cmdbuf.pushConstants(unproject_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
            }
            if (!job->lamp_affine.empty()) {
                const vk::DescriptorBufferInfo bit_info{job->lamp_affine_bits, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 2> writes{{
                    write,
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &bit_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, job->lamp_affine_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, job->lamp_affine_layout,
                                            0, writes);
                for (const LampAffinePush& push : job->lamp_affine) {
                    cmdbuf.pushConstants(job->lamp_affine_layout, vk::ShaderStageFlagBits::eCompute,
                                         0, sizeof(push), &push);
                    cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
                }
            }
            // bbport (r62e_leaf-cards-usable): the guard of the cut-out builds (rt_card_guard.comp):
            // their flags zeroed, DETECT over their triangles, COLLAPSE over their vertices; after the
            // pass above wrote the positions, before the check and the builds below read them
            if (job->guard_pipeline) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr auto ShaderAccess =
                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
                // the previous call's COLLAPSE read these flags: the fill waits for it
                EffectPass::MemoryBarrier(cmdbuf, Compute, {}, Transfer, {});
                cmdbuf.fillBuffer(job->guard_buffer, vk::DeviceSize(CARD_GUARD_W_FLAGS) * 4,
                                  vk::DeviceSize(job->guard.size()) * 4, 0);
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderAccess);
                const vk::DescriptorBufferInfo guard_info{job->guard_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 2> guard_writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &position_info},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &guard_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, job->guard_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, job->guard_layout, 0,
                                            guard_writes);
                for (const u32 mode : {u32(CARD_GUARD_DETECT), u32(CARD_GUARD_COLLAPSE)}) {
                    for (CardGuardPush push : job->guard) {
                        push.mode = mode;
                        cmdbuf.pushConstants(job->guard_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                             sizeof(push), &push);
                        const u32 items =
                            mode == u32(CARD_GUARD_DETECT) ? push.triangles : push.vertex_count;
                        cmdbuf.dispatch((items + u32(CARD_GUARD_GROUP) - 1) / u32(CARD_GUARD_GROUP), 1,
                                        1);
                    }
                    // DETECT's flags before COLLAPSE reads them; COLLAPSE's positions before the
                    // check and the builds; the counts for the host (CardSafeLog reads them late)
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute | vk::PipelineStageFlagBits2::eHost,
                                              ShaderAccess | vk::AccessFlagBits2::eHostRead);
                }
            }
            // bbport (r62d_card-uv-diag): the geometry check of what the builds below read (after
            // the pass above wrote it; it only reads the positions), and once a window the counts
            // to the host and back to 0
            if (job->geo_pipeline) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                constexpr auto ShaderAccess =
                    vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
                constexpr vk::DeviceSize geo_bytes = GeoCheckWords * 4;
                if (job->geo_clear) {
                    cmdbuf.fillBuffer(job->geo_buffer, 0, geo_bytes, 0);
                }
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderAccess);
                if (!job->geo.empty()) {
                    const vk::DescriptorBufferInfo count_info{job->geo_buffer, 0, VK_WHOLE_SIZE};
                    const std::array<vk::WriteDescriptorSet, 2> geo_writes{{
                        {.dstBinding = 0, .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &position_info},
                        {.dstBinding = 1, .descriptorCount = 1,
                         .descriptorType = vk::DescriptorType::eStorageBuffer,
                         .pBufferInfo = &count_info},
                    }};
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, job->geo_pipeline);
                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, job->geo_layout, 0,
                                                geo_writes);
                    for (const GeoCheckPush& push : job->geo) {
                        cmdbuf.pushConstants(job->geo_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                             sizeof(push), &push);
                        cmdbuf.dispatch((push.triangles + 63) / 64, 1, 1);
                    }
                }
                if (job->geo_flush) {
                    GeoCheckFlush(cmdbuf, job->geo_buffer, job->geo_readback);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                   AsBuild | vk::PipelineStageFlagBits2::eCopy,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR |
                       vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eTransferRead);
            if (!job->infos.empty()) {
                cmdbuf.buildAccelerationStructuresKHR(job->infos, job->pointers);
            }
            for (const auto& [dst, region] : job->copies) {
                cmdbuf.copyBuffer(positions, dst, region);
            }
            if (!job->copies.empty()) {
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy, vk::AccessFlagBits2::eTransferWrite,
                       Compute | vk::PipelineStageFlagBits2::eVertexShader,
                       vk::AccessFlagBits2::eShaderRead);
            }
            if (job->bottle) {
                constexpr auto Copy = vk::PipelineStageFlagBits2::eCopy;
                constexpr auto Write = vk::AccessFlagBits2::eTransferWrite;
                EffectPass::MemoryBarrier(cmdbuf, Compute | Copy,
                    vk::AccessFlagBits2::eShaderRead | Write, Copy, Write);
                cmdbuf.copyBuffer(positions, job->bottle, job->bottle_regions);
                EffectPass::MemoryBarrier(cmdbuf, Copy, Write, Compute, vk::AccessFlagBits2::eShaderRead);
                EffectPass::MemoryBarrier(cmdbuf, Copy, {}, vk::PipelineStageFlagBits2::eVertexShader | Compute, {});
            }
            if (job->probe_host) { // bbport (r64b_surface-probe-more): set only with the probe on
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost,
                                          vk::AccessFlagBits2::eHostRead);
            }
            EffectPass::MemoryBarrier(cmdbuf, AsBuild, vk::AccessFlagBits2::eAccelerationStructureWriteKHR, AsBuild,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR);
            if (job->war_barrier) { // bbport (r62d_card-uv-diag): fix A (see above)
                EffectPass::MemoryBarrier(cmdbuf, AsBuild | vk::PipelineStageFlagBits2::eCopy, {},
                                          vk::PipelineStageFlagBits2::eVertexShader | Compute, {});
            }
        });
    if (built_any) { // bbport (r47_still-check): probes alone change nothing the scene holds
        tlas_count = 0;
    }
}

bool RtShadow::SceneWanted() const {
    if (!RayTracing()) {
        return false;
    }
    const auto& s = BbSettings::Get();
    // bbport (r80_lamp-fog-shafts): and BB_LAMP_FOG_SHAFTS set with lamp fog on: the lamp fog's
    // shadow maps trace the scene (VolumetricLight::RecordShafts)
    return (LampFogShafts::Level() != LampFogShafts::Off &&
            s.effects[BbSettings::EffectPointFog].load(std::memory_order_relaxed)) ||
           SunRayTraced() || s.graphics_rt_point_shadows.load(std::memory_order_relaxed) ||
           (s.graphics_rt_bounce.load(std::memory_order_relaxed) &&
            !(s.graphics_gi_probes.load(std::memory_order_relaxed) &&
              s.effects[BbSettings::EffectGi].load(std::memory_order_relaxed)));
}

bool RtShadow::PrepareCapture() {
    if (!Wanted()) {
        return false;
    }
    RecordBuilds();
    // bbport (r62_leaf-stage3): the card layers a reader of the scene may test, filled first.
    if (card_layers) {
        card_layers->RecordFills();
    }
    return Complete() && camera_motion.PassMatrices().valid;
}

WindowPathProbe::LampSceneIdentity RtShadow::LampPhysicalScene() const noexcept {
    return {std::bit_cast<u64>(static_cast<VkAccelerationStructureKHR>(tlas)),
            reinterpret_cast<std::uintptr_t>(tlas_storage.allocation),
            tlas_guard.writes, u32(r17_tlas_records.size())};
}

bool RtShadow::LampSceneMatches(const WindowPathProbe::SceneObservation& observation,
                               VideoCore::ImageId depth, u64 uid) const noexcept {
    const auto matrices = camera_motion.PassMatrices();
    const bool clean = matrices.valid && TlasGuardOn() && !r26_freeze &&
                       r17_tlas_valid && !r17_blas_dirty;
    return observation.MatchesLamp(LampPhysicalScene(), clean, frame,
        {matrices.view, matrices.inv_view}, matrices.proj, depth, uid);
}

bool RtShadow::PrepareScene(WindowPathProbe::SceneObservation* window) {
    auto* watching = roof_probe ? roof_probe->Watch() : nullptr;
    const auto watch_scene = [&](const char* reason) {
        if (watching) {
            watching->SceneRefusal(reason);
        }
    };
    if (window_scene_active_serial) {
        window_scene_active_serial = 0;
    }
    if (!window) {
        window = window_scene_watch;
    }
    if (window && !window->lamp_witness) {
        window->Reset();
    }
    if (!need_scene || !PrepareCapture()) {
        watch_scene("natural-scene-preparation-unavailable");
        if (roof_probe) {
            roof_probe->Reject("normal scene preparation unavailable", true);
        }
        return false;
    }
    const auto camera = camera_motion.PassMatrices();
    auto* roof = roof_probe.get();
    const InteriorRoof::Camera roof_camera = (roof || window)
        ? InteriorRoof::Camera{camera.view, camera.inv_view} : InteriorRoof::Camera{};
    u64 observed_depth_uid = 0;
    if (window) {
        if (r26_freeze || !TlasGuardOn() || !camera.valid || !camera_motion.Depth() ||
            !InteriorRoof::Valid(roof_camera) || !window->textures) {
            window = nullptr;
        } else if (const auto* image = window->textures->TryGetImage(camera_motion.Depth(), 0)) {
            observed_depth_uid = image->image_uid;
        }
        if (!observed_depth_uid) {
            window = nullptr;
        }
    }
    if (roof && (!roof->Enabled() || r26_freeze || !TlasGuardOn() || !camera.valid ||
                 !camera_motion.Depth() || !InteriorRoof::Valid(roof_camera))) {
        watch_scene(r26_freeze ? "upkeep-freeze" :
                    !TlasGuardOn() ? "normal-liveness-guard-off" : "invalid-camera-or-depth");
        roof->Reject(r26_freeze ? "RT upkeep/TLAS freeze" :
                     !TlasGuardOn() ? "TLAS guard disabled, cannot attest emitted geometry" :
                     "main-camera transform unavailable or inconsistent", true);
        roof = nullptr;
    }
    const auto roof_use = [&] {
        if (roof) {
            roof->Use(tlas, roof_camera, frame, {r17_stats.tlas_built, r17_stats.tlas_updated,
                r17_stats.tlas_skipped, tlas_guard.ring_full, tlas_guard.bad_view, tlas_guard.no_address,
                tlas_live.dangling, tlas_live.moved, tlas_live.no_handle, stats.over_budget, stats.unsupported});
        }
    };
    // bbport (r121_tlas-hang-guard): a view that is not finite (every record's transform): no scene
    if (TlasGuardOn() && !TlasViewSane(camera.view)) {
        ++tlas_guard.bad_view;
        watch_scene("normal-view-guard-refused");
        if (roof) {
            roof->Reject("normal TLAS view guard refused", true);
        }
        return false;
    }
    // bbport (r14_cascade_rt): after the drawn entries, those held for cascades not drawn (none
    // when off); rebuilt too when entries moved from held to drawn or a cascade's draws arrived.
    CollectHeld();
    const u32 count = std::min<u32>(u32(frame_entries.size() + held_now.size()), MaxInstances);
    // bbport (r62_leaf-stage3): the changed card rows, before the TLAS (a first row of an entry
    // writes the TLAS again: its instance takes its slot as custom index).
    if (card_layers_on) {
        CardRows();
    }
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE with the TLAS frozen: the TLAS last built
    // is traced as it is (no records, no build; the BLAS it holds stay alive, see R26FrameEnd).
    // BLAS builds recorded since (=tlas) get the barrier the TLAS build would have given the
    // tracing. BLAS work frozen alone (=blas): the TLAS is built or refit as whenever a BLAS
    // changed (every frame today), so that only the BLAS work is left out.
    if ((r26_freeze & 2u) && r26_tlas_built) {
        if (tlas_count == 0) {
            stats.instances += count;
            ++stats.frames;
            ++r26_stats.tlas_kept;
            if ((r26_freeze & 1u) == 0) {
                scheduler.Record([](vk::CommandBuffer cmdbuf) {
                    const vk::MemoryBarrier2 after{
                        .srcStageMask = AsBuild,
                        .srcAccessMask = vk::AccessFlagBits2::eAccelerationStructureWriteKHR,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eAccelerationStructureReadKHR};
                    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
                });
            }
        }
        tlas_count = count;
        r26_tlas_kept = true;
        watch_scene("frozen-tlas-no-new-publication");
        return true;
    }
    if (r26_freeze == 1u) {
        r17_blas_dirty = true;
    }
    // bbport (r46_lamp-cards): the rule for cut-out cards, read at every scene build: with
    // experiment LampCardsOldBit set, or BB_RT_LAMP_CARDS=0, the rule of before. When it is not
    // the one the instance records were written with (the bit changed while the game runs), they
    // are written again, as for a changed mask in PrepareDraw: old and new can be compared in
    // one run.
    const bool cards_old = BbToggle::Experiment(LampCardsOldBit);
    const u32 card_level = LampCardLevel();
    if (const u32 rule = cards_old ? 0u : card_level; rule != card_rule) {
        card_rule = rule;
        tlas_count = 0;
    }
    if (count == tlas_count && (!hold_frames || (tlas_drawn == frame_entries.size() &&
                                                 tlas_cascades == frame_cascades))) {
        watch_scene("natural-scene-reuse-no-new-publication");
        if (window && window->lamp_witness &&
            LampSceneMatches(*window, camera_motion.Depth(), observed_depth_uid)) {
            window->lamp_via_earlier = true;
            window_scene_active_serial = window->scene->serial;
            UnwatchWindowScene(window);
        } else if (window) {
            window->Reset(window->lamp_witness ? WindowPathProbe::SceneStatus::EarlierPreparationUnattested
                                               : WindowPathProbe::SceneStatus::UnattestedReuse);
        }
        roof_use();
        return true;
    }
    // This may be called between ordinary draw admission and draw delivery. A
    // published ordinal is provisional until the exact direct draw is recorded.
    const bool bottle_attest = BottleObserved();
    if (bottle_attest) {
        bottle_scene_frame = ~u64{0};
    }
    u32 bottle_ordinal = MaxInstances;
    u32 bottle_mask = 0;
    BottleEndpoint bottle_endpoint;
    tlas_drawn = frame_entries.size();
    // bbport (r26_upkeep-probe): from here the TLAS is built, refit or found the same as last
    // built: it holds only entries of this frame, so it may later be traced as it is.
    r26_tlas_built = true;
    ++r26_stats.tlas_prepared;
    tlas_cascades = frame_cascades;
    const u32 slot = u32(frame % 4);
    // bbport (r121_tlas-hang-guard): a write of its own ring slot for each TLAS write of the frame (the
    // GPU reads the records when the build runs, a later write of the frame would overwrite them);
    // taken (tlas_subs) where the build is recorded below. Past the sub slots: the TLAS stays as built.
    const bool tlas_guard_on = TlasGuardOn();
    if (tlas_guard_on && !tlas_live.said) { // bbport (r121c_tlas-unbound-read)
        tlas_live.said = true;
        std::printf("Ray tracing scene guard (r121c): BB_RT_TLAS_GUARD on: an instance record is written only for an "
                    "entry whose BLAS is registered live (Entry known, address and handle as made); others are "
                    "dropped and counted by reason\n");
    }
    if (tlas_sub_frame != frame) {
        tlas_sub_frame = frame;
        tlas_subs = 0;
    }
    const u32 sub = tlas_guard_on ? tlas_subs : 0u;
    if (sub >= TlasSubSlots) {
        ++tlas_guard.ring_full;
        watch_scene("normal-ring-guard-refused");
        if (roof) {
            roof->Reject("normal TLAS ring guard refused", true);
        }
        return true;
    }
    auto* ring = static_cast<vk::AccelerationStructureInstanceKHR*>(instance_data.mapped) +
                 (u64(slot) * TlasSubSlots + sub) * MaxInstances;
    // bbport (r17_rt-upkeep): the records go to a CPU list first, to compare with the last TLAS's
    const bool upkeep = UpkeepOn();
    if (upkeep) {
        r17_records.resize(count);
    }
    auto* out = upkeep ? r17_records.data() : ring;
    u64 triangles = 0;
    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
    u32 placed_old_pose = 0; // bbport (r47b_casters)
    // bbport (r47c_review-fixes): held moving props known by an address that keep the lamp bit,
    // and whether a moving prop of a mesh known by an address is drawn this frame (their mesh
    // keys are listed when the first held one asks; most frames none does).
    u32 placed_held = 0;
    bool placed_listed = false;
    const auto placed_twin = [&](u64 base) {
        if (!placed_listed) {
            placed_listed = true;
            placed_drawn.clear();
            for (const Entry* e : frame_entries) {
                if (e->instance && e->palette_placed && e->dynamic) {
                    placed_drawn.push_back(e->base);
                }
            }
            std::ranges::sort(placed_drawn);
        }
        return std::ranges::binary_search(placed_drawn, base);
    };
    // bbport (r41_lamp-shadows, r42_lamp-soft): with BB_LAMP_SHADOW_STALE=1 only
    const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
    card_stats = {}; // bbport (r46_lamp-cards): of the records written now
    const u32 lamp_leave = LampLeave(); // bbport (r47_still-check)
    still_leave_count = 0;
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1, the layers on, and a lamp pass that can bind a
    // CARDS build within CardLampHoldFrames (NoteCardLampUser): the cards may take CardLampMask
    const bool card_lamps = card_layers_on && CardLampsWanted() && card_lamp_user_seen &&
                            frame - card_lamp_user_frame <= CardLampHoldFrames;
    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT: the knob now; true: the entries a registry hit marked get glass records
    const bool glass_rec_on = glass_light_mode != 0 && GlassLightFrame(card_lamps);
    if (glass_light_mode != 0) {
        GlassForwardFrame(); // bbport (r130g_glass-light-forward): its lines come right after r130c's
    }
    card_safe_now = {}; // bbport (r62e_leaf-cards-usable): of the records written now
    // bbport (r62n_cutout-skinned-blocker) FEATURE: which lone skinned cut-out cards may cast lamp shadows (BB_RT_CARD_LAMP_SKINNED: 0 only a
    // few-bones one, 1 every one, 2 none); only asked while the lamp rays read the cards
    card_skinned_now = {};
    const CardSkinnedMode skinned_mode = card_lamps ? CardSkinnedModeNow() : CardSkinnedMode::All;
    const u32 skinned_bones = card_lamps ? CardSkinnedBonesNow() : CardSkinnedBonesDefault;
    u32 glass_records = 0, glass_records_carried = 0; // bbport (r86_glass-light-stage2a)
    // bbport (r84_live-test-knobs): BB_VOLUMETRIC_GATE_PROBE may change through the live knobs file;
    // off again: the table is emptied once, so that a probe coming back never reads older ids
    gate_table_on = VolumetricOcclusion::GateProbe();
    if (!gate_table_on && !gate_table.empty()) {
        gate_table.clear();
    }
    if (gate_table_on) { // bbport (r76_sun-fog-outdoors): GateTable, with the records below
        gate_table.clear();
        gate_caps.clear(); // bbport (r76c_sun-fog-shells): GateCaptures, beside it
    }
    std::shared_ptr<InteriorRoof::Scene> roof_next;
    if (window) {
        window->Reset();
        constexpr u32 AttemptsMost = 2;
        if (++window->attempts > AttemptsMost ||
            frame_entries.size() + held_now.size() > MaxInstances) {
            window->status = WindowPathProbe::SceneStatus::Budget;
            if (window_scene_watch == window) {
                window_scene_watch = nullptr;
            }
            window = nullptr;
        } else {
            try {
                window->facts.reserve(count);
                if (!roof) {
                    roof_next = std::make_shared<InteriorRoof::Scene>();
                    roof_next->records.reserve(count);
                }
            } catch (const std::bad_alloc&) {
                roof_next.reset();
                window->status = WindowPathProbe::SceneStatus::Budget;
                if (window_scene_watch == window) {
                    window_scene_watch = nullptr;
                }
                window = nullptr;
            }
        }
    }
    if (roof || window) {
        static_assert(InteriorRoof::MaxRecords == MaxInstances);
        if (roof) {
            roof_next = std::make_shared<InteriorRoof::Scene>();
            roof_next->records.reserve(count);
        }
        roof_next->camera = roof_camera;
        roof_next->tlas_view = XXH3_64bits(camera.view.data(), sizeof(camera.view));
        roof_next->frame = frame;
        roof_next->requested = u32(frame_entries.size() + held_now.size());
        roof_next->flags = u32(RtGlassOn()) | (u32(glass_rec_on) << 1) | (u32(card_lamps) << 2) |
                           (u32(card_layers_on) << 3) | (u32(gate_shell_rule.on) << 4) |
                           (u32(glass_clear_now) << 5) | (u32(tlas_guard_on) << 6);
    }
    for (u32 i = 0; i < count; ++i) {
        // bbport (r14_cascade_rt): a held entry, or a held one drawn only by the camera pass while
        // its cascades are not drawn, keeps casting the sun's shadow (rt_shadow.comp's ray mask 1).
        // Not held (dropped: its cascade drew without it): the camera pass's mask only, as before.
        const bool kept = i >= frame_entries.size();
        Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];
        // bbport (r121c_tlas-unbound-read): an Entry* that is not a live entry is never dereferenced (a dangling
        // pointer would hand the build whatever the freed object held as a BLAS address)
        const auto live_entry = tlas_guard_on ? entry_live.find(entry) : entry_live.end();
        if (tlas_guard_on) {
            ++tlas_live.checked;
            if (live_entry == entry_live.end()) {
                ++tlas_live.dangling;
                if (watching) {
                    watching->UnassignedGuard();
                }
                continue;
            }
        }
        if (!entry->blas) {
            if (auto* row = RoofWatchEntry(*entry)) {
                ++row->now.scanned;
                row->now.emit_why = "selected-without-blas";
            }
            continue;
        }
        // bbport (r121_tlas-hang-guard): an entry whose BLAS was never made has no address to point at
        if (tlas_guard_on && entry->address == 0) {
            ++tlas_guard.no_address;
            if (watching) {
                watching->UnassignedGuard();
            }
            continue;
        }
        // bbport (r121c_tlas-unbound-read): the address is the one the BLAS was made with, and its handle is there
        if (tlas_guard_on) {
            if (live_entry->second != entry->address) {
                ++tlas_live.moved;
                if (watching) {
                    watching->UnassignedGuard();
                }
                continue;
            }
            if (!entry->handle) {
                ++tlas_live.no_handle;
                if (watching) {
                    watching->UnassignedGuard();
                }
                continue;
            }
        }
        if (watching && tlas_guard_on) {
            if (auto* row = watching->Exact(entry->base, entry->mesh)) {
                ++row->now.scanned;
                row->Cache(entry->address, roof_probe->Geometry(entry->address), entry->r17_capture_frame,
                           "guarded-cache");
            }
        }
        // bbport (r46_lamp-cards): an entry no camera pass draw of its own showed as a cut-out
        // (a sun cascade's copy, a prop drawn there under another bone palette, a card whose
        // camera pass draw is not in the scene) is one when the camera pass draws its mesh with
        // a discarding shader. Looked up here and not at its draw: a sun cascade draws its copy
        // before the camera pass makes the mesh known, and the copy would cast its whole-polygon
        // shadow for a frame. One lookup an entry each time a cut-out new to the sets was drawn.
        if (!entry->card_camera && !entry->card_mesh && entry->card_gen != cutout_gen) {
            entry->card_gen = cutout_gen;
            entry->card_mesh =
                cutout_meshes.contains(entry->mesh) || cutout_keys.contains(entry->base);
            ++card_lookups;
        }
        // bbport (r46_lamp-cards): a cut-out card by any draw of it, whatever the order of the
        // passes and whether or not it counts as moving (rt_lamp_cards.h). cards_old: the rule
        // of before, shadow_card && !dynamic.
        const bool cutout = entry->card_camera || entry->card_mesh;
        // bbport (r46b_plant-rule): what a skinned cut-out's vertices are taken for (a plant
        // when no sun shadow pass draws them: lone), looked up when the map's verdicts changed
        if (entry->skinned && entry->lone_gen != lone_gen && (cutout || entry->card_shadow)) {
            entry->lone_gen = lone_gen;
            const auto known = lone_streams.find(entry->stream);
            entry->lone = entry->stream != 0 && known != lone_streams.end()
                              ? LampLoneOf(known->second)
                              : LampLoneState::None;
        }
        const bool lone = entry->lone == LampLoneState::Lone;
        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,
                                   entry->card_shadow, cutout, entry->skinned, lone);
        // bbport (r50_leaf-stage1): with BB_RT_CARD_ALPHA_LOG=1, the pixel shaders of the
        // cut-outs by the class this rule gives them (each entry once a class)
        if ((entry->cut_camera_ps | entry->cut_sun_ps) != 0 &&
            Shader::Optimization::CutoutLogOn()) { // (r54)
            using CardClass = Shader::Optimization::CutoutCardClass;
            const CardClass card_class = card ? (!entry->skinned ? CardClass::Static
                                                 : lone            ? CardClass::Plant
                                                                   : CardClass::SkinnedOut)
                                              : entry->skinned ? CardClass::SkinnedKept
                                                               : CardClass::OtherKept;
            const u8 bit = u8(1u << u32(card_class));
            if ((entry->cut_noted & bit) == 0) {
                entry->cut_noted |= bit;
                Shader::Optimization::NoteCutoutCard(entry->cut_camera_ps, entry->cut_sun_ps,
                                                     card_class);
            }
        }
        // bbport (r86_glass-light-stage2a): a window pane carried from the frame before
        // (CollectHeld, BB_RT_GLASS_LIGHT) is not held for the sun: its own mask, RtGlassMask
        const u8 mask =
            kept && !RtGlassEntry(entry->mask)
                ? ShadowMask
                : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
        // For the 600-frame line: what is left out and by which sign, and what each rule would
        // leave out of these same instances (the route by which a card kept its lamp bit).
        if (card) {
            ++card_stats.out;
            card_stats.by_shadow += entry->card_shadow ? 1 : 0;
            card_stats.by_camera += entry->card_camera ? 1 : 0;
            card_stats.by_mesh += entry->card_mesh && !entry->card_camera ? 1 : 0;
            card_stats.with_palette += entry->palette != 0 ? 1 : 0;
            card_stats.camera_only += (mask & ShadowMask) == 0 ? 1 : 0;
            card_stats.moving += entry->dynamic ? 1 : 0;
            card_stats.skinned_out += entry->skinned ? 1 : 0;
            // The four with the most triangles, each mesh once: a caster that is no plant (a
            // weapon, a fence, a prop whose shader discards for a fade) is named in the line.
            if (std::ranges::none_of(card_stats.largest, [&](const CardFound& c) {
                    return c.triangles != 0 && c.key == entry->base;
                })) {
                CardFound found{entry->mesh,
                                entry->base,
                                entry->triangles,
                                entry->card_shadow,
                                entry->card_camera,
                                entry->card_mesh,
                                entry->palette != 0,
                                entry->instance,
                                entry->dynamic,
                                (mask & ShadowMask) == 0,
                                entry->skinned,
                                entry->lone};
                for (CardFound& slot : card_stats.largest) {
                    if (found.triangles > slot.triangles) {
                        std::swap(slot, found);
                    }
                }
            }
        } else if ((entry->card_shadow || cutout) && entry->skinned) {
            ++card_stats.skinned_kept;
            card_stats.sun_drawn += entry->lone == LampLoneState::Sun ? 1 : 0;
            card_stats.lone_waiting += entry->lone == LampLoneState::Waiting ? 1 : 0;
        }
        for (u32 level = 0; level < card_stats.rule_out.size(); ++level) {
            card_stats.rule_out[level] +=
                LampCard(false, level, entry->shadow_card, entry->dynamic, entry->card_shadow,
                         cutout, entry->skinned, lone)
                    ? 1
                    : 0;
        }
        // bbport (r41_lamp-shadows): a moving shared copy in an old pose casts no lamp shadow
        // (Entry::lamp_out, kept by PrepareDraw; a changed mask makes the TLAS a full build,
        // not a refit).
        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
        // bbport (r47b_casters): a moving prop known by its palette's address, not drawn this
        // frame and held for a sun cascade that was not drawn (r14): its pose is an earlier
        // frame's. Where the game keeps a moving object's palette at two addresses in turn (the
        // carried torch) this is the object's other entry one frame after a far cascade drew it,
        // beside the entry drawn now: it keeps the sun's ray mask as every held caster does, and
        // casts no lamp shadow (the lamp sits at the torch's tip, a copy of the torch a step
        // behind would shade it). Such entries only exist with experiment StillCheckOldBit
        // clear.
        // bbport (r47c_review-fixes): only while another moving prop of its mesh known by an
        // address IS drawn this frame (the object's other entry, in today's pose). A mover with
        // one address that only a far cascade draws (out of the camera's view: held 7 frames of
        // 8 with graphics_sun_far_shadows=rare) keeps the lamp bit as before r47b; without it
        // its lamp shadow would show one frame in 8.
        const bool held_pose = kept && entry->instance && entry->palette_placed && entry->dynamic;
        const bool old_pose = held_pose && placed_twin(entry->base);
        placed_old_pose += old_pose ? 1 : 0;
        placed_held += held_pose && !old_pose ? 1 : 0;
        // bbport (r47_still-check): BB_RT_LAMP_LEAVE (a diagnostic, off unless set): lamp rays
        // leave out the instances of the classes it names
        const bool leave =
            lamp_leave != 0 &&
            (lamp_leave &
             StillLeaveClasses((mask & CameraMask) != 0, kept, entry->rebuilt, entry->instance,
                               entry->dynamic,
                               LampCard(false, LampCardLevelDefault, entry->shadow_card,
                                        entry->dynamic, entry->card_shadow, cutout,
                                        entry->skinned, lone))) != 0;
        // Counted where the knob alone withholds the lamp bit (not a card or a starved copy
        // that is left out anyway).
        still_leave_count += leave && !card && !stale ? 1 : 0;
        // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: a card that today has no lamp bit, a plant or
        // a static cut-out (characters, hair and cloth are stage 5), whose row has data: the lamp
        // rays test its texels (CardLampMask, FORCE_NO_OPAQUE). A copy in an old pose, a stale one
        // or one BB_RT_LAMP_LEAVE leaves out stays out. Off: the record of before, byte for byte.
        // (Moving rigid cut-outs are taken too, counted apart in the r63 line: whether to leave
        // them out is decided after the game test. `dynamic` alone would also leave out the
        // plants, which are skinned and lone, and so dynamic.)
        // bbport (r83_glass-water-stage1): a window pane (RtGlassMask) is never a lamp card
        // bbport (r62e_leaf-cards-usable): only a still cut-out (CardStillFor: no moving rigid one,
        // a skinned one only when lone); a stale copy never, and the bit stays off
        // CardLampHoldFrames after its last stale record (no flip at each turn of a shared copy);
        // BB_RT_CARD_SAFE=0: !stale as r63
        // bbport (r62n_cutout-skinned-blocker) FEATURE: a lone skinned cut-out (r46b's plant sign) the rule judges (rt_card_skinned.h)
        const bool skinned_judged = card_lamps && card && entry->skinned && lone;
        const bool skinned_ok =
            !skinned_judged || CardSkinnedLampOk(skinned_mode, entry->skeleton_bones, skinned_bones);
        if (skinned_judged) {
            card_skinned_now.Note(skinned_ok, entry->skeleton_bones);
        }
        const bool lamp_card = card_lamps && card && !leave && !old_pose && mask != 0 &&
                               !RtGlassEntry(mask) && CardStillFor(*entry, stale) &&
                               (!entry->skinned || (lone && skinned_ok)) && CardLampOn(*entry);
        lamp_cards += lamp_card ? 1 : 0;
        lamp_plants += lamp_card && entry->skinned ? 1 : 0;
        lamp_moving += lamp_card && !entry->skinned && entry->dynamic ? 1 : 0;
        if (entry->card_uv && entry->card_uv->lamp_written != lamp_card) { // every change of the
            ++lamp_flips;                                                   // bit, whatever its cause
            ++(CardMaskTurn(entry->card_uv->lamp_once) ? card_safe.flips : card_safe.first_on); // (r62e)
            entry->card_uv->lamp_written = lamp_card;
        }
        // bbport (r130c_glass-lamp-light): a transmitting registry entry's record (never a cut-out card, a stale copy, an old pose
        // or one BB_RT_LAMP_LEAVE leaves out: their lamp bit is withheld already). Off: glass_rec_on and entry->glass_light are 0.
        const bool glass_rec = glass_rec_on && entry->glass_light != 0 && mask != 0 && !card && !stale && !leave && !old_pose;
        if (entry->glass_light != 0 && glass_light_now && !glass_rec_on) {
            ++glass_counts.kept_cards; // the lamp cards are on: the record stays as before
        }
        vk::AccelerationStructureInstanceKHR record{
            // bbport (r62_leaf-stage3); a glass record's index is its registry entry (bbport r130c_glass-lamp-light)
            .instanceCustomIndex = glass_rec ? GlassLight::CustomIndex(u8(entry->glass_light - 1u)) : CardCustomIndex(*entry),
            // bbport (r83_glass-water-stage1): a window pane's record: RtGlassMask alone
            .mask = RtGlassRecordMask(mask, u8(mask | (card || stale || leave || old_pose ? 0 : LampMask) |
                                               (lamp_card ? CardLampMask : 0))), // bbport (r63_leaf-stage4)
            .flags = u8(lamp_card ? u32(VK_GEOMETRY_INSTANCE_FORCE_NO_OPAQUE_BIT_KHR) : 0u),
            .accelerationStructureReference = entry->address,
        };
        std::memcpy(&record.transform, camera.view.data(), sizeof(camera.view));
        // bbport (r76c_sun-fog-shells): BB_VOLUMETRIC_GATE_SHELLS (test only, read once). At the
        // scene's first record: the line every 600 scenes (the last scene's shells), or once that
        // the text was not understood. While on, every record the sun gate may hit gets its gate
        // bits (GateSolidBits: 0x20 with the sun's 1, 0x40 with the camera pass's 2) unless the rule
        // takes its entry's last draw for a shell; the gate traces those bits alone (GateRayMask),
        // and every other ray sees the records as without the rule. Not set: nothing here.
        if (built == 0 && (gate_shell_rule.on || gate_shell_rule.bad)) {
            if (gate_shell_rule.bad && !gate_shell_bad_said) {
                gate_shell_bad_said = true;
                std::printf("Volumetric lighting (r76c): BB_VOLUMETRIC_GATE_SHELLS not understood "
                            "(tests: far, notest, nocull, <vs hex>:<ps hex>, <vs hex>:*, separated "
                            "by , or +, at most %u pairs): no shells left out\n",
                            VolumetricOcclusion::GateShellPairsMost);
            }
            if (gate_shell_rule.on && gate_shell_scenes++ % 600 == 1) {
                std::printf("Volumetric lighting (r76c): gate shells (BB_VOLUMETRIC_GATE_SHELLS%s%s%s, "
                            "%u pairs): %u of %u records the gate may hit were left out of its rays "
                            "in the last scene (%u of them sun casters); the gate traces mask bits "
                            "0x20 and 0x40\n",
                            gate_shell_rule.far_depth ? " far" : "",
                            gate_shell_rule.no_test ? " notest" : "",
                            gate_shell_rule.no_cull ? " nocull" : "", gate_shell_rule.pairs,
                            gate_shells_now, gate_shell_records, gate_shells_sun);
            }
            gate_shells_now = gate_shells_sun = gate_shell_records = 0;
        }
        if (gate_shell_rule.on) {
            const u32 bits = record.mask;
            const bool shell =
                (bits & 3u) != 0 && VolumetricOcclusion::GateShell(gate_shell_rule, entry->gate_cap);
            record.mask = u8(bits | VolumetricOcclusion::GateSolidBits(bits, shell));
            gate_shell_records += (bits & 3u) != 0 ? 1 : 0;
            gate_shells_now += shell ? 1 : 0;
            gate_shells_sun += shell && (bits & 1u) != 0 ? 1 : 0;
        }
        // bbport (r130c_glass-lamp-light): the glass record drops the lamp bits and takes RtGlassMask (a pane has it alone already:
        // glass_gain only where the mask changes, for the pane counts below)
        const bool glass_gain = glass_rec && !RtGlassEntry(mask);
        if (glass_rec) {
            record.mask = u8((u32(record.mask) & ~u32(LampMask | CardLampMask)) | RtGlassMask);
            ++glass_light_records_now;
            ++glass_counts.records;
        }
        // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on (glass_clear_now, set by the rasterizer each frame): the glass record of
        // a clearing kind (the cabinet's pane) takes RtGlassMask alone: the sun, moon and camera rays pass it (they do not read
        // GLASS_INDEX_BIT); the lamp glass query still finds it for its tint. Off: false, nothing here changes.
        if (glass_rec && glass_clear_now &&
            GlassRegistryRules::Clears(GlassRegistryRules::Load().entries[(entry->glass_light - 1u) % GlassRegistryRules::MaxEntries].kind)) {
            record.mask = RtGlassMask;
            ++glass_clear_records;
        }
        if (bottle_attest && entry == bottle_entry && !kept && !stale && !old_pose && entry->built &&
            record.accelerationStructureReference == bottle_entry_address && (record.mask & CameraMask) != 0 && !card) {
            const bool warm = entry->address == bottle_resident_address && entry->r17_capture_frame == bottle_resident_capture &&
                              (bottle_resident_capture == frame || (!entry->rebuilt && !entry->dynamic));
            const bool cold = BottleColdEligible(*entry) &&
                              (record.flags & VK_GEOMETRY_INSTANCE_FORCE_OPAQUE_BIT_KHR) == 0;
            if (warm || cold) {
                bottle_ordinal = bottle_ordinal == MaxInstances ? built : MaxInstances + 1;
                bottle_mask = record.mask;
                bottle_endpoint = BottleGeneration(*entry);
            }
        }
        out[built++] = record;
        if (roof_next) {
            if ((record.flags & VK_GEOMETRY_INSTANCE_FORCE_OPAQUE_BIT_KHR) != 0) {
                if (roof) {
                    watch_scene("roof-observation-force-opaque");
                    roof->Reject("force-opaque instance prevents candidate traversal", true);
                    roof = nullptr;
                }
                roof_next.reset();
            } else {
                const u32 flags = InteriorRoof::Flags(record.mask,
                    RtGlassEntry(record.mask) || entry->glass_light != 0,
                    lamp_card || entry->shadow_card || entry->card_shadow || cutout,
                    entry->skinned || entry->skeleton_bones != 0,
                    entry->dynamic || entry->still_moved || entry->still_seen || entry->still_doubt,
                    entry->palette != 0 || entry->palette_placed);
                const InteriorRoof::Record evidence{
                    .key = entry->base,
                    .mesh = entry->mesh,
                    .capture_frame = entry->r17_capture_frame,
                    .flags = flags,
                    .held = kept,
                    .palette_nonzero = entry->palette != 0,
                    .palette_placed = entry->palette_placed,
                    .geometry = roof ? roof->Geometry(entry->address) : InteriorRoof::GeometryRevision{},
                    .captured_inputs = entry->r17_inputs,
                };
                if (!InteriorRoof::Append(*roof_next, built - 1, evidence)) {
                    if (roof) {
                        watch_scene("roof-observation-emission-order-mismatch");
                    roof->Reject("emitted instance order differs from sidecar", true);
                        roof = nullptr;
                    }
                    roof_next.reset();
                } else if (window) {
                    window->facts.push_back({
                        .key = evidence.key,
                        .capture_frame = evidence.capture_frame,
                        .triangles = entry->triangles,
                        .custom_index = record.instanceCustomIndex,
                    });
                }
            }
        }
        glass_fwd.carried += glass_rec && kept ? 1u : 0u; // bbport (r130g_glass-light-forward): a glass record of a carried pane
        // bbport (r86_glass-light-stage2a): the pane records (Record asks them only while one is
        // in)
        if (!glass_gain && RtGlassEntry(static_cast<u8>(record.mask))) {
            ++glass_records;
            glass_records_carried += kept ? 1 : 0;
        }
        if (gate_table_on) { // bbport (r76_sun-fog-outdoors): instance id built - 1
            gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});
            gate_caps.push_back(entry->gate_cap); // bbport (r76c_sun-fog-shells)
            gate_caps.back().moving = entry->dynamic;
        }
        triangles += entry->triangles;
    }
    // bbport (r63_leaf-stage4): what the TLAS of these records holds (PointShadow binds its CARDS
    // build only while it holds a card with CardLampMask)
    card_lamp_instances = lamp_cards;
    glass_instances = glass_records; // bbport (r86_glass-light-stage2a)
    glass_frame = frame;             // bbport (r86b_glass-visible): GlassScene
    glass_view = camera.view;
    glass_carried = glass_records_carried;
    card_lamp_plants = lamp_plants;
    card_lamp_moving = lamp_moving;
    card_lamp_counts.records += lamp_cards;
    card_lamp_counts.flips += lamp_flips;
    card_lamp_counts.flip_writes += lamp_flips != 0 ? 1 : 0;
    ++card_lamp_counts.writes;
    if (tlas_count == 0) {
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
        still_stats.placed_held += placed_held;         // bbport (r47c_review-fixes)
        stats.instances += count;
        stats.triangles += triangles;
        ++stats.frames;
    }
    const auto publish_bottle = [&] {
        if (bottle_ordinal < built && tlas_guard_on && !r26_freeze) {
            bottle_scene_frame = frame;
            bottle_scene_ordinal = bottle_ordinal;
            bottle_scene_mask = bottle_mask;
            bottle_scene_view = camera.view;
            bottle_scene_endpoint = bottle_endpoint;
        }
    };
    const auto publish_window = [&](WindowPathProbe::LampSceneSource source) {
        if (!window || !roof_next || !built || window->facts.size() != built ||
            roof_next->records.size() != built) {
            return;
        }
        if (window->lamp_witness) {
            const auto physical = LampPhysicalScene();
            if (!r17_tlas_valid || r17_blas_dirty || !physical.Valid() || physical.emitted != built) {
                return;
            }
            window->lamp_identity = physical;
            window->lamp_source = source;
        }
        window->scene = roof_next;
        window->projection = camera.proj;
        window->depth = camera_motion.Depth();
        window->depth_uid = observed_depth_uid;
        window->status = WindowPathProbe::SceneStatus::Ready;
        window_scene_active_serial = roof_next->serial;
        UnwatchWindowScene(window);
    };
    tlas_count = count;
    // bbport (r17_rt-upkeep): nothing changed since the TLAS was last built or refit (no BLAS
    // build or refit recorded since, the same records byte for byte): it is left as it is. Only
    // transforms and BLAS contents changed (same references, masks, flags and count): refit.
    auto tlas_mode = vk::BuildAccelerationStructureModeKHR::eBuild;
    vk::BuildAccelerationStructureFlagsKHR tlas_flags =
        vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace;
    if (upkeep) {
        constexpr std::size_t Transform = sizeof(vk::TransformMatrixKHR);
        constexpr std::size_t Record = sizeof(vk::AccelerationStructureInstanceKHR);
        bool same_refs = r17_tlas_valid && r17_tlas_records.size() == built;
        bool same_all = same_refs;
        for (u32 i = 0; same_refs && i < built; ++i) {
            const auto* a = reinterpret_cast<const char*>(&r17_records[i]);
            const auto* b = reinterpret_cast<const char*>(&r17_tlas_records[i]);
            same_refs = std::memcmp(a + Transform, b + Transform, Record - Transform) == 0;
            same_all = same_refs && same_all && std::memcmp(a, b, Transform) == 0;
        }
        // bbport (r121_tlas-hang-guard): a later write of the frame with other references, masks, flags
        // or count than the write before it (the case that read the first build's records wrongly)
        tlas_guard.later_differ += sub > 0 && !same_refs && !(same_all && !r17_blas_dirty) ? 1 : 0;
        if (same_all && !r17_blas_dirty) {
            ++r17_stats.tlas_skipped;
            watch_scene("bytewise-normal-reuse-no-new-publication");
            if (window && window->lamp_witness && roof_next && built) {
                // The normal comparison just matched every ordered instance byte, and no BLAS
                // build, refit or referenced retirement intervened. Keep the physical write ID.
                roof_next->serial = ++observed_scene_serial;
                roof_next->ms = InteriorRoof::Now();
                publish_window(WindowPathProbe::LampSceneSource::ExactBytewise);
            }
            if (window && window->status != WindowPathProbe::SceneStatus::Ready) {
                window->Reset(window->lamp_witness ? WindowPathProbe::SceneStatus::BytewiseReuseUnattested
                                                   : WindowPathProbe::SceneStatus::UnattestedReuse);
            }
            publish_bottle(); // the matching current record occupies the same ordinal
            roof_use(); // unchanged TLAS retains its original matching table
            return true;
        }
        tlas_flags |= vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate;
        if (same_refs && built > 0 && r17_tlas_age < TlasRefitsBetweenBuilds) {
            tlas_mode = vk::BuildAccelerationStructureModeKHR::eUpdate;
            ++r17_tlas_age;
            ++r17_stats.tlas_updated;
        } else {
            r17_tlas_age = 0;
            ++r17_stats.tlas_built;
            if (BbSpike::on) { // bbport (r23_spike-trace)
                BbSpike::tlas_builds.fetch_add(1, std::memory_order_relaxed);
            }
        }
        std::memcpy(ring, r17_records.data(), std::size_t(built) * Record);
        r17_tlas_records.assign(r17_records.begin(), r17_records.begin() + built);
        r17_tlas_valid = true;
    } else {
        r17_tlas_valid = false;
        ++r17_stats.tlas_built;
    }
    r17_blas_dirty = false;
    slot_ticks[slot] = scheduler.CurrentTick();
    ++tlas_subs; // bbport (r121_tlas-hang-guard): the sub slot is taken
    ++tlas_guard.writes;
    tlas_guard.later_writes += sub > 0 ? 1 : 0;
    const u64 instances_address =
        instance_data.address + (u64(slot) * TlasSubSlots + sub) * MaxInstances *
                                    sizeof(vk::AccelerationStructureInstanceKHR);
    EffectPass::Mark(17, "ray tracing scene"); // bbport: as in RecordBuilds
    scheduler.RecordCrumb(
        {.name = "Ray tracing scene"},
        [count = built, instances_address, tlas = tlas, tlas_mode, tlas_flags, // r17_rt-upkeep
         tlas_scratch = tlas_scratch.address](vk::CommandBuffer cmdbuf) {
            const vk::AccelerationStructureGeometryKHR geometry{
                .geometryType = vk::GeometryTypeKHR::eInstances,
                .geometry = {.instances = vk::AccelerationStructureGeometryInstancesDataKHR{
                    .data = {.deviceAddress = instances_address}}},
                .flags = vk::GeometryFlagBitsKHR::eOpaque,
            };
            const vk::AccelerationStructureBuildGeometryInfoKHR info{
                .type = vk::AccelerationStructureTypeKHR::eTopLevel,
                .flags = tlas_flags, // bbport (r17_rt-upkeep): eAllowUpdate unless experiment set
                .mode = tlas_mode,
                .srcAccelerationStructure = tlas_mode == vk::BuildAccelerationStructureModeKHR::eUpdate
                                                ? tlas
                                                : vk::AccelerationStructureKHR{},
                .dstAccelerationStructure = tlas,
                .geometryCount = 1,
                .pGeometries = &geometry,
                .scratchData = {.deviceAddress = tlas_scratch},
            };
            const vk::AccelerationStructureBuildRangeInfoKHR range{.primitiveCount = count};
            const vk::AccelerationStructureBuildRangeInfoKHR* range_pointer = &range;
            const vk::MemoryBarrier2 before{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = AsBuild,
                .dstAccessMask = vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                                 vk::AccessFlagBits2::eAccelerationStructureWriteKHR};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            cmdbuf.buildAccelerationStructuresKHR(info, range_pointer);
            const vk::MemoryBarrier2 after{.srcStageMask = AsBuild,
                                           .srcAccessMask =
                                               vk::AccessFlagBits2::eAccelerationStructureWriteKHR,
                                           .dstStageMask = Compute,
                                           .dstAccessMask =
                                               vk::AccessFlagBits2::eAccelerationStructureReadKHR};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        });
    publish_bottle();
    if (roof_next && roof_next->records.size() == built) {
        if (built) {
            roof_next->serial = ++observed_scene_serial;
            roof_next->ms = InteriorRoof::Now();
            publish_window(WindowPathProbe::LampSceneSource::NativeWrite);
        }
        if (roof) {
            roof->Publish(std::move(roof_next));
            roof_use(); // the ordinary AS-build-to-compute dependency is already recorded
        }
    } else if (roof) {
        watch_scene("roof-observation-emitted-count-mismatch");
        roof->Reject("emitted count and diagnostic metadata differ", true);
    }
    if (window && window->status != WindowPathProbe::SceneStatus::Ready) {
        window->Reset();
    }
    return true;
}

bool RtShadow::MakeRaw(u32 width, u32 height) {
    if (raw_image && raw_width == width && raw_height == height) {
        return true;
    }
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    if (raw_image) {
        scheduler.DeferOperation([device, allocator, image = raw_image, memory = raw_allocation,
                                  view = raw_view] {
            device.destroyImageView(view);
            vmaDestroyImage(allocator, image, memory);
        });
        raw_image = vk::Image{};
        raw_view = vk::ImageView{};
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(allocator, &image_ci, &alloc_ci, &raw, &raw_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    raw_image = raw;
    const auto [result, view] = device.createImageView({
        .image = raw_image,
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8Unorm,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    raw_view = view;
    raw_width = width;
    raw_height = height;
    return true;
}

// bbport (r131a_foliage-translucency): the sun trace's hue image (rt_shadow.comp FOLIAGE builds, binding 11): RGBA8 at the trace's size, made (and
// made again when the size changes) only with the light through leaves on for the sun. Each trace clears it before it writes.
bool RtShadow::MakeSunHue(u32 width, u32 height) {
    if (sun_hue_image && sun_hue_width == width && sun_hue_height == height) {
        return true;
    }
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    if (sun_hue_image) {
        scheduler.DeferOperation([device, allocator, image = sun_hue_image, memory = sun_hue_allocation, view = sun_hue_view] {
            device.destroyImageView(view);
            vmaDestroyImage(allocator, image, memory);
        });
        sun_hue_image = vk::Image{};
        sun_hue_view = vk::ImageView{};
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(allocator, &image_ci, &alloc_ci, &raw, &sun_hue_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    sun_hue_image = raw;
    const auto [result, view] = device.createImageView({
        .image = sun_hue_image,
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8G8B8A8Unorm,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    sun_hue_view = view;
    sun_hue_width = width;
    sun_hue_height = height;
    return true;
}

bool RtShadow::Record(const Inputs& in) {
    if (!(need_scene ? PrepareScene() : PrepareCapture()) || !MakeRaw(in.width, in.height)) {
        return false;
    }
    if (!need_scene) {
        stats.instances += frame_entries.size();
        ++stats.frames;
    }
    bool use_vsm = false;
    if (BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed)) {
        if (!vsm_tried) {
            vsm_tried = true;
            vsm = std::make_unique<SunVsm>(instance, scheduler);
        }
        const auto camera = camera_motion.PassMatrices();
        if (vsm && vsm->Ready() && camera.valid) {
            auto& casters = vsm_casters;
            casters.clear();
            casters.reserve(frame_entries.size());
            // bbport (r14_cascade_rt): entries held for cascades not drawn this frame are casters
            // as if drawn (moving ones in their last pose), not kept casters to verify or cull.
            CollectHeld();
            for (std::size_t i = 0; i < frame_entries.size() + held_now.size(); ++i) {
                Entry* entry = i < frame_entries.size() ? frame_entries[i]
                                                        : held_now[i - frame_entries.size()];
                if (entry->shadow && entry->world.buffer && entry->copied) {
                    if (const auto* box = vsm->Box(entry->world.address)) {
                        entry->box = *box;
                        entry->has_box = true;
                    }
                    casters.push_back({entry->world.address, entry->indices.address,
                                       entry->triangles, entry->dynamic,
                                       entry->copied_at > vsm_copies});
                }
            }
            // A caster the game draws now in nearly the same place as a kept one has replaced it
            // (a swapped level of detail): their boxes overlap by half of their union or more.
            const auto replaced = [&](const std::array<float, 6>& box) {
                constexpr float Pad = 5e-4f;
                float volume = 1.0f;
                for (int k = 0; k < 3; ++k) {
                    volume *= box[k + 3] - box[k] + 2.0f * Pad;
                }
                for (std::size_t i = 0; i < frame_entries.size() + held_now.size(); ++i) {
                    const Entry* drawn = i < frame_entries.size()
                                             ? frame_entries[i]
                                             : held_now[i - frame_entries.size()]; // r14
                    if (!drawn->shadow || !drawn->has_box) {
                        continue;
                    }
                    float overlap = 1.0f, other = 1.0f;
                    for (int k = 0; k < 3; ++k) {
                        const float span = std::min(box[k + 3], drawn->box[k + 3]) -
                                           std::max(box[k], drawn->box[k]) + 2.0f * Pad;
                        if (span <= 0.0f) {
                            overlap = 0.0f;
                            break;
                        }
                        overlap *= span;
                        other *= drawn->box[k + 3] - drawn->box[k] + 2.0f * Pad;
                    }
                    if (overlap > 0.0f && overlap * 3.0f >= volume + other) {
                        return true;
                    }
                }
                return false;
            };
            const std::array<float, 2> camera_proj{camera.proj[0], camera.proj[1]};
            if (!cull_serial || cull_view != camera.view || cull_inv_view != camera.inv_view ||
                cull_proj != camera_proj ||
                cull_drawn != frame_entries.size() + held_now.size()) {
                cull_view = camera.view;
                cull_inv_view = camera.inv_view;
                cull_proj = camera_proj;
                cull_drawn = frame_entries.size() + held_now.size();
                ++cull_serial;
            }
            for (const auto& item : entries) {
                Entry* entry = item.second.get();
                if (entry && entry->shadow && entry->seen_frame != frame &&
                    !(entry->held && Holds(*entry)) && // r14: listed above as drawn
                    !entry->gone && frame - entry->seen_frame <= VsmKeepFrames &&
                    !entry->dynamic && entry->built && entry->copied && entry->world.buffer) {
                    if (const auto* box = vsm->Box(entry->world.address)) {
                        entry->box = *box;
                        entry->has_box = true;
                    }
                    // Alpha cut-outs float over the scene depth where the texture discards.
                    const bool cutout = cutout_meshes.contains(entry->mesh);
                    u32 tested = 0, floating = 0;
                    if (!cutout && vsm->Verdict(entry->world.address, tested, floating)) {
                        ++stats.vsm_verified;
                        if (tested >= 12 && floating * 10 >= tested * 6) {
                            if (++entry->gone_streak >= 3) {
                                entry->gone = true;
                                ++stats.vsm_gone;
                                continue;
                            }
                        } else {
                            entry->gone_streak = 0;
                        }
                    }
                    if (entry->has_box) {
                        // Re-tested when the drawn set may have changed, a quarter of the
                        // casters each frame.
                        if (entry->cull_serial != cull_serial || entry->cull_box != entry->box) {
                            if (!entry->cull_serial || entry->cull_box != entry->box ||
                                (frame + (item.first & 3)) % 4 == 0) {
                                entry->culled = replaced(entry->box);
                                entry->cull_box = entry->box;
                                entry->cull_serial = cull_serial;
                            }
                        }
                        if (entry->culled) {
                            ++stats.vsm_culled;
                            continue;
                        }
                    }
                    ++stats.vsm_kept;
                    casters.push_back({entry->world.address, entry->indices.address,
                                       entry->triangles, false, entry->copied_at > vsm_copies,
                                       !cutout});
                }
            }
            const SunVsm::Inputs vsm_in{
                .constants = in.constants,
                .constants_offset = in.constants_offset,
                .constants_range = in.constants_range,
                .depth = in.depth,
                .raw_image = raw_image,
                .raw_view = raw_view,
                .view = camera.view,
                .inv_view = camera.inv_view,
                .constants_offset_word = in.constants_offset_word,
                .frame_index = in.frame_index,
                .width = in.width,
                .height = in.height,
            };
            use_vsm = vsm->Record(casters, vsm_in);
            if (use_vsm) {
                vsm_copies = copies;
            }
        }
    }
    if (!use_vsm && !(need_scene && SunRayTraced())) {
        return false;
    }
    // bbport (experiment mask 4194304 = the old behaviour): pixels whose ray the filter cannot
    // show (outside the game's shadow coverage, with every neighbour it reads) are not traced;
    // rt_shadow.comp RayIsSeen. The same radius for both passes keeps that exact.
    constexpr s32 FilterRadius = 2;
    // bbport (r25_rt-sun-trace): experiment 1125899906842624 clear (default): the exact savings
    // (rt_shadow.comp Shade, rt_shadow_filter.comp R25); set: the old paths. One sun trace in 8
    // counts; every 600 the means per counted frame (u32 differences survive the wrap; read while
    // the GPU may still copy a later frame's counters, which then fall in the next window).
    r25_half = R25HalfWanted(); // bbport (r37_menu-options)
    const CardSunUse card_sun = CardSunNow(r25_half); // bbport (r128c_lrt-cutout-props): empty unless BB_RT_CARD_SUN=1
    if (probe_on) { // bbport (r64b_surface-probe-more): this frame's sun path, for the log
        probe_sun_path = use_vsm ? 1 : r25_half ? 3 : 2;
    }
    const bool r25_exact = !BbToggle::Experiment(R25SunTraceOffBit);
    if (++r25_frames >= 600 && r25_readback.mapped) {
        std::array<u32, R25Slots> now{};
        std::memcpy(now.data(), r25_readback.mapped, sizeof(now));
        const u32 counted = now[0] - r25_last[0];
        std::array<double, R25Slots> d{};
        for (u32 i = 0; i < R25Slots && counted != 0; ++i) {
            d[i] = double(u32(now[i] - r25_last[i])) / double(counted);
        }
        r25_last = now;
        std::printf("Ray traced sun (r25): experiment 1125899906842624 %s, half resolution %s, "
                    "%ux%u; a frame (mean of %u counted): pixels traced %.0f (%.0f full "
                    "resolution or first pass, %.0f second pass); skipped: sky %.0f, beyond the "
                    "shadow distance %.0f (%s), facing away %.0f, taken from the first pass %.0f; "
                    "workgroups with no ray %.0f of %.0f; filter: fade 0 %.0f (%s), 5x5 blur "
                    "%.0f, plain %.0f, workgroups with no fade > 0 %.0f of %.0f\n",
                    r25_exact ? "clear" : "set (old paths)", r25_half ? "on" : "off", raw_width,
                    raw_height, counted, d[4] + d[5], d[4], d[5], d[1], d[2],
                    r25_exact ? "not stored" : "stored", d[3], d[6], d[7], d[8], d[9],
                    r25_exact ? "ray result not read" : "read as before", d[10], d[11], d[12],
                    d[13]);
        // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: its counters, means per counted
        // frame as r25's (u32 differences survive the wrap); a short line, the slot runs keep 300
        // characters of a line
        if (RtGlassLightOn()) {
            std::array<u32, RtGlassLightWords> got{};
            std::memcpy(got.data(),
                        static_cast<const u32*>(r25_readback.mapped) + RtGlassLightFirstWord,
                        sizeof(got));
            std::array<double, RtGlassLightWords> m{};
            for (u32 i = 0; i < RtGlassLightWords && counted != 0; ++i) {
                m[i] = double(u32(got[i] - r86_last[i])) / double(counted);
            }
            r86_last = got;
            std::printf("Ray tracing glass light (r86): %s; panes in the scene %u (carried %u), "
                        "built at a frame end in %u frames; a counted frame (%u): sun-lit asked "
                        "%.0f, crossing a pane %.0f, pane hits %.0f, at the cap %.0f; shadowed "
                        "tested %.0f, blocked at a pane %.0f\n",
                        RtGlassLightName(RtGlassLight()), glass_instances, glass_carried,
                        glass_late, counted, m[0], m[1], m[2], m[3], m[4], m[5]);
            glass_late = 0;
        }
        // bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN=1: its counters, means per counted frame as r25's (u32 differences survive the wrap)
        if (CardSunWanted()) {
            std::array<u32, CardSunWords> got{};
            std::memcpy(got.data(), static_cast<const u32*>(r25_readback.mapped) + CardSunFirstWord, sizeof(got));
            std::array<double, CardSunWords> m{};
            for (u32 i = 0; i < CardSunWords && counted != 0; ++i) {
                m[i] = double(u32(got[i] - card_sun_last[i])) / double(counted);
            }
            card_sun_last = got;
            std::printf("Ray traced sun cut-outs (r128c): %u sun traces ran the cut-out build, %u the plain one (cut-out cards in the scene %u); a counted "
                        "frame (%u): pixels traced %.0f, with a ray that met a card %.0f, layer reads %.0f, rays stopped by a kept texel %.0f (pixels "
                        "%.0f), candidates passed as the pixel's own surface %.0f, rays stopped at the cap %.0f, first-pass pixels marked %.0f\n",
                        card_sun_cards, card_sun_plain, card_lamp_instances, counted, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7]);
            card_sun_cards = card_sun_plain = 0;
        }
        // bbport (r131a_foliage-translucency): the sun's light through leaves: its four counters follow the CARDS ones (r25 words 24 to 27), means per
        // counted frame as r25's
        if (FoliageTranslucency::SunThrough()) {
            std::array<u32, 4> got{};
            std::memcpy(got.data(), static_cast<const u32*>(r25_readback.mapped) + CardSunFirstWord + CardSunWords, sizeof(got));
            std::array<double, 4> m{};
            for (u32 i = 0; i < 4 && counted != 0; ++i) {
                m[i] = double(u32(got[i] - foliage_sun_last[i])) / double(counted);
            }
            foliage_sun_last = got;
            std::printf("Foliage light (r131a): sun rays %.0f, passed a leaf %.0f (T=%.2f), ended at floor %.0f, grey (no colour) %.0f (a counted frame, %u of "
                        "them); the sun and moon: %s\n",
                        m[0], m[1], double(FoliageTranslucency::Tuning().pass), m[2], m[3], counted,
                        FoliageTranslucency::Glow() ? "grey part through the game's light, hue added by the glow pass"
                                                    : "grey (no tint without the glow pass)");
        }
        r25_frames = 0;
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on and a pane in the TLAS: its bits
    // (rt_glass_light.h); off, or no pane: 0, the flags of before
    const u32 r25_flags =
        (r25_exact ? R25Exact : 0u) | ((r25_recorded++ & 7) == 0 ? R25Count : 0u) |
        RtGlassLightFlags(RtGlassLight(), glass_instances != 0);
    const bool r25_clear = !r25_cleared;
    r25_cleared = true;
    const TracePush trace{
        .buf_off = in.constants_offset_word,
        .frame_index = 0u,
        .size = {float(in.width), float(in.height)},
        .rays = rays,
        .light_tan = 0.02f,
        .bias_m = 0.01f,
        .max_distance = 800.0f,
        .far_radius = BbToggle::Experiment(4194304) ? -1 : FilterRadius,
        .r25_flags = r25_flags,
        .pass_share = FoliageTranslucency::LightNow() ? FoliageTranslucency::Tuning().pass : 0.0f, // bbport (r131a_foliage-translucency): 0 switched off live
        .pass_tint = FoliageTranslucency::Tuning().tint,
        .pass_floor = FoliageTranslucency::Tuning().floor,
    };
    const FilterPush filter{
        .buf_off = in.constants_offset_word,
        .radius = FilterRadius,
        .size = {float(in.width), float(in.height)},
        .r25_flags = r25_flags,
    };
    if (card_sun.foliage && !use_vsm) { // bbport (r131a_foliage-translucency): the hue image of this trace (the glow pass reads it)
        sun_hue_frame = frame;
    }
    EffectPass::Mark(14, "ray traced sun");
    scheduler.RecordCrumb(
        {.name = "Ray traced sun"},
        [in, trace, filter, use_vsm, tlas = tlas, raw_image = raw_image, raw_view = raw_view,
         sampler = *sampler, card_sun, // bbport (r128c_lrt-cutout-props): the cut-out build, or nothing
         trace_pipeline = card_sun.pipeline ? card_sun.pipeline : *trace_pipeline,
         trace_layout = card_sun.pipeline ? card_sun.layout : *trace_layout,
         filter_pipeline = *filter_pipeline, filter_layout = *filter_layout,
         r25_counts = r25_counts.buffer, r25_readback = r25_readback.buffer, r25_half = r25_half,
         half_pipeline = r25_half ? (card_sun.pipeline ? card_sun.pipeline : *r25_half_pipeline) : vk::Pipeline{},
         half_layout = r25_half ? (card_sun.pipeline ? card_sun.layout : *r25_half_layout) : vk::PipelineLayout{},
         r25_clear](vk::CommandBuffer cmdbuf) {
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = Compute,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .image = raw_image,
                .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
            };
            if (!use_vsm) {
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            if (card_sun.foliage && !use_vsm) {
                // bbport (r131a_foliage-translucency): the hue image: undefined to general and cleared to 0 (a pixel the trace does not shade has no leaf share)
                const vk::ImageMemoryBarrier2 hue_to_general{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .image = card_sun.hue_image,
                    .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &hue_to_general});
                const vk::ClearColorValue hue_zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                const vk::ImageSubresourceRange hue_range{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
                cmdbuf.clearColorImage(card_sun.hue_image, vk::ImageLayout::eGeneral, hue_zero, hue_range);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            }
            if (r25_clear) { // bbport (r25_rt-sun-trace): the counters start at zero
                cmdbuf.fillBuffer(r25_counts, 0, VK_WHOLE_SIZE, 0);
                // vkCmdFillBuffer is a transfer command: eTransfer covers it whichever
                // transfer sub-stage (clear or copy) a driver or the validation layer files it
                // under.
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            }
            const vk::DescriptorBufferInfo r25_info{r25_counts, 0, VK_WHOLE_SIZE};

            const vk::DescriptorBufferInfo constants{in.constants, in.constants_offset, in.constants_range};
            const vk::DescriptorBufferInfo uniforms{in.uniforms, in.uniforms_offset, in.uniforms_range};
            const vk::DescriptorImageInfo depth{sampler, in.depth, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo raw_write{{}, raw_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo raw_read{sampler, raw_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo target{{}, in.target, vk::ImageLayout::eGeneral};
            const vk::WriteDescriptorSetAccelerationStructureKHR scene{
                .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
            // bbport (r128c_lrt-cutout-props): bindings 6 to 9 are the cut-out build's card tables (pushed only with it)
            const vk::DescriptorBufferInfo cs_rows{card_sun.rows, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo cs_pool{card_sun.pool, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo cs_info{card_sun.info, 0, VK_WHOLE_SIZE};
            const vk::DescriptorImageInfo cs_alpha{card_sun.sampler, card_sun.layers, vk::ImageLayout::eGeneral};
            // bbport (r131a_foliage-translucency): bindings 10 and 11 are the FOLIAGE builds' colour layers and hue image (pushed only with them)
            const vk::DescriptorImageInfo cs_colour{card_sun.sampler, card_sun.colour, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo cs_hue{{}, card_sun.hue, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 12> trace_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &raw_write},
                {.pNext = &scene, .dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &uniforms},
                {.dstBinding = 5, .descriptorCount = 1, // r25: counters
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},
                {.dstBinding = 6, .descriptorCount = 1, // r128c: the cut-out cards (rt_shadow_cards_comp)
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_rows},
                {.dstBinding = 7, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_pool},
                {.dstBinding = 8, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cs_info},
                {.dstBinding = 9, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_alpha},
                {.dstBinding = 10, .descriptorCount = 1, // r131a: the colour layers
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_colour},
                {.dstBinding = 11, .descriptorCount = 1, // r131a: the hue image
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cs_hue},
            }};
            // the plain build has six bindings, the cut-out build ten (a count and a pointer: no copy)
            const vk::ArrayProxy<const vk::WriteDescriptorSet> trace_push(card_sun.foliage ? 12u : card_sun.pipeline ? 10u : 6u,
                                                                          trace_writes.data()); // (r131a: 12 with the FOLIAGE build)
            if (!use_vsm) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, trace_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, trace_layout, 0,
                                            trace_push);
                cmdbuf.pushConstants(trace_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(trace), &trace);
                if (!r25_half) {
                    cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
                } else {
                    // bbport (r25_rt-sun-trace): BB_RT_SUN_HALF=1: pixel (2x, 2y) of each 2x2
                    // block, then the other three (taken from those, or traced), with the
                    // rt_shadow_half_comp build (same bindings and push constants).
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipeline);
                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_layout, 0,
                                                trace_push);
                    TracePush pass = trace;
                    pass.r25_flags = trace.r25_flags | R25HalfFirst;
                    cmdbuf.pushConstants(half_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(pass), &pass);
                    cmdbuf.dispatch(((in.width + 1) / 2 + 7) / 8, ((in.height + 1) / 2 + 7) / 8,
                                    1);
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                    pass.r25_flags = trace.r25_flags | R25HalfFill;
                    cmdbuf.pushConstants(half_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(pass), &pass);
                    cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                   vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            const std::array<vk::WriteDescriptorSet, 6> filter_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &raw_read},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &target},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &uniforms},
                {.dstBinding = 5, .descriptorCount = 1, // r25: counters
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},
            }};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, filter_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, filter_layout, 0, filter_writes);
            cmdbuf.pushConstants(filter_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(filter), &filter);
            cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, vk::PipelineStageFlagBits2::eAllCommands,
                   vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
            // bbport (r25_rt-sun-trace): a counted frame's counters to the host (Record reads
            // them); later counting waits for the copy.
            if ((filter.r25_flags & R25Count) != 0) {
                const vk::BufferCopy region{0, 0, R25Words() * sizeof(u32)}; // (r86)
                cmdbuf.copyBuffer(r25_counts, r25_readback, region);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite |
                                              vk::AccessFlagBits2::eTransferRead,
                                          vk::PipelineStageFlagBits2::eHost | Compute,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            }
        });
    return true;
}

// bbport (r26_upkeep-probe): at each frame end while BB_RT_UPKEEP_FREEZE is set, after `frame`
// moved on and before the evictions. Counts the frames in the level (in a row with casters in the
// ray tracing scene), decides what the next frame freezes, prints, and returns whether this frame
// end's evictions wait: the TLAS traced as it was holds the BLAS addresses of its entries, so none
// is destroyed while it stays frozen. An eviction pass that does run may destroy one, so a new
// TLAS is built before one is kept again.
bool RtShadow::R26FrameEnd() {
    const u32 mode = UpkeepProbeMode();
    const u32 was = r26_freeze;
    r26_level_frames = need_scene && !frame_entries.empty() ? r26_level_frames + 1 : 0;
    const bool bit = BbToggle::Experiment(R26ProbeOffBit);
    r26_freeze = !bit && need_scene && r26_level_frames >= R26AfterFrames ? mode : 0u;
    const bool evicting = frame % 64 == 0 || blas_bytes > blas_limit - blas_limit / 8 ||
                          entry_bytes > MaxEntryBytes / 8 * 7;
    const bool hold = r26_tlas_kept && (r26_freeze & 2u) != 0;
    if (evicting && hold) {
        ++r26_stats.evictions_held;
    } else if (evicting || !need_scene) {
        r26_tlas_built = false;
    }
    r26_tlas_kept = false;
    static constexpr const char* mode_names[] = {"off", "blas", "tlas", "all"};
    static constexpr const char* frozen_names[] = {
        "nothing", "BLAS refits and builds (TLAS built as usual)",
        "the TLAS (BLAS refits and builds as usual)", "BLAS refits and builds and the TLAS"};
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    if (r26_freeze != 0 && was == 0) {
        std::printf("Ray tracing upkeep probe (r26): engaged from frame %llu after %llu frames in "
                    "the level: BB_RT_UPKEEP_FREEZE=%s freezes %s; experiment 2251799813685248 "
                    "set releases it\n",
                    u(frame), u(r26_level_frames), mode_names[mode], frozen_names[mode]);
    } else if (r26_freeze == 0 && was != 0) {
        std::printf("Ray tracing upkeep probe (r26): released from frame %llu (%s)\n", u(frame),
                    bit           ? "experiment 2251799813685248 set"
                    : !need_scene ? "ray tracing scene off"
                                  : "no casters in the scene: left the level");
    }
    ++r26_stats.frames;
    r26_stats.frozen += was != 0 ? 1 : 0;
    if (r26_stats.frames >= 600 || (r26_stats.frames > 1 && bit != r26_stats.bit)) {
        const double f = double(r26_stats.frames);
        std::printf("Ray tracing upkeep probe (r26): BB_RT_UPKEEP_FREEZE=%s (freezes %s), "
                    "experiment 2251799813685248 %s; over %llu frames, %llu frozen: a frame %.1f "
                    "BLAS refits (%.0f triangles) and %.1f BLAS builds (%.0f triangles) left out, "
                    "%.1f casters without a BLAS left out, %.1f BLAS refits and builds still "
                    "recorded, %.2f TLAS builds left out (%llu kept as built, %llu prepared as "
                    "usual); %llu eviction passes held back; %llu frames in the level\n",
                    mode_names[mode], frozen_names[mode],
                    r26_stats.bit ? "set (probe off)" : "clear (probe on)", u(r26_stats.frames),
                    u(r26_stats.frozen), double(r26_stats.refits_left) / f,
                    double(r26_stats.refit_triangles) / f, double(r26_stats.builds_left) / f,
                    double(r26_stats.build_triangles) / f, double(r26_stats.left_out) / f,
                    double(r26_stats.recorded) / f, double(r26_stats.tlas_kept) / f,
                    u(r26_stats.tlas_kept), u(r26_stats.tlas_prepared),
                    u(r26_stats.evictions_held), u(r26_level_frames));
        r26_stats = {};
    }
    r26_stats.bit = bit;
    return hold;
}

// bbport (r43_copy-turns): the end of a frame hands out the turns of the next
// (rt_copy_turns.h): tickets for the built shared copies drawn on this frame, the oldest build
// first, so that no moving copy that is drawn every frame goes more than CopyWait() frames in a
// row without a rebuild. The tickets are kept in the entries themselves; turn_drawn and
// turn_items point into the entries only up to the end of this call, which runs before the
// frame end's evictions (no entry is destroyed during a frame). A turn leads to the rebuild
// every refresh of a shared copy is: in place, recorded by RecordBuilds before the top-level
// build of the frame that traces it (PrepareScene), nothing created or freed.
void RtShadow::PlanCopyTurns() {
    const bool on = CopyTurnsOn();
    turn_items.clear();
    for (Entry* entry : turn_drawn) {
        entry->turn_listed = false;
        // (Listed and then not drawn after all, not built yet, or promoted to an instance's
        // entry on this frame: no turn.)
        if (on && entry->rebuilt && entry->built && entry->seen_frame == frame) {
            turn_items.push_back({&entry->turn, entry->built_frame, entry->triangles,
                                  u32(entry->turn_gap), entry->dynamic});
        }
    }
    turn_drawn.clear();
    if (!on) {
        copy_turns.Clear();
        return;
    }
    const CopyTurnPlan plan = copy_turns.Plan(turn_items, frame, RebuiltBudget(), CopyWait());
    turn_items.clear();
    turn_stats.past += plan.past;
    turn_stats.past_triangles += plan.past_triangles;
}

// bbport (r47_still-check): what is done about the casters held for still right now. The
// experiment bit is read at each use, so old and new can be compared in one run.
u32 RtShadow::StillNow() const {
    return still_ready && !BbToggle::Experiment(StillCheckOldBit) ? StillMode() : u32(StillOff);
}

// bbport (r47_still-check): a signature of this frame for a capture of `entry` (1 to
// StillSigsPerFrame), or 0 when the frame's are used up. Until it is read or dropped the entry
// counts it (Entry::still_wait).
u32 RtShadow::TakeStillSig(Entry& entry) {
    if (still_sig_used >= StillSigsPerFrame) {
        return 0;
    }
    ++entry.still_wait;
    return ++still_sig_used;
}

// bbport (r47_still-check): for the signature of a capture drawn with `constants` (the
// projection at word 52, view to world at word 180, as ToWorld reads them): what takes its clip
// space positions to world space in rt_still_sig.comp (StillClipToWorld). False without an
// inverse of the projection.
bool RtShadow::StillWorld(const float* constants, Build& build) const {
    bool ok = false;
    const auto inverse = Invert(constants + 52, ok);
    if (!ok) {
        return false;
    }
    StillClipToWorld(inverse.data(), constants + 180, build.still_rows, build.still_origin);
    const auto finite = [](float v) { return std::isfinite(v); };
    return std::ranges::all_of(build.still_rows, finite) &&
           std::ranges::all_of(build.still_origin, finite);
}

// bbport (r47_still-check): the rasterizer left out the draw PrepareDraw last set a capture up
// for (its pipeline is still compiling: vk_rasterizer.cpp, SkipUncompiledDraw). No vertex shader
// ran, so nothing stored the draw's positions: their range holds what an earlier frame left
// there. A look would read that as a move, a reference taken from it would make every later
// look one, and a BLAS built from it holds no caster. So the capture's signature is given back;
// a probe is dropped and its look taken again at the caster's next draw; and with BB_RT_STILL=on
// the build is dropped too (RecordBuilds), so the entry is built from its next draw that runs.
// With count the build stays as it always was, only unmeasured. Nothing with the experiment bit
// set. `motion_param`, `mode`: the draw's push constant and its pipeline's motion mode, as
// EffectsCaptureDraw left them.
void RtShadow::CaptureLeftOut(u32 motion_param, u32 mode) {
    const u32 param = Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth
                          ? motion_param >> 16
                          : motion_param;
    if (auto* pane = window_pane_watch; pane && param && pane->rt_frame == frame && param == pane->param) {
        pane->Refuse("ordinary pane draw did not execute");
    }
    if (lamp_pane && lamp_pane->Captured() && lamp_pane->capture.rt == frame &&
        param == lamp_pane->param && param != 0) {
        lamp_pane->refusal = "matching draw was left out before rasterization";
    }
    // bbport (r54_leaf-stage2): nor its card UVs: none are expanded, the entry stays Wanted.
    // A capture for the UVs alone (CardUvProbe) is nothing more: r47's looks never counted
    // it, so none of their state below changes for it.
    if (param != 0 && !builds.empty() && builds.back().param == param) {
        Build& last = builds.back();
        if (last.uv_base != 0) {
            last.uv_base = 0;
            ++card_uv_stats.left_out;
        }
        if (last.uv_only) {
            last.left_out = true;
            return;
        }
    }
    const u32 still = StillNow();
    if (param == 0 || still == StillOff || builds.empty() || builds.back().param != param) {
        return;
    }
    Build& build = builds.back();
    Entry& entry = *build.entry;
    if (build.sig != 0) {
        build.sig = 0;
        entry.still_wait -= entry.still_wait != 0 ? 1 : 0;
    }
    ++still_stats.left_out;
    if (build.probe) {
        entry.still_checks -= entry.still_checks != 0 && entry.still_checks != 0xff ? 1 : 0;
        entry.still_next = frame;
        build.left_out = true;
    } else if (still == StillOn) {
        build.left_out = true;
    }
}

// bbport (r47c_review-fixes): BB_RT_PALETTE_PLACE, read once (default 1). 0, a diagnostic for a
// whole run: a small bone palette in memory the GPU wrote is known by its bytes in guest memory
// again, as before r47b, while r47's looks stay on (the two share experiment StillCheckOldBit):
// what the looks do without r47b. Every instance of such a prop's mesh is then one entry, which
// the looks find "moving" between the instances' places and refit to the one drawn last.
bool RtShadow::PalettePlace() {
    static const bool place = ReadCopyTurnKnob(std::getenv("BB_RT_PALETTE_PLACE"), 1, 1) != 0;
    return place;
}

// bbport (r47_still-check): an entry that is new under the key `id`: when a look found the
// caster of that key moving before (still_movers) it counts as moving from the start, within
// the cap. (A shared copy's key is never in the list: copies are rebuilt in turn, not looked at.)
void RtShadow::StillAdmit(Entry& entry, u64 id) {
    if (StillNow() != StillOn || entry.dynamic || !still_movers.contains(id) ||
        still_mover_triangles + entry.triangles > StillMoverCap()) {
        return;
    }
    entry.dynamic = true;
    entry.still_moved = true;
    still_mover_triangles += entry.triangles;
    ++still_stats.known;
}

// bbport (r47_still-check): the signatures of one frame of the ring, once the GPU has written
// them. A capture the BLAS was built from gives the reference: the caster's bounds in that
// pose. A look's bounds are compared with it: past the tolerance the caster has moved since its
// BLAS was built, and (BB_RT_STILL=on, on the second look in a row that finds so, within the
// cap) counts as moving from now on, like a skinned one: PrepareDraw refits it at every draw.
// The two passes may place one mesh a little
// differently (a sun shadow pass's vertex shader may add a bias), so each pass has its own
// reference; a look by the pass that has none yet is compared with the other pass's under the
// wide tolerance (a caster built in a passing pose is off by far more) and, within it, becomes
// that pass's reference.
void RtShadow::ReadStillSigs(u32 slot) {
    const auto* words = static_cast<const u32*>(still_readback.mapped) +
                        std::size_t(slot) * StillSigsPerFrame * StillSigWords;
    const u32 still = StillNow();
    for (const StillPending& item : still_pending[slot]) {
        Entry& entry = *item.entry;
        entry.still_wait -= entry.still_wait != 0 ? 1 : 0;
        std::array<u32, StillSigWords> sig;
        std::memcpy(sig.data(), words + std::size_t(item.sig - 1) * StillSigWords, sizeof(sig));
        StillBox box;
        if (!DecodeStillSig(sig.data(), box)) {
            // A mesh with a vertex that is not a number: its bounds cannot be compared, so it
            // is not looked at again until its BLAS is built anew.
            entry.still_blind = true;
            ++still_stats.unread;
            continue;
        }
        const u32 pass = item.camera ? 0u : 1u;
        if (item.first) {
            entry.still_has_ref = {};
            entry.still_ref[pass] = box;
            entry.still_has_ref[pass] = true;
            entry.still_ref_frame = item.frame;
            ++still_stats.firsts;
            continue;
        }
        const bool cross = !entry.still_has_ref[pass];
        if (cross && !entry.still_has_ref[pass ^ 1u]) {
            // No reference at all (BB_RT_STILL=count, and built before the looks began or its
            // signature lost): this look is the first that can be compared with.
            entry.still_ref[pass] = box;
            entry.still_has_ref[pass] = true;
            entry.still_ref_frame = item.frame;
            continue;
        }
        const StillBox& then = entry.still_ref[cross ? pass ^ 1u : pass];
        const float moved = StillMoved(then, box);
        const float limit = cross ? std::max(StillLimit(), StillCrossTolerance) : StillLimit();
        if (!(moved > limit)) {
            entry.still_doubt = false;
            if (cross) {
                entry.still_ref[pass] = box;
                entry.still_has_ref[pass] = true;
            }
            continue;
        }
        ++still_stats.found;
        still_stats.found_new += entry.still_seen ? 0 : 1;
        still_stats.found_instance += entry.instance ? 1 : 0;
        still_stats.found_camera += item.camera ? 1 : 0;
        still_stats.found_cross += cross ? 1 : 0;
        entry.still_seen = true;
        const u64 id = entry.instance ? InstanceKey(entry.base, entry.palette) : entry.base;
        // bbport (r47c_review-fixes): a prop known by its palette's address found far from where
        // its BLAS was built, with a box of the same size: carried whole, or its palette's
        // address was given to another prop of the mesh (it then counts as moving for good once
        // taken, and is refit at every draw). Counted for the line; no run has shown one.
        still_stats.placed_carried += entry.instance && entry.palette_placed &&
                                              moved > StillCarried &&
                                              StillSameSize(then, box, 2.0f * StillLimit())
                                          ? 1
                                          : 0;
        bool taken = false;
        if (still == StillOn && !entry.dynamic) {
            if (!entry.still_doubt) {
                // One look decides nothing that lasts for the life of the entry: one capture
                // that went wrong must not make a wall a moving caster. A second look is asked
                // for at once, and a caster is taken when that one finds it moved as well.
                entry.still_doubt = true;
                entry.still_next = frame;
                ++still_stats.doubted;
            } else if (still_mover_triangles + entry.triangles > StillMoverCap()) {
                ++still_stats.not_taken;
            } else {
                entry.still_doubt = false;
                entry.dynamic = true;
                entry.still_moved = true;
                still_mover_triangles += entry.triangles;
                if (still_movers.size() >= 65536) {
                    still_movers.clear();
                }
                still_movers.insert(id);
                ++still_stats.taken;
                taken = true;
            }
        }
        // For the line: the four that moved farthest, each caster once.
        const StillFound found{id, entry.base, entry.mesh, item.frame - entry.still_ref_frame,
                               entry.triangles, entry.still_checks, moved, then, box,
                               entry.instance, item.camera, cross, taken, entry.palette != 0,
                               entry.palette_placed, entry.skinned};
        // bbport (r47b_casters): BB_RT_STILL_LIST: every one of them, each caster once
        if (StillListMost() != 0) {
            auto listed = still_list.find(id);
            if (listed == still_list.end() && still_list.size() < StillListMost()) {
                listed = still_list.emplace(id, found).first;
            }
            if (listed != still_list.end()) {
                const u32 finds = listed->second.finds + 1;
                const bool was_taken = listed->second.taken;
                if (moved >= listed->second.moved) {
                    listed->second = found;
                }
                listed->second.finds = finds;
                listed->second.taken = was_taken || taken;
            }
        }
        // Its place: the one it has, else the first empty one, else the smallest move's.
        StillFound* place = nullptr;
        for (StillFound& kept : still_stats.largest) {
            if (kept.triangles != 0 && kept.id == id) {
                place = &kept;
                break;
            }
            if (!place || (place->triangles != 0 &&
                           (kept.triangles == 0 || kept.moved < place->moved))) {
                place = &kept;
            }
        }
        if (place->triangles != 0 && place->id == id) {
            const bool was_taken = place->taken;
            if (moved > place->moved) {
                *place = found;
            }
            place->taken = was_taken || taken;
        } else if (place->triangles == 0 || moved > place->moved) {
            *place = found;
        }
    }
    still_pending[slot].clear();
    still_ticks[slot] = 0;
}

// bbport (r54_leaf-stage2): the card UVs, stage 2 of the ray traced foliage shadows (BB_RT_CARD_ALPHA=1;
// rt_card_uv.h says what, engine/docs/rt_card_alpha.md why). A cut-out entry's capture also stores
// its vertices' coordinates and alpha factors (the vertex shader's capture variant, CaptureUv,
// into card_ring), and RecordBuilds expands them into the entry's block of card_pool: a record of
// 16 bytes a BLAS primitive. Nothing reads the pool yet; no ray, mask, TLAS or BLAS changes.

// The ring, the expand pass and its stat slots (at setup, the knob on). Without them no capture
// stores UVs (CardCapture), and the address blocks hold a ring address of 0 that nothing reads.
// The ring's memory is not known until the first RecordBuilds fills it with CARD_UV_RING_UNSET
// (card_ring_clean); no capture stores UVs before that.
bool RtShadow::CardSetup() {
    using enum vk::DescriptorType;
    const vk::DeviceSize stat_bytes = vk::DeviceSize(CARD_UV_STAT_SLOTS) * CARD_UV_STAT_WORDS * 4;
    card_ring_clean = false;
    card_ring_dirty = 0;
    card_uv_ready =
        EffectPass::Create(instance, card_set, card_layout, card_pipeline,
                           {eStorageBuffer, eStorageBuffer, eStorageBuffer}, sizeof(CardUvPush),
                           RT_CARD_UV_COMP, "Ray tracing card UVs") &&
        Make(card_ring, CardRingBytes, false,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        Make(card_stat_buffer, stat_bytes, false,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                 VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        Make(card_readback, stat_bytes, true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        card_readback.mapped;
    if (!card_uv_ready) {
        Free(card_ring);
        Free(card_stat_buffer);
        Free(card_readback);
        std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%u but off - no pipeline or "
                    "buffer for them\n",
                    Shader::Optimization::CardAlphaLevel()); // (r62) the level read
        return false;
    }
    std::memset(card_readback.mapped, 0, std::size_t(stat_bytes));
    std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%u, the cut-out cards' UVs are captured "
                "(ring %llu MiB now, pool %llu MiB at the first card); no ray reads them yet, the "
                "picture is unchanged\n",
                Shader::Optimization::CardAlphaLevel(), // (r62) the level read
                static_cast<unsigned long long>(CardRingBytes >> 20),
                static_cast<unsigned long long>(CardPoolBytes >> 20));
    return true;
}

bool RtShadow::CardMakePool() {
    if (card_pool_failed) {
        return false;
    }
    const VmaVirtualBlockCreateInfo block_ci{.size = CardPoolBytes};
    if (!Make(card_pool, CardPoolBytes, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        vmaCreateVirtualBlock(&block_ci, &card_block) != VK_SUCCESS) {
        Free(card_pool);
        card_block = VK_NULL_HANDLE;
        card_pool_failed = true;
        std::printf("Ray tracing card UVs (r54): no pool (%llu MiB): no card gets UVs\n",
                    static_cast<unsigned long long>(CardPoolBytes >> 20));
        return false;
    }
    return true;
}

// A block of the pool for the entry's records (and its card slot). Over the pool: NoRoom, tried
// again once a block is freed (card_pool_gen).
bool RtShadow::CardTakeBlock(Entry& entry) {
    CardUvEntry& c = *entry.card_uv;
    if (!CardPoolFits(entry.triangles) || (!card_block && !CardMakePool())) {
        CardNoRoom(c.uv, card_pool_gen);
        ++card_uv_stats.no_room;
        return false;
    }
    const VmaVirtualAllocationCreateInfo alloc_ci{.size = CardPoolSize(entry.triangles),
                                                  .alignment = CARD_UV_RECORD_BYTES};
    VmaVirtualAllocation block{};
    VkDeviceSize offset = 0;
    if (vmaVirtualAllocate(card_block, &alloc_ci, &block, &offset) != VK_SUCCESS) {
        CardNoRoom(c.uv, card_pool_gen);
        ++card_uv_stats.no_room;
        return false;
    }
    c.block = block;
    c.offset = u32(offset / CARD_UV_RECORD_BYTES);
    c.slot = card_slots.Take();
    card_pool_used += alloc_ci.size;
    ++card_pool_blocks;
    CardGotRoom(c.uv);
    return true;
}

// A cut-out draw of the entry (Draw::card): its card data, at every draw (a second draw of the
// frame too, so the sun shadow pass's card is had whichever pass comes first). The entry's part
// is made at its first such draw, once (not on every frame). A sun shadow pass card gives way to
// a camera pass card when it is stale or no sun shadow pass draw gave it for more than
// CardSunFrames frames (CardTakes; counted). The first time an entry has a valid
// card from both passes, both references and both second reference dwords (cb[21]) are printed
// (the first CardBothLines such entries; the 600-frame line counts all), with the pass whose card
// the entry holds then (the sun shadow pass's unless that card was stale), and a tester sees
// whether the camera pass's material constants give another reference.
void RtShadow::CardNoteDraw(Entry& entry, const Draw& draw) {
    const CardDraw& d = *draw.card;
    ++card_uv_stats.draws;
    if (d.valid) {
        ++card_uv_stats.valid;
    } else {
        ++card_uv_stats.miss[std::size_t(d.miss)];
    }
    if (!entry.card_uv) {
        entry.card_uv = std::make_unique<CardUvEntry>();
    }
    CardUvEntry& c = *entry.card_uv;
    if (entry.seen_frame != frame) {
        CardWaitFrame(c.uv);
    }
    const CardNoted noted = CardNote(c.uv, d, frame);
    card_uv_stats.coordinates += noted.taken && noted.coordinates && c.block ? 1 : 0;
    card_uv_stats.constants += noted.other ? 1 : 0;
    card_uv_stats.sun_gave_way += noted.sun_gave_way ? 1 : 0;
    if (noted.both && card_both_said < CardBothLines &&
        card_said.insert(CardSaidKey(entry.base, CardSaid::Both, false)).second) { // (r62b) once
        ++card_both_said;
        const float sun = c.uv.pass_reference[0];
        const float cam = c.uv.pass_reference[1];
        std::printf("Ray tracing card UVs (r54): drawn by both passes, key %016llx (%s): sun shadow "
                    "pass ps %016llx reference %.6g (second dword %.6g), camera pass ps %016llx "
                    "reference %.6g (second dword %.6g, dither taken as 0), %s; the card is the "
                    "%s pass's\n",
                    static_cast<unsigned long long>(entry.base), CardClassNow(entry), // (r62b)
                    static_cast<unsigned long long>(c.uv.pass_ps_hash[0]), double(sun),
                    double(c.uv.pass_ref2[0]), static_cast<unsigned long long>(c.uv.pass_ps_hash[1]),
                    double(cam), double(c.uv.pass_ref2[1]), sun == cam ? "the same" : "they differ",
                    c.uv.card.camera ? "camera" : "sun shadow");
    }
    // bbport (r62b_leaf-stage3-followups): one line per entry and pass whose card has a second
    // reference dword not 0 (cb[21]; the r54 log counted 5 and named 3), with the reference it
    // gives (as read, never clamped) and whether the rule keeps any alpha in [0, 1].
    if (d.valid && d.ref_dwords[1] != 0.0f && card_ref2_said < CardBothLines &&
        card_said.insert(CardSaidKey(entry.base, CardSaid::SecondDword, d.camera)).second) {
        ++card_ref2_said;
        const bool dither = d.dither && d.dither_scale != 0.0f;
        std::printf("Ray tracing card UVs (r62b): second reference dword not 0, key %016llx (%s), "
                    "%s pass ps %016llx: first dword %.6g, second %.6g, reference %.6g%s, dither "
                    "coefficient %.6g%s; %s\n",
                    static_cast<unsigned long long>(entry.base), CardClassNow(entry),
                    d.camera ? "camera" : "sun shadow", static_cast<unsigned long long>(d.ps_hash),
                    double(d.ref_dwords[0]), double(d.ref_dwords[1]), double(d.reference),
                    d.reference > 1.0f ? " (above 1, used as read)" : "", double(d.dither_scale),
                    dither ? "" : " (no dither)",
                    CardRuleClear(d.op, d.reference, d.nonzero, dither, d.dither_scale)
                        ? "fully clear: the rule keeps no alpha in [0, 1]"
                        : "not fully clear");
    }
}

// bbport (r62b_leaf-stage3-followups): the class of an entry as the log names it now.
const char* RtShadow::CardClassNow(const Entry& entry) const noexcept {
    return CardClassText(entry.skinned, entry.lone == LampLoneState::Lone,
                         entry.lone == LampLoneState::Lone || entry.lone == LampLoneState::Sun);
}

// bbport (r62m_cutout-name-blocker, TOOL): see the declaration.
RtShadow::CardBlockerInfo RtShadow::CardBlockerOf(u32 slot) const {
    CardBlockerInfo r;
    if (slot == 0) {
        return r;
    }
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || !e->card_uv || CardCustomIndex(*e) != slot) {
            continue;
        }
        r.found = true;
        r.key = e->base;
        r.stream = e->stream;
        r.camera_pass = e->card_uv->uv.card.camera;
        r.ps = e->card_uv->uv.card.ps_hash;
        r.skinned = e->skinned;
        r.dynamic = e->dynamic;
        r.instance = e->instance;
        r.triangles = e->triangles;
        r.vertices = e->vertices;
        r.bones = e->skeleton_bones; // bbport (r62n_cutout-skinned-blocker) TOOL
        r.lone = e->lone == LampLoneState::Lone;
        r.lone_text = !e->skinned                          ? "not skinned"
                      : e->lone == LampLoneState::Lone     ? "lone"
                      : e->lone == LampLoneState::Sun      ? "drawn by the sun shadow pass"
                      : e->lone == LampLoneState::Waiting  ? "not settled"
                                                           : "no verdict";
        const u32 flags = e->card_uv->row[2];
        r.op = (flags >> CARD_ROW_OP_SHIFT) & 7u;
        r.layer = flags & u32(CARD_ROW_LAYER_MASK);
        r.reference = std::bit_cast<float>(e->card_uv->row[3]);
        if (e->has_box) {
            r.box = e->box;
            r.box_src = 'v';
        } else if (e->still_has_ref[1]) {
            r.box = e->still_ref[1];
            r.box_src = 's';
        } else if (e->still_has_ref[0]) {
            r.box = e->still_ref[0];
            r.box_src = 'c';
        }
        if (r.box_src != '-') {
            const auto view = camera_motion.CameraMatrices().view; // 3 rows of 4: view space = view * (world, 1)
            const std::array<float, 3> mid{0.5f * (r.box[0] + r.box[3]), 0.5f * (r.box[1] + r.box[4]),
                                           0.5f * (r.box[2] + r.box[5])};
            for (u32 i = 0; i < 3; ++i) {
                r.centre_view[i] = view[i * 4] * mid[0] + view[i * 4 + 1] * mid[1] + view[i * 4 + 2] * mid[2] + view[i * 4 + 3];
            }
        }
        break;
    }
    return r;
}

// bbport (r62n_cutout-skinned-blocker) TOOL: see the declaration. The camera's inverse view takes the point to the world; the hunter's place is
// the game's (y up): sideways is x and z, up is y.
RtShadow::HunterRel RtShadow::HunterAgainst(const std::array<float, 3>& point_view) const {
    HunterRel r;
    const auto m = camera_motion.CameraMatrices();
    float pos[3] = {0.0f, 0.0f, 0.0f};
    if (!m.valid || !BbEngine::world_player_position(pos) || !std::isfinite(pos[0]) || !std::isfinite(pos[1]) ||
        !std::isfinite(pos[2])) {
        return r;
    }
    r.known = true;
    std::array<float, 3> at{};
    for (u32 i = 0; i < 3; ++i) {
        r.world[i] = pos[i];
        r.view[i] = m.view[i * 4] * pos[0] + m.view[i * 4 + 1] * pos[1] + m.view[i * 4 + 2] * pos[2] + m.view[i * 4 + 3];
        at[i] = m.inv_view[i * 4] * point_view[0] + m.inv_view[i * 4 + 1] * point_view[1] +
                m.inv_view[i * 4 + 2] * point_view[2] + m.inv_view[i * 4 + 3];
    }
    const float dx = at[0] - pos[0];
    const float dz = at[2] - pos[2];
    r.horizontal_m = std::sqrt(dx * dx + dz * dz);
    r.up_m = at[1] - pos[1];
    return r;
}

// bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_SKINNED: 0 (default) a lone skinned cut-out casts a lamp shadow when it has at most
// BB_RT_CARD_LAMP_BONES bones, 1 every one (r62m), 2 none (rt_card_skinned.h). With r84's knobs file present it is asked again at every change of
// the file (a test flips it in one running game); without, the environment's value at the first call.
CardSkinnedMode RtShadow::CardSkinnedModeNow() {
#ifdef BB_R62N_LIVE_KNOBS
    static BbLiveKnobs::Knob<u32> knob{"BB_RT_CARD_LAMP_SKINNED",
                                       [](const char* text) -> u32 { return u32(CardSkinnedModeOf(text)); }};
    return static_cast<CardSkinnedMode>(knob.Get());
#else
    static const CardSkinnedMode mode = CardSkinnedModeOf(std::getenv("BB_RT_CARD_LAMP_SKINNED"));
    return mode;
#endif
}

// BB_RT_CARD_LAMP_BONES: read once (1 to 341, default 24).
u32 RtShadow::CardSkinnedBonesNow() {
    static const u32 bones = CardSkinnedBonesOf(std::getenv("BB_RT_CARD_LAMP_BONES"));
    return bones;
}

// bbport (r62n_cutout-skinned-blocker) FEATURE: every 600 frames while the lamp rays read the cards: the lone skinned cut-out cards the rule
// judged in the last scene, how many it let cast lamp shadows, and by bones (at most 24, 25 to 48, 49 to 96, more or none read). Said once at
// the first call. Nothing runs without BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1.
void RtShadow::CardSkinnedLog() {
    if (!card_layers_on || !CardLampsWanted()) {
        return;
    }
    const CardSkinnedMode mode = CardSkinnedModeNow();
    if (!card_skinned_said) {
        card_skinned_said = true;
        std::printf("Foliage lamp shadows (r62n): lone skinned cut-out cards: BB_RT_CARD_LAMP_SKINNED=%u (%s), BB_RT_CARD_LAMP_BONES=%u: a lone "
                    "skinned card (no sun shadow pass draws it) casts a lamp shadow when it has at most that many bones; a skinned card that is not "
                    "lone never does (r62e); the line 'Foliage lamp shadows (r62n) skinned' counts them every 600 frames\n",
                    unsigned(mode),
                    mode == CardSkinnedMode::All    ? "every lone skinned card casts, as r62m"
                    : mode == CardSkinnedMode::None ? "none casts"
                                                    : "a lone skinned card with few bones casts",
                    CardSkinnedBonesNow());
    }
    const CardSkinnedScene& s = card_skinned_now;
    std::printf("Foliage lamp shadows (r62n) skinned: %u lone skinned cut-outs judged in the last scene, %u let cast lamp shadows (mode %u, at most "
                "%u bones); by bones %u up to 24, %u of 25 to 48, %u of 49 to 96, %u more or none read\n",
                s.judged, s.allowed, unsigned(mode), CardSkinnedBonesNow(), s.bins[0], s.bins[1], s.bins[2], s.bins[3]);
}

// bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry (one with card
// UV data: a cut-out draw of it was seen) whose pixel shader does not discard, or that has none
// (the judge inferred 2 hair or cloth entries with only a camera card): the game's sun shadow of
// it is solid, whatever its card says. The entry keeps that for good (the row's
// CARD_ROW_SUN_SOLID, for stages 5 and 6) and is printed once (its key remembered).
void RtShadow::CardNoteSunSolid(Entry& entry, const Draw& draw) {
    CardUvEntry& c = *entry.card_uv;
    c.sun_solid_ps = draw.pixel_shader;
    if (c.sun_solid) {
        return;
    }
    c.sun_solid = true;
    if (card_solid_said >= CardBothLines ||
        !card_said.insert(CardSaidKey(entry.base, CardSaid::SunSolid, false)).second) {
        return;
    }
    ++card_solid_said;
    const bool has_card = c.uv.state != CardUvState::NotCard;
    std::printf("Ray tracing card UVs (r62b): sun shadow pass draw without a cut-out, key %016llx "
                "(%s): pixel shader %016llx (0: none) does not discard, so the game's sun shadow "
                "of it is solid; the entry's card: %s ps %016llx, reference %.6g; row bit "
                "SUN_SOLID (stages 5 and 6 keep it solid for the sun)\n",
                static_cast<unsigned long long>(entry.base), CardClassNow(entry),
                static_cast<unsigned long long>(draw.pixel_shader),
                !has_card ? "none yet," : c.uv.card.camera ? "camera pass" : "sun shadow pass",
                static_cast<unsigned long long>(has_card ? c.uv.card.ps_hash : 0),
                double(has_card ? c.uv.card.reference : 0.0f));
}

// Whether a capture of the entry by this draw may store its UVs now: they are wanted, the ring
// was filled once (card_ring_clean), the draw is one of the card's own (its pixel shader and the same
// coordinates, so the same vertex shader outputs) and stores the entry's instances (Param), the
// ring and the frame's budget have room, and the entry has a block of the pool (taken here when
// it has none). Nothing is set yet.
bool RtShadow::CardCaptureCan(Entry& entry, const Draw& draw) {
    // bbport (r62d_card-uv-diag): BB_RT_CARD_UV_DIAG=1 or 2: never (no capture, no probe, so
    // no expand pass)
    if (card_diag == 1 || card_diag == 2) {
        return false;
    }
    if (!card_uv_ready || !card_ring_clean || !entry.card_uv || !need_scene) {
        return false;
    }
    // bbport (r62e_leaf-cards-usable): a cut-out with a skeleton not taken for still (not lone),
    // or a moving rigid one, never gets card UVs (rt_card_still.h); BB_RT_CARD_SAFE=0: as before
    if (CardSafeOn()) {
        const CardStillWhy why =
            CardStillOf(entry.skinned, entry.lone == LampLoneState::Lone, entry.dynamic);
        if (why != CardStillWhy::Still) {
            ++(why == CardStillWhy::Skinned ? card_safe.refused_skinned : card_safe.refused_moving);
            return false;
        }
    }
    CardUvEntry& c = *entry.card_uv;
    if (!CardCaptureWanted(c.uv, card_pool_gen) || c.taken_frame == frame) {
        return false;
    }
    const CardDraw* d = draw.card;
    if (!d || !d->valid || d->ps_hash != c.uv.card.ps_hash || d->uv_hash != c.uv.card.uv_hash ||
        draw.first_instance != entry.first_instance) {
        ++card_uv_stats.other_draw;
        return false;
    }
    if (!CardRingFits(card_ring_used, u64(entry.vertices) * entry.instances, card_captures)) {
        ++card_uv_stats.budget;
        return false;
    }
    return c.block || CardTakeBlock(entry);
}

// The capture of `build` (a param of its own) stores the entry's UVs (CardCaptureCan said yes):
// the param's word 1 (the ring index + 1) and word 7 (the selector) are set, and build.uv_base,
// uv_hash.
void RtShadow::CardCaptureTake(Entry& entry, const Draw& draw, Build& build) {
    CardUvEntry& c = *entry.card_uv;
    const u64 stored = u64(entry.vertices) * entry.instances;
    build.uv_base = card_ring_used + 1;
    build.uv_hash = draw.card->uv_hash;
    auto* words = static_cast<u32*>(params.mapped) + std::size_t(build.param) * 8;
    words[1] = build.uv_base;
    words[7] = draw.card->selector;
    card_ring_used += u32(stored);
    card_ring_peak = std::max(card_ring_peak, card_ring_used);
    ++card_captures;
    ++card_uv_stats.captures;
    c.taken_frame = frame;
}

// The capture of `build` (its param, made for the build or r47's look) also stores the entry's
// UVs where CardCaptureCan says so. False for none (words 1 and 7 stay 0).
bool RtShadow::CardCapture(Entry& entry, const Draw& draw, Build& build) {
    if (build.param == 0 || !CardCaptureCan(entry, draw)) {
        return false;
    }
    CardCaptureTake(entry, draw, build);
    return true;
}

// A capture for the UVs alone, of an entry that waited CardWaitFrames frames drawn without one
// (a caster built before its card data was there, held for still, drawn by a sun shadow pass
// first on every frame): a probe (Build::probe and uv_only, no signature) that builds and copies
// nothing. Every check comes before its param is taken, so a refused one costs no param; it
// takes params and positions only within the first half of the frame's (CardUvProbeFits), so
// the builds after it keep the rest. Returns its param, 0 for none (the draw then stores
// nothing).
u32 RtShadow::CardUvProbe(Entry& entry, const Draw& draw) {
    if (!card_uv_ready || !entry.card_uv || !need_scene || r26_freeze != 0) {
        return 0;
    }
    const CardUvEntry& c = *entry.card_uv;
    if (!CardUvOnlyDue(c.uv, card_pool_gen) || c.taken_frame == frame || !draw.card ||
        !draw.card->valid || draw.card->ps_hash != c.uv.card.ps_hash ||
        draw.card->uv_hash != c.uv.card.uv_hash) {
        return 0;
    }
    const u64 stored = u64(entry.vertices) * entry.instances;
    if (!CardUvProbeFits(params_used, MaxParams, positions_used, stored, MaxPositions)) {
        ++card_uv_stats.budget;
        return 0;
    }
    if (!CardCaptureCan(entry, draw)) {
        return 0;
    }
    Build probe{&entry, positions_used, false, {}};
    probe.probe = true;
    probe.uv_only = true;
    probe.param = Param(positions_used, entry);
    if (probe.param == 0) {
        return 0; // not reached: CardUvProbeFits left params
    }
    CardCaptureTake(entry, draw, probe);
    builds.push_back(probe);
    positions_used += u32(stored);
    ++card_uv_stats.uv_probes;
    return probe.param;
}

// bbport (r62e_leaf-cards-usable): BB_RT_CARD_SAFE, read once. 0: r62e's still rule and guard are off
// (the cut-out shadows as r62c, r62b and r63 left them, to compare in one build); unset or anything
// else: on. Read only with BB_RT_CARD_ALPHA on (CardGuardSetup, CardCaptureCan, CardStillFor).
bool RtShadow::CardSafeOn() {
    static const bool on = [] {
        const char* const env = std::getenv("BB_RT_CARD_SAFE");
        return !(env && std::strcmp(env, "0") == 0);
    }();
    return on;
}

// bbport (r62e_leaf-cards-usable): whether an entry of the lamp card set (PrepareScene,
// BB_RT_CARD_LAMPS=1) may carry CARD_LAMP_MASK by what it is: a still cut-out (CardStillOf)
// whose copy is not stale (an old pose) and was not stale within CardLampHoldFrames
// (CardStaleHoldOff). Counted for CardSafeLog. BB_RT_CARD_SAFE=0, or no card data (CardLampOn
// then says no anyway): r63's rule, not stale.
bool RtShadow::CardStillFor(Entry& entry, bool stale) {
    if (!CardSafeOn() || !entry.card_uv) {
        return !stale;
    }
    const CardStillWhy why =
        CardStillOf(entry.skinned, entry.lone == LampLoneState::Lone, entry.dynamic);
    card_safe_now.skinned += why == CardStillWhy::Skinned ? 1 : 0;
    card_safe_now.moving += why == CardStillWhy::Moving ? 1 : 0;
    if (why != CardStillWhy::Still) {
        return false;
    }
    ++card_safe_now.still;
    const bool on = CardStaleHoldOff(stale, frame, entry.card_uv->lamp_stale, CardLampHoldFrames);
    card_safe_now.stale_off += on ? 0 : 1;
    return on;
}

// bbport (r62e_leaf-cards-usable): the guard's pass and counts (BB_RT_CARD_ALPHA on, at setup), and
// the knob's line, once.
void RtShadow::CardGuardSetup() {
    using enum vk::DescriptorType;
    if (!CardSafeOn()) {
        std::printf("Ray traced lamps (r62e): cut-out shadows (true shape): BB_RT_CARD_SAFE=0: the "
                    "still rule and the guard are off (the cut-outs as r63 left them)\n");
        return;
    }
    card_guard_on =
        EffectPass::Create(instance, guard_set, guard_layout, guard_pipeline,
                           {eStorageBuffer, eStorageBuffer}, sizeof(CardGuardPush),
                           RT_CARD_GUARD_COMP, "Cut-out shadows guard") &&
        Make(card_guard, vk::DeviceSize(CardGuardWords) * 4, true,
             VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
        card_guard.mapped;
    if (card_guard_on) {
        std::memset(card_guard.mapped, 0, std::size_t(CardGuardWords) * 4);
    } else {
        Free(card_guard);
    }
    std::printf("Ray traced lamps (r62e): cut-out shadows (true shape), BB_RT_CARD_ALPHA=%u: a "
                "cut-out (a draw whose pixel shader discards by a texture's alpha: leaves, a "
                "lantern's hook, a grille, a chain) stores card UVs, and with BB_RT_CARD_LAMPS=1 "
                "casts its true shape in lamp shadows, only while still (no skeleton and never "
                "moved, or a skeleton no sun shadow pass draws) and not a stale copy (nor within "
                "120 frames of one); guard %s (a cut-out's build with a corner that is not a "
                "number, a vertex past its own or an edge over %g m is dropped from the scene); "
                "BB_RT_CARD_SAFE=0 turns this off\n",
                Shader::Optimization::CardAlphaLevel(),
                card_guard_on ? "on" : "wanted but off - no pipeline or buffer", double(CardGuardEdge));
}

// bbport (r62e_leaf-cards-usable): every 600 frames with BB_RT_CARD_ALPHA on: the lamp card set of the
// last record write by rule, the card mask's first turn-ons and flips, the card UVs refused, and the
// guard (its GPU counts are read as the GPU left them: a frame or two late).
void RtShadow::CardSafeLog() {
    if (!card_uv_on) {
        return;
    }
    const auto* w = card_guard_on ? static_cast<const u32*>(card_guard.mapped) : nullptr;
    std::array<u32, 4> now{};
    char keys[CARD_GUARD_RECORDS * 18 + 1] = "";
    float longest = 0.0f;
    if (w) {
        now = {w[CARD_GUARD_W_DROPPED], w[CARD_GUARD_W_BAD], w[CARD_GUARD_W_NOT_FINITE],
               w[CARD_GUARD_W_RECORDS]};
        std::memcpy(&longest, &w[CARD_GUARD_W_LONGEST], sizeof(longest));
        std::size_t at = 0;
        for (u32 i = 0; i < std::min<u32>(now[3], CARD_GUARD_RECORDS); ++i) {
            const u64 key = u64(w[CARD_GUARD_W_FIRST_RECORD + 2 * i]) |
                            (u64(w[CARD_GUARD_W_FIRST_RECORD + 2 * i + 1]) << 32);
            at += std::size_t(std::snprintf(keys + at, sizeof(keys) - at, " %016llx",
                                            static_cast<unsigned long long>(key)));
        }
    }
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    // The counts a test reads first (the slot worker keeps 300 characters of a line)
    std::printf("Ray traced lamps (r62e): 600 frames: card mask flips %llu (first turn-ons %llu); "
                "guard %s dropped %u builds (%u bad triangles, %u not a number or past the vertices; "
                "%u since the start) of %llu checked (%llu unchecked, over %u a call); lamp card set "
                "of the last write %u still, left out %u with a skeleton not taken for still, %u "
                "moving rigid, %u stale copies held off; card UVs refused %llu with a skeleton, %llu "
                "moving; longest finite bad edge %.4g m; first dropped keys:%s\n",
                ull(card_safe.flips), ull(card_safe.first_on), card_guard_on ? "on" : "off",
                now[0] - card_guard_last[0], now[1] - card_guard_last[1],
                now[2] - card_guard_last[2], now[0], ull(card_safe.guarded),
                ull(card_safe.unguarded), CardGuardSlots, card_safe_now.still,
                card_safe_now.skinned, card_safe_now.moving, card_safe_now.stale_off,
                ull(card_safe.refused_skinned), ull(card_safe.refused_moving), double(longest),
                now[3] != 0 ? keys : " none");
    card_guard_last = now;
    card_safe = {};
}

// bbport (r62d_card-uv-diag): the knob's line, and the geometry check's pass and buffers
// (BB_RT_CARD_UV_DIAG not 0, or BB_RT_GEOMETRY_CHECK=1). Without them nothing is checked.
void RtShadow::GeoCheckSetup() {
    using enum vk::DescriptorType;
    card_diag = Shader::Optimization::CardUvDiag();
    const bool wanted = card_diag != 0 || GeoCheckKnob();
    if (!wanted) {
        return;
    }
    geo_huge = GeoCheckEdge();
    geo_on = EffectPass::Create(instance, geo_set, geo_layout, geo_pipeline,
                                {eStorageBuffer, eStorageBuffer}, sizeof(GeoCheckPush),
                                RT_GEOMETRY_CHECK_COMP, "Ray tracing geometry check") &&
             Make(geo_buffer, GeoCheckWords * 4, false,
                  VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
             Make(geo_readback, GeoCheckWords * 4, true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
             geo_readback.mapped;
    if (geo_on) {
        std::memset(geo_readback.mapped, 0, GeoCheckWords * 4);
        geo_time = GeoCheckNowMs();
        geo_infos.reserve(4096);
    } else {
        Free(geo_buffer);
        Free(geo_readback);
    }
    static constexpr const char* What[] = {
        "as before",
        "no card UV capture, no UV-only probe, no expand pass; capture pipelines keep the card "
        "UVs (recompiler vertex shaders)",
        "no card UV capture, probe or expand pass, and no capture pipeline has the card UVs "
        "(lifter vertex shaders, as with BB_RT_CARD_ALPHA=0)",
        "fix A: an execution barrier from each call's BLAS builds and copies to later vertex "
        "shaders and compute passes; captures as before",
        "fix B: the card UVs only on capture pipelines whose pixel shader discards (the others "
        "are the lifter's); captures as before",
        "fixes A and B"};
    std::printf("Ray tracing card UV diagnosis (r62d): BB_RT_CARD_UV_DIAG=%u: %s; BB_RT_CARD_ALPHA "
                "level %u; geometry check %s (edges over %g m and %g m counted, a line every %llu "
                "frames or %llu s)\n",
                card_diag, What[card_diag < 6 ? card_diag : 0],
                Shader::Optimization::CardAlphaLevel(),
                geo_on ? "on" : "wanted but off - no pipeline or buffer", double(geo_huge),
                double(geo_huge / 8.0f), static_cast<unsigned long long>(GeoCheckFrames),
                static_cast<unsigned long long>(GeoCheckMs / 1000));
}

// bbport (r62d_card-uv-diag): the open window becomes the one whose copy is awaited (from the
// tick recorded now), and a new window starts.
void RtShadow::GeoCheckTakeWindow(u64 now) {
    geo_pending = true;
    geo_tick = scheduler.CurrentTick();
    geo_read.swap(geo_infos);
    geo_infos.clear();
    geo_read_window = geo_window;
    geo_read_window.frames = frame - geo_frame;
    geo_window = {};
    geo_frame = frame;
    geo_time = now;
}

// bbport (r62d_card-uv-diag): a window's counts, once the GPU is past their copy (asked once a
// frame while one is awaited; no wait). The records name the builds by their serial. A window
// that is due while no RecordBuilds call came to copy it (no BLAS built or refit since: a still
// stretch, or the last calls of a loading burst) is copied here on its own; one without any
// call says so on the host alone.
void RtShadow::GeoCheckFrameEnd() {
    if (!geo_on) {
        return;
    }
    if (geo_pending && scheduler.IsFree(geo_tick)) {
        geo_pending = false;
        GeoCheckPrint();
    }
    if (geo_pending) {
        return;
    }
    const u64 now = GeoCheckNowMs();
    if (frame < geo_frame + GeoCheckFrames && now < geo_time + GeoCheckMs) {
        return;
    }
    if (geo_window.calls == 0 || !geo_clean) {
        std::printf("Ray tracing geometry check (r62d, BB_RT_CARD_UV_DIAG=%u, BB_RT_CARD_ALPHA=%u): "
                    "%llu frames, 0 calls: no BLAS built or refit, nothing checked\n",
                    card_diag, Shader::Optimization::CardAlphaLevel(),
                    static_cast<unsigned long long>(frame - geo_frame));
        geo_infos.clear();
        geo_window = {};
        geo_frame = frame;
        geo_time = now;
        return;
    }
    GeoCheckTakeWindow(now);
    scheduler.EndRendering();
    scheduler.Record([counts = geo_buffer.buffer, readback = geo_readback.buffer](
                         vk::CommandBuffer cmdbuf) { GeoCheckFlush(cmdbuf, counts, readback); });
}

// bbport (r62d_card-uv-diag): the line of the window whose copy the GPU is past
void RtShadow::GeoCheckPrint() {
    const auto* w = static_cast<const u32*>(geo_readback.mapped);
    const auto metres = [](u32 bits) { return double(std::bit_cast<float>(bits)); };
    const GeoCheckWindow& g = geo_read_window;
    std::printf("Ray tracing geometry check (r62d, BB_RT_CARD_UV_DIAG=%u, BB_RT_CARD_ALPHA=%u): "
                "%llu frames, %llu calls, %llu BLAS inputs (%llu refits) of %llu triangles sent, "
                "%u checked; index out of range %u, not finite %u, longest edge over %g m %u, "
                "over %g m %u; longest finite edge %.4g m; %u bad records\n",
                card_diag, Shader::Optimization::CardAlphaLevel(),
                static_cast<unsigned long long>(g.frames), static_cast<unsigned long long>(g.calls),
                static_cast<unsigned long long>(g.builds), static_cast<unsigned long long>(g.refits),
                static_cast<unsigned long long>(g.triangles), w[0], w[1], w[2], double(geo_huge),
                w[3], double(geo_huge / 8.0f), w[4], metres(w[5]), w[6]);
    const u32 records = std::min(w[6], GeoCheckRecords);
    std::array<u32, GeoCheckLines> said{};
    u32 lines = 0;
    for (u32 r = 0; r < records && lines < GeoCheckLines; ++r) {
        const u32* rec = w + 8 + 4 * r;
        const u32 serial = rec[0];
        if (std::find(said.begin(), said.begin() + lines, serial) != said.begin() + lines) {
            continue;
        }
        said[lines++] = serial;
        if (serial >= geo_read.size()) {
            std::printf("Ray tracing geometry check (r62d): bad build (not named, serial %u): %u "
                        "out of range or not finite, %u over %g m, longest %.4g m (one workgroup)\n",
                        serial, rec[1], rec[2], double(geo_huge), metres(rec[3]));
            continue;
        }
        const GeoCheckInfo& i = geo_read[serial];
        const u32 f = i.flags;
        std::printf("Ray tracing geometry check (r62d): bad build: key %016llx vs %016llx, %u "
                    "triangles, %s%s, mask%s%s, %s%s%s%s%s%s%s; %u out of range or not finite, %u "
                    "over %g m, longest %.4g m (one workgroup)\n",
                    static_cast<unsigned long long>(i.key),
                    static_cast<unsigned long long>(i.vs_hash), i.triangles,
                    (f & 1u) ? "refit" : "built", (f & 2u) ? " fast" : "",
                    (f & 4u) ? " camera" : "", (f & 8u) ? " sun" : "",
                    (f & 16u) ? "moving" : "not moving", (f & 32u) ? ", shared copy" : "",
                    (f & 64u) ? ", instance" : "", (f & 128u) ? ", skinned" : "",
                    (f & 256u) ? ", card" : "", (f & 512u) ? ", held" : "",
                    (f & 1024u) ? ", UV capture" : "", rec[1], rec[2], double(geo_huge),
                    metres(rec[3]));
    }
    geo_read.clear();
}

// Destroy: the block and slot are freed once the GPU is past what was recorded so far (an
// expand pass may still write the block).
void RtShadow::CardRelease(Entry& entry) {
    if (!entry.card_uv) {
        return;
    }
    CardUvEntry& c = *entry.card_uv;
    if (c.pending) {
        std::erase(card_pending, &entry);
    }
    if (c.block) {
        card_frees.push_back({std::bit_cast<u64>(c.block), c.slot, scheduler.CurrentTick()});
    }
    entry.card_uv.reset();
}

// At a frame's end: the frame's ring and budget start again, the expanded entries whose tick
// the GPU passed are Ready, and the blocks of destroyed entries it is done with are freed. The
// driver is asked once how far the GPU is (as ReadStillSigs' caller does); no wait. UV captures
// no RecordBuilds took (drawn after the frame's last one; OnFrameEnd drops their builds) wrote
// their part of the ring: card_ring_dirty keeps how far, and the next RecordBuilds fills that
// part too. (A capture of the next frame before that RecordBuilds may meet such a value at a
// vertex it does not store itself: a window this does not close.)
void RtShadow::CardFrameEnd() {
    card_ring_dirty = std::max(card_ring_dirty, card_ring_used);
    card_ring_used = 0;
    card_captures = 0;
    if (card_pending.empty() && card_frees.empty()) {
        return;
    }
    bool asked = false;
    const auto passed = [&](u64 tick) {
        const bool free = asked ? scheduler.GetWorkSemaphore()->IsFree(tick) : scheduler.IsFree(tick);
        asked = true;
        return free;
    };
    std::erase_if(card_pending, [&](Entry* e) {
        CardUvEntry& c = *e->card_uv;
        if (c.uv.state == CardUvState::Pending && !CardSettle(c.uv, passed(c.uv.tick))) {
            return false;
        }
        c.pending = false;
        return true;
    });
    CardReleaseFrees(card_frees, passed, [&](const CardFree& f) {
        const auto block = std::bit_cast<VmaVirtualAllocation>(f.block);
        VmaVirtualAllocationInfo info{};
        vmaGetVirtualAllocationInfo(card_block, block, &info);
        card_pool_used -= std::min<u64>(card_pool_used, info.size);
        card_pool_blocks -= card_pool_blocks != 0 ? 1 : 0;
        vmaVirtualFree(card_block, block);
        card_slots.Give(f.slot);
        ++card_pool_gen;
    });
}

// The 600-frame line (BB_RT_CARD_ALPHA=1): the cut-out entries by class (as BB_RT_LAMP_CARDS=3
// sees them) and state, which pass's card the entries both passes draw hold, the sun shadow pass
// cards no sun shadow pass draw gave again, the cards' constants (judge's items 3 and 7), why
// entries have no card data or a stale one, the pool, the draws since the last line; then the
// stat slots of the first entries expanded since, once the GPU is past them.
void RtShadow::CardLog() {
    if (!card_uv_on) {
        return;
    }
    constexpr std::size_t Classes = std::size_t(CardClass::Count);
    constexpr std::size_t States = std::size_t(CardUvState::Count);
    std::array<std::array<u32, States>, Classes> states{};
    std::array<u32, std::size_t(CardMiss::Count)> waiting{};
    std::array<u32, std::size_t(CardMiss::Count)> stale{};
    u64 ready_triangles = 0;
    u32 card_entries = 0;
    u32 both = 0, both_sun = 0, both_camera = 0, both_differ = 0, sun_gone = 0;
    u32 with_card = 0, fade = 0, second = 0, dithered = 0;
    u32 above_one = 0, above_step = 0, clear = 0, sun_solid = 0; // (r62b)
    // the least and greatest of the cards' reference dwords and dither coefficients (NaN: none)
    std::array<float, 6> range{NAN, NAN, NAN, NAN, NAN, NAN};
    const auto widen = [&range](std::size_t at, float v) {
        range[at] = std::isnan(range[at]) ? v : std::min(range[at], v);
        range[at + 1] = std::isnan(range[at + 1]) ? v : std::max(range[at + 1], v);
    };
    for (const auto& [key, e] : entries) {
        if (!e->card_uv) {
            continue;
        }
        const CardUvEntry& c = *e->card_uv;
        const bool has_card = c.uv.state != CardUvState::NotCard;
        sun_solid += c.sun_solid ? 1 : 0; // (r62b)
        if (c.uv.passes == 3) {
            ++both;
            both_sun += has_card && !c.uv.card.camera ? 1 : 0;
            both_camera += has_card && c.uv.card.camera ? 1 : 0;
        }
        both_differ += CardBothDiffer(c.uv) ? 1 : 0;
        sun_gone += CardSunGone(c.uv, frame) ? 1 : 0;
        if (has_card) {
            const CardDraw& d = c.uv.card;
            ++with_card;
            // bbport (r62b_leaf-stage3-followups): references above 1 (as read, never clamped)
            // and cards whose rule keeps no alpha in [0, 1]
            above_one += d.reference > 1.0f ? 1 : 0;
            above_step += d.reference > 1.0f + 1.0f / 255.0f ? 1 : 0;
            clear += CardRuleClear(d.op, d.reference, d.nonzero,
                                   d.dither && d.dither_scale != 0.0f, d.dither_scale)
                         ? 1
                         : 0;
            fade += d.fade_left_out ? 1 : 0;
            second += d.ref_dwords[1] != 0.0f ? 1 : 0;
            widen(0, d.ref_dwords[0]);
            widen(2, d.ref_dwords[1]);
            if (d.dither) {
                ++dithered;
                widen(4, d.dither_scale);
            }
        }
        const CardClass card_class = CardClassOf(e->skinned, e->lone == LampLoneState::Lone);
        ++states[std::size_t(card_class)][std::size_t(c.uv.state)];
        if (!has_card) {
            ++waiting[std::size_t(c.uv.miss)];
        } else if (CardStale(c.uv)) {
            ++stale[std::size_t(c.uv.miss)];
        }
        ready_triangles += c.uv.state == CardUvState::Ready ? e->triangles : 0;
        ++card_entries;
    }
    const u32 ring_peak = card_ring_peak;
    card_ring_peak = 0;
    if (card_entries == 0 && card_uv_stats.draws == 0) {
        return; // no cut-out entry and no cut-out draw: nothing to say
    }
    using ull = unsigned long long;
    const auto& s = card_uv_stats;
    const auto& m = s.miss;
    const auto cls = [&](CardClass k, CardUvState st) {
        return states[std::size_t(k)][std::size_t(st)];
    };
    using M = CardMiss;
    const auto why = [](const auto& count, M miss) { return ull(count[std::size_t(miss)]); };
    using enum CardUvState;
    std::printf(
        "Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=%u): %u cut-out entries [ready, pending, "
        "wanted, no room, no card data]: plants [%u, %u, %u, %u, %u], static [%u, %u, %u, %u, %u], "
        "skinned kept [%u, %u, %u, %u, %u]; drawn by both passes: %u (the card the sun shadow "
        "pass's %u, the camera pass's %u), %u with another reference in the camera pass; sun "
        "shadow pass cards not given again for more than %llu frames: %u; cards' constants: %u "
        "with a card, %u with the fade left out, %u with a second reference dword not 0, first "
        "reference dword %.6g to %.6g, second %.6g to %.6g, %u dithered with a coefficient %.6g "
        "to %.6g (taken as 0); no card data at the last draw: %llu no record, %llu a record of "
        "other resources, %llu not repeatable, %llu another permutation, %llu inputs, %llu "
        "constants, %llu image; a card but none at the last draw of its pass (stale): %llu no "
        "record, %llu a record of other resources, %llu not repeatable, %llu another "
        "permutation, %llu inputs, %llu constants, %llu image; pool %.1f of %llu "
        "MiB (%llu triangles in %u blocks, %llu ready); ring peak %u vertices (%.1f MiB); since "
        "the last line: %llu cut-out draws, %llu with card data (without: %llu no record, %llu a "
        "record of other resources, %llu not repeatable, %llu another permutation, %llu inputs, "
        "%llu constants, %llu image), %llu sun shadow pass cards given way to the camera pass's, "
        "%llu UV captures (%llu for the UVs alone), %llu expanded (%llu triangles; %llu dropped, "
        "the card changed), %llu from another draw, %llu over the frame's budget, %llu no room, "
        "%llu left out, %llu new coordinates, %llu other constants changed\n",
        Shader::Optimization::CardAlphaLevel(), // (r62) the level read
        card_entries, cls(CardClass::Plant, Ready), cls(CardClass::Plant, Pending),
        cls(CardClass::Plant, Wanted), cls(CardClass::Plant, NoRoom), cls(CardClass::Plant, NotCard),
        cls(CardClass::Static, Ready), cls(CardClass::Static, Pending),
        cls(CardClass::Static, Wanted), cls(CardClass::Static, NoRoom),
        cls(CardClass::Static, NotCard), cls(CardClass::SkinnedKept, Ready),
        cls(CardClass::SkinnedKept, Pending), cls(CardClass::SkinnedKept, Wanted),
        cls(CardClass::SkinnedKept, NoRoom), cls(CardClass::SkinnedKept, NotCard), both, both_sun,
        both_camera, both_differ, ull(CardSunFrames), sun_gone, with_card, fade, second,
        double(range[0]), double(range[1]), double(range[2]), double(range[3]), dithered,
        double(range[4]), double(range[5]), why(waiting, M::NoRecord),
        why(waiting, M::OtherResources), why(waiting, M::NotRepeatable),
        why(waiting, M::OtherPermutation), why(waiting, M::Inputs), why(waiting, M::Constants),
        why(waiting, M::Image), why(stale, M::NoRecord), why(stale, M::OtherResources),
        why(stale, M::NotRepeatable), why(stale, M::OtherPermutation), why(stale, M::Inputs),
        why(stale, M::Constants), why(stale, M::Image), double(card_pool_used) / 1048576.0,
        ull(CardPoolBytes >> 20), ull(card_pool_used / CARD_UV_RECORD_BYTES), card_pool_blocks,
        ull(ready_triangles), ring_peak, double(u64(ring_peak) * CARD_UV_RING_BYTES) / 1048576.0,
        ull(s.draws), ull(s.valid), why(m, M::NoRecord), why(m, M::OtherResources),
        why(m, M::NotRepeatable), why(m, M::OtherPermutation), why(m, M::Inputs),
        why(m, M::Constants), why(m, M::Image),
        ull(s.sun_gave_way), ull(s.captures), ull(s.uv_probes), ull(s.expanded),
        ull(s.expanded_triangles), ull(s.dropped), ull(s.other_draw), ull(s.budget),
        ull(s.no_room), ull(s.left_out), ull(s.coordinates), ull(s.constants));
    // bbport (r62b_leaf-stage3-followups): the judge's stage 3 items 1 and 2, and the once-only
    // lines printed so far
    std::printf("Ray tracing card UVs (r62b): cards' references: %u with a card, %u above 1 (%u "
                "above 1 + 1/255), %u fully clear (the rule keeps no alpha in [0, 1] at any dither: "
                "the reference is used as read, never clamped; rays drop every texel, the debug "
                "view draws them white); %u entries a sun shadow pass draws with a pixel shader "
                "that does not discard (their sun shadow is solid: row bit SUN_SOLID); once-only "
                "lines so far: %u both passes, %u second reference dword not 0, %u sun shadow pass "
                "draws without a cut-out (at most %u each)\n",
                with_card, above_one, above_step, clear, sun_solid, card_both_said, card_ref2_said,
                card_solid_said, CardBothLines);
    card_uv_stats = {};
    if (card_stat_used == 0 || !scheduler.IsFree(card_stat_tick)) {
        return; // none, or the GPU is not past them: the next line reads them
    }
    const auto* words = static_cast<const u32*>(card_readback.mapped);
    static constexpr std::array<const char*, Classes> ClassNames{"plant", "static", "skinned kept"};
    static constexpr std::array<char, 4> Comps{'x', 'y', 'z', 'w'};
    for (u32 i = 0; i < card_stat_used; ++i) {
        const CardStat st = CardReadStat(words + i * CARD_UV_STAT_WORDS);
        const CardStatInfo& info = card_stat_info[i];
        // bbport (r62b_leaf-stage3-followups): the class as the entry is now (found by its
        // pointer, compared only, and its key; "gone since" when `entries` no longer holds it),
        // the triangles marked NO_ALPHA, and the raw values at the first corners with the
        // output and components the selector named.
        const char* now = "gone since";
        for (const auto& [key, held] : entries) {
            if (held && held.get() == info.entry && held->base == info.base) {
                now = CardClassNow(*held);
                break;
            }
        }
        CardSelector sel;
        const bool factor = UnpackCardSelector(info.selector, sel) && sel.has_alpha;
        std::printf("Ray tracing card UVs (r54): first entries, %u: key %016llx, ps %016llx (%s "
                    "pass), %s, %u triangles: %s u %.4g to %.4g, v %.4g to %.4g, alpha factor "
                    "%.3g to %.3g (scaled, no offset or shift applied), %u with an alpha factor "
                    "outside [0, 1], %u with one off the 8-bit steps, %u wide, %u not "
                    "finite; (r62b) %s at expansion, %u marked NO_ALPHA, raw read-back at corners "
                    "1-4 (triangle 1's three, triangle 2's first) of vertex shader output %u: "
                    "alpha factor (.%c) %.9g, %.9g, %.9g, %.9g; other component (.%c) %.9g, %.9g, "
                    "%.9g, %.9g%s\n",
                    i + 1, ull(info.base), ull(info.ps_hash), info.camera ? "camera" : "sun shadow",
                    now, info.triangles,
                    st.any ? "" : "no finite corner;", double(st.umin), double(st.umax),
                    double(st.vmin), double(st.vmax), double(st.amin), double(st.amax),
                    st.alpha_range, st.alpha_rounded, st.wide, st.not_finite,
                    ClassNames[std::size_t(info.card_class)], st.no_alpha, sel.alpha_out,
                    Comps[sel.alpha_comp & 3u], double(st.raw_alpha[0]), double(st.raw_alpha[1]),
                    double(st.raw_alpha[2]), double(st.raw_alpha[3]),
                    Comps[Shader::MotionVectors::CaptureUvOther(sel.alpha_comp) & 3u],
                    double(st.raw_other[0]), double(st.raw_other[1]), double(st.raw_other[2]),
                    double(st.raw_other[3]),
                    factor ? "" : " (no alpha factor: the capture stored 1 and no other component)");
    }
    card_stat_used = 0;
}

// bbport (r62_leaf-stage3): the card table (BB_RT_CARD_ALPHA=2): CardRowsBytes, one row a card
// slot, made at the first PrepareScene with the knob, zeroed (no row READY). Device memory: rays
// read it; only changed rows are written, in stream order.
bool RtShadow::CardRowsMake() {
    if (card_rows.buffer) {
        return true;
    }
    if (card_rows_failed) {
        return false;
    }
    if (!Make(card_rows, CardRowsBytes, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)) {
        Free(card_rows);
        card_rows_failed = true;
        std::printf("Card alpha layers (r62): no card table (%llu bytes): no card has a row\n",
                    static_cast<unsigned long long>(CardRowsBytes));
        return false;
    }
    scheduler.EndRendering();
    scheduler.Record([rows = card_rows.buffer](vk::CommandBuffer cmdbuf) {
        cmdbuf.fillBuffer(rows, 0, CardRowsBytes, 0);
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite,
                                  vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
    return true;
}

// The rows of the entries this scene holds (drawn and held), at each PrepareScene: a row is
// written when it changed (its card state, its layer, its rule or its offset), at most
// CardRowUpdatesPerCall a call (the rest at the next call; counted). Recorded before the TLAS
// build and every ray of this call in stream order. An entry's first row being written changes
// its instance's custom index from 0 to its slot (CardCustomIndex) at the next TLAS write: at
// the latest the frame's next first PrepareScene (OnFrameEnd sets tlas_count to 0, so that one
// always writes the TLAS). No extra build is forced here: a second build in one frame writes
// the instance records into the same ring slot (frame % 4) the frame's earlier build may still
// be reading on the GPU. Until then the instance reads as not a card (custom index 0).
// A slot is the entry's for as long as its pool block (CardTakeBlock to CardRelease); a slot
// given to a new entry gets the new entry's row before its instance carries the slot.
void RtShadow::CardRows() {
    if (!CardRowsMake()) {
        return;
    }
    struct Update {
        u32 slot = 0;
        std::array<u32, CARD_ROW_WORDS> row{};
    };
    std::array<Update, CardRowUpdatesPerCall> updates{};
    u32 n = 0;
    const auto visit = [&](Entry* entry) {
        if (!entry || !entry->card_uv || entry->card_uv->slot == 0) {
            return;
        }
        CardUvEntry& c = *entry->card_uv;
        const auto row =
            CardPackRow(CardRowFor(c.uv, c.offset, entry->triangles, c.sun_solid)); // (r62b)
        if (c.row_written && row == c.row) {
            return;
        }
        if (n == updates.size()) {
            ++card_row_counts.deferred;
            return;
        }
        updates[n++] = {c.slot, row};
        c.row = row;
        c.row_written = true;
        ++card_row_counts.written;
        card_row_counts.ready += (row[2] & CARD_ROW_READY) != 0 ? 1 : 0;
    };
    for (Entry* entry : frame_entries) {
        visit(entry);
    }
    for (Entry* entry : held_now) {
        visit(entry);
    }
    if (n == 0) {
        return;
    }
    scheduler.EndRendering();
    scheduler.Record([updates, n, rows = card_rows.buffer](vk::CommandBuffer cmdbuf) {
        // After every earlier reader of the rows (rays recorded before).
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                                  vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite);
        for (u32 i = 0; i < n; ++i) {
            cmdbuf.updateBuffer(rows, vk::DeviceSize(updates[i].slot) * CARD_ROW_BYTES,
                                sizeof(updates[i].row), updates[i].row.data());
        }
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite,
                                  vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
}

// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS, read once. 1 with BB_RT_CARD_ALPHA=2: the lamp rays
// read the cut-out cards (PrepareScene, PointShadow's CARDS builds). Anything else: off, the scene
// and the lamp pass of before. Said once when the variable is set.
bool RtShadow::CardLampsWanted() {
    static const bool wanted = [] {
        const char* const env = std::getenv("BB_RT_CARD_LAMPS");
        // bbport (r131b_lrt-settings): a variable that is set and not empty decides (also "0" and text); else the setting
        // graphics_rt_foliage_shadows (the start copy) 1 or 2 turns it on. Neither: off, as with the variable unset.
        const int setting = BbSettings::Get().startup_rt_foliage_shadows;
        const bool from_env = EnvGiven(env);
        if (!from_env && setting < 1) {
            return false;
        }
        const bool one = CardLampsOf(env, setting);
        const bool layers = Shader::Optimization::CardAlphaLevel() == 2;
        char source[64];
        if (from_env) {
            std::snprintf(source, sizeof source, "BB_RT_CARD_LAMPS=%s", one ? "1" : "(not 1)");
        } else {
            std::snprintf(source, sizeof source, "the setting graphics_rt_foliage_shadows=%d", setting);
        }
        std::printf("Ray traced lamps (r63): %s: %s\n", source,
                    !one      ? "off (only 1 turns it on)"
                    : !layers ? "off - it needs BB_RT_CARD_ALPHA=2 (the alpha layers)"
                              : "the lamp rays cross a plant's or a static cut-out's card where the "
                                "game's alpha test drops its texel and stop where it keeps it "
                                "(characters, hair, cloth and the sun as before)");
        return one && layers;
    }();
    return wanted;
}

RtShadow::CardLampReaders RtShadow::CardLampReadersNow() const {
    if (!card_layers_on || !card_layers || card_lamp_instances == 0 || !CardLampsWanted()) {
        return {};
    }
    const auto layers = card_layers->ReaderBindings();
    return {card_rows.buffer, card_pool.buffer, layers.info, layers.layers, layers.sampler,
            card_lamp_instances, layers.colour}; // bbport (r131a_foliage-translucency): the colour layers
}

// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN, read once: exactly 1 turns on the sun side of the cut-out shadows (rt_card_sun.h). It needs
// the cards in the scene (BB_RT_CARD_ALPHA=2 with BB_RT_CARD_LAMPS=1: the lamp card path gives an instance CARD_LAMP_MASK) and is not made with
// BB_RT_GLASS_LIGHT (the sun trace's counter words 16 and up). Said once when the variable is set, with the reason when it stays off.
bool RtShadow::CardSunWanted() {
    static const bool wanted = [] {
        const char* const env = std::getenv("BB_RT_CARD_SUN");
        // bbport (r131b_lrt-settings): a variable that is set and not empty decides; else the setting 2 (lamps and sun).
        const int setting = BbSettings::Get().startup_rt_foliage_shadows;
        const bool from_env = EnvGiven(env);
        if (!from_env && setting < 2) {
            return false;
        }
        const bool one = CardSunOf(env, setting);
        const bool cards = one && CardLampsWanted();
        const bool glass = RtGlassLightOn();
        char source[96];
        if (from_env) {
            std::snprintf(source, sizeof source, "BB_RT_CARD_SUN=%.40s", env);
        } else {
            std::snprintf(source, sizeof source, "the setting graphics_rt_foliage_shadows=%d", setting);
        }
        std::printf("Ray traced sun cut-outs (r128c): %s: %s\n", source,
                    !one      ? "off (only 1 turns it on)"
                    : !cards  ? "off - it needs BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 (the cards in the scene)"
                    : glass   ? "off - it is not made with BB_RT_GLASS_LIGHT (the two share the sun trace's counter words)"
                              : "the sun's rays cross the cut-out cards where the game's alpha test drops the texel and stop where it "
                                "keeps it (rt_shadow.comp CARDS builds; the lamp rays' rule; a card within 3 cm of the ray's start is the "
                                "pixel's own surface)");
        return one && cards && !glass;
    }();
    return wanted;
}

// bbport (r128c_lrt-cutout-props) FEATURE: the cut-out build of the sun trace for this sun trace, or nothing (the plain build is pushed). While the
// knob is on the scene is told that a reader of the cards exists (NoteCardLampUser, as the lamp pass does) so that the cards take CARD_LAMP_MASK; the
// pipelines are made the first time (the full and the half form apart); nothing is returned while the live knob (test tools' knobs file) says off,
// the pipeline could not be made, or the scene holds no card with the mask yet (CardLampReadersNow).
RtShadow::CardSunUse RtShadow::CardSunNow(bool half) {
    CardSunUse use{};
    if (!CardSunWanted()) {
        return use;
    }
    NoteCardLampUser();
#ifdef BB_R62N_LIVE_KNOBS
    // bbport (r131b_lrt-settings): unset or empty in the knobs file is -1 (CardSunWanted decided: the variable or the setting), so the
    // setting's sun build runs in a slot build; "0" turns it off live, "1" on.
    static BbLiveKnobs::Knob<int> live{"BB_RT_CARD_SUN", [](const char* text) -> int { return CardSunLive(text); }};
    static bool told_on = true;
    const int live_value = live.Get();
    const bool on = live_value < 0 || live_value == 1;
    if (on != told_on) {
        told_on = on;
        std::printf("Ray traced sun cut-outs (r128c): the cut-out build is now %s (live)\n", on ? "on" : "off");
    }
    if (!on) {
        ++card_sun_plain;
        return use;
    }
#endif
    bool& tried = half ? card_sun_half_tried : card_sun_tried;
    if (!tried) {
        tried = true;
        using enum vk::DescriptorType;
        // bbport (r131a_foliage-translucency): with the light through leaves for the sun the FOLIAGE builds: bindings 10 (the colour layers) and 11
        // (the hue image) more, and the leaf share in the push constants
        const bool foliage = FoliageTranslucency::SunThrough();
        const bool made =
            foliage ? (half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,
                                                 {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                                  eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                                  eCombinedImageSampler, eCombinedImageSampler, eStorageImage},
                                                 sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_FOLIAGE_COMP},
                                                 "Ray traced shadows (cut-outs, leaves, half resolution)")
                            : EffectPass::Create(instance, card_sun_set, card_sun_layout, card_sun_pipeline,
                                                 {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                                  eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                                  eCombinedImageSampler, eCombinedImageSampler, eStorageImage},
                                                 sizeof(TracePush), std::span<const u32>{RT_SHADOW_CARDS_FOLIAGE_COMP},
                                                 "Ray traced shadows (cut-outs, leaves)"))
            : half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler},
                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_COMP},
                                      "Ray traced shadows (cut-outs, half resolution)")
                 : EffectPass::Create(instance, card_sun_set, card_sun_layout, card_sun_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler},
                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_CARDS_COMP},
                                      "Ray traced shadows (cut-outs)");
        std::printf("Ray traced sun cut-outs (r128c): the %s build %s\n", half ? "half resolution" : "full resolution",
                    made ? "made" : "could not be made: the sun trace runs its plain build");
    }
    const vk::Pipeline pipeline = half ? *card_sun_half_pipeline : *card_sun_pipeline;
    const auto readers = CardLampReadersNow();
    if (!pipeline || readers.instances == 0 || !readers.rows || !readers.pool || !readers.info || !readers.layers ||
        !readers.sampler) {
        ++card_sun_plain;
        return use;
    }
    // bbport (r131a_foliage-translucency): the FOLIAGE builds need the colour layers and the hue image
    if (FoliageTranslucency::SunThrough() && (!readers.colour || !MakeSunHue(raw_width, raw_height))) {
        ++card_sun_plain;
        return use;
    }
    ++card_sun_cards;
    use.pipeline = pipeline;
    use.layout = half ? *card_sun_half_layout : *card_sun_layout;
    use.rows = readers.rows;
    use.pool = readers.pool;
    use.info = readers.info;
    use.layers = readers.layers;
    use.sampler = readers.sampler;
    if (FoliageTranslucency::SunThrough()) { // bbport (r131a_foliage-translucency)
        use.foliage = true;
        use.colour = readers.colour;
        use.hue = sun_hue_view;
        use.hue_image = sun_hue_image;
    }
    return use;
}

// The mask's hold (CardLampHold): an entry's instance takes CardLampMask when its row has data
// and keeps it CardLampHoldFrames frames after (a row loses its data while its layer is filled
// again; its candidates are passed meanwhile, as without the bit), so that the TLAS is not built
// whole each time. Only an entry whose instance carries its slot (CardCustomIndex) can have it.
bool RtShadow::CardLampOn(Entry& entry) {
    if (!entry.card_uv || CardCustomIndex(entry) == 0) {
        return false;
    }
    CardUvEntry& c = *entry.card_uv;
    const bool ready = (c.row[2] & CARD_ROW_READY) != 0;
    if (ready) {
        c.lamp_ready_frame = frame;
    }
    const bool on = CardLampHold(c.lamp_on, ready, frame, c.lamp_ready_frame, CardLampHoldFrames);
    c.lamp_on = on; // (PrepareScene counts the changes of the bit written: lamp_written)
    return on;
}

void RtShadow::OnFrameEnd() {
    if (window_scene_active_serial) {
        window_scene_active_serial = 0;
    }
    if (roof_probe) {
        roof_probe->Poll(frame, !RayTracing() ? "RT off or unsupported" :
                               !need_scene ? "no natural RT scene requested" : nullptr);
    }
    if (!capturing) {
        return;
    }
    if (bottle_cold || bottle_failed.entry) {
        if (!BottleCaustic::On()) {
            bottle_failed = {};
            DiscardBottleCold();
        } else if (bottle_cold && (!BottleObserved() || bottle_recorded_frame != frame ||
                                  !BottleColdEligible(*bottle_entry) || BottleGeneration(*bottle_entry) != bottle_cold->endpoint)) {
            DiscardBottleCold();
        } else {
            ConsumeBottleSpan();
        }
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the game draws the window panes after
    // the frame's last reader of the scene (forward, after the sun's trace and the lamp pass), so
    // their captures would be dropped below (an entry is captured again at its next draw) and no
    // pane ever got a BLAS. While a pane's capture waits and the scene is wanted, the frame's
    // waiting captures are built here, as a later reader's PrepareScene builds them (with
    // BB_LAMP_FOG_SHAFTS), and CollectHeld carries the panes into the next frame's scene. Off:
    // nothing here.
    if ((RtGlassCarryOn() || (glass_light_mode != 0 && !glass_drawn.empty())) && need_scene && // bbport (r86b, r130g): or
        std::ranges::any_of(builds, [](const Build& b) {
            return !b.probe && !b.left_out && b.entry && RtGlassEntry(b.entry->mask);
        })) {
        scheduler.EndRendering();
        RecordBuilds();
        ++glass_late;
    }
    if (vsm) {
        vsm->OnFrameEnd();
    }
    need_scene = SceneWanted();
    // Frames whose casters were too incomplete for Complete(): the game's own shadows showed.
    stats.missed += missed;
    stats.incomplete += !frame_entries.empty() && missed * 4 > u32(frame_entries.size()) ? 1 : 0;
    for (const Build& build : builds) {
        // bbport (r47_still-check): its signature was never recorded; a probe left the entry
        // and its BLAS as they were
        if (build.sig != 0) {
            build.entry->still_wait -= build.entry->still_wait != 0 ? 1 : 0;
        }
        if (build.probe) {
            continue;
        }
        if (probe_on) { // bbport (r64b_surface-probe-more): no copy for the surface probe
            ProbeDropped(build);
        }
        InvalidateBottleGeometry(build.entry->address);
        if (reflection_tracker) {
            ReflectionDropCapture(build);
        }
        build.entry->built = build.entry->built && build.update;
        build.entry->r17_inputs = 0; // bbport (r17_rt-upkeep): its BLAS did not get this capture
    }
    builds.clear();
    if (stats.frames >= 600) {
        const double f = double(stats.frames);
        std::printf("Ray tracing: %.0f shadow + %.0f camera draws, %.0f instances, %.0f triangles a "
                    "frame; %zu BLAS; alpha %.1f, not ortho %.1f, no camera %.1f, unsupported %.1f, "
                    "many instances %.1f, over budget %.1f, moving %.1f, copies rebuilt %.1f, strips "
                    "%.1f, in both passes %.1f, cut-out characters %.1f, new triangles built %.0f, "
                    "evicted %.1f a frame; scene %.0f MB of %.0f; missed %.1f, kept casters %.1f "
                    "drawn %.1f culled %.1f verified a frame, %llu declared gone since the last line; "
                    "%llu prop instances promoted since the last line, %zu candidates; %llu frames "
                    "fell back to the game's shadows\n",
                    double(stats.draws) / f, double(stats.camera_draws) / f,
                    double(stats.instances) / f, double(stats.triangles) / f, entries.size(),
                    double(stats.alpha) / f, double(stats.not_ortho) / f, double(stats.no_camera) / f,
                    double(stats.unsupported) / f, double(stats.instanced) / f,
                    double(stats.over_budget) / f, double(stats.dynamic_draws) / f,
                    double(stats.shared_builds) / f, double(stats.strips) / f,
                    double(stats.merged) / f, double(stats.cut_characters) / f,
                    double(stats.built_triangles) / f, double(stats.evicted) / f,
                    double(blas_bytes) / 1048576.0, double(blas_limit) / 1048576.0,
                    double(stats.missed) / f, double(stats.vsm_kept) / f,
                    double(stats.vsm_culled) / f, double(stats.vsm_verified) / f,
                    static_cast<unsigned long long>(stats.vsm_gone),
                    static_cast<unsigned long long>(stats.promoted), candidates.size(),
                    static_cast<unsigned long long>(stats.incomplete));
        // bbport: what the shared entries are: copies of a mesh drawn more than once in a pass,
        // known by draw order and fully rebuilt within RebuiltBudget() triangles a frame, in turn
        // (r43_copy-turns; before, the first in draw order every frame; see PrepareDraw).
        u64 shared = 0, shared_triangles = 0, shared_moving = 0, shared_palette = 0,
            shared_camera = 0, shared_rebuilt = 0, shared_rebuilt_triangles = 0;
        // bbport (r41_lamp-shadows): moving copies left out of lamp rays for their old pose
        // (Entry::lamp_out), and the oldest moving copy's BLAS in frames.
        u64 shared_no_lamp = 0, shared_oldest = 0;
        u64 shared_oldest_still = 0; // bbport (r43_copy-turns)
        const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
        // bbport (r42_lamp-soft): the moving copies starved of rebuilds (Entry::lamp_out is kept
        // whatever BB_LAMP_SHADOW_STALE says), and the four of them with the most triangles.
        u64 shared_starved = 0;
        std::array<const Entry*, 4> starved{};
        std::unordered_set<u64> shared_meshes;
        for (const auto& item : entries) {
            const Entry* e = item.second.get();
            if (!e || !e->rebuilt || e->seen_frame != frame) {
                continue;
            }
            ++shared;
            shared_triangles += e->triangles;
            shared_moving += e->dynamic ? 1 : 0;
            shared_palette += e->palette != 0 ? 1 : 0;
            shared_camera += (e->mask & CameraMask) != 0 ? 1 : 0;
            shared_meshes.insert(e->base);
            if (e->built_frame == frame) {
                ++shared_rebuilt;
                shared_rebuilt_triangles += e->triangles;
            }
            // bbport (r43_copy-turns): the copies that do not move take turns too, four times
            // as slowly (CopyTurnStill): their oldest build, for the 600-frame line
            if (!e->dynamic) {
                shared_oldest_still = std::max(shared_oldest_still, frame - e->built_frame);
            }
            if (e->dynamic) { // bbport (r41_lamp-shadows)
                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
                shared_no_lamp += lamp_repair && e->lamp_out ? 1 : 0;
                if (e->lamp_out) { // bbport (r42_lamp-soft)
                    ++shared_starved;
                    const Entry* held = e;
                    for (const Entry*& slot : starved) {
                        if (!slot || held->triangles > slot->triangles) {
                            std::swap(slot, held);
                        }
                        if (!held) {
                            break;
                        }
                    }
                }
            }
        }
        // bbport (r43_copy-turns): whether the copies take turns, and the bound on the frames a
        // moving copy drawn every frame goes without a rebuild
        const bool turns = CopyTurnsOn();
        char turn_bound[96];
        if (turns && CopyWait() != 0) {
            std::snprintf(turn_bound, sizeof(turn_bound),
                          "the bound is %u, BB_RT_COPY_WAIT, kept while a frame's turns fit two "
                          "budgets",
                          CopyWait());
        } else {
            std::snprintf(turn_bound, sizeof(turn_bound), "%s",
                          turns ? "no bound: BB_RT_COPY_WAIT=0, the budget alone decides"
                                : "no bound without turns");
        }
        std::printf("Ray tracing: %.0f triangles refit a frame; shared copies drawn on the last "
                    "frame: %llu of %zu meshes, %llu triangles, %llu moving, %llu with a palette, "
                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u; %llu left out of lamp rays (oldest %llu frames); copies take turns: %s; "
                    "worst age of a moving copy since the last line: %u frames without a rebuild "
                    "while drawn every frame (%s), %u draws in a row without one for a copy drawn "
                    "again after frames undrawn; %.1f copies a frame were drawn again so; %llu "
                    "turns (%llu triangles) went past the budget; oldest build of a copy that "
                    "does not move: %llu frames; %llu moving copies "
                    "starved of rebuilds, %s (BB_LAMP_SHADOW_STALE=%d)%s",
                    double(stats.refit_triangles) / f, static_cast<unsigned long long>(shared),
                    shared_meshes.size(), static_cast<unsigned long long>(shared_triangles),
                    static_cast<unsigned long long>(shared_moving),
                    static_cast<unsigned long long>(shared_palette),
                    static_cast<unsigned long long>(shared_camera),
                    static_cast<unsigned long long>(shared_rebuilt),
                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget(),
                    static_cast<unsigned long long>(shared_no_lamp),
                    static_cast<unsigned long long>(shared_oldest),
                    turns ? "on (experiment 1152921504606846976 clear), the oldest build first"
                          : "off (experiment 1152921504606846976 set), the first in draw order as "
                            "before r43",
                    turn_stats.worst_run, turn_bound, turn_stats.worst_back_run,
                    double(turn_stats.back) / f,
                    static_cast<unsigned long long>(turn_stats.past),
                    static_cast<unsigned long long>(turn_stats.past_triangles),
                    static_cast<unsigned long long>(shared_oldest_still),
                    static_cast<unsigned long long>(shared_starved),
                    lamp_repair ? "left out of lamp rays" : "kept in lamp rays",
                    LampStaleOut() ? 1 : 0, starved[0] ? ", the largest:" : "");
        // bbport (r42_lamp-soft): which they are
        for (const Entry* e : starved) {
            if (!e) {
                break;
            }
            std::printf(" mesh %016llx, %u triangles, %s, built %llu frames ago;",
                        static_cast<unsigned long long>(e->mesh), e->triangles,
                        (e->mask & CameraMask) != 0 ? "in the camera pass" : "not in the camera pass",
                        static_cast<unsigned long long>(frame - e->built_frame));
        }
        std::printf("\n");
        // bbport (r46_lamp-cards): the cut-out cards among the instances of the scene last
        // built, and what each rule would leave out of them
        const bool cards_old = BbToggle::Experiment(LampCardsOldBit);
        static constexpr const char* card_rules[] = {
            "old (the sun pass's texture on a first draw, not while moving)",
            "1 (cut-outs without a skeleton)", "2 (every cut-out)",
            "3 (cut-outs without a skeleton, and those with one that no sun shadow pass draws)"};
        // bbport (r46b_plant-rule): the skinned cut-outs by what their vertices are taken for,
        // rule 3's count, and the map of position streams
        std::printf("Ray tracing cut-out cards (r46): rule %s (experiment 9223372036854775808 "
                    "%s, BB_RT_LAMP_CARDS=%u); on the last scene %u instances left out of lamp "
                    "rays as cut-out cards (%u known from the sun pass's texture, %u from their "
                    "own camera pass draw's discard, %u only from a camera pass draw of their "
                    "mesh that is not their own; %u with a bone palette, %u drawn by the camera "
                    "pass only, %u counted as moving, %u with a skeleton), %u skinned cut-outs "
                    "kept in lamp rays (%u whose vertices a sun shadow pass draws, %u not yet "
                    "%u frames without one); the old rule would leave out %u, rule 1 %u, rule 2 "
                    "%u, rule 3 %u; %zu cut-out meshes known, %zu by their key, %.2f entries a "
                    "frame looked themselves up among them; %zu position streams drawn with a "
                    "skeleton known, %.1f draws a frame went through them, a sun shadow pass "
                    "last drew a skeleton %lld frames ago (-1: never)%s",
                    card_rules[cards_old ? 0u : LampCardLevel()], cards_old ? "set" : "clear",
                    LampCardLevel(), card_stats.out, card_stats.by_shadow, card_stats.by_camera,
                    card_stats.by_mesh, card_stats.with_palette, card_stats.camera_only,
                    card_stats.moving, card_stats.skinned_out, card_stats.skinned_kept,
                    card_stats.sun_drawn, card_stats.lone_waiting, LampLoneFrames,
                    card_stats.rule_out[0], card_stats.rule_out[1], card_stats.rule_out[2],
                    card_stats.rule_out[3], cutout_meshes.size(), cutout_keys.size(),
                    double(card_lookups) / f, lone_streams.size(), double(lone_draws) / f,
                    sun_skinned_any ? static_cast<long long>(frame - sun_skinned_frame) : -1ll,
                    card_stats.largest[0].triangles != 0 ? "; the largest left out:" : "");
        lone_draws = 0;
        for (const CardFound& c : card_stats.largest) {
            if (c.triangles == 0) {
                break;
            }
            std::printf(" mesh %016llx (key %016llx), %u triangles, known from%s%s%s%s%s%s%s%s;",
                        static_cast<unsigned long long>(c.mesh),
                        static_cast<unsigned long long>(c.key), c.triangles,
                        c.by_shadow ? " [the sun pass's texture]" : "",
                        c.by_camera ? " [its camera pass draw]" : "",
                        c.by_mesh ? " [a camera pass draw of its mesh]" : "",
                        c.palette ? ", with a bone palette" : "",
                        c.instance ? ", an instance's own entry" : "",
                        c.moving ? ", counted as moving" : "",
                        c.camera_only ? ", drawn by the camera pass only" : "",
                        !c.skinned                        ? ""
                        : c.lone == LampLoneState::Lone   ? ", with a skeleton, its vertices in "
                                                            "no sun shadow pass"
                        : c.lone == LampLoneState::Sun    ? ", with a skeleton, its vertices in "
                                                            "a sun shadow pass"
                                                          : ", with a skeleton");
        }
        std::printf("\n");
        card_lookups = 0;
        // bbport (r47_still-check): the looks at the casters held for still since the last
        // line, and the casters that moved farthest between the capture their BLAS was built
        // from and a look: a caster built in a passing pose shows as one moved far at look 1,
        // two frames after that capture, with its bounds then and now.
        {
            const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
            static constexpr const char* still_modes[] = {"off", "count", "on"};
            const StillStats& s = still_stats;
            std::printf("Ray tracing still check (r47): BB_RT_STILL=%s (experiment "
                        "4611686018427387904 %s%s); a frame %.1f casters held for still captured "
                        "again (%.0f triangles; %.1f first looks after a build, %.1f other early "
                        "looks, %.1f in turn; budgets %u, %u and %u triangles), %.1f waited for "
                        "a budget (the longest wait of a look %llu frames; the casters due in "
                        "turn on the last frame need %u frames at the budget), %.2f found no "
                        "room, %.2f were drawn from another first instance; since the last line "
                        "%llu captures left out with their draw, %llu refit once because "
                        "nothing was known of the capture their BLAS held, %llu builds measured, "
                        "%llu signatures not usable, %llu looks found "
                        "a caster moving (%llu for the first time, %llu instance entries, %llu in "
                        "the camera pass, %llu against the other pass's capture), %llu of them "
                        "asked for a second look, %llu taken as moving from now on (found so "
                        "twice in a row), %llu not taken past the cap of %u triangles (%llu "
                        "held by living casters), %llu known from before and taken at their "
                        "first draw, %llu held for still again; %zu casters known to move; "
                        "tolerance %.4f m (%.2f m between the passes); lamp bit withheld by class "
                        "alone (BB_RT_LAMP_LEAVE=%u): %u instances on the last scene%s",
                        still_modes[StillMode()],
                        BbToggle::Experiment(StillCheckOldBit) ? "set" : "clear",
                        still_ready || StillMode() == StillOff ? "" : ", not ready",
                        // bbport (r47c_review-fixes): with the overdue looks in turn (lane 3)
                        double(s.probes[0] + s.probes[1] + s.probes[2] + s.probes[3]) / f,
                        double(s.probe_triangles) / f, double(s.probes[0]) / f,
                        double(s.probes[1]) / f, double(s.probes[2] + s.probes[3]) / f,
                        StillLane(true),
                        StillLane(true), StillLane(false), double(s.waited) / f,
                        u(s.longest_wait), StillCrowd(still_due_last, StillLane(false)),
                        double(s.no_room) / f, double(s.other_draw) / f, u(s.left_out),
                        u(s.refits), u(s.firsts), u(s.unread), u(s.found), u(s.found_new),
                        u(s.found_instance), u(s.found_camera), u(s.found_cross), u(s.doubted),
                        u(s.taken), u(s.not_taken), StillMoverCap(), u(still_mover_triangles),
                        u(s.known), u(s.taken_back), still_movers.size(), double(StillLimit()),
                        double(std::max(StillLimit(), StillCrossTolerance)), LampLeave(),
                        still_leave_count, s.largest[0].triangles != 0 ? "; moved farthest:" : "");
            std::array<StillFound, 4> largest = s.largest;
            std::ranges::sort(largest, [](const StillFound& a, const StillFound& b) {
                return a.moved > b.moved;
            });
            for (const StillFound& m : largest) {
                if (m.triangles == 0) {
                    break;
                }
                std::printf(" mesh %016llx (key %016llx), %u triangles, moved %.3f m at look %u, "
                            "%llu frames after the capture its BLAS was built from, box then "
                            "(%.3f %.3f %.3f)-(%.3f %.3f %.3f), now (%.3f %.3f %.3f)-(%.3f %.3f "
                            "%.3f), %s, by %s%s%s;",
                            u(m.mesh), u(m.key), m.triangles, double(m.moved), m.checks,
                            u(m.after), double(m.then[0]), double(m.then[1]), double(m.then[2]),
                            double(m.then[3]), double(m.then[4]), double(m.then[5]),
                            double(m.now[0]), double(m.now[1]), double(m.now[2]),
                            double(m.now[3]), double(m.now[4]), double(m.now[5]),
                            m.instance ? "an instance's own entry" : "known by draw order",
                            m.camera ? "a camera pass draw" : "a sun shadow pass draw",
                            m.cross ? " against the other pass's capture" : "",
                            m.taken ? ", taken as moving" : "");
            }
            std::printf("\n");
            // bbport (r47b_casters): how the props with a small bone palette are known, and
            // (BB_RT_STILL_LIST) every caster the looks found moving since the last line
            u64 instances = 0, placed = 0, placed_triangles = 0;
            for (const Entry* e : frame_entries) {
                instances += e->instance ? 1 : 0;
                if (e->instance && e->palette_placed) {
                    ++placed;
                    placed_triangles += e->triangles;
                }
            }
            std::printf("Ray tracing prop palettes (r47b): a frame %.1f draws with a small bone "
                        "palette, %.1f of them known by the palette's address (memory the GPU "
                        "wrote; experiment 4611686018427387904 set: all by their bytes); on the "
                        "last frame %llu instance entries drawn, %llu of them known by an "
                        "address (%llu triangles); %.2f instances a frame held in an earlier "
                        "frame's pose and left without the lamp bit\n",
                        double(s.palette_draws) / f, double(s.placed_draws) / f, u(instances),
                        u(placed), u(placed_triangles), double(s.placed_old_pose) / f);
            // bbport (r47c_review-fixes): the pace of the looks in turn, the held movers the
            // lamp bit was left to, the signs of an address the game uses again
            std::printf("Ray tracing review counters (r47c): the casters looked at in turn count "
                        "for %llu triangles (the most a frame drew of late; one the camera pass "
                        "does not draw for a quarter), at %u a frame a look of each every %u "
                        "frames at the least (64 where that is less); the look that waited "
                        "longest for a budget waited %llu frames (a caster of %llu triangles, "
                        "%s, drawn %llu frames after its draw before), %.2f looks a frame that "
                        "had waited %u frames or more were served from the second budget "
                        "(BB_RT_STILL_OVERDUE); %.2f held moving props known by an address a "
                        "frame kept the lamp bit (no other prop of their mesh drawn that frame); "
                        "%llu looks found a prop known by an address more than %.1f m from where "
                        "it was built with a box of the same size (its palette's address given "
                        "to another prop, or a prop carried whole); small palettes in memory the "
                        "GPU wrote are known by their %s (BB_RT_PALETTE_PLACE=%u); %llu position "
                        "streams drawn with a skeleton were bound with another size than before "
                        "(another mesh at the address: taken for new)\n",
                        u(still_pool_last), StillLane(false),
                        StillCrowd(still_pool_last, StillLane(false)), u(s.oldest_waiting),
                        u(s.oldest_triangles), s.oldest_near ? "near" : "not near",
                        u(s.oldest_gap), double(s.probes[3]) / f, StillOverdueFrames(),
                        double(s.placed_held) / f, u(s.placed_carried), double(StillCarried),
                        PalettePlace() && !BbToggle::Experiment(StillCheckOldBit) ? "address"
                                                                                  : "bytes",
                        PalettePlace() ? 1u : 0u, u(lone_resized));
            lone_resized = 0;
            if (StillListMost() != 0) {
                std::vector<const StillFound*> order;
                order.reserve(still_list.size());
                for (const auto& item : still_list) {
                    order.push_back(&item.second);
                }
                std::ranges::sort(order, [](const StillFound* a, const StillFound* b) {
                    return a->moved != b->moved ? a->moved > b->moved : a->id < b->id;
                });
                std::printf("Ray tracing still list (r47b): %zu casters found moving since the "
                            "last line (BB_RT_STILL_LIST=%u)\n",
                            order.size(), StillListMost());
                for (const StillFound* m : order) {
                    std::printf("still mover: mesh %016llx key %016llx tri %u moved %.3f m on "
                                "%u looks (look %u, %llu frames after the capture of its BLAS) "
                                "then (%.3f %.3f %.3f)-(%.3f %.3f %.3f) now (%.3f %.3f %.3f)-"
                                "(%.3f %.3f %.3f) size then (%.3f %.3f %.3f) now (%.3f %.3f "
                                "%.3f) %s, palette %s, %s, %s pass%s%s\n",
                                u(m->mesh), u(m->key), m->triangles, double(m->moved), m->finds,
                                m->checks, u(m->after), double(m->then[0]), double(m->then[1]),
                                double(m->then[2]), double(m->then[3]), double(m->then[4]),
                                double(m->then[5]), double(m->now[0]), double(m->now[1]),
                                double(m->now[2]), double(m->now[3]), double(m->now[4]),
                                double(m->now[5]), double(m->then[3] - m->then[0]),
                                double(m->then[4] - m->then[1]), double(m->then[5] - m->then[2]),
                                double(m->now[3] - m->now[0]), double(m->now[4] - m->now[1]),
                                double(m->now[5] - m->now[2]),
                                m->instance ? "instance entry" : "draw order",
                                !m->palette ? "none" : m->placed ? "by address" : "by bytes",
                                m->skinned ? "skinned" : "not skinned",
                                m->camera ? "camera" : "sun",
                                m->cross ? ", against the other pass's capture" : "",
                                m->taken ? ", taken as moving" : "");
                }
                still_list.clear();
            }
            still_stats = {};
        }
        stats = {};
        turn_stats = {}; // bbport (r43_copy-turns)
    }
    // bbport (r17_rt-upkeep): one line every 600 frames
    ++r17_stats.frames;
    if (frame % 600 == 0 && r17_stats.tlas_built + r17_stats.tlas_updated +
                                    r17_stats.tlas_skipped + r17_stats.world_computed +
                                    r17_stats.world_reused != 0) {
        const double f = double(r17_stats.frames);
        const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
        static constexpr const char* unchanged_names[] = {"off", "count", "skip"};
        std::printf("Ray tracing upkeep (r17): a frame %.1f meshes refit (%.0f triangles), %.1f "
                    "built (%.0f triangles), %.1f of them shared copies built fast (%.0f "
                    "triangles); unchanged inputs (BB_RT_UNCHANGED=%s): %.1f refits skipped (%.0f "
                    "triangles), %.1f refit although unchanged (%.0f triangles), %.1f not provable; "
                    "far only (every %u, 0 off; BB_RT_REFIT_EVERY or graphics_rt_far_refit): "
                    "%.1f refits skipped (%.0f triangles), %.1f "
                    "refit (%.0f triangles); TLAS over %llu frames: %llu built, %llu refit, %llu "
                    "skipped as unchanged; to-world %.0f computed, %.0f reused a frame; experiment "
                    "4398046511104 %s\n",
                    double(r17_stats.refit) / f, double(r17_stats.refit_triangles) / f,
                    double(r17_stats.rebuilt) / f, double(r17_stats.rebuilt_triangles) / f,
                    double(r17_stats.fast) / f, double(r17_stats.fast_triangles) / f,
                    unchanged_names[UnchangedMode()], double(r17_stats.same_skipped) / f,
                    double(r17_stats.same_skipped_triangles) / f, double(r17_stats.same_would) / f,
                    double(r17_stats.same_would_triangles) / f, double(r17_stats.same_unknown) / f,
                    RefitEvery(), double(r17_stats.far_skipped) / f,
                    double(r17_stats.far_skipped_triangles) / f, double(r17_stats.far_refit) / f,
                    double(r17_stats.far_refit_triangles) / f, u(r17_stats.frames),
                    u(r17_stats.tlas_built), u(r17_stats.tlas_updated), u(r17_stats.tlas_skipped),
                    double(r17_stats.world_computed) / f, double(r17_stats.world_reused) / f,
                    UpkeepOn() ? "clear (new)" : "set (old)");
    }
    if (frame % 600 == 0) {
        r17_stats = {};
        // bbport (r50_leaf-stage1): the pixel shaders' cut-out analysis so far, and the
        // cut-out cards' pixel shaders, with BB_RT_CARD_ALPHA_LOG=1.
        Shader::Optimization::PrintCutoutSummary();
        CardLog(); // bbport (r54_leaf-stage2): with BB_RT_CARD_ALPHA=1
        CardSafeLog(); // bbport (r62e_leaf-cards-usable): with BB_RT_CARD_ALPHA on
        CardSkinnedLog(); // bbport (r62n_cutout-skinned-blocker): with BB_RT_CARD_LAMPS=1
    }
    // The draw order entries of instances promoted this frame (their other cascades' copies, an
    // old pose's) would otherwise stay behind as duplicate kept casters.
    if (!promoted_now.empty()) {
        for (auto& item : entries) {
            Entry& e = *item.second;
            if (e.instance || e.dynamic || !e.palette || e.gone || e.seen_frame == frame) {
                continue;
            }
            const std::array<u64, 3> shadow_id{e.base, e.palette, 0u};
            const std::array<u64, 3> camera_id{e.base, e.palette, 1u};
            if (promoted_now.contains(XXH3_64bits(shadow_id.data(), sizeof(shadow_id))) ||
                promoted_now.contains(XXH3_64bits(camera_id.data(), sizeof(camera_id)))) {
                e.gone = true;
                if (auto* row = RoofWatchEntry(e)) {
                    row->now.hold_why = "marked-gone-by-existing-promotion";
                }
            }
        }
        promoted_now.clear();
    }
    if (frame % 60 == 0) {
        std::erase_if(candidates, [&](const auto& item) {
            return item.second.last + CandidateFrames < frame + 1;
        });
    }
    // bbport (r43_copy-turns): the next frame's turns, while frame_entries still holds this
    // frame's entries and before the evictions below (no pointer to an entry is kept past it)
    PlanCopyTurns();
    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    if (roof_probe) {
        roof_probe->WatchEnd(frame);
    }
    ++frame;
    if (BbWindHangProbe::On() && !wind_probe_done && ++wind_probe_frames >= 600 &&
        wind_probe_frames % 30 == 0) { // bbport (r112b_hang-probe, TOOL)
        WindHangProbeReport();
    }
    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: the r83b line every
    // RtGlassProbe::EveryFrames frames (rt_glass_probe.h). Off: one test of a static bool.
    if (RtGlassOn() && frame % RtGlassProbe::EveryFrames == 0) {
        RtGlassProbe::Line(frame);
    }
    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: the find lines (rt_glass_find.h). Off: one test.
    if (RtGlassFind::On()) {
        RtGlassFind::Report(frame, RtGlassAutoIndices(), RtGlassAutoMin());
        RtGlassFind::AreaReport(frame); // bbport (r86i_glint-find-gbuffer)
        GlassFindBox();                 // bbport (r86i_glint-find-gbuffer)
    }
    if (glass_tri) { // bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route's frame end
        GlassTriFrameEnd();
    }
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE set: true while the TLAS traced as it was
    // stays frozen (it holds BLAS addresses: no entry is destroyed). Unset: false, as before.
    if (frame % 600 == 0 && tlas_guard.writes != 0) { // bbport (r121_tlas-hang-guard)
        std::printf("Ray tracing scene guard (r121): %s: %llu TLAS writes, %llu of them after the first "
                    "of their frame (own ring slot), %llu of those with other references or count than "
                    "the write before (the hang's case), %llu dropped for want of a slot, %llu views "
                    "left no scene (not finite), %llu records without a BLAS address left out\n",
                    TlasGuardOn() ? "on" : "off (0)", static_cast<unsigned long long>(tlas_guard.writes),
                    static_cast<unsigned long long>(tlas_guard.later_writes),
                    static_cast<unsigned long long>(tlas_guard.later_differ),
                    static_cast<unsigned long long>(tlas_guard.ring_full),
                    static_cast<unsigned long long>(tlas_guard.bad_view),
                    static_cast<unsigned long long>(tlas_guard.no_address));
    }
    if (frame % 600 == 0 && tlas_live.checked != 0) { // bbport (r121c_tlas-unbound-read)
        std::printf("Ray tracing scene guard (r121c): %s: %llu instance records checked against the live BLAS "
                    "registry (%zu entries), dropped: %llu with an Entry that is not live, %llu with an address "
                    "other than the registered one, %llu without a handle; %llu BLAS freed while the TLAS last "
                    "built still held them (it is built afresh, the free waits for the GPU)\n",
                    TlasGuardOn() ? "on" : "off (0)", static_cast<unsigned long long>(tlas_live.checked),
                    entry_live.size(), static_cast<unsigned long long>(tlas_live.dangling),
                    static_cast<unsigned long long>(tlas_live.moved),
                    static_cast<unsigned long long>(tlas_live.no_handle),
                    static_cast<unsigned long long>(tlas_live.freed_in_tlas));
    }
    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();
    if (!r26_hold && (frame % 64 == 0 || blas_bytes > blas_limit - blas_limit / 8)) {
        const bool keep_casters = vsm && vsm->Ready() &&
                                  BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed);
        const auto protected_vsm = [&](const Entry& entry) {
            return keep_casters && frame - entry.seen_frame <= VsmKeepFrames && entry.shadow &&
                   !entry.dynamic && !entry.gone && entry.built && entry.copied && entry.world.buffer;
        };
        u64 keep_from = frame > UnusedFrames ? frame - UnusedFrames : 0;
        if (blas_bytes > blas_limit - blas_limit / 8) {
            u64 bytes = blas_bytes;
            const u64 target = blas_limit - blas_limit / 4;
            std::size_t at = 0;
            std::vector<std::pair<u64, u64>> aged;
            aged.reserve(entries.size());
            for (const auto& [key, entry] : entries) {
                if (!protected_vsm(*entry) && !entry->held) {
                    aged.emplace_back(entry->seen_frame, entry->scene_bytes);
                }
            }
            std::ranges::sort(aged);
            for (; at < aged.size() && bytes > target && aged[at].first + KeptFrames < frame; ++at) {
                bytes -= std::min(bytes, aged[at].second);
                keep_from = std::max(keep_from, aged[at].first + 1);
            }
        }
        ++r19_entries_gen; // bbport (r19_draw-cost): entries may be erased below
        std::erase_if(entries, [&](auto& item) {
            const Entry& entry = *item.second;
            if (entry.seen_frame >= keep_from || protected_vsm(entry) || entry.held) {
                return false;
            }
            Destroy(*item.second, entry.seen_frame + UnusedFrames < frame ?
                                          "cache-age-expiry" : "scene-memory-budget-eviction");
            ++stats.evicted;
            return true;
        });
    }
    if (!r26_hold && entry_bytes > MaxEntryBytes / 8 * 7) {
        std::vector<std::pair<u64, u64>> order;
        order.reserve(entries.size());
        for (const auto& [key, entry] : entries) {
            if (frame - entry->seen_frame > 2 && !entry->held) {
                order.emplace_back(entry->seen_frame, key);
            }
        }
        std::ranges::sort(order);
        for (const auto& [seen, key] : order) {
            if (entry_bytes <= MaxEntryBytes / 4 * 3) {
                break;
            }
            const auto it = entries.find(key);
            Destroy(*it->second, "entry-memory-budget-eviction");
            entries.erase(it);
            ++r19_entries_gen; // bbport (r19_draw-cost)
        }
    }
    const u32 slot = u32(frame % 4);
    if (slot_ticks[slot]) {
        scheduler.Wait(slot_ticks[slot]);
        slot_ticks[slot] = 0;
    }
    // bbport (r47_still-check): the signatures the GPU is done with are read, the oldest frame's
    // first: those of the ring slot the coming frame writes again (recorded four frames ago:
    // waited for like the capture params just above, which the GPU has long passed), and those
    // of the frames since whose tick the GPU has passed. No wait for these: the driver is asked
    // once how far the GPU is (the tick the scheduler knows is only as new as the last wait
    // anywhere), and only on a frame that has signatures to read; that answer serves the other
    // slots. An entry is not looked at again before its signature is read, so a late read
    // would put its first look off.
    bool asked = false;
    for (u32 age = 0; age < 4; ++age) {
        const u32 s = (slot + age) % 4;
        if (still_ticks[s] == 0) {
            continue;
        }
        if (age == 0) {
            scheduler.Wait(still_ticks[s]);
        } else {
            const bool passed = asked ? scheduler.GetWorkSemaphore()->IsFree(still_ticks[s])
                                      : scheduler.IsFree(still_ticks[s]);
            asked = true;
            if (!passed) {
                break;
            }
        }
        ReadStillSigs(s);
    }
    still_sig_used = 0;
    still_used = {};
    still_due_last = still_due;
    still_due = 0;
    still_pool_last = still_pool_peak.End(still_pool, frame); // bbport (r47c_review-fixes)
    still_pool = 0;
    CardFrameEnd(); // bbport (r54_leaf-stage2)
    GeoCheckFrameEnd(); // bbport (r62d_card-uv-diag)
    params_used = 0;
    positions_used = 0;
    scratch_used = 0;
    new_triangles = 0;
    rebuilt_triangles = 0;
    missed = 0;
    tlas_count = 0;
    frame_entries.clear();
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: this frame's pane keys, each once,
    // for the next frame's scene (CollectHeld). Off: both lists stay empty.
    if (RtGlassCarryOn() || glass_light_mode != 0) { // bbport (r86b_glass-visible; r130g_glass-light-forward): or BB_GLASS_GLINT on
        glass_carry.swap(glass_drawn);
        glass_drawn.clear();
        std::ranges::sort(glass_carry);
        const auto twice = std::ranges::unique(glass_carry);
        glass_carry.erase(twice.begin(), twice.end());
    }
    frame_cameras.clear();
    RtGlassStatic::FrameEnd(frame); // bbport (r121b_glass-pane-hang): the verdict counters, every 600 frames
    // bbport (r86f_glass-static-panes): the vote ends with the frame, its candidate too (a vote
    // that fell to 0 keeps its last pointer, which must not reach the next frame's panes)
    r86f_camera = nullptr;
    r86f_votes = 0;
    occurrences.clear();
    if (++occurrence_epoch == 0) { // 2^32 frames: slots of epoch 0 would read as this frame's
        occurrence_slots.fill(OccurrenceSlot{});
        occurrence_epoch = 1;
    }
}

// bbport (r64b_surface-probe-more): BB_SURFACE_PROBE=1, the rasterizer's own test.
bool RtShadow::ProbeWanted() {
    const char* value = std::getenv("BB_SURFACE_PROBE");
    return (value && value[0] == '1' && value[1] == '\0') || RtGlassTri::On(); // bbport (r86m): its world copy
}

// bbport (r86n_glint-aim-panes, TOOL): the slots' sizes. Knob off: every slot holds ProbeSlotVertices, in a row (the old layout).
// Knob on: the slots from ProbeSlotsSmall up hold ProbeBigSlotVertices each (the triangle route's: a big level mesh is copied whole).
u32 RtShadow::ProbeSlotLimit(u32 slot) {
    return RtGlassTri::On() && slot >= ProbeSlotsSmall ? ProbeBigSlotVertices : ProbeSlotVertices;
}

std::size_t RtShadow::ProbeSlotFirst(u32 slot) {
    if (!RtGlassTri::On() || slot <= ProbeSlotsSmall) {
        return std::size_t(slot) * ProbeSlotVertices;
    }
    return std::size_t(ProbeSlotsSmall) * ProbeSlotVertices + std::size_t(slot - ProbeSlotsSmall) * ProbeBigSlotVertices;
}

static_assert(RtShadow::ProbeBigSlotVertices == RtGlassTri::SlotVertices);

std::size_t RtShadow::ProbeWorldVertices() {
    return ProbeSlotFirst(ProbeSlots - 1) + ProbeSlotLimit(ProbeSlots - 1);
}

// bbport (r64b_surface-probe-more): the build's world positions (after the unproject pass) go to
// the probe's host slot with the world copies of RecordBuilds. Nothing else of the build changes.
bool RtShadow::ProbeCopyBuild(u32 build, u32 slot) {
    if (!probe_on || build == 0 || build > builds.size() || slot >= ProbeSlots) {
        return false;
    }
    Build& b = builds[build - 1];
    if (b.probe || b.left_out || !b.entry ||
        u64(b.entry->vertices) * b.entry->instances > ProbeSlotLimit(slot)) {
        return false;
    }
    if (!probe_world.buffer) {
        if (probe_world_failed) {
            return false;
        }
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = VkDeviceSize(ProbeWorldVertices()) * 16,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer raw{};
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw,
                            &probe_world.allocation, &info) != VK_SUCCESS ||
            !info.pMappedData) {
            if (raw) {
                vmaDestroyBuffer(instance.GetAllocator(), raw, probe_world.allocation);
            }
            probe_world = {};
            probe_world_failed = true;
            return false;
        }
        probe_world.buffer = raw;
        probe_world.mapped = info.pMappedData;
    }
    b.probe_slot = slot + 1;
    probe_ticks[slot] = 0;
    return true;
}

// bbport (r64b_surface-probe-more): the scene's entries as of this frame (before OnFrameEnd).
RtShadow::ProbeScene RtShadow::ProbeSceneNow(u32 skinned_most) {
    ProbeScene s;
    s.capturing = capturing;
    s.need_scene = need_scene;
    s.entries = entries.size();
    s.frame_entries = frame_entries.size();
    s.tlas_instances = tlas_count;
    s.blas_bytes = blas_bytes;
    s.blas_limit = blas_limit;
    for (const auto& [key, holder] : entries) {
        const Entry* e = holder.get();
        if (!e) {
            continue;
        }
        const bool drawn = e->seen_frame == frame;
        if (e->skinned) {
            ++s.skinned_alive;
            if (drawn) {
                ++s.skinned_drawn;
                s.skinned_drawn_triangles += e->triangles;
                s.skinned.push_back({key, e->triangles, e->mask});
            }
        } else if (e->dynamic) {
            ++s.moving_alive;
            s.moving_drawn += drawn ? 1u : 0u;
        } else if ((e->mask & CameraMask) != 0) {
            const u64 bytes = e->built && e->blas ? e->scene_bytes : 0;
            ++s.static_alive;
            s.static_alive_bytes += bytes;
            s.static_alive_triangles += e->triangles;
            if (drawn) {
                ++s.static_drawn;
                s.static_drawn_bytes += bytes;
                s.static_drawn_triangles += e->triangles;
            }
        } else {
            ++s.shadow_alive;
            s.shadow_drawn += drawn ? 1u : 0u;
        }
    }
    std::vector<std::size_t> order(s.skinned.size());
    for (std::size_t i = 0; i < order.size(); ++i) {
        order[i] = i;
    }
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return s.skinned[a].triangles > s.skinned[b].triangles;
    });
    std::vector<ProbeSkinned> kept;
    for (std::size_t i = 0; i < order.size() && kept.size() < skinned_most; ++i) {
        kept.push_back(s.skinned[order[i]]);
    }
    s.skinned = std::move(kept);
    return s;
}

}
