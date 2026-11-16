// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT's numbers, shared by rt_shadow.comp's
// GLASS_LIGHT builds and renderer_vulkan/rt_glass_light.h. Plain #define lines only, as
// rt_glass_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_GLASS_LIGHT_LAYOUT_H
#define RT_GLASS_LIGHT_LAYOUT_H

// r25_flags bits of the sun trace, above r25's own (1, 2, 4, 8).
#define RT_GLASS_LIGHT_PANES 16u // panes are in the scene: sun-lit pixels ask them
#define RT_GLASS_LIGHT_VIEW 32u  // such a pixel keeps half its sun per pane candidate
#define RT_GLASS_LIGHT_PROBE 64u // counted frames: is a shadowed pixel's blocker a pane?
// Pane candidates (triangles) a ray takes at most.
#define RT_GLASS_LIGHT_CAP 4u
// The counters: words 16 to 21 of the sun trace's counters (r25_buf).
#define RT_GLASS_LIGHT_FIRST_WORD 16u
#define RT_GLASS_LIGHT_WORDS 6u

#endif
