// SPDX-License-Identifier: GPL-3.0-or-later
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
#include <mutex> // bbport (r89l_twigs-palette-move)
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
/// bbport (r89l_twigs-palette-move, TOOL): with BB_WIND_TWIGS_PROOF a tree word of a G-buffer draw also has this bit (free:
/// PackWord's ramp ends at bit 23): the lifter's offset counters (OffsetAt) then tell the G-buffer's vertex runs from the
/// other passes'.
inline constexpr std::uint32_t PassBit = 1u << 24;
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
/// bbport (r89f_twigs-scale): added to the version as well with BB_WIND_TWIGS_SIZE (the shader differs).
inline constexpr std::uint32_t SizeAdd = 100;
/// bbport (r89g_twigs-proof): added as well with BB_WIND_TWIGS_FIT (the weight rule differs) and with
/// BB_WIND_TWIGS_PROOF (the lifter's shader counts and tints). Their sums with BinaryAdd and SizeAdd stay
/// apart from r112's hang version (the sway and hang versions differ by 11, these are multiples of 10).
inline constexpr std::uint32_t FitAdd = 10, ProofAdd = 20;
/// bbport (r89h_twigs-alive): added as well with BB_WIND_TWIGS_PUSH (the along rule differs; the sums of the four
/// optional offsets 10, 20, 40 and 100 stay apart from each other and from r112's hang version).
inline constexpr std::uint32_t PushAdd = 40;
/// bbport (r89g_twigs-proof, TOOL): with BB_WIND_TWIGS_PROOF=1 every base slot has ProofSlotWords counters
/// behind the box keys (words from the start of the sway region's buffer): 0 vertices run, 1 finite, 2 of a tall
/// mesh (tau above 0), 3 old (box) rule weight above a tenth of the gain, 4 fit rule weight above it, 5 the weight
/// in use above it, 6 moved over 1 cm, 7 largest move (m, float bits), 8 gain, 9 lean flag, 10 ramp, 11 along
/// (m), 12 highest hc (m), 13 gust factor, 14 largest weight, 15 vertices over FitLo m above the camera.
inline constexpr std::uint32_t ProofSlotWords = 16;
inline constexpr std::uint32_t ProofAt = TwigEnd;
inline constexpr std::uint32_t ProofWords = W::BaseSlots * ProofSlotWords;
inline constexpr std::uint32_t ProofEnd = ProofAt + ProofWords;
inline constexpr std::uint32_t ProofBytes = ProofEnd * 4;
/// bbport (r89h_twigs-alive, TOOL): with the proof knob and the push rule every base slot has ChangeSlotWords more
/// counters behind the proof counters (words from the start of the sway region's buffer): 0 the largest change of
/// the push (m, float bits) between now and LagFrames frames ago, 1 the sum of the changes (mm, u32), 2 the twig
/// vertices counted, 3 the largest change of the front share F (float bits); then LagWords words the CPU writes
/// once a frame: the front phases of LagFrames frames ago (3 floats) and a flag (1.0 valid, 0.0 not yet).
inline constexpr std::uint32_t ChangeSlotWords = 4;
inline constexpr std::uint32_t ChangeAt = ProofEnd;
inline constexpr std::uint32_t ChangeWords = W::BaseSlots * ChangeSlotWords;
inline constexpr std::uint32_t LagAt = ChangeAt + ChangeWords, LagWords = 4;
inline constexpr std::uint32_t LagEnd = LagAt + LagWords;
/// bbport (r89l_twigs-palette-move, TOOL): with the proof knob every base slot has OffsetSlotWords more counters behind the
/// lag words (words from the start of the sway region's buffer): OffsetSets sets of OffsetSetWords words, set 1 the vertex
/// runs of draws whose word has PassBit (the G-buffer's), set 0 every other pass's. A set: 0 vertices counted, 1 the sum of
/// their move (mm, u32), 2 moved over 1 mm, 3 over 1 cm, 4 over 5 cm, 5 over 10 cm, 6 the largest move (m, float bits), 7 spare.
/// OffsetAdd is added to the sway shader binary version with the proof knob (the lifter's shader differs).
inline constexpr std::uint32_t OffsetSets = 2, OffsetSetWords = 8;
inline constexpr std::uint32_t OffsetSlotWords = OffsetSets * OffsetSetWords;
inline constexpr std::uint32_t OffsetAt = LagEnd;
inline constexpr std::uint32_t OffsetWords = W::BaseSlots * OffsetSlotWords;
inline constexpr std::uint32_t OffsetEnd = OffsetAt + OffsetWords;
inline constexpr std::uint32_t OffsetAdd = 400;
/// bbport (r89m_twigs-no-tear): added to the shader binary version with the twigs on (the proof's tint is gone: the lifter's shader
/// differs), and CapAdd as well with the cap on (BB_WIND_TWIGS_CAP, the sway shaders carry the soft cap).
/// bbport (r89n_twigs-visible): BoostAdd is added with the twigs on, with the cap on or off (the shaders' boost, TwigCap and
/// TwigRest differ from r89m's): no cached shader of build 65 is reused.
/// bbport (r89o_wind-chains-twigs-visible): BoostAdd 16000 -> 20000 (the shaders' TwigBoost and TwigCap differ again: no cached shader of
/// build 72 is reused; 20000 and 28000 are not r89n's 16000 and 28000 of the cap on, and not r89m's 4000 and 12000).
inline constexpr std::uint32_t FixAdd = 4000, CapAdd = 8000, BoostAdd = 20000;
static_assert(OffsetAt % 4 == 0 && OffsetSetWords % 4 == 0 && OffsetSets == 2, "the offset sets are 16-byte aligned");
static_assert((W::PackWord(3, 1, 1023, 255) & PassBit) == 0 && (PassBit & W::WordOn) == 0 && PassBit != (1u << 13) &&
                  PassBit != TreeBit,
              "PassBit lies outside PackWord's fields and is neither r112's HangBit nor TreeBit");
inline constexpr std::uint32_t LagFrames = 15;
static_assert(ChangeAt % 4 == 0 && LagAt % 4 == 0 && ChangeSlotWords % 4 == 0 && LagWords == 4,
              "the lag words are one aligned vec4");
