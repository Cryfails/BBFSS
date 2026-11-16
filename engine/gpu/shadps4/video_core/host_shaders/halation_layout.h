// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): what the halation's shader (halation.comp) and the engine
// (renderer_vulkan/halation_params.h, which ties these to its enums with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef HALATION_LAYOUT_H
#define HALATION_LAYOUT_H

// The passes, by the push word `mode` (HalationParams::Mode).
#define HALATION_MODE_DOWN 0u
#define HALATION_MODE_BLUR_X 1u
#define HALATION_MODE_BLUR_Y 2u
#define HALATION_MODE_ADD 3u
// BB_HALATION_SHOW=2: the glow alone on black (HalationParams::ShowGlowOnly).
#define HALATION_SHOW_GLOW_ONLY 2u
// A key slot's words: log-luminance sum, texels, pixels over the threshold, unused
// (HalationParams::KeySlotWords).
#define HALATION_SLOT_WORDS 4u
// Pixels or texels a side of one workgroup (HalationParams::Group).
#define HALATION_GROUP 8u

#endif
