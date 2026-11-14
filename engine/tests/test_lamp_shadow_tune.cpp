// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
// bbport (r42_lamp-soft): the area lamp's knobs, the frames of history, and the lamps of a pass
// told apart and followed from one frame to the next (LampTrack).
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"

using namespace Vulkan;

namespace {
using Pair = std::pair<const char*, const char*>;
// The environment of the case being read.
const Pair* env_begin = nullptr;
const Pair* env_end = nullptr;

const char* Get(const char* name) {
    for (const Pair* it = env_begin; it != env_end; ++it) {
        if (std::strcmp(it->first, name) == 0) {
            return it->second;
        }
    }
    return nullptr;
}

template <std::size_t N>
LampShadowTune Read(const std::array<Pair, N>& env) {
    env_begin = env.data();
    env_end = env.data() + N;
    return ReadLampShadowTune(Get);
}

float F(std::uint32_t word) {
    return std::bit_cast<float>(word);
}

bool Near(float a, float b) {
    return std::abs(a - b) <= 1e-6f;
}

// A lamp record as the pass has it: its place in view space, 1 / reach squared, its colour.
std::array<std::uint32_t, 16> Record(float x, float y, float z, float reach, float grey = 1.0f) {
    std::array<std::uint32_t, 16> r{};
    const std::array<float, 7> f{x, y, z, 1.0f / (reach * reach), grey, grey, grey};
    for (std::size_t k = 0; k < f.size(); ++k) {
        r[k] = std::bit_cast<std::uint32_t>(f[k]);
    }
    return r;
}
} // namespace

