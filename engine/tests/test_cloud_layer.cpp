// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): checks of gpu/shadps4/video_core/renderer_vulkan/cloud_layer_params.h,
// the cloud layer's knobs, slab, cloud field and Params block (built and run by engine/build.sh --test
// and the CMake target cloud-layer-test).
//  a. The knobs: BB_VOLUMETRIC_CLOUDS starts with 1; every other knob falls back to its default when
//     missing or not a number and is clamped; BB_VOLUMETRIC_CLOUDS_SHOW starts with 1.
//  b. CoverEdges: the shadows' edges at cover 0.5, moved by (0.5 - cover) CoverShift, always apart.
//  c. The slab: the reference height and sigma.
//  d. SlabRange: a camera below, inside and above the slab, rays up, down and level.
//  e. The noise twin: the corner hash, the value noise (reference values worked out with the same
//     arithmetic in python), its period, FieldN with and without offsets and with octaves faded.
//  f. The shadow and the layer read the same density: for ground points g under a light, the cover
//     of the cloud over g (CloudOver) at the layer's plane coordinate is the cloud shadows' own cover
//     at g, and the shadow's Light(n) is 1 - depth x that cover; the density is 0 outside the slab
//     and above a column's top.
//  g. The Params block: its slots, the light without a valid sun, the knobs in their places.
//  h. IsSky, LightShare, and the counters' shares.
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

#include "gpu/shadps4/video_core/renderer_vulkan/cloud_layer_params.h"

using namespace CloudLayerParams;

namespace {

bool Near(double a, double b, double eps) {
    return std::fabs(a - b) <= eps;
}

std::array<float, 3> Unit(float x, float y, float z) {
    const float n = std::sqrt(x * x + y * y + z * z);
    return {x / n, y / n, z / n};
}

} // namespace

