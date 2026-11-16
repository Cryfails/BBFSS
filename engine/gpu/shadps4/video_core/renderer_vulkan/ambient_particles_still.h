// SPDX-License-Identifier: GPL-3.0-or-later
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
