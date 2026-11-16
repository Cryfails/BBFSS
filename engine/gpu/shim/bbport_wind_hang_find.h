// SPDX-License-Identifier: GPL-3.0-or-later
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
inline constexpr std::size_t TakenMost = 6, TakenChars = 300; // bbport (r112j_hang-static-verts)
// bbport (r112k_hang-lantern-verdict): the survey's lines may be this long (the route's tail needs more than r112j's
// LineChars), the routes kept at most, how long a skinned refusal stands (frames), the most a static candidate's keys
// may span by default (m: the union of the places a mesh is drawn at) and at most
inline constexpr std::size_t LineCharsK = 560, RoutesMost = 4096; // bbport (r112l): was 480 (the cut-out mark)
inline constexpr std::uint64_t HoldSkinned = 1800;
inline constexpr float UnionDefault = 12.0f, UnionMax = 40.0f;

static_assert(HeightLo > 0.0f && HeightHiDefault <= HeightHiMax && HeightHiDefault > HeightLo);
static_assert(SupportGap > 0.0f && ThinWidth > 0.0f && NearGap > SupportGap);

struct Knobs {
    bool static_on = true; ///< BB_WIND_HANG_STATIC is not 0
    bool find = false;     ///< BB_WIND_HANG_FIND=1
    std::uint32_t verts = VertsDefault;
    float height_hi = HeightHiDefault;
    float clear = ClearDefault;
    std::uint32_t focus = 0; ///< bbport (r112k): BB_WIND_HANG_FOCUS: a vertex shader hash (hex) the survey lists first
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

/// bbport (r112k_hang-lantern-verdict): BB_WIND_HANG_FOCUS: a vertex shader hash in hex (the survey's "vs"); 0 (no
/// text, an empty one or one that is no hex number) lists none first.
[[nodiscard]] inline std::uint32_t ParseFocus(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return 0;
    }
    char* end = nullptr;
    const unsigned long value = std::strtoul(text, &end, 16);
    if (end == text || *end != 0) {
        return 0;
    }
    return static_cast<std::uint32_t>(value & 0xffffffffu);
}

[[nodiscard]] inline Knobs WithFocus(Knobs k, const char* focus) {
    k.focus = ParseFocus(focus);
    return k;
}

/// The knobs, read once.
[[nodiscard]] inline const Knobs& KnobOnce() {
    static const Knobs k = WithFocus(
        ParseKnobs(std::getenv("BB_WIND_HANG_STATIC"), std::getenv("BB_WIND_HANG_FIND"),
                   std::getenv("BB_WIND_HANG_STATIC_VERTS"),
                   std::getenv("BB_WIND_HANG_STATIC_HEIGHT"),
                   std::getenv("BB_WIND_HANG_STATIC_CLEAR")),
        std::getenv("BB_WIND_HANG_FOCUS"));
    return k;
}

/// The static path is on: BB_WIND_HANG on (it needs the plant sway) and BB_WIND_HANG_STATIC not 0.
[[nodiscard]] inline bool StaticOn() {
    return H::KnobOnce().on && KnobOnce().static_on;
}

// bbport (r112k_hang-lantern-verdict): BB_WIND_HANG_STATIC_GPU (default on; exactly 0 = r112j): a draw of an opaque
// pipeline with the Sway bit whose small bone palette the GPU writes (Motion::Kind::GpuPalette) goes to the static path
// too, when its stream's standing verdict is a candidate (r112i and r112j offered only Kind::Other draws, the ones whose
// palette the CPU reads: the lanterns of the graveyard were never asked).
[[nodiscard]] inline bool ParseGpu(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool GpuKnob() {
    static const bool on = ParseGpu(std::getenv("BB_WIND_HANG_STATIC_GPU"));
    return on;
}

/// The GPU-palette route is on: the static path is, and BB_WIND_HANG_STATIC_GPU is not 0.
[[nodiscard]] inline bool GpuOn() {
    return StaticOn() && GpuKnob();
}

// bbport (r112k): BB_WIND_HANG_STATIC_UNION (m, UnionDefault, held to MaxExtent..UnionMax): the most the keys of a static
// candidate may span (a mesh drawn at several places spans the union of them; r112 stopped every hanging thing at 4 m).
[[nodiscard]] inline float ParseUnion(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, UnionDefault), H::MaxExtent, UnionMax);
}

[[nodiscard]] inline float UnionKnob() {
    static const float span = ParseUnion(std::getenv("BB_WIND_HANG_STATIC_UNION"));
    return span;
}

// bbport (r112l_hang-discard-lanterns): BB_WIND_HANG_STATIC_CUT (default on; exactly 0 = r112k): a draw of a pipeline whose
// pixel shader discards (a cut-out: the graveyard lanterns' ps 0f54e5f9 is one) goes to the static path like an opaque one,
// when its stream is a hanging candidate. r112i's Wanted refused every such pipeline before any verdict ("a cut-out is the
// twigs'"): the survey read "disc 1 ... asked 0, book -" for them.
[[nodiscard]] inline bool ParseCut(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool CutKnob() {
    static const bool on = ParseCut(std::getenv("BB_WIND_HANG_STATIC_CUT"));
    return on;
}

/// The cut-out route is on: the static path is, and BB_WIND_HANG_STATIC_CUT is not 0.
[[nodiscard]] inline bool CutOn() {
    return StaticOn() && CutKnob();
}

/// A pixel shader (null: none) that discards.
template <class Stage>
[[nodiscard]] inline bool Cuts(const Stage* fragment) {
    return fragment != nullptr && fragment->has_discard;
}

/// Pure form of WantedCut: a pipeline with the Sway bit; one whose pixel shader discards only with the cut knob.
template <class Stage>
[[nodiscard]] inline bool WantedCutWith(bool static_on, bool cut_on, bool sway_bit, const Stage* fragment) {
    return static_on && sway_bit && (cut_on || !Cuts(fragment));
}

/// May a static draw of this pipeline carry a hang word (is the pipeline built for it)? As Wanted, and a cut-out too
/// with BB_WIND_HANG_STATIC_CUT (the caller then asks the static book about the stream before it takes the draw).
template <class Stage>
[[nodiscard]] inline bool WantedCut(bool sway_bit, const Stage* fragment) {
    return WantedCutWith(StaticOn(), CutKnob(), sway_bit, fragment);
}

// bbport (r112l): BB_WIND_HANG_STATIC_GAIN (0 to 1, default GainDefault): the share of the sway's push a static candidate gets
// (b55: 0.4 m on a lantern, far above a lantern's few cm); BB_WIND_HANG_STATIC_TALL (m, MinExtent to UnionMax, default
// TallDefault): the keys' span beyond which a static candidate must clearly hang (ClearlyHanging) to keep its union limit.
inline constexpr float GainDefault = 0.2f;
inline constexpr float TallDefault = 2.5f;
inline constexpr float ClearlyHeight = 1.5f; ///< m: a mesh that clearly hangs is at most this tall (scene box)
inline constexpr float ClearlyAbove = 2.0f;  ///< m: and its bottom is at least this far over the ground

[[nodiscard]] inline float ParseGain(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, GainDefault), 0.0f, 1.0f);
}

