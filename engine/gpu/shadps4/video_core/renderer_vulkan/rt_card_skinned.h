// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r62n_cutout-skinned-blocker): which skinned cut-out cards may cast lamp shadows (BB_RT_CARD_LAMP_SKINNED), and what a card that
// blocks lamp light is (the blocker lines of the lamp pass). No Vulkan here: the rule, the counts and the names only.
//
// A skinned cut-out is a card whose draw binds a skeleton palette (Motion::BufferRole::Skeleton, 640 bytes or more). r62e lets one cast
// a lamp shadow only when r46b's sign takes it for a plant (`lone`: no sun shadow pass draws its vertices while the sun shadow pass
// draws skeletons). A skinned entry has no motion measure (it is refit at every draw; the still looks hold only entries that are not
// dynamic), so 'moves' is taken as 'is the rig of a figure': more bones than BB_RT_CARD_LAMP_BONES (default 24, r112h's limit; the
// hunter's gear has 28 bones, enemies 69-130, the hunter 277).

#include <array>
#include <cstdint>

namespace Vulkan {

/// BB_RT_CARD_LAMP_SKINNED: Rule (0, the default) a lone skinned card casts when its skeleton has few bones; All (1) every lone skinned
/// card (r62m's behaviour); None (2) none.
enum class CardSkinnedMode : std::uint8_t { Rule = 0, All = 1, None = 2 };

/// The knob's text: exactly "1" or "2"; anything else, none set included, is the rule.
[[nodiscard]] constexpr CardSkinnedMode CardSkinnedModeOf(const char* text) noexcept {
    if (text != nullptr && text[0] != '\0' && text[1] == '\0') {
        return text[0] == '1'   ? CardSkinnedMode::All
               : text[0] == '2' ? CardSkinnedMode::None
                                : CardSkinnedMode::Rule;
    }
    return CardSkinnedMode::Rule;
}

inline constexpr std::uint32_t CardSkinnedBonesDefault = 24;
inline constexpr std::uint32_t CardSkinnedBonesMost = 341; ///< 16384 bytes of palette / 48

/// BB_RT_CARD_LAMP_BONES: a whole number from 1 to CardSkinnedBonesMost; anything else the default.
[[nodiscard]] constexpr std::uint32_t CardSkinnedBonesOf(const char* text) noexcept {
    if (text == nullptr || text[0] == '\0') {
        return CardSkinnedBonesDefault;
    }
    std::uint32_t value = 0;
    for (const char* p = text; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9' || value > 1000) {
            return CardSkinnedBonesDefault;
        }
        value = value * 10 + std::uint32_t(*p - '0');
    }
    return value >= 1 && value <= CardSkinnedBonesMost ? value : CardSkinnedBonesDefault;
}

/// May a lone skinned cut-out card with `bones` bones (0: none read) carry the lamp card bit?
[[nodiscard]] constexpr bool CardSkinnedLampOk(CardSkinnedMode mode, std::uint32_t bones,
                                               std::uint32_t bones_most) noexcept {
    return mode == CardSkinnedMode::All ||
           (mode == CardSkinnedMode::Rule && bones != 0 && bones <= bones_most);
}

/// What the rule judged in the last scene: the lone skinned cut-out cards, how many it let cast, and the judged by bones
/// (at most 24, 25 to 48, 49 to 96, more or none read).
struct CardSkinnedScene {
    std::uint32_t judged = 0, allowed = 0;
    std::array<std::uint32_t, 4> bins{};
    constexpr void Note(bool ok, std::uint32_t bones) noexcept {
        ++judged;
        allowed += ok ? 1u : 0u;
        ++bins[bones == 0 ? 3 : bones <= 24 ? 0 : bones <= 48 ? 1 : bones <= 96 ? 2 : 3];
    }
};

/// What a card that blocked lamp light is, by what is known of it and of the hunter.
enum class CardBlockerKind : std::uint8_t { Unknown, Plant, Character, Hunter };

inline constexpr float CardHunterNearM = 1.5f;  ///< m sideways (r112h's BB_WIND_HANG_NEAR)
inline constexpr float CardHunterBelow = 1.5f;  ///< m under his position
inline constexpr float CardHunterAbove = 2.5f;  ///< m over his position

/// A point `horizontal_m` sideways and `up_m` above the hunter's position (up_m negative: under it) lies on him.
[[nodiscard]] constexpr bool CardNearHunter(float horizontal_m, float up_m, float near_m) noexcept {
    return near_m > 0.0f && horizontal_m <= near_m && up_m >= -CardHunterBelow && up_m <= CardHunterAbove;
}

/// Unknown: no skeleton. A rig of a figure (not lone, or over `bones_most` bones): the hunter when on him, else a character. Else a plant.
[[nodiscard]] constexpr CardBlockerKind CardBlockerKindOf(bool skinned, bool lone, std::uint32_t bones,
                                                          std::uint32_t bones_most, bool on_hunter) noexcept {
    if (!skinned) {
        return CardBlockerKind::Unknown;
    }
    if (!lone || bones > bones_most) {
        return on_hunter ? CardBlockerKind::Hunter : CardBlockerKind::Character;
    }
    return CardBlockerKind::Plant;
}

[[nodiscard]] constexpr const char* CardBlockerKindText(CardBlockerKind kind) noexcept {
    switch (kind) {
    case CardBlockerKind::Hunter:
        return "the hunter";
    case CardBlockerKind::Character:
        return "a character";
    case CardBlockerKind::Plant:
        return "a plant";
    default:
        return "unknown";
    }
}

} // namespace Vulkan
