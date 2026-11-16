# r83_glass-water-stage1: FEATURE patch (glass, water and caustics, branch visual/glass-water).
# Window panes into the ray traced scene under an instance mask of their own, which no ray
# traces yet: the groundwork of light through windows (stage S5 of the light plan, "capture"),
# which coloured light through glass (S6), the window-shaped light on the floor (S9), glass
# reflections (S8/R6) and the sun shafts through windows all need. Off by default.
#
# Why: the owner (2026-11-15) wants glass and water reflections and caustics as part of the lamp
# ray tracing work, from the sun and every light, and window-shaped coloured light on floors. The
# surface probe of 2026-11-15 (eight places) found every window pane drawn FORWARD (one colour
# target, alpha blended, depth write on, discard), so no pane is in the ray traced scene today:
# capture variants exist only for draws with 0 or 5+ colour targets. Every later glass stage
# needs the panes in the scene first, with a mask the existing rays do not see.
#
# What (BB_RT_GLASS, environment only, read once; rt_glass.h):
# 1. unset, empty, "0" or text that names no shader pair: off. Nothing changes: the pipeline keys,
#    the SPIR-V of every default build, the TLAS records and the picture are as before.
# 2. "1": the built-in pairs (RtGlassBuiltIn: vs c6cdba2b with ps c31bd920, the warm window at
#    church-candles and the house windows at graveyard-blood; vs c6cdba2b with ps 6720ae0d, the
#    sibling at lamp-test-spot, church-puddles, graveyard-blood, dark-alley). "vs:ps,vs:ps" (hex,
#    at most 8, separators , ; or space) names the pairs instead (dream-house's e30b0480:8a6c7657
#    can be tried that way; it is not built in because the probe did not prove it is glass).
# 3. On, PipelineCache::RefreshGraphicsKey gives a forward draw of a named pair the capture
#    variant (VertexCapture) too: 1 or 2 colour targets, a depth target, one sample, clipping on,
#    plain VS stages (RtGlassTargetsFit and the conditions of the capture rule of before).
#    Rasterizer::EffectsCaptureDraw hands it to RtShadow::PrepareDraw as a solid, whole, static
#    camera pass draw (Draw::glass; one with a skeleton or a bone palette is left out).
#    PrepareDraw keeps it as its own entry (key RtGlassKey, apart from any pass's entry of the
#    same mesh) with RtGlassMask (0x10, host_shaders/rt_glass_layout.h) and no other bit; its TLAS
#    record gets RtGlassMask alone (RtGlassRecordMask) and is never a lamp card.
# 4. The rays: lamp (0x04, 0x04|0x08 with the cards), sun (0x01) and the sun fog gate (0 to 3) do
#    not see 0x10. The bounced light traced 0xff: with the knob on SSGI is made with the build
#    ssgi_gather_ray_glass_comp (GLASS_SCENE=1, mask 0xff & ~RT_GLASS_MASK), so it passes through
#    the panes as before; with the knob off the build of before (byte for byte the same SPIR-V).
#    The debug view rt_card_view.comp and the lab rt_lab.comp still trace 0xff (debug only).
# 5. Log: one once-line at the ray tracing start, "Ray tracing glass (r83): BB_RT_GLASS off ..."
#    or "... on: ..." with the pairs; on, "Ray tracing glass (r83): first window pane draw ..."
#    and then every 600 frames with pane draws "Ray tracing glass (r83): N window pane draws (T
#    triangles) in the last F frames ...".
# 6. Tests: rt-glass-test (tests/test_rt_glass.cpp, CMake and build.sh --test): the knob's text,
#    the matching, the targets, the masks against every bit the tree uses, the key, the line.
#    README: the variable's row.
#
# Cost: off: one test of a static bool per pipeline key refresh and per captured draw outside the
# G-buffer and sun shadow passes (with the knob off no forward draw has a capture pipeline), one at
# SSGI's start; no GPU work, no memory. On (NOT MEASURED): per pane draw the capture stores its
# vertices (360 indices for c31bd920) and PrepareDraw runs (a few microseconds of CPU); one BLAS
# per pane mesh, built once like any static entry (about 96 bytes a triangle); a few more TLAS
# instances; the bounce build costs what the build of before does (one constant differs). The
# first time a pane is seen in a run without its pipeline in the cache, its capture pipeline
# compiles and the pane may be missing for a moment (SkipUncompiledDraw's budget), as any new
# pipeline. Saved: nothing in this stage; the own mask keeps the later glass ray (S6) to a few
# candidates and leaves every ray of today untouched.
#
# Not changed here: what the panes do to light (nothing yet: S6), the pane shaders, the dream-house
# windows the sun shadow pass draws (e30b0480's meshes are in the sun's scene through 4aaa195a), the
# lattice cut-out (the pane goes in whole), stained glass (S9, after leaf stage 4).
#
# Files: renderer_vulkan/rt_glass.h (new), host_shaders/rt_glass_layout.h (new),
# engine/tests/test_rt_glass.cpp (new), renderer_vulkan/vk_pipeline_cache.cpp,
# vk_rasterizer_effects.cpp, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_ssgi.cpp,
# host_shaders/ssgi_gather_ray.comp, engine/gpu/CMakeLists.txt, engine/build.sh, README.md.
# It touches neither volumetric_light.comp nor vk_volumetric_light.cpp, and no gate_table line.
#
# Review (2026-11-15, adversarial reviewer): the README row now states the exact rule the code
# applies (outside the G-buffer and sun shadow passes, not "after the G-buffer"; one sample,
# clipping on, plain vertex stage, no bone palette; only while the ray traced scene is built).
# Nothing else changed against the draft.
#
# Use: cd <tree> && python -I -X utf8 r83_glass-water-stage1.py check | apply | revert (root from
# R83_ROOT, else the current directory). Files keep their line ends (CRLF in the tree); new files
# are written CRLF. Originals are kept in r83_backup/ next to this script; revert removes the new
# files (only when they are as this script writes them). Applies on the tree with r76 (.fixed) in.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r83_backup")
ROOT = os.environ.get("R83_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    H + "rt_glass_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r83_glass-water-stage1): the instance mask of a window pane's entry in the ray traced
// scene (BB_RT_GLASS; RtShadow, renderer_vulkan/rt_glass.h), shared with the shaders that must
// leave the panes out (ssgi_gather_ray.comp's GLASS_SCENE build). Plain #define lines only, as
// rt_card_layers_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_GLASS_LAYOUT_H
#define RT_GLASS_LAYOUT_H

