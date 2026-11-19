// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89j_twigs-pick-trees): which draws are the trees (BB_WIND_TWIGS_TREES) and a pixel pick that names the
// draw that wrote the final depth at a screen pixel (BB_WIND_TWIGS_PICK, TOOL). Pure parts only: the knob texts,
// the tree shape rule on a draw's own vertices, the book of verdicts, the pick's points, rectangles, winner rule
// and log lines. The rasterizer (vk_rasterizer_effects.cpp) reads the guest memory and records the queries.
//
//   BB_WIND_TWIGS_TREES   FEATURE (default 0): 1 takes the tree draws for the twigs by the shape of the draw's own
//                         vertices (a trunk that is narrow against a crown that spreads wide), never by the
//                         pipeline; keys the draw's vertex range as a mesh of its own (the box keys then measure
//                         one tree, not the union of a stand), and replaces the fit rule (a vertex's height over
//                         the camera) by the mesh rule (height in the mesh x distance from its centre line).
//   BB_WIND_TWIGS_PICK    TOOL (default off): "x,y;x,y;..." (or "x:y;...") output pixels (at most PickMost); with
//                         BB_WIND_TWIGS_PICK_SIZE=WxH (default 1280x720: the picture the pixels are read from) and
//                         BB_WIND_TWIGS_PICK_FRAME=N (default 900: the first frame of the pick, which draws only
//                         a 3x3 pixel patch of the G-buffer for PickFramesPerPoint frames a point).
// Header only: engine/tests/test_wind_trees.cpp runs it.
#pragma once

#include <algorithm>
#include <array>
#include <atomic> // bbport (r86l_glint-pick-glass)
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <vector>

#include "bbport_wind_twigs.h"

namespace BbWindTrees {
namespace W = BbWindSway;
namespace T = BbWindTwigs;

inline constexpr std::size_t ShapeSamples = 4096;        ///< vertices read at most for a draw's shape
inline constexpr std::uint32_t ShapeIndexMax = 262144;   ///< indices read at most for a draw's vertex range
inline constexpr std::size_t PartMin = 8;                ///< vertices a trunk part or a crown part needs
inline constexpr float AxisShare = 0.10f;                ///< the lowest tenth of the height sets the trunk axis
inline constexpr float TrunkShare = 0.25f, CrownShare = 0.50f; ///< lowest quarter: trunk; upper half: crown
inline constexpr float TrunkPct = 0.80f, CrownPct = 0.90f;     ///< percentiles of the distance from the axis
inline constexpr float SpreadMin = 2.5f;                 ///< crown radius at least this many trunk radii
inline constexpr float CrownMin = 0.25f, CrownMax = 1.6f;      ///< crown radius of the height (not a spire, not a fan)
inline constexpr float TrunkMax = 0.15f;                 ///< trunk radius at most this share of the height (thin)
inline constexpr float RadiusFloor = 0.01f;              ///< trunk radius at least this share of the height
/// bbport (r89p_twigs-really-move): the camera's open wind share (r117's field: 1 - the shelter at the camera) the trees route needs.
/// It was the constant 0.5: a camera under a canopy or beside a wall reads 0.47 to 0.53 and switched every tree off (the owner's run: windows
/// with 39000 tree-shaped draws refused as indoors and none taken, at the camera 0.52-0.53, overhead cover 0.49); a real interior reads
/// 0.95 to 1.0 sheltered. BB_WIND_TWIGS_OPEN_MIN, read once, default OpenMinDefault; 0 never gates, 1 never takes. The per-vertex shelter
/// factor (r117) still takes the wind away from a vertex in a lee.
inline constexpr float OpenMinDefault = 0.2f;

[[nodiscard]] inline float OpenMin() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_OPEN_MIN"), OpenMinDefault), 0.0f, 1.0f);
    return v;
}
/// bbport (r89o_wind-chains-twigs-visible): a tree must be at least ModelMin units tall in its OWN model, a limb piece LimbExtra more
/// (BB_WIND_TWIGS_MIN_MODEL, read once; default ModelMinDefault; 0 turns the rule off). The shape rule is scale free, and the trees route's
/// world judge is loose (the union box of an instanced mesh), so a chain, a grille bar or a prop with a thin base and a wider top was
/// taken as a tree and swayed (the owner's coffin chains). The log's smallest tree-shaped mesh is 3.37, its real limb pieces 7.25 and
/// more, its chain-like piece 2.48.
inline constexpr float ModelMinDefault = 3.0f, LimbExtra = 1.0f;

[[nodiscard]] inline float ModelMin() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_MIN_MODEL"), ModelMinDefault), 0.0f, 30.0f);
    return v;
}

/// Whether a mesh whose model is `model_height` units tall (Shape::height) is big enough to be a tree (or a limb piece).
[[nodiscard]] inline bool SizeOk(float model_height, bool limb) {
    const float m = ModelMin();
    return !(m > 0.0f) || model_height >= (limb ? m + LimbExtra : m);
}

inline constexpr std::uint64_t RecheckFrames = 3600;     ///< a verdict is made again after this many frames
inline constexpr std::size_t BookMost = 4096;            ///< meshes known at most
inline constexpr std::uint32_t JudgeMost = 8;            ///< draw ranges judged a frame at most (the rest keep an
                                                         ///< older verdict or wait a frame: no hitch at first sight
                                                         ///< or when many verdicts expire together)
inline constexpr unsigned MeshLines = 12;                ///< verdict lines logged at most

/// bbport (r89k_twigs-opaque-word): the limb rule (BB_WIND_TWIGS_LIMBS). An opaque draw the shape rule refuses may be a
/// limb piece of a tree: at least LimbSamplesMin vertices read, its smallest bounding-box extent at least LimbFlatMin of
/// its largest (not a slab, a pole or a column), and at most BB_WIND_TWIGS_LIMB_BOXY (default LimbBoxyDefault) of its
/// vertices within LimbBand of an extent from a face of the box (a wall, a facade or a building is a shell: most of its
/// vertices lie on a face). The world box then judges it (BbWindTwigs::SmallWhy, at least BbWindTwigs::LimbMinH tall).
inline constexpr std::size_t LimbSamplesMin = 64;
inline constexpr float LimbFlatMin = 0.08f;
inline constexpr float LimbBand = 0.01f;
inline constexpr float LimbBoxyDefault = 0.10f;
inline constexpr unsigned LimbLines = 16;                ///< limb verdict lines logged at most

