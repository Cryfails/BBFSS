# r89i_twigs-colour-pass: FEATURE fix on top of r89d..r89h (wind work, build 48), with a TOOL knob (the census).
# Three knobs, read once, all only with BB_WIND=1 and the twigs on (BB_WIND_TWIGS above 0):
#   BB_WIND_TWIGS_PALETTE (FEATURE; default 1; 0 = r89h's rule)  draws of a cut-out whose small bone palette the GPU writes
#                         (Motion::Kind::GpuPalette) are offered to the twig rule too
#   BB_WIND_TWIGS_STATIC  (FEATURE; default 1; 0 = r89h; 2 = a TEST)  a G-buffer pipeline with no bone palette whose pixel
#                         shader discards gets the motion variant and so the sway bit
#   BB_WIND_TWIGS_CENSUS  (TOOL, a test aid, goes to the test-tools branch; default 0)  the colour-pass census
# Wind off, twigs off or all three knobs at their off values leave every pipeline key, shader and code path as r89h had
# them (see OFF).
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The wave
# should just be very subtle".
# THE REPORT OF BUILD 48: the counters see motion (proof line: "slot 10: 600 draws (600 on pipelines with the sway bit,
# 1 pipelines) x 156641 vertices; shader counted 576000 vertices ... time motion over 15 frames: 576000 twig vertices,
# 960 vertices run per draw, change mean 7.11 cm, largest 49.36 cm ... verdict OK"), but on screen crop differences of the
# trees 0.5 s apart (on, and the x5 proof) show no branch motion and the proof's yellow tint appears nowhere.
#
# WHAT THE CODE AND THE b48 LOGS SAY (reading only; no game run for this patch):
#  1. The sway bit exists only on a MOTION pipeline (vk_pipeline_cache.cpp: sel.motion, a G-buffer pipeline whose vertex
#     shader reads a stride-16 bone palette buffer, Skeleton or SmallSkeleton size) AND SwayWanted (a pixel shader that
#     discards, or the hang/twig reach knobs). A G-buffer pipeline with NO palette buffer is never a motion pipeline, so
#     it cannot carry the sway bit whatever the CPU rules say. The sun shadow passes (no colour target) are never motion
#     pipelines either, so "the one pipeline with the sway bit" is a G-buffer pipeline: its 960 vertices a draw (all over
#     3 m above the camera, up to 45 m) are one small draw of the 156641-vertex stream, not the visible stand.
#  2. The graveyard line of build 48 (600 frames) counts the draws the sway never reached: "skipped 61200 by reason
#     (draws: small-skeleton 39000, opaque 22200)": 65 draws a frame of sway pipelines that are not Kind::Skinned and,
#     since r89e routes Kind::Other to its candidate rule, are Kind::GpuPalette (a cut-out with a small bone palette the
#     GPU writes: nothing offered them to the twig rule), and 37 draws a frame of opaque skinned pipelines (the existing
#     BB_WIND_TWIGS_REACH=2 gives those the bit; the b43 4K clip with REACH=2 showed the same motion, so they are
#     probably characters). The static cut-out candidates the r89e rule saw were 5 draws a frame, 1 of them the stand.
#  3. Nothing in the logs says which draws paint the visible branches; that is what the census answers.
# THE FIX.
#  (1) BB_WIND_TWIGS_CENSUS=1 (TOOL): in vk_rasterizer.cpp's DrawRecord one call a draw of the G-buffer and sun shadow
#      passes (Rasterizer::WindTwigCensus): the pipeline's render target kind (G-buffer or sun shadow), colour targets
#      and first format, depth size and write, vs:ps hashes, cut-out or opaque, motion pipeline or not, sway bit or not,
#      the position stream (vertices, stride), draws by kind (skinned, GPU palette, static, no motion block), swayed
#      draws, indices, the largest draw's first index and base vertex and the index values it uses (read once a row and
#      report from guest memory, at most 262144 indices), and the reason for no sway word. Every 600 frames, with the
#      twigs' lines: a header line (totals), the 10 G-buffer rows with the most indices, every row with the sway bit
#      (6 more at most) and the 3 sun rows with the most indices: "Wind twigs colour pass (r89i)". There is no
#      screen-area test (the draw's place on screen is not known without its geometry): the biggest draws by indices and
#      the stream sizes stand for it, and the vs:ps pairs are the ones of the tree (6a833138 / 1c3953c6 and the rows
#      around it).
#  (2) BB_WIND_TWIGS_PALETTE=1: a Kind::GpuPalette draw of a pipeline with the sway bit goes to WindSwayWord as a twig
#      candidate (small palette flag 1), as a Kind::Other cut-out does since r89e. A candidate stream with a bone palette
#      is judged with the "loose" rule of BB_WIND_TWIGS_SMALL=3 (height 4-40 m, still, vertex count; no shape or instance
#      check): a mesh drawn once for each tree it stands for has the union of all its places as its world box, which the
#      shape rule refuses ("instanced", "wide", "box").
#  (3) BB_WIND_TWIGS_STATIC=1: in the motion selection a G-buffer pipeline with no bone palette whose pixel shader
#      discards becomes a motion pipeline (sel.motion), which gives it the motion variant and (SwayWanted) the sway bit;
#      its draws are Kind::Other and go to the r89e candidate rule as before. =2 (a TEST) does the same for every opaque
#      G-buffer pipeline without a skeleton (the shape rule refuses a building, a wall or the ground, but the shaders
#      carry the sway code in many more pipelines: the do-nothing job runs it indoors). The shadow side ("the matching
#      shadow draws"): NOT done. The sun shadow pass has no motion variant, so no sway word reaches it; the ray traced
#      scene's capture (the shadow of the swayed branches for the ray traced sun) takes the swayed clip position of the
#      motion variants as before; the game's own sun shadow maps stay unswayed (cm).
# The PROOF knob's yellow tint and counters exist only in the lifter's shader (r89g); a branch whose vertex shader the
# lifter declines is moved x5 by the recompiler's emitter without a tint (the census does not say which shader path a
# pipeline took).
#
# OFF. The twigs off or SMALL=0: PaletteOn/StaticCutouts/StaticOpaque are false (every one asks ReachSmall first, the
# knobs are read once); the pipeline cache's new test is `!sel.motion && vs && StaticWanted(...)` (false: nothing), the
# SwayWanted clause is false, the DrawRecord routing clause is false (one static-bool test) and both census sites are one
# static-bool test (CensusOn). PALETTE=0 STATIC=0 CENSUS=0: the same, so pipeline keys, shaders, cache versions and
# the motion block's words are r89h's (no shader cache version is added: the shaders do not change, only which pipelines
# get them).
# COST ON: CPU: PALETTE adds the GPU-palette cut-out draws to r89e's candidate path (one map lookup a draw for a known
# stream, a judgement of 68 frames for a new one, at most 96 streams at once); STATIC adds motion pipelines (more pipeline
# and shader compiles at first sight of each cut-out G-buffer pipeline: a one-time hitch each, then cached) and the
# Motion block's work for their draws (a hash-free path: no palette); the census (TOOL) costs one map lookup (at most
# 4096 rows) a G-buffer or sun draw. GPU: STATIC writes the motion target (R32G32B32A32, 16 bytes a pixel) for the cut-out
# static draws that had none (estimated well under 0.1 ms at 1080p internal; not measured); the sway code runs only for
# draws with a sway word (r89's design). Memory: 0 (the census book is at most 4096 rows of about 250 bytes, 1 MB, while it runs).
#
# Files: edits: bbport_wind_twigs.h is NOT touched. New: engine/gpu/shim/bbport_wind_census.h (knobs, book, texts),
# engine/tests/test_wind_census.cpp. Edited: vk_pipeline_cache.cpp (include, SwayWanted clause, motion selection),
# vk_rasterizer.h (include, declaration, member), vk_rasterizer.cpp (routing clause, 2 census sites),
# vk_rasterizer_effects.cpp (the loose rule, WindTwigCensus, the report block), build.sh and gpu/CMakeLists.txt (the test),
# README.md (three rows).
# Order: after r89h (build 48). Compatible with r112j / r62m / wave 37 drafts: the anchors here are r89's Motion block
# lines (the Draw call, the WindTwigSkip chain end, the RtCapture section), r89d's report tail, r89e's WindTwigWord loose
# lines, the SwayWanted tail line and the motion selection's all_motion lines.
#
# Use: python -I -X utf8 r89i_twigs-colour-pass.py check | apply | revert (root from R89I_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89i_backup/ next to this script; revert deletes the two new files.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89i_backup")
ROOT = os.environ.get("R89I_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
CACHE = R + "vk_pipeline_cache.cpp"
RASTH = R + "vk_rasterizer.h"
RAST = R + "vk_rasterizer.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
BUILD = "engine/build.sh"
CMAKE = G + "CMakeLists.txt"
README = "README.md"
NEWH = G + "shim/bbport_wind_census.h"
NEWT = "engine/tests/test_wind_census.cpp"

NEW_FILES = {
    NEWH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89i_twigs-colour-pass): which colour-pass draws the tree twigs (r89d-r89h) can reach, and a census
// that names the draws they do not reach. Three knobs, read once (all only with BB_WIND_TWIGS on):
//   BB_WIND_TWIGS_CENSUS  TOOL (a test aid): 1 logs, every BbWindSway::ReportFrames frames, one row per
//                         (pipeline, position stream) of the G-buffer and sun shadow passes: the render target
//                         kind, cut-out or opaque, motion pipeline or not, sway bit or not, draw kinds, indices,
//                         the largest draw's index range, and the reason a draw got no sway word. Default 0.
//   BB_WIND_TWIGS_PALETTE FEATURE: 1 (default) offers the draws of a cut-out whose small bone palette the GPU
//                         writes (Motion::Kind::GpuPalette, 65 draws a frame in the graveyard of build 48 that
//                         the twig rule never saw) to the twig rule as candidates; a candidate with a bone
//                         palette skips the shape and instance checks (a mesh drawn once for each tree it
//                         stands for has the union of all its places as its box), its height, stillness and
//                         vertex count are still judged. 0: as r89h.
//   BB_WIND_TWIGS_STATIC  FEATURE: 1 (default) gives a G-buffer pipeline with no bone palette whose pixel shader
//                         discards (a cut-out) the motion variant, so it carries the sway bit and its draws
//                         (Motion::Kind::Other) reach the twig rule; 2 also every opaque one (a TEST: the
//                         twig rule's shape checks refuse a building, but the shaders carry the sway code in
//                         many more pipelines); 0: as r89h.
// Header only, pure: engine/tests/test_wind_census.cpp runs it. The rasterizer fills the book
// (Rasterizer::WindTwigCensus), prints the lines (WindTwigsReport) and asks the knobs.
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <utility>
#include <vector>

#include "bbport_wind_twigs.h"

namespace BbWindCensus {
namespace W = BbWindSway;
namespace T = BbWindTwigs;

inline constexpr std::size_t RowsMost = 4096;  ///< (pipeline, stream) rows kept between two reports
inline constexpr std::size_t TopLines = 10;    ///< G-buffer rows with the most indices that are named
inline constexpr std::size_t SwayLines = 6;    ///< rows with the sway bit that are named as well
inline constexpr std::size_t SunLines = 3;     ///< sun shadow rows with the most indices that are named
inline constexpr std::size_t KindSlots = 4;    ///< draws by kind: skinned, GPU palette, static, no motion block
inline constexpr std::size_t KindSkinned = 0, KindPalette = 1, KindStatic = 2, KindNone = 3;
inline constexpr std::uint32_t RangeScanMax = 262144; ///< indices read for the range of a row's first draw

struct Knob {
    bool census = false;  ///< BB_WIND_TWIGS_CENSUS (TOOL)
    bool palette = true;  ///< BB_WIND_TWIGS_PALETTE
    int statics = 1;      ///< BB_WIND_TWIGS_STATIC: 0 none, 1 cut-outs, 2 also opaque (a test)
};

/// The knobs' texts: numbers as the wind knobs read them (unset, empty, unreadable or not finite: the default).
[[nodiscard]] inline Knob ParseKnob(const char* census, const char* palette, const char* statics) {
    Knob k;
    k.census = W::ParseNumber(census, 0.0f) >= 0.5f;
    k.palette = W::ParseNumber(palette, 1.0f) >= 0.5f;
    const float s = W::ParseNumber(statics, 1.0f);
    k.statics = s >= 1.5f ? 2 : (s >= 0.5f ? 1 : 0);
    return k;
}

[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND_TWIGS_CENSUS"), std::getenv("BB_WIND_TWIGS_PALETTE"),
                                       std::getenv("BB_WIND_TWIGS_STATIC"));
    return knob;
}

/// The census runs (the twigs on, BB_WIND_TWIGS_CENSUS=1).
[[nodiscard]] inline bool CensusOn() {
    return T::On() && KnobOnce().census;
}

/// GPU-palette cut-outs are twig candidates (the twigs on, BB_WIND_TWIGS_SMALL above 0, PALETTE on).
[[nodiscard]] inline bool PaletteOn() {
    return T::ReachSmall() && KnobOnce().palette;
}

/// A G-buffer cut-out without a bone palette gets the motion variant and the sway bit.
[[nodiscard]] inline bool StaticCutouts() {
    return T::ReachSmall() && KnobOnce().statics >= 1;
}

/// BB_WIND_TWIGS_STATIC=2: every G-buffer pipeline without a skeleton, opaque too (a test).
[[nodiscard]] inline bool StaticOpaque() {
    return T::ReachSmall() && KnobOnce().statics >= 2;
}

/// Whether a G-buffer pipeline with no bone palette (`discards`: its pixel shader discards) takes the motion variant.
[[nodiscard]] inline bool StaticWanted(bool discards) {
    return discards ? StaticCutouts() : StaticOpaque();
}

enum class Target : std::uint8_t { Gbuffer, Sun };

[[nodiscard]] inline const char* TargetName(Target target) {
    return target == Target::Gbuffer ? "G-buffer" : "sun shadow";
}

/// What the census knows of one (pipeline, position stream) pair of the colour passes.
struct Row {
    std::uintptr_t pipeline = 0;
    std::uint64_t stream = 0;           ///< the position stream's address (0: none found)
    std::uint32_t vs = 0, ps = 0;       ///< low 32 bits of the shader hashes
    Target target = Target::Gbuffer;
    std::uint32_t targets = 0;          ///< colour targets written (not the motion output)
    std::uint32_t format = 0;           ///< the first colour target's data format (the enum's number)
    std::uint32_t depth_w = 0, depth_h = 0;
    bool cutout = false;                ///< the pixel shader discards
    bool sway_bit = false;              ///< the pipeline's key has MotionVectors::Sway
    bool motion = false;                ///< the pipeline writes motion vectors (has a bone palette buffer)
    bool depth_write = false;
    std::uint32_t stream_verts = 0, stride = 0;
    std::uint64_t draws = 0, indices = 0, max_indices = 0;
    std::uint32_t max_first = 0;        ///< first index of the largest draw
    std::int32_t max_base = 0;          ///< base vertex of the largest draw
    std::array<std::uint64_t, KindSlots> kind{};
    std::uint64_t swayed = 0;           ///< draws that got a sway word
    bool ranged = false;                ///< the index range of the row's first draw was tried
    std::uint32_t vmin = 0xffffffffu, vmax = 0; ///< index values of that draw (vmin above vmax: not read)
};

/// The rows since the last report, and the draws counted by target.
class Book {
public:
    /// The row of (pipeline, stream): `fresh` says a new one (to fill); nullptr when RowsMost rows are in use.
    [[nodiscard]] Row* Touch(std::uintptr_t pipeline, std::uint64_t stream, bool& fresh) {
        const std::pair<std::uintptr_t, std::uint64_t> key{pipeline, stream};
        const auto found = index_.find(key);
        fresh = false;
        if (found != index_.end()) {
            return &rows_[found->second];
        }
        if (rows_.size() >= RowsMost) {
            ++overflow;
            return nullptr;
        }
        Row row;
        row.pipeline = pipeline;
        row.stream = stream;
        index_.emplace(key, rows_.size());
        rows_.push_back(row);
        fresh = true;
        return &rows_.back();
    }

    void Clear() {
        rows_.clear();
        index_.clear();
        overflow = 0;
        draws = {};
    }

    [[nodiscard]] const std::vector<Row>& Rows() const {
        return rows_;
    }

    std::uint64_t overflow = 0;                ///< draws whose row did not fit
    std::array<std::uint64_t, 2> draws{};      ///< draws seen by target (G-buffer, sun)

private:
    std::vector<Row> rows_;
    std::map<std::pair<std::uintptr_t, std::uint64_t>, std::size_t> index_; ///< (pipeline, stream) -> row
};

/// One draw of the row: its indices, first index and base vertex (the largest draw is kept), its kind slot
/// (KindSkinned .. KindNone; above the last: the last) and whether it got a sway word.
inline void Count(Row& r, std::size_t kind_slot, std::uint32_t indices, std::uint32_t first, std::int32_t base,
                  bool swayed) {
    ++r.draws;
    r.indices += indices;
    if (indices > r.max_indices) {
        r.max_indices = indices;
        r.max_first = first;
        r.max_base = base;
    }
    r.kind[std::min(kind_slot, KindSlots - 1)] += 1;
    r.swayed += swayed ? 1 : 0;
}

/// The reason a row's draws got no sway word (a string literal, under 130 characters).
[[nodiscard]] inline const char* Why(const Row& r, bool palette_on) {
    if (r.target == Target::Sun) {
        return "sun shadow pass: depth only, no sway bit (the game's own shadow map is not swayed)";
    }
    if (r.swayed > 0) {
        return "swayed";
    }
    if (!r.motion) {
        return r.cutout ? "no motion pipeline (no bone palette buffer): no sway bit; BB_WIND_TWIGS_STATIC=1 gives it"
                        : "no motion pipeline (no bone palette buffer), opaque: no sway bit; BB_WIND_TWIGS_STATIC=2 gives it";
    }
    if (!r.sway_bit) {
        return "motion pipeline without the sway bit (opaque: skinned BB_WIND_TWIGS_REACH=2, static BB_WIND_TWIGS_STATIC=2)";
    }
    if (r.kind[KindPalette] > 0 && !palette_on) {
        return "GPU-written palette: BB_WIND_TWIGS_PALETTE=1 offers it to the twig rule";
    }
    return "sway bit, no word: the twig rule refused it (see the r89e candidate lines)";
}

/// Totals of the rows for the header line.
struct Totals {
    std::uint64_t gbuf_draws = 0, gbuf_cutout = 0, gbuf_motion = 0, gbuf_sway = 0, gbuf_swayed = 0, sun_draws = 0;
    std::uint32_t gbuf_rows = 0, sun_rows = 0, sway_rows = 0;
};

[[nodiscard]] inline Totals TotalsOf(const Book& book) {
    Totals t;
    for (const Row& r : book.Rows()) {
        if (r.target == Target::Gbuffer) {
            ++t.gbuf_rows;
            t.gbuf_draws += r.draws;
            t.gbuf_cutout += r.cutout ? r.draws : 0;
            t.gbuf_motion += r.motion ? r.draws : 0;
            t.gbuf_sway += r.sway_bit ? r.draws : 0;
            t.gbuf_swayed += r.swayed;
        } else {
            ++t.sun_rows;
            t.sun_draws += r.draws;
        }
        t.sway_rows += r.sway_bit ? 1 : 0;
    }
    return t;
}

/// The rows to name: the TopLines G-buffer rows with the most indices, then up to SwayLines rows with the sway
/// bit not named yet (most indices first), then the SunLines sun rows with the most indices.
[[nodiscard]] inline std::vector<const Row*> Pick(const Book& book) {
    std::vector<const Row*> gbuf, sun, sway, out;
    for (const Row& r : book.Rows()) {
        (r.target == Target::Gbuffer ? gbuf : sun).push_back(&r);
        if (r.sway_bit) {
            sway.push_back(&r);
        }
    }
    const auto by_indices = [](const Row* a, const Row* b) {
        if (a->indices != b->indices) {
            return a->indices > b->indices;
        }
        return a->pipeline != b->pipeline ? a->pipeline < b->pipeline : a->stream < b->stream;
    };
    std::sort(gbuf.begin(), gbuf.end(), by_indices);
    std::sort(sun.begin(), sun.end(), by_indices);
    std::sort(sway.begin(), sway.end(), by_indices);
    const auto take = [&out](const std::vector<const Row*>& from, std::size_t count) {
        std::size_t added = 0;
        for (const Row* r : from) {
            if (added >= count) {
                break;
            }
            if (std::find(out.begin(), out.end(), r) == out.end()) {
                out.push_back(r);
                ++added;
            }
        }
    };
    take(gbuf, TopLines);
    take(sway, SwayLines);
    take(sun, SunLines);
    return out;
}

/// The header line of a report (under 700 characters).
inline void HeaderLine(const Book& book, bool palette_on, const Knob& knob, char* out, std::size_t size) {
    const Totals t = TotalsOf(book);
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs colour pass (r89i): in %u frames the colour passes drew: G-buffer %llu draws on %u rows "
                  "(%llu cut-out, %llu on motion pipelines, %llu on pipelines with the sway bit, %llu given a sway word), "
                  "sun shadow %llu draws on %u rows; %u rows have the sway bit; %llu draws did not fit in %u rows; "
                  "BB_WIND_TWIGS_PALETTE %d, BB_WIND_TWIGS_STATIC %d; named: the %u G-buffer rows with the most indices, "
                  "the rows with the sway bit, the %u sun rows with the most indices",
                  static_cast<unsigned>(W::ReportFrames), n(t.gbuf_draws), t.gbuf_rows, n(t.gbuf_cutout),
                  n(t.gbuf_motion), n(t.gbuf_sway), n(t.gbuf_swayed), n(t.sun_draws), t.sun_rows, t.sway_rows,
                  n(book.overflow), static_cast<unsigned>(RowsMost), palette_on ? 1 : 0, knob.statics,
                  static_cast<unsigned>(TopLines), static_cast<unsigned>(SunLines));
}

