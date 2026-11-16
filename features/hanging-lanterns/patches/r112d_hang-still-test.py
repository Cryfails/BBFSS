# r112d_hang-still-test: FEATURE fix on top of r112_wind-more-things.fixed (+ r112c_hang-reset-guard and the
# TOOL r112b_hang-probe, all applied; r116 and r117 are applied before it in the tree and are not touched).
# Behind r112's own knob BB_WIND_HANG=1 (off by default; with it off nothing of this runs: the only
# edited function, Rasterizer::WindHangVerdict, returns at its first line when the knob is off, the
# report lines sit inside r112's knob-on block, and the new members are an empty unordered_map and a
# string). No new knob.
#
# What was wrong (r112b probe, hangprobe_graveyard.txt, hangprobe_alley.txt): r112 took no hanging thing
# ("hang none", 45 of 45 skinned streams "moving") because (1) it called a stream moving when the HASH of
# its palette bytes changed: the game writes palettes to a per-frame ring (address changes on every
# draw) and one stream (128 bones) differed in 3 words by 3e-16, float noise; (2) 22 of 30 graveyard
# palettes (the 84, 48 and 28 bone ones, several streams sharing one palette address) and 14 of 27 in
# the alley could not be read at all.
#
# The fix:
#  1. Content test (new shim/bbport_wind_hang_still.h, BbWindHangStill): the bones taken relative to a
#     pivot bone (shape A = inverse(P) Mi, shape B = Mi inverse(P): a camera on the left cancels in A, on
#     the right in B), the first frame's shapes kept per position stream (its address and its bone count,
#     never the palette's address), later frames compared with them within 1e-3 m (translation) and 1e-3
#     (other elements); moving for good when both shapes left the tolerance. WindHangVerdict feeds the
#     result to r112's BbWindHang::Book unchanged (a constant hash, readable = the content test passed),
#     so the frames, the height measure, the settled shortcut and the verdicts are r112's.
#  2. Why 84/48/28 bone palettes could not be read: the reader (r112's WindHangVerdict, copied into the
#     r112b probe) refuses a palette when (a) the page is GPU-modified and not bound in place, (b) there
#     is no GPU mapping at its address, or (c) the mapping ends inside it. Not (b)/(c) for 300 of 300 draws
#     across sizes 1344, 2304 and 4032 bytes while 3328, 6144 and 13312 byte palettes at the same kind of
#     address read fine; (a) fits: BufferCache::ObtainBuffer (buffer_cache.cpp, GuestInPlace branch)
#     keeps a range the GPU writes regularly (NoteGpuWrite: 3 frames of 60) as VRAM data ("the CPU does
#     not read what the GPU wrote there (no readbacks)") unless BB_GPU_WRITES_IN_PLACE=1, so the CPU copy of
#     such a ring is stale and WindHangVerdict (right) refuses it. The change keeps the reason of each
#     refusal (Why) and logs it, so the next run states it per group; BB_GPU_WRITES_IN_PLACE=1 (a test
#     setting: about 9 ms a frame) makes those palettes bound in place and so readable. There is no
#     readback here: a palette that is only in VRAM stays unread and its stream is never taken.
#  3. Groups: a palette of more than 96 bones is character-sized and never taken (the hunter 277, the
#     128 bone rig, whatever else is big); the 28-84 bone groups are judged by content. One line per run
#     (again only if it changes) names, by bone count, the streams taken (hang), waiting (wait), still
#     but outside 0.8-4 m (height), moving (moving, with the greatest deviation in tolerances), unread
#     (gpu, unmapped, short, nopal, pivot) and character-sized (char), and how many palettes were read in
#     place.
#
# Files: new engine/gpu/shim/bbport_wind_hang_still.h and engine/tests/test_wind_hang_still.cpp (its twin
# in Python: r112d_twin.py). Edits: vk_rasterizer.h (include, member hang_still), vk_rasterizer_effects.cpp
# (the hash block of WindHangVerdict, the groups line in r112's 600-frame block), CMakeLists.txt and
# build.sh (the test next to r112's wind-hang-test). No shader, no host shader, no add_host_shader line.
#
# Use: python -I -X utf8 r112d_hang-still-test.py check | apply | revert
# Root: R112D_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112d_backup next to
# this script; revert takes out exactly what apply put in and removes the new files.
import os, sys

