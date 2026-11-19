// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r107_caustics): the water caustics' numbers, shared by host_shaders/caustics.comp and
// renderer_vulkan/caustics_params.h (which ties them to its C++ names with static_asserts and
// the test). Plain #define lines only: GLSL and C++ both read this file.
#ifndef CAUSTICS_LAYOUT_H
#define CAUSTICS_LAYOUT_H

// One workgroup: 8x8 pixels.
#define CAUSTICS_GROUP 8

// Push word `flags`.
#define CAUSTICS_FLAG_SHOW 1u     // the test view (BB_CAUSTICS=show)
#define CAUSTICS_FLAG_PLANE 2u    // a water plane, a sun or moon above the horizon and the
                                  // screen shadow target: the caustics are drawn
#define CAUSTICS_FLAG_MATERIAL 4u // the G-buffer's material target (gloss in .r) is bound
// bbport (r107b_caustics-visible): the lamps' caustics are drawn (BB_CAUSTICS_LAMPS; the lamps in
// the slot's data block), the light sets' sun mask is in the data block and the G-buffer's
// specular target (its alpha byte: each pixel's light set) is bound, the albedo target is bound.
#define CAUSTICS_FLAG_LAMPS 8u
#define CAUSTICS_FLAG_RECORDS 16u
#define CAUSTICS_FLAG_ALBEDO 32u
// bbport (r107e_caustics-puddles): puddles stand in for the water plane (count the candidates;
// lamps cross water only on a candidate); the puddle plane is in sun.w (count the pixels on it).
#define CAUSTICS_FLAG_PUDDLE 64u
#define CAUSTICS_FLAG_PUDDLE_PLANE 128u
// bbport (r107f_caustics-world-anchored): BB_CAUSTICS_WORLD (with BB_CAUSTICS_LAMPS, a plane or a
// puddle plane): the world map (binding 7) is read and written, the water gets the light of the lamps
// seen through it (a mirrored plane) or their ripple (puddles).
#define CAUSTICS_FLAG_WORLD 256u
// bbport (r130b_water-moves): BB_WATER_MOTION / graphics_water_motion_strength: the slot's motion block (CAUSTICS_MOTION_* below) is
// written and WaveAt bends and focuses every pattern lookup and shimmers the water pixels. Without the flag none of it runs.
#define CAUSTICS_FLAG_MOTION 512u
// bbport (r130e_sewer-water-moves): two more dispatches of this pass inside one Apply (the rippled reflection of a mirrored plane's
// water), both with CAUSTICS_FLAG_MOTION: WARP_COPY copies each water pixel's colour of the band into the copy image (binding 8),
// WARP takes it from a place moved along the wave field's slope and gives it a glint. Without these flags none of it runs.
#define CAUSTICS_FLAG_WARP_COPY 1024u
#define CAUSTICS_FLAG_WARP 2048u
#define CAUSTICS_FLAG_AMBIENT 4096u // indoor reflection warp with current-band water donors
#define CAUSTICS_FLAG_WETNESS_PROBE 8192u // t133f, dedicated binding 4 slice
#define CAUSTICS_FLAG_NATIVE_BED 16384u // registered native bed and CB2, binding 9 and 5
#define CAUSTICS_FLAG_BED_IN_WARP 32768u // Shade leaves bed light for the destination in WARP
#define CAUSTICS_FLAG_BED_2X 65536u // binding 9 at 2x the scene extent

#define CAUSTICS_PROBE_MAGIC 0x74313366u
#define CAUSTICS_PROBE_VERSION 1u
#define CAUSTICS_PROBE_POINTS 4u
#define CAUSTICS_PROBE_HEADER_WORDS 16u
#define CAUSTICS_PROBE_POINT_WORDS 16u
#define CAUSTICS_PROBE_INVALID_FLOAT 0x7fc00000u
#define CAUSTICS_PROBE_INVALID_PIXEL 0xffffffffu
#define CAUSTICS_PROBE_UNKNOWN 0u
#define CAUSTICS_PROBE_REJECTED 1u
#define CAUSTICS_PROBE_WATER 2u
#define CAUSTICS_PROBE_OK 0u
#define CAUSTICS_PROBE_PROJECTION 1u
#define CAUSTICS_PROBE_OFFSCREEN 2u
#define CAUSTICS_PROBE_BORDER 3u
#define CAUSTICS_PROBE_COARSE 4u
#define CAUSTICS_PROBE_DEPTH 5u
#define CAUSTICS_PROBE_SKY 6u
#define CAUSTICS_PROBE_OCCLUDED 7u
#define CAUSTICS_PROBE_NO_SURFACE 8u
#define CAUSTICS_PROBE_NEIGHBOUR 9u
#define CAUSTICS_PROBE_NORMAL 10u
#define CAUSTICS_PROBE_PREDICATE 11u

