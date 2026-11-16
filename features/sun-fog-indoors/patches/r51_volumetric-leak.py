# r51_volumetric-leak: stage A of the fix for the volumetric sunlight that shines through roofs,
# walls and bridges ("in some interiors the volumetric sun rays ... shines through and creates like
# a shaft and fog in the rooms or roof ... goes through buildings or bridges"). check|apply|revert
# (revert restores byte for byte and deletes the two new files). On top of r1..r48 as <tree>
# has them on 2026-11-14 night. The tree: the one the environment variable R51_ROOT names; without
# it the current directory when that is the root of a source tree, else <tree>/. Nothing is
# changed in place: every new text is written beside its target and moved over it, and a failure
# puts back what was already moved. Files keep their line ends (CRLF or LF, as each has them).
#
# WHY (volumetric_leak.json, verified again here). The march (volumetric_light.comp visibility())
# asks the game's sun atlas whether a sample is sunlit: the first cascade (by view z) whose
# quadrant holds the sample decides, and a texel at the clear value counts as lit. Cascade 0
# (0-2 m) never gets a caster draw from the game (log: frames with draws 0% for c0; r14 keeps it
# blank), so every room had a sunlit haze within 2 m of the camera, and any quadrant holding only
# the clear value did the same over its range. A roof or bridge the game drew only into a coarser
# cascade was never asked about.
#
# WHAT: one knob, BB_VOLUMETRIC_OCCLUSION, a bit field read once at start (default 7 = all; a
# clear bit gives that part as before r51, 0 the picture before r51; anything but a whole number
# 0..7 counts as 7). New header renderer_vulkan/volumetric_occlusion.h (Parse, Bits, Valid, Pack).
#  1 (A1) cascades without casters count as outside the atlas. At the shadow resolve the
#    rasterizer builds a 4-bit mask (VolumetricOcclusion::Valid):
#      r14 kept quadrants keeping in this atlas frame (sun_keep.tracked):
#        sun_keep.drawn | (~sun_keep.cleared & ~sun_keep.blank)
#      else: sun_atlas.drawn_mask | (0xF if an atlas draw of no single quadrant was seen this
#        frame: mask_spread, r14's rule) | (sun_hold.confirmed & ~(sun_hold.stale |
#        sun_hold.pending_clear)) (r7's kept cascades it has not lost; 0 without r7)
#    and in both the first `count` only (count = countr_zero(skipped_mask), as before).
#    r14's re-clear of all four quadrants within an atlas frame (SunKeepBeforePass, "reallocated
#    or written within a frame") now also resets sun_keep.drawn: the draws before it are gone, so
#    those quadrants count as blank, not drawn (r14 itself: a blank quadrant is not expired; its
#    content is the clear value either way). Verified:
#    SunKeepInPass ORs every atlas draw's quadrant into sun_keep.drawn before SunAtlasSkipDraw
#    runs (vk_rasterizer.cpp: SunKeepInPass, then SunAtlasSkipDraw), whatever the r19 path does;
#    sun_keep.drawn/cleared are reset at each clear of the whole image while the gate is on, and
#    tracked == the mode was active at the last such clear (the gate then stays on: linger);
#    pending is always within cleared in an atlas frame (the clear takeover sets cleared =
#    pending; SunKeepInPass ORs a clear into cleared before it may defer it), so ~pending adds
#    nothing; blank is what the atlas frame before left (never expired). sun_atlas.drawn_mask is
#    set only past the r19 short path, which returns for every draw while the sun is not ray
#    traced (no VSM) and neither r7 nor a pass-log frame runs, so with ray tracing off it stayed 0.
#    The step added there: while the march wants the mask (BB_VOLUMETRIC_OCCLUSION bit 1 and the
#    last resolve marched; mask_wanted) and r14 is not keeping, a draw with a depth target
#    compares Scheduler::PassesBegun() with the pass it last looked at; only on a new pass is the
#    target's image looked up and its address compared with the atlas's; an atlas draw then ORs
#    SunQuadrant (r14's rule, the same as SunAtlasSkipDraw's) into drawn_mask and counts it in
#    cascade_draws as the full path does (so the "Sun atlas: at" line's two halves agree), or, in
#    no single quadrant, in mask_spread (the full path counts those too). mask_wanted ends with a
#    frame without a resolve (SunAtlasFrameEnd). Per draw: a bool,
#    a null id, a bool and a u64 compare; per pass with a depth target: one image lookup; per
#    atlas draw (~30-40 a frame): ~15 float ops. It cannot be cheaper: the quadrant comes from
#    each draw's viewport and scissor (one atlas pass may draw into more than one quadrant), and
#    the image test is already per pass. With bit 1 clear or the effect off: one bool per draw.
#    Shader: a cascade outside the mask is skipped like a sample outside its quadrant; a sample no
#    cascade with casters holds is dark (as a sample outside every quadrant was).
#  2 (A2) the darkest answer of every cascade holding the sample (stop at the first 0), and a
#    light depth outside [0, 1] asks the next cascade instead of answering dark.
#  4 (A0) no sun fog when the fade rate (uniforms 73) is not positive and finite (it would turn
#    the fade around); the march ends at min(surface or reach, shadow distance): past the
#    distance the fade is 0, so at 25.1 m the 32 steps are 0.78 m apart, not 1.25 m (12 of 32
#    samples of a sky ray were spent where the fade is 0); the integral is the same, the banding
#    finer.
#  The bits and the mask travel in the existing push word `cascades` (bits 0-3 the count as
#  before, 8-11 the mask, 16-23 the knob; VolumetricOcclusion::Pack). Free on both sides: the
#  C++ side wrote min(count, 4) (bits 0-2), and the word's only reader was visibility()
#  (min(cascades, 4u)), which now takes cascades & 15u. The push block stays 32 bytes.
#  A log line every 600 frames with the "Sun atlas: at" line, while the effect marched:
#  "Sun atlas: volumetric march (r51) reads cascades 0xe now, BB_VOLUMETRIC_OCCLUSION 7; c0..c3
#  read on 0 600 600 600 of 600 frames marched; frames with an atlas draw of no single quadrant
#  (all four read) 0" (what the shader got: with bit 1 clear the count). With the sun not ray
#  traced and r14 not keeping, the "Sun atlas: at" line's draws and frames with draws are now
#  counted while bit 1 is set (by the r19 step) and stay 0 with it clear: compare those figures
#  only between runs with the same knob.
#  Cost of bit 2 (not measured): a lit sample gathers once per valid cascade holding it, so in
#  sunlit open air about 1.9 gathers a sample (61 a pixel against 32) with splits 2/8/15 m and a
#  25.1 m shadow distance, up to 3 (96) for rays ending within 8 m; to be measured (7 against 5)
#  at the user's output resolution before bit 2 stays in the default.
#  Test: tests/test_volumetric_occlusion.cpp (volumetric-occlusion-test in engine/gpu/CMakeLists).
# NOT CHANGED: stage B (a ray traced gate) and stage C (the fog colour's record).
# REVIEW (2026-11-14, second pass): r7's stale quadrants, r14's re-clear within an atlas frame,
# cascade_draws in the r19 step, mask_wanted's end, spanning / no-viewport draws by r14's rule.
# VERIFIED (2026-11-14): check against <tree> writes nothing; apply / check ("already
# applied") / revert on a copy of the 6 files (byte for byte back after revert); the shader built
# as the engine builds it (glslangValidator --target-env vulkan1.3, INTEGRATE=1 and REPAIR=1) and
# spirv-val; the test built with the target's flags and run; vk_volumetric_light.cpp and
# vk_rasterizer_effects.cpp compiled -fsyntax-only (gnu++23, bbgpu's include paths and defines, the
# patched headers first; no new warning with -Wall -Wextra). Not built in the tree, not run in the
# game.