int main() {
    // Nothing set: the defaults the patch documents.
    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.facing_floor == 0.05f);
        assert(t.radius_m == 0.1f && t.history == 0.9f && t.reject == 0.5f && t.trail_m == 0.08f);
        assert(t.follow && !t.stale && t.carry_m == 2.5f && t.around == 1.6f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);
    }
    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "1.5"},
            {"BB_LAMP_SHADOW_CLAMP", "2.5"},
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_HISTORY", "0.8"},
            {"BB_LAMP_SHADOW_REJECT", "0.7"},
            {"BB_LAMP_SHADOW_TRAIL", "0.5"},
            {"BB_LAMP_SHADOW_FOLLOW", "0"},
            {"BB_LAMP_SHADOW_STALE", "1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "4"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.facing_floor == 0.25f);
        assert(t.radius_m == 0.2f && t.history == 0.8f && t.reject == 0.7f && t.trail_m == 0.5f);
        assert(!t.follow && t.stale && t.carry_m == 1.5f && t.around == 2.5f);
        assert(t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 4u && t.view_gain == 4.0f);
    }
    // r41's rim knobs are gone: set, they change nothing.
    {
        const LampShadowTune t = Read(std::array<Pair, 3>{{
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.9"},
            {"BB_LAMP_SHADOW_NEAR", "1"},
        }});
        const LampShadowTune d;
        assert(LampTuneWords(t, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(t.history == d.history && t.trail_m == d.trail_m && t.follow == d.follow && t.stale == d.stale);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "-1"},
            {"BB_LAMP_SHADOW_CLAMP", "-1"},
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_HISTORY", "-1"},
            {"BB_LAMP_SHADOW_REJECT", "-1"},
            {"BB_LAMP_SHADOW_TRAIL", "-1"},
            {"BB_LAMP_SHADOW_FOLLOW", "-3"},
            {"BB_LAMP_SHADOW_STALE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
            {"BB_LAMP_SHADOW_SELF", "-1"},
            {"BB_LAMP_SHADOW_VIEW", "-1"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.facing_floor == 0.0f);
        assert(low.radius_m == 0.0f && low.history == 0.0f && low.reject == 0.0f && low.trail_m == 0.0f);
        assert(!low.follow && !low.stale && low.carry_m == 0.0f && low.around == 0.0f);
        assert(low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        const LampShadowTune high = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "9"},
            {"BB_LAMP_SHADOW_CLAMP", "9"},
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_HISTORY", "2"},
            {"BB_LAMP_SHADOW_REJECT", "3"},
            {"BB_LAMP_SHADOW_TRAIL", "9"},
            {"BB_LAMP_SHADOW_FOLLOW", "7"},
            {"BB_LAMP_SHADOW_STALE", "9"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
            {"BB_LAMP_SHADOW_SELF", "1"},
            {"BB_LAMP_SHADOW_VIEW", "9"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.facing_floor == 1.0f);
        assert(high.radius_m == 0.5f && high.history == 0.98f && high.reject == 1.0f && high.trail_m == 2.0f);
        assert(high.follow && high.stale && high.carry_m == 5.0f && high.around == 4.0f);
        assert(high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 6u && high.view_gain == 16.0f);
        // A reject that is on is never below the least that leaves a history standing, and
        // the same for the bound by the answers around a pixel.
        const LampShadowTune weak = Read(std::array<Pair, 2>{{{"BB_LAMP_SHADOW_REJECT", "0.1"},
                                                              {"BB_LAMP_SHADOW_CLAMP", "0.1"}}});
        assert(weak.reject == LampRejectLeast && LampRejectLeast * 0.9f > 0.4f);
        assert(weak.around == LampAroundLeast);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "near"},
            {"BB_LAMP_SHADOW_CLAMP", "1.6x"},
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_HISTORY", "0.5x"},
            {"BB_LAMP_SHADOW_REJECT", "nan"},
            {"BB_LAMP_SHADOW_TRAIL", "far"},
            {"BB_LAMP_SHADOW_FOLLOW", "no"},
            {"BB_LAMP_SHADOW_STALE", "yes"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
            {"BB_LAMP_SHADOW_SELF", "0.12 "},
            {"BB_LAMP_SHADOW_VIEW", "1x"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "-"},
        }});
        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.history == d.history && t.reject == d.reject && t.trail_m == d.trail_m);
        assert(t.follow == d.follow && t.stale == d.stale && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.carry_m == d.carry_m && t.around == d.around);
        assert(t.self_m == 0.12f);
    }
    // The frames of history: a frame's share is 1 / (frames + 1).
    {
        LampShadowTune t;
        assert(std::abs(LampHistoryFrames(t) - 9.0f) < 1e-4f);
        t.history = 0.5f;
        assert(Near(LampHistoryFrames(t), 1.0f));
        t.history = 0.98f;
        assert(std::abs(LampHistoryFrames(t) - 49.0f) < 1e-3f);
        t.history = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // this frame's ray alone
        t = {};
        t.radius_m = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // a point lamp keeps no history
        // The last four words of the history block.
        static_assert(LampHistoryTailWords == 4);
        t = {};
        t.trail_m = 0.25f;
        t.carry_m = 1.5f;
        t.around = 2.0f;
        const auto tail = LampHistoryTail(t);
        assert(std::abs(F(tail[0]) - 9.0f) < 1e-4f && F(tail[1]) == 0.25f && F(tail[2]) == 1.5f && F(tail[3]) == 2.0f);
    }
    // A cut: the way back to the camera of the frame before is more than 2 m or about 20 degrees.
    {
        std::array<float, 12> back{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        assert(!LampCameraCut(back.data()));
        back[3] = 0.5f;
        back[11] = -1.5f; // a fast camera: 1.6 m in a frame
        assert(!LampCameraCut(back.data()));
        back[7] = 1.3f; // 2.05 m
        assert(LampCameraCut(back.data()));
        const auto turned = [](float degrees) {
            const float a = degrees * 0.01745329f, c = std::cos(a), s = std::sin(a);
            return std::array<float, 12>{c, 0, s, 0.1f, 0, 1, 0, 0, -s, 0, c, 0};
        };
        assert(!LampCameraCut(turned(5.0f).data()) && !LampCameraCut(turned(-18.0f).data()));
        assert(LampCameraCut(turned(25.0f).data()) && LampCameraCut(turned(180.0f).data()));
        back = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        back[5] = std::nanf("");
        assert(LampCameraCut(back.data()));
    }
    // The words: flags, nine floats, two axes.
    {
        static_assert(LampTuneWordCount == 16);
        const LampShadowTune d;
        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        assert(words[0] == 1u); // new weights, view 0
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
        // The frame counter goes into word 3 as it is, and changes nothing else.
        const auto later = LampTuneWords(d, false, 0.05f, nullptr, 0xC0000077u);
        assert(later[3] == 0xC0000077u);
        for (std::size_t k = 0; k < LampTuneWordCount; ++k) {
            assert(k == 3 || later[k] == words[k]);
        }
        assert(Near(F(words[6]), 0.0025f));
        assert(F(words[8]) == 0.05f && F(words[9]) == 0.5f);
        // No view matrix: the view's own x and y axes.
        assert(F(words[10]) == 1.0f && F(words[11]) == 0.0f && F(words[12]) == 0.0f);
        assert(F(words[13]) == 0.0f && F(words[14]) == 1.0f && F(words[15]) == 0.0f);
        // A view matrix (rows of four; here the camera looks down the world's -y, turned by
        // 30 degrees about it, and stands away from the origin): the world's +x and +y axes as
        // the view sees them are its first two columns, whatever the translation.
        const float c = std::cos(0.5235988f), s = std::sin(0.5235988f);
        const std::array<float, 12> view{c,    0.0f, -s,   5.0f,  s,    0.0f,
                                         c,    -7.0f, 0.0f, -1.0f, 0.0f, 9.0f};
        const auto turned = LampTuneWords(d, false, 0.05f, view.data());
        assert(Near(F(turned[10]), c) && Near(F(turned[11]), s) && Near(F(turned[12]), 0.0f));
        assert(Near(F(turned[13]), 0.0f) && Near(F(turned[14]), 0.0f));
        assert(Near(F(turned[15]), -1.0f));
        for (int k = 0; k < 10; ++k) {
            assert(turned[k] == words[k]); // the axes change nothing else
        }
        // A matrix that is no rotation (scaled, sheared, not finite, empty): the view's own axes.
        std::array<float, 12> bad = view;
        bad[0] = 3.0f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[1] = 0.5f;
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = view;
        bad[4] = std::nanf("");
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        bad = {};
        assert(LampTuneAxes(bad.data()) == LampTuneAxes(nullptr));
        LampShadowTune t;
        t.weights = false;
        t.view = 4;
        t.reject = 0.75f;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8));
        assert(F(other[9]) == 0.75f);
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The view cannot leave its field.
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == 6u << 8);
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
    // one (1 - d^2/r^2)^2 gave 0.5625: a distant lamp counted 2.25 times too much.
    {
        const LampShadowTune d;
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, 1.0f, true, 0.5f), 0.125f)); // luma
        LampShadowTune old;
        old.weights = false;
        assert(Near(LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f), 0.5625f));
        // The old weight knows no facing and no curve switch.
        assert(LampWeight(old, true, 0.05f, 0.25f, -1.0f, true, 1.0f) ==
               LampWeight(old, false, 0.05f, 0.25f, 1.0f, true, 1.0f));
        // Behind the surface, floor 0: nothing with wrap 0, nothing past the wrap otherwise.
        // The whole weight with wrap 1 (no N.L) or where the pass found no normal.
        LampShadowTune hard;
        hard.wrap = 0.0f;
        hard.facing_floor = 0.0f;
        assert(LampWeight(hard, false, 0.05f, 0.25f, -0.2f, true, 1.0f) == 0.0f);
        assert(LampWeight(hard, false, 0.05f, 0.25f, 0.0f, true, 1.0f) == 0.0f);
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, 0.5f, true, 1.0f), 0.125f));
        LampShadowTune gate;
        gate.facing_floor = 0.0f;
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.15f, true, 1.0f) == 0.0f);
        assert(LampWeight(gate, false, 0.05f, 0.25f, -0.1f, true, 1.0f) > 0.0f);
        // The default floor: a lamp behind the surface keeps a twentieth of its weight (so a
        // pixel whose only lamp it is still gets its ray), and still ranks below one in front.
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.0125f));
        assert(Near(LampWeight(d, false, 0.05f, 0.25f, -0.15f, true, 1.0f), 0.0125f));
        assert(LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) > 1e-5f);
        assert(LampWeight(d, false, 0.05f, 0.25f, 0.3f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.25f, -1.0f, true, 1.0f) * 5.0f);
        LampShadowTune none;
        none.wrap = 1.0f;
        assert(Near(LampWeight(none, false, 0.05f, 0.25f, -1.0f, true, 1.0f), 0.25f));
        assert(Near(LampWeight(hard, false, 0.05f, 0.25f, -1.0f, false, 1.0f), 0.25f));
        // The inverse-square curve: 1 / (x^2 + core^2) - 1 / (1 + core^2), 0 at the radius.
        const float core2 = 0.05f * 0.05f;
        assert(Near(LampWeight(d, true, 0.05f, 0.25f, 1.0f, true, 1.0f),
                    1.0f / (0.25f + core2) - 1.0f / (1.0f + core2)));
        assert(Near(LampWeight(d, true, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(std::isfinite(LampWeight(d, true, 0.0f, 0.0f, 1.0f, true, 1.0f)));
        // Both curves end at the radius and fall with distance.
        assert(Near(LampWeight(d, false, 0.05f, 1.0f, 1.0f, true, 1.0f), 0.0f));
        assert(LampWeight(d, false, 0.05f, 0.04f, 1.0f, true, 1.0f) >
               LampWeight(d, false, 0.05f, 0.64f, 1.0f, true, 1.0f));
    }
    // bbport (r42_lamp-soft): the lamps of a pass, told apart and followed.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        // The camera of the second frame stands 2 m along x: world = view + (2, 0, 0).
        constexpr std::array<float, 12> Moved{1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0};
        LampTrack track;
        // Frame 1: lamp A (listed for three tiles), lamp B, and a record with no reach.
        const auto a1 = Record(1.0f, 2.0f, 3.0f, 6.0f, 0.5f), b1 = Record(5.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        track.Begin(Same.data());
        assert(track.Add(a1.data()) == 0 && track.Add(b1.data()) == 1 && track.Add(a1.data()) == 0);
        assert(track.Add(a1.data()) == 0 && track.Count() == 2);
        std::array<std::uint32_t, 16> none{};
        assert(track.Add(none.data()) == -1 && track.Count() == 2);
        assert(track.Lamp(0).records == 3 && track.Lamp(1).records == 1);
        assert(Near(track.Lamp(0).radius, 6.0f) && Near(track.Lamp(0).luma, 0.5f));
        assert(Near(track.Lamp(1).away, std::sqrt(26.0f)));
        track.Follow(); // no frame before: nothing is followed, nothing shifts
        assert(!track.Lamp(0).followed && track.Shift(0, Same.data()) == (std::array<float, 3>{}));
        // The brightest first.
        assert(track.Strongest() == (std::array<int, 4>{1, 0, -1, -1}));
        track.End(true);
        // Frame 2: A went (0.1, 0, 0.05) in the world, B stands; the camera moved, so both
        // records hold other numbers. C is new; D stands where B does with twice its reach.
        const auto a2 = Record(1.1f - 2.0f, 2.0f, 3.05f, 6.0f, 0.5f), b2 = Record(3.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        const auto c2 = Record(9.0f, 0.0f, 0.0f, 4.0f), d2 = Record(3.0f, 1.0f, 0.01f, 8.0f);
        track.Begin(Moved.data());
        assert(track.Add(a2.data()) == 0 && track.Add(b2.data()) == 1 && track.Add(c2.data()) == 2);
        assert(track.Add(d2.data()) == 3);
        track.Follow();
        assert(track.Lamp(0).followed && track.Lamp(1).followed);
        assert(!track.Lamp(2).followed && !track.Lamp(3).followed);
        assert(Near(track.Lamp(0).world[0], 1.1f) && Near(track.Lamp(0).moved[0], 0.1f));
        assert(Near(track.Lamp(0).moved[1], 0.0f) && Near(track.Lamp(0).moved[2], 0.05f));
        assert(track.Lamp(1).moved == (std::array<float, 3>{})); // it stands
        // The shift is the lamp's motion turned into the view of the frame before (here a
        // quarter turn about y), whatever that camera's place.
        constexpr std::array<float, 12> Turned{0, 0, -1, 7, 0, 1, 0, 8, 1, 0, 0, 9};
        const auto shift = track.Shift(0, Turned.data());
        assert(Near(shift[0], -0.05f) && Near(shift[1], 0.0f) && Near(shift[2], 0.1f));
        assert(track.Shift(1, Turned.data()) == (std::array<float, 3>{}));
        // The step is the length of the motion, with or without a view to turn it into. A
        // lamp that was looked for in the frame before and not found has no history: Lost.
        assert(Near(track.Step(0), std::sqrt(0.1f * 0.1f + 0.05f * 0.05f)));
        assert(track.Step(1) == 0.0f && track.Step(2) == LampTrack::Lost && track.Step(-1) == 0.0f);
        assert(track.Step(3) == LampTrack::Lost);
        // What a followed lamp did since the steps were last cleared.
        assert(track.Lamp(0).steps == 1 && Near(track.Lamp(0).step_most, track.Step(0)));
        assert(track.Lamp(1).steps == 1 && track.Lamp(1).step_sum == 0.0f && track.Lamp(2).steps == 0);
        assert(track.Shift(-1, Turned.data()) == (std::array<float, 3>{}));
        assert(track.Shift(0, nullptr) == (std::array<float, 3>{}));
        track.End(true);
        // Frame 3: two lamps near where A was: the nearer one is A, the other is new. A lamp
        // further than Reach from every lamp of the frame before is new.
        const auto a3 = Record(1.2f - 2.0f, 2.0f, 3.05f, 6.0f), e3 = Record(1.4f - 2.0f, 2.0f, 3.05f, 6.0f);
        const auto b3 = Record(3.0f + LampTrack::Reach + 0.1f, 1.0f, 0.0f, 4.0f);
        track.Begin(Moved.data());
        assert(track.Add(e3.data()) == 0 && track.Add(a3.data()) == 1 && track.Add(b3.data()) == 2);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Lamp(1).followed && !track.Lamp(2).followed);
        assert(Near(track.Lamp(1).moved[0], 0.1f));
        assert(track.Lamp(1).steps == 2 && Near(track.Lamp(1).step_sum, track.Lamp(1).step_most + 0.1f));
        track.ClearSteps();
        assert(track.Lamp(1).steps == 0 && track.Lamp(1).step_sum == 0.0f && track.Lamp(1).step_most == 0.0f);
        track.End(false); // the pass kept no history: the next frame follows nothing
        track.Begin(Moved.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f); // not looked for: not Lost
        track.End(true);
        // No camera: the lamps are listed in view space and not followed, on this frame or the next.
        track.Begin(nullptr);
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && Near(track.Lamp(0).world[0], 1.2f - 2.0f));
        track.End(true);
        track.Begin(Same.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed);
        track.End(true);
        // More lamps than it tells apart: the first Most keep their numbers, the rest have none.
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most + 6; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f, k == 5 ? 9.0f : 1.0f);
            assert(track.Add(r.data()) == (k < LampTrack::Most ? int(k) : -1));
        }
        const auto again = Record(7.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(again.data()) == 7 && track.Count() == LampTrack::Most);
        // Strongest: none of them is within Near of the camera.
        assert(track.Strongest() == (std::array<int, 4>{-1, -1, -1, -1}));
        track.End(false);
        // Strongest: by luminance, the nearer first among equals, four at most.
        track.Begin(Same.data());
        const std::array<std::array<std::uint32_t, 16>, 6> some{
            Record(0, 0, 5, 3, 1.0f), Record(0, 0, 2, 3, 1.0f), Record(0, 0, 9, 3, 4.0f),
            Record(0, 0, 14, 3, 0.2f), Record(0, 0, 16, 3, 50.0f), Record(1, 0, 3, 3, 0.5f)};
        for (const auto& r : some) {
            track.Add(r.data());
        }
        assert(track.Strongest() == (std::array<int, 4>{2, 1, 0, 5}));
        track.End(false);
        // Two lights at one place with different reach or colour are two lamps (a torch made
        // of two); the same seven words are one.
        track.Begin(Same.data());
        const auto wide = Record(1, 2, 3, 6.0f), small = Record(1, 2, 3, 1.5f), red = Record(1, 2, 3, 6.0f, 0.3f);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Add(red.data()) == 2);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Count() == 3);
        assert(Near(LampTrack::Away(wide.data()), std::sqrt(14.0f)));
        track.End(false);
    }
    // Two lamps a few centimetres apart that move together (a hand torch made of two lights):
    // each is found again as itself, from the first moving frame on, and both have the step.
    // Before, each took the nearest place of the frame before: one of them the other's, with
    // a wrong step or one against the motion, and the other none.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<std::array<float, 2>, 5> cases{{{0.05f, 0.067f}, {0.05f, 0.03f}, {0.1f, 0.067f},
                                                         {0.02f, 0.01f}, {0.3f, 0.067f}}};
        for (const auto& [gap, step] : cases) {
            for (const bool second_first : {false, true}) {
                LampTrack track;
                for (int frame = 0; frame < 4; ++frame) {
                    const float x = step * float(frame);
                    const auto a = Record(x, 1.0f, 2.0f, 5.0f), b = Record(x + gap, 1.0f, 2.0f, 5.0f);
                    track.Begin(Same.data());
                    const int ia = second_first ? (track.Add(b.data()), track.Add(a.data())) : track.Add(a.data());
                    const int ib = track.Add(b.data());
                    track.Follow();
                    if (frame > 0) {
                        assert(track.Lamp(std::uint32_t(ia)).followed && track.Lamp(std::uint32_t(ib)).followed);
                        assert(std::abs(track.Step(ia) - step) < 1e-4f && std::abs(track.Step(ib) - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ia)).moved[0] - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ib)).moved[0] - step) < 1e-4f);
                    }
                    track.End(true);
                }
            }
        }
        // A flame whose reach flickers (5 m, 6.6 m) while it is carried is one lamp all the same.
        LampTrack track;
        for (int frame = 0; frame < 4; ++frame) {
            const auto a = Record(0.05f * float(frame), 1.0f, 2.0f, frame & 1 ? 6.6f : 5.0f);
            track.Begin(Same.data());
            track.Add(a.data());
            track.Follow();
            assert(frame == 0 || (track.Lamp(0).followed && std::abs(track.Step(0) - 0.05f) < 1e-4f));
            track.End(true);
        }
        // A lamp that jumps further than Reach is new, and what the history holds under it is
        // not its own: Lost. Unless the frame before had as many lamps as are told apart (it
        // may have been one more of them): then nothing is known, and the step is 0.
        const auto jumped = Record(0.15f + LampTrack::Reach + 0.2f, 1.0f, 2.0f, 5.0f);
        track.Begin(Same.data());
        track.Add(jumped.data());
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == LampTrack::Lost);
        track.End(true);
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f);
            track.Add(r.data());
        }
        track.End(true);
        track.Begin(Same.data());
        const auto stranger = Record(-5.0f, 0.0f, 20.0f, 3.0f), known = Record(3.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(stranger.data()) == 0 && track.Add(known.data()) == 1);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f);
        assert(track.Lamp(1).followed && track.Step(1) == 0.0f);
        track.End(false);
    }
    std::puts("lamp shadow tune: ok");
    return 0;
}
