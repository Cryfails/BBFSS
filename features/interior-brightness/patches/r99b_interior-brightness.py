# r99b_interior-brightness: FEATURE patch (lamp work, "dim interiors and auto exposure"), on top of
# r99_interior-exposure (apply r99 first; revert this one before r99). Off by default behind
# BB_INTERIOR_EXPOSURE, like r99.
#
# .fixed (adversarial review 2026-11-15): (a) a reading metered without a usable camera (no open
# distance pushed) no longer eases the open share down (it held only depth-1 sky, so it could start
# a lift outdoors); each slot keeps the distance it was metered with and the log prints that one;
# (b) comments and README state the exact open rule (depth 1 or OPEN_M or farther) instead of
# claiming that streets count as open, which nothing has measured; (c) the periodic log line puts
# applied/wanted/metered/open first and stays under the slot runner's 300-character evidence cut;
# (d) r99's comment above the call ("floor") is replaced with the call.
#
# Why: r99 (built and slot-tested 2026-11-15 20:50) lifts the library (+0.5 EV level, +0.9 EV
# looking up) and leaves the graveyard alone, but (1) its "indoor" test never works: it counts sky
# only at depth 1, and the game's sky dome is drawn geometry (no measured view had a single sample
# at depth 1; only loading frames do), so it is a pure luminance floor that cannot tell a dark
# street from a room (the dark alley with the BB PC Remaster mod: +1.0 EV); (2) its floor 0.02
# does nothing in the dream house and church-candles, two of the three rooms the owner named, with
# or without the mod; (3) it has no notion of walking in or out.
#
# What r99b changes:
#  1. An "open view" share replaces the dead sky test: a sample is open at depth 1 OR at a view
#     depth of BB_INTERIOR_EXPOSURE_OPEN_M (80 m) or more, from the camera's projection (as
#     camera_motion.comp turns depth into view depth). The meter also counts samples at 20/40/80/
#     160 m and the log line prints those shares, so the first run measures how open real views
#     are (the numbers that set the open distance and the 3 %/15 % edges).
#  2. The open share is eased: up over 0.15 s (an open view stops the lift at once), down over
#     1.5 s (a closed dark view is lifted after about 2-5 s: walking into a room, the eye adapts).
#     It starts at 1 (open) after loading.
#  3. New defaults: target 0.05, strength 0.5 (close half the gap in stops), cap 1.5 EV: the
#     library about +0.9 EV (mod: +1.5), church-candles with the mod +1.0, the dream house with the
#     mod +0.37, without it 0; rooms keep their order of brightness (not flattened to one level).
#     r99's rule: TARGET=0.02 STRENGTH=1 OPEN_M=0.
#
# Files (all the feature's own; whole-file swaps are taken only when the file is byte for byte
# r99's version, sha256 checked; revert writes r99's version back from this script):
#   engine/gpu/shim/bbport_interior_exposure.h      rule, knobs (OPEN_M), StepOpen, OpenShare
#   host_shaders/interior_meter.comp                 distance counts; Push 32 -> 48 bytes
#   renderer_vulkan/vk_interior_exposure.h/.cpp      Meter takes the CameraMotion; eased open share;
#                                                    the r99b log lines
#   engine/tests/test_interior_exposure.cpp          new numbers, the open gate, walking in and out
#   renderer_vulkan/vk_temporal_upscaler.cpp         r99's call line gains camera_motion (1 line -> 2)
#   README.md                                        r99's section replaced by r99b's
# No CMake or build.sh change (same shader build, same test target).
#
# Off: Meter returns at its first line (the mode test) before it touches the camera, so passing
# the CameraMotion by reference costs nothing; Scale() stays exactly 1.0f; no pipeline, buffer,
# dispatch or line. On: the same single 256-thread dispatch as r99 plus one division and four
# compares per sample (2304 samples) and 4 KB more shared memory; estimate still 0.01-0.03 ms at
# 1080p internal, NOT MEASURED. Memory: unchanged (a 128-byte host buffer, one pipeline).
#
# Use: python -I -X utf8 r99b_interior-brightness.py check | apply | revert (root from R99B_ROOT,
# else <tree>). Files keep CRLF. Originals are also copied to r99b_backup/ next to this script.
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r99b_backup")
ROOT = os.environ.get("R99B_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

# path -> (r99's text, r99b's text); both LF here, CRLF on disk.
SWAPS = {
    "engine/gpu/shim/bbport_interior_exposure.h": (r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r99_interior-exposure): a brighten-only exposure floor for dark interiors, part of the
// lamp work. A meter (Vulkan::InteriorExposure::Meter, host_shaders/interior_meter.comp) takes
// GridX x GridY samples of the HDR scene colour at the upscaler, before the tone curve: the
// log-average of their Rec.709 luminance, each clamped to [LumMin, LumMax], leaving out the sky
// (depth 1, the clear value), and the sky's share of the samples. Want() turns one reading into a
// lift in stops; Step() eases the applied lift toward it in real time; the lift, as a factor,
// multiplies the GT7/ACES exposure pushed to the game's final composite (Pipeline::BindResources).
// The game's own curve (graphics_tonemapper=original) and the HDR curve extension take no
// exposure, so with them it changes nothing.
//
// The rule (Want): gap = log2(target / metered), at least 0; wanted = min(max_ev, strength * gap)
// * indoor, indoor = 1 - smoothstep(SkyOpen, SkyGone, sky share). So a scene metered at or above
// the target, or one with SkyGone or more sky among the samples, gets no lift, and the lift never
// darkens. A reading metered below BlackFrame (a black or fading frame) or without a number keeps
// the lift as it is. Pure: no Vulkan, no settings; tested by tests/test_interior_exposure.cpp.
//
// Knobs (environment, read once by Knobs()): BB_INTERIOR_EXPOSURE 1 on, 2 SHOW (the Show* values
// for every number not set), anything else off; BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _MAX_EV.
// A missing, unreadable or non-finite number takes the default, then the range.
//
// It is a floor on dark views, not an indoor test: the sky share only removes the lift where the
// samples see sky at depth 1. Measured 2026-11-15 (hero light off, no view with any such sky): the
// library 0.014 (looking up 0.011), the dream house 0.055, the dark alley 0.025 without the
// Remaster mod (so the default target 0.02 leaves that street alone) and 0.0097 with it (lifted).

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>

namespace BbInteriorExposure {

inline constexpr float DefaultTarget = 0.02f;  ///< log-average luminance aimed at (the floor)
inline constexpr float DefaultStrength = 1.0f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 1.5f;    ///< the largest lift, stops
inline constexpr float ShowTarget = 0.15f;     ///< BB_INTERIOR_EXPOSURE=2 (test): exaggerated
inline constexpr float ShowStrength = 1.0f;
inline constexpr float ShowMaxEv = 3.0f;
inline constexpr float TargetMin = 0.005f, TargetMax = 1.0f;
inline constexpr float MaxEvLimit = 3.0f;
inline constexpr float SkyOpen = 0.03f;    ///< sky share of the samples where the lift starts to fade
inline constexpr float SkyGone = 0.15f;    ///< sky share from which there is no lift
inline constexpr float BlackFrame = 4e-4f; ///< metered below this: a black or fading frame, hold
inline constexpr float RiseSeconds = 1.0f; ///< time constant while the lift grows
inline constexpr float FallSeconds = 0.4f; ///< time constant while it shrinks
inline constexpr float MaxStep = 0.25f;    ///< s: the longest step one Step takes
inline constexpr unsigned GridX = 64, GridY = 36; ///< the meter's samples across, down
inline constexpr float LumMin = 1e-4f, LumMax = 64.0f; ///< each sample's luminance clamp (pushed)

enum Mode : int { Off = 0, On = 1, Show = 2 };

struct Config {
    int mode = Off;
    float target = DefaultTarget;
    float strength = DefaultStrength;
    float max_ev = DefaultMaxEv;
};

inline float Number(const char* text, float fallback, float lo, float hi) {
    float value = fallback;
    if (text && *text) {
        char* end = nullptr;
        const float read = std::strtof(text, &end);
        if (end != text && *end == '\0' && std::isfinite(read)) {
            value = read;
        }
    }
    return std::clamp(value, lo, hi);
}

inline Config Parse(const char* mode, const char* target, const char* strength, const char* max_ev) {
    Config c;
    if (mode && mode[0] && !mode[1]) {
        c.mode = mode[0] == '1' ? On : mode[0] == '2' ? Show : Off;
    }
    const bool show = c.mode == Show;
    c.target = Number(target, show ? ShowTarget : DefaultTarget, TargetMin, TargetMax);
    c.strength = Number(strength, show ? ShowStrength : DefaultStrength, 0.0f, 1.0f);
    c.max_ev = Number(max_ev, show ? ShowMaxEv : DefaultMaxEv, 0.0f, MaxEvLimit);
    return c;
}

/// The knobs, read from the environment at the first call.
inline const Config& Knobs() {
    static const Config config = Parse(
        std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
        std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"));
    return config;
}

/// One meter reading (interior_meter.comp's slot): the sum of log2 luminance over the ground
/// samples, their number, the sky samples, and all samples.
struct Reading {
    float log_sum = 0, samples = 0, sky = 0, total = 0;
};

struct Lift {
    bool valid = false;   ///< false: hold the applied lift
    float metered = 0;    ///< log-average luminance of the ground samples (0 without any)
    float sky_share = 0;  ///< sky samples / all samples
    float indoor = 0;     ///< 1 - smoothstep(SkyOpen, SkyGone, sky_share)
    float wanted_ev = 0;  ///< the lift this reading asks for, stops, 0..max_ev
};

inline float Smoothstep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

inline Lift Want(const Config& c, const Reading& r) {
    Lift l;
    if (!(r.total > 0.0f) || !std::isfinite(r.log_sum) || !std::isfinite(r.samples) ||
        !std::isfinite(r.sky) || !std::isfinite(r.total) || r.samples < 0.0f || r.sky < 0.0f) {
        return l;
    }
    l.sky_share = std::clamp(r.sky / r.total, 0.0f, 1.0f);
    l.indoor = 1.0f - Smoothstep(SkyOpen, SkyGone, l.sky_share);
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open sky: no lift
        return l;
    }
    if (r.samples < 1.0f || !(l.metered >= BlackFrame)) {
        return l; // nothing to meter, or a black frame: hold
    }
    l.valid = true;
    const float gap = std::max(0.0f, std::log2(c.target / l.metered));
    l.wanted_ev = std::min(c.max_ev, c.strength * gap) * l.indoor;
    return l;
}

/// The applied lift after `dt` seconds (clamped to 0..MaxStep; not a number: 0) of easing toward
/// `wanted`: exponential, RiseSeconds while it grows, FallSeconds while it shrinks. Never passes
/// `wanted`.
inline float Step(float applied, float wanted, float dt) {
    dt = std::isfinite(dt) ? std::clamp(dt, 0.0f, MaxStep) : 0.0f;
    const float tau = wanted > applied ? RiseSeconds : FallSeconds;
    return applied + (wanted - applied) * (1.0f - std::exp(-dt / tau));
}

/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 unless the knob is on: only
/// Vulkan::InteriorExposure::Meter writes it.
inline std::atomic<float> applied_scale{1.0f};
inline float Scale() {
    return applied_scale.load(std::memory_order_relaxed);
}

} // namespace BbInteriorExposure
''', r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r99_interior-exposure, r99b_interior-brightness): a brighten-only exposure lift for dark
// interiors, part of the lamp work. A meter (Vulkan::InteriorExposure::Meter,
// host_shaders/interior_meter.comp) takes GridX x GridY samples of the HDR scene colour and depth
// at the upscaler, before the tone curve: the log-average of their Rec.709 luminance, each clamped
// to [LumMin, LumMax], leaving out the sky (depth 1, the clear value), and how many samples are
// "open": at depth 1, or farther than the open distance (BB_INTERIOR_EXPOSURE_OPEN_M, view depth
// from the camera's projection). Want() turns one reading into a lift in stops; Step() eases the
// applied lift toward it in real time; the lift, as a factor, multiplies the GT7/ACES exposure
// pushed to the game's final composite (Pipeline::BindResources). The game's own curve
// (graphics_tonemapper=original) and the HDR curve extension take no exposure, so with them it
// changes nothing.
//
// The rule (Want): gap = log2(target / metered), at least 0; wanted = min(max_ev, strength * gap)
// * indoor, indoor = 1 - smoothstep(SkyOpen, SkyGone, eased open share). The open share is eased
// in real time (StepOpen): it follows a rise within OpenRiseSeconds and a fall over
// OpenFallSeconds, so a view with SkyGone or more open samples stops the lift almost at once,
// while the lift comes only after a few seconds of a view with fewer (walking into a room). A
// reading metered without the open distance (no usable camera) does not move the eased share. So
// a scene metered at or above the target, or one that showed SkyGone or more open samples lately,
// gets no lift, and the lift never darkens. Whether a dark street shows that many samples at the
// open distance is not known: the log line measures it. A reading metered below BlackFrame (a
// black or fading frame) or without a number keeps the lift as it is. Pure: no Vulkan, no
// settings; tested by tests/test_interior_exposure.cpp.
//
// Knobs (environment, read once by Knobs()): BB_INTERIOR_EXPOSURE 1 on, 2 SHOW (the Show* values
// for every number not set), anything else off; BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _MAX_EV,
// _OPEN_M (0: only depth 1 counts as open, r99's rule). A missing, unreadable or non-finite number
// takes the default, then the range. r99's exact behaviour: TARGET=0.02 STRENGTH=1 OPEN_M=0 (the
// open share is then eased too).
//
// Measured 2026-11-15 (hero light off, log-average before the tone curve; no measured view had any
// sample at depth 1): the library 0.014 (looking up 0.011; 0.0055 with the BB PC Remaster mod),
// church-candles 0.040 (0.012 with the mod), the dream house 0.052 (0.030 with the mod, hero light
// kept), the dark alley 0.025 (0.0097 with the mod). The defaults close half the gap in stops to
// 0.05: the library rises about +0.9 EV (+1.5 EV, the cap, with the mod), church-candles with the
// mod about +1.0 EV, the dream house with the mod about +0.37 EV, the dream house without it 0, so
// rooms stay in the same order of brightness. Outdoors relies on the open share: how many samples
// open views have is what the r99b log line measures (not known when this was written).

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>

namespace BbInteriorExposure {

inline constexpr float DefaultTarget = 0.05f;  ///< log-average luminance aimed at
inline constexpr float DefaultStrength = 0.5f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 1.5f;    ///< the largest lift, stops
inline constexpr float DefaultOpenMeters = 80.0f; ///< view depth from which a sample is open
inline constexpr float ShowTarget = 0.15f;     ///< BB_INTERIOR_EXPOSURE=2 (test): exaggerated
inline constexpr float ShowStrength = 1.0f;
inline constexpr float ShowMaxEv = 3.0f;
inline constexpr float TargetMin = 0.005f, TargetMax = 1.0f;
inline constexpr float MaxEvLimit = 3.0f;
inline constexpr float OpenMetersMax = 1000.0f; ///< BB_INTERIOR_EXPOSURE_OPEN_M range 0..this
inline constexpr float SkyOpen = 0.03f;    ///< eased open share where the lift starts to fade
inline constexpr float SkyGone = 0.15f;    ///< eased open share from which there is no lift
inline constexpr float BlackFrame = 4e-4f; ///< metered below this: a black or fading frame, hold
inline constexpr float RiseSeconds = 1.0f; ///< time constant while the lift grows
inline constexpr float FallSeconds = 0.4f; ///< time constant while it shrinks
inline constexpr float OpenRiseSeconds = 0.15f; ///< time constant while the open share grows
inline constexpr float OpenFallSeconds = 1.5f;  ///< time constant while it shrinks
inline constexpr float OpenStart = 1.0f;   ///< the eased open share before the first reading
inline constexpr float MaxStep = 0.25f;    ///< s: the longest step one Step takes
inline constexpr unsigned GridX = 64, GridY = 36; ///< the meter's samples across, down
inline constexpr float LumMin = 1e-4f, LumMax = 64.0f; ///< each sample's luminance clamp (pushed)

enum Mode : int { Off = 0, On = 1, Show = 2 };

struct Config {
    int mode = Off;
    float target = DefaultTarget;
    float strength = DefaultStrength;
    float max_ev = DefaultMaxEv;
    float open_m = DefaultOpenMeters; ///< 0: only depth 1 is open
};

inline float Number(const char* text, float fallback, float lo, float hi) {
    float value = fallback;
    if (text && *text) {
        char* end = nullptr;
        const float read = std::strtof(text, &end);
        if (end != text && *end == '\0' && std::isfinite(read)) {
            value = read;
        }
    }
    return std::clamp(value, lo, hi);
}

inline Config Parse(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m = nullptr) {
    Config c;
    if (mode && mode[0] && !mode[1]) {
        c.mode = mode[0] == '1' ? On : mode[0] == '2' ? Show : Off;
    }
    const bool show = c.mode == Show;
    c.target = Number(target, show ? ShowTarget : DefaultTarget, TargetMin, TargetMax);
    c.strength = Number(strength, show ? ShowStrength : DefaultStrength, 0.0f, 1.0f);
    c.max_ev = Number(max_ev, show ? ShowMaxEv : DefaultMaxEv, 0.0f, MaxEvLimit);
    c.open_m = Number(open_m, DefaultOpenMeters, 0.0f, OpenMetersMax);
    return c;
}

/// The knobs, read from the environment at the first call.
inline const Config& Knobs() {
    static const Config config = Parse(
        std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
        std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"),
        std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"));
    return config;
}

/// One meter reading (interior_meter.comp's slot): the sum of log2 luminance over the ground
/// samples, their number, the sky samples (depth 1), all samples, and the ground samples whose
/// view depth is at least a quarter, half, one and two times the open distance.
struct Reading {
    float log_sum = 0, samples = 0, sky = 0, total = 0;
    float quarter = 0, halfway = 0, open = 0, twice = 0;
};

struct Lift {
    bool valid = false;   ///< false: hold the applied lift
    float metered = 0;    ///< log-average luminance of the ground samples (0 without any)
    float sky_share = 0;  ///< sky samples / all samples
    float indoor = 0;     ///< 1 - smoothstep(SkyOpen, SkyGone, the eased open share)
    float wanted_ev = 0;  ///< the lift this reading asks for, stops, 0..max_ev
};

inline float Smoothstep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The reading's numbers are usable.
inline bool Usable(const Reading& r) {
    return r.total > 0.0f && std::isfinite(r.log_sum) && std::isfinite(r.samples) &&
           std::isfinite(r.sky) && std::isfinite(r.total) && std::isfinite(r.open) &&
           r.samples >= 0.0f && r.sky >= 0.0f && r.open >= 0.0f;
}

/// The share of open samples (depth 1, or at least the open distance away) in one reading; 0 for
/// an unusable one.
inline float OpenShare(const Reading& r) {
    return Usable(r) ? std::clamp((r.sky + r.open) / r.total, 0.0f, 1.0f) : 0.0f;
}

/// `open_eased`: the open share after easing (StepOpen); the reading's own share when not eased.
inline Lift Want(const Config& c, const Reading& r, float open_eased) {
    Lift l;
    if (!Usable(r)) {
        return l;
    }
    l.sky_share = std::clamp(r.sky / r.total, 0.0f, 1.0f);
    l.indoor = 1.0f - Smoothstep(SkyOpen, SkyGone, std::isfinite(open_eased) ? open_eased : 1.0f);
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open: no lift
        return l;
    }
    if (r.samples < 1.0f || !(l.metered >= BlackFrame)) {
        return l; // nothing to meter, or a black frame: hold
    }
    l.valid = true;
    const float gap = std::max(0.0f, std::log2(c.target / l.metered));
    l.wanted_ev = std::min(c.max_ev, c.strength * gap) * l.indoor;
    return l;
}

inline Lift Want(const Config& c, const Reading& r) {
    return Want(c, r, OpenShare(r));
}

inline float Ease(float value, float toward, float dt, float rise, float fall) {
    dt = std::isfinite(dt) ? std::clamp(dt, 0.0f, MaxStep) : 0.0f;
    const float tau = toward > value ? rise : fall;
    return value + (toward - value) * (1.0f - std::exp(-dt / tau));
}

/// The applied lift after `dt` seconds (clamped to 0..MaxStep; not a number: 0) of easing toward
/// `wanted`: exponential, RiseSeconds while it grows, FallSeconds while it shrinks. Never passes
/// `wanted`.
inline float Step(float applied, float wanted, float dt) {
    return Ease(applied, wanted, dt, RiseSeconds, FallSeconds);
}

/// The eased open share after `dt` seconds toward `share`: OpenRiseSeconds while it grows (an
/// open view stops the lift almost at once), OpenFallSeconds while it shrinks (a closed view
/// brings the lift after a few seconds).
inline float StepOpen(float eased, float share, float dt) {
    return Ease(eased, share, dt, OpenRiseSeconds, OpenFallSeconds);
}

/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 unless the knob is on: only
/// Vulkan::InteriorExposure::Meter writes it.
inline std::atomic<float> applied_scale{1.0f};
inline float Scale() {
    return applied_scale.load(std::memory_order_relaxed);
}

} // namespace BbInteriorExposure
'''),
    H + "interior_meter.comp": (r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure): the interior exposure meter (vk_interior_exposure.cpp). One group
// of 256 threads takes grid.x * grid.y samples at cell centres over the render size: a sample
// whose depth is 1 (the clear value: sky) is counted apart, every other one adds log2 of its
// Rec.709 luminance clamped to [lum_min, lum_max] (pushed from bbport_interior_exposure.h's
// LumMin, LumMax; one that is not a number is left out). Thread 0
// writes the sums and the frame number into one slot of a small host buffer; the CPU reads it once
// the GPU has passed that frame (gpu/shim/bbport_interior_exposure.h has the rule).
#version 450
#extension GL_EXT_samplerless_texture_functions : require

layout(local_size_x = 256) in;

layout(binding = 0, rgba16f) uniform readonly image2D scene_img; // HDR scene, before the tone curve
layout(binding = 1) uniform texture2D depth_tex;                 // D32, 1 = sky

struct Slot {
    float log_sum; // sum of log2 luminance over the ground samples
    float samples; // ground samples
    float sky;     // sky samples
    float total;   // all samples
    uint frame;    // the frame number pushed with this dispatch
    uint pad0;
    uint pad1;
    uint pad2;
};
layout(binding = 2, std430) writeonly buffer Slots {
    Slot slots[];
};

layout(push_constant) uniform Push {
    uvec2 size; // render pixels
    uvec2 grid; // samples across, down
    uint slot;
    uint frame;
    float lum_min; // each sample's luminance clamp
    float lum_max;
};

shared float s_log[256];
shared float s_ground[256];
shared float s_sky[256];

void main() {
    const uint t = gl_LocalInvocationIndex;
    const uint count = grid.x * grid.y;
    float log_sum = 0.0;
    float ground = 0.0;
    float sky = 0.0;
    for (uint i = t; i < count; i += 256u) {
        const uvec2 cell = uvec2(i % grid.x, i / grid.x);
        const ivec2 p = ivec2((vec2(cell) + 0.5) * vec2(size) / vec2(grid));
        if (texelFetch(depth_tex, p, 0).r >= 1.0) {
            sky += 1.0;
            continue;
        }
        const float y = dot(imageLoad(scene_img, p).rgb, vec3(0.2126, 0.7152, 0.0722));
        if (isnan(y) || isinf(y)) {
            continue;
        }
        log_sum += log2(clamp(y, lum_min, lum_max));
        ground += 1.0;
    }
    s_log[t] = log_sum;
    s_ground[t] = ground;
    s_sky[t] = sky;
    barrier();
    for (uint stride = 128u; stride > 0u; stride >>= 1u) {
        if (t < stride) {
            s_log[t] += s_log[t + stride];
            s_ground[t] += s_ground[t + stride];
            s_sky[t] += s_sky[t + stride];
        }
        barrier();
    }
    if (t == 0u) {
        slots[slot] = Slot(s_log[0], s_ground[0], s_sky[0], float(count), frame, 0u, 0u, 0u);
    }
}
''', r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure, r99b_interior-brightness): the interior exposure meter
// (vk_interior_exposure.cpp). One group of 256 threads takes grid.x * grid.y samples at cell
// centres over the render size: a sample whose depth is 1 (the clear value: sky) is counted apart,
// every other one adds log2 of its Rec.709 luminance clamped to [lum_min, lum_max] (pushed from
// bbport_interior_exposure.h's LumMin, LumMax; one that is not a number is left out) and, when
// open_m > 0, is counted at view depths of at least a quarter, half, one and two times open_m
// (view depth z = z_offset / (depth - z_scale), the projection's z terms as camera_motion.comp
// takes them). Thread 0 writes the sums and the frame number into one slot of a small host
// buffer; the CPU reads it once the GPU has passed that frame (gpu/shim/bbport_interior_exposure.h
// has the rule).
#version 450
#extension GL_EXT_samplerless_texture_functions : require

layout(local_size_x = 256) in;

layout(binding = 0, rgba16f) uniform readonly image2D scene_img; // HDR scene, before the tone curve
layout(binding = 1) uniform texture2D depth_tex;                 // D32, 1 = sky

struct Slot {
    float log_sum; // sum of log2 luminance over the ground samples
    float samples; // ground samples
    float sky;     // sky samples
    float quarter; // ground samples at least open_m / 4 away
    uint frame;    // the frame number pushed with this dispatch
    float halfway; // ground samples at least open_m / 2 away
    float open;    // ground samples at least open_m away
    float twice;   // ground samples at least 2 * open_m away
};
layout(binding = 2, std430) writeonly buffer Slots {
    Slot slots[];
};

layout(push_constant) uniform Push {
    uvec2 size; // render pixels
    uvec2 grid; // samples across, down
    uint slot;
    uint frame;
    float lum_min; // each sample's luminance clamp
    float lum_max;
    float z_scale;  // depth = z_scale + z_offset / z
    float z_offset;
    float open_m;   // 0: no distance counts
    float pad0;
};

shared float s_log[256];
shared float s_ground[256];
shared float s_sky[256];
shared vec4 s_far[256];

void main() {
    const uint t = gl_LocalInvocationIndex;
    const uint count = grid.x * grid.y;
    float log_sum = 0.0;
    float ground = 0.0;
    float sky = 0.0;
    vec4 far = vec4(0.0);
    const vec4 reach = vec4(0.25, 0.5, 1.0, 2.0) * open_m;
    for (uint i = t; i < count; i += 256u) {
        const uvec2 cell = uvec2(i % grid.x, i / grid.x);
        const ivec2 p = ivec2((vec2(cell) + 0.5) * vec2(size) / vec2(grid));
        const float depth = texelFetch(depth_tex, p, 0).r;
        if (depth >= 1.0) {
            sky += 1.0;
            continue;
        }
        const float y = dot(imageLoad(scene_img, p).rgb, vec3(0.2126, 0.7152, 0.0722));
        if (isnan(y) || isinf(y)) {
            continue;
        }
        log_sum += log2(clamp(y, lum_min, lum_max));
        ground += 1.0;
        if (open_m > 0.0) {
            const float z = z_offset / min(depth - z_scale, -1e-8);
            far += vec4(greaterThanEqual(vec4(z), reach));
        }
    }
    s_log[t] = log_sum;
    s_ground[t] = ground;
    s_sky[t] = sky;
    s_far[t] = far;
    barrier();
    for (uint stride = 128u; stride > 0u; stride >>= 1u) {
        if (t < stride) {
            s_log[t] += s_log[t + stride];
            s_ground[t] += s_ground[t + stride];
            s_sky[t] += s_sky[t + stride];
            s_far[t] += s_far[t + stride];
        }
        barrier();
    }
    if (t == 0u) {
        slots[slot] = Slot(s_log[0], s_ground[0], s_sky[0], s_far[0].x, frame, s_far[0].y,
                           s_far[0].z, s_far[0].w);
    }
}
'''),
    R + "vk_interior_exposure.h": (r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class Instance;
class Scheduler;

/// bbport (r99_interior-exposure): the meter of the interior exposure floor
/// (gpu/shim/bbport_interior_exposure.h has the rule and the knobs).
namespace InteriorExposure {

/// Called by TemporalUpscaler::Run with the frame's HDR scene colour (`color`: rgba16f, GENERAL,
/// storage) and depth (`depth`: GENERAL, sampled) of w x h render pixels, before the upscaler
/// reads them. Reads the newest earlier reading the GPU has finished, eases the lift and stores
/// its factor (BbInteriorExposure::Scale), then records this frame's meter dispatch. With
/// BB_INTERIOR_EXPOSURE not 1 or 2 it returns at once: nothing is made, recorded or printed.
void Meter(const Instance& instance, Scheduler& scheduler, vk::ImageView color, vk::ImageView depth,
           u32 w, u32 h);

} // namespace InteriorExposure
} // namespace Vulkan
''', r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class CameraMotion;
class Instance;
class Scheduler;

/// bbport (r99_interior-exposure, r99b_interior-brightness): the meter of the interior exposure
/// lift (gpu/shim/bbport_interior_exposure.h has the rule and the knobs).
namespace InteriorExposure {

/// Called by TemporalUpscaler::Run with the frame's camera (its projection turns depth into view
/// depth for the open share), HDR scene colour (`color`: rgba16f, GENERAL, storage) and depth
/// (`depth`: GENERAL, sampled) of w x h render pixels, before the upscaler reads them. Reads the
/// newest earlier reading the GPU has finished, eases the open share and the lift and stores the
/// lift's factor (BbInteriorExposure::Scale), then records this frame's meter dispatch. With
/// BB_INTERIOR_EXPOSURE not 1 or 2 it returns at once: nothing is made, read, recorded or printed.
void Meter(const Instance& instance, Scheduler& scheduler, const CameraMotion& camera,
           vk::ImageView color, vk::ImageView depth, u32 w, u32 h);

} // namespace InteriorExposure
} // namespace Vulkan
'''),
    R + "vk_interior_exposure.cpp": (r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_interior_exposure.h"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

#include <vk_mem_alloc.h>

#include "bbport_interior_exposure.h"
#include "bbport_settings.h"
#include "video_core/host_shaders/interior_meter_comp.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan::InteriorExposure {
namespace {
namespace Policy = BbInteriorExposure;
using Clock = std::chrono::steady_clock;

constexpr u32 SlotCount = 4;

/// interior_meter.comp's Slot (std430).
struct Slot {
    float log_sum, samples, sky, total;
    u32 frame, pad[3];
};
static_assert(sizeof(Slot) == 32);

/// interior_meter.comp's Push.
struct Push {
    u32 width, height, grid_x, grid_y, slot, frame;
    float lum_min, lum_max;
};
static_assert(sizeof(Push) == 32);

/// The meter's objects, made at its first call with the knob on. They are never freed: the process
/// ends with the device (one compute pipeline and a 128-byte host buffer).
struct State {
    bool tried = false, ready = false;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::Buffer buffer{};
    VmaAllocation allocation{};
    void* mapped = nullptr;
    std::array<u64, SlotCount> tick{};    ///< the scheduler tick each slot's dispatch was recorded in
    std::array<u32, SlotCount> frame{};   ///< the frame number pushed with it
    std::array<bool, SlotCount> pending{}; ///< recorded, not read back yet
    u32 next_frame = 1;
    float applied_ev = 0.0f;
    Policy::Lift last{};
    bool have_read = false;
    Clock::time_point last_read{}, last_line{};
    u32 metered = 0, read = 0, held = 0, busy = 0; ///< since the last line
};

bool MakeBuffer(const Instance& instance, State& s) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(Slot) * SlotCount,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
    alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &s.allocation, &info) !=
            VK_SUCCESS ||
        !info.pMappedData) {
        return false;
    }
    s.buffer = raw;
    s.mapped = info.pMappedData;
    std::memset(s.mapped, 0, sizeof(Slot) * SlotCount);
    return true;
}

