// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r107_caustics): the water caustics' knob, push words, drift and pattern
// (renderer_vulkan/caustics_params.h). Built by engine/build.sh --test (C++20, -Werror) and by the
// CMake target caustics-test.
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "gpu/shadps4/video_core/renderer_vulkan/caustics_params.h"

using namespace BbCaustics;

static bool Near(float a, float b, float tol) {
    return std::fabs(a - b) <= tol;
}

int main() {
    // The knob: off unless a strength above 0 or "show".
    assert(Parse(nullptr, nullptr).strength == 0.0f);
    assert(Parse("", nullptr).strength == 0.0f && !Parse("", nullptr).unreadable);
    assert(Parse("0", nullptr).strength == 0.0f);
    assert(Parse("-1", nullptr).strength == 0.0f);
    assert(Parse("1", nullptr).strength == 1.0f && !Parse("1", nullptr).show);
    assert(Parse("2.5", nullptr).strength == 2.5f);
    assert(Parse("9", nullptr).strength == MaxStrength);
    assert(Parse("1 ", nullptr).strength == 1.0f);
    assert(Parse("yes", nullptr).unreadable && Parse("yes", nullptr).strength == 0.0f);
    assert(Parse("1x", nullptr).unreadable);
    assert(Parse("nan", nullptr).strength == 0.0f);
    const Knobs show = Parse("show", nullptr);
    assert(show.show && show.strength == 1.0f && Near(GainOf(show), Gain * ShowGain, 1e-6f));
    assert(Near(GainOf(Parse("2", nullptr)), 2.0f * Gain, 1e-6f));
    // bbport (r107b_caustics-visible): BB_CAUSTICS_LAMPS reads as BB_CAUSTICS, on its own too.
    assert(Parse("1", nullptr).lamp_strength == 0.0f && Parse("1", "0").lamp_strength == 0.0f &&
           Parse("1", "").lamp_strength == 0.0f);
    assert(Parse(nullptr, "1").lamp_strength == 1.0f && Parse(nullptr, "1").strength == 0.0f);
    assert(Parse(nullptr, "9").lamp_strength == MaxStrength && Parse(nullptr, "-2").lamp_strength == 0.0f);
    assert(Parse(nullptr, "on").lamps_unreadable && !Parse(nullptr, "on").unreadable);
    const Knobs lamp_show = Parse(nullptr, "show");
    assert(lamp_show.show && lamp_show.lamp_strength == 1.0f && lamp_show.strength == 0.0f);
    assert(Near(LampGainOf(lamp_show), LampGain * ShowGain, 1e-6f) && GainOf(lamp_show) == 0.0f);
    // r107d: above 1 the lamps' light stays at strength 1 and the look grows to CAUSTICS_LOOK_MAX.
    assert(Near(LampGainOf(Parse("show", "2")), LampGain * ShowGain, 1e-6f));
    assert(Near(LampGainOf(Parse(nullptr, "0.5")), 0.5f * LampGain, 1e-6f));
    assert(LookOf(Parse(nullptr, "1")) == 0.0f && LookOf(Parse(nullptr, "0.5")) == 0.0f && LookOf(lamp_show) == 0.0f);
    assert(Near(LookOf(Parse(nullptr, "4")), float(CAUSTICS_LOOK_MAX), 1e-6f) &&
           Near(LookOf(Parse(nullptr, "2.5")), 0.5f * float(CAUSTICS_LOOK_MAX), 1e-6f));
    // r107d: the bins of the modelled lamp light.
    assert(BinOf(0.0f) == 0 && BinOf(0.0009f) == 0 && BinOf(0.001f) == 1 && BinOf(0.24f) == 4 &&
           BinOf(0.25f) == 5 && BinOf(1.0f) == Bins - 1 && BinOf(50.0f) == Bins - 1);

    // The push block is the shader's (caustics.comp Push): 128 bytes, the fields in order.
    static_assert(sizeof(Push) == 128);
    static_assert(offsetof(Push, inv_view) == 32 && offsetof(Push, sun) == 80 && offsetof(Push, drift) == 96);
    static_assert(offsetof(Push, gain) == 112 && offsetof(Push, evolve) == 116 && offsetof(Push, flags) == 120 &&
                  offsetof(Push, slot) == 124);

    // The sun: unit, above the horizon.
    std::array<float, 3> s{};
    assert(SunUsable({0.0f, 2.0f, 0.0f}, s) && Near(s[1], 1.0f, 1e-6f));
    assert(!SunUsable({1.0f, 0.0f, 0.0f}, s));
    assert(!SunUsable({0.3f, -0.5f, 0.1f}, s));
    assert(!SunUsable({0.0f, 0.0f, 0.0f}, s));
    assert(!SunUsable({NAN, 1.0f, 0.0f}, s));

    // The drift: real seconds, clamped; the wind adds its shares; layer 1 wraps at its period.
    Drift d;
    d.Advance(1.0, {0.0f, 0.0f, 0.0f}); // clamped to MaxStep
    assert(Near(float(d.time), float(MaxStep), 1e-9f));
    assert(Near(float(d.off[0]), Drift1[0] * float(MaxStep), 1e-7f));
    Drift w;
    w.Advance(0.1, {2.0f, 0.0f, -1.0f});
    assert(Near(float(w.off[0]), (Drift1[0] + WindShare1 * 2.0f) * 0.1f, 1e-6f));
    assert(Near(float(w.off[3]), (Drift2[1] - WindShare2 * 1.0f) * 0.1f, 1e-6f));
    w.Advance(-1.0, {NAN, 0.0f, 0.0f});
    assert(Near(float(w.time), 0.1f, 1e-9f));
    Drift far;
    for (int i = 0; i < 400000; ++i) {
        far.Advance(0.1, {40.0f, 0.0f, 0.0f});
    }
    assert(far.off[0] < 1024.0 * Lambda1 && far.off[0] > -1024.0 * Lambda1);
    assert(far.EvolveCells() >= 0.0f && far.EvolveCells() < 1024.0f);

    // The noise: the values the shader's copy must give (from the Monte Carlo script's twin).
    assert(Near(Noise(0.25f, 0.5f, 0.75f), 0.6614143f, 2e-5f));
    assert(Near(Noise(12.3f, -7.9f, 3.1f), 0.6591443f, 2e-5f));
    assert(Near(Noise(-500.5f, 1023.9f, 40.0f), 0.3346269f, 2e-4f));
    assert(Near(Ridge(0.25f, 0.5f, 0.75f), 0.6771714f, 4e-5f));

    // bbport (r107b_caustics-visible): the lamps that light the water, from light grid records.
    {
        const auto word = [](float f) {
            std::uint32_t u;
            std::memcpy(&u, &f, sizeof(u));
            return u;
        };
        // View to world: a camera at (0, 2, 0), axes as the world's.
        const std::array<float, 12> m{1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1, 0};
        std::uint32_t records[16 * 7] = {};
        const auto put = [&](int i, float x, float y, float z, float reach, float r, float g, float b) {
            const float w[7] = {x, y, z, 1.0f / (reach * reach), r, g, b};
            for (int j = 0; j < 7; ++j) {
                records[i * 16 + j] = word(w[j]);
            }
        };
        put(0, 0.0f, 1.0f, 5.0f, 6.0f, 1.0f, 0.8f, 0.5f);   // 3 m above the plane at y 0: lights it
        put(1, 0.0f, 6.0f, 5.0f, 5.0f, 1.0f, 1.0f, 1.0f);   // 8 m above, reach 5: does not
        put(2, 0.0f, -2.5f, 5.0f, 6.0f, 1.0f, 1.0f, 1.0f);  // under the plane: does not
        put(3, 4.0f, 0.0f, 9.0f, 4.0f, 8.0f, 0.0f, 0.0f);   // 2 m above, red (ranked as 4; r107c: kept)
        put(4, 0.0f, 1.0f, 5.0f, 6.0f, 1.0f, 0.8f, 0.5f);   // as record 0 (ties: the first stays first)
        put(5, 1.0f, -1.98f, 1.0f, 3.0f, 1.0f, 1.0f, 1.0f); // 2 cm above: under the lowest height
        put(6, 0.0f, 0.0f, 3.0f, 0.0f, 1.0f, 1.0f, 1.0f);   // reach infinite (inverse 0 is skipped below)
        records[6 * 16 + 3] = word(0.0f);
        std::array<Lamp, MaxLamps> out{};
        const std::uint32_t n = ChooseLamps(records, 7, m, 0.0f, out);
        assert(n == 3);
        assert(Near(out[0].world[1], 3.0f, 1e-5f) && Near(out[0].world[2], 5.0f, 1e-5f));
        assert(Near(out[1].world[1], 3.0f, 1e-5f) && out[0].importance == out[1].importance);
        assert(Near(out[2].colour[0], 8.0f, 1e-5f) && Near(out[2].reach, 4.0f, 1e-4f));
        assert(out[0].importance >= out[2].importance);
        // More than MaxLamps: the most important ones stay.
        std::uint32_t many[16 * 6] = {};
        for (int i = 0; i < 6; ++i) {
            const float w[7] = {float(i), 0.0f, 3.0f, 1.0f / 25.0f, 0.2f * float(i + 1), 0.2f * float(i + 1),
                                0.2f * float(i + 1)};
            for (int j = 0; j < 7; ++j) {
                many[i * 16 + j] = word(w[j]);
            }
        }
        const std::uint32_t k = ChooseLamps(many, 6, m, 0.0f, out);
        assert(k == MaxLamps);
        for (std::uint32_t i = 1; i < k; ++i) {
            assert(out[i - 1].importance >= out[i].importance);
        }
        assert(Near(out[0].colour[0], 1.2f, 1e-5f));
        assert(ChooseLamps(nullptr, 0, m, 0.0f, out) == 0);
    }
    // bbport (r107f_caustics-world-anchored): the world knob, and the lamp choice's hysteresis.
    {
        assert(WorldOf(nullptr) == 0.0f && WorldOf("") == 0.0f && WorldOf("0") == 0.0f && WorldOf("-1") == 0.0f);
        assert(WorldOf("1") == 1.0f && WorldOf("2.5") == 2.5f && WorldOf("9") == MaxStrength);
        assert(WorldOf("yes") == 0.0f && WorldOf("1x") == 0.0f && Parse("1", "1").world == 0.0f);
        assert(FlagWorld == 256u && MapWords == 65536u && CAUSTICS_MAP_SIZE * CAUSTICS_MAP_SIZE == 65536);
        // Five lamps at the same distance from the camera (0, 2, 0), 1 m above it: the fifth is 10%
        // brighter, so it wins on its own; with the first four kept it does not.
        const std::array<float, 12> m{1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1, 0};
        const auto word = [](float f) {
            std::uint32_t u = 0;
            std::memcpy(&u, &f, sizeof(u));
            return u;
        };
        std::uint32_t rec[16 * 5] = {};
        const float spots[5][2] = {{3.0f, 4.0f}, {-3.0f, 4.0f}, {4.0f, 3.0f}, {-4.0f, 3.0f}, {0.0f, 5.0f}};
        for (int i = 0; i < 5; ++i) {
            const float c = i == 4 ? 1.1f : 1.0f;
            const float w[7] = {spots[i][0], 1.0f, spots[i][1], 1.0f / 36.0f, c, c, c};
            for (int j = 0; j < 7; ++j) {
                rec[i * 16 + j] = word(w[j]);
            }
        }
        std::array<Lamp, MaxLamps> first{}, kept{}, plain{};
        assert(ChooseLamps(rec, 4, m, 0.0f, first) == 4);
        assert(ChooseLamps(rec, 5, m, 0.0f, plain) == 4 && Near(plain[0].colour[0], 1.1f, 1e-5f));
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, &first, 4) == 4);
        for (std::uint32_t i = 0; i < 4; ++i) {
            assert(Near(kept[i].colour[0], 1.0f, 1e-5f)); // the kept four, not the brighter newcomer
        }
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, nullptr, 4) == 4 && Near(kept[0].colour[0], 1.1f, 1e-5f));
        // A newcomer clearly brighter (twice) still wins.
        rec[4 * 16 + 4] = rec[4 * 16 + 5] = rec[4 * 16 + 6] = word(2.0f);
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, &first, 4) == 4 && Near(kept[0].colour[0], 2.0f, 1e-5f));
    }
    // bbport (r107e_caustics-puddles): the puddle plane from the candidates' heights, and the guard.
    {
        std::uint32_t bins[HeightBins] = {};
        const std::uint32_t pixels = 1920u * 1080u; // needs max(64, 207) candidates
        assert(!EstimatePuddle(bins, 10.0f, pixels).found);
        bins[80] = 300; // a puddle 5.12 - 80.5 x 0.04 = 1.90 m below a camera at y 10
        bins[81] = 100;
        const PuddleEstimate one = EstimatePuddle(bins, 10.0f, pixels);
        assert(one.found && one.candidates == 400 && one.near == 400);
        assert(Near(one.height, 10.0f - 5.12f + (80.5f * 300.0f + 81.5f * 100.0f) / 400.0f * 0.04f, 1e-4f));
        bins[20] = 150; // a second level holds fewer: the first stays, 400 of 550 near it
        assert(EstimatePuddle(bins, 10.0f, pixels).found && Near(EstimatePuddle(bins, 10.0f, pixels).height,
                                                               one.height, 1e-4f));
        for (std::uint32_t i = 0; i < HeightBins; ++i) {
            bins[i] = 10; // spread over every height: no plane
        }
        assert(!EstimatePuddle(bins, 10.0f, pixels).found);
        std::uint32_t few[HeightBins] = {};
        few[64] = 150; // under the 207 a 1080p scene needs
        assert(!EstimatePuddle(few, 0.0f, pixels).found && EstimatePuddle(few, 0.0f, 640u * 480u).found);
        assert(PuddlesNotFloor(1000, 300) && !PuddlesNotFloor(1000, 700) && !PuddlesNotFloor(100, 10));
    }
    // The water's reflectance: F0 straight down, 1 at grazing.
    assert(Near(Reflectance(1.0f), float(CAUSTICS_WATER_F0), 1e-6f) && Near(Reflectance(0.0f), 1.0f, 1e-6f));
    assert(Reflectance(0.5f) > Reflectance(0.8f));
    // bbport (r107c_caustics-lamp-gain): the game's lamp curves; the water's share is never above 1.
    assert(Near(LampCurve(0.5f, -1.0f, 1.0f), 0.25f, 1e-6f) && LampCurve(0.999f, -1.0f, 1.0f) < 1e-5f);
    const float c2 = 0.05f * 0.05f, e = 1.0f / (30.0f * (1.0f - 0.05f * std::atan(20.0f) - 1.0f / (3.0f * (1.0f + c2))));
    assert(Near(LampCurve(0.5f, c2, e), e * (1.0f / (0.25f + c2) - 1.0f / (1.0f + c2)), 1e-5f));
    assert(LampCurve(1.0f, c2, e) == 0.0f && LampCurve(0.1f, c2, e) > LampCurve(0.2f, c2, e));
    assert(LampShare(LampGain, Reflectance(1.0f), 1.0f / PatternMean) < 1.0f && LampShare(LampGain, 0.02f, 0.0f) == 0.0f);
    assert(LampShare(4.0f * LampGain * ShowGain, 1.0f, 1.0f / PatternMean) <= 1.0f);

    // bbport (r128b_lrt-caustics-water): the setting as a strength, and the knobs with it. A variable that is set
    // and not empty decides for its channel (also 0, also text); else the setting (0..MaxStrength, 0 for what is
    // not finite or not above 0); show, unreadable and world stay the environment's.
    assert(SettingOf(0.0f) == 0.0f && SettingOf(-1.0f) == 0.0f && SettingOf(1.5f) == 1.5f);
    assert(SettingOf(9.0f) == MaxStrength && SettingOf(std::nanf("")) == 0.0f && SettingOf(INFINITY) == 0.0f);
    {
        const Knobs none = Parse(nullptr, nullptr);
        const Knobs off = WithSettings(none, false, false, 0.0f, 0.0f);
        assert(off.strength == 0.0f && off.lamp_strength == 0.0f && !off.show);
        const Knobs set = WithSettings(none, false, false, 1.0f, 2.5f);
        assert(set.strength == 1.0f && set.lamp_strength == 2.5f && GainOf(set) == Gain);
        const Knobs envs = WithSettings(Parse("0", "0.5"), true, true, 4.0f, 4.0f); // the variables decide
        assert(envs.strength == 0.0f && envs.lamp_strength == 0.5f);
        const Knobs half = WithSettings(Parse("2", nullptr), true, false, 4.0f, 3.0f); // sun env, lamps setting
        assert(half.strength == 2.0f && half.lamp_strength == 3.0f);
        const Knobs text = WithSettings(Parse("yes", nullptr), true, false, 4.0f, 0.0f);
        assert(text.strength == 0.0f && text.unreadable && text.lamp_strength == 0.0f);
        const Knobs show = WithSettings(Parse(nullptr, "show"), false, true, 2.0f, 4.0f); // show stays, lamps env
        assert(show.show && show.strength == 2.0f && show.lamp_strength == 1.0f);
        assert(WithSettings(none, false, false, 9.0f, 9.0f).strength == MaxStrength);
        assert(WithSettings(Parse("1", "1"), true, true, 4.0f, 4.0f).strength == 1.0f); // as before r128b
    }
    // The pattern's mean is 1 (PatternMean), its values from 0 to 1 / PatternMean.
    double sum = 0.0, share = 0.0; // r107c: share, the water's mean share at strength 1, 0.02
    float most = 0.0f, least = 1e9f;
    const std::array<float, 4> drift{1.5f, -2.0f, 3.0f, 0.5f};
    int n = 0;
    for (int i = 0; i < 400; ++i) {
        for (int j = 0; j < 400; ++j) {
            const float c = Pattern(-150.0f + 0.7531f * float(i), 80.0f + 0.6917f * float(j), drift,
                                    0.37f * float((i * 7 + j * 13) % 997));
            sum += c;
            share += LampShare(LampGain, Reflectance(1.0f), c);
            most = std::max(most, c);
            least = std::min(least, c);
            ++n;
        }
    }
    const double mean = sum / n;
    assert(mean > 0.96 && mean < 1.04);
    assert(least >= 0.0f && most <= 1.0f / PatternMean + 1e-3f);
    // r107c: about 0.37 (the README's "about 0.37"): the lamps' net at strength 1, straight down.
    assert(share / n > 0.33 && share / n < 0.41);
    // r107d: the look divides by that mean (CAUSTICS_LOOK_MEAN), so its contrast's mean is 1.
    assert(std::fabs(share / n - CAUSTICS_LOOK_MEAN) < 0.01);
    // bbport (r130b_water-moves): the moving water: the knob, the flag, the waves, the rings, the walker, the block, the twin's maths.
    {
        namespace M = Motion;
        // the knob: unset or empty -1 (the setting decides); else 0..4, text and not above 0 are 0
        assert(M::ParseEnv(nullptr) == -1.0f && M::ParseEnv("") == -1.0f);
        assert(M::ParseEnv("0") == 0.0f && M::ParseEnv("2.5") == 2.5f && M::ParseEnv("9") == MaxStrength);
        assert(M::ParseEnv("-1") == 0.0f && M::ParseEnv("abc") == 0.0f && M::ParseEnv("nan") == 0.0f && M::ParseEnv("1x") == 0.0f);
        assert(M::ParseEnv("1 ") == 1.0f);
        assert(M::Pick(-1.0f, 2.0f) == 2.0f && M::Pick(0.0f, 2.0f) == 0.0f && M::Pick(3.0f, 0.0f) == 3.0f);
        assert(M::Pick(-1.0f, 9.0f) == MaxStrength && M::Pick(-1.0f, NAN) == 0.0f && M::Pick(-1.0f, -2.0f) == 0.0f);
        // off: strength 0 (or not finite, or no dispatch) never gives the flag; a strength above 0 does
        assert(M::FlagsOf(0.0f, true) == 0u && M::FlagsOf(-1.0f, true) == 0u && M::FlagsOf(NAN, true) == 0u);
        assert(M::FlagsOf(1.0f, false) == 0u && M::FlagsOf(0.01f, true) == CAUSTICS_FLAG_MOTION && M::FlagMotion == 512u);
        assert(M::Words == 104u && M::Base == Slots * (SlotWords + DataWords) && M::Base * 4 == 8 * (168 + 48) * 4);
        // the dispersion of the 0.15 m wave: sqrt(g k + (sigma / rho) k^3) x 0.6, within 1% (k = 2 pi / 0.15)
        {
            const double k = 2.0 * M::Pi / 0.15, w = std::sqrt(9.81 * k + 7.4e-5 * k * k * k) * 0.6;
            assert(std::fabs(M::Omega(0.15) - w) < 0.01 * w && std::fabs(M::Omega(0.15) - 12.24) < 0.1);
            assert(M::Omega(0.60) < M::Omega(0.38) && M::Omega(0.38) < M::Omega(0.24) && M::Omega(0.24) < M::Omega(0.15));
        }
        // the heading follows the wind, low-passed: 63% of a step in 2 s; calm: 30 degrees; wind under 0.2 m/s is calm
        {
            M::State s;
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            assert(std::fabs(M::HeadingDeg(s) - 30.0) < 1e-6 && s.amp == 0.6f);
            M::State t = s;
            for (int i = 0; i < 20; ++i) {
                M::Advance(t, 0.1, {0.0f, 0.0f, 3.0f}, 2.0f); // wind toward +z: 90 degrees
            }
            const double moved = (M::HeadingDeg(t) - 30.0) / (90.0 - 30.0);
            assert(std::fabs(moved - (1.0 - std::exp(-1.0))) < 1e-6);
            M::State u = s;
            M::Advance(u, 0.1, {0.1f, 0.0f, 0.1f}, 2.0f);
            assert(std::fabs(M::HeadingDeg(u) - 30.0) < 1e-6);
            for (int i = 0; i < 400; ++i) {
                M::Advance(t, 0.1, {0.0f, 0.0f, 3.0f}, 2.0f);
            }
            assert(std::fabs(M::HeadingDeg(t) - 90.0) < 1e-3 && t.amp == 1.4f); // the cap, wind 3 m/s
            M::State v;
            M::Advance(v, 0.1, {NAN, 0.0f, INFINITY}, 2.0f); // not finite: calm
            assert(std::fabs(M::HeadingDeg(v) - 30.0) < 1e-6);
            // the amplitude factor: 0.6 calm, 1.0 at 1.5 m/s, 1.4 from 3 m/s; the steepness 0.05 x strength x it, at most 0.15
            M::State a;
            M::Advance(a, 0.1, {1.5f, 0.0f, 0.0f}, 2.0f);
            assert(Near(a.amp, 1.0f, 1e-6f) && Near(a.steep, 0.1f, 1e-6f));
            M::Advance(a, 0.1, {1.5f, 0.0f, 0.0f}, 4.0f);
            assert(a.steep == M::SteepMax);
            M::Advance(a, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f);
            assert(a.steep == 0.0f);
            // the phases stay in 0..2 pi however long it runs
            for (int i = 0; i < 100000; ++i) {
                M::Advance(a, 0.1, {0.0f, 0.0f, 0.0f}, 1.0f);
            }
            for (const double p : a.phase) {
                assert(p >= 0.0 && p < 2.0 * M::Pi);
            }
        }
        // the walker (footprints.h's cases): a step every 0.75 m of path, to the side in turn; a 2 m jump or a 1 m drop starts anew
        {
            M::Walker w;
            const float p0[3] = {0.0f, 0.0f, 0.0f};
            assert(!M::Walk(w, p0).step);
            int steps = 0;
            float side_sum = 0.0f;
            for (int i = 1; i <= 100; ++i) {
                const float p[3] = {0.1f * float(i), 0.0f, 0.0f};
                const M::Step st = M::Walk(w, p);
                steps += st.step ? 1 : 0;
                if (st.step) {
                    side_sum += st.z; // +0.11, -0.11 in turn: the sum stays within one
                    assert(Near(std::fabs(st.z), M::GaitHalfM, 1e-5f) && Near(st.x, p[0], 1e-5f));
                }
            }
            assert(steps == 13 && std::fabs(side_sum) <= M::GaitHalfM + 1e-5f); // 10 m / 0.75 m
            const float far[3] = {50.0f, 0.0f, 0.0f};
            assert(!M::Walk(w, far).step && w.jumps == 1 && w.acc == 0.0f);
            const float down[3] = {50.0f, -1.5f, 0.0f};
            assert(!M::Walk(w, down).step && w.jumps == 2);
            const float nan3[3] = {NAN, 0.0f, 0.0f};
            assert(!M::Walk(w, nan3).step && w.jumps == 3);
        }
        // steps and landings make rings (Observe); a drop of 0.3 to 1 m is a landing at twice the amplitude; a ring lives 2.5 s
        {
            M::State s;
            const float a[3] = {0.0f, 0.0f, 0.0f}, b[3] = {0.8f, 0.0f, 0.0f}, c[3] = {0.8f, -0.5f, 0.0f}, d[3] = {0.8f, -2.0f, 0.0f};
            assert(M::Observe(s, a, 2.0f).steps == 0 && s.count == 0);
            const M::Events one = M::Observe(s, b, 2.0f);
            assert(one.steps == 1 && one.landings == 0 && s.count == 1 && Near(s.rings[0].amp, 0.0016f, 1e-7f));
            const M::Events two = M::Observe(s, c, 2.0f);
            assert(two.landings == 1 && two.steps == 0 && s.count == 2 && Near(s.rings[1].amp, 0.0032f, 1e-7f));
            const M::Events three = M::Observe(s, d, 2.0f); // 1.5 m drop: a warp, no ring
            assert(three.steps == 0 && three.landings == 0 && s.count == 2);
            for (int i = 0; i < 24; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            }
            assert(s.count == 2); // 2.4 s
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 2.0f);
            assert(s.count == 0); // 2.6 s (the ages are floats: 25 steps of 0.1 may stay just under 2.5): gone
            // 20 rings: the oldest is replaced, 16 stay
            for (int i = 0; i < 20; ++i) {
                M::AddRing(s, float(i), 0.0f, 0.001f);
                M::Advance(s, 0.01, {0.0f, 0.0f, 0.0f}, 2.0f);
            }
            assert(s.count == 16);
        }
        // a ring is zero outside |s| < 3 w and after its life; its slope and curvature are the height's derivatives
        {
            M::State s;
            M::AddRing(s, 1.0f, 2.0f, 0.002f);
            for (int i = 0; i < 10; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f); // strength 0: no waves, the ring alone; age 1.0 s: radius 0.30 m
            }
            std::uint32_t block[M::Words];
            M::WriteBlock(block, s, 1, 2.0f);
            const double band = 3.0 * CAUSTICS_RING_WIDTH;
            for (int i = 0; i < 400; ++i) {
                const double r = 0.0125 * double(i); // 0 to 5 m from the ring's centre, along x
                const M::Sample v = M::Eval(block, 1.0 + r, 2.0);
                const bool inside = std::fabs(r - CAUSTICS_RING_SPEED * 1.0) < band + 0.002 || r < 1e-3; // (a margin: the age is a float)
                if (!inside) {
                    assert(v.eta == 0.0 && v.gx == 0.0 && v.gz == 0.0 && v.lap == 0.0 && !v.ring);
                }
            }
            double most = 0.0;
            for (int i = 0; i < 2000; ++i) {
                const double x = 1.0 + 0.2 + 0.0001 * double(i), z = 2.0 + 0.05; // across the packet
                const M::Sample v = M::Eval(block, x, z);
                const double h = 1e-6;
                const M::Sample xp = M::Eval(block, x + h, z), xm = M::Eval(block, x - h, z);
                const M::Sample zp = M::Eval(block, x, z + h), zm = M::Eval(block, x, z - h);
                if (std::fabs(std::sqrt((x - 1.0) * (x - 1.0) + 0.0025) - 0.3) > band - 0.01) {
                    continue; // near the cut: the packet is cut off at 3 w (a step of about 1% of its peak)
                }
                const double gx = (xp.eta - xm.eta) / (2 * h), gz = (zp.eta - zm.eta) / (2 * h);
                const double lap = (xp.eta + xm.eta + zp.eta + zm.eta - 4.0 * v.eta) / (h * h);
                assert(std::fabs(gx - v.gx) < 1e-5 * (1.0 + std::fabs(v.gx)) && std::fabs(gz - v.gz) < 1e-5 * (1.0 + std::fabs(v.gz)));
                assert(std::fabs(lap - v.lap) < 1e-4 * (1.0 + std::fabs(v.lap)));
                most = std::max(most, std::fabs(v.lap));
            }
            assert(most > 1.0); // the ring bends the light (curvature of the order a k^2 / sqrt(1 + r / r0): a few per metre)
            for (int i = 0; i < 16; ++i) {
                M::Advance(s, 0.1, {0.0f, 0.0f, 0.0f}, 0.0f); // 2.6 s in all: gone
            }
            M::WriteBlock(block, s, 1, 2.0f);
            assert(block[CAUSTICS_MOTION_RINGS] == 0u && !M::Eval(block, 1.3, 2.0).ring);
        }
        // the waves' slope and curvature are the height's derivatives, and the block is the layout's (kind, rings, strength, 0 ring px)
        {
            M::State s;
            for (int i = 0; i < 37; ++i) {
                M::Advance(s, 0.05, {1.0f, 0.0f, 0.5f}, 2.0f);
            }
            std::uint32_t block[M::Words];
            std::memset(block, 0xAB, sizeof(block));
            M::WriteBlock(block, s, 2, 2.0f);
            assert(block[CAUSTICS_MOTION_KIND] == 2u && block[CAUSTICS_MOTION_RINGS] == 0u && block[CAUSTICS_MOTION_RING_PX] == 0u);
            assert(M::BitsToFloat(block[CAUSTICS_MOTION_STRENGTH]) == 2.0f);
            for (std::uint32_t i = CAUSTICS_MOTION_RINGS_AT; i < M::Words; ++i) {
                assert(block[i] == 0u);
            }
            double worst = 0.0;
            for (int i = 0; i < 200; ++i) {
                const double x = -3.0 + 0.0613 * double(i), z = 4.0 - 0.0471 * double(i);
                const M::Sample v = M::Eval(block, x, z);
                const double h = 1e-5;
                const M::Sample xp = M::Eval(block, x + h, z), xm = M::Eval(block, x - h, z);
                const M::Sample zp = M::Eval(block, x, z + h), zm = M::Eval(block, x, z - h);
                assert(std::fabs((xp.eta - xm.eta) / (2 * h) - v.gx) < 1e-5 && std::fabs((zp.eta - zm.eta) / (2 * h) - v.gz) < 1e-5);
                worst = std::max(worst, std::fabs((xp.eta + xm.eta + zp.eta + zm.eta - 4.0 * v.eta) / (h * h) - v.lap));
            }
            assert(worst < 0.05);
        }
        // the focus keeps the light's mean at 1 (4 x 4 m, strength 4, windy, rings alive, four moments); the slope stays moderate
        {
            double worst = 0.0, top_slope = 0.0, top_warp = 0.0, sum_all = 0.0;
            int moments = 0;
            M::State s;
            const float feet[6][3] = {{0.0f, 0.0f, 0.0f}, {0.8f, 0.0f, 0.1f}, {1.6f, 0.0f, 0.0f},
                                      {2.4f, 0.0f, 0.1f}, {3.2f, 0.0f, 0.0f}, {4.0f, 0.0f, 0.1f}};
            for (int step = 0; step < 6; ++step) {
                M::Observe(s, feet[step], 4.0f);
                for (int i = 0; i < 8; ++i) {
                    M::Advance(s, 0.05, {1.5f, 0.0f, 0.4f}, 4.0f);
                }
            }
            for (int moment = 0; moment < 4; ++moment) {
                for (int i = 0; i < 17; ++i) {
                    M::Advance(s, 0.05, {1.5f, 0.0f, 0.4f}, 4.0f);
                }
                std::uint32_t block[M::Words];
                M::WriteBlock(block, s, 1, 4.0f);
                double sum = 0.0;
                int n = 0;
                for (int i = 0; i < 200; ++i) {
                    for (int j = 0; j < 200; ++j) {
                        const M::Sample v = M::Eval(block, 0.0207 * i, 0.0203 * j);
                        sum += M::Focus(float(v.lap));
                        ++n;
                        top_slope = std::max(top_slope, std::hypot(v.gx, v.gz));
                        top_warp = std::max(top_warp, 4.0 * std::hypot(v.gx, v.gz));
                    }
                }
                worst = std::max(worst, std::fabs(sum / n - 1.0));
                sum_all += sum / n;
                ++moments;
            }
            std::printf("water motion: focus mean %.4f (worst moment %.4f), top slope %.3f, top warp %.2f m\n", sum_all / moments,
                        worst, top_slope, top_warp);
            assert(worst < 0.03);
            assert(top_slope < 0.8);
        }
    }
    // bbport (r130e_sewer-water-moves): the rippled reflection: the band, the shift, the glint, the stamp, the bed light's rule, the
    // lone motion.
    {
        namespace M = Motion;
        namespace W = Motion::Warp;
        static_assert(W::FlagCopy == 1024u && W::FlagWarp == 2048u && W::StampCount == 2047u);
        static_assert(CAUSTICS_MOTION_ROW0 == 100 && CAUSTICS_MOTION_STAMP == 103 && CAUSTICS_MOTION_WORDS == 104);
        // a camera (1080p, 60 degrees vertical, view y up on screen: proj y < 0 as the engine's) `above` the plane y = 0, pitched down
        const auto camera = [](float above, float pitch_deg) {
            Push p{};
            const float rad = pitch_deg * 3.14159265f / 180.0f, c = std::cos(rad), s = std::sin(rad);
            p.proj = {0.974f, -1.732f, 0.0f, 0.0f};
            p.frame = {1920.0f, 1080.0f, 0.0f, 0.0f};
            p.inv_view = {1.0f, 0.0f, 0.0f, 0.0f, 0.0f, c, -s, above, 0.0f, s, c, 0.0f};
            return p;
        };
        // WaterTopRow: level, 1.07 m above the plane: the plane is within 45 m from 1.07 / 45 below the horizon (row 540 + 22),
        // minus the margin 16, on the 8 row grid
        {
            const std::uint32_t level = W::WaterTopRow(camera(1.07f, 0.0f), 0.0f, 1920, 1080);
            const double expect = 540.0 + 540.0 * (1.07 / 45.0) * 1.732 - 16.0;
            assert(std::fabs(double(level) - expect) <= 12.0 && (level + 16u) % 8u == 0u);
            assert(W::WaterTopRow(camera(1.07f, 60.0f), 0.0f, 1920, 1080) == 0u);      // looking down: every row is in range
            assert(W::WaterTopRow(camera(-1.0f, 0.0f), 0.0f, 1920, 1080) == 1080u);    // the plane above the camera: none
            assert(W::WaterTopRow(camera(1.07f, -40.0f), 0.0f, 1920, 1080) == 1080u);  // looking up 40 degrees: all above the horizon
            assert(W::WaterTopRow(camera(1.07f, 0.0f), NAN, 1920, 1080) == 1080u);
            assert(W::WaterTopRow(camera(1.07f, 0.0f), 0.0f, 0, 1080) == 1080u);
            assert(W::WaterTopRow(camera(40.0f, 0.0f), 0.0f, 1920, 1080) == 1080u);    // 40 m up, level: no ray meets it within 45 m
        }
        // ShiftPx: slope 0 none; 0.05 along x at z 3 m: 2 x 0.25 x 0.05 = 0.025 m across, f 0.974 x 960 px: 7.79 px, under the clamp;
        // along z it moves the point away (a small step on screen); 1: clamped to 0.012 x 1080 px; 50 m away: faded out
        {
            const Push level = camera(1.07f, 0.0f);
            const auto none = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.0f, 0.0f);
            assert(none[0] == 0.0f && none[1] == 0.0f);
            const auto across = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.05f, 0.0f);
            assert(Near(across[0], 0.974f * 0.025f / 3.0f * 960.0f, 0.01f) && std::fabs(across[1]) < 1e-3f);
            const auto back = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 0.0f, 0.05f);
            const float y0 = (1.07f * 1.732f / 3.0f + 1.0f) * 540.0f, y1 = (1.07f * 1.732f / 3.025f + 1.0f) * 540.0f;
            assert(std::fabs(back[0]) < 1e-3f && Near(back[1], y1 - y0, 0.01f) && back[1] < 0.0f);
            const auto big = W::ShiftPx(level, {0.0f, 0.0f, 3.0f}, 1.0f, 0.0f);
            assert(Near(std::hypot(big[0], big[1]), W::ShiftMax * 1080.0f, 1e-3f) && big[0] > 0.0f);
            const auto distant = W::ShiftPx(level, {0.0f, 0.0f, 50.0f}, 0.05f, 0.0f);
            assert(distant[0] == 0.0f && distant[1] == 0.0f);
            const auto behind = W::ShiftPx(level, {0.0f, 0.0f, -3.0f}, 0.05f, 0.0f);
            assert(behind[0] == 0.0f && behind[1] == 0.0f);
        }
        // Stamp: 1 to 2047, wraps; exact in half float (integers to 2048)
        {
            assert(W::Stamp(0) == 1u && W::Stamp(2046) == 2047u && W::Stamp(2047) == 1u && W::Stamp(4294967295u) >= 1u);
            for (std::uint32_t d = 0; d < 5000; ++d) {
                assert(W::Stamp(d) >= 1u && W::Stamp(d) <= 2047u && W::Stamp(d) != W::Stamp(d + 1u));
            }
        }
        // WorldFor: a set variable wins (also 0); else the bed starts with the motion and the lamps; else the variable's own value
        {
            assert(W::WorldFor(false, 0.0f, 2.0f, 4.0f) == W::BedAuto && W::WorldFor(false, 0.0f, 0.0f, 4.0f) == 0.0f);
            assert(W::WorldFor(false, 0.0f, 2.0f, 0.0f) == 0.0f && W::WorldFor(false, 0.0f, NAN, 4.0f) == 0.0f);
            assert(W::WorldFor(true, 0.0f, 2.0f, 4.0f) == 0.0f && W::WorldFor(true, 2.5f, 0.0f, 0.0f) == 2.5f);
            assert(W::WorldFor(true, 0.5f, 2.0f, 4.0f) == 0.5f && W::WorldFor(false, 1.5f, 0.0f, 0.0f) == 1.5f);
        }
        // Alone: only with motion, a plane, the camera above it and nothing else drawing
        {
            assert(W::Alone(2.0f, true, true, false, false));
            assert(!W::Alone(0.0f, true, true, false, false) && !W::Alone(-1.0f, true, true, false, false) &&
                   !W::Alone(NAN, true, true, false, false) && !W::Alone(INFINITY, true, true, false, false));
            assert(!W::Alone(2.0f, false, true, false, false) && !W::Alone(2.0f, true, false, false, false));
            assert(!W::Alone(2.0f, true, true, true, false) && !W::Alone(2.0f, true, true, false, true));
        }
        // GlintOf: 1 with no strength, no luminance, no curvature; follows the knob; symmetric clamp; faded
        {
            assert(W::GlintOf(1.0f, 1.0f, 0.0f) == 1.0f && W::GlintOf(1.0f, 0.0f, 4.0f) == 1.0f && W::GlintOf(0.0f, 1.0f, 4.0f) == 1.0f);
            assert(W::GlintOf(-1.0f, 1.0f, 2.0f) > 1.0f && W::GlintOf(1.0f, 1.0f, 2.0f) < 1.0f); // a hollow brightens, a crest dims
            assert(W::GlintOf(-1.0f, 1.0f, 4.0f) - 1.0f > 1.9f * (W::GlintOf(-1.0f, 1.0f, 2.0f) - 1.0f));
            assert(W::GlintOf(-100.0f, 1.0f, 4.0f) == 1.0f + W::GlintMax && W::GlintOf(100.0f, 1.0f, 4.0f) == 1.0f - W::GlintMax);
            assert(W::GlintOf(-1.0f, 1.0f, 4.0f, 0.0f) == 1.0f);
            assert(std::fabs(W::GlintOf(-1.0f, 0.01f, 4.0f) - 1.0f) < std::fabs(W::GlintOf(-1.0f, 1.0f, 4.0f) - 1.0f)); // dark: less
        }
        // The glint's mean over a 4 x 4 m grid of the wave field (calm, windy, rings, four moments) stays 1 at strength 2 and 4, and
        // the swing on a bright reflection is clearly there: its rms at strength 2 and 4 (the calm field, the weakest)
        {
            double worst = 0.0, rms2 = 0.0, rms4 = 0.0, top = 0.0;
            for (const float strength : {2.0f, 4.0f}) {
                for (const float wind : {0.0f, 1.5f}) {
                    M::State s;
                    const float feet[6][3] = {{0.0f, 0.0f, 0.0f}, {0.8f, 0.0f, 0.1f}, {1.6f, 0.0f, 0.0f},
                                              {2.4f, 0.0f, 0.1f}, {3.2f, 0.0f, 0.0f}, {4.0f, 0.0f, 0.1f}};
                    for (int step = 0; step < 6; ++step) {
                        M::Observe(s, feet[step], strength);
                        for (int i = 0; i < 8; ++i) {
                            M::Advance(s, 0.05, {wind, 0.0f, 0.4f * wind}, strength);
                        }
                    }
                    for (int moment = 0; moment < 4; ++moment) {
                        for (int i = 0; i < 17; ++i) {
                            M::Advance(s, 0.05, {wind, 0.0f, 0.4f * wind}, strength);
                        }
                        std::uint32_t block[M::Words];
                        M::WriteBlock(block, s, 1, strength);
                        double sum = 0.0, sq = 0.0;
                        int n = 0;
                        for (int i = 0; i < 200; ++i) {
                            for (int j = 0; j < 200; ++j) {
                                const M::Sample v = M::Eval(block, 0.0207 * i, 0.0203 * j);
                                const double g = double(W::GlintOf(float(v.lap), 1.0f, strength)) - 1.0;
                                sum += g;
                                sq += g * g;
                                top = std::max(top, std::fabs(g));
                                ++n;
                            }
                        }
                        worst = std::max(worst, std::fabs(sum / n));
                        if (wind == 0.0f) {
                            (strength == 2.0f ? rms2 : rms4) += std::sqrt(sq / n) / 4.0;
                        }
                    }
                }
            }
            std::printf("water warp: glint mean off 1 by at most %.4f; swing on a bright reflection, calm field: rms %.3f at strength 2, "
                        "%.3f at 4, at most %.2f\n", worst, rms2, rms4, top);
            assert(worst < 0.03);
            assert(rms2 > 0.06 && rms4 > 1.5 * rms2 && top <= double(W::GlintMax) + 1e-6);
        }
    }
    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f; lamp share %.3f)\n", mean, n,
                double(least), double(most), share / n);
    return 0;
}
