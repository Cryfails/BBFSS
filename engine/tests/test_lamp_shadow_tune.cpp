// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
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
} // namespace

int main() {
    // Nothing set: the defaults the patch documents.
    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.radius_m == 0.05f && t.rim == 3u);
        assert(t.share == 0.25f && t.clearance_m == 0.35f && t.bias_m == 0.03f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        assert(t.facing_floor == 0.05f && t.near_part == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);
    }
    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_NEAR", "0.75"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.4"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "2"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.radius_m == 0.2f && t.rim == 4u);
        assert(t.share == 0.4f && t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 2u && t.view_gain == 4.0f);
        assert(t.facing_floor == 0.25f && t.near_part == 0.75f);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_NEAR", "0"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_RIM", "-2"},
            {"BB_LAMP_SHADOW_SHARE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
            {"BB_LAMP_SHADOW_SELF", "-1"},
            {"BB_LAMP_SHADOW_VIEW", "-1"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.radius_m == 0.0f && low.rim == 0u);
        assert(low.share == 0.0f && low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        assert(low.facing_floor == 0.0f && low.near_part == 0.05f);
        const LampShadowTune high = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_NEAR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_RIM", "99"},
            {"BB_LAMP_SHADOW_SHARE", "2"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
            {"BB_LAMP_SHADOW_SELF", "1"},
            {"BB_LAMP_SHADOW_VIEW", "9"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.radius_m == 0.3f && high.rim == 4u);
        assert(high.share == 1.0f && high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 3u && high.view_gain == 16.0f);
        assert(high.facing_floor == 1.0f && high.near_part == 1.0f);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_NEAR", "0.5x"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_RIM", "two"},
            {"BB_LAMP_SHADOW_SHARE", "nan"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
            {"BB_LAMP_SHADOW_SELF", "0.12 "},
            {"BB_LAMP_SHADOW_VIEW", "1x"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "-"},
        }});
        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.rim == d.rim && t.share == d.share && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.near_part == d.near_part);
        assert(t.self_m == 0.12f);
    }
    // The words: flags, nine floats, two axes.
    {
        static_assert(LampTuneWordCount == 16);
        const LampShadowTune d;
        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        assert(words[0] == (1u | 3u << 4)); // new weights, 3 rim rays, view 0
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.05f && F(words[3]) == 0.25f);
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
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
        t.rim = 4;
        t.view = 3;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 4 | 3u << 8));
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The rim count and the view cannot leave their fields.
        t.rim = 100;
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (7u << 4 | 3u << 8));
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
    std::puts("lamp shadow tune: ok");
    return 0;
}
