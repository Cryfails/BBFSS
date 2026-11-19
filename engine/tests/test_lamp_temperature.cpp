// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r123_lamp-colour-temperature): the lamp colour temperature's knobs, blackbody colours,
// kinds, tint and its place in the lamp flicker's tracker
// (gpu/shadps4/video_core/renderer_vulkan/lamp_temperature.h, lamp_flicker.h).
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h"
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_temperature.h"

using namespace LampTemperature;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

std::uint32_t U(float f) {
    return std::bit_cast<std::uint32_t>(f);
}

float Fl(std::uint32_t u) {
    return std::bit_cast<float>(u);
}

float LumaOf(const std::array<float, 3>& c) {
    return Luma[0] * c[0] + Luma[1] * c[1] + Luma[2] * c[2];
}

/// One record: view space place, reach, colour; words 7 to 15 hold other things.
std::array<std::uint32_t, 16> Record(float x, float y, float z, float reach, float r, float g,
                                     float b) {
    std::array<std::uint32_t, 16> rec{};
    rec[0] = U(x);
    rec[1] = U(y);
    rec[2] = U(z);
    rec[3] = U(1.0f / (reach * reach));
    rec[4] = U(r);
    rec[5] = U(g);
    rec[6] = U(b);
    for (std::uint32_t i = 7; i < 16; ++i) {
        rec[i] = 0xA5A50000u + i;
    }
    return rec;
}

std::array<float, 3> ColourOf(const std::uint32_t* rec) {
    return {Fl(rec[4]), Fl(rec[5]), Fl(rec[6])};
}

const auto Count = [](const char*, auto&&...) {};

// The camera at the world origin looking down view -z: view space is world space.
constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};

struct Sample {
    const char* name;
    std::array<float, 3> colour;
    float reach;
    Kind kind;
    float least_k, most_k; ///< the kelvin the rules give
};
// The game's own lamp colours (probe lists of 2026-11-15/16).
const Sample Samples[] = {
    {"hunter torch", {2.91f, 1.63f, 0.73f}, 8.5f, Kind::Fire, 1849.0f, 1851.0f},
    {"hand lantern", {1.34f, 0.75f, 0.34f}, 5.2f, Kind::Fire, 1849.0f, 1851.0f},
    {"church candle", {2.06f, 1.41f, 0.74f}, 2.0f, Kind::Candle, 1849.0f, 1851.0f},
    {"church candle, dim", {1.0f, 0.62f, 0.36f}, 3.0f, Kind::Candle, 1849.0f, 1851.0f},
    {"wall lantern", {1.79f, 1.07f, 0.66f}, 6.0f, Kind::Lantern, 2100.0f, 2300.0f},
    {"street lamp", {1.0f, 0.74f, 0.50f}, 5.0f, Kind::Street, 2549.0f, 2551.0f},
    {"big pale lamp", {1.5f, 1.12f, 0.75f}, 9.0f, Kind::Street, 2549.0f, 2551.0f},
};
} // namespace

