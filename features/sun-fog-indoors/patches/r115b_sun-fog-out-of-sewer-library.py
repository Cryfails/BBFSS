# r115b_sun-fog-out-of-sewer-library: FEATURE patch (owner, 2026-11-16, tested build 72 by hand:
# "There is still fog inside the sewer from volumetric sunlight", "Maybe the indoor fog fix wasn't
# included because it's also here, including the wind and particles in the dark interior" (the
# library); rule of 2026-11-15 14:46: "The sun fog shouldn't go indoors at all").
#
# WHY THE GATE KEPT THE FOG (read from the owner's session log, 48650 lines):
#  - the owner's run had BB_FOG_NOISE=1 (the "wind" feature) AND BB_VOLUMETRIC_AREA_GATE=2: the
#    log says "area gate 2 on 600 of 600 marches: 0 with the dual ray traced gate, ... 600 with the
#    ray traced gate as r85 (fog noise or gate probe on)". r115's dual gate (the part of mode 2 that
#    uses the camera's geometry) is never built together with the fog noise (#error in the shader),
#    so with the noise on, mode 2 is r85's rule plus the near rule: the light sets decide.
#  - and the light sets cannot decide there: the area gate probe lines show "brightest light 0
#    0.940 of 225 records", "camera weight 0.88-1.00" and "fog kept 89-100%" through the whole run:
#    the records of the sewer and the library carry sun, so the weight is 1 and nothing is cut.
#  So any rule made of the game's light sets or of the ray traced gate alone cannot clear those
#  rooms. The wind shelter (r117b) already measures what is needed, per frame and without ray
#  tracing: the share of the camera's climbing view rays that end on a down facing surface within
#  a few metres (a ceiling, a vault), smoothed over a second, held while the view has no such
#  rays. The log shows "overhead cover 1.00" through every interior stretch (0.99 to 1.00) and 0.00
#  in the graveyard (share 0.61) and the open places.
#
# WHAT THIS PATCH DOES: BB_VOLUMETRIC_ROOF=1 (FEATURE, off by default, read live). The sun fog
# march's strength is multiplied by Keep(cover) = 1 - smoothstep(0.50, 0.95, cover), cover the
# camera's overhead cover read from the wind shelter's counters (WindShelter::CameraCover, the same
# 4 byte host read CameraOpen makes). Under a roof (cover 0.95 or more) the strength is 0: the march
# returns at once for every pixel and the fog image stays 0 (the path the volumetric intensity
# slider at 0 already takes), so no sun fog, no shafts and no drift of it indoors, whatever the
# light sets or the ray traced gate say; in the open (cover 0.5 or less) it is 1 and the march is
# exactly as before. In between (an arch, a porch, a doorway) a smooth fade as the cover follows.
# Lamp fog, the fog noise's own light and every other effect are untouched. This is the owner's rule
# "the sun fog shouldn't go indoors at all", without the window shafts (the owner's 15:04 verdict:
# the church beam cannot stand for other interiors).
#  REQUIRES the wind shelter field: BB_WIND=1 and BB_WIND_SHELTER above 0 (r117; its pass makes the
#  cover). Without it there is no cover, Keep is 1 and the rule does nothing (said once and counted
#  in the periodic line). The wind's own consequences (plants, drift) follow BB_WIND as before.
#  NOT a shader change: no .comp, no CMake shader build changes; every SPIR-V stays byte-identical.
#
# OFF (the default, BB_VOLUMETRIC_ROOF unset or not exactly "1"): RoofKeep returns 1.0f after one
# live knob read, and `strength * 1.0f` is the same float, so the march, its push words and its
# builds are exactly as before; the rasterizer's hook is skipped by the same knob read (no shelter
# read); no pass, buffer or pipeline is made by this patch at all.
# ON: no GPU work is added (the march gets cheaper indoors: its pixels return at the strength
# test); CPU: one 4 byte read of host memory and one live knob read a march; no memory.
#
# Files (11): new renderer_vulkan/volumetric_roof.h (knob text, curve, counters),
# engine/tests/test_volumetric_roof.cpp; edits: vk_wind_shelter.h/.cpp (CameraCover),
# vk_volumetric_light.h/.cpp (RoofMode, SetRoofCover, RoofKeep, one changed line in Integrate),
# vk_rasterizer_effects.cpp (one hook before Integrate), gpu/CMakeLists.txt and build.sh (the test),
# README.md (one row).
#
# Use: python -I -X utf8 r115b_sun-fog-out-of-sewer-library.py check | apply | revert
# Root: R115B_ROOT, else <tree>. Line ends kept (CRLF in the tree; new files in the tree's
# line ends). apply backs the originals up in r115b_backup next to this script; revert takes out
# exactly what apply put in (inserted texts are found by themselves, so a later patch's text next
# to them stays; the one replaced line goes back to the original) and removes the new files.
import os, sys

