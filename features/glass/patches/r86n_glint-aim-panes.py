# r86n_glint-aim-panes: TOOL (goes to the test-tools branch, dev/test-tools; never a feature branch or a pull request).
# On top of build 61's tree (r86m_glint-pane-from-triangle.fixed applied, r86l .. r86b, the r83 glass chain).
#
# THE OWNER: "make sure to add those glass and water reflections and caustics apart of the lamp raytracing changes. They
# should receive the same treatment from sun raytracing and other lights not just from the hunter."
#
# WHY (b61, b61_reports.txt): the triangle route works mechanically. The pixel 1348,621 gave mesh e609f2f1518698d0, triangle 773,
# a panel of 2 triangles 1.568 x 0.059 m: a vertical POST left of the lantern, not glass; the glint pass ran with it (pane points
# 63, 56 lamp pairs facing) but the highest N.H was 0.229 at sharpness 32, glint px 0: the right result for a post. The pixels
# 1371,622 and 1370,642 hit mesh 0f2401b04b946e35 (51880 triangles, 78292 vertices): "cannot be copied (a slot holds 16384
# vertices): nothing taken". The lit panes of the lantern lie at x 1392-1398 and x 1420-1432, rows y 617-632 and y 640-655.
#
# WHAT THIS CHANGES (all behind BB_GLASS_PICK_TRI=1, as r86m; nothing is on by default):
#  (1) AIM: the jobs (S/slot_jobs_r86n_glint-aim-panes.json) pick the pixels 1395,624  1395,648  1426,624  1426,648 and the wall
#      control 1600,300 of the dream-house picture (the b61 camera). Each pane pixel logs its mesh key and triangle (r86m's
#      "pane from triangle" line).
#  (2) BIG MESHES: while the knob is on the world copy's slots 12 to 15 (the triangle route's own) hold 131072 vertices each
#      (4 x 2 MiB host memory, made at the first copy; slots 0 to 11 stay 16384 and the buffer is the old 4 MiB when the knob is
#      off: RtShadow::ProbeSlotLimit, ProbeSlotFirst, ProbeWorldVertices). The mesh 0f2401b04b946e35 (78292 vertices) is copied
#      whole (the seed is known only after the copy: the projection finds it), but the panel search then looks only at the
#      NEIGHBOURHOOD of the seed: triangles with every vertex within 0.75 m of the seed's first vertex (Rules::radius); the others
#      are never put in the edge map (a big level mesh costs one scan, counted as "out of the neighbourhood" in the panel line).
#      A mesh above 131072 vertices (the alley prop, 163643) is still refused with the line r86m had (that place must do nothing).
#  (3) JUDGE THE PANE: a panel longer than 0.6 m or narrower than 0.05 m is refused ("longer than 0.6 m: a post or a frame, not
#      glass", "narrower than 0.05 m: a post or a rail, not glass"); before the panel is grown a "seed triangle (r86n)" line logs
#      the seed's edges, area and normal and the sizes of the triangles around it (count within 0.75 m, longest edge in 5 bins,
#      how many are coplanar with the seed whether connected or not).
#  (4) LAMP TERMS: the first glint pass after a pane is cut logs, per pane and per lamp (view space, CPU side from the pass's own
#      lamp list and camera, using glass_glint.h's Term: no shader change): distance, N.L, N.H, the half vector's angle off the
#      normal, the term, the term x colour x strength, the term at a perfect N.H of 1, and a verdict: fires | N.H too low (needs
#      about X) | can never fire for this lamp (even N.H 1 stays under 1/255) | behind the pane | out of reach. The pane's centre
#      and normal stand for its points (a pane is a few cm to 0.6 m). Sharpness 32 stays.
#  (5) PAINTED OR EMISSIVE: when no panel could be cut from any pixel of a mesh, a "NO PANE CUT" line says so plainly (the panes
#      are then not separate flat glass triangles of that mesh: emissive or painted texture on the body, or the glass is another
#      mesh) and the seed lines above it hold the triangle sizes for the lead's decision.
#  (6) JOBS (3): dream house one game (off, live on, show, unset), the knob-off twin, the dark alley (must do nothing).
#
# OFF (default): BB_GLASS_PICK_TRI unset. RtGlassTri::On() is r86m's static bool (false). The new code is: header functions that
# only run from RtGlassTri::Solve / the registry (reached only from GlassTriFrameEnd, which runs only when glass_tri exists, i.e.
# after GlassTriWant made it: knob on); ProbeSlotLimit/ProbeSlotFirst/ProbeWorldVertices compare the static bool and give the old
# numbers when it is false (the probe's buffer is the old size and layout, byte for byte the same offsets); the glint hook is one
# call of RtGlassTri::LampLinesPending() (static bool and a counter that stays 0: nothing else is read) once a pass. No shader,
# no pipeline key, no allocation, no log line.
# ON: 8 MiB more host memory (slots 12 to 15 at 131072 vertices; the buffer 11 MiB instead of 4), one CPU scan of the mesh
# (a few ms once), 4 floats of arithmetic a lamp once a pane is cut.
#
# SHARED LINES TOUCHED: NO pick line (GlassPickGroup, GlassPickPoll, WindTreesPickFrameEnd, the pick query pool, the
# trees_pick_draw gates stay as r86l/r86m left them). vk_glass_glint.cpp: one include and one block after "stats.lamps +=
# picked.count;" in AfterGlassDraw (glass code). vk_rt_shadow.cpp: GlassTriWant (one line after the once line), GlassTriCopy (two
# limit terms), GlassTriFrameEnd (one loop after w.keep = ...), the probe's copy offset and limit in RecordBuilds (two terms),
# ProbeCopyBuild (buffer size and limit: two terms), three small functions after ProbeWanted. vk_rt_shadow.h: three declarations
# and the ProbeWorld offset. rt_glass_tri.h, README.md (rows), tests/test_rt_glass.cpp.
#
# NOT VERIFIED (nothing was built or run; rule: no clang++): see the final report: the C++ spots a compiler could reject.
#
# Files: rt_glass_tri.h, vk_rt_shadow.h, vk_rt_shadow.cpp, vk_glass_glint.cpp, README.md, tests/test_rt_glass.cpp (all edited).
# Use: python -I -X utf8 r86n_glint-aim-panes.py check | apply | revert
# Root: R86N_ROOT else <tree>. Line ends kept per file. Backups in r86n_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86n_backup")
ROOT = os.environ.get("R86N_ROOT") or "<tree>"
G = "engine/gpu/"
V = G + "shadps4/video_core/renderer_vulkan/"
TRIH = V + "rt_glass_tri.h"
RTH = V + "vk_rt_shadow.h"
RTC = V + "vk_rt_shadow.cpp"
GLINT = V + "vk_glass_glint.cpp"
TEST = "engine/tests/test_rt_glass.cpp"
README = "README.md"

