// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r111b_footprints-pickup): is a ground pixel blood? One rule for every effect that needs it
// (the footprints' pickup, the blood sheen): from the pixel's LINEAR albedo (the game's G-buffer
// target 2 decoded from sRGB), dark red:
//   red between BLOOD_ALBEDO_R_MIN (0.01) and BLOOD_ALBEDO_R_MAX (0.12), and
//   red at least BLOOD_ALBEDO_RED_OVER_GREEN (2.5) times green and BLOOD_ALBEDO_RED_OVER_BLUE (2.5)
//   times blue.
// Grounds it was checked against (the footprints log, "linear albedo mean", the band of ground around
// the hunter): the graveyard's blood pool 0.021 0.006 0.005 is blood; the church floor
// 0.125 0.109 0.087 and the dream house floor 0.085 0.132 0.146 are not (green and blue too high);
// a bright red (0.3 0.02 0.015) is not (red over the maximum), nor is near black (red under 0.01: the
// ratios are noise there).
// The numbers live in host_shaders/blood_albedo_layout.h (plain #defines), which the shaders include;
// the shader twin is IsBloodAlbedo in host_shaders/footprints.comp (same four numbers, same tests).
// No Vulkan here: tests/test_blood_albedo.cpp builds it alone.

#include "../host_shaders/blood_albedo_layout.h"

namespace Vulkan::BloodAlbedo {

inline constexpr float RMin = float(BLOOD_ALBEDO_R_MIN);
inline constexpr float RMax = float(BLOOD_ALBEDO_R_MAX);
inline constexpr float RedOverGreen = float(BLOOD_ALBEDO_RED_OVER_GREEN);
inline constexpr float RedOverBlue = float(BLOOD_ALBEDO_RED_OVER_BLUE);

/// `r`, `g`, `b`: linear albedo.
constexpr bool IsBlood(float r, float g, float b) {
    return r >= RMin && r <= RMax && r >= RedOverGreen * g && r >= RedOverBlue * b;
}

inline bool IsBlood(const float rgb[3]) {
    return IsBlood(rgb[0], rgb[1], rgb[2]);
}

} // namespace Vulkan::BloodAlbedo
