// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r94_fog-noise): checks of gpu/shadps4/video_core/renderer_vulkan/volumetric_fog_noise.h,
// the sun fog noise's knobs, shaping and drift (built and run by engine/build.sh --test and the
// CMake target volumetric-fog-noise-test).
//  a. BB_FOG_NOISE: missing, empty, not a number, not finite or below 0: 0 (off); clamped to 2.
//  b. BB_FOG_NOISE_SCALE: missing or not a number: 10 m; clamped to 2-100 m.
//  c. The knobs: off by default; BB_FOG_NOISE_SHOW=1 turns them on at strength 3.
//  d. The shaping: m within 0-2, 1 at d = 0, Factor(d) + Factor(-d) = 2 (odd around 1, so the mean
//     of m is 1 for the symmetric d of the value noise) at every strength.
//  e. The shared numbers: weights add up to 1, the octaves get finer, the yaws are rotations.
//  f. No wind: the offsets stay 0 (the noise stands still in the world).
//  g. Wind: each octave's pattern travels with the wind at Speed[k] times its velocity.
//  h. A long gap moves the offsets by at most MaxStep s of wind; time going back moves nothing.
//  i. The offsets stay in [0, 256) over a long run.
//  j. The push tail holds the rows, the offsets, the amplitude, the gain and 1 / scale.
//  k. bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS: the knobs (off unless it starts with 1;
//     then the scale's default is 14 m), the tail without it equal to r94's, with it the mark (gain
//     below 0), the clear air's m and the flatter up row; the banks' m from 0.15 to 2.51, and its
//     mean over a grid of world points (a C++ copy of fog_noise.glsl's noise) within 0.03 of 1.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <cstdint> // bbport (r94b_fog-noise-visible)

#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_fog_noise.h"

using namespace VolumetricFogNoise;

namespace {

bool Near(double a, double b, double eps) {
    return std::fabs(a - b) <= eps;
}

// The difference a - b of two lattice coordinates, wrapped into [-Period / 2, Period / 2).
double CellGap(double a, double b) {
    const double gap = WrapCells(a - b + Period / 2.0) - Period / 2.0;
    return gap;
}

// bbport (r94b_fog-noise-visible): a copy of host_shaders/fog_noise.glsl's corner hash and value
// noise, for check k's mean of the banks look.
float CornerValue(std::uint32_t packed) {
    std::uint32_t h = packed + std::uint32_t(FOG_NOISE_SEED);
    h ^= h >> 16u;
    h *= 0x7feb352du;
    h ^= h >> 15u;
    h *= 0x846ca68bu;
    h ^= h >> 16u;
    return float(h >> 8u) * (1.0f / 16777216.0f);
}

float ValueNoise(const std::array<float, 3>& x) {
    const auto fade = [](float u) { return u * u * u * (u * (u * 6.0f - 15.0f) + 10.0f); };
    const auto mix = [](float a, float b, float t) { return a * (1.0f - t) + b * t; };
    const std::uint32_t mask = std::uint32_t(FOG_NOISE_PERIOD - 1);
    std::array<std::uint32_t, 3> a{}, b{};
    std::array<float, 3> u{};
    for (std::size_t i = 0; i < 3; ++i) {
        const float f = std::floor(x[i]);
        u[i] = fade(x[i] - f);
        a[i] = std::uint32_t(int(f)) & mask;
        b[i] = (a[i] + 1u) & mask;
    }
    const std::uint32_t y0 = a[1] << 8u, y1 = b[1] << 8u, z0 = a[2] << 16u, z1 = b[2] << 16u;
    const float x00 = mix(CornerValue(a[0] | y0 | z0), CornerValue(b[0] | y0 | z0), u[0]);
    const float x10 = mix(CornerValue(a[0] | y1 | z0), CornerValue(b[0] | y1 | z0), u[0]);
    const float x01 = mix(CornerValue(a[0] | y0 | z1), CornerValue(b[0] | y0 | z1), u[0]);
    const float x11 = mix(CornerValue(a[0] | y1 | z1), CornerValue(b[0] | y1 | z1), u[0]);
    return mix(mix(x00, x10, u[1]), mix(x01, x11, u[1]), u[2]);
}

} // namespace

