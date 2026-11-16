// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112d_hang-still-test): the content test r112's hanging-thing selection uses in place of
// "the palette bytes hash the same". Why: the b25 test took nothing (45 of 45 skinned streams
// "moving") because the game writes bone palettes to a per-frame ring (the address changes on every
// draw), because 1e-16 float noise changes a hash, and because 22 of 30 palettes could not be read
// (the probe of r112b). Now, per position stream (its address and its bone count, never the
// palette's address):
//  - the palette is read as bones of 48 bytes (3 rows of 4 floats); shape A = inverse(P) Mi and
//    shape B = Mi inverse(P) are worked out with the pivot P = the first invertible bone of the
//    first 8 (bone 0 for a rig). A camera matrix multiplied on the left of every bone cancels in
//    A, one on the right cancels in B, so a still thing's shape does not change when the camera
//    or the ring moves. A moving rig changes both.
//  - the first frame's shapes are kept; every later draw is compared with them (also a second
//    draw of a frame: another instance of the mesh may move while the first hangs still):
//    a translation element (3, 7, 11 of a bone) may differ by TolMove (1e-3 m), any other
//    element by TolTurn (1e-3). A shape that stays inside is alive; the stream moves for good
//    when both shapes died. Comparing with the FIRST frame (not the one before) catches a slow
//    drift too.
//  - Never (taken for no reason, as moving): a palette that was not readable (GpuWritten: the
//    GPU wrote that page and it is not bound in place, so the CPU copy is stale; NotMapped;
//    Short), more than CharacterBones bones (character-sized: the hunter has 277, a still 128 bone
//    rig may be his gear, enemies and bodies 69-130; the groups of 28-84 bones are judged), no
//    invertible pivot, no palette bound.
// The rest of r112's rule (sun-shadowed stream, StillFrames frames, height 0.8-4 m, bottom pinned)
// is unchanged: BbWindHang::Book keeps the frames and the height; this file only says whether a
// frame's palette is the same one. Report names the groups (by bone count) taken and skipped.
// bbport (r112e_hang-taken): (1) a stream settled as moving or as unread (a reason that may pass)
// is judged afresh after RejudgeFrames (Due), unless it went BigDeviation tolerances (a character);
// (2) BB_WIND_HANG_READ_GPU=1 (TEST) reads palettes the buffer cache calls GPU-written too
// (ReadFlagged);
// (3) the groups line comes every window, under 300 characters, totals first (Report).
// bbport (r112f_hang-gpu-judge): (4) the GPU judges stillness (BoxBook): the mesh's world box as
// the vertex shaders keep it (r89's base and crown keys, r89d's box keys) must not grow, so a
// palette the GPU wrote and the CPU cannot read is judged too; GpuJudgeable says which may be.
// bbport (r112g_hang-judge-settles): (5) why the GPU judge never settled (b37: 14 streams judging
// for good, restarts 48): (a) a give-up (no key offered for BoxGiveUpFrames) was forgotten the
// next frame (r112e's Due fired at once for a stream whose palette was never read), so a stream
// cycled judging -> give-up -> judging; the judge's own Due decides now; (b) the six keys had to
// come all together: the y keys alone judge now (after BoxBoxWaitFrames frames without the box
// keys: `weak`); (c) a give-up leaves a note with the keys as the GPU held them, and Causes counts
// why windows began and what the reads saw, so the next log names the cause of keys that never
// come.
// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "bbport_wind_hang.h"
#include "bbport_wind_twigs.h" // bbport (r112f_hang-gpu-judge): the box keys' layout and reader

namespace BbWindHangStill {

inline constexpr std::uint32_t BoneBytes = 48;      ///< 3 rows of 4 floats
inline constexpr std::uint32_t CharacterBones = 96; ///< more bones: a character, never taken
inline constexpr std::uint32_t PivotTries = 8;      ///< bones tried as the pivot
inline constexpr double TolMove = 1e-3;             ///< m: a translation element may differ so much
inline constexpr double TolTurn = 1e-3;             ///< any other element
inline constexpr std::size_t StreamsMost = 256;     ///< streams kept (more: never taken)
inline constexpr std::uint64_t SeenFrames = BbWindHang::BookKeep; ///< listed if drawn this recently
inline constexpr std::size_t GroupsMost = 12;       ///< groups the line names at most
inline constexpr std::size_t LineMost = 200;        ///< no group is added to a line this long
inline constexpr std::size_t LineChars = 296;       ///< the line's end: the slot report keeps 300
// bbport (r112e_hang-taken): a stream settled as moving, or as unread for a reason that may pass,
// is judged afresh RejudgeFrames after (a new first frame): a pose the game held for a moment, a
// palette in flight when it was first asked, a ring that moved. One that went BigDeviation
// tolerances from its first frame (2 cm or 0.02 in a bone: a character's animation, not a held
// pose) is a mover for good, as are the streams of more than CharacterBones bones.
inline constexpr std::uint64_t RejudgeFrames = 300;
inline constexpr double BigDeviation = 20.0;

/// BB_WIND_HANG_READ_GPU=1 (a TEST setting, off by default): a palette the buffer cache says
/// the GPU wrote and that is not bound in place is read from guest memory all the same (mapped
/// and long enough), and judged by its content like any other. The CPU copy of such a palette
/// may be stale (a stale copy that never changes would pass for a still one): the groups line
/// counts those reads ("forced") so the test says whether their bytes live (moving groups with a
/// deviation) or not (every group still, deviation 0).
[[nodiscard]] inline bool ReadFlagged() {
    static const bool on = [] {
        const char* v = std::getenv("BB_WIND_HANG_READ_GPU");
        return v != nullptr && v[0] == '1' && v[1] == 0;
    }();
    return on;
}

/// A 3x4 matrix, row major (row r at r * 4), the fourth row 0 0 0 1.
using Mat = std::array<double, 12>;

[[nodiscard]] inline bool ReadBone(const unsigned char* base, std::uint32_t bone, Mat& m) {
    float f[12];
    std::memcpy(f, base + std::size_t(bone) * BoneBytes, sizeof(f));
    for (std::size_t i = 0; i < 12; ++i) {
        if (!std::isfinite(f[i])) {
            return false;
        }
        m[i] = double(f[i]);
    }
    return true;
}

/// a * b as 4x4 affine matrices.
[[nodiscard]] inline Mat Mul(const Mat& a, const Mat& b) {
    Mat r{};
    for (std::size_t i = 0; i < 3; ++i) {
        for (std::size_t j = 0; j < 4; ++j) {
            double s = j == 3 ? a[i * 4 + 3] : 0.0;
            for (std::size_t k = 0; k < 3; ++k) {
                s += a[i * 4 + k] * b[k * 4 + j];
            }
            r[i * 4 + j] = s;
        }
    }
    return r;
}

/// The inverse of an affine matrix; false when its 3x3 part is singular.
[[nodiscard]] inline bool Invert(const Mat& m, Mat& out) {
    const double a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9],
                 i = m[10];
    const double det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if (!(std::fabs(det) > 1e-9)) {
        return false;
    }
    const double k = 1.0 / det;
    out[0] = (e * i - f * h) * k;
    out[1] = (c * h - b * i) * k;
    out[2] = (b * f - c * e) * k;
    out[4] = (f * g - d * i) * k;
    out[5] = (a * i - c * g) * k;
    out[6] = (c * d - a * f) * k;
    out[8] = (d * h - e * g) * k;
    out[9] = (b * g - a * h) * k;
    out[10] = (a * e - b * d) * k;
    const double tx = m[3], ty = m[7], tz = m[11];
    out[3] = -(out[0] * tx + out[1] * ty + out[2] * tz);
    out[7] = -(out[4] * tx + out[5] * ty + out[6] * tz);
    out[11] = -(out[8] * tx + out[9] * ty + out[10] * tz);
    return true;
}