[[nodiscard]] inline float GainKnob() {
    static const float gain = ParseGain(std::getenv("BB_WIND_HANG_STATIC_GAIN"));
    return gain;
}

[[nodiscard]] inline float ParseTall(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, TallDefault), H::MinExtent, UnionMax);
}

[[nodiscard]] inline float TallKnob() {
    static const float tall = ParseTall(std::getenv("BB_WIND_HANG_STATIC_TALL"));
    return tall;
}

/// A hang word's ramp byte scaled by the static push gain (0 to 1).
[[nodiscard]] inline std::uint32_t GainRamp(std::uint32_t ramp, float gain) {
    return std::uint32_t(std::lround(float(ramp) * std::clamp(gain, 0.0f, 1.0f)));
}

/// The survey is on: BB_WIND_HANG on and BB_WIND_HANG_FIND=1.
[[nodiscard]] inline bool FindOn() {
    return H::KnobOnce().on && KnobOnce().find;
}

// bbport (r112j_hang-static-verts): the push of a static hanging thing under a roof. BB_WIND_HANG_STATIC_ROOF
// (0 to 1, default 0.1, 1 = off): the scale of its push while the camera's open share of the wind (r117's
// field at the camera) is at or under the indoor share (BB_WIND_HANG_INDOOR), rising to 1 at RoofOpen (or
// RoofGap over the indoor share when that is higher): a smooth ramp, so nothing pops when the camera walks in.
inline constexpr float RoofDefault = 0.1f, RoofOpen = 0.5f, RoofGap = 0.05f;

[[nodiscard]] inline float ParseRoof(const char* text) {
    return std::clamp(BbWindSway::ParseNumber(text, RoofDefault), 0.0f, 1.0f);
}

/// The knob, read once.
[[nodiscard]] inline float RoofKnob() {
    static const float roof = ParseRoof(std::getenv("BB_WIND_HANG_STATIC_ROOF"));
    return roof;
}

/// The scale of the push at the camera's open share `open` (`indoor`: BB_WIND_HANG_INDOOR, `roof`: the knob).
[[nodiscard]] inline float RoofScale(float roof, float indoor, float open) {
    const float hi = std::max(RoofOpen, indoor + RoofGap);
    const float t = std::clamp((open - indoor) / (hi - indoor), 0.0f, 1.0f);
    return roof + (1.0f - roof) * t;
}

/// A sway word with its ramp byte (bits 16-23, BbWindSway::PackWord) scaled by `scale` (0 to 1).
[[nodiscard]] inline std::uint32_t ScaleRamp(std::uint32_t word, float scale) {
    const std::uint32_t ramp = (word >> 16) & 255u;
    const std::uint32_t scaled =
        std::uint32_t(std::lround(float(ramp) * std::clamp(scale, 0.0f, 1.0f)));
    return (word & ~(255u << 16)) | (scaled << 16);
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

enum class Why : std::uint8_t { Ok, TooBig, NoBox, Shape, NoGround, Grounded, Skinned };
inline constexpr std::size_t WhyCount = 7; // bbport (r112k_hang-lantern-verdict): Skinned

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
    case Why::Skinned: // bbport (r112k_hang-lantern-verdict)
        return "skinned";
    }
    return "?";
}

/// What is known of one static stream.
struct Entry {
    // bbport (r112j_hang-static-verts): `verts` is the mesh's OWN vertex count (the ray traced scene's index
    // range of its draw: the survey's "verts"); `stream_verts` is what the bytes bound at the stream's address
    // over its stride say: the size of the buffer the mesh lies in, not of the mesh (r112i tested that one and
    // refused every mesh); kept for the log only
    std::uint32_t size = 0, verts = 0, stream_verts = 0; ///< bytes bound at its address; own vertices; bytes / stride
    std::uint64_t vs = 0;                                ///< its vertex shader's hash (for the log)
    Why why = Why::Ok;
    std::uint64_t until = 0; ///< the verdict stands until this frame
    std::uint64_t seen = 0;  ///< the last frame a draw of it was looked at
    float height = 0.0f, width = 0.0f, above = 0.0f; ///< its box (m) and height over the ground
};