// No ray of today traces this bit: lamps 0x04 (0x04 | 0x08 with the cards), the sun 0x01, the sun
// fog gate 0 to 3, the bounced light 0xff, which the GLASS_SCENE build narrows to leave it out.
#define RT_GLASS_MASK 0x10u

#endif
''',
    R + "rt_glass.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r83_glass-water-stage1): window panes in the ray traced scene (BB_RT_GLASS). No Vulkan
// here: tests/test_rt_glass.cpp builds this header alone and runs the code the engine runs.
//
// The game draws its window panes FORWARD, after the G-buffer: one colour target (the scene
// colour), alpha blended, depth write on, and a pixel shader that discards (the surface probe of
// 2026-11-15 at eight places). The ray traced scene takes only draws with 0 colour targets (the
// sun shadow pass) or 5 and more (the G-buffer): capture variants exist only for them
// (PipelineCache::RefreshGraphicsKey), so no pane is in the scene and lamp and sun rays pass
// every window. Light through glass (a tint, the window's shape on the floor, glass reflections)
// needs the panes in the scene first, kept apart from what today's rays hit.
//
// With BB_RT_GLASS on, a forward draw (1 or 2 colour targets, a depth target, one sample,
// clipping on, plain VS stages) of a shader pair the knob names gets the capture variant too.
// RtShadow keeps it as an entry of its own (RtGlassKey) under RtGlassMask alone, which no ray
// of today traces; the bounced light's rays are built to leave it out (GLASS_SCENE). So the
// picture stays as it is; a later stage traces the mask.

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/rt_glass_layout.h"

namespace Vulkan {

/// The instance mask of a window pane's entry, and of its TLAS record, alone.
inline constexpr std::uint8_t RtGlassMask = RT_GLASS_MASK;
static_assert(RtGlassMask != 0 && (RtGlassMask & (RtGlassMask - 1)) == 0, "one bit");

/// A pane's shader pair: the vertex and pixel shader's pgm_hash.
struct RtGlassPair {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
};

/// BB_RT_GLASS=1: the pairs the surface probe of 2026-11-15 took for window glass (likely, not
/// proven: the probe cannot tell which draw made which pixel). c6cdba2b:c31bd920 is the only
/// glass-like pair at church-candles (one draw a frame, 360 indices, a tall sRGB albedo) and draws
/// the house windows at graveyard-blood; c6cdba2b:6720ae0d is its sibling at lamp-test-spot,
/// church-puddles, graveyard-blood and dark-alley.
inline constexpr std::array<RtGlassPair, 2> RtGlassBuiltIn{{
    {0xc6cdba2bull, 0xc31bd920ull},
    {0xc6cdba2bull, 0x6720ae0dull},
}};

/// Pairs the knob's text may name.
inline constexpr std::size_t RtGlassPairsMost = 8;

struct RtGlassKnob {
    bool on = false;
    bool listed = false; ///< the pairs are the text's, not RtGlassBuiltIn
    std::uint32_t count = 0;
    std::array<RtGlassPair, RtGlassPairsMost> pairs{};
};

/// A hex digit's value, or -1.
constexpr int RtGlassHexDigit(char c) {
    return c >= '0' && c <= '9'   ? c - '0'
           : c >= 'a' && c <= 'f' ? c - 'a' + 10
           : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                  : -1;
}

/// Reads a hex number at text[at] (an optional 0x first, 1 to 16 digits) into value and moves at
/// past it; false (at and value as they were) when there is none or it has more than 16 digits.
constexpr bool RtGlassReadHex(const char* text, std::size_t& at, std::uint64_t& value) {
    std::size_t i = at;
    if (text[i] == '0' && (text[i + 1] == 'x' || text[i + 1] == 'X')) {
        i += 2;
    }
    std::size_t digits = 0;
    std::uint64_t v = 0;
    while (RtGlassHexDigit(text[i]) >= 0) {
        if (++digits > 16) {
            return false;
        }
        v = v * 16 + std::uint64_t(RtGlassHexDigit(text[i]));
        ++i;
    }
    if (digits == 0) {
        return false;
    }
    at = i;
    value = v;
    return true;
}

/// BB_RT_GLASS's text. Unset, empty or "0": off. "1": the built-in pairs. Otherwise a list of
/// "vs:ps" pairs (hex, each 1 to 16 digits, an optional 0x, neither 0), at most RtGlassPairsMost,
/// separated by ',', ';' or ' ' (leading and trailing ones too): those pairs. Anything else (a
/// malformed pair, a zero hash, more than RtGlassPairsMost pairs): off, nothing half read.
constexpr RtGlassKnob ParseRtGlass(const char* text) {
    RtGlassKnob off{};
    if (!text || text[0] == '\0' || (text[0] == '0' && text[1] == '\0')) {
        return off;
    }
    if (text[0] == '1' && text[1] == '\0') {
        RtGlassKnob knob{};
        knob.on = true;
        for (const RtGlassPair& pair : RtGlassBuiltIn) {
            knob.pairs[knob.count++] = pair;
        }
        return knob;
    }
    RtGlassKnob listed{};
    listed.listed = true;
    std::size_t at = 0;
    const auto skip = [&] {
        while (text[at] == ',' || text[at] == ';' || text[at] == ' ') {
            ++at;
        }
    };
    skip();
    while (text[at] != '\0') {
        std::uint64_t vs = 0, ps = 0;
        if (!RtGlassReadHex(text, at, vs) || text[at] != ':') {
            return off;
        }
        ++at;
        if (!RtGlassReadHex(text, at, ps) || vs == 0 || ps == 0 ||
            listed.count == RtGlassPairsMost) {
            return off;
        }
        if (text[at] != '\0' && text[at] != ',' && text[at] != ';' && text[at] != ' ') {
            return off;
        }
        listed.pairs[listed.count++] = {vs, ps};
        skip();
    }
    listed.on = listed.count != 0;
    return listed.on ? listed : off;
}

/// Whether the knob names the pair (off: never).
constexpr bool RtGlassMatches(const RtGlassKnob& knob, std::uint64_t vs, std::uint64_t ps) {
    for (std::uint32_t i = 0; knob.on && i < knob.count; ++i) {
        if (knob.pairs[i].vs == vs && knob.pairs[i].ps == ps) {
            return true;
        }
    }
    return false;
}

/// The colour targets a forward pane draw may have (bound with writes on): the scene colour,
/// and one more at most. The G-buffer (5 and more) and the shadow pass (0) have capture variants
/// of their own.
constexpr bool RtGlassTargetsFit(std::uint32_t bound) {
    return bound == 1 || bound == 2;
}

/// A pane's entry key: apart from any pass's entry of the same mesh (a sun shadow pass may draw
/// the same vertices, and its entry keeps the sun and lamp bits). Never the key itself.
inline constexpr std::uint64_t RtGlassKeySalt = 0x6a09e667f3bcc909ull;
constexpr std::uint64_t RtGlassKey(std::uint64_t key) {
    return key ^ RtGlassKeySalt;
}

/// Whether an entry's mask is a pane's.
constexpr bool RtGlassEntry(std::uint8_t entry_mask) {
    return (entry_mask & RtGlassMask) != 0;
}

/// A TLAS record's mask: RtGlassMask alone for a pane's entry, else the record of before.
constexpr std::uint8_t RtGlassRecordMask(std::uint8_t entry_mask, std::uint8_t record_mask) {
    return RtGlassEntry(entry_mask) ? RtGlassMask : record_mask;
}

/// The bounced light's instance mask in its GLASS_SCENE build (ssgi_gather_ray.comp).
inline constexpr std::uint32_t RtGlassBounceMask = 0xffu & ~std::uint32_t(RT_GLASS_MASK);

/// The pane draws since the last line (RtShadow::NoteGlassDraw).
inline constexpr std::uint64_t RtGlassWindowFrames = 600;
struct RtGlassStats {
    std::uint64_t window_start = 0; ///< 0: no pane drawn yet
    std::uint64_t draws = 0;
    std::uint64_t triangles = 0;
};

/// What a pane draw at `frame` with `triangles` says: counted, then 1 for the very first pane
/// draw (a line now, the window starts), 2 once RtGlassWindowFrames frames passed since the
/// window started (the window's line, then RtGlassWindowNext), 0 otherwise.
constexpr int RtGlassNote(RtGlassStats& stats, std::uint64_t frame, std::uint32_t triangles) {
    ++stats.draws;
    stats.triangles += triangles;
    if (stats.window_start == 0) {
        stats.window_start = frame == 0 ? 1 : frame;
        return 1;
    }
    return frame >= stats.window_start + RtGlassWindowFrames ? 2 : 0;
}

/// A new window from `frame`.
constexpr void RtGlassWindowNext(RtGlassStats& stats, std::uint64_t frame) {
    stats.window_start = frame == 0 ? 1 : frame;
    stats.draws = 0;
    stats.triangles = 0;
}

/// The knob, read once.
inline const RtGlassKnob& RtGlass() {
    static const RtGlassKnob knob = ParseRtGlass(std::getenv("BB_RT_GLASS"));
    return knob;
}

inline bool RtGlassOn() {
    return RtGlass().on;
}

inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {
    return RtGlassMatches(RtGlass(), vs, ps);
}

} // namespace Vulkan
''',
    "engine/tests/test_rt_glass.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r83_glass-water-stage1): window panes in the ray traced scene (rt_glass.h): the knob's
