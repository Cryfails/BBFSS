# r112i_hang-find-lanterns: FEATURE fix on top of r112h_hang-not-the-hunter (r112g, r112f, r112e, r112d, r112c,
# r112b, r112; r89g is in the tree). Behind r112's own knob BB_WIND_HANG=1 (off by default);
# BB_WIND_HANG_STATIC=0 leaves the static path out again (r112h's behaviour); BB_WIND_HANG_FIND=1 is a
# survey (a test aid: TOOL-grade, its code is one hook line, one report block and one RtShadow accessor, so the
# lead may leave it out of the features branch).
#
# THE EVIDENCE (b44, slot_b44_result.txt, b44_reports.txt): r112h refuses the hunter's gear everywhere and the
# interior is 0, but NOTHING is kept anywhere ('hang none', pushed 0): the lantern that hangs on the bare tree
# of the graveyard was never a candidate. The whole r112 chain looks only at SKINNED draws (Kind::Skinned: a
# bone palette of character size) that a sun shadow pass draws; a hanging lantern, chain or cage is quite
# possibly a plain STATIC mesh (Kind::Other, no palette), or part of a bigger static mesh. And the indoor rule
# was untested ('no field: rule off': BB_WIND_SHELTER was not on in the jobs).
#
# WHAT THIS DOES
#  (1) SURVEY (BB_WIND_HANG_FIND=1, with BB_WIND_HANG=1). Every 600 frames, with the r112h lines: a header and
#      up to 14 lines "Wind sway hang (r112i): A stream .. vs .. ps .. static|SKINNED idx .. verts .. h .. w ..
#      bottom y .. at x .. z .. dist .. m: FREE|held above .. m, support gap .. m, src c pal 0 dyn 0 book ..":
#      the ray traced scene's meshes (RtShadow entries seen in the last 120 frames with a world box: the sun
#      VSM's, else the still check's bounds) of 0.15-2 m height and at most 3 m width within 60 m of the
#      camera that hang (more than 1 m above the lowest box near them and nothing under them: the r112b probe's
#      rule, FREE) or are held at the top by a thin box (a chain or a hook), nearest first, with the shader pair
#      of their capture draw (a map stream -> vs, ps, skinned, palette, index count noted in
#      EffectsCaptureDraw), skinned or static, vertices and triangles, box, distance, the height above the
#      ground, the support under it and the static path's verdict on the stream. This names what the
#      lantern on the tree is (its pair, its size, its box) and whether the scene sees it at all (the header
#      line counts the boxes, those that fit and those that hang). The camera's view cone is not tested
#      (distance only); 'near a lamp' is not tested.
#  (2) STATIC PATH (BB_WIND_HANG=1 and BB_WIND_HANG_STATIC not 0). (a) A motion pipeline of an opaque
#      (no discard) vertex shader with no skeleton gets the sway code too (SwayWanted, vk_pipeline_cache.cpp:
#      the Sway bit of the pipeline key), so a draw of it can carry a hang word. (b) Its draw (Motion block,
#      vk_rasterizer.cpp: Kind::Other, the Sway bit, no discard) calls WindSwayWord(pipeline, palette flag,
#      true): no plant, no tree, no twig candidate; WindHangVerdict's static mode asks
#      WindHangStaticAllowed: the stream (address and bytes) gets ONE verdict (BbWindHangFind::Evaluate, held
#      for 120-3600 frames in the StaticBook): at most 20000 vertices (no building, no big batch), a box in
#      the ray traced scene of 0.15-2 m height and at most 3 m width (no box yet: asked again in 120
#      frames), hanging (Clearance: its bottom over 1 m above the lowest bottom of the boxes within 4 m
#      sideways that are up to 60 m wide, no box top within 0.3 m under it, no thin box standing from under it
#      up through it: a post with a lamp is rigid). Every other static draw costs one map lookup and returns 0.
#      (c) A candidate then goes the skinned things' road with no palette test: hang_book.Note, the GPU
#      judge's window (the world box the vertex shaders keep must not grow; BoxBook), WindHangActorsClear (the
#      hunter, the indoor rule; one bone stands in for the figure rule), r112g's height rule (0.15-4 m, the
#      top as pivot, HangScale) and r112's push: it leans downwind about its top, push only, no swing, the top
#      still. The mesh is taken per stream: a mesh drawn at several places (instanced) has a bigger box than
#      the scene's, grows in the judge or misses the height rule: not taken.
#  (3) The jobs set BB_WIND_SHELTER=1 so that the indoor rule (open wind share at the camera 0.1 or less) is
#      tested; a hanging lantern the camera walks away from is stopped by r117's field (it scales every sway
#      vertex).
#
# Off: BB_WIND_HANG unset: StaticOn() and FindOn() are false (they test BbWindHang::KnobOnce().on first); the
# SwayWanted clause is false (no pipeline gets the Sway bit for it, the sway SPIR-V of every pipeline is as
# before, cached under the same keys); the new Motion-block branch is false (Wanted is false); the hook in
# EffectsCaptureDraw is one test of FindOn(); the reports are inside BbWindHang::KnobOnce().on. With
# BB_WIND_HANG_STATIC=0 and BB_WIND_HANG_FIND unset the only differences from r112h are those tests. No shader
# changes: no host shader, no emitter, no lifter edit (the SPIR-V of each pipeline is identical; with
# BB_WIND_HANG=1 more motion pipelines have the sway code, built as r89's cut-out pipelines are).
#
# Files: engine/gpu/shim/bbport_wind_hang_find.h (new: knobs, Wanted, Box, Clearance, Evaluate, StaticBook,
# BoxSet, Draws, Stats, texts, survey), engine/tests/test_wind_hang_find.cpp (new), vk_rasterizer.h (include,
# members, declarations, default arguments), vk_rasterizer.cpp (one branch of the sway word's expression),
# vk_rasterizer_effects.cpp (WindSwayWord, WindHangVerdict, WindHangActorsClear, three new functions, the
# capture hook, the once-line and the report block), vk_rt_shadow.h/.cpp (HangFindBox, WindHangFindBoxes),
# vk_pipeline_cache.cpp (include, SwayWanted), engine/gpu/CMakeLists.txt and engine/build.sh (the test),
# README.md (three rows).
#
# Cost (estimate, nothing measured): GPU: the sway code is in the vertex shaders of the opaque static motion
# pipelines (with BB_WIND_HANG=1 only): per vertex one read of the draw's sway word and a branch, 0 for every
# draw that is not a candidate; the shader binaries are bigger (a few hundred bytes of SPIR-V each, built at
# first use: pipeline builds take longer once, cached after); a candidate pays r112's hang displacement per
# vertex. CPU: per opaque static draw of a sway pipeline one map lookup (a few tens of ns; thousands of draws a
# frame: tens of microseconds); per new static stream one verdict (a compare, and for a small one a scan of
# the scene's boxes, a few thousand, once per stream); the scene's boxes are read from the RT entries every 60
# frames when a stream asks (a few thousand entries, 56 bytes each). With FIND on, one map insert per capture
# draw. Memory: up to 8192 static verdicts (56 bytes), up to 4096 draws' records (40 bytes), the box set
# (a few hundred KB at most).
#
# Use: python -I -X utf8 r112i_hang-find-lanterns.py check | apply | revert
# Root: R112I_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112i_backup next to
# this script; revert takes out exactly what apply put in (new files removed). Needs r112h applied.
import os, sys

