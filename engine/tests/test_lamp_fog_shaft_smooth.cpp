// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r80b_shafts-smooth-visible): the shafts' smoothing and gain knobs, the pushed word and counters
// (lamp_fog_shaft_smooth.h) and a C++ mirror of point_volumetric.comp's ShaftTaps (the bilinear share of
// the four gathered texels): the gather's component order, the weights, and that level 0 is r106c's
// quarter steps.
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
// the pure test links no runtime: the knobs are read from the environment
#define BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE 1
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_smooth.h"

using namespace Vulkan::LampFogShaftSmooth;

namespace {

constexpr int N = 8; // texels a side in the mirror's map

struct Vec4 {
    float x, y, z, w;
};

/// A map of N x N free distances (row j grows with v); clamp to edge.
struct Map {
    float t[N][N];
    float At(int i, int j) const {
        return t[std::clamp(j, 0, N - 1)][std::clamp(i, 0, N - 1)];
    }
};

/// textureGather(map, uv, 0): (i0,j1), (i1,j1), (i1,j0), (i0,j0) with i0 = floor(u N - 0.5).
Vec4 Gather(const Map& m, float u, float v) {
    const int i0 = int(std::floor(u * N - 0.5f)), j0 = int(std::floor(v * N - 0.5f));
    return {m.At(i0, j0 + 1), m.At(i0 + 1, j0 + 1), m.At(i0 + 1, j0), m.At(i0, j0)};
}

float Step(float limit, float value) { return limit <= value ? 1.0f : 0.0f; } // GLSL step(edge, x)

/// ShaftTaps at levels 0 and 1 (no jitter): the shader's statements.
float Taps(const Map& m, float u, float v, float limit, int level) {
    const Vec4 g = Gather(m, u, v);
    const float hx = Step(limit, g.x), hy = Step(limit, g.y), hz = Step(limit, g.z),
                hw = Step(limit, g.w);
    if (level == 0) {
        return 0.25f * (hx + hy + hz + hw);
    }
    const float fx = u * N - 0.5f - std::floor(u * N - 0.5f);
    const float fy = v * N - 0.5f - std::floor(v * N - 0.5f);
    if (hx == hy && hy == hz && hz == hw) {
        return hx; // four equal tests: exactly that answer
    }
    return hx * ((1 - fx) * fy) + hy * (fx * fy) + hz * (fx * (1 - fy)) + hw * ((1 - fx) * (1 - fy));
}

/// The straightforward bilinear filter of the hit grid at (u, v).
float Bilinear(const Map& m, float u, float v, float limit) {
    const float x = u * N - 0.5f, y = v * N - 0.5f;
    const int i0 = int(std::floor(x)), j0 = int(std::floor(y));
    const float fx = x - i0, fy = y - j0;
    const auto h = [&](int i, int j) { return Step(limit, m.At(i, j)); };
    return (1 - fx) * (1 - fy) * h(i0, j0) + fx * (1 - fy) * h(i0 + 1, j0) +
           (1 - fx) * fy * h(i0, j0 + 1) + fx * fy * h(i0 + 1, j0 + 1);
}

} // namespace