/// One row's line (under 700 characters).
inline void RowLine(const Row& r, unsigned rank, bool palette_on, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    char range[40];
    if (r.vmin <= r.vmax) {
        std::snprintf(range, sizeof(range), "%u-%u", r.vmin, r.vmax);
    } else {
        std::snprintf(range, sizeof(range), "not read");
    }
    std::snprintf(out, size,
                  "Wind twigs colour pass (r89i) #%u: %s pass, %u colour targets (first format %u), depth %ux%u%s, "
                  "vs %08x ps %08x, %s, %s, sway bit %s; stream %u vertices at stride %u; draws %llu (skinned %llu, "
                  "GPU palette %llu, static %llu, no motion block %llu), %llu swayed; %llu indices, largest draw %llu "
                  "from index %u at base vertex %d, index values %s; %s",
                  rank, TargetName(r.target), r.targets, r.format, r.depth_w, r.depth_h,
                  r.depth_write ? ", depth write" : ", depth test only", r.vs, r.ps,
                  r.cutout ? "cut-out" : "opaque", r.motion ? "motion pipeline" : "no motion pipeline",
                  r.sway_bit ? "YES" : "no", r.stream_verts, r.stride, n(r.draws), n(r.kind[KindSkinned]),
                  n(r.kind[KindPalette]), n(r.kind[KindStatic]), n(r.kind[KindNone]), n(r.swayed), n(r.indices),
                  n(r.max_indices), r.max_first, static_cast<int>(r.max_base), range, Why(r, palette_on));
}

