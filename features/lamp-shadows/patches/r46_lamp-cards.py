# r46_lamp-cards: plants (ivy, weeds: flat cards whose texture cuts the shape out) no longer cast
# ray traced lamp shadows shaped like their whole polygons (vk_rt_shadow.cpp/.h, a new header
# rt_lamp_cards.h with its test, one comment in bbport_settings.h, one test target in
# gpu/CMakeLists.txt). check|apply|revert (revert restores byte for byte and removes the two new
# files). On top of r1..r43 with r44_half-area-lamp applied (it anchors on r44's comment in
# bbport_settings.h); r47_still-check goes on top of this one. Back: r47 first, then r46 (while
# r47 is in the tree every command of this script says so and changes nothing). The tree: the
# one the environment variable R46_ROOT names; without it the current directory when that is
# the root of a source tree (run from there), else <tree>/. Nothing is changed in
# place: every new text is written beside its target and moved over it, and a failure puts back
# what was already moved. Source files keep their CRLF line ends. Every old text below is found
# exactly once when its turn comes, every new one exactly once on the way back.
#
# WHY. With ray traced lamp shadows on, the hand torch threw rectangles of shadow behind weeds
# and ivy. A lamp ray (point_shadow_ray.comp: opaque, the first hit ends it, instance mask 0x04)
# cannot test a texture: the scene's bottom-level structures hold positions only. A cut-out card
# is therefore hit as its whole polygon. One rule kept cards out of lamp rays, and it missed the
# plants: an entry was a card only by the texture of its sun shadow pass draw, read only when
# that draw was the entry's first of a frame (Entry::shadow_card), and only while the entry did
# not count as moving (PrepareScene: shadow_card && !dynamic). A card kept its lamp bit when the
# camera pass alone drew it, when its camera pass draw came first in the frame, when it once
# counted as moving (never taken back), or when its sun pass shader samples no texture. Which of
# these the plants took is not known; the new rule closes all of them and the new log line names
# the route.
#
# WHAT.
#  1. An entry keeps for good what any draw of it ever showed (PrepareDraw, before the return of
#     a second draw of the frame): card_shadow, a sun shadow pass draw of it samples a texture;
#     card_camera, a camera pass draw of it has a discarding pixel shader; skinned, a draw of it
#     had a skeleton. And card_mesh: the camera pass draws its mesh with a discarding shader in
#     another draw (a sun cascade's copy, a prop drawn there under another bone palette, a card
#     whose camera pass draw is not in the scene). That is looked up in two sets: cutout_meshes
#     (there before: the mesh without its shader) and the new cutout_keys (the key entries are
#     known by, Entry::base). The second one because `mesh` hashes every vertex stream a draw
#     binds (vk_rasterizer.cpp: buffers_hash, one buffer for each attribute of the fetch shader)
#     and a sun shadow pass shader may bind fewer than the camera pass's, while the key of a
#     draw with a position stream is the same in every pass. Both sets are filled where the
#     camera pass's cut-out is seen, BEFORE PrepareDraw's filters: a cut-out without skeleton or
#     palette is dropped there (it is not in the scene) and never reaches the place where its
#     key is otherwise made, yet it is exactly the card whose sun shadow pass entry must find
#     itself. The lookup is done by PrepareScene when it writes the entry's instance record, not
#     at the entry's draw: a sun cascade draws its copy before the camera pass makes the mesh
#     known, and the copy would keep its lamp bit for the frame. One lookup an entry each time a
#     cut-out new to the sets was drawn (cutout_gen), none for an entry that has a sign already.
#  2. The rule is one pure function, LampCard (rt_lamp_cards.h, no Vulkan; the test runs it):
#     level 1 (default): a cut-out (card_shadow, card_camera or card_mesh) without a skeleton
#     stays out of lamp rays; level 2: every cut-out; the experiment bit or level 0: the rule of
#     before, shadow_card && !dynamic, from the same Entry::shadow_card as before (that line of
#     PrepareDraw is untouched). Neither level 1 nor 2 reads the order of the passes or `dynamic`
#     (r47 will count more entries as moving; under the rule of before each such card would come
#     back into lamp rays).
#  3. PrepareScene reads the bit and the level at every scene build; when the rule is not the
#     one the instance records were last written with, they are written again (tlas_count = 0,
#     as PrepareDraw does for a changed mask; the changed masks make that top-level build a full
#     one). The records are written every frame anyway (OnFrameEnd zeroes tlas_count), so a
#     change of the bit shows on the next frame at the latest.
#  4. Only the lamp bit (4) of an instance's mask changes. The sun's rays (mask 1) and bounced
#     light (mask 0xff) hit cards as before; the admission rule of PrepareDraw (a discarding
#     camera pass draw without skeleton or palette is not in the scene) is as before; no shader,
#     no pipeline, no buffer changes.
#  5. Experiment 9223372036854775808 (bit 63, LampCardsOldBit in vk_rt_shadow.h) set = the rule
#     of before: the same masks as before the patch (A/B in one run through BB_TOGGLE_FILE). The
#     signs of 1 are kept up either way (bytes on the CPU), so that clearing the bit shows the
#     new rule at once. It is not one of BbSettings::PreviousPathsBits: set brings the picture
#     fault back. Not bit 63 of the other mask (BbToggle::Fsr4EncodedInput).
#
# THE TRADE. Plants and every other cut-out without a skeleton (a fence lattice, a grate, a
# banner, alpha-tested parts of a weapon) cast no lamp shadow at all, as in the game, which has
# no lamp shadows. Before, those that were left in cast the shadow of their whole polygons. A
# solid prop whose camera pass shader discards for another reason (a fade) would lose its lamp
# shadow too, and for good: the signs are never taken back (a sign that came and went with the
# shader of the last draw would give the plants their rectangles back whenever a pre-pass and a
# G-buffer draw of one mesh differ in it, or after the sets were emptied). The log line says
# how many instances are left out, how many of them have a bone palette (plants have none), and
# names the four largest by mesh, key and triangles: a caster that is no plant shows there. If
# the hand torch or a weapon is among them, r46 alone takes away the caster of the fault r47 is
# for: judge r47 with this patch's bit set. Leaf-shaped lamp shadows need an alpha test in the
# ray (not in this patch).
#
# KNOB (environment variable, read once at start; not a whole number: the default; above 2: 2).
#   BB_RT_LAMP_CARDS  [1]  0|1|2  0: the rule of before. 1: cut-outs without a skeleton stay out
#                                 of lamp rays. 2: every cut-out stays out, skinned ones too
#                                 (hair and cloth then cast no lamp shadow): for a plant that
#                                 turns out to be drawn with a skeleton.
#
# LOG LINE, once every 600 frames with a scene, after the "Ray tracing: ... shared copies" line:
#   "Ray tracing cut-out cards (r46): rule 1 (cut-outs without a skeleton) (experiment
#    9223372036854775808 clear, BB_RT_LAMP_CARDS=1); on the last scene A instances left out of
#    lamp rays as cut-out cards (B known from the sun pass's texture, C from their own camera
#    pass draw's discard, D only from a camera pass draw of their mesh that is not their own; P
#    with a bone palette, E drawn by the camera pass only, F counted as moving), G skinned
#    cut-outs kept in lamp rays; the old rule would leave out H, rule 1 I, rule 2 J; K cut-out
#    meshes known, L by their key, M entries a frame looked themselves up among them; the
#    largest left out: mesh <16 hex> (key <16 hex>), N triangles, known from [the sun pass's
#    texture] [its camera pass draw] [a camera pass draw of its mesh], with a bone palette, an
#    instance's own entry, counted as moving, drawn by the camera pass only; ..."
#   (the part after "the largest left out:" only when A is above 0: up to four casters, each
#   mesh once, the most triangles first; only the words that hold for a caster are printed).
# What to read: A above 0 near plants and H smaller than I (I - H is the leak); E and F name the
# route (camera pass only, counted as moving); D counts the instances that have no camera pass
# sign of their own and were found through the two sets alone (the tie through the mesh works:
# the sun cascades' copies of a plant); P above 0 and a large triangle count in the list point
# at casters that are no plants; G is about the character's hair and cloth; M should fall to
# about 0 once a place is loaded (a value that stays near the number of instances means a
# camera pass cut-out is new to the sets on every frame). With the bit set the line says "rule
# old ..." and A equals H, while I and J still say what the new rule would leave out. With r47
# applied and at work, more entries count as moving, so H (what the rule of before would leave
# out NOW) is smaller than before the patches: read H and F, and judge the old picture, with
# r47's bit set as well (experiment mask 13835058055282163712 = both).
#
# TEST. tests/test_rt_lamp_cards.cpp (target rt-lamp-cards-test in gpu/CMakeLists.txt, registered
# as rt-copy-turns-test is): LampCard over all 32 combinations of an entry's five signs, the
# three levels and the bit; the plants' four ways into lamp rays under the rule of before; walls,
# bodies, hair; the knob's values.

