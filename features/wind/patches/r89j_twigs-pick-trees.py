# r89j_twigs-pick-trees: FEATURE fix (BB_WIND_TWIGS_TREES, default 0) + TOOL (BB_WIND_TWIGS_PICK) on top of r89d..r89i (build 51).
# The tool: a pixel pick that names the G-buffer draw that wrote the final depth at listed output pixels.
# The feature: the tree rule takes tree draws by the shape of the draw's own vertices, never buildings or interiors.
#
# THE OWNER: "I think if the small branches on the trees moved slightly due to wind that would look great"; "The wave
# should just be very subtle".
# BUILD 51 (r89i): the census works (the cut-out G-buffer rows take the sway bit; the large opaque GPU-palette rows do not);
# no branch motion on screen, no proof stain on any tree. With BB_WIND_TWIGS_STATIC=2 the stain appeared on the CATHEDRAL
# facade and sways interior walls (dark interior), on no tree: the height-over-camera rule (fit) and the stand-wide box
# keys put the weight on tall buildings, and nothing told a tree from a wall.
#
# TOOL BB_WIND_TWIGS_PICK="x,y;x,y;..." (output pixels, at most 8; BB_WIND_TWIGS_PICK_SIZE=WxH, default 1280x720: the
# picture the pixels are read from; BB_WIND_TWIGS_PICK_FRAME=N, default 900: the first frame). From frame N on, for 2
# frames a pixel, the G-buffer draws only a 3x3 patch around the pixel (UpdateViewportScissorState intersects every
# G-buffer scissor with the patch; the picture of those frames is broken) and every G-buffer draw is wrapped in an
# occlusion query (the pattern of r12's water queries: a pool of 4 groups x 4096 queries, host query reset, results read
# without waiting once the GPU is past the frame). The last draw with samples that writes depth is the one that wrote the
# final depth there; up to 3 earlier draws with samples are named too. Log, once per pixel:
#   Wind twigs pick (r89j): pixel x,y (render X,Y): row N of M G-buffer draws (P with samples at the patch) vs:ps ...,
#   stream V vertices at stride S, opaque|cut-out, skinned|GPU palette|static|no motion block, sway bit, sway word, indices,
#   first index, base vertex; scene box (y range and over the camera), tree shape and twig book verdict.
# The twig weight at that vertex is not known on the CPU: the proof tint (BB_WIND_TWIGS_PROOF=1) shows it on screen. Off
# (no pixel in the knob): the three hooks are one test of a static bool or of a false member each.
#
# FEATURE BB_WIND_TWIGS_TREES=1 (default 0; needs BB_WIND_TWIGS above 0 and BB_WIND_TWIGS_SMALL above 0):
#  1. SwayWanted: an opaque motion pipeline with no skeleton read (a small bone palette: the big bare trees of build 51)
#     carries the sway bit (the shaders then hold the sway code; a draw moves only with a sway word).
#  2. A candidate draw (Kind::GpuPalette or Kind::Other of a sway pipeline) goes through WindTreesDraw before the slot is
#     taken: the lowest and highest index value of the draw (at most 262144 indices read) give its vertex range; up to
#     4096 of its vertices are read from guest memory and BbWindTrees::ShapeOf judges them (for some axis as up: the
#     lowest quarter of the height is thin (a radius of at most 0.15 of the height), the upper half spreads at least 2.5
#     times as wide, 0.25 to 1.6 of the height wide; a wall, a floor, a column, a tower, a cone or a lamp post is not). The
#     verdict is kept 3600 frames per (stream, base vertex, index address, index count). Not tree-shaped: no word (a
#     building, a wall, an interior mesh, the ground never get one). A tree-shaped draw is taken only while the camera is
#     outdoors (r117's field: BbWindShelter open share at the camera at least 0.5 with BB_WIND_SHELTER=1; without the
#     field the camera counts as outdoors).
#  3. A taken draw is a mesh of its own: its sway slot key is the address of its first used vertex and its size the bytes
#     of its vertex range, so the base, crown and box keys the shaders keep measure ONE tree, not the union of a stand
#     (the cause of the box rule's failure in r89g). The twig judgement (BbWindTwigs::Judge, loose: height 4 to 40 m, still)
#     then reads that tree's box.
#  4. BbWindTwigs::FitOn() is false while TREES is on: the shaders use the mesh rule (BbWindSway::TwigWeight: how far the
#     vertex is from the box's centre line over the half width, and its height over the mesh's own lowest point) in place of
#     the fit rule (its height over the camera): the weight lands on the thin outer branches of that tree, not on the
#     trunk top. The push rule (r89h) and the proof counters are unchanged. Shader cache versions: FitAdd is not added
#     (a known sum: KnownVersion lists every subset), so TREES on builds its own shader binaries; off nothing changes.
#     A cost of this: sun-drawn skinned tree words of the older rule (a stand-wide stream key) now get the mesh rule on
#     their stand's box too (a small weight): only the per-draw trees are meant to move with TREES on.
# OFF (default): TreesWanted() is a static bool (false): FitOn(), SwayWanted, the WindSwayWord block, the DrawRecord note,
# the report line and WindTwigWord's loose rule see it false and run no new code; no pipeline key, shader, cache version
# or log line differs from r89i.
# COST ON: CPU: a hash lookup a candidate draw; a new draw range costs one index scan (<= 262144 indices) and a read of
# <= 4096 vertices plus a sort of that many numbers three times (about 1 ms once per draw range, held 3600 frames);
# GPU: the sway code of the pipelines that carry the bit (opaque palette pipelines) runs only for draws with a word, so
# for the taken trees; more pipeline compiles at first sight (one-time). Memory: the book of at most 4096 meshes (about 100 KB).
# NOT TESTED in the game: whether the trees' draws are Kind::GpuPalette with a sway bit under this rule (the pick says),
# whether their index values lie in one contiguous range per tree, whether the stand's base vertex is the draw's.
#
# Files: new engine/gpu/shim/bbport_wind_trees.h, engine/tests/test_wind_trees.cpp. Edited: bbport_wind_twigs.h
# (TreesWanted, FitOn), vk_pipeline_cache.cpp (SwayWanted), vk_rasterizer.h (include, declarations, members),
# vk_rasterizer.cpp (the draw's range, the pick's notes, the query hook, the scissor), vk_rasterizer_effects.cpp (the
# WindSwayWord block, the loose rule, the frame-end call, the three functions), build.sh, gpu/CMakeLists.txt (the test),
# README.md (two rows). Compatible with the wave 40 and 41 drafts: only the twig code and hook lines of its own.
# Order: after r89i (build 51).
#
# Use: python -I -X utf8 r89j_twigs-pick-trees.py check | apply | revert (root from R89J_ROOT, else <tree>).
# Files keep their line ends. Originals are kept in r89j_backup/ next to this script; revert deletes the two new files.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89j_backup")
ROOT = os.environ.get("R89J_ROOT") or "<tree>"
G = "engine/gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
TWIGS = G + "shim/bbport_wind_twigs.h"
CACHE = R + "vk_pipeline_cache.cpp"
RASTH = R + "vk_rasterizer.h"
RAST = R + "vk_rasterizer.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
BUILD = "engine/build.sh"
CMAKE = G + "CMakeLists.txt"
README = "README.md"
NEWH = G + "shim/bbport_wind_trees.h"
NEWT = "engine/tests/test_wind_trees.cpp"