ROOT = os.environ.get("R112I_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112i_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
TH = RV + "vk_rt_shadow.h"
TC = RV + "vk_rt_shadow.cpp"
PC = RV + "vk_pipeline_cache.cpp"
NF = "engine/gpu/shim/bbport_wind_hang_find.h"
NT = "engine/tests/test_wind_hang_find.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
RM = "README.md"

NEW_FILES = {
NF: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112i_hang-find-lanterns): static meshes that hang, and a survey of what hangs. b44 (r112h)
// kept nothing anywhere: the hunter's gear was refused, but the lantern that hangs on the bare tree of
// the graveyard was never a candidate, because the whole r112 chain looks at SKINNED, sun-drawn
// meshes, and a lantern, chain or cage of this game is probably a plain STATIC mesh (no bone palette
// of character size). This file holds the pure parts of the two things r112i adds (the
// Rasterizer code that uses them is in vk_rasterizer_effects.cpp):
//
// (1) THE STATIC PATH (BB_WIND_HANG=1, off with BB_WIND_HANG_STATIC=0). A motion pipeline of an
//     opaque (no discard) vertex shader with no skeleton gets the sway code too (Wanted, read by
//     SwayWanted in vk_pipeline_cache.cpp), so that a draw of it can carry a hang word; the word is 0
//     for every draw that is not a candidate, so nothing moves and the vertex shader only reads it.
//     A draw is a candidate when its position stream (address and bytes; the draw's Kind::Other) is
//     small, hangs and is not part of the ground: Evaluate, once per stream and then held (StaticBook):
//       - at most BB_WIND_HANG_STATIC_VERTS (20000) vertices: no building, no big static batch;
//       - a world box (the ray traced scene's: its entries' sun VSM box or still-check bounds,
//         BoxSet) of BB_WIND_HANG_STATIC_HEIGHT (2 m; from 0.15 m) at most in height and 3 m in width;
//       - hanging: its bottom more than BB_WIND_HANG_STATIC_CLEAR (1 m) above the lowest bottom of
//         the boxes near it (4 m sideways; boxes up to 60 m wide count as ground), with no box top
//         under it within 0.3 m sideways, and no thin box (1 m or less wide) standing from under it
//         up through it (a post with a lamp on it is rigid).
//     A candidate then goes the way of the skinned hanging things: a slot, the GPU judge's window
//     (the world box the vertex shaders keep must not grow), r112h's hunter and indoor rules, r112g's
//     height rule (0.15-4 m) and push scale, r112's push: it leans downwind about its top, push only.
//     Static meshes are not tested for a palette; the one ray traced scene box is read once per window.
// (2) THE SURVEY (BB_WIND_HANG_FIND=1, a test aid: TOOL grade). Every 600 frames: the ray traced scene's
//     boxes of 0.15-2 m that hang (the same Clearance rule, or are held at the top by a thin box)
//     within 60 m of the camera, nearest first, each with its shader pair (vs and ps, as the capture
//     draw had them), skinned or static, bones, index count, vertices, world box, distance, the
//     height above the ground, the support and the static book's verdict, so that a log says what the
//     hanging things of a place are, and what the static path made of them.
// Pure: no Vulkan; tested by tests/test_wind_hang_find.cpp.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>
#include <vector>

#include "bbport_wind_hang.h"

namespace BbWindHangFind {

namespace H = BbWindHang;

inline constexpr float HeightLo = H::MinExtent; ///< m: a mesh lower than this does not hang
inline constexpr float HeightHiDefault = 2.0f, HeightHiMax = H::MaxExtent; ///< m
inline constexpr float WidthHi = 3.0f;          ///< m: the wider of x and z of a candidate's box
inline constexpr float NearGap = 4.0f;          ///< m sideways: a box is near
inline constexpr float GroundWidthMax = 60.0f;  ///< m: wider boxes are no ground reference
inline constexpr float SupportTop = 0.15f;      ///< m: a box top this far over the bottom holds
inline constexpr float SupportGap = 0.3f;       ///< m: nothing within this under the bottom
inline constexpr float HeldGap = 0.3f;          ///< m sideways: a box touches the top
inline constexpr float ThinWidth = 1.0f;        ///< m: a post, a chain, a hook is this thin
inline constexpr float ClearDefault = 1.0f, ClearMax = 20.0f; ///< m above the ground
inline constexpr float ViewMax = 60.0f;         ///< m: the survey looks this far
inline constexpr std::uint32_t VertsDefault = 20000, VertsLow = 64, VertsHigh = 1000000;
inline constexpr std::uint64_t RefreshFrames = 60; ///< the scene's boxes are read this seldom
inline constexpr std::uint64_t KeepCandidate = 3600, HoldBig = 3600, HoldShape = 1800,
                               HoldGround = 1800, HoldNoBox = 120, HoldNoGround = 300;
inline constexpr std::size_t BookMost = 8192, DrawsMost = 4096, ListMost = 14;
inline constexpr std::size_t LineChars = 380;

static_assert(HeightLo > 0.0f && HeightHiDefault <= HeightHiMax && HeightHiDefault > HeightLo);
static_assert(SupportGap > 0.0f && ThinWidth > 0.0f && NearGap > SupportGap);

struct Knobs {
    bool static_on = true; ///< BB_WIND_HANG_STATIC is not 0
    bool find = false;     ///< BB_WIND_HANG_FIND=1
    std::uint32_t verts = VertsDefault;
    float height_hi = HeightHiDefault;
    float clear = ClearDefault;
};

[[nodiscard]] inline Knobs ParseKnobs(const char* stat, const char* find, const char* verts,
                                      const char* height, const char* clear) {
    Knobs k;
    k.static_on = !(stat != nullptr && stat[0] == '0');
    k.find = find != nullptr && find[0] == '1' && find[1] == 0;
    const float v = BbWindSway::ParseNumber(verts, float(VertsDefault));
    k.verts = std::uint32_t(std::clamp(v, float(VertsLow), float(VertsHigh)));
    k.height_hi = std::clamp(BbWindSway::ParseNumber(height, HeightHiDefault), HeightLo, HeightHiMax);
    k.clear = std::clamp(BbWindSway::ParseNumber(clear, ClearDefault), 0.0f, ClearMax);
    return k;
}

/// The knobs, read once.
[[nodiscard]] inline const Knobs& KnobOnce() {
    static const Knobs k =
        ParseKnobs(std::getenv("BB_WIND_HANG_STATIC"), std::getenv("BB_WIND_HANG_FIND"),
                   std::getenv("BB_WIND_HANG_STATIC_VERTS"),
                   std::getenv("BB_WIND_HANG_STATIC_HEIGHT"),
                   std::getenv("BB_WIND_HANG_STATIC_CLEAR"));
    return k;
}

/// The static path is on: BB_WIND_HANG on (it needs the plant sway) and BB_WIND_HANG_STATIC not 0.
[[nodiscard]] inline bool StaticOn() {
    return H::KnobOnce().on && KnobOnce().static_on;
}

/// The survey is on: BB_WIND_HANG on and BB_WIND_HANG_FIND=1.
[[nodiscard]] inline bool FindOn() {
    return H::KnobOnce().on && KnobOnce().find;
}

/// Pure form of Wanted: a pipeline with the Sway bit whose pixel shader (null: none) does not discard.
template <class Stage>
[[nodiscard]] inline bool WantedWith(bool static_on, bool sway_bit, const Stage* fragment) {
    return static_on && sway_bit && !(fragment != nullptr && fragment->has_discard);
}

/// May an opaque static draw of this pipeline carry a hang word (is the pipeline built for it)?
template <class Stage>
[[nodiscard]] inline bool Wanted(bool sway_bit, const Stage* fragment) {
    return WantedWith(StaticOn(), sway_bit, fragment);
}

/// A mesh of the ray traced scene with its world box.
struct Box {
    std::uint64_t stream = 0; ///< its position stream's address (0: none)
    std::uint32_t vertices = 0, triangles = 0;
    std::array<float, 6> box{}; ///< least x, y, z, greatest x, y, z (world, y up)
    char src = '?';             ///< v: the sun VSM's box, s: still bounds of a sun pass capture, c: of
                                ///< a camera pass capture
    bool skinned = false, dynamic = false, palette = false, shadow = false;
};

[[nodiscard]] inline float HeightOf(const std::array<float, 6>& b) {
    return b[4] - b[1];
}

[[nodiscard]] inline float WidthOf(const std::array<float, 6>& b) {
    return std::max(b[3] - b[0], b[5] - b[2]);
}

/// Where a box stands in the scene around it.
struct Ground {
    bool known = false;   ///< boxes near gave a ground to measure from
    bool support = false; ///< a box top lies under the bottom, within SupportGap sideways
    bool stands = false;  ///< a thin box stands from under the bottom up through it (a post)
    bool held = false;    ///< a thin box touches the top (a chain, a hook, a post)
    bool free = false;    ///< hangs: more than `clear` above the ground, nothing under it
    float above = 0.0f;   ///< the bottom over the lowest bottom of the boxes near (m)
    float gap = 0.0f;     ///< the bottom over the highest top under it (m; only with support)
};

/// `r` the box (least x, y, z, greatest x, y, z), `self` its stream (its own boxes do not count: 0 =
/// none), `all` the scene's boxes, `clear` the least height above the ground.
[[nodiscard]] inline Ground Clearance(const std::array<float, 6>& r, std::uint64_t self,
                                      const std::vector<Box>& all, float clear) {
    Ground g;
    float low = 1e30f, top = -1e30f;
    for (const Box& o : all) {
        if (self != 0 && o.stream == self) {
            continue;
        }
        const float gap_x = std::max(o.box[0] - r[3], r[0] - o.box[3]);
        const float gap_z = std::max(o.box[2] - r[5], r[2] - o.box[5]);
        const float o_width = WidthOf(o.box);
        if (gap_x < NearGap && gap_z < NearGap && o_width <= GroundWidthMax) {
            low = std::min(low, o.box[1]);
        }
        if (gap_x < SupportGap && gap_z < SupportGap && o.box[4] <= r[1] + SupportTop) {
            top = std::max(top, o.box[4]);
        }
        if (gap_x < HeldGap && gap_z < HeldGap && o_width <= ThinWidth) {
            if (o.box[1] <= r[4] + SupportTop && o.box[4] > r[4] + SupportTop) {
                g.held = true;
            }
            if (o.box[1] < r[1] - SupportGap && o.box[4] >= r[1] - SupportTop) {
                g.stands = true;
            }
        }
    }
    g.known = low < 1e29f;
    g.above = r[1] - low;
    g.support = top > -1e29f;
    g.gap = r[1] - top;
    g.free = g.known && g.above > clear && !g.stands && (!g.support || g.gap > SupportGap);
    return g;
}

enum class Why : std::uint8_t { Ok, TooBig, NoBox, Shape, NoGround, Grounded };
inline constexpr std::size_t WhyCount = 6;

[[nodiscard]] inline const char* WhyName(Why w) {
    switch (w) {
    case Why::Ok:
        return "candidate";
    case Why::TooBig:
        return "too big";
    case Why::NoBox:
        return "no box";
    case Why::Shape:
        return "size";
    case Why::NoGround:
        return "no ground";
    case Why::Grounded:
        return "grounded";
    }
    return "?";
}

/// What is known of one static stream.
struct Entry {
    std::uint32_t size = 0, verts = 0; ///< bytes bound at its address, vertices in them
    Why why = Why::Ok;
    std::uint64_t until = 0; ///< the verdict stands until this frame
    std::uint64_t seen = 0;  ///< the last frame a draw of it was looked at
    float height = 0.0f, width = 0.0f, above = 0.0f; ///< its box (m) and height over the ground
};

/// The verdict on a new static stream: `verts` its vertex count, `b` its box in the scene (null: none),
/// `all` the scene's boxes, `stream` its address.
[[nodiscard]] inline Entry Evaluate(const Knobs& k, std::uint32_t size, std::uint32_t verts,
                                    std::uint64_t stream, const Box* b, const std::vector<Box>& all,
                                    std::uint64_t frame) {
    Entry e;
    e.size = size;
    e.verts = verts;
    e.seen = frame;
    if (verts > k.verts) {
        e.why = Why::TooBig;
        e.until = frame + HoldBig;
        return e;
    }
    if (b == nullptr) {
        e.why = Why::NoBox;
        e.until = frame + HoldNoBox;
        return e;
    }
    e.height = HeightOf(b->box);
    e.width = WidthOf(b->box);
    if (!std::isfinite(e.height) || !std::isfinite(e.width)) {
        e.why = Why::NoBox;
        e.until = frame + HoldNoBox;
        return e;
    }
    if (e.height < HeightLo || e.height > k.height_hi || e.width > WidthHi) {
        e.why = Why::Shape;
        e.until = frame + HoldShape;
        return e;
    }
    const Ground g = Clearance(b->box, stream, all, k.clear);
    e.above = g.above;
    if (!g.known) {
        e.why = Why::NoGround;
        e.until = frame + HoldNoGround;
        return e;
    }
    if (!g.free) {
        e.why = Why::Grounded;
        e.until = frame + HoldGround;
        return e;
    }
    e.why = Why::Ok;
    e.until = frame + KeepCandidate;
    return e;
}

/// The static streams, by their address. Another size at a known address is another mesh. At BookMost
/// the verdicts that ran out go, then all.
class StaticBook {
public:
    struct Look {
        bool known = false; ///< a verdict stands
        bool pass = false;  ///< and it is a candidate
    };

    std::array<std::uint64_t, WhyCount> by_why{}; ///< verdicts made, by reason

    /// The standing verdict of a stream drawn on `frame` (known false: none, evaluate it).
    [[nodiscard]] Look Peek(std::uint64_t stream, std::uint32_t size, std::uint64_t frame) {
        const auto found = entries.find(stream);
        if (found == entries.end()) {
            return {};
        }
        Entry& e = found->second;
        if ((size != 0 && e.size != 0 && e.size != size) || frame >= e.until) {
            return {};
        }
        e.seen = frame;
        return {true, e.why == Why::Ok};
    }

    void Set(std::uint64_t stream, const Entry& e, std::uint64_t frame) {
        if (entries.size() >= BookMost && entries.find(stream) == entries.end()) {
            std::erase_if(entries, [&](const auto& item) { return item.second.until <= frame; });
            if (entries.size() >= BookMost) {
                entries.clear();
            }
        }
        entries[stream] = e;
        ++by_why[static_cast<std::size_t>(e.why)];
    }

    [[nodiscard]] const Entry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return entries.size();
    }

private:
    std::unordered_map<std::uint64_t, Entry> entries;
};

/// The scene's boxes, read from the ray traced scene every RefreshFrames frames.
class BoxSet {
public:
    bool camera_ok = false;
    std::array<float, 3> camera{};

    [[nodiscard]] bool Fresh(std::uint64_t frame) const {
        return filled && frame >= at && frame < at + RefreshFrames;
    }

    void Begin(std::uint64_t frame) {
        all.clear();
        by_stream.clear();
        at = frame;
        filled = true;
    }

    /// The first box of a stream is the one Find gives.
    void Add(const Box& b) {
        if (b.stream != 0) {
            by_stream.emplace(b.stream, all.size());
        }
        all.push_back(b);
    }

    [[nodiscard]] const Box* Find(std::uint64_t stream) const {
        const auto found = by_stream.find(stream);
        return found == by_stream.end() ? nullptr : &all[found->second];
    }

    [[nodiscard]] const std::vector<Box>& All() const {
        return all;
    }

private:
    std::vector<Box> all;
    std::unordered_map<std::uint64_t, std::size_t> by_stream;
    std::uint64_t at = 0;
    bool filled = false;
};

/// What the capture draws of a stream had (the survey's join with the boxes).
struct Seen {
    std::uint64_t vs = 0, ps = 0, frame = 0;
    std::uint32_t indices = 0;
    bool skinned = false, palette = false, camera = false;
};

class Draws {
public:
    std::uint64_t dropped = 0;

    /// A capture draw of `stream`: the camera pass's draw is kept over a sun shadow pass's.
    void Note(std::uint64_t stream, const Seen& s) {
        if (stream == 0) {
            return;
        }
        const auto found = seen.find(stream);
        if (found == seen.end()) {
            // (review) full: the streams not drawn for 600 frames go (at most once in 60 frames),
            // so that a long run or a new place still names its pairs
            if (seen.size() >= DrawsMost && s.frame >= purged + 60) {
                purged = s.frame;
                std::erase_if(seen, [&](const auto& item) { return item.second.frame + 600 < s.frame; });
            }
            if (seen.size() >= DrawsMost) {
                ++dropped;
                return;
            }
            seen.emplace(stream, s);
            return;
        }
        if (found->second.camera && !s.camera) {
            found->second.frame = s.frame;
            return;
        }
        found->second = s;
    }

    [[nodiscard]] const Seen* Find(std::uint64_t stream) const {
        const auto found = seen.find(stream);
        return found == seen.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return seen.size();
    }

private:
    std::unordered_map<std::uint64_t, Seen> seen;
    std::uint64_t purged = 0;
};

/// Counts of the static path's draws since the last line.
struct Stats {
    std::uint64_t draws = 0;     ///< opaque static draws of sway pipelines asked about
    std::uint64_t no_stream = 0; ///< no position stream found
    std::uint64_t no_keys = 0;   ///< no box keys (BB_WIND_TWIGS off) or no sway words
    std::uint64_t refused = 0;   ///< a standing verdict said no
    std::uint64_t passed = 0;    ///< a standing verdict said candidate
    std::uint64_t judged = 0;    ///< a stream got a new verdict
};

[[nodiscard]] inline std::string Cap(const char* text) {
    std::string out(text);
    if (out.size() > LineChars) {
        out.resize(LineChars - 3);
        out += "...";
    }
    return out;
}

/// The once-line (the static path and the survey).
[[nodiscard]] inline std::string OnceText(const Knobs& k) {
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112i): static meshes hang too (BB_WIND_HANG_STATIC=%d): an "
                  "opaque static draw (no skeleton) of a sway pipeline is a candidate when its "
                  "stream has at most %u vertices (BB_WIND_HANG_STATIC_VERTS) and the ray traced "
                  "scene's world box of it is %.2f-%.1f m tall (BB_WIND_HANG_STATIC_HEIGHT) and at "
                  "most %.0f m wide, its bottom over %.1f m above the lowest box near and nothing "
                  "under it (BB_WIND_HANG_STATIC_CLEAR); then the GPU judge, the hunter and indoor "
                  "rules of r112h and r112g's height rule decide; survey of what hangs "
                  "(BB_WIND_HANG_FIND): %s; lines every %u frames",
                  k.static_on ? 1 : 0, k.verts, double(HeightLo), double(k.height_hi),
                  double(WidthHi), double(k.clear), k.find ? "ON" : "off", BbWindSway::ReportFrames);
    return std::string(buf);
}

