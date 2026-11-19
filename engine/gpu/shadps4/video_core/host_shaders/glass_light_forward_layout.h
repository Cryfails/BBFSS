// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130g_glass-light-forward): what the lamp pass's GLASS builds (point_shadow_ray.comp, GLASS=1) and the engine
// (renderer_vulkan/glass_light_forward.h, which ties these to its constants with static_asserts) share, on top of
// glass_light_layout.h. Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is.
#ifndef GLASS_LIGHT_FORWARD_LAYOUT_H
#define GLASS_LIGHT_FORWARD_LAYOUT_H

// The glass query of a lamp ray ends this far (m) short of the lamp's centre.
#define GLASS_LAMP_CLEAR 0.02
// The glass counter's words in half_counts (the half resolution passes' counters): the first word and how many. +0 rays asked,
// +1 met a glass record, +2 tinted the light, +3 met one inside the old blind end, +4 the entries met (OR of bits 0-31), +5..+7 the
// view position of a lamp met (float bits, last written), +8 its nearest pane's distance from the lamp's centre (mm, smallest).
#define GLASS_RAY_FIRST 16u
#define GLASS_RAY_SLOTS 9u

#endif
