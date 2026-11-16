# r86l_glint-pick-glass: TOOL (goes to the test-tools branch, dev/test-tools; never a feature branch or a pull request).
# On top of build 57's tree (r89k_twigs-opaque-word and r112l_hang-discard-lanterns applied) and r86k_glint-box-gbuffer, r86j .. r86b, r83.
#
# THE OWNER: "make sure to add those glass and water reflections and caustics apart of the lamp raytracing changes. They
# should receive the same treatment from sun raytracing and other lights not just from the hunter."
#
# WHY (b54 + b55g re-aim, logs b54_s5.log, b55g_s1.log pots box, b55g_s2.log table lantern box): the box camera is fixed
# ("committed camera is used") but the scene entry list never holds the glass. The lantern box 1225:495:1295:675 (the glass
# table lantern by the bookshelf, lit, panes clearly visible) lists 2 entries: a bogus 9da6aacb:bb10e440 box 12 x 469 x 10 m and
# the room. The pots box lists metal and ceramic pots. Glint lines: 0 pane draws asked, 0 passes, glint px 0. The r86i area table
# of the same logs has "3deaa573:2140da2b G-buffer: 2.0 draws a frame, indices 792-3000 | blend nozwrite ztest discard textured
# capture": a BLENDED G-buffer draw without depth write, which PrepareDraw leaves out (not solid) and no entry list can show.
# Nobody has looked at WHICH draw makes the pane pixels. This patch does.
#
# WHAT THIS ADDS (all behind BB_GLASS_PICK, a TEST path; off costs nothing, see below):
#  (1) THE PICK (BB_GLASS_PICK="x:y;x:y", pixels of a 1920x1080 picture; read live where the test tools' knobs file exists, so a
#      job's set:/unset: arms and drops it in a running game, else once from the environment). It REUSES r89j/r89k's pixel
#      pick (BB_WIND_TWIGS_PICK: an occlusion query a draw, the draws narrowed to a 5x5 patch for 2 frames a pixel, the groups read
#      when the GPU is through, query pool, group ring, scissor patch and note line all unchanged). Generalised: (a) the pick's
#      knob can be the glass pick's (bbport_wind_trees.h: PickCurrent, PickOn, PickKnob::glass, GlassPickLive; the twig knob
#      works as before when the glass pick is not armed); (b) the draws it takes are not only the G-buffer's: with the glass pick
#      armed the forward draws of the scene (scene_started, a depth target that is not a sun shadow pass, colour write, depth
#      test only) are narrowed and measured too (vk_rasterizer.cpp: trees_pick_draw, set once a draw in PrepareRenderState and read
#      where r89j read gbuffer_draw: the query site and the scissor site); (c) PickDraw carries the facts of the draw.
#      The report lists EVERY draw that passed the depth test in the patch (not one winner): the last 8, in draw order, one line
#      each, "GLINT-PROOF glass pick (r86l): pixel x,y draw k of n, S samples: G-buffer|forward, blend, zwrite, ztest, discard,
#      textured, T targets, vs:ps, indices (first, base) x instances, static|GPU palette|skeleton|no motion block [, bone palette],
#      capture pipeline and camera constants, stream, mesh key | in scene: NO ENTRY | N entries, PANE|solid, tris, verts, box with
#      its source" and the indices' span and distinct use. The mesh key is the position key RtShadow::PrepareDraw keys entries by.
#      Pixels to use (framing slot_gbx-pots_off0.jpg, 1920x1080): lantern panes 1255:560 and 1240:620, lantern flame 1262:600,
#      shelf bottle 12:470, wall 1600:300 (control).
#  (2) PANES FROM THE PICK (BB_GLASS_PICK_PANES: "1" every pick pixel is a pane pixel, "2" the same and every small draw there is
#      taken, "x:y;x:y" only those pixels; needs BB_RT_GLASS on, for example auto). A draw with samples at a pane pixel is taken
#      when it is not skinned, has 24 to 3000 indices and (mode 1) is a forward draw, blended, cut out or writes no depth.
#      A G-buffer draw is taken BY ITS MESH KEY (RtShadow::GlassPickTake: the box rule's own route, GlassBoxMatch is true for it;
#      a table of 32 keys apart from the box's, which a live knob change would clear): its next draws are made pane records by
#      the r86i/r86k chain (Draw::glass: solid and whole, its own capture of ITS OWN VERTICES, RtGlassMask alone: no sun or lamp
#      caster is added). The scene entry's still box (the "bad palette bounds") is not used to take it: the key is. A forward
#      draw is taken BY ITS SHADER PAIR (rt_glass.h: RtGlassPickAdd, a 16-pair table of relaxed atomics that RtGlassMatch reads
#      after the knob's list): its pipeline gets the capture variant at its next draw like a listed pair, and every draw of the
#      pair is a pane (pair level, because a forward draw has no entry yet to take by key). Log: "pane from pick: pixel, vs:ps, key,
#      indices, pass, state: taken - <how>", or "not taken: <reason>" for a draw that was a candidate and was refused.
#  (3) THE GLINT CHAIN in ONE dream-house game: the jobs (slot_jobs_r86l_glint-pick-glass.json) take off0, arm the pick and the
#      panes live, drop the pick, then glint 1, show, glint 0 in the same game and camera. The existing GLINT-PROOF chain lines
#      (chain at frame: G-buffer draws of taken meshes, pane record made or not, glint noted ...; gate; glint: passes, pane points,
#      glass px, lamp pairs, glint px) follow the panes this patch takes.
#  (4) THE 469 m BOUND, one line (not fixed: it is outside the glass code, RtShadow::MakeEntry / rt_still_sig.comp). In the b55g_s1
#      line "9da6aacb:bb10e440 ... 469.50 m (12.43 x 469.22 x 10.60) ... 904 triangles 2852 vertices ... 2712 indices": 904
#      triangles use at most 2712 vertices, the entry holds 2852: AT LEAST 140 vertices of the captured range lo..hi are used by no
#      triangle. MakeEntry captures every vertex lo..hi of the draw's index range (vertex_count = hi - lo + 1), the capture vertex
#      shader transforms all of them with THIS draw's matrices, and the still box is measured over all of them: a vertex that is
#      another mesh of the shared stream lands anywhere, so the box is tall; the triangles (and so the BLAS) are right. The pick
#      prints "bound cause" for every listed scene entry whose box is over 100 m across, with the index list's real span and the
#      number of distinct vertices it uses, which proves or refutes this on the next run.
#
# OFF (default): BB_GLASS_PICK unset: nothing is armed. Per frame: RtShadow::GlassPickRead compares one generation (a relaxed load)
# and the poll returns; PickOn() reads one more relaxed atomic (false); a draw sets trees_pick_draw = trees_pick_rect_on && ...
# (a false member, the rest not read); EffectsCaptureDraw tests the bool trees_pick_glass; RtGlassMatch reads one more atomic count
# (0) and only with BB_RT_GLASS on. No shader, no pipeline key (the pair table is read by RtGlassMatch: empty while no pane
# is picked), no cache version, no allocation changes. BB_WIND_TWIGS_PICK behaves as in r89k when BB_GLASS_PICK is not armed.
# ARMED: a query a draw in the pick's frames (at most 4096 a group, 4 groups, the twig pick's pool) and 2 frames a pixel; at most
# 8 pixels x 2 frames of broken pictures (the delay before the first pixel draws normally); the report reads the index list of
# each listed draw that has a scene entry (at most 8 a pixel, any length the draw has) from guest memory; log lines of at most
# 700 characters (8 draws + a header a pixel). Memory: a few KiB of keys, counters and texts, no GPU memory.
# CAVEAT: BB_GLASS_PICK_PANES=2 takes opaque G-buffer draws too; such a draw becomes a pane INSTEAD of the solid entry the
# ray traced scene had of that mesh (the capture hook routes the draw as a pane, the same as r86i's box panes): use it to look,
# not to judge the lamp and sun shadows of the scene. Mode 1 takes mostly draws PrepareDraw gave no entry (blended, no depth write,
# a cut-out without a skeleton or bone palette); a cut-out with a bone palette had one and loses it the same way.
#
# SHARED LINES TOUCHED: the twig pick's (r89j/r89k) in vk_rasterizer.cpp (the two gates `trees_pick_rect_on && gbuffer_draw` become
# `trees_pick_draw`), vk_rasterizer_effects.cpp (WindTreesPickQuery: a block before its last three lines; WindTreesPickFrameEnd: the
# knob line, the head of the group loop, one poll call), bbport_wind_trees.h (PickOn, PickKnob, PickDraw, an include). The G-buffer-only
# behaviour of the twig pick is unchanged while BB_GLASS_PICK is not armed. rt_glass.h: RtGlassMatch (one more atomic read).
# vk_rt_shadow.cpp: GlassBoxMatch / GlassBoxCandidate (a second key table). README.md: two rows before the BB_GLASS_FIND row.
#
# NOT VERIFIED (nothing was built or run; rule: no clang++): see the final report: the C++ spots a compiler could reject.
#
# Files: rt_glass.h, rt_glass_pick.h (new), vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer.h, vk_rasterizer.cpp,
# vk_rasterizer_effects.cpp, bbport_wind_trees.h, README.md, tests/test_rt_glass.cpp.
# Use: python -I -X utf8 r86l_glint-pick-glass.py check | apply | revert
# Root: R86L_ROOT else <tree>. Line ends kept per file (the new file takes CRLF). Backups in r86l_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86l_backup")
ROOT = os.environ.get("R86L_ROOT") or "<tree>"
G = "engine/gpu/"
V = G + "shadps4/video_core/renderer_vulkan/"
TREES = G + "shim/bbport_wind_trees.h"
GLASS = V + "rt_glass.h"
PICKH = V + "rt_glass_pick.h"
RTH = V + "vk_rt_shadow.h"
RTC = V + "vk_rt_shadow.cpp"
RASTH = V + "vk_rasterizer.h"
RAST = V + "vk_rasterizer.cpp"
EFFECTS = V + "vk_rasterizer_effects.cpp"
TEST = "engine/tests/test_rt_glass.cpp"
README = "README.md"

