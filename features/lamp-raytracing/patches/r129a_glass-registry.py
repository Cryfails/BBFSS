# r129a_glass-registry: FEATURE patch (lane LRT, stage S0 of <queue>/LRT/inflight/glass_plan_v2.md). Owner goal LRT-G055
# (2026-11-16 ~11:30): "What is the glass glinting and why do we have it? I thought for glass I wanted it to behave like glass,
# where light passed through it, it did different color caustics from colored glass, mirrors would correctly reflected the work,
# glass would reflect the world etc". The glint was a stand-in; the real glass work (S1 lamp light through glass with a tint per
# pane, S3/S6 mirror and glass tags) needs one thing first: to KNOW which draws are glass, of what kind, with what tint and F0, and
# for the owner to see it ("yes, that is the glass"). This patch is that: a GLASS REGISTRY and a DEBUG VIEW. No light change.
#
# What changes (everything OFF by default; nothing changes with the knob off):
#  - BB_GLASS_TABLE (read once): entries "kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0]" separated by ';' (kinds window,
#    mirror, bottle, lantern, cabinet; vs/ps hex pgm_hash; indexcount 0 or '*' = any; firstindex '*' = any, 0 is a first index;
#    t = tint default FFFFFF; f = Fresnel F0 0..1, default 0.04, mirror 0.90). The token "builtin" adds the measured entries:
#    the dream house mirror pair 9da6aacb:ca7226ec with index count 24 (NO first index: it may change between loads) and the arch
#    window 97f2d384:2390c887 with index count 324. Unset, empty, "0" or "off": off and never the built-in table. A bad entry is
#    skipped and said (the others stay); at most 64 entries (S1's tint table size).
#  - Every direct draw (Rasterizer::DrawRecord, RT on or off, right before EffectsBeforeResources) looks its (vs, ps, index
#    count, first index) up: a hit is counted per entry (relaxed atomics), put into DrawContext::glass_hit (entry index + 1) and
#    copied into the new RtShadow::Draw::glass_entry for S1 to read (nothing reads it in this patch).
#  - BB_GLASS_VIEW=1 (live with the test tools' live knobs file: the slot runner's set:/unset: actions work; else read once):
#    the registry's hit draws painted over the scene (window cyan, bottle orange, mirror magenta, lantern/cabinet yellow), by
#    the same SNAPSHOT / MARK / SHOW idea as the blood sheen (compare target 0 and depth before and after a hit draw, so it
#    shows exactly the pixels that draw wrote). New compute shader host_shaders/glass_view.comp (four builds).
#  - Log lines "Glass registry (r129a): ..." (the table at the start, per entry, per bad entry, every 600 frames the hits per
#    entry) and "Glass view (r129a): ..." (view on/off at frame N, every 600 frames the passes and the skip reasons).
#
# Not changed: BB_RT_GLASS, instanceCustomIndex (S1 splits it), vk_rt_shadow.cpp, rt_glass*.h, the glint, any existing shader.
# GPU profile row: key 129 ("Lighting: glass view"). EffectPass::Mark rows are keys (0x4C490000 | key), not table positions; in use:
# 6, 10-18, 51, 61-64, 80, 81, 86, 95, 97, 99, 100, 105, 107, 111, 117, 119. 129 is free.
#
# Cost. OFF (BB_GLASS_TABLE unset, empty, 0 or off): no GlassRegistry and no GlassView is made; per direct draw ONE null pointer
# test (`if (glass_registry)` in DrawRecord) and, in EffectsCaptureDraw's initializer, a plain load of DrawContext::glass_hit
# (never written, so 0) stored into RtShadow::Draw::glass_entry; per G-buffer lighting and per frame one null test each. No
# lookup, allocation, pipeline, image, buffer, pass or object; no existing shader changes, so every existing SPIR-V is
# byte-identical. ON, view off: per direct draw a pair hash and a probe of a 128-slot table, then a scan of the pair's 1-3
# entries, about 10-30 ns (estimate), 0.02-0.1 ms CPU a frame at 2000-4000 draws; no GPU work, the picture is unchanged. VIEW
# ON: about 0.1 ms per hit draw at 1080p internal (a SNAPSHOT and a MARK pass over the scene; the plan's 0.02 ms is not
# reachable with a per-draw compare), at most 8 hit draws a frame, plus about 0.05 ms per G-buffer lighting with a G-buffer hit
# (SHOW); memory two R32UI images of the scene size (16.6 MB at 1920x1080, 66 MB at 3840x2160). All estimates, not measured.
#
# Files. New: engine/gpu/shadps4/video_core/renderer_vulkan/glass_registry.h (rules, parse, lookup; no Vulkan; static_asserts),
# vk_glass_view.h, vk_glass_view.cpp (GlassRegistry, Rasterizer::GlassRegistryDraw, GlassView), host_shaders/glass_view.comp,
# host_shaders/glass_view_layout.h, engine/tests/test_glass_registry.cpp. Edited: vk_rasterizer.h, vk_rasterizer.cpp,
# vk_rasterizer_effects.cpp, vk_rt_shadow.h, engine/gpu/CMakeLists.txt (four shader builds, the layout include, the test
# target), engine/build.sh (--test), engine/tests/test_effect_pipelines.cpp (the four passes), README.md (one row per knob).
# (All .cpp under shadps4/video_core are globbed by CMake: no source list edit.)
#
# Differences from the draft: a fourth shader build GLASS_PAINT (forward hit draws are painted in place; the draft's three builds
# could not bind the scene colour as storage without a second image type); a MARK still pending at the frame end is dropped, not
# recorded (the hit draw was the frame's last direct draw: rare, and its image ids may be stale at the display pass);
# firstindex 0 is a first index (only '*' is "any"; indexcount 0 or '*' is any).
#
# Review fix (.fixed): the MARK and SHOW look the hit draw's target 0 and depth up by id and image_uid (TryGetImage) first:
# the MARK runs at the next draw's hook, after that draw's PrepareRenderState may have freed them.
#
# Not verified (no full build, no game run, no GPU; the unit test and the shader compile are the only checks):
#  - That the full engine build compiles and links (not run). Checked: glass_registry.h by its unit test (clang++ -std=c++20
#    -Wall -Wextra -Werror); the four shader builds with glslangValidator --target-env vulkan1.3 and spirv-val; vk_glass_view.cpp,
#    vk_rasterizer.cpp, vk_rasterizer_effects.cpp and test_effect_pipelines.cpp with clang++ -fsyntax-only on the patched copy,
#    with stand-in headers for magic_enum and the other generated shader headers (no error came from this patch's lines).
#  - That the GPU passes run without a validation error; the view's picture (mirror magenta, arch window cyan, nothing else).
#  - That a MARK recorded at the NEXT registry hook (not right after the draw, as BloodSheen::AfterDraw does) sees the draw's
#    pixels before another pass changes the target; the draft chose this to keep the per-draw cost to one null test.
#  - That the SHOW depth rule ((depth bits & ~7) equal to the tag's) keeps a hunter in front of the mirror untinted.
#  - That forward hit draws have RGBA16F scene-size target 0 with storage use (else they are counted as "shape" and left out).
#  - The costs above; that the built-in entries are hit in ~600/600 frames; that the mirror's first index is not needed.
#  - That the live knob BB_GLASS_VIEW switches the view in a game (needs BB_LIVE_KNOBS_FILE and the test tools' header).
#
# Use: python -I -X utf8 r129a_glass-registry.py check | apply | revert
# Root: R129A_ROOT, else <tree>; a root without engine/gpu is refused. Line ends kept (CRLF or LF per file; a mixed file is
# refused; new files take CRLF as the tree has). Each edit refuses unless its anchor is found exactly once; a mixed applied/clean
# state is refused; text checks run on the result before anything is written. apply backs the originals up in r129a_backup
# next to this script and writes through a temp file and a rename; revert takes out exactly what apply inserted and removes the
# new files.
import os, sys

