# r89d_tree-twigs: FEATURE patch (wind work). Off unless BB_WIND=1 with the plant sway's lean (r89c:
# BB_WIND_SWAY above 0, BB_WIND_SWAY_STYLE not "wave"); then ON by default (BB_WIND_TWIGS=1); 0 gives the
# trees of r89c. Applies on top of r89, r89b, r89c, r112, r116 and r117 as they stand in the tree.
#
# The owner, 2026-11-15 23:43, verbatim: "So the trees don't move anymore? I think if the small
# branches on the trees moved slighty due to wind that would look great." Standing motion rule (22:58,
# 23:01): "The sway on the trees either should be removed or very subtle unless it's strong wind. The
# foliage moving should not wave but move in the direction of the wind and it should be not as fast
# unless the wind is really blowing" and "The wave should just be very subtle". r89c made trees x0.07
# at 1.5 m/s (about 5 mm at a 6 m top): still.
#
# WHAT IT DOES. Trunk and main limbs of a tree mesh stay still; its small branches and twigs (the outer,
# upper parts of the crown) stir: r89c's slow downwind lean that breathes with the gust fronts, with its
# subtle wave (0.375 Hz at 1.5 m/s), at TwigRatio (0.30) x BB_WIND_TWIGS of a bush's amplitude. A twig
# tip: at 1.5 m/s 0.6 cm steady and 1.3 cm at the crest of a gust front (gust factor 1; 2.6 cm at the
# strongest gust, 2), at 4 m/s 4.5 cm and 9.2 cm; the fronts pass every 9 m / v (6 s at 1.5 m/s).
#
# WHICH VERTEX (decided per vertex from what the vertex shader has). The recompiler's and the lifter's
# sway code runs in the vertex epilogue on the skinned, world-placed position: it has the vertex's
# world x, y and z, and the mesh's lowest and highest y (r89's base key and r89c's crown key, kept by
# the GPU per base slot). It has no vertex colour or UV weight: nothing in the tree logs the game's tree
# pipelines' vertex inputs, a colour or UV weight would be a new input path in two emitters that nobody
# can compile here, and the game's tree meshes are not known to carry a branch weight. So the weight is
# from the position in the mesh: the GPU also keeps the mesh's world x and z extent (four more
# atomic-minimum keys a base slot, HeightKey/CrownKey of x and z, at TwigAt behind r117's field block),
# and a vertex's twig weight is
#     smoothstep(r^2 / half^2; 0.35^2, 0.85^2) x smoothstep(h / height; 0.30, 0.70),
# r its distance from the box's centre line, half the box's half width (the larger of x and z, at least
# 0.5 m), h its height above the mesh's lowest point, height the mesh's. Near the centre line (trunk,
# main limbs: r under 0.35 half) or low (under 0.3 of the height) it is 0; outer and upper (over 0.85
# half and over 0.7 height) it is 1. Smooth in position: neighbouring vertices of a branch have
# neighbouring weights and the displacement is one world vector field, so a branch moves as one and
# leaf cards follow their twig (a card's vertices differ in weight only as far as the card is large).
#
# WHICH MESHES (FIRST CHECK, by reading; the game run gives the numbers). r89's sway takes only skinned
# draws (a Skeleton-size bone palette, Motion's Kind::Skinned) of pipelines whose pixel shader discards,
# that RtShadow's plant rule (r46b) calls Lone: skinned cut-outs no sun shadow pass draws. A big bare
# tree can be left out of that in three ways: (1) it is drawn by a sun shadow pass (trees cast sun
# shadows: the stream is "Sun", like a character), (2) its pipeline has no cut-out pixel shader (an
# opaque trunk-and-branch mesh: no Sway bit), (3) it has a small skeleton or a palette (Motion's
# SmallSkeleton: never Kind::Skinned). The slot logs of 600 frames at graveyard-blood held 11244 draws of
# sway pipelines with a skeleton, 1416 of them plants (the rest were not plants: sun-drawn skeleton
# draws, characters and, likely, trees). This patch counts all three and extends the classifier for (1)
# and (2):
#   * Rule (1), BB_WIND_TWIGS_REACH 1 (the default): a skinned sway draw whose stream a sun shadow pass
#     also draws (RtShadow::SunSkinned: outdoors only) gets a sway word with TreeBit and a ramp of 0
#     while the CPU judges it (Book, in bbport_wind_twigs.h): the shaders offer its keys; JudgeFrames (8)
#     frames after its slot was taken the keys are read, StillFrames (60) frames later again; it is a
#     TREE when it is at least 3 m tall (and under 60 m, boxes under 80 m), and its box and heights moved
#     at most 0.3 m in between. Then its word gets the ramp (1 s), else it gets no word again (and the
#     hang rule may judge it). A word with TreeBit gives the shaders no bush weight: such a mesh moves
#     only where its height says tree (tau above 0), never as a bush.
#     WHY NOTHING ELSE IS SWEPT IN: walls, lamps, tombs and other props are not Kind::Skinned (no
#     Skeleton-size palette: Motion's role rule) and indoors RtShadow has no sun verdict, so none is a
#     candidate; a character (or its hair, cloth, a boss's cloak) is sun-drawn and skinned but is under
#     3 m (nearly always) and walks (its box moves metres in a second): NotTree. Left: a standing boss
#     of 3 m or more (its cut-outs would move 1-3 cm: harmless), the limit of the rule.
#   * Rule (2), BB_WIND_TWIGS_REACH 2 (not the default): the Sway bit (the sway code in the vertex shader)
#     also goes to every skinned pipeline without a cut-out (SkeletonRead), so opaque tree meshes reach
#     rule (1). Cost: the shaders of every character carry the sway prologue (a word load and a
#     branch a vertex) and are compiled again once; this is why it is off by default.
#   * (3) is not extended (a palette-skinned mesh has no sun verdict in RtShadow, and a small skeleton
#     draw is also a static wall piece: sweeping them in would take walls). The log counts such cut-out
#     draws ("small-skeleton"), so the next step is decided from a number.
# Every tall mesh the plant rule already takes (Lone) uses the twig weight too (r89c's tau).
#
# LOG. Once "Wind twigs (r89d, BB_WIND_TWIGS=1.00, REACH=1): ..." (the tip numbers at 1.5 and 4 m/s) and
# every 600 frame ends "Wind twigs (r89d): trees taken N (meshes: L lone, S sun; tallest ... m), skipped M
# by reason (draws: small-skeleton, opaque, no-sun; meshes: sun-not-still); twig share of tree vertices
# X% (model); tip move at this wind ... cm lean, ... cm gust front". The share is a MODEL (vertices
# spread evenly over a cylinder of the box's half width and the mesh's height: the real share of a
# tree's vertices is not measured), the rest are counts and the GPU's keys read on the CPU at the line.
# The line starts "Wind twigs", not "Wind sway": a slot run's evidence patterns that match "Wind sway"
# do not collect it: grep "^Wind twigs" in the slot's session.log.
#
# OFF. BB_WIND unset: Knob.on false: nothing here runs (every new CPU path starts with a test of the
# once-read knob; no SPIR-V: the emitters emit the twig blocks only `if (twig_on)`; the sway
# region and the shader binary version are as before). BB_WIND_TWIGS=0: the same (trees as r89c, byte
# for byte: the new C++ default arguments are null, the blocks absent). BB_WIND_SWAY_STYLE=wave: off.
# ON: shader code per swayed vertex: 4 loads, about 60 operations, and one branch with 4 atomic
# minimums only where the vertex lies outside the box so far (the first frames of a mesh; a mesh in
# its settled state: none); CPU a map lookup per sun-drawn skinned draw, 2 reads of 6 mapped words
# per judged stream, a census of at most 512 slots every 600 frames; memory: the sway region's buffer
# is padded to word 12304 (49216 bytes, host visible): +35 KB over r112's 14 KB, +16 KB over r117's
# field block alone; no GPU-only memory. Shader binaries: +2000 on the sway binary
# version with the twigs on (cached sway shaders of another setting are built again).
#
# Order: after r89c, r112, r116 and r117 (the tree holds them); revert this one first. Each edit
# anchors on text of r89c or r112 or on a line of the sway code; r117's shelter block (before the
# position store) multiplies the displacement this patch makes, so twigs behind a wall are sheltered
# like every other sway.
#
# Files: new engine/gpu/shim/bbport_wind_twigs.h; edits: bbport_wind_sway.h (the weight rule, TwigIn,
# TwigWeight, Displace's twig arguments, Slots::ForEachInUse), emit_spirv_special.cpp and
# lifter/lift_stage.cpp (the box keys' loads, the weight, the offers), vk_rasterizer_effects.cpp
# (the tree rule, the gain word, the box key reset, WindTwigWord, WindTwigTree, WindTwigSkip,
# WindTwigsReport, the log lines), vk_rasterizer.h/.cpp (declarations, members, one call-site line),
# vk_pipeline_cache.cpp (SwayWanted for REACH 2), vk_pipeline_serialization.cpp (the version offset),
# vk_object_motion.cpp (the buffer length and the keys' start), tests/test_wind_sway.cpp, README.md
# (two rows before BB_WIND_HANG). No host shader, CMake or build.sh file: every host shader build is
# byte for byte as before.
#
# Use: python -I -X utf8 r89d_tree-twigs.py check | apply | revert (root from R89D_ROOT, else
# <tree>). Files keep their line ends. Originals are kept in r89d_backup/ next to this script.
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r89d_backup")
ROOT = os.environ.get("R89D_ROOT") or "<tree>"
G = "engine/gpu/"
S = G + "shadps4/shader_recompiler/"
R = G + "shadps4/video_core/renderer_vulkan/"
L = G + "shim/lifter/"
HEADER = G + "shim/bbport_wind_sway.h"
NEWH = G + "shim/bbport_wind_twigs.h"
EMIT = S + "backend/spirv/emit_spirv_special.cpp"
LIFT = L + "lift_stage.cpp"
EFFECTS = R + "vk_rasterizer_effects.cpp"
RASH = R + "vk_rasterizer.h"
RASC = R + "vk_rasterizer.cpp"
CACHE = R + "vk_pipeline_cache.cpp"
SERIAL = R + "vk_pipeline_serialization.cpp"
MOTION = R + "vk_object_motion.cpp"
TEST = "engine/tests/test_wind_sway.cpp"
README = "README.md"

NEW_FILES = {NEWH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r89d_tree-twigs): the tree twigs of the plant sway (BB_WIND_TWIGS, BB_WIND_TWIGS_REACH).
// Trunk and main limbs of a tree mesh stay still; its small branches (the outer, upper parts of its
// crown) stir: the plant sway's lean (r89c) with a per-vertex weight from the vertex's place in its
// mesh. The weight rule and its constants are in bbport_wind_sway.h (TwigWeight, Displace: the
// shaders' rule in C++); this file has the knob, the key layout, the CPU's judgement of which
// sun-drawn meshes are trees (Book), the counts and the log texts. Header only, pure: engine/tests/
// test_wind_sway.cpp runs it.
//
// How a vertex knows its place: the shaders of a swayed draw (MotionVectors::Sway) already keep, per
// mesh (per base slot of the sway region), the lowest and the highest world y any of its vertices had
// (r89's base key, r89c's crown key). With the twigs on they also keep the world x and z extent of
// the mesh: four more atomic-minimum keys a slot (BbWindSway::HeightKey of the lowest x, CrownKey of
// the highest x, the same for z), at TwigAt in the region's buffer. A vertex's weight is
//   (how far it is from the box's centre line, of the box's half width) x (how high it is in the mesh).
// Why this and not the vertex colour or UV: the vertex shader's inputs are not known without a log
// of the game's tree pipelines (the first game run of this patch gives the counts, the lead decides),
// and a colour or UV weight would be another SPIR-V input path in two emitters; the world position
// is always there after skinning. A mesh with no box yet (or no crown) has weight 0.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <utility>

#include "bbport_wind_sway.h"

