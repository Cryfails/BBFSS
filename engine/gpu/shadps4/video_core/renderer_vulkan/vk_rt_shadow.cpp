// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_rt_shadow.h"

#include <algorithm>
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
#include "shader_recompiler/runtime_info.h"
#include "video_core/host_shaders/rt_shadow_coverage_comp.h"
#include "video_core/host_shaders/rt_shadow_filter_r25_comp.h" // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"

namespace Vulkan {
namespace {
constexpr u32 MaxParams = 8192;
static_assert(1 + 4 * MaxParams == Shader::MotionVectors::CaptureParamsCapacity);
constexpr u32 MaxPositions = 8u << 20;
constexpr u32 MaxInstances = 8192;
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

// The key of an instance's own entry (see PrepareDraw): its mesh key and its bone palette.
u64 InstanceKey(u64 key, u64 palette) {
    return XXH3_64bits_withSeed(&palette, sizeof(palette), key ^ 0xa24baed4963ee407ull);
}

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;

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
    Free(still_sigs); // bbport (r47_still-check)
    Free(still_readback);
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
    entry_bytes -= std::min(entry_bytes, entry.bytes);
    blas_bytes -= std::min(blas_bytes, entry.scene_bytes);
    entry.bytes = 0;
    entry.scene_bytes = 0;
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
                               sizeof(TracePush), RT_SHADOW_HALF_COMP,
                               "Ray traced shadows (half resolution)");
        std::printf("Ray traced sun (r25): half resolution (%s) %s\n",
                    r25_half_env == 1 ? "BB_RT_SUN_HALF=1" : "graphics_rt_sun_half=1",
                    made ? "ready" : "ignored - no pipeline");
    }
    return wanted && r25_half_pipeline;
}

