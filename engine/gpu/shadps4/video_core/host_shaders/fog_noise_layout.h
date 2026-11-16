// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r94_fog-noise): what the sun fog's world anchored noise shares between its shader
// (fog_noise.glsl, included by the NOISE builds of volumetric_light.comp) and the engine
// (renderer_vulkan/volumetric_fog_noise.h, VolumetricLight's fog noise). Plain #define lines only:
// the shader includes this file through GL_GOOGLE_include_directive and C++ includes it as it is,
// so one text holds every number both sides use.
#ifndef FOG_NOISE_LAYOUT_H
#define FOG_NOISE_LAYOUT_H

// A patch is FOG_NOISE_SQUASH times as wide as it is tall: the world's up (y) is multiplied by it
// before the lattice.
#define FOG_NOISE_SQUASH 1.6
// The three octaves: each one's cell over the scale (BB_FOG_NOISE_SCALE, metres), its weight
// (they add up to 1), and the cosine and sine of its yaw about the up axis (20, 57 and 97
// degrees), which turns each octave's lattice so that no two line up with each other or the world.
#define FOG_NOISE_RATIO0 1.0
#define FOG_NOISE_RATIO1 0.43
#define FOG_NOISE_RATIO2 0.19
#define FOG_NOISE_WEIGHT0 0.55
#define FOG_NOISE_WEIGHT1 0.30
#define FOG_NOISE_WEIGHT2 0.15
#define FOG_NOISE_YAW_COS0 0.93969262
#define FOG_NOISE_YAW_SIN0 0.34202014
#define FOG_NOISE_YAW_COS1 0.54463904
#define FOG_NOISE_YAW_SIN1 0.83867057
#define FOG_NOISE_YAW_COS2 -0.12186934
#define FOG_NOISE_YAW_SIN2 0.99254615
// The finest octave counts in full up to FOG_NOISE_FINE_FROM scales from the camera and fades
// out at FOG_NOISE_FINE_TO (16 and 24 m at the default 10 m): farther away its small swirls are
// smaller than a pixel of the march, and a sample there hashes 16 corners instead of 24.
#define FOG_NOISE_FINE_FROM 1.6
#define FOG_NOISE_FINE_TO 2.4
// Lattice cells along each axis before the corner values repeat (a coordinate's cell is taken
// & (FOG_NOISE_PERIOD - 1)); the offsets wrap at it.
#define FOG_NOISE_PERIOD 256
// The corner hash's seed (added to the packed cell before lowbias32, so cell 0 is not 0).
#define FOG_NOISE_SEED 0x9E3779B9u
// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1, the banks look: m = A + B w with w =
// smoothstep(FOG_NOISE_BANK_FROM, FOG_NOISE_BANK_TO, d), d the octaves' sum above (its sd is about
// 0.13), so banks of fog (w near 1, about a third of space) with clearer air between them.
// FOG_NOISE_BANK_MEAN is the mean of w over the world (a CPU sample of 300000 points: 0.360, and
// 0.357 past the finest octave's fade), FOG_NOISE_BANK_CLEAR the m of the clear air at strength 1,
// FOG_NOISE_BANK_SQUASH how many times wider than tall a bank is (in place of FOG_NOISE_SQUASH).
#define FOG_NOISE_BANK_FROM (-0.01)
#define FOG_NOISE_BANK_TO 0.11
#define FOG_NOISE_BANK_MEAN 0.36
#define FOG_NOISE_BANK_CLEAR 0.15
#define FOG_NOISE_BANK_SQUASH 2.5

#endif
