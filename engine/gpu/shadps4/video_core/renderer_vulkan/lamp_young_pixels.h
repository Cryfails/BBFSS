// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG, the lamp shadows' young pixels. Where the
// guards against trails (the reject, the window clamp, the trail cap, the unsure cut) give a pixel's
// history up at a moving shadow's edge, its ratio was this frame's bare ray, 0 or 1, for a frame or
// two: a ragged, hatched moving edge. 0 (the default): as before. 1: in the centred window's resolve
// (BB_LAMP_SHADOW_WINDOW=2, the default) a pixel the guards left fewer than 2 frames takes a mean of
// this frame's answers on its own surface by 1 - smoothstep(0.5, 2, frames) (point_shadow_ray.comp
// youngMean; word 0 bit 27). 2: 1, and where the window clamp gives a history up the pixel keeps the
// clamped value with up to one frame (bit 28; a test setting: that value lies at the edge of the
// clamp's bound toward the old shadow, so it can leave a faint trail). Read once, at the first call.
// No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "lamp_shadow_tune.h"

namespace Vulkan {

/// Word 0 of the lamp pass's tuning words, read only by the CENTRED builds' resolve: bit 27 the young
/// pixels' mean, bit 28 the clamp's kept frame (the value 2). LampTuneWords leaves both clear;
/// PointShadow::Flush ORs them in after it (LampYoungBits).
inline constexpr std::uint32_t LampTuneYoung = 1u << 27, LampTuneYoungKeep = 1u << 28;
// Free: none of LampTuneWords' bits, the view's field or r63's card cap, nor r101's bits 2 and 3, r91's
// 24, r92's 25 or r93's 26 (LampTuneSpatial).
static_assert(((LampTuneYoung | LampTuneYoungKeep) &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | LampTuneSpatial | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) | (1u << 24) | (1u << 25))) == 0,
              "bbport (r103_lamp-young-pixels): word 0 bits 27 and 28 must be free");
// bbport (r103b_lamp-young-standing): bit 29, BB_LAMP_SHADOW_YOUNG_STILL, the standing rule; set only with
// bit 27 (LampYoungBits), read only by the CENTRED builds' resolve (point_shadow_ray.comp, main's young block).
inline constexpr std::uint32_t LampTuneYoungStill = 1u << 29;
static_assert((LampTuneYoungStill &
               (LampTuneYoung | LampTuneYoungKeep | LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |
                LampTuneWindow | LampTuneCentred | LampTuneSpatial | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) | (1u << 24) | (1u << 25))) == 0,
              "bbport (r103b_lamp-young-standing): word 0 bit 29 must be free");

/// BB_LAMP_SHADOW_YOUNG as a whole number 0 to 2 (3 or more: 2; below 0: 0); text that is not a whole
/// number, or nothing: 0.
inline std::uint32_t LampYoungParse(const char* text) {
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

/// The bits for a pass with the knob at `value`: none without the centred window (only its resolve
/// reads them; BB_LAMP_SHADOW_WINDOW 0 and 1 have no resolve).
inline constexpr std::uint32_t LampYoungBitsFor(std::uint32_t value, const LampShadowTune& tune) {
    return value == 0 || !tune.window || !tune.window_centred ? 0u
           : value == 1                                       ? LampTuneYoung
                                                              : (LampTuneYoung | LampTuneYoungKeep);
}

/// The knob, read once (the first call).
inline std::uint32_t LampYoungValue() {
    static const std::uint32_t value = LampYoungParse(std::getenv("BB_LAMP_SHADOW_YOUNG"));
    return value;
}

/// bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL: on (the default) unless it is the whole
/// number 0, which keeps r103's young pixels as they were (for comparison); text that is not a whole
/// number, or nothing: on.
inline bool LampYoungStillParse(const char* text) {
    if (!text || !text[0]) {
        return true;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !LampTuneDetail::Ends(end)) {
        return true;
    }
    return value != 0;
}

/// bbport (r103b_lamp-young-standing): the standing rule's knob, read once (the first call).
inline bool LampYoungStillValue() {
    static const bool value = LampYoungStillParse(std::getenv("BB_LAMP_SHADOW_YOUNG_STILL"));
    return value;
}

/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).
inline std::uint32_t LampYoungBits(const LampShadowTune& tune) {
    const std::uint32_t bits = LampYoungBitsFor(LampYoungValue(), tune);
    // bbport (r103b_lamp-young-standing): bit 29 with bit 27, unless BB_LAMP_SHADOW_YOUNG_STILL=0
    return bits != 0u && LampYoungStillValue() ? bits | LampTuneYoungStill : bits;
}

