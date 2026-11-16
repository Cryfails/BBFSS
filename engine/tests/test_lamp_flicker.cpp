// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r96_lamp-flicker-colour): the lamp flicker's knobs, wave, colour gains, flame test and
// tracker (gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h).
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/lamp_flicker.h"
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"

using namespace LampFlicker;

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

float LumaOf(const std::uint32_t* rec) {
    return Luma[0] * Fl(rec[4]) + Luma[1] * Fl(rec[5]) + Luma[2] * Fl(rec[6]);
}

int lines = 0;
const auto Count = [](const char*, auto&&...) { ++lines; };

// The camera at the world origin looking down view -z: view space is world space.
constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
} // namespace

int main() {
    // a. knobs
    {
        const Params off = ParseParams(nullptr, nullptr, nullptr);
        Expect(!off.on && off.strength == 0.0f, "a1 unset is off");
        Expect(!ParseParams("0", nullptr, nullptr).on, "a2 0 is off");
        Expect(!ParseParams("abc", nullptr, nullptr).on, "a3 text is off");
        Expect(!ParseParams("-1", nullptr, nullptr).on, "a4 negative is off");
        Expect(!ParseParams("nan", nullptr, nullptr).on, "a5 nan is off");
        const Params one = ParseParams("1", nullptr, nullptr);
        Expect(one.on && one.strength == 1.0f && one.temp == DefaultTemp && !one.show,
               "a6 1 is full strength, default colour shift");
        Expect(ParseParams("3", nullptr, nullptr).strength == 1.0f, "a7 clamped to 1");
        Expect(ParseParams("0.5", "0", nullptr).temp == 0.0f, "a8 temp 0");
        Expect(ParseParams("0.5", "7", nullptr).temp == 1.0f, "a9 temp clamped");
        Expect(ParseParams("0.5", "x", nullptr).temp == DefaultTemp, "a10 temp text: default");
        const Params show = ParseParams("1", nullptr, "1");
        Expect(show.show && show.Amplitude() == std::min(MaxSwing, Swing * ShowScale),
               "a11 show multiplies the swing");
        Expect(one.Amplitude() == Swing, "a12 swing at 1");
    }
    // b. wave: bounded, smooth (step per 1/60 s within the bound of its derivative)
    {
        float most = 0.0f, step = 0.0f;
        double bound = 0.0;
        for (std::size_t i = 0; i < 3; ++i) {
            bound += double(WaveWeight[i]) * WaveHz[i] * 1.15 * 6.283185307179586;
        }
        for (std::uint32_t seed : {1u, 77u, 0xDEADBEEFu, 123456789u}) {
            float before = Wave(seed, 0.0);
            for (int f = 1; f < 60 * 120; ++f) {
                const float w = Wave(seed, f / 60.0);
                most = std::max(most, std::abs(w));
                step = std::max(step, std::abs(w - before));
                before = w;
            }
        }
        Expect(most <= 1.0f + 1e-5f, "b1 |wave| <= 1");
        Expect(most > 0.5f, "b2 the wave moves");
        Expect(double(step) <= bound / 60.0 + 1e-4, "b3 step per frame within the slope bound");
        std::printf("wave: largest %.4f, largest step per 1/60 s %.4f (bound %.4f)\n", double(most),
                    double(step), bound / 60.0);
        Expect(Wave(5u, 10.0) != Wave(6u, 10.0), "b4 seeds differ");
        Expect(Wave(5u, 1000000.25) == Wave(5u, 1000000.25), "b5 deterministic");
    }
    // c. gains: luminance exactly f times, dimmer redder, brighter yellower, no shift at T 0
    {
        const std::array<float, 3> c{1.0f, 0.55f, 0.18f};
        const float base = Luma[0] * c[0] + Luma[1] * c[1] + Luma[2] * c[2];
        for (const float f : {0.4f, 0.86f, 1.0f, 1.14f, 1.6f}) {
            for (const float t : {0.0f, 0.6f, 1.2f, 2.0f}) {
                const auto g = Gains(f, t, c);
                const float lit = Luma[0] * c[0] * g[0] + Luma[1] * c[1] * g[1] + Luma[2] * c[2] * g[2];
                Expect(std::abs(lit - f * base) <= 1e-5f * f * base, "c1 luminance is f times");
                if (t == 0.0f) {
                    Expect(std::abs(g[0] - f) < 1e-5f && std::abs(g[1] - f) < 1e-5f &&
                               std::abs(g[2] - f) < 1e-5f,
                           "c2 no colour shift at T 0");
                } else if (f < 1.0f) {
                    Expect(g[0] > g[1] && g[1] > g[2], "c3 dimmer is redder");
                } else if (f > 1.0f) {
                    Expect(g[0] < g[1] && g[1] < g[2], "c4 brighter is yellower");
                } else {
                    Expect(g[0] == 1.0f && g[1] == 1.0f && g[2] == 1.0f, "c5 f 1 changes nothing");
                }
            }
        }
    }
    // d. flame colours
    {
        Expect(Flame({1.0f, 0.55f, 0.18f}, 1.0f / 64.0f), "d1 orange flame");
        Expect(Flame({1.2f, 0.9f, 0.5f}, 1.0f / 144.0f), "d2 yellow gas lamp");
        Expect(!Flame({1.0f, 1.0f, 1.0f}, 1.0f / 64.0f), "d3 white is no flame");
        Expect(!Flame({0.3f, 0.4f, 1.0f}, 1.0f / 64.0f), "d4 blue is no flame");
        Expect(!Flame({-1.0f, -0.5f, -0.1f}, 1.0f / 64.0f), "d5 a light that darkens is no flame");
        Expect(!Flame({1.0f, 0.55f, 0.18f}, 1.0f / (100.0f * 100.0f)), "d6 too far a reach");
        Expect(!Flame({1.0f, 0.55f, 0.18f}, 0.0f), "d7 no reach");
        Expect(!Flame({1.0f, 0.05f, 0.0f}, 1.0f / 64.0f), "d8 deep red is no flame");
    }
    // e. tracker: a still lamp in two tiles, a lamp the game flickers, a white light
    {
        Params p = ParseParams("1", nullptr, nullptr);
        Tracker t{p};
        const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);
        const auto white = Record(-3.0f, 0.5f, -9.0f, 8.0f, 0.8f, 0.8f, 0.8f);
        std::vector<std::uint32_t> in(48), out(48);
        bool changed_early = false, changed_late = false, tiles_differ = false;
        bool white_changed = false;
        bool game_lamp_changed = false, luma_ok = true, rest_kept = true;
        float least = 2.0f, most = 0.0f;
        for (int f = 0; f < 60 * 6; ++f) {
            const double s = f / 60.0;
            // the game's own flicker: a new colour every frame
            const float g = 0.9f + 0.1f * float(std::sin(f * 0.7));
            const auto game = Record(0.2f, 1.4f, -2.0f, 5.2f, g, 0.5f * g, 0.15f * g);
            std::copy(still.begin(), still.end(), in.begin());
            std::copy(game.begin(), game.end(), in.begin() + 16);
            std::copy(white.begin(), white.end(), in.begin() + 32);
            const bool changed = t.Patch(in.data(), 3, out.data(), Identity.data());
            // the same lamp in another tile, the same frame
            std::vector<std::uint32_t> again(16);
            t.Patch(still.data(), 1, again.data(), Identity.data());
            tiles_differ = tiles_differ || !std::equal(again.begin(), again.end(), out.begin());
            if (s < SteadySeconds) {
                changed_early = changed_early || changed;
            } else if (s > SteadySeconds + 0.5) {
                changed_late = changed_late || changed;
            }
            game_lamp_changed = game_lamp_changed ||
                                !std::equal(out.begin() + 16, out.begin() + 32, in.begin() + 16);
            white_changed = white_changed ||
                            !std::equal(out.begin() + 32, out.begin() + 48, in.begin() + 32);
            const float factor = LumaOf(out.data()) / LumaOf(in.data());
            least = std::min(least, factor);
            most = std::max(most, factor);
            luma_ok = luma_ok && factor >= 1.0f - Swing - 1e-4f && factor <= 1.0f + Swing + 1e-4f;
            for (int w : {0, 1, 2, 3, 7, 8, 15}) {
                rest_kept = rest_kept && out[std::size_t(w)] == in[std::size_t(w)];
            }
            t.EndFrame(s + 1.0 / 60.0, Count);
        }
        Expect(!changed_early, "e1 nothing changes in the first second");
        Expect(changed_late, "e2 a steady flame flickers after it");
        Expect(!tiles_differ, "e3 the same lamp gets the same colour in every tile of a frame");
        Expect(!game_lamp_changed, "e4 a lamp the game changes is left alone");
        Expect(!white_changed, "e5 a white light is left alone");
        Expect(luma_ok, "e6 luminance within the swing");
        Expect(least < 0.95f && most > 1.05f, "e7 the swing is used");
        Expect(rest_kept, "e8 place, reach and the other words are kept");
        // wave step (0.0186 at the full swing) plus the ramp's (Swing / 60 / RampIn)
        Expect(t.LargestStep() <= 0.0186f + Swing / 60.0f + 1e-4f,
               "e9 largest step per frame within the bound");
        const auto states = t.States();
        Expect(states[std::size_t(State::GameChanges)] > 0, "e10 the game's lamp is counted");
        std::printf("tracker: factor %.3f to %.3f, largest step %.4f; lamp frames flickering %llu, "
                    "waiting %llu, the game changes it %llu\n",
                    double(least), double(most), double(t.LargestStep()),
                    (unsigned long long)states[0], (unsigned long long)states[1],
                    (unsigned long long)states[2]);
    }
    // f. a lamp that starts to change loses the flicker within RampOut, a moving lamp keeps its
    // phase (no jump), and nothing flickers without a camera
    {
        Tracker t{ParseParams("1", "0", nullptr)};
        std::array<std::uint32_t, 16> out{};
        float before = 1.0f, jump = 0.0f;
        bool gone = false;
        for (int f = 0; f < 60 * 8; ++f) {
            const double s = f / 60.0;
            const float x = 1.0f + 0.05f * float(f);              // walks 3 m/s
            const float bright = f < 60 * 5 ? 1.0f : 1.0f + 0.02f * float(f % 7); // the game starts
            const auto rec = Record(x, 1.0f, -5.0f, 6.0f, bright, 0.55f * bright, 0.18f * bright);
            t.Patch(rec.data(), 1, out.data(), Identity.data());
            const float factor = LumaOf(out.data()) / LumaOf(rec.data());
            if (f > 60 * 3 && f < 60 * 5) {
                jump = std::max(jump, std::abs(factor - before));
            }
            if (s > 5.0 + RampOut + 2.0 / 60.0) {
                gone = gone || factor == 1.0f;
                Expect(factor == 1.0f, "f1 no flicker once the game changes it");
            }
            before = factor;
            t.EndFrame(s + 1.0 / 60.0, Count);
        }
        Expect(gone, "f2 the flicker went");
        Expect(jump <= 0.0186f + 1e-4f, "f3 a walking lamp keeps its flicker (no jump)");
        Tracker blind{ParseParams("1", nullptr, nullptr)};
        bool changed = false;
        for (int f = 0; f < 60 * 4; ++f) {
            const auto rec = Record(1.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);
            changed = changed || blind.Patch(rec.data(), 1, out.data(), nullptr);
            blind.EndFrame(f / 60.0, Count);
        }
        Expect(!changed, "f4 nothing without a camera");
        // a lamp the game flickers by its reach only (colour kept) is left alone too
        Tracker reach{ParseParams("1", nullptr, nullptr)};
        bool reach_changed = false;
        for (int f = 0; f < 60 * 4; ++f) {
            const float r = 6.0f * (1.0f + 0.03f * float(f % 5));
            const auto rec = Record(1.0f, 1.0f, -5.0f, r, 1.0f, 0.55f, 0.18f);
            reach_changed =
                reach_changed || reach.Patch(rec.data(), 1, out.data(), Identity.data());
            reach.EndFrame(f / 60.0, Count);
        }
        Expect(!reach_changed, "f5 a lamp whose reach the game changes is left alone");
    }
    // g. the fog gets the records the draw was bound to, once, and only for that draw
    {
        Tracker t{ParseParams("1", nullptr, nullptr)};
        const auto rec = Record(1.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);
        const std::uint32_t* patched = nullptr;
        for (int f = 0; f < 60 * 3 && patched == nullptr; ++f) {
            patched = t.PatchDraw(rec.data(), rec.data(), 1, Identity.data());
            t.EndFrame(f / 60.0, Count);
        }
        Expect(patched != nullptr, "g1 patched after the ramp");
        const auto other = Record(9.0f, 1.0f, -5.0f, 6.0f, 1.0f, 0.55f, 0.18f);
        Expect(t.FogRecords(other.data()) == other.data(), "g2 another draw: its own records");
        Expect(t.FogRecords(rec.data()) == patched, "g3 the draw's fog: the patched records");
        Expect(t.FogRecords(rec.data()) == rec.data(), "g4 once");
        t.PatchDraw(rec.data(), rec.data(), 1, Identity.data());
        t.Skipped(Skip::Stream);
        Expect(t.FogRecords(rec.data()) == rec.data(), "g5 a draw left as it was: raw records");
        Expect(!t.TooLarge(), "g6 copies allowed at first");
        t.Skipped(Skip::Large);
        Expect(t.TooLarge(), "g7 a binding too large to copy turns the flicker off");
    }
    // i. the luminance weights are those of the lamp shadow pass's own copy (LampTrack, the r42
    // log and lampWeight's numbers; point_shadow_ray.comp's are checked by the patch script)
    {
        Vulkan::LampTrack track;
        track.Begin(Identity.data());
        const auto rec = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);
        const int at = track.Add(rec.data());
        Expect(at == 0 && std::abs(track.Lamp(std::uint32_t(at)).luma - LumaOf(rec.data())) <=
                              1e-6f * LumaOf(rec.data()),
               "i1 the luminance weights are LampTrack's");
    }
    // h. the periodic line comes every LineFrames frames
    {
        Tracker t{ParseParams("1", nullptr, "1")};
        lines = 0;
        for (std::uint32_t f = 0; f < LineFrames; ++f) {
            t.EndFrame(f / 60.0, Count);
        }
        Expect(lines >= 1, "h1 a line after LineFrames frames");
    }
    // j. bbport (r109a_strength-settings-engine): the two strengths
    {
        using StrengthKnob::ReadEnv;
        const StrengthKnob::Env unset = ReadEnv(nullptr, MaxStrength);
        Expect(!unset.set && !ReadEnv("", MaxStrength).set, "j1 unset or empty: the setting");
        const Strengths d = Resolve(unset, unset, DefaultSteady, DefaultOnGame);
        Expect(d.steady.value == 1.0f && d.on_game.value == 0.0f && !d.steady.from_env &&
                   !d.on_game.from_env && d.On(),
               "j2 defaults: steady lamps 1, lamps the game changes 0, from the settings");
        const Strengths e = Resolve(ReadEnv("0", MaxStrength), ReadEnv("1", MaxStrength), 0.7f, 0.0f);
        Expect(e.steady.value == 0.0f && e.steady.from_env && e.on_game.value == 1.0f &&
                   e.on_game.from_env && e.On(),
               "j3 a set variable wins over the setting, 0 too");
        for (const char* text : {"0", "abc", "-1", "nan", "1", "3", "0.5"}) {
            Expect(ReadEnv(text, MaxStrength).value == ParseParams(text, nullptr, nullptr).strength,
                   "j4 BB_LAMP_FLICKER's text is read by r96's rule");
        }
        const Strengths c = Resolve(unset, unset, 7.0f, -1.0f);
        const Strengths n = Resolve(unset, unset, NAN, INFINITY);
        Expect(c.steady.value == 1.0f && c.on_game.value == 0.0f && n.steady.value == DefaultSteady &&
                   n.on_game.value == DefaultOnGame,
               "j5 settings clamped to 0..1, not finite: the default");
        Expect(!Resolve(unset, unset, 0.0f, 0.0f).On(), "j6 both 0: off");

        // A steady flame and a lamp the game flickers (a new colour every frame), 6 s.
        struct Run {
            std::vector<std::uint32_t> in, out;
            std::array<std::uint64_t, 3> states{};
        };
        const auto run = [](Tracker& t, float steady, float on_game, int on_game_until) {
            Run r;
            std::vector<std::uint32_t> in(32), out(32);
            const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);
            for (int f = 0; f < 60 * 6; ++f) {
                if (steady >= 0.0f) { // below 0: the strengths the tracker was made with
                    t.SetStrengths(steady, f < on_game_until ? on_game : 0.0f);
                }
                const float g = 0.9f + 0.1f * float(std::sin(f * 0.7));
                const auto game = Record(0.2f, 1.4f, -2.0f, 5.2f, g, 0.5f * g, 0.15f * g);
                std::copy(still.begin(), still.end(), in.begin());
                std::copy(game.begin(), game.end(), in.begin() + 16);
                t.Patch(in.data(), 2, out.data(), Identity.data());
                r.in.insert(r.in.end(), in.begin(), in.end());
                r.out.insert(r.out.end(), out.begin(), out.end());
                t.EndFrame(f / 60.0 + 1.0 / 60.0, Count);
            }
            r.states = t.States();
            return r;
        };
        const Params base = ParseParams(nullptr, nullptr, nullptr); // the default colour shift
        Tracker t96{ParseParams("1", nullptr, nullptr)}, t0{base}, t1{base}, thalf{base}, tback{base};
        const Run r96 = run(t96, -1.0f, 0.0f, 0);
        const Run r0 = run(t0, 1.0f, 0.0f, 1 << 30);
        const Run r1 = run(t1, 1.0f, 1.0f, 1 << 30);
        const Run rhalf = run(thalf, 0.5f, 0.0f, 1 << 30);
        const Run rback = run(tback, 1.0f, 1.0f, 60 * 3);
        const std::size_t frames = r0.out.size() / 32;
        bool game_kept = true, game_changed = false, game_in_swing = true, steady_same = true;
        bool back_kept = true, half_ok = true;
        float most = 0.0f;
        for (std::size_t f = 0; f < frames; ++f) {
            const std::size_t at = f * 32;
            game_kept = game_kept && std::equal(r0.out.begin() + at + 16, r0.out.begin() + at + 32,
                                                r0.in.begin() + at + 16);
            game_changed = game_changed || !std::equal(r1.out.begin() + at + 16,
                                                       r1.out.begin() + at + 32, r1.in.begin() + at + 16);
            const float gf = LumaOf(r1.out.data() + at + 16) / LumaOf(r1.in.data() + at + 16);
            game_in_swing = game_in_swing && gf >= 1.0f - Swing - 1e-4f && gf <= 1.0f + Swing + 1e-4f;
            steady_same = steady_same && std::equal(r1.out.begin() + at, r1.out.begin() + at + 16,
                                                    r0.out.begin() + at);
            if (f >= std::size_t(60 * 3)) {
                back_kept = back_kept && std::equal(rback.out.begin() + at + 16,
                                                    rback.out.begin() + at + 32,
                                                    rback.in.begin() + at + 16);
            }
            const float full = LumaOf(r0.out.data() + at) / LumaOf(r0.in.data() + at) - 1.0f;
            const float part = LumaOf(rhalf.out.data() + at) / LumaOf(rhalf.in.data() + at) - 1.0f;
            half_ok = half_ok && std::abs(part - 0.5f * full) <= 2e-5f;
            most = std::max(most, std::abs(full));
        }
        Expect(r0.out == r96.out, "j7 strengths 1 and 0 from the setting: bit for bit r96's path");
        Expect(game_kept, "j8 on-game strength 0: the game's lamp stays bit for bit as the game made it");
        Expect(r0.states[std::size_t(State::GameChanges)] > 0, "j9 and it is counted as left alone");
        Expect(game_changed && game_in_swing, "j10 on-game strength 1: the game's lamp flickers within the swing");
        Expect(r1.states[std::size_t(State::GameChanges)] == 0 && r1.states[std::size_t(State::Flickers)] > 0,
               "j11 and it is counted as flickering, none left alone");
        Expect(steady_same, "j12 the steady lamp does not depend on the on-game strength");
        Expect(half_ok && most > 0.05f, "j13 strength 0.5: half the swing of strength 1");
        Expect(back_kept, "j14 the on-game strength back to 0: the game's lamp left alone at once");
        // Back on after frame ends with both strengths 0 (FrameEnd passes resumed): t0's steady
        // lamp, flickering at full share before, is a new lamp again and waits SteadySeconds.
        bool resumed_kept = true;
        {
            std::vector<std::uint32_t> one(16);
            const auto still = Record(1.0f, 0.5f, -6.0f, 8.0f, 1.0f, 0.55f, 0.18f);
            t0.SetStrengths(1.0f, 0.0f, true); // the frame end that turns it on again,
            t0.EndFrame(6.0 + 2.0, Count);     // 2 s after its last one
            for (int f = 0; f < 30; ++f) {
                t0.SetStrengths(1.0f, 0.0f);
                t0.Patch(still.data(), 1, one.data(), Identity.data());
                resumed_kept = resumed_kept && std::equal(one.begin(), one.end(), still.begin());
                t0.EndFrame(8.0 + (f + 1) / 60.0, Count);
            }
        }
        Expect(resumed_kept && r0.out != r0.in, "j15 back on after both 0: no lamp jumps to its swing");
    }
    if (failures == 0) {
        std::printf("lamp-flicker-test: all checks passed\n");
    }
    return failures == 0 ? 0 : 1;
}
