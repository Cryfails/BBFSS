// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass
// (point_shadow_ray.comp with MODE_REPAIR): the knobs, read once from the environment, the
// sixteen words PointShadow::Flush appends to the pass's data, and the weight of a lamp as the
// shader works it out. No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it alone.
// bbport (r42_lamp-soft): the lamp is an area light now (one ray a frame to a point of its disc,
// averaged over frames in the pass's history); the rim rays of r41 and their knobs are gone.

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace Vulkan {

/// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW when it is not set: 0 the pixel's own
/// last frames, 1 the 5x5 window confined to the 8x8 workgroup (r57, as before), 2 the window
/// centred on every pixel (one more dispatch, see LampShadowTune::window_centred). The one line to
/// change to make 2 the default; tests/test_lamp_shadow_tune.cpp follows it, and the torch lab's
/// default runs (tests/test_rt_shadows.cpp --lamps) then run value 2. 0 as the default also
/// needs the tune test's r57 asserts changed (they hold for a default with the window: 1 or 2).
/// bbport (r72_lamp-window-default): 2 since r72 (in the game +0.01 ms over 1 at full and +0.08 ms
/// at half resolution, and no squares behind the moving torch shadow); 1 was the default before.
inline constexpr std::uint32_t LampWindowDefault = 2;
static_assert(LampWindowDefault <= 2, "BB_LAMP_SHADOW_WINDOW has the values 0, 1 and 2");

struct LampShadowTune {
    bool weights = true;         ///< BB_LAMP_SHADOW_WEIGHTS: the game's falloff times N.L; 0: as before
    bool colour = false;         ///< bbport (r92_lamp-shadow-colour): BB_LAMP_SHADOW_COLOUR: 1: each lamp's
                                 ///< share of a shadow keeps its colour (the COLOUR builds, picked at
                                 ///< start); 0: one grey ratio for all lamps
    float wrap = 0.15f;          ///< BB_LAMP_SHADOW_WRAP, 0..1: N.L tolerance; 1: no N.L
    float facing_floor = 0.05f;  ///< BB_LAMP_SHADOW_FLOOR, 0..1: least facing factor; 0: none
    float radius_m = 0.1f;       ///< BB_LAMP_SHADOW_SOFT, 0..0.5: the lamp's radius; 0: a point
    bool radius_set = false;     ///< bbport (r48_lamp-softness): BB_LAMP_SHADOW_SOFT gave radius_m
                                 ///< (a number): it wins over graphics_lamp_shadow_softness
                                 ///< (LampSoftnessRadius)
    float disc_each = 0.0f;      ///< bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP,
                                 ///< 0..1 per metre of reach: each lamp's own disc (LampDiscRadius) in
                                 ///< the pass that averages; 0: off, radius_m for every lamp
    float history = 0.9f;        ///< BB_LAMP_SHADOW_HISTORY, 0..0.98: share of the frames before
                                 ///< in the shadow ratio; 0: this frame's ray alone
    float reject = 0.5f;         ///< BB_LAMP_SHADOW_REJECT, 0 or 0.45..1: the history is dropped
                                 ///< where the last frames' ratio is this far from it; 0: never
    float trail_m = 0.08f;       ///< BB_LAMP_SHADOW_TRAIL, 0..2: how far a moving lamp's shadows
                                 ///< may trail, metres; 0: its motion does not shorten the history
    bool follow = true;          ///< BB_LAMP_SHADOW_FOLLOW: the history is looked up where a
                                 ///< moving lamp's motion puts it (LampTrack); 0: where the
                                 ///< surface was
    bool follow_soft = true;     ///< bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT: under a
                                 ///< moving lamp the history is looked up at both places (where the
                                 ///< surface was, where the lamp's motion puts it) and mixed by a
                                 ///< follow state each pixel keeps; 0: one of them, picked by the
                                 ///< vote of the 5x5 answers around the pixel (r42)
    bool window = LampWindowDefault >= 1; ///< bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW: 1:
                                 ///< the history is bound by the 5x5 answers around the pixel and
                                 ///< the frames under a moving lamp are capped by their far
                                 ///< blockers' swing, as before r57; 0 (to try): by the pixel's own
                                 ///< last frames and one fixed swing. The window cannot be centred
                                 ///< near the 8x8 workgroup's rim and is the likely source of the
                                 ///< squares fixed to the screen behind moving shadows; without it
                                 ///< a change of less than about 0.86 of the light (a penumbra
                                 ///< that becomes lit, one lamp's part of two) is not cut but fades
                                 ///< like the unguarded history, with one lamp or several. With
                                 ///< BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap keep the
                                 ///< window either way (they have no per-pixel form).
                                 ///< bbport (r60_lamp-centred-window): 2 is 1 with window_centred
    bool window_centred = LampWindowDefault == 2; ///< bbport (r60_lamp-centred-window):
                                 ///< BB_LAMP_SHADOW_WINDOW=2 (with window): the 5x5 window is centred
                                 ///< on every pixel, wherever the workgroup's rim lies, meant to leave
                                 ///< none of its squares and to bind as the window of 1 does (not
                                 ///< measured). The pass that
                                 ///< averages runs as two dispatches (a trace, a resolve; four at
                                 ///< half resolution) with one image more, 8 bytes a pixel
                                 ///< (PointShadow::Flush). Read at start only (the pipelines are
                                 ///< picked then)
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
                                 ///< this distance of it is taken to move with it, metres
    float around = 1.6f;         ///< BB_LAMP_SHADOW_CLAMP, 0 or 0.5..4: the history may lie this
                                 ///< many deviations from this frame's answers around the
                                 ///< pixel; 0: anywhere
    bool spatial = false;        ///< bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL: 1: the
                                 ///< centred window's resolve (window_centred) takes into the history
                                 ///< this frame's answer mixed with the mean of it and its 3x3
                                 ///< neighbours on the pixel's plane, unless the pixel's last frames were all lit
                                 ///< or all dark (point_shadow_ray.comp spatialMean, spatial_u); 0: as
                                 ///< before
    bool stale = false;          ///< BB_LAMP_SHADOW_STALE: 1: starved moving shared copies are left
                                 ///< out of lamp rays (r41); 0: they stay in (vk_rt_shadow.cpp)
    float clearance_m = 0.18f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp
                                 ///< (bbport r90_lamp-clearance-default: 0.18, 0.35 before;
                                 ///< what a pass uses: LampPassClearance)
    float bias_m = 0.03f;        ///< BB_LAMP_SHADOW_BIAS, 0.005..0.2: ray start offset (the push block)
    float self_m = 0.06f;        ///< BB_LAMP_SHADOW_SELF, 0..0.3: grazing self skip
    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..7: debug view (7: r63's cards)
    float view_gain = 0.5f;      ///< BB_LAMP_SHADOW_VIEW_GAIN, 0.01..16
};

inline constexpr std::uint32_t LampTuneWordCount = 16;
// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used), bit 20 the
// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used), bit 21 the
// window (bbport r57_lamp-window, LampTuneWindow), bit 22 the centred window (bbport
// r60_lamp-centred-window, LampTuneCentred; only with bit 21). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
// radius, 4 self skip, 5 wrap, 6 the inverse-square curve's core squared, 7 view gain, 8 facing
// floor, 9 reject. Words 10-12 and 13-15: two axes of the world in view space, unit length and
// square to each other (the frame the lamp's disc is laid out in): world +x (horizontal) and
// world +y (up).
inline constexpr std::uint32_t LampTuneNewWeights = 1, LampTuneInverseSquare = 2;
// bbport (r63_leaf-stage4): view 7, where the lamp rays met cut-out cards (point_shadow_ray.comp)
inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 7;
inline constexpr std::uint32_t LampTuneFollowSoft = 1u << 20; // bbport (r52_follow-soft)
inline constexpr std::uint32_t LampTuneWindow = 1u << 21;     // bbport (r57_lamp-window)
inline constexpr std::uint32_t LampTuneCentred = 1u << 22;    // bbport (r60_lamp-centred-window)
// bbport (r93_lamp-shadow-spatial): bit 26, BB_LAMP_SHADOW_SPATIAL, read only by the CENTRED builds'
// resolve. LampTuneWords leaves it 0; vk_point_shadow.cpp Flush sets it (LampTuneSpatialBit).
inline constexpr std::uint32_t LampTuneSpatial = 1u << 26;
// bbport (r63_leaf-stage4): bits 12-17 the most card candidates a lamp ray tests
// (BB_RT_CARD_LAMP_CAP; 0: the shader's default). LampTuneWords leaves them 0; vk_point_shadow.cpp
// Flush sets them for a pass that binds the CARDS build.
inline constexpr std::uint32_t LampTuneCardCapShift = 12, LampTuneCardCapMask = 0x3Fu;
static_assert((LampTuneCardCapMask << LampTuneCardCapShift) == (0x3Fu << 12) && LampTuneViewMax < 8u);
// (Bit 22 is free: it is none of the bits above, the view's field, 12-17 or 20-21.)
static_assert((LampTuneCentred & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |
                                  LampTuneWindow | (7u << LampTuneViewShift) | (0x3Fu << 12))) == 0);
// bbport (r93_lamp-shadow-spatial): bit 26 is none of the bits above either
static_assert((LampTuneSpatial & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |
                                  LampTuneWindow | LampTuneCentred | (7u << LampTuneViewShift) |
                                  (0x3Fu << 12))) == 0);