inline constexpr std::size_t PickMost = 8;               ///< pick points at most
inline constexpr std::uint32_t PickPerGroup = 4096;      ///< G-buffer draws measured in a pick frame at most
inline constexpr std::uint32_t PickGroups = 4;           ///< pick frames of queries in flight at most
inline constexpr std::uint64_t PickFramesPerPoint = 2;
inline constexpr std::uint64_t PickFrameDefault = 900;
inline constexpr int PickHalf = 2;                       ///< the patch is 2 * PickHalf + 1 pixels wide (r89k: 5, was 3)
inline constexpr std::size_t PickUnder = 3;              ///< earlier draws that also passed, named

/// BB_WIND_TWIGS_TREES: 1 on (the twigs on and BB_WIND_TWIGS_SMALL above 0), default 0.
[[nodiscard]] inline bool On() {
    return T::TreesWanted();
}

// ------------------------------------------------------------------------------------------- the shape rule

/// What the shape rule read of a draw's vertices (model units; the up axis 0 x, 1 y, 2 z, -1 none).
struct Shape {
    bool tree = false;
    int up = -1;
    float height = 0.0f, trunk = 0.0f, crown = 0.0f;
    const char* why = "few";
};

/// The `share` percentile of `v` (not empty; the order of v changes).
[[nodiscard]] inline float Percentile(std::vector<float>& v, float share) {
    const std::size_t k = std::min(v.size() - 1, static_cast<std::size_t>(share * static_cast<float>(v.size())));
    std::nth_element(v.begin(), v.begin() + static_cast<std::ptrdiff_t>(k), v.end());
    return v[k];
}

/// Whether `count` vertices (x, y, z floats, finite) are tree-shaped: for some axis taken as up, the lowest part
/// (a quarter of the height) is narrow (a radius of at most TrunkMax of the height), the upper half is at least
/// SpreadMin times as wide, and that width lies between CrownMin and CrownMax of the height. Width: the percentile of the distance from the trunk axis (the
/// middle of the lowest tenth). A wall, a floor, a column or a tower has the same width low and high (ratio near
/// 1), a spire or a cone is wider low (ratio under 1): none passes. The axis with the largest ratio is the reading.
[[nodiscard]] inline Shape ShapeOf(const float* xyz, std::size_t count) {
    Shape best;
    if (xyz == nullptr || count < 3 * PartMin) {
        return best;
    }
    float best_ratio = -1.0f;
    for (int up = 0; up < 3; ++up) {
        const int p = (up + 1) % 3;
        const int q = (up + 2) % 3;
        std::vector<std::size_t> order(count);
        for (std::size_t i = 0; i < count; ++i) {
            order[i] = i;
        }
        std::sort(order.begin(), order.end(),
                  [&](std::size_t a, std::size_t b) { return xyz[a * 3 + up] < xyz[b * 3 + up]; });
        const float lo = xyz[order.front() * 3 + up];
        const float hi = xyz[order.back() * 3 + up];
        const float height = hi - lo;
        if (!(height > 0.0f) || !std::isfinite(height)) {
            continue;
        }
        const std::size_t axis_n = std::max<std::size_t>(PartMin, static_cast<std::size_t>(AxisShare * static_cast<float>(count)));
        double ap = 0.0, aq = 0.0;
        for (std::size_t k = 0; k < axis_n; ++k) {
            ap += static_cast<double>(xyz[order[k] * 3 + p]);
            aq += static_cast<double>(xyz[order[k] * 3 + q]);
        }
        const float axis_p = static_cast<float>(ap / static_cast<double>(axis_n));
        const float axis_q = static_cast<float>(aq / static_cast<double>(axis_n));
        std::vector<float> trunk, crown;
        for (std::size_t i = 0; i < count; ++i) {
            const float u = xyz[i * 3 + up] - lo;
            const float d = std::hypot(xyz[i * 3 + p] - axis_p, xyz[i * 3 + q] - axis_q);
            if (u <= TrunkShare * height) {
                trunk.push_back(d);
            }
            if (u >= CrownShare * height) {
                crown.push_back(d);
            }
        }
        if (trunk.size() < PartMin || crown.size() < PartMin) {
            continue;
        }
        const float rt = std::max(Percentile(trunk, TrunkPct), RadiusFloor * height);
        const float rc = Percentile(crown, CrownPct);
        const float ratio = rc / rt;
        if (ratio > best_ratio) {
            best_ratio = ratio;
            best.up = up;
            best.height = height;
            best.trunk = rt;
            best.crown = rc;
            if (!(ratio >= SpreadMin)) {
                best.why = "no-spread";
            } else if (rt > TrunkMax * height) {
                best.why = "stout";
            } else if (rc < CrownMin * height) {
                best.why = "slim";
            } else if (rc > CrownMax * height) {
                best.why = "fan";
            } else {
                best.why = nullptr;
            }
        }
    }
    if (best.up >= 0 && best.why == nullptr) {
        best.tree = true;
    }
    return best;
}

// ------------------------------------------------------------------------------------------- the limb rule

/// bbport (r89k_twigs-opaque-word): BB_WIND_TWIGS_LIMBS (read once; default 1, 0 gives r89j back): whether a draw the
/// shape rule refuses may still be taken as a limb piece of a tree. Needs BB_WIND_TWIGS_TREES.
[[nodiscard]] inline bool LimbOn() {
    static const bool on = T::TreesWanted() && W::ParseNumber(std::getenv("BB_WIND_TWIGS_LIMBS"), 1.0f) >= 0.5f;
    return on;
}

/// BB_WIND_TWIGS_LIMB_BOXY (read once; 0 to 1, default LimbBoxyDefault): the most vertices on a box face a limb piece has.
[[nodiscard]] inline float LimbBoxyMax() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_LIMB_BOXY"), LimbBoxyDefault), 0.0f, 1.0f);
    return v;
}

