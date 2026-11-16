// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block, without Vulkan
// (tests/test_ambient_particles.cpp builds this header alone; vk_ambient_particles.cpp draws).
//
// Knobs (environment, read once by Get(), at the Rasterizer's construction):
//  - BB_PARTICLES: the density, 0 to 2 (MaxDensity); unset, unreadable, not finite or 0: off.
//    A lattice cell (AP_CELL m) holds a mote with the chance OccupancyPerDensity x density, at
//    most MaxOccupancy. 1 is the intended look.
//  - BB_PARTICLES_EMBERS: the share of the motes that are embers, 0 to 1; DefaultEmbers when
//    unset or unreadable.
//  - BB_PARTICLES_SHOW: "1" (first character) exaggerates for tests: light gain ShowGain times,
//    size ShowSize times, and a colour floor ShowFloor so motes show in the dark too.
// The drift: real time (steps clamped to 0-MaxStep s), wrapped at TimeWrap s; the lattice moves
// with WindFollow x the shared wind (bbport_wind.h) when BB_WIND=1, else at CalmDrift m/s; each
// axis is wrapped into [0, Period) m (the hash's period, so the wrap moves nothing).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "../host_shaders/ambient_particles_layout.h"

namespace Vulkan::AmbientMotes {

inline constexpr float Cell = float(AP_CELL);
inline constexpr std::uint32_t Instances = std::uint32_t(AP_NX) * AP_NY * AP_NZ;
inline constexpr double Period = double(AP_PERIOD) * AP_CELL; ///< m: the field repeats
inline constexpr double MaxStep = 0.1;                        ///< s: the longest step
inline constexpr double TimeWrap = 4096.0;                    ///< s
inline constexpr float MaxDensity = 2.0f;
inline constexpr float OccupancyPerDensity = 0.30f;
inline constexpr float MaxOccupancy = 0.90f;
inline constexpr float DefaultEmbers = 0.08f;
inline constexpr float Gain = 1.5f;      ///< the light around a mote, times this
inline constexpr float ShowGain = 2.5f;  ///< BB_PARTICLES_SHOW=1: the gain times this,
inline constexpr float ShowSize = 1.6f;  ///< the size times this,
inline constexpr float ShowFloor = 0.05f; ///< and this added to the colour (display-encoded)
inline constexpr float WindFollow = 0.8f; ///< share of the wind's velocity the lattice drifts at
inline constexpr std::array<float, 3> CalmDrift{0.06f, 0.0f, 0.04f}; ///< m/s without BB_WIND

static_assert(AP_PERIOD > 0 && (AP_PERIOD & (AP_PERIOD - 1)) == 0, "the hash masks the cell");
static_assert(float(AP_CELL) * AP_PERIOD == 768.0f, "the wrap is exact in floats");
static_assert(AP_NX % 2 == 0 && AP_NY % 2 == 0 && AP_NZ % 2 == 0);
static_assert(AP_NEAR0 < AP_NEAR1 && AP_FAR0 < AP_FAR1 && AP_FAR_Y >= 1.0);
static_assert(AP_MOTE_LIFE_MIN < AP_MOTE_LIFE_MAX && AP_EMBER_LIFE_MIN < AP_EMBER_LIFE_MAX);
// Every place a mote can be seen (inside the fade) is covered by the lattice: the box reaches at
// least (N/2 - 1) cells from the camera on each side, and a mote strays from its cell at most by
// its rise over half a life plus its wobble.
inline constexpr double EmberStrayY =
    AP_EMBER_RISE * AP_EMBER_LIFE_MAX / 2.0 + AP_EMBER_WOBBLE * AP_WOBBLE_Y;
inline constexpr double MoteStrayY =
    -AP_MOTE_RISE * AP_MOTE_LIFE_MAX / 2.0 + AP_MOTE_WOBBLE * AP_WOBBLE_Y;
static_assert((AP_NY / 2 - 1) * AP_CELL - std::max(EmberStrayY, MoteStrayY) >= AP_FAR1 / AP_FAR_Y,
              "the vertical fade ends inside the lattice");
static_assert((AP_NX / 2 - 1) * AP_CELL - AP_EMBER_WOBBLE >= AP_FAR1 &&
                  (AP_NZ / 2 - 1) * AP_CELL - AP_EMBER_WOBBLE >= AP_FAR1,
              "the horizontal fade ends inside the lattice");

struct Knobs {
    float density = 0.0f;         ///< BB_PARTICLES, 0-MaxDensity; 0 is off
    float embers = DefaultEmbers; ///< BB_PARTICLES_EMBERS, 0-1
    bool show = false;            ///< BB_PARTICLES_SHOW=1
    [[nodiscard]] bool On() const {
        return density > 0.0f;
    }
};

/// A number from the environment's text; `fallback` when null, empty, unreadable or not finite.
inline float Number(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

inline Knobs Parse(const char* density, const char* embers, const char* show) {
    Knobs k;
    k.density = std::clamp(Number(density, 0.0f), 0.0f, MaxDensity);
    k.embers = std::clamp(Number(embers, DefaultEmbers), 0.0f, 1.0f);
    k.show = show != nullptr && show[0] == '1';
    return k;
}

/// The knobs, read once.
inline const Knobs& Get() {
    static const Knobs knobs = Parse(std::getenv("BB_PARTICLES"), std::getenv("BB_PARTICLES_EMBERS"),
                                     std::getenv("BB_PARTICLES_SHOW"));
    return knobs;
}

inline double Wrap(double v, double period) {
    double r = std::fmod(v, period);
    if (r < 0.0) {
        r += period;
    }
    return r >= period ? 0.0 : r;
}

/// The time and the lattice's drift.
struct Drift {
    double time = 0.0;               ///< s, in [0, TimeWrap)
    std::array<double, 3> offset{}; ///< m, each in [0, Period)
    double speed = 0.0;              ///< m/s, the last step's (bbport r98d_particles-still-indoors)

    /// One step of `seconds` (not finite or negative: 0; at most MaxStep). With `wind_on` the
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
};

/// ambient_particles.vert's push block; the layout is the GLSL block's (std430 push constants:
/// six 16-byte members).
struct Push {
    std::array<float, 12> view{};          ///< world to view, rows
    std::array<float, 4> proj{};           ///< x, y scale (ndc +y down), z scale, z offset
    std::array<float, 4> camera{};         ///< camera world xyz (m), time (s)
    std::array<float, 4> drift{};          ///< drift xyz (m), occupancy
    std::array<float, 4> look{};           ///< gain, ember share, size scale, colour floor
    std::array<std::uint32_t, 4> frame{};  ///< output size, render size, jitter, flags
};
static_assert(sizeof(Push) == AP_PUSH_BYTES && AP_PUSH_BYTES <= 128);
static_assert(offsetof(Push, proj) == 48 && offsetof(Push, camera) == 64 &&
              offsetof(Push, drift) == 80 && offsetof(Push, look) == 96 &&
              offsetof(Push, frame) == 112);

/// w | h << 16 (each below 65536).
inline std::uint32_t PackSize(std::uint32_t w, std::uint32_t h) {
    return (w & 0xffffu) | (h & 0xffffu) << 16;
}

/// One float as GLSL's packSnorm2x16 stores it (clamped to -1..1).
inline std::uint32_t Snorm16(float v) {
    const float c = std::isfinite(v) ? std::clamp(v, -1.0f, 1.0f) : 0.0f;
    return std::uint32_t(std::uint16_t(std::int16_t(std::lround(c * 32767.0f))));
}

/// GLSL's unpackSnorm2x16 of one half (the tests' check of Snorm16).
inline float Unsnorm16(std::uint32_t bits) {
    const auto v = std::int16_t(std::uint16_t(bits & 0xffffu));
    return std::clamp(float(v) / 32767.0f, -1.0f, 1.0f);
}

inline float Occupancy(const Knobs& k) {
    return std::min(OccupancyPerDensity * k.density, MaxOccupancy);
}

/// The push block of one draw. `view` and `inv_view`: 3x4 rows (CameraMotion::Matrices), the
/// camera's world place is inv_view's translation ([3], [7], [11]). `jitter`: the depth's
/// sub-pixel shift (render pixels, at most 1 each way). `scene_srgb`: the frame before the UI is
/// read through an sRGB view.
inline Push MakePush(const Knobs& k, const Drift& d, const std::array<float, 12>& view,
                     const std::array<float, 12>& inv_view, const std::array<float, 4>& proj,
                     std::uint32_t out_w, std::uint32_t out_h, std::uint32_t render_w,
                     std::uint32_t render_h, const std::array<float, 2>& jitter, bool scene_srgb) {
    Push p;
    p.view = view;
    p.proj = proj;
    p.camera = {inv_view[3], inv_view[7], inv_view[11], float(d.time)};
    p.drift = {float(d.offset[0]), float(d.offset[1]), float(d.offset[2]), Occupancy(k)};
    p.look = {Gain * (k.show ? ShowGain : 1.0f), k.embers, k.show ? ShowSize : 1.0f,
              k.show ? ShowFloor : 0.0f};
    p.frame = {PackSize(out_w, out_h), PackSize(render_w, render_h),
               Snorm16(jitter[0]) | Snorm16(jitter[1]) << 16,
               scene_srgb ? std::uint32_t(AP_FLAG_SCENE_SRGB) : 0u};
    return p;
}

} // namespace Vulkan::AmbientMotes
