// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86m_glint-pane-from-triangle, TOOL; goes to the test-tools branch): a pane cut from the triangles of an opaque
// G-buffer mesh. The glass of the Hunter's Dream house lantern is not a draw of its own (b59): it is flat triangles inside
// one opaque skinned mesh (the pick named vs:ps 9da6aacb:bb10e440, 794 triangles, a prop set). The glass pick of r86l names
// the DRAW under a pixel; this finds the TRIANGLE: the world positions the capture of that draw made (the surface probe's
// copy to a host slot, RtShadow::ProbeCopyBuild: after the palette transform, before any box) are projected with the camera
// and the triangle that covers the pixel (the nearest one) is the seed; the pane grows over the triangles that share an edge
// with it, lie in its plane (normals within NormalDegrees, every vertex within PlaneMetres of the seed's plane) and stops
// where the frame bends away. The panel's world box, size and normal are logged; the pane is then the draw's own triangles
// of that set only (RtShadow::MakeEntry keeps them, the rest of the mesh stays solid or is left out of the pane).
//
//   BB_GLASS_PICK_TRI=1    read once at the start (the surface probe's host copy is made then): the pick pixels named in
//                          BB_GLASS_PICK_PANES whose last G-buffer draw has a scene entry take the triangle route instead
//                          of the whole-mesh route; and, once at the arming of BB_GLASS_PICK, the G-buffer's channels at
//                          every pick pixel are read back and logged (glass pixels against frame and wall pixels).
//
// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <limits>
#include <unordered_map>
#include <vector>

#include "rt_glass_find.h"

