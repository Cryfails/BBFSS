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
    std::printf("caustics: ok (pattern mean %.4f over %d points, %.3f to %.3f; lamp share %.3f)\n", mean, n,
                double(least), double(most), share / n);
    return 0;
}