NEW_FILES = {
    NEWH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
inline constexpr float OpenMin = 0.5f;                   ///< the camera's open wind share needed (r117's field)
inline constexpr std::uint64_t RecheckFrames = 3600;     ///< a verdict is made again after this many frames
inline constexpr std::size_t BookMost = 4096;            ///< meshes known at most
inline constexpr std::uint32_t JudgeMost = 8;            ///< draw ranges judged a frame at most (the rest keep an
                                                         ///< older verdict or wait a frame: no hitch at first sight
                                                         ///< or when many verdicts expire together)
inline constexpr unsigned MeshLines = 12;                ///< verdict lines logged at most

inline constexpr std::size_t PickMost = 8;               ///< pick points at most
inline constexpr std::uint32_t PickPerGroup = 4096;      ///< G-buffer draws measured in a pick frame at most
inline constexpr std::uint32_t PickGroups = 4;           ///< pick frames of queries in flight at most
inline constexpr std::uint64_t PickFramesPerPoint = 2;
inline constexpr std::uint64_t PickFrameDefault = 900;
inline constexpr int PickHalf = 1;                       ///< the patch is 2 * PickHalf + 1 pixels wide
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

// ------------------------------------------------------------------------------------------- the book

/// One draw's vertex range (a mesh of its own) and the verdict on it.
struct Mesh {
    bool tree = false;
    std::uint64_t addr = 0;           ///< the address of its first used vertex: its key for the sway slot
    std::uint32_t size = 0;           ///< bytes of its vertex range
    std::uint32_t verts = 0;
    Shape shape;
    const char* why = "unread";       ///< a string literal: why it is no tree
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
                  static_cast<double>(SpreadMin), static_cast<double>(OpenMin));
}

inline void LineText(const Stats& s, const Book& book, unsigned frames, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs trees (r89j): in %u frames %llu candidate draws: %llu taken (tree-shaped), %llu refused "
                  "(shape), %llu indoors, %llu unread; %llu draw ranges judged (%llu tree-shaped, %llu not); book %zu "
                  "meshes, %zu tree-shaped",
                  frames, n(s.draws), n(s.taken), n(s.refused), n(s.indoors), n(s.unread), n(s.new_meshes),
                  n(s.tree_meshes), n(s.refused_meshes), book.Size(), book.Trees());
}

inline void MeshText(const Mesh& m, std::uint64_t key_stream, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs trees (r89j) mesh: stream %llx, vertex range at %llx, %u vertices: %s (model height "
                  "%.2f, trunk radius %.3f, crown radius %.3f, up axis %d%s%s)",
                  static_cast<unsigned long long>(key_stream), static_cast<unsigned long long>(m.addr), m.verts,
                  m.tree ? "TREE-SHAPED" : "refused", static_cast<double>(m.shape.height),
                  static_cast<double>(m.shape.trunk), static_cast<double>(m.shape.crown), m.shape.up,
                  m.tree ? "" : ", why ", m.tree ? "" : m.why);
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
};

[[nodiscard]] inline PickKnob ParsePick(const char* list, const char* size, const char* frame) {
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
    return k;
}

[[nodiscard]] inline const PickKnob& PickOnce() {
    static const PickKnob knob = ParsePick(std::getenv("BB_WIND_TWIGS_PICK"), std::getenv("BB_WIND_TWIGS_PICK_SIZE"),
                                           std::getenv("BB_WIND_TWIGS_PICK_FRAME"));
    return knob;
}

/// BB_WIND_TWIGS_PICK names at least one pixel (TOOL).
[[nodiscard]] inline bool PickOn() {
    return PickOnce().count > 0;
}

/// The point a pick frame draws for (the frame count the frame will have), -1 outside the pick.
[[nodiscard]] inline int PointAt(std::uint64_t frame, std::uint64_t start, std::size_t count) {
    if (frame < start) {
        return -1;
    }
    const std::uint64_t k = (frame - start) / PickFramesPerPoint;
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

/// What the rasterizer knew of one G-buffer draw of a pick frame.
struct PickDraw {
    std::uint32_t vs = 0, ps = 0;
    std::uint32_t stream_verts = 0, stride = 0, indices = 0, first = 0, sway = 0;
    std::int32_t base = 0;
    int kind = 3;                    ///< 0 skinned, 1 GPU palette, 2 static, 3 no motion block
    bool cutout = false, sway_bit = false, motion = false, depth_write = false;
    std::uint64_t stream = 0;        ///< the position stream's address (0: none)
    std::uint64_t index_address = 0;
};

struct PickResult {
    bool found = false;
    std::size_t row = 0;             ///< the winner: the last draw that passed with depth write
    std::size_t passed = 0;          ///< draws with samples at the patch
    std::array<std::size_t, PickUnder> under{};
    std::size_t under_n = 0;         ///< earlier draws that passed as well (most recent first)
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

inline void PickNoneLine(const Point& pt, const Rect& rect, std::size_t total, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j): pixel %d,%d (render %d,%d): no G-buffer draw of %zu wrote depth there "
                  "(sky, or the patch missed)",
                  pt.x, pt.y, rect.cx, rect.cy, total);
}