// text, which draws are panes, the masks against every bit the tree's rays and records use, the
// pane's entry key and the log line's window.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass.h"

using namespace Vulkan;

namespace {
// The instance mask bits RtShadow sets today (vk_rt_shadow.cpp: ShadowMask, CameraMask, LampMask,
// CardLampMask) and the masks today's rays trace.
constexpr std::uint8_t ShadowMask = 1, CameraMask = 2, LampMask = 4, CardLampMask = 8;
constexpr std::uint8_t TodayBits = ShadowMask | CameraMask | LampMask | CardLampMask;

bool Same(const RtGlassKnob& a, const RtGlassKnob& b) {
    if (a.on != b.on || a.listed != b.listed || a.count != b.count) {
        return false;
    }
    for (std::uint32_t i = 0; i < a.count; ++i) {
        if (a.pairs[i].vs != b.pairs[i].vs || a.pairs[i].ps != b.pairs[i].ps) {
            return false;
        }
    }
    return true;
}
} // namespace

int main() {
    // The mask: one bit, none of today's, so no ray of today hits a pane.
    static_assert(RtGlassMask == 0x10 && (RtGlassMask & TodayBits) == 0);
    static_assert((RtGlassMask & ShadowMask) == 0 && (RtGlassMask & LampMask) == 0);
    static_assert((RtGlassMask & (LampMask | CardLampMask)) == 0); // the lamp rays with cards
    for (std::uint32_t gate = 0; gate <= 3; ++gate) {               // the sun fog gate's masks
        assert((RtGlassMask & gate) == 0);
    }
    // The bounced light's GLASS_SCENE build sees every bit but the pane's.
    static_assert(RtGlassBounceMask == 0xefu && (RtGlassBounceMask & RtGlassMask) == 0);
    static_assert((RtGlassBounceMask & std::uint32_t(TodayBits)) == std::uint32_t(TodayBits));

    // Off.
    assert(!ParseRtGlass(nullptr).on && !ParseRtGlass("").on && !ParseRtGlass("0").on);
    static_assert(!ParseRtGlass("0").on && ParseRtGlass("0").count == 0);
    for (const char* text : {"2", "on", "yes", "1 ", " 1", "10", "c6cdba2b", "c6cdba2b:", ":c31bd920",
                             "c6cdba2b:c31bd920x", "c6cdba2b::c31bd920", "0:c31bd920", "c6cdba2b:0",
                             "c6cdba2b:c31bd920,zz:1", "11111111111111111:1", "g:1"}) {
        const RtGlassKnob knob = ParseRtGlass(text);
        assert(!knob.on && knob.count == 0);
    }
    // "1": the built-in pairs.
    constexpr RtGlassKnob builtin = ParseRtGlass("1");
    static_assert(builtin.on && !builtin.listed && builtin.count == RtGlassBuiltIn.size());
    static_assert(RtGlassMatches(builtin, 0xc6cdba2b, 0xc31bd920));
    static_assert(RtGlassMatches(builtin, 0xc6cdba2b, 0x6720ae0d));
    static_assert(!RtGlassMatches(builtin, 0xc31bd920, 0xc6cdba2b)); // the order counts
    static_assert(!RtGlassMatches(builtin, 0x9253a878, 0xe3021062)); // the water is not a pane
    static_assert(!RtGlassMatches(builtin, 0xe30b0480, 0x8a6c7657)); // not proven: only listed
    static_assert(!RtGlassMatches(RtGlassKnob{}, 0xc6cdba2b, 0xc31bd920));
    // A list.
    {
        const RtGlassKnob knob = ParseRtGlass("e30b0480:8a6c7657, 0xC6CDBA2B:0xc31bd920;1:2 ");
        assert(knob.on && knob.listed && knob.count == 3);
        assert(RtGlassMatches(knob, 0xe30b0480, 0x8a6c7657));
        assert(RtGlassMatches(knob, 0xc6cdba2b, 0xc31bd920));
        assert(RtGlassMatches(knob, 1, 2));
        assert(!RtGlassMatches(knob, 0xc6cdba2b, 0x6720ae0d)); // the list replaces the table
        assert(Same(ParseRtGlass(",e30b0480:8a6c7657"), ParseRtGlass("e30b0480:8a6c7657")));
        assert(RtGlassMatches(ParseRtGlass("ffffffffffffffff:1"), ~std::uint64_t(0), 1));
    }
    // At most RtGlassPairsMost pairs; one more turns it off.
    assert(ParseRtGlass("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8").count == RtGlassPairsMost);
    assert(!ParseRtGlass("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9").on);
    assert(!ParseRtGlass(" , ;").on); // separators alone name nothing

    // The targets of a forward pane draw.
    static_assert(!RtGlassTargetsFit(0) && RtGlassTargetsFit(1) && RtGlassTargetsFit(2));
    for (std::uint32_t bound = 3; bound <= 8; ++bound) {
        assert(!RtGlassTargetsFit(bound));
    }

    // The entry key is never the key of the pass entry of the same mesh, and goes back.
    for (std::uint64_t key : {std::uint64_t(0), std::uint64_t(1), RtGlassKeySalt, ~std::uint64_t(0),
                              std::uint64_t(0x123456789abcdefull)}) {
        assert(RtGlassKey(key) != key && RtGlassKey(RtGlassKey(key)) == key);
    }

    // A record: a pane alone under its mask (never a lamp, sun, camera or card bit); every other
    // entry's record exactly as before.
    for (std::uint32_t entry = 0; entry < 256; ++entry) {
        for (std::uint32_t record = 0; record < 256; ++record) {
            const std::uint8_t got = RtGlassRecordMask(std::uint8_t(entry), std::uint8_t(record));
            if ((entry & RtGlassMask) != 0) {
                assert(got == RtGlassMask && RtGlassEntry(std::uint8_t(entry)));
            } else {
                assert(std::uint32_t(got) == record && !RtGlassEntry(std::uint8_t(entry)));
            }
        }
    }
    static_assert(RtGlassRecordMask(RtGlassMask, ShadowMask | LampMask) == RtGlassMask);
    static_assert(RtGlassRecordMask(CameraMask, CameraMask | LampMask) == (CameraMask | LampMask));

    // The line: the first pane draw says one at once; then one when 600 frames passed.
    {
        RtGlassStats stats{};
        assert(RtGlassNote(stats, 100, 120) == 1 && stats.window_start == 100 && stats.draws == 1);
        RtGlassWindowNext(stats, 100);
        assert(stats.draws == 0 && stats.triangles == 0);
        assert(RtGlassNote(stats, 101, 120) == 0 && RtGlassNote(stats, 699, 30) == 0);
        assert(stats.draws == 2 && stats.triangles == 150);
        assert(RtGlassNote(stats, 700, 10) == 2 && stats.draws == 3 && stats.triangles == 160);
        RtGlassWindowNext(stats, 700);
        assert(RtGlassNote(stats, 1299, 1) == 0 && RtGlassNote(stats, 1300, 1) == 2);
        RtGlassStats at_zero{};
        assert(RtGlassNote(at_zero, 0, 1) == 1 && at_zero.window_start == 1); // 0 means "not yet"
    }

    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\n",
                unsigned(RtGlassMask), unsigned(RtGlassBounceMask), RtGlassBuiltIn.size(),
                RtGlassPairsMost);
    return 0;
}
''',
}

EDITS = {
    R + "vk_pipeline_cache.cpp": [
        (r'''#include "video_core/renderer_vulkan/motion_history.h"
