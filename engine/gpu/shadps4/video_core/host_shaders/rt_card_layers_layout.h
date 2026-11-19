// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the layout the card alpha passes (rt_card_alpha_fill.comp,
// rt_card_view.comp, and the rays of stage 4 through rt_cards.glsl) share with the engine
// (renderer_vulkan/rt_card_layers.h, CardAlpha, RtShadow). Plain #define lines only, as
// rt_card_uv_layout.h: GLSL includes this file and C++ includes it as it is, so one text says
// where every field lies for both.
#ifndef RT_CARD_LAYERS_LAYOUT_H
#define RT_CARD_LAYERS_LAYOUT_H

// The alpha layers: one R8_UNORM 2D array image, CARD_LAYER_SIZE square, CARD_LAYER_MIPS levels,
// CARD_LAYER_COUNT layers. A layer holds one game texture's alpha lane (the lane the cut-out test
// reads), resampled to this size. Level 0 is what a lamp ray reads (stage 4); levels 1 and 2 are
// for the sun (mip 1) and the bounced light (mip 2) of stage 6, and for the debug view, which
// reads the level that matches the game's own mip at each pixel. They cost 1/3 more.
#define CARD_LAYER_SIZE 256
#define CARD_LAYER_MIPS 3
#define CARD_LAYER_COUNT 128

// The layer info buffer: one uint a layer. Bits 0-30 the layer's generation (it changes each time
// the layer is given to another texture), bit 31 set when the layer holds a fill of it. A card
// row names a layer and the generation it was given with: a row whose generation is not the
// layer's (the layer went to another texture) or whose layer is not filled is a card without
// data, never a card tested against another texture's alpha.
#define CARD_LAYER_GEN_MASK 0x7fffffffu
#define CARD_LAYER_READY 0x80000000u

// The card table: one row of 8 uints (32 bytes, two uvec4) a card slot (CardUvEntry::slot, 1 to
// 65535; row 0 is never READY). A TLAS instance of a cut-out entry carries its slot as its
// instanceCustomIndex (24 bits; 0: not a card).
//  word 0: the entry's first record in the pool (CardUvEntry::offset, in records)
//  word 1: the entry's triangles (a primitive index at or past it is no data)
//  word 2: flags: the layer in bits 0-9, the test's op (CardOp) in bits 10-12, the nonzero term
//          in bit 13, the u axis's mode in bits 14-15, v's in bits 16-17, bit 18 the camera
//          pass's dither with a coefficient not 0 (taken as 0, as stage 2 does; stage 4
//          decides), bit 19 the rule is the sun shadow pass's (the entry's card is a sun pass
//          card: its reference may differ from the camera pass's), bits 20-21 the u axis's
//          extra (CARD_AXIS_*), bits 22-23 v's, (r62b) bit 24 a sun shadow pass draw of the
//          entry does not discard (its sun shadow is solid: stages 5 and 6), bit 25 the rule keeps
//          no alpha in [0, 1] (fully clear: no layer needed, every candidate dropped), READY in
//          bit 31
//  word 3: the reference (float bits): keep A <op> reference
//  words 4, 5: the card's offset u, v (float bits): the pool leaves it to its reader
//  word 6: the dither's coefficient (float bits; 0 for a sun shadow pass card)
//  word 7: the layer's generation when the row was written (see CARD_LAYER_GEN_MASK)
#define CARD_ROW_WORDS 8
#define CARD_ROW_BYTES 32
#define CARD_ROWS 65536
#define CARD_ROW_LAYER_MASK 0x3ffu
#define CARD_ROW_OP_SHIFT 10
#define CARD_ROW_NONZERO 0x2000u
#define CARD_ROW_MODE_U_SHIFT 14
#define CARD_ROW_MODE_V_SHIFT 16
#define CARD_ROW_DITHER 0x40000u
#define CARD_ROW_SUN 0x80000u
#define CARD_ROW_EXTRA_U_SHIFT 20
#define CARD_ROW_EXTRA_V_SHIFT 22
#define CARD_ROW_SUN_SOLID 0x1000000u
#define CARD_ROW_CLEAR 0x2000000u
#define CARD_ROW_READY 0x80000000u