NEW_FILES = {
    PICKH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86l_glint-pick-glass, TOOL; goes to the test-tools branch): the glass pick. BB_GLASS_PICK="x:y;x:y;..." (output
// pixels of a 1920x1080 picture, at most B::PickMost; "x,y" reads too) names EVERY draw of the camera pass that passed the
// depth test in a 5x5 patch around each pixel: the G-buffer draws and the forward draws of the scene (colour write, depth
// test only), blended or not, with or without depth write. It reuses the twig pick's mechanism (BB_WIND_TWIGS_PICK in
// bbport_wind_trees.h: an occlusion query a draw, the draws narrowed to the patch in the pick's frames, the groups read
// when the GPU is through): the one change there is the knob (BbWindTrees::PickCurrent / PickOn, armed live).
//
//   BB_GLASS_PICK          the pixels. Read live where the test tools' knobs file exists (a job's set: / unset:), else
//                          once from the environment. Unset or empty: no pick (the picture is whole again).
//   BB_GLASS_PICK_SIZE     WxH of the picture the pixels are read from (default 1920x1080).
//   BB_GLASS_PICK_FRAME    frames from arming to the first pixel (default 30: the camera settles after a live set).
//   BB_GLASS_PICK_REPEAT   the sweep starts again every this many frames (at least a sweep; default once).
//   BB_GLASS_PICK_PANES    "1": every pick pixel is a pane pixel; "2": the same, and every small draw there is taken (not
//                          only the glass-like ones); "x:y;x:y": only these pixels (they should be pick pixels too).
//                          A draw with samples at a pane pixel is taken as a pane when it is not skinned, has 24 to 3000
//                          indices and (mode 1) is a forward draw, blended, cut out or writes no depth. A G-buffer draw
//                          is taken by its mesh key (RtShadow::GlassPickTake: the box rule's route, a pane record at its
//                          next draw, made from the draw's own vertices: no entry bound is used), a forward draw by its
//                          shader pair (RtGlassPickAdd: its pipeline gets the capture variant at the next draw, and every
//                          draw of the pair is a pane). BB_RT_GLASS must be on (for example "auto").
// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "../../../shim/bbport_wind_trees.h"
#include "rt_glass.h"

namespace Vulkan::RtGlassPick {

namespace B = BbWindTrees;

// The facts of a pick draw (B::PickDraw::glass_flags).
inline constexpr std::uint32_t FlagGBuffer = 1u << 0;     ///< a G-buffer draw (5 and more colour targets); else forward
inline constexpr std::uint32_t FlagBlend = 1u << 1;       ///< blended on colour target 0
inline constexpr std::uint32_t FlagZWrite = 1u << 2;
inline constexpr std::uint32_t FlagZTest = 1u << 3;
inline constexpr std::uint32_t FlagTextured = 1u << 4;
inline constexpr std::uint32_t FlagCapture = 1u << 5;     ///< a capture pipeline: the ray traced scene may take the draw
inline constexpr std::uint32_t FlagGeometry = 1u << 6;
inline constexpr std::uint32_t FlagIndexed = 1u << 7;
inline constexpr std::uint32_t FlagStashed = 1u << 8;     ///< the capture hook saw the draw: the facts below are its
inline constexpr std::uint32_t FlagBonePalette = 1u << 9; ///< a small bone palette in memory (a prop in one pose)
inline constexpr std::uint32_t FlagSkinned = 1u << 10;    ///< a skeleton buffer
inline constexpr std::uint32_t FlagOwnCamera = 1u << 11;  ///< its vertex shader has the 864-byte camera constants
inline constexpr std::uint32_t FlagSolid = 1u << 12;      ///< the capture hook's "solid": depth write, not blended

inline constexpr std::size_t RowsShown = 8;               ///< draws with samples listed for a pixel (the last ones)
inline constexpr std::uint32_t PaneIndicesMin = 24, PaneIndicesMax = 3000;
inline constexpr std::uint32_t DelayDefault = 30;         ///< frames from arming to the first pixel
inline constexpr float BogusMetres = 100.0f;              ///< a scene entry's box this big (diagonal) gets a cause line
inline constexpr std::size_t EntriesShown = 3;

/// The texts of the five knobs (RtShadow::GlassPickRead fills them).
struct Texts {
    char list[160] = {};
    char size[32] = {};
    char frame[32] = {};
    char repeat[32] = {};
    char panes[160] = {};
};

/// The pick the texts name, armed `now` (the pick's own frame count): the twig pick's knob with `glass` set.
[[nodiscard]] inline B::PickKnob MakeKnob(const Texts& t, std::uint64_t now) {
    B::PickKnob k = B::ParsePick(t.list, t.size[0] != '\0' ? t.size : "1920x1080", nullptr,
                                 t.repeat[0] != '\0' ? t.repeat : nullptr);
    const float delay = B::W::ParseNumber(t.frame[0] != '\0' ? t.frame : nullptr, static_cast<float>(DelayDefault));
    k.start = now + (delay >= 0.0f && delay <= 1.0e6f ? static_cast<std::uint64_t>(delay)
                                                       : static_cast<std::uint64_t>(DelayDefault));
    k.glass = true;
    return k;
}

/// BB_GLASS_PICK_PANES.
struct PaneSpec {
    bool on = false;
    bool all = false; ///< every pick pixel is a pane pixel
    int mode = 1;     ///< 1: glass-like draws only; 2: every small draw
    std::array<B::Point, B::PickMost> points{};
    std::size_t count = 0;
};

[[nodiscard]] inline PaneSpec ParsePanes(const char* text) {
    PaneSpec s;
    if (text == nullptr || text[0] == '\0' || (text[0] == '0' && text[1] == '\0')) {
        return s;
    }
    if ((text[0] == '1' || text[0] == '2') && text[1] == '\0') {
        s.on = true;
        s.all = true;
        s.mode = text[0] == '2' ? 2 : 1;
        return s;
    }
    s.count = B::ParsePoints(text, s.points.data(), s.points.size());
    s.on = s.count != 0;
    return s;
}

[[nodiscard]] inline bool PaneAt(const PaneSpec& s, const B::Point& p) {
    if (!s.on) {
        return false;
    }
    if (s.all) {
        return true;
    }
    for (std::size_t i = 0; i < s.count; ++i) {
        if (s.points[i].x == p.x && s.points[i].y == p.y) {
            return true;
        }
    }
    return false;
}

enum class Verdict { Take, Skinned, TooFew, TooMany, Plain, NoKey };

/// Whether a draw with samples at a pane pixel is taken as a pane (see the header).
[[nodiscard]] inline Verdict PaneVerdict(const B::PickDraw& d, int mode) {
    const std::uint32_t f = d.glass_flags;
    if ((f & FlagSkinned) != 0 || d.kind == 0) {
        return Verdict::Skinned;
    }
    if (d.indices < PaneIndicesMin) {
        return Verdict::TooFew;
    }
    if (d.indices > PaneIndicesMax) {
        return Verdict::TooMany;
    }
    const bool gbuffer = (f & FlagGBuffer) != 0;
    const bool glassy = !gbuffer || (f & FlagBlend) != 0 || d.cutout || (f & FlagZWrite) == 0;
    if (mode < 2 && !glassy) {
        return Verdict::Plain;
    }
    if (gbuffer && d.mesh == 0) {
        return Verdict::NoKey;
    }
    return Verdict::Take;
}

[[nodiscard]] inline const char* VerdictText(Verdict v) {
    switch (v) {
    case Verdict::Take: return "taken";
    case Verdict::Skinned: return "not taken: skinned (a skeleton)";
    case Verdict::TooFew: return "not taken: fewer than 24 indices (a sprite)";
    case Verdict::TooMany: return "not taken: more than 3000 indices (not a pane)";
    case Verdict::Plain: return "not taken: an opaque G-buffer draw (BB_GLASS_PICK_PANES=2 takes it)";
    case Verdict::NoKey: return "not taken: no position stream, no mesh key";
    }
    return "?";
}

/// What the scene's entry list says of a mesh key (RtShadow::GlassPickEntries).
struct EntryView {
    std::uint32_t mask = 0;
    bool glass = false, shadow = false, moving = false, palette = false, skinned = false, probe = false;
    bool has_bounds = false, drawn_recently = false;
    std::uint32_t vertices = 0, triangles = 0, instances = 0;
    std::array<float, 6> bounds{};
    char source = '-'; ///< c: camera pass still reference, b: sun VSM box, s: sun pass still reference
};

[[nodiscard]] inline float Diagonal(const EntryView& e) {
    if (!e.has_bounds) {
        return 0.0f;
    }
    const float dx = e.bounds[3] - e.bounds[0], dy = e.bounds[4] - e.bounds[1], dz = e.bounds[5] - e.bounds[2];
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

/// The index range a draw's index list spans and how many distinct vertices it uses (`counted`: false when the range is
/// too wide to count).
struct IndexUse {
    bool read = false, counted = false;
    std::uint32_t lo = 0, hi = 0, used = 0, count = 0;
};

[[nodiscard]] inline IndexUse ScanIndices(const void* data, std::uint32_t count, std::uint32_t index_size) {
    IndexUse u;
    if (data == nullptr || count == 0 || (index_size != 2 && index_size != 4)) {
        return u;
    }
    const auto* bytes = static_cast<const unsigned char*>(data);
    const std::uint32_t cut = index_size == 2 ? 0xffffu : 0xffffffffu;
    const auto at = [&](std::uint32_t i) {
        std::uint32_t v = 0;
        if (index_size == 2) {
            std::uint16_t w = 0;
            std::memcpy(&w, bytes + std::size_t(i) * 2, 2);
            v = w;
        } else {
            std::memcpy(&v, bytes + std::size_t(i) * 4, 4);
        }
        return v;
    };
    std::uint32_t lo = 0xffffffffu, hi = 0;
    for (std::uint32_t i = 0; i < count; ++i) {
        const std::uint32_t v = at(i);
        if (v == cut) {
            continue;
        }
        lo = std::min(lo, v);
        hi = std::max(hi, v);
    }
    if (lo > hi) {
        return u;
    }
    u.read = true;
    u.lo = lo;
    u.hi = hi;
    u.count = count;
    const std::uint64_t range = std::uint64_t(hi) - lo + 1;
    if (range > (std::uint64_t(1) << 22)) {
        return u;
    }
    std::vector<bool> seen(static_cast<std::size_t>(range), false);
    std::uint32_t used = 0;
    for (std::uint32_t i = 0; i < count; ++i) {
        const std::uint32_t v = at(i);
        if (v != cut && !seen[v - lo]) {
            seen[v - lo] = true;
            ++used;
        }
    }
    u.used = used;
    u.counted = true;
    return u;
}

inline void HeaderLine(const B::Point& pt, const B::Rect& rect, std::size_t asked, std::size_t passed, std::size_t gbuffer,
                       std::size_t forward, std::uint32_t skipped, std::uint64_t frame, bool pane_pixel, char* out,
                       std::size_t size) {
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86l): pixel %d,%d (render %d,%d), frame %llu: %zu draws asked a query, %zu had "
                  "samples in the 5x5 patch (%zu G-buffer, %zu forward in the scene)%s; the last %u of them follow in draw "
                  "order, the last one drew last%s",
                  pt.x, pt.y, rect.cx, rect.cy, static_cast<unsigned long long>(frame), asked, passed, gbuffer, forward,
                  skipped != 0 ? ", NOTE: some draws had no query (group full)" : "", static_cast<unsigned>(RowsShown),
                  pane_pixel ? "; a pane pixel (BB_GLASS_PICK_PANES)" : "");
}

inline void SceneText(const EntryView* entries, std::uint32_t found, std::uint64_t mesh, const IndexUse& use, char* out,
                      std::size_t size) {
    char range[96] = "";
    if (use.read) {
        std::snprintf(range, sizeof(range), "; indices span verts %u..%u (%u), %u used%s", use.lo, use.hi,
                      use.hi - use.lo + 1, use.used, use.counted ? "" : " (not counted)");
    }
    if (found == 0 || entries == nullptr) {
        std::snprintf(out, size, "in scene: NO ENTRY%s%s", mesh == 0 ? " (no position stream)" : "", range);
        return;
    }
    const EntryView& e = entries[0];
    char box[72] = "no box";
    if (e.has_bounds) {
        std::snprintf(box, sizeof(box), "box %.1f x %.1f x %.1f m (%c)", static_cast<double>(e.bounds[3] - e.bounds[0]),
                      static_cast<double>(e.bounds[4] - e.bounds[1]), static_cast<double>(e.bounds[5] - e.bounds[2]),
                      e.source);
    }
    std::snprintf(out, size, "in scene: %u entr%s, first %s%s%s%s%s%s, %u tris %u verts x %u inst, %s%s", found,
                  found == 1 ? "y" : "ies", e.glass ? "PANE" : "solid", e.shadow ? " +sun" : "", e.moving ? " moving" : "",
                  e.palette ? " palette" : "", e.skinned ? " skinned" : "", e.probe ? " probe" : "", e.triangles,
                  e.vertices, e.instances, box, range);
}

inline void DrawLine(const B::Point& pt, std::size_t row, std::size_t total, std::uint64_t samples, const B::PickDraw& d,
                     const EntryView* entries, std::uint32_t found, const IndexUse& use, char* out, std::size_t size) {
    const std::uint32_t f = d.glass_flags;
    char scene[300];
    SceneText(entries, found, d.mesh, use, scene, sizeof(scene));
    const char* capture = (f & FlagCapture) == 0 ? "no (no capture pipeline)"
                          : (f & FlagStashed) == 0 ? "yes"
                          : (f & FlagOwnCamera) != 0 ? "yes, own camera constants"
                                                     : "yes, no own camera constants";
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86l): pixel %d,%d draw %zu of %zu, %llu samples: %s, blend %s, zwrite %s, ztest "
                  "%s, %s, %s, %u targets, vs:ps %08x:%08x, %u indices (first %u, base %d) x %u inst, %s%s%s, capture %s, "
                  "stream %u verts stride %u, mesh key %016llx | %s",
                  pt.x, pt.y, row, total, static_cast<unsigned long long>(samples), (f & FlagGBuffer) != 0 ? "G-buffer" : "forward",
                  (f & FlagBlend) != 0 ? "on" : "off", (f & FlagZWrite) != 0 ? "on" : "off", (f & FlagZTest) != 0 ? "on" : "off",
                  d.cutout ? "discard" : "no discard", (f & FlagTextured) != 0 ? "textured" : "plain", d.targets, d.vs, d.ps,
                  d.indices, d.first, static_cast<int>(d.base), d.instances, B::KindName(d.kind),
                  (f & FlagBonePalette) != 0 ? ", bone palette" : "", (f & FlagSkinned) != 0 ? ", skeleton" : "", capture,
                  d.stream_verts, d.stride, static_cast<unsigned long long>(d.mesh), scene);
}

