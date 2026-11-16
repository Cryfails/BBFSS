# r130c_glass-lamp-light: FEATURE patch (lane LRT, stage S1 of <queue>/LRT/inflight/glass_plan_v2.md). Draft:
# <queue>/LRT/next/r130c_glass-lamp-light.draft.md. A lamp's light that crosses a registered glass entry (r129a's registry:
# window, bottle, lantern, cabinet) is TINTED by the entry's tint and DIMMED by its strength, instead of being blocked (a G-buffer
# glass draw today) or passing untouched (an r83 pane today). The mirror stays opaque. Sun and moon: stage S2, not here.
#
# How (everything OFF by default; nothing changes with the knob off):
#  - BB_GLASS_LIGHT (read once; live with the test tools' live knobs file): unset, empty: nothing. "0": off (live: made but idle).
#    "1" or "on": on, needs BB_GLASS_TABLE on, ray traced lamps and the A2B10G10R10 storage format; else off with a reason line.
#    Other text: off, said. Registry token sX (0..1): the entry's strength (defaults by kind: window 0.90, cabinet 0.90, lantern
#    0.85, bottle 0.75; the mirror does not transmit).
#  - TLAS records: a registry hit of a transmitting kind marks the draw's entry (RtShadow::Entry::glass_light, sticky); a later sun
#    shadow pass draw of the same mesh (same geometry, indices, index count: the "twin") is marked the same. While on, a marked
#    entry's record drops LampMask (and CardLampMask) and gains RtGlassMask 0x10 (an r83 pane already has it alone), and its
#    instanceCustomIndex becomes GLASS_INDEX_BIT | entry index (bit 23; card slots stay below 1<<16). CameraMask and ShadowMask stay
#    (the sun and the camera rays see it as before). With the lamp cards on this frame (BB_RT_CARD_LAMPS) the records stay as today.
#  - Lamp rays: the r92 COLOUR route (a colour image, per-channel visibility, colourScale) is reused. BB_GLASS_LIGHT=1 forces the
#    colour builds on (colour_mode) and selects four new GLASS forms of the tracing COLOUR builds (point_shadow_ray.comp COLOUR=1
#    GLASS=1). A free lamp ray asks one more query (NoOpaque, mask 0x10) for the glass records on its way: each entry multiplies
#    the product once (tint x strength), at most GLASS_RAY_CAP candidates; the grey visibility is the luma of the product, the
#    hue rides in the colour sums. 16 tuning-adjacent words follow the 16 tuning words of a repair pass: flags and 64 tint words.
#
# Off guarantee (BB_GLASS_LIGHT unset, "0" without the live file, or off for a reason): RtShadow::glass_light_mode stays 0, no entry
# is ever marked (Entry::glass_light is 0), glass_rec is false for every record, so the TLAS records are bit for bit those of r129a
# (instance mask, flags and instanceCustomIndex = CardCustomIndex as before; the pane counters unchanged); PointShadow::glass_mode is
# false: colour_mode as before, no GLASS build selected, no extra tuning word, the profile row stays "point shadows". The shader
# changes are all under #ifdef GLASS (and an empty macro GLASS_HUE in the COLOUR builds): the 16 existing point_shadow_ray SPIR-V
# builds are byte-identical (compared before and after by the verifying run).
#
# Differences from the draft: the GPU profile row key is 131 (130 is t129c's sun term view); the glass twin table keeps 4 words an
# entry (geometry, indices, index count, entry); a pass that runs a COLOUR build without the history blend (t_colour clear) still
# dims by the glass luma, without hue (the draft left such a pass transparent); the live knob is a member read once a frame.
#
# Not verified (no full build, no game run, no GPU): that the engine builds and links; that the ray query loop runs without a
# validation error; the picture; whether the lantern pair's index count is '*'; that the 0x10 query costs what the draft estimates;
# whether a sun-pass twin of the window exists (the log counts twins); that BB_GLASS_LIGHT with r86 BB_RT_GLASS_LIGHT together is
# sane (the sun rays would see the registry glass).
#
# Use: python -I -X utf8 r130c_glass-lamp-light.py check | apply | revert
# Root: R130C_ROOT, else <tree>; a root without engine/gpu is refused. Line ends kept (CRLF or LF per file; a mixed file is
# refused; new files take CRLF). Each edit refuses unless its anchor is found exactly once; a mixed applied/clean state is refused;
# text checks run on the result before anything is written. apply backs the originals up in r130c_backup next to this script and
# writes through a temp file and a rename; revert takes out exactly what apply inserted and removes the new files.
# Needs r129a (the registry) applied; t129c does not touch these files.
import os, sys