const char* ToneName(int tone) {
    return tone == BbSettings::TonemapperGt7    ? "GT7"
           : tone == BbSettings::TonemapperAces ? "ACES"
                                                : "the game's curve: no effect";
}

void SayOn(const Policy::Config& knobs, bool ready) {
    if (!ready) {
        std::printf("Interior exposure (r99): off - no meter pipeline or host buffer\n");
        return;
    }
    const int tone = BbSettings::Get().graphics_tonemapper.load(std::memory_order_relaxed);
    std::printf("Interior exposure (r99, BB_INTERIOR_EXPOSURE=%d%s): meter of %ux%u samples of the "
                "HDR scene at the upscaler (one 256-thread group, a %u-byte host buffer); target "
                "%.3f, strength %.2f, at most %+.2f EV, no lift with %.0f%% sky or more (fading from "
                "%.0f%%), rises over %.1f s, falls over %.1f s; acts through the GT7/ACES exposure "
                "(tonemapper now: %s)\n",
                knobs.mode, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev,
                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::RiseSeconds,
                Policy::FallSeconds, ToneName(tone));
}
} // namespace

void Meter(const Instance& instance, Scheduler& scheduler, vk::ImageView color, vk::ImageView depth,
           u32 w, u32 h) {
    const Policy::Config& knobs = Policy::Knobs();
    if (knobs.mode == Policy::Off || !color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    if (!s.tried) {
        s.tried = true;
        s.ready = EffectPass::Create(instance, s.set_layout, s.layout, s.pipeline,
                                     {vk::DescriptorType::eStorageImage,
                                      vk::DescriptorType::eSampledImage,
                                      vk::DescriptorType::eStorageBuffer},
                                     sizeof(Push), INTERIOR_METER_COMP, "Interior exposure (r99)") &&
                  MakeBuffer(instance, s);
        SayOn(knobs, s.ready);
        s.last_line = Clock::now();
    }
    if (!s.ready) {
        return;
    }
    const auto now = Clock::now();

    // The newest reading the GPU has finished; a slot that holds another frame's numbers is skipped.
    bool got = false;
    Slot newest{};
    u32 newest_frame = 0;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i] || !scheduler.IsFree(s.tick[i])) {
            continue;
        }
        s.pending[i] = false;
        Slot slot;
        std::memcpy(&slot, static_cast<const u8*>(s.mapped) + i * sizeof(Slot), sizeof(Slot));
        if (slot.frame != s.frame[i]) {
            ++s.held;
            continue;
        }
        if (!got || s.frame[i] > newest_frame) {
            newest = slot;
            newest_frame = s.frame[i];
            got = true;
        }
    }
    if (got) {
        ++s.read;
        const Policy::Lift lift =
            Policy::Want(knobs, {newest.log_sum, newest.samples, newest.sky, newest.total});
        const float dt = s.have_read ? std::chrono::duration<float>(now - s.last_read).count() : 0.0f;
        s.have_read = true;
        s.last_read = now;
        if (lift.valid) {
            s.applied_ev = Policy::Step(s.applied_ev, lift.wanted_ev, dt);
            s.last = lift;
        } else {
            ++s.held;
        }
        Policy::applied_scale.store(std::exp2(s.applied_ev), std::memory_order_relaxed);
    }

    // This frame's meter, into a slot nobody waits on.
    u32 slot = SlotCount;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i]) {
            slot = i;
            break;
        }
    }
    if (slot == SlotCount) {
        ++s.busy;
    } else {
        const Push push{w, h, Policy::GridX, Policy::GridY, slot, s.next_frame,
                        Policy::LumMin, Policy::LumMax};
        s.frame[slot] = s.next_frame;
        s.next_frame = s.next_frame == 0xffffffffu ? 1u : s.next_frame + 1u;
        s.pending[slot] = true;
        s.tick[slot] = scheduler.CurrentTick();
        ++s.metered;
        EffectPass::Mark(99, "interior exposure meter", true);
        scheduler.Record([push, color, depth, buffer = s.buffer, pipeline = *s.pipeline,
                          layout = *s.layout](vk::CommandBuffer cmd) {
            const vk::DescriptorImageInfo scene_info{.imageView = color,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo depth_info{.imageView = depth,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo slots_info{buffer, 0, VK_WHOLE_SIZE};
            const std::array<vk::WriteDescriptorSet, 3> writes{{
                {.dstBinding = 0,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage,
                 .pImageInfo = &scene_info},
                {.dstBinding = 1,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eSampledImage,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer,
                 .pBufferInfo = &slots_info},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch(1, 1, 1);
            EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eComputeShader,
                                      vk::AccessFlagBits2::eShaderWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    }

    const float since = std::chrono::duration<float>(now - s.last_line).count();
    if (since >= (knobs.mode == Policy::Show ? 1.0f : 2.0f)) {
        s.last_line = now;
        const auto& settings = BbSettings::Get();
        const int tone = settings.graphics_tonemapper.load(std::memory_order_relaxed);
        const float gt7 = settings.graphics_gt7_exposure.load(std::memory_order_relaxed);
        const float scale = Policy::Scale();
        std::printf("Interior exposure (r99): metered %.5f (log-average luminance before the tone "
                    "curve, sky left out), sky %.1f%%, indoor %.2f, wanted %+.2f EV, applied %+.3f EV "
                    "(x%.4f), GT7/ACES exposure %.2f -> %.3f (tonemapper: %s); %u meters, %u read, %u "
                    "held, %u busy since the last line\n",
                    s.last.metered, s.last.sky_share * 100.0f, s.last.indoor, s.last.wanted_ev,
                    s.applied_ev, scale, gt7, gt7 * scale, ToneName(tone), s.metered, s.read, s.held,
                    s.busy);
        s.metered = s.read = s.held = s.busy = 0;
    }
}

} // namespace Vulkan::InteriorExposure
''', r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_interior_exposure.h"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

#include <vk_mem_alloc.h>

#include "bbport_interior_exposure.h"
#include "bbport_settings.h"
#include "video_core/host_shaders/interior_meter_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan::InteriorExposure {
namespace {
namespace Policy = BbInteriorExposure;
using Clock = std::chrono::steady_clock;

constexpr u32 SlotCount = 4;
constexpr float SampleCount = float(Policy::GridX * Policy::GridY);

/// interior_meter.comp's Slot (std430).
struct Slot {
    float log_sum, samples, sky, quarter;
    u32 frame;
    float halfway, open, twice;
};
static_assert(sizeof(Slot) == 32);

/// interior_meter.comp's Push.
struct Push {
    u32 width, height, grid_x, grid_y, slot, frame;
    float lum_min, lum_max;
    float z_scale, z_offset, open_m, pad0;
};
static_assert(sizeof(Push) == 48);

/// The meter's objects, made at its first call with the knob on. They are never freed: the process
/// ends with the device (one compute pipeline and a 128-byte host buffer).
struct State {
    bool tried = false, ready = false;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::Buffer buffer{};
    VmaAllocation allocation{};
    void* mapped = nullptr;
    std::array<u64, SlotCount> tick{};    ///< the scheduler tick each slot's dispatch was recorded in
    std::array<u32, SlotCount> frame{};   ///< the frame number pushed with it
    std::array<bool, SlotCount> pending{}; ///< recorded, not read back yet
    std::array<float, SlotCount> open_at{}; ///< the open distance pushed with it (0: depth 1 only)
    u32 next_frame = 1;
    float applied_ev = 0.0f;
    float open_eased = Policy::OpenStart;
    Policy::Lift last{};
    Policy::Reading last_reading{};
    float last_open_m = 0.0f; ///< the open distance the last reading was metered with
    bool have_read = false;
    Clock::time_point last_read{}, last_line{};
    u32 metered = 0, read = 0, held = 0, busy = 0, no_camera = 0; ///< since the last line
};

bool MakeBuffer(const Instance& instance, State& s) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(Slot) * SlotCount,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
    alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &s.allocation, &info) !=
            VK_SUCCESS ||
        !info.pMappedData) {
        return false;
    }
    s.buffer = raw;
    s.mapped = info.pMappedData;
    std::memset(s.mapped, 0, sizeof(Slot) * SlotCount);
    return true;
}

const char* ToneName(int tone) {
    return tone == BbSettings::TonemapperGt7    ? "GT7"
           : tone == BbSettings::TonemapperAces ? "ACES"
                                                : "the game's curve: no effect";
}

void SayOn(const Policy::Config& knobs, bool ready) {
    if (!ready) {
        std::printf("Interior exposure (r99b): off - no meter pipeline or host buffer\n");
        return;
    }
    const int tone = BbSettings::Get().graphics_tonemapper.load(std::memory_order_relaxed);
    char open[64];
    if (knobs.open_m > 0.0f) {
        std::snprintf(open, sizeof(open), "depth 1 or %.0f m or farther", knobs.open_m);
    } else {
        std::snprintf(open, sizeof(open), "depth 1 only");
    }
    std::printf("Interior exposure (r99b, BB_INTERIOR_EXPOSURE=%d%s): meter of %ux%u samples of "
                "the HDR scene at the upscaler (one 256-thread group, a %u-byte host buffer); "
                "target %.3f, strength %.2f, at most %+.2f EV; open samples: %s; no lift with %.0f%% "
                "open or more (fading from %.0f%%), the open share eased up over %.2f s and down "
                "over %.1f s; the lift rises over %.1f s, falls over %.1f s; acts through the "
                "GT7/ACES exposure (tonemapper now: %s); each line: metered = log-average "
                "luminance before the tone curve, sky left out; counts since the last line\n",
                knobs.mode, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev, open,
                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::OpenRiseSeconds,
                Policy::OpenFallSeconds, Policy::RiseSeconds, Policy::FallSeconds, ToneName(tone));
}

float Percent(float count) {
    return count * (100.0f / SampleCount);
}
} // namespace

void Meter(const Instance& instance, Scheduler& scheduler, const CameraMotion& camera,
           vk::ImageView color, vk::ImageView depth, u32 w, u32 h) {
    const Policy::Config& knobs = Policy::Knobs();
    if (knobs.mode == Policy::Off || !color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    if (!s.tried) {
        s.tried = true;
        s.ready = EffectPass::Create(instance, s.set_layout, s.layout, s.pipeline,
                                     {vk::DescriptorType::eStorageImage,
                                      vk::DescriptorType::eSampledImage,
                                      vk::DescriptorType::eStorageBuffer},
                                     sizeof(Push), INTERIOR_METER_COMP, "Interior exposure (r99b)") &&
                  MakeBuffer(instance, s);
        SayOn(knobs, s.ready);
        s.last_line = Clock::now();
    }
    if (!s.ready) {
        return;
    }
    const auto now = Clock::now();

    // The newest reading the GPU has finished; a slot that holds another frame's numbers is skipped.
    bool got = false;
    Slot newest{};
    u32 newest_frame = 0;
    float newest_open_m = 0.0f;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i] || !scheduler.IsFree(s.tick[i])) {
            continue;
        }
        s.pending[i] = false;
        Slot slot;
        std::memcpy(&slot, static_cast<const u8*>(s.mapped) + i * sizeof(Slot), sizeof(Slot));
        if (slot.frame != s.frame[i]) {
            ++s.held;
            continue;
        }
        if (!got || s.frame[i] > newest_frame) {
            newest = slot;
            newest_frame = s.frame[i];
            newest_open_m = s.open_at[i];
            got = true;
        }
    }
    if (got) {
        ++s.read;
        const Policy::Reading reading{newest.log_sum, newest.samples, newest.sky, SampleCount,
                                      newest.quarter, newest.halfway, newest.open, newest.twice};
        const float dt = s.have_read ? std::chrono::duration<float>(now - s.last_read).count() : 0.0f;
        s.have_read = true;
        s.last_read = now;
        // A reading metered without the open distance (no usable camera then) saw only depth-1
        // sky: it does not move the eased share, so it cannot start a lift outdoors.
        const bool full = newest_open_m == knobs.open_m;
        if (Policy::Usable(reading) && full) {
            s.open_eased = Policy::StepOpen(s.open_eased, Policy::OpenShare(reading), dt);
        }
        const Policy::Lift lift = Policy::Want(knobs, reading, s.open_eased);
        s.last_reading = reading;
        s.last_open_m = newest_open_m;
        if (lift.valid) {
            s.applied_ev = Policy::Step(s.applied_ev, lift.wanted_ev, dt);
            s.last = lift;
        } else {
            ++s.held;
        }
        Policy::applied_scale.store(std::exp2(s.applied_ev), std::memory_order_relaxed);
    }

    // The projection's z terms (depth = z_scale + z_offset / z, z_offset < 0 in front); without a
    // usable camera only depth 1 counts as open this frame.
    const std::array<float, 4> proj = camera.CameraMatrices().proj;
    const bool camera_ok = std::isfinite(proj[2]) && std::isfinite(proj[3]) && proj[3] < 0.0f;
    const float open_m = camera_ok ? knobs.open_m : 0.0f;
    if (!camera_ok) {
        ++s.no_camera;
    }

    // This frame's meter, into a slot nobody waits on.
    u32 slot = SlotCount;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i]) {
            slot = i;
            break;
        }
    }
    if (slot == SlotCount) {
        ++s.busy;
    } else {
        const Push push{w, h, Policy::GridX, Policy::GridY, slot, s.next_frame,
                        Policy::LumMin, Policy::LumMax, proj[2], proj[3], open_m, 0.0f};
        s.frame[slot] = s.next_frame;
        s.open_at[slot] = open_m;
        s.next_frame = s.next_frame == 0xffffffffu ? 1u : s.next_frame + 1u;
        s.pending[slot] = true;
        s.tick[slot] = scheduler.CurrentTick();
        ++s.metered;
        EffectPass::Mark(99, "interior exposure meter", true);
        scheduler.Record([push, color, depth, buffer = s.buffer, pipeline = *s.pipeline,
                          layout = *s.layout](vk::CommandBuffer cmd) {
            const vk::DescriptorImageInfo scene_info{.imageView = color,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo depth_info{.imageView = depth,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo slots_info{buffer, 0, VK_WHOLE_SIZE};
            const std::array<vk::WriteDescriptorSet, 3> writes{{
                {.dstBinding = 0,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage,
                 .pImageInfo = &scene_info},
                {.dstBinding = 1,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eSampledImage,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer,
                 .pBufferInfo = &slots_info},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch(1, 1, 1);
            EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eComputeShader,
                                      vk::AccessFlagBits2::eShaderWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    }

    const float since = std::chrono::duration<float>(now - s.last_line).count();
    if (since >= (knobs.mode == Policy::Show ? 1.0f : 2.0f)) {
        s.last_line = now;
        const auto& settings = BbSettings::Get();
        const int tone = settings.graphics_tonemapper.load(std::memory_order_relaxed);
        const float gt7 = settings.graphics_gt7_exposure.load(std::memory_order_relaxed);
        const float scale = Policy::Scale();
        const Policy::Reading& r = s.last_reading;
        const float m = s.last_open_m;
        std::printf("Interior exposure (r99b): applied %+.3f EV (x%.4f), wanted %+.2f EV, metered "
                    "%.5f; open %.1f%%, eased %.1f%%, indoor %.2f (depth 1 %.1f%%; at least "
                    "%.0f/%.0f/%.0f/%.0f m: %.1f/%.1f/%.1f/%.1f%%); GT7/ACES exposure %.2f -> %.3f "
                    "(%s); %u meters, %u read, %u held, %u busy, %u no camera\n",
                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered,
                    Policy::OpenShare(r) * 100.0f, s.open_eased * 100.0f, s.last.indoor,
                    Percent(r.sky), 0.25f * m, 0.5f * m, m, 2.0f * m, Percent(r.quarter),
                    Percent(r.halfway), Percent(r.open), Percent(r.twice), gt7, gt7 * scale,
                    ToneName(tone), s.metered, s.read, s.held, s.busy, s.no_camera);
        s.metered = s.read = s.held = s.busy = s.no_camera = 0;
    }
}

} // namespace Vulkan::InteriorExposure
'''),
    "engine/tests/test_interior_exposure.cpp": (r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure): the interior exposure floor's knobs, rule and easing
// (gpu/shim/bbport_interior_exposure.h). Built and run by engine/build.sh --test and the CMake
// target interior-exposure-test.
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "gpu/shim/bbport_interior_exposure.h"

using namespace BbInteriorExposure;

static bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}

// A reading of `ground` samples all at luminance `lum` and `sky` sky samples.
static Reading Scene(float lum, float ground, float sky) {
    Reading r;
    r.log_sum = std::log2(lum) * ground;
    r.samples = ground;
    r.sky = sky;
    r.total = ground + sky;
    return r;
}

int main() {
    const float all = float(GridX * GridY);
    // a. Knobs: off unless exactly "1" or "2"; defaults; SHOW's defaults; set values win; ranges.
    {
        const Config off = Parse(nullptr, nullptr, nullptr, nullptr);
        assert(off.mode == Off && off.target == DefaultTarget && off.strength == DefaultStrength &&
               off.max_ev == DefaultMaxEv);
        for (const char* m : {"", "0", "3", "12", "on", "1 ", "-1"}) {
            assert(Parse(m, nullptr, nullptr, nullptr).mode == Off);
        }
        const Config on = Parse("1", nullptr, nullptr, nullptr);
        assert(on.mode == On && on.target == DefaultTarget && on.strength == DefaultStrength &&
               on.max_ev == DefaultMaxEv);
        const Config show = Parse("2", nullptr, nullptr, nullptr);
        assert(show.mode == Show && show.target == ShowTarget && show.strength == ShowStrength &&
               show.max_ev == ShowMaxEv);
        const Config set = Parse("2", "0.02", "0.25", "1");
        assert(set.target == 0.02f && set.strength == 0.25f && set.max_ev == 1.0f);
        const Config high = Parse("1", "9", "-1", "7");
        assert(high.target == TargetMax && high.strength == 0.0f && high.max_ev == MaxEvLimit);
        const Config low = Parse("1", "0", "2", "-3");
        assert(low.target == TargetMin && low.strength == 1.0f && low.max_ev == 0.0f);
        const Config junk = Parse("1", "abc", "0.5x", "nan");
        assert(junk.target == DefaultTarget && junk.strength == DefaultStrength &&
               junk.max_ev == DefaultMaxEv);
        assert(Parse("1", "inf", "", nullptr).target == DefaultTarget);
        assert(DefaultMaxEv <= MaxEvLimit && ShowMaxEv <= MaxEvLimit && SkyOpen < SkyGone);
    }
    // b. The rule at the study's measured scenes (2026-11-15, hero light off, sky masked).
    const Config on = Parse("1", nullptr, nullptr, nullptr);
    const Config show = Parse("2", nullptr, nullptr, nullptr);
    {
        const Lift level = Want(on, Scene(0.01425f, all, 0)); // library, mod off, level
        assert(level.valid && Near(level.metered, 0.01425f, 1e-5f) && level.indoor == 1.0f);
        assert(Near(level.wanted_ev, std::log2(0.02f / 0.01425f), 1e-4f));
        assert(level.wanted_ev > 0.45f && level.wanted_ev < 0.53f);
        const Lift up = Want(on, Scene(0.01098f, all, 0)); // looking up
        assert(up.valid && up.wanted_ev > 0.83f && up.wanted_ev < 0.90f);
        const Lift mod = Want(on, Scene(0.00432f, all, 0)); // library, Remaster mod on
        assert(mod.valid && mod.wanted_ev == DefaultMaxEv);
        const Lift house = Want(on, Scene(0.05514f, all, 0)); // dream house: above the target
        assert(house.valid && house.wanted_ev == 0.0f);
        const Lift alley = Want(on, Scene(0.02509f, all, 0)); // dark alley, mod off: no sky seen
        assert(alley.valid && alley.indoor == 1.0f && alley.wanted_ev == 0.0f);
        const Lift alley_mod = Want(on, Scene(0.0097f, all, 0)); // with the mod: lifted (floor)
        assert(alley_mod.valid && alley_mod.wanted_ev > 1.0f && alley_mod.wanted_ev < 1.1f);
        const Lift at = Want(on, Scene(DefaultTarget, all, 0));
        assert(at.valid && Near(at.wanted_ev, 0.0f, 1e-5f));
        const Lift bright = Want(on, Scene(0.5f, all, 0)); // never darkens
        assert(bright.valid && bright.wanted_ev == 0.0f);
        const Lift house_show = Want(show, Scene(0.05514f, all, 0)); // SHOW lifts the house
        assert(Near(house_show.wanted_ev, std::log2(0.15f / 0.05514f), 1e-4f));
        assert(house_show.wanted_ev > 1.4f && house_show.wanted_ev < 1.5f);
        assert(Want(show, Scene(0.01425f, all, 0)).wanted_ev == ShowMaxEv);
        assert(Want(Parse("1", nullptr, "0", nullptr), Scene(0.001f, all, 0)).wanted_ev == 0.0f);
    }
    // c. The sky gate: up to SkyOpen full, from SkyGone none, half way between half.
    {
        const Lift full = Want(on, Scene(0.01425f, 97, 3));
        assert(full.valid && Near(full.indoor, 1.0f, 1e-5f) && full.wanted_ev > 0.45f);
        const Lift half = Want(on, Scene(0.01425f, 91, 9));
        assert(half.valid && Near(half.indoor, 0.5f, 1e-3f));
        assert(Near(half.wanted_ev, 0.5f * std::log2(0.02f / 0.01425f), 2e-3f));
        const Lift street = Want(on, Scene(0.01f, 80, 20));
        assert(street.valid && street.indoor == 0.0f && street.wanted_ev == 0.0f);
        const Lift sky_only = Want(on, Scene(1.0f, 0, all));
        assert(sky_only.valid && sky_only.metered == 0.0f && sky_only.wanted_ev == 0.0f);
    }
    // d. Readings that hold the lift: a black frame, nothing read, numbers that are not numbers.
    {
        assert(!Want(on, Scene(LumMin, all, 0)).valid);
        assert(!Want(on, Scene(BlackFrame * 0.5f, all, 0)).valid);
        assert(Want(on, Scene(BlackFrame * 2.0f, all, 0)).valid);
        assert(!Want(on, Reading{}).valid);
        Reading nan = Scene(0.01f, all, 0);
        nan.log_sum = std::nanf("");
        assert(!Want(on, nan).valid);
        Reading negative = Scene(0.01f, all, 0);
        negative.sky = -1.0f;
        assert(!Want(on, negative).valid);
    }
    // e. Easing: RiseSeconds up, FallSeconds down, steps clamped, never past the wanted lift.
    {
        assert(Near(Step(0.0f, 1.0f, 0.2f), 1.0f - std::exp(-0.2f / RiseSeconds), 1e-6f));
        assert(Near(Step(1.0f, 0.0f, 0.2f), std::exp(-0.2f / FallSeconds), 1e-6f));
        assert(Step(0.0f, 1.0f, 5.0f) == Step(0.0f, 1.0f, MaxStep));
        assert(Step(0.5f, 1.0f, -1.0f) == 0.5f && Step(0.5f, 1.0f, std::nanf("")) == 0.5f);
        float a = 0.0f;
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 1.2f, 1.0f / 60.0f);
            assert(b >= a && b <= 1.2f);
            a = b;
        }
        assert(Near(a, 1.2f, 1e-3f));
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 0.0f, 1.0f / 60.0f);
            assert(b <= a && b >= 0.0f);
            a = b;
        }
        assert(Near(a, 0.0f, 1e-3f));
    }
    // f. The factor is exactly 1 until the meter writes it, so x * Scale() is x bit for bit.
    {
        assert(Scale() == 1.0f);
        for (const float x : {1.0f, 0.25f, 4.0f, 1.41f, 0.3333333f}) {
            const float y = x * Scale();
            assert(std::memcmp(&x, &y, sizeof x) == 0);
        }
        assert(std::exp2(0.0f) == 1.0f);
    }
    std::puts("interior-exposure-test: all checks passed");
    return 0;
}
''', r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure, r99b_interior-brightness): the interior exposure lift's knobs,
// rule and easing (gpu/shim/bbport_interior_exposure.h). Built and run by engine/build.sh --test
// and the CMake target interior-exposure-test.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "gpu/shim/bbport_interior_exposure.h"

using namespace BbInteriorExposure;

static bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}

// A reading of `ground` samples all at luminance `lum`, `sky` sky samples, and `open` of the
// ground samples at the open distance or farther.
static Reading Scene(float lum, float ground, float sky, float open = 0.0f) {
    Reading r;
    r.log_sum = std::log2(lum) * ground;
    r.samples = ground;
    r.sky = sky;
    r.total = ground + sky;
    r.quarter = r.halfway = r.open = open;
    r.twice = 0.0f;
    return r;
}

// 60 frames a second of `seconds` toward `share` (open share) at luminance `lum`; returns the
// largest applied lift on the way; `eased` and `applied` carry over.
static float Walk(const Config& c, float lum, float share, float seconds, float& eased,
                  float& applied) {
    const float all = float(GridX * GridY);
    const Reading r = Scene(lum, all, 0.0f, share * all);
    float peak = applied;
    for (int i = 0; i < int(seconds * 60.0f + 0.5f); ++i) {
        eased = StepOpen(eased, OpenShare(r), 1.0f / 60.0f);
        const Lift l = Want(c, r, eased);
        assert(l.valid);
        applied = Step(applied, l.wanted_ev, 1.0f / 60.0f);
        peak = std::max(peak, applied);
    }
    return peak;
}

int main() {
    const float all = float(GridX * GridY);
    // a. Knobs: off unless exactly "1" or "2"; defaults; SHOW's defaults; set values win; ranges.
    {
        const Config off = Parse(nullptr, nullptr, nullptr, nullptr);
        assert(off.mode == Off && off.target == DefaultTarget && off.strength == DefaultStrength &&
               off.max_ev == DefaultMaxEv && off.open_m == DefaultOpenMeters);
        for (const char* m : {"", "0", "3", "12", "on", "1 ", "-1"}) {
            assert(Parse(m, nullptr, nullptr, nullptr).mode == Off);
        }
        const Config on = Parse("1", nullptr, nullptr, nullptr, nullptr);
        assert(on.mode == On && on.target == DefaultTarget && on.strength == DefaultStrength &&
               on.max_ev == DefaultMaxEv && on.open_m == DefaultOpenMeters);
        const Config show = Parse("2", nullptr, nullptr, nullptr);
        assert(show.mode == Show && show.target == ShowTarget && show.strength == ShowStrength &&
               show.max_ev == ShowMaxEv && show.open_m == DefaultOpenMeters);
        const Config set = Parse("2", "0.02", "0.25", "1", "40");
        assert(set.target == 0.02f && set.strength == 0.25f && set.max_ev == 1.0f &&
               set.open_m == 40.0f);
        const Config high = Parse("1", "9", "-1", "7", "5000");
        assert(high.target == TargetMax && high.strength == 0.0f && high.max_ev == MaxEvLimit &&
               high.open_m == OpenMetersMax);
        const Config low = Parse("1", "0", "2", "-3", "-5");
        assert(low.target == TargetMin && low.strength == 1.0f && low.max_ev == 0.0f &&
               low.open_m == 0.0f);
        const Config junk = Parse("1", "abc", "0.5x", "nan", "80m");
        assert(junk.target == DefaultTarget && junk.strength == DefaultStrength &&
               junk.max_ev == DefaultMaxEv && junk.open_m == DefaultOpenMeters);
        assert(Parse("1", "inf", "", nullptr).target == DefaultTarget);
        assert(DefaultMaxEv <= MaxEvLimit && ShowMaxEv <= MaxEvLimit && SkyOpen < SkyGone);
        assert(DefaultOpenMeters <= OpenMetersMax && OpenRiseSeconds < OpenFallSeconds);
    }
    // b. The rule at the study's measured scenes (2026-11-15, hero light off unless said, sky
    //    masked), seen as closed views (no open samples).
    const Config on = Parse("1", nullptr, nullptr, nullptr);
    const Config show = Parse("2", nullptr, nullptr, nullptr);
    {
        const Lift level = Want(on, Scene(0.01425f, all, 0)); // library, level
        assert(level.valid && Near(level.metered, 0.01425f, 1e-5f) && level.indoor == 1.0f);
        assert(Near(level.wanted_ev, 0.5f * std::log2(0.05f / 0.01425f), 1e-4f));
        assert(level.wanted_ev > 0.88f && level.wanted_ev < 0.93f);
        const Lift up = Want(on, Scene(0.01098f, all, 0)); // library, looking up
        assert(up.valid && up.wanted_ev > 1.07f && up.wanted_ev < 1.12f);
        const Lift mod = Want(on, Scene(0.00546f, all, 0)); // library, BB PC Remaster mod on
        assert(mod.valid && mod.wanted_ev == DefaultMaxEv);
        const Lift church_mod = Want(on, Scene(0.01234f, all, 0)); // church-candles, mod on
        assert(church_mod.valid && church_mod.wanted_ev > 0.98f && church_mod.wanted_ev < 1.04f);
        const Lift church = Want(on, Scene(0.04016f, all, 0)); // church-candles, mod off
        assert(church.valid && church.wanted_ev > 0.14f && church.wanted_ev < 0.18f);
        const Lift house_mod = Want(on, Scene(0.02982f, all, 0)); // dream house, mod on
        assert(house_mod.valid && house_mod.wanted_ev > 0.35f && house_mod.wanted_ev < 0.40f);
        const Lift house = Want(on, Scene(0.05192f, all, 0)); // dream house, mod off
        assert(house.valid && house.wanted_ev == 0.0f);
        // Rooms keep their order: lifted, the library stays darker than the church and the house.
        const float lib_after = 0.01425f * std::exp2(level.wanted_ev);
        assert(lib_after < 0.04016f * std::exp2(church.wanted_ev) && lib_after < 0.05192f);
        // The dark alley (outdoors, mod off): luminance alone would lift it; open samples stop it.
        const Lift alley_closed = Want(on, Scene(0.02509f, all, 0));
        assert(alley_closed.valid && alley_closed.wanted_ev > 0.45f && alley_closed.wanted_ev < 0.55f);
        const Lift alley_open = Want(on, Scene(0.02509f, all, 0, 0.2f * all));
        assert(alley_open.valid && alley_open.indoor == 0.0f && alley_open.wanted_ev == 0.0f);
        const Lift at = Want(on, Scene(DefaultTarget, all, 0));
        assert(at.valid && Near(at.wanted_ev, 0.0f, 1e-5f));
        const Lift bright = Want(on, Scene(0.5f, all, 0)); // never darkens
        assert(bright.valid && bright.wanted_ev == 0.0f);
        const Lift house_show = Want(show, Scene(0.05192f, all, 0)); // SHOW lifts the house
        assert(Near(house_show.wanted_ev, std::log2(0.15f / 0.05192f), 1e-4f));
        assert(Want(show, Scene(0.01425f, all, 0)).wanted_ev == ShowMaxEv);
        assert(Want(Parse("1", nullptr, "0", nullptr), Scene(0.001f, all, 0)).wanted_ev == 0.0f);
        // r99's numbers with r99's values.
        const Config r99 = Parse("1", "0.02", "1", nullptr, "0");
        assert(Near(Want(r99, Scene(0.01425f, all, 0)).wanted_ev, std::log2(0.02f / 0.01425f), 1e-4f));
    }
    // c. The open gate: up to SkyOpen full, from SkyGone none, half way between half; sky and far
    //    samples count alike; the eased share decides, not the reading's own.
    {
        const Lift full = Want(on, Scene(0.01425f, 97, 3));
        assert(full.valid && Near(full.indoor, 1.0f, 1e-5f) && full.wanted_ev > 0.85f);
        const Lift full_far = Want(on, Scene(0.01425f, 100, 0, 3));
        assert(Near(full_far.indoor, 1.0f, 1e-5f) && Near(full_far.wanted_ev, full.wanted_ev, 1e-4f));
        const Lift half = Want(on, Scene(0.01425f, 91, 9));
        assert(half.valid && Near(half.indoor, 0.5f, 1e-3f));
        assert(Near(half.wanted_ev, 0.25f * std::log2(0.05f / 0.01425f), 2e-3f));
        const Lift half_far = Want(on, Scene(0.01425f, 100, 4, 5)); // 9 of 104 open
        assert(half_far.indoor > 0.4f && half_far.indoor < 0.6f);
        const Lift street = Want(on, Scene(0.01f, 80, 20));
        assert(street.valid && street.indoor == 0.0f && street.wanted_ev == 0.0f);
        const Lift sky_only = Want(on, Scene(1.0f, 0, all));
        assert(sky_only.valid && sky_only.metered == 0.0f && sky_only.wanted_ev == 0.0f);
        assert(Near(OpenShare(Scene(0.01f, 90, 10, 20)), 0.3f, 1e-6f));
        // A closed view right after an open one: no lift yet.
        assert(Want(on, Scene(0.01425f, all, 0), 0.2f).wanted_ev == 0.0f);
        // An open reading while the eased share is still closed: lifted (the easing decides).
        assert(Want(on, Scene(0.01425f, 80, 20), 0.0f).wanted_ev > 0.85f);
        // Not a number: taken as open.
        assert(Want(on, Scene(0.01425f, all, 0), std::nanf("")).wanted_ev == 0.0f);
    }
    // d. Readings that hold the lift: a black frame, nothing read, numbers that are not numbers.
    {
        assert(!Want(on, Scene(LumMin, all, 0)).valid);
        assert(!Want(on, Scene(BlackFrame * 0.5f, all, 0)).valid);
        assert(Want(on, Scene(BlackFrame * 2.0f, all, 0)).valid);
        assert(!Want(on, Reading{}).valid);
        assert(OpenShare(Reading{}) == 0.0f);
        Reading nan = Scene(0.01f, all, 0);
        nan.log_sum = std::nanf("");
        assert(!Want(on, nan).valid);
        Reading negative = Scene(0.01f, all, 0);
        negative.sky = -1.0f;
        assert(!Want(on, negative).valid && OpenShare(negative) == 0.0f);
        Reading open_nan = Scene(0.01f, all, 0);
        open_nan.open = std::nanf("");
        assert(!Usable(open_nan) && !Want(on, open_nan).valid);
    }
    // e. Easing: RiseSeconds up, FallSeconds down, steps clamped, never past the wanted lift; the
    //    open share up over OpenRiseSeconds, down over OpenFallSeconds.
    {
        assert(Near(Step(0.0f, 1.0f, 0.2f), 1.0f - std::exp(-0.2f / RiseSeconds), 1e-6f));
        assert(Near(Step(1.0f, 0.0f, 0.2f), std::exp(-0.2f / FallSeconds), 1e-6f));
        assert(Step(0.0f, 1.0f, 5.0f) == Step(0.0f, 1.0f, MaxStep));
        assert(Step(0.5f, 1.0f, -1.0f) == 0.5f && Step(0.5f, 1.0f, std::nanf("")) == 0.5f);
        assert(Near(StepOpen(0.0f, 1.0f, 0.1f), 1.0f - std::exp(-0.1f / OpenRiseSeconds), 1e-6f));
        assert(Near(StepOpen(1.0f, 0.0f, 0.2f), std::exp(-0.2f / OpenFallSeconds), 1e-6f));
        float a = 0.0f;
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 1.2f, 1.0f / 60.0f);
            assert(b >= a && b <= 1.2f);
            a = b;
        }
        assert(Near(a, 1.2f, 1e-3f));
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 0.0f, 1.0f / 60.0f);
            assert(b <= a && b >= 0.0f);
            a = b;
        }
        assert(Near(a, 0.0f, 1e-3f));
    }
    // f. Walking (60 frames a second): into the library with the mod from a street showing 40 %
    //    open samples, the lift reaches 90 % of +1.5 EV after 4-5.5 s; back out it is under
    //    +0.15 EV within 1.2 s; a 1 s look at the ground of a dark street lifts nothing.
    {
        float eased = 0.4f, applied = 0.0f;
        Walk(on, 0.00546f, 0.4f, 2.0f, eased, applied);
        assert(applied == 0.0f);
        Walk(on, 0.00546f, 0.0f, 4.0f, eased, applied);
        assert(applied < 0.9f * DefaultMaxEv);
        Walk(on, 0.00546f, 0.0f, 1.5f, eased, applied);
        assert(applied > 0.9f * DefaultMaxEv);
        Walk(on, 0.03f, 0.4f, 1.2f, eased, applied);
        assert(applied < 0.15f);
        float e2 = 0.4f, a2 = 0.0f;
        assert(Walk(on, 0.0097f, 0.0f, 1.0f, e2, a2) < 0.05f);
        // The start: taken as open until readings say otherwise.
        assert(OpenStart >= SkyGone);
    }
    // g. The factor is exactly 1 until the meter writes it, so x * Scale() is x bit for bit.
    {
        assert(Scale() == 1.0f);
        for (const float x : {1.0f, 0.25f, 4.0f, 1.41f, 0.3333333f}) {
            const float y = x * Scale();
            assert(std::memcmp(&x, &y, sizeof x) == 0);
        }
        assert(std::exp2(0.0f) == 1.0f);
    }
    std::puts("interior-exposure-test: all checks passed");
    return 0;
}
'''),
}
# sha256 of r99's files as they are on disk (CRLF), checked against SWAPS' old texts too.
OLD_SHA = {
    'engine/gpu/shim/bbport_interior_exposure.h': 'f14ca109b97a61a47ebc4b6a278ced464cca72f7e5e97d5786697b5231179661',
    H + 'interior_meter.comp': 'cd384044223147c4d146f8ca9fdcf799ad1a391814fb252733069cefb0f95802',
    R + 'vk_interior_exposure.h': '4431008559991aaf6be7227f077c1abd5367bb5ec12f746bd69c51b47d14089a',
    R + 'vk_interior_exposure.cpp': 'a53062be20ebf9441a61f8a1efff2e76b1c97209ef404c7d89015d9b47d6b97f',
    'engine/tests/test_interior_exposure.cpp': '3543648ae13f8435520ffad8269d829466560c9191929d0ccf775de7c7224e7a',
}

