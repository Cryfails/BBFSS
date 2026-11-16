// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r115b_sun-fog-out-of-sewer-library): "the sun fog shouldn't go indoors at all" for the
// rooms whose light sets carry sun and whose ray traced gate lets some through (the sewer, the
// library). No Vulkan here: tests/test_volumetric_roof.cpp builds this header alone.
//
// BB_VOLUMETRIC_ROOF (read live, VolumetricLight::RoofMode with ParseMode): exactly "1" is on, anything
// else (unset too) off. On, the sun fog march's strength is multiplied by Keep(cover), the camera's
// overhead cover from the wind shelter's counters (WindShelter::CameraCover: 0 in the open, 1 under a
// roof; BB_WIND=1 and BB_WIND_SHELTER above 0 make it). No cover (no shelter field, or its pass has not
// run yet) keeps the fog whole. Off: Keep is not asked, the march's strength is as it was.

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace Vulkan::VolumetricRoof {

/// Keep is 1 up to CoverLo and 0 from CoverHi, a smoothstep between. The shelter's cover is 0.99-1.00
/// in every interior of one test run and 0.00 in the graveyard; an arch, a porch or a doorway gives
/// the values between, which fade the fog instead of cutting it.
inline constexpr float CoverLo = 0.55f, CoverHi = 0.90f; // r115c: of the ROOF share (was 0.50 / 0.95 of the cover)
static_assert(CoverLo > 0.0f && CoverLo < CoverHi && CoverHi < 1.0f);

/// BB_VOLUMETRIC_ROOF's text: exactly "1" is on (1); anything else 0.
inline std::uint32_t ParseMode(const char* text) {
    return text && text[0] == '1' && text[1] == '\0' ? 1u : 0u;
}

/// The share of the sun fog's strength that stays at an overhead cover `cover` (0-1); a cover that is
/// not a number or negative (no shelter field) keeps all of it.
inline float Keep(float cover) {
    if (!std::isfinite(cover) || cover < 0.0f) {
        return 1.0f;
    }
    const float t = std::clamp((cover - CoverLo) / (CoverHi - CoverLo), 0.0f, 1.0f);
    return 1.0f - t * t * (3.0f - 2.0f * t);
}

/// The periodic line's counts: marches asked, of them without a cover, with the fog off (Keep 0),
/// dimmed (Keep between 0 and 1) and the sum of the covers read.
struct Counts {
    std::uint64_t marches = 0, no_field = 0, off = 0, dimmed = 0;
    double cover_sum = 0.0;
};
inline void Tally(Counts& c, float cover, float keep) {
    ++c.marches;
    if (!(cover >= 0.0f) || !std::isfinite(cover)) {
        ++c.no_field;
        return;
    }
    c.cover_sum += double(cover);
    if (keep <= 0.0f) {
        ++c.off;
    } else if (keep < 1.0f) {
        ++c.dimmed;
    }
}

} // namespace Vulkan::VolumetricRoof
