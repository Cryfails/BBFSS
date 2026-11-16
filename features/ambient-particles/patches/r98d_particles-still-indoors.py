# r98d_particles-still-indoors: FEATURE fix (ambient particles), on top of r98 .fixed, r98b, r98c .fixed
# (the reviewed one) and r116/r117 (the wind and its shelter field). Everything of it sits inside
# BB_PARTICLES (off by default: with BB_PARTICLES unset the Rasterizer makes no AmbientParticles, so none
# of this code runs); the two knobs below default to 1 inside it (as BB_PARTICLES_LAMPS does) and 0 gives
# the r98c behaviour exactly.
#
# Owner (build 72, 4K): "Particles are also flying with the win in the church" and "including the wind
# and particles in the dark interior" (the library).
#
# Cause (read in the tree and in the owner's log): r117's State::Advance takes the camera's open share of
# air (WindShelter::CameraOpen, 0 indoors) into Snapshot::wind, but the motes read the wind through
# BbWind::Felt (r116: WindAt = speed x gust front x heading), which never sees it. The owner's log:
# "Wind shelter (r117): ... at the camera 1.00" (fully sheltered) and, in the same run, "followers ...
# motes 211.3/0.88": the motes took 0.88 x the 4 m/s wind, 0.8 x of it as the lattice's drift (2.8 m/s).
#
# What it changes for the eye (with BB_PARTICLES above 0 and the field, BB_WIND=1 with BB_WIND_SHELTER):
#  - BB_PARTICLES_STILL (0-1, unset 1): the camera's open share of air (followed over 0.5 s) gives an air
#    share 1 - still x (1 - open); the lattice drift and the flames' embers move at that share of the
#    wind and the rest at the calm drift (0.06 / 0.04 m/s): indoors they only float slowly, outdoors
#    exactly as before (open 1 gives share 1 and the same floats; no field gives open 1 always).
#  - BB_PARTICLES_DARK (0-1, unset 1): indoors (the same share) a dust mote's picture-behind light is
#    faded by smoothstep(0.12, 0.40, luma of the picture behind it): a dim wall no longer shows a faint
#    dot at every mote; lamp light on a mote and embers are not faded. Outdoors the share is 0.
#  - Log: once-line "Ambient particles (r98d, BB_PARTICLES_STILL=..., BB_PARTICLES_DARK=...)" and every
#    10 s "Ambient particles (r98d): the camera's open air ... air share ... still in N of M frames, the
#    lattice moved D m in S s".
# Off guarantee: BB_PARTICLES unset/0: no object, no draw, no call of any new code. On with both knobs 0
# (or without the field: open is always 1): AirShare is exactly 1, the shade exactly 0, Drift::Advance
# takes its old branch with the same floats, SparkDrift too, the shader's mix(1.0, x, 0.0) is exactly 1.
#
# Files (each edit's text found exactly once, else nothing is written):
#  - new renderer_vulkan/ambient_particles_still.h (pure: knobs, open follow, air share, shade, stats);
#  - renderer_vulkan/ambient_particles.h: Drift::speed and Advance's share;
#  - renderer_vulkan/ambient_particles_lamps.h: SparkDrift's share, the LampBlock word's comment;
#  - host_shaders/ambient_particles_layout.h: AP_DARK_LO / AP_DARK_HI;
#  - host_shaders/ambient_particles.vert: the dust's fade by lamp_wind.w (ambient_particles.frag unchanged);
#  - renderer_vulkan/vk_ambient_particles.h/.cpp: Draw's open argument, the air share, the shade, the lines;
#  - renderer_vulkan/vk_rasterizer.cpp: the one Draw call passes wind_shelter->CameraOpen();
#  - tests/test_ambient_particles.cpp: checks of the new header;
#  - README.md: the intro sentence and the two rows.
#
# Use: python -I -X utf8 r98d_particles-still-indoors.py check | apply | revert. Root from R98D_ROOT, else
# <tree>. Line ends of each file kept (CRLF in the tree). Originals of the edited files are copied to
# r98d_backup/ next to this script at apply; revert removes the new file.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r98d_backup")
ROOT = os.environ.get("R98D_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TAG = "r98d_particles-still-indoors"

# ---------------------------------------------------------------- new pure header
STILL_H = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r98d_particles-still-indoors): the ambient motes in sheltered air, without Vulkan
// (tests/test_ambient_particles.cpp builds it alone; vk_ambient_particles.cpp uses it).
//
// The fault (owner, build 72, the church and the library): the motes drifted with the wind indoors.
// The shared wind (bbport_wind.h) is the open wind; its shelter (r117, BB_WIND_SHELTER) is the
// share of it the field takes away at the camera (WindShelter::CameraOpen: 1 in the open, 0
// indoors). The wind's own State::Advance applies it to Snapshot::wind, but the motes read the
// wind through BbWind::Felt (r116: speed x gust front x heading), which does not, so the motes
// went with the full open wind. The camera's open share now reaches the motes:
//  - the air share = 1 - still x (1 - open): the lattice's drift and the flames' embers move at
//    that share of the wind's velocity plus the rest at the calm drift (0.06 / 0.04 m/s), so
//    indoors the motes only float slowly (their own sinking and wobble, the calm drift) and in
//    the open nothing changes (open 1 gives the share 1 exactly: the same floats as before);
//  - the indoor shade = dark x (1 - open): a dust mote's own colour is the light of the picture
//    behind it times 1.5, so in a dark room it still showed as a faint dot over a dim wall; the
//    shade fades that term by smoothstep(AP_DARK_LO, AP_DARK_HI, luma of the light behind) in
//    proportion to the shade (ambient_particles.vert, Lamps block word lamp_wind.w), so a mote
//    shows indoors where the picture behind it is lit (or a lamp lights it: the lamps' light is
//    not faded). Nothing in the open (shade 0).
// `open` is smoothed over OpenTau s (the field at the camera can step at a doorway).
//
// Knobs (environment, read once by StillGet), both inside BB_PARTICLES (off without it):
//  - BB_PARTICLES_STILL: 0 to 1, unset or unreadable DefaultStill (1); 0 = the drift of before.
//  - BB_PARTICLES_DARK: 0 to 1, unset or unreadable DefaultDark (1); 0 = no fade.
// Both need the field: BB_WIND=1 with BB_WIND_SHELTER above 0 (without it `open` is always 1).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "../host_shaders/ambient_particles_layout.h"
#include "ambient_particles.h"