ROOT = os.environ.get("R112D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112d_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RH = RV + "vk_rasterizer.h"
RE = RV + "vk_rasterizer_effects.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
NH = "engine/gpu/shim/bbport_wind_hang_still.h"
NT = "engine/tests/test_wind_hang_still.cpp"

NEW_FILES = {
NH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "bbport_wind_hang.h"

namespace BbWindHangStill {

inline constexpr std::uint32_t BoneBytes = 48;      ///< 3 rows of 4 floats
inline constexpr std::uint32_t CharacterBones = 96; ///< more bones: a character, never taken
inline constexpr std::uint32_t PivotTries = 8;      ///< bones tried as the pivot
inline constexpr double TolMove = 1e-3;             ///< m: a translation element may differ so much
inline constexpr double TolTurn = 1e-3;             ///< any other element
inline constexpr std::size_t StreamsMost = 256;     ///< streams kept (more: never taken)
inline constexpr std::uint64_t SeenFrames = BbWindHang::BookKeep; ///< listed if drawn this recently
inline constexpr std::size_t GroupsMost = 12;       ///< groups the line names at most
inline constexpr std::size_t LineMost = 380;        ///< characters of the groups line, about

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
    Why never = Why::None;
    double worst_a = 0.0, worst_b = 0.0; ///< greatest difference from `ref`, in tolerances
    Shape ref;
};

/// The streams whose palettes are judged, by their position stream's address.
class Book {
public:
    /// A skinned draw of `stream` on `frame`: `palette` its bone palette's bytes (null: not
    /// readable, `why` says why), `size` their number, `in_place` it was read from a GPU-written
    /// page bound in place. Same: this frame's palette is the first one's.
    Result Judge(std::uint64_t stream, std::uint32_t size, const unsigned char* palette, Why why,
                 bool in_place, std::uint64_t frame) {
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
            return Result::Never;
        }
        if (palette == nullptr) { // first: the log should say why a big palette was not read too
            e.never = why == Why::None ? Why::NoPalette : why;
            e.ref = Shape{};
            return Result::Never;
        }
        if (e.bones > CharacterBones) {
            e.never = Why::Character;
            e.ref = Shape{};
            return Result::Never;
        }
        e.in_place = e.in_place || in_place;
        if (!e.have) {
            if (!MakeShape(palette, e.bones, e.ref)) {
                e.never = Why::NoPivot;
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
            e.ref = Shape{};
            return Result::Never;
        }
        const bool a = Within(e.ref.a, now.a, e.worst_a);
        const bool b = Within(e.ref.b, now.b, e.worst_b);
        e.a_alive = e.a_alive && a;
        e.b_alive = e.b_alive && b;
        if (!e.a_alive && !e.b_alive) {
            e.moved = true;
            e.ref = Shape{};
            return Result::Moved;
        }
        return Result::Same;
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

    /// The groups line (by bone count, most bones first; every stream drawn within SeenFrames of
    /// `frame`): per group the streams in each class, using `heights` (the height book of r112,
    /// by the same stream) for the streams whose content stayed still:
    ///   hang = taken (still, 0.8-4 m, or its height is being measured), wait = still for fewer
    ///   than StillFrames frames, height = still but outside 0.8-4 m, moving = the content moved
    ///   (dev: the least of the two forms' greatest differences, in tolerances),
    ///   gpu / unmapped / short / nopal / pivot = no content test (Why), char = over CharacterBones
    /// True (and `out` set) when the line differs from the last one reported: one line per run once
    /// the groups are known. At most GroupsMost groups are named.
    bool Report(BbWindHang::Book& heights, std::uint64_t frame, std::string& out) {
        struct Group {
            unsigned streams = 0, hang = 0, wait = 0, height = 0, moving = 0;
            std::array<unsigned, WhyCount> never{};
            double dev = 0.0;
        };
        std::map<std::uint32_t, Group, std::greater<std::uint32_t>> groups;
        unsigned in_place = 0, listed = 0;
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
            Group& g = groups[e.bones];
            ++g.streams;
            if (e.never != Why::None) {
                ++g.never[std::size_t(e.never)];
            } else if (e.moved) {
                ++g.moving;
                g.dev = std::max(g.dev, std::min(e.worst_a, e.worst_b));
            } else {
                switch (h == nullptr ? BbWindHang::Verdict::Waiting : BbWindHang::VerdictOf(*h)) {
                case BbWindHang::Verdict::Still:
                    if (h->judged && !h->fits) {
                        ++g.height;
                    } else {
                        ++g.hang;
                    }
                    break;
                case BbWindHang::Verdict::Unfit:
                    ++g.height;
                    break;
                case BbWindHang::Verdict::Moving:
                    ++g.moving;
                    break;
                case BbWindHang::Verdict::Waiting:
                    ++g.wait;
                    break;
                }
            }
        }
        char buf[200];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112d): %u sun-shadowed skinned streams by bones "
                      "(%u palettes read in place, %llu not kept)",
                      listed, in_place, static_cast<unsigned long long>(overflow));
        std::string text = buf;
        std::size_t shown = 0;
        for (const auto& item : groups) {
            if (shown == GroupsMost || text.size() > LineMost) {
                std::snprintf(buf, sizeof(buf), "; +%zu groups", groups.size() - shown);
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
        if (text == last_line) {
            return false;
        }
        last_line = text;
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
    std::uint64_t overflow = 0;
    std::string last_line;
};

} // namespace BbWindHangStill
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112d_hang-still-test): the content test of the hanging things' palettes (gpu/shim/
// bbport_wind_hang_still.h): shapes relative to the pivot, the tolerance, the book, the groups
// line.
// The twin in Python (r112d_twin.py) holds the same cases.
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
    // the groups line: groups by bones, the classes, once
    {
        S::Book book;
        BbWindHang::Book heights;
        const auto bytes = Bytes(base);
        const std::uint32_t size = std::uint32_t(bytes.size());
        for (std::uint64_t f = 0; f < 70; ++f) {
            // stream 10: still, 28 bones; 11: moving; 12: unreadable (84 bones); 13: 128 bones
            const auto r10 = book.Judge(10, size, bytes.data(), S::Why::None, true, f);
            heights.Note(10, 4096, 0, r10 == S::Result::Same, f, 1);
            std::vector<S::Mat> turning = base;
            turning[4] = RotZ(0.1 * double(f), 0.0, 1.0, 0.0);
            const auto b11 = Bytes(turning);
            const auto r11 = book.Judge(11, size, b11.data(), S::Why::None, false, f);
            heights.Note(11, 4096, 0, r11 == S::Result::Same, f, 1);
            book.Judge(12, 84 * S::BoneBytes, nullptr, S::Why::GpuWritten, false, f);
            book.Judge(13, 128 * S::BoneBytes, bytes.data(), S::Why::None, false, f);
        }
        std::string line;
        Expect(book.Report(heights, 70, line), "the groups line is reported");
        Expect(line.find("28b x2:") != std::string::npos, "groups: 28 bones, 2 streams");
        Expect(line.find(" hang=1") != std::string::npos, "groups: the still one hangs");
        Expect(line.find(" moving=1(dev ") != std::string::npos, "groups: the turning one moves");
        Expect(line.find("84b x1: gpu=1") != std::string::npos, "groups: 84 bones, gpu");
        Expect(line.find("128b x1: char=1") != std::string::npos, "groups: 128 bones, char");
        Expect(line.find("1 palettes read in place") != std::string::npos,
               "groups: in place count");
        Expect(line.find("; 128b x") < line.find("; 84b x") &&
                   line.find("; 84b x") < line.find("; 28b x"),
               "groups: most bones first");
        Expect(!book.Report(heights, 70, line), "the same line is not reported twice");
        Expect(line.size() < 400, "the line is short");
    }
    if (failures == 0) {
        std::printf("wind-hang-still-test: all passed\n");
    }
    return failures == 0 ? 0 : 1;
}
''',
}

OLD_VERDICT = r'''    u64 hash = 0;
    bool readable = true;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || buffer.GetStride() != 16 ||
            Motion::ClassifyBuffer(size) != Motion::BufferRole::Skeleton) {
            continue;
        }
        if ((buffer_cache.IsRegionGpuModified(buffer.base_address, size) &&
             !buffer_cache.IsInPlace(buffer.base_address, size)) ||
            !memory->IsValidGpuMapping(buffer.base_address, 0) ||
            memory->ClampRangeSize(buffer.base_address, size) != size) {
            readable = false;
            break;
        }
        hash = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address), size, hash);
    }
    switch (hang_book.Note(positions, positions_size, hash, readable, frame, vs.pgm_hash)) {
'''

NEW_VERDICT = r'''    // bbport (r112d_hang-still-test): the first Skeleton-size palette (stride 16) is judged by
    // its content relative to its pivot bone, within a tolerance (BbWindHangStill), not by a
    // hash of its bytes: the game writes palettes to a ring (the address changes on every draw)
    // and float noise changed a hash. The reader's tests are r112's, in its order; the one that
    // refuses is kept (Why).
    const unsigned char* palette = nullptr;
    u32 palette_size = 0;
    bool in_place = false;
    BbWindHangStill::Why why = BbWindHangStill::Why::None;
    for (const auto& resource : vs.buffers) {
        if (resource.IsSpecial()) {
            continue;
        }
        const auto buffer = resource.GetSharp(vs);
        const u32 size = buffer.GetSize();
        if (!buffer.Valid() || buffer.GetStride() != 16 ||
            Motion::ClassifyBuffer(size) != Motion::BufferRole::Skeleton) {
            continue;
        }
        palette_size = size;
        const bool gpu = buffer_cache.IsRegionGpuModified(buffer.base_address, size);
        in_place = gpu && buffer_cache.IsInPlace(buffer.base_address, size);
        if (gpu && !in_place) {
            why = BbWindHangStill::Why::GpuWritten;
        } else if (!memory->IsValidGpuMapping(buffer.base_address, 0)) {
            why = BbWindHangStill::Why::NotMapped;
        } else if (memory->ClampRangeSize(buffer.base_address, size) != size) {
            why = BbWindHangStill::Why::Short;
        } else {
            palette = reinterpret_cast<const unsigned char*>(buffer.base_address);
        }
        break;
    }
    const bool still = hang_still.Judge(positions, palette_size, palette, why, in_place, frame) ==
                       BbWindHangStill::Result::Same;
    switch (hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)) {
'''

EDITS = {
RH: [
("ins", '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n', "",
        '#include "bbport_wind_hang_still.h" // bbport (r112d_hang-still-test)\n'),
("ins", "    BbWindHang::Stats hang_stats;\n", "",
        "    BbWindHangStill::Book hang_still; // bbport (r112d_hang-still-test): palettes' content\n"),
],
RE: [
("rep", OLD_VERDICT, "", NEW_VERDICT),
("ins", "        hang_stats = {};\n",
r"""        std::string still_line; // bbport (r112d_hang-still-test): groups by bones, once
        if (hang_still.Report(hang_book, object_motion->Frame(), still_line)) {
            BbReport::Printf("%s\n", still_line.c_str());
        }
""", ""),
],
CM: [
("ins", "target_include_directories(wind-hang-test PRIVATE ..)\n", "",
r"""# bbport (r112d_hang-still-test): the palettes' content test (shim/bbport_wind_hang_still.h); also
# built and run by engine/build.sh --test.
add_executable(wind-hang-still-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_still.cpp)
target_compile_options(wind-hang-still-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-still-test PRIVATE ..)
"""),
],
BS: [
("ins", "    out/wind-hang-test\n", "",
r"""    # bbport (r112d_hang-still-test): the hanging things' palette content test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang_still.cpp -o out/wind-hang-still-test
    out/wind-hang-still-test
"""),
],
}

ORDER = (RH, RE, CM, BS)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    """(anchor-or-old, texts that must each be found exactly once when applied, texts that must be
    gone when applied)."""
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    have = open(full, "rb").read().replace(b"\r\n", b"\n")
    if have == NEW_FILES[path].encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists with other content" % path)


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def text_checks(texts):
    """The ties a compiler cannot check."""
    def need(path, want, n):
        if texts[path].count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" %
                             (path, want, texts[path].count(want), n))
    re_ = texts[RE]
    need(RE, "hang_still.Judge(positions, palette_size, palette, why, in_place, frame)", 1)
    need(RE, "hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)", 1)
    need(RE, "hang_still.Report(hang_book, object_motion->Frame(), still_line)", 1)
    need(RE, "hash, readable, frame, vs.pgm_hash", 0)
    need(RH, "BbWindHangStill::Book hang_still;", 1)
    need(RH, '#include "bbport_wind_hang_still.h"', 1)
    need(CM, "wind-hang-still-test", 3)
    need(BS, "test_wind_hang_still.cpp", 1)
    # the content test sits inside WindHangVerdict, after r112's knob test, the sun test and the
    # settled shortcut, before the book's verdict
    a = re_.find("bool Rasterizer::WindHangVerdict(")
    k = re_.find("if (!BbWindHang::KnobOnce().on) {", a)
    s = re_.find("rt_shadow->SunSkinned(positions, positions_size)", a)
    t = re_.find("hang_book.Settled(positions, positions_size, frame)", a)
    j = re_.find("hang_still.Judge(", a)
    n = re_.find("hang_book.Note(", a)
    e = re_.find("\n}\n", a)
    if not (0 <= a < k < s < t < j < n < e):
        raise SystemExit("text check: the content test is not in order inside WindHangVerdict")
    # the groups line sits inside r112's knob-on block, before hang_stats is cleared
    r = re_.find("hang_still.Report(")
    h = re_.find("hang_stats = {};", r)
    b = re_.find("if (BbWindHang::KnobOnce().on) { // bbport (r112_wind-more-things): its two lines")
    if not (0 <= b < r < h):
        raise SystemExit("text check: the groups line is not in r112's knob-on block")
    for path in (RH, RE):
        for ed in EDITS[path]:
            for part in (ed[3:] if ed[0] == "rep" else ed[2:]):
                for line in part.split("\n"):
                    if len(line) > 100:
                        raise SystemExit("text check: %s: a new line over 100 columns: %r" %
                                         (path, line[:60]))
    hh, tt = NEW_FILES[NH], NEW_FILES[NT]
    for name, body in NEW_FILES.items():
        for line in body.split("\n"):
            if len(line) > 100:
                raise SystemExit("text check: %s: a line over 100 columns: %r" % (name, line[:60]))
        if not body.isascii() or "\t" in body or "\r" in body:
            raise SystemExit("text check: %s is not plain ASCII without tabs" % name)
    for want in ("TolMove = 1e-3;", "TolTurn = 1e-3;", "CharacterBones = 96;", "StreamsMost = 256;",
                 "namespace BbWindHangStill", "bool Report(BbWindHang::Book& heights"):
        if want not in hh:
            raise SystemExit("text check: %r is missing in the header" % want)
    if "gpu/shim/bbport_wind_hang_still.h" not in tt or "return failures == 0 ? 0 : 1;" not in tt:
        raise SystemExit("text check: the test lacks its include or its result")
    # every Why has a name and a count slot
    if hh.count("case Why::") != 7 or "WhyCount = 7;" not in hh:
        raise SystemExit("text check: WhyName does not cover the reasons")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112D_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == RE and "bool Rasterizer::WindHangVerdict(" not in cur:
            raise SystemExit("REFUSED: r112_wind-more-things is not applied (no WindHangVerdict)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    news = {p: new_state(p) for p in NEW_FILES}
    states = {p[5] for p in plan} | set(news.values())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                     ["%s %s" % (p, s) for p, s in news.items()]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new; text checks on the "
                  "result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112dtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, body in NEW_FILES.items():
            full = os.path.join(ROOT, path)
            tmp = full + ".r112dtmp"
            open(tmp, "wb").write(body.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112dtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