// The counters: CAUSTICS_SLOTS slots of CAUSTICS_SLOT_WORDS words, one slot a dispatch, in turn.
// Words: 0 pixels in the band above the water that face the reflected light, 1 of them whose
// water point is water on the screen, 2 of them whose water point the sun shadow says is lit
// (drawn), 3 puddle candidates painted by the test view.
// bbport (r107b_caustics-visible): 4 of word 1 whose water point's light set has no sun, 5-7
// those of word 0 whose water point is not water: off the screen or at the sky (5), hidden behind
// something nearer (6), a surface above the plane there (7, dry ground); 8-9 those of word 1 whose
// depth lies on the plane (8: the water is in the depth) or below it (9: the ground under the
// water is); 10 pixels a lamp's reflected light reaches facing it, 11 of them lit by lamp
// caustics, 12 lamp paths whose water crossing is not water, 13 the lamp light added over the
// pixel's own (luminance ratio, clamped to 4, x 256), summed over word 11.
// bbport (r107c_caustics-lamp-gain): 12 only the crossings on dry ground; 14 those off the screen or
// hidden; 13 clamped to CAUSTICS_RATIO_MAX, x CAUSTICS_RATIO_SCALE, rounded; 15 the lamps' own
// direct light there (the pass's model of it: albedo x colour x curve x facing, no shadow) over
// the pixel's own, clamped to CAUSTICS_MODEL_MAX, x CAUSTICS_MODEL_SCALE, rounded, summed over
// word 11. At most 1024 a pixel each: 4 million lit pixels a dispatch fit in a word.
// bbport (r107d_caustics-lamp-look): CAUSTICS_BINS bins of the lamps' own direct light as modelled
// (luminance, albedo included; bin 0 below 2^-10, then 2 stops a bin, the last 1 and above), over
// every pixel in the band the modelled light reaches: from CAUSTICS_W_BIN_COUNT their counts, from
// CAUSTICS_W_BIN_RATIO that light over the pixel's own as word 15 sums it (the log's check of the
// model's units: near 1 where the lamps light a pixel); CAUSTICS_W_LOOK pixels the look changed.
// bbport (r107e_caustics-puddles): CAUSTICS_W_PUDDLE_GROUND the pixels facing up on the puddle
// plane given, CAUSTICS_W_PUDDLE_WET the candidates among them; from CAUSTICS_W_HEIGHTS
// CAUSTICS_HEIGHT_BINS counts of the candidates by height: bin i holds those whose world y lies
// from the camera's y - CAUSTICS_HEIGHT_RANGE + i x CAUSTICS_HEIGHT_STEP up by CAUSTICS_HEIGHT_STEP
// (from 5.12 m below the camera to the camera). Words 33-38 are r107f's (below), 39 is free.
#define CAUSTICS_SLOT_WORDS 168
#define CAUSTICS_SLOTS 8
#define CAUSTICS_W_NO_SUN_SET 4
#define CAUSTICS_W_OFF 5
#define CAUSTICS_W_HIDDEN 6
#define CAUSTICS_W_DRY 7
#define CAUSTICS_W_ON_PLANE 8
#define CAUSTICS_W_BELOW 9
#define CAUSTICS_W_LAMP_TRIED 10
#define CAUSTICS_W_LAMP_LIT 11
#define CAUSTICS_W_LAMP_DRY 12
#define CAUSTICS_W_LAMP_RATIO 13
#define CAUSTICS_W_LAMP_UNSEEN 14
#define CAUSTICS_W_LAMP_MODEL 15
#define CAUSTICS_RATIO_SCALE 512.0
#define CAUSTICS_RATIO_MAX 2.0
#define CAUSTICS_MODEL_SCALE 128.0
#define CAUSTICS_MODEL_MAX 8.0
#define CAUSTICS_BINS 7
#define CAUSTICS_W_BIN_COUNT 16
#define CAUSTICS_W_BIN_RATIO 23
#define CAUSTICS_W_LOOK 30
#define CAUSTICS_W_PUDDLE_GROUND 31
#define CAUSTICS_W_PUDDLE_WET 32
// bbport (r107f_caustics-world-anchored): 33 water pixels given the light of the lamps seen through
// the water (a mirrored plane), 34 and 35 cells written to the world map as water and as dry, 36 and
// 37 lamp crossings the screen cannot see (off it, hidden) taken from the map as water and as dry, 38
// puddle pixels the ripple moved.
#define CAUSTICS_W_BED 33
#define CAUSTICS_W_MAP_WATER 34
#define CAUSTICS_W_MAP_DRY 35
#define CAUSTICS_W_MAP_RESCUED_WATER 36
#define CAUSTICS_W_MAP_RESCUED_DRY 37
#define CAUSTICS_W_BED_PUDDLE 38
// bbport (r130b_water-moves): 39 water pixels the shimmer changed (the free word).
#define CAUSTICS_W_MOTION_WATER 39
#define CAUSTICS_W_HEIGHTS 40
#define CAUSTICS_HEIGHT_BINS 128
#define CAUSTICS_HEIGHT_STEP 0.04
#define CAUSTICS_HEIGHT_RANGE 5.12