/// What the limb rule read of a draw's vertices.
struct Limb {
    bool ok = false;
    float boxy = 0.0f;  ///< the share of the vertices within LimbBand of an extent from a face of the bounding box
    float flat = 0.0f;  ///< the smallest extent over the largest
    const char* why = "few"; ///< a string literal: "few", "point", "flat", "boxy"; nullptr when ok
};

/// Whether `count` vertices (x, y, z floats, finite) are a limb piece: see LimbSamplesMin and the constants. A scale-free
/// rule (model units are not metres: the draws' models run from 0.01 to 27 units tall).
[[nodiscard]] inline Limb LimbOf(const float* xyz, std::size_t count, float boxy_max = LimbBoxyDefault) {
    Limb l;
    if (xyz == nullptr || count < LimbSamplesMin) {
        return l;
    }
    float lo[3] = {xyz[0], xyz[1], xyz[2]};
    float hi[3] = {xyz[0], xyz[1], xyz[2]};
    for (std::size_t i = 1; i < count; ++i) {
        for (int a = 0; a < 3; ++a) {
            lo[a] = std::min(lo[a], xyz[i * 3 + static_cast<std::size_t>(a)]);
            hi[a] = std::max(hi[a], xyz[i * 3 + static_cast<std::size_t>(a)]);
        }
    }
    const float ext[3] = {hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]};
    const float ext_max = std::max({ext[0], ext[1], ext[2]});
    const float ext_min = std::min({ext[0], ext[1], ext[2]});
    if (!(ext_max > 0.0f) || !std::isfinite(ext_max)) {
        l.why = "point";
        return l;
    }
    l.flat = ext_min / ext_max;
    if (!(l.flat >= LimbFlatMin)) {
        l.why = "flat";
        return l;
    }
    std::size_t on_face = 0;
    for (std::size_t i = 0; i < count; ++i) {
        bool face = false;
        for (std::size_t a = 0; a < 3; ++a) {
            const float v = xyz[i * 3 + a];
            face = face || std::min(v - lo[a], hi[a] - v) <= LimbBand * ext[a];
        }
        on_face += face ? 1u : 0u;
    }
    l.boxy = static_cast<float>(on_face) / static_cast<float>(count);
    if (!(l.boxy <= boxy_max)) {
        l.why = "boxy";
        return l;
    }
    l.ok = true;
    l.why = nullptr;
    return l;
}

// ------------------------------------------------------------------------------------------- the trees' gain

/// bbport (r89l_twigs-palette-move): BB_WIND_TWIGS_TREES_GAIN (read once; 0 to 1, default TreesGainDefault): the share of the
/// move r89k gave that a draw of the trees route (tree-shaped or limb piece) keeps. 'A few cm at 4 m/s, very subtle.'
/// bbport (r89o_wind-chains-twigs-visible): 0.5 -> 1.0 (the 4K clips of build 72 showed no twig motion; the soft cap holds the move now).
inline constexpr float TreesGainDefault = 1.0f;

[[nodiscard]] inline float TreesGain() {
    static const float gain = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_TREES_GAIN"), TreesGainDefault), 0.0f, 1.0f);
    return gain;
}

/// A sway word's ramp byte (0 to 255) times `gain` (0 to 1): 0 stays 0 (judging, no motion), a gain of 0 gives 0, any other
/// gain keeps at least 1 so a mesh that moves keeps moving.
[[nodiscard]] inline std::uint32_t GainRamp(std::uint32_t ramp, float gain) {
    if (ramp == 0u || !(gain > 0.0f)) {
        return 0u;
    }
    const float g = std::isfinite(gain) ? std::min(gain, 1.0f) : 1.0f;
    const long scaled = std::lround(static_cast<float>(std::min(ramp, 255u)) * g);
    return static_cast<std::uint32_t>(std::clamp(scaled, 1L, 255L));
}

// ------------------------------------------------------------------------------------------- the book

/// One draw's vertex range (a mesh of its own) and the verdict on it.
struct Mesh {
    bool tree = false;
    std::uint64_t addr = 0;           ///< the address of its first used vertex: its key for the sway slot
    std::uint32_t size = 0;           ///< bytes of its vertex range
    std::uint32_t verts = 0;
    Shape shape;
    const char* why = "unread";       ///< a string literal: why it is no tree
    bool limb = false;                ///< bbport (r89k_twigs-opaque-word): refused by shape, but a limb piece (LimbOf)
    float boxy = 0.0f;                ///< the limb rule's share of vertices on a box face
    const char* limb_why = "";        ///< a string literal: "" not tried, "ok", or why the limb rule refused
    std::uint64_t at = 0;             ///< frame of the verdict
};

/// The key of a draw: its position stream, base vertex, index address and index count.
[[nodiscard]] constexpr std::uint64_t MeshKey(std::uint64_t positions, std::int32_t base, std::uint64_t index_address,
                                              std::uint32_t count) {
    std::uint64_t k = positions * 0x9E3779B97F4A7C15ull;
    k ^= static_cast<std::uint64_t>(static_cast<std::uint32_t>(base)) + 0x7F4A7C15ull + (k << 6) + (k >> 2);
    k *= 0x9E3779B97F4A7C15ull;
    k ^= index_address + 0x85EBCA6Bull + (k << 6) + (k >> 2);
    k *= 0xC2B2AE3D27D4EB4Full;
    k ^= static_cast<std::uint64_t>(count) + (k << 6) + (k >> 2);
    return k;
}

class Book {
public:
    /// The verdict of `key` if one was made in the last RecheckFrames frames, else nullptr.
    [[nodiscard]] Mesh* Find(std::uint64_t key, std::uint64_t frame) {
        const auto found = meshes_.find(key);
        if (found == meshes_.end() || found->second.at + RecheckFrames < frame) {
            return nullptr;
        }
        return &found->second;
    }

    /// The verdict of `key` however old, else nullptr (held while a frame's judging budget is used up).
    [[nodiscard]] Mesh* Any(std::uint64_t key) {
        const auto found = meshes_.find(key);
        return found == meshes_.end() ? nullptr : &found->second;
    }

    Mesh& Put(std::uint64_t key, const Mesh& mesh) {
        if (meshes_.size() >= BookMost && meshes_.find(key) == meshes_.end()) {
            meshes_.clear();
        }
        return meshes_[key] = mesh;
    }

