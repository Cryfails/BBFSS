// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the shared wind state and the CPU copy of the fog noise
// (gpu/shim/bbport_wind.h) and the sun fog's march step (m, n, q). The GLSL copy is
// checked on the GPU by tests/test_wind_noise.cpp.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "gpu/shim/bbport_wind.h"

using namespace BbWind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

template <typename T>
bool SameBits(const T& a, const T& b) {
    return std::memcmp(&a, &b, sizeof(T)) == 0;
}

/// Field by field, so the padding of Snapshot is not compared.
bool Same(const Snapshot& a, const Snapshot& b) {
    return SameBits(a.on, b.on) && SameBits(a.time, b.time) && SameBits(a.direction_deg, b.direction_deg) &&
           SameBits(a.dir_x, b.dir_x) && SameBits(a.dir_z, b.dir_z) && SameBits(a.speed, b.speed) &&
           SameBits(a.gust, b.gust) && SameBits(a.wind, b.wind) && SameBits(a.off1, b.off1) &&
           SameBits(a.off2, b.off2);
}

/// splitmix64: a seeded sequence that is the same with every compiler and library.
struct Random {
    std::uint64_t state;
    std::uint64_t Next() {
        std::uint64_t z = (state += 0x9e3779b97f4a7c15ull);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
        return z ^ (z >> 31);
    }
    double Unit() { // [0, 1)
        return double(Next() >> 11) * (1.0 / 9007199254740992.0);
    }
};

float Circular(float a, float b) {
    const float d = std::fabs(a - b);
    return std::min(d, float(Period) - d);
}

constexpr Params On{.on = true};

struct Run {
    double distance = 0.0; // m: the sum of |wind| * step as the snapshots report it
    Snapshot last{};
};

/// 60 s of wind at a fixed rate (hz > 0) or with seeded random steps in [0, 0.1] s (hz == 0);
/// the last step lands exactly on 60 s.
Run Sixty(double hz, Params p, std::uint64_t seed = 1) {
    State state;
    Random random{seed};
    Run run;
    double t = 0.0;
    const double end = 60.0;
    for (int n = 0; t < end; ++n) {
        const double next = hz > 0.0 ? double(n + 1) / hz : t + random.Unit() * MaxStep;
        const double dt = std::min(next, end) - t;
        state.Advance(p, dt);
        t += dt;
        const Snapshot s = state.Get();
        run.distance += std::hypot(double(s.wind[0]), double(s.wind[2])) * dt;
    }
    run.last = state.Get();
    return run;
}
} // namespace