// bbport (r107b_caustics-visible): after the counters, CAUSTICS_SLOTS data blocks of
// CAUSTICS_DATA_WORDS words the host writes before each dispatch (the slot's): words 0-7 the
// light sets' sun mask (bit i: light set i has sun), CAUSTICS_DATA_COUNT the lamps, then
// CAUSTICS_DATA_GAIN the lamps' gain (float), and from CAUSTICS_DATA_LAMPS CAUSTICS_MAX_LAMPS
// lamps of CAUSTICS_LAMP_WORDS words: world x, y, z, reach (m), colour r, g, b, 0.
// bbport (r107c_caustics-lamp-gain): CAUSTICS_DATA_CORE2 and CAUSTICS_DATA_ENERGY the game's lamp
// curve (floats): core squared and energy of the inverse-square curve the game's lamp shaders are
// patched to (startup_local_inverse_square), or -1 and 1 for its own (1 - d / reach)^2.
#define CAUSTICS_DATA_WORDS 48
#define CAUSTICS_DATA_COUNT 8
#define CAUSTICS_DATA_GAIN 9
#define CAUSTICS_DATA_CORE2 10
#define CAUSTICS_DATA_ENERGY 11
// bbport (r107d_caustics-lamp-look): the look's amount (float; 0: off).
#define CAUSTICS_DATA_LOOK 12
// bbport (r107f_caustics-world-anchored): the map's generation (uint: a cell counts only when it
// holds this one; 0 without the map) and the bed's strength (float: BB_CAUSTICS_WORLD).
#define CAUSTICS_DATA_WORLD_GEN 13
#define CAUSTICS_DATA_BED 14
#define CAUSTICS_DATA_LAMPS 16
#define CAUSTICS_MAX_LAMPS 4
#define CAUSTICS_LAMP_WORDS 8

