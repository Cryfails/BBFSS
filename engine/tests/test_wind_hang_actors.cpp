// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112h_hang-not-the-hunter): who may hang (gpu/shim/bbport_wind_hang_actors.h): the knobs,
// the rule (the hunter's gear, figures, indoors, unplaced), the refusal's hold and the keyless hold
// in the GPU judge's book (gpu/shim/bbport_wind_hang_still.h), the book's lines.
// The twin in Python (r112h_twin.py) holds the same cases.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_actors.h"

namespace A = BbWindHangActors;
namespace S = BbWindHangStill;
namespace W = BbWindSway;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

S::BoxEntry Box(float x0, float x1, float z0, float z1, float y0, float y1, bool placed) {
    S::BoxEntry e;
    e.snap.x_lo = x0;
    e.snap.x_hi = x1;
    e.snap.z_lo = z0;
    e.snap.z_hi = z1;
    e.snap.base = y0;
    e.snap.crown = y1;
    e.snap.y_ok = true;
    e.snap.box_ok = placed;
    e.started = 7;
    return e;
}
} // namespace

int main() {
    // the knobs: defaults, an off, out of range values, text that is no number
    const A::Knobs d = A::ParseKnobs(nullptr, nullptr, nullptr, nullptr);
    Expect(d.on && d.bones == 24 && d.near_m == 1.5f && d.indoor == 0.1f, "knobs: defaults");
    const A::Knobs off = A::ParseKnobs("0", nullptr, nullptr, nullptr);
    Expect(!off.on, "knobs: BB_WIND_HANG_ACTORS=0 is off");
    const A::Knobs wide = A::ParseKnobs("1", "500", "9", "2");
    Expect(wide.on && wide.bones == S::CharacterBones && wide.near_m == A::NearMax &&
               wide.indoor == 1.0f,
           "knobs: held to their ranges");
    const A::Knobs low = A::ParseKnobs("1", "0", "-3", "-1");
    Expect(low.bones == A::BonesMin && low.near_m == 0.0f && low.indoor == 0.0f,
           "knobs: held at the low end");
    const A::Knobs junk = A::ParseKnobs("1", "abc", "x", "nan");
    Expect(junk.bones == 24 && junk.near_m == 1.5f && junk.indoor == 0.1f,
           "knobs: text that is no number gives the defaults");

    // the rule
    A::Hunter hunter;
    hunter.known = true;
    hunter.x = 10.0f;
    hunter.y = -40.0f;
    hunter.z = 20.0f;
    float side = 0.0f;
    // the gear: a 0.6 m box on the hunter, 28 bones: too many bones
    const S::BoxEntry gear = Box(9.6f, 10.3f, 19.7f, 20.2f, -40.3f, -39.7f, true);
    Expect(A::Judge(d, &gear, 28, hunter, 1.0f, true, &side) == A::Why::Bones, "rule: 28 bones");
    Expect(side < 0.0f, "rule: no distance worked out for a refusal by bones");
    // the same box with 12 bones: on the hunter
    Expect(A::Judge(d, &gear, 12, hunter, 1.0f, true, &side) == A::Why::Near && side == 0.0f,
           "rule: on the hunter");
    // 1.4 m sideways is still near, 1.6 m is not; 6 m above his band is not
    const S::BoxEntry close = Box(11.4f, 11.6f, 19.9f, 20.1f, -40.2f, -39.4f, true);
    Expect(A::Judge(d, &close, 12, hunter, 1.0f, true, &side) == A::Why::Near &&
               std::fabs(side - 1.4f) < 1e-4f,
           "rule: 1.4 m sideways is near");
    const S::BoxEntry apart = Box(11.6f, 11.8f, 19.9f, 20.1f, -40.2f, -39.4f, true);
    Expect(A::Judge(d, &apart, 12, hunter, 1.0f, true, &side) == A::Why::Ok &&
               std::fabs(side - 1.6f) < 1e-4f,
           "rule: 1.6 m sideways is kept");
    const S::BoxEntry high = Box(10.0f, 10.4f, 20.0f, 20.4f, -34.0f, -33.0f, true);
    Expect(A::Judge(d, &high, 12, hunter, 1.0f, true, &side) == A::Why::Ok,
           "rule: 6 m over him is not on him");
    const S::BoxEntry ground = Box(10.0f, 10.4f, 20.0f, 20.4f, -43.0f, -42.0f, true);
    Expect(A::Judge(d, &ground, 12, hunter, 1.0f, true, &side) == A::Why::Ok,
           "rule: 2 m under his feet is not on him");
    // far away, 6 bones: kept
    const S::BoxEntry lantern = Box(40.0f, 40.4f, 50.0f, 50.4f, -38.0f, -36.0f, true);
    Expect(A::Judge(d, &lantern, 6, hunter, 1.0f, true, &side) == A::Why::Ok && side > 30.0f,
           "rule: a lantern far away is kept");
    // not placed, the hunter unread, no palette
    const S::BoxEntry unplaced = Box(0, 0, 0, 0, -38.0f, -36.0f, false);
    Expect(A::Judge(d, &unplaced, 6, hunter, 1.0f, true, &side) == A::Why::Unplaced,
           "rule: no box keys is unplaced");
    A::Hunter blind;
    Expect(A::Judge(d, &lantern, 6, blind, 1.0f, true, &side) == A::Why::NoHunter,
           "rule: the hunter unread: nothing is taken");
    Expect(A::Judge(d, &lantern, 0, hunter, 1.0f, true, &side) == A::Why::NoPalette &&
               A::Judge(d, nullptr, 6, hunter, 1.0f, true, &side) == A::Why::NoPalette,
           "rule: no palette or no entry");
    // indoors: the open share at or under the limit, only with the field
    Expect(A::Judge(d, &lantern, 6, hunter, 0.05f, true, &side) == A::Why::Indoor &&
               A::Judge(d, &lantern, 6, hunter, 0.1f, true, &side) == A::Why::Indoor &&
               A::Judge(d, &lantern, 6, hunter, 0.5f, true, &side) == A::Why::Ok &&
               A::Judge(d, &lantern, 6, hunter, 0.0f, false, &side) == A::Why::Ok,
           "rule: indoors by the open share, not without the field");
    // the rules off by their knobs
    const A::Knobs loose = A::ParseKnobs("1", "96", "0", "0");
    Expect(A::Judge(loose, &gear, 28, hunter, 0.0f, true, &side) == A::Why::Ok,
           "rule: near 0, indoor 0 and 96 bones leave the gear in (the old behaviour)");
    // the order: bones before place before hunter before near before indoors
    Expect(A::Judge(d, &unplaced, 28, blind, 0.0f, true, &side) == A::Why::Bones &&
               A::Judge(d, &unplaced, 6, blind, 0.0f, true, &side) == A::Why::Unplaced &&
               A::Judge(d, &gear, 12, hunter, 0.0f, true, &side) == A::Why::Near,
           "rule: the order of the reasons");
    Expect(A::HoldOf(A::Why::Near) == A::FigureHoldFrames &&
               A::HoldOf(A::Why::Bones) == A::FigureHoldFrames &&
               A::HoldOf(A::Why::Indoor) == S::RejudgeFrames &&
               A::HoldOf(A::Why::Unplaced) == S::RejudgeFrames &&
               A::HoldOf(A::Why::NoHunter) == S::RejudgeFrames,
           "holds by reason");
    const float good[3] = {1.0f, 2.0f, 3.0f}, bad[3] = {1.0f, NAN, 2.0f};
    Expect(A::Finite3(good) && !A::Finite3(bad), "finite position test");

    // the GPU judge's book: a refused stream is held, a keyless one is held long
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, W::ResetKey);
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1,
                               float z0, float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) {
                words[at] = std::min(words[at], key);
            };
            const std::uint32_t at = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(at + 0, W::HeightKey(x0));
            low(at + 1, W::CrownKey(x1));
            low(at + 2, W::HeightKey(z0));
            low(at + 3, W::CrownKey(z1));
        };
        S::BoxBook book;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(7, -40.3f, -39.7f, 9.6f, 10.3f, 19.7f, 20.2f);
            }
            book.Step(10, 4096, 7, f == 100, f, words.data());
        }
        const S::BoxEntry* const still = book.Find(10);
        Expect(still != nullptr && still->state == S::BoxState::Still && still->snap.box_ok,
               "book: still with its box read");
        Expect(A::Judge(d, still, 12, hunter, 1.0f, true, &side) == A::Why::Near,
               "book: the gear's box read from the keys is on the hunter");
        Expect(book.Reject(10, 200, A::FigureHoldFrames) && book.HoldsMoved(10) &&
                   !book.Final(10) && book.Find(10)->dev < -1.5f,
               "book: rejected: moved, not final, dev -2");
        Expect(!book.Due(10, 200 + A::FigureHoldFrames - 1) &&
                   book.Due(10, 200 + A::FigureHoldFrames),
               "book: due after the figure hold");
        Expect(book.Find(10) == nullptr, "book: forgotten when due");
        Expect(!book.Reject(99, 200, 1), "book: a stream it does not know cannot be rejected");
        // a refusal for a place (indoors): due after RejudgeFrames
        S::BoxBook place;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(8, -40.3f, -39.7f, 9.6f, 10.3f, 19.7f, 20.2f);
            }
            place.Step(11, 4096, 8, f == 100, f, words.data());
        }
        Expect(place.Reject(11, 200, A::HoldOf(A::Why::Indoor)) &&
                   !place.Due(11, 200 + S::RejudgeFrames - 1) &&
                   place.Due(11, 200 + S::RejudgeFrames),
               "book: a place refusal is due after RejudgeFrames");
        // a keyless stream: nothing offered; the give-up holds it as the knob says
        S::BoxBook none;
        none.SetKeylessHold(A::KeylessHoldFrames);
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            none.Step(12, 4096, 20, f == 100, f, words.data());
        }
        const std::uint64_t gave = 100 + S::BoxGiveUpFrames;
        Expect(none.HoldsMoved(12) && none.Find(12)->keyless && none.Find(12)->dev == -1.0f,
               "book: gave up, keyless");
        Expect(none.Keyless(gave) == 1u && none.Keyless(gave + 1000000) == 0u,
               "book: keyless count, recent ones only");
        Expect(!none.Due(12, gave + S::RejudgeFrames) &&
                   !none.Due(12, gave + A::KeylessHoldFrames - 1) &&
                   none.Due(12, gave + A::KeylessHoldFrames),
               "book: a keyless stream is due only after the long hold");
        // the hold 0 (the knob off) is r112g: due after RejudgeFrames
        S::BoxBook plain;
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            plain.Step(13, 4096, 21, f == 100, f, words.data());
        }
        Expect(plain.Due(13, gave + S::RejudgeFrames), "book: hold 0 keeps r112g's 300 frames");
    }

    // the actors' book: cleared per window, counts, lines
    {
        A::Book book;
        A::Seen s;
        s.vs = 0xc77a0097u;
        s.bones = 28;
        s.height = 0.22f;
        s.top = -39.2f;
        s.side = 0.4f;
        s.why = A::Why::Bones;
        s.window = 7;
        s.frame = 1000;
        book.Note(1, s);
        Expect(!book.Cleared(1, 7), "actors: a refused stream is not cleared");
        s.why = A::Why::Ok;
        s.bones = 6;
        s.height = 0.9f;
        s.side = 12.0f;
        book.Note(1, s);
        Expect(book.Cleared(1, 7) && !book.Cleared(1, 8) && !book.Cleared(2, 7),
               "actors: cleared in its window only");
        s.vs = 0xb10c4f55u;
        s.why = A::Why::Near;
        s.height = 0.21f;
        book.Note(2, s);
        Expect(book.by_why[static_cast<std::size_t>(A::Why::Ok)] == 1u &&
                   book.by_why[static_cast<std::size_t>(A::Why::Near)] == 1u &&
                   book.by_why[static_cast<std::size_t>(A::Why::Bones)] == 1u,
               "actors: counts by reason");
        book.hunter = hunter;
        book.hunter_read = 3;
        book.no_param = 5;
        std::string first, second;
        book.Lines(1200, true, 4, first, second);
        Expect(first.size() <= A::LineChars && second.size() <= A::LineChars,
               "actors: lines under the slot report's 300");
        Expect(first.find("1 kept") != std::string::npos &&
                   first.find("4 keyless") != std::string::npos &&
                   first.find("5 sway words lost") != std::string::npos,
               "actors: totals line");
        Expect(second.find("vs 00000000") == std::string::npos &&
                   second.find("kept vs") != std::string::npos &&
                   second.find("refused vs b10c4f55") != std::string::npos &&
                   second.find("on the hunter") != std::string::npos,
               "actors: lists");
        book.Lines(1000000, false, 0, first, second);
        Expect(second.find("kept none; refused none") != std::string::npos &&
                   first.find("no field: rule off") != std::string::npos,
               "actors: nothing recent, no field");
        // the facts of a judging draw
        A::Facts f;
        f.vs = 0x6a833138u;
        f.size = 1200000;
        f.stride = 12;
        f.slot = 41;
        f.view = 0;
        f.views = 1;
        f.word = 0x80010123u;
        f.cam[0] = 9.0f;
        f.cam[1] = -38.5f;
        f.cam[2] = 17.0f;
        f.floats = true;
        f.frame = 999;
        book.Fact(77, f);
        std::string text;
        Expect(book.FactsText(77, text) && !book.FactsText(78, text) &&
                   text.size() <= A::LineChars,
               "actors: facts line");
        book.FactsText(77, text);
        Expect(text.find("100000 vertices") != std::string::npos &&
                   text.find("slot 41") != std::string::npos &&
                   text.find("6a833138") != std::string::npos,
               "actors: facts text");
    }
    if (failures == 0) {
        std::printf("wind hang actors: all passed\n");
        return 0;
    }
    std::printf("wind hang actors: %d failed\n", failures);
    return 1;
}