/// One line for a scene entry whose box is bogus (Diagonal above BogusMetres): the cause as far as the draw's own index
/// list says. RtShadow::MakeEntry captures the vertices lo..hi of the draw's index range, the vertex shader transforms all
/// of them with this draw's matrices, and the still box is measured over all of them: a vertex of the range that no
/// triangle uses (another mesh of the shared stream) lands anywhere and makes the box tall; the triangles themselves, and
/// so the BLAS, are right.
inline void BoundsLine(const B::Point& pt, const B::PickDraw& d, const EntryView& e, const IndexUse& use, char* out,
                       std::size_t size) {
    char verdict[320]; // (review) the stray-vertices text alone expands to at least 227: 200 is a -Wfortify-source error
    if (!use.read) {
        std::snprintf(verdict, sizeof(verdict), "the draw's indices could not be read here");
    } else if (!use.counted) {
        std::snprintf(verdict, sizeof(verdict), "the index range %u..%u is too wide to count", use.lo, use.hi);
    } else if (use.used < use.hi - use.lo + 1) {
        std::snprintf(verdict, sizeof(verdict),
                      "its %u indices use %u of the %u vertices of the range %u..%u the capture transforms: %u stray "
                      "vertices (another mesh of the shared stream) are moved by this draw's matrices all the same, the "
                      "box follows them, the triangles are right",
                      use.count, use.used, use.hi - use.lo + 1, use.lo, use.hi, use.hi - use.lo + 1 - use.used);
    } else {
        std::snprintf(verdict, sizeof(verdict),
                      "all %u vertices of the range %u..%u are used: the box is not from stray vertices (look at the "
                      "vertex shader's own output)",
                      use.hi - use.lo + 1, use.lo, use.hi);
    }
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86l): bound cause: pixel %d,%d vs:ps %08x:%08x key %016llx: the scene entry's box "
                  "is %.1f m across (%.1f x %.1f x %.1f, source %c) over %u captured vertices; %s",
                  pt.x, pt.y, d.vs, d.ps, static_cast<unsigned long long>(d.mesh), static_cast<double>(Diagonal(e)),
                  static_cast<double>(e.bounds[3] - e.bounds[0]), static_cast<double>(e.bounds[4] - e.bounds[1]),
                  static_cast<double>(e.bounds[5] - e.bounds[2]), e.source, e.vertices, verdict);
}

inline void PaneLine(const B::Point& pt, const B::PickDraw& d, Verdict verdict, bool took, const char* how, char* out,
                     std::size_t size) {
    const std::uint32_t f = d.glass_flags;
    const char* head = verdict == Verdict::Take ? (took ? "taken" : "NOT taken") : VerdictText(verdict);
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86l): pane from pick: pixel %d,%d vs:ps %08x:%08x key %016llx, %u indices, %s, "
                  "blend %s, zwrite %s, %s: %s%s%s",
                  pt.x, pt.y, d.vs, d.ps, static_cast<unsigned long long>(d.mesh), d.indices,
                  (f & FlagGBuffer) != 0 ? "G-buffer" : "forward", (f & FlagBlend) != 0 ? "on" : "off",
                  (f & FlagZWrite) != 0 ? "on" : "off", d.cutout ? "discard" : "no discard", head,
                  how[0] != '\0' ? " - " : "", how);
}