ROOT = os.environ.get("R129A_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r129a_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
RE = RV + "vk_rasterizer_effects.cpp"
TH = RV + "vk_rt_shadow.h"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
TP = "engine/tests/test_effect_pipelines.cpp"
R = "README.md"

# New files: path -> text (LF here; written with CRLF).
NEW = {
RV + "glass_registry.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r129a_glass-registry): the glass registry (stage S0 of the glass plan). BB_GLASS_TABLE names which draws are glass:
// entries "kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0]" separated by ';' (kinds window, mirror, bottle, lantern,
// cabinet; vs/ps hex pgm_hash, 1-16 digits, optional 0x; indexcount decimal, 0 or '*' = any; firstindex decimal or '*' = any,
// 0 is the first index 0; t = tint, default FFFFFF; f = Fresnel F0 0..1, default 0.04, mirror 0.90). The token "builtin" adds
// the measured entries (dream house mirror pair 9da6aacb:ca7226ec with 24 indices, arch window 97f2d384:2390c887 with 324
// indices; no first index, it may change between loads). Unset, empty, "0" or "off": off, and never the built-in table. A bad
// entry is skipped and said; at most 64 entries.
// BB_GLASS_VIEW=1 (live with the test tools' live knobs file, else read once): registry hits painted over the scene (window
// cyan, bottle orange, mirror magenta, lantern and cabinet yellow). Needs BB_GLASS_TABLE.
// Off (BB_GLASS_TABLE unset): the rasterizer makes no GlassRegistry and no GlassView: per draw one null pointer test
// (DrawRecord) and one byte copy into RtShadow::Draw (always 0, a plain store); per G-buffer lighting and per frame one null
// test. No lookup, allocation, pipeline, image, buffer or pass; no existing shader changes (glass_view.comp is new), so every
// existing SPIR-V is byte-identical.
// On, view off: per direct draw a pair hash and a probe of a 128-slot table, then a scan of the pair's entries (1-3):
// about 10-30 ns a draw, 0.02-0.1 ms CPU a frame at 2000-4000 draws; no GPU work, the picture is unchanged.
// View on: per hit draw (at most 8 a frame) a SNAPSHOT and a MARK pass over the scene (~0.05 ms each at 1920x1080 internal),
// one SHOW pass per G-buffer lighting with a G-buffer hit; two R32UI images of the scene size (16.6 MB at 1920x1080, 66 MB at
// 3840x2160). GPU profile row "Lighting: glass view". The tags read at SHOW need the upscaler (EffectsBlendedScene).
// No Vulkan here: tests/test_glass_registry.cpp builds this header alone and runs the code the engine runs; the static_asserts
// below are tests too.

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/glass_view_layout.h"
#include "rt_glass.h"

namespace Vulkan::GlassRegistryRules {

using u8 = std::uint8_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;

enum class Kind : u8 { None = 0, Window = 1, Mirror = 2, Bottle = 3, Lantern = 4, Cabinet = 5 };
static_assert(u32(Kind::None) == GLASS_VIEW_KIND_NONE && u32(Kind::Window) == GLASS_VIEW_KIND_WINDOW &&
              u32(Kind::Mirror) == GLASS_VIEW_KIND_MIRROR && u32(Kind::Bottle) == GLASS_VIEW_KIND_BOTTLE &&
              u32(Kind::Lantern) == GLASS_VIEW_KIND_LANTERN && u32(Kind::Cabinet) == GLASS_VIEW_KIND_CABINET);

enum class Reason : u8 { Kind, Vs, Ps, Count, First, Tint, F0, Field, TooMany, Duplicate };

inline constexpr u32 MaxEntries = 64; // S1's tint table size; entry index + 1 fits a u8 and instanceCustomIndex
inline constexpr u32 Slots = 128;     // pair table, power of two, at least 2 x MaxEntries
static_assert(Slots >= 2 * MaxEntries && (Slots & (Slots - 1)) == 0 && MaxEntries < 255);
inline constexpr u32 AnyCount = 0, AnyFirst = 0xffffffffu;
inline constexpr u32 CountMax = 100000000u;
inline constexpr u32 FirstMax = 4000000000u;
inline constexpr u32 ViewGroup = GLASS_VIEW_GROUP;
inline constexpr float DefaultF0 = 0.04f, MirrorF0 = 0.90f;

struct Entry {
    u64 vs = 0, ps = 0;
    u32 index_count = AnyCount, first_index = AnyFirst;
    u32 tint = 0xffffff;
    float f0 = DefaultF0;
    Kind kind = Kind::None;
    bool builtin = false;
};

struct Error {
    u8 ordinal = 0; // the entry's place in the text, 1 first (a "builtin" token counts as one)
    u8 reason = 0;  // Reason
};

struct Table {
    bool on = false;
    u32 count = 0, builtins = 0, errors = 0;
    std::array<Entry, MaxEntries> entries{}; // sorted: by pair, then first index given, count given, wildcard
    std::array<u8, Slots> slot_first{}, slot_count{}; // slot -> entry index + 1 of the pair's run (0 empty), run length
    std::array<Error, 4> first_errors{};
};

// The measured entries. The mirror has no first index: it may change between loads (t86q 2026-11-16: 11685 of 11946
// px of the mirror box); the mirror pair's other draw (12720 indices) is not it. The arch window is a G-buffer draw
// (top right of the dream house view, 7 targets).
inline constexpr std::array<Entry, 2> BuiltIn{{
    {0x9da6aacb, 0xca7226ec, 24, AnyFirst, 0xffffff, MirrorF0, Kind::Mirror, true},
    {0x97f2d384, 0x2390c887, 324, AnyFirst, 0xffffff, DefaultF0, Kind::Window, true},
}};

namespace Detail {

struct Span {
    std::size_t b = 0, e = 0;
};

constexpr bool IsSpace(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

constexpr std::size_t Length(const char* text) {
    std::size_t n = 0;
    while (text[n] != '\0') {
        ++n;
    }
    return n;
}

constexpr Span Trim(const char* text, std::size_t b, std::size_t e) {
    while (b < e && IsSpace(text[b])) {
        ++b;
    }
    while (e > b && IsSpace(text[e - 1])) {
        --e;
    }
    return {b, e};
}

/// text[s.b, s.e) is exactly `word`.
constexpr bool Is(const char* text, Span s, const char* word) {
    std::size_t i = s.b;
    while (i < s.e && *word != '\0') {
        if (text[i] != *word) {
            return false;
        }
        ++i;
        ++word;
    }
    return i == s.e && *word == '\0';
}

constexpr bool ReadDecimal(const char* text, Span s, u64& value) {
    if (s.b >= s.e) {
        return false;
    }
    u64 v = 0;
    for (std::size_t i = s.b; i < s.e; ++i) {
        if (text[i] < '0' || text[i] > '9') {
            return false;
        }
        v = v * 10 + u64(text[i] - '0');
        if (v > 1000000000000ull) {
            return false;
        }
    }
    value = v;
    return true;
}

/// A decimal number 0..1 ("0", "0.9", ".5", "1.0"), at most 3 digits before and 9 after the point.
constexpr bool ReadUnit(const char* text, Span s, float& out) {
    double v = 0.0, scale = 1.0;
    std::size_t i = s.b, ints = 0, fracs = 0;
    while (i < s.e && text[i] >= '0' && text[i] <= '9') {
        v = v * 10.0 + double(text[i] - '0');
        ++i;
        if (++ints > 3) {
            return false;
        }
    }
    if (i < s.e && text[i] == '.') {
        ++i;
        while (i < s.e && text[i] >= '0' && text[i] <= '9') {
            scale /= 10.0;
            v += double(text[i] - '0') * scale;
            ++i;
            if (++fracs > 9) {
                return false;
            }
        }
    }
    if (i != s.e || ints + fracs == 0 || v > 1.0) {
        return false;
    }
    out = float(v);
    return true;
}

/// A hash field: hex, 1 to 16 digits, an optional 0x, not 0, nothing after it.
constexpr bool ReadHash(const char* text, Span s, u64& value) {
    std::size_t at = s.b;
    u64 v = 0;
    if (s.b >= s.e || !RtGlassReadHex(text, at, v) || at != s.e || v == 0) {
        return false;
    }
    value = v;
    return true;
}

/// "t" and exactly six hex digits.
constexpr bool ReadTint(const char* text, Span s, u32& value) {
    if (s.e - s.b != 7) {
        return false;
    }
    u32 v = 0;
    for (std::size_t i = s.b + 1; i < s.e; ++i) {
        const int d = RtGlassHexDigit(text[i]);
        if (d < 0) {
            return false;
        }
        v = v * 16 + u32(d);
    }
    value = v;
    return true;
}

constexpr Kind ReadKind(const char* text, Span s) {
    return Is(text, s, "window")    ? Kind::Window
           : Is(text, s, "mirror")  ? Kind::Mirror
           : Is(text, s, "bottle")  ? Kind::Bottle
           : Is(text, s, "lantern") ? Kind::Lantern
           : Is(text, s, "cabinet") ? Kind::Cabinet
                                    : Kind::None;
}

constexpr bool SameDraw(const Entry& a, const Entry& b) {
    return a.vs == b.vs && a.ps == b.ps && a.index_count == b.index_count && a.first_index == b.first_index;
}

/// Parses one entry text [b, e) (not "builtin") into `out`; -1 when it is good, else the Reason.
constexpr int ParseEntry(const char* text, std::size_t b, std::size_t e, Entry& out) {
    constexpr std::size_t MaxFields = 8;
    std::array<Span, MaxFields> field{};
    std::size_t n = 0, start = b;
    while (true) {
        std::size_t k = start;
        while (k < e && text[k] != ':') {
            ++k;
        }
        if (n == MaxFields) {
            return int(Reason::Field);
        }
        field[n++] = Trim(text, start, k);
        if (k >= e) {
            break;
        }
        start = k + 1;
    }
    Entry entry{};
    entry.kind = ReadKind(text, field[0]);
    if (entry.kind == Kind::None) {
        return int(Reason::Kind);
    }
    entry.f0 = entry.kind == Kind::Mirror ? MirrorF0 : DefaultF0;
    if (n < 3) {
        return int(Reason::Field);
    }
    if (!ReadHash(text, field[1], entry.vs)) {
        return int(Reason::Vs);
    }
    if (!ReadHash(text, field[2], entry.ps)) {
        return int(Reason::Ps);
    }
    std::size_t place = 0; // 0: the index count is next, 1: the first index, 2: no more numbers
    bool numbers = true, have_tint = false, have_f0 = false;
    for (std::size_t i = 3; i < n; ++i) {
        const Span s = field[i];
        const char c = s.b < s.e ? text[s.b] : '\0';
        if (c == 't') {
            if (have_tint || !ReadTint(text, s, entry.tint)) {
                return int(have_tint ? Reason::Field : Reason::Tint);
            }
            have_tint = true;
            numbers = false;
        } else if (c == 'f') {
            if (have_f0 || !ReadUnit(text, {s.b + 1, s.e}, entry.f0)) {
                return int(have_f0 ? Reason::Field : Reason::F0);
            }
            have_f0 = true;
            numbers = false;
        } else if (!numbers || place >= 2) {
            return int(Reason::Field);
        } else if (place == 0) {
            u64 v = 0;
            if (!Is(text, s, "*") && (!ReadDecimal(text, s, v) || v > CountMax)) {
                return int(Reason::Count);
            }
            entry.index_count = u32(v);
            ++place;
        } else {
            u64 v = AnyFirst;
            if (!Is(text, s, "*") && (!ReadDecimal(text, s, v) || v > FirstMax)) {
                return int(Reason::First);
            }
            entry.first_index = u32(v);
            ++place;
        }
    }
    out = entry;
    return -1;
}

/// 0 the entry is the most specific (a first index), 2 the least (any count, any first index).
constexpr u32 Rank(const Entry& e) {
    return e.first_index != AnyFirst ? 0 : e.index_count != AnyCount ? 1 : 2;
}

constexpr bool SortsBefore(const Entry& a, const Entry& b) {
    if (a.vs != b.vs) {
        return a.vs < b.vs;
    }
    if (a.ps != b.ps) {
        return a.ps < b.ps;
    }
    return Rank(a) < Rank(b);
}

/// -1 when added, else the Reason.
constexpr int Add(Table& t, const Entry& e) {
    if (t.count >= MaxEntries) {
        return int(Reason::TooMany);
    }
    for (u32 i = 0; i < t.count; ++i) {
        if (SameDraw(t.entries[i], e)) {
            return int(Reason::Duplicate);
        }
    }
    t.entries[t.count++] = e;
    t.builtins += e.builtin ? 1u : 0u;
    return -1;
}

constexpr void Fail(Table& t, std::size_t ordinal, int reason) {
    if (t.errors < t.first_errors.size()) {
        t.first_errors[t.errors] = {u8(ordinal > 255 ? 255 : ordinal), u8(reason)};
    }
    ++t.errors;
}

} // namespace Detail

/// The pair's slot in the 128-slot table (the top 7 bits of a mix of both hashes).
constexpr u32 PairSlot(u64 vs, u64 ps) {
    return u32((((vs * 0x9e3779b97f4a7c15ull) ^ ps) * 0xff51afd7ed558ccdull) >> 57);
}

/// BB_GLASS_TABLE's text. Unset, empty, "0" or "off": off (an empty table, no error). Otherwise entries separated by ';'
/// (spaces, tabs and new lines around a field are skipped; ',' is not a separator; empty entries are ignored), each a
/// kind and a pair with optional fields, or the token "builtin". A bad entry adds an Error and is skipped; the others
/// stay (unlike BB_RT_GLASS, which goes all off). The same (pair, index count, first index) twice: Duplicate, the
/// second skipped. More than MaxEntries: TooMany. on = at least one entry.
constexpr Table Parse(const char* text) {
    Table table{};
    if (text == nullptr) {
        return table;
    }
    const std::size_t length = Detail::Length(text);
    const Detail::Span whole{0, length};
    if (length == 0 || Detail::Is(text, whole, "0") || Detail::Is(text, whole, "off")) {
        return table;
    }
    std::size_t at = 0, ordinal = 0;
    while (text[at] != '\0') {
        while (text[at] == ';' || Detail::IsSpace(text[at])) {
            ++at;
        }
        if (text[at] == '\0') {
            break;
        }
        const std::size_t begin = at;
        while (text[at] != '\0' && text[at] != ';') {
            ++at;
        }
        const Detail::Span token = Detail::Trim(text, begin, at);
        ++ordinal;
        if (Detail::Is(text, token, "builtin")) {
            int failed = -1;
            for (const Entry& built : BuiltIn) {
                const int r = Detail::Add(table, built);
                failed = failed < 0 ? r : failed;
            }
            if (failed >= 0) {
                Detail::Fail(table, ordinal, failed);
            }
            continue;
        }
        Entry entry{};
        int r = Detail::ParseEntry(text, token.b, token.e, entry);
        if (r < 0) {
            r = Detail::Add(table, entry);
        }
        if (r >= 0) {
            Detail::Fail(table, ordinal, r);
        }
    }
    // Sorted (stable): by pair, then the most specific first.
    for (u32 i = 1; i < table.count; ++i) {
        const Entry moving = table.entries[i];
        u32 j = i;
        while (j > 0 && Detail::SortsBefore(moving, table.entries[j - 1])) {
            table.entries[j] = table.entries[j - 1];
            --j;
        }
        table.entries[j] = moving;
    }
    for (u32 i = 0; i < table.count;) {
        u32 run = 1;
        while (i + run < table.count && table.entries[i + run].vs == table.entries[i].vs &&
               table.entries[i + run].ps == table.entries[i].ps) {
            ++run;
        }
        u32 slot = PairSlot(table.entries[i].vs, table.entries[i].ps);
        while (table.slot_first[slot] != 0) {
            slot = (slot + 1) & (Slots - 1);
        }
        table.slot_first[slot] = u8(i + 1);
        table.slot_count[slot] = u8(run);
        i += run;
    }
    table.on = table.count > 0;
    return table;
}

/// The entry index + 1 of the first entry of the pair's run whose index count and first index match (0 or the
/// wildcard match anything), or 0. An indexed draw's `first_index` is its first index; a draw that is not indexed
/// (or indirect) gives AnyFirst, which only a first index of '*' matches.
constexpr u8 Lookup(const Table& t, u64 vs, u64 ps, u32 index_count, u32 first_index) {
    u32 slot = PairSlot(vs, ps);
    for (u32 probes = 0; probes < Slots && t.slot_first[slot] != 0; ++probes, slot = (slot + 1) & (Slots - 1)) {
        const u32 start = u32(t.slot_first[slot]) - 1;
        if (t.entries[start].vs != vs || t.entries[start].ps != ps) {
            continue;
        }
        for (u32 i = start; i < start + t.slot_count[slot]; ++i) {
            const Entry& e = t.entries[i];
            if ((e.index_count == AnyCount || e.index_count == index_count) &&
                (e.first_index == AnyFirst || e.first_index == first_index)) {
                return u8(i + 1);
            }
        }
        return 0;
    }
    return 0;
}

/// The table, read once from BB_GLASS_TABLE (any thread).
inline const Table& Load() {
    static const Table table = Parse(std::getenv("BB_GLASS_TABLE"));
    return table;
}

/// BB_GLASS_VIEW's text: 0 off (nullptr, "", "0", "off"), 1 on ("1", "on"), 2 unreadable.
constexpr u8 ParseView(const char* text) {
    if (text == nullptr) {
        return 0;
    }
    const Detail::Span whole{0, Detail::Length(text)};
    if (whole.e == 0 || Detail::Is(text, whole, "0") || Detail::Is(text, whole, "off")) {
        return 0;
    }
    return Detail::Is(text, whole, "1") || Detail::Is(text, whole, "on") ? 1 : 2;
}

/// The colour a kind is painted in (glass_view_layout.h has the numbers the shader uses).
constexpr std::array<float, 3> ViewColour(Kind k) {
    switch (k) {
    case Kind::Window:
        return {float(GLASS_VIEW_WINDOW_R), float(GLASS_VIEW_WINDOW_G), float(GLASS_VIEW_WINDOW_B)};
    case Kind::Mirror:
        return {float(GLASS_VIEW_MIRROR_R), float(GLASS_VIEW_MIRROR_G), float(GLASS_VIEW_MIRROR_B)};
    case Kind::Bottle:
        return {float(GLASS_VIEW_BOTTLE_R), float(GLASS_VIEW_BOTTLE_G), float(GLASS_VIEW_BOTTLE_B)};
    case Kind::Lantern:
    case Kind::Cabinet:
        return {float(GLASS_VIEW_YELLOW_R), float(GLASS_VIEW_YELLOW_G), float(GLASS_VIEW_YELLOW_B)};
    default:
        return {0.0f, 0.0f, 0.0f};
    }
}

constexpr const char* KindName(Kind k) {
    switch (k) {
    case Kind::Window:
        return "window";
    case Kind::Mirror:
        return "mirror";
    case Kind::Bottle:
        return "bottle";
    case Kind::Lantern:
        return "lantern";
    case Kind::Cabinet:
        return "cabinet";
    default:
        return "none";
    }
}

constexpr const char* ReasonName(u8 reason) {
    switch (Reason(reason)) {
    case Reason::Kind:
        return "kind is not window, mirror, bottle, lantern or cabinet";
    case Reason::Vs:
        return "vs is not a hex hash (1-16 digits, not 0)";
    case Reason::Ps:
        return "ps is not a hex hash (1-16 digits, not 0)";
    case Reason::Count:
        return "index count is not a number (or *)";
    case Reason::First:
        return "first index is not a number (or *)";
    case Reason::Tint:
        return "tint is not t and six hex digits";
    case Reason::F0:
        return "f0 is not a number from 0 to 1";
    case Reason::Field:
        return "a field is missing, misplaced or repeated";
    case Reason::TooMany:
        return "more than 64 entries";
    case Reason::Duplicate:
        return "the same draw is listed twice";
    }
    return "unknown";
}

// Compile-time tests of the rules (tests/test_glass_registry.cpp runs the rest).
static_assert(!Parse(nullptr).on && !Parse("").on && !Parse("0").on && !Parse("off").on && Parse("off").errors == 0);
static_assert(Parse("builtin").on && Parse("builtin").count == 2 && Parse("builtin").builtins == 2 &&
              Parse("builtin").errors == 0);
static_assert(Lookup(Parse("builtin"), 0x9da6aacb, 0xca7226ec, 24, 2440816) != 0);
static_assert(Lookup(Parse("builtin"), 0x9da6aacb, 0xca7226ec, 12720, 455504) == 0);
static_assert(ParseView("1") == 1 && ParseView("") == 0 && ParseView("yes") == 2);

} // namespace Vulkan::GlassRegistryRules
''',
RV + "vk_glass_view.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): the glass registry's counters and the glass view, a test view that paints the pixels the
// registry's draws wrote (glass_registry.h has the table and the rules; host_shaders/glass_view.comp the passes).
//
// Where (hooks, each a null pointer test while BB_GLASS_TABLE is off):
//  - Rasterizer::DrawRecord, every direct draw, right before EffectsBeforeResources (GlassRegistryDraw): the draw's pair
//    hash is looked up in the table; a hit is counted (GlassRegistry::Hit), put in DrawContext::glass_hit (entry index + 1,
//    for RtShadow::Draw::glass_entry, S1's hand-off) and, with the view on, SNAPSHOT is recorded before the draw's pass.
//  - The next registry hook, EffectsBlendedScene (Show) and EffectsOnFrameEnd flush the pending MARK: compare the target
//    and the depth with the snapshot; a G-buffer draw leaves a tag where it wrote, a forward draw paints at once.
//  - EffectsBlendedScene (Show), after each G-buffer pass's opaque lighting: SHOW paints the tagged pixels whose depth is
//    still the draw's (a later draw in front, e.g. the hunter before the mirror, is not tinted) and clears the tags.
//  - EffectsOnFrameEnd: the counters, and every LineFrames frames the "Glass registry (r129a)" lines.
// Each pass ends the game's render pass (the next draw begins a new one), as BloodSheen's passes do. A menu's 3D preview
// frame (CameraMotion::PreviewFrame) and another camera's pass are left alone.
//
// Off (BB_GLASS_TABLE unset): the rasterizer makes no GlassRegistry and no GlassView; nothing of this runs.
// Registry on, view off: counters only. View on: four pipelines and two R32UI images of the scene's size are made at the
// first hit draw with the view on (and again when the scene's size changes); GPU work only for hit draws (at most
// MaxSnapshots a frame).
#pragma once

#include <array>
#include <atomic>

#include "common/types.h"
#include "video_core/renderer_vulkan/glass_registry.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

/// What the registry's hits were, counted per entry; made only when BB_GLASS_TABLE names a valid entry.
class GlassRegistry {
public:
    /// Says the table once (the entries, the errors, the view knob).
    GlassRegistry();
    /// BB_GLASS_TABLE off or without a valid entry: says so when it was asked for (or the view was), else nothing.
    static void SayOff();

    [[nodiscard]] const GlassRegistryRules::Table& Rules() const {
        return table;
    }
    /// A draw of entry `index` (0 based) was recorded. Any thread (a player's draw context).
    void Hit(u8 index) {
        frame_draws[index].fetch_add(1, std::memory_order_relaxed);
        frame_mask.fetch_or(1ull << index, std::memory_order_relaxed);
    }
    /// Every frame end: folds the frame into the window; every LineFrames frames the lines.
    void OnFrameEnd();
    /// For later stages: the entries (bit i = entry i) drawn in the last frame, and how many draws of entry i.
    [[nodiscard]] u64 LastFrameMask() const {
        return last_frame_mask;
    }
    [[nodiscard]] u32 LastFrameDraws(u32 i) const {
        return last_frame_draws[i];
    }

    static constexpr u32 LineFrames = 600;

private:
    const GlassRegistryRules::Table& table;
    std::array<std::atomic<u32>, GlassRegistryRules::MaxEntries> frame_draws{};
    std::atomic<u64> frame_mask{0};
    std::array<u32, GlassRegistryRules::MaxEntries> last_frame_draws{}, window_draws{}, window_frames{};
    u64 last_frame_mask = 0;
    u64 frames = 0;       ///< frame ends so far
    u64 window_start = 0; ///< `frames` when the window began
};

class GlassView {
public:
    /// BB_GLASS_VIEW=1 (read once), or, in a build with the live knobs header, BB_LIVE_KNOBS_FILE set (the view is then
    /// switched with the live knob BB_GLASS_VIEW). The caller also asks for a valid registry.
    [[nodiscard]] static bool Wanted();
    GlassView(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
              SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~GlassView();
    GlassView(const GlassView&) = delete;
    GlassView& operator=(const GlassView&) = delete;

    /// The view is on now (a member bool, set once a frame by OnFrameEnd).
    [[nodiscard]] bool On() const {
        return on;
    }
    /// Before a hit draw's resources and pass: `target0` its colour target 0 (the normal for a G-buffer draw, else the
    /// scene colour), `depth` its depth target, `gbuffer` it is a G-buffer draw (five or more colour targets), `kind`
    /// the entry's, `lamps_pending` a lamps-apart batch is still open.
    void Snapshot(VideoCore::ImageId target0, VideoCore::ImageId depth, bool gbuffer, GlassRegistryRules::Kind kind,
                  bool lamps_pending);
    /// The pending MARK (the draw after a SNAPSHOT), if any.
    void FlushMark();
    /// After a G-buffer pass's opaque lighting: paints and clears the tags. `scene` the lit scene (the pass's depth is the one
    /// the last G-buffer MARK was made with: the scene camera's).
    void Show(VideoCore::ImageId scene, bool lamps_pending);
    /// Every frame end: drops a pending MARK (the hit draw was the frame's last), reads the live knob, counters, and every
    /// LineFrames frames a line.
    void OnFrameEnd();

    /// GlassView::Push, word for word with glass_view.comp (32 bytes).
    struct Push {
        std::array<float, 2> size{};
        u32 kind = 0;
        u32 flags = 0;
        std::array<float, 4> colour{};
    };
    static_assert(sizeof(Push) == 32);

    static constexpr u32 LineFrames = 600;
    static constexpr u32 MaxSnapshots = 8; ///< hit draws a frame that get a SNAPSHOT and a MARK

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// A game image's view for a pass: the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written or read as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    bool Ready();
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    void Fail(const char* why);
    void Mark();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, mark_pass, paint_pass, show_pass;
    /// The tag (a G-buffer hit draw's depth bits and kind where it wrote) and SNAPSHOT's prints: two R32UI images of the
    /// scene's size.
    VideoCore::UniqueImage tag_image, before_image;
    vk::UniqueImageView tag_view, before_view;
    u32 tag_width = 0, tag_height = 0;
    bool tag_fresh = false; ///< made and not yet in the General layout
    bool clear_due = true;  ///< the tag's contents are not known to be zero: the next SNAPSHOT clears it
    bool tag_dirty = false; ///< a G-buffer MARK wrote tags since the last SHOW
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool on = false;
    bool told_on = false;
    u64 frame = 0;

    /// The hit draw a SNAPSHOT was recorded for, until its MARK.
    struct Pending {
        bool active = false;
        bool gbuffer = false;
        GlassRegistryRules::Kind kind = GlassRegistryRules::Kind::None;
        VideoCore::ImageId target0{}, depth{};
        u64 target0_uid = 0, depth_uid = 0; ///< their image_uid at the SNAPSHOT: the MARK runs only if both still are
    } pending;
    VideoCore::ImageId tag_depth{}; ///< the depth image of the last G-buffer MARK
    u64 tag_depth_uid = 0;          ///< its image_uid (SHOW runs only if it still is)
    u32 snapshots_this_frame = 0;
    bool told_show = false;

    struct Stats {
        u32 frames = 0, snapshots = 0, marks = 0, paints = 0, shows = 0;
        u32 skip_cap = 0, skip_preview = 0, skip_lamps = 0, skip_camera = 0, skip_shape = 0;
    } stats;
};

} // namespace Vulkan
''',
RV + "vk_glass_view.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_glass_view.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/glass_view_mark_comp.h"
#include "video_core/host_shaders/glass_view_paint_comp.h"
#include "video_core/host_shaders/glass_view_show_comp.h"
#include "video_core/host_shaders/glass_view_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r129a_glass-registry): the live knobs of the test tools (r84_live-test-knobs): in a build with the header,
// BB_GLASS_VIEW is switched while the game runs.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define GLASS_VIEW_LIVE 1
#endif

namespace Vulkan {
namespace {
namespace R = GlassRegistryRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto TagFormat = vk::Format::eR32Uint;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
// EffectPass::Mark's key (the row "Lighting: glass view"): the rows are keys, 0x4C490000 | key; in use: 6, 10-18, 51, 61-64,
// 80, 81, 86, 95, 97, 99, 100, 105, 107, 111, 117, 119; 129 is free
constexpr u64 ProfileRow = 129;

/// Target 0 formats a sampled view reads as float (a G-buffer draw's normal target, a forward draw's scene colour).
bool FloatColour(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb ||
           format == vk::Format::eR16G16B16A16Sfloat || format == vk::Format::eA2B10G10R10UnormPack32 ||
           format == vk::Format::eB10G11R11UfloatPack32;
}

/// BB_GLASS_VIEW now: live in a build with the live knobs header, else read once. 1 only: the view is on.
bool ViewNow() {
#ifdef GLASS_VIEW_LIVE
    static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_VIEW", R::ParseView};
    return knob.Get() == 1;
#else
    static const bool fixed = R::ParseView(std::getenv("BB_GLASS_VIEW")) == 1;
    return fixed;
#endif
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

/// What a pass's commands begin with: the game's writes before it (and the last pass's reads of the tag) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead | vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// "any" or the number.
std::string Wild(u32 value, u32 any) {
    return value == any ? std::string("any") : std::to_string(value);
}
} // namespace

// ---- the registry ----

GlassRegistry::GlassRegistry() : table{R::Load()} {
    const char* text = std::getenv("BB_GLASS_TABLE");
    const char* view_text = std::getenv("BB_GLASS_VIEW");
    const u8 view = R::ParseView(view_text);
    BbReport::Printf("Glass registry (r129a): BB_GLASS_TABLE=%.200s: %u entries (%u built-in), %u errors; view %s\n",
                     text ? text : "", table.count, table.builtins, table.errors,
                     !GlassView::Wanted() ? "off" : (view == 1 ? "on" : "off (live: BB_GLASS_VIEW)"));
    for (u32 i = 0; i < table.count; ++i) {
        const auto& e = table.entries[i];
        BbReport::Printf("Glass registry (r129a): entry %u %s %08llx:%08llx idx %s first %s tint %06x f0 %.2f%s%s\n", i + 1,
                         R::KindName(e.kind), static_cast<unsigned long long>(e.vs), static_cast<unsigned long long>(e.ps),
                         Wild(e.index_count, R::AnyCount).c_str(), Wild(e.first_index, R::AnyFirst).c_str(), e.tint,
                         double(e.f0), e.builtin ? " (built-in)" : "",
                         e.kind == R::Kind::Lantern ? " (whole draw: the panes need a triangle class, a later stage)" : "");
    }
    for (u32 i = 0; i < std::min<u32>(table.errors, u32(table.first_errors.size())); ++i) {
        BbReport::Printf("Glass registry (r129a): error in entry %u: %s, skipped\n", u32(table.first_errors[i].ordinal),
                         R::ReasonName(table.first_errors[i].reason));
    }
    if (table.errors > table.first_errors.size()) {
        BbReport::Printf("Glass registry (r129a): %u more errors not listed\n",
                         table.errors - u32(table.first_errors.size()));
    }
    if (view == 2) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s is neither 0 nor 1: view off\n", view_text);
    }
}

void GlassRegistry::SayOff() {
    const char* text = std::getenv("BB_GLASS_TABLE");
    if (text != nullptr && text[0] != '\0' && std::strcmp(text, "0") != 0 && std::strcmp(text, "off") != 0) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_TABLE=%.40s: no valid entry, registry off\n", text);
        const auto& table = R::Load();
        for (u32 i = 0; i < std::min<u32>(table.errors, u32(table.first_errors.size())); ++i) {
            BbReport::Printf("Glass registry (r129a): error in entry %u: %s, skipped\n",
                             u32(table.first_errors[i].ordinal), R::ReasonName(table.first_errors[i].reason));
        }
    }
    const char* view_text = std::getenv("BB_GLASS_VIEW");
    const u8 view = R::ParseView(view_text);
    if (view == 1) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s needs BB_GLASS_TABLE; view off\n", view_text);
    } else if (view == 2) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s is neither 0 nor 1: view off\n", view_text);
    }
}

void GlassRegistry::OnFrameEnd() {
    last_frame_mask = frame_mask.exchange(0, std::memory_order_relaxed);
    for (u32 i = 0; i < table.count; ++i) {
        const u32 draws = frame_draws[i].exchange(0, std::memory_order_relaxed);
        last_frame_draws[i] = draws;
        if (draws != 0) {
            window_draws[i] += draws;
            ++window_frames[i];
        }
    }
    ++frames;
    if (frames - window_start < LineFrames) {
        return;
    }
    u32 hit = 0, total = 0;
    for (u32 i = 0; i < table.count; ++i) {
        hit += window_draws[i] != 0 ? 1u : 0u;
        total += window_draws[i];
    }
    BbReport::Printf("Glass registry (r129a): frames %llu-%llu: %u of %u entries hit, %u draws\n",
                     static_cast<unsigned long long>(window_start + 1), static_cast<unsigned long long>(frames), hit,
                     table.count, total);
    for (u32 i = 0; i < table.count; ++i) {
        const auto& e = table.entries[i];
        BbReport::Printf("Glass registry (r129a): entry %u %s %08llx:%08llx: %u draws in %u/%u frames\n", i + 1,
                         R::KindName(e.kind), static_cast<unsigned long long>(e.vs), static_cast<unsigned long long>(e.ps),
                         window_draws[i], window_frames[i], u32(frames - window_start));
    }
    window_draws = {};
    window_frames = {};
    window_start = frames;
}

// ---- the draw hook ----

void Rasterizer::GlassRegistryDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset) {
    auto& dc = Dc();
    if (glass_view) {
        glass_view->FlushMark(); // the draw before a hit has finished: its MARK goes in front of this draw
    }
    dc.glass_hit = 0;
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps) {
        return;
    }
    const u8 hit = R::Lookup(glass_registry->Rules(), pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps->pgm_hash,
                             u32(Regs().num_indices), is_indexed ? index_offset : R::AnyFirst);
    if (hit == 0) {
        return;
    }
    dc.glass_hit = hit;
    glass_registry->Hit(u8(hit - 1));
    if (glass_view && glass_view->On()) {
        const u32 mrt = u32(pipeline->GetGraphicsKey().mrt_mask);
        // PrepareRenderState has run: cb_descs and db_desc are this draw's
        glass_view->Snapshot(cb_descs[0].first, db_desc.first, std::popcount(mrt) >= 5,
                             glass_registry->Rules().entries[hit - 1].kind, point_shadow->Pending());
    }
}

