# r86m_glint-pane-from-triangle: TOOL (goes to the test-tools branch, dev/test-tools; never a feature branch or a pull request).
# On top of build 59's tree (r86l_glint-pick-glass.fixed applied, r86k .. r86b, r83 chain, r64b's surface probe copy).
#
# THE OWNER: "make sure to add those glass and water reflections and caustics apart of the lamp raytracing changes. They
# should receive the same treatment from sun raytracing and other lights not just from the hunter."
#
# WHY (b59, slot_b59_result.txt, b59_reports.txt): the glass pick works. The pixels 1255:560 and 1240:620 of the b59 picture name ONE
# opaque G-buffer draw (vs:ps 9da6aacb:bb10e440, mesh key e609f2f1518698d0, 794 triangles, GPU palette, a prop set 10.3 x 3.8 x
# 14.6 m); the forward draws there are sprites. So the lantern's glass is flat triangles INSIDE an opaque mesh: no draw, no shader
# pair and no scene-entry box can cut it out, and r86l's whole-mesh pane (a 10 m box) is no pane. (Reading the b59 picture again:
# those two pixels lie on the shelf post and the fire left of the lantern, not on its panes: the lantern's panes are near
# 1348:621, 1371:622, 1370:642, its frame post 1357:628, its base 1350:658, in the 1920x1080 picture. The jobs use these.)
#
# WHAT THIS ADDS (everything behind BB_GLASS_PICK_TRI=1 in the environment, read once at the start):
#  (1) THE TRIANGLE UNDER THE PIXEL. The pick names the draw and its mesh key (r86l). For a pane pixel (BB_GLASS_PICK_PANES) the
#      last G-buffer draw with samples, when the scene has an entry for its mesh, is WANTED (RtShadow::GlassTriWant). The want
#      makes the key's solid entry captured once more at its next draw (PrepareDraw: a static entry is made unbuilt for it; a
#      palette entry is captured at every draw anyway) and the build's world positions (after the palette transform, the unproject
#      pass of RecordBuilds) go to a host slot: the surface probe's copy (RtShadow::ProbeCopyBuild, probe slots 12 to 15; the
#      knob makes RtShadow::probe_on true, as BB_SURFACE_PROBE=1 does). The entry's triangle list and the camera of that frame are
#      kept. RtShadow::GlassTriFrameEnd reads the positions once the GPU is past the copy (scheduler.IsFree) and 45 frames after
#      the pick's last pixel (a sweep gives its pixels one by one), and projects every triangle with the camera
#      (RtGlassFind::ProjectToPicture: the reading the box rule's logs proved): the triangle that covers the pixel, the nearest if
#      several, else the one within 4 px of its edge, is the seed (RtGlassTri::FindTriangleAt, a CPU search over the entry's
#      triangles: no GPU pass, no shader).
#  (2) THE PANE FROM THE TRIANGLE. RtGlassTri::Grow: from the seed over triangles that share an EDGE (corners closer than 1 mm
#      are one: a mesh repeats a corner for each normal and seam) and are coplanar: the normal within 10 degrees of the seed's
#      (a back side counts) and every vertex within 1 cm of the seed's plane; the frame of a lantern bends away from the glass,
#      so the growth stops there (a frame in the glass's plane would be part of the pane: said in the report). A panel of more
#      than 512 triangles or wider than 3 m is a wall or a floor and refused. The panel's world box, least rectangle (w x h
#      metres), normal and plane are logged: "pane from triangle: pixel, mesh key, triangle T of N, tris N, size w x h m, normal".
#      Every pane pixel of a mesh is handled the same way and the panels are joined (every flat panel the pixels name). The key
#      is then taken (GlassPickTake: the box rule's route) with the triangle set (RtShadow::GlassTriKeep): the first draw of the
#      pane entry makes it from those triangles only (MakeEntry keeps them: the draw's own vertices, the BLAS holds the pane).
#      CAVEAT (as r86l's mode 2): while the mesh is taken its draws are pane records INSTEAD of the solid entry the scene had of
#      it (the lamp and sun shadow of the mesh are left out): for looking at the glint, not for judging shadows.
#  (3) THE G-BUFFER'S CHANNELS at every pick pixel: once, when BB_GLASS_PICK is armed, at the first blended scene draw (or fog
#      composite) of a frame that is not a pick frame, one texel of cb0 to cb4 and of the depth at each pixel is copied to a
#      small host buffer (the surface probe's recipe: Runtime::Transit, the reduced proxy when it holds the content) and logged
#      once the GPU is past it: "glass material: pixel x,y (pane pixel|other pixel): cb0=.. cb1=.. cb2=.. cb3=.. cb4=.. depth=..".
#      The jobs name glass pixels, frame pixels and a wall control: whether glass is tellable by the material channels.
#  (4) JOBS: S/slot_jobs_r86m_glint-pane-from-triangle.json (3 jobs).
#
# OFF (default): BB_GLASS_PICK_TRI unset. RtGlassTri::On() is a static bool (false); RtShadow::ProbeWanted adds it to the surface
# probe's own test (false, so probe_on stays as BB_SURFACE_PROBE has it); in PrepareDraw glass_tri_active is a u32 member that
# stays 0 (the hooks test it first: one compare, nothing read after it; the pane-entry hook runs at an entry's creation only and
# reads glass_tri, a null pointer); Rasterizer::glass_tri_on is a const false, glass_tri_read a false bool (the hooks in
# EffectsAfterTargets, EffectsBlendedScene and EffectsSceneComposite test it) and glass_tri_job a null pointer; the pick's report
# tests RtGlassTri::On() once a draw line. No shader, no pipeline key, no cache version, no allocation, no GPU work, no log line.
# ON: a world copy of at most 16384 vertices x 16 bytes (the surface probe's host slots, 4 MiB made at the first copy), one more
# capture and BLAS build of the wanted entry, a CPU search over its triangles (a few hundred microseconds, once a mesh), 768
# bytes of host readback once, some log lines; at most 8 pixels x 4 mesh keys.
#
# SHARED LINES TOUCHED (the pixel pick itself is NOT touched: bbport_wind_trees.h, WindTreesPickQuery, the trees_pick_draw gates and
# the query pool stay as r86l left them; r89m and r112n can change them): vk_rasterizer_effects.cpp: GlassPickGroup (r86l's report
# function: one line after RowsShown's, one block before PaneVerdict: in tri mode a pane pixel only takes the triangle route, the
# whole-mesh and forward routes are skipped for it), GlassPickPoll (one statement after its once line), WindTreesPickFrameEnd (one
# call after its GlassPickPoll() line), EffectsAfterTargets (one block after the glint's ClearLights), EffectsBlendedScene and
# EffectsSceneComposite (one call each). vk_rt_shadow.cpp: PrepareDraw (three hook lines: before needs_data, after the build is
# queued, before MakeEntry), MakeEntry (one block before the vertex count), ProbeWanted (one term), OnFrameEnd (one call after the
# find block). vk_rt_shadow.h, vk_rasterizer.h: declarations and members. README.md: one row. tests/test_rt_glass.cpp: a block.
#
# NOT VERIFIED (nothing was built or run; rule: no clang++): see the final report: the C++ spots a compiler could reject.
#
# Files: rt_glass_tri.h (new), vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer.h, vk_rasterizer_effects.cpp, README.md,
# tests/test_rt_glass.cpp.
# Use: python -I -X utf8 r86m_glint-pane-from-triangle.py check | apply | revert
# Root: R86M_ROOT else <tree>. Line ends kept per file (the new file takes CRLF). Backups in r86m_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86m_backup")
ROOT = os.environ.get("R86M_ROOT") or "<tree>"
G = "engine/gpu/"
V = G + "shadps4/video_core/renderer_vulkan/"
TRIH = V + "rt_glass_tri.h"
RTH = V + "vk_rt_shadow.h"
RTC = V + "vk_rt_shadow.cpp"
RASTH = V + "vk_rasterizer.h"
EFFECTS = V + "vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_rt_glass.cpp"
README = "README.md"