namespace BbWindTwigs {
namespace W = BbWindSway;

inline constexpr float TwigsDefault = 1.0f, TwigsMax = 4.0f; ///< BB_WIND_TWIGS
/// The sway word's bit for a mesh that may only be a tree (a sun-drawn skinned mesh): free (PackWord's
/// base slot ends at bit 12, r112's HangBit is bit 13, the ramp starts at bit 16). The shaders give a
/// word with it no bush weight: such a mesh moves only where its height says tree (BbWindSway::
/// TreeLo), so a character's hair or a prop does not sway.
inline constexpr std::uint32_t TreeBit = 1u << 14;
/// The box keys: TwigSlotWords words a base slot (lowest x, highest x, lowest z, highest z), BaseSlots
/// slots, from TwigAt (words from the start of the sway region's buffer). TwigAt lies behind r117's
/// field block (word 4096 + 8 + 64 x 64 = 8200; vk_object_motion.cpp asserts it), so the layout does
/// not depend on that knob.
inline constexpr std::uint32_t TwigSlotWords = 4;
inline constexpr std::uint32_t TwigAt = 8208;
inline constexpr std::uint32_t TwigWords = W::BaseSlots * TwigSlotWords;
inline constexpr std::uint32_t TwigEnd = TwigAt + TwigWords;
inline constexpr std::uint32_t TwigBytes = TwigEnd * 4;
inline constexpr std::uint32_t BinaryAdd = 2000; ///< added to the sway shader binary version when on
/// The CPU's judgement of a sun-drawn skinned stream (a character, a prop or a tree): the keys are
/// first read JudgeFrames frames after its slot was taken (the GPU is done with the frames read) and
/// again StillFrames frames later; a tree is at least TreeMin m tall, whose box and heights moved
/// at most StillTol m between the two reads (a walking character's box moves metres in a second),
/// and not larger than TreeMax m (a stream that spans a level is not a tree).
inline constexpr std::uint64_t JudgeFrames = 8, StillFrames = 60, GiveUpFrames = 600;
inline constexpr float TreeMin = 3.0f, TreeMax = 60.0f, BoxMax = 80.0f, StillTol = 0.3f;
inline constexpr std::size_t BookMost = 4096;      ///< streams known at most
inline constexpr std::uint64_t BookKeep = 600;     ///< frames unseen before one may be forgotten
inline constexpr std::uint32_t TallestShown = 3;   ///< meshes named in the log line

static_assert(TwigAt % 4 == 0 && TwigAt >= 4096 + 8 + 64 * 64, "behind r117's field block");
static_assert((W::PackWord(3, 1, 1023, 255) & TreeBit) == 0, "TreeBit lies outside PackWord's fields");
static_assert((TreeBit & W::WordOn) == 0 && TreeBit != (1u << 13), "TreeBit is not r112's HangBit");
static_assert(JudgeFrames > W::FrameSlots, "the GPU is done with the frames read");
static_assert(TreeMin > W::TreeLo, "a sun-drawn tree is a tree by the shaders' height rule too");

/// BB_WIND_TWIGS (0-TwigsMax, unset or unreadable TwigsDefault; 0: trees as in r89c) and
/// BB_WIND_TWIGS_REACH: 0 only meshes the plant rule takes (cut-outs no sun shadow pass draws), 1
/// (the default) also sun-drawn skinned cut-outs that measure as trees (Book), 2 also the skinned
/// pipelines without a cut-out (the shaders of all skeleton draws then carry the sway code).
struct Knob {
    bool asked = false; ///< BB_WIND_TWIGS above 0
    bool on = false;    ///< and the plant sway's lean is on (BB_WIND=1, BB_WIND_SWAY above 0)
    float twigs = TwigsDefault;
    int reach = 1;
};

/// BB_WIND_TWIGS as a number: 0-TwigsMax, unset, empty or unreadable TwigsDefault.
[[nodiscard]] inline float ParseTwigs(const char* text) {
    return std::clamp(W::ParseNumber(text, TwigsDefault), 0.0f, TwigsMax);
}

[[nodiscard]] inline Knob ParseKnob(const char* twigs, const char* reach, bool sway_on, bool lean) {
    Knob k;
    k.twigs = ParseTwigs(twigs);
    const float r = W::ParseNumber(reach, 1.0f);
    k.reach = r >= 1.5f ? 2 : (r >= 0.5f ? 1 : 0);
    k.asked = k.twigs > 0.0f;
    k.on = k.asked && sway_on && lean;
    return k;
}

/// Read once, at the first use (the pipeline cache's first key, or the motion buffer).
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND_TWIGS"), std::getenv("BB_WIND_TWIGS_REACH"),
                                       W::KnobOnce().on, W::LeanKnobOnce().lean);
    return knob;
}

[[nodiscard]] inline bool On() {
    return KnobOnce().on;
}

[[nodiscard]] inline bool ReachSun() {
    return KnobOnce().on && KnobOnce().reach >= 1;
}

[[nodiscard]] inline bool ReachOpaque() {
    return KnobOnce().on && KnobOnce().reach >= 2;
}

/// The twigs' gain for BB_WIND_TWIGS `twigs` (the value now: the live knobs may change it), written
/// to every view's RippleD.z (the lean's tree weight Ta there, without the twigs): the twig weight is
/// 1 at a twig tip, and a tip's bend is then TwigRatio x BB_WIND_TWIGS times the lean's bend of a bush
/// (the lean's D is of the wind speed, so the twigs' is).
[[nodiscard]] inline float Gain(float twigs) {
    return W::TwigRatio * twigs;
}

/// The sway region's buffer length with the box keys (only when on).
[[nodiscard]] inline std::uint32_t BufferBytes(std::uint32_t region_bytes) {
    return On() ? std::max(region_bytes, TwigBytes) : region_bytes;
}

/// The box keys at ResetKey (the buffer's words up to TwigEnd, when on), called once after the
/// region's words were zeroed.
inline void InitWords(std::uint32_t* sway_words) {
    if (On() && sway_words != nullptr) {
        for (std::uint32_t i = 0; i < TwigWords; ++i) {
            sway_words[TwigAt + i] = W::ResetKey;
        }
    }
}

/// A slot's four box keys back to ResetKey (the slot goes to another stream, or another size).
inline void ResetSlot(std::uint32_t* words, std::uint32_t slot) {
    if (On() && slot < W::BaseSlots) {
        for (std::uint32_t i = 0; i < TwigSlotWords; ++i) {
            words[TwigAt + slot * TwigSlotWords + i] = W::ResetKey;
        }
    }
}

/// Added to the serialized sway shader binary version: 0 off (the shader is as before).
[[nodiscard]] inline std::uint32_t BinaryOffset() {
    return On() ? BinaryAdd : 0u;
}

/// Whether a saved shader's version is a sway or hang version with any of the optional offsets
/// (r117's `shelter_add`, this patch's BinaryAdd): the load then compares it with the one expected.
[[nodiscard]] inline bool KnownVersion(std::uint32_t version, std::uint32_t sway, std::uint32_t hang,
                                       std::uint32_t shelter_add) {
    for (const std::uint32_t a : {0u, shelter_add}) {
        for (const std::uint32_t b : {0u, BinaryAdd}) {
            if (version == sway + a + b || version == hang + a + b) {
                return true;
            }
        }
    }
    return false;
}

/// A sun-drawn stream's sway word: a ramp of 0 while it is judged (the shaders still offer its
/// keys), its ramp once it is a tree; both with TreeBit.
[[nodiscard]] constexpr std::uint32_t TreeWord(std::uint32_t frame_slot, std::uint32_t view,
                                               std::uint32_t slot, std::uint32_t ramp) {
    return W::PackWord(frame_slot, view, slot, ramp) | TreeBit;
}

[[nodiscard]] constexpr bool IsTreeWord(std::uint32_t word) {
    return (word & W::WordOn) != 0 && (word & TreeBit) != 0;
}

/// The keys of a slot as the GPU holds them.
struct Keys {
    std::uint32_t base = W::ResetKey, crown = W::ResetKey;
    std::array<std::uint32_t, 4> box{W::ResetKey, W::ResetKey, W::ResetKey, W::ResetKey};
};

/// The sway words of the region, `slot`'s keys. Read through a volatile pointer: the GPU writes
/// them (host visible memory; the caller has waited JudgeFrames frames).
[[nodiscard]] inline Keys ReadKeys(const std::uint32_t* words, std::uint32_t slot) {
    const volatile std::uint32_t* const v = words;
    Keys k;
    k.base = v[W::BaseAt + slot];
    k.crown = v[W::CrownAt + slot];
    for (std::uint32_t i = 0; i < TwigSlotWords; ++i) {
        k.box[i] = v[TwigAt + slot * TwigSlotWords + i];
    }
    return k;
}

/// A mesh's measured size: lowest and highest y, lowest and highest x and z (m); ok when every key
/// was offered (a mesh no vertex has been seen of has ResetKey keys).
struct Measure {
    float base = 0.0f, crown = 0.0f, x_lo = 0.0f, x_hi = 0.0f, z_lo = 0.0f, z_hi = 0.0f;
    bool ok = false;
};

[[nodiscard]] inline Measure MeasureOf(const Keys& k) {
    Measure m;
    m.ok = k.base != W::ResetKey && k.crown != W::ResetKey && k.box[0] != W::ResetKey &&
           k.box[1] != W::ResetKey && k.box[2] != W::ResetKey && k.box[3] != W::ResetKey;
    if (m.ok) {
        m.base = W::KeyHeight(k.base);
        m.crown = W::KeyCrown(k.crown);
        m.x_lo = W::KeyHeight(k.box[0]);
        m.x_hi = W::KeyCrown(k.box[1]);
        m.z_lo = W::KeyHeight(k.box[2]);
        m.z_hi = W::KeyCrown(k.box[3]);
    }
    return m;
}

/// The largest change of any of the six numbers between two measures.
[[nodiscard]] inline float Moved(const Measure& a, const Measure& b) {
    return std::max({std::fabs(a.base - b.base), std::fabs(a.crown - b.crown),
                     std::fabs(a.x_lo - b.x_lo), std::fabs(a.x_hi - b.x_hi),
                     std::fabs(a.z_lo - b.z_lo), std::fabs(a.z_hi - b.z_hi)});
}

enum class Verdict : std::uint8_t { Waiting, Tree, NotTree };

/// What the CPU knows of one sun-drawn skinned stream (by its position stream's address).
struct Entry {
    std::uint32_t size = 0;                ///< the stream's bytes (another size: another mesh)
    std::uint32_t slot = 0xffffffffu;      ///< the base slot it was measured in
    std::uint64_t first = 0;               ///< frame its slot was taken (or the measuring began)
    std::uint64_t snap_at = 0, seen = 0;   ///< frame of the first read; frame last drawn
    bool snapped = false;
    Measure snap;
    Verdict verdict = Verdict::Waiting;
    float height = 0.0f;                   ///< the mesh's height at the verdict
    bool ramping = false;                  ///< a tree's ramp has begun
    double tree_since = 0.0;               ///< wind time of its first word as a tree
};

class Book {
public:
    /// The stream's entry for a draw this frame in `slot` (new, or started again when the slot, the
    /// size or the slot's keys (`reset`) changed).
    Entry& Touch(std::uint64_t stream, std::uint32_t size, std::uint32_t slot, bool reset,
                 std::uint64_t frame) {
        if (entries.size() >= BookMost && entries.find(stream) == entries.end()) {
            std::erase_if(entries, [&](const auto& item) { return item.second.seen + BookKeep < frame; });
            if (entries.size() >= BookMost) {
                entries.clear();
            }
        }
        Entry& e = entries[stream];
        if (reset || e.slot != slot || e.size != size) {
            e = Entry{};
            e.size = size;
            e.slot = slot;
            e.first = frame;
        }
        e.seen = frame;
        return e;
    }

    [[nodiscard]] const Entry* Find(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found == entries.end() ? nullptr : &found->second;
    }

    [[nodiscard]] std::size_t Size() const {
        return entries.size();
    }

    template <class F>
    void ForEach(F&& fn) const {
        for (const auto& item : entries) {
            fn(item.first, item.second);
        }
    }

private:
    std::unordered_map<std::uint64_t, Entry> entries;
};

/// The verdict on a stream: Waiting until two reads of its keys StillFrames frames apart are made
/// (the first JudgeFrames frames after the slot was taken); then Tree or NotTree for good (until the
/// slot, the size or the keys are reset). `words`: the sway region's words. At most one read of the
/// mapped memory per stream per frame, and none once judged.
[[nodiscard]] inline Verdict Judge(Entry& e, const std::uint32_t* words, std::uint64_t frame) {
    if (e.verdict != Verdict::Waiting) {
        return e.verdict;
    }
    if (frame < e.first + JudgeFrames || (e.snapped && frame < e.snap_at + StillFrames)) {
        return Verdict::Waiting;
    }
    const Measure m = MeasureOf(ReadKeys(words, e.slot));
    if (!m.ok) {
        if (frame >= e.first + GiveUpFrames) {
            e.verdict = Verdict::NotTree;
        }
        return e.verdict;
    }
    if (!e.snapped) {
        e.snapped = true;
        e.snap = m;
        e.snap_at = frame;
        return Verdict::Waiting;
    }
    e.height = m.crown - m.base;
    const bool sane = e.height <= TreeMax && m.x_hi - m.x_lo <= BoxMax && m.z_hi - m.z_lo <= BoxMax;
    e.verdict = sane && e.height >= TreeMin && Moved(e.snap, m) <= StillTol ? Verdict::Tree
                                                                             : Verdict::NotTree;
    return e.verdict;
}

/// The ramp byte (0-255) of a tree's word: from the verdict (the first call after it) W::RampTime of
/// wind time `now` to full, never above `slot_ramp` (the slot's own, 255 by the time of a verdict).
[[nodiscard]] inline std::uint32_t TreeRamp(Entry& e, double now, std::uint32_t slot_ramp) {
    if (!e.ramping) {
        e.ramping = true;
        e.tree_since = now;
    }
    return std::min(slot_ramp, W::RampByte((now - e.tree_since) / W::RampTime));
}

/// Counts for the log's line every W::ReportFrames frames.
struct Stats {
    std::uint64_t tree_draws = 0; ///< sun-drawn draws given the twigs (a tree's)
    std::uint64_t measuring = 0;  ///< sun-drawn draws still being judged (ramp 0)
    std::uint64_t not_tree = 0;   ///< sun-drawn draws of streams judged not trees (no word)
    std::uint64_t no_sun = 0;     ///< skinned sway draws neither plant nor sun-drawn
    std::uint64_t small = 0;      ///< cut-out draws with a small skeleton or a palette (never Skinned)
    std::uint64_t opaque = 0;     ///< skinned draws of pipelines without a cut-out (no sway code)
};

