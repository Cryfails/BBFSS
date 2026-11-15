// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r47_still-check): whether a caster of the ray tracing scene that is held for still
// has moved (RtShadow, vk_rt_shadow.cpp). No Vulkan here: tests/test_rt_still_check.cpp builds
// this header alone and runs the code the engine runs.
//
// A caster counts as moving only by two signs of its draw: a skeleton (a stride-16 buffer of 640
// bytes or more) or a small bone palette whose bytes changed. Every other caster is built once,
// in the pose of the frame it was first drawn, and never captured again while it is drawn: a
// prop moved by a one-bone palette, by its model matrix, or by a palette the game writes on the
// GPU (its bytes on the CPU never change) keeps the place of its first build in the scene and
// casts a lamp shadow that stays behind (a torch-shaped line on the ground while the torch is
// carried on).
//
// Now such a caster is looked at again in turn. Its draw is captured once more (a probe: nothing
// is built from it), the bounds of the vertices its triangles use are measured on the GPU in
// world space (host_shaders/rt_still_sig.comp, the signature), and they are compared with the
// bounds of the capture its bottom-level structure was built from. Past the tolerance on two
// looks in a row it counts as moving from then on, as a skinned caster does: refit at every
// draw. The first three looks come 2, 8 and 32 frames after the build (a caster first drawn in a
// passing pose is found on the first, and taken on the look that follows it at once), the later
// ones about once a second, four times more rarely for a caster the camera pass does not draw,
// and all of them more rarely while a frame draws more of them than the budget lets through at
// that pace (StillCrowd).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace Vulkan {

/// Signatures a frame, and the words of one (as rt_still_sig.comp writes them): 0-2 the
/// greatest inverted key of x, y, z (the least value), 3-5 the greatest key (the greatest
/// value), 6 the vertices taken, 7 those left out because a coordinate was not a finite number.
inline constexpr std::uint32_t StillSigsPerFrame = 2048;
inline constexpr std::uint32_t StillSigWords = 8;
/// The most indices of a mesh one dispatch of rt_still_sig.comp measures: every device runs
/// 65,535 work groups of its 64 threads, none need run more. A larger mesh is not looked at.
inline constexpr std::uint32_t StillSigIndicesMost = 65535u * 64u;
/// The looks of an entry that come early (StillNext), served from a budget of their own.
inline constexpr std::uint32_t StillEarlyChecks = 3;
/// BB_RT_STILL_BUDGET and BB_RT_STILL_EARLY: triangles a frame looked at again in turn, and for
/// the early looks; their most.
inline constexpr std::uint32_t StillBudget = 60000;
inline constexpr std::uint32_t StillEarly = 100000;
inline constexpr std::uint32_t StillBudgetMost = 4000000;
/// BB_RT_STILL_MOVERS: the most triangles of casters counted as moving by a look; its most.
inline constexpr std::uint32_t StillMovers = 400000;
inline constexpr std::uint32_t StillMoversMost = 16000000;
/// BB_RT_STILL_TOLERANCE, metres: a caster whose bounds differ by more has moved.
inline constexpr float StillTolerance = 0.004f;
inline constexpr float StillToleranceLeast = 0.0005f;
inline constexpr float StillToleranceMost = 0.1f;
/// The tolerance where the two captures come from different passes (the camera pass's draw
/// against a sun shadow pass's, whose vertex shader may place the mesh with a bias).
inline constexpr float StillCrossTolerance = 0.25f;
/// A caster counts as near while the camera pass drew it within this many frames.
inline constexpr std::uint32_t StillNearFrames = 8;
/// BB_RT_LAMP_LEAVE's most (seven classes, StillLeaveClasses).
inline constexpr std::uint32_t StillLeaveMost = 127;
/// The most frames StillCrowd gives (about a quarter of an hour).
inline constexpr std::uint32_t StillCrowdMost = 65536;

/// World bounds: least x, y, z, greatest x, y, z.
using StillBox = std::array<float, 6>;

/// A float as an unsigned number of the same order (-0 just below +0): what the shader's
/// atomicMax compares.
constexpr std::uint32_t StillKey(float value) {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(value);
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}
constexpr float StillUnkey(std::uint32_t key) {
    return std::bit_cast<float>((key & 0x80000000u) != 0 ? key & 0x7fffffffu : ~key);
}

/// One vertex into a signature, as rt_still_sig.comp does it (the tests compare the two).
constexpr void StillSigAdd(std::uint32_t* words, float x, float y, float z) {
    const std::array<float, 3> p{x, y, z};
    for (const float v : p) {
        if ((std::bit_cast<std::uint32_t>(v) & 0x7f800000u) == 0x7f800000u) {
            ++words[7];
            return;
        }
    }
    for (std::uint32_t k = 0; k < 3; ++k) {
        words[k] = std::max(words[k], ~StillKey(p[k]));
        words[3 + k] = std::max(words[3 + k], StillKey(p[k]));
    }
    ++words[6];
}