/// bbport (r93_lamp-shadow-spatial): word 0's bit 26 for a pass: set only with the centred window,
/// whose resolve is the only code that reads it.
inline constexpr std::uint32_t LampTuneSpatialBit(const LampShadowTune& tune) {
    return tune.spatial && tune.window && tune.window_centred ? LampTuneSpatial : 0u;
}
/// bbport (r92_lamp-shadow-colour): bit 25, the pass shadows in colour (point_shadow_ray.comp
/// t_colour). PointShadow::Flush sets it on a pass that binds a COLOUR build with its colour image;
/// LampTuneWords leaves it 0. Bits 24 and 26 (5u << 24) are r91's and r93's (per-lamp radius,
/// spatial filter).
inline constexpr std::uint32_t LampTuneColour = 1u << 25;
static_assert((LampTuneColour & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                                 LampTuneCentred | (7u << LampTuneViewShift) | (0x3Fu << 12) | (5u << 24))) == 0);
/// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW as a number, 0 to 2.
inline constexpr std::uint32_t LampWindowValue(const LampShadowTune& tune) {
    return tune.window ? (tune.window_centred ? 2u : 1u) : 0u;
}
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
// the shader's mean of the last few frames by 0.4 (1 - FAST_KEEP), and the reject sets in at 0.9
// of the knob (REJECT_FROM): below 0.45 every such ray would drop the history, and the picture
// would stay as noisy as one frame's.
inline constexpr float LampRejectLeast = 0.45f;
// The least BB_LAMP_SHADOW_CLAMP that is not 0: below it the 25 answers around a pixel would
// bind its history inside a penumbra too, where they are a coin's throws.
inline constexpr float LampAroundLeast = 0.5f;

using LampTuneGet = const char* (*)(const char*);

namespace LampTuneDetail {
// The text up to trailing blanks must be a number; anything else leaves the default.
inline bool Ends(const char* end) {
    while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') {
        ++end;
    }
    return *end == '\0';
}

inline float Number(LampTuneGet get, const char* name, float fallback, float lo, float hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !Ends(end) || !std::isfinite(value)) {
        return fallback;
    }
    return std::clamp(value, lo, hi);
}

inline std::uint32_t Whole(LampTuneGet get, const char* name, std::uint32_t fallback,
                           std::uint32_t hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !Ends(end)) {
        return fallback;
    }
    return std::uint32_t(std::clamp(value, 0l, long(hi)));
}
} // namespace LampTuneDetail

