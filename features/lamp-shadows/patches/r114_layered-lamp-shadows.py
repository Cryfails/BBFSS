# r114_layered-lamp-shadows: FEATURE patch (lamp work; the owner, 2026-11-15 19:56: "I think another
# thing if we don't already do it is that some shadows when light hits them have layers especially
# when it's a dim light"). Off by default behind BB_LAMP_SHADOW_LAYERS (environment; with the test
# tools' live knobs header in the tree it is asked again at every pass, else read once).
#
# What the lamp pass did before (point_shadow_ray.comp main, read 2026-11-15 22:40):
#  - Sharp lamps (steps 0): every lamp that reaches a pixel gets its own ray to its centre: one
#    visibility per lamp, ratio = sum(w_i v_i) / sum(w_i). Hard layers already.
#  - Soft and softer (the default; steps 1): the STRONGEST lamp gets one ray to a point of its disc;
#    ALL the others share ONE ray to a lamp picked by weight anew every frame, whose answer stands for
#    their summed weight. Exactly two lamps: the pick is always the second, so two overlapping lamps
#    already give two layers of their own darkness. Three or more: lamps 2..N share one ray, a new pick
#    each frame, and the history averages the picks: their layers are noisy, and the guards against
#    trails cut that noise (reject, clamp), so the young-pixel and same-surface means smear them.
#  - One grey ratio is applied to the summed lamp light; with BB_LAMP_SHADOW_COLOUR=1 (r92) the ratio
#    is worked out per channel, so the tint of overlapping lamps of different colour IS there (exact
#    with two lamps; with three or more the weaker lamps share the pick's hue).
#  - Each lamp is ONE uniform disc (0.1 m soft, 0.2 m softer, or r91's own size): its shadow is a dark
#    umbra and ONE smooth penumbra ramp. Nothing gives the crisp core plus a paler outer layer that a
#    flame with a glow round it (or a bulb in a shade) throws.
#
# Review fixes (2026-11-15 23:20, this .fixed.py; the draft r114_layered-lamp-shadows.py stays):
#  - Word 0 bit 11 clashed with r113_lamp-softness.fixed.py (BB_LAMP_SHADOW_FLAME, drafted at the same
#    time: bits 11 and 23). Both compiled, so BB_LAMP_SHADOW_FLAME=1 would have switched on r114's
#    second lamp ray and BB_LAMP_SHADOW_LAYERS=2 r113's flame. The second lamp's bit is now 7 and the
#    halo's share 3 bits (4-6) in EIGHTHS (default 3/8 = 0.375, as before); the static_assert keeps
#    r113's 11 and 23 out. Word 0 bits 4-7, 18-19, 30-31: r114; 11, 23: r113; every bit is now taken.
#  - Halo rays aimed up to 0.6 m off the lamp's centre with the disc's blind distance (0.18-0.25 m),
#    so a wall behind a wall lamp, a candle's table or the hand at a torch could block part of the halo
#    for every surface the lamp lights (darker by up to about the halo share times the halo's blocked
#    part). FIXED in the shader text (HALO): a halo point's ray is blind as much further as the point
#    lies beyond the disc's radius (r113's flame rule), set anew at every call.
#  - With three or more lamps the second lamp's ray reused the picked lamp's xi offset (correlated
#    points, more noise, no bias). FIXED (SECRAY): the next offset when a lamp is picked; two lamps
#    trace the same rays as before.
#  - Texts (rule 7): unshadowed light is unchanged only where nothing near the lamp crosses a halo
#    ray; BB_LAMP_SHADOW_FLAME (r113) is the same idea as value 1 (set one of them).
#
# What this patch adds (all off unless BB_LAMP_SHADOW_LAYERS says so; only passes whose lamps have a
# disc and average over frames, i.e. soft and softer):
#  1 = core and halo: each lamp ray goes, for a share BB_LAMP_SHADOW_LAYERS_HALO of the frames (in
#      8ths, default 3/8 = 0.375), to a point of a halo BB_LAMP_SHADOW_LAYERS_WIDE times the lamp's
#      disc (2, 2.5, 3 or 3.5; default 2.5; at most 0.6 m and never smaller than the disc), else to a
#      point of a core BB_LAMP_SHADOW_LAYERS_CORE times the disc (1, 0.75, 0.5 or 0.25; default 0.5).
#      The R2 point walk is split at that share (xi.x below it: the halo, stretched back to 0..1;
#      above: the core), so each part keeps its points spread evenly. Averaged over the frames a
#      shadow's edge gets two slopes: a steep inner one (the core, half the softness disc) and a wide
#      shallow outer one (the halo, a pale layer that share deep at most). Model (a body 0.4 m wide 0.5 m
#      over the floor, lamp 1.5 m up; a grid over the disc, 2026-11-15): old ratio 0.05 / 0.25 / 0.50 / 0.75 / 0.95 at
#      0.26 / 0.28 / 0.30 / 0.32 / 0.34 m; with the defaults 0.11 / 0.18 / 0.50 / 0.82 / 0.89, plus a
#      pale foot 0.02-0.08 inside (0.20-0.24 m, the old was 0) and a pale tail 0.92-0.98 outside
#      (0.36-0.40 m, the old was 1). The light reaching an unshadowed surface is the same as before
#      where nothing within the halo's reach of the lamp crosses a halo ray. No extra ray, no image,
#      no binding.
#      BB_LAMP_SHADOW_FLAME (r113) puts the rays to a core and an envelope too: set one of the two.
#  2 = two lamps apart: in the pick path the second strongest lamp gets a ray of its own every frame;
#      the pick then stands only for the lamps after it. One or two lamps at a pixel: the same rays as
#      before (the second lamp's ray goes to the same disc point the pick's did), so the same answers;
#      three: every lamp its own ray (the third is alone in the pick); four or more: the 3rd..Nth
#      share the pick. With BB_LAMP_SHADOW_COLOUR=1 the second lamp's part is put in its own colour
#      too. One ray more, only at pixels with three or more lamps.
#  3 = both.
#
# Files: NEW renderer_vulkan/lamp_shadow_layers.h (parse with compile-time checks, the bits, the once
#  line, the counter and its line). point_shadow_ray.comp: 7 inserts (globals, loadTune, lampVisibility's
#  core and halo, two in the weight loop, the second lamp's ray, its colour). vk_point_shadow.cpp: 3
#  one-line hooks (include after r101's, Flush ORs the bits after r93's OR, the short line after r103's).
#  README.md: four rows after BB_LAMP_SHADOW_COLOUR's. Word 0 bits 4-6 (share), 7 (second lamp), 18-19
#  and 30-31: free (static_assert in the header, which also keeps r113's 11 and 23 out).
#  Text kept out on purpose so the siblings' own checks still pass: no "#ifdef COLOUR" (r92 counts it;
#  this uses "#if defined(COLOUR)"), no other patch's name or the words they scan for in a shader line,
#  no lampRecord( call (r91 counts it). Every insert lands outside the siblings' inserted texts.
#
# Off (the default): the knob is 0 -> LampLayersBits returns 0 -> word 0 as before -> t_halo 0 and
#  t_layers_two false -> the halo branch (uniform) and the second lamp's tracking, swap and ray are
#  skipped, lay_sec_w stays 0 and lay_sec_part below 0, so the colour block is skipped: every statement
#  of before runs on the same values. The host adds four knob reads (an atomic load each), an OR of 0
#  and a line call that returns.
#
# Use: python -I -X utf8 r114_layered-lamp-shadows.py check | apply | revert
# Root: R114_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r114_backup next to this script; revert takes out exactly what apply inserted (each inserted text is
# found by itself, exactly once) and removes the new header. Revert r114 before any patch it anchors on
# (r91, r92, r93, r101, r103).
import os, sys

