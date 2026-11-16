// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r80_lamp-fog-shafts): the lamp fog shafts' pure parts (lamp_fog_shafts.h): the knob's
// text, the sizes and ray counts of each level, the octahedral map's encode and decode (every
// texel centre of both map sizes comes back to its own texel), the segment's sample point (it
// halves the segment's inverse-square energy) and the share of lit texels with the bias.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string_view>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shafts.h"

using namespace Vulkan::LampFogShafts;

int main() {
    // The knob: exactly "0" to "3"; anything else (also unset and empty) is off.
    assert(Parse(nullptr) == Off && Parse("") == Off);
    assert(Parse("0") == Off && Parse("1") == Medium && Parse("2") == High && Parse("3") == View);
    assert(Parse("4") == Off && Parse("10") == Off && Parse("1x") == Off && Parse(" 1") == Off &&
           Parse("on") == Off && Parse("-1") == Off);
    assert(std::string_view(Name(Off)) == "off" && std::string_view(Name(Medium)) == "on" &&
           std::string_view(Name(7)) == "off");

    // Sizes: 128 texels for 1 and 3, 256 for 2; segments 12 only for 2.
    assert(MapSize(Off) == 0 && MapSize(Medium) == 128 && MapSize(High) == 256 &&
           MapSize(View) == 128 && MapSize(4) == 0);
    assert(Segments(Medium) == 6 && Segments(High) == 12 && Segments(View) == 6);
    assert(MapBytes(Medium) == 2u * 1024 * 1024 && MapBytes(High) == 8u * 1024 * 1024 &&
           MapBytes(Off) == 0);
    assert(MapRays(Medium, 2) == 2u * 16384 && MapRays(High, 16) == 16u * 65536 &&
           MapRays(Medium, 100) == 64u * 16384 && MapRays(Off, 8) == 0);
    assert(SceneMask == 4 && MaxMaps == 64);

    // The blind sphere: 0.35 m, at most half the radius.
    assert(Blind(10.0f) == Clearance && Blind(0.4f) == 0.2f && Blind(0.7f) == Clearance);

    // The octahedral map: +z at the centre, -z at the corners, the axes on the edges' middles.
    {
        const auto c = OctEncode({0.0f, 0.0f, 1.0f});
        assert(c[0] == 0.0f && c[1] == 0.0f);
        const auto x = OctEncode({1.0f, 0.0f, 0.0f});
        assert(x[0] == 1.0f && x[1] == 0.0f);
        const auto y = OctEncode({0.0f, -1.0f, 0.0f});
        assert(y[0] == 0.0f && y[1] == -1.0f);
        const auto back = OctEncode({0.0f, 0.0f, -1.0f});
        assert(std::abs(back[0]) == 1.0f && std::abs(back[1]) == 1.0f);
        const auto down = OctDecode({1.0f, 1.0f});
        assert(std::abs(down[2] + 1.0f) < 1e-6f);
    }
    // Every texel centre of both sizes decodes to a unit direction that encodes into the same
    // texel.
    for (const std::uint32_t size : {128u, 256u}) {
        for (std::uint32_t ty = 0; ty < size; ++ty) {
            for (std::uint32_t tx = 0; tx < size; ++tx) {
                const std::array<float, 2> e{(float(tx) + 0.5f) / float(size) * 2.0f - 1.0f,
                                             (float(ty) + 0.5f) / float(size) * 2.0f - 1.0f};
                const auto d = OctDecode(e);
                assert(std::abs(d[0] * d[0] + d[1] * d[1] + d[2] * d[2] - 1.0f) < 1e-5f);
                const auto back = OctEncode(d);
                const auto bx = std::uint32_t((back[0] * 0.5f + 0.5f) * float(size));
                const auto by = std::uint32_t((back[1] * 0.5f + 0.5f) * float(size));
                assert(bx == tx && by == ty);
            }
        }
    }

    // A segment's sample point lies in the segment and halves its inverse-square energy.
    for (const float along : {-3.0f, 0.5f, 4.0f, 12.0f}) {
        for (const float q : {0.05f, 0.4f, 2.0f}) {
            for (const float t0 : {0.0f, 1.5f, 6.0f}) {
                const float t1 = t0 + 1.25f;
                const float a0 = std::atan((t0 - along) / q), a1 = std::atan((t1 - along) / q);
                const float m = EnergyMiddle(along, q, a0, a1);
                assert(m >= t0 - 1e-3f && m <= t1 + 1e-3f);
                const float am = std::atan((m - along) / q);
                assert(std::abs((am - a0) - (a1 - am)) < 1e-4f);
            }
        }
    }

    // The lit share of four texels; a point up to Bias beyond a texel's free distance is lit.
    assert(Lit({1.0f, 1.0f, 1.0f, 1.0f}, 0.5f) == 1.0f);
    assert(Lit({0.2f, 0.2f, 0.2f, 0.2f}, 0.5f) == 0.0f);
    assert(Lit({0.2f, 1.0f, 0.2f, 1.0f}, 0.5f) == 0.5f);
    assert(Lit({0.5f, 0.5f, 0.5f, 0.5f}, 0.5f + 0.5f * Bias) == 1.0f);
    assert(Lit({0.5f, 0.5f, 0.5f, 0.5f}, 0.5f + 2.0f * Bias) == 0.0f);

    std::printf("lamp fog shafts: all checks passed\n");
    return 0;
}
