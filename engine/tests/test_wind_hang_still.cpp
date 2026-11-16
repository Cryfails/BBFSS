// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112d_hang-still-test, r112e_hang-taken): the content test of the hanging things'
// palettes (gpu/shim/bbport_wind_hang_still.h): shapes relative to the pivot, the tolerance, the
// book, the groups line, the judgement afresh (Due), the forced reads.
// The twin in Python (r112d_twin.py, r112e_twin.py) holds the same cases.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_still.h"

namespace S = BbWindHangStill;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

S::Mat RotZ(double angle, double tx, double ty, double tz) {
    const double c = std::cos(angle), s = std::sin(angle);
    return {c, -s, 0.0, tx, s, c, 0.0, ty, 0.0, 0.0, 1.0, tz};
}

std::vector<S::Mat> Bones(std::mt19937& rng, std::uint32_t n) {
    std::uniform_real_distribution<double> angle(-1.0, 1.0), pos(-2.0, 2.0), up(0.0, 3.0);
    std::vector<S::Mat> out;
    for (std::uint32_t i = 0; i < n; ++i) {
        out.push_back(RotZ(angle(rng), pos(rng), up(rng), pos(rng)));
    }
    return out;
}

/// The palette's bytes: the bones as floats.
std::vector<unsigned char> Bytes(const std::vector<S::Mat>& bones) {
    std::vector<unsigned char> out(bones.size() * S::BoneBytes);
    for (std::size_t i = 0; i < bones.size(); ++i) {
        float f[12];
        for (std::size_t k = 0; k < 12; ++k) {
            f[k] = float(bones[i][k]);
        }
        std::memcpy(out.data() + i * S::BoneBytes, f, sizeof(f));
    }
    return out;
}

std::vector<S::Mat> Left(const S::Mat& camera, const std::vector<S::Mat>& bones) {
    std::vector<S::Mat> out;
    for (const S::Mat& m : bones) {
        out.push_back(S::Mul(camera, m));
    }
    return out;
}

std::vector<S::Mat> Right(const S::Mat& camera, const std::vector<S::Mat>& bones) {
    std::vector<S::Mat> out;
    for (const S::Mat& m : bones) {
        out.push_back(S::Mul(m, camera));
    }
    return out;
}

S::Result Judge(S::Book& book, std::uint64_t stream, const std::vector<S::Mat>& bones,
                std::uint64_t frame) {
    const auto bytes = Bytes(bones);
    return book.Judge(stream, std::uint32_t(bytes.size()), bytes.data(), S::Why::None, false,
                      frame);
}

} // namespace

