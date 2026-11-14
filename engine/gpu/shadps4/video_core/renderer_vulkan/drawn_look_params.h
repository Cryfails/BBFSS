// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r45_drawn-look): the words the drawn look's passes take (host_shaders/paint_common.glsl,
// the Constants block), and how the settings and the frame's camera become them. No Vulkan here:
// tests/test_drawn_look.cpp runs the passes with the same words.

#include <algorithm>
#include <array>
#include <cstdint>

namespace Vulkan::DrawnLookParams {

/// The push constants of the drawn look's passes (host_shaders/paint_*.comp).
struct Params {
    std::array<float, 12> inv_view; ///< view to world, 3x4 rows
    std::array<float, 4> proj;      ///< x scale, y scale, z scale, z offset
    std::array<float, 2> size;      ///< the scene in pixels
    std::array<float, 2> jitter;    ///< the frame's viewport shift in pixels
    float strength;
    float brush;
    float outlines;
    float ink_world;
    float characters;
    float cell_bold;
    float cell_fine;
    std::uint32_t flags;
};
static_assert(sizeof(Params) == 112);

inline constexpr std::uint32_t FlagNormals = 1; ///< the G-buffer's world normals are bound
inline constexpr std::uint32_t FlagMotion = 2;  ///< this frame's object motion is bound
inline constexpr std::uint32_t ViewShift = 8;   ///< the test view, three bits from here

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
    float outlines = 0.35f;
    float ink_world = 0.0f;
    float characters = 0.5f;
    int view = ViewOff;
};

/// The scene's `height` is the upscaler's input (render) height: its output has the same
/// picture on more pixels, so a stroke that is a set share of the render height is that share
/// of the screen whatever the upscaler mode.
inline Params Make(const Knobs& knobs, const std::array<float, 12>& inv_view,
                   const std::array<float, 4>& proj, std::uint32_t width, std::uint32_t height,
                   const std::array<float, 2>& jitter, bool normals, bool motion) {
    const float scale = float(height) / 2160.0f * knobs.stroke_size;
    return {
        .inv_view = inv_view,
        .proj = proj,
        .size = {float(width), float(height)},
        .jitter = jitter,
        .strength = knobs.strength,
        .brush = knobs.texture,
        .outlines = knobs.outlines,
        .ink_world = knobs.ink_world,
        .characters = knobs.characters,
        // Under two pixels a cell a stroke is no longer a shape.
        .cell_bold = std::max(BoldCellAt2160 * scale, 2.0f),
        .cell_fine = std::max(FineCellAt2160 * scale, 2.0f),
        .flags = (normals ? FlagNormals : 0u) | (motion ? FlagMotion : 0u) |
                 std::uint32_t(std::clamp(knobs.view, int(ViewOff), int(ViewMax))) << ViewShift,
    };
}

} // namespace Vulkan::DrawnLookParams
