// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): what the wind shelter's shader (wind_shelter.comp), its reader
// (wind_shelter.glsl) and the engine (gpu/shim/bbport_wind_shelter.h, which ties these to its own
// constants with static_asserts) share. Plain #define lines only: the shaders include this file
// through GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds every number
// both sides use. Floats carry the f suffix (valid in GLSL 450 and in C++).
#ifndef WIND_SHELTER_LAYOUT_H
#define WIND_SHELTER_LAYOUT_H

// The field the vertex shaders, the fog and the particles read: a square of WS_N x WS_N cells of
// WS_CELL m, in the sway region's buffer (words, from its start) at WS_BLOCK_WORD: 8 header words
// then WS_N * WS_N floats, row after row (z), cell (i, j) = world x ox + (i + 0.5) WS_CELL, z oz +
// (j + 0.5) WS_CELL. Header words (floats): 0 the marker (1 once written, 0 before), 1 ox, 2 oz,
// 3 1 / WS_CELL, 4 WS_N, 5 the camera's y (the field's level), 6 the strength (BB_WIND_SHELTER),
// 7 the half band (m) of the level within which the field holds.
#define WS_BLOCK_WORD 4096u
#define WS_HEADER_WORDS 8u
#define WS_N 64u
#define WS_CELL 1.0f
#define WS_BAND 14.0f
#define WS_BAND_SOFT 4.0f

// The cache of what the depth showed (toroidal, WS_M x WS_M cells): per cell WS_CELL_WORDS words,
// then the frame's own min/max (WS_FRESH_WORDS words a cell) after all of them.
#define WS_M 128u
#define WS_CELL_WORDS 6u
#define WS_FRESH_WORDS 3u
// r117b: after the cache's cells and fresh words the state buffer has WS_GLOBAL_WORDS words: 0 the
// frame's count of climbing view rays, 1 of them covered (the splat pass adds, the final pass
// clears), 2 the camera's smoothed covered share (float), 3 the cover it maps to (float), 4 1 once
// the share was first taken. The cache's cell word 5 is the cell's cover (float).
#define WS_GLOBAL_WORDS 20u // r115c: 8 words were used; 8..17 are the roof rule's (below)
#define WS_STRIDE 4u
#define WS_MIN_SAMPLES 2u
#define WS_STEPS 28u

// Quantised heights: y -> round((y + WS_Y_BIAS) * WS_Y_SCALE) in 16 bits.
#define WS_Y_BIAS 1024.0f
#define WS_Y_SCALE 32.0f