inline void PickOnceText(const PickKnob& k, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs pick (r89j, TOOL, BB_WIND_TWIGS_PICK): %zu pixel(s) of a %ux%u picture, from frame %llu "
                  "on, %llu frames a pixel: those frames draw only a %dx%d patch of the G-buffer (the picture is "
                  "broken for them); an occlusion query a draw names the last draw that passed the depth test with "
                  "depth write there",
                  k.count, k.out_w, k.out_h, static_cast<unsigned long long>(k.start),
                  static_cast<unsigned long long>(PickFramesPerPoint), 2 * PickHalf + 1, 2 * PickHalf + 1);
}

} // namespace BbWindTrees
''',
    NEWT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
            std::numeric_limits<std::uint64_t>::max();
        B::Book book;
        char text[720];
        B::LineText(s, book, 600, text, sizeof(text));
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
    }

    // The patch.
    {
        const B::Point p{640, 360};
        const B::Rect r = B::PickRect(p, 1280, 720, 1280, 720);
        Expect(r.cx == 640 && r.cy == 360 && r.x == 639 && r.y == 359 && r.w == 3 && r.h == 3, "the same size");
        const B::Rect half = B::PickRect(p, 1280, 720, 640, 360);
        Expect(half.cx == 320 && half.cy == 180 && half.w == 3, "a render target of half the size");
        const B::Rect corner = B::PickRect({0, 0}, 1280, 720, 1280, 720);
        Expect(corner.x == 0 && corner.y == 0 && corner.w == 2 && corner.h == 2, "the corner is cut");
        const B::Rect outside = B::PickRect({5000, 5000}, 1280, 720, 1280, 720);
        Expect(outside.cx == 1279 && outside.cy == 719 && outside.w == 2 && outside.h == 2, "outside: the last pixel");
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
        B::PickNoneLine({1, 2}, B::PickRect({1, 2}, 1280, 720, 1280, 720), 12, text, sizeof(text));
        Expect(std::strstr(text, "no G-buffer draw of 12 wrote depth there") != nullptr, "the none line");
        B::PickOnceText(B::ParsePick("1,2;3,4", nullptr, nullptr), text, sizeof(text));
        Expect(std::strstr(text, "2 pixel(s) of a 1280x720 picture, from frame 900 on, 2 frames a pixel") != nullptr &&
                   std::strlen(text) < 720,
               "the once line of the pick");
    }

    if (failures == 0) {
        std::printf("wind-trees-test: ok\n");
    }
    return failures == 0 ? 0 : 1;
}
''',
}

# ---------------------------------------------------------------- bbport_wind_twigs.h
TW_OLD = ("[[nodiscard]] inline bool FitOn() {\n"
          "    return KnobOnce().on && KnobOnce().fit >= 1;\n"
          "}\n")
TW_NEW = (
    "/// bbport (r89j_twigs-pick-trees): BB_WIND_TWIGS_TREES (read once; default 0): the tree draws are taken by the shape of\n"
    "/// their own vertices, each draw its own mesh (bbport_wind_trees.h), and the twig weight is the mesh rule, not the fit\n"
    "/// rule. Needs the twigs on and BB_WIND_TWIGS_SMALL above 0.\n"
    "[[nodiscard]] inline bool TreesWanted() {\n"
    "    static const bool wanted = W::ParseNumber(std::getenv(\"BB_WIND_TWIGS_TREES\"), 0.0f) >= 0.5f;\n"
    "    return wanted && KnobOnce().on && KnobOnce().small >= 1;\n"
    "}\n"
    "\n"
    "[[nodiscard]] inline bool FitOn() {\n"
    "    return KnobOnce().on && KnobOnce().fit >= 1 && !TreesWanted(); // bbport (r89j): TREES: the mesh rule\n"
    "}\n")

# ---------------------------------------------------------------- vk_pipeline_cache.cpp
PC_OLD = "            (BbWindCensus::StaticOpaque() && !SkeletonRead(sel)));\n"
PC_NEW = (
    "            (BbWindCensus::StaticOpaque() && !SkeletonRead(sel)) ||\n"
    "            // bbport (r89j_twigs-pick-trees): BB_WIND_TWIGS_TREES: also an opaque pipeline with a small bone palette (a tree)\n"
    "            (BbWindTwigs::TreesWanted() && !SkeletonRead(sel)));\n")

# ---------------------------------------------------------------- vk_rasterizer.h
RH_INC_OLD = '#include "bbport_wind_census.h" // bbport (r89i_twigs-colour-pass)\n'
RH_INC_NEW = RH_INC_OLD + '#include "bbport_wind_trees.h" // bbport (r89j_twigs-pick-trees)\n'

RH_DECL_OLD = ("    void WindTwigCensus(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, bool is_indexed,\n"
               "                        u32 index_offset, int kind_slot, u32 sway, int base_vertex);\n")
RH_DECL_NEW = RH_DECL_OLD + (
    "    /// bbport (r89j_twigs-pick-trees; BB_WIND_TWIGS_TREES=1): whether the candidate draw (trees_draw) is a tree-shaped\n"
    "    /// mesh of its own and the camera is outdoors; true: positions and positions_size become its vertex range\n"
    "    bool WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats);\n"
    "    /// bbport (r89j_twigs-pick-trees, TOOL; BB_WIND_TWIGS_PICK): a G-buffer draw of a pick frame gets an occlusion query\n"
    "    void WindTreesPickQuery(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, u32 index_offset,\n"
    "                            s32 base_vertex, vk::QueryPool& pool, u32& index);\n"
    "    /// the trees' line every report, the pick's frames and results (once a frame)\n"
    "    void WindTreesPickFrameEnd();\n")

