# r113_lamp-softness: FEATURE patch (lamp work: lamp shadow softness, the port the 2026-11-15 22:31 round
# asked for). Off by default behind BB_LAMP_SHADOW_FLAME (environment only; a menu row comes later).
#
# What the tree has already: r48's setting graphics_lamp_shadow_softness (sharp 0 m, soft 0.1 m, softer
# 0.2 m; ini key, live in-game menu row, BB_LAMP_SHADOW_SOFT wins) IS applied and built; r91's
# BB_LAMP_SHADOW_RADIUS_PER_LAMP scales each lamp's disc from it. The disc already widens every penumbra
# with the distance behind the caster. What it does not do is look like a flame: its light is even over
# the disc, so a far shadow becomes one broad, low-contrast ramp (the 2026-11-14 run: softer "almost
# washes out"), and a near one is no crisper than the disc allows.
#
# What r113 adds (one knob, three values; 0 = today's picture):
#  0 (default, not set, not a whole number): the even disc, as before.
#  1 flame: half of the lamp's light in a core of 0.5 x the disc's radius, half in an envelope of 2 x
#    the radius. Across a straight shadow edge: 20-80% of the light over 0.85 radii (disc: 0.98), 2-98%
#    over 3.3 radii (disc: 1.8) (scratch r113_profile.py). A crisper edge with a faint fringe twice as
#    wide; both widen with the distance behind the caster as before.
#  2 tall flame: 1 with the flame half as wide as it is tall (world up; the projection of that
#    ellipsoid on the plane square to the ray). From the side: shadow sides about twice as crisp
#    (middle 0.42 radii), tops and tips as soft as 1.
# The disc's radius (soft/softer, BB_LAMP_SHADOW_SOFT, or each lamp's own with
# BB_LAMP_SHADOW_RADIUS_PER_LAMP) is the unit; sharp and every pass with point lamps are untouched (the
# shader's code sits inside lampVisibility's `radius > 0` branch). A ray to a flame point at distance s
# from the lamp's centre is blind max(s - radius, 0) further from its target than the disc's rule (so
# the lamp's centre stays blind to every ray, as LampPassClearance promises for the disc).
#
# Off: LampFlameBits() is 0, word 0 bits 11 and 23 stay clear, the shader's t_flame stays 0 and its one
# new branch (`if (t_flame != 0u)`, the same for the whole dispatch) is not taken: every statement of
# before runs on the same values. The four RESOLVE builds (no rays) keep their SPIR-V words (all new
# shader text is inside #ifndef RESOLVE). The host: per lamp pass one knob read (a static, or with the
# test tools an atomic load) and a compare. On: no more rays, no memory; per lamp ray, next to its ray
# query, a few dozen arithmetic steps (two square roots, a sine and a cosine, a length; 2: also two
# dots, an inverse square root and a square root). The wider fringe puts more of the screen into
# penumbra, so at half resolution the second pass traces more pixels (as softer does; not measured).
#
# Review fixes (2026-11-15, r113_lamp-softness.fixed.py; the draft r113_lamp-softness.py stays):
#  - Bits 11 and 23 in place of 18 and 19: r114_layered-lamp-shadows (drafted at the same time) takes
#    word 0 bits 4-7, 18-19 and 30, and its check refused a tree with the draft's "(f >> 18u) & 3u".
#    The static_assert now also keeps r114's bits out.
#  - The knob is a live test knob when the test tools' bbport_live_knobs.h is in the tree (r84; the
#    r114 pattern): one slot game can take the knob-off twin and the knob-on picture seconds apart, so
#    the slot jobs need no twin from another run. Without that header (a feature branch) it is read
#    once, as before. The once-line is said again at each change; the counter starts again.
#  - The counter counts a pass as "acted" when the shader's flame code runs (the repair's words, a
#    disc in word 2, not zeroed for an unread history), not only when the pass averages.
#  - Texts: the cost, "read at start", and the blind distance with BB_LAMP_SHADOW_RADIUS_PER_LAMP
#    (discs up to LampDiscCap 0.5 m, so up to 0.5 m more blind, not 0.2 m).
#
# Files: new renderer_vulkan/lamp_flame.h (knob, bits, shape constants, C++ copy of the radius, log
# lines). Hooks: point_shadow_ray.comp (t_flame before t_frame, its read in loadTune before t_frame's,
# flameOffset after samplePoint, the block after the disc's target line; none goes between r91's texts
# and their anchors, which r91's check wants next to each other), vk_point_shadow.cpp (include; Flush: data[tune_at] |= LampFlameBits(); the pass
# count after r48's history_radius_m line), test_lamp_shadow_tune.cpp (include, a test block), README.md
# (a row before the BB_LAMP_SHADOW_HALF row, so after the softness rows: BB_LAMP_SHADOW_SOFT and r91's).
#
# Every edit only inserts text before or after an anchor that it keeps whole; check and revert find each
# inserted text by itself (exactly once), so patches that insert next to the same anchors (r101, r103,
# r93 after the tune_words insert) can come and go in any order.
#
# Use: python -I -X utf8 r113_lamp-softness.fixed.py check | apply | revert
# Root: R113_ROOT, else <tree>. Line ends kept (CRLF in the tree; the new header is written CRLF).
# apply backs the originals up in r113_backup next to this script; revert removes the new header.
import os
import re
import sys