inline void OnceText(const B::PickKnob& k, const PaneSpec& panes, char* out, std::size_t size) {
    char pane_text[96] = "off";
    if (panes.on) {
        std::snprintf(pane_text, sizeof(pane_text), "%s (mode %d)", panes.all ? "every pick pixel" : "listed pixels",
                      panes.mode);
    }
    std::snprintf(out, size,
                  "GLINT-PROOF glass pick (r86l, TOOL, BB_GLASS_PICK): %zu pixel(s) of a %ux%u picture, from frame %llu of "
                  "the pick, %llu frames a pixel: those frames draw only a 5x5 patch of the G-buffer and of the forward "
                  "draws of the scene (the picture is broken for them); an occlusion query a draw lists every draw that "
                  "passed the depth test there; panes from the pick: %s",
                  k.count, k.out_w, k.out_h, static_cast<unsigned long long>(k.start),
                  static_cast<unsigned long long>(B::PickFramesPerPoint), pane_text);
}

} // namespace Vulkan::RtGlassPick
''',
}

# ---------------------------------------------------------------- bbport_wind_trees.h
TR_INC_OLD = "#include <array>\n#include <cmath>\n"
TR_INC_NEW = "#include <array>\n#include <atomic> // bbport (r86l_glint-pick-glass)\n#include <cmath>\n"

TR_KNOB_OLD = "    std::uint64_t repeat = 0; ///< bbport (r89k): the sweep starts again every this many frames (0: once)\n};\n"
TR_KNOB_NEW = ("    std::uint64_t repeat = 0; ///< bbport (r89k): the sweep starts again every this many frames (0: once)\n"
               "    bool glass = false;       ///< bbport (r86l_glint-pick-glass, TOOL): the glass pick: every draw that passed, forward ones too\n"
               "};\n")

TR_ON_OLD = '''/// BB_WIND_TWIGS_PICK names at least one pixel (TOOL).
[[nodiscard]] inline bool PickOn() {
    return PickOnce().count > 0;
}
'''
TR_ON_NEW = '''/// bbport (r86l_glint-pick-glass, TOOL): the glass pick (BB_GLASS_PICK, rt_glass_pick.h) is armed and dropped while the game
/// runs (a job's set: / unset:). The frame end writes it, the draws read `armed`; `knob` is read only while armed.
struct GlassPickLive {
    std::atomic<bool> armed{false};
    PickKnob knob{};
};

[[nodiscard]] inline GlassPickLive& GlassPickState() {
    static GlassPickLive state;
    return state;
}

/// The pick in force: the glass pick's while it is armed, else BB_WIND_TWIGS_PICK's.
[[nodiscard]] inline const PickKnob& PickCurrent() {
    const GlassPickLive& live = GlassPickState();
    return live.armed.load(std::memory_order_relaxed) ? live.knob : PickOnce();
}

/// BB_WIND_TWIGS_PICK names at least one pixel, or the glass pick is armed (TOOL).
[[nodiscard]] inline bool PickOn() {
    return GlassPickState().armed.load(std::memory_order_relaxed) || PickOnce().count > 0;
}
'''

TR_DRAW_OLD = "    std::uint64_t index_address = 0;\n};\n\nstruct PickResult {\n"
TR_DRAW_NEW = ("    std::uint64_t index_address = 0;\n"
               "    // bbport (r86l_glint-pick-glass, TOOL): the glass pick's facts of the draw (RtGlassPick::Flag*; 0 for the twig pick)\n"
               "    std::uint32_t glass_flags = 0, targets = 0, instances = 0, index_size = 0, images = 0;\n"
               "    std::uint64_t mesh = 0;          ///< the position key PrepareDraw keys entries by (0: no position stream)\n"
               "    std::uint64_t pair_vs = 0, pair_ps = 0; ///< the full shader hashes (RtGlassMatch's)\n"
               "};\n\nstruct PickResult {\n")

# ---------------------------------------------------------------- rt_glass.h
GL_INC_OLD = '#include <array>\n#include <cstddef>\n#include <cstdint>\n#include <cstdlib>\n\n#include "../host_shaders/rt_glass_layout.h"\n'
GL_INC_NEW = ('#include <array>\n#include <atomic> // bbport (r86l_glint-pick-glass)\n#include <cstddef>\n#include <cstdint>\n#include <cstdlib>\n\n'
              '#include "../host_shaders/rt_glass_layout.h"\n')

GL_MATCH_OLD = '''inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {
    return RtGlassMatches(RtGlass(), vs, ps);
}
'''
GL_MATCH_NEW = '''// bbport (r86l_glint-pick-glass, TOOL): shader pairs the glass pick took at run time (BB_GLASS_PICK_PANES: a forward draw is
// taken by its pair). A fixed table of relaxed atomics: written by the frame end, read by every draw and by the pipeline
// key; empty while no pane is picked (one load). RtGlassMatch reads it after the knob's list, so a picked pair is a listed one.
inline constexpr std::size_t RtGlassPickPairsMost = 16;
struct RtGlassPickTable {
    std::atomic<std::uint32_t> count{0};
    std::array<std::atomic<std::uint64_t>, RtGlassPickPairsMost> vs{};
    std::array<std::atomic<std::uint64_t>, RtGlassPickPairsMost> ps{};
};

inline RtGlassPickTable& RtGlassPicked() {
    static RtGlassPickTable table;
    return table;
}

inline bool RtGlassPickPair(std::uint64_t vs, std::uint64_t ps) {
    const RtGlassPickTable& table = RtGlassPicked();
    const std::uint32_t n = table.count.load(std::memory_order_acquire);
    for (std::uint32_t i = 0; i < n; ++i) {
        if (table.vs[i].load(std::memory_order_relaxed) == vs && table.ps[i].load(std::memory_order_relaxed) == ps) {
            return true;
        }
    }
    return false;
}

/// Adds a pair: false when it is zero, known, or the table is full.
inline bool RtGlassPickAdd(std::uint64_t vs, std::uint64_t ps) {
    if (vs == 0 || ps == 0 || RtGlassPickPair(vs, ps)) {
        return false;
    }
    RtGlassPickTable& table = RtGlassPicked();
    const std::uint32_t n = table.count.load(std::memory_order_relaxed);
    if (n >= RtGlassPickPairsMost) {
        return false;
    }
    table.vs[n].store(vs, std::memory_order_relaxed);
    table.ps[n].store(ps, std::memory_order_relaxed);
    table.count.store(n + 1, std::memory_order_release);
    return true;
}

inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {
    return RtGlassMatches(RtGlass(), vs, ps) || RtGlassPickPair(vs, ps);
}
'''

# ---------------------------------------------------------------- vk_rt_shadow.h
RH_INC_OLD = "class SunVsm;\n"
RH_INC_NEW = ("class SunVsm;\n"
              "namespace RtGlassPick { // bbport (r86l_glint-pick-glass, TOOL): rt_glass_pick.h, included by vk_rt_shadow.cpp\n"
              "struct EntryView;\n"
              "struct Texts;\n"
              "} // namespace RtGlassPick\n")

RC_INC_OLD = '#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'
RC_INC_NEW = RC_INC_OLD + '#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)\n'

RH_DECL_OLD = "    [[nodiscard]] bool GlassBoxCandidate(const Draw& draw, u64 vs, u64 ps, bool left_out);\n"
RH_DECL_NEW = RH_DECL_OLD + '''    // bbport (r86l_glint-pick-glass, TOOL): the glass pick (BB_GLASS_PICK, vk_rasterizer_effects.cpp). GlassPickTake: a G-buffer
    // draw of this mesh key (the position key PrepareDraw gives a draw with a position stream) becomes a pane: GlassBoxMatch is
    // true for it, in a table of 32 keys apart from the box rule's (a live knob change that clears the box's keys leaves these);
    // false when the key is known or the table is full. GlassPickEntries: the scene's entries of that key (a mesh may have
    // several: palettes, copies); `out` gets at most `most`, the return value counts them all. GlassPickRead: the texts of
    // BB_GLASS_PICK, _SIZE, _FRAME, _REPEAT and _PANES (live where the test tools' knobs file exists, else the environment);
    // true when the knobs' generation changed since the last call (the first call too).
    [[nodiscard]] bool GlassPickTake(u64 key);
    [[nodiscard]] u32 GlassPickEntries(u64 key, RtGlassPick::EntryView* out, u32 most) const;
    [[nodiscard]] bool GlassPickRead(RtGlassPick::Texts& texts);
'''

RH_MEM_OLD = "    std::array<u64, 128> glass_box_rejected{};\n    u32 glass_box_rejected_count = 0;\n"
RH_MEM_NEW = RH_MEM_OLD + '''    // bbport (r86l_glint-pick-glass, TOOL): the mesh keys the glass pick took, and the knobs' generation it was read at
    std::array<u64, 32> glass_pick_keys{};
    u32 glass_pick_count = 0;
    u32 glass_pick_gen = 0xffffffffu;