// An axis's extra (row bits 20-21, 22-23), from the sampler's raw clamp mode (GCN: 3
// MirrorOnceLastTexel, 4 ClampHalfBorder, 5 MirrorOnceHalfBorder, 6 ClampBorder, 7
// MirrorOnceBorder; the mode bits say CLAMP for all of them). Mirror once: the coordinate is
// mirrored about 0 before the clamp. Border: outside [0, 1] the game reads the border colour,
// which the row does not hold: such a candidate is no data.
#define CARD_AXIS_MIRROR_ONCE 1u
#define CARD_AXIS_BORDER 2u

// The ops (CardOp's order)
#define CARD_OP_LESS 0
#define CARD_OP_LESS_EQUAL 1
#define CARD_OP_GREATER 2
#define CARD_OP_GREATER_EQUAL 3
#define CARD_OP_EQUAL 4
#define CARD_OP_NOT_EQUAL 5

// What a card test gives (cardTest in rt_cards.glsl)
#define CARD_NO_DATA 0
#define CARD_KEPT 1
#define CARD_DROPPED 2

// The fill pass: 8x8 threads a group, CARD_LAYER_SIZE square threads: each writes its texel of
// level 0, of level 1 when both coordinates are below CARD_LAYER_SIZE / 2, of level 2 below / 4.
// Push constants (16 bytes): uint layer, uint lane (the view lane, 0-3), two unused. A texel is
// the mean of up to CARD_FILL_MAX_TAPS bilinear taps an axis (CardFillLod).
#define CARD_FILL_GROUP 8
#define CARD_FILL_PUSH_BYTES 16
#define CARD_FILL_MAX_TAPS 8

// The debug view (BB_RT_CARD_ALPHA_VIEW): 8x8 threads a group, one a pixel. Push constants (64
// bytes): vec4 proj (x scale, y scale, z scale, z offset; CameraMotion's), vec2 jitter (render
// pixels), uvec2 size, uint mode, uint flags, two unused, then vec4 unused.
#define CARD_VIEW_GROUP 8
#define CARD_VIEW_PUSH_BYTES 64
#define CARD_VIEW_OVERLAY 1
#define CARD_VIEW_ALPHA 2
#define CARD_VIEW_UV 3
#define CARD_VIEW_MODES 3
// The counters (uints, atomicAdd), read back every CardViewLineFrames view frames. Every pixel
// adds to PIXELS and to one class: SKY, NO_CARD, NO_DATA, one of the four judged classes
// (AGREE_*, RAY_*), or, for a tested card pixel the GO line does not judge, the reason:
// SUN_CARD (the row holds the sun shadow pass's rule, not the camera's), DITHERED (the camera
// pass dithers with a coefficient not 0), COARSE (the game's own mip there is coarser than the
// layer's last level), and (r62b) CLEAR (the row's rule keeps no alpha in [0, 1]: drawn white).
// CARD_HITS counts the pixels with a card candidate in front of the first other hit, whatever
// their class.
#define CARD_VIEW_PIXELS 0
#define CARD_VIEW_CARD_HITS 1
#define CARD_VIEW_AGREE_KEPT 2
#define CARD_VIEW_AGREE_DROPPED 3
#define CARD_VIEW_RAY_KEPT_GAME_DROPPED 4
#define CARD_VIEW_RAY_DROPPED_GAME_KEPT 5
#define CARD_VIEW_NO_DATA 6
#define CARD_VIEW_DITHERED 7
#define CARD_VIEW_NO_CARD 8
#define CARD_VIEW_SKY 9
#define CARD_VIEW_SUN_CARD 10
#define CARD_VIEW_COARSE 11
#define CARD_VIEW_CLEAR 12
#define CARD_VIEW_COUNTERS 13
// A card candidate at ray distance t is "where the game's depth is" within this tolerance:
// |t - depth distance| < CARD_VIEW_TOL_REL * depth distance + CARD_VIEW_TOL_ABS (metres, the
// game's units). The depth buffer is 24-bit or float: its own error at 50 m is centimetres.
#define CARD_VIEW_TOL_REL 0.005
#define CARD_VIEW_TOL_ABS 0.02