ROOT = os.environ.get("R114_ROOT") or "<tree>"
BACKUP = os.environ.get("R114_BACKUP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "r114_backup")
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
R = "README.md"
NEW = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_layers.h"
TAG = "bbport (r114_lamp-shadow-layers)"

HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r114_lamp-shadow-layers): FEATURE. BB_LAMP_SHADOW_LAYERS, layered lamp shadows. 0 (the
// default): as before. Only a pass whose lamps have a disc and that averages over frames (soft and
// softer; sharp traces every lamp to its centre and changes nothing):
//  1: core and halo. Each lamp ray goes, for a share BB_LAMP_SHADOW_LAYERS_HALO of the frames (0 to 1
//     in 8ths, rounded, at most 7/8; default 3/8 = 0.375; 0: neither halo nor core), to a point of a
//     halo BB_LAMP_SHADOW_LAYERS_WIDE times the lamp's disc (2, 2.5, 3 or 3.5, the nearest; default
//     2.5; at most 0.6 m and never smaller than the disc: point_shadow_ray.comp LAYERS_HALO_MOST), else
//     to a point of a core BB_LAMP_SHADOW_LAYERS_CORE times the disc (1, 0.75, 0.5 or 0.25, the
//     nearest; default 0.5). Averaged over the frames a shadow's edge has a steep inner slope (the core) and a
//     wide pale outer layer (the halo, that share deep at most). No extra ray. BB_LAMP_SHADOW_FLAME
//     (r113_lamp-softness) is the same idea in another form: set one of the two.
//  2: two lamps apart. Where three or more lamps light a pixel the second strongest gets a ray of its
//     own every frame (before, it shared the one picked ray with every weaker lamp, a new pick every
//     frame); pixels with one or two lamps trace the same rays as before. One ray more there.
//  3: both.
// With the test tools' live knobs (bbport_live_knobs.h, branch dev/test-tools) the four knobs are
// asked again at every pass, so one running game can switch them; without that header (a feature
// branch) they are read once, at the first pass.
// Word 0 of the lamp pass's tuning words: bits 4-6 the halo's share in 8ths (0: no halo), bit 7 the
// second lamp's own ray, bits 18-19 the halo's width code (its radius = the disc's x (2 + 0.5 x code)),
// bits 30-31 the core's code (its radius = the disc's x (1 - 0.25 x code)). LampTuneWords leaves them
// clear; PointShadow::Flush ORs them in (LampLayersBits). No Vulkan here; the parse rules are checked
// at compile time below.

#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "lamp_shadow_tune.h"
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h"
#define BB_LAMP_SHADOW_LAYERS_LIVE 1
#else
#define BB_LAMP_SHADOW_LAYERS_LIVE 0
#endif

namespace Vulkan {

inline constexpr std::uint32_t LampLayersHaloShift = 4, LampLayersHaloMask = 7u;
inline constexpr std::uint32_t LampLayersTwo = 1u << 7;
inline constexpr std::uint32_t LampLayersWideShift = 18, LampLayersWideMask = 3u;
inline constexpr std::uint32_t LampLayersCoreShift = 30, LampLayersCoreMask = 3u;
inline constexpr std::uint32_t LampLayersAllBits = (LampLayersHaloMask << LampLayersHaloShift) | LampLayersTwo |
                                                   (LampLayersWideMask << LampLayersWideShift) |
                                                   (LampLayersCoreMask << LampLayersCoreShift);
// Free: none of LampTuneWords' bits (0, 1, the view's 8-10, 20-22), r63's card cap (12-17), r101's 2 and
// 3, r91's 24, r92's 25, r93's 26, r103's 27 and 28, r103b's 29, nor r113_lamp-softness's 11 and 23
// (BB_LAMP_SHADOW_FLAME, lamp_flame.h LampTuneFlame and LampTuneFlameTall; named by number, since that
// header is another feature's). With these, all 32 bits of word 0 are taken.
static_assert((LampLayersAllBits &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | LampTuneSpatial | LampTuneColour | LampTuneDiscEach |
                (7u << LampTuneViewShift) | (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) |
                (7u << 27) | (1u << 11) | (1u << 23))) == 0,
              "bbport (r114_lamp-shadow-layers): word 0 bits 4-7, 18, 19, 30 and 31 must be free");

namespace LampLayersDetail {
/// A plain decimal number (blanks round it; digits with at most one '.'), as num / den with den a
/// power of ten (6 decimals at most are kept, and digits past 10^12 are dropped: such a knob is
/// clamped anyway); ok false: the text is not such a number (a sign, a letter, nothing).
struct Number {
    bool ok = false;
    std::uint64_t num = 0;
    std::uint64_t den = 1;
};
constexpr bool Blank(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}
constexpr Number Read(const char* text) {
    Number n;
    if (text == nullptr) {
        return n;
    }
    const char* p = text;
    while (Blank(*p)) {
        ++p;
    }
    bool dot = false, digit = false;
    for (; *p != 0 && !Blank(*p); ++p) {
        if (*p == '.' && !dot) {
            dot = true;
            continue;
        }
        if (*p < '0' || *p > '9') {
            return Number{};
        }
        digit = true;
        if (n.num >= 1000000000000ull || (dot && n.den >= 1000000ull)) {
            continue;
        }
        n.num = n.num * 10u + std::uint64_t(*p - '0');
        if (dot) {
            n.den *= 10u;
        }
    }
    while (Blank(*p)) {
        ++p;
    }
    n.ok = digit && *p == 0;
    return n;
}
} // namespace LampLayersDetail

/// BB_LAMP_SHADOW_LAYERS: a whole number 0 to 3 (more: 3); nothing, or text that is not a whole
/// number: 0.
constexpr std::uint32_t LampLayersParseMode(const char* text) {
    const LampLayersDetail::Number n = LampLayersDetail::Read(text);
    if (!n.ok || n.num % n.den != 0u) {
        return 0u;
    }
    const std::uint64_t v = n.num / n.den;
    return v > 3u ? 3u : std::uint32_t(v);
}

inline constexpr std::uint32_t LampLayersHaloDefault = 3u; ///< 3/8 = 0.375 of the rays go to the halo
inline constexpr std::uint32_t LampLayersWideDefault = 1u; ///< the halo is 2.5 times the disc
inline constexpr std::uint32_t LampLayersCoreDefault = 2u; ///< the core is 0.5 times the disc

/// BB_LAMP_SHADOW_LAYERS_HALO: the halo's share of each lamp's rays in 8ths, rounded (at most 7; 0: no
/// halo); nothing, or text that is not a number: 3 (0.375).
constexpr std::uint32_t LampLayersParseHalo(const char* text) {
    const LampLayersDetail::Number n = LampLayersDetail::Read(text);
    if (!n.ok) {
        return LampLayersHaloDefault;
    }
    const std::uint64_t code = (n.num * 8u + n.den / 2u) / n.den;
    return code > LampLayersHaloMask ? LampLayersHaloMask : std::uint32_t(code);
}

/// BB_LAMP_SHADOW_LAYERS_WIDE: the halo's radius over the lamp's disc as a code 0 to 3 (2 + 0.5 x code:
/// 2, 2.5, 3 or 3.5, the nearest; 2 or less: 0, more than 3.5: 3); nothing, or text that is not a
/// number: 1 (2.5).
constexpr std::uint32_t LampLayersParseWide(const char* text) {
    const LampLayersDetail::Number n = LampLayersDetail::Read(text);
    if (!n.ok) {
        return LampLayersWideDefault;
    }
    if (n.num <= 2u * n.den) {
        return 0u;
    }
    const std::uint64_t code = ((n.num - 2u * n.den) * 2u + n.den / 2u) / n.den;
    return code > LampLayersWideMask ? LampLayersWideMask : std::uint32_t(code);
}

/// BB_LAMP_SHADOW_LAYERS_CORE: the core's radius over the lamp's disc as a code 0 to 3 (1 - 0.25 x code:
/// 1, 0.75, 0.5 or 0.25, the nearest; 1 or more: 0, 0.25 or less: 3); nothing, or text that is not a
/// number: 2 (0.5).
constexpr std::uint32_t LampLayersParseCore(const char* text) {
    const LampLayersDetail::Number n = LampLayersDetail::Read(text);
    if (!n.ok) {
        return LampLayersCoreDefault;
    }
    if (n.num >= n.den) {
        return 0u;
    }
    const std::uint64_t code = ((n.den - n.num) * 4u + n.den / 2u) / n.den;
    return code > LampLayersCoreMask ? LampLayersCoreMask : std::uint32_t(code);
}

/// What the shader makes of the codes (point_shadow_ray.comp loadTune: t_halo, t_halo_wide, t_halo_core).
constexpr float LampLayersShare(std::uint32_t halo) {
    return float(halo) / 8.0f;
}
constexpr float LampLayersWide(std::uint32_t wide) {
    return 2.0f + 0.5f * float(wide);
}
constexpr float LampLayersCore(std::uint32_t core) {
    return 1.0f - 0.25f * float(core);
}

/// The bits for a pass with the knobs at mode, halo, wide, core. disc: the pass's lamps have a disc and
/// it averages over frames (else none is set: a point lamp has nothing to layer, and a pass without a
/// history would show the split rays as bare noise).
constexpr std::uint32_t LampLayersBitsFor(std::uint32_t mode, std::uint32_t halo, std::uint32_t wide,
                                          std::uint32_t core, bool disc) {
    if (!disc) {
        return 0u;
    }
    const std::uint32_t ring = (mode & 1u) != 0u && halo != 0u
                                   ? (halo & LampLayersHaloMask) << LampLayersHaloShift |
                                         (wide & LampLayersWideMask) << LampLayersWideShift |
                                         (core & LampLayersCoreMask) << LampLayersCoreShift
                                   : 0u;
    return ring | ((mode & 2u) != 0u ? LampLayersTwo : 0u);
}

// The rules above, checked when this compiles.
static_assert(LampLayersParseMode(nullptr) == 0u && LampLayersParseMode("") == 0u && LampLayersParseMode("1") == 1u &&
              LampLayersParseMode(" 3 ") == 3u && LampLayersParseMode("7") == 3u && LampLayersParseMode("2.0") == 2u &&
              LampLayersParseMode("1.5") == 0u && LampLayersParseMode("-1") == 0u && LampLayersParseMode("on") == 0u);
static_assert(LampLayersParseHalo(nullptr) == 3u && LampLayersParseHalo("0.375") == 3u &&
              LampLayersParseHalo("0.35") == 3u && LampLayersParseHalo("0.5") == 4u && LampLayersParseHalo("0") == 0u &&
              LampLayersParseHalo("1") == 7u && LampLayersParseHalo("9") == 7u && LampLayersParseHalo(".25") == 2u &&
              LampLayersParseHalo("0.875") == 7u && LampLayersParseHalo("x") == 3u);
static_assert(LampLayersParseWide(nullptr) == 1u && LampLayersParseWide("2") == 0u && LampLayersParseWide("1") == 0u &&
              LampLayersParseWide("2.5") == 1u && LampLayersParseWide("2.7") == 1u && LampLayersParseWide("3") == 2u &&
              LampLayersParseWide("3.5") == 3u && LampLayersParseWide("4") == 3u && LampLayersParseWide("wide") == 1u);
static_assert(LampLayersParseCore(nullptr) == 2u && LampLayersParseCore("1") == 0u && LampLayersParseCore("2") == 0u &&
              LampLayersParseCore("0.75") == 1u && LampLayersParseCore("0.5") == 2u && LampLayersParseCore("0.6") == 2u &&
              LampLayersParseCore("0.25") == 3u && LampLayersParseCore("0") == 3u && LampLayersParseCore("core") == 2u);
static_assert(LampLayersBitsFor(3u, 3u, 1u, 2u, true) == ((3u << 4) | (1u << 7) | (1u << 18) | (2u << 30)) &&
              LampLayersBitsFor(1u, 3u, 1u, 2u, true) == ((3u << 4) | (1u << 18) | (2u << 30)) &&
              LampLayersBitsFor(2u, 3u, 1u, 2u, true) == LampLayersTwo &&
              LampLayersBitsFor(3u, 7u, 3u, 3u, true) == LampLayersAllBits &&
              LampLayersBitsFor(3u, 3u, 1u, 2u, false) == 0u && LampLayersBitsFor(0u, 3u, 1u, 2u, true) == 0u &&
              LampLayersBitsFor(1u, 0u, 1u, 2u, true) == 0u);
static_assert(LampLayersShare(3u) == 0.375f && LampLayersWide(1u) == 2.5f && LampLayersWide(3u) == 3.5f &&
              LampLayersCore(0u) == 1.0f && LampLayersCore(2u) == 0.5f);

#if BB_LAMP_SHADOW_LAYERS_LIVE
inline std::uint32_t LampLayersMode() {
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_SHADOW_LAYERS", LampLayersParseMode};
    return knob.Get();
}
inline std::uint32_t LampLayersHalo() {
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_SHADOW_LAYERS_HALO", LampLayersParseHalo};
    return knob.Get();
}
inline std::uint32_t LampLayersWideCode() {
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_SHADOW_LAYERS_WIDE", LampLayersParseWide};
    return knob.Get();
}
inline std::uint32_t LampLayersCoreCode() {
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_SHADOW_LAYERS_CORE", LampLayersParseCore};
    return knob.Get();
}
#else
inline std::uint32_t LampLayersMode() {
    static const std::uint32_t value = LampLayersParseMode(std::getenv("BB_LAMP_SHADOW_LAYERS"));
    return value;
}
inline std::uint32_t LampLayersHalo() {
    static const std::uint32_t value = LampLayersParseHalo(std::getenv("BB_LAMP_SHADOW_LAYERS_HALO"));
    return value;
}
inline std::uint32_t LampLayersWideCode() {
    static const std::uint32_t value = LampLayersParseWide(std::getenv("BB_LAMP_SHADOW_LAYERS_WIDE"));
    return value;
}
inline std::uint32_t LampLayersCoreCode() {
    static const std::uint32_t value = LampLayersParseCore(std::getenv("BB_LAMP_SHADOW_LAYERS_CORE"));
    return value;
}
#endif

namespace LampLayersDetail {
inline std::uint32_t passes = 0;      ///< passes with any of the bits since the last line
inline std::uint32_t halo_passes = 0; ///< of them, with the core and halo
inline std::uint32_t two_passes = 0;  ///< of them, with the second lamp's own ray
inline std::uint32_t told = 0xFFFFFFFFu; ///< the knobs the once-line said last (mode | halo << 8 | wide << 16 | core << 24)
} // namespace LampLayersDetail

/// PointShadow::Flush, once a ray traced pass with the repair: what it ORs into tuning word 0 (0 with
/// the knob at 0: the words as before). disc: as LampLayersBitsFor's. Says the once-line when the knob
/// is first set and again whenever one of the four changes (a live knob), on or off first.
inline std::uint32_t LampLayersBits(bool disc) {
    const std::uint32_t mode = LampLayersMode(), halo = LampLayersHalo(), wide = LampLayersWideCode(),
                        core = LampLayersCoreCode();
    const std::uint32_t knobs = mode | halo << 8 | wide << 16 | core << 24;
    if (knobs != LampLayersDetail::told && (mode != 0u || LampLayersDetail::told != 0xFFFFFFFFu)) {
        LampLayersDetail::told = knobs;
        const bool ring = (mode & 1u) != 0u && halo != 0u;
        std::printf("Ray traced lamps (r114): layered lamp shadows %s (BB_LAMP_SHADOW_LAYERS=%u): halo %s (%.3f of "
                    "each lamp's rays to %.1f times its disc, at most 0.6 m, the rest to %.2f times it), second "
                    "lamp's own ray %s; soft and softer lamps in the pass that averages only\n",
                    mode != 0u ? "on" : "off", unsigned(mode), ring ? "on" : "off",
                    double(ring ? LampLayersShare(halo) : 0.0f), double(LampLayersWide(wide)),
                    double(ring ? LampLayersCore(core) : 1.0f), (mode & 2u) != 0u ? "on" : "off");
    }
    const std::uint32_t bits = LampLayersBitsFor(mode, halo, wide, core, disc);
    LampLayersDetail::passes += bits != 0u ? 1u : 0u;
    LampLayersDetail::halo_passes += (bits & (LampLayersHaloMask << LampLayersHaloShift)) != 0u ? 1u : 0u;
    LampLayersDetail::two_passes += (bits & LampLayersTwo) != 0u ? 1u : 0u;
    return bits;
}

/// PointShadow's r42 lamp line (every 600 frames), right after r103's short line: a short line of its
/// own (the slot runs keep 300 characters of a line), while the knob is set or a pass had the bits.
inline void LampLayersLine() {
    if (LampLayersMode() != 0u || LampLayersDetail::passes != 0u) {
        std::printf("Ray traced lamps (r114): %u ray traced lamp passes had layered shadows since the r42 line "
                    "before (%u the core and halo, %u the second lamp's own ray; BB_LAMP_SHADOW_LAYERS=%u)\n",
                    unsigned(LampLayersDetail::passes), unsigned(LampLayersDetail::halo_passes),
                    unsigned(LampLayersDetail::two_passes), unsigned(LampLayersMode()));
    }
    LampLayersDetail::passes = LampLayersDetail::halo_passes = LampLayersDetail::two_passes = 0;
}

} // namespace Vulkan
'''

GLOBALS = r'''// bbport (r114_lamp-shadow-layers): BB_LAMP_SHADOW_LAYERS (lamp_shadow_layers.h; tune word 0 bits
// 4-6, 7, 18-19 and 30-31, loadTune). t_halo: the share of each lamp's rays that goes to its halo (0:
// none, and no core); t_halo_wide, t_halo_core: the halo's and the core's radius over the lamp's disc;
// t_layers_two: the second strongest lamp gets a ray of its own in the pick path. lay_sec_w, lay_sec_l,
// lay_sec_at: that lamp's weight, place and record; lay_top_at, lay_cand_at: the records of top_l and
// cand_l in the pick loop; lay_sec_part: what its ray let through, times its weight (below 0: not cast).
float t_halo = 0.0;
float t_halo_wide = 2.0;
float t_halo_core = 1.0;
bool t_layers_two = false;
const float LAYERS_HALO_MOST = 0.6; // m: the widest halo (never narrower than the disc)
float lay_sec_w = 0.0;
vec3 lay_sec_l = vec3(0.0);
uint lay_sec_at = 0u, lay_top_at = 0u, lay_cand_at = 0u;
float lay_sec_part = -1.0;
'''

LOADTUNE = r'''    t_halo = float((f >> 4u) & 7u) * (1.0 / 8.0);     // bbport (r114_lamp-shadow-layers)
    t_halo_wide = 2.0 + 0.5 * float((f >> 18u) & 3u); // bbport (r114_lamp-shadow-layers)
    t_halo_core = 1.0 - 0.25 * float(f >> 30u);       // bbport (r114_lamp-shadow-layers)
    t_layers_two = (f & (1u << 7u)) != 0u;            // bbport (r114_lamp-shadow-layers)
