// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' ray budget (lamp_fog_shaft_cap.h): the
// knob, the budget and maps a frame, the table words, the view pyramid test, and the planner: few
// lamps are all rebuilt every frame (as r80), many never take more than the frame's maps and are
// all mapped within a few frames, still lamps then rebuild 4 a frame each in turn, a moving torch
// is rebuilt every frame, shared centres take one map, a lamp over budget fades out and back in,
// no camera shadows nothing, a lamp out of view wants no map, a turning camera rebuilds nothing,
// standing lamps that seem to move keep their maps and wait behind a new lamp (review fix).
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <map>
#include <set>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_cap.h"

using namespace Vulkan::LampFogShaftCap;

namespace {

constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
// (x, y, depth, 1) to (x, y, 1): the view pyramid |x| <= z, |y| <= z.
constexpr std::array<float, 16> Projection{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1};
constexpr float Dt = 1.0f / 60.0f;

LampFog::Light Light(float x, float y, float z, float radius, float colour = 1.0f) {
    LampFog::Light light{};
    light[0] = std::bit_cast<std::uint32_t>(x);
    light[1] = std::bit_cast<std::uint32_t>(y);
    light[2] = std::bit_cast<std::uint32_t>(z);
    light[3] = std::bit_cast<std::uint32_t>(1.0f / (radius * radius));
    for (std::size_t i = 4; i < 7; ++i) {
        light[i] = std::bit_cast<std::uint32_t>(colour);
    }
    return light;
}

LampFog::Camera Camera(const std::array<float, 12>& view_to_world, bool valid = true) {
    LampFog::Camera camera;
    camera.view_to_world = view_to_world;
    camera.valid = valid;
    return camera;
}

std::uint32_t Strength(std::uint32_t entry) {
    return entry >> 16;
}

} // namespace

