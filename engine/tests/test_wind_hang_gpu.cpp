// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112p_hang-gpu-palette-lanterns): skinned hanging things the CPU palette test refuses
// (gpu/shim/bbport_wind_hang_gpu.h): the knobs, the kinds, who the GPU box judge may take (BoxJudgeable), the
// page tests, the census and its line, the palette writer watch, the book's new reason (5) and box route, the texts.
// The twin in Python (r112p_twin.py) holds the same cases.
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_find.h"
#include "gpu/shim/bbport_wind_hang_gpu.h"

namespace G = BbWindHangGpu;
namespace S = BbWindHangStill;
namespace F = BbWindHangFind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Has(const std::string& text, const char* needle) {
    return text.find(needle) != std::string::npos;
}

S::Entry MakeEntry(std::uint32_t bones, S::Why never) {
    S::Entry e;
    e.size = bones * S::BoneBytes;
    e.bones = bones;
    e.never = never;
    return e;
}

G::Item MakeItem(std::uint64_t stream, G::Kind kind, bool box) {
    G::Item item;
    item.stream = stream;
    item.address = 0x7f0000001000ull + stream * 0x40;
    item.size = 4032;
    item.bones = 84;
    item.kind = kind;
    item.modified = true;
    item.box = box;
    return item;
}
} // namespace