int main() {
    // a.
    {
        const Knobs k = MakeKnobs(nullptr, nullptr, nullptr, nullptr, nullptr);
        assert(!k.on && !k.show && k.cover == DefaultCover && k.density == DefaultDensity &&
               k.height == DefaultHeight && k.thick == DefaultThick && k.steps == DefaultSteps &&
               k.sky_z == DefaultSkyZ);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr).on);
        assert(MakeKnobs("1x", nullptr, nullptr, nullptr, nullptr).on);
        for (const char* off : {"", "0", "2", "yes", " 1"}) {
            assert(!MakeKnobs(off, nullptr, nullptr, nullptr, nullptr).on);
        }
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, "1").show);
        assert(!MakeKnobs("1", nullptr, nullptr, nullptr, "0").show);
        const Knobs c = MakeKnobs("1", "2", "100", "10", nullptr, "5", "1", "999999");
        assert(c.cover == 1.0f && c.density == MaxDensity && c.height == MinHeight &&
               c.thick == MinThick && c.steps == MinSteps && c.sky_z == MaxSkyZ);
        const Knobs d = MakeKnobs("1", "-1", "0", "99999", nullptr, "99999", "999", "-5");
        assert(d.cover == 0.0f && d.density == MinDensity && d.height == MaxHeight &&
               d.thick == MaxThick && d.steps == MaxSteps && d.sky_z == 0.0f);
        const Knobs e = MakeKnobs("1", "abc", "nan", "", nullptr, "inf", "x", "y");
        assert(e.cover == DefaultCover && e.density == DefaultDensity && e.height == DefaultHeight &&
               e.thick == DefaultThick && e.steps == DefaultSteps && e.sky_z == DefaultSkyZ);
        const Knobs f = MakeKnobs("1", "0.8", "2.5", "900", nullptr, "400", "20", "3000");
        assert(Near(f.cover, 0.8, 1e-6) && Near(f.density, 2.5, 1e-6) && f.height == 900.0f &&
               f.thick == 400.0f && f.steps == 20 && f.sky_z == 3000.0f);
    }
    // b.
    {
        const Edges same = CoverEdges(CloudShadows::Low, CloudShadows::High, DefaultCover);
        assert(same.low == CloudShadows::Low && same.high == CloudShadows::High);
        const Edges more = CoverEdges(CloudShadows::Low, CloudShadows::High, 1.0f);
        assert(Near(more.low, CloudShadows::Low - 0.5 * CoverShift, 1e-6) &&
               Near(more.high, CloudShadows::High - 0.5 * CoverShift, 1e-6));
        const Edges less = CoverEdges(CloudShadows::Low, CloudShadows::High, 0.0f);
        assert(Near(less.low, CloudShadows::Low + 0.5 * CoverShift, 1e-6));
        float last = 1.0f;
        for (int i = 0; i <= 20; ++i) {
            const Edges e = CoverEdges(CloudShadows::Low, CloudShadows::High, float(i) / 20.0f);
            assert(e.low >= 0.02f && e.high <= 0.99f && e.high >= e.low + 0.02f - 1e-6f);
            assert(e.low <= last); // more cover: lower edges
            last = e.low;
        }
        // a wide input is held apart too
        const Edges tight = CoverEdges(0.9f, 0.9f, 0.0f);
        assert(tight.high >= tight.low + 0.02f - 1e-6f && tight.high <= 0.99f);
    }
    // c.
    {
        const Knobs k = MakeKnobs("1", nullptr, "2", "600", nullptr, "200");
        const Slab s = MakeSlab(k);
        assert(s.base == 600.0f && s.thick == 200.0f && s.Top() == 800.0f);
        assert(Near(s.reference, 600.0 + RefFraction * 200.0, 1e-4));
        assert(Near(s.sigma, SigmaScale / 200.0 * 2.0, 1e-7));
        // a full column straight up: optical depth about 5.6 x density at the defaults (r119d)
        const Slab d = MakeSlab(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr));
        assert(Near(d.sigma * d.thick, SigmaScale, 1e-4));
    }
    // d.
    {
        float t0 = -1.0f, t1 = -1.0f;
        // below the slab, looking up at 45 degrees
        assert(SlabRange(100.0f, 0.7071f, 700.0f, 1000.0f, &t0, &t1));
        assert(Near(t0, 600.0 / 0.7071, 0.5) && Near(t1, 900.0 / 0.7071, 0.5));
        // below, looking down or level: no slab
        assert(!SlabRange(100.0f, -0.5f, 700.0f, 1000.0f, &t0, &t1));
        assert(!SlabRange(100.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1));
        // inside, looking up: from the camera to the top; looking down: from the camera to the base
        assert(SlabRange(800.0f, 1.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f &&
               Near(t1, 200.0, 1e-3));
        assert(SlabRange(800.0f, -1.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f &&
               Near(t1, 100.0, 1e-3));
        // inside, level: the whole stretch (up to MaxT); above, level: none
        assert(SlabRange(800.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f && t1 == MaxT);
        assert(!SlabRange(1200.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1));
        // above the slab, looking down: it is met at the top
        assert(SlabRange(1200.0f, -1.0f, 700.0f, 1000.0f, &t0, &t1) && Near(t0, 200.0, 1e-3) &&
               Near(t1, 500.0, 1e-3));
        // above, looking up: no slab
        assert(!SlabRange(1200.0f, 0.5f, 700.0f, 1000.0f, &t0, &t1));
    }
    // e.
    {
        assert(Corner(0u) * 16777216.0f == 130277.0f);
        assert(Corner(1u) * 16777216.0f == 10440790.0f);
        assert(Corner(0x0102u) * 16777216.0f == 11616340.0f);
        assert(Corner(0x030201u) * 16777216.0f == 16643622.0f);
        assert(Corner(0xFF00FFu) * 16777216.0f == 4582979.0f);
        assert(Near(Value({3.3f, 0.0f, 7.8f}), 0.41997828, 1e-4));
        assert(Near(Value({-1.25f, 0.0f, -40.5f}), 0.29839898, 1e-4));
        assert(Near(Value({0.0f, 0.0f, 0.0f}), 0.0077651143, 1e-6));
        // the lattice repeats every FOG_NOISE_PERIOD cells
        assert(Near(Value({3.3f + 256.0f, 0.0f, 7.8f}), Value({3.3f, 0.0f, 7.8f}), 1e-4));
        assert(Near(Value({3.3f, 0.0f, 7.8f - 256.0f}), Value({3.3f, 0.0f, 7.8f}), 1e-4));
        for (int i = 0; i < 200; ++i) {
            const float v = Value({0.37f * float(i), 0.11f * float(i), -0.53f * float(i)});
            assert(v >= 0.0f && v < 1.0f);
        }
        const Offsets zero{};
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, zero), 0.50065323, 1e-4));
        assert(Near(FieldN({-3.2f, 0.0f, 5.1f}, zero), 0.76081447, 1e-4));
        const Offsets moved{{{1.5f, 0.25f, 2.0f}, {0.5f, 0.5f, 0.5f}, {10.0f, 0.0f, 3.0f}}};
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, moved), 0.46092598, 1e-4));
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.5f, 0.0f}), 0.46809860, 1e-4));
        // an octave left out (lod 0) is the same as a missing term, and a faded one lies between
        const float full = FieldN({1.7f, 0.0f, 2.9f}, moved);
        const float none = FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.0f, 0.0f});
        const float half = FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.5f, 0.5f});
        assert(std::fabs(half - none) <= std::fabs(full - none) + 1e-6f);
    }
    // f.
    {
        const CloudShadows::Knobs shadow = CloudShadows::MakeKnobs("1", nullptr, nullptr, "90");
        const std::array<float, 3> light = Unit(0.6f, 0.5f, -0.3f);
        CloudShadows::State state;
        for (int i = 0; i < 80; ++i) {
            state.Advance(shadow, true, 90.0f, true, light, 0.1);
        }
        const Knobs knobs = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        Field f;
        f.offsets = OffsetsOf(state.Offsets());
        f.inv_size = 1.0f / shadow.scale;
        f.edges = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), knobs.cover);
        f.slope = CloudShadows::Slope(light);
        f.slab = MakeSlab(knobs);
        assert(f.edges.low == CloudShadows::Low && f.edges.high == CloudShadows::High);
        int clear = 0, partial = 0, full = 0, dense = 0, total = 0;
        for (int i = -10; i <= 10; ++i) {
            for (int j = -10; j <= 10; ++j) {
                const std::array<float, 3> g{37.0f * float(i) + 3.0f, 2.0f * float((i * j) % 7),
                                             41.0f * float(j) - 5.0f};
                const std::array<float, 3> over = CloudOver(f, g);
                assert(over[1] == f.slab.reference);
                // the cloud over g, read at the layer's plane, is the shadow's cover at g
                const float layer = Cover(f, LayerPlane(f, over));
                const float shade = ShadowCover(f, g);
                assert(Near(layer, shade, 2e-3));
                // the shadow's Light is 1 - depth x that cover (CloudShadows::Light at the same n)
                const std::array<float, 2> q = CloudShadows::Plane(g, f.slope);
                const float n = FieldN({q[0] * f.inv_size, 0.0f, q[1] * f.inv_size}, f.offsets);
                const float depth = shadow.Depth();
                assert(Near(CloudShadows::Light(n, depth, shadow.LowEdge(), shadow.HighEdge()),
                            1.0 - depth * shade, 1e-5));
                // the density where that cloud is: 0 where there is none, else sigma c h
                float v = -1.0f;
                const float dens = Density(f, over, &v);
                if (layer <= 0.0f) {
                    assert(dens == 0.0f);
                    ++clear;
                } else {
                    assert(v >= 0.0f && v < 1.0f + 1e-6f);
                    assert(dens >= 0.0f && dens <= f.slab.sigma * layer + 1e-6f);
                    if (layer >= 1.0f) {
                        ++full;
                    } else {
                        ++partial;
                    }
                    if (dens > 0.0f) {
                        ++dense;
                    }
                }
                ++total;
            }
        }
        // the field has all three kinds of ground, and the reference plane holds cloud
        assert(total == 441 && clear > 40 && partial > 20 && full > 10 && dense > 40);
        // outside the slab: nothing, at any plane coordinate
        float v = 0.0f;
        assert(Density(f, {0.0f, f.slab.base - 1.0f, 0.0f}, &v) == 0.0f);
        assert(Density(f, {0.0f, f.slab.Top() + 1.0f, 0.0f}, &v) == 0.0f);
        assert(Density(f, {0.0f, f.slab.base, 0.0f}, &v) == 0.0f);
        // a thinner cloud is lower: for a small cover the top (v = 1) is under the slab's top
        std::array<float, 3> p{0.0f, 0.0f, 0.0f};
        int low_tops = 0;
        for (int i = 0; i < 300; ++i) {
            p = {11.0f * float(i), f.slab.base + 0.9f * f.slab.thick, 7.0f * float(i)};
            if (Cover(f, LayerPlane(f, p)) < 0.4f) {
                float vv = 0.0f;
                assert(Density(f, p, &vv) == 0.0f); // 0.9 of the slab is above a 0.35 + 0.65 c top
                ++low_tops;
            }
        }
        assert(low_tops > 30);
    }
    // g.
    {
        VolumetricFogNoise::Drift drift; // bbport (r119c_clouds-gaps): the layer's own offsets
        const Knobs knobs = MakeKnobs("1", "0.7", "1.5", "800", nullptr, "250", "16", "4000", "1200", "3");
        const std::array<float, 12> rows{1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7};
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);
        const std::array<float, 2> slope = CloudShadows::Slope(light);
        const Params p = MakeParams(rows, proj, drift, knobs, light, true, slope, {0.25f, -0.5f});
        assert(p.row0[3] == 5.0f && p.row1[3] == 6.0f && p.row2[3] == 7.0f && p.row0[0] == 1.0f &&
               p.row1[1] == 1.0f && p.row2[2] == 1.0f);
        assert(p.proj == proj);
        assert(Near(p.off0[3], 1.0 / 1200.0, 1e-7));
        const Edges e = CoverEdges(LayerLow, LayerHigh, 0.7f);
        assert(p.off1[3] == e.low && p.off2[3] == e.high);
        assert(p.off0[0] == 0.0f && p.off1[1] == 0.0f && p.off2[2] == 0.0f); // a fresh Drift
        assert(Near(p.light[1], 0.8, 1e-6) && Near(p.light[2], 0.6, 1e-6) && p.light[3] == 1.0f);
        assert(p.slab[0] == 800.0f && p.slab[1] == 250.0f && Near(p.slab[2], 800.0 + 0.35 * 250.0, 1e-3) &&
               Near(p.slab[3], SigmaScale / 250.0 * 1.5, 1e-6));
        assert(Near(p.plane[0], slope[0], 1e-7) && Near(p.plane[1], slope[1], 1e-7) &&
               p.plane[2] == 0.25f && p.plane[3] == -0.5f);
        assert(p.look[0] == 16.0f && p.look[1] == OpacityCap && p.look[2] == HorizonEdges(knobs.horizon)[0] &&
               p.look[3] == HorizonEdges(knobs.horizon)[1]); // bbport (r119i): the default horizon is no longer the old edges
        assert(p.dist[0] == FadeFrom && p.dist[1] == FadeTo && p.dist[2] == 4000.0f);
        assert(p.tone[0] == Ambient && p.tone[1] == LightGain &&
               Near(p.tone[2], double(Desaturate) * (1.0 - double(knobs.tint)), 1e-6) && p.tone[3] == Forward); // bbport (r119i): tint default 0.7
        // no valid sun: the light points up with no share (only the sky's ambient lights the cloud)
        const Params dark = MakeParams(rows, proj, drift, knobs, {1.0f, 0.0f, 0.0f}, false,
                                       {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(dark.light[0] == 0.0f && dark.light[1] == 1.0f && dark.light[2] == 0.0f &&
               dark.light[3] == 0.0f);
        // the push block and the layout's numbers
        assert(sizeof(Push) == 16 && CounterWords == CL_WORDS && CL_WORD_STEPS < CL_WORDS);
    }
    // h.
    {
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        assert(IsSky(1.0f, proj, 0.0f) && !IsSky(0.9999f, proj, 0.0f));
        assert(IsSky(1.0f, proj, 500.0f));
        // proj z scale 1, offset 0.1: z = 0.1 / (depth - 1): depth 0.99999 is 10000 m, 0.9 is -1 m
        assert(Near(ViewZ(0.99999f, 1.0f, 0.1f), 0.1 / (0.99999f - 1.0f), 1.0));
        assert(IsSky(0.99999f, proj, 5.0f) == (ViewZ(0.99999f, 1.0f, 0.1f) > 5.0f));
        assert(!IsSky(0.5f, proj, 50.0f));
        assert(LightShare({0.0f, 0.5f, 0.0f}, false) == 0.0f);
        assert(LightShare({0.0f, -0.1f, 0.0f}, true) == 0.0f);
        assert(LightShare({0.0f, 0.3f, 0.0f}, true) == 1.0f && LightShare({0.0f, 0.9f, 0.0f}, true) == 1.0f);
        float last = -1.0f;
        for (int i = 0; i <= 40; ++i) {
            const float s = LightShare({0.0f, -0.1f + 0.0125f * float(i), 0.0f}, true);
            assert(s >= last && s >= 0.0f && s <= 1.0f);
            last = s;
        }
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_TOTAL] = 1000;
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_HIT] = 300;
        frame[CL_WORD_COVERED] = 200;
        frame[CL_WORD_OPACITY] = 400 * 64; // a mean opacity of 0.25
        frame[CL_WORD_STEPS] = 3600;
        t.Add(frame);
        t.Add(frame);
        const Shares s = SharesOf(t);
        assert(t.frames == 2 && Near(s.sky, 0.4, 1e-9) && Near(s.covered, 0.5, 1e-9) &&
               Near(s.opacity, 0.25, 1e-9) && Near(s.steps, 12.0, 1e-9));
        const Shares none = SharesOf(Totals{});
        assert(none.sky == 0.0 && none.covered == 0.0 && none.opacity == 0.0 && none.steps == 0.0);
    }
    // i. (r119b) the game's sky dome is drawn a little short of depth 1: the default counts it as sky.
    {
        // the log's projection: Camera motion: projection x 1.4280 y 2.5386 z 1.000017 -0.050068
        const std::array<float, 4> proj{1.4280f, 2.5386f, 1.000017f, -0.050068f};
        const auto depth_of = [&](float z) { return proj[2] + proj[3] / z; };
        assert(DefaultSkyZ == 500.0f && MakeKnobs("1", nullptr, nullptr, nullptr, nullptr).sky_z == 500.0f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "0").sky_z == 0.0f);
        for (const float z : {600.0f, 1500.0f, 1900.0f, 2800.0f}) { // the dome 1500 to 1900 m, the far plane 2945 m
            assert(depth_of(z) < 1.0f);
            assert(IsSky(depth_of(z), proj, DefaultSkyZ));
            assert(!IsSky(depth_of(z), proj, 0.0f)); // r119's rule: depth 1 only, so the dome never counted
        }
        for (const float z : {0.5f, 30.0f, 200.0f, 400.0f}) {
            assert(!IsSky(depth_of(z), proj, DefaultSkyZ));
        }
        assert(IsSky(1.0f, proj, DefaultSkyZ) && IsSky(1.0f, proj, 0.0f));
        // the probe's bands: the edges and the words
        assert(DepthBands == 7 && DepthEdges[0] == 1500.0f && DepthEdges[1] == 1000.0f &&
               DepthEdges[2] == 500.0f && DepthEdges[3] == 250.0f && DepthEdges[4] == 100.0f);
        assert(CL_WORD_Z_SKY > CL_WORD_STEPS && CL_WORD_Z_LAST < CL_WORDS);
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_TOTAL] = 1000;
        frame[CL_WORD_Z_SKY] = 100;
        frame[CL_WORD_Z_SKY + 1] = 300;
        frame[CL_WORD_Z_LAST] = 600;
        t.Add(frame);
        t.Add(frame);
        const std::array<double, DepthBands> shares = DepthShares(t);
        assert(Near(shares[0], 0.1, 1e-9) && Near(shares[1], 0.3, 1e-9) && shares[2] == 0.0 &&
               Near(shares[DepthBands - 1], 0.6, 1e-9));
        assert(DepthShares(Totals{})[0] == 0.0);
    }
    // j. (r119c) the layer's own size, speed, edges and drift: separate masses with gaps, not a blanket.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.size == DefaultSize && d.size == 800.0f && d.speed == DefaultSpeed && d.speed == 1.5f);
        const Knobs c = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "1", "999");
        assert(c.size == MinSize && c.speed == MaxSpeed);
        const Knobs e = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "99999", "0");
        assert(e.size == MaxSize && e.speed == MinSpeed);
        const Knobs f = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "abc", "nan");
        assert(f.size == DefaultSize && f.speed == DefaultSpeed);
        // the edges at cover 0.5 are the layer's own (not the shadows')
        const Edges same = CoverEdges(LayerLow, LayerHigh, DefaultCover);
        assert(same.low == LayerLow && same.high == LayerHigh && LayerHigh > LayerLow);
        // the lod: a 100 m step is one cell of a 100 m size (octaves 1 and 2 gone: the blanket), 0.125 cell of 800 m
        assert(Near(Lod(1.0f, 0), 0.6, 1e-6) && Lod(1.0f, 1) == 0.0f && Lod(1.0f, 2) == 0.0f);
        assert(Lod(100.0f / DefaultSize, 0) == 1.0f && Lod(100.0f / DefaultSize, 1) == 1.0f &&
               Near(Lod(100.0f / DefaultSize, 2), 1.6 - 0.125 / 0.19, 1e-4));
        // the field at the default size and edges (zero offsets), 3600 points over 24 km: python port of the
        // march's noise gives (r119d edges 0.51 / 0.57) clear 1848, in between 520, full 1232 of the 3600 (r119c
        // edges 0.49 / 0.65: 1659, 1270, 671)
        const Offsets zero{};
        int clear = 0, partial = 0, full = 0;
        for (int i = 0; i < 60; ++i) {
            for (int j = 0; j < 60; ++j) {
                const std::array<float, 3> x{float(i) * 397.0f / DefaultSize, 0.0f, float(j) * 311.0f / DefaultSize};
                const float cover = Smoothstep(LayerLow, LayerHigh, FieldN(x, zero));
                if (cover <= 0.0f) {
                    ++clear;
                } else if (cover >= 0.99f) {
                    ++full;
                } else {
                    ++partial;
                }
            }
        }
        assert(clear + partial + full == 3600);
        assert(clear > 1500 && clear < 2200 && full > 900 && full < 1550 && partial > 300 && partial < 760);
        // the drift: the wind's cloud speed times the knob moves the layer's offsets, the morph does not scale
        const Knobs fast = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "3"); // r119i: twice the default 1.5
        assert(LayerWind(0.0f, 6.0f, fast)[1] == LayerWind(0.0f, 6.0f, d)[1]);
        assert(Near(LayerWind(0.0f, 6.0f, d)[0], 9.0, 1e-4) && Near(LayerWind(0.0f, 6.0f, fast)[0], 18.0, 1e-4));
        VolumetricFogNoise::Drift one, two;
        one.Advance(true, 10.0, LayerWind(0.0f, 6.0f, d), d.size);
        one.Advance(true, 10.5, LayerWind(0.0f, 6.0f, d), d.size);
        two.Advance(true, 10.0, LayerWind(0.0f, 6.0f, fast), fast.size);
        two.Advance(true, 10.5, LayerWind(0.0f, 6.0f, fast), fast.size);
        const std::array<float, 3> a = one.Cells(0), b = two.Cells(0);
        assert(a[0] > 0.0f && a[2] > 0.0f && Near(b[0], 2.0 * a[0], 1e-5) && Near(b[2], 2.0 * a[2], 1e-5));
        assert(Near(a[0] / a[2], VolumetricFogNoise::YawCos[0] / VolumetricFogNoise::YawSin[0], 1e-3));
        // the visible share of the counters
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_VISIBLE] = 100;
        t.Add(frame);
        assert(Near(SharesOf(t).visible, 0.25, 1e-9) && SharesOf(Totals{}).visible == 0.0);
        assert(CL_WORD_VISIBLE == 13u && CL_VISIBLE_ALPHA == 0.25);
    }
    // k. (r119d_clouds-contrast) a narrow edge band, dense cores, a drift that shows in 2 s, the contrast counters.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(LayerHigh > LayerLow && LayerHigh - LayerLow < 0.07f);
        assert(Near(Smoothstep(LayerLow, LayerHigh, 0.5f * (LayerLow + LayerHigh)), 0.5, 1e-5));
        assert(Smoothstep(LayerLow, LayerHigh, LayerLow) == 0.0f && Smoothstep(LayerLow, LayerHigh, LayerHigh) == 1.0f);
        assert(OpacityCap > 0.9f && SigmaScale >= 8.0f && LightGain > Ambient && Forward >= 3.0f);
        // the speed: the wind's cloud speed held between the floor and the ceiling, times the knob
        assert(LayerSpeed(0.0f, d) == DriftFloor * d.speed && LayerSpeed(1.6f, d) == DriftFloor * d.speed);
        assert(Near(LayerSpeed(6.0f, d), 9.0, 1e-4) && LayerSpeed(15.0f, d) == DriftCeil * d.speed); // bbport (r119i): speed 1.5
        assert(LayerSpeed(std::nanf(""), d) == DriftFloor * d.speed);
        // at the slowest default a cloud 1000 m away moves more than 0.4 degrees in 2 s (r119i: speed 1.5, was 1.5 degrees at 6)
        assert(LayerSpeed(0.0f, d) * 2.0f / 1000.0f * 57.29578f > 0.4f);
        // the counters
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_VISIBLE] = 100;
        frame[CL_WORD_DARK] = 30;
        frame[CL_WORD_BRIGHT] = 50;
        t.Add(frame);
        const Shares s = SharesOf(t);
        assert(Near(s.dark, 0.3, 1e-9) && Near(s.bright, 0.5, 1e-9));
        assert(SharesOf(Totals{}).dark == 0.0 && SharesOf(Totals{}).bright == 0.0);
        assert(CL_WORD_DARK == 14u && CL_WORD_BRIGHT == 15u && CL_WORD_BRIGHT < CL_WORDS);
    }
    // l. (r119e_clouds-real-sky) the contrast knob and the live parsers: clamped, defaulted, in the Params block.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.contrast == DefaultContrast && DefaultContrast == 1.25f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "1.6").contrast == 1.6f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "99").contrast == MaxContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "0").contrast == MinContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "abc").contrast == DefaultContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "nan").contrast == DefaultContrast);
        assert(ParseContrast(nullptr) == DefaultContrast && ParseContrast("2") == 2.0f && ParseContrast("") == DefaultContrast);
        assert(ParseSpeed(nullptr) == DefaultSpeed && ParseSpeed("24") == 24.0f && ParseSpeed("0") == MinSpeed &&
               ParseSpeed("999") == MaxSpeed && ParseSpeed("x") == DefaultSpeed);
        // the live reads give what the start's read gives
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "12").speed == ParseSpeed("12"));
        // the two scales: 1 is the r119d look; 1.25 is undersides x0.80 and rims x1.12
        assert(ShadeScale(1.0f) == 1.0f && LitScale(1.0f) == 1.0f);
        assert(Near(ShadeScale(DefaultContrast), 0.8, 1e-6) && Near(LitScale(DefaultContrast), 1.118034, 1e-5));
        assert(ShadeScale(2.0f) < ShadeScale(DefaultContrast) && LitScale(2.0f) > LitScale(DefaultContrast));
        // the Params block carries it in dist.w
        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        VolumetricFogNoise::Drift drift;
        const Params p = MakeParams(rows, proj, drift, d, {0.0f, 1.0f, 0.0f}, true, {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(p.dist[3] == DefaultContrast && p.dist[2] == DefaultSkyZ);
        const Knobs hot = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "2");
        const Params q = MakeParams(rows, proj, drift, hot, {0.0f, 1.0f, 0.0f}, true, {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(q.dist[3] == 2.0f);
        // the frozen speed (BB_VOLUMETRIC_CLOUDS_SPEED=0.25) is a small fraction of the default's drift
        Knobs slow = d;
        slow.speed = MinSpeed;
        assert(LayerSpeed(6.0f, slow) < LayerSpeed(6.0f, d) / 5.0f && LayerSpeed(6.0f, slow) > 0.0f);
    }
    // m. (r119f_clouds-open-sky) BB_VOLUMETRIC_CLOUDS_REPORT: whole numbers 30 to 3000, else 0 (the defaults).
    {
        assert(ReportFramesFrom(nullptr) == 0u && ReportFramesFrom("") == 0u);
        assert(ReportFramesFrom("30") == 30u && ReportFramesFrom("90") == 90u && ReportFramesFrom("3000") == 3000u);
        assert(ReportFramesFrom("29") == 0u && ReportFramesFrom("3001") == 0u && ReportFramesFrom("0") == 0u);
        assert(ReportFramesFrom("9x") == 0u && ReportFramesFrom("-90") == 0u && ReportFramesFrom("1.5") == 0u);
        assert(ReportFramesFrom("99999999999999999999") == 0u && ReportFramesFrom(" 90") == 0u);
        assert(ReportFramesLeast == 30u && ReportFramesMost == 3000u && FramesFirst < FramesPeriod);
    }
    // n. (r119g_clouds-smear-and-cover) the cover, the tint and the smear fix: parsing, defaults, the Params slots.
    {
        assert(ParseCover(nullptr) == DefaultCover && ParseCover("0.3") == 0.3f && ParseCover("9") == 1.0f &&
               ParseCover("-1") == 0.0f && ParseCover("abc") == DefaultCover);
        assert(ParseTint(nullptr) == DefaultTint && ParseTint("0.5") == 0.5f && ParseTint("7") == 1.0f &&
               ParseTint("x") == DefaultTint && DefaultTint == 0.7f);
        assert(ParseSmear(nullptr) && ParseSmear("") && ParseSmear("1") && ParseSmear("x") && !ParseSmear("0"));
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.tint == DefaultTint && d.smear);
        const Knobs t = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
                                  nullptr, "0.4", "0");
        assert(t.tint == 0.4f && !t.smear);
        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, -1.0f, 1.0f, 0.1f};
        const VolumetricFogNoise::Drift drift;
        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);
        const std::array<float, 2> slope = CloudShadows::Slope(light);
        const Params on = MakeParams(rows, proj, drift, d, light, true, slope, {0.0f, 0.0f});
        assert(on.extra[0] == DefaultTint && on.extra[1] == float(LightTaps) && on.extra[2] == ShadeBase &&
               on.extra[3] == HorizonGlow && Near(on.tone[2], double(Desaturate) * (1.0 - double(DefaultTint)), 1e-6));
        const Params off = MakeParams(rows, proj, drift, t, light, true, slope, {0.0f, 0.0f});
        assert(off.extra[0] == 0.4f && off.extra[1] == 1.0f && off.extra[2] == OldShadeBase && off.extra[3] == 0.0f);
        assert(Near(off.tone[2], double(Desaturate) * 0.6, 1e-6)); // a tint of 0.4 leaves 60% of the desaturation
        const Knobs full = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
                                     nullptr, "1");
        assert(MakeParams(rows, proj, drift, full, light, true, slope, {0.0f, 0.0f}).tone[2] == 0.0f);
        assert(LightTaps == 2 && ShadeBase > OldShadeBase && OldShadeBase == 0.25f && HorizonGlow > 0.0f);
    }
    // o. (r119h_clouds-freeze-sheet) the freeze and mark parsers, HeldSpeed against LayerSpeed, and a zero wind holding the
    //    drift's offsets exactly (clock kept, so no jump when it moves again).
    {
        assert(!ParseFreeze(nullptr) && !ParseFreeze("") && !ParseFreeze("0") && !ParseFreeze("x") && ParseFreeze("1"));
        assert(ParseMark(nullptr) == 0u && ParseMark("") == 0u && ParseMark("0") == 0u && ParseMark("7") == 7u &&
               ParseMark("999999") == 999999u);
        assert(ParseMark("1000000") == 0u && ParseMark("-1") == 0u && ParseMark("1.5") == 0u && ParseMark("9x") == 0u &&
               ParseMark(" 3") == 0u && ParseMark("99999999999999999999") == 0u);
        assert(MarkFrames > 0u && MarkSkipFrames > 0u && MarkTimeoutFrames > MarkSkipFrames + MarkFrames);
        assert(HeldSpeed(1.0f) == DriftFloor && HeldSpeed(100.0f) == DriftCeil && HeldSpeed(5.0f) == 5.0f &&
               HeldSpeed(std::nanf("")) == DriftFloor);
        const Knobs base = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        Knobs slow = base;
        slow.speed = MinSpeed;
        for (const float c : {1.0f, 3.0f, 6.0f, 20.0f, std::nanf("")}) {
            assert(LayerSpeed(c, base) == HeldSpeed(c) * base.speed && LayerSpeed(c, slow) == HeldSpeed(c) * MinSpeed);
        }
        // the speed knob's floor leaves a drift (6 x 0.25 = 1.5 m/s) and the morph does not scale with it: no speed stops the field
        assert(Near(double(LayerSpeed(6.0f, slow)), 1.5, 1e-6));
        const std::array<float, 3> moving = LayerWind(214.0f, 6.0f, slow);
        assert(moving[1] > 0.0f && moving[1] == LayerWind(214.0f, 6.0f, base)[1]);
        VolumetricFogNoise::Drift d;
        d.Advance(true, 10.0, moving, slow.size);
        d.Advance(true, 10.5, moving, slow.size);
        d.Advance(true, 11.0, moving, slow.size);
        std::array<std::array<float, 3>, 3> held{};
        for (std::size_t k = 0; k < 3; ++k) held[k] = d.Cells(k);
        bool moved = false;
        for (std::size_t k = 0; k < 3; ++k) moved = moved || held[k][1] != 0.0f;
        assert(moved);
        const std::array<float, 3> zero{0.0f, 0.0f, 0.0f};
        for (const double t : {11.5, 12.0, 14.0, 20.0}) { // a zero wind, including a long gap: nothing moves, bit for bit
            d.Advance(true, t, zero, slow.size);
            for (std::size_t k = 0; k < 3; ++k) {
                const std::array<float, 3> now = d.Cells(k);
                assert(now[0] == held[k][0] && now[1] == held[k][1] && now[2] == held[k][2]);
            }
        }
        // moving again takes one step of the time since the last call (the clock was kept), not the whole pause
        d.Advance(true, 20.5, moving, slow.size);
        VolumetricFogNoise::Drift once;
        once.Advance(true, 20.0, moving, slow.size);
        once.Advance(true, 20.5, moving, slow.size);
        for (std::size_t k = 0; k < 3; ++k) {
            for (std::size_t i = 0; i < 3; ++i) {
                const double gone = VolumetricFogNoise::WrapCells(double(d.Cells(k)[i]) - double(held[k][i]));
                const double want = double(once.Cells(k)[i]);
                const double gap = std::fabs(gone - want);
                assert(gap < 2e-3 || std::fabs(gap - VolumetricFogNoise::Period) < 2e-3);
            }
        }
    }
    // p. (r119i_clouds-behind-painted-sky) the painted fade, the colour cap and the horizon: parsing, defaults, the Params slots, the counter.
    {
        assert(ParsePainted(nullptr) == DefaultPainted && ParsePainted("0") == 0.0f && ParsePainted("0.5") == 0.5f &&
               ParsePainted("9") == 1.0f && ParsePainted("-1") == 0.0f && ParsePainted("x") == DefaultPainted);
        assert(ParseGlow(nullptr) == DefaultGlow && ParseGlow("0") == 0.0f && ParseGlow("99") == MaxGlow &&
               ParseGlow("x") == DefaultGlow);
        assert(ParseHorizon(nullptr) == DefaultHorizon && ParseHorizon("0") == 0.0f && ParseHorizon("99") == MaxHorizon &&
               ParseHorizon("-5") == 0.0f && ParseHorizon("x") == DefaultHorizon);
        // the horizon: 0 (or no number) is the old edges; 30 degrees is the slope sin 30 = 0.5, the fade starting at sin 12 degrees
        const std::array<float, 2> old_edges = HorizonEdges(0.0f);
        assert(old_edges[0] == HorizonFrom && old_edges[1] == HorizonTo && HorizonEdges(std::nanf(""))[0] == HorizonFrom);
        const std::array<float, 2> edges = HorizonEdges(DefaultHorizon);
        assert(DefaultHorizon == 30.0f && Near(edges[1], 0.5, 1e-5) &&
               Near(edges[0], std::sin(12.0 * 3.14159265358979 / 180.0), 1e-5) && edges[0] < edges[1]);
        assert(HorizonEdges(60.0f)[1] > HorizonEdges(30.0f)[1] && HorizonEdges(10.0f)[1] < HorizonEdges(30.0f)[1]);
        // the speed: the default is 1.5 (3.75 to 12 m/s from the held wind speed)
        assert(DefaultSpeed == 1.5f && Near(HeldSpeed(0.0f) * DefaultSpeed, 3.75, 1e-6) && Near(HeldSpeed(99.0f) * DefaultSpeed, 12.0, 1e-6));
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.painted == DefaultPainted && d.horizon == DefaultHorizon && d.glow == DefaultGlow && d.tint == 0.7f);
        const Knobs off = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
                                    nullptr, nullptr, nullptr, "0", "0", "0");
        assert(off.painted == 0.0f && off.horizon == 0.0f && off.glow == 0.0f);
        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, -1.0f, 1.0f, 0.1f};
        const VolumetricFogNoise::Drift drift;
        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);
        const std::array<float, 2> slope = CloudShadows::Slope(light);
        const Params on = MakeParams(rows, proj, drift, d, light, true, slope, {0.0f, 0.0f});
        assert(on.paint[0] == DefaultPainted && on.paint[1] == RingNear && on.paint[2] == RingFar && on.paint[3] == DefaultGlow);
        assert(on.look[2] == edges[0] && on.look[3] == edges[1]);
        // everything off gives the r119h look in the block: no painted fade, no cap, the old horizon edges
        const Params none = MakeParams(rows, proj, drift, off, light, true, slope, {0.0f, 0.0f});
        assert(none.paint[0] == 0.0f && none.paint[3] == 0.0f && none.look[2] == HorizonFrom && none.look[3] == HorizonTo);
        assert(RingNear < RingFar && RingNear >= 4.0f);
        // the counter: the painted share is of the marched (hit) sky pixels
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_HIT] = 200;
        frame[CL_WORD_PAINTED] = 50;
        t.Add(frame);
        assert(Near(SharesOf(t).painted, 0.25, 1e-9) && SharesOf(Totals{}).painted == 0.0);
        assert(CL_WORD_PAINTED == 16u && CL_WORDS == 17u && CL_WORD_PAINTED < CL_WORDS);
    }
    std::puts("cloud layer: ok");
    return 0;
}
