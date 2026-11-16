// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstdint>

/// bbport (r14): the game leaves some sun shadow cascades undrawn on some frames (the engine's
/// hook on the game's cascade loop, shim/engine/graphics.cpp, BB_SUN_CASCADES). Written by the
/// game's render thread, read by the renderer's threads.
namespace BbSunCascades {
/// 0: the game draws every cascade it has every frame (nothing for the renderer to keep).
/// N > 1: a cascade may go undrawn for up to N - 1 frames in a row and is then drawn again; the
/// renderer keeps its atlas quadrant and its ray tracing world copies for that long.
inline std::atomic<std::uint32_t> skip_period{0};
/// Experiment bit: set = old behaviour (four cascades every frame, whole-atlas clear).
constexpr std::uint64_t kOffBit = 1099511627776ull;
}