OLD_README = r'''### Interior exposure (in development)

Part of the lamp work: a brighten-only exposure floor, so rooms lit only by lamps (tested with `graphics_disable_player_light=1`) read dim but legible instead of black. It is a floor on dark views, not an indoor test: it lifts any view metered below the target that shows little sky at depth 1, outdoors too. Measured with the hero light off (2026-11-15, no measured view had any sky at depth 1): the library 0.014 (looking up 0.011) gets +0.49 EV (+0.87 EV) at the defaults, the Hunter's Dream house 0.055 and the dark alley 0.025 without the BB PC Remaster mod get nothing, the library with the mod reaches the +1.5 EV cap and the dark alley with the mod (0.0097) gets about +1.0 EV. Off unless `BB_INTERIOR_EXPOSURE` is `1` or `2`. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing; no ini key yet.

| Variable | What it does | Default |
|---|---|---|
| `BB_INTERIOR_EXPOSURE` | `1` turns it on, `2` is the test setting with the exaggerated values in brackets below. At each frame the upscaler takes as an HDR scene (DLSS, FSR, XeSS or TAA before the game's post, as with `upscale_before_post=1`), one group of 256 threads takes 64x36 samples of the scene colour before the tone curve: samples at depth 1 (sky) are counted apart, the others give the log-average L of their Rec.709 luminance (each clamped to 0.0001..64, values pushed to the meter). A reading the GPU has finished is read back (a 128-byte host buffer, 4 frames in a ring). The lift in stops is min(max, strength x log2(target / L)), never below 0, times 1 - smoothstep(0.03, 0.15, sky share): no lift at or above the target, none with 15% or more sky among the samples. A reading with L below 0.0004 (a black or fading frame) keeps the lift as it is. The applied lift eases toward that in real time (1 s time constant while it grows, 0.4 s while it shrinks) and, as the factor 2^lift, multiplies the exposure of the GT7 or ACES tone map (`graphics_tonemapper`, times `graphics_gt7_exposure`); with the game's own curve or the HDR curve extension it changes nothing. With it on, the log has a line once and then every 2 s (1 s with `2`): `Interior exposure (r99): metered L ..., sky ...%, indoor ..., wanted ... EV, applied ... EV (x...), GT7/ACES exposure a -> b`; no such line means no frame went through that upscaler path. Cost: one dispatch of one group, 2304 samples, an estimate of 0.01 to 0.03 ms at 1080p internal, not measured; read it on the `Lighting: interior exposure meter` row of `BB_GPU_PROFILE=1`. Off, nothing is made or dispatched and the factor is exactly 1 | off |
| `BB_INTERIOR_EXPOSURE_TARGET` | The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off: the library about 0.014, the dark alley about 0.025, the Hunter's Dream house about 0.055) | `0.02` (`0.15`) |
| `BB_INTERIOR_EXPOSURE_STRENGTH` | The share of the gap in stops the lift closes, 0 to 1 | `1` (`1`) |
| `BB_INTERIOR_EXPOSURE_MAX_EV` | The largest lift in stops, 0 to 3 | `1.5` (`3`) |

'''
NEW_README = r'''### Interior exposure (in development)

Part of the lamp work: a brighten-only exposure lift, so rooms lit only by lamps (tested with `graphics_disable_player_light=1`) read dim but legible instead of black, while views with 15% or more samples at depth 1 or at the open distance (80 m) or farther get none. Measured with the hero light off (2026-11-15; log-average before the tone curve, no measured view had any sample at depth 1): the library 0.014 (0.0055 with the BB PC Remaster mod) gets about +0.9 EV (+1.5 EV, the cap, with the mod), church-candles 0.040 (0.012 with the mod) about +0.16 EV (+1.0 EV), the Hunter's Dream house 0.052 nothing (0.030 with the mod: about +0.37 EV), so rooms keep their order of brightness. Outdoors depends on the open share alone: a dark street with fewer open samples is lifted like a room (the dark alley, 0.025, would get about +0.5 EV; 0.0097 with the mod, about +1.2 EV); how many open samples real streets show is not measured yet, the log line measures it. Off unless `BB_INTERIOR_EXPOSURE` is `1` or `2`. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing; no ini key yet. `BB_INTERIOR_EXPOSURE_TARGET=0.02 BB_INTERIOR_EXPOSURE_STRENGTH=1 BB_INTERIOR_EXPOSURE_OPEN_M=0` gives the first version's rule (r99), with the open share eased.

| Variable | What it does | Default |
|---|---|---|
| `BB_INTERIOR_EXPOSURE` | `1` turns it on, `2` is the test setting with the exaggerated values in brackets below. At each frame the upscaler takes as an HDR scene (DLSS, FSR, XeSS or TAA before the game's post, as with `upscale_before_post=1`), one group of 256 threads takes 64x36 samples of the scene colour and depth: samples at depth 1 (sky) are counted apart, the others give the log-average L of their Rec.709 luminance before the tone curve (each clamped to 0.0001..64, values pushed to the meter) and are counted by view depth (from the camera's projection) at a quarter, half, one and two times the open distance. A reading the GPU has finished is read back (a 128-byte host buffer, 4 frames in a ring). The open share (samples at depth 1 or at the open distance or farther, of all samples) is eased in real time: 0.15 s time constant while it grows, 1.5 s while it shrinks, starting at 1; a reading metered without a usable camera (no open distance) leaves it as it is. The lift in stops is min(max, strength x log2(target / L)), never below 0, times 1 - smoothstep(0.03, 0.15, eased open share): no lift at or above the target, none while 15% or more of the eased view is open, so a dark view with few open samples starts to be lifted about 1.5 to 3 s after it comes (from 40% or 100% open) and is near the full lift about 3 s later, and a view with 15% or more open samples stops the lift within about a second. A reading with L below 0.0004 (a black or fading frame) keeps the lift as it is. The applied lift eases toward that in real time (1 s time constant while it grows, 0.4 s while it shrinks) and, as the factor 2^lift, multiplies the exposure of the GT7 or ACES tone map (`graphics_tonemapper`, times `graphics_gt7_exposure`); with the game's own curve or the HDR curve extension it changes nothing. With it on, the log has a line once and then every 2 s (1 s with `2`): `Interior exposure (r99b): applied ... EV (x...), wanted ... EV, metered L; open ...%, eased ...%, indoor ... (depth 1 ...%; at least 20/40/80/160 m: .../.../.../...%); GT7/ACES exposure a -> b`; no such line means no frame went through that upscaler path. Cost: one dispatch of one group, 2304 samples, an estimate of 0.01 to 0.03 ms at 1080p internal, not measured; read it on the `Lighting: interior exposure meter` row of `BB_GPU_PROFILE=1`. Off, nothing is made or dispatched and the factor is exactly 1 | off |
| `BB_INTERIOR_EXPOSURE_TARGET` | The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off: the library about 0.014, the dark alley about 0.025, church-candles about 0.040, the Hunter's Dream house about 0.052) | `0.05` (`0.15`) |
| `BB_INTERIOR_EXPOSURE_STRENGTH` | The share of the gap in stops the lift closes, 0 to 1 | `0.5` (`1`) |
| `BB_INTERIOR_EXPOSURE_MAX_EV` | The largest lift in stops, 0 to 3 | `1.5` (`3`) |
| `BB_INTERIOR_EXPOSURE_OPEN_M` | The open distance in metres of view depth, 0 to 1000; 0 counts only depth 1 as open | `80` (`80`) |

'''