// Receivers: from CAUSTICS_MIN_HEIGHT to CAUSTICS_MAX_HEIGHT metres above the water plane, at
// most CAUSTICS_MAX_PATH metres from their water point along the reflected light, facing it by
// more than CAUSTICS_MIN_FACING (the cosine). Weight exp(-path / CAUSTICS_PATH_FALLOFF), faded out
// between CAUSTICS_FADE_START and CAUSTICS_FADE_END metres of view depth.
#define CAUSTICS_MIN_HEIGHT 0.03
#define CAUSTICS_MAX_HEIGHT 4.0
#define CAUSTICS_MAX_PATH 8.0
#define CAUSTICS_PATH_FALLOFF 2.5
#define CAUSTICS_MIN_FACING 0.05
#define CAUSTICS_FADE_START 30.0
#define CAUSTICS_FADE_END 45.0
// The water point counts as water when nothing on the screen stands in front of it (the depth
// there is not nearer than the point by more than CAUSTICS_SEEN_M + CAUSTICS_SEEN_REL x its view
// depth) and the surface the depth shows there does not stand above the plane by more than
// CAUSTICS_WATER_M + CAUSTICS_WATER_REL x its view depth (m): the water itself, or the ground
// under it seen through it. bbport (r107b_caustics-visible): was "the depth lies on the plane".
// bbport (r107c_caustics-lamp-gain): a surface the depth shows on the plane (within that height)
// is the water, also when it is nearer than the point.
#define CAUSTICS_WATER_M 0.04
#define CAUSTICS_WATER_REL 0.002
#define CAUSTICS_SEEN_M 0.05
#define CAUSTICS_SEEN_REL 0.03
// bbport (r107b_caustics-visible): the lamps (BB_CAUSTICS_LAMPS). A lamp from
// CAUSTICS_LAMP_MIN_HEIGHT above the plane up to its reach lights the water; the water's light
// arrives as from the lamp mirrored in the plane. Receivers from CAUSTICS_MIN_HEIGHT to
// CAUSTICS_LAMP_MAX_HEIGHT above the plane. Light added: albedo x colour x (1 - d / reach)^2 (the
// game's lamp curve, d the reflected path's length) x facing x the water's reflectance (Schlick,
// CAUSTICS_WATER_F0 at normal incidence) x the pattern where the path crosses the water x
// CAUSTICS_LAMP_GAIN (a look choice: a ripple focuses the reflected light into the net's lines) x
// strength.
// bbport (r107c_caustics-lamp-gain): that was far too faint (the log's "+0%"): 2.5 x a reflectance
// of about 0.02 (the angles a wall beside the water takes its light at) is about 5% of the lamp's
// own light at that distance, less where its colour was limited. Now: albedo x colour x the
// game's lamp curve at d (CAUSTICS_DATA_CORE2) x facing (the lamp's own direct light at the
// reflected path's length and angle) x the water's share 1 - exp(-CAUSTICS_LAMP_GAIN x strength x
// reflectance x the pattern): always below 1, so never more than that direct light; at strength 1
// and near normal incidence its mean is about 0.37, on the net's lines about 0.7 to 0.9.
#define CAUSTICS_LAMP_MIN_HEIGHT 0.05
#define CAUSTICS_LAMP_MAX_HEIGHT 8.0
#define CAUSTICS_WATER_F0 0.02
#define CAUSTICS_LAMP_GAIN 30.0
// bbport (r107d_caustics-lamp-look): BB_CAUSTICS_LAMPS above 1 adds a look control: the lamps'
// light above stays at strength 1, and ALL the light a receiver has (the scene's colour, whatever
// lit it) is multiplied by 1 + look x min(w, 1) x fade x (c - 1). look = CAUSTICS_LOOK_MAX x
// (strength - 1) / 3 (strength 4: CAUSTICS_LOOK_MAX); w = the sum over the lamps whose path crosses
// water of facing x exp(-the crossing's distance / CAUSTICS_PATH_FALLOFF) (here a crossing hidden
// behind something nearer counts as water: the screen cannot tell); c = their weighted mean of
// (1 - exp(-CAUSTICS_LAMP_GAIN x CAUSTICS_WATER_F0 x the pattern)) / CAUSTICS_LOOK_MEAN, mean 1,
// from 0 to 2.69: light is moved, not added; the factor stays from 1 - look to 1 + 1.69 x look.
#define CAUSTICS_LOOK_MAX 0.6
#define CAUSTICS_LOOK_MEAN 0.372
// bbport (r107e_caustics-puddles): a puddle candidate faces up (world normal y from
// CAUSTICS_PUDDLE_UP) and has the G-buffer's gloss (material .r, the specular exponent's log2 / 13)
// from CAUSTICS_PUDDLE_GLOSS (exponent 2^10.4, about 1350: near a mirror). Still water: the pattern
// on a puddle drifts and changes CAUSTICS_PUDDLE_SPEED as fast and keeps CAUSTICS_PUDDLE_CONTRAST of
// its contrast (1 + 0.5 x (pattern - 1)).
#define CAUSTICS_PUDDLE_GLOSS 0.8
#define CAUSTICS_PUDDLE_UP 0.9
#define CAUSTICS_PUDDLE_SPEED 0.25
#define CAUSTICS_PUDDLE_CONTRAST 0.5
// bbport (r107f_caustics-world-anchored): the world map: CAUSTICS_MAP_SIZE x CAUSTICS_MAP_SIZE cells
// of 1 / CAUSTICS_MAP_CELLS_PER_M m in world x, z (wrapped: 64 m), one word each: the plane's
// generation x 4 + the state (CAUSTICS_MAP_*). Written by every up-facing pixel on the plane (water;
// on puddles only a candidate) or up to CAUSTICS_MAP_LEDGE m above it (dry), read where a lamp's
// crossing is off the screen or hidden. The bed: a mirrored plane's water pixel gets the lamps'
// unshadowed light on the horizontal surface x its albedo (the bed's, from the G-buffer) x
// CAUSTICS_BED_T x the pattern there x BB_CAUSTICS_WORLD's number; a puddle's pixel has the share of
// its light that comes from the lamps (at most 1) x CAUSTICS_BED_PUDDLE moved by the pattern (at most
// 3). Puddles ripple like water: the pattern at CAUSTICS_RIPPLE_SPEED of the speed, with
// CAUSTICS_RIPPLE_CONTRAST of its contrast.
#define CAUSTICS_MAP_SIZE 256
#define CAUSTICS_MAP_WORDS 65536
#define CAUSTICS_MAP_CELLS_PER_M 4.0
#define CAUSTICS_MAP_UNKNOWN 0u
#define CAUSTICS_MAP_WATER 1u
#define CAUSTICS_MAP_DRY 2u
#define CAUSTICS_MAP_LEDGE 0.6
#define CAUSTICS_BED_T 0.3
#define CAUSTICS_BED_PUDDLE 0.7
#define CAUSTICS_RIPPLE_SPEED 0.8
#define CAUSTICS_RIPPLE_CONTRAST 1.0