ROOT = os.environ.get("R115B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r115b_backup")
TAG = ".r115btmp"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
WH = RV + "vk_wind_shelter.h"
WC = RV + "vk_wind_shelter.cpp"
VH = RV + "vk_volumetric_light.h"
VC = RV + "vk_volumetric_light.cpp"
RE = RV + "vk_rasterizer_effects.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"
NH = RV + "volumetric_roof.h"
NT = "engine/tests/test_volumetric_roof.cpp"

NEW_FILES = {
NH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
inline constexpr float CoverLo = 0.50f, CoverHi = 0.95f;
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
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
''',
}

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
INS = {
WH: [
("    [[nodiscard]] float CameraOpen() const;\n",
 "",
 "    /// bbport (r115b_sun-fog-out-of-sewer-library): the camera's overhead cover 0-1 (the r117b\n"
 "    /// measure, BbWindShelter::CoverIndoors of its smoothed share, as the GPU wrote it a frame or two\n"
 "    /// ago); -1 before any pass has run.\n"
 "    [[nodiscard]] float CameraCover() const;\n"),
],
WC: [
("vk::ImageView WindShelter::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {\n",
 "float WindShelter::CameraCover() const {\n"
 "    // bbport (r115b_sun-fog-out-of-sewer-library): -1 = no cover known (the sun fog rule then keeps the fog)\n"
 "    if (!made || !counter_host.mapped || frame == 0) {\n"
 "        return -1.0f;\n"
 "    }\n"
 "    std::uint32_t word = 0;\n"
 "    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_COVER * 4, 4);\n"
 "    return BbWindShelter::CoverIndoors(BbWindShelter::CameraShelter(word));\n"
 "}\n\n",
 ""),
],
VH: [
('#include "video_core/renderer_vulkan/volumetric_area_gate.h"  // bbport (r81_sun-fog-no-rt)\n',
 "",
 '#include "video_core/renderer_vulkan/volumetric_roof.h" // bbport (r115b_sun-fog-out-of-sewer-library)\n'),
("    [[nodiscard]] float AtlasReach() const noexcept { return atlas_reach; }\n",
 "",
 "    /// bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF as the engine reads it (live): 1\n"
 "    /// scales the sun fog's strength by VolumetricRoof::Keep of the cover SetRoofCover gave right before\n"
 "    /// Integrate (-1: no shelter field); 0 off, and then SetRoofCover is not called.\n"
 "    static u32 RoofMode();\n"
 "    void SetRoofCover(float cover) noexcept { roof_cover = cover; }\n"),
("    void SayAreaNearProbe(const u32* words);\n",
 "",
 "    // bbport (r115b_sun-fog-out-of-sewer-library): the factor of this march's strength (1.0f when off),\n"
 "    // the cover SetRoofCover gave, the counts of the 600-march line and the mode last said\n"
 "    float RoofKeep();\n"
 "    float roof_cover = -1.0f;\n"
 "    VolumetricRoof::Counts roof_counts{};\n"
 "    u32 roof_mode_seen = ~0u;\n"
 "    bool roof_said_no_field = false;\n"),
],
VC: [
('    static BbLiveKnobs::Knob<u32> mode{"BB_VOLUMETRIC_AREA_GATE", VolumetricAreaGate::ParseMode};\n    return mode.Get();\n}\n',
 "",
 "\n"
 "// bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF as the engine reads it, live: 1 is\n"
 "// on (VolumetricRoof::ParseMode), anything else off.\n"
 "u32 VolumetricLight::RoofMode() {\n"
 '    static BbLiveKnobs::Knob<u32> mode{"BB_VOLUMETRIC_ROOF", VolumetricRoof::ParseMode};\n'
 "    return mode.Get();\n"
 "}\n"
 "\n"
 "// bbport (r115b_sun-fog-out-of-sewer-library): the factor of this march's sun fog strength: 1.0f with\n"
 "// the knob off (one live knob read; `strength * 1.0f` is the same float, so nothing changes), else\n"
 "// VolumetricRoof::Keep of the cover the rasterizer gave (the wind shelter's overhead cover; no field:\n"
 "// 1). Says the rule once, and every 600 marches the counts.\n"
 "float VolumetricLight::RoofKeep() {\n"
 "    const u32 mode = RoofMode();\n"
 "    if (mode != roof_mode_seen) {\n"
 "        if (mode != 0) {\n"
 '            std::printf("Volumetric lighting (r115b, BB_VOLUMETRIC_ROOF=1): on; the sun fog\'s strength is "\n'
 '                        "scaled by 1 - smoothstep(%.2f, %.2f, the camera\'s overhead cover) (the wind shelter "\n'
 '                        "field: BB_WIND=1 and BB_WIND_SHELTER above 0): none under a roof, whole in the open; "\n'
 '                        "lamp fog unchanged\\n",\n'
 "                        double(VolumetricRoof::CoverLo), double(VolumetricRoof::CoverHi));\n"
 "        } else if (roof_mode_seen != ~0u) {\n"
 '            std::printf("Volumetric lighting (r115b): BB_VOLUMETRIC_ROOF now off (live knobs)\\n");\n'
 "        }\n"
 "        roof_mode_seen = mode;\n"
 "        roof_counts = {};\n"
 "        roof_said_no_field = false;\n"
 "    }\n"
 "    if (mode == 0) {\n"
 "        return 1.0f;\n"
 "    }\n"
 "    const float keep = VolumetricRoof::Keep(roof_cover);\n"
 "    VolumetricRoof::Tally(roof_counts, roof_cover, keep);\n"
 "    if (!(roof_cover >= 0.0f) && !roof_said_no_field) {\n"
 "        roof_said_no_field = true;\n"
 '        std::printf("Volumetric lighting (r115b): no overhead cover yet (the wind shelter field is not made "\n'
 '                    "or its pass has not run: BB_WIND=1 and BB_WIND_SHELTER above 0 make it); the sun fog "\n'
 '                    "stays whole until it does\\n");\n'
 "    }\n"
 "    if (roof_counts.marches % 600 == 0) {\n"
 '        std::printf("Volumetric lighting (r115b): roof rule on %llu marches: sun fog off %llu, dimmed %llu, "\n'
 '                    "whole %llu (no cover known %llu); mean cover %.2f\\n",\n'
 "                    static_cast<unsigned long long>(roof_counts.marches),\n"
 "                    static_cast<unsigned long long>(roof_counts.off),\n"
 "                    static_cast<unsigned long long>(roof_counts.dimmed),\n"
 "                    static_cast<unsigned long long>(roof_counts.marches - roof_counts.off -\n"
 "                                                    roof_counts.dimmed - roof_counts.no_field),\n"
 "                    static_cast<unsigned long long>(roof_counts.no_field),\n"
 "                    roof_counts.marches > roof_counts.no_field\n"
 "                        ? roof_counts.cover_sum / double(roof_counts.marches - roof_counts.no_field)\n"
 "                        : 0.0);\n"
 "        roof_counts = {};\n"
 "    }\n"
 "    return keep;\n"
 "}\n"),
],
RE: [
("        volumetric_light->Integrate(cb_descs[0].first, dc.image_infos[0],\n",
 "        // bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF=1: the camera's overhead cover for the march's strength (-1 without the wind shelter field)\n"
 "        if (VolumetricLight::RoofMode() != 0) {\n"
 "            volumetric_light->SetRoofCover(wind_shelter ? wind_shelter->CameraCover() : -1.0f);\n"
 "        }\n",
 ""),
],
CM: [
("target_include_directories(volumetric-area-gate-test PRIVATE ..)\n",
 "",
 "# bbport (r115b_sun-fog-out-of-sewer-library): the roof rule's knob text, curve and counts (volumetric_roof.h)\n"
 "add_executable(volumetric-roof-test EXCLUDE_FROM_ALL ../tests/test_volumetric_roof.cpp)\n"
 "target_compile_options(volumetric-roof-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(volumetric-roof-test PRIVATE ..)\n"),
],
BS: [
("    out/volumetric-area-gate-test\n",
 "",
 "    # bbport (r115b_sun-fog-out-of-sewer-library): the sun fog's roof rule (volumetric_roof.h)\n"
 '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_volumetric_roof.cpp -o out/volumetric-roof-test\n'
 "    out/volumetric-roof-test\n"),
],
}

# one replaced line (old, new): new does not hold old
REP = {
VC: [
("    const float live_strength = strength *\n",
 "    const float live_strength = RoofKeep() * strength * // bbport (r115b_sun-fog-out-of-sewer-library): 1.0f unless BB_VOLUMETRIC_ROOF=1\n"),
],
}

ROW = ("| `BB_VOLUMETRIC_ROOF` | `1`: the sun fog does not go under a roof, whatever the game's light sets or the ray "
       "traced sun gate say (`BB_VOLUMETRIC_AREA_GATE` cannot clear a room whose light sets carry sun, and its second "
       "ray is not built with `BB_FOG_NOISE`). The sun fog march's strength is multiplied by 1 - smoothstep(0.50, "
       "0.95, c), c the camera's overhead cover from the wind shelter field: the share of the camera's climbing view "
       "rays that end within a few metres on a surface that faces down (a ceiling, a vault, a canopy's underside), "
       "followed over about a second and held while the view has no climbing rays (`Wind shelter (r117)` log lines: "
       "`overhead cover`; 0.99-1.00 in the interiors of one test run, 0.00 in the graveyard). Under a roof the "
       "strength is 0 and every pixel of the march returns at once; in the open it is 1 and the march is as before; "
       "an arch or a porch fades it. Lamp fog and the lamps' light shafts are not touched; the sun's window shafts "
       "go too. Needs the field: `BB_WIND=1` and `BB_WIND_SHELTER` above 0 (without it there is no "
       "cover, the fog stays whole and the log says so once). Read live (a live knobs file may change it). The log "
       "(lines `Volumetric lighting (r115b)`) says the rule once and every 600 marches how many had the fog off, "
       "dimmed or whole, and the mean cover. Cost: no GPU work added (the march gets cheaper indoors); one 4 byte "
       "host read and one knob read a march; no memory. Off (unset or not exactly `1`): the march is as before | off |\n")
ROW_KEY = "| `BB_VOLUMETRIC_ROOF` |"
ROW_ANCHOR_KEY = "| `BB_VOLUMETRIC_AREA_GATE` |"

FILES = (WH, WC, VH, VC, RE, CM, BS, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def ins_for(path, text):
    if path == RM:
        lines = [l for l in text.split("\n") if l.startswith(ROW_ANCHOR_KEY)]
        if len(lines) != 1:
            raise SystemExit("README.md: the BB_VOLUMETRIC_AREA_GATE row is there %d times, wanted 1" % len(lines))
        return [(lines[0] + "\n", "", ROW)]
    return INS.get(path, [])


def state_of(cur, ins, rep, path):
    """'applied', 'clean', or refuse. Inserted texts are found by themselves, not next to their anchor."""
    done = todo = 0
    for anchor, before, after in ins:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    for old, new in rep:
        no, nn = cur.count(old), cur.count(new)
        if no == 1 and nn == 0:
            todo += 1
        elif no == 0 and nn == 1:
            done += 1
        else:
            raise SystemExit("REFUSED %s: replaced line found %d times, its new text %d times: %r"
                             % (path, no, nn, old[:70]))
    total = len(ins) + len(rep)
    if done == total:
        return "applied"
    if todo == total:
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, total))


def text_checks(texts):
    vc, vh, rm, re_ = texts[VC], texts[VH], texts[RM], texts[RE]
    for want, n in (("float VolumetricLight::RoofKeep() {", 1), ("u32 VolumetricLight::RoofMode() {", 1),
                    ("const float live_strength = RoofKeep() * strength *", 1),
                    ('"BB_VOLUMETRIC_ROOF", VolumetricRoof::ParseMode', 1)):
        if vc.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (VC, want, vc.count(want), n))
    # RoofKeep is asked once, in Integrate, before live_strength is used
    if vc.count("RoofKeep()") != 2 or vc.find("RoofKeep() * strength") < vc.find("float VolumetricLight::RoofKeep()"):
        raise SystemExit("text check: RoofKeep is not defined once and asked once")
    for want in ("static u32 RoofMode();", "void SetRoofCover(float cover) noexcept", "float RoofKeep();",
                 "VolumetricRoof::Counts roof_counts{};", '#include "video_core/renderer_vulkan/volumetric_roof.h"'):
        if vh.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times, wanted 1" % (VH, want, vh.count(want)))
    # the hook sits right before Integrate's call, after the knob test
    h = re_.find("if (VolumetricLight::RoofMode() != 0) {")
    i = re_.find("volumetric_light->Integrate(cb_descs[0].first, dc.image_infos[0],")
    if re_.count("SetRoofCover(") != 1 or not (0 <= h < i):
        raise SystemExit("text check: the rasterizer hook is not once, before Integrate")
    if texts[WC].count("float WindShelter::CameraCover() const {") != 1 or \
            texts[WH].count("[[nodiscard]] float CameraCover() const;") != 1:
        raise SystemExit("text check: CameraCover is not declared and defined once")
    if "WS_C_COVER * 4" not in texts[WC]:
        raise SystemExit("text check: CameraCover does not read WS_C_COVER")
    row = [l for l in rm.split("\n") if l.startswith(ROW_KEY)]
    if len(row) != 1 or "0.50, 0.95" not in row[0] or "BB_WIND_SHELTER" not in row[0]:
        raise SystemExit("text check: README row and the curve constants disagree")
    if "CoverLo = 0.50f, CoverHi = 0.95f" not in NEW_FILES[NH]:
        raise SystemExit("text check: the curve constants moved")
    for path in (NH, NT):
        if "\t" in NEW_FILES[path]:
            raise SystemExit("text check: a tab in %s" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R115B_ROOT)" % ROOT)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        ins, rep = ins_for(path, cur), REP.get(path, [])
        plan.append((path, ins, rep, raw, eol, cur, state_of(cur, ins, rep, path)))
    new_present = [os.path.exists(os.path.join(ROOT, p)) for p in NEW_FILES]
    states = {p[6] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[6]) for p in plan))
    state = states.pop()
    if (state == "applied") != all(new_present) or (state == "clean" and any(new_present)):
        raise SystemExit("mixed state: the files read %s but the new files are %s" % (state, new_present))
    eol0 = plan[0][4]

    def applied_texts():
        out = {}
        for path, ins, rep, raw, eol, cur, _ in plan:
            for anchor, before, after in ins:
                cur = cur.replace(anchor, before + anchor + after)
            for old, new in rep:
                cur = cur.replace(old, new)
            if state_of(cur, ins, rep, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        for p, t in NEW_FILES.items():
            out[p] = t
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({**{p[0]: p[5] for p in plan}, **NEW_FILES})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d new, %d edits; text checks on the result pass)"
                  % (len(plan), len(NEW_FILES), sum(len(p[1]) + len(p[2]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, ins, rep, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, ins, rep, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            open(full + TAG, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(full + TAG, full)
        for p, t in NEW_FILES.items():
            full = os.path.join(ROOT, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "wb").write(t.replace("\n", eol0).encode("utf-8"))
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, ins, rep, raw, eol, cur, _ in plan:
        for old, new in rep:
            cur = cur.replace(new, old, 1)
        for anchor, before, after in reversed(ins):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, ins, rep, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, ins, rep, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + TAG, "wb").write(out[path])
        os.replace(full + TAG, full)
    for p in NEW_FILES:
        os.remove(os.path.join(ROOT, p))
    print("reverted")


main()