/// bbport (r103b_lamp-young-standing): PointShadow::Ready, once, right after r103's line (so only with
/// BB_LAMP_SHADOW_YOUNG set): the standing rule, on or off first. centred: as LampYoungStartLine's.
inline void LampYoungStillStartLine(bool centred) {
    std::printf("Ray traced lamps (r103b): standing rule %s (BB_LAMP_SHADOW_YOUNG_STILL=%u; 0: r103 as it was): "
                "under a lamp that stepped under 0.01 m only the reject's and the clamp's cut of the history found "
                "where the surface was makes a pixel young, not the follow, trail cap or unsure cut\n",
                centred && LampYoungStillValue() ? "on" : "off", LampYoungStillValue() ? 1u : 0u);
}

/// PointShadow::Ready, once, when the knob is set: on or off and why first (the slot runs keep 300
/// characters of a line). centred: the centred window's builds were made; spatial: BB_LAMP_SHADOW_SPATIAL.
inline void LampYoungStartLine(bool centred, bool spatial) {
    const std::uint32_t v = LampYoungValue();
    if (v == 0) {
        return;
    }
    std::printf("Ray traced lamps (r103): young pixels %s (BB_LAMP_SHADOW_YOUNG=%u%s): a pixel whose history "
                "the guards just gave up (fewer than 2 frames left) shows the mean of this frame's answers "
                "within 2 px on its surface (5x5; 3x3 without history and in the half-resolution first pass) "
                "by 1 - smoothstep(0.5, 2, frames), not its bare ray; every guard against trails takes the raw "
                "answer; BB_LAMP_SHADOW_SPATIAL=%u (1: the larger of the two shares); %s; nothing with sharp "
                "lamps, BB_LAMP_SHADOW_HISTORY below 2/3, views 2, 3 and 7\n",
                centred ? "on" : "off", unsigned(v),
                centred ? ""
                        : "; it needs the centred window, BB_LAMP_SHADOW_WINDOW=2, which this run does not have "
                          "(not set, or its build could not be made)",
                spatial ? 1u : 0u,
                v == 2 ? "2: where the clamp gives a history up it keeps the clamped value with one frame "
                         "(a test setting; can leave a faint trail)"
                       : "the clamp's cut stays as it was");
    LampYoungStillStartLine(centred); // bbport (r103b_lamp-young-standing)
}

namespace LampYoungDetail {
inline std::uint32_t passes = 0; ///< passes whose resolve ran with bit 27 since the last line
} // namespace LampYoungDetail

/// PointShadow::Flush, once a pass: `ran` = the pass is split into the centred trace and resolve, has
/// the repair and bit 27, and its history may hold 2 frames (LampHistoryFrames, word 30: the shader's
/// own test).
inline void LampYoungPass(bool ran) {
    LampYoungDetail::passes += ran ? 1u : 0u;
}

/// PointShadow::TrackLamps, right after the r42 lamp line (a short line of its own, at its times),
/// when the knob is set.
inline void LampYoungLine() {
    if (LampYoungValue() != 0) {
        std::printf("Ray traced lamps (r103): %u ray traced lamp passes ran their resolve with the young "
                    "pixels' mean (BB_LAMP_SHADOW_YOUNG=%u) since the r42 line before\n",
                    unsigned(LampYoungDetail::passes), unsigned(LampYoungValue()));
    }
    LampYoungDetail::passes = 0;
}

/// PointShadow::OnFrameEnd's half-resolution block (every 600 frames), when the knob is set: young =
/// the rise of half_counts word 13 since its last line (the young pixels that took a mean in one 2x2
/// block in four, added by every half-resolution resolve; read with the counted passes' copy, so a
/// few passes late), passes = half-resolution passes in those frames (all of them, split into a
/// resolve or not).
inline void LampYoungHalfLine(double young, std::uint32_t passes, std::uint32_t frames, double sway = -1.0) {
    if (LampYoungValue() == 0) {
        return;
    }
    // bbport (r103b_lamp-young-standing): sway = the rise of half_counts word 15, the young pixels of one 2x2
    // block in four whose share the standing rule cut (fully: not in `young`; partly: in both); said only
    // with the rule's knob on
    if (LampYoungStillValue() && sway >= 0.0) {
        std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                    "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames); r103b: "
                    "about %.0f a pass had their share cut as sway (lamp step under 0.01 m)\n",
                    passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames),
                    passes != 0 ? 4.0 * sway / double(passes) : 0.0);
        return;
    }
    std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames)\n",
                passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames));
}

} // namespace Vulkan