namespace Vulkan::AmbientMotes {

inline constexpr float DefaultStill = 1.0f;
inline constexpr float DefaultDark = 1.0f;
inline constexpr float OpenTau = 0.5f; ///< s: the camera's open share is followed over this
static_assert(AP_DARK_LO > 0.0 && AP_DARK_LO < AP_DARK_HI && AP_DARK_HI <= 1.0,
              "a smoothstep from a dark to a lit picture");

struct StillKnobs {
    float still = DefaultStill; ///< BB_PARTICLES_STILL, 0-1
    float dark = DefaultDark;   ///< BB_PARTICLES_DARK, 0-1
};

/// A knob's text as 0..1: unset, empty, unreadable or not finite gives `fallback`.
inline float ParseUnit(const char* text, float fallback) {
    return std::clamp(Number(text, fallback), 0.0f, 1.0f);
}

inline StillKnobs ParseStill(const char* still, const char* dark) {
    StillKnobs k;
    k.still = ParseUnit(still, DefaultStill);
    k.dark = ParseUnit(dark, DefaultDark);
    return k;
}

/// The knobs, read once.
inline const StillKnobs& StillGet() {
    static const StillKnobs knobs =
        ParseStill(std::getenv("BB_PARTICLES_STILL"), std::getenv("BB_PARTICLES_DARK"));
    return knobs;
}

/// `previous` moved toward `target` (the camera's open share, not finite: 1; clamped to 0..1) by a
/// step of `seconds` (not finite or negative: 0; at most MaxStep) with the time constant OpenTau.
/// previous == target gives previous itself.
inline float OpenFollow(float previous, float target, double seconds) {
    const float goal = std::isfinite(target) ? std::clamp(target, 0.0f, 1.0f) : 1.0f;
    const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
    const float k = float(1.0 - std::exp(-dt / double(OpenTau)));
    const float from = std::isfinite(previous) ? std::clamp(previous, 0.0f, 1.0f) : 1.0f;
    return std::clamp(from + (goal - from) * k, 0.0f, 1.0f);
}

/// The share of the wind's velocity the motes move at: 1 - still x (1 - open). open 1 or still 0
/// give exactly 1 (so: the same floats as before r98d); open 0 with still 1 gives 0.
inline float AirShare(float open, float still) {
    const float o = std::isfinite(open) ? std::clamp(open, 0.0f, 1.0f) : 1.0f;
    const float s = std::isfinite(still) ? std::clamp(still, 0.0f, 1.0f) : 0.0f;
    return 1.0f - s * (1.0f - o);
}

/// The indoor shade handed to the shader (0..1): dark x (1 - open); exactly 0 for open 1 or dark 0.
inline float IndoorShade(float open, float dark) {
    const float o = std::isfinite(open) ? std::clamp(open, 0.0f, 1.0f) : 1.0f;
    const float d = std::isfinite(dark) ? std::clamp(dark, 0.0f, 1.0f) : 0.0f;
    return d * (1.0f - o);
}

/// ambient_particles.vert's fade of a dust mote's picture-behind light for a picture of luma
/// `luma` (display-encoded) and the shade: mix(1, smoothstep(AP_DARK_LO, AP_DARK_HI, luma), shade).
/// The shader's formula in C++ (the test's check of the numbers).
inline float DarkFade(float luma, float shade) {
    const float t = std::clamp((luma - float(AP_DARK_LO)) / (float(AP_DARK_HI) - float(AP_DARK_LO)),
                               0.0f, 1.0f);
    const float s = t * t * (3.0f - 2.0f * t);
    return 1.0f * (1.0f - shade) + s * shade;
}

/// What the 10 s line of r98d says: the camera's open share, the air share the motes got, how far
/// the lattice moved.
struct StillStats {
    std::uint32_t frames = 0; ///< draws since the last line
    std::uint32_t still = 0;  ///< of them with an air share under 0.5
    float open_now = 1.0f, air_now = 1.0f;
    float open_min = 1.0f, open_max = 1.0f;
    float shade_max = 0.0f;
    double moved = 0.0;     ///< m the lattice moved
    double speed_now = 0.0; ///< m/s, the last step's