inline constexpr float ProofGain = 5.0f;       ///< a tree word's move is multiplied by this with the proof knob
inline constexpr std::uint32_t ProofLines = 6; ///< tree meshes named in one report
static_assert(ProofAt % 4 == 0 && ProofSlotWords % 4 == 0, "the counters are 16-byte aligned");
/// The CPU's judgement of a sun-drawn skinned stream (a character, a prop or a tree): the keys are
/// first read JudgeFrames frames after its slot was taken (the GPU is done with the frames read) and
/// again StillFrames frames later; a tree is at least TreeMin m tall, whose box and heights moved
/// at most StillTol m between the two reads (a walking character's box moves metres in a second),
/// and not larger than TreeMax m (a stream that spans a level is not a tree).
inline constexpr std::uint64_t JudgeFrames = 8, StillFrames = 60, GiveUpFrames = 600;
inline constexpr float TreeMin = 3.0f, TreeMax = 40.0f, BoxMax = 80.0f, StillTol = 0.3f;
/// bbport (r89e_twigs-big-trees): the rule for static cut-out meshes (Kind::Other with a cut-out pixel
/// shader: the big bare trees): height SmallMinH to SmallMaxH, larger horizontal box width between
/// SmallAspectLo and SmallAspectHi of the height, smaller width at least SmallThin of the larger, at
/// most SmallInstMax draws of the stream in a frame; its vertex count between SmallMinVerts and
/// SmallMaxVerts; at most SmallLiveMax streams measured at once; FarShare samples SmallSample vertices;
/// the log's lines: SmallLogJudged for judged streams, SmallLogRefused for the cheap check's refusals.
inline constexpr float SmallMinH = 4.0f, SmallMaxH = TreeMax;
/// bbport (r89k_twigs-opaque-word): a limb piece of a tree (BbWindTrees::LimbOf) must be at least this tall in the world
/// (the lean's tree weight starts at W::TreeLo)
inline constexpr float LimbMinH = 3.0f;
/// bbport (r89r_twigs-limb-units): BB_WIND_TWIGS_LIMB_MIN_H (read once, default LimbMinH, 1 or more up to 10: the lean's tree weight starts
/// at W::TreeLo): the world height a limb piece's box needs (Judge). The default is the old constant.
[[nodiscard]] inline float LimbMinHeight() {
    static const float v = std::clamp(W::ParseNumber(std::getenv("BB_WIND_TWIGS_LIMB_MIN_H"), LimbMinH), 1.0f, 10.0f);
    return v;
}
inline constexpr float SmallAspectLo = 0.20f, SmallAspectHi = 1.8f, SmallThin = 0.30f;
/// bbport (r89m_twigs-no-tear): a mesh whose larger horizontal box side is over this is more than one tree: refused ('box-many').
inline constexpr float OneTreeBox = 30.0f;
inline constexpr std::uint32_t SmallMinVerts = 120, SmallMaxVerts = 250000, SmallInstMax = 2;
inline constexpr std::uint32_t SmallLiveMax = 96, SmallSample = 2048;
inline constexpr std::uint32_t SmallLogJudged = 64, SmallLogRefused = 24;
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
    int small = 1; ///< bbport (r89e): BB_WIND_TWIGS_SMALL 0 off, 1 the rule, 2 log only, 3 loose
    int size = 1;  ///< bbport (r89f): BB_WIND_TWIGS_SIZE 0 off, 1 the size factor
    int fit = 1;   ///< bbport (r89g): BB_WIND_TWIGS_FIT 0 the box shape rule, 1 the fit rule
    bool proof = false; ///< bbport (r89g, TOOL): BB_WIND_TWIGS_PROOF=1
    int push = 1;  ///< bbport (r89h): BB_WIND_TWIGS_PUSH 0 r89g's along rule, 1 the push rule
};

/// BB_WIND_TWIGS as a number: 0-TwigsMax, unset, empty or unreadable TwigsDefault.
[[nodiscard]] inline float ParseTwigs(const char* text) {
    return std::clamp(W::ParseNumber(text, TwigsDefault), 0.0f, TwigsMax);
}

[[nodiscard]] inline Knob ParseKnob(const char* twigs, const char* reach, bool sway_on, bool lean,
                                    const char* small = nullptr, const char* size = nullptr,
                                    const char* fit = nullptr, const char* proof = nullptr,
                                    const char* push = nullptr) {
    Knob k;
    k.twigs = ParseTwigs(twigs);
    {   // bbport (r89e_twigs-big-trees): BB_WIND_TWIGS_SMALL 0-3, unset or unreadable 1
        const float s = W::ParseNumber(small, 1.0f);
        k.small = s >= 2.5f ? 3 : (s >= 1.5f ? 2 : (s >= 0.5f ? 1 : 0));
    }
    k.size = W::ParseNumber(size, 1.0f) >= 0.5f ? 1 : 0; // bbport (r89f_twigs-scale): 0 or 1, unreadable 1
    k.fit = W::ParseNumber(fit, 1.0f) >= 0.5f ? 1 : 0;   // bbport (r89g_twigs-proof): 0 or 1, unreadable 1
    k.proof = W::ParseNumber(proof, 0.0f) >= 0.5f;       // (TOOL) 1 only when asked
    k.push = W::ParseNumber(push, 1.0f) >= 0.5f ? 1 : 0; // bbport (r89h_twigs-alive): 0 or 1, unreadable 1
    const float r = W::ParseNumber(reach, 1.0f);
    k.reach = r >= 1.5f ? 2 : (r >= 0.5f ? 1 : 0);
    k.asked = k.twigs > 0.0f;
    k.on = k.asked && sway_on && lean;
    return k;
}

/// Read once, at the first use (the pipeline cache's first key, or the motion buffer).
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = ParseKnob(std::getenv("BB_WIND_TWIGS"), std::getenv("BB_WIND_TWIGS_REACH"),
                                       W::KnobOnce().on, W::LeanKnobOnce().lean,
                                       std::getenv("BB_WIND_TWIGS_SMALL"),
                                       std::getenv("BB_WIND_TWIGS_SIZE"),
                                       std::getenv("BB_WIND_TWIGS_FIT"),
                                       std::getenv("BB_WIND_TWIGS_PROOF"),
                                       std::getenv("BB_WIND_TWIGS_PUSH"));
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

/// bbport (r89e_twigs-big-trees): whether static cut-out draws are candidates (BB_WIND_TWIGS_SMALL above 0).
[[nodiscard]] inline bool ReachSmall() {
    return KnobOnce().on && KnobOnce().small >= 1;
}

/// BB_WIND_TWIGS_SMALL=2: the candidates are measured and logged, none is taken.
[[nodiscard]] inline bool SmallLogOnly() {
    return KnobOnce().small == 2;
}

/// BB_WIND_TWIGS_SMALL=3: the shape and instance checks are dropped (height, still and vertices stay).
[[nodiscard]] inline bool SmallLoose() {
    return KnobOnce().small >= 3;
}

/// bbport (r89f_twigs-scale): whether the twig weight carries the size factor (BB_WIND_TWIGS_SIZE above 0, the
/// twigs on). Read once with the shaders: the sway shaders then differ (BinaryOffset).
[[nodiscard]] inline bool SizeOn() {
    return KnobOnce().on && KnobOnce().size >= 1;
}

/// bbport (r89g_twigs-proof): whether the twig weight is the fit rule (BB_WIND_TWIGS_FIT above 0, the twigs on).
/// Read once with the shaders (BinaryOffset).
/// bbport (r89j_twigs-pick-trees): BB_WIND_TWIGS_TREES (read once; default 0): the tree draws are taken by the shape of
/// their own vertices, each draw its own mesh (bbport_wind_trees.h), and the twig weight is the mesh rule, not the fit
/// rule. Needs the twigs on and BB_WIND_TWIGS_SMALL above 0.
[[nodiscard]] inline bool TreesWanted() {
    static const bool wanted = W::ParseNumber(std::getenv("BB_WIND_TWIGS_TREES"), 0.0f) >= 0.5f;
    return wanted && KnobOnce().on && KnobOnce().small >= 1;
}

[[nodiscard]] inline bool FitOn() {
    return KnobOnce().on && KnobOnce().fit >= 1 && !TreesWanted(); // bbport (r89j): TREES: the mesh rule
}

/// bbport (r89g_twigs-proof, TOOL): whether the proof knob is on (BB_WIND_TWIGS_PROOF=1, the twigs on).
[[nodiscard]] inline bool ProofOn() {
    return KnobOnce().on && KnobOnce().proof;
}

/// bbport (r89m_twigs-no-tear): whether a tree word's weight is soft capped (BbWindSway::TwigSoftCap): BB_WIND_TWIGS_CAP (read once,
/// default 1; 0 gives r89l's move back) with the twigs on. Read once with the shaders (BinaryOffset).
[[nodiscard]] inline bool CapOn() {
    static const bool wanted = W::ParseNumber(std::getenv("BB_WIND_TWIGS_CAP"), 1.0f) >= 0.5f;
    return wanted && KnobOnce().on;
}

/// bbport (r89h_twigs-alive): whether knob `k` asks for the push rule (the twigs on, the fit rule on, PUSH above 0).
[[nodiscard]] inline bool PushWanted(const Knob& k) {
    return k.on && k.fit >= 1 && k.push >= 1;
}