/// The bounds a signature holds. False when it holds none that can be compared: no vertex was
/// taken (the slot was never written), or one was left out (a caster with such a vertex would
/// seem to move whenever that vertex comes and goes).
constexpr bool DecodeStillSig(const std::uint32_t* words, StillBox& box) {
    if (words[6] == 0 || words[7] != 0) {
        return false;
    }
    for (std::uint32_t k = 0; k < 3; ++k) {
        box[k] = StillUnkey(~words[k]);
        box[3 + k] = StillUnkey(words[3 + k]);
    }
    return true;
}

/// For a capture's signature: what takes its clip space positions to world space, in two
/// parts. `inverse`: the inverse of the capture's projection (4x4 rows); `view_to_world`: its
/// view to world rows (3x4). `rows` (3x4) give the place of a clip space position relative to
/// the capture's camera, `origin` is the camera's place: world = rows * clip + origin.
/// Not the one 3x4 product the scene's positions are made with (RtShadow::ToWorld): the inverse
/// of a perspective projection rebuilds the 1 of a view space position from clip z and w, and
/// the product multiplies the camera's place by it: two terms of the size of (the camera's
/// distance from the world's origin) x depth / near plane that cancel. What their rounding
/// leaves (millimetres at 30 m, centimetres at 100 m) changes with every pose of the camera, so
/// a wall far away would read as moved whenever the camera did. The view space x, y and z come
/// from clip x, y and w without such terms, and the 1 is known.
constexpr void StillClipToWorld(const float* inverse, const float* view_to_world,
                                std::array<float, 12>& rows, std::array<float, 3>& origin) {
    for (std::uint32_t r = 0; r < 3; ++r) {
        for (std::uint32_t c = 0; c < 4; ++c) {
            double sum = 0.0;
            for (std::uint32_t k = 0; k < 3; ++k) {
                sum += double(view_to_world[r * 4 + k]) * double(inverse[k * 4 + c]);
            }
            rows[r * 4 + c] = float(sum);
        }
        origin[r] = view_to_world[r * 4 + 3];
    }
}
/// A clip space position's place in the world, as rt_still_sig.comp works it out.
constexpr std::array<float, 3> StillPoint(const std::array<float, 12>& rows,
                                          const std::array<float, 3>& origin, const float* clip) {
    std::array<float, 3> p{};
    for (std::uint32_t r = 0; r < 3; ++r) {
        p[r] = rows[r * 4] * clip[0] + rows[r * 4 + 1] * clip[1] + rows[r * 4 + 2] * clip[2] +
               rows[r * 4 + 3] * clip[3] + origin[r];
    }
    return p;
}

/// How far a caster moved between two captures: the greatest difference of the six bounds.
constexpr float StillMoved(const StillBox& a, const StillBox& b) {
    float most = 0.0f;
    for (std::uint32_t k = 0; k < 6; ++k) {
        const float d = a[k] > b[k] ? a[k] - b[k] : b[k] - a[k];
        most = d > most ? d : most;
    }
    return most;
}

/// bbport (r47c_review-fixes): a prop known by its palette's address that a look finds more than
/// this many metres from where its BLAS was built, with a box of the same size (StillSameSize),
/// was carried whole, or its palette's address was given to another prop of the mesh. Counted
/// for the log only.
inline constexpr float StillCarried = 0.5f;
/// Whether two boxes have the same size along every axis, within `limit` metres.
constexpr bool StillSameSize(const StillBox& a, const StillBox& b, float limit) {
    for (std::uint32_t k = 0; k < 3; ++k) {
        const float d = (a[3 + k] - a[k]) - (b[3 + k] - b[k]);
        if (d > limit || -d > limit) {
            return false;
        }
    }
    return true;
}

/// bbport (r47c_review-fixes): the budgets are spent in draw order, so a caster drawn late in
/// the frame finds the budget of the looks in turn used up by those drawn before it. One that
/// every frame draws gets its look on the next frame with room. One that only every 8th frame
/// draws (a far sun cascade's, graphics_sun_far_shadows) meets the same crowd every time: in
/// the game such looks waited without end (403, 1003, 1603 frames on three log lines in a row)
/// while the budget was not used up on average. A look in turn that has waited this many
/// frames is served from a second budget of the same size (lane 3, StillLaneOf).
/// BB_RT_STILL_OVERDUE; 0: no second budget.
inline constexpr std::uint32_t StillOverdue = 64;
inline constexpr std::uint32_t StillOverdueMost = 65536;
/// The lane a due look is served from: 0 the first look after a build, 1 the other early
/// looks, 2 the looks in turn, 3 a look in turn that has waited `overdue` frames or more
/// (`waited`) while the budget of lane 2 is used up on this frame (`turn_used_up`).
constexpr std::uint32_t StillLaneOf(std::uint32_t checks, bool turn_used_up, std::uint64_t waited,
                                    std::uint32_t overdue) {
    if (checks < StillEarlyChecks) {
        return checks == 0 ? 0u : 1u;
    }
    return turn_used_up && overdue != 0 && waited >= overdue ? 3u : 2u;
}

