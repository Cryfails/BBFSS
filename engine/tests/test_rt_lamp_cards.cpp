// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r46_lamp-cards): which entries of the ray tracing scene lamp rays leave out as cut-out
// cards (rt_lamp_cards.h), over every combination of what RtShadow knows of an entry, and the
// plants' ways into lamp rays under the rule of before.
// bbport (r46b_plant-rule): level 3 (cut-outs with a skeleton that no sun shadow pass draws stay
// out too) and the count that makes a position stream "lone" (LampLone).
// bbport (r47c_review-fixes): a stream's address given to another mesh (LampLoneSized).
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_copy_turns.h"
#include "gpu/shadps4/video_core/renderer_vulkan/rt_lamp_cards.h"
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_still.h" // bbport (r62e)

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
    {
        // bbport (r47c_review-fixes): the game hands a stream's address to another mesh
        // (another size of vertices is bound there): what was known of it is forgotten.
        LampLone reused;
        assert(!LampLoneSized(reused, 4800) && reused.size == 4800); // its first draw
        assert(CameraFrames(reused, 10, LampLoneFrames) == 1);
        assert(LampLoneOf(reused) == LampLoneState::Lone);
        // The same size, or a draw whose size is not known: nothing changes.
        assert(!LampLoneSized(reused, 4800) && !LampLoneSized(reused, 0));
        assert(LampLoneOf(reused) == LampLoneState::Lone && reused.size == 4800);
        // A character's cloth at the plant's old address: waiting again, so kept in lamp rays,
        // also where no sun shadow pass draws (indoors), for as long as it is drawn.
        assert(LampLoneSized(reused, 7200) && LampLoneOf(reused) == LampLoneState::Waiting);
        assert(reused.frames == 0 && reused.size == 7200);
        for (std::uint64_t frame = 100; frame < 1100; ++frame) {
            assert(!LampLoneCameraDraw(reused, frame, false, 0));
        }
        assert(LampLoneOf(reused) == LampLoneState::Waiting);
        // The other way: a plant at a character's old address counts its frames from nothing.
        assert(LampLoneSunDraw(reused, 1100) && LampLoneOf(reused) == LampLoneState::Sun);
        assert(LampLoneSized(reused, 4800) && LampLoneOf(reused) == LampLoneState::Waiting);
        assert(CameraFrames(reused, 1200, LampLoneFrames - 1) == 0);
        assert(CameraFrames(reused, 1200 + LampLoneFrames - 1, 1) == 1);
        assert(LampLoneOf(reused) == LampLoneState::Lone);
        // A stream that is waiting anyway is forgotten without a change to tell.
        LampLone waiting;
        assert(!LampLoneSized(waiting, 100) && CameraFrames(waiting, 5, 3) == 0);
        assert(waiting.frames == 3 && !LampLoneSized(waiting, 200) && waiting.frames == 0);
    }
    {
        // bbport (r62e_leaf-cards-usable): cut-out shadows (true shape). The rule asks only whether a
        // cut-out is still, never what it shows. A wall lantern's hook, a grille or a railing drawn as
        // a textured card (a camera pass draw that discards, no skeleton, never moved): a card at the
        // default level and still, so it gets card UVs and its true shape in lamp shadows.
        Facts hook;
        hook.card_camera = true;
        assert(Card(false, LampCardLevelDefault, hook));
        assert(CardStillOf(hook.skinned, hook.lone, hook.dynamic) == CardStillWhy::Still);
        Facts grille_by_sun;
        grille_by_sun.card_shadow = true;
        assert(Card(false, LampCardLevelDefault, grille_by_sun));
        assert(CardStillOf(false, false, false) == CardStillWhy::Still);
        // The same grille on a moving door or a carried lantern (dynamic): still a card for the lamp
        // rule of before (no lamp shadow, as with the knobs off), but no card UVs and no lamp card bit.
        Facts moving;
        moving.dynamic = true;
        moving.card_camera = true;
        assert(Card(false, LampCardLevelDefault, moving));
        assert(CardStillOf(moving.skinned, moving.lone, moving.dynamic) == CardStillWhy::Moving);
        // Hair or a coat (a skeleton a sun shadow pass draws, or not settled yet): never.
        assert(CardStillOf(true, false, true) == CardStillWhy::Skinned);
        // A bed of plants (a skeleton no sun shadow pass draws: lone; r89's sway moves only these):
        // still, whatever its skeleton does.
        assert(CardStillOf(true, true, true) == CardStillWhy::Still);
        // A stale copy (an old pose) never has the bit, and the bit stays off for `hold` frames
        // after its last stale record (r41's second shadow stays out; no flip at each turn).
        std::uint64_t last_stale = 0;
        bool on = CardStaleHoldOff(false, 5, last_stale, 120);
        assert(on && last_stale == 0);
        on = CardStaleHoldOff(true, 10, last_stale, 120);
        assert(!on && last_stale == 11);
        on = CardStaleHoldOff(false, 130, last_stale, 120);
        assert(!on); // 120 frames after the stale record: still off
        on = CardStaleHoldOff(false, 131, last_stale, 120);
        assert(on);
        on = CardStaleHoldOff(true, 200, last_stale, 120);
        assert(!on && last_stale == 201);
        // The first change of an entry's bit is its turn-on, every later one a flip.
        bool once = false;
        const bool first = CardMaskTurn(once);
        assert(!first && once);
        const bool second = CardMaskTurn(once);
        const bool third = CardMaskTurn(once);
        assert(second && third);
        // The guard's test of a triangle (rt_card_guard.comp DETECT).
        const float inf = std::numeric_limits<float>::infinity();
        const float nan = std::numeric_limits<float>::quiet_NaN();
        float p[16] = {0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1};
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        assert(CardGuardBad(p, 3, 0, 1, 3, CardGuardEdge)); // a vertex past the build's
        p[4] = 199.0f;
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // edges 199 and 199.0025 m
        p[4] = 300.0f;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // an edge of 300 m
        p[4] = inf;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        p[4] = nan;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        p[4] = 3e38f;
        p[8] = -3e38f;
        assert(CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge)); // finite corners, the edge overflows
        p[4] = 1.0f;
        p[8] = 0.0f;
        p[7] = nan; // w is not read
        assert(!CardGuardBad(p, 4, 0, 1, 2, CardGuardEdge));
        // A dropped build (every vertex at the origin) reads as good: nothing for the check to name.
        const float origin[12] = {};
        assert(!CardGuardBad(origin, 3, 0, 1, 2, CardGuardEdge));
        static_assert(CardGuardEdge == 200.0f && CardGuardSlots == 1024 &&
                      CardGuardWords == 32 + 1024);
        std::printf("rt card still (r62e): ok\n");
    }
    std::printf("rt lamp cards: ok (of the 64 combinations of an entry's signs the rule of before leaves out "
                "%u, level 1 %u, level 2 %u, level 3 %u; a stream is lone after %u frames)\n",
                out_old, out_one, out_two, out_three, LampLoneFrames);
    return 0;
}
