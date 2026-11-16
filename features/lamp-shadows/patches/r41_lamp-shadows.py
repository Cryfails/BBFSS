# r41_lamp-shadows: repair of the ray traced lamp shadows (point_shadow_ray.comp,
# vk_point_shadow.cpp, vk_rt_shadow.cpp). check|apply|revert (revert restores byte for byte; the
# two new files are made by apply and removed by revert). On top of r1..r40 (r32_lamp-half and
# r40_master-bits applied). The tree is <tree>/ unless the environment variable R41_ROOT
# names another root (a copy). Nothing is changed in place: every new text is written beside its
# target and moved over it, and a failure puts back what was already moved.
#
# The fault (ray tracing on, graphics_rt_point_shadows=1, camera above a character who holds a
# hand torch): the torch throws thin hard bands of shadow with lit gaps between them, the body
# shadow is faint, shadows end abruptly near the flame, cape and hair show blocky patches. The
# lamp ray pass never ran before the tile count reached it, so all of this is new on screen.
#
# What the code did (read in the source, not measured on screen):
#  - one hard ray to a point lamp: a torch stick, a weapon handle or a torch head, a few
#    centimetres wide but close to the flame, throws a long magnified band;
#  - copies of a moving mesh drawn more than once in a pass ("shared copies", vk_rt_shadow.cpp
#    PrepareDraw) are rebuilt within 300,000 triangles a frame, in draw order. With more than
#    that (35 copies, 779,210 triangles in the test run, 17 rebuilt a frame) the same copies go
#    without every frame, keep an old pose and stay in the scene: a second, displaced caster;
#  - all lamps of a pixel share one shadow ratio, weighted (1 - d^2/r^2)^2 * luma with no facing
#    term, while the game's own curve is (1 - d/r)^2 (vk_local_falloff.h): a lamp far away or
#    behind the surface is overrated, so its shadow removes the torch's light and the torch's
#    own shadow removes too little;
#  - the ray starts 3 cm off the surface along a normal worked out from depth: layered cloth and
#    hair cards shadow themselves as whole polygons.
#
# What changes (all on by default; experiment bit 45, value 35184372088832, set = the picture
# and the masks as before, read at every pass and every scene build, so one run compares both):
#  a. Weights follow the game: (1 - d/r)^2, or the inverse-square curve of
#     startup_local_inverse_square, times a wrapped N.L from the depth normal that never falls
#     below a floor (0.05). The facing ranks the lamps; it does not remove one: a pixel whose
#     only lamp had no weight would get no ray and keep that lamp's light unshadowed, and the
#     depth normal is arbitrary on features a pixel or two wide (hair, cape fringe).
#  b. The lamp is a disc of radius 0.05 m: where the ray to its centre is blocked by something
#     near the lamp and the lamp holds at least 25% of the pixel's weight, up to 3 rays go to
#     its rim; one free rim ray means lit. The answer stays 0 or 1 per lamp: no noise, no
#     history, nothing to filter. With q = caster distance / receiver distance from the lamp:
#     a caster thinner than about 2 * radius * (1 - q) casts nothing (a 3 cm stick next to the
#     flame); a wide caster keeps its shadow with each edge moved in by up to
#     radius * (1 - q) / q on the receiver. That is not "a few centimetres" for a body next to
#     a torch: 0.45 m from the lamp with the ground 2 m away, up to 17 cm a side at radius 0.05
#     (34 cm at 0.10, which is why the default is 0.05); 1 cm for a caster 5 m from a lamp with
#     the ground at 6 m. For the strongest lamp and for the picked one.
#  c. "Near the lamp" (BB_LAMP_SHADOW_NEAR, 0.5): the radius is whole up to q = 0.25 and falls
#     to nothing at q = 0.5, q taken from the centre ray's hit. A caster further from the lamp
#     than halfway to the receiver keeps the point lamp's shadow and costs no rim ray: railings,
#     legs and bodies metres from a lamp are not eroded, and the rim rays are spent only where a
#     point lamp magnifies a caster more than twice.
#  d. The rim points are laid out against two axes of the world (world +x and +y in view space,
#     from the pass's view matrix), not of the view: against the view's axes the pattern turned
#     with the camera, and eroded edges and casters at the threshold moved with it.
#  e. Grazing self skip: the ray's start is lifted along the normal by 0.06 m * (1 - N.L)^2
#     (not "hits count from further along the ray", which would pass a thin wall next to the
#     pixel).
#  f. A moving shared copy that was drawn and went without a rebuild more than 2 times in a row
#     is left out of lamp rays (instance mask bit 4) until it has been rebuilt on 3 draws in a
#     row; the sun's rays keep it as before. Counted in starved draws, not in the age of the
#     BLAS, and with a way back that needs several rebuilds: a copy the far cascades hold
#     undrawn (graphics_sun_far_shadows alternate/rare) or one at the edge of the budget does
#     not blink. With BB_RT_UNCHANGED set, a starved copy whose draw reads what its BLAS was
#     built from stays in (its pose is right).
#  g. Unchanged: one compute pass a frame, at most two lamps traced a pixel (the strongest and
#     one picked), the 0.35 m blind sphere at the lamp, one ratio for all lamps, history off,
#     the half-resolution path (graphics_lamp_shadow_half): the ratio is still one number made
#     of 0/1 answers, so its block answers and their 1/64 agreement test work as they did.
#
# How the shader gets its numbers: the push block is full, so sixteen words are appended to the
# pass's data buffer after the tile table (before the history words) and their place goes in
# bits 8-31 of the mode word, beside a new bit MODE_REPAIR (16). A caller that sets neither
# (tests/test_rt_shadows.cpp's existing runs, the experiment bit) gets the arithmetic of before.
#
# Knobs (environment, read once at start; defaults in brackets):
#   BB_LAMP_SHADOW_WEIGHTS [1] 0|1      1 = the game's falloff times N.L, 0 = the old weights
#   BB_LAMP_SHADOW_WRAP [0.15] 0..1     N.L tolerance; 1 = no N.L
#   BB_LAMP_SHADOW_FLOOR [0.05] 0..1    least facing factor; 0 = a lamp behind the surface gets
#                                       no weight and no ray (lit specks where it is the only one)
#   BB_LAMP_SHADOW_SOFT [0.05] 0..0.3   lamp radius in metres; 0 = a point lamp, no rim rays
#   BB_LAMP_SHADOW_RIM [3] 0..4         rim rays (2 lie on one line: a stick along it keeps its
#                                       band; 3 or 4 cover every direction)
#   BB_LAMP_SHADOW_SHARE [0.25] 0..1    least share of the pixel's weight for rim rays
#   BB_LAMP_SHADOW_NEAR [0.5] 0.05..1   rim rays only for casters within this share of the way
#                                       from the lamp to the receiver; 1 = everywhere
#   BB_LAMP_SHADOW_CLEARANCE [0.35] 0.05..2   blind sphere at the lamp, metres
#   BB_LAMP_SHADOW_BIAS [0.03] 0.005..0.2     ray start offset, metres
#   BB_LAMP_SHADOW_SELF [0.06] 0..0.3   grazing self skip, metres
#   BB_LAMP_SHADOW_VIEW [0] 0..3        debug view on traced pixels, written to the first light
#                                       target (the second gets 0): 1 the shadow ratio; 2 lamp
#                                       records with weight at the pixel (1 blue, 2 green, 3
#                                       yellow, 4+ red; a lamp listed by two overlapping tiles
#                                       counts twice, as its weight does) times 0.25 + 0.75 *
#                                       strongest share; 3 rays cast (0 blue, 1 green, 2 yellow,
#                                       3+ red)
#   BB_LAMP_SHADOW_VIEW_GAIN [0.5] 0.01..16   brightness of the view
# LANTERN_RT_LAMPS_EXACT, LANTERN_RT_LAMP_REUSE and BB_LAMP_SHADOW_HALF stay as they are.
#
# Log lines: once when the ray pipeline is made, "Ray traced lamps (r41): weights ..."; at the
# first ray pass and at each change of the experiment bit, "Ray traced lamps (r41): repair on|off
# ..."; the 600-frame "shared copies drawn on the last frame" line ends with "N left out of lamp
# rays (oldest M frames)".
#
# Files: host_shaders/point_shadow_ray.comp (both builds come from it), renderer_vulkan/
# vk_point_shadow.cpp/.h, vk_rt_shadow.cpp/.h, new renderer_vulkan/lamp_shadow_tune.h (knobs,
# words, the world's axes and a mirror of the weight, no Vulkan), shim/bbport_settings.h
# (comment: 45 is not a "previous path" bit, set brings faults back, like 14), gpu/
# CMakeLists.txt, tests/test_settings.cpp, tests/test_rt_shadows.cpp (the GPU lab,
# rt-shadow-test --speed), new tests/test_lamp_shadow_tune.cpp (lamp-shadow-tune-test).
#
# The GPU lab: its instances carry masks 1 to 3 and a lamp ray asks for 4, so no lamp ray of its
# existing runs hits anything (those runs and their numbers are left as they are). The new block
# gives the instances the lamp bit for its own runs, adds "torch" lamps 0.45 m from a
# character's side (the street lamps stand metres from what they shadow) and checks, for both:
# the old weights, a point lamp and no self skip under MODE_REPAIR give the very numbers of mode
# 0 with every lamp traced (with picked lamps two runs of mode 0 already differ on a few pixels,
# so there the difference is bounded by four times that plus 64 pixels); a lamp with a radius
# leaves no pixel darker than a point lamp; a body beside a torch keeps at least half of its
# dark pixels; the inverse-square weights give a ratio. It prints the cost of the default repair
# against mode 0 of the same shader, with the engine's ray start offset.
#
# Cost, measured in that lab only (RTX 4090, 1920x1080, 1.34 million triangles, picked lamps,
# the fastest of 50 runs taken in turn in one process; "before" is the shader before this patch,
# built from the unpatched source into the same process by a throwaway probe, not by the lab
# itself; the same numbers within 0.002 ms in five processes, except the torch lamps of the
# first camera, see below):
#                                   street lamps, 3 cameras     torch lamps, cameras 1 and 2
#   before r41                      0.164  0.227  0.289 ms      0.105  0.166 ms
#   patched, experiment bit set     0.183  0.237  0.300 ms      0.123  0.177 ms
#   patched, default                0.197  0.288  0.327 ms      0.140  0.242 ms
# So the bit set gives the picture of before (0 differing pixels against the shader before r41,
# every lamp traced, street and torch lamps) but not its cost: the patched shader costs 0.01 to
# 0.02 ms more whatever its tuning (4 to 17%). About 0.005 ms of that are the tuning's values
# being read at run time; most of the rest comes with the rim rays' ray query being in the
# shader at all, cast or not (with the rim query taken out: 0.177 0.229 0.292). Other forms of
# the same rim rays were built and timed in the same process and were no faster: in the centre
# ray's own loop, as straight calls, with the noted lamps in plain variables in place of arrays
# (0.210 0.262 0.308 with the bit set), and with nothing kept in globals at all, the tuning read
# where it is used (0.193 0.243 0.302). An in-game comparison by the bit does not show the fixed
# part: compare the pass's GPU label between a reverted and an applied build for the whole.
# Default against before: +13 to +27% on the street lamps, +33 to +46% on the torch lamps (every
# pixel there is lit by a lamp with a body next to it). Scaled to the 0.76 ms of the heavy spot
# in the game that is +0.10 to +0.20 ms for street lamps and up to +0.35 ms if the whole screen
# were torch-lit next to a body (an inference: the game was not run). With
# BB_LAMP_SHADOW_NEAR=1 (rim rays for every blocked strong lamp) the street lamps cost 0.23 0.36
# 0.39 ms; with the old weights, NEAR=1 and SHARE=0 on top (every blocked lamp, the worst this
# pass can do with two lamps a pixel) 0.28 0.42 0.51 ms.
# The lab's times are not the same in every process, for one and the same shader: the torch
# lamps of the first camera ran at 0.10, 0.14 or 0.24 ms before r41, depending on the process,
# and in about one process of five the pipeline the lab makes first ran slower whatever shader
# it held (0.224 0.274 0.312 ms with the bit set, for this shader and for the one with nothing
# in globals alike, while a pipeline made later in the same process ran as in the table). Not
# explained, and not known whether the game's one pipeline can land in it. Only numbers of one
# process compare.
#
# Not cured: edges stay hard and stair-stepped; one ratio still serves all lamps and the weights
# are diffuse only; with three or more lamps the picked second lamp is a fixed pattern; the
# rebuild budget still starves the same copies (rotating it would change the sun's shadows too),
# and a starved moving copy that is the only caster of its object casts no lamp shadow at all.
import os
import re
import sys

