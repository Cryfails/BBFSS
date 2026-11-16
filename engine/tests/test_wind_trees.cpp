// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89j_twigs-pick-trees): the tree shape rule, the book, the pick's points, rectangles and winner rule
// (shim/bbport_wind_trees.h).
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include "gpu/shim/bbport_wind_trees.h"

namespace B = BbWindTrees;

static int failures = 0;

static void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

namespace {

struct Rng {
    std::uint32_t s = 12345u;
    float Next() {
        s = s * 1664525u + 1013904223u;
        return static_cast<float>(s >> 8) / 16777216.0f;
    }
};

void Push(std::vector<float>& v, float x, float y, float z) {
    v.push_back(x);
    v.push_back(y);
    v.push_back(z);
}

// A tree: a trunk of radius 0.3 up to 4 m, a crown of radius up to 4 m from 4 m to 10 m (y up).
std::vector<float> Tree() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 200; ++i) {
        const float a = 6.2831853f * r.Next();
        Push(v, 0.3f * std::cos(a), 4.0f * r.Next(), 0.3f * std::sin(a));
    }
    for (int i = 0; i < 400; ++i) {
        const float a = 6.2831853f * r.Next();
        const float rad = 4.0f * std::sqrt(r.Next());
        Push(v, rad * std::cos(a), 4.0f + 6.0f * r.Next(), rad * std::sin(a));
    }
    return v;
}

// A wall 20 m wide, 10 m high, half a metre thick.
std::vector<float> Wall() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 600; ++i) {
        Push(v, 20.0f * r.Next(), 10.0f * r.Next(), 0.5f * r.Next());
    }
    return v;
}

// A column of radius 1, 10 m high.
std::vector<float> Column() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 600; ++i) {
        const float a = 6.2831853f * r.Next();
        Push(v, std::cos(a), 10.0f * r.Next(), std::sin(a));
    }
    return v;
}

// A cone: wide at the foot (radius 5), a point at 10 m.
std::vector<float> Cone() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 600; ++i) {
        const float u = r.Next();
        const float a = 6.2831853f * r.Next();
        const float rad = 5.0f * (1.0f - u);
        Push(v, rad * std::cos(a), 10.0f * u, rad * std::sin(a));
    }
    return v;
}

// A hall: a wide base block (radius 8, to 3 m) with a tower (radius 2) from 3 to 12 m.
std::vector<float> Hall() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 300; ++i) {
        const float a = 6.2831853f * r.Next();
        const float rad = 8.0f * std::sqrt(r.Next());
        Push(v, rad * std::cos(a), 3.0f * r.Next(), rad * std::sin(a));
    }
    for (int i = 0; i < 300; ++i) {
        const float a = 6.2831853f * r.Next();
        const float rad = 2.0f * std::sqrt(r.Next());
        Push(v, rad * std::cos(a), 3.0f + 9.0f * r.Next(), rad * std::sin(a));
    }
    return v;
}

// A lamp post: a thin post to 4 m, a head of radius 0.5 above it (5 m in all).
std::vector<float> Lamp() {
    Rng r;
    std::vector<float> v;
    for (int i = 0; i < 300; ++i) {
        const float a = 6.2831853f * r.Next();
        Push(v, 0.1f * std::cos(a), 4.0f * r.Next(), 0.1f * std::sin(a));
    }
    for (int i = 0; i < 300; ++i) {
        const float a = 6.2831853f * r.Next();
        const float rad = 0.5f * std::sqrt(r.Next());
        Push(v, rad * std::cos(a), 4.0f + r.Next(), rad * std::sin(a));
    }
    return v;
}

// A tree with z as up: the tree's x, y, z permuted so that its height is the third number.
std::vector<float> TreeZUp() {
    std::vector<float> v = Tree();
    for (std::size_t i = 0; i + 2 < v.size(); i += 3) {
        std::swap(v[i + 1], v[i + 2]);
    }
    return v;
}

} // namespace

