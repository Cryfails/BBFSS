// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r122_game-wind-drive, FEATURE): one wind for everything. The owner's rule (2026-11-16 08:12):
// "we should cut the vanilla foliage movement and particle direction to make it match our wind not the
// other way around". BB_WIND_GAME=1 (read once; any other value is off; it needs BB_WIND=1 and the plant
// sway, BB_WIND_SWAY above 0, which is its default) cuts the game's own foliage waves.
//
// What the game does (read from the vertex shaders the engine saved in user/cache, spirv-dis, nothing
// run): the big tree vertex shaders (vs 6a833138, 9da6aacb, c829ee58, 7620368b, 803b9d24) are plain
// skinning with no time, no sine and no wind in them, so whatever moves such a tree is in its bone
// palette, which the game writes (not cut here). The skinned cut-out vertex shaders of the plants and
// leaves (vs 3eaa5555, 15382148, a666c443, bc03d90c, f68743cf: 16 sines each) are a bank of 16 wave
// emitters: per emitter a falloff 1 - distance / radius, a phase (k r + a time word of the draw's
// constants) / 360 turns, w = 0.5 sin(2 pi phase) + 0.5, the smoother step w^3 (6 w^2 - 15 w + 10), and a
// displacement along the emitter's direction of min + (max - min) times that. That is the vanilla
// foliage motion of the graveyard (a travelling wave that is not our wind's).
//
// The cut: a vertex shader of a motion pipeline with the plant sway bit (MotionVectors::Sway) is built
// with MotionVectors::GameCut (16, in the pipeline key and the stage's runtime info, so the cut and the
// uncut shader are different cache entries; no binary version offset is needed) and then every v_sin_f32
// of the game's code (Lifter V_SIN_F32, recompiler EmitFPSin) gives CutLevel (-1: the wave at its trough,
// w = 0, so the emitter adds only its base `min`, a constant: the displacement stops moving; whether that
// constant is 0 in the game's data is NOT known, a non-zero one is a fixed lean). Our own sway code (VertexSway, EmitVertexSway) uses its own sine
// emitters and is not touched. Where the pipeline has no sine, nothing changes. The cut is per pipeline
// (every draw of a plant pipeline loses the game's waves, also a draw our sway does not move), and it
// applies to the camera pass pipelines only (the game's sun shadow maps still draw the vanilla wave;
// with ray tracing the ray traced shadows use the camera pass's positions, as the sway itself does).
//
// The game's own particles are NOT changed here: their vertex shader (vs 4cd21a0f, ps 71c96598, additive
// points, 1-21 a draw) is a pass-through of a 28-float record per point, so their positions are made by
// the game's CPU every frame; the engine has no shader term to cut (see the context file).
//
// Off (BB_WIND_GAME unset, the default): CutOn() is false, the key bit and the info bit are never set,
// no shader differs, the pipeline hash and the cache are as before; the draw hook tests a mask of the
// key that is 0. Pure: no Vulkan; tests/test_wind_game.cpp.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "bbport_wind_sway.h"

namespace BbWindGame {

/// What a cut v_sin_f32 gives: -1 puts the emitter's wave at its trough (0.5 sin + 0.5 = 0, the smoother
/// step 0), where the displacement is the emitter's base only.
inline constexpr float CutLevel = -1.0f;
/// The bit of Shader::MotionVectors::GameCut (runtime_info.h); the patch's text check ties the two.
inline constexpr std::uint32_t GameCutBit = 16;

/// BB_WIND_GAME: exactly "1" is on, anything else (unset, empty, "0", "11") is off.
[[nodiscard]] inline bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

/// Read once, at the first use (the pipeline cache's first key). On needs the plant sway too: nothing
/// else would move the foliage the cut holds still.
[[nodiscard]] inline bool CutOn() {
    static const bool on = BbWindSway::KnobOnce().on && ParseOn(std::getenv("BB_WIND_GAME"));
    return on;
}

/// The pipeline selection says plant sway and the cut is on.
[[nodiscard]] inline bool CutWanted(bool sway_wanted) {
    return sway_wanted && CutOn();
}

struct Counters {
    std::atomic<std::uint64_t> sines{0}; ///< v_sin_f32 instructions replaced (per shader built)
    std::atomic<std::uint64_t> draws{0}; ///< draws of pipelines that have the GameCut bit
};

[[nodiscard]] inline Counters& Count() {
    static Counters counters;
    return counters;
}

/// The once-line, printed by the first caller that has the cut on (the pipeline key).
inline void Announce() {
    static const bool told = [] {
        std::printf("Wind game (r122, BB_WIND_GAME=1): the game's own plant waves are cut so that only our "
                    "wind moves foliage: in the vertex shaders of the plant sway pipelines (MotionVectors::"
                    "GameCut) every v_sin_f32 of the game's code gives %.0f (the wave at its trough); our sway "
                    "is not touched; the game's particles and bone-palette trees are not changed; a Wind game "
                    "line every 600 wind steps counts the sines cut and the draws\n",
                    double(CutLevel));
        return true;
    }();
    (void)told;
}

/// The periodic line (totals since the start).
inline int ReportText(char* out, std::size_t size) {
    const Counters& c = Count();
    return std::snprintf(out, size,
                         "Wind game (r122): %llu sines of the game's vertex shaders cut (per shader built), "
                         "%llu draws on pipelines with the cut, since the start",
                         static_cast<unsigned long long>(c.sines.load(std::memory_order_relaxed)),
                         static_cast<unsigned long long>(c.draws.load(std::memory_order_relaxed)));
}

static_assert(GameCutBit == 16 && (GameCutBit & 3u) == 0, "Kind() looks at bits 0 and 1 only");
static_assert(CutLevel >= -1.0f && CutLevel <= 1.0f, "a sine's range");

} // namespace BbWindGame