'''

HALO = r'''        // bbport (r114_lamp-shadow-layers): BB_LAMP_SHADOW_LAYERS 1 or 3: the points whose xi.x lies
        // below t_halo (that share of the frames) lie on a halo t_halo_wide times the disc (at most
        // LAYERS_HALO_MOST m, never narrower than the disc), the others on a core t_halo_core times
        // it; xi.x is stretched back to 0..1 within each part, so each keeps its points evenly over its
        // area. Averaged over the frames a shadow's edge gets a steep inner slope (the core) and a wide
        // pale outer layer, t_halo deep at most (the halo). A halo point's ray is blind as much further
        // as the point lies beyond the disc (so the wall behind a wall lamp, or the hand at a torch,
        // does not take the halo's light from everything the lamp lights); the base is this call's
        // blind distance (word 10's, read just above, with the per-lamp disc; else t_clear), set anew
        // at every call, so no lamp keeps another's.
        if (t_halo > 0.0) {
            const float disc_r = radius;
            float halo_beyond = 0.0;
            if (xi.x < t_halo) {
                xi.x /= t_halo;
                radius = max(radius, min(radius * t_halo_wide, LAYERS_HALO_MOST));
                halo_beyond = max(radius * sqrt(xi.x) - disc_r, 0.0);
            } else {
                xi.x = (xi.x - t_halo) / (1.0 - t_halo);
                radius *= t_halo_core;
            }
            ray_clear += (t_disc_each ? 0.0 : t_clear - ray_clear) + halo_beyond;
        }