/// The verdict on a new static stream: `size` the bytes bound at its address and `stream_verts` those over its
/// stride (the buffer's, for the log only: r112j), `b` its box in the scene (null: none) and with it the mesh's
/// own vertex count, the number tested against Knobs::verts (r112j), `all` the scene's boxes, `stream` its address.
[[nodiscard]] inline Entry Evaluate(const Knobs& k, std::uint32_t size, std::uint32_t stream_verts,
                                    std::uint64_t stream, const Box* b, const std::vector<Box>& all,
                                    std::uint64_t frame) {
    Entry e;
    e.size = size;
    e.stream_verts = stream_verts;
    e.seen = frame;
    if (b == nullptr) {
        e.why = Why::NoBox;
        e.until = frame + HoldNoBox;
        return e;
    }
    e.verts = b->vertices; // bbport (r112j): the mesh's own count
    if (e.verts > k.verts) {
        e.why = Why::TooBig;
        e.until = frame + HoldBig;
        return e;
    }
    if (b->skinned) { // bbport (r112k_hang-lantern-verdict): a skeleton draws it (r112's path); never the static book's
        e.why = Why::Skinned;
        e.until = frame + HoldSkinned;
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
    /// bbport (r112j_hang-static-verts): the streams refused as too big (how many, and the least and the most
    /// of their own vertex counts), and the candidates of the last verdicts (the newest TakenMost), for the log
    std::uint64_t big_n = 0;
    std::uint32_t big_least = 0, big_most = 0;
    struct Taken {
        std::uint64_t stream = 0;
        Entry e;
    };
    std::vector<Taken> taken;

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
        if (e.why == Why::TooBig) { // bbport (r112j_hang-static-verts)
            big_least = big_n == 0 ? e.verts : std::min(big_least, e.verts);
            big_most = std::max(big_most, e.verts);
            ++big_n;
        } else if (e.why == Why::Ok) {
            const auto same = std::find_if(taken.begin(), taken.end(),
                                           [&](const Taken& t) { return t.stream == stream; });
            if (same != taken.end()) {
                same->e = e;
            } else {
                if (taken.size() >= TakenMost) {
                    taken.erase(taken.begin());
                }
                taken.push_back({stream, e});
            }
        }
    }

    /// bbport (r112k_hang-lantern-verdict): a standing candidate whose box in the scene carries the skinned flag (a
    /// verdict made before a skeleton draw of the stream was seen) is refused from now on and leaves the list.
    void DropSkinned(const std::vector<Box>& boxes, std::uint64_t frame) {
        for (const Box& b : boxes) {
            if (!b.skinned || b.stream == 0) {
                continue;
            }
            const auto found = entries.find(b.stream);
            if (found == entries.end() || found->second.why != Why::Ok) {
                continue;
            }
            found->second.why = Why::Skinned;
            found->second.until = frame + HoldSkinned;
            ++skinned_dropped;
            ++by_why[static_cast<std::size_t>(Why::Skinned)];
            const std::uint64_t stream = b.stream;
            taken.erase(std::remove_if(taken.begin(), taken.end(),
                                       [stream](const Taken& t) { return t.stream == stream; }),
                        taken.end());
        }
    }

    std::uint64_t skinned_dropped = 0; ///< bbport (r112k): candidates taken back by DropSkinned

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
    // bbport (r112j_hang-static-verts): the camera's view (3x4 rows) and projection (x, y scales, z scale, z
    // offset) and the render size, for the survey's screen estimate (ScreenOf)
    bool view_ok = false;
    std::array<float, 12> view{};
    std::array<float, 4> proj{};
    std::array<std::uint32_t, 2> render{};

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

/// bbport (r112k_hang-lantern-verdict, TOOL grade with BB_WIND_HANG_FIND=1): what the rasterizer's Motion block made
/// of the draws of a stream (by the address of its position attribute): the kind of the draws (S skinned, P GPU
/// palette, O other), whether the pipeline has the Sway bit and a pixel shader that discards, how many draws, how many
/// got a sway word, how many of those words reached the motion parameter, and how many were asked of the static path
/// and passed as a candidate. The survey prints it after the stream's line: a stream with no route was drawn by no pass
/// that has the Motion block.
struct Route {
    char kind = '?';
    bool sway_bit = false, discards = false;
    std::uint32_t draws = 0, swayed = 0, delivered = 0, asked = 0, passed = 0;
    std::uint64_t frame = 0;
};

class Routes {
public:
    std::uint64_t dropped = 0; ///< streams not kept for want of room

    void Note(std::uint64_t stream, char kind, bool sway_bit, bool discards, bool swayed, bool delivered,
              std::uint64_t frame) {
        Route* const r = Slot(stream);
        if (r == nullptr) {
            return;
        }
        r->kind = kind;
        r->sway_bit = sway_bit;
        r->discards = discards;
        ++r->draws;
        r->swayed += swayed ? 1u : 0u;
        r->delivered += delivered ? 1u : 0u;
        r->frame = frame;
    }

    /// The static path judged a draw of the stream: `pass` = a candidate.
    void Asked(std::uint64_t stream, bool pass) {
        Route* const r = Slot(stream);
        if (r == nullptr) {
            return;
        }
        ++r->asked;
        r->passed += pass ? 1u : 0u;
    }

    [[nodiscard]] const Route* Find(std::uint64_t stream) const {
        const auto found = routes.find(stream);
        return found == routes.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return routes.size();
    }

private:
    Route* Slot(std::uint64_t stream) {
        if (stream == 0) {
            return nullptr;
        }
        const auto found = routes.find(stream);
        if (found != routes.end()) {
            return &found->second;
        }
        if (routes.size() >= RoutesMost) {
            ++dropped;
            return nullptr;
        }
        return &routes[stream];
    }

    std::unordered_map<std::uint64_t, Route> routes;
};

/// Counts of the static path's draws since the last line.
struct Stats {
    std::uint64_t draws = 0;     ///< opaque static draws of sway pipelines asked about
    std::uint64_t no_stream = 0; ///< no position stream found
    std::uint64_t no_keys = 0;   ///< no box keys (BB_WIND_TWIGS off) or no sway words
    std::uint64_t refused = 0;   ///< a standing verdict said no
    std::uint64_t passed = 0;    ///< a standing verdict said candidate
    std::uint64_t judged = 0;    ///< a stream got a new verdict
    std::uint64_t gpu_asked = 0;  ///< bbport (r112k): draws of GPU-palette streams of opaque sway pipelines asked about
    std::uint64_t gpu_passed = 0; ///< bbport (r112k): and those of a candidate stream (sent on to the static path)
    std::uint64_t cut_asked = 0;  ///< bbport (r112l): of those, draws of a pipeline whose pixel shader discards (cut-outs)
    std::uint64_t cut_passed = 0; ///< bbport (r112l): and those of a candidate stream
    std::uint64_t too_tall = 0;   ///< bbport (r112m): draws of a static candidate refused as too tall (its scene box)
    std::uint64_t roof_words = 0; ///< bbport (r112j): hang words of static things scaled down (camera under a roof)
    std::uint64_t full_words = 0; ///< bbport (r112j): and left whole
    float roof_least = 1.0f;      ///< bbport (r112j): the least scale given
};

[[nodiscard]] inline std::string Cap(const char* text) {
    std::string out(text);
    if (out.size() > LineCharsK) { // bbport (r112k): was LineChars
        out.resize(LineCharsK - 3);
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
                  "mesh (its own count: r112j) has at most %u vertices (BB_WIND_HANG_STATIC_VERTS) and the ray traced "
                  "scene's world box of it is %.2f-%.1f m tall (BB_WIND_HANG_STATIC_HEIGHT) and at "
                  "most %.0f m wide, its bottom over %.1f m above the lowest box near and nothing "
                  "under it (BB_WIND_HANG_STATIC_CLEAR); then the GPU judge, the hunter and indoor "
                  "rules of r112h and r112g's height rule decide; survey of what hangs "
                  "(BB_WIND_HANG_FIND): %s; lines every %u frames",
                  k.static_on ? 1 : 0, k.verts, double(HeightLo), double(k.height_hi),
                  double(WidthHi), double(k.clear), k.find ? "ON" : "off", BbWindSway::ReportFrames);
    return std::string(buf);
}

/// bbport (r112j_hang-static-verts): the once-line of the fix.
[[nodiscard]] inline std::string OnceTextJ(const Knobs& k, float roof, float indoor) {
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112j): the static path's vertex test compares the mesh's OWN count (the ray "
                  "traced scene's index range of its draw), at most %u, and no more the bytes bound at its "
                  "stream's address over the stride (the buffer's: r112i read that and refused 17 of 17 and 50 "
                  "of 52 streams); a static hanging thing's push is x%.2f while the camera's open share of the "
                  "wind is %.2f or less, rising to x1 at %.2f (BB_WIND_HANG_STATIC_ROOF=%.2f, 1 = off); the "
                  "survey's lines carry scr x,y (an estimate of the screen position)",
                  k.verts, double(roof), double(indoor), double(std::max(RoofOpen, indoor + RoofGap)),
                  double(roof));
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

/// bbport (r112j_hang-static-verts): where a world point lies on the screen, estimated from the camera's view
/// (3x4 rows, world to view, z forward) and projection (x and y scales signed by the G-buffer viewport: ndc +y down, footprints.h's rule) in pixels of
/// the render size. An estimate that no picture has checked: the survey prints it as "scr".
struct Screen {
    bool known = false; ///< the camera was read
    bool ok = false;    ///< and the point is in front of it
    float x = 0.0f, y = 0.0f;
};

[[nodiscard]] inline Screen ScreenOf(const BoxSet& set, float wx, float wy, float wz) {
    Screen s;
    if (!set.view_ok) {
        return s;
    }
    s.known = true;
    const std::array<float, 12>& v = set.view;
    const float vx = v[0] * wx + v[1] * wy + v[2] * wz + v[3];
    const float vy = v[4] * wx + v[5] * wy + v[6] * wz + v[7];
    const float vz = v[8] * wx + v[9] * wy + v[10] * wz + v[11];
    if (!(vz > 0.05f) || !std::isfinite(vx + vy + vz)) {
        return s;
    }
    s.ok = true;
    s.x = 0.5f * float(set.render[0]) * (1.0f + set.proj[0] * vx / vz);
    s.y = 0.5f * float(set.render[1]) * (1.0f + set.proj[1] * vy / vz); // (review) proj[1] carries the sign
    return s;
}

/// bbport (r112j_hang-static-verts): the second line of the static path: the numbers first (how many streams
/// were refused as too big and the least and the most of their OWN counts, the roof push), then the
/// candidates by vertex shader hash. Under TakenChars characters.
[[nodiscard]] inline std::string TakenLine(const StaticBook& book, const Knobs& k, const Stats& s) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    char buf[200];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112j): candidates %zu, too big %llu (own counts %u..%u, limit %u); roof "
                  "push %llu words (least x%.2f), %llu full:",
                  book.taken.size(), n(book.big_n), book.big_least, book.big_most, k.verts,
                  n(s.roof_words), double(s.roof_least), n(s.full_words));
    std::string out(buf);
    for (const StaticBook::Taken& t : book.taken) {
        std::snprintf(buf, sizeof(buf), " vs %08x %u verts %.2f m tall %.1f m up;",
                      static_cast<unsigned>(t.e.vs & 0xffffffffull), t.e.verts, double(t.e.height),
                      double(t.e.above));
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > TakenChars) {
        out.resize(TakenChars - 3);
        out += "...";
    }
    return out;
}