/// The meshes in use at a report: tall (above W::TreeLo) ones by who takes them.
struct Census {
    std::uint32_t lone = 0, sun = 0, sun_not = 0;
    std::array<float, TallestShown> tallest{};

    void Tall(float height) {
        for (std::uint32_t i = 0; i < TallestShown; ++i) {
            if (height > tallest[i]) {
                std::swap(height, tallest[i]);
            }
        }
    }
};

/// The share of a mesh's vertices that move by more than half a twig tip, as a MODEL: vertices
/// spread evenly over a cylinder of the box's half width (r^2 / half^2 even in 0-1) and over the
/// mesh's height (even in 0-1). The real mesh's share is not measured.
[[nodiscard]] inline float ModelShare() {
    constexpr int n = 200;
    int strong = 0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            const float r2 = (float(i) + 0.5f) / float(n), f = (float(j) + 0.5f) / float(n);
            if (W::Smooth01(r2, W::TwigRad2Lo, W::TwigRad2Inv) *
                    W::Smooth01(f, W::TwigHeightLo, W::TwigHeightInv) >=
                0.5f) {
                ++strong;
            }
        }
    }
    return float(strong) / float(n * n);
}

/// A twig tip's move at wind speed `speed` (m/s), BB_WIND_SWAY `scale`, BB_WIND_SWAY_WAVE `wave`,
/// BB_WIND_TWIGS `twigs`: the steady lean (a gust factor and a front envelope of 1) and the peak in
/// a gust front (envelope 2, wave at its crest), both at a gust factor of 1, in m.
struct Tip {
    float lean = 0.0f, front = 0.0f;
};

[[nodiscard]] inline Tip TipAt(float speed, float scale, float wave, float twigs, bool show) {
    const W::LeanCurve c = W::LeanAt(speed, scale, wave, show);
    const float gain = W::TwigRatio * twigs;
    Tip t;
    t.lean = gain * (c.rest + c.bend);
    t.front = gain * (c.rest + c.bend + c.bend * (W::EnvScale - 1.0f) + c.along * W::EnvScale);
    return t;
}

/// The once line (Rasterizer::WindSwayFrameEnd), under 300 characters.
inline void OnceText(const Knob& k, float scale, float wave, char* out, std::size_t size) {
    const Tip d = TipAt(BbWind::DefaultSpeed, scale, wave, k.twigs, false);
    const Tip s = TipAt(BbWind::MaxSpeed, scale, wave, k.twigs, false);
    std::snprintf(out, size,
                  "Wind twigs (r89d, BB_WIND_TWIGS=%.2f, REACH=%d): small branches of tree meshes "
                  "(over %.0f m) stir, trunk and limbs still; tip %.1f/%.1f cm (lean/gust front) "
                  "at 1.5 m/s, %.1f/%.1f cm at 4 m/s, gust x1",
                  double(k.twigs), k.reach, double(W::TreeLo), double(d.lean * 100.0f),
                  double(d.front * 100.0f), double(s.lean * 100.0f), double(s.front * 100.0f));
}

/// The line every W::ReportFrames frames: "Wind twigs (r89d): trees taken N (meshes ...), skipped M
/// by reason ..., twig share of tree vertices ..., tip move at this wind ... cm".
inline void LineText(const Census& census, const Stats& st, const BbWind::Snapshot& wind,
                     const Knob& k, float scale, float wave, char* out, std::size_t size) {
    char tall[48];
    tall[0] = 0;
    for (std::uint32_t i = 0; i < TallestShown; ++i) {
        if (census.tallest[i] > 0.0f) {
            std::snprintf(tall + std::strlen(tall), sizeof(tall) - std::strlen(tall), "%s%.1f",
                          i == 0 ? "" : "/", double(census.tallest[i]));
        }
    }
    if (tall[0] == 0) {
        std::snprintf(tall, sizeof(tall), "none");
    }
    const float speed = std::isfinite(wind.speed) ? std::max(wind.speed, 0.0f) : 0.0f;
    const Tip tip = TipAt(speed, scale, wave, k.twigs, false);
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const std::uint64_t skipped = st.small + st.opaque + st.no_sun + census.sun_not;
    std::snprintf(out, size,
                  "Wind twigs (r89d): trees taken %u (meshes: %u lone, %u sun; tallest %s m), "
                  "skipped %llu by reason (draws: small-skeleton %llu, opaque %llu, no-sun %llu; "
                  "meshes: sun-not-still %u); twig share of tree vertices %.0f%% (model); tip move "
                  "at %.2f m/s: %.1f cm lean, %.1f cm gust front",
                  census.lone + census.sun, census.lone, census.sun, tall, n(skipped), n(st.small),
                  n(st.opaque), n(st.no_sun), census.sun_not, double(ModelShare() * 100.0f),
                  double(speed), double(tip.lean * 100.0f), double(tip.front * 100.0f));
}

} // namespace BbWindTwigs
'''}

# ---------------------------------------------------------------- bbport_wind_sway.h
H_BLOCK = r'''// bbport (r89d_tree-twigs): the twigs (bbport_wind_twigs.h has the knob, the box keys and the
// judgement of sun-drawn meshes). With BB_WIND_TWIGS on a tall mesh (the lean's tree rule: tau above
// 0) takes, in place of the top half's weight, a twig weight from where the vertex lies in the mesh's
// box:
//   wt = Gain x smoothstep(TwigRad2Lo, TwigRad2Hi; r^2 / half^2) x smoothstep(TwigHeightLo,
//        TwigHeightHi; h / height),
// r the vertex's distance from the box's centre line, half the box's half width (the larger of the x
// and z extents, at least TwigHalfFloor), h its height above the mesh's lowest point, height the
// mesh's, Gain (the view's RippleD.z, written by the CPU) = TwigRatio x BB_WIND_TWIGS. The trunk and
// the main limbs (near the centre line, or low) stay still; the outer, upper parts move by TwigRatio
// of a bush's lean at most. The weights are smooth in position, so a branch moves as one. A word
// with TreeBit (a sun-drawn stream: a tree, or a character) has no bush weight.
inline constexpr float TwigRatio = 0.30f;
inline constexpr float TwigRadLo = 0.35f, TwigRadHi = 0.85f; ///< of the box's half width
inline constexpr float TwigRad2Lo = TwigRadLo * TwigRadLo, TwigRad2Hi = TwigRadHi * TwigRadHi;
inline constexpr float TwigRad2Inv = 1.0f / (TwigRad2Hi - TwigRad2Lo);
inline constexpr float TwigHeightLo = 0.30f, TwigHeightHi = 0.70f; ///< of the mesh's height
inline constexpr float TwigHeightInv = 1.0f / (TwigHeightHi - TwigHeightLo);
inline constexpr float TwigHalfFloor = 0.5f; ///< m
static_assert(TwigRadLo < TwigRadHi && TwigHeightLo < TwigHeightHi && TwigRatio < 1.0f);

/// smoothstep of x between lo and lo + 1 / inv (the shaders' rule).
[[nodiscard]] inline float Smooth01(float x, float lo, float inv) {
    const float c = std::clamp((x - lo) * inv, 0.0f, 1.0f);
    return c * c * (3.0f - 2.0f * c);
}

/// What a vertex knows of its mesh's box: the four keys (HeightKey of the lowest x, CrownKey of the
/// highest x, the same for z; ResetKey: none yet) and the word's TreeBit.
struct TwigIn {
    std::array<std::uint32_t, 4> keys{ResetKey, ResetKey, ResetKey, ResetKey};
    bool tree_only = false;
};

/// The twig weight (before the lean's gust and front) at world x `ax`, z `az`, height `h` above the
/// mesh's lowest point, of a mesh `mesh` m tall with box keys `keys`; `view` holds the gain.
[[nodiscard]] inline float TwigWeight(const float* view, float ax, float az, float h, float mesh,
                                      const std::array<std::uint32_t, 4>& keys) {
    const float x_lo = KeyHeight(keys[0]), x_hi = KeyCrown(keys[1]);
    const float z_lo = KeyHeight(keys[2]), z_hi = KeyCrown(keys[3]);
    const float cx = 0.5f * (x_lo + x_hi), cz = 0.5f * (z_lo + z_hi);
    const float half_w = std::max(0.5f * std::max(x_hi - x_lo, z_hi - z_lo), TwigHalfFloor);
    const float ex = ax - cx, ez = az - cz;
    const float r2 = (ex * ex + ez * ez) / (half_w * half_w);
    const float wr = Smooth01(r2, TwigRad2Lo, TwigRad2Inv);
    const float wh = Smooth01(h / std::max(mesh, MeshFloor), TwigHeightLo, TwigHeightInv);
    return view[RippleD + 2] * (wr * wh);
}

'''
H_DOC = "/// What the shaders do to one vertex: `view` its ViewWords floats, `clip` the clip position,\n"
H_SIG_OLD = "                                                   std::uint32_t* key_crown = nullptr) {\n"
H_SIG_NEW = (
    "                                                   std::uint32_t* key_crown = nullptr,\n"
    "                                                   const TwigIn* twig = nullptr, // r89d\n"
    "                                                   std::array<std::uint32_t, 4>* twig_offer = nullptr) {\n")
H_FIN_OLD = ("    const bool fin = std::fabs(h) + std::fabs(rx) + std::fabs(rz) < FiniteMost;\n"
             "    if (!fin) {\n")
H_FIN_NEW = (
    "    const bool fin = std::fabs(h) + std::fabs(rx) + std::fabs(rz) < FiniteMost;\n"
    "    // bbport (r89d_tree-twigs): the keys the vertex offers its mesh's box (`twig_offer`: the GPU\n"
    "    // keeps the smaller of each and the stored one)\n"
    "    if (twig_offer != nullptr) {\n"
    "        const float ax = view[WindE + 2] + rx, az = view[WindE + 3] + rz;\n"
    "        *twig_offer = fin ? std::array<std::uint32_t, 4>{HeightKey(ax), CrownKey(ax), HeightKey(az),\n"
    "                                                          CrownKey(az)}\n"
    "                          : std::array<std::uint32_t, 4>{ResetKey, ResetKey, ResetKey, ResetKey};\n"
    "    }\n"
    "    if (!fin) {\n")
H_W_OLD = "    const float w = (wb + tau * lean * (wt - wb)) * ramp;\n"
H_W_NEW = (
    "    // bbport (r89d_tree-twigs): with `twig` (BB_WIND_TWIGS on) a tall mesh takes the twig weight in\n"
    "    // place of the top half's, and a mesh that may only be a tree (TreeBit) has no bush weight\n"
    "    float wt_use = wt, wb_use = wb;\n"
    "    if (twig != nullptr) {\n"
    "        wt_use = tau > 0.0f ? TwigWeight(view, view[WindE + 2] + rx, view[WindE + 3] + rz, h, mesh,\n"
    "                                         twig->keys)\n"
    "                            : 0.0f;\n"
    "        wb_use = twig->tree_only ? 0.0f : wb;\n"
    "    }\n"
    "    const float w = (wb_use + tau * lean * (wt_use - wb_use)) * ramp;\n")
H_SLOTS_OLD = "        return n;\n    }\n\nprivate:\n    struct Slot {\n"
H_SLOTS_NEW = (
    "        return n;\n    }\n\n"
    "    /// bbport (r89d_tree-twigs): fn(slot, stream, size) for each slot drawn within the last\n"
    "    /// ReuseFrames frames.\n"
    "    template <class F>\n"
    "    void ForEachInUse(std::uint64_t frame, F&& fn) const {\n"
    "        for (std::uint32_t i = 0; i < PlantSlots; ++i) {\n"
    "            const Slot& slot = slots[i];\n"
    "            if (slot.stream != 0 && slot.last + ReuseFrames >= frame) {\n"
    "                fn(i, slot.stream, slot.size);\n"
    "            }\n"
    "        }\n"
    "    }\n\n"
    "private:\n    struct Slot {\n")

# ---------------------------------------------------------------- the recompiler (EmitVertexSway)
E_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
E_INC_NEW = E_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
E_CROWN_OLD = "    const Id crown = ctx.OpLoad(u32_type, crown_ptr, spv::MemoryAccessMask::Aligned, 4u);\n"
E_A = r'''    // bbport (r89d_tree-twigs): with BB_WIND_TWIGS on (read once; such sway code has its own shader
    // cache version) the mesh's box keys (BbWindTwigs::TwigAt: lowest x, highest x, lowest z, highest
    // z, four words a base slot): loaded here, offered to below. Off: nothing is emitted.
    const bool twig_on = BbWindTwigs::On();
    Id twig_addr{}, tk_x0{}, tk_x1{}, tk_z0{}, tk_z1{};
    const auto twig_word = [&](u64 bytes) {
        return ctx.OpConvertUToPtr(u32_ptr, at(twig_addr, bytes));
    };
    if (twig_on) {
        twig_addr = scaled(at(region, u64(BbWindTwigs::TwigAt) * 4u), field(3u, 10u), 16u);
        const auto twig_key = [&](u64 bytes) {
            return ctx.OpLoad(u32_type, twig_word(bytes), spv::MemoryAccessMask::Aligned, 4u);
        };
        tk_x0 = twig_key(0u);
        tk_x1 = twig_key(4u);
        tk_z0 = twig_key(8u);
        tk_z1 = twig_key(12u);
    }