// The model (see bbport_wind_shelter.h for what each number means).
#define WS_H_START 1.0f
#define WS_TAN_LO 0.12f
#define WS_TAN_HI 0.40f
#define WS_LIFT_LO 1.2f
#define WS_LIFT_HI 2.4f
// r117b: the overhead cover (no roof rule: a tall thing gives its own cell nothing). The camera's
// view rays that climb (tangent of the elevation above WS_COVER_TAN) and end on a surface within
// WS_COVER_DIST m are covered; their share, followed in time (WS_COVER_TAU s) and mapped by
// smoothstep(WS_COVER_LO, WS_COVER_HI), is the camera's cover; cells seen within WS_COVER_RADIUS
// cells of the camera move toward it by WS_COVER_RATE a frame, the cells within WS_COVER_NEAR
// cells take it outright; fewer than WS_COVER_MIN climbing samples a frame: no news.
#define WS_COVER_TAN 0.35f
#define WS_COVER_DIST 80.0f
#define WS_COVER_MIN 64u
#define WS_COVER_LO 0.80f
#define WS_COVER_HI 0.96f
#define WS_COVER_TAU 0.4f
#define WS_COVER_RADIUS 16.0f
#define WS_COVER_RATE 0.25f
#define WS_COVER_NEAR 2.5f
#define WS_RAY_DEG 14.0f
#define WS_GAIN 1.06f
#define WS_EDGE_CELLS 4.0f
#define WS_TAU 0.5f
#define WS_SNAP_FRAMES 20u
#define WS_NO_GROUND 1.7f
// r117c (open ground read sheltered, see r117c_shelter-outdoors.py): a climbing view ray is covered when it
// ends within WS_COVER_CLOSE m of the camera, or beyond that within WS_COVER_DIST m on a surface facing
// down (its normal, turned toward the camera, has y below -WS_DOWN_NY; the neighbour pixels used for it
// may differ in depth by at most WS_NORMAL_TOL of the distance). An obstacle counts for at most
// WS_EFF_MAX m above WS_H_START (a tree or a building shelters like a 3 m wall). An obstacle lower than
// WS_NEAR_TOP_LO..HI above its ground that stands within WS_NEAR_CAM_LO..HI m of the camera (the Hunter)
// counts for nothing: keep = max(smoothstep(TOP_LO, TOP_HI, height), smoothstep(CAM_LO, CAM_HI, distance)).
#define WS_COVER_CLOSE 35.0f
#define WS_DOWN_NY 0.5f
#define WS_NORMAL_TOL 0.08f
#define WS_EFF_MAX 2.0f
#define WS_NEAR_TOP_LO 2.0f
#define WS_NEAR_TOP_HI 2.6f
#define WS_NEAR_CAM_LO 4.0f
#define WS_NEAR_CAM_HI 7.0f
// r117d (thin and low things counted as walls, see r117d_shelter-thin.py): an obstacle a ray meets counts by
// smoothstep(WS_THIN_H_LO, WS_THIN_H_HI, its top above the ground) times smoothstep(WS_THIN_W_LO, WS_THIN_W_HI, w),
// w = 1 + the cells next to it across the ray (2 on each side): 1 for a known cell with a top at least
// WS_THIN_NB above the ground, WS_THIN_UNSEEN for a cell the cache knows nothing of, 0 for a known low one.
#define WS_THIN_H_LO 1.2f
#define WS_THIN_H_HI 2.0f
#define WS_THIN_W_LO 1.0f
#define WS_THIN_W_HI 3.0f
#define WS_THIN_NB 1.5f
#define WS_THIN_UNSEEN 0.15f
// r117e: a hit whose top is at least WS_TALL_H above the ground is "tall" in the log (a tree or a tall wall); a
// neighbour across the ray counts as wide only if it stands (its lowest height under WS_LIFT_LO above the ground).
#define WS_TALL_H 4.0f
// r117f: a hit that beats the ray's value counts by far_weight(dist, top above the ground): 1 up to WS_DIST_NEAR m,
// falling to WS_DIST_FLOOR at WS_DIST_FAR m, times smoothstep(WS_ELEV_LO, WS_ELEV_HI, tangent of the elevation of its
// top above WS_H_START over the ground, seen from the cell; 0.30 / 0.50 = 17 / 27 degrees).
#define WS_DIST_NEAR 1.0f
#define WS_DIST_FAR 8.0f
#define WS_DIST_FLOOR 0.2f
#define WS_ELEV_LO 0.30f
#define WS_ELEV_HI 0.50f
// r117g (see r117g_shelter-graveyard.py): the lee of a low thing is short: s = smoothstep(WS_SHORT_LO, WS_SHORT_HI, top above
// the ground); the distance weight reaches its floor (WS_DIST_FLOOR s) at WS_SHORT_REACH + (WS_DIST_FAR - WS_SHORT_REACH) s
// m. A cell that is itself tall (own top WS_SELF_H_LO..HI above its ground) takes from a hit that does not rise above its
// own top only WS_SELF_KEEP of the weight (the hit counts in full from WS_SELF_RISE m above the cell's top).
#define WS_SHORT_LO 2.0f
#define WS_SHORT_HI 3.0f
#define WS_SHORT_REACH 3.5f
#define WS_SELF_H_LO 2.0f
#define WS_SELF_H_HI 3.0f
#define WS_SELF_RISE 2.0f
#define WS_SELF_KEEP 0.4f