/// bbport (r89h_twigs-alive): whether the twigs' along-wind move is the push rule (BB_WIND_TWIGS_PUSH above 0 with the
/// fit rule). Read once with the shaders (BinaryOffset).
[[nodiscard]] inline bool PushOn() {
    return PushWanted(KnobOnce());
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
    return On() ? std::max(region_bytes, ProofOn() ? OffsetEnd * 4 : TwigBytes) // bbport (r89g_twigs-proof, r89h, r89l)
                : region_bytes;
}

/// The box keys at ResetKey (the buffer's words up to TwigEnd, when on), called once after the
/// region's words were zeroed.
inline void InitWords(std::uint32_t* sway_words) {
    if (On() && sway_words != nullptr) {
        for (std::uint32_t i = 0; i < TwigWords; ++i) {
            sway_words[TwigAt + i] = W::ResetKey;
        }
        if (ProofOn()) { // bbport (r89h_twigs-alive, TOOL): the change counters and the lag words at 0
            for (std::uint32_t i = 0; i < ChangeWords + LagWords; ++i) {
                sway_words[ChangeAt + i] = 0;
            }
        }
        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the counters at 0
            for (std::uint32_t i = 0; i < ProofWords; ++i) {
                sway_words[ProofAt + i] = 0;
            }
        }
        if (ProofOn()) { // bbport (r89l_twigs-palette-move, TOOL): the offset counters at 0
            for (std::uint32_t i = 0; i < OffsetWords; ++i) {
                sway_words[OffsetAt + i] = 0;
            }
        }
    }
}

/// A slot's four box keys back to ResetKey (the slot goes to another stream, or another size).
inline void ResetSlot(std::uint32_t* words, std::uint32_t slot) {
    if (On() && slot < W::BaseSlots) {
        for (std::uint32_t i = 0; i < TwigSlotWords; ++i) {
            words[TwigAt + slot * TwigSlotWords + i] = W::ResetKey;
        }
        if (ProofOn()) { // bbport (r89h_twigs-alive, TOOL): the slot's change counters at 0
            for (std::uint32_t i = 0; i < ChangeSlotWords; ++i) {
                words[ChangeAt + slot * ChangeSlotWords + i] = 0;
            }
        }
        if (ProofOn()) { // bbport (r89g_twigs-proof, TOOL): the slot's counters at 0
            for (std::uint32_t i = 0; i < ProofSlotWords; ++i) {
                words[ProofAt + slot * ProofSlotWords + i] = 0;
            }
        }
        if (ProofOn()) { // bbport (r89l_twigs-palette-move, TOOL): the slot's offset counters at 0
            for (std::uint32_t i = 0; i < OffsetSlotWords; ++i) {
                words[OffsetAt + slot * OffsetSlotWords + i] = 0;
            }
        }
    }
}

/// Added to the serialized sway shader binary version: 0 off (the shader is as before).
[[nodiscard]] inline std::uint32_t BinaryOffset() {
    return On() ? BinaryAdd + (SizeOn() ? SizeAdd : 0u) + (FitOn() ? FitAdd : 0u) + // bbport (r89f, r89g)
                      (ProofOn() ? ProofAdd + OffsetAdd : 0u) + (PushOn() ? PushAdd : 0u) + // bbport (r89h, r89l)
                      FixAdd + BoostAdd + (CapOn() ? CapAdd : 0u)                                      // bbport (r89m)
                : 0u;
}