import os
import re
import sys

# The tree: R46_ROOT when it is set; else the current directory when that is the root of a
# source tree (the script is run from there); else <tree>/, as the rounds before.
ROOT = os.environ.get("R46_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_rt_shadow.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
S = G + "shim/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"

BIT = 63
VALUE = 1 << BIT  # 9223372036854775808
TMP = ".r46tmp"  # a new text waits under this name beside its target (main)

# The two files this round adds (apply writes them with CRLF line ends, revert removes them if
# they are still as written here).
NEW_FILES = {
    R + "rt_lamp_cards.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
    TESTS + "test_rt_lamp_cards.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. In the two files other rounds change as
# well (bbport_settings.h, gpu/CMakeLists.txt) the old text is one whole line.
EDITS = {
    S + "bbport_settings.h": [
        (r"""// same reason: set brings the hard-edged torch shadows back.
""",
         r"""// same reason: set brings the hard-edged torch shadows back.
// bbport (r46_lamp-cards): nor is 63 (9223372036854775808; set = lamp rays leave out as cut-out
// cards only what the rule of before did, vk_rt_shadow.h LampCardsOldBit), for the same reason:
// set brings the plants' whole-polygon lamp shadows back.
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""target_include_directories(rt-copy-turns-test PRIVATE ..)
""",
         r"""target_include_directories(rt-copy-turns-test PRIVATE ..)
# bbport (r46_lamp-cards): which cut-out cards lamp rays leave out (rt_lamp_cards.h)
add_executable(rt-lamp-cards-test EXCLUDE_FROM_ALL ../tests/test_rt_lamp_cards.cpp)
target_compile_options(rt-lamp-cards-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-lamp-cards-test PRIVATE ..)
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""inline constexpr u64 LampRepairOffBit = 35184372088832ull;
""",
         r"""inline constexpr u64 LampRepairOffBit = 35184372088832ull;

// bbport (r46_lamp-cards): experiment bit 63: set = lamp rays leave out as cut-out cards only
// what the rule of before did (the entries whose sun shadow pass draw has a texture, while they
// do not count as moving; rt_lamp_cards.h), so plants cast whole-polygon lamp shadows again.
// Read at every scene build (RtShadow::PrepareScene). Set brings the picture fault back, so it
// is not one of BbSettings::PreviousPathsBits. Not bit 63 of the other mask
// (BbToggle::Fsr4EncodedInput).
inline constexpr u64 LampCardsOldBit = 9223372036854775808ull;
"""),
        (r"""        bool shadow_card = false;
""",
         r"""        bool shadow_card = false;
        // bbport (r46_lamp-cards): what any draw of it ever showed, kept for good (PrepareDraw;
        // LampCard in rt_lamp_cards.h reads them): a sun shadow pass draw of it samples a
        // texture; a camera pass draw of it has a discarding pixel shader; the camera pass
        // draws its mesh so in another draw (cutout_meshes, cutout_keys; looked up by
        // PrepareScene, again only while card_gen is not cutout_gen); a draw of it had a
        // skeleton.
        bool card_shadow = false;
        bool card_camera = false;
        bool card_mesh = false;
        bool skinned = false;
        u32 card_gen = 0;
"""),
        (r"""    std::unordered_set<u64> cutout_meshes;
""",
         r"""    std::unordered_set<u64> cutout_meshes;
    // bbport (r46_lamp-cards): the same draws by the key entries are known by (Entry::base).
    // `mesh` hashes every vertex stream a draw binds, and a sun shadow pass shader may bind
    // fewer than the camera pass's; the key of a draw with a position stream does not depend on
    // the pass. cutout_gen changes whenever either set does: an entry looks itself up again only
    // then (Entry::card_gen; card_lookups counts the lookups since the last 600-frame line: a
    // camera pass cut-out whose mesh is new on every frame would make every entry look on every
    // frame). card_rule: the rule the scene's instance records were last written with (0 the
    // rule of before, else BB_RT_LAMP_CARDS). card_stats: those records' instances, for the
    // 600-frame line: left out of lamp rays as cut-out cards (of them: known from the sun
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
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
""",
         r"""#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
#include "video_core/renderer_vulkan/rt_lamp_cards.h"    // bbport (r46_lamp-cards)
"""),
        (r"""// card (a leaf on a vine) shadows as its whole polygon: rectangles of shadow on the ground. The
// cards the shadow pass draws (Entry::shadow_card) stay out and cast no lamp shadow, as in the
// game; skinned meshes keep theirs (cloth).
constexpr u8 LampMask = 4;
""",
         r"""// card (a leaf on a vine) shadows as its whole polygon: rectangles of shadow on the ground. The
// cards stay out and cast no lamp shadow, as in the game; skinned meshes keep theirs (cloth).
// bbport (r46_lamp-cards): a card is known by any draw of it that ever showed a cut-out: a sun
// shadow pass draw with a texture, or a camera pass draw with a discarding pixel shader, its
// own or another draw of the same mesh (Entry::card_shadow, card_camera, card_mesh; LampCard in
// rt_lamp_cards.h). Before, only by the texture of a sun shadow pass draw that was the entry's
// first of a frame, and only while the entry did not count as moving (Entry::shadow_card): the
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
    return level;
}
"""),
        (r"""    const u64 mesh = r19 ? 0 : mesh_of();
    if (draw.camera_pass && draw.alpha) {
        if (cutout_meshes.size() >= 65536) {
            cutout_meshes.clear();
        }
        cutout_meshes.insert(r19 ? mesh_of() : mesh);
""",
         r"""    const u64 mesh = r19 ? 0 : mesh_of();
    // bbport (r46_lamp-cards): the key of a draw with a position stream (the entries are known
    // by it, below): it depends neither on the pass nor on the shader.
    const auto position_key = [&] {
        const std::array<u64, 4> parts{draw.positions, draw.indices,
                                       (u64(draw.index_count) << 32) | draw.first_vertex,
                                       draw.instances};
        return XXH3_64bits(parts.data(), sizeof(parts));
    };
    if (draw.camera_pass && draw.alpha) {
        // bbport (r46_lamp-cards): cutout_gen tells the entries that a set changed (PrepareScene)
        if (cutout_meshes.size() >= 65536) {
            cutout_meshes.clear();
            ++cutout_gen;
        }
        if (cutout_meshes.insert(r19 ? mesh_of() : mesh).second) {
            ++cutout_gen;
        }
        // The same draw by the key as well, which the sun shadow pass's entries of the mesh
        // have too where `mesh` differs between the passes (see cutout_keys). Here, before the
        // filters below: a cut-out without skeleton or palette is dropped there and gets no
        // entry from the camera pass, so its sun shadow pass entry knows itself as a card
        // through these sets alone.
        if (draw.positions && draw.indices) {
            if (cutout_keys.size() >= 65536) {
                cutout_keys.clear();
                ++cutout_gen;
            }
            if (cutout_keys.insert(position_key()).second) {
                ++cutout_gen;
            }
        }
"""),
        (r"""    if (draw.positions) {
        const std::array<u64, 4> mesh{draw.positions, draw.indices,
                                      (u64(draw.index_count) << 32) | draw.first_vertex,
                                      draw.instances};
        key = XXH3_64bits(mesh.data(), sizeof(mesh));
""",
         r"""    if (draw.positions) {
        key = position_key(); // bbport (r46_lamp-cards): as the camera pass's cut-outs above
"""),
        (r"""        entry.r17_near_frame = frame;
    }
""",
         r"""        entry.r17_near_frame = frame;
    }
    // bbport (r46_lamp-cards): what this draw shows of a cut-out card, at every draw of the
    // entry (a second draw of the frame returns just below) and for good: whichever pass comes
    // first, and whether or not the entry counts as moving, lamp rays leave a card out
    // (PrepareScene). Entry::shadow_card below is the rule of before, kept as it was.
    entry.skinned = entry.skinned || draw.skinned;
    entry.card_shadow = entry.card_shadow || (draw.shadow_pass && draw.textured);
    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
"""),
        (r"""        r17_blas_dirty = true;
    }
""",
         r"""        r17_blas_dirty = true;
    }
    // bbport (r46_lamp-cards): the rule for cut-out cards, read at every scene build: with
    // experiment LampCardsOldBit set, or BB_RT_LAMP_CARDS=0, the rule of before. When it is not
    // the one the instance records were written with (the bit changed while the game runs), they
    // are written again, as for a changed mask in PrepareDraw: old and new can be compared in
    // one run.
    const bool cards_old = BbToggle::Experiment(LampCardsOldBit);
    const u32 card_level = LampCardLevel();
    if (const u32 rule = cards_old ? 0u : card_level; rule != card_rule) {
        card_rule = rule;
        tlas_count = 0;
    }
"""),
        (r"""    // bbport (r41_lamp-shadows, r42_lamp-soft): with BB_LAMP_SHADOW_STALE=1 only
    const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
""",
         r"""    // bbport (r41_lamp-shadows, r42_lamp-soft): with BB_LAMP_SHADOW_STALE=1 only
    const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
    card_stats = {}; // bbport (r46_lamp-cards): of the records written now
"""),
        (r"""        const bool kept = i >= frame_entries.size();
        const Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];
""",
         r"""        const bool kept = i >= frame_entries.size();
        Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];
"""),
        (r"""        }
        const bool card = entry->shadow_card && !entry->dynamic;
""",
         r"""        }
        // bbport (r46_lamp-cards): an entry no camera pass draw of its own showed as a cut-out
        // (a sun cascade's copy, a prop drawn there under another bone palette, a card whose
        // camera pass draw is not in the scene) is one when the camera pass draws its mesh with
        // a discarding shader. Looked up here and not at its draw: a sun cascade draws its copy
        // before the camera pass makes the mesh known, and the copy would cast its whole-polygon
        // shadow for a frame. One lookup an entry each time a cut-out new to the sets was drawn.
        if (!entry->card_camera && !entry->card_mesh && entry->card_gen != cutout_gen) {
            entry->card_gen = cutout_gen;
            entry->card_mesh =
                cutout_meshes.contains(entry->mesh) || cutout_keys.contains(entry->base);
            ++card_lookups;
        }
        // bbport (r46_lamp-cards): a cut-out card by any draw of it, whatever the order of the
        // passes and whether or not it counts as moving (rt_lamp_cards.h). cards_old: the rule
        // of before, shadow_card && !dynamic.
        const bool cutout = entry->card_camera || entry->card_mesh;
        const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,
                                   entry->card_shadow, cutout, entry->skinned);
"""),
        (r"""                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
""",
         r"""                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
        // For the 600-frame line: what is left out and by which sign, and what each rule would
        // leave out of these same instances (the route by which a card kept its lamp bit).
        if (card) {
            ++card_stats.out;
            card_stats.by_shadow += entry->card_shadow ? 1 : 0;
            card_stats.by_camera += entry->card_camera ? 1 : 0;
            card_stats.by_mesh += entry->card_mesh && !entry->card_camera ? 1 : 0;
            card_stats.with_palette += entry->palette != 0 ? 1 : 0;
            card_stats.camera_only += (mask & ShadowMask) == 0 ? 1 : 0;
            card_stats.moving += entry->dynamic ? 1 : 0;
            // The four with the most triangles, each mesh once: a caster that is no plant (a
            // weapon, a fence, a prop whose shader discards for a fade) is named in the line.
            if (std::ranges::none_of(card_stats.largest, [&](const CardFound& c) {
                    return c.triangles != 0 && c.key == entry->base;
                })) {
                CardFound found{entry->mesh,
                                entry->base,
                                entry->triangles,
                                entry->card_shadow,
                                entry->card_camera,
                                entry->card_mesh,
                                entry->palette != 0,
                                entry->instance,
                                entry->dynamic,
                                (mask & ShadowMask) == 0};
                for (CardFound& slot : card_stats.largest) {
                    if (found.triangles > slot.triangles) {
                        std::swap(slot, found);
                    }
                }
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
"""),
        (r"""        std::printf("\n");
""",
         r"""        std::printf("\n");
        // bbport (r46_lamp-cards): the cut-out cards among the instances of the scene last
        // built, and what each rule would leave out of them
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
                        c.by_camera ? " [its camera pass draw]" : "",
                        c.by_mesh ? " [a camera pass draw of its mesh]" : "",
                        c.palette ? ", with a bone palette" : "",
                        c.instance ? ", an instance's own entry" : "",
                        c.moving ? ", counted as moving" : "",
                        c.camera_only ? ", drawn by the camera pass only" : "");
        }
        std::printf("\n");
        card_lookups = 0;
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the experiment bit is the one the task gave,
    declared once and read where the scene's records are written and where the line is printed,
    and is not one of the master switch's; the rule of before is kept word for word behind it;
    the engine and the header agree on the rule's call; an entry's signs are kept up before the
    return of a second draw of the frame; the rule is compared before the scene's early return;
    the 600-frame line is one line; the C texts kept their line breaks; the header and its test
    are registered; the camera pass's cut-outs are put into both sets before PrepareDraw's
    filters, and an entry looks itself up where its instance record is written."""
    ok = True
    scene = texts[R + "vk_rt_shadow.cpp"]
    head = texts[R + "vk_rt_shadow.h"]
    cmake = texts[G + "CMakeLists.txt"]
    settings = texts[S + "bbport_settings.h"]
    cards = NEW_FILES[R + "rt_lamp_cards.h"]
    test = NEW_FILES[TESTS + "test_rt_lamp_cards.cpp"]
    nl = "\r\n" if "\r\n" in scene else "\n"
    if VALUE != 9223372036854775808 or head.count("inline constexpr u64 LampCardsOldBit = %dull;" % VALUE) != 1 or \
            scene.count("BbToggle::Experiment(LampCardsOldBit)") != 2 or \
            scene.count("experiment %d " % VALUE) != 1:
        print("experiment %d is not declared once in vk_rt_shadow.h and read in two places" % VALUE)
        ok = False
    bits = re.search(r"PreviousPathsBits\[\] = \{([^}]*)\}", settings)
    if not bits or BIT in [int(x) for x in re.findall(r"\d+", bits.group(1))]:
        print("bit %d is in PreviousPathsBits (or the list was not found)" % BIT)
        ok = False
    # The rule of before, word for word: the line that sets Entry::shadow_card is untouched and
    # the header's first branch reads it and `dynamic` alone.
    if scene.count(fix("    if (mask == ShadowMask) {\n        entry.shadow_card = draw.textured;\n", nl)) != 1 or \
            scene.count("shadow_card = ") != 1 or \
            cards.count("    if (old || level == 0) {\n        return shadow_card && !dynamic;\n    }\n") != 1:
        print("the rule of before is not kept as it was behind the experiment bit")
        ok = False
    if scene.count("const bool card = LampCard(cards_old, card_level, entry->shadow_card, entry->dynamic,") != 1 or \
            scene.count("LampCard(") != 2 or \
            "constexpr bool LampCard(bool old, std::uint32_t level, bool shadow_card," not in cards or \
            scene.count('ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_CARDS"),') != 1 or \
            scene.count(".mask = u8(mask | (card || stale ? 0 : LampMask)),") != 1:
        print("vk_rt_shadow.cpp and rt_lamp_cards.h do not agree on the rule's call, or the mask line changed")
        ok = False
    # The camera pass's cut-outs go into both sets before the first of PrepareDraw's filters
    # (the draws it leaves out of the scene), and the key is made in one place for both.
    if not scene.index("            if (cutout_keys.insert(position_key()).second) {") < \
            scene.index("    if (draw.camera_pass && !need_scene) {") or \
            scene.count("position_key()") != 2 or scene.count("cutout_keys.insert(") != 1 or \
            scene.count("++cutout_gen;") != 4:
        print("the camera pass's cut-outs are not recorded by their key before PrepareDraw's filters")
        ok = False
    # The signs before the return of a second draw and before the old rule's line; the lookup
    # where the instance records are written, before the rule reads it, for entries without a
    # sign of their own.
    second = scene.index(fix("    if (entry.seen_frame == frame) {\n        if ((entry.mask & mask) == 0) {\n", nl))
    lookup = "        if (!entry->card_camera && !entry->card_mesh && entry->card_gen != cutout_gen) {"
    if not scene.index("    entry.card_camera = entry.card_camera ||") < second < \
            scene.index("        entry.shadow_card = draw.textured;") < scene.index("    card_stats = {};") < \
            scene.index(lookup) < scene.index("const bool card = LampCard(") or scene.count(lookup) != 1 or \
            scene.count("card_gen") != 2 or scene.count("card_mesh =") != 1:
        print("an entry's signs of a cut-out are not kept up where the patch put them")
        ok = False
    if not scene.index("rule != card_rule") < scene.index("    if (count == tlas_count && (!hold_frames") or \
            scene.count("card_stats = {};") != 1 or \
            scene.index("    card_stats = {};") > scene.index("const bool card = LampCard("):
        print("the rule is not compared before the scene's early return, or the counts are not reset with the records")
        ok = False
    line = scene.index('std::printf("Ray tracing cut-out cards (r46): rule %s')
    if scene.count('std::printf("Ray tracing cut-out cards (r46): rule %s') != 1 or \
            not line < scene.index('"; the largest left out:" : "");') < \
            scene.index('        std::printf("' + chr(92) + 'n");' + nl + "        card_lookups = 0;") or \
            scene.count("card_lookups = 0;") != 1 or \
            'level 2 %u)' + chr(92) + 'n",' not in test:
        print("the 600-frame line is not there once, or a C escape lost its backslash on the way into the script")
        ok = False
    if cmake.count("add_executable(rt-lamp-cards-test EXCLUDE_FROM_ALL ../tests/test_rt_lamp_cards.cpp)") != 1 or \
            scene.count('#include "video_core/renderer_vulkan/rt_lamp_cards.h"') != 1 or \
            '#include "gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h"' not in test:
        print("the new header or its test is not registered")
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
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def above():
    """Whether r47_still-check, which goes on top of this round, is in the tree. This round's
    own texts are all still there under it, so nothing else would stop a revert in the wrong
    order, which would leave r47's lines in a tree without what they stand on."""
    try:
        head = open(R + "vk_rt_shadow.h", encoding="utf-8", newline="").read()
    except OSError:
        return False
    return "inline constexpr u64 StillCheckOldBit = " in head


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r46_lamp-cards.py check|apply|revert   (the tree: R46_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    if above():
        print("r47_still-check is applied on top of this round in %s: %s" % (
            ROOT, "revert that one first" if mode == "revert" else "this round is under it, applied"))
        return 1
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
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