    [[nodiscard]] std::size_t Size() const {
        return meshes_.size();
    }

    [[nodiscard]] std::size_t Trees() const {
        std::size_t n = 0;
        for (const auto& item : meshes_) {
            n += item.second.tree ? 1u : 0u;
        }
        return n;
    }

private:
    std::unordered_map<std::uint64_t, Mesh> meshes_;
};

struct Stats {
    std::uint64_t draws = 0;        ///< candidate draws asked
    std::uint64_t unread = 0;       ///< not indexed, no float positions, nothing to read, or waiting (JudgeMost)
    std::uint64_t taken = 0;        ///< given the mesh key (tree-shaped, camera open)
    std::uint64_t refused = 0;      ///< not tree-shaped
    std::uint64_t indoors = 0;      ///< tree-shaped, the camera is indoors (r117's field)
    std::uint64_t new_meshes = 0, tree_meshes = 0, refused_meshes = 0;
    std::uint64_t limbs = 0;         ///< bbport (r89k): draws taken as limb pieces (counted in taken too)
    std::uint64_t too_small = 0;     ///< bbport (r89o): tree-shaped or limb-piece draws refused as too small a model (SizeOk)
    std::uint64_t limb_cutout = 0;   ///< bbport (r89p): limb piece by shape, refused because its pixel shader discards (not an opaque draw)
    std::uint64_t limb_cut = 0;      ///< bbport (r89q): cut-out limb pieces taken (counted in taken and limbs too)
    std::uint64_t limb_cut_small = 0; ///< bbport (r89q): cut-out limb pieces refused under CutoutMin
    std::uint64_t lr_model = 0;      ///< bbport (r89r): limb-shaped draws refused under the model size rule (LimbWorldOn() false)
    std::uint64_t lr_indoors = 0;    ///< bbport (r89r): limb-shaped draws refused as indoors
    std::uint64_t lr_old = 0;        ///< bbport (r89r): limb draws taken that r89q's model size rules would have refused
    std::uint64_t limb_new = 0, limb_refused = 0; ///< ranges judged limb pieces; refused by the limb rule too
};

inline void OnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89j, BB_WIND_TWIGS_TREES=1): a draw of a pipeline with the sway bit (a cut-out, "
                  "or an opaque one with a bone palette) is a tree when the shape of its own vertices says so (the "
                  "lowest quarter of the height at most 1/%.1f as wide as the upper half, the upper half 0.25-1.6 of "
                  "the height wide; a wall, a tower, a column or a cone is not) and the camera is outdoors (open "
                  "wind share at least %.1f with BB_WIND_SHELTER=1); each such draw is its own mesh (its vertex "
                  "range is its sway slot key) and the twig weight is the mesh rule (height in the mesh x distance "
                  "from its centre line), not the fit rule (height over the camera)",
                  static_cast<double>(SpreadMin), static_cast<double>(OpenMin()));
}

inline void LineText(const Stats& s, const Book& book, unsigned frames, unsigned limb_meshes, unsigned limb_trees,
                     char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs trees (r89j): in %u frames %llu candidate draws: %llu taken (tree-shaped or limb piece, r89k: "
                  "%llu limb), %llu refused (shape), %llu indoors, %llu unread; %llu draw ranges judged (%llu tree-shaped, "
                  "%llu not; %llu limb pieces, %llu refused by the limb rule too); book %zu meshes, %zu tree-shaped; limb "
                  "meshes in the twig book %u, judged trees by their world box %u",
                  frames, n(s.draws), n(s.taken), n(s.limbs), n(s.refused), n(s.indoors), n(s.unread), n(s.new_meshes),
                  n(s.tree_meshes), n(s.refused_meshes), n(s.limb_new), n(s.limb_refused), book.Size(), book.Trees(),
                  limb_meshes, limb_trees);
}

/// bbport (r89o_wind-chains-twigs-visible): the size rule's line, every ReportFrames frames with the trees route on.
inline void SizeLineText(const Stats& s, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89o, BB_WIND_TWIGS_MIN_MODEL=%.1f): %llu draws refused in the last 600 frames as too small to be a "
                  "tree (a model under %.1f units tall, a limb piece under %.1f: chains, grilles, hooks and props stay still)",
                  static_cast<double>(ModelMin()), static_cast<unsigned long long>(s.too_small), static_cast<double>(ModelMin()),
                  static_cast<double>(ModelMin() + LimbExtra));
}

/// bbport (r89q_twigs-limb-discard): BB_WIND_TWIGS_LIMB_CUTOUT (read once, default 1; needs the limb rule): a limb piece whose pixel
/// shader discards (an alpha-tested bark or twig card: the visible wood of the bare trees) is taken like an opaque one. 0 gives r89p back.
[[nodiscard]] inline bool CutoutOn() {
    static const bool on = LimbOn() && W::ParseNumber(std::getenv("BB_WIND_TWIGS_LIMB_CUTOUT"), 1.0f) >= 0.5f;
    return on;
}

/// bbport (r89q): the model height (Shape::height units) a cut-out limb piece needs, on top of the size rule: a cut-out is also what iron
/// fences, grilles and cage bars are made of. Default 6.0 (the bare trees' limb pieces of the log are 6.94 to 7.25, a chain-like one 2.48);
/// BB_WIND_TWIGS_CUTOUT_MIN_MODEL, read once; 0 = no extra rule.
inline constexpr float CutoutMinDefault = 6.0f;

[[nodiscard]] inline float CutoutMin() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_CUTOUT_MIN_MODEL"), CutoutMinDefault), 0.0f, 30.0f);
    return v;
}

[[nodiscard]] inline bool CutoutSizeOk(float model_height) {
    const float m = CutoutMin();
    return !(m > 0.0f) || model_height >= m;
}

inline void CutoutOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89q, BB_WIND_TWIGS_LIMB_CUTOUT=%d, BB_WIND_TWIGS_CUTOUT_MIN_MODEL=%.1f): a limb piece whose pixel "
                  "shader discards (alpha-tested bark and twig cards) is taken like an opaque one when its model is at least that many "
                  "units tall, the camera is outdoors and its world box says tree",
                  CutoutOn() ? 1 : 0, static_cast<double>(CutoutMin()));
}