NEW_FILES = {
    TRIH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
inline constexpr std::uint32_t WantsMost = 4;       ///< mesh keys at once
inline constexpr std::uint32_t PixelsMost = 8;      ///< pixels a mesh key
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
    std::uint32_t by_angle = 0, by_plane = 0, degenerate = 0; ///< neighbours the panel did not take, by the first test that refused them
};

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
        out.why = "the seed triangle is degenerate";
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

struct Solved {
    std::vector<std::uint32_t> keep; ///< ascending, no repeats
    std::uint32_t panels = 0, missed = 0, refused = 0, same = 0;
};

inline void PanelLine(const Pixel& p, std::uint64_t key, const Hit& h, std::uint32_t triangles, const Panel& pa, char* out,
                      std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86m): pane from triangle: pixel %d,%d, mesh key %016llx, triangle %u of %u (%s, "
                  "%.1f px off, %.2f m deep): %s: tris %zu, size %.3f x %.3f m, normal (%.3f, %.3f, %.3f), plane %.3f, box "
                  "(%.2f %.2f %.2f) to (%.2f %.2f %.2f), neighbours left out: %u by angle, %u by plane, %u degenerate",
                  p.x, p.y, static_cast<unsigned long long>(key), h.tri, triangles, h.inside ? "inside" : "near its edge",
                  static_cast<double>(h.edge_px), static_cast<double>(h.depth), pa.why, pa.tris.size(),
                  static_cast<double>(pa.width), static_cast<double>(pa.height), static_cast<double>(pa.normal[0]),
                  static_cast<double>(pa.normal[1]), static_cast<double>(pa.normal[2]), static_cast<double>(pa.offset),
                  static_cast<double>(pa.box[0]), static_cast<double>(pa.box[1]), static_cast<double>(pa.box[2]),
                  static_cast<double>(pa.box[3]), static_cast<double>(pa.box[4]), static_cast<double>(pa.box[5]), pa.by_angle,
                  pa.by_plane, pa.degenerate);
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
        const Panel pa = Grow(m, h.tri);
        PanelLine(p, w.key, h, m.triangles, pa, line, sizeof(line));
        emit(static_cast<const char*>(line));
        if (!pa.ok) {
            ++out.refused;
            continue;
        }
        ++out.panels;
        std::vector<std::uint32_t> merged;
        merged.reserve(out.keep.size() + pa.tris.size());
        std::set_union(out.keep.begin(), out.keep.end(), pa.tris.begin(), pa.tris.end(), std::back_inserter(merged));
        out.keep.swap(merged);
    }
    return out;
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
''',
}

# ---------------------------------------------------------------- vk_rt_shadow.h
RTH_FWD_OLD = "} // namespace RtGlassPick\n"
RTH_FWD_NEW = ("} // namespace RtGlassPick\n"
               "namespace RtGlassTri { // bbport (r86m_glint-pane-from-triangle, TOOL): rt_glass_tri.h, included by vk_rt_shadow.cpp\n"
               "struct State;\n"
               "} // namespace RtGlassTri\n")

RTH_PUB_OLD = "    [[nodiscard]] bool GlassPickRead(RtGlassPick::Texts& texts);\n"
RTH_PUB_NEW = (RTH_PUB_OLD +
               "    // bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the glass pick named this mesh key under a pane pixel\n"
               "    // (rt_glass_tri.h). The key's solid entry is captured again and its world positions are copied to a host slot; the pane is\n"
               "    // then cut from the triangles under the pane pixels (GlassTriFrameEnd) and the key taken with them. `note`: the text of a new\n"
               "    // want or pixel (or why none); the return value is true when a pixel was added.\n"
               "    [[nodiscard]] bool GlassTriWant(u64 key, s32 x, s32 y, const char*& note);\n")

RTH_PRIV_OLD = "    u32 glass_pick_gen = 0xffffffffu;\n"
RTH_PRIV_NEW = (RTH_PRIV_OLD +
                "    // bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route's state (made at the first want), the number of wants\n"
                "    // that wait for a capture or a copy, and the triangle set MakeEntry keeps for the pane entry it makes now (null: all)\n"
                "    std::unique_ptr<RtGlassTri::State> glass_tri;\n"
                "    u32 glass_tri_active = 0;\n"
                "    const std::vector<u32>* glass_tri_keep_now = nullptr;\n"
                "    void GlassTriCopy(Entry& entry, u64 key, u32 build);\n"
                "    void GlassTriFrameEnd();\n"
                "    [[nodiscard]] const std::vector<u32>* GlassTriKeep(u64 key) const;\n")

# ---------------------------------------------------------------- vk_rt_shadow.cpp
RTC_INC_OLD = '#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)\n'
RTC_INC_NEW = (RTC_INC_OLD +
               '#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle, TOOL)\n')

RTC_MAKE_OLD = ("    const u64 vertex_count = u64(hi - lo + 1);\n"
                "    if (!good || list.empty() || list.size() / 3 * draw.instances > MaxTrianglesPerBlas ||\n")
RTC_MAKE_NEW = ("    if (good && glass_tri_keep_now != nullptr) { // bbport (r86m_glint-pane-from-triangle, TOOL): a pane cut from some triangles\n"
                "        std::vector<u32> kept;\n"
                "        kept.reserve(glass_tri_keep_now->size() * 3);\n"
                "        for (const u32 t : *glass_tri_keep_now) {\n"
                "            if (std::size_t(t) * 3 + 2 < list.size()) {\n"
                "                kept.insert(kept.end(), list.begin() + std::ptrdiff_t(t) * 3, list.begin() + std::ptrdiff_t(t) * 3 + 3);\n"
                "            }\n"
                "        }\n"
                "        std::printf(\"GLINT-PROOF glass pick (r86m): pane entry made from %zu of %zu triangles of the draw\\n\", kept.size() / 3,\n"
                "                    list.size() / 3);\n"
                "        list.swap(kept);\n"
                "    }\n" + RTC_MAKE_OLD)

RTC_SLOT_OLD = ("            slot = MakeEntry(draw, mask);\n"
                "            if (!slot) {\n"
                "                entries.erase(entry_key);\n")
RTC_SLOT_NEW = ("            // bbport (r86m_glint-pane-from-triangle, TOOL): a pane the triangle route cut is made from its triangles only\n"
                "            glass_tri_keep_now = draw.glass && glass_tri ? GlassTriKeep(RtGlassKey(key)) : nullptr;\n"
                "            slot = MakeEntry(draw, mask);\n"
                "            glass_tri_keep_now = nullptr;\n"
                "            if (!slot) {\n"
                "                entries.erase(entry_key);\n")

RTC_NEEDS_OLD = "    bool needs_data = !entry.built || entry.dynamic || entry.rebuilt ||\n"
RTC_NEEDS_NEW = ("    if (glass_tri_active != 0 && !draw.glass) { // bbport (r86m_glint-pane-from-triangle, TOOL): a mesh a want waits for is captured once more\n"
                 "        for (const RtGlassTri::Want& want : glass_tri->wants) {\n"
                 "            if (want.stage == 1 && want.key == key) {\n"
                 "                entry.built = false;\n"
                 "                break;\n"
                 "            }\n"
                 "        }\n"
                 "    }\n" + RTC_NEEDS_OLD)

RTC_BUILD_OLD = ("        if (probe_on) { // bbport (r64b_surface-probe-more): this draw builds the entry\n"
                 "            probe_draw.build = u32(builds.size());\n"
                 "        }\n")
RTC_BUILD_NEW = (RTC_BUILD_OLD +
                 "        if (glass_tri_active != 0 && !draw.glass) { // bbport (r86m_glint-pane-from-triangle, TOOL): its world positions for a want\n"
                 "            GlassTriCopy(entry, key, u32(builds.size()));\n"
                 "        }\n")

RTC_PROBE_OLD = ('bool RtShadow::ProbeWanted() {\n'
                 '    const char* value = std::getenv("BB_SURFACE_PROBE");\n'
                 "    return value && value[0] == '1' && value[1] == '\\0';\n"
                 '}\n')
RTC_PROBE_NEW = ('bool RtShadow::ProbeWanted() {\n'
                 '    const char* value = std::getenv("BB_SURFACE_PROBE");\n'
                 "    return (value && value[0] == '1' && value[1] == '\\0') || RtGlassTri::On(); // bbport (r86m): its world copy\n"
                 '}\n')

RTC_END_OLD = ("        GlassFindBox();                 // bbport (r86i_glint-find-gbuffer)\n"
               "    }\n")
RTC_END_NEW = (RTC_END_OLD +
               "    if (glass_tri) { // bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route's frame end\n"
               "        GlassTriFrameEnd();\n"
               "    }\n")

RTC_FUNCS_OLD = "// bbport (r86l_glint-pick-glass, TOOL): the five knobs' texts, asked again when the live knobs' generation changed (without the\n"
RTC_FUNCS_NEW = r'''// bbport (r86m_glint-pane-from-triangle, TOOL): the triangle route of the glass pick (rt_glass_tri.h). GlassTriWant: the pick
// named this mesh key under a pane pixel (its last G-buffer draw has a scene entry). The key's solid entry is captured again at
// its next draw (PrepareDraw: a static one is made unbuilt for it) and the build's world positions go to a host slot of the
// surface probe's copy (GlassTriCopy); GlassTriFrameEnd reads them once the GPU is past the copy and the pick's pixels have all
// come (RtGlassTri::GatherFrames after the last), cuts the panels and takes the key (GlassPickTake) with the pane's triangle set
// (GlassTriKeep, which MakeEntry reads). `note` is a line's text for a new want or pixel (null: nothing to say). Frame end, on
// the thread that draws.
bool RtShadow::GlassTriWant(u64 key, s32 x, s32 y, const char*& note) {
    note = nullptr;
    if (!RtGlassTri::On() || key == 0) {
        return false;
    }
    if (!glass_tri) {
        glass_tri = std::make_unique<RtGlassTri::State>();
        char once[1100];
        RtGlassTri::OnceText(once, sizeof(once));
        std::printf("%s\n", once);
    }
    RtGlassTri::Want* want = nullptr;
    for (RtGlassTri::Want& w : glass_tri->wants) {
        if (w.stage != 0 && w.key == key) {
            want = &w;
            break;
        }
    }
    if (want == nullptr) {
        for (RtGlassTri::Want& w : glass_tri->wants) {
            if (w.stage == 0) {
                want = &w;
                break;
            }
        }
        if (want == nullptr) {
            note = "not wanted: the table of 4 mesh keys is full";
            return false;
        }
        *want = RtGlassTri::Want{};
        want->key = key;
        want->stage = 1;
        want->since = frame;
        ++glass_tri->asked;
        ++glass_tri_active;
        note = "wanted: its solid entry is captured again at its next draw and its world positions are copied to a host "
               "slot; the panel is cut from the triangle under each pane pixel once the pick's pixels are all in";
    }
    for (u32 i = 0; i < want->pixel_count; ++i) {
        if (want->pixels[i].x == x && want->pixels[i].y == y) {
            return false;
        }
    }
    if (want->stage >= 3) {
        note = "the pane of this mesh key is cut (or failed) already: this pixel is not used (set the pick again after a "
               "new game start)";
        return false;
    }
    if (want->pixel_count >= RtGlassTri::PixelsMost) {
        note = "not used: 8 pixels a mesh key at most";
        return false;
    }
    want->pixels[want->pixel_count++] = {x, y};
    want->last_pixel = frame;
    if (note == nullptr) {
        note = "pixel added to the want";
    }
    return true;
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the triangle set of the pane of a mesh key (its plain key), or null. MakeEntry
// reads it for a pane entry's first draw.
const std::vector<u32>* RtShadow::GlassTriKeep(u64 key) const {
    if (!glass_tri) {
        return nullptr;
    }
    for (const RtGlassTri::Want& w : glass_tri->wants) {
        if (w.stage == 3 && w.key == key) {
            return &w.keep;
        }
    }
    return nullptr;
}

// bbport (r86m_glint-pane-from-triangle, TOOL): this capture build is of the solid entry a want waits for: its world positions
// go to the want's probe slot (ProbeCopyBuild: with the world copies of RecordBuilds, after the unproject pass), and the entry's
// triangle list and the camera of this frame are kept for the pixel projection (the committed camera when no pass camera is
// open). Not for an entry of several instances or more vertices than a slot holds. Asked again at the next capture while the
// copy could not be asked (a slot busy); the wait ends in RtGlassTri::BuildWaitFrames.
void RtShadow::GlassTriCopy(Entry& entry, u64 key, u32 build) {
    for (u32 i = 0; i < RtGlassTri::WantsMost; ++i) {
        RtGlassTri::Want& w = glass_tri->wants[i];
        if (w.stage != 1 || w.key != key) {
            continue;
        }
        if (w.skip != 0) {
            --w.skip;
            continue;
        }
        if (entry.instances != 1 || entry.triangles == 0 || entry.indices.mapped == nullptr ||
            u64(entry.vertices) * entry.instances > ProbeSlotVertices) {
            w.stage = 4;
            ++glass_tri->failed;
            std::printf("GLINT-PROOF glass pick (r86m): mesh key %016llx: its entry cannot be copied (%u instances, %u "
                        "triangles, %u vertices; a slot holds %u vertices and one instance): nothing is taken\n",
                        static_cast<unsigned long long>(key), entry.instances, entry.triangles, entry.vertices,
                        ProbeSlotVertices);
            continue;
        }
        const u32 slot = RtGlassTri::SlotFirst + i;
        if (!ProbeCopyBuild(build, slot)) {
            continue;
        }
        const CameraMotion::Matrices pass = camera_motion.PassMatrices();
        const CameraMotion::Matrices committed = pass.valid ? pass : camera_motion.CameraMatrices();
        w.view = committed.view;
        w.proj = committed.proj;
        w.camera_ok = pass.valid || committed.valid;
        w.slot = slot;
        w.vertices = entry.vertices;
        w.triangles = entry.triangles;
        const u32* list = static_cast<const u32*>(entry.indices.mapped);
        w.indices.assign(list, list + std::size_t(entry.triangles) * 3);
        w.stage = 2;
        w.since = frame;
        ++glass_tri->copies;
    }
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the frame end of the triangle route: a want whose copy the GPU has passed (and
// whose pixels have all come) is solved (RtGlassTri::Solve: a panel from the triangle under each pixel, one line each) and its
// mesh key is taken with the union of the panels; a want that waits too long for a capture or a copy is asked again (at most
// RtGlassTri::TriesMost times) or fails with a line. The counters' line every 600 frames.
void RtShadow::GlassTriFrameEnd() {
    RtGlassTri::State& s = *glass_tri;
    const auto fail = [&](RtGlassTri::Want& w, const char* why) {
        w.stage = 4;
        ++s.failed;
        std::printf("GLINT-PROOF glass pick (r86m): mesh key %016llx: %s\n", static_cast<unsigned long long>(w.key), why);
    };
    const auto again = [&](RtGlassTri::Want& w, const char* why) {
        ProbeForget(w.slot);
        if (++w.tries > RtGlassTri::TriesMost) {
            fail(w, why);
            return;
        }
        w.stage = 1;
        w.since = frame;
        w.skip = w.tries; // a mesh drawn several times: the next copy is of a later capture, maybe the instance at the pixel
        ++s.retried;
    };
    for (RtGlassTri::Want& w : s.wants) {
        if (w.stage == 1) {
            if (frame > w.since + RtGlassTri::BuildWaitFrames) {
                fail(w, "no capture of the entry's draw came in 600 frames (the entry is not drawn by the camera pass, or "
                        "nothing could be built): nothing is taken");
            }
            continue;
        }
        if (w.stage != 2) {
            continue;
        }
        u64 tick = 0;
        const float* world = ProbeWorld(w.slot, tick);
        if (tick == ProbeDroppedTick) {
            again(w, "the build kept being dropped before it was recorded: nothing is taken");
            continue;
        }
        if (world == nullptr || tick == 0 || !scheduler.IsFree(tick)) {
            if (frame > w.since + RtGlassTri::CopyWaitFrames) {
                again(w, "the copy of the world positions did not come: nothing is taken");
            }
            continue;
        }
        if (frame < w.last_pixel + RtGlassTri::GatherFrames) {
            continue; // more pixels of the pick may still come
        }
        const RtGlassTri::Solved solved =
            RtGlassTri::Solve(w, world, [](const char* text) { std::printf("%s\n", text); });
        ProbeForget(w.slot);
        s.panels += solved.panels;
        if (solved.panels == 0 && solved.refused == 0 && solved.same == 0 && solved.missed == w.pixel_count) {
            again(w, "no triangle of the copied instances covers a pixel of the pick (tried the next capture of the mesh each "
                     "time): nothing is taken");
            continue;
        }
        if (solved.keep.empty()) {
            fail(w, "no panel could be cut from the pixels (see the lines above): nothing is taken");
            continue;
        }
        if (!RtGlassOn()) {
            fail(w, "BB_RT_GLASS is off: nothing is taken (set it, for example auto)");
            continue;
        }
        w.keep = solved.keep;
        w.stage = 3;
        s.kept += static_cast<u32>(w.keep.size());
        const bool joined = GlassPickTake(w.key);
        std::printf("GLINT-PROOF glass pick (r86m): pane taken: mesh key %016llx keeps %zu of %u triangles in %u panel(s) (%u "
                    "pixels, %u in a panel already, %u without a triangle, %u refused); %s: its next draws are pane records "
                    "of those triangles only, the solid entry of the mesh is replaced by them\n",
                    static_cast<unsigned long long>(w.key), w.keep.size(), w.triangles, solved.panels, w.pixel_count,
                    solved.same, solved.missed, solved.refused,
                    joined ? "the key joined the pane keys" : "the key was a pane key already");
    }
    glass_tri_active = 0;
    for (const RtGlassTri::Want& w : s.wants) {
        glass_tri_active += w.stage == 1 || w.stage == 2 ? 1u : 0u;
    }
    if (frame % 600 == 0) {
        char line[300];
        RtGlassTri::CounterLine(s, frame, line, sizeof(line));
        std::printf("%s\n", line);
    }
}

''' + RTC_FUNCS_OLD

# ---------------------------------------------------------------- vk_rasterizer.h
RAH_INC_OLD = '#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)\n'
RAH_INC_NEW = (RAH_INC_OLD +
               '#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle, TOOL)\n')

RAH_MEM_OLD = ("    void GlassPickGroup(const TreesPickGroup& g, const std::vector<u64>& counts, vk::Result result,\n"
               "                        const BbWindTrees::Point& pt);\n")
RAH_MEM_NEW = (RAH_MEM_OLD +
               "    // bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the G-buffer's texels at the pick pixels, once when the\n"
               "    // pick is armed. glass_tri_read: wanted at the next blended draw of a frame that is no pick frame; glass_tri_gb, glass_tri_depth:\n"
               "    // the targets of the last G-buffer pass (EffectsAfterTargets); glass_tri_job: the copy on its way (GlassTriReadPoll).\n"
               "    const bool glass_tri_on = RtGlassTri::On();\n"
               "    bool glass_tri_read = false;\n"
               "    std::array<VideoCore::ImageId, 5> glass_tri_gb{};\n"
               "    VideoCore::ImageId glass_tri_depth{};\n"
               "    struct GlassTriJob;\n"
               "    std::shared_ptr<GlassTriJob> glass_tri_job;\n"
               "    void GlassTriReadback();\n"
               "    void GlassTriReadPoll();\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_ARM_OLD = ("    RtGlassPick::OnceText(knob, glass_pick_panes, once, sizeof(once));\n"
              "    std::printf(\"%s\\n\", once);\n"
              "}\n")
EF_ARM_NEW = ("    RtGlassPick::OnceText(knob, glass_pick_panes, once, sizeof(once));\n"
              "    std::printf(\"%s\\n\", once);\n"
              "    if (glass_tri_on) { // bbport (r86m_glint-pane-from-triangle, TOOL): the G-buffer's texels at the pixels, once\n"
              "        glass_tri_read = true;\n"
              "        glass_tri_gb = {}; // bbport (r86m review): no target ids of an earlier arming (read only after a G-buffer pass)\n"
              "        glass_tri_depth = {};\n"
              "    }\n"
              "}\n")

EF_POLL_OLD = "    GlassPickPoll(); // bbport (r86l_glint-pick-glass, TOOL): BB_GLASS_PICK armed or dropped (live)\n"
EF_POLL_NEW = (EF_POLL_OLD +
               "    if (glass_tri_job) { // bbport (r86m_glint-pane-from-triangle, TOOL): the readback's lines, once the GPU is past it\n"
               "        GlassTriReadPoll();\n"
               "    }\n")

EF_LAST_OLD = "    const std::size_t first_shown = rows.size() > RtGlassPick::RowsShown ? rows.size() - RtGlassPick::RowsShown : 0;\n"
EF_LAST_NEW = (EF_LAST_OLD +
               "    std::size_t last_gbuffer = rows.size(); // bbport (r86m_glint-pane-from-triangle, TOOL): the last G-buffer draw with samples is the surface seen\n"
               "    for (std::size_t n = 0; n < rows.size(); ++n) {\n"
               "        if ((g.draws[rows[n]].glass_flags & RtGlassPick::FlagGBuffer) != 0) {\n"
               "            last_gbuffer = n;\n"
               "        }\n"
               "    }\n")

EF_TRI_OLD = "        const RtGlassPick::Verdict verdict = RtGlassPick::PaneVerdict(d, glass_pick_panes.mode);\n"
EF_TRI_NEW = ("        if (RtGlassTri::On()) { // bbport (r86m_glint-pane-from-triangle, TOOL): a pane pixel's surface is cut into a pane by its triangles\n"
              "            if (n == last_gbuffer) {\n"
              "                const char* note = nullptr;\n"
              "                const char* reason = nullptr;\n"
              "                if (!RtGlassOn()) {\n"
              "                    reason = \"BB_RT_GLASS is off: nothing is taken (set it, for example auto)\";\n"
              "                } else if (d.mesh == 0 || found == 0) {\n"
              "                    reason = \"not wanted: the mesh has no entry in the ray traced scene (no solid entry to copy the world \"\n"
              "                             \"positions from)\";\n"
              "                } else if ((d.glass_flags & RtGlassPick::FlagSkinned) != 0 || d.instances != 1) {\n"
              "                    reason = \"not wanted: a skinned or instanced draw\";\n"
              "                } else if (rt_shadow->GlassTriWant(d.mesh, pt.x, pt.y, note) || note != nullptr) {\n"
              "                    reason = note;\n"
              "                }\n"
              "                if (reason != nullptr) {\n"
              "                    std::snprintf(line, sizeof(line),\n"
              "                                  \"GLINT-PROOF glass pick (r86m): triangle route: pixel %d,%d, last G-buffer draw vs:ps %08x:%08x \"\n"
              "                                  \"mesh key %016llx, %u scene entr%s: %s\",\n"
              "                                  pt.x, pt.y, d.vs, d.ps, static_cast<unsigned long long>(d.mesh), found, found == 1 ? \"y\" : \"ies\",\n"
              "                                  reason);\n"
              "                    std::printf(\"%s\\n\", line);\n"
              "                }\n"
              "            }\n"
              "            continue;\n"
              "        }\n" + EF_TRI_OLD)

EF_NOTE_OLD = ("        if (glass_glint) { // bbport (r86b_glass-visible): the same rule\n"
               "            glass_glint->ClearLights();\n"
               "        }\n")
EF_NOTE_NEW = (EF_NOTE_OLD +
               "        if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): this pass's targets, for the pixel readback\n"
               "            for (u32 cb = 0; cb < 5; ++cb) {\n"
               "                glass_tri_gb[cb] = ((key.mrt_mask >> cb) & 1u) != 0 ? cb_descs[cb].first : VideoCore::ImageId{};\n"
               "            }\n"
               "            glass_tri_depth = db_desc.first;\n"
               "        }\n")

EF_BLEND_OLD = ("        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
                "                                    glint_gpane);\n"
                "    }\n"
                "}\n"
                "\n"
                "// bbport (r45_drawn-look): a full-screen pass over the scene colour is about to be drawn.\n")
EF_BLEND_NEW = ("        glass_glint->AfterGlassDraw(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending(),\n"
                "                                    glint_gpane);\n"
                "    }\n"
                "    if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): the G-buffer's texels at the pick pixels, once\n"
                "        GlassTriReadback();\n"
                "    }\n"
                "}\n"
                "\n"
                "// bbport (r45_drawn-look): a full-screen pass over the scene colour is about to be drawn.\n")

EF_COMP_OLD = "void Rasterizer::EffectsSceneComposite(const GraphicsPipeline* pipeline) {\n"
EF_COMP_NEW = (EF_COMP_OLD +
               "    if (glass_tri_read) { // bbport (r86m_glint-pane-from-triangle, TOOL): as in EffectsBlendedScene, when no blended draw came\n"
               "        GlassTriReadback();\n"
               "    }\n")

EF_READ_OLD = "// bbport (r64b_surface-probe-more): BB_SURFACE_PROBE=1. Once a window, at the first blended scene\n"
EF_READ_NEW = r'''// bbport (r86m_glint-pane-from-triangle, TOOL; BB_GLASS_PICK_TRI=1): the G-buffer's channels at the pick pixels, once when
// BB_GLASS_PICK was armed (GlassPickPoll sets glass_tri_read; EffectsAfterTargets notes the targets of the frame's last G-buffer
// pass at its draws): at the first blended scene draw (or fog composite) of a frame that is not a pick frame, one texel of cb0
// to cb4 and of the depth at each pixel is copied into a small host buffer (as the surface probe's readback does it:
// Runtime::Transit, the reduced scene target's proxy when it holds the content), and GlassTriReadPoll prints the texels once
// the GPU is past the copy. Nothing is written to the targets. The aim: whether glass is tellable from the frame or the wall
// by the G-buffer's channels (the material, the roughness code, the albedo), for a later automatic rule.
struct Rasterizer::GlassTriJob {
    struct Item {
        const char* name = "-";
        vk::Format format = vk::Format::eUndefined;
        u8 texel = 0; ///< a ProbeTexel
        u32 width = 0, height = 0;
        u64 offset = 0;
        bool read = false, proxy = false;
        const char* why = "-";
    };
    std::array<Item, 6> items{};
    std::array<BbWindTrees::Point, BbWindTrees::PickMost> points{};
    std::array<bool, BbWindTrees::PickMost> pane{};
    u32 count = 0, out_w = 1920, out_h = 1080;
    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation{};
    const u8* mapped = nullptr;
    u64 tick = 0, frame = 0;
};

void Rasterizer::GlassTriReadback() {
    if (!glass_tri_read || glass_tri_job || trees_pick_rect_on) {
        return;
    }
    const BbWindTrees::GlassPickLive& live = BbWindTrees::GlassPickState();
    if (!live.armed.load(std::memory_order_relaxed)) {
        glass_tri_read = false;
        return;
    }
    if (!glass_tri_gb[1]) {
        return; // no G-buffer pass seen yet: the next blended draw tries again
    }
    glass_tri_read = false; // one try
    auto job = std::make_shared<GlassTriJob>();
    const BbWindTrees::PickKnob& knob = live.knob;
    job->count = u32(std::min<std::size_t>(knob.count, BbWindTrees::PickMost));
    job->out_w = knob.out_w != 0 ? u32(knob.out_w) : 1920u;
    job->out_h = knob.out_h != 0 ? u32(knob.out_h) : 1080u;
    job->frame = object_motion->Frame();
    for (u32 i = 0; i < job->count; ++i) {
        job->points[i] = knob.points[i];
        job->pane[i] = RtGlassPick::PaneAt(glass_pick_panes, knob.points[i]);
    }
    const std::array<std::pair<const char*, VideoCore::ImageId>, 6> wanted{
        {{"cb0", glass_tri_gb[0]},
         {"cb1", glass_tri_gb[1]},
         {"cb2", glass_tri_gb[2]},
         {"cb3", glass_tri_gb[3]},
         {"cb4", glass_tri_gb[4]},
         {"depth", glass_tri_depth}}};
    const bool reduced = scene_targets->Reduced();
    std::array<VideoCore::ImageId, 6> ids{};
    constexpr u64 per_item = u64(BbWindTrees::PickMost) * 16;
    u64 bytes = 0;
    for (std::size_t i = 0; i < wanted.size(); ++i) {
        GlassTriJob::Item& item = job->items[i];
        item.name = wanted[i].first;
        const VideoCore::ImageId id = wanted[i].second;
        if (!id) {
            item.why = "none";
            continue;
        }
        const auto& image = texture_cache.GetImage(id);
        item.format = image.info.pixel_format;
        const ProbeTexel texel = ProbeTexelOf(item.format);
        item.texel = static_cast<u8>(texel);
        item.proxy = reduced && scene_targets->Eligible(image) && scene_targets->ProxyCurrent(image);
        item.width = image.info.size.width;
        item.height = image.info.size.height;
        if (item.proxy) {
            const auto size = scene_targets->ProxySize(image);
            item.width = size.width;
            item.height = size.height;
        }
        item.offset = u64(i) * per_item;
        if (texel == ProbeTexel::None) {
            item.why = "format";
        } else if (image.info.num_samples > 1) {
            item.why = "multisampled";
        } else if (!item.proxy && !(image.usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) {
            item.why = "usage";
        } else if (item.width == 0 || item.height == 0) {
            item.why = "size";
        } else {
            item.read = true;
            ids[i] = id;
            bytes = item.offset + per_item;
        }
    }
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (bytes != 0) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        const VmaAllocationCreateInfo alloc_ci{
            .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
            .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
        };
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &buffer, &allocation, &info) != VK_SUCCESS ||
            !info.pMappedData) {
            if (buffer) {
                vmaDestroyBuffer(instance.GetAllocator(), buffer, allocation);
            }
            buffer = VK_NULL_HANDLE;
        }
    }
    if (!buffer) {
        std::printf("GLINT-PROOF glass material (r86m): nothing could be read (no readable G-buffer target or no host "
                    "memory for the copy)\n");
        return;
    }
    struct Copy {
        vk::Image image;
        vk::ImageLayout layout{};
        std::vector<vk::BufferImageCopy> regions;
    };
    auto copies = std::make_shared<std::vector<Copy>>();
    scheduler.EndRendering();
    for (std::size_t i = 0; i < job->items.size(); ++i) {
        GlassTriJob::Item& item = job->items[i];
        if (!item.read) {
            continue;
        }
        auto& image = texture_cache.GetImage(ids[i]);
        Copy copy;
        if (item.proxy) {
            VideoCore::ImageViewInfo view_info;
            view_info.format = item.format;
            const auto target = scene_targets->Read(ids[i], view_info, vk::PipelineStageFlagBits2::eTransfer,
                                                    vk::AccessFlagBits2::eTransferRead);
            if (!(target.usage & vk::ImageUsageFlagBits::eTransferSrc)) {
                item.read = false;
                item.why = "proxy-usage";
                continue;
            }
            copy.image = target.image;
            copy.layout = target.layout;
        } else {
            runtime.Transit(&image, vk::ImageLayout::eTransferSrcOptimal, vk::PipelineStageFlagBits2::eTransfer,
                            vk::AccessFlagBits2::eTransferRead);
            copy.image = image.GetImage();
            copy.layout = vk::ImageLayout::eTransferSrcOptimal;
        }
        const auto aspect = std::string_view(item.name) == "depth" ? vk::ImageAspectFlagBits::eDepth
                                                                   : vk::ImageAspectFlagBits::eColor;
        for (u32 p = 0; p < job->count; ++p) {
            const u64 px = u64(std::max(0, job->points[p].x)) * item.width / job->out_w;
            const u64 py = u64(std::max(0, job->points[p].y)) * item.height / job->out_h;
            copy.regions.push_back(vk::BufferImageCopy{
                .bufferOffset = item.offset + u64(p) * 16,
                .imageSubresource = {aspect, 0, 0, 1},
                .imageOffset = {s32(std::min<u64>(px, item.width - 1)), s32(std::min<u64>(py, item.height - 1)), 0},
                .imageExtent = {1, 1, 1},
            });
        }
        copies->push_back(std::move(copy));
    }
    runtime.FlushBarriers();
    const vk::Buffer target_buffer{buffer};
    scheduler.RecordCrumb({.name = "Glass pick G-buffer readback"}, [copies, target_buffer](vk::CommandBuffer cmdbuf) {
        for (const Copy& copy : *copies) {
            cmdbuf.copyImageToBuffer(copy.image, copy.layout, target_buffer, copy.regions);
        }
        const vk::MemoryBarrier2 to_host{
            .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
            .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
            .dstStageMask = vk::PipelineStageFlagBits2::eHost,
            .dstAccessMask = vk::AccessFlagBits2::eHostRead,
        };
        cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_host});
    });
    job->buffer = buffer;
    job->allocation = allocation;
    job->mapped = static_cast<const u8*>(info.pMappedData);
    job->tick = scheduler.CurrentTick();
    glass_tri_job = std::move(job);
}