/// The static path's line: this interval's counts and the verdicts made so far.
[[nodiscard]] inline std::string StaticLine(const Stats& s, const StaticBook& book, const Knobs& k,
                                            unsigned frames) {
    char buf[1024];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto w = [&](Why why) { return n(book.by_why[static_cast<std::size_t>(why)]); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112i): static draws in %u frames: %llu asked, %llu refused by a "
                  "standing verdict, %llu candidate draws, %llu streams judged, %llu without a "
                  "stream, %llu without box keys; verdicts so far: %llu candidate, %llu over %u "
                  "vertices, %llu no box, %llu not %.2f-%.1f m tall or over %.0f m wide, %llu no "
                  "ground, %llu grounded (clear %.1f m); %zu in the book",
                  frames, n(s.draws), n(s.refused), n(s.passed), n(s.judged), n(s.no_stream),
                  n(s.no_keys), w(Why::Ok), w(Why::TooBig), k.verts, w(Why::NoBox), w(Why::Shape),
                  double(HeightLo), double(k.height_hi), double(WidthHi), w(Why::NoGround),
                  w(Why::Grounded), double(k.clear), book.Size());
    return Cap(buf);
}

/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
/// HeightLo-k.height_hi m that hangs by Clearance or is held at the top by a thin box, within ViewMax
/// m of the camera, free ones first, then nearest first). `frame` for the header.
[[nodiscard]] inline std::vector<std::string> SurveyLines(const Knobs& k, const BoxSet& set,
                                                          const Draws& draws,
                                                          const StaticBook& book,
                                                          std::uint64_t frame) {
    struct Cand {
        const Box* b = nullptr;
        Ground g;
        float height = 0.0f, width = 0.0f, dist = -1.0f;
    };
    std::vector<Cand> list;
    std::size_t with_stream = 0, fit = 0, far_away = 0;
    unsigned free_n = 0, held_n = 0;
    for (const Box& b : set.All()) {
        with_stream += b.stream != 0 ? 1u : 0u;
        const float h = HeightOf(b.box), w = WidthOf(b.box);
        if (!(std::isfinite(h) && std::isfinite(w) && h >= HeightLo && h <= k.height_hi &&
              w <= WidthHi)) {
            continue;
        }
        ++fit;
        Cand c;
        c.b = &b;
        c.height = h;
        c.width = w;
        if (set.camera_ok) {
            const float dx = 0.5f * (b.box[0] + b.box[3]) - set.camera[0];
            const float dy = 0.5f * (b.box[1] + b.box[4]) - set.camera[1];
            const float dz = 0.5f * (b.box[2] + b.box[5]) - set.camera[2];
            c.dist = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (c.dist > ViewMax) {
                ++far_away;
                continue;
            }
        }
        c.g = Clearance(b.box, b.stream, set.All(), k.clear);
        free_n += c.g.free ? 1u : 0u;
        held_n += c.g.held ? 1u : 0u;
        if (c.g.free || c.g.held) {
            list.push_back(c);
        }
    }
    std::sort(list.begin(), list.end(), [](const Cand& a, const Cand& b) {
        if (a.g.free != b.g.free) {
            return a.g.free;
        }
        return a.dist < b.dist;
    });
    std::vector<std::string> out;
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112i): survey at frame %llu: %zu scene boxes (%zu with a "
                  "stream), %zu draws noted (%llu dropped); of %.2f-%.1f m x width %.0f m: %zu fit, "
                  "%zu of them over %.0f m away, %u hang free (over %.1f m, nothing under), %u "
                  "held at the top by a thin box; camera %s",
                  static_cast<unsigned long long>(frame), set.All().size(), with_stream, draws.Size(),
                  static_cast<unsigned long long>(draws.dropped), double(HeightLo),
                  double(k.height_hi), double(WidthHi), fit, far_away, double(ViewMax), free_n,
                  double(k.clear), held_n,
                  set.camera_ok ? "read" : "unread: no distance limit");
    out.push_back(Cap(buf));
    for (std::size_t i = 0; i < list.size() && i < ListMost; ++i) {
        const Cand& c = list[i];
        const Seen* d = draws.Find(c.b->stream);
        const Entry* e = book.Find(c.b->stream);
        char vs[16], ps[16], dist[16], above[16], gap[16], idx[16];
        if (d != nullptr) {
            std::snprintf(vs, sizeof(vs), "%08x", static_cast<unsigned>(d->vs & 0xffffffffull));
            std::snprintf(ps, sizeof(ps), "%08x", static_cast<unsigned>(d->ps & 0xffffffffull));
            std::snprintf(idx, sizeof(idx), "%u", d->indices);
        } else {
            std::snprintf(vs, sizeof(vs), "n/a");
            std::snprintf(ps, sizeof(ps), "n/a");
            std::snprintf(idx, sizeof(idx), "n/a");
        }
        if (c.dist >= 0.0f) {
            std::snprintf(dist, sizeof(dist), "%.1f", double(c.dist));
        } else {
            std::snprintf(dist, sizeof(dist), "n/a");
        }
        if (c.g.known) {
            std::snprintf(above, sizeof(above), "%.2f", double(c.g.above));
        } else {
            std::snprintf(above, sizeof(above), "n/a");
        }
        if (c.g.support) {
            std::snprintf(gap, sizeof(gap), "%.2f", double(c.g.gap));
        } else {
            std::snprintf(gap, sizeof(gap), "none");
        }
        const bool skinned = c.b->skinned || (d != nullptr && d->skinned);
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112i): %c stream %08llx vs %s ps %s %s idx %s verts %u tris "
                      "%u h %.2f w %.2f bottom y %.2f at x %.1f z %.1f dist %s m: %s%s above %s m, "
                      "support gap %s m, src %c pal %d dyn %d book %s",
                      char('A' + int(i)),
                      static_cast<unsigned long long>(c.b->stream & 0xffffffffull), vs, ps,
                      skinned ? "SKINNED" : "static", idx, c.b->vertices, c.b->triangles,
                      double(c.height), double(c.width), double(c.b->box[1]),
                      double(0.5f * (c.b->box[0] + c.b->box[3])),
                      double(0.5f * (c.b->box[2] + c.b->box[5])), dist, c.g.free ? "FREE" : "held",
                      c.g.stands ? " (post)" : "", above, gap, c.b->src, c.b->palette ? 1 : 0,
                      c.b->dynamic ? 1 : 0, e != nullptr ? WhyName(e->why) : "-");
        out.push_back(Cap(buf));
    }
    return out;
}

} // namespace BbWindHangFind
''',
NT: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112i_hang-find-lanterns): static meshes that hang (gpu/shim/bbport_wind_hang_find.h): the
// knobs, the pipeline test, the ground rule (Clearance), the verdict on a stream (Evaluate), the book,
// the box set, the draws' join and the survey's lines. The twin in Python (r112i_twin.py) holds the
// same scenes.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_hang_find.h"

namespace F = BbWindHangFind;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

struct Stage {
    bool has_discard = false;
};

F::Box MakeBox(std::uint64_t stream, float x0, float y0, float z0, float x1, float y1, float z1) {
    F::Box b;
    b.stream = stream;
    b.box = {x0, y0, z0, x1, y1, z1};
    b.src = 'c';
    b.vertices = 100;
    b.triangles = 150;
    return b;
}

// a 40 m square of ground (bottom -10, top -9.5)
F::Box Ground() {
    return MakeBox(1, -20.0f, -10.0f, -20.0f, 20.0f, -9.5f, 20.0f);
}

bool Has(const std::string& text, const char* part) {
    return text.find(part) != std::string::npos;
}
} // namespace

int main() {
    // the knobs: defaults, off, ranges, junk
    const F::Knobs d = F::ParseKnobs(nullptr, nullptr, nullptr, nullptr, nullptr);
    Expect(d.static_on && !d.find && d.verts == 20000 && d.height_hi == 2.0f && d.clear == 1.0f,
           "knobs: defaults");
    const F::Knobs off = F::ParseKnobs("0", "1", nullptr, nullptr, nullptr);
    Expect(!off.static_on && off.find, "knobs: STATIC=0 is off, FIND=1 is on");
    const F::Knobs odd = F::ParseKnobs("yes", "11", nullptr, nullptr, nullptr);
    Expect(odd.static_on && !odd.find, "knobs: other text is on for STATIC, FIND is exactly 1");
    const F::Knobs wide = F::ParseKnobs("1", nullptr, "9999999", "50", "900");
    Expect(wide.verts == F::VertsHigh && wide.height_hi == F::HeightHiMax && wide.clear == F::ClearMax,
           "knobs: held to their ranges");
    const F::Knobs low = F::ParseKnobs("1", nullptr, "1", "0", "-3");
    Expect(low.verts == F::VertsLow && low.height_hi == F::HeightLo && low.clear == 0.0f,
           "knobs: held at the low end");
    const F::Knobs junk = F::ParseKnobs("1", nullptr, "abc", "nan", "x");
    Expect(junk.verts == 20000 && junk.height_hi == 2.0f && junk.clear == 1.0f,
           "knobs: text that is no number gives the defaults");

    // the pipeline test
    const Stage solid{false}, cut{true};
    Expect(F::WantedWith(true, true, &solid), "wanted: opaque with the Sway bit");
    Expect(F::WantedWith(true, true, static_cast<const Stage*>(nullptr)), "wanted: no pixel shader");
    Expect(!F::WantedWith(true, true, &cut), "wanted: a cut-out is the twigs'");
    Expect(!F::WantedWith(true, false, &solid), "wanted: no Sway bit");
    Expect(!F::WantedWith(false, true, &solid), "wanted: the path is off");

    // the ground rule
    const F::Knobs k = d;
    std::vector<F::Box> scene{Ground()};
    const F::Box lantern = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -5.5f, 0.4f);
    F::Ground g = F::Clearance(lantern.box, lantern.stream, scene, k.clear);
    Expect(g.known && g.free && std::fabs(g.above - 4.0f) < 1e-4f, "ground: a lantern 4 m up hangs");
    Expect(g.support && std::fabs(g.gap - 3.5f) < 1e-4f && !g.stands && !g.held,
           "ground: the ground under it is far, nothing touches it");
    const F::Box low_one = MakeBox(7, 0.0f, -9.9f, 0.0f, 0.4f, -9.4f, 0.4f);
    g = F::Clearance(low_one.box, 7, scene, k.clear);
    Expect(g.known && !g.free && std::fabs(g.above - 0.1f) < 1e-4f, "ground: 0.1 m up is no hanging");
    const F::Box at_clear = MakeBox(7, 0.0f, -9.0f, 0.0f, 0.4f, -8.5f, 0.4f);
    g = F::Clearance(at_clear.box, 7, scene, k.clear);
    Expect(!g.free, "ground: exactly the clearance does not hang");
    scene.push_back(MakeBox(2, 0.1f, -10.0f, 0.1f, 0.3f, -4.0f, 0.3f)); // a post through it
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.stands && g.held && !g.free, "ground: a thin post through it holds it rigid");
    scene.pop_back();
    scene.push_back(MakeBox(3, -5.0f, -10.0f, -5.0f, 5.0f, 10.0f, 5.0f)); // a tree, 10 m wide
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.free && !g.stands && !g.held, "ground: a lantern in a tree hangs (a wide box is no post)");
    scene.pop_back();
    scene.push_back(MakeBox(4, 0.0f, -6.5f, 0.0f, 0.4f, -6.1f, 0.4f)); // a shelf 0.1 m under it
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.support && std::fabs(g.gap - 0.1f) < 1e-4f && !g.free, "ground: a box under it holds it");
    scene.pop_back();
    scene.push_back(MakeBox(7, 0.0f, -10.0f, 0.0f, 0.4f, 5.0f, 0.4f)); // its own stream's box
    g = F::Clearance(lantern.box, 7, scene, k.clear);
    Expect(g.free, "ground: the boxes of its own stream do not count");
    scene.pop_back();
    const std::vector<F::Box> none;
    g = F::Clearance(lantern.box, 7, none, k.clear);
    Expect(!g.known && !g.free, "ground: no box near gives no ground");
    const std::vector<F::Box> far_scene{MakeBox(5, 30.0f, -10.0f, 30.0f, 40.0f, -9.5f, 40.0f)};
    g = F::Clearance(lantern.box, 7, far_scene, k.clear);
    Expect(!g.known, "ground: a box 30 m away is no ground");
    const std::vector<F::Box> wide_scene{MakeBox(6, -50.0f, -10.0f, -50.0f, 50.0f, -9.5f, 50.0f)};
    g = F::Clearance(lantern.box, 7, wide_scene, k.clear);
    Expect(!g.known, "ground: a box over 60 m wide is no reference");

    // the verdict on a stream
    const std::vector<F::Box> ground_only{Ground()};
    F::Entry e = F::Evaluate(k, 4096, 30000, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::TooBig && e.until == 100 + F::HoldBig, "evaluate: too many vertices");
    e = F::Evaluate(k, 4096, 500, 7, nullptr, ground_only, 100);
    Expect(e.why == F::Why::NoBox && e.until == 100 + F::HoldNoBox, "evaluate: no box");
    const F::Box tall = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -3.0f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &tall, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 3 m tall is no lantern");
    const F::Box flat = MakeBox(7, 0.0f, -6.0f, 0.0f, 0.4f, -5.95f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &flat, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 0.05 m tall is not either");
    const F::Box broad = MakeBox(7, 0.0f, -6.0f, 0.0f, 4.0f, -5.5f, 0.4f);
    e = F::Evaluate(k, 4096, 500, 7, &broad, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: 4 m wide is a roof, not a lantern");
    e = F::Evaluate(k, 4096, 500, 7, &lantern, none, 100);
    Expect(e.why == F::Why::NoGround && e.until == 100 + F::HoldNoGround, "evaluate: no ground");
    e = F::Evaluate(k, 4096, 500, 7, &low_one, ground_only, 100);
    Expect(e.why == F::Why::Grounded && e.until == 100 + F::HoldGround, "evaluate: on the ground");
    e = F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::Ok && e.until == 100 + F::KeepCandidate && e.verts == 500 &&
               e.size == 4096 && std::fabs(e.height - 0.5f) < 1e-4f && std::fabs(e.above - 4.0f) < 1e-4f,
           "evaluate: a lantern 4 m up is a candidate");
    F::Knobs strict = k;
    strict.height_hi = 0.4f;
    e = F::Evaluate(strict, 4096, 500, 7, &lantern, ground_only, 100);
    Expect(e.why == F::Why::Shape, "evaluate: the height limit is a knob");

    // the book
    F::StaticBook book;
    Expect(!book.Peek(7, 4096, 100).known, "book: an unknown stream");
    book.Set(7, F::Evaluate(k, 4096, 500, 7, &lantern, ground_only, 100), 100);
    F::StaticBook::Look look = book.Peek(7, 4096, 150);
    Expect(look.known && look.pass, "book: a candidate stands");
    Expect(!book.Peek(7, 8192, 150).known, "book: another size at the address is another mesh");
    Expect(book.Peek(7, 0, 150).known, "book: size 0 is not known: the verdict stands");
    Expect(!book.Peek(7, 4096, 100 + F::KeepCandidate).known, "book: the verdict runs out");
    book.Set(8, F::Evaluate(k, 4096, 500, 8, &low_one, ground_only, 100), 100);
    look = book.Peek(8, 4096, 101);
    Expect(look.known && !look.pass, "book: a refusal stands");
    Expect(book.by_why[static_cast<std::size_t>(F::Why::Ok)] == 1 &&
               book.by_why[static_cast<std::size_t>(F::Why::Grounded)] == 1 && book.Size() == 2,
           "book: the verdicts are counted");
    F::StaticBook full;
    for (std::uint64_t s = 1; s <= F::BookMost; ++s) {
        F::Entry shortlived;
        shortlived.until = 10;
        full.Set(s, shortlived, 5);
    }
    Expect(full.Size() == F::BookMost, "book: filled to BookMost");
    F::Entry later;
    later.until = 1000;
    full.Set(F::BookMost + 100, later, 20); // the old ones have run out: they go
    Expect(full.Size() == 1, "book: expired verdicts go first");
    F::StaticBook crowded;
    for (std::uint64_t s = 1; s <= F::BookMost; ++s) {
        F::Entry standing;
        standing.until = 1000;
        crowded.Set(s, standing, 5);
    }
    crowded.Set(F::BookMost + 100, later, 20); // none has run out at frame 20: all go
    Expect(crowded.Size() == 1, "book: a full book of standing verdicts is cleared");

    // the box set
    F::BoxSet set;
    Expect(!set.Fresh(5), "boxes: none read");
    set.Begin(10);
    set.Add(MakeBox(7, 0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 1.0f));
    set.Add(MakeBox(7, 5.0f, 0.0f, 0.0f, 6.0f, 1.0f, 1.0f));
    set.Add(MakeBox(0, 9.0f, 0.0f, 0.0f, 9.5f, 1.0f, 1.0f));
    Expect(set.Fresh(10) && set.Fresh(69) && !set.Fresh(70) && !set.Fresh(9), "boxes: fresh for 60 frames");
    Expect(set.All().size() == 3 && set.Find(7) != nullptr && set.Find(7)->box[0] == 0.0f &&
               set.Find(0) == nullptr && set.Find(9) == nullptr,
           "boxes: the first box of a stream is found, stream 0 is not");
    set.Begin(100);
    Expect(set.All().empty() && set.Find(7) == nullptr && set.Fresh(100), "boxes: begun again");

    // the draws
    F::Draws draws;
    F::Seen cam;
    cam.vs = 0xabc;
    cam.ps = 0xdef;
    cam.camera = true;
    cam.indices = 300;
    cam.frame = 5;
    F::Seen sun = cam;
    sun.vs = 0x111;
    sun.camera = false;
    sun.frame = 6;
    draws.Note(7, sun);
    Expect(draws.Find(7) != nullptr && draws.Find(7)->vs == 0x111, "draws: a sun pass draw is kept");
    draws.Note(7, cam);
    Expect(draws.Find(7)->vs == 0xabc, "draws: the camera pass's replaces it");
    draws.Note(7, sun);
    Expect(draws.Find(7)->vs == 0xabc && draws.Find(7)->frame == 6, "draws: and stays");
    draws.Note(0, cam);
    Expect(draws.Size() == 1, "draws: stream 0 is not noted");

    // the survey
    F::BoxSet world;
    world.Begin(0);
    world.Add(Ground());
    F::Box hung = lantern;
    hung.vertices = 777;
    hung.triangles = 900;
    world.Add(hung);
    world.Add(MakeBox(9, 6.0f, -10.0f, 6.0f, 6.4f, -7.0f, 6.4f)); // a 3 m post: no fit
    world.Add(MakeBox(8, 0.0f, -9.9f, 0.0f, 0.4f, -9.4f, 0.4f)); // on the ground: fits, not hanging
    world.camera_ok = true;
    world.camera = {0.0f, -6.0f, 5.0f};
    F::Draws seen_draws;
    seen_draws.Note(7, cam);
    F::StaticBook shown;
    shown.Set(7, F::Evaluate(k, 4096, 777, 7, &hung, world.All(), 0), 0);
    const std::vector<std::string> lines = F::SurveyLines(k, world, seen_draws, shown, 1200);
    Expect(lines.size() == 2, "survey: a header and the one that hangs");
    if (lines.size() == 2) {
        Expect(Has(lines[0], "survey at frame 1200") && Has(lines[0], "4 scene boxes") &&
                   Has(lines[0], "2 fit") && Has(lines[0], "1 hang free") &&
                   Has(lines[0], "camera read"),
               "survey: the header counts");
        Expect(Has(lines[1], "A stream 00000007") && Has(lines[1], "vs 00000abc") &&
                   Has(lines[1], "ps 00000def") && Has(lines[1], "static") &&
                   Has(lines[1], "idx 300") && Has(lines[1], "verts 777") &&
                   Has(lines[1], "FREE") && Has(lines[1], "above 4.00") &&
                   Has(lines[1], "book candidate"),
               "survey: the candidate's line");
        Expect(lines[0].size() <= F::LineChars && lines[1].size() <= F::LineChars, "survey: lines are capped");
    }
    world.camera = {500.0f, -6.0f, 500.0f};
    const std::vector<std::string> far_lines = F::SurveyLines(k, world, seen_draws, shown, 1200);
    Expect(far_lines.size() == 1 && Has(far_lines[0], "of them over 60 m away"),
           "survey: a candidate far from the camera is only counted");
    world.camera_ok = false;
    const std::vector<std::string> no_camera = F::SurveyLines(k, world, F::Draws{}, F::StaticBook{}, 1);
    Expect(no_camera.size() == 2 && Has(no_camera[0], "camera unread") && Has(no_camera[1], "vs n/a") &&
               Has(no_camera[1], "book -") && Has(no_camera[1], "dist n/a"),
           "survey: without the camera or the draws it still lists, with n/a");
    F::BoxSet many;
    many.Begin(0);
    many.Add(Ground());
    for (std::uint64_t i = 0; i < 40; ++i) {
        many.Add(MakeBox(100 + i, float(i) * 0.1f, -6.0f, 0.0f, float(i) * 0.1f + 0.2f, -5.5f, 0.2f));
    }
    const std::vector<std::string> capped = F::SurveyLines(k, many, F::Draws{}, F::StaticBook{}, 1);
    Expect(capped.size() == 1 + F::ListMost, "survey: at most ListMost candidate lines");

    // the once-line and the static line
    F::Stats stats;
    stats.draws = 12;
    stats.refused = 7;
    stats.passed = 3;
    stats.judged = 2;
    const std::string line = F::StaticLine(stats, book, k, 600);
    Expect(Has(line, "static draws in 600 frames: 12 asked, 7 refused") && Has(line, "3 candidate draws") &&
               Has(line, "1 candidate") && Has(line, "1 grounded") && Has(line, "2 in the book"),
           "static line: counts");
    const std::string once = F::OnceText(k);
    Expect(Has(once, "BB_WIND_HANG_STATIC=1") && Has(once, "20000 vertices") && Has(once, "survey") &&
               Has(once, "off"),
           "once line");

    if (failures == 0) {
        std::printf("wind hang find: all passed\n");
        return 0;
    }
    std::printf("wind hang find: %d failed\n", failures);
    return 1;
}
''',
}

