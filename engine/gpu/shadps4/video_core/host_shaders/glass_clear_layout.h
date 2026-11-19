// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131c_cabinet-glass-clear): what the glass clear's shader (glass_clear.comp) and the engine
// (renderer_vulkan/vk_glass_clear.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text holds every number both sides use.
#ifndef GLASS_CLEAR_LAYOUT_H
#define GLASS_CLEAR_LAYOUT_H

// Pixels a side of one workgroup.
#define GLASS_CLEAR_GROUP 8u
// The counters buffer: visible pane pixels, of them holes (nothing drawn behind the pane). Cumulative.
#define GLASS_CLEAR_W_VISIBLE 0u
#define GLASS_CLEAR_W_HOLE 1u
#define GLASS_CLEAR_WORDS 4u
// The push word `flags`: the depth func is of the greater kind (reverse z: far is 0).
#define GLASS_CLEAR_FLAG_REVERSE 1u
// The film's albedo is clamped to this luminance, then lit by the scene's own luminance times the gain.
#define GLASS_CLEAR_FILM_LUMA 0.5
#define GLASS_CLEAR_LIT_GAIN 1.2
// A pane pixel with nothing drawn behind it (a hole) is painted with this much film (frosted, not a hole to the void).
#define GLASS_CLEAR_HOLE_ALPHA 0.6
// The sheen's tap distance in pixels at 1080 lines of height.
#define GLASS_CLEAR_SHEEN_PIXELS 12.0

#endif