/// bbport (r112k_hang-lantern-verdict, TOOL grade): the route text after a survey line: what the Motion block made of
/// the draws of the stream (Routes), "[focus]" when its vertex shader is BB_WIND_HANG_FOCUS's. Only the focus mark
/// without routes (the tests' calls).
[[nodiscard]] inline std::string RouteText(const Routes* routes, std::uint64_t stream, bool focus) {
    if (routes == nullptr) {
        return focus ? std::string(" [focus]") : std::string();
    }
    char buf[200];
    const Route* const r = routes->Find(stream);
    if (r == nullptr) {
        std::snprintf(buf, sizeof(buf), "%s; route none (no draw of it reached the Motion block)",
                      focus ? " [focus]" : "");
    } else {
        std::snprintf(buf, sizeof(buf),
                      "%s; route %c bit %d disc %d draws %u swayed %u delivered %u asked %u passed %u",
                      focus ? " [focus]" : "", r->kind, r->sway_bit ? 1 : 0, r->discards ? 1 : 0,
                      static_cast<unsigned>(r->draws), static_cast<unsigned>(r->swayed),
                      static_cast<unsigned>(r->delivered), static_cast<unsigned>(r->asked),
                      static_cast<unsigned>(r->passed));
    }
    return std::string(buf);
}

/// bbport (r112k_hang-lantern-verdict): where the push of a hanging thing comes from, from the wind snapshot: r112's
/// "push" prints the follower's last table sample, which stays 0 until a table is filled (the first pushed draw).
struct PushSource {
    bool wind_on = false;
    float speed = 0.0f, gust = 1.0f, drive = 1.0f; ///< m/s, the gust factor now, its square (what drives the push)
    float amp = 0.0f;     ///< m at gust 1 (BB_WIND_SWAY x PushFull x (speed / FullSpeed)^2)
    float now = 0.0f;     ///< m: amp x drive, held to MaxAlong
    float lantern = 0.0f; ///< m: now x the scale of a 0.9 m thing: its bottom, at most
};

[[nodiscard]] inline PushSource PushSourceOf(bool wind_on, float speed, float gust, float scale) {
    PushSource p;
    p.wind_on = wind_on;
    p.speed = speed;
    p.gust = gust;
    p.drive = H::Drive(gust);
    p.amp = H::Amp(speed, scale);
    p.now = std::clamp(p.amp * p.drive, 0.0f, BbWindSway::MaxAlong);
    p.lantern = p.now * H::HangScale(0.0f, 0.9f);
    return p;
}

/// bbport (r112k): the once-line of the fix.
[[nodiscard]] inline std::string OnceTextK(const Knobs& k, bool gpu, bool live, float union_m) {
    char focus[16];
    if (k.focus != 0) {
        std::snprintf(focus, sizeof(focus), "%08x", static_cast<unsigned>(k.focus));
    } else {
        std::snprintf(focus, sizeof(focus), "none");
    }
    char buf[1024];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112k): a draw whose small bone palette the GPU writes is a static candidate too "
                  "(BB_WIND_HANG_STATIC_GPU=%d); a stream a skeleton draws is refused (skinned); a static "
                  "candidate's keys may span %.1f m, the union of the places it is drawn at (BB_WIND_HANG_STATIC_UNION; "
                  "r112 stopped at %.1f m); survey focus (BB_WIND_HANG_FOCUS): %s, and a route tail on the survey's "
                  "lines; live knob BB_WIND_HANG_PUSH=0 (set:/unset:) stops the push at once: %s",
                  gpu ? 1 : 0, double(union_m), double(H::MaxExtent), focus, live ? "available" : "not built in");
    return std::string(buf);
}

/// bbport (r112k): the candidates' measures: for each (the newest TakenMost) the scene box's height, then what the
/// keys of its slot measured (r112's book): fits or not. Under 400 characters.
[[nodiscard]] inline std::string MeasureText(const StaticBook& book, H::Book& heights) {
    std::string out = "Wind sway hang (r112k): candidates measured:";
    char buf[128];
    for (const StaticBook::Taken& t : book.taken) {
        const H::Entry* const h = heights.Find(t.stream);
        const unsigned vs = static_cast<unsigned>(t.e.vs & 0xffffffffull);
        if (h == nullptr || !h->judged) {
            std::snprintf(buf, sizeof(buf), " vs %08x scene %.2f m, keys not read;", vs, double(t.e.height));
        } else {
            std::snprintf(buf, sizeof(buf), " vs %08x scene %.2f m, keys %.2f m (%s);", vs, double(t.e.height),
                          double(h->top - h->base), h->fits ? "fits" : "does not fit");
        }
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > 400) {
        out.resize(397);
        out += "...";
    }
    return out;
}

