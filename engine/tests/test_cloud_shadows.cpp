// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r105_cloud-shadows): checks of gpu/shadps4/video_core/renderer_vulkan/cloud_shadow_params.h,
// the cloud shadows' knobs, direction rule, drift and push words (built and run by engine/build.sh
// --test and the CMake target cloud-shadows-test).
//  a. BB_CLOUD_SHADOWS: missing, empty, not a number or below 0: 0 (off); clamped to 1.
//  b. BB_CLOUD_SHADOWS_SCALE: missing or not a number: 100 m (r105b; 70 m with SHOW); clamped to
//     40-600.
//  c. BB_CLOUD_SHADOWS_SHOW=1 turns them on at strength 1 with the show look.
//  d. BB_CLOUDS_DIR: a number (wrapped into [0, 360)), "auto", or the wind's direction (missing,
//     empty, other text) (r105b).
//  e. The light kept: 1 below the low edge, 1 - depth above the high edge, never rising with n.
//  f. Slope and Plane: the light's height floor, a point carried along the light.
//  g. Auto: across the light (its azimuth + 90 deg); none for a light straight up.
//  h. Easing goes the shorter way round and reaches the target.
//  i. The direction's source (r105b): the wind (BB_WIND=1), then BB_CLOUDS_DIR's number, then auto,
//     then the wind's BB_WIND_DIR with its wander; auto snaps to the first light, then eases, and
//     keeps its value without a light.
//  j. The drift: the largest octave's offset is the lattice point of the clouds' travel (speed x
//     time toward the direction) and of the morph (time / MorphSeconds) in its third axis.
//  k. The push words: the Params block's order and the knobs in their slots.
//  l. The wind's knobs (r105b): BB_WIND_DIR and BB_WIND_SPEED read as the wind reads them; the
//     clouds' speed is SpeedRatio (ShowSpeedRatio) times the wind's.
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <initializer_list>

#include "gpu/shadps4/video_core/renderer_vulkan/cloud_shadow_params.h"

using namespace CloudShadows;

namespace {

bool Near(double a, double b, double eps) {
    return std::fabs(a - b) <= eps;
}

// The difference a - b of two lattice coordinates, wrapped into [-Period / 2, Period / 2).
double CellGap(double a, double b) {
    const double p = VolumetricFogNoise::Period;
    return VolumetricFogNoise::WrapCells(a - b + p / 2.0) - p / 2.0;
}

double DegGap(double a, double b) {
    return std::fabs(double(ArcDeg(float(b), float(a))));
}

} // namespace