inline void CutoutLineText(const Stats& s, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89q): in the last 600 frames %llu cut-out limb draws taken (counted in taken and limbs too), "
                  "%llu refused as a cut-out under BB_WIND_TWIGS_CUTOUT_MIN_MODEL (%.1f)",
                  static_cast<unsigned long long>(s.limb_cut), static_cast<unsigned long long>(s.limb_cut_small),
                  static_cast<double>(CutoutMin()));
}

/// bbport (r89r_twigs-limb-units): BB_WIND_TWIGS_LIMB_WORLD (read once, default 1; needs the limb rule): a limb piece (opaque or cut-out)
/// is sized by its WORLD box (BbWindTwigs::LimbMinHeight metres tall, still), not by Shape::height, which is the extent along an arbitrary
/// axis in model units (a bare tree's bark and twig cards read 0.01 to 0.11). 0 gives r89q's model size rules back.
[[nodiscard]] inline bool LimbWorldOn() {
    static const bool on = LimbOn() && W::ParseNumber(std::getenv("BB_WIND_TWIGS_LIMB_WORLD"), 1.0f) >= 0.5f;
    return on;
}

/// bbport (r89r): whether r89q's model size rules (SizeOk for a limb, and CutoutSizeOk for a cut-out) would refuse a limb draw.
[[nodiscard]] inline bool LimbOldRuleRefuses(float model_height, bool cut_out) {
    return !SizeOk(model_height, true) || (cut_out && !CutoutSizeOk(model_height));
}

/// bbport (r89r): the frame of the early report line (the regular one comes every ReportFrames frames).
inline constexpr std::uint64_t UnitsEarlyFrame = 150;

/// bbport (r89r): the limb entries of the twig book by the verdict of their world box (Add is called for each, at the report).
struct LimbCensus {
    unsigned entries = 0, waiting = 0, tree = 0, short_h = 0, moved = 0, tall = 0, other = 0, judged = 0;
    float h_min = 0.0f, h_max = 0.0f;

    void Add(bool is_waiting, bool is_tree, const char* why, float height) {
        ++entries;
        if (is_waiting) {
            ++waiting;
            return;
        }
        if (is_tree) {
            ++tree;
        } else if (why != nullptr && std::strcmp(why, "short") == 0) {
            ++short_h;
        } else if (why != nullptr && std::strcmp(why, "moved") == 0) {
            ++moved;
        } else if (why != nullptr && std::strcmp(why, "tall") == 0) {
            ++tall;
        } else {
            ++other;
        }
        if (height > 0.0f && std::isfinite(height)) {
            h_min = judged == 0 ? height : std::min(h_min, height);
            h_max = judged == 0 ? height : std::max(h_max, height);
            ++judged;
        }
    }
};

/// bbport (r89r): the once line (no 'limb piece', 'mesh:' or 'candidate' in it: the slot runner's evidence filter drops those).
inline void UnitsOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89r, BB_WIND_TWIGS_LIMB_WORLD=%d, BB_WIND_TWIGS_LIMB_MIN_H=%.1f): a limb-shaped draw (opaque or cut-out) is "
                  "sized by its world box (at least that many metres tall, still, camera outdoors), not by its model height (model units "
                  "are not metres); a line every 600 frames (and at frame %llu) counts why each is refused",
                  LimbWorldOn() ? 1 : 0, static_cast<double>(BbWindTwigs::LimbMinHeight()),
                  static_cast<unsigned long long>(UnitsEarlyFrame));
}

/// bbport (r89r): the counts line. `s` holds the counters since the last report (the 600-frame line resets them).
inline void UnitsLineText(const Stats& s, const LimbCensus& c, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs trees (r89r): limb draws taken %llu (cut-out %llu; %llu the old model rule would have refused), refused: %llu "
                  "by model size, %llu by cut-out model size, %llu indoors, %llu because the pixel shader discards; limb entries in the twig "
                  "book %u: %u judged trees, %u waiting, refused by world box %u short (under %.1f m), %u moved, %u tall, %u other; "
                  "judged world heights %.1f to %.1f m",
                  n(s.limbs), n(s.limb_cut), n(s.lr_old), n(s.lr_model), n(s.limb_cut_small), n(s.lr_indoors), n(s.limb_cutout), c.entries,
                  c.tree, c.waiting, c.short_h, static_cast<double>(BbWindTwigs::LimbMinHeight()), c.moved, c.tall, c.other,
                  static_cast<double>(c.h_min), static_cast<double>(c.h_max));
}

/// bbport (r89q): the line of a cut-out limb piece taken (the first few, each once).
inline void CutLimbText(const Mesh& m, std::uint64_t first_vertex, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89q) cut-out limb part taken: first vertex at %llx, %u vertices, model height %.2f, "
                  "trunk radius %.3f, crown radius %.3f, up axis %d, boxy %.3f",
                  static_cast<unsigned long long>(first_vertex), m.verts, static_cast<double>(m.shape.height),
                  static_cast<double>(m.shape.trunk), static_cast<double>(m.shape.crown), m.shape.up, static_cast<double>(m.boxy));
}

/// bbport (r89p_twigs-really-move): the gate and limb line, every ReportFrames frames with the trees route on.
inline void GateLineText(const Stats& s, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89p, BB_WIND_TWIGS_OPEN_MIN=%.2f): in the last 600 frames %llu draws refused as indoors (the camera's "
                  "open wind share under that), %llu limb-shaped draws refused because their pixel shader discards, %llu taken (%llu of "
                  "them limb pieces)",
                  static_cast<double>(OpenMin()), static_cast<unsigned long long>(s.indoors),
                  static_cast<unsigned long long>(s.limb_cutout), static_cast<unsigned long long>(s.taken),
                  static_cast<unsigned long long>(s.limbs));
}