''', r'''#include "video_core/renderer_vulkan/motion_history.h"
#include "video_core/renderer_vulkan/rt_glass.h" // bbport (r83_glass-water-stage1)
'''),
        (r'''    // Compile and bind shader stages
    if (!RefreshGraphicsStages(sel)) {
        return false;
    }
    if (motion_possible) {
''', r'''    // Compile and bind shader stages
    if (!RefreshGraphicsStages(sel)) {
        return false;
    }
    // bbport (r83_glass-water-stage1): BB_RT_GLASS (rt_glass.h, read once; off by default): a
    // forward draw of a shader pair the knob names (a window pane: 1 or 2 colour targets, a depth
    // target, one sample, clipping on, plain VS stages, as the capture rule above asks of the
    // passes) gets the capture variant too, so RtShadow can keep the pane under RtGlassMask,
    // which no ray traces yet. The stages are bound again with it, as for motion below. Off: one
    // test of a static bool, the key as before.
    if (position_capture && !sel.capture && RtGlassOn()) {
        u32 bound = 0;
        for (s32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS && !skip_cb_binding; ++cb) {
            bound += (regs.color_buffers[cb] && regs.color_target_mask.GetMask(cb)) ? 1 : 0;
        }
        const auto* glass_vs = sel.infos[static_cast<u32>(Shader::SwStage::Vertex)];
        const auto* glass_fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
        if (RtGlassTargetsFit(bound) && regs.depth_buffer.DepthValid() &&
            regs.depth_buffer.NumSamples() == 1 && !regs.IsClipDisabled() &&
            regs.stage_enable.raw == AmdGpu::ShaderStageEnable::VgtStages::Vs && glass_vs &&
            glass_fs && RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash)) {
            sel.capture = true;
            if (!RefreshGraphicsStages(sel)) {
                return false;
            }
        }
    }
    if (motion_possible) {
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''    BbSections::Scope prepare_scope{BbSections::RtPrepare};
    const u32 param = rt_shadow->PrepareDraw(draw);
''', r'''    // bbport (r83_glass-water-stage1): BB_RT_GLASS (rt_glass.h): a forward draw of a pair the knob
    // names has a capture pipeline only through it (PipelineCache::RefreshGraphicsKey). It goes
    // to PrepareDraw as a window pane (Draw::glass): drawn with the camera, solid and whole (its
    // blend and discard are the pane's look, not holes), static: one with a skeleton or a bone
    // palette is left out (neither pass, PrepareDraw takes nothing). Off: one test of a static bool.
    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {
        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned && draw.palette == 0) {
            draw.glass = true;
            draw.camera_pass = true;
            draw.solid = true;
            draw.alpha = false;
        }
    }
    BbSections::Scope prepare_scope{BbSections::RtPrepare};
    const u32 param = rt_shadow->PrepareDraw(draw);