int main() {
    // The shape rule.
    {
        const std::vector<float> t = Tree();
        const B::Shape s = B::ShapeOf(t.data(), t.size() / 3);
        Expect(s.tree && s.up == 1 && s.why == nullptr, "the tree is tree-shaped with y up");
        Expect(s.height > 9.0f && s.height < 10.1f && s.trunk < 0.5f && s.crown > 3.0f, "its measures");
        const std::vector<float> z = TreeZUp();
        const B::Shape sz = B::ShapeOf(z.data(), z.size() / 3);
        Expect(sz.tree && sz.up == 2, "the same tree with z up is read with z up");
        const std::vector<float> w = Wall();
        Expect(!B::ShapeOf(w.data(), w.size() / 3).tree, "a wall is not a tree");
        const std::vector<float> c = Column();
        Expect(!B::ShapeOf(c.data(), c.size() / 3).tree, "a column is not a tree");
        const std::vector<float> k = Cone();
        Expect(!B::ShapeOf(k.data(), k.size() / 3).tree, "a cone is not a tree");
        const std::vector<float> h = Hall();
        Expect(!B::ShapeOf(h.data(), h.size() / 3).tree, "a hall with a tower is not a tree");
        const std::vector<float> lamp = Lamp();
        Expect(!B::ShapeOf(lamp.data(), lamp.size() / 3).tree, "a lamp post with a head is not a tree");
        Expect(!B::ShapeOf(nullptr, 100).tree && std::strcmp(B::ShapeOf(nullptr, 100).why, "few") == 0, "no vertices");
        Expect(!B::ShapeOf(t.data(), 10).tree, "ten vertices are too few");
        const std::vector<float> flat(300, 1.0f); // all one point
        Expect(!B::ShapeOf(flat.data(), 100).tree, "a point is no tree");
    }

    // Percentile.
    {
        std::vector<float> v{5, 1, 4, 2, 3};
        Expect(B::Percentile(v, 0.0f) == 1.0f, "percentile 0");
        std::vector<float> w{5, 1, 4, 2, 3};
        Expect(B::Percentile(w, 0.99f) == 5.0f, "percentile 0.99");
    }

    // The book: a verdict is found, forgotten after RecheckFrames, the book is bounded.
    {
        B::Book book;
        B::Mesh m;
        m.tree = true;
        m.at = 100;
        const std::uint64_t key = B::MeshKey(0x1000, 5, 0x2000, 300);
        Expect(book.Find(key, 100) == nullptr, "an unknown key");
        book.Put(key, m);
        Expect(book.Find(key, 200) != nullptr && book.Find(key, 200)->tree, "a known key");
        Expect(book.Find(key, 100 + B::RecheckFrames) != nullptr, "still known at the limit");
        Expect(book.Find(key, 101 + B::RecheckFrames) == nullptr, "made again after RecheckFrames");
        Expect(book.Any(key) != nullptr && book.Any(key + 1) == nullptr, "an old verdict is still held (JudgeMost)");
        Expect(book.Trees() == 1 && book.Size() == 1, "counts");
        Expect(B::MeshKey(0x1000, 5, 0x2000, 300) != B::MeshKey(0x1000, 6, 0x2000, 300) &&
                   B::MeshKey(0x1000, 5, 0x2000, 300) != B::MeshKey(0x1008, 5, 0x2000, 300) &&
                   B::MeshKey(0x1000, 5, 0x2000, 300) != B::MeshKey(0x1000, 5, 0x2004, 300) &&
                   B::MeshKey(0x1000, 5, 0x2000, 300) != B::MeshKey(0x1000, 5, 0x2000, 301),
               "the key follows every part of the draw");
        for (std::uint64_t i = 0; i < B::BookMost + 5; ++i) {
            book.Put(i + 1, m);
        }
        Expect(book.Size() <= B::BookMost, "the book is bounded");
    }

    // The log lines stay under 700 characters.
    {
        B::Stats s;
        s.draws = s.taken = s.refused = s.indoors = s.unread = s.new_meshes = s.tree_meshes = s.refused_meshes =
            s.limbs = s.limb_new = s.limb_refused = std::numeric_limits<std::uint64_t>::max();
        B::Book book;
        char text[720];
        B::LineText(s, book, 600, 4000000000u, 4000000000u, text, sizeof(text));
        Expect(std::strlen(text) < 700 && std::strstr(text, "Wind twigs trees (r89j)") != nullptr, "the line");
        B::OnceText(text, sizeof(text));
        Expect(std::strlen(text) < 720 && std::strstr(text, "BB_WIND_TWIGS_TREES=1") != nullptr, "the once line");
        B::Mesh m;
        m.verts = 4000000000u;
        m.addr = 0x7fffffffffffull;
        m.why = "no-spread";
        B::MeshText(m, 0x7fffffffffffull, text, sizeof(text));
        Expect(std::strlen(text) < 700 && std::strstr(text, "model height") != nullptr, "the mesh line");
        // no BB_WIND_TWIGS_TREES in the test's environment: off
        Expect(!B::On(), "off by default");
    }

    // The pick's points.
    {
        B::Point p[8];
        Expect(B::ParsePoints(nullptr, p, 8) == 0, "no text");
        Expect(B::ParsePoints("", p, 8) == 0, "empty");
        Expect(B::ParsePoints("1180,60;1010,110", p, 8) == 2 && p[0].x == 1180 && p[0].y == 60 && p[1].x == 1010 &&
                   p[1].y == 110,
               "two points");
        Expect(B::ParsePoints(" 300 , 95 ; x,2 ; 480,140;7", p, 8) == 2 && p[0].x == 300 && p[1].y == 140,
               "spaces and bad items");
        Expect(B::ParsePoints("-1,5;5,-1;99999,5;3,4", p, 8) == 1 && p[0].x == 3, "out of range items are skipped");
        Expect(B::ParsePoints("1,1;2,2;3,3", p, 2) == 2, "at most max");
        Expect(B::ParsePoints("5,6;;7,8", p, 8) == 2 && p[1].x == 7, "an empty item");
        Expect(B::ParsePoints("1180:60;1010:110", p, 8) == 2 && p[1].x == 1010 && p[1].y == 110, "a colon as the separator");
        const B::PickKnob d = B::ParsePick(nullptr, nullptr, nullptr);
        Expect(d.count == 0 && d.out_w == 1280 && d.out_h == 720 && d.start == B::PickFrameDefault, "pick defaults");
        const B::PickKnob k = B::ParsePick("10,20", "1920x1080", "300");
        Expect(k.count == 1 && k.out_w == 1920 && k.out_h == 1080 && k.start == 300, "pick knobs");
        const B::PickKnob bad = B::ParsePick("10,20", "wide", "soon");
        Expect(bad.out_w == 1280 && bad.start == B::PickFrameDefault, "unreadable size and frame: defaults");
        Expect(B::ParsePick("1,1", "4x4", nullptr).out_w == 1280, "a size under 16 is refused");
        Expect(!B::PickOn(), "no pick without the knob in the test's environment");
    }

    // The frames of the pick.
    {
        Expect(B::PointAt(899, 900, 3) == -1 && B::PointAt(900, 900, 3) == 0 && B::PointAt(901, 900, 3) == 0 &&
                   B::PointAt(902, 900, 3) == 1 && B::PointAt(905, 900, 3) == 2 && B::PointAt(906, 900, 3) == -1,
               "two frames a point, then nothing");
        // bbport (r89k_twigs-opaque-word): the sweep starts again every `repeat` frames
        Expect(B::PointAt(906, 900, 3, 10) == -1 && B::PointAt(910, 900, 3, 10) == 0 && B::PointAt(912, 900, 3, 10) == 1 &&
                   B::PointAt(914, 900, 3, 10) == 2 && B::PointAt(917, 900, 3, 10) == -1 && B::PointAt(899, 900, 3, 10) == -1,
               "a repeating sweep");
        const B::PickKnob again = B::ParsePick("1,1;2,2;3,3", nullptr, nullptr, "40");
        Expect(again.repeat == 40, "the repeat knob");
        Expect(B::ParsePick("1,1;2,2;3,3", nullptr, nullptr, "5").repeat == 0, "a repeat shorter than the sweep is refused");
        Expect(B::ParsePick("1,1", nullptr, nullptr, nullptr).repeat == 0 && B::ParsePick("1,1", nullptr, nullptr, "soon").repeat == 0,
               "no repeat unless asked");
    }

    // The patch.
    {
        const B::Point p{640, 360};
        const B::Rect r = B::PickRect(p, 1280, 720, 1280, 720);
        Expect(r.cx == 640 && r.cy == 360 && r.x == 638 && r.y == 358 && r.w == 5 && r.h == 5, "the same size (a 5x5 patch)");
        const B::Rect half = B::PickRect(p, 1280, 720, 640, 360);
        Expect(half.cx == 320 && half.cy == 180 && half.w == 5, "a render target of half the size");
        const B::Rect corner = B::PickRect({0, 0}, 1280, 720, 1280, 720);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 3 && corner.h == 3, "the corner is cut");
        const B::Rect outside = B::PickRect({5000, 5000}, 1280, 720, 1280, 720);
        Expect(outside.cx == 1279 && outside.cy == 719 && outside.w == 3 && outside.h == 3, "outside: the last pixel");
        const B::Rect none = B::PickRect(p, 0, 720, 1280, 720);
        Expect(none.w == 0 && none.h == 0, "no picture size: no patch");
    }

    // The winner.
    {
        std::vector<B::PickDraw> draws(6);
        for (std::size_t i = 0; i < draws.size(); ++i) {
            draws[i].depth_write = true;
            draws[i].vs = static_cast<std::uint32_t>(i);
        }
        draws[4].depth_write = false;
        const std::uint64_t counts[6] = {0, 7, 0, 3, 9, 0};
        const B::PickResult r = B::PickWinner(draws, counts);
        Expect(r.found && r.row == 3, "the last draw with samples that writes depth wins");
        Expect(r.passed == 3, "draws with samples");
        Expect(r.under_n == 1 && r.under[0] == 1, "earlier draws that passed");
        const std::uint64_t none[6] = {0, 0, 0, 0, 0, 0};
        Expect(!B::PickWinner(draws, none).found, "no draw passed");
        const std::uint64_t only_nowrite[6] = {0, 0, 0, 0, 5, 0};
        const B::PickResult nw = B::PickWinner(draws, only_nowrite);
        Expect(!nw.found && nw.passed == 1, "a draw without depth write does not win");
        char text[720];
        B::PickDraw d;
        d.vs = 0x9da6aacb;
        d.ps = 0xbb10e440;
        d.cutout = false;
        d.kind = 1;
        d.stream_verts = 156641;
        d.stride = 16;
        d.indices = 4294967295u;
        d.first = 4294967295u;
        d.base = std::numeric_limits<std::int32_t>::min();
        B::PickLine({16384, 16384}, B::PickRect({10, 10}, 1280, 720, 1280, 720), 99999, 99999, 99999, d, false,
                    "scene box y 1.0..12.0 m, over the camera -1.0..10.0 m, 7.0 x 6.0 m wide",
                    "twig book: Tree (height 12.0 m)", text, sizeof(text));
        Expect(std::strlen(text) < 700 && std::strstr(text, "vs:ps 9da6aacb:bb10e440") != nullptr &&
                   std::strstr(text, "opaque, GPU palette, sway bit no, sway word no") != nullptr,
               "the pick line");
        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, 0, text, sizeof(text));
        Expect(std::strstr(text, "no G-buffer draw of 12 wrote depth there") != nullptr &&
                   std::strstr(text, " 0 of them had samples") != nullptr && std::strstr(text, "missed every draw") != nullptr,
               "the none line");
        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, 3, text, sizeof(text));
        Expect(std::strstr(text, " 3 of them had samples") != nullptr && std::strstr(text, "none with depth write") != nullptr,
               "the none line with samples");
        {
            const float cam[3] = {-51.3f, -39.0f, 71.3f};
            B::PickNoteLine({1180, 60}, B::PickRect({1180, 60}, 1280, 720, 1280, 720), 1280, 720, 600, true, cam, 400, 104,
                            504, text, sizeof(text));
            Expect(std::strstr(text, "pixel 1180,60: frame 600, camera -51.3 -39.0 71.3, picture 1280x720") != nullptr &&
                       std::strstr(text, "patch x 1178..1182 y 58..62 (5x5, centre 1180,60)") != nullptr &&
                       std::strstr(text, "met the patch 400, that did not 104, draws with a query 504") != nullptr,
                   "the note line");
            B::PickNoteLine({16384, 16384}, B::PickRect({10, 10}, 1280, 720, 1280, 720), 16384, 16384,
                            std::numeric_limits<std::uint64_t>::max(), false, nullptr,
                            std::numeric_limits<std::uint32_t>::max(), std::numeric_limits<std::uint32_t>::max(), 99999, text,
                            sizeof(text));
            Expect(std::strlen(text) < 700 && std::strstr(text, "camera unread") != nullptr, "the note line is short and says unread");
        }
        B::PickOnceText(B::ParsePick("1,2;3,4", nullptr, nullptr), text, sizeof(text));
        Expect(std::strstr(text, "2 pixel(s) of a 1280x720 picture, from frame 900 on, 2 frames a pixel") != nullptr &&
                   std::strlen(text) < 720,
               "the once line of the pick");
    }

    // bbport (r89k_twigs-opaque-word): the limb rule, the winner's fallback, the world box's height for a limb piece.
    {
        Rng r;
        // A branchy mesh: a trunk and 30 limbs from 3 to 6 m up (y up), each a line of vertices.
        std::vector<float> branchy;
        for (int i = 0; i < 60; ++i) {
            Push(branchy, 0.1f * (r.Next() - 0.5f), 6.0f * r.Next(), 0.1f * (r.Next() - 0.5f));
        }
        for (int b = 0; b < 30; ++b) {
            const float h0 = 3.0f + 3.0f * r.Next();
            const float a = 6.2831853f * r.Next();
            const float len = 2.0f + 4.0f * r.Next();
            for (int k = 0; k < 40; ++k) {
                const float t = len * r.Next();
                Push(branchy, 0.8f * std::cos(a) * t + 0.05f * (r.Next() - 0.5f), h0 + 0.5f * t + 0.05f * (r.Next() - 0.5f),
                     0.8f * std::sin(a) * t + 0.05f * (r.Next() - 0.5f));
            }
        }
        const B::Limb lb = B::LimbOf(branchy.data(), branchy.size() / 3);
        Expect(lb.ok && lb.why == nullptr && lb.boxy < 0.05f && lb.flat > 0.5f, "branches are a limb piece");
        // A building: a shell, every vertex on one of the six faces of a 10 x 8 x 6 box.
        std::vector<float> shell;
        for (int i = 0; i < 600; ++i) {
            const float u = r.Next(), w = r.Next();
            switch (i % 6) {
            case 0: Push(shell, 0.0f, 8.0f * u, 6.0f * w); break;
            case 1: Push(shell, 10.0f, 8.0f * u, 6.0f * w); break;
            case 2: Push(shell, 10.0f * u, 0.0f, 6.0f * w); break;
            case 3: Push(shell, 10.0f * u, 8.0f, 6.0f * w); break;
            case 4: Push(shell, 10.0f * u, 8.0f * w, 0.0f); break;
            default: Push(shell, 10.0f * u, 8.0f * w, 6.0f); break;
            }
        }
        const B::Limb ls = B::LimbOf(shell.data(), shell.size() / 3);
        Expect(!ls.ok && std::strcmp(ls.why, "boxy") == 0 && ls.boxy > 0.9f, "a shell is boxy");
        std::vector<float> slab; // a facade: 12 x 8 m, 0.1 m thick
        for (int i = 0; i < 600; ++i) {
            Push(slab, 12.0f * r.Next(), 8.0f * r.Next(), 0.1f * r.Next());
        }
        Expect(std::strcmp(B::LimbOf(slab.data(), slab.size() / 3).why, "flat") == 0, "a slab is flat");
        std::vector<float> post; // a pole: 0.4 x 10 x 0.4
        for (int i = 0; i < 600; ++i) {
            Push(post, 0.4f * r.Next(), 10.0f * r.Next(), 0.4f * r.Next());
        }
        Expect(std::strcmp(B::LimbOf(post.data(), post.size() / 3).why, "flat") == 0, "a pole is flat");
        Expect(std::strcmp(B::LimbOf(branchy.data(), 10).why, "few") == 0 && std::strcmp(B::LimbOf(nullptr, 100).why, "few") == 0,
               "few vertices");
        const std::vector<float> dot(300, 1.0f);
        Expect(std::strcmp(B::LimbOf(dot.data(), 100).why, "point") == 0, "all one point");
        const B::Limb strict = B::LimbOf(branchy.data(), branchy.size() / 3, 0.0f);
        Expect(strict.ok == (strict.boxy <= 0.0f), "a zero allowance refuses any vertex on a face");
        Expect(!B::LimbOn() && B::LimbBoxyMax() == B::LimbBoxyDefault, "limbs off without BB_WIND_TWIGS_TREES in the test's environment");

        // The world box: a limb piece may be 3 m tall, a tree 4 m.
        BbWindTwigs::Measure m;
        m.ok = true;
        m.base = 0.0f;
        m.crown = 3.5f;
        m.x_lo = 0.0f;
        m.x_hi = 2.0f;
        m.z_lo = 0.0f;
        m.z_hi = 2.0f;
        Expect(std::strcmp(BbWindTwigs::SmallWhy(m, 0.0f, 1, true), "short") == 0, "3.5 m is short for a tree");
        Expect(BbWindTwigs::SmallWhy(m, 0.0f, 1, true, BbWindTwigs::LimbMinH) == nullptr, "3.5 m is tall enough for a limb piece");
        m.crown = 2.5f;
        Expect(std::strcmp(BbWindTwigs::SmallWhy(m, 0.0f, 1, true, BbWindTwigs::LimbMinH), "short") == 0, "2.5 m is short for a limb piece");
        static_assert(BbWindTwigs::LimbMinH > BbWindSway::TreeLo && BbWindTwigs::LimbMinH < BbWindTwigs::SmallMinH,
                      "a limb piece is taller than the lean's tree weight starts and shorter than a tree");
        BbWindTwigs::Entry e;
        Expect(!e.limb, "an entry is no limb piece at first");

        // The winner's fallback: the last draw with samples although it wrote no depth.
        std::vector<B::PickDraw> draws(4);
        for (std::size_t i = 0; i < draws.size(); ++i) {
            draws[i].depth_write = i != 2;
        }
        const std::uint64_t only_no_depth[4] = {0, 0, 5, 0};
        const B::PickResult nw = B::PickWinner(draws, only_no_depth);
        Expect(!nw.found && nw.any && nw.any_row == 2 && nw.passed == 1, "no winner, the fallback names the draw with samples");
        const std::uint64_t mixed[4] = {2, 0, 7, 0};
        const B::PickResult mx = B::PickWinner(draws, mixed);
        Expect(mx.found && mx.row == 0 && mx.any && mx.any_row == 2 && mx.under_n == 0, "a winner and the last draw with samples");
        const std::uint64_t nothing[4] = {0, 0, 0, 0};
        Expect(!B::PickWinner(draws, nothing).any, "nothing passed: no fallback");

        // The log lines name limb pieces.
        char text[720];
        B::Mesh limb;
        limb.limb = true;
        limb.boxy = 0.012f;
        limb.limb_why = "ok";
        limb.why = "no-spread";
        limb.verts = 2043;
        B::MeshText(limb, 0x1087992290ull, text, sizeof(text));
        Expect(std::strstr(text, "LIMB PIECE") != nullptr && std::strstr(text, "shape why no-spread") != nullptr &&
                   std::strstr(text, "limb rule: ok, boxy 0.012") != nullptr,
               "the mesh line of a limb piece");
        B::Mesh refused;
        refused.why = "stout";
        refused.limb_why = "boxy";
        refused.boxy = 0.62f;
        B::MeshText(refused, 0x1087992290ull, text, sizeof(text));
        Expect(std::strstr(text, "refused") != nullptr && std::strstr(text, "limb rule: boxy, boxy 0.620") != nullptr,
               "the mesh line of a piece the limb rule refused");
        B::Mesh plain;
        plain.why = "no-spread";
        B::MeshText(plain, 1, text, sizeof(text));
        Expect(std::strstr(text, "limb rule") == nullptr, "no limb text when the limb rule was not tried");
    }

    // bbport (r89l_twigs-palette-move): the pick's patch in raster pixels, the trees' gain, the offset counters' texts.
    {
        const B::Rect game = B::PickRect({480, 140}, 1280, 720, 1280, 720);
        const B::RasterRect same = B::PickRectRaster(game, 1.0f, 1.0f, 0.0f, 0.0f);
        Expect(same.x == game.x && same.y == game.y && same.w == game.w && same.h == game.h, "scale 1: the patch is as it was");
        const B::RasterRect half = B::PickRectRaster(game, 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(half.w == 5 && half.h == 5 && half.x == 240 - 2 && half.y == 70 - 2, "a half-size raster: a 5x5 patch at half the coordinates");
        const B::Rect east_pixel = B::PickRect({1180, 60}, 1280, 720, 1280, 720);
        const B::RasterRect right = B::PickRectRaster(east_pixel, 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(right.x == 590 - 2 && right.y == 30 - 2 && right.x + right.w <= 640, "a right-hand pixel lies inside a 640 wide raster");
        const B::RasterRect shifted = B::PickRectRaster(game, 0.5f, 0.5f, 10.0f, 4.0f);
        Expect(shifted.x == half.x + 10 && shifted.y == half.y + 4, "the target offset is added");
        const B::RasterRect corner = B::PickRectRaster(B::PickRect({0, 0}, 1280, 720, 1280, 720), 0.5f, 0.5f, 0.0f, 0.0f);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 3 && corner.h == 3, "the corner is cut at 0");
        Expect(B::PickRectRaster(B::Rect{}, 0.5f, 0.5f, 0.0f, 0.0f).w == 0 && B::PickRectRaster(game, 0.0f, 0.5f, 0.0f, 0.0f).w == 0 &&
                   B::PickRectRaster(game, std::numeric_limits<float>::quiet_NaN(), 0.5f, 0.0f, 0.0f).w == 0,
               "no patch for an empty rect or a scale that is 0 or not a number");
        char text[512];
        B::PickRasterText(1280, 720, 1280, 720, 0.5f, 0.5f, 0.0f, 0.0f, half.x, half.y, half.w, half.h, text, sizeof(text));
        Expect(std::strstr(text, "1280x720 picture, scaled to the game targets 1280x720 and then to the raster 640x360") != nullptr &&
                   std::strstr(text, "target scale 0.500 x 0.500") != nullptr,
               "the scaling line");

        Expect(B::GainRamp(255, 0.5f) == 128 && B::GainRamp(255, 1.0f) == 255 && B::GainRamp(255, 0.0f) == 0 && B::GainRamp(0, 0.5f) == 0 &&
                   B::GainRamp(1, 0.1f) == 1 && B::GainRamp(100, 2.0f) == 100 &&
                   B::GainRamp(255, std::numeric_limits<float>::quiet_NaN()) == 0 && B::GainRamp(300, 1.0f) == 255,
               "the gain on a ramp byte");
        Expect(B::TreesGainDefault == 1.0f && B::TreesGain() >= 0.0f && B::TreesGain() <= 1.0f, "the trees' gain is a share");
        // bbport (r89o_wind-chains-twigs-visible): the size rule (BB_WIND_TWIGS_MIN_MODEL unset in the test's environment: 3 units)
        Expect(B::ModelMinDefault == 3.0f && B::LimbExtra == 1.0f && B::ModelMin() == 3.0f, "the size rule's constants");
        Expect(B::SizeOk(8.0f, false) && B::SizeOk(3.37f, false) && B::SizeOk(3.0f, false) && !B::SizeOk(2.48f, false) &&
                   !B::SizeOk(2.48f, true) && !B::SizeOk(3.5f, true) && B::SizeOk(4.0f, true) && B::SizeOk(7.25f, true) &&
                   !B::SizeOk(std::numeric_limits<float>::quiet_NaN(), false) && !B::SizeOk(0.0f, false),
               "a tree needs 3 model units, a limb piece 4: the chain-like piece of 2.48 is refused, the log's smallest tree (3.37) is kept");
        {
            B::Stats sz;
            sz.too_small = 123;
            char sz_text[320];
            B::SizeLineText(sz, sz_text, sizeof(sz_text));
            Expect(std::strstr(sz_text, "r89o") != nullptr && std::strstr(sz_text, "123") != nullptr && std::strlen(sz_text) < 300,
                   "the size rule's line");
        }

        namespace T = BbWindTwigs;
        static_assert(T::OffsetSlotWords == 16 && T::OffsetEnd == T::OffsetAt + BbWindSway::BaseSlots * 16, "the offset block");
        Expect(T::PassBit == (1u << 24) && T::KnownVersion(2011 + 20 + T::OffsetAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + T::OffsetAdd, 11, 21, 1000) && !T::KnownVersion(2011 + 250, 11, 21, 1000),
               "the offset shaders' version is known");
        std::vector<std::uint32_t> words(T::OffsetEnd, 0u);
        const std::uint32_t slot = 7;
        std::uint32_t* const at = words.data() + T::OffsetAt + slot * T::OffsetSlotWords;
        at[0] = 100;
        at[1] = 250;  // 25.0 cm in all over 100 runs: mean 0.25 cm... (mm)
        at[2] = 40;
        at[3] = 20;
        at[4] = 3;
        at[5] = 1;
        const float big = 0.12f;
        std::memcpy(&at[6], &big, sizeof(float));
        at[T::OffsetSetWords + 0] = 600;
        at[T::OffsetSetWords + 1] = 3000;
        at[T::OffsetSetWords + 2] = 500;
        at[T::OffsetSetWords + 3] = 300;
        at[T::OffsetSetWords + 4] = 40;
        at[T::OffsetSetWords + 5] = 9;
        const float big_gbuffer = 0.31f;
        std::memcpy(&at[T::OffsetSetWords + 6], &big_gbuffer, sizeof(float));
        const T::OffsetCounts counts = T::ReadOffset(words.data(), slot);
        Expect(counts.pass[0].verts == 100 && counts.pass[1].verts == 600 && counts.pass[1].over_5cm == 40 &&
                   std::fabs(counts.pass[1].move_max - 0.31f) < 1.0e-6f && std::fabs(counts.pass[0].move_max - 0.12f) < 1.0e-6f,
               "the offset counters are read by set");
        Expect(T::ReadOffset(words.data(), 5000).pass[1].verts == 0 && T::ReadOffset(nullptr, 1).pass[0].verts == 0,
               "a slot out of range or no words reads as 0");
        T::OffsetTotals pal;
        pal.Add(600, 590, counts, 0x7620368bu, 1);
        pal.Add(200, 0, counts, 0x7620368bu, 1);
        pal.Add(10, 10, T::OffsetCounts{}, 0x9da6aacbu, 2);
        Expect(pal.meshes == 3 && pal.draws == 810 && pal.gbuffer_draws == 600 && pal.vs_n == 2 && pal.pass[1].verts == 1200 &&
                   std::fabs(pal.pass[1].move_max - 0.31f) < 1.0e-6f,
               "the totals add meshes, draws, sets and name each vertex shader once");
        char line[1400];
        T::OffsetLine(pal, T::OffsetTotals{}, line, sizeof(line));
        Expect(std::strstr(line, "twig offset in palette path: 810 draws (600 in the G-buffer), 3 meshes, mean ") != nullptr &&
                   std::strstr(line, "max 31.00 cm") != nullptr && std::strstr(line, "vs 7620368b lifted") != nullptr &&
                   std::strstr(line, "vs 9da6aacb RECOMPILED (no counters, no tint)") != nullptr && std::strlen(line) < 1400,
               "the offset line names draws, mean, max and the shader paths");
        T::ClearOffset(words.data(), slot);
        Expect(T::ReadOffset(words.data(), slot).pass[1].verts == 0 && at[T::OffsetSetWords + 6] == 0, "the offset counters are cleared");
        T::NoteShaderPath(0x1234u, true);
        T::NoteShaderPath(0x1234u, false);
        T::NoteShaderPath(0x5678u, true);
        Expect(T::ShaderPathOf(0x1234u) == 3 && T::ShaderPathOf(0x5678u) == 1 && T::ShaderPathOf(0x9999u) == 0, "the shader path note");
        char once[704];
        T::OffsetOnceText(once, sizeof(once));
        Expect(std::strstr(once, "Wind twigs offset") != nullptr && std::strlen(once) < 700, "the once line");
    }

    // bbport (r89m_twigs-no-tear): the soft cap, the largest move, the one-tree box, the shader version.
    {
        namespace T = BbWindTwigs;
        namespace S = BbWindSway;
        Expect(S::TwigSoftCap(0.0f) == 0.0f && S::TwigSoftCap(-0.0f) == 0.0f, "the cap leaves 0 at 0");
        // bbport (r89n_twigs-visible): the boosted cap: w / (1 / TwigBoost + |w| / TwigCap)
        Expect(std::fabs(S::TwigSoftCap(0.05f) - 0.05f / (1.0f / S::TwigBoost + 0.05f / S::TwigCap)) < 1.0e-6f &&
                   S::TwigSoftCap(0.01f) > 0.04f && S::TwigSoftCap(0.05f) > 0.2f,
               "a small weight is boosted (about x6)");
        bool monotone = true, under_cap = true, slow = true;
        float previous = 0.0f;
        for (int i = 1; i <= 4000; ++i) {
            const float x = 0.005f * static_cast<float>(i);
            const float y = S::TwigSoftCap(x);
            monotone = monotone && y >= previous;
            under_cap = under_cap && y < S::TwigCap + 1.0e-6f;
            slow = slow && (y - previous) <= S::TwigBoost * 0.005f + 1.0e-6f; // slope at most TwigBoost
            previous = y;
        }
        Expect(monotone && under_cap && slow, "the cap is monotone, below the cap, slope at most TwigBoost");
        Expect(S::TwigSoftCap(4.5f) > 1.2f && S::TwigSoftCap(4.5f) < S::TwigCap && S::TwigSoftCap(1.0e9f) < S::TwigCap + 1.0e-6f,
               "r89l's weight of 4.5 gives under the cap");
        // bbport (r89o_wind-chains-twigs-visible): TwigBoost 10, TwigCap 1.5
        Expect(std::fabs(S::TwigSoftCap(0.15f) - 0.75f) < 0.02f && std::fabs(S::TwigSoftCap(0.6f) - 1.20f) < 0.02f &&
                   std::fabs(S::TwigSoftCap(0.3f) - 1.00f) < 0.02f,
               "a typical limb piece's raw weight 0.15 gives y 0.75, 0.3 gives 1.0, 0.6 gives 1.2");
        const double most = static_cast<double>(S::TwigCap) *
                            (std::hypot(static_cast<double>(S::MaxAlong), static_cast<double>(S::MaxCross)) +
                             1.4143 * static_cast<double>(S::MaxLeaf));
        Expect(most > 0.70 && most < 0.90, "the hard bound of the largest move is 70 to 90 cm");
        Expect(most * static_cast<double>(S::TwigCapProofMul) < 0.90, "the proof's largest move stays under 90 cm");
        // a tip in a full gust front at 4 m/s (bend D = BendMax at BB_WIND_SWAY 1, push rule: D x (TwigRest + TwigPush)): the
        // typical tip 17 cm, the largest 42 cm; at 1.5 m/s the bend is (1.5 / 4)^2 of that: a few cm
        const double crest4 = static_cast<double>(S::BendMax) * static_cast<double>(S::TwigRest + S::TwigPush);
        const double crest15 = crest4 * (1.5 / 4.0) * (1.5 / 4.0);
        Expect(static_cast<double>(S::TwigSoftCap(0.15f)) * crest4 > 0.10 && static_cast<double>(S::TwigSoftCap(0.15f)) * crest4 < 0.30 &&
                   static_cast<double>(S::TwigCap) * crest4 > 0.30 && static_cast<double>(S::TwigCap) * crest4 < 0.50,
               "a typical tip moves 10-30 cm in a full gust front at 4 m/s, the largest 30-50 cm");
        Expect(static_cast<double>(S::TwigCap) * crest15 < 0.07 && static_cast<double>(S::TwigSoftCap(0.15f)) * crest15 < 0.04 &&
                   static_cast<double>(S::TwigSoftCap(0.15f)) * static_cast<double>(S::BendMax) * (1.5 / 4.0) * (1.5 / 4.0) *
                           static_cast<double>(S::TwigRest) < 0.01,
               "at 1.5 m/s a tip moves under 4 cm in a gust front and under 1 cm between gusts: almost still");
        S::TwigIn in;
        Expect(!in.cap, "the C++ twin's cap is off in a default TwigIn");

        const auto meas = [](float base, float crown, float x0, float x1, float z0, float z1) {
            T::Measure m;
            m.base = base;
            m.crown = crown;
            m.x_lo = x0;
            m.x_hi = x1;
            m.z_lo = z0;
            m.z_hi = z1;
            m.ok = true;
            return m;
        };
        const char* const many = T::SmallWhy(meas(0, 20, 0, 35, 0, 20), 0.0f, 1, false);
        Expect(many != nullptr && std::strcmp(many, "box-many") == 0, "a 35 x 20 m box of a 20 m mesh is several trees");
        Expect(T::SmallWhy(meas(0, 20, 0, 28, 0, 20), 0.0f, 1, false) == nullptr, "a 28 x 20 m box of a 20 m mesh is one tree");
        Expect(T::SmallWhy(meas(0, 20, 0, 35, 0, 20), 0.0f, 1, true) == nullptr, "the loose rule keeps no box rule");
        const char* const wide = T::SmallWhy(meas(0, 12, 0, 40, 0, 20), 0.0f, 1, false);
        Expect(wide != nullptr && std::strcmp(wide, "wide") == 0, "the shape reasons still come first");
        Expect(T::OneTreeBox == 30.0f && T::FixAdd == 4000u && T::CapAdd == 8000u, "the constants");
        // bbport (r89n_twigs-visible): the shader versions since r89n carry BoostAdd (with the cap on or off)
        Expect(T::BoostAdd == 20000u && T::KnownVersion(2011 + T::FixAdd + T::BoostAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + T::FixAdd + T::CapAdd + T::BoostAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 20 + T::OffsetAdd + T::FixAdd + T::CapAdd + T::BoostAdd, 11, 21, 1000) &&
                   !T::KnownVersion(2011 + T::BoostAdd, 11, 21, 1000) && !T::KnownVersion(2011 + T::CapAdd + T::BoostAdd, 11, 21, 1000),
               "the shader versions with BoostAdd are known, a stray one is not");
        Expect(T::KnownVersion(2011 + T::FixAdd, 11, 21, 1000) && T::KnownVersion(2011 + T::FixAdd + T::CapAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 20 + T::OffsetAdd + T::FixAdd + T::CapAdd, 11, 21, 1000) &&
                   T::KnownVersion(2011 + 20 + T::OffsetAdd, 11, 21, 1000) && !T::KnownVersion(2011 + 7, 11, 21, 1000) &&
                   !T::KnownVersion(2011 + T::CapAdd, 11, 21, 1000),
               "the shader versions with the fix and the cap are known, a stray one is not");
        char cap_text[640];
        T::CapOnceText(cap_text, sizeof(cap_text));
        Expect(std::strstr(cap_text, "Wind twigs cap") != nullptr && std::strstr(cap_text, "BB_WIND_TWIGS_CAP=") != nullptr && std::strlen(cap_text) < 560 &&
                   std::strstr(cap_text, "box-many") != nullptr,
               "the cap's once line");
    }

    { // bbport (r89p_twigs-really-move): the open gate's default, the frozen view and the two text functions
        namespace SW = BbWindSway;
        Expect(B::OpenMinDefault == 0.2f && B::OpenMin() == 0.2f, "the trees route's open gate is 0.2 (BB_WIND_TWIGS_OPEN_MIN unset in the test)");
        std::vector<float> view(SW::ViewWords, 0.0f);
        float* const p = view.data() + SW::RippleAt;
        p[13] = 1.0f; // the lean's flag: the skew is on
        p[2] = 0.3f;
        p[3] = 1.9f;
        p[4] = -2.4f;
        p[7] = 0.42f;
        p[12] = 0.12f;
        for (std::uint32_t i = 0; i < SW::GustSamples; ++i) {
            view[SW::TableAt + i] = 0.2f + 0.01f * static_cast<float>(i);
        }
        B::FreezeView(view.data());
        const float at[5][2] = {{0.0f, 0.0f}, {50.0f, -20.0f}, {-7.0f, 13.0f}, {300.0f, 300.0f}, {-1.0f, 0.5f}};
        bool crest = true;
        for (const auto& sq : at) {
            crest = crest && std::fabs(SW::Envelope(view.data(), sq[0], sq[1]) - SW::EnvScale) < 1e-3f;
        }
        Expect(crest, "a frozen view is at the crest of a front (E = EnvScale) at every point");
        bool table = true;
        for (std::uint32_t i = 0; i < SW::GustSamples; ++i) {
            table = table && view[SW::TableAt + i] == 1.0f;
        }
        Expect(table && p[7] == 0.0f && p[0] == 0.0f && p[5] == 0.0f && view[SW::WindB + 3] == 0.0f && view[SW::WindC + 2] == 0.0f,
               "a frozen view: gust table 1, fronts in step, swing and leaf phases 0");
        B::Stats st;
        st.indoors = 39000;
        st.limb_cutout = 123;
        st.taken = 36600;
        st.limbs = 7;
        char gate[400];
        B::GateLineText(st, gate, sizeof(gate));
        Expect(std::strstr(gate, "r89p") != nullptr && std::strstr(gate, "39000") != nullptr && std::strstr(gate, "123") != nullptr &&
                   std::strlen(gate) < 360,
               "the gate's line");
        char once[600];
        B::FreezeOnceText(once, sizeof(once));
        Expect(std::strstr(once, "BB_WIND_FREEZE=1") != nullptr && std::strlen(once) < 520, "the freeze once line");
    }

    if (failures == 0) {
        std::printf("wind-trees-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