/// bbport (r89p_twigs-really-move, TOOL): BB_WIND_FREEZE (exactly "1" is on; read at each new view, live with the test tools' knobs when
/// the effects file has them). Without them: the environment.
[[nodiscard]] inline bool FreezeEnv() {
    const char* const text = std::getenv("BB_WIND_FREEZE");
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

/// bbport (r89p_twigs-really-move, TOOL): the view words frozen at a full gust front: the gust table 1, the fronts' scale 0 (every point
/// at the same phase), each front's phase solved so that its skewed sine reads 1 (a + skew sin a = pi / 2, skew = the view's lean flag x
/// LeanSkew), so the envelope is EnvScale everywhere and for ever; the swing and leaf phases 0. `view` holds one view's ViewWords floats as
/// FillLean / FillRipple left them (the lean's flag at RippleAt + 13). No time and no gust remain in the move: it is the push rule's full
/// front, D x (TwigRest + TwigPush) x weight, downwind.
inline void FreezeView(float* view) {
    float* const p = view + W::RippleAt;
    const float skew = p[13] * W::LeanSkew;
    float a = 1.5707963f;
    for (int i = 0; i < 24; ++i) {
        a = 1.5707963f - skew * std::sin(a);
    }
    for (std::uint32_t i = 2; i <= 4; ++i) {
        p[i] = a;
    }
    p[0] = p[1] = p[5] = p[6] = 0.0f;
    p[7] = 0.0f;
    view[W::WindB + 3] = 0.0f;
    view[W::WindC + 2] = 0.0f;
    for (std::uint32_t i = 0; i < W::GustSamples; ++i) {
        view[W::TableAt + i] = 1.0f;
    }
}

inline void FreezeOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind freeze (r89p, TOOL, BB_WIND_FREEZE=1): every view's wind is frozen at a full gust front (gust table 1, fronts in "
                  "step at their crest, swing and leaf phases 0): plants, trees and twigs lean downwind by their full weight and stand "
                  "still; the same camera with BB_WIND_TWIGS=0 differs by the twig move only");
}

inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {
    char limb[96] = ""; // bbport (r89k_twigs-opaque-word): what the limb rule made of a shape refusal
    if (!m.tree && m.limb_why != nullptr && m.limb_why[0] != '\0') {
        std::snprintf(limb, sizeof(limb), "; limb rule: %s, boxy %.3f", m.limb_why, static_cast<double>(m.boxy));
    }
    std::snprintf(out, size,
                  "Wind twigs trees (r89j) mesh: stream %llx, vertex range at %llx, %u vertices: %s (model height "
                  "%.2f, trunk radius %.3f, crown radius %.3f, up axis %d%s%s%s)",
                  static_cast<unsigned long long>(key_stream), static_cast<unsigned long long>(m.addr), m.verts,
                  m.tree ? "TREE-SHAPED" : (m.limb ? "LIMB PIECE" : "refused"), static_cast<double>(m.shape.height),
                  static_cast<double>(m.shape.trunk), static_cast<double>(m.shape.crown), m.shape.up,
                  m.tree ? "" : ", shape why ", m.tree ? "" : m.why, limb);
}

// ------------------------------------------------------------------------------------------- the pick

struct Point {
    int x = 0, y = 0;
};

/// The text after the next ';' (or the end).
[[nodiscard]] inline const char* NextItem(const char* s) {
    while (*s != '\0' && *s != ';') {
        ++s;
    }
    return *s == ';' ? s + 1 : s;
}

/// "x,y;x,y;..." (or "x:y;x:y;..."): the points (0..16384 each), at most `max`; an item that does not read is skipped.
[[nodiscard]] inline std::size_t ParsePoints(const char* text, Point* out, std::size_t max) {
    std::size_t n = 0;
    if (text == nullptr) {
        return 0;
    }
    const char* s = text;
    while (*s != '\0' && n < max) {
        char* end = nullptr;
        const long x = std::strtol(s, &end, 10);
        const char* t = end;
        if (end == s) {
            s = NextItem(s);
            continue;
        }
        while (*t == ' ') {
            ++t;
        }
        if (*t != ',' && *t != ':') { // ':' for environments that cannot hold a comma
            s = NextItem(t);
            continue;
        }
        ++t;
        char* end2 = nullptr;
        const long y = std::strtol(t, &end2, 10);
        if (end2 == t) {
            s = NextItem(t);
            continue;
        }
        if (x >= 0 && y >= 0 && x <= 16384 && y <= 16384) {
            out[n].x = static_cast<int>(x);
            out[n].y = static_cast<int>(y);
            ++n;
        }
        s = NextItem(end2);
    }
    return n;
}

struct PickKnob {
    std::array<Point, PickMost> points{};
    std::size_t count = 0;
    std::uint32_t out_w = 1280, out_h = 720;
    std::uint64_t start = PickFrameDefault;
    std::uint64_t repeat = 0; ///< bbport (r89k): the sweep starts again every this many frames (0: once)
    bool glass = false;       ///< bbport (r86l_glint-pick-glass, TOOL): the glass pick: every draw that passed, forward ones too
};

[[nodiscard]] inline PickKnob ParsePick(const char* list, const char* size, const char* frame,
                                      const char* repeat = nullptr) {
    PickKnob k;
    k.count = ParsePoints(list, k.points.data(), PickMost);
    if (size != nullptr) {
        char* end = nullptr;
        const long w = std::strtol(size, &end, 10);
        if (end != size && (*end == 'x' || *end == 'X')) {
            char* end2 = nullptr;
            const long h = std::strtol(end + 1, &end2, 10);
            if (end2 != end + 1 && w >= 16 && h >= 16 && w <= 16384 && h <= 16384) {
                k.out_w = static_cast<std::uint32_t>(w);
                k.out_h = static_cast<std::uint32_t>(h);
            }
        }
    }
    const float f = W::ParseNumber(frame, static_cast<float>(PickFrameDefault));
    k.start = f >= 0.0f && f <= 1.0e7f ? static_cast<std::uint64_t>(f) : PickFrameDefault;
    // bbport (r89k_twigs-opaque-word): BB_WIND_TWIGS_PICK_REPEAT: at least a sweep long (PickFramesPerPoint x points)
    const float rep = W::ParseNumber(repeat, 0.0f);
    if (rep > 0.0f && rep <= 1.0e7f && static_cast<std::uint64_t>(rep) >= k.count * PickFramesPerPoint) {
        k.repeat = static_cast<std::uint64_t>(rep);
    }
    return k;
}