/// bbport (r112k): the line of the fix every ReportFrames frames: the GPU-palette draws asked and passed, the routes
/// kept, the skinned refusals, the push's source.
[[nodiscard]] inline std::string KLine(const Stats& s, const StaticBook& book, const Routes& routes, bool gpu,
                                       const PushSource& p) {
    char buf[1024];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112k): GPU-palette static draws (BB_WIND_HANG_STATIC_GPU=%d): %llu asked, %llu of "
                  "a candidate stream; streams with a route %zu (%llu not kept); skinned refused %llu (%llu taken back "
                  "from a standing candidate); push source: wind %s, speed %.2f m/s, gust %.2f (drive %.2f), "
                  "amplitude %.3f m at gust 1, %.3f m now, the bottom of a 0.9 m lantern %.3f m at most (r112's "
                  "'push' prints 0 until a table is filled: nothing pushed yet)",
                  gpu ? 1 : 0, n(s.gpu_asked), n(s.gpu_passed), routes.Size(), n(routes.dropped),
                  n(book.by_why[static_cast<std::size_t>(Why::Skinned)]), n(book.skinned_dropped),
                  p.wind_on ? "on" : "off", double(p.speed), double(p.gust), double(p.drive), double(p.amp),
                  double(p.now), double(p.lantern));
    return std::string(buf);
}

/// bbport (r112l_hang-discard-lanterns): a candidate that clearly hangs: a small mesh (its scene box at most ClearlyHeight
/// tall) that stands well clear of the ground (its bottom ClearlyAbove or more over it): the places a lantern hangs at.
[[nodiscard]] inline bool ClearlyHanging(const Entry& e) {
    return e.height <= ClearlyHeight && e.above >= ClearlyAbove;
}

/// The most the keys of a static candidate may span: the union limit for a mesh that clearly hangs (a mesh drawn at
/// several places spans the union of them), else the tall limit held to r112's MaxExtent.
[[nodiscard]] inline float SpanLimitWith(float union_m, float tall_m, const Entry& e) {
    return ClearlyHanging(e) ? union_m : std::min(H::MaxExtent, tall_m);
}

[[nodiscard]] inline float SpanLimit(const Entry& e) {
    return SpanLimitWith(UnionKnob(), TallKnob(), e);
}

/// The push of a static candidate now (m): the push table's value held to MaxAlong, times the gain.
[[nodiscard]] inline float StaticPush(const PushSource& p, float gain) {
    return p.now * std::clamp(gain, 0.0f, 1.0f);
}

/// The survey's mark of a stream whose pixel shader discards (nothing for another or no route).
[[nodiscard]] inline std::string CutNote(const Routes* routes, std::uint64_t stream, bool cut_on) {
    if (routes == nullptr) {
        return std::string();
    }
    const Route* const r = routes->Find(stream);
    if (r == nullptr || !r->discards) {
        return std::string();
    }
    return cut_on ? std::string(" [cut-out: offered]") : std::string(" [cut-out: held back, CUT=0]");
}

/// The once-line of r112l: why a discard stopped the lanterns, and what is done.
[[nodiscard]] inline std::string OnceTextL(bool cut, float gain, float tall_m) {
    char buf[1536];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112l): a pipeline whose pixel shader discards (a cut-out lantern or cage; r112i's "
                  "Wanted refused it before any verdict: the survey's 'disc 1' with 'asked 0, book -') is offered to the "
                  "static path like an opaque one and pushed when its stream is a candidate (BB_WIND_HANG_STATIC_CUT=%d); "
                  "a static candidate's push is %.2f of the sway's (BB_WIND_HANG_STATIC_GAIN): at most %.3f m (MaxAlong "
                  "x gain); keys that span more than %.1f m (BB_WIND_HANG_STATIC_TALL; r112's %.1f m at most) count only "
                  "for a mesh that clearly hangs (scene box at most %.1f m tall, %.1f m or more over the ground: the "
                  "union of the places a lantern is drawn at), any other is refused as too tall",
                  cut ? 1 : 0, double(gain), double(BbWindSway::MaxAlong * gain), double(tall_m), double(H::MaxExtent),
                  double(ClearlyHeight), double(ClearlyAbove));
    return std::string(buf);
}

/// The line of r112l every ReportFrames frames: the cut-out draws asked and passed, the static push gain and its size now.
[[nodiscard]] inline std::string CutLine(const Stats& s, bool cut, float gain, const PushSource& p) {
    char buf[1024];
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112l): cut-out streams (a pixel shader that discards; BB_WIND_HANG_STATIC_CUT=%d): "
                  "%llu draws asked, %llu of a candidate stream; static push gain %.2f (BB_WIND_HANG_STATIC_GAIN): a "
                  "static candidate is pushed %.3f m now (wind %s, %.2f m/s, gust %.2f), at most %.3f m (MaxAlong x gain), "
                  "its lowest part moving as a whole by that",
                  cut ? 1 : 0, n(s.cut_asked), n(s.cut_passed), double(gain), double(StaticPush(p, gain)),
                  p.wind_on ? "on" : "off", double(p.speed), double(p.gust),
                  double(BbWindSway::MaxAlong * std::clamp(gain, 0.0f, 1.0f)));
    return std::string(buf);
}

/// The candidates' keys: for each (the newest TakenMost) the span of its slot's keys, the limit it got and whether it was
/// kept as clearly hanging or refused as too tall, with the scene box's height and the height over the ground.
[[nodiscard]] inline std::string TallText(const StaticBook& book, H::Book& heights, float union_m, float tall_m) {
    std::string out = "Wind sway hang (r112l): candidates by the span of their keys:";
    char buf[220];
    for (const StaticBook::Taken& t : book.taken) {
        const H::Entry* const h = heights.Find(t.stream);
        const unsigned vs = static_cast<unsigned>(t.e.vs & 0xffffffffull);
        if (h == nullptr || !h->judged) {
            std::snprintf(buf, sizeof(buf), " vs %08x keys not read;", vs);
            out += buf;
            continue;
        }
        const float span = h->top - h->base;
        const float limit = SpanLimitWith(union_m, tall_m, t.e);
        const bool tall = span > std::min(H::MaxExtent, tall_m);
        const char* what = !tall                 ? "within the tall limit"
                           : span <= limit       ? "over it, kept: clearly hanging"
                           : ClearlyHanging(t.e) ? "refused: over the union limit"
                                                 : "refused: over it, not clearly hanging";
        std::snprintf(buf, sizeof(buf), " vs %08x keys %.2f m (%s; scene %.2f m, %.2f m up, limit %.1f m);", vs,
                      double(span), what, double(t.e.height), double(t.e.above), double(limit));
        out += buf;
    }
    if (book.taken.empty()) {
        out += " none";
    }
    if (out.size() > 700) {
        out.resize(697);
        out += "...";
    }
    return out;
}