'''),
    ],
    R + "vk_rt_shadow.h": [
        (r'''#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
''', r'''#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/rt_glass.h"       // bbport (r83_glass-water-stage1)
'''),
        (r'''        const CardDraw* card = nullptr;
    };
    u32 PrepareDraw(const Draw& draw);
''', r'''        const CardDraw* card = nullptr;
        // bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's forward draw, given as a
        // solid camera pass draw without cut-out (EffectsCaptureDraw); its entry is its own
        // (RtGlassKey) and takes RtGlassMask alone
        bool glass = false;
    };
    u32 PrepareDraw(const Draw& draw);
'''),
        (r'''    u64 frame = 1;
    u32 params_used = 0;
''', r'''    u64 frame = 1;
    // bbport (r83_glass-water-stage1): the window pane draws for the log (NoteGlassDraw)
    RtGlassStats glass_stats{};
    void NoteGlassDraw(const Entry& entry);
    u32 params_used = 0;
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''        std::printf("Ray tracing: on, sun %u rays a pixel, lamps and bounced light\n", rays);
''', r'''        std::printf("Ray tracing: on, sun %u rays a pixel, lamps and bounced light\n", rays);
        // bbport (r83_glass-water-stage1): BB_RT_GLASS's state (rt_glass.h), said once
        static_assert((RtGlassMask & (ShadowMask | CameraMask | LampMask | CardLampMask)) == 0);
        const RtGlassKnob& glass = RtGlass();
        if (!glass.on) {
            const char* text = std::getenv("BB_RT_GLASS");
            const bool named = text && text[0] && !(text[0] == '0' && text[1] == '\0');
            std::printf("Ray tracing glass (r83): BB_RT_GLASS off%s%.80s%s: window panes stay out of "
                        "the ray traced scene, as before\n",
                        named ? " (its text \"" : "", named ? text : "",
                        named ? "\" names no shader pair vs:ps, hex, at most 8)" : "");
        } else {
            char list[RtGlassPairsMost * 36 + 1] = {};
            std::size_t used = 0;
            for (u32 i = 0; i < glass.count && used < sizeof(list); ++i) {
                const int n = std::snprintf(list + used, sizeof(list) - used, "%s%llx:%llx",
                                            i ? "," : "",
                                            static_cast<unsigned long long>(glass.pairs[i].vs),
                                            static_cast<unsigned long long>(glass.pairs[i].ps));
                used += n > 0 ? std::size_t(n) : 0;
            }
            std::printf("Ray tracing glass (r83): BB_RT_GLASS on, %s pairs %s: their forward draws "
                        "go into the ray traced scene as window panes under instance mask 0x%x "
                        "alone, which no ray traces yet; bounced light leaves it out (the picture "
                        "is as before)\n",
                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));
        }
