// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106c_shaft-march-cheaper): the fast march's knob and counters (lamp_fog_shaft_fast.h) and a
// mirror of point_volumetric.comp's inscatterShadowedFast sampling (the C++ twin of the Python mirror
// scratch r106c_mirror.py): where a half chord's samples read the map, and what that does to the
// energy against the old march that reads every sample.
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <vector>
// the pure test links no runtime: the knob is read from the environment
#define BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE 1
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_fast.h"

using namespace Vulkan::LampFogShaftFast;

namespace {

struct Seg {
    float energy; ///< the segment's light before the map
    float at;     ///< where its map sample lies (any number: the scene function takes it)
};

/// inscatterShadowed's loop over one half chord: every segment with light reads the map.
float OldHalf(const std::vector<Seg>& segs, const std::function<float(float)>& lit, int& reads) {
    float energy = 0.0f;
    for (const Seg& s : segs) {
        if (s.energy > 0.0f) {
            energy += s.energy * lit(s.at);
            ++reads;
        }
    }
    return energy;
}

/// inscatterShadowedFast's loop, statement for statement.
float FastHalf(const std::vector<Seg>& segs, const std::function<float(float)>& lit_at,
               float skip_below, int& reads) {
    const std::size_t n = segs.size();
    float energy = 0.0f, lit_prev = -1.0f, pend_segment = 0.0f, pend_middle = 0.0f;
    for (std::size_t i = 0; i < n; ++i) {
        const float segment = segs[i].energy;
        const float carried = lit_prev >= 0.0f ? lit_prev : 1.0f;
        if ((i & 1u) == 0u || i + 1u == n) {
            float lit = -1.0f;
            if (segment > skip_below) {
                lit = lit_at(segs[i].at);
                ++reads;
            }
            if (pend_segment > 0.0f) {
                float lit_pend;
                if (lit >= 0.0f && lit == lit_prev) {
                    lit_pend = lit;
                } else {
                    lit_pend = lit_at(pend_middle);
                    ++reads;
                }
                energy += pend_segment * lit_pend;
                pend_segment = 0.0f;
            }
            if (segment > 0.0f) {
                energy += segment * (lit >= 0.0f ? lit : carried);
            }
            lit_prev = lit;
        } else if (segment > skip_below) {
            pend_segment = segment;
            pend_middle = segs[i].at;
        } else if (segment > 0.0f) {
            energy += segment * carried;
        }
    }
    return energy;
}

std::vector<Seg> Uniform(std::size_t n) {
    std::vector<Seg> segs;
    for (std::size_t i = 0; i < n; ++i) {
        segs.push_back({1.0f, float(i)});
    }
    return segs;
}

} // namespace

int main() {
    // the knob: exactly "0" is the old march
    assert(ParseFast(nullptr) && ParseFast("") && ParseFast("1") && ParseFast("2") &&
           ParseFast("00") && ParseFast("off"));
    assert(!ParseFast("0"));
    // the skip level is 1/16384 (the README and the shader comment say so)
    assert(std::fabs(SHAFT_FAST_SKIP - 1.0 / 16384.0) < 1e-9);
    // the bound: 3 lights x 2 halves x 6 samples x 1920 x 1080
    assert(TapsBound(3, 6, 1920, 1080) == 3ull * 2 * 6 * 1920 * 1080);
    assert(TapsBound(64, 12, 3840, 2160) == 64ull * 2 * 12 * 3840 * 2160); // no 32-bit overflow
    // counters: Frame() counts, says the first value, returns the flag; PrintLine resets
    {
        const std::uint32_t flag = Frame(5, 6, 640, 360);
        assert(flag == (Fast() ? 1u : 0u));
        assert(totals.frames == 1 && totals.bound == TapsBound(5, 6, 640, 360));
        assert(totals.lights_most == 5);
        Frame(9, 6, 640, 360);
        assert(totals.frames == 2 && totals.lights_most == 9);
        PrintLine();
        assert(totals.frames == 0 && totals.bound == 0);
    }
    // 1. all lit: the same energy; 4 reads of 6 at 6 samples, 7 of 12 at 12
    for (const std::size_t n : {std::size_t(6), std::size_t(12)}) {
        const auto segs = Uniform(n);
        int ro = 0, rf = 0;
        const auto lit = [](float) { return 1.0f; };
        assert(OldHalf(segs, lit, ro) == float(n) && FastHalf(segs, lit, 0.0f, rf) == float(n));
        assert(ro == int(n) && rf == (n == 6 ? 4 : 7));
    }
    // 2. a shadow's edge between samples: the odd sample at the edge reads and the energy is exact
    {
        const auto segs = Uniform(6);
        int ro = 0, rf = 0;
        const auto lit = [](float at) { return at < 3.5f ? 1.0f : 0.0f; };
        assert(OldHalf(segs, lit, ro) == FastHalf(segs, lit, 0.0f, rf));
        assert(rf == 5); // 0, 2, 4, 5 and the odd sample 3 (its neighbours 1 and 0 differ)
    }
    // 3. a thin blocker on an odd sample between two lit ones is missed (the documented limit)
    {
        const auto segs = Uniform(6);
        int ro = 0, rf = 0;
        const auto lit = [](float at) { return at == 1.0f ? 0.0f : 1.0f; };
        assert(OldHalf(segs, lit, ro) == 5.0f && FastHalf(segs, lit, 0.0f, rf) == 6.0f);
    }
    // 4. a sample under skip_below reads nothing and takes the answer before it
    {
        std::vector<Seg> segs = Uniform(6);
        for (Seg& s : segs) {
            s.energy = 1e-3f;
        }
        int rf = 0;
        const auto lit = [](float) { return 0.5f; };
        const float e = FastHalf(segs, lit, 1e-2f, rf); // everything under the level: no reads
        assert(rf == 0 && std::fabs(e - 6e-3f) < 1e-7f); // no answer known: 1 (unshadowed)
    }
    // 5. a randomised comparison: many soft shadows; the fast march's energy stays within a sample's
    // worth of the old march's, and its reads stay under the old march's
    {
        std::uint32_t seed = 12345;
        const auto next = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return float((seed >> 8) & 0xFFFF) / 65535.0f;
        };
        long reads_old = 0, reads_fast = 0;
        double worst = 0.0;
        for (int trial = 0; trial < 2000; ++trial) {
            const float edge1 = next() * 6.0f, edge2 = edge1 + next() * 3.0f;
            const auto lit = [=](float at) {
                return at < edge1 ? 1.0f : (at < edge2 ? 0.25f * std::floor((edge2 - at) / (edge2 - edge1) * 4.0f) : 0.0f);
            };
            auto segs = Uniform(12);
            for (Seg& s : segs) {
                s.energy = 0.5f + next();
            }
            int ro = 0, rf = 0;
            const float old_energy = OldHalf(segs, lit, ro);
            const float fast_energy = FastHalf(segs, lit, 0.0f, rf);
            reads_old += ro;
            reads_fast += rf;
            worst = std::fmax(worst, std::fabs(fast_energy - old_energy) / old_energy);
        }
        assert(reads_fast < reads_old);
        assert(worst < 0.5); // one odd sample of 12 of unit energy wrong at most (1/12 of 1.5 each)
    }
    std::printf("lamp fog shaft fast: ok\n");
    return 0;
}
