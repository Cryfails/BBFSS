// SPDX-License-Identifier: GPL-3.0-or-later
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
    for (std::uint8_t r = 0; r <= std::uint8_t(Reason::Strength); ++r) {
        assert(std::string(ReasonName(r)) != "unknown");
    }

    // n. the built-in entries and the numbers the shader shares.
    assert(BuiltIn[0].vs == MirrorVs && BuiltIn[0].index_count == 24 && BuiltIn[0].first_index == AnyFirst);
    assert(BuiltIn[1].vs == WindowVs && BuiltIn[1].index_count == 324);
    assert(ViewGroup == 8 && MaxEntries == 64 && Slots == 128);

    // o. bbport (r130c_glass-lamp-light): the s token (strength 0..1): after the numbers, once, any order; default below 0.
    {
        const Table t = Parse("window:1:2:s0.5;bottle:3:4:t102030:s.25:f0.1;mirror:5:6;lantern:7:8:s1;cabinet:9:a:s0");
        assert(t.errors == 0 && t.count == 5);
        assert(Find(t, 1, 2, 1, 1)->strength == 0.5f && Find(t, 3, 4, 1, 1)->strength == 0.25f);
        assert(Find(t, 3, 4, 1, 1)->tint == 0x102030 && Find(t, 3, 4, 1, 1)->f0 == 0.1f);
        assert(Find(t, 5, 6, 1, 1)->strength < 0.0f && Find(t, 7, 8, 1, 1)->strength == 1.0f);
        assert(Find(t, 9, 10, 1, 1)->strength == 0.0f);
        assert(Parse("window:1:2:s1.5").first_errors[0].reason == std::uint8_t(Reason::Strength));
        assert(Parse("window:1:2:s").first_errors[0].reason == std::uint8_t(Reason::Strength));
        assert(Parse("window:1:2:s0.1:s0.2").first_errors[0].reason == std::uint8_t(Reason::Field));
        assert(Parse("window:1:2:s0.5:7").first_errors[0].reason == std::uint8_t(Reason::Field)); // no number after s
        assert(Parse("builtin").entries[0].strength < 0.0f && Parse("builtin").errors == 0);
    }

    // bbport (r131c_cabinet-glass-clear): the cabinet's pane is keyed alone: the mirror (24 indices) and the pair's other draws are not it.
    {
        const Table t = Parse("builtin;cabinet:9da6aacb:ca7226ec:255");
        assert(t.errors == 0 && t.count == 3);
        const u8 pane = Lookup(t, 0x9da6aacb, 0xca7226ec, 255, 1), mirror = Lookup(t, 0x9da6aacb, 0xca7226ec, 24, 2440816);
        assert(pane != 0 && mirror != 0 && pane != mirror);
        assert(t.entries[pane - 1].kind == Kind::Cabinet && Clears(t.entries[pane - 1].kind));
        assert(t.entries[mirror - 1].kind == Kind::Mirror && !Clears(t.entries[mirror - 1].kind));
        assert(Lookup(t, 0x9da6aacb, 0xca7226ec, 12720, 455504) == 0 && Lookup(t, 0x9da6aacb, 0xca7226ec, 162096, 0) == 0);
        assert(Lookup(t, 0x9da6aacb, 0xca7226ec, 64836, 0) == 0);
        // the rules of the knobs
        assert(ParseClear(nullptr) == 0 && ParseClear("") == 0 && ParseClear("0") == 0 && ParseClear("off") == 0);
        assert(ParseClear("1") == 1 && ParseClear("on") == 1 && ParseClear("yes") == 2);
        assert(ParseClearFilm(nullptr) == ClearFilmDefault && ParseClearFilm("") == ClearFilmDefault);
        assert(ParseClearFilm("0") == 0.0f && ParseClearFilm("0.5") == 0.5f && ParseClearFilm("0.7") == ClearFilmMax);
        assert(ParseClearFilm("0.25") == 0.25f && ParseClearFilm("x") == ClearFilmDefault && ParseClearFilm("3") == ClearFilmDefault);
        assert(ClearFilmDefault == 0.12f && ClearHoleMetres == 1.5f);
    }

    std::puts("glass registry: ok");
    return 0;
}