NEW_FILES = {}

EDITS = {}

# ---------------------------------------------------------------- rt_glass_tri.h
EDITS[TRIH] = [
    # constants
    (r'''inline constexpr std::uint32_t WantsMost = 4;''',
     r'''inline constexpr float RadiusMetres = 0.75f;        ///< r86n: only triangles with every vertex this near the seed's first vertex are looked at
inline constexpr float PaneLongestMetres = 0.6f;    ///< r86n: a panel longer than this is a post, a frame or a wall, not a pane
inline constexpr float PaneNarrowestMetres = 0.05f; ///< r86n: a panel narrower than this is a post or a rail, not glass
inline constexpr std::uint32_t PanesMost = 8;       ///< r86n: panes the lamp-term log remembers
inline constexpr std::uint32_t LampLinePasses = 1;  ///< r86n: glint passes (after a pane is cut) that log the lamp terms
inline constexpr std::uint32_t WantsMost = 4;'''),
    # rules
    (r'''    float metres_most = PanelMostMetres;
};''',
     r'''    float metres_most = PanelMostMetres;
    float radius = RadiusMetres;                  ///< r86n: 0 looks at the whole mesh
    float longest_metres = PaneLongestMetres;     ///< r86n: 0 judges nothing
    float narrowest_metres = PaneNarrowestMetres; ///< r86n: 0 judges nothing
};'''),
    # panel counter
    (r'''    std::uint32_t by_angle = 0, by_plane = 0, degenerate = 0;''',
     r'''    std::uint32_t by_far = 0; ///< r86n: triangles of the mesh outside the neighbourhood radius (never looked at)
    std::uint32_t by_angle = 0, by_plane = 0, degenerate = 0;'''),
    # survey + helper before Grow
    (r'''[[nodiscard]] inline Panel Grow(const Mesh& m, std::uint32_t seed, const Rules& rules = {}) {''',
     r'''/// r86n: every vertex of triangle `t` within `radius` of `centre`.
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

[[nodiscard]] inline Panel Grow(const Mesh& m, std::uint32_t seed, const Rules& rules = {}) {'''),
    # far triangles
    (r'''        const std::uint32_t i0 = m.indices[std::size_t(t) * 3], i1 = m.indices[std::size_t(t) * 3 + 1],''',
     r'''        if (rules.radius > 0.0f && !AllWithin(m, t, origin, rules.radius)) {
            bad[t] = 2; // r86n: outside the neighbourhood of the seed: never put in the edge map
            ++out.by_far; // counted here: a far triangle is in no edge list, so it never comes up as a neighbour
            continue;
        }
        const std::uint32_t i0 = m.indices[std::size_t(t) * 3], i1 = m.indices[std::size_t(t) * 3 + 1],'''),
    (r'''    if (bad[seed] != 0) {
        out.why = "the seed triangle is degenerate";''',
     r'''    if (bad[seed] != 0) {
        out.why = bad[seed] == 2 ? "the seed triangle has a vertex farther than 0.75 m from its first: a wall or a floor, not a pane"
                                 : "the seed triangle is degenerate";'''),
    (r'''    out.ok = true;
    out.why = "taken";''',
     r'''    if (rules.longest_metres > 0.0f && out.width > rules.longest_metres) {
        out.why = "longer than 0.6 m: a post or a frame, not glass";
        return out;
    }
    if (rules.narrowest_metres > 0.0f && out.height < rules.narrowest_metres) {
        out.why = "narrower than 0.05 m: a post or a rail, not glass";
        return out;
    }
    out.ok = true;
    out.why = "taken";'''),
    # panel line: the new counter
    (r'''%u by angle, %u by plane, %u degenerate",''',
     r'''%u by angle, %u by plane, %u degenerate, %u out of the neighbourhood",'''),
    (r'''pa.by_plane, pa.degenerate);''',
     r'''pa.by_plane, pa.degenerate, pa.by_far);'''),
    # registry, lamp terms, before Solved
    (r'''struct Solved {''',
     r'''/// r86n: a pane that was cut (world centre, normal, size): the first glint pass after it logs each lamp's N.H and term for it.
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
    std::vector<PaneInfo> panes; ///< r86n: one a usable panel'''),
    # seed line before the panel is grown
    (r'''        const Panel pa = Grow(m, h.tri);''',
     r'''        const Around around = Survey(m, h.tri);
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
        const Panel pa = Grow(m, h.tri);'''),
    (r'''        ++out.panels;
        std::vector<std::uint32_t> merged;''',
     r'''        ++out.panels;
        out.panes.push_back({w.key,
                             {(pa.box[0] + pa.box[3]) * 0.5f, (pa.box[1] + pa.box[4]) * 0.5f, (pa.box[2] + pa.box[5]) * 0.5f},
                             pa.normal, pa.width, pa.height});
        std::vector<std::uint32_t> merged;'''),
    # verdict + the second once text, before OnceText
    (r'''    return out;
}

inline void OnceText(char* out, std::size_t size) {''',
     r'''    if (out.panels == 0 && w.pixel_count > 0) {
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

inline void OnceText(char* out, std::size_t size) {'''),
    (r'''inline constexpr std::uint32_t SlotFirst = 12;''',
     r'''inline constexpr std::uint32_t SlotVertices = 131072; ///< r86n: vertices a slot of this tool holds (RtShadow::ProbeBigSlotVertices)
inline constexpr std::uint32_t SlotFirst = 12;'''),
]