'''),
        (r'''u32 RtShadow::PrepareDraw(const Draw& draw) {
''', r'''// bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's draw reached its entry
// (RtGlassMask alone). The first pane draw of the run is said at once; then every
// RtGlassWindowFrames frames in which panes drew, one line with their draws and triangles.
void RtShadow::NoteGlassDraw(const Entry& entry) {
    const int say = RtGlassNote(glass_stats, frame, entry.triangles);
    if (say == 1) {
        std::printf("Ray tracing glass (r83): first window pane draw at frame %llu: %u triangles, "
                    "%u instances, instance mask 0x%x alone\n",
                    static_cast<unsigned long long>(frame), entry.triangles, entry.instances,
                    unsigned(RtGlassMask));
    } else if (say == 2) {
        std::printf("Ray tracing glass (r83): %llu window pane draws (%llu triangles) in the last "
                    "%llu frames; instance mask 0x%x alone, which no ray traces yet\n",
                    static_cast<unsigned long long>(glass_stats.draws),
                    static_cast<unsigned long long>(glass_stats.triangles),
                    static_cast<unsigned long long>(frame - glass_stats.window_start),
                    unsigned(RtGlassMask));
    }
    if (say != 0) {
        RtGlassWindowNext(glass_stats, frame);
    }
}

u32 RtShadow::PrepareDraw(const Draw& draw) {
'''),
        (r'''    const u8 mask = draw.camera_pass ? CameraMask : ShadowMask;
    u64 key;
''', r'''    // bbport (r83_glass-water-stage1): a window pane's draw (BB_RT_GLASS, Draw::glass) has an
    // entry of its own (RtGlassKey below) under RtGlassMask alone
    const u8 mask = draw.glass ? RtGlassMask : draw.camera_pass ? CameraMask : ShadowMask;
    u64 key;
'''),
        (r'''        key = XXH3_64bits_withSeed(parts.data(), sizeof(parts), key);
    }

    // bbport (r14_cascade_rt): a shadow pass draw's copies are known by its cascade, not by the
''', r'''        key = XXH3_64bits_withSeed(parts.data(), sizeof(parts), key);
    }
    if (draw.glass) { // bbport (r83_glass-water-stage1): apart from a pass's entry of the mesh
        key = RtGlassKey(key);
    }

    // bbport (r14_cascade_rt): a shadow pass draw's copies are known by its cascade, not by the