RH_MEMBER_OLD = "    BbWindCensus::Book twig_census; // bbport (r89i_twigs-colour-pass, TOOL): the colour passes' rows\n"
RH_MEMBER_NEW = RH_MEMBER_OLD + (
    "    /// bbport (r89j_twigs-pick-trees): the index range of the candidate draw being recorded (WindTreesDraw), the verdicts\n"
    "    /// on draw ranges, the counters; the pick's note of the draw (kind, sway word), queries and patch\n"
    "    struct TreesDraw {\n"
    "        u64 index_address = 0;\n"
    "        u32 num_indices = 0;\n"
    "        s32 base_vertex = 0;\n"
    "        u32 index_size = 0;\n"
    "        bool valid = false;\n"
    "    } trees_draw;\n"
    "    BbWindTrees::Book trees_book;\n"
    "    BbWindTrees::Stats trees_stats;\n"
    "    unsigned trees_lines = 0;\n"
    "    u64 trees_frames = 0;\n"
    "    struct TreesPickNote {\n"
    "        int kind = 3;\n"
    "        u32 sway = 0;\n"
    "    } trees_pick_note;\n"
    "    struct TreesPickGroup {\n"
    "        u32 used = 0;\n"
    "        bool pending = false;\n"
    "        u64 tick = 0;\n"
    "        u32 point = 0;\n"
    "        u32 skipped = 0;\n"
    "        BbWindTrees::Rect rect{};\n"
    "        std::vector<BbWindTrees::PickDraw> draws;\n"
    "    };\n"
    "    struct TreesPick {\n"
    "        vk::UniqueQueryPool pool{};\n"
    "        bool tried = false;\n"
    "        bool said = false;\n"
    "        u32 group = 0;\n"
    "        u64 frame = 0;\n"
    "        std::array<TreesPickGroup, BbWindTrees::PickGroups> groups;\n"
    "    } trees_pick;\n"
    "    bool trees_pick_rect_on = false; ///< this frame draws only the pick's patch of the G-buffer\n"
    "    vk::Rect2D trees_pick_rect{};\n")

# ---------------------------------------------------------------- vk_rasterizer.cpp
RC_RANGE_OLD = "        // bbport (r89_wind-foliage-sway): a plant's sway word (WindSwayWord); 0 for every other\n"
RC_RANGE_NEW = (
    "        if (BbWindTwigs::TreesWanted()) { // bbport (r89j_twigs-pick-trees): this draw's index range, for WindTreesDraw\n"
    "            trees_draw = {index_address, regs.num_indices, s32(base_vertex), index_size, indices_valid};\n"
    "        }\n" + RC_RANGE_OLD)

RC_NOTE_A_OLD = "        if (BbWindCensus::CensusOn()) { // bbport (r89i_twigs-colour-pass, TOOL): this draw's row\n"
RC_NOTE_A_NEW = (
    "        if (BbWindTrees::PickOn()) { // bbport (r89j_twigs-pick-trees, TOOL): the pick names this draw's kind and word\n"
    "            trees_pick_note = {r34_kind == Motion::Kind::Skinned\n"
    "                                   ? 0\n"
    "                                   : (r34_kind == Motion::Kind::GpuPalette ? 1 : 2),\n"
    "                               sway};\n"
    "        }\n" + RC_NOTE_A_OLD)

RC_NOTE_B_OLD = "    if (BbWindCensus::CensusOn() && !(dc.motion_draw && dc.motion_geometry)) { // bbport (r89i_twigs-colour-pass, TOOL)\n"
RC_NOTE_B_NEW = (
    "    if (BbWindTrees::PickOn() && !(dc.motion_draw && dc.motion_geometry)) { // bbport (r89j_twigs-pick-trees, TOOL)\n"
    "        trees_pick_note = {3, 0u};\n"
    "    }\n" + RC_NOTE_B_OLD)

RC_QUERY_OLD = ("        SunAtlasReaderQuery(query.pool, query.index);\n"
                "    }\n")
RC_QUERY_NEW = RC_QUERY_OLD + (
    "    if (trees_pick_rect_on && gbuffer_draw) { // bbport (r89j_twigs-pick-trees, TOOL): this draw's query, for the pick\n"
    "        WindTreesPickQuery(pipeline, regs, index_offset, s32(vertex_offset), query.pool, query.index);\n"
    "    }\n")

RC_SCISSOR_OLD = "        scissors.push_back(DrawScissor(i));\n"
RC_SCISSOR_NEW = (
    "        vk::Rect2D scissor = DrawScissor(i);\n"
    "        if (trees_pick_rect_on && gbuffer_draw) { // bbport (r89j_twigs-pick-trees, TOOL): only the pick's patch is drawn\n"
    "            const s32 x0 = std::max(scissor.offset.x, trees_pick_rect.offset.x);\n"
    "            const s32 y0 = std::max(scissor.offset.y, trees_pick_rect.offset.y);\n"
    "            const s32 x1 = std::min(scissor.offset.x + s32(scissor.extent.width),\n"
    "                                    trees_pick_rect.offset.x + s32(trees_pick_rect.extent.width));\n"
    "            const s32 y1 = std::min(scissor.offset.y + s32(scissor.extent.height),\n"
    "                                    trees_pick_rect.offset.y + s32(trees_pick_rect.extent.height));\n"
    "            scissor = vk::Rect2D{.offset = {x0, y0}, .extent = {u32(std::max(x1 - x0, 0)), u32(std::max(y1 - y0, 0))}};\n"
    "        }\n"
    "        scissors.push_back(scissor);\n")

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
EF_BLOCK_OLD = "    const bool plant = small_palette < 0 && rt_shadow->LonePlant(positions, positions_size);\n"
EF_BLOCK_NEW = (
    "    // bbport (r89j_twigs-pick-trees): BB_WIND_TWIGS_TREES: a candidate draw (static or GPU palette, no hanging mesh) is a\n"
    "    // tree when its own vertices are tree-shaped and the camera is outdoors; its vertex range is then its mesh\n"
    "    // (positions and positions_size become its key and size). Anything else of a candidate gets no word.\n"
    "    if (small_palette >= 0 && !hang_static && BbWindTwigs::TreesWanted() &&\n"
    "        !WindTreesDraw(positions, positions_size, positions_stride, positions_floats)) {\n"
    "        return 0;\n"
    "    }\n" + EF_BLOCK_OLD)

EF_LOOSE_OLD = "            entry.loose = entry.loose || (BbWindCensus::PaletteOn() && info->palette);\n"
EF_LOOSE_NEW = ("            // bbport (r89j_twigs-pick-trees): with TREES the shape rule has judged the draw: height and stillness only\n"
                "            entry.loose = entry.loose || BbWindTrees::On() || (BbWindCensus::PaletteOn() && info->palette);\n")

EF_FRAME_OLD = "    WindSwayFrameEnd(); // bbport (r89_wind-foliage-sway): its log lines\n"
EF_FRAME_NEW = EF_FRAME_OLD + "    WindTreesPickFrameEnd(); // bbport (r89j_twigs-pick-trees): the trees' line, the pick (TOOL)\n"