/// The bones relative to the pivot, in both orders: 12 floats a bone each.
struct Shape {
    std::vector<float> a; ///< inverse(P) Mi: a camera on the left of every bone cancels
    std::vector<float> b; ///< Mi inverse(P): a camera on the right cancels
};

/// False when a float is not finite or no pivot is invertible (out is left empty then).
[[nodiscard]] inline bool MakeShape(const unsigned char* palette, std::uint32_t bones,
                                    Shape& out) {
    out.a.clear();
    out.b.clear();
    if (palette == nullptr || bones == 0) {
        return false;
    }
    std::vector<Mat> m(bones);
    for (std::uint32_t i = 0; i < bones; ++i) {
        if (!ReadBone(palette, i, m[i])) {
            return false;
        }
    }
    Mat inverse{};
    bool pivot = false;
    for (std::uint32_t i = 0; i < std::min(bones, PivotTries) && !pivot; ++i) {
        pivot = Invert(m[i], inverse);
    }
    if (!pivot) {
        return false;
    }
    out.a.resize(std::size_t(bones) * 12);
    out.b.resize(std::size_t(bones) * 12);
    for (std::uint32_t i = 0; i < bones; ++i) {
        const Mat a = Mul(inverse, m[i]), b = Mul(m[i], inverse);
        for (std::size_t k = 0; k < 12; ++k) {
            out.a[std::size_t(i) * 12 + k] = float(a[k]);
            out.b[std::size_t(i) * 12 + k] = float(b[k]);
        }
    }
    return true;
}

/// Whether two shapes (one form of them) agree: every element within its tolerance. `worst` takes
/// the greatest difference seen, in units of the tolerance (1 = at the limit; 1e30 for a value that
/// is not finite). Empty or unequal shapes do not agree.
[[nodiscard]] inline bool Within(const std::vector<float>& x, const std::vector<float>& y,
                                 double& worst) {
    if (x.size() != y.size() || x.empty()) {
        return false;
    }
    bool same = true;
    for (std::size_t i = 0; i < x.size(); ++i) {
        const double tol = i % 4 == 3 ? TolMove : TolTurn;
        const double d = std::fabs(double(x[i]) - double(y[i]));
        const double r = std::isfinite(d) ? d / tol : 1e30;
        worst = std::max(worst, r);
        if (r > 1.0) {
            same = false;
        }
    }
    return same;
}

/// Why a palette was not taken as a still one (None: no reason, it is judged by its content).
enum class Why : std::uint8_t {
    None,
    GpuWritten, ///< the GPU wrote its page and it is not bound in place: the CPU copy is stale
    NotMapped,  ///< no GPU mapping at its address
    Short,      ///< the mapping ends before the palette does
    NoPalette,  ///< no palette of Skeleton size is bound
    NoPivot,    ///< no bone of the first PivotTries is invertible (or a float is not finite)
    Character,  ///< more than CharacterBones bones
};
inline constexpr std::size_t WhyCount = 7;

[[nodiscard]] inline const char* WhyName(Why w) {
    switch (w) {
    case Why::GpuWritten:
        return "gpu";
    case Why::NotMapped:
        return "unmapped";
    case Why::Short:
        return "short";
    case Why::NoPalette:
        return "nopal";
    case Why::NoPivot:
        return "pivot";
    case Why::Character:
        return "char";
    case Why::None:
        break;
    }
    return "none";
}

enum class Result : std::uint8_t {
    Same,  ///< this frame's palette is the first one's, within the tolerance
    Moved, ///< it is not (for good)
    Never, ///< no content test is possible or wanted (Why; for good)
};

