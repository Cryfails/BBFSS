// SPDX-License-Identifier: GPL-3.0-or-later
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