int main() {
    std::mt19937 rng(7);
    const std::vector<S::Mat> base = Bones(rng, 28);

    // a camera on the left of every bone, moving every frame: still for 100 frames
    {
        S::Book book;
        bool all_same = true;
        for (std::uint64_t f = 0; f < 100; ++f) {
            const S::Mat cam = RotZ(0.01 * double(f), 0.3 * double(f), 1.0, -0.2 * double(f));
            all_same = all_same && Judge(book, 1, Left(cam, base), f) == S::Result::Same;
        }
        const S::Entry* e = book.Find(1);
        Expect(all_same, "camera on the left: still on 100 frames");
        Expect(e != nullptr && e->a_alive && !e->b_alive,
               "camera on the left: only shape A stays alive");
        Expect(e != nullptr && e->worst_a < 0.05, "camera on the left: A within 5% of the limit");
    }
    // a camera on the right: shape B stays alive
    {
        S::Book book;
        bool all_same = true;
        for (std::uint64_t f = 0; f < 100; ++f) {
            const S::Mat cam = RotZ(0.01 * double(f), 0.3 * double(f), 1.0, -0.2 * double(f));
            all_same = all_same && Judge(book, 1, Right(cam, base), f) == S::Result::Same;
        }
        const S::Entry* e = book.Find(1);
        Expect(all_same, "camera on the right: still on 100 frames");
        Expect(e != nullptr && e->b_alive, "camera on the right: shape B stays alive");
    }
    // float noise (the probe's skin B: 3 words of 1e-15) is still
    {
        S::Book book;
        std::uniform_real_distribution<double> noise(-1e-15, 1e-15);
        bool all_same = true;
        for (std::uint64_t f = 0; f < 60; ++f) {
            std::vector<S::Mat> bones = base;
            for (auto& m : bones) {
                for (double& v : m) {
                    v += noise(rng);
                }
            }
            all_same = all_same && Judge(book, 1, bones, f) == S::Result::Same;
        }
        Expect(all_same, "float noise of 1e-15 is still");
    }
    // the tolerance edges on bone 5 (not the pivot): a translation, a rotation element
    struct Edge {
        const char* what;
        std::size_t element;
        double delta;
        S::Result want;
    };
    const Edge edges[] = {
        {"translation 0.5e-3 is still", 3, 0.5e-3, S::Result::Same},
        {"translation 2e-3 moved", 3, 2e-3, S::Result::Moved},
        {"rotation element 0.5e-3 is still", 5, 0.5e-3, S::Result::Same},
        {"rotation element 2e-3 moved", 5, 2e-3, S::Result::Moved},
    };
    for (const Edge& edge : edges) {
        S::Book book;
        Expect(Judge(book, 1, base, 0) == S::Result::Same, "first frame is the reference");
        std::vector<S::Mat> bones = base;
        bones[5][edge.element] += edge.delta;
        Expect(Judge(book, 1, bones, 1) == edge.want, edge.what);
    }
    // a bone that turns a radian moves it for good, also when it comes back
    {
        S::Book book;
        Judge(book, 1, base, 0);
        std::vector<S::Mat> bones = base;
        bones[9] = RotZ(0.9, 0.0, 1.0, 0.0);
        Expect(Judge(book, 1, bones, 1) == S::Result::Moved, "a bone turning 1 rad moved");
        Expect(Judge(book, 1, base, 2) == S::Result::Moved, "moved stays moved");
    }
    // a slow drift (0.3 mm a frame) is caught against the first frame
    {
        S::Book book;
        bool caught = false;
        for (std::uint64_t f = 0; f < 60; ++f) {
            std::vector<S::Mat> bones = base;
            bones[3][3] += 0.3e-3 * double(f);
            caught = caught || Judge(book, 1, bones, f) == S::Result::Moved;
        }
        Expect(caught, "a drift of 0.3 mm a frame is caught within 60 frames");
    }
    // unreadable palettes: never, with their reason; the reason is kept for good
    {
        S::Book book;
        Expect(book.Judge(1, 1344, nullptr, S::Why::GpuWritten, false, 0) == S::Result::Never,
               "unreadable: never");
        Expect(book.Find(1)->never == S::Why::GpuWritten, "unreadable: the reason is kept");
        const auto bytes = Bytes(base);
        Expect(book.Judge(1, 1344, bytes.data(), S::Why::None, false, 1) == S::Result::Never,
               "unreadable once: never, also when it reads later");
        Expect(book.Judge(2, 1344, nullptr, S::Why::None, false, 0) == S::Result::Never &&
                   book.Find(2)->never == S::Why::NoPalette,
               "unreadable without a reason: nopal");
    }
    // size and bones: character-sized, 64 bones judged, another size at an address starts again
    {
        S::Book book;
        Expect(Judge(book, 1, Bones(rng, 97), 0) == S::Result::Never &&
                   book.Find(1)->never == S::Why::Character,
               "97 bones: character-sized, never");
        Expect(Judge(book, 2, Bones(rng, 96), 0) == S::Result::Same, "96 bones are judged");
        Expect(Judge(book, 1, Bones(rng, 28), 1) == S::Result::Same,
               "another size at the address: judged anew");
        Expect(book.Find(1)->bones == 28, "another size at the address: its bones");
        std::vector<S::Mat> singular(10, S::Mat{});
        Expect(Judge(book, 3, singular, 0) == S::Result::Never &&
                   book.Find(3)->never == S::Why::NoPivot,
               "no invertible bone: no pivot, never");
        std::vector<S::Mat> shifted = base;
        shifted[2][3] += 1.0;
        Judge(book, 4, base, 5);
        Expect(Judge(book, 4, shifted, 5) == S::Result::Moved,
               "a second draw of a frame that differs is compared");
        Expect(book.Judge(0, 1344, nullptr, S::Why::None, false, 0) == S::Result::Same,
               "stream 0 is left to the height book");
    }
    // a book that is full takes no more streams (never), and forgets the unseen
    {
        S::Book book;
        for (std::uint64_t s = 1; s <= S::StreamsMost; ++s) {
            Judge(book, s, base, 0);
        }
        Expect(Judge(book, 100000, base, 1) == S::Result::Never && book.Overflow() == 1,
               "full book: one more stream is never taken");
        Expect(Judge(book, 100000, base, 2 * S::SeenFrames) == S::Result::Same,
               "full book: the unseen ones are forgotten");
    }
    // the groups line: totals, then the groups with a stream that may hang, then by bones
    {
        S::Book book;
        BbWindHang::Book heights;
        const auto bytes = Bytes(base);
        const std::uint32_t size = std::uint32_t(bytes.size());
        for (std::uint64_t f = 0; f < 70; ++f) {
            // stream 10: still, 28 bones; 11: moving; 12: unreadable (84 bones); 13: 128 bones;
            // 14: still, 28 bones, read though GPU-written (forced)
            const auto r10 = book.Judge(10, size, bytes.data(), S::Why::None, true, f);
            heights.Note(10, 4096, 0, r10 == S::Result::Same, f, 1);
            std::vector<S::Mat> turning = base;
            turning[4] = RotZ(0.1 * double(f), 0.0, 1.0, 0.0);
            const auto b11 = Bytes(turning);
            const auto r11 = book.Judge(11, size, b11.data(), S::Why::None, false, f);
            heights.Note(11, 4096, 0, r11 == S::Result::Same, f, 1);
            book.Judge(12, 84 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, f);
            book.Judge(13, 128 * S::BoneBytes, bytes.data(), S::Why::None, false, f);
            const auto r14 = book.Judge(14, size, bytes.data(), S::Why::None, false, f, true);
            heights.Note(14, 4096, 0, r14 == S::Result::Same, f, 1);
        }
        std::string line;
        Expect(book.Report(heights, 70, line), "the groups line is reported");
        Expect(line.find("28b x3:") != std::string::npos, "groups: 28 bones, 3 streams");
        Expect(line.find(" hang=2") != std::string::npos, "groups: the two still ones hang");
        Expect(line.find(" moving=1(dev ") != std::string::npos, "groups: the turning one moves");
        Expect(line.find("84b x1: gpu=1") != std::string::npos, "groups: 84 bones, gpu");
        Expect(line.find("128b") == std::string::npos,
               "groups: character-sized ones are not named");
        Expect(line.find(" 1 char;") != std::string::npos, "totals: 1 char");
        Expect(line.find(" 2 hang ") != std::string::npos, "totals: 2 hang");
        Expect(line.find("in place 1,") != std::string::npos, "totals: in place count");
        Expect(line.find("forced 1,") != std::string::npos, "totals: forced count");
        Expect(line.find("; 28b x") < line.find("; 84b x"), "groups: those that may hang first");
        Expect(line.find("Wind sway hang (r112e): 5 sun-drawn skinned:") == 0, "totals: listed");
        Expect(book.Report(heights, 70, line), "the line comes every window, also unchanged");
        Expect(line.size() <= S::LineChars, "the line is short");
        // many groups: the line stays under 300 characters and counts the rest
        S::Book many;
        BbWindHang::Book none;
        for (std::uint32_t bones = 3; bones < 3 + 40; ++bones) {
            const std::uint32_t big = bones * S::BoneBytes;
            many.Judge(1000 + bones, big, nullptr, S::Why::GpuWritten, false, 5);
            many.Judge(2000 + bones, big, nullptr, S::Why::NotMapped, false, 5);
        }
        Expect(many.Report(none, 6, line) && line.size() <= S::LineChars, "many groups: short");
        Expect(line.find("+") != std::string::npos, "many groups: the rest is counted");
    }
    // judged afresh: a held pose, an unread palette that passes; not a character, not big movers
    {
        S::Book book;
        const std::uint64_t again = S::RejudgeFrames;
        // moved by a small step (2 mm on a bone): afresh after RejudgeFrames, then still
        Judge(book, 1, base, 0);
        std::vector<S::Mat> held = base;
        held[5][3] += 2e-3;
        Expect(Judge(book, 1, held, 1) == S::Result::Moved, "a small step moves it");
        Expect(book.Find(1)->settled == 1, "moved: the frame it settled");
        Expect(!book.Due(1, 1 + again - 1), "not due before RejudgeFrames");
        Expect(book.Due(1, 1 + again), "due after RejudgeFrames (a small deviation)");
        Expect(book.Rejudged() == 1 && book.Find(1)->again == 1, "judged afresh once");
        Expect(!book.Find(1)->moved && !book.Find(1)->have, "afresh: a new first frame");
        Expect(Judge(book, 1, held, 1 + again) == S::Result::Same,
               "afresh: the held pose is the reference");
        Expect(Judge(book, 1, held, 2 + again) == S::Result::Same, "afresh: and it holds");
        Expect(!book.Due(1, 2 + again), "still: not due");
        // a character's animation (a bone turning a radian) is a mover for good
        Judge(book, 2, base, 0);
        std::vector<S::Mat> turned = base;
        turned[9] = RotZ(0.9, 0.0, 1.0, 0.0);
        Expect(Judge(book, 2, turned, 1) == S::Result::Moved, "a bone turning 1 rad moved");
        Expect(!book.Due(2, 1000000), "a big mover is never judged again");
        // unread (gpu): afresh after RejudgeFrames and read then
        book.Judge(3, 1344, nullptr, S::Why::GpuWritten, false, 10);
        Expect(!book.Due(3, 10 + again - 1) && book.Due(3, 10 + again), "unread: due later");
        Expect(Judge(book, 3, base, 10 + again) == S::Result::Same, "unread: read later, judged");
        // character-sized: never afresh
        Judge(book, 4, Bones(rng, 128), 0);
        Expect(!book.Due(4, 1000000), "character-sized: never due");
        // not known: due (the caller clears the height book's entry)
        Expect(book.Due(99, 5), "a stream the book does not know is due");
        // a still stream is not due
        Judge(book, 5, base, 0);
        Expect(!book.Due(5, 1000000), "a still stream is not due");
        // the forced flag is kept through a fresh start
        const auto bytes = Bytes(base);
        book.Judge(6, std::uint32_t(bytes.size()), bytes.data(), S::Why::None, false, 0, true);
        Expect(book.Find(6)->forced, "forced is noted");
        std::vector<S::Mat> shifted = base;
        shifted[3][3] += 3e-3;
        Judge(book, 6, shifted, 1);
        Expect(book.Due(6, 1 + again) && book.Find(6)->forced, "forced is kept when judged afresh");
    }
    // r112f: the GPU judge (the sway words' keys: base, crown and the box), case for case with
    // r112f_twin.py
    {
        std::vector<std::uint32_t> words(BbWindTwigs::TwigEnd, BbWindSway::ResetKey);
        namespace W = BbWindSway;
        const auto offer = [&](std::uint32_t slot, float y0, float y1, float x0, float x1, float z0,
                               float z1) {
            const auto low = [&](std::uint32_t at, std::uint32_t key) {
                words[at] = std::min(words[at], key);
            };
            const std::uint32_t box = BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords;
            low(W::BaseAt + slot, W::HeightKey(y0));
            low(W::CrownAt + slot, W::CrownKey(y1));
            low(box + 0, W::HeightKey(x0));
            low(box + 1, W::CrownKey(x1));
            low(box + 2, W::HeightKey(z0));
            low(box + 3, W::CrownKey(z1));
        };
        // still: judging until frame 168 (window 100, first read 108, second 168), then still
        S::BoxBook box;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer(7, 0.0f, 2.0f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            const S::BoxState st = box.Step(10, 4096, 7, f == 100, f, words.data());
            if (f < 168) {
                Expect(st == S::BoxState::Judging, "box: judging before frame 168");
            } else {
                Expect(st == S::BoxState::Still, "box: still from frame 168");
            }
        }
        Expect(box.Find(10)->dev == 0.0f && !box.Final(10), "box: no deviation, not final");
        // 5 mm of jitter stays still
        S::BoxBook jitter;
        for (std::uint64_t f = 100; f < 200; ++f) {
            const float d = 0.005f * float(f % 2);
            if (f >= 101) {
                offer(8, 0.0f, 2.0f + d, 10.0f - d, 11.0f + d, 20.0f, 21.0f - d);
            }
            jitter.Step(11, 4096, 8, f == 100, f, words.data());
        }
        Expect(jitter.Find(11)->state == S::BoxState::Still && jitter.Find(11)->dev < 0.012f,
               "box: 5 mm of jitter is still");
        // a mover (0.5 m): moved for good
        S::BoxBook mover;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(9, 0.0f, f < 120 ? 2.0f : 2.5f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            mover.Step(12, 4096, 9, f == 100, f, words.data());
        }
        Expect(mover.Find(12)->state == S::BoxState::Moved && mover.Final(12) &&
                   !mover.Due(12, 100000),
               "box: a mover is final, never judged again");
        // a small mover (50 mm): moved, due after RejudgeFrames, then judged afresh with fresh keys
        S::BoxBook nudged;
        for (std::uint64_t f = 100; f < 170; ++f) {
            if (f >= 101) {
                offer(10, 0.0f, f < 120 ? 2.0f : 2.05f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            nudged.Step(13, 4096, 10, f == 100, f, words.data());
        }
        const std::uint64_t at = nudged.Find(13)->settled;
        Expect(nudged.Find(13)->state == S::BoxState::Moved && !nudged.Final(13),
               "box: small mover");
        Expect(!nudged.Due(13, at + S::RejudgeFrames - 1) && nudged.Due(13, at + S::RejudgeFrames),
               "box: due after RejudgeFrames");
        Expect(nudged.Find(13) == nullptr && nudged.Counts().again == 1, "box: forgotten, counted");
        nudged.Step(13, 4096, 10, false, at + S::RejudgeFrames, words.data());
        Expect(nudged.Find(13)->state == S::BoxState::Judging &&
                   words[W::CrownAt + 10] == W::ResetKey,
               "box: judged afresh with the keys reset");
        // watched: still, then the box grows 0.1 m: moved at the next check
        S::BoxBook watched;
        S::BoxState at197 = S::BoxState::Judging, at198 = S::BoxState::Judging;
        for (std::uint64_t f = 100; f < 230; ++f) {
            if (f >= 101) {
                offer(11, 0.0f, f < 190 ? 2.0f : 2.1f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            const S::BoxState st = watched.Step(14, 4096, 11, f == 100, f, words.data());
            at197 = f == 197 ? st : at197;
            at198 = f == 198 ? st : at198;
        }
        Expect(at197 == S::BoxState::Still && at198 == S::BoxState::Moved,
               "box: a still stream is watched every 30 frames");
        // a reset, another slot and another size start again
        S::BoxBook restart;
        for (std::uint64_t f = 100; f < 130; ++f) {
            restart.Step(15, 4096, 12, f == 100, f, words.data());
        }
        restart.Step(15, 4096, 12, true, 130, words.data());
        Expect(restart.Find(15)->started == 130 && words[W::BaseAt + 12] == W::ResetKey,
               "box: a reset starts again, keys reset");
        restart.Step(15, 4096, 13, false, 131, words.data());
        Expect(restart.Find(15)->slot == 13 && restart.Find(15)->started == 131,
               "box: another slot starts again");
        restart.Step(15, 8192, 13, false, 132, words.data());
        Expect(restart.Find(15)->started == 132, "box: another size starts again");
        // nothing offered: waits, gives up after BoxGiveUpFrames (dev -1: not final, due later)
        S::BoxBook none;
        S::BoxState before = S::BoxState::Judging, after = S::BoxState::Judging;
        for (std::uint64_t f = 100; f <= 100 + S::BoxGiveUpFrames; ++f) {
            const S::BoxState st = none.Step(16, 4096, 20, f == 100, f, words.data());
            before = f == 100 + S::BoxGiveUpFrames - 1 ? st : before;
            after = f == 100 + S::BoxGiveUpFrames ? st : after;
        }
        Expect(before == S::BoxState::Judging && after == S::BoxState::Moved, "box: gives up");
        Expect(none.Find(16)->dev == -1.0f && !none.Final(16), "box: no key: dev -1, not final");
        // refused: no stream, a slot beyond the plant slots, no words
        Expect(none.Step(0, 4096, 1, false, 1, words.data()) == S::BoxState::Moved,
               "box: stream 0");
        Expect(none.Step(5, 4096, W::PlantSlots, false, 1, words.data()) == S::BoxState::Moved,
               "box: slot out of range");
        Expect(none.Step(5, 4096, 1, false, 1, nullptr) == S::BoxState::Moved, "box: no words");
        // one read a frame: three draws of one frame read once
        S::BoxBook once;
        once.Step(1, 4096, 3, true, 0, words.data());
        const std::uint64_t reads = once.Counts().reads;
        once.Step(1, 4096, 3, false, 50, words.data());
        once.Step(1, 4096, 3, false, 50, words.data());
        once.Step(1, 4096, 3, false, 50, words.data());
        Expect(once.Counts().reads == reads + 1, "box: one read a frame");
        // which streams the keys may judge
        S::Book palettes;
        palettes.Judge(3, 28 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, 10);
        palettes.Judge(4, 277 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, 10);
        palettes.Judge(5, 28 * S::BoneBytes, nullptr, S::Why::NotMapped, false, 10);
        palettes.Judge(6, 0, nullptr, S::Why::None, false, 10);
        palettes.Judge(7, 28 * S::BoneBytes, nullptr, S::Why::None, false, 10);
        Expect(S::GpuJudgeable(palettes.Find(3), S::Result::Never),
               "judgeable: 28 bones, GPU-written");
        Expect(!S::GpuJudgeable(palettes.Find(4), S::Result::Never), "judgeable: the hunter's 277");
        Expect(S::GpuJudgeable(palettes.Find(5), S::Result::Never), "judgeable: not mapped");
        Expect(!S::GpuJudgeable(palettes.Find(6), S::Result::Never), "judgeable: no palette");
        Expect(!S::GpuJudgeable(palettes.Find(7), S::Result::Never),
               "judgeable: no palette bound (nopal)");
        Expect(!S::GpuJudgeable(nullptr, S::Result::Same), "judgeable: unknown stream");
        Expect(!S::GpuJudgeable(palettes.Find(3), S::Result::Moved),
               "judgeable: a palette that moved");
        Expect(S::GpuJudgeable(palettes.Find(3), S::Result::Same), "judgeable: a still palette");
        // r112g: the y keys alone judge when the box keys never come (the first read waits
        // BoxBoxWaitFrames frames, then the stream counts as weak); box keys that come in time are
        // used
        const auto offer_y = [&](std::uint32_t slot, float y0, float y1) {
            words[W::BaseAt + slot] = std::min(words[W::BaseAt + slot], W::HeightKey(y0));
            words[W::CrownAt + slot] = std::min(words[W::CrownAt + slot], W::CrownKey(y1));
        };
        S::BoxBook weak;
        S::BoxState w189 = S::BoxState::Moved, w190 = S::BoxState::Judging;
        for (std::uint64_t f = 100; f < 230; ++f) {
            if (f >= 101) {
                offer_y(30, 0.0f, 2.0f);
            }
            const S::BoxState st = weak.Step(40, 4096, 30, f == 100, f, words.data());
            w189 = f == 189 ? st : w189;
            w190 = f == 190 ? st : w190;
        }
        Expect(w189 == S::BoxState::Judging && w190 == S::BoxState::Still,
               "box: the y keys alone judge: first read at +30, second at +90");
        Expect(weak.Find(40)->weak && weak.Counts().weak == 1 && weak.Counts().reads_y > 0 &&
                   weak.Find(40)->snap_at == 130,
               "box: weak, counted");
        S::BoxBook late;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer_y(31, 0.0f, 2.0f);
            }
            if (f >= 115) {
                offer(31, 0.0f, 2.0f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            late.Step(41, 4096, 31, f == 100, f, words.data());
        }
        Expect(late.Find(41)->state == S::BoxState::Still && !late.Find(41)->weak &&
                   late.Find(41)->snap_at == 115 && late.Counts().weak == 0,
               "box: box keys that come before +30 are used");
        // a give-up leaves a note with the keys; the judge's verdict is held by HoldsMoved
        Expect(none.Notes().size() == 1 && none.Notes()[0].stream == 16 &&
                   none.Notes()[0].slot == 20 && none.Notes()[0].drawn > 0 &&
                   none.Notes()[0].keys[0] == W::ResetKey && none.Counts().gave_up == 1,
               "box: a give-up leaves a note with the keys");
        none.ClearNotes();
        Expect(none.Notes().empty(), "box: notes cleared");
        Expect(none.HoldsMoved(16) && mover.HoldsMoved(12) && !box.HoldsMoved(10) &&
                   !none.HoldsMoved(99),
               "box: HoldsMoved is the judge's own Moved");
        std::string causes;
        Expect(weak.Causes(causes) &&
                   causes.find("Wind sway hang (r112g): windows begun 1 (1 new, 0 slot, 0 size, "
                               "0 reset)") == 0 &&
                   causes.size() <= S::LineChars,
               "box: the causes line");
        Expect(restart.Counts().began_reset == 1 && restart.Counts().began_slot == 1 &&
                   restart.Counts().began_size == 1 && restart.Counts().began_new == 1,
               "box: windows by cause");
        // the line
        BbWindHang::Book heights;
        std::string line;
        Expect(box.Report(heights, palettes, 230, line), "box: the line is reported");
        Expect(line.find("Wind sway hang (r112f): GPU judge, tol 20 mm: 1 streams: 0 judging "
                         "1 still") == 0,
               "box line: totals");
        Expect(line.find("; 0b x1: still=1 quiet<=0mm") != std::string::npos, "box line: group");
        Expect(line.size() <= S::LineChars, "box line: short");
        Expect(mover.Report(heights, palettes, 200, line) &&
                   line.find(" moved=1 moved>=500mm") != std::string::npos,
               "box line: a moved stream and its least deviation");
        S::BoxBook many;
        for (std::uint64_t s = 1; s < 60; ++s) {
            many.Step(s, 4096, std::uint32_t(s), true, 5, words.data());
        }
        Expect(many.Report(heights, palettes, 6, line) && line.size() <= S::LineChars,
               "box line: many streams, short");
    }
    if (failures == 0) {
        std::printf("wind-hang-still-test: all passed\n");
    }
    return failures == 0 ? 0 : 1;
}