int main() {
    // a. knobs
    {
        Expect(ParseStrength(nullptr) == 0.0f && ParseStrength("") == 0.0f, "a1 unset is 0");
        Expect(ParseStrength("0") == 0.0f && ParseStrength("-1") == 0.0f, "a2 0 and below are 0");
        Expect(ParseStrength("abc") == 0.0f && ParseStrength("nan") == 0.0f, "a3 text is 0");
        Expect(ParseStrength("0.5") == 0.5f && ParseStrength("1") == 1.0f, "a4 numbers");
        Expect(ParseStrength("7") == 1.0f, "a5 clamped to 1");
        Expect(ParseSpread(nullptr) == DefaultSpread && ParseSpread("") == DefaultSpread,
               "a6 spread unset is the default");
        Expect(ParseSpread("abc") == DefaultSpread && ParseSpread("inf") == DefaultSpread,
               "a7 spread text is the default");
        Expect(ParseSpread("0") == 0.0f && ParseSpread("-5") == 0.0f, "a8 spread 0 and below");
        Expect(ParseSpread("80") == 80.0f && ParseSpread("9000") == MaxSpread, "a9 spread clamped");
        Expect(!Setting{}.On() && Setting{0.1f, 150.0f}.On(), "a10 On");
        Expect(ParseShow("1") && !ParseShow(nullptr) && !ParseShow("") && !ParseShow("0") &&
                   !ParseShow("2") && !ParseShow("11") && !ParseShow("abc") && !Setting{}.show,
               "a11 the test view is exactly 1 (r123b)");
    }
    // b. blackbody colours: luminance 1, warm, monotone, continuous, clamped
    {
        float before_gr = 0.0f, before_br = 0.0f;
        bool monotone = true;
        for (float k = MinKelvin; k <= MaxKelvin; k += 25.0f) {
            const auto c = Blackbody(k);
            Expect(std::abs(LumaOf(c) - 1.0f) < 1e-5f, "b1 luminance 1");
            Expect(c[0] > c[1] && c[1] > c[2] && c[2] >= BlueFloor * c[0] * 0.999f,
                   "b2 red, green, blue in order, blue floor");
            const float gr = c[1] / c[0], br = c[2] / c[0];
            monotone = monotone && gr >= before_gr - 1e-5f && br >= before_br - 1e-5f; // blue sits on its floor at first
            before_gr = gr;
            before_br = br;
        }
        Expect(monotone, "b3 green/red and blue/red rise with the kelvin");
        const auto a = Blackbody(2221.99f), b = Blackbody(2222.0f);
        Expect(std::abs(a[0] - b[0]) < 1e-3f * a[0] && std::abs(a[1] - b[1]) < 1e-3f * a[1] &&
                   std::abs(a[2] - b[2]) < 1e-3f * a[2],
               "b4 no step at 2222 K");
        Expect(Blackbody(1000.0f) == Blackbody(MinKelvin) && Blackbody(9000.0f) == Blackbody(MaxKelvin),
               "b5 clamped to the fit's range");
        const auto k1850 = Blackbody(1850.0f);
        Expect(std::abs(k1850[1] / k1850[0] - 0.2196f) < 2e-3f, "b6 1850 K green/red (model 0.2196)");
        std::printf("blackbody: 1850 K g/r %.3f b/r %.3f, 2600 K g/r %.3f b/r %.3f\n",
                    double(k1850[1] / k1850[0]), double(k1850[2] / k1850[0]),
                    double(Blackbody(2600.0f)[1] / Blackbody(2600.0f)[0]),
                    double(Blackbody(2600.0f)[2] / Blackbody(2600.0f)[0]));
    }
    // c. the kinds and their kelvin
    {
        for (const Sample& s : Samples) {
            const Class c = Classify(s.colour, s.reach);
            Expect(c.kind == s.kind, s.name);
            Expect(c.kelvin >= s.least_k && c.kelvin <= s.most_k, s.name);
        }
        // the reach blends a lamp into a candle between 4.4 and 3.2 m; continuous in the colour
        const std::array<float, 3> lamp{1.79f, 1.07f, 0.66f};
        float before = Classify(lamp, 5.0f).kelvin, largest = 0.0f;
        for (float r = 5.0f; r >= 2.5f; r -= 0.01f) {
            const float k = Classify(lamp, r).kelvin;
            largest = std::max(largest, std::abs(k - before));
            before = k;
        }
        Expect(largest < 30.0f, "c1 the kelvin moves smoothly with the reach");
        Expect(Classify(lamp, 3.0f).kelvin == KFire && Classify(lamp, 4.5f).kelvin == Classify(lamp, 9.0f).kelvin,
               "c2 candle reach and beyond");
        before = Classify({1.0f, 0.6f, 0.20f}, 6.0f).kelvin;
        largest = 0.0f;
        for (float b = 0.20f; b <= 0.60f; b += 0.001f) {
            const float k = Classify({1.0f, 0.6f, b}, 6.0f).kelvin;
            largest = std::max(largest, std::abs(k - before));
            before = k;
        }
        Expect(largest < 15.0f, "c3 the kelvin moves smoothly with blue / red");
    }
    // d. the tint: luminance kept, strength 0 and KRef keep the colour, warmer is redder
    {
        for (const Sample& s : Samples) {
            for (const float strength : {0.25f, 0.5f, 1.0f}) {
                for (const float offset : {-1.0f, 0.0f, 1.0f}) {
                    const Tinted t = Tint(s.colour, s.reach, offset, strength, 150.0f);
                    Expect(std::abs(LumaOf(t.colour) - LumaOf(s.colour)) <= 1e-5f * LumaOf(s.colour),
                           "d1 luminance is the game's");
                    Expect(t.colour[0] > 0.0f && t.colour[1] > 0.0f && t.colour[2] > 0.0f,
                           "d2 colour stays positive");
                    Expect(t.kind == s.kind, "d3 the kind");
                }
            }
            const Tinted zero = Tint(s.colour, s.reach, 0.3f, 0.0f, 150.0f);
            Expect(zero.colour == s.colour, "d4 strength 0: the same colour");
        }
        // 2600 K changes nothing (up to float noise), 1850 K is redder, more strength more so
        const std::array<float, 3> game{1.5f, 0.9f, 0.5f};
        const auto warm1 = Tint(game, 2.0f, 0.0f, 1.0f, 0.0f); // candle: 1850 K
        const auto warm05 = Tint(game, 2.0f, 0.0f, 0.5f, 0.0f);
        Expect(warm1.colour[1] / warm1.colour[0] < warm05.colour[1] / warm05.colour[0] &&
                   warm05.colour[1] / warm05.colour[0] < game[1] / game[0],
               "d5 more strength is redder");
        Expect(warm1.colour[2] / warm1.colour[0] < warm05.colour[2] / warm05.colour[0] &&
                   warm05.colour[2] / warm05.colour[0] < game[2] / game[0],
               "d6 and has less blue");
        // KRef changes nothing, and (r123b) every kind with its largest offset is warmer than KRef
        const std::array<float, 3> pale{1.5f, 1.1f, 0.75f}; // blue / red 0.5: a street lamp, 2550 K
        const auto at_ref = TintToKelvin(pale, KRef, Calibration);
        Expect(KRef > KPale + MaxSpread, "d7 every lamp is warmer than KRef");
        Expect(std::abs(at_ref[0] - pale[0]) < 2e-4f && std::abs(at_ref[1] - pale[1]) < 2e-4f &&
                   std::abs(at_ref[2] - pale[2]) < 2e-4f,
               "d8 KRef keeps the game's colour");
        // the spread: lamps of one colour with different offsets differ, with spread 0 they do not
        const auto lo = Tint(game, 9.0f, -1.0f, 1.0f, 150.0f);
        const auto hi = Tint(game, 9.0f, 1.0f, 1.0f, 150.0f);
        Expect(std::abs(hi.kelvin - lo.kelvin - 300.0f) < 1e-3f, "d9 the spread is +-150 K");
        Expect(hi.colour[1] / hi.colour[0] > lo.colour[1] / lo.colour[0], "d10 hotter is yellower");
        Expect(Tint(game, 9.0f, -1.0f, 1.0f, 0.0f).colour == Tint(game, 9.0f, 1.0f, 1.0f, 0.0f).colour,
               "d11 spread 0: no difference");
        // a colour without luminance or not finite stays
        const std::array<float, 3> nothing{0.0f, 0.0f, 0.0f};
        Expect(Tint(nothing, 5.0f, 0.0f, 1.0f, 150.0f).colour == nothing, "d12 black stays");
        // the torch and the candle numbers written in the header's comment
        const auto torch = Tint({2.91f, 1.63f, 0.73f}, 8.5f, 0.0f, 1.0f, 0.0f);
        Expect(std::abs(torch.colour[1] / torch.colour[0] - 0.359f) < 5e-3f, "d13 torch green/red 0.36");
        const auto candle = Tint({1.0f, 0.62f, 0.36f}, 3.0f, 0.0f, 1.0f, 0.0f);
        Expect(std::abs(candle.colour[1] / candle.colour[0] - 0.397f) < 5e-3f, "d14 candle green/red 0.40");
        std::printf("tint: torch g/r %.3f b/r %.3f; candle g/r %.3f b/r %.3f\n",
                    double(torch.colour[1] / torch.colour[0]), double(torch.colour[2] / torch.colour[0]),
                    double(candle.colour[1] / candle.colour[0]), double(candle.colour[2] / candle.colour[0]));
        // r123b: a street lamp is moved now (blue / red 0.50 -> 0.30 at 2550 K), and the test view
        const auto street = Tint({1.0f, 0.74f, 0.50f}, 5.0f, 0.0f, 1.0f, 0.0f);
        Expect(std::abs(street.colour[1] / street.colour[0] - 0.6275f) < 5e-3f &&
                   std::abs(street.colour[2] / street.colour[0] - 0.2967f) < 5e-3f,
               "d15 street lamp green/red 0.63, blue/red 0.30");
        const auto shown = Tint({1.0f, 0.62f, 0.36f}, 3.0f, 0.0f, 1.0f, 0.0f, true);
        Expect(std::abs(LumaOf(shown.colour) - LumaOf({1.0f, 0.62f, 0.36f})) <= 1e-5f * LumaOf({1.0f, 0.62f, 0.36f}) &&
                   shown.kind == Kind::Candle,
               "d16 the view keeps the luminance and the kind");
        Expect(shown.colour[1] / shown.colour[0] < candle.colour[1] / candle.colour[0] &&
                   shown.colour[2] / shown.colour[0] < candle.colour[2] / candle.colour[0] &&
                   shown.colour[1] > 0.0f && shown.colour[2] > 0.0f,
               "d17 the view is redder and stays positive");
        const auto direct = TintToKelvin({1.0f, 0.62f, 0.36f}, shown.kelvin, Calibration * ShowScale);
        Expect(std::abs(direct[0] - shown.colour[0]) < 1e-6f && std::abs(direct[2] - shown.colour[2]) < 1e-6f,
               "d18 the view is the exponent times ShowScale");
        Expect(Tint({1.0f, 0.62f, 0.36f}, 3.0f, 0.0f, 0.0f, 0.0f, true).colour ==
                   std::array<float, 3>{1.0f, 0.62f, 0.36f},
               "d19 strength 0 with the view: the game's colour");
    }
    // e. in the tracker: records tinted after the ramp, the same in every tile, the rest kept
    {
        LampFlicker::Params p = LampFlicker::ParseParams(nullptr, nullptr, nullptr); // no flicker
        LampFlicker::Tracker t{p};
        t.SetStrengths(0.0f, 0.0f);
        const auto street_a = Record(2.0f, 1.0f, -6.0f, 5.0f, 1.0f, 0.74f, 0.50f);
        const auto street_b = Record(-7.0f, 1.0f, -9.0f, 5.0f, 1.0f, 0.74f, 0.50f); // same colour
        const auto candle = Record(0.5f, 0.5f, -3.0f, 2.0f, 2.06f, 1.41f, 0.74f);
        const auto moon = Record(4.0f, 3.0f, -8.0f, 12.0f, 0.28f, 0.53f, 1.00f); // cold: no flame
        std::vector<std::uint32_t> in(64), out(64), tile(16);
        std::copy(street_a.begin(), street_a.end(), in.begin());
        std::copy(street_b.begin(), street_b.end(), in.begin() + 16);
        std::copy(candle.begin(), candle.end(), in.begin() + 32);
        std::copy(moon.begin(), moon.end(), in.begin() + 48);
        bool early = false, late = false, tiles_differ = false, luma_ok = true, rest_kept = true;
        bool moon_changed = false;
        t.SetTemperature(Setting{1.0f, 150.0f});
        for (int f = 0; f < 60 * 3; ++f) {
            const bool changed = t.Patch(in.data(), 4, out.data(), Identity.data());
            if (f == 0) {
                early = changed; // the ramp starts at the first frame end
            }
            late = changed;
            t.Patch(street_a.data(), 1, tile.data(), Identity.data());
            tiles_differ = tiles_differ || !std::equal(tile.begin(), tile.end(), out.begin());
            for (std::size_t k = 0; k < 3; ++k) {
                const std::uint32_t* a = in.data() + k * 16;
                const std::uint32_t* b = out.data() + k * 16;
                luma_ok = luma_ok && std::abs(LumaOf(ColourOf(b)) - LumaOf(ColourOf(a))) <=
                                         1e-5f * LumaOf(ColourOf(a));
                for (int w : {0, 1, 2, 3, 7, 8, 15}) {
                    rest_kept = rest_kept && a[w] == b[w];
                }
            }
            moon_changed = moon_changed || !std::equal(out.begin() + 48, out.begin() + 64, in.begin() + 48);
            t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);
        }
        Expect(!early, "e1 nothing changes before the first frame end");
        Expect(late, "e2 the colours are tinted after the ramp");
        Expect(!tiles_differ, "e3 the same lamp gets the same colour in every tile");
        Expect(luma_ok, "e4 each lamp keeps the game's luminance");
        Expect(rest_kept, "e5 place, reach and the other words are kept");
        Expect(!moon_changed, "e6 a cold light is left alone");
        const auto ca = ColourOf(out.data()), cb = ColourOf(out.data() + 16);
        Expect(ca != cb, "e7 two street lamps of one colour get different colours (the spread)");
        Expect(std::abs(ca[1] / ca[0] - cb[1] / cb[0]) < 0.12f, "e8 within the spread's reach");
        const auto cc = ColourOf(out.data() + 32);
        Expect(cc[1] / cc[0] < 1.41f / 2.06f, "e9 the candle is redder than the game made it");
        std::printf("tracker: street lamps g/r %.3f and %.3f (game 0.740), candle g/r %.3f (game 0.684)\n",
                    double(ca[1] / ca[0]), double(cb[1] / cb[0]), double(cc[1] / cc[0]));
        // the setting back to 0: the records return to the game's own after the ramp
        t.SetTemperature(Setting{0.0f, 150.0f});
        bool changed_after = true;
        for (int f = 0; f < 60 * 3; ++f) {
            changed_after = t.Patch(in.data(), 4, out.data(), Identity.data());
            t.EndFrame(3.0 + f / 60.0 + 1.0 / 60.0, Count);
        }
        Expect(!changed_after, "e10 strength 0 again: the game's colours");
    }
    // f. with the flicker on top: the light is the game's times the flicker factor, tinted colour
    {
        LampFlicker::Tracker t{LampFlicker::ParseParams("1", "0", nullptr)}; // flicker, no colour shift
        t.SetStrengths(1.0f, 0.0f);
        t.SetTemperature(Setting{1.0f, 150.0f});
        const auto lamp = Record(1.0f, 1.0f, -5.0f, 5.0f, 1.0f, 0.74f, 0.50f);
        std::array<std::uint32_t, 16> out{};
        bool factor_ok = true, tinted_late = false;
        float least = 2.0f, most = 0.0f;
        for (int f = 0; f < 60 * 8; ++f) {
            t.Patch(lamp.data(), 1, out.data(), Identity.data());
            const float factor = LumaOf(ColourOf(out.data())) / LumaOf(ColourOf(lamp.data()));
            if (f > 60 * 2) {
                least = std::min(least, factor);
                most = std::max(most, factor);
                factor_ok = factor_ok && factor >= 1.0f - LampFlicker::Swing - 1e-4f &&
                            factor <= 1.0f + LampFlicker::Swing + 1e-4f;
                tinted_late = tinted_late || out[5] != U(Fl(lamp[5]) * factor);
            }
            t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);
        }
        Expect(factor_ok, "f2 luminance within the flicker's swing of the game's");
        Expect(least < 0.97f && most > 1.03f, "f3 the flicker is used on a tinted lamp");
        Expect(tinted_late, "f4 the colour is the tinted one");
    }
    // g. the ramp: 0 to full in RampSeconds, no jump larger than a frame's share
    {
        LampFlicker::Tracker t{LampFlicker::ParseParams(nullptr, nullptr, nullptr)};
        t.SetStrengths(0.0f, 0.0f);
        t.SetTemperature(Setting{1.0f, 0.0f});
        const auto lamp = Record(1.0f, 1.0f, -5.0f, 2.0f, 2.0f, 1.2f, 0.7f);
        std::array<std::uint32_t, 16> out{};
        float before = 1.2f / 2.0f, largest = 0.0f, last = before;
        for (int f = 0; f < 60 * 2; ++f) {
            t.Patch(lamp.data(), 1, out.data(), Identity.data());
            const auto c = ColourOf(out.data());
            last = c[1] / c[0];
            largest = std::max(largest, std::abs(last - before));
            before = last;
            t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);
        }
        Expect(largest < 0.01f, "g1 the green/red moves by less than 0.01 a frame");
        Expect(last < 0.5f, "g2 and arrives");
    }
    // h. (r123b) the test view in the tracker: the same lamp is redder than without it
    {
        const auto lamp = Record(1.0f, 1.0f, -5.0f, 2.0f, 2.0f, 1.2f, 0.7f);
        float plain_gr = 0.0f, shown_gr = 0.0f;
        for (const bool show : {false, true}) {
            LampFlicker::Tracker t{LampFlicker::ParseParams(nullptr, nullptr, nullptr)};
            t.SetStrengths(0.0f, 0.0f);
            t.SetTemperature(Setting{1.0f, 0.0f, show});
            std::array<std::uint32_t, 16> out{};
            for (int f = 0; f < 60 * 2; ++f) {
                t.Patch(lamp.data(), 1, out.data(), Identity.data());
                t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);
            }
            const auto c = ColourOf(out.data());
            (show ? shown_gr : plain_gr) = c[1] / c[0];
        }
        Expect(shown_gr < plain_gr - 0.1f, "h1 the test view is redder in the tracker");
    }
    if (failures == 0) {
        std::printf("lamp-temperature-test: all checks passed\n");
    }
    return failures == 0 ? 0 : 1;
}