import os
import sys

ROOT = os.environ.get("R51_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_volumetric_light.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
H = B + "host_shaders/"
TESTS = E + "tests/"

TMP = ".r51tmp"  # a new text waits under this name beside its target (main)

HEADER = r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r51_volumetric-leak): what the volumetric sunlight's march may take from the game's sun
// atlas, and which of its occlusion fixes run. No Vulkan here: tests/test_volumetric_occlusion.cpp
// builds this header alone.
//
// BB_VOLUMETRIC_OCCLUSION, a bit field read once at start (default 7, all on; 0: as before r51):
//   1 a cascade whose quadrant holds no casters (only the clear value, read as full sun) counts
//     as outside the atlas: the march asks the next cascade, and a sample no cascade with
//     casters holds is dark (cascade 0, 0-2 m, never gets a caster from the game)
//   2 the darkest answer of every cascade holding the sample, not the first one's (a roof or a
//     bridge drawn only into a coarser cascade); a light depth outside [0, 1] asks the next one
//   4 no fog for a fade rate that is not positive and finite, and the march ends at the shadow
//     distance (past it the fade is 0)
// Bit 1 is the mask (Valid) the rasterizer builds; bits 2 and 4 the shader reads (Pack).

#include <cstdint>
#include <cstdlib>

namespace Vulkan::VolumetricOcclusion {

inline constexpr std::uint32_t SkipEmpty = 1, Darkest = 2, Robust = 4;
inline constexpr std::uint32_t All = SkipEmpty | Darkest | Robust;

/// BB_VOLUMETRIC_OCCLUSION's text: a whole number 0..7; unset, empty or anything else gives All.
inline std::uint32_t Parse(const char* text) {
    if (!text || !*text) {
        return All;
    }
    char* end = nullptr;
    const unsigned long n = std::strtoul(text, &end, 10);
    return *end == '\0' && n <= All ? std::uint32_t(n) : All;
}

/// The knob, read once.
inline std::uint32_t Bits() {
    static const std::uint32_t bits = Parse(std::getenv("BB_VOLUMETRIC_OCCLUSION"));
    return bits;
}

/// The sun atlas at the game's shadow resolve, bit c for cascade c (Rasterizer::sun_atlas,
/// sun_keep, sun_hold).
struct Quadrants {
    std::uint32_t count = 4;      ///< cascades before the first one with draws left out
    std::uint32_t drawn = 0;      ///< with draws this frame (sun_atlas.drawn_mask)
    bool spread = false;          ///< a draw across quadrants or without a single viewport this
                                  ///< frame (sun_atlas.mask_spread): all four, as r14 counts it
    std::uint32_t held = 0;       ///< r7: kept from a full drawing (sun_hold.confirmed)
    std::uint32_t held_lost = 0;  ///< r7: kept depth lost or owed a clear (sun_hold.stale,
                                  ///< pending_clear): only the clear value, or soon
    bool kept_tracked = false;    ///< r14 keeps quadrants in this atlas frame (sun_keep.tracked)
    std::uint32_t kept_drawn = 0; ///< r14: with draws in it (sun_keep.drawn)
    std::uint32_t kept_cleared = 0; ///< r14: cleared or owed a clear in it (sun_keep.cleared)
    std::uint32_t kept_blank = 0; ///< r14: only the clear value when it began (sun_keep.blank)
};

/// The cascades the march may read: the first `count`, with SkipEmpty only those holding casters
/// (drawn this frame, or depth kept from an earlier drawing). r14's own record covers its atlas
/// frame (a quadrant neither drawn nor cleared in it keeps what it held, blank or not); without
/// it the atlas is cleared whole every frame, but for the quadrants r7 keeps (and has not lost).
/// A draw whose quadrant is not known counts for all four in both (r14's rule).
constexpr std::uint32_t Valid(const Quadrants& q, std::uint32_t bits) {
    const std::uint32_t first = q.count >= 4 ? 0xFu : (1u << q.count) - 1u;
    if ((bits & SkipEmpty) == 0) {
        return first;
    }
    const std::uint32_t data =
        q.kept_tracked ? q.kept_drawn | (~q.kept_cleared & ~q.kept_blank)
                       : q.drawn | (q.spread ? 0xFu : 0u) | (q.held & ~q.held_lost);
    return data & first;
}

/// volumetric_light.comp's push word `cascades`: bits 0-3 the count, 8-11 Valid, 16-23 the knob.
constexpr std::uint32_t Pack(std::uint32_t count, std::uint32_t valid, std::uint32_t bits) {
    return (count < 4 ? count : 4u) | (valid & 0xFu) << 8 | (bits & 0xFFu) << 16;
}

} // namespace Vulkan::VolumetricOcclusion
"""

TEST = r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r51_volumetric-leak): the volumetric march's cascades (volumetric_occlusion.h): the
// knob's text, the mask in every mode (r14 kept quadrants on and off, r7, cascades left out) and
// the push word the shader takes apart.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_occlusion.h"

using namespace Vulkan::VolumetricOcclusion;

int main() {
    // The knob: a whole number 0..7, else everything on.
    assert(Parse(nullptr) == All && Parse("") == All && All == 7);
    assert(Parse("0") == 0 && Parse("1") == 1 && Parse("5") == 5 && Parse("7") == 7);
    assert(Parse("8") == All && Parse("-1") == All && Parse("3x") == All && Parse("on") == All);

    // Bit 1 clear: the first `count` cascades, as before r51, whatever the quadrants hold.
    for (std::uint32_t count = 0; count <= 5; ++count) {
        const std::uint32_t first = count >= 4 ? 0xFu : (1u << count) - 1u;
        for (std::uint32_t m = 0; m < 16; ++m) {
            for (const bool tracked : {false, true}) {
                const Quadrants q{.count = count, .drawn = m, .spread = (m & 1u) != 0,
                                  .held = m ^ 5u, .held_lost = m ^ 6u, .kept_tracked = tracked,
                                  .kept_drawn = m ^ 3u, .kept_cleared = m, .kept_blank = m ^ 9u};
                for (const std::uint32_t bits : {0u, 2u, 4u, 6u}) {
                    assert(Valid(q, bits) == first);
                }
                // Bit 1 set: never a cascade the count leaves out.
                assert((Valid(q, All) & ~first) == 0);
            }
        }
    }

    // r14 off (the game clears the whole atlas every frame): the cascades with draws. The log's
    // frames: c0 never drawn, c1 every frame, c2 and c3 now and then.
    assert(Valid({.drawn = 0xEu}, All) == 0xEu);
    assert(Valid({.drawn = 0x2u}, All) == 0x2u);
    // No casters anywhere (an interior the game draws no sun casters for): nothing to read.
    assert(Valid({.drawn = 0}, All) == 0);
    // Cascades left out from c2 on (ray traced sun): not read, drawn or not.
    assert(Valid({.count = 2, .drawn = 0xEu}, All) == 0x2u);
    // r7 (BB_SUN_CASCADE_EVERY): a kept cascade has no draws this frame and holds its depth.
    assert(Valid({.drawn = 0x2u, .held = 0xCu}, All) == 0xEu);
    // r7 lost c3's kept depth (the atlas image changed, a whole clear it could not narrow, an
    // indirect draw): stale, cleared or owed a clear; confirmed stays set. Not read unless drawn.
    assert(Valid({.drawn = 0x2u, .held = 0xCu, .held_lost = 0x8u}, All) == 0x6u);
    assert(Valid({.drawn = 0xAu, .held = 0xCu, .held_lost = 0xCu}, All) == 0xAu);
    // A draw across quadrants or without a single viewport: all four, as r14 counts it.
    assert(Valid({.drawn = 0x2u, .spread = true}, All) == 0xFu);
    assert(Valid({.count = 2, .spread = true}, All) == 0x3u);

    // r14 on, the user's log ("quadrant clears by cascade 0 600 75 75; kept 600 0 525 525"):
    // a frame drawing c1 only. c1 cleared before its first draw; c0 blank since the mode began;
    // c2 and c3 keep their last drawing.
    const Quadrants kept{.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0x1u};
    assert(Valid(kept, All) == 0xEu);
    // r14's record wins over the frame's draws (it holds the atlas frame; the r19 path may not
    // have counted them).
    assert(Valid({.drawn = 0xFu, .spread = true, .held = 0xFu, .kept_tracked = true,
                  .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0x1u}, All) == 0xEu);
    // r14 found the kept depth untrustworthy within its atlas frame (SunKeepBeforePass: all four
    // cleared again, drawn reset since r51): only the draws after that hold casters.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x4u, .kept_cleared = 0xFu, .kept_blank = 0x1u}, All) == 0x4u);
    // A frame drawing c1, c2 and c3.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0xEu, .kept_cleared = 0xEu, .kept_blank = 0x1u}, All) == 0xEu);
    // c3 kept too long (cleared with this pass, no draw): only the clear value.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0xAu, .kept_blank = 0x1u}, All) == 0x6u);
    // An owed clear counts as cleared (SunKeepInPass: pending is always within cleared).
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x6u, .kept_blank = 0x1u}, All) == 0xAu);
    // The atlas cleared whole in the mode (the first clear, a DB clear draw, ...): cleared 0xF,
    // only this atlas frame's draws hold casters.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0xFu, .kept_blank = 0}, All) == 0x2u);
    // A quadrant blank at the start and still undrawn: not read.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x2u, .kept_cleared = 0x2u, .kept_blank = 0xDu}, All) == 0x2u);
    // A blank quadrant drawn again: read.
    assert(Valid({.kept_tracked = true, .kept_drawn = 0x3u, .kept_cleared = 0x3u, .kept_blank = 0x1u}, All) == 0xFu);

    // The push word: count (at most 4) in bits 0-3, the mask in 8-11, the knob in 16-23.
    assert(Pack(4, 0xEu, 7) == (4u | 0xE00u | 0x70000u));
    assert(Pack(9, 0x1Fu, 0x1FFu) == (4u | 0xF00u | 0xFF0000u));
    assert(Pack(0, 0, 0) == 0);
    const std::uint32_t word = Pack(3, Valid({.count = 3, .drawn = 0xEu}, 5), 5);
    assert((word & 15u) == 3 && ((word >> 8) & 15u) == 0x6u && ((word >> 16) & Darkest) == 0 &&
           ((word >> 16) & Robust) != 0);

    std::printf("volumetric occlusion: all checks passed\n");
    return 0;
}
"""