struct Entry {
    std::uint32_t size = 0, bones = 0; ///< bytes of the palette, bones in it
    std::uint64_t frame = 0;           ///< the last frame compared
    std::uint64_t seen = 0;            ///< the last frame a draw of it was looked at
    bool have = false;                 ///< `ref` holds the first frame's shapes
    bool a_alive = true, b_alive = true;
    bool moved = false;
    bool in_place = false; ///< its palette was read from a page the GPU writes, bound in place
    bool forced = false;   ///< (BB_WIND_HANG_READ_GPU) read from a GPU-written page, not in place
    std::uint64_t settled = 0; ///< the frame it was settled as moving or unread (Due)
    std::uint32_t again = 0;   ///< times it was judged afresh (Due)
    Why never = Why::None;
    double worst_a = 0.0, worst_b = 0.0; ///< greatest difference from `ref`, in tolerances
    Shape ref;
};

/// The streams whose palettes are judged, by their position stream's address.
class Book {
public:
    /// A skinned draw of `stream` on `frame`: `palette` its bone palette's bytes (null: not
    /// readable, `why` says why), `size` their number, `in_place` it was read from a GPU-written
    /// page bound in place, `forced` (BB_WIND_HANG_READ_GPU) from one that is not. Same: this
    /// frame's palette is the first one's.
    Result Judge(std::uint64_t stream, std::uint32_t size, const unsigned char* palette, Why why,
                 bool in_place, std::uint64_t frame, bool forced = false) {
        if (stream == 0) {
            return Result::Same; // BbWindHang::Book::Note ignores it too
        }
        auto found = entries.find(stream);
        if (found == entries.end()) {
            if (entries.size() >= StreamsMost) {
                Prune(frame);
                if (entries.size() >= StreamsMost) {
                    ++overflow;
                    return Result::Never;
                }
            }
            found = entries.emplace(stream, Entry{}).first;
        }
        Entry& e = found->second;
        if (e.size != size) { // another mesh at the address: what was known goes
            e = Entry{};
            e.size = size;
            e.bones = size / BoneBytes;
        }
        e.seen = frame;
        if (e.never != Why::None) {
            return Result::Never;
        }
        if (e.moved) {
            return Result::Moved;
        }
        if (e.bones == 0) {
            e.never = Why::NoPalette;
            e.settled = frame;
            return Result::Never;
        }
        if (palette == nullptr) { // first: the log should say why a big palette was not read too
            e.never = why == Why::None ? Why::NoPalette : why;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;
        }
        if (e.bones > CharacterBones) {
            e.never = Why::Character;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;
        }
        e.in_place = e.in_place || in_place;
        e.forced = e.forced || forced;
        if (!e.have) {
            if (!MakeShape(palette, e.bones, e.ref)) {
                e.never = Why::NoPivot;
                e.settled = frame;
                return Result::Never;
            }
            e.have = true;
            e.frame = frame;
            return Result::Same;
        }
        e.frame = frame; // every draw is compared (review: a second instance may move)
        Shape now;
        if (!MakeShape(palette, e.bones, now)) {
            e.never = Why::NoPivot;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Never;
        }
        const bool a = Within(e.ref.a, now.a, e.worst_a);
        const bool b = Within(e.ref.b, now.b, e.worst_b);
        e.a_alive = e.a_alive && a;
        e.b_alive = e.b_alive && b;
        if (!e.a_alive && !e.b_alive) {
            e.moved = true;
            e.settled = frame;
            e.ref = Shape{};
            return Result::Moved;
        }
        return Result::Same;
    }

