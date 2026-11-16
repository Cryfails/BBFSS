# r46b_plant-rule: the plants' whole-polygon lamp shadows (fault B), second step.
# check|apply|revert (revert restores byte for byte). On top of r1..r47 (r46_lamp-cards and
# r47_still-check applied).
#
# WHY. r46's level 1 keeps every cut-out drawn with a skeleton in lamp rays (hair, cloth). In the
# game the plants that throw the rectangles turned out to be exactly that: beds of weed of 60,900
# to 132,160 triangles a draw, drawn with a skeleton by the camera pass only, so level 1 left
# out 55 instances against the old rule's 49 and the picture did not change; level 2 (every
# cut-out) removed the dark band but takes a character's own cut-outs out as well.
# What tells the two apart with what the engine sees: the game gives a character a sun shadow
# and these plants none. At the spot all 106 skinned cut-outs that stay are of vertices a sun
# shadow pass draws (the character's six among them, each drawn by both passes), and the 20
# that no sun shadow pass draws are the plants.
#
# WHAT.
#  1. rt_lamp_cards.h: BB_RT_LAMP_CARDS gets level 3, the new default (0 the rule of before,
#     1 and 2 as they were): as 1, and a cut-out with a skeleton stays out too when its vertices
#     are "lone". LampCard() takes `lone` as its last argument. LampLone (one position stream):
#     a sun shadow pass draw of it with a skeleton marks it for good (LampLoneSunDraw); a camera
#     pass draw of it with a skeleton and a discarding pixel shader counts the frame
#     (LampLoneCameraDraw) when a sun shadow pass drew some skeleton on that frame or one of the
#     two before; after LampLoneFrames (32) such frames without a sun shadow pass draw of its
#     own it is lone (LampLoneOf). So a character keeps its lamp shadow where no sun shadow pass
#     draws skeletons at all, during the first 32 frames, and for good once a sun shadow pass
#     drew its vertices even once (a lone stream is taken back then).
#  2. vk_rt_shadow.cpp, PrepareDraw: the map lone_streams by the address of the position stream
#     (not by the key: a pass may draw another index list of the same vertices), kept before
#     the draw filters; at 16,384 streams it forgets those not drawn for 600 frames that are not
#     lone, then everything. Entry::stream, Entry::lone (looked up by PrepareScene only when the
#     map's verdicts changed, lone_gen). PrepareScene passes `lone` to LampCard; the instance
#     mask line is untouched. With experiment 9223372036854775808 set, or BB_RT_LAMP_CARDS=0,
#     LampCard returns the rule of before from the same two fields as before: the old masks.
#  3. The 600-frame line "Ray tracing cut-out cards (r46)": rule "3 (cut-outs without a
#     skeleton, and those with one that no sun shadow pass draws)"; "... N counted as moving,
#     N with a skeleton), N skinned cut-outs kept in lamp rays (N whose vertices a sun shadow
#     pass draws, N not yet 32 frames without one); the old rule would leave out N, rule 1 N,
#     rule 2 N, rule 3 N; ...; N position streams drawn with a skeleton known, N draws a frame
#     went through them, a sun shadow pass last drew a skeleton N frames ago (-1: never)"; each
#     of "the largest left out" says ", with a skeleton, its vertices in no sun shadow pass"
#     (or "in a sun shadow pass" at level 2).
#  4. tests/test_rt_lamp_cards.cpp: the 64 combinations of the six signs under the four levels
#     and the bit, the bed of weed, hair, and LampLone's count (a plant, several draws a frame,
#     a far cascade's turn, no sun shadow pass, a stale one, taken back).
# No shader, pipeline or buffer change; no new experiment bit (the rule is under r46's bit 63).
#
# PROOF IN THE GAME (dev install, 3840x2160, the save's spot, the character not moved, ray
# traced lamp shadows at full resolution, BB_RT_STILL=off; new = mask 0, old = bit 63, one run):
#  default camera: new "75 instances left out (... 20 with a skeleton), 106 skinned cut-outs
#  kept (106 whose vertices a sun shadow pass draws, 0 not yet 32 frames without one); the old
#  rule would leave out 49, rule 1 55, rule 2 181, rule 3 75"; old "49 ... 126 skinned cut-outs
#  kept". The dark band with the straight top edge on the pillar and the wall behind the weed
#  bed is gone (r46b_a_weedbed_new_old.jpg), as with level 2. Top-down camera: 22 against 17
#  (rule 1 18, rule 2 56); the character's own lamp shadows are the same in old and new
#  (r46b_b_character_new_old.jpg). The same counts with graphics_sun_far_shadows=rare.
#
# The tree: the one the environment variable R46B_ROOT names; without it the current directory
# when that is the root of a source tree (run from there), else <tree>/. Nothing is
# changed in place: every new text is written beside its target and moved over it, and a failure
# puts back what was already moved. Source files keep their CRLF line ends. The (old, new) pairs
# below were made by machine from the copy of the files taken before the round's first edit and
# the tree the game was run on (each old text is found exactly once when its turn comes, each
# new one exactly once on the way back). Each text starts on the line after its opening quotes.
# Revert r46b before r47 or r46.

import os
import sys