/// Whether a saved shader's version is a sway or hang version with any of the optional offsets
/// (r117's `shelter_add`, this patch's BinaryAdd): the load then compares it with the one expected.
[[nodiscard]] inline bool KnownVersion(std::uint32_t version, std::uint32_t sway, std::uint32_t hang,
                                       std::uint32_t shelter_add) {
    for (const std::uint32_t a : {0u, shelter_add}) {
        for (std::uint32_t m = 0; m <= 16; ++m) { // bbport (r89f, r89g, r89h): 0, then BinaryAdd with each subset
            const std::uint32_t k = m == 0 ? 0u : m - 1u; // of the four optional offsets (size, fit, proof, push)
            const std::uint32_t b = m == 0 ? 0u
                                           : BinaryAdd + ((k & 1u) != 0 ? SizeAdd : 0u) +
                                                 ((k & 2u) != 0 ? FitAdd : 0u) + ((k & 4u) != 0 ? ProofAdd : 0u) +
                                                 ((k & 8u) != 0 ? PushAdd : 0u);
            // bbport (r89l_twigs-palette-move): and the offset counters' OffsetAdd (the proof knob's shaders)
            // bbport (r89m_twigs-no-tear): and FixAdd, FixAdd + CapAdd (the twigs' shaders since r89m)
            // bbport (r89n_twigs-visible): and FixAdd + BoostAdd, FixAdd + CapAdd + BoostAdd (the twigs' shaders since r89n)
            const std::uint32_t fixes[5] = {0u, FixAdd, FixAdd + CapAdd, FixAdd + BoostAdd, FixAdd + CapAdd + BoostAdd};
            for (std::uint32_t ci = 0; ci < (m == 0 ? 1u : 5u); ++ci) { // (the fixes only with BinaryAdd: m above 0)
                const std::uint32_t c = fixes[ci];
                if (version == sway + a + b + c || version == hang + a + b + c ||
                    version == sway + a + b + c + OffsetAdd || version == hang + a + b + c + OffsetAdd) {
                    return true;
                }
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

/// bbport (r89e_twigs-big-trees): why a static cut-out mesh measuring `m` is no tree (a string literal),
/// nullptr when it is one. `moved`: how far its box and heights moved between the two reads (m);
/// `per_frame`: the most draws of its stream in one frame; `loose`: BB_WIND_TWIGS_SMALL=3 (no shape or
/// instance check). Pure: engine/tests/test_wind_sway.cpp runs it.
[[nodiscard]] inline const char* SmallWhy(const Measure& m, float moved, std::uint32_t per_frame,
                                          bool loose, float min_height = SmallMinH) {
    const float h = m.crown - m.base;
    const float wx = m.x_hi - m.x_lo, wz = m.z_hi - m.z_lo;
    const float wmax = std::max(wx, wz), wmin = std::min(wx, wz);
    if (!(h > 0.0f) || !(wmax >= 0.0f) || !(wmin >= 0.0f)) {
        return "height";
    }
    if (!(moved <= StillTol)) {
        return "moved";
    }
    if (h < min_height) { // bbport (r89k_twigs-opaque-word): LimbMinH for a limb piece
        return "short";
    }
    if (h > SmallMaxH) {
        return "tall";
    }
    if (loose) {
        return nullptr;
    }
    if (wmax > BoxMax) {
        return "box";
    }
    if (per_frame > SmallInstMax) {
        return "instanced";
    }
    if (wmax > SmallAspectHi * h) {
        return "wide";
    }
    if (wmax < SmallAspectLo * h) {
        return "slim";
    }
    if (wmin < SmallThin * wmax) {
        return "thin";
    }
    if (wmax > OneTreeBox) { // bbport (r89m_twigs-no-tear): a box of several trees (the shape rules above passed)
        return "box-many";
    }
    return nullptr;
}

/// The cheap check on a new stream's vertex count: nullptr, "verts-few" or "verts-many".
[[nodiscard]] inline const char* SmallPrefilter(std::uint32_t verts) {
    return verts < SmallMinVerts ? "verts-few" : (verts > SmallMaxVerts ? "verts-many" : nullptr);
}

/// What the CPU read of a static cut-out stream at its first sight (for the log; far_share is not used
/// by the rule).
struct SmallInfo {
    std::uint32_t verts = 0;
    float far_share = -1.0f;            ///< see FarShare (-1: not read)
    std::uint64_t vs = 0, ps = 0;       ///< the vertex and pixel shaders' hashes
    bool palette = false;               ///< it read a small bone palette
    std::uint64_t draws = 0;            ///< draws seen
    std::uint64_t frame = 0;            ///< the frame `frame_draws` counts
    std::uint32_t frame_draws = 0, max_per_frame = 0;
};

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
    // bbport (r89e_twigs-big-trees): a static cut-out candidate (SmallWhy judges it)
    bool small = false, loose = false, logged = false;
    bool limb = false;                     ///< bbport (r89k_twigs-opaque-word): a limb piece (BbWindTrees::LimbOf)
    std::uint32_t per_frame = 0;           ///< most draws of its stream in one frame so far
    const char* why = nullptr;             ///< the reason it is no tree (a string literal)
    Measure last;                          ///< its measure at the verdict (not ok: none)
};

class Book {
public:
    /// bbport (r89e_twigs-big-trees): the stream's info (nullptr: none), set or replaced, and the stream
    /// refused by a cheap check (an entry with the verdict NotTree and no slot).
    [[nodiscard]] SmallInfo* FindInfo(std::uint64_t stream) {
        const auto found = infos.find(stream);
        return found == infos.end() ? nullptr : &found->second;
    }

    SmallInfo& SetInfo(std::uint64_t stream, const SmallInfo& info) {
        if (infos.size() >= BookMost && infos.find(stream) == infos.end()) {
            infos.clear();
        }
        return infos[stream] = info;
    }

    Entry& Refuse(std::uint64_t stream, std::uint32_t size, std::uint64_t frame, const char* why) {
        Entry& e = Touch(stream, size, 0xffffffffu, true, frame);
        e.small = true;
        e.verdict = Verdict::NotTree;
        e.why = why;
        return e;
    }

    /// How many candidates are being measured (a slot, no verdict, drawn within the last 2 frames);
    /// counted once a frame.
    [[nodiscard]] std::uint32_t LiveSmall(std::uint64_t frame) {
        if (live_frame != frame) {
            live_frame = frame;
            live = 0;
            for (const auto& item : entries) {
                const Entry& e = item.second;
                live += e.small && e.verdict == Verdict::Waiting && e.slot != 0xffffffffu &&
                                e.seen + 2 >= frame
                            ? 1u
                            : 0u;
            }
        }
        return live;
    }

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
    std::unordered_map<std::uint64_t, SmallInfo> infos; // bbport (r89e_twigs-big-trees)
    std::uint64_t live_frame = ~std::uint64_t(0);
    std::uint32_t live = 0;
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
            e.why = "no-keys"; // bbport (r89e_twigs-big-trees)
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
    e.last = m;
    if (e.small) { // bbport (r89e_twigs-big-trees): a static cut-out candidate
        e.why = SmallWhy(m, Moved(e.snap, m), e.per_frame, e.loose, e.limb ? LimbMinHeight() : SmallMinH);
        e.verdict = e.why == nullptr ? Verdict::Tree : Verdict::NotTree;
        return e.verdict;
    }
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
    // bbport (r89e_twigs-big-trees): static cut-out candidates: draws seen, given a tree's word,
    // still judged (ramp 0), refused, left waiting for a free measuring place; meshes the cheap
    // check refused
    std::uint64_t small_seen = 0, small_tree = 0, small_judging = 0, small_refused = 0,
                  small_deferred = 0, small_pre = 0;
};

/// The meshes in use at a report: tall (above W::TreeLo) ones by who takes them.
struct Census {
    std::uint32_t lone = 0, sun = 0, sun_not = 0;
    std::array<float, TallestShown> tallest{};
    // bbport (r89e_twigs-big-trees): static cut-out trees, those still judged, and meshes over
    // SmallMaxH (not trees) with the tallest
    std::uint32_t small = 0, small_wait = 0, huge = 0;
    float huge_top = 0.0f;

    void Huge(float height) {
        ++huge;
        huge_top = std::max(huge_top, height);
    }

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

// bbport (r89e_twigs-big-trees): the far share and the log's texts of the static cut-out candidates.

/// The share (0-1) of up to SmallSample vertices, sampled evenly from `count` float vectors `stride`
/// bytes apart starting at `data`, that lie farther than half the largest radius from the mesh's longest
/// local axis (a trunk and a few limbs: low; a wall or a flat card: high). -1 when it cannot be told
/// (fewer than 8 vertices, a stride under 12, a vertex that is not a number). Log only.
[[nodiscard]] inline float FarShare(const unsigned char* data, std::uint32_t stride, std::uint32_t count) {
    if (data == nullptr || stride < 12 || count < 8) {
        return -1.0f;
    }
    const std::uint32_t n = std::min(count, SmallSample);
    const auto fetch = [&](std::uint32_t i, std::array<float, 3>& v) {
        std::memcpy(v.data(), data + (std::uint64_t(i) * count / n) * stride, 12);
        return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
    };
    std::array<float, 3> lo{1e30f, 1e30f, 1e30f}, hi{-1e30f, -1e30f, -1e30f}, v{};
    std::uint32_t good = 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (!fetch(i, v)) {
            continue;
        }
        ++good;
        for (int c = 0; c < 3; ++c) {
            lo[c] = std::min(lo[c], v[c]);
            hi[c] = std::max(hi[c], v[c]);
        }
    }
    if (good < 8) {
        return -1.0f;
    }
    int up = 0;
    for (int c = 1; c < 3; ++c) {
        up = hi[c] - lo[c] > hi[up] - lo[up] ? c : up;
    }
    const int a = (up + 1) % 3, b = (up + 2) % 3;
    const float ca = 0.5f * (lo[a] + hi[a]), cb = 0.5f * (lo[b] + hi[b]);
    float rmax = 0.0f;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (fetch(i, v)) {
            rmax = std::max(rmax, std::hypot(v[a] - ca, v[b] - cb));
        }
    }
    if (!(rmax > 1e-6f)) {
        return -1.0f;
    }
    std::uint32_t far_count = 0;
    for (std::uint32_t i = 0; i < n; ++i) {
        if (fetch(i, v) && std::hypot(v[a] - ca, v[b] - cb) > 0.5f * rmax) {
            ++far_count;
        }
    }
    return float(far_count) / float(good);
}

/// One candidate's line when it is judged or refused by the cheap check (under 300 characters):
/// "Wind twigs (r89e) candidate TREE: height ... m, box X x Z m (box/height R, thin T), verts V, far F,
/// palette P, vs H ps H, draws N per frame M, why ...". `info` may be null.
inline void SmallLine(const Entry& e, const SmallInfo* info, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const Measure& m = e.last;
    const float h = m.crown - m.base, wx = m.x_hi - m.x_lo, wz = m.z_hi - m.z_lo;
    const float wmax = std::max(wx, wz), wmin = std::min(wx, wz);
    char shape[96];
    if (m.ok && h > 0.0f && wmax > 0.0f) {
        std::snprintf(shape, sizeof(shape), "height %.1f m, box %.1f x %.1f m (box/height %.2f, thin %.2f)",
                      double(h), double(wx), double(wz), double(wmax / h), double(wmin / wmax));
    } else {
        std::snprintf(shape, sizeof(shape), "not measured");
    }
    std::snprintf(out, size,
                  "Wind twigs (r89e) candidate %s%s: %s, verts %u, far %.2f, palette %d, vs %08x ps %08x, "
                  "draws %llu per frame %u, why %s",
                  e.verdict == Verdict::Tree ? "TREE" : "refused", e.limb ? " (limb piece)" : "", shape,
                  info ? info->verts : 0u,
                  double(info ? info->far_share : -1.0f), info && info->palette ? 1 : 0,
                  info ? static_cast<unsigned>(info->vs & 0xffffffffu) : 0u,
                  info ? static_cast<unsigned>(info->ps & 0xffffffffu) : 0u, n(info ? info->draws : 0),
                  info ? info->max_per_frame : 0u, e.why != nullptr ? e.why : "-");
}

/// The once line of the static cut-out candidates (BB_WIND_TWIGS_SMALL above 0), under 300 characters.
inline void SmallOnceText(const Knob& k, char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs (r89e, BB_WIND_TWIGS_SMALL=%d): static cut-outs of %.0f-%.0f m (box/height "
                  "%.2f-%.1f, thin %.2f, at most %u draws a frame, %u+ vertices) are judged by their "
                  "world box for %u frames and stir if still; %s",
                  k.small, double(SmallMinH), double(SmallMaxH), double(SmallAspectLo), double(SmallAspectHi),
                  double(SmallThin), SmallInstMax, SmallMinVerts, unsigned(JudgeFrames + StillFrames),
                  k.small == 2 ? "log only, none taken" : (k.small >= 3 ? "loose rule" : "default rule"));
}

/// The line every W::ReportFrames frames for the candidates (under 300 characters).
inline void SmallReportText(const Census& census, const Stats& st, const Knob& k, char* out,
                            std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    std::snprintf(out, size,
                  "Wind twigs (r89e, BB_WIND_TWIGS_SMALL=%d): small-skeleton cut-outs: meshes %u tree, %u "
                  "judging; draws %llu seen, %llu tree, %llu judging, %llu refused (%llu meshes by the cheap "
                  "check), %llu deferred; over %.0f m: %u meshes (tallest %.1f m)",
                  k.small, census.small, census.small_wait, n(st.small_seen), n(st.small_tree),
                  n(st.small_judging), n(st.small_refused), n(st.small_pre), n(st.small_deferred),
                  double(SmallMaxH), census.huge, double(census.huge_top));
}

// bbport (r89f_twigs-scale): the size-scaled tips' numbers and log texts.

/// A twig tip's move (TipAt) at wind `speed` on a tip `h` m above its mesh's lowest point: TipAt x
/// BbWindSway::SizeFactor(h) when `sized`.
[[nodiscard]] inline Tip TipSized(float speed, float scale, float wave, float twigs, float h, bool sized) {
    Tip t = TipAt(speed, scale, wave, twigs, false);
    const float k = sized ? W::SizeFactor(h) : 1.0f;
    t.lean *= k;
    t.front *= k;
    return t;
}

/// The once line of BB_WIND_TWIGS_SIZE (under 640 characters): the tip at 1.5 and 4 m/s at 6, 12, 20 and 37 m.
inline void SizeOnceText(const Knob& k, float scale, float wave, char* out, std::size_t capacity) {
    const float heights[4] = {W::SizeRefH, 12.0f, 20.0f, 37.0f};
    char at_slow[176], at_fast[176];
    at_slow[0] = 0;
    at_fast[0] = 0;
    for (int i = 0; i < 4; ++i) {
        const Tip a = TipSized(BbWind::DefaultSpeed, scale, wave, k.twigs, heights[i], k.size >= 1);
        const Tip b = TipSized(BbWind::MaxSpeed, scale, wave, k.twigs, heights[i], k.size >= 1);
        const std::size_t n_slow = std::strlen(at_slow), n_fast = std::strlen(at_fast);
        std::snprintf(at_slow + n_slow, sizeof(at_slow) - n_slow, "%s%.1f/%.1f (%.0f m)", i == 0 ? "" : ", ",
                      double(a.lean * 100.0f), double(a.front * 100.0f), double(heights[i]));
        std::snprintf(at_fast + n_fast, sizeof(at_fast) - n_fast, "%s%.1f/%.1f (%.0f m)", i == 0 ? "" : ", ",
                      double(b.lean * 100.0f), double(b.front * 100.0f), double(heights[i]));
    }
    std::snprintf(out, capacity,
                  "Wind twigs (r89f, BB_WIND_TWIGS_SIZE=%d): a twig tip moves x (its height above the mesh's "
                  "lowest point / %.0f m), 1 to %.0f; tip cm lean/gust front at 1.5 m/s: %s; at 4 m/s: %s",
                  k.size, double(W::SizeRefH), double(W::SizeMax), at_slow, at_fast);
}

/// The line every W::ReportFrames frames (under 320 characters): the tree draws taken (the sun-drawn and the
/// static cut-outs), the tallest tree and its tip's move at this wind.
inline void SizeReportText(const Census& census, const Stats& st, const BbWind::Snapshot& wind, const Knob& k,
                           float scale, float wave, char* out, std::size_t capacity) {
    const float speed = std::isfinite(wind.speed) ? std::max(wind.speed, 0.0f) : 0.0f;
    const float top = census.tallest[0];
    const Tip tip = TipSized(speed, scale, wave, k.twigs, top, k.size >= 1);
    std::snprintf(out, capacity,
                  "Wind twigs (r89f, BB_WIND_TWIGS_SIZE=%d): %llu tree draws with size-scaled tips; tallest %.1f m "
                  "(x%.2f): tip %.1f cm lean, %.1f cm gust front at %.2f m/s",
                  k.size, static_cast<unsigned long long>(st.tree_draws + st.small_tree), double(top),
                  double(W::SizeFactor(top)), double(tip.lean * 100.0f), double(tip.front * 100.0f),
                  double(speed));
}

// bbport (r89g_twigs-proof): the fit rule's once line, and the proof knob's counters, verdict and texts.

/// The once line of BB_WIND_TWIGS_FIT (under 520 characters).
inline void FitOnceText(const Knob& k, char* out, std::size_t size) {
    if (k.fit >= 1) {
        std::snprintf(out, size,
                      "Wind twigs (r89g, BB_WIND_TWIGS_FIT=1): a tall mesh's twig weight is a rule of the vertex's "
                      "height over the camera (smoothstep %.0f to %.0f m, x%.2f, x the size factor at height + %.0f m "
                      "when BB_WIND_TWIGS_SIZE is on), not a shape in the mesh's world box (the box of a stream that "
                      "holds many trees is not one tree's)",
                      double(W::FitLo), double(W::FitHi), double(W::FitShare), double(W::FitEye));
    } else {
        std::snprintf(out, size,
                      "Wind twigs (r89g, BB_WIND_TWIGS_FIT=0): the box shape rule of r89d (weight from the vertex's "
                      "place in the mesh's world box)");
    }
}

/// The once line of BB_WIND_TWIGS_PROOF (TOOL; under 520 characters).
inline void ProofOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs (r89g, BB_WIND_TWIGS_PROOF=1, TOOL): a tree word's move x%.0f (its weight then soft capped "
                  "at twice the cap of r89m; the yellow tint is gone: the game's outputs are normals and UV pairs); "
                  "%u counters a mesh slot (%u bytes of "
                  "the sway buffer); a 'Wind twigs proof (r89g)' line per tree mesh (at most %u) every %u frames "
                  "with a verdict",
                  double(ProofGain), ProofSlotWords, ProofBytes, ProofLines, unsigned(W::ReportFrames));
}