    /// Asked for a stream the height book (BbWindHang::Book) holds as settled (moving, or out of
    /// height): true when its judgement starts afresh now (the caller then clears the height
    /// book's entry too). That is so for a stream settled here as moving, or as unread for a
    /// reason that may pass (not Character), at least RejudgeFrames ago, unless it went
    /// BigDeviation tolerances from its first frame (a character's animation: for good), nor one
    /// of more than CharacterBones bones; also for a stream not known here while the book has room
    /// (the book forgot it: nothing says it moves; full, Judge would refuse it on every draw and
    /// count it as not kept each time). The stream counts as
    /// seen. False: the verdict stands (a stream settled by its height, whose content is still,
    /// is not judged again).
    bool Due(std::uint64_t stream, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return entries.size() < StreamsMost;
        }
        Entry& e = found->second;
        e.seen = frame;
        const bool unread = e.never != Why::None && e.never != Why::Character;
        if (!(e.moved || unread) || e.bones > CharacterBones ||
            e.settled + RejudgeFrames > frame) {
            return false;
        }
        if (e.moved && std::min(e.worst_a, e.worst_b) >= BigDeviation) {
            return false;
        }
        Entry fresh;
        fresh.size = e.size;
        fresh.bones = e.bones;
        fresh.again = e.again + 1;
        fresh.in_place = e.in_place;
        fresh.forced = e.forced;
        fresh.seen = frame;
        e = std::move(fresh);
        ++rejudged;
        return true;
    }

    [[nodiscard]] std::uint64_t Rejudged() const {
        return rejudged;
    }

    [[nodiscard]] const Entry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return entries.size();
    }

    [[nodiscard]] std::uint64_t Overflow() const {
        return overflow;
    }

    /// The groups line, every 600 frames (r112e: every window, not only when it changes): the
    /// streams drawn within SeenFrames of `frame`, in totals and then by bone count (most bones
    /// first, groups of nothing but character-sized streams left out: they count under `char`),
    /// using `heights` (the height book of r112, by the same stream) for the streams whose
    /// content stayed still:
    ///   hang = taken (still, 0.8-4 m, or its height is being measured), wait = still for fewer
    ///   than StillFrames frames, height = still but outside 0.8-4 m, moving = the content moved
    ///   (dev: the least of the two forms' greatest differences, in tolerances),
    ///   gpu / unmapped / short / nopal / pivot = no content test (Why), char = over CharacterBones
    /// and the totals: read in place, read though GPU-written (forced, BB_WIND_HANG_READ_GPU),
    /// judged again (Due), not kept. The text is at most LineChars characters (the slot report
    /// keeps 300). True (and `out` set) always: the caller prints it.
    bool Report(BbWindHang::Book& heights, std::uint64_t frame, std::string& out) {
        struct Group {
            unsigned streams = 0, hang = 0, wait = 0, height = 0, moving = 0;
            std::array<unsigned, WhyCount> never{};
            double dev = 0.0;
        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned in_place = 0, forced = 0, listed = 0, again = 0;
        unsigned hang = 0, wait = 0, height = 0, moving = 0, unread = 0, chars = 0;
        for (const auto& item : entries) {
            const Entry& e = item.second;
            // a stream the height book settled is no longer judged here: its `seen` counts too
            const BbWindHang::Entry* h = heights.Find(item.first);
            const std::uint64_t last = std::max(e.seen, h == nullptr ? std::uint64_t{0} : h->seen);
            if (last + SeenFrames < frame) {
                continue;
            }
            ++listed;
            in_place += e.in_place ? 1u : 0u;
            forced += e.forced ? 1u : 0u;
            again += e.again != 0 ? 1u : 0u;
            if (e.never == Why::Character) {
                ++chars;
                continue;
            }
            Group& g = groups[e.bones];
            ++g.streams;
            if (e.never != Why::None) {
                ++g.never[std::size_t(e.never)];
                ++unread;
            } else if (e.moved) {
                ++g.moving;
                ++moving;
                g.dev = std::max(g.dev, std::min(e.worst_a, e.worst_b));
            } else {
                switch (h == nullptr ? BbWindHang::Verdict::Waiting : BbWindHang::VerdictOf(*h)) {
                case BbWindHang::Verdict::Still:
                    ++g.hang;
                    ++hang;
                    break;
                case BbWindHang::Verdict::Unfit:
                    ++g.height;
                    ++height;
                    break;
                case BbWindHang::Verdict::Moving:
                    ++g.moving;
                    ++moving;
                    break;
                case BbWindHang::Verdict::Waiting:
                    ++g.wait;
                    ++wait;
                    break;
                }
            }
        }
        char buf[300];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112e): %u sun-drawn skinned: %u hang %u wait %u height %u "
                      "moving %u unread %u char; in place %u, forced %u, judged again %u (%llux), "
                      "not kept %llu; bones",
                      listed, hang, wait, height, moving, unread, chars, in_place, forced, again,
                      static_cast<unsigned long long>(rejudged),
                      static_cast<unsigned long long>(overflow));
        std::string text = buf;
        // the groups with a stream that may hang first, then by bones, most first
        std::vector<std::pair<std::uint32_t, Group>> order(groups.begin(), groups.end());
        const auto candidates = [](const Group& g) { return g.hang + g.wait + g.height; };
        std::stable_sort(order.begin(), order.end(), [&](const auto& x, const auto& y) {
            return candidates(x.second) != 0 && candidates(y.second) == 0;
        });
        std::size_t shown = 0;
        for (const auto& item : order) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", order.size() - shown);
                text += buf;
                break;
            }
            ++shown;
            const Group& g = item.second;
            std::snprintf(buf, sizeof(buf), "; %ub x%u:", item.first, g.streams);
            text += buf;
            const auto put = [&](const char* name, unsigned n) {
                if (n != 0) {
                    std::snprintf(buf, sizeof(buf), " %s=%u", name, n);
                    text += buf;
                }
            };
            put("hang", g.hang);
            put("wait", g.wait);
            put("height", g.height);
            put("moving", g.moving);
            if (g.moving != 0 && g.dev > 0.0) {
                std::snprintf(buf, sizeof(buf), "(dev %.0e tol)", g.dev);
                text += buf;
            }
            for (std::size_t w = 1; w < WhyCount; ++w) {
                put(WhyName(Why(w)), g.never[w]);
            }
        }
        if (text.size() > LineChars) {
            text.resize(LineChars - 3);
            text += "...";
        }
        out = std::move(text);
        return true;
    }

private:
    void Prune(std::uint64_t frame) {
        for (auto it = entries.begin(); it != entries.end();) {
            if (it->second.seen + SeenFrames < frame) {
                it = entries.erase(it);
            } else {
                ++it;
            }
        }
    }

    std::unordered_map<std::uint64_t, Entry> entries;
    std::uint64_t overflow = 0, rejudged = 0;
};

// ------------------------------------------------------------------------------------------------
// bbport (r112f_hang-gpu-judge): the GPU's judgement of a stream's stillness. The vertex shaders
// of a sway draw (any sway word) offer each vertex's WORLD position, after skinning, to the
// stream's base slot: lowest y (BaseAt), highest y (CrownAt), lowest and highest x and z (r89d's
// TwigAt, with BB_WIND_TWIGS on): the mesh's world box, as atomic minima, so it only ever grows.
// The CPU resets a slot's keys, waits, reads them, waits BoxStillFrames, reads again: the
// greatest change of the six numbers is the deviation. Whoever wrote the bone palette, the keys
// are what the screen shows.
inline constexpr float BoxTolDefault = 0.02f;         ///< m: the box of a still mesh grows no more
inline constexpr float BoxTolMin = 0.002f, BoxTolMax = 0.2f; ///< BB_WIND_HANG_BOX_TOL's range (m)
inline constexpr float BoxFinal = 0.25f;              ///< m: grown this much it is a character
inline constexpr std::uint64_t BoxJudgeFrames = BbWindTwigs::JudgeFrames; ///< before the first read
inline constexpr std::uint64_t BoxStillFrames = BbWindTwigs::StillFrames; ///< between the two reads
inline constexpr std::uint64_t BoxCheckFrames = 30;   ///< a still stream's box is read this often
inline constexpr std::uint64_t BoxGiveUpFrames = 300; ///< no key offered in this long: not judged
// bbport (r112g_hang-judge-settles): the first read waits this long for the box keys, then the y
// keys alone judge; the notes of give-ups kept for the log at most
inline constexpr std::uint64_t BoxBoxWaitFrames = 30;
inline constexpr std::size_t NotesMost = 8;
inline constexpr std::size_t BoxStreamsMost = 256;    ///< streams kept
static_assert(BoxJudgeFrames > BbWindSway::FrameSlots, "the GPU is done with the frames read");
static_assert(BoxBoxWaitFrames > BoxJudgeFrames &&
              BoxBoxWaitFrames + BoxStillFrames < BoxGiveUpFrames);
