# r62n_cutout-skinned-blocker: FEATURE part (the skinned rule, the lamp housing zone) + TOOL part (the blocker identification:
# 'the hunter / a character / a plant / unknown', the hunter's position, the front-read line), on top of r62m (build 50). Only in the
# CARDS builds of the lamp pass and the lamp card set (BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1); with those knobs off nothing of it
# runs: PrepareScene's lamp bit is computed only when card_lamps is true (the skinned rule is asked behind it), the new spec constant
# exists only in the CARDS builds, CardSkinnedLog returns at once without card_layers_on / CardLampsWanted, and the book lines are
# printed from the window line, which is called only while the card passes' set layout exists. The FEATURE part is OFF by default with
# the cut-out shadows themselves (BB_RT_CARD_LAMPS unset).
#
# Why (build 50, r62m): the dream-house shelf darkening (whole shelf and lantern surroundings dimmer, upper-left crop luma 45.2 off vs
# 32.6 on) comes 98-99 % from ONE blocker: slot 27, key 1aa783cbe2c4509a, ps 1c3953c6 (the generic foliage alpha test, also the weeds'),
# skinned, 6188 tris, 2263 verts, 0.83 m from the lamp, 1.42 m from the surface, no world box. Weeds: blocker #1 a skinned card (4788
# tris), the game keeps 73 % of its texels. Sewer: the lamp's own static housing (0.63 x 0.97 x 0.52 m, 0.30 m from the lamp, the game
# keeps 99 %) gives 311 px, invisible. The front-read counter read 0 in every b47/b50 line (see 5 below).
#
# What this patch does:
#  1. IDENTIFY (TOOL): the blocker book's top two cards per window get one more line, 'Foliage lamp shadows (r62n) blocker <w> #n is
#     <the hunter|a character|a plant|unknown>: <px>, <bones> bones, <lone state>, hits' centre in view, hunter read/unread with his place
#     in view, sideways and up distance of the hits' centre from him, skinned mode'. The skeleton's bone count is new: EffectsCaptureDraw
#     keeps the size of the Skeleton-role palette (Motion::ClassifyBuffer: 640+ bytes, stride 16) / 48 in Draw::skeleton_bones and the entry
#     the most of its draws (Entry::skeleton_bones). The hunter is BbEngine::world_player_position (r111's read, r112h's test): 'the hunter'
#     = a figure-sized rig (not lone, or more than BB_RT_CARD_LAMP_BONES bones) whose hits' centre lies within 1.5 m sideways of him and
#     from 1.5 m under to 2.5 m over his position; 'a character' such a rig elsewhere; 'a plant' a lone skinned card with few bones;
#     'unknown' a card with no skeleton. The centre is the middle of the hits' box (the book's box is since the start of the run).
#  2. RULE (FEATURE): BB_RT_CARD_LAMP_SKINNED (live with r84's knobs file when it is present, else read at start; exactly 0, 1 or 2; default 0):
#       0  a lone skinned cut-out (r46b's sign: no sun shadow pass draws its vertices; the plants) casts a lamp shadow only when its skeleton
#          has at most BB_RT_CARD_LAMP_BONES bones (1 to 341, default 24, read at start: r112h's 'figure' limit; the hunter's gear has 28,
#          enemies 69-130, the hunter 277): a plant or a hanging thing; a rig of a figure does not (characters, hair, cloth);
#       1  every lone skinned cut-out, as r62m (build 50);
#       2  none.
#     NOT a motion measure: a skinned entry has none (the still looks hold only non-dynamic entries; a skeleton's palette changes every frame
#     in a ring), so 'moves' is taken as 'is a figure-sized rig'. The line 'Foliage lamp shadows (r62n) skinned' counts the lone skinned cards
#     the rule judged in the last scene by bones (up to 24, 25-48, 49-96, more or none read) and how many it let cast, so the number the
#     default lets through can be read off a run. Characters (a skinned card that is not lone) get no lamp shadow in any mode: r62e's
#     CardStillOf refuses to store their card UVs (the 15:25 test found bad BLAS inputs, the player's coat and hair); showing the hunter's
#     own lamp shadow would need that refusal lifted: NOT done here.
#  3. HOUSING (FEATURE): BB_RT_CARD_LAMP_HOUSING (metres, 0 to 2, default 0.4, read at start; 0 = r62m): a cut-out card met within that
#     distance of the lamp end of a lamp ray is passed untested (specialization constant 14 CARD_HOUSING; rt_cards.glsl card_skip_from;
#     the solid housing, which the lamp clearance handles, is not touched). The sewer's lamp housing (0.30 m) falls inside. Counter 65
#     CARD_LAMP_HOUSING_SKIPS (a free slot of the 72).
#  4. FRONT READS (TOOL): the counters worked where the proof view was on (b42 59, b44 5533 reads); the zeros of b47/b50 are the windows
#     without it, and the one window that had it (n1 d) lost its line (the runner keeps the first and last line of each kind, 30 Foliage
#     kinds, and the slot log is the last job's only). A window that has proof pixels or housing skips now prints ONE short line
#     'Foliage lamp shadows (r62n) <w>: front reads N (game kept %, game alpha 0 %, lamp rule kept %) of P proof px; housing skips S (zone m);
#     skinned mode', numbers first. The jobs run the proof view in a job of its own whose window line is printed at its end.
#
# Files: vk_rt_shadow.h, vk_rt_shadow.cpp, vk_rasterizer_effects.cpp (one line), vk_point_shadow.cpp, point_shadow_ray.comp, rt_cards.glsl,
# rt_card_layers_layout.h, README.md; new: renderer_vulkan/rt_card_skinned.h (pure rule and names, no Vulkan). No CMake change. Revert
# r62n before r62m.
# Cost: off 0. On: the rule is one compare per lone skinned entry per scene; the housing skip is one float compare per card candidate a lamp
# ray meets (a few ALU ops, fewer card reads); the identification and the line run from the window line (one to a few per test). Memory:
# one u32 in Draw and Entry; no new buffer.
# Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62n_cutout-skinned-blocker.py check | apply | revert
# Root: R62N_CUTOUT_SKINNED_BLOCKER_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62n_backup.
import os, re, sys

