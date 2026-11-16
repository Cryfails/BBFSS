# r111b_footprints-pickup: FEATURE patch on top of r111_footprints (owner 2026-11-15 23:36: "the grave
# yard doesn't have a bloody coat just blood on the ground"; his original idea 07:45: "footprints that
# react to wet surfaces making wet foot prints, muddy, or bloody"). Still off unless BB_FOOTPRINTS is
# set (r111's knob); costs nothing more than r111 when off. Branch: visual/footprints.
#
# What changes: the coat of the feet is now PICKED UP from the ground under them, not forced.
#  - Blood: the footprints pass already reads the ground band around the feet (up-facing pixels within
#    FOOTPRINTS_SENSE_RADIUS_M and FOOTPRINTS_GROUND_M of his height, before any print is laid). It now
#    also counts, for the pixels within FOOTPRINTS_PICK_RADIUS_M (0.25 m) of his position, how many
#    there are (word 16) and how many are blood (word 17) by the dark red albedo rule in linear values
#    (blood_albedo_layout.h: red 0.01 to 0.12 and at least 2.5 times green and 2.5 times blue; the
#    graveyard pool's band mean in the log was 0.021 0.006 0.005). At least 24 pixels and 25% of them
#    blood = the feet are in blood. The coat is then blood at strength (share / 0.5) up to 1; a blood
#    coat leaves 3 prints at that strength, then keeps 0.7 per step (0.7, 0.49, 0.34 ...), dry below
#    0.06 after 10 prints in all. Water and puddles give wet prints as in r111 (13 prints). Water,
#    blood and puddle are tried in that order; the newest pickup wins (replaces kind and strength).
#  - Mud is NOT read: no fair rule exists in the G-buffer (see the README text and the final report).
#    BB_FOOTPRINTS_COAT=wet|mud|blood stays as a test override that forces a coat.
#  - A blood print does not recolour ground that already is blood (a print in the pool would be
#    brighter than the pool), and the print's own colour is now dark red (0.05 0.006 0.005, about the
#    pool's), not 0.3 0.02 0.015.
#  - Log: a line per 600 frames with the coat, pickups by kind and steps by what the feet stood in,
#    one with the blood share at the pickups, and a "first pickup" line per kind.
# The blood rule is its own small header, renderer_vulkan/blood_albedo.h (C++, with a unit test) over
# host_shaders/blood_albedo_layout.h (the numbers, plain #defines the shaders include too), so the blood
# sheen lane can use the same rule: the GLSL one-liner is in footprints.comp (IsBloodAlbedo).
#
# Files, new: renderer_vulkan/blood_albedo.h, host_shaders/blood_albedo_layout.h,
# engine/tests/test_blood_albedo.cpp. Edited (r111's own text; each old text found exactly once, replaced
# or kept with an insert): renderer_vulkan/footprints.h, vk_footprints.h, vk_footprints.cpp,
# host_shaders/footprints.comp, footprints_layout.h, engine/tests/test_footprints.cpp,
# engine/gpu/CMakeLists.txt, engine/build.sh, README.md.
#
# Order: needs r111_footprints.fixed.py applied (refused otherwise). To take r111 out again, revert
# r111b first (r111's check and revert refuse files that r111b changed).
# Use: python -I -X utf8 r111b_footprints-pickup.py check | apply | revert
# Root: R111B_ROOT, else <tree>. Line ends kept (CRLF in the tree; new files CRLF). apply backs the
# originals up in r111b_backup next to this script; revert puts each old text back (each new text found
# by itself, exactly once) and removes the new files (refused if one differs from this patch's text).
import os, re, sys

