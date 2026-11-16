// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86b_glass-visible): the glass glint's numbers, shared by host_shaders/glass_glint.comp
// (its COARSE and SHADE builds) and renderer_vulkan/glass_glint.h (which ties them to its C++
// names with static_asserts and the test). Plain #define lines only: GLSL and C++ both read this
// file.
#ifndef GLASS_GLINT_LAYOUT_H
#define GLASS_GLINT_LAYOUT_H

// One workgroup: 8x8 threads. COARSE: a thread a block of GLASS_GLINT_BLOCK x GLASS_GLINT_BLOCK
// pixels; SHADE: a thread a pixel (or a 2x2 quad, see GLASS_GLINT_QUAD_PERCENT).
#define GLASS_GLINT_GROUP 8
#define GLASS_GLINT_BLOCK 4

// Push word info.w.
#define GLASS_GLINT_FLAG_SHOW 1u // the test view (BB_GLASS_GLINT=show)

// The shadow ray to a lamp traces the lamps' instance mask (RtShadow's LampMask, tied there by a
// static_assert); the panes are under RT_GLASS_MASK alone, so a pane never shadows its own glint.
#define GLASS_GLINT_LAMP_MASK 0x04u

// The counters buffer: GLASS_GLINT_SLOTS slots of GLASS_GLINT_SLOT_WORDS counter words (one slot a
// pass, in turn), then GLASS_GLINT_SLOTS data blocks of GLASS_GLINT_DATA_WORDS words (the same
// slot's): word GLASS_GLINT_DATA_COUNT the lamp count, from GLASS_GLINT_DATA_LAMPS
// GLASS_GLINT_LAMP_WORDS words a lamp: view x, y, z, reach (m), colour r, g, b, 0.
#define GLASS_GLINT_SLOTS 16u
#define GLASS_GLINT_SLOT_WORDS 24u
#define GLASS_GLINT_MAX_LAMPS 8u
#define GLASS_GLINT_LAMP_WORDS 8u
#define GLASS_GLINT_DATA_COUNT 0u
#define GLASS_GLINT_DATA_LAMPS 8u
#define GLASS_GLINT_DATA_WORDS 84u
// bbport (r86e_glint-hit-distance): the data block's words 1 to 6 hold the pane draw the pass follows
// (vertex shader hash low, high, pixel shader hash low, high, index count, instances) and words 72 to
// 83 the pass's camera (world to view, 3x4, row by row), both for the log (host-written).
#define GLASS_GLINT_DATA_DRAW 1u
#define GLASS_GLINT_DATA_VIEW 72u
// After the data blocks, a raw-value area of GLASS_GLINT_DBG_WORDS words a slot (the GPU clears it
// with the slot's counters): word 0 the pane samples taken (atomic; at most DBG_PANE_MAX are
// written), then from GLASS_GLINT_DBG_FIRST records of GLASS_GLINT_DBG_RECORD words: DBG_PANE_MAX
// pane-pixel records, then DBG_GRID_MAX records of fixed blocks (4 across, 3 down). A record: 0 kind
// (0 empty, 1 pane pixel, 2 grid block), 1 pixel x | y << 16, 2 raw depth, 3 the depth's distance
// (m; the sky 1000), 4 to 6 the point the depth gives (view space), 7 the pane's t (m; -1 none; a
// grid block's is the nearest pane on its ray at any distance), 8 to 10 that point, 11 to 13 the
// nearest lamp (view space), 14 its distance to the pane point (to the depth's point when there is
// no pane; -1: no lamps), 15 its reach (m).
#define GLASS_GLINT_DBG_PANE_MAX 8u
#define GLASS_GLINT_DBG_GRID_MAX 12u
#define GLASS_GLINT_DBG_RECORD 16u
#define GLASS_GLINT_DBG_FIRST 4u
#define GLASS_GLINT_DBG_WORDS 324u

