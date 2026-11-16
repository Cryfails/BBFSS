// SPDX-License-Identifier: GPL-3.0-or-later
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