    void Add(float open, float air, float shade, double speed, double seconds) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        open_min = frames == 0 ? open : std::min(open_min, open);
        open_max = frames == 0 ? open : std::max(open_max, open);
        shade_max = std::max(shade_max, shade);
        open_now = open;
        air_now = air;
        speed_now = speed;
        moved += speed * dt;
        still += air < 0.5f ? 1u : 0u;
        ++frames;
    }
    /// The line (under 300 characters: the slot runs keep that many); `window` s since the last.
    int Text(char* out, std::size_t size, double window) const {
        return std::snprintf(out, size,
                             "Ambient particles (r98d): the camera's open air %.2f now (%.2f to %.2f), "
                             "air share %.2f, still in %u of %u frames, the lattice moved %.1f m in "
                             "%.1f s (%.2f m/s now), dark fade up to %.2f",
                             double(open_now), double(open_min), double(open_max), double(air_now),
                             still, frames, moved, window, speed_now, double(shade_max));
    }
};

} // namespace Vulkan::AmbientMotes
'''

NEW_FILES = {R + "ambient_particles_still.h": STILL_H}

# ---------------------------------------------------------------- ambient_particles.h
AH_SPEED_ANCHOR = "    std::array<double, 3> offset{}; ///< m, each in [0, Period)\n"
AH_SPEED_BLOCK = "    double speed = 0.0;              ///< m/s, the last step's (bbport r98d_particles-still-indoors)\n"

AH_ADV_OLD = r'''    /// One step of `seconds` (not finite or negative: 0; at most MaxStep). With `wind_on` the
    /// lattice moves at WindFollow x `wind` (m/s), else at CalmDrift.
    void Advance(double seconds, bool wind_on, const std::array<float, 3>& wind) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        time = Wrap(time + dt, TimeWrap);
        for (std::size_t i = 0; i < 3; ++i) {
            const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
            const double v = wind_on ? double(WindFollow) * double(w) : double(CalmDrift[i]);
            offset[i] = Wrap(offset[i] + v * dt, Period);
        }
    }
'''
AH_ADV_NEW = r'''    /// One step of `seconds` (not finite or negative: 0; at most MaxStep). With `wind_on` the
    /// lattice moves at WindFollow x `wind` (m/s), else at CalmDrift. bbport
    /// (r98d_particles-still-indoors): `share` (0-1, not finite: 1; ambient_particles_still.h's
    /// AirShare) is the part of that wind velocity that stays, the rest of the velocity is the calm
    /// drift; 1 gives the same floats as before. `speed` is the step's velocity (m/s).
    void Advance(double seconds, bool wind_on, const std::array<float, 3>& wind, float share = 1.0f) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        time = Wrap(time + dt, TimeWrap);
        const double kept = std::isfinite(share) ? std::clamp(double(share), 0.0, 1.0) : 1.0;
        double fast = 0.0;
        for (std::size_t i = 0; i < 3; ++i) {
            const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
            double v = wind_on ? double(WindFollow) * double(w) : double(CalmDrift[i]);
            if (wind_on && kept < 1.0) {
                v = v * kept + (1.0 - kept) * double(CalmDrift[i]);
            }
            fast += v * v;
            offset[i] = Wrap(offset[i] + v * dt, Period);
        }
        speed = std::sqrt(fast);
    }