# ("replace", old, new): applied when `new` is found once and `old` is not; clean the other way.
EDITS = {
    R + "vk_temporal_upscaler.cpp": [
        ("replace",
         '    // bbport (r99_interior-exposure): meters this HDR scene for the interior exposure floor\n'
         '    // (only with BB_INTERIOR_EXPOSURE=1 or 2; otherwise it returns at once and makes nothing).\n'
         '    InteriorExposure::Meter(instance, scheduler, input_color_view, input_depth_view, w, h);\n',
         '    // bbport (r99_interior-exposure, r99b_interior-brightness): meters this HDR scene and its\n'
         '    // view depth (the camera\'s projection) for the interior exposure lift (only with\n'
         '    // BB_INTERIOR_EXPOSURE=1 or 2; otherwise it returns at once and makes nothing).\n'
         '    InteriorExposure::Meter(instance, scheduler, camera_motion, input_color_view, input_depth_view,\n'
         '                            w, h);\n'),
    ],
    "README.md": [("replace", OLD_README, NEW_README)],
}

# README rows and the header's constants must agree.
TIES = [
    ("DefaultTarget = 0.05f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.05` (`0.15`)"),
    ("ShowTarget = 0.15f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.05` (`0.15`)"),
    ("DefaultStrength = 0.5f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`0.5` (`1`)"),
    ("ShowStrength = 1.0f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`0.5` (`1`)"),
    ("DefaultMaxEv = 1.5f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "`1.5` (`3`)"),
    ("ShowMaxEv = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "`1.5` (`3`)"),
    ("MaxEvLimit = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "0 to 3"),
    ("DefaultOpenMeters = 80.0f", "| `BB_INTERIOR_EXPOSURE_OPEN_M`", "`80` (`80`)"),
    ("OpenMetersMax = 1000.0f", "| `BB_INTERIOR_EXPOSURE_OPEN_M`", "0 to 1000"),
    ("TargetMin = 0.005f, TargetMax = 1.0f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "0.005 to 1"),
    ("SkyOpen = 0.03f", "| `BB_INTERIOR_EXPOSURE` |", "smoothstep(0.03, 0.15"),
    ("SkyGone = 0.15f", "| `BB_INTERIOR_EXPOSURE` |", "15% or more of the eased view"),
    ("BlackFrame = 4e-4f", "| `BB_INTERIOR_EXPOSURE` |", "below 0.0004"),
    ("RiseSeconds = 1.0f", "| `BB_INTERIOR_EXPOSURE` |", "1 s time constant while it grows"),
    ("FallSeconds = 0.4f", "| `BB_INTERIOR_EXPOSURE` |", "0.4 s while it shrinks"),
    ("OpenRiseSeconds = 0.15f", "| `BB_INTERIOR_EXPOSURE` |", "0.15 s time constant while it grows"),
    ("OpenFallSeconds = 1.5f", "| `BB_INTERIOR_EXPOSURE` |", "1.5 s while it shrinks"),
    ("OpenStart = 1.0f", "| `BB_INTERIOR_EXPOSURE` |", "starting at 1"),
    ("GridX = 64, GridY = 36", "| `BB_INTERIOR_EXPOSURE` |", "64x36 samples"),
    ("LumMin = 1e-4f, LumMax = 64.0f", "| `BB_INTERIOR_EXPOSURE` |", "clamped to 0.0001..64"),
]
# The C++ side of the shader's blocks (the clamp and the projection are pushed, never constants).
CPP_TIES = [
    "static_assert(sizeof(Push) == 48);",
    "    float z_scale, z_offset, open_m, pad0;\n",
    "    float log_sum, samples, sky, quarter;\n    u32 frame;\n    float halfway, open, twice;\n",
    "newest.quarter, newest.halfway, newest.open, newest.twice",
    "Policy::LumMin, Policy::LumMax, proj[2], proj[3], open_m, 0.0f",
    "        s.open_at[slot] = open_m;\n",
    "        const bool full = newest_open_m == knobs.open_m;\n",
    "        if (Policy::Usable(reading) && full) {\n",
]
SHADER_TIES = [
    "    float lum_max;\n    float z_scale;  // depth = z_scale + z_offset / z\n    float z_offset;\n"
    "    float open_m;   // 0: no distance counts\n    float pad0;\n};",
    "    float quarter; // ground samples at least open_m / 4 away\n    uint frame;",
    "slots[slot] = Slot(s_log[0], s_ground[0], s_sky[0], s_far[0].x, frame, s_far[0].y,",
    "const float z = z_offset / min(depth - z_scale, -1e-8);",
]
HEADER_TIES = [
    "    float log_sum = 0, samples = 0, sky = 0, total = 0;\n"
    "    float quarter = 0, halfway = 0, open = 0, twice = 0;\n",
]


def disk(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edit_state(text, edit):
    kind, a, b = edit
    if text.count(b) == 1 and text.count(a) == 0: return "applied"
    if text.count(a) == 1 and text.count(b) == 0: return "clean"
    return "broken (old %d, new %d)" % (text.count(a), text.count(b))


def text_checks(texts):
    header = SWAPS["engine/gpu/shim/bbport_interior_exposure.h"][1]
    shader = SWAPS[H + "interior_meter.comp"][1]
    cpp = SWAPS[R + "vk_interior_exposure.cpp"][1]
    readme = texts["README.md"]
    for const, row, value in TIES:
        lines = [l for l in readme.split("\n") if l.startswith(row)]
        if header.count(const) != 1 or len(lines) != 1 or value not in lines[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    for t in CPP_TIES:
        if cpp.count(t) != 1: raise SystemExit("C++ tie check: %r" % t)
    for t in SHADER_TIES:
        if shader.count(t) != 1: raise SystemExit("shader tie check: %r" % t)
    for t in HEADER_TIES:
        if header.count(t) != 1: raise SystemExit("header tie check: %r" % t)
    if "LUM_MIN" in shader or "#define" in shader:
        raise SystemExit("shader check: no constants of its own")
    up = texts[R + "vk_temporal_upscaler.cpp"]
    call = up.find("InteriorExposure::Meter(instance, scheduler, camera_motion, input_color_view, input_depth_view,")
    if not (up.find("void TemporalUpscaler::Run() {") < up.find("const bool has_reactive = mask_ready || RecordReactive(input_color_view);") < call
            < up.find('MarkUpscalerPart(4, "upscaler: evaluate (DLSS, FSR, XeSS or TAA)");') < up.find("void TemporalUpscaler::RunUiOnly(")):
        raise SystemExit("order check: the meter call is not in TemporalUpscaler::Run between the reactive mask and the evaluate")
    if readme.count("### Interior exposure (in development)\n") != 1:
        raise SystemExit("README check: one Interior exposure section")
    for path, (old, new) in SWAPS.items():
        if not all(ord(c) < 128 for c in new) or "\r" in new:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    if not all(ord(c) < 128 for c in NEW_README):
        raise SystemExit("README section must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R99B_ROOT)" % ROOT)
    for path, (old, new) in SWAPS.items():
        if sha(disk(old)) != OLD_SHA[path]:
            raise SystemExit("%s: this script's copy of r99's text does not match its hash" % path)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        states = [edit_state(cur, e) for e in edits]
        for e, st in zip(edits, states):
            if st.startswith("broken"):
                raise SystemExit("%s: edit %r: %s" % (path, e[1][:70], st))
        if len(set(states)) != 1:
            raise SystemExit("%s: some edits applied, some not: %s" % (path, states))
        plan.append((path, edits, raw, eol, cur, states[0]))
    for path, (old, new) in SWAPS.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            raise SystemExit("%s is missing: apply r99_interior-exposure first" % path)
        data = open(full, "rb").read()
        if data == disk(new): state = "applied"
        elif sha(data) == OLD_SHA[path]: state = "clean"
        else: raise SystemExit("%s is neither r99's nor r99b's version (changed by someone else?)" % path)
        plan.append((path, None, data, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]

    def result_texts(direction):
        texts = {}
        for path, edits, raw, eol, cur, _ in edited:
            for kind, a, b in edits:
                cur = cur.replace(a, b) if direction == "apply" else cur.replace(b, a)
            texts[path] = cur
        return texts

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            text_checks(result_texts("apply"))
            print("not applied; would apply (%d files edited, %d swapped from r99's version; text "
                  "checks on the result pass)" % (len(edited), len(SWAPS)))
        return
    if cmd == "apply" and state == "applied":
        print("already applied"); return
    if cmd == "revert" and state != "applied":
        print("nothing to revert"); return
    texts = result_texts(cmd)
    if cmd == "apply":
        text_checks(texts)
    outs = []
    for path, edits, raw, eol, cur, _ in edited:
        outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
    for path, (old, new) in SWAPS.items():
        data = next(p[2] for p in plan if p[0] == path)
        outs.append((path, disk(new) if cmd == "apply" else disk(old), data))
    if cmd == "apply":
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
    written = []
    try:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r99btmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, os.path.join(ROOT, path))
            written.append((path, raw))
    except Exception:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r99btmp"
            if os.path.exists(tmp): os.remove(tmp)
        for path, raw in written:
            open(os.path.join(ROOT, path), "wb").write(raw)
        raise
    print("applied" if cmd == "apply" else "reverted")


main()
