// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r101_lamp-moving-edge): BB_LAMP_SHADOW_MOVING_EDGE, the half-resolution lamp shadows
// (graphics_lamp_shadow_half=1) share a 2x2 block's answer only once it has settled. Behind a
// moving shadow the first pass's guards (reject, clamp, trail) give up a block pixel's history, and
// its answer is then one frame's ray, 0 or 1; nine such answers can agree by chance on the dark or
// lit side of a penumbra, and the block's other three pixels took that bare answer and the block's
// young history with it (point_shadow_ray.comp HalfAnswer, HALF_YOUNG): squares of 2x2 pixels on a
// moving edge. 0 (the default): as before. 1: a block's answer is taken only where its pixel kept
// more than half a frame of history through this frame's guards (history_cur b = frames + 1 > 1.5,
// as the first pass just wrote it) and the mean of its last few frames (a) lies within 0.125 of its
// ratio. 2 (show): the same with 1/64 (the frames test stays: two equal rays after a cut pass it).
// An un-shared pixel shows its own rays (finer noise in place of 2x2 steps). Read once, at the
// first lamp pass. No Vulkan here.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "video_core/renderer_vulkan/lamp_shadow_tune.h"

namespace Vulkan {

/// Word 0 of the lamp pass's tuning words, read only by the HALF builds of point_shadow_ray.comp
/// (MOVING_EDGE_ON, MOVING_EDGE_SHOW): bit 3 on, bit 2 the show setting. LampTuneWords leaves both
/// clear; PointShadow::Flush ORs them in after it (LampMovingEdgeBits).
inline constexpr std::uint32_t LampTuneMovingEdge = 1u << 3, LampTuneMovingEdgeShow = 1u << 2;
static_assert(((LampTuneMovingEdge | LampTuneMovingEdgeShow) &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) |
                LampTuneDiscEach | (1u << 25) | LampTuneSpatial)) == 0, // r101b: r91, r92 (pending), r93
              "bbport (r101_lamp-moving-edge): word 0 bits 2 and 3 must be free");

/// BB_LAMP_SHADOW_MOVING_EDGE as a whole number 0 to 2 (3 or more: 2; below 0: 0); text that is not
/// a whole number, or nothing: 0.
inline std::uint32_t LampMovingEdgeParse(const char* text) {
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

/// The knob, read once (the first call), with its line in the log when it is on.
inline std::uint32_t LampMovingEdgeValue() {
    static const std::uint32_t value = [] {
        const std::uint32_t v = LampMovingEdgeParse(std::getenv("BB_LAMP_SHADOW_MOVING_EDGE"));
        if (v != 0) {
            std::printf("Ray traced lamps (r101): moving edge %u (BB_LAMP_SHADOW_MOVING_EDGE): at half "
                        "resolution a 2x2 block's answer is shared only once it has settled (history "
                        "kept this frame, last frames within %s); else the pixel casts its "
                        "own ray. Only graphics_lamp_shadow_half=1 with soft or softer lamps\n",
                        unsigned(v), v == 1 ? "0.125" : "1/64 (show)");
        }
        return v;
    }();
    return value;
}

/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).
inline std::uint32_t LampMovingEdgeBits() {
    const std::uint32_t v = LampMovingEdgeValue();
    return v == 0 ? 0u : v == 1 ? LampTuneMovingEdge : (LampTuneMovingEdge | LampTuneMovingEdgeShow);
}

/// PointShadow::OnFrameEnd's half-resolution line (every 600 frames), when the knob is on: young =
/// second-pass pixels a counted pass sent to their own rays by this rule (half_counts word 14, mean
/// per counted pass), traced = all second-pass pixels it traced (word 5).
inline void LampMovingEdgeLine(double young, double traced) {
    if (LampMovingEdgeValue() == 0) {
        return;
    }
    std::printf("Ray traced lamps (r101): a counted half-resolution pass sent %.0f second-pass pixels to "
                "their own rays because their block's answer was young (of %.0f it traced; "
                "BB_LAMP_SHADOW_MOVING_EDGE=%u)\n",
                young, traced, unsigned(LampMovingEdgeValue()));
}

} // namespace Vulkan