# ---- vk_rasterizer.h -------------------------------------------------------------------------------
H1 = r"""#include "bbport_wind_hang_actors.h" // bbport (r112h_hang-not-the-hunter)
"""
H1N = r"""#include "bbport_wind_hang_find.h" // bbport (r112i_hang-find-lanterns)
"""
H2 = r"""    u32 WindSwayWord(const GraphicsPipeline* pipeline, int small_palette = -1);
"""
H2N = r"""    /// bbport (r112i_hang-find-lanterns): hang_static: an opaque static draw (small_palette 0 or 1, its
    /// palette flag) that may hang (BB_WIND_HANG_STATIC): no plant, no tree, no twig candidate
    u32 WindSwayWord(const GraphicsPipeline* pipeline, int small_palette = -1,
                     bool hang_static = false);
"""
H3 = r"""    bool WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size);
"""
H3N = r"""    /// bbport (r112i_hang-find-lanterns): hang_static and stride: an opaque static draw's stream, judged
    /// by the ray traced scene's boxes (WindHangStaticAllowed) and the GPU's keys, with no palette
    bool WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions, u32 positions_size,
                         bool hang_static = false, u32 stride = 0);
"""
H4 = r"""    bool WindHangActorsClear(u64 positions, u64 frame);
"""
H4N = r"""    bool WindHangActorsClear(u64 positions, u64 frame, bool hang_static = false);
    /// bbport (r112i_hang-find-lanterns): an opaque static draw's stream: may it hang (BB_WIND_HANG_STATIC:
    /// small, a box of 0.15-2 m in the ray traced scene, hanging, not the ground)? The scene's boxes are
    /// read every RefreshFrames frames for the verdicts; the survey (BB_WIND_HANG_FIND) every 600 frames
    bool WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame);
    void WindHangFindRefresh(u64 frame);
    void WindHangFindReport();
"""
H5 = r"""    BbWindHangActors::Book hang_actors;
"""
H5N = r"""    /// bbport (r112i_hang-find-lanterns): the static streams' verdicts, the ray traced scene's boxes they
    /// are measured against, the capture draws' shaders (the survey) and the counts
    BbWindHangFind::StaticBook hang_static_book;
    BbWindHangFind::BoxSet hang_find_boxes;
    BbWindHangFind::Draws hang_find_draws;
    BbWindHangFind::Stats hang_find_stats;
"""

