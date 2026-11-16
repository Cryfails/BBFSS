// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97b_heat-haze-paths): what the heat haze's shader (heat_haze.comp) and the engine
// (renderer_vulkan/heat_haze.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef HEAT_HAZE_LAYOUT_H
#define HEAT_HAZE_LAYOUT_H

// The pass, by the push word atlas.z (BbHeatHaze::PassCopy, PassHaze).
#define HH_PASS_COPY 0
#define HH_PASS_HAZE 1
// The flags, by the push word atlas.w (BbHeatHaze::Flag*).
#define HH_FLAG_SHOW 1     // BB_HEAT_HAZE_SHOW=1 or 2: the column tinted
#define HH_FLAG_OUTLINE 2  // BB_HEAT_HAZE_SHOW=2: the column's rectangle framed (2 pixels)
#define HH_FLAG_NO_DEPTH 4 // BB_HEAT_HAZE_DEPTH=0 or BB_HEAT_HAZE_SHOW=2: no depth test
#define HH_FLAG_PROBE 8    // the frame's nearest column: its flame pixel's depth is kept
#define HH_FLAG_PROOF 16   // BB_HEAT_HAZE_PROOF=1 (r97d): every written pixel mixed 30% towards magenta
// The counter buffer's words (BbHeatHaze::Word*): totals since the pass was made, never cleared.
// Words 0 to 9 are counted per workgroup in shared memory and added once a workgroup.
#define HH_WORD_RECT 0u     // haze pass pixels inside a column's rectangle
#define HH_WORD_SHAPE 1u    // of them outside the column's shape (or too weak to move)
#define HH_WORD_NEAR 2u     // tested pixels nearer the camera than the flame (the depth test)
#define HH_WORD_SOURCE 3u   // tested pixels whose source pixel is nearer (the second depth test)
#define HH_WORD_WRITTEN 4u  // pixels written
#define HH_WORD_Z_BAD 5u    // tested pixels whose depth gives no view z in front of the camera
#define HH_WORD_Z_CLOSE 6u  // ... a view z under half the flame's
#define HH_WORD_Z_FRONT 7u  // ... from half the flame's up to the depth test's limit
#define HH_WORD_Z_BEHIND 8u // ... behind that limit (not the sky)
#define HH_WORD_Z_SKY 9u    // ... the sky (depth 1)
#define HH_COUNTED 10u
// The nearest column's flame pixel, last frame it was seen (float bits): its depth, the view z
// that depth gives, the depth test's limit (m), the depth the lamp's own view z would give, how
// many times they were written, and the lamp's view z (m).
#define HH_WORD_FLAME_DEPTH 10u
#define HH_WORD_FLAME_Z 11u
#define HH_WORD_FLAME_FRONT 12u
#define HH_WORD_FLAME_EXPECT 13u
#define HH_WORD_FLAME_SEEN 14u
#define HH_WORD_FLAME_LAMP_Z 15u
// (r97d) the offset of every written pixel, in render pixels: 8 bins (upper edges 0.25, 0.5, 1, 2, 4,
// 8, 16 px, then more), their sum in 1/16 px, and the largest in 1/16 px (a running maximum).
// Words 16 to 24 are counted per workgroup in shared memory like words 0 to 9.
#define HH_WORD_OFF_BIN0 16u
#define HH_OFF_BINS 8u
#define HH_WORD_OFF_SUM 24u
#define HH_WORD_OFF_MAX 25u
#define HH_SHARED 25u // the shared counters: words 0 to 24 (10 to 15 stay zero there)
#define HH_WORDS 26u

#endif