# The tree: R46B_ROOT when it is set; else the current directory when that is the root of a
# source tree (the script is run from there); else <tree>/, as the rounds before.
ROOT = os.environ.get("R46B_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
R = E + "gpu/shadps4/video_core/renderer_vulkan/"
TESTS = E + "tests/"

TMP = ".r46btmp"  # a new text waits under this name beside its target (main)

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    R + "rt_lamp_cards.h": [
        (r"""
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r46_lamp-cards): which instances of the ray tracing scene lamp rays leave out as
// cut-out cards (RtShadow::PrepareScene, vk_rt_shadow.cpp). No Vulkan here:
// tests/test_rt_lamp_cards.cpp builds this header alone and runs the code the engine runs.
//
// A lamp ray (point_shadow_ray.comp) cannot test a texture: the scene's bottom-level structures
// hold positions only and are opaque. A cut-out card (a leaf of ivy, a weed: a flat polygon
// whose texture cuts the shape out) is hit as its whole polygon and throws a rectangle of
// shadow. So cards stay out of lamp rays and cast no lamp shadow, as in the game, which has no
// lamp shadows at all.
//
// The rule of before knew a card only by the texture of its sun shadow pass draw, read only
// when that draw was the entry's first of a frame, and only while the entry did not count as
// moving. A card therefore kept its lamp shadow when the camera pass alone drew it, when its
// camera pass draw came first in the frame, when it once counted as moving (that is never taken
// back), or when its sun shadow pass shader samples no texture. The plants did.
//
// Now an entry is a cut-out when any draw of it ever showed one: a sun shadow pass draw whose
// pixel shader samples a texture, or a camera pass draw whose pixel shader discards (its own,
// or another draw of the same mesh). Neither the order of the passes nor "moving" is read. A
// cut-out drawn with a skeleton (hair, cloth on a body) keeps its lamp shadow at level 1: its
// polygons follow the body closely, and without them a character would cast a bald shadow.

#include <cstdint>

namespace Vulkan {

/// BB_RT_LAMP_CARDS: 0 the rule of before, 1 cut-outs without a skeleton stay out of lamp rays,
/// 2 every cut-out stays out (hair and cloth then cast no lamp shadow either).
inline constexpr std::uint32_t LampCardLevelDefault = 1;
inline constexpr std::uint32_t LampCardLevelMost = 2;

/// Whether lamp rays leave an entry out as a cut-out card.
/// `old` (the experiment bit) or level 0: the rule of before, from `shadow_card` (the entry's
/// first draw of the frame was a sun shadow pass draw with a texture, when it last was one) and
/// `dynamic` (it counts as moving).
/// Else from what was ever seen of the entry: `card_shadow` (a sun shadow pass draw of it
/// samples a texture), `card_camera` (a camera pass draw of it, or of its mesh, discards) and
/// `skinned` (a draw of it had a skeleton).
[[nodiscard]] constexpr bool LampCard(bool old, std::uint32_t level, bool shadow_card,
                                      bool dynamic, bool card_shadow, bool card_camera,
                                      bool skinned) noexcept {
    if (old || level == 0) {
        return shadow_card && !dynamic;
    }
    const bool cutout = card_shadow || card_camera;
    return level == 1 ? cutout && !skinned : cutout;
}

} // namespace Vulkan
""",
         r"""
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r46_lamp-cards): which instances of the ray tracing scene lamp rays leave out as
// cut-out cards (RtShadow::PrepareScene, vk_rt_shadow.cpp). No Vulkan here:
// tests/test_rt_lamp_cards.cpp builds this header alone and runs the code the engine runs.
//
// A lamp ray (point_shadow_ray.comp) cannot test a texture: the scene's bottom-level structures
// hold positions only and are opaque. A cut-out card (a leaf of ivy, a weed: a flat polygon
// whose texture cuts the shape out) is hit as its whole polygon and throws a rectangle of
// shadow. So cards stay out of lamp rays and cast no lamp shadow, as in the game, which has no
// lamp shadows at all.
//
// The rule of before knew a card only by the texture of its sun shadow pass draw, read only
// when that draw was the entry's first of a frame, and only while the entry did not count as
// moving. A card therefore kept its lamp shadow when the camera pass alone drew it, when its
// camera pass draw came first in the frame, when it once counted as moving (that is never taken
// back), or when its sun shadow pass shader samples no texture. The plants did.
//
// Now an entry is a cut-out when any draw of it ever showed one: a sun shadow pass draw whose
// pixel shader samples a texture, or a camera pass draw whose pixel shader discards (its own,
// or another draw of the same mesh). Neither the order of the passes nor "moving" is read. A
// cut-out drawn with a skeleton (hair, cloth on a body) keeps its lamp shadow at level 1: its
// polygons follow the body closely, and without them a character would cast a bald shadow.
//
// bbport (r46b_plant-rule): the plants that threw the rectangles are cut-outs drawn WITH a
// skeleton (whole beds of weed, 60,000 to 130,000 triangles a draw), so level 1 kept them. What
// tells them from hair and cloth: the game gives a character a sun shadow and the plants none.
// A cut-out with a skeleton whose vertices no sun shadow pass draws, while the camera pass
// draws it on frame after frame on which the sun shadow pass does draw skeletons, is "lone"
// (LampLone below) and stays out of lamp rays at level 3, the default. A character keeps its
// lamp shadow wherever the sign cannot be read: where no sun shadow pass draws any skeleton
// (no sun in the place, a scene without cascades), until LampLoneFrames such frames have
// passed, and for good once a sun shadow pass drew its vertices even once.

#include <cstdint>

namespace Vulkan {

/// BB_RT_LAMP_CARDS: 0 the rule of before, 1 cut-outs without a skeleton stay out of lamp rays,
/// 2 every cut-out stays out (hair and cloth then cast no lamp shadow either), 3 (the default)
/// as 1, and the cut-outs with a skeleton that no sun shadow pass draws (plants) stay out too.
inline constexpr std::uint32_t LampCardLevelPlain = 1;
inline constexpr std::uint32_t LampCardLevelEvery = 2;
inline constexpr std::uint32_t LampCardLevelLone = 3;
inline constexpr std::uint32_t LampCardLevelDefault = LampCardLevelLone;
inline constexpr std::uint32_t LampCardLevelMost = 3;

/// Whether lamp rays leave an entry out as a cut-out card.
/// `old` (the experiment bit) or level 0: the rule of before, from `shadow_card` (the entry's
/// first draw of the frame was a sun shadow pass draw with a texture, when it last was one) and
/// `dynamic` (it counts as moving).
/// Else from what was ever seen of the entry: `card_shadow` (a sun shadow pass draw of it
/// samples a texture), `card_camera` (a camera pass draw of it, or of its mesh, discards),
/// `skinned` (a draw of it had a skeleton) and `lone` (its vertices are LampLoneState::Lone).
[[nodiscard]] constexpr bool LampCard(bool old, std::uint32_t level, bool shadow_card,
                                      bool dynamic, bool card_shadow, bool card_camera,
                                      bool skinned, bool lone) noexcept {
    if (old || level == 0) {
        return shadow_card && !dynamic;
    }
    const bool cutout = card_shadow || card_camera;
    if (level == LampCardLevelPlain) {
        return cutout && !skinned;
    }
    if (level == LampCardLevelEvery) {
        return cutout;
    }
    return cutout && (!skinned || lone);
}

/// Frames a cut-out with a skeleton must be drawn by the camera pass, on each of which the sun
/// shadow pass draws skeletons but not this one's vertices, before it counts as lone. Far sun
/// cascades may be drawn only every 8th frame (graphics_sun_far_shadows), and a character that
/// comes into view is in the camera pass a frame or two before its cascade's turn.
inline constexpr std::uint32_t LampLoneFrames = 32;
/// A sun shadow pass draw of a skeleton this many frames back still says that the game draws
/// sun shadows of characters now (this frame's may come after the camera pass's draws).
inline constexpr std::uint64_t LampLoneSunAge = 2;

/// What is known of one position stream (a mesh's vertices) that is drawn with a skeleton.
struct LampLone {
    std::uint64_t seen = 0;   ///< frame of its last draw by either pass (RtShadow ages by it)
    std::uint64_t frame = 0;  ///< the last frame counted in `frames`
    std::uint32_t frames = 0; ///< camera pass cut-out frames counted, up to LampLoneFrames
    bool sun = false;         ///< a sun shadow pass drew it, kept for good
};

/// What a stream is taken for: not known (no such draw of it yet), drawn by a sun shadow pass
/// (a character's: for good), waiting (no sun shadow pass draw yet, not enough frames counted)
/// or lone (a plant by the sign above).
enum class LampLoneState : std::uint8_t { None, Sun, Waiting, Lone };

[[nodiscard]] constexpr LampLoneState LampLoneOf(const LampLone& known) noexcept {
    return known.sun                        ? LampLoneState::Sun
           : known.frames >= LampLoneFrames ? LampLoneState::Lone
                                            : LampLoneState::Waiting;
}

/// A sun shadow pass draws the stream with a skeleton on `frame`. True when LampLoneOf changed.
constexpr bool LampLoneSunDraw(LampLone& known, std::uint64_t frame) noexcept {
    const bool changed = !known.sun;
    known.seen = frame;
    known.sun = true;
    return changed;
}

/// The camera pass draws the stream on `frame` with a skeleton and a discarding pixel shader;
/// `sun_frame`: the last frame on which a sun shadow pass drew any skeleton (`sun_any`: one ever
/// did). Each frame counts once. True when LampLoneOf changed.
constexpr bool LampLoneCameraDraw(LampLone& known, std::uint64_t frame, bool sun_any,
                                  std::uint64_t sun_frame) noexcept {
    known.seen = frame;
    if (known.sun || known.frames >= LampLoneFrames || !sun_any ||
        sun_frame + LampLoneSunAge < frame || (known.frames != 0 && known.frame == frame)) {
        return false;
    }
    known.frame = frame;
    return ++known.frames >= LampLoneFrames;
}

} // namespace Vulkan
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
""",
         r"""

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/rt_lamp_cards.h" // bbport (r46b_plant-rule)
#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"
"""),
        (r"""
        bool card_mesh = false;
        bool skinned = false;
        u32 card_gen = 0;
        // The mesh and shader key (see PrepareDraw) and whether this is a promoted per instance
        // entry: a static prop identified by its bone palette, not by its draw order.
        u64 base = 0;
""",
         r"""
        bool card_mesh = false;
        bool skinned = false;
        u32 card_gen = 0;
        // bbport (r46b_plant-rule): the position stream of its draws (0: none), and what that
        // stream is taken for (LampLoneOf of lone_streams; Lone: a cut-out with a skeleton that
        // no sun shadow pass draws, a plant), as of lone_gen (looked up again by PrepareScene
        // only while that is not RtShadow::lone_gen).
        u64 stream = 0;
        LampLoneState lone = LampLoneState::None;
        u32 lone_gen = 0;
        // The mesh and shader key (see PrepareDraw) and whether this is a promoted per instance
        // entry: a static prop identified by its bone palette, not by its draw order.
        u64 base = 0;
"""),
        (r"""
    // pass's texture, from their own camera pass draw, only from another camera pass draw of
    // their mesh, with a bone palette, without the sun's mask, counting as moving), skinned
    // cut-outs kept, what each rule would leave out, and the four left out with the most
    // triangles (CardFound, each mesh once).
    std::unordered_set<u64> cutout_keys;
    u32 cutout_gen = 1;
    u32 card_rule = 0;
    u64 card_lookups = 0;
    struct CardFound {
        u64 mesh = 0, key = 0;
        u32 triangles = 0;
        bool by_shadow = false, by_camera = false, by_mesh = false, palette = false,
             instance = false, moving = false, camera_only = false;
    };
    struct CardStats {
        u32 out = 0, by_shadow = 0, by_camera = 0, by_mesh = 0, with_palette = 0,
            camera_only = 0, moving = 0, skinned_kept = 0;
        std::array<u32, 3> rule_out{};
        std::array<CardFound, 4> largest{};
    } card_stats;

""",
         r"""
    // pass's texture, from their own camera pass draw, only from another camera pass draw of
    // their mesh, with a bone palette, without the sun's mask, counting as moving), skinned
    // cut-outs kept, what each rule would leave out, and the four left out with the most
    // triangles (CardFound, each mesh once). bbport (r46b_plant-rule): and those left out
    // that have a skeleton, and of the skinned cut-outs kept: those whose vertices a sun shadow
    // pass draws, and those still waiting (LampLoneState).
    std::unordered_set<u64> cutout_keys;
    u32 cutout_gen = 1;
    u32 card_rule = 0;
    u64 card_lookups = 0;
    // bbport (r46b_plant-rule): the position streams drawn with a skeleton by a sun shadow pass,
    // or by the camera pass with a discarding pixel shader (rt_lamp_cards.h, LampLone), by
    // their address. lone_gen changes whenever a stream is new to the map or is taken for
    // something else (LampLoneOf), or the map is thinned (Entry::lone_gen). sun_skinned_frame:
    // the last frame on which a sun shadow pass drew a skeleton (sun_skinned_any: one ever
    // did). lone_draws: draws that went through the map since the last 600-frame line.
    std::unordered_map<u64, LampLone> lone_streams;
    u32 lone_gen = 1;
    u64 sun_skinned_frame = 0;
    bool sun_skinned_any = false;
    u64 lone_draws = 0;
    struct CardFound {
        u64 mesh = 0, key = 0;
        u32 triangles = 0;
        bool by_shadow = false, by_camera = false, by_mesh = false, palette = false,
             instance = false, moving = false, camera_only = false, skinned = false;
        LampLoneState lone = LampLoneState::None;
    };
    struct CardStats {
        u32 out = 0, by_shadow = 0, by_camera = 0, by_mesh = 0, with_palette = 0,
            camera_only = 0, moving = 0, skinned_kept = 0, skinned_out = 0, lone_waiting = 0,
            sun_drawn = 0;
        std::array<u32, 4> rule_out{};
        std::array<CardFound, 4> largest{};
    } card_stats;

"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""
// plants kept their lamp bit. That rule is still the one with experiment LampCardsOldBit set or
// BB_RT_LAMP_CARDS=0.
constexpr u8 LampMask = 4;
// bbport (r46_lamp-cards): BB_RT_LAMP_CARDS, read once (default LampCardLevelDefault, 1; at
// most LampCardLevelMost, 2). 0: the rule of before. 1: cut-outs without a skeleton stay out of
// lamp rays. 2: every cut-out stays out, skinned ones too (hair and cloth then cast no lamp
// shadow): for a plant that turns out to be drawn with a skeleton.
u32 LampCardLevel() {
    static const u32 level = ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_CARDS"),
                                              LampCardLevelDefault, LampCardLevelMost);
""",
         r"""
// plants kept their lamp bit. That rule is still the one with experiment LampCardsOldBit set or
// BB_RT_LAMP_CARDS=0.
constexpr u8 LampMask = 4;
// bbport (r46_lamp-cards, r46b_plant-rule): BB_RT_LAMP_CARDS, read once (default
// LampCardLevelDefault, 3; at most LampCardLevelMost, 3). 0: the rule of before. 1: cut-outs
// without a skeleton stay out of lamp rays. 2: every cut-out stays out, skinned ones too (hair
// and cloth then cast no lamp shadow). 3: as 1, and of the skinned cut-outs those whose vertices
// no sun shadow pass draws (Entry::lone): the plants that threw the rectangles are drawn with a
// skeleton, and the game gives them no sun shadow, while it gives one to every character.
// bbport (r46b_plant-rule): position streams known at most (lone_streams), and the frames a
// stream that is not lone stays known undrawn once the map is full.
constexpr std::size_t LoneStreamsMost = 16384;
constexpr u64 LoneStreamKeep = 600;
u32 LampCardLevel() {
    static const u32 level = ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_CARDS"),
                                              LampCardLevelDefault, LampCardLevelMost);
"""),
        (r"""
        }
    }

    // Camera pass casters only serve the ray traced scene (lamp shadows, bounced light).
    if (draw.camera_pass && !need_scene) {
        return 0;
""",
         r"""
        }
    }

    // bbport (r46b_plant-rule): the position streams drawn with a skeleton, by a sun shadow
    // pass (the game gives the mesh a shadow: a character's, for good) or by the camera pass with
    // a discarding pixel shader (LampLoneCameraDraw counts the frames on which the sun shadow
    // pass draws skeletons but not this one). By the stream's address and not by the key: a pass
    // may draw another index list of the same vertices (a coarser level of detail). Here,
    // before the filters below, so a sun shadow pass draw counts whatever becomes of it. A map
    // at its cap first forgets the streams not drawn for LoneStreamKeep frames that are not
    // lone (vertices written to a new address on every frame would fill it), then everything.
    if (draw.skinned && draw.positions != 0 && (draw.shadow_pass || draw.alpha)) {
        ++lone_draws;
        if (lone_streams.size() >= LoneStreamsMost) {
            std::erase_if(lone_streams, [&](const auto& item) {
                return LampLoneOf(item.second) != LampLoneState::Lone &&
                       item.second.seen + LoneStreamKeep < frame;
            });
            if (lone_streams.size() >= LoneStreamsMost) {
                lone_streams.clear();
            }
            ++lone_gen;
        }
        const auto [known, fresh] = lone_streams.try_emplace(draw.positions);
        bool changed = fresh;
        if (draw.shadow_pass) {
            sun_skinned_frame = frame;
            sun_skinned_any = true;
            changed |= LampLoneSunDraw(known->second, frame);
        } else {
            changed |= LampLoneCameraDraw(known->second, frame, sun_skinned_any,
                                          sun_skinned_frame);
        }
        lone_gen += changed ? 1 : 0;
    }

    // Camera pass casters only serve the ray traced scene (lamp shadows, bounced light).
    if (draw.camera_pass && !need_scene) {
        return 0;
"""),
        (r"""
    entry.skinned = entry.skinned || draw.skinned;
    entry.card_shadow = entry.card_shadow || (draw.shadow_pass && draw.textured);
    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
    // bbport (r47_still-check): the last camera pass draw of it, also when a sun cascade drew
    // it first on the frame (a caster the camera pass draws is looked at more often)
    if (draw.camera_pass) {
""",
         r"""
    entry.skinned = entry.skinned || draw.skinned;
    entry.card_shadow = entry.card_shadow || (draw.shadow_pass && draw.textured);
    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
    entry.stream = draw.positions; // bbport (r46b_plant-rule): the same at every draw of the key
    // bbport (r47_still-check): the last camera pass draw of it, also when a sun cascade drew
    // it first on the frame (a caster the camera pass draws is looked at more often)
    if (draw.camera_pass) {
"""),
        (r"""
        // passes and whether or not it counts as moving (rt_lamp_cards.h). cards_old: the rule
        // of before, shadow_card && !dynamic.
        const bool cutout = entry->card_camera || entry->card_mesh;
        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,
                                   entry->card_shadow, cutout, entry->skinned);
        const u8 mask =
            kept ? ShadowMask
                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
""",
         r"""
        // passes and whether or not it counts as moving (rt_lamp_cards.h). cards_old: the rule
        // of before, shadow_card && !dynamic.
        const bool cutout = entry->card_camera || entry->card_mesh;
        // bbport (r46b_plant-rule): what a skinned cut-out's vertices are taken for (a plant
        // when no sun shadow pass draws them: lone), looked up when the map's verdicts changed
        if (entry->skinned && entry->lone_gen != lone_gen && (cutout || entry->card_shadow)) {
            entry->lone_gen = lone_gen;
            const auto known = lone_streams.find(entry->stream);
            entry->lone = entry->stream != 0 && known != lone_streams.end()
                              ? LampLoneOf(known->second)
                              : LampLoneState::None;
        }
        const bool lone = entry->lone == LampLoneState::Lone;
        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,
                                   entry->card_shadow, cutout, entry->skinned, lone);
        const u8 mask =
            kept ? ShadowMask
                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
"""),
        (r"""
            card_stats.with_palette += entry->palette != 0 ? 1 : 0;
            card_stats.camera_only += (mask & ShadowMask) == 0 ? 1 : 0;
            card_stats.moving += entry->dynamic ? 1 : 0;
            // The four with the most triangles, each mesh once: a caster that is no plant (a
            // weapon, a fence, a prop whose shader discards for a fade) is named in the line.
            if (std::ranges::none_of(card_stats.largest, [&](const CardFound& c) {
""",
         r"""
            card_stats.with_palette += entry->palette != 0 ? 1 : 0;
            card_stats.camera_only += (mask & ShadowMask) == 0 ? 1 : 0;
            card_stats.moving += entry->dynamic ? 1 : 0;
            card_stats.skinned_out += entry->skinned ? 1 : 0;
            // The four with the most triangles, each mesh once: a caster that is no plant (a
            // weapon, a fence, a prop whose shader discards for a fade) is named in the line.
            if (std::ranges::none_of(card_stats.largest, [&](const CardFound& c) {
"""),
        (r"""
                                entry->palette != 0,
                                entry->instance,
                                entry->dynamic,
                                (mask & ShadowMask) == 0};
                for (CardFound& slot : card_stats.largest) {
                    if (found.triangles > slot.triangles) {
                        std::swap(slot, found);
""",
         r"""
                                entry->palette != 0,
                                entry->instance,
                                entry->dynamic,
                                (mask & ShadowMask) == 0,
                                entry->skinned,
                                entry->lone};
                for (CardFound& slot : card_stats.largest) {
                    if (found.triangles > slot.triangles) {
                        std::swap(slot, found);
"""),
        (r"""
            }
        } else if ((entry->card_shadow || cutout) && entry->skinned) {
            ++card_stats.skinned_kept;
        }
        for (u32 level = 0; level < card_stats.rule_out.size(); ++level) {
            card_stats.rule_out[level] +=
                LampCard(false, level, entry->shadow_card, entry->dynamic, entry->card_shadow,
                         cutout, entry->skinned)
                    ? 1
                    : 0;
        }
""",
         r"""
            }
        } else if ((entry->card_shadow || cutout) && entry->skinned) {
            ++card_stats.skinned_kept;
            card_stats.sun_drawn += entry->lone == LampLoneState::Sun ? 1 : 0;
            card_stats.lone_waiting += entry->lone == LampLoneState::Waiting ? 1 : 0;
        }
        for (u32 level = 0; level < card_stats.rule_out.size(); ++level) {
            card_stats.rule_out[level] +=
                LampCard(false, level, entry->shadow_card, entry->dynamic, entry->card_shadow,
                         cutout, entry->skinned, lone)
                    ? 1
                    : 0;
        }
"""),
        (r"""
                               entry->dynamic,
                               LampCard(false, LampCardLevelDefault, entry->shadow_card,
                                        entry->dynamic, entry->card_shadow, cutout,
                                        entry->skinned))) != 0;
        // Counted where the knob alone withholds the lamp bit (not a card or a starved copy
        // that is left out anyway).
        still_leave_count += leave && !card && !stale ? 1 : 0;
""",
         r"""
                               entry->dynamic,
                               LampCard(false, LampCardLevelDefault, entry->shadow_card,
                                        entry->dynamic, entry->card_shadow, cutout,
                                        entry->skinned, lone))) != 0;
        // Counted where the knob alone withholds the lamp bit (not a card or a starved copy
        // that is left out anyway).
        still_leave_count += leave && !card && !stale ? 1 : 0;
"""),
        (r"""
        const bool cards_old = BbToggle::Experiment(LampCardsOldBit);
        static constexpr const char* card_rules[] = {
            "old (the sun pass's texture on a first draw, not while moving)",
            "1 (cut-outs without a skeleton)", "2 (every cut-out)"};
        std::printf("Ray tracing cut-out cards (r46): rule %s (experiment 9223372036854775808 "
                    "%s, BB_RT_LAMP_CARDS=%u); on the last scene %u instances left out of lamp "
                    "rays as cut-out cards (%u known from the sun pass's texture, %u from their "
                    "own camera pass draw's discard, %u only from a camera pass draw of their "
                    "mesh that is not their own; %u with a bone palette, %u drawn by the camera "
                    "pass only, %u counted as moving), %u skinned cut-outs kept in lamp rays; "
                    "the old rule would leave out %u, rule 1 %u, rule 2 %u; %zu cut-out meshes "
                    "known, %zu by their key, %.2f entries a frame looked themselves up among "
                    "them%s",
                    card_rules[cards_old ? 0u : LampCardLevel()], cards_old ? "set" : "clear",
                    LampCardLevel(), card_stats.out, card_stats.by_shadow, card_stats.by_camera,
                    card_stats.by_mesh, card_stats.with_palette, card_stats.camera_only,
                    card_stats.moving, card_stats.skinned_kept, card_stats.rule_out[0],
                    card_stats.rule_out[1], card_stats.rule_out[2], cutout_meshes.size(),
                    cutout_keys.size(), double(card_lookups) / f,
                    card_stats.largest[0].triangles != 0 ? "; the largest left out:" : "");
        for (const CardFound& c : card_stats.largest) {
            if (c.triangles == 0) {
                break;
            }
            std::printf(" mesh %016llx (key %016llx), %u triangles, known from%s%s%s%s%s%s%s;",
                        static_cast<unsigned long long>(c.mesh),
                        static_cast<unsigned long long>(c.key), c.triangles,
                        c.by_shadow ? " [the sun pass's texture]" : "",
""",
         r"""
        const bool cards_old = BbToggle::Experiment(LampCardsOldBit);
        static constexpr const char* card_rules[] = {
            "old (the sun pass's texture on a first draw, not while moving)",
            "1 (cut-outs without a skeleton)", "2 (every cut-out)",
            "3 (cut-outs without a skeleton, and those with one that no sun shadow pass draws)"};
        // bbport (r46b_plant-rule): the skinned cut-outs by what their vertices are taken for,
        // rule 3's count, and the map of position streams
        std::printf("Ray tracing cut-out cards (r46): rule %s (experiment 9223372036854775808 "
                    "%s, BB_RT_LAMP_CARDS=%u); on the last scene %u instances left out of lamp "
                    "rays as cut-out cards (%u known from the sun pass's texture, %u from their "
                    "own camera pass draw's discard, %u only from a camera pass draw of their "
                    "mesh that is not their own; %u with a bone palette, %u drawn by the camera "
                    "pass only, %u counted as moving, %u with a skeleton), %u skinned cut-outs "
                    "kept in lamp rays (%u whose vertices a sun shadow pass draws, %u not yet "
                    "%u frames without one); the old rule would leave out %u, rule 1 %u, rule 2 "
                    "%u, rule 3 %u; %zu cut-out meshes known, %zu by their key, %.2f entries a "
                    "frame looked themselves up among them; %zu position streams drawn with a "
                    "skeleton known, %.1f draws a frame went through them, a sun shadow pass "
                    "last drew a skeleton %lld frames ago (-1: never)%s",
                    card_rules[cards_old ? 0u : LampCardLevel()], cards_old ? "set" : "clear",
                    LampCardLevel(), card_stats.out, card_stats.by_shadow, card_stats.by_camera,
                    card_stats.by_mesh, card_stats.with_palette, card_stats.camera_only,
                    card_stats.moving, card_stats.skinned_out, card_stats.skinned_kept,
                    card_stats.sun_drawn, card_stats.lone_waiting, LampLoneFrames,
                    card_stats.rule_out[0], card_stats.rule_out[1], card_stats.rule_out[2],
                    card_stats.rule_out[3], cutout_meshes.size(), cutout_keys.size(),
                    double(card_lookups) / f, lone_streams.size(), double(lone_draws) / f,
                    sun_skinned_any ? static_cast<long long>(frame - sun_skinned_frame) : -1ll,
                    card_stats.largest[0].triangles != 0 ? "; the largest left out:" : "");
        lone_draws = 0;
        for (const CardFound& c : card_stats.largest) {
            if (c.triangles == 0) {
                break;
            }
            std::printf(" mesh %016llx (key %016llx), %u triangles, known from%s%s%s%s%s%s%s%s;",
                        static_cast<unsigned long long>(c.mesh),
                        static_cast<unsigned long long>(c.key), c.triangles,
                        c.by_shadow ? " [the sun pass's texture]" : "",
"""),
        (r"""
                        c.palette ? ", with a bone palette" : "",
                        c.instance ? ", an instance's own entry" : "",
                        c.moving ? ", counted as moving" : "",
                        c.camera_only ? ", drawn by the camera pass only" : "");
        }
        std::printf("\n");
        card_lookups = 0;
""",
         r"""
                        c.palette ? ", with a bone palette" : "",
                        c.instance ? ", an instance's own entry" : "",
                        c.moving ? ", counted as moving" : "",
                        c.camera_only ? ", drawn by the camera pass only" : "",
                        !c.skinned                        ? ""
                        : c.lone == LampLoneState::Lone   ? ", with a skeleton, its vertices in "
                                                            "no sun shadow pass"
                        : c.lone == LampLoneState::Sun    ? ", with a skeleton, its vertices in "
                                                            "a sun shadow pass"
                                                          : ", with a skeleton");
        }
        std::printf("\n");
        card_lookups = 0;
"""),
    ],
    TESTS + "test_rt_lamp_cards.cpp": [
        (r"""
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r46_lamp-cards): which entries of the ray tracing scene lamp rays leave out as cut-out
// cards (rt_lamp_cards.h), over every combination of what RtShadow knows of an entry, and the
// plants' ways into lamp rays under the rule of before.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_copy_turns.h"
#include "gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h"

using namespace Vulkan;

namespace {
// What RtShadow::Entry keeps for the rule.
struct Facts {
    bool shadow_card = false; ///< the rule of before: set on a first draw of a frame only
    bool dynamic = false;
    bool card_shadow = false;
    bool card_camera = false;
    bool skinned = false;
};

bool Card(bool old, std::uint32_t level, const Facts& f) {
    return LampCard(old, level, f.shadow_card, f.dynamic, f.card_shadow, f.card_camera, f.skinned);
}

// The level as RtShadow reads it from BB_RT_LAMP_CARDS.
std::uint32_t Level(const char* text) {
    return ReadCopyTurnKnob(text, LampCardLevelDefault, LampCardLevelMost);
}
} // namespace

int main() {
    // Usable where the engine needs a constant, and the default is the repair.
    static_assert(LampCardLevelDefault == 1 && LampCardLevelMost == 2);
    static_assert(LampCard(false, 1, false, false, true, false, false));
    static_assert(!LampCard(true, 1, false, false, true, false, false));

    // Every combination of the five facts, the three levels and the experiment bit.
    std::uint32_t out_old = 0, out_one = 0, out_two = 0;
    for (std::uint32_t bits = 0; bits < 32; ++bits) {
        const Facts f{(bits & 1) != 0, (bits & 2) != 0, (bits & 4) != 0, (bits & 8) != 0,
                      (bits & 16) != 0};
        const bool before = f.shadow_card && !f.dynamic;
        const bool cutout = f.card_shadow || f.card_camera;
        // The rule of before: the experiment bit at any level, and level 0 without the bit. It
        // reads nothing of what the new rule keeps.
        for (std::uint32_t level = 0; level <= LampCardLevelMost; ++level) {
            assert(Card(true, level, f) == before);
        }
        assert(Card(false, 0, f) == before);
        // Level 1: a cut-out by either sign unless it was drawn with a skeleton. Level 2: every
        // cut-out. Neither reads the order of the passes (shadow_card) or "moving" (dynamic).
        assert(Card(false, 1, f) == (cutout && !f.skinned));
        assert(Card(false, 2, f) == cutout);
        Facts other = f;
        other.shadow_card = !f.shadow_card;
        other.dynamic = !f.dynamic;
        assert(Card(false, 1, other) == Card(false, 1, f) && Card(false, 2, other) == Card(false, 2, f));
        // A level never leaves out less than the one below it does of the new rule's cut-outs.
        assert(!Card(false, 1, f) || Card(false, 2, f));
        out_old += before ? 1 : 0;
        out_one += Card(false, 1, f) ? 1 : 0;
        out_two += Card(false, 2, f) ? 1 : 0;
    }
    assert(out_old == 8 && out_one == 12 && out_two == 24);

    // The plants' ways into lamp rays under the rule of before; each is a card now.
    {
        // Drawn by the camera pass only (a weed with a small bone palette): no sun shadow pass
        // draw ever set shadow_card.
        const Facts camera_only{.card_camera = true};
        assert(!Card(true, 1, camera_only) && Card(false, 1, camera_only));
        // The camera pass draw comes first in every frame: shadow_card was never read from the
        // sun shadow pass draw, which is the entry's second draw.
        const Facts camera_first{.card_shadow = true, .card_camera = true};
        assert(!Card(true, 1, camera_first) && Card(false, 1, camera_first));
        // It once counted as moving (its bone palette changed once): never taken back.
        const Facts moved{.shadow_card = true, .dynamic = true, .card_shadow = true};
        assert(!Card(true, 1, moved) && Card(false, 1, moved));
        // Its sun shadow pass shader samples no texture; the camera pass draws the same mesh
        // with a discarding shader.
        const Facts untextured{.card_camera = true};
        assert(!Card(true, 1, untextured) && Card(false, 1, untextured));
    }
    // What must not change: a wall, a pillar, a body (no sign of a cut-out) stay in lamp rays
    // at every level; the card the rule of before left out stays out.
    {
        const Facts wall{};
        const Facts body{.dynamic = true, .skinned = true};
        const Facts leaf{.shadow_card = true, .card_shadow = true};
        for (std::uint32_t level = 0; level <= LampCardLevelMost; ++level) {
            assert(!Card(false, level, wall) && !Card(true, level, wall));
            assert(!Card(false, level, body) && !Card(true, level, body));
            assert(Card(false, level, leaf) && Card(true, level, leaf));
        }
        // Hair and cloth (a cut-out drawn with a skeleton) keep their lamp shadow at level 1 and
        // lose it only at level 2.
        const Facts hair{.dynamic = true, .card_shadow = true, .card_camera = true, .skinned = true};
        assert(!Card(false, 0, hair) && !Card(false, 1, hair) && Card(false, 2, hair));
    }
    // BB_RT_LAMP_CARDS: a whole number, at most 2; anything else leaves the default.
    assert(Level(nullptr) == 1 && Level("") == 1 && Level("x") == 1 && Level("-1") == 1);
    assert(Level("0") == 0 && Level("1") == 1 && Level(" 2 ") == 2 && Level("7") == 2);
    std::printf("rt lamp cards: ok (of the 32 combinations of an entry's signs the rule of before leaves out "
                "%u, level 1 %u, level 2 %u)\n",
                out_old, out_one, out_two);
    return 0;
}
""",
         r"""
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r46_lamp-cards): which entries of the ray tracing scene lamp rays leave out as cut-out
// cards (rt_lamp_cards.h), over every combination of what RtShadow knows of an entry, and the
// plants' ways into lamp rays under the rule of before.
// bbport (r46b_plant-rule): level 3 (cut-outs with a skeleton that no sun shadow pass draws stay
// out too) and the count that makes a position stream "lone" (LampLone).
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_copy_turns.h"
#include "gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h"

using namespace Vulkan;

namespace {
// What RtShadow::Entry keeps for the rule.
struct Facts {
    bool shadow_card = false; ///< the rule of before: set on a first draw of a frame only
    bool dynamic = false;
    bool card_shadow = false;
    bool card_camera = false;
    bool skinned = false;
    bool lone = false; ///< its vertices are LampLoneState::Lone
};

bool Card(bool old, std::uint32_t level, const Facts& f) {
    return LampCard(old, level, f.shadow_card, f.dynamic, f.card_shadow, f.card_camera, f.skinned,
                    f.lone);
}

// The level as RtShadow reads it from BB_RT_LAMP_CARDS.
std::uint32_t Level(const char* text) {
    return ReadCopyTurnKnob(text, LampCardLevelDefault, LampCardLevelMost);
}

// A stream the camera pass draws as a skinned cut-out on `frames` frames in a row from `first`,
// while a sun shadow pass draws some skeleton on every frame. Returns how often the draw said
// that what the stream is taken for changed.
std::uint32_t CameraFrames(LampLone& known, std::uint64_t first, std::uint32_t frames) {
    std::uint32_t changes = 0;
    for (std::uint64_t frame = first; frame < first + frames; ++frame) {
        changes += LampLoneCameraDraw(known, frame, true, frame) ? 1 : 0;
    }
    return changes;
}
} // namespace

int main() {
    // Usable where the engine needs a constant, and the default is the repair.
    static_assert(LampCardLevelPlain == 1 && LampCardLevelEvery == 2 && LampCardLevelLone == 3);
    static_assert(LampCardLevelDefault == 3 && LampCardLevelMost == 3);
    static_assert(LampCard(false, 1, false, false, true, false, false, false));
    static_assert(!LampCard(true, 1, false, false, true, false, false, false));
    static_assert(LampCard(false, 3, false, true, false, true, true, true));
    static_assert(!LampCard(false, 3, false, true, false, true, true, false));

    // Every combination of the six facts, the four levels and the experiment bit.
    std::uint32_t out_old = 0, out_one = 0, out_two = 0, out_three = 0;
    for (std::uint32_t bits = 0; bits < 64; ++bits) {
        const Facts f{(bits & 1) != 0,  (bits & 2) != 0,  (bits & 4) != 0,
                      (bits & 8) != 0,  (bits & 16) != 0, (bits & 32) != 0};
        const bool before = f.shadow_card && !f.dynamic;
        const bool cutout = f.card_shadow || f.card_camera;
        // The rule of before: the experiment bit at any level, and level 0 without the bit. It
        // reads nothing of what the new rule keeps.
        for (std::uint32_t level = 0; level <= LampCardLevelMost; ++level) {
            assert(Card(true, level, f) == before);
        }
        assert(Card(false, 0, f) == before);
        // Level 1: a cut-out by either sign unless it was drawn with a skeleton. Level 2: every
        // cut-out. Level 3: as 1, and a cut-out with a skeleton when its vertices are lone.
        // None reads the order of the passes (shadow_card) or "moving" (dynamic).
        assert(Card(false, 1, f) == (cutout && !f.skinned));
        assert(Card(false, 2, f) == cutout);
        assert(Card(false, 3, f) == (cutout && (!f.skinned || f.lone)));
        Facts other = f;
        other.shadow_card = !f.shadow_card;
        other.dynamic = !f.dynamic;
        for (std::uint32_t level = 1; level <= LampCardLevelMost; ++level) {
            assert(Card(false, level, other) == Card(false, level, f));
        }
        // Only level 3 reads "lone".
        Facts flipped = f;
        flipped.lone = !f.lone;
        for (std::uint32_t level = 0; level <= 2; ++level) {
            assert(Card(false, level, flipped) == Card(false, level, f));
            assert(Card(true, level, flipped) == Card(true, level, f));
        }
        assert(Card(true, 3, flipped) == Card(true, 3, f));
        // Level 3 leaves out all that level 1 does and nothing that level 2 does not.
        assert(!Card(false, 1, f) || Card(false, 3, f));
        assert(!Card(false, 3, f) || Card(false, 2, f));
        out_old += before ? 1 : 0;
        out_one += Card(false, 1, f) ? 1 : 0;
        out_two += Card(false, 2, f) ? 1 : 0;
        out_three += Card(false, 3, f) ? 1 : 0;
    }
    assert(out_old == 16 && out_one == 24 && out_two == 48 && out_three == 36);

    // The plants' ways into lamp rays under the rule of before; each is a card now.
    {
        // Drawn by the camera pass only (a weed with a small bone palette): no sun shadow pass
        // draw ever set shadow_card.
        const Facts camera_only{.card_camera = true};
        assert(!Card(true, 1, camera_only) && Card(false, 1, camera_only));
        // The camera pass draw comes first in every frame: shadow_card was never read from the
        // sun shadow pass draw, which is the entry's second draw.
        const Facts camera_first{.card_shadow = true, .card_camera = true};
        assert(!Card(true, 1, camera_first) && Card(false, 1, camera_first));
        // It once counted as moving (its bone palette changed once): never taken back.
        const Facts moved{.shadow_card = true, .dynamic = true, .card_shadow = true};
        assert(!Card(true, 1, moved) && Card(false, 1, moved));
        // Its sun shadow pass shader samples no texture; the camera pass draws the same mesh
        // with a discarding shader.
        const Facts untextured{.card_camera = true};
        assert(!Card(true, 1, untextured) && Card(false, 1, untextured));
        // bbport (r46b_plant-rule): a bed of weed drawn with a skeleton by the camera pass only
        // (what the game showed): level 1 keeps it, level 3 leaves it out once it is lone.
        const Facts bed{.dynamic = true, .card_camera = true, .skinned = true, .lone = true};
        assert(!Card(true, 3, bed) && !Card(false, 0, bed) && !Card(false, 1, bed));
        assert(Card(false, 2, bed) && Card(false, 3, bed));
        Facts waiting = bed;
        waiting.lone = false;
        assert(!Card(false, 3, waiting));
    }
    // What must not change: a wall, a pillar, a body (no sign of a cut-out) stay in lamp rays
    // at every level; the card the rule of before left out stays out.
    {
        const Facts wall{};
        const Facts body{.dynamic = true, .skinned = true};
        const Facts body_lone{.dynamic = true, .skinned = true, .lone = true}; // no cut-out
        const Facts leaf{.shadow_card = true, .card_shadow = true};
        for (std::uint32_t level = 0; level <= LampCardLevelMost; ++level) {
            assert(!Card(false, level, wall) && !Card(true, level, wall));
            assert(!Card(false, level, body) && !Card(true, level, body));
            assert(!Card(false, level, body_lone) && !Card(true, level, body_lone));
            assert(Card(false, level, leaf) && Card(true, level, leaf));
        }
        // Hair and cloth (a cut-out drawn with a skeleton, its vertices in the sun shadow pass)
        // keep their lamp shadow at levels 1 and 3 and lose it only at level 2.
        const Facts hair{.dynamic = true, .card_shadow = true, .card_camera = true, .skinned = true};
        assert(!Card(false, 0, hair) && !Card(false, 1, hair) && Card(false, 2, hair));
        assert(!Card(false, 3, hair));
    }
    // BB_RT_LAMP_CARDS: a whole number, at most 3; anything else leaves the default.
    assert(Level(nullptr) == 3 && Level("") == 3 && Level("x") == 3 && Level("-1") == 3);
    assert(Level("0") == 0 && Level("1") == 1 && Level(" 2 ") == 2 && Level("3") == 3);
    assert(Level("7") == 3);

    // bbport (r46b_plant-rule): when a position stream is lone.
    static_assert(LampLoneFrames > 8 + LampLoneSunAge); // longer than a far cascade's turn
    {
        // A plant: the camera pass draws it frame after frame, a sun shadow pass draws
        // skeletons on each of them, never this one. Lone at the last of LampLoneFrames frames,
        // said once.
        LampLone plant;
        assert(LampLoneOf(plant) == LampLoneState::Waiting);
        assert(CameraFrames(plant, 100, LampLoneFrames - 1) == 0);
        assert(LampLoneOf(plant) == LampLoneState::Waiting);
        assert(CameraFrames(plant, 100 + LampLoneFrames - 1, 1) == 1);
        assert(LampLoneOf(plant) == LampLoneState::Lone);
        assert(CameraFrames(plant, 200, 50) == 0 && LampLoneOf(plant) == LampLoneState::Lone);
        assert(plant.seen == 249);
        // A sun shadow pass draws it after all: not lone, for good.
        assert(LampLoneSunDraw(plant, 300) && LampLoneOf(plant) == LampLoneState::Sun);
        assert(!LampLoneSunDraw(plant, 301));
        assert(CameraFrames(plant, 302, 100) == 0 && LampLoneOf(plant) == LampLoneState::Sun);
    }
    {
        // Several draws of one frame count once (copies of a mesh, the cascades).
        LampLone twice;
        for (std::uint32_t i = 0; i < 4 * LampLoneFrames; ++i) {
            assert(!LampLoneCameraDraw(twice, 7, true, 7));
        }
        assert(twice.frames == 1);
        // The first frame counts also when it is frame 0.
        LampLone zero;
        assert(!LampLoneCameraDraw(zero, 0, true, 0) && zero.frames == 1);
    }
    {
        // A character: its sun shadow pass draw comes before the camera pass's on the same
        // frame, or frames later (a far cascade drawn every 8th frame): never lone.
        LampLone near;
        assert(LampLoneSunDraw(near, 50));
        assert(CameraFrames(near, 50, 1000) == 0 && LampLoneOf(near) == LampLoneState::Sun);
        LampLone far;
        assert(CameraFrames(far, 50, 8) == 0);
        assert(LampLoneSunDraw(far, 58));
        assert(CameraFrames(far, 58, 1000) == 0 && LampLoneOf(far) == LampLoneState::Sun);
    }
    {
        // Where the sign cannot be read a character keeps its lamp shadow: no sun shadow pass
        // ever drew a skeleton, or the last one did more than LampLoneSunAge frames ago.
        LampLone indoors;
        for (std::uint64_t frame = 1; frame <= 1000; ++frame) {
            assert(!LampLoneCameraDraw(indoors, frame, false, 0));
        }
        assert(indoors.frames == 0 && LampLoneOf(indoors) == LampLoneState::Waiting);
        for (std::uint64_t frame = 1001; frame <= 2000; ++frame) {
            assert(!LampLoneCameraDraw(indoors, frame, true, 1000 - LampLoneSunAge));
        }
        assert(indoors.frames == 0);
        // A sun shadow pass draw LampLoneSunAge frames back still counts.
        assert(!LampLoneCameraDraw(indoors, 2001, true, 2001 - LampLoneSunAge));
        assert(indoors.frames == 1);
    }
    std::printf("rt lamp cards: ok (of the 64 combinations of an entry's signs the rule of before leaves out "
                "%u, level 1 %u, level 2 %u, level 3 %u; a stream is lone after %u frames)\n",
                out_old, out_one, out_two, out_three, LampLoneFrames);
    return 0;
}
"""),
    ],
}


