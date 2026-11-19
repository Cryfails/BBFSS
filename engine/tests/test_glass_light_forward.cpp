// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130g_glass-light-forward): the steady rule for a registered pane drawn with a GPU-placed palette and the numbers the
// lamp shader shares (renderer_vulkan/glass_light_forward.h). Pure: no Vulkan. Built and run by engine/build.sh --test and the
// CMake target glass-light-forward-test.
#undef NDEBUG
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/glass_light_forward.h"

namespace L = Vulkan::GlassLight;

int main() {
    // a. the shared numbers: the counter follows half_counts' 16 words, 9 of them.
    assert(L::RayFirst >= 16u && L::RayFirst + L::RaySlots == 25u && L::RaySlots == 9u);
    assert(L::LampClear == 0.02f && L::SteadyFrames == 3 && L::PlacedPerFrame == 16);

    // b. A, A, A on three frames in a row: taken on the third, and then on.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 7, 100) && !L::JudgeSteady(m, 7, 101) && L::JudgeSteady(m, 7, 102));
        assert(L::JudgeSteady(m, 7, 102) && L::JudgeSteady(m, 7, 103)); // twice in a frame, and on
    }
    // c. the torch: two palette addresses in turn, each instance every other frame: never.
    {
        L::SteadyMap m;
        for (std::uint64_t f = 1; f <= 200; ++f) {
            assert(!L::JudgeSteady(m, (f & 1u) ? 11 : 12, f));
        }
    }
    // d. a gap starts the count again; the same frame twice counts once.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 5, 1) && !L::JudgeSteady(m, 5, 1) && !L::JudgeSteady(m, 5, 2));
        assert(!L::JudgeSteady(m, 5, 4)); // frame 3 missed
        assert(!L::JudgeSteady(m, 5, 5) && L::JudgeSteady(m, 5, 6));
        assert(!L::JudgeSteady(m, 5, 8)); // and a gap after taken starts it again
    }
    // e. two instances do not share a count.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 1, 10) && !L::JudgeSteady(m, 2, 10) && !L::JudgeSteady(m, 1, 11) && !L::JudgeSteady(m, 2, 11));
        assert(L::JudgeSteady(m, 1, 12) && L::JudgeSteady(m, 2, 12));
    }
    // f. the table stays bounded: full of one frame's keys it is cleared (a new key stays, as a first look); with old keys among
    // the new ones only the old go.
    {
        L::SteadyMap m;
        for (std::uint64_t k = 0; k < L::SteadyKeysMost; ++k) {
            L::JudgeSteady(m, 1000 + k, 1);
        }
        assert(m.size() == L::SteadyKeysMost);
        L::JudgeSteady(m, 5000, 2);
        assert(m.size() == 1 && m.contains(5000));
        L::SteadyMap n;
        for (std::uint64_t k = 0; k < 100; ++k) {
            L::JudgeSteady(n, 1000 + k, 1);
        }
        for (std::uint64_t k = 100; k < L::SteadyKeysMost; ++k) {
            L::JudgeSteady(n, 1000 + k, 9);
        }
        L::JudgeSteady(n, 5000, 10);
        assert(n.size() == L::SteadyKeysMost - 100 + 1 && n.contains(5000) && !n.contains(1000) && n.contains(1100));
        for (std::uint64_t f = 11; f < 2000; ++f) { // a long run of changing keys never grows it past the bound
            L::JudgeSteady(n, 9000 + f, f);
            assert(n.size() <= L::SteadyKeysMost);
        }
    }
    // g. frame 0 is a frame like any other.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 3, 0) && !L::JudgeSteady(m, 3, 1) && L::JudgeSteady(m, 3, 2));
    }

    std::puts("glass light forward: ok");
    return 0;
}