ROOT = os.environ.get("R130C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r130c_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
SH = HS + "point_shadow_ray.comp"
GR = RV + "glass_registry.h"
TH = RV + "vk_rt_shadow.h"
TC = RV + "vk_rt_shadow.cpp"
PH = RV + "vk_point_shadow.h"
PC = RV + "vk_point_shadow.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
TG = "engine/tests/test_glass_registry.cpp"
R = "README.md"

# New files: path -> text (LF here; written with CRLF).
NEW = {
HS + "glass_light_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130c_glass-lamp-light): what the lamp pass's GLASS builds (point_shadow_ray.comp, GLASS=1) and the engine
// (renderer_vulkan/glass_light.h, which ties these to its constants with static_asserts) share. Plain #define lines only: the
// shader includes this file through GL_GOOGLE_include_directive and C++ includes it as it is.
#ifndef GLASS_LIGHT_LAYOUT_H
#define GLASS_LIGHT_LAYOUT_H

// A glass record's instanceCustomIndex: this bit (bit 23) and, in the low 6 bits, the registry entry index (0 based). Card
// slots (rt_card_uv.h CardSlotsMost) stay below 1 << 16, so a glass record is never taken for a card.
#define GLASS_INDEX_BIT 0x800000u
#define GLASS_ENTRY_MASK 63u
// The glass query's instance mask (RtGlassMask) and its nearest start along a lamp ray, m.
#define GLASS_LIGHT_MASK 0x10u
#define GLASS_LIGHT_TMIN 0.03
// Most candidates (triangles of the mask) one lamp ray looks at.
#define GLASS_RAY_CAP 4u
// The words after a repair pass's 16 tuning words: one flag word, then one tint word for each registry entry (64).
#define GLASS_WORDS 65u
// The flag word: this pass's scene holds glass records; the lamps keep their own hue (BB_LAMP_SHADOW_COLOUR=1).
#define GLASS_FLAG_ACTIVE 1u
#define GLASS_FLAG_LAMP_HUE 2u

#endif
''',
RV + "glass_light.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r130c_glass-lamp-light): lamp light through glass (stage S1 of the glass plan). BB_GLASS_LIGHT=1 (needs the glass
// registry, BB_GLASS_TABLE) makes a lamp's light that crosses a registered glass entry of a transmitting kind (window, bottle,
// lantern, cabinet; not the mirror) tinted by the entry's tint and dimmed by its strength (token sX, 0..1; defaults by kind),
// instead of blocked or passed untouched. No Vulkan here: tests/test_glass_light.cpp builds this header alone and runs the code
// the engine runs. The numbers the shader shares are in host_shaders/glass_light_layout.h.
//
// A tint word (what a lamp ray multiplies by when it crosses the entry): unorm8 R, G, B in bits 0-23 of the linear tint times
// the strength, the entry's kind in bits 24-31 (0: the entry does not transmit). Linear: (c / 255) ^ 2.2.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

#include "../host_shaders/glass_light_layout.h"
#include "glass_registry.h"
#include "rt_card_uv.h"
#include "rt_glass.h"

namespace Vulkan::GlassLight {

namespace R = GlassRegistryRules;
using u8 = std::uint8_t;
using u32 = std::uint32_t;

inline constexpr u32 IndexBit = GLASS_INDEX_BIT, EntryMask = GLASS_ENTRY_MASK, RayCap = GLASS_RAY_CAP;
inline constexpr u32 WordCount = GLASS_WORDS, FlagActive = GLASS_FLAG_ACTIVE, FlagLampHue = GLASS_FLAG_LAMP_HUE;
inline constexpr u32 RayMask = GLASS_LIGHT_MASK;
inline constexpr float RayTmin = float(GLASS_LIGHT_TMIN);

static_assert(IndexBit == (1u << 23) && IndexBit > CardSlotsMost && CardSlotsMost <= IndexBit,
              "a glass record's custom index never reads as a card slot");
static_assert((IndexBit | EntryMask) < (1u << 24), "instanceCustomIndex has 24 bits");
static_assert(EntryMask + 1 == R::MaxEntries && WordCount == 1 + R::MaxEntries && (IndexBit & EntryMask) == 0);
static_assert(RayMask == RtGlassMask && RayCap >= 1 && FlagActive != FlagLampHue);

/// BB_GLASS_LIGHT's text: 0 off (nullptr, "", "0", "off"), 1 on ("1", "on"), 2 unreadable.
constexpr u8 ParseLight(const char* text) {
    return R::ParseView(text);
}

/// The kinds whose lamp light passes (tinted); the mirror stays opaque.
constexpr bool Transmits(R::Kind kind) {
    return kind == R::Kind::Window || kind == R::Kind::Bottle || kind == R::Kind::Lantern || kind == R::Kind::Cabinet;
}

constexpr float DefaultStrength(R::Kind kind) {
    switch (kind) {
    case R::Kind::Window:
    case R::Kind::Cabinet:
        return 0.90f;
    case R::Kind::Lantern:
        return 0.85f;
    case R::Kind::Bottle:
        return 0.75f;
    default:
        return 0.0f;
    }
}

/// The entry's strength: its s token, else the kind's default.
constexpr float StrengthOf(const R::Entry& entry) {
    return entry.strength >= 0.0f ? entry.strength : DefaultStrength(entry.kind);
}

/// An sRGB hex colour (0xRRGGBB) as linear light: (c / 255) ^ 2.2 each.
inline std::array<float, 3> LinearOf(u32 srgb_hex) {
    const auto one = [](u32 byte) { return std::pow(float(byte & 255u) / 255.0f, 2.2f); };
    return {one(srgb_hex >> 16), one(srgb_hex >> 8), one(srgb_hex)};
}

/// The entry's tint word (see above); 0 for an entry that does not transmit.
inline u32 TintWord(const R::Entry& entry) {
    if (!Transmits(entry.kind)) {
        return 0;
    }
    const std::array<float, 3> lin = LinearOf(entry.tint);
    const float s = StrengthOf(entry);
    u32 word = u32(entry.kind) << 24;
    for (u32 c = 0; c < 3; ++c) {
        const float v = std::clamp(lin[c] * s, 0.0f, 1.0f);
        word |= u32(std::lround(v * 255.0f)) << (8 * c);
    }
    return word;
}

/// The 64 tint words of the table (an unused entry: 0).
inline std::array<u32, R::MaxEntries> Words(const R::Table& table) {
    std::array<u32, R::MaxEntries> words{};
    for (u32 i = 0; i < table.count && i < R::MaxEntries; ++i) {
        words[i] = TintWord(table.entries[i]);
    }
    return words;
}

/// How many entries of the table transmit, and how many stay opaque (the mirror).
constexpr u32 CountTransmitting(const R::Table& table) {
    u32 n = 0;
    for (u32 i = 0; i < table.count; ++i) {
        n += Transmits(table.entries[i].kind) ? 1u : 0u;
    }
    return n;
}

/// A glass record's instanceCustomIndex for the registry entry index `entry` (0 based).
constexpr u32 CustomIndex(u8 entry) {
    return IndexBit | (u32(entry) & EntryMask);
}

constexpr bool IsGlassIndex(u32 custom_index) {
    return (custom_index & IndexBit) != 0;
}

/// The flag word a repair pass pushes after its tuning words.
constexpr u32 Flags(bool active, bool lamp_hue) {
    return (active ? FlagActive : 0u) | (lamp_hue ? FlagLampHue : 0u);
}

static_assert(CustomIndex(5) == 0x800005u && CustomIndex(63) == 0x80003fu && IsGlassIndex(CustomIndex(0)));
static_assert(ParseLight("1") == 1 && ParseLight("") == 0 && ParseLight(nullptr) == 0 && ParseLight("2") == 2);
static_assert(Transmits(R::Kind::Window) && !Transmits(R::Kind::Mirror) && !Transmits(R::Kind::None));
static_assert(Flags(true, true) == 3 && Flags(false, true) == 2 && Flags(false, false) == 0);

} // namespace Vulkan::GlassLight
''',
"engine/tests/test_glass_light.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130c_glass-lamp-light): lamp light through glass: the knob text, the kinds that transmit, the strengths, the linear
// tint, the tint words, the custom index range and the registry's s token (renderer_vulkan/glass_light.h, glass_registry.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target glass-light-test.
#undef NDEBUG
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include "gpu/shadps4/video_core/renderer_vulkan/glass_light.h"

namespace L = Vulkan::GlassLight;
namespace R = Vulkan::GlassRegistryRules;

namespace {
bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}
std::uint32_t Channel(std::uint32_t word, int c) {
    return (word >> (8 * c)) & 255u;
}
} // namespace

int main() {
    // a. the shared numbers.
    assert(L::IndexBit == 0x800000u && L::EntryMask == 63u && L::RayCap == 4u && L::WordCount == 65u);
    assert(L::RayMask == 0x10u && Near(L::RayTmin, 0.03f, 1e-6f));

    // b. the knob text.
    assert(L::ParseLight(nullptr) == 0 && L::ParseLight("") == 0 && L::ParseLight("0") == 0 && L::ParseLight("off") == 0);
    assert(L::ParseLight("1") == 1 && L::ParseLight("on") == 1);
    assert(L::ParseLight("2") == 2 && L::ParseLight("yes") == 2 && L::ParseLight(" 1") == 2);

    // c. the kinds.
    assert(L::Transmits(R::Kind::Window) && L::Transmits(R::Kind::Bottle) && L::Transmits(R::Kind::Lantern) &&
           L::Transmits(R::Kind::Cabinet));
    assert(!L::Transmits(R::Kind::Mirror) && !L::Transmits(R::Kind::None));

    // d. the strengths: the kind's default without an s token, the token otherwise (s0 is a strength of 0, not "default").
    {
        const R::Table t = R::Parse("window:1:2;cabinet:3:4;lantern:5:6;bottle:7:8;mirror:9:a;window:b:c:s0.5;window:d:e:s0;"
                                    "bottle:f:10:t102030:s1:f0.1");
        assert(t.errors == 0 && t.count == 8);
        const auto strength = [&](std::uint64_t vs, std::uint64_t ps) {
            const std::uint8_t hit = R::Lookup(t, vs, ps, 1, 1);
            assert(hit != 0);
            return L::StrengthOf(t.entries[hit - 1u]);
        };
        assert(Near(strength(1, 2), 0.90f, 1e-6f) && Near(strength(3, 4), 0.90f, 1e-6f));
        assert(Near(strength(5, 6), 0.85f, 1e-6f) && Near(strength(7, 8), 0.75f, 1e-6f) && strength(9, 10) == 0.0f);
        assert(strength(11, 12) == 0.5f && strength(13, 14) == 0.0f && strength(15, 16) == 1.0f);
        assert(L::CountTransmitting(t) == 7);
    }

    // e. the linear tint: (c / 255) ^ 2.2.
    {
        const auto white = L::LinearOf(0xffffff), black = L::LinearOf(0x000000), orange = L::LinearOf(0xff8000);
        for (int c = 0; c < 3; ++c) {
            assert(Near(white[c], 1.0f, 1e-6f) && black[c] == 0.0f);
        }
        assert(Near(orange[0], 1.0f, 1e-6f) && Near(orange[1], 0.2195f, 0.002f) && orange[2] == 0.0f);
        assert(Near(L::LinearOf(0x808080)[1], 0.2195f, 0.002f));
    }

    // f. the tint words: linear tint times strength in unorm8, the kind on top; the mirror's is 0.
    {
        const R::Table t = R::Parse("window:1:2:tff8000:s1;bottle:3:4;lantern:5:6:s0;mirror:7:8:tff0000;cabinet:9:a:t000000");
        assert(t.errors == 0 && t.count == 5);
        const auto word_of = [&](std::uint64_t vs) {
            const std::uint8_t hit = R::Lookup(t, vs, std::uint64_t(vs + 1), 1, 1);
            assert(hit != 0);
            return L::TintWord(t.entries[hit - 1u]);
        };
        const std::uint32_t window = word_of(1);
        assert((window >> 24) == std::uint32_t(R::Kind::Window) && Channel(window, 0) == 255);
        assert(Channel(window, 1) >= 55 && Channel(window, 1) <= 57 && Channel(window, 2) == 0);
        const std::uint32_t bottle = word_of(3); // white at the default strength 0.75: 191 or 192
        assert((bottle >> 24) == std::uint32_t(R::Kind::Bottle) && Channel(bottle, 0) >= 191 && Channel(bottle, 0) <= 192);
        assert(Channel(bottle, 0) == Channel(bottle, 1) && Channel(bottle, 1) == Channel(bottle, 2));
        const std::uint32_t lantern = word_of(5); // strength 0: dark, but still a lantern (it blocks, it is not "no entry")
        assert((lantern >> 24) == std::uint32_t(R::Kind::Lantern) && (lantern & 0xffffffu) == 0);
        assert(word_of(7) == 0); // the mirror stays opaque: no word
        assert((word_of(9) >> 24) == std::uint32_t(R::Kind::Cabinet) && (word_of(9) & 0xffffffu) == 0);
    }

    // g. the table's words: in entry order (the table is sorted by pair), unused entries 0.
    {
        const R::Table t = R::Parse("window:1:2;mirror:3:4;lantern:5:6:s0.5");
        const auto words = L::Words(t);
        assert(words[0] != 0 && words[1] == 0 && words[2] != 0);
        for (std::size_t i = 3; i < words.size(); ++i) {
            assert(words[i] == 0);
        }
        assert(words.size() == 64 && L::Words(R::Parse("off"))[0] == 0);
    }

    // h. the custom index: never a card slot, within 24 bits, reads back its entry.
    for (std::uint32_t entry = 0; entry < R::MaxEntries; ++entry) {
        const std::uint32_t index = L::CustomIndex(std::uint8_t(entry));
        assert(L::IsGlassIndex(index) && (index & L::EntryMask) == entry && index < (1u << 24));
        assert(index >= Vulkan::CardSlotsMost);
    }
    for (std::uint32_t slot = 0; slot < Vulkan::CardSlotsMost; slot += 17) {
        assert(!L::IsGlassIndex(slot));
    }
    assert(!L::IsGlassIndex(Vulkan::CardSlotsMost - 1));

    // i. the flag word.
    assert(L::Flags(false, false) == 0 && L::Flags(true, false) == 1 && L::Flags(false, true) == 2 && L::Flags(true, true) == 3);

    // j. the registry's s token (stage S1): 0..1, any order after the numbers, once; bad text is skipped and said.
    {
        const R::Table t = R::Parse("window:1:2:s0.5;window:3:4:t102030:s.25:f0.1;mirror:5:6;lantern:7:8:s1");
        assert(t.errors == 0 && t.count == 4);
        assert(t.entries[0].strength == 0.5f && t.entries[1].strength == 0.25f && t.entries[2].strength < 0.0f &&
               t.entries[3].strength == 1.0f);
        assert(t.entries[1].tint == 0x102030 && t.entries[1].f0 == 0.1f);
        assert(R::Parse("window:1:2:s1.5").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:s").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:sx").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:s0.1:s0.2").first_errors[0].reason == std::uint8_t(R::Reason::Field));
        assert(R::Parse("window:1:2:s0.5:7").first_errors[0].reason == std::uint8_t(R::Reason::Field));
        assert(R::Parse("window:1:2:s0.5;window:3:4").errors == 0);
    }

    std::puts("glass light: ok");
    return 0;
}
''',
}

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old).
EDITS = {
SH: [
("ins", "#extension GL_EXT_ray_query : require\n",
 "",
 "#ifdef GLASS\n"
 "#extension GL_GOOGLE_include_directive : require\n"
 "#endif\n"),
("ins", "vec3 colour_a = vec3(0.0), colour_f = vec3(0.0), colour_held = vec3(0.0);\n",
 "",
 "#ifdef GLASS\n"
 "// bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1 only (the GLASS builds: COLOUR=1 GLASS=1, four tracing forms of the COLOUR\n"
 "// builds; every other build is as before, byte for byte). A lamp ray that is free of solid geometry asks one more query for the\n"
 "// glass records on its way (instance mask 0x10, NoOpaque: every candidate is looked at, none is confirmed): each registry entry\n"
 "// it meets (instanceCustomIndex with GLASS_INDEX_BIT) multiplies the product by its tint word once, at most GLASS_RAY_CAP\n"
 "// candidates. lampVisibility then returns the luma of the product as the visibility (dimming in the grey ratio and in every\n"
 "// guard) and ray_hue = product / luma rides in the colour sums (top_hue, sec_hue for the picked lamps), so colourScale keeps the\n"
 "// grey luma and gives the tint's hue. g_glass: the pass's scene holds glass records (word 16 bit 0, written after the 16 tuning\n"
 "// words); g_hue: the lamps keep their own hue (BB_LAMP_SHADOW_COLOUR=1; clear: colourOf is 1). Weaker \"rest\" lamps stay grey.\n"
 "#include \"glass_light_layout.h\"\n"
 "bool g_glass = false, g_hue = false, g_cast = false;\n"
 "uint g_words = 0u;\n"
 "vec3 ray_hue = vec3(1.0), top_hue = vec3(1.0), sec_hue = vec3(1.0);\n"
 "vec3 g_org = vec3(0.0), g_dir = vec3(0.0, 0.0, 1.0);\n"
 "float g_tmin = 0.0, g_tmax = 0.0;\n"
 "\n"
 "vec3 glassCross(vec3 o, float tmin, vec3 dir, float tmax) {\n"
 "    vec3 product = vec3(1.0);\n"
 "    uint seen_lo = 0u, seen_hi = 0u, looked = 0u;\n"
 "    rayQueryEXT glass;\n"
 "    rayQueryInitializeEXT(glass, scene, gl_RayFlagsNoOpaqueEXT, GLASS_LIGHT_MASK, o, max(tmin, float(GLASS_LIGHT_TMIN)), dir, tmax);\n"
 "    while (rayQueryProceedEXT(glass)) {\n"
 "        if (rayQueryGetIntersectionTypeEXT(glass, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {\n"
 "            continue;\n"
 "        }\n"
 "        const uint index = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(glass, false));\n"
 "        if ((index & GLASS_INDEX_BIT) != 0u) {\n"
 "            const uint entry = index & GLASS_ENTRY_MASK;\n"
 "            const uint bit = 1u << (entry & 31u);\n"
 "            const bool seen = ((entry < 32u ? seen_lo : seen_hi) & bit) != 0u;\n"
 "            if (!seen) {\n"
 "                seen_lo |= entry < 32u ? bit : 0u;\n"
 "                seen_hi |= entry < 32u ? 0u : bit;\n"
 "                const uint w = data.d[g_words + entry];\n"
 "                product *= vec3(float(w & 255u), float((w >> 8u) & 255u), float((w >> 16u) & 255u)) * (1.0 / 255.0);\n"
 "            }\n"
 "        }\n"
 "        if (++looked >= GLASS_RAY_CAP) {\n"
 "            rayQueryTerminateEXT(glass);\n"
 "        }\n"
 "    }\n"
 "    return product;\n"
 "}\n"
 "#define GLASS_HUE(h) * h\n"
 "#else\n"
 "#define GLASS_HUE(h)\n"
 "#endif\n"),
("ins", "    return l > 0.0 ? col / l : vec3(1.0);\n",
 "#ifdef GLASS\n"
 "    if (!g_hue) { // bbport (r130c_glass-lamp-light): the lamps keep no hue of their own: only glass changes it\n"
 "        return vec3(1.0);\n"
 "    }\n"
 "#endif\n",
 ""),
("ins", "    t_colour = (f & (1u << 25u)) != 0u;      // bbport (r92_lamp-shadow-colour)\n",
 "",
 "#ifdef GLASS\n"
 "    { // bbport (r130c_glass-lamp-light): the flag word after the 16 tuning words, then the 64 tint words\n"
 "        const uint glass_flags = data.d[at + 16u];\n"
 "        g_glass = (glass_flags & GLASS_FLAG_ACTIVE) != 0u;\n"
 "        g_hue = (glass_flags & GLASS_FLAG_LAMP_HUE) != 0u;\n"
 "        g_words = at + 17u;\n"
 "    }\n"
 "#endif\n"),
("ins", "    const float tmax = ray_len - (ray_clear > 0.0 ? ray_clear : t_clear); // bbport (r91): the lamp's own\n",
 "",
 "#ifdef GLASS\n"
 "    g_cast = false; // bbport (r130c_glass-lamp-light): set where the plain ray is cast\n"
 "#endif\n"),
("ins", "    rayQueryEXT query;\n    // 0x04: everything but cut-out cards (vk_rt_shadow.cpp LampMask).\n",
 "#ifdef GLASS\n"
 "    g_org = origin; // bbport (r130c_glass-lamp-light): the same ray, for the glass query lampVisibility asks when it is free\n"
 "    g_dir = ray_to / ray_len;\n"
 "    g_tmin = reach * 0.5;\n"
 "    g_tmax = tmax;\n"
 "    g_cast = true;\n"
 "#endif\n",
 ""),
("ins", "float lampVisibility(vec3 P, vec3 n, vec3 origin, float reach, vec3 L, vec2 xi) {\n",
 "",
 "#ifdef GLASS\n"
 "    ray_hue = vec3(1.0); // bbport (r130c_glass-lamp-light)\n"
 "#endif\n"),
("ins", "    return ray(from, reach, target) < 0.0 ? 1.0 : 0.0;\n",
 "#ifdef GLASS\n"
 "    // bbport (r130c_glass-lamp-light): a blocked ray is 0; a free one crossed the glass records on its way (glassCross): the luma\n"
 "    // of what they let through, and its hue for the colour sums\n"
 "    if (ray(from, reach, target) >= 0.0) {\n"
 "        return 0.0;\n"
 "    }\n"
 "    if (g_glass && g_cast) {\n"
 "        const vec3 through = glassCross(g_org, g_tmin, g_dir, g_tmax);\n"
 "        const float grey = dot(through, vec3(0.299, 0.587, 0.114));\n"
 "        ray_hue = grey > 1e-4 ? through / grey : vec3(1.0);\n"
 "        return min(grey, 1.0);\n"
 "    }\n"
 "    return 1.0;\n"
 "#else\n",
 "#endif // GLASS (r130c lampVisibility)\n"),
("rep", "vsum_c += colourOf(col) * (vsum - vsum_seen);",
 "vsum_c += colourOf(col) GLASS_HUE(ray_hue) * (vsum - vsum_seen);"),
("ins", "            vsum_top = vsum; // bbport (r92_lamp-shadow-colour): the strongest lamp's part\n",
 "",
 "#ifdef GLASS\n"
 "            top_hue = ray_hue; // bbport (r130c_glass-lamp-light): the hue of what the strongest lamp's ray let through\n"
 "#endif\n"),
("ins", "                vsum += lay_sec_part;\n",
 "#ifdef GLASS\n"
 "                sec_hue = ray_hue; // bbport (r130c_glass-lamp-light): the second strongest lamp's\n"
 "#endif\n",
 ""),
("rep", "vsum_c = top_c * vsum_top;",
 "vsum_c = top_c GLASS_HUE(top_hue) * vsum_top;"),
("rep", "vsum_c = top_c * vsum_top + sec_c * lay_sec_part;",
 "vsum_c = top_c GLASS_HUE(top_hue) * vsum_top + sec_c GLASS_HUE(sec_hue) * lay_sec_part;"),
],
GR: [
("rep", "enum class Reason : u8 { Kind, Vs, Ps, Count, First, Tint, F0, Field, TooMany, Duplicate };",
 "enum class Reason : u8 { Kind, Vs, Ps, Count, First, Tint, F0, Field, TooMany, Duplicate, Strength };"),
("ins", "// BB_GLASS_VIEW=1 (live with the test tools' live knobs file, else read once): registry hits painted over the scene (window\n",
 "// bbport (r130c_glass-lamp-light): entries gain [:sS] (kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0][:sS]): s = the\n"
 "// strength of lamp light through the glass, 0..1 (BB_GLASS_LIGHT; default by kind: window and cabinet 0.90, lantern 0.85, bottle\n"
 "// 0.75; the mirror does not transmit). Same place as t and f: after the numbers, once, any order.\n",
 ""),
("ins", "    bool builtin = false;\n",
 "",
 "    float strength = -1.0f; // bbport (r130c_glass-lamp-light): the s token, 0..1; below 0: the kind's default (glass_light.h)\n"),
("rep", "bool numbers = true, have_tint = false, have_f0 = false;",
 "bool numbers = true, have_tint = false, have_f0 = false, have_strength = false;"),
("ins", "        } else if (c == 'f') {\n",
 "        } else if (c == 's') { // bbport (r130c_glass-lamp-light): the strength of light through the glass\n"
 "            if (have_strength || !ReadUnit(text, {s.b + 1, s.e}, entry.strength)) {\n"
 "                return int(have_strength ? Reason::Field : Reason::Strength);\n"
 "            }\n"
 "            have_strength = true;\n"
 "            numbers = false;\n",
 ""),
("ins", '        return "the same draw is listed twice";\n',
 "",
 "    case Reason::Strength:\n"
 '        return "strength is not s and a number from 0 to 1";\n'),
("ins", 'static_assert(ParseView("1") == 1 && ParseView("") == 0 && ParseView("yes") == 2);\n',
 "",
 'static_assert(Parse("window:1:2:s0.5").entries[0].strength == 0.5f && Parse("window:1:2").entries[0].strength < 0.0f &&\n'
 '              Parse("window:1:2:s2").errors == 1 && Parse("builtin").entries[0].strength < 0.0f);\n'),
],
TH: [
("ins", "        u8 cut_noted = 0;\n",
 "",
 "        // bbport (r130c_glass-lamp-light): the registry entry of a glass draw of this entry (or of its sun shadow pass twin), index +\n"
 "        // 1, sticky for the entry's life (0: none; always 0 while BB_GLASS_LIGHT is off); PrepareScene reads it for the record.\n"
 "        u8 glass_light = 0;\n"),
("ins", "    [[nodiscard]] bool SunWanted() const;\n",
 "",
 "    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT (glass_light.h), decided at start (GlassLightStart): the lamp pass makes its\n"
 "    // GLASS builds, PrepareScene rewrites the records of glass entries. GlassLightActive: this frame's knob is on and the last\n"
 "    // scene held glass records (the lamp rays then ask the glass query).\n"
 "    [[nodiscard]] bool GlassLightWanted() const noexcept {\n"
 "        return glass_light_mode != 0;\n"
 "    }\n"
 "    [[nodiscard]] bool GlassLightLive() const noexcept {\n"
 "        return glass_light_live;\n"
 "    }\n"
 "    [[nodiscard]] bool GlassLightActive() const noexcept {\n"
 "        return glass_light_mode != 0 && glass_light_now && glass_light_records_now != 0;\n"
 "    }\n"
 "    /// The lamp pass could not make its GLASS builds (no storage format): off for good, as if never asked.\n"
 "    void GlassLightOff() noexcept {\n"
 "        glass_light_mode = 0;\n"
 "    }\n"
 "    /// One repair pass pushed the glass words (`active`: with the glass flag), for the 600-frame line.\n"
 "    void NoteGlassLightPass(bool active) noexcept {\n"
 "        ++glass_counts.passes;\n"
 "        glass_counts.passes_glass += active ? 1u : 0u;\n"
 "    }\n"),
("ins", "    /// A TLAS instance's custom index: its card slot once the slot's row is written, else 0.\n",
 "    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT. glass_light_mode: 0 off, 1 made (GlassLightStart); glass_light_live: the live\n"
 "    // knob decides each frame (glass_light_now); glass_light_records_now: glass records the last scene's TLAS got. glass_geo: the\n"
 "    // meshes of registry hits ({geometry, indices, index count | entry + 1 << 32}), for the shadow pass twins.\n"
 "    struct GlassLightCounts {\n"
 "        u64 window_start = 0, records = 0, twins = 0, kept_cards = 0, passes = 0, passes_glass = 0, live_off = 0, off_frame = 0;\n"
 "    };\n"
 "    u8 glass_light_mode = 0;\n"
 "    bool glass_light_live = false, glass_light_now = false;\n"
 "    u32 glass_light_records_now = 0;\n"
 "    GlassLightCounts glass_counts;\n"
 "    std::array<std::array<u64, 3>, 64> glass_geo{};\n"
 "    u32 glass_geo_n = 0;\n"
 "    void GlassLightStart();\n"
 "    bool GlassLightFrame(bool card_lamps);\n"
 "    void GlassLightNote(Entry& entry, const Draw& draw);\n",
 ""),
],
TC: [
("ins", '#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle, TOOL)\n',
 "",
 '#include "video_core/renderer_vulkan/glass_light.h" // bbport (r130c_glass-lamp-light)\n'),
# (review fix) the end of the constructor, so BB_GLASS_LIGHT is read once, before PointShadow::Ready asks GlassLightWanted.
# The draft's anchor (the end of UpdateHeld) runs at every frame end: mode reset every frame (GlassLightOff undone, Ready
# seeing mode 0 on frame 1, the 600-frame line never due, a reason line every frame).
("ins", '    } else {\n        std::printf("Ray tracing: off - setup failed\\n");\n    }\n',
 "",
 "    GlassLightStart(); // bbport (r130c_glass-lamp-light): reads BB_GLASS_LIGHT once; unset: nothing\n"),
("ins", "// bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's draw reached its entry\n",
 "// bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT, read once at start. Unset or empty: nothing (no line, no state). \"0\" without\n"
 "// the live knobs file is as unset. Otherwise the mode is made and the lamp pass (PointShadow::Ready) says the rest; off for a\n"
 "// reason here (not 0 or 1, no registry, no ray traced lamps) is said once. With the live file the knob is read each frame.\n"
 "void RtShadow::GlassLightStart() {\n"
 '    const char* text = std::getenv("BB_GLASS_LIGHT");\n'
 "    if (text == nullptr || text[0] == '\\0') {\n"
 "        return;\n"
 "    }\n"
 "    const u8 parsed = GlassLight::ParseLight(text);\n"
 "    bool live = false;\n"
 "#if BB_GLASS_STATIC_LIVE\n"
 '    const char* file = std::getenv("BB_LIVE_KNOBS_FILE");\n'
 "    live = file != nullptr && file[0] != '\\0';\n"
 "#endif\n"
 "    if (parsed == 0 && !live) {\n"
 "        return;\n"
 "    }\n"
 "    const char* why = parsed == 2                         ? \"is neither 0 nor 1\"\n"
 "                      : !GlassRegistryRules::Load().on ? \"needs BB_GLASS_TABLE\"\n"
 "                      : !capturing                      ? \"no ray traced lamps\"\n"
 "                                                        : nullptr;\n"
 "    if (why != nullptr) {\n"
 '        std::printf("Glass light (r130c): BB_GLASS_LIGHT=%.16s: off (%s)\\n", text, why);\n'
 "        return;\n"
 "    }\n"
 "    glass_light_mode = 1;\n"
 "    glass_light_live = live;\n"
 "    glass_light_now = parsed == 1 || !live;\n"
 "    glass_counts.window_start = frame;\n"
 "}\n"
 "\n"
 "// bbport (r130c_glass-lamp-light): once a scene's records are written (PrepareScene, only while the mode is made): the knob now\n"
 "// (live: each frame), the live flips and the 600-frame line. True: this scene's glass entries get glass records (not with the\n"
 "// lamp cards on, whose CARDS builds have no glass form: the records stay as before, counted).\n"
 "bool RtShadow::GlassLightFrame(bool card_lamps) {\n"
 "    bool now = true;\n"
 "#if BB_GLASS_STATIC_LIVE\n"
 "    if (glass_light_live) {\n"
 '        static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_LIGHT", GlassLight::ParseLight};\n'
 "        now = knob.Get() == 1;\n"
 "    }\n"
 "#endif\n"
 "    if (now != glass_light_now) {\n"
 '        std::printf("Glass light (r130c): live %s at frame %llu\\n", now ? "on" : "off",\n'
 "                    static_cast<unsigned long long>(frame));\n"
 "        glass_light_now = now;\n"
 "    }\n"
 "    if (!now && glass_counts.off_frame != frame + 1) {\n"
 "        glass_counts.off_frame = frame + 1;\n"
 "        ++glass_counts.live_off;\n"
 "    }\n"
 "    if (frame - glass_counts.window_start >= 600) {\n"
 '        std::printf("Glass light (r130c): frames %llu-%llu: glass records %llu (twins %llu), kept blocking (lamp cards) %llu, "\n'
 '                    "passes with glass %llu of %llu, live off %llu frames\\n",\n'
 "                    static_cast<unsigned long long>(glass_counts.window_start + 1), static_cast<unsigned long long>(frame),\n"
 "                    static_cast<unsigned long long>(glass_counts.records), static_cast<unsigned long long>(glass_counts.twins),\n"
 "                    static_cast<unsigned long long>(glass_counts.kept_cards),\n"
 "                    static_cast<unsigned long long>(glass_counts.passes_glass),\n"
 "                    static_cast<unsigned long long>(glass_counts.passes), static_cast<unsigned long long>(glass_counts.live_off));\n"
 "        glass_counts = {};\n"
 "        glass_counts.window_start = frame;\n"
 "    }\n"
 "    glass_light_records_now = 0;\n"
 "    return now && !card_lamps;\n"
 "}\n"
 "\n"
 "// bbport (r130c_glass-lamp-light): a draw reached its entry (PrepareDraw, only while the mode is made). A registry hit of a\n"
 "// transmitting kind marks the entry (sticky) and remembers the mesh; a sun shadow pass draw of a remembered mesh (the twin: the\n"
 "// pass that draws the pane for the sun) is marked with the same entry, so that both records carry the glass index.\n"
 "void RtShadow::GlassLightNote(Entry& entry, const Draw& draw) {\n"
 "    const u64 count = draw.index_count;\n"
 "    if (draw.glass_entry != 0) {\n"
 "        const auto& table = GlassRegistryRules::Load();\n"
 "        const u32 index = u32(draw.glass_entry) - 1u;\n"
 "        if (index >= table.count || !GlassLight::Transmits(table.entries[index].kind)) {\n"
 "            return;\n"
 "        }\n"
 "        entry.glass_light = draw.glass_entry;\n"
 "        const u64 packed = count | u64(draw.glass_entry) << 32;\n"
 "        for (u32 i = 0; i < glass_geo_n; ++i) {\n"
 "            if (glass_geo[i][0] == draw.geometry && glass_geo[i][1] == draw.indices && (glass_geo[i][2] & 0xffffffffull) == count) {\n"
 "                glass_geo[i][2] = packed;\n"
 "                return;\n"
 "            }\n"
 "        }\n"
 "        if (glass_geo_n < glass_geo.size()) {\n"
 "            glass_geo[glass_geo_n++] = {draw.geometry, draw.indices, packed};\n"
 "        }\n"
 "    } else if (draw.shadow_pass && entry.glass_light == 0) {\n"
 "        for (u32 i = 0; i < glass_geo_n; ++i) {\n"
 "            if (glass_geo[i][0] == draw.geometry && glass_geo[i][1] == draw.indices && (glass_geo[i][2] & 0xffffffffull) == count) {\n"
 "                entry.glass_light = u8(glass_geo[i][2] >> 32);\n"
 "                ++glass_counts.twins;\n"
 "                return;\n"
 "            }\n"
 "        }\n"
 "    }\n"
 "}\n"
 "\n",
 ""),
("ins", "    Entry& entry = *r19_entry;\n",
 "",
 "    if (glass_light_mode != 0) { // bbport (r130c_glass-lamp-light): off: this byte test alone\n"
 "        GlassLightNote(entry, draw);\n"
 "    }\n"),
("ins", "    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;\n",
 "",
 "    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT: the knob now; true: the entries a registry hit marked get glass records\n"
 "    const bool glass_rec_on = glass_light_mode != 0 && GlassLightFrame(card_lamps);\n"),
("ins", "        vk::AccelerationStructureInstanceKHR record{\n",
 "        // bbport (r130c_glass-lamp-light): a transmitting registry entry's record (never a cut-out card, a stale copy, an old pose\n"
 "        // or one BB_RT_LAMP_LEAVE leaves out: their lamp bit is withheld already). Off: glass_rec_on and entry->glass_light are 0.\n"
 "        const bool glass_rec = glass_rec_on && entry->glass_light != 0 && mask != 0 && !card && !stale && !leave && !old_pose;\n"
 "        if (entry->glass_light != 0 && glass_light_now && !glass_rec_on) {\n"
 "            ++glass_counts.kept_cards; // the lamp cards are on: the record stays as before\n"
 "        }\n",
 ""),
("rep", "            .instanceCustomIndex = CardCustomIndex(*entry), // bbport (r62_leaf-stage3)\n",
 "            // bbport (r62_leaf-stage3); a glass record's index is its registry entry (bbport r130c_glass-lamp-light)\n"
 "            .instanceCustomIndex = glass_rec ? GlassLight::CustomIndex(u8(entry->glass_light - 1u)) : CardCustomIndex(*entry),\n"),
("ins", "        out[built++] = record;\n",
 "        // bbport (r130c_glass-lamp-light): the glass record drops the lamp bits and takes RtGlassMask (a pane has it alone already:\n"
 "        // glass_gain only where the mask changes, for the pane counts below)\n"
 "        const bool glass_gain = glass_rec && !RtGlassEntry(mask);\n"
 "        if (glass_rec) {\n"
 "            record.mask = u8((u32(record.mask) & ~u32(LampMask | CardLampMask)) | RtGlassMask);\n"
 "            ++glass_light_records_now;\n"
 "            ++glass_counts.records;\n"
 "        }\n",
 ""),
("rep", "        if (RtGlassEntry(static_cast<u8>(record.mask))) {\n",
 "        if (!glass_gain && RtGlassEntry(static_cast<u8>(record.mask))) {\n"),
],
PH: [
("ins", "    OwnImage colour_image;\n",
 "",
 "    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1 (RtShadow::GlassLightWanted) with colour_mode: the four tracing COLOUR builds are\n"
 "    // made in their GLASS form (point_shadow_ray.comp GLASS), and every repair pass pushes the flag word and glass_words (the 64 tint\n"
 "    // words, GlassLight::Words) after its 16 tuning words. Off: false, nothing pushed, nothing selected.\n"
 "    bool glass_mode = false;\n"
 "    std::array<u32, 64> glass_words{};\n"),
],
PC: [
("ins", '#include "video_core/host_shaders/point_shadow_ray_resolve_colour_comp.h"\n',
 "",
 "// bbport (r130c_glass-lamp-light): the GLASS forms of the tracing COLOUR builds (BB_GLASS_LIGHT=1)\n"
 '#include "video_core/host_shaders/point_shadow_ray_centred_colour_glass_comp.h"\n'
 '#include "video_core/host_shaders/point_shadow_ray_colour_glass_comp.h"\n'
 '#include "video_core/host_shaders/point_shadow_ray_half_centred_colour_glass_comp.h"\n'
 '#include "video_core/host_shaders/point_shadow_ray_half_colour_glass_comp.h"\n'
 '#include "video_core/renderer_vulkan/glass_light.h"\n'),
("ins", "std::span<const u32> ColourCode(bool colour, std::span<const u32> plain, std::span<const u32> coloured) {\n    return colour ? coloured : plain;\n}\n",
 "",
 "\n"
 "// bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1: the COLOUR build's GLASS form (same bindings, more code)\n"
 "std::span<const u32> GlassCode(bool glass, std::span<const u32> coloured, std::span<const u32> glassed) {\n"
 "    return glass ? glassed : coloured;\n"
 "}\n"),
("rep", "    colour_mode = tune.colour && EffectPass::StorageFormat(instance, ColourFormat);\n",
 "    // bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1 (RtShadow::GlassLightWanted) needs the colour image too: the colour builds\n"
 "    // are made for it, in their GLASS form (four tracing builds; the resolves do not trace)\n"
 "    glass_mode = rt_shadow.GlassLightWanted();\n"
 "    colour_mode = (tune.colour || glass_mode) && EffectPass::StorageFormat(instance, ColourFormat);\n"
 "    if (glass_mode) {\n"
 "        const auto& glass_table = GlassRegistryRules::Load();\n"
 '        const char* glass_text = std::getenv("BB_GLASS_LIGHT");\n'
 "        if (!colour_mode) {\n"
 '            std::printf("Glass light (r130c): BB_GLASS_LIGHT=%.16s: off (this GPU cannot store A2B10G10R10)\\n",\n'
 '                        glass_text ? glass_text : "");\n'
 "            rt_shadow.GlassLightOff();\n"
 "            glass_mode = false;\n"
 "        } else {\n"
 "            glass_words = GlassLight::Words(glass_table);\n"
 "            const u32 transmitting = GlassLight::CountTransmitting(glass_table);\n"
 '            std::printf("Glass light (r130c): BB_GLASS_LIGHT=%.16s: on: lamp light through %u transmitting entries (tint x "\n'
 '                        "strength), %u mirror entries stay opaque; colour builds on; lamp hue %s (BB_LAMP_SHADOW_COLOUR); live %s\\n",\n'
 '                        glass_text ? glass_text : "", transmitting, glass_table.count - transmitting,\n'
 '                        tune.colour ? "on" : "off", rt_shadow.GlassLightLive() ? "yes (BB_LIVE_KNOBS_FILE)" : "no");\n'
 "            for (u32 i = 0; i < glass_table.count; ++i) {\n"
 "                const auto& e = glass_table.entries[i];\n"
 "                const auto lin = GlassLight::LinearOf(e.tint);\n"
 '                std::printf("Glass light (r130c): entry %u %s %08llx:%08llx tint %06x strength %.2f -> linear %.3f %.3f %.3f%s\\n",\n'
 "                            i + 1, GlassRegistryRules::KindName(e.kind), static_cast<unsigned long long>(e.vs),\n"
 "                            static_cast<unsigned long long>(e.ps), e.tint, double(GlassLight::StrengthOf(e)), double(lin[0]),\n"
 "                            double(lin[1]), double(lin[2]), GlassLight::Transmits(e.kind) ? \"\" : \" opaque (mirror)\");\n"
 "            }\n"
 "        }\n"
 "    }\n"),
("rep", "ColourCode(colour_mode, POINT_SHADOW_RAY_CENTRED_COMP, POINT_SHADOW_RAY_CENTRED_COLOUR_COMP), // r92\n",
 "GlassCode(glass_mode, ColourCode(colour_mode, POINT_SHADOW_RAY_CENTRED_COMP, POINT_SHADOW_RAY_CENTRED_COLOUR_COMP),\n"
 "                                 POINT_SHADOW_RAY_CENTRED_COLOUR_GLASS_COMP), // r92, r130c\n"),
("rep", 'sizeof(Push), POINT_SHADOW_RAY_COLOUR_COMP, "Ray traced lamps (colour)", true)) {\n',
 "sizeof(Push), GlassCode(glass_mode, POINT_SHADOW_RAY_COLOUR_COMP, POINT_SHADOW_RAY_COLOUR_GLASS_COMP),\n"
 '                            "Ray traced lamps (colour)", true)) { // bbport (r130c_glass-lamp-light): GlassCode\n'),
("rep", "ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_CENTRED_COMP,\n"
        + " " * 48 + "POINT_SHADOW_RAY_HALF_CENTRED_COLOUR_COMP), // bbport (r92)\n",
 "GlassCode(glass_mode, ColourCode(colour_mode, POINT_SHADOW_RAY_HALF_CENTRED_COMP,\n"
 + " " * 48 + "POINT_SHADOW_RAY_HALF_CENTRED_COLOUR_COMP),\n"
 + " " * 33 + "POINT_SHADOW_RAY_HALF_CENTRED_COLOUR_GLASS_COMP), // bbport (r92, r130c)\n"),
("rep", 'sizeof(Push), POINT_SHADOW_RAY_HALF_COLOUR_COMP, "Ray traced lamps (half resolution, colour)",\n',
 "sizeof(Push), GlassCode(glass_mode, POINT_SHADOW_RAY_HALF_COLOUR_COMP, POINT_SHADOW_RAY_HALF_COLOUR_GLASS_COMP),\n"
 '                           "Ray traced lamps (half resolution, colour)", // bbport (r130c_glass-lamp-light): GlassCode\n'),
("ins", "    u32 tune_at = 0;\n",
 "",
 "    bool glass_pass = false; // bbport (r130c_glass-lamp-light): this pass pushed the glass words with the flag ACTIVE\n"),
("ins", "            data[tune_at] |= LampLayersBits(pass_tune.radius_m > 0.0f && LampHistoryFrames(pass_tune) > 0.0f); // bbport (r114_lamp-shadow-layers): bits 4-7, 18, 19, 30, 31; 0 when off\n",
 "",
 "            if (glass_mode) { // bbport (r130c_glass-lamp-light): the 16 tuning words end here; the glass words follow at word 16\n"
 "                if (data.size() != std::size_t(tune_at) + 16) {\n"
 "                    data.clear();\n"
 "                    return;\n"
 "                }\n"
 "                glass_pass = rt_shadow.GlassLightActive();\n"
 "                data.push_back(GlassLight::Flags(glass_pass, tune.colour));\n"
 "                data.insert(data.end(), glass_words.begin(), glass_words.end());\n"
 "                rt_shadow.NoteGlassLightPass(glass_pass);\n"
 "            }\n"),
("rep", '    EffectPass::Mark(card_bind ? 64 : 6, card_bind ? "point shadows (leaf cards)" : "point shadows");\n',
 "    // bbport (r130c_glass-lamp-light): a pass with the glass flag has its own row (key 131; 129 and 130 are t129c's and r129a's)\n"
 "    EffectPass::Mark(card_bind ? 64 : glass_pass ? 131 : 6,\n"
 '                     card_bind ? "point shadows (leaf cards)" : glass_pass ? "point shadows (glass light)" : "point shadows");\n'),
],
CM: [
("ins", "add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_comp HALF=1 CENTRED=1 COLOUR=1)\n",
 "",
 "# bbport (r130c_glass-lamp-light): BB_GLASS_LIGHT=1: the GLASS form of each tracing COLOUR build (lamp light through glass); the\n"
 "# builds above are unchanged, byte for byte. The two resolve builds do not trace and have none.\n"
 "add_host_shader(point_shadow_ray.comp point_shadow_ray_colour_glass_comp COLOUR=1 GLASS=1)\n"
 "add_host_shader(point_shadow_ray.comp point_shadow_ray_half_colour_glass_comp HALF=1 COLOUR=1 GLASS=1)\n"
 "add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_colour_glass_comp CENTRED=1 COLOUR=1 GLASS=1)\n"
 "add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_colour_glass_comp HALF=1 CENTRED=1 COLOUR=1 GLASS=1)\n"),
("ins", "    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)\n",
 "    # bbport (r130c_glass-lamp-light): the lamp pass's GLASS builds include the glass light's numbers, shared with C++ (glass_light.h)\n"
 '    if (FILENAME MATCHES "^point_shadow_ray")\n'
 "        list(APPEND INCLUDES ${SHADER_SRC}/glass_light_layout.h)\n"
 "    endif()\n",
 ""),
("ins", "add_executable(glass-registry-test EXCLUDE_FROM_ALL ../tests/test_glass_registry.cpp)\n"
        "target_compile_options(glass-registry-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
        "target_include_directories(glass-registry-test PRIVATE ..)\n",
 "",
 "# bbport (r130c_glass-lamp-light): lamp light through glass: tint words, strengths, custom index, the s token (glass_light.h); also\n"
 "# built and run by engine/build.sh --test.\n"
 "add_executable(glass-light-test EXCLUDE_FROM_ALL ../tests/test_glass_light.cpp)\n"
 "target_compile_options(glass-light-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(glass-light-test PRIVATE ..)\n"),
],
BS: [
("ins", "    out/glass-registry-test\n",
 "",
 "    # bbport (r130c_glass-lamp-light): lamp light through glass: tint words, strengths, custom index, the s token\n"
 '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_glass_light.cpp -o out/glass-light-test\n'
 "    out/glass-light-test\n"),
],
TG: [
("rep", "for (std::uint8_t r = 0; r <= std::uint8_t(Reason::Duplicate); ++r) {",
 "for (std::uint8_t r = 0; r <= std::uint8_t(Reason::Strength); ++r) {"),
("ins", '    std::puts("glass registry: ok");\n',
 "    // o. bbport (r130c_glass-lamp-light): the s token (strength 0..1): after the numbers, once, any order; default below 0.\n"
 "    {\n"
 '        const Table t = Parse("window:1:2:s0.5;bottle:3:4:t102030:s.25:f0.1;mirror:5:6;lantern:7:8:s1;cabinet:9:a:s0");\n'
 "        assert(t.errors == 0 && t.count == 5);\n"
 "        assert(Find(t, 1, 2, 1, 1)->strength == 0.5f && Find(t, 3, 4, 1, 1)->strength == 0.25f);\n"
 "        assert(Find(t, 3, 4, 1, 1)->tint == 0x102030 && Find(t, 3, 4, 1, 1)->f0 == 0.1f);\n"
 "        assert(Find(t, 5, 6, 1, 1)->strength < 0.0f && Find(t, 7, 8, 1, 1)->strength == 1.0f);\n"
 "        assert(Find(t, 9, 10, 1, 1)->strength == 0.0f);\n"
 '        assert(Parse("window:1:2:s1.5").first_errors[0].reason == std::uint8_t(Reason::Strength));\n'
 '        assert(Parse("window:1:2:s").first_errors[0].reason == std::uint8_t(Reason::Strength));\n'
 '        assert(Parse("window:1:2:s0.1:s0.2").first_errors[0].reason == std::uint8_t(Reason::Field));\n'
 '        assert(Parse("window:1:2:s0.5:7").first_errors[0].reason == std::uint8_t(Reason::Field)); // no number after s\n'
 "        assert(Parse(\"builtin\").entries[0].strength < 0.0f && Parse(\"builtin\").errors == 0);\n"
 "    }\n"
 "\n",
 ""),
],
}

ROW_LIGHT = (
    "| `BB_GLASS_LIGHT` | Lamp light through glass (r130c_glass-lamp-light, stage S1 of the glass plan). A lamp's light that crosses a "
    "registered glass entry of the kind `window`, `bottle`, `lantern` or `cabinet` (`BB_GLASS_TABLE`; the `mirror` stays opaque) is "
    "tinted by the entry's `t` tint and dimmed by its `s` strength (a number from 0 to 1; default window 0.90, cabinet 0.90, lantern "
    "0.85, bottle 0.75), instead of being blocked (a G-buffer glass draw) or passing untouched (a `BB_RT_GLASS` pane). Unset, empty "
    "or `0`: off, nothing is made, read or run (no new shader, no word, no change of any ray traced instance: the picture is bit for "
    "bit as before). `1` or `on`: on; needs `BB_GLASS_TABLE` on, ray traced lamps and a GPU that stores A2B10G10R10 (else off, with a "
    "reason line); other text: off, said. Started as `0` or `1` with the test tools' live knobs file (`BB_LIVE_KNOBS_FILE`): live "
    "(the slot runner's `set:` action; `0` is made but idle). How: a registry hit of a transmitting kind marks the draw's ray traced "
    "entry (and the same mesh drawn by the sun shadow pass); while on, its instance drops the lamp bits and takes the glass bit "
    "(0x10), and its custom index holds bit 23 and the registry entry (card slots stay below 65536). The lamp pass reuses the "
    "coloured lamp shadows (`BB_LAMP_SHADOW_COLOUR`'s colour image, 12 bytes a pixel of the pass; the lamps' own hue stays neutral "
    "unless that knob is on): a lamp ray that is free of solid geometry asks one more query for the glass on its way (at most 4 "
    "candidates, each entry once), the grey shadow ratio takes the luma of what passed and the hue goes to the coloured sums; the "
    "weaker lamps of a pixel stay grey. With `BB_RT_CARD_LAMPS=1` the leaf cards' lamp passes have no glass form: glass stays as "
    "without this knob there (counted in the log). Limits: a whole draw is tinted (a lantern's frame, a window's bars); glass "
    "within 0.18 m of a lamp neither blocks nor tints; the lamp fog shafts pass glass untinted. Cost, an estimate (not measured): "
    "off 0; on without glass in view about 0.03 to 0.1 ms (the coloured shadows), with glass near lamps 0.05 to 0.2 ms more at "
    "1080p internal; memory the colour image. GPU profile row `Lighting: point shadows (glass light)`. Log lines `Glass light "
    "(r130c): ...`: the start line and one per entry, every 600 frames the records, twins and passes, `live on|off at frame N` | off |")


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_GLASS_VIEW` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_GLASS_VIEW row is there %d times, wanted 1" % len(lines))
    return [
        ("rep", "`kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0]` separated by `;`",
         "`kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0][:sS]` separated by `;`"),
        ("rep", "mirror 0.90). The token `builtin` adds the measured entries",
         "mirror 0.90); `s` and a number from 0 to 1 is the strength of lamp light through the glass (`BB_GLASS_LIGHT`; default by "
         "kind: window and cabinet 0.90, lantern 0.85, bottle 0.75). The token `builtin` adds the measured entries"),
        ("ins", lines[0] + "\n", "", ROW_LIGHT + "\n"),
    ]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read()
    if raw == NEW[path].replace("\n", "\r\n").encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists and is not the one this patch writes" % path)


def new_lines_check(label, text):
    for n, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            raise SystemExit("text check: %s line %d holds a tab" % (label, n))
        if len(line) > 150:
            raise SystemExit("text check: %s line %d is %d columns (150 at most)" % (label, n, len(line)))


def edit_texts(eds):
    for e in eds:
        yield from (e[2] + e[3],) if e[0] == "ins" else (e[2],)


def texts_check(texts, news):
    # new files and inserted or replaced code: no tabs, at most 150 columns
    for path, text in news.items():
        new_lines_check(path, text)
    for path, eds in EDITS.items():
        if path in (CM, BS):
            continue
        for t in edit_texts(eds):
            new_lines_check(path + " (edited)", t)
    # log lines: every one this patch adds starts "Glass light (r130c)"
    for path in (TC, PC):
        for t in edit_texts(EDITS[path]):
            lines = t.split("\n")
            for i, line in enumerate(lines):
                if "printf(" in line:
                    rest = line.split("printf(", 1)[1]
                    if not rest.lstrip().startswith('"Glass light (r130c)'):
                        raise SystemExit("text check: a log line does not start with Glass light (r130c): %s" % line.strip())
    allp = "".join(t for p in (TC, PC) for t in edit_texts(EDITS[p]))
    if allp.count("Glass light (r130c)") < 6:
        raise SystemExit("text check: too few Glass light (r130c) log lines")
    # the layout numbers C++ ties to
    lay = news[HS + "glass_light_layout.h"]
    for want in ("GLASS_INDEX_BIT 0x800000u", "GLASS_ENTRY_MASK 63u", "GLASS_RAY_CAP 4u", "GLASS_WORDS 65u",
                 "GLASS_FLAG_ACTIVE 1u", "GLASS_FLAG_LAMP_HUE 2u", "GLASS_LIGHT_MASK 0x10u"):
        if lay.count("#define " + want) != 1:
            raise SystemExit("text check: glass_light_layout.h: %s" % want)
    # the shader: every edit is under GLASS (an inserted block) or the empty GLASS_HUE macro; the four GLASS builds are in CMake
    for e in EDITS[SH]:
        body = "".join(edit_texts([e]))
        if e[0] == "ins" and "GLASS" not in body:
            raise SystemExit("text check: a shader edit is not under GLASS: %r" % e[1][:60])
        if e[0] == "rep" and "GLASS_HUE" not in e[2]:
            raise SystemExit("text check: a shader replacement without GLASS_HUE: %r" % e[1][:60])
    cm = texts[CM]
    for name, d in (("colour", "COLOUR=1"), ("half_colour", "HALF=1 COLOUR=1"), ("centred_colour", "CENTRED=1 COLOUR=1"),
                    ("half_centred_colour", "HALF=1 CENTRED=1 COLOUR=1")):
        want = "add_host_shader(point_shadow_ray.comp point_shadow_ray_%s_glass_comp %s GLASS=1)" % (name, d)
        if cm.count(want) != 1:
            raise SystemExit("text check: CMakeLists.txt: %s" % want)
    if cm.count("add_executable(glass-light-test EXCLUDE_FROM_ALL ../tests/test_glass_light.cpp)") != 1 or \
            cm.count("${SHADER_SRC}/glass_light_layout.h") != 1:
        raise SystemExit("text check: CMakeLists.txt: the glass light test or the layout include")
    if texts[BS].count("tests/test_glass_light.cpp -o out/glass-light-test") != 1 or texts[BS].count("out/glass-light-test\n") != 2:
        raise SystemExit("text check: build.sh does not build and run the glass light test once")
    # the TLAS record: off is the record of before (the guards are the byte test and the bool), mask 0x10 only for glass_rec
    tc = texts[TC]
    for want in ("if (glass_light_mode != 0) { // bbport (r130c_glass-lamp-light): off: this byte test alone",
                 "const bool glass_rec_on = glass_light_mode != 0 && GlassLightFrame(card_lamps);",
                 "const bool glass_rec = glass_rec_on && entry->glass_light != 0 && mask != 0 && !card && !stale && !leave && !old_pose;",
                 ".instanceCustomIndex = glass_rec ? GlassLight::CustomIndex(u8(entry->glass_light - 1u)) : CardCustomIndex(*entry),",
                 "record.mask = u8((u32(record.mask) & ~u32(LampMask | CardLampMask)) | RtGlassMask);",
                 "if (!glass_gain && RtGlassEntry(static_cast<u8>(record.mask))) {"):
        if tc.count(want) != 1:
            raise SystemExit("text check: vk_rt_shadow.cpp: %r is there %d times" % (want[:70], tc.count(want)))
    i, j = tc.find("const bool glass_rec = "), tc.find(".instanceCustomIndex = glass_rec")
    k, m = tc.find("if (glass_rec) {\n            record.mask"), tc.find("out[built++] = record;")
    if not (0 <= i < j < k < m):
        raise SystemExit("text check: the record's glass_rec comes before the record, the mask change after out[built++]")
    if tc.count("glass_rec ") < 3 or tc.find("GlassLightNote(entry, draw);") > tc.find("if (draw.glass) { // bbport (r83_glass-water-stage1): for the log"):
        raise SystemExit("text check: GlassLightNote runs after the pane log")
    # the lamp pass: glass words directly after the 16 tuning words, the row, the selection of the four builds
    pc = texts[PC]
    for want in ("glass_mode = rt_shadow.GlassLightWanted();", "colour_mode = (tune.colour || glass_mode) && EffectPass::StorageFormat(",
                 "data.push_back(GlassLight::Flags(glass_pass, tune.colour));", "card_bind ? 64 : glass_pass ? 131 : 6,",
                 "data.size() != std::size_t(tune_at) + 16"):
        if want not in "".join(edit_texts(EDITS[PC])):
            raise SystemExit("text check: vk_point_shadow.cpp edit missing: %r" % want)
    for n in ("CENTRED_COLOUR_GLASS", "POINT_SHADOW_RAY_COLOUR_GLASS", "HALF_CENTRED_COLOUR_GLASS", "HALF_COLOUR_GLASS"):
        if pc.count("POINT_SHADOW_RAY_" + n + "_COMP") < 1 and pc.count(n + "_COMP") < 1:
            raise SystemExit("text check: vk_point_shadow.cpp does not select the %s build" % n)
    if pc.count("GlassCode(glass_mode,") != 4:
        raise SystemExit("text check: vk_point_shadow.cpp: GlassCode is used %d times, wanted 4" % pc.count("GlassCode(glass_mode,"))
    if pc.find("data[tune_at] |= LampLayersBits(") > pc.find("data.push_back(GlassLight::Flags("):
        raise SystemExit("text check: the glass words come before the tuning words are done")
    # README: one row, the default off; the other rows untouched
    rows = [l for l in texts[R].split("\n") if l.startswith("| `BB_GLASS_LIGHT` |")]
    if len(rows) != 1 or not rows[0].endswith("| off |"):
        raise SystemExit("text check: README row of BB_GLASS_LIGHT")
    if texts[R].count("[:tRRGGBB][:fF0][:sS]") != 1:
        raise SystemExit("text check: README BB_GLASS_TABLE grammar")
    # the cards stay out of it
    for path in list(EDITS) + list(NEW):
        if "vk_card_alpha" in path or "rt_cards" in path or "rasterizer" in path or "rt_shadow.comp" in path:
            raise SystemExit("text check: %s must not be touched by this patch" % path)


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R130C_ROOT)" % ROOT)
    plan = []
    for path in (SH, GR, TH, TC, PH, PC, CM, BS, TG, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    new_plan = [(path, new_state(path)) for path in NEW]
    states = {p[5] for p in plan} | {s for _, s in new_plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % p for p in new_plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    def all_checks(texts):
        texts_check(texts, NEW)

    if cmd == "check":
        if state == "applied":
            all_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            all_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        all_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        writes = [(os.path.join(ROOT, path), texts[path].replace("\n", eol).encode("utf-8")) for path, eds, raw, eol, cur, _ in plan]
        writes += [(os.path.join(ROOT, path), text.replace("\n", "\r\n").encode("utf-8")) for path, text in NEW.items()]
        for full, data in writes:
            open(full + ".r130ctmp", "wb").write(data)
        for full, data in writes:
            os.replace(full + ".r130ctmp", full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + ".r130ctmp", "wb").write(out[path])
        os.replace(full + ".r130ctmp", full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
