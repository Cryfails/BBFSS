// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r129a_glass-registry): the glass registry (stage S0 of the glass plan). BB_GLASS_TABLE names which draws are glass:
// entries "kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0]" separated by ';' (kinds window, mirror, bottle, lantern,
// cabinet; vs/ps hex pgm_hash, 1-16 digits, optional 0x; indexcount decimal, 0 or '*' = any; firstindex decimal or '*' = any,
// 0 is the first index 0; t = tint, default FFFFFF; f = Fresnel F0 0..1, default 0.04, mirror 0.90). The token "builtin" adds
// the measured entries (dream house mirror pair 9da6aacb:ca7226ec with 24 indices, arch window 97f2d384:2390c887 with 324
// indices; no first index, it may change between loads). Unset, empty, "0" or "off": off, and never the built-in table. A bad
// entry is skipped and said; at most 64 entries.
// bbport (r130c_glass-lamp-light): entries gain [:sS] (kind:vs:ps[:indexcount[:firstindex]][:tRRGGBB][:fF0][:sS]): s = the
// strength of lamp light through the glass, 0..1 (BB_GLASS_LIGHT; default by kind: window and cabinet 0.90, lantern 0.85, bottle
// 0.75; the mirror does not transmit). Same place as t and f: after the numbers, once, any order.
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

enum class Reason : u8 { Kind, Vs, Ps, Count, First, Tint, F0, Field, TooMany, Duplicate, Strength };

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
    float strength = -1.0f; // bbport (r130c_glass-lamp-light): the s token, 0..1; below 0: the kind's default (glass_light.h)
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
    bool numbers = true, have_tint = false, have_f0 = false, have_strength = false;
    for (std::size_t i = 3; i < n; ++i) {
        const Span s = field[i];
        const char c = s.b < s.e ? text[s.b] : '\0';
        if (c == 't') {
            if (have_tint || !ReadTint(text, s, entry.tint)) {
                return int(have_tint ? Reason::Field : Reason::Tint);
            }
            have_tint = true;
            numbers = false;
        } else if (c == 's') { // bbport (r130c_glass-lamp-light): the strength of light through the glass
            if (have_strength || !ReadUnit(text, {s.b + 1, s.e}, entry.strength)) {
                return int(have_strength ? Reason::Field : Reason::Strength);
            }
            have_strength = true;
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

// bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR and BB_GLASS_CLEAR_FILM. The kinds whose pane leaves the opaque G-buffer and
// comes back as a glass layer (vk_glass_clear.h): the cabinet only. The mirror is the same shader pair with 24 indices (it has its
// own entry, kind mirror) and stays as it is.
constexpr bool Clears(Kind k) {
    return k == Kind::Cabinet;
}
inline constexpr float ClearFilmDefault = 0.12f, ClearFilmMax = 0.5f, ClearHoleMetres = 1.5f;

/// BB_GLASS_CLEAR's text: the rules of BB_GLASS_VIEW: 0 off (nullptr, "", "0", "off"), 1 on ("1", "on"), 2 unreadable.
constexpr u8 ParseClear(const char* text) {
    return ParseView(text);
}

/// BB_GLASS_CLEAR_FILM's text: a number from 0 to 1, taken at most ClearFilmMax; unset, empty or unreadable: ClearFilmDefault.
constexpr float ParseClearFilm(const char* text) {
    if (text == nullptr) {
        return ClearFilmDefault;
    }
    float v = 0.0f;
    if (!Detail::ReadUnit(text, Detail::Trim(text, 0, Detail::Length(text)), v)) {
        return ClearFilmDefault;
    }
    return v > ClearFilmMax ? ClearFilmMax : v;
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
    case Reason::Strength:
        return "strength is not s and a number from 0 to 1";
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
static_assert(Clears(Kind::Cabinet) && !Clears(Kind::Mirror) && !Clears(Kind::Window) && !Clears(Kind::Bottle) &&
              !Clears(Kind::Lantern) && !Clears(Kind::None)); // bbport (r131c_cabinet-glass-clear)
static_assert(ParseClear(nullptr) == 0 && ParseClear("1") == 1 && ParseClear("") == 0 && ParseClear("yes") == 2);
static_assert(ParseClearFilm(nullptr) == ClearFilmDefault && ParseClearFilm("") == ClearFilmDefault &&
              ParseClearFilm("0") == 0.0f && ParseClearFilm("0.3") == 0.3f && ParseClearFilm("0.9") == ClearFilmMax &&
              ParseClearFilm("x") == ClearFilmDefault && ParseClearFilm("2") == ClearFilmDefault);
static_assert(Parse("window:1:2:s0.5").entries[0].strength == 0.5f && Parse("window:1:2").entries[0].strength < 0.0f &&
              Parse("window:1:2:s2").errors == 1 && Parse("builtin").entries[0].strength < 0.0f);

} // namespace Vulkan::GlassRegistryRules