'''),
        (r'''    Entry& entry = *r19_entry;
    if (probe_on) {''', r'''    Entry& entry = *r19_entry;
    if (draw.glass) { // bbport (r83_glass-water-stage1): for the log
        NoteGlassDraw(entry);
    }
    if (probe_on) {'''),
        (r'''        const bool lamp_card = card_lamps && card && !stale && !leave && !old_pose && mask != 0 &&
''', r'''        // bbport (r83_glass-water-stage1): a window pane (RtGlassMask) is never a lamp card
        const bool lamp_card = card_lamps && card && !stale && !leave && !old_pose && mask != 0 &&
                               !RtGlassEntry(mask) &&
'''),
        (r'''            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask) |
                       (lamp_card ? CardLampMask : 0)), // bbport (r63_leaf-stage4)
''', r'''            // bbport (r83_glass-water-stage1): a window pane's record: RtGlassMask alone
            .mask = RtGlassRecordMask(mask, u8(mask | (card || stale || leave || old_pose ? 0 : LampMask) |
                                               (lamp_card ? CardLampMask : 0))), // bbport (r63_leaf-stage4)
'''),
    ],
    R + "vk_ssgi.cpp": [
        (r'''                    SSGI_GATHER_RAY_COMP, "Ray traced bounce")) &&
''', r'''                    // bbport (r83_glass-water-stage1): BB_RT_GLASS on: the build whose rays leave
                    // the window panes' mask out (RtGlassBounceMask); off: the build of before
                    RtGlassOn() ? std::span<const u32>{SSGI_GATHER_RAY_GLASS_COMP}
                                : std::span<const u32>{SSGI_GATHER_RAY_COMP},
                    "Ray traced bounce")) &&
'''),
        (r'''#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
''', r'''#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
#include "video_core/host_shaders/ssgi_gather_ray_glass_comp.h" // bbport (r83_glass-water-stage1)
'''),
    ],
    H + "ssgi_gather_ray.comp": [
        (r'''#extension GL_EXT_ray_query : require
''', r'''#extension GL_EXT_ray_query : require
#ifdef GLASS_SCENE
// bbport (r83_glass-water-stage1): BB_RT_GLASS on: window panes are in the scene under their own
// instance mask (RT_GLASS_MASK); the bounced light passes through them, as without the knob
#include "rt_glass_layout.h"
#endif
'''),
        (r'''        rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, 0xffu, origin, reach * 0.5, dir, REACH);
''', r'''#ifdef GLASS_SCENE
        rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, 0xffu & ~RT_GLASS_MASK, origin, reach * 0.5, dir, REACH);
#else
        rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, 0xffu, origin, reach * 0.5, dir, REACH);
#endif
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''    if (FILENAME MATCHES "^ssgi")
        list(APPEND INCLUDES ${SHADER_SRC}/ssgi_common.glsl)
    endif()
''', r'''    if (FILENAME MATCHES "^ssgi")
        list(APPEND INCLUDES ${SHADER_SRC}/ssgi_common.glsl)
        # bbport (r83_glass-water-stage1): the gather's GLASS_SCENE build includes the panes' mask
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h)
    endif()
'''),
        (r'''add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
''', r'''add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
# bbport (r83_glass-water-stage1): BB_RT_GLASS on: the bounced light's rays leave the window panes'
# mask out (rt_glass_layout.h); the build above is unchanged.
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_glass_comp GLASS_SCENE=1)
'''),
        (r'''add_executable(rt-still-check-test EXCLUDE_FROM_ALL ../tests/test_rt_still_check.cpp)
target_compile_options(rt-still-check-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-still-check-test PRIVATE ..)
''', r'''add_executable(rt-still-check-test EXCLUDE_FROM_ALL ../tests/test_rt_still_check.cpp)
target_compile_options(rt-still-check-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-still-check-test PRIVATE ..)
# bbport (r83_glass-water-stage1): the window panes' knob, masks and key (rt_glass.h)
add_executable(rt-glass-test EXCLUDE_FROM_ALL ../tests/test_rt_glass.cpp)
target_compile_options(rt-glass-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-glass-test PRIVATE ..)
'''),
    ],
    "engine/build.sh": [
        (r'''    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_still_check.cpp -o out/rt-still-check-test
    out/rt-still-check-test
''', r'''    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_still_check.cpp -o out/rt-still-check-test
    out/rt-still-check-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_glass.cpp -o out/rt-glass-test
    out/rt-glass-test