ROOT = os.environ.get("R113_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r113_backup")
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
U = "engine/tests/test_lamp_shadow_tune.cpp"
R = "README.md"
NEW = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_flame.h"

HEADER = r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME, how a lamp's light is spread over the disc its
// shadow rays go to (point_shadow_ray.comp flameOffset). A small flame is no even disc: most of its
// light comes from a bright core inside a larger, dimmer envelope, and it is taller than it is wide.
//  - 0 (the default, also when not set or not a whole number): the even disc, as before.
//  - 1 (flame): LampFlameCoreShare of the light in a core of LampFlameCore x the disc's radius, the
//    rest in an envelope of LampFlameReach x the radius (each even over its area). Across a straight
//    shadow edge the middle (20% to 80% of the light) is 0.85 radii wide against the disc's 0.98, and
//    the outer fringe (2% to 98%) 3.3 radii against 1.8 (scratch r113_profile.py): a crisp edge with a
//    faint fringe twice as wide, which like every penumbra widens with the distance behind the caster.
//  - 2 (tall flame): 1 with the flame LampFlameSlim as wide as it is tall (world up): seen from the
//    side, the sides of its shadows are about twice as crisp (middle 0.42 radii), their tops and tips
//    as soft as with 1; seen from straight above or below it is round and LampFlameSlim as large.
// The disc's radius stays what it was: graphics_lamp_shadow_softness (or BB_LAMP_SHADOW_SOFT), or each
// lamp's own with BB_LAMP_SHADOW_RADIUS_PER_LAMP. Sharp (radius 0) and every pass with point lamps are
// not touched. A ray to a point of the flame beyond the disc's radius is blind that much further from
// its target than the disc's rule says, so the lamp's own model at its centre stays blind to every ray.
// The rays are as many as before. Read at the first lamp pass; with the test tools' live knobs
// (gpu/shim/bbport_live_knobs.h, BB_LIVE_KNOBS_FILE) asked again at every pass, so one running game
// can switch it; without that header (a feature branch) read once. No Vulkan here:
// tests/test_lamp_shadow_tune.cpp builds it.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "lamp_shadow_tune.h"
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_SHADOW_FLAME_LIVE 1
#else
#define BB_LAMP_SHADOW_FLAME_LIVE 0
#endif

namespace Vulkan {

/// Word 0 of the lamp pass's tuning words: bit 11 the flame (values 1 and 2), bit 23 the tall
/// flame (value 2). The shader reads ((word 0 >> 11) & 1) * (1 + ((word 0 >> 23) & 1)) (LampFlameOf).
/// LampTuneWords leaves them clear; PointShadow::Flush ORs them in after it (LampFlameBits).
inline constexpr std::uint32_t LampTuneFlame = 1u << 11, LampTuneFlameTall = 1u << 23;
// Free: none of LampTuneWords' bits, the view's field (8-10), the card cap (12-17), r101's bits 2 and
// 3, the per-lamp disc's 24, the colour's 25, 26 (LampTuneSpatial), 27 to 29 (r103, r103b), nor the
// bits r114_layered-lamp-shadows takes (4-7, 18-19, 30).
static_assert(((LampTuneFlame | LampTuneFlameTall) &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | LampTuneSpatial | LampTuneDiscEach | LampTuneColour | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) | (7u << 27) | (15u << 4) |
                (3u << 18) | (1u << 30))) == 0,
              "bbport (r113_lamp-softness): word 0 bits 11 and 23 must be free");

