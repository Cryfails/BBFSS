// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r97g_shelter-haze-sparks): the wind the heat haze and the weapon sparks feel, in sheltered air.
// Pure CPU, no Vulkan (tests/test_wind_felt_shelter.cpp builds it alone).
//
// The fault (owner, build 72: "Particles are also flying with the win in the church"; r98d fixed our ambient
// motes): BbWind::Felt (r116) is the wind AT the camera, WindAt = speed x gust front x heading, the OPEN wind.
// r117's shelter share reaches Snapshot::wind (State::Advance: the fog's drift, the caustics, the game's
// particle lean) but not Felt. Two followers still read Felt: the heat haze (the column's top leans with it)
// and the weapon sparks (the falling copies drift with it). Indoors the haze leaned and the sparks were pushed
// sideways by a wind that is not there.
//
// The rule (the one of r98d with its default BB_PARTICLES_STILL = 1): the camera's open share of air (1 in
// the open, 0 indoors: WindShelter::CameraOpen, 1 without the field), followed over OpenTau s (it can step at
// a doorway), scales the felt wind's vector. Indoors the vector is 0: the haze rises straight, the sparks fall
// without a push. In the open (share 1) the vector is multiplied by exactly 1.0f: the same floats as before.
// Without BB_WIND=1 (Snapshot::on false) nothing runs: the zero vector of WindAt, no state, no count.
//
// Every wind follower, as found in the tree (the grep of the snapshot reads), and how it is sheltered:
//  - the sun fog's march and noise drift, the caustics' drift, the game's particle lean (r122b): read
//    Snapshot::wind / off1 / off2, which State::Advance already scales by the open share (r117);
//  - the plants, the twigs and what hangs (r89, r89d, r112): per vertex on the GPU by r117's field;
//  - the ambient motes: r98d (AirShare of the followed open share);
//  - the heat haze and the weapon sparks: BbWindFelt::Felt below (this patch);
//  - the clouds and their shadows: aloft, they move with the open wind everywhere (nothing of it is a
//    drift of air at the camera).

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>

#include "bbport_wind.h"

namespace BbWindFelt {

inline constexpr float OpenTau = 0.5f;    ///< s: the camera's open share is followed over this
inline constexpr double JumpGap = 1.0;    ///< s: after a gap this long (or no earlier read) the share jumps

/// The camera's open share as 0..1; not finite (or missing) gives 1 (open air).
inline float Open01(float open) {
    return std::isfinite(open) ? std::clamp(open, 0.0f, 1.0f) : 1.0f;
}

/// `previous` moved toward `target` by a step of `seconds` with the time constant OpenTau
/// (r98d's OpenFollow with the same maths); previous == target gives previous itself.
inline float Follow(float previous, float target, double seconds) {
    const float goal = Open01(target);
    const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, JumpGap) : 0.0;
    const float k = float(1.0 - std::exp(-dt / double(OpenTau)));
    const float from = Open01(previous);
    return std::clamp(from + (goal - from) * k, 0.0f, 1.0f);
}

/// The followed share. Step(open, now) is called by every read of the felt wind (the haze once a frame
/// on the GPU command thread, the sparks per draw on the draw thread): atomics, no lock; two threads
/// reading at once can lose one small step of the follow, which the next read repeats.
class Air {
public:
    /// The share after the time `now_ns` (steady clock, ns): the first read, or one after JumpGap s without a
    /// read, takes the camera's share at once (a game that starts or loads indoors is still from its first
    /// frame); the others follow it over OpenTau.
    float Step(float open, std::int64_t now_ns) {
        const std::int64_t before = at_ns.exchange(now_ns, std::memory_order_relaxed);
        const double gap = before == 0 ? JumpGap : double(now_ns - before) * 1e-9;
        const float goal = Open01(open);
        const float next = gap >= JumpGap ? goal : Follow(value.load(std::memory_order_relaxed), goal, gap);
        value.store(next, std::memory_order_relaxed);
        return next;
    }
    float Value() const {
        return value.load(std::memory_order_relaxed);
    }

private:
    std::atomic<float> value{1.0f};
    std::atomic<std::int64_t> at_ns{0}; ///< 0: no read yet
};