# ---- vk_rasterizer.cpp -----------------------------------------------------------------------------
C1 = r"""                ? WindSwayWord(pipeline)
"""
C1N = r"""                // bbport (r112i_hang-find-lanterns): an opaque static draw of a sway pipeline may hang
                : (r34_kind == Motion::Kind::Other &&
                   BbWindHangFind::Wanted((pipeline->GetGraphicsKey().motion_vectors &
                                           Shader::MotionVectors::Sway) != 0,
                                          pipeline->GetStages()[u32(Shader::SwStage::Fragment)]))
                    ? WindSwayWord(pipeline, palette != 0 ? 1 : 0, true)
"""

# ---- vk_rasterizer_effects.cpp ---------------------------------------------------------------------
E1 = r"""u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline, int small_palette) {
"""
E1N = r"""u32 Rasterizer::WindSwayWord(const GraphicsPipeline* pipeline, int small_palette,
                             bool hang_static) {
"""
E2 = r"""    const bool tree = !plant && (small_palette >= 0
"""
E2N = r"""    const bool tree = !plant && !hang_static && (small_palette >= 0 // (r112i: a static hanging mesh)
"""
E3 = r"""    bool hang = !plant && !tree && small_palette < 0 && // (r89e: never a static cut-out)
                WindHangVerdict(pipeline, positions, positions_size);
"""
E3N = r"""    bool hang = !plant && !tree && (small_palette < 0 || hang_static) && // (r89e: no static cut-out)
                WindHangVerdict(pipeline, positions, positions_size, hang_static, positions_stride);
"""
E4 = r"""            if (!WindHangActorsClear(positions, frame)) { // bbport (r112h_hang-not-the-hunter)
"""
E4N = r"""            if (!WindHangActorsClear(positions, frame, hang_static)) { // bbport (r112h, r112i)
"""
E5 = r"""bool Rasterizer::WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions,
                                 u32 positions_size) {
"""
E5N = r"""bool Rasterizer::WindHangVerdict(const GraphicsPipeline* pipeline, u64 positions,
                                 u32 positions_size, bool hang_static, u32 stride) {
"""
E6 = r"""    if (BbWindHangProbe::On()) { // bbport (r112b_hang-probe, TOOL): every skinned sway draw
"""
E6N = r"""    if (BbWindHangProbe::On() && !hang_static) { // bbport (r112b_hang-probe, TOOL): every skinned draw
"""
E7 = r"""    if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++hang_stats.no_sun;
        return false;
    }
"""
E7N = r"""    if (hang_static) { // bbport (r112i_hang-find-lanterns): an opaque static mesh: its box, no sun pass
        if (!BbWindHangStill::BoxAvailable() || object_motion->SwayWords() == nullptr) {
            ++hang_find_stats.no_keys; // only the GPU's keys can judge a mesh with no palette
            return false;
        }
        if (!WindHangStaticAllowed(positions, positions_size, stride, object_motion->Frame())) {
            return false;
        }
    } else if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++hang_stats.no_sun;
        return false;
    }
"""
E8 = r"""    const BbWindHangStill::Result content =
        hang_still.Judge(positions, palette_size, palette, why, in_place, frame, forced);
"""
E8N = r"""    const BbWindHangStill::Result content =
        hang_static ? BbWindHangStill::Result::Same // (r112i: no palette: the GPU's keys judge)
                    : hang_still.Judge(positions, palette_size, palette, why, in_place, frame, forced);
"""
E9 = r"""                     BbWindHangStill::GpuJudgeable(hang_still.Find(positions), content);
"""
E9N = r"""                     (hang_static ||
                      BbWindHangStill::GpuJudgeable(hang_still.Find(positions), content));
"""
E10 = r"""bool Rasterizer::WindHangActorsClear(u64 positions, u64 frame) {
"""
E10N = r"""bool Rasterizer::WindHangActorsClear(u64 positions, u64 frame, bool hang_static) {
"""
E11 = r"""    if (!knobs.on) {
        return true;
    }
    const BbWindHangStill::BoxEntry* const box = hang_box.Find(positions);
"""
E11N = r"""    if (!knobs.on) {
        return !hang_static; // bbport (r112i): a static mesh hangs only under the hunter and indoor rules
    }
    const BbWindHangStill::BoxEntry* const box = hang_box.Find(positions);
"""
E12 = r"""    const A::Why why = A::Judge(knobs, box, bones, hunter, open, have_field, &side);
"""
E12N = r"""    // bbport (r112i): a static mesh has no palette: one bone stands in for the figure rule
    const A::Why why =
        A::Judge(knobs, box, hang_static ? 1u : bones, hunter, open, have_field, &side);
"""
E13 = r"""// bbport (r112b_hang-probe, TOOL): the first bone palette (stride 16, Skeleton size: the buffer
"""
E13N = r"""// bbport (r112i_hang-find-lanterns): the ray traced scene's world boxes, read from its entries (the sun VSM's
// box or the still check's bounds, RtShadow::WindHangFindBoxes) when the set is older than RefreshFrames
// frames, for the static hanging things' verdicts and the survey. On the thread recording draws.
void Rasterizer::WindHangFindRefresh(u64 frame) {
    if (hang_find_boxes.Fresh(frame)) {
        return;
    }
    std::vector<RtShadow::HangFindBox> boxes;
    std::array<float, 3> camera{};
    bool camera_ok = false;
    rt_shadow->WindHangFindBoxes(boxes, camera, camera_ok);
    hang_find_boxes.Begin(frame);
    for (const RtShadow::HangFindBox& source : boxes) {
        BbWindHangFind::Box b;
        b.stream = source.stream;
        b.vertices = source.vertices;
        b.triangles = source.triangles;
        b.box = source.box;
        b.src = source.src;
        b.skinned = source.skinned;
        b.dynamic = source.dynamic;
        b.palette = source.palette;
        b.shadow = source.shadow;
        hang_find_boxes.Add(b);
    }
    hang_find_boxes.camera = camera;
    hang_find_boxes.camera_ok = camera_ok;
}

// bbport (r112i_hang-find-lanterns): an opaque static draw (Kind::Other, a pipeline with the Sway bit, no
// discard) of the stream at `positions` (`positions_size` bytes at `stride`): may it hang? A stream with a
// standing verdict (BbWindHangFind::StaticBook) costs one lookup; a new one gets its verdict from its
// vertex count and its box in the ray traced scene (Evaluate), held for 120-3600 frames. True: a
// candidate: the caller goes on to the GPU judge. On the thread recording draws.
bool Rasterizer::WindHangStaticAllowed(u64 positions, u32 positions_size, u32 stride, u64 frame) {
    BbWindHangFind::Stats& stats = hang_find_stats;
    ++stats.draws;
    if (positions == 0 || positions_size == 0 || stride == 0) {
        ++stats.no_stream;
        return false;
    }
    const BbWindHangFind::StaticBook::Look look =
        hang_static_book.Peek(positions, positions_size, frame);
    if (look.known) {
        if (look.pass) {
            ++stats.passed;
        } else {
            ++stats.refused;
        }
        return look.pass;
    }
    WindHangFindRefresh(frame);
    const BbWindHangFind::Entry verdict = BbWindHangFind::Evaluate(
        BbWindHangFind::KnobOnce(), positions_size, positions_size / stride, positions,
        hang_find_boxes.Find(positions), hang_find_boxes.All(), frame);
    hang_static_book.Set(positions, verdict, frame);
    ++stats.judged;
    return verdict.why == BbWindHangFind::Why::Ok;
}

// bbport (r112i_hang-find-lanterns, TOOL grade; BB_WIND_HANG_FIND=1): the survey's lines (the header and the
// meshes that hang), every 600 frames with r112h's. On the thread recording draws.
void Rasterizer::WindHangFindReport() {
    const u64 frame = object_motion->Frame();
    WindHangFindRefresh(frame);
    for (const std::string& line : BbWindHangFind::SurveyLines(BbWindHangFind::KnobOnce(),
                                                                hang_find_boxes, hang_find_draws,
                                                                hang_static_book, frame)) {
        BbReport::Printf("%s\n", line.c_str());
    }
}

"""
E14 = r"""            BbReport::Printf("%s\n%s\n", first_line.c_str(), second_line.c_str());
        }
"""
E14N = r"""        if (BbWindHangFind::StaticOn()) { // bbport (r112i_hang-find-lanterns): the static path's line
            const std::string static_line = BbWindHangFind::StaticLine(
                hang_find_stats, hang_static_book, BbWindHangFind::KnobOnce(), BbWindSway::ReportFrames);
            BbReport::Printf("%s\n", static_line.c_str());
            hang_find_stats = {};
        }
        if (BbWindHangFind::FindOn()) { // (r112i) the survey: what hangs, with its shaders
            WindHangFindReport();
        }
"""
E15 = r"""            BbReport::Printf("Wind sway hang (r112h): OFF (BB_WIND_HANG_ACTORS=0): as r112g\n");
        }
    }
"""
E15N = r"""    // bbport (r112i_hang-find-lanterns): its line once (BB_WIND_HANG on)
    static bool hang_find_said = false;
    if (!hang_find_said && BbWindHang::KnobOnce().on) {
        hang_find_said = true;
        BbReport::Printf("%s\n", BbWindHangFind::OnceText(BbWindHangFind::KnobOnce()).c_str());
    }
"""
E16 = r"""    if (r19_palette) { // bbport (r19_draw-cost)
        draw.palette = r19_motion.palette;
        ++r19_stats.motion_palettes;
    }
"""
E16N = r"""    if (BbWindHangFind::FindOn()) { // bbport (r112i_hang-find-lanterns): the survey's shader pairs
        BbWindHangFind::Seen noted;
        noted.vs = vs.pgm_hash;
        noted.ps = ps ? ps->pgm_hash : 0;
        noted.frame = object_motion->Frame();
        noted.indices = regs.num_indices;
        noted.skinned = draw.skinned;
        noted.palette = draw.palette != 0;
        noted.camera = draw.camera_pass;
        hang_find_draws.Note(draw.positions, noted);
    }
"""