// bbport (r63_leaf-stage4): the lamp rays read the cards (BB_RT_CARD_LAMPS=1 with
// BB_RT_CARD_ALPHA=2; point_shadow_ray.comp's CARDS builds through rt_cards.glsl's
// cardTraceShadow; renderer_vulkan/rt_card_layers.h CardRayRun is the same loop on the CPU). A
// plant's or a static cut-out's instance whose card row is READY carries CARD_LAMP_MASK in its
// TLAS mask and is built FORCE_NO_OPAQUE (RtShadow::PrepareScene); every other instance keeps its
// mask and stays opaque, so a ray that meets no card is the opaque ray of before, ended at its
// first hit. The lamp rays trace 0x04 (vk_rt_shadow.cpp LampMask) | CARD_LAMP_MASK.
#define CARD_LAMP_MASK 0x08u
// The most card candidates with data one ray tests (one layer read each): the next one blocks the
// ray. The default, and the most BB_RT_CARD_LAMP_CAP can give (6 bits of the lamp tuning word 0).
#define CARD_RAY_CAP_DEFAULT 16u
#define CARD_RAY_CAP_MOST 63u
// Card candidates of any kind (with data or without) one ray takes: at most CARD_RAY_GUARD times
// its cap; the next one blocks the ray.
#define CARD_RAY_GUARD 4u
// A candidate's layer level: log2 of the ray's footprint there in layer texels, taking one UV unit
// as one metre of the world (CARD_RAY_TEXELS_PER_M texels a metre); 0 at one texel or less, at most
// the last level. A guess (atlas leaves or large cards are off by an unknown factor):
// BB_RT_CARD_LAMP_TEXELS scales the lamp pass's footprint for the game test (CardRayTexelScale);
// texels a metre worked out per triangle is a stage 7 item.
#define CARD_RAY_TEXELS_PER_M 256.0
// What ended a ray (CardRay.how): nothing (it reached its end), a solid hit, a kept texel, the cap
#define CARD_RAY_FREE 0u
#define CARD_RAY_OPAQUE 1u
#define CARD_RAY_KEPT 2u
#define CARD_RAY_CAP 3u
// The lamp pass's counters (uints; set 1 binding 4 of its CARDS builds), added to on one pass in
// 16 (MODE_CARD_COUNT) by the rays of one pixel in 64 (x and y multiples of 8), never cleared (the
// host takes differences; CARD_LAMP_MOST, atomicMax, is the most since the start): the rays, those
// that met a card candidate, the candidates tested (layer reads), the candidates without data, the
// most candidates one ray tested, then one counter a CardRay.how of the rays that met a card
// (CARD_LAMP_HOW + how).
#define CARD_LAMP_RAYS 0
#define CARD_LAMP_CARD_RAYS 1
#define CARD_LAMP_TESTED 2
#define CARD_LAMP_NO_DATA 3
#define CARD_LAMP_MOST 4
#define CARD_LAMP_HOW 5
// (then, of the rays that met a card, those that tested none: they met only cards without data)
#define CARD_LAMP_BLIND 9
// bbport (r62g_cutout-shadows-visible): six more counters of the same 16: of the layer reads, those at a
// level above 0, those on a texel of alpha 0, those on a texel with an alpha above 0 that the card's rule
// dropped (the rest were kept); the rays cast to the card disc (BB_RT_CARD_LAMP_RADIUS), those only a
// card blocked, and the rays the solid ray blocked first (no card ray was cast).
#define CARD_LAMP_LOD_READS 10
#define CARD_LAMP_ZERO_READS 11
#define CARD_LAMP_PARTIAL_READS 12
#define CARD_LAMP_SHARP_RAYS 13
#define CARD_LAMP_CARD_ONLY 14
#define CARD_LAMP_SOLID_FIRST 15
// bbport (r62h_cutout-cards-hit): seven more, of the card rays of the two-ray form (r62g): the rays that a
// card stopped by the distance of the hit from the ray's start (under 3 cm, under 10, under 30, farther), the
// reads of these rays, those kept only by the reference scale (BB_RT_CARD_LAMP_REF) and the sum of the
// levels read in sixteenths.
#define CARD_LAMP_KEPT_D0 16
#define CARD_LAMP_KEPT_D1 17
#define CARD_LAMP_KEPT_D2 18
#define CARD_LAMP_KEPT_D3 19
#define CARD_LAMP_RESCUED 20
#define CARD_LAMP_LOD16 21
#define CARD_LAMP_SPLIT_READS 22
// bbport (r62i_cutout-uv-proof): nine more of the 32, of the proof view (BB_RT_CARD_LAMP_PROOF_VIEW): the screen pixels
// read, then one counter a class of cardProof (not a card, kept, dropped on alpha 0, dropped on a partly covered texel,
// no data, not judged: CARD_LAMP_PROOF_NO_CARD + class), the card pixels the layer's level 1 keeps, and the card pixels
// whose raw coordinates lie outside 0-1.
#define CARD_LAMP_PROOF_PIXELS 23
#define CARD_LAMP_PROOF_NO_CARD 24
#define CARD_LAMP_PROOF_KEPT 25
#define CARD_LAMP_PROOF_ZERO 26
#define CARD_LAMP_PROOF_PARTIAL 27
#define CARD_LAMP_PROOF_NO_DATA 28
#define CARD_LAMP_PROOF_UNJUDGED 29
#define CARD_LAMP_PROOF_KEPT_L1 30
#define CARD_LAMP_PROOF_UV_OUTSIDE 31
// bbport (r62j_cutout-rule-and-place): eleven more of the proof view, then spare: the judged card pixels the LAMP rule keeps;
// the pixels the game's rule dropped on a partly covered texel, by texel alpha over the reference (under 0.25, 0.25-0.5,
// 0.5-1); the judged pixels with coordinates outside 0-1, those the row's mode keeps, those a forced wrap would keep; the
// reads at cards in front of the surface (the game dropped them): all, on alpha 0, kept by the game's rule, kept by the lamp rule.
#define CARD_LAMP_PROOF_LAMP_KEPT 32
#define CARD_LAMP_PROOF_BIN1 33
#define CARD_LAMP_PROOF_BIN2 34
#define CARD_LAMP_PROOF_BIN3 35
#define CARD_LAMP_PROOF_OUT_JUDGED 36
#define CARD_LAMP_PROOF_OUT_KEPT 37
#define CARD_LAMP_PROOF_OUT_WRAP_KEPT 38
#define CARD_LAMP_PROOF_FRONT_READS 39
#define CARD_LAMP_PROOF_FRONT_ZERO 40
#define CARD_LAMP_PROOF_FRONT_GAME_KEPT 41
#define CARD_LAMP_PROOF_FRONT_LAMP_KEPT 42
// bbport (r62k_cutout-lit-fence): the three layer rules' kept counts (rule 0 bilinear, 1 maximum of four, 2 nearest; three each, in
// that order): at cards in front of the surface (the game dropped them: false shadows), then on the judged card pixels (of which the
// game kept most); then the lit patch finder (cardLit): pixels seen, card-shadowed, lit, both, and the sums for both (x, y, z, pixel
// x, pixel y, lamp distance, lamp share, shadow depth), then spare ones
#define CARD_LAMP_FRONT_BILIN 43
#define CARD_LAMP_FRONT_MAX 44
#define CARD_LAMP_FRONT_NEAR 45
#define CARD_LAMP_JUDGED_BILIN 46
#define CARD_LAMP_JUDGED_MAX 47
#define CARD_LAMP_JUDGED_NEAR 48
#define CARD_LAMP_LIT_PIXELS 49
#define CARD_LAMP_LIT_BLOCKED 50
#define CARD_LAMP_LIT_BRIGHT 51
#define CARD_LAMP_LIT_BOTH 52
#define CARD_LAMP_LIT_SUM_X 53
#define CARD_LAMP_LIT_SUM_Y 54
#define CARD_LAMP_LIT_SUM_Z 55
#define CARD_LAMP_LIT_SUM_PX 56
#define CARD_LAMP_LIT_SUM_PY 57
#define CARD_LAMP_LIT_SUM_DIST 58
#define CARD_LAMP_LIT_SUM_SHARE 59
#define CARD_LAMP_LIT_SUM_DEPTH 60
// bbport (r62l_cutout-steady-proof): the lit patch's blocker within 10 cm of the surface, the sum of the blockers' distances (cm, at most
// 300 each), the kept reads the strict zone overruled, and the lit-and-shadowed pixels that lie on a card surface; then spare ones
#define CARD_LAMP_LIT_NEAR 61
#define CARD_LAMP_LIT_SUM_WENT 62
#define CARD_LAMP_STRICT_DROPS 63
#define CARD_LAMP_LIT_ON_CARD 64
#define CARD_LAMP_HOUSING_SKIPS 65 // bbport (r62n_cutout-skinned-blocker): cut-out cards passed untested within the housing zone of the lamp
// bbport (r62o_cutout-visible-foliage) FEATURE: the half-resolution blocks (BB_RT_CARD_LAMP_BLOCKS), counted like the other card counters: first-pass pixels,
// those whose rays tested a leaf card (they mark their block), second-pass pixels that reached the take decision in a marked block, beside a marked block only,
// forced to trace by the rule, and all that reached the decision (the last one counts only with the knob on, 1 to 3)
#define CARD_LAMP_BLK_FIRST 66
#define CARD_LAMP_BLK_FIRST_CARD 67
#define CARD_LAMP_BLK_OWN 68
#define CARD_LAMP_BLK_RING 69
#define CARD_LAMP_BLK_FORCED 70
#define CARD_LAMP_BLK_TAKEN_ALL 71
#define CARD_LAMP_COUNTERS 72 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48 then 64; r62l: was 64)
// bbport (r62m_cutout-name-blocker) TOOL: the blocker book follows the counters (the counters buffer is CARD_LAMP_BUFFER_WORDS words
// long; the host differences only the first CARD_LAMP_COUNTERS): CARD_BOOK_ENTRIES entries of CARD_BOOK_WORDS words at CARD_LAMP_BOOK,
// one for each card slot that blocked the lamp ray of a lit and shadowed counted pixel (point_shadow_ray.comp bookAdd): word 0 the card
// slot (0: empty), 1 the pixels, 2-4 the hits' smallest x, y, z as 6400 minus (cm + 3200) in view space (atomicMax keeps them), 5-7 the
// largest, 8 the sum of the hit-to-lamp distances (cm, each at most 3000), 9 the sum of the hit-to-surface distances (cm), 10 the hits the
// game's own rule keeps too, 11 spare. Then the pixels whose blocker had no card slot and those that found the table full.
#define CARD_LAMP_BOOK 72
#define CARD_BOOK_ENTRIES 12
#define CARD_BOOK_WORDS 12
#define CARD_LAMP_BOOK_NO_SLOT 216
#define CARD_LAMP_BOOK_FULL 217
#define CARD_LAMP_BUFFER_WORDS 218

// bbport (r131a_foliage-translucency): the colour layers (RGBA8, CARD_COLOUR_SIZE square, one level, CARD_LAYER_COUNT layers: the level 2 size of the
// alpha layers; rt_card_alpha_fill.comp COLOUR=1) and the lamp pass's FOLIAGE counters (point_shadow_ray.comp): words CARD_LAMP_FOLIAGE_FIRST on of the
// counters buffer, which is CARD_LAMP_FOLIAGE_WORDS words longer only with FOLIAGE builds: 0 lamp rays, 1 rays that passed a leaf, 2 leaves passed,
// 3 rays that ended at the floor, 4 leaves passed without colour (a mask texture), then three spare.
#define CARD_COLOUR_SIZE 64
#define CARD_LAMP_FOLIAGE_FIRST 218
#define CARD_LAMP_FOLIAGE_WORDS 8

#endif