int main() {
    // the knobs
    assert(ParseSmooth(nullptr) == 2 && ParseSmooth("") == 2 && ParseSmooth("3") == 2 &&
           ParseSmooth("11") == 2 && ParseSmooth("x") == 2);
    assert(ParseSmooth("0") == 0 && ParseSmooth("1") == 1 && ParseSmooth("2") == 2);
    assert(ParseGain(nullptr) == DefaultGain && ParseGain("") == DefaultGain &&
           ParseGain("abc") == DefaultGain && ParseGain("1.5x") == DefaultGain &&
           ParseGain("nan") == DefaultGain && ParseGain("inf") == DefaultGain);
    assert(ParseGain("1") == 1.0f && ParseGain("2.5") == 2.5f);
    assert(ParseGain("0") == MinGain && ParseGain("100") == MaxGain && ParseGain("-3") == MinGain);
    assert(DefaultGain > 1.0f && DefaultGain < 2.0f);
    // the word: bit 0 as r106c's flag, the rest decodes back
    assert(GainBits(1.0f) == 32u && GainBits(1.35f) == 43u && GainBits(0.0f) == 8u &&
           GainBits(99.0f) == 255u);
    {
        const std::uint32_t w = PackWord(1u, 2u, 1.0f, 0x12345u);
        assert((w & 1u) == 1u);
        assert(((w >> SHAFT_PUSH_SMOOTH_SHIFT) & 3u) == 2u);
        assert(((w >> SHAFT_PUSH_GAIN_SHIFT) & 255u) == 32u);
        assert((w >> SHAFT_PUSH_FRAME_SHIFT) == 0x2345u);
        // smoothing 0, gain 1, frame 0: the shader's old inputs (bit 0 and a gain of 1) and nothing else
        assert(PackWord(0u, 0u, 1.0f, 0u) == (32u << SHAFT_PUSH_GAIN_SHIFT));
        assert((PackWord(7u, 7u, 1.0f, 0u) & 0xFFu) == (1u | (3u << SHAFT_PUSH_SMOOTH_SHIFT)));
    }
    // counters: Pack() counts, says the first values, keeps r106c's flag, counts the frame up
    {
        const std::uint32_t a = Pack(1u);
        const std::uint32_t b = Pack(0u);
        assert((a & 1u) == 1u && (b & 1u) == 0u);
        assert((b >> SHAFT_PUSH_FRAME_SHIFT) == ((a >> SHAFT_PUSH_FRAME_SHIFT) + 1u));
        assert(totals.frames == 2 && totals.level[Smooth()] == 2);
        PrintLine();
        assert(totals.frames == 0 && totals.level[0] + totals.level[1] + totals.level[2] == 0);
    }
    // the gather's order and the bilinear weights: levels 1 equals a plain bilinear filter of the hits,
    // over a map with a diagonal edge, at many (u, v); level 0 is quarter steps
    {
        Map m;
        for (int j = 0; j < N; ++j) {
            for (int i = 0; i < N; ++i) {
                m.t[j][i] = (i + 2 * j < 9) ? 100.0f : 3.0f; // lit (free 100 m) beyond a diagonal edge
            }
        }
        double worst = 0.0;
        int in_between = 0, steps_in_between = 0;
        for (int a = 0; a <= 256; ++a) {
            for (int b = 0; b <= 256; ++b) {
                const float u = (a + 0.37f) / 257.0f, v = (b + 0.61f) / 257.0f;
                const float smooth = Taps(m, u, v, 50.0f, 1), plain = Bilinear(m, u, v, 50.0f);
                worst = std::fmax(worst, std::fabs(smooth - plain));
                assert(smooth >= 0.0f && smooth <= 1.0f);
                const float quarter = Taps(m, u, v, 50.0f, 0);
                assert(std::fabs(quarter * 4.0f - std::round(quarter * 4.0f)) < 1e-6f);
                if (smooth > 0.001f && smooth < 0.999f) {
                    ++in_between;
                    if (std::fabs(smooth * 4.0f - std::round(smooth * 4.0f)) < 1e-3f) {
                        ++steps_in_between;
                    }
                }
            }
        }
        assert(worst < 1e-5);
        // every texel reaches the limit: exactly 1 at any place (not 0.99999994), as the fast march compares
        for (int a = 0; a <= 100; ++a) {
            assert(Taps(m, (a + 0.3f) / 101.0f, (a * 7 % 101 + 0.6f) / 101.0f, 1.0f, 1) == 1.0f);
        }
        // the smoothed edge takes many values between 0 and 1, the old one only the quarters
        assert(in_between > 1000 && steps_in_between * 4 < in_between);
    }
    // a vertical edge along the map: the share rises linearly with u across one texel (left lit)
    {
        Map m;
        for (int j = 0; j < N; ++j) {
            for (int i = 0; i < N; ++i) {
                m.t[j][i] = (i < 4) ? 100.0f : 3.0f;
            }
        }
        float last = 2.0f;
        for (int a = 0; a <= 100; ++a) {
            const float u = (3.0f + a / 100.0f) / N; // from 3/N to 4/N, across the texel centres 3.5/N
            const float s = Taps(m, u, 0.5f, 50.0f, 1);
            assert(s <= last + 1e-6f); // never rises as u goes from lit to dark
            last = s;
        }
        assert(Taps(m, 3.5f / N, 0.5f, 50.0f, 1) == 1.0f && Taps(m, 4.5f / N, 0.5f, 50.0f, 1) == 0.0f);
        assert(std::fabs(Taps(m, 4.0f / N, 0.5f, 50.0f, 1) - 0.5f) < 1e-5f);
    }
    std::printf("lamp fog shaft smooth: ok\n");
    return 0;
}