# ---- vk_rt_shadow.h / .cpp -------------------------------------------------------------------------
T1 = r"""    bool wind_probe_done = false;
"""
T1N = r"""    // bbport (r112i_hang-find-lanterns): the world boxes of the entries a draw reached in the last 120
    // frames (the sun VSM's, else the still check's bounds; entries with none are left out), whatever
    // they are: the static hanging things are judged against them and the survey lists them; and the
    // camera's world position
    struct HangFindBox {
        u64 stream = 0;
        u32 vertices = 0, triangles = 0;
        std::array<float, 6> box{};
        char src = '?';
        bool skinned = false, dynamic = false, palette = false, shadow = false;
    };
    void WindHangFindBoxes(std::vector<HangFindBox>& out, std::array<float, 3>& camera,
                           bool& camera_ok) const;
"""
T2 = r"""bool RtShadow::RayTracing() const {
"""
T2N = r"""// bbport (r112i_hang-find-lanterns): see the declaration. The boxes and sources of WindHangProbeReport
// (the sun VSM's box, else the still check's bounds of the sun pass's capture, else of the camera pass's),
// for every entry seen in the last 120 frames that is not gone.
void RtShadow::WindHangFindBoxes(std::vector<HangFindBox>& out, std::array<float, 3>& camera,
                                 bool& camera_ok) const {
    out.clear();
    out.reserve(entries.size());
    for (const auto& item : entries) {
        const Entry* e = item.second.get();
        if (e == nullptr || e->gone || e->vertices == 0 || e->seen_frame + 120 < frame) {
            continue;
        }
        HangFindBox r;
        if (e->has_box) {
            r.box = e->box;
            r.src = 'v';
        } else if (e->still_has_ref[1]) {
            r.box = e->still_ref[1];
            r.src = 's';
        } else if (e->still_has_ref[0]) {
            r.box = e->still_ref[0];
            r.src = 'c';
        } else {
            continue;
        }
        if (!(r.box[0] <= r.box[3] && r.box[1] <= r.box[4] && r.box[2] <= r.box[5]) ||
            !std::isfinite(r.box[0] + r.box[1] + r.box[2] + r.box[3] + r.box[4] + r.box[5])) {
            continue;
        }
        r.stream = e->stream;
        r.vertices = e->vertices;
        r.triangles = e->triangles;
        r.skinned = e->skinned;
        r.dynamic = e->dynamic;
        r.palette = e->palette != 0;
        r.shadow = e->shadow;
        out.push_back(r);
    }
    const auto matrices = camera_motion.CameraMatrices();
    camera = {matrices.inv_view[3], matrices.inv_view[7], matrices.inv_view[11]};
    camera_ok = std::isfinite(camera[0]) && std::isfinite(camera[1]) && std::isfinite(camera[2]) &&
                (matrices.inv_view[0] != 0.0f || matrices.inv_view[5] != 0.0f);
}

"""

