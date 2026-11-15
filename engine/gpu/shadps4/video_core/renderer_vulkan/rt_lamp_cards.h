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
    /// bbport (r47c_review-fixes): the bytes of vertices its draws bind there (0: not known yet)
    std::uint32_t size = 0;
    bool sun = false; ///< a sun shadow pass drew it, kept while the address holds this mesh
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

/// bbport (r47c_review-fixes): a draw binds `size` bytes of vertices at a known stream's
/// address. The streams are known by their address alone for as long as the game runs, and the
/// game hands the memory of a mesh it unloaded to the next one it loads: a character's cloth at
/// a plant's old address would be lone at once (and stay so where no sun shadow pass draws:
/// indoors), a plant at a character's old address would keep its rectangle of shadow for good.
/// Another size than the stream was known with says the vertices are another mesh's: what was
/// known is forgotten and the stream waits again, which keeps it in lamp rays. Not forgotten by
/// age: a plant that was out of view for a while would throw its rectangle for LampLoneFrames
/// frames each time it came back. A draw whose size is not known (0) changes nothing. True when
/// LampLoneOf changed.
constexpr bool LampLoneSized(LampLone& known, std::uint32_t size) noexcept {
    if (size == 0 || known.size == size) {
        return false;
    }
    const bool first = known.size == 0;
    known.size = size;
    if (first) {
        return false;
    }
    const bool changed = LampLoneOf(known) != LampLoneState::Waiting;
    known.frames = 0;
    known.frame = 0;
    known.sun = false;
    return changed;
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