// bbport (r86m_glint-pane-from-triangle, TOOL): the readback's lines, once the GPU is past the copy (a frame end; nothing waits):
// a header and a line a pixel with every target's texel (its channels in the format's order), the pane pixels marked.
void Rasterizer::GlassTriReadPoll() {
    GlassTriJob& job = *glass_tri_job;
    if (!scheduler.IsFree(job.tick)) {
        return;
    }
    vmaInvalidateAllocation(instance.GetAllocator(), job.allocation, 0, VK_WHOLE_SIZE);
    std::string head = fmt::format(
        "GLINT-PROOF glass material (r86m): the G-buffer's texels at {} pick pixels of a {}x{} picture, read at frame {} "
        "(pane pixels are the ones of BB_GLASS_PICK_PANES; compare them with the frame and wall pixels); targets:",
        job.count, job.out_w, job.out_h, job.frame);
    for (const GlassTriJob::Item& item : job.items) {
        head += item.read ? fmt::format(" {}={}x{} {}{}", item.name, item.width, item.height, vk::to_string(item.format),
                                        item.proxy ? " (proxy)" : "")
                          : fmt::format(" {}=not read ({})", item.name, item.why);
    }
    std::printf("%s\n", head.c_str());
    for (u32 p = 0; p < job.count; ++p) {
        std::string line = fmt::format("GLINT-PROOF glass material (r86m): pixel {},{} ({}):", job.points[p].x, job.points[p].y,
                                       job.pane[p] ? "pane pixel" : "other pixel");
        for (const GlassTriJob::Item& item : job.items) {
            if (!item.read) {
                continue;
            }
            const ProbeTexel texel = static_cast<ProbeTexel>(item.texel);
            std::array<float, 4> c{};
            ProbeDecode(texel, job.mapped + item.offset + u64(p) * 16, c);
            std::string values;
            for (u32 ch = 0; ch < ProbeChannels(texel); ++ch) {
                values += fmt::format("{}{:.4f}", ch != 0 ? "," : "", c[ch]);
            }
            line += fmt::format(" {}={}", item.name, values);
        }
        std::printf("%s\n", line.c_str());
    }
    vmaDestroyBuffer(instance.GetAllocator(), job.buffer, job.allocation);
    glass_tri_job.reset();
}

