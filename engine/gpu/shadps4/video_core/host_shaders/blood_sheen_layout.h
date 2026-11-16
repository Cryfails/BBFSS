// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): what the blood sheen's shader
// (blood_sheen.comp) and the engine (renderer_vulkan/blood_sheen.h, which ties these to its constants
// with static_asserts) share. Plain #define lines only: the shader includes this file through
// GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds every number both sides
// use.
#ifndef BLOOD_SHEEN_LAYOUT_H
#define BLOOD_SHEEN_LAYOUT_H

// Pixels a side of one workgroup (BloodSheenRules::Group).
#define BLOOD_SHEEN_GROUP 8u
// The push word `flags`: the test view (BB_BLOOD_SHEEN=show); the counter slot of this frame (0 or
// 1); EDIT: a draw key is set (a pixel must still hold what a keyed draw wrote); EDIT: the albedo rule
// (BB_BLOOD_SHEEN_RULE=albedo) picks among the pixels; SNAPSHOT: the first keyed draw of this
// G-buffer pass (the tag is cleared).
#define BLOOD_SHEEN_FLAG_SHOW 1u
#define BLOOD_SHEEN_FLAG_SLOT 2u
#define BLOOD_SHEEN_FLAG_KEYED 4u
#define BLOOD_SHEEN_FLAG_RULE_ALBEDO 8u
#define BLOOD_SHEEN_FLAG_CLEAR 16u
// bbport (r100e_blood-sheen-visible): EDIT: the normal target is bound and RGBA8 (the pixels' normals
// are flattened); SHOW (not the test view): the picked pixels are dimmed and reddened (push `darken`).
#define BLOOD_SHEEN_FLAG_NORMAL 32u
// A counter slot's words, sums. MARK: pixels the keyed draws changed (each draw's own, summed).
// EDIT: of the pixels a keyed draw changed, those that still hold what it wrote (kept) and those a
// later draw changed again (lost); pixels the albedo rule was asked about and passed; pixels made wet.
#define BLOOD_SHEEN_SLOT_WORDS 8u
#define BLOOD_SHEEN_WORD_KEYED 0u
#define BLOOD_SHEEN_WORD_KEPT 1u
#define BLOOD_SHEEN_WORD_LOST 2u
#define BLOOD_SHEEN_WORD_RULE 3u
#define BLOOD_SHEEN_WORD_WET 4u
// bbport (r100e_blood-sheen-visible): EDIT, what the made-wet pixels had before the film: the sum of
// the gloss times 255, the sum of the specular root's red times 255, and how many had a gloss at or
// above BLOOD_SHEEN_WET_GLOSS already.
#define BLOOD_SHEEN_WORD_GLOSS_SUM 5u
#define BLOOD_SHEEN_WORD_ROOT_SUM 6u
#define BLOOD_SHEEN_WORD_GLOSSY 7u
// The tag after EDIT: a pixel made wet; a keyed draw's pixel the albedo rule left out (SHOW paints
// both). Before EDIT the tag holds, where a keyed draw changed the pixel, its print with bit 0 set.
#define BLOOD_SHEEN_TAG_WET 1u
#define BLOOD_SHEEN_TAG_LEFT_OUT 2u
// EDIT: the gloss (G-buffer target 1, red; exponent 2^(13 g) in the game's lighting) and the root of
// the specular colour (G-buffer target 3, rgb; f0 = rgb^2) a pixel is raised toward: a liquid film
// (f0 0.09 at strength 1), gloss kept below the mirror (a sharp lobe, 2^(13 x 0.82) = 1660) so the
// game's static cube map does not show a wrong sky. Never lowered (max with what the ground has).
// Target 3's alpha (the lighting record) is never written. Above strength 1 the root grows with its
// square root, at most BLOOD_SHEEN_SPEC_ROOT_MAX (r100e_blood-sheen-visible: r100d had 0.66, 0.2, 0.4).
// r100h_sheen-liquid: the gloss stays 0.86 (exponent 2320; a level surface mirrors a light in ONE lobe, a
// higher gloss only narrows it) but is SET to it for every wet pixel (the ground's own value may go down:
// one width of lobe, no speckle); root 0.55 (f0 0.30 at strength 1), cap 0.75. (The numbers above name
// r100e's 0.82, 0.3 and 0.55, r100g's 0.86, 0.45 and 0.65.)
#define BLOOD_SHEEN_WET_GLOSS 0.86
// r100i_sheen-blood-tint: root 0.45 (f0 0.20 before the tint), cap 0.65 (strength 2: 0.636), and the root is
// TINTED by the blood: multiplied per channel by (TINT_R, TINT_G, TINT_B), a deep red (f0 = root squared, so red
// keeps 0.72 of the intensity, green 0.12, blue 0.09): the moon gives a dark red highlight, a torch a warm red
// orange one. Red is never lowered; green and blue go down to the tinted target by the pixel's wet weight.
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65
#define BLOOD_SHEEN_TINT_R 0.85
#define BLOOD_SHEEN_TINT_G 0.35
#define BLOOD_SHEEN_TINT_B 0.30
// EDIT, the normal (target 0, xyz*2-1, world space, Y up): a picked pixel's unit normal goes this share
// (times the strength, at most 1, times smoothstep(UP_LO, UP_HI, its own normal.y)) of the way to the
// world up vector: a liquid film lies level. The weight is a function of the pixel's own normal only,
// so no group, block or neighbour shows in it (r100f_sheen-smooth; r100e flattened toward the mean of
// each 8x8 workgroup and left a square highlight per block).
// r100g_sheen-sheets: the pixel goes ALL the way (SMOOTH 1.0) where the pool's dark red covers its
// surroundings (cover: the share of 16 taps, 8 directions at NEAR and 8 at FAR pixels at 1080p, scaled by
// height/1080, whose albedo is dark red; cover = smoothstep(COVER_LO, COVER_HI, share)); the weight is
// mix(EDGE, 1, cover) at the pool's edge so the edge follows the stones; the up gate is 0.35..0.6.
#define BLOOD_SHEEN_NORMAL_SMOOTH 1.0
#define BLOOD_SHEEN_NORMAL_UP_LO 0.35
#define BLOOD_SHEEN_NORMAL_UP_HI 0.6
#define BLOOD_SHEEN_NORMAL_EDGE 0.3
// r100h_sheen-liquid: the cover above is now the share of 24 taps, three rings of 8 at RING0, RING1 and RING2
// pixels (1080p, scaled by height/1080, each ring turned) whose albedo is dark red, so the ripple of the
// mask (a stone, a crack) is smaller than the blur; smoothstep(COVER_LO, COVER_HI, share) (the 16 taps and
// the numbers 0.45, 0.95, 4 and 10 of r100g are gone). FILL: a ground pixel the keyed draw wrote that is
// not dark red itself is made wet when at least FILL_MIN_HITS of the 8 taps of RING1 are dark red and by
// smoothstep(FILL_LO, FILL_HI, share) times the up weight (UP_LO, UP_HI) of its own normal.
#define BLOOD_SHEEN_COVER_LO 0.25
#define BLOOD_SHEEN_COVER_HI 0.65
#define BLOOD_SHEEN_RING0 6
#define BLOOD_SHEEN_RING1 14
#define BLOOD_SHEEN_RING2 28
#define BLOOD_SHEEN_FILL_LO 0.5
#define BLOOD_SHEEN_FILL_HI 0.8
#define BLOOD_SHEEN_FILL_MIN_HITS 2
// r100j_sheen-clean-rim: a gap-fill pixel's specular colour and gloss weight is its wet weight times
// mix(FILL_SPEC, 1, smoothstep(FILL_HI, 1, share)): at the pool's rim at most FILL_SPEC (0.35, r100k) of the body's,
// back to the body's value deep inside the pool. A pixel that passes the albedo rule is not a gap: share 1.
#define BLOOD_SHEEN_FILL_SPEC 0.35
// r100k_sheen-no-hot-spot: the gap-fill pixel's specular weight is also multiplied by its fill weight again (a squared
// falloff toward the rim's outer edge). SHOW, the picked pixels of the lit scene: a soft luminance ceiling,
// PEAK (BB_BLOOD_SHEEN_PEAK, default 0.7); luminance up to KNEE x PEAK is untouched, above it rolls off
// exponentially toward PEAK (colour scaled, hue kept). A near light's tight highlight on the wet lobe cannot
// blow out; the moonlit dark red sheet (below the knee) is as before. PEAK 0: no ceiling.
#define BLOOD_SHEEN_PEAK_DEFAULT 0.7
#define BLOOD_SHEEN_PEAK_KNEE 0.5
// SHOW (not the test view): a picked pixel of the lit scene is multiplied by (RED, OTHER, OTHER) times
// the share darken x (1 - smoothstep(LO, HI, luminance)), so dim diffuse goes deeper and redder and a
// bright highlight stays as it is.
#define BLOOD_SHEEN_DARKEN_RED 0.7
#define BLOOD_SHEEN_DARKEN_OTHER 0.4
#define BLOOD_SHEEN_DARKEN_LUMA_LO 0.1
#define BLOOD_SHEEN_DARKEN_LUMA_HI 0.6
// SHOW: the least brightness the marks are painted with (the pool is near black).
#define BLOOD_SHEEN_SHOW_FLOOR 0.1

#endif