static_assert(BoxTolMin < BoxTolDefault && BoxTolDefault < BoxTolMax && BoxTolMax < BoxFinal);

/// BB_WIND_HANG_BOX_TOL in millimetres (2-200, default 20), read once.
[[nodiscard]] inline float BoxTol() {
    static const float tol = [] {
        const float mm = BbWindSway::ParseNumber(std::getenv("BB_WIND_HANG_BOX_TOL"),
                                                 BoxTolDefault * 1000.0f);
        return std::clamp(mm * 0.001f, BoxTolMin, BoxTolMax);
    }();
    return tol;
}

/// The box keys exist only with BB_WIND_TWIGS on (r89d: the keys, their buffer, their shader code).
[[nodiscard]] inline bool BoxAvailable() {
    return BbWindTwigs::On();
}

/// May the GPU's keys stand in for the palette's content for this stream? `e` its palette entry
/// (may be null), `cpu` what Book::Judge said of this draw. Yes when the palette was read and is
/// still, or it could not be read for a reason that may pass (the GPU wrote it, no mapping, too
/// short, no pivot), and the stream has at most CharacterBones bones. Never a character (more
/// bones), never a stream with no palette bound, never a palette that moved.
[[nodiscard]] inline bool GpuJudgeable(const Entry* e, Result cpu) {
    if (e == nullptr || e->bones == 0 || e->bones > CharacterBones) {
        return false;
    }
    if (cpu == Result::Same) {
        return true;
    }
    return cpu == Result::Never &&
           (e->never == Why::GpuWritten || e->never == Why::NotMapped || e->never == Why::Short ||
            e->never == Why::NoPivot);
}

/// A slot's keys back to ResetKey: base, crown, top and the four box keys (as the caller does when
/// the slot is taken, without BbWindTwigs::ResetSlot's knob test: only called with BoxAvailable()).
inline void ResetKeys(std::uint32_t* words, std::uint32_t slot) {
    words[BbWindSway::BaseAt + slot] = BbWindSway::ResetKey;
    words[BbWindSway::CrownAt + slot] = BbWindSway::ResetKey;
    words[BbWindHang::TopAt + slot] = BbWindSway::ResetKey;
    for (std::uint32_t i = 0; i < BbWindTwigs::TwigSlotWords; ++i) {
        words[BbWindTwigs::TwigAt + slot * BbWindTwigs::TwigSlotWords + i] = BbWindSway::ResetKey;
    }
}

enum class BoxState : std::uint8_t {
    Judging, ///< the window is open: the stream's word has no motion
    Still,   ///< the box did not grow: the CPU's rules go on (height, ramp, push)
    Moved,   ///< it grew (or nothing was offered): not taken
};

/// The keys of a slot as numbers (bbport r112g_hang-judge-settles): base and crown (the y keys,
/// which every vertex of a sway word offers) and the box keys (x and z; a vertex offers them only
/// once the base key is set), each present when it is not ResetKey.
struct BoxMeasure {
    float base = 0.0f, crown = 0.0f, x_lo = 0.0f, x_hi = 0.0f, z_lo = 0.0f, z_hi = 0.0f;
    bool y_ok = false;   ///< base and crown were offered
    bool box_ok = false; ///< and the four box keys too
};

[[nodiscard]] inline BoxMeasure MeasureKeys(const BbWindTwigs::Keys& k) {
    namespace W = BbWindSway;
    BoxMeasure m;
    m.y_ok = k.base != W::ResetKey && k.crown != W::ResetKey;
    m.box_ok = m.y_ok && k.box[0] != W::ResetKey && k.box[1] != W::ResetKey &&
               k.box[2] != W::ResetKey && k.box[3] != W::ResetKey;
    if (m.y_ok) {
        m.base = W::KeyHeight(k.base);
        m.crown = W::KeyCrown(k.crown);
    }
    if (m.box_ok) {
        m.x_lo = W::KeyHeight(k.box[0]);
        m.x_hi = W::KeyCrown(k.box[1]);
        m.z_lo = W::KeyHeight(k.box[2]);
        m.z_hi = W::KeyCrown(k.box[3]);
    }
    return m;
}

/// The greatest change between two reads: of the y keys, and of the box keys when both reads have
/// them (a read without the box keys is compared on y alone).
[[nodiscard]] inline float Deviation(const BoxMeasure& a, const BoxMeasure& b) {
    float d = std::max(std::fabs(a.base - b.base), std::fabs(a.crown - b.crown));
    if (a.box_ok && b.box_ok) {
        d = std::max({d, std::fabs(a.x_lo - b.x_lo), std::fabs(a.x_hi - b.x_hi),
                      std::fabs(a.z_lo - b.z_lo), std::fabs(a.z_hi - b.z_hi)});
    }
    return d;
}