/// The once line (under 700 characters).
inline void OnceText(const Knob& k, char* out, std::size_t size) {
    const bool small_on = T::ReachSmall();
    std::snprintf(out, size,
                  "Wind twigs (r89i, BB_WIND_TWIGS_PALETTE=%d, BB_WIND_TWIGS_STATIC=%d, BB_WIND_TWIGS_CENSUS=%d): "
                  "cut-outs whose small bone palette the GPU writes %s twig candidates (a candidate with a bone palette "
                  "skips the shape and instance checks); G-buffer cut-outs without a bone palette %s the motion "
                  "variant and the sway bit%s; the census %s",
                  k.palette ? 1 : 0, k.statics, k.census ? 1 : 0,
                  small_on && k.palette ? "are" : "are not", small_on && k.statics >= 1 ? "take" : "do not take",
                  small_on && k.statics >= 2 ? " (opaque ones too: a test)" : "",
                  k.census ? "logs a block of 'Wind twigs colour pass (r89i)' lines every report" : "is off");
}

} // namespace BbWindCensus
''',
    NEWT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89i_twigs-colour-pass): the colour-pass census and its knobs (shim/bbport_wind_census.h).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>

#include "gpu/shim/bbport_wind_census.h"

namespace C = BbWindCensus;

static int failures = 0;

static void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

// A draw of `indices` indices in the row of (pipeline, stream); the row's facts are set when it is new.
static C::Row* Add(C::Book& book, std::uintptr_t pipeline, std::uint64_t stream, C::Target target,
                   std::uint32_t indices, bool sway_bit, bool motion, bool cutout) {
    bool fresh = false;
    C::Row* const row = book.Touch(pipeline, stream, fresh);
    if (row == nullptr) {
        return nullptr;
    }
    if (fresh) {
        row->target = target;
        row->sway_bit = sway_bit;
        row->motion = motion;
        row->cutout = cutout;
    }
    C::Count(*row, C::KindStatic, indices, 0, 0, false);
    return row;
}

static bool Contains(const std::vector<const C::Row*>& rows, std::uintptr_t pipeline) {
    for (const C::Row* r : rows) {
        if (r->pipeline == pipeline) {
            return true;
        }
    }
    return false;
}

int main() {
    // The knobs: unset is census off, palette on, statics 1; numbers as the wind knobs read them.
    {
        const C::Knob d = C::ParseKnob(nullptr, nullptr, nullptr);
        Expect(!d.census && d.palette && d.statics == 1, "defaults: census off, palette on, statics 1");
        const C::Knob off = C::ParseKnob("1", "0", "0");
        Expect(off.census && !off.palette && off.statics == 0, "1, 0, 0");
        const C::Knob odd = C::ParseKnob("x", "nan", "2");
        Expect(!odd.census && odd.palette && odd.statics == 2, "unreadable: the default; statics 2");
        Expect(C::ParseKnob(nullptr, nullptr, "9").statics == 2, "statics above 2: 2");
        Expect(C::ParseKnob(nullptr, nullptr, "0.4").statics == 0, "statics 0.4: 0");
        Expect(C::ParseKnob(nullptr, nullptr, "1.2").statics == 1, "statics 1.2: 1");
        Expect(C::ParseKnob("", "", "").statics == 1 && C::ParseKnob("", "", "").palette, "empty: the default");
        // no BB_WIND here: the twigs are off, so nothing is asked of the pipelines
        Expect(!C::CensusOn() && !C::PaletteOn() && !C::StaticCutouts() && !C::StaticOpaque() &&
                   !C::StaticWanted(true) && !C::StaticWanted(false),
               "the twigs off: no census, no widening");
    }

    // The book: one row for a (pipeline, stream), a new one is fresh, RowsMost rows at most.
    {
        C::Book book;
        bool fresh = false;
        C::Row* const a = book.Touch(1, 10, fresh);
        Expect(a != nullptr && fresh, "a new row is fresh");
        C::Row* const again = book.Touch(1, 10, fresh);
        Expect(again == book.Rows().data() && !fresh, "the same key: the same row, not fresh");
        Expect(book.Touch(1, 11, fresh) != nullptr && fresh, "another stream: a new row");
        Expect(book.Touch(2, 10, fresh) != nullptr && fresh, "another pipeline: a new row");
        Expect(book.Rows().size() == 3, "three rows");
        for (std::uintptr_t i = 0; i < C::RowsMost + 3; ++i) {
            (void)book.Touch(100 + i, 0, fresh);
        }
        Expect(book.Rows().size() == C::RowsMost, "no more than RowsMost rows");
        Expect(book.overflow == 6, "rows over the limit are counted");
        Expect(book.Touch(1, 10, fresh) != nullptr && !fresh, "a known row is found when the book is full");
        book.Clear();
        Expect(book.Rows().empty() && book.overflow == 0 && book.draws[0] == 0, "Clear");
    }

    // Count: indices, the largest draw, the kind slots (above the last: the last), the sway words.
    {
        C::Row r;
        C::Count(r, C::KindSkinned, 300, 5, 7, true);
        C::Count(r, C::KindPalette, 900, 11, -3, false);
        C::Count(r, 99, 100, 1, 1, true);
        Expect(r.draws == 3 && r.indices == 1300, "draws and indices");
        Expect(r.max_indices == 900 && r.max_first == 11 && r.max_base == -3,
               "the largest draw's first index and base");
        Expect(r.kind[C::KindSkinned] == 1 && r.kind[C::KindPalette] == 1 && r.kind[C::KindNone] == 1,
               "kind slots, an unknown slot is the last");
        Expect(r.swayed == 2, "swayed draws");
    }

    // Why: the reason a row got no word.
    {
        C::Row r;
        r.target = C::Target::Sun;
        Expect(std::strstr(C::Why(r, true), "sun shadow") != nullptr, "sun row");
        r.target = C::Target::Gbuffer;
        r.motion = false;
        r.cutout = true;
        Expect(std::strstr(C::Why(r, true), "BB_WIND_TWIGS_STATIC=1") != nullptr,
               "cut-out without a motion pipeline");
        r.cutout = false;
        Expect(std::strstr(C::Why(r, true), "STATIC=2") != nullptr, "opaque without a motion pipeline");
        r.motion = true;
        Expect(std::strstr(C::Why(r, true), "without the sway bit") != nullptr, "motion pipeline, no sway bit");
        r.sway_bit = true;
        r.kind[C::KindPalette] = 4;
        Expect(std::strstr(C::Why(r, false), "BB_WIND_TWIGS_PALETTE=1") != nullptr, "GPU palette, knob off");
        Expect(std::strstr(C::Why(r, true), "refused it") != nullptr, "sway bit, rule refused");
        r.swayed = 1;
        Expect(std::strcmp(C::Why(r, true), "swayed") == 0, "swayed");
        r.swayed = 0;
        r.motion = false;
        r.sway_bit = false;
        Expect(std::strlen(C::Why(r, false)) < 130, "reasons stay short");
    }

    // Pick: the top G-buffer rows, the sway rows not named yet, the top sun rows; most indices first.
    {
        C::Book book;
        for (std::uintptr_t i = 1; i <= 12; ++i) {
            (void)Add(book, i, i, C::Target::Gbuffer, static_cast<std::uint32_t>(i * 1000), false, true, true);
        }
        (void)Add(book, 50, 1, C::Target::Gbuffer, 5, true, true, true);  // a small row with the sway bit
        (void)Add(book, 51, 1, C::Target::Gbuffer, 6, true, true, true);  // another
        (void)Add(book, 12, 99, C::Target::Gbuffer, 4, true, true, true); // a sway row of a top pipeline's other stream
        for (std::uintptr_t i = 1; i <= 5; ++i) {
            (void)Add(book, 200 + i, 0, C::Target::Sun, static_cast<std::uint32_t>(i * 10), false, false, true);
        }
        const std::vector<const C::Row*> picked = C::Pick(book);
        Expect(picked.size() == C::TopLines + 3 + C::SunLines, "10 top rows, 3 sway rows, 3 sun rows");
        Expect(picked.front()->pipeline == 12 && picked.front()->stream == 12, "the row with the most indices is first");
        Expect(picked[1]->indices == 11000 && picked[C::TopLines - 1]->indices == 3000, "most indices first");
        Expect(!Contains(picked, 1) && !Contains(picked, 2), "the two smallest of the 12 are not named");
        Expect(Contains(picked, 50) && Contains(picked, 51) && Contains(picked, 12), "the sway rows are named");
        Expect(Contains(picked, 205) && Contains(picked, 203) && !Contains(picked, 202), "the 3 biggest sun rows");
        const C::Totals t = C::TotalsOf(book);
        Expect(t.gbuf_rows == 15 && t.sun_rows == 5 && t.sway_rows == 3, "rows by target and the sway bit");
        Expect(t.gbuf_draws == 15 && t.sun_draws == 5 && t.gbuf_sway == 3 && t.gbuf_cutout == 15, "draws by target");
        Expect(t.gbuf_motion == 15 && t.gbuf_swayed == 0, "motion draws and swayed draws");
    }

    // The log lines stay under 700 characters, at the largest numbers, and say the facts.
    {
        C::Row r;
        r.pipeline = 0x1234;
        r.stream = 0x7fffffffffffull;
        r.vs = 0x6a833138u;
        r.ps = 0x1c3953c6u;
        r.targets = 5;
        r.format = 9;
        r.depth_w = 3840;
        r.depth_h = 2160;
        r.cutout = true;
        r.motion = true;
        r.sway_bit = true;
        r.depth_write = true;
        r.stream_verts = 156641;
        r.stride = 12;
        C::Count(r, C::KindStatic, 960, 0, 0, true);
        char text[720];
        C::RowLine(r, 1, true, text, sizeof(text));
        Expect(std::strstr(text, "vs 6a833138 ps 1c3953c6") != nullptr && std::strstr(text, "sway bit YES") != nullptr &&
                   std::strstr(text, "G-buffer pass, 5 colour targets") != nullptr &&
                   std::strstr(text, "stream 156641 vertices at stride 12") != nullptr &&
                   std::strstr(text, "index values not read") != nullptr &&
                   std::strstr(text, ", 1 swayed; 960 indices") != nullptr,
               "the row line's facts");
        r.vmin = 3;
        r.vmax = 959;
        C::RowLine(r, 1, true, text, sizeof(text));
        Expect(std::strstr(text, "index values 3-959") != nullptr, "the index range");
        // the largest numbers
        r.draws = r.indices = r.max_indices = std::numeric_limits<std::uint64_t>::max();
        r.swayed = std::numeric_limits<std::uint64_t>::max();
        for (std::uint64_t& k : r.kind) {
            k = std::numeric_limits<std::uint64_t>::max();
        }
        r.max_first = 0xffffffffu;
        r.max_base = std::numeric_limits<std::int32_t>::min();
        r.stream_verts = 0xffffffffu;
        r.stride = 0xffffffffu;
        r.vmin = 0;
        r.vmax = 0xfffffffeu;
        r.sway_bit = true;
        r.swayed = 0;
        r.motion = false;
        r.cutout = false;
        C::RowLine(r, 99, false, text, sizeof(text));
        Expect(std::strlen(text) < 700 && std::strlen(text) + 1 < sizeof(text), "the row line at the largest numbers");

        C::Book book;
        (void)Add(book, 1, 1, C::Target::Gbuffer, 100, true, true, true);
        char header[720];
        C::HeaderLine(book, true, C::ParseKnob(nullptr, nullptr, nullptr), header, sizeof(header));
        Expect(std::strstr(header, "G-buffer 1 draws on 1 rows (1 cut-out, 1 on motion pipelines, 1 on pipelines with "
                                   "the sway bit, 0 given a sway word)") != nullptr,
               "the header line's counts");
        Expect(std::strlen(header) < 700, "the header line is under 700 characters");
        char once[720];
        C::OnceText(C::ParseKnob("1", "1", "2"), once, sizeof(once));
        Expect(std::strncmp(once, "Wind twigs (r89i, BB_WIND_TWIGS_PALETTE=1, BB_WIND_TWIGS_STATIC=2, BB_WIND_TWIGS_CENSUS=1)", 90) == 0 &&
                   std::strlen(once) < 700,
               "the once line");
    }

    if (failures == 0) {
        std::printf("wind-census-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
''',
}