int main() {
    // a
    assert(ParseStrength(nullptr) == 0.0f && ParseStrength("") == 0.0f);
    assert(ParseStrength("on") == 0.0f && ParseStrength("nan") == 0.0f);
    assert(ParseStrength("inf") == 0.0f && ParseStrength("-1") == 0.0f);
    assert(ParseStrength("1") == 1.0f && ParseStrength("0.5") == 0.5f);
    assert(ParseStrength("7") == MaxStrength);

    // b
    assert(ParseScale(nullptr) == DefaultScale && ParseScale("") == DefaultScale);
    assert(ParseScale("x") == DefaultScale && ParseScale("nan") == DefaultScale);
    assert(ParseScale("1") == MinScale && ParseScale("500") == MaxScale);
    assert(ParseScale("25") == 25.0f);

    // c
    {
        const Knobs k = MakeKnobs(nullptr, nullptr, nullptr);
        assert(!k.On() && !k.show && k.scale == DefaultScale);
        const Knobs zero = MakeKnobs("0", "8", "0");
        assert(!zero.On() && zero.scale == 8.0f);
        const Knobs one = MakeKnobs("1", "8", nullptr);
        assert(one.On() && one.strength == 1.0f && one.scale == 8.0f && !one.show);
        const Knobs show = MakeKnobs("0", nullptr, "1");
        assert(show.On() && show.show && show.strength == ShowStrength);
        assert(SuggestedStrength > 0.0f && SuggestedStrength <= MaxStrength);
    }

    // d
    assert(Amplitude(0.5f) == 0.5f && Amplitude(1.0f) == 1.0f && Amplitude(ShowStrength) == 1.0f);
    assert(Gain(0.5f) == BaseGain && Gain(1.0f) == BaseGain && Gain(2.0f) == 2.0f * BaseGain);
    for (const float s : {0.25f, 0.5f, 1.0f, 2.0f, ShowStrength}) {
        const float a = Amplitude(s), g = Gain(s);
        assert(Factor(0.0f, a, g) == 1.0f);
        for (int i = 0; i <= 100; ++i) {
            const float d = -0.5f + 0.01f * float(i);
            const float m = Factor(d, a, g), n = Factor(-d, a, g);
            assert(m >= 0.0f && m <= 2.0f && Near(m + n, 2.0, 1e-6));
            assert(m >= 1.0f - a && m <= 1.0f + a);
        }
    }

    // e
    assert(Near(Weight[0] + Weight[1] + Weight[2], 1.0, 1e-6));
    assert(Ratio[0] == 1.0f && Ratio[1] < Ratio[0] && Ratio[2] < Ratio[1] && Ratio[2] > 0.0f);
    for (std::size_t k = 0; k < 3; ++k) {
        assert(Near(YawCos[k] * YawCos[k] + YawSin[k] * YawSin[k], 1.0, 1e-6));
    }
    assert(FineFrom < FineTo && Squash > 0.0f && Period == 256.0);

    // f
    {
        Drift drift;
        for (int i = 0; i < 100; ++i) {
            drift.Advance(false, 0.1 * i, {1.5f, 0.0f, -1.0f}, DefaultScale);
        }
        for (std::size_t k = 0; k < 3; ++k) {
            assert((drift.Cells(k) == std::array<float, 3>{0.0f, 0.0f, 0.0f}));
        }
    }

    // g
    {
        const float scale = 8.0f;
        const std::array<float, 3> wind{1.2f, 0.0f, -0.9f};
        Drift drift;
        double t = 5.0;
        drift.Advance(true, t, wind, scale); // the first call only takes the time
        assert((drift.Cells(0) == std::array<float, 3>{0.0f, 0.0f, 0.0f}));
        for (int i = 0; i < 40; ++i) {
            t += 0.05;
            drift.Advance(true, t, wind, scale);
        }
        const double seconds = 40 * 0.05;
        const std::array<float, 3> p{13.0f, 2.0f, -7.0f};
        for (std::size_t k = 0; k < 3; ++k) {
            const double travelled = seconds * double(Speed[k]);
            const std::array<float, 3> q{float(p[0] + wind[0] * travelled), p[1],
                                         float(p[2] + wind[2] * travelled)};
            const std::array<float, 3> before = LatticePoint(p, k, scale);
            const std::array<float, 3> after = LatticePoint(q, k, scale);
            const std::array<float, 3> off = drift.Cells(k);
            for (std::size_t j = 0; j < 3; ++j) {
                assert(Near(CellGap(double(after[j]) - double(off[j]), double(before[j])), 0.0, 1e-3));
            }
        }
        // the pattern moved: the largest octave's offset is not 0
        const std::array<float, 3> moved = drift.Cells(0);
        assert(std::fabs(moved[0]) + std::fabs(moved[2]) > 0.1f);
    }

    // h
    {
        const std::array<float, 3> wind{2.0f, 0.0f, 0.0f};
        Drift a, b;
        a.Advance(true, 0.0, wind, DefaultScale);
        b.Advance(true, 0.0, wind, DefaultScale);
        a.Advance(true, 100.0, wind, DefaultScale);   // a 100 s gap counts as MaxStep
        b.Advance(true, MaxStep, wind, DefaultScale);
        for (std::size_t k = 0; k < 3; ++k) {
            for (std::size_t j = 0; j < 3; ++j) {
                assert(Near(a.Cells(k)[j], b.Cells(k)[j], 1e-5));
            }
        }
        const std::array<float, 3> held = a.Cells(1);
        a.Advance(true, 50.0, wind, DefaultScale); // back in time: nothing moves
        assert(a.Cells(1) == held);
    }

    // i
    {
        const std::array<float, 3> wind{4.0f, 0.0f, 3.0f};
        Drift drift;
        double t = 0.0;
        for (int i = 0; i < 200000; ++i) {
            drift.Advance(true, t, wind, MinScale);
            t += 0.1;
        }
        for (std::size_t k = 0; k < 3; ++k) {
            for (const float c : drift.Cells(k)) {
                assert(c >= 0.0f && c < 256.0f);
            }
        }
    }

    // j
    {
        const Knobs knobs = MakeKnobs("2", "20", nullptr);
        Drift drift;
        std::array<float, 12> rows{};
        for (std::size_t i = 0; i < rows.size(); ++i) {
            rows[i] = float(i) * 0.5f;
        }
        const Tail tail = MakeTail(rows, drift, knobs);
        assert(tail.view_to_world == rows);
        assert(tail.off0[3] == Amplitude(2.0f) && tail.off1[3] == Gain(2.0f));
        assert(Near(tail.off2[3], 1.0 / 20.0, 1e-7));
        assert(tail.off0[0] == 0.0f && tail.off1[1] == 0.0f && tail.off2[2] == 0.0f);
        assert(sizeof(Tail) + 32 == PushBytes && PushBytes <= 128);
    }

    // k (bbport r94b_fog-noise-visible)
    {
        for (const char* off : {static_cast<const char*>(nullptr), "", "0", "yes"}) {
            const Knobs a = MakeKnobs("1", nullptr, nullptr, off);
            const Knobs b = MakeKnobs("1", nullptr, nullptr);
            assert(!a.banks && a.strength == b.strength && a.scale == b.scale && a.show == b.show);
        }
        const Knobs banks = MakeKnobs("1", nullptr, nullptr, "1");
        assert(banks.On() && banks.banks && banks.scale == BankScale);
        assert(MakeKnobs("1", "20", nullptr, "1").scale == 20.0f);
        assert(MakeKnobs("1", "x", nullptr, "1").scale == BankScale);
        assert(MakeKnobs("1", "500", nullptr, "1").scale == MaxScale);
        assert(!MakeKnobs(nullptr, nullptr, nullptr, "1").On()); // the banks alone: still off
        assert(MakeKnobs("0", nullptr, "1", "1").strength == ShowStrength);

        // the tail: without the banks r94's words, with them the mark and the flatter up row
        Drift drift;
        drift.Advance(true, 0.0, {1.0f, 0.0f, 0.5f}, 10.0f);
        drift.Advance(true, 0.5, {1.0f, 0.0f, 0.5f}, 10.0f);
        std::array<float, 12> rows{};
        for (std::size_t i = 0; i < rows.size(); ++i) {
            rows[i] = 0.25f * float(i) - 1.0f;
        }
        const Tail r94 = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr));
        const Tail same = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr, "0"));
        assert(r94.view_to_world == same.view_to_world && r94.off0 == same.off0);
        assert(r94.off1 == same.off1 && r94.off2 == same.off2);
        for (const float s : {0.25f, 1.0f, MaxStrength, ShowStrength}) {
            assert(Gain(s) > 0.0f); // r94's tail never carries the mark
        }
        const Tail bt = MakeTail(rows, drift, MakeKnobs("1", "10", nullptr, "1"));
        assert(bt.off1[3] < 0.0f && Near(-bt.off1[3], BankGain(1.0f), 1e-7));
        assert(bt.off0[3] == BankClear(1.0f) && bt.off2 == r94.off2);
        for (std::size_t i = 0; i < 3; ++i) {
            assert(bt.off0[i] == r94.off0[i] && bt.off1[i] == r94.off1[i]);
        }
        for (std::size_t i = 0; i < rows.size(); ++i) {
            if (i >= 4 && i < 8) {
                assert(Near(bt.view_to_world[i], rows[i] * BankSquash / Squash, 1e-6));
            } else {
                assert(bt.view_to_world[i] == rows[i]);
            }
        }

        // the shaping: 0.15 in the clear air, 2.51 in a bank's core, mean 1 over the world
        assert(BankFrom < BankTo && BankMean > 0.0f && BankMean < 1.0f && BankSquash > Squash);
        const float clear = BankClear(1.0f), gain = BankGain(1.0f);
        assert(Near(clear, BankClearShare, 1e-6) && Near(clear + gain, 2.5111, 1e-3));
        assert(BankFactor(-1.0f, clear, gain) == clear && Near(BankFactor(1.0f, clear, gain),
                                                                clear + gain, 1e-6));
        assert(BankClear(ShowStrength) == clear && BankClear(0.5f) > clear);
        assert(Near(BankClear(0.5f) + BankGain(0.5f) * BankMean, 1.0, 1e-6));
        double sum_w = 0.0, sum_m = 0.0;
        constexpr int n = 48;
        for (int i = 0; i < n; ++i) {
            for (int j = 0; j < n; ++j) {
                for (int l = 0; l < n; ++l) {
                    // as the shader sees it: the banks' up row is times BankSquash / Squash
                    const std::array<float, 3> p{(float(i) + 0.37f) * 7.31f,
                                                 (float(j) + 0.37f) * 7.31f * 0.53f *
                                                     (BankSquash / Squash),
                                                 (float(l) + 0.37f) * 7.31f};
                    float d = 0.0f;
                    for (std::size_t k = 0; k < 3; ++k) {
                        d += Weight[k] * (ValueNoise(LatticePoint(p, k, BankScale)) - 0.5f);
                    }
                    sum_w += BankFactor(d, 0.0f, 1.0f);
                    sum_m += BankFactor(d, clear, gain);
                }
            }
        }
        const double count = double(n) * n * n;
        assert(Near(sum_w / count, BankMean, 0.01) && Near(sum_m / count, 1.0, 0.03));
    }

    std::printf("volumetric-fog-noise-test: ok\n");
    return 0;
}