/// The flame's shape, in radii of the disc (point_shadow_ray.comp FLAME_CORE, FLAME_CORE_SHARE,
/// FLAME_REACH, FLAME_SLIM hold the same numbers; the patch script checks both).
inline constexpr float LampFlameCore = 0.5f, LampFlameCoreShare = 0.5f, LampFlameReach = 2.0f, LampFlameSlim = 0.5f;
/// The share of the light within the core's radius (core and the envelope's middle): 0.53125.
inline constexpr float LampFlameSplit =
    LampFlameCoreShare + (1.0f - LampFlameCoreShare) * (LampFlameCore / LampFlameReach) * (LampFlameCore / LampFlameReach);

/// point_shadow_ray.comp flameOffset's radius in C++ (for the test): the distance from the lamp's
/// centre, in radii of the disc, within which the share `u` (0 to 1) of the flame's light lies, the
/// inverse of F(r) = LampFlameCoreShare min(r / LampFlameCore, 1)^2 + (1 - LampFlameCoreShare)
/// (r / LampFlameReach)^2. The shader's u walks the unit square evenly over the frames (samplePoint),
/// so the rays go to the flame as its light lies.
inline float LampFlameRadius(float u) {
    const float w = LampFlameCoreShare;
    return u <= LampFlameSplit
               ? std::sqrt(u / (w / (LampFlameCore * LampFlameCore) + (1.0f - w) / (LampFlameReach * LampFlameReach)))
               : LampFlameReach * std::sqrt((u - w) / (1.0f - w));
}

/// BB_LAMP_SHADOW_FLAME as a whole number 0 to 2 (3 or more: 2; below 0: 0); text that is not a whole
/// number, or nothing: 0.
inline std::uint32_t LampFlameParse(const char* text) {
    if (!text || !text[0]) {
        return 0;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !LampTuneDetail::Ends(end)) {
        return 0;
    }
    return std::uint32_t(std::clamp(value, 0l, 2l));
}

/// The word 0 bits of a value (0: none; 1: the flame; 2 or more: the tall flame).
inline constexpr std::uint32_t LampFlameBitsFor(std::uint32_t value) {
    return value == 0u ? 0u : value == 1u ? LampTuneFlame : (LampTuneFlame | LampTuneFlameTall);
}

/// The value the shader reads from word 0 (point_shadow_ray.comp loadTune, t_flame), for the test.
inline constexpr std::uint32_t LampFlameOf(std::uint32_t word0) {
    return ((word0 >> 11) & 1u) * (1u + ((word0 >> 23) & 1u));
}

namespace LampFlameDetail {
inline std::uint32_t passes = 0; ///< passes that took the lamp history since the last line (or change)
inline std::uint32_t flamed = 0; ///< of them, where the shader's flame code ran
inline std::uint32_t told = 0;   ///< the value the last once-line said (0: none said, or off)
} // namespace LampFlameDetail
/// The r113 line's period, in passes that take the lamp history (about one a frame).
inline constexpr std::uint32_t LampFlameLinePasses = 600;

/// The knob, with its line in the log when it is first on and again at each change (a live knob).
inline std::uint32_t LampFlameValue() {
#if BB_LAMP_SHADOW_FLAME_LIVE
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_SHADOW_FLAME", LampFlameParse};
    const std::uint32_t v = knob.Get();
#else
    static const std::uint32_t v = LampFlameParse(std::getenv("BB_LAMP_SHADOW_FLAME"));
#endif
    if (v != LampFlameDetail::told) {
        LampFlameDetail::told = v;
        LampFlameDetail::passes = LampFlameDetail::flamed = 0;
        if (v != 0) {
            std::printf("Ray traced lamps (r113): flame %u on (BB_LAMP_SHADOW_FLAME): %s; the disc's radius as "
                        "the softness setting has it; sharp lamps and passes with point lamps unchanged; no "
                        "more rays\n",
                        unsigned(v),
                        v == 1 ? "half the light in a core of 0.5 radii, half in an envelope of 2 radii"
                               : "the flame of 1, half as wide as it is tall");
        } else {
            std::printf("Ray traced lamps (r113): flame off (BB_LAMP_SHADOW_FLAME): the even disc again\n");
        }
    }
    return v;
}

