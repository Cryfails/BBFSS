// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN. No Vulkan here.
//
// The ray traced sun (rt_shadow.comp) crosses the cut-out cards of the ray traced scene as the lamp rays do (rt_cards.glsl cardTraceShadow): a
// leaf's, a weed's or a static cut-out's texel the game's alpha test keeps stops the sun, a dropped texel lets it through. Off by default; it needs
// BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 (the instances take CARD_LAMP_MASK through the lamp card path) and is not made with BB_RT_GLASS_LIGHT
// (the two share the sun trace's counter words 16 and up).

#include <cstdint>

#include "../host_shaders/rt_card_sun_layout.h"

namespace Vulkan {

/// BB_RT_CARD_SUN's text: exactly "1" is on; unset, empty, "0" or anything else is off.
constexpr bool CardSunText(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}
static_assert(CardSunText("1") && !CardSunText("0") && !CardSunText("") && !CardSunText("11") && !CardSunText("on") &&
              !CardSunText(nullptr));

/// bbport (r131b_lrt-settings): the sun side from BB_RT_CARD_SUN or, when that is unset or empty, the setting graphics_rt_foliage_shadows
/// (2 = lamps and sun). A variable that is set decides (also "0" and text: off).
constexpr bool CardSunOf(const char* env, int setting) {
    return env != nullptr && env[0] != '\0' ? CardSunText(env) : setting >= 2;
}
/// The live knob's reading (test builds): -1 unset or empty (CardSunWanted decided at the start: the variable or the setting), else 1 for
/// exactly "1" and 0 for the rest.
constexpr int CardSunLive(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : CardSunText(text) ? 1 : 0;
}
static_assert(CardSunOf("1", 0) && !CardSunOf("0", 2) && CardSunOf(nullptr, 2) && CardSunOf("", 2) && !CardSunOf(nullptr, 1) &&
              !CardSunOf("", 0) && !CardSunOf("on", 2));
static_assert(CardSunLive(nullptr) == -1 && CardSunLive("") == -1 && CardSunLive("1") == 1 && CardSunLive("0") == 0 && CardSunLive("on") == 0);

inline constexpr std::uint32_t CardSunFirstWord = CARD_SUN_FIRST_WORD;
inline constexpr std::uint32_t CardSunWords = CARD_SUN_WORDS;
/// The sun trace's counters with the knob on (r25's 16 words, then these).
inline constexpr std::uint32_t CardSunCounterWords = CardSunFirstWord + CardSunWords;
static_assert(CardSunWords == 8 && CardSunCounterWords == 24);

} // namespace Vulkan