int main() {
    // a.
    for (const char* off : {static_cast<const char*>(nullptr), "", "0", "-1", "abc", "nan", "inf"}) {
        assert(!MakeKnobs(off, nullptr, nullptr, nullptr).On());
    }
    assert(Near(MakeKnobs("0.5", nullptr, nullptr, nullptr).strength, 0.5, 1e-6));
    assert(Near(MakeKnobs("1", nullptr, nullptr, nullptr).strength, 1.0, 1e-6));
    assert(Near(MakeKnobs("3", nullptr, nullptr, nullptr).strength, MaxStrength, 1e-6));
    const Knobs plain = MakeKnobs("1", nullptr, nullptr, nullptr);
    assert(!plain.show && Near(plain.Depth(), FullDepth, 1e-6));
    assert(plain.LowEdge() == Low && plain.HighEdge() == High &&
           Near(plain.Velocity(), SpeedRatio * BbWind::DefaultSpeed, 1e-6));
    // b.
    assert(plain.scale == DefaultScale);
    assert(MakeKnobs("1", "10", nullptr, nullptr).scale == MinScale);
    assert(MakeKnobs("1", "5000", nullptr, nullptr).scale == MaxScale);
    assert(MakeKnobs("1", "250", nullptr, nullptr).scale == 250.0f);
    assert(MakeKnobs("1", "wide", nullptr, nullptr).scale == DefaultScale);
    // c.
    const Knobs show = MakeKnobs(nullptr, nullptr, "1", nullptr);
    assert(show.On() && show.show && show.strength == MaxStrength && show.scale == ShowScale);
    assert(Near(show.Depth(), ShowDepth, 1e-6) && show.LowEdge() == ShowLow &&
           show.HighEdge() == ShowHigh &&
           Near(show.Velocity(), ShowSpeedRatio * BbWind::DefaultSpeed, 1e-6));
    assert(MakeKnobs("0", "100", "1", nullptr).scale == 100.0f);
    assert(!MakeKnobs("0", nullptr, "0", nullptr).On());
    assert(Low < High && ShowLow < ShowHigh && FullDepth < 1.0f && ShowDepth < 1.0f);
    // d.
    for (const char* windy : {static_cast<const char*>(nullptr), "", "left", "Auto"}) {
        assert(MakeKnobs("1", nullptr, nullptr, windy).dir == Source::WindKnob);
    }
    assert(MakeKnobs("1", nullptr, nullptr, "auto").dir == Source::Auto);
    assert(MakeKnobs("1", nullptr, nullptr, "90").dir == Source::Env &&
           MakeKnobs("1", nullptr, nullptr, "90").dir_deg == 90.0f);
    assert(Near(MakeKnobs("1", nullptr, nullptr, "-90").dir_deg, 270.0, 1e-4));
    assert(Near(MakeKnobs("1", nullptr, nullptr, "720.5").dir_deg, 0.5, 1e-3));
    // e.
    assert(Light(0.0f, 0.6f, Low, High) == 1.0f && Light(Low, 0.6f, Low, High) == 1.0f);
    assert(Near(Light(High, 0.6f, Low, High), 0.4, 1e-6) && Near(Light(1.0f, 0.6f, Low, High), 0.4, 1e-6));
    float last = 1.0f;
    for (int i = 0; i <= 100; ++i) {
        const float l = Light(float(i) / 100.0f, 0.6f, Low, High);
        assert(l <= last + 1e-7f && l >= 0.4f - 1e-6f);
        last = l;
    }
    assert(Light(0.9f, 0.0f, Low, High) == 1.0f);
    // f.
    const auto low_sun = Slope({0.0f, 0.05f, 1.0f});
    assert(Near(low_sun[0], 0.0, 1e-6) && Near(low_sun[1], 1.0 / MinLightY, 1e-4));
    const auto slope = Slope({0.6f, 0.8f, 0.0f});
    assert(Near(slope[0], 0.75, 1e-6) && slope[1] == 0.0f);
    // a point 4 m up the light's ray from p lands where p does
    const std::array<float, 3> p{10.0f, 2.0f, -3.0f}, up{10.0f + 0.6f * 4.0f, 2.0f + 0.8f * 4.0f, -3.0f};
    assert(Near(Plane(p, slope)[0], Plane(up, slope)[0], 1e-4) && Plane(p, slope)[1] == -3.0f);
    // g.
    float deg = -1.0f;
    assert(AutoDeg({1.0f, 0.5f, 0.0f}, &deg) && Near(deg, 90.0, 1e-4));
    assert(AutoDeg({0.0f, 0.3f, 1.0f}, &deg) && Near(deg, 180.0, 1e-4));
    // a light logged in a slot run (world -0.803, 0.375, 0.464): azimuth 149.98 deg, auto 239.98
    assert(AutoDeg({-0.803f, 0.375f, 0.464f}, &deg) && Near(deg, 239.98, 0.01));
    assert(AutoDeg({-1.0f, 0.0f, 0.0f}, &deg) && Near(deg, 270.0, 1e-4));
    assert(!AutoDeg({0.0f, 1.0f, 0.0f}, &deg) && !AutoDeg({NAN, 0.5f, 0.5f}, &deg));
    // h.
    float e = 350.0f;
    for (int i = 0; i < 4; ++i) {
        e = EaseDeg(e, 10.0f, 1.0, EaseSeconds);
        assert(e > 350.0f || e < 10.0f);
    }
    e = EaseDeg(e, 10.0f, 1000.0, EaseSeconds);
    assert(DegGap(e, 10.0) < 1e-3);
    assert(EaseDeg(40.0f, 100.0f, 0.0, EaseSeconds) == 40.0f);
    assert(Near(EaseDeg(0.0f, 100.0f, EaseSeconds, EaseSeconds), 100.0 * (1.0 - std::exp(-1.0)), 1e-3));
    // i.
    {
        const Knobs env = MakeKnobs("1", nullptr, nullptr, "30");
        State s; // r105b: with BB_WIND=1 the wind decides, whatever BB_CLOUDS_DIR says
        s.Advance(env, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);
        assert(s.From() == Source::Wind && s.Direction() == 200.0f);
        State en;
        en.Advance(env, false, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);
        assert(en.From() == Source::Env && en.Direction() == 30.0f);
        State w;
        w.Advance(plain, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);
        assert(w.From() == Source::Wind && w.Direction() == 200.0f);
        // the wind off: the wind's base direction with its wander, at the state's own time
        const Knobs blows = MakeKnobs("1", nullptr, nullptr, nullptr, "100", nullptr);
        State b;
        for (int i = 0; i < 1200; ++i) { // 120 s
            b.Advance(blows, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.1);
            assert(b.From() == Source::WindKnob);
            assert(Near(b.Direction(), BbWind::WanderDeg(b.Time(), 100.0f), 1e-3));
            assert(DegGap(b.Direction(), 100.0) <= double(BbWind::Wander) + 1e-3);
        }
        const Knobs autok = MakeKnobs("1", nullptr, nullptr, "auto");
        State a;
        a.Advance(autok, false, 200.0f, false, {}, 0.05);
        assert(a.From() == Source::Auto && a.Direction() == StartDirection);
        a.Advance(autok, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.05); // first light: at once
        assert(Near(a.Direction(), 90.0, 1e-4));
        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 0.1); // eased toward 180
        assert(a.Direction() > 90.0f && a.Direction() < 95.0f);
        const float held = a.Direction();
        a.Advance(autok, false, 0.0f, false, {}, 0.1); // no light: kept
        assert(a.Direction() == held);
        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, NAN); // no time: kept
        assert(a.Direction() == held && Near(a.Time(), 0.3, 1e-9));
        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 50.0); // clamped to MaxStep
        assert(Near(a.Time(), 0.3 + MaxStep, 1e-9));
    }
    // j.
    {
        const Knobs k = MakeKnobs("1", "200", nullptr, "60");
        State s;
        const int steps = 2000; // 100 s after the first step (which only takes the time)
        for (int i = 0; i <= steps; ++i) {
            s.Advance(k, false, 0.0f, true, {0.0f, 1.0f, 0.0f}, 0.05);
        }
        const double t = steps * 0.05;
        const auto v = DriftVelocity(60.0f, k.Velocity(), 200.0f); // r105b: the wind's x 4
        assert(Near(k.Velocity(), SpeedRatio * BbWind::DefaultSpeed, 1e-6));
        assert(Near(std::hypot(v[0], v[2]), k.Velocity(), 1e-4) && Near(std::atan2(v[2], v[0]) * 57.29577951308232, 60.0, 1e-3));
        const std::array<float, 3> travel{float(v[0] * t), float(v[1] * t), float(v[2] * t)};
        const auto want = VolumetricFogNoise::LatticePoint(travel, 0, 200.0f);
        const auto got = s.Offsets().Cells(0);
        for (int i = 0; i < 3; ++i) {
            assert(Near(CellGap(got[i], want[i]), 0.0, 1e-3));
        }
        assert(Near(got[1], t / MorphSeconds, 1e-4));
        for (std::size_t o = 0; o < 3; ++o) {
            for (const float c : s.Offsets().Cells(o)) {
                assert(c >= 0.0f && c < 256.0f);
            }
        }
    }
    // k.
    {
        static_assert(offsetof(Push, off0) == 48 && offsetof(Push, off1) == 64 &&
                      offsetof(Push, off2) == 80 && offsetof(Push, slope) == 96 &&
                      offsetof(Push, high) == 104 && offsetof(Push, offsets) == 108 &&
                      offsetof(Push, reach) == 112 && sizeof(Push) == 120);
        const Knobs k = MakeKnobs("0.5", "100", nullptr, nullptr);
        State s;
        const std::array<float, 12> rows{1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7};
        const Push push = MakePush(rows, s, k, {0.6f, 0.8f, 0.0f}, 0x1234u, 40.0f);
        assert(push.view_to_world == rows && Near(push.off0[3], 0.5 * FullDepth, 1e-6));
        assert(Near(push.off1[3], 0.01, 1e-7) && push.off2[3] == Low && push.high == High);
        assert(Near(push.slope[0], 0.75, 1e-6) && push.offsets == 0x1234u && push.reach == 40.0f);
    }
    // l. (r105b)
    {
        const Knobs a = MakeKnobs("1", nullptr, nullptr, nullptr, "90", "3");
        assert(a.wind_deg == 90.0f && a.wind_speed == 3.0f);
        assert(Near(a.Velocity(), 3.0 * SpeedRatio, 1e-6));
        const Knobs b = MakeKnobs("1", nullptr, nullptr, nullptr, "-30", "9");
        assert(Near(b.wind_deg, 330.0, 1e-4) && b.wind_speed == BbWind::MaxSpeed);
        const Knobs c = MakeKnobs("1", nullptr, nullptr, nullptr, "east", "");
        assert(c.wind_deg == BbWind::DefaultDirection && c.wind_speed == BbWind::DefaultSpeed);
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, "nan", "-2");
        assert(d.wind_deg == BbWind::DefaultDirection && d.wind_speed == 0.0f);
        assert(d.Velocity() == 0.0f);
        const Knobs sh = MakeKnobs(nullptr, nullptr, "1", nullptr, nullptr, "2");
        assert(Near(sh.Velocity(), 2.0 * ShowSpeedRatio, 1e-6));
        // the wind's default speed gives r105's speeds (6 m/s, SHOW 15 m/s)
        assert(Near(SpeedRatio * BbWind::DefaultSpeed, 6.0, 1e-6) &&
               Near(ShowSpeedRatio * BbWind::DefaultSpeed, 15.0, 1e-6));
    }
    // m. (r116b) the wind's weather moves the clouds: their speed is the ratio times the wind's mean speed
    // of the frame, their cover shifts the edges; without the wind, or without a speed, nothing changes.
    {
        const Knobs k = MakeKnobs("1", nullptr, nullptr, nullptr);
        const std::array<float, 3> light{0.6f, 0.8f, 0.0f};
        const std::array<float, 12> rows{};
        State s;
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        s.Advance(k, true, 200.0f, false, light, 0.1);
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        s.Advance(k, true, 200.0f, false, light, 0.1, 0.8f, 0.01f);
        assert(Near(s.Velocity(k), 0.8 * SpeedRatio, 1e-5) && s.CoverShift() == 0.01f);
        const Push calm = MakePush(rows, s, k, light, 0u, 0.0f);
        assert(Near(calm.off2[3], Low - 0.01, 1e-6) && Near(calm.high, High - 0.01, 1e-6));
        s.Advance(k, true, 200.0f, false, light, 0.1, 3.2f, -0.02f);
        assert(Near(s.Velocity(k), 3.2 * SpeedRatio, 1e-5) && s.CoverShift() == -0.02f);
        s.Advance(k, true, 200.0f, false, light, 0.1, -1.0f, 0.03f); // no speed: the knobs'; no weather: no shift
        assert(Near(s.Velocity(k), k.Velocity(), 1e-6) && s.CoverShift() == 0.0f);
        State off;
        off.Advance(k, false, 200.0f, false, light, 0.1, 3.0f, 0.03f); // wind off: both ignored
        assert(Near(off.Velocity(k), k.Velocity(), 1e-6) && off.CoverShift() == 0.0f);
        const Push plain_push = MakePush(rows, off, k, light, 0u, 0.0f);
        assert(plain_push.off2[3] == Low && plain_push.high == High);
        const Knobs show = MakeKnobs(nullptr, nullptr, "1", nullptr);
        State sh;
        sh.Advance(show, true, 200.0f, false, light, 0.1, 2.0f);
        assert(Near(sh.Velocity(show), 2.0 * ShowSpeedRatio, 1e-5));
        // the weather's speed range gives the clouds 1.6 to 15.6 m/s (4 x 0.4 to 4 x 3.9)
        assert(Near(BbWind::CloudRatio * BbWind::WeatherMin, 1.6, 1e-6) && Near(BbWind::CloudRatio * BbWind::WeatherMax, 15.6, 1e-5));
    }
    std::puts("cloud shadows: ok"); // r105b: a to l
    return 0;
}