'''
E_W_OLD = "    const Id w = mul(add(wb, mul(mul(tau, lean), sub(wt, wb))), ramp);\n"
E_W_NEW = r'''    // bbport (r89d_tree-twigs): with the twigs a tall mesh (tau above 0) takes the twig weight
    // (BbWindSway::TwigWeight: the vertex's distance from the box's centre line and its height in the
    // mesh) in place of the top half's, and a word with TreeBit has no bush weight (BbWindSway::Displace)
    Id wt_use = wt, wb_use = wb;
    if (twig_on) {
        const auto smooth01 = [&](Id x, float lo, float inv) {
            const Id c = ctx.OpFClamp(f32_type, mul(sub(x, f(lo)), f(inv)), zero, f(1.0f));
            return mul(mul(c, c), sub(f(3.0f), mul(f(2.0f), c)));
        };
        const auto key_lo = [&](Id key) { return sub(ctx.OpBitcast(f32_type, key), f(W::HeightBias)); };
        const auto key_hi = [&](Id key) { return sub(f(W::HeightBias), ctx.OpBitcast(f32_type, key)); };
        const Id x_lo = key_lo(tk_x0);
        const Id x_hi = key_hi(tk_x1);
        const Id z_lo = key_lo(tk_z0);
        const Id z_hi = key_hi(tk_z1);
        const Id ex = sub(add(comp(wind_e, 2u), rx), mul(f(0.5f), add(x_lo, x_hi)));
        const Id ez = sub(add(comp(wind_e, 3u), rz), mul(f(0.5f), add(z_lo, z_hi)));
        const Id half_w = ctx.OpFMax(
            f32_type, mul(f(0.5f), ctx.OpFMax(f32_type, sub(x_hi, x_lo), sub(z_hi, z_lo))),
            f(W::TwigHalfFloor));
        const Id r2 = ctx.OpFDiv(f32_type, add(mul(ex, ex), mul(ez, ez)), mul(half_w, half_w));
        const Id wr = smooth01(r2, W::TwigRad2Lo, W::TwigRad2Inv);
        const Id wh = smooth01(ctx.OpFDiv(f32_type, h, ctx.OpFMax(f32_type, mesh, f(W::MeshFloor))),
                             W::TwigHeightLo, W::TwigHeightInv);
        const Id twig = mul(comp(lean_d, 2u), mul(wr, wh));
        wt_use = ctx.OpSelect(f32_type, ctx.OpFOrdGreaterThan(bool_type, tau, zero), twig, zero);
        wb_use = ctx.OpSelect(f32_type,
                              ctx.OpINotEqual(bool_type,
                                              ctx.OpBitwiseAnd(u32_type, word,
                                                               ctx.ConstU32(BbWindTwigs::TreeBit)),
                                              ctx.u32_zero_value),
                              zero, wb);
    }
    const Id w = mul(add(wb_use, mul(mul(tau, lean), sub(wt_use, wb_use))), ramp);
'''
E_END_OLD = "    ctx.AddLabel(crown_merge);\n    ctx.OpBranch(sway_merge);\n"
E_C = r'''    if (twig_on) { // bbport (r89d_tree-twigs): the vertex offers its world x and z to the box keys
        const Id ax = add(comp(wind_e, 2u), rx);
        const Id az = add(comp(wind_e, 3u), rz);
        const auto offer_key = [&](Id value) {
            return ctx.OpBitcast(u32_type, ctx.OpFMax(f32_type, value, zero));
        };
        const Id k_x0 = offer_key(add(ax, f(W::HeightBias)));
        const Id k_x1 = offer_key(sub(f(W::HeightBias), ax));
        const Id k_z0 = offer_key(add(az, f(W::HeightBias)));
        const Id k_z1 = offer_key(sub(f(W::HeightBias), az));
        const auto lower = [&](Id key, Id stored_key) {
            return ctx.OpULessThan(bool_type, key, stored_key);
        };
        const auto either = [&](Id a, Id b) { return ctx.OpLogicalOr(bool_type, a, b); };
        const Id offer_twig = ctx.OpLogicalAnd(
            bool_type, fin,
            either(either(lower(k_x0, tk_x0), lower(k_x1, tk_x1)),
                   either(lower(k_z0, tk_z0), lower(k_z1, tk_z1))));
        const Id twig_label = ctx.OpLabel();
        const Id twig_merge = ctx.OpLabel();
        ctx.OpSelectionMerge(twig_merge, spv::SelectionControlMask::MaskNone);
        ctx.OpBranchConditional(offer_twig, twig_label, twig_merge);
        ctx.AddLabel(twig_label);
        const std::array<Id, 4> offered{k_x0, k_x1, k_z0, k_z1};
        for (u32 k = 0; k < 4; ++k) {
            ctx.OpAtomicUMin(u32_type, twig_word(u64(k) * 4u),
                             ctx.ConstU32(static_cast<u32>(spv::Scope::Device)), ctx.u32_zero_value,
                             offered[k]);
        }
        ctx.OpBranch(twig_merge);
        ctx.AddLabel(twig_merge);
    }
'''

# ---------------------------------------------------------------- the lifter (Lift_::VertexSway)
L_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
L_INC_NEW = L_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
L_CROWN_OLD = "    const u32 crown = Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {crown_ptr, aligned, 4}, 6);\n"
L_A = r'''    // bbport (r89d_tree-twigs): the mesh's box keys (BbWindTwigs::TwigAt: lowest x, highest x, lowest z,
    // highest z, four words a base slot), as the recompiler's EmitVertexSway. Off: nothing is emitted.
    const bool twig_on = BbWindTwigs::On();
    u32 twig_addr = 0, tk_x0 = 0, tk_x1 = 0, tk_z0 = 0, tk_z1 = 0;
    const auto twig_word = [&](u64 bytes) {
        return Emit(O(spv::Op::OpConvertUToPtr), ptr_u32, Ty::None, {at(twig_addr, bytes)});
    };
    if (twig_on) {
        twig_addr = scaled(at(region, u64(BbWindTwigs::TwigAt) * 4u), field(3, 10), 16);
        const auto twig_key = [&](u64 bytes) {
            return Emit(O(spv::Op::OpLoad), t_u32, Ty::U32, {twig_word(bytes), aligned, 4}, 6);
        };
        tk_x0 = twig_key(0u);
        tk_x1 = twig_key(4u);
        tk_z0 = twig_key(8u);
        tk_z1 = twig_key(12u);
    }
'''
L_W_OLD = "    const u32 w = FMul(FAdd(wb, FMul(FMul(tau, lean), FSub(wt, wb))), ramp);\n"
L_W_NEW = r'''    // bbport (r89d_tree-twigs): the twig weight in place of the top half's for a tall mesh, no bush weight
    // for a word with TreeBit (as the recompiler's EmitVertexSway; BbWindSway::Displace in C++)
    u32 wt_use = wt, wb_use = wb;
    if (twig_on) {
        const auto smooth01 = [&](u32 x, float lo, float inv) {
            const u32 c = clamp_f(FMul(FSub(x, CF(lo)), CF(inv)), zero, CF(1.0f));
            return FMul(FMul(c, c), FSub(CF(3.0f), FMul(CF(2.0f), c)));
        };
        const auto key_lo = [&](u32 key) { return FSub(Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {key}), CF(W::HeightBias)); };
        const auto key_hi = [&](u32 key) { return FSub(CF(W::HeightBias), Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {key})); };
        const u32 x_lo = key_lo(tk_x0);
        const u32 x_hi = key_hi(tk_x1);
        const u32 z_lo = key_lo(tk_z0);
        const u32 z_hi = key_hi(tk_z1);
        const u32 ex = FSub(FAdd(comp(wind_e, 2), rx), FMul(CF(0.5f), FAdd(x_lo, x_hi)));
        const u32 ez = FSub(FAdd(comp(wind_e, 3), rz), FMul(CF(0.5f), FAdd(z_lo, z_hi)));
        const u32 half_w = Ext(GLSLstd450FMax, t_f32, Ty::F32, {FMul(CF(0.5f), Ext(GLSLstd450FMax, t_f32, Ty::F32, {FSub(x_hi, x_lo), FSub(z_hi, z_lo)})), CF(W::TwigHalfFloor)});
        const u32 r2 = Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {FAdd(FMul(ex, ex), FMul(ez, ez)), FMul(half_w, half_w)});
        const u32 wr = smooth01(r2, W::TwigRad2Lo, W::TwigRad2Inv);
        const u32 wh = smooth01(Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {h, mesh_floor}), W::TwigHeightLo, W::TwigHeightInv);
        const u32 twig = FMul(comp(lean_d, 2), FMul(wr, wh));
        wt_use = Select(FCmp(O(spv::Op::OpFOrdGreaterThan), tau, zero), twig, zero);
        wb_use = Select(ICmp(O(spv::Op::OpINotEqual), IOp(O(spv::Op::OpBitwiseAnd), word, CU(BbWindTwigs::TreeBit)), CU(0)), zero, wb);
    }
    const u32 w = FMul(FAdd(wb_use, FMul(FMul(tau, lean), FSub(wt_use, wb_use))), ramp);
'''
L_END_OLD = "    Open(crown_merge);\n    EmitVoid(O(spv::Op::OpBranch), {sway_merge});\n"
L_C = r'''    if (twig_on) { // bbport (r89d_tree-twigs): the vertex offers its world x and z to the box keys
        const u32 ax = FAdd(comp(wind_e, 2), rx);
        const u32 az = FAdd(comp(wind_e, 3), rz);
        const auto offer_key = [&](u32 value) {
            return Emit(O(spv::Op::OpBitcast), t_u32, Ty::U32, {Ext(GLSLstd450FMax, t_f32, Ty::F32, {value, zero})});
        };
        const u32 k_x0 = offer_key(FAdd(ax, CF(W::HeightBias)));
        const u32 k_x1 = offer_key(FSub(CF(W::HeightBias), ax));
        const u32 k_z0 = offer_key(FAdd(az, CF(W::HeightBias)));
        const u32 k_z1 = offer_key(FSub(CF(W::HeightBias), az));
        const auto lower = [&](u32 key, u32 stored_key) { return ICmp(O(spv::Op::OpULessThan), key, stored_key); };
        const auto either = [&](u32 a, u32 b) { return Emit(O(spv::Op::OpLogicalOr), t_bool, Ty::Bool, {a, b}); };
        const u32 offer_twig = Emit(O(spv::Op::OpLogicalAnd), t_bool, Ty::Bool,
                                    {fin, either(either(lower(k_x0, tk_x0), lower(k_x1, tk_x1)), either(lower(k_z0, tk_z0), lower(k_z1, tk_z1)))});
        const u32 twig_label = m.NewId();
        const u32 twig_merge = m.NewId();
        EmitVoid(O(spv::Op::OpSelectionMerge), {twig_merge, 0}, 2);
        EmitVoid(O(spv::Op::OpBranchConditional), {offer_twig, twig_label, twig_merge});
        Open(twig_label);
        const std::array<u32, 4> offered{k_x0, k_x1, k_z0, k_z1};
        for (u32 k = 0; k < 4; ++k) {
            const u32 prev_twig = Emit(O(spv::Op::OpAtomicUMin), t_u32, Ty::U32, {twig_word(u64(k) * 4u), CU(u32(spv::Scope::Device)), CU(0), offered[k]});
            nodes[m.NodeOf(prev_twig)].effect = true;
        }
        EmitVoid(O(spv::Op::OpBranch), {twig_merge});
        Open(twig_merge);
    }
'''

# ---------------------------------------------------------------- vk_rasterizer_effects.cpp
F_TREE_OLD = ("    const bool hang = !plant && WindHangVerdict(pipeline, positions, positions_size);\n"
              "    if (!plant && !hang) {\n")
F_TREE_NEW = (
    "    // bbport (r89d_tree-twigs): or a sun-drawn skinned stream that measures as a tree (WindTwigTree)\n"
    "    const bool tree = !plant && WindTwigTree(positions, positions_size);\n"
    "    const bool hang = !plant && !tree && WindHangVerdict(pipeline, positions, positions_size);\n"
    "    if (!plant && !hang && !tree) {\n")
F_GAIN_OLD = "        std::memcpy(words + BbWindSway::ViewAt(frame_slot, view), filled.data(), sizeof(filled));\n"
F_GAIN_NEW = (
    "        if (BbWindTwigs::On()) { // bbport (r89d_tree-twigs): RippleD.z: the twigs' gain (not the trees' Ta)\n"
    "            filled[BbWindSway::RippleD + 2] = BbWindTwigs::Gain(WindTwigsNow());\n"
    "        }\n" + F_GAIN_OLD)
F_RESET_OLD = "        words[BbWindSway::CrownAt + taken.slot] = BbWindSway::ResetKey; // bbport (r89c)\n"
F_RESET_NEW = F_RESET_OLD + "        BbWindTwigs::ResetSlot(words, taken.slot); // bbport (r89d_tree-twigs): the box keys\n"
F_WORD_OLD = "    if (hang) { // bbport (r112_wind-more-things): its word (WindHangWord), counted in its lines\n"
F_WORD_NEW = (
    "    if (tree) { // bbport (r89d_tree-twigs): its word (WindTwigWord), counted in its line\n"
    "        return WindTwigWord(words, frame_slot, view, taken, positions, positions_size, frame,\n"
    "                            snapshot.time);\n"
    "    }\n" + F_WORD_OLD)
F_INC_OLD = '#include "video_core/renderer_vulkan/vk_rasterizer.h"\n'
F_INC_NEW = F_INC_OLD + r'''#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // bbport (r89d_tree-twigs): the test tools' (r84) live knobs, when present
#define BB_WIND_TWIGS_LIVE 1
#else
#define BB_WIND_TWIGS_LIVE 0
#endif
'''
F_LIVE_ANCHOR = "// bbport (r89_wind-foliage-sway): the sway word (BbWindSway::PackWord) of a skinned draw of a\n"
F_LIVE = r'''// bbport (r89d_tree-twigs): BB_WIND_TWIGS now: with the test tools' live knobs (r84) the value in the
// live knobs file, else the environment's, read when the knob is first asked. The shaders carry the twig
// code only if the knob was above 0 at the start; a live 0 gives the twigs a gain of 0 at the next view
// (the trees then stand still, not as r89c has them: that is BB_WIND_TWIGS=0 at the start).
#if BB_WIND_TWIGS_LIVE
static float TwigsParseLive(const char* text) {
    return BbWindTwigs::ParseTwigs(text);
}
#endif