// Counter words of a slot. COARSE: 0 blocks traced, 1 blocks whose centre ray meets a pane in
// front of the depth (within GLASS_GLINT_TOL_*), 2 blocks whose ray meets a pane only behind it
// (the test view only). SHADE: 3 pixels on a pane in front of the depth, 4 pixels whose ray meets
// a pane only behind the depth (the test view only), 5 pixels whose glint's largest channel is
// above GLASS_GLINT_GLINT_LEVEL, 6 shadow rays, 7 of them that met something, 8 the largest added
// channel (float bits; atomicMax of non-negative floats), 9 workgroups that ran, 10 of them in the
// quad mode, 11 pane points without a normal (no neighbour on the same surface).
#define GLASS_GLINT_W_BLOCKS 0u
#define GLASS_GLINT_W_FLAGGED 1u
#define GLASS_GLINT_W_BEHIND 2u
#define GLASS_GLINT_W_GLASS 3u
#define GLASS_GLINT_W_REJECTED 4u
#define GLASS_GLINT_W_GLINT 5u
#define GLASS_GLINT_W_SHADOW_RAYS 6u
#define GLASS_GLINT_W_SHADOWED 7u
#define GLASS_GLINT_W_MAX_ADD 8u
#define GLASS_GLINT_W_TILES 9u
#define GLASS_GLINT_W_QUAD_TILES 10u
#define GLASS_GLINT_W_NO_NORMAL 11u
// bbport (r86c_glass-glint-visible): the numbers behind the log's second line, a slot's words 12 on.
// Summed, a unit being a pixel or a 2x2 quad: 12 pane points (units) in front of the depth, 13 pane
// point x lamp pairs inside the lamp's reach, 14 of them facing the lamp (N.L above 0), 15 the sum of
// those pairs' distances (cm). The largest (atomicMax): 16 the nearest pair as 0xFFFFFFFF less its
// distance in mm (0: no pair), 17 the brightest lamp term before the strength and the shadow test
// (float bits), 18 the highest N.H of a facing pair (float bits). Summed: 19 pane points whose normal
// from the two units before the centre differs by more than 2.6 degrees from the normal from the two
// after it (curved), 20 the sum of the pane points' distances t (cm, each put into 100 m).
#define GLASS_GLINT_W_UNITS 12u
#define GLASS_GLINT_W_PAIRS 13u
#define GLASS_GLINT_W_FACING 14u
#define GLASS_GLINT_W_DIST_SUM 15u
#define GLASS_GLINT_W_DIST_MIN 16u
#define GLASS_GLINT_W_BEST_MAX 17u
#define GLASS_GLINT_W_NH_MAX 18u
#define GLASS_GLINT_W_CURVED 19u
#define GLASS_GLINT_W_T_SUM 20u
// bbport (r86d_glint-pane-depth): summed: 21 the pane points' own distance (whole metres, each put
// into GLASS_GLINT_FAR), 22 pane points whose depth is the sky, 23 pane points nearer than 50 m.
#define GLASS_GLINT_W_FAR_SUM 21u
#define GLASS_GLINT_W_SKY 22u
#define GLASS_GLINT_W_NEAR 23u
#define GLASS_GLINT_W_COUNT 24u

// A pane is in front of the depth when its distance t along the camera ray is at most the depth's
// distance d + GLASS_GLINT_TOL_ABS (m) + GLASS_GLINT_TOL_REL x d (a pane that writes its depth
// lies on it). The sky (depth 1) is GLASS_GLINT_FAR away.
#define GLASS_GLINT_TOL_ABS 0.02
#define GLASS_GLINT_TOL_REL 0.002
#define GLASS_GLINT_FAR 1000.0
// bbport (r86e_glint-hit-distance): a pane is only taken up to this distance (m) on a camera ray:
// the dream house's pair draws one 29892-triangle mesh a frame that lies 900 m and more away (a
// dome: every ray below the horizon met it), which is not glass; a lamp reaches 8.5 m at most.
#define GLASS_GLINT_PANE_MAX 50.0
// The normal: central differences of the pane points of the neighbours one unit (a pixel, or a
// quad) to each side; a neighbour counts when its t differs from the centre's by at most
// GLASS_GLINT_NEAR_ABS (m) + GLASS_GLINT_NEAR_REL x t (else one side; neither: no normal).
#define GLASS_GLINT_NEAR_ABS 0.03
#define GLASS_GLINT_NEAR_REL 0.01
// Shading: Blinn-Phong with (n + 8) / 8 (the game's lamp units: its lamp light is colour x falloff
// x N.L with no 1/pi, so the BRDF's 1/pi is left out too), Schlick from GLASS_GLINT_F0, each channel
// of the sum put into 0 to GLASS_GLINT_ADD_MAX. One shadow ray, to the lamp with the largest term,
// when that term x strength is above GLASS_GLINT_SHADOW_LEVEL: from GLASS_GLINT_SHADOW_TMIN (m) to the
// lamp's distance less GLASS_GLINT_LAMP_STOP (m).
#define GLASS_GLINT_F0 0.04
// bbport (r86c_glass-glint-visible): the look gain on a lamp's term. The Blinn-Phong lobe spreads the
// lamp's irradiance (the game's units); the lamp's image in glass is its radiance, a thousand times
// that over pi, so the lobe's top is about the scene's own level (log-mean key 0.05) and a glint that
// small does not show. At 32 the torch of the dream house (3.77 m, colour 2.49, reach 8.5 m) gives
// 0.86 at the top of the lobe.
#define GLASS_GLINT_GAIN 8.0
#define GLASS_GLINT_ADD_MAX 8.0
#define GLASS_GLINT_SHADOW_LEVEL (1.0 / 255.0)
#define GLASS_GLINT_SHADOW_TMIN 0.03
#define GLASS_GLINT_LAMP_STOP 0.1
#define GLASS_GLINT_GLINT_LEVEL 0.02
// More than this percentage of the blocks on a pane: SHADE traces one ray a 2x2 quad (the cost
// cap of a screen full of glass); each pixel of a quad still takes its own depth test.
#define GLASS_GLINT_QUAD_PERCENT 10u

#endif
