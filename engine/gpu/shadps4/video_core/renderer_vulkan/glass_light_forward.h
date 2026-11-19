// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r130g_glass-light-forward): the pure parts of the forward glass light: the numbers the lamp shader shares
// (host_shaders/glass_light_forward_layout.h) and the "steady" rule that lets a registered pane drawn with a palette the GPU wrote
// into the scene (RtShadow::GlassPlacedSteady). No Vulkan here: tests/test_glass_light_forward.cpp builds this header alone.

#include <cstdint>
#include <iterator>
#include <unordered_map>

#include "../host_shaders/glass_light_forward_layout.h"

namespace Vulkan::GlassLight {

using u32 = std::uint32_t;
using u64 = std::uint64_t;

inline constexpr float LampClear = float(GLASS_LAMP_CLEAR);
inline constexpr u32 RayFirst = GLASS_RAY_FIRST, RaySlots = GLASS_RAY_SLOTS;
/// The frames in a row a placed pane instance must be drawn, and the most the scene takes in a frame.
inline constexpr u32 SteadyFrames = 3, PlacedPerFrame = 16;
/// The judge's table: at this many keys the ones not drawn for SteadyKeep frames go, then all if it is still full.
inline constexpr u32 SteadyKeysMost = 256, SteadyKeep = 6;

// half_counts holds 16 words before the glass counter; the counter follows them.
static_assert(RayFirst >= 16 && RayFirst + RaySlots == 25 && RaySlots == 9 && LampClear > 0.0f && LampClear < 0.1f);

struct Steady {
    u64 frame = 0; // the last frame the instance was drawn
    u32 run = 0;   // the frames in a row up to it
};
using SteadyMap = std::unordered_map<u64, Steady>;

/// A placed pane instance `instance` is drawn on `frame` (any number of times in it): true once it was drawn on SteadyFrames
/// frames in a row (a gap of one frame starts the count again). The held torch's palette sits at two addresses in turn, so each
/// of its instances is drawn every other frame and never gets there.
inline bool JudgeSteady(SteadyMap& map, u64 instance, u64 frame) {
    if (map.size() >= SteadyKeysMost && !map.contains(instance)) {
        for (auto it = map.begin(); it != map.end();) {
            it = it->second.frame + SteadyKeep < frame ? map.erase(it) : std::next(it);
        }
        if (map.size() >= SteadyKeysMost) {
            map.clear();
        }
    }
    Steady& s = map[instance];
    if (s.run == 0) {
        s = {frame, 1};
    } else if (s.frame != frame) {
        s.run = s.frame + 1 == frame ? (s.run < 1000u ? s.run + 1u : s.run) : 1u;
        s.frame = frame;
    }
    return s.run >= SteadyFrames;
}

} // namespace Vulkan::GlassLight