'''

TRACK = r'''            if (t_layers_two) { // bbport (r114_lamp-shadow-layers): the records of top_l and cand_l below
                lay_cand_at = w > view_top ? lay_top_at : at;
                lay_top_at = w > view_top ? at : lay_top_at;
            }
'''

SWAP = r'''            // bbport (r114_lamp-shadow-layers): the second strongest lamp keeps a ray of its own; the pick
            // below stands only for the lamps weaker than it
            if (t_layers_two && cand_w > lay_sec_w) {
                const float was_w = lay_sec_w;
                const vec3 was_l = lay_sec_l;
                const uint was_at = lay_sec_at;
                lay_sec_w = cand_w;
                lay_sec_l = cand_l;
                lay_sec_at = lay_cand_at;
                cand_w = was_w;
                cand_l = was_l;
                lay_cand_at = was_at;
                pick_cand = was_at; // (the record the pick takes on, for a lamp's own disc)
            }
'''

SECRAY = r'''            // bbport (r114_lamp-shadow-layers): the second strongest lamp's own ray, to the point of its
            // disc the picked lamp's ray took before when nothing is picked (two lamps: the pixel traces
            // what it did), else to the next one (the exact path's spacing); lampVisibility's call after
            // the strongest's (and the pick's) takes its record
            if (lay_sec_w > 0.0) {
                const uint rest_at = pick_rest;
                pick_rest = lay_sec_at;
                lay_sec_part = lay_sec_w * lampVisibility(P, n, origin, reach, lay_sec_l,
                                                          fract(xi + (rest_w > 0.0 ? 2.0 : 1.0) *
                                                                         vec2(0.5545497, 0.3085170)));
                pick_rest = rest_at;
                vsum += lay_sec_part;
            }