# ---------------------------------------------------------------- vk_rt_shadow.h
EDITS[RTH] = [
    (r'''    static constexpr u32 ProbeSlotVertices = 16384;''',
     r'''    static constexpr u32 ProbeSlotVertices = 16384;
    // bbport (r86n_glint-aim-panes, TOOL): with BB_GLASS_PICK_TRI=1 the slots from ProbeSlotsSmall up (the triangle route's)
    // hold ProbeBigSlotVertices vertices each; without it every slot holds ProbeSlotVertices as before.
    static constexpr u32 ProbeSlotsSmall = 12;
    static constexpr u32 ProbeBigSlotVertices = 131072;
    [[nodiscard]] static u32 ProbeSlotLimit(u32 slot);
    [[nodiscard]] static std::size_t ProbeSlotFirst(u32 slot);
    [[nodiscard]] static std::size_t ProbeWorldVertices();'''),
    (r'''std::size_t(slot) * ProbeSlotVertices * 4''',
     r'''ProbeSlotFirst(slot) * 4'''),
]

# ---------------------------------------------------------------- vk_rt_shadow.cpp
EDITS[RTC] = [
    (r'''        std::printf("%s\n", once);
    }
    RtGlassTri::Want* want = nullptr;''',
     r'''        std::printf("%s\n", once);
        RtGlassTri::OnceTextAim(once, sizeof(once)); // bbport (r86n_glint-aim-panes, TOOL)
        std::printf("%s\n", once);
    }
    RtGlassTri::Want* want = nullptr;'''),
    (r'''            u64(entry.vertices) * entry.instances > ProbeSlotVertices) {''',
     r'''            u64(entry.vertices) * entry.instances > ProbeSlotLimit(RtGlassTri::SlotFirst + i)) {'''),
    (r'''                        ProbeSlotVertices);
            continue;''',
     r'''                        ProbeSlotLimit(RtGlassTri::SlotFirst + i));
            continue;'''),
    (r'''        w.keep = solved.keep;
        w.stage = 3;''',
     r'''        for (const RtGlassTri::PaneInfo& pane : solved.panes) { // bbport (r86n_glint-aim-panes, TOOL): for the glint pass's lamp log
            RtGlassTri::AddPane(pane);
        }
        w.keep = solved.keep;
        w.stage = 3;'''),
    (r'''            if (probe_world.buffer && world_bytes <= vk::DeviceSize(ProbeSlotVertices) * 16) {''',
     r'''            if (probe_world.buffer && world_bytes <= vk::DeviceSize(ProbeSlotLimit(build.probe_slot - 1)) * 16) {'''),
    (r'''                                    u64(build.probe_slot - 1) * ProbeSlotVertices * 16,''',
     r'''                                    u64(ProbeSlotFirst(build.probe_slot - 1)) * 16,'''),
    (r'''        u64(b.entry->vertices) * b.entry->instances > ProbeSlotVertices) {''',
     r'''        u64(b.entry->vertices) * b.entry->instances > ProbeSlotLimit(slot)) {'''),
    (r'''            .size = VkDeviceSize(ProbeSlots) * ProbeSlotVertices * 16,''',
     r'''            .size = VkDeviceSize(ProbeWorldVertices()) * 16,'''),
    (r'''    return (value && value[0] == '1' && value[1] == '\0') || RtGlassTri::On(); // bbport (r86m): its world copy
}''',
     r'''    return (value && value[0] == '1' && value[1] == '\0') || RtGlassTri::On(); // bbport (r86m): its world copy
}

// bbport (r86n_glint-aim-panes, TOOL): the slots' sizes. Knob off: every slot holds ProbeSlotVertices, in a row (the old layout).
// Knob on: the slots from ProbeSlotsSmall up hold ProbeBigSlotVertices each (the triangle route's: a big level mesh is copied whole).
u32 RtShadow::ProbeSlotLimit(u32 slot) {
    return RtGlassTri::On() && slot >= ProbeSlotsSmall ? ProbeBigSlotVertices : ProbeSlotVertices;
}

std::size_t RtShadow::ProbeSlotFirst(u32 slot) {
    if (!RtGlassTri::On() || slot <= ProbeSlotsSmall) {
        return std::size_t(slot) * ProbeSlotVertices;
    }
    return std::size_t(ProbeSlotsSmall) * ProbeSlotVertices + std::size_t(slot - ProbeSlotsSmall) * ProbeBigSlotVertices;
}

static_assert(RtShadow::ProbeBigSlotVertices == RtGlassTri::SlotVertices);

std::size_t RtShadow::ProbeWorldVertices() {
    return ProbeSlotFirst(ProbeSlots - 1) + ProbeSlotLimit(ProbeSlots - 1);
}'''),
]