ROOT = os.environ.get("R41_ROOT", "<tree>/").replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
S = G + "shim/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"

BIT = 45
VALUE = 1 << BIT  # 35184372088832
TMP = ".r41tmp"  # a new text waits under this name beside its target (main)
assert VALUE == 35184372088832

TUNE_H = r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass
// (point_shadow_ray.comp with MODE_REPAIR): the knobs, read once from the environment, the
// sixteen words PointShadow::Flush appends to the pass's data, and the weight of a lamp as the
// shader works it out. No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it alone.

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace Vulkan {

struct LampShadowTune {
    bool weights = true;         ///< BB_LAMP_SHADOW_WEIGHTS: the game's falloff times N.L; 0: as before
    float wrap = 0.15f;          ///< BB_LAMP_SHADOW_WRAP, 0..1: N.L tolerance; 1: no N.L
    float facing_floor = 0.05f;  ///< BB_LAMP_SHADOW_FLOOR, 0..1: least facing factor; 0: none
    float radius_m = 0.05f;      ///< BB_LAMP_SHADOW_SOFT, 0..0.3: the lamp's radius; 0: a point
    std::uint32_t rim = 3;       ///< BB_LAMP_SHADOW_RIM, 0..4: rays to the lamp's rim
    float share = 0.25f;         ///< BB_LAMP_SHADOW_SHARE, 0..1: least weight share for rim rays
    float near_part = 0.5f;      ///< BB_LAMP_SHADOW_NEAR, 0.05..1: rim rays for casters this near
                                 ///< the lamp (share of the way to the receiver); 1: everywhere
    float clearance_m = 0.35f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp
    float bias_m = 0.03f;        ///< BB_LAMP_SHADOW_BIAS, 0.005..0.2: ray start offset (the push block)
    float self_m = 0.06f;        ///< BB_LAMP_SHADOW_SELF, 0..0.3: grazing self skip
    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..3: debug view
    float view_gain = 0.5f;      ///< BB_LAMP_SHADOW_VIEW_GAIN, 0.01..16
};

inline constexpr std::uint32_t LampTuneWordCount = 16;
// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 4-6 rim rays, bits 8-9 the view. Words 1-9, floats: clearance,
// radius, share, self skip, wrap, the inverse-square curve's core squared, view gain, facing
// floor, near part. Words 10-12 and 13-15: two axes of the world in view space, unit length and
// square to each other (the rim pattern's frame): world +x (horizontal) and world +y (up).
inline constexpr std::uint32_t LampTuneNewWeights = 1, LampTuneInverseSquare = 2;
inline constexpr std::uint32_t LampTuneRimShift = 4, LampTuneViewShift = 8;

using LampTuneGet = const char* (*)(const char*);

namespace LampTuneDetail {
// The text up to trailing blanks must be a number; anything else leaves the default.
inline bool Ends(const char* end) {
    while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') {
        ++end;
    }
    return *end == '\0';
}

inline float Number(LampTuneGet get, const char* name, float fallback, float lo, float hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !Ends(end) || !std::isfinite(value)) {
        return fallback;
    }
    return std::clamp(value, lo, hi);
}

inline std::uint32_t Whole(LampTuneGet get, const char* name, std::uint32_t fallback,
                           std::uint32_t hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !Ends(end)) {
        return fallback;
    }
    return std::uint32_t(std::clamp(value, 0l, long(hi)));
}
} // namespace LampTuneDetail

/// The knobs as `get` (std::getenv) has them: a value out of range is clamped, one that is not
/// a number leaves the default.
inline LampShadowTune ReadLampShadowTune(LampTuneGet get) {
    using namespace LampTuneDetail;
    LampShadowTune tune;
    tune.weights = Whole(get, "BB_LAMP_SHADOW_WEIGHTS", tune.weights ? 1u : 0u, 1u) != 0;
    tune.wrap = Number(get, "BB_LAMP_SHADOW_WRAP", tune.wrap, 0.0f, 1.0f);
    tune.facing_floor = Number(get, "BB_LAMP_SHADOW_FLOOR", tune.facing_floor, 0.0f, 1.0f);
    tune.radius_m = Number(get, "BB_LAMP_SHADOW_SOFT", tune.radius_m, 0.0f, 0.3f);
    tune.rim = Whole(get, "BB_LAMP_SHADOW_RIM", tune.rim, 4u);
    tune.share = Number(get, "BB_LAMP_SHADOW_SHARE", tune.share, 0.0f, 1.0f);
    tune.near_part = Number(get, "BB_LAMP_SHADOW_NEAR", tune.near_part, 0.05f, 1.0f);
    tune.clearance_m = Number(get, "BB_LAMP_SHADOW_CLEARANCE", tune.clearance_m, 0.05f, 2.0f);
    tune.bias_m = Number(get, "BB_LAMP_SHADOW_BIAS", tune.bias_m, 0.005f, 0.2f);
    tune.self_m = Number(get, "BB_LAMP_SHADOW_SELF", tune.self_m, 0.0f, 0.3f);
    tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, 3u);
    tune.view_gain = Number(get, "BB_LAMP_SHADOW_VIEW_GAIN", tune.view_gain, 0.01f, 16.0f);
    return tune;
}

/// The core of the game's inverse-square curve as LocalFalloff::Patch takes it.
inline float LampTuneCore(float core) {
    return std::isfinite(core) && core > 0.0f ? core : 0.0f;
}