# ---------------------------------------------------------------- vk_pipeline_cache.cpp
PC_INC_OLD = '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
PC_INC_NEW = PC_INC_OLD + '#include "bbport_wind_census.h" // bbport (r89i_twigs-colour-pass)\n'

PC_WANT_OLD = "            (BbWindTwigs::ReachOpaque() && SkeletonRead(sel)));\n"
PC_WANT_NEW = (
    "            (BbWindTwigs::ReachOpaque() && SkeletonRead(sel)) ||\n"
    "            // bbport (r89i_twigs-colour-pass): BB_WIND_TWIGS_STATIC=2 (a test): also an opaque pipeline with no skeleton\n"
    "            (BbWindCensus::StaticOpaque() && !SkeletonRead(sel)));\n")

PC_MOTION_OLD = ("        if (all_motion) {\n"
                 "            sel.motion = true;\n"
                 "        }\n"
                 "        if (sel.motion && !RefreshGraphicsStages(sel)) {\n")
PC_MOTION_NEW = (
    "        if (all_motion) {\n"
    "            sel.motion = true;\n"
    "        }\n"
    "        // bbport (r89i_twigs-colour-pass): BB_WIND_TWIGS_STATIC: a G-buffer pipeline with no bone palette whose pixel\n"
    "        // shader discards (a cut-out; =2: any) takes the motion variant, so it can carry the sway bit (SwayWanted)\n"
    "        if (!sel.motion && vs && BbWindCensus::StaticWanted(FragmentDiscards(sel))) {\n"
    "            sel.motion = true;\n"
    "        }\n"
    "        if (sel.motion && !RefreshGraphicsStages(sel)) {\n")