/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).
inline std::uint32_t LampFlameBits() {
    return LampFlameBitsFor(LampFlameValue());
}

/// PointShadow::Flush, once a pass that takes the lamp history: `flamed` = the shader's flame code
/// runs in it (the repair's words are there and word 2's radius is above 0: not sharp, not a pass
/// with point lamps, not zeroed for an unread history). With the knob on, every LampFlameLinePasses
/// such passes a line says on how many the flame acted. Nothing when off.
inline void LampFlamePass(bool flamed) {
    if (LampFlameValue() == 0) {
        return;
    }
    ++LampFlameDetail::passes;
    LampFlameDetail::flamed += flamed ? 1u : 0u;
    if (LampFlameDetail::passes >= LampFlameLinePasses) {
        std::printf("Ray traced lamps (r113): flame %u acted on %u of the last %u passes that took the lamp "
                    "history (the others: sharp, or point lamps for now)\n",
                    unsigned(LampFlameValue()), unsigned(LampFlameDetail::flamed), unsigned(LampFlameDetail::passes));
        LampFlameDetail::passes = LampFlameDetail::flamed = 0;
    }
}

} // namespace Vulkan
"""

FLAME_FN = """#ifndef RESOLVE
// bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME (word 0 bits 11 and 23, t_flame; renderer_vulkan/
// lamp_flame.h). A small flame is no even disc: most of its light comes from a bright core inside a
// larger, dimmer envelope, and it is taller than it is wide. The offset from the lamp's centre of the
// point a ray goes to, for the disc's radius `radius` and the disc's axes u, v (square to dir, the way
// from the ray's start to the lamp):
//  - 1: FLAME_CORE_SHARE of the light in a core of FLAME_CORE x radius, the rest in an envelope of
//    FLAME_REACH x radius, each even over its area: the distance is the inverse of the light's share
//    F(r) = s min(r / FLAME_CORE, 1)^2 + (1 - s) (r / FLAME_REACH)^2 at xi.x (which walks the unit
//    square evenly over the frames, samplePoint, so the rays go where the light is); split = F(core).
//    A shadow edge: 20-80% of the light over 0.85 radii (the disc: 0.98), 2-98% over 3.3 (1.8).
//  - 2: that flame FLAME_SLIM as wide as it is tall along the world's up (t_axis_b): the ellipsoid's
//    outline seen along dir, FLAME_SLIM across and k = sqrt(slim^2 + (1 - slim^2) sin^2) along the up
//    seen in the disc's plane (sin: of the angle between dir and up; seen from straight above: slim).
//    From the side the sides of a shadow get about twice as crisp (20-80% over 0.42 radii), its tips
//    stay as with 1.
const float FLAME_CORE = 0.5;
const float FLAME_CORE_SHARE = 0.5;
const float FLAME_REACH = 2.0;
const float FLAME_SLIM = 0.5;
vec3 flameOffset(float radius, vec2 xi, vec3 u, vec3 v, vec3 dir) {
    const float s = FLAME_CORE_SHARE;
    const float split = s + (1.0 - s) * (FLAME_CORE / FLAME_REACH) * (FLAME_CORE / FLAME_REACH);
    const float r = xi.x <= split
                        ? sqrt(xi.x / (s / (FLAME_CORE * FLAME_CORE) + (1.0 - s) / (FLAME_REACH * FLAME_REACH)))
                        : FLAME_REACH * sqrt((xi.x - s) / (1.0 - s));
    const float a = 6.2831853 * xi.y;
    vec3 o = (radius * r) * (cos(a) * u + sin(a) * v);
    if (t_flame >= 2u) {
        const vec3 up = t_axis_b - dir * dot(dir, t_axis_b);
        const float sin2 = min(dot(up, up), 1.0);
        o *= FLAME_SLIM;
        if (sin2 > 1e-6) {
            const vec3 e = up * inversesqrt(sin2);
            const float k = sqrt(FLAME_SLIM * FLAME_SLIM + (1.0 - FLAME_SLIM * FLAME_SLIM) * sin2);
            o += (k / FLAME_SLIM - 1.0) * dot(o, e) * e;
        }
    }
    return o;
}
#endif