bool RtShadow::Setup(const ObjectMotion& object_motion) {
    tried = true;
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
                            sizeof(TracePush), RT_SHADOW_COVERAGE_COMP, "Ray traced shadows") ||
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
              vk::DeviceSize(4 * MaxInstances) * sizeof(vk::AccelerationStructureInstanceKHR), true,
              InputUsage) ||
        !Make(capture_addresses, 16, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||
        !Make(both_addresses, 32, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT)) {
        return false;
    }
    std::memset(params.mapped, 0, 32);
    // bbport (r25_rt-sun-trace): the pass counters (zeroed on the GPU by the first sun trace).
    if (!Make(r25_counts, R25Slots * sizeof(u32), false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                  VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(r25_readback, R25Slots * sizeof(u32), true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !r25_readback.mapped) {
        return false;
    }
    std::memset(r25_readback.mapped, 0, R25Slots * sizeof(u32));
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
    const std::array<u64, 2> capture_table{params.address, positions.address};
    std::memcpy(capture_addresses.mapped, capture_table.data(), sizeof(capture_table));
    const auto motion_table = object_motion.AddressTable();
    const std::array<u64, 4> both_table{motion_table.params, motion_table.positions, params.address,
                                        positions.address};
    std::memcpy(both_addresses.mapped, both_table.data(), sizeof(both_table));
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
    const vk::DescriptorBufferInfo capture_info{capture_addresses.buffer, 0, 16};
    const vk::DescriptorBufferInfo both_info{both_addresses.buffer, 0, 32};
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
    const vk::DescriptorSet set = mode == 3u ? both_set : capture_set;
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
        return 0;
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
    stats.strips += draw.strip ? 1 : 0;
    const u8 mask = draw.camera_pass ? CameraMask : ShadowMask;
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
            slot = MakeEntry(draw, mask);
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
    entry.card_shadow = entry.card_shadow || (draw.shadow_pass && draw.textured);
    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key
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
        return 0;
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
        stats.refit_triangles += update ? entry.triangles : 0;
        // bbport (r17_rt-upkeep): a shared copy's refresh (never refit) is built for speed
        builds.back().fast = UpkeepOn() && refresh;
        builds.back().inputs = draw.inputs;
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
    }
    builds.clear();
    positions_used = 0;
    scratch_used = 0;
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
    EffectPass::Mark(16, "ray tracing geometry");
    scheduler.RecordCrumb(
        {.name = "Ray tracing geometry"},
        [job, positions = positions.buffer, unproject_pipeline = *unproject_pipeline,
         unproject_layout = *unproject_layout, still_sigs = still_sigs.buffer,
         still_readback = still_readback.buffer, still_pipeline = *still_pipeline,
         still_layout = *still_layout](vk::CommandBuffer cmdbuf) {
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
            EffectPass::MemoryBarrier(cmdbuf, AsBuild, vk::AccessFlagBits2::eAccelerationStructureWriteKHR, AsBuild,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR);
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
    return SunRayTraced() || s.graphics_rt_point_shadows.load(std::memory_order_relaxed) ||
           (s.graphics_rt_bounce.load(std::memory_order_relaxed) &&
            !(s.graphics_gi_probes.load(std::memory_order_relaxed) &&
              s.effects[BbSettings::EffectGi].load(std::memory_order_relaxed)));
}

bool RtShadow::PrepareCapture() {
    if (!Wanted()) {
        return false;
    }
    RecordBuilds();
    return Complete() && camera_motion.PassMatrices().valid;
}

bool RtShadow::PrepareScene() {
    if (!need_scene || !PrepareCapture()) {
        return false;
    }
    const auto camera = camera_motion.PassMatrices();
    // bbport (r14_cascade_rt): after the drawn entries, those held for cascades not drawn (none
    // when off); rebuilt too when entries moved from held to drawn or a cascade's draws arrived.
    CollectHeld();
    const u32 count = std::min<u32>(u32(frame_entries.size() + held_now.size()), MaxInstances);
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
    auto* ring = static_cast<vk::AccelerationStructureInstanceKHR*>(instance_data.mapped) +
                 slot * MaxInstances;
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
    for (u32 i = 0; i < count; ++i) {
        // bbport (r14_cascade_rt): a held entry, or a held one drawn only by the camera pass while
        // its cascades are not drawn, keeps casting the sun's shadow (rt_shadow.comp's ray mask 1).
        // Not held (dropped: its cascade drew without it): the camera pass's mask only, as before.
        const bool kept = i >= frame_entries.size();
        Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];
        if (!entry->blas) {
            continue;
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
        const u8 mask =
            kept ? ShadowMask
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
        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),
            .accelerationStructureReference = entry->address,
        };
        std::memcpy(&record.transform, camera.view.data(), sizeof(camera.view));
        out[built++] = record;
        triangles += entry->triangles;
    }
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
    const u64 instances_address =
        instance_data.address + u64(slot) * MaxInstances * sizeof(vk::AccelerationStructureInstanceKHR);
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
        r25_frames = 0;
    }
    const u32 r25_flags =
        (r25_exact ? R25Exact : 0u) | ((r25_recorded++ & 7) == 0 ? R25Count : 0u);
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
                const vk::BufferCopy region{0, 0, R25Slots * sizeof(u32)};
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
    const u32 param =
        mode == Shader::MotionVectors::VertexBoth ? motion_param >> 16 : motion_param;
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

void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
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
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE set: true while the TLAS traced as it was
    // stays frozen (it holds BLAS addresses: no entry is destroyed). Unset: false, as before.
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
    params_used = 0;
    positions_used = 0;
    scratch_used = 0;
    new_triangles = 0;
    rebuilt_triangles = 0;
    missed = 0;
    tlas_count = 0;
    frame_entries.clear();
    frame_cameras.clear();
    occurrences.clear();
    if (++occurrence_epoch == 0) { // 2^32 frames: slots of epoch 0 would read as this frame's
        occurrence_slots.fill(OccurrenceSlot{});
        occurrence_epoch = 1;
    }
}

}