EF_FUNC_OLD = "// bbport (r89i_twigs-colour-pass, TOOL; BB_WIND_TWIGS_CENSUS=1): one draw of the G-buffer or a sun shadow pass\n"
EF_FUNC_NEW = r'''// bbport (r89j_twigs-pick-trees; BB_WIND_TWIGS_TREES=1): whether the candidate draw being recorded (trees_draw: its index
// range) is a tree. Its vertex range is found from the lowest and highest index value (at most ShapeIndexMax indices read
// from guest memory), up to ShapeSamples of its vertices are read and BbWindTrees::ShapeOf judges their shape, once per
// (stream, base vertex, index address, index count) and RecheckFrames frames. A tree-shaped draw is taken only while the
// camera is outdoors (r117's field at the camera; without the field the camera counts as outdoors). True: `positions` and
// `positions_size` are then the draw's own vertex range (the address of its first used vertex, its bytes): the key and the
// size of its sway slot, so the box keys the shaders keep measure one tree. On the thread recording draws.
bool Rasterizer::WindTreesDraw(u64& positions, u32& positions_size, u32 stride, bool floats) {
    BbWindTrees::Stats& st = trees_stats;
    ++st.draws;
    const TreesDraw& d = trees_draw;
    if (positions == 0 || positions_size == 0 || stride < 12 || !floats || !d.valid || d.num_indices == 0 ||
        (d.index_size != 2 && d.index_size != 4)) {
        ++st.unread;
        return false;
    }
    const u64 frame = object_motion->Frame();
    const u64 key = BbWindTrees::MeshKey(positions, d.base_vertex, d.index_address, d.num_indices);
    BbWindTrees::Mesh* mesh = trees_book.Find(key, frame);
    if (mesh == nullptr) { // at most JudgeMost draw ranges judged a frame: an older verdict holds, or the draw waits
        static u64 judge_frame = ~u64(0);
        static u32 judged = 0;
        if (judge_frame != frame) {
            judge_frame = frame;
            judged = 0;
        }
        if (judged >= BbWindTrees::JudgeMost) {
            mesh = trees_book.Any(key);
            if (mesh == nullptr) {
                ++st.unread;
                return false;
            }
        } else {
            ++judged;
        }
    }
    if (mesh == nullptr) {
        BbWindTrees::Mesh fresh;
        fresh.at = frame;
        const unsigned char* const data = reinterpret_cast<const unsigned char*>(d.index_address);
        const u32 count = std::min<u32>(d.num_indices, BbWindTrees::ShapeIndexMax);
        u32 lo = 0xffffffffu;
        u32 hi = 0;
        for (u32 i = 0; i < count; ++i) {
            u32 value = 0;
            if (d.index_size == 2) {
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
        const s64 first = s64(d.base_vertex) + s64(lo);
        const u64 verts = lo <= hi ? u64(hi) - u64(lo) + 1u : u64(0);
        if (lo > hi) {
            fresh.why = "indices";
        } else if (first < 0) {
            fresh.why = "base";
        } else if (verts < BbWindTwigs::SmallMinVerts) {
            fresh.why = "verts-few";
        } else if (verts > BbWindTwigs::SmallMaxVerts) {
            fresh.why = "verts-many";
        } else {
            const u64 address = positions + u64(first) * stride;
            const u64 bytes = verts * stride;
            if (!memory->IsValidGpuMapping(address, 0) || memory->ClampRangeSize(address, bytes) != bytes) {
                fresh.why = "memory";
            } else if (buffer_cache.IsRegionGpuModified(address, bytes)) {
                fresh.why = "gpu";
            } else {
                const unsigned char* const base = reinterpret_cast<const unsigned char*>(address);
                const u64 step = std::max<u64>(1, verts / BbWindTrees::ShapeSamples);
                std::vector<float> samples;
                samples.reserve(3 * BbWindTrees::ShapeSamples + 3);
                for (u64 v = 0; v < verts; v += step) {
                    float xyz[3];
                    std::memcpy(xyz, base + v * stride, sizeof(xyz));
                    if (std::isfinite(xyz[0]) && std::isfinite(xyz[1]) && std::isfinite(xyz[2])) {
                        samples.push_back(xyz[0]);
                        samples.push_back(xyz[1]);
                        samples.push_back(xyz[2]);
                    }
                }
                fresh.shape = BbWindTrees::ShapeOf(samples.data(), samples.size() / 3);
                fresh.tree = fresh.shape.tree;
                fresh.why = fresh.shape.why != nullptr ? fresh.shape.why : "";
                fresh.addr = address;
                fresh.size = static_cast<u32>(bytes);
                fresh.verts = static_cast<u32>(verts);
            }
        }
        ++st.new_meshes;
        if (fresh.tree) {
            ++st.tree_meshes;
        } else {
            ++st.refused_meshes;
        }
        mesh = &trees_book.Put(key, fresh);
        static unsigned refused_lines = 0;
        unsigned& lines = fresh.tree ? trees_lines : refused_lines;
        if (lines < (fresh.tree ? BbWindTrees::MeshLines : BbWindTrees::MeshLines / 2)) {
            ++lines;
            char text[512];
            BbWindTrees::MeshText(*mesh, positions, text, sizeof(text));
            BbReport::Printf("%s\n", text);
        }
    }
    if (!mesh->tree) {
        ++st.refused;
        return false;
    }
    if (wind_shelter != nullptr && wind_shelter->CameraOpen() < BbWindTrees::OpenMin) {
        ++st.indoors;
        return false;
    }
    positions = mesh->addr;
    positions_size = mesh->size;
    ++st.taken;
    return true;
}

// bbport (r89j_twigs-pick-trees, TOOL; BB_WIND_TWIGS_PICK): the G-buffer draw being recorded in a pick frame gets the next
// query of the pool (a draw another query wraps, or a full group, is left out) and its facts are kept for the winner
// rule: the pipeline's shader hashes, cut-out, sway bit, motion pipeline, depth write, the position stream, the draw's
// range, its kind and sway word (trees_pick_note, set by the Motion block or the census site of the draw). On the thread
// recording draws.
void Rasterizer::WindTreesPickQuery(const GraphicsPipeline* pipeline, const AmdGpu::Regs& regs, u32 index_offset,
                                    s32 base_vertex, vk::QueryPool& pool, u32& index) {
    TreesPick& p = trees_pick;
    if (!p.pool || pool) {
        return;
    }
    TreesPickGroup& g = p.groups[p.group];
    if (g.pending) {
        return;
    }
    if (g.used >= BbWindTrees::PickPerGroup) {
        ++g.skipped; // no query left: the report says so (a missing late draw could be the winner)
        return;
    }
    const auto& key = pipeline->GetGraphicsKey();
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
    const auto& fetch = pipeline->GetFetchShader();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    BbWindTrees::PickDraw d;
    d.vs = static_cast<u32>(vs.pgm_hash & 0xffffffffu);
    d.ps = static_cast<u32>(FragmentHash(pipeline) & 0xffffffffu);
    d.indices = regs.num_indices;
    d.first = index_offset;
    d.base = base_vertex;
    d.kind = trees_pick_note.kind;
    d.sway = trees_pick_note.sway;
    d.cutout = ps != nullptr && ps->has_discard;
    d.sway_bit = (key.motion_vectors & Shader::MotionVectors::Sway) != 0;
    d.motion = (key.motion_vectors & Shader::MotionVectors::VertexOutputs) != 0;
    d.depth_write = regs.depth_control.depth_write_enable != 0;
    const u32 index_size = regs.index_buffer_type.index_type == AmdGpu::IndexType::Index16 ? 2u : 4u;
    d.index_address = regs.index_base_address.Address<VAddr>() + u64(index_offset) * index_size;
    if (fetch) {
        for (const auto& attribute : fetch->attributes) {
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                d.stream = stream.base_address;
                d.stride = stream.GetStride();
                d.stream_verts = d.stride != 0 ? stream.GetSize() / d.stride : 0u;
                break;
            }
        }
    }
    pool = *p.pool;
    index = p.group * BbWindTrees::PickPerGroup + g.used++;
    g.draws.push_back(d);
}

// bbport (r89j_twigs-pick-trees), once a frame (EffectsOnFrameEnd): the once lines; with BB_WIND_TWIGS_TREES the trees'
// line every BbWindSway::ReportFrames frames; with BB_WIND_TWIGS_PICK (TOOL) the pick: this frame's group of queries is
// closed (it waits for the GPU's tick), groups the GPU has passed are read without waiting (the winner rule and the log
// lines; the query range is reset from the host), and the next frame's patch is set while it lies in the pick's frames.
void Rasterizer::WindTreesPickFrameEnd() {
    static bool trees_said = false;
    if (!trees_said && BbWindTrees::On()) {
        trees_said = true;
        char once[1024];
        BbWindTrees::OnceText(once, sizeof(once));
        BbReport::Printf("%s\n", once);
    }
    if (BbWindTrees::On() && ++trees_frames % BbWindSway::ReportFrames == 0) {
        char text[704];
        BbWindTrees::LineText(trees_stats, trees_book, BbWindSway::ReportFrames, text, sizeof(text));
        BbReport::Printf("%s\n", text);
        trees_stats = {};
    }
    if (!BbWindTrees::PickOn()) {
        return;
    }
    TreesPick& p = trees_pick;
    const BbWindTrees::PickKnob& knob = BbWindTrees::PickOnce();
    ++p.frame;
    const vk::Device device = instance.GetDevice();
    constexpr u32 queries = BbWindTrees::PickPerGroup * BbWindTrees::PickGroups;
    if (!p.tried) {
        p.tried = true;
        if (instance.IsHostQueryResetSupported()) {
            const vk::QueryPoolCreateInfo info = {
                .queryType = vk::QueryType::eOcclusion,
                .queryCount = queries,
            };
            auto created = device.createQueryPoolUnique(info);
            if (created.result == vk::Result::eSuccess) {
                p.pool = std::move(created.value);
                device.resetQueryPool(*p.pool, 0, queries);
            }
        }
    }
    if (!p.said) {
        p.said = true;
        char once[768];
        BbWindTrees::PickOnceText(knob, once, sizeof(once));
        BbReport::Printf("%s%s\n", once, p.pool ? "" : " (NO host query reset or no query pool: the pick cannot run)");
    }
    if (!p.pool) {
        return;
    }
    if (trees_pick_rect_on) { // this frame drew the patch: its group goes to the GPU
        TreesPickGroup& g = p.groups[p.group];
        if (g.used != 0) {
            g.pending = true;
            g.tick = scheduler.CurrentTick();
            p.group = (p.group + 1) % BbWindTrees::PickGroups;
        }
        trees_pick_rect_on = false;
    }
    for (u32 gi = 0; gi < BbWindTrees::PickGroups; ++gi) {
        TreesPickGroup& g = p.groups[gi];
        if (!g.pending || !scheduler.IsFree(g.tick)) {
            continue;
        }
        const u32 n = g.used;
        std::vector<u64> counts(n, u64(0));
        const vk::Result result = device.getQueryPoolResults(*p.pool, gi * BbWindTrees::PickPerGroup, n,
                                                             n * sizeof(u64), counts.data(), sizeof(u64),
                                                             vk::QueryResultFlagBits::e64);
        const BbWindTrees::Point& pt = knob.points[g.point];
        char text[704];
        if (result != vk::Result::eSuccess) {
            std::snprintf(text, sizeof(text),
                          "Wind twigs pick (r89j): pixel %d,%d: the query results were not available (result %d)", pt.x,
                          pt.y, static_cast<int>(result));
            BbReport::Printf("%s\n", text);
        } else {
            const u64 frame = object_motion->Frame();
            WindHangFindRefresh(frame);
            const auto describe = [&](std::size_t row, std::size_t passed, bool is_under) {
                const BbWindTrees::PickDraw& d = g.draws[row];
                char box[200];
                std::snprintf(box, sizeof(box), "no scene box for the stream");
                if (const BbWindHangFind::Box* const b = hang_find_boxes.Find(d.stream)) {
                    std::snprintf(box, sizeof(box), "scene box y %.1f..%.1f m, %.1f x %.1f m wide",
                                  static_cast<double>(b->box[1]), static_cast<double>(b->box[4]),
                                  static_cast<double>(b->box[3] - b->box[0]), static_cast<double>(b->box[5] - b->box[2]));
                    if (hang_find_boxes.camera_ok) {
                        char tail[96];
                        std::snprintf(tail, sizeof(tail), "; over the camera %.1f..%.1f m",
                                      static_cast<double>(b->box[1] - hang_find_boxes.camera[1]),
                                      static_cast<double>(b->box[4] - hang_find_boxes.camera[1]));
                        std::strncat(box, tail, sizeof(box) - std::strlen(box) - 1);
                    }
                }
                const u64 mesh_key = BbWindTrees::MeshKey(d.stream, d.base, d.index_address, d.indices);
                const BbWindTrees::Mesh* const mesh = trees_book.Find(mesh_key, frame);
                const BbWindTwigs::Entry* const entry =
                    twig_book.Find(mesh != nullptr && mesh->tree ? mesh->addr : d.stream);
                const char* const entry_why = entry != nullptr && entry->why != nullptr ? entry->why : "";
                char book[200];
                std::snprintf(book, sizeof(book), "tree shape: %s; twig book: %s%s%s%s",
                              mesh != nullptr ? (mesh->tree ? "TREE-SHAPED" : mesh->why) : "not judged",
                              entry == nullptr ? "no entry"
                                               : (entry->verdict == BbWindTwigs::Verdict::Tree
                                                      ? "Tree"
                                                      : (entry->verdict == BbWindTwigs::Verdict::NotTree ? "NotTree"
                                                                                                         : "Waiting")),
                              entry_why[0] != '\0' ? " (" : "", entry_why, entry_why[0] != '\0' ? ")" : "");
                char line[704];
                BbWindTrees::PickLine(pt, g.rect, row, g.draws.size(), passed, d, is_under, box, book, line,
                                      sizeof(line));
                BbReport::Printf("%s\n", line);
            };
            const BbWindTrees::PickResult res = BbWindTrees::PickWinner(g.draws, counts.data());
            if (!res.found) {
                BbWindTrees::PickNoneLine(pt, g.rect, g.draws.size(), text, sizeof(text));
                BbReport::Printf("%s\n", text);
            } else {
                describe(res.row, res.passed, false);
                for (std::size_t k = 0; k < res.under_n; ++k) {
                    describe(res.under[k], res.passed, true);
                }
            }
        }
        if (g.skipped != 0) {
            std::snprintf(text, sizeof(text),
                          "Wind twigs pick (r89j): NOTE pixel %d,%d: %u G-buffer draws of that frame had no query (the group "
                          "of %u was full): a late draw may be the real winner",
                          pt.x, pt.y, g.skipped, static_cast<unsigned>(BbWindTrees::PickPerGroup));
            BbReport::Printf("%s\n", text);
        }
        device.resetQueryPool(*p.pool, gi * BbWindTrees::PickPerGroup, n);
        g.pending = false;
        g.used = 0;
        g.skipped = 0;
        g.draws.clear();
    }
    const int point = BbWindTrees::PointAt(p.frame + 1, knob.start, knob.count);
    if (point >= 0 && camera_motion && !p.groups[p.group].pending) {
        const auto size = camera_motion->RenderSize();
        const BbWindTrees::Rect r = BbWindTrees::PickRect(knob.points[static_cast<std::size_t>(point)], knob.out_w,
                                                          knob.out_h, size[0], size[1]);
        if (r.w > 0 && r.h > 0) {
            trees_pick_rect = vk::Rect2D{.offset = {r.x, r.y}, .extent = {u32(r.w), u32(r.h)}};
            trees_pick_rect_on = true;
            p.groups[p.group].point = static_cast<u32>(point);
            p.groups[p.group].rect = r;
        }
    }
}

''' + EF_FUNC_OLD