'''),
    ],
    "README.md": [
        (r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |
''', r'''| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |
| `BB_RT_GLASS` | Groundwork for light through windows, while the ray traced scene is built (ray tracing on with the ray traced sun, lamp shadows or bounced light): `1` puts the draws of two shader pairs the engine takes for window panes into the ray traced scene, under an instance mask of their own that no ray traces yet; `vs:ps,vs:ps` (hex shader hashes, at most 8, separated by `,`, `;` or spaces) names the pairs instead. A draw of such a pair is taken only outside the G-buffer and sun shadow passes, with one or two colour targets, a depth target, one sample, clipping on, a plain vertex stage, and without a skeleton or a bone palette. Bounced light leaves the panes out, so the picture stays the same, except that the first time such a draw is seen without its pipeline in the cache, it can be missing for a moment while that pipeline compiles. Any other text is off | off |
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    R + "vk_pipeline_cache.cpp": [("RtGlassOn()", 1), ("sel.capture = true;", 1),
                                  ('#include "video_core/renderer_vulkan/rt_glass.h"', 1),
                                  ("RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash)", 1)],
    R + "vk_rasterizer_effects.cpp": [("draw.glass = true;", 1), ("RtGlassOn()", 1)],
    R + "vk_rt_shadow.h": [("bool glass = false;", 1), ("RtGlassStats glass_stats{};", 1),
                           ("void NoteGlassDraw(const Entry& entry);", 1)],
    R + "vk_rt_shadow.cpp": [("const u8 mask = draw.glass ? RtGlassMask : draw.camera_pass ? CameraMask : ShadowMask;", 1),
                             ("key = RtGlassKey(key);", 1), ("NoteGlassDraw(entry);", 1),
                             ("void RtShadow::NoteGlassDraw(const Entry& entry) {", 1),
                             ("!RtGlassEntry(mask) &&", 1), (".mask = RtGlassRecordMask(mask, ", 1),
                             ('std::getenv("BB_RT_GLASS")', 1),
                             ("gate_table.push_back({entry->base, entry->triangles, static_cast<u8>(record.mask)});", 1)],
    R + "vk_ssgi.cpp": [("SSGI_GATHER_RAY_GLASS_COMP", 1), ("std::span<const u32>{SSGI_GATHER_RAY_COMP}", 1)],
    H + "ssgi_gather_ray.comp": [("#ifdef GLASS_SCENE", 2), ("0xffu & ~RT_GLASS_MASK", 1),
                                 ("gl_RayFlagsOpaqueEXT, 0xffu, origin", 1)],
    H + "rt_glass_layout.h": [("#define RT_GLASS_MASK 0x10u", 1)],
    R + "rt_glass.h": [('std::getenv("BB_RT_GLASS")', 1), ("RT_GLASS_MASK", 2),
                       ('#include "../host_shaders/rt_glass_layout.h"', 1)],
    "engine/gpu/CMakeLists.txt": [("ssgi_gather_ray_glass_comp GLASS_SCENE=1", 1),
                                  ("${SHADER_SRC}/rt_glass_layout.h", 1),
                                  ("add_executable(rt-glass-test EXCLUDE_FROM_ALL ../tests/test_rt_glass.cpp)", 1)],
    "engine/build.sh": [("tests/test_rt_glass.cpp -o out/rt-glass-test", 1)],
    "engine/tests/test_rt_glass.cpp": [('#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass.h"', 1)],
    "README.md": [("| `BB_RT_GLASS` |", 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    R + "vk_pipeline_cache.cpp": ["    if (!RefreshGraphicsStages(sel)) {", "RtGlassOn()",
                                  "    if (motion_possible) {", "    if (sel.capture) {"],
    R + "vk_rasterizer_effects.cpp": ["void Rasterizer::EffectsCaptureDraw(", "draw.glass = true;",
                                      "const u32 param = rt_shadow->PrepareDraw(draw);"],
    R + "vk_rt_shadow.cpp": ["void RtShadow::NoteGlassDraw(", "u32 RtShadow::PrepareDraw(const Draw& draw) {",
                             "const u8 mask = draw.glass", "key = RtGlassKey(key);",
                             "u32 camera_index = cascade < 4", "NoteGlassDraw(entry);",
                             "!RtGlassEntry(mask) &&", ".mask = RtGlassRecordMask(mask, ",
                             "gate_table.push_back("],
    H + "ssgi_gather_ray.comp": ["#extension GL_EXT_ray_query : require", '#include "rt_glass_layout.h"',
                                 "0xffu & ~RT_GLASS_MASK", "gl_RayFlagsOpaqueEXT, 0xffu, origin"],
}

TMP = ".r83tmp"


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    # What this patch writes is ASCII.
    for path, text in list(NEW.items()) + [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n") for ch in text):
            raise SystemExit("text check: %s: what this patch writes is not plain ASCII" % path)
    # The C escapes kept their backslash on the way into this script.
    rt = texts[R + "vk_rt_shadow.cpp"]
    if "as before\\n\",\n" not in rt or "alone\\n\",\n" not in rt or \
            "(the picture \"\n                        \"is as before)\\n\",\n" not in rt:
        raise SystemExit("text check: vk_rt_shadow.cpp: a C escape lost its backslash")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R83_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.isdir(os.path.dirname(full)):
            raise SystemExit("no such folder: %s" % os.path.dirname(path))
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == text.replace("\n", "\r\n").encode("utf-8"):
            state = "applied"
        else:
            raise SystemExit("%s is there but not as this script writes it" % path)
        plan.append((path, None, None, "\r\n", None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def patched():
        texts = {}
        for path, edits, raw, eol, cur, _ in plan:
            if edits is None:
                texts[path] = NEW[path]
                continue
            if state == "clean":
                for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
        return texts

    if cmd == "check":
        text_checks(patched())
        if state == "applied":
            print("applied (text checks pass)")
        else:
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(EDITS), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts = patched()
        text_checks(texts)
        outs = []
        for path, edits, raw, eol, cur, _ in plan:
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        if edits is None:
            os.remove(os.path.join(ROOT, path))
            continue
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")


main()