'''

# ---------------------------------------------------------------- ambient_particles_lamps.h
AL_SPARK_OLD = r'''/// The embers' drift (m/s): SparkWindFollow x the wind with `wind_on` (a word not finite counts
/// as 0), else CalmDrift (the lattice's calm drift).
inline std::array<float, 3> SparkDrift(bool wind_on, const std::array<float, 3>& wind) {
    std::array<float, 3> d{};
    for (std::size_t i = 0; i < 3; ++i) {
        const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
        d[i] = wind_on ? SparkWindFollow * w : CalmDrift[i];
    }
    return d;
}
'''
AL_SPARK_NEW = r'''/// The embers' drift (m/s): SparkWindFollow x the wind with `wind_on` (a word not finite counts
/// as 0), else CalmDrift (the lattice's calm drift). bbport (r98d_particles-still-indoors):
/// `share` (0-1, not finite: 1) is the part of the wind that stays, the rest is the calm drift;
/// 1 gives the same floats as before.
inline std::array<float, 3> SparkDrift(bool wind_on, const std::array<float, 3>& wind,
                                       float share = 1.0f) {
    std::array<float, 3> d{};
    const float kept = std::isfinite(share) ? std::clamp(share, 0.0f, 1.0f) : 1.0f;
    for (std::size_t i = 0; i < 3; ++i) {
        const float w = std::isfinite(wind[i]) ? wind[i] : 0.0f;
        d[i] = wind_on ? SparkWindFollow * w : CalmDrift[i];
        if (wind_on && kept < 1.0f) {
            d[i] = d[i] * kept + (1.0f - kept) * CalmDrift[i];
        }
    }
    return d;
}
'''
AL_WIND_OLD = "    std::array<float, 4> wind{}; ///< the embers' drift xyz (m/s), unused\n"
AL_WIND_NEW = ("    std::array<float, 4> wind{}; ///< the embers' drift xyz (m/s); w: the indoor shade 0..1\n"
               "                                 ///< (r98d_particles-still-indoors, AmbientMotes::IndoorShade)\n")

# ---------------------------------------------------------------- ambient_particles_layout.h
LAYOUT_ANCHOR = "#define AP_EMBER_NEAR1 4.0\n"
LAYOUT_BLOCK = r'''
// bbport (r98d_particles-still-indoors): with the camera sheltered (the wind shelter field, shade
// lamp_wind.w above 0) a dust mote's picture-behind light counts by smoothstep(AP_DARK_LO,
// AP_DARK_HI, the luma of the light behind it, display-encoded) mixed in by the shade: nothing in a
// picture darker than AP_DARK_LO, in full from AP_DARK_HI. A lamp's own light on the mote is not
// faded.
#define AP_DARK_LO 0.12
#define AP_DARK_HI 0.40
'''

# ---------------------------------------------------------------- ambient_particles.vert
VERT_WIND_OLD = "    vec4 lamp_wind;                 // xyz: the embers' drift (m/s)\n"
VERT_WIND_NEW = ("    vec4 lamp_wind;                 // xyz: the embers' drift (m/s), w: the indoor shade 0..1\n"
                 "                                    // (r98d_particles-still-indoors: 0 in the open)\n")
VERT_COLOUR_OLD = ("        colour = min(hue * vec3(1.0, 0.96, 0.9) * (look.x * back) + look.w, "
                   "vec3(AP_MAX_COLOUR));\n")
VERT_COLOUR_NEW = r'''        // bbport (r98d_particles-still-indoors): with the camera sheltered (lamp_wind.w above 0) the
        // picture behind the mote counts only as far as it is lit (exactly 1 in the open).
        const float dark = mix(1.0, smoothstep(AP_DARK_LO, AP_DARK_HI, luma), lamp_wind.w);
        colour = min(hue * vec3(1.0, 0.96, 0.9) * (look.x * back * dark) + look.w, vec3(AP_MAX_COLOUR));
'''

# ---------------------------------------------------------------- vk_ambient_particles.h
VH_INC_ANCHOR = '#include "video_core/renderer_vulkan/ambient_particles_lamps.h" // bbport (r98c_particles-visible)\n'
VH_INC_BLOCK = '#include "video_core/renderer_vulkan/ambient_particles_still.h" // bbport (r98d_particles-still-indoors)\n'
VH_DRAW_OLD = r'''    void Draw(const TemporalUpscaler::UpscaledFrame& frame, const CameraMotion::Matrices& camera,
              bool wind_on, const std::array<float, 3>& wind);
'''
VH_DRAW_NEW = r'''    void Draw(const TemporalUpscaler::UpscaledFrame& frame, const CameraMotion::Matrices& camera,
              bool wind_on, const std::array<float, 3>& wind,
              float open = 1.0f); // bbport (r98d_particles-still-indoors): the camera's open share of
                                  // air (WindShelter::CameraOpen; 1 without the field)
'''
VH_MEMBER_ANCHOR = "    } lamp_window;\n"
VH_MEMBER_BLOCK = r'''    // bbport (r98d_particles-still-indoors): the camera's open share of air, followed (1: open),
    // and what the r98d line of the last 10 s says.
    float open_follow = 1.0f;
    AmbientMotes::StillStats still_stats;
