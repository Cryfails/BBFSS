// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97f_haze-per-flame): what the heat haze's flame finder (heat_haze_find.comp) and the
// engine (renderer_vulkan/heat_haze_flames.h, which ties these to its constants with static_asserts)
// share. Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive
// and C++ includes it as it is, so one text holds every number both sides use.
#ifndef HEAT_HAZE_FIND_LAYOUT_H
#define HEAT_HAZE_FIND_LAYOUT_H

// One workgroup (16 x 16 invocations) scans one lamp's surroundings: HF_GRID x HF_GRID cells over a
// square of the view plane at the lamp's depth, 2 x the half side wide (the push constants give it).
#define HF_GRID 32u       // cells a side
#define HF_SUPPRESS 4     // a peak clears the cells within this many cells of it (chebyshev)
#define HF_PEAKS 3u       // flames found around one lamp, at most
#define HF_SLOTS 8u       // lamps scanned a frame, at most (one block each)
#define HF_BLOCK_WORDS 16u
// A block (one lamp, one frame), in words. Floats are given by their bits (floatBitsToUint).
#define HF_WORD_ID 0u     // the table entry's id the push constants gave (echoed)
#define HF_WORD_TAG 1u    // the frame's tag (echoed): a block is new when its tag is
#define HF_WORD_COUNT 2u  // flames found, 0 to HF_PEAKS
#define HF_WORD_BEST 3u   // float: the strongest blob (HDR luma above its surround), 0 when none
#define HF_WORD_PEAK0 4u  // peak k at HF_WORD_PEAK0 + k * HF_PEAK_WORDS: x, y (float, metres in the
#define HF_PEAK_WORDS 3u  // view plane from the lamp, +y up the view's own y) and its blob (float)
#define HF_WORD_BRIGHT 13u // float: the brightest cell's mean luma
#define HF_WORD_CELLS 14u  // cells inside the scene
#define HF_WORD_CHECK 15u  // a fold of words 0 to 14 (the engine reads these words while the GPU
                           // may still be copying them: a block that does not check is skipped)
#define HF_WORDS_TOTAL 128u // HF_SLOTS * HF_BLOCK_WORDS

#endif