static float WindTwigsNow() {
#if BB_WIND_TWIGS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_WIND_TWIGS", TwigsParseLive};
    return knob.Get();
#else
    return BbWindTwigs::KnobOnce().twigs;
#endif
}

'''
F_FUNCS_ANCHOR = "// bbport (r89_wind-foliage-sway): the knob's line once (nothing with BB_WIND off: r82's line says\n"
F_FUNCS = r'''// bbport (r89d_tree-twigs): whether a skinned sway draw that is no plant may be a tree
// (BB_WIND_TWIGS_REACH 1 or more): its stream is one a sun shadow pass draws (RtShadow::SunSkinned:
// a character, a prop with a skeleton or a tree, outdoors) that the Book has not judged a non-tree.
// Counts the draws it turns away. On the thread recording draws.
bool Rasterizer::WindTwigTree(u64 positions, u32 positions_size) {
    if (!BbWindTwigs::ReachSun()) {
        return false;
    }
    if (!rt_shadow->SunSkinned(positions, positions_size)) {
        ++twig_stats.no_sun;
        return false;
    }
    const BbWindTwigs::Entry* const entry = twig_book.Find(positions);
    if (entry != nullptr && entry->size == positions_size &&
        entry->verdict == BbWindTwigs::Verdict::NotTree) {
        ++twig_stats.not_tree;
        return false;
    }
    return true;
}

// bbport (r89d_tree-twigs): a sun-drawn stream's sway word once it has its slot: TreeBit with a ramp
// of 0 while the Book judges it (the shaders offer its keys; the CPU reads them JudgeFrames frames
// after the slot was taken, and StillFrames frames later), once it is a tree a ramp from the verdict
// (BbWindSway::RampTime of wind time `time`, so the twigs do not start at once), 0 (no sway code run)
// once it is not. On the thread recording draws.
u32 Rasterizer::WindTwigWord(u32* words, u32 frame_slot, u32 view,
                             const BbWindSway::Slots::Taken& taken, u64 positions,
                             u32 positions_size, u64 frame, double time) {
    BbWindTwigs::Entry& entry =
        twig_book.Touch(positions, positions_size, taken.slot, taken.reset, frame);
    switch (BbWindTwigs::Judge(entry, words, frame)) {
    case BbWindTwigs::Verdict::Tree:
        ++twig_stats.tree_draws;
        return BbWindTwigs::TreeWord(frame_slot, view, taken.slot,
                                     BbWindTwigs::TreeRamp(entry, time, taken.ramp));
    case BbWindTwigs::Verdict::NotTree:
        ++twig_stats.not_tree;
        return 0;
    case BbWindTwigs::Verdict::Waiting:
        break;
    }
    ++twig_stats.measuring;
    return BbWindTwigs::TreeWord(frame_slot, view, taken.slot, 0);
}

// bbport (r89d_tree-twigs): the Motion block's draws that got no sway word because the sway cannot
// reach them (counted for the twigs' line, twigs on only): a skinned draw of a pipeline without the
// Sway bit (no cut-out: an opaque mesh; BB_WIND_TWIGS_REACH=2 would take it) and a draw of a
// pipeline with the Sway bit that is not Kind::Skinned (a cut-out with a small skeleton or a palette).
// Returns 0, the sway word.
u32 Rasterizer::WindTwigSkip(bool skinned, bool sway_bit) {
    if (BbWindTwigs::On()) {
        if (skinned && !sway_bit) {
            ++twig_stats.opaque;
        } else if (!skinned && sway_bit) {
            ++twig_stats.small;
        }
    }
    return 0;
}

// bbport (r89d_tree-twigs): the twigs' line every BbWindSway::ReportFrames frame ends: the census
// of the meshes in use (the GPU's keys of each slot, read here: mapped memory is slow, once in 600
// frames), the counts of the draws and the tip move at the wind now.
void Rasterizer::WindTwigsReport() {
    u32* const words = object_motion->SwayWords();
    if (words == nullptr) {
        return;
    }
    BbWindTwigs::Census census;
    sway_slots.ForEachInUse(object_motion->Frame(), [&](u32 slot, u64 stream, u32 size) {
        const BbWindTwigs::Measure m = BbWindTwigs::MeasureOf(BbWindTwigs::ReadKeys(words, slot));
        const float height = m.crown - m.base;
        if (!m.ok || height < BbWindSway::TreeLo) {
            return;
        }
        const BbWindTwigs::Entry* const entry = twig_book.Find(stream);
        if (entry != nullptr && entry->verdict == BbWindTwigs::Verdict::Tree) {
            ++census.sun;
            census.Tall(height);
        } else if (rt_shadow->LonePlant(stream, size)) {
            ++census.lone;
            census.Tall(height);
        } else if (entry != nullptr) {
            ++census.sun_not;
        }
    });
    char text[512];
    BbWindTwigs::Knob knob = BbWindTwigs::KnobOnce();
    knob.twigs = WindTwigsNow(); // BB_WIND_TWIGS as it is now (the live knobs)
    BbWindTwigs::LineText(census, twig_stats, wind.Get(), knob,
                          BbWindSway::KnobOnce().scale, BbWindSway::LeanKnobOnce().wave, text,
                          sizeof(text));
    BbReport::Printf("%s\n", text);
    twig_stats = {};
}

'''
F_ONCE_ANCHOR = "    // bbport (r112_wind-more-things): BB_WIND_HANG's line once, with the wind's speed then\n"
F_ONCE = r'''    // bbport (r89d_tree-twigs): BB_WIND_TWIGS's line once (nothing with BB_WIND off)
    static bool twigs_said = false;
    if (!twigs_said && BbWindSway::KnobOnce().on) {
        twigs_said = true;
        char twigs[512];
        if (BbWindTwigs::On()) {
            BbWindTwigs::OnceText(BbWindTwigs::KnobOnce(), BbWindSway::KnobOnce().scale,
                                  BbWindSway::LeanKnobOnce().wave, twigs, sizeof(twigs));
        } else {
            std::snprintf(twigs, sizeof(twigs),
                          "Wind twigs (r89d): off (BB_WIND_TWIGS=0, or BB_WIND_SWAY_STYLE=wave); "
                          "trees as with r89c");
        }
        BbReport::Printf("%s\n", twigs);
    }
'''
F_LINE_OLD = ("    sway_stats = {};\n"
              "    if (BbWindHang::KnobOnce().on) { // bbport (r112_wind-more-things): its two lines\n")
F_LINE_NEW = ("    sway_stats = {};\n"
              "    if (BbWindTwigs::On()) { // bbport (r89d_tree-twigs): its line\n"
              "        WindTwigsReport();\n"
              "    }\n"
              "    if (BbWindHang::KnobOnce().on) { // bbport (r112_wind-more-things): its two lines\n")

# ---------------------------------------------------------------- vk_rasterizer.h / .cpp
RH_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
RH_INC_NEW = RH_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
RH_DECL_OLD = "    void WindSwayFrameEnd();\n"
RH_DECL_NEW = RH_DECL_OLD + r'''    /// bbport (r89d_tree-twigs, bbport_wind_twigs.h): whether a skinned sway draw's stream may be a
    /// tree a sun shadow pass draws, its sway word once it has its slot, the Motion block's draws the
    /// sway cannot reach (counted; returns 0) and the twigs' line every 600 frames.
    bool WindTwigTree(u64 positions, u32 positions_size);
    u32 WindTwigWord(u32* words, u32 frame_slot, u32 view, const BbWindSway::Slots::Taken& taken,
                     u64 positions, u32 positions_size, u64 frame, double time);
    u32 WindTwigSkip(bool skinned, bool sway_bit);
    void WindTwigsReport();
'''
RH_MEM_OLD = "    u64 sway_frames = 0;\n"
RH_MEM_NEW = (RH_MEM_OLD +
              "    BbWindTwigs::Book twig_book;   // bbport (r89d_tree-twigs): sun-drawn streams judged\n"
              "    BbWindTwigs::Stats twig_stats; // and the line's counts\n")
RC_OLD = ("                ? WindSwayWord(pipeline)\n"
          "                : 0u;\n")
RC_NEW = ("                ? WindSwayWord(pipeline)\n"
          "                // bbport (r89d_tree-twigs): 0, counting (twigs on) the draws the sway cannot reach\n"
          "                : WindTwigSkip(r34_kind == Motion::Kind::Skinned,\n"
          "                               (pipeline->GetGraphicsKey().motion_vectors &\n"
          "                                Shader::MotionVectors::Sway) != 0);\n")

# ---------------------------------------------------------------- pipeline cache, serialization, motion buffer
C_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
C_INC_NEW = C_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
C_WANT_OLD = ("           (FragmentDiscards(sel) || (BbWindHang::KnobOnce().on && SkeletonRead(sel)));\n")
C_WANT_NEW = ("           (FragmentDiscards(sel) || (BbWindHang::KnobOnce().on && SkeletonRead(sel)) ||\n"
              "            // bbport (r89d_tree-twigs): BB_WIND_TWIGS_REACH=2: also every skeleton draw (an opaque tree)\n"
              "            (BbWindTwigs::ReachOpaque() && SkeletonRead(sel)));\n")
S_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
S_INC_NEW = S_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
S_OFF_OLD = "                     BbWindShelter::BinaryOffset() // (r117_wind-shelter: 1000 with the field's read)\n"
S_OFF_NEW = ("                     BbWindShelter::BinaryOffset() + // (r117_wind-shelter: 1000 with the field's read)\n"
             "                     BbWindTwigs::BinaryOffset() // (r89d_tree-twigs: 2000 with the twigs)\n")
S_ACC_OLD = "        binary_version != Serialization::HangShaderBinaryVersion + BbWindShelter::BinaryAdd) {\n"
S_ACC_NEW = ("        binary_version != Serialization::HangShaderBinaryVersion + BbWindShelter::BinaryAdd &&\n"
             "        !BbWindTwigs::KnownVersion(binary_version, Serialization::SwayShaderBinaryVersion,\n"
             "                                   Serialization::HangShaderBinaryVersion,\n"
             "                                   BbWindShelter::BinaryAdd)) { // bbport (r89d_tree-twigs)\n")
M_INC_OLD = '#include "bbport_wind_hang.h" // bbport (r112_wind-more-things)\n'
M_INC_NEW = M_INC_OLD + '#include "bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
M_BUF_OLD = "(BbWindSway::KnobOnce().on ? BbWindShelter::BufferBytes(BbWindHang::SwayBytes()) : 0u), // (r112, r117)\n"
M_BUF_NEW = ("(BbWindSway::KnobOnce().on\n"
             "                          ? BbWindTwigs::BufferBytes(BbWindShelter::BufferBytes(BbWindHang::SwayBytes()))\n"
             "                          : 0u), // (r112, r117, r89d)\n")
M_INIT_OLD = ("        for (u32 i = BbWindSway::BaseAt; i < BbWindHang::KeysEnd(); ++i) { // (r112): top keys\n"
              "            sway_words[i] = BbWindSway::ResetKey;\n"
              "        }\n")
M_INIT_NEW = (M_INIT_OLD +
              "        static_assert(BbWindTwigs::TwigAt >= BbWindShelter::BlockWord + BbWindShelter::BlockWords,\n"
              "                      \"the twigs' box keys lie behind r117's field block\");\n"
              "        BbWindTwigs::InitWords(sway_words); // bbport (r89d_tree-twigs): the box keys at ResetKey\n")

# ---------------------------------------------------------------- the test
T_INC_OLD = '#include "gpu/shim/bbport_wind_sway.h"\n'
T_INC_NEW = T_INC_OLD + '#include "gpu/shim/bbport_wind_twigs.h" // bbport (r89d_tree-twigs)\n'
T_HELP_OLD = "    s.gust = BbWind::Gust(time, gusts);\n    return s;\n}\n} // namespace\n"
T_HELP_NEW = r'''    s.gust = BbWind::Gust(time, gusts);
    return s;
}

// bbport (r89d_tree-twigs): a tree mesh's box in the world (m) as the GPU's keys hold it: lowest and
// highest y, lowest and highest x, lowest and highest z.
struct TreeBox {
    float base, crown, x_lo, x_hi, z_lo, z_hi;
};

TwigIn TwigInOf(const TreeBox& b, bool tree_only) {
    TwigIn in;
    in.keys = {HeightKey(b.x_lo), CrownKey(b.x_hi), HeightKey(b.z_lo), CrownKey(b.z_hi)};
    in.tree_only = tree_only;
    return in;
}

