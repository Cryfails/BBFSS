// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111b_footprints-pickup): the blood rule (renderer_vulkan/blood_albedo.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target blood-albedo-test.
#undef NDEBUG
#include <cassert>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/blood_albedo.h"

using namespace Vulkan::BloodAlbedo;

static_assert(BLOOD_ALBEDO_R_MIN == 0.01 && BLOOD_ALBEDO_R_MAX == 0.12);
static_assert(BLOOD_ALBEDO_RED_OVER_GREEN == 2.5 && BLOOD_ALBEDO_RED_OVER_BLUE == 2.5);
static_assert(IsBlood(0.021f, 0.006f, 0.005f) && !IsBlood(0.0f, 0.0f, 0.0f));

int main() {
    // The graveyard pool's band mean (the footprints log: linear albedo mean 0.021 0.006 0.005).
    assert(IsBlood(0.021f, 0.006f, 0.005f));
    // The church floor and the dream house floor (same log): not blood.
    assert(!IsBlood(0.125f, 0.109f, 0.087f));
    assert(!IsBlood(0.085f, 0.132f, 0.146f));
    // r111's first blood print colour is too bright; the new one is blood; a grey is not.
    assert(!IsBlood(0.3f, 0.02f, 0.015f));
    assert(IsBlood(0.05f, 0.006f, 0.005f));
    assert(!IsBlood(0.05f, 0.05f, 0.05f));
    // Near black: the ratios mean nothing.
    assert(!IsBlood(0.009f, 0.001f, 0.001f) && !IsBlood(0.0f, 0.0f, 0.0f));
    // The ratios: green or blue too high by a little.
    assert(IsBlood(0.05f, 0.019f, 0.019f));
    assert(!IsBlood(0.05f, 0.021f, 0.019f));
    assert(!IsBlood(0.05f, 0.019f, 0.021f));
    // The range.
    assert(IsBlood(0.11f, 0.01f, 0.01f) && !IsBlood(0.13f, 0.01f, 0.01f));
    assert(IsBlood(0.0105f, 0.001f, 0.001f) && !IsBlood(0.0095f, 0.001f, 0.001f));
    // The array overload.
    const float pool[3] = {0.021f, 0.006f, 0.005f};
    const float floor_grey[3] = {0.125f, 0.109f, 0.087f};
    assert(IsBlood(pool) && !IsBlood(floor_grey));
    std::puts("blood albedo: ok");
    return 0;
}