/// The GPU's counters of one base slot (see ProofSlotWords); the floats are as the shader stored them.
struct ProofCounts {
    std::uint32_t verts = 0, fin = 0, tall = 0, old_w = 0, fit_w = 0, used_w = 0, moved = 0, high = 0;
    float move_max = 0.0f, gain = 0.0f, lean = 0.0f, ramp = 0.0f, along = 0.0f, gust = 0.0f, hc_max = 0.0f,
          w_max = 0.0f;
    // bbport (r89h_twigs-alive, TOOL): the push's change over LagFrames frames (ChangeAt words)
    std::uint32_t change_sum = 0, change_n = 0; ///< mm summed, twig vertices counted
    float change_max = 0.0f, front_max = 0.0f;  ///< m, a share of the front (0-1)
};

/// The counters of `slot` read from the sway region's words (a volatile read: the GPU writes them; at most 16
/// words, at a report). A slot out of range reads as all 0.
[[nodiscard]] inline ProofCounts ReadProof(const std::uint32_t* words, std::uint32_t slot) {
    ProofCounts c;
    if (words == nullptr || slot >= W::BaseSlots) {
        return c;
    }
    const volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;
    const auto number = [&](std::uint32_t k) { return std::uint32_t(v[k]); };
    const auto real = [&](std::uint32_t k) {
        const std::uint32_t bits = v[k];
        float f = 0.0f;
        std::memcpy(&f, &bits, sizeof(f));
        return f;
    };
    c.verts = number(0);
    c.fin = number(1);
    c.tall = number(2);
    c.old_w = number(3);
    c.fit_w = number(4);
    c.used_w = number(5);
    c.moved = number(6);
    c.move_max = real(7);
    c.gain = real(8);
    c.lean = real(9);
    c.ramp = real(10);
    c.along = real(11);
    c.hc_max = real(12);
    c.gust = real(13);
    c.w_max = real(14);
    c.high = number(15);
    // bbport (r89h_twigs-alive, TOOL): the push's change counters (4 words of this slot behind the proof's)
    const volatile std::uint32_t* const ch = words + ChangeAt + slot * ChangeSlotWords;
    const std::uint32_t change_bits = ch[0], front_bits = ch[3];
    std::memcpy(&c.change_max, &change_bits, sizeof(float));
    std::memcpy(&c.front_max, &front_bits, sizeof(float));
    c.change_sum = ch[1];
    c.change_n = ch[2];
    return c;
}