/// The world's +x and +y axes in view space (six floats) from `view`, the pass's world-to-view
/// matrix as 12 floats in rows of four (CameraMotion::Matrices::view, a VkTransformMatrixKHR):
/// its first two columns, made unit length. No matrix, or columns that are not finite, not of
/// about unit length or not square to each other: the view's own x and y axes (the rim pattern
/// then turns with the camera, as it did before the axes were handed over).
inline std::array<float, 6> LampTuneAxes(const float* view) {
    constexpr std::array<float, 6> Own{1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
    if (!view) {
        return Own;
    }
    std::array<float, 6> axes{view[0], view[4], view[8], view[1], view[5], view[9]};
    for (int k = 0; k < 2; ++k) {
        float* a = axes.data() + k * 3;
        const float length = std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        if (!std::isfinite(length) || !(length > 0.5f) || !(length < 2.0f)) {
            return Own;
        }
        for (int c = 0; c < 3; ++c) {
            a[c] /= length;
        }
    }
    const float dot = axes[0] * axes[3] + axes[1] * axes[4] + axes[2] * axes[5];
    return std::abs(dot) < 0.05f ? axes : Own;
}

/// What the shader reads at the place the mode word names. inverse_square, core: the lamp
/// falloff the game's shaders were patched to (startup_local_inverse_square,
/// startup_local_light_core). view: see LampTuneAxes.
inline std::array<std::uint32_t, LampTuneWordCount> LampTuneWords(const LampShadowTune& tune,
                                                                  bool inverse_square, float core,
                                                                  const float* view = nullptr) {
    const auto bits = [](float v) { return std::bit_cast<std::uint32_t>(v); };
    core = LampTuneCore(core);
    const auto axes = LampTuneAxes(view);
    const std::uint32_t flags = (tune.weights ? LampTuneNewWeights : 0u) |
                                (inverse_square ? LampTuneInverseSquare : 0u) |
                                std::min<std::uint32_t>(tune.rim, 7u) << LampTuneRimShift |
                                std::min<std::uint32_t>(tune.view, 3u) << LampTuneViewShift;
    return {flags,
            bits(tune.clearance_m),
            bits(tune.radius_m),
            bits(tune.share),
            bits(tune.self_m),
            bits(tune.wrap),
            bits(core * core),
            bits(tune.view_gain),
            bits(tune.facing_floor),
            bits(tune.near_part),
            bits(axes[0]),
            bits(axes[1]),
            bits(axes[2]),
            bits(axes[3]),
            bits(axes[4]),
            bits(axes[5])};
}

/// A lamp's weight at a pixel as point_shadow_ray.comp's lampWeight works it out. t2: distance
/// squared over radius squared (below 1); facing: the cosine between the surface normal and the
/// direction to the lamp; has_normal false: the pass found no normal there (no facing term);
/// luma: of the lamp's colour.
inline float LampWeight(const LampShadowTune& tune, bool inverse_square, float core, float t2,
                        float facing, bool has_normal, float luma) {
    if (!tune.weights) {
        float w = 1.0f - t2;
        w *= w * luma;
        return w;
    }
    float f = 1.0f - std::sqrt(t2);
    f *= f;
    if (inverse_square) {
        core = LampTuneCore(core);
        f = std::max(0.0f, 1.0f / std::max(t2 + core * core, 1e-6f) - 1.0f / (1.0f + core * core));
    }
    float faced = 1.0f;
    if (tune.wrap < 1.0f && has_normal) {
        // Never below the floor: the facing ranks the lamps, it does not remove one.
        faced = std::clamp((facing + tune.wrap) / (1.0f + tune.wrap), tune.facing_floor, 1.0f);
    }
    return f * faced * luma;
}

} // namespace Vulkan
"""

TUNE_TEST = r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"

using namespace Vulkan;

namespace {
using Pair = std::pair<const char*, const char*>;
// The environment of the case being read.
const Pair* env_begin = nullptr;
const Pair* env_end = nullptr;

const char* Get(const char* name) {
    for (const Pair* it = env_begin; it != env_end; ++it) {
        if (std::strcmp(it->first, name) == 0) {
            return it->second;
        }
    }
    return nullptr;
}

template <std::size_t N>
LampShadowTune Read(const std::array<Pair, N>& env) {
    env_begin = env.data();
    env_end = env.data() + N;
    return ReadLampShadowTune(Get);
}

float F(std::uint32_t word) {
    return std::bit_cast<float>(word);
}

bool Near(float a, float b) {
    return std::abs(a - b) <= 1e-6f;
}
} // namespace

int main() {
    // Nothing set: the defaults the patch documents.
    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.radius_m == 0.05f && t.rim == 3u);
        assert(t.share == 0.25f && t.clearance_m == 0.35f && t.bias_m == 0.03f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        assert(t.facing_floor == 0.05f && t.near_part == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);
    }
    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_NEAR", "0.75"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.4"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "2"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.radius_m == 0.2f && t.rim == 4u);
        assert(t.share == 0.4f && t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 2u && t.view_gain == 4.0f);
        assert(t.facing_floor == 0.25f && t.near_part == 0.75f);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_NEAR", "0"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_RIM", "-2"},
            {"BB_LAMP_SHADOW_SHARE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
            {"BB_LAMP_SHADOW_SELF", "-1"},
            {"BB_LAMP_SHADOW_VIEW", "-1"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.radius_m == 0.0f && low.rim == 0u);
        assert(low.share == 0.0f && low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        assert(low.facing_floor == 0.0f && low.near_part == 0.05f);
        const LampShadowTune high = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_NEAR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_RIM", "99"},
            {"BB_LAMP_SHADOW_SHARE", "2"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
            {"BB_LAMP_SHADOW_SELF", "1"},
            {"BB_LAMP_SHADOW_VIEW", "9"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.radius_m == 0.3f && high.rim == 4u);
        assert(high.share == 1.0f && high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 3u && high.view_gain == 16.0f);
        assert(high.facing_floor == 1.0f && high.near_part == 1.0f);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_NEAR", "0.5x"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_RIM", "two"},
            {"BB_LAMP_SHADOW_SHARE", "nan"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
            {"BB_LAMP_SHADOW_SELF", "0.12 "},
            {"BB_LAMP_SHADOW_VIEW", "1x"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "-"},
        }});
        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.rim == d.rim && t.share == d.share && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.near_part == d.near_part);
        assert(t.self_m == 0.12f);
    }
    // The words: flags, nine floats, two axes.
    {
        static_assert(LampTuneWordCount == 16);
        const LampShadowTune d;
        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        assert(words[0] == (1u | 3u << 4)); // new weights, 3 rim rays, view 0
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.05f && F(words[3]) == 0.25f);
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
        assert(Near(F(words[6]), 0.0025f));
        assert(F(words[8]) == 0.05f && F(words[9]) == 0.5f);
        // No view matrix: the view's own x and y axes.
        assert(F(words[10]) == 1.0f && F(words[11]) == 0.0f && F(words[12]) == 0.0f);
        assert(F(words[13]) == 0.0f && F(words[14]) == 1.0f && F(words[15]) == 0.0f);
        // A view matrix (rows of four; here the camera looks down the world's -y, turned by
        // 30 degrees about it, and stands away from the origin): the world's +x and +y axes as
        // the view sees them are its first two columns, whatever the translation.
        const float c = std::cos(0.5235988f), s = std::sin(0.5235988f);
        const std::array<float, 12> view{c,    0.0f, -s,   5.0f,  s,    0.0f,
                                         c,    -7.0f, 0.0f, -1.0f, 0.0f, 9.0f};
        const auto turned = LampTuneWords(d, false, 0.05f, view.data());
        assert(Near(F(turned[10]), c) && Near(F(turned[11]), s) && Near(F(turned[12]), 0.0f));
        assert(Near(F(turned[13]), 0.0f) && Near(F(turned[14]), 0.0f));
        assert(Near(F(turned[15]), -1.0f));
        for (int k = 0; k < 10; ++k) {
            assert(turned[k] == words[k]); // the axes change nothing else
        }
        // A matrix that is no rotation (scaled, sheared, not finite, empty): the view's own axes.
        std::array<float, 12> bad = view;
        bad[0] = 3.0f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[1] = 0.5f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[4] = std::nanf("");
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = {};
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        LampShadowTune t;
        t.weights = false;
        t.rim = 4;
        t.view = 3;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 4 | 3u << 8));
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The rim count and the view cannot leave their fields.
        t.rim = 100;
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (7u << 4 | 3u << 8));
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
    // one (1 - d^2/r^2)^2 gave 0.5625: a distant lamp counted 2.25 times too much.
    {
        const LampShadowTune d;
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 0.5f), 0.125f)); // luma
        LampShadowTune old;
        old.weights = false;
        assert(Near(LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.5625f));
        // The old weight knows no facing and no curve switch.
        assert(LampWeight(old, true, 0.05f, 0.25f, -1.0f, true, 1.0f) ==
               LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f));
        // Behind the surface, floor 0: nothing with wrap 0, nothing past the wrap otherwise.
        // The whole weight with wrap 1 (no N.L) or where the pass found no normal.
        LampShadowTune hard;
        hard.wrap = 0.0f;
        hard.facing_floor = 0.0f;
        assert(LampWeight(hard, false, 0.05f, 0.25f, -0.2f, true, 1.0f) == 0.0f);
        assert(LampWeight(hard, false, 0.05f, 0.25f, 0.0f, true, 1.0f) == 0.0f);
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, 0.5f, true, 1.0f), 0.125f));
        LampShadowTune gate;
        gate.facing_floor = 0.0f;
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.15f, true, 1.0f) == 0.0f);
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.1f, true, 1.0f) > 0.0f);
        // The default floor: a lamp behind the surface keeps a twentieth of its weight (so a
        // pixel whose only lamp it is still gets its ray), and still ranks below one in front.
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.0125f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -0.15f, true, 1.0f), 0.0125f));
        assert(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) > 1e-5f);
        assert(LampWeight(d, false, 0.05f, 0.25f, 0.3f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) * 5.0f);
        LampShadowTune none;
        none.wrap = 1.0f;
        assert(Near(LampWeight(none, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, -1.0f, false, 1.0f), 0.25f));
        // The inverse-square curve: 1 / (x^2 + core^2) - 1 / (1 + core^2), 0 at the radius.
        const float core2 = 0.05f * 0.05f;
        assert(Near(LampWeight(d, true, 0.05f, 0.25f, 1.0f, true, 1.0f),
                    1.0f / (0.25f + core2) - 1.0f / (1.0f + core2)));
        assert(Near(LampWeight(d, true, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(std::isfinite(LampWeight(d, true, 0.0f, 0.0f, 1.0f, true, 1.0f)));
        // Both curves end at the radius and fall with distance.
        assert(Near(LampWeight(d, false, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(LampWeight(d, false, 0.05f, 0.04f, 1.0f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.64f, 1.0f, true, 1.0f));
    }
    std::puts("lamp shadow tune: ok");
    return 0;
}
"""