namespace Vulkan::RtGlassTri {

inline bool On() {
    static const bool on = [] {
        const char* text = std::getenv("BB_GLASS_PICK_TRI");
        return text != nullptr && text[0] == '1' && text[1] == '\0';
    }();
    return on;
}

inline constexpr float NormalDegrees = 10.0f;
inline constexpr float NormalCosine = 0.98480775f; ///< cos(NormalDegrees)
inline constexpr float PlaneMetres = 0.01f;
inline constexpr float WeldMetres = 0.001f;         ///< vertices this close are one corner (copies for seams and normals)
inline constexpr std::uint32_t PanelTrianglesMost = 512;
inline constexpr float PanelMostMetres = 3.0f;      ///< a flat panel wider than this is a wall or a floor, not a pane
inline constexpr float EdgePixels = 4.0f;           ///< a pixel this near a triangle's edge (and in none) still names it
inline constexpr float RadiusMetres = 0.75f;        ///< r86n: only triangles with every vertex this near the seed's first vertex are looked at
inline constexpr float PaneLongestMetres = 0.6f;    ///< r86n: a panel longer than this is a post, a frame or a wall, not a pane
inline constexpr float PaneNarrowestMetres = 0.05f; ///< r86n: a panel narrower than this is a post or a rail, not glass
inline constexpr std::uint32_t PanesMost = 8;       ///< r86n: panes the lamp-term log remembers
inline constexpr std::uint32_t LampLinePasses = 1;  ///< r86n: glint passes (after a pane is cut) that log the lamp terms
inline constexpr std::uint32_t WantsMost = 4;       ///< mesh keys at once
inline constexpr std::uint32_t PixelsMost = 8;      ///< pixels a mesh key
inline constexpr std::uint32_t SlotVertices = 131072; ///< r86n: vertices a slot of this tool holds (RtShadow::ProbeBigSlotVertices)
inline constexpr std::uint32_t SlotFirst = 12;      ///< RtShadow's probe slots 12.. are this tool's (the surface probe takes 0 up)
inline constexpr std::uint32_t TriesMost = 6;
inline constexpr std::uint64_t BuildWaitFrames = 600; ///< frames a want waits for a capture of its entry
inline constexpr std::uint64_t CopyWaitFrames = 300;  ///< frames a copy may take before it is asked again
inline constexpr std::uint64_t GatherFrames = 45;     ///< frames after the last pixel before the panels are cut (a pick sweep gives its pixels one by one)

struct V3 {
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

[[nodiscard]] inline V3 Sub(const V3& a, const V3& b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}
[[nodiscard]] inline V3 Cross(const V3& a, const V3& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
[[nodiscard]] inline float Dot(const V3& a, const V3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}
[[nodiscard]] inline float Length(const V3& a) {
    return std::sqrt(Dot(a, a));
}

struct Pixel {
    std::int32_t x = 0, y = 0;
};

/// The captured mesh: world positions (4 floats a vertex: x, y, z, w) and the triangle list the entry holds (three
/// vertex numbers a triangle, relative to the first captured vertex, as the world copy is).
struct Mesh {
    const float* world = nullptr;
    std::uint32_t vertices = 0;
    const std::uint32_t* indices = nullptr;
    std::uint32_t triangles = 0;
};

[[nodiscard]] inline V3 At(const Mesh& m, std::uint32_t vertex) {
    const float* w = m.world + std::size_t(vertex) * 4;
    return {w[0], w[1], w[2]};
}

[[nodiscard]] inline bool Usable(const Mesh& m, std::uint32_t t) {
    for (std::uint32_t k = 0; k < 3; ++k) {
        if (m.indices[std::size_t(t) * 3 + k] >= m.vertices) {
            return false;
        }
    }
    return true;
}

struct Hit {
    bool found = false;
    bool inside = false;     ///< the pixel is inside the triangle (else within EdgePixels of its edge)
    std::uint32_t tri = 0;
    float edge_px = 0.0f;    ///< 0 inside, else the distance to the nearest edge
    float depth = 0.0f;      ///< view depth of the triangle at the pixel, metres
};

[[nodiscard]] inline float SegmentDistance(float px, float py, float ax, float ay, float bx, float by) {
    const float dx = bx - ax, dy = by - ay;
    const float len2 = dx * dx + dy * dy;
    float t = len2 > 1.0e-12f ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0.0f;
    t = std::clamp(t, 0.0f, 1.0f);
    const float cx = ax + t * dx - px, cy = ay + t * dy - py;
    return std::sqrt(cx * cx + cy * cy);
}

/// The triangle of `m` that covers the pixel (px, py) of the 1920x1080 picture, the nearest one when several do; else the
/// one whose edge is nearest within EdgePixels. `view`, `proj`: CameraMotion's (RtGlassFind::ProjectToPicture's reading).
[[nodiscard]] inline Hit FindTriangleAt(const Mesh& m, const std::array<float, 12>& view, const std::array<float, 4>& proj,
                                        float px, float py) {
    Hit best;
    float best_depth = std::numeric_limits<float>::infinity();
    float best_edge = std::numeric_limits<float>::infinity();
    const float forward = proj[3] < 0.0f ? 1.0f : -1.0f;
    if (m.world == nullptr || m.indices == nullptr) {
        return best;
    }
    for (std::uint32_t t = 0; t < m.triangles; ++t) {
        if (!Usable(m, t)) {
            continue;
        }
        std::array<RtGlassFind::ScreenPoint, 3> s{};
        std::array<float, 3> depth{};
        bool front = true;
        for (std::uint32_t k = 0; k < 3; ++k) {
            const V3 p = At(m, m.indices[std::size_t(t) * 3 + k]);
            depth[k] = (view[8] * p.x + view[9] * p.y + view[10] * p.z + view[11]) * forward;
            s[k] = RtGlassFind::ProjectToPicture(view, proj, p.x, p.y, p.z);
            front = front && s[k].front;
        }
        if (!front) {
            continue;
        }
        const float d = (s[1].x - s[0].x) * (s[2].y - s[0].y) - (s[2].x - s[0].x) * (s[1].y - s[0].y);
        if (std::fabs(d) < 1.0e-6f) {
            continue;
        }
        const float w1 = ((px - s[0].x) * (s[2].y - s[0].y) - (s[2].x - s[0].x) * (py - s[0].y)) / d;
        const float w2 = ((s[1].x - s[0].x) * (py - s[0].y) - (px - s[0].x) * (s[1].y - s[0].y)) / d;
        const float w0 = 1.0f - w1 - w2;
        constexpr float slack = -1.0e-4f;
        const float inv = w0 / depth[0] + w1 / depth[1] + w2 / depth[2];
        const float at_depth = inv > 0.0f ? 1.0f / inv : depth[0];
        if (w0 >= slack && w1 >= slack && w2 >= slack) {
            if (!best.inside || at_depth < best_depth) {
                best = {true, true, t, 0.0f, at_depth};
                best_depth = at_depth;
            }
            continue;
        }
        if (best.inside) {
            continue;
        }
        const float e = std::min({SegmentDistance(px, py, s[0].x, s[0].y, s[1].x, s[1].y),
                                  SegmentDistance(px, py, s[1].x, s[1].y, s[2].x, s[2].y),
                                  SegmentDistance(px, py, s[2].x, s[2].y, s[0].x, s[0].y)});
        if (e <= EdgePixels && (e < best_edge || (e == best_edge && at_depth < best_depth))) {
            best = {true, false, t, e, at_depth};
            best_edge = e;
            best_depth = at_depth;
        }
    }
    return best;
}

struct Rules {
    float cosine = NormalCosine;
    float plane = PlaneMetres;
    float weld = WeldMetres;
    std::uint32_t triangles_most = PanelTrianglesMost;
    float metres_most = PanelMostMetres;
    float radius = RadiusMetres;                  ///< r86n: 0 looks at the whole mesh
    float longest_metres = PaneLongestMetres;     ///< r86n: 0 judges nothing
    float narrowest_metres = PaneNarrowestMetres; ///< r86n: 0 judges nothing
};

/// A flat panel of the mesh: the triangles that are connected to the seed by shared edges and lie in its plane.
struct Panel {
    bool ok = false;
    const char* why = "";
    std::vector<std::uint32_t> tris; ///< triangle numbers, ascending
    std::array<float, 3> normal{};
    float offset = 0.0f;             ///< the plane: normal . p = offset
    std::array<float, 6> box{};      ///< least x, y, z, greatest x, y, z over the panel's vertices
    float width = 0.0f, height = 0.0f; ///< the least rectangle in the plane, width >= height, metres
    std::uint32_t by_far = 0; ///< r86n: triangles of the mesh outside the neighbourhood radius (never looked at)
    std::uint32_t by_angle = 0, by_plane = 0, degenerate = 0; ///< neighbours the panel did not take, by the first test that refused them
};

/// r86n: every vertex of triangle `t` within `radius` of `centre`.
[[nodiscard]] inline bool AllWithin(const Mesh& m, std::uint32_t t, const V3& centre, float radius) {
    for (std::uint32_t k = 0; k < 3; ++k) {
        const float d = Length(Sub(At(m, m.indices[std::size_t(t) * 3 + k]), centre));
        if (!(d <= radius)) {
            return false;
        }
    }
    return true;
}

/// r86n: the seed triangle's size and normal and what lies around it: the triangles within the radius, their longest edge in
/// five bins (under 5 cm, 5 to 15, 15 to 30, 30 to 60, over 60 cm) and how many lie in the seed's plane (normal within
/// NormalDegrees, every vertex within PlaneMetres of the plane), connected to the seed or not.
struct Around {
    std::uint32_t tris = 0, coplanar = 0;
    std::array<std::uint32_t, 5> bins{};
    float seed_longest = 0.0f, seed_shortest = 0.0f, seed_area = 0.0f;
    std::array<float, 3> seed_normal{};
};

[[nodiscard]] inline Around Survey(const Mesh& m, std::uint32_t seed, const Rules& rules = {}) {
    Around out;
    if (m.world == nullptr || m.indices == nullptr || seed >= m.triangles || !Usable(m, seed)) {
        return out;
    }
    const V3 a = At(m, m.indices[std::size_t(seed) * 3]);
    const V3 b = At(m, m.indices[std::size_t(seed) * 3 + 1]);
    const V3 c = At(m, m.indices[std::size_t(seed) * 3 + 2]);
    const float e0 = Length(Sub(b, a)), e1 = Length(Sub(c, b)), e2 = Length(Sub(a, c));
    out.seed_longest = std::max({e0, e1, e2});
    out.seed_shortest = std::min({e0, e1, e2});
    const V3 cr = Cross(Sub(b, a), Sub(c, a));
    const float len = Length(cr);
    out.seed_area = 0.5f * len;
    V3 sn{};
    if (len > 1.0e-12f) {
        sn = {cr.x / len, cr.y / len, cr.z / len};
    }
    out.seed_normal = {sn.x, sn.y, sn.z};
    const float offset = Dot(sn, a);
    for (std::uint32_t t = 0; t < m.triangles; ++t) {
        if (!Usable(m, t) || (rules.radius > 0.0f && !AllWithin(m, t, a, rules.radius))) {
            continue;
        }
        ++out.tris;
        const V3 p0 = At(m, m.indices[std::size_t(t) * 3]);
        const V3 p1 = At(m, m.indices[std::size_t(t) * 3 + 1]);
        const V3 p2 = At(m, m.indices[std::size_t(t) * 3 + 2]);
        const float longest = std::max({Length(Sub(p1, p0)), Length(Sub(p2, p1)), Length(Sub(p0, p2))});
        ++out.bins[longest < 0.05f ? 0u : longest < 0.15f ? 1u : longest < 0.3f ? 2u : longest <= 0.6f ? 3u : 4u];
        const V3 tc = Cross(Sub(p1, p0), Sub(p2, p0));
        const float tl = Length(tc);
        if (!(tl > 1.0e-12f) || !(len > 1.0e-12f)) {
            continue;
        }
        const V3 tn{tc.x / tl, tc.y / tl, tc.z / tl};
        if (std::fabs(Dot(sn, tn)) >= rules.cosine && std::fabs(Dot(sn, p0) - offset) <= rules.plane &&
            std::fabs(Dot(sn, p1) - offset) <= rules.plane && std::fabs(Dot(sn, p2) - offset) <= rules.plane) {
            ++out.coplanar;
        }
    }
    return out;
}

[[nodiscard]] inline Panel Grow(const Mesh& m, std::uint32_t seed, const Rules& rules = {}) {
    Panel out;
    if (m.world == nullptr || m.indices == nullptr || seed >= m.triangles || !Usable(m, seed)) {
        out.why = "no usable seed triangle";
        return out;
    }
    const V3 origin = At(m, m.indices[std::size_t(seed) * 3]);
    // the corners: vertices closer than `weld` are one (a mesh repeats a corner for each normal and seam)
    std::vector<std::uint32_t> corner(m.vertices, 0);
    {
        std::unordered_map<std::uint64_t, std::uint32_t> cells;
        cells.reserve(m.vertices);
        const auto cell = [&](float value, float base) {
            double c = (double(value) - double(base)) / double(rules.weld);
            if (!std::isfinite(c)) {
                c = 0.0;
            }
            c = std::clamp(std::floor(c + 0.5), -1.0e6, 1.0e6);
            return std::uint64_t(std::int64_t(c) + 1000000);
        };
        for (std::uint32_t v = 0; v < m.vertices; ++v) {
            const V3 p = At(m, v);
            const std::uint64_t key = cell(p.x, origin.x) | (cell(p.y, origin.y) << 21) | (cell(p.z, origin.z) << 42);
            const auto found = cells.emplace(key, v);
            corner[v] = found.first->second;
        }
    }
    // the normals, and the edges (a pair of corners) with the triangles that have them
    std::vector<V3> normal(m.triangles);
    std::vector<std::uint8_t> bad(m.triangles, 0);
    std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> edges;
    edges.reserve(std::size_t(m.triangles) * 2);
    const auto edge_key = [](std::uint32_t a, std::uint32_t b) {
        return a < b ? (std::uint64_t(a) << 32) | b : (std::uint64_t(b) << 32) | a;
    };
    for (std::uint32_t t = 0; t < m.triangles; ++t) {
        if (!Usable(m, t)) {
            bad[t] = 1;
            continue;
        }
        if (rules.radius > 0.0f && !AllWithin(m, t, origin, rules.radius)) {
            bad[t] = 2; // r86n: outside the neighbourhood of the seed: never put in the edge map
            ++out.by_far; // counted here: a far triangle is in no edge list, so it never comes up as a neighbour
            continue;
        }
        const std::uint32_t i0 = m.indices[std::size_t(t) * 3], i1 = m.indices[std::size_t(t) * 3 + 1],
                            i2 = m.indices[std::size_t(t) * 3 + 2];
        const std::uint32_t c0 = corner[i0], c1 = corner[i1], c2 = corner[i2];
        const V3 n = Cross(Sub(At(m, i1), At(m, i0)), Sub(At(m, i2), At(m, i0)));
        const float len = Length(n);
        if (c0 == c1 || c1 == c2 || c0 == c2 || !(len > 1.0e-9f) || !std::isfinite(len)) {
            bad[t] = 1;
            continue;
        }
        normal[t] = {n.x / len, n.y / len, n.z / len};
        edges[edge_key(c0, c1)].push_back(t);
        edges[edge_key(c1, c2)].push_back(t);
        edges[edge_key(c2, c0)].push_back(t);
    }
    if (bad[seed] != 0) {
        out.why = bad[seed] == 2 ? "the seed triangle has a vertex farther than 0.75 m from its first: a wall or a floor, not a pane"
                                 : "the seed triangle is degenerate";
        return out;
    }
    const V3 n = normal[seed];
    out.normal = {n.x, n.y, n.z};
    out.offset = Dot(n, origin);
    std::vector<std::uint8_t> state(m.triangles, 0); // 0 not seen, 1 in the panel, 2 seen and refused
    std::vector<std::uint32_t> queue{seed};
    state[seed] = 1;
    bool too_many = false;
    for (std::size_t head = 0; head < queue.size() && !too_many; ++head) {
        const std::uint32_t t = queue[head];
        for (std::uint32_t k = 0; k < 3 && !too_many; ++k) {
            const std::uint32_t a = corner[m.indices[std::size_t(t) * 3 + k]];
            const std::uint32_t b = corner[m.indices[std::size_t(t) * 3 + (k + 1) % 3]];
            const auto found = edges.find(edge_key(a, b));
            if (found == edges.end()) {
                continue;
            }
            for (const std::uint32_t u : found->second) {
                if (state[u] != 0) {
                    continue;
                }
                state[u] = 2;
                if (bad[u] != 0) {
                    ++out.degenerate;
                    continue;
                }
                if (std::fabs(Dot(n, normal[u])) < rules.cosine) {
                    ++out.by_angle;
                    continue;
                }
                bool flat = true;
                for (std::uint32_t j = 0; j < 3 && flat; ++j) {
                    flat = std::fabs(Dot(n, At(m, m.indices[std::size_t(u) * 3 + j])) - out.offset) <= rules.plane;
                }
                if (!flat) {
                    ++out.by_plane;
                    continue;
                }
                state[u] = 1;
                queue.push_back(u);
                if (queue.size() > rules.triangles_most) {
                    too_many = true;
                    break;
                }
            }
        }
    }
    std::sort(queue.begin(), queue.end());
    out.tris = queue;
    // the box and the least rectangle (the plane's axes turned in steps of 5 degrees) over the panel's vertices
    const V3 up = std::fabs(n.y) < 0.9f ? V3{0.0f, 1.0f, 0.0f} : V3{1.0f, 0.0f, 0.0f};
    V3 ua = Cross(n, up);
    const float ulen = Length(ua);
    ua = {ua.x / ulen, ua.y / ulen, ua.z / ulen};
    const V3 va = Cross(n, ua);
    out.box = {std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity(),
               std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(),
               -std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()};
    std::vector<std::array<float, 2>> flat_points;
    flat_points.reserve(out.tris.size() * 3);
    for (const std::uint32_t t : out.tris) {
        for (std::uint32_t j = 0; j < 3; ++j) {
            const V3 p = At(m, m.indices[std::size_t(t) * 3 + j]);
            out.box = {std::min(out.box[0], p.x), std::min(out.box[1], p.y), std::min(out.box[2], p.z),
                       std::max(out.box[3], p.x), std::max(out.box[4], p.y), std::max(out.box[5], p.z)};
            flat_points.push_back({Dot(p, ua), Dot(p, va)});
        }
    }
    float best_area = std::numeric_limits<float>::infinity();
    for (int step = 0; step < 18; ++step) {
        const float angle = float(step) * 5.0f * 3.14159265f / 180.0f;
        const float c = std::cos(angle), s = std::sin(angle);
        float lo_a = std::numeric_limits<float>::infinity(), hi_a = -lo_a, lo_b = lo_a, hi_b = -lo_a;
        for (const auto& q : flat_points) {
            const float a = q[0] * c + q[1] * s, b = -q[0] * s + q[1] * c;
            lo_a = std::min(lo_a, a);
            hi_a = std::max(hi_a, a);
            lo_b = std::min(lo_b, b);
            hi_b = std::max(hi_b, b);
        }
        const float w = hi_a - lo_a, h = hi_b - lo_b;
        if (w * h < best_area) {
            best_area = w * h;
            out.width = std::max(w, h);
            out.height = std::min(w, h);
        }
    }
    if (too_many) {
        out.why = "more than 512 triangles: a wall or a floor, not a pane";
        return out;
    }
    if (out.width > rules.metres_most) {
        out.why = "wider than 3 m: a wall or a floor, not a pane";
        return out;
    }
    if (rules.longest_metres > 0.0f && out.width > rules.longest_metres) {
        out.why = "longer than 0.6 m: a post or a frame, not glass";
        return out;
    }
    if (rules.narrowest_metres > 0.0f && out.height < rules.narrowest_metres) {
        out.why = "narrower than 0.05 m: a post or a rail, not glass";
        return out;
    }
    out.ok = true;
    out.why = "taken";
    return out;
}

/// One mesh key the triangle route works on: its pixels, its stage, the copy of its world positions and the camera of that
/// frame, and (stage 3) the triangles that make its pane.
struct Want {
    std::uint64_t key = 0;
    std::uint32_t stage = 0; ///< 0 free, 1 waits for a capture of the solid entry, 2 its copy is on the way, 3 pane taken, 4 failed
    std::uint32_t slot = 0, vertices = 0, triangles = 0, tries = 0;
    std::uint32_t skip = 0;  ///< captures of the key to let pass before the next copy (a mesh drawn several times: another instance)
    std::uint64_t since = 0; ///< the frame the stage began
    std::uint64_t last_pixel = 0; ///< the frame the last pixel was added
    std::array<Pixel, PixelsMost> pixels{};
    std::uint32_t pixel_count = 0;
    std::vector<std::uint32_t> indices; ///< the entry's triangle list at the time of the copy
    std::array<float, 12> view{};
    std::array<float, 4> proj{};
    bool camera_ok = false;
    std::vector<std::uint32_t> keep;    ///< stage 3: the pane's triangles, ascending
};

struct State {
    std::array<Want, WantsMost> wants{};
    std::uint32_t asked = 0, copies = 0, panels = 0, kept = 0, retried = 0, failed = 0; ///< the periodic line's counters
    bool said = false;
};

/// r86n: a pane that was cut (world centre, normal, size): the first glint pass after it logs each lamp's N.H and term for it.
struct PaneInfo {
    std::uint64_t key = 0;
    std::array<float, 3> centre{};
    std::array<float, 3> normal{};
    float width = 0.0f, height = 0.0f;
};

struct Registry {
    std::array<PaneInfo, PanesMost> panes{};
    std::uint32_t count = 0;
    std::uint32_t lines_left = 0; ///< glint passes that still log the lamp terms
};

[[nodiscard]] inline Registry& Panes() {
    static Registry registry;
    return registry;
}

inline void AddPane(const PaneInfo& pane) {
    Registry& r = Panes();
    if (r.count < PanesMost) {
        r.panes[r.count++] = pane;
    }
    r.lines_left = LampLinePasses;
}

[[nodiscard]] inline bool LampLinesPending() {
    return On() && Panes().lines_left != 0;
}

/// A lamp of the glint pass: view-space position, reach, the largest colour channel.
struct LampIn {
    float x = 0.0f, y = 0.0f, z = 0.0f, reach = 0.0f, colour = 0.0f;
};

/// The first glint pass after a pane was cut: for each pane and each lamp the numbers that decide whether a glint can show
/// (the pane's centre and normal in view space, camera at the origin as the shader has it, normal toward the camera).
/// `term(d, reach, nl, nh, vh, sharp)` is glass_glint.h's Term. Prints and counts the pass down.
template <class TermFn>
inline void NoteLampTerms(const std::array<float, 12>& view, const LampIn* lamps, std::uint32_t count, float sharp,
                          float strength, TermFn&& term) {
    Registry& r = Panes();
    if (r.lines_left == 0 || lamps == nullptr) {
        return;
    }
    --r.lines_left;
    constexpr float fires = 1.0f / 255.0f;
    for (std::uint32_t i = 0; i < r.count; ++i) {
        const PaneInfo& p = r.panes[i];
        const V3 c{p.centre[0], p.centre[1], p.centre[2]};
        const V3 pv{view[0] * c.x + view[1] * c.y + view[2] * c.z + view[3],
                    view[4] * c.x + view[5] * c.y + view[6] * c.z + view[7],
                    view[8] * c.x + view[9] * c.y + view[10] * c.z + view[11]};
        V3 nv{view[0] * p.normal[0] + view[1] * p.normal[1] + view[2] * p.normal[2],
              view[4] * p.normal[0] + view[5] * p.normal[1] + view[6] * p.normal[2],
              view[8] * p.normal[0] + view[9] * p.normal[1] + view[10] * p.normal[2]};
        const float dist = Length(pv);
        if (!(dist > 1.0e-4f)) {
            continue;
        }
        if (Dot(nv, pv) > 0.0f) {
            nv = {-nv.x, -nv.y, -nv.z};
        }
        const V3 v{-pv.x / dist, -pv.y / dist, -pv.z / dist};
        std::printf("GLINT-PROOF glass glint (r86n): first pass with a pane: pane %u of %u (mesh key %016llx, %.3f x %.3f m, "
                    "%.2f m from the camera, normal toward the camera (%.3f, %.3f, %.3f) in view space), %u lamps, sharpness "
                    "%.0f, strength %.2f; a lamp's value is colour x term x strength, a glint shows from 1/255\n",
                    i + 1, r.count, static_cast<unsigned long long>(p.key), static_cast<double>(p.width),
                    static_cast<double>(p.height), static_cast<double>(dist), static_cast<double>(nv.x),
                    static_cast<double>(nv.y), static_cast<double>(nv.z), count, static_cast<double>(sharp),
                    static_cast<double>(strength));
        for (std::uint32_t k = 0; k < count; ++k) {
            const LampIn& lamp = lamps[k];
            const V3 to{lamp.x - pv.x, lamp.y - pv.y, lamp.z - pv.z};
            const float d = Length(to);
            if (!(d > 1.0e-4f)) {
                continue;
            }
            const V3 l{to.x / d, to.y / d, to.z / d};
            const float nl = Dot(nv, l);
            const V3 hs{l.x + v.x, l.y + v.y, l.z + v.z};
            const float hl = Length(hs);
            const float nh = hl > 1.0e-6f ? std::max(Dot(nv, hs) / hl, 0.0f) : 0.0f;
            const float vh = hl > 1.0e-6f ? std::clamp(Dot(v, hs) / hl, 0.0f, 1.0f) : 0.0f;
            const float degrees = std::acos(std::min(nh, 1.0f)) * 57.29578f;
            const float t = term(d, lamp.reach, nl, nh, vh, sharp);
            const float peak = term(d, lamp.reach, nl, 1.0f, vh, sharp);
            const float scale = lamp.colour * strength;
            char need[160] = "";
            const char* verdict = need;
            if (!(d < lamp.reach)) {
                verdict = "out of the lamp's reach";
            } else if (!(nl > 0.0f)) {
                verdict = "the lamp is behind the pane (N.L is 0 or less)";
            } else if (t * scale >= fires) {
                verdict = "fires";
            } else if (peak * scale < fires) {
                verdict = "CAN NEVER FIRE for this lamp: even N.H 1 stays under 1/255";
            } else {
                const float needed = std::pow(fires / (peak * scale), 1.0f / std::max(sharp, 1.0f));
                std::snprintf(need, sizeof(need), "N.H too low: needs about %.3f (half vector within %.1f degrees of the normal)",
                              static_cast<double>(needed), static_cast<double>(std::acos(std::min(needed, 1.0f)) * 57.29578f));
            }
            std::printf("GLINT-PROOF glass glint (r86n):   lamp %u of %u at %.2f m (reach %.1f, colour %.2f): N.L %.3f, N.H %.3f "
                        "(half vector %.1f degrees off the normal), term %.3e, x colour x strength %.3e, at N.H 1 %.3e: %s\n",
                        k + 1, count, static_cast<double>(d), static_cast<double>(lamp.reach), static_cast<double>(lamp.colour),
                        static_cast<double>(nl), static_cast<double>(nh), static_cast<double>(degrees),
                        static_cast<double>(t), static_cast<double>(t * scale), static_cast<double>(peak * scale), verdict);
        }
    }
}

struct Solved {
    std::vector<PaneInfo> panes; ///< r86n: one a usable panel
    std::vector<std::uint32_t> keep; ///< ascending, no repeats
    std::uint32_t panels = 0, missed = 0, refused = 0, same = 0;
};

inline void PanelLine(const Pixel& p, std::uint64_t key, const Hit& h, std::uint32_t triangles, const Panel& pa, char* out,
                      std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86m): pane from triangle: pixel %d,%d, mesh key %016llx, triangle %u of %u (%s, "
                  "%.1f px off, %.2f m deep): %s: tris %zu, size %.3f x %.3f m, normal (%.3f, %.3f, %.3f), plane %.3f, box "
                  "(%.2f %.2f %.2f) to (%.2f %.2f %.2f), neighbours left out: %u by angle, %u by plane, %u degenerate, %u out of the neighbourhood",
                  p.x, p.y, static_cast<unsigned long long>(key), h.tri, triangles, h.inside ? "inside" : "near its edge",
                  static_cast<double>(h.edge_px), static_cast<double>(h.depth), pa.why, pa.tris.size(),
                  static_cast<double>(pa.width), static_cast<double>(pa.height), static_cast<double>(pa.normal[0]),
                  static_cast<double>(pa.normal[1]), static_cast<double>(pa.normal[2]), static_cast<double>(pa.offset),
                  static_cast<double>(pa.box[0]), static_cast<double>(pa.box[1]), static_cast<double>(pa.box[2]),
                  static_cast<double>(pa.box[3]), static_cast<double>(pa.box[4]), static_cast<double>(pa.box[5]), pa.by_angle,
                  pa.by_plane, pa.degenerate, pa.by_far);
}

/// The panels of a want's pixels over the copied world positions: one line each through `emit(const char*)`; the union of
/// the panels that are usable is the pane's triangle set.
template <class Emit>
[[nodiscard]] inline Solved Solve(const Want& w, const float* world, Emit&& emit) {
    Solved out;
    Mesh m;
    m.world = world;
    m.vertices = w.vertices;
    m.indices = w.indices.data();
    m.triangles = static_cast<std::uint32_t>(std::min<std::size_t>(w.triangles, w.indices.size() / 3));
    char line[760];
    for (std::uint32_t i = 0; i < w.pixel_count; ++i) {
        const Pixel& p = w.pixels[i];
        const Hit h = FindTriangleAt(m, w.view, w.proj, float(p.x) + 0.5f, float(p.y) + 0.5f);
        if (!h.found) {
            std::snprintf(line, sizeof(line),
                          "GLINT-PROOF glass pick (r86m): pane from triangle: pixel %d,%d, mesh key %016llx: no triangle of "
                          "the mesh covers the pixel or lies within %.0f px of it (%u triangles tried, camera %s): nothing "
                          "taken for this pixel",
                          p.x, p.y, static_cast<unsigned long long>(w.key), static_cast<double>(EdgePixels), m.triangles,
                          w.camera_ok ? "of the capture's frame" : "UNKNOWN (no matrices)");
            emit(static_cast<const char*>(line));
            ++out.missed;
            continue;
        }
        if (std::binary_search(out.keep.begin(), out.keep.end(), h.tri)) {
            std::snprintf(line, sizeof(line),
                          "GLINT-PROOF glass pick (r86m): pane from triangle: pixel %d,%d, mesh key %016llx: triangle %u is "
                          "in a panel taken for an earlier pixel (the same panel)",
                          p.x, p.y, static_cast<unsigned long long>(w.key), h.tri);
            emit(static_cast<const char*>(line));
            ++out.same;
            continue;
        }
        const Around around = Survey(m, h.tri);
        std::snprintf(line, sizeof(line),
                      "GLINT-PROOF glass pick (r86n): seed triangle %u of %u at pixel %d,%d (mesh key %016llx): longest edge "
                      "%.3f m, shortest %.3f m, area %.4f m2, normal (%.3f, %.3f, %.3f); within %.2f m of it %u triangles "
                      "(longest edge under 5 cm %u, 5 to 15 cm %u, 15 to 30 cm %u, 30 to 60 cm %u, over 60 cm %u), %u of them "
                      "in the seed's plane (connected to it or not)",
                      h.tri, m.triangles, p.x, p.y, static_cast<unsigned long long>(w.key),
                      static_cast<double>(around.seed_longest), static_cast<double>(around.seed_shortest),
                      static_cast<double>(around.seed_area), static_cast<double>(around.seed_normal[0]),
                      static_cast<double>(around.seed_normal[1]), static_cast<double>(around.seed_normal[2]),
                      static_cast<double>(RadiusMetres), around.tris, around.bins[0], around.bins[1], around.bins[2],
                      around.bins[3], around.bins[4], around.coplanar);
        emit(static_cast<const char*>(line));
        const Panel pa = Grow(m, h.tri);
        PanelLine(p, w.key, h, m.triangles, pa, line, sizeof(line));
        emit(static_cast<const char*>(line));
        if (!pa.ok) {
            ++out.refused;
            continue;
        }
        ++out.panels;
        out.panes.push_back({w.key,
                             {(pa.box[0] + pa.box[3]) * 0.5f, (pa.box[1] + pa.box[4]) * 0.5f, (pa.box[2] + pa.box[5]) * 0.5f},
                             pa.normal, pa.width, pa.height});
        std::vector<std::uint32_t> merged;
        merged.reserve(out.keep.size() + pa.tris.size());
        std::set_union(out.keep.begin(), out.keep.end(), pa.tris.begin(), pa.tris.end(), std::back_inserter(merged));
        out.keep.swap(merged);
    }
    if (out.panels == 0 && w.pixel_count > 0) {
        std::snprintf(line, sizeof(line),
                      "GLINT-PROOF glass pick (r86n): NO PANE CUT from the %u pixel(s) of mesh key %016llx (%u refused as a "
                      "post, frame or wall, %u without a triangle): if these pixels lie on the lit panes, the panes are NOT "
                      "separate flat glass triangles of this mesh (emissive or painted texture on the body, or the glass is "
                      "another mesh); the seed triangle lines above hold the sizes of the triangles around each pixel",
                      w.pixel_count, static_cast<unsigned long long>(w.key), out.refused, out.missed);
        emit(static_cast<const char*>(line));
    }
    return out;
}

inline void OnceTextAim(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86n, TOOL): panels are cut from the triangles within %.2f m of the seed; a panel "
                  "longer than %.2f m or narrower than %.2f m is refused as a post or frame, not glass; the world copy slots "
                  "%u to %u hold %u vertices each; the first glint pass after a pane is cut logs N.H and the term of every "
                  "lamp for it",
                  static_cast<double>(RadiusMetres), static_cast<double>(PaneLongestMetres),
                  static_cast<double>(PaneNarrowestMetres), SlotFirst, SlotFirst + WantsMost - 1, SlotVertices);
}