/// The slot's counters back to 0 (after a report).
inline void ClearProof(std::uint32_t* words, std::uint32_t slot) {
    if (words == nullptr || slot >= W::BaseSlots) {
        return;
    }
    volatile std::uint32_t* const v = words + ProofAt + slot * ProofSlotWords;
    for (std::uint32_t k = 0; k < ProofSlotWords; ++k) {
        v[k] = 0;
    }
    volatile std::uint32_t* const ch = words + ChangeAt + slot * ChangeSlotWords; // bbport (r89h_twigs-alive)
    for (std::uint32_t k = 0; k < ChangeSlotWords; ++k) {
        ch[k] = 0;
    }
}

// bbport (r89l_twigs-palette-move, TOOL): the offset counters (OffsetAt: two sets of OffsetSetWords words a base slot, the
// G-buffer's, whose word has PassBit, and every other pass's), the note of which emitter made a vertex shader, and the line
// that names the twig offset in the palette path.

/// One set of the offset counters of a slot (see OffsetAt).
struct OffsetSet {
    std::uint32_t verts = 0, sum_mm = 0, over_1mm = 0, over_1cm = 0, over_5cm = 0, over_10cm = 0;
    float move_max = 0.0f; ///< m
};

struct OffsetCounts {
    std::array<OffsetSet, OffsetSets> pass{}; ///< 0 the other passes, 1 the G-buffer
};

/// The offset counters of `slot` (a volatile read: the GPU writes them; at report time). A slot out of range reads as all 0.
[[nodiscard]] inline OffsetCounts ReadOffset(const std::uint32_t* words, std::uint32_t slot) {
    OffsetCounts c;
    if (words == nullptr || slot >= W::BaseSlots) {
        return c;
    }
    for (std::uint32_t s = 0; s < OffsetSets; ++s) {
        const volatile std::uint32_t* const v = words + OffsetAt + slot * OffsetSlotWords + s * OffsetSetWords;
        OffsetSet& o = c.pass[s];
        o.verts = v[0];
        o.sum_mm = v[1];
        o.over_1mm = v[2];
        o.over_1cm = v[3];
        o.over_5cm = v[4];
        o.over_10cm = v[5];
        const std::uint32_t bits = v[6];
        std::memcpy(&o.move_max, &bits, sizeof(float));
    }
    return c;
}

/// The slot's offset counters back to 0 (after a report).
inline void ClearOffset(std::uint32_t* words, std::uint32_t slot) {
    if (words == nullptr || slot >= W::BaseSlots) {
        return;
    }
    volatile std::uint32_t* const v = words + OffsetAt + slot * OffsetSlotWords;
    for (std::uint32_t k = 0; k < OffsetSlotWords; ++k) {
        v[k] = 0;
    }
}

/// The sum over slots of one set.
struct OffsetSum {
    std::uint64_t verts = 0, sum_mm = 0, over_1mm = 0, over_1cm = 0, over_5cm = 0, over_10cm = 0;
    float move_max = 0.0f; ///< m
    void Add(const OffsetSet& s) {
        verts += s.verts;
        sum_mm += s.sum_mm;
        over_1mm += s.over_1mm;
        over_1cm += s.over_1cm;
        over_5cm += s.over_5cm;
        over_10cm += s.over_10cm;
        if (std::isfinite(s.move_max)) {
            move_max = std::max(move_max, s.move_max);
        }
    }
};

/// The tree meshes of one path (palette or static) in a report window: the CPU's draws and meshes, the GPU's counters by set,
/// and the vertex shaders (the low 32 bits of their hashes, at most VsMost) with the emitter that made them (ShaderPathOf).
struct OffsetTotals {
    static constexpr std::size_t VsMost = 6;
    std::uint64_t meshes = 0, draws = 0, gbuffer_draws = 0;
    std::array<OffsetSum, OffsetSets> pass{};
    std::array<std::uint32_t, VsMost> vs{};
    std::array<std::uint8_t, VsMost> vs_path{};
    std::size_t vs_n = 0;
    void Add(std::uint64_t slot_draws, std::uint64_t slot_gbuffer, const OffsetCounts& c, std::uint32_t vs_hash,
             std::uint8_t path) {
        ++meshes;
        draws += slot_draws;
        gbuffer_draws += slot_gbuffer;
        for (std::size_t s = 0; s < OffsetSets; ++s) {
            pass[s].Add(c.pass[s]);
        }
        if (vs_hash != 0) {
            bool known = false;
            for (std::size_t i = 0; i < vs_n; ++i) {
                known = known || vs[i] == vs_hash;
            }
            if (!known && vs_n < VsMost) {
                vs[vs_n] = vs_hash;
                vs_path[vs_n] = path;
                ++vs_n;
            }
        }
    }
};

/// Which emitter made the vertex shaders of a hash (the pipeline cache notes it when it compiles one): bit 0 the lifter, bit 1
/// the recompiler. Thread safe (shaders compile on several threads).
[[nodiscard]] inline std::mutex& PathMutex() {
    static std::mutex m;
    return m;
}

[[nodiscard]] inline std::unordered_map<std::uint64_t, std::uint8_t>& PathMap() {
    static std::unordered_map<std::uint64_t, std::uint8_t> map;
    return map;
}

inline void NoteShaderPath(std::uint64_t hash, bool lifted) {
    const std::lock_guard<std::mutex> lock(PathMutex());
    std::uint8_t& bits = PathMap()[hash];
    bits = static_cast<std::uint8_t>(bits | (lifted ? 1u : 2u));
}

[[nodiscard]] inline std::uint8_t ShaderPathOf(std::uint64_t hash) {
    const std::lock_guard<std::mutex> lock(PathMutex());
    const auto found = PathMap().find(hash);
    return found != PathMap().end() ? found->second : std::uint8_t{0};
}

[[nodiscard]] inline const char* PathName(std::uint8_t path) {
    switch (path) {
    case 1:
        return "lifted";
    case 2:
        return "RECOMPILED (no counters, no tint)";
    case 3:
        return "lifted and recompiled variants";
    default:
        return "path not noted (shader from the cache)";
    }
}