/// The frames a set of casters needs at the budget for one look of each: `due` triangles of
/// them against `budget` triangles a frame. 0 while the budget lets them all through on one
/// frame (and with no budget at all: no looks in turn).
/// bbport (r47c_review-fixes): RtShadow asks with ALL the casters looked at in turn, due or not
/// (StillPoolShare of each, the most a frame drew: StillPoolPeak). Asked with those due on one
/// frame only, as at first, it gave the few frames the waiting ones needed, far below the
/// period of 64 to 95 frames, and put nothing off: with more casters than the budget serves at
/// that period the first in draw order take it again at every period and the last wait for good
/// (the test runs both).
constexpr std::uint32_t StillCrowd(std::uint64_t due, std::uint32_t budget) {
    if (budget == 0 || due <= budget) {
        return 0;
    }
    return std::uint32_t(std::min<std::uint64_t>((due + budget - 1) / budget, StillCrowdMost));
}

/// bbport (r47c_review-fixes): what a caster looked at in turn counts for in the pool that sets
/// the pace: its triangles, a quarter of them when it is not `nearby` (StillNext looks at it
/// four times more rarely).
constexpr std::uint64_t StillPoolShare(std::uint32_t triangles, bool nearby) {
    return nearby ? triangles : (triangles + 3u) / 4u;
}
/// The pool is what a frame draws, and a far sun cascade's casters are drawn on every 8th frame
/// only: the pace is set by the most a frame drew over the last StillPoolFrames to twice as
/// many frames. End: at the end of `frame`, with what it drew; returns that most.
inline constexpr std::uint32_t StillPoolFrames = 32;
struct StillPoolPeak {
    std::uint64_t now = 0, before = 0;
    constexpr std::uint64_t End(std::uint64_t pool, std::uint64_t frame) {
        now = std::max(now, pool);
        if (frame % StillPoolFrames == 0) {
            before = now;
            now = 0;
        }
        return std::max(now, before);
    }
};

/// Frames from a look to the next one: `checks` looks were taken since the build, this one
/// counted (0: from the build to the first look). `key` spreads the later looks of the casters
/// over the frames; `nearby`: the camera pass draws it, or it has a bone palette (a prop).
/// `crowd` (StillCrowd of all the casters looked at in turn): a look in turn does not come
/// again before each of them could have had its own. Without it the casters drawn first would
/// take the budget again at every period and those drawn last would never be looked at; with
/// it all are, at the pace the budget allows.
constexpr std::uint32_t StillNext(std::uint32_t checks, std::uint64_t key, bool nearby,
                                  std::uint32_t crowd = 0) {
    constexpr std::array<std::uint32_t, StillEarlyChecks> early{2, 6, 24};
    if (checks < StillEarlyChecks) {
        return early[checks];
    }
    const std::uint32_t spread = std::uint32_t(key % 32);
    // bbport (r47c_review-fixes): four times more rarely also where the crowd sets the pace
    // (StillPoolShare counts such a caster for a quarter). Before: max of the two, so that under
    // a crowd a caster the camera pass does not draw came as often as one it does.
    return (std::max(64u, crowd) + spread) * (nearby ? 1u : 4u);
}

/// BB_RT_STILL: 2 on (the default, and for a text that is not understood), 1 count (the looks
/// and the log, nothing is counted as moving: the picture of before with the proof in the log),
/// 0 off.
enum : std::uint32_t { StillOff = 0, StillCount = 1, StillOn = 2 };
inline std::uint32_t ReadStillMode(const char* text) {
    if (!text) {
        return StillOn;
    }
    return std::strcmp(text, "off") == 0     ? StillOff
           : std::strcmp(text, "count") == 0 ? StillCount
                                             : StillOn;
}

/// BB_RT_STILL_TOLERANCE in metres, kept within its bounds; no text or not a number: the default.
inline float ReadStillTolerance(const char* text) {
    if (!text) {
        return StillTolerance;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return StillTolerance;
    }
    return std::clamp(value, StillToleranceLeast, StillToleranceMost);
}

/// BB_RT_LAMP_LEAVE's classes of an instance of the scene (a diagnostic: lamp rays leave out
/// the instances of the classes the knob names, to tell which kind of caster throws a shadow):
/// 1 the camera pass does not draw it on this frame, 2 held for a sun cascade that is not drawn,
/// 4 a shared copy, 8 an instance's own entry (a prop known by its bone palette), 16 held for
/// still and known by its draw order, 32 moving and not a shared copy, 64 a cut-out card by
/// r46's default rule.
constexpr std::uint32_t StillLeaveClasses(bool camera, bool held, bool shared, bool instance,
                                          bool moving, bool card) {
    return (camera ? 0u : 1u) | (held ? 2u : 0u) | (shared ? 4u : 0u) | (instance ? 8u : 0u) |
           (!moving && !shared && !instance ? 16u : 0u) | (moving && !shared ? 32u : 0u) |
           (card ? 64u : 0u);
}

} // namespace Vulkan
