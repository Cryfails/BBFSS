// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89i_twigs-colour-pass): the colour-pass census and its knobs (shim/bbport_wind_census.h).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>

#include "gpu/shim/bbport_wind_census.h"

namespace C = BbWindCensus;

static int failures = 0;

static void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

// A draw of `indices` indices in the row of (pipeline, stream); the row's facts are set when it is new.
static C::Row* Add(C::Book& book, std::uintptr_t pipeline, std::uint64_t stream, C::Target target,
                   std::uint32_t indices, bool sway_bit, bool motion, bool cutout) {
    bool fresh = false;
    C::Row* const row = book.Touch(pipeline, stream, fresh);
    if (row == nullptr) {
        return nullptr;
    }
    if (fresh) {
        row->target = target;
        row->sway_bit = sway_bit;
        row->motion = motion;
        row->cutout = cutout;
    }
    C::Count(*row, C::KindStatic, indices, 0, 0, false);
    return row;
}

static bool Contains(const std::vector<const C::Row*>& rows, std::uintptr_t pipeline) {
    for (const C::Row* r : rows) {
        if (r->pipeline == pipeline) {
            return true;
        }
    }
    return false;
}

int main() {
    // The knobs: unset is census off, palette on, statics 1; numbers as the wind knobs read them.
    {
        const C::Knob d = C::ParseKnob(nullptr, nullptr, nullptr);
        Expect(!d.census && d.palette && d.statics == 1, "defaults: census off, palette on, statics 1");
        const C::Knob off = C::ParseKnob("1", "0", "0");
        Expect(off.census && !off.palette && off.statics == 0, "1, 0, 0");
        const C::Knob odd = C::ParseKnob("x", "nan", "2");
        Expect(!odd.census && odd.palette && odd.statics == 2, "unreadable: the default; statics 2");
        Expect(C::ParseKnob(nullptr, nullptr, "9").statics == 2, "statics above 2: 2");
        Expect(C::ParseKnob(nullptr, nullptr, "0.4").statics == 0, "statics 0.4: 0");
        Expect(C::ParseKnob(nullptr, nullptr, "1.2").statics == 1, "statics 1.2: 1");
        Expect(C::ParseKnob("", "", "").statics == 1 && C::ParseKnob("", "", "").palette, "empty: the default");
        // no BB_WIND here: the twigs are off, so nothing is asked of the pipelines
        Expect(!C::CensusOn() && !C::PaletteOn() && !C::StaticCutouts() && !C::StaticOpaque() &&
                   !C::StaticWanted(true) && !C::StaticWanted(false),
               "the twigs off: no census, no widening");
    }

    // The book: one row for a (pipeline, stream), a new one is fresh, RowsMost rows at most.
    {
        C::Book book;
        bool fresh = false;
        C::Row* const a = book.Touch(1, 10, fresh);
        Expect(a != nullptr && fresh, "a new row is fresh");
        C::Row* const again = book.Touch(1, 10, fresh);
        Expect(again == book.Rows().data() && !fresh, "the same key: the same row, not fresh");
        Expect(book.Touch(1, 11, fresh) != nullptr && fresh, "another stream: a new row");
        Expect(book.Touch(2, 10, fresh) != nullptr && fresh, "another pipeline: a new row");
        Expect(book.Rows().size() == 3, "three rows");
        for (std::uintptr_t i = 0; i < C::RowsMost + 3; ++i) {
            (void)book.Touch(100 + i, 0, fresh);
        }
        Expect(book.Rows().size() == C::RowsMost, "no more than RowsMost rows");
        Expect(book.overflow == 6, "rows over the limit are counted");
        Expect(book.Touch(1, 10, fresh) != nullptr && !fresh, "a known row is found when the book is full");
        book.Clear();
        Expect(book.Rows().empty() && book.overflow == 0 && book.draws[0] == 0, "Clear");
    }

    // Count: indices, the largest draw, the kind slots (above the last: the last), the sway words.
    {
        C::Row r;
        C::Count(r, C::KindSkinned, 300, 5, 7, true);
        C::Count(r, C::KindPalette, 900, 11, -3, false);
        C::Count(r, 99, 100, 1, 1, true);
        Expect(r.draws == 3 && r.indices == 1300, "draws and indices");
        Expect(r.max_indices == 900 && r.max_first == 11 && r.max_base == -3,
               "the largest draw's first index and base");
        Expect(r.kind[C::KindSkinned] == 1 && r.kind[C::KindPalette] == 1 && r.kind[C::KindNone] == 1,
               "kind slots, an unknown slot is the last");
        Expect(r.swayed == 2, "swayed draws");
    }

    // Why: the reason a row got no word.
    {
        C::Row r;
        r.target = C::Target::Sun;
        Expect(std::strstr(C::Why(r, true), "sun shadow") != nullptr, "sun row");
        r.target = C::Target::Gbuffer;
        r.motion = false;
        r.cutout = true;
        Expect(std::strstr(C::Why(r, true), "BB_WIND_TWIGS_STATIC=1") != nullptr,
               "cut-out without a motion pipeline");
        r.cutout = false;
        Expect(std::strstr(C::Why(r, true), "STATIC=2") != nullptr, "opaque without a motion pipeline");
        r.motion = true;
        Expect(std::strstr(C::Why(r, true), "without the sway bit") != nullptr, "motion pipeline, no sway bit");
        r.sway_bit = true;
        r.kind[C::KindPalette] = 4;
        Expect(std::strstr(C::Why(r, false), "BB_WIND_TWIGS_PALETTE=1") != nullptr, "GPU palette, knob off");
        Expect(std::strstr(C::Why(r, true), "refused it") != nullptr, "sway bit, rule refused");
        r.swayed = 1;
        Expect(std::strcmp(C::Why(r, true), "swayed") == 0, "swayed");
        r.swayed = 0;
        r.motion = false;
        r.sway_bit = false;
        Expect(std::strlen(C::Why(r, false)) < 130, "reasons stay short");
    }

    // Pick: the top G-buffer rows, the sway rows not named yet, the top sun rows; most indices first.
    {
        C::Book book;
        for (std::uintptr_t i = 1; i <= 12; ++i) {
            (void)Add(book, i, i, C::Target::Gbuffer, static_cast<std::uint32_t>(i * 1000), false, true, true);
        }
        (void)Add(book, 50, 1, C::Target::Gbuffer, 5, true, true, true);  // a small row with the sway bit
        (void)Add(book, 51, 1, C::Target::Gbuffer, 6, true, true, true);  // another
        (void)Add(book, 12, 99, C::Target::Gbuffer, 4, true, true, true); // a sway row of a top pipeline's other stream
        for (std::uintptr_t i = 1; i <= 5; ++i) {
            (void)Add(book, 200 + i, 0, C::Target::Sun, static_cast<std::uint32_t>(i * 10), false, false, true);
        }
        const std::vector<const C::Row*> picked = C::Pick(book);
        Expect(picked.size() == C::TopLines + 3 + C::SunLines, "10 top rows, 3 sway rows, 3 sun rows");
        Expect(picked.front()->pipeline == 12 && picked.front()->stream == 12, "the row with the most indices is first");
        Expect(picked[1]->indices == 11000 && picked[C::TopLines - 1]->indices == 3000, "most indices first");
        Expect(!Contains(picked, 1) && !Contains(picked, 2), "the two smallest of the 12 are not named");
        Expect(Contains(picked, 50) && Contains(picked, 51) && Contains(picked, 12), "the sway rows are named");
        Expect(Contains(picked, 205) && Contains(picked, 203) && !Contains(picked, 202), "the 3 biggest sun rows");
        const C::Totals t = C::TotalsOf(book);
        Expect(t.gbuf_rows == 15 && t.sun_rows == 5 && t.sway_rows == 3, "rows by target and the sway bit");
        Expect(t.gbuf_draws == 15 && t.sun_draws == 5 && t.gbuf_sway == 3 && t.gbuf_cutout == 15, "draws by target");
        Expect(t.gbuf_motion == 15 && t.gbuf_swayed == 0, "motion draws and swayed draws");
    }

    // The log lines stay under 700 characters, at the largest numbers, and say the facts.
    {
        C::Row r;
        r.pipeline = 0x1234;
        r.stream = 0x7fffffffffffull;
        r.vs = 0x6a833138u;
        r.ps = 0x1c3953c6u;
        r.targets = 5;
        r.format = 9;
        r.depth_w = 3840;
        r.depth_h = 2160;
        r.cutout = true;
        r.motion = true;
        r.sway_bit = true;
        r.depth_write = true;
        r.stream_verts = 156641;
        r.stride = 12;
        C::Count(r, C::KindStatic, 960, 0, 0, true);
        char text[720];
        C::RowLine(r, 1, true, text, sizeof(text));
        Expect(std::strstr(text, "vs 6a833138 ps 1c3953c6") != nullptr && std::strstr(text, "sway bit YES") != nullptr &&
                   std::strstr(text, "G-buffer pass, 5 colour targets") != nullptr &&
                   std::strstr(text, "stream 156641 vertices at stride 12") != nullptr &&
                   std::strstr(text, "index values not read") != nullptr &&
                   std::strstr(text, ", 1 swayed; 960 indices") != nullptr,
               "the row line's facts");
        r.vmin = 3;
        r.vmax = 959;
        C::RowLine(r, 1, true, text, sizeof(text));
        Expect(std::strstr(text, "index values 3-959") != nullptr, "the index range");
        // the largest numbers
        r.draws = r.indices = r.max_indices = std::numeric_limits<std::uint64_t>::max();
        r.swayed = std::numeric_limits<std::uint64_t>::max();
        for (std::uint64_t& k : r.kind) {
            k = std::numeric_limits<std::uint64_t>::max();
        }
        r.max_first = 0xffffffffu;
        r.max_base = std::numeric_limits<std::int32_t>::min();
        r.stream_verts = 0xffffffffu;
        r.stride = 0xffffffffu;
        r.vmin = 0;
        r.vmax = 0xfffffffeu;
        r.sway_bit = true;
        r.swayed = 0;
        r.motion = false;
        r.cutout = false;
        C::RowLine(r, 99, false, text, sizeof(text));
        Expect(std::strlen(text) < 700 && std::strlen(text) + 1 < sizeof(text), "the row line at the largest numbers");

        C::Book book;
        (void)Add(book, 1, 1, C::Target::Gbuffer, 100, true, true, true);
        char header[720];
        C::HeaderLine(book, true, C::ParseKnob(nullptr, nullptr, nullptr), header, sizeof(header));
        Expect(std::strstr(header, "G-buffer 1 draws on 1 rows (1 cut-out, 1 on motion pipelines, 1 on pipelines with "
                                   "the sway bit, 0 given a sway word)") != nullptr,
               "the header line's counts");
        Expect(std::strlen(header) < 700, "the header line is under 700 characters");
        char once[720];
        C::OnceText(C::ParseKnob("1", "1", "2"), once, sizeof(once));
        Expect(std::strncmp(once, "Wind twigs (r89i, BB_WIND_TWIGS_PALETTE=1, BB_WIND_TWIGS_STATIC=2, BB_WIND_TWIGS_CENSUS=1)", 90) == 0 &&
                   std::strlen(once) < 700,
               "the once line");
    }

    if (failures == 0) {
        std::printf("wind-census-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