def fix(s, nl):
    # s[1:]: each text starts on the line after its opening quotes
    return s[1:].replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: level 3 is the default and the highest;
    LampCard has one definition, with `lone` last, and the rule of before as its first return;
    the scene reads the rule through LampCard in three places, each with `lone`; the instance
    mask line and the old rule's field are as they were; the map is kept before the draw
    filters; the log line names rule 3; the C escapes are intact."""
    ok = True

    def need(what, *counts):
        nonlocal ok
        for text, part, want in counts:
            if text.count(part) != want:
                print("%s (%a found %d times, want %d)" % (what, part[:70], text.count(part), want))
                ok = False

    rule = texts[R + "rt_lamp_cards.h"]
    cpp = texts[R + "vk_rt_shadow.cpp"]
    head = texts[R + "vk_rt_shadow.h"]
    test = texts[TESTS + "test_rt_lamp_cards.cpp"]
    need("level 3 should be the default and the highest level, 1 and 2 as they were",
         (rule, "inline constexpr std::uint32_t LampCardLevelPlain = 1;", 1),
         (rule, "inline constexpr std::uint32_t LampCardLevelEvery = 2;", 1),
         (rule, "inline constexpr std::uint32_t LampCardLevelLone = 3;", 1),
         (rule, "inline constexpr std::uint32_t LampCardLevelDefault = LampCardLevelLone;", 1),
         (rule, "inline constexpr std::uint32_t LampCardLevelMost = 3;", 1))
    need("LampCard should have one definition with `lone` last and the rule of before first",
         (rule, "constexpr bool LampCard(", 1), (rule, "bool skinned, bool lone) noexcept {", 1),
         (rule, "    if (old || level == 0) {", 1), (rule, "        return shadow_card && !dynamic;", 1),
         (rule, "    return cutout && (!skinned || lone);", 1),
         (rule, "inline constexpr std::uint32_t LampLoneFrames = 32;", 1))
    need("the scene should read the rule through LampCard in three places, each with `lone`",
         (cpp, "LampCard(", 3), (cpp, "entry->skinned, lone)", 3),
         (cpp, "        const bool lone = entry->lone == LampLoneState::Lone;", 1),
         (cpp, "\n    const bool cards_old = BbToggle::Experiment(LampCardsOldBit);", 1),
         (cpp, "\n    const u32 card_level = LampCardLevel();", 1))
    need("the instance mask line and the old rule's field should be as they were",
         (cpp, "            .mask = u8(mask | (card || stale || leave ? 0 : LampMask)),", 1),
         (cpp, "        entry.shadow_card = draw.textured;", 1))
    need("the map of position streams should be kept once, and the entries know their stream",
         (cpp, "lone_streams.try_emplace(draw.positions)", 1), (cpp, "    entry.stream = draw.positions;", 1),
         (head, "    std::unordered_map<u64, LampLone> lone_streams;", 1),
         (head, "        LampLoneState lone = LampLoneState::None;", 2),
         (head, "        std::array<u32, 4> rule_out{};", 1))
    # before the filters: the map is kept above the first return that depends on the scene
    at = cpp.find("lone_streams.try_emplace(draw.positions)")
    if at < 0 or cpp.find("    if (draw.camera_pass && !need_scene) {", at) < 0 or \
            cpp.rfind("    if (draw.camera_pass && !need_scene) {", 0, at) >= 0:
        print("the map of position streams is not kept before the draw filters")
        ok = False
    need("the 600-frame line should name rule 3 and keep its C escapes",
         (cpp, '"3 (cut-outs without a skeleton, and those with one that no sun shadow pass draws)"};', 1),
         (cpp, '"%u, rule 3 %u; %zu cut-out meshes known, %zu by their key, %.2f entries a "', 1),
         (cpp, '"last drew a skeleton %lld frames ago (-1: never)%s",', 1))
    need("the offline test should hold level 3 and the count",
         (test, "static_assert(LampCardLevelDefault == 3 && LampCardLevelMost == 3);", 1),
         (test, "assert(out_old == 16 && out_one == 24 && out_two == 48 && out_three == 36);", 1),
         (test, "LampLoneCameraDraw(", 6), (test, '"%u, level 1 %u, level 2 %u, level 3 %u; a stream is lone after %u frames)\\n",', 1))
    for path, text in texts.items():
        if "TEMP" in text or "r46b_list" in text or "BB_RT_CARD_" in text:
            print("%s holds a temporary diagnostic" % path)
            ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r46b_plant-rule.py check|apply|revert   (the tree: R46B_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    before = {}
    for path in out:
        before[path] = open(path, "rb").read()
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