# ---- vk_pipeline_cache.cpp -------------------------------------------------------------------------
P1 = r"""#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)
"""
P1N = r"""#include "bbport_wind_hang_find.h" // bbport (r112i_hang-find-lanterns)
"""
P2 = r"""           (FragmentDiscards(sel) || (BbWindHang::KnobOnce().on && SkeletonRead(sel)) ||
"""
P2N = r"""            // bbport (r112i_hang-find-lanterns): an opaque static one (no skeleton): a lantern, chain or cage
            (BbWindHangFind::StaticOn() && !SkeletonRead(sel)) ||
"""

# ---- build files and README ------------------------------------------------------------------------
M1 = r"""target_include_directories(wind-hang-actors-test PRIVATE ..)
"""
M1N = r"""# bbport (r112i_hang-find-lanterns): static hanging things and the survey (shim/bbport_wind_hang_find.h); also
# built and run by engine/build.sh --test.
add_executable(wind-hang-find-test EXCLUDE_FROM_ALL ../tests/test_wind_hang_find.cpp)
target_compile_options(wind-hang-find-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wind-hang-find-test PRIVATE ..)
"""
B1 = r"""    out/wind-hang-actors-test
"""
B1N = r"""    # bbport (r112i_hang-find-lanterns): static hanging things and the survey
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_wind_hang_find.cpp -o out/wind-hang-find-test
    out/wind-hang-find-test
"""
R1 = r"""| `BB_WIND_HANG_ACTORS` | Part of `BB_WIND_HANG` (r112h;"""
R1P = r"""| `BB_WIND_HANG_STATIC` | Part of `BB_WIND_HANG` (r112i; `0` leaves it out and gives back r112h's rule, any other text or unset is on; it does nothing without `BB_WIND_HANG=1`). Static meshes hang too: a lantern, chain or cage that is a plain mesh with no bone palette. An opaque motion pipeline with no skeleton gets the sway code (it only reads its sway word, 0 for every draw that is not a candidate); a draw is a candidate when its position stream has at most `BB_WIND_HANG_STATIC_VERTS` vertices (no building, no big batch), the ray traced scene's world box of it is 0.15 m to `BB_WIND_HANG_STATIC_HEIGHT` m tall and at most 3 m wide, it hangs more than `BB_WIND_HANG_STATIC_CLEAR` m above the lowest box near it with no box under it, and no thin post stands through it. Then the skinned things' road: the GPU judge, r112h's hunter and indoor rules, the height rule and the push; it leans downwind about its top, push only. Needs ray tracing and the box keys (`BB_WIND_TWIGS` on). Off, no pipeline gets the sway code for it and no word is made. The log says "Wind sway hang (r112i)" once and every 600 frames. |
| `BB_WIND_HANG_STATIC_VERTS`, `BB_WIND_HANG_STATIC_HEIGHT`, `BB_WIND_HANG_STATIC_CLEAR` | The numbers of `BB_WIND_HANG_STATIC` (r112i): the most vertices of a candidate's position stream (64 to 1000000, default 20000), the tallest world box (0.15 to 4 m, default 2) and the least height of its bottom above the lowest box near it (0 to 20 m, default 1). Text that is no number gives the default. |
| `BB_WIND_HANG_FIND` | A TEST aid for `BB_WIND_HANG` (r112i; `1` turns it on, it does nothing without `BB_WIND_HANG=1`): every 600 frames the ray traced scene's meshes of 0.15 to 2 m height that hang (or are held at the top by a thin box) within 60 m of the camera, nearest first, each with its vertex and pixel shader hashes, skinned or static, index and vertex counts, world box, distance, height above the ground and the static path's verdict ("Wind sway hang (r112i)" lines). One map insert per capture draw while on. |
"""