struct BoxEntry {
    std::uint32_t size = 0;                 ///< the position stream's bytes (another: another mesh)
    std::uint32_t slot = 0xffffffffu;       ///< the base slot of the window
    std::uint64_t started = 0, seen = 0;    ///< frame the window began; frame last drawn
    std::uint64_t last = ~std::uint64_t{0}; ///< the last frame stepped (one read a frame at most)
    std::uint64_t snap_at = 0, checked = 0; ///< frame of the first read; of the last read if still
    std::uint64_t settled = 0;              ///< frame it was found moving
    std::uint64_t frames = 0, draws = 0;    ///< frames drawn and draws since the window began
    bool snapped = false;
    bool weak = false; ///< judged on the y keys alone (the box keys never came in time)
    BoxMeasure snap;   ///< the first read
    BoxState state = BoxState::Judging;
    float dev = 0.0f; ///< the greatest change from `snap` seen (m); -1 when no key was ever offered
    // bbport (r112h_hang-not-the-hunter): -2 above when refused as the hunter's, a figure's, indoors
    std::uint64_t hold = 0; ///< frames it is held as moving before Due says so; 0: RejudgeFrames
    bool keyless = false;   ///< it gave up with no key offered
};

struct BoxStats {
    std::uint64_t words = 0;    ///< judging words given (a draw each)
    std::uint64_t reads = 0;    ///< reads of a slot's keys (six mapped words each)
    std::uint64_t restarts = 0; ///< windows begun
    std::uint64_t again = 0;    ///< judged again (Due)
    // bbport (r112g_hang-judge-settles): why windows began, how they ended, what the reads saw
    std::uint64_t began_new = 0, began_reset = 0, began_slot = 0, began_size = 0;
    std::uint64_t frames = 0;    ///< frames a judging stream was drawn, summed
    std::uint64_t gave_up = 0;   ///< windows that ended with no key offered
    std::uint64_t reads_y = 0;   ///< reads with the y keys but not the box keys
    std::uint64_t reads_none = 0; ///< reads with no y key
    std::uint64_t weak = 0;      ///< streams found still on the y keys alone
};

/// What a give-up saw: the stream, its window and the keys as the GPU held them.
struct GiveUpNote {
    std::uint64_t stream = 0, frames = 0, drawn = 0, draws = 0;
    std::uint32_t slot = 0, size = 0;
    std::array<std::uint32_t, 7> keys{}; ///< base, crown, the four box keys, top
};

/// The streams the GPU's keys judge, by position stream address.
class BoxBook {
public:
    /// A draw of `stream` on `frame` whose CPU rules would take it, in base slot `slot` (`reset`:
    /// the slot was just taken, its keys reset by the caller); `words` the sway region's words.
    /// Judging until BoxJudgeFrames + BoxStillFrames frames after the window began; then Still (the
    /// box grew at most BoxTol) or Moved; a Still stream's keys are read again every
    /// BoxCheckFrames frames (it is Moved when the box grew more than twice BoxTol). At most one
    /// read of the mapped memory a frame. (r112g: the first read waits up to BoxBoxWaitFrames
    /// frames for the box keys, then the y keys alone judge; no key at all for BoxGiveUpFrames
    /// frames gives up, with a note.)
    BoxState Step(std::uint64_t stream, std::uint32_t size, std::uint32_t slot, bool reset,
                  std::uint64_t frame, std::uint32_t* words) {
        if (stream == 0 || words == nullptr || slot >= BbWindSway::PlantSlots) {
            return BoxState::Moved;
        }
        auto found = entries.find(stream);
        bool fresh = false;
        if (found == entries.end()) {
            if (entries.size() >= BoxStreamsMost) {
                Prune(frame);
                if (entries.size() >= BoxStreamsMost) {
                    return BoxState::Moved;
                }
            }
            found = entries.emplace(stream, BoxEntry{}).first;
            Start(found->second, size, slot, frame, words, Began::New);
            fresh = true;
        }
        BoxEntry& e = found->second;
        if (!fresh) {
            if (reset) {
                Start(e, size, slot, frame, words, Began::Reset);
            } else if (e.slot != slot) {
                Start(e, size, slot, frame, words, Began::Slot);
            } else if (e.size != size) {
                Start(e, size, slot, frame, words, Began::Size);
            }
        }
        e.seen = frame;
        if (e.state == BoxState::Moved) {
            return Judged(e);
        }
        ++e.draws;
        if (e.last == frame) {
            return Judged(e);
        }
        e.last = frame;
        ++e.frames;
        stats.frames += e.state == BoxState::Judging ? 1u : 0u;
        if (e.state == BoxState::Still) {
            if (frame >= e.checked + BoxCheckFrames) {
                e.checked = frame;
                const BoxMeasure m = Read(words, slot);
                if (m.y_ok) {
                    const float dev = Deviation(e.snap, m);
                    e.dev = std::max(e.dev, dev);
                    if (!(dev <= 2.0f * BoxTol())) {
                        Settle(e, frame);
                    }
                }
            }
            return e.state;
        }
        if (frame < e.started + BoxJudgeFrames ||
            (e.snapped && frame < e.snap_at + BoxStillFrames)) {
            return Judged(e);
        }
        const BoxMeasure m = Read(words, slot);
        if (!m.y_ok) { // nothing offered yet (the mesh may be off screen): wait, then give up
            if (frame >= e.started + BoxGiveUpFrames) {
                GiveUp(e, stream, frame, words);
                return e.state;
            }
            return Judged(e);
        }
        if (!e.snapped) {
            if (!m.box_ok && frame < e.started + BoxBoxWaitFrames) { // the box keys may still come
                return Judged(e);
            }
            e.snapped = true;
            e.snap = m;
            e.snap_at = frame;
            return Judged(e);
        }
        const float dev = Deviation(e.snap, m);
        e.dev = std::max(e.dev, dev);
        e.weak = !(e.snap.box_ok && m.box_ok);
        if (dev <= BoxTol()) {
            e.state = BoxState::Still;
            e.checked = frame;
            stats.weak += e.weak ? 1u : 0u;
        } else {
            Settle(e, frame);
        }
        return e.state;
    }

    /// A stream whose box grew BoxFinal or more: a character, never judged again.
    [[nodiscard]] bool Final(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found != entries.end() && found->second.state == BoxState::Moved &&
               found->second.dev >= BoxFinal;
    }