// ---- the view ----

bool GlassView::Wanted() {
#ifdef GLASS_VIEW_LIVE
    if (std::getenv("BB_LIVE_KNOBS_FILE") != nullptr) {
        return true;
    }
#endif
    return R::ParseView(std::getenv("BB_GLASS_VIEW")) == 1;
}

GlassView::GlassView(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                     Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    on = ViewNow();
}

GlassView::~GlassView() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool GlassView::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TagFormat) && EffectPass::StorageFormat(instance, SceneFormat) &&
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage}, sizeof(Push),
                           GLASS_VIEW_SNAPSHOT_COMP, "Glass view snapshot") &&
        EffectPass::Create(instance, mark_pass.set_layout, mark_pass.layout, mark_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage}, sizeof(Push),
                           GLASS_VIEW_MARK_COMP, "Glass view mark") &&
        EffectPass::Create(instance, paint_pass.set_layout, paint_pass.layout, paint_pass.pipeline,
                           {eSampledImage, eStorageImage, eStorageImage}, sizeof(Push), GLASS_VIEW_PAINT_COMP,
                           "Glass view paint") &&
        EffectPass::Create(instance, show_pass.set_layout, show_pass.layout, show_pass.pipeline,
                           {eStorageImage, eSampledImage, eStorageImage}, sizeof(Push), GLASS_VIEW_SHOW_COMP,
                           "Glass view show");
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void GlassView::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Glass view (r129a): off - %s\n", why);
    ReleaseImage();
}