// bbport (r112m_hang-close-proof): BB_WIND_HANG_STATIC_SAME (default on; exactly 0 = r112l): the ramp of a static candidate
// makes its BOTTOM move by min(scale, gain) x push (scale: the shaders' HangScale of its keys' height), so a 0.21 m part
// moves as far as the 0.88 m cage it hangs in (r112l: scale x gain x push: 1.0 cm against 4.2 cm).
inline constexpr std::size_t CandMost = 12; ///< candidate lines of one report at most

[[nodiscard]] inline bool ParseSame(const char* text) {
    return !(text != nullptr && text[0] == '0' && text[1] == 0);
}

[[nodiscard]] inline bool SameKnob() {
    static const bool on = ParseSame(std::getenv("BB_WIND_HANG_STATIC_SAME"));
    return on;
}

[[nodiscard]] inline float ClampGain(float gain) {
    return std::isnan(gain) ? 0.0f : std::clamp(gain, 0.0f, 1.0f);
}

[[nodiscard]] inline float ClampScale(float scale) {
    return std::clamp(std::isnan(scale) ? 1.0f : scale, H::HangScaleMin, 1.0f);
}

/// A static candidate's ramp byte: with `same` the ramp times min(1, gain / scale) (the bottom then moves min(scale, gain) x
/// push), else r112l's ramp times gain (GainRamp: the bottom moves scale x gain x push).
[[nodiscard]] inline std::uint32_t SameRamp(std::uint32_t ramp, float gain, float scale, bool same) {
    const float g = ClampGain(gain);
    const float f = same ? std::min(1.0f, g / ClampScale(scale)) : g;
    return static_cast<std::uint32_t>(std::lround(float(ramp) * f));
}

/// How far the bottom of a static candidate of scale `scale` moves (m) when the push table says `now`.
[[nodiscard]] inline float BottomPush(float now, float gain, float scale, bool same) {
    const float g = ClampGain(gain);
    const float s = ClampScale(scale);
    return now * (same ? std::min(s, g) : s * g);
}

/// The real hanging length of a static candidate is its mesh's own box in the ray traced scene (the keys of its slot span
/// the union of all the places the mesh is drawn at): refused when that box is taller than the tall limit.
[[nodiscard]] inline bool TooTall(const Entry& e, float tall_m) {
    return e.height > tall_m;
}

/// One candidate of the scene now, as the report lines see it.
struct CandInfo {
    std::uint64_t stream = 0;
    Entry e;                        ///< the static book's entry: vs, verts, scene height, width, height over the ground
    std::array<float, 6> box{};     ///< its nearest box in the scene
    float dist = -1.0f;             ///< m from the camera to that box's middle (-1: the camera was not read)
    unsigned places = 1;            ///< scene boxes of the stream: places a mesh is drawn at
    bool hang = false;              ///< r112's book knows the stream
    bool judged = false, fits = false, moving = false;
    float span = 0.0f;              ///< the keys of its slot: top minus base (m), when judged
    std::uint32_t frames = 0;
    int judge = 0;                  ///< the GPU judge: 0 no entry, 1 judging, 2 still, 3 moved
    float dev = 0.0f;               ///< its box growth (m); -2: refused by r112h's rules; -1: no key ever offered
    std::uint64_t judge_draws = 0;
    std::uint8_t moving_why = 0;    ///< bbport (r112n): the hang book's reason for `moving` (BbWindHang::Entry::why_moving)
    std::uint32_t moved_after = 0;  ///< bbport (r112n): and its number (frames counted, or r112h's rule's number)
    std::uint8_t box_only = 0;      ///< bbport (r112p_hang-gpu-palette-lanterns): judged by the GPU box in place of its palette: 1 unread, 2 content moved
};