[[nodiscard]] inline const PickKnob& PickOnce() {
    static const PickKnob knob = ParsePick(std::getenv("BB_WIND_TWIGS_PICK"), std::getenv("BB_WIND_TWIGS_PICK_SIZE"),
                                           std::getenv("BB_WIND_TWIGS_PICK_FRAME"),
                                           std::getenv("BB_WIND_TWIGS_PICK_REPEAT"));
    return knob;
}

/// bbport (r86l_glint-pick-glass, TOOL): the glass pick (BB_GLASS_PICK, rt_glass_pick.h) is armed and dropped while the game
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

/// The point a pick frame draws for (the frame count the frame will have), -1 outside the pick.
[[nodiscard]] inline int PointAt(std::uint64_t frame, std::uint64_t start, std::size_t count,
                                std::uint64_t repeat = 0) {
    if (frame < start) {
        return -1;
    }
    std::uint64_t d = frame - start;
    if (repeat != 0) { // bbport (r89k_twigs-opaque-word): the sweep starts again every `repeat` frames
        d %= repeat;
    }
    const std::uint64_t k = d / PickFramesPerPoint;
    return k < count ? static_cast<int>(k) : -1;
}

struct Rect {
    int x = 0, y = 0, w = 0, h = 0;
    int cx = 0, cy = 0; ///< the pixel in the render target
};

/// The patch of the render target (render_w x render_h) that the output pixel `p` of an out_w x out_h picture lies
/// in: 2 * PickHalf + 1 pixels wide, kept inside the target. w and h 0: no target.
[[nodiscard]] inline Rect PickRect(const Point& p, std::uint32_t out_w, std::uint32_t out_h, std::uint32_t render_w,
                                   std::uint32_t render_h) {
    Rect r;
    if (out_w == 0 || out_h == 0 || render_w == 0 || render_h == 0) {
        return r;
    }
    const double fx = (static_cast<double>(p.x) + 0.5) * static_cast<double>(render_w) / static_cast<double>(out_w);
    const double fy = (static_cast<double>(p.y) + 0.5) * static_cast<double>(render_h) / static_cast<double>(out_h);
    const int cx = std::clamp(static_cast<int>(std::floor(fx)), 0, static_cast<int>(render_w) - 1);
    const int cy = std::clamp(static_cast<int>(std::floor(fy)), 0, static_cast<int>(render_h) - 1);
    const int x0 = std::max(cx - PickHalf, 0);
    const int y0 = std::max(cy - PickHalf, 0);
    const int x1 = std::min(cx + PickHalf + 1, static_cast<int>(render_w));
    const int y1 = std::min(cy + PickHalf + 1, static_cast<int>(render_h));
    r.x = x0;
    r.y = y0;
    r.w = x1 - x0;
    r.h = y1 - y0;
    r.cx = cx;
    r.cy = cy;
    return r;
}

/// bbport (r89l_twigs-palette-move): the pick's patch in RASTER pixels. PickRect makes the patch in game-target pixels (the
/// target size the game believes it draws to), but the G-buffer's scissors are in raster pixels (the game's scissor times the
/// rasterizer's target scale plus its offset: the scene may be drawn at half the size of the game's targets, as in the slot
/// windows). The patch is 2 * PickHalf + 1 raster pixels around the scaled centre pixel; its right and lower edges are not
/// cut (the scissor intersection does). w and h 0: no patch.
struct RasterRect {
    int x = 0, y = 0, w = 0, h = 0;
};

[[nodiscard]] inline RasterRect PickRectRaster(const Rect& r, float scale_x, float scale_y, float offset_x, float offset_y) {
    RasterRect o;
    if (r.w <= 0 || r.h <= 0 || !std::isfinite(scale_x) || !std::isfinite(scale_y) || !std::isfinite(offset_x) ||
        !std::isfinite(offset_y) || !(scale_x > 0.0f) || !(scale_y > 0.0f)) {
        return o;
    }
    const double fx = (static_cast<double>(r.cx) + 0.5) * static_cast<double>(scale_x) + static_cast<double>(offset_x);
    const double fy = (static_cast<double>(r.cy) + 0.5) * static_cast<double>(scale_y) + static_cast<double>(offset_y);
    const int cx = static_cast<int>(std::floor(std::clamp(fx, -1.0e6, 1.0e6)));
    const int cy = static_cast<int>(std::floor(std::clamp(fy, -1.0e6, 1.0e6)));
    o.x = std::max(cx - PickHalf, 0);
    o.y = std::max(cy - PickHalf, 0);
    o.w = cx + PickHalf + 1 - o.x;
    o.h = cy + PickHalf + 1 - o.y;
    if (o.w <= 0 || o.h <= 0) {
        o = RasterRect{};
    }
    return o;
}

/// The once line of the pick's scaling (under 400 characters): the picture the pixels are read from, the game targets, the
/// raster they are drawn at, and the first patch in raster pixels.
inline void PickRasterText(std::uint32_t out_w, std::uint32_t out_h, std::uint32_t game_w, std::uint32_t game_h, float scale_x,
                           float scale_y, float offset_x, float offset_y, int patch_x, int patch_y, int patch_w, int patch_h,
                           char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89l): pick pixels are read in a %ux%u picture, scaled to the game targets %ux%u and then to "
                  "the raster %ux%u (target scale %.3f x %.3f, offset %.1f, %.1f); the G-buffer's scissors are in raster pixels; "
                  "the first patch is x %d y %d, %dx%d raster pixels",
                  out_w, out_h, game_w, game_h, static_cast<unsigned>(std::lround(static_cast<double>(game_w) * scale_x)),
                  static_cast<unsigned>(std::lround(static_cast<double>(game_h) * scale_y)), static_cast<double>(scale_x),
                  static_cast<double>(scale_y), static_cast<double>(offset_x), static_cast<double>(offset_y), patch_x, patch_y,
                  patch_w, patch_h);
}