// The pattern: two layers of ridged value noise on the water (world x, z), cells of
// CAUSTICS_LAMBDA1 and CAUSTICS_LAMBDA2 metres, the second turned by 37 degrees (CAUSTICS_COS2,
// CAUSTICS_SIN2); each layer's ridge to the power CAUSTICS_SHARP (thin bright lines), the two
// averaged (a net whose crossings are brightest), divided by CAUSTICS_PATTERN_MEAN (that average's
// mean, from a Monte Carlo of this noise over 600000 points: 0.1933), so the pattern's mean is 1:
// light is moved, not added. The third noise axis is the time: CAUSTICS_EVOLVE cells a second
// (layer 2: x CAUSTICS_EVOLVE2, shifted by CAUSTICS_EVOLVE2_SHIFT cells).
#define CAUSTICS_LAMBDA1 0.9
#define CAUSTICS_LAMBDA2 0.55
#define CAUSTICS_COS2 0.79863551
#define CAUSTICS_SIN2 0.60181502
#define CAUSTICS_SHARP 8.0
#define CAUSTICS_PATTERN_MEAN 0.1933
#define CAUSTICS_EVOLVE 0.3
#define CAUSTICS_EVOLVE2 1.3
#define CAUSTICS_EVOLVE2_SHIFT 17.0
// bbport (r130b_water-moves): the moving water. After the data blocks, a motion block of CAUSTICS_MOTION_WORDS words a slot (base
// CAUSTICS_MOTION_BASE), written by the host before a dispatch with CAUSTICS_FLAG_MOTION: word KIND the plane (0 none, 1 mirrored,
// 2 a checked puddle plane), RINGS the rings live, STRENGTH (float) the knob, RING_PX the water pixels a ring reached (the SHADER
// adds, one atomicAdd a group; the host reads it before it rewrites the slot), from WAVES_AT CAUSTICS_MOTION_WAVES waves of
// WAVE_WORDS (k x, k z, A, phase, 0 ...: eta = A sin(k . xz - phase)), from RINGS_AT up to MAX_RINGS rings of RING_WORDS (x, z,
// age s, amplitude m). Focus: the pattern times clamp(1 - FOCUS x curvature, 0, 3); warp: its position moves by WARP x slope; the
// shimmer: SHIMMER x strength x clamp(8 x slope toward the camera, -0.6, 0.6). A ring is a packet at radius RING_SPEED x age, width
// RING_WIDTH, wave number RING_K (rad/m), amplitude falling as exp(-age / RING_TAU) / sqrt(1 + r / RING_R0); it lives RING_LIFE s.
#define CAUSTICS_MOTION_WORDS 104
#define CAUSTICS_MOTION_BASE (CAUSTICS_SLOTS * (CAUSTICS_SLOT_WORDS + CAUSTICS_DATA_WORDS))
#define CAUSTICS_MOTION_KIND 0
#define CAUSTICS_MOTION_RINGS 1
#define CAUSTICS_MOTION_STRENGTH 2
#define CAUSTICS_MOTION_RING_PX 3
#define CAUSTICS_MOTION_WAVES_AT 4
#define CAUSTICS_MOTION_WAVE_WORDS 8
#define CAUSTICS_MOTION_WAVES 4
#define CAUSTICS_MOTION_RINGS_AT 36
#define CAUSTICS_MOTION_RING_WORDS 4
#define CAUSTICS_MOTION_MAX_RINGS 16
#define CAUSTICS_MOTION_FOCUS 0.25
#define CAUSTICS_MOTION_WARP 4.0
#define CAUSTICS_MOTION_SHIMMER 0.35
#define CAUSTICS_RING_SPEED 0.30
#define CAUSTICS_RING_WIDTH 0.05
#define CAUSTICS_RING_K 89.76
#define CAUSTICS_RING_TAU 0.9
#define CAUSTICS_RING_LIFE 2.5
#define CAUSTICS_RING_R0 0.05
// bbport (r130e_sewer-water-moves): the rippled reflection. The four free words of the motion block: ROW0 the first row of the band
// (the host's WaterTopRow), WARP_PX and WARP_KEPT the water pixels the WARP dispatch took a colour for and those it left as they were
// (the shader adds, one atomicAdd a group; the host reads them before it rewrites the slot), STAMP the dispatch's number (1 to 2047,
// exact in half float): a copy texel counts only when its alpha holds it. The mirror image moves by 2 x REFLECT_M metres of the water
// plane for a slope of 1 (a look number: the physical 2 to 4 m would tear the image), projected, at most SHIFT_MAX x the frame's
// height in pixels. The glint: the colour times 1 + t, t = GLINT x strength x (Focus - 1) x lum / (lum + GLINT_KNEE) within
// +-GLINT_MAX (the focus has mean 1: light is moved, not added). The band starts ROW_MARGIN pixels above the first row the host's ray
// test puts water in (it steps ROW_STEP rows).
#define CAUSTICS_MOTION_ROW0 100
#define CAUSTICS_MOTION_WARP_PX 101
#define CAUSTICS_MOTION_WARP_KEPT 102
#define CAUSTICS_MOTION_STAMP 103
#define CAUSTICS_MOTION_REFLECT_M 0.25
#define CAUSTICS_MOTION_SHIFT_MAX 0.012
#define CAUSTICS_MOTION_GLINT 0.30
#define CAUSTICS_MOTION_GLINT_MAX 0.6
#define CAUSTICS_MOTION_GLINT_KNEE 0.05
#define CAUSTICS_MOTION_ROW_MARGIN 16
#define CAUSTICS_MOTION_ROW_STEP 8