/// The knobs as `get` (std::getenv) has them: a value out of range is clamped, one that is not
/// a number leaves the default.
inline LampShadowTune ReadLampShadowTune(LampTuneGet get) {
    using namespace LampTuneDetail;
    LampShadowTune tune;
    tune.weights = Whole(get, "BB_LAMP_SHADOW_WEIGHTS", tune.weights ? 1u : 0u, 1u) != 0;
    tune.colour = Whole(get, "BB_LAMP_SHADOW_COLOUR", tune.colour ? 1u : 0u, 1u) != 0; // bbport (r92)
    tune.wrap = Number(get, "BB_LAMP_SHADOW_WRAP", tune.wrap, 0.0f, 1.0f);
    tune.facing_floor = Number(get, "BB_LAMP_SHADOW_FLOOR", tune.facing_floor, 0.0f, 1.0f);
    // bbport (r48_lamp-softness): read with no fallback (a NaN when the variable is not set or
    // is not a number), so that the pass knows whether it gave the radius.
    const float soft = Number(get, "BB_LAMP_SHADOW_SOFT", std::nanf(""), 0.0f, 0.5f);
    tune.radius_set = !std::isnan(soft);
    tune.radius_m = tune.radius_set ? soft : tune.radius_m;
    // bbport (r91_lamp-radius-per-lamp): 0 or below, or not a number: off
    tune.disc_each = Number(get, "BB_LAMP_SHADOW_RADIUS_PER_LAMP", tune.disc_each, 0.0f, 1.0f);
    tune.history = Number(get, "BB_LAMP_SHADOW_HISTORY", tune.history, 0.0f, 0.98f);
    tune.reject = Number(get, "BB_LAMP_SHADOW_REJECT", tune.reject, 0.0f, 1.0f);
    if (tune.reject > 0.0f) {
        tune.reject = std::max(tune.reject, LampRejectLeast);
    }
    tune.trail_m = Number(get, "BB_LAMP_SHADOW_TRAIL", tune.trail_m, 0.0f, 2.0f);
    tune.follow = Whole(get, "BB_LAMP_SHADOW_FOLLOW", tune.follow ? 1u : 0u, 1u) != 0;
    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
    // r57; r60_lamp-centred-window: 2 the centred window (3 or more: 2, below 0: 0)
    const std::uint32_t window = Whole(get, "BB_LAMP_SHADOW_WINDOW", LampWindowValue(tune), 2u);
    tune.window = window >= 1;
    tune.window_centred = window == 2;
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
    tune.around = Number(get, "BB_LAMP_SHADOW_CLAMP", tune.around, 0.0f, 4.0f);
    if (tune.around > 0.0f) {
        tune.around = std::max(tune.around, LampAroundLeast);
    }
    tune.spatial = Whole(get, "BB_LAMP_SHADOW_SPATIAL", tune.spatial ? 1u : 0u, 1u) != 0; // bbport (r93)
    tune.stale = Whole(get, "BB_LAMP_SHADOW_STALE", tune.stale ? 1u : 0u, 1u) != 0;
    tune.clearance_m = Number(get, "BB_LAMP_SHADOW_CLEARANCE", tune.clearance_m, 0.05f, 2.0f);
    tune.bias_m = Number(get, "BB_LAMP_SHADOW_BIAS", tune.bias_m, 0.005f, 0.2f);
    tune.self_m = Number(get, "BB_LAMP_SHADOW_SELF", tune.self_m, 0.0f, 0.3f);
    tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, LampTuneViewMax);
    tune.view_gain = Number(get, "BB_LAMP_SHADOW_VIEW_GAIN", tune.view_gain, 0.01f, 16.0f);
    return tune;
}

/// The core of the game's inverse-square curve as LocalFalloff::Patch takes it.
inline float LampTuneCore(float core) {
    return std::isfinite(core) && core > 0.0f ? core : 0.0f;
}