'''

# ---------------------------------------------------------------- vk_rt_shadow.cpp
RC_MATCH_OLD = '''    if (glass_box_count == 0 || draw.skinned || draw.positions == 0) {
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return true;
        }
    }
    return false;
}
'''
RC_MATCH_NEW = '''    if ((glass_box_count == 0 && glass_pick_count == 0) || draw.skinned || draw.positions == 0) { // bbport (r86l): and the pick's keys
        return false;
    }
    const std::array<u64, 4> parts{draw.positions, draw.indices,
                                   (u64(draw.index_count) << 32) | draw.first_vertex, draw.instances};
    const u64 key = XXH3_64bits(parts.data(), sizeof(parts));
    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return true;
        }
    }
    for (u32 i = 0; i < glass_pick_count; ++i) { // bbport (r86l_glint-pick-glass, TOOL): taken by the glass pick
        if (glass_pick_keys[i] == key) {
            return true;
        }
    }
    return false;
}
'''

RC_CAND_OLD = '''    for (u32 i = 0; i < glass_box_count; ++i) {
        if (glass_box_keys[i] == key) {
            return false; // taken: GlassBoxMatch makes it a box pane
        }
    }
'''
RC_CAND_NEW = RC_CAND_OLD + '''    for (u32 i = 0; i < glass_pick_count; ++i) { // bbport (r86l_glint-pick-glass, TOOL): taken by the glass pick
        if (glass_pick_keys[i] == key) {
            return false;
        }
    }
'''

RC_FUNCS_ANCHOR = "// bbport (r86i_glint-find-gbuffer): see the declaration. The entries are those of the ray traced scene (solid\n"
RC_FUNCS_NEW = '''// bbport (r86l_glint-pick-glass, TOOL): see the declaration. A pane taken by the glass pick is a box pane by its key.
bool RtShadow::GlassPickTake(u64 key) {
    if (key == 0) {
        return false;
    }
    for (u32 i = 0; i < glass_pick_count; ++i) {
        if (glass_pick_keys[i] == key) {
            return false;
        }
    }
    if (glass_pick_count >= glass_pick_keys.size()) {
        return false;
    }
    glass_pick_keys[glass_pick_count++] = key;
    return true;
}

// bbport (r86l_glint-pick-glass, TOOL): the entries of a mesh key, plain (the position key) or a pane's (RtGlassKey of it, the
// base PrepareDraw stores). Called from the frame end, on the thread that draws.
u32 RtShadow::GlassPickEntries(u64 key, RtGlassPick::EntryView* out, u32 most) const {
    if (key == 0) {
        return 0;
    }
    const u64 glass_key = RtGlassKey(key);
    u32 total = 0;
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || (e->base != key && e->base != glass_key)) {
            continue;
        }
        if (out != nullptr && total < most) {
            RtGlassPick::EntryView& v = out[total];
            v = {};
            v.mask = e->mask;
            v.glass = (e->mask & RtGlassMask) != 0;
            v.shadow = e->shadow;
            v.moving = e->dynamic;
            v.palette = e->palette != 0;
            v.skinned = e->skinned;
            v.probe = e->box_candidate;
            v.vertices = e->vertices;
            v.triangles = e->triangles;
            v.instances = e->instances;
            v.drawn_recently = e->still_camera_frame + StillNearFrames >= frame;
            const std::array<float, 6>* bounds = nullptr;
            if (e->still_has_ref[0]) {
                bounds = &e->still_ref[0];
                v.source = 'c';
            } else if (e->has_box) {
                bounds = &e->box;
                v.source = 'b';
            } else if (e->still_has_ref[1]) {
                bounds = &e->still_ref[1];
                v.source = 's';
            }
            if (bounds != nullptr && (*bounds)[0] <= (*bounds)[3] && (*bounds)[1] <= (*bounds)[4] &&
                (*bounds)[2] <= (*bounds)[5]) {
                v.has_bounds = true;
                v.bounds = *bounds;
            }
        }
        ++total;
    }
    return total;
}

// bbport (r86l_glint-pick-glass, TOOL): the five knobs' texts, asked again when the live knobs' generation changed (without the
// test tools' knobs file: once, from the environment).
bool RtShadow::GlassPickRead(RtGlassPick::Texts& texts) {
#if BB_GLASS_STATIC_LIVE
    const u32 generation = BbLiveKnobs::Generation();
#else
    const u32 generation = 0;
#endif
    if (generation == glass_pick_gen) {
        return false;
    }
    glass_pick_gen = generation;
    static const char* const names[5] = {"BB_GLASS_PICK", "BB_GLASS_PICK_SIZE", "BB_GLASS_PICK_FRAME", "BB_GLASS_PICK_REPEAT",
                                         "BB_GLASS_PICK_PANES"};
    char* const dest[5] = {texts.list, texts.size, texts.frame, texts.repeat, texts.panes};
    const std::size_t room[5] = {sizeof(texts.list), sizeof(texts.size), sizeof(texts.frame), sizeof(texts.repeat),
                                 sizeof(texts.panes)};
    for (int i = 0; i < 5; ++i) {
#if BB_GLASS_STATIC_LIVE
        const BbLiveKnobs::Text text = BbLiveKnobs::Lookup(names[i]);
        const char* value = text.Get();
#else
        const char* value = std::getenv(names[i]);
#endif
        std::snprintf(dest[i], room[i], "%s", value != nullptr ? value : "");
    }
    return true;
}

''' + RC_FUNCS_ANCHOR

# ---------------------------------------------------------------- vk_rasterizer.h
RAH_INC_OLD = '#include "video_core/renderer_vulkan/vk_glass_glint.h" // bbport (r86b_glass-visible)\n'
RAH_INC_NEW = RAH_INC_OLD + '#include "video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass, TOOL)\n'

RAH_MEM_OLD = "    mutable u32 trees_pick_meet = 0, trees_pick_apart = 0;\n"
RAH_MEM_NEW = RAH_MEM_OLD + '''    // bbport (r86l_glint-pick-glass, TOOL): the glass pick. trees_pick_draw: this draw is narrowed to the patch and given a query
    // (the G-buffer's, as r89j had it, and with the glass pick armed the forward draws of the scene); trees_pick_glass: the glass
    // pick is armed (its draw facts are kept); trees_pick_indexed: the draw is indexed; glass_pick_note: the capture hook's facts
    // of the draw the query site asks about
    bool trees_pick_draw = false;
    bool trees_pick_glass = false;
    bool trees_pick_indexed = false;
    RtGlassPick::PaneSpec glass_pick_panes{};
    struct GlassPickNote {
        bool valid = false;
        u64 positions = 0, key = 0;
        u32 index_count = 0;
        u32 flags = 0;
    } glass_pick_note;
    void GlassPickPoll();
    void GlassPickStash(const RtShadow::Draw& draw);
    void GlassPickGroup(const TreesPickGroup& g, const std::vector<u64>& counts, vk::Result result,
                        const BbWindTrees::Point& pt);
'''

# ---------------------------------------------------------------- vk_rasterizer.cpp
RA_PREP_OLD = "    EffectsAfterTargets(pipeline);\n    if (upscaler->Enabled() && cb_descs[0].first) {\n"
RA_PREP_NEW = '''    // bbport (r86l_glint-pick-glass, TOOL): the draws of a pick frame that are narrowed to the patch and given a query: the
    // G-buffer's (as r89j had it) and, with the glass pick armed, the forward draws of the scene (a depth target that is no sun
    // shadow pass, a colour target, the scene's frame running). Off: trees_pick_rect_on is false, nothing else is read.
    trees_pick_draw = trees_pick_rect_on &&
                      (gbuffer_draw ||
                       (trees_pick_glass && scene_started && db_desc.first && key.mrt_mask != 0 &&
                        !(regs.depth_buffer.Pitch() == regs.depth_buffer.Height() && regs.depth_buffer.Height() >= 1024)));
''' + RA_PREP_OLD

RA_QUERY_OLD = ("    if (trees_pick_rect_on && gbuffer_draw) { // bbport (r89j_twigs-pick-trees, TOOL): this draw's query, for the pick\n"
                "        WindTreesPickQuery(")
RA_QUERY_NEW = ("    if (trees_pick_draw) { // bbport (r89j_twigs-pick-trees, TOOL): this draw's query, for the pick (r86l: forward draws too)\n"
                "        trees_pick_indexed = is_indexed;\n"
                "        WindTreesPickQuery(")

RA_SCISSOR_OLD = "        if (trees_pick_rect_on && gbuffer_draw) { // bbport (r89j_twigs-pick-trees, TOOL): only the pick's patch is drawn\n"
RA_SCISSOR_NEW = "        if (trees_pick_draw) { // bbport (r89j_twigs-pick-trees, TOOL): only the pick's patch is drawn (r86l: forward draws too)\n"

RA_DISPATCH_OLD = "    gbuffer_draw = false;\n\n    scheduler.PopPendingOperations();\n"
RA_DISPATCH_NEW = "    gbuffer_draw = false;\n    trees_pick_draw = false; // bbport (r86l_glint-pick-glass, TOOL)\n\n    scheduler.PopPendingOperations();\n"

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_QUERY_OLD = '''    pool = *p.pool;
    index = p.group * BbWindTrees::PickPerGroup + g.used++;
    g.draws.push_back(d);