/// What the 10 s line says: reads of each follower since the last line, the share now and the least.
struct Stats {
    std::atomic<std::uint32_t> haze{0}, sparks{0}, still{0};
    std::atomic<float> share_now{1.0f}, share_min{1.0f};
    std::atomic<bool> once{false};
};

inline Stats& Counts() {
    static Stats stats;
    return stats;
}

/// The one share (the camera's) the haze and the sparks both read.
inline Air& Shared() {
    static Air air;
    return air;
}

inline std::array<float, 3> Scale(const std::array<float, 3>& v, float share) {
    return {v[0] * share, v[1] * share, v[2] * share};
}

/// The felt wind of `f` (BbWind::Follower::Haze or Sparks): WindAt at the camera (`inv_view`: 3x4 rows,
/// translation in [3], [7], [11]) times the followed share, counted for `f` after the scale. The zero vector
/// without the wind (Snapshot::on false), as WindAt gives it, and nothing else happens. `air` and `now_ns`
/// are the follow's state and clock (the tests pass their own).
inline std::array<float, 3> FeltAt(BbWind::Follower f, const BbWind::Snapshot& s,
                                   const std::array<float, 12>& inv_view, float open, Air& air,
                                   std::int64_t now_ns) {
    std::array<float, 3> v = BbWind::WindAt(s, inv_view[3], inv_view[11]);
    if (!s.on) {
        return v;
    }
    const float share = air.Step(open, now_ns);
    v = Scale(v, share);
    BbWind::Use(f, s, v);
    Stats& c = Counts();
    (f == BbWind::Follower::Haze ? c.haze : c.sparks).fetch_add(1, std::memory_order_relaxed);
    if (share < 0.5f) {
        c.still.fetch_add(1, std::memory_order_relaxed);
    }
    c.share_now.store(share, std::memory_order_relaxed);
    if (share < c.share_min.load(std::memory_order_relaxed)) {
        c.share_min.store(share, std::memory_order_relaxed);
    }
    return v;
}

/// BbWind::Felt for the haze and the sparks: the wind at the camera in the shelter's air. `open` is the
/// camera's open share (WindShelter::CameraOpen; 1 without the field).
inline std::array<float, 3> Felt(BbWind::Follower f, const BbWind::Snapshot& s,
                                 const std::array<float, 12>& inv_view, float open) {
    const std::int64_t now = std::chrono::duration_cast<std::chrono::nanoseconds>(
                                 std::chrono::steady_clock::now().time_since_epoch())
                                 .count();
    return FeltAt(f, s, inv_view, open, Shared(), now);
}

/// The next line for the log (each 600 wind steps, about 10 s; under 300 characters): the first call
/// the once-line, then a line with the reads since the last one, none when nothing read the wind.
/// false: nothing to print. Resets the counts.
inline bool ReportText(char* out, std::size_t size) {
    Stats& c = Counts();
    if (!c.once.exchange(true, std::memory_order_relaxed)) {
        std::snprintf(out, size,
                      "Wind shelter for the haze and the sparks (r97g): the heat haze and the weapon sparks feel the "
                      "open wind times the camera's open share of air (r117's field, followed over 0.5 s; 1 without "
                      "BB_WIND_SHELTER): indoors the haze rises straight and the sparks fall without a sideways push");
        return true;
    }
    const std::uint32_t haze = c.haze.exchange(0, std::memory_order_relaxed);
    const std::uint32_t sparks = c.sparks.exchange(0, std::memory_order_relaxed);
    const std::uint32_t still = c.still.exchange(0, std::memory_order_relaxed);
    const float least = c.share_min.exchange(1.0f, std::memory_order_relaxed);
    if (haze == 0 && sparks == 0) {
        return false;
    }
    std::snprintf(out, size,
                  "Wind shelter (r97g): the haze read the wind %u times and the sparks %u times since the last line; "
                  "the camera's open air share %.2f now (least %.2f), under 0.5 in %u of the reads",
                  haze, sparks, double(c.share_now.load(std::memory_order_relaxed)), double(least), still);
    return true;
}

} // namespace BbWindFelt