'''

SECCOLOUR = r'''#if defined(COLOUR)
        // bbport (r114_lamp-shadow-layers): with the second strongest lamp's own ray, its part in its own
        // colour as well (the picked lamp's answer then stands only for the lamps weaker than it)
        if (t_colour && lay_sec_part >= 0.0 && vsum_top >= 0.0) {
            const vec3 top_c = colourOf(vec3(word(top_at + 4u), word(top_at + 5u), word(top_at + 6u)));
            const vec3 sec_c = colourOf(vec3(word(lay_sec_at + 4u), word(lay_sec_at + 5u), word(lay_sec_at + 6u)));
            vsum_c = top_c * vsum_top + sec_c * lay_sec_part;
            if (0.0 < rest_w) {
                vsum_c += max(wsum_c - top_w * top_c - lay_sec_w * sec_c, vec3(0.0)) *
                          ((vsum - vsum_top - lay_sec_part) / rest_w);
            }
            colour_rc = clamp(mix(vec3(ratio), vsum_c / max(wsum_c, vec3(1e-30)), greaterThan(wsum_c, vec3(0.0))),
                              0.0, 1.0);
        }
#endif
'''

ROWS = (
    "| `BB_LAMP_SHADOW_LAYERS` | Layered lamp shadows; soft or softer lamps in the pass that averages over frames only "
    "(sharp changes nothing). `1`: a share `BB_LAMP_SHADOW_LAYERS_HALO` of each lamp's rays goes to a halo "
    "`BB_LAMP_SHADOW_LAYERS_WIDE` times the lamp's disc (at most 0.6 m; such a ray is blind as much further as its "
    "point lies beyond the disc), the rest to a core "
    "`BB_LAMP_SHADOW_LAYERS_CORE` times it, so a shadow's edge gets a steep inner slope and a wide pale outer layer; no "
    "extra ray. `BB_LAMP_SHADOW_FLAME` is the same idea in another form: set one of the two. "
    "`2`: where three or more lamps light a pixel, the second strongest gets a ray of its own every frame "
    "(before, it shared the one picked ray with every weaker lamp, a new pick each frame), so overlapping shadows keep "
    "their own darkness (and colour with `BB_LAMP_SHADOW_COLOUR=1`); one ray more there only, pixels with one or two "
    "lamps trace as before. `3`: both. With the test tools' live knobs file it can be changed while the game runs | `0` |\n"
    "| `BB_LAMP_SHADOW_LAYERS_HALO` | With `BB_LAMP_SHADOW_LAYERS` 1 or 3: the halo's share of each lamp's rays, 0 to 1 "
    "in eighths (rounded, at most 7/8); the pale outer layer is at most this deep; 0 is neither halo nor core | "
    "`0.375` |\n"
    "| `BB_LAMP_SHADOW_LAYERS_WIDE` | With `BB_LAMP_SHADOW_LAYERS` 1 or 3: the halo's radius over the lamp's disc, 2, "
    "2.5, 3 or 3.5 (the nearest) | `2.5` |\n"
    "| `BB_LAMP_SHADOW_LAYERS_CORE` | With `BB_LAMP_SHADOW_LAYERS` 1 or 3: the core's radius over the lamp's disc, 1, "
    "0.75, 0.5 or 0.25 (the nearest); below 1 the inner edge is crisper than the softness setting alone | `0.5` |\n"
)


def readme_edit(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_COLOUR` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_COLOUR row is there %d times, wanted 1 (r92 first)"
                         % len(lines))
    return (lines[0] + "\n", "", ROWS)


# (anchor, text before it, text after it); each anchor must be found exactly once.
EDITS = {
    S: [
        ("float ray_clear = 0.0;\n", "", GLOBALS),
        ("    t_disc_each = (f & (1u << 24u)) != 0u; // bbport (r91_lamp-radius-per-lamp)\n", "", LOADTUNE),
        ("    if (radius > 0.0) {\n", "", HALO),
        ("            ++lamps;\n", TRACK, ""),
        ("            if (cand_w > 0.0) {\n", SWAP, ""),
        ("                vsum += rest_w * lampVisibility(P, n, origin, reach, rest_l,\n"
         "                                                fract(xi + vec2(0.5545497, 0.3085170)));\n"
         "            }\n", "", SECRAY),
        ("        stable = old_valid && abs(ratio - old_ratio) < STABLE_CHANGE ? min(old_stable + 1.0, 15.0) : 0.0;\n",
         SECCOLOUR, ""),
    ],
    C: [
        ('#include "video_core/renderer_vulkan/lamp_moving_edge.h" // bbport (r101_lamp-moving-edge)\n', "",
         '#include "video_core/renderer_vulkan/lamp_shadow_layers.h" // bbport (r114_lamp-shadow-layers)\n'),
        ("            data[tune_at] |= LampTuneSpatialBit(pass_tune); // bbport (r93_lamp-shadow-spatial): bit 26\n", "",
         "            data[tune_at] |= LampLayersBits(pass_tune.radius_m > 0.0f && LampHistoryFrames(pass_tune) > 0.0f); "
         "// bbport (r114_lamp-shadow-layers): bits 4-7, 18, 19, 30, 31; 0 when off\n"),
        ("    LampYoungLine(); // bbport (r103_lamp-young-pixels): a short line after the r42 line, only with the knob set\n",
         "", "    LampLayersLine(); // bbport (r114_lamp-shadow-layers): a short line after the r42 line, with the knob set\n"),
    ],
}


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


def text_checks(texts, originals):
    """The ties a compiler cannot check."""
    s, o = texts[S], originals[S]
    for want, n in (("(1u << 7u)", 1), ("(f >> 4u) & 7u", 1), ("(f >> 18u) & 3u", 1), ("float(f >> 30u)", 1),
                    ("float t_halo = 0.0;", 1), ("const float LAYERS_HALO_MOST = 0.6;", 1),
                    ("2.0 + 0.5 * float(", 1), ("1.0 - 0.25 * float(", 1), ("(1.0 / 8.0)", 1),
                    ("ray_clear += (t_disc_each ? 0.0 : t_clear - ray_clear) + halo_beyond;", 1),
                    ("fract(xi + (rest_w > 0.0 ? 2.0 : 1.0) *", 1),
                    ("lay_sec_part = lay_sec_w * lampVisibility(", 1), (TAG, 10)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # no other reader of the bits: the shader's word 0 tests before this patch use none of them
    for other in ("(f >> 4u)", "(f >> 7u)", "(1u << 7u)", "(1u << 4u)", "(1u << 5u)", "(1u << 6u)", "(1u << 11u)",
                  "(f >> 18u)", "(f >> 30u)", "(1u << 30u)", "(1u << 31u)"):
        if o.count(other) != 0:
            raise SystemExit("text check: %s already reads %r" % (S, other))
    # the siblings' own checks count these: unchanged
    for keep in ("#ifdef COLOUR\n", "lampRecord(", "ray_clear = ", "pick_rest = pick_cand;", "(1u << 24u)",
                 "(1u << 25u)", "(1u << 26u)", "(1u << 27u)", "(1u << 28u)", "(1u << 29u)"):
        if s.count(keep) != o.count(keep):
            raise SystemExit("text check: %s: %r %d times, %d before" % (S, keep, s.count(keep), o.count(keep)))
    if s.count("#if") != s.count("#endif"):
        raise SystemExit("text check: #if and #endif do not pair")
    for block in (GLOBALS, LOADTUNE, HALO, TRACK, SWAP, SECRAY, SECCOLOUR):
        low = block.lower()
        for word in ("spatial", "r91", "r92", "r93", "r101", "r103", "young"):
            if word in low:
                raise SystemExit("text check: an r114 shader text names %r (a sibling's check scans for it)" % word)
        if not all(ord(c) < 128 for c in block) or "\r" in block:
            raise SystemExit("text check: r114 text must be ASCII with LF in the script")
    # the order in the shader
    order = ["float ray_clear = 0.0;\n// bbport (r114", "void loadTune()", "    t_halo = float((f >> 4u)",
             "float lampVisibility(", "if (t_halo > 0.0) {", "void main()", "lay_cand_at = w > view_top",
             "            ++lamps;", "if (t_layers_two && cand_w > lay_sec_w) {", "            if (cand_w > 0.0) {",
             "vsum += rest_w * lampVisibility(P, n, origin, reach, rest_l,", "if (lay_sec_w > 0.0) {",
             "        ratio = clamp(vsum / wsum, 0.0, 1.0);", "colour_rc = clamp(mix(vec3(ratio), vsum_c",
             "if (t_colour && lay_sec_part >= 0.0 && vsum_top >= 0.0) {", "        stable = old_valid &&"]
    at = -1
    for want in order:
        i = s.find(want, at + 1)
        if i < 0:
            raise SystemExit("order check: %s: %r not after the one before" % (S, want))
        at = i
    # the core and halo lie inside lampVisibility's disc block, before the point is laid out
    a, b, c = s.find("    if (radius > 0.0) {\n        // bbport (r114"), s.find("if (t_halo > 0.0) {"), \
        s.find("            const float a = 6.2831853 * xi.y;")
    if not (0 <= a < b < c):
        raise SystemExit("text check: the halo is not between `if (radius > 0.0) {` and the disc point")
    # shader decode and the header agree
    for want in ("LampLayersHaloShift = 4, LampLayersHaloMask = 7u;", "LampLayersTwo = 1u << 7;",
                 "LampLayersWideShift = 18, LampLayersWideMask = 3u;", "LampLayersCoreShift = 30, LampLayersCoreMask = 3u;",
                 "return 2.0f + 0.5f * float(wide);", "return float(halo) / 8.0f;", "return 1.0f - 0.25f * float(core);",
                 "at most 0.6 m", "(1u << 11) | (1u << 23)", "* 8u + n.den / 2u"):
        if want not in HEADER:
            raise SystemExit("text check: header lacks %r" % want)
    if "at most 0.6 m" not in ROWS or "eighths" not in ROWS or "(1.0 / 8.0)" not in LOADTUNE:
        raise SystemExit("text check: README rows and shader disagree")
    cs = texts[C]
    for want, n in (("LampLayersBits(", 1), ("LampLayersLine();", 1), ('lamp_shadow_layers.h"', 1), (TAG, 3)):
        if cs.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (C, want, cs.count(want), n))
    if not (0 <= cs.find("LampYoungLine();") < cs.find("LampLayersLine();") < cs.find("    track.ClearSteps();\n")):
        raise SystemExit("text check: the r114 line is not between r103's line and ClearSteps")
    if not (0 <= cs.find("tune_at = u32(data.size());") < cs.find("LampLayersBits(")):
        raise SystemExit("text check: the r114 OR is not after the tune words")
    if texts[R].count("| `BB_LAMP_SHADOW_LAYERS") != 4:
        raise SystemExit("text check: README rows")


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
        raise SystemExit("%s is not a source tree root (set R114_ROOT)" % ROOT)
    new_full = os.path.join(ROOT, NEW)
    header = HEADER.replace("\n", "\r\n").encode("utf-8")
    new_there = os.path.exists(new_full)
    new_ours = new_there and open(new_full, "rb").read() == header
    plan = []
    for path in (S, C, R):
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
            tmp = full + ".r114tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        open(new_full, "wb").write(header)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = reverted_texts()
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r114tmp"
        open(tmp, "wb").write(out[path].replace("\n", eol).encode("utf-8"))
        os.replace(tmp, full)
    os.remove(new_full)
    print("reverted")


main()