'''
EF_QUERY_NEW = '''    if (trees_pick_glass) { // bbport (r86l_glint-pick-glass, TOOL): what the glass pick says of this draw
        const auto& pick_dc = Dc();
        d.glass_flags = (gbuffer_draw ? RtGlassPick::FlagGBuffer : 0u) |
                        (regs.blend_control[0].enable != 0 ? RtGlassPick::FlagBlend : 0u) |
                        (d.depth_write ? RtGlassPick::FlagZWrite : 0u) |
                        (regs.depth_control.depth_enable != 0 ? RtGlassPick::FlagZTest : 0u) |
                        (ps != nullptr && !ps->images.empty() ? RtGlassPick::FlagTextured : 0u) |
                        (pick_dc.capture_draw ? RtGlassPick::FlagCapture : 0u) |
                        (pick_dc.motion_geometry != 0 ? RtGlassPick::FlagGeometry : 0u) |
                        (trees_pick_indexed ? RtGlassPick::FlagIndexed : 0u);
        d.targets = u32(std::popcount(key.mrt_mask));
        d.instances = regs.num_instances.NumInstances();
        d.index_size = index_size;
        d.images = ps != nullptr ? u32(ps->images.size()) : 0u;
        d.pair_vs = vs.pgm_hash;
        d.pair_ps = ps != nullptr ? ps->pgm_hash : 0u;
        GlassPickNote& note = glass_pick_note;
        if (note.valid && note.positions == d.stream && note.index_count == d.indices) {
            // the capture hook saw this draw: its key and facts (the skeleton, the bone palette, its own camera constants)
            d.mesh = note.key;
            d.glass_flags |= note.flags | RtGlassPick::FlagStashed;
        } else if (d.stream != 0) {
            const std::array<u64, 4> parts{d.stream, trees_pick_indexed ? d.index_address : u64(0),
                                           (u64(d.indices) << 32) | u32(d.base), u64(d.instances)};
            d.mesh = XXH3_64bits(parts.data(), sizeof(parts)); // the key PrepareDraw makes of a draw with a position stream
        }
        note.valid = false;
    }
''' + EF_QUERY_OLD

EF_POLL_OLD = '''    if (!BbWindTrees::PickOn()) {
        return;
    }
    TreesPick& p = trees_pick;
    const BbWindTrees::PickKnob& knob = BbWindTrees::PickOnce();
    ++p.frame;
'''
EF_POLL_NEW = '''    GlassPickPoll(); // bbport (r86l_glint-pick-glass, TOOL): BB_GLASS_PICK armed or dropped (live)
    if (!BbWindTrees::PickOn()) {
        return;
    }
    TreesPick& p = trees_pick;
    const BbWindTrees::PickKnob& knob = BbWindTrees::PickCurrent(); // bbport (r86l): the glass pick's while it is armed
    trees_pick_glass = knob.glass;
    ++p.frame;