    /// A stream found moving by less than BoxFinal (or with no key offered), at least RejudgeFrames
    /// ago: true, and it is forgotten (the next Step opens a new window with the keys reset).
    bool Due(std::uint64_t stream, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end() || found->second.state != BoxState::Moved ||
            found->second.dev >= BoxFinal ||
            found->second.settled +
                    (found->second.hold != 0 ? found->second.hold : RejudgeFrames) > frame) {
            return false;
        }
        entries.erase(found);
        ++stats.again;
        return true;
    }

    void Forget(std::uint64_t stream) {
        entries.erase(stream);
    }

    /// bbport (r112q_hang-bracket-route): as Due, but a stream whose box grew BoxFinal or more (a character for good: Due never says yes)
    /// is due too, `retry` frames after it was found moving (BB_WIND_HANG_BOX_RETRY): the caller asks it of a box-judged stream only,
    /// whose union box a camera turn changes. A smaller mover and a stream r112h rejected follow Due's rules (RejudgeFrames, its hold).
    bool DueSoft(std::uint64_t stream, std::uint64_t frame, std::uint64_t retry) {
        const auto found = entries.find(stream);
        if (found == entries.end() || found->second.state != BoxState::Moved) {
            return false;
        }
        if (found->second.dev < BoxFinal) {
            return Due(stream, frame);
        }
        if (found->second.settled + retry > frame) {
            return false;
        }
        entries.erase(found);
        ++stats.again;
        return true;
    }

    /// bbport (r112g_hang-judge-settles): the judge holds `stream` as moving (a verdict, a
    /// give-up): then its own Due decides when it is judged again, not the palette book's.
    [[nodiscard]] bool HoldsMoved(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found != entries.end() && found->second.state == BoxState::Moved;
    }

    /// bbport (r112h_hang-not-the-hunter): `stream` may not hang (the hunter's gear, a figure,
    /// indoors, unplaced): moved at once (dev -2, not final), judged again `hold` frames later (Due).
    /// False when the stream is not known.
    bool Reject(std::uint64_t stream, std::uint64_t frame, std::uint64_t hold) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return false;
        }
        found->second.dev = -2.0f;
        found->second.hold = hold;
        Settle(found->second, frame);
        return true;
    }

    /// bbport (r112h_hang-not-the-hunter): the frames a give-up holds its stream (0: RejudgeFrames,
    /// as r112g).
    void SetKeylessHold(std::uint64_t frames) {
        keyless_hold = frames;
    }

    /// bbport (r112h_hang-not-the-hunter): the streams drawn within SeenFrames that gave up with no key
    /// offered and are still held.
    [[nodiscard]] unsigned Keyless(std::uint64_t frame) const {
        unsigned count = 0;
        for (const auto& item : entries) {
            const BoxEntry& e = item.second;
            count += e.keyless && e.state == BoxState::Moved && e.seen + SeenFrames >= frame ? 1u : 0u;
        }
        return count;
    }

    /// The notes of give-ups since the last ClearNotes (at most NotesMost; Counts().gave_up counts
    /// all).
    [[nodiscard]] const std::vector<GiveUpNote>& Notes() const {
        return notes;
    }

    void ClearNotes() {
        notes.clear();
    }

    /// The line after the judge's own (under LineChars characters): why windows began (new stream,
    /// its slot taken again, another slot, another size), how often a judged stream was drawn a
    /// frame, what the reads saw (y keys only, none), the give-ups, the stills judged on the y
    /// keys alone. True always: the caller prints it.
    bool Causes(std::string& out) const {
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        char buf[320];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112g): windows begun %llu (%llu new, %llu slot, %llu size, "
                      "%llu reset); a judged stream drawn %.2f times a frame; of %llu reads %llu "
                      "had the y keys only and %llu none; gave up %llu; still on the y keys alone "
                      "%llu; heights %.2f-%.1f m",
                      n(stats.restarts), n(stats.began_new), n(stats.began_slot),
                      n(stats.began_size), n(stats.began_reset),
                      stats.frames == 0 ? 0.0 : double(stats.words) / double(stats.frames),
                      n(stats.reads), n(stats.reads_y), n(stats.reads_none), n(stats.gave_up),
                      n(stats.weak), double(BbWindHang::MinExtent), double(BbWindHang::MaxExtent));
        out = buf;
        if (out.size() > LineChars) {
            out.resize(LineChars - 3);
            out += "...";
        }
        return true;
    }

    [[nodiscard]] const BoxEntry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return entries.size();
    }

    [[nodiscard]] const BoxStats& Counts() const {
        return stats;
    }

    /// The line every 600 frames (under LineChars characters): the totals (judging, still = the box
    /// held but the height is not measured yet, hang = still and 0.8-4 m, height = still and out of
    /// it, moved), the counts, then the groups by the palette's bone count (`palettes`: the content
    /// book knows it), those with a stream that may hang first: per group the classes, `quiet` the
    /// greatest deviation of a still one (mm) and `moved` the least of a moving one (mm).
    /// `heights` is r112's book. True always: the caller prints it.
    bool Report(BbWindHang::Book& heights, const Book& palettes, std::uint64_t frame,
                std::string& out) const {
        struct Group {
            unsigned streams = 0, judging = 0, still = 0, hang = 0, height = 0, moved = 0;
            float quiet = 0.0f; ///< the greatest deviation of a stream the keys found still (m)
            float least = -1.0f; ///< the least of one they found moving (m); -1: none
        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned listed = 0, judging = 0, still = 0, hang = 0, height = 0, moved = 0;
        for (const auto& item : entries) {
            const BoxEntry& e = item.second;
            if (e.seen + SeenFrames < frame) {
                continue;
            }
            const Entry* const palette = palettes.Find(item.first);
            Group& g = groups[palette == nullptr ? 0u : palette->bones];
            ++listed;
            ++g.streams;
            switch (e.state) {
            case BoxState::Judging:
                ++g.judging;
                ++judging;
                break;
            case BoxState::Moved:
                ++g.moved;
                ++moved;
                if (e.dev >= 0.0f && (g.least < 0.0f || e.dev < g.least)) {
                    g.least = e.dev;
                }
                break;
            case BoxState::Still: {
                const BbWindHang::Entry* const h = heights.Find(item.first);
                if (h != nullptr && h->judged && h->fits) {
                    ++g.hang;
                    ++hang;
                } else if (h != nullptr && h->judged) {
                    ++g.height;
                    ++height;
                } else {
                    ++g.still;
                    ++still;
                }
                g.quiet = std::max(g.quiet, e.dev);
                break;
            }
            }
        }
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        char buf[300];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112f): GPU judge, tol %.0f mm: %u streams: %u judging "
                      "%u still %u hang %u height %u moved; words %llu, reads %llu, restarts "
                      "%llu, again %llu; bones",
                      double(BoxTol()) * 1000.0, listed, judging, still, hang, height, moved,
                      n(stats.words), n(stats.reads), n(stats.restarts), n(stats.again));
        std::string text = buf;
        std::vector<std::pair<std::uint32_t, Group>> order(groups.begin(), groups.end());
        const auto may = [](const Group& g) { return g.judging + g.still + g.hang + g.height; };
        std::stable_sort(order.begin(), order.end(), [&](const auto& x, const auto& y) {
            return may(x.second) != 0 && may(y.second) == 0;
        });
        std::size_t shown = 0;
        for (const auto& item : order) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", order.size() - shown);
                text += buf;
                break;
            }
            ++shown;
            const Group& g = item.second;
            std::snprintf(buf, sizeof(buf), "; %ub x%u:", item.first, g.streams);
            text += buf;
            const auto put = [&](const char* name, unsigned count) {
                if (count != 0) {
                    std::snprintf(buf, sizeof(buf), " %s=%u", name, count);
                    text += buf;
                }
            };
            put("judging", g.judging);
            put("still", g.still);
            put("hang", g.hang);
            put("height", g.height);
            put("moved", g.moved);
            if (g.streams != g.judging + g.moved) {
                std::snprintf(buf, sizeof(buf), " quiet<=%.0fmm", double(g.quiet) * 1000.0);
                text += buf;
            }
            if (g.least >= 0.0f) {
                std::snprintf(buf, sizeof(buf), " moved>=%.0fmm", double(g.least) * 1000.0);
                text += buf;
            }
        }
        if (text.size() > LineChars) {
            text.resize(LineChars - 3);
            text += "...";
        }
        out = std::move(text);
        return true;
    }