EDITS = {
RH: [
('ins', H1, "", H1N),
('rep', H2, "", H2N),
('rep', H3, "", H3N),
('rep', H4, "", H4N),
('ins', H5, "", H5N),
],
RC: [
('ins', C1, "", C1N),
],
RE: [
('rep', E1, "", E1N),
('rep', E2, "", E2N),
('rep', E3, "", E3N),
('rep', E4, "", E4N),
('rep', E5, "", E5N),
('rep', E6, "", E6N),
('rep', E7, "", E7N),
('rep', E8, "", E8N),
('rep', E9, "", E9N),
('rep', E10, "", E10N),
('rep', E11, "", E11N),
('rep', E12, "", E12N),
('ins', E13, E13N, ""),
('ins', E14, "", E14N),
('ins', E15, "", E15N),
('ins', E16, "", E16N),
],
TH: [
('ins', T1, "", T1N),
],
TC: [
('ins', T2, T2N, ""),
],
PC: [
('ins', P1, "", P1N),
('ins', P2, "", P2N),
],
CM: [
('ins', M1, "", M1N),
],
BS: [
('ins', B1, "", B1N),
],
RM: [
('ins', R1, R1P, ""),
],
}

ORDER = (RH, RC, RE, TH, TC, PC, CM, BS, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def new_state():
    states = set()
    for path, text in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            states.add("clean")
            continue
        got = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
        if got != text:
            raise SystemExit("REFUSED: %s exists and is not this patch's file" % path)
        states.add("applied")
    if len(states) != 1:
        raise SystemExit("mixed state: some of the new files exist")
    return states.pop()


def text_checks(texts):
    """The ties a compiler cannot check."""
    re_ = texts[RE]
    v = re_.find("bool Rasterizer::WindHangVerdict(")
    a = re_.find("bool Rasterizer::WindHangActorsClear(")
    f = re_.find("void Rasterizer::WindHangFindRefresh(")
    s = re_.find("bool Rasterizer::WindHangStaticAllowed(")
    r = re_.find("void Rasterizer::WindHangFindReport(")
    p = re_.find("// bbport (r112b_hang-probe, TOOL): the first bone palette")
    if not (0 <= v < a < f < s < r < p):
        raise SystemExit("text check: the new functions are not between WindHangActorsClear and the probe")
    w = re_.find("u32 Rasterizer::WindSwayWord(")
    if not (0 <= w < v):
        raise SystemExit("text check: WindSwayWord is not before WindHangVerdict")
    once = re_.find("hang_find_said = true;")
    rep = re_.find("if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {", once)
    if not (0 <= once < rep):
        raise SystemExit("text check: the once-line is not before the report's frame test")
    line = re_.find("BbWindHangFind::StaticLine(")
    surv = re_.find("WindHangFindReport();", line)
    clear = re_.find("hang_box.ClearNotes();", surv)
    if not (0 <= line < surv < clear):
        raise SystemExit("text check: the static line and the survey are not before ClearNotes")
    for needle in ("BbWindHangFind::FindOn()) { // bbport (r112i_hang-find-lanterns): the survey's",):
        if re_.count(needle) != 1:
            raise SystemExit("text check: %r is not there once" % needle)
    # the static call chain: the Motion block's branch passes true, the signature has the default
    if "WindSwayWord(pipeline, palette != 0 ? 1 : 0, true)" not in texts[RC]:
        raise SystemExit("text check: the Motion block's static branch is missing")
    if "bool hang_static = false);" not in texts[RH] or "bool hang_static = false, u32 stride = 0);" not in texts[RH]:
        raise SystemExit("text check: the declarations' default arguments are missing")
    if "BbWindHangFind::StaticOn() && !SkeletonRead(sel)" not in texts[PC]:
        raise SystemExit("text check: SwayWanted's static clause is missing")
    for path in (RH, RC, RE, TH, TC, PC):
        for ed in EDITS[path]:
            for part in (ed[3:] if ed[0] == "rep" else ed[2:]):
                for text_line in part.split("\n"):
                    if len(text_line) > 110:
                        raise SystemExit("text check: %s: a new line over 110 columns: %r" %
                                         (path, text_line[:60]))
    for path, text in NEW_FILES.items():
        if not text.isascii() or "\t" in text or "\r" in text:
            raise SystemExit("text check: %s is not plain ASCII without tabs" % path)
        if text.count("{") != text.count("}") or text.count("(") != text.count(")"):
            raise SystemExit("text check: %s: braces or parentheses do not balance" % path)
    for path in (RH, RC, RE, TH, TC, PC):
        for ed in EDITS[path]:
            added = "".join(ed[2:]) if ed[0] == "ins" else ed[3]
            gone = ed[1] if ed[0] == "rep" else ""
            for open_, close in (("{", "}"), ("(", ")")):
                if added.count(open_) - added.count(close) != gone.count(open_) - gone.count(close):
                    raise SystemExit("text check: %s: an edit changes the balance of %s%s: %r" %
                                     (path, open_, close, (ed[1] if ed[0] == "rep" else added)[:60]))
    if texts[RM].count("| `BB_WIND_HANG_STATIC` |") != 1 or texts[RM].count("| `BB_WIND_HANG_FIND` |") != 1:
        raise SystemExit("text check: README's rows are not there once")
    # the header's names are the ones the edits use
    for want in ("inline Entry Evaluate", "class StaticBook", "class BoxSet", "class Draws",
                 "inline std::vector<std::string> SurveyLines", "inline std::string StaticLine",
                 "inline std::string OnceText", "inline bool Wanted(", "inline bool StaticOn()",
                 "inline bool FindOn()", "struct Look {"):
        if want not in NEW_FILES[NF].replace("[[nodiscard]] ", ""):
            raise SystemExit("text check: %r is missing in the new header" % want)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112I_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == RE and ("WindHangActorsClear(" not in cur or "WindTwigSmall(" not in cur):
            raise SystemExit("REFUSED: r112h_hang-not-the-hunter (and r89e) must be applied (WindHangActorsClear)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    states.add(new_state())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the "
                  "result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112itmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, text in NEW_FILES.items():
            full = os.path.join(ROOT, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            tmp = full + ".r112itmp"
            open(tmp, "wb").write(text.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112itmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


if __name__ == "__main__":
    main()