void GlassView::ReleaseImage() {
    if (tag_image) {
        scheduler.DeferOperation([image = std::move(tag_image), view = std::move(tag_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    if (before_image) {
        scheduler.DeferOperation([image = std::move(before_image), view = std::move(before_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    tag_view.reset();
    before_view.reset();
    tag_width = tag_height = 0;
}

bool GlassView::EnsureImage(u32 width, u32 height) {
    if (tag_image && tag_width == width && tag_height == height) {
        return true;
    }
    ReleaseImage();
    if (!EffectPass::HasRoom(instance, 8ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = TagFormat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    tag_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    tag_image.Create(image_ci);
    SetObjectName(device, vk::Image(tag_image), "Glass view tag");
    tag_view = Check<"create glass view tag view">(device.createImageViewUnique({
        .image = vk::Image(tag_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    before_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    before_image.Create(image_ci);
    SetObjectName(device, vk::Image(before_image), "Glass view prints before");
    before_view = Check<"create glass view prints view">(device.createImageViewUnique({
        .image = vk::Image(before_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    tag_width = width;
    tag_height = height;
    tag_fresh = true;
    clear_due = true;
    tag_dirty = false;
    return true;
}

vk::ImageView GlassView::CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == format &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create glass view image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool GlassView::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

vk::ImageView GlassView::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

void GlassView::Snapshot(VideoCore::ImageId target0, VideoCore::ImageId depth, bool gbuffer, R::Kind kind,
                         bool lamps_pending) {
    if (failed) {
        return;
    }
    // Lamps apart (vk_point_shadow.h): an open batch must not see the scene depth read.
    if (lamps_pending) {
        ++stats.skip_lamps;
        return;
    }
    if (snapshots_this_frame >= MaxSnapshots) {
        ++stats.skip_cap;
        return;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.skip_preview;
        return;
    }
    // Only the scene camera's pass (a planar reflection's pass has another depth, often another size).
    if (!depth || depth != camera_motion.Depth()) {
        ++stats.skip_camera;
        return;
    }
    u32 width = 0, height = 0, width0 = 0, height0 = 0;
    bool reduced = false, reduced0 = false;
    if (!target0 || !SceneSize(depth, width, height, reduced) || !SceneSize(target0, width0, height0, reduced0)) {
        ++stats.skip_shape;
        return;
    }
    const auto& image = texture_cache.GetImage(target0);
    const bool format_fits = gbuffer ? FloatColour(image.info.pixel_format) : image.info.pixel_format == SceneFormat;
    if (!format_fits || image.info.num_samples != 1 || width0 != width || height0 != height || reduced0 != reduced) {
        ++stats.skip_shape;
        return;
    }
    if (!Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.skip_shape;
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    const vk::ImageView colour_view = ViewOf(target0, vk::ImageAspectFlagBits::eColor, false, false);
    const vk::ImageView depth_view = ViewOf(depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!colour_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.size = {float(width), float(height)};
    push.flags = clear_due ? u32(GLASS_VIEW_FLAG_CLEAR) : 0u;
    clear_due = false;
    const bool fresh = std::exchange(tag_fresh, false);
    EffectPass::Mark(ProfileRow, "glass view", true);
    scheduler.RecordCrumb(
        {.name = "glass view snapshot"},
        [push, fresh, width, height, colour_view, depth_view, tag_handle = vk::Image(tag_image),
         before_handle = vk::Image(before_image), tag = *tag_view, before = *before_view,
         pipeline = *snapshot_pass.pipeline, layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
                EffectPass::InitGeneral(cmd, before_handle, ColorLevel);
            }
            using enum vk::DescriptorType;
            const std::array infos{Info(colour_view), Info(depth_view), Info(before), Info(tag)};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
    ++snapshots_this_frame;
    ++stats.snapshots;
    pending = {.active = true, .gbuffer = gbuffer, .kind = kind, .target0 = target0, .depth = depth,
               .target0_uid = image.image_uid, .depth_uid = texture_cache.GetImage(depth).image_uid};
}

void GlassView::FlushMark() {
    if (pending.active) {
        Mark();
    }
}

void GlassView::Mark() {
    const Pending draw = std::exchange(pending, Pending{});
    if (!draw.active || failed || !tag_image) {
        return;
    }
    // the MARK runs at the next draw's hook: that draw's PrepareRenderState may have freed (or reused the slot of) the hit
    // draw's target 0 or depth; GetImage on a freed id is not safe, so both are looked up by id and uid first
    if (!texture_cache.TryGetImage(draw.target0, draw.target0_uid) || !texture_cache.TryGetImage(draw.depth, draw.depth_uid)) {
        ++stats.skip_shape;
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    // a G-buffer draw: target 0 is read (its print, as the SNAPSHOT's); a forward draw paints target 0 itself
    const vk::ImageView colour_view =
        draw.gbuffer ? ViewOf(draw.target0, vk::ImageAspectFlagBits::eColor, false, false)
                     : ViewOf(draw.target0, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(draw.depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!colour_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.size = {float(tag_width), float(tag_height)};
    push.kind = u32(draw.kind);
    const auto colour = R::ViewColour(draw.kind);
    push.colour = {colour[0], colour[1], colour[2], 1.0f};
    EffectPass::Mark(ProfileRow, "glass view", true);
    const auto& pass = draw.gbuffer ? mark_pass : paint_pass;
    scheduler.RecordCrumb(
        {.name = draw.gbuffer ? "glass view mark" : "glass view paint"},
        [push, gbuffer = draw.gbuffer, width = tag_width, height = tag_height, colour_view, depth_view, tag = *tag_view,
         before = *before_view, pipeline = *pass.pipeline, layout = *pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            if (gbuffer) {
                const std::array infos{Info(colour_view), Info(depth_view), Info(before), Info(tag)};
                const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                        ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3])};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            } else {
                const std::array infos{Info(depth_view), Info(before), Info(colour_view)};
                const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eStorageImage, &infos[1]),
                                        ImageWrite(2, eStorageImage, &infos[2])};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            }
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
    if (draw.gbuffer) {
        tag_dirty = true;
        tag_depth = draw.depth;
        tag_depth_uid = draw.depth_uid;
        ++stats.marks;
    } else {
        ++stats.paints;
    }
}

void GlassView::Show(VideoCore::ImageId scene, bool lamps_pending) {
    FlushMark();
    if (!tag_dirty || failed || !scene || !tag_depth || !tag_image || lamps_pending ||
        !texture_cache.TryGetImage(tag_depth, tag_depth_uid)) { // the tags' depth freed since: the frame end clears them
        return;
    }
    const auto& image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) || width != tag_width ||
        height != tag_height) {
        if (!told_show) {
            told_show = true;
            BbReport::Printf("Glass view (r129a): show left out (first time): the lit scene is format %u, %ux%u, the tag "
                             "%ux%u (RGBA16F, 97, of the tag's size wanted)\n",
                             u32(image.info.pixel_format), width, height, tag_width, tag_height);
        }
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = ViewOf(scene, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(tag_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view || !depth_view) {
        return;
    }
    Push push{};
    push.size = {float(width), float(height)};
    tag_dirty = false; // SHOW clears every tag it reads
    ++stats.shows;
    EffectPass::Mark(ProfileRow, "glass view", true);
    scheduler.RecordCrumb(
        {.name = "glass view show"},
        [push, width, height, scene_view, depth_view, tag = *tag_view, pipeline = *show_pass.pipeline,
         layout = *show_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            const std::array infos{Info(tag), Info(depth_view), Info(scene_view)};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
}

void GlassView::OnFrameEnd() {
    // a MARK still pending (the hit draw was the frame's last direct draw) is dropped, not recorded at the frame end
    pending = {};
    const bool now = ViewNow();
    if (now != on || now != told_on) {
        on = now;
        told_on = now;
        BbReport::Printf("Glass view (r129a): view %s at frame %llu\n", now ? "on" : "off",
                         static_cast<unsigned long long>(frame));
    }
    if (tag_dirty) { // tags no SHOW took (the scene did not fit): the next hit draw's SNAPSHOT clears them
        clear_due = true;
        tag_dirty = false;
    }
    snapshots_this_frame = 0;
    tag_depth = {};
    ++frame;
    if (++stats.frames < LineFrames) {
        return;
    }
    BbReport::Printf("Glass view (r129a): view %s: snapshots %u marks %u paints %u shows %u; skipped cap %u preview %u "
                     "lamps open %u camera %u shape %u%s\n",
                     on ? "on" : "off", stats.snapshots, stats.marks, stats.paints, stats.shows, stats.skip_cap,
                     stats.skip_preview, stats.skip_lamps, stats.skip_camera, stats.skip_shape,
                     failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
''',
HS + "glass_view.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): the glass view, a test view that paints the pixels the glass registry's draws wrote
// (renderer_vulkan/vk_glass_view.cpp records the passes, glass_registry.h has the rules). Four builds, one per pass,
// the same snapshot / compare idea as blood_sheen.comp:
//   GLASS_SNAPSHOT  right before a hit draw: a 32-bit print of each pixel's colour (target 0) and depth into `before_img`
//                   (the first hit draw of a frame whose tag is not known clear also clears the tag)
//   GLASS_MARK      right after a G-buffer hit draw: where the print changed, tag = (depth bits & ~7) | kind
//   GLASS_PAINT     right after a forward hit draw (target 0 is the RGBA16F scene colour): where the print changed, the
//                   pixel is painted in the kind's colour at once
//   GLASS_SHOW      over the lit scene after a G-buffer pass's lighting: a tagged pixel whose depth is still the tag's
//                   (no later draw in front of it) is painted; every tag is cleared
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "glass_view_layout.h"

#define GLASS_BUILDS 0
#if defined(GLASS_SNAPSHOT)
#undef GLASS_BUILDS
#define GLASS_BUILDS 1
#endif
#if defined(GLASS_MARK)
#if GLASS_BUILDS != 0
#error "glass_view.comp: define exactly one of GLASS_SNAPSHOT, GLASS_MARK, GLASS_PAINT, GLASS_SHOW"
#endif
#undef GLASS_BUILDS
#define GLASS_BUILDS 1
#endif
#if defined(GLASS_PAINT)
#if GLASS_BUILDS != 0
#error "glass_view.comp: define exactly one of GLASS_SNAPSHOT, GLASS_MARK, GLASS_PAINT, GLASS_SHOW"
#endif
#undef GLASS_BUILDS
#define GLASS_BUILDS 1
#endif
#if defined(GLASS_SHOW)
#if GLASS_BUILDS != 0
#error "glass_view.comp: define exactly one of GLASS_SNAPSHOT, GLASS_MARK, GLASS_PAINT, GLASS_SHOW"
#endif
#undef GLASS_BUILDS
#define GLASS_BUILDS 1
#endif
#if GLASS_BUILDS != 1
#error "glass_view.comp: define exactly one of GLASS_SNAPSHOT, GLASS_MARK, GLASS_PAINT, GLASS_SHOW"
#endif

layout(local_size_x = GLASS_VIEW_GROUP, local_size_y = GLASS_VIEW_GROUP, local_size_z = 1) in;

// GlassView::Push (vk_glass_view.h), word for word (8 words).
layout(push_constant) uniform Push {
    vec2 size;   // pixels
    uint kind;   // MARK, PAINT: GLASS_VIEW_KIND_*
    uint flags;  // GLASS_VIEW_FLAG_*
    vec4 colour; // PAINT: the kind's colour (rgb)
};

#if defined(GLASS_SNAPSHOT)
layout(binding = 0) uniform texture2D colour_tex;                 // target 0 of the hit draw
layout(binding = 1) uniform texture2D depth_tex;                  // the pass's depth
layout(binding = 2, r32ui) uniform writeonly uimage2D before_img; // the prints before the draw
layout(binding = 3, r32ui) uniform writeonly uimage2D tag_img;    // cleared with GLASS_VIEW_FLAG_CLEAR
#elif defined(GLASS_MARK)
layout(binding = 0) uniform texture2D colour_tex;
layout(binding = 1) uniform texture2D depth_tex;
layout(binding = 2, r32ui) uniform readonly uimage2D before_img;
layout(binding = 3, r32ui) uniform writeonly uimage2D tag_img;
#elif defined(GLASS_PAINT)
layout(binding = 0) uniform texture2D depth_tex;
layout(binding = 1, r32ui) uniform readonly uimage2D before_img;
layout(binding = 2, rgba16f) uniform image2D scene_img; // target 0: the lit scene colour
#else
layout(binding = 0, r32ui) uniform uimage2D tag_img;
layout(binding = 1) uniform texture2D depth_tex;
layout(binding = 2, rgba16f) uniform image2D scene_img;
#endif

#if !defined(GLASS_SHOW)
// A pixel's colour and depth in 32 bits: a pixel a draw wrote prints differently unless two different values collide.
uint ColourHash(vec4 c) {
    const uvec4 a = floatBitsToUint(c);
    uint h = a.x * 0x9E3779B1u;
    h = (h ^ (h >> 15u) ^ a.y) * 0x85EBCA77u;
    h = (h ^ (h >> 13u) ^ a.z) * 0xC2B2AE3Du;
    h = (h ^ (h >> 16u) ^ a.w) * 0x27D4EB2Fu;
    return h ^ (h >> 15u);
}
uint Print(uint depth_bits, vec4 c) {
    return depth_bits ^ (ColourHash(c) * 0x9E3779B1u);
}
#endif

#if defined(GLASS_SHOW)
// GlassRegistryRules::ViewColour, the same numbers (glass_view_layout.h).
vec3 KindColour(uint k) {
    if (k == GLASS_VIEW_KIND_WINDOW) {
        return vec3(GLASS_VIEW_WINDOW_R, GLASS_VIEW_WINDOW_G, GLASS_VIEW_WINDOW_B);
    }
    if (k == GLASS_VIEW_KIND_MIRROR) {
        return vec3(GLASS_VIEW_MIRROR_R, GLASS_VIEW_MIRROR_G, GLASS_VIEW_MIRROR_B);
    }
    if (k == GLASS_VIEW_KIND_BOTTLE) {
        return vec3(GLASS_VIEW_BOTTLE_R, GLASS_VIEW_BOTTLE_G, GLASS_VIEW_BOTTLE_B);
    }
    return vec3(GLASS_VIEW_YELLOW_R, GLASS_VIEW_YELLOW_G, GLASS_VIEW_YELLOW_B);
}
#endif

vec3 Painted(vec3 c, vec3 tint) {
    const float luma = max(dot(c, vec3(0.2126, 0.7152, 0.0722)), GLASS_VIEW_FLOOR);
    return mix(c, tint * luma, GLASS_VIEW_MIX);
}

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x >= int(size.x) || p.y >= int(size.y)) {
        return;
    }
#if defined(GLASS_SNAPSHOT)
    const uint depth_bits = floatBitsToUint(texelFetch(depth_tex, p, 0).x);
    imageStore(before_img, p, uvec4(Print(depth_bits, texelFetch(colour_tex, p, 0))));
    if ((flags & GLASS_VIEW_FLAG_CLEAR) != 0u) {
        imageStore(tag_img, p, uvec4(0u));
    }
#elif defined(GLASS_MARK)
    const uint depth_bits = floatBitsToUint(texelFetch(depth_tex, p, 0).x);
    if (Print(depth_bits, texelFetch(colour_tex, p, 0)) != imageLoad(before_img, p).x) {
        imageStore(tag_img, p, uvec4((depth_bits & ~7u) | kind));
    }
#elif defined(GLASS_PAINT)
    const uint depth_bits = floatBitsToUint(texelFetch(depth_tex, p, 0).x);
    const vec4 c = imageLoad(scene_img, p);
    if (Print(depth_bits, c) != imageLoad(before_img, p).x) {
        imageStore(scene_img, p, vec4(Painted(c.rgb, colour.rgb), c.a));
    }
#else
    const uint tag = imageLoad(tag_img, p).x;
    if (tag != 0u) {
        const uint depth_bits = floatBitsToUint(texelFetch(depth_tex, p, 0).x);
        if ((tag & 7u) != 0u && (depth_bits & ~7u) == (tag & ~7u)) {
            const vec4 c = imageLoad(scene_img, p);
            imageStore(scene_img, p, vec4(Painted(c.rgb, KindColour(tag & 7u)), c.a));
        }
        imageStore(tag_img, p, uvec4(0u));
    }
#endif
}
''',
HS + "glass_view_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): what the glass view's shader (glass_view.comp) and the engine
// (renderer_vulkan/glass_registry.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text holds every number both sides use.
#ifndef GLASS_VIEW_LAYOUT_H
#define GLASS_VIEW_LAYOUT_H

// Pixels a side of one workgroup.
#define GLASS_VIEW_GROUP 8u
// The push word `flags`: SNAPSHOT: the tag is cleared too (first hit draw of a frame whose tag is not known clear).
#define GLASS_VIEW_FLAG_CLEAR 1u
// The kinds (GlassRegistryRules::Kind): the low three bits of a tag, 0 = no tag.
#define GLASS_VIEW_KIND_NONE 0u
#define GLASS_VIEW_KIND_WINDOW 1u
#define GLASS_VIEW_KIND_MIRROR 2u
#define GLASS_VIEW_KIND_BOTTLE 3u
#define GLASS_VIEW_KIND_LANTERN 4u
#define GLASS_VIEW_KIND_CABINET 5u
// The colour each kind is painted in (window cyan, mirror magenta, bottle orange, lantern and cabinet yellow).
#define GLASS_VIEW_WINDOW_R 0.0
#define GLASS_VIEW_WINDOW_G 1.0
#define GLASS_VIEW_WINDOW_B 1.0
#define GLASS_VIEW_MIRROR_R 1.0
#define GLASS_VIEW_MIRROR_G 0.0
#define GLASS_VIEW_MIRROR_B 1.0
#define GLASS_VIEW_BOTTLE_R 1.0
#define GLASS_VIEW_BOTTLE_G 0.5
#define GLASS_VIEW_BOTTLE_B 0.0
#define GLASS_VIEW_YELLOW_R 1.0
#define GLASS_VIEW_YELLOW_G 1.0
#define GLASS_VIEW_YELLOW_B 0.0
// Painted pixel = mix(pixel, colour * max(pixel luminance, FLOOR), MIX).
#define GLASS_VIEW_FLOOR 0.5
#define GLASS_VIEW_MIX 0.7

#endif
''',
"engine/tests/test_glass_registry.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): the glass registry's table text, lookup and view knob
// (renderer_vulkan/glass_registry.h). Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target
// glass-registry-test.
#undef NDEBUG
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
#include "gpu/shadps4/video_core/renderer_vulkan/glass_registry.h"

using namespace Vulkan::GlassRegistryRules;

namespace {
constexpr std::uint64_t MirrorVs = 0x9da6aacb, MirrorPs = 0xca7226ec;
constexpr std::uint64_t WindowVs = 0x97f2d384, WindowPs = 0x2390c887;

/// The entry a lookup found, or nullptr.
const Entry* Find(const Table& t, std::uint64_t vs, std::uint64_t ps, std::uint32_t count, std::uint32_t first) {
    const std::uint8_t hit = Lookup(t, vs, ps, count, first);
    return hit == 0 ? nullptr : &t.entries[hit - 1u];
}
} // namespace

int main() {
    // a. off: unset, empty, "0", "off" (and spaces only) are off with no error, and never the built-in table.
    for (const char* text : {static_cast<const char*>(nullptr), "", "0", "off", "  ", ";;", " ; "}) {
        const Table t = Parse(text);
        assert(!t.on && t.count == 0 && t.errors == 0 && t.builtins == 0);
        assert(Lookup(t, MirrorVs, MirrorPs, 24, 2440816) == 0);
    }
    assert(!Parse("OFF").on && Parse("OFF").errors == 1); // not the word: a bad entry

    // b. builtin: the mirror (pair and 24 indices, no first index) and the arch window (324 indices), once.
    {
        const Table t = Parse("builtin");
        assert(t.on && t.count == 2 && t.builtins == 2 && t.errors == 0);
        const Entry* mirror = Find(t, MirrorVs, MirrorPs, 24, 2440816);
        assert(mirror && mirror->kind == Kind::Mirror && mirror->builtin && mirror->first_index == AnyFirst);
        assert(mirror->f0 == 0.90f && mirror->tint == 0xffffff && mirror->index_count == 24);
        assert(Find(t, MirrorVs, MirrorPs, 24, 12345) == mirror); // the first index may change between loads
        assert(Find(t, MirrorVs, MirrorPs, 24, AnyFirst) == mirror);
        const Entry* window = Find(t, WindowVs, WindowPs, 324, 0);
        assert(window && window->kind == Kind::Window && window->f0 == 0.04f && window->index_count == 324);
        assert(Find(t, MirrorVs, MirrorPs, 12720, 455504) == nullptr); // the mirror pair's other draw is not glass
        assert(Find(t, WindowVs, WindowPs, 323, 0) == nullptr);
        assert(Find(t, 1, 2, 24, 0) == nullptr);
        // a second token is a Duplicate (once), the table is as it was
        const Table twice = Parse("builtin;builtin");
        assert(twice.count == 2 && twice.errors == 1 && twice.first_errors[0].ordinal == 2 &&
               twice.first_errors[0].reason == std::uint8_t(Reason::Duplicate));
    }

    // c. separators and spaces: ';' between entries, spaces, tabs and new lines around fields, empty entries ignored.
    {
        const Table t = Parse(" window:1:2 ;\n\tbottle : 0x3 : 4 : 7 ;; cabinet:5:6:*:* ;");
        assert(t.on && t.count == 3 && t.errors == 0);
        const Entry* a = Find(t, 1, 2, 99, 99);
        assert(a && a->kind == Kind::Window && a->index_count == AnyCount && a->first_index == AnyFirst);
        const Entry* b = Find(t, 3, 4, 7, 1);
        assert(b && b->kind == Kind::Bottle && b->index_count == 7);
        assert(Find(t, 5, 6, 1, 1) != nullptr);
        // ',' is not a separator: a bad entry (the second pair's hash has no valid text)
        const Table comma = Parse("window:1:2,window:3:4");
        assert(!comma.on && comma.errors == 1 && comma.first_errors[0].reason == std::uint8_t(Reason::Ps));
    }

    // d. hashes: hex, 1 to 16 digits, optional 0x, upper or lower case, not 0; 17 digits or a bad digit refused.
    {
        const Table t = Parse("window:0xABCDEF0123456789:fFfFfFfFfFfFfFfF");
        assert(t.count == 1 && t.entries[0].vs == 0xabcdef0123456789ull && t.entries[0].ps == 0xffffffffffffffffull);
        assert(Parse("window:12345678901234567:2").errors == 1);
        assert(Parse("window:0:2").first_errors[0].reason == std::uint8_t(Reason::Vs));
        assert(Parse("window:1:0").first_errors[0].reason == std::uint8_t(Reason::Ps));
        assert(Parse("window:1g:2").first_errors[0].reason == std::uint8_t(Reason::Vs));
        assert(Parse("window:1:2 3").first_errors[0].reason == std::uint8_t(Reason::Ps));
        assert(Parse("window:0x:2").first_errors[0].reason == std::uint8_t(Reason::Vs));
        assert(Parse("window::2").first_errors[0].reason == std::uint8_t(Reason::Vs));
        assert(Parse("window:1").first_errors[0].reason == std::uint8_t(Reason::Field));
        assert(Parse("window").first_errors[0].reason == std::uint8_t(Reason::Field));
    }

    // e. kinds, and a bad kind (the third entry, ordinal 3, is skipped; the others stay).
    {
        const Table t = Parse("builtin;bottle:e30b0480:8a6c7657;lamp:1:2");
        assert(t.on && t.count == 3 && t.builtins == 2 && t.errors == 1);
        assert(t.first_errors[0].ordinal == 3 && t.first_errors[0].reason == std::uint8_t(Reason::Kind));
        assert(Parse("Window:1:2").first_errors[0].reason == std::uint8_t(Reason::Kind)); // lower case words only
        assert(Parse("windows:1:2").errors == 1 && Parse(":1:2").errors == 1);
        for (const char* kind : {"window", "mirror", "bottle", "lantern", "cabinet"}) {
            const std::string text = std::string(kind) + ":1:2";
            assert(Parse(text.c_str()).count == 1 && Parse(text.c_str()).errors == 0);
        }
        assert(Parse("lantern:6a833138:1c3953c6:4641").entries[0].kind == Kind::Lantern);
    }

    // f. index count and first index: decimal, '*', 0 count = any; 0 as a first index is a first index; limits.
    {
        const Table t = Parse("window:1:2:0:0;window:3:4:*:*;window:5:6:100000000;window:7:8:5:2440816");
        assert(t.count == 4 && t.errors == 0);
        const Entry* zero = Find(t, 1, 2, 77, 0);
        assert(zero && zero->first_index == 0 && zero->index_count == AnyCount);
        assert(Find(t, 1, 2, 77, 1) == nullptr && Find(t, 1, 2, 77, AnyFirst) == nullptr); // not indexed: no match
        assert(Find(t, 3, 4, 1, AnyFirst) != nullptr); // '*' first index matches a draw that is not indexed
        assert(Find(t, 5, 6, 100000000, 3) != nullptr && Find(t, 5, 6, 99999999, 3) == nullptr);
        assert(Find(t, 7, 8, 5, 2440816) != nullptr && Find(t, 7, 8, 5, 2440817) == nullptr &&
               Find(t, 7, 8, 5, AnyFirst) == nullptr);
        assert(Parse("window:1:2:100000001").first_errors[0].reason == std::uint8_t(Reason::Count));
        assert(Parse("window:1:2:-1").first_errors[0].reason == std::uint8_t(Reason::Count));
        assert(Parse("window:1:2:1.5").first_errors[0].reason == std::uint8_t(Reason::Count));
        assert(Parse("window:1:2:5:x").first_errors[0].reason == std::uint8_t(Reason::First));
        assert(Parse("window:1:2:5:4294967295").first_errors[0].reason == std::uint8_t(Reason::First));
        assert(Parse("window:1:2:5:4000000000").count == 1);
        assert(Parse("window:1:2:5:6:7").first_errors[0].reason == std::uint8_t(Reason::Field));
        assert(Parse("window:1:2::").first_errors[0].reason == std::uint8_t(Reason::Count));
    }

    // g. t (tint) and f (F0) tokens: any order, after the numbers (a t or f token ends the positional fields).
    {
        const Table t = Parse("window:1:2:10:20:tff8000:f0.5;bottle:3:4:f.25:t102030;mirror:5:6;mirror:7:8:f0.5;window:9:a:t00ff00");
        assert(t.count == 5 && t.errors == 0);
        const Entry* a = Find(t, 1, 2, 10, 20);
        assert(a && a->tint == 0xff8000 && a->f0 == 0.5f);
        const Entry* b = Find(t, 3, 4, 1, 1);
        assert(b && b->tint == 0x102030 && b->f0 == 0.25f && b->index_count == AnyCount);
        assert(Find(t, 5, 6, 1, 1)->f0 == 0.90f && Find(t, 5, 6, 1, 1)->tint == 0xffffff); // the mirror's default F0
        assert(Find(t, 7, 8, 1, 1)->f0 == 0.5f);
        assert(Find(t, 9, 10, 1, 1)->f0 == 0.04f && Find(t, 9, 10, 1, 1)->tint == 0x00ff00);
        assert(Parse("window:1:2:t12345").first_errors[0].reason == std::uint8_t(Reason::Tint));
        assert(Parse("window:1:2:t1234567").first_errors[0].reason == std::uint8_t(Reason::Tint));
        assert(Parse("window:1:2:tgggggg").first_errors[0].reason == std::uint8_t(Reason::Tint));
        assert(Parse("window:1:2:f1.5").first_errors[0].reason == std::uint8_t(Reason::F0));
        assert(Parse("window:1:2:f").first_errors[0].reason == std::uint8_t(Reason::F0));
        assert(Parse("window:1:2:f-0.1").first_errors[0].reason == std::uint8_t(Reason::F0));
        assert(Parse("window:1:2:f0.1.2").first_errors[0].reason == std::uint8_t(Reason::F0));
        assert(Parse("window:1:2:f1").entries[0].f0 == 1.0f && Parse("window:1:2:f0").entries[0].f0 == 0.0f);
        assert(Parse("window:1:2:t000000:t111111").first_errors[0].reason == std::uint8_t(Reason::Field));
        assert(Parse("window:1:2:f0.1:f0.2").first_errors[0].reason == std::uint8_t(Reason::Field));
        assert(Parse("window:1:2:t000000:5").first_errors[0].reason == std::uint8_t(Reason::Field)); // no number after t
    }

    // h. a duplicate (the same pair, count and first index) is skipped and said; the same pair with another count is not.
    {
        const Table t = Parse("window:1:2:5;window:1:2:5;window:1:2:6;window:1:2:5:7");
        assert(t.count == 3 && t.errors == 1 && t.first_errors[0].ordinal == 2 &&
               t.first_errors[0].reason == std::uint8_t(Reason::Duplicate));
        // the user's own copy of a built-in entry is a duplicate of it
        assert(Parse("builtin;mirror:9da6aacb:ca7226ec:24").errors == 1);
        assert(Parse("mirror:9da6aacb:ca7226ec:24;builtin").errors == 1 && Parse("mirror:9da6aacb:ca7226ec:24;builtin").count == 2);
    }

    // i. 64 entries fit, the 65th is TooMany (and the rest are said as errors, four kept).
    {
        std::string text;
        for (int i = 1; i <= 64; ++i) {
            text += "window:" + std::to_string(i) + ":1;"; // hex digits: 1..9 read the same; 10..64 are 0x10..0x64
        }
        const Table full = Parse(text.c_str());
        assert(full.on && full.count == MaxEntries && full.errors == 0);
        for (int i = 1; i <= 64; ++i) {
            assert(Find(full, std::uint64_t(std::stoi(std::to_string(i), nullptr, 16)), 1, 1, 1) != nullptr);
        }
        assert(Find(full, 0x65, 1, 1, 1) == nullptr);
        const Table over = Parse((text + "window:65:1;window:66:1;builtin;window:67:1;window:68:1;window:69:1").c_str());
        assert(over.count == MaxEntries && over.errors == 6 && over.first_errors[0].ordinal == 65 &&
               over.first_errors[0].reason == std::uint8_t(Reason::TooMany) && over.first_errors[3].ordinal == 68);
        assert(Find(over, 0x65, 1, 1, 1) == nullptr);
        // every slot of a full table is findable (probing past the others)
        for (std::uint32_t i = 0; i < full.count; ++i) {
            const Entry& e = full.entries[i];
            assert(Lookup(full, e.vs, e.ps, 7, 7) == i + 1);
        }
    }

    // j. lookup order: first index given, then count given, then wildcard; a pair is found among others.
    {
        const Table t = Parse("window:1:2;window:1:2:24;window:1:2:24:100;mirror:3:4:8;bottle:5:6");
        assert(t.count == 5);
        assert(Find(t, 1, 2, 24, 100)->first_index == 100);
        assert(Find(t, 1, 2, 24, 101)->index_count == 24 && Find(t, 1, 2, 24, 101)->first_index == AnyFirst);
        assert(Find(t, 1, 2, 25, 100)->index_count == AnyCount);
        assert(Find(t, 1, 2, 25, AnyFirst)->index_count == AnyCount);
        assert(Find(t, 3, 4, 8, 0)->kind == Kind::Mirror && Find(t, 3, 4, 9, 0) == nullptr);
        assert(Find(t, 5, 6, 1, 1)->kind == Kind::Bottle && Find(t, 2, 1, 1, 1) == nullptr);
        // the table is sorted by pair: runs are contiguous
        std::size_t runs = 0;
        for (std::uint32_t i = 0; i < t.count; ++i) {
            runs += (i == 0 || t.entries[i].vs != t.entries[i - 1].vs || t.entries[i].ps != t.entries[i - 1].ps) ? 1 : 0;
        }
        assert(runs == 3);
        // an off table finds nothing
        assert(Lookup(Parse("off"), 1, 2, 1, 1) == 0);
    }

    // k. PairSlot: 7 bits.
    for (std::uint64_t v = 1; v < 5000; v += 7) {
        assert(PairSlot(v, v * 3 + 1) < Slots);
    }

    // l. the view knob.
    assert(ParseView(nullptr) == 0 && ParseView("") == 0 && ParseView("0") == 0 && ParseView("off") == 0);
    assert(ParseView("1") == 1 && ParseView("on") == 1);
    assert(ParseView("2") == 2 && ParseView("yes") == 2 && ParseView(" 1") == 2 && ParseView("true") == 2);

    // m. colours and names: window cyan, mirror magenta, bottle orange, lantern and cabinet yellow.
    assert((ViewColour(Kind::Window) == std::array<float, 3>{0.0f, 1.0f, 1.0f}));
    assert((ViewColour(Kind::Mirror) == std::array<float, 3>{1.0f, 0.0f, 1.0f}));
    assert((ViewColour(Kind::Bottle) == std::array<float, 3>{1.0f, 0.5f, 0.0f}));
    assert((ViewColour(Kind::Lantern) == std::array<float, 3>{1.0f, 1.0f, 0.0f}));
    assert((ViewColour(Kind::Cabinet) == ViewColour(Kind::Lantern)));
    assert(std::string(KindName(Kind::Window)) == "window" && std::string(KindName(Kind::Cabinet)) == "cabinet");
    for (std::uint8_t r = 0; r <= std::uint8_t(Reason::Duplicate); ++r) {
        assert(std::string(ReasonName(r)) != "unknown");
    }

    // n. the built-in entries and the numbers the shader shares.
    assert(BuiltIn[0].vs == MirrorVs && BuiltIn[0].index_count == 24 && BuiltIn[0].first_index == AnyFirst);
    assert(BuiltIn[1].vs == WindowVs && BuiltIn[1].index_count == 324);
    assert(ViewGroup == 8 && MaxEntries == 64 && Slots == 128);

    std::puts("glass registry: ok");
    return 0;
}
''',
}

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new.
EDITS = {
RH: [
("ins", '#include "video_core/renderer_vulkan/vk_blood_sheen.h" // bbport (r100_blood-sheen)\n',
 "",
 '#include "video_core/renderer_vulkan/vk_glass_view.h" // bbport (r129a_glass-registry)\n'),
("ins", "    std::unique_ptr<BloodSheen> blood_sheen;\n",
 "",
 "    /// bbport (r129a_glass-registry): made only with BB_GLASS_TABLE naming a valid entry (GlassRegistryRules::Load), else null:\n"
 "    /// the draw hook is one null pointer test. glass_view: also BB_GLASS_VIEW=1 or the live knobs file (GlassView::Wanted).\n"
 "    std::unique_ptr<GlassRegistry> glass_registry;\n"
 "    std::unique_ptr<GlassView> glass_view;\n"
 "    /// bbport (r129a_glass-registry): from DrawRecord, right before EffectsBeforeResources, only with glass_registry:\n"
 "    /// looks the draw up, counts a hit, sets DrawContext::glass_hit and, with the view on, records the SNAPSHOT.\n"
 "    void GlassRegistryDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset);\n"),
("ins", "        DrawInputs draw_inputs{};\n",
 "",
 "        /// bbport (r129a_glass-registry): the registry entry of the draw being recorded, index + 1 (0: none); set by\n"
 "        /// GlassRegistryDraw only, so 0 while the registry is off; valid to the end of DrawRecord.\n"
 "        u8 glass_hit = 0;\n"),
],
RC: [
("ins", "    if (GlassGlint::Wanted()) {\n",
 "    // bbport (r129a_glass-registry): BB_GLASS_TABLE naming a valid entry only (read once); otherwise no GlassRegistry and no\n"
 "    // GlassView are made and the draw hook is one null pointer test. The view is made with BB_GLASS_VIEW=1 or the live knobs\n"
 "    // file; its pipelines and images are made at the first hit draw with the view on (vk_glass_view.h).\n"
 "    if (GlassRegistryRules::Load().on) {\n"
 "        glass_registry = std::make_unique<GlassRegistry>();\n"
 "        if (GlassView::Wanted()) {\n"
 "            glass_view = std::make_unique<GlassView>(instance, scheduler, texture_cache, runtime, *scene_targets,\n"
 "                                                     *camera_motion);\n"
 "        }\n"
 "    } else {\n"
 "        GlassRegistry::SayOff(); // prints only when the table or BB_GLASS_VIEW was given\n"
 "    }\n",
 ""),
("ins", "    EffectsBeforeResources(pipeline);\n",
 "    if (glass_registry) { // bbport (r129a_glass-registry): off: this null test alone\n"
 "        GlassRegistryDraw(pipeline, is_indexed, index_offset);\n"
 "    }\n",
 ""),
],
RE: [
("ins", "        .pixel_shader = ps ? ps->pgm_hash : 0, // bbport (r50_leaf-stage1)\n",
 "",
 "        .glass_entry = dc.glass_hit, // bbport (r129a_glass-registry): 0 while the registry is off (S1 reads it)\n"),
("ins", "        blood_sheen->Show(cb_descs[0].first, point_shadow->Pending());\n    }\n",
 "",
 "    // bbport (r129a_glass-registry): BB_GLASS_VIEW on only (off: one null pointer test): the tagged pixels of the registry's\n"
 "    // G-buffer hit draws painted over the lit scene, once after each G-buffer pass's opaque lighting (vk_glass_view.h).\n"
 "    if (glass_view) {\n"
 "        glass_view->Show(cb_descs[0].first, point_shadow->Pending());\n"
 "    }\n"),
("ins", "    if (glass_glint) { // bbport (r86b_glass-visible); a noted pane draw never made is forgotten\n",
 "    if (glass_view) { // bbport (r129a_glass-registry): first (drops a pending MARK), then the registry's frame counts\n"
 "        glass_view->OnFrameEnd();\n"
 "    }\n"
 "    if (glass_registry) {\n"
 "        glass_registry->OnFrameEnd();\n"
 "    }\n",
 ""),
],
TH: [
("ins", "        u32 find_flags = 0;\n",
 "",
 "        // bbport (r129a_glass-registry): the registry entry of this draw, index + 1 (0: none; always 0 while the registry\n"
 "        // is off). Unread in r129a; S1 reads it in PrepareDraw to withhold LampMask/ShadowMask and for the instance's tint.\n"
 "        u8 glass_entry = 0;\n"),
],
CM: [
("ins", "add_host_shader(blood_sheen.comp blood_sheen_show_comp BLOOD_SHOW=1)\n",
 "",
 "# bbport (r129a_glass-registry): the glass view's snapshot, mark (G-buffer hit draws), paint (forward hit draws) and show passes\n"
 "# (renderer_vulkan/vk_glass_view.cpp)\n"
 "add_host_shader(glass_view.comp glass_view_snapshot_comp GLASS_SNAPSHOT=1)\n"
 "add_host_shader(glass_view.comp glass_view_mark_comp GLASS_MARK=1)\n"
 "add_host_shader(glass_view.comp glass_view_paint_comp GLASS_PAINT=1)\n"
 "add_host_shader(glass_view.comp glass_view_show_comp GLASS_SHOW=1)\n"),
("ins", '    if (FILENAME MATCHES "^blood_sheen")\n        list(APPEND INCLUDES ${SHADER_SRC}/blood_sheen_layout.h)\n    endif()\n',
 "",
 "    # bbport (r129a_glass-registry): the glass view's numbers, shared with C++ (glass_registry.h)\n"
 '    if (FILENAME MATCHES "^glass_view")\n'
 "        list(APPEND INCLUDES ${SHADER_SRC}/glass_view_layout.h)\n"
 "    endif()\n"),
("ins", "add_executable(glass-glint-test EXCLUDE_FROM_ALL ../tests/test_glass_glint.cpp)\n"
        "target_compile_options(glass-glint-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
        "target_include_directories(glass-glint-test PRIVATE ..)\n",
 "",
 "# bbport (r129a_glass-registry): the glass registry's table text, lookup and view knob (glass_registry.h); also built and run\n"
 "# by engine/build.sh --test.\n"
 "add_executable(glass-registry-test EXCLUDE_FROM_ALL ../tests/test_glass_registry.cpp)\n"
 "target_compile_options(glass-registry-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(glass-registry-test PRIVATE ..)\n"),
],
BS: [
("ins", "    out/glass-glint-test\n",
 "",
 "    # bbport (r129a_glass-registry): the glass registry's table text, lookup and view knob\n"
 '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_glass_registry.cpp -o out/glass-registry-test\n'
 "    out/glass-registry-test\n"),
],
TP: [
("ins", '#include "video_core/host_shaders/blood_sheen_snapshot_comp.h" // bbport (r100_blood-sheen)\n',
 "",
 '#include "video_core/host_shaders/glass_view_mark_comp.h"     // bbport (r129a_glass-registry)\n'
 '#include "video_core/host_shaders/glass_view_paint_comp.h"    // bbport (r129a_glass-registry)\n'
 '#include "video_core/host_shaders/glass_view_show_comp.h"     // bbport (r129a_glass-registry)\n'
 '#include "video_core/host_shaders/glass_view_snapshot_comp.h" // bbport (r129a_glass-registry)\n'),
("ins", '        {"blood sheen show", BLOOD_SHEEN_SHOW_COMP, {eStorageImage, eStorageImage}, 32},\n',
 "",
 "        // bbport (r129a_glass-registry): as vk_glass_view.cpp makes them (GlassView::Push, 32 bytes)\n"
 '        {"glass view snapshot",\n'
 "         GLASS_VIEW_SNAPSHOT_COMP,\n"
 "         {eSampledImage, eSampledImage, eStorageImage, eStorageImage},\n"
 "         32},\n"
 '        {"glass view mark",\n'
 "         GLASS_VIEW_MARK_COMP,\n"
 "         {eSampledImage, eSampledImage, eStorageImage, eStorageImage},\n"
 "         32},\n"
 '        {"glass view paint", GLASS_VIEW_PAINT_COMP, {eSampledImage, eStorageImage, eStorageImage}, 32},\n'
 '        {"glass view show", GLASS_VIEW_SHOW_COMP, {eStorageImage, eSampledImage, eStorageImage}, 32},\n'),
],
}

ROW_TABLE = (
    "| `BB_GLASS_TABLE` | The glass registry (r129a_glass-registry, stage S0 of the glass plan: which draws are glass, of what kind, "
    "tint and F0; no light change, no change of the picture). Entries `kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0]` "
    "separated by `;` (not `,`; spaces around a field are skipped): `kind` is `window`, `mirror`, `bottle`, `lantern` or `cabinet`; "
    "`vs` and `ps` are the draw's shader hashes in hex (1 to 16 digits, an optional `0x`, not 0, as the probes print them); "
    "`indexcount` is the draw's index count in decimal (`0` or `*`: any; at most 100000000); `firstindex` is the draw's first index "
    "in decimal (`*`: any; `0` is the first index 0; a draw that is not indexed has none, and only `*` matches it); `t` and six hex "
    "digits is the tint (default `FFFFFF`; read by later stages); `f` and a number from 0 to 1 is the Fresnel F0 (default 0.04, "
    "mirror 0.90). The token `builtin` adds the measured entries: the Hunter's Dream house mirror `9da6aacb:ca7226ec` with 24 "
    "indices (no first index: it may change between loads) and the arch window `97f2d384:2390c887` with 324 indices (a G-buffer "
    "draw). Unset, empty, `0` or `off`: off, and the built-in entries are not taken. A bad entry is skipped and said in the log "
    "(the others stay); at most 64 entries; the same draw twice is skipped. Entries are sorted by pair; of one pair the most "
    "specific match wins (a first index given, then an index count given, then any). A `lantern` entry marks the whole draw (its "
    "panes are triangles inside the mesh: a later stage). Read once. Off costs one null pointer test a draw and a plain store of "
    "0 into the ray traced scene's draw record: no lookup, no allocation, no object. On: per direct draw a hash and a probe of a "
    "128-slot table, about 10 to 30 ns (an estimate, not measured), no GPU work. Log: once `Glass registry (r129a): "
    "BB_GLASS_TABLE=...: N entries (B built-in), E errors; view ...`, a line per entry, a line per bad entry (four at most), and "
    "every 600 frames the hits per entry; `... no valid entry, registry off` when nothing in the text was good | off |")
ROW_VIEW = (
    "| `BB_GLASS_VIEW` | Only with `BB_GLASS_TABLE` (r129a_glass-registry; a test view so that the owner can say that is the glass). "
    "`1` or `on`: the pixels each registry hit draw wrote are painted over the scene (window cyan, mirror magenta, bottle orange, "
    "lantern and cabinet yellow; the pixel moves 0.7 of the way to the colour times its luminance, at least 0.5); `0`, `off`, "
    "empty or unset: off; other text: off, said in the log. Live (the slot runner's `set:` action) in a build with the test "
    "tools' live knobs file (`BB_LIVE_KNOBS_FILE`), else read once. How: before a hit draw the colour target 0 and the depth are "
    "printed, after it the pixels whose print changed are tagged (a G-buffer draw: painted after the opaque lighting, and only "
    "where the depth is still the draw's, so a hunter in front of the mirror is not tinted) or painted at once (a forward draw "
    "to the RGBA16F scene colour). At most 8 hit draws a frame; none in a menu's 3D preview, in another camera's pass or while a "
    "lamps-apart batch is open (counted in the log). Cost, an estimate (not measured): about 0.1 ms for each hit draw at 1080p "
    "internal (two passes over the scene) and about 0.05 ms for each G-buffer lighting with a G-buffer hit; memory two 4-byte "
    "images of the scene's size (16.6 MB at 1080p internal), made at the first hit draw with the view on; the "
    "`Lighting: glass view` row of `BB_GPU_PROFILE=1`. With the view off, or no table, no object, pass or image is made. Log "
    "lines `Glass view (r129a): ...`: `view on at frame N` / `view off at frame N`, and every 600 frames the passes made and "
    "the reasons a hit draw was left out | off |")


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_RT_GLASS_STATIC` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_GLASS_STATIC row is there %d times, wanted 1" % len(lines))
    return [("ins", lines[0] + "\n", "", ROW_TABLE + "\n" + ROW_VIEW + "\n")]


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


def texts_check(texts, news):
    # new C++ lines (and the shader, and the other inserted code): no tabs, at most 150 columns
    for path, text in news.items():
        new_lines_check(path, text)
    for path, eds in EDITS.items():
        if path in (R, CM, BS):
            continue
        for e in eds:
            if e[0] == "ins":
                new_lines_check(path + " (inserted)", e[2] + e[3])
    reg, view, cpp = news[RV + "glass_registry.h"], news[RV + "vk_glass_view.h"], news[RV + "vk_glass_view.cpp"]
    # the built-in keys: pair plus index count only (no first index), the arch window's pair with 324
    for want in ("{0x9da6aacb, 0xca7226ec, 24, AnyFirst, 0xffffff, MirrorF0, Kind::Mirror, true},",
                 "{0x97f2d384, 0x2390c887, 324, AnyFirst, 0xffffff, DefaultF0, Kind::Window, true},"):
        if reg.count(want) != 1:
            raise SystemExit("text check: glass_registry.h built-in entry missing: %s" % want)
    if "inline constexpr std::array<Entry, 2> BuiltIn" not in reg or "MaxEntries = 64" not in reg:
        raise SystemExit("text check: glass_registry.h table size or built-in count")
    # the shader's four builds and the layout numbers C++ ties to
    comp = news[HS + "glass_view.comp"]
    for d in ("GLASS_SNAPSHOT", "GLASS_MARK", "GLASS_PAINT", "GLASS_SHOW"):
        if comp.count("defined(" + d + ")") < 2:
            raise SystemExit("text check: glass_view.comp does not use %s" % d)
    # the log lines start as asked
    for line in cpp.split("\n"):
        if "BbReport::Printf(" in line and '"' in line:
            first = line.split('"', 1)[1]
            if not (first.startswith("Glass registry (r129a)") or first.startswith("Glass view (r129a)")):
                raise SystemExit("text check: a log line does not start with Glass registry (r129a) or Glass view (r129a): %s" % line.strip())
    if cpp.count("Printf(\"Glass") < 8:
        raise SystemExit("text check: vk_glass_view.cpp has too few log lines")
    # the hook: one null test, before EffectsBeforeResources; the call is only inside it
    rc = texts[RC]
    i = rc.find("    if (glass_registry) { // bbport (r129a_glass-registry): off: this null test alone\n")
    j = rc.find("    EffectsBeforeResources(pipeline);\n")
    if not (0 <= i < j) or rc.count("GlassRegistryDraw(") != 1 or rc.count("if (glass_registry)") != 1:
        raise SystemExit("text check: the DrawRecord hook")
    if rc.count("glass_registry = std::make_unique<GlassRegistry>();") != 1 or rc.count("GlassRegistryRules::Load().on") != 1:
        raise SystemExit("text check: the constructor makes the registry only with a valid table")
    re_ = texts[RE]
    for want in (".glass_entry = dc.glass_hit,", "glass_view->Show(cb_descs[0].first, point_shadow->Pending());",
                 "glass_view->OnFrameEnd();", "glass_registry->OnFrameEnd();"):
        if re_.count(want) != 1:
            raise SystemExit("text check: vk_rasterizer_effects.cpp: %s is there %d times" % (want, re_.count(want)))
    if not (0 <= re_.find("glass_view->OnFrameEnd();") < re_.find("glass_registry->OnFrameEnd();")):
        raise SystemExit("text check: the view's frame end comes before the registry's")
    # RtShadow::Draw's new field is the last one of the struct (declared after find_flags)
    th = texts[TH]
    k = th.find("        u8 glass_entry = 0;\n")
    if not (th.count("u8 glass_entry = 0;") == 1 and th.find("        u32 find_flags = 0;\n") < k and
            th[k + len("        u8 glass_entry = 0;\n"):].lstrip().startswith("};")):
        raise SystemExit("text check: glass_entry is not the last member of RtShadow::Draw")
    # the shaders and the test are wired in CMake, build.sh and the pipeline test
    cm = texts[CM]
    for want in ("glass_view_snapshot_comp GLASS_SNAPSHOT=1", "glass_view_mark_comp GLASS_MARK=1",
                 "glass_view_paint_comp GLASS_PAINT=1", "glass_view_show_comp GLASS_SHOW=1",
                 'MATCHES "^glass_view"', "add_executable(glass-registry-test EXCLUDE_FROM_ALL ../tests/test_glass_registry.cpp)"):
        if cm.count(want) != 1:
            raise SystemExit("text check: CMakeLists.txt: %r is there %d times" % (want, cm.count(want)))
    if texts[BS].count("tests/test_glass_registry.cpp -o out/glass-registry-test") != 1 or texts[BS].count("out/glass-registry-test\n") != 2:
        raise SystemExit("text check: build.sh does not build and run the registry test once")
    tp = texts[TP]
    for n in ("SNAPSHOT", "MARK", "PAINT", "SHOW"):
        if tp.count("GLASS_VIEW_%s_COMP" % n) != 1 or tp.count("glass_view_%s_comp.h" % n.lower()) != 1:
            raise SystemExit("text check: test_effect_pipelines.cpp does not build the glass view %s pass once" % n)
    # one README row per knob, each with the default off
    for knob in ("BB_GLASS_TABLE", "BB_GLASS_VIEW"):
        rows = [l for l in texts[R].split("\n") if l.startswith("| `%s` |" % knob)]
        if len(rows) != 1 or not rows[0].endswith("| off |"):
            raise SystemExit("text check: README row of %s" % knob)
    # nothing else is touched: BB_RT_GLASS and instanceCustomIndex stay as they are
    for path in list(EDITS) + list(NEW):
        if "vk_rt_shadow.cpp" in path or "rt_glass" in path or "glint" in path:
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
        raise SystemExit("%s is not a source tree root (set R129A_ROOT)" % ROOT)
    plan = []
    for path in (RH, RC, RE, TH, CM, BS, TP, R):
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
            open(full + ".r129atmp", "wb").write(data)
        for full, data in writes:
            os.replace(full + ".r129atmp", full)
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
        open(full + ".r129atmp", "wb").write(out[path])
        os.replace(full + ".r129atmp", full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
