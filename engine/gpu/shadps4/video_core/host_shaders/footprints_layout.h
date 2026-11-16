// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111_footprints): what the footprints' shader (footprints.comp) and the engine
// (renderer_vulkan/footprints.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef FOOTPRINTS_LAYOUT_H
#define FOOTPRINTS_LAYOUT_H

// Pixels a side of one workgroup (FootprintRules::Group).
#define FOOTPRINTS_GROUP 8u
// Prints the shader reads at most (the host sends only those whose box is on this pass's screen).
#define FOOTPRINTS_MAX_PRINTS 48u
// The push word `flags`: the test view (BB_FOOTPRINTS=show); the counter slot of this frame (0 or
// 1); the hunter's position in `hunter` is known (the sense around the feet runs, and the test view
// draws its ring); G-buffer target 2 is R8G8B8A8_SRGB, bound through an R8G8B8A8_UNORM view (the
// shader decodes it to linear and encodes what it writes back).
#define FOOTPRINTS_FLAG_SHOW 1u
#define FOOTPRINTS_FLAG_SLOT 2u
#define FOOTPRINTS_FLAG_HUNTER 4u
#define FOOTPRINTS_FLAG_SRGB 8u
// A print's kind (the print's b.w): what the feet stepped in.
#define FOOTPRINTS_KIND_WET 0u
#define FOOTPRINTS_KIND_MUD 1u
#define FOOTPRINTS_KIND_BLOOD 2u
#define FOOTPRINTS_KINDS 3u
// A counter slot's words. All sums (each group adds its own with one atomic a word), except STAMP,
// a maximum: the push word `stamp` of the pass that wrote the slot (the host's frame + 1).
#define FOOTPRINTS_SLOT_WORDS 18u
// Pixels a print changed (weight above 1/64), pixels the pass looked at.
#define FOOTPRINTS_WORD_PRINT_PX 0u
#define FOOTPRINTS_WORD_SEEN_PX 1u
// Around the hunter (within FOOTPRINTS_SENSE_RADIUS_M across, FOOTPRINTS_SENSE_HEIGHT_M up or
// down of his position's height), up-facing pixels: their count; the sum of (height above his
// position + FOOTPRINTS_SENSE_HEIGHT_M) in millimetres; the count by that height: below
// -FOOTPRINTS_BIN_M, below -FOOTPRINTS_GROUND_M, within FOOTPRINTS_GROUND_M (the ground band),
// up to FOOTPRINTS_BIN_M, above it.
#define FOOTPRINTS_WORD_SENSE_N 2u
#define FOOTPRINTS_WORD_SENSE_DY_MM 3u
#define FOOTPRINTS_WORD_BIN_LOW 4u
#define FOOTPRINTS_WORD_BIN_BELOW 5u
#define FOOTPRINTS_WORD_GROUND_N 6u
#define FOOTPRINTS_WORD_BIN_ABOVE 7u
#define FOOTPRINTS_WORD_BIN_HIGH 8u
// The ground band's pixels, before any print is laid on them: the sum of the gloss (G-buffer target
// 1, red) times 255; how many have a gloss of at least FOOTPRINTS_PUDDLE_GLOSS; the sums of the
// linear albedo (G-buffer target 2, decoded from sRGB when it is so) red, green and blue times 255.
#define FOOTPRINTS_WORD_GLOSS_SUM 9u
#define FOOTPRINTS_WORD_WET_N 10u
#define FOOTPRINTS_WORD_ALBEDO_R 11u
#define FOOTPRINTS_WORD_ALBEDO_G 12u
#define FOOTPRINTS_WORD_ALBEDO_B 13u
#define FOOTPRINTS_WORD_STAMP 14u
#define FOOTPRINTS_WORD_RING_PX 15u
// r111b: the pickup disc, the ground band's pixels within FOOTPRINTS_PICK_RADIUS_M of his position
// (the ground under and around the feet): how many, and how many of them are blood by the albedo
// rule of blood_albedo_layout.h.
#define FOOTPRINTS_WORD_PICK_N 16u
#define FOOTPRINTS_WORD_BLOOD_N 17u
// The sense around the feet (metres).
#define FOOTPRINTS_SENSE_RADIUS_M 0.45
#define FOOTPRINTS_SENSE_HEIGHT_M 1.0
#define FOOTPRINTS_BIN_M 0.25
#define FOOTPRINTS_GROUND_M 0.08
// (r111b) The pickup disc around his position, within the ground band (metres across).
#define FOOTPRINTS_PICK_RADIUS_M 0.25
// Gloss a puddle has at least (exponent 2^(13 g) in the game's lighting).
#define FOOTPRINTS_PUDDLE_GLOSS 0.88
// A pixel is up-facing when its normal (from the depth of its neighbours) has an upward share of at
// least FOOTPRINTS_UP_MIN; a print's weight grows from 0 at FOOTPRINTS_UP_MIN to full at
// FOOTPRINTS_UP_FULL (walls and the hunter's legs get none).
#define FOOTPRINTS_UP_MIN 0.6
#define FOOTPRINTS_UP_FULL 0.85
// A print lies on the ground within this height of its centre (metres): a print placed in the air
// (a jump) or on another level draws nothing.
// (r111c: 0.16, was 0.12: the graveyard's cobbles tilt by several cm across one sole)
#define FOOTPRINTS_PRINT_BAND_M 0.16
// The sole (metres, along the step u, across v): the fore part an ellipse at u FORE_U with half
// axes FORE_RU x FORE_RV, the heel one at u HEEL_U with HEEL_RU x HEEL_RV; edges soft from
// FOOTPRINTS_EDGE of the radius out.
#define FOOTPRINTS_FORE_U 0.055
#define FOOTPRINTS_FORE_RU 0.085
#define FOOTPRINTS_FORE_RV 0.055
#define FOOTPRINTS_HEEL_U -0.095
#define FOOTPRINTS_HEEL_RU 0.045
#define FOOTPRINTS_HEEL_RV 0.04
// (r111d) A boot's sole: the heel block (u -0.14 to -0.05, 0.08 m across), the narrow waist (an ellipse
// at u WAIST_U with half axes WAIST_RU x WAIST_RV, 0.044 m across, bridging the gap between the heel and
// the ball) and the ball (u -0.03 to 0.14, 0.11 m across) make a print 0.28 m long and 0.11 m across at its
// widest (r111c's two ellipses drawn 1.25 times larger were a blob). Edges are soft only from EDGE of the
// radius out: 0.82 (was 0.7), about 1 cm.
#define FOOTPRINTS_WAIST_U -0.04
#define FOOTPRINTS_WAIST_RU 0.045
#define FOOTPRINTS_WAIST_RV 0.022
#define FOOTPRINTS_EDGE 0.82
// (r111d) The sole above is drawn at this scale: 1 (r111c drew r111's numbers 1.25 times larger; the
// numbers themselves now give the 0.28 x 0.11 m sole).
#define FOOTPRINTS_SOLE_SCALE 1.0
// What a fully weighted print does to the G-buffer (albedo values linear). Wet: the albedo
// darkened by WET_DARKEN (review 2026-11-15: 0.5, so that it reads in a still); the
// gloss raised toward WET_GLOSS and the root of the specular colour (target 3, f0 = rgb^2) toward
// WET_SPEC_ROOT (a water film, f0 0.04; never lowered). Mud: the albedo toward MUD_ALBEDO by
// MUD_COVER; the gloss toward MUD_GLOSS. Blood: the albedo toward BLOOD_ALBEDO by BLOOD_COVER; the
// gloss raised toward BLOOD_GLOSS, the specular colour as wet (never lowered).
// (r111c: darken 0.6 was 0.5, gloss 0.8 was 0.62, specular root 0.25 was 0.2: a wet print on night stone
// was a few levels darker than the stone, under its noise)
// (r111d: darken 0.65, was 0.6)
#define FOOTPRINTS_WET_DARKEN 0.65
#define FOOTPRINTS_WET_GLOSS 0.8
#define FOOTPRINTS_WET_SPEC_ROOT 0.25
#define FOOTPRINTS_MUD_ALBEDO_R 0.2
#define FOOTPRINTS_MUD_ALBEDO_G 0.14
#define FOOTPRINTS_MUD_ALBEDO_B 0.08
#define FOOTPRINTS_MUD_COVER 0.8
#define FOOTPRINTS_MUD_GLOSS 0.42
// (r111b: dark red about as the graveyard pool's own albedo, linear 0.021 0.006 0.005 on average;
// r111 had 0.3 0.02 0.015, far brighter than the pool the blood comes from)
// (r111c: the print's red follows the stone it lies on, so it reads as a dark red patch on any ground:
// red = the ground's linear red x BLOOD_RED_KEEP, between RED_MIN and RED_MAX (the blood rule's own maximum
// is 0.12, so prints stay blood for the pickup rule and the blood sheen); green and blue are low, ALBEDO_G
// and _B. ALBEDO_R is the typical print red (the stone's 0.09 x 0.75), kept for the tests.)
// (r111d: darker: red 0.6 times the stone's, 0.03 to 0.085, was 0.75 times, 0.04 to 0.10; ALBEDO_R is the
// typical print red, the stone's 0.1 x 0.6; gloss 0.78, was 0.72. Every red of the range is blood by the
// blood rule: at least 0.01, at most 0.12, at least 2.5 times the green and the blue.)
#define FOOTPRINTS_BLOOD_ALBEDO_R 0.06
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005
#define FOOTPRINTS_BLOOD_RED_KEEP 0.6
#define FOOTPRINTS_BLOOD_RED_MIN 0.03
#define FOOTPRINTS_BLOOD_RED_MAX 0.085
#define FOOTPRINTS_BLOOD_COVER 0.95
#define FOOTPRINTS_BLOOD_GLOSS 0.78
// Test view: the ring around the hunter's position (metres from it, across).
#define FOOTPRINTS_RING_IN_M 0.3
#define FOOTPRINTS_RING_OUT_M 0.34
// (r111e) The draw over the finished picture (footprints_flat.comp). Counter words, one atomic a drawn
// pixel: the flat red test view's pixels and the post stamp's pixels. The test view's red (scene colour,
// before the tonemap; the print's centre dot is white, 4). The post stamp: a wet or mud print darkens the
// lit pixel a further POST_WET_DARKEN; a blood print recolours it toward a dark red of the pixel's own
// luminance (the tint has luminance 1: (1.00 0.12 0.10) over 0.3056), cover POST_BLOOD_COVER at full
// weight, scaled by POST_BLOOD_LUM.
// (r111f) The counters grew: the pass's own proof that it ran (workgroups executed, the stamp of the frame it
// ran in) and, for the first FLAT_PROBES prints, where the shader finds the print's centre on the screen and
// the scene's depth there: per probe FLAT_PROBE_WORDS words (pixel x + 1, pixel y, the depth's bits, the view
// z's bits; word 0 = 0: no result). FLAT_MARK_HALF: half the side of the test view's hollow marker square
// (2 * half + 1 pixels); FLAT_BEACON: the side of the solid corner square drawn whenever the pass ran.
#define FOOTPRINTS_FLAT_WORD_RED_PX 0u
#define FOOTPRINTS_FLAT_WORD_POST_PX 1u
#define FOOTPRINTS_FLAT_WORD_GROUPS 2u
#define FOOTPRINTS_FLAT_WORD_STAMP 3u
#define FOOTPRINTS_FLAT_WORD_PROBE 4u
#define FOOTPRINTS_FLAT_PROBES 8u
#define FOOTPRINTS_FLAT_PROBE_WORDS 4u
// (r111i) Six more counter words after the probes, for every stamped pixel (weight above 1/64): the number of
// pixels, the sum of the lit luminance before the stamp and the sum after it, each times LUM_SCALE with the
// luminance capped at LUM_CAP (the sums wrap past 65536 pixels a pass), for wet and mud prints (words LUM + 0 to 2)
// and for blood prints (LUM + 3 to 5): the proof of what the stamp did where it wrote. A pixel counts as blood
// where the blood weight is above the wet and mud ones.
#define FOOTPRINTS_FLAT_WORD_LUM 36u
#define FOOTPRINTS_FLAT_LUM_WORDS 6u
#define FOOTPRINTS_FLAT_LUM_SCALE 16384.0
#define FOOTPRINTS_FLAT_LUM_CAP 4.0
// (r111j) One more counter word after the luminance words: the blood pixels the faint wet sheen lifted.
#define FOOTPRINTS_FLAT_WORD_SHEEN 42u
#define FOOTPRINTS_FLAT_WORDS 43u
#define FOOTPRINTS_FLAT_MARK_HALF 7
#define FOOTPRINTS_FLAT_BEACON 24
#define FOOTPRINTS_FLAT_RED 3.0
// (r111g) Stronger at the default: a wet or mud print darkens the lit pixel 40% (was 25%); the blood tint is a
// deeper, more saturated red (3.90 0.22 0.19, luminance 1.0002; was 3.272 0.393 0.327), laid at 0.70 of the pixel's
// own luminance (was 1.00: a dark red mark on the stone, not a recoloured one), cover 95% (was 85%).
// (r111h) A wet or mud print darkens the lit pixel 55% (was 40%) with a soft edge (the sole's outer 45% of its
// radius, POST_WET_EDGE; blood keeps EDGE).
#define FOOTPRINTS_POST_WET_DARKEN 0.55
// (r111i) a firmer wet outline: the soft edge starts at 70% of the radius (was 55%); blood keeps EDGE (82%).
#define FOOTPRINTS_POST_WET_EDGE 0.70
#define FOOTPRINTS_POST_BLOOD_TINT_R 3.90
#define FOOTPRINTS_POST_BLOOD_TINT_G 0.22
#define FOOTPRINTS_POST_BLOOD_TINT_B 0.19
// (r111h) A DEEP dark red, 0.25 of the lit pixel's luminance (was 0.70, which put the red channel at 2.7 times
// the stone's: bright red): the red channel is about 0.97 of the stone's, green and blue 0.05.
#define FOOTPRINTS_POST_BLOOD_LUM 0.25
// (r111h) The right surface: a pixel whose view z is under NEAR_FRAC of its print's view z and more than NEAR_M
// nearer is not on the print (a character or a plant in front of it); the facing is read from points NORMAL_PX
// pixels away and not across a depth jump of more than NEIGHBOUR_M + NEIGHBOUR_REL x z.
#define FOOTPRINTS_POST_NEAR_FRAC 0.9
#define FOOTPRINTS_POST_NEAR_M 0.3
#define FOOTPRINTS_POST_NORMAL_PX 3
#define FOOTPRINTS_POST_NEIGHBOUR_M 0.15
#define FOOTPRINTS_POST_NEIGHBOUR_REL 0.05
#define FOOTPRINTS_POST_BLOOD_COVER 0.95
// (r111i) Next to something in front: a pixel with a surface more than SILHOUETTE_M + SILHOUETTE_REL x its own view
// z NEARER at SILHOUETTE_FRAC x the picture height (at least 2 pixels) to its left, right, above or below is beside
// the hunter's leg or weapon (or a plant), not on the print: it is left out.
#define FOOTPRINTS_POST_SILHOUETTE_FRAC 0.005
#define FOOTPRINTS_POST_SILHOUETTE_M 0.2
#define FOOTPRINTS_POST_SILHOUETTE_REL 0.03
// (r111j) BB_FOOTPRINTS_SHEEN (blood prints only, default 0 = off): a wet film on dark ground reflects a little of the
// sky, so a dark red print on near-black stone is lifted to at least SHEEN_SKY x the knob in luminance (the blood
// tint's luminance is 1, so the lift adds exactly that), passed through r100k's roll-off: untouched under SHEEN_KNEE
// x SHEEN_PEAK, an exponential toward SHEEN_PEAK above it, never above it. Lit ground above the floor is not touched.
#define FOOTPRINTS_SHEEN_SKY 0.012
#define FOOTPRINTS_SHEEN_PEAK 0.03
#define FOOTPRINTS_SHEEN_KNEE 0.5
// (r111j) A view line's verdict 2 or 3: the mean lit luminance under the stamp is under this (near black), or not.
#define FOOTPRINTS_VIEW_READABLE_LUM 0.02
// (r111k) Water against blood (BB_FOOTPRINTS_LOOK, default on; 0 is r111j's look). A wet print darkens more (the G-buffer
// change K_WET_DARKEN, was 0.65; the post stamp K_POST_WET_DARKEN, was 0.55), raises a dull ground's gloss toward
// K_WET_GLOSS (never lowered; the specular colour is not touched, as r111g left it) and on near-black ground is lifted to
// a faint COOL grey, a wet film's sky reflection: luminance floor K_WET_SHEEN in the hue K_WET_TINT (luminance 1, so the
// lift adds exactly the floor; no red). A blood print keeps its dark red and, under the look, always has the blood
// sheen's floor (K_BLOOD_SHEEN times SHEEN_SKY, as BB_FOOTPRINTS_SHEEN=1). Wet reads dark, cool and glossy; blood dark red.
#define FOOTPRINTS_K_WET_DARKEN 0.70
#define FOOTPRINTS_K_POST_WET_DARKEN 0.65
#define FOOTPRINTS_K_WET_GLOSS 0.85
#define FOOTPRINTS_K_WET_SHEEN 0.007
#define FOOTPRINTS_K_WET_TINT_R 0.88
#define FOOTPRINTS_K_WET_TINT_G 1.02
#define FOOTPRINTS_K_WET_TINT_B 1.11
#define FOOTPRINTS_K_BLOOD_SHEEN 1.0

#endif
