// SPDX-License-Identifier: GPL-3.0-or-later
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