# ---------------------------------------------------------------- build.sh, CMake, README
BS_OLD = "    out/wind-census-test\n"
BS_NEW = BS_OLD + (
    "    # bbport (r89j_twigs-pick-trees): the tree shape rule, the pick's points, patch and winner rule\n"
    "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_trees.cpp -o out/wind-trees-test\n"
    "    out/wind-trees-test\n")

CM_OLD = "target_include_directories(wind-census-test PRIVATE ..)\n"
CM_NEW = CM_OLD + (
    "# bbport (r89j_twigs-pick-trees): the tree shape rule, the pick's points, patch and winner rule (shim/bbport_wind_trees.h);\n"
    "# also built and run by engine/build.sh --test.\n"
    "add_executable(wind-trees-test EXCLUDE_FROM_ALL ../tests/test_wind_trees.cpp)\n"
    "target_compile_options(wind-trees-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
    "target_include_directories(wind-trees-test PRIVATE ..)\n")

README_ANCHOR = "| `BB_WIND_TWIGS_CENSUS` |"
README_NEW = (
    "| `BB_WIND_TWIGS_TREES` | Which draws are the trees (`BB_WIND_TWIGS` and `BB_WIND_TWIGS_SMALL` rows; r89j): `1` takes a draw of a pipeline with the sway bit (a cut-out, or an opaque one with a small bone palette) as a tree only when the shape of its own vertices says so (for some axis as up: the lowest quarter of the height is thin, a radius of at most 0.15 of the height, the upper half spreads at least 2.5 times as wide, 0.25 to 1.6 of the height wide; a wall, a floor, a column, a tower, a cone or a lamp post is not) and the camera is outdoors (open wind share at least 0.5 with `BB_WIND_SHELTER=1`); each such draw is a mesh of its own (the address of its first used vertex is its sway slot key, so the keys measure one tree, not a stand), and the twig weight is the mesh rule (height over the mesh's own lowest point and distance from its centre line) in place of the fit rule (height over the camera): the weight lands on the thin outer branches. A verdict is read from at most 262144 indices and 4096 vertices of the draw, kept 3600 frames, and costs one hash lookup a draw after that. Needs `BB_WIND_TWIGS` and `BB_WIND_TWIGS_SMALL` above 0. Read once. Log: once `Wind twigs trees (r89j, ...)`, the first 12 tree-shaped and 6 refused ranges as `Wind twigs trees (r89j) mesh:`, and a counter line every 600 frames. Default `0`: nothing differs from r89i (a static bool, false) | `0` |\n"
    "| `BB_WIND_TWIGS_PICK` | TOOL (a test aid, r89j; goes to the test-tools branch): `x,y;x,y;...` (or `x:y;x:y;...` where a value cannot hold a comma; at most 8 output pixels) names, for each pixel, the G-buffer draw that wrote the final depth there. From frame `BB_WIND_TWIGS_PICK_FRAME` (default 900), 2 frames a pixel, the G-buffer draws only a 3x3 patch around the pixel (the picture of those frames is broken) and every G-buffer draw gets an occlusion query (pool of 4 groups x 4096 queries, host query reset needed, read without waiting); the last draw with samples that writes depth is the winner, up to 3 earlier ones with samples are named. `BB_WIND_TWIGS_PICK_SIZE=WxH` (default `1280x720`) is the picture the pixels are read from. Log: `Wind twigs pick (r89j): pixel x,y (render X,Y): row N of M ...` with vs:ps, stream vertices and stride, opaque or cut-out, skinned, GPU palette or static, sway bit and word, the index range, the scene box over the camera, the tree shape and the twig book's verdict. Default off: one test of a static bool, two of a false member a draw | unset |\n"
    + README_ANCHOR)

