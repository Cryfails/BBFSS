// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r115b_sun-fog-out-of-sewer-library): the roof rule's knob text, curve and counts
// (volumetric_roof.h).
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_roof.h"

using namespace Vulkan::VolumetricRoof;

namespace {
bool Near(float a, float b) {
    return std::abs(a - b) < 1e-5f;
}
}

int main() {
    // The knob: exactly "1" is on.
    assert(ParseMode(nullptr) == 0 && ParseMode("") == 0 && ParseMode("0") == 0 && ParseMode("2") == 0 &&
           ParseMode("10") == 0 && ParseMode(" 1") == 0 && ParseMode("1 ") == 0 && ParseMode("on") == 0);
    assert(ParseMode("1") == 1);

    // The curve: whole in the open, nothing under a roof, a smooth fall between, never rising.
    assert(Keep(0.0f) == 1.0f && Keep(0.30f) == 1.0f && Keep(CoverLo) == 1.0f);
    assert(Keep(CoverHi) == 0.0f && Keep(0.99f) == 0.0f && Keep(1.0f) == 0.0f && Keep(2.0f) == 0.0f);
    assert(Near(Keep(0.5f * (CoverLo + CoverHi)), 0.5f));
    float last = 1.0f;
    for (int i = 0; i <= 200; ++i) {
        const float k = Keep(float(i) / 200.0f);
        assert(k >= 0.0f && k <= 1.0f && k <= last + 1e-6f);
        last = k;
    }
    // The values the owner's log shows: interior stretches 0.99-1.00 (off), the graveyard 0.00 and
    // the partly covered places 0.2-0.5 (whole), 0.62 and 0.74 dimmed.
    assert(Keep(0.99f) == 0.0f && Keep(0.00f) == 1.0f && Keep(0.49f) == 1.0f);
    assert(Keep(0.62f) > 0.7f && Keep(0.62f) < 1.0f && Keep(0.74f) > 0.2f && Keep(0.74f) < 0.6f);

    // No cover (no field, not a number, negative): the fog stays whole.
    assert(Keep(-1.0f) == 1.0f && Keep(std::numeric_limits<float>::quiet_NaN()) == 1.0f &&
           Keep(std::numeric_limits<float>::infinity()) == 1.0f);

    // The counts.
    Counts c;
    Tally(c, -1.0f, 1.0f);
    Tally(c, 0.0f, Keep(0.0f));
    Tally(c, 0.74f, Keep(0.74f));
    Tally(c, 1.0f, Keep(1.0f));
    Tally(c, std::numeric_limits<float>::quiet_NaN(), 1.0f);
    assert(c.marches == 5 && c.no_field == 2 && c.off == 1 && c.dimmed == 1);
    assert(Near(float(c.cover_sum), 1.74f));

    std::printf("volumetric roof: ok\n");
    return 0;
}