ROOT = os.environ.get("R111B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111b_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
COMP = HS + "footprints.comp"
LAYOUT = HS + "footprints_layout.h"
TEST = "engine/tests/test_footprints.cpp"
CMAKE = "engine/gpu/CMakeLists.txt"
BUILD = "engine/build.sh"
README = "README.md"
ORDER = [RULES, VKH, VKC, COMP, LAYOUT, TEST, CMAKE, BUILD, README]

NEW = {
    RV + "blood_albedo.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r111b_footprints-pickup): is a ground pixel blood? One rule for every effect that needs it
// (the footprints' pickup, the blood sheen): from the pixel's LINEAR albedo (the game's G-buffer
// target 2 decoded from sRGB), dark red:
//   red between BLOOD_ALBEDO_R_MIN (0.01) and BLOOD_ALBEDO_R_MAX (0.12), and
//   red at least BLOOD_ALBEDO_RED_OVER_GREEN (2.5) times green and BLOOD_ALBEDO_RED_OVER_BLUE (2.5)
//   times blue.
// Grounds it was checked against (the footprints log, "linear albedo mean", the band of ground around
// the hunter): the graveyard's blood pool 0.021 0.006 0.005 is blood; the church floor
// 0.125 0.109 0.087 and the dream house floor 0.085 0.132 0.146 are not (green and blue too high);
// a bright red (0.3 0.02 0.015) is not (red over the maximum), nor is near black (red under 0.01: the
// ratios are noise there).
// The numbers live in host_shaders/blood_albedo_layout.h (plain #defines), which the shaders include;
// the shader twin is IsBloodAlbedo in host_shaders/footprints.comp (same four numbers, same tests).
// No Vulkan here: tests/test_blood_albedo.cpp builds it alone.

#include "../host_shaders/blood_albedo_layout.h"

namespace Vulkan::BloodAlbedo {

inline constexpr float RMin = float(BLOOD_ALBEDO_R_MIN);
inline constexpr float RMax = float(BLOOD_ALBEDO_R_MAX);
inline constexpr float RedOverGreen = float(BLOOD_ALBEDO_RED_OVER_GREEN);
inline constexpr float RedOverBlue = float(BLOOD_ALBEDO_RED_OVER_BLUE);

/// `r`, `g`, `b`: linear albedo.
constexpr bool IsBlood(float r, float g, float b) {
    return r >= RMin && r <= RMax && r >= RedOverGreen * g && r >= RedOverBlue * b;
}

inline bool IsBlood(const float rgb[3]) {
    return IsBlood(rgb[0], rgb[1], rgb[2]);
}

} // namespace Vulkan::BloodAlbedo
''',
    HS + "blood_albedo_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111b_footprints-pickup): the numbers of the blood rule (renderer_vulkan/blood_albedo.h
// explains it and holds the C++ function; host_shaders/footprints.comp holds the GLSL one). Plain
// #define lines only: shaders include this file through GL_GOOGLE_include_directive and C++ includes it
// as it is, so one text holds the numbers both sides use.
#ifndef BLOOD_ALBEDO_LAYOUT_H
#define BLOOD_ALBEDO_LAYOUT_H

// Linear red of a blood pixel: from BLOOD_ALBEDO_R_MIN to BLOOD_ALBEDO_R_MAX.
#define BLOOD_ALBEDO_R_MIN 0.01
#define BLOOD_ALBEDO_R_MAX 0.12
// Red is at least this many times green, and this many times blue.
#define BLOOD_ALBEDO_RED_OVER_GREEN 2.5
#define BLOOD_ALBEDO_RED_OVER_BLUE 2.5

#endif
''',
    "engine/tests/test_blood_albedo.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
''',
}

# (path, old, new): `old` found exactly once; `new` replaces it. Applied when `new` is found exactly once.
EDITS = {
    RULES: [
        # includes
        ('#include "../host_shaders/footprints_layout.h"\n',
         '#include "../host_shaders/footprints_layout.h"\n#include "blood_albedo.h"\n'),
        # the header's coat paragraph
        ("// water). Each print takes the coat's amount as its strength, and the coat then keeps DryPerStep of\n"
         "// it; below MinCoat the feet are dry and place nothing. BB_FOOTPRINTS_COAT (a TEST) gives the feet a\n"
         "// coat that never dries. The game marks neither mud nor blood in what the engine sees (a blood pool\n"
         "// is a forward draw, not ground), so mud and blood prints come only from that test knob for now.\n",
         "// water). Each print takes the coat's amount as its strength; a wet coat then keeps DryPerStep of it\n"
         "// each step; below MinCoat the feet are dry and place nothing. BB_FOOTPRINTS_COAT (a TEST) gives the\n"
         "// feet a coat that never dries.\n"
         "// Pickup (r111b; the owner: \"the grave yard doesn't have a bloody coat just blood on the ground\"):\n"
         "// the coat comes from the ground under the feet. Blood: of the up-facing ground pixels within\n"
         "// FOOTPRINTS_PICK_RADIUS_M of his position and FOOTPRINTS_GROUND_M of his height (the pass counts\n"
         "// them before any print is laid), at least MinPickPixels and BloodSharePercent of them are blood by\n"
         "// the dark red albedo rule of blood_albedo.h (linear red 0.01 to 0.12, at least 2.5 times green and\n"
         "// 2.5 times blue); the coat is then blood at BloodAmount (the share over BloodFullShare, at most 1).\n"
         "// A blood coat leaves BloodFullPrints prints at its strength, then keeps BloodKeep of it each step:\n"
         "// a full coat gives 3 full prints, then 0.7, 0.49 ... and is dry after 10 (7 of them fading). Water,\n"
         "// blood and puddle are tried in that order and the newest pickup wins (a new source replaces the\n"
         "// coat's kind and strength). Mud has no fair rule in the G-buffer (README): only the test coat makes\n"
         "// mud prints.\n"),
        # slot words
        ("static_assert(Group == 8u && MaxPrints == 48u && SlotWords == 16u);\n",
         "static_assert(Group == 8u && MaxPrints == 48u && SlotWords == 18u);\n"),
        ("inline constexpr std::uint32_t WordRingPx = FOOTPRINTS_WORD_RING_PX;\n",
         "inline constexpr std::uint32_t WordRingPx = FOOTPRINTS_WORD_RING_PX;\n"
         "inline constexpr std::uint32_t WordPickN = FOOTPRINTS_WORD_PICK_N;\n"
         "inline constexpr std::uint32_t WordBloodN = FOOTPRINTS_WORD_BLOOD_N;\n"),
        ("static_assert(WordRingPx + 1 == SlotWords);\n",
         "static_assert(WordPickN == 16 && WordBloodN == 17 && WordBloodN + 1 == SlotWords);\n"),
        ("static_assert(FOOTPRINTS_RING_IN_M == 0.3 && FOOTPRINTS_RING_OUT_M == 0.34);\n",
         "static_assert(FOOTPRINTS_RING_IN_M == 0.3 && FOOTPRINTS_RING_OUT_M == 0.34);\n"
         "static_assert(FOOTPRINTS_PICK_RADIUS_M == 0.25 && FOOTPRINTS_PICK_RADIUS_M < FOOTPRINTS_SENSE_RADIUS_M);\n"
         "// A blood print's own colour is blood by the pickup rule (a print is never read as ground without it).\n"
         "static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_ALBEDO_R), float(FOOTPRINTS_BLOOD_ALBEDO_G),\n"
         "                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));\n"),
        # the coat
        ("struct Coat {\n"
         "    Kind kind = Kind::Wet;\n"
         "    float amount = 0.0f; ///< 0: dry\n"
         "};\n",
         "/// What the feet stand in, and so pick up: water, blood, a puddle (tried in that order).\n"
         "enum class Source : std::uint32_t { None = 0, Water = 1, Puddle = 2, Blood = 3 };\n"
         "\n"
         "inline const char* SourceName(Source source) {\n"
         "    return source == Source::Water    ? \"water\"\n"
         "           : source == Source::Puddle ? \"a puddle\"\n"
         "           : source == Source::Blood  ? \"blood\"\n"
         "                                      : \"nothing\";\n"
         "}\n"
         "\n"
         "/// The coat: its kind, how much is on the feet (0: dry), the prints still to leave at the whole\n"
         "/// amount, and what the feet stood in at the last Soak.\n"
         "struct Coat {\n"
         "    Kind kind = Kind::Wet;\n"
         "    float amount = 0.0f;    ///< 0: dry\n"
         "    std::uint32_t full = 0; ///< prints that still leave the whole amount\n"
         "    Source source = Source::None;\n"
         "};\n"
         "\n"
         "/// How a coat wears off: `full` prints at the whole amount, then each step keeps `keep` of it.\n"
         "struct CoatRule {\n"
         "    std::uint32_t full;\n"
         "    float keep;\n"
         "};\n"
         "inline constexpr std::uint32_t BloodFullPrints = 3; ///< a blood coat: this many full prints\n"
         "inline constexpr float BloodKeep = 0.7f;            ///< then each step keeps this much\n"
         "inline constexpr CoatRule RuleOf(Kind kind) {\n"
         "    // (mud, which only the test coat makes, wears as wet does)\n"
         "    return kind == Kind::Blood ? CoatRule{BloodFullPrints, BloodKeep} : CoatRule{1, DryPerStep};\n"
         "}\n"
         "// Blood under the feet: of the pickup disc's up-facing ground pixels (at least MinPickPixels), at\n"
         "// least BloodSharePercent are blood (blood_albedo.h); the coat's strength is the share over\n"
         "// BloodFullShare, at most 1.\n"
         "inline constexpr std::uint32_t MinPickPixels = 24;\n"
         "inline constexpr std::uint32_t BloodSharePercent = 25;\n"
         "inline constexpr float BloodFullShare = 0.5f;\n"),
        ("/// This frame's soaking, before a step: a forced coat always; water or a puddle make the feet wet.\n"
         "inline void Soak(Coat& c, const Knobs& k, bool in_water, bool glossy) {\n"
         "    if (k.coat_forced) {\n"
         "        c.kind = k.coat;\n"
         "        c.amount = 1.0f;\n"
         "        return;\n"
         "    }\n"
         "    if (in_water || glossy) {\n"
         "        c.kind = Kind::Wet;\n"
         "        c.amount = 1.0f;\n"
         "    }\n"
         "}\n",
         "/// The pickup disc is in blood: `pick` up-facing ground pixels, `blood` of them blood.\n"
         "inline bool InBlood(std::uint32_t pick, std::uint32_t blood) {\n"
         "    return pick >= MinPickPixels && std::uint64_t(blood) * 100u >= std::uint64_t(pick) * BloodSharePercent;\n"
         "}\n"
         "\n"
         "/// A blood coat's strength from the pickup disc: its blood share over BloodFullShare, 0 to 1.\n"
         "inline float BloodAmount(std::uint32_t pick, std::uint32_t blood) {\n"
         "    if (pick == 0) {\n"
         "        return 0.0f;\n"
         "    }\n"
         "    return std::clamp(float(blood) / float(pick) / BloodFullShare, 0.0f, 1.0f);\n"
         "}\n"
         "\n"
         "/// This frame's pickup, before a step: a forced coat always. Else what the feet stand in is water\n"
         "/// (wet), else blood (blood, at BloodAmount), else a puddle (wet); the newest pickup replaces the\n"
         "/// coat's kind and strength, and with nothing under the feet the coat is kept as it is. True when\n"
         "/// the feet stepped into a source (a different one than the frame before, or one after none).\n"
         "inline bool Soak(Coat& c, const Knobs& k, bool in_water, bool glossy, std::uint32_t pick = 0,\n"
         "                 std::uint32_t blood = 0) {\n"
         "    if (k.coat_forced) {\n"
         "        c.kind = k.coat;\n"
         "        c.amount = 1.0f;\n"
         "        return false;\n"
         "    }\n"
         "    const Source now = in_water                  ? Source::Water\n"
         "                       : InBlood(pick, blood)    ? Source::Blood\n"
         "                       : glossy                  ? Source::Puddle\n"
         "                                                 : Source::None;\n"
         "    const bool picked = now != Source::None && now != c.source;\n"
         "    c.source = now;\n"
         "    if (now == Source::None) {\n"
         "        return false;\n"
         "    }\n"
         "    c.kind = now == Source::Blood ? Kind::Blood : Kind::Wet;\n"
         "    c.amount = now == Source::Blood ? BloodAmount(pick, blood) : 1.0f;\n"
         "    c.full = RuleOf(c.kind).full;\n"
         "    return picked;\n"
         "}\n"),
        ("    c.amount *= DryPerStep;\n"
         "    if (c.amount < MinCoat) {\n"
         "        c.amount = 0.0f;\n"
         "    }\n"
         "    return strength;\n",
         "    if (c.full > 1) { // (a blood coat: its first prints leave the whole amount)\n"
         "        --c.full;\n"
         "    } else {\n"
         "        c.amount *= RuleOf(c.kind).keep;\n"
         "    }\n"
         "    if (c.amount < MinCoat) {\n"
         "        c.amount = 0.0f;\n"
         "    }\n"
         "    return strength;\n"),
    ],
    VKH: [
        ("// bbport (r111_footprints): the hunter's footprints after he stepped in water (and, with a test\n"
         "// knob, mud or blood), laid into the game's G-buffer so its own lights light them (footprints.h has\n",
         "// bbport (r111_footprints, r111b): the hunter's footprints after he stepped in water or in blood on\n"
         "// the ground (and, with a test knob, mud), laid into the game's G-buffer so its own lights light\n"
         "// them (footprints.h has\n"),
        ("        u32 previews = 0, sense_fresh = 0, planes = 0;\n",
         "        u32 previews = 0, sense_fresh = 0, planes = 0;\n"
         "        std::array<u32, 3> pickups{};  ///< coat pickups by kind (the feet newly in a source)\n"
         "        std::array<u32, 4> steps_in{}; ///< steps by what the feet stood in (R::Source)\n"
         "        u32 share_n = 0, share_last = 0, share_max = 0, share_sum = 0; ///< blood share at pickups, %\n"),
        ("    bool told_unfit = false, told_position = false, told_unread = false, told_print = false;\n",
         "    bool told_unfit = false, told_position = false, told_unread = false, told_print = false;\n"
         "    std::array<bool, 3> told_pickup{}; ///< the first pickup of each kind is told\n"),
    ],
    VKC: [
        ('                                   : "from the game (wet from a water plane or glossy ground)",\n',
         '                                   : "from the ground (wet: water, puddles; blood: dark red)",\n'),
        ("    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);\n",
         "    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);\n"
         "    // (r111b) the pickup disc under his feet: its up-facing ground pixels, and the blood ones.\n"
         "    const u32 pick_px = fresh ? c[R::WordPickN] : 0u, blood_px = fresh ? c[R::WordBloodN] : 0u;\n"),
        ("        R::Soak(coat, k, in_water, glossy);\n"
         "        const R::Step s = R::Walk(walker, pos);\n"
         "        if (s.step) {\n"
         "            ++stats.steps;\n",
         "        // (a stale sense reads as nothing under the feet: keep the coat's source, so one pool is one pickup)\n"
         "        if ((fresh || in_water || k.coat_forced) && R::Soak(coat, k, in_water, glossy, pick_px, blood_px)) {\n"
         "            const u32 share = pick_px ? u32(u64(blood_px) * 100u / pick_px) : 0u;\n"
         "            const u32 kind_at = std::min<u32>(u32(coat.kind), 2u);\n"
         "            ++stats.pickups[kind_at];\n"
         "            if (coat.source == R::Source::Blood) {\n"
         "                stats.share_last = share;\n"
         "                stats.share_max = std::max(stats.share_max, share);\n"
         "                stats.share_sum += share;\n"
         "                ++stats.share_n;\n"
         "            }\n"
         "            if (!told_pickup[kind_at]) {\n"
         "                told_pickup[kind_at] = true;\n"
         "                BbReport::Printf(\"Footprints (r111): first pickup at frame %llu: a %s coat from %s, \"\n"
         "                                 \"strength %.2f; pickup disc %u px, %u blood (%u%%); ground band %u \"\n"
         "                                 \"px, %u glossy\\n\",\n"
         "                                 static_cast<unsigned long long>(frame), R::KindName(coat.kind),\n"
         "                                 R::SourceName(coat.source), double(coat.amount), pick_px, blood_px,\n"
         "                                 share, c[R::WordGroundN], c[R::WordWetN]);\n"
         "            }\n"
         "        }\n"
         "        const R::Step s = R::Walk(walker, pos);\n"
         "        if (s.step) {\n"
         "            ++stats.steps;\n"
         "            ++stats.steps_in[std::min<u32>(u32(coat.source), 3u)];\n"),
        ("                     double(s[R::WordAlbedoB]) * g, s[R::WordRingPx], water);\n",
         "                     double(s[R::WordAlbedoB]) * g, s[R::WordRingPx], water);\n"
         "    BbReport::Printf(\"Footprints (r111): pickup: coat %s %.2f, %u prints at full strength left; picked \"\n"
         "                     \"up %u wet, %u blood, %u mud (mud is not read); steps in blood %u, in water %u, \"\n"
         "                     \"on a puddle %u, elsewhere %u\\n\",\n"
         "                     R::KindName(coat.kind), double(coat.amount), coat.full, stats.pickups[0],\n"
         "                     stats.pickups[2], stats.pickups[1], stats.steps_in[3], stats.steps_in[1],\n"
         "                     stats.steps_in[2], stats.steps_in[0]);\n"
         "    BbReport::Printf(\"Footprints (r111): blood pickups %u: share of the pickup disc in blood last %u%%, \"\n"
         "                     \"max %u%%, mean %u%%; disc now %u px, %u blood; the rule: linear \"\n"
         "                     \"red %.2f to %.2f, at least %.1f times green and %.1f times blue, from %u%% of \"\n"
         "                     \"the disc\\n\",\n"
         "                     stats.pickups[2], stats.share_last, stats.share_max,\n"
         "                     stats.share_n ? stats.share_sum / stats.share_n : 0u, s[R::WordPickN],\n"
         "                     s[R::WordBloodN], double(BLOOD_ALBEDO_R_MIN), double(BLOOD_ALBEDO_R_MAX),\n"
         "                     double(BLOOD_ALBEDO_RED_OVER_GREEN), double(BLOOD_ALBEDO_RED_OVER_BLUE),\n"
         "                     R::BloodSharePercent);\n"),
    ],
    COMP: [
        ('#include "footprints_layout.h"\n',
         '#include "footprints_layout.h"\n#include "blood_albedo_layout.h"\n'),
        ("// 0..1 from a world point's cell (2.5 cm): the uneven edge of a print.\n",
         "// The ground is blood (r111b): a dark red albedo, in linear values. The numbers are\n"
         "// blood_albedo_layout.h's; the C++ twin is BloodAlbedo::IsBlood (renderer_vulkan/blood_albedo.h,\n"
         "// with its unit test). Any shader that needs the rule can copy this function.\n"
         "bool IsBloodAlbedo(vec3 a) {\n"
         "    return a.r >= BLOOD_ALBEDO_R_MIN && a.r <= BLOOD_ALBEDO_R_MAX &&\n"
         "           a.r >= BLOOD_ALBEDO_RED_OVER_GREEN * a.g && a.r >= BLOOD_ALBEDO_RED_OVER_BLUE * a.b;\n"
         "}\n"
         "\n"
         "// 0..1 from a world point's cell (2.5 cm): the uneven edge of a print.\n"),
        ("                    n[FOOTPRINTS_WORD_ALBEDO_B] = uint(clamp(a.b, 0.0, 1.0) * 255.0 + 0.5);\n",
         "                    n[FOOTPRINTS_WORD_ALBEDO_B] = uint(clamp(a.b, 0.0, 1.0) * 255.0 + 0.5);\n"
         "                    if (across <= FOOTPRINTS_PICK_RADIUS_M) { // r111b: the pickup disc under the feet\n"
         "                        n[FOOTPRINTS_WORD_PICK_N] = 1u;\n"
         "                        n[FOOTPRINTS_WORD_BLOOD_N] = IsBloodAlbedo(a.rgb) ? 1u : 0u;\n"
         "                    }\n"),
        ("            vec4 s = imageLoad(specular_img, p);\n",
         "            vec4 s = imageLoad(specular_img, p);\n"
         "            const bool ground_blood = IsBloodAlbedo(a.rgb); // r111b: a print on blood keeps its colour\n"),
        ("                    a.rgb = mix(a.rgb, blood_albedo, FOOTPRINTS_BLOOD_COVER * blood);\n",
         "                    if (!ground_blood) {\n"
         "                        a.rgb = mix(a.rgb, blood_albedo, FOOTPRINTS_BLOOD_COVER * blood);\n"
         "                    }\n"),
    ],
    LAYOUT: [
        ("#define FOOTPRINTS_SLOT_WORDS 16u\n", "#define FOOTPRINTS_SLOT_WORDS 18u\n"),
        ("#define FOOTPRINTS_WORD_RING_PX 15u\n",
         "#define FOOTPRINTS_WORD_RING_PX 15u\n"
         "// r111b: the pickup disc, the ground band's pixels within FOOTPRINTS_PICK_RADIUS_M of his position\n"
         "// (the ground under and around the feet): how many, and how many of them are blood by the albedo\n"
         "// rule of blood_albedo_layout.h.\n"
         "#define FOOTPRINTS_WORD_PICK_N 16u\n"
         "#define FOOTPRINTS_WORD_BLOOD_N 17u\n"),
        ("#define FOOTPRINTS_GROUND_M 0.08\n",
         "#define FOOTPRINTS_GROUND_M 0.08\n"
         "// (r111b) The pickup disc around his position, within the ground band (metres across).\n"
         "#define FOOTPRINTS_PICK_RADIUS_M 0.25\n"),
        ("#define FOOTPRINTS_BLOOD_ALBEDO_R 0.3\n"
         "#define FOOTPRINTS_BLOOD_ALBEDO_G 0.02\n"
         "#define FOOTPRINTS_BLOOD_ALBEDO_B 0.015\n",
         "// (r111b: dark red about as the graveyard pool's own albedo, linear 0.021 0.006 0.005 on average;\n"
         "// r111 had 0.3 0.02 0.015, far brighter than the pool the blood comes from)\n"
         "#define FOOTPRINTS_BLOOD_ALBEDO_R 0.05\n"
         "#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006\n"
         "#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005\n"),
    ],
    TEST: [
        ("    // A forced coat never dries; the test view prints every step at full.\n",
         "    // Pickup (r111b): blood on the ground under the feet, and what a blood coat does.\n"
         "    {\n"
         "        const Knobs k = Read(\"1\", nullptr);\n"
         "        assert(!InBlood(23, 23) && InBlood(24, 6) && !InBlood(24, 5) && !InBlood(100, 24));\n"
         "        assert(InBlood(100, 25) && !InBlood(0, 0));\n"
         "        assert(Near(BloodAmount(100, 25), 0.5) && Near(BloodAmount(100, 50), 1.0));\n"
         "        assert(BloodAmount(100, 100) == 1.0f && BloodAmount(0, 0) == 0.0f);\n"
         "        Coat c;\n"
         "        Kind kind = Kind::Wet;\n"
         "        // 5% of the disc: no pickup. 60%: a blood coat at full strength.\n"
         "        assert(!Soak(c, k, false, false, 200, 10) && c.amount == 0.0f && c.source == Source::None);\n"
         "        assert(Soak(c, k, false, false, 200, 120));\n"
         "        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 3u);\n"
         "        assert(!Soak(c, k, false, false, 200, 120)); // still in it: no new pickup\n"
         "        // The feet leave the blood (nothing under them: the coat is kept): 3 full prints, then 0.7\n"
         "        // of the amount a step, dry after 10 prints in all.\n"
         "        assert(!Soak(c, k, false, false, 200, 0) && c.amount == 1.0f && c.source == Source::None);\n"
         "        float strength[24] = {};\n"
         "        int prints = 0;\n"
         "        while (prints < 24) {\n"
         "            const float s = TakeStep(c, k, false, kind);\n"
         "            if (s == 0.0f) {\n"
         "                break;\n"
         "            }\n"
         "            assert(kind == Kind::Blood);\n"
         "            strength[prints++] = s;\n"
         "        }\n"
         "        assert(prints == 10 && c.amount == 0.0f);\n"
         "        assert(strength[0] == 1.0f && strength[1] == 1.0f && strength[2] == 1.0f);\n"
         "        assert(Near(strength[3], 0.7) && Near(strength[4], 0.49) && Near(strength[9], 0.0823543));\n"
         "        // A weaker pickup: 30% of the disc is 0.6 of the strength.\n"
         "        assert(Soak(c, k, false, false, 100, 30) && Near(c.amount, 0.6));\n"
         "        // The newest pickup wins: a puddle after blood is wet at full; blood on a puddle is blood\n"
         "        // (a different source than the frame before); water beats blood.\n"
         "        assert(Soak(c, k, false, true, 100, 0) && c.kind == Kind::Wet && c.amount == 1.0f);\n"
         "        assert(c.source == Source::Puddle && c.full == 1u);\n"
         "        assert(!Soak(c, k, false, true, 100, 0));\n"
         "        assert(Soak(c, k, false, true, 200, 120) && c.kind == Kind::Blood && c.source == Source::Blood);\n"
         "        assert(Soak(c, k, true, false, 200, 120) && c.kind == Kind::Wet && c.source == Source::Water);\n"
         "        // Too few ground pixels in the disc (23 of 23 blood): not blood.\n"
         "        Coat few;\n"
         "        assert(!Soak(few, k, false, false, 23, 23) && few.amount == 0.0f);\n"
         "        // A forced coat is no pickup.\n"
         "        const Knobs forced = Read(\"1\", \"mud\");\n"
         "        Coat f;\n"
         "        assert(!Soak(f, forced, false, false, 200, 120) && f.kind == Kind::Mud && f.amount == 1.0f);\n"
         "        // Blood and wet coats as a table: blood 3 full then 0.7; wet 1 full then 0.8.\n"
         "        assert(RuleOf(Kind::Blood).full == 3u && Near(RuleOf(Kind::Blood).keep, 0.7));\n"
         "        assert(RuleOf(Kind::Wet).full == 1u && Near(RuleOf(Kind::Wet).keep, 0.8));\n"
         "        assert(std::string(SourceName(Source::Blood)) == \"blood\");\n"
         "    }\n"
         "    // A forced coat never dries; the test view prints every step at full.\n"),
        ('#include <cstdio>\n#include "gpu/shadps4/video_core/renderer_vulkan/footprints.h"\n',
         '#include <cstdio>\n#include <string>\n#include "gpu/shadps4/video_core/renderer_vulkan/footprints.h"\n'),
    ],
    CMAKE: [
        ("        list(APPEND INCLUDES ${SHADER_SRC}/footprints_layout.h)\n",
         "        list(APPEND INCLUDES ${SHADER_SRC}/footprints_layout.h)\n"
         "        list(APPEND INCLUDES ${SHADER_SRC}/blood_albedo_layout.h)\n"),
        ("target_include_directories(footprints-test PRIVATE ..)\n",
         "target_include_directories(footprints-test PRIVATE ..)\n"
         "# bbport (r111b_footprints-pickup): the blood rule (blood_albedo.h); also built and run by\n"
         "# engine/build.sh --test.\n"
         "add_executable(blood-albedo-test EXCLUDE_FROM_ALL ../tests/test_blood_albedo.cpp)\n"
         "target_compile_options(blood-albedo-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(blood-albedo-test PRIVATE ..)\n"),
    ],
    BUILD: [
        ("    out/footprints-test\n",
         "    out/footprints-test\n"
         "    # bbport (r111b_footprints-pickup): the blood rule\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_blood_albedo.cpp -o out/blood-albedo-test\n'
         "    out/blood-albedo-test\n"),
    ],
    README: [
        ("The game marks neither mud nor blood on the ground in what the engine sees, so mud and blood prints come only from the test variable `BB_FOOTPRINTS_COAT` for now.",
         "The coat is picked up from the ground under the feet. Blood: of the up-facing ground pixels within 25 cm of his position and 8 cm of his height (counted by the pass before any print is laid), at least 24 pixels and at least 25% of them are dark red by the albedo rule (linear albedo: red 0.01 to 0.12, and red at least 2.5 times the green and 2.5 times the blue; the graveyard pool's band averages 0.021 0.006 0.005, a bright red 0.3 0.02 0.015 is not blood); the feet then carry blood at a strength of that share over 50% (at most 1), the first 3 prints leave the whole strength and each step after keeps 0.7 of it (0.7, 0.49, 0.34 for a full coat), and the feet are dry (below 0.06) after 10 prints. Water, blood and a puddle are tried in that order and the newest pickup wins: a new source replaces the coat's kind and strength; wet prints work as before (13 prints). The rule lives in `blood_albedo.h` over `blood_albedo_layout.h` (its numbers, which shaders include; the GLSL twin is `IsBloodAlbedo` in `footprints.comp`), with a unit test. Mud is not read: the game's ground is dark brown nearly everywhere (the church floor averages 0.125 0.109 0.087 linear albedo, the graveyard ground near the pool the same warm grey) and gloss alone does not tell mud from wet stone, so no rule would be fair; only the test variable `BB_FOOTPRINTS_COAT=mud` makes mud prints."),
        ("the first print, a G-buffer it cannot write (once)",
         "the first print, the first pickup of each kind, a G-buffer it cannot write (once)"),
        ("the test view's ring pixels and the last water plane.",
         "the test view's ring pixels and the last water plane; then two lines on the pickup: the coat, the pickups and the steps by what the feet stood in, and the blood share of the pickup disc at the pickups (last, largest, mean) with the disc's pixels in a recent frame."),
        ("for the puddle sense)", "for the puddle and blood sense)"),
        ("a blood print takes the albedo toward a dark red by up to 85%, raises",
         "a blood print takes the albedo toward a dark red (linear 0.05 0.006 0.005, about the graveyard pool's own colour) by up to 85%, but not on ground that already is blood by the pickup rule (a print in the pool is no brighter than the pool), raises"),
        ("Unset or empty: the coat comes from the game as above;",
         "Unset or empty: the coat is picked up from water and the ground as above;"),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; is r111_footprints applied, and is this patch's own earlier version "
                             "reverted?): %r" % (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if have == NEW[path]:
        return "applied"
    raise SystemExit("REFUSED %s: exists and differs from this patch's text" % path)


def text_checks(texts):
    """Ties a compiler cannot check, on the full result (edited and new files)."""
    def need(path, text, n=1):
        if texts[path].count(text) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d"
                             % (path, text, texts[path].count(text), n))
    rules, cpp, lay, comp = texts[RULES], texts[VKC], texts[LAYOUT], texts[COMP]
    bl = texts[HS + "blood_albedo_layout.h"]
    # The numbers of the rule, read from the layout, give what the README and the tests say.
    nums = {m.group(1): float(m.group(2)) for m in re.finditer(r"#define (BLOOD_ALBEDO_\w+) ([0-9.]+)\n", bl)}
    if nums != {"BLOOD_ALBEDO_R_MIN": 0.01, "BLOOD_ALBEDO_R_MAX": 0.12, "BLOOD_ALBEDO_RED_OVER_GREEN": 2.5,
                "BLOOD_ALBEDO_RED_OVER_BLUE": 2.5}:
        raise SystemExit("text check: the blood rule's numbers are not the documented ones: %r" % nums)

    def is_blood(r, g, b):
        return nums["BLOOD_ALBEDO_R_MIN"] <= r <= nums["BLOOD_ALBEDO_R_MAX"] and \
            r >= nums["BLOOD_ALBEDO_RED_OVER_GREEN"] * g and r >= nums["BLOOD_ALBEDO_RED_OVER_BLUE"] * b
    if not (is_blood(0.021, 0.006, 0.005) and is_blood(0.05, 0.006, 0.005)
            and not is_blood(0.125, 0.109, 0.087) and not is_blood(0.085, 0.132, 0.146)
            and not is_blood(0.3, 0.02, 0.015)):
        raise SystemExit("text check: the rule does not hold on the logged grounds")
    # The print's colour in the layout is the one the README and the rule's header say.
    for define, value in (("FOOTPRINTS_BLOOD_ALBEDO_R", "0.05"), ("FOOTPRINTS_BLOOD_ALBEDO_G", "0.006"),
                          ("FOOTPRINTS_BLOOD_ALBEDO_B", "0.005"), ("FOOTPRINTS_PICK_RADIUS_M", "0.25"),
                          ("FOOTPRINTS_SLOT_WORDS", "18u"), ("FOOTPRINTS_WORD_PICK_N", "16u"),
                          ("FOOTPRINTS_WORD_BLOOD_N", "17u")):
        need(LAYOUT, "#define %s %s\n" % (define, value))
    # The GLSL rule uses the four numbers by name, and nothing else.
    need(COMP, "bool IsBloodAlbedo(vec3 a) {\n"
               "    return a.r >= BLOOD_ALBEDO_R_MIN && a.r <= BLOOD_ALBEDO_R_MAX &&\n"
               "           a.r >= BLOOD_ALBEDO_RED_OVER_GREEN * a.g && a.r >= BLOOD_ALBEDO_RED_OVER_BLUE * a.b;\n"
               "}\n")
    need(COMP, '#include "blood_albedo_layout.h"\n')
    need(COMP, "IsBloodAlbedo(a.rgb)", 2)
    need(COMP, "n[FOOTPRINTS_WORD_PICK_N] = 1u;\n")
    need(COMP, "n[FOOTPRINTS_WORD_BLOOD_N] = IsBloodAlbedo(a.rgb) ? 1u : 0u;\n")
    need(COMP, "if (!ground_blood) {\n")
    # The sense is counted before the print code (and so before a print changes the albedo): the
    # pickup words are written in the sense block, ahead of the prints' loop.
    if not (comp.find("n[FOOTPRINTS_WORD_BLOOD_N]") < comp.find("// The prints: the strongest of each kind here.")):
        raise SystemExit("text check: the pickup counts are not before the prints in footprints.comp")
    # The shader's counter words and the C++ words agree.
    need(RULES, "WordPickN == 16 && WordBloodN == 17 && WordBloodN + 1 == SlotWords")
    need(RULES, "SlotWords == 18u")
    need(RULES, '#include "blood_albedo.h"\n')
    need(VKC, "c[R::WordPickN]")
    need(VKC, "c[R::WordBloodN]")
    need(VKH, "std::array<bool, 3> told_pickup{};")
    # The build wiring.
    need(CMAKE, "add_executable(blood-albedo-test EXCLUDE_FROM_ALL ../tests/test_blood_albedo.cpp)\n")
    need(CMAKE, "list(APPEND INCLUDES ${SHADER_SRC}/blood_albedo_layout.h)\n")
    need(BUILD, "tests/test_blood_albedo.cpp -o out/blood-albedo-test\n")
    need(BUILD, "    out/blood-albedo-test\n")
    # The coat's numbers the README states: a full blood coat gives 3 full prints and 10 in all.
    prints, amount, full = 0, 1.0, 3
    while amount >= 0.06:
        prints += 1
        if full > 1:
            full -= 1
        else:
            amount *= 0.7
    if prints != 10:
        raise SystemExit("text check: a blood coat gives %d prints, the README says 10" % prints)
    for words in ("BloodFullPrints = 3;", "BloodKeep = 0.7f;", "MinPickPixels = 24;", "BloodSharePercent = 25;",
                  "BloodFullShare = 0.5f;", "MinCoat = 0.06f", "DryPerStep = 0.8f"):
        need(RULES, words)
    # README: the sentences the new text states.
    whole = texts[README]
    rd = whole[whole.find("### Footprints (in development)\n"):]
    rd = rd[:rd.find("\n## ") + 1] if "\n## " in rd else rd
    for words in ("The coat is picked up from the ground under the feet.", "within 25 cm of his position and 8 cm of his height",
                  "at least 24 pixels and at least 25% of them", "red 0.01 to 0.12", "at least 2.5 times the green and 2.5 times the blue",
                  "0.021 0.006 0.005", "that share over 50%", "the first 3 prints leave the whole strength", "keeps 0.7 of it",
                  "after 10 prints", "newest pickup wins", "Mud is not read", "0.125 0.109 0.087", "`blood_albedo.h`",
                  "`IsBloodAlbedo`", "the first pickup of each kind", "then two lines on the pickup",
                  "linear 0.05 0.006 0.005", "but not on ground that already is blood", "the coat is picked up from water and the ground",
                  "for the puddle and blood sense)"):
        if rd.count(words) != 1:
            raise SystemExit("text check: README holds %r %d times, wanted 1" % (words, rd.count(words)))
    for gone in ("The game marks neither mud nor blood", "the coat comes from the game as above"):
        if gone in whole:
            raise SystemExit("text check: README still says %r" % gone)
    # Log lines: prefix, and under 300 characters with wide numbers (the slot runner keeps 300).
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)', cpp):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111)"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = re.sub(r"%s", "X" * 12, wide)
        wide = wide.replace("%%", "%")
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
        if "pickup" in fmt:
            print("  log line (wide %d): %s..." % (len(wide), fmt[:50]))
    # The constructor's line with its longest texts (show, the new coat text, the longest suffix).
    ctor = None
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)', cpp):
        f = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if f.startswith("Footprints (r111): on%s"):
            ctor = f
    coat_text = re.search(r': "(from the ground \([^"]*)",\n', cpp).group(1)
    base = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, ctor)
    longest = len(base) - 6 + len(", show (test colours, ring)") + len(coat_text) + len(
        " (BB_FOOTPRINTS_COAT names no kind: wet, mud or blood)")
    if longest > 300:
        raise SystemExit("text check: the constructor's line may pass 300 characters (%d)" % longest)
    print("  constructor line at most %d characters" % longest)
    # No tab, no CR in the new texts and in the edit texts; every new file ends with a newline.
    for path, text in NEW.items():
        if "\t" in text or "\r" in text or not text.endswith("\n"):
            raise SystemExit("text check: %s has a tab, a CR or no final newline" % path)
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111b_footprints-pickup.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111B_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, RULES)):
        raise SystemExit("REFUSED: r111_footprints is not applied (%s is missing)" % RULES)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = {path: new_state(path) for path in NEW}
    states = {p[5] for p in plan} | set(news.values())
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                       ["%s %s" % (k, v) for k, v in news.items()]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update(NEW)
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update(NEW)
            text_checks(texts)
            print("applied (%d files edited, %d new; text checks pass)" % (len(plan), len(NEW)))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW.items():
            full = os.path.join(ROOT, path)
            tmp = full + ".r111btmp"
            open(tmp, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited, %d new)" % (len(plan), len(NEW)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(plan), len(NEW)))


main()