NEW_FILES = {
 R + "lamp_shadow_tune.h": TUNE_H,
 TESTS + "test_lamp_shadow_tune.cpp": TUNE_TEST,
}

EDITS = {
 B + "host_shaders/point_shadow_ray.comp": [
  # The tuning the pass hands over, and the colours of the views.
  (r"""float word(uint i) { return uintBitsToFloat(data.d[i]); }
vec4 row(uint i) { return vec4(word(i), word(i + 1u), word(i + 2u), word(i + 3u)); }
""", r"""float word(uint i) { return uintBitsToFloat(data.d[i]); }
vec4 row(uint i) { return vec4(word(i), word(i + 1u), word(i + 2u), word(i + 3u)); }

// bbport (r41_lamp-shadows): the repair. MODE_REPAIR in `mode`: bits 8-31 of `mode` are the
// place in `data` of sixteen tuning words (vk_point_shadow.cpp Flush, lamp_shadow_tune.h
// LampTuneWords). Clear (experiment 35184372088832 set, or a caller that knows nothing of it):
// the values below stay as they are here, which is the pass of before: the old weights, a point
// lamp, LAMP_CLEARANCE, the ray's start where it was, no view.
const uint MODE_REPAIR = 16u;
bool new_w = false;             // weights follow the game's falloff and the surface's facing
bool inv_sq = false;            // the game's lamps use the inverse-square curve
uint t_rim = 0u;                // rays to the rim of a strong lamp whose centre is blocked
uint t_view = 0u;               // debug view (BB_LAMP_SHADOW_VIEW)
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
float t_radius = 0.0;           // the lamp's radius, m
float t_share = 2.0;            // least share of the pixel's weight for rim rays
float t_self = 0.0;             // grazing self skip, m
float t_wrap = 0.0;             // N.L tolerance of the weights; 1: no N.L
float t_core2 = 0.0;            // the inverse-square curve's core, squared
float t_gain = 1.0;             // brightness of the view
float t_floor = 0.0;            // least facing factor of the weights
float t_near = 1.0;             // rim rays for a caster this near the lamp (share of the way)
// Two axes of the world, in view space (this pass works in view space): the rim pattern is laid
// out against them, so it stays put in the world when the camera turns.
vec3 t_axis_a = vec3(1.0, 0.0, 0.0);
vec3 t_axis_b = vec3(0.0, 1.0, 0.0);
uint rays_cast = 0u;            // rays this invocation cast (view 3)

// Called once a workgroup has a tile (an empty one reads nothing).
void loadTune() {
    if ((mode & MODE_REPAIR) == 0u) {
        return;
    }
    const uint at = mode >> 8u;
    const uint f = data.d[at];
    new_w = (f & 1u) != 0u;
    inv_sq = (f & 2u) != 0u;
    t_rim = (f >> 4u) & 7u;
    t_view = (f >> 8u) & 3u;
    t_clear = word(at + 1u);
    t_radius = word(at + 2u);
    t_share = word(at + 3u);
    t_self = word(at + 4u);
    t_wrap = word(at + 5u);
    t_core2 = word(at + 6u);
    t_gain = word(at + 7u);
    t_floor = word(at + 8u);
    t_near = word(at + 9u);
    t_axis_a = vec3(word(at + 10u), word(at + 11u), word(at + 12u));
    t_axis_b = vec3(word(at + 13u), word(at + 14u), word(at + 15u));
}

// The views' colour for a count: 0 blue, 1 green, 2 yellow, 3 or more red.
vec3 stepColour(uint k) {
    return k == 0u ? vec3(0.0, 0.0, 1.0)
                   : k == 1u ? vec3(0.0, 1.0, 0.0) : k == 2u ? vec3(1.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
}

// A lamp's weight in the pixel's shadow ratio: about its share of the lamps' light there.
// to_light: from the surface to the lamp; t2: its length squared over the radius squared.
// Before (and with BB_LAMP_SHADOW_WEIGHTS=0): (1 - t2)^2 * luma. The game's own curve is
// (1 - d/r)^2 (vk_local_falloff.h), or 1 / (t2 + core^2) - 1 / (1 + core^2) with
// startup_local_inverse_square, and its light goes with N.L: the old weight overrated a lamp far
// away or behind the surface, so that lamp's shadow took the nearer lamp's light and the nearer
// lamp's shadow took too little. The normal is the one from depth: t_wrap forgives its error,
// and the facing never falls below t_floor: it ranks the lamps, it does not remove one. (A pixel
// whose only lamp had no weight would get no ray and keep that lamp's light unshadowed, also
// inside a wall's shadow; and the normal is arbitrary on features a pixel or two wide.) With the
// floor a lamp behind the surface keeps a ray, which its own surface blocks, as before.
float lampWeight(vec3 to_light, float t2, vec3 col, vec3 n) {
    const float l = dot(col, vec3(0.299, 0.587, 0.114));
    if (!new_w) {
        float w = 1.0 - t2;
        w *= w * l;
        return w;
    }
    float f = 1.0 - sqrt(t2);
    f *= f;
    if (inv_sq) {
        f = max(0.0, 1.0 / max(t2 + t_core2, 1e-6) - 1.0 / (1.0 + t_core2));
    }
    float facing = 1.0;
    if (t_wrap < 1.0 && n != vec3(0.0)) {
        facing = clamp((dot(n, to_light) * inversesqrt(max(dot(to_light, to_light), 1e-8)) + t_wrap) /
                           (1.0 + t_wrap),
                       t_floor, 1.0);
    }
    return f * facing * l;
}
"""),
  # One ray, with the place where hits start to count handed in.
  (r"""float visibility(vec3 origin, float reach, vec3 L) {
    const vec3 ray_to = L - origin;
    const float ray_len = length(ray_to);
    const float tmax = ray_len - LAMP_CLEARANCE;
    if (!(tmax > reach)) {
        return 1.0;
    }
""", r"""// bbport (r41_lamp-shadows): one ray from `origin` towards `target` (the lamp's centre or a
// point of its rim), blind within t_clear of the target. Below 0: free. Else blocked: how far
// along the way to the target the hit lies, 0 to 1 (a hit, not always the nearest: the ray stops
// at its first). (Before: visibility(), 1 free and 0 blocked, with LAMP_CLEARANCE; with the
// repair off t_clear is that constant and the query is the same.)
float ray(vec3 origin, float reach, vec3 target) {
    const vec3 ray_to = target - origin;
    const float ray_len = length(ray_to);
    const float tmax = ray_len - t_clear;
    if (!(tmax > reach)) {
        return -1.0;
    }
    ++rays_cast;
"""),
  (r"""                          origin, reach * 0.5, ray_to / ray_len, tmax);
    rayQueryProceedEXT(query);
    return rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionNoneEXT ? 1.0
                                                                                                  : 0.0;
}
""", r"""                          origin, reach * 0.5, ray_to / ray_len, tmax);
    rayQueryProceedEXT(query);
    if (rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
        return -1.0;
    }
    return rayQueryGetIntersectionTEXT(query, true) / ray_len;
}

// bbport (r41_lamp-shadows): whether the lamp at L lights the surface at P: 1 or 0, nothing
// between (no noise, nothing to filter, and the half-resolution build's block answers keep
// agreeing). The ray to the lamp's centre is cast here, in straight code as before; the rays to
// its rim are cast later, in one loop for the pixel (rimLight): a ray query inside a loop that
// every lamp goes through made the whole pass slower, also with the repair off.
//  - Grazing self skip: the ray starts reach off the surface along a normal worked out from
//    depth, and at a flat angle it stays close to the surface it left for a long way: layered
//    cloth and hair cards shadowed themselves in polygon-shaped patches. The start is lifted
//    along the normal by t_self * (1 - N.L)^2 more. (Lifted, not "hits count from further along
//    the ray": that would also pass a thin wall or prop standing next to the pixel.)
//  - wide: the lamp is a disc of radius t_radius facing the surface, not a point. Where the ray
//    to its centre is blocked, up to t_rim rays go to its rim, and one free ray means lit. A
//    caster thinner than about 2 * t_radius * (1 - q) then casts nothing, q being its distance
//    from the lamp over the receiver's: a point lamp magnified a torch stick, a weapon handle or
//    the torch head next to the flame into a long hard band across the ground. A wide caster
//    keeps its shadow, with each edge moved in by up to t_radius * (1 - q) / q on the receiver
//    (between half of that and all of it, by the edge's angle to the three rim points).
//  - t_near: all of that only where the caster is near the lamp, which is where a point lamp
//    magnifies it: the radius is whole up to q = t_near / 2 and falls to nothing at q = t_near
//    (q from the centre ray's hit). A caster further from the lamp keeps the point lamp's shadow
//    and costs no rim ray. 1: everywhere.
//  - The rim points are laid out against two axes of the world (t_axis_a, a horizontal one, and
//    t_axis_b, up), not of the view: against the view's they turned with the camera and so did
//    the eroded edges. Where the ray runs within 26 degrees of the first axis the second takes
//    over; that seam is fixed in the world.
// wide is asked only for a lamp that holds a share of the pixel's weight (w), so the extra rays
// go where a strong lamp is blocked by something near it; at most MAX_RIM_LAMPS lamps a pixel.
const uint MAX_RIM_LAMPS = 4u;
vec3 rim_from[MAX_RIM_LAMPS];    // the ray's start
vec3 rim_l[MAX_RIM_LAMPS];       // the lamp's centre
float rim_radius[MAX_RIM_LAMPS]; // the lamp's radius for this caster
float rim_w[MAX_RIM_LAMPS];      // the lamp's weight
uint rim_n = 0u;

float lampVisibility(vec3 P, vec3 n, vec3 origin, float reach, vec3 L, float w, bool wide) {
    vec3 from = origin;
    if (t_self > 0.0 && n != vec3(0.0)) {
        const float g = 1.0 - clamp(dot(n, normalize(L - P)), 0.0, 1.0);
        from += n * (t_self * g * g);
    }
    const float hit = ray(from, reach, L);
    if (hit < 0.0) {
        return 1.0;
    }
    if (wide && rim_n < MAX_RIM_LAMPS) {
        float radius = t_radius;
        if (t_near < 1.0) {
            radius *= clamp(2.0 - 2.0 * (1.0 - hit) / t_near, 0.0, 1.0);
        }
        if (radius > 0.0) {
            rim_from[rim_n] = from;
            rim_l[rim_n] = L;
            rim_radius[rim_n] = radius;
            rim_w[rim_n] = w;
            ++rim_n;
        }
    }
    return 0.0;
}

// bbport (r41_lamp-shadows): the weight of the lamps lampVisibility noted (centre blocked by
// something near the lamp) that a ray to their rim reaches after all.
float rimLight(float reach) {
    float lit = 0.0;
    for (uint j = 0u; j < rim_n; ++j) {
        const vec3 dir = normalize(rim_l[j] - rim_from[j]);
        const vec3 across = cross(dir, abs(dot(dir, t_axis_a)) < 0.9 ? t_axis_a : t_axis_b);
        const float len2 = dot(across, across);
        if (!(len2 > 1e-6)) {
            continue;
        }
        const vec3 u = across * inversesqrt(len2);
        const vec3 v = cross(dir, u);
        for (uint i = 0u; i < t_rim; ++i) {
            const float a = 6.2831853 * (float(i) + 0.25) / float(t_rim);
            if (ray(rim_from[j], reach, rim_l[j] + rim_radius[j] * (cos(a) * u + sin(a) * v)) < 0.0) {
                lit += rim_w[j];
                break;
            }
        }
    }
    return lit;
}
"""),
  (r"""    const bool overflow = listed > MAX_GROUP_TILES;
""", r"""    loadTune(); // bbport (r41_lamp-shadows): after the return of a workgroup with no tile
    const bool overflow = listed > MAX_GROUP_TILES;
"""),
  (r"""    float wsum = 0.0;
    const bool exact = steps == 0u;
""", r"""    float wsum = 0.0;
    // bbport (r41_lamp-shadows): rim rays wanted at all; for view 2, the lamp records with weight
    // at the pixel (a lamp that two overlapping tiles of a batch list counts twice, as its
    // weight does) and the largest weight (top_w is not kept when every lamp is traced).
    const bool rim = t_rim > 0u && t_radius > 0.0;
    uint lamps = 0u;
    float view_top = 0.0;
    const bool exact = steps == 0u;
"""),
  (r"""            const vec3 col = vec3(word(at + 4u), word(at + 5u), word(at + 6u));
            float w = 1.0 - t2;
            w *= w * dot(col, vec3(0.299, 0.587, 0.114));
            if (!(w > 1e-5)) {
                continue;
            }
            wsum += w;
""", r"""            const vec3 col = vec3(word(at + 4u), word(at + 5u), word(at + 6u));
            const float w = lampWeight(to_light, t2, col, n); // bbport (r41_lamp-shadows)
            if (!(w > 1e-5)) {
                continue;
            }
            wsum += w;
            ++lamps;
            view_top = max(view_top, w);
"""),
  (r"""                        float w = 1.0 - t2;
                        w *= w * dot(col, vec3(0.299, 0.587, 0.114));
                        if (!(w > 1e-5)) {
                            continue;
                        }
                        vsum += w * visibility(origin, reach, L);
""", r"""                        const float w = lampWeight(to_light, t2, col, n); // bbport (r41)
                        if (!(w > 1e-5)) {
                            continue;
                        }
                        vsum += w * lampVisibility(P, n, origin, reach, L, w, rim && w >= t_share * wsum);
"""),
  (r"""            vsum = top_w * visibility(origin, reach, top_l);
            if (rest_w > 0.0) {
                vsum += rest_w * visibility(origin, reach, rest_l);
            }
""", r"""            // bbport (r41_lamp-shadows): rim rays for the strongest lamp and for the picked one
            // (which stands for all the others), each only where it holds a share of the
            // pixel's weight
            vsum = top_w * lampVisibility(P, n, origin, reach, top_l, top_w, rim && top_w >= t_share * wsum);
            if (rest_w > 0.0) {
                vsum += rest_w *
                        lampVisibility(P, n, origin, reach, rest_l, rest_w, rim && rest_w >= t_share * wsum);
            }
"""),
  (r"""        ratio = clamp(vsum / wsum, 0.0, 1.0);
""", r"""        if (rim_n != 0u) {
            vsum += rimLight(reach); // bbport (r41_lamp-shadows): the rim rays of the noted lamps
        }
        ratio = clamp(vsum / wsum, 0.0, 1.0);
"""),
  (r"""    const float scale = mix(1.0, ratio, strength * fade);
    imageStore(cur0, px, vec4(s0 + d0 * scale, 1.0));
    imageStore(cur1, px, vec4(s1 + d1 * scale, 1.0));
""", r"""    const float scale = mix(1.0, ratio, strength * fade);
    vec3 out0 = s0 + d0 * scale, out1 = s1 + d1 * scale;
    if (t_view != 0u) {
        // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_VIEW, on pixels the pass shadows, in place of
        // their light (the game multiplies it by the surface's colour). 1: the shadow ratio. 2:
        // how many lamp records have weight here (1 blue, 2 green, 3 yellow, 4 or more red),
        // dimmer the smaller the strongest one's share. 3: rays this pixel cast (0 blue, 1
        // green, 2 yellow, 3 or more red). The history and the half-resolution answers hold the
        // ratio as always.
        vec3 shown = vec3(ratio);
        if (t_view == 2u) {
            shown = stepColour(lamps - 1u) * (0.25 + 0.75 * view_top / wsum);
        } else if (t_view == 3u) {
            shown = stepColour(rays_cast);
        }
        out0 = shown * t_gain;
        out1 = vec3(0.0);
    }
    imageStore(cur0, px, vec4(out0, 1.0));
    imageStore(cur1, px, vec4(out1, 1.0));
"""),
 ],
 R + "vk_rt_shadow.h": [
  (r"""inline constexpr u64 R19DrawCostOffBit = 17592186044416ull;
""", r"""inline constexpr u64 R19DrawCostOffBit = 17592186044416ull;

// bbport (r41_lamp-shadows): experiment bit 45: set = ray traced lamp shadows as before their
// repair (read at every lamp pass and every scene build): the old weights, a point lamp, no
// grazing self skip (PointShadow::Flush, point_shadow_ray.comp MODE_REPAIR), and moving shared
// copies with an old pose still in lamp rays (RtShadow::PrepareScene, Entry::lamp_out). Set
// brings picture faults back, so it is not one of BbSettings::PreviousPathsBits.
inline constexpr u64 LampRepairOffBit = 35184372088832ull;
"""),
  (r"""        u8 cascades = 0;
        bool held = false;
""", r"""        u8 cascades = 0;
        bool held = false;
        // bbport (r41_lamp-shadows): a moving shared copy (rebuilt and dynamic): draws in a row
        // that went without a rebuild (PrepareDraw's skip, up to LampStaleSkips + 1), rebuilds
        // in a row since it was left out, and whether lamp rays leave it out (PrepareScene).
        u8 lamp_skips = 0;
        u8 lamp_builds = 0;
        bool lamp_out = false;
"""),
 ],
 R + "vk_rt_shadow.cpp": [
  (r"""constexpr u8 LampMask = 4;
""", r"""constexpr u8 LampMask = 4;
// bbport (r41_lamp-shadows): a moving copy of a mesh drawn more than once in a pass (a "shared"
// entry, see PrepareDraw) is never refit, only rebuilt, within RebuiltTrianglesPerFrame and in
// draw order. Where a frame's copies hold more triangles than that, the same ones go without
// every frame: they keep the pose of their last build and stay in the scene, beside the live
// copy of the same mesh. A lamp ray then finds two casters, the second one displaced: a second
// hard shadow. Such a copy is left out of lamp rays (Entry::lamp_out) once it was drawn and went
// without more than LampStaleSkips times in a row, and comes back once it was rebuilt on
// LampFreshBuilds draws in a row: a copy at the edge of the budget does not blink in and out
// (and each change of an instance's mask makes the TLAS a full build). Counted in draws that
// went without, not in the age of the BLAS: a copy the far cascades hold undrawn
// (graphics_sun_far_shadows) ages without being starved and keeps its lamp shadow. A copy whose
// draw is known to read what its BLAS was built from (Draw::inputs, with BB_RT_UNCHANGED set)
// holds the right pose and stays in. The sun's rays keep every copy, as before. Experiment
// LampRepairOffBit set: all stay in lamp rays (the counting goes on).
constexpr u32 LampStaleSkips = 2;
constexpr u32 LampFreshBuilds = 3;
"""),
  (r"""        if (!entry.built) {
            ++missed;
            return 0u;
        }
        entry.seen_frame = frame;
        frame_entries.push_back(&entry);
        return 0u;
    };
""", r"""        if (!entry.built) {
            ++missed;
            return 0u;
        }
        // bbport (r41_lamp-shadows): a moving shared copy drawn without a rebuild (see
        // LampStaleSkips); at most once a frame (a second draw of an entry returns above).
        if (entry.rebuilt && entry.dynamic) {
            entry.lamp_builds = 0;
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                entry.lamp_skips = 0; // the BLAS holds this very pose
                entry.lamp_out = false;
            } else if (entry.lamp_skips > LampStaleSkips || ++entry.lamp_skips > LampStaleSkips) {
                entry.lamp_out = true;
            }
        }
        entry.seen_frame = frame;
        frame_entries.push_back(&entry);
        return 0u;
    };
"""),
  (r"""        if (!update) {
            entry.built_frame = frame;
        }
""", r"""        if (!update) {
            entry.built_frame = frame;
            // bbport (r41_lamp-shadows): rebuilt: back in lamp rays after LampFreshBuilds in a row
            entry.lamp_skips = 0;
            if (entry.lamp_out && ++entry.lamp_builds >= LampFreshBuilds) {
                entry.lamp_out = false;
                entry.lamp_builds = 0;
            }
        }
"""),
  (r"""    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
""", r"""    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
    const bool lamp_repair = !BbToggle::Experiment(LampRepairOffBit); // bbport (r41_lamp-shadows)
"""),
  (r"""        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card ? 0 : LampMask)),
""", r"""        // bbport (r41_lamp-shadows): a moving shared copy in an old pose casts no lamp shadow
        // (Entry::lamp_out, kept by PrepareDraw; a changed mask makes the TLAS a full build,
        // not a refit).
        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card || stale ? 0 : LampMask)),
"""),
  (r"""        u64 shared = 0, shared_triangles = 0, shared_moving = 0, shared_palette = 0,
            shared_camera = 0, shared_rebuilt = 0, shared_rebuilt_triangles = 0;
""", r"""        u64 shared = 0, shared_triangles = 0, shared_moving = 0, shared_palette = 0,
            shared_camera = 0, shared_rebuilt = 0, shared_rebuilt_triangles = 0;
        // bbport (r41_lamp-shadows): moving copies left out of lamp rays for their old pose
        // (Entry::lamp_out), and the oldest moving copy's BLAS in frames.
        u64 shared_no_lamp = 0, shared_oldest = 0;
        const bool lamp_repair = !BbToggle::Experiment(LampRepairOffBit);
"""),
  (r"""            if (e->built_frame == frame) {
                ++shared_rebuilt;
                shared_rebuilt_triangles += e->triangles;
            }
""", r"""            if (e->built_frame == frame) {
                ++shared_rebuilt;
                shared_rebuilt_triangles += e->triangles;
            }
            if (e->dynamic) { // bbport (r41_lamp-shadows)
                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
                shared_no_lamp += lamp_repair && e->lamp_out ? 1 : 0;
            }
"""),
  (r"""                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u\n",
""", r"""                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u; %llu left out of lamp rays (oldest %llu frames)\n",
"""),
  (r"""                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget());
""", r"""                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget(),
                    static_cast<unsigned long long>(shared_no_lamp),
                    static_cast<unsigned long long>(shared_oldest));
"""),
 ],
 R + "vk_point_shadow.h": [
  (r"""#include "video_core/buffer_cache/buffer.h"
""", r"""#include "video_core/buffer_cache/buffer.h"
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
"""),
  (r"""    float bias_m = 0.03f;
    u32 steps = 16;
""", r"""    float bias_m = 0.03f;
    u32 steps = 16;
    // bbport (r41_lamp-shadows): the ray traced pass's tuning (BB_LAMP_SHADOW_*, read once), which
    // Flush hands the shader while experiment 35184372088832 (LampRepairOffBit) is clear; whether
    // the last ray traced pass had it (-1: none yet), for the log line at each change.
    LampShadowTune tune;
    int repair_state = -1;
"""),
 ],
 R + "vk_point_shadow.cpp": [
  (r"""constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
""", r"""constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
// bbport (r41_lamp-shadows): MODE_REPAIR, and where the place of the pass's tuning words
// (LampTuneWords) goes in the same word: bits 8-31. The shader only tests single bits below
// that; with DataWords 2^18 the word stays below 2^27.
constexpr u32 ModeRepair = 16;
constexpr u32 TuneAtShift = 8;
static_assert(DataWords <= 1u << (32 - TuneAtShift));
"""),
  (r"""    fade_start_m = fade_end_m * 0.6f;
""", r"""    fade_start_m = fade_end_m * 0.6f;
    // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_*, read once
    tune = ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); });
"""),
  (r"""        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
""", r"""        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows)
        std::printf("Ray traced lamps (r41): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s), lamp radius %.2f m with %u rim rays from share %.2f for casters within "
                    "%.2f of the way from the lamp, clearance %.2f m, bias %.3f m, self skip %.2f "
                    "m, view %u (BB_LAMP_SHADOW_*); experiment 35184372088832 set = the path "
                    "before\n",
                    tune.weights ? "as the game's falloff and facing" : "as before", tune.wrap,
                    tune.facing_floor,
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", tune.radius_m,
                    tune.rim, tune.share, tune.near_part, tune.clearance_m, tune.bias_m,
                    tune.self_m, tune.view);
    }
"""),
  (r"""                              (apart || merged ? HistoryWords : 0) <= DataWords;
""", r"""                              (apart || merged ? HistoryWords + LampTuneWordCount : 0) <=
                          DataWords; // bbport (r41_lamp-shadows): and the tuning words
"""),
  (r"""    std::array<s32, 4> covered{s32(width), s32(height), 0, 0};
    u32 table = 0;
    if (use_rays) {
""", r"""    std::array<s32, 4> covered{s32(width), s32(height), 0, 0};
    u32 table = 0;
    // bbport (r41_lamp-shadows): the repair, unless experiment 35184372088832 is set (read at
    // every pass): the tuning words go after the tile table, their place into the mode word.
    bool repair = false;
    u32 tune_at = 0;
    if (use_rays) {
"""),
  (r"""                                     u32(tile.rect[3]), tile.first_light, tile.count, 0u, 0u});
        }
""", r"""                                     u32(tile.rect[3]), tile.first_light, tile.count, 0u, 0u});
        }
        repair = !BbToggle::Experiment(LampRepairOffBit);
        if (repair) {
            const auto& settings = BbSettings::Get();
            // The scene the rays cross is in this camera's view space (RtShadow::PrepareScene,
            // true above, wrote its instances with this matrix): the world's axes for the rim
            // pattern, so that it does not turn with the camera.
            const auto camera = camera_motion.PassMatrices();
            const auto tune_words = LampTuneWords(tune, settings.startup_local_inverse_square,
                                                  settings.startup_local_light_core,
                                                  camera.valid ? camera.view.data() : nullptr);
            tune_at = u32(data.size());
            data.insert(data.end(), tune_words.begin(), tune_words.end());
        }
        if (int(repair) != std::exchange(repair_state, int(repair))) {
            std::printf("Ray traced lamps (r41): repair %s (experiment 35184372088832 %s)\n",
                        repair ? "on" : "off", repair ? "clear" : "set");
        }
"""),
  (r"""        .thickness_m = use_rays ? std::bit_cast<float>(batch_apart ? ModeApart : 0u) : thickness_m,
""", r"""        // bbport (r41_lamp-shadows): MODE_REPAIR and the place of its words
        .thickness_m = use_rays ? std::bit_cast<float>((batch_apart ? ModeApart : 0u) |
                                                       (repair ? ModeRepair | tune_at << TuneAtShift
                                                               : 0u))
                                : thickness_m,
"""),
  (r"""        .bias_m = bias_m,
        .rect = {},
""", r"""        .bias_m = repair ? tune.bias_m : bias_m, // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_BIAS
        .rect = {},
"""),
 ],
 S + "bbport_settings.h": [
  (r"""// copies never refreshed), 23 (no Reflex sleep at all), 28 (acts only with BB_SUN_CASCADE_EVERY)
// and 51 (acts only with BB_RT_UPKEEP_FREEZE).
inline constexpr int PreviousPathsBits[] = {""", r"""// copies never refreshed), 23 (no Reflex sleep at all), 28 (acts only with BB_SUN_CASCADE_EVERY)
// and 51 (acts only with BB_RT_UPKEEP_FREEZE).
// bbport (r41_lamp-shadows): 45 (35184372088832; set = ray traced lamp shadows before their
// repair, vk_rt_shadow.h LampRepairOffBit) is not in it either, for the reason 14 is not: set
// brings picture faults back (doubled and faint torch shadows).
inline constexpr int PreviousPathsBits[] = {"""),
 ],
 G + "CMakeLists.txt": [
  (r"""add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
""", r"""add_executable(lamp-fog-lights-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_lights.cpp)
target_compile_options(lamp-fog-lights-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-fog-lights-test PRIVATE ..)
# bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h)
add_executable(lamp-shadow-tune-test EXCLUDE_FROM_ALL ../tests/test_lamp_shadow_tune.cpp)
target_compile_options(lamp-shadow-tune-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(lamp-shadow-tune-test PRIVATE ..)
"""),
  (r"""    add_dependencies(${effect_test_name} host_shaders)
endforeach()
""", r"""    add_dependencies(${effect_test_name} host_shaders)
endforeach()
# bbport (r41_lamp-shadows): the lab runs the lamp pass with lamp_shadow_tune.h's words
target_include_directories(rt-shadow-test PRIVATE ..)
"""),
 ],
 TESTS + "test_settings.cpp": [
  (r"""        for (const int bit : {0, 1, 2, 3, 4, 8, 14, 23, 28, 51}) { // left out on purpose
""", r"""        // bbport (r41_lamp-shadows): 45 (the lamp shadow repair off) brings faults back, as 14
        for (const int bit : {0, 1, 2, 3, 4, 8, 14, 23, 28, 45, 51}) { // left out on purpose
"""),
 ],
 TESTS + "test_rt_shadows.cpp": [
  (r"""#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
""", r"""#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
"""),
  (r"""        std::array<std::array<double, 2>, 3> pick_error{};
""", r"""        std::array<std::array<double, 2>, 3> pick_error{};
        // bbport (r41_lamp-shadows): per camera, on casters a lamp ray can hit, for the street
        // lamps and for the torch lamps: ms of mode 0 and of the default repair (picked lamps);
        // mean lamp light kept by mode 0, by the repair with a point lamp and by the repair
        // (every lamp traced). Pixels on which two runs of mode 0 differ and on which the old
        // tuning under MODE_REPAIR differs from mode 0 (picked); mean lamp light kept with the
        // inverse-square weights; pixels a torch leaves dark as a point lamp and repaired.
        std::array<std::array<double, 2>, 3> repair_ms{}, torch_ms{};
        std::array<std::array<double, 3>, 3> repair_kept{}, torch_kept{};
        std::array<std::array<std::size_t, 2>, 3> repair_differ{}, torch_dark{};
        std::array<double, 3> inverse_kept{};
"""),
  (r"""        const auto build_tlas = [&](Tlas& t, const Mat4& view, VkBuildAccelerationStructureFlagsKHR flags, bool doubled) {
""", r"""        // bbport (r41_lamp-shadows): more_mask: more instance mask bits (4: lamp rays hit)
        const auto build_tlas = [&](Tlas& t, const Mat4& view, VkBuildAccelerationStructureFlagsKHR flags, bool doubled,
                                    unsigned more_mask = 0) {
"""),
  (r"""                    inst.mask = doubled ? (copy ? 2 : 1) : 3;
""", r"""                    inst.mask = (doubled ? (copy ? 2 : 1) : 3) | more_mask;
"""),
  (r"""                const unsigned history_at = used;
                const auto run_lamps = [&](bool per_tile, unsigned pick = 0, unsigned frame = 0, int parity = -1) {
""", r"""                const unsigned history_at = used;
                // bbport (r41_lamp-shadows): more ways to run the pass. tune: with MODE_REPAIR:
                // its words go after the history block, their place into the mode word, and the
                // world's axes come from this camera's view matrix (as PointShadow::Flush does);
                // without it the mode word is 0, as before. inverse_square: the weights' curve.
                // engine_bias: the ray start offset the engine pushes (the tuning's, 0.03 without
                // one) in place of the lab's 0.02. torch: the torch lamps (written after the
                // tuning words by the block that uses them) in place of the street lamps.
                struct LampRun {
                    const Vulkan::LampShadowTune* tune = nullptr;
                    bool inverse_square = false;
                    bool engine_bias = false;
                    bool torch = false;
                };
                constexpr unsigned MaxTorches = 8;
                const unsigned tune_at = used + 32;
                const unsigned torch_at = tune_at + Vulkan::LampTuneWordCount;
                unsigned torch_count = 0;
                const auto run_lamps = [&](bool per_tile, unsigned pick = 0, unsigned frame = 0, int parity = -1,
                                           LampRun more = {}) {
                    if (more.tune) {
                        const auto tune_words =
                            Vulkan::LampTuneWords(*more.tune, more.inverse_square, 0.05f, views.view.m.data());
                        std::memcpy(reinterpret_cast<std::uint32_t*>(words) + tune_at, tune_words.data(),
                                    sizeof(tune_words));
                    }
"""),
  (r"""                    VkDescriptorBufferInfo data{lights.buffer, 0, (used + 32) * 4};
""", r"""                    VkDescriptorBufferInfo data{lights.buffer, 0,
                                                (used + 32 + Vulkan::LampTuneWordCount + MaxTorches * 24) * 4};
"""),
  (r"""                        if (parity >= 0) std::memcpy(&push.length, &history_at, 4);
""", r"""                        if (parity >= 0) std::memcpy(&push.length, &history_at, 4);
                        if (more.torch) { // bbport (r41_lamp-shadows)
                            push.first_light = torch_at + torch_count * 16;
                            push.count = torch_count;
                            push.rect = {0, 0, int(W), int(H)};
                        }
                        if (more.engine_bias) {
                            push.bias = more.tune ? more.tune->bias_m : 0.03f;
                        }
                        if (more.tune) { // MODE_REPAIR | place << 8
                            const unsigned mode = 16u | tune_at << 8;
                            std::memcpy(&push.thickness, &mode, 4);
                        }
"""),
  (r"""                    reuse_error[cam] = reuse_sum / double(exact.size());
""", r"""                    reuse_error[cam] = reuse_sum / double(exact.size());
                    // bbport (r41_lamp-shadows): MODE_REPAIR, on casters a lamp ray can hit. The
                    // lab's instances carry masks 1 to 3 and a lamp ray asks for 4 (vk_rt_shadow.cpp
                    // LampMask): no lamp ray of the runs above and below hits anything, and they
                    // stay as they are. For these runs the instances get the lamp bit as well.
                    //  - The old weights, a point lamp and no self skip under MODE_REPAIR give the
                    //    very numbers of mode 0 when every lamp is traced. With picked lamps the
                    //    second lamp depends on the order in which a workgroup's invocations list
                    //    its tiles, which is not fixed (two runs of mode 0 differ on some pixels),
                    //    so there the difference is bounded, not zero.
                    //  - A lamp with a radius never darkens a pixel that a point lamp lights (a
                    //    free rim ray only ever lights).
                    //  - The torch lamps: one beside each character (a capsule 1.8 m tall and 0.6 m
                    //    wide), 0.45 m from its side at 1.4 m, reaching 5 m, as a hand torch is
                    //    held: the caster is near the lamp, which is where a point lamp magnifies
                    //    it and where the rim rays are spent (the street lamps stand metres from
                    //    what they shadow). The same checks, and the body keeps most of its
                    //    shadow.
                    //  - What the default repair costs against mode 0 of this same shader (the
                    //    experiment bit's path; the shader before r41 is not in this build), with
                    //    the engine's ray start offset, runs taken in turn.
                    {
                        build_tlas(tlas, views.view, variant.flags, variant.doubled, 4);
                        {
                            auto* raw = reinterpret_cast<std::uint32_t*>(words);
                            torch_count = 0;
                            for (unsigned i = 0; i < n && torch_count < MaxTorches; ++i) {
                                if (!scene.meshes[i].skinned) continue;
                                const Vec3 world{scene.meshes[i].position.x + 0.75f, 1.4f, scene.meshes[i].position.z};
                                std::array<float, 16> light{};
                                for (int r = 0; r < 3; ++r)
                                    light[r] = views.view.at(r, 0) * world.x + views.view.at(r, 1) * world.y +
                                               views.view.at(r, 2) * world.z + views.view.at(r, 3);
                                light[3] = 1.0f / 25.0f;
                                light[4] = 1.0f; light[5] = 0.8f; light[6] = 0.6f;
                                std::memcpy(raw + torch_at + torch_count * 16, light.data(), sizeof(light));
                                ++torch_count;
                            }
                            for (unsigned t = 0; t < torch_count; ++t) {
                                const std::array<std::uint32_t, 8> row{0u, 0u, unsigned(W), unsigned(H),
                                                                       torch_at + t * 16, 1u, 0u, 0u};
                                std::memcpy(raw + torch_at + torch_count * 16 + t * 8, row.data(), sizeof(row));
                            }
                        }
                        if (torch_count == 0) {
                            std::fprintf(stderr, "the lab scene has no character for a torch lamp\n");
                            return 1;
                        }
                        Vulkan::LampShadowTune same;
                        same.weights = false;
                        same.radius_m = 0.0f;
                        same.self_m = 0.0f;
                        const auto differing = [&](unsigned pick, const Vulkan::LampShadowTune* tune, bool torch) {
                            run_lamps(false, pick, 0, -1, {.torch = torch});
                            const auto before = lamp_values();
                            run_lamps(false, pick, 0, -1, {.tune = tune, .torch = torch});
                            const auto after = lamp_values();
                            std::size_t differ = 0;
                            for (std::size_t k = 0; k < before.size(); ++k) differ += before[k] != after[k] ? 1 : 0;
                            return differ;
                        };
                        for (const bool torch : {false, true}) {
                            if (const std::size_t differ = differing(0, &same, torch); differ != 0) {
                                std::fprintf(stderr, "every lamp traced: lamp repair with the old tuning differs from "
                                                     "mode 0 on %zu pixels (camera %zu, %s lamps)\n",
                                             differ, cam, torch ? "torch" : "street");
                                return 1;
                            }
                        }
                        const std::size_t noise = differing(1, nullptr, false);
                        const std::size_t picked = differing(1, &same, false);
                        if (picked > 4 * noise + 64) {
                            std::fprintf(stderr, "picked lamps: lamp repair with the old tuning differs from mode 0 on "
                                                 "%zu pixels, two runs of mode 0 on %zu (camera %zu)\n", picked, noise, cam);
                            return 1;
                        }
                        const auto kept = [](const std::vector<float>& values) {
                            double sum = 0;
                            for (const float v : values) sum += v;
                            return sum / double(values.size());
                        };
                        Vulkan::LampShadowTune repaired, point;
                        point.radius_m = 0.0f;
                        for (const bool torch : {false, true}) {
                            run_lamps(false, 0, 0, -1, {.torch = torch});
                            const double kept_before = kept(lamp_values());
                            run_lamps(false, 0, 0, -1, {.tune = &point, .torch = torch});
                            const auto with_point = lamp_values();
                            run_lamps(false, 0, 0, -1, {.tune = &repaired, .torch = torch});
                            const auto with_radius = lamp_values();
                            std::size_t darker = 0, dark_point = 0, dark_radius = 0;
                            for (std::size_t k = 0; k < with_point.size(); ++k) {
                                darker += with_radius[k] < with_point[k] ? 1 : 0;
                                dark_point += with_point[k] < 0.25f ? 1 : 0;
                                dark_radius += with_radius[k] < 0.25f ? 1 : 0;
                            }
                            if (darker != 0) {
                                std::fprintf(stderr, "a lamp with a radius left %zu pixels darker than a point lamp "
                                                     "(camera %zu, %s lamps)\n", darker, cam, torch ? "torch" : "street");
                                return 1;
                            }
                            (torch ? torch_kept : repair_kept)[cam] = {kept_before, kept(with_point), kept(with_radius)};
                            if (torch) {
                                torch_dark[cam] = {dark_point, dark_radius};
                                if (dark_radius * 2 < dark_point) {
                                    std::fprintf(stderr, "torch lamps: the default radius left %zu dark pixels of the "
                                                         "point lamp's %zu (camera %zu)\n", dark_radius, dark_point, cam);
                                    return 1;
                                }
                            }
                            std::vector<double> plain, fixed;
                            for (int i = 0; i < 40; ++i) {
                                plain.push_back(run_lamps(false, 1, unsigned(i), -1, {.engine_bias = true, .torch = torch}));
                                fixed.push_back(run_lamps(false, 1, unsigned(i), -1,
                                                          {.tune = &repaired, .engine_bias = true, .torch = torch}));
                            }
                            // The fastest run of each: this lab's lamp pass times jump between runs
                            // by several times, and the median moves with them.
                            (torch ? torch_ms : repair_ms)[cam] = {*std::min_element(plain.begin(), plain.end()),
                                                                   *std::min_element(fixed.begin(), fixed.end())};
                        }
                        // The inverse-square weights (startup_local_inverse_square): they run and
                        // give a ratio.
                        run_lamps(false, 0, 0, -1, {.tune = &repaired, .inverse_square = true});
                        const auto inverse = lamp_values();
                        for (const float v : inverse) {
                            if (!(v >= 0.0f && v <= 1.0001f)) {
                                std::fprintf(stderr, "inverse-square weights: a pixel holds %g (camera %zu)\n", double(v), cam);
                                return 1;
                            }
                        }
                        inverse_kept[cam] = kept(inverse);
                        repair_differ[cam] = {noise, picked};
                        build_tlas(tlas, views.view, variant.flags, variant.doubled); // as it was
                    }
"""),
  (r"""                    reuse_ms[0], reuse_ms[1], reuse_ms[2], reuse_error[0], reuse_error[1], reuse_error[2]);
""", r"""                    reuse_ms[0], reuse_ms[1], reuse_ms[2], reuse_error[0], reuse_error[1], reuse_error[2]);
        // bbport (r41_lamp-shadows)
        std::printf("Lamps that hit (instances with the lamp bit), picked, repaired (r41, default tuning): %.3f %.3f "
                    "%.3f ms against %.3f %.3f %.3f ms of mode 0 of this shader (the experiment bit's path; the "
                    "fastest of 40 runs taken in turn, the engine's ray start offset); mean lamp light kept with "
                    "every lamp traced: mode 0 "
                    "%.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired %.4f %.4f %.4f, repaired "
                    "with inverse-square weights %.4f %.4f %.4f; the old "
                    "tuning under MODE_REPAIR gave mode 0's numbers with every lamp traced, and with picked lamps "
                    "differed on %zu %zu %zu pixels where two runs of mode 0 differed on %zu %zu %zu\n",
                    repair_ms[0][1], repair_ms[1][1], repair_ms[2][1], repair_ms[0][0], repair_ms[1][0],
                    repair_ms[2][0], repair_kept[0][0], repair_kept[1][0], repair_kept[2][0], repair_kept[0][1],
                    repair_kept[1][1], repair_kept[2][1], repair_kept[0][2], repair_kept[1][2], repair_kept[2][2],
                    inverse_kept[0], inverse_kept[1], inverse_kept[2],
                    repair_differ[0][1], repair_differ[1][1], repair_differ[2][1], repair_differ[0][0],
                    repair_differ[1][0], repair_differ[2][0]);
        std::printf("Torch lamps (0.45 m from a character's side, reach 5 m), picked, repaired: %.3f %.3f %.3f ms "
                    "against %.3f %.3f %.3f ms of mode 0 of this shader; mean lamp light kept with every lamp traced: "
                    "mode 0 %.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired %.4f %.4f %.4f; dark "
                    "pixels repaired %zu %zu %zu, with a point lamp %zu %zu %zu\n",
                    torch_ms[0][1], torch_ms[1][1], torch_ms[2][1], torch_ms[0][0], torch_ms[1][0], torch_ms[2][0],
                    torch_kept[0][0], torch_kept[1][0], torch_kept[2][0], torch_kept[0][1], torch_kept[1][1],
                    torch_kept[2][1], torch_kept[0][2], torch_kept[1][2], torch_kept[2][2], torch_dark[0][1],
                    torch_dark[1][1], torch_dark[2][1], torch_dark[0][0], torch_dark[1][0], torch_dark[2][0]);
"""),
 ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the shader and the pass agree on the mode
    bit and on the number of tuning words, the bit has one definition and is not one of the
    master switch's bits."""
    ok = True
    comp = texts[B + "host_shaders/point_shadow_ray.comp"]
    cpp = texts[R + "vk_point_shadow.cpp"]
    if "const uint MODE_REPAIR = 16u;" not in comp or "constexpr u32 ModeRepair = 16;" not in cpp:
        print("the shader and the pass do not agree on MODE_REPAIR")
        ok = False
    read = len(set(re.findall(r"word\(at \+ (\d+)u\)", comp[comp.index("void loadTune()"):comp.index("vec3 stepColour")])))
    if read != 15 or "LampTuneWordCount = 16;" not in TUNE_H or TUNE_H.count("            bits(") != 15:
        print("the shader reads %d tuning floats, the header gives 15 and a flag word" % read)
        ok = False
    if comp.count("ray(from, reach, L)") != 1 or comp.count("ray(rim_from[j], reach, ") != 1 or \
            comp.count("rayQueryInitializeEXT(") != 1:
        print("the shader should call ray() once for a centre and once for the rim, and start its query in ray()")
        ok = False
    if "visibility(origin, reach" in comp:
        print("a call of the old visibility() is left in the shader")
        ok = False
    header = texts[R + "vk_rt_shadow.h"]
    if header.count("LampRepairOffBit = %dull;" % VALUE) != 1:
        print("LampRepairOffBit is not defined exactly once as %d" % VALUE)
        ok = False
    settings = texts[S + "bbport_settings.h"]
    bits = re.search(r"PreviousPathsBits\[\] = \{([^}]*)\}", settings)
    if not bits or BIT in [int(x) for x in re.findall(r"\d+", bits.group(1))]:
        print("bit %d is in PreviousPathsBits (or the list was not found)" % BIT)
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r41_lamp-shadows.py check|apply|revert   (R41_ROOT names another tree)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
