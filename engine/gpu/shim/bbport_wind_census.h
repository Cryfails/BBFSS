// SPDX-License-Identifier: GPL-3.0-or-later
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