''' + EF_READ_OLD

# ---------------------------------------------------------------- README.md
RM_OLD = "Panes show only with `BB_GLASS_GLINT` | off |\n"
RM_NEW = (RM_OLD +
          "| `BB_GLASS_PICK_TRI` | TOOL (r86m; goes to the test-tools branch; off by default; read once at the start: it makes the surface probe's world copy available, so a game start is needed). `1`, with `BB_GLASS_PICK`, `BB_GLASS_PICK_PANES` pixels and `BB_RT_GLASS` on (for example `auto`): a pane pixel whose last G-buffer draw has a scene entry takes the triangle route instead of r86l's whole-mesh route (the lantern's glass is flat triangles inside one opaque prop mesh). The entry's world positions (after the palette transform) are copied to a host slot at its next capture (the surface probe's copy, probe slots 12 to 15), the triangle under the pixel seeds a panel of the triangles that share an edge with it and lie in its plane (normals within 10 degrees, every vertex within 1 cm of the seed's plane, corners 1 mm apart are one; at most 512 triangles and 3 m), the panels of all the mesh's pane pixels are joined (45 frames after the last pixel came) and the pane is those triangles only; the mesh's solid entry is replaced by them while it is taken (a skinned, instanced or over 16384 vertices draw is left out). Log: `GLINT-PROOF glass pick (r86m)`: a once line, `triangle route` per pixel, `pane from triangle` (mesh key, tris N, size w x h m, normal, box, what its edges stopped), `pane taken`, a counters line every 600 frames. When the pick is armed the G-buffer's texels (cb0 to cb4, depth) at every pick pixel are read back once and logged (`GLINT-PROOF glass material (r86m)`). Off: a static bool, one unsigned compare in `PrepareDraw`, no state, no lines | off |\n")

EDITS = {
    RTH: [(RTH_FWD_OLD, RTH_FWD_NEW), (RTH_PUB_OLD, RTH_PUB_NEW), (RTH_PRIV_OLD, RTH_PRIV_NEW)],
    RTC: [(RTC_INC_OLD, RTC_INC_NEW), (RTC_MAKE_OLD, RTC_MAKE_NEW), (RTC_SLOT_OLD, RTC_SLOT_NEW),
          (RTC_NEEDS_OLD, RTC_NEEDS_NEW), (RTC_BUILD_OLD, RTC_BUILD_NEW), (RTC_PROBE_OLD, RTC_PROBE_NEW),
          (RTC_END_OLD, RTC_END_NEW), (RTC_FUNCS_OLD, RTC_FUNCS_NEW)],
    RASTH: [(RAH_INC_OLD, RAH_INC_NEW), (RAH_MEM_OLD, RAH_MEM_NEW)],
    EFFECTS: [(EF_ARM_OLD, EF_ARM_NEW), (EF_POLL_OLD, EF_POLL_NEW), (EF_LAST_OLD, EF_LAST_NEW), (EF_TRI_OLD, EF_TRI_NEW),
              (EF_NOTE_OLD, EF_NOTE_NEW), (EF_BLEND_OLD, EF_BLEND_NEW), (EF_COMP_OLD, EF_COMP_NEW),
              (EF_READ_OLD, EF_READ_NEW)],
    TEST: [("#include \"gpu/shadps4/video_core/renderer_vulkan/rt_glass_pick.h\" // bbport (r86l_glint-pick-glass)\n",
            "#include \"gpu/shadps4/video_core/renderer_vulkan/rt_glass_pick.h\" // bbport (r86l_glint-pick-glass)\n"
            "#include \"gpu/shadps4/video_core/renderer_vulkan/rt_glass_tri.h\" // bbport (r86m_glint-pane-from-triangle)\n"),
           ("    std::printf(\"rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n\",\n",
            r'''    { // bbport (r86m_glint-pane-from-triangle): the triangle under a pixel and the flat panel that grows from it
        namespace T = Vulkan::RtGlassTri;
        std::vector<float> world;
        std::vector<std::uint32_t> list;
        const auto quad = [&](const float (&p)[4][3]) {
            const std::uint32_t i = static_cast<std::uint32_t>(world.size() / 4);
            for (const auto& v : p) {
                world.insert(world.end(), {v[0], v[1], v[2], 1.0f});
            }
            list.insert(list.end(), {i, i + 1, i + 2, i, i + 2, i + 3});
        };
        // the glass (triangles 0 and 1); the top and right walls that stand on its edges (2 to 5); a strip tilted 3 degrees
        // on its left edge, 0.5 m long (6 and 7)
        quad({{-0.05f, -0.1f, 0.0f}, {0.05f, -0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {-0.05f, 0.1f, 0.0f}});
        quad({{-0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.05f}, {-0.05f, 0.1f, 0.05f}});
        quad({{0.05f, -0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.05f}, {0.05f, -0.1f, 0.05f}});
        quad({{-0.05f, -0.1f, 0.0f}, {-0.05f, 0.1f, 0.0f}, {-0.549315f, 0.1f, -0.026168f}, {-0.549315f, -0.1f, -0.026168f}});
        const T::Mesh whole{world.data(), static_cast<std::uint32_t>(world.size() / 4), list.data(),
                            static_cast<std::uint32_t>(list.size() / 3)};
        // a camera that looks along +z from 5 m in front of the glass: the view z is z + 5 (proj.w < 0: forward is +z)
        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 5};
        const std::array<float, 4> proj{1.0f, 1.0f, 1.0f, -0.1f};
        // the glass alone: the pixel of the world point (0.03, -0.05) lies in triangle 0, that of (-0.03, 0.05) in 1
        const T::Mesh glass{world.data(), 4, list.data(), 2};
        const T::Hit a = T::FindTriangleAt(glass, view, proj, 965.76f, 534.6f);
        assert(a.found && a.inside && a.tri == 0 && std::fabs(a.depth - 5.0f) < 1.0e-3f);
        const T::Hit b = T::FindTriangleAt(glass, view, proj, 954.24f, 545.4f);
        assert(b.found && b.inside && b.tri == 1);
        // 3 px outside its right edge (x = 969.6): not inside, within the edge tolerance; 6 px outside: none
        const T::Hit c = T::FindTriangleAt(glass, view, proj, 972.6f, 540.0f);
        assert(c.found && !c.inside && c.edge_px > 2.5f && c.edge_px < 3.5f);
        assert(!T::FindTriangleAt(glass, view, proj, 975.6f, 540.0f).found);
        // two triangles over each other: the nearer one (view z 4 against 5)
        const std::vector<float> two{-0.05f, -0.1f, 0.0f,  1.0f, 0.05f, -0.1f, 0.0f,  1.0f, 0.05f, 0.1f, 0.0f,  1.0f,
                                     -0.05f, -0.1f, -1.0f, 1.0f, 0.05f, -0.1f, -1.0f, 1.0f, 0.05f, 0.1f, -1.0f, 1.0f};
        const std::uint32_t two_list[6] = {0, 1, 2, 3, 4, 5};
        const T::Mesh over{two.data(), 6, two_list, 2};
        const T::Hit nearer = T::FindTriangleAt(over, view, proj, 965.76f, 534.6f);
        assert(nearer.found && nearer.inside && nearer.tri == 1);
        // a behind-the-camera mesh and a camera of zeros find nothing
        assert(!T::FindTriangleAt(glass, std::array<float, 12>{}, std::array<float, 4>{}, 960.0f, 540.0f).found);
        // the panel of the glass: its two triangles; the walls stop it by angle (2), the tilted strip by plane (1: its far edge
        // is 2.6 cm off the plane although its normal is within 10 degrees)
        for (std::uint32_t seed = 0; seed < 2; ++seed) {
            const T::Panel panel = T::Grow(whole, seed);
            assert(panel.ok && panel.tris.size() == 2 && panel.tris[0] == 0 && panel.tris[1] == 1);
            assert(panel.by_angle == 2 && panel.by_plane == 1 && panel.degenerate == 0);
            assert(std::fabs(std::fabs(panel.normal[2]) - 1.0f) < 1.0e-4f);
            assert(std::fabs(panel.width - 0.2f) < 2.0e-3f && std::fabs(panel.height - 0.1f) < 2.0e-3f);
            assert(std::fabs(panel.box[0] + 0.05f) < 1.0e-5f && std::fabs(panel.box[3] - 0.05f) < 1.0e-5f);
        }
        // a wall by its triangle count and its width
        T::Rules few;
        few.triangles_most = 1;
        assert(!T::Grow(whole, 0, few).ok);
        T::Rules narrow;
        narrow.metres_most = 0.15f;
        const T::Panel wide = T::Grow(whole, 0, narrow);
        assert(!wide.ok && std::strstr(wide.why, "wider") != nullptr && wide.tris.size() == 2);
        // a seed that is no triangle
        assert(!T::Grow(whole, 99).ok && !T::Grow(T::Mesh{}, 0).ok);
        // the pixels of a want: two in the glass (the second in the panel of the first), one that covers nothing
        T::Want want;
        want.key = 0x1234;
        want.vertices = whole.vertices;
        want.triangles = whole.triangles;
        want.indices = list;
        want.view = view;
        want.proj = proj;
        want.camera_ok = true;
        want.pixels[0] = {965, 534};
        want.pixels[1] = {954, 545};
        want.pixels[2] = {1800, 100};
        want.pixel_count = 3;
        char first[800] = "", last[800] = "";
        int emitted = 0;
        const T::Solved solved = T::Solve(want, world.data(), [&](const char* text) {
            if (emitted++ == 0) {
                std::snprintf(first, sizeof(first), "%s", text);
            }
            std::snprintf(last, sizeof(last), "%s", text);
        });
        assert(emitted == 3 && solved.panels == 1 && solved.same == 1 && solved.missed == 1 && solved.refused == 0);
        assert(solved.keep.size() == 2 && solved.keep[0] == 0 && solved.keep[1] == 1);
        assert(std::strstr(first, "pane from triangle") != nullptr && std::strstr(first, "tris 2,") != nullptr &&
               std::strstr(first, "size 0.200 x 0.100 m") != nullptr && std::strstr(first, "normal") != nullptr &&
               std::strstr(first, "mesh key 0000000000001234") != nullptr && std::strlen(first) < 700);
        assert(std::strstr(last, "no triangle of the mesh covers the pixel") != nullptr);
        char text[1200];
        T::OnceText(text, sizeof(text));
        assert(std::strstr(text, "BB_GLASS_PICK_TRI") != nullptr && std::strlen(text) < 1100);
        T::State state;
        state.asked = 2;
        T::CounterLine(state, 1200, text, sizeof(text));
        assert(std::strstr(text, "2 wants asked") != nullptr && std::strlen(text) < 300);
        static_assert(T::NormalDegrees == 10.0f && T::SlotFirst + T::WantsMost <= 16 && T::PixelsMost == 8);
        assert(std::fabs(T::NormalCosine - std::cos(T::NormalDegrees * 3.14159265f / 180.0f)) < 1.0e-5f);
    }
