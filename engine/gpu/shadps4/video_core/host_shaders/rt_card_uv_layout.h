// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r54_leaf-stage2): the layout the card UV pass (rt_card_uv.comp) shares with the engine
// (renderer_vulkan/rt_card_uv.h, RtShadow::RecordBuilds). Plain #define lines only: the shader
// includes this file through GL_GOOGLE_include_directive and C++ includes it as it is, so one
// text says where every field lies for both. Stage 3 and later read the pool records with it.
#ifndef RT_CARD_UV_LAYOUT_H
#define RT_CARD_UV_LAYOUT_H

// Threads a group: one triangle each.
#define CARD_UV_GROUP 64

// The capture ring: per captured vertex four floats (u, v, the alpha factor, 1.0 when the
// pixel shader has none, and (r62b_leaf-stage3-followups) another component of the alpha
// factor's output, MotionVectors::CaptureUvOther, unset without a factor: the log reads it back),
// 16 bytes, at ring[(capture param word 1 - 1 + vertex slot) * 4].
#define CARD_UV_RING_FLOATS 4
#define CARD_UV_RING_BYTES 16
// What the ring holds where no capture stored (a quiet NaN's bits): RecordBuilds fills the used
// part with it after each expand pass (and all of it once, before the first UV capture), and the
// capture stores it for a value its selector cannot name. The expand pass then marks the
// triangle not finite (CARD_UV_TRI_NOT_FINITE) instead of keeping an old or a zero value.
#define CARD_UV_RING_UNSET 0x7fc00000u

// The pool: one record of 16 bytes (a uvec4) a BLAS primitive, primitive p of an entry at
// pool[entry offset + p]. Words 0, 1, 2: packHalf2x16(u, v) of corners 0, 1, 2: the input
// coordinates times the draw's scale, minus the shift. The draw's offset is NOT in the pool: its
// reader adds the entry's card offset (CardDraw::affine[2], [3]; for a wrapping axis it may take
// it modulo 1, for a mirrored one modulo 2), so a moving offset (scrolling UVs) keeps the records.
// Word 3: corner alphas as unorm8 in bits 0-7, 8-15, 16-23, the flags below in bits 24-31.
#define CARD_UV_RECORD_BYTES 16
#define CARD_UV_RECORD_WORDS 4
#define CARD_UV_FLAGS_SHIFT 24
// A corner's coordinate is 4.0 or more away from 0 after the shift: half precision there is
// 2^-8 or coarser, so the triangle is marked (not dropped).
#define CARD_UV_TRI_WIDE 1
// The pixel shader multiplies no alpha factor in: the alphas are 255.
#define CARD_UV_TRI_NO_ALPHA 2
// A corner's coordinate is not a finite number, or its alpha factor not a number (a vertex no
// capture stored reads as CARD_UV_RING_UNSET): the triangle is not shifted.
#define CARD_UV_TRI_NOT_FINITE 4
// The alpha factor in 8 bits (r54 review points R7, R7-a, R7-b). The game's A is texel alpha
// times the interpolated factor; a ray's will be texel alpha times the interpolation of the
// stored k / 255. CARD_UV_ALPHA_GRID_EPS is the tolerance, in 8-bit steps: 2^-14 of a step
// (2.4e-7 in alpha; a few float ulps, which k / 255 computed in another order of operations
// stays within). A factor that far or nearer to k / 255 at every corner is not marked and is
// stored as k / 255: a ray then keeps and drops what the game does, except for an A within
// texel alpha * 2.4e-7 of the reference (and float rounding of the interpolation, which a ray
// and the raster may do differently). It is not "exact". Otherwise:
// A corner's factor is below 0 or above 1 by more than the tolerance (2.4e-7): the stored value
// is clamped, a ray's A can be far from the game's. A reader takes the triangle as one without
// card data (as CARD_UV_TRI_NOT_FINITE). A factor 1 + 1 ulp or -1e-9 is not marked: the clamp
// there moves it by less than the tolerance.
#define CARD_UV_TRI_ALPHA_RANGE 8
// A corner's factor is in [0, 1] but more than the tolerance away from k / 255: rounded by at
// most half a step (0.5 / 255), so a ray's A differs from the game's by at most texel alpha *
// 0.5 / 255. A texel whose A lies that close to the reference can fall on the other side
// (examples in test_rt_card_uv.cpp). Kept and counted; a later stage decides (a wider alpha needs
// a larger record).
#define CARD_UV_TRI_ALPHA_ROUNDED 16
#define CARD_UV_ALPHA_GRID_EPS 0.00006103515625
#define CARD_UV_SPAN_LIMIT 4.0

// How an axis repeats (the sampler's clamp mode): wrap shifts by floor(min), mirror by an even
// number, clamp not at all.
#define CARD_UV_MODE_WRAP 0
#define CARD_UV_MODE_MIRROR 1
#define CARD_UV_MODE_CLAMP 2

// Push constants (48 bytes): u64 indices at 0 (the entry's triangle list, buffer reference),
// uint ring_base at 8 (the capture's first ring vertex), uint triangles at 12, uint
// pool_offset at 16 (records), uint flags at 20, two unused words, vec4 affine at 32 (scale u,
// scale v, offset u, offset v: coordinate = input * scale + offset; RecordBuilds passes the
// offset as 0, see the pool above).
#define CARD_UV_PUSH_BYTES 48
#define CARD_UV_PUSH_RING_BASE 8
#define CARD_UV_PUSH_TRIANGLES 12
#define CARD_UV_PUSH_POOL_OFFSET 16
#define CARD_UV_PUSH_FLAGS 20
#define CARD_UV_PUSH_AFFINE 32
// flags: the u axis's mode in bits 0-1, v's in bits 2-3, an alpha factor in bit 4, the stat
// slot + 1 in bits 8-10 (0: none).
#define CARD_UV_PUSH_MODE_V_SHIFT 2
#define CARD_UV_PUSH_HAS_ALPHA 16
#define CARD_UV_PUSH_STAT_SHIFT 8

// The stat slots (the first entries expanded after each 600-frame line): 19 words each. Words
// 0-2 the least u, v, alpha of the corners after the scale, before the shift, as inverted keys
// (atomicMax of ~Key), words 3-5 the greatest as keys, word 6 the triangles marked wide, word 7
// those marked not finite, word 8 those marked CARD_UV_TRI_ALPHA_RANGE, word 9 those marked
// CARD_UV_TRI_ALPHA_ROUNDED. Words 0-5 take atomicMax, 6-9 atomicAdd. Each workgroup gathers its
// own in shared memory first (no subgroup operation is needed).
// (r62b_leaf-stage3-followups) Word 10 the triangles marked CARD_UV_TRI_NO_ALPHA (atomicAdd,
// as 6-9; words 0-10 are the ones gathered in shared memory, CARD_UV_STAT_SUM_WORDS). Words
// 11-18: the ring's raw values at the first CARD_UV_STAT_RAW_CORNERS corners of the entry's
// triangle list (triangle 0's three, triangle 1's first), per corner the alpha factor's bits,
// then the other component's (CARD_UV_RING_UNSET past the list or where no capture stored).
// Written by the dispatch's first invocation alone (plain stores).
#define CARD_UV_STAT_SLOTS 4
#define CARD_UV_STAT_SUM_WORDS 11
#define CARD_UV_STAT_RAW 11
#define CARD_UV_STAT_RAW_CORNERS 4
#define CARD_UV_STAT_WORDS 19
#define CARD_UV_STAT_MAX_WORDS 6

#endif