/// The world's +x and +y axes in view space (six floats) from `view`, the pass's world-to-view
/// matrix as 12 floats in rows of four (CameraMotion::Matrices::view, a VkTransformMatrixKHR):
/// its first two columns, made unit length. No matrix, or columns that are not finite, not of
/// about unit length or not square to each other: the view's own x and y axes (the disc's frame
/// then turns with the camera).
inline std::array<float, 6> LampTuneAxes(const float* view) {
    constexpr std::array<float, 6> Own{1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
    if (!view) {
        return Own;
    }
    std::array<float, 6> axes{view[0], view[4], view[8], view[1], view[5], view[9]};
    for (int k = 0; k < 2; ++k) {
        float* a = axes.data() + k * 3;
        const float length = std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        if (!std::isfinite(length) || !(length > 0.5f) || !(length < 2.0f)) {
            return Own;
        }
        for (int c = 0; c < 3; ++c) {
            a[c] /= length;
        }
    }
    const float dot = axes[0] * axes[3] + axes[1] * axes[4] + axes[2] * axes[5];
    return std::abs(dot) < 0.05f ? axes : Own;
}

/// bbport (r42_lamp-soft): the frames of history a pixel's shadow ratio may hold: a frame's
/// share is 1 / (frames + 1), so BB_LAMP_SHADOW_HISTORY 0.9 is nine frames. 0: this frame's ray
/// alone, no history (a point lamp, or BB_LAMP_SHADOW_HISTORY=0).
inline float LampHistoryFrames(const LampShadowTune& tune) {
    if (!(tune.radius_m > 0.0f) || !(tune.history > 0.0f)) {
        return 0.0f;
    }
    return tune.history / (1.0f - std::min(tune.history, 0.98f));
}

/// bbport (r44_half-area-lamp): the lamp's radius for one ray traced lamp pass of a frame
/// (PointShadow::Flush); 0: a point lamp. The area lamp shows one ray's answer a frame, which
/// is noise until the history has averaged it: where the knobs ask for the averaging, only the
/// pass that takes the history has the area lamp (takes_history), and another pass of the frame
/// keeps the point lamp. A pass at half resolution (half) shares one answer among the pixels of
/// a 2x2 block, which only an averaged answer can be: it has the area lamp when it averages, and
/// the point lamp without the averaging (BB_LAMP_SHADOW_HISTORY=0, where a full-resolution pass
/// shows the bare rays) and while experiment 2305843009213693952 is set (half_points: the
/// half-resolution pass of before r44, point lamps without a history).
inline float LampPassRadius(const LampShadowTune& tune, bool takes_history, bool half, bool half_points) {
    const bool averages = LampHistoryFrames(tune) > 0.0f;
    if (half && (half_points || !averages)) {
        return 0.0f;
    }
    return averages && !takes_history ? 0.0f : tune.radius_m;
}

/// bbport (r48_lamp-softness): the lamp's radius, m, for graphics_lamp_shadow_softness
/// (bbport_settings.h LampSoftness: 0 sharp, 1 soft, 2 softer; another number: the nearest of
/// the three, as the menu shows it and the ini saves it; r53_lamp-housekeeping). The ini's text
/// that is no name is soft (bbport_settings.cpp). BB_LAMP_SHADOW_SOFT, when it gave a number
/// (radius_set), wins. PointShadow::Flush
/// takes it at every pass, so the menu switches it live.
///  - Sharp, 0: a point lamp. Its ray goes to the lamp's centre, the same ray every frame, and
///    nothing is averaged (LampHistoryFrames 0: the pass neither reads nor writes a history);
///    the pass traces every lamp that reaches a pixel (LampPassSteps).
///  - Soft, 0.1 m: the area lamp of r42, one ray a lamp a frame to a point of its disc, averaged
///    in the history (BB_LAMP_SHADOW_HISTORY 0.9: up to 9 frames before this one).
///  - Softer, 0.2 m: the same with a disc twice as wide, so every penumbra is twice as wide. The
///    rays are as many and the history as long: the points a pixel's rays go to walk the disc
///    in its own measure (samplePoint, the unit square laid over the disc's area), so 9 frames
///    cover a wide disc as evenly as a narrow one and the noise left in a penumbra pixel does
///    not grow with the radius. What grows is the share of the screen in penumbra, where the
///    history does the averaging and the answers around a pixel bind it least, and the share of
///    its pixels the half-resolution pass's second half traces. A ray is blind within
///    its pass's clearance (LampPassClearance: 0.25 m here) of its target, a point of the disc at
///    most the radius from the
///    lamp's centre. So everything within clearance_m minus the radius of the centre (0.05 m at
///    0.2 m), where the lamp's own model sits, is blind to every ray; beyond clearance_m plus
///    the radius (0.45 m at 0.2 m) every ray sees it; in between a thin wall or arm can be missed
///    by the rays whose target lies near it, and a wider disc widens that band (worked out from
///    the code, not seen in the game).
inline constexpr std::array<float, 3> LampSoftnessRadii{0.0f, 0.1f, 0.2f};
inline float LampSoftnessRadius(const LampShadowTune& tune, int softness) {
    if (tune.radius_set) {
        return tune.radius_m;
    }
    return LampSoftnessRadii[std::size_t(std::clamp(softness, 0, int(LampSoftnessRadii.size()) - 1))];
}

/// bbport (r48_lamp-softness): the shader's `steps` for a ray traced lamp pass (its push block):
/// 0 traces every lamp that reaches a pixel; else (`pick`: 1, or 0 with LANTERN_RT_LAMPS_EXACT=1)
/// the strongest lamp and one of the others, picked by weight anew each frame where the camera
/// jitters, which the area lamp's history averages. A point lamp (sharp, or
/// BB_LAMP_SHADOW_SOFT=0) has no history to average the pick in, and the light of a pixel that
/// three or more lamps reach would change from frame to frame in the weaker lamps' shadows: with
/// the repair (not experiment 35184372088832, the pass of before r41) it traces every lamp. No
/// noise, and more rays only where three or more lamps reach a pixel.
inline std::uint32_t LampPassSteps(const LampShadowTune& tune, bool repair, std::uint32_t pick) {
    return repair && !(tune.radius_m > 0.0f) ? 0u : pick;
}

/// bbport (r90_lamp-clearance-default): the blind distance at a ray's target that a pass uses:
/// clearance_m, but at least the lamp's radius plus LampClearanceOverRadius, so the lamp's centre
/// (where its own model sits) is blind to every ray to its disc. 0.18 m for a point lamp and the
/// soft disc (0.1 m), 0.25 m for the softer one (0.2 m).
inline constexpr float LampClearanceOverRadius = 0.05f;
inline float LampPassClearance(const LampShadowTune& tune) {
    return std::max(tune.clearance_m, tune.radius_m + LampClearanceOverRadius);
}

/// bbport (r91_lamp-radius-per-lamp): BB_LAMP_SHADOW_RADIUS_PER_LAMP (disc_each = k, per metre of
/// reach; 0: off). In the pass that averages (the one whose TrackLamps writes the records' word 10,
/// vk_point_shadow.cpp), each lamp's disc has its own radius in place of radius_m:
///   clamp(k x reach, LampDiscLeast, LampDiscMost) x (radius_m / 0.1 m), at most LampDiscCap,
/// reach = 1 / sqrt(word 3). So the softness setting stays the base: soft (0.1 m) gives the clamp as
/// written, softer (0.2 m) twice it, BB_LAMP_SHADOW_SOFT scales it alike, and sharp (0) has no disc
/// (point lamps without a history, every lamp traced: the knob changes nothing there). From the
/// reach, not the luminance: the reach is the one size-like number of a record and steady; the
/// luminance of a flame swings and its units are not known. k 0.02: 5 m of reach keeps 0.1 m,
/// 12 m gets 0.24 m, 15 m or more 0.3 m, 1.5 m or less 0.03 m. The pass reads the disc only with
/// tune word 0 bit 24 (LampTuneDiscEach), which LampTuneWords never sets: Flush sets it after
/// TrackLamps wrote word 10.
inline constexpr std::uint32_t LampTuneDiscEach = 1u << 24;
// (Bit 24 is free: none of bits 0, 1, the view's 8-10, the card cap's 12-17, 20, 21 or 22.)
static_assert((LampTuneDiscEach & (LampTuneNewWeights | LampTuneInverseSquare | (7u << LampTuneViewShift) |
                                   (LampTuneCardCapMask << LampTuneCardCapShift) | LampTuneFollowSoft |
                                   LampTuneWindow | LampTuneCentred)) == 0);
inline constexpr float LampDiscLeast = 0.03f, LampDiscMost = 0.3f, LampDiscCap = 0.5f;
/// A followed lamp's disc moves this share of the way to the one its reach gives now, each frame
/// (LampDiscKeep), unless that one is LampDiscJump times larger or smaller: then it is taken at once.
inline constexpr float LampDiscFollow = 0.0625f, LampDiscJump = 1.6f;
inline float LampDiscRadius(const LampShadowTune& tune, float inv_r2) {
    const float reach = inv_r2 > 0.0f && std::isfinite(inv_r2) ? 1.0f / std::sqrt(inv_r2) : 0.0f;
    const float soft = std::clamp(tune.disc_each * reach, LampDiscLeast, LampDiscMost);
    return std::min(soft * (tune.radius_m / LampSoftnessRadii[1]), LampDiscCap);
}

/// bbport (r91_lamp-radius-per-lamp): the disc a followed lamp has this frame: `held` (its disc of
/// the frame before; 0: none) moved LampDiscFollow of the way to `wanted` (LampDiscRadius now), so
/// that a flame whose reach flickers (5 m and 6.6 m in turn) keeps a steady disc near the mean of
/// its values. `wanted` itself where there is none, or where it is LampDiscJump times larger or
/// smaller than `held` (another softness, or another lamp in its place).
inline float LampDiscKeep(float held, float wanted) {
    if (!(held > 0.0f) || !(wanted < held * LampDiscJump) || !(wanted * LampDiscJump > held)) {
        return wanted;
    }
    return held + (wanted - held) * LampDiscFollow;
}

/// bbport (r91_lamp-radius-per-lamp): word 10 of a lamp record, as point_shadow_ray.comp
/// lampVisibility unpacks it: the disc's radius in millimetres, rounded (low 16 bits), and the
/// blind distance of a ray to it in millimetres, rounded up (high 16 bits): LampPassClearance at
/// that radius, BB_LAMP_SHADOW_CLEARANCE but at least the radius plus LampClearanceOverRadius.
inline std::uint32_t LampDiscWord(const LampShadowTune& tune, float radius_m) {
    LampShadowTune at = tune;
    at.radius_m = radius_m;
    const auto mm = [](float m, bool up) {
        const float v = std::clamp(m * 1000.0f, 0.0f, 65535.0f);
        return std::uint32_t(up ? std::ceil(v - 0.01f) : std::round(v));
    };
    return mm(radius_m, false) | mm(LampPassClearance(at), true) << 16;
}

/// What the shader reads at the place the mode word names. inverse_square, core: the lamp
/// falloff the game's shaders were patched to (startup_local_inverse_square,
/// startup_local_light_core). view: see LampTuneAxes. frame: the frame counter.
inline std::array<std::uint32_t, LampTuneWordCount> LampTuneWords(const LampShadowTune& tune,
                                                                  bool inverse_square, float core,
                                                                  const float* view = nullptr,
                                                                  std::uint32_t frame = 0) {
    const auto bits = [](float v) { return std::bit_cast<std::uint32_t>(v); };
    core = LampTuneCore(core);
    const auto axes = LampTuneAxes(view);
    const std::uint32_t flags = (tune.weights ? LampTuneNewWeights : 0u) |
                                (inverse_square ? LampTuneInverseSquare : 0u) |
                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift |
                                (tune.follow_soft ? LampTuneFollowSoft : 0u) | // bbport (r52_follow-soft)
                                (tune.window ? LampTuneWindow : 0u) |          // bbport (r57_lamp-window)
                                (tune.window && tune.window_centred ? LampTuneCentred : 0u); // bbport (r60)
    return {flags,
            bits(LampPassClearance(tune)), // bbport (r90_lamp-clearance-default)
            bits(tune.radius_m),
            frame,
            bits(tune.self_m),
            bits(tune.wrap),
            bits(core * core),
            bits(tune.view_gain),
            bits(tune.facing_floor),
            bits(tune.reject),
            bits(axes[0]),
            bits(axes[1]),
            bits(axes[2]),
            bits(axes[3]),
            bits(axes[4]),
            bits(axes[5])};
}

/// A lamp's weight at a pixel as point_shadow_ray.comp's lampWeight works it out. t2: distance
/// squared over radius squared (below 1); facing: the cosine between the surface normal and the
/// direction to the lamp; has_normal false: the pass found no normal there (no facing term);
/// luma: of the lamp's colour.
inline float LampWeight(const LampShadowTune& tune, bool inverse_square, float core, float t2,
                        float facing, bool has_normal, float luma) {
    if (!tune.weights) {
        float w = 1.0f - t2;
        w *= w * luma;
        return w;
    }
    float f = 1.0f - std::sqrt(t2);
    f *= f;
    if (inverse_square) {
        core = LampTuneCore(core);
        f = std::max(0.0f, 1.0f / std::max(t2 + core * core, 1e-6f) - 1.0f / (1.0f + core * core));
    }
    float faced = 1.0f;
    if (tune.wrap < 1.0f && has_normal) {
        // Never below the floor: the facing ranks the lamps, it does not remove one.
        faced = std::clamp((facing + tune.wrap) / (1.0f + tune.wrap), tune.facing_floor, 1.0f);
    }
    return f * faced * luma;
}

/// bbport (r92_lamp-shadow-colour): point_shadow_ray.comp's colourScale in C++ (BB_LAMP_SHADOW_COLOUR;
/// tests/test_lamp_shadow_tune.cpp): the scale of each channel of the lamp light `light` for the
/// grey ratio and the channels' ratios rc. rc is made to give the lamp light the luma (Rec. 601,
/// weighted by the light) the grey ratio gives it, then moved toward the grey ratio (which keeps
/// that luma) until no channel passes more than its whole light. No light, or an rc that passes
/// nothing of it: the grey ratio.
using LampRgb = std::array<float, 3>;
inline LampRgb LampColourScale(const LampRgb& rc, float ratio, const LampRgb& light) {
    ratio = std::clamp(ratio, 0.0f, 1.0f); // bbport (r131d_lamp-colour-blob): match shader colourScale
    constexpr LampRgb Luma{0.299f, 0.587f, 0.114f};
    float whole = 0.0f, got = 0.0f;
    for (int c = 0; c < 3; ++c) {
        whole += light[c] * Luma[c];
        got += light[c] * Luma[c] * rc[c];
    }
    if (!(whole > 0.0f) || !(got > 1e-6f * whole)) {
        return {ratio, ratio, ratio};
    }
    LampRgb x{};
    for (int c = 0; c < 3; ++c) {
        x[c] = rc[c] * (ratio * whole / got);
    }
    const float top = std::max({x[0], x[1], x[2]});
    if (top > 1.0f) {
        const float a = (1.0f - ratio) / (top - ratio);
        for (float& v : x) {
            v = ratio + (v - ratio) * a;
        }
    }
    return x;
}

/// bbport (r42_lamp-soft): the last four words of the pass's history block (words 30 to 33,
/// point_shadow_ray.comp HISTORY_BLEND): the most frames a texel may hold, how far a moving
/// lamp's shadows may trail, within what distance of a moving lamp a caster is taken to move
/// with it, and how many deviations of the answers around a pixel its history may lie from
/// their mean.
inline constexpr std::uint32_t LampHistoryTailWords = 4;
inline std::array<std::uint32_t, LampHistoryTailWords> LampHistoryTail(const LampShadowTune& tune) {
    return {std::bit_cast<std::uint32_t>(LampHistoryFrames(tune)), std::bit_cast<std::uint32_t>(tune.trail_m),
            std::bit_cast<std::uint32_t>(tune.carry_m), std::bit_cast<std::uint32_t>(tune.around)};
}

/// bbport (r42_lamp-soft): whether the camera jumped between two frames: `back` is the way from
/// this frame's view space to that of the frame before (12 floats in rows of four, the history
/// block's words 2 to 13). More than 2 m or more than about 20 degrees in one frame is a cut
/// (a cutscene's change of shot, a warp), not a camera's motion: the history of the frame before
/// then shows another place, and what of it passes the depth test does so by chance.
inline bool LampCameraCut(const float* back) {
    const float moved2 = back[3] * back[3] + back[7] * back[7] + back[11] * back[11];
    const float trace = back[0] + back[5] + back[10];
    // (1 + 2 cos 20 degrees = 2.879; not finite counts as a cut.)
    return !(moved2 <= 4.0f) || !(trace >= 2.879f);
}

/// bbport (r42_lamp-soft): one lamp of a pass (LampTrack).
struct LampSeen {
    std::array<std::uint32_t, 7> key{}; ///< its place in view space, 1 / reach squared and its
                                        ///< colour, as the records hold them
    std::array<float, 3> world{};       ///< its place in the world
    std::array<float, 3> moved{};       ///< since the frame before, in the world; zero unless followed
    float radius = 0.0f;                ///< its reach, m
    float luma = 0.0f;                  ///< of its colour
    float away = 0.0f;                  ///< from the camera, m
    std::uint32_t records = 0;          ///< records of the pass that hold it (one a tile it reaches)
    bool followed = false;              ///< found in the frame before
    /// Since LampTrack::ClearSteps, along the frames it was followed: how many, and the sum
    /// and the largest of its steps, m (a flame's lamp that wobbles shows here).
    std::uint32_t steps = 0;
    float step_sum = 0.0f, step_most = 0.0f;
    /// bbport (r91_lamp-radius-per-lamp): its disc this frame, m (LampTrack::Disc; 0: none yet),
    /// its disc of the frame before (set by Follow; 0: none), and how often it jumped (LampDiscKeep
    /// took the new one at once) along the frames it was followed since LampTrack::ClearSteps
    float disc = 0.0f, disc_was = 0.0f;
    std::uint32_t disc_moves = 0;
};

/// bbport (r42_lamp-soft): the lamps of the pass that holds the shadow history, told apart and
/// followed from one frame to the next. A hand torch moves with the one who carries it, and so do
/// the shadows it throws of its carrier, on the ground and on the carrier itself: a history
/// looked up where the ground was a frame ago holds them where they were, and they smear for as
/// long as it lasts. So the pass looks a pixel's history up where the pixel's strongest lamp
/// would put it: moved back by that lamp's motion (Shift, in the lamp records' words 12 to
/// 14), where what blocks the lamp there is near it (the shader decides, see its HISTORY_BLEND).
/// For what moves with the lamp that is exact; for a still caster under a moving lamp it is
/// not, which the shader bounds by the lamp's step (Step, word 15). The same list feeds the log
/// line that says where the lamps near the camera are.
/// A record: 16 words, the lamp's place in view space (3 floats), 1 / reach squared, its colour
/// (3 floats); two records are one lamp when those seven words are the same bits (a lamp is
/// listed once for every tile it reaches; two lights of a torch at one place with different
/// reach or colour are two lamps).
class LampTrack {
public:
    static constexpr std::uint32_t Most = 64; ///< lamps told apart in a pass; more are not followed
    static constexpr float Reach = 0.6f;      ///< a lamp further than this from every lamp of the
                                              ///< frame before is a new one, m
    static constexpr float Still = 0.002f;    ///< a lamp that moved less stands still, m
    static constexpr float Near = 15.0f;      ///< "near the camera", m
    static constexpr float Lost = 1000.0f;    ///< Step of a lamp that was not there the frame
                                              ///< before, m: no history holds under its shadows
                                              ///< (bbport r52_follow-soft: point_shadow_ray.comp
                                              ///< NEW_LAMP_STEP is half of it; tied by this
                                              ///< comment only)

    /// A pass begins. inv_view: its camera, view to world, 12 floats in rows of four; null: not
    /// known (nothing is followed this frame or the next).
    void Begin(const float* inv_view) {
        count = 0;
        slots.fill(0);
        matched = false;
        has_world = inv_view != nullptr;
        if (inv_view) {
            std::memcpy(to_world.data(), inv_view, sizeof(to_world));
        }
    }

    /// How far a record's lamp is from the camera, m (the pass adds the records of lamps within
    /// Near first, so that with more than Most lamps in a pass the near ones are followed).
    [[nodiscard]] static float Away(const std::uint32_t* record) {
        const float x = std::bit_cast<float>(record[0]), y = std::bit_cast<float>(record[1]),
                    z = std::bit_cast<float>(record[2]);
        return std::sqrt(x * x + y * y + z * z);
    }

    /// One record of the pass. Its lamp's index in Lamps(), or -1: no lamp (no reach), or more
    /// than Most.
    int Add(const std::uint32_t* record) {
        const float inv_r2 = std::bit_cast<float>(record[3]);
        if (!(inv_r2 > 0.0f) || !std::isfinite(inv_r2)) {
            return -1;
        }
        std::uint32_t at = (record[0] * 0x9E3779B1u ^ record[1] * 0x85EBCA77u ^ record[2] * 0xC2B2AE3Du) >> 24;
        for (std::uint32_t tries = 0; tries < slots.size(); ++tries, at = (at + 1) & 255u) {
            if (slots[at] == 0) {
                break;
            }
            LampSeen& lamp = lamps[slots[at] - 1u];
            if (std::equal(lamp.key.begin(), lamp.key.end(), record)) {
                ++lamp.records;
                return int(slots[at]) - 1;
            }
        }
        if (count >= Most) {
            return -1;
        }
        LampSeen& lamp = lamps[count];
        lamp = {};
        std::copy_n(record, lamp.key.size(), lamp.key.begin());
        const std::array<float, 3> v{std::bit_cast<float>(record[0]), std::bit_cast<float>(record[1]),
                                     std::bit_cast<float>(record[2])};
        for (int r = 0; r < 3; ++r) {
            lamp.world[r] = has_world ? to_world[r * 4] * v[0] + to_world[r * 4 + 1] * v[1] +
                                            to_world[r * 4 + 2] * v[2] + to_world[r * 4 + 3]
                                      : v[r];
        }
        lamp.radius = 1.0f / std::sqrt(inv_r2);
        lamp.luma = 0.299f * std::bit_cast<float>(record[4]) + 0.587f * std::bit_cast<float>(record[5]) +
                    0.114f * std::bit_cast<float>(record[6]);
        lamp.away = Away(record);
        lamp.records = 1;
        slots[at] = std::uint8_t(++count);
        return int(count) - 1;
    }

    /// After the pass's last record: finds each lamp in the frame before, one of this frame for
    /// one of that.
    ///  - A lamp can be one of the frame before that lies within Reach of it, or whose place
    ///    plus the step it made then does (a lamp that moves goes on moving).
    ///  - Each lamp takes the nearest such one that is free (nearer by place or by place plus
    ///    step; among equals the one of its own reach); where two want the same, the nearer has
    ///    it and the other looks again.
    ///  - Then pairs change partners where that brings both nearer in sum (of squares): two
    ///    lamps a few centimetres apart that set off together would else each take the other's
    ///    place of the frame before, or one of them none (a hand torch made of two lights).
    void Follow() {
        if (!has_world || !had_world) {
            return;
        }
        matched = true;
        std::array<int, Most> from{}, taken{};
        std::array<float, Most> gap{};
        from.fill(-1);
        taken.fill(-1);
        for (std::uint32_t round = 0; round < 6; ++round) {
            bool asked = false;
            std::array<int, Most> want{};
            want.fill(-1);
            for (std::uint32_t i = 0; i < count; ++i) {
                if (from[i] >= 0) {
                    continue;
                }
                float best = Far;
                for (std::uint32_t j = 0; j < before_count; ++j) {
                    if (taken[j] >= 0) {
                        continue;
                    }
                    const float d = Gap(lamps[i], before[j]);
                    if (d < best) {
                        best = d;
                        want[i] = int(j);
                    }
                }
                gap[i] = best;
                asked = asked || want[i] >= 0;
            }
            if (!asked) {
                break;
            }
            for (std::uint32_t i = 0; i < count; ++i) {
                if (want[i] < 0) {
                    continue;
                }
                const std::uint32_t j = std::uint32_t(want[i]);
                if (taken[j] < 0 || gap[i] < gap[std::uint32_t(taken[j])]) {
                    if (taken[j] >= 0) {
                        from[std::uint32_t(taken[j])] = -1;
                    }
                    taken[j] = int(i);
                    from[i] = int(j);
                }
            }
        }
        for (std::uint32_t sweep = 0; sweep < 4; ++sweep) {
            bool changed = false;
            for (std::uint32_t i = 0; i < count; ++i) {
                // (A lamp that stands where it stood has its own.)
                if (from[i] < 0 || gap[i] < Still * Still) {
                    continue;
                }
                for (std::uint32_t k = i + 1; k < count; ++k) {
                    if (from[k] < 0 || gap[k] < Still * Still) {
                        continue;
                    }
                    const float ik = Gap(lamps[i], before[std::uint32_t(from[k])]),
                                ki = Gap(lamps[k], before[std::uint32_t(from[i])]);
                    if (ik < Far && ki < Far && ik + ki < (gap[i] + gap[k]) * 0.999f) {
                        std::swap(from[i], from[k]);
                        gap[i] = ik;
                        gap[k] = ki;
                        changed = true;
                    }
                }
            }
            if (!changed) {
                break;
            }
        }
        for (std::uint32_t i = 0; i < count; ++i) {
            if (from[i] < 0) {
                continue;
            }
            LampSeen& lamp = lamps[i];
            const LampSeen& was = before[std::uint32_t(from[i])];
            lamp.followed = true;
            lamp.disc_was = was.disc; // bbport (r91_lamp-radius-per-lamp)
            lamp.disc_moves = was.disc_moves;
            float d2 = 0.0f;
            for (int c = 0; c < 3; ++c) {
                d2 += (lamp.world[c] - was.world[c]) * (lamp.world[c] - was.world[c]);
            }
            if (d2 >= Still * Still) {
                for (int c = 0; c < 3; ++c) {
                    lamp.moved[c] = lamp.world[c] - was.world[c];
                }
            }
            const float step = d2 >= Still * Still ? std::sqrt(d2) : 0.0f;
            lamp.steps = was.steps + 1;
            lamp.step_sum = was.step_sum + step;
            lamp.step_most = std::max(was.step_most, step);
        }
    }

    [[nodiscard]] std::uint32_t Count() const noexcept {
        return count;
    }
    [[nodiscard]] const LampSeen& Lamp(std::uint32_t index) const noexcept {
        return lamps[index];
    }

    /// What the pass takes from a pixel's place in the view space of the frame before to find
    /// the history its strongest lamp's shadows left: the lamp's motion, turned into that view
    /// space. before_view: the camera of the frame before, world to view, 12 floats in rows of
    /// four. Zero for a lamp that stands still or is not followed.
    [[nodiscard]] std::array<float, 3> Shift(int index, const float* before_view) const {
        std::array<float, 3> out{};
        if (index < 0 || std::uint32_t(index) >= count || !before_view) {
            return out;
        }
        const auto& m = lamps[std::uint32_t(index)].moved;
        for (int r = 0; r < 3; ++r) {
            out[r] = before_view[r * 4] * m[0] + before_view[r * 4 + 1] * m[1] + before_view[r * 4 + 2] * m[2];
        }
        return out;
    }

    /// How far the lamp moved since the frame before, metres: the pass shortens the history
    /// under a moving lamp's shadows by it (BB_LAMP_SHADOW_TRAIL). Zero for a lamp that stands
    /// still. Lost for a lamp that was looked for in the frame before and not found (it is new,
    /// or it jumped): what the history holds under it was made without it. Zero again where
    /// that cannot be told: no frame before, a lamp beyond Most, or a frame before that had
    /// Most lamps (the lamp may have been one more).
    [[nodiscard]] float Step(int index) const {
        if (index < 0 || std::uint32_t(index) >= count) {
            return 0.0f;
        }
        const LampSeen& lamp = lamps[std::uint32_t(index)];
        if (!lamp.followed) {
            return matched && before_count < Most ? Lost : 0.0f;
        }
        const auto& m = lamp.moved;
        return std::sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]);
    }

    /// bbport (r91_lamp-radius-per-lamp): the disc of lamp `index` this frame for the radius its
    /// record asks for now (`wanted`, LampDiscRadius): worked out at its first record of the frame
    /// from the disc it had in the frame before (LampDiscKeep; none when it is not followed), kept
    /// for the next frame, and the same for its other records. No lamp (-1, or beyond Most):
    /// `wanted`.
    float Disc(int index, float wanted) {
        if (index < 0 || std::uint32_t(index) >= count) {
            return wanted;
        }
        LampSeen& lamp = lamps[std::uint32_t(index)];
        if (!(lamp.disc > 0.0f)) {
            lamp.disc = LampDiscKeep(lamp.disc_was, wanted);
            // (a jump: LampDiscKeep took the new one at once)
            lamp.disc_moves += lamp.disc_was > 0.0f && lamp.disc == wanted && wanted != lamp.disc_was ? 1u : 0u;
        }
        return lamp.disc;
    }

    /// The up to four brightest lamps within Near of the camera (the nearer first among equals),
    /// as indices; -1: no more.
    [[nodiscard]] std::array<int, 4> Strongest() const {
        std::array<int, 4> out{-1, -1, -1, -1};
        for (std::uint32_t i = 0; i < count; ++i) {
            if (!(lamps[i].away <= Near)) {
                continue;
            }
            int held = int(i);
            for (int& slot : out) {
                if (slot < 0) {
                    slot = held;
                    break;
                }
                const LampSeen& a = lamps[std::uint32_t(held)];
                const LampSeen& b = lamps[std::uint32_t(slot)];
                if (a.luma > b.luma || (a.luma == b.luma && a.away < b.away)) {
                    std::swap(slot, held);
                }
            }
        }
        return out;
    }

    /// The steps counted along the lamps start again (after the log line that printed them).
    void ClearSteps() {
        for (std::uint32_t i = 0; i < count; ++i) {
            lamps[i].steps = 0;
            lamps[i].step_sum = lamps[i].step_most = 0.0f;
            lamps[i].disc_moves = 0; // bbport (r91_lamp-radius-per-lamp)
        }
    }

    /// The frame ends. kept: the pass ran with a history, so its lamps are "the frame before" of
    /// the next; false: the next frame follows nothing.
    void End(bool kept) {
        had_world = kept && has_world;
        before_count = had_world ? count : 0;
        if (had_world) {
            std::copy_n(lamps.begin(), count, before.begin());
        }
        count = 0;
        has_world = false;
    }

private:
    static constexpr float Far = 1e30f; ///< Gap of two lamps that cannot be one

    /// How far lamp `now` is from where lamp `was` (of the frame before) stood or would be had
    /// it gone on as it moved then, squared, plus a little for a different reach (which only
    /// decides between places equally near: a flame's reach may flicker); Far: beyond Reach.
    static float Gap(const LampSeen& now, const LampSeen& was) {
        float stood = 0.0f, went = 0.0f;
        for (int c = 0; c < 3; ++c) {
            const float d = now.world[c] - was.world[c];
            stood += d * d;
            went += (d - was.moved[c]) * (d - was.moved[c]);
        }
        const float least = std::min(stood, went);
        if (!(least <= Reach * Reach)) {
            return Far;
        }
        const float reach = std::log(std::max(now.radius, 1e-6f) / std::max(was.radius, 1e-6f));
        return least + 0.0625f * reach * reach;
    }

    std::array<LampSeen, Most> lamps{}, before{};
    std::array<std::uint8_t, 256> slots{};
    std::array<float, 12> to_world{};
    std::uint32_t count = 0, before_count = 0;
    bool has_world = false, had_world = false;
    bool matched = false; ///< Follow looked for this frame's lamps in the frame before
};

} // namespace Vulkan
