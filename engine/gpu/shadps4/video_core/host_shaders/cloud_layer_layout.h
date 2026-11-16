// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): what the cloud layer's shader (cloud_layer.comp) and the engine
// (renderer_vulkan/cloud_layer_params.h, which ties these to its constants with static_asserts)
// share. Plain #define lines only: the shader includes this file through
// GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds every number both
// sides use.
#ifndef CLOUD_LAYER_LAYOUT_H
#define CLOUD_LAYER_LAYOUT_H

// The march's image is 1 / CL_DIV of the scene along each axis (CL_DIV x CL_DIV scene pixels a
// pixel of it); the composite upsamples it with a depth (sky) aware bilinear filter.
#define CL_DIV 2
// The workgroup's side, both passes.
#define CL_WG 8
// The push word `flags` (CloudLayerParams::Flag*).
#define CL_FLAG_SHOW 1 // BB_VOLUMETRIC_CLOUDS_SHOW=1: the opacity painted in a test colour
// The counter buffer's words (CloudLayerParams::Word*): this frame's totals, cleared before each
// frame's march and copied to the host after the composite. Counted per workgroup in shared
// memory and added once a workgroup.
#define CL_WORD_TOTAL 0u   // march pixels (1 / CL_DIV of the scene a side)
#define CL_WORD_SKY 1u     // of them with at least one sky pixel under them (marched or not)
#define CL_WORD_HIT 2u     // sky pixels whose ray meets the slab and is not faded out
#define CL_WORD_COVERED 3u // sky pixels with an opacity of 1/64 or more
#define CL_WORD_OPACITY 4u // the sum of round(opacity x 256) over the sky pixels
#define CL_WORD_STEPS 5u   // march steps taken
// The depth probe (r119b): the first pixel of each march block, sky or not, by its depth: word Z_SKY depth 1,
// then the view z (m) at or over EDGE0 .. EDGE4 (one band a word, Z_SKY + 1 .. Z_SKY + 5), Z_LAST the rest.
#define CL_WORD_Z_SKY 6u
#define CL_WORD_Z_LAST 12u
#define CL_Z_EDGE0 1500.0
#define CL_Z_EDGE1 1000.0
#define CL_Z_EDGE2 500.0
#define CL_Z_EDGE3 250.0
#define CL_Z_EDGE4 100.0
// bbport (r119c_clouds-gaps): the sky pixels with an opacity of CL_VISIBLE_ALPHA or more (a cloud that shows)
#define CL_WORD_VISIBLE 13u
#define CL_VISIBLE_ALPHA 0.25
// bbport (r119d_clouds-contrast): of the visible sky pixels (opacity CL_VISIBLE_ALPHA or more) those whose picture is
// darker than CL_DARK_RATIO or brighter than CL_BRIGHT_RATIO of the sky behind them (the contrast proof)
#define CL_WORD_DARK 14u
#define CL_WORD_BRIGHT 15u
#define CL_DARK_RATIO 0.7
#define CL_BRIGHT_RATIO 1.4
// bbport (r119i_clouds-behind-painted-sky): the marched sky blocks of which the painted sky took CL_PAINTED_SHARE or more of the opacity
#define CL_WORD_PAINTED 16u
#define CL_PAINTED_SHARE 0.25
#define CL_WORDS 17u

#endif