'''

EF_GROUP_OLD = '''        const BbWindTrees::Point& pt = knob.points[g.point];
        char text[704];
        if (result != vk::Result::eSuccess) {
'''
EF_GROUP_NEW = '''        const BbWindTrees::Point& pt = knob.points[g.point];
        char text[704];
        if (knob.glass) { // bbport (r86l_glint-pick-glass, TOOL): its own lines: every draw that passed, not one winner
            GlassPickGroup(g, counts, result, pt);
        } else if (result != vk::Result::eSuccess) {
'''

EF_FUNCS_ANCHOR = "// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of the G-buffer or a sun shadow pass\n"
EF_FUNCS_NEW = r'''// bbport (r86l_glint-pick-glass, TOOL), once a frame before the pick's own work (WindTreesPickFrameEnd): the glass pick's knobs
// (RtShadow::GlassPickRead: live where the test tools' knobs file exists, else the environment) arm or drop it. Armed:
// BbWindTrees::GlassPickState() holds its knob and the first pixel comes BB_GLASS_PICK_FRAME frames after the set, counted in
// the pick's own frames (trees_pick.frame). Dropped: this frame's patch goes (the picture is whole again) and the pick stops.
// A change of another live knob that leaves the five texts as they were does nothing.
void Rasterizer::GlassPickPoll() {
    static RtGlassPick::Texts fresh, last;
    if (!rt_shadow->GlassPickRead(fresh)) {
        return;
    }
    if (std::memcmp(&fresh, &last, sizeof(fresh)) == 0) {
        return;
    }
    last = fresh;
    BbWindTrees::GlassPickLive& live = BbWindTrees::GlassPickState();
    glass_pick_panes = RtGlassPick::ParsePanes(fresh.panes);
    const BbWindTrees::PickKnob knob = RtGlassPick::MakeKnob(fresh, trees_pick.frame);
    if (knob.count == 0) {
        if (live.armed.load(std::memory_order_relaxed)) {
            live.armed.store(false, std::memory_order_relaxed);
            trees_pick_rect_on = false;
            trees_pick_draw = false;
            trees_pick_glass = false;
            trees_pick_meet = 0;
            trees_pick_apart = 0;
            std::printf("GLINT-PROOF glass pick (r86l): BB_GLASS_PICK unset: the pick stops, the picture is whole again\n");
        }
        return;
    }
    live.knob = knob;
    live.armed.store(true, std::memory_order_relaxed);
    trees_pick.said = true; // the twig pick's once-line is for BB_WIND_TWIGS_PICK
    char once[1024];
    RtGlassPick::OnceText(knob, glass_pick_panes, once, sizeof(once));
    std::printf("%s\n", once);
}

// bbport (r86l_glint-pick-glass, TOOL): the capture hook's facts of the draw it just prepared (EffectsCaptureDraw, before
// PrepareDraw): the position key and what PrepareDraw will see (a skeleton, a bone palette, own camera constants, solid).
// WindTreesPickQuery uses them when the same draw (its position stream and index count) asks for its query.
void Rasterizer::GlassPickStash(const RtShadow::Draw& draw) {
    GlassPickNote& note = glass_pick_note;
    note.valid = true;
    note.positions = draw.positions;
    note.index_count = draw.index_count;
    note.key = 0;
    if (draw.positions != 0) {
        const std::array<u64, 4> parts{draw.positions, draw.indices, (u64(draw.index_count) << 32) | draw.first_vertex,
                                       u64(draw.instances)};
        note.key = XXH3_64bits(parts.data(), sizeof(parts));
    }
    note.flags = (draw.skinned ? RtGlassPick::FlagSkinned : 0u) | (draw.palette != 0 ? RtGlassPick::FlagBonePalette : 0u) |
                 (draw.constants != nullptr ? RtGlassPick::FlagOwnCamera : 0u) | (draw.solid ? RtGlassPick::FlagSolid : 0u);
}

// bbport (r86l_glint-pick-glass, TOOL): one pick pixel's group of queries, read once the GPU passed it: the header line, the last
// RtGlassPick::RowsShown draws that had samples in draw order (with what the scene's entry list says of each, the index
// list's span and use, and for a box over 100 m a cause line), and for a pane pixel the draws taken as panes (a G-buffer draw
// by its mesh key, a forward draw by its shader pair) or why not.
void Rasterizer::GlassPickGroup(const TreesPickGroup& g, const std::vector<u64>& counts, vk::Result result,
                                const BbWindTrees::Point& pt) {
    char line[1100];
    if (result != vk::Result::eSuccess) {
        std::printf("GLINT-PROOF glass pick (r86l): pixel %d,%d: the query results were not available (result %d)\n", pt.x,
                    pt.y, static_cast<int>(result));
        return;
    }
    const u64 frame = object_motion->Frame();
    std::vector<std::size_t> rows;
    std::size_t gbuffer = 0, forward = 0;
    for (std::size_t i = 0; i < g.draws.size() && i < counts.size(); ++i) {
        if (counts[i] == 0) {
            continue;
        }
        rows.push_back(i);
        if ((g.draws[i].glass_flags & RtGlassPick::FlagGBuffer) != 0) {
            ++gbuffer;
        } else {
            ++forward;
        }
    }
    const bool pane_pixel = RtGlassPick::PaneAt(glass_pick_panes, pt);
    RtGlassPick::HeaderLine(pt, g.rect, g.draws.size(), rows.size(), gbuffer, forward, g.skipped, frame, pane_pixel, line,
                            sizeof(line));
    std::printf("%s\n", line);
    const std::size_t first_shown = rows.size() > RtGlassPick::RowsShown ? rows.size() - RtGlassPick::RowsShown : 0;
    for (std::size_t n = 0; n < rows.size(); ++n) {
        const std::size_t i = rows[n];
        const BbWindTrees::PickDraw& d = g.draws[i];
        const bool shown = n >= first_shown;
        std::array<RtGlassPick::EntryView, RtGlassPick::EntriesShown> views;
        const u32 found = d.mesh != 0 ? rt_shadow->GlassPickEntries(d.mesh, views.data(), u32(views.size())) : 0u;
        RtGlassPick::IndexUse use;
        if (shown && found != 0 && (d.glass_flags & RtGlassPick::FlagIndexed) != 0 && d.index_address != 0 && d.indices != 0 &&
            d.index_size != 0) {
            const u64 bytes = u64(d.indices) * d.index_size;
            if (memory->IsValidGpuMapping(d.index_address, 0) && memory->ClampRangeSize(d.index_address, bytes) == bytes) {
                use = RtGlassPick::ScanIndices(reinterpret_cast<const void*>(d.index_address), d.indices, d.index_size);
            }
        }
        if (shown) {
            RtGlassPick::DrawLine(pt, n + 1, rows.size(), counts[i], d, views.data(), found, use, line, sizeof(line));
            std::printf("%s\n", line);
            if (found != 0 && views[0].has_bounds && RtGlassPick::Diagonal(views[0]) > RtGlassPick::BogusMetres) {
                RtGlassPick::BoundsLine(pt, d, views[0], use, line, sizeof(line));
                std::printf("%s\n", line);
            }
        }
        if (!pane_pixel) {
            continue;
        }
        const RtGlassPick::Verdict verdict = RtGlassPick::PaneVerdict(d, glass_pick_panes.mode);
        if (verdict != RtGlassPick::Verdict::Take) {
            if (shown) {
                RtGlassPick::PaneLine(pt, d, verdict, false, "", line, sizeof(line));
                std::printf("%s\n", line);
            }
            continue;
        }
        const char* how = "";
        bool took = false;
        if (!RtGlassOn()) {
            how = "BB_RT_GLASS is off: nothing is taken (set it, for example auto)";
        } else if ((d.glass_flags & RtGlassPick::FlagGBuffer) != 0) {
            took = rt_shadow->GlassPickTake(d.mesh);
            how = took ? "G-buffer draw: its mesh key joins the pane keys; its next draws are made pane records of their own "
                         "vertices (the r86i/r86k box pane route; no entry bound is used)"
                       : "this mesh key was taken before, or the table of 32 keys is full";
        } else {
            took = RtGlassPickAdd(d.pair_vs, d.pair_ps);
            how = took ? "forward draw: its shader pair joins the capture list; its pipeline is made again with a capture "
                         "variant at the next draw, and every draw of the pair is a pane record"
                       : "this shader pair was taken before, or the table of 16 pairs is full";
        }
        if (took || shown) {
            RtGlassPick::PaneLine(pt, d, verdict, took, how, line, sizeof(line));
            std::printf("%s\n", line);
        }
    }
}

''' + EF_FUNCS_ANCHOR

EF_STASH_OLD = "        rt_shadow->SetGateCapture(cap);\n    }\n"
EF_STASH_NEW = EF_STASH_OLD + ("    if (trees_pick_glass) { // bbport (r86l_glint-pick-glass, TOOL): the glass pick keeps this draw's facts\n"
                               "        GlassPickStash(draw);\n"
                               "    }\n")

# ---------------------------------------------------------------- README.md
README_ANCHOR = "| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only)"
README_NEW = ("| `BB_GLASS_PICK` | TOOL (r86l; goes to the test-tools branch; off by default). `x:y;x:y;...` (`x,y` reads too), at most 8 pixels of a "
              "1920x1080 picture (`BB_GLASS_PICK_SIZE=WxH` for another size; `BB_GLASS_PICK_FRAME=N`, default 30: the frames from the set to "
              "the first pixel; `BB_GLASS_PICK_REPEAT=N`: the sweep starts again every N frames). Read live where the test tools' knobs file "
              "exists (a job's `set:` and `unset:`), else once from the environment; unset or empty drops it and the picture is whole again. "
              "It reuses the twig pick (`BB_WIND_TWIGS_PICK`: an occlusion query a draw, only a 5x5 patch drawn for 2 frames a pixel, the "
              "picture of those frames is broken) but names EVERY draw of the camera pass that passed the depth test at the pixel: the "
              "G-buffer draws and the forward draws of the scene (colour write, depth test only; not the sun shadow passes, not the HUD), "
              "blended or not. Log, `GLINT-PROOF glass pick (r86l)`: per pixel a header and the last 8 such draws in draw order, each with the "
              "shader pair, pass kind, blend, depth write and test, discard, targets, indices, instances, static, GPU palette, skeleton or bone "
              "palette, whether a capture pipeline and own camera constants exist, the mesh key (the position key the ray traced scene keys "
              "its entries by) and whether the scene's entry list holds it (entries, pane or solid, triangles, vertices, box and its source, "
              "the index list's span and distinct vertices); for an entry box over 100 m across a `bound cause` line (the capture transforms "
              "every vertex of the draw's index range, also those no triangle uses: stray vertices of a shared stream make the box tall, the "
              "triangles are right). Off: a relaxed load of a false flag in `PickOn`, one bool a draw, one generation compare a frame. Armed: "
              "a query a draw in the pick's frames and some log lines | off |\n"
              "| `BB_GLASS_PICK_PANES` | TOOL (r86l; with `BB_GLASS_PICK` and `BB_RT_GLASS` on, for example `auto`). `1`: every pick pixel is a pane "
              "pixel; `2`: the same and every small draw there is taken; `x:y;x:y`: only those pixels. A draw with samples at a pane pixel is "
              "taken as a pane when it is not skinned, has 24 to 3000 indices and (with `1`) is a forward draw, blended, cut out or writes no depth. "
              "A G-buffer draw is taken by its mesh key (the box rule's route: its next draws become pane records of their own vertices, no "
              "entry bound is used), a forward draw by its shader pair (its pipeline gets the capture variant at its next draw, every draw of "
              "the pair is a pane). Log: `pane from pick: ...: taken - <how>` or `not taken: <reason>`. Panes show only with `BB_GLASS_GLINT` | off |\n"
              + README_ANCHOR)

# ---------------------------------------------------------------- tests/test_rt_glass.cpp
TE_INC_OLD = '#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'
TE_INC_NEW = TE_INC_OLD + '#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass)\n'

TE_FIN_OLD = '    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n",\n'
TE_FIN_NEW = r'''    // bbport (r86l_glint-pick-glass): the glass pick's pure parts, the pair table and the pick's live arming
    {
        namespace P = RtGlassPick;
        const P::PaneSpec all = P::ParsePanes("1");
        assert(all.on && all.all && all.mode == 1 && P::ParsePanes("2").mode == 2 && P::ParsePanes("2").all);
        assert(!P::ParsePanes(nullptr).on && !P::ParsePanes("").on && !P::ParsePanes("0").on && !P::ParsePanes("x").on);
        const P::PaneSpec listed = P::ParsePanes("1255:560;1240,620");
        assert(listed.on && !listed.all && listed.count == 2 && listed.mode == 1);
        assert(P::PaneAt(listed, {1255, 560}) && P::PaneAt(listed, {1240, 620}) && !P::PaneAt(listed, {1600, 300}));
        assert(P::PaneAt(all, {1, 2}) && !P::PaneAt(P::ParsePanes(nullptr), {1, 2}));
        P::Texts texts;
        std::snprintf(texts.list, sizeof(texts.list), "%s", "1255:560;1240:620;12:470");
        const BbWindTrees::PickKnob knob = P::MakeKnob(texts, 100);
        assert(knob.glass && knob.count == 3 && knob.out_w == 1920 && knob.out_h == 1080 && knob.start == 130);
        std::snprintf(texts.frame, sizeof(texts.frame), "%s", "5");
        std::snprintf(texts.size, sizeof(texts.size), "%s", "1280x720");
        const BbWindTrees::PickKnob knob2 = P::MakeKnob(texts, 100);
        assert(knob2.start == 105 && knob2.out_w == 1280 && knob2.out_h == 720);
        assert(P::MakeKnob(P::Texts{}, 7).count == 0);
        BbWindTrees::PickDraw d;
        d.indices = 600;
        d.mesh = 7;
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = P::FlagGBuffer | P::FlagZWrite; // an opaque G-buffer draw
        assert(P::PaneVerdict(d, 1) == P::Verdict::Plain && P::PaneVerdict(d, 2) == P::Verdict::Take);
        d.cutout = true;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.cutout = false;
        d.glass_flags = P::FlagGBuffer; // no depth write
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = 0; // forward
        d.mesh = 0;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        assert(P::PaneVerdict(d, 1) == P::Verdict::NoKey);
        d.mesh = 7;
        d.indices = 12;
        assert(P::PaneVerdict(d, 1) == P::Verdict::TooFew);
        d.indices = 5000;
        assert(P::PaneVerdict(d, 1) == P::Verdict::TooMany);
        d.indices = 600;
        d.glass_flags |= P::FlagSkinned;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Skinned);
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        d.kind = 0;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Skinned);
        d.kind = 2;
        // the index list's span and use
        const std::uint16_t idx[] = {10, 11, 12, 10, 12, 13, 40, 41, 42};
        const P::IndexUse use = P::ScanIndices(idx, 9, 2);
        assert(use.read && use.counted && use.lo == 10 && use.hi == 42 && use.used == 7 && use.count == 9);
        const std::uint32_t wide[] = {5, 0xffffffffu, 6};
        const P::IndexUse use4 = P::ScanIndices(wide, 3, 4);
        assert(use4.read && use4.lo == 5 && use4.hi == 6 && use4.used == 2);
        assert(!P::ScanIndices(nullptr, 3, 2).read && !P::ScanIndices(idx, 0, 2).read && !P::ScanIndices(idx, 9, 3).read);
        const std::uint32_t far_apart[] = {0, 0x7fffffffu};
        assert(P::ScanIndices(far_apart, 2, 4).read && !P::ScanIndices(far_apart, 2, 4).counted);
        // the lines stay under the 700 characters the test runner keeps
        char line[1100];
        P::EntryView e;
        e.has_bounds = true;
        e.bounds = {0.0f, 0.0f, 0.0f, 12.43f, 469.22f, 10.6f};
        e.source = 'c';
        e.vertices = 2852;
        e.triangles = 904;
        e.instances = 1;
        assert(P::Diagonal(e) > P::BogusMetres && P::Diagonal(P::EntryView{}) == 0.0f);
        d.vs = 0x9da6aacb;
        d.ps = 0xbb10e440;
        d.index_size = 2;
        d.targets = 7;
        d.instances = 1;
        d.stream_verts = 90094;
        d.stride = 32;
        d.glass_flags = P::FlagGBuffer | P::FlagZWrite | P::FlagZTest | P::FlagTextured | P::FlagCapture | P::FlagStashed |
                        P::FlagBonePalette | P::FlagOwnCamera;
        P::BoundsLine({1255, 560}, d, e, use, line, sizeof(line));
        assert(std::strstr(line, "bound cause") != nullptr && std::strstr(line, "stray") != nullptr && std::strlen(line) < 700);
        const P::IndexUse all_used = P::ScanIndices(idx, 6, 2); // 10..13 all used
        P::BoundsLine({1255, 560}, d, e, all_used, line, sizeof(line));
        assert(std::strstr(line, "not from stray") != nullptr);
        P::BoundsLine({1255, 560}, d, e, P::IndexUse{}, line, sizeof(line));
        assert(std::strstr(line, "could not be read") != nullptr);
        P::DrawLine({1255, 560}, 3, 5, 25, d, nullptr, 0, use, line, sizeof(line));
        assert(std::strstr(line, "G-buffer") != nullptr && std::strstr(line, "NO ENTRY") != nullptr &&
               std::strstr(line, "9da6aacb:bb10e440") != nullptr && std::strlen(line) < 700);
        P::DrawLine({1255, 560}, 3, 5, 25, d, &e, 1, use, line, sizeof(line));
        assert(std::strstr(line, "in scene: 1 entry") != nullptr && std::strstr(line, "box 12.4 x 469.2 x 10.6 m (c)") != nullptr &&
               std::strlen(line) < 700);
        d.glass_flags = 0;
        P::DrawLine({1255, 560}, 1, 1, 9, d, nullptr, 0, P::IndexUse{}, line, sizeof(line));
        assert(std::strstr(line, "forward") != nullptr && std::strstr(line, "capture no") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Take, true, "how", line, sizeof(line));
        assert(std::strstr(line, "pane from pick") != nullptr && std::strstr(line, "taken - how") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Take, false, "", line, sizeof(line));
        assert(std::strstr(line, "NOT taken") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Plain, false, "", line, sizeof(line));
        assert(std::strstr(line, "not taken") != nullptr && std::strlen(line) < 700);
        BbWindTrees::Rect rect;
        P::HeaderLine({1255, 560}, rect, 500, 4, 3, 1, 0, 600, true, line, sizeof(line));
        assert(std::strstr(line, "a pane pixel") != nullptr && std::strlen(line) < 700);
        P::OnceText(knob, P::ParsePanes("1"), line, sizeof(line));
        assert(std::strstr(line, "BB_GLASS_PICK") != nullptr && std::strlen(line) < 1000);
        // the pair table: a picked pair is a listed pair, only after it was added
        assert(!RtGlassPickPair(0x11, 0x22) && !RtGlassMatch(0x11, 0x22));
        assert(RtGlassPickAdd(0x11, 0x22) && RtGlassPickPair(0x11, 0x22) && RtGlassPickPair(0x11, 0x22));
        assert(!RtGlassPickAdd(0x11, 0x22) && !RtGlassPickAdd(0, 5) && !RtGlassPickAdd(5, 0) && !RtGlassPickPair(0x22, 0x11));
        for (std::uint64_t i = 1; i < RtGlassPickPairsMost; ++i) {
            assert(RtGlassPickAdd(0x100 + i, 0x200 + i));
        }
        assert(!RtGlassPickAdd(0x999, 0x998)); // full
        // the live arming: the twig pick is off, the glass pick arms and drops it
        assert(!BbWindTrees::PickOn() && !BbWindTrees::PickCurrent().glass);
        BbWindTrees::GlassPickState().knob = knob;
        BbWindTrees::GlassPickState().armed.store(true, std::memory_order_relaxed);
        assert(BbWindTrees::PickOn() && BbWindTrees::PickCurrent().glass && BbWindTrees::PickCurrent().count == 3);
        BbWindTrees::GlassPickState().armed.store(false, std::memory_order_relaxed);
        assert(!BbWindTrees::PickOn() && !BbWindTrees::PickCurrent().glass);
    }