// A view with the lean and the twigs' gain in RippleD.z, as the CPU writes it (BB_WIND_TWIGS `twigs`).
std::array<float, ViewWords> TwigViewOf(const std::array<float, 216>& c, const BbWind::Snapshot& s,
                                        Ripple& ripple, float twigs, float scale = 1.0f,
                                        float gusts = 0.5f) {
    auto view = LeanViewOf(c, s, ripple, ParseRipple(nullptr, nullptr), ParseLean(nullptr, nullptr),
                           scale, gusts);
    view[RippleD + 2] = TwigRatio * twigs;
    return view;
}

// How the lean moves world point p of a mesh with box b, with the twigs (or, `twigs_on` false, as
// before them): after minus before, in the world (x, y, z).
std::array<double, 3> TwigMoveOf(const float* view, const std::array<float, 216>& c,
                                 const std::array<double, 3>& p, const TreeBox& b,
                                 bool tree_only = false, bool twigs_on = true) {
    const auto clip = ClipOf(c, p);
    const auto before = WorldOf(view, clip);
    const TwigIn in = TwigInOf(b, tree_only);
    const auto after = WorldOf(view, Displace(view, clip, HeightKey(b.base), 1.0f, nullptr,
                                              CrownKey(b.crown), nullptr,
                                              twigs_on ? &in : nullptr));
    return {after[0] - before[0], after[1] - before[1], after[2] - before[2]};
}
} // namespace
'''
T_TESTS_ANCHOR = "    // The log's texts.\n"
T_TESTS = r'''    // bbport (r89d_tree-twigs): the knobs, the layout, the sway word's bit and the saved versions.
    {
        namespace T = BbWindTwigs;
        const T::Knob def = T::ParseKnob(nullptr, nullptr, true, true);
        Expect(def.on && def.asked && def.twigs == 1.0f && def.reach == 1,
               "BB_WIND_TWIGS unset: on at 1, reach 1");
        Expect(!T::ParseKnob("0", nullptr, true, true).on &&
                   !T::ParseKnob("0", nullptr, true, true).asked,
               "BB_WIND_TWIGS=0: off (trees as r89c)");
        Expect(T::ParseKnob("9", nullptr, true, true).twigs == T::TwigsMax &&
                   T::ParseKnob("-1", nullptr, true, true).twigs == 0.0f &&
                   T::ParseKnob("abc", nullptr, true, true).twigs == 1.0f &&
                   T::ParseKnob("2.5", nullptr, true, true).twigs == 2.5f,
               "BB_WIND_TWIGS: 0-4, unreadable 1");
        Expect(!T::ParseKnob(nullptr, nullptr, false, true).on &&
                   !T::ParseKnob(nullptr, nullptr, true, false).on,
               "the twigs need the sway and its lean");
        Expect(T::ParseKnob(nullptr, "0", true, true).reach == 0 &&
                   T::ParseKnob(nullptr, "1", true, true).reach == 1 &&
                   T::ParseKnob(nullptr, "2", true, true).reach == 2 &&
                   T::ParseKnob(nullptr, "x", true, true).reach == 1,
               "BB_WIND_TWIGS_REACH 0, 1, 2; unreadable 1");
        Expect(T::TwigAt >= 4096 + 8 + 64 * 64 && T::TwigEnd == T::TwigAt + BaseSlots * 4 &&
                   T::TwigBytes == T::TwigEnd * 4,
               "the box keys lie behind r117's field block");
        const std::uint32_t word = T::TreeWord(3, 1, 511, 200);
        const Unpacked u = Unpack(word);
        Expect(T::IsTreeWord(word) && u.on && u.frame_slot == 3 && u.view == 1 &&
                   u.base_slot == 511 && u.ramp == 200 && !T::IsTreeWord(PackWord(3, 1, 511, 200)),
               "TreeWord keeps PackWord's fields and adds TreeBit");
        Expect(T::KnownVersion(11, 11, 21, 1000) && T::KnownVersion(2011, 11, 21, 1000) &&
                   T::KnownVersion(3021, 11, 21, 1000) && T::KnownVersion(1021, 11, 21, 1000) &&
                   !T::KnownVersion(4011, 11, 21, 1000) && !T::KnownVersion(12, 11, 21, 1000),
               "the saved sway versions that are known");
        Expect(T::Gain(1.0f) == TwigRatio && T::Gain(4.0f) == TwigRatio * 4.0f && T::Gain(0.0f) == 0.0f &&
                   T::ParseTwigs(nullptr) == 1.0f && T::ParseTwigs("2") == 2.0f &&
                   T::ParseTwigs("9") == T::TwigsMax,
               "the gain is TwigRatio x BB_WIND_TWIGS; live values parse as the knob does");
    }

    // The twig weight: the trunk and the main limbs still, the outer upper parts in full, smooth.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const float gain = view[RippleD + 2];
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const TwigIn in = TwigInOf(tree, false);
        const auto weight = [&](double dx, double dz, double h) {
            return TwigWeight(view.data(), float(mid[0] + dx), float(mid[2] + dz), float(h), 10.0f,
                              in.keys);
        };
        Expect(weight(0.0, 0.0, 2.0) == 0.0f && weight(0.0, 0.0, 9.0) == 0.0f,
               "on the box's centre line: still at any height");
        Expect(weight(3.8, 0.0, 2.0) == 0.0f && weight(-3.8, 1.0, 1.5) == 0.0f,
               "low (the roots, the trunk's flare): still at any radius");
        Expect(std::fabs(weight(3.7, 0.0, 9.0) - gain) < 1e-6 &&
                   std::fabs(weight(0.0, -3.7, 9.0) - gain) < 1e-6,
               "outer and high: the full twig gain");
        Expect(weight(1.0, 0.0, 9.0) == 0.0f, "near the centre line (a main limb): still");
        bool rising = true, smooth = true;
        float last = 0.0f;
        for (int i = 0; i <= 400; ++i) { // outward at h = 9 m, 1 cm steps
            const float w = weight(0.01 * i, 0.0, 9.0);
            rising = rising && w >= last - 1e-9f;
            smooth = smooth && std::fabs(w - last) < 0.03f * gain;
            last = w;
        }
        last = 0.0f;
        for (int i = 0; i <= 1000; ++i) { // upward at r = 3.7 m, 1 cm steps
            const float w = weight(3.7, 0.0, 0.01 * i);
            rising = rising && w >= last - 1e-9f;
            smooth = smooth && std::fabs(w - last) < 0.03f * gain;
            last = w;
        }
        Expect(rising, "the twig weight grows with the radius and the height");
        Expect(smooth, "neighbouring vertices (1 cm apart) have neighbouring weights");
        // a mesh with no box yet or a thin one: finite, and a box under 1 m wide counts as 1 m
        const TwigIn none{};
        Expect(std::isfinite(TwigWeight(view.data(), 10.0f, 20.0f, 9.0f, 10.0f, none.keys)),
               "no box keys yet: a finite weight");
        const TreeBox thin = {0.5f, 10.5f, float(mid[0] - 0.05), float(mid[0] + 0.05),
                              float(mid[2] - 0.05), float(mid[2] + 0.05)};
        const TwigIn thin_in = TwigInOf(thin, false);
        Expect(TwigWeight(view.data(), float(mid[0] + 0.1), float(mid[2]), 9.0f, 10.0f, thin_in.keys) == 0.0f,
               "a thin box: the half width is held to 0.5 m");
    }

    // The twigs move by TwigRatio of a bush's lean: a tip at 1.5 m/s at most about 3 cm, at 4 m/s
    // about 9 cm (10 at a gust factor of 1.1); the trunk does not move.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const std::array<double, 3> tip = {mid[0] + 3.7, 9.5, mid[2]};
        const std::array<double, 3> trunk = {mid[0], 5.0, mid[2]};
        double peak15 = 0.0, peak4 = 0.0, trunk_move = 0.0;
        for (int k = 0; k < 2; ++k) {
            const float speed = k == 0 ? 1.5f : 4.0f;
            double& peak = k == 0 ? peak15 : peak4;
            Ripple ripple;
            for (int i = 0; i < 1500; ++i) {
                const auto view = TwigViewOf(c, Gusty(0.1 * i, 225.0f, speed, 0.5f), ripple, 1.0f);
                const auto d = TwigMoveOf(view.data(), c, tip, tree);
                peak = std::max(peak, std::hypot(d[0], d[2]));
                trunk_move = std::max(trunk_move, Length(TwigMoveOf(view.data(), c, trunk, tree)));
            }
        }
        // the analytic bound at 1.5 m/s (no leaves): gust factor GustMax, front EnvScale, the wave
        // at its crest, the twig weight TwigRatio at a tip (gain 0.3 x BB_WIND_TWIGS 1)
        const LeanCurve n15 = LeanAt(1.5f, 1.0f, 1.0f, false);
        const double along15 = double(BbWind::GustMax) *
                               (double(n15.rest) + double(n15.bend) +
                                double(n15.bend) * (double(EnvScale) - 1.0) +
                                double(n15.along) * double(EnvScale));
        const double cross15 = double(BbWind::GustMax) * double(n15.cross) * double(EnvScale);
        const double bound15 = double(TwigRatio) * std::hypot(along15, cross15) * 1.02;
        Expect(peak15 > 0.003 && peak15 < 0.03 && peak15 < bound15 + 1e-4,
               "a twig tip at 1.5 m/s: between 0.3 and 3 cm");
        Expect(peak4 > 0.03 && peak4 < 0.14, "a twig tip at 4 m/s: between 3 and 14 cm");
        Expect(peak4 > 2.5 * peak15 && peak4 < 20.0 * peak15,
               "the stronger wind moves the twigs several times as far");
        Expect(trunk_move < 1e-9, "the trunk does not move");
        const BbWindTwigs::Tip d15 = BbWindTwigs::TipAt(1.5f, 1.0f, 1.0f, 1.0f, false);
        const BbWindTwigs::Tip d4 = BbWindTwigs::TipAt(4.0f, 1.0f, 1.0f, 1.0f, false);
        Expect(Near(d15.lean, 0.0063, 2e-4) && Near(d15.front, 0.0129, 3e-4) &&
                   Near(d4.lean, 0.045, 1e-4) && Near(d4.front, 0.0918, 3e-4),
               "TipAt: 0.6/1.3 cm at 1.5 m/s and 4.5/9.2 cm at 4 m/s");
        Expect(BbWindTwigs::TipAt(0.0f, 1.0f, 1.0f, 1.0f, false).front == 0.0f,
               "no wind: no twig move");
    }

    // The twigs change nothing for a bush (tau 0), nothing without them (twig null), and a mesh
    // that may only be a tree (TreeBit) has no bush weight.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        const std::array<double, 3> mid = {10.0 - std::sin(0.3) * 7.0, 0.0, 20.0 - std::cos(0.3) * 7.0};
        const TreeBox bush = {0.5f, 2.0f, float(mid[0] - 1.0), float(mid[0] + 1.0), float(mid[2] - 1.0),
                              float(mid[2] + 1.0)};
        const TreeBox tree = {0.5f, 10.5f, float(mid[0] - 4.0), float(mid[0] + 4.0),
                              float(mid[2] - 4.0), float(mid[2] + 4.0)};
        const TreeBox prop = {0.5f, 1.7f, float(mid[0] - 1.0), float(mid[0] + 1.0), float(mid[2] - 1.0),
                              float(mid[2] + 1.0)};
        Ripple ripple;
        double bush_diff = 0.0, off_diff = 0.0, tree_only_diff = 0.0, prop_only = 0.0;
        for (int i = 0; i < 600; ++i) {
            const auto view = TwigViewOf(c, Gusty(0.2 * i, 225.0f, 3.0f, 0.5f), ripple, 1.0f);
            const std::array<double, 3> p = {mid[0] + 0.9, 1.4, mid[2] - 0.2};
            const auto with = TwigMoveOf(view.data(), c, p, bush);
            const auto without = TwigMoveOf(view.data(), c, p, bush, false, false);
            bush_diff = std::max(bush_diff, Length({with[0] - without[0], with[1] - without[1],
                                                    with[2] - without[2]}));
            const std::array<double, 3> q = {mid[0] + 3.7, 9.5, mid[2]};
            const auto a = TwigMoveOf(view.data(), c, q, tree, false);
            const auto b = TwigMoveOf(view.data(), c, q, tree, true);
            tree_only_diff = std::max(tree_only_diff,
                                      Length({a[0] - b[0], a[1] - b[1], a[2] - b[2]}));
            prop_only = std::max(prop_only, Length(TwigMoveOf(view.data(), c, p, prop, true)));
            const auto plain = TwigMoveOf(view.data(), c, p, bush, false, false);
            const auto old = LeanMoveOf(view.data(), c, p, 0.5f, 2.0f);
            off_diff = std::max(off_diff, Length({plain[0] - old[0], plain[1] - old[1], plain[2] - old[2]}));
        }
        Expect(bush_diff == 0.0, "a bush (mesh under 2 m) moves as before with the twigs on");
        Expect(off_diff == 0.0, "twig null: Displace is r89c's (the old path, bit for bit)");
        Expect(tree_only_diff < 1e-6, "a tall tree-only mesh moves as a tree: no bush weight to lose");
        Expect(prop_only == 0.0, "a short mesh that may only be a tree does not move");
    }

    // The keys a vertex offers the box.
    {
        const auto c = Constants(0.3, -0.1, {10.0, 2.0, 20.0});
        Ripple ripple;
        const auto view = TwigViewOf(c, Wind(5.0, 225.0f, 1.5f), ripple, 1.0f);
        const std::array<double, 3> p = {10.0 - std::sin(0.3) * 6.0 + 1.25, 2.0, 20.0 - std::cos(0.3) * 6.0 - 0.75};
        const auto clip = ClipOf(c, p);
        const TwigIn in{};
        std::array<std::uint32_t, 4> offered{};
        (void)Displace(view.data(), clip, HeightKey(0.5f), 1.0f, nullptr, ResetKey, nullptr, &in,
                       &offered);
        Expect(Near(KeyHeight(offered[0]), p[0], 3e-3) && Near(KeyCrown(offered[1]), p[0], 3e-3) &&
                   Near(KeyHeight(offered[2]), p[2], 3e-3) && Near(KeyCrown(offered[3]), p[2], 3e-3),
               "a vertex offers its world x and z to the box keys");
        Expect(offered[0] < ResetKey && offered[1] < ResetKey && offered[2] < ResetKey &&
                   offered[3] < ResetKey,
               "the offered keys lie below ResetKey");
    }

    // The CPU's judgement of a sun-drawn stream (Book, Judge) and the key words.
    {
        namespace T = BbWindTwigs;
        std::vector<std::uint32_t> words(T::TwigEnd, 0u);
        const auto set = [&](std::uint32_t slot, float base, float crown, float x0, float x1, float z0,
                             float z1) {
            words[BaseAt + slot] = HeightKey(base);
            words[CrownAt + slot] = CrownKey(crown);
            words[T::TwigAt + slot * 4 + 0] = HeightKey(x0);
            words[T::TwigAt + slot * 4 + 1] = CrownKey(x1);
            words[T::TwigAt + slot * 4 + 2] = HeightKey(z0);
            words[T::TwigAt + slot * 4 + 3] = CrownKey(z1);
        };
        const auto none = [&](std::uint32_t slot) {
            words[BaseAt + slot] = ResetKey;
            words[CrownAt + slot] = ResetKey;
            for (std::uint32_t i = 0; i < T::TwigSlotWords; ++i) {
                words[T::TwigAt + slot * T::TwigSlotWords + i] = ResetKey;
            }
        };
        T::Book book;
        // a still tall mesh: waiting for 8 + 60 frames (the first read at frame 108), then a tree
        set(5, 0.5f, 10.5f, 20.0f, 28.0f, 40.0f, 46.0f);
        T::Entry& tree = book.Touch(0xa000, 4096, 5, true, 100);
        bool waiting = true;
        for (std::uint64_t f = 100; f < 168; ++f) {
            tree.seen = f;
            waiting = waiting && T::Judge(tree, words.data(), f) == T::Verdict::Waiting;
        }
        Expect(waiting && tree.snapped && tree.snap_at == 108, "judging: waits, first read at frame 108");
        Expect(T::Judge(tree, words.data(), 168) == T::Verdict::Tree && Near(tree.height, 10.0, 2e-3),
               "a still mesh 10 m tall is a tree");
        // a prop 1.2 m tall, still: not a tree
        set(6, 0.5f, 1.7f, 20.0f, 21.0f, 40.0f, 41.0f);
        T::Entry& prop = book.Touch(0xa100, 512, 6, true, 100);
        (void)T::Judge(prop, words.data(), 108);
        Expect(T::Judge(prop, words.data(), 168) == T::Verdict::NotTree, "a 1.2 m mesh is not a tree");
        // a walking character 3.4 m tall (a giant): its box moves 2 m in a second: not a tree
        set(7, 0.5f, 3.9f, 20.0f, 21.0f, 40.0f, 41.0f);
        T::Entry& walker = book.Touch(0xa200, 512, 7, true, 100);
        (void)T::Judge(walker, words.data(), 108);
        set(7, 0.5f, 3.9f, 22.0f, 23.0f, 40.0f, 41.0f);
        Expect(T::Judge(walker, words.data(), 168) == T::Verdict::NotTree, "a mesh whose box moves is not a tree");
        // a mesh whose keys were never offered: waits, then gives up
        none(8);
        T::Entry& unseen = book.Touch(0xa300, 512, 8, true, 100);
        Expect(T::Judge(unseen, words.data(), 120) == T::Verdict::Waiting &&
                   T::Judge(unseen, words.data(), 100 + T::GiveUpFrames) == T::Verdict::NotTree,
               "keys never offered: waiting, then not a tree");
        // a verdict stays until the slot, the size or the keys change
        T::Entry& again = book.Touch(0xa000, 4096, 5, false, 200);
        Expect(again.verdict == T::Verdict::Tree, "a verdict stays");
        T::Entry& reset = book.Touch(0xa000, 4096, 5, true, 300);
        Expect(reset.verdict == T::Verdict::Waiting && reset.first == 300 && !reset.snapped,
               "a reset slot is judged again");
        T::Entry& resized = book.Touch(0xa000, 8192, 5, false, 301);
        Expect(resized.size == 8192 && resized.verdict == T::Verdict::Waiting, "another size: again");
        Expect(book.Find(0xa000) != nullptr && book.Find(0xdead) == nullptr, "Find");
        // a tree's ramp starts at the verdict, in wind time (and never above the slot's own ramp)
        T::Entry fresh;
        Expect(T::TreeRamp(fresh, 100.0, 255) == 0 && T::TreeRamp(fresh, 100.5, 255) >= 126 &&
                   T::TreeRamp(fresh, 100.5, 255) <= 129 && T::TreeRamp(fresh, 101.0, 255) == 255 &&
                   T::TreeRamp(fresh, 105.0, 50) == 50,
               "TreeRamp: from 0 at the verdict to 255 in 1 s, held to the slot's ramp");
        // the keys' reading and the measure
        const T::Keys keys = T::ReadKeys(words.data(), 5);
        const T::Measure m = T::MeasureOf(keys);
        Expect(m.ok && Near(m.base, 0.5, 2e-3) && Near(m.crown, 10.5, 2e-3) && Near(m.x_lo, 20.0, 2e-3) &&
                   Near(m.x_hi, 28.0, 2e-3) && Near(m.z_lo, 40.0, 2e-3) && Near(m.z_hi, 46.0, 2e-3),
               "ReadKeys and MeasureOf give back the box");
        Expect(!T::MeasureOf(T::Keys{}).ok, "keys at ResetKey: no measure");
    }

    // The slots in use.
    {
        Slots slots;
        (void)slots.Take(0x1000, 64, 10, 0.0);
        (void)slots.Take(0x2000, 128, 10, 0.0);
        std::vector<std::uint64_t> seen;
        slots.ForEachInUse(12, [&](std::uint32_t slot, std::uint64_t stream, std::uint32_t size) {
            Expect(slot < PlantSlots && size != 0, "ForEachInUse: slot and size");
            seen.push_back(stream);
        });
        std::uint32_t later = 0;
        slots.ForEachInUse(10 + ReuseFrames + 1, [&](std::uint32_t, std::uint64_t, std::uint32_t) { ++later; });
        Expect(seen.size() == 2 && (seen[0] == 0x1000 || seen[1] == 0x1000) && later == 0,
               "ForEachInUse: the streams drawn within ReuseFrames frames");
    }

    // The twigs' log texts (under 300 characters), the model's share.
    {
        namespace T = BbWindTwigs;
        char text[512];
        T::Census census;
        census.lone = 3;
        census.sun = 4;
        census.sun_not = 2;
        for (const float h : {9.2f, 7.1f, 6.4f, 3.0f, 8.0f}) {
            census.Tall(h);
        }
        T::Stats st;
        st.small = 40;
        st.opaque = 12;
        T::LineText(census, st, Wind(10.0, 231.0f, 1.5f), T::ParseKnob(nullptr, nullptr, true, true),
                    1.0f, 1.0f, text, sizeof(text));
        const char* head =
            "Wind twigs (r89d): trees taken 7 (meshes: 3 lone, 4 sun; tallest 9.2/8.0/7.1 m), skipped 54 by "
            "reason (draws: small-skeleton 40, opaque 12, no-sun 0; meshes: sun-not-still 2); twig share of "
            "tree vertices ";
        Expect(std::strncmp(text, head, std::strlen(head)) == 0 && std::strlen(text) < 300 &&
                   std::strstr(text, "(model); tip move at 1.50 m/s: 0.6 cm lean, 1.3 cm gust front") != nullptr,
               "the twigs' line");
        census = T::Census{};
        st.small = 999999;
        st.opaque = 999999;
        st.no_sun = 999999;
        census.lone = 30;
        census.sun = 40;
        census.sun_not = 99;
        for (const float h : {19.2f, 18.0f, 17.1f}) {
            census.Tall(h);
        }
        T::LineText(census, st, Wind(10.0, 231.0f, 4.0f), T::ParseKnob("4", "2", true, true), MaxScale, 4.0f,
                    text, sizeof(text));
        Expect(std::strlen(text) < 300, "the line at 6-digit counts stays under 300 characters");
        T::LineText(T::Census{}, T::Stats{}, Wind(10.0, 231.0f, 1.5f), T::ParseKnob(nullptr, nullptr, true, true),
                    1.0f, 1.0f, text, sizeof(text));
        Expect(std::strstr(text, "trees taken 0 (meshes: 0 lone, 0 sun; tallest none m)") != nullptr,
               "the line with no tree");
        T::OnceText(T::ParseKnob(nullptr, nullptr, true, true), 1.0f, 1.0f, text, sizeof(text));
        Expect(std::strncmp(text, "Wind twigs (r89d, BB_WIND_TWIGS=1.00, REACH=1): small branches", 62) == 0 &&
                   std::strlen(text) < 300 &&
                   std::strstr(text, "tip 0.6/1.3 cm (lean/gust front) at 1.5 m/s, 4.5/9.2 cm at 4 m/s") != nullptr,
               "the twigs' once line");
        T::OnceText(T::ParseKnob("4", "2", true, true), MaxScale, 4.0f, text, sizeof(text));
        Expect(std::strlen(text) < 300, "the once line at the strongest");
        const float share = T::ModelShare();
        Expect(share > 0.2f && share < 0.35f, "the model's twig share is about 28 percent");
    }