# ---------------------------------------------------------------- vk_rasterizer.h
RH_INC_OLD = '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
RH_INC_NEW = RH_INC_OLD + '#include "bbport_wind_census.h" // bbport (r89i_twigs-colour-pass)\n'

RH_DECL_OLD = "    void WindTwigsReport();\n"
RH_DECL_NEW = RH_DECL_OLD + (
    "    /// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of a colour pass for the census\n"
    "    /// (kind_slot: BbWindCensus::KindSkinned .. KindNone; sway: its sway word; base_vertex: its base vertex)\n"
    "    void WindTwigCensus(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, bool is_indexed,\n"
    "                        u32 index_offset, int kind_slot, u32 sway, int base_vertex);\n")

RH_MEMBER_OLD = "    BbWindTwigs::Stats twig_stats; // and the line's counts\n"
RH_MEMBER_NEW = RH_MEMBER_OLD + "    BbWindCensus::Book twig_census; // bbport (r89i_twigs-colour-pass, TOOL): the colour passes' rows\n"

# ---------------------------------------------------------------- vk_rasterizer.cpp
RC_ROUTE_OLD = ("                // bbport (r89d_tree-twigs): 0, counting (twigs on) the draws the sway cannot reach\n"
                "                : WindTwigSkip(r34_kind == Motion::Kind::Skinned,\n")
