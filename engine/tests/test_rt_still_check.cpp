// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r47_still-check): the looks at the ray tracing scene's casters held for still
// (rt_still_check.h): the order of the keys the shader compares, a signature's bounds, how far
// two captures differ, a capture's way from clip space to the world under two poses of the
// camera, when the next look comes, the knobs and BB_RT_LAMP_LEAVE's classes.
// bbport (r47c_review-fixes): the looks in turn where a scene holds more casters than the
// budget serves at the usual period, and where some are drawn on every 8th frame only (the
// pace by the pool, the second budget of the looks that waited long), and StillSameSize.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"

using namespace Vulkan;

namespace {
using Sig = std::array<std::uint32_t, StillSigWords>;

// The signature of a mesh's vertices, each moved by `shift`.
Sig Measure(const std::array<std::array<float, 3>, 5>& mesh, float sx, float sy, float sz) {
    Sig sig{};
    for (const auto& p : mesh) {
        StillSigAdd(sig.data(), p[0] + sx, p[1] + sy, p[2] + sz);
    }
    return sig;
}

// A camera as the game's draws give it to RtShadow: view to world rows (3x4), the projection's
// inverse (4x4 rows), and what a vertex shader works with: world to view rows and the
// projection's four numbers. All in float, as the game holds them.
struct Camera {
    std::array<float, 12> view_to_world{}, world_to_view{};
    std::array<float, 16> inverse{};
    float p00 = 0, p11 = 0, a = 0, b = 0;
};
Camera MakeCamera(double yaw, double pitch, const std::array<double, 3>& at, double near_plane) {
    const double cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
    // The columns of view to world: the camera's right, up and back in the world.
    const double m[3][3] = {{cy, sy * sp, sy * cp}, {0.0, cp, -sp}, {-sy, cy * sp, cy * cp}};
    Camera c;
    for (int r = 0; r < 3; ++r) {
        double t = 0.0;
        for (int k = 0; k < 3; ++k) {
            c.view_to_world[r * 4 + k] = float(m[r][k]);
            c.world_to_view[r * 4 + k] = float(m[k][r]);
            t -= m[k][r] * at[k];
        }
        c.view_to_world[r * 4 + 3] = float(at[r]);
        c.world_to_view[r * 4 + 3] = float(t);
    }
    const double far_plane = 3000.0, p00 = 1.0 / std::tan(0.6), p11 = p00 * 16.0 / 9.0;
    const double a = far_plane / (near_plane - far_plane), b = near_plane * a;
    c.p00 = float(p00), c.p11 = float(p11), c.a = float(a), c.b = float(b);
    c.inverse = {float(1.0 / p00), 0, 0, 0, 0, float(1.0 / p11), 0, 0,
                 0, 0, 0, -1, 0, 0, float(1.0 / b), float(a / b)};
    return c;
}
// The clip space position a vertex shader stores for a point of the world.
std::array<float, 4> Clip(const Camera& c, const std::array<float, 3>& p) {
    std::array<float, 3> v{};
    for (int k = 0; k < 3; ++k) {
        v[k] = c.world_to_view[k * 4] * p[0] + c.world_to_view[k * 4 + 1] * p[1] +
               c.world_to_view[k * 4 + 2] * p[2] + c.world_to_view[k * 4 + 3];
    }
    return {c.p00 * v[0], c.p11 * v[1], c.a * v[2] + c.b, -v[2]};
}
// The one product the scene's positions are made with (RtShadow::ToWorld and
// rt_unproject.comp): what the signatures were first measured from.
std::array<float, 3> OneProduct(const Camera& c, const std::array<float, 4>& clip) {
    std::array<float, 3> p{};
    for (int r = 0; r < 3; ++r) {
        std::array<float, 4> row{};
        for (int col = 0; col < 4; ++col) {
            float sum = c.view_to_world[r * 4 + 3] * c.inverse[12 + col];
            for (int k = 0; k < 3; ++k) {
                sum += c.view_to_world[r * 4 + k] * c.inverse[k * 4 + col];
            }
            row[col] = sum;
        }
        p[r] = row[0] * clip[0] + row[1] * clip[1] + row[2] * clip[2] + row[3] * clip[3];
    }
    return p;
}

// bbport (r47c_review-fixes): the looks in turn as RtShadow::PrepareDraw hands them out, in draw
// order: `count` casters that every frame draws, then `rare` casters that only every 8th frame
// draws and the camera pass does not (a far sun cascade's: looked at four times more rarely).
// One whose look is due gets it unless its budget is used up when its draw comes, and comes
// again StillNext frames later. `by_pool`: the pace (StillNext's crowd) is set by all of them
// (StillPoolShare, StillPoolPeak), else by those due on the frame before, as r47 first did it.
// `overdue`: BB_RT_STILL_OVERDUE (0: no second budget). Returns the longest any look waited for
// a budget in the second half of 8000 frames, served or not.
std::uint64_t LongestWait(bool by_pool, std::uint32_t overdue, std::uint32_t count,
                          std::uint32_t rare) {
    struct Caster {
        std::uint32_t triangles;
        std::uint64_t key, next;
    };
    std::vector<Caster> casters(count + rare);
    std::uint64_t seed = 12345;
    const auto rnd = [&] {
        seed = seed * 6364136223846793005ull + 1442695040888963407ull;
        return std::uint32_t(seed >> 33);
    };
    for (Caster& c : casters) {
        c.triangles = 200 + rnd() % 7000;
        c.key = rnd();
        c.next = rnd() % 96;
    }
    StillPoolPeak peak;
    std::uint64_t due_last = 0, pool_last = 0, longest = 0;
    for (std::uint64_t frame = 0; frame < 8000; ++frame) {
        std::uint64_t due = 0, pool = 0;
        std::array<std::uint64_t, 4> used{};
        const std::uint32_t drawn = frame % 8 == 0 ? count + rare : count;
        for (std::uint32_t i = 0; i < drawn; ++i) {
            Caster& c = casters[i];
            const bool nearby = i < count;
            pool += StillPoolShare(c.triangles, nearby);
            if (frame < c.next) {
                continue;
            }
            due += c.triangles;
            if (frame >= 4000) {
                longest = std::max(longest, frame - c.next);
            }
            const std::uint32_t lane =
                StillLaneOf(StillEarlyChecks, used[2] >= StillBudget, frame - c.next, overdue);
            assert(lane == 2 || (lane == 3 && overdue != 0 && frame - c.next >= overdue));
            if (used[lane] >= StillBudget) {
                continue;
            }
            used[lane] += c.triangles;
            c.next = frame + StillNext(StillEarlyChecks, c.key, nearby,
                                       StillCrowd(by_pool ? pool_last : due_last, StillBudget));
        }
        due_last = due;
        pool_last = peak.End(pool, frame + 1);
    }
    return longest;
}
} // namespace