// t196's optional binding 4 tail. Fields not reached retain the all-ones sentinel.
#define BED_OBS_BASE (CAUSTICS_MOTION_BASE + CAUSTICS_SLOTS * CAUSTICS_MOTION_WORDS)
#define BED_OBS_TAIL_WORDS 512u
#define BED_OBS_NPOINTS 3u
#define BED_OBS_NSTAGES 3u
#define BED_OBS_WORDS 40u
#define BED_OBS_READBACK (BED_OBS_BASE + BED_OBS_NSTAGES * BED_OBS_NPOINTS * BED_OBS_WORDS)
// Observation-only coordinates and actual fetch addresses/words follow the HDR snapshots.
#define BED_OBS_POINTS (BED_OBS_READBACK + 2u * BED_OBS_NSTAGES * BED_OBS_NPOINTS)
#define BED_OBS_TAPS (BED_OBS_POINTS + 2u * BED_OBS_NPOINTS)
#define BED_OBS_NTAPS 3u
#define BED_OBS_TAP_WORDS 3u
// Optional motion-series lamp crossing words, two WARP rows by four lamps.
#define BED_OBS_MOTION_SERIES (BED_OBS_TAPS + BED_OBS_NSTAGES * BED_OBS_NPOINTS * BED_OBS_NTAPS * BED_OBS_TAP_WORDS)
#define BED_OBS_OPTICS (BED_OBS_MOTION_SERIES + 1u)
#define BED_OBS_OPTIC_WORDS 4u
#define BED_OBS_MAGIC 0x74313936u
#define BED_OBS_UNREAD 0xffffffffu
#define BED_OBS_SHADE 0u
#define BED_OBS_COPY 1u
#define BED_OBS_WARP 2u
#define BED_OBS_X0 780
#define BED_OBS_Y0 670
#define BED_OBS_X1 700
#define BED_OBS_Y1 810
#define BED_OBS_X2 1140
#define BED_OBS_Y2 390