RC_ROUTE_NEW = (
    "                // bbport (r89i_twigs-colour-pass): a cut-out whose small bone palette the GPU writes is a twig\n"
    "                // candidate too (BB_WIND_TWIGS_PALETTE): the rule of the static cut-outs above\n"
    "                : (r34_kind == Motion::Kind::GpuPalette && BbWindCensus::PaletteOn() &&\n"
    "                   (pipeline->GetGraphicsKey().motion_vectors & Shader::MotionVectors::Sway) != 0)\n"
    "                    ? WindSwayWord(pipeline, 1)\n" + RC_ROUTE_OLD)

RC_SITE_A_OLD = "        dc.push_data.motion_param = object_motion->Draw({\n"
RC_SITE_A_NEW = (
    "        if (BbWindCensus::CensusOn()) { // bbport (r89i_twigs-colour-pass, TOOL): this draw's row\n"
    "            WindTwigCensus(pipeline, regs, is_indexed, index_offset,\n"
    "                           r34_kind == Motion::Kind::Skinned\n"
    "                               ? int(BbWindCensus::KindSkinned)\n"
    "                               : (r34_kind == Motion::Kind::GpuPalette ? int(BbWindCensus::KindPalette)\n"
    "                                                                       : int(BbWindCensus::KindStatic)),\n"
    "                           sway, int(base_vertex));\n"
    "        }\n" + RC_SITE_A_OLD)

RC_SITE_B_OLD = "    if (dc.capture_draw) {\n        BB_SECTION(RtCapture);\n"
RC_SITE_B_NEW = (
    "    if (BbWindCensus::CensusOn() && !(dc.motion_draw && dc.motion_geometry)) { // bbport (r89i_twigs-colour-pass, TOOL)\n"
    "        WindTwigCensus(pipeline, regs, is_indexed, index_offset, int(BbWindCensus::KindNone), 0u,\n"
    "                       int(GetDrawOffsets(regs, pipeline->GetStage(Shader::SwStage::Vertex),\n"
    "                                          pipeline->GetFetchShader()).first));\n"
    "    }\n" + RC_SITE_B_OLD)

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_LOOSE_OLD = ("        entry.loose = BbWindTwigs::SmallLoose();\n"
                "        if (const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(positions)) {\n"
                "            entry.per_frame = info->max_per_frame;\n"
                "        }\n")
EF_LOOSE_NEW = (
    "        entry.loose = BbWindTwigs::SmallLoose();\n"
    "        if (const BbWindTwigs::SmallInfo* const info = twig_book.FindInfo(positions)) {\n"
    "            entry.per_frame = info->max_per_frame;\n"
    "            // bbport (r89i_twigs-colour-pass): BB_WIND_TWIGS_PALETTE: a stream with a bone palette is judged\n"
    "            // without the shape and instance checks (one mesh drawn once for each tree it stands for has the\n"
    "            // union of all its places as its box); its height, stillness and vertex count still count\n"
    "            entry.loose = entry.loose || (BbWindCensus::PaletteOn() && info->palette);\n"
    "        }\n")