/// The scene's candidates (a stream with a candidate verdict in the static book), one per stream (`places` boxes counted),
/// nearest first (the camera unread: in the scene's order). `JudgeBook::Find(stream)` gives null or an entry with `state`
/// (Judging, Still, Moved: 0, 1, 2), `dev` and `draws` (BbWindHangStill::BoxBook).
template <class JudgeBook>
[[nodiscard]] inline std::vector<CandInfo> GatherCands(const BoxSet& set, const StaticBook& book, H::Book& heights,
                                                       const JudgeBook& judge) {
    std::vector<CandInfo> out;
    for (const Box& b : set.All()) {
        if (b.stream == 0) {
            continue;
        }
        const Entry* const e = book.Find(b.stream);
        if (e == nullptr || e->why != Why::Ok) {
            continue;
        }
        float dist = -1.0f;
        if (set.camera_ok) {
            const float dx = 0.5f * (b.box[0] + b.box[3]) - set.camera[0];
            const float dy = 0.5f * (b.box[1] + b.box[4]) - set.camera[1];
            const float dz = 0.5f * (b.box[2] + b.box[5]) - set.camera[2];
            dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        const auto same = std::find_if(out.begin(), out.end(),
                                       [&](const CandInfo& c) { return c.stream == b.stream; });
        if (same != out.end()) {
            ++same->places;
            if (dist >= 0.0f && (same->dist < 0.0f || dist < same->dist)) {
                same->dist = dist;
                same->box = b.box;
            }
            continue;
        }
        CandInfo c;
        c.stream = b.stream;
        c.e = *e;
        c.box = b.box;
        c.dist = dist;
        if (const H::Entry* const h = heights.Find(b.stream)) {
            c.hang = true;
            c.judged = h->judged;
            c.fits = h->fits;
            c.moving = h->moving;
            c.frames = h->frames;
            c.span = h->judged ? h->top - h->base : 0.0f;
            c.moving_why = h->why_moving; // bbport (r112n_hang-teleport-camera)
            c.moved_after = h->moved_after;
            c.box_only = h->box_only; // bbport (r112p_hang-gpu-palette-lanterns)
        }
        if (const auto* const j = judge.Find(b.stream)) {
            c.judge = 1 + static_cast<int>(j->state);
            c.dev = j->dev;
            c.judge_draws = static_cast<std::uint64_t>(j->draws);
        }
        out.push_back(c);
    }
    std::stable_sort(out.begin(), out.end(), [](const CandInfo& a, const CandInfo& b) {
        if ((a.dist < 0.0f) != (b.dist < 0.0f)) {
            return b.dist < 0.0f;
        }
        return a.dist < b.dist;
    });
    return out;
}

// bbport (r112n_hang-teleport-camera): why r112's book holds a stream as moving (BbWindHang::Entry::why_moving, the FIRST reason): a
// palette it draws with could not be read, or its palette bytes changed (an animated skeleton, or instances with other palettes
// sharing the stream's address), or the GPU judge saw its box grow, or r112h's rule refused it (`n`: the rule's number, the
// order of BbWindHangActors::Why). A held stream's keys are never measured: that is why its candidate line says "keys span
// not read".
[[nodiscard]] inline std::string MovingWhy(std::uint8_t why, std::uint32_t n) {
    static constexpr const char* const rules[] = {"ok",     "no hunter read", "near the hunter", "a figure (bones)",
                                                  "indoors", "unplaced",       "no palette"};
    char buf[320];
    switch (why) {
    case 1:
        std::snprintf(buf, sizeof(buf),
                      "a palette it draws with could not be read (GPU-written or not mapped); its keys are never measured "
                      "while it is held");
        break;
    case 2:
        std::snprintf(buf, sizeof(buf),
                      "its palette bytes changed after %u frames counted (an animated skeleton, or instances with other "
                      "palettes at the stream's address); its keys are never measured while it is held",
                      n);
        break;
    case 3:
        std::snprintf(buf, sizeof(buf),
                      "the GPU judge saw its box grow; its keys are never measured while it is held");
        break;
    case 4:
        std::snprintf(buf, sizeof(buf), "r112h's rule refused it (%s); its keys are never measured while it is held",
                      n < sizeof(rules) / sizeof(rules[0]) ? rules[n] : "?");
        break;
    case 5: // bbport (r112p_hang-gpu-palette-lanterns): the palette was read and its content differed
        std::snprintf(buf, sizeof(buf),
                      "its palette's content differs from the first draw's (an animated skeleton, or instances of the stream posed "
                      "differently); its keys are never measured while it is held");
        break;
    default:
        std::snprintf(buf, sizeof(buf), "the reason was not recorded");
        break;
    }
    return std::string(buf);
}

enum class CandClass : std::uint8_t { Pushed, Tall, NoJudge, Other };

[[nodiscard]] inline CandClass ClassOf(const CandInfo& c, float tall_m) {
    if (TooTall(c.e, tall_m)) {
        return CandClass::Tall;
    }
    if (c.judge == 3) {
        return CandClass::Other;
    }
    if (c.hang && !c.moving && c.judged && c.fits) {
        return CandClass::Pushed;
    }
    if (!c.hang && c.judge == 0) {
        return CandClass::NoJudge;
    }
    return CandClass::Other;
}

/// Why one candidate is or is not pushed (the state part of its line).
[[nodiscard]] inline std::string CandState(const CandInfo& c, float tall_m, float gain, bool same, float push_now) {
    char buf[320];
    if (TooTall(c.e, tall_m)) {
        std::snprintf(buf, sizeof(buf),
                      "TOO TALL: its scene box is %.2f m, over %.1f m (BB_WIND_HANG_STATIC_TALL): refused, no hang word",
                      double(c.e.height), double(tall_m));
    } else if (c.judge == 3 && c.dev < -1.5f) {
        std::snprintf(buf, sizeof(buf),
                      "refused by r112h's rules (the hunter's gear, a figure, indoors or unplaced): held as moving");
    } else if (c.judge == 3) {
        std::snprintf(buf, sizeof(buf), "the GPU judge found it moving (its box grew %.0f mm): held as moving",
                      double(c.dev) * 1000.0);
    } else if (!c.hang && c.judge == 0) {
        std::snprintf(buf, sizeof(buf),
                      "no GPU-judge entry: no draw of it has taken a sway slot (never drawn through the hang path)");
    } else if (!c.hang && c.judge == 1) {
        std::snprintf(buf, sizeof(buf), "the GPU judge's window is open (judging): its word has no motion yet");
    } else if (!c.hang) {
        std::snprintf(buf, sizeof(buf), "the GPU judge says still, but r112's book has no entry for it");
    } else if (c.moving) {
        std::snprintf(buf, sizeof(buf), "held as moving by r112's book: %s", MovingWhy(c.moving_why, c.moved_after).c_str());
    } else if (!c.judged) {
        std::snprintf(buf, sizeof(buf), "measuring: the keys of its slot are not read yet (a word with no motion)");
    } else if (!c.fits) {
        if (c.span < H::MinExtent) {
            std::snprintf(buf, sizeof(buf), "unfit: its keys span %.2f m, under %.2f m", double(c.span),
                          double(H::MinExtent));
        } else {
            std::snprintf(buf, sizeof(buf), "unfit: its keys span %.2f m, over its limit %.1f m", double(c.span),
                          double(SpanLimitWith(UnionKnob(), tall_m, c.e)));
        }
    } else {
        const float scale = H::HangScale(0.0f, c.span);
        std::snprintf(buf, sizeof(buf), "PUSHED: scale %.2f, its bottom moves %.3f m now (push %.3f m, gain %.2f, %s)",
                      double(scale), double(BottomPush(push_now, gain, scale, same)), double(push_now),
                      double(ClampGain(gain)), same ? "same bottom push for every size" : "scaled by its height");
        if (c.box_only != 0) { // bbport (r112p_hang-gpu-palette-lanterns): the GPU box judged it, not its palette
            const std::size_t used = std::char_traits<char>::length(buf);
            std::snprintf(buf + used, sizeof(buf) - used, " [judged by the GPU box: palette %s]",
                          c.box_only == 2 ? "content moved" : "unread");
        }
    }
    return std::string(buf);
}

/// The lines of r112m every ReportFrames frames: the header (counts, the nearest candidate, the gain, the knobs), then with
/// `lines` (BB_WIND_HANG_FIND=1) one line per candidate, nearest first, at most CandMost.
[[nodiscard]] inline std::vector<std::string> CandLines(const std::vector<CandInfo>& cands, const Stats& s, float tall_m,
                                                        float gain, bool same, float push_now, bool lines, bool proof) {
    std::size_t pushed = 0, tall = 0, nojudge = 0;
    for (const CandInfo& c : cands) {
        const CandClass k = ClassOf(c, tall_m);
        pushed += k == CandClass::Pushed ? 1u : 0u;
        tall += k == CandClass::Tall ? 1u : 0u;
        nojudge += k == CandClass::NoJudge ? 1u : 0u;
    }
    char near_text[48] = "none";
    if (!cands.empty() && cands.front().dist >= 0.0f) {
        std::snprintf(near_text, sizeof(near_text), "%.1f m (vs %08x)", double(cands.front().dist),
                      static_cast<unsigned>(cands.front().e.vs & 0xffffffffull));
    }
    char buf[640];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112m): candidates in the scene now %zu (%zu pushed, %zu too tall, %zu with no GPU-judge "
                  "entry, %zu other); nearest %s; %llu draws refused as too tall (scene box over %.1f m, "
                  "BB_WIND_HANG_STATIC_TALL); static gain %.2f (live), same-bottom rule %d (BB_WIND_HANG_STATIC_SAME), "
                  "table push now %.3f m; proof tint %s (BB_WIND_HANG_PROOF)",
                  cands.size(), pushed, tall, nojudge, cands.size() - pushed - tall - nojudge, near_text,
                  static_cast<unsigned long long>(s.too_tall), double(tall_m), double(ClampGain(gain)), same ? 1 : 0,
                  double(push_now), proof ? "ON" : "off");
    std::vector<std::string> out;
    out.push_back(Cap(buf));
    for (std::size_t i = 0; lines && i < cands.size() && i < CandMost; ++i) {
        const CandInfo& c = cands[i];
        char dist[16], keys[24];
        if (c.dist >= 0.0f) {
            std::snprintf(dist, sizeof(dist), "%.1f", double(c.dist));
        } else {
            std::snprintf(dist, sizeof(dist), "n/a");
        }
        if (c.hang && c.judged) {
            std::snprintf(keys, sizeof(keys), "%.2f m", double(c.span));
        } else {
            std::snprintf(keys, sizeof(keys), "%s", c.moving ? "not read (held)" : "not read"); // bbport (r112n)
        }
        const std::string state = CandState(c, tall_m, gain, same, push_now);
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112m): %c vs %08x (%u place%s, %u verts) dist %s m: scene box %.2f m tall %.2f m "
                      "wide, %.2f m up (middle %.2f %.2f %.2f, ground y %.2f); keys span %s (the union of its places) vs "
                      "scene box %.2f m; %s",
                      char('A' + int(i)), static_cast<unsigned>(c.e.vs & 0xffffffffull), c.places,
                      c.places == 1 ? "" : "s", c.e.verts, dist, double(c.e.height), double(c.e.width), double(c.e.above),
                      double(0.5f * (c.box[0] + c.box[3])), double(0.5f * (c.box[1] + c.box[4])),
                      double(0.5f * (c.box[2] + c.box[5])), double(c.box[1] - c.e.above), keys, double(c.e.height),
                      state.c_str());
        out.push_back(Cap(buf));
    }
    return out;
}