# ---------------------------------------------------------------- vk_glass_glint.cpp
EDITS[GLINT] = [
    (r'''#include "video_core/renderer_vulkan/rt_glass_light.h"''',
     r'''#include "video_core/renderer_vulkan/rt_glass_light.h"
#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86n_glint-aim-panes, TOOL)'''),
    (r'''    stats.lamps += picked.count;
''',
     r'''    stats.lamps += picked.count;
    if (RtGlassTri::LampLinesPending()) { // bbport (r86n_glint-aim-panes, TOOL): N.H and the term of every lamp for the pane just cut
        std::array<RtGlassTri::LampIn, ::BbGlassGlint::MaxLamps> in{};
        for (u32 k = 0; k < picked.count; ++k) {
            const BG::Lamp& lamp = picked.lamps[k];
            in[k] = {lamp.view[0], lamp.view[1], lamp.view[2], lamp.reach,
                     std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]})};
        }
        RtGlassTri::NoteLampTerms(camera.view, in.data(), picked.count, float(knobs.sharp), live < 0.0f ? -live : live,
                                  [](float d, float reach, float nl, float nh, float vh, float n) {
                                      return BG::Term(d, reach, nl, nh, vh, n);
                                  });
    }
'''),
]

# ---------------------------------------------------------------- tests/test_rt_glass.cpp
EDITS[TEST] = [
    (r'''            if (emitted++ == 0) {
                std::snprintf(first, sizeof(first), "%s", text);
            }''',
     r'''            ++emitted; // r86n: the seed line comes before the panel's own line
            if (first[0] == 0 && std::strstr(text, "pane from triangle") != nullptr) {
                std::snprintf(first, sizeof(first), "%s", text);
            }'''),
    (r'''        assert(emitted == 3 && solved.panels == 1''',
     r'''        assert(emitted == 4 && solved.panels == 1'''),
    (r'''        assert(std::fabs(T::NormalCosine - std::cos(T::NormalDegrees * 3.14159265f / 180.0f)) < 1.0e-5f);
    }''',
     r'''        assert(std::fabs(T::NormalCosine - std::cos(T::NormalDegrees * 3.14159265f / 180.0f)) < 1.0e-5f);
        { // bbport (r86n_glint-aim-panes): the survey of the seed, the size rules, the neighbourhood and the lamp terms
            const T::Around around = T::Survey(whole, 0);
            assert(around.tris == 8 && around.coplanar == 2 && std::fabs(around.seed_longest - 0.2236f) < 1.0e-3f &&
                   std::fabs(around.seed_shortest - 0.1f) < 1.0e-4f && std::fabs(around.seed_area - 0.01f) < 1.0e-4f);
            assert(around.bins[0] == 0 && around.bins[2] + around.bins[1] + around.bins[3] == 8);
            // a plate 0.04 x 0.5 m (a post), one 0.1 x 0.7 m (a frame), a quad 1 x 1 m (outside the neighbourhood)
            const std::uint32_t plate_list[6] = {0, 1, 2, 0, 2, 3};
            const std::vector<float> post{0, 0, 0, 1, 0.04f, 0, 0, 1, 0.04f, 0.5f, 0, 1, 0, 0.5f, 0, 1};
            const T::Mesh post_mesh{post.data(), 4, plate_list, 2};
            const T::Panel post_panel = T::Grow(post_mesh, 0);
            assert(!post_panel.ok && std::strstr(post_panel.why, "narrower than 0.05") != nullptr && post_panel.tris.size() == 2);
            const std::vector<float> frame{0, 0, 0, 1, 0.1f, 0, 0, 1, 0.1f, 0.7f, 0, 1, 0, 0.7f, 0, 1};
            const T::Mesh frame_mesh{frame.data(), 4, plate_list, 2};
            const T::Panel frame_panel = T::Grow(frame_mesh, 0);
            assert(!frame_panel.ok && std::strstr(frame_panel.why, "longer than 0.6") != nullptr);
            T::Rules judged_off;
            judged_off.longest_metres = 0.0f;
            judged_off.narrowest_metres = 0.0f;
            assert(T::Grow(frame_mesh, 0, judged_off).ok && T::Grow(post_mesh, 0, judged_off).ok);
            const std::vector<float> wall{0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1};
            const T::Mesh wall_mesh{wall.data(), 4, plate_list, 2};
            const T::Panel wall_panel = T::Grow(wall_mesh, 0);
            assert(!wall_panel.ok && std::strstr(wall_panel.why, "0.75 m") != nullptr);
            T::Rules whole_mesh;
            whole_mesh.radius = 0.0f;
            whole_mesh.longest_metres = 0.0f;
            assert(T::Grow(wall_mesh, 0, whole_mesh).ok);
            // a mesh with a far triangle: the neighbour is counted as out of the neighbourhood
            std::vector<float> two_part = world;
            std::vector<std::uint32_t> two_list = list;
            const std::uint32_t base = static_cast<std::uint32_t>(two_part.size() / 4);
            two_part.insert(two_part.end(), {5.0f, 5.0f, 0.0f, 1.0f, 6.0f, 5.0f, 0.0f, 1.0f, 6.0f, 6.0f, 0.0f, 1.0f});
            two_list.insert(two_list.end(), {base, base + 1, base + 2});
            const T::Mesh two_mesh{two_part.data(), static_cast<std::uint32_t>(two_part.size() / 4), two_list.data(),
                                   static_cast<std::uint32_t>(two_list.size() / 3)};
            assert(T::Survey(two_mesh, 0).tris == 8);
            // the lamp terms: a pane 2 m in front of the camera facing it, one lamp beside the camera, one far away
            T::Panes() = T::Registry{};
            T::AddPane({0x77, {0.0f, 0.0f, 2.0f}, {0.0f, 0.0f, -1.0f}, 0.2f, 0.1f});
            assert(T::Panes().count == 1 && T::Panes().lines_left == T::LampLinePasses);
            const std::array<T::LampIn, 2> lamps{T::LampIn{0.5f, 0.0f, 0.0f, 6.0f, 1.0f}, T::LampIn{0.0f, 0.0f, 30.0f, 6.0f, 1.0f}};
            const std::array<float, 12> eye{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
            int asked = 0;
            T::NoteLampTerms(eye, lamps.data(), 2, 32.0f, 1.0f, [&](float d, float reach, float nl, float nh, float, float n) {
                ++asked;
                return d < reach && nl > 0.0f ? std::pow(nh, n) : 0.0f;
            });
            assert(asked == 4 && T::Panes().lines_left == 0);
            T::NoteLampTerms(eye, lamps.data(), 2, 32.0f, 1.0f, [&](float, float, float, float, float, float) { ++asked; return 0.0f; });
            assert(asked == 4); // no pass left to count down
            T::Panes() = T::Registry{};
            assert(!T::LampLinesPending());
            char text2[800];
            T::OnceTextAim(text2, sizeof(text2));
            assert(std::strstr(text2, "r86n") != nullptr && std::strlen(text2) < 600);
        }
    }'''),
]