EF_FUNC_OLD = "// bbport (r89d_tree-twigs): the twigs' line every BbWindSway::ReportFrames frame ends: the census\n"
EF_FUNC_NEW = r'''// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of the G-buffer or a sun shadow pass
// for the census (bbport_wind_census.h): the pipeline's row (render target kind, colour targets and first format,
// depth, shader hashes, cut-out, motion pipeline, sway bit, position stream) is made the first time, the draw is
// counted (indices, the largest draw's first index and base vertex, its kind, whether it got a sway word) and the
// first draw of a row has its index values' range read from guest memory (at most BbWindCensus::RangeScanMax
// indices, once a row and report). Draws of other passes are left out. On the thread recording draws.
void Rasterizer::WindTwigCensus(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, bool is_indexed,
                                u32 index_offset, int kind_slot, u32 sway, int base_vertex) {
    const auto& key = pipeline->GetGraphicsKey();
    const u32 colour = key.mrt_mask & ~(1u << Shader::MotionVectors::Output);
    BbWindCensus::Target target = BbWindCensus::Target::Gbuffer;
    if (!gbuffer_draw) {
        const bool sun_pass = colour == 0 && regs.depth_buffer.DepthValid() &&
                              regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
                              regs.depth_buffer.Height() >= 1024;
        if (!sun_pass) {
            return;
        }
        target = BbWindCensus::Target::Sun;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    u64 positions = 0;
    u32 positions_size = 0;
    u32 positions_stride = 0;
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                positions = stream.base_address;
                positions_size = stream.GetSize();
                positions_stride = stream.GetStride();
                break;
            }
        }
    }
    ++twig_census.draws[target == BbWindCensus::Target::Gbuffer ? 0 : 1];
    bool fresh = false;
    BbWindCensus::Row* const row =
        twig_census.Touch(reinterpret_cast<std::uintptr_t>(pipeline), positions, fresh);
    if (row == nullptr) {
        return;
    }
    if (fresh) {
        const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        row->vs = static_cast<u32>(vs.pgm_hash & 0xffffffffu);
        row->ps = static_cast<u32>(FragmentHash(pipeline) & 0xffffffffu);
        row->target = target;
        row->targets = static_cast<u32>(std::popcount(colour));
        row->format = colour != 0 ? static_cast<u32>(key.color_buffers[std::countr_zero(colour)].data_format) : 0u;
        row->depth_w = regs.depth_buffer.Pitch();
        row->depth_h = regs.depth_buffer.Height();
        row->cutout = ps != nullptr && ps->has_discard;
        row->sway_bit = (key.motion_vectors & Shader::MotionVectors::Sway) != 0;
        row->motion = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
        row->depth_write = regs.depth_control.depth_write_enable != 0;
        row->stride = positions_stride;
        row->stream_verts = positions_stride != 0 ? positions_size / positions_stride : 0u;
    }
    BbWindCensus::Count(*row, static_cast<std::size_t>(kind_slot), regs.num_indices, index_offset, base_vertex,
                        sway != 0);
    if (!row->ranged && is_indexed && regs.num_indices != 0) {
        row->ranged = true;
        const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
        const VAddr address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
        const u64 bytes = u64(regs.num_indices) * index_size;
        if (memory->IsValidGpuMapping(address, 0) && memory->ClampRangeSize(address, bytes) == bytes) {
            const unsigned char* const data = reinterpret_cast<const unsigned char*>(address);
            const u32 count = std::min<u32>(regs.num_indices, BbWindCensus::RangeScanMax);
            u32 lo = 0xffffffffu;
            u32 hi = 0;
            for (u32 i = 0; i < count; ++i) {
                u32 value = 0;
                if (index_size == 2) {
                    u16 narrow = 0;
                    std::memcpy(&narrow, data + u64(i) * 2, sizeof(narrow));
                    value = narrow == 0xffffu ? 0xffffffffu : u32(narrow); // the restart index is no vertex
                } else {
                    std::memcpy(&value, data + u64(i) * 4, sizeof(value));
                }
                if (value == 0xffffffffu) {
                    continue;
                }
                lo = std::min(lo, value);
                hi = std::max(hi, value);
            }
            if (lo <= hi) {
                row->vmin = lo;
                row->vmax = hi;
            }
        }
    }
}

''' + EF_FUNC_OLD

EF_REPORT_OLD = "        twig_proof_draws.clear();\n    }\n    twig_stats = {};\n}\n"
EF_REPORT_NEW = (
    "        twig_proof_draws.clear();\n"
    "    }\n"
    "    // bbport (r89i_twigs-colour-pass): its once line (with the first report), and with BB_WIND_TWIGS_CENSUS=1 (TOOL) the\n"
    "    // colour passes' census: a header line and the rows (BbWindCensus::Pick), then the book is emptied\n"
    "    static bool census_said = false;\n"
    "    if (!census_said) {\n"
    "        census_said = true;\n"
    "        char census_once[704];\n"
    "        BbWindCensus::OnceText(BbWindCensus::KnobOnce(), census_once, sizeof(census_once));\n"
    "        BbReport::Printf(\"%s\\n\", census_once);\n"
    "    }\n"
    "    if (BbWindCensus::CensusOn()) {\n"
    "        char census_text[704];\n"
    "        BbWindCensus::HeaderLine(twig_census, BbWindCensus::PaletteOn(), BbWindCensus::KnobOnce(), census_text,\n"
    "                                 sizeof(census_text));\n"
    "        BbReport::Printf(\"%s\\n\", census_text);\n"
    "        unsigned census_rank = 0;\n"
    "        for (const BbWindCensus::Row* const census_row : BbWindCensus::Pick(twig_census)) {\n"
    "            BbWindCensus::RowLine(*census_row, ++census_rank, BbWindCensus::PaletteOn(), census_text,\n"
    "                                  sizeof(census_text));\n"
    "            BbReport::Printf(\"%s\\n\", census_text);\n"
    "        }\n"
    "        twig_census.Clear();\n"
    "    }\n"
    "    twig_stats = {};\n"
    "}\n")

# ---------------------------------------------------------------- build.sh, CMake, README
BS_OLD = "    out/wind-sway-test\n"
BS_NEW = BS_OLD + (
    "    # bbport (r89i_twigs-colour-pass): the colour-pass census and its knobs\n"
    "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_census.cpp -o out/wind-census-test\n"
    "    out/wind-census-test\n")

CM_OLD = "target_include_directories(wind-sway-test PRIVATE ..)\n"
CM_NEW = CM_OLD + (
    "# bbport (r89i_twigs-colour-pass): the colour-pass census and its knobs (shim/bbport_wind_census.h); also built and\n"
    "# run by engine/build.sh --test.\n"
    "add_executable(wind-census-test EXCLUDE_FROM_ALL ../tests/test_wind_census.cpp)\n"
    "target_compile_options(wind-census-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
    "target_include_directories(wind-census-test PRIVATE ..)\n")

