// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r83_glass-water-stage1): the instance mask of a window pane's entry in the ray traced
// scene (BB_RT_GLASS; RtShadow, renderer_vulkan/rt_glass.h), shared with the shaders that must
// leave the panes out (ssgi_gather_ray.comp's GLASS_SCENE build). Plain #define lines only, as
// rt_card_layers_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_GLASS_LAYOUT_H
#define RT_GLASS_LAYOUT_H

// No ray of today traces this bit: lamps 0x04 (0x04 | 0x08 with the cards), the sun 0x01, the sun
// fog gate 0 to 3, the bounced light 0xff, which the GLASS_SCENE build narrows to leave it out.
#define RT_GLASS_MASK 0x10u

#endif