''' +
            "    std::printf(\"rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n\",\n")],
    README: [(RM_OLD, RM_NEW)],
}

# The tie checks: a value the README row names must be the header's constant.
CHECKS = {
    TRIH: [("inline constexpr float NormalDegrees = 10.0f;", 1), ("inline constexpr float PlaneMetres = 0.01f;", 1),
           ("inline constexpr float WeldMetres = 0.001f;", 1), ("inline constexpr std::uint32_t PanelTrianglesMost = 512;", 1),
           ("inline constexpr float PanelMostMetres = 3.0f;", 1), ("inline constexpr std::uint64_t GatherFrames = 45;", 1),
           ("inline constexpr std::uint32_t SlotFirst = 12;", 1), ("inline constexpr std::uint32_t WantsMost = 4;", 1)],
    README: [("`BB_GLASS_PICK_TRI`", 1), ("normals within 10 degrees", 1), ("every vertex within 1 cm of the seed's plane", 1), ("at most 512 triangles and 3 m", 1),
             ("45 frames after the last pixel", 1), ("1 mm apart", 1), ("probe slots 12 to 15", 1)],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    texts = dict(texts)
    texts[TRIH] = NEW_FILES[TRIH]
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for edits in EDITS.values():
        for old, new in edits:
            if "\r" in new:
                raise SystemExit("new text must have LF only in the script")
    for path, new in list(NEW_FILES.items()) + [(p, n) for p, es in EDITS.items() if p != README for _, n in es]:
        if not all(ord(c) < 128 for c in new):
            raise SystemExit("%s: new text must be ASCII" % path)
        if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
            raise SystemExit("a local path in the patch's text")
    for path, new in NEW_FILES.items():
        if new.count("{") != new.count("}") or new.count("(") != new.count(")"):
            raise SystemExit("%s: braces or parentheses do not balance" % path)
    allnew = NEW_FILES[TRIH] + "".join(n for p, es in EDITS.items() if p != README for _, n in es)
    for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near", " small =", "float small",
                "float small;"):
        if bad in allnew:
            raise SystemExit("the name %r is a macro on some Windows headers" % bad)
    for path, edits in EDITS.items():
        if path == README:
            continue
        for old, new in edits:
            if new.count("{") - old.count("{") != new.count("}") - old.count("}") or \
               new.count("(") - old.count("(") != new.count(")") - old.count(")"):
                raise SystemExit("%s: an edit does not balance its braces or parentheses: %r" % (path, new.split("\n")[0][:70]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R86M_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = todo = 0
        for old, new in edits:
            if cur.count(new) == 1:
                done += 1
            elif cur.count(old) == 1 and cur.count(new) == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once): %r"
                                 % (path, cur.count(old), old.split("\n")[0][:80]))
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits applied" % (path, done, len(edits)))
        plan.append((path, edits, raw, eol, cur, state))
    new_state = []
    for path, content in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            new_state.append("clean")
        elif open(full, "rb").read().decode("utf-8").replace("\r\n", "\n") == content:
            new_state.append("applied")
        else:
            raise SystemExit("REFUSED %s: a file of that name is there and is not this patch's" % path)
    states = {p[5] for p in plan} | set(new_state)
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + "; new files " + str(new_state))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits:
                if cur.count(old) != 1:
                    raise SystemExit("REFUSED %s: anchor not once after the edits before it: %r"
                                     % (path, old.split("\n")[0][:80]))
                cur = cur.replace(old, new)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, edits, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r86mtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, content in NEW_FILES.items():  # new files take the line ends of the tree (CRLF)
            full = os.path.join(ROOT, path)
            tmp = full + ".r86mtmp"
            open(tmp, "wb").write(content.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits):
            if cur.count(new) != 1:
                raise SystemExit("%s: an edit's text is not there once; nothing written" % path)
            cur = cur.replace(new, old)
        for old, new in edits:
            if cur.count(old) != 1 or cur.count(new) != 0:
                raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, edits, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r86mtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
