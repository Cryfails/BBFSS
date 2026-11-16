// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_rt_shadow.h"

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

#include <xxhash.h>

#include "bbport_sections.h"
#include "bbport_settings.h"
#include "bbport_sun_cascades.h"
#include "bbport_toggles.h"
#include "bbport_wind_hang_probe.h" // bbport (r112b_hang-probe, TOOL)
#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)
#include "shader_recompiler/runtime_info.h"
#include "video_core/host_shaders/rt_shadow_coverage_comp.h"
#include "video_core/host_shaders/rt_shadow_filter_r25_comp.h" // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_glass_comp.h"      // bbport (r86_glass-light-stage2a)
#include "video_core/host_shaders/rt_shadow_half_glass_comp.h" // bbport (r86_glass-light-stage2a)
#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)
#include "video_core/host_shaders/rt_card_uv_comp.h"           // bbport (r54_leaf-stage2)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/rt_geometry_check_comp.h" // bbport (r62d_card-uv-diag)
#include "video_core/host_shaders/rt_card_guard_comp.h" // bbport (r62e_leaf-cards-usable)
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
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
};
static_assert(sizeof(TracePush) == 40);

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

RtShadow::RtShadow(const Instance& instance_, Scheduler& scheduler_, CameraMotion& camera_motion_,
                   const ObjectMotion& object_motion)
    : instance{instance_}, scheduler{scheduler_}, camera_motion{camera_motion_} {
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
}

