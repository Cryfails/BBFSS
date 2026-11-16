// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86_glass-light-stage2a): sunlight through window panes, its first part
// (BB_RT_GLASS_LIGHT). No Vulkan here.
//
// r83 (BB_RT_GLASS) put the game's forward window pane draws into the ray traced scene under
// RtGlassMask (0x10) alone, which no ray traced. The game draws them after the sun's trace and the
// lamp pass; RtShadow builds captures only for a reader of the scene and forgets a frame's entries
// at its end. So with this knob on RtShadow builds the waiting captures at the frame end while a
// pane's is among them, and carries the panes drawn in a frame into the next frame's scene
// (CollectHeld). Where the sun's ray reaches the sun, a second ray asks the panes (rt_shadow.comp,
// GLASS_LIGHT builds): every pane triangle a candidate, at most RtGlassLightCap. No colour yet:
// "1" counts, "view" shows the window's shape of light (half the sun per candidate), "probe" also
// asks whether a shadowed pixel's blocker is a pane's own copy in the sun's scene.

#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/rt_glass_light_layout.h"
#include "rt_glass.h"
#include "glass_glint.h" // bbport (r86b_glass-visible)

namespace Vulkan {

enum class RtGlassLightMode : std::uint32_t { Off = 0, Count = 1, View = 2, Probe = 3 };

constexpr bool RtGlassLightSame(const char* a, const char* b) {
    std::size_t i = 0;
    while (a[i] != '\0' && a[i] == b[i]) {
        ++i;
    }
    return a[i] == b[i];
}

/// BB_RT_GLASS_LIGHT's text: "1" Count, "view" View, "probe" Probe; anything else (unset, empty,
/// "0") Off.
constexpr RtGlassLightMode ParseRtGlassLight(const char* text) {
    return !text                             ? RtGlassLightMode::Off
           : RtGlassLightSame(text, "1")     ? RtGlassLightMode::Count
           : RtGlassLightSame(text, "view")  ? RtGlassLightMode::View
           : RtGlassLightSame(text, "probe") ? RtGlassLightMode::Probe
                                             : RtGlassLightMode::Off;
}
static_assert(ParseRtGlassLight("1") == RtGlassLightMode::Count);
static_assert(ParseRtGlassLight("view") == RtGlassLightMode::View);
static_assert(ParseRtGlassLight("probe") == RtGlassLightMode::Probe);
static_assert(ParseRtGlassLight("0") == RtGlassLightMode::Off && ParseRtGlassLight("") == RtGlassLightMode::Off);
static_assert(ParseRtGlassLight("2") == RtGlassLightMode::Off && ParseRtGlassLight("views") == RtGlassLightMode::Off);
static_assert(ParseRtGlassLight(nullptr) == RtGlassLightMode::Off);

/// The sun trace's r25_flags bits (rt_glass_light_layout.h), above r25's 1, 2, 4 and 8.
inline constexpr std::uint32_t RtGlassLightPanes = RT_GLASS_LIGHT_PANES;
inline constexpr std::uint32_t RtGlassLightView = RT_GLASS_LIGHT_VIEW;
inline constexpr std::uint32_t RtGlassLightProbe = RT_GLASS_LIGHT_PROBE;
static_assert(((RtGlassLightPanes | RtGlassLightView | RtGlassLightProbe) & 15u) == 0);
inline constexpr std::uint32_t RtGlassLightCap = RT_GLASS_LIGHT_CAP;
inline constexpr std::uint32_t RtGlassLightFirstWord = RT_GLASS_LIGHT_FIRST_WORD;
inline constexpr std::uint32_t RtGlassLightWords = RT_GLASS_LIGHT_WORDS;
/// The sun trace's counters with the knob on (r25's 16 words, then these).
inline constexpr std::uint32_t RtGlassLightCounterWords = RtGlassLightFirstWord + RtGlassLightWords;

/// A sun trace's r25_flags bits: none when off or when no pane is in the scene.
constexpr std::uint32_t RtGlassLightFlags(RtGlassLightMode mode, bool panes) {
    return mode == RtGlassLightMode::Off || !panes
               ? 0u
               : RtGlassLightPanes | (mode == RtGlassLightMode::View ? RtGlassLightView : 0u) |
                     (mode == RtGlassLightMode::Probe ? RtGlassLightProbe : 0u);
}
static_assert(RtGlassLightFlags(RtGlassLightMode::Off, true) == 0);
static_assert(RtGlassLightFlags(RtGlassLightMode::View, false) == 0);
static_assert(RtGlassLightFlags(RtGlassLightMode::Count, true) == RtGlassLightPanes);
static_assert(RtGlassLightFlags(RtGlassLightMode::View, true) == (RtGlassLightPanes | RtGlassLightView));
static_assert(RtGlassLightFlags(RtGlassLightMode::Probe, true) == (RtGlassLightPanes | RtGlassLightProbe));

constexpr const char* RtGlassLightName(RtGlassLightMode mode) {
    return mode == RtGlassLightMode::Count  ? "1"
           : mode == RtGlassLightMode::View  ? "view"
           : mode == RtGlassLightMode::Probe ? "probe"
                                             : "off";
}

/// The knob, read once; off while BB_RT_GLASS is off (no pane is in the scene then).
inline RtGlassLightMode RtGlassLight() {
    static const RtGlassLightMode mode =
        RtGlassOn() ? ParseRtGlassLight(std::getenv("BB_RT_GLASS_LIGHT")) : RtGlassLightMode::Off;
    return mode;
}

inline bool RtGlassLightOn() {
    return RtGlassLight() != RtGlassLightMode::Off;
}

// bbport (r86b_glass-visible): RtShadow carries the panes drawn in a frame into the next frame's
// scene and builds their waiting captures at the frame end while BB_RT_GLASS_LIGHT or
// BB_GLASS_GLINT (glass_glint.h) is on; both off: false, as before.
inline bool RtGlassCarryOn() {
    return RtGlassLightOn() || ::BbGlassGlint::On();
}

} // namespace Vulkan
