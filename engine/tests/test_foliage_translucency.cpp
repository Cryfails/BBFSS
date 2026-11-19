// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the pure parts of the foliage translucency (renderer_vulkan/foliage_translucency.h): the knob rules, the
// share of light a leaf passes and its hue, the CARD_TRANSMIT rule of the card ray against rt_card_layers.h's CardRayRun (share 0 is the old
// result bit for bit; order independence; the floor; the cap), the lamp's reading of what got through, the sun's hue texel and its zero-luma
// term, the back-lit factor. Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target foliage-translucency-test.
#undef NDEBUG
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <utility>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/foliage_translucency.h"

namespace F = Vulkan::FoliageTranslucency;
using Vulkan::CardRayOpaque;
using Vulkan::CardRayRun;

namespace {
bool Near(float a, float b, float eps = 1e-5f) {
    return std::fabs(a - b) <= eps;
}
const char* Lookup(const std::array<std::pair<const char*, const char*>, 4>& table, const char* name) {
    for (const auto& [k, v] : table) {
        if (k != nullptr && std::strcmp(k, name) == 0) {
            return v;
        }
    }
    return nullptr;
}
} // namespace

int main() {
    // a. the shared numbers
    static_assert(CARD_COLOUR_SIZE == CARD_LAYER_SIZE / 4 && FG_PIXEL_LAMPS == 2);
    assert(F::SettingLight == 1 && F::SettingGlow == 2 && F::SettingBoth == 3);

    // b. the knob rules: the master (a variable wins over the setting), the sub-switches, the alpha layers
    {
        using F::Decide;
        assert(!Decide(nullptr, nullptr, nullptr, 0, true).master);              // all off by default
        assert(!Decide("", nullptr, nullptr, 0, true).master);                   // an empty variable falls to the setting (0)
        assert(Decide(nullptr, nullptr, nullptr, 3, true).light && Decide(nullptr, nullptr, nullptr, 3, true).glow);
        assert(Decide(nullptr, nullptr, nullptr, 1, true).light && !Decide(nullptr, nullptr, nullptr, 1, true).glow);
        assert(!Decide(nullptr, nullptr, nullptr, 2, true).light && Decide(nullptr, nullptr, nullptr, 2, true).glow);
        assert(Decide("1", nullptr, nullptr, 0, true).master && Decide("1", nullptr, nullptr, 0, true).light &&
               Decide("1", nullptr, nullptr, 0, true).glow); // the variable with no sub-switch: both on
        assert(!Decide("0", nullptr, nullptr, 3, true).master);   // the variable wins over the setting
        assert(!Decide("x", nullptr, nullptr, 3, true).master && !Decide("11", nullptr, nullptr, 3, true).master);
        assert(Decide("1", "0", nullptr, 0, true).glow && !Decide("1", "0", nullptr, 0, true).light);
        assert(Decide("1", nullptr, "0", 0, true).light && !Decide("1", nullptr, "0", 0, true).glow);
        assert(Decide(nullptr, nullptr, "1", 1, true).glow && Decide(nullptr, nullptr, "1", 1, true).light); // a sub-switch decides for its own part
        assert(!Decide("1", nullptr, nullptr, 0, false).master); // needs BB_RT_CARD_ALPHA=2
        assert(std::strstr(Decide("1", nullptr, nullptr, 0, false).why, "BB_RT_CARD_ALPHA=2") != nullptr);
        assert(Decide(nullptr, nullptr, nullptr, 99, true).glow && !Decide(nullptr, nullptr, nullptr, -4, true).master); // out of range: the nearest end
    }
    // c. the tuning: defaults, limits, text
    {
        const F::Tune d = F::ReadTune([](const char*) -> const char* { return nullptr; });
        assert(Near(d.pass, 0.25f) && Near(d.tint, 1.0f) && Near(d.floor, 0.02f) && Near(d.strength, 1.0f) && Near(d.wrap, 0.3f) &&
               Near(d.sun_k, 0.318f) && !d.glow_view);
        const std::array<std::pair<const char*, const char*>, 4> t{{{"BB_FOLIAGE_PASS", "0.9"}, {"BB_FOLIAGE_TINT", "x"},
                                                                    {"BB_FOLIAGE_FLOOR", "0.0001"}, {"BB_FOLIAGE_GLOW_VIEW", "1"}}};
        const F::Tune r = F::ReadTune([&](const char* name) { return Lookup(t, name); });
        assert(Near(r.pass, F::PassMax));  // above the limit: the nearest end
        assert(Near(r.tint, 1.0f));        // text: the default
        assert(Near(r.floor, F::FloorMin)); // below the limit
        assert(r.glow_view);
    }
    // d. the leaf's pass: the luma share T, the hue from the leaf
    {
        const F::Rgb grey{0.5f, 0.5f, 0.5f}; // stored sqrt: a leaf of linear 0.25 grey
        const F::Rgb pg = F::LeafPass(grey, 0.25f, 1.0f);
        assert(Near(pg[0], 0.25f) && Near(pg[1], 0.25f) && Near(pg[2], 0.25f)); // a grey leaf passes grey
        const F::Rgb green{0.2f, 0.8f, 0.1f};
        for (const float tint : {0.0f, 0.5f, 1.0f}) {
            const F::Rgb p = F::LeafPass(green, 0.25f, tint);
            assert(Near(F::Luma(p), 0.25f, 1e-3f)); // the hue mix is linear: the luma is T at every tint
            if (tint == 0.0f) {
                assert(Near(p[0], 0.25f) && Near(p[1], 0.25f) && Near(p[2], 0.25f)); // tint 0: grey
            }
        }
        const F::Rgb pe = F::LeafPass(green, 0.25f, 1.0f);
        assert(pe[1] > pe[0] && pe[1] > pe[2]); // a green leaf passes green light
        const F::Rgb black{0.0f, 0.0f, 0.0f};
        const F::Rgb pb = F::LeafPass(black, 0.25f, 1.0f);
        assert(std::isfinite(pb[0]) && Near(pb[0], 0.0f) && Near(pb[1], 0.0f)); // a black texel: finite, 0
    }
    // e. the card ray: share 0 is CardRayRun, bit for bit
    {
        std::mt19937 rng(131);
        for (int run = 0; run < 4000; ++run) {
            std::vector<F::Event> events;
            std::vector<std::uint32_t> kinds;
            const int n = int(rng() % 9);
            for (int i = 0; i < n; ++i) {
                const std::uint32_t pick = rng() % 4;
                F::Event e;
                e.kind = pick == 0 ? std::uint32_t(CARD_NO_DATA) : pick == 1 ? std::uint32_t(CARD_DROPPED) : pick == 2 ? std::uint32_t(CARD_KEPT) : CardRayOpaque;
                e.colour = {0.3f, 0.6f, 0.2f};
                events.push_back(e);
                kinds.push_back(e.kind);
            }
            const std::uint32_t cap = 1 + rng() % 6;
            const auto old = CardRayRun(kinds, cap);
            const auto now = F::PassRun(events, cap, 0.0f, 1.0f, 0.02f);
            assert(now.how == old.how && now.seen == old.seen && now.tested == old.tested && now.no_data == old.no_data);
            assert(now.passed == 0 && now.product[0] == 1.0f && now.product[1] == 1.0f && now.product[2] == 1.0f);
        }
    }
    // f. a leaf passes light and the ray goes on; the floor ends it; order independence; the cap
    {
        const auto leaf = [](float r, float g, float b) {
            F::Event e;
            e.kind = CARD_KEPT;
            e.colour = {r, g, b};
            return e;
        };
        const F::Rgb stored{0.5f, 0.5f, 0.5f};
        std::vector<F::Event> two{leaf(0.5f, 0.5f, 0.5f), leaf(0.5f, 0.5f, 0.5f)};
        auto r = F::PassRun(two, 16, 0.25f, 1.0f, 0.02f);
        assert(r.how == CARD_RAY_FREE && r.passed == 2 && Near(r.product[0], 0.0625f)); // 0.25 x 0.25: free
        std::vector<F::Event> three{two[0], two[1], leaf(0.5f, 0.5f, 0.5f)};
        r = F::PassRun(three, 16, 0.25f, 1.0f, 0.02f);
        assert(r.how == CARD_RAY_KEPT && r.floor_ended == 1 && r.passed == 3); // 0.25^3 = 0.0156 < 0.02: the third blocks
        assert(F::PassRun(three, 16, 0.25f, 1.0f, 0.01f).how == CARD_RAY_FREE); // a lower floor: free
        std::vector<F::Event> opaque{leaf(0.5f, 0.5f, 0.5f), F::Event{CardRayOpaque, stored, false}};
        assert(F::PassRun(opaque, 16, 0.25f, 1.0f, 0.02f).how == CARD_RAY_OPAQUE); // an opaque hit ends it as before
        // order independence: coloured leaves in any order give one product
        std::vector<F::Event> mix{leaf(0.2f, 0.8f, 0.1f), leaf(0.7f, 0.7f, 0.2f)};
        const auto a = F::PassRun(mix, 16, 0.4f, 1.0f, 0.001f);
        std::reverse(mix.begin(), mix.end());
        const auto b = F::PassRun(mix, 16, 0.4f, 1.0f, 0.001f);
        for (int i = 0; i < 3; ++i) {
            assert(Near(a.product[i], b.product[i], 1e-6f));
        }
        // grey: a layer without colour passes T in every channel and is counted
        F::Event g = leaf(0.9f, 0.1f, 0.1f);
        g.grey = true;
        const auto rg = F::PassRun(std::vector<F::Event>{g}, 16, 0.25f, 1.0f, 0.02f);
        assert(rg.grey == 1 && Near(rg.product[0], 0.25f) && Near(rg.product[1], 0.25f) && Near(rg.product[2], 0.25f));
        // the cap: a passed leaf is a tested one; the next candidate blocks at the cap
        std::vector<F::Event> many(5, leaf(0.5f, 0.5f, 0.5f));
        const auto rc = F::PassRun(many, 2, 0.5f, 1.0f, 0.001f);
        assert(rc.how == CARD_RAY_CAP && rc.tested == 2);
    }
    // g. the lamp's reading: luma dims, the hue rides along; nothing passed is 1 and white
    {
        const auto none = F::LampLightOf({1.0f, 1.0f, 1.0f});
        assert(none.grey == 1.0f && none.hue[0] == 1.0f && none.hue[1] == 1.0f && none.hue[2] == 1.0f);
        const F::Rgb product = F::LeafPass({0.2f, 0.8f, 0.1f}, 0.25f, 1.0f);
        const auto l = F::LampLightOf(product);
        assert(Near(l.grey, F::Luma(product)) && Near(F::Luma(l.hue), 1.0f, 1e-4f) && l.hue[1] > l.hue[0]);
        const auto dark = F::LampLightOf({0.0f, 0.0f, 0.0f});
        assert(dark.grey == 0.0f && dark.hue[0] == 1.0f); // no light: no hue to give
    }
    // h. the sun's hue texel: the stored term has zero luma, so only the colour changes
    {
        const F::Rgb p1 = F::LeafPass({0.2f, 0.8f, 0.1f}, 0.25f, 1.0f);
        const F::Rgb p2 = F::LeafPass({0.3f, 0.7f, 0.2f}, 0.25f, 1.0f);
        const F::Rgb sum{p1[0] + p2[0], p1[1] + p2[1], p1[2] + p2[2]};
        const float leaf_luma = F::Luma(p1) + F::Luma(p2);
        const auto t = F::SunHueStore(sum, leaf_luma, 8.0f);
        assert(Near(t.a, leaf_luma / 8.0f));
        for (int i = 0; i < 3; ++i) {
            assert(t.rgb[i] >= 0.0f && t.rgb[i] <= 1.0f); // fits the 8-bit texel
        }
        const F::Rgb term = F::SunHueTerm(t);
        assert(Near(F::Luma(term), 0.0f, 1e-4f)); // zero luma by construction
        assert(term[1] > 0.0f && term[0] < 0.0f);  // green leaves: the term is green, less red
        const auto empty = F::SunHueStore({0.0f, 0.0f, 0.0f}, 0.0f, 8.0f);
        const F::Rgb zero = F::SunHueTerm(empty);
        assert(Near(zero[0], 0.0f) && Near(zero[1], 0.0f) && Near(zero[2], 0.0f)); // no leaf: a is 0, the term is 0
    }
    // i. the back-lit factor
    {
        assert(Near(F::BackLit(-1.0f, 0.3f), 1.0f));  // the light straight behind: full
        assert(Near(F::BackLit(1.0f, 0.3f), 0.0f));   // in front: none
        assert(Near(F::BackLit(0.0f, 0.3f), 0.3f / 1.3f)); // edge on: the wrap
        assert(F::BackLit(-0.5f, 0.0f) == 0.5f && F::BackLit(0.2f, 0.0f) == 0.0f);
    }

    std::puts("foliage translucency: ok");
    return 0;
}
