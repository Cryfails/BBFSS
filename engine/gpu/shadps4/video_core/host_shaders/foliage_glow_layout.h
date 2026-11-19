// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): what the back-lit glow pass (foliage_glow.comp) and the engine (renderer_vulkan/vk_foliage_glow.cpp,
// foliage_translucency.h, which ties these to its constants with static_asserts) share. Plain #define lines only: the shader includes this
// file through GL_GOOGLE_include_directive and C++ includes it as it is.
#ifndef FOLIAGE_GLOW_LAYOUT_H
#define FOLIAGE_GLOW_LAYOUT_H

// 8x8 threads a group, one a pixel of the scene.
#define FG_GROUP 8
// The lamps of the last G-buffer pass the pass reads (the nearest to the camera when there are more).
#define FG_MAX_LAMPS 32
// The data blocks the host writes, one a dispatch in turn (the GPU reads a block some frames after the host wrote it).
#define FG_SLOTS 16
// The buffer holds FG_COUNTER_WORDS counters (cumulative, u32), then FG_SLOTS blocks of FG_DATA_WORDS words:
//  words 0-2 the direction toward the sun or moon in view space, 3 the sun's diffuse scale k, 4-6 the sun's colour, 7 the lamp count,
//  then FG_MAX_LAMPS records of 8 words: view position x y z, inverse radius squared, colour r g b, 0 (as the game's light grid has them).
#define FG_COUNTER_WORDS 8
#define FG_DATA_WORDS 264
#define FG_DATA_SUN 0
#define FG_DATA_SUN_K 3
#define FG_DATA_SUN_COLOUR 4
#define FG_DATA_LAMP_COUNT 7
#define FG_DATA_LAMPS 8
// The counters: non-sky pixels, pixels the camera ray found a kept leaf texel at, back-lit pixels (a light behind the leaf was traced),
// lamp rays, sun rays, the sum of the luma added x 1000, pixels the sun's hue term reached, short camera rays cast.
#define FG_C_PIXELS 0
#define FG_C_FOLIAGE 1
#define FG_C_BACKLIT 2
#define FG_C_LAMP_RAYS 3
#define FG_C_SUN_RAYS 4
#define FG_C_ADDED 5
#define FG_C_HUE 6
#define FG_C_ID_RAYS 7
// The flags of the push constants: the glow itself, the sun's data are valid, the visibility rays tint (light through leaves is on),
// the sun's hue image is bound and the size of the scene, the test view (the term x8 over a dim scene).
#define FG_FLAG_GLOW 1u
#define FG_FLAG_SUN 2u
#define FG_FLAG_TRANSMIT 4u
#define FG_FLAG_HUE 8u
#define FG_FLAG_VIEW 16u
#define FG_FLAG_MASK_DIAG 32u
#define FG_FLAG_MASK_VIEW 64u
// The push constants (see foliage_glow.comp).
#define FG_PUSH_BYTES 112
// The strongest lamps and the sun are traced: at most this many lamp rays a pixel.
#define FG_PIXEL_LAMPS 2
// The back-lit visibility ray starts this far (m) on the light's side of the leaf, and is blind to the first FG_RAY_TMIN of its way.
#define FG_RAY_START 0.03
#define FG_RAY_TMIN 0.01
// The reference of an "above the reference" rule for these rays (the sun rays' CARD_SUN_REF).
#define FG_REF_SCALE 0.6

#endif