'''
T_TESTS_NEW = T_TESTS + T_TESTS_ANCHOR

# ---------------------------------------------------------------- README
README_ANCHOR = "| `BB_WIND_HANG` | Hanging things lean with the wind:"
README_ROWS = (
    "| `BB_WIND_TWIGS` | Tree twigs: the small branches of tree meshes stir with the wind while the trunk "
    "and the main limbs stay still. 0 to 4, default 1 (unset or text that is not a number: 1; 0: trees as "
    "with the lean alone, `BB_WIND_SWAY_STYLE`: only the top half of a tree bends, times smoothstep(1, 4 "
    "m/s, v)). It needs the plant sway on (`BB_WIND=1`, `BB_WIND_SWAY` above 0, the lean) and ray tracing. "
    "A tree is a mesh over 2 m tall (a full tree from 3.5 m) that the plant sway takes: a plant (a cut-out "
    "with a skeleton no sun shadow pass draws) or, with `BB_WIND_TWIGS_REACH` 1 or 2, a skinned mesh a "
    "sun shadow pass also draws that measures at least 3 m tall and still (its box and its heights move at "
    "most 0.3 m in 60 frames: a walking character does not qualify). A vertex's twig weight is "
    "smoothstep(0.35^2, 0.85^2; r^2 / half^2) x smoothstep(0.3, 0.7; h / height): r its distance from the "
    "centre line of the mesh's box, half the box's half width (the larger of x and z, at least 0.5 m), h "
    "its height above the mesh's lowest point, height the mesh's. The GPU keeps the box (the world x and z "
    "extent: four more keys a mesh, as the lowest and highest y), so a trunk, a main limb (near the "
    "centre line) and the low part of a tree do not move; outer and upper parts move in full. Weights "
    "are smooth in position: a branch moves as one and leaf cards follow their twig. A twig tip bends "
    "0.3 x the knob of a bush's lean (the lean's gust fronts, 9 m / v apart, and its subtle wave at "
    "0.15 + 0.15 v Hz): at 1.5 m/s 0.6 cm steady and 1.3 cm at the crest of a gust front (gust factor 1; "
    "up to 2.6 cm in the strongest gust), at 4 m/s 4.5 cm and 9.2 cm; nothing at 0 m/s. With BB_WIND_TWIGS=4 "
    "four times that, held to the lean's limits. With the test tools' live knobs `set:BB_WIND_TWIGS=0` gives the "
    "twigs no weight at once (the trees stand still; the shaders keep the code, so only a value above 0 at the "
    "start can be set live). The log says once `Wind twigs (r89d, BB_WIND_TWIGS=...)` "
    "and every 600 frames `Wind twigs (r89d): trees taken N (meshes ...), skipped M by reason ..., twig "
    "share of tree vertices ... (model), tip move at this wind ... cm`; the share is a model (vertices "
    "spread evenly in the box), the rest counted; the line starts `Wind twigs`, not `Wind sway`. "
    "Limits: a tree drawn as several meshes is judged mesh by mesh; a standing creature 3 m or more tall "
    "with cut-outs would move 1-3 cm; trees drawn with a small skeleton (2 to 39 bones) or with a palette "
    "are not reached (the line counts them as `small-skeleton`). Cost: with the twigs on 4 more loads and "
    "about 60 operations a vertex of a swayed mesh, 4 atomic minimums only while a vertex lies outside "
    "the box so far, the sway region's buffer is 48 KB (host visible: the box keys sit 16 KB behind r117's field block), a sun-drawn skinned stream gets a "
    "sway word while it is judged (about 70 frames); not measured | `1` |\n"
    "| `BB_WIND_TWIGS_REACH` | Which trees the twigs may take (`BB_WIND_TWIGS` row): `0` only the meshes "
    "the plant sway takes; `1` (default) also skinned cut-outs that a sun shadow pass draws and that "
    "measure as trees; `2` also skinned draws of pipelines without a cut-out (a bare tree drawn as an opaque "
    "mesh): then every skeleton draw's vertex shader carries the sway code (compiled again once, a word "
    "load and a branch a vertex of every character), which is why it is not the default. Any other text "
    "is 1. The log line's `opaque` count says how many skinned draws `2` would add | `1` |\n")
README_SWAY_CHECK = "| `BB_WIND_SWAY_STYLE` |"

EDITS = {
    HEADER: [
        (H_DOC, H_BLOCK + H_DOC),
        (H_SIG_OLD, H_SIG_NEW),
        (H_FIN_OLD, H_FIN_NEW),
        (H_W_OLD, H_W_NEW),
        (H_SLOTS_OLD, H_SLOTS_NEW),
    ],
    EMIT: [
        (E_INC_OLD, E_INC_NEW),
        (E_CROWN_OLD, E_CROWN_OLD + E_A),
        (E_W_OLD, E_W_NEW),
        (E_END_OLD, "    ctx.AddLabel(crown_merge);\n" + E_C + "    ctx.OpBranch(sway_merge);\n"),
    ],
    LIFT: [
        (L_INC_OLD, L_INC_NEW),
        (L_CROWN_OLD, L_CROWN_OLD + L_A),
        (L_W_OLD, L_W_NEW),
        (L_END_OLD, "    Open(crown_merge);\n" + L_C + "    EmitVoid(O(spv::Op::OpBranch), {sway_merge});\n"),
    ],
    EFFECTS: [
        (F_INC_OLD, F_INC_NEW),
        (F_LIVE_ANCHOR, F_LIVE + F_LIVE_ANCHOR),
        (F_TREE_OLD, F_TREE_NEW),
        (F_GAIN_OLD, F_GAIN_NEW),
        (F_RESET_OLD, F_RESET_NEW),
        (F_WORD_OLD, F_WORD_NEW),
        (F_FUNCS_ANCHOR, F_FUNCS + F_FUNCS_ANCHOR),
        (F_ONCE_ANCHOR, F_ONCE + F_ONCE_ANCHOR),
        (F_LINE_OLD, F_LINE_NEW),
    ],
    RASH: [
        (RH_INC_OLD, RH_INC_NEW),
        (RH_DECL_OLD, RH_DECL_NEW),
        (RH_MEM_OLD, RH_MEM_NEW),
    ],
    RASC: [
        (RC_OLD, RC_NEW),
    ],
    CACHE: [
        (C_INC_OLD, C_INC_NEW),
        (C_WANT_OLD, C_WANT_NEW),
    ],
    SERIAL: [
        (S_INC_OLD, S_INC_NEW),
        (S_OFF_OLD, S_OFF_NEW),
        (S_ACC_OLD, S_ACC_NEW),
    ],
    MOTION: [
        (M_INC_OLD, M_INC_NEW),
        (M_BUF_OLD, M_BUF_NEW),
        (M_INIT_OLD, M_INIT_NEW),
    ],
    TEST: [
        (T_INC_OLD, T_INC_NEW),
        (T_HELP_OLD, T_HELP_NEW),
        (T_TESTS_ANCHOR, T_TESTS_NEW),
    ],
    README: [
        (README_ANCHOR, README_ROWS + README_ANCHOR),
    ],
}

CHECKS = {
    HEADER: [("inline constexpr float TwigRatio = 0.30f;", 1), ("inline float TwigWeight(", 1),
             ("const TwigIn* twig = nullptr, // r89d", 1), ("void ForEachInUse(", 1),
             ("wb_use = twig->tree_only ? 0.0f : wb;", 1), ("const float w = (wb + tau * lean", 0),
             ("inline bool FillLean(", 1), ("std::uint32_t stored_crown = ResetKey", 1)],
    EMIT: [("BbWindTwigs::On()", 1), ("u64(BbWindTwigs::TwigAt)", 1), ("ctx.ConstU32(BbWindTwigs::TreeBit)", 1), ("OpAtomicUMin", 4),
           ("const Id w = mul(add(wb_use,", 1), ("const Id w = mul(add(wb,", 0), ("W::TwigRad2Lo", 1),
           ("EmitVertexSway(ctx);", 1), ("if (twig_on) {", 3), ("BbWindShelter::KnobOnce().on", 1)],
    LIFT: [("BbWindTwigs::On()", 1), ("u64(BbWindTwigs::TwigAt)", 1), ("CU(BbWindTwigs::TreeBit)", 1), ("OpAtomicUMin", 4),
           ("const u32 w = FMul(FAdd(wb_use,", 1), ("const u32 w = FMul(FAdd(wb,", 0), ("W::TwigRad2Lo", 1),
           ("VertexSway();", 1), ("if (twig_on) {", 3), ("BbWindShelter::KnobOnce().on", 1)],
    EFFECTS: [("WindTwigTree(", 2), ("WindTwigWord(", 2), ("WindTwigsReport(", 2), ("WindTwigSkip(", 1),
              ("BbWindTwigs::ResetSlot(", 1), ("BbWindTwigs::Gain(WindTwigsNow())", 1), ("WindTwigsNow()", 3), ("BbWindTwigs::OnceText(", 1),
              ("BbWindTwigs::LineText(", 1), ("WindHangVerdict(pipeline, positions, positions_size)", 1)],
    RASH: [("bool WindTwigTree(", 1), ("u32 WindTwigWord(", 1), ("u32 WindTwigSkip(", 1), ("void WindTwigsReport();", 1),
           ("BbWindTwigs::Book twig_book;", 1), ("BbWindTwigs::Stats twig_stats;", 1)],
    RASC: [("WindTwigSkip(", 1), ("? WindSwayWord(pipeline)", 1)],
    CACHE: [("BbWindTwigs::ReachOpaque()", 1)],
    SERIAL: [("BbWindTwigs::BinaryOffset()", 1), ("BbWindTwigs::KnownVersion(", 1)],
    MOTION: [("BbWindTwigs::BufferBytes(", 1), ("BbWindTwigs::InitWords(", 1), ("BbWindTwigs::TwigAt >=", 1)],
    TEST: [("TwigMoveOf(", 9), ("wind-sway-test: ok", 1), ("TwigViewOf(", 5)],
    README: [("| `BB_WIND_TWIGS` |", 1), ("| `BB_WIND_TWIGS_REACH` |", 1), ("| `BB_WIND_HANG` |", 1)],
}

ORDER = {
    HEADER: ["inline constexpr float TwigRatio", "inline float Smooth01(", "struct TwigIn {", "inline float TwigWeight(",
             "inline std::array<float, 4> Displace(", "const TwigIn* twig = nullptr", "if (twig_offer != nullptr)",
             "float wt_use = wt, wb_use = wb;", "class Slots {", "void ForEachInUse("],
    EMIT: ["static void EmitVertexSway(", "const Id crown = ", "const bool twig_on", "const Id w = mul(add(wb_use,",
           "const Id ddx_one", "const Id d =", "ctx.OpStore(ctx.output_position", "const Id crown_key",
           "ctx.AddLabel(crown_merge);", "if (twig_on) { // bbport (r89d_tree-twigs): the vertex offers",
           "ctx.OpBranch(sway_merge);", "void EmitEpilogue("],
    LIFT: ["void Lift_::VertexSway() {", "const u32 crown = ", "const bool twig_on", "const u32 w = FMul(FAdd(wb_use,",
           "const u32 ddx_one", "const u32 d = ", "EmitVoid(O(spv::Op::OpStore), {var_position", "const u32 crown_key",
           "Open(crown_merge);", "if (twig_on) { // bbport (r89d_tree-twigs): the vertex offers",
           "EmitVoid(O(spv::Op::OpBranch), {sway_merge});", "void Lift_::VertexMotion() {"],
    EFFECTS: ["u32 Rasterizer::WindSwayWord(", "const bool tree = ", "BbWindTwigs::ResetSlot(", "WindTwigWord(words,",
              "bool Rasterizer::WindTwigTree(", "void Rasterizer::WindTwigsReport()",
              "void Rasterizer::WindSwayFrameEnd()", "static bool twigs_said", "WindTwigsReport();"],
    TEST: ["TreeBox {", "TwigMoveOf(const float* view", "} // namespace", "int main() {", "the knobs, the layout, the sway word's bit",
           "The twig weight: the trunk", "The CPU's judgement of a sun-drawn stream", "// The log's texts.",
           "wind-sway-test: ok"],
    README: ["| `BB_WIND_SWAY_STYLE` |", "| `BB_WIND_TWIGS` |", "| `BB_WIND_TWIGS_REACH` |", "| `BB_WIND_HANG` |"],
}

# Numbers written twice (rule 10): the header's constants and the README row's text.
TIES = [(HEADER, "TwigRatio = 0.30f", "0.3 x the knob of a bush's lean"),
        (HEADER, "TwigRadLo = 0.35f, TwigRadHi = 0.85f", "smoothstep(0.35^2, 0.85^2;"),
        (HEADER, "TwigHeightLo = 0.30f, TwigHeightHi = 0.70f", "smoothstep(0.3, 0.7; h / height)"),
        (HEADER, "TwigHalfFloor = 0.5f", "at least 0.5 m"),
        (NEWH, "TreeMin = 3.0f", "measures at least 3 m tall"),
        (NEWH, "StillTol = 0.3f", "move at most 0.3 m in 60 frames"),
        (NEWH, "StillFrames = 60", "in 60 frames"),
        (HEADER, "TreeLo = 2.0f, TreeHi = 3.5f", "a mesh over 2 m tall (a full tree from 3.5 m)")]


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
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    rows = "\n".join(l for l in texts[README].split("\n") if l.startswith("| `BB_WIND_TWIGS"))
    for path, const, value in TIES:
        if texts[path].count(const) != 1 or value not in rows:
            raise SystemExit("tie check: %r against the README rows (%r)" % (const, value))
    # the shelter block's words must end before the box keys (r117's layout constants, read from its header)
    lay = open(os.path.join(ROOT, G + "shadps4/video_core/host_shaders/wind_shelter_layout.h"), "r", encoding="utf-8").read()
    def define(name):
        for line in lay.split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "#define" and parts[1] == name:
                return int(parts[2].rstrip("uU"))
        raise SystemExit("r117's layout header has no %s" % name)
    block_end = define("WS_BLOCK_WORD") + define("WS_HEADER_WORDS") + define("WS_N") * define("WS_N")
    twig_at = int([l for l in texts[NEWH].split("\n") if "inline constexpr std::uint32_t TwigAt =" in l][0].split("=")[1].strip(" ;"))
    if twig_at < block_end or twig_at % 4:
        raise SystemExit("layout check: TwigAt %d lies inside r117's field block (ends at word %d)" % (twig_at, block_end))
    # the shader rule and the C++ rule use the same constants, in both emitters
    for path in (EMIT, LIFT):
        for name in ("TwigRad2Lo", "TwigRad2Inv", "TwigHeightLo", "TwigHeightInv", "TwigHalfFloor", "TreeBit"):
            if texts[path].count("W::" + name) + texts[path].count("BbWindTwigs::" + name) != 1:
                raise SystemExit("text check: %s does not use %s exactly once" % (path, name))
    for edits in EDITS.values():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("new text must be ASCII with LF in the script")
            if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
                raise SystemExit("a local path in the patch's text")
    for path, content in NEW_FILES.items():
        if not all(ord(c) < 128 for c in content) or "\r" in content:
            raise SystemExit("new file text must be ASCII with LF in the script")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R89D_ROOT)" % ROOT)
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
    # new files: absent = clean, the same text = applied, anything else refused
    new_state = {}
    for path, content in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            new_state[path] = "clean"
        else:
            have = open(full, "rb").read().decode("utf-8").replace("\r\n", "\n")
            if have != content:
                raise SystemExit("REFUSED %s: exists and is not this patch's file" % path)
            new_state[path] = "applied"
    states = {p[5] for p in plan} | set(new_state.values())
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % kv for kv in new_state.items()))
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
        for path, content in NEW_FILES.items():
            out[path] = content
        return out

    def write_all(texts, eols):
        for path, text in texts.items():
            full = os.path.join(ROOT, path)
            tmp = full + ".r89dtmp"
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(tmp, "wb").write(text.replace("\n", eols.get(path, "\r\n")).encode("utf-8"))
            os.replace(tmp, full)

    if cmd == "check":
        if state == "applied":
            cur = {p[0]: p[4] for p in plan}
            for path in NEW_FILES:
                cur[path] = NEW_FILES[path]
            text_checks(cur)
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
        write_all(texts, {p[0]: p[3] for p in plan})
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
        tmp = full + ".r89dtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