README_ANCHOR = "| `BB_WIND_HANG_STATIC` |"
README_NEW = (
    "| `BB_WIND_TWIGS_PALETTE` | Which draws the twigs may see (`BB_WIND_TWIGS` and `BB_WIND_TWIGS_SMALL` rows; r89i): `1` (default) the draws of a cut-out whose small bone palette the GPU writes (65 draws a frame in the graveyard of build 48, which no twig rule ever saw) are offered to the twig rule as candidates, and a candidate stream with a bone palette is judged without the shape and instance checks of `BB_WIND_TWIGS_SMALL` (one mesh drawn once for each tree it stands for has the union of all its places as its box): its height (4 to 40 m), stillness and vertex count still count. `0` r89h's rule. Read once. Log: once `Wind twigs (r89i, ...)`. Off: no code path changes; on: the candidate path's work for those draws (a lookup a draw, a judgement of 68 frames a new stream); not measured | `1` |\n"
    "| `BB_WIND_TWIGS_STATIC` | Which pipelines may carry the twigs' sway bit (`BB_WIND_TWIGS` and `BB_WIND_TWIGS_SMALL` rows; r89i): the sway bit exists only on a motion pipeline, and a G-buffer pipeline whose vertex shader reads no bone palette never was one. `1` (default) a G-buffer pipeline with no bone palette whose pixel shader discards (a cut-out: branch cards, foliage) takes the motion variant and so the sway bit; its draws go to the static cut-out rule of `BB_WIND_TWIGS_SMALL`. `2` a TEST: every G-buffer pipeline without a skeleton, opaque ones too (the rule's shape checks refuse a building or the ground, but the shaders carry the sway code in many more pipelines). `0` r89h. Read once. Cost: more pipeline and shader compiles at first sight (a one-time hitch each) and the motion target (16 bytes a pixel) written for those draws, about 0.1 ms or less at 1080p internal (estimate, not measured). The game's own sun shadow maps stay unswayed | `1` |\n"
    "| `BB_WIND_TWIGS_CENSUS` | TOOL (a test aid, r89i; goes to the test-tools branch): `1` logs, with the twigs' lines every 600 frames, a header line and rows `Wind twigs colour pass (r89i)`: per (pipeline, position stream) of the G-buffer and sun shadow passes the render target kind, colour targets and first format, depth size and write, shader hashes, cut-out or opaque, motion pipeline or not, sway bit or not, the stream's vertices and stride, draws by kind (skinned, GPU palette, static, no motion block), draws given a sway word, indices, the largest draw's first index, base vertex and index values, and why there is no sway word. The 10 G-buffer rows with the most indices, every row with the sway bit (6 more at most) and the 3 sun rows with the most indices are named; the book holds 4096 rows; the index values of a row's first draw are read from guest memory (at most 262144 indices). A draw's place on screen is not known, so the biggest draws stand for the trees. Default `0`: two tests of a static bool a draw | `0` |\n"
    + README_ANCHOR)

EDITS = {
    CACHE: [(PC_INC_OLD, PC_INC_NEW), (PC_WANT_OLD, PC_WANT_NEW), (PC_MOTION_OLD, PC_MOTION_NEW)],
    RASTH: [(RH_INC_OLD, RH_INC_NEW), (RH_DECL_OLD, RH_DECL_NEW), (RH_MEMBER_OLD, RH_MEMBER_NEW)],
    RAST: [(RC_ROUTE_OLD, RC_ROUTE_NEW), (RC_SITE_A_OLD, RC_SITE_A_NEW), (RC_SITE_B_OLD, RC_SITE_B_NEW)],
    EFFECTS: [(EF_LOOSE_OLD, EF_LOOSE_NEW), (EF_FUNC_OLD, EF_FUNC_NEW), (EF_REPORT_OLD, EF_REPORT_NEW)],
    BUILD: [(BS_OLD, BS_NEW)],
    CMAKE: [(CM_OLD, CM_NEW)],
    README: [(README_ANCHOR, README_NEW)],
}

CHECKS = {
    CACHE: [("BbWindCensus::StaticWanted(FragmentDiscards(sel))", 1), ("BbWindCensus::StaticOpaque()", 1),
            ('#include "bbport_wind_census.h"', 1)],
    RASTH: [("void WindTwigCensus(", 1), ("BbWindCensus::Book twig_census;", 1), ('#include "bbport_wind_census.h"', 1)],
    RAST: [("BbWindCensus::PaletteOn()", 1), ("WindTwigCensus(pipeline, regs, is_indexed, index_offset", 2),
           ("WindSwayWord(pipeline, 1)", 1)],
    EFFECTS: [("void Rasterizer::WindTwigCensus(", 1), ("BbWindCensus::PaletteOn() && info->palette", 1),
              ("BbWindCensus::Pick(twig_census)", 1), ("BbWindCensus::OnceText(", 1)],
    BUILD: [("tests/test_wind_census.cpp", 1)],
    CMAKE: [("add_executable(wind-census-test", 1)],
    README: [("| `BB_WIND_TWIGS_PALETTE` |", 1), ("| `BB_WIND_TWIGS_STATIC` |", 1), ("| `BB_WIND_TWIGS_CENSUS` |", 1),
             ("| `BB_WIND_HANG_STATIC` |", 1)],
}

# Numbers written twice: the header's constants and the README rows' text.
CENSUS_ROW = "| `BB_WIND_TWIGS_CENSUS`"
TIES = [("inline constexpr std::size_t TopLines = 10", CENSUS_ROW, "The 10 G-buffer rows"),
        ("inline constexpr std::size_t SwayLines = 6", CENSUS_ROW, "(6 more at most)"),
        ("inline constexpr std::size_t SunLines = 3", CENSUS_ROW, "the 3 sun rows"),
        ("inline constexpr std::size_t RowsMost = 4096", CENSUS_ROW, "the book holds 4096 rows"),
        ("inline constexpr std::uint32_t RangeScanMax = 262144", CENSUS_ROW, "at most 262144 indices")]


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
    for const, row_start, value in TIES:
        rows = "\n".join(l for l in texts[README].split("\n") if l.startswith(row_start))
        if NEW_FILES[NEWH].count(const) != 1 or value not in rows:
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
    # a macro-named identifier (far, near) must not appear as a variable in the new C++ text
    allnew = NEW_FILES[NEWH] + NEW_FILES[NEWT] + "".join(n for p, es in EDITS.items() if p != README for _, n in es)
    for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near"):
        if bad in allnew:
            raise SystemExit("the name %r is a macro on some Windows headers" % bad)
    for path, new in NEW_FILES.items():
        if new.count("{") != new.count("}") or new.count("(") != new.count(")"):
            raise SystemExit("%s: braces or parentheses do not balance" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89I_ROOT)" % ROOT)
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
            tmp = full + ".r89itmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, content in NEW_FILES.items():  # new files take the line ends of the tree (CRLF)
            full = os.path.join(ROOT, path)
            tmp = full + ".r89itmp"
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
        tmp = full + ".r89itmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