// The passes, by the push word `mode`.
#define WS_MODE_CLEAR 0u
#define WS_MODE_SPLAT 1u
#define WS_MODE_MERGE 2u
#define WS_MODE_RAW 3u
#define WS_MODE_FINAL 4u
#define WS_MODE_SHOW 5u
#define WS_GROUP 8u

// The counter words (32-bit totals except WS_C_CAMERA, a float's bits, overwritten each frame).
#define WS_COUNTER_WORDS 26u // r115c: 24, then WS_C_ROOF and WS_C_ROOF_ALL (below)
#define WS_C_PIXELS 0u         // depth samples read by the splat pass
#define WS_C_PIXELS_SHELTERED 1u // of them where last frame's field was above 0.5
#define WS_C_PIXELS_SUM 2u     // sum of last frame's field there, in thousandths
#define WS_C_PIXELS_INDOOR 3u  // of them above 0.95
#define WS_C_CELLS_SEEN 4u     // window cells with depth data (raw pass)
#define WS_C_CELLS_SHELTERED 5u // window cells whose new field is above 0.5 (final pass)
#define WS_C_CAMERA 6u         // last frame's field at the camera (float bits)
#define WS_C_CELLS_SUM 7u      // sum of the window's field, in thousandths
#define WS_C_MERGED 8u         // cache cells that took this frame's samples
#define WS_C_CELLS 9u          // window cells written (final pass)
#define WS_C_COVER 10u         // the camera's smoothed covered share (float bits, overwritten each frame)
#define WS_C_PIXELS_SUM_HI 11u // carry of WS_C_PIXELS_SUM: with it a 64-bit total (r117b)
#define WS_C_UP 12u            // climbing view rays (r117c)
#define WS_C_CLOSE 13u         // of them ending within WS_COVER_CLOSE m
#define WS_C_DOWN 14u          // of them ending beyond that on a surface facing down, within WS_COVER_DIST
#define WS_C_MID 15u           // of them ending on another surface within WS_COVER_DIST (the rest: sky or beyond)
#define WS_C_THIN_SEEN 16u     // obstacle cells a raw-pass ray met that would have raised its value (r117d)
#define WS_C_THIN_LOW 17u      // of them with a height weight below 0.5
#define WS_C_THIN_NARROW 18u   // of the rest with a width weight below 0.5
#define WS_C_THIN_KEPT 19u     // of the hits, those whose weight stays at 0.5 or more (r117e)
#define WS_C_THIN_TALL 20u     // of the kept ones, those with a top WS_TALL_H or more above the ground
#define WS_C_FAR_CUT 21u       // of the hits that beat the ray's value, those cut under 0.5 by distance/elevation (r117f)
#define WS_C_SELF_CUT 22u      // of the hits that counted 0.5 or more after distance/elevation, those the cell's own height cut under 0.5 (r117g)
#define WS_C_SELF_CELLS 23u    // seen window cells that are tall (own top WS_SELF_H_HI or more above their ground) (r117g)
// r115c (the roof rule of BB_VOLUMETRIC_ROOF, see r115c_roof-rule-not-trees.py): a climbing view ray is ROOF when it ends within
// WS_ROOF_DIST m on a solid surface (the depth pixels WS_ROOF_STEP px left, right, up and down end within WS_NORMAL_TOL of its
// distance). The roof share is the smallest share over the 4 world quadrants (by the signs of the ray's x and z) that have
// WS_ROOF_QMIN or more climbing samples in the frame; followed over WS_COVER_TAU, held without such a quadrant. Made only when
// the push word cells.w is not 0. State words WS_GLOBAL_WORDS: 8..11 climbing rays a quadrant, 12..15 roof rays a quadrant, 16 the
// smoothed roof share (float), 17 1 once it was first taken. Counters: WS_C_ROOF the smoothed roof share (float bits, each
// frame), WS_C_ROOF_ALL the share of all the frame's climbing rays that are roof (float bits).
#define WS_ROOF_DIST 16.0f
#define WS_ROOF_STEP 3
#define WS_ROOF_QMIN 32u
#define WS_C_ROOF 24u
#define WS_C_ROOF_ALL 25u

#endif
