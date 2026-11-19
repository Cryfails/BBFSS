// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130c_glass-lamp-light): what the lamp pass's GLASS builds (point_shadow_ray.comp, GLASS=1) and the engine
// (renderer_vulkan/glass_light.h, which ties these to its constants with static_asserts) share. Plain #define lines only: the
// shader includes this file through GL_GOOGLE_include_directive and C++ includes it as it is.
#ifndef GLASS_LIGHT_LAYOUT_H
#define GLASS_LIGHT_LAYOUT_H

// A glass record's instanceCustomIndex: this bit (bit 23) and, in the low 6 bits, the registry entry index (0 based). Card
// slots (rt_card_uv.h CardSlotsMost) stay below 1 << 16, so a glass record is never taken for a card.
#define GLASS_INDEX_BIT 0x800000u
#define GLASS_ENTRY_MASK 63u
// The glass query's instance mask (RtGlassMask) and its nearest start along a lamp ray, m.
#define GLASS_LIGHT_MASK 0x10u
#define GLASS_LIGHT_TMIN 0.03
// Most candidates (triangles of the mask) one lamp ray looks at.
#define GLASS_RAY_CAP 4u
// The words after a repair pass's 16 tuning words: one flag word, then one tint word for each registry entry (64).
#define GLASS_WORDS 65u
// The flag word: this pass's scene holds glass records; the lamps keep their own hue (BB_LAMP_SHADOW_COLOUR=1).
#define GLASS_FLAG_ACTIVE 1u
#define GLASS_FLAG_LAMP_HUE 2u

#endif