ROOT = os.environ.get("R62N_CUTOUT_SKINNED_BLOCKER_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62n_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
G = HS + "rt_cards.glsl"
S = HS + "point_shadow_ray.comp"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
RH = RV + "vk_rt_shadow.h"
RC = RV + "vk_rt_shadow.cpp"
EF = RV + "vk_rasterizer_effects.cpp"
R = "README.md"
NEWH = RV + "rt_card_skinned.h"
FILES = (G, S, L, C, RH, RC, EF, R)

NEW_FILES = {
NEWH: r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r62n_cutout-skinned-blocker): which skinned cut-out cards may cast lamp shadows (BB_RT_CARD_LAMP_SKINNED), and what a card that
// blocks lamp light is (the blocker lines of the lamp pass). No Vulkan here: the rule, the counts and the names only.
//
// A skinned cut-out is a card whose draw binds a skeleton palette (Motion::BufferRole::Skeleton, 640 bytes or more). r62e lets one cast
// a lamp shadow only when r46b's sign takes it for a plant (`lone`: no sun shadow pass draws its vertices while the sun shadow pass
// draws skeletons). A skinned entry has no motion measure (it is refit at every draw; the still looks hold only entries that are not
// dynamic), so 'moves' is taken as 'is the rig of a figure': more bones than BB_RT_CARD_LAMP_BONES (default 24, r112h's limit; the
// hunter's gear has 28 bones, enemies 69-130, the hunter 277).

#include <array>
#include <cstdint>

namespace Vulkan {

/// BB_RT_CARD_LAMP_SKINNED: Rule (0, the default) a lone skinned card casts when its skeleton has few bones; All (1) every lone skinned
/// card (r62m's behaviour); None (2) none.
enum class CardSkinnedMode : std::uint8_t { Rule = 0, All = 1, None = 2 };

/// The knob's text: exactly "1" or "2"; anything else, none set included, is the rule.
[[nodiscard]] constexpr CardSkinnedMode CardSkinnedModeOf(const char* text) noexcept {
    if (text != nullptr && text[0] != '\0' && text[1] == '\0') {
        return text[0] == '1'   ? CardSkinnedMode::All
               : text[0] == '2' ? CardSkinnedMode::None
                                : CardSkinnedMode::Rule;
    }
    return CardSkinnedMode::Rule;
}

inline constexpr std::uint32_t CardSkinnedBonesDefault = 24;
inline constexpr std::uint32_t CardSkinnedBonesMost = 341; ///< 16384 bytes of palette / 48

/// BB_RT_CARD_LAMP_BONES: a whole number from 1 to CardSkinnedBonesMost; anything else the default.
[[nodiscard]] constexpr std::uint32_t CardSkinnedBonesOf(const char* text) noexcept {
    if (text == nullptr || text[0] == '\0') {
        return CardSkinnedBonesDefault;
    }
    std::uint32_t value = 0;
    for (const char* p = text; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9' || value > 1000) {
            return CardSkinnedBonesDefault;
        }
        value = value * 10 + std::uint32_t(*p - '0');
    }
    return value >= 1 && value <= CardSkinnedBonesMost ? value : CardSkinnedBonesDefault;
}

/// May a lone skinned cut-out card with `bones` bones (0: none read) carry the lamp card bit?
[[nodiscard]] constexpr bool CardSkinnedLampOk(CardSkinnedMode mode, std::uint32_t bones,
                                               std::uint32_t bones_most) noexcept {
    return mode == CardSkinnedMode::All ||
           (mode == CardSkinnedMode::Rule && bones != 0 && bones <= bones_most);
}

/// What the rule judged in the last scene: the lone skinned cut-out cards, how many it let cast, and the judged by bones
/// (at most 24, 25 to 48, 49 to 96, more or none read).
struct CardSkinnedScene {
    std::uint32_t judged = 0, allowed = 0;
    std::array<std::uint32_t, 4> bins{};
    constexpr void Note(bool ok, std::uint32_t bones) noexcept {
        ++judged;
        allowed += ok ? 1u : 0u;
        ++bins[bones == 0 ? 3 : bones <= 24 ? 0 : bones <= 48 ? 1 : bones <= 96 ? 2 : 3];
    }
};

/// What a card that blocked lamp light is, by what is known of it and of the hunter.
enum class CardBlockerKind : std::uint8_t { Unknown, Plant, Character, Hunter };

inline constexpr float CardHunterNearM = 1.5f;  ///< m sideways (r112h's BB_WIND_HANG_NEAR)
inline constexpr float CardHunterBelow = 1.5f;  ///< m under his position
inline constexpr float CardHunterAbove = 2.5f;  ///< m over his position

/// A point `horizontal_m` sideways and `up_m` above the hunter's position (up_m negative: under it) lies on him.
[[nodiscard]] constexpr bool CardNearHunter(float horizontal_m, float up_m, float near_m) noexcept {
    return near_m > 0.0f && horizontal_m <= near_m && up_m >= -CardHunterBelow && up_m <= CardHunterAbove;
}

/// Unknown: no skeleton. A rig of a figure (not lone, or over `bones_most` bones): the hunter when on him, else a character. Else a plant.
[[nodiscard]] constexpr CardBlockerKind CardBlockerKindOf(bool skinned, bool lone, std::uint32_t bones,
                                                          std::uint32_t bones_most, bool on_hunter) noexcept {
    if (!skinned) {
        return CardBlockerKind::Unknown;
    }
    if (!lone || bones > bones_most) {
        return on_hunter ? CardBlockerKind::Hunter : CardBlockerKind::Character;
    }
    return CardBlockerKind::Plant;
}

[[nodiscard]] constexpr const char* CardBlockerKindText(CardBlockerKind kind) noexcept {
    switch (kind) {
    case CardBlockerKind::Hunter:
        return "the hunter";
    case CardBlockerKind::Character:
        return "a character";
    case CardBlockerKind::Plant:
        return "a plant";
    default:
        return "unknown";
    }
}

} // namespace Vulkan
''',
}

EDITS = {
G: [
("float card_kept_lod = 0.0;\n",
 r"""float card_kept_lod = 0.0;
// bbport (r62n_cutout-skinned-blocker) FEATURE: card_skip_from: a card met at a hit farther than this many metres along the ray is passed
// untested (a lamp's own housing or hook: the lamp pass sets it to the ray's length minus CARD_HOUSING; 1e30: never); card_housing_skips:
// the cards passed that way (the lamp pass counts them and zeroes it).
float card_skip_from = 1e30;
uint card_housing_skips = 0u;
"""),
("            const float t = rayQueryGetIntersectionTEXT(query, false);\n            const float texels",
 r"""            const float t = rayQueryGetIntersectionTEXT(query, false);
            if (t > card_skip_from) { // bbport (r62n_cutout-skinned-blocker) FEATURE: the lamp's own housing casts no shadow
                ++card_housing_skips;
                continue;
            }
            const float texels"""),
],
L: [
("#define CARD_LAMP_LIT_ON_CARD 64\n",
 r"""#define CARD_LAMP_LIT_ON_CARD 64
#define CARD_LAMP_HOUSING_SKIPS 65 // bbport (r62n_cutout-skinned-blocker): cut-out cards passed untested within the housing zone of the lamp
"""),
],
S: [
("layout(constant_id = 13) const uint CARD_SPLIT_PHASE = 0u;\n",
 r"""layout(constant_id = 13) const uint CARD_SPLIT_PHASE = 0u;
// bbport (r62n_cutout-skinned-blocker) FEATURE: specialization constant 14 (vk_point_shadow.cpp, BB_RT_CARD_LAMP_HOUSING, metres, default 0.4, 0 off): a
// cut-out card met within this distance of the lamp end of a lamp ray is passed untested (card_skip_from in rt_cards.glsl): the lamp's own housing, hook
// or chain would black out the lamp.
layout(constant_id = 14) const float CARD_HOUSING = 0.0;
"""),
("        card_lod16 = 0u;\n        const CardRay card_hit",
 r"""        card_lod16 = 0u;
        card_skip_from = CARD_HOUSING > 0.0 ? card_len - CARD_HOUSING : 1e30; // bbport (r62n_cutout-skinned-blocker) FEATURE
        const CardRay card_hit"""),
("        card_strict_drops = 0u;\n        ray_card_kept = card_hit.how == CARD_RAY_KEPT;\n",
 r"""        card_strict_drops = 0u;
        cardCount(CARD_LAMP_HOUSING_SKIPS, card_housing_skips); // bbport (r62n_cutout-skinned-blocker) FEATURE
        card_housing_skips = 0u;
        card_skip_from = 1e30;
        ray_card_kept = card_hit.how == CARD_RAY_KEPT;
"""),
("    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x04u | CARD_LAMP_MASK,\n",
 r"""    card_skip_from = CARD_HOUSING > 0.0 ? ray_len - CARD_HOUSING : 1e30; // bbport (r62n_cutout-skinned-blocker) FEATURE
    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x04u | CARD_LAMP_MASK,
"""),
("    card_strict_drops = 0u;\n    ray_card_kept = hit.how == CARD_RAY_KEPT;\n",
 r"""    card_strict_drops = 0u;
    cardCount(CARD_LAMP_HOUSING_SKIPS, card_housing_skips); // bbport (r62n_cutout-skinned-blocker) FEATURE
    card_housing_skips = 0u;
    card_skip_from = 1e30;
    ray_card_kept = hit.how == CARD_RAY_KEPT;
"""),
],
C: [
("    u32 split_phase;   // TOOL: BB_RT_CARD_LAMP_SPLIT_PHASE, 0 or 1\n};\n",
 r"""    u32 split_phase;   // TOOL: BB_RT_CARD_LAMP_SPLIT_PHASE, 0 or 1
    float housing_m;   // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, default 0.4 (0: off)
};
"""),
("4.0f, 0.0f, 0u, 0u}; // (r62h: three more;",
 "4.0f, 0.0f, 0u, 0u, 0.4f}; // (r62n_cutout-skinned-blocker: the housing zone) (r62h: three more;"),
('        e.split_phase = flag("BB_RT_CARD_LAMP_SPLIT_PHASE", e.split_phase);\n',
 r"""        e.split_phase = flag("BB_RT_CARD_LAMP_SPLIT_PHASE", e.split_phase);
        e.housing_m = number("BB_RT_CARD_LAMP_HOUSING", e.housing_m, 0.0f, 2.0f); // bbport (r62n_cutout-skinned-blocker) FEATURE
"""),
("    const std::array<u32, 14> spec_words{", "    const std::array<u32, 15> spec_words{"),
("extras.split, extras.split_phase}; // (r62l",
 "extras.split, extras.split_phase, std::bit_cast<u32>(extras.housing_m)}; // (r62n_cutout-skinned-blocker: 14 CARD_HOUSING) (r62l"),
("const std::array<vk::SpecializationMapEntry, 14> spec_entries{{", "const std::array<vk::SpecializationMapEntry, 15> spec_entries{{"),
("{12, 48, 4}, {13, 52, 4}}};", "{12, 48, 4}, {13, 52, 4}, {14, 56, 4}}};"),
('                        extras.split != 0 ? "on" : "off");\n        }\n',
 r"""                        extras.split != 0 ? "on" : "off");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62n_cutout-skinned-blocker)
            std::printf("Foliage lamp shadows (r62n): a cut-out card within %.2f m of a lamp casts no lamp shadow (BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, "
                        "0 off: the lamp's own housing or hook); lone skinned cut-outs: the line 'Foliage lamp shadows (r62n) skinned' says the "
                        "mode and the bones (BB_RT_CARD_LAMP_SKINNED, BB_RT_CARD_LAMP_BONES); the window lines of r62m name the blockers "
                        "('is the hunter, a character, a plant, unknown'); a line 'Foliage lamp shadows (r62n) <w>' counts the front reads "
                        "of the proof view and the housing skips\n",
                        double(extras.housing_m));
        }
"""),
(r"""                    double(info.box[4]), double(info.box[5]), info.box_src, info.op, double(info.reference), info.layer);
""",
 r"""                    double(info.box[4]), double(info.box[5]), info.box_src, info.op, double(info.reference), info.layer);
        // bbport (r62n_cutout-skinned-blocker) TOOL: what the blocker is. The skeleton's bones, r46b's sign and the hunter (the game's physics
        // position, BbEngine::world_player_position) against the hits' centre: 'the hunter' a figure-sized rig (not lone, or over
        // BB_RT_CARD_LAMP_BONES bones) whose hits lie within 1.5 m sideways of him and from 1.5 m under to 2.5 m over his position (r112h's
        // test), 'a character' such a rig elsewhere, 'a plant' a lone skinned card with few bones, 'unknown' a card with no skeleton.
        if (n < 2 && info.found) {
            const std::array<float, 3> centre{float(0.5 * (lo(0) + hi(0))), float(0.5 * (lo(1) + hi(1))), float(0.5 * (lo(2) + hi(2)))};
            const RtShadow::HunterRel hunter = rt.HunterAgainst(centre);
            const bool on_hunter = hunter.known && CardNearHunter(hunter.horizontal_m, hunter.up_m, CardHunterNearM);
            const CardBlockerKind kind =
                CardBlockerKindOf(info.skinned, info.lone, info.bones, RtShadow::CardSkinnedBonesNow(), on_hunter);
            std::printf("Foliage lamp shadows (r62n) blocker %s #%u is %s: %.0f px, %u bones, %s, hits' centre %.1f %.1f %.1f m (view), hunter %s at "
                        "%.1f %.1f %.1f m (view), %.2f m sideways and %.2f m up of him, skinned mode %u\n",
                        tag, n + 1, CardBlockerKindText(kind), row.px, info.bones, info.lone_text, double(centre[0]), double(centre[1]),
                        double(centre[2]), hunter.known ? "read" : "unread", double(hunter.view[0]), double(hunter.view[1]),
                        double(hunter.view[2]), double(hunter.horizontal_m), double(hunter.up_m),
                        unsigned(RtShadow::CardSkinnedModeNow()));
        }
"""),
("    CardBlockerLines(book_now, book_last, rt, tag, both);\n",
 r"""    CardBlockerLines(book_now, book_last, rt, tag, both);
    // bbport (r62n_cutout-skinned-blocker) TOOL: the camera-ray front reads of the proof view (BB_RT_CARD_LAMP_PROOF_VIEW=1 with BB_LAMP_SHADOW_VIEW=7:
    // the cards in front of a surface the game dropped, and what each rule keeps there) and the housing skips, in one short line a window
    // that has either prints (a window without proof pixels and without skips prints none: front reads are then 0 by construction)
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0 || d[CARD_LAMP_HOUSING_SKIPS] > 0.0) {
        const double reads = d[CARD_LAMP_PROOF_FRONT_READS];
        std::printf("Foliage lamp shadows (r62n) %s: front reads %.0f (game kept %.1f %%, game alpha 0 %.1f %%, lamp rule kept %.1f %%) of %.0f proof px; "
                    "housing skips %.0f (zone %.2f m); skinned mode %u\n",
                    tag, reads, share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], reads), share(d[CARD_LAMP_PROOF_FRONT_ZERO], reads),
                    share(d[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], reads), d[CARD_LAMP_PROOF_PIXELS], d[CARD_LAMP_HOUSING_SKIPS],
                    double(CardExtrasFromEnv().housing_m), unsigned(RtShadow::CardSkinnedModeNow()));
    }
"""),
],
RH: [
('#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)\n',
 r"""#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/rt_card_skinned.h" // bbport (r62n_cutout-skinned-blocker)
"""),
("        bool solid = false;\n        bool skinned = false;\n        bool alpha = false;\n",
 r"""        bool solid = false;
        bool skinned = false;
        // bbport (r62n_cutout-skinned-blocker): the bones of the skeleton palette a skinned draw binds (its size / 48; 0: none)
        u32 skeleton_bones = 0;
        bool alpha = false;
"""),
("        bool built = false;\n        bool dynamic = false;\n        bool rebuilt = false;\n",
 r"""        bool built = false;
        bool dynamic = false;
        bool rebuilt = false;
        // bbport (r62n_cutout-skinned-blocker): the most bones of a skeleton palette any draw of the entry bound (0: none read)
        u32 skeleton_bones = 0;
"""),
("        std::array<float, 3> centre_view{};\n    };\n    [[nodiscard]] CardBlockerInfo CardBlockerOf(u32 slot) const;\n",
 r"""        std::array<float, 3> centre_view{};
        // bbport (r62n_cutout-skinned-blocker) TOOL: the most bones of a skeleton palette a draw of it bound (0: none), r46b's sign (lone: no sun
        // shadow pass draws its vertices) and its words
        u32 bones = 0;
        bool lone = false;
        const char* lone_text = "not skinned";
    };
    [[nodiscard]] CardBlockerInfo CardBlockerOf(u32 slot) const;
    // bbport (r62n_cutout-skinned-blocker) TOOL: the hunter (the game's physics position, BbEngine::world_player_position: false while it is not
    // readable) against a point in view space: his place in world and view space, how far the point lies from him sideways (x and z of the world,
    // y up) and how far above him (negative: below). Reads the engine's memory: a few pointer reads, from the lamp pass's window line only.
    struct HunterRel {
        bool known = false;
        std::array<float, 3> world{}, view{};
        float horizontal_m = 0.0f, up_m = 0.0f;
    };
    [[nodiscard]] HunterRel HunterAgainst(const std::array<float, 3>& point_view) const;
    // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_SKINNED (live with the test knobs file when present, else read at start) and
    // BB_RT_CARD_LAMP_BONES (read at start): see rt_card_skinned.h
    [[nodiscard]] static CardSkinnedMode CardSkinnedModeNow();
    [[nodiscard]] static u32 CardSkinnedBonesNow();
"""),
("    CardSafeScene card_safe_now;\n",
 r"""    CardSafeScene card_safe_now;
    CardSkinnedScene card_skinned_now; // bbport (r62n_cutout-skinned-blocker): the last scene's lone skinned cut-outs by the rule
    bool card_skinned_said = false;
"""),
("    void CardSafeLog();\n",
 r"""    void CardSafeLog();
    void CardSkinnedLog(); // bbport (r62n_cutout-skinned-blocker)
"""),
],
RC: [
('#include "video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e_leaf-cards-usable)\n',
 r"""#include "video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e_leaf-cards-usable)
#include "engine/engine_state.h" // bbport (r62n_cutout-skinned-blocker) TOOL: the hunter's position for the blocker lines
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // bbport (r62n_cutout-skinned-blocker): the test tools' (r84) live knobs, when present
#define BB_R62N_LIVE_KNOBS 1
#endif
"""),
("    entry.skinned = entry.skinned || draw.skinned;\n",
 r"""    entry.skinned = entry.skinned || draw.skinned;
    entry.skeleton_bones = std::max(entry.skeleton_bones, draw.skeleton_bones); // bbport (r62n_cutout-skinned-blocker)
"""),
("    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;\n    card_safe_now = {}; // bbport (r62e_leaf-cards-usable): of the records written now\n",
 r"""    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    card_safe_now = {}; // bbport (r62e_leaf-cards-usable): of the records written now
    // bbport (r62n_cutout-skinned-blocker) FEATURE: which lone skinned cut-out cards may cast lamp shadows (BB_RT_CARD_LAMP_SKINNED: 0 only a
    // few-bones one, 1 every one, 2 none); only asked while the lamp rays read the cards
    card_skinned_now = {};
    const CardSkinnedMode skinned_mode = card_lamps ? CardSkinnedModeNow() : CardSkinnedMode::All;
    const u32 skinned_bones = card_lamps ? CardSkinnedBonesNow() : CardSkinnedBonesDefault;
"""),
("        const bool lamp_card = card_lamps && card && !leave && !old_pose && mask != 0 &&\n",
 r"""        // bbport (r62n_cutout-skinned-blocker) FEATURE: a lone skinned cut-out (r46b's plant sign) the rule judges (rt_card_skinned.h)
        const bool skinned_judged = card_lamps && card && entry->skinned && lone;
        const bool skinned_ok =
            !skinned_judged || CardSkinnedLampOk(skinned_mode, entry->skeleton_bones, skinned_bones);
        if (skinned_judged) {
            card_skinned_now.Note(skinned_ok, entry->skeleton_bones);
        }
        const bool lamp_card = card_lamps && card && !leave && !old_pose && mask != 0 &&
"""),
("                               (!entry->skinned || lone) && CardLampOn(*entry);\n",
 "                               (!entry->skinned || (lone && skinned_ok)) && CardLampOn(*entry);\n"),
("        CardSafeLog(); // bbport (r62e_leaf-cards-usable): with BB_RT_CARD_ALPHA on\n",
 r"""        CardSafeLog(); // bbport (r62e_leaf-cards-usable): with BB_RT_CARD_ALPHA on
        CardSkinnedLog(); // bbport (r62n_cutout-skinned-blocker): with BB_RT_CARD_LAMPS=1
"""),
("        r.vertices = e->vertices;\n        const u32 flags = e->card_uv->row[2];\n",
 r"""        r.vertices = e->vertices;
        r.bones = e->skeleton_bones; // bbport (r62n_cutout-skinned-blocker) TOOL
        r.lone = e->lone == LampLoneState::Lone;
        r.lone_text = !e->skinned                          ? "not skinned"
                      : e->lone == LampLoneState::Lone     ? "lone"
                      : e->lone == LampLoneState::Sun      ? "drawn by the sun shadow pass"
                      : e->lone == LampLoneState::Waiting  ? "not settled"
                                                           : "no verdict";
        const u32 flags = e->card_uv->row[2];
"""),
("// bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry (one with card\n",
 r"""// bbport (r62n_cutout-skinned-blocker) TOOL: see the declaration. The camera's inverse view takes the point to the world; the hunter's place is
// the game's (y up): sideways is x and z, up is y.
RtShadow::HunterRel RtShadow::HunterAgainst(const std::array<float, 3>& point_view) const {
    HunterRel r;
    const auto m = camera_motion.CameraMatrices();
    float pos[3] = {0.0f, 0.0f, 0.0f};
    if (!m.valid || !BbEngine::world_player_position(pos) || !std::isfinite(pos[0]) || !std::isfinite(pos[1]) ||
        !std::isfinite(pos[2])) {
        return r;
    }
    r.known = true;
    std::array<float, 3> at{};
    for (u32 i = 0; i < 3; ++i) {
        r.world[i] = pos[i];
        r.view[i] = m.view[i * 4] * pos[0] + m.view[i * 4 + 1] * pos[1] + m.view[i * 4 + 2] * pos[2] + m.view[i * 4 + 3];
        at[i] = m.inv_view[i * 4] * point_view[0] + m.inv_view[i * 4 + 1] * point_view[1] +
                m.inv_view[i * 4 + 2] * point_view[2] + m.inv_view[i * 4 + 3];
    }
    const float dx = at[0] - pos[0];
    const float dz = at[2] - pos[2];
    r.horizontal_m = std::sqrt(dx * dx + dz * dz);
    r.up_m = at[1] - pos[1];
    return r;
}

// bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_SKINNED: 0 (default) a lone skinned cut-out casts a lamp shadow when it has at most
// BB_RT_CARD_LAMP_BONES bones, 1 every one (r62m), 2 none (rt_card_skinned.h). With r84's knobs file present it is asked again at every change of
// the file (a test flips it in one running game); without, the environment's value at the first call.
CardSkinnedMode RtShadow::CardSkinnedModeNow() {
#ifdef BB_R62N_LIVE_KNOBS
    static BbLiveKnobs::Knob<u32> knob{"BB_RT_CARD_LAMP_SKINNED",
                                       [](const char* text) -> u32 { return u32(CardSkinnedModeOf(text)); }};
    return static_cast<CardSkinnedMode>(knob.Get());
#else
    static const CardSkinnedMode mode = CardSkinnedModeOf(std::getenv("BB_RT_CARD_LAMP_SKINNED"));
    return mode;
#endif
}

// BB_RT_CARD_LAMP_BONES: read once (1 to 341, default 24).
u32 RtShadow::CardSkinnedBonesNow() {
    static const u32 bones = CardSkinnedBonesOf(std::getenv("BB_RT_CARD_LAMP_BONES"));
    return bones;
}

// bbport (r62n_cutout-skinned-blocker) FEATURE: every 600 frames while the lamp rays read the cards: the lone skinned cut-out cards the rule
// judged in the last scene, how many it let cast lamp shadows, and by bones (at most 24, 25 to 48, 49 to 96, more or none read). Said once at
// the first call. Nothing runs without BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1.
void RtShadow::CardSkinnedLog() {
    if (!card_layers_on || !CardLampsWanted()) {
        return;
    }
    const CardSkinnedMode mode = CardSkinnedModeNow();
    if (!card_skinned_said) {
        card_skinned_said = true;
        std::printf("Foliage lamp shadows (r62n): lone skinned cut-out cards: BB_RT_CARD_LAMP_SKINNED=%u (%s), BB_RT_CARD_LAMP_BONES=%u: a lone "
                    "skinned card (no sun shadow pass draws it) casts a lamp shadow when it has at most that many bones; a skinned card that is not "
                    "lone never does (r62e); the line 'Foliage lamp shadows (r62n) skinned' counts them every 600 frames\n",
                    unsigned(mode),
                    mode == CardSkinnedMode::All    ? "every lone skinned card casts, as r62m"
                    : mode == CardSkinnedMode::None ? "none casts"
                                                    : "a lone skinned card with few bones casts",
                    CardSkinnedBonesNow());
    }
    const CardSkinnedScene& s = card_skinned_now;
    std::printf("Foliage lamp shadows (r62n) skinned: %u lone skinned cut-outs judged in the last scene, %u let cast lamp shadows (mode %u, at most "
                "%u bones); by bones %u up to 24, %u of 25 to 48, %u of 49 to 96, %u more or none read\n",
                s.judged, s.allowed, unsigned(mode), CardSkinnedBonesNow(), s.bins[0], s.bins[1], s.bins[2], s.bins[3]);
}

// bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry (one with card
"""),
],
EF: [
("                draw.skinned = true;\n",
 r"""                draw.skinned = true;
                draw.skeleton_bones = std::max(draw.skeleton_bones, size / 48u); // bbport (r62n_cutout-skinned-blocker)
"""),
],
}

ROWS_OLD = "blocker` lines) | `0` (off), `0` |\n"
ROWS_NEW = ROWS_OLD + (
    "| `BB_RT_CARD_LAMP_SKINNED`, `BB_RT_CARD_LAMP_BONES`, `BB_RT_CARD_LAMP_HOUSING` | FEATURE, only with `BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1` "
    "(r62n). Which cut-out cards cast lamp shadows. `BB_RT_CARD_LAMP_SKINNED` (exactly `0`, `1` or `2`; asked again at every change of the live test knobs "
    "file when that is present, else read at start): a skinned cut-out card that no sun shadow pass draws (a plant) is `0` (default) allowed to cast when its "
    "skeleton has at most `BB_RT_CARD_LAMP_BONES` bones (a whole number 1 to 341, read at start, default 24: the figure limit of the hanging things; a "
    "figure's rig has more: the hunter 277, enemies 69 to 130; a skinned card has no motion measure, so a figure-sized rig stands for one that moves), `1` "
    "every one (as r62m), `2` none; a skinned card that is not drawn alone (a character) never casts, in any mode. `BB_RT_CARD_LAMP_HOUSING`: metres, 0 to 2, "
    "read at start, default `0.4` (`0` off): a cut-out card within that distance of the lamp end of a lamp ray is passed untested (the lamp's own housing, "
    "hook or chain; solid geometry keeps the lamp clearance). Log: a once-line, `Foliage lamp shadows (r62n) skinned` every 600 frames (the cards the rule "
    "judged by bones and how many it let cast), and in the window of r62m `blocker <w> #n is <the hunter, a character, a plant, unknown>` and `Foliage lamp "
    "shadows (r62n) <w>` (the proof view's front reads and the housing skips). Cost: off none; on one compare per lone skinned card per scene and one per "
    "card candidate of a lamp ray (estimate, not measured) | `0`, `24`, `0.4` |\n")


def readme_edits(text):
    if text.count(ROWS_OLD) != 1 and text.count(ROWS_NEW) != 1:
        raise SystemExit("README.md: the r62m row ending is there %d times, wanted 1 (r62m applied?)" % text.count(ROWS_OLD))
    return [(ROWS_OLD, ROWS_NEW)]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit, else refuse. A swap (new does not hold old) is applied when old is gone and
    new is there once; an insert (new holds old) when new is there once."""
    done = todo = 0
    for old, new in eds:
        n_old, n_new = cur.count(old), cur.count(new)
        holds = old in new
        if n_old == 1 and n_new == 0:
            todo += 1
        elif (holds and n_old == 1 and n_new == 1) or (not holds and n_old == 0 and n_new == 1):
            done += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted once, none): %r"
                             % (path, n_old, n_new, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def inside_only(text, markers, flags, what):
    """Every line holding one of `markers` lies inside an #ifdef of `flags` (a set of names)."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#ifdef") or st.startswith("#ifndef") or st.startswith("#if "):
            stack.append(st.startswith("#ifdef") and st.split()[1] in flags)
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = False
        elif any(m in line for m in markers) and not any(stack):
            raise SystemExit("text check: %s: a line of r62n is outside its #ifdef: %r" % (what, line))


def text_checks(texts):
    g, s, l, c, rh, rc, ef, r = (texts[p] for p in FILES)
    # the lamp shader: every r62n line lies in the CARDS builds; the knob and the counter are used where they are said
    inside_only(s, ("r62n", "CARD_HOUSING", "card_skip_from", "card_housing_skips", "CARD_LAMP_HOUSING_SKIPS"), {"CARDS"}, S)
    inside_only(g, ("card_skip_from", "card_housing_skips"), {"CARD_TRACE_SHADOW"}, G)
    for want, n in (("card_skip_from = CARD_HOUSING > 0.0 ?", 2), ("cardCount(CARD_LAMP_HOUSING_SKIPS, card_housing_skips);", 2),
                    ("card_housing_skips = 0u;", 2), ("card_skip_from = 1e30;", 2)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    if g.count("if (t > card_skip_from)") != 1 or g.count("float card_skip_from = 1e30;") != 1:
        raise SystemExit("text check: rt_cards.glsl skip")
    if l.count("#define CARD_LAMP_HOUSING_SKIPS 65 ") != 1 or "#define CARD_LAMP_COUNTERS 72" not in l:
        raise SystemExit("text check: the housing counter slot")
    # the spec constants: 15 words, 15 entries, constant 14 read as a float
    if c.count("std::array<u32, 15> spec_words") != 1 or c.count("std::array<vk::SpecializationMapEntry, 15> spec_entries") != 1 \
       or c.count("{14, 56, 4}") != 1 or c.count("std::bit_cast<u32>(extras.housing_m)") != 1:
        raise SystemExit("text check: the 15 specialization constants")
    if s.count("layout(constant_id = 14) const float CARD_HOUSING = 0.0;") != 1:
        raise SystemExit("text check: constant 14")
    ids = sorted(int(x.split(")")[0]) for x in s.split("layout(constant_id = ")[1:])
    if ids != list(range(15)):
        raise SystemExit("text check: the shader's constant ids are %r" % ids)
    # the rule: asked once a record, only behind card_lamps
    if rc.count("CardSkinnedLampOk(skinned_mode, entry->skeleton_bones, skinned_bones)") != 1 or rc.count("(lone && skinned_ok)") != 1 \
       or rc.count("(!entry->skinned || lone)") != 0:
        raise SystemExit("text check: the lamp card rule")
    if rc.count("const CardSkinnedMode skinned_mode = card_lamps ? CardSkinnedModeNow() : CardSkinnedMode::All;") != 1:
        raise SystemExit("text check: the rule is not behind card_lamps")
    if rc.count("CardSkinnedLog();") != 1 or rc.count("void RtShadow::CardSkinnedLog() {") != 1:
        raise SystemExit("text check: the log call")
    for want, n in (("RtShadow::HunterRel RtShadow::HunterAgainst(", 1), ("CardSkinnedMode RtShadow::CardSkinnedModeNow() {", 1),
                    ("u32 RtShadow::CardSkinnedBonesNow() {", 1), ("entry.skeleton_bones = std::max(", 1)):
        if rc.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times" % (RC, want, rc.count(want)))
    for want in ("[[nodiscard]] HunterRel HunterAgainst(", "[[nodiscard]] static CardSkinnedMode CardSkinnedModeNow();",
                 "[[nodiscard]] static u32 CardSkinnedBonesNow();", "void CardSkinnedLog();", "u32 skeleton_bones = 0;"):
        if rh.count(want) < 1:
            raise SystemExit("text check: %s lacks %r" % (RH, want))
    if rh.count("u32 skeleton_bones = 0;") != 2:
        raise SystemExit("text check: skeleton_bones is declared %d times, wanted 2 (Draw, Entry)" % rh.count("u32 skeleton_bones = 0;"))
    if ef.count("draw.skeleton_bones = std::max(draw.skeleton_bones, size / 48u);") != 1:
        raise SystemExit("text check: the palette bones")
    if c.count("is %s: %.0f px, %u bones") != 1 or c.count("Foliage lamp shadows (r62n) %s: front reads") != 1:
        raise SystemExit("text check: the lamp pass's r62n lines")
    if r.count("`BB_RT_CARD_LAMP_SKINNED`, `BB_RT_CARD_LAMP_BONES`, `BB_RT_CARD_LAMP_HOUSING`") != 1:
        raise SystemExit("text check: README row")
    # the new text: ASCII, no local path, balanced, no Windows macro names as identifiers
    allnew = NEW_FILES[NEWH]
    for edits in EDITS.values():
        for old, new in edits:
            if "\r" in new:
                raise SystemExit("new text must have LF only in the script")
            allnew += new
    for path, new in list(NEW_FILES.items()) + [(p, n) for p, es in EDITS.items() if p != R for _, n in es]:
        if not all(ord(ch) < 128 for ch in new):
            raise SystemExit("%s: new text must be ASCII" % path)
        if any(x in new for x in ("C:/", "G:/", "<user>", "Temp/claude")):
            raise SystemExit("a local path in the patch's text")
    for bad in (r"(float|bool|int|auto|u32)\s+(near|far)", r"\s(near|far)\s*=[^=]", r"\.(near|far)"):
        if re.search(bad, allnew):
            raise SystemExit("the name near or far is a macro on some Windows headers: %r" % bad)
    for path, new in NEW_FILES.items():
        if new.count("{") != new.count("}") or new.count("(") != new.count(")"):
            raise SystemExit("%s: braces or parentheses do not balance" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62N_CUTOUT_SKINNED_BLOCKER_ROOT)" % ROOT)
    for path in FILES:  # apply writes nothing when a file is missing
        if not os.path.isfile(os.path.join(ROOT, path)):
            raise SystemExit("%s is missing" % path)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    new_state = []
    for path, content in NEW_FILES.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            new_state.append("clean")
        elif open(full, "rb").read().decode("utf-8").replace("\r\n", "\n") == content:
            new_state.append("applied")
        else:
            raise SystemExit("%s exists and is not this patch's file" % path)
    states = {p[5] for p in plan} | set(new_state)
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + " new " + ",".join(new_state))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new)
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
            print("not applied; would apply (%d files, %d edits, %d new; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW_FILES)))
        return
    if cmd == "apply":
        if state == "applied":
            print("REFUSED: already applied")
            sys.exit(1)
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r62ntmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        for path, content in NEW_FILES.items():  # new files take the line ends of the tree (CRLF)
            full = os.path.join(ROOT, path)
            tmp = full + ".r62ntmp"
            open(tmp, "wb").write(content.replace("\n", "\r\n").encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r62ntmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path in NEW_FILES:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