RtShadow::~RtShadow() {
    if (!tried) {
        return;
    }
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
    Free(r25_counts); // bbport (r25_rt-sun-trace)
    Free(r25_readback);
    Free(probe_world); // bbport (r64b_surface-probe-more)
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
    for (Buffer* b : {&capture_addresses, &both_addresses, &params, &positions, &scratch,
                      &instance_data, &tlas_storage, &tlas_scratch}) {
        Free(*b);
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

void RtShadow::Destroy(Entry& entry) {
    // bbport (r121c_tlas-unbound-read): no record is written for it from here. When the TLAS last built still holds
    // its address (it was in the records of the last scene) the next scene is a build and the free is counted; the
    // free itself waits for the GPU below (DeferOperation: the tick of the command buffer being recorded, never
    // before a TLAS or BLAS build recorded earlier).
    entry_live.erase(&entry);
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

void RtShadow::BindAddresses(vk::PipelineLayout layout, u32 mode) {
    const vk::DescriptorSet set =
        Shader::MotionVectors::Kind(mode) == Shader::MotionVectors::VertexBoth ? both_set
                                                                              : capture_set;
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
        if (entry->seen_frame != frame && Holds(*entry)) {
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
                continue;
            }
            entry->held = true;
            held_next.push_back(entry);
        }
        if (window) {
            for (Entry* entry : frame_entries) {
                if (!entry->held && entry->shadow_frame == frame && (entry->cascades & 0x0f)) {
                    entry->held = true;
                    held_next.push_back(entry);
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

u32 RtShadow::PrepareDraw(const Draw& draw) {
    // bbport (r19_draw-cost): experiment 17592186044416 clear: the short paths marked r19 below,
    // each giving what the old code computes from the same inputs; set: the old code.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    if (r19 && draw.r19_wanted) {
        ++r19_stats.wanted_skipped;
    } else if (!Wanted()) {
        return 0;
    }
    if (!draw.shadow_pass && !draw.camera_pass) {
        return 0;
    }
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
        return 0;
    }
    draw.camera_pass ? ++stats.camera_draws : ++stats.draws;
    if (!draw.solid) {
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
            return 0;
        }
    }
    if (!draw.constants) {
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
        return 0;
    }
    if (!draw.triangles || !draw.indices || draw.instances == 0 ||
        draw.instances > MaxInstancesPerDraw) {
        draw.instances > MaxInstancesPerDraw ? ++stats.instanced : ++stats.unsupported;
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
                ++stats.over_budget;
                ++missed;
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            // bbport (r26_upkeep-probe): BLAS and TLAS frozen: no new caster (nothing would
            // build it, the TLAS traced as it was would not hold it), so no memory is taken.
            if (r26_freeze == 3u) {
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
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
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
    if (draw.glass) { // bbport (r83_glass-water-stage1): for the log
        NoteGlassDraw(entry);
        if (RtGlassCarryOn()) { // bbport (r86_glass-light-stage2a, r86b): carried into the next frame
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
            return probe.param;
        }
    }
    // Over budget, a caster built before keeps last frame's BLAS and world copy (exact for static
    // props drawn several times, a frame late for moving ones) rather than vanishing.
    const auto skip = [&] {
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
        return 0u;
    };
    u32 param = 0;
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
            const auto keep = [&] {
                entry.seen_frame = frame;
                frame_entries.push_back(&entry);
                return 0u;
            };
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                if (on && UnchangedMode() == 2) {
                    ++r17_stats.same_skipped;
                    r17_stats.same_skipped_triangles += entry.triangles;
                    return keep();
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
                    return keep();
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
            return skip();
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
                return 0;
            }
            if (r26_freeze == 3u) {
                ++r26_stats.left_out;
                return 0;
            }
            ++r26_stats.recorded;
        }
        param = Param(positions_used, entry);
        if (!param) {
            return skip();
        }
        builds.push_back({&entry, positions_used, update, to_world});
        builds.back().param = param; // bbport (r47_still-check): see CaptureLeftOut
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
    return param;
}

void RtShadow::RecordBuilds() {
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
        std::vector<vk::AccelerationStructureGeometryKHR> geometries;
        std::vector<vk::AccelerationStructureBuildGeometryInfoKHR> infos;
        std::vector<vk::AccelerationStructureBuildRangeInfoKHR> ranges;
        std::vector<const vk::AccelerationStructureBuildRangeInfoKHR*> pointers;
        std::vector<UnprojectPush> unproject;
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
        Entry& e = *build.entry;
        // bbport (r47_still-check): the draw of this capture was left out (CaptureLeftOut): its
        // range of the positions was not written. Nothing is measured, built or copied from it;
        // like a build that was never recorded (OnFrameEnd), the entry is built at its next
        // draw.
        if (build.left_out) {
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
        job->unproject.push_back({build.to_world, build.store, e.vertices * e.instances});
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
        if (!need_scene) {
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

bool RtShadow::PrepareScene() {
    if (!need_scene || !PrepareCapture()) {
        return false;
    }
    const auto camera = camera_motion.PassMatrices();
    // bbport (r121_tlas-hang-guard): a view that is not finite (every record's transform): no scene
    if (TlasGuardOn() && !TlasViewSane(camera.view)) {
        ++tlas_guard.bad_view;
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
        return true;
    }
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
                continue;
            }
        }
        if (!entry->blas) {
            continue;
        }
        // bbport (r121_tlas-hang-guard): an entry whose BLAS was never made has no address to point at
        if (tlas_guard_on && entry->address == 0) {
            ++tlas_guard.no_address;
            continue;
        }
        // bbport (r121c_tlas-unbound-read): the address is the one the BLAS was made with, and its handle is there
        if (tlas_guard_on) {
            if (live_entry->second != entry->address) {
                ++tlas_live.moved;
                continue;
            }
            if (!entry->handle) {
                ++tlas_live.no_handle;
                continue;
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
        vk::AccelerationStructureInstanceKHR record{
            .instanceCustomIndex = CardCustomIndex(*entry), // bbport (r62_leaf-stage3)
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
        out[built++] = record;
        // bbport (r86_glass-light-stage2a): the pane records (Record asks them only while one is
        // in)
        if (RtGlassEntry(static_cast<u8>(record.mask))) {
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
    };
    const FilterPush filter{
        .buf_off = in.constants_offset_word,
        .radius = FilterRadius,
        .size = {float(in.width), float(in.height)},
        .r25_flags = r25_flags,
    };
    EffectPass::Mark(14, "ray traced sun");
    scheduler.RecordCrumb(
        {.name = "Ray traced sun"},
        [in, trace, filter, use_vsm, tlas = tlas, raw_image = raw_image, raw_view = raw_view,
         sampler = *sampler, trace_pipeline = *trace_pipeline, trace_layout = *trace_layout,
         filter_pipeline = *filter_pipeline, filter_layout = *filter_layout,
         r25_counts = r25_counts.buffer, r25_readback = r25_readback.buffer, r25_half = r25_half,
         half_pipeline = r25_half ? *r25_half_pipeline : vk::Pipeline{},
         half_layout = r25_half ? *r25_half_layout : vk::PipelineLayout{},
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
            const std::array<vk::WriteDescriptorSet, 6> trace_writes{{
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
            }};
            if (!use_vsm) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, trace_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, trace_layout, 0,
                                            trace_writes);
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
                                                trace_writes);
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
        if (!env) {
            return false;
        }
        const bool one = std::strcmp(env, "1") == 0;
        const bool layers = Shader::Optimization::CardAlphaLevel() == 2;
        std::printf("Ray traced lamps (r63): BB_RT_CARD_LAMPS=%s: %s\n", one ? "1" : "(not 1)",
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
            card_lamp_instances};
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
    if (!capturing) {
        return;
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the game draws the window panes after
    // the frame's last reader of the scene (forward, after the sun's trace and the lamp pass), so
    // their captures would be dropped below (an entry is captured again at its next draw) and no
    // pane ever got a BLAS. While a pane's capture waits and the scene is wanted, the frame's
    // waiting captures are built here, as a later reader's PrepareScene builds them (with
    // BB_LAMP_FOG_SHAFTS), and CollectHeld carries the panes into the next frame's scene. Off:
    // nothing here.
    if (RtGlassCarryOn() && need_scene && // bbport (r86b_glass-visible): or BB_GLASS_GLINT on
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
            Destroy(*item.second);
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
            Destroy(*it->second);
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
    if (RtGlassCarryOn()) { // bbport (r86b_glass-visible): or BB_GLASS_GLINT on
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