''' + TE_FIN_OLD

EDITS = {
    TREES: [(TR_INC_OLD, TR_INC_NEW), (TR_KNOB_OLD, TR_KNOB_NEW), (TR_ON_OLD, TR_ON_NEW), (TR_DRAW_OLD, TR_DRAW_NEW)],
    GLASS: [(GL_INC_OLD, GL_INC_NEW), (GL_MATCH_OLD, GL_MATCH_NEW)],
    RTH: [(RH_INC_OLD, RH_INC_NEW), (RH_DECL_OLD, RH_DECL_NEW), (RH_MEM_OLD, RH_MEM_NEW)],
    RTC: [(RC_INC_OLD, RC_INC_NEW), (RC_MATCH_OLD, RC_MATCH_NEW), (RC_CAND_OLD, RC_CAND_NEW), (RC_FUNCS_ANCHOR, RC_FUNCS_NEW)],
    RASTH: [(RAH_INC_OLD, RAH_INC_NEW), (RAH_MEM_OLD, RAH_MEM_NEW)],
    RAST: [(RA_PREP_OLD, RA_PREP_NEW), (RA_QUERY_OLD, RA_QUERY_NEW), (RA_SCISSOR_OLD, RA_SCISSOR_NEW),
           (RA_DISPATCH_OLD, RA_DISPATCH_NEW)],
    EFFECTS: [(EF_QUERY_OLD, EF_QUERY_NEW), (EF_POLL_OLD, EF_POLL_NEW), (EF_GROUP_OLD, EF_GROUP_NEW),
              (EF_FUNCS_ANCHOR, EF_FUNCS_NEW), (EF_STASH_OLD, EF_STASH_NEW)],
    README: [(README_ANCHOR, README_NEW)],
    TEST: [(TE_INC_OLD, TE_INC_NEW), (TE_FIN_OLD, TE_FIN_NEW)],
}

CHECKS = {
    TREES: [("bool glass = false;", 1), ("struct GlassPickLive {", 1), ("inline const PickKnob& PickCurrent() {", 1),
            ("std::uint64_t pair_vs = 0, pair_ps = 0;", 1), ("#include <atomic>", 1)],
    GLASS: [("inline bool RtGlassPickAdd(", 1), ("RtGlassMatches(RtGlass(), vs, ps) || RtGlassPickPair(vs, ps)", 1)],
    RTH: [("bool GlassPickTake(u64 key);", 1), ("u32 glass_pick_count = 0;", 1), ("struct EntryView;", 1)],
    RTC: [('#include "video_core/renderer_vulkan/rt_glass_pick.h"', 1), ("bool RtShadow::GlassPickTake(u64 key) {", 1), ("u32 RtShadow::GlassPickEntries(", 1), ("bool RtShadow::GlassPickRead(", 1),
          ("glass_pick_keys[i] == key", 3)],
    RASTH: [("void GlassPickGroup(const TreesPickGroup& g", 1), ("bool trees_pick_draw = false;", 1)],
    RAST: [("trees_pick_draw = trees_pick_rect_on &&", 1), ("if (trees_pick_draw) {", 2), ("trees_pick_draw = false; // bbport (r86l", 1)],
    EFFECTS: [("void Rasterizer::GlassPickPoll() {", 1), ("void Rasterizer::GlassPickStash(", 1), ("void Rasterizer::GlassPickGroup(", 1),
              ("GlassPickGroup(g, counts, result, pt);", 1), ("GlassPickStash(draw);", 1), ("BbWindTrees::PickCurrent()", 1)],
    README: [("| `BB_GLASS_PICK` |", 1), ("| `BB_GLASS_PICK_PANES` |", 1)],
    TEST: [("namespace P = RtGlassPick;", 1)],
}

# Numbers written twice: the header's constants and the README rows' text.
TIES = [("inline constexpr std::uint32_t PaneIndicesMin = 24, PaneIndicesMax = 3000;", "| `BB_GLASS_PICK_PANES` |", "has 24 to 3000 indices"),
        ("inline constexpr std::uint32_t DelayDefault = 30;", "| `BB_GLASS_PICK` |", "default 30"),
        ("inline constexpr float BogusMetres = 100.0f;", "| `BB_GLASS_PICK` |", "over 100 m across"),
        ("inline constexpr std::size_t RowsShown = 8;", "| `BB_GLASS_PICK` |", "the last 8 such draws"),
        ("inline constexpr std::size_t PickMost = 8;", "| `BB_GLASS_PICK` |", "at most 8 pixels")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    pick_h = NEW_FILES[PICKH]
    for const, row_start, value in TIES:
        rows = "\n".join(l for l in texts[README].split("\n") if l.startswith(row_start))
        src = pick_h if "PaneIndicesMin" in const or "DelayDefault" in const or "BogusMetres" in const or "RowsShown" in const else texts[TREES]
        if src.count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README row %r (%r)" % (const, row_start, value))
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
    allnew = NEW_FILES[PICKH] + "".join(n for p, es in EDITS.items() if p != README for _, n in es)
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
        raise SystemExit("%s is not a source tree root (set R86L_ROOT)" % ROOT)
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
            tmp = full + ".r86ltmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, content in NEW_FILES.items():  # new files take the line ends of the tree (CRLF)
            full = os.path.join(ROOT, path)
            tmp = full + ".r86ltmp"
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
        tmp = full + ".r86ltmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
