// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r45_drawn-look): the words the drawn look's passes take (host_shaders/paint_common.glsl,
// the Constants block), and how the settings and the frame's camera become them. No Vulkan here:
// tests/test_drawn_look.cpp runs the passes with the same words.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace Vulkan::DrawnLookParams {

/// The push constants of the drawn look's passes (host_shaders/paint_*.comp). 128 bytes: what
/// every GPU takes, and all of it used. The ink's two knobs (Knobs::outlines, ink_world), which
/// no pass reads yet, gave their places to the camera of the frame before
/// (r45b_drawn-look-fixes).
struct Params {
    std::array<float, 12> inv_view; ///< view to world, 3x4 rows
    std::array<float, 4> proj;      ///< x scale, y scale, z scale, z offset
    std::array<float, 2> size;      ///< the scene in pixels
    std::array<float, 2> jitter;    ///< the frame's viewport shift in pixels
    float strength;
    float brush;
    float characters;
    float cell_bold;
    /// From this frame's view axes to those of the frame before: a turn (the vector part of its
    /// unit quaternion; the scalar part is positive) and then a shift in metres. FlagPrevious.
    std::array<float, 3> back_turn;
    float cell_fine;
    std::array<float, 3> back_shift;
    std::uint32_t flags;
};
static_assert(sizeof(Params) == 128);

inline constexpr std::uint32_t FlagNormals = 1; ///< the G-buffer's world normals are bound
inline constexpr std::uint32_t FlagMotion = 2;  ///< this frame's object motion is bound
/// The camera of the frame before is known (back_turn, back_shift, the zoom): what the object
/// motion says of a pixel is compared with what the camera's own move does to it.
inline constexpr std::uint32_t FlagPrevious = 4;
inline constexpr std::uint32_t ViewShift = 8;   ///< the test view, three bits from here
/// 16 bits from here: the projection's scale of the frame before over this frame's (a zoom),
/// as (ratio - 1) * 32768 + 32768. 32768: the same lens.
inline constexpr std::uint32_t ZoomShift = 16;
/// The test view in a block's flags (a View).
constexpr std::uint32_t ViewOf(std::uint32_t flags) {
    return (flags >> ViewShift) & 7u;
}

/// graphics_drawn_look_debug (BB_DRAWN_LOOK_VIEW). 1, 2 and 4 paint every stroke in a flat
/// colour of its own: with the sizes the look mixes, all fine, all bold. 3 is kept for the ink
/// lines' view; until they are built it shows the look, as 0 does.
enum View : int { ViewOff = 0, ViewStrokes = 1, ViewFine = 2, ViewInk = 3, ViewBold = 4, ViewMax = 4 };

/// A stroke's cell on a screen of 2160 lines, in pixels, at stroke size 1.0 (a stroke is about
/// 2.4 cells long and one wide). The owner chose a mix: bold strokes on large plain surfaces,
/// fine ones where there is detail. Other resolutions keep the stroke's share of the picture.
inline constexpr float BoldCellAt2160 = 30.0f, FineCellAt2160 = 10.0f;

/// What the settings give a frame (BbSettings: the graphics_drawn_look_* keys).
struct Knobs {
    float strength = 0.6f;
    float stroke_size = 1.0f;
    float texture = 1.0f;
    float outlines = 0.35f; ///< the ink is not built: not among the passes' words
    float ink_world = 0.0f; ///< the same
    float characters = 0.5f;
    int view = ViewOff;
};

/// The camera a frame was drawn with, kept for the frame after it.
struct Previous {
    std::array<float, 12> view; ///< world to view, 3x4 rows
    std::array<float, 4> proj;  ///< x scale, y scale, z scale, z offset
};

/// (r45b_drawn-look-fixes) A draw of six indices or fewer into the scene colour is as small as a
/// full-screen pass. It is one of the game's transparents (a particle system of a few
/// particles: a card of fog, a few sparks) when it is blended, writes no depth and is tested
/// against the scene's depth; a full-screen pass over the scene is not blended, or does not
/// test the depth. The look paints before the first transparent draw of a frame.
/// `depth_always`: the depth test's function lets everything pass.
constexpr bool SmallTransparent(bool blend, bool blend_bypass, bool depth_write, bool depth_test,
                                bool depth_always) {
    return blend && !blend_bypass && !depth_write && depth_test && !depth_always;
}