int main() {
    char what[160];

    // a. The step is clamped to 0.1 s; a NaN, negative or infinite step moves nothing.
    {
        State a, b;
        a.Advance(On, 0.5);
        b.Advance(On, 0.1);
        Expect(Same(a.Get(), b.Get()), "one Advance(0.5) equals one Advance(0.1)");
        Expect(a.Get().time == 0.1, "a 0.5 s step counts as 0.1 s");
        State c;
        for (int i = 0; i < 50; ++i) {
            c.Advance(On, 1.0 / 60.0);
        }
        for (double bad : {std::numeric_limits<double>::quiet_NaN(), -1.0,
                           std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()}) {
            const Snapshot before = c.Get();
            c.Advance(On, bad);
            const Snapshot after = c.Get();
            std::snprintf(what, sizeof(what), "a step of %g leaves the offsets and the time", bad);
            Expect(SameBits(before.off1, after.off1) && SameBits(before.off2, after.off2) &&
                       SameBits(before.time, after.time),
                   what);
        }
    }

    // b. Frame-rate independence: 60 s at 30, 60 and 144 Hz and with random steps.
    for (const float gusts : {0.5f, 1.0f}) {
        Params p = On;
        p.gusts = gusts;
        const Run reference = Sixty(144.0, p);
        Expect(std::fabs(reference.last.time - 60.0) < 1e-9, "144 Hz ends at 60 s");
        for (const double hz : {30.0, 60.0, 0.0}) {
            const Run run = Sixty(hz, p, 7);
            const double rel = std::fabs(run.distance - reference.distance) / reference.distance;
            float worst = 0.0f;
            for (std::size_t i = 0; i < 3; ++i) {
                worst = std::max(worst, Circular(run.last.off1[i], reference.last.off1[i]));
                worst = std::max(worst, Circular(run.last.off2[i], reference.last.off2[i]));
            }
            std::printf("wind-test: gusts %.1f, %s: %.3f m against %.3f m at 144 Hz (%.3f%%), "
                        "offsets differ by %.5f cells at most\n",
                        double(gusts), hz > 0.0 ? (hz == 30.0 ? "30 Hz" : "60 Hz") : "random steps",
                        run.distance, reference.distance, rel * 100.0, double(worst));
            std::snprintf(what, sizeof(what), "gusts %.1f at %g Hz: distance within 1%% of 144 Hz",
                          double(gusts), hz);
            Expect(rel <= 0.01, what);
            std::snprintf(what, sizeof(what), "gusts %.1f at %g Hz: offsets within 0.01 cells of 144 Hz",
                          double(gusts), hz);
            Expect(worst <= 0.01f, what);
            Expect(std::fabs(run.last.time - 60.0) < 1e-9, "the run ends at 60 s");
        }
    }

    // c. Gusts.
    {
        bool exact = true;
        for (int i = 0; i < 1000; ++i) {
            exact = exact && Gust(double(i) * 3.7 + 0.123, 0.0f) == 1.0f;
        }
        Expect(exact, "gusts 0 give exactly 1");
        for (const float g : {0.5f, 1.0f}) {
            double sum = 0.0;
            float lo = 10.0f, hi = -10.0f, jump = 0.0f;
            const int samples = 3600 * 20;
            for (int i = 0; i < samples; ++i) {
                const double t = double(i) / 20.0;
                const float v = Gust(t, g);
                sum += v;
                lo = std::min(lo, v);
                hi = std::max(hi, v);
            }
            for (int i = 0; i < 360000; ++i) {
                const double t = double(i) * 0.01;
                jump = std::max(jump, std::fabs(Gust(t + 0.01, g) - Gust(t, g)));
            }
            const double mean = sum / samples;
            std::printf("wind-test: gusts %.1f: mean over 1 h %.4f, range %.3f-%.3f, largest change "
                        "in 0.01 s %.4f (GustCentre %.4f)\n",
                        double(g), mean, double(lo), double(hi), double(jump), double(GustCentre));
            std::snprintf(what, sizeof(what), "gusts %.1f stay in 0.3-2.0", double(g));
            Expect(lo >= GustMin && hi <= GustMax, what);
            std::snprintf(what, sizeof(what), "gusts %.1f: the 1 h mean is in 0.95-1.05", double(g));
            Expect(mean >= 0.95 && mean <= 1.05, what);
            if (g == 1.0f) {
                Expect(jump <= 0.04f, "gusts 1 change by 0.04 at most in 0.01 s");
            }
        }
    }

    // d. Wander and the direction vector.
    {
        for (const float base : {225.0f, 0.0f, 359.0f}) {
            bool inside = true;
            for (int i = 0; i <= 3600; ++i) {
                const float deg = WanderDeg(double(i), base);
                inside = inside && deg >= base - Wander && deg <= base + Wander;
            }
            std::snprintf(what, sizeof(what), "the direction stays within %g +- 15 deg over 1 h", double(base));
            Expect(inside, what);
        }
        bool unit = true;
        for (float deg = -720.0f; deg <= 720.0f; deg += 0.5f) {
            const auto d = DirectionXZ(deg);
            unit = unit && std::fabs(std::hypot(d[0], d[1]) - 1.0f) <= 1e-6f;
        }
        Expect(unit, "DirectionXZ has length 1");
        const auto east = DirectionXZ(0.0f), north = DirectionXZ(90.0f);
        Expect(std::fabs(east[0] - 1.0f) <= 1e-6f && std::fabs(east[1]) <= 1e-6f, "0 deg is +x");
        Expect(std::fabs(north[0]) <= 1e-6f && std::fabs(north[1] - 1.0f) <= 1e-6f, "90 deg is +z");
        // The snapshot's wind points along the direction.
        State s;
        s.Advance(On, 0.05);
        const Snapshot w = s.Get();
        Expect(w.direction_deg >= DefaultDirection - Wander && w.direction_deg <= DefaultDirection + Wander,
               "the first snapshot's direction is within the wander");
        const float along = w.wind[0] * w.dir_x + w.wind[2] * w.dir_z;
        Expect(std::fabs(along - w.speed * w.gust) <= 1e-5f && w.wind[1] == 0.0f,
               "the wind is speed * gust along (dir_x, 0, dir_z)");
    }

    // e. Off: Advance without on changes nothing.
    {
        State s;
        const Snapshot fresh = s.Get();
        s.Advance(Params{}, 0.05);
        Expect(Same(fresh, s.Get()) && !s.Get().on, "off leaves a fresh state as it is");
        for (int i = 0; i < 30; ++i) {
            s.Advance(On, 0.03);
        }
        const Snapshot before = s.Get();
        s.Advance(Params{.on = false, .direction_deg = 10.0f, .speed = 4.0f, .gusts = 1.0f}, 0.05);
        Expect(Same(before, s.Get()), "off leaves an advanced state as it is");
        s.Reset();
        Expect(Same(fresh, s.Get()), "Reset gives the fresh state");
        // With speed 0 the offsets stay where they are.
        State still;
        Params calm = On;
        calm.speed = 0.0f;
        for (int i = 0; i < 100; ++i) {
            still.Advance(calm, 0.05);
        }
        const Snapshot c = still.Get();
        Expect(c.off1 == std::array<float, 3>{} && c.off2 == std::array<float, 3>{} && c.time > 4.99,
               "speed 0 keeps the offsets at 0");
    }

    // Sanitize.
    {
        const float nan = std::numeric_limits<float>::quiet_NaN();
        const Params a = Sanitize({.on = true, .direction_deg = nan, .speed = nan, .gusts = nan});
        Expect(a.direction_deg == DefaultDirection && a.speed == DefaultSpeed && a.gusts == DefaultGusts,
               "non-finite values become the defaults");
        const Params b = Sanitize({.on = true, .direction_deg = -90.0f, .speed = 9.0f, .gusts = 2.0f});
        Expect(b.direction_deg == 270.0f && b.speed == MaxSpeed && b.gusts == MaxGusts,
               "-90 deg wraps to 270, speed and gusts clamp at their maxima");
        const Params c = Sanitize({.on = true, .direction_deg = 720.0f, .speed = -1.0f, .gusts = -1.0f});
        Expect(c.direction_deg == 0.0f && c.speed == 0.0f && c.gusts == 0.0f,
               "720 deg wraps to 0, speed and gusts clamp at 0");
        const float inf = std::numeric_limits<float>::infinity();
        Expect(Sanitize({.on = true, .direction_deg = inf, .speed = -inf, .gusts = inf}).speed == DefaultSpeed,
               "an infinite speed becomes the default");
        Expect(SanitizeContrast(nan) == DefaultContrast && SanitizeContrast(5.0f) == MaxContrast &&
                   SanitizeContrast(-1.0f) == 0.0f && SanitizeContrast(MaxContrast) == MaxContrast,
               "the contrast clamps to 0-MaxContrast, NaN gives DefaultContrast");
        // bbport (r88_wind-lamp-fog): the lamp fog's strength (BB_WIND_LAMP_FOG) and its contrast
        Expect(SanitizeLampFog(nan) == DefaultLampFog && SanitizeLampFog(inf) == DefaultLampFog &&
                   SanitizeLampFog(5.0f) == MaxLampFog && SanitizeLampFog(-1.0f) == 0.0f &&
                   SanitizeLampFog(MaxLampFog) == MaxLampFog,
               "the lamp fog's strength clamps to 0-MaxLampFog, NaN and inf give DefaultLampFog");
        Expect(LampFogContrast(0.0f) == 0.0f && LampFogContrast(DefaultLampFog) == LampFogGain &&
                   LampFogContrast(MaxLampFog) == 2.0f * LampFogGain,
               "the lamp fog's contrast is the strength times LampFogGain");
    }

    // f. The noise repeats every 256 cells. The points and offsets lie on a 1/1024 grid that
    // p / 12, p / 6 and p / 4.5 keep exact, so the comparison sees the lattice, not float rounding.
    {
        Random random{11};
        float worst = 0.0f;
        for (int i = 0; i < 100; ++i) {
            std::array<float, 3> p{}, o1{}, o2{}, w1{}, w2{};
            for (std::size_t k = 0; k < 3; ++k) {
                p[k] = 36.0f * float(random.Next() % 5689) / 1024.0f; // 0-200 m
                o1[k] = float(random.Next() % (256 * 1024)) / 1024.0f;
                o2[k] = float(random.Next() % (256 * 1024)) / 1024.0f;
                w1[k] = o1[k] + 256.0f;
                w2[k] = o2[k] - 256.0f;
            }
            worst = std::max(worst, std::fabs(Density(p, o1, o2, 0.4f) - Density(p, w1, w2, 0.4f)));
            worst = std::max(worst, std::fabs(Field(p, o1, o2) - Field(p, w1, o2)));
        }
        std::snprintf(what, sizeof(what), "an offset 256 cells on gives the same density (%.2g)", double(worst));
        Expect(worst <= 1e-5f, what);
    }

    // g. The density's mean.
    {
        Random random{5};
        double field = 0.0, density = 0.0;
        double lamp = 0.0; // bbport (r88_wind-lamp-fog): at the lamp fog's strongest contrast
        bool flat = true;
        const int count = 100000;
        const std::array<float, 3> o1{17.25f, 3.5f, 101.0f}, o2{44.0f, 200.5f, 9.75f};
        for (int i = 0; i < count; ++i) {
            const std::array<float, 3> p{float(random.Unit() * 200.0), float(random.Unit() * 200.0),
                                         float(random.Unit() * 200.0)};
            const float n = Field(p, o1, o2);
            field += n;
            density += Density(p, o1, o2, 0.4f);
            lamp += Density(p, o1, o2, LampFogContrast(MaxLampFog)); // bbport (r88_wind-lamp-fog)
            flat = flat && Density(p, o1, o2, 0.0f) == 1.0f && n >= 0.0f && n < 1.0f;
        }
        field /= count;
        density /= count;
        std::printf("wind-test: over %d points in a 200 m cube the mean of N is %.4f and of the "
                    "density at contrast 0.4 %.4f\n",
                    count, field, density);
        Expect(std::fabs(field - 0.5) <= 0.01, "the mean of N is 0.5 +- 0.01");
        Expect(std::fabs(density - 1.0) <= 0.02, "the mean density at contrast 0.4 is 1 +- 0.02");
        Expect(flat, "contrast 0 gives exactly 1, and N lies in [0, 1)");
        // bbport (r88_wind-lamp-fog): the lamp fog at its strongest (contrast
        // LampFogContrast(MaxLampFog) = 3) clips m at 0 where N < 1/3, which only adds: its mean
        // lies above the unclipped 1 + C (2 mean(N) - 1) by a few percent (CPU estimate 0.05)
        lamp /= count;
        const double unclipped = 1.0 + double(LampFogContrast(MaxLampFog)) * (2.0 * field - 1.0);
        std::printf("wind-test: the lamp fog's density at contrast %.2f has the mean %.4f (%.4f "
                    "without the clip at 0)\n",
                    double(LampFogContrast(MaxLampFog)), lamp, unclipped);
        Expect(lamp >= unclipped && lamp - unclipped <= 0.08,
               "the lamp fog's strongest contrast raises the mean density by 0-0.08 (clip at 0)");
    }

    // h. Noise3 at six points: the values the GLSL copy must give (printed by this test's first
    // run; a separate double-precision copy of Hash3 and Noise3 in Python gave them within 1e-7).
    {
        struct Pin {
            float x, y, z, value;
        };
        constexpr std::array<Pin, 6> pins{{
            {0.0f, 0.0f, 0.0f, 0.6081519f},
            {0.5f, 0.5f, 0.5f, 0.5781672f},
            {1.25f, 7.5f, -3.75f, 0.5259736f},
            {255.9f, 0.0f, 0.0f, 0.6062171f},
            {-0.3f, 12.7f, 100.1f, 0.4207422f},
            {3.0f, 3.0f, 3.0f, 0.4130008f},
        }};
        for (const Pin& pin : pins) {
            const float v = Noise3(pin.x, pin.y, pin.z);
            std::printf("wind-test: Noise3(%g, %g, %g) = %.7f\n", double(pin.x), double(pin.y), double(pin.z),
                        double(v));
            std::snprintf(what, sizeof(what), "Noise3(%g, %g, %g) is the pinned %.7f", double(pin.x),
                          double(pin.y), double(pin.z), double(pin.value));
            Expect(std::fabs(v - pin.value) <= 1e-6f, what);
        }
    }

    // i. GustAt with speed 0 (or NaN) does not divide by zero: both use the 0.1 m/s floor.
    {
        const float a = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f, 0.0f);
        const float b = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f,
                               std::numeric_limits<float>::quiet_NaN());
        const float floored = GustAt(12.0, 1.0f, 30.0f, -40.0f, -0.7071f, -0.7071f, 0.1f);
        Expect(std::isfinite(a) && std::isfinite(b), "GustAt with speed 0 or NaN is finite");
        Expect(a == floored && b == floored,"GustAt with speed 0 or NaN is GustAt at the 0.1 m/s floor");
        Expect(GustAt(12.0, 0.7f, 0.0f, 0.0f, 1.0f, 0.0f, 1.5f) == Gust(12.0, 0.7f),
               "GustAt at the origin is Gust");
        Expect(GustAt(12.0, 0.7f, 3.0f, 0.0f, 1.0f, 0.0f, 1.5f) == Gust(10.0, 0.7f),
               "GustAt 3 m downwind at 1.5 m/s is the gust of 2 s before");
    }

    // j. The offsets' absolute rates, from the plan's numbers written out here (not the header's
    // constants): octave 1 moves by wind / (12, 6, 12) m, octave 2 by wind * 1.6 / 4.5 m. A
    // steady wind (gusts 0) at 1.5 m/s, 20 s of 0.05 s steps; the wander turns it, so the
    // expected offsets sum each step's snapshot wind. With gusts 0 the wind is exactly 1.5 m/s.
    {
        State s;
        Params p = On;
        p.gusts = 0.0f;
        std::array<double, 3> moved{};
        double distance = 0.0;
        for (int i = 0; i < 400; ++i) {
            s.Advance(p, 0.05);
            const Snapshot w = s.Get();
            for (std::size_t k = 0; k < 3; ++k) {
                moved[k] += double(w.wind[k]) * 0.05;
            }
            distance += std::hypot(double(w.wind[0]), double(w.wind[2])) * 0.05;
        }
        const Snapshot w = s.Get();
        const std::array<double, 3> cell1{12.0, 6.0, 12.0};
        float worst = 0.0f;
        for (std::size_t k = 0; k < 3; ++k) {
            worst = std::max(worst, Circular(w.off1[k], float(WrapCells(moved[k] / cell1[k]))));
            worst = std::max(worst, Circular(w.off2[k], float(WrapCells(moved[k] * 1.6 / 4.5))));
        }
        std::printf("wind-test: a steady 1.5 m/s for 20 s: %.4f m, offsets %.4f %.4f / %.4f %.4f "
                    "cells, %.2g from the plan's rates\n",
                    distance, double(w.off1[0]), double(w.off1[2]), double(w.off2[0]), double(w.off2[2]),
                    double(worst));
        Expect(std::fabs(distance - 30.0) <= 1e-4, "a steady 1.5 m/s wind covers 30 m in 20 s");
        Expect(worst <= 1e-4f, "the offsets move by wind / (12, 6, 12) m and wind * 1.6 / 4.5 m");
        Expect(w.off1[1] == 0.0f && w.off2[1] == 0.0f, "the y offsets stay 0");
    }

    // k. Field at world points with non-zero offsets: ties the 12 / 6 / 4.5 m scales, the
    // 0.65 / 0.35 weights and the offsets' sign, beside the Noise3 pins (h). The values the GLSL
    // copy of Field must give (printed by this test's first run; a separate Python copy that
    // rounds the coordinates to float32 the same way and runs Noise3 in double agreed within 1e-7).
    {
        struct Pin {
            std::array<float, 3> p, o1, o2;
            float value;
        };
        const std::array<Pin, 4> pins{{
            {{0.0f, 0.0f, 0.0f}, {0.25f, 0.5f, 0.75f}, {1.5f, 2.25f, 3.0f}, 0.2916170f},
            {{13.0f, 7.0f, -25.0f}, {3.125f, 0.0f, 250.5f}, {17.75f, 0.0f, 128.0f}, 0.4034448f},
            {{101.3f, 2.4f, 57.9f}, {200.0f, 0.0f, 33.3f}, {5.5f, 0.0f, 99.9f}, 0.6770673f},
            {{-48.6f, 15.2f, 211.7f}, {12.75f, 0.0f, 0.5f}, {255.5f, 0.0f, 64.25f}, 0.3751206f},
        }};
        for (const Pin& pin : pins) {
            const float v = Field(pin.p, pin.o1, pin.o2);
            std::printf("wind-test: Field(%g, %g, %g; %g %g %g; %g %g %g) = %.7f, density at 0.4 %.7f\n",
                        double(pin.p[0]), double(pin.p[1]), double(pin.p[2]), double(pin.o1[0]),
                        double(pin.o1[1]), double(pin.o1[2]), double(pin.o2[0]), double(pin.o2[1]),
                        double(pin.o2[2]), double(v), double(Density(pin.p, pin.o1, pin.o2, 0.4f)));
            std::snprintf(what, sizeof(what), "Field at (%g, %g, %g) is the pinned %.7f", double(pin.p[0]),
                          double(pin.p[1]), double(pin.p[2]), double(pin.value));
            Expect(std::fabs(v - pin.value) <= 1e-6f, what);
            const float m = Density(pin.p, pin.o1, pin.o2, 0.4f);
            Expect(std::fabs(m - std::max(0.0f, 1.0f + 0.4f * (2.0f * pin.value - 1.0f))) <= 1e-6f,
                   "Density is max(0, 1 + 0.4 (2 Field - 1))");
        }
    }

    // l. The direction and the gust are taken at the NEW wind time (after the step), as Advance
    // says: after 600 steps of 0.1 s the snapshot equals Gust and WanderDeg at the snapshot's time.
    // Taken at the time before the step they would differ by about the change over 0.1 s, which
    // the test prints.
    {
        State s;
        Params p = On;
        p.gusts = 1.0f;
        for (int i = 0; i < 600; ++i) {
            s.Advance(p, 0.1);
        }
        const Snapshot w = s.Get();
        float deg = std::fmod(WanderDeg(w.time, DefaultDirection), 360.0f);
        if (deg < 0.0f) {
            deg += 360.0f;
        }
        const float old_gust = Gust(w.time - 0.1, 1.0f);
        const float old_deg = WanderDeg(w.time - 0.1, DefaultDirection);
        std::printf("wind-test: at %.1f s the gust %.6f (at the step's start %.6f), direction %.5f "
                    "(at the step's start %.5f)\n",
                    w.time, double(w.gust), double(old_gust), double(w.direction_deg), double(old_deg));
        Expect(std::fabs(w.gust - Gust(w.time, 1.0f)) <= 1e-6f, "the gust is taken at the new time");
        Expect(std::fabs(w.direction_deg - deg) <= 1e-5f, "the direction is taken at the new time");
        Expect(std::fabs(old_gust - w.gust) > 1e-4f && std::fabs(old_deg - w.direction_deg) > 1e-4f,
               "this check can tell the new time from the old one");
    }

    // m. The march step at m = 1 gives the bits of the march without wind
    // (volumetric_light.comp's plain line), for 2000 random rays of 32 steps, and excess stays 0.
    {
        Random random{59};
        bool same = true, zero = true;
        for (int ray = 0; ray < 2000; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            float plain = 0.0f;
            March march;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Next() % 5) * 0.25f;
                plain += std::exp(-density * t) * density * ds * vis;
                MarchStep(march, density, t, ds, jitter, 1.0f, vis);
                same = same && SameBits(plain, march.energy);
                zero = zero && SameBits(march.excess, 0.0f);
            }
        }
        Expect(same, "MarchStep at m = 1 gives the bits of exp(-density t) density ds vis");
        Expect(zero, "MarchStep at m = 1 keeps excess at +0");
    }

    // n. With the noise the step is the plan's: s = density m, energy += exp(-(tau + s jitter ds))
    // s ds vis, tau += s ds (in double here); a constant m = k is a fog k times as dense; the last
    // optical depth density (t_end + excess) is density times the sum of m ds.
    {
        Random random{60};
        double worst = 0.0, worst_k = 0.0, worst_tau = 0.0;
        for (int ray = 0; ray < 500; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            const float contrast = MaxContrast * float(random.Unit());
            const float k = float(0.1 + 1.8 * random.Unit());
            std::array<float, 3> start{}, dir{}, o1{}, o2{};
            double length = 0.0;
            for (std::size_t a = 0; a < 3; ++a) {
                start[a] = float(random.Unit() * 400.0 - 200.0);
                dir[a] = float(random.Unit() * 2.0 - 1.0);
                length += double(dir[a]) * dir[a];
                o1[a] = float(random.Unit() * 256.0);
                o2[a] = float(random.Unit() * 256.0);
            }
            for (auto& d : dir) {
                d = float(d / std::sqrt(length));
            }
            March march, constant;
            float plain_k = 0.0f;
            double energy = 0.0, tau = 0.0, sum = 0.0;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Unit());
                const std::array<float, 3> at{start[0] + dir[0] * t, start[1] + dir[1] * t,
                                              start[2] + dir[2] * t};
                const float m = Density(at, o1, o2, contrast);
                MarchStep(march, density, t, ds, jitter, m, vis);
                const double s = double(density) * m;
                energy += std::exp(-(tau + s * jitter * ds)) * s * ds * vis;
                tau += s * ds;
                sum += double(m) * ds;
                MarchStep(constant, density, t, ds, jitter, k, vis);
                plain_k += std::exp(-(density * k) * t) * (density * k) * ds * vis;
            }
            const double end = 32.0 * ds; // the march's length: t + excess then is the sum of m ds
            worst = std::max(worst, std::fabs(march.energy - energy) / std::max(energy, 1e-12));
            worst_k = std::max(worst_k, std::fabs(double(constant.energy) - plain_k) /
                                            std::max(double(plain_k), 1e-12));
            const double depth = double(density) * (end + march.excess);
            worst_tau = std::max(worst_tau, std::fabs(depth - double(density) * sum) /
                                                std::max(double(density) * sum, 1e-12));
        }
        std::printf("wind-test: march with the noise against the plan's tau form %.2g, constant m "
                    "against a denser fog %.2g, last optical depth %.2g (relative, at most)\n",
                    worst, worst_k, worst_tau);
        Expect(worst <= 1e-5, "MarchStep is the plan's step (tau + s jitter ds) within 1e-5");
        Expect(worst_k <= 1e-5, "a constant m = k marches like a fog k times as dense within 1e-5");
        Expect(worst_tau <= 1e-5, "density (t_end + excess) is density times the sum of m ds");
    }

    // o. The noise's correlation lengths: the lag at which N's autocorrelation along x, y and z
    // falls to 0.5 is within 10% of what 12 m across, 6 m up and 4.5 m give, predicted from
    // Noise3's own autocorrelation on its unit lattice as (0.65^2 r(lag / L1) + 0.35^2
    // r(lag / 4.5 m)) / (0.65^2 + 0.35^2) (the two octaves are independent: other offsets, other
    // cells).
    {
        constexpr int Points = 6000;
        Random random{61};
        std::vector<std::array<float, 3>> base(Points);
        for (auto& b : base) {
            for (auto& c : b) {
                c = float(random.Unit() * 240.0);
            }
        }
        const auto correlation = [&](auto value, std::size_t axis, float lag) {
            double sa = 0.0, sb = 0.0, saa = 0.0, sbb = 0.0, sab = 0.0;
            for (const auto& b : base) {
                auto moved = b;
                moved[axis] += lag;
                const double x = value(b), y = value(moved);
                sa += x;
                sb += y;
                saa += x * x;
                sbb += y * y;
                sab += x * y;
            }
            const double n = Points;
            const double cov = sab / n - sa / n * (sb / n);
            return cov / std::sqrt((saa / n - sa / n * (sa / n)) * (sbb / n - sb / n * (sb / n)));
        };
        // Noise3's own autocorrelation on its lattice, 1/32 cell apart up to 3 cells.
        std::array<double, 97> unit{};
        const auto noise = [](const std::array<float, 3>& p) {
            return double(Noise3(p[0], p[1], p[2]));
        };
        for (std::size_t k = 0; k < unit.size(); ++k) {
            unit[k] = correlation(noise, 0, float(k) / 32.0f);
        }
        const auto unit_at = [&](double cells) {
            const double at = std::min(cells * 32.0, double(unit.size() - 1));
            const std::size_t lo = std::min(std::size_t(at), unit.size() - 2);
            return unit[lo] + (unit[lo + 1] - unit[lo]) * (at - double(lo));
        };
        // The first lag (m, 0.05 m apart) at which a correlation falls under 0.5, interpolated.
        const auto half = [](auto rho) {
            double before = 1.0;
            for (int k = 1; k <= 600; ++k) {
                const double now = rho(k * 0.05);
                if (now < 0.5) {
                    return (k - 1 + (before - 0.5) / (before - now)) * 0.05;
                }
                before = now;
            }
            return 30.0;
        };
        const std::array<float, 3> o1{10.5f, 20.25f, 30.75f}, o2{140.5f, 7.25f, 99.0f};
        const auto field = [&](const std::array<float, 3>& p) { return double(Field(p, o1, o2)); };
        constexpr std::array<double, 3> across{12.0, 6.0, 12.0};
        constexpr const char* names[3] = {"x", "y", "z"};
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double model = half([&](double lag) {
                return (0.4225 * unit_at(lag / across[axis]) + 0.1225 * unit_at(lag / 4.5)) / 0.545;
            });
            // Bisection on the measured correlation, from the model's neighbourhood outwards.
            double lo = 0.0, hi = 3.0 * model;
            for (int step = 0; step < 24; ++step) {
                const double mid = 0.5 * (lo + hi);
                (correlation(field, axis, float(mid)) < 0.5 ? hi : lo) = mid;
            }
            const double measured = 0.5 * (lo + hi);
            std::printf("wind-test: N's autocorrelation along %s falls to 0.5 at %.3f m (the "
                        "wavelengths give %.3f m)\n",
                        names[axis], measured, model);
            std::snprintf(what, sizeof(what),
                          "the correlation length along %s is within 10%% of the wavelengths'",
                          names[axis]);
            Expect(std::fabs(measured / model - 1.0) <= 0.10, what);
        }
    }


    // p. ViewToWorld on a turned and moved camera (rows as
    // CameraMotion::PassMatrices().inv_view stores them, translation in [3], [7], [11]): the view
    // origin goes to the translation, view +z 10 m ahead to translation + 10 times the third
    // column. ViewShade stretches m over 1 - C to 1 + C. The mean of m at the default contrast
    // and at the largest stays 1 +- 0.03 (at 2, m is clipped at 0 where N < 0.25).
    {
        // 90 deg about y: view +x looks toward world -z, view +z toward world +x.
        const std::array<float, 12> rows{0, 0, 1, 5, 0, 1, 0, -2, -1, 0, 0, 7};
        const auto o = ViewToWorld(rows, {0.0f, 0.0f, 0.0f});
        const auto z = ViewToWorld(rows, {0.0f, 0.0f, 10.0f});
        const auto x = ViewToWorld(rows, {3.0f, 0.0f, 0.0f});
        Expect(o == std::array<float, 3>{5.0f, -2.0f, 7.0f}, "ViewToWorld: the origin goes to the translation");
        Expect(z == std::array<float, 3>{15.0f, -2.0f, 7.0f}, "ViewToWorld: view +z goes along the third column");
        Expect(x == std::array<float, 3>{5.0f, -2.0f, 4.0f}, "ViewToWorld: view +x goes along the first column");
        Expect(ViewShade(1.0f, 0.0f) == 0.5f && ViewShade(1.0f, 0.5f) == 0.5f &&
                   ViewShade(0.5f, 0.5f) == 0.0f && ViewShade(1.5f, 0.5f) == 1.0f &&
                   ViewShade(0.0f, 2.0f) == 0.25f && ViewShade(9.0f, 1.0f) == 1.0f &&
                   ViewShade(1.0f, std::numeric_limits<float>::quiet_NaN()) == 0.5f,
               "ViewShade: 1 - C is 0, 1 is 0.5, 1 + C is 1, clamped; 0.5 at contrast 0 or NaN");
        Random random{62};
        const std::array<float, 3> o1{3.5f, 9.25f, 71.0f}, o2{120.0f, 33.5f, 2.75f};
        double at_default = 0.0, at_max = 0.0, shade = 0.0;
        const int count = 100000;
        for (int i = 0; i < count; ++i) {
            const std::array<float, 3> p{float(random.Unit() * 200.0), float(random.Unit() * 200.0),
                                         float(random.Unit() * 200.0)};
            const float m = Density(p, o1, o2, DefaultContrast);
            at_default += m;
            at_max += Density(p, o1, o2, MaxContrast);
            shade += std::fabs(ViewShade(m, DefaultContrast) - Field(p, o1, o2));
        }
        std::printf("wind-test: the mean density at the default contrast %.2f is %.4f, at the "
                    "largest %.2f %.4f\n",
                    double(DefaultContrast), at_default / count, double(MaxContrast), at_max / count);
        Expect(std::fabs(at_default / count - 1.0) <= 0.03, "the mean density at the default contrast is 1 +- 0.03");
        Expect(std::fabs(at_max / count - 1.0) <= 0.03, "the mean density at the largest contrast is 1 +- 0.03");
        Expect(shade / count <= 1e-6, "at the default contrast the view shade is N");
    }

    // q. MarchLitStep, the step the sun fog takes: where the sample is lit it is MarchStep bit for
    // bit; where it is in shadow (vis 0) it changes neither the light nor the excess, whatever m
    // is (2000 random rays of 32 steps, a third of the samples in shadow, m from 0 to 2).
    {
        Random random{63};
        bool lit_same = true, shadow_still = true;
        for (int ray = 0; ray < 2000; ++ray) {
            const float density = float(0.005 + 0.045 * random.Unit());
            const float ds = float(0.5 + 39.5 * random.Unit()) / 32.0f;
            const float jitter = float(random.Unit());
            March march;
            for (int i = 0; i < 32; ++i) {
                const float t = (float(i) + jitter) * ds;
                const float vis = float(random.Next() % 3) * 0.5f;
                const float m = float(2.0 * random.Unit());
                March full = march;
                const March before = march;
                MarchStep(full, density, t, ds, jitter, m, vis);
                MarchLitStep(march, density, t, ds, jitter, m, vis);
                if (vis > 0.0f) {
                    lit_same = lit_same && SameBits(full.energy, march.energy) &&
                               SameBits(full.excess, march.excess);
                } else {
                    shadow_still = shadow_still && SameBits(before.energy, march.energy) &&
                                   SameBits(before.excess, march.excess);
                }
            }
        }
        Expect(lit_same, "MarchLitStep on a lit sample is MarchStep");
        Expect(shadow_still, "MarchLitStep on a sample in shadow changes nothing");
    }

    // r. r116_wind-one-source: the heading's wander knob, the wind at a point, the followers' line.
    {
        const float qnan = std::numeric_limits<float>::quiet_NaN();
        // WanderDeg with the wander set: at Wander it is the 2-argument function, at 0 the base heading,
        // at MaxWander still within MaxWander of it (an hour of wind time, odd steps).
        bool same = true, fixed = true, bounded = true;
        for (int i = 0; i <= 3600; ++i) {
            same = same && std::fabs(WanderDeg(double(i), 225.0f, Wander) - WanderDeg(double(i), 225.0f)) <= 1e-5f;
            fixed = fixed && WanderDeg(double(i), 225.0f, 0.0f) == 225.0f;
            const float deg = WanderDeg(double(i) * 7.3, 100.0f, MaxWander);
            bounded = bounded && deg >= 100.0f - MaxWander && deg <= 100.0f + MaxWander;
        }
        Expect(same, "WanderDeg at Wander is the 2-argument WanderDeg");
        Expect(fixed, "WanderDeg with wander 0 is the base heading");
        Expect(bounded, "WanderDeg stays within MaxWander of the base heading");
        Expect(Params{}.wander == Wander && MaxWander >= Wander && CloudRatio == 4.0f,
               "defaults: wander 15, ratio 4");
        // Sanitize: not finite is the default, negative 0, above MaxWander MaxWander.
        Expect(Sanitize({.on = true, .wander = qnan}).wander == Wander, "Sanitize: wander not finite is Wander");
        Expect(Sanitize({.on = true, .wander = -3.0f}).wander == 0.0f, "Sanitize: wander below 0 is 0");
        Expect(Sanitize({.on = true, .wander = 99.0f}).wander == MaxWander, "Sanitize: wander above the maximum");
        // The state: wander 0 holds the heading at its base for 120 s; the snapshot carries the knobs.
        Params p = On;
        p.direction_deg = 100.0f;
        p.wander = 0.0f;
        State fixed_state;
        bool held = true;
        for (int i = 0; i < 1200; ++i) {
            fixed_state.Advance(p, 0.1);
            held = held && fixed_state.Get().direction_deg == 100.0f;
        }
        Expect(held, "wander 0: the heading is the base heading at every step");
        const Snapshot f = fixed_state.Get();
        Expect(f.gusts == p.gusts && f.wander == 0.0f && f.cloud_speed == CloudRatio * p.speed,
               "the snapshot carries the gusts, the wander and the cloud speed");
        // The default wander is r82's: the same heading as WanderDeg(time, base) says.
        State moving;
        for (int i = 0; i < 600; ++i) {
            moving.Advance(On, 0.1);
        }
        const Snapshot m = moving.Get();
        float want = std::fmod(WanderDeg(m.time, DefaultDirection), 360.0f);
        if (want < 0.0f) {
            want += 360.0f;
        }
        Expect(std::fabs(m.direction_deg - want) <= 1e-4f && m.wander == Wander,
               "the default wander gives the heading r82 gave");
        // WindAt: zero without the wind; at the origin the snapshot's wind (bit for bit); downwind the
        // gust the origin had that much earlier (a front reaches the upwind side first).
        Expect(WindAt(Snapshot{}, 5.0f, 5.0f) == std::array<float, 3>{0.0f, 0.0f, 0.0f}, "WindAt without the wind is zero");
        Params g = On;
        g.gusts = 1.0f;
        g.speed = 2.0f;
        g.direction_deg = 30.0f;
        g.wander = 0.0f;
        State gs;
        for (int i = 0; i < 900; ++i) {
            gs.Advance(g, 0.1);
        }
        const Snapshot w = gs.Get();
        Expect(SameBits(WindAt(w, 0.0f, 0.0f), w.wind), "WindAt at the origin is the snapshot's wind");
        const float dx = 12.0f * w.dir_x, dz = 12.0f * w.dir_z;
        const auto down = WindAt(w, dx, dz);
        const float want_speed = w.speed * Gust(w.time - double(dx * w.dir_x + dz * w.dir_z) / double(std::max(w.speed, 0.1f)), w.gusts);
        Expect(std::fabs(std::hypot(down[0], down[2]) - want_speed) <= 1e-4f && down[1] == 0.0f,
               "WindAt 12 m downwind has the gust the origin had 6 s earlier");
        Expect(down[0] * w.dir_z - down[2] * w.dir_x <= 1e-5f * want_speed + 1e-6f &&
                   down[0] * w.dir_x + down[2] * w.dir_z >= 0.0f,
               "WindAt points along the heading");
        // HeadingDeg and ScreenVelocity.
        Expect(HeadingDeg(1.0f, 0.0f) == 0.0f && std::fabs(HeadingDeg(0.0f, 1.0f) - 90.0f) <= 1e-4f &&
                   std::fabs(HeadingDeg(-1.0f, 0.0f) - 180.0f) <= 1e-4f &&
                   std::fabs(HeadingDeg(-0.7071068f, -0.7071068f) - 225.0f) <= 1e-3f &&
                   HeadingDeg(0.0f, 0.0f) == 0.0f && HeadingDeg(qnan, 1.0f) == 0.0f,
               "HeadingDeg");
        const std::array<float, 12> identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const auto sx = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, 2.0f, 100.0f, 50.0f);
        const auto sy = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {0.0f, 1.0f, 0.0f}, 2.0f, 100.0f, 50.0f);
        Expect(std::fabs(sx[0] - 50.0f) <= 1e-4f && sx[1] == 0.0f && sy[0] == 0.0f && std::fabs(sy[1] + 37.5f) <= 1e-4f,
               "ScreenVelocity: x scale 2, y scale -3, depth 2, 100 x 50");
        const auto none = ScreenVelocity(identity, {2.0f, -3.0f, 1.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, 0.0f, 100.0f, 50.0f);
        Expect(none[0] == 0.0f && none[1] == 0.0f, "ScreenVelocity at depth 0 is zero");
        // The followers' line: a follower that read prints its heading and gust, the others "-"; the
        // counts reset with each line; a read without the wind counts for nothing.
        char text[400];
        FollowersText(w, text, sizeof(text)); // clears whatever came before
        Use(Follower::Fog, w, w.wind);
        UseHeading(Follower::Clouds, w, w.direction_deg, w.cloud_speed, CloudRatio);
        Felt(Follower::Motes, w, identity);
        Use(Follower::Haze, Snapshot{}, w.wind);
        const FollowerNote& fog = Notes()[std::size_t(Follower::Fog)];
        const FollowerNote& clouds = Notes()[std::size_t(Follower::Clouds)];
        Expect(std::fabs(fog.heading.load() - w.direction_deg) <= 1e-3f && std::fabs(fog.gust.load() - w.gust) <= 1e-4f,
               "Use: the heading of the vector and the gust factor it holds");
        Expect(std::fabs(clouds.heading.load() - w.direction_deg) <= 1e-6f && std::fabs(clouds.gust.load() - 1.0f) <= 1e-5f,
               "UseHeading: the clouds' factor is 1 (no gusts, speed CloudRatio x the mean)");
        const int length = FollowersText(w, text, sizeof(text));
        Expect(length > 0 && length < 300, "the followers' line is under 300 characters");
        Expect(std::strstr(text, "Wind (r116): heading") == text && std::strstr(text, " fog ") != nullptr &&
                   std::strstr(text, " clouds ") != nullptr && std::strstr(text, " motes ") != nullptr &&
                   std::strstr(text, " noise -") != nullptr && std::strstr(text, " plants -") != nullptr &&
                   std::strstr(text, " haze -") != nullptr && std::strstr(text, " sparks -") != nullptr,
               "the followers' line names the readers and marks the others");
        FollowersText(w, text, sizeof(text));
        Expect(std::strstr(text, " fog -") != nullptr && std::strstr(text, " clouds -") != nullptr,
               "the counts reset with each line");
    }

    // s. r116b_wind-weather: the weather's range, steps and shares of time, the knobs that must do nothing,
    // continuity of the speed and the gust, the gusts' coupling, the clouds' speed, WindAt, the line.
    {
        const float qnan = std::numeric_limits<float>::quiet_NaN();
        // One noise period of weather (Period x WeatherCell s): the numbers r116b's Python copy prints
        // (calm 55.9%, light 22.8%, in-between 17.3%, strong 4.0%, 3.5 m/s and over 1.05%, top 3.84,
        // at most 0.088 m/s a second).
        const double span = Period * WeatherCell;
        std::size_t calm = 0, light = 0, band = 0, strong = 0, high = 0, total = 0;
        float lo = 1e9f, hi = 0.0f, step = 0.0f, prev = WeatherSpeed(0.0);
        for (double tw = 0.0; tw < span; tw += 1.0) {
            const float v = WeatherSpeed(tw);
            lo = std::min(lo, v);
            hi = std::max(hi, v);
            step = std::max(step, std::fabs(v - prev));
            prev = v;
            ++total;
            if (v < CalmBelow) {
                ++calm;
            } else if (v < LightBelow) {
                ++light;
            } else if (v < StrongFrom) {
                ++band;
            } else {
                ++strong;
            }
            high += v >= 3.5f ? 1 : 0;
        }
        const auto share = [&](std::size_t n) { return double(n) / double(total); };
        Expect(lo >= WeatherMin && hi <= WeatherMax && lo < 0.45f && hi > 3.6f,
               "the weather's speed stays within 0.4-3.9 m/s and reaches both ends over a period");
        Expect(step <= 0.15f, "the weather's speed changes at most 0.15 m/s each second");
        Expect(share(calm) > 0.50 && share(calm) < 0.62, "calm (below 0.7 m/s) about 56% of the time");
        Expect(share(light) > 0.18 && share(light) < 0.28, "light (0.7-1.5) about 23% of the time");
        Expect(share(band) > 0.12 && share(band) < 0.22, "in-between (1.5-3) about 17% of the time");
        Expect(share(strong) > 0.025 && share(strong) < 0.055, "strong (3 and over) about 4% of the time");
        Expect(share(calm) + share(light) > 0.74, "calm or light more than 74% of the time");
        Expect(share(high) > 0.003 && share(high) < 0.03, "3.5 m/s and over about 1% of the time");
        std::array<bool, 5> seen{};
        for (double tw = 0.0; tw < span; tw += 7.0) {
            seen[std::size_t(SkyAt(tw))] = true;
        }
        Expect(seen[0] && seen[1] && seen[2] && seen[3] && seen[4],
               "every state shows over a period: calm, light, building, easing, strong");
        Expect(std::strcmp(SkyName(Sky::Calm), "calm") == 0 && std::strcmp(SkyName(Sky::Light), "light") == 0 &&
                   std::strcmp(SkyName(Sky::Building), "building") == 0 &&
                   std::strcmp(SkyName(Sky::Easing), "easing") == 0 && std::strcmp(SkyName(Sky::Strong), "strong") == 0,
               "the states' names");
        Expect(WeatherLevel(WeatherMin) == 0.0f && WeatherLevel(WeatherMax) == 1.0f && WeatherLevel(qnan) == 0.0f &&
                   WeatherLevel(100.0f) == 1.0f,
               "WeatherLevel: 0 at the lowest speed, 1 at the highest, 0 for NaN");
        Expect(WeatherSpeed(std::numeric_limits<double>::quiet_NaN()) >= WeatherMin, "WeatherSpeed of NaN is a speed");

        // Sanitize.
        Expect(Sanitize({.on = true, .weather_rate = 1000.0}).weather_rate == WeatherRateMax &&
                   Sanitize({.on = true, .weather_rate = 0.0}).weather_rate == WeatherRateMin &&
                   Sanitize({.on = true, .weather_rate = double(qnan)}).weather_rate == 1.0 &&
                   Sanitize({.on = true, .weather_rate = 20.0}).weather_rate == 20.0,
               "Sanitize: the weather's rate 0.05-100, NaN is 1");
        Expect(Sanitize({.on = true, .weather_at = 1e9}).weather_at == WeatherAtLimit &&
                   Sanitize({.on = true, .weather_at = -1e9}).weather_at == -WeatherAtLimit &&
                   Sanitize({.on = true, .weather_at = double(qnan)}).weather_at == 0.0 &&
                   Sanitize({.on = true, .weather_at = 123.0}).weather_at == 123.0,
               "Sanitize: the weather's start is limited, NaN is 0");
        Expect(!Params{}.weather && Params{}.weather_rate == 1.0 && Params{}.weather_at == 0.0,
               "defaults: the weather is a knob of the environment, off in Params");

        // The weather off: the rate and the start do nothing (bit for bit r116's snapshots, 10 s).
        {
            Params inert = On;
            inert.weather_rate = 7.0;
            inert.weather_at = 99.0;
            State a, b;
            bool same_all = true;
            for (int i = 0; i < 600; ++i) {
                a.Advance(On, 1.0 / 60.0);
                b.Advance(inert, 1.0 / 60.0);
                const Snapshot sa = a.Get(), sb = b.Get();
                same_all = same_all && Same(sa, sb) && SameBits(sa.cloud_speed, sb.cloud_speed) &&
                           SameBits(sa.gust_strength, sb.gust_strength) && sa.speed == DefaultSpeed &&
                           !sa.weather_on && sa.weather == 0.0f && sa.gust_strength == On.gusts &&
                           ClockOf(sa, 10.0) == 10.0;
            }
            Expect(same_all, "weather off: the rate and the start change nothing; speed, gust strength and clock are r116's");
        }

        // The weather on: Snapshot::speed is the weather at the clock; the speed and the gust are continuous
        // between frames; the clouds' speed is CloudRatio x it and covers a wide range.
        Params wp = On;
        wp.weather = true;
        wp.weather_rate = 20.0;
        wp.weather_at = 500.0;
        State st;
        Snapshot sn{};
        float prev_speed = 0.0f, prev_gust = 1.0f, max_dv = 0.0f, max_dg = 0.0f, c_lo = 1e9f, c_hi = 0.0f;
        bool follows = true, cloud_ties = true, levels = true;
        for (int i = 0; i < 36000; ++i) { // 600 s at 60 Hz: 12000 s of weather
            st.Advance(wp, 1.0 / 60.0);
            sn = st.Get();
            follows = follows && sn.weather_on && sn.speed == WeatherSpeed(500.0 + 20.0 * sn.time) &&
                      sn.weather_rate == 20.0 && sn.weather_at == 500.0;
            cloud_ties = cloud_ties && sn.cloud_speed == CloudRatio * sn.speed;
            levels = levels && sn.weather == WeatherLevel(sn.speed) &&
                     sn.gust_strength == GustStrength(wp.gusts, sn.weather);
            c_lo = std::min(c_lo, sn.cloud_speed);
            c_hi = std::max(c_hi, sn.cloud_speed);
            if (i > 0) {
                max_dv = std::max(max_dv, std::fabs(sn.speed - prev_speed));
                max_dg = std::max(max_dg, std::fabs(sn.gust - prev_gust));
            }
            prev_speed = sn.speed;
            prev_gust = sn.gust;
        }
        Expect(follows, "weather on: Snapshot::speed is WeatherSpeed(start + rate x wind time) at every step");
        Expect(levels, "weather on: Snapshot::weather and gust_strength are the level's");
        Expect(max_dv <= 0.04f, "weather on, rate 20, 60 Hz: the speed moves at most 0.04 m/s a frame (no jumps)");
        Expect(max_dg <= 0.06f, "weather on: the gust factor moves at most 0.06 a frame (no jumps)");
        Expect(cloud_ties, "the clouds' speed is CloudRatio x the weather's speed at every step");
        Expect(c_hi > 2.0f * c_lo && c_lo >= CloudRatio * WeatherMin && c_hi <= CloudRatio * WeatherMax,
               "the clouds' speed follows the weather over a wide range (calm clouds drift slowly, strong ones fast)");

        // The gusts follow the level: weaker and rarer when calm, stronger and more often when up, the
        // mean near 1 (the rates are the Python copy's: level 0: mean 0.99, 2.6% above 1.15; level 0.35:
        // 1.00; level 1: mean 1.13, 39% above 1.15).
        const auto gust_run = [](float level) {
            double sum = 0.0;
            std::size_t over = 0, n = 0;
            for (double t = 0.0; t < 8000.0; t += 0.5) {
                const float g = GustWeather(t, 0.5f, level);
                sum += double(g);
                over += g > 1.15f ? 1 : 0;
                ++n;
            }
            return std::array<double, 2>{sum / double(n), double(over) / double(n)};
        };
        const auto g0 = gust_run(0.0f), gn = gust_run(GustNeutral), g1 = gust_run(1.0f);
        Expect(g0[1] < 0.08 && g1[1] > 0.25 && g1[1] > 3.0 * g0[1],
               "gusts: rare when calm (under 8% above x1.15), frequent when strong (over 25%)");
        Expect(g0[0] > 0.95 && g0[0] < 1.02 && gn[0] > 0.97 && gn[0] < 1.03 && g1[0] > 1.05 && g1[0] < 1.2,
               "gusts: the mean factor stays near 1 and rises with the level");
        Expect(GustWeather(12.3, 0.0f, 0.7f) == 1.0f && std::fabs(GustStrength(0.5f, 0.0f) - 0.15f) <= 1e-6f &&
                   std::fabs(GustStrength(0.5f, 1.0f) - 0.65f) <= 1e-6f && GustStrength(1.0f, 1.0f) == MaxGusts,
               "gust strength: 0 gusts is a steady wind, g x (0.3 + level), held to MaxGusts");
        Expect(std::fabs(CoverShift(CoverNeutral)) <= 1e-7f && CoverShift(1.0f) > 0.04f && CoverShift(0.0f) < 0.0f &&
                   CoverShift(1.0f) < 0.05f,
               "cover shift: 0 at the neutral level, denser (positive) when up, thinner when calm");

        // WindAt and GustOf with the weather: at the origin the snapshot's wind (bit for bit), elsewhere the
        // gust of the time the front passed the origin at the weather level of THAT time.
        Expect(SameBits(WindAt(sn, 0.0f, 0.0f), sn.wind), "weather on: WindAt at the origin is the snapshot's wind");
        const float ax = 12.0f * sn.dir_x, az = 12.0f * sn.dir_z;
        const double t_front = sn.time - double(ax * sn.dir_x + az * sn.dir_z) / double(std::max(sn.speed, 0.1f));
        const float want_gust = GustWeather(t_front, sn.gusts, WeatherLevel(WeatherSpeed(500.0 + 20.0 * t_front)));
        const auto along = WindAt(sn, ax, az);
        Expect(GustOf(sn, t_front, sn.gusts) == want_gust && std::fabs(std::hypot(along[0], along[2]) - sn.speed * want_gust) <= 1e-4f,
               "weather on: GustOf and WindAt take the weather level of the front's time");
        Snapshot constant = sn;
        constant.weather_on = false;
        Expect(GustOf(constant, 100.0, constant.gusts) == Gust(100.0, constant.gusts) &&
                   SameBits(WindAt(constant, 3.0f, -2.0f),
                            std::array<float, 3>{constant.speed * GustAt(constant.time, constant.gusts, 3.0f, -2.0f, constant.dir_x, constant.dir_z, constant.speed) * constant.dir_x,
                                                 0.0f,
                                                 constant.speed * GustAt(constant.time, constant.gusts, 3.0f, -2.0f, constant.dir_x, constant.dir_z, constant.speed) * constant.dir_z}),
               "weather off: GustOf is Gust and WindAt is r116's (GustAt)");
        Expect(ClockOf(sn, 10.0) == 500.0 + 20.0 * 10.0, "ClockOf: the start plus the rate x wind time");

        // The proof line.
        WeatherWindow ww;
        ww.Add(1.0f);
        ww.Add(2.0f);
        ww.Add(3.0f);
        ww.Add(qnan);
        char line[400];
        const int n = WeatherText(sn, ww, sn.cloud_speed, line, sizeof(line));
        Expect(n > 0 && n < 300, "the weather line is under 300 characters");
        Expect(std::strstr(line, "Wind (r116b): weather ") == line && std::strstr(line, "(clock ") != nullptr &&
                   std::strstr(line, ", speed now ") != nullptr && std::strstr(line, "(mean 2.00, range 1.00-3.00)") != nullptr &&
                   std::strstr(line, "gust strength ") != nullptr && std::strstr(line, ", clouds ") != nullptr &&
                   std::strstr(line, SkyName(SkyAt(ClockOf(sn, sn.time)))) != nullptr,
               "the weather line names the state, the clock, the speed with mean and range, the gusts and the clouds");
        WeatherText(sn, ww, sn.cloud_speed, line, sizeof(line));
        Expect(ww.count == 0 && std::strstr(line, "range ") != nullptr, "the weather line empties its window");
        State off_state;
        off_state.Advance(On, 0.05);
        WeatherWindow empty;
        WeatherText(off_state.Get(), empty, 6.0f, line, sizeof(line));
        Expect(std::strstr(line, "weather off") != nullptr && std::strstr(line, "clouds 6.00 m/s") != nullptr,
               "weather off: the line says so");
    }

    if (failures) {
        std::printf("wind-test: %d failure(s)\n", failures);
        return failures != 0;
    }
    std::printf("wind-test: ok\n");
    return 0;
}