/// The once-line of r112m: why A had no line, the same-bottom push, the tall rule's number, the proof tint.
[[nodiscard]] inline std::string OnceTextM(bool same, bool proof, float tall_m) {
    char buf[1536];
    std::snprintf(buf, sizeof(buf),
                  "Wind sway hang (r112m): the candidate lists of r112j, r112k and r112l keep the newest %zu candidates "
                  "(the oldest, a lantern's streams among them, fall off) and r112's meshes line the 3 tallest: the "
                  "r112m lines list every candidate of the scene nearest first with its state (the candidate lines with "
                  "BB_WIND_HANG_FIND=1); a static candidate's keys span the UNION of the places its mesh is drawn at: its "
                  "length is its scene box, refused over %.1f m (BB_WIND_HANG_STATIC_TALL), counted in 'too tall'; the "
                  "bottom of every static candidate moves by gain x push (a short part as far as a long one: "
                  "BB_WIND_HANG_STATIC_SAME=%d); BB_WIND_HANG_STATIC_GAIN is live where the test tools' knobs are built; "
                  "proof tint (BB_WIND_HANG_PROOF=%d, TOOL): pushed hang draws of the lifter's shaders tint toward cyan",
                  TakenMost, double(tall_m), same ? 1 : 0, proof ? 1 : 0);
    return std::string(buf);
}

/// The survey: a header line and up to ListMost candidate lines (a mesh of the scene of
/// HeightLo-k.height_hi m that hangs by Clearance or is held at the top by a thin box, within ViewMax
/// m of the camera, free ones first, then nearest first). `frame` for the header.
[[nodiscard]] inline std::vector<std::string> SurveyLines(const Knobs& k, const BoxSet& set,
                                                          const Draws& draws,
                                                          const StaticBook& book,
                                                          std::uint64_t frame,
                                                          const Routes* routes = nullptr) {
    struct Cand {
        const Box* b = nullptr;
        Ground g;
        float height = 0.0f, width = 0.0f, dist = -1.0f;
        bool focus = false; // bbport (r112k): its vertex shader is BB_WIND_HANG_FOCUS's
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
        // bbport (r112k_hang-lantern-verdict): the focus shader's meshes are listed first, hanging or not
        const Seen* const noted = draws.Find(b.stream);
        c.focus = k.focus != 0 && noted != nullptr &&
                  static_cast<std::uint32_t>(noted->vs & 0xffffffffull) == k.focus;
        if (c.g.free || c.g.held || c.focus) {
            list.push_back(c);
        }
    }
    std::sort(list.begin(), list.end(), [](const Cand& a, const Cand& b) {
        if (a.focus != b.focus) { // bbport (r112k)
            return a.focus;
        }
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
        char vs[16], ps[16], dist[16], above[16], gap[16], idx[16], scr[24], book_text[64];
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
        // bbport (r112j_hang-static-verts): the screen estimate and the book's verdict with the numbers compared
        const Screen sc = ScreenOf(set, 0.5f * (c.b->box[0] + c.b->box[3]),
                                   0.5f * (c.b->box[1] + c.b->box[4]), 0.5f * (c.b->box[2] + c.b->box[5]));
        if (sc.ok) {
            std::snprintf(scr, sizeof(scr), "%.0f,%.0f", double(sc.x), double(sc.y));
        } else {
            std::snprintf(scr, sizeof(scr), "%s", sc.known ? "behind" : "n/a");
        }
        if (e != nullptr) {
            std::snprintf(book_text, sizeof(book_text), "%s %uv (stream said %uv)", WhyName(e->why),
                          e->verts, e->stream_verts);
        } else {
            std::snprintf(book_text, sizeof(book_text), "-");
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
                      "%u h %.2f w %.2f bottom y %.2f at x %.1f z %.1f dist %s m scr %s: %s%s above %s m, "
                      "support gap %s m, src %c pal %d dyn %d book %s",
                      char('A' + int(i)),
                      static_cast<unsigned long long>(c.b->stream & 0xffffffffull), vs, ps,
                      skinned ? "SKINNED" : "static", idx, c.b->vertices, c.b->triangles,
                      double(c.height), double(c.width), double(c.b->box[1]),
                      double(0.5f * (c.b->box[0] + c.b->box[3])),
                      double(0.5f * (c.b->box[2] + c.b->box[5])), dist, scr, c.g.free ? "FREE" : "held",
                      c.g.stands ? " (post)" : "", above, gap, c.b->src, c.b->palette ? 1 : 0,
                      c.b->dynamic ? 1 : 0, book_text);
        std::string text(buf); // bbport (r112k): the stream's route and focus mark after the line
        text += RouteText(routes, c.b->stream, c.focus);
        text += CutNote(routes, c.b->stream, CutKnob()); // bbport (r112l_hang-discard-lanterns)
        out.push_back(Cap(text.c_str()));
    }
    return out;
}

} // namespace BbWindHangFind
