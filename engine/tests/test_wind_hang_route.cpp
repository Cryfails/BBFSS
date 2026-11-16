// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112q_hang-bracket-route): the route lines, BB_WIND_HANG_FORCE, BB_WIND_HANG_BOX_RETRY, the proof's binary version add and
// the GPU judge's DueSoft (gpu/shim/bbport_wind_hang_route.h, _gpu.h, _still.h, bbport_wind_hang.h). The twin in Python
// (r112q_twin.py) holds the same cases.
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_gpu.h"
#include "gpu/shim/bbport_wind_hang_route.h"
#include "gpu/shim/bbport_wind_hang_still.h"

namespace R = BbWindHangRoute;
namespace G = BbWindHangGpu;
namespace S = BbWindHangStill;
namespace H = BbWindHang;
namespace A = BbWindHangActors;

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

bool AnyHas(const std::vector<std::string>& lines, const char* needle) {
    for (const std::string& line : lines) {
        if (Has(line, needle)) {
            return true;
        }
    }
    return false;
}
} // namespace

int main() {
    // BB_WIND_HANG_FORCE
    {
        const R::Force none = R::ParseForce(nullptr);
        Expect(!none.all && none.n == 0 && !R::ForceMatchesWith(none, 0xe859b6d9u), "force: unset forces nothing");
        Expect(R::ParseForce("").n == 0 && !R::ParseForce("").all, "force: empty forces nothing");
        Expect(R::ParseForce("all").all && R::ForceMatchesWith(R::ParseForce("all"), 0x12345678u), "force: all");
        Expect(!R::ParseForce("ALL").all, "force: only the exact word all");
        const R::Force one = R::ParseForce("e859b6d9");
        Expect(!one.all && one.n == 1 && one.vs[0] == 0xe859b6d9u && R::ForceMatchesWith(one, 0xe859b6d9u) &&
                   !R::ForceMatchesWith(one, 0x97f2d384u),
               "force: one hash");
        const R::Force many = R::ParseForce("e859b6d9:97f2d384:6a833138:9da6aacb:c829ee58");
        Expect(many.n == R::ForceMost && many.vs[3] == 0x9da6aacbu && !R::ForceMatchesWith(many, 0xc829ee58u),
               "force: at most four hashes");
        Expect(R::ParseForce("zz").n == 0, "force: text that is no hex forces nothing");
        Expect(R::ParseForce("e859b6d9:zz").n == 1, "force: a bad second hash is left out");
    }
    // BB_WIND_HANG_BOX_RETRY
    {
        Expect(G::ParseRetry(nullptr) == 120 && G::ParseRetry("") == 120 && G::ParseRetry("abc") == 120, "retry: default 120");
        Expect(G::ParseRetry("0") == 0, "retry: 0 gives r112p's rule");
        Expect(G::ParseRetry("5") == 30 && G::ParseRetry("99999") == 3600 && G::ParseRetry("200") == 200, "retry: 30 to 3600");
    }
    // the proof's binary version add
    {
        static_assert(H::ProofBinaryAdd == 200000u, "the add is a number no sway version reaches (r112r: 200000, r112q: 100000)");
        static_assert(H::ProofBinaryAdd > 22u + 1000u + 2000u + 100u + 10u + 20u + 400u + 40u + 4000u + 8000u + 400u, "no clash");
    }
    // where a draw leaves the chain
    {
        const std::uint32_t keys_word = H::HangWord(0, 0, 5, 0);
        const std::uint32_t push_word = H::HangWord(0, 0, 5, 200);
        const std::uint32_t plant_word = BbWindSway::PackWord(0, 0, 5, 100);
        R::Mark before;
        std::uint8_t why = 9;
        Expect(R::Classify(before, before, 0, why) == R::Exit::NoWord, "exit: WindSwayWord not called");
        R::Mark after = before;
        after.called = 1;
        Expect(R::Classify(before, after, 0, why) == R::Exit::Other && why == 0, "exit: called, nothing moved");
        R::Mark m = after;
        m.no_sun = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::NoSun, "exit: no sun pass");
        m = after;
        m.settled = 1;
        m.moving = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Settled, "exit: settled comes before moving in the chain");
        m = after;
        m.moving = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Moving, "exit: moving");
        m = after;
        m.why[static_cast<std::size_t>(A::Why::Near)] = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Refused && why == static_cast<std::uint8_t>(A::Why::Near),
               "exit: refused by r112h's near rule");
        m = after;
        m.why[0] = 1;
        Expect(R::Classify(before, m, 0, why) == R::Exit::Other, "exit: a kept stream (Why::Ok) is no refusal");
        Expect(R::Classify(before, after, keys_word, why) == R::Exit::Keys, "exit: a hang word with ramp 0 is keys only");
        Expect(R::Classify(before, after, push_word, why) == R::Exit::Pushed, "exit: a hang word with a ramp is pushed");
        Expect(R::Classify(before, after, plant_word, why) == R::Exit::OtherWord, "exit: a plant word has no hang bit");
        m = after;
        m.forced = 1;
        Expect(R::Classify(before, m, push_word, why) == R::Exit::Forced, "exit: a forced word");
    }
    // the groups and their lines
    {
        const std::uint32_t push_word = H::HangWord(0, 0, 5, 200);
        R::Book book;
        R::Mark before;
        R::Mark after = before;
        after.called = 1;
        for (int i = 0; i < 6; ++i) { // 6 pushed, delivered draws of the bracket shader
            book.Note(0xe859b6d9u, 0xe21e283au, 'S', true, false, 0x1000, push_word, true, before, after);
        }
        R::Mark sun = after;
        sun.no_sun = 1;
        for (int i = 0; i < 4; ++i) { // 4 draws of another shader that no sun pass draws
            book.Note(0x63220f67u, 0xdbb222ebu, 'S', true, false, 0x2000 + i, 0, true, before, sun);
        }
        for (int i = 0; i < 3; ++i) { // a pipeline with no bit
            book.Note(0x11111111u, 0x22222222u, 'O', false, false, 0x3000, 0, true, before, before);
        }
        Expect(book.Size() == 3 && book.Find(0xe859b6d9u, 0xe21e283au)->draws == 6, "book: one group a pair of shaders");
        const R::Lookup look = [](std::uint64_t) {
            R::StreamInfo s;
            s.scene = true;
            s.height = 1.32f;
            s.width = 0.88f;
            s.verts = 1907;
            s.box = true;
            s.box_state = 2;
            s.dev = 0.31f;
            s.book = true;
            s.moving = true;
            s.why_moving = 3;
            s.box_only = 1;
            return s;
        };
        const R::PathOf path = [](std::uint64_t) { return "lifted"; };
        const std::vector<std::string> lines = R::Lines(book, 0, look, path, 600);
        Expect(AnyHas(lines, "3 stream groups") && AnyHas(lines, "vs:ps e859b6d9:e21e283a [bracket]"), "lines: the header and the bracket group");
        Expect(!AnyHas(lines, "NO draw of it reached"), "lines: no 'no draw' line while the bracket shader was drawn");
        Expect(AnyHas(lines, "none up to the shader: 6 pushed words were delivered"), "lines: FIRST BREAK of a pushed, delivered group");
        Expect(AnyHas(lines, "vs:ps 63220f67:dbb222eb") && AnyHas(lines, "no sun shadow pass draws this stream"),
               "lines: a skinned group with the bit and no sun pass");
        Expect(!AnyHas(lines, "vs:ps 11111111:22222222"), "lines: a group no hang code can touch is not told");
        Expect(AnyHas(lines, "scene 1.32 m tall 0.88 m wide 1907 verts, judge moved dev 310 mm, book moving (why 3, box 1)"),
               "lines: a stream's scene box, judge state and book");
        R::Book other;
        other.Note(0x63220f67u, 0xdbb222ebu, 'S', true, false, 0x2000, 0, true, before, sun);
        const std::vector<std::string> none = R::Lines(other, 0, look, path, 600);
        Expect(AnyHas(none, "vs e859b6d9") && AnyHas(none, "NO draw of it reached the Motion block"),
               "lines: the bracket shader always has a line");
        // FIRST BREAK of a pipeline with no bit, of lost words
        R::Group g;
        g.draws = 5;
        g.exits[static_cast<std::size_t>(R::Exit::NoWord)] = 5;
        Expect(Has(R::FirstBreak(g, "lifted"), "no Sway bit"), "break: no bit");
        g.bit = 5;
        g.kinds[2] = 5;
        Expect(Has(R::FirstBreak(g, "lifted"), "no skinned draw"), "break: a static group");
        R::Group lost;
        lost.draws = 3;
        lost.exits[static_cast<std::size_t>(R::Exit::Pushed)] = 3;
        lost.lost = 3;
        Expect(Has(R::FirstBreak(lost, "lifted"), "the word is lost"), "break: pushed words with no motion parameter");
        R::Group keys;
        keys.draws = 3;
        keys.bit = 3;
        keys.kinds[0] = 3;
        keys.exits[static_cast<std::size_t>(R::Exit::Keys)] = 3;
        Expect(Has(R::FirstBreak(keys, "lifted"), "ramp stays 0"), "break: keys only");
        Expect(Has(R::OnceText(120, true, true), "BB_WIND_HANG_BOX_RETRY") && Has(R::OnceText(120, false, false), "FORCE (TOOL): off"),
               "once line");
        R::Book full;
        for (std::uint64_t i = 0; i < R::GroupsMost + 5; ++i) {
            full.Note(0x1000u + i, 0x2000u, 'S', true, false, 1, 0, true, before, after);
        }
        Expect(full.Size() == R::GroupsMost && full.dropped == 5, "book: at most GroupsMost groups");
        for (const std::string& line : lines) {
            Expect(line.size() <= R::LineChars + 4, "lines: under LineChars");
        }
    }
    // the judge's DueSoft: a box that grew 0.25 m is due again after `retry` frames, a small mover as Due says
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, BbWindSway::ResetKey);
        namespace W = BbWindSway;
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1, float z0, float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) { words[at] = std::min(words[at], key); };
            const std::uint32_t box = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(box + 0, W::HeightKey(x0));
            low(box + 1, W::CrownKey(x1));
            low(box + 2, W::HeightKey(z0));
            low(box + 3, W::CrownKey(z1));
        };
        S::BoxBook mover;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(9, 0.0f, f < 120 ? 2.0f : 2.5f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            mover.Step(12, 4096, 9, f == 100, f, words.data());
        }
        Expect(mover.Final(12) && !mover.Due(12, 100000), "soft: r112p's rule: final, never due");
        const std::uint64_t at = mover.Find(12)->settled;
        Expect(!mover.DueSoft(12, at + 119, 120), "soft: not due before retry frames");
        Expect(mover.DueSoft(12, at + 120, 120) && mover.Find(12) == nullptr, "soft: due after retry frames, forgotten");
        Expect(!mover.DueSoft(99, 1000000, 120), "soft: an unknown stream is not due (the caller asks only for held ones)");
        S::BoxBook small;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(10, 0.0f, f < 120 ? 2.0f : 2.05f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            small.Step(13, 4096, 10, f == 100, f, words.data());
        }
        const std::uint64_t small_at = small.Find(13)->settled;
        Expect(!small.Final(13) && !small.DueSoft(13, small_at + S::RejudgeFrames - 1, 30) && small.DueSoft(13, small_at + S::RejudgeFrames, 30),
               "soft: a small mover is due as Due says, not sooner");
        S::BoxBook rejected;
        rejected.Step(14, 4096, 11, true, 100, words.data());
        Expect(rejected.Reject(14, 100, 7200) && !rejected.DueSoft(14, 100 + 7199, 30) && rejected.DueSoft(14, 100 + 7200, 30),
               "soft: r112h's hold stands");
    }
    // the writer watch hears the other paths
    {
        G::Watch watch;
        Expect(watch.Add(0x7f0000001100ull, 4032, 84, 0x55), "writers: a palette is watched");
        watch.Written(0, G::WriterCopy, 0x7f0000001000ull, 0x4000);
        watch.Written(0, G::WriterFill, 0x7f0000009000ull, 0x1000); // elsewhere
        watch.Written(0, G::WriterGuest, 0x7f0000002000ull, 0x10);   // shares the page of the palette's end
        const std::vector<std::string> lines = watch.TakeLines();
        Expect(watch.Hits() == 2 && lines.size() == 2 && Has(lines[0], "a DMA copy destination (no shader) writes") &&
                   Has(lines[0], "lies INSIDE that range") && Has(lines[1], "a guest-memory write (no shader)") &&
                   Has(lines[1], "only SHARES a page"),
               "writers: a copy and a guest write are named, no shader hash");
        Expect(Has(G::NoWriterText(8), "8 watched palette pages") && Has(G::NoWriterText(8), "r112q"), "writers: the explanation line");
    }
    // bbport (r112r_hang-bracket-judge): the pairs that got a hang word, the proof's lines
    {
        R::TintBook book;
        const std::uint32_t pushed_word = H::HangWord(0, 0, 5, 200);
        const std::uint32_t keys_word = H::HangWord(0, 0, 5, 0);
        book.Note(0xe859b6d9u, 0x1u, 'S', pushed_word, true, false, 100);
        book.Note(0xe859b6d9u, 0x1u, 'S', keys_word, true, false, 110);
        book.Note(0xe859b6d9u, 0x1u, 'S', pushed_word, false, false, 120); // the word was lost
        book.Note(0xe859b6d9u, 0x1u, 'S', 0, true, false, 130);            // no word
        book.Note(0x6a833138u, 0x2u, 'O', pushed_word, true, true, 140);
        book.Note(0x77u, 0x3u, 'P', 0, false, false, 150);
        const R::Seen* const lantern = book.Find(0xe859b6d9u, 0x1u);
        Expect(lantern != nullptr && lantern->draws == 4 && lantern->words == 2 && lantern->kinds[0] == 2 && lantern->pushed == 1 &&
                   lantern->hidden == 0 && lantern->first == 100 && lantern->last == 110,
               "tint: a delivered hang word counts, a ramp 0 counts as a word, a lost word and no word do not");
        const R::Seen* const hidden = book.Find(0x6a833138u, 0x2u);
        Expect(hidden != nullptr && hidden->words == 1 && hidden->kinds[2] == 1 && hidden->hidden == 1, "tint: a static draw, hidden");
        Expect(book.Find(0x77u, 0x3u) != nullptr && book.Find(0x77u, 0x3u)->words == 0 && book.Find(0x1234u, 0x1u) == nullptr && book.Pairs() == 3,
               "tint: a pair with no word is kept, an unknown pair is not there");
        Expect(book.Find(0xaaaa0000e859b6d9ull, 0xbbbb000000000001ull) != nullptr, "tint: pairs are keyed by the low 32 bits of the hashes");
        const std::vector<std::string> lines = book.Lines(R::TintLinesMost);
        Expect(lines.size() == 3 && Has(lines[0], "2 pairs and 3 draws with a hang word") && Has(lines[0], "most draws first") &&
                   Has(lines[1], "tinted vs:ps e859b6d9:00000001: 2 draws (skinned 2, GPU palette 0, static 0), ramp above 0 in 1, hidden 0, frames 100 to 110, of 4 Motion block draws") &&
                   Has(lines[2], "vs:ps 6a833138:00000002: 1 draws (skinned 0, GPU palette 0, static 1), ramp above 0 in 1, hidden 1"),
               "tint: the report's lines, most words first");
        Expect(book.Lines(1).size() == 2, "tint: at most `most` pair lines");
        const R::TintBook empty{};
        const std::vector<std::string> none = empty.Lines(R::TintLinesMost);
        Expect(none.size() == 1 && Has(none[0], "NO draw got a hang word, nothing is tinted"), "tint: an empty book says so");
        const std::string with = book.PickText(1117, 677, 0xe859b6d9u, 0x1u, true);
        Expect(Has(with, "pick pixel 1117,677 vs:ps e859b6d9:00000001: 4 Motion block draws of this pair, 2 with a hang word delivered") &&
                   Has(with, "the proof tints these draws") && !Has(with, "NONE"),
               "tint: the pick's line for a pair with words");
        Expect(Has(book.PickText(1, 2, 0xe859b6d9u, 0x1u, false), "BB_WIND_HANG_PROOF is off: nothing is tinted"), "tint: the pick's line with the proof off");
        Expect(Has(book.PickText(1, 2, 0x77u, 0x3u, true), "NONE with a hang word delivered") &&
                   Has(book.PickText(1, 2, 0x99u, 0x9u, true), "no Motion block draw of this pair of shaders was seen"),
               "tint: the pick's lines for a pair with no word and for an unknown pair");
        Expect(R::ParseHide("1") && !R::ParseHide(nullptr) && !R::ParseHide("") && !R::ParseHide("0") && !R::ParseHide("11"), "hide: exactly 1");
        const std::string once = R::ProofOnceText(H::ProofShare, H::ProofBinaryAdd);
        Expect(Has(once, "lifted AND recompiled") && Has(once, "50 percent") && Has(once, "(+200000)") && Has(once, "BB_WIND_HANG_PROOF_HIDE=1"),
               "tint: the once line");
        R::TintBook full;
        for (std::uint64_t i = 0; i < R::SeenMost + 5; ++i) {
            full.Note(i + 1, 1, 'S', 0, false, false, 1);
        }
        Expect(full.Pairs() == R::SeenMost && full.dropped == 5 && Has(full.Lines(1)[0], "pairs dropped"), "tint: the table is bounded");
    }
    if (failures == 0) {
        std::printf("wind-hang-route-test: all passed\n");
    }
    return failures == 0 ? 0 : 1;
}