/// The once line of the offset counters (under 700 characters).
inline void OffsetOnceText(char* out, std::size_t size) {
    std::snprintf(out, size,
                  "Wind twigs offset (r89l, TOOL, with BB_WIND_TWIGS_PROOF=1): every %u frames a line names the twig offset the "
                  "lifter's shaders counted for every tree mesh, the palette path (draws that read a small bone palette) and "
                  "the static one, the G-buffer's vertex runs (the word's PassBit, set for G-buffer draws only) apart from the "
                  "other passes', and whether each vertex shader of the palette meshes was made by the lifter or the "
                  "recompiler (which has no counters); %u counters a mesh slot (%u bytes of the sway buffer)",
                  unsigned(W::ReportFrames), OffsetSlotWords, OffsetWords * 4u);
}

/// The window's line (under 1400 characters): the twig offset in the palette path (draws, G-buffer draws, meshes, mean and
/// largest move of the counted vertex runs), the G-buffer's runs and the other passes' apart, the real offset (the proof's
/// x ProofGain taken out), the emitters of the palette meshes' vertex shaders and the static path in short.
inline void OffsetLine(const OffsetTotals& pal, const OffsetTotals& stat, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const auto mean_cm = [](std::uint64_t sum_mm, std::uint64_t verts) {
        return verts > 0 ? static_cast<double>(sum_mm) / static_cast<double>(verts) * 0.1 : 0.0;
    };
    const auto max_cm = [](const OffsetTotals& t) {
        return static_cast<double>(std::max(t.pass[0].move_max, t.pass[1].move_max)) * 100.0;
    };
    const auto all_mean = [&](const OffsetTotals& t) {
        return mean_cm(t.pass[0].sum_mm + t.pass[1].sum_mm, t.pass[0].verts + t.pass[1].verts);
    };
    char paths[320] = "";
    for (std::size_t i = 0; i < pal.vs_n; ++i) {
        const std::size_t used = std::strlen(paths);
        std::snprintf(paths + used, sizeof(paths) - used, "%svs %08x %s", i == 0 ? "" : ", ",
                      static_cast<unsigned>(pal.vs[i]), PathName(pal.vs_path[i]));
    }
    const double gain = static_cast<double>(ProofGain);
    std::snprintf(out, size,
                  "Wind twigs offset (r89l, TOOL): twig offset in palette path: %llu draws (%llu in the G-buffer), %llu meshes, "
                  "mean %.2f cm, max %.2f cm (proof x%.0f, weight soft capped since r89m, so the columns divided by x5 read low: %.2f cm, %.2f cm); G-buffer vertex runs "
                  "%llu, mean %.2f cm, max %.2f cm, over 1 cm %llu, over 5 cm %llu, over 10 cm %llu; other passes' vertex runs "
                  "%llu, mean %.2f cm, max %.2f cm; shader paths: %s; static path: %llu draws (%llu in the G-buffer), %llu "
                  "meshes, mean %.2f cm, max %.2f cm, G-buffer vertex runs %llu",
                  n(pal.draws), n(pal.gbuffer_draws), n(pal.meshes), all_mean(pal), max_cm(pal), gain, all_mean(pal) / gain,
                  max_cm(pal) / gain, n(pal.pass[1].verts), mean_cm(pal.pass[1].sum_mm, pal.pass[1].verts),
                  static_cast<double>(pal.pass[1].move_max) * 100.0, n(pal.pass[1].over_1cm), n(pal.pass[1].over_5cm),
                  n(pal.pass[1].over_10cm), n(pal.pass[0].verts), mean_cm(pal.pass[0].sum_mm, pal.pass[0].verts),
                  static_cast<double>(pal.pass[0].move_max) * 100.0, pal.vs_n == 0 ? "none" : paths, n(stat.draws),
                  n(stat.gbuffer_draws), n(stat.meshes), all_mean(stat), max_cm(stat), n(stat.pass[1].verts));
}

/// bbport (r89m_twigs-no-tear): the once line of the cap (under 560 characters).
inline void CapOnceText(char* out, std::size_t size) {
    // bbport (r89n_twigs-visible): the hard bound by the limits, and a tip's move in a full gust front at the strongest wind
    const double real = static_cast<double>(W::TwigCap) *
                        (std::hypot(static_cast<double>(W::MaxAlong), static_cast<double>(W::MaxCross)) +
                         1.4143 * static_cast<double>(W::MaxLeaf)) * 100.0;
    const double crest = static_cast<double>(W::TwigCap) * static_cast<double>(W::BendMax) *
                         static_cast<double>(W::TwigRest + W::TwigPush) * 100.0;
    const double ratio = static_cast<double>(BbWind::MaxSpeed / BbWind::DefaultSpeed) *
                         static_cast<double>(BbWind::MaxSpeed / BbWind::DefaultSpeed);
    if (CapOn()) {
        std::snprintf(out, size,
                      "Wind twigs cap (r89n, BB_WIND_TWIGS_CAP=1): a tree word's weight w is boosted x%.0f and soft capped at %.2f "
                      "(w / (1 / %.0f + w / cap): smooth), so a twig tip moves up to about %.0f cm in a full gust front at 4 m/s "
                      "(BB_WIND_SWAY 1; hard bound %.0f cm), %.0f times less at 1.5 m/s, and neighbouring vertices move together; "
                      "a strictly judged mesh whose box is over %.0f m is refused (box-many; not with TREES, palette or SMALL=3)",
                      static_cast<double>(W::TwigBoost), static_cast<double>(W::TwigCap), static_cast<double>(W::TwigBoost), crest,
                      real, ratio, static_cast<double>(OneTreeBox));
    } else {
        std::snprintf(out, size,
                      "Wind twigs cap (r89m, BB_WIND_TWIGS_CAP=0): off, the weight of a tree word is not capped (r89l's move); "
                      "a strictly judged mesh whose box is over %.0f m is still refused (box-many; not with TREES, palette or SMALL=3)",
                      static_cast<double>(OneTreeBox));
    }
}

/// bbport (r89h_twigs-alive, TOOL): what the change counters say of the push's time motion (a string literal).
[[nodiscard]] inline const char* ChangeVerdict(const ProofCounts& c) {
    if (c.change_n == 0) {
        return "no twig vertex counted with a lag (push off, the lag words not valid yet, or no twig share)";
    }
    if (!(c.change_max >= 0.001f)) {
        return "STILL: the push changes by under 1 mm over the lag (the phases do not advance on the GPU, or no wind)";
    }
    return "moving";
}

/// What the counters point at, the first break in the order the shader meets them (a string literal).
[[nodiscard]] inline const char* ProofVerdict(const ProofCounts& c) {
    if (c.verts == 0) {
        return "no vertex counted: the twig code of this mesh's shader did not run (a draw on a pipeline without "
               "it, or the recompiler's shader, which has no counters)";
    }
    if (c.fin < c.verts / 2) {
        return "most vertices are not finite: the world position rebuilt from the clip position is wrong";
    }
    if (c.tall == 0) {
        return "tau is 0: the mesh's height from its keys is under 2 m";
    }
    if (!(c.ramp > 0.0f)) {
        return "ramp 0: the sway word's ramp byte is 0";
    }
    if (!(c.gain > 0.0f)) {
        return "gain 0: the view's twig gain is 0";
    }
    if (!(c.lean > 0.0f)) {
        return "lean 0: the view's lean flag is 0";
    }
    if (c.used_w == 0) {
        return "weight 0: no vertex has a twig weight above a tenth of the gain (the rule puts it on no vertex)";
    }
    if (!(c.move_max >= 0.001f)) {
        return "weight above 0 but the move is under 1 mm: the wind's amplitude at these vertices is 0";
    }
    return "OK: the shader moves vertices (see the largest move)";
}