int main() {
    // Usable where the engine needs a constant; the layout the shader writes.
    static_assert(StillSigWords == 8 && StillSigsPerFrame == 2048 && StillEarlyChecks == 3);
    static_assert(StillKey(-1.0f) < StillKey(-0.0f) && StillKey(-0.0f) < StillKey(0.0f) &&
                  StillKey(0.0f) < StillKey(1.0f));
    static_assert(StillNext(0, 7, true) == 2 && StillNext(1, 7, false) == 6);

    // The keys keep the order of the floats, negative, zero and positive, and come back as the
    // same bits.
    const float inf = std::numeric_limits<float>::infinity();
    const std::array<float, 15> ordered{-inf, -3.0e38f, -1024.5f, -1.0f, -1.0e-30f,
                                        -std::numeric_limits<float>::denorm_min(), -0.0f, 0.0f,
                                        std::numeric_limits<float>::denorm_min(), 1.0e-30f,
                                        0.004f, 1.0f, 1024.5f, 3.0e38f, inf};
    for (std::size_t i = 0; i < ordered.size(); ++i) {
        const float v = ordered[i];
        assert(std::bit_cast<std::uint32_t>(StillUnkey(StillKey(v))) == std::bit_cast<std::uint32_t>(v));
        if (i + 1 < ordered.size()) {
            assert(StillKey(v) < StillKey(ordered[i + 1]));
        }
        // The least value is kept as the greatest inverted key.
        if (i > 0) {
            assert(~StillKey(v) < ~StillKey(ordered[i - 1]));
        }
    }
    // 0 is below every key and every inverted key of a finite number: a zeroed slot only grows.
    assert(StillKey(-std::numeric_limits<float>::max()) > 0 &&
           ~StillKey(std::numeric_limits<float>::max()) > 0);

    // A slot nothing was written to holds no bounds.
    StillBox box{};
    Sig empty{};
    assert(!DecodeStillSig(empty.data(), box));

    // A mesh on both sides of zero: the bounds are its least and greatest coordinates.
    const std::array<std::array<float, 3>, 5> mesh{{{-0.4f, 0.02f, 3.0f},
                                                    {0.5f, 0.10f, 2.2f},
                                                    {0.1f, -0.03f, 2.9f},
                                                    {-0.1f, 0.0f, 2.5f},
                                                    {0.45f, 0.09f, -0.0f}}};
    const Sig still = Measure(mesh, 0.0f, 0.0f, 0.0f);
    assert(still[6] == 5 && still[7] == 0 && DecodeStillSig(still.data(), box));
    assert(box[0] == -0.4f && box[1] == -0.03f && box[2] == -0.0f && box[3] == 0.5f &&
           box[4] == 0.10f && box[5] == 3.0f);
    // The order of the vertices does not matter (the shader's threads run in any order).
    Sig reversed{};
    for (std::size_t i = mesh.size(); i-- > 0;) {
        StillSigAdd(reversed.data(), mesh[i][0] + 0.0f, mesh[i][1] + 0.0f, mesh[i][2] + 0.0f);
    }
    assert(reversed == still);
    // -0 and +0 are two keys next to each other and the same place.
    Sig minus{}, plus{};
    StillSigAdd(minus.data(), -0.0f, -0.0f, -0.0f);
    StillSigAdd(plus.data(), 0.0f, 0.0f, 0.0f);
    StillBox at_minus{}, at_plus{};
    assert(minus != plus && DecodeStillSig(minus.data(), at_minus) &&
           DecodeStillSig(plus.data(), at_plus) && StillMoved(at_minus, at_plus) == 0.0f);

    // Captured again in the same place: no difference at all. Moved: the size of the move,
    // whichever way.
    StillBox again{}, moved{}, lifted{}, nudged{};
    assert(DecodeStillSig(Measure(mesh, 0.0f, 0.0f, 0.0f).data(), again));
    assert(StillMoved(box, again) == 0.0f);
    assert(DecodeStillSig(Measure(mesh, 0.5f, 0.0f, 0.0f).data(), moved));
    assert(std::abs(StillMoved(box, moved) - 0.5f) < 1e-6f && StillMoved(moved, box) == StillMoved(box, moved));
    assert(DecodeStillSig(Measure(mesh, 0.0f, -1.2f, 0.0f).data(), lifted));
    assert(std::abs(StillMoved(box, lifted) - 1.2f) < 1e-6f);
    // The tolerance: a millimetre is not a move, a centimetre is; a torch built lying on the
    // ground and carried a metre higher is one under the wide tolerance between the passes too.
    assert(DecodeStillSig(Measure(mesh, 0.001f, 0.0f, 0.0f).data(), nudged));
    assert(!(StillMoved(box, nudged) > StillTolerance));
    assert(DecodeStillSig(Measure(mesh, 0.0f, 0.0f, 0.01f).data(), nudged));
    assert(StillMoved(box, nudged) > StillTolerance && !(StillMoved(box, nudged) > StillCrossTolerance));
    assert(StillMoved(box, lifted) > StillCrossTolerance);
    // A caster that only turned in place moved too (its bounds changed).
    StillBox turned = box;
    turned[3] = box[3] - 0.2f;
    assert(StillMoved(box, turned) > StillTolerance);

    // A vertex that is not a finite number is counted and left out, and such a signature is
    // not compared: the caster would seem to move whenever that vertex comes and goes.
    Sig broken = still;
    StillSigAdd(broken.data(), std::numeric_limits<float>::quiet_NaN(), 0.0f, 0.0f);
    StillSigAdd(broken.data(), 0.0f, inf, 0.0f);
    StillSigAdd(broken.data(), 0.0f, 0.0f, -inf);
    assert(broken[6] == 5 && broken[7] == 3 && !DecodeStillSig(broken.data(), box));
    for (std::uint32_t k = 0; k < 6; ++k) {
        assert(broken[k] == still[k]);
    }

    // From clip space to the world. With nothing to undo, the rows are the view to world
    // turn and the origin its place.
    {
        const std::array<float, 16> same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
        const std::array<float, 12> place{1, 0, 0, 10.25f, 0, 1, 0, 1.5f, 0, 0, 1, -3.0f};
        std::array<float, 12> rows{};
        std::array<float, 3> origin{};
        StillClipToWorld(same.data(), place.data(), rows, origin);
        const std::array<float, 4> clip{0.5f, -2.0f, 4.0f, 1.0f};
        const auto p = StillPoint(rows, origin, clip.data());
        assert(origin[0] == 10.25f && origin[1] == 1.5f && origin[2] == -3.0f && rows[3] == 0.0f);
        assert(p[0] == 10.75f && p[1] == -0.5f && p[2] == 1.0f);
    }
    // A mesh that stands still, captured by the camera pass under two poses of the camera (the
    // camera a hundred metres from the world's origin, as in the game; moved and turned between
    // the captures), near and far, for three near planes. Its bounds must come out the same
    // within a fraction of the tolerance, and where the mesh stands; the one product the scene's
    // positions are made with gives bounds that differ by more than the tolerance far away,
    // which read as a move.
    float worst_new = 0.0f, worst_old = 0.0f, worst_place = 0.0f, worst_old_near = 0.0f;
    std::uint32_t old_over = 0, cases = 0, seed = 47;
    const auto random = [&] {
        seed = seed * 1664525u + 1013904223u;
        return double(seed >> 8) / double(1u << 24);
    };
    for (const double near_plane : {0.05, 0.1, 0.3}) {
        for (const double distance : {3.0, 30.0, 60.0, 120.0}) {
            for (int run = 0; run < 12; ++run, ++cases) {
                const std::array<double, 3> at{-22.0 + random(), -107.0 + random(), -26.0 + random()};
                const double yaw = 6.28 * random(), pitch = 0.6 * random() - 0.3;
                const Camera first = MakeCamera(yaw, pitch, at, near_plane);
                const Camera second = MakeCamera(yaw + 0.2, pitch - 0.05,
                                                 {at[0] + 0.3, at[1] + 0.1, at[2] - 0.2}, near_plane);
                // In front of the first camera (it looks along its -z).
                std::array<float, 3> centre{};
                for (int r = 0; r < 3; ++r) {
                    centre[r] = float(at[r] - double(first.view_to_world[r * 4 + 2]) * distance);
                }
                std::array<Sig, 2> sig_new{}, sig_old{};
                StillBox truth{};
                Sig sig_truth{};
                for (int v = 0; v < 200; ++v) {
                    const std::array<float, 3> p{centre[0] + float(2.0 * random() - 1.0),
                                                 centre[1] + float(2.0 * random() - 1.0),
                                                 centre[2] + float(2.0 * random() - 1.0)};
                    StillSigAdd(sig_truth.data(), p[0], p[1], p[2]);
                    const Camera* cameras[2] = {&first, &second};
                    for (int c = 0; c < 2; ++c) {
                        const auto clip = Clip(*cameras[c], p);
                        std::array<float, 12> rows{};
                        std::array<float, 3> origin{};
                        StillClipToWorld(cameras[c]->inverse.data(), cameras[c]->view_to_world.data(),
                                         rows, origin);
                        const auto q = StillPoint(rows, origin, clip.data());
                        StillSigAdd(sig_new[c].data(), q[0], q[1], q[2]);
                        const auto o = OneProduct(*cameras[c], clip);
                        StillSigAdd(sig_old[c].data(), o[0], o[1], o[2]);
                    }
                }
                std::array<StillBox, 2> box_new{}, box_old{};
                assert(DecodeStillSig(sig_truth.data(), truth));
                for (int c = 0; c < 2; ++c) {
                    assert(DecodeStillSig(sig_new[c].data(), box_new[c]));
                    assert(DecodeStillSig(sig_old[c].data(), box_old[c]));
                    worst_place = std::max(worst_place, StillMoved(truth, box_new[c]));
                }
                const float moved_new = StillMoved(box_new[0], box_new[1]);
                const float moved_old = StillMoved(box_old[0], box_old[1]);
                worst_new = std::max(worst_new, moved_new);
                worst_old = std::max(worst_old, moved_old);
                if (distance <= 3.0) {
                    worst_old_near = std::max(worst_old_near, moved_old);
                }
                old_over += moved_old > StillTolerance ? 1 : 0;
            }
        }
    }
    assert(worst_new < StillToleranceLeast / 4 && worst_place < StillToleranceLeast / 4);
    // The fault this guards against is there to be found: without it the test would prove
    // nothing.
    assert(old_over > 0 && worst_old > StillTolerance);

    // The looks: 2 frames after the build, 6 and 24 frames after the look before, then about
    // once a second, spread by the key; four times more rarely for a caster the camera pass does
    // not draw.
    assert(StillNext(0, 0, true) == 2 && StillNext(1, 0, true) == 6 && StillNext(2, 0, true) == 24);
    assert(StillNext(0, 99, false) == 2 && StillNext(2, 99, false) == 24);
    for (std::uint64_t key = 0; key < 200; ++key) {
        const std::uint32_t soon = StillNext(3, key, true), late = StillNext(200, key, false);
        assert(soon >= 64 && soon <= 95 && soon == 64 + key % 32 && late == 4 * soon);
        // More casters due than the budget lets through: a look in turn waits until those
        // now due had theirs, an early look does not.
        assert(StillNext(3, key, true, 10) == soon && StillNext(3, key, true, 500) == 500 + key % 32);
        // bbport (r47c_review-fixes): four times more rarely under a crowd as well
        assert(StillNext(3, key, false, 10) == late && StillNext(3, key, false, 64) == late);
        assert(StillNext(3, key, false, 200) == 4 * (200 + key % 32));
        assert(StillNext(3, key, false, 500) == 4 * (500 + key % 32));
        assert(StillNext(0, key, true, 500) == 2 && StillNext(2, key, true, 500) == 24);
    }
    // The crowd: nothing while a frame's due casters fit the budget; else the frames they
    // need at it, rounded up and bounded. No budget: no looks in turn, nothing to put off.
    assert(StillCrowd(0, 60000) == 0 && StillCrowd(60000, 60000) == 0 && StillCrowd(60001, 60000) == 2);
    assert(StillCrowd(4400000, 60000) == 74 && StillCrowd(1000, 0) == 0);
    assert(StillCrowd(std::uint64_t(1) << 40, 1) == StillCrowdMost);
    // bbport (r47c_review-fixes): the lanes: the early looks have their own; a look in turn
    // goes to the second budget only when it waited long AND the first is used up now.
    static_assert(StillLaneOf(0, true, 999, 64) == 0 && StillLaneOf(2, true, 999, 64) == 1);
    static_assert(StillLaneOf(3, false, 999, 64) == 2 && StillLaneOf(3, true, 63, 64) == 2);
    static_assert(StillLaneOf(3, true, 64, 64) == 3 && StillLaneOf(255, true, 64, 0) == 2);
    // The pool: a caster the camera pass does not draw counts for a quarter; the most a frame
    // drew stays known over the frames that draw less.
    static_assert(StillPoolShare(4000, true) == 4000 && StillPoolShare(4000, false) == 1000 &&
                  StillPoolShare(1, false) == 1 && StillPoolShare(0, false) == 0);
    {
        StillPoolPeak peak;
        std::uint64_t least = ~0ull, most = 0;
        for (std::uint64_t frame = 1; frame <= 400; ++frame) {
            const std::uint64_t last = peak.End(frame % 8 == 0 ? 900 : 500, frame);
            if (frame > 2 * StillPoolFrames) {
                least = std::min(least, last);
                most = std::max(most, last);
            }
        }
        assert(least == 900 && most == 900);
        for (std::uint64_t frame = 401; frame <= 400 + 2 * StillPoolFrames; ++frame) {
            most = peak.End(100, frame);
        }
        assert(most == 100); // and is forgotten once nothing draws that much
    }
    // The pace. 600 casters of 3,700 triangles on average need 28,000 triangles a frame at a
    // look every 80 frames: the budget serves them, both paces are the same and the second
    // budget is not asked for. 2400 need 111,000: with the pace set by the casters due on one
    // frame the first in draw order take the budget again at every period and the last are
    // never looked at; set by all of them, every look comes within a few frames of its turn.
    const std::uint64_t few_due = LongestWait(false, 0, 600, 0);
    const std::uint64_t few_pool = LongestWait(true, StillOverdue, 600, 0);
    const std::uint64_t many_due = LongestWait(false, 0, 2400, 0);
    const std::uint64_t many_pool = LongestWait(true, 0, 2400, 0);
    assert(few_due == few_pool && few_due < 16);
    assert(many_due > 3500 && many_pool < 64);
    // 900 casters drawn on every frame (42,000 triangles a frame) and, after them in draw
    // order, 400 that only every 8th frame draws (37,000 on each of those frames): the budget
    // is not used up on average, but on the frames that draw the 400 the 900 leave too little
    // of it, every time. Without the second budget their looks wait without end, whatever
    // sets the pace; with it they are served within a few of their draws.
    const std::uint64_t rare_none = LongestWait(true, 0, 900, 400);
    const std::uint64_t rare_second = LongestWait(true, StillOverdue, 900, 400);
    assert(rare_none > 3500 && rare_second < 4 * StillOverdue);
    // Two boxes of one size, wherever they stand; a box that grew along one axis is another.
    {
        const StillBox here{1.0f, 2.0f, 3.0f, 2.5f, 2.5f, 7.0f};
        const StillBox there{-51.0f, 2.1f, 30.0f, -49.5f, 2.6f, 34.0f};
        const StillBox wider{-51.0f, 2.1f, 30.0f, -49.5f, 2.6f, 34.02f};
        assert(StillSameSize(here, there, 0.008f) && StillSameSize(there, here, 0.008f));
        assert(!StillSameSize(here, wider, 0.008f) && !StillSameSize(wider, here, 0.008f));
        assert(StillMoved(here, there) > StillCarried);
    }
    // A mesh of more indices than one dispatch of the shader takes is not measured.
    static_assert(StillSigIndicesMost == 4194240 && (StillSigIndicesMost + 63) / 64 == 65535);

    // The knobs.
    assert(ReadStillMode(nullptr) == StillOn && ReadStillMode("on") == StillOn &&
           ReadStillMode("count") == StillCount && ReadStillMode("off") == StillOff &&
           ReadStillMode("") == StillOn && ReadStillMode("Count") == StillOn);
    assert(ReadStillTolerance(nullptr) == StillTolerance && ReadStillTolerance("") == StillTolerance &&
           ReadStillTolerance("x") == StillTolerance && ReadStillTolerance("nan") == StillTolerance &&
           ReadStillTolerance("0.01") == 0.01f && ReadStillTolerance("0") == StillToleranceLeast &&
           ReadStillTolerance("-1") == StillToleranceLeast && ReadStillTolerance("5") == StillToleranceMost);
    assert(StillTolerance > StillToleranceLeast && StillTolerance < StillToleranceMost &&
           StillCrossTolerance > StillToleranceMost);

    // BB_RT_LAMP_LEAVE's classes: (camera, held, shared, instance, moving, card).
    assert(StillLeaveClasses(true, false, false, false, false, false) == 16);  // a wall
    assert(StillLeaveClasses(false, false, false, false, false, false) == 17); // in the sun's pass alone
    assert(StillLeaveClasses(false, true, false, false, false, false) == 19);  // held for a cascade
    assert(StillLeaveClasses(true, false, true, false, true, false) == 4);     // a moving shared copy
    assert(StillLeaveClasses(true, false, false, true, false, false) == 8);    // a prop held for still
    assert(StillLeaveClasses(true, false, false, true, true, false) == 40);    // a prop found moving
    assert(StillLeaveClasses(true, false, false, false, true, false) == 32);   // a body
    assert(StillLeaveClasses(true, false, false, false, false, true) == 80);   // a plant
    std::uint32_t all = 0;
    for (std::uint32_t bits = 0; bits < 64; ++bits) {
        all |= StillLeaveClasses((bits & 1) != 0, (bits & 2) != 0, (bits & 4) != 0, (bits & 8) != 0,
                                 (bits & 16) != 0, (bits & 32) != 0);
    }
    assert(all == StillLeaveMost);

    std::printf("rt still check: ok (a mesh captured again in place differs by %.4f m, moved half "
                "a metre by %.4f m; tolerance %.4f m, %.2f m between the passes; looks %u frames "
                "after a build, %u and %u after the look before, then every %u to %u)\n",
                double(StillMoved(box, again)), double(StillMoved(again, moved)),
                double(StillTolerance), double(StillCrossTolerance), StillNext(0, 0, true),
                StillNext(1, 0, true), StillNext(2, 0, true), StillNext(3, 0, true),
                StillNext(3, 31, true));
    std::printf("rt still check: a still mesh under two poses of the camera, %u cases 3 to 120 m "
                "away: bounds differ by at most %.6f m (and from its true place by %.6f m); with "
                "the scene's one product by up to %.4f m (%.5f m at 3 m), past the tolerance in "
                "%u cases\n",
                cases, double(worst_new), double(worst_place), double(worst_old),
                double(worst_old_near), old_over);
    std::printf("rt still check: looks in turn in draw order at %u triangles a frame, the "
                "longest wait: 600 casters %llu frames; 2400 casters %llu frames with the pace "
                "set by those due on one frame, %llu set by all of them; 900 and 400 drawn "
                "every 8th frame %llu frames without the second budget, %llu with it\n",
                StillBudget, static_cast<unsigned long long>(few_pool),
                static_cast<unsigned long long>(many_due),
                static_cast<unsigned long long>(many_pool),
                static_cast<unsigned long long>(rare_none),
                static_cast<unsigned long long>(rare_second));
    return 0;
}