#define BED_OBS_ENTRY 0u
#define BED_OBS_GATE 1u
#define BED_OBS_REASON 2u
#define BED_OBS_READS 3u
#define BED_OBS_RAW 4u
#define BED_OBS_DEPTH 5u
#define BED_OBS_WATER_Z 6u
#define BED_OBS_WATER_WORLD 7u
#define BED_OBS_BED_Z 10u
#define BED_OBS_BED_WORLD 11u
#define BED_OBS_LAMPS 14u
#define BED_OBS_INCIDENT 18u
#define BED_OBS_CB2 21u
#define BED_OBS_NATIVE 24u
#define BED_OBS_RGB_BASE 27u
#define BED_OBS_OPERAND 30u
#define BED_OBS_STORE 34u
#define BED_OBS_DONOR 35u
#define BED_OBS_NORMAL 36u
#define BED_OBS_FADE 37u
#define BED_OBS_STRENGTH 38u
#define BED_OBS_STAMP 39u

// Destination gate (one final disposition, including the first failed gate).
#define BED_GATE_CLEAR 1u
#define BED_GATE_NO_WORLD 2u
#define BED_GATE_HEIGHT 3u
#define BED_GATE_NORMAL 4u
#define BED_GATE_DRY 5u
#define BED_GATE_PUDDLE 6u
#define BED_GATE_LEGACY 7u
#define BED_GATE_DEFERRED 8u
#define BED_GATE_NATIVE 9u
#define BED_GATE_FADE 10u
#define BED_GATE_COPY_WET 11u

// First native receiver disposition. Geometry failures retain the actual read mask.
#define BED_CAUSE_WATER_Z 1u
#define BED_CAUSE_CENTRE_RAW 2u
#define BED_CAUSE_CENTRE_WORLD 3u
#define BED_CAUSE_CENTRE_ABOVE 4u
#define BED_CAUSE_CENTRE_Z 5u
#define BED_CAUSE_X 6u
#define BED_CAUSE_Y 7u
#define BED_CAUSE_EDGE_X 8u
#define BED_CAUSE_EDGE_Y 9u
#define BED_CAUSE_DEGENERATE 10u
#define BED_CAUSE_NO_INCIDENT 11u
#define BED_CAUSE_NO_PRODUCT 12u
#define BED_CAUSE_POSITIVE 13u

#define BED_LAMP_HEIGHT 1u
#define BED_LAMP_RADIUS 2u
#define BED_LAMP_RANGE 3u
#define BED_LAMP_NEAR 4u
#define BED_LAMP_INCIDENCE 5u
#define BED_LAMP_WATER_RESULT 6u // + Water()'s actual return code (0 = accepted)
#define BED_STORE_NONE 0u
#define BED_STORE_SCENE 1u
#define BED_STORE_COPY 2u

#endif