NEW_FILES = {
    R + "volumetric_occlusion.h": HEADER,
    TESTS + "test_volumetric_occlusion.cpp": TEST,
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    H + "volumetric_light.comp": [
        (r"""    uint cascades; // sun atlas cascades drawn in full; the others count as outside the atlas
""",
         r"""    // sun atlas cascades: bits 0-3 how many are drawn in full (the others count as outside the
    // atlas); bbport (r51_volumetric-leak): bits 8-11 those holding casters, 16-23
    // BB_VOLUMETRIC_OCCLUSION (volumetric_occlusion.h Pack)
    uint cascades;
"""),
        (r"""mat4 local_light[4];
vec3 local_splits;

float visibility(vec3 p, vec2 texel) {
    int first = int(p.z > local_splits.x) + int(p.z > local_splits.y) + int(p.z > local_splits.z);
    for (int cascade = first; cascade < int(min(cascades, 4u)); ++cascade) {
        mat4 m = local_light[cascade];
""",
         r"""mat4 local_light[4];
vec3 local_splits;
// bbport (r51_volumetric-leak): the bits of BB_VOLUMETRIC_OCCLUSION the shader reads.
const uint OcclusionDarkest = 2u, OcclusionRobust = 4u;

float visibility(vec3 p, vec2 texel) {
    int first = int(p.z > local_splits.x) + int(p.z > local_splits.y) + int(p.z > local_splits.z);
    // bbport (r51_volumetric-leak): a cascade holding no casters counts as outside the atlas;
    // with OcclusionDarkest every cascade holding the sample answers, the darkest answer stands.
    uint valid = (cascades >> 8) & 15u;
    bool darkest = ((cascades >> 16) & OcclusionDarkest) != 0u;
    float answer = 2.0;
    for (int cascade = first; cascade < int(min(cascades & 15u, 4u)); ++cascade) {
        if (((valid >> cascade) & 1u) == 0u) continue;
        mat4 m = local_light[cascade];
"""),
        (r"""        if (s.z < 0.0 || s.z > 1.0) return 0.0;
""",
         r"""        if (s.z < 0.0 || s.z > 1.0) {
            if (darkest) continue;
            return 0.0;
        }
"""),
        (r"""        float coverage = clamp(shared_coverage.y * (shared_coverage.x - length(p)), 0.0, 1.0);
        return dot(lit, vec4(0.25)) * coverage;
    }
    return 0.0;
}
""",
         r"""        float coverage = clamp(shared_coverage.y * (shared_coverage.x - length(p)), 0.0, 1.0);
        if (!darkest) return dot(lit, vec4(0.25)) * coverage;
        answer = min(answer, dot(lit, vec4(0.25)) * coverage);
        if (answer == 0.0) break;
    }
    return answer <= 1.0 ? answer : 0.0;
}
"""),
        (r"""    float limit = sky ? reach : min(distance_to_surface, reach);
    float ds = limit / float(steps);
""",
         r"""    float limit = sky ? reach : min(distance_to_surface, reach);
    // bbport (r51_volumetric-leak): no fog for a fade rate that is not positive and finite (it
    // would turn the fade around), and no steps past the shadow distance, where the fade is 0.
    if (((cascades >> 16) & OcclusionRobust) != 0u) {
        if (!(shared_coverage.y > 0.0) || isinf(shared_coverage.y)) return;
        if (shared_coverage.x < limit) limit = max(shared_coverage.x, 0.0);
    }
    float ds = limit / float(steps);
"""),
    ],
    R + "vk_volumetric_light.h": [
        (r"""    /// bbport: the sun atlas cascades drawn in full (the first `count`); the march treats the
    /// others as outside the atlas (Rasterizer::SunAtlasSkipDraw).
    void SetAtlasCascades(u32 count) noexcept { atlas_cascades = count; }
""",
         r"""    /// bbport: the sun atlas cascades drawn in full (the first `count`); the march treats the
    /// others as outside the atlas (Rasterizer::SunAtlasSkipDraw). bbport (r51_volumetric-leak):
    /// and those not in `valid` (VolumetricOcclusion::Valid).
    void SetAtlasCascades(u32 count, u32 valid) noexcept {
        atlas_cascades = count;
        atlas_valid = valid;
    }
"""),
        (r"""    u32 atlas_cascades = 4;
""",
         r"""    u32 atlas_cascades = 4;
    u32 atlas_valid = 0xF; ///< bbport (r51_volumetric-leak): bit c set: cascade c may be read
"""),
    ],
    R + "vk_volumetric_light.cpp": [
        (r"""#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
""",
         r"""#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h"
#include "video_core/texture_cache/texture_cache.h"
"""),
        (r"""    u32 cascades; // sun atlas cascades drawn in full (SetAtlasCascades)
""",
         r"""    u32 cascades; // VolumetricOcclusion::Pack (r51_volumetric-leak): count, mask, knob
"""),
        (r"""                        anisotropy, 0.02f, std::min<u32>(atlas_cascades, 4)};
""",
         r"""                        anisotropy, 0.02f,
                        VolumetricOcclusion::Pack(atlas_cascades, atlas_valid,
                                                  VolumetricOcclusion::Bits())};
"""),
    ],
    R + "vk_rasterizer.h": [
        (r"""        u32 drawn_mask = 0;            ///< cascades with draws this frame
""",
         r"""        u32 drawn_mask = 0;            ///< cascades with draws this frame
        // bbport (r51_volumetric-leak): the cascades the volumetric march read at the last resolve
        // (VolumetricOcclusion::Valid), and in how many of the frames it marched; the r19 path
        // counts draws into drawn_mask while the march wants it (mask_wanted), looking the depth
        // target up once a pass (mask_pass, mask_atlas); mask_spread counts this frame's atlas
        // draws across quadrants or without a single viewport (all four for the mask, as r14
        // counts them), spread_frames the frames with one. mask_wanted ends with a frame
        // without a resolve.
        u32 valid_mask = 0xF;
        std::array<u32, 4> valid_frames{};
        u32 march_frames = 0;
        bool mask_wanted = false;
        u64 mask_pass = ~0ull;
        bool mask_atlas = false;
        u32 mask_spread = 0, spread_frames = 0;
"""),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r"""#include "video_core/renderer_vulkan/vk_shader_util.h"

namespace Vulkan {
""",
         r"""#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h"

namespace Vulkan {
"""),
        (r"""        SunAtlasResolve(*ps_info);
        // Cascades left out since the last resolve are not marched through (SunAtlasSkipDraw).
        volumetric_light->SetAtlasCascades(
            sun_atlas.skipped_mask ? u32(std::countr_zero(sun_atlas.skipped_mask)) : 4u);
        sun_atlas.skipped_mask = 0;
""",
         r"""        SunAtlasResolve(*ps_info);
        // Cascades left out since the last resolve are not marched through (SunAtlasSkipDraw).
        // bbport (r51_volumetric-leak): with BB_VOLUMETRIC_OCCLUSION bit 1 neither are cascades
        // holding no casters: without draws, unless r14 or r7 keeps an earlier drawing (r7's
        // quadrants it marked stale or owes a clear hold the clear value: not kept).
        const u32 count =
            sun_atlas.skipped_mask ? u32(std::countr_zero(sun_atlas.skipped_mask)) : 4u;
        sun_atlas.valid_mask = VolumetricOcclusion::Valid(
            {.count = count, .drawn = sun_atlas.drawn_mask, .spread = sun_atlas.mask_spread != 0,
             .held = sun_hold.confirmed, .held_lost = sun_hold.stale | sun_hold.pending_clear,
             .kept_tracked = sun_keep.tracked, .kept_drawn = sun_keep.drawn,
             .kept_cleared = sun_keep.cleared, .kept_blank = sun_keep.blank},
            VolumetricOcclusion::Bits());
        volumetric_light->SetAtlasCascades(count, sun_atlas.valid_mask);
        sun_atlas.skipped_mask = 0;
"""),
        (r"""        sun_atlas.reach = volumetric_light->AtlasReach();
    } else if (hash == DirectionalFragmentShaderHash && !dc.buffer_infos.empty()) {
""",
         r"""        sun_atlas.reach = volumetric_light->AtlasReach();
        // bbport (r51_volumetric-leak): the r19 path counts the next atlas draws for the mask.
        sun_atlas.mask_wanted = sun_atlas.reach > 0.0f &&
                                (VolumetricOcclusion::Bits() & VolumetricOcclusion::SkipEmpty) != 0;
    } else if (hash == DirectionalFragmentShaderHash && !dc.buffer_infos.empty()) {
"""),
        (r"""        return value && value[0] == '1';
    }();
    return ignore;
}
}

void Rasterizer::SunAtlasResolve(const Shader::Info& ps) {
""",
         r"""        return value && value[0] == '1';
    }();
    return ignore;
}
/// r14's quadrant of a draw (below); bbport (r51_volumetric-leak): the r19 path's too.
u32 SunQuadrant(const DynamicState& dynamic, u32 width, u32 height);
}

void Rasterizer::SunAtlasResolve(const Shader::Info& ps) {
"""),
        (r"""        !rt_shadow->SunWanted()) {
        ++r19_stats.sun_short;
        return false;
    }
""",
         r"""        !rt_shadow->SunWanted()) {
        ++r19_stats.sun_short;
        // bbport (r51_volumetric-leak): the volumetric march's mask needs the cascades with draws
        // (r14 records its own); whether the depth target is the atlas is looked up once a pass.
        if (a.mask_wanted && db_desc.first && !sun_keep.tracked) {
            const u64 pass = scheduler.PassesBegun();
            if (pass != a.mask_pass) {
                a.mask_pass = pass;
                a.mask_atlas =
                    texture_cache.GetImage(db_desc.first).info.guest_address == a.address;
            }
            if (a.mask_atlas) {
                // As the full path below counts it (cascade_draws, drawn_mask); a draw across
                // quadrants or without a single viewport counts for all four (r14's rule).
                const u32 quadrant =
                    SunQuadrant(scheduler.GetDynamicState(), state.width, state.height);
                if (quadrant < 4) {
                    ++a.cascade_draws[quadrant];
                    a.drawn_mask |= 1u << quadrant;
                } else if (quadrant < 6) {
                    ++a.mask_spread;
                }
            }
        }
        return false;
    }
"""),
        (r"""    // The cascade: the quadrant holding the draw's viewport and scissor.
""",
         r"""    // bbport (r51_volumetric-leak): a draw across quadrants or without a single viewport
    // returns below without a cascade; for the volumetric march's mask it counts for all four,
    // as r14 counts it (the r19 path above does the same).
    if (a.mask_wanted && !sun_keep.tracked) {
        const u32 quadrant = SunQuadrant(dynamic, state.width, state.height);
        a.mask_spread += quadrant == 4 || quadrant == 5 ? 1u : 0u;
    }
    // The cascade: the quadrant holding the draw's viewport and scissor.
"""),
        (r"""    for (u32 c = 0; c < 4; ++c) {
        a.cascade_frames[c] += (a.drawn_mask >> c) & 1u;
    }
""",
         r"""    a.march_frames += a.reach > 0.0f ? 1u : 0u; // bbport (r51_volumetric-leak)
    a.spread_frames += a.mask_spread != 0 ? 1u : 0u;
    for (u32 c = 0; c < 4; ++c) {
        a.cascade_frames[c] += (a.drawn_mask >> c) & 1u;
        a.valid_frames[c] += a.reach > 0.0f ? (a.valid_mask >> c) & 1u : 0u;
    }
"""),
        (r"""                    100.0 * double(a.cascade_frames[2]) / f, 100.0 * double(a.cascade_frames[3]) / f);
        if (!BbToggle::Experiment(SunAtlasLiveOffBit)) {
""",
         r"""                    100.0 * double(a.cascade_frames[2]) / f, 100.0 * double(a.cascade_frames[3]) / f);
        if (a.march_frames != 0) { // bbport (r51_volumetric-leak)
            BbReport::Printf("Sun atlas: volumetric march (r51) reads cascades %#x now, "
                             "BB_VOLUMETRIC_OCCLUSION %u; c0..c3 read on %u %u %u %u of %u frames "
                             "marched; frames with an atlas draw of no single quadrant (all four "
                             "read) %u\n",
                             a.valid_mask, VolumetricOcclusion::Bits(), a.valid_frames[0],
                             a.valid_frames[1], a.valid_frames[2], a.valid_frames[3],
                             a.march_frames, a.spread_frames);
        }
        if (!BbToggle::Experiment(SunAtlasLiveOffBit)) {
"""),
        (r"""        a.cascade_skipped = {};
        a.cascade_frames = {};
    }
""",
         r"""        a.cascade_skipped = {};
        a.cascade_frames = {};
        a.valid_frames = {}; // bbport (r51_volumetric-leak)
        a.march_frames = 0;
        a.spread_frames = 0;
    }
"""),
        (r"""    a.resolved = false;
    a.reach = 0.0f;
    a.drawn_mask = 0;
    a.any_skipped = false;
""",
         r"""    // bbport (r51_volumetric-leak): a frame without a resolve (the effects off, no sun shadow)
    // ends the r19 path's counting for the mask; the next resolve starts it again.
    if (!a.resolved) {
        a.mask_wanted = false;
    }
    a.mask_spread = 0;
    a.resolved = false;
    a.reach = 0.0f;
    a.drawn_mask = 0;
    a.any_skipped = false;
"""),
        (r"""            k.pending = 0xFu;
            k.cleared = 0xFu;
            if (!k.whole_now) {
""",
         r"""            k.pending = 0xFu;
            k.cleared = 0xFu;
            // bbport (r51_volumetric-leak): and their draws are gone: only the draws from here on
            // hold casters (the volumetric march's mask; the quadrants left blank count as blank).
            k.drawn = 0;
            if (!k.whole_now) {
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
""",
         r"""add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
# bbport (r51_volumetric-leak): the volumetric march's cascades and knob (volumetric_occlusion.h)
add_executable(volumetric-occlusion-test EXCLUDE_FROM_ALL ../tests/test_volumetric_occlusion.cpp)
target_compile_options(volumetric-occlusion-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-occlusion-test PRIVATE ..)
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text."""
    ok = True
    comp = texts[H + "volumetric_light.comp"]
    # The push word's only reader takes it apart as Pack packs it; nothing reads it bare.
    if comp.count("cascades") != 6 or comp.count("int(min(cascades & 15u, 4u))") != 1 or \
            comp.count("uint valid = (cascades >> 8) & 15u;") != 1 or \
            comp.count("((cascades >> 16) & OcclusionDarkest) != 0u") != 1 or \
            comp.count("((cascades >> 16) & OcclusionRobust) != 0u") != 1:
        print("volumetric_light.comp: `cascades` is not read as the patch reads it (count 0-3, "
              "mask 8-11, knob 16-23)")
        ok = False
    # The robust guard comes before the step length is worked out from the limit.
    if not (0 < comp.find("if (shared_coverage.x < limit)") < comp.find("float ds = limit / float(steps);")):
        print("volumetric_light.comp: the march is not limited before its step is worked out")
        ok = False
    cpp, h = texts[R + "vk_volumetric_light.cpp"], texts[R + "vk_volumetric_light.h"]
    if "std::min<u32>(atlas_cascades, 4)" in cpp or \
            cpp.count("VolumetricOcclusion::Pack(atlas_cascades, atlas_valid,") != 1 or \
            h.count("void SetAtlasCascades(u32 count, u32 valid) noexcept {") != 1:
        print("vk_volumetric_light: the push word is not packed by VolumetricOcclusion::Pack")
        ok = False
    fx = texts[R + "vk_rasterizer_effects.cpp"]
    if fx.count("SetAtlasCascades(") != 1 or fx.count("SetAtlasCascades(count, sun_atlas.valid_mask);") != 1:
        print("vk_rasterizer_effects.cpp: SetAtlasCascades is not called once with the mask")
        ok = False
    # SunQuadrant is declared before the r19 path uses it, and the step sits inside that path.
    declared = fx.find("u32 SunQuadrant(const DynamicState& dynamic, u32 width, u32 height);")
    short = fx.find("++r19_stats.sun_short;")
    step = fx.find("a.drawn_mask |= 1u << quadrant;")
    live = fx.find(fix("    if (live) {\n        // r12: every draw sampling", "\r\n" if "\r\n" in fx else "\n"))
    full = fx.find("a.mask_spread += quadrant == 4 || quadrant == 5 ? 1u : 0u;")
    cascade = fx.find("    const u32 cascade = (east ? 1u : 0u) | (south ? 2u : 0u);")
    if not (0 < declared < short < step < live < full < cascade) or \
            fx.count("a.drawn_mask |= 1u << quadrant;") != 1 or fx.count("++a.cascade_draws[quadrant];") != 1 or \
            not (cascade < fx.find("u32 SunQuadrant(const DynamicState& dynamic, u32 width, u32 height) {")):
        print("vk_rasterizer_effects.cpp: SunQuadrant's declaration or the r19 path's step is out of place")
        ok = False
    # The mask's inputs: r7's lost quadrants, the spread draws; mask_wanted ends with a frame
    # without a resolve; r14's re-clear within an atlas frame drops the draws before it.
    if fx.count(".held_lost = sun_hold.stale | sun_hold.pending_clear,") != 1 or \
            fx.count(".spread = sun_atlas.mask_spread != 0,") != 1 or \
            fx.count("a.mask_wanted = false;") != 1 or \
            not (fx.find("a.mask_wanted = false;") < fx.find("    a.resolved = false;") <
                 fx.find("a.drawn_mask = 0;")) or \
            fx.count(fix("            k.cleared = 0xFu;\n", "\r\n" if "\r\n" in fx else "\n")) != 1 or \
            not (fx.find(fix("            k.cleared = 0xFu;\n", "\r\n" if "\r\n" in fx else "\n")) <
                 fx.find("            k.drawn = 0;") <
                 fx.find("the atlas image was reallocated or written within a frame")):
        print("vk_rasterizer_effects.cpp: the mask's inputs or resets are not where the patch puts them")
        ok = False
    rh = texts[R + "vk_rasterizer.h"]
    if rh.count("u32 valid_mask = 0xF;") != 1 or rh.count("bool mask_wanted = false;") != 1 or \
            rh.count("u32 mask_spread = 0, spread_frames = 0;") != 1:
        print("vk_rasterizer.h: sun_atlas lacks the patch's fields")
        ok = False
    # The header's layout and the shader's decoding agree.
    if HEADER.count("(count < 4 ? count : 4u) | (valid & 0xFu) << 8 | (bits & 0xFFu) << 16") != 1 or \
            HEADER.count("SkipEmpty = 1, Darkest = 2, Robust = 4;") != 1 or \
            comp.count("const uint OcclusionDarkest = 2u, OcclusionRobust = 4u;") != 1:
        print("volumetric_occlusion.h and volumetric_light.comp disagree on the push word")
        ok = False
    if texts[G + "CMakeLists.txt"].count("add_executable(volumetric-occlusion-test ") != 1:
        print("CMakeLists.txt: the test target is not there once")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts (None: the file is deleted), or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    # New files: CRLF as the tree's sources; apply wants none there, revert the patch's own text.
    for path, text in NEW_FILES.items():
        exists = os.path.exists(path)
        if mode != "revert":
            if exists:
                if not quiet:
                    print("already there: %s" % path)
                return None
            out[path] = fix(text, "\r\n")
        else:
            if not exists or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("missing or changed since apply (not deleted): %s" % path)
                return None
            out[path] = None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r51_volumetric-leak.py check|apply|revert   (the tree: R51_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file); a file to delete goes last. If a step
    # fails, what was already done is put back from the texts read at the start, so the tree is
    # never left half patched.
    before = {path: open(path, "rb").read() if os.path.exists(path) else None for path in out}
    done = []
    try:
        for path, t in out.items():
            if t is not None:
                with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                    f.write(t)
        for path, t in out.items():
            if t is not None:
                os.replace(path + TMP, path)
                done.append(path)
        for path, t in out.items():
            if t is None:
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
