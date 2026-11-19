// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r128c_lrt-cutout-props) FEATURE: BB_RT_CARD_SUN's numbers, shared by rt_shadow.comp's CARDS builds and renderer_vulkan/rt_card_sun.h. Plain
// #define lines only, as rt_glass_light_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_CARD_SUN_LAYOUT_H
#define RT_CARD_SUN_LAYOUT_H

// The CARDS builds' counters: words 16 to 23 of the sun trace's counters (r25_buf), the words BB_RT_GLASS_LIGHT uses (the two are not made together).
// 0 pixels that cast rays, 1 of them with a ray that met a card candidate, 2 layer reads, 3 rays a kept texel stopped, 4 pixels with such a ray,
// 5 candidates passed as the pixel's own surface, 6 rays stopped at the candidate cap, 7 first-pass pixels marked (the half build only).
#define CARD_SUN_FIRST_WORD 16u
#define CARD_SUN_WORDS 8u
// bbport (r131a_foliage-translucency): the FOLIAGE builds' four counters follow the CARDS ones (words 24 to 27 of the sun trace's counters; the buffer is
// four words longer only with them): sun rays, rays that passed a leaf, rays that ended at the floor, leaves passed without colour.
#define CARD_SUN_FOLIAGE_WORDS 4u
// The most card candidates with data one sun ray reads (the lamp rays' default, CARD_RAY_CAP_DEFAULT).
#define CARD_SUN_CAP 16u
// A card nearer than this many metres (or the ray's reach, if more) to the ray's start is the pixel's own surface: passed.
#define CARD_SUN_SELF_M 0.03
// The reference of an "above the reference" rule is scaled by this for the sun's reads (the lamp pass's CARD_REF_SCALE default).
#define CARD_SUN_REF 0.6

#endif