# ---------------------------------------------------------------- README.md
EDITS[README] = [
    (r'''(a skinned, instanced or over 16384 vertices draw is left out)''',
     r'''(a skinned, instanced or over 131072 vertices draw is left out)'''),
    (r'''(`GLINT-PROOF glass material (r86m)`). Off: a static bool''',
     r'''(`GLINT-PROOF glass material (r86m)`). r86n: only the triangles with every vertex within 0.75 m of the seed's first vertex are looked at (the others count as out of the neighbourhood), so a mesh of up to 131072 vertices is copied whole (while the knob is on the probe slots 12 to 15 hold 131072 vertices each: 8 MiB more host memory); a panel longer than 0.6 m or narrower than 0.05 m is refused as a post, frame or wall; a `seed triangle (r86n)` line per pixel logs the seed's edges, area and normal and the sizes of the triangles around it, and a `NO PANE CUT` line says when no flat panel exists near a mesh's pixels (the panes are then painted or emissive texture, or in another mesh); the first glint pass after a pane is cut logs per lamp N.H, the half vector's angle, the term and a verdict (`glass glint (r86n)`). Off: a static bool'''),
]

CHECKS = {
    TRIH: [("inline constexpr float RadiusMetres = 0.75f;", 1), ("inline constexpr float PaneLongestMetres = 0.6f;", 1),
           ("inline constexpr float PaneNarrowestMetres = 0.05f;", 1), ("inline constexpr std::uint32_t SlotVertices = 131072;", 1),
           ("inline constexpr std::uint32_t WantsMost = 4;", 1), ("inline constexpr std::uint32_t LampLinePasses = 1;", 1),
           ('"longer than 0.6 m: a post or a frame, not glass"', 1), ('"narrower than 0.05 m: a post or a rail, not glass"', 1)],
    RTH: [("static constexpr u32 ProbeBigSlotVertices = 131072;", 1), ("static constexpr u32 ProbeSlotsSmall = 12;", 1)],
    README: [("within 0.75 m of the seed's first vertex", 1), ("longer than 0.6 m or narrower than 0.05 m", 1),
             ("up to 131072 vertices", 1), ("hold 131072 vertices each", 1)],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    texts = dict(texts)
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for edits in EDITS.values():
        for old, new in edits:
            if "\r" in new:
                raise SystemExit("new text must have LF only in the script")
    for path, edits in EDITS.items():
        if path == README:
            continue
        for old, new in edits:
            if not all(ord(c) < 128 for c in new):
                raise SystemExit("%s: new text must be ASCII: %r" % (path, new.split("\n")[0][:70]))
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")
            if new.count("{") - old.count("{") != new.count("}") - old.count("}") or \
               new.count("(") - old.count("(") != new.count(")") - old.count(")"):
                raise SystemExit("%s: an edit does not balance its braces or parentheses: %r" % (path, new.split("\n")[0][:70]))
    allnew = "".join(n for p, es in EDITS.items() if p != README for _, n in es)
    for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near", " small =", "float small",
                "float small;"):
        if bad in allnew:
            raise SystemExit("the name %r is a macro on some Windows headers" % bad)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R86N_ROOT)" % ROOT)
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
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), its new text %d times: %r"
                                 % (path, cur.count(old), cur.count(new), old.split("\n")[0][:80]))
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits applied" % (path, done, len(edits)))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
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
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
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
            tmp = full + ".r86ntmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
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
        tmp = full + ".r86ntmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