private:
    /// One read of a slot's keys (mapped memory), counted for the line.
    BoxMeasure Read(const std::uint32_t* words, std::uint32_t slot) {
        ++stats.reads;
        const BoxMeasure m = MeasureKeys(BbWindTwigs::ReadKeys(words, slot));
        stats.reads_y += m.y_ok && !m.box_ok ? 1u : 0u;
        stats.reads_none += m.y_ok ? 0u : 1u;
        return m;
    }

    enum class Began : std::uint8_t { New, Reset, Slot, Size };

    void Start(BoxEntry& e, std::uint32_t size, std::uint32_t slot, std::uint64_t frame,
               std::uint32_t* words, Began why) {
        e = BoxEntry{};
        e.size = size;
        e.slot = slot;
        e.started = frame;
        e.seen = frame;
        ResetKeys(words, slot); // a new window: the history of an earlier life does not count
        ++stats.restarts;
        stats.began_new += why == Began::New ? 1u : 0u;
        stats.began_reset += why == Began::Reset ? 1u : 0u;
        stats.began_slot += why == Began::Slot ? 1u : 0u;
        stats.began_size += why == Began::Size ? 1u : 0u;
    }

    void Settle(BoxEntry& e, std::uint64_t frame) {
        e.state = BoxState::Moved;
        e.settled = frame;
    }

    /// No y key was offered in BoxGiveUpFrames frames: Moved with dev -1 (judged again after
    /// RejudgeFrames), and a note of what the keys held.
    void GiveUp(BoxEntry& e, std::uint64_t stream, std::uint64_t frame,
                const std::uint32_t* words) {
        e.dev = -1.0f;
        e.keyless = true; // bbport (r112h_hang-not-the-hunter): held keyless_hold frames (0: as before)
        e.hold = keyless_hold;
        Settle(e, frame);
        ++stats.gave_up;
        if (notes.size() >= NotesMost) {
            return;
        }
        const BbWindTwigs::Keys k = BbWindTwigs::ReadKeys(words, e.slot);
        const volatile std::uint32_t* const v = words;
        GiveUpNote note;
        note.stream = stream;
        note.frames = frame - e.started;
        note.drawn = e.frames;
        note.draws = e.draws;
        note.slot = e.slot;
        note.size = e.size;
        note.keys = {k.base,   k.crown,  k.box[0], k.box[1],
                     k.box[2], k.box[3], v[BbWindHang::TopAt + e.slot]};
        notes.push_back(note);
    }

    /// The answer of a Judging entry's draw (a word with no motion is given: counted); else as is.
    BoxState Judged(const BoxEntry& e) {
        stats.words += e.state == BoxState::Judging ? 1u : 0u;
        return e.state;
    }

    void Prune(std::uint64_t frame) {
        for (auto it = entries.begin(); it != entries.end();) {
            if (it->second.seen + SeenFrames < frame) {
                it = entries.erase(it);
            } else {
                ++it;
            }
        }
    }

    std::unordered_map<std::uint64_t, BoxEntry> entries;
    BoxStats stats;
    std::vector<GiveUpNote> notes; // bbport (r112g_hang-judge-settles): at most NotesMost
    std::uint64_t keyless_hold = 0; // bbport (r112h_hang-not-the-hunter): see SetKeylessHold
};

} // namespace BbWindHangStill
