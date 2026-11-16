// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r81_sun-fog-no-rt): the sun fog's area light gate (volumetric_area_gate.h): the knob's
// text, the records' weights, the beam keep, the fog a pixel keeps, the camera's weight, the
// probe's schedule and its list of records.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_area_gate.h"

using namespace Vulkan::VolumetricAreaGate;

namespace {
bool Near(float a, float b) {
    return std::abs(a - b) < 1e-5f;
}
}

int main() {
    // The knob: exactly "1" is on; unset, empty and anything else off.
    assert(!Parse(nullptr) && !Parse("") && !Parse("0") && !Parse("2") && !Parse("10") &&
           !Parse(" 1") && !Parse("1 ") && !Parse("on"));
    assert(Parse("1"));

    // Records as Tint counts them: whole 288-byte records after the offset, at most 256.
    assert(RecordBytes == 288 && RecordCount(64800, 0) == 225 && RecordCount(64800 + 100, 100) == 225);
    assert(RecordCount(287, 0) == 0 && RecordCount(288, 0) == 1 && RecordCount(400, 200) == 0);
    assert(RecordCount(1u << 20, 0) == 256);

    // GLSL's smoothstep.
    assert(Smooth(0.15f, 0.5f, 0.0f) == 0.0f && Smooth(0.15f, 0.5f, 0.15f) == 0.0f &&
           Smooth(0.15f, 0.5f, 0.5f) == 1.0f && Smooth(0.15f, 0.5f, 2.0f) == 1.0f);
    assert(Near(Smooth(0.15f, 0.5f, 0.325f), 0.5f));

    // Light 0's luminance: clamped, scaled to at most 1 a channel, not a number gives 0.
    const float white[3]{1.0f, 1.0f, 1.0f}, bright[3]{4.0f, 2.0f, 0.0f}, dark[3]{-1.0f, 0.1f, 0.0f};
    const float bad[3]{1.0f, std::numeric_limits<float>::quiet_NaN(), 0.0f};
    assert(Near(SunLuminance(white), 1.0f));
    assert(Near(SunLuminance(bright), 0.2126f + 0.5f * 0.7152f));
    assert(Near(SunLuminance(dark), 0.07152f) && SunLuminance(bad) == 0.0f);
    // As stored (the probe): not scaled, clamped, not a number gives 0.
    assert(Near(RawLuminance(bright), 4.0f * 0.2126f + 2.0f * 0.7152f) &&
           Near(RawLuminance(dark), 0.07152f) && RawLuminance(bad) == 0.0f);
    // The probe's ranks are words (the slot runner drops lines that differ only in digits).
    assert(std::strcmp(RankName(0), "first") == 0 && std::strcmp(RankName(3), "fourth") == 0 &&
           std::strcmp(RankName(4), "-") == 0);

    // The built-in white record (as the TINT build's is_fallback).
    std::array<float, AREA_PROBE_ROW_FLOATS> record{};
    record[0] = 0.70710678f;
    record[1] = 0.70710678f;
    record[16] = record[17] = record[18] = 1.0f;
    assert(IsFallback(record.data()));
    record[21] = 0.5f; // light 1 not black
    assert(!IsFallback(record.data()));
    record[21] = 0.0f;
    record[2] = 0.1f; // another direction
    assert(!IsFallback(record.data()));

    // Weights: half the brightest or more is 1 (no change), 15% or less is 0; no brightest is 1.
    assert(SunWeight(0.8f, 0.8f) == 1.0f && SunWeight(0.4f, 0.8f) == 1.0f);
    assert(SunWeight(0.1f, 0.8f) == 0.0f && SunWeight(0.0f, 0.8f) == 0.0f);
    assert(SunWeight(0.26f, 0.8f) > 0.0f && SunWeight(0.26f, 0.8f) < 1.0f);
    assert(SunWeight(0.0f, 0.0f) == 1.0f && SunWeight(0.3f, -1.0f) == 1.0f &&
           SunWeight(0.3f, std::numeric_limits<float>::infinity()) == 1.0f);

    // The beam keep: a ray mostly in shadow keeps its lit air, one mostly in sun does not.
    assert(BeamKeep(0.0f) == 1.0f && BeamKeep(0.35f) == 1.0f && BeamKeep(0.65f) == 0.0f &&
           BeamKeep(1.0f) == 0.0f && Near(BeamKeep(0.5f), 0.5f));

    // The fog a pixel keeps. Outdoors (weights 1): near + far, whatever the lit share.
    assert(Near(Apply(0.3f, 0.2f, 1.0f, 1.0f, 1.0f), 0.5f) && Near(Apply(0.3f, 0.2f, 0.0f, 1.0f, 1.0f), 0.5f));
    // Indoors (weights 0), air all in sun (no roof in the atlas): nothing.
    assert(Apply(0.3f, 0.2f, 1.0f, 0.0f, 0.0f) == 0.0f);
    // Indoors, a beam (a fifth of the ray in sun): all of it.
    assert(Near(Apply(0.3f, 0.2f, 0.2f, 0.0f, 0.0f), 0.5f));
    // Outdoor camera looking into a room: the near air stays, the room's does not.
    assert(Near(Apply(0.3f, 0.2f, 0.9f, 1.0f, 0.0f), 0.3f));
    // Indoor camera looking out at a sunlit street: only its last part (at the street) stays.
    assert(Near(Apply(0.3f, 0.2f, 0.9f, 0.0f, 1.0f), 0.2f));

    // The camera's weight: the grid's mean; no surface (all sky) is 1.
    assert(CameraWeight(0.0f, 0.0f) == 1.0f && CameraWeight(0.5f, 0.0f) == 1.0f);
    assert(Near(CameraWeight(0.25f, 1.0f), 0.25f) && CameraWeight(3.0f, 1.0f) == 1.0f);

    // The probe's schedule: the 120th march, then every 600th.
    ProbeClock clock;
    std::uint32_t lines = 0, first = 0, second = 0;
    for (std::uint32_t march = 1; march < 1320; ++march) {
        if (clock.Next()) {
            ++lines;
            (lines == 1 ? first : second) = march;
        }
    }
    assert(lines == 2 && first == 120 && second == 720);

    // The records the most grid points showed: most first, ties by index, no empty ones.
    std::array<std::uint32_t, Records> counts{};
    auto top = TopRecords(counts.data());
    assert(top[0] == Records && top[3] == Records);
    counts[7] = 30;
    counts[3] = 100;
    counts[200] = 30;
    counts[5] = 1;
    counts[9] = 2;
    top = TopRecords(counts.data());
    assert(top[0] == 3 && top[1] == 7 && top[2] == 200 && top[3] == 9);

    // bbport (r115_sun-fog-indoors): the knob as the engine reads it (live): "1" and "2", else 0
    // (r81's Parse above keeps "1" only).
    assert(ParseMode(nullptr) == 0 && ParseMode("") == 0 && ParseMode("0") == 0 &&
           ParseMode("3") == 0 && ParseMode("12") == 0 && ParseMode(" 2") == 0 &&
           ParseMode("2 ") == 0 && ParseMode("on") == 0);
    assert(ParseMode("1") == 1 && ParseMode("2") == 2);
    // The near mark: negative for every b >= 0 (0 too), and b back without it.
    const float marks[] = {0.0f, 1e-6f, 0.004f, 0.37f, 1.0f};
    for (const float b : marks) {
        assert(NearMarked(b) < 0.0f && Near(Unmarked(NearMarked(b)), b) && Unmarked(b) == b);
    }
    // "2"'s apply: without a mark and without dual r81's Apply; a marked (near) ray takes the
    // camera's weight; after a DUAL march b is kept whole and the sets weigh the rest, no beam test.
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.5f, 1.0f, 0.0f, false), Apply(0.2f, 0.3f, 0.5f, 1.0f, 0.0f)));
    assert(Near(ApplyMode2(0.2f, 0.3f, NearMarked(0.5f), 1.0f, 0.0f, false),
                Apply(0.2f, 0.3f, 0.5f, 1.0f, 1.0f)));
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.1f, 0.0f, 0.0f, true), 0.1f));
    assert(Near(ApplyMode2(0.2f, 0.3f, 0.1f, 0.5f, 1.0f, true), 0.1f + 0.1f + 0.3f));
    assert(Near(ApplyMode2(0.2f, 0.3f, NearMarked(0.1f), 0.5f, 0.0f, true), 0.1f + 0.1f + 0.15f));
    assert(NearMark == (1u << 24) && FlagNear == 4u && FlagDual == 8u && NearMetres == 4.0f);
    std::printf("volumetric area gate: all checks passed\n");
    return 0;
}