/// One mesh's proof line (under 760 characters): the CPU's draw counts (`draws` of the stream since the last
/// line, `patched` of them on pipelines with the sway bit, `pipelines` distinct ones, at most 4; `verts_each`
/// the stream's vertex count, 0 unknown), the GPU's counters and the verdict.
inline void ProofLine(const ProofCounts& c, std::uint32_t slot, std::uint64_t draws, std::uint64_t patched,
                      std::uint32_t pipelines, std::uint32_t verts_each, char* out, std::size_t size) {
    const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
    const double expected = double(draws) * double(verts_each);
    const double ratio = expected > 0.0 ? double(c.verts) / expected : 0.0;
    std::snprintf(out, size,
                  "Wind twigs proof (r89g): slot %u: %llu draws (%llu on pipelines with the sway bit, %u pipelines) "
                  "x %u vertices; shader counted %u vertices (%.2f of draws x vertices), %u finite, %u of a tall mesh; "
                  "weight above a tenth of the gain: old rule %u, fit rule %u, in use %u; moved over 1 cm %u; read "
                  "gain %.3f lean %.1f ramp %.2f along %.3f m gust %.2f; highest %.1f m over the camera (%u over "
                  "%.0f m), largest weight %.3f, largest move %.1f cm; time motion over %u frames: %u twig vertices, "
                  "%.0f vertices run per draw, change mean %.2f cm, largest %.2f cm, front share changed by up to "
                  "%.2f (%s)%s; verdict: %s",
                  slot, n(draws), n(patched), pipelines, verts_each, c.verts, ratio, c.fin, c.tall, c.old_w, c.fit_w,
                  c.used_w, c.moved, double(c.gain), double(c.lean), double(c.ramp), double(c.along), double(c.gust),
                  double(c.hc_max), c.high, double(W::FitLo), double(c.w_max), double(c.move_max * 100.0f),
                  unsigned(LagFrames), c.change_n, draws > 0 ? double(c.verts) / double(draws) : 0.0,
                  c.change_n > 0 ? double(c.change_sum) / double(c.change_n) * 0.1 : 0.0,
                  double(c.change_max * 100.0f), double(c.front_max), ChangeVerdict(c),
                  c.change_sum > 4000000000u ? " [sum may have wrapped]" : "", ProofVerdict(c));
}

// bbport (r89h_twigs-alive): the push rule's numbers and texts, and the proof knob's lag step.

/// A twig tip's move (m) by the push rule: steady (no front) and the peak (a full front), at a gust factor of 1.
struct PushTip {
    float steady = 0.0f, peak = 0.0f;
};

/// The push rule's tip at wind `speed` (m/s), BB_WIND_SWAY `scale`, BB_WIND_TWIGS `twigs`, `hc` m over the camera (the
/// fit weight, with the size factor when `sized`, times D (TwigRest, and TwigRest + TwigPush)).
[[nodiscard]] inline PushTip PushTipAt(float speed, float scale, float twigs, float hc, bool sized) {
    const W::LeanCurve c = W::LeanAt(speed, scale, 1.0f, false);
    const float weight = W::TwigRatio * twigs * (W::FitShare * W::Smooth01(hc, W::FitLo, W::FitInv)) *
                         (sized ? W::SizeFactor(hc + W::FitEye) : 1.0f);
    PushTip t;
    t.steady = weight * c.bend * W::TwigRest;
    t.peak = weight * c.bend * (W::TwigRest + W::TwigPush);
    return t;
}

/// "steady/peak (h m), ..." in cm for tips 8, 20 and 38 m over the camera (under 100 characters).
inline void PushTipsText(float speed, float scale, float twigs, bool sized, char* out, std::size_t size) {
    const float heights[3] = {8.0f, 20.0f, 38.0f};
    if (size == 0) {
        return;
    }
    out[0] = 0;
    for (int i = 0; i < 3; ++i) {
        const PushTip t = PushTipAt(speed, scale, twigs, heights[i], sized);
        const std::size_t used = std::strlen(out);
        std::snprintf(out + used, size - used, "%s%.2f/%.1f (%.0f m)", i == 0 ? "" : ", ", double(t.steady * 100.0f),
                      double(t.peak * 100.0f), double(heights[i]));
    }
}

/// The once line of BB_WIND_TWIGS_PUSH (under 560 characters).
inline void PushOnceText(const Knob& k, float scale, char* out, std::size_t size) {
    if (!PushWanted(k)) {
        std::snprintf(out, size,
                      "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=%d): off (the push rule needs BB_WIND_TWIGS_FIT=1); the twigs "
                      "move by r89g's along rule",
                      k.push);
        return;
    }
    char slow[128], fast[128];
    PushTipsText(BbWind::DefaultSpeed, scale, k.twigs, k.size >= 1, slow, sizeof(slow));
    PushTipsText(BbWind::MaxSpeed, scale, k.twigs, k.size >= 1, fast, sizeof(fast));
    std::snprintf(out, size,
                  "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=1): a twig is pushed downwind by gust fronts and settles back: "
                  "steady %.2f of the bend, push up to %.1f x the bend x the front share squared (fronts %.0f m apart, "
                  "carried by the wind: every %.1f s at 4 m/s, %.1f s at 1.5 m/s); steady/peak cm at 4 m/s: %s; at "
                  "1.5 m/s: %s",
                  double(W::TwigRest), double(W::TwigPush), double(W::EnvWavelength[0]),
                  double(W::EnvWavelength[0] / BbWind::MaxSpeed), double(W::EnvWavelength[0] / BbWind::DefaultSpeed), fast,
                  slow);
}

/// The line every W::ReportFrames frames (under 400 characters): the tree draws taken and the steady/peak tip moves
/// at this wind.
inline void PushReportText(const Stats& st, const BbWind::Snapshot& wind, const Knob& k, float scale, char* out,
                           std::size_t size) {
    const float speed = std::isfinite(wind.speed) ? std::max(wind.speed, 0.0f) : 0.0f;
    char tips[128];
    PushTipsText(speed, scale, k.twigs, k.size >= 1, tips, sizeof(tips));
    std::snprintf(out, size,
                  "Wind twigs (r89h, BB_WIND_TWIGS_PUSH=%d): %llu tree draws pushed by gust fronts; at %.2f m/s "
                  "steady/peak cm at 8/20/38 m over the camera: %s",
                  k.push, static_cast<unsigned long long>(st.tree_draws + st.small_tree), double(speed), tips);
}

/// bbport (r89h_twigs-alive, TOOL): once a frame (at the first view's fill) keeps the front phases of this fill and
/// writes the ones of LagFrames fills ago, and a validity flag, into the lag words (LagAt) the lifter's change counters
/// read. `view` is the filled view (its phases at RippleA + 2, RippleA + 3 and RippleB).
inline void ProofLagStep(std::uint32_t* words, const float* view) {
    static std::array<std::array<float, 3>, LagFrames + 1> ring{};
    static std::uint64_t count = 0;
    if (words == nullptr || view == nullptr) {
        return;
    }
    const std::array<float, 3> now = {view[W::RippleA + 2], view[W::RippleA + 3], view[W::RippleB]};
    const std::uint64_t at = count++;
    ring[at % ring.size()] = now;
    const bool valid = at >= LagFrames;
    const std::array<float, 3>& lag = valid ? ring[(at + 1) % ring.size()] : now;
    volatile std::uint32_t* const out = words + LagAt;
    for (std::uint32_t k = 0; k < 3; ++k) {
        std::uint32_t bits = 0;
        std::memcpy(&bits, &lag[k], sizeof(bits));
        out[k] = bits;
    }
    const float flag = valid ? 1.0f : 0.0f;
    std::uint32_t flag_bits = 0;
    std::memcpy(&flag_bits, &flag, sizeof(flag_bits));
    out[3] = flag_bits;
}

} // namespace BbWindTwigs