EDITS = {
    TWIGS: [(TW_OLD, TW_NEW)],
    CACHE: [(PC_OLD, PC_NEW)],
    RASTH: [(RH_INC_OLD, RH_INC_NEW), (RH_DECL_OLD, RH_DECL_NEW), (RH_MEMBER_OLD, RH_MEMBER_NEW)],
    RAST: [(RC_RANGE_OLD, RC_RANGE_NEW), (RC_NOTE_A_OLD, RC_NOTE_A_NEW), (RC_NOTE_B_OLD, RC_NOTE_B_NEW),
           (RC_QUERY_OLD, RC_QUERY_NEW), (RC_SCISSOR_OLD, RC_SCISSOR_NEW)],
    EFFECTS: [(EF_BLOCK_OLD, EF_BLOCK_NEW), (EF_LOOSE_OLD, EF_LOOSE_NEW), (EF_FRAME_OLD, EF_FRAME_NEW),
              (EF_FUNC_OLD, EF_FUNC_NEW)],
    BUILD: [(BS_OLD, BS_NEW)],
    CMAKE: [(CM_OLD, CM_NEW)],
    README: [(README_ANCHOR, README_NEW)],
}

CHECKS = {
    TWIGS: [("inline bool TreesWanted()", 1), ("&& !TreesWanted()", 1)],
    CACHE: [("BbWindTwigs::TreesWanted() && !SkeletonRead(sel)", 1)],
    RASTH: [("bool WindTreesDraw(", 1), ("void WindTreesPickQuery(", 1), ("void WindTreesPickFrameEnd();", 1),
            ("BbWindTrees::Book trees_book;", 1), ('#include "bbport_wind_trees.h"', 1)],
    RAST: [("BbWindTwigs::TreesWanted()", 1), ("BbWindTrees::PickOn()", 2), ("trees_pick_rect_on", 2),
           ("WindTreesPickQuery(pipeline, regs", 1), ("scissors.push_back(scissor);", 1)],
    EFFECTS: [("bool Rasterizer::WindTreesDraw(", 1), ("void Rasterizer::WindTreesPickQuery(", 1),
              ("void Rasterizer::WindTreesPickFrameEnd(", 1), ("WindTreesPickFrameEnd(); // bbport (r89j", 1),
              ("BbWindTrees::On() || (BbWindCensus::PaletteOn()", 1), ("!WindTreesDraw(positions", 1)],
    BUILD: [("tests/test_wind_trees.cpp", 1)],
    CMAKE: [("add_executable(wind-trees-test", 1)],
    README: [("| `BB_WIND_TWIGS_TREES` |", 1), ("| `BB_WIND_TWIGS_PICK` |", 1), ("| `BB_WIND_TWIGS_CENSUS` |", 1)],
}