int main() {
    // the knobs
    Expect(G::ParseMode(nullptr) == G::Mode::All && G::ParseMode("1") == G::Mode::All && G::ParseMode("") == G::Mode::All &&
               G::ParseMode("00") == G::Mode::All && G::ParseMode("Unread") == G::Mode::All && G::ParseMode("0") == G::Mode::Off &&
               G::ParseMode("unread") == G::Mode::Unread,
           "knobs: BOXJUDGE is all unless exactly 0 (off) or unread");
    Expect(std::string(G::ModeName(G::Mode::Off)) == "OFF" && std::string(G::ModeName(G::Mode::Unread)) == "unread" &&
               std::string(G::ModeName(G::Mode::All)) == "all",
           "knobs: mode names");
    Expect(G::ParseBones(nullptr) == 96 && G::ParseBones("200") == 200 && G::ParseBones("5") == G::BonesMin &&
               G::ParseBones("9999") == G::BonesMax && G::ParseBones("abc") == 96 && G::ParseBones("nan") == 96 &&
               G::ParseBones("") == 96,
           "knobs: the bone cap defaults to 96 and is held to 13 to 341");

    // the kinds
    const S::Entry gpu84 = MakeEntry(84, S::Why::GpuWritten);
    const S::Entry unmapped = MakeEntry(28, S::Why::NotMapped);
    const S::Entry shorter = MakeEntry(48, S::Why::Short);
    const S::Entry pivot = MakeEntry(13, S::Why::NoPivot);
    const S::Entry nopal = MakeEntry(0, S::Why::NoPalette);
    const S::Entry character = MakeEntry(277, S::Why::Character);
    const S::Entry plain = MakeEntry(69, S::Why::None);
    Expect(G::KindOf(&gpu84, S::Result::Never) == G::Kind::Gpu && G::KindOf(&unmapped, S::Result::Never) == G::Kind::Unmapped &&
               G::KindOf(&shorter, S::Result::Never) == G::Kind::Short && G::KindOf(&pivot, S::Result::Never) == G::Kind::Pivot &&
               G::KindOf(&nopal, S::Result::Never) == G::Kind::NoPal &&
               G::KindOf(&character, S::Result::Never) == G::Kind::Character &&
               G::KindOf(&plain, S::Result::Moved) == G::Kind::Moved && G::KindOf(&plain, S::Result::Same) == G::Kind::Same &&
               G::KindOf(nullptr, S::Result::Never) == G::Kind::Other && G::KindOf(&plain, S::Result::Never) == G::Kind::Other &&
               G::KindOf(nullptr, S::Result::Moved) == G::Kind::Moved,
           "kinds: each refusal has its own kind");
    Expect(std::string(G::KindName(G::Kind::Gpu)) == "gpu" && std::string(G::KindName(G::Kind::Moved)) == "moved" &&
               std::string(G::KindName(G::Kind::Character)) == "char" && std::string(G::KindName(G::Kind::Other)) == "other",
           "kinds: names");

    // who the GPU box judge may take
    Expect(G::BoxJudgeable(&gpu84, S::Result::Never, 96) && G::BoxJudgeable(&unmapped, S::Result::Never, 96) &&
               G::BoxJudgeable(&shorter, S::Result::Never, 96) && G::BoxJudgeable(&pivot, S::Result::Never, 96),
           "judge: a palette that could not be read, up to the cap, goes to the GPU box");
    Expect(!G::BoxJudgeable(&gpu84, S::Result::Never, 60) && G::BoxJudgeable(&gpu84, S::Result::Never, 84),
           "judge: the cap is the V#'s bones: 84 bones need a cap of 84");
    const S::Entry big_gpu = MakeEntry(128, S::Why::GpuWritten);
    Expect(!G::BoxJudgeable(&big_gpu, S::Result::Never, 96) && G::BoxJudgeable(&big_gpu, S::Result::Never, 200),
           "judge: 128 unread bones stay refused at the default cap and are taken when the cap is raised");
    Expect(!G::BoxJudgeable(&character, S::Result::Never, 341), "judge: a readable palette of more than 96 bones is a character, never judged");
    Expect(G::BoxJudgeable(&plain, S::Result::Moved, 96) && !G::BoxJudgeable(&plain, S::Result::Same, 96) &&
               !G::BoxJudgeable(&plain, S::Result::Never, 96),
           "judge: a palette whose content moved goes to the box, a still one needs no judge, no reason is no case");
    Expect(!G::BoxJudgeable(&plain, S::Result::Moved, 96, false) && G::BoxJudgeable(&gpu84, S::Result::Never, 96, false) &&
               G::BoxJudgeable(&plain, S::Result::Moved, 96, true),
           "judge: Mode::Unread leaves the moved content out and keeps the unread palettes");
    Expect(!G::BoxJudgeable(&nopal, S::Result::Never, 96) && !G::BoxJudgeable(nullptr, S::Result::Never, 96) &&
               !G::BoxJudgeable(nullptr, S::Result::Moved, 96),
           "judge: no bones, no palette entry: refused");

    // the page tests
    Expect(G::SharePage(0x1000, 0x40, 0x1ff0, 0x20) && !G::SharePage(0x1000, 0x40, 0x2000, 0x10) &&
               G::SharePage(0x1fff, 2, 0x2000, 1) && !G::SharePage(0x1000, 0, 0x1000, 8) && !G::SharePage(0x1000, 8, 0x1000, 0),
           "pages: sharing a 4 KiB page, the end of the last page counts, empty ranges share nothing");
    Expect(G::Holds(0x1000, 0x1000, 0x1100, 0x40) && !G::Holds(0x1000, 0x100, 0x10f0, 0x40) && G::Holds(0x1000, 0x40, 0x1000, 0x40) &&
               !G::Holds(0x1100, 0x40, 0x1000, 0x40),
           "pages: a range holds another only when all of it lies inside");

    // the census
    {
        G::Census census;
        Expect(census.Size() == 0, "census: starts empty");
        std::string line;
        Expect(!census.TakeLine(G::Mode::All, 96, line), "census: nothing noted, no line");
        Expect(census.Note(MakeItem(1, G::Kind::Gpu, true)) && !census.Note(MakeItem(1, G::Kind::Gpu, true)),
               "census: a new stream is news, the same again is not");
        Expect(census.Note(MakeItem(2, G::Kind::Moved, false)) && census.Note(MakeItem(1, G::Kind::Gpu, false)),
               "census: a changed route is news again");
        Expect(census.Size() == 2 && census.Count(G::Kind::Gpu, false) == 1 && census.Count(G::Kind::Gpu, true) == 0 &&
                   census.Count(G::Kind::Moved, false) == 1 && census.Boxed() == 0,
               "census: counts by kind and route");
        census.Note(MakeItem(3, G::Kind::Gpu, true));
        census.Note(MakeItem(4, G::Kind::Moved, true));
        Expect(census.Boxed() == 2 && census.Count(G::Kind::Moved, true) == 1, "census: boxed streams");
        Expect(census.TakeLine(G::Mode::All, 96, line), "census: a change gives a line");
        Expect(Has(line, "GLINT-PROOF hang box (r112p): 4 refused streams") && Has(line, "gpu 1+1") && Has(line, "content moved 1+1") &&
                   Has(line, "box judge all up to 96 bones") && Has(line, "2 judged, 2 turned away") && Has(line, "84b 4032B") &&
                   Has(line, "-> box") && Has(line, "-> refused") && line.size() <= G::LineChars,
               "census: the line says what the streams are");
        Expect(!census.TakeLine(G::Mode::All, 96, line), "census: the line comes once per change");
        census.Note(MakeItem(5, G::Kind::Short, true));
        std::string off;
        Expect(census.TakeLine(G::Mode::Off, 60, off) && Has(off, "box judge OFF up to 60 bones"), "census: the knob state is in the line");
        census.Note(MakeItem(6, G::Kind::Gpu, true));
        std::string unread_line;
        Expect(census.TakeLine(G::Mode::Unread, 96, unread_line) && Has(unread_line, "box judge unread up to 96 bones"), "census: the unread mode is in the line");
        G::Census full;
        for (std::uint64_t i = 1; i <= G::CensusMost + 3; ++i) {
            full.Note(MakeItem(i, G::Kind::Gpu, false));
        }
        std::string full_line;
        Expect(full.Size() == G::CensusMost && full.TakeLine(G::Mode::All, 96, full_line) && Has(full_line, "(census full)") &&
                   full_line.size() <= G::LineChars,
               "census: at most CensusMost streams, the line says it is full and stays capped");
    }

    // the writer watch
    {
        G::Watch watch;
        watch.Written(0xabcdull, 5, 0x7f0000001000ull, 0x2000); // nothing watched: nothing noted
        Expect(watch.Hits() == 0 && watch.Watched() == 0 && watch.TakeLines().empty(), "watch: nothing watched, nothing noted");
        Expect(!watch.Add(0, 4032, 84, 1) && !watch.Add(0x7f0000001000ull, 0, 84, 1), "watch: no address or no bytes is not watched");
        Expect(watch.Add(0x7f0000001100ull, 4032, 84, 0x55) && !watch.Add(0x7f0000001100ull, 4032, 84, 0x55) && watch.Watched() == 1,
               "watch: one palette once");
        watch.Written(0x1111ull, 5, 0x7f0000009000ull, 0x1000); // elsewhere
        Expect(watch.Hits() == 0, "watch: a write elsewhere is no hit");
        watch.Written(0x1111ull, 5, 0x7f0000001000ull, 0x4000); // holds the palette
        watch.Written(0x1111ull, 5, 0x7f0000001000ull, 0x4000); // the same writer again: once
        watch.Written(0x2222ull, 3, 0x7f0000002000ull, 0x10);   // only shares the page of the palette's end
        std::vector<std::string> lines = watch.TakeLines();
        Expect(watch.Hits() == 2 && lines.size() == 2 && Has(lines[0], "palette writer 1: a compute shader 0000000000001111") &&
                   Has(lines[0], "lies INSIDE that binding") && Has(lines[1], "palette writer 2: a vertex shader 0000000000002222") &&
                   Has(lines[1], "only SHARES a page") && Has(lines[0], "(84 bones, stream 0x55)") &&
                   lines[0].size() <= G::LineChars + 64,
               "watch: a writer is named once with its shader, its stage and how it meets the palette");
        Expect(watch.TakeLines().empty(), "watch: each hit is taken once");
        for (std::uint64_t i = 0; i < 20; ++i) {
            watch.Written(0x9000ull + i, 5, 0x7f0000001000ull, 0x4000);
        }
        Expect(watch.Hits() == G::HitsMost, "watch: at most HitsMost writers");
        G::Watch many;
        std::size_t added = 0;
        for (std::uint64_t i = 0; i < G::WatchMost + 4; ++i) {
            added += many.Add(0x7f0000100000ull + i * 0x10000, 640, 13, i + 1) ? 1u : 0u;
        }
        Expect(added == G::WatchMost && many.Watched() == G::WatchMost, "watch: at most WatchMost palettes");
    }

    // the book's reasons and the box route
    {
        BbWindHang::Book book;
        book.Note(7, 4096, 0, false, 1, 0xe859b6d9ull, 5, 0); // the palette's content differed
        book.Note(8, 4096, 0, false, 1, 0xe859b6d9ull);        // unread (defaults: why 1)
        book.Note(9, 4096, 0, true, 1, 0xe859b6d9ull, 1, 2);   // sent to the box judge: not moving, box route 2
        book.Note(10, 4096, 0, true, 1, 0xe859b6d9ull, 1, 1);
        book.Note(7, 4096, 0, false, 2, 0xe859b6d9ull, 1, 0);  // the first reason stays
        const BbWindHang::Entry* const content = book.Find(7);
        const BbWindHang::Entry* const unread = book.Find(8);
        const BbWindHang::Entry* const boxed = book.Find(9);
        const BbWindHang::Entry* const boxed_unread = book.Find(10);
        Expect(content != nullptr && unread != nullptr && boxed != nullptr && boxed_unread != nullptr && content->moving &&
                   content->why_moving == 5 && unread->moving && unread->why_moving == 1 && !boxed->moving &&
                   boxed->why_moving == 0 && boxed->box_only == 2 && boxed_unread->box_only == 1 && content->box_only == 0 &&
                   unread->box_only == 0,
               "book: why 5 for a changed content, why 1 for unread, the box route kept, the first reason stays");
        book.Note(9, 4096, 0, true, 2, 0xe859b6d9ull); // a later draw with the defaults: no box route
        Expect(book.Find(9)->box_only == 0, "book: the box route is the last draw's (a draw without it clears it)");
    }

    // the texts
    Expect(Has(F::MovingWhy(5, 0), "differs from the first draw's") && Has(F::MovingWhy(5, 0), "never measured") &&
               Has(F::MovingWhy(1, 0), "could not be read"),
           "texts: the reasons 1 and 5");
    {
        F::CandInfo pushed;
        pushed.e.height = 1.84f;
        pushed.hang = true;
        pushed.judged = true;
        pushed.fits = true;
        pushed.span = 1.84f;
        const std::string plain_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        pushed.box_only = 2;
        const std::string moved_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        pushed.box_only = 1;
        const std::string unread_text = F::CandState(pushed, 2.5f, 0.2f, true, 0.35f);
        Expect(Has(plain_text, "PUSHED:") && !Has(plain_text, "GPU box") && Has(moved_text, "PUSHED:") &&
                   Has(moved_text, "[judged by the GPU box: palette content moved]") &&
                   Has(unread_text, "[judged by the GPU box: palette unread]") && moved_text.size() < 320,
               "texts: a box-judged candidate's state says so");
    }
    {
        const std::string once = G::OnceText(G::Mode::All, 96, 0.2f, 0.08f);
        const std::string unread_once = G::OnceText(G::Mode::Unread, 96, 0.2f, 0.08f);
        const std::string off = G::OnceText(G::Mode::Off, 96, 0.2f, 0.08f);
        Expect(Has(once, "Wind sway hang (r112p): on (BB_WIND_HANG_BOXJUDGE unset or 1") && Has(once, "or its content differs") &&
                   Has(once, "at most 96 bones") && Has(once, "gain 0.20") && Has(once, "at most 0.080 m") &&
                   Has(unread_once, "on, unread palettes only") && !Has(unread_once, "or its content differs") &&
                   Has(off, "OFF (BB_WIND_HANG_BOXJUDGE=0: as r112o)"),
               "texts: the once-line");
        G::Stats stats;
        stats.box_draws = 120;
        stats.turned_away = 7;
        stats.words = 90;
        stats.ramping = 12;
        G::Census census;
        census.Note(MakeItem(1, G::Kind::Gpu, true));
        census.Note(MakeItem(2, G::Kind::Moved, true));
        census.Note(MakeItem(3, G::Kind::Moved, false));
        const std::string line = G::StatsText(stats, census, 2, 1, 0.2f);
        Expect(Has(line, "refused streams 3, 2 judged by the GPU box (gpu 1, moved 1)") && Has(line, "120 draws of them went to the judge") &&
                   Has(line, "7 were turned away") && Has(line, "90 got a push (12 still in the rise)") &&
                   Has(line, "palette pages watched 2, writers found 1") && line.size() < 420,
               "texts: the periodic line");
    }

    // bbport (r112r_hang-bracket-judge): a stream with no skeleton-size palette goes to the box judge when asked
    {
        Expect(G::ParseNopal(nullptr) && G::ParseNopal("") && G::ParseNopal("1") && G::ParseNopal("00") && !G::ParseNopal("0"),
               "nopal: on unless exactly 0");
        const S::Entry bare = MakeEntry(0, S::Why::NoPalette);
        const S::Entry character = MakeEntry(120, S::Why::Character);
        const S::Entry gpu_palette = MakeEntry(84, S::Why::GpuWritten);
        Expect(!G::BoxJudgeable(&bare, S::Result::Never, 96) && !G::BoxJudgeable(&bare, S::Result::Never, 96, true, false),
               "nopal: turned away as before without the flag");
        Expect(G::BoxJudgeable(&bare, S::Result::Never, 96, true, true) && G::BoxJudgeable(&bare, S::Result::Never, 96, false, true),
               "nopal: judged by the box with the flag (also with moved_ok false: it was never read)");
        Expect(!G::BoxJudgeable(nullptr, S::Result::Never, 96, true, true) && !G::BoxJudgeable(&bare, S::Result::Same, 96, true, true) &&
                   !G::BoxJudgeable(&bare, S::Result::Moved, 96, true, true),
               "nopal: no entry, a still palette and a moved one are no nopal case");
        Expect(!G::BoxJudgeable(&character, S::Result::Never, 341, true, true) && G::BoxJudgeable(&gpu_palette, S::Result::Never, 96, true, true),
               "nopal: a character stays refused, the unread palettes are judged as before");
        G::Census census;
        for (std::uint64_t i = 1; i <= G::NopalMost; ++i) {
            Expect(census.NopalRoom(i), "nopal: room while fewer than the most are judged");
            census.Note(MakeItem(i, G::Kind::NoPal, true));
        }
        Expect(!census.NopalRoom(9999) && census.NopalRoom(3), "nopal: full: a new stream has no room, a judged one keeps it");
        census.Note(MakeItem(500, G::Kind::NoPal, false));
        Expect(!census.NopalRoom(500), "nopal: a turned-away stream does not count as judged and has no room when full");
        census.Note(MakeItem(1, G::Kind::NoPal, false)); // stream 1 changes to turned away: its place is free again
        Expect(census.NopalRoom(9999), "nopal: a place frees when a judged stream is turned away");
        census.Note(MakeItem(1, G::Kind::NoPal, true));
        Expect(!census.NopalRoom(9999), "nopal: and is taken again");
        G::Census crowded;
        for (std::uint64_t i = 1; i <= G::CensusMost; ++i) {
            crowded.Note(MakeItem(i, G::Kind::Gpu, false));
        }
        Expect(!crowded.NopalRoom(G::CensusMost + 1) && crowded.NopalRoom(1), "nopal: no room for a stream the full census cannot note");
        std::string line;
        Expect(census.TakeLine(G::Mode::All, 96, line) && Has(line, "no palette 48+1") && Has(line, "character 0+0") && Has(line, "other 0+0") &&
                   Has(line, "content moved 0+0"),
               "nopal: the census line counts the three new kinds");
        G::Census mixed;
        mixed.Note(MakeItem(7, G::Kind::Character, false));
        mixed.Note(MakeItem(8, G::Kind::Other, false));
        std::string mixed_line;
        Expect(mixed.TakeLine(G::Mode::All, 96, mixed_line) && Has(mixed_line, "character 0+1") && Has(mixed_line, "other 0+1") &&
                   Has(mixed_line, "no palette 0+0"),
               "nopal: character and other are counted turned away");
    }
    if (failures != 0) {
        std::printf("%d failures\n", failures);
        return 1;
    }
    std::printf("wind-hang-gpu-test: all passed\n");
    return 0;
}