"""

FLAME_USE = """#ifndef RESOLVE
            if (t_flame != 0u) {
                // bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME: the point of the flame (flameOffset) in
                // place of the even disc's. Its ray is blind as much further from its target as the point
                // lies beyond the disc's radius, so the lamp's centre stays blind to every ray. The base is
                // this call's blind distance of the disc (word 10's with the per-lamp disc, read just above;
                // else t_clear), so it is set anew at every call and no lamp keeps another's.
                const vec3 o = flameOffset(radius, xi, u, v, dir);
                target = L + o;
                ray_clear += (t_disc_each ? 0.0 : t_clear - ray_clear) + max(length(o) - radius, 0.0);
            }
#endif
"""

TEST = r"""    // bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME (lamp_flame.h): the parse, word 0's bits 11 and
    // 23 (the shader reads ((word 0 >> 11) & 1) * (1 + ((word 0 >> 23) & 1)); LampTuneWords never sets
    // them), and the flame's radius as the shader's flameOffset works it out: from 0 to LampFlameReach,
    // never falling, the core's edge at LampFlameSplit, and the inverse of the share of the light within it.
    {
        assert(LampFlameParse(nullptr) == 0u && LampFlameParse("") == 0u && LampFlameParse("0") == 0u);
        assert(LampFlameParse("1") == 1u && LampFlameParse(" 2 ") == 2u && LampFlameParse("7") == 2u);
        assert(LampFlameParse("-1") == 0u && LampFlameParse("yes") == 0u && LampFlameParse("1x") == 0u);
        assert(LampFlameBitsFor(0u) == 0u && LampFlameBitsFor(1u) == LampTuneFlame &&
               LampFlameBitsFor(2u) == (LampTuneFlame | LampTuneFlameTall) &&
               LampFlameBitsFor(9u) == (LampTuneFlame | LampTuneFlameTall));
        for (std::uint32_t v = 0; v <= 2; ++v) {
            assert(LampFlameOf(LampFlameBitsFor(v)) == v && LampFlameOf(LampFlameBitsFor(v) | 0xFF7FF7FFu) == v);
        }
        assert(LampFlameOf(LampTuneFlameTall) == 0u); // bit 23 alone: no flame
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert((LampTuneWords(d, true, 0.05f)[0] & (LampTuneFlame | LampTuneFlameTall)) == 0u);
        assert(std::fabs(LampFlameSplit - 0.53125f) < 1e-6f);
        float last = -1.0f;
        for (int i = 0; i <= 1000; ++i) {
            const float u = float(i) / 1000.0f;
            const float r = LampFlameRadius(u);
            assert(r >= last && r >= 0.0f && r <= LampFlameReach + 1e-5f);
            const float c = std::min(r / LampFlameCore, 1.0f);
            const float share = LampFlameCoreShare * c * c +
                                (1.0f - LampFlameCoreShare) * (r / LampFlameReach) * (r / LampFlameReach);
            assert(std::fabs(share - u) < 1e-4f);
            last = r;
        }
        assert(LampFlameRadius(0.0f) == 0.0f && std::fabs(LampFlameRadius(1.0f) - LampFlameReach) < 1e-5f);
        assert(std::fabs(LampFlameRadius(LampFlameSplit) - LampFlameCore) < 1e-5f);
    }