# Numbers written twice: the header's constants and the README rows' text.
TREES_ROW = "| `BB_WIND_TWIGS_TREES`"
PICK_ROW = "| `BB_WIND_TWIGS_PICK`"
TIES = [("inline constexpr float SpreadMin = 2.5f", TREES_ROW, "at least 2.5 times as wide"),
        ("inline constexpr float TrunkMax = 0.15f", TREES_ROW, "at most 0.15 of the height"),
        ("inline constexpr float CrownMin = 0.25f, CrownMax = 1.6f", TREES_ROW, "0.25 to 1.6 of the height wide"),
        ("inline constexpr float OpenMin = 0.5f", TREES_ROW, "at least 0.5"),
        ("inline constexpr std::uint32_t ShapeIndexMax = 262144", TREES_ROW, "at most 262144 indices"),
        ("inline constexpr std::size_t ShapeSamples = 4096", TREES_ROW, "4096 vertices"),
        ("inline constexpr std::uint64_t RecheckFrames = 3600", TREES_ROW, "kept 3600 frames"),
        ("inline constexpr unsigned MeshLines = 12", TREES_ROW, "first 12 tree-shaped and 6 refused"),
        ("inline constexpr std::size_t PickMost = 8", PICK_ROW, "at most 8 output pixels"),
        ("inline constexpr std::uint32_t PickPerGroup = 4096", PICK_ROW, "4 groups x 4096 queries"),
        ("inline constexpr std::uint32_t PickGroups = 4", PICK_ROW, "4 groups x 4096 queries"),
        ("inline constexpr std::uint64_t PickFramesPerPoint = 2", PICK_ROW, "2 frames a pixel"),
        ("inline constexpr std::uint64_t PickFrameDefault = 900", PICK_ROW, "(default 900)"),
        ("inline constexpr std::size_t PickUnder = 3", PICK_ROW, "up to 3 earlier ones")]


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
    allnew = NEW_FILES[NEWH] + NEW_FILES[NEWT] + "".join(n for p, es in EDITS.items() if p != README for _, n in es)
    for bad in ("float far ", "float far;", " far =", " far;", ".far,", ".far)", " near =", "float near"):
        if bad in allnew:
            raise SystemExit("the name %r is a macro on some Windows headers" % bad)
    for path, new in NEW_FILES.items():
        if new.count("{") != new.count("}") or new.count("(") != new.count(")"):
            raise SystemExit("%s: braces or parentheses do not balance" % path)
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
        raise SystemExit("%s is not a source tree root (set R89J_ROOT)" % ROOT)
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
            tmp = full + ".r89jtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, content in NEW_FILES.items():  # new files take the line ends of the tree (CRLF)
            full = os.path.join(ROOT, path)
            tmp = full + ".r89jtmp"
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
        tmp = full + ".r89jtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