/// What the rasterizer knew of one G-buffer draw of a pick frame.
struct PickDraw {
    std::uint32_t vs = 0, ps = 0;
    std::uint32_t stream_verts = 0, stride = 0, indices = 0, first = 0, sway = 0;
    std::int32_t base = 0;
    int kind = 3;                    ///< 0 skinned, 1 GPU palette, 2 static, 3 no motion block
    bool cutout = false, sway_bit = false, motion = false, depth_write = false;
    std::uint64_t stream = 0;        ///< the position stream's address (0: none)
    std::uint64_t index_address = 0;
    // bbport (r86l_glint-pick-glass, TOOL): the glass pick's facts of the draw (RtGlassPick::Flag*; 0 for the twig pick)
    std::uint32_t glass_flags = 0, targets = 0, instances = 0, index_size = 0, images = 0;
    std::uint64_t mesh = 0;          ///< the position key PrepareDraw keys entries by (0: no position stream)
    std::uint64_t pair_vs = 0, pair_ps = 0; ///< the full shader hashes (RtGlassMatch's)
};

struct PickResult {
    bool found = false;
    std::size_t row = 0;             ///< the winner: the last draw that passed with depth write
    std::size_t passed = 0;          ///< draws with samples at the patch
    std::array<std::size_t, PickUnder> under{};
    std::size_t under_n = 0;         ///< earlier draws that passed as well (most recent first)
    bool any = false;                ///< bbport (r89k): some draw had samples (whether it wrote depth or not)
    std::size_t any_row = 0;         ///< the last draw with samples
};

/// The draw that wrote the final depth at the patch: the last draw with samples that writes depth; and up to
/// PickUnder earlier draws with samples. `counts[i]` the samples of draws[i].
[[nodiscard]] inline PickResult PickWinner(const std::vector<PickDraw>& draws, const std::uint64_t* counts) {
    PickResult r;
    for (std::size_t i = draws.size(); i-- > 0;) {
        if (counts[i] == 0) {
            continue;
        }
        ++r.passed;
        if (!r.any) { // bbport (r89k_twigs-opaque-word): the last draw with samples, for the fallback line
            r.any = true;
            r.any_row = i;
        }
        if (!r.found && draws[i].depth_write) {
            r.found = true;
            r.row = i;
        } else if (r.found && r.under_n < PickUnder) {
            r.under[r.under_n++] = i;
        }
    }
    return r;
}

[[nodiscard]] inline const char* KindName(int kind) {
    return kind == 0 ? "skinned" : (kind == 1 ? "GPU palette" : (kind == 2 ? "static" : "no motion block"));
}

/// One pick line (under 700 characters). `box` names the scene box and `book` the twig book's verdict.
inline void PickLine(const Point& pt, const Rect& rect, std::size_t row, std::size_t total, std::size_t passed,
                     const PickDraw& d, bool is_under, const char* box, const char* book, char* out,
                     std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j): pixel %d,%d (render %d,%d): %s %zu of %zu G-buffer draws (%zu with samples "
                  "at the patch) vs:ps %08x:%08x, stream %u vertices at stride %u, %s, %s, sway bit %s, sway word %s, "
                  "%u indices from index %u at base vertex %d; twig weight at that vertex: not known on the CPU (the "
                  "proof tint shows it); %s; %s",
                  pt.x, pt.y, rect.cx, rect.cy, is_under ? "under:" : "row", row, total, passed, d.vs, d.ps,
                  d.stream_verts, d.stride, d.cutout ? "cut-out" : "opaque", KindName(d.kind), d.sway_bit ? "YES" : "no",
                  d.sway != 0 ? "YES" : "no", d.indices, d.first, static_cast<int>(d.base), box, book);
}

inline void PickNoneLine(const Point& pt, const Rect& rect, std::size_t total, std::size_t passed, char* out,
                         std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j): pixel %d,%d (render %d,%d): no G-buffer draw of %zu wrote depth there "
                  "(%zu of them had samples at the patch: %s)",
                  pt.x, pt.y, rect.cx, rect.cy, total, passed,
                  passed == 0 ? "the patch drew nothing: sky, or the patch missed every draw"
                              : "none with depth write: a later pass wrote the depth");
}

/// bbport (r89k_twigs-opaque-word): the note line of a pick pixel: the frame, the camera, the picture and the patch, and
/// how many G-buffer scissors met the patch (`meet`) or did not (`apart`: all apart = the patch lies outside every draw's
/// scissor, a coordinate mismatch, not an empty pixel); `queried` draws had a query. `camera` three floats, or nullptr.
inline void PickNoteLine(const Point& pt, const Rect& rect, std::uint32_t out_w, std::uint32_t out_h, std::uint64_t frame,
                         bool camera_ok, const float* camera, std::uint32_t meet, std::uint32_t apart,
                         std::size_t queried, char* out, std::size_t size) {
    char cam[96] = "unread";
    if (camera_ok && camera != nullptr) {
        std::snprintf(cam, sizeof(cam), "%.1f %.1f %.1f", static_cast<double>(camera[0]), static_cast<double>(camera[1]),
                      static_cast<double>(camera[2]));
    }
    std::snprintf(out, size,
                  "Wind twigs pick (r89k): pixel %d,%d: frame %llu, camera %s, picture %ux%u, patch x %d..%d y %d..%d "
                  "(%dx%d, centre %d,%d), G-buffer scissors that met the patch %u, that did not %u, draws with a query %zu",
                  pt.x, pt.y, static_cast<unsigned long long>(frame), cam, out_w, out_h, rect.x, rect.x + rect.w - 1, rect.y,
                  rect.y + rect.h - 1, rect.w, rect.h, rect.cx, rect.cy, meet, apart, queried);
}

inline void PickOnceText(const PickKnob& k, char* out, std::size_t size) {
    char again[64] = "";
    if (k.repeat != 0) { // bbport (r89k_twigs-opaque-word)
        std::snprintf(again, sizeof(again), "; the sweep starts again every %llu frames", static_cast<unsigned long long>(k.repeat));
    }
    std::snprintf(out, size,
                  "Wind twigs pick (r89j, TOOL, BB_WIND_TWIGS_PICK): %zu pixel(s) of a %ux%u picture, from frame %llu "
                  "on, %llu frames a pixel: those frames draw only a %dx%d patch of the G-buffer (the picture is "
                  "broken for them); an occlusion query a draw names the last draw that passed the depth test with "
                  "depth write there%s",
                  k.count, k.out_w, k.out_h, static_cast<unsigned long long>(k.start),
                  static_cast<unsigned long long>(PickFramesPerPoint), 2 * PickHalf + 1, 2 * PickHalf + 1, again);
}

} // namespace BbWindTrees