"""

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
S: [
("uint t_frame = 0u;              // the frame counter (the sample points' sequence)\n",
 "#ifndef RESOLVE\n"
 "uint t_flame = 0u;              // bbport (r113_lamp-softness): BB_LAMP_SHADOW_FLAME (bits 11, 23; flameOffset)\n"
 "#endif\n",
 ""),
("    t_frame = data.d[at + 3u];\n",
 "#ifndef RESOLVE\n"
 "    t_flame = ((f >> 11u) & 1u) * (1u + ((f >> 23u) & 1u)); // bbport (r113_lamp-softness)\n"
 "#endif\n",
 ""),
("    return fract(start + vec2(walked >> 8u) * (1.0 / 16777216.0));\n}\n",
 "",
 "\n" + FLAME_FN.rstrip("\n") + "\n"),
("            target += (radius * sqrt(xi.x)) * (cos(a) * u + sin(a) * v); // bbport (r91): was t_radius\n",
 "",
 FLAME_USE),
],
C: [
("#include \"video_core/renderer_vulkan/vk_camera_motion.h\"\n",
 "#include \"video_core/renderer_vulkan/lamp_flame.h\" // bbport (r113_lamp-softness)\n",
 ""),
("            data.insert(data.end(), tune_words.begin(), tune_words.end());\n",
 "",
 "            data[tune_at] |= LampFlameBits(); // bbport (r113_lamp-softness): bits 11, 23; 0 when off\n"),
("        history_radius_m = pass_tune.radius_m; // bbport (r48_lamp-softness)\n",
 "",
 "        LampFlamePass(repair && !unread && pass_tune.radius_m > 0.0f); // bbport (r113_lamp-softness): its line\n"),
],
U: [
("#include \"gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h\"\n",
 "",
 "#include \"gpu/shadps4/video_core/renderer_vulkan/lamp_flame.h\" // bbport (r113_lamp-softness)\n"),
("    std::puts(\"lamp shadow tune: ok\");\n",
 TEST,
 ""),
],
# README.md: readme_edit (the row after the BB_LAMP_SHADOW_SOFT row)
}

ROW = ("| `BB_LAMP_SHADOW_FLAME` | How a lamp's light is spread over the disc its shadow rays go to (soft or softer "
       "lamps; with `BB_LAMP_SHADOW_RADIUS_PER_LAMP` each lamp's own disc). `1` (flame): half the light in a bright "
       "core of half the disc's radius, half in a dim envelope of twice the radius, so a shadow's edge is a little "
       "crisper in its middle (20% to 80% of the light across 0.85 radii against the even disc's 0.98) and its faint "
       "outer fringe reaches about twice as far (2% to 98%: 3.3 radii against 1.8); like every penumbra both widen "
       "with the distance behind the caster. `2` (tall flame): the flame of `1` half as wide as it is tall, so seen "
       "from the side the sides of its shadows are about twice as crisp (middle 0.42 radii) and their tops and tips "
       "as soft as with `1`. A ray to a point of the flame beyond the disc's radius is blind that much further from "
       "its target (up to one disc radius more: 0.1 m with soft, 0.2 m with softer, up to 0.5 m with the largest "
       "discs of `BB_LAMP_SHADOW_RADIUS_PER_LAMP`), so the lamp's own model stays unseen and thin things right next "
       "to the flame (the hand holding a torch) can cast fainter shadows. Sharp lamps and passes with point lamps do "
       "not change. No more rays and no memory, a few arithmetic steps a ray; at half resolution the wider fringe "
       "makes the second pass trace more pixels, as softer does. Read at the first lamp pass (with the test tools' "
       "live knobs file, again after each change). Log: \"(r113)\" lines. `0`: the even disc, as before | `0` |\n")


def readme_edit(text):
    """The README row goes before the BB_LAMP_SHADOW_HALF row (the whole line is the anchor), so it follows
    the softness rows (BB_LAMP_SHADOW_SOFT, then r91's, which r91's check wants right after the SOFT row)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_HALF` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_HALF row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", ROW, "")


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == R:
        return [readme_edit(text)]
    return EDITS[path]


def text_checks(texts, before):
    """The ties a compiler cannot check. before: the texts without this patch."""
    s, h, row = texts[S], HEADER, ROW
    for want, n in (("const float FLAME_CORE = 0.5;", 1), ("const float FLAME_CORE_SHARE = 0.5;", 1),
                    ("const float FLAME_REACH = 2.0;", 1), ("const float FLAME_SLIM = 0.5;", 1),
                    ("t_flame = ((f >> 11u) & 1u) * (1u + ((f >> 23u) & 1u));", 1), ("vec3 flameOffset(", 1),
                    ("flameOffset(radius, xi, u, v, dir)", 1), ("uint t_flame = 0u;", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    if "LampFlameCore = 0.5f, LampFlameCoreShare = 0.5f, LampFlameReach = 2.0f, LampFlameSlim = 0.5f;" not in h or \
            "LampTuneFlame = 1u << 11, LampTuneFlameTall = 1u << 23;" not in h or \
            "return ((word0 >> 11) & 1u) * (1u + ((word0 >> 23) & 1u));" not in h:
        raise SystemExit("text check: lamp_flame.h and the shader's constants or bits disagree")
    if "LampFlamePass(repair && !unread && pass_tune.radius_m > 0.0f);" not in texts[C]:
        raise SystemExit("text check: the counter's condition is not the shader's (repair, a radius, not unread)")
    for n in ("0.85", "0.98", "3.3", "1.8", "0.42"):
        if n not in row or n not in h or n not in s:
            raise SystemExit("text check: %s is not in the README row, the header and the shader alike" % n)
    # every r113 line of the shader lies inside #ifndef RESOLVE (the four RESOLVE builds keep their words)
    mine = re.compile(r"r113|\b(t_flame|flameOffset|FLAME_CORE|FLAME_CORE_SHARE|FLAME_REACH|FLAME_SLIM)\b")
    stack = []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifndef RESOLVE")
        elif st.startswith("#else") or st.startswith("#elif"):
            stack[-1] = False
        elif st.startswith("#endif"):
            stack.pop()
        elif mine.search(line) and not any(stack):
            raise SystemExit("text check: r113 shader line outside #ifndef RESOLVE: %r" % line)
    if stack:
        raise SystemExit("text check: #if and #endif do not pair in the shader")
    # words other patches' checks count in these files: this patch adds none of them
    # (r114_layered-lamp-shadows, drafted at the same time, counts "(f >> 18u) & 3u", "(1u << 30u)",
    # "#ifdef COLOUR", "lampRecord(", "pick_rest = pick_cand;" and r91-r103b's bit tests)
    for path, words in ((S, ("ray_clear = ", "r91", "r93", "r103", "spatial", "young", "1u << 2", "(f >> 18u) & 3u",
                             "(f >> 4u) & 15u", "(1u << 30u)", "#ifdef COLOUR\n", "lampRecord(", "t_halo",
                             "pick_rest = pick_cand;", "1u << 29", "(f & (1u << 25u))")),
                        (C, ("r91", "LampTuneDiscEach", "history_radius_m = pass_tune.radius_m;",
                             "tune.radius_m = LampSoftnessRadius(", "LampLayersBits(", "LampYoungLine();")),
                        (U, ("BB_LAMP_SHADOW_RADIUS_PER_LAMP", "r91")),
                        (R, ("| `BB_LAMP_SHADOW_RADIUS_PER_LAMP` |",))):
        for w in words:
            a, b = texts[path].lower().count(w.lower()), before[path].lower().count(w.lower())
            if a != b:
                raise SystemExit("text check: %s holds %r %d times, %d before this patch" % (path, w, a, b))
    # the flame's block comes after the disc's target line and before the lift onto the surface's plane
    a = s.find("            target += (radius * sqrt(xi.x)) * (cos(a) * u + sin(a) * v);")
    b = s.find("target = L + o;")
    c = s.find("            target += n * max(min(reach, dot(n, L - P)) - dot(n, target - P), 0.0);")
    if not (0 <= a < b < c) or not (s.find("vec3 flameOffset(") < s.find("float lampVisibility(")):
        raise SystemExit("text check: the flame's block is not between the disc's target and the lift")
    cs = texts[C]
    if not (cs.find("LampFlamePass(") > cs.find("bool unread = false;") > 0):
        raise SystemExit("text check: LampFlamePass is not after unread's declaration")


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R113_ROOT)" % ROOT)
    new_full = os.path.join(ROOT, NEW)
    header = HEADER.replace("\n", "\r\n").encode("utf-8")
    new_there = os.path.exists(new_full)
    new_ours = new_there and open(new_full, "rb").read() == header
    plan = []
    for path in (S, C, U, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if state == "applied" and not new_ours:
        raise SystemExit("mixed state: edits applied but %s is %s" % (NEW, "not ours" if new_there else "missing"))
    if state == "clean" and new_there:
        raise SystemExit("mixed state: edits not applied but %s is there" % NEW)

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    def reverted_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in reversed(eds):
                for part in (after, before):
                    if part:
                        cur = cur.replace(part, "", 1)
            if state_of(cur, eds, path) != "clean":
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan}, reverted_texts())
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), {p[0]: p[4] for p in plan})
            print("not applied; would apply (%d files edited, %d edits, 1 new file; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts, {p[0]: p[4] for p in plan})
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r113tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        open(new_full, "wb").write(header)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = reverted_texts()
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r113tmp"
        open(tmp, "wb").write(out[path].replace("\n", eol).encode("utf-8"))
        os.replace(tmp, full)
    os.remove(new_full)
    print("reverted")


main()