'''

# ---------------------------------------------------------------- vk_ambient_particles.cpp
VC_CTOR_OLD = r'''                    "picture behind a mote only, embers anywhere (the r98b look)\n");
    }
}
'''
VC_CTOR_NEW = r'''                    "picture behind a mote only, embers anywhere (the r98b look)\n");
    }
    // bbport (r98d_particles-still-indoors)
    const auto& still_knobs = AmbientMotes::StillGet();
    std::printf("Ambient particles (r98d, BB_PARTICLES_STILL=%.2f, BB_PARTICLES_DARK=%.2f): where "
                "the wind shelter field says the camera is sheltered (BB_WIND=1 with "
                "BB_WIND_SHELTER above 0; the open share of air at the camera, followed over %.1f "
                "s) the lattice and the embers drift at the open share of the wind and the rest at "
                "the calm %.2f/%.2f m/s, and dust over a picture darker than luma %.2f fades "
                "(in full from %.2f); in the open nothing changes; without the field the share "
                "stays 1\n",
                double(still_knobs.still), double(still_knobs.dark), double(AmbientMotes::OpenTau),
                double(AmbientMotes::CalmDrift[0]), double(AmbientMotes::CalmDrift[2]),
                double(AP_DARK_LO), double(AP_DARK_HI));
}
'''
VC_SIG_OLD = r'''void AmbientParticles::Draw(const TemporalUpscaler::UpscaledFrame& frame,
                            const CameraMotion::Matrices& camera, bool wind_on,
                            const std::array<float, 3>& wind) {
'''
VC_SIG_NEW = r'''void AmbientParticles::Draw(const TemporalUpscaler::UpscaledFrame& frame,
                            const CameraMotion::Matrices& camera, bool wind_on,
                            const std::array<float, 3>& wind, float open) {
'''
VC_ADV_OLD = "    drift.Advance(seconds, wind_on, wind);\n"
VC_ADV_NEW = r'''    // bbport (r98d_particles-still-indoors): the camera's open share of air (r117's field; 1
    // without it) reaches the motes: the lattice and the embers drift at that share of the wind
    // and the rest at the calm drift; indoors a dust mote's picture-behind light fades if dark.
    const auto& still = AmbientMotes::StillGet();
    open_follow = AmbientMotes::OpenFollow(open_follow, open, seconds);
    const float air = AmbientMotes::AirShare(open_follow, still.still);
    const float shade = AmbientMotes::IndoorShade(open_follow, still.dark);
    drift.Advance(seconds, wind_on, wind, air);
    still_stats.Add(open_follow, air, shade, drift.speed, seconds);
'''
VC_SPARK_OLD = "                                  AmbientMotes::SparkDrift(wind_on, wind));\n"
VC_SPARK_NEW = "                                  AmbientMotes::SparkDrift(wind_on, wind, air)); // r98d\n"
VC_SHADE_ANCHOR = "    // The lattice's instances, then the flames' ember slots while the lamps are on.\n"
VC_SHADE_BLOCK = r'''    // bbport (r98d_particles-still-indoors): the indoor shade, for the dust's colour (0 in the open).
    lamp_block.wind[3] = shade;
'''
VC_LINE_OLD = "        lamp_window = {};\n        window = now;\n"
VC_LINE_NEW = r'''        // bbport (r98d_particles-still-indoors): the air the motes had in the same 10 s.
        char still_line[320];
        still_stats.Text(still_line, sizeof(still_line), elapsed);
        std::printf("%s\n", still_line);
        still_stats = {};
        lamp_window = {};
        window = now;
'''

# ---------------------------------------------------------------- vk_rasterizer.cpp
RAS_OLD = r'''                ambient_particles->Draw(frame, cam, w.on,
                                        BbWind::Felt(BbWind::Follower::Motes, w, cam.inv_view));
'''
RAS_NEW = r'''                // bbport (r98d_particles-still-indoors): the camera's open share of air (r117's
                // field: 0 indoors; 1 without it) is not in Felt's wind, so it goes alongside
                ambient_particles->Draw(frame, cam, w.on,
                                        BbWind::Felt(BbWind::Follower::Motes, w, cam.inv_view),
                                        wind_shelter ? wind_shelter->CameraOpen() : 1.0f);
'''

# ---------------------------------------------------------------- tests
T_INC_ANCHOR = '#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles_lamps.h" // r98c\n'
T_INC_BLOCK = '#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles_still.h" // r98d\n'
T_BODY_ANCHOR = '    std::printf("ambient-particles-test: %u cells, %s\\n", Instances,\n'
T_BODY_BLOCK = r'''    // g. bbport (r98d_particles-still-indoors): sheltered air (ambient_particles_still.h).
    {
        const StillKnobs unset = ParseStill(nullptr, nullptr);
        Expect(unset.still == 1.0f && unset.dark == 1.0f, "BB_PARTICLES_STILL and _DARK are 1 unset");
        const StillKnobs zero = ParseStill("0", "0");
        Expect(zero.still == 0.0f && zero.dark == 0.0f, "0 turns both off");
        const StillKnobs clamped = ParseStill("7", "-3");
        Expect(clamped.still == 1.0f && clamped.dark == 0.0f, "clamped to 0..1");
        const StillKnobs bad = ParseStill("abc", "nan");
        Expect(bad.still == 1.0f && bad.dark == 1.0f, "unreadable counts as unset");
        Expect(AirShare(1.0f, 1.0f) == 1.0f && AirShare(0.3f, 0.0f) == 1.0f,
               "open air, or still 0: the share is exactly 1");
        Expect(AirShare(0.0f, 1.0f) == 0.0f && Near(AirShare(0.5f, 0.5f), 0.75, 1e-6),
               "indoors the share is 0; open 0.5 with still 0.5 gives 0.75");
        Expect(AirShare(std::numeric_limits<float>::quiet_NaN(), 1.0f) == 1.0f,
               "an open share that is not a number counts as open");
        Expect(IndoorShade(1.0f, 1.0f) == 0.0f && IndoorShade(0.0f, 0.0f) == 0.0f &&
                   IndoorShade(0.0f, 1.0f) == 1.0f && Near(IndoorShade(0.25f, 0.5f), 0.375, 1e-6),
               "the shade is dark x (1 - open), exactly 0 in the open or with dark 0");
        Expect(OpenFollow(1.0f, 1.0f, 0.1) == 1.0f && OpenFollow(0.3f, 0.3f, 0.1) == 0.3f,
               "following the value it holds keeps it exactly");
        float followed = 1.0f;
        for (int i = 0; i < 10; ++i) {
            followed = OpenFollow(followed, 0.0f, 0.1);
        }
        Expect(Near(followed, std::exp(-1.0 / double(OpenTau)), 1e-4),
               "one second toward 0 leaves exp(-1 / OpenTau)");
        Expect(OpenFollow(1.0f, 0.0f, std::numeric_limits<double>::quiet_NaN()) == 1.0f,
               "a step that is not a number moves nothing");
        // The lattice's drift: share 1 is the drift of before (the formula written out), share 0
        // with the wind on is the calm drift, a half share is half and half; no wind: always calm.
        const std::array<float, 3> breeze{2.0f, 0.0f, -1.5f};
        Drift open_air, shelter, half, calm;
        std::array<double, 3> expected{};
        for (int i = 0; i < 100; ++i) {
            open_air.Advance(0.016, true, breeze, 1.0f);
            for (std::size_t a = 0; a < 3; ++a) {
                expected[a] = Wrap(expected[a] + double(WindFollow) * double(breeze[a]) * 0.016, Period);
            }
            shelter.Advance(0.1, true, breeze, 0.0f);
            half.Advance(0.1, true, breeze, 0.5f);
            calm.Advance(0.1, false, breeze, 0.0f);
        }
        Expect(open_air.offset == expected, "share 1 moves the lattice exactly as before");
        Expect(Near(shelter.offset[0], 0.6, 1e-6) && Near(shelter.offset[2], 0.4, 1e-6) &&
                   Near(shelter.speed, std::hypot(double(CalmDrift[0]), double(CalmDrift[2])), 1e-6),
               "share 0 with the wind on: the calm drift (10 s: 0.6 m and 0.4 m), speed 0.072 m/s");
        Expect(Near(half.offset[0], 10.0 * (0.5 * 1.6 + 0.5 * double(CalmDrift[0])), 1e-5) &&
                   Near(half.offset[2], Period + 10.0 * (0.5 * 0.8 * -1.5 + 0.5 * double(CalmDrift[2])), 1e-5),
               "a half share: half the wind's drift and half the calm drift");
        Expect(calm.offset == shelter.offset, "no wind: the calm drift whatever the share");
        Drift nan_share;
        nan_share.Advance(0.1, true, breeze, std::numeric_limits<float>::quiet_NaN());
        Expect(Near(nan_share.speed, std::hypot(1.6, 1.2), 1e-6), "a share that is not a number counts as 1");
        // The embers' drift.
        const std::array<float, 3> before = SparkDrift(true, breeze);
        Expect(before == SparkDrift(true, breeze, 1.0f) && before[0] == 2.0f && before[2] == -1.5f,
               "the embers' drift with share 1 is the wind, as before");
        Expect(SparkDrift(true, breeze, 0.0f) == CalmDrift && SparkDrift(false, breeze, 0.3f) == CalmDrift,
               "share 0 or no wind: the calm drift");
        Expect(Near(SparkDrift(true, breeze, 0.5f)[0], 0.5 * 2.0 + 0.5 * double(CalmDrift[0]), 1e-6),
               "a half share of the embers' drift");
        // The shader's fade, as C++.
        Expect(DarkFade(0.05f, 1.0f) == 0.0f && DarkFade(0.9f, 1.0f) == 1.0f && DarkFade(0.0f, 0.0f) == 1.0f &&
                   Near(DarkFade(0.26f, 1.0f), 0.5, 1e-5) && Near(DarkFade(0.12f, 0.5f), 0.5, 1e-6),
               "the dust's fade: nothing under 0.12, 1 from 0.40, half at 0.26; shade 0 changes nothing");
        // The line.
        StillStats stats;
        stats.Add(0.0f, 0.0f, 1.0f, 0.072, 0.1);
        stats.Add(0.2f, 0.2f, 0.8f, 0.072, 0.1);
        char line[400];
        const int length = stats.Text(line, sizeof(line), 10.0);
        Expect(length > 0 && length < 300 && stats.frames == 2 && stats.still == 2 &&
                   Near(stats.open_min, 0.0, 0.0) && Near(stats.open_max, 0.2, 1e-6) && Near(stats.moved, 0.0144, 1e-9) &&
                   std::strstr(line, "(r98d)") != nullptr,
               "the 10 s line: counts, range, under 300 characters");
        Expect(sizeof(LampBlock) == AP_LAMP_BLOCK_BYTES, "the block's word w changes no size");
    }

'''

# ---------------------------------------------------------------- README
README_INTRO_OLD = ("One look indoors and outdoors (the engine has no cheap test for an interior here); a mote "
                    "takes its light from the picture behind it and from the lamps near it "
                    "(`BB_PARTICLES_LAMPS`), so it shows where there is light and fades in the dark; flames "
                    "throw embers.")
README_INTRO_NEW = ("Where the wind shelter field (`BB_WIND=1` with `BB_WIND_SHELTER` above 0) says the camera "
                    "is sheltered, as indoors, the air stands still: the motes only float slowly and dust over "
                    "a dark picture fades (`BB_PARTICLES_STILL`, `BB_PARTICLES_DARK`); without the field it is "
                    "one look indoors and outdoors (the engine has no other cheap test for an interior here); "
                    "a mote takes its light from the picture behind it and from the lamps near it "
                    "(`BB_PARTICLES_LAMPS`), so it shows where there is light and fades in the dark; flames "
                    "throw embers.")
README_SHOW_ANCHOR = "| `BB_PARTICLES_SHOW` | Test only: `1` multiplies the motes' light by 2.5"
README_ROWS = (
    "| `BB_PARTICLES_STILL` | Still air in shelter, 0 to 1; unset or unreadable is 1; 0 gives the drift before it "
    "(the open wind's, indoors too). Needs the wind shelter field (`BB_WIND=1` with `BB_WIND_SHELTER` above 0: "
    "without it the camera's open share of air is always 1 and nothing changes). The camera's open share (1 in "
    "the open, 0 indoors: the field's value at the camera, followed over 0.5 s) gives the air share 1 - this x "
    "(1 - open); the lattice of motes and the embers the flames throw drift at that share of the wind's velocity "
    "(0.8 times it for the lattice) and the rest at the calm 0.06 m/s along x and 0.04 m/s along z, so indoors "
    "they only float slowly (their own sinking at 0.05 m/s and wobble) and in the open as before. The wind "
    "itself, the fog and the plants are not touched by this knob. The log says it once when on and every 10 s "
    "`Ambient particles (r98d): the camera's open air <o> now (<min> to <max>), air share <a>, still in <n> of "
    "<m> frames, the lattice moved <d> m in <s> s`. Cost: a few floats a frame | `1` |\n"
    "| `BB_PARTICLES_DARK` | Dust in a dark room, 0 to 1; unset or unreadable is 1; 0 turns it off. A dust mote's "
    "own colour is the light of the picture behind it times 1.5, so in a dim room it showed as a faint dot over "
    "every wall. With the camera sheltered (the field of `BB_PARTICLES_STILL`; the share is this x (1 - the "
    "camera's open share)) that light counts by smoothstep(0.12, 0.40, the luma of the picture behind it, "
    "display-encoded) mixed in by that share: nothing over a picture darker than luma 0.12, in full from 0.40. "
    "A lamp's own light on a mote (`BB_PARTICLES_LAMPS`) and embers are not faded, so dust still glows near "
    "lamps. In the open the share is 0 and nothing changes. `dark fade up to` in the 10 s line is the largest "
    "share. Cost: one smoothstep a dust mote on screen, not measured | `1` |\n")

# ---------------------------------------------------------------- the edit table
EDITS = {
    R + "ambient_particles.h": [
        ("after", AH_SPEED_ANCHOR, AH_SPEED_BLOCK),
        ("replace", AH_ADV_OLD, AH_ADV_NEW),
    ],
    R + "ambient_particles_lamps.h": [
        ("replace", AL_SPARK_OLD, AL_SPARK_NEW),
        ("replace", AL_WIND_OLD, AL_WIND_NEW),
    ],
    H + "ambient_particles_layout.h": [("after", LAYOUT_ANCHOR, LAYOUT_BLOCK)],
    H + "ambient_particles.vert": [
        ("replace", VERT_WIND_OLD, VERT_WIND_NEW),
        ("replace", VERT_COLOUR_OLD, VERT_COLOUR_NEW),
    ],
    R + "vk_ambient_particles.h": [
        ("after", VH_INC_ANCHOR, VH_INC_BLOCK),
        ("replace", VH_DRAW_OLD, VH_DRAW_NEW),
        ("after", VH_MEMBER_ANCHOR, VH_MEMBER_BLOCK),
    ],
    R + "vk_ambient_particles.cpp": [
        ("replace", VC_CTOR_OLD, VC_CTOR_NEW),
        ("replace", VC_SIG_OLD, VC_SIG_NEW),
        ("replace", VC_ADV_OLD, VC_ADV_NEW),
        ("replace", VC_SPARK_OLD, VC_SPARK_NEW),
        ("before", VC_SHADE_ANCHOR, VC_SHADE_BLOCK),
        ("replace", VC_LINE_OLD, VC_LINE_NEW),
    ],
    R + "vk_rasterizer.cpp": [("replace", RAS_OLD, RAS_NEW)],
    "engine/tests/test_ambient_particles.cpp": [
        ("after", T_INC_ANCHOR, T_INC_BLOCK),
        ("before", T_BODY_ANCHOR, T_BODY_BLOCK),
    ],
    "README.md": [
        ("replace", README_INTRO_OLD, README_INTRO_NEW),
        ("before", README_SHOW_ANCHOR, README_ROWS),
    ],
}

# After apply each file holds these texts this many times.
CHECKS = {
    R + "ambient_particles.h": [("double speed = 0.0;", 1), ("float share = 1.0f", 1),
                                ("if (wind_on && kept < 1.0)", 1)],
    R + "ambient_particles_lamps.h": [("float share = 1.0f", 1), ("if (wind_on && kept < 1.0f)", 1),
                                      ("unused", 0)],
    H + "ambient_particles_layout.h": [("#define AP_DARK_LO 0.12\n", 1), ("#define AP_DARK_HI 0.40\n", 1)],
    H + "ambient_particles.vert": [("lamp_wind.w", 2), ("mix(1.0, smoothstep(AP_DARK_LO, AP_DARK_HI, luma), lamp_wind.w)", 1),
                                   ("(look.x * back * dark)", 1), ("(look.x * back)", 0)],
    R + "vk_ambient_particles.h": [(TAG, 3), ("float open = 1.0f", 1), ("AmbientMotes::StillStats still_stats;", 1)],
    R + "vk_ambient_particles.cpp": [(TAG, 4), ("drift.Advance(seconds, wind_on, wind, air);", 1),
                                     ("drift.Advance(seconds, wind_on, wind);", 0),
                                     ("lamp_block.wind[3] = shade;", 1), ("SparkDrift(wind_on, wind, air)", 1),
                                     ("still_stats.Text(", 1), ("Ambient particles (r98d", 1),
                                     ("const std::array<float, 3>& wind, float open) {", 1)],
    R + "vk_rasterizer.cpp": [(TAG, 1), ("wind_shelter ? wind_shelter->CameraOpen() : 1.0f);", 1),
                              ("BbWind::Felt(BbWind::Follower::Motes, w, cam.inv_view)", 1)],
    "engine/tests/test_ambient_particles.cpp": [("// g. bbport (r98d", 1)],
    "README.md": [("`BB_PARTICLES_STILL`", 3), ("`BB_PARTICLES_DARK`", 2),
                  ("followed over 0.5 s", 1), ("smoothstep(0.12, 0.40", 1), ("the calm 0.06 m/s along x and 0.04 m/s along z", 1),
                  ("the air stands still", 1)],
}
# Texts that must come in this order.
ORDER = {
    R + "vk_ambient_particles.cpp": [
        "Ambient particles (r98c, BB_PARTICLES_LAMPS", "Ambient particles (r98d, BB_PARTICLES_STILL",
        "AmbientParticles::~AmbientParticles() {", "void AmbientParticles::Draw(",
        "open_follow = AmbientMotes::OpenFollow(", "drift.Advance(seconds, wind_on, wind, air);",
        "lamps.Update(", "SparkDrift(wind_on, wind, air)", "lamp_block.wind[3] = shade;",
        "The lattice's instances, then the flames'", "scheduler.RecordCrumb(",
        "Ambient particles (r98c): lamps in", "still_stats.Text(", "lamp_window = {};", "        window = now;"],
    H + "ambient_particles.vert": ["uniform Lamps {", "const float dark = mix(", "colour += lamp_lit;"],
    "README.md": ["| `BB_PARTICLES_LAMPS` |", "| `BB_PARTICLES_STILL` |", "| `BB_PARTICLES_DARK` |",
                  "| `BB_PARTICLES_SHOW` |", "### Wind (in development)"],
    "engine/tests/test_ambient_particles.cpp": ["// f. bbport (r98c", "// g. bbport (r98d", "std::printf(\"ambient-particles-test:"],
}


def pairs(path):
    out = []
    for kind, a, b in EDITS[path]:
        if kind == "replace":
            out.append((a, b))
        elif kind == "after":
            out.append((a, a + b))
        else:
            out.append((a, b + a))
    return out


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    for path in EDITS:
        for old, new in pairs(path):
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: text must be ASCII with LF in the script" % path)
    for path, text in NEW_FILES.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: text must be ASCII with LF in the script" % path)


def new_file_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if raw == NEW_FILES[path]:
        return "applied"
    raise SystemExit("%s exists with other content: refused" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R98D_ROOT)" % ROOT)
    plan, states = [], set()
    for path in NEW_FILES:
        states.add(new_file_state(path))
    for path in EDITS:
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("%s missing: apply r98, r98b and r98c (the .fixed) first" % path)
        raw, eol, cur = load(path)
        ps = pairs(path)
        done = sum(cur.count(new) == 1 for old, new in ps)
        todo = sum(cur.count(new) == 0 and cur.count(old) == 1 for old, new in ps)
        if done == len(ps):
            state = "applied"
        elif todo == len(ps):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits present, %d could be made (mixed or changed; r98c.fixed "
                             "must be in the tree)" % (path, done, len(ps), todo))
        plan.append((path, ps, raw, eol, cur))
        states.add(state)
    if len(states) != 1:
        raise SystemExit("mixed state: some files have this patch, some not")
    state = states.pop()
    if cmd in ("check", "apply"):
        texts = {}
        for path, ps, raw, eol, cur in plan:
            if state == "clean":
                for old, new in ps:
                    if cur.count(old) != 1 or cur.count(new) != 0:
                        raise SystemExit("%s: edit text not found once: %r" % (path, old[:70]))
                    cur = cur.replace(old, new, 1)
                for old, new in ps:
                    if cur.count(new) != 1:
                        raise SystemExit("%s: edits overlap: %r" % (path, new[:70]))
            texts[path] = cur
        text_checks(texts)
        if cmd == "check":
            if state == "applied":
                print("applied (text checks pass)")
            else:
                print("not applied; would apply (%d files edited, %d edits, %d new file; text checks "
                      "on the result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
            return
        if state == "applied":
            print("already applied")
            return
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8"), raw)
                for path, ps, raw, eol, cur in plan]
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written, created = [], []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r98dtmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
            for path, text in NEW_FILES.items():
                full = os.path.join(ROOT, path)
                open(full, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
                created.append(full)
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r98dtmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            for full in created:
                os.remove(full)
            raise
        print("applied (%d files edited, %d new)" % (len(plan), len(NEW_FILES)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path, ps, raw, eol, cur in plan:
        for old, new in reversed(ps):
            if cur.count(new) != 1:
                raise SystemExit("%s: edited text not found once" % path)
            cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files, %d new removed)" % (len(outs), len(NEW_FILES)))


main()
