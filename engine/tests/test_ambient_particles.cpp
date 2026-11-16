// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): the ambient motes' knobs, drift and push block
// (gpu/shadps4/video_core/renderer_vulkan/ambient_particles.h). Built and run by engine/build.sh
// --test and the CMake target ambient-particles-test.
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <limits>
#include <bit>    // bbport (r98c_particles-visible)
#include <vector> // bbport (r98c_particles-visible)

#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles.h"
#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles_lamps.h" // r98c
#include "gpu/shadps4/video_core/renderer_vulkan/ambient_particles_still.h" // r98d

using namespace Vulkan::AmbientMotes;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(double a, double b, double tolerance) {
    return std::fabs(a - b) <= tolerance;
}
} // namespace

int main() {
    // a. BB_PARTICLES: unset, empty, 0, negative, unreadable and not finite are off; clamped to 2.
    for (const char* off : {static_cast<const char*>(nullptr), "", "0", "-1", "abc", "nan", "inf"}) {
        Expect(!Parse(off, nullptr, nullptr).On(), "an unset, 0 or unreadable BB_PARTICLES is off");
    }
    Expect(Parse("1", nullptr, nullptr).density == 1.0f, "BB_PARTICLES=1 is density 1");
    Expect(Parse("0.5", nullptr, nullptr).density == 0.5f, "BB_PARTICLES=0.5 is density 0.5");
    Expect(Parse("7", nullptr, nullptr).density == MaxDensity, "BB_PARTICLES above 2 is 2");
    // b. BB_PARTICLES_EMBERS and BB_PARTICLES_SHOW.
    Expect(Parse("1", nullptr, nullptr).embers == DefaultEmbers, "unset embers take the default");
    Expect(Parse("1", "x", nullptr).embers == DefaultEmbers, "unreadable embers take the default");
    Expect(Parse("1", "0.5", nullptr).embers == 0.5f, "BB_PARTICLES_EMBERS=0.5");
    Expect(Parse("1", "3", nullptr).embers == 1.0f && Parse("1", "-2", nullptr).embers == 0.0f,
           "embers clamp to 0-1");
    Expect(Parse("1", nullptr, "1").show && !Parse("1", nullptr, "0").show &&
               !Parse("1", nullptr, nullptr).show,
           "BB_PARTICLES_SHOW is on with a leading 1 only");

    // c. Occupancy: 0.3 a density, at most 0.9.
    Expect(Near(Occupancy(Parse("1", nullptr, nullptr)), 0.3, 1e-6), "density 1 fills 30% of cells");
    Expect(Near(Occupancy(Parse("2", nullptr, nullptr)), 0.6, 1e-6), "density 2 fills 60% of cells");

    // d. Drift: steps clamped, bad steps move nothing, wraps.
    {
        Drift a, b;
        a.Advance(0.5, false, {});
        b.Advance(MaxStep, false, {});
        Expect(a.time == b.time && a.offset == b.offset && a.time == MaxStep,
               "a 0.5 s step counts as 0.1 s");
        for (const double bad : {std::numeric_limits<double>::quiet_NaN(), -1.0,
                                 std::numeric_limits<double>::infinity()}) {
            Drift c = b;
            c.Advance(bad, true, {1.0f, 0.0f, 1.0f});
            Expect(c.time == b.time && c.offset == b.offset, "a bad step moves nothing");
        }
        Drift calm;
        for (int i = 0; i < 100; ++i) {
            calm.Advance(0.05, false, {9.0f, 9.0f, 9.0f});
        }
        Expect(Near(calm.offset[0], 5.0 * CalmDrift[0], 1e-9) && Near(calm.offset[1], 0.0, 1e-12) &&
                   Near(calm.offset[2], 5.0 * CalmDrift[2], 1e-9),
               "without the wind the lattice drifts at CalmDrift");
        Drift windy;
        for (int i = 0; i < 100; ++i) {
            windy.Advance(0.05, true, {2.0f, 0.0f, -1.0f});
        }
        Expect(Near(windy.offset[0], 5.0 * 2.0 * WindFollow, 1e-6) &&
                   Near(windy.offset[2], Period - 5.0 * WindFollow, 1e-6),
               "with the wind the lattice drifts at WindFollow x the wind, wrapped into [0, Period)");
        Drift bad_wind;
        bad_wind.Advance(0.05, true, {std::numeric_limits<float>::quiet_NaN(), 0.0f, 0.0f});
        Expect(bad_wind.offset[0] == 0.0, "a wind that is not finite counts as 0");
        Drift late;
        late.time = TimeWrap - 0.01;
        late.Advance(0.05, false, {});
        Expect(Near(late.time, 0.04, 1e-9), "the time wraps at TimeWrap");
        Expect(Period == 768.0 && Wrap(-1.0, Period) == Period - 1.0 && Wrap(Period, Period) == 0.0,
               "the period is 768 m and Wrap stays in [0, Period)");
    }

    // e. The push block.
    {
        std::array<float, 12> view{}, inv{};
        for (int i = 0; i < 12; ++i) {
            view[i] = float(i);
            inv[i] = float(100 + i);
        }
        Drift d;
        d.time = 12.5;
        d.offset = {1.0, 2.0, 3.0};
        const Push p = MakePush(Parse("1", "0.25", "1"), d, view, inv, {1.5f, -2.0f, 1.0f, -0.1f},
                                3840, 2160, 1920, 1080, {0.25f, -0.5f}, true);
        Expect(p.view == view && p.proj[1] == -2.0f, "view rows and projection as given");
        Expect(p.camera[0] == 103.0f && p.camera[1] == 107.0f && p.camera[2] == 111.0f &&
                   p.camera[3] == 12.5f,
               "the camera is inv_view's translation, then the time");
        Expect(p.drift[0] == 1.0f && p.drift[2] == 3.0f && Near(p.drift[3], 0.3, 1e-6),
               "drift and occupancy");
        Expect(Near(p.look[0], Gain * ShowGain, 1e-6) && p.look[1] == 0.25f &&
                   p.look[2] == ShowSize && p.look[3] == ShowFloor,
               "BB_PARTICLES_SHOW=1 exaggerates gain and size and adds the floor");
        Expect(p.frame[0] == (3840u | 2160u << 16) && p.frame[1] == (1920u | 1080u << 16),
               "sizes packed as w | h << 16");
        Expect(Near(Unsnorm16(p.frame[2]), 0.25, 1e-4) && Near(Unsnorm16(p.frame[2] >> 16), -0.5, 1e-4),
               "the jitter round-trips through snorm16");
        Expect(p.frame[3] == std::uint32_t(AP_FLAG_SCENE_SRGB), "the sRGB flag");
        const Push plain = MakePush(Parse("1", nullptr, nullptr), d, view, inv, {}, 1280, 720, 640,
                                    360, {0.0f, 0.0f}, false);
        Expect(plain.look[0] == Gain && plain.look[2] == 1.0f && plain.look[3] == 0.0f &&
                   plain.frame[2] == 0u && plain.frame[3] == 0u,
               "without show: the plain look, no flags");
        Expect(Unsnorm16(Snorm16(5.0f)) == 1.0f && Unsnorm16(Snorm16(-5.0f)) == -1.0f,
               "the jitter clamps to -1..1");
    }

    // f. bbport (r98c_particles-visible): the lamps (ambient_particles_lamps.h).
    {
        Expect(ParseLampGain(nullptr) == DefaultLampGain && ParseLampGain("x") == DefaultLampGain,
               "an unset or unreadable BB_PARTICLES_LAMPS is 1");
        Expect(ParseLampGain("0") == 0.0f && ParseLampGain("-1") == 0.0f &&
                   ParseLampGain("9") == MaxLampGain && ParseLampGain("0.5") == 0.5f,
               "BB_PARTICLES_LAMPS clamps to 0-4, 0 is off");
        Expect(IsFlame({1.0f, 0.5f, 0.15f}, 6.0f) && !IsFlame({1.0f, 1.0f, 1.0f}, 6.0f) &&
                   !IsFlame({0.2f, 0.4f, 1.0f}, 6.0f) && !IsFlame({1.0f, 0.5f, 0.15f}, 30.0f),
               "a warm lamp of a flame's reach is a flame; white, cold or far-reaching ones are not");
        // The r64 probe's records: the hand torch burns; the glass street lamp, a warm fill light
        // and the yellow lamps of the alley do not.
        Expect(Burns({2.6f, 1.45f, 0.65f}, 8.5f) && Burns({2.0f, 1.18f, 0.59f}, 8.0f) &&
                   !Burns({0.72f, 0.42f, 0.26f}, 6.0f) && !Burns({0.60f, 0.45f, 0.30f}, 9.0f) &&
                   !Burns({1.50f, 1.12f, 0.75f}, 9.0f),
               "a flame burns when bright and red enough");
        Expect(SparkShare(4.0f) == 0.0f && SparkShare(8.0f) == 1.0f && SparkShare(5.47f) > 0.25f &&
                   SparkShare(5.47f) < 0.35f,
               "no embers at a reach of 4 m, all from 8 m, about 0.3 for the church's chandeliers");
        const float seed = SeedOf(7);
        Expect(seed >= 0.0f && seed < 1.0f &&
                   float(std::uint32_t(seed * 16777216.0f)) == seed * 16777216.0f &&
                   SeedOf(7) != SeedOf(8),
               "a seed is a 24-bit fraction, its own for each serial");
        Expect(SparkBirth(Parse("1", nullptr, nullptr)) == SparkBirthPerDensity &&
                   SparkBirth(Parse("2", nullptr, "1")) == MaxOccupancy,
               "the ember chance follows the density, at most MaxOccupancy");
        const auto calm = SparkDrift(false, {9.0f, 9.0f, 9.0f});
        const auto windy = SparkDrift(true, {2.0f, std::numeric_limits<float>::quiet_NaN(), -1.0f});
        Expect(calm == CalmDrift && windy[0] == 2.0f * SparkWindFollow && windy[1] == 0.0f &&
                   windy[2] == -SparkWindFollow,
               "the embers go with the calm drift, or with the wind (not finite: 0)");

        const auto record = [](float x, float y, float z, float reach, float r, float g, float b) {
            std::array<std::uint32_t, 16> w{};
            const std::array<float, 7> f{x, y, z, 1.0f / (reach * reach), r, g, b};
            for (std::size_t i = 0; i < f.size(); ++i) {
                w[i] = std::bit_cast<std::uint32_t>(f[i]);
            }
            return w;
        };
        // The camera at (10, 0, 0) looking along +z: view = world - camera.
        const std::array<float, 12> inv{1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0};
        LampSet set;
        const auto torch = record(0.0f, 1.0f, 3.0f, 8.0f, 2.4f, 1.3f, 0.6f);
        const auto white = record(1.0f, 0.0f, 2.0f, 5.0f, 1.0f, 1.0f, 1.0f);
        const auto distant = record(0.0f, 0.0f, 40.0f, 6.0f, 2.4f, 1.3f, 0.6f);
        Expect(LampSet::Useful(torch.data()) && !LampSet::Useful(distant.data()),
               "a record beyond max(16 m, 7.5 m + reach) of the camera is not gathered");
        set.Add(torch.data(), 1);
        set.Add(white.data(), 1);
        set.Add(distant.data(), 1);
        set.Add(torch.data(), 1); // one lamp in two tiles
        LampBlock b = set.Update(inv, 0.1, 1.0f, 0.5f, {0.06f, 0.0f, 0.04f});
        Expect(b.info[0] == 2.0f && b.info[1] == 1.0f && b.info[2] == 1.0f && b.info[3] == 0.5f &&
                   set.Last().listed == 2,
               "two lamps (one listed twice, a far one skipped), one flame, the gain and the chance");
        Expect(b.place[0][0] == 10.0f && b.place[0][1] == 1.0f && b.place[0][2] == 3.0f &&
                   Near(b.place[0][3], 8.0, 1e-4) && b.place[1][0] == 11.0f,
               "the flame first, then the lamp, in the world");
        Expect(Near(b.colour[0][3], 0.1 / LampSet::FadeIn, 1e-6) && b.colour[1][1] == 1.0f,
               "a new lamp fades in; the colour as drawn");
        Expect(b.flame[0][0] == SeedOf(1) && b.flame[0][1] == SparkShare(8.0f) * b.colour[0][3] &&
                   b.flame[1][1] == 0.0f,
               "the flame's seed and share; no flame in the next slot");
        Expect(b.wind[0] == 0.06f && b.wind[2] == 0.04f, "the embers' drift");
        // Listed again a little moved and dimmed by its flicker below the bright limit: the same
        // lamp (its seed stays), still burning.
        const auto moved = record(0.05f, 1.0f, 3.0f, 8.0f, 1.1f, 0.6f, 0.28f);
        set.Add(moved.data(), 1);
        b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == 2.0f && b.info[1] == 1.0f && b.flame[0][0] == SeedOf(1) &&
                   Near(b.place[0][0], 10.05, 1e-5) && set.Kept() == 2,
               "a lamp listed again near its place is the same lamp, and it keeps burning");
        // Unlisted: held for Hold s (still fading in), then fading out over FadeOut s, then gone.
        for (int i = 0; i < 5; ++i) {
            b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        }
        Expect(b.info[0] == 2.0f && b.colour[0][3] == 1.0f, "held while unlisted");
        for (int i = 0; i < 20; ++i) {
            b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        }
        Expect(b.info[0] == 0.0f && set.Kept() == 0, "faded out and dropped");
        // More lamps than places: the flames (at most 8, nearest first), then the brightest.
        for (int i = 0; i < 12; ++i) {
            const auto flame = record(float(i) * 0.6f, 0.0f, 2.0f, 6.0f, 2.0f, 1.18f, 0.59f);
            const auto lamp = record(float(i) * 0.6f, 2.0f, 2.0f, 6.0f, 0.5f + 0.1f * float(i),
                                     0.5f + 0.1f * float(i), 0.5f + 0.1f * float(i));
            set.Add(flame.data(), 1);
            set.Add(lamp.data(), 1);
        }
        b = set.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == float(AP_MAX_LAMPS) && b.info[1] == float(AP_MAX_FLAMES) &&
                   set.Last().left_out == std::uint32_t(24 - AP_MAX_LAMPS) && b.place[0][0] == 10.0f,
               "16 lamps in the block, the 8 nearest flames first");
        // A warp: all forgotten.
        const std::array<float, 12> away{1, 0, 0, 500, 0, 1, 0, 0, 0, 0, 1, 0};
        b = set.Update(away, 0.1, 1.0f, 0.5f, {});
        Expect(b.info[0] == 0.0f && set.Kept() == 0, "a camera jump forgets the lamps");
        // A candle (bright, reach 2 m: no share of embers) lights the dust but takes no flame slot.
        LampSet candles;
        const auto candle = record(0.0f, 0.0f, 2.0f, 2.0f, 2.67f, 1.83f, 0.96f);
        candles.Add(candle.data(), 1);
        b = candles.Update(inv, 0.1, 1.0f, 0.5f, {});
        Expect(Burns({2.67f, 1.83f, 0.96f}, 2.0f) && b.info[0] == 1.0f && b.info[1] == 0.0f &&
                   b.flame[0][1] == 0.0f,
               "a flame with no share of embers is a lamp, not a flame slot");
        Expect(sizeof(LampBlock) == AP_LAMP_BLOCK_BYTES && FlameInstances == 128u,
               "the block's bytes and the flames' instances");
    }

    // g. bbport (r98d_particles-still-indoors): sheltered air (ambient_particles_still.h).
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

    std::printf("ambient-particles-test: %u cells, %s\n", Instances,
                failures == 0 ? "all checks pass" : "FAILED");
    return failures == 0 ? 0 : 1;
}
