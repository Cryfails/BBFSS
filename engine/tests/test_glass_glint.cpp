// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86b_glass-visible): the glass glint's knobs, lamps, gate, push words and shading
// numbers (renderer_vulkan/glass_glint.h). Built by engine/build.sh --test (C++20, -Werror) and by
// the CMake target glass-glint-test.
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/glass_glint.h"

using namespace BbGlassGlint;

static bool Near(float a, float b, float tol) {
    return std::fabs(a - b) <= tol;
}

static LampFog::Light MakeLight(float x, float y, float z, float reach, float r, float g, float b) {
    LampFog::Light light{};
    const std::array<float, 7> words{x, y, z, 1.0f / (reach * reach), r, g, b};
    for (std::size_t i = 0; i < words.size(); ++i) {
        light[i] = std::bit_cast<std::uint32_t>(words[i]);
    }
    return light;
}

int main() {
    // BB_GLASS_GLINT: off unless a strength above 0 or "show"; a strength is put into 0.25 to 4.
    assert(Parse(nullptr, nullptr).strength == 0.0f && !Parse(nullptr, nullptr).unreadable);
    assert(Parse("", nullptr).strength == 0.0f && !Parse("", nullptr).unreadable);
    assert(Parse("0", nullptr).strength == 0.0f && !Parse("0", nullptr).unreadable);
    assert(Parse("-1", nullptr).strength == 0.0f);
    assert(Parse("1", nullptr).strength == 1.0f && !Parse("1", nullptr).show);
    assert(Parse("1 ", nullptr).strength == 1.0f);
    assert(Parse("2.5", nullptr).strength == 2.5f);
    assert(Parse("9", nullptr).strength == MaxStrength);
    assert(Parse("0.1", nullptr).strength == MinStrength);
    assert(Parse("show", nullptr).strength == 1.0f && Parse("show", nullptr).show);
    // bbport (r86j_glint-same-game): the live setting: 0 off, strength on, negative for the test view
    assert(ParseLive(nullptr) == 0.0f && ParseLive("") == 0.0f && ParseLive("0") == 0.0f && ParseLive("x") == 0.0f);
    assert(ParseLive("1") == 1.0f && ParseLive("2.5") == 2.5f && ParseLive("show") == -1.0f);
    assert(ParseLive("9") == MaxStrength && ParseLive("0.1") == MinStrength);
    assert(Parse("shows", nullptr).strength == 0.0f && Parse("shows", nullptr).unreadable);
    assert(Parse("1x", nullptr).strength == 0.0f && Parse("1x", nullptr).unreadable);
    assert(Parse("nan", nullptr).strength == 0.0f && Parse("nan", nullptr).unreadable);
    // BB_GLASS_GLINT_SHARP: 16 to 4096, default 256.
    assert(Parse("1", nullptr).sharp == SharpDefault && SharpDefault == 32);
    assert(Parse("1", "").sharp == 32 && !Parse("1", "").sharp_unreadable);
    assert(Parse("1", "512").sharp == 512);
    assert(Parse("1", "4").sharp == SharpMin && Parse("1", "-3").sharp == SharpMin);
    assert(Parse("1", "100000").sharp == SharpMax);
    assert(Parse("1", "soft").sharp == 32 && Parse("1", "soft").sharp_unreadable);
    assert(Parse("1", "64.5").sharp == 32 && Parse("1", "64.5").sharp_unreadable);

    // The push words: 64 bytes, as glass_glint.comp declares them.
    static_assert(offsetof(Push, proj) == 0 && offsetof(Push, frame) == 16);
    static_assert(offsetof(Push, info) == 32 && offsetof(Push, params) == 48);

    // Shading: the normalisation, Fresnel and one lamp's term.
    // In the game's lamp units (no 1/pi): (n + 8) / 8.
    assert(Near(Normalisation(256.0f), 33.0f, 1e-5f) && Near(Normalisation(16.0f), 3.0f, 1e-6f));
    assert(Near(Fresnel(1.0f), 0.04f, 1e-6f) && Near(Fresnel(0.0f), 1.0f, 1e-6f));
    assert(Fresnel(0.5f) > 0.04f && Fresnel(0.5f) < 0.1f);
    assert(Term(1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f) == 0.0f); // at the reach
    assert(Term(0.5f, 1.0f, 0.0f, 1.0f, 1.0f, 256.0f) == 0.0f); // facing away
    // A mirror direction at half the reach: (1/2)^2 x 1 x 0.04 x 33 = 0.33
    assert(Near(Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f),
                0.25f * 0.04f * Normalisation(256.0f) * Gain, 1e-5f));
    // r86c: the look gain, and the lobe. A half vector 10 degrees off the normal keeps 2 % of the
    // top at 256 (r86b's default: the glints never showed) and 61 % at 32 (the default now).
    assert(Gain == 8.0f && GLASS_GLINT_GAIN == 8.0);
    {
        const float off = std::cos(0.17453293f);
        const float r256 = Term(0.5f, 1.0f, 1.0f, off, 1.0f, 256.0f) / Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f);
        const float r32 = Term(0.5f, 1.0f, 1.0f, off, 1.0f, 32.0f) / Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 32.0f);
        assert(r256 > 0.015f && r256 < 0.03f && r32 > 0.55f && r32 < 0.68f);
        // 20 degrees off the half vector (a lamp 40 degrees off the horizontal of a bottle): nothing
        // at 256 (r86b), a visible glint at 32 for the dream house's torch (3.77 m of 8.5 m, colour
        // 2.49, N.L 0.7): the numbers of the README's r86c table.
        const float far_off = std::cos(0.34906585f);
        const float torch = 2.49f * Term(3.77f, 8.5f, 0.7f, far_off, 0.94f, 256.0f);
        const float torch32 = 2.49f * Term(3.77f, 8.5f, 0.7f, far_off, 0.94f, 32.0f);
        assert(torch < ShadowLevel && torch32 > 4.0f * float(GLASS_GLINT_GLINT_LEVEL)); // 0 and 0.118
        // the top of the torch's lobe at 32: 2.49 x 0.31 x 0.7 x 0.04 x 5 x 8 = 0.86
        const float top = 2.49f * Term(3.77f, 8.5f, 0.7f, 1.0f, 1.0f, 32.0f);
        assert(Near(top, 0.865f, 0.02f));
    }
    // the nearest lamp-to-pane distance as the shader stores it
    assert(DistMinMetres(0) == -1.0f && Near(DistMinMetres(0xFFFFFFFFu - 1234u), 1.234f, 1e-5f));
    assert(Capped(MaxPasses, false) && Capped(0, true) && !Capped(MaxPasses - 1, false));
    // Sharp: 5 degrees off the half vector is far below the peak at 256.
    assert(Term(0.5f, 1.0f, 1.0f, std::cos(0.0873f), 1.0f, 256.0f) <
           0.5f * Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f));
    // The peak of a torch of colour 2 at 1 m of 4 m reach, strength 1, is a visible glint:
    // 2 x 0.5625 x 0.04 x 33 = 1.49, well above the log's glint level and the shadow ray's.
    assert(2.0f * Term(1.0f, 4.0f, 1.0f, 1.0f, 1.0f, 256.0f) > float(GLASS_GLINT_GLINT_LEVEL));
    assert(2.0f * Term(1.0f, 4.0f, 1.0f, 1.0f, 1.0f, 256.0f) > ShadowLevel);

    // The depth test: 2 cm + 0.2 % past the depth.
    assert(InFront(1.0f, 1.0f) && InFront(1.021f, 1.0f) && !InFront(1.023f, 1.0f));
    assert(InFront(9.0f, 10.0f) && InFront(10.039f, 10.0f) && !InFront(10.041f, 10.0f));

    // The quad mode: more than 10 % of the blocks.
    assert(!Quads(0, 100) && !Quads(10, 100) && Quads(11, 100));
    assert(BlocksOf(3840) == 960 && BlocksOf(2160) == 540 && BlocksOf(1918) == 480);
    assert(!Quads(51840, 960 * 540) && Quads(51841, 960 * 540)); // 4K: no 32-bit overflow
    assert(GroupsOf(BlocksOf(1920)) == 60 && GroupsOf(1920) == 240 && GroupsOf(1) == 1);

    // Lamps: LampFog::Select's MaxLamps that show most; behind the camera left out; colour.
    {
        std::vector<LampFog::Light> lights;
        lights.push_back(MakeLight(0.0f, 0.0f, 2.0f, 4.0f, 1.0f, 0.5f, 0.2f));
        lights.push_back(MakeLight(0.0f, 0.0f, -9.0f, 4.0f, 1.0f, 1.0f, 1.0f)); // behind: z + r <= 0
        lights.push_back(MakeLight(1.0f, 0.0f, 3.0f, 2.0f, 64.0f, -1.0f, 32.0f));
        const Picked picked = PickLamps(lights);
        assert(picked.count == 2);
        bool saw_bright = false, saw_torch = false;
        for (std::uint32_t i = 0; i < picked.count; ++i) {
            const Lamp& lamp = picked.lamps[i];
            assert(lamp.view[2] > 0.0f);
            if (Near(lamp.reach, 2.0f, 1e-4f)) {
                saw_bright = true;
                assert(Near(lamp.colour[0], LampColourMost, 1e-4f));
                assert(lamp.colour[1] == 0.0f);
                assert(Near(lamp.colour[2], LampColourMost * 0.5f, 1e-4f));
            } else {
                saw_torch = Near(lamp.reach, 4.0f, 1e-4f) && Near(lamp.colour[0], 1.0f, 1e-6f);
            }
        }
        assert(saw_bright && saw_torch);
        const auto words = Words(picked.lamps[0]);
        assert(words.size() == LampWords && words[3] == picked.lamps[0].reach && words[7] == 0.0f);
        // More than MaxLamps: MaxLamps.
        std::vector<LampFog::Light> many;
        for (int i = 0; i < 20; ++i) {
            many.push_back(MakeLight(float(i) * 0.1f, 0.0f, 1.0f + float(i), 3.0f, 1.0f, 1.0f, 1.0f));
        }
        assert(PickLamps(many).count == MaxLamps);
        assert(PickLamps({}).count == 0);
    }

    // The camera: each entry within 1e-4 of the larger of 1 and its size.
    {
        std::array<float, 12> a{1.0f, 0.0f, 0.0f, 100.0f, 0.0f, 1.0f, 0.0f, -5.0f, 0.0f, 0.0f, 1.0f, 3.0f};
        auto b = a;
        assert(SameCamera(a, b));
        b[0] += 5e-5f;
        b[3] += 5e-3f;
        assert(SameCamera(a, b));
        b[7] += 1e-3f;
        assert(!SameCamera(a, b));
        b = a;
        b[2] = std::nanf("");
        assert(!SameCamera(a, b));
    }

    // The gate: its order.
    {
        const Gate good{.panes = true, .this_frame = true, .same_camera = true, .lamps = true,
                        .lamps_open = false, .shape = true, .passes = 0, .depth_done = false};
        assert(Decide(good) == Skip::None);
        Gate g = good;
        g.passes = MaxPasses - 1;
        assert(Decide(g) == Skip::None);
        g.passes = MaxPasses;
        assert(Decide(g) == Skip::Cap);
        g = good;
        g.depth_done = true;
        assert(Decide(g) == Skip::Cap);
        g.shape = false; // r86c: the cap is asked first
        assert(Decide(g) == Skip::Cap);
        g.depth_done = false;
        assert(Decide(g) == Skip::Shape);
        g.lamps_open = true;
        assert(Decide(g) == Skip::LampsOpen);
        g.lamps = false;
        assert(Decide(g) == Skip::NoLamps);
        g.same_camera = false;
        assert(Decide(g) == Skip::OtherCamera);
        g.this_frame = false;
        assert(Decide(g) == Skip::NoPane);
        g = good;
        g.panes = false;
        assert(Decide(g) == Skip::NoPane);
        assert(Decide(Gate{}) == Skip::NoPane);
    }

    std::printf("glass glint test: all passed\n");
    return 0;
}