int main() {
    // The knob: digits only, at most 9; anything else (and 0) is the default.
    assert(ParseRays(nullptr) == 0 && ParseRays("") == 0 && ParseRays("0") == 0);
    assert(ParseRays("131072") == 131072 && ParseRays("12x") == 0 && ParseRays("-5") == 0);
    assert(ParseRays("999999999") == 999999999 && ParseRays("1000000000") == 0);
    assert(RaysPerMap(1) == 16384 && RaysPerMap(2) == 65536 && RaysPerMap(3) == 16384 &&
           RaysPerMap(0) == 0);
    assert(Budget(0, 1) == 131072 && Budget(0, 2) == 524288 && Budget(0, 3) == 131072);
    assert(Budget(5, 1) == RaysMin && Budget(999999999, 1) == RaysMax && Budget(200000, 2) == 200000);
    assert(MapsPerFrame(131072, 1) == 8 && MapsPerFrame(524288, 2) == 8 &&
           MapsPerFrame(16384, 2) == 1 && MapsPerFrame(200000, 1) == 12);
    assert(MapsPerFrame(RaysMax, 1) == 64 && MapsPerFrame(RaysMax, 2) == 64 &&
           MapsPerFrame(131072, 0) == 0);
    // The rays a frame are at most the maps a frame times one map's rays: never more than the
    // budget, except one map when the budget is below a map.
    for (const std::uint32_t level : {1u, 2u, 3u}) {
        for (const std::uint64_t parsed : {0ull, 1ull, 16384ull, 100000ull, 131072ull, 999999ull,
                                           4194304ull, 999999999ull}) {
            const std::uint64_t budget = Budget(parsed, level);
            const std::uint64_t worst = MapsPerFrame(budget, level) * RaysPerMap(level);
            assert(worst <= std::max(budget, RaysPerMap(level)) && worst <= 64 * RaysPerMap(level));
        }
    }
    assert(sizeof(MapPush) == 64 && TableBytes == 592 * 4);

    // A record's word: the layer, the strength as 16 bits; 0 when unshadowed.
    assert(Entry(3, 1.0f) == (3u | (65535u << 16)) && Entry(3, 0.0f) == 0);
    assert(Entry(5, 0.5f) == (5u | (32768u << 16)) && Entry(7, 2.0f) == (7u | (65535u << 16)) &&
           Entry(7, -1.0f) == 0);

    // The view pyramid.
    assert(InView(Projection, {0, 0, 5}, 1) && !InView(Projection, {0, 0, -5}, 1));
    assert(!InView(Projection, {10, 0, 5}, 1) && InView(Projection, {5.5f, 0, 5}, 1) &&
           !InView(Projection, {0, 9, 5}, 1));
    assert(InView(Projection, {0, 0, 0.2f}, 1)); // the camera inside the sphere
    {
        const std::array<float, 16> none{};
        assert(InView(none, {100, 0, -5}, 1)); // no projection: no culling
    }

    // The table: the rotation, a word per record, the jobs.
    {
        Plan plan;
        plan.entries = {Entry(2, 1.0f), 0u};
        plan.jobs.push_back({{1.0f, 2.0f, 3.0f}, 4.5f, 2u});
        const auto table = MakeTable(plan, Identity);
        assert(table.size() == SHAFT_TABLE_WORDS);
        assert(std::bit_cast<float>(table[SHAFT_TABLE_TO_WORLD + 10]) == 1.0f);
        assert(table[SHAFT_TABLE_RECORDS] == Entry(2, 1.0f) && table[SHAFT_TABLE_RECORDS + 1] == 0);
        assert(std::bit_cast<float>(table[SHAFT_TABLE_JOBS + 2]) == 3.0f &&
               std::bit_cast<float>(table[SHAFT_TABLE_JOBS + 3]) == 4.5f &&
               table[SHAFT_TABLE_JOBS + 4] == 2u && table[SHAFT_TABLE_JOBS + 5] == 0u);
        Totals totals;
        totals.Add(plan, 16384);
        assert(totals.frames == 1 && totals.rays == 16384 && totals.rays_most == 16384);
    }

    // 3 still lamps: every map every frame, as r80, all at full strength.
    {
        Planner planner;
        const std::vector<LampFog::Light> lamps{Light(-2, 0, 8, 4), Light(0, 1, 10, 5),
                                                Light(2, 0, 12, 3)};
        for (int f = 0; f < 10; ++f) {
            const Plan plan = planner.Run(lamps, Camera(Identity), Projection, Dt, 8);
            assert(plan.jobs.size() == 3 && plan.fresh == 3 && plan.over == 0 && plan.reused == 0);
            std::set<std::uint32_t> layers;
            for (const std::uint32_t entry : plan.entries) {
                assert(Strength(entry) == 65535);
                layers.insert(entry & SHAFT_LAYER_MASK);
            }
            assert(layers.size() == 3);
        }
    }

    // 40 still lamps, 8 maps a frame: never more than 8 maps; all mapped by frame 5, the late ones
    // fading in; then 4 a frame, every lamp within 10 frames.
    std::vector<LampFog::Light> street;
    for (int i = 0; i < 40; ++i) {
        street.push_back(Light(float(i % 8) - 3.5f, float(i / 8) - 2.0f, 15.0f + float(i), 3));
    }
    {
        Planner planner;
        std::map<std::uint32_t, int> last_built;
        for (int f = 1; f <= 120; ++f) {
            const Plan plan = planner.Run(street, Camera(Identity), Projection, Dt, 8);
            assert(plan.jobs.size() <= 8);
            for (const Job& job : plan.jobs) {
                last_built[job.layer] = f;
            }
            std::size_t full = 0, fading = 0, some = 0;
            for (const std::uint32_t entry : plan.entries) {
                full += Strength(entry) == 65535 ? 1 : 0;
                fading += Strength(entry) > 0 && Strength(entry) < 65535 ? 1 : 0;
                some += entry != 0 ? 1 : 0;
            }
            if (f == 1) {
                assert(plan.fresh == 8 && plan.over == 32 && some == 8);
            }
            if (f == 2) {
                assert(plan.fresh == 8 && plan.over == 24 && full == 8 && fading == 8);
            }
            if (f == 5) {
                assert(plan.over == 0 && some == 40);
            }
            if (f >= 20) {
                assert(plan.over == 0 && plan.jobs.size() == 4 && plan.fresh == 4 &&
                       plan.reused == 36 && full == 40);
                for (const auto& layer_built : last_built) {
                    assert(f - layer_built.second <= 10);
                }
            }
        }
        assert(last_built.size() == 40);
    }

    // A moving torch near the camera and the 40 lamps: the torch is rebuilt every frame.
    {
        Planner planner;
        for (int f = 1; f <= 60; ++f) {
            std::vector<LampFog::Light> lights{Light(0.5f * std::cos(0.3f * float(f)), -0.5f,
                                                     1.5f + 0.5f * std::sin(0.3f * float(f)), 6,
                                                     2.0f)};
            lights.insert(lights.end(), street.begin(), street.end());
            const Plan plan = planner.Run(lights, Camera(Identity), Projection, Dt, 8);
            const std::uint32_t torch = plan.entries[0] & SHAFT_LAYER_MASK;
            bool rebuilt = false;
            for (const Job& job : plan.jobs) {
                rebuilt = rebuilt || job.layer == torch;
            }
            assert(rebuilt && Strength(plan.entries[0]) == 65535 && plan.jobs.size() <= 8);
        }
    }

    // The torch's two spheres share one map with the larger reach.
    {
        Planner planner;
        const std::vector<LampFog::Light> torch{Light(0, -0.5f, 1, 4, 2.0f),
                                                Light(0, -0.5f, 1, 6, 2.0f)};
        const Plan plan = planner.Run(torch, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.size() == 1 && std::abs(plan.jobs[0].reach - 6.0f) < 1e-4f &&
               plan.entries[0] == plan.entries[1] && plan.entries[0] != 0);
    }

    // Over budget: a lamp that loses its map fades out (no pop), then back in.
    {
        Planner planner;
        const auto pair = [](int f) {
            return std::vector<LampFog::Light>{Light(0.3f * float(f), 0, 6, 4, 2.0f),
                                               Light(-0.3f * float(f), 0, 9, 4, 1.0f)};
        };
        for (int f = 1; f < 4; ++f) {
            const Plan plan = planner.Run(pair(f), Camera(Identity), Projection, Dt, 2);
            assert(plan.jobs.size() == 2 && Strength(plan.entries[0]) == 65535 &&
                   Strength(plan.entries[1]) == 65535);
        }
        std::uint32_t previous = 65535;
        Plan plan;
        for (int f = 4; f < 24; ++f) {
            plan = planner.Run(pair(f), Camera(Identity), Projection, Dt, 1);
            assert(plan.jobs.size() == 1 && plan.over == 1 && Strength(plan.entries[0]) == 65535);
            const std::uint32_t strength = Strength(plan.entries[1]);
            if (f == 4) {
                assert(strength > 60000 && strength < 65535);
            }
            assert(strength <= previous);
            previous = strength;
        }
        assert(plan.entries[1] == 0 && plan.reused == 0);
        plan = planner.Run(pair(24), Camera(Identity), Projection, Dt, 2);
        assert(plan.jobs.size() == 2 && Strength(plan.entries[1]) > 0 &&
               Strength(plan.entries[1]) < 10000);
    }

    // Standing lamps (word 7 20: the map's own lights) that seem to move 0.7 m (more than Still,
    // less than SameLamp: the records' wobble in a turn) keep their maps at full strength while
    // over budget, and a new dim lamp (word 7 0) gets its map before them.
    {
        Planner planner;
        std::vector<LampFog::Light> lamps;
        for (int i = 0; i < 20; ++i) {
            LampFog::Light lamp =
                Light(float(i % 5) - 2.0f, float(i / 5) - 1.5f, 8.0f + float(i), 3);
            lamp[7] = std::bit_cast<std::uint32_t>(20.0f);
            lamps.push_back(lamp);
        }
        assert(Standing(lamps[0]) && !Standing(Light(0, 0, 5, 1)));
        for (int f = 0; f < 30; ++f) {
            planner.Run(lamps, Camera(Identity), Projection, Dt, 8);
        }
        std::vector<LampFog::Light> wobbled;
        for (const LampFog::Light& lamp : lamps) {
            LampFog::Light moved = lamp;
            moved[0] = std::bit_cast<std::uint32_t>(std::bit_cast<float>(lamp[0]) + 0.7f);
            wobbled.push_back(moved);
        }
        wobbled.push_back(Light(0, 0, 40, 1, 0.5f));
        for (int f = 0; f < 10; ++f) {
            const Plan plan = planner.Run(wobbled, Camera(Identity), Projection, Dt, 8);
            if (f == 0) {
                assert(plan.jobs.size() == 8 && plan.over == 13 &&
                       Strength(plan.entries[20]) == 65535);
            }
            for (std::size_t k = 0; k < 20; ++k) {
                assert(Strength(plan.entries[k]) == 65535);
            }
        }
    }

    // No camera: nothing shadowed, every map dropped.
    {
        Planner planner;
        const std::vector<LampFog::Light> three(street.begin(), street.begin() + 3);
        planner.Run(three, Camera(Identity), Projection, Dt, 8);
        Plan plan = planner.Run(three, Camera(Identity, false), Projection, Dt, 8);
        assert(!plan.camera && plan.jobs.empty());
        for (const std::uint32_t entry : plan.entries) {
            assert(entry == 0);
        }
        plan = planner.Run(three, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.size() == 3);
    }

    // Out of view: no map wanted and not over budget.
    {
        Planner planner;
        const std::vector<LampFog::Light> beside{Light(20, 0, 5, 1)};
        const Plan plan = planner.Run(beside, Camera(Identity), Projection, Dt, 8);
        assert(plan.jobs.empty() && plan.over == 0 && plan.entries.size() == 1 &&
               plan.entries[0] == 0);
    }

    // A turning camera: still lamps keep their world-direction maps (4 refreshes a frame).
    {
        Planner planner;
        for (int f = 1; f < 40; ++f) {
            const float a = 0.01f * float(f), c = std::cos(a), s = std::sin(a);
            const std::array<float, 12> to_world{c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0};
            std::vector<LampFog::Light> lights;
            for (int i = 0; i < 10; ++i) {
                const float wx = float(i % 5) - 2.0f, wy = float(i / 5) - 0.5f, wz = 20.0f + float(i);
                lights.push_back(Light(c * wx - s * wz, wy, s * wx + c * wz, 3));
            }
            const Plan plan = planner.Run(lights, Camera(to_world), Projection, Dt, 8);
            if (f >= 3) {
                assert(plan.fresh == 4 && plan.over == 0);
            }
        }
    }

    std::printf("lamp fog shaft cap: all checks passed\n");
    return 0;
}
