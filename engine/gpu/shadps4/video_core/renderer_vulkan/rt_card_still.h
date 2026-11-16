// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r62e_leaf-cards-usable): cut-out shadows (true shape) made safe to turn on
// (BB_RT_CARD_ALPHA, BB_RT_CARD_LAMPS; BB_RT_CARD_SAFE=0 turns this off). No Vulkan here:
// tests/test_rt_lamp_cards.cpp builds this header alone and runs the code the engine runs.
//
// A cut-out is any draw whose pixel shader discards by a texture's alpha (rt_lamp_cards.h: a sun
// shadow pass draw that samples a texture, a camera pass draw that discards, or one of its mesh):
// leaves and weeds, but just as well a wall lantern's hook, a grille, a railing or a chain drawn as a
// textured card. Nothing here asks what it is, only whether it is still:
// - no skeleton and not moving (Entry::dynamic: a palette, a promoted instance, the still check):
//   still, whatever it shows;
// - a skeleton: still only when r46b's sign takes it for the thing's own motion (its position stream
//   is LampLoneState::Lone: no sun shadow pass draws it while the sun shadow pass draws skeletons, the
//   game gives it no shadow of its own: a bed of plants). r89's wind sway only moves such lone streams
//   (Rasterizer::WindSwayWord asks RtShadow::LonePlant), so a swaying plant stays still here;
// - anything else (a character's hair or coat, a moving rigid prop): not still. It stores no card
//   UVs and gets no lamp card bit (its capture pipeline stays the CaptureUv variant: the pipeline is
//   chosen from the draw state before the entry is known). Of those entries the 15:25 game test
//   found the bad BLAS inputs (vs c77a0097, skinned, the player's coat or hair) and the mask flips
//   (moving rigid cut-outs, whose old pose and stale state alternate).

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "../host_shaders/rt_card_guard_layout.h"

namespace Vulkan {

/// Why an entry of the cut-out sets is or is not still.
enum class CardStillWhy : std::uint8_t { Still, Skinned, Moving };

/// `skinned`: a draw of it had a skeleton; `lone`: its vertices are LampLoneState::Lone;
/// `dynamic`: it counts as moving (a skinned entry always does).
[[nodiscard]] constexpr CardStillWhy CardStillOf(bool skinned, bool lone, bool dynamic) noexcept {
    if (skinned) {
        return lone ? CardStillWhy::Still : CardStillWhy::Skinned;
    }
    return dynamic ? CardStillWhy::Moving : CardStillWhy::Still;
}

/// A still cut-out's copy in an old pose (r41's stale: a shared copy between its rebuild turns)
/// never carries the lamp card bit: its displaced pose would cast a second shadow beside the live
/// copy's (the fault r41 repaired). Once stale it stays without the bit until more than `hold`
/// frames passed since its last stale record, so that the bit does not come and go with every turn
/// (each change makes the TLAS a full build). `last_stale`: the frame + 1 of its last stale record
/// (0: never), kept by the caller. True: the bit may be on.
[[nodiscard]] constexpr bool CardStaleHoldOff(bool stale, std::uint64_t frame,
                                              std::uint64_t& last_stale, std::uint64_t hold) noexcept {
    if (stale) {
        last_stale = frame + 1;
        return false;
    }
    return last_stale == 0 || frame + 1 - last_stale > hold;
}

/// The lamp card bit of an entry's record changed: true for a flip (it had changed before), false
/// for the first turn-on of the entry (`once` then becomes true).
constexpr bool CardMaskTurn(bool& once) noexcept {
    const bool flip = once;
    once = true;
    return flip;
}

inline constexpr float CardGuardEdge = float(CARD_GUARD_EDGE_M);
inline constexpr std::uint32_t CardGuardSlots = CARD_GUARD_SLOTS;
inline constexpr std::uint32_t CardGuardWords = CARD_GUARD_WORDS;
static_assert(CARD_GUARD_W_FIRST_RECORD + 2 * CARD_GUARD_RECORDS <= CARD_GUARD_W_LONGEST &&
              CARD_GUARD_W_LONGEST < CARD_GUARD_W_FLAGS && CARD_GUARD_DETECT != CARD_GUARD_COLLAPSE);

/// rt_card_guard.comp's DETECT test of one triangle on the CPU (4 floats a vertex, `w` not read):
/// a corner past `vertex_count`, a corner that is not a finite number, or an edge that is not at most
/// `edge` metres (an edge that overflows to infinity is not).
[[nodiscard]] inline bool CardGuardBad(const float* positions, std::uint32_t vertex_count,
                                       std::uint32_t a, std::uint32_t b, std::uint32_t c,
                                       float edge) noexcept {
    if (a >= vertex_count || b >= vertex_count || c >= vertex_count) {
        return true;
    }
    const float* const p[3] = {positions + 4 * std::size_t(a), positions + 4 * std::size_t(b),
                               positions + 4 * std::size_t(c)};
    for (const float* v : p) {
        if (!std::isfinite(v[0]) || !std::isfinite(v[1]) || !std::isfinite(v[2])) {
            return true;
        }
    }
    const auto length = [](const float* u, const float* v) {
        const float x = u[0] - v[0], y = u[1] - v[1], z = u[2] - v[2];
        return std::sqrt(x * x + y * y + z * z);
    };
    const float longest = std::max(length(p[0], p[1]), std::max(length(p[1], p[2]), length(p[2], p[0])));
    return !(longest <= edge);
}

} // namespace Vulkan
