// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r80_lamp-fog-shafts): lamp and torch shafts through fog, a first experiment. The lamp
// fog (point_volumetric.comp: every light the game lists, the hunter's torch and hand lantern
// included) is unshadowed: a pillar or the hunter between a light and the fog does not cut its
// glow. With BB_LAMP_FOG_SHAFTS set, every frame with lamp fog and a ray traced scene first builds
// the octahedral shadow maps r106 picks for the lamp fog's lights (lamp_fog_shaft_map.comp:
// from the light's centre, one ray per texel through the frame's ray traced scene, instance mask
// SceneMask, blind within Blind(radius) of the centre, out to the light's radius; the texel keeps
// the nearest hit's distance (r106: metres, SHAFT_FREE where nothing is hit). The SHAFTS builds
// then multiply each segment's light by Lit(): the share of the four map texels around the
// direction from the light to the segment's sample point whose free distance reaches the point
// (less Bias of the radius). The sample point is the place where the segment's inverse-square
// energy is split in half (EnergyMiddle). The SHAFTS builds take Bias and Segments from their
// push constants (VolumetricLight::RecordShafts). No Vulkan here: tests/test_lamp_fog_shafts.cpp
// builds this header alone.
//
// BB_LAMP_FOG_SHAFTS, read once at start; unset, empty or any text but "0" to "3" is 0:
//   0 off: the lamp fog's pass and build of before; nothing of this runs or is made
//   1 on: 128x128 maps, 6 segments a half chord (the march's count of before)
//   2 on: 256x256 maps, 12 segments a half chord
//   3 as 1, the lamp fog drawn as a debug view: orange the light that reaches the fog, blue the
//     light the maps cut off, both 4 times as bright as the fog
// The maps exist only while the ray traced scene is built (effect_ray_tracing on, which the
// settings derive from the ray traced sun, lamp shadows, bounced light and virtual shadow maps; a
// set knob with lamp fog on also makes RtShadow::SceneWanted true) and only in frames that draw
// lamp fog, which needs the game's sun shadow resolve (VolumetricLight::Integrate). With r106
// (lamp_fog_shaft_cap.h) a map belongs to a lamp and is kept across frames within a ray budget:
// its texels are world directions and keep the free distance in metres (SHAFT_FREE where
// nothing is hit); Lit() below takes that distance over the radius, as the march compares it.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace Vulkan::LampFogShafts {

inline constexpr std::uint32_t Off = 0, Medium = 1, High = 2, View = 3;

/// The knob's text: exactly one character "0" to "3"; anything else is Off.
inline std::uint32_t Parse(const char* text) {
    return text && text[0] >= '0' && text[0] <= '3' && text[1] == '\0'
               ? std::uint32_t(text[0] - '0')
               : Off;
}

/// BB_LAMP_FOG_SHAFTS, read once.
inline std::uint32_t Level() {
    static const std::uint32_t level = Parse(std::getenv("BB_LAMP_FOG_SHAFTS"));
    return level;
}

inline const char* Name(std::uint32_t level) {
    switch (level) {
    case Medium:
        return "on";
    case High:
        return "on (high)";
    case View:
        return "on (debug view)";
    default:
        return "off";
    }
}

/// A map's side in texels; 0 when off.
inline constexpr std::uint32_t MapSize(std::uint32_t level) {
    return level == High ? 256u : (level == Medium || level == View) ? 128u : 0u;
}

/// Segments a half chord of the march's SHAFTS builds for the level, pushed to them
/// (point_volumetric.comp shaft_segments); 6 is the count of the build without SHAFTS.
inline constexpr std::uint32_t Segments(std::uint32_t level) {
    return level == High ? 12u : 6u;
}

/// Map layers: one per light record the lamp fog takes (vk_volumetric_light.cpp FogMaxLights,
/// tied there by a static_assert).
inline constexpr std::uint32_t MaxMaps = 64;

/// The instance mask the map rays trace: 4, what the ray traced lamp shadows trace
/// (vk_rt_shadow.cpp LampMask, point_shadow_ray.comp's 0x04): everything but cut-out cards.
inline constexpr std::uint32_t SceneMask = 4;

/// The blind sphere at the light's centre, m (point_shadow_ray.comp LAMP_CLEARANCE): what lies
/// closer to the flame than this (a torch's stick, the lantern's cage, the hand) casts nothing.
inline constexpr float Clearance = 0.35f;

/// lamp_fog_shaft_map.comp's ray start: Clearance, at most half the light's radius.
inline float Blind(float radius) {
    return std::min(Clearance, 0.5f * radius);
}

/// A texel lets the light through to a point whose distance from the centre over the radius is
/// at most its free distance over the radius plus this (pushed: point_volumetric.comp shaft_bias).
inline constexpr float Bias = 0.01f;

/// Bytes of the map image (R16F, MaxMaps layers) for the level.
inline constexpr std::uint64_t MapBytes(std::uint32_t level) {
    return std::uint64_t(MapSize(level)) * MapSize(level) * 2u * MaxMaps;
}

/// Map rays in a frame with `lights` records if every record were mapped every frame (r80 without
/// r106's cap; r80's 600-frame line prints it beside the cap's rays).
inline constexpr std::uint64_t MapRays(std::uint32_t level, std::uint32_t lights) {
    return std::uint64_t(MapSize(level)) * MapSize(level) * std::min(lights, MaxMaps);
}

/// The octahedral map (point_volumetric.comp OctEncode, lamp_fog_shaft_map.comp OctDecode): a
/// direction to a point of [-1, 1]^2 (+z at the centre, -z at the four corners) and back.
inline std::array<float, 2> OctEncode(std::array<float, 3> n) {
    const float sum = std::abs(n[0]) + std::abs(n[1]) + std::abs(n[2]);
    const float x = n[0] / sum, y = n[1] / sum, z = n[2] / sum;
    if (z < 0.0f) {
        return {(1.0f - std::abs(y)) * (x >= 0.0f ? 1.0f : -1.0f),
                (1.0f - std::abs(x)) * (y >= 0.0f ? 1.0f : -1.0f)};
    }
    return {x, y};
}

inline std::array<float, 3> OctDecode(std::array<float, 2> e) {
    float x = e[0], y = e[1];
    const float z = 1.0f - std::abs(x) - std::abs(y);
    if (z < 0.0f) {
        const float ox = x, oy = y;
        x = (1.0f - std::abs(oy)) * (ox >= 0.0f ? 1.0f : -1.0f);
        y = (1.0f - std::abs(ox)) * (oy >= 0.0f ? 1.0f : -1.0f);
    }
    const float length = std::sqrt(x * x + y * y + z * z);
    return {x / length, y / length, z / length};
}

/// Where a segment's sample of the map lies along the view ray (m): the march integrates the
/// inverse-square core per segment exactly as the difference of atan((t - along) / q) between the
/// segment's ends (`previous`, `angle`); the point where half of that lies on either side.
inline float EnergyMiddle(float along, float q, float previous, float angle) {
    return along + q * std::tan(0.5f * (previous + angle));
}

/// The share of the four gathered texels (free distance over the radius) that let the light
/// reach a point at `distance_ratio` (its distance from the centre over the radius).
inline float Lit(const std::array<float, 4>& free_ratio, float distance_ratio) {
    float lit = 0.0f;
    for (const float f : free_ratio) {
        lit += f >= distance_ratio - Bias ? 0.25f : 0.0f;
    }
    return lit;
}

} // namespace Vulkan::LampFogShafts
