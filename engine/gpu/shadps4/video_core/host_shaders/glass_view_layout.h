// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r129a_glass-registry): what the glass view's shader (glass_view.comp) and the engine
// (renderer_vulkan/glass_registry.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text holds every number both sides use.
#ifndef GLASS_VIEW_LAYOUT_H
#define GLASS_VIEW_LAYOUT_H

// Pixels a side of one workgroup.
#define GLASS_VIEW_GROUP 8u
// The push word `flags`: SNAPSHOT: the tag is cleared too (first hit draw of a frame whose tag is not known clear).
#define GLASS_VIEW_FLAG_CLEAR 1u
// The kinds (GlassRegistryRules::Kind): the low three bits of a tag, 0 = no tag.
#define GLASS_VIEW_KIND_NONE 0u
#define GLASS_VIEW_KIND_WINDOW 1u
#define GLASS_VIEW_KIND_MIRROR 2u
#define GLASS_VIEW_KIND_BOTTLE 3u
#define GLASS_VIEW_KIND_LANTERN 4u
#define GLASS_VIEW_KIND_CABINET 5u
// The colour each kind is painted in (window cyan, mirror magenta, bottle orange, lantern and cabinet yellow).
#define GLASS_VIEW_WINDOW_R 0.0
#define GLASS_VIEW_WINDOW_G 1.0
#define GLASS_VIEW_WINDOW_B 1.0
#define GLASS_VIEW_MIRROR_R 1.0
#define GLASS_VIEW_MIRROR_G 0.0
#define GLASS_VIEW_MIRROR_B 1.0
#define GLASS_VIEW_BOTTLE_R 1.0
#define GLASS_VIEW_BOTTLE_G 0.5
#define GLASS_VIEW_BOTTLE_B 0.0
#define GLASS_VIEW_YELLOW_R 1.0
#define GLASS_VIEW_YELLOW_G 1.0
#define GLASS_VIEW_YELLOW_B 0.0
// Painted pixel = mix(pixel, colour * max(pixel luminance, FLOOR), MIX).
#define GLASS_VIEW_FLOOR 0.5
#define GLASS_VIEW_MIX 0.7

#endif