inline void OnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86m, TOOL, BB_GLASS_PICK_TRI=1): a pane pixel whose last G-buffer draw has a "
                  "scene entry takes the triangle route: the entry's world positions are copied to a host slot at its next "
                  "capture (probe slots %u to %u), the triangle under the pixel seeds a flat panel (normals within %.0f "
                  "degrees, vertices within %.0f cm of the seed's plane, corners %.0f mm apart are one, at most %u "
                  "triangles and %.0f m), and the pane is those triangles of the draw only (its solid entry is replaced by "
                  "them while the mesh is taken); the G-buffer's channels at every pick pixel are logged once when the pick "
                  "is armed",
                  SlotFirst, SlotFirst + WantsMost - 1, static_cast<double>(NormalDegrees), static_cast<double>(PlaneMetres * 100.0f),
                  static_cast<double>(WeldMetres * 1000.0f), PanelTrianglesMost, static_cast<double>(PanelMostMetres));
}

inline void CounterLine(const State& s, std::uint64_t frame, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86m): frame %llu: %u wants asked, %u world copies asked, %u panels found, %u "
                  "triangles kept, %u retries, %u failed",
                  static_cast<unsigned long long>(frame), s.asked, s.copies, s.panels, s.kept, s.retried, s.failed);
}

} // namespace Vulkan::RtGlassTri