/// The scene's `height` is the upscaler's input (render) height: its output has the same
/// picture on more pixels, so a stroke that is a set share of the render height is that share
/// of the screen whatever the upscaler mode.
/// `previous`: the camera of the frame before, or null when there was none (the first painted
/// frame, the frame after one that was not painted). Without it, and after a cut the words
/// cannot hold (a turn of more than 120 degrees, a lens more than twice or less than half as
/// long, a mirrored camera), FlagPrevious is not set.
inline Params Make(const Knobs& knobs, const std::array<float, 12>& inv_view,
                   const std::array<float, 4>& proj, std::uint32_t width, std::uint32_t height,
                   const std::array<float, 2>& jitter, bool normals, bool motion,
                   const Previous* previous = nullptr) {
    const float scale = float(height) / 2160.0f * knobs.stroke_size;
    Params params{
        .inv_view = inv_view,
        .proj = proj,
        .size = {float(width), float(height)},
        .jitter = jitter,
        .strength = knobs.strength,
        .brush = knobs.texture,
        .characters = knobs.characters,
        // Under two pixels a cell a stroke is no longer a shape.
        .cell_bold = std::max(BoldCellAt2160 * scale, 2.0f),
        .back_turn = {},
        .cell_fine = std::max(FineCellAt2160 * scale, 2.0f),
        .back_shift = {},
        .flags = (normals ? FlagNormals : 0u) | (motion ? FlagMotion : 0u) |
                 std::uint32_t(std::clamp(knobs.view, int(ViewOff), int(ViewMax))) << ViewShift |
                 32768u << ZoomShift,
    };
    if (!previous) {
        return params;
    }
    // previous view * this frame's inverse view: [turn | shift], 3x4 rows.
    double turn[3][3], shift[3];
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            turn[i][j] = 0.0;
            for (int k = 0; k < 3; ++k) {
                turn[i][j] += double(previous->view[i * 4 + k]) * double(inv_view[k * 4 + j]);
            }
        }
        shift[i] = double(previous->view[i * 4 + 3]);
        for (int k = 0; k < 3; ++k) {
            shift[i] += double(previous->view[i * 4 + k]) * double(inv_view[k * 4 + 3]);
        }
    }
    const double w = 0.5 * std::sqrt(std::max(1.0 + turn[0][0] + turn[1][1] + turn[2][2], 0.0));
    const double zoom_x = double(previous->proj[0]) / double(proj[0]);
    const double zoom = double(previous->proj[1]) / double(proj[1]);
    // (Written so that a number that is none fails every test.)
    if (!(w > 0.5) || !(zoom > 0.5 && zoom < 1.999) || !(std::abs(zoom_x - zoom) < 1e-3 * zoom)) {
        return params;
    }
    const double q[3] = {(turn[2][1] - turn[1][2]) / (4.0 * w), (turn[0][2] - turn[2][0]) / (4.0 * w),
                         (turn[1][0] - turn[0][1]) / (4.0 * w)};
    // A turn has a quaternion of length 1; a mirrored camera's "turn" has not.
    const double length2 = w * w + q[0] * q[0] + q[1] * q[1] + q[2] * q[2];
    if (!(std::abs(length2 - 1.0) < 1e-3) ||
        !(std::isfinite(shift[0]) && std::isfinite(shift[1]) && std::isfinite(shift[2]))) {
        return params;
    }
    params.back_turn = {float(q[0]), float(q[1]), float(q[2])};
    params.back_shift = {float(shift[0]), float(shift[1]), float(shift[2])};
    const auto zoom_bits = std::uint32_t(
        std::clamp(std::lround((zoom - 1.0) * 32768.0) + 32768l, 0l, 65535l));
    params.flags = (params.flags & ~(0xffffu << ZoomShift)) | zoom_bits << ZoomShift | FlagPrevious;
    return params;
}

} // namespace Vulkan::DrawnLookParams
