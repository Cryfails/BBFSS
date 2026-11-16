# r62_leaf-stage3: stage 3 of the ray traced foliage shadows: the card alpha layers, the card
# table, the instance custom index, the card debug view and the CUT1 cache part. A DRAFT: not
# built in the tree, not run in the game. Off by default: BB_RT_CARD_ALPHA=2 (read once) turns it
# on; BB_RT_CARD_ALPHA_VIEW=1..3 (environment only, read once, never saved) shows the debug view.
# No shadow reads any of it: stage 4 (the lamp rays) will. (engine/docs/rt_card_alpha.md,
# "Stage 3", says what and why, with the numbers.)
#
# Apply order: r60, r53, r54 (r54_leaf-stage2.py), then this; check needs all three applied
# (S/r54_work is that state of the files it touches), 2026-11-15. Revision 1: the review fixes
# (S1-S12, F1-F12). check|apply|revert (revert restores byte for byte and removes the new files). The
# tree: the one the environment variable R62_ROOT names; without it the current directory when
# that is the root of a source tree, else <tree>/. Nothing is changed in place: every new
# text is written beside its target and moved over it, and a failure puts back what was already
# moved and removes what was already made. Files keep their line ends (all CRLF); new files are
# CRLF.
#
# WHAT (file by file):
#  renderer_vulkan/rt_card_uv.h: BB_RT_CARD_ALPHA=2 (CardAlphaLayers) read as a level;
#     CardDraw::layer (the layer + 1) and layer_gen (in neither hash), clamp_u/clamp_v (the
#     sampler's raw clamp modes, in constants_hash). tests/test_rt_card_uv.cpp: the knob's
#     expectations for "2" and "3".
#  ir/passes/cutout_analysis.h, cutout_analysis_pass.cpp: CardAlphaLevel() (read once; the
#     misread line names 0, 1 and 2); CardAlphaOn() is level >= 1; CutoutAnalysisVersion.
#  renderer_vulkan/vk_rt_shadow.h/.cpp: SetCardLayers (card_layers_on: a CardAlpha that is on),
#     CardTables, TakeCardRowCounts; the card table (CardRowsMake, CardRows: changed rows only,
#     before the TLAS build, no extra build); the instance custom index (the card slot, once its
#     row is written); PrepareCapture records the layer fills before every reader; r54's lines
#     print the knob's level.
#  renderer_vulkan/vk_rasterizer.h/.cpp: CardAlpha made after the drawn look only when Wanted()
#     (BB_RT_CARD_ALPHA=2), given to RtShadow when on; DrawContext::card_bound (what the pixel
#     shader's texture binding found, set by BindTexturesFromSet and the full lookup when
#     card_bound_on); NoteCardLayer.
#  renderer_vulkan/vk_rasterizer_effects.cpp: NoteCardLayer at a cut-out draw with card data; the
#     sampler's raw clamp modes into the card; the debug view at the end of
#     EffectsBeforeUpscaler; CardAlpha::OnFrameEnd.
#  renderer_vulkan/vk_pipeline_serialization.cpp: the CUT1 part (Info::Serialize, Deserialize;
#     padding written as 0, versioned with CutoutAnalysisVersion), LoadPipelineStage takes a
#     discarding pixel shader with it when only BB_RT_CARD_ALPHA is set.
#  renderer_vulkan/vk_card_alpha.h/.cpp, rt_card_layers.h (new): the layers, the fills, the view;
#     the pure parts. host_shaders/rt_card_layers_layout.h, rt_cards.glsl, rt_card_alpha_fill.comp,
#     rt_card_view.comp (new). tests/test_rt_card_layers.cpp (new).
#  engine/gpu/CMakeLists.txt: the two shaders (with their includes), rt-card-layers-test.
#  engine/build.sh: rt-card-layers-test in --test. engine/docs/rt_card_alpha.md: stage 3.
# KNOB OFF (unset or 1): no CardAlpha is made and nothing is printed (a set view knob is said
# off once); RtShadow's card_layers_on is false: no rows, custom index 0, no fills; the draw path
# and BindTextures test one bool (card_bound_on); DrawContext grows by 208 bytes (card_bound).
# Cache records as before (no cutout is analysed with the knob unset; with 1 the CUT1 part is
# written and used too, which only removes compiles in play). The engine's gpu-cache.id changes
# (as with any change to vk_pipeline_serialization.cpp or shader_recompiler/): the first start
# recompiles the cache with bb-shader-lab, or clears it.
# NOT CHANGED: anything a shadow ray or pass reads; point_shadow_ray.comp, lamp_shadow_tune.h,
# vk_point_shadow.h/.cpp, test_lamp_shadow_tune.cpp, test_rt_shadows.cpp,
# docs/renderer-performance-0.9.43.md, the drawn look's and the volumetric/fog files.

import os
import sys

ROOT = os.environ.get("R62_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/shader_recompiler/recompiler.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
SR = G + "shadps4/shader_recompiler/"
P = SR + "ir/passes/"
R = G + "shadps4/video_core/renderer_vulkan/"
H = G + "shadps4/video_core/host_shaders/"
TESTS = E + "tests/"
DOCS = E + "docs/"

TMP = ".r62tmp"  # a new text waits under this name beside its target (main)

FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "renderer-performance-0.9.43.md")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or \
        "volumetric" in name or "fog" in name


NEW = {
    H + "rt_card_layers_layout.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
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
//          extra (CARD_AXIS_*), bits 22-23 v's, READY in bit 31
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
// layer's last level). CARD_HITS counts the pixels with a card candidate in front of the first
// other hit, whatever their class.
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
#define CARD_VIEW_COUNTERS 12
// A card candidate at ray distance t is "where the game's depth is" within this tolerance:
// |t - depth distance| < CARD_VIEW_TOL_REL * depth distance + CARD_VIEW_TOL_ABS (metres, the
// game's units). The depth buffer is 24-bit or float: its own error at 50 m is centimetres.
#define CARD_VIEW_TOL_REL 0.005
#define CARD_VIEW_TOL_ABS 0.02

#endif
""",
    H + "rt_cards.glsl": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card test a ray runs at a candidate of a cut-out card, shared by
// the debug view (rt_card_view.comp) and, in stage 4, the lamp rays. renderer_vulkan/
// rt_card_layers.h's CardTest is the same on the CPU (tests/test_rt_card_layers.cpp).
//
// The including shader defines, before including this file, the bindings of set 0 it gives them:
//   CARD_BINDING_ROWS        the card table (RtShadow::CardTables().rows): two uvec4 a card slot
//   CARD_BINDING_POOL        r54's pool (RtShadow::CardTables().pool): one uvec4 a BLAS primitive
//   CARD_BINDING_LAYER_INFO  CardAlpha's layer info: one uint a layer
//   CARD_BINDING_ALPHA       CardAlpha's layers: the R8 2D array, linear, linear between its
//                            levels, clamp to edge (CardAlpha::ReaderBindings)
// How a ray finds its card (stage 4): the TLAS instance's instanceCustomIndex is the entry's card
// slot (0: not a card; RtShadow::PrepareScene with BB_RT_CARD_ALPHA=2), the candidate's
// primitive index is the BLAS primitive (one geometry a BLAS), and its barycentrics weigh the
// record's corners as 1 - b.x - b.y, b.x, b.y. Stage 4 traces with gl_RayFlagsNoOpaqueEXT (or
// builds the card instances with FORCE_NO_OPAQUE), runs cardTest on each card candidate and
// confirms a CARD_KEPT one; CARD_NO_DATA is its own choice (today's lamp rule leaves cards out).
// A lamp ray reads level 0 (cardTest); the sun (stage 6) may read level 1, the bounced light
// level 2 (cardTestLod).
#ifndef RT_CARDS_GLSL
#define RT_CARDS_GLSL

#include "rt_card_uv_layout.h"
#include "rt_card_layers_layout.h"

layout(set = 0, binding = CARD_BINDING_ROWS, std430) readonly buffer CardRows {
    uvec4 card_rows[];
};
layout(set = 0, binding = CARD_BINDING_POOL, std430) readonly buffer CardPool {
    uvec4 card_pool[];
};
layout(set = 0, binding = CARD_BINDING_LAYER_INFO, std430) readonly buffer CardLayerInfo {
    uint card_layer_info[];
};
layout(set = 0, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;

// One axis as the game's sampler repeats it (CardRepeat).
float cardRepeat(float c, uint mode) {
    if (mode == CARD_UV_MODE_WRAP) {
        return c - floor(c);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        const float m = c - 2.0 * floor(c * 0.5);
        return m > 1.0 ? 2.0 - m : m;
    }
    return clamp(c, 0.0, 1.0);
}

// With the axis's extra bits (CardRepeatAxis): mirror once before the clamp; a border axis
// outside [0, 1] sets `border` (the border colour is not in the row: no data).
float cardRepeatAxis(float c, uint mode, uint extra, inout bool border) {
    if (mode == CARD_UV_MODE_CLAMP) {
        if ((extra & CARD_AXIS_MIRROR_ONCE) != 0u) {
            c = abs(c);
        }
        if ((extra & CARD_AXIS_BORDER) != 0u && !(c >= 0.0 && c <= 1.0)) {
            border = true;
        }
    }
    return cardRepeat(c, mode);
}

bool cardKeeps(float a, float reference, uint op, bool nonzero) {
    bool keep = false;
    if (op == CARD_OP_LESS) {
        keep = a < reference;
    } else if (op == CARD_OP_LESS_EQUAL) {
        keep = a <= reference;
    } else if (op == CARD_OP_GREATER) {
        keep = a > reference;
    } else if (op == CARD_OP_GREATER_EQUAL) {
        keep = a >= reference;
    } else if (op == CARD_OP_EQUAL) {
        keep = a == reference;
    } else {
        keep = a != reference;
    }
    return keep && (!nonzero || a != 0.0);
}

struct CardResult {
    uint status; // CARD_NO_DATA, CARD_KEPT, CARD_DROPPED
    float alpha; // texel alpha times the interpolated factor
    vec2 uv;     // the layer coordinates read
    vec2 raw;    // the coordinates before the repeat (smooth over the card)
    uint flags;  // the row's word 2 (CARD_ROW_*), 0 without a row
};

CardResult cardTestLod(uint slot, uint primitive, vec2 bary, float lod) {
    CardResult r = CardResult(CARD_NO_DATA, 0.0, vec2(0.0), vec2(0.0), 0u);
    if (slot == 0u || slot >= uint(CARD_ROWS)) {
        return r;
    }
    const uvec4 a = card_rows[slot * 2u];
    const uvec4 b = card_rows[slot * 2u + 1u];
    r.flags = a.z;
    const uint layer = a.z & CARD_ROW_LAYER_MASK;
    // A row not READY, a layer given to another texture since (its generation moved on) or not
    // filled, a primitive past the entry's records or past the pool: no data, never another
    // card's alpha.
    if ((a.z & CARD_ROW_READY) == 0u || layer >= uint(CARD_LAYER_COUNT) ||
        card_layer_info[layer] != (b.w | CARD_LAYER_READY) || primitive >= a.y ||
        a.x + primitive >= uint(card_pool.length())) {
        return r;
    }
    const uvec4 rec = card_pool[a.x + primitive];
    if (((rec.w >> CARD_UV_FLAGS_SHIFT) & uint(CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_ALPHA_RANGE)) != 0u) {
        return r;
    }
    const float b0 = 1.0 - bary.x - bary.y;
    const vec2 uv = unpackHalf2x16(rec.x) * b0 + unpackHalf2x16(rec.y) * bary.x +
                    unpackHalf2x16(rec.z) * bary.y + uintBitsToFloat(b.xy);
    const vec3 corner = vec3(float(rec.w & 0xffu), float((rec.w >> 8) & 0xffu),
                             float((rec.w >> 16) & 0xffu)) / 255.0;
    const float factor = corner.x * b0 + corner.y * bary.x + corner.z * bary.y;
    bool border = false;
    r.raw = uv;
    r.uv = vec2(cardRepeatAxis(uv.x, (a.z >> CARD_ROW_MODE_U_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u, border),
                cardRepeatAxis(uv.y, (a.z >> CARD_ROW_MODE_V_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
    if (border) {
        return r;
    }
    r.alpha = textureLod(card_alpha, vec3(r.uv, float(layer)), lod).r * factor;
    r.status = cardKeeps(r.alpha, uintBitsToFloat(a.w), (a.z >> CARD_ROW_OP_SHIFT) & 7u,
                         (a.z & CARD_ROW_NONZERO) != 0u)
                   ? CARD_KEPT
                   : CARD_DROPPED;
    return r;
}

// The lamp rays' test (stage 4): the layer's level 0.
CardResult cardTest(uint slot, uint primitive, vec2 bary) {
    return cardTestLod(slot, primitive, bary, 0.0);
}

#endif
""",
    H + "rt_card_alpha_fill.comp": r"""#version 460
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): one card alpha layer from a game texture (CardAlpha::RecordFills).
// The source is the game's own view of the texture (Image::FindView with the draw's T# and
// resource), sampled through a linear sampler: BC1 (its punch-through alpha decodes to 0 or 1),
// BC3, BC7 and sRGB views are decoded by the hardware as for the game, and the view's component
// mapping is the T#'s, so view lane `lane` reads what the game's cut-out test reads. One thread
// a texel of level 0, of level 1 below half the size, of level 2 below a quarter: each level
// samples the source at its own footprint (rt_card_layers.h, CardFillLod), so no level waits on
// another inside the dispatch.
#extension GL_GOOGLE_include_directive : require

#include "rt_card_layers_layout.h"

layout(local_size_x = CARD_FILL_GROUP, local_size_y = CARD_FILL_GROUP) in;

layout(set = 0, binding = 0) uniform sampler2D src;
layout(set = 0, binding = 1, r8) uniform writeonly image2DArray level0;
layout(set = 0, binding = 2, r8) uniform writeonly image2DArray level1;
layout(set = 0, binding = 3, r8) uniform writeonly image2DArray level2;

layout(push_constant) uniform Push {
    uint layer;
    uint lane;
    uint unused0;
    uint unused1;
} pc;

float lane(vec4 texel) {
    return texel[min(pc.lane, 3u)];
}

// CardFillAxisTaps: the source texels an axis covers, as a count of taps (1 to the most).
int axisTaps(float texels) {
    return int(clamp(ceil(texels - 1e-3), 1.0, float(CARD_FILL_MAX_TAPS)));
}

// CardFillLod: the level from the smaller side's ratio (log2(ratio) - 1, or 0 when that side is
// no larger than the level), then on each axis as many bilinear taps as source texels it covers
// there, spread evenly over the destination texel (a box filter of its footprint).
float alphaAt(ivec2 p, float size) {
    const vec2 src_size = vec2(textureSize(src, 0));
    const float top = float(max(textureQueryLevels(src), 1) - 1);
    const vec2 ratio = max(src_size, vec2(1.0)) / size;
    const float small = min(ratio.x, ratio.y);
    const float lod = small <= 1.0 ? 0.0 : clamp(log2(small) - 1.0, 0.0, top);
    const vec2 texels = ratio * exp2(-lod);
    const int nu = axisTaps(texels.x);
    const int nv = axisTaps(texels.y);
    const vec2 origin = vec2(p) / size; // the destination texel's corner
    float sum = 0.0;
    for (int j = 0; j < nv; ++j) {
        for (int i = 0; i < nu; ++i) {
            const vec2 at = origin + (vec2(i, j) + 0.5) / (vec2(nu, nv) * size);
            sum += lane(textureLod(src, at, lod));
        }
    }
    return sum / float(nu * nv);
}

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const int size = CARD_LAYER_SIZE;
    if (p.x >= size || p.y >= size) {
        return;
    }
    const int layer = int(pc.layer);
    imageStore(level0, ivec3(p, layer), vec4(alphaAt(p, float(size))));
    if (p.x < size / 2 && p.y < size / 2) {
        imageStore(level1, ivec3(p, layer), vec4(alphaAt(p, float(size / 2))));
    }
    if (p.x < size / 4 && p.y < size / 4) {
        imageStore(level2, ivec3(p, layer), vec4(alphaAt(p, float(size / 4))));
    }
}
""",
    H + "rt_card_view.comp": r"""#version 460
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card debug view (BB_RT_CARD_ALPHA_VIEW, with BB_RT_CARD_ALPHA=2;
// CardAlpha::View before the upscaler). It proves the chain a stage 4 ray will use, end to end,
// before any shadow changes: TLAS custom index -> card row -> pool record -> layer -> the game's
// rule. Per pixel, a ray from the camera (the origin of the TLAS's view space) towards the point
// the game's depth gives meets every candidate up to just past that point (no opaque flag: card
// candidates are tested, the others confirmed). The nearest card candidate in front of the first
// other hit is tested with cardTestLod and compared with what the game did there: its depth lies
// at the card (the game kept the card's texel) or behind it (the game dropped it).
// The game ran its alpha test at its own mip: far or grazing leaves read a coarse, blurred level.
// The view reads the layer level that matches it (CardViewLod: the coordinates' difference to
// the neighbouring pixels of the same card, shared in the group), so a correct chain agrees
// there too. The class (rt_card_layers.h, CardViewClass) tints the picture and is counted; a
// card the GO line does not judge (a sun pass card, a dithered one, one whose game mip is coarser
// than the layers' last level: CardViewExcluded) is counted by that reason and drawn hatched.
#extension GL_EXT_ray_query : require
#extension GL_GOOGLE_include_directive : require

#define CARD_BINDING_ROWS 3
#define CARD_BINDING_POOL 4
#define CARD_BINDING_LAYER_INFO 5
#define CARD_BINDING_ALPHA 6
#include "rt_cards.glsl"

layout(local_size_x = CARD_VIEW_GROUP, local_size_y = CARD_VIEW_GROUP) in;

layout(set = 0, binding = 0) uniform accelerationStructureEXT scene;
layout(set = 0, binding = 1) uniform sampler2D depth_tex;
layout(set = 0, binding = 2, rgba16f) uniform image2D color;
layout(set = 0, binding = 7, std430) buffer Counters {
    uint counters[];
};

layout(push_constant) uniform Push {
    vec4 proj;   // CameraMotion's: x scale, y scale, z scale, z offset
    vec2 jitter; // render pixels, x right, y down
    uvec2 size;
    uint mode;   // CARD_VIEW_OVERLAY, CARD_VIEW_ALPHA, CARD_VIEW_UV
    uint flags;
    uint unused0;
    uint unused1;
    vec4 unused2;
} pc;

shared uint group_counts[CARD_VIEW_COUNTERS];
// Each pixel's card candidate (its slot, 0: none or no data) and raw coordinates, for the
// neighbours' footprint (CardViewLod).
shared uint group_slot[CARD_VIEW_GROUP * CARD_VIEW_GROUP];
shared vec2 group_raw[CARD_VIEW_GROUP * CARD_VIEW_GROUP];

// CardViewClass
uint viewClass(bool sky, bool card, float t_card, uint status, float depth_t) {
    if (sky) {
        return CARD_VIEW_SKY;
    }
    if (!card) {
        return CARD_VIEW_NO_CARD;
    }
    const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
    if (depth_t < t_card - tol) {
        return CARD_VIEW_NO_CARD;
    }
    if (status == CARD_NO_DATA) {
        return CARD_VIEW_NO_DATA;
    }
    const bool game_kept = depth_t <= t_card + tol;
    const bool ray_kept = status == CARD_KEPT;
    if (game_kept) {
        return ray_kept ? CARD_VIEW_AGREE_KEPT : CARD_VIEW_RAY_DROPPED_GAME_KEPT;
    }
    return ray_kept ? CARD_VIEW_RAY_KEPT_GAME_DROPPED : CARD_VIEW_AGREE_DROPPED;
}

// CardViewLod
float viewLod(vec2 dx, bool has_x, vec2 dy, bool has_y) {
    const float f = max(has_x ? length(dx) : 0.0, has_y ? length(dy) : 0.0);
    if (!(has_x || has_y) || !(f > 0.0)) {
        return 0.0;
    }
    return log2(f * float(CARD_LAYER_SIZE));
}

// CardViewExcluded
uint viewExcluded(uint row_flags, float lod) {
    if ((row_flags & CARD_ROW_SUN) != 0u) {
        return CARD_VIEW_SUN_CARD;
    }
    if ((row_flags & CARD_ROW_DITHER) != 0u) {
        return CARD_VIEW_DITHERED;
    }
    return lod > float(CARD_LAYER_MIPS - 1) ? CARD_VIEW_COARSE : 0u;
}

void main() {
    const uint local = gl_LocalInvocationIndex;
    if (local < uint(CARD_VIEW_COUNTERS)) {
        group_counts[local] = 0u;
    }

    // 1. The ray, its card candidate, and that candidate's raw coordinates (level 0 test).
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const bool inside = p.x < int(pc.size.x) && p.y < int(pc.size.y);
    bool sky = true;
    bool card = false;
    float t_card = 0.0;
    float depth_t = 0.0;
    uint best_slot = 0u, best_primitive = 0u;
    vec2 best_bary = vec2(0.0);
    CardResult first = CardResult(CARD_NO_DATA, 0.0, vec2(0.0), vec2(0.0), 0u);
    if (inside) {
        const float depth = texelFetch(depth_tex, p, 0).r;
        sky = depth >= 1.0;
        if (!sky) {
            // camera_motion.comp's reconstruction: ndc +y down, the jitter taken out.
            const vec2 size = vec2(pc.size);
            const vec2 scene_uv = (vec2(p) + 0.5) / size - pc.jitter / size;
            const vec2 ndc = scene_uv * 2.0 - 1.0;
            const float z = pc.proj.w / min(depth - pc.proj.z, -1e-8);
            const vec3 point = vec3(ndc.x * z / pc.proj.x, ndc.y * z / pc.proj.y, z);
            depth_t = length(point);
            const vec3 dir = point / max(depth_t, 1e-6);
            const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
            rayQueryEXT query;
            rayQueryInitializeEXT(query, scene, gl_RayFlagsNoOpaqueEXT, 0xffu, vec3(0.0), 0.0, dir,
                                  depth_t + 2.0 * tol);
            float best_t = 1e30;
            while (rayQueryProceedEXT(query)) {
                if (rayQueryGetIntersectionTypeEXT(query, false) !=
                    gl_RayQueryCandidateIntersectionTriangleEXT) {
                    continue;
                }
                const uint slot = rayQueryGetIntersectionInstanceCustomIndexEXT(query, false);
                if (slot == 0u) {
                    rayQueryConfirmIntersectionEXT(query);
                    continue;
                }
                const float t = rayQueryGetIntersectionTEXT(query, false);
                if (t < best_t) {
                    best_t = t;
                    best_slot = slot;
                    best_primitive = rayQueryGetIntersectionPrimitiveIndexEXT(query, false);
                    best_bary = rayQueryGetIntersectionBarycentricsEXT(query, false);
                }
            }
            float opaque_t = 1e30;
            if (rayQueryGetIntersectionTypeEXT(query, true) ==
                gl_RayQueryCommittedIntersectionTriangleEXT) {
                opaque_t = rayQueryGetIntersectionTEXT(query, true);
            }
            card = best_t < opaque_t;
            if (card) {
                t_card = best_t;
                first = cardTestLod(best_slot, best_primitive, best_bary, 0.0);
            }
        }
    }
    const bool has_raw = card && first.status != CARD_NO_DATA;
    group_slot[local] = has_raw ? best_slot : 0u;
    group_raw[local] = first.raw;
    barrier();

    // 2. The game's mip from the neighbours on the same card (the other pixel of this pixel's
    // pair in x and in y: always in the group), the test at that level, the class.
    if (inside) {
        CardResult result = first;
        uint excluded = 0u;
        if (has_raw) {
            const uvec2 l = gl_LocalInvocationID.xy;
            const uint nx = l.y * CARD_VIEW_GROUP + (l.x ^ 1u);
            const uint ny = (l.y ^ 1u) * CARD_VIEW_GROUP + l.x;
            const bool has_x = group_slot[nx] == best_slot;
            const bool has_y = group_slot[ny] == best_slot;
            const float lod = viewLod(group_raw[nx] - first.raw, has_x, group_raw[ny] - first.raw,
                                      has_y);
            result = cardTestLod(best_slot, best_primitive, best_bary,
                                 clamp(lod, 0.0, float(CARD_LAYER_MIPS - 1)));
            excluded = viewExcluded(result.flags, lod);
        }
        const uint cls = viewClass(sky, card, t_card, result.status, depth_t);
        // CardViewCounter: a judged class of an excluded card counts as its reason.
        const bool judged = cls >= CARD_VIEW_AGREE_KEPT && cls <= CARD_VIEW_RAY_DROPPED_GAME_KEPT;
        const uint counter = judged && excluded != 0u ? excluded : cls;
        atomicAdd(group_counts[CARD_VIEW_PIXELS], 1u);
        atomicAdd(group_counts[counter], 1u);
        if (card) {
            atomicAdd(group_counts[CARD_VIEW_CARD_HITS], 1u);
        }

        vec4 c = imageLoad(color, p);
        const float light = max(dot(c.rgb, vec3(0.3333)), 0.2);
        if (pc.mode == CARD_VIEW_OVERLAY) {
            vec3 tint = vec3(0.0);
            float w = 0.0;
            if (cls == CARD_VIEW_AGREE_KEPT) {
                tint = vec3(0.0, 1.0, 0.0);
                w = 0.35;
            } else if (cls == CARD_VIEW_AGREE_DROPPED) {
                tint = vec3(0.0, 0.8, 0.8);
                w = 0.2;
            } else if (cls == CARD_VIEW_RAY_KEPT_GAME_DROPPED) {
                tint = vec3(1.0, 0.0, 0.0);
                w = 0.6;
            } else if (cls == CARD_VIEW_RAY_DROPPED_GAME_KEPT) {
                tint = vec3(1.0, 0.0, 1.0);
                w = 0.6;
            } else if (cls == CARD_VIEW_NO_DATA) {
                tint = vec3(0.0, 0.2, 1.0);
                w = 0.5;
            }
            if (excluded != 0u && judged && ((p.x + p.y) & 1) != 0) {
                w = 0.0; // not judged: hatched (every other pixel keeps the game's colour)
            }
            c.rgb = mix(c.rgb, tint * light * 2.0, w);
        } else if (pc.mode == CARD_VIEW_ALPHA) {
            c.rgb = card && result.status != CARD_NO_DATA ? vec3(result.alpha) * light * 2.0
                                                          : c.rgb * 0.25;
        } else if (pc.mode == CARD_VIEW_UV) {
            c.rgb = card && result.status != CARD_NO_DATA ? vec3(result.uv, 0.0) * light * 2.0
                                                          : c.rgb * 0.25;
        }
        imageStore(color, p, c);
    }
    barrier();
    if (local < uint(CARD_VIEW_COUNTERS)) {
        const uint n = group_counts[local];
        if (n != 0u) {
            atomicAdd(counters[local], n);
        }
    }
}
""",
    R + "rt_card_layers.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the pure parts of the card alpha layers, the card table and the
// debug view (BB_RT_CARD_ALPHA=2; CardAlpha in vk_card_alpha.h, RtShadow's rows). No Vulkan, no
// AmdGpu: tests/test_rt_card_layers.cpp builds this alone.
//
// What a layer is: one game texture's alpha lane (the view lane the cut-out test reads), copied
// by the GPU (rt_card_alpha_fill.comp, sampling the game's own image view, so BC1, BC3, BC7 and
// sRGB views are decoded by the hardware as for the game) into a slice of one R8 2D array:
// CARD_LAYER_SIZE square, CARD_LAYER_MIPS levels, CARD_LAYER_COUNT slices. Why one array and not
// the game's textures themselves: a ray in stage 4 meets any card of the scene, and a descriptor
// array of the game's views would change with every texture the game streams in or out, under
// rays still in flight; the array never changes its views, a layer's content changes only by a
// fill recorded in stream order. Why 256 square and R8: a ray thresholds a bilinear-filtered
// alpha, which keeps smooth contours at 4-8 mm a texel on a 1-2 m card, well inside the soft lamp
// penumbra (0.1 m); one byte is all a test needs. Bytes: below (CardLayersBytes).
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>
#include <type_traits>

#include "../host_shaders/rt_card_layers_layout.h"
#include "rt_card_uv.h"

namespace Vulkan {

// ---- Sizes

inline constexpr std::uint32_t CardLayerSize = CARD_LAYER_SIZE;
inline constexpr std::uint32_t CardLayerMips = CARD_LAYER_MIPS;
inline constexpr std::uint32_t CardLayerCount = CARD_LAYER_COUNT;
inline constexpr std::uint32_t CardNoLayer = 0xffffffffu;
/// Bytes of one R8 layer of `size` square with `mips` levels.
[[nodiscard]] constexpr std::uint64_t CardLayerBytesAt(std::uint32_t size, std::uint32_t mips) noexcept {
    std::uint64_t bytes = 0;
    for (std::uint32_t k = 0; k < mips; ++k) {
        const std::uint64_t s = std::max<std::uint32_t>(1u, size >> k);
        bytes += s * s;
    }
    return bytes;
}
inline constexpr std::uint64_t CardLayerBytes = CardLayerBytesAt(CardLayerSize, CardLayerMips);
inline constexpr std::uint64_t CardLayersBytes = CardLayerBytes * CardLayerCount;
inline constexpr std::uint64_t CardRowsBytes = std::uint64_t(CARD_ROWS) * CARD_ROW_BYTES;
inline constexpr std::uint64_t CardLayerInfoBytes = std::uint64_t(CardLayerCount) * 4u;
/// Fills recorded a frame at most (each one dispatch of CardLayerSize^2 threads, about 0.01 ms
/// on a current GPU; the source's few hundred KB read once): a scene's first frame with 100
/// new cards takes 13 frames to fill them all; meanwhile those cards are cards without data.
inline constexpr std::uint32_t CardFillsPerFrame = 8;
/// Card rows written by one PrepareScene call at most (one vkCmdUpdateBuffer each, captured in
/// the recorded closure: 64 * 36 bytes); the rest wait for the next call.
inline constexpr std::uint32_t CardRowUpdatesPerCall = 64;
/// The debug view's counters are copied and printed every this many view frames: a u32 counter
/// sums at most one a pixel a frame, and 120 frames of an 8K render (7680 x 4320) still fit.
inline constexpr std::uint32_t CardViewLineFrames = 120;
static_assert(std::uint64_t(7680) * 4320 * CardViewLineFrames < (std::uint64_t(1) << 32),
              "the view's u32 counters would overflow");
static_assert(CardSlotsMost == CARD_ROWS, "one card row a card slot");
static_assert(CardLayerCount - 1 <= CARD_ROW_LAYER_MASK, "a layer index fits its row bits");

// ---- The knob's level and the debug view's knob

/// BB_RT_CARD_ALPHA=2 (CardAlphaLayers, rt_card_uv.h): stage 2's UVs and this stage's layers,
/// card table and instance custom index. BB_RT_CARD_ALPHA_VIEW (read once, environment only,
/// never saved): unset or "0" off; "1" the overlay (agree/disagree tints over the picture), "2"
/// the alpha a ray reads (grey), "3" the coordinates a ray reads (fract u red, fract v green).
/// Only with BB_RT_CARD_ALPHA=2.
[[nodiscard]] constexpr std::uint32_t ReadCardView(const char* text) noexcept {
    return text && text[0] >= '1' && text[0] <= char('0' + CARD_VIEW_MODES) && text[1] == '\0'
               ? std::uint32_t(text[0] - '0')
               : 0u;
}
/// Set but not one of "0" to "3": said once in the log, as off.
[[nodiscard]] constexpr bool CardViewMisread(const char* text) noexcept {
    return text && !(text[0] == '0' && text[1] == '\0') && ReadCardView(text) == 0;
}

// ---- Which textures a layer can hold

/// Why a card has no layer (counted; the 600-frame line prints them).
enum class CardLayerMiss : std::uint8_t {
    None,
    NoSource,    ///< the draw's binding of the alpha texture is not in the binding memo
    NotTwoD,     ///< not a plain 2D view (array, cube, 3D, 1D)
    Multisample, ///< a multisampled image
    Conversion,  ///< the T# asks for a number conversion the shader does by hand
    Format,      ///< not Unorm, Srgb or Float (Snorm and the integer formats are not alpha)
    Constant,    ///< the test reads a constant lane (0 or 1): no texture to copy
    NoLane,      ///< no view lane reads the stored channel the test reads
    Depth,       ///< the image is a depth image
    Full,        ///< all layers in use this frame or the last
    Gone,        ///< the image was unregistered before its fill was recorded
    Count,
};
[[nodiscard]] constexpr const char* CardLayerMissName(CardLayerMiss m) noexcept {
    constexpr std::array<const char*, std::size_t(CardLayerMiss::Count)> names{
        "none", "no source", "not 2D", "multisampled", "conversion", "format", "constant lane",
        "no lane", "depth", "full", "gone"};
    return std::size_t(m) < names.size() ? names[std::size_t(m)] : "?";
}

/// The T# facts the checks need, as numbers (AmdGpu::Image's GetType(), GetNumberFmt(),
/// GetNumberConversion(), DstSelect() r, g, b, a): the pure part needs no AmdGpu header.
struct CardTexFacts {
    std::uint32_t type = 0;       ///< AmdGpu::ImageType: 9 Color2D, 14 Color2DMsaa
    std::uint32_t num_format = 0; ///< AmdGpu::NumberFormat: 0 Unorm, 7 Float, 9 Srgb
    std::uint32_t conversion = 0; ///< AmdGpu::NumberConversion: 0 None
    std::array<std::uint8_t, 4> dst_select{4, 5, 6, 7};
};
inline constexpr std::uint32_t CardTypeColor2D = 9;
inline constexpr std::uint32_t CardTypeColor2DMsaa = 14;
inline constexpr std::uint32_t CardTypeColor2DMsaaArray = 15;

/// The view lane (0-3) whose DstSelect is `stored` (AmdGpu::CompSwizzle 4-7), or 0xff. The fill
/// samples the game's own view, which applies DstSelect as its component mapping (ImageViewInfo
/// for a sampled image): that lane reads what the game's test reads. Two lanes with the same
/// select read the same value; the lowest is taken.
[[nodiscard]] constexpr std::uint8_t CardViewLane(const std::array<std::uint8_t, 4>& dst_select,
                                                  std::uint8_t stored) noexcept {
    if (stored < 4 || stored > 7) {
        return 0xff;
    }
    for (std::uint8_t lane = 0; lane < 4; ++lane) {
        if (dst_select[lane] == stored) {
            return lane;
        }
    }
    return 0xff;
}
/// Whether a layer can hold this texture's alpha (None), and the view lane to copy.
[[nodiscard]] constexpr CardLayerMiss CardSourceCheck(const CardTexFacts& f, std::uint8_t stored,
                                                      std::uint8_t& lane) noexcept {
    lane = 0xff;
    if (f.type == CardTypeColor2DMsaa || f.type == CardTypeColor2DMsaaArray) {
        return CardLayerMiss::Multisample;
    }
    if (f.type != CardTypeColor2D) {
        return CardLayerMiss::NotTwoD;
    }
    if (f.conversion != 0) {
        return CardLayerMiss::Conversion;
    }
    if (f.num_format != 0 && f.num_format != 7 && f.num_format != 9) {
        return CardLayerMiss::Format;
    }
    if (stored == 0 || stored == 1) {
        return CardLayerMiss::Constant;
    }
    lane = CardViewLane(f.dst_select, stored);
    return lane == 0xff ? CardLayerMiss::NoLane : CardLayerMiss::None;
}

/// A layer's key: the whole T# and the lane. Two T#s of one image that differ elsewhere (another
/// base level, another swizzle) are two layers: a little waste, never a wrong alpha. Never 0.
[[nodiscard]] constexpr std::uint64_t CardLayerKey(const std::array<std::uint32_t, 8>& tsharp,
                                                   std::uint8_t lane) noexcept {
    const std::uint64_t h = CardHashWords(tsharp, 0x52363243ull ^ lane);
    return h != 0 ? h : 1u;
}

/// The fill's source level and taps for a destination level of `dst` square. The level comes
/// from the SMALLER side's ratio (source texels a destination texel): log2(ratio) - 1, clamped to
/// the source's levels, or 0 when that side is no larger than `dst`, so neither axis is read
/// coarser than it needs (a 2048x128 source keeps its 128 rows; taking the larger side would
/// read v at 32 rows). At that level each axis covers `texels` source texels a destination
/// texel, read with that many bilinear taps (rounded up, 1 to CARD_FILL_MAX_TAPS), evenly spread
/// over the destination texel: a box filter of the footprint on each axis. A square source
/// larger than `dst` gets 2 x 2 taps a quarter of a destination texel from its centre, as
/// before; a source no larger, one tap. rt_card_alpha_fill.comp computes the same.
struct CardFillTaps {
    float lod = 0.0f;
    std::uint32_t taps_u = 1;
    std::uint32_t taps_v = 1;
};
[[nodiscard]] inline std::uint32_t CardFillAxisTaps(float texels) {
    // 1e-3: a ratio of exactly 2 (a power of two) is 2 taps, not 3 by rounding.
    const float n = std::ceil(texels - 1e-3f);
    return std::uint32_t(std::clamp(n, 1.0f, float(CARD_FILL_MAX_TAPS)));
}
[[nodiscard]] inline CardFillTaps CardFillLod(std::uint32_t src_w, std::uint32_t src_h,
                                              std::uint32_t src_levels, std::uint32_t dst) {
    const float d = float(std::max(dst, 1u));
    const float ratio_u = float(std::max(src_w, 1u)) / d;
    const float ratio_v = float(std::max(src_h, 1u)) / d;
    const float small = std::min(ratio_u, ratio_v);
    const float top = float(std::max(src_levels, 1u) - 1u);
    CardFillTaps t;
    t.lod = small <= 1.0f ? 0.0f : std::clamp(std::log2(small) - 1.0f, 0.0f, top);
    const float scale = std::exp2(-t.lod);
    t.taps_u = CardFillAxisTaps(ratio_u * scale);
    t.taps_v = CardFillAxisTaps(ratio_v * scale);
    return t;
}

// ---- The layer table (fixed size: nothing is allocated)

enum class CardLayerState : std::uint8_t { Free, Wanted, Ready };
/// The image a layer is filled from: the texture cache's ImageId (as a number), its image_uid,
/// and Image::write_seq (bumped by every write access and backing swap: unchanged, the image
/// holds what it held). A changed source (streamed in, replaced, written) fills the layer again;
/// the old fill stays readable meanwhile (a streamed texture keeps its alpha).
struct CardLayerSource {
    std::uint32_t image = 0;
    std::uint64_t uid = 0;
    std::uint64_t write_seq = 0;
    [[nodiscard]] constexpr bool operator==(const CardLayerSource&) const noexcept = default;
};
struct CardLayer {
    std::uint64_t key = 0;
    CardLayerState state = CardLayerState::Free;
    bool refill = false; ///< Ready, and the source changed since its fill
    bool queued = false;
    std::uint8_t lane = 0;
    std::uint32_t gen = 0; ///< bumped each time the layer is given to a key
    std::uint64_t last_used = 0;
    CardLayerSource source; ///< as the last draw bound it
    CardLayerSource filled; ///< as the last fill read it
};
struct CardLayerGet {
    std::uint32_t layer = CardNoLayer;
    std::uint32_t gen = 0;
    bool given = false; ///< the key had no layer: this one was given to it now
    bool taken = false; ///< and it was taken from another key (least recently used)
    /// The key's layer was READY but now answers another image (another ImageId or uid: the
    /// address may hold another texture with the same T# words): it is no longer READY until
    /// its refill, so no ray reads the old image's alpha for the new one.
    bool dropped = false;
};

class CardLayerTable {
public:
    /// The key's layer as of `frame`, given one when it has none: a free layer first, else the
    /// least recently used one not used this frame or the last (a ray of either may still be
    /// meant for it; the row's generation check keeps a reused layer from being read for its old
    /// key). CardNoLayer when all are in use. The layer is queued for a fill when it holds none
    /// or its source changed.
    CardLayerGet Get(std::uint64_t key, std::uint8_t lane, const CardLayerSource& source,
                     std::uint64_t frame) noexcept {
        CardLayerGet out;
        std::uint32_t found = CardNoLayer, free = CardNoLayer, oldest = CardNoLayer;
        // The hint first: a card's draws (the camera pass and every cascade, hundreds to
        // thousands a frame in a plant scene) find their key without the scan of 128 layers.
        // A hint may be stale (its layer went to another key): it is only taken when it holds
        // the key.
        const std::uint32_t hinted = std::uint32_t(hint[key % CardLayerHints]) - 1u;
        if (hinted < CardLayerCount && layers[hinted].state != CardLayerState::Free &&
            layers[hinted].key == key) {
            found = hinted;
            ++hint_hits;
        }
        for (std::uint32_t i = 0; found == CardNoLayer && i < CardLayerCount; ++i) {
            const CardLayer& l = layers[i];
            if (l.state != CardLayerState::Free && l.key == key) {
                found = i;
                break;
            }
            if (l.state == CardLayerState::Free) {
                free = free == CardNoLayer ? i : free;
            } else if (l.last_used + 1 < frame &&
                       (oldest == CardNoLayer || l.last_used < layers[oldest].last_used)) {
                oldest = i;
            }
        }
        if (found == CardNoLayer) {
            found = free != CardNoLayer ? free : oldest;
            if (found == CardNoLayer) {
                return out;
            }
            CardLayer& l = layers[found];
            out.given = true;
            out.taken = l.state != CardLayerState::Free;
            l.key = key;
            l.lane = lane;
            l.state = CardLayerState::Wanted;
            l.refill = false;
            l.gen = (l.gen + 1) & CARD_LAYER_GEN_MASK;
            l.filled = {};
        }
        hint[key % CardLayerHints] = std::uint8_t(found + 1);
        CardLayer& l = layers[found];
        l.last_used = frame;
        l.source = source;
        if (l.state == CardLayerState::Ready &&
            (l.filled.image != source.image || l.filled.uid != source.uid)) {
            // Another image answers the key: not READY (no data) until the refill. The
            // generation stays: rows of the key read the layer again once it is filled.
            l.state = CardLayerState::Wanted;
            l.refill = false;
            l.filled = {};
            out.dropped = true;
        } else if (l.state == CardLayerState::Ready && !(l.filled == source)) {
            // The same image, written since (streamed mips, a replacement in place): the old
            // fill stays readable until the refill.
            l.refill = true;
        }
        if ((l.state == CardLayerState::Wanted || l.refill) && !l.queued) {
            l.queued = true;
            queue[(head + count) % CardLayerCount] = std::uint16_t(found);
            ++count;
        }
        out.layer = found;
        out.gen = l.gen;
        return out;
    }
    /// The next layer to fill, in the order asked, or CardNoLayer.
    std::uint32_t NextFill() noexcept {
        while (count > 0) {
            const std::uint32_t i = queue[head];
            head = (head + 1) % CardLayerCount;
            --count;
            CardLayer& l = layers[i];
            l.queued = false;
            if (l.state == CardLayerState::Wanted || (l.state == CardLayerState::Ready && l.refill)) {
                return i;
            }
        }
        return CardNoLayer;
    }
    /// A fill of the layer from `as_read` was recorded: readable from the next reader on.
    void Filled(std::uint32_t i, const CardLayerSource& as_read) noexcept {
        CardLayer& l = layers[i];
        l.state = CardLayerState::Ready;
        l.filled = as_read;
        l.refill = !(as_read == l.source);
    }
    /// No fill could be recorded (the image went away): a Wanted layer waits for a draw that
    /// binds a living image (Get queues it again), a Ready one keeps its old fill.
    void FillFailed(std::uint32_t i) noexcept {
        layers[i].refill = false;
    }
    /// What the layer info buffer holds for the layer.
    [[nodiscard]] std::uint32_t Info(std::uint32_t i) const noexcept {
        const CardLayer& l = layers[i];
        return (l.gen & CARD_LAYER_GEN_MASK) | (l.state == CardLayerState::Ready ? CARD_LAYER_READY : 0u);
    }
    [[nodiscard]] const CardLayer& At(std::uint32_t i) const noexcept {
        return layers[i];
    }
    [[nodiscard]] std::uint32_t Count(CardLayerState s) const noexcept {
        return std::uint32_t(std::count_if(layers.begin(), layers.end(),
                                           [s](const CardLayer& l) { return l.state == s; }));
    }
    [[nodiscard]] std::uint32_t Queued() const noexcept {
        return count;
    }
    /// Gets answered by the hint (no scan), since the last call.
    std::uint64_t TakeHintHits() noexcept {
        const std::uint64_t n = hint_hits;
        hint_hits = 0;
        return n;
    }

private:
    static constexpr std::uint32_t CardLayerHints = 256; ///< 256 bytes, a key's layer + 1
    static_assert(CardLayerCount < 255, "a hint holds a layer + 1 in a byte");
    std::array<CardLayer, CardLayerCount> layers{};
    std::array<std::uint8_t, CardLayerHints> hint{};
    std::uint64_t hint_hits = 0;
    std::array<std::uint16_t, CardLayerCount> queue{};
    std::uint32_t head = 0;
    std::uint32_t count = 0;
};

// ---- The card table's rows

struct CardRow {
    bool ready = false;
    std::uint32_t pool_offset = 0;
    std::uint32_t triangles = 0;
    std::uint32_t layer = 0;
    std::uint32_t layer_gen = 0;
    CardOp op = CardOp::GreaterEqual;
    bool nonzero = false;
    bool dither = false; ///< the camera pass dithers with a coefficient not 0
    bool sun = false;    ///< the rule is the sun shadow pass card's
    std::uint32_t mode_u = CARD_UV_MODE_WRAP;
    std::uint32_t mode_v = CARD_UV_MODE_WRAP;
    std::uint32_t extra_u = 0; ///< CARD_AXIS_* bits
    std::uint32_t extra_v = 0;
    float reference = 0.0f;
    float offset_u = 0.0f;
    float offset_v = 0.0f;
    float dither_scale = 0.0f;
};
[[nodiscard]] constexpr std::array<std::uint32_t, CARD_ROW_WORDS> CardPackRow(const CardRow& r) noexcept {
    std::array<std::uint32_t, CARD_ROW_WORDS> w{};
    w[0] = r.pool_offset;
    w[1] = r.triangles;
    w[2] = (r.layer & CARD_ROW_LAYER_MASK) | (std::uint32_t(r.op) << CARD_ROW_OP_SHIFT) |
           (r.nonzero ? CARD_ROW_NONZERO : 0u) | ((r.mode_u & 3u) << CARD_ROW_MODE_U_SHIFT) |
           ((r.mode_v & 3u) << CARD_ROW_MODE_V_SHIFT) | (r.dither ? CARD_ROW_DITHER : 0u) |
           (r.sun ? CARD_ROW_SUN : 0u) | ((r.extra_u & 3u) << CARD_ROW_EXTRA_U_SHIFT) |
           ((r.extra_v & 3u) << CARD_ROW_EXTRA_V_SHIFT) | (r.ready ? CARD_ROW_READY : 0u);
    w[3] = std::bit_cast<std::uint32_t>(r.reference);
    w[4] = std::bit_cast<std::uint32_t>(r.offset_u);
    w[5] = std::bit_cast<std::uint32_t>(r.offset_v);
    w[6] = std::bit_cast<std::uint32_t>(r.dither_scale);
    w[7] = r.layer_gen & CARD_LAYER_GEN_MASK;
    return w;
}
[[nodiscard]] constexpr CardRow CardUnpackRow(const std::array<std::uint32_t, CARD_ROW_WORDS>& w) noexcept {
    CardRow r;
    r.pool_offset = w[0];
    r.triangles = w[1];
    r.layer = w[2] & CARD_ROW_LAYER_MASK;
    r.op = CardOp((w[2] >> CARD_ROW_OP_SHIFT) & 7u);
    r.nonzero = (w[2] & CARD_ROW_NONZERO) != 0;
    r.mode_u = (w[2] >> CARD_ROW_MODE_U_SHIFT) & 3u;
    r.mode_v = (w[2] >> CARD_ROW_MODE_V_SHIFT) & 3u;
    r.dither = (w[2] & CARD_ROW_DITHER) != 0;
    r.sun = (w[2] & CARD_ROW_SUN) != 0;
    r.extra_u = (w[2] >> CARD_ROW_EXTRA_U_SHIFT) & 3u;
    r.extra_v = (w[2] >> CARD_ROW_EXTRA_V_SHIFT) & 3u;
    r.ready = (w[2] & CARD_ROW_READY) != 0;
    r.reference = std::bit_cast<float>(w[3]);
    r.offset_u = std::bit_cast<float>(w[4]);
    r.offset_v = std::bit_cast<float>(w[5]);
    r.dither_scale = std::bit_cast<float>(w[6]);
    r.layer_gen = w[7];
    return r;
}
/// An axis's extra bits (CARD_AXIS_*) from the sampler's raw clamp mode (AmdGpu::ClampMode 0-7):
/// 3, 5, 7 mirror once; 4, 5, 6, 7 a border. 0-2 none (wrap, mirror, clamp to the last texel).
[[nodiscard]] constexpr std::uint32_t CardAxisExtra(std::uint32_t clamp_mode) noexcept {
    const bool mirror_once = clamp_mode == 3 || clamp_mode == 5 || clamp_mode == 7;
    const bool border = clamp_mode >= 4 && clamp_mode <= 7;
    return (mirror_once ? CARD_AXIS_MIRROR_ONCE : 0u) | (border ? CARD_AXIS_BORDER : 0u);
}
/// An entry's row: READY when its records are Ready (the expand pass passed its tick), its card
/// is not stale (the last draw of the card's pass still had card data) and the card has a layer
/// (CardDraw::layer, the layer + 1). The offset is the card's (the pool leaves it out). The
/// dither bit only where the coefficient is not 0 (8 of the 9 camera pass shaders have the
/// dither's form with cb[21] = 0: no dither); the sun bit where the card is the sun shadow
/// pass's (r54 prefers it: its reference may not be the camera pass's).
[[nodiscard]] constexpr CardRow CardRowFor(const CardUv& uv, std::uint32_t pool_offset,
                                           std::uint32_t triangles) noexcept {
    const CardDraw& d = uv.card;
    CardRow r;
    r.ready = uv.state == CardUvState::Ready && !CardStale(uv) && d.valid && d.layer != 0;
    r.pool_offset = pool_offset;
    r.triangles = triangles;
    r.layer = d.layer != 0 ? d.layer - 1 : 0;
    r.layer_gen = d.layer_gen;
    r.op = d.op;
    r.nonzero = d.nonzero;
    r.dither = d.dither && d.dither_scale != 0.0f;
    r.sun = !d.camera;
    r.mode_u = d.mode_u;
    r.mode_v = d.mode_v;
    r.extra_u = CardAxisExtra(d.clamp_u);
    r.extra_v = CardAxisExtra(d.clamp_v);
    r.reference = d.reference;
    r.offset_u = d.affine[2];
    r.offset_v = d.affine[3];
    r.dither_scale = d.dither_scale;
    return r;
}

// ---- What a ray does with a card candidate (rt_cards.glsl's cardTest, mirrored)

/// One axis's coordinate in [0, 1] as the game's sampler repeats it.
[[nodiscard]] inline float CardRepeat(float c, std::uint32_t mode) {
    if (mode == CARD_UV_MODE_WRAP) {
        return c - std::floor(c);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        const float m = c - 2.0f * std::floor(c * 0.5f);
        return m > 1.0f ? 2.0f - m : m;
    }
    return std::clamp(c, 0.0f, 1.0f);
}
/// The same with the axis's extra bits: mirror once mirrors about 0 before the clamp; a border
/// axis outside [0, 1] reads the border colour, which the row does not hold (`border` set: the
/// candidate is no data).
[[nodiscard]] inline float CardRepeatAxis(float c, std::uint32_t mode, std::uint32_t extra,
                                          bool& border) {
    if (mode == CARD_UV_MODE_CLAMP) {
        if ((extra & CARD_AXIS_MIRROR_ONCE) != 0) {
            c = std::abs(c);
        }
        if ((extra & CARD_AXIS_BORDER) != 0 && !(c >= 0.0f && c <= 1.0f)) {
            border = true;
        }
    }
    return CardRepeat(c, mode);
}
struct CardTestResult {
    std::uint32_t status = CARD_NO_DATA;
    float alpha = 0.0f; ///< texel alpha times the interpolated factor (CARD_KEPT/DROPPED only)
    float u = 0.0f, v = 0.0f; ///< the layer coordinates read
    float raw_u = 0.0f, raw_v = 0.0f; ///< before the repeat (smooth over the card: the view's mip)
};
/// The candidate at BLAS primitive `primitive` with barycentrics (b1, b2) of the card whose row
/// is `row`, the layer info word `info` of the row's layer, the pool, and `sample(layer, u, v,
/// lod)` (the layer at level `lod`, bilinear, linear between levels, clamp to edge). Corner
/// weights: 1 - b1 - b2, b1, b2. A lamp ray reads `lod` 0; the debug view the game's mip.
template <typename Sample>
[[nodiscard]] CardTestResult CardTest(const std::array<std::uint32_t, CARD_ROW_WORDS>& row,
                                      std::uint32_t info,
                                      std::span<const std::array<std::uint32_t, 4>> pool,
                                      std::uint32_t primitive, float b1, float b2, float lod,
                                      Sample&& sample) {
    CardTestResult out;
    const CardRow r = CardUnpackRow(row);
    if (!r.ready || info != (r.layer_gen | CARD_LAYER_READY) || primitive >= r.triangles ||
        std::size_t(r.pool_offset) + primitive >= pool.size()) {
        return out;
    }
    std::array<CardCorner, 3> c{};
    std::uint32_t flags = 0;
    CardUnpackTriangle(pool[r.pool_offset + primitive], c, flags);
    if ((flags & (CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_ALPHA_RANGE)) != 0) {
        return out;
    }
    const float b0 = 1.0f - b1 - b2;
    const float u = c[0].u * b0 + c[1].u * b1 + c[2].u * b2 + r.offset_u;
    const float v = c[0].v * b0 + c[1].v * b1 + c[2].v * b2 + r.offset_v;
    const float a = c[0].a * b0 + c[1].a * b1 + c[2].a * b2;
    bool border = false;
    out.raw_u = u;
    out.raw_v = v;
    out.u = CardRepeatAxis(u, r.mode_u, r.extra_u, border);
    out.v = CardRepeatAxis(v, r.mode_v, r.extra_v, border);
    if (border) {
        return out;
    }
    out.alpha = sample(r.layer, out.u, out.v, lod) * a;
    out.status = CardKeeps(out.alpha, r.reference, r.op, r.nonzero) ? CARD_KEPT : CARD_DROPPED;
    return out;
}

// ---- The debug view's classes (rt_card_view.comp mirrors this)

/// Which counter a pixel adds to. `sky`: no depth there. `card`: the ray met a card candidate
/// before the first opaque hit, at `t_card`, and the card test gave `status`. `depth_t`: the
/// distance of the game's depth along the ray. The game kept the card where its depth lies at
/// the candidate (within the tolerance), dropped it where the depth lies behind; a depth in front
/// is something the TLAS does not hold (not a caster): no card.
[[nodiscard]] constexpr std::uint32_t CardViewClass(bool sky, bool card, float t_card,
                                                    std::uint32_t status, float depth_t) noexcept {
    if (sky) {
        return CARD_VIEW_SKY;
    }
    if (!card) {
        return CARD_VIEW_NO_CARD;
    }
    const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
    if (depth_t < t_card - tol) {
        return CARD_VIEW_NO_CARD;
    }
    if (status == CARD_NO_DATA) {
        return CARD_VIEW_NO_DATA;
    }
    const bool game_kept = depth_t <= t_card + tol;
    const bool ray_kept = status == CARD_KEPT;
    if (game_kept) {
        return ray_kept ? CARD_VIEW_AGREE_KEPT : CARD_VIEW_RAY_DROPPED_GAME_KEPT;
    }
    return ray_kept ? CARD_VIEW_RAY_KEPT_GAME_DROPPED : CARD_VIEW_AGREE_DROPPED;
}
/// The layer level that matches the game's own mip at a pixel, from the raw coordinates of the
/// pixel's card candidate and of its neighbours in x and in y (each only when it is on the same
/// card with data; `has_x`, `has_y`): log2 of the larger footprint (texture coordinates a pixel)
/// times CARD_LAYER_SIZE. The game reads its source of S texels at log2(footprint * S); the
/// layer's level k has CARD_LAYER_SIZE / 2^k texels, the same count at k = log2(footprint *
/// CARD_LAYER_SIZE), whatever S is (exact for a square source; isotropic, as the hardware without
/// anisotropic filtering). Neither neighbour: 0 (level 0, judged). Not clamped: above
/// CARD_LAYER_MIPS - 1 the game reads coarser than the layers hold (CardViewExcluded).
[[nodiscard]] inline float CardViewLod(float du_x, float dv_x, bool has_x, float du_y, float dv_y,
                                       bool has_y) {
    const float fx = has_x ? std::sqrt(du_x * du_x + dv_x * dv_x) : 0.0f;
    const float fy = has_y ? std::sqrt(du_y * du_y + dv_y * dv_y) : 0.0f;
    const float f = std::max(fx, fy);
    if (!(has_x || has_y) || !(f > 0.0f)) {
        return 0.0f;
    }
    return std::log2(f * float(CARD_LAYER_SIZE));
}
/// Why a tested card pixel is left out of the GO line's judged classes (0: judged): the row holds
/// the sun shadow pass's rule (CARD_ROW_SUN), the camera pass dithers (CARD_ROW_DITHER), or the
/// game's mip there is coarser than the layers' last level.
[[nodiscard]] constexpr std::uint32_t CardViewExcluded(std::uint32_t row_flags, float lod) noexcept {
    if ((row_flags & CARD_ROW_SUN) != 0) {
        return CARD_VIEW_SUN_CARD;
    }
    if ((row_flags & CARD_ROW_DITHER) != 0) {
        return CARD_VIEW_DITHERED;
    }
    return lod > float(CARD_LAYER_MIPS - 1) ? CARD_VIEW_COARSE : 0u;
}
/// The counter a pixel adds to: its class, or the reason when a judged class is excluded.
[[nodiscard]] constexpr std::uint32_t CardViewCounter(std::uint32_t cls, std::uint32_t excluded) noexcept {
    const bool judged = cls >= CARD_VIEW_AGREE_KEPT && cls <= CARD_VIEW_RAY_DROPPED_GAME_KEPT;
    return judged && excluded != 0 ? excluded : cls;
}

// ---- The cut-out record in the pipeline cache ("CUT1", r54 open point 2)

/// A tagged tail part of a shader's cache record (Info::Serialize): the tag, a version, the
/// payload's size, then the payload's bytes (Info::Cutout, a trivially copyable struct). A
/// discarding pixel shader loaded with it needs no compile in play for the card data
/// (LoadPipelineStage). Another version or size is skipped whole (its size says how far) and the
/// shader compiles in play once, then is saved with this version.
/// The version is the part's format (CardCutoutFormat) and the analysis's version
/// (Shader::Optimization::CutoutAnalysisVersion, cutout_analysis.h): a matcher change that
/// keeps the struct's size (as r50b and r50c did) bumps the latter, so no record keeps a verdict
/// of the old matcher.
inline constexpr std::uint32_t CardCutoutTag = 0x31545543u; // "CUT1"
inline constexpr std::uint32_t CardCutoutFormat = 1;
[[nodiscard]] constexpr std::uint32_t CardCutoutVersion(std::uint32_t analysis) noexcept {
    return (CardCutoutFormat << 16) | (analysis & 0xffffu);
}
inline constexpr std::size_t CardCutoutHeader = 12;
template <typename T>
inline constexpr std::size_t CardCutoutBytes = CardCutoutHeader + sizeof(T);
/// The part of `value`, with its padding bytes (offsets in T, `padding`) written as 0: a record's
/// bytes then depend on its values alone (the struct's padding holds whatever was there).
template <typename T>
void CardCutoutEncode(const T& value, std::uint32_t version, std::span<const std::size_t> padding,
                      std::uint8_t* out) noexcept {
    static_assert(std::is_trivially_copyable_v<T>);
    const std::uint32_t head[3] = {CardCutoutTag, version, std::uint32_t(sizeof(T))};
    std::memcpy(out, head, sizeof(head));
    std::memcpy(out + sizeof(head), &value, sizeof(T));
    for (const std::size_t p : padding) {
        if (p < sizeof(T)) {
            out[sizeof(head) + p] = 0;
        }
    }
}
/// At a part starting with CardCutoutTag: the bytes the part takes (0: not a whole part, the
/// record is broken) and, when its version is `version` and its size T's, its payload's start in
/// `payload` (else null: skipped).
template <typename T>
[[nodiscard]] std::size_t CardCutoutPart(const std::uint8_t* in, std::size_t avail,
                                         std::uint32_t version,
                                         const std::uint8_t*& payload) noexcept {
    payload = nullptr;
    if (avail < CardCutoutHeader) {
        return 0;
    }
    std::uint32_t head[3];
    std::memcpy(head, in, sizeof(head));
    if (head[0] != CardCutoutTag || head[2] > avail - CardCutoutHeader) {
        return 0;
    }
    if (head[1] == version && head[2] == sizeof(T)) {
        payload = in + CardCutoutHeader;
    }
    return CardCutoutHeader + head[2];
}
/// Whether a payload's bytes hold a cut-out record this engine could have written: every enum in
/// its range, every bool 0 or 1 (a bool of another value read from memory is undefined
/// behaviour). C is Info::Cutout (or a test's stand-in with the same members and enums).
template <typename C>
[[nodiscard]] bool CardCutoutBytesValid(const std::uint8_t* p) noexcept {
    const auto at = [p](std::size_t offset) { return p[offset]; };
    const bool enums = at(offsetof(C, verdict)) <= std::uint8_t(C::Verdict::Other) &&
                       at(offsetof(C, detail)) < std::uint8_t(C::Detail::Count) &&
                       at(offsetof(C, op)) <= std::uint8_t(C::Op::NotEqual) &&
                       at(offsetof(C, ref_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, ref2_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, uv_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, dither_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, layer)) <= std::uint8_t(C::Layer::Other);
    const bool bools = at(offsetof(C, uv_by_constant)) <= 1 && at(offsetof(C, uv_unrecorded)) <= 1 &&
                       at(offsetof(C, texel_offset)) <= 1 && at(offsetof(C, dither)) <= 1 &&
                       at(offsetof(C, nonzero)) <= 1;
    return enums && bools;
}

} // namespace Vulkan
""",
    R + "vk_card_alpha.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card alpha layers and the card debug view (BB_RT_CARD_ALPHA=2;
// docs/rt_card_alpha.md, "Stage 3"). The pure parts are in rt_card_layers.h.
//
// A cut-out draw's card (CardDraw, EffectsCaptureDraw) is given a layer of one R8 2D array: the
// draw's alpha texture, the image this draw's own texture binding found (Rasterizer's
// DrawContext::card_bound, from either binding path), is copied into it by the GPU (RecordFills,
// from RtShadow::PrepareCapture: before any reader of the scene) through the game's own image
// view. RtShadow writes the card's row (the pool offset, the layer, the rule) and gives the TLAS
// instance its card slot as custom index. The debug view (BB_RT_CARD_ALPHA_VIEW) traces the
// camera's rays through that chain and compares each card candidate's decision with what the
// game drew. Nothing of a shadow reads any of it yet (stage 4). With the knob unset or 1 the
// rasterizer makes no CardAlpha (Wanted) and no draw calls in.
#pragma once

#include <array>
#include <atomic>

#include "common/types.h"
#include "video_core/renderer_vulkan/rt_card_layers.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image_view.h"
#include "video_core/texture_cache/types.h"

namespace AmdGpu {
struct Image;
}
namespace Shader {
struct ImageResource;
}
namespace VideoCore {
class TextureCache;
struct Image;
} // namespace VideoCore

namespace Vulkan {

class CameraMotion;
class Instance;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

/// The CUT1 cache parts (vk_pipeline_serialization.cpp): discarding pixel shaders the warm-up
/// took with their cut-out record, and those it left to compile in play (no part, or the log
/// knob wants the IR). Printed with the 600-frame line.
struct CardCacheCounts {
    u64 loaded = 0;
    u64 refused = 0;
};
CardCacheCounts CardCacheTally();
void NoteCardCutoutLoaded();
void NoteCardCutoutRefused();

class CardAlpha {
public:
    /// BB_RT_CARD_ALPHA=2 (both knobs are read once, here or at the first call): the rasterizer
    /// makes a CardAlpha only then. Otherwise a view knob that is set is said off, once.
    [[nodiscard]] static bool Wanted();
    CardAlpha(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
              Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
              RtShadow& rt_shadow);
    ~CardAlpha();
    CardAlpha(const CardAlpha&) = delete;
    CardAlpha& operator=(const CardAlpha&) = delete;

    /// BB_RT_CARD_ALPHA=2 and the layers were made.
    [[nodiscard]] bool On() const noexcept {
        return made;
    }
    /// And BB_RT_CARD_ALPHA_VIEW names a mode.
    [[nodiscard]] bool ViewOn() const noexcept {
        return made && view_mode != 0;
    }
    /// A cut-out draw's card (valid) and the image its binding of the alpha texture found
    /// (`image`, `uid`): the card's layer + 1 and the layer's generation into card.layer and
    /// card.layer_gen (0: none, counted why). Render thread, after BindResources.
    void NoteDraw(CardDraw& card, const AmdGpu::Image& sharp, const Shader::ImageResource& res,
                  VideoCore::ImageId image, u64 uid);
    /// The draw's binding of the alpha texture is not known (no image found, or the binding
    /// record is another stage's): no layer.
    void NoteNoSource(CardDraw& card);
    /// The upscaler is off: the view has no place in the frame (EffectsBeforeUpscaler). Said
    /// once when the view knob is set.
    void NoSceneHooks();
    /// The fills asked for, up to CardFillsPerFrame a frame, and the layer info when it changed
    /// (RtShadow::PrepareCapture, outside rendering).
    void RecordFills();
    /// The debug view over the scene colour before the upscaler (EffectsBeforeUpscaler).
    void View(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
    void OnFrameEnd();

    /// What a reader of the layers binds (stage 4: rt_cards.glsl's CARD_BINDING_ALPHA and
    /// CARD_BINDING_LAYER_INFO). The sampler reads every level (linear between them): a lamp ray
    /// asks level 0, the view the game's mip, stage 6 levels 1 and 2.
    struct Bindings {
        vk::ImageView layers;
        vk::Sampler sampler;
        vk::Buffer info;
    };
    [[nodiscard]] Bindings ReaderBindings() const noexcept {
        return {*layers_view, *layer_sampler, info_buffer.buffer};
    }

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    bool Make();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    /// What a fill did: recorded; not yet (the image holds CPU writes not uploaded: the next
    /// draw that binds it uploads them and asks again); gone (the image is not registered).
    enum class FillResult { Recorded, NotYet, Gone };
    FillResult Fill(u32 layer);
    bool MakeView();
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    void Miss(CardDraw& card, CardLayerMiss why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;

    u32 level = 0;     ///< BB_RT_CARD_ALPHA, read once (Shader::Optimization::CardAlphaLevel)
    u32 view_mode = 0; ///< BB_RT_CARD_ALPHA_VIEW, read once
    bool made = false;
    bool view_failed = false;
    u64 frame = 2; ///< CardLayerTable wants "this frame and the last" to be > 0
    u64 fills_frame = 0;
    u32 fills_left = 0;
    bool info_dirty = true;

    CardLayerTable table;
    /// The view a layer's fill samples: the game's view of the texture (ImageViewInfo of the
    /// draw's T# and resource), taken when the layer is queued.
    std::array<VideoCore::ImageViewInfo, CardLayerCount> fill_view{};

    vk::Image layers_image{};
    VmaAllocation layers_allocation{};
    vk::UniqueImageView layers_view;
    std::array<vk::UniqueImageView, CardLayerMips> level_views;
    vk::UniqueSampler layer_sampler;  ///< linear, clamp to edge, every level (readers)
    vk::UniqueSampler source_sampler; ///< linear, linear between levels (the fill's source)
    vk::UniqueSampler depth_sampler;
    Buffer info_buffer;
    vk::UniqueDescriptorSetLayout fill_set;
    vk::UniquePipelineLayout fill_layout;
    vk::UniquePipeline fill_pipeline;

    // The debug view: its pass, its counters (CARD_VIEW_COUNTERS uints, copied to the readback
    // every CardViewLineFrames frames with a view), and the views of the scene's images.
    vk::UniqueDescriptorSetLayout view_set;
    vk::UniquePipelineLayout view_layout;
    vk::UniquePipeline view_pipeline;
    Buffer view_counters, view_readback;
    u32 view_frames = 0;
    u32 view_copied_frames = 0; ///< the view frames the copy in flight sums
    u64 view_readback_tick = 0;
    bool view_readback_pending = false;
    bool view_said_no_hooks = false;
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;

    struct Stats {
        u64 draws = 0, given = 0, taken = 0, fills = 0, refills = 0, failed_fills = 0;
        u64 dirty_waits = 0; ///< fills put off: the image held CPU writes not uploaded
        u64 dropped = 0;     ///< READY layers whose key another image now answers
        u64 views = 0, view_skipped = 0;
        std::array<u64, std::size_t(CardLayerMiss::Count)> miss{};
    } stats;
    u32 line_frames = 0;
};

} // namespace Vulkan
""",
    R + "vk_card_alpha.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card alpha layers and the card debug view (vk_card_alpha.h).

#include "video_core/renderer_vulkan/vk_card_alpha.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "shader_recompiler/info.h"
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "video_core/amdgpu/resource.h"
#include "video_core/host_shaders/rt_card_alpha_fill_comp.h"
#include "video_core/host_shaders/rt_card_view_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {

namespace {

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ShaderWrite = vk::AccessFlagBits2::eShaderWrite;
constexpr auto ReadWrite = ShaderRead | ShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u32 LineFrames = 600;
constexpr vk::ImageSubresourceRange LayersRange{vk::ImageAspectFlagBits::eColor, 0, CardLayerMips,
                                                0, CardLayerCount};

std::atomic<u64> cutout_loaded{0};
std::atomic<u64> cutout_refused{0};

// BB_RT_CARD_ALPHA_VIEW, read once (the first caller: Wanted, at the rasterizer's start).
u32 ViewKnob() {
    static const u32 view = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA_VIEW");
        if (CardViewMisread(env)) {
            std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%.16s is not 0 to %d: off\n",
                        env, CARD_VIEW_MODES);
        }
        return ReadCardView(env);
    }();
    return view;
}

constexpr const char* ViewName(u32 mode) {
    return mode == CARD_VIEW_OVERLAY ? "overlay"
           : mode == CARD_VIEW_ALPHA ? "alpha"
           : mode == CARD_VIEW_UV    ? "coordinates"
                                     : "off";
}

} // namespace

CardCacheCounts CardCacheTally() {
    return {cutout_loaded.load(std::memory_order_relaxed),
            cutout_refused.load(std::memory_order_relaxed)};
}
void NoteCardCutoutLoaded() {
    cutout_loaded.fetch_add(1, std::memory_order_relaxed);
}
void NoteCardCutoutRefused() {
    cutout_refused.fetch_add(1, std::memory_order_relaxed);
}

bool CardAlpha::Wanted() {
    // Both knobs are read once (CardAlphaLevel and ViewKnob keep what they read); the
    // rasterizer asks once, at its start, before the first frame.
    const u32 level = Shader::Optimization::CardAlphaLevel();
    const u32 view = ViewKnob();
    if (level < CardAlphaLayers && view != 0) {
        std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%u needs "
                    "BB_RT_CARD_ALPHA=2: off\n", view);
    }
    return level >= CardAlphaLayers; // unset or 1: no CardAlpha, nothing made, no draw calls in
}

CardAlpha::CardAlpha(const Instance& instance_, Scheduler& scheduler_,
                     VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                     SceneTargets& scene_targets_, CameraMotion& camera_motion_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_} {
    // Made only when Wanted(): the knobs as it read them.
    level = Shader::Optimization::CardAlphaLevel();
    const u32 view = ViewKnob();
    if (level < CardAlphaLayers) {
        return;
    }
    made = Make();
    view_mode = made ? view : 0;
    std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA=2: %s; %u layers of %ux%u R8, %u levels "
                "(%llu bytes), layer info %llu bytes, card rows %llu bytes (made at the first ray traced scene), "
                "at most %u fills a frame; debug view BB_RT_CARD_ALPHA_VIEW=%u (%s); no shadow "
                "reads the layers yet\n",
                made ? "on" : "off - the layers could not be made", CardLayerCount, CardLayerSize,
                CardLayerSize, CardLayerMips, static_cast<unsigned long long>(CardLayersBytes),
                static_cast<unsigned long long>(CardLayerInfoBytes),
                static_cast<unsigned long long>(CardRowsBytes), CardFillsPerFrame, view,
                ViewName(view_mode));
}

CardAlpha::~CardAlpha() {
    const auto device = instance.GetDevice();
    for (auto& e : view_cache) {
        if (e.view) {
            device.destroyImageView(e.view);
        }
    }
    level_views = {};
    layers_view.reset();
    if (layers_image) {
        vmaDestroyImage(instance.GetAllocator(), layers_image, layers_allocation);
    }
    FreeBuffer(info_buffer);
    FreeBuffer(view_counters);
    FreeBuffer(view_readback);
}

bool CardAlpha::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void CardAlpha::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

// The layers (CardLayersBytes), their views, the layer info and the fill pass: all once, at
// start. The array is never recreated or resized, so a reader's descriptors never go stale.
bool CardAlpha::Make() {
    const auto device = instance.GetDevice();
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) ||
        !EffectPass::HasRoom(instance, CardLayersBytes)) {
        return false;
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .extent = {CardLayerSize, CardLayerSize, 1},
        .mipLevels = CardLayerMips,
        .arrayLayers = CardLayerCount,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(instance.GetAllocator(), &image_ci, &alloc_ci, &raw, &layers_allocation,
                       nullptr) != VK_SUCCESS) {
        return false;
    }
    layers_image = raw;
    SetObjectName(device, layers_image, "Card alpha layers");
    layers_view = Check<"create card layers view">(device.createImageViewUnique({
        .image = layers_image,
        .viewType = vk::ImageViewType::e2DArray,
        .format = vk::Format::eR8Unorm,
        .subresourceRange = LayersRange,
    }));
    for (u32 k = 0; k < CardLayerMips; ++k) {
        level_views[k] = Check<"create card layer level view">(device.createImageViewUnique({
            .image = layers_image,
            .viewType = vk::ImageViewType::e2DArray,
            .format = vk::Format::eR8Unorm,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, k, 1, 0, CardLayerCount},
        }));
    }
    const auto make_sampler = [&](vk::UniqueSampler& out, float max_lod, vk::SamplerMipmapMode mip) {
        auto made_sampler = device.createSamplerUnique({
            .magFilter = vk::Filter::eLinear,
            .minFilter = vk::Filter::eLinear,
            .mipmapMode = mip,
            .addressModeU = vk::SamplerAddressMode::eClampToEdge,
            .addressModeV = vk::SamplerAddressMode::eClampToEdge,
            .addressModeW = vk::SamplerAddressMode::eClampToEdge,
            .maxLod = max_lod,
        });
        if (made_sampler.result != vk::Result::eSuccess) {
            return false;
        }
        out = std::move(made_sampler.value);
        return true;
    };
    if (!make_sampler(layer_sampler, float(CardLayerMips - 1), vk::SamplerMipmapMode::eLinear) ||
        !make_sampler(source_sampler, VK_LOD_CLAMP_NONE, vk::SamplerMipmapMode::eLinear) ||
        !MakeBuffer(info_buffer, CardLayerInfoBytes, false,
                    vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst)) {
        return false;
    }
    using enum vk::DescriptorType;
    if (!EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,
                            {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},
                            CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COMP, "card alpha fill")) {
        return false;
    }
    // Every layer starts at 0 (a reader never reads a layer before its fill: the layer info's
    // READY bit) and the info at 0 (no layer READY).
    scheduler.Record([image = layers_image, info = info_buffer.buffer](vk::CommandBuffer cmd) {
        EffectPass::InitGeneral(cmd, image, LayersRange);
        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
        cmd.clearColorImage(image, vk::ImageLayout::eGeneral, zero, LayersRange);
        cmd.fillBuffer(info, 0, CardLayerInfoBytes, 0);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  MemoryAll);
    });
    info_dirty = false;
    return true;
}

void CardAlpha::Miss(CardDraw& card, CardLayerMiss why) {
    card.layer = 0;
    card.layer_gen = 0;
    ++stats.miss[std::size_t(why)];
}

void CardAlpha::NoteNoSource(CardDraw& card) {
    ++stats.draws;
    Miss(card, CardLayerMiss::NoSource);
}

void CardAlpha::NoteDraw(CardDraw& card, const AmdGpu::Image& sharp, const Shader::ImageResource& res,
                         VideoCore::ImageId image, u64 uid) {
    ++stats.draws;
    const auto dst = sharp.DstSelect();
    const CardTexFacts facts{
        .type = u32(sharp.GetType()),
        .num_format = u32(sharp.GetNumberFmt()),
        .conversion = u32(sharp.GetNumberConversion()),
        .dst_select = {u8(dst.r), u8(dst.g), u8(dst.b), u8(dst.a)},
    };
    u8 lane = 0xff;
    if (const CardLayerMiss why = CardSourceCheck(facts, card.stored_channel, lane);
        why != CardLayerMiss::None) {
        Miss(card, why);
        return;
    }
    // Read without touching the texture cache's LRU (the draw's binding just did).
    const VideoCore::Image* found = texture_cache.TryGetImage(image, uid);
    if (!found || !texture_cache.IsRegisteredImage(image, uid)) {
        Miss(card, CardLayerMiss::NoSource);
        return;
    }
    if (found->info.props.is_depth) {
        Miss(card, CardLayerMiss::Depth);
        return;
    }
    const CardLayerSource source{image.index, uid, found->write_seq};
    const CardLayerGet got = table.Get(CardLayerKey(card.tsharp, lane), lane, source, frame);
    if (got.layer == CardNoLayer) {
        Miss(card, CardLayerMiss::Full);
        return;
    }
    stats.given += got.given ? 1 : 0;
    stats.taken += got.taken ? 1 : 0;
    stats.dropped += got.dropped ? 1 : 0;
    // A layer given (new generation) or dropped (no longer READY): the info changes.
    info_dirty = info_dirty || got.given || got.dropped;
    if (table.At(got.layer).queued) {
        // The view the fill samples, as this draw binds the texture (the newest source).
        fill_view[got.layer] = VideoCore::ImageViewInfo(sharp, res);
    }
    card.layer = got.layer + 1;
    card.layer_gen = got.gen;
}

void CardAlpha::RecordFills() {
    if (!made) {
        return;
    }
    if (fills_frame != frame) {
        fills_frame = frame;
        fills_left = CardFillsPerFrame;
    }
    while (fills_left > 0) {
        const u32 layer = table.NextFill();
        if (layer == CardNoLayer) {
            break;
        }
        --fills_left;
        const bool refill = table.At(layer).state == CardLayerState::Ready;
        const FillResult result = Fill(layer);
        if (result == FillResult::Recorded) {
            ++(refill ? stats.refills : stats.fills);
            info_dirty = true;
        } else {
            // Not filled: a Wanted layer waits for the next draw that binds the texture, a
            // Ready one keeps its fill (the next draw asks again if the source differs).
            table.FillFailed(layer);
            if (result == FillResult::NotYet) {
                ++stats.dirty_waits;
            } else {
                ++stats.failed_fills;
                ++stats.miss[std::size_t(CardLayerMiss::Gone)];
            }
        }
    }
    if (!info_dirty) {
        return;
    }
    info_dirty = false;
    std::array<u32, CardLayerCount> info{};
    for (u32 i = 0; i < CardLayerCount; ++i) {
        info[i] = table.Info(i);
    }
    scheduler.EndRendering();
    scheduler.Record([info, buffer = info_buffer.buffer](vk::CommandBuffer cmd) {
        // After every earlier reader of the info (rays of this frame's earlier passes).
        EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Transfer,
                                  vk::AccessFlagBits2::eTransferWrite);
        cmd.updateBuffer(buffer, 0, sizeof(info), info.data());
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
}

// One layer from its source image, as the last draw bound it. The image must still be the
// registered image of that uid (a texture streamed out since: the fill waits for a draw that
// binds a living one). The source's write_seq as read here is what the layer then holds.
// An image with Dirty flags (the CPU wrote its memory after the draw bound it, or a fill put off
// by the budget meets such writes) holds older texels than the guest's: no fill from it; the
// next draw's binding uploads them (a write that bumps write_seq) and asks for the fill again.
CardAlpha::FillResult CardAlpha::Fill(u32 layer) {
    const CardLayer& l = table.At(layer);
    const VideoCore::ImageId id{l.source.image};
    VideoCore::Image* image = texture_cache.TryGetImage(id, l.source.uid);
    if (!image || !texture_cache.IsRegisteredImage(id, l.source.uid) || image->info.props.is_depth) {
        return FillResult::Gone;
    }
    if (True(image->flags & VideoCore::ImageFlagBits::Dirty)) {
        return FillResult::NotYet;
    }
    const CardLayerSource as_read{l.source.image, l.source.uid, image->write_seq};
    const vk::ImageView source = *image->FindView(fill_view[layer]).image_view;
    scheduler.EndRendering();
    runtime.Transit(image, vk::ImageLayout::eShaderReadOnlyOptimal, Compute, ShaderRead);
    runtime.FlushBarriers();
    const std::array<u32, 4> push{layer, l.lane, 0, 0};
    const vk::DescriptorImageInfo src{*source_sampler, source, vk::ImageLayout::eShaderReadOnlyOptimal};
    const vk::DescriptorImageInfo dst0{{}, *level_views[0], vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo dst1{{}, *level_views[1], vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo dst2{{}, *level_views[2], vk::ImageLayout::eGeneral};
    constexpr u32 groups = (CardLayerSize + CARD_FILL_GROUP - 1) / CARD_FILL_GROUP;
    EffectPass::Mark(62, "card alpha fill");
    scheduler.RecordCrumb(
        {.name = "Card alpha fill"},
        [push, src, dst0, dst1, dst2, pipeline = *fill_pipeline,
         layout = *fill_layout](vk::CommandBuffer cmd) {
            // The layer may be read by rays recorded before (its old texture, or the same one
            // before a refill): they finish first.
            EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Compute, ShaderWrite);
            const std::array writes{
                vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                                       .pImageInfo = &src},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst0},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst1},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &dst2}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), push.data());
            cmd.dispatch(groups, groups, 1);
            EffectPass::MemoryBarrier(cmd, Compute, ShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead);
        });
    table.Filled(layer, as_read);
    return FillResult::Recorded;
}

void CardAlpha::NoSceneHooks() {
    if (view_mode != 0 && !view_said_no_hooks) {
        view_said_no_hooks = true;
        std::printf("Card alpha layers (r62): BB_RT_CARD_ALPHA_VIEW=%u has no place in the frame "
                    "without the upscaler (it runs before it): the view stays off\n", view_mode);
    }
}

bool CardAlpha::MakeView() {
    if (view_pipeline) {
        return true;
    }
    if (view_failed) {
        return false;
    }
    using enum vk::DescriptorType;
    view_failed = !EffectPass::CreateSampler(instance, depth_sampler, vk::Filter::eNearest) ||
                  !MakeBuffer(view_counters, CARD_VIEW_COUNTERS * 4, false,
                              vk::BufferUsageFlagBits::eStorageBuffer |
                                  vk::BufferUsageFlagBits::eTransferSrc |
                                  vk::BufferUsageFlagBits::eTransferDst) ||
                  !MakeBuffer(view_readback, CARD_VIEW_COUNTERS * 4, true,
                              vk::BufferUsageFlagBits::eTransferDst) ||
                  !EffectPass::Create(instance, view_set, view_layout, view_pipeline,
                                      {eAccelerationStructureKHR, eCombinedImageSampler, eStorageImage,
                                       eStorageBuffer, eStorageBuffer, eStorageBuffer,
                                       eCombinedImageSampler, eStorageBuffer},
                                      CARD_VIEW_PUSH_BYTES, RT_CARD_VIEW_COMP, "card debug view");
    if (view_failed) {
        std::printf("Card alpha layers (r62): the debug view is off - its pass could not be made\n");
        return false;
    }
    // Outside rendering: PrepareScene before this need not have ended it (no build, no fill).
    scheduler.EndRendering();
    scheduler.Record([counters = view_counters.buffer](vk::CommandBuffer cmd) {
        cmd.fillBuffer(counters, 0, CARD_VIEW_COUNTERS * 4, 0);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                  MemoryAll);
    });
    return true;
}

vk::ImageView CardAlpha::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .aspect = aspect,
        .view = Check<"create card view image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

// The debug view: a frame whose scene is built (PrepareScene; it records the fills first) and
// whose scene colour is RGBA16F with storage, as the drawn look takes it.
void CardAlpha::View(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter) {
    if (!ViewOn() || !color_id || !depth_id || camera_motion.PreviewFrame()) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid || !rt_shadow.PrepareScene() || !MakeView()) {
        ++stats.view_skipped;
        return;
    }
    const auto tables = rt_shadow.CardTables();
    const vk::AccelerationStructureKHR scene = rt_shadow.Scene();
    if (!tables.rows || !tables.pool || !scene) {
        ++stats.view_skipped; // no card yet: no rows, no pool
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.view_skipped;
        return;
    }
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    const SceneUseScope scene_use{"card debug view"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.view_skipped;
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.view_skipped;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    struct Push {
        std::array<float, 4> proj;
        std::array<float, 2> jitter;
        std::array<u32, 2> size;
        u32 mode, flags, unused0, unused1;
        std::array<float, 4> unused2;
    };
    static_assert(sizeof(Push) == CARD_VIEW_PUSH_BYTES);
    const Push push{camera.proj, jitter, {width, height}, view_mode, 0, 0, 0, {}};
    // Copied every CardViewLineFrames view frames: the u32 counters cannot overflow (at 4K, 600
    // frames would). The frames since the last copy are printed with the counts.
    const bool copy = ++view_frames >= CardViewLineFrames && !view_readback_pending;
    if (copy) {
        view_copied_frames = view_frames;
        view_frames = 0;
        view_readback_pending = true;
        view_readback_tick = scheduler.CurrentTick();
    }
    ++stats.views;
    const auto layers = ReaderBindings();
    EffectPass::Mark(63, "card debug view");
    scheduler.RecordCrumb(
        {.name = "Card debug view"},
        [push, scene, color_view, depth_view, tables, layers, copy,
         depth_sampler = *depth_sampler, counters = view_counters.buffer,
         readback = view_readback.buffer, pipeline = *view_pipeline,
         layout = *view_layout](vk::CommandBuffer cmd) {
            EffectPass::FullBarrier(cmd);
            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const vk::DescriptorImageInfo depth_info{depth_sampler, depth_view,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo alpha_info{layers.sampler, layers.layers,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo rows_info{tables.rows, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo pool_info{tables.pool, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo layer_info{layers.info, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = eCombinedImageSampler,
                                       .pImageInfo = &depth_info},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = eStorageImage, .pImageInfo = &color_info},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &rows_info},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &pool_info},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &layer_info},
                vk::WriteDescriptorSet{.dstBinding = 6, .descriptorCount = 1,
                                       .descriptorType = eCombinedImageSampler,
                                       .pImageInfo = &alpha_info},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer,
                                       .pBufferInfo = &counter_info}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((push.size[0] + CARD_VIEW_GROUP - 1) / CARD_VIEW_GROUP,
                         (push.size[1] + CARD_VIEW_GROUP - 1) / CARD_VIEW_GROUP, 1);
            EffectPass::FullBarrier(cmd);
            if (copy) {
                const vk::BufferCopy region{0, 0, CARD_VIEW_COUNTERS * 4};
                cmd.copyBuffer(counters, readback, region);
                EffectPass::FullBarrier(cmd);
                cmd.fillBuffer(counters, 0, CARD_VIEW_COUNTERS * 4, 0);
                EffectPass::FullBarrier(cmd);
            }
        });
}

void CardAlpha::OnFrameEnd() {
    if (!made) {
        return;
    }
    ++frame;
    if (view_readback_pending && scheduler.IsFree(view_readback_tick)) {
        view_readback_pending = false;
        // A copy of the GPU's counters in our own readback buffer (not guest memory). Summed in
        // 64 bits.
        const auto* c = static_cast<const u32*>(view_readback.mapped);
        const u64 tested = u64(c[CARD_VIEW_AGREE_KEPT]) + c[CARD_VIEW_AGREE_DROPPED] +
                           c[CARD_VIEW_RAY_KEPT_GAME_DROPPED] + c[CARD_VIEW_RAY_DROPPED_GAME_KEPT];
        const u64 agreed = u64(c[CARD_VIEW_AGREE_KEPT]) + c[CARD_VIEW_AGREE_DROPPED];
        const double agree = tested > 0 ? 100.0 * double(agreed) / double(tested) : 0.0;
        std::printf("Card debug view (r62): %u frames, %u pixels: %u on a card candidate; judged "
                    "(camera pass cards without dither, game mip within the layers): %u agree "
                    "kept, %u agree dropped, %u ray kept where the game dropped, %u ray dropped "
                    "where the game kept (%.2f %% agree); not judged: %u sun pass cards, %u "
                    "dithered, %u game mip coarser than the layers; %u no data; %u no card, %u "
                    "sky\n",
                    view_copied_frames, c[CARD_VIEW_PIXELS], c[CARD_VIEW_CARD_HITS],
                    c[CARD_VIEW_AGREE_KEPT], c[CARD_VIEW_AGREE_DROPPED],
                    c[CARD_VIEW_RAY_KEPT_GAME_DROPPED], c[CARD_VIEW_RAY_DROPPED_GAME_KEPT], agree,
                    c[CARD_VIEW_SUN_CARD], c[CARD_VIEW_DITHERED], c[CARD_VIEW_COARSE],
                    c[CARD_VIEW_NO_DATA], c[CARD_VIEW_NO_CARD], c[CARD_VIEW_SKY]);
    }
    if (++line_frames < LineFrames) {
        return;
    }
    line_frames = 0;
    const auto rows = rt_shadow.TakeCardRowCounts();
    const auto cache = CardCacheTally();
    const auto& m = stats.miss;
    std::printf("Card alpha layers (r62): %u frames: %llu card draws (%llu found by the hint), %llu "
                "layers given (%llu taken from another texture, %llu dropped: another image), "
                "%llu fills, %llu refills, %llu failed, %llu put off (CPU writes not uploaded); "
                "layers %u ready, %u "
                "wanted, %u free, %u queued; no layer: %llu no source, %llu not 2D, %llu "
                "multisampled, %llu conversion, %llu format, %llu constant, %llu no lane, %llu depth, "
                "%llu full, %llu gone; rows %llu written (%llu ready), %llu deferred; views %llu "
                "(%llu skipped); cache CUT1 %llu loaded, %llu refused\n",
                LineFrames, static_cast<unsigned long long>(stats.draws),
                static_cast<unsigned long long>(table.TakeHintHits()),
                static_cast<unsigned long long>(stats.given),
                static_cast<unsigned long long>(stats.taken),
                static_cast<unsigned long long>(stats.dropped),
                static_cast<unsigned long long>(stats.fills),
                static_cast<unsigned long long>(stats.refills),
                static_cast<unsigned long long>(stats.failed_fills),
                static_cast<unsigned long long>(stats.dirty_waits),
                table.Count(CardLayerState::Ready), table.Count(CardLayerState::Wanted),
                table.Count(CardLayerState::Free), table.Queued(),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NoSource)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NotTwoD)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Multisample)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Conversion)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Format)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Constant)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::NoLane)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Depth)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Full)]),
                static_cast<unsigned long long>(m[std::size_t(CardLayerMiss::Gone)]),
                static_cast<unsigned long long>(rows.written),
                static_cast<unsigned long long>(rows.ready),
                static_cast<unsigned long long>(rows.deferred),
                static_cast<unsigned long long>(stats.views),
                static_cast<unsigned long long>(stats.view_skipped),
                static_cast<unsigned long long>(cache.loaded),
                static_cast<unsigned long long>(cache.refused));
    stats = {};
}

} // namespace Vulkan
""",
    TESTS + "test_rt_card_layers.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): tests of the pure parts of the card alpha layers (rt_card_layers.h):
// the sizes, the view knob, which textures a layer takes and through which lane, the layer key,
// the fill's source level and taps, the layer table (given, filled, refilled, dropped, reused,
// full, the hint), the card rows (sun, dither, axis extras), the card test a ray runs (against
// the game's rule on the original coordinates, at a level, mirror once and border), the debug
// view's classes, mip and exclusions, and the CUT1 cache part (version, padding, byte checks).
// Built alone: c++ -std=c++20 -I. tests/test_rt_card_layers.cpp (engine/build.sh --test).

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include "gpu/shadps4/video_core/renderer_vulkan/rt_card_layers.h"

using namespace Vulkan;

namespace {

int failures = 0;
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::printf("FAILED %s:%d: %s\n", __FILE__, __LINE__, #x);                             \
            ++failures;                                                                            \
        }                                                                                          \
    } while (0)

void TestSizes() {
    CHECK(CardLayerBytes == 65536u + 16384u + 4096u);
    CHECK(CardLayersBytes == 11010048u); // 10.5 MiB
    CHECK(CardLayerBytesAt(512, 3) == 344064u);
    CHECK(CardLayerBytesAt(512, 3) * 128 == 44040192u); // 42 MiB at 512
    CHECK(CardLayerBytesAt(4, 4) == 16u + 4u + 1u + 1u);
    CHECK(CardRowsBytes == 2097152u);
    CHECK(CardLayerInfoBytes == 512u);
    // The view's u32 counters over CardViewLineFrames frames: 4K and 8K fit, 600 frames of 4K not.
    CHECK(CardViewLineFrames == 120);
    CHECK(std::uint64_t(3840) * 2160 * CardViewLineFrames < (std::uint64_t(1) << 32));
    CHECK(std::uint64_t(3840) * 2160 * 600 > 0xffffffffull);
}

void TestViewKnob() {
    CHECK(ReadCardView(nullptr) == 0);
    CHECK(ReadCardView("0") == 0);
    CHECK(ReadCardView("1") == CARD_VIEW_OVERLAY);
    CHECK(ReadCardView("2") == CARD_VIEW_ALPHA);
    CHECK(ReadCardView("3") == CARD_VIEW_UV);
    CHECK(ReadCardView("4") == 0);
    CHECK(ReadCardView("11") == 0);
    CHECK(ReadCardView("") == 0);
    CHECK(!CardViewMisread(nullptr));
    CHECK(!CardViewMisread("0"));
    CHECK(!CardViewMisread("3"));
    CHECK(CardViewMisread("4"));
    CHECK(CardViewMisread(""));
    CHECK(CardViewMisread("on"));
}

void TestSource() {
    CardTexFacts f; // Color2D? not yet: type 0
    std::uint8_t lane = 0;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NotTwoD);
    f.type = CardTypeColor2D;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None && lane == 3); // BC3, BC7: a in w
    f.dst_select = {7, 7, 7, 7}; // an alpha-only view (BC4-like swizzle): every lane reads it
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None && lane == 0);
    f.dst_select = {4, 5, 6, 1}; // BC1 without alpha in w: the test reads red
    CHECK(CardSourceCheck(f, 4, lane) == CardLayerMiss::None && lane == 0);
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NoLane && lane == 0xff);
    CHECK(CardSourceCheck(f, 1, lane) == CardLayerMiss::Constant);
    CHECK(CardSourceCheck(f, 0, lane) == CardLayerMiss::Constant);
    f.dst_select = {4, 5, 6, 7};
    f.num_format = 9; // sRGB: the alpha lane is linear either way
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None);
    f.num_format = 7;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::None);
    f.num_format = 1; // Snorm
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Format);
    f.num_format = 4; // Uint
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Format);
    f.num_format = 0;
    f.conversion = 1;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Conversion);
    f.conversion = 0;
    f.type = CardTypeColor2DMsaa;
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::Multisample);
    f.type = 13; // Color2DArray (a cube reads as one)
    CHECK(CardSourceCheck(f, 7, lane) == CardLayerMiss::NotTwoD);
    CHECK(CardViewLane({4, 5, 6, 7}, 8) == 0xff);
    for (std::size_t m = 0; m < std::size_t(CardLayerMiss::Count); ++m) {
        CHECK(std::strcmp(CardLayerMissName(CardLayerMiss(m)), "?") != 0);
    }
}

void TestKey() {
    std::array<std::uint32_t, 8> t{1, 2, 3, 4, 5, 6, 7, 8};
    const std::uint64_t k = CardLayerKey(t, 3);
    CHECK(k != 0);
    CHECK(k == CardLayerKey(t, 3));
    CHECK(k != CardLayerKey(t, 0));
    t[7] ^= 1;
    CHECK(k != CardLayerKey(t, 3));
}

void TestFillLod() {
    const auto taps = [](const CardFillTaps& t, std::uint32_t u, std::uint32_t v) {
        return t.taps_u == u && t.taps_v == v;
    };
    CardFillTaps t = CardFillLod(256, 256, 9, 256); // the same size: one tap at level 0
    CHECK(t.lod == 0.0f && taps(t, 1, 1));
    t = CardFillLod(128, 64, 8, 256); // smaller: one tap
    CHECK(t.lod == 0.0f && taps(t, 1, 1));
    t = CardFillLod(1024, 1024, 11, 256); // ratio 4: level 1, 2 x 2 taps (as before r62 rev. 1)
    CHECK(std::abs(t.lod - 1.0f) < 1e-6f && taps(t, 2, 2));
    t = CardFillLod(1024, 1024, 11, 64);
    CHECK(std::abs(t.lod - 3.0f) < 1e-6f && taps(t, 2, 2));
    t = CardFillLod(512, 512, 10, 256); // ratio 2: level 0, 2 x 2 taps
    CHECK(t.lod == 0.0f && taps(t, 2, 2));
    // Not square: the smaller side sets the level, the larger takes more taps (S7: v of a
    // 2048x512 source is read at its 512 rows' level, not 4 times coarser).
    t = CardFillLod(2048, 512, 12, 256);
    CHECK(t.lod == 0.0f && taps(t, 8, 2));
    t = CardFillLod(2048, 128, 12, 256); // v smaller than the layer: level 0, one tap in v
    CHECK(t.lod == 0.0f && taps(t, 8, 1));
    t = CardFillLod(4096, 1024, 13, 256); // ratio 4 in v: level 1, u covers 8 texels there
    CHECK(std::abs(t.lod - 1.0f) < 1e-6f && taps(t, 8, 2));
    t = CardFillLod(8192, 512, 14, 256); // u would want 16: at most CARD_FILL_MAX_TAPS
    CHECK(t.lod == 0.0f && taps(t, CARD_FILL_MAX_TAPS, 2));
    t = CardFillLod(4096, 4096, 1, 256); // no mips: level 0, the most taps
    CHECK(t.lod == 0.0f && taps(t, CARD_FILL_MAX_TAPS, CARD_FILL_MAX_TAPS));
    t = CardFillLod(700, 300, 10, 256); // not a power of two: 300 / 256 = 1.17, level 0
    CHECK(t.lod == 0.0f && taps(t, 3, 2));
    t = CardFillLod(1400, 600, 11, 256); // 600 / 256 = 2.34: level log2(2.34) - 1 = 0.23, where v
    // covers 2 texels and u 1400 / 600 * 2 = 4.67
    CHECK(std::abs(t.lod - (std::log2(600.0f / 256.0f) - 1.0f)) < 1e-6f && taps(t, 5, 2));
    CHECK(CardFillAxisTaps(0.5f) == 1 && CardFillAxisTaps(1.0f) == 1 && CardFillAxisTaps(2.0f) == 2 &&
          CardFillAxisTaps(2.01f) == 3 && CardFillAxisTaps(100.0f) == CARD_FILL_MAX_TAPS);
}

void TestTable() {
    CardLayerTable table;
    const CardLayerSource a{7, 70, 1};
    CardLayerGet g = table.Get(100, 3, a, 10);
    CHECK(g.layer == 0 && g.given && !g.taken && g.gen == 1);
    CHECK(table.At(0).state == CardLayerState::Wanted && table.Queued() == 1);
    CHECK(table.Info(0) == 1u); // not filled: no READY bit
    // Another draw of the same key and source: same layer, not queued twice.
    g = table.Get(100, 3, a, 10);
    CHECK(g.layer == 0 && !g.given && table.Queued() == 1);
    CHECK(table.NextFill() == 0 && table.NextFill() == CardNoLayer);
    table.Filled(0, a);
    CHECK(table.Info(0) == (1u | CARD_LAYER_READY));
    g = table.Get(100, 3, a, 11);
    CHECK(table.Queued() == 0 && !table.At(0).refill);
    // The image was written (streamed in, replaced): filled again, the old fill stays readable.
    const CardLayerSource a2{7, 70, 2};
    g = table.Get(100, 3, a2, 12);
    CHECK(table.At(0).refill && table.Queued() == 1 && table.Info(0) == (1u | CARD_LAYER_READY));
    CHECK(table.NextFill() == 0);
    // The image went away before the fill: the old fill stays, nothing queued.
    table.FillFailed(0);
    CHECK(table.Info(0) == (1u | CARD_LAYER_READY) && table.Queued() == 0);
    g = table.Get(100, 3, a2, 12); // the next draw asks again
    CHECK(table.Queued() == 1 && table.NextFill() == 0);
    table.Filled(0, a2);
    CHECK(!table.At(0).refill);
    // A source that changed again between the fill's start and its record stays wanted.
    g = table.Get(100, 3, CardLayerSource{7, 70, 3}, 12);
    CHECK(table.NextFill() == 0);
    table.Filled(0, a2);
    CHECK(table.At(0).refill);
    // Fill every layer in frame 20.
    CardLayerTable full;
    for (std::uint32_t k = 0; k < CardLayerCount; ++k) {
        g = full.Get(1000 + k, 3, CardLayerSource{k + 1, k + 1, 0}, 20);
        CHECK(g.layer == k && g.given);
    }
    CHECK(full.Queued() == CardLayerCount);
    for (std::uint32_t k = 0; k < CardLayerCount; ++k) {
        const std::uint32_t i = full.NextFill();
        CHECK(i == k);
        full.Filled(i, full.At(i).source);
    }
    CHECK(full.Count(CardLayerState::Ready) == CardLayerCount);
    // Frame 21: all were used in frame 20 (the last): a new key gets none.
    g = full.Get(5000, 3, CardLayerSource{999, 999, 0}, 21);
    CHECK(g.layer == CardNoLayer);
    // Frame 22: layer 5 used in frame 21, the others last in 20: the least recently used, the
    // first of those, is taken; its generation moves on and it is no longer READY.
    full.Get(1005, 3, CardLayerSource{6, 6, 0}, 21);
    full.Get(1000, 3, CardLayerSource{1, 1, 0}, 21);
    g = full.Get(5000, 3, CardLayerSource{999, 999, 0}, 22);
    CHECK(g.layer == 1 && g.given && g.taken && g.gen == 2);
    CHECK(full.Info(1) == 2u);
    // The old key's row (gen 1) no longer matches the layer.
    CHECK(full.Info(1) != (1u | CARD_LAYER_READY));
    // The old key comes back: another layer, a new generation there.
    g = full.Get(1001, 3, CardLayerSource{2, 2, 0}, 23);
    CHECK(g.given && g.layer != 1 && g.layer != 0 && g.layer != 5);

    // Another image answers a READY key (another uid, or another ImageId): no longer READY, the
    // generation kept, queued for its refill; READY again with the same generation once filled.
    CardLayerTable swap;
    const CardLayerSource s1{3, 30, 5};
    g = swap.Get(77, 3, s1, 10);
    CHECK(swap.NextFill() == g.layer);
    swap.Filled(g.layer, s1);
    const std::uint32_t gen = g.gen;
    CHECK(swap.Info(g.layer) == (gen | CARD_LAYER_READY));
    const CardLayerSource s2{3, 31, 5}; // the same slot, another image (uid)
    g = swap.Get(77, 3, s2, 11);
    CHECK(g.dropped && !g.given && g.gen == gen && swap.Info(g.layer) == gen &&
          swap.At(g.layer).state == CardLayerState::Wanted && swap.Queued() == 1);
    CHECK(swap.NextFill() == g.layer);
    swap.Filled(g.layer, s2);
    CHECK(swap.Info(g.layer) == (gen | CARD_LAYER_READY));
    g = swap.Get(77, 3, CardLayerSource{4, 31, 5}, 12); // another ImageId: dropped too
    CHECK(g.dropped && swap.Info(g.layer) == gen);
    swap.Filled(g.layer, CardLayerSource{4, 31, 5});
    g = swap.Get(77, 3, CardLayerSource{4, 31, 6}, 13); // the same image written: refill, READY
    CHECK(!g.dropped && swap.At(g.layer).refill && swap.Info(g.layer) == (gen | CARD_LAYER_READY));

    // The hint: a known key is found without the scan; a stale hint (its layer went to another
    // key) is not taken; two keys of one hint slot are both found.
    CardLayerTable hinted;
    (void)hinted.TakeHintHits();
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    const std::uint32_t first = g.layer;
    CHECK(hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    CHECK(g.layer == first && hinted.TakeHintHits() == 1);
    g = hinted.Get(5 + 256, 3, CardLayerSource{2, 2, 0}, 2); // the same hint slot
    const std::uint32_t second = g.layer;
    CHECK(g.given && second != first && hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2); // the slot holds 5 + 256 now: a scan
    CHECK(g.layer == first && !g.given && hinted.TakeHintHits() == 0);
    g = hinted.Get(5, 3, CardLayerSource{1, 1, 0}, 2);
    CHECK(g.layer == first && hinted.TakeHintHits() == 1);
}

void TestRows() {
    CardRow r;
    r.ready = true;
    r.pool_offset = 4194303;
    r.triangles = 65535 * 64;
    r.layer = 127;
    r.layer_gen = 0x7fffffff;
    r.op = CardOp::NotEqual;
    r.nonzero = true;
    r.dither = true;
    r.sun = true;
    r.mode_u = CARD_UV_MODE_MIRROR;
    r.mode_v = CARD_UV_MODE_CLAMP;
    r.extra_u = CARD_AXIS_MIRROR_ONCE;
    r.extra_v = CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER;
    r.reference = 0.50196f;
    r.offset_u = -3.25f;
    r.offset_v = 1e-7f;
    r.dither_scale = -1.0f;
    const auto w = CardPackRow(r);
    const CardRow b = CardUnpackRow(w);
    CHECK(b.ready && b.pool_offset == r.pool_offset && b.triangles == r.triangles && b.layer == 127 &&
          b.layer_gen == r.layer_gen && b.op == r.op && b.nonzero && b.dither && b.sun &&
          b.mode_u == r.mode_u && b.mode_v == r.mode_v && b.extra_u == r.extra_u &&
          b.extra_v == r.extra_v && b.reference == r.reference &&
          b.offset_u == r.offset_u && b.offset_v == r.offset_v && b.dither_scale == r.dither_scale);
    for (std::uint32_t op = 0; op < 6; ++op) {
        r.op = CardOp(op);
        r.ready = false;
        r.nonzero = false;
        r.sun = false;
        r.extra_u = 0;
        const CardRow c = CardUnpackRow(CardPackRow(r));
        CHECK(c.op == CardOp(op) && !c.ready && !c.nonzero && !c.sun && c.extra_u == 0 &&
              c.extra_v == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    }
    // Every flag in its own bits.
    CHECK((CARD_ROW_DITHER & CARD_ROW_SUN) == 0 && (CARD_ROW_SUN >> CARD_ROW_EXTRA_U_SHIFT) == 0 &&
          CARD_ROW_EXTRA_V_SHIFT + 2 <= 31);
    // The raw clamp modes' extras.
    CHECK(CardAxisExtra(0) == 0 && CardAxisExtra(1) == 0 && CardAxisExtra(2) == 0);
    CHECK(CardAxisExtra(3) == CARD_AXIS_MIRROR_ONCE && CardAxisExtra(4) == CARD_AXIS_BORDER);
    CHECK(CardAxisExtra(5) == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    CHECK(CardAxisExtra(6) == CARD_AXIS_BORDER);
    CHECK(CardAxisExtra(7) == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER));
    // When a row is READY.
    CardUv uv;
    uv.card.valid = true;
    uv.card.layer = 5;
    uv.card.layer_gen = 9;
    uv.card.affine = {2.0f, 3.0f, 0.25f, -0.5f};
    uv.card.camera = true;
    uv.card.clamp_u = 7;
    uv.card.clamp_v = 2;
    uv.state = CardUvState::Ready;
    CardRow e = CardRowFor(uv, 10, 20);
    CHECK(e.ready && e.layer == 4 && e.layer_gen == 9 && e.pool_offset == 10 && e.triangles == 20 &&
          e.offset_u == 0.25f && e.offset_v == -0.5f && !e.sun && !e.dither &&
          e.extra_u == (CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER) && e.extra_v == 0);
    // The dither bit only with a coefficient not 0 (F3); the sun bit for a sun pass card (F1).
    uv.card.dither = true;
    CHECK(!CardRowFor(uv, 10, 20).dither);
    uv.card.dither_scale = -1.0f;
    CHECK(CardRowFor(uv, 10, 20).dither);
    uv.card.dither = false;
    CHECK(!CardRowFor(uv, 10, 20).dither);
    uv.card.dither_scale = 0.0f;
    uv.card.camera = false;
    CHECK(CardRowFor(uv, 10, 20).sun);
    uv.card.camera = true;
    uv.state = CardUvState::Pending;
    CHECK(!CardRowFor(uv, 10, 20).ready);
    uv.state = CardUvState::Ready;
    uv.miss = CardMiss::NoRecord; // stale
    CHECK(!CardRowFor(uv, 10, 20).ready);
    uv.miss = CardMiss::None;
    uv.card.layer = 0; // no layer
    CHECK(!CardRowFor(uv, 10, 20).ready);
}

// A smooth alpha with sharp-enough features: what the layer would hold, sampled exactly.
float Texture(float u, float v) {
    return 0.5f + 0.5f * std::sin(6.2831853f * u * 3.0f) * std::cos(6.2831853f * v * 2.0f);
}

void TestCardTest() {
    std::mt19937 rng(62);
    std::uniform_real_distribution<float> uv01(-2.0f, 3.0f), alpha(0.2f, 1.0f), bary(0.0f, 1.0f);
    const std::array<float, 4> affine{1.5f, 0.75f, 0.3125f, -0.125f}; // scale u, v, offset u, v
    std::uint32_t checked = 0, near_ref = 0, differ = 0;
    for (std::uint32_t mode = 0; mode < 3; ++mode) {
        std::vector<std::array<std::uint32_t, 4>> pool;
        std::vector<std::array<CardCorner, 3>> original;
        for (int t = 0; t < 400; ++t) {
            std::array<CardCorner, 3> c{};
            const float bu = uv01(rng), bv = uv01(rng);
            for (CardCorner& k : c) {
                k = {bu + 0.3f * bary(rng), bv + 0.3f * bary(rng), alpha(rng)};
                k.a = float(CardUnorm8(k.a)) / 255.0f; // on the 8-bit grid: not rounded
            }
            original.push_back(c);
            std::array<CardCorner, 3> scaled{};
            for (std::size_t i = 0; i < 3; ++i) {
                scaled[i] = CardApplyAffine(c[i], CardPoolAffine(affine));
            }
            pool.push_back(CardPackTriangle(scaled, mode, mode, true));
        }
        CardRow r;
        r.ready = true;
        r.pool_offset = 0;
        r.triangles = std::uint32_t(pool.size());
        r.layer = 3;
        r.layer_gen = 77;
        r.op = CardOp::GreaterEqual;
        r.nonzero = true;
        r.mode_u = mode;
        r.mode_v = mode;
        r.reference = 0.392f;
        r.offset_u = affine[2];
        r.offset_v = affine[3];
        const auto row = CardPackRow(r);
        std::uint32_t layer_seen = 0;
        float lod_seen = -1.0f;
        const auto sample = [&](std::uint32_t layer, float u, float v, float lod) {
            layer_seen = layer;
            lod_seen = lod;
            return Texture(u, v);
        };
        for (std::uint32_t p = 0; p < pool.size(); ++p) {
            float b1 = bary(rng), b2 = bary(rng);
            if (b1 + b2 > 1.0f) {
                b1 = 1.0f - b1;
                b2 = 1.0f - b2;
            }
            const float lod = float(p % 3) * 0.5f;
            const CardTestResult got =
                CardTest(row, 77u | CARD_LAYER_READY, pool, p, b1, b2, lod, sample);
            std::uint32_t flags = pool[p][3] >> CARD_UV_FLAGS_SHIFT;
            CHECK((flags & CARD_UV_TRI_NOT_FINITE) == 0);
            CHECK(got.status != CARD_NO_DATA && layer_seen == 3 && lod_seen == lod);
            // The game: the original coordinates, the draw's whole affine, the sampler's repeat.
            const auto& c = original[p];
            const float b0 = 1.0f - b1 - b2;
            const float u = (c[0].u * b0 + c[1].u * b1 + c[2].u * b2) * affine[0] + affine[2];
            const float v = (c[0].v * b0 + c[1].v * b1 + c[2].v * b2) * affine[1] + affine[3];
            const float a = c[0].a * b0 + c[1].a * b1 + c[2].a * b2;
            const float ga = Texture(CardRepeat(u, mode), CardRepeat(v, mode)) * a;
            const bool game = CardKeeps(ga, r.reference, r.op, r.nonzero);
            // The raw coordinates: before the repeat, the offset in (half precision of the
            // shifted pool coordinates: within a whole repeat for wrap, two for mirror).
            if (mode == CARD_UV_MODE_CLAMP) {
                CHECK(std::abs(got.raw_u - u) < 0.01f && std::abs(got.raw_v - v) < 0.01f);
            } else {
                const float period = mode == CARD_UV_MODE_WRAP ? 1.0f : 2.0f;
                const float du = (got.raw_u - u) / period, dv = (got.raw_v - v) / period;
                CHECK(std::abs(du - std::round(du)) < 0.01f && std::abs(dv - std::round(dv)) < 0.01f);
            }
            // Half precision of a shifted coordinate within 4: 2^-11 relative; the texture's
            // slope is at most 3 * 2 * pi * 0.5 + 2 * 2 * pi * 0.5 per unit: about 16.
            const float bound = 16.0f * 0.0025f + 1e-4f;
            ++checked;
            if (std::abs(ga - r.reference) < bound) {
                ++near_ref;
            } else {
                CHECK(game == (got.status == CARD_KEPT));
                differ += game == (got.status == CARD_KEPT) ? 0 : 1;
                CHECK(std::abs(got.alpha - ga) < bound);
            }
        }
        // No data: not ready, another generation, the layer not filled, past the triangles, a
        // record marked not finite.
        CHECK(CardTest(row, 77u, pool, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        CHECK(CardTest(row, 78u | CARD_LAYER_READY, pool, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, pool, r.triangles, 0.2f, 0.2f, 0.0f, sample).status ==
              CARD_NO_DATA);
        CardRow nr = r;
        nr.ready = false;
        CHECK(CardTest(CardPackRow(nr), 77u | CARD_LAYER_READY, pool, 0, 0.2f, 0.2f, 0.0f, sample).status ==
              CARD_NO_DATA);
        auto bad = pool;
        bad[0] = CardPackTriangle({CardCorner{NAN, 0.0f, 1.0f}, CardCorner{}, CardCorner{}}, mode,
                                  mode, true);
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, bad, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
        bad[0] = CardPackTriangle({CardCorner{0.0f, 0.0f, 1.5f}, CardCorner{}, CardCorner{}}, mode,
                                  mode, true); // CARD_UV_TRI_ALPHA_RANGE
        CHECK(CardTest(row, 77u | CARD_LAYER_READY, bad, 0, 0.2f, 0.2f, 0.0f, sample).status == CARD_NO_DATA);
    }
    CHECK(checked == 1200 && differ == 0 && near_ref < checked / 4);
    // A border axis outside [0, 1] is no data; inside it is tested. Mirror once mirrors about 0.
    {
        std::vector<std::array<std::uint32_t, 4>> one{CardPackTriangle(
            {CardCorner{-0.5f, 0.5f, 1.0f}, CardCorner{-0.5f, 0.5f, 1.0f}, CardCorner{-0.5f, 0.5f, 1.0f}},
            CARD_UV_MODE_CLAMP, CARD_UV_MODE_CLAMP, true)};
        CardRow br;
        br.ready = true;
        br.triangles = 1;
        br.layer_gen = 5;
        br.mode_u = CARD_UV_MODE_CLAMP;
        br.mode_v = CARD_UV_MODE_CLAMP;
        br.reference = 0.5f;
        float u_seen = -1.0f;
        const auto flat = [&](std::uint32_t, float u, float, float) {
            u_seen = u;
            return 1.0f;
        };
        CardTestResult t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT && u_seen == 0.0f); // clamp to the last texel
        br.extra_u = CARD_AXIS_MIRROR_ONCE;
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT && std::abs(u_seen - 0.5f) < 1e-3f); // -0.5 mirrored to 0.5
        br.extra_u = CARD_AXIS_BORDER;
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_NO_DATA); // the border colour: not in the row
        br.extra_u = CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER; // mirrored inside: tested
        t = CardTest(CardPackRow(br), 5u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, flat);
        CHECK(t.status == CARD_KEPT);
        bool border = false;
        CHECK(CardRepeatAxis(1.5f, CARD_UV_MODE_CLAMP, CARD_AXIS_MIRROR_ONCE | CARD_AXIS_BORDER,
                             border) == 1.0f && border);
        border = false;
        CHECK(CardRepeatAxis(1.5f, CARD_UV_MODE_WRAP, CARD_AXIS_BORDER, border) == 0.5f && !border);
        CHECK(CardRepeatAxis(-0.25f, CARD_UV_MODE_CLAMP, CARD_AXIS_MIRROR_ONCE, border) == 0.25f &&
              !border);
        CHECK(CardRepeatAxis(NAN, CARD_UV_MODE_CLAMP, CARD_AXIS_BORDER, border) != 2.0f && border);
    }
    // The repeat of one axis.
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_WRAP) == 0.25f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_WRAP) == 0.75f);
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_MIRROR) == 0.75f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_MIRROR) == 0.25f);
    CHECK(CardRepeat(2.25f, CARD_UV_MODE_MIRROR) == 0.25f);
    CHECK(CardRepeat(1.25f, CARD_UV_MODE_CLAMP) == 1.0f);
    CHECK(CardRepeat(-0.25f, CARD_UV_MODE_CLAMP) == 0.0f);
}

void TestViewClass() {
    CHECK(CardViewClass(true, true, 5.0f, CARD_KEPT, 5.0f) == CARD_VIEW_SKY);
    CHECK(CardViewClass(false, false, 0.0f, CARD_NO_DATA, 5.0f) == CARD_VIEW_NO_CARD);
    // The game's depth at the card: kept by the game.
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 5.01f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 5.0f, CARD_DROPPED, 5.01f) == CARD_VIEW_RAY_DROPPED_GAME_KEPT);
    // Behind it: dropped by the game (the pixel sees through the card).
    CHECK(CardViewClass(false, true, 5.0f, CARD_DROPPED, 7.0f) == CARD_VIEW_AGREE_DROPPED);
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 7.0f) == CARD_VIEW_RAY_KEPT_GAME_DROPPED);
    // In front of it: something the scene does not hold.
    CHECK(CardViewClass(false, true, 5.0f, CARD_KEPT, 3.0f) == CARD_VIEW_NO_CARD);
    CHECK(CardViewClass(false, true, 5.0f, CARD_NO_DATA, 5.0f) == CARD_VIEW_NO_DATA);
    // The tolerance: 0.5 % + 2 cm (at 10 m: 7 cm).
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 10.06f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 10.09f) == CARD_VIEW_RAY_KEPT_GAME_DROPPED);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 9.94f) == CARD_VIEW_AGREE_KEPT);
    CHECK(CardViewClass(false, true, 10.0f, CARD_KEPT, 9.9f) == CARD_VIEW_NO_CARD);

    // The game's mip: a pixel covering 1/256 of the texture is level 0, 1/128 level 1; the
    // larger axis decides; a neighbour on another card is not used; none: 0.
    CHECK(std::abs(CardViewLod(1.0f / 256.0f, 0.0f, true, 0.0f, 0.0f, false)) < 1e-5f);
    CHECK(std::abs(CardViewLod(0.0f, 1.0f / 128.0f, true, 1.0f / 512.0f, 0.0f, true) - 1.0f) < 1e-5f);
    CHECK(std::abs(CardViewLod(1.0f / 1024.0f, 0.0f, true, 0.0f, 1.0f / 32.0f, false) + 2.0f) < 1e-5f);
    CHECK(std::abs(CardViewLod(0.03f, 0.04f, true, 0.0f, 0.0f, true) - std::log2(0.05f * 256.0f)) < 1e-5f);
    CHECK(CardViewLod(0.5f, 0.5f, false, 0.5f, 0.5f, false) == 0.0f);
    CHECK(CardViewLod(0.0f, 0.0f, true, 0.0f, 0.0f, true) == 0.0f);
    CHECK(CardViewLod(-1.0f / 64.0f, 0.0f, true, 0.0f, 0.0f, false) == 2.0f);
    // What is not judged: a sun pass card first, then a dithered one, then a coarse mip.
    CHECK(CardViewExcluded(0u, 0.0f) == 0u && CardViewExcluded(0u, 2.0f) == 0u);
    CHECK(CardViewExcluded(0u, 2.01f) == CARD_VIEW_COARSE);
    CHECK(CardViewExcluded(CARD_ROW_DITHER, 0.0f) == CARD_VIEW_DITHERED);
    CHECK(CardViewExcluded(CARD_ROW_SUN | CARD_ROW_DITHER, 5.0f) == CARD_VIEW_SUN_CARD);
    CHECK(CardViewExcluded(CARD_ROW_READY | 0x3ffu, 1.0f) == 0u);
    // A judged class of an excluded card counts as its reason; other classes as themselves.
    for (std::uint32_t c = CARD_VIEW_AGREE_KEPT; c <= CARD_VIEW_RAY_DROPPED_GAME_KEPT; ++c) {
        CHECK(CardViewCounter(c, 0) == c && CardViewCounter(c, CARD_VIEW_SUN_CARD) == CARD_VIEW_SUN_CARD);
    }
    for (const std::uint32_t c : {std::uint32_t(CARD_VIEW_NO_DATA), std::uint32_t(CARD_VIEW_NO_CARD),
                                  std::uint32_t(CARD_VIEW_SKY)}) {
        CHECK(CardViewCounter(c, CARD_VIEW_COARSE) == c);
    }
    CHECK(CARD_VIEW_COARSE + 1 == CARD_VIEW_COUNTERS && CARD_VIEW_SUN_CARD < CARD_VIEW_COUNTERS);
}

struct MockCutout {
    std::uint8_t verdict = 1;
    bool flag = true;
    std::uint16_t dword = 0xbeef;
    float ref = 0.392f;
    std::array<float, 2> scale{1.5f, -2.0f};
    std::uint32_t mask = 0x12345678u;
};

// A stand-in for Info::Cutout with the members and enums CardCutoutBytesValid reads, and
// padding (after `layer`).
struct ValidCutout {
    enum class Verdict : std::uint8_t { NotAnalysed, Matched, Other };
    enum class Detail : std::uint8_t { None, Clamped, Count };
    enum class Op : std::uint8_t { Less, NotEqual };
    enum class Ref : std::uint8_t { Immediate, ConstBuffer };
    enum class Layer : std::uint8_t { None, Other };
    Verdict verdict{};
    Detail detail{};
    Op op{};
    Ref ref_kind{};
    Ref ref2_kind{};
    Ref uv_kind{};
    Ref dither_kind{};
    Layer layer{};
    bool uv_by_constant{};
    bool uv_unrecorded{};
    bool texel_offset{};
    bool dither{};
    bool nonzero{};
    float ref = 0.5f;
};
static_assert(sizeof(ValidCutout) == 20 && offsetof(ValidCutout, ref) == 16);

void TestCutoutValid() {
    ValidCutout c;
    c.verdict = ValidCutout::Verdict::Other;
    c.detail = ValidCutout::Detail::Clamped;
    c.op = ValidCutout::Op::NotEqual;
    c.ref_kind = c.ref2_kind = c.uv_kind = c.dither_kind = ValidCutout::Ref::ConstBuffer;
    c.layer = ValidCutout::Layer::Other;
    c.uv_by_constant = c.uv_unrecorded = c.texel_offset = c.dither = c.nonzero = true;
    std::array<std::uint8_t, sizeof(ValidCutout)> b{};
    std::memcpy(b.data(), &c, sizeof(c));
    CHECK(CardCutoutBytesValid<ValidCutout>(b.data()));
    // Each enum one past its last value, each bool 2: refused.
    const std::size_t enums[] = {offsetof(ValidCutout, verdict), offsetof(ValidCutout, op),
                                 offsetof(ValidCutout, ref_kind), offsetof(ValidCutout, ref2_kind),
                                 offsetof(ValidCutout, uv_kind), offsetof(ValidCutout, dither_kind),
                                 offsetof(ValidCutout, layer)};
    for (const std::size_t at : enums) {
        auto bad = b;
        ++bad[at];
        CHECK(!CardCutoutBytesValid<ValidCutout>(bad.data()));
    }
    auto bad = b;
    bad[offsetof(ValidCutout, detail)] = std::uint8_t(ValidCutout::Detail::Count); // Count itself
    CHECK(!CardCutoutBytesValid<ValidCutout>(bad.data()));
    const std::size_t bools[] = {offsetof(ValidCutout, uv_by_constant), offsetof(ValidCutout, uv_unrecorded),
                                 offsetof(ValidCutout, texel_offset), offsetof(ValidCutout, dither),
                                 offsetof(ValidCutout, nonzero)};
    for (const std::size_t at : bools) {
        auto two = b;
        two[at] = 2;
        CHECK(!CardCutoutBytesValid<ValidCutout>(two.data()));
    }
    // The other bytes are not looked at (the float, the padding).
    auto other = b;
    other[offsetof(ValidCutout, ref)] = 0xff;
    other[offsetof(ValidCutout, nonzero) + 1] = 0xff;
    CHECK(CardCutoutBytesValid<ValidCutout>(other.data()));
}

void TestCutoutPart() {
    MockCutout m;
    const std::uint32_t version = CardCutoutVersion(7);
    CHECK(version == ((CardCutoutFormat << 16) | 7u) && CardCutoutVersion(8) != version);
    std::vector<std::uint8_t> bytes(CardCutoutBytes<MockCutout> + 4, 0xcd);
    CardCutoutEncode(m, version, {}, bytes.data());
    std::uint32_t tag = 0;
    std::memcpy(&tag, bytes.data(), 4);
    CHECK(tag == CardCutoutTag && std::memcmp(bytes.data(), "CUT1", 4) == 0);
    const std::uint8_t* payload = nullptr;
    std::size_t used = CardCutoutPart<MockCutout>(bytes.data(), bytes.size(), version, payload);
    CHECK(used == CardCutoutBytes<MockCutout> && payload == bytes.data() + CardCutoutHeader);
    MockCutout back{};
    back.verdict = 0;
    back.flag = false;
    std::memcpy(&back, payload, sizeof(back));
    CHECK(back.verdict == 1 && back.flag && back.dword == 0xbeef && back.ref == 0.392f &&
          back.scale[1] == -2.0f && back.mask == 0x12345678u);
    // Another version (another analysis, or another format): skipped whole, nothing taken.
    used = CardCutoutPart<MockCutout>(bytes.data(), bytes.size(), CardCutoutVersion(8), payload);
    CHECK(used == CardCutoutBytes<MockCutout> && payload == nullptr);
    std::vector<std::uint8_t> other = bytes;
    // Another size (the struct changed without a new version): skipped by its own size.
    const std::uint32_t size2 = sizeof(MockCutout) - 4;
    std::memcpy(other.data() + 8, &size2, 4);
    used = CardCutoutPart<MockCutout>(other.data(), other.size(), version, payload);
    CHECK(used == CardCutoutHeader + size2 && payload == nullptr);
    // Cut short: broken.
    CHECK(CardCutoutPart<MockCutout>(bytes.data(), CardCutoutBytes<MockCutout> - 1, version, payload) == 0);
    CHECK(CardCutoutPart<MockCutout>(bytes.data(), 8, version, payload) == 0);
    // Not this tag.
    std::vector<std::uint8_t> fry = bytes;
    std::memcpy(fry.data(), "FRY1", 4);
    CHECK(CardCutoutPart<MockCutout>(fry.data(), fry.size(), version, payload) == 0);
    // Padding: whatever the struct's padding bytes hold, the part has 0 there; the values stay.
    ValidCutout v;
    std::memset(static_cast<void*>(&v), 0xcd, sizeof(v));
    v.verdict = ValidCutout::Verdict::Matched;
    v.nonzero = true;
    v.ref = 0.25f;
    const std::size_t pad[] = {offsetof(ValidCutout, nonzero) + 1, offsetof(ValidCutout, nonzero) + 2,
                               offsetof(ValidCutout, nonzero) + 3, 999};
    std::array<std::uint8_t, CardCutoutBytes<ValidCutout>> part{};
    CardCutoutEncode(v, version, pad, part.data());
    const std::uint8_t* body = part.data() + CardCutoutHeader;
    CHECK(body[pad[0]] == 0 && body[pad[1]] == 0 && body[pad[2]] == 0);
    ValidCutout back_v;
    std::memcpy(static_cast<void*>(&back_v), body, sizeof(back_v));
    CHECK(back_v.verdict == ValidCutout::Verdict::Matched && back_v.nonzero && back_v.ref == 0.25f);
    // Two encodes of equal values with other padding bytes are equal byte for byte.
    ValidCutout w = v;
    std::memset(reinterpret_cast<std::uint8_t*>(&w) + pad[0], 0x11, 3);
    std::array<std::uint8_t, CardCutoutBytes<ValidCutout>> part2{};
    CardCutoutEncode(w, version, pad, part2.data());
    CHECK(part == part2);
}

} // namespace

int main() {
    TestSizes();
    TestViewKnob();
    TestSource();
    TestKey();
    TestFillLod();
    TestTable();
    TestRows();
    TestCardTest();
    TestViewClass();
    TestCutoutValid();
    TestCutoutPart();
    if (failures != 0) {
        std::printf("rt-card-layers-test: %d failed\n", failures);
        return 1;
    }
    std::printf("rt-card-layers-test: all passed\n");
    return 0;
}
""",
}

RT_ROWS = r"""// bbport (r62_leaf-stage3): the card table (BB_RT_CARD_ALPHA=2): CardRowsBytes, one row a card
// slot, made at the first PrepareScene with the knob, zeroed (no row READY). Device memory: rays
// read it; only changed rows are written, in stream order.
bool RtShadow::CardRowsMake() {
    if (card_rows.buffer) {
        return true;
    }
    if (card_rows_failed) {
        return false;
    }
    if (!Make(card_rows, CardRowsBytes, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)) {
        Free(card_rows);
        card_rows_failed = true;
        std::printf("Card alpha layers (r62): no card table (%llu bytes): no card has a row\n",
                    static_cast<unsigned long long>(CardRowsBytes));
        return false;
    }
    scheduler.EndRendering();
    scheduler.Record([rows = card_rows.buffer](vk::CommandBuffer cmdbuf) {
        cmdbuf.fillBuffer(rows, 0, CardRowsBytes, 0);
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite,
                                  vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
    return true;
}

// The rows of the entries this scene holds (drawn and held), at each PrepareScene: a row is
// written when it changed (its card state, its layer, its rule or its offset), at most
// CardRowUpdatesPerCall a call (the rest at the next call; counted). Recorded before the TLAS
// build and every ray of this call in stream order. An entry's first row being written changes
// its instance's custom index from 0 to its slot (CardCustomIndex) at the next TLAS write: at
// the latest the frame's next first PrepareScene (OnFrameEnd sets tlas_count to 0, so that one
// always writes the TLAS). No extra build is forced here: a second build in one frame writes
// the instance records into the same ring slot (frame % 4) the frame's earlier build may still
// be reading on the GPU. Until then the instance reads as not a card (custom index 0).
// A slot is the entry's for as long as its pool block (CardTakeBlock to CardRelease); a slot
// given to a new entry gets the new entry's row before its instance carries the slot.
void RtShadow::CardRows() {
    if (!CardRowsMake()) {
        return;
    }
    struct Update {
        u32 slot = 0;
        std::array<u32, CARD_ROW_WORDS> row{};
    };
    std::array<Update, CardRowUpdatesPerCall> updates{};
    u32 n = 0;
    const auto visit = [&](Entry* entry) {
        if (!entry || !entry->card_uv || entry->card_uv->slot == 0) {
            return;
        }
        CardUvEntry& c = *entry->card_uv;
        const auto row = CardPackRow(CardRowFor(c.uv, c.offset, entry->triangles));
        if (c.row_written && row == c.row) {
            return;
        }
        if (n == updates.size()) {
            ++card_row_counts.deferred;
            return;
        }
        updates[n++] = {c.slot, row};
        c.row = row;
        c.row_written = true;
        ++card_row_counts.written;
        card_row_counts.ready += (row[2] & CARD_ROW_READY) != 0 ? 1 : 0;
    };
    for (Entry* entry : frame_entries) {
        visit(entry);
    }
    for (Entry* entry : held_now) {
        visit(entry);
    }
    if (n == 0) {
        return;
    }
    scheduler.EndRendering();
    scheduler.Record([updates, n, rows = card_rows.buffer](vk::CommandBuffer cmdbuf) {
        // After every earlier reader of the rows (rays recorded before).
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                                  vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite);
        for (u32 i = 0; i < n; ++i) {
            cmdbuf.updateBuffer(rows, vk::DeviceSize(updates[i].slot) * CARD_ROW_BYTES,
                                sizeof(updates[i].row), updates[i].row.data());
        }
        EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                  vk::AccessFlagBits2::eTransferWrite,
                                  vk::PipelineStageFlagBits2::eAllCommands,
                                  vk::AccessFlagBits2::eMemoryRead);
    });
}

"""
FX_LAYER = r"""// bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the image a cut-out draw's card reads its alpha
// from, for its layer (CardAlpha::NoteDraw). This draw's own binding of its pixel shader's
// textures (BindTextures, before EffectsCaptureDraw) left what it found in the draw context
// (DrawContext::card_bound): from the texture set memo on a set hit, from its lookups otherwise.
// Not from the binding memo (image_desc_cache): a set hit does not touch it, so another T# may
// have evicted the card texture's entry while the card's draws keep hitting their set. The
// record is taken only when it is this pixel shader's (the stage pointer) and holds one image a
// shader image (no mip arrays); its image must still be the registered image of its uid
// (NoteDraw). Otherwise no layer this draw; a later draw of the card may.
void Rasterizer::NoteCardLayer(CardDraw& card, const Shader::Info& ps) {
    const DrawContext::CardBound& bound = Dc().card_bound;
    if (bound.stage == &ps) {
        for (u32 i = 0; i < bound.count && i < ps.images.size(); ++i) {
            const auto& res = ps.images[i];
            const AmdGpu::Image sharp = res.GetSharp(ps);
            static_assert(sizeof(sharp) == sizeof(card.tsharp));
            if (std::memcmp(&sharp, card.tsharp.data(), sizeof(card.tsharp)) != 0) {
                continue;
            }
            if (bound.ids[i]) {
                card_alpha->NoteDraw(card, sharp, res, bound.ids[i], bound.uids[i]);
                return;
            }
            break;
        }
    }
    card_alpha->NoteNoSource(card);
}

"""
DOC_STAGE3 = r"""## Stage 3: alpha layers, card table, debug view, cache tag (r62, BB_RT_CARD_ALPHA=2)

Status: a draft (r62, revision 1). Off by default. With `BB_RT_CARD_ALPHA=2` the chain a stage 4
ray will use is built and can be looked at; no shadow reads it, so no shadow changes. With the
knob unset or `1` no CardAlpha is made and no draw calls into it (one test of a bool in the draw
path and in BindTextures).

### The knobs

| Variable | Values | What it does |
|---|---|---|
| `BB_RT_CARD_ALPHA` | `2` | Stage 2's UVs and this stage: layers, card table, instance custom index. Read once. The CUT1 cache part is written and read with any level from `1` up (and with the log knob). |
| `BB_RT_CARD_ALPHA_VIEW` | unset, `0`: off. `1` overlay, `2` alpha, `3` coordinates. Anything else: off, said once. | The debug view. Environment only (never saved in the ini). Only with `BB_RT_CARD_ALPHA=2`; set without it, the log says it is off. It runs before the upscaler: with the upscaler off it has no place in the frame, and the log says so once. |

### What runs

1. At a cut-out draw with card data (EffectsCaptureDraw, after ResolveCardDraw), the draw's
   alpha texture is found among the pixel shader's images by its T# (the card's), and its image
   in what this draw's own texture binding found (DrawContext::card_bound: on a texture set hit
   the set's entries, otherwise the lookups; written by BindTextures only with the knob). Not in
   the binding memo: a set hit does not touch it, so another T# may have evicted the card
   texture's entry while the card's draws keep hitting their set. CardAlpha::NoteDraw checks the
   texture (a plain 2D, not multisampled, no number conversion, Unorm, Srgb or Float, a lane that
   reads the stored channel the test reads, not a depth image, still the registered image of its
   uid), keys it by the T# and the lane, and gives it a layer: `CardDraw::layer` (layer + 1) and
   `layer_gen`. They travel with the card into the entry (CardNote copies the card). A
   256-byte hint finds a known key without the scan of the 128 layers.
2. A layer is a slice of one R8 2D array, 256 x 256, 3 levels, 128 slices. The fill
   (rt_card_alpha_fill.comp) samples the game's own view of the texture (Image::FindView with the
   draw's T# and resource), so BC1 (its punch-through alpha decodes to 0 or 1), BC3, BC7 and
   sRGB views are decoded by the hardware as for the game, and the view's component mapping is
   the T#'s DstSelect, so the lane read is the test's. The source level comes from the smaller
   side (log2(ratio) - 1; a 2048x128 source keeps its 128 rows), and each axis takes as many
   bilinear taps as source texels it covers there (1 to 8, CardFillLod). Fills are recorded by
   RtShadow::PrepareCapture, before any reader of the scene, at most 8 a frame. An image whose
   memory the CPU wrote and nobody uploaded yet (Dirty flags) is not read: the fill waits for the
   next draw that binds it (counted "put off").
3. A texture streamed in, replaced or written while its card lives: the image's write counter
   (Image::write_seq) changes and the layer is filled again; the old fill stays readable
   meanwhile. If another image (another ImageId or uid) now answers the same T# words, the layer
   stops being READY until its refill (counted "dropped"): rays read no data, never the old
   image's alpha. An image gone before its fill: the layer waits for a draw that binds a living
   one. A layer goes to another texture only when it was not used this frame or the last (least
   recently used first); its generation moves on, and every row naming the old generation reads
   as no data.
4. RtShadow writes one 32-byte row a card slot (rt_card_layers_layout.h, CARD_ROW_*): the pool
   offset, the triangles, the layer and its generation, the op, the nonzero term, the axis modes
   and their extras (mirror once, border), the reference, the offset, the dither's coefficient,
   whether the rule is the sun shadow pass card's. A row is READY when the entry's records are
   Ready, its card not stale and it has a layer. Only changed rows are written (64 a call at
   most).
5. The TLAS instance of an entry with a written row carries its card slot as
   `instanceCustomIndex` (0 otherwise). A first row does not force a TLAS build: the slot appears
   at the next TLAS write, at the latest the next frame's first scene (a second build in one
   frame would write its instance records into the ring slot the frame's first build may still
   be reading). No shader before the debug view reads it.
6. The debug view (rt_card_view.comp, before the upscaler) traces, per pixel, a ray from the
   camera to the depth point through the TLAS without the opaque flag, tests the nearest card
   candidate in front of the first other hit with `cardTestLod` (rt_cards.glsl) and compares it
   with the game: the depth at the candidate means the game kept that texel, the depth behind it
   means the game dropped it. The game ran its alpha test at its own mip; far or grazing leaves
   read a coarse, blurred level. The view estimates that mip from the coordinates' difference to
   the neighbouring pixels on the same card (CardViewLod: log2 of the larger footprint times 256;
   isotropic, as the hardware without anisotropic filtering) and reads the layer level that
   matches it (0 to 2).

### Debug view colours

| Mode | What it shows |
|---|---|
| 1 overlay | green: both kept; cyan: both dropped; red: the ray kept, the game dropped; magenta: the ray dropped, the game kept; blue: a card without data (no row, not READY, layer not filled, reused or dropped, a border axis outside its range). Hatched (every other pixel untinted): a card the GO line does not judge (below). Everything else untouched. |
| 2 alpha | grey: the A a ray computes (texel times the vertex factor) on card pixels, at the matched level; the rest darkened. |
| 3 coordinates | red: u, green: v, as the ray reads the layer; the rest darkened. |

Not judged (counted by reason, drawn hatched):
- a sun pass card: r54 prefers the sun shadow pass's card for an entry both passes draw, so its
  row holds the sun pass's reference (0.196 in the r50c log), while the camera pass tests 0.039
  to 0.892 (hair and cloth 0.039 and 0.502): wide red or magenta bands there are by design;
- a dithered card (a coefficient not 0, as 998b035e with cb21 = 1: the game's threshold moves per
  pixel from 0.892 down to -0.108);
- a pixel whose game mip is coarser than the layers' last level (level 2).
Also red, and judged: an instance faded to 0 (the fade is left out of the rule, r50c): the game
drops it, the ray keeps it.

The overlay is written into the scene colour before TAA or FSR, so it enters the upscaler's
history and smears in motion: judge it standing still.

### Memory (numbers)

| What | Bytes | When |
|---|---|---|
| Alpha layers: 128 x (65,536 + 16,384 + 4,096) | 11,010,048 (10.5 MiB) | at start, with the knob |
| Layer info: 128 x 4 | 512 | at start, with the knob |
| Card table: 65,536 rows x 32 | 2,097,152 (2 MiB) | at the first ray traced scene with the knob |
| Debug view counters and readback | 2 x 48 | at the first view |
| CPU: CardAlpha (layer table 128 x 72, hint 256, fill views 128 x ImageViewInfo, queue) | about 17 KB | at start, with the knob only |
| CPU: CardUvEntry row and flag | 33 (about 40 with alignment) a cut-out entry | with `BB_RT_CARD_ALPHA` 1 or 2 (CardUvEntry is made only then) |
| CPU: CardDraw layer, generation, raw clamp modes | 10 a card | on the stack at a draw, and in each CardUvEntry |
| CPU: DrawContext::card_bound | 208 a draw context | for every player (written only with the knob) |

At 512 x 512 the layers would take 44,040,192 bytes (42 MiB). A typical scene (the r46b plant
spot: tens of cut-out textures) uses a few dozen layers; the array is made whole once so its
descriptors never change.

### Cost (estimates, not measured)

- A fill: 65,536 threads, about 86,000 texels written, 4 bilinear taps each for a square source
  (up to 8 on an axis for a long thin source, 64 for a large one without mips); on a current
  desktop GPU of the order of 0.01 to 0.02 ms for the square case (basis: a full-screen 4K
  compute pass of similar work, 8.3 M threads, takes about 0.5 to 1 ms on such a GPU; this is
  1/100 of it). 8 a frame at most: under 0.2 ms in the worst usual frame, 0 in a frame with no
  new or changed card texture.
- Rows: 64 updateBuffer calls of 32 bytes a call at most.
- The draw path: per cut-out draw a T# compare per image of the pixel shader, the hint (one key
  compare) and, for a key the hint does not hold, a scan of 128 layers (CPU, not measured).
  BindTextures of a pixel shader: up to 16 id and uid copies, with the knob only.
- The debug view: one ray a pixel with candidate loops and two card tests; a debug cost only
  (it is off unless set).

### The cache tag CUT1 (r54 open point 2)

A pixel shader's cache record gets a tagged tail part "CUT1": a version, the payload's size and
Info::Cutout's bytes, its three padding bytes written as 0 (vk_pipeline_serialization.cpp). It
is written whenever the shader's info holds an analysed cut-out record: analysed in a run with
`BB_RT_CARD_ALPHA` (any level) or `BB_RT_CARD_ALPHA_LOG`, or restored from a CUT1 part (a run
with no knob that saves a new permutation of such a shader keeps it). With `BB_RT_CARD_ALPHA`
alone the warm-up takes a discarding pixel shader whose record has the part (its card data comes
from the restored cut-out record); one without it compiles once in play and is saved with it.
`BB_RT_CARD_ALPHA_LOG=1` still refuses them all (its shader lines need the IR). The version is
the part's format and `CutoutAnalysisVersion` (cutout_analysis.h): bump the latter with any
change of the matcher, even one that keeps the struct's size. A part of another version or size
is skipped by its size. An engine without r62 reading a record with the part fails that record
and compiles the shader in play (it does not know the tag). The capture vertex shaders with
CaptureUv are their own permutations (the motion bits are in the runtime info) and are saved
after their first compile, so they too compile in play only on the first run with the knob.

For every player, knob or not: an engine with r62 has another gpu-cache.id (build.sh hashes
shader_recompiler/ and vk_pipeline_serialization.cpp), so at its first start the starter has
bb-shader-lab recompile the shader cache, or clears it (ResetStaleGpuCache), as after any change
to those files (r54 did the same). That recompile runs in the starter's environment and analyses
cut-outs only if `BB_RT_CARD_ALPHA` is set there: without it the records lose their CUT1 parts,
and after each engine update that changes the id the discarding pixel shaders compile in play
once more on the next run with the knob.

### Stage 4's hooks

- Bindings (rt_cards.glsl): the including shader names four bindings of set 0: the card table
  (`RtShadow::CardTables().rows`), the pool (`.pool`), the layer info and the layer array with
  its sampler (`CardAlpha::ReaderBindings()`; the sampler reads all three levels).
- Per instance: `instanceCustomIndex` is the card slot; the slot's row holds the instance's
  offset into the pool (word 0, in 16-byte records), so a candidate's record is
  `pool[row.word0 + primitive index]` (bounded by word 1 and by the pool's length).
- The 16-byte triangle record: r54's (rt_card_uv_layout.h); the reader adds the row's offset and
  repeats each axis as the row's modes and extras say.
- The alpha layer index: row word 2 bits 0-9, its generation word 7, checked against the layer
  info.
- The rule: row word 3 (the reference), word 2 bits 10-12 (the op) and bit 13 (nonzero); bit 18
  says the camera pass dithers with a coefficient not 0 (taken as 0, as stage 2 does), word 6
  its coefficient; bit 19 says the rule is the sun shadow pass's.
- The level: `cardTest` reads level 0 (lamps); `cardTestLod` another (the sun's mip 1, the
  bounce's mip 2 in stage 6).
- What stage 4 adds: CardLampMask 0x08, FORCE_NO_OPAQUE on card instances (or the no-opaque ray
  flag), a candidate loop calling `cardTest`, hysteresis, `BB_RT_CARD_LAMPS`, view 7.

### What the log must show (stage 3)

With `BB_RT_CARD_ALPHA=2 BB_RT_CARD_ALPHA_VIEW=1`, ray tracing on, the upscaler on, the r46b
plant spot, standing still:
- at start one `Card alpha layers (r62): BB_RT_CARD_ALPHA=2: on; 128 layers of 256x256 R8, 3
  levels (11010048 bytes) ... debug view BB_RT_CARD_ALPHA_VIEW=1 (overlay) ...` line, and r54's
  start line naming `BB_RT_CARD_ALPHA=2`;
- every 600 frames `Card alpha layers (r62): 600 frames: ...`: card draws above 0 and most of
  them found by the hint, layers given and fills above 0 in the first line, refills and dropped
  0 or few while standing still, "full" 0, "no source" a small share of the card draws, rows
  written above 0 with ready above 0, "views" near 600 and skipped near 0;
- every 120 view frames `Card debug view (r62): 120 frames, ...`: card candidates above 0;
  judged pixels agree at or above 95 %; the not judged counts (sun pass cards, dithered, game
  mip coarser) shown apart; no data falling to a small share once the cards are Ready;
- the picture with the view: green on leaves, cyan in their holes, red or magenta only as thin
  fringes at leaf edges of judged cards (hatched cards may show wide bands, see above); with
  `BB_RT_CARD_ALPHA_VIEW` unset the picture as with the knob unset;
- with both knobs unset no `(r62` line.

## Not done in this stage

The lamp rays (stage 4), the decision point for a lamp card map (4b), characters, hair and cloth
(5), the sun and the bounced light (6), and the cost levers (7).
"""

EDITS = {
    R + "rt_card_uv.h": [
        (r"""/// BB_RT_CARD_ALPHA: unset, "0" or anything else off; "1": the card UVs (capture and pool), all
/// stage 2 does. Later stages take levels above 1. Read once (CardAlphaOn in cutout_analysis.h).
inline constexpr std::uint32_t CardAlphaOff = 0;
inline constexpr std::uint32_t CardAlphaUv = 1;
[[nodiscard]] constexpr std::uint32_t ReadCardAlpha(const char* text) noexcept {
    return text && text[0] == '1' && text[1] == '\0' ? CardAlphaUv : CardAlphaOff;
}
/// Set but neither "0" nor "1": said once in the log, as off.
[[nodiscard]] constexpr bool CardAlphaMisread(const char* text) noexcept {
    return text && !((text[0] == '0' || text[0] == '1') && text[1] == '\0');
}
""",
         r"""/// BB_RT_CARD_ALPHA: unset, "0" or anything else off; "1": the card UVs (capture and pool), all
/// stage 2 does; "2" (r62_leaf-stage3): the UVs and stage 3's alpha layers, card table and
/// instance custom index (rt_card_layers.h). Read once (CardAlphaLevel in cutout_analysis.h).
inline constexpr std::uint32_t CardAlphaOff = 0;
inline constexpr std::uint32_t CardAlphaUv = 1;
inline constexpr std::uint32_t CardAlphaLayers = 2;
[[nodiscard]] constexpr std::uint32_t ReadCardAlpha(const char* text) noexcept {
    return text && (text[0] == '1' || text[0] == '2') && text[1] == '\0'
               ? std::uint32_t(text[0] - '0')
               : CardAlphaOff;
}
/// Set but not "0", "1" or "2": said once in the log, as off.
[[nodiscard]] constexpr bool CardAlphaMisread(const char* text) noexcept {
    return text && !((text[0] == '0' || text[0] == '1' || text[0] == '2') && text[1] == '\0');
}
"""),
        (r"""    std::uint64_t constants_hash = 0;
};
""",
         r"""    std::uint64_t constants_hash = 0;
    /// bbport (r62_leaf-stage3): with BB_RT_CARD_ALPHA=2 the card's alpha layer + 1 (0: none)
    /// and the layer's generation when it was given (CardAlpha::NoteDraw). In neither hash: a
    /// layer changes no record, only the card's row (CardRowFor).
    std::uint32_t layer = 0;
    std::uint32_t layer_gen = 0;
    /// bbport (r62_leaf-stage3): the sampler's raw clamp modes (AmdGpu::ClampMode 0-7, in
    /// constants_hash): mode_u/v say CLAMP for all of 2-7; the card's row adds mirror once and
    /// border (CardAxisExtra, rt_card_layers.h).
    std::uint8_t clamp_u = 0;
    std::uint8_t clamp_v = 0;
};
"""),
        (r"""        0u, 0u};
    d.constants_hash = CardHashWords(d.tsharp, CardHashWords(rest, d.uv_hash));
""",
         r"""        std::uint32_t(d.clamp_u) | (std::uint32_t(d.clamp_v) << 8), 0u}; // (r62) raw modes
    d.constants_hash = CardHashWords(d.tsharp, CardHashWords(rest, d.uv_hash));
"""),
    ],
    TESTS + "test_rt_card_uv.cpp": [
        (r"""    CHECK(ReadCardAlpha("2") == CardAlphaOff); // later stages' levels are not this stage's
""",
         r"""    CHECK(ReadCardAlpha("2") == CardAlphaLayers); // (r62_leaf-stage3) stage 3's level
    CHECK(ReadCardAlpha("3") == CardAlphaOff);
"""),
        (r"""    CHECK(CardAlphaMisread("2"));
""",
         r"""    CHECK(!CardAlphaMisread("2")); // (r62_leaf-stage3)
    CHECK(CardAlphaMisread("3"));
"""),
    ],
    P + "cutout_analysis.h": [
        (r"""[[nodiscard]] bool CardAlphaOn();
""",
         r"""[[nodiscard]] bool CardAlphaOn();

/// (r62_leaf-stage3) BB_RT_CARD_ALPHA's level, read once (Vulkan::ReadCardAlpha): 0 off, 1 the
/// card UVs, 2 the UVs and the alpha layers (CardAlpha). CardAlphaOn() is level >= 1.
[[nodiscard]] u32 CardAlphaLevel();

/// (r62_leaf-stage3) The version of what AnalyzeCutout writes into Info::Cutout. The CUT1 cache
/// part carries it (vk_pipeline_serialization.cpp): bump it with ANY change of the matcher or of
/// what a field means, even one that keeps the struct's size (r50b and r50c would have needed
/// it), so no cache record keeps a verdict of an older matcher.
inline constexpr u32 CutoutAnalysisVersion = 1;
"""),
    ],
    P + "cutout_analysis_pass.cpp": [
        (r"""bool CardAlphaOn() {
    static const bool on = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA");
        if (Vulkan::CardAlphaMisread(env)) {
            std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is neither 0 nor 1: "
                        "off\n",
                        env);
        }
        return Vulkan::ReadCardAlpha(env) == Vulkan::CardAlphaUv;
    }();
    return on;
}
""",
         r"""u32 CardAlphaLevel() {
    static const u32 level = [] {
        const char* env = std::getenv("BB_RT_CARD_ALPHA");
        if (Vulkan::CardAlphaMisread(env)) {
            std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is not 0, 1 or 2: "
                        "off\n",
                        env);
        }
        return Vulkan::ReadCardAlpha(env);
    }();
    return level;
}

bool CardAlphaOn() {
    return CardAlphaLevel() >= Vulkan::CardAlphaUv; // (r62_leaf-stage3) 2: the UVs and the layers
}
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""#include "video_core/renderer_vulkan/rt_card_uv.h"     // bbport (r54_leaf-stage2)
""",
         r"""#include "video_core/renderer_vulkan/rt_card_uv.h"     // bbport (r54_leaf-stage2)
#include "video_core/renderer_vulkan/rt_card_layers.h" // bbport (r62_leaf-stage3)
"""),
        (r"""class RtShadow {
public:
""",
         r"""class CardAlpha; // bbport (r62_leaf-stage3)

class RtShadow {
public:
"""),
        (r"""    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {
        return tlas;
    }
""",
         r"""    [[nodiscard]] vk::AccelerationStructureKHR Scene() const noexcept {
        return tlas;
    }
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2. The card layers (CardAlpha, the rasterizer
    // owns it; null when off or when its layers could not be made), whose fills PrepareCapture
    // records before every reader of the scene: the rows and custom indices only with them. The
    // card table (one row a card slot; null until the first scene with them) and r54's pool, for
    // the readers (rt_cards.glsl). The row counts for CardAlpha's 600-frame line.
    void SetCardLayers(CardAlpha* layers) noexcept {
        card_layers = layers;
        card_layers_on = layers != nullptr;
    }
    struct CardTablesView {
        vk::Buffer rows;
        vk::Buffer pool;
    };
    [[nodiscard]] CardTablesView CardTables() const noexcept {
        return {card_rows.buffer, card_pool.buffer};
    }
    struct CardRowCounts {
        u64 written = 0, ready = 0, deferred = 0;
    };
    CardRowCounts TakeCardRowCounts() noexcept {
        const CardRowCounts counts = card_row_counts;
        card_row_counts = {};
        return counts;
    }
"""),
        (r"""        u64 taken_frame = 0;
        bool pending = false;
    };
""",
         r"""        u64 taken_frame = 0;
        bool pending = false;
        // bbport (r62_leaf-stage3): the card row last written for this entry's slot (CardRows)
        std::array<u32, CARD_ROW_WORDS> row{};
        bool row_written = false;
    };
"""),
        (r"""    void CardFrameEnd();
    void CardLog();
""",
         r"""    void CardFrameEnd();
    void CardLog();
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2 with its layers made (card_layers_on, set by
    // SetCardLayers at the rasterizer's start): the card table (card_rows, CardRowsBytes, made at
    // the first PrepareScene with them; CardRows), the layers to fill before a reader
    // (card_layers), the row counts since CardAlpha's last line.
    bool card_layers_on = false;
    bool card_rows_failed = false;
    CardAlpha* card_layers = nullptr;
    Buffer card_rows;
    CardRowCounts card_row_counts;
    bool CardRowsMake();
    void CardRows();
    /// A TLAS instance's custom index: its card slot once the slot's row is written, else 0.
    [[nodiscard]] u32 CardCustomIndex(const Entry& entry) const noexcept {
        return card_layers_on && entry.card_uv && entry.card_uv->row_written ? entry.card_uv->slot
                                                                             : 0u;
    }
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""#include "video_core/renderer_vulkan/vk_camera_motion.h"
""",
         r"""#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
"""),
        (r"""    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback}) {
""",
         r"""    for (Buffer* b : {&card_ring, &card_pool, &card_stat_buffer, &card_readback, &card_rows}) {
"""),
        (r"""        std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=1 but off - no pipeline or "
                    "buffer for them\n");
""",
         r"""        std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%u but off - no pipeline or "
                    "buffer for them\n",
                    Shader::Optimization::CardAlphaLevel()); // (r62) the level read
"""),
        (r"""    std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=1, the cut-out cards' UVs are captured "
                "(ring %llu MiB now, pool %llu MiB at the first card); no ray reads them yet, the "
                "picture is unchanged\n",
""",
         r"""    std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%u, the cut-out cards' UVs are captured "
                "(ring %llu MiB now, pool %llu MiB at the first card); no ray reads them yet, the "
                "picture is unchanged\n",
                Shader::Optimization::CardAlphaLevel(), // (r62) the level read
"""),
        (r"""        "Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=1): %u cut-out entries [ready, pending, "
""",
         r"""        "Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=%u): %u cut-out entries [ready, pending, "
"""),
        (r"""        card_entries, cls(CardClass::Plant, Ready), cls(CardClass::Plant, Pending),
""",
         r"""        Shader::Optimization::CardAlphaLevel(), // (r62) the level read
        card_entries, cls(CardClass::Plant, Ready), cls(CardClass::Plant, Pending),
"""),
        (r"""    RecordBuilds();
    return Complete() && camera_motion.PassMatrices().valid;
""",
         r"""    RecordBuilds();
    // bbport (r62_leaf-stage3): the card layers a reader of the scene may test, filled first.
    if (card_layers) {
        card_layers->RecordFills();
    }
    return Complete() && camera_motion.PassMatrices().valid;
"""),
        (r"""    CollectHeld();
    const u32 count = std::min<u32>(u32(frame_entries.size() + held_now.size()), MaxInstances);
""",
         r"""    CollectHeld();
    const u32 count = std::min<u32>(u32(frame_entries.size() + held_now.size()), MaxInstances);
    // bbport (r62_leaf-stage3): the changed card rows, before the TLAS (a first row of an entry
    // writes the TLAS again: its instance takes its slot as custom index).
    if (card_layers_on) {
        CardRows();
    }
"""),
        (r"""        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),
""",
         r"""        vk::AccelerationStructureInstanceKHR record{
            .instanceCustomIndex = CardCustomIndex(*entry), // bbport (r62_leaf-stage3)
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),
"""),
        (r"""void RtShadow::OnFrameEnd() {
""",
         RT_ROWS + r"""void RtShadow::OnFrameEnd() {
"""),
    ],
    R + "vk_rasterizer.h": [
        (r"""#include "video_core/renderer_vulkan/vk_drawn_look.h"
""",
         r"""#include "video_core/renderer_vulkan/vk_drawn_look.h"
#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
"""),
        (r"""    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)
""",
         r"""    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)
    // bbport (r62_leaf-stage3): made only with BB_RT_CARD_ALPHA=2 (CardAlpha::Wanted), else null;
    // card_bound_on: it is made and on (set once, at the start; read by the binding helper too):
    // BindTextures notes what a pixel shader's binding found (DrawContext::card_bound) and a
    // cut-out draw asks for its card's layer.
    std::unique_ptr<CardAlpha> card_alpha;
    bool card_bound_on = false;
"""),
        (r"""    bool LookupMemoized(ImageDescCacheEntry& entry, u64 generation);
""",
         r"""    bool LookupMemoized(ImageDescCacheEntry& entry, u64 generation);
    /// bbport (r62_leaf-stage3): a cut-out draw's card gets its alpha layer (CardAlpha::NoteDraw)
    /// from the image this draw's pixel shader binding found for the card's T# (card_bound).
    void NoteCardLayer(CardDraw& card, const Shader::Info& ps);
"""),
        (r"""        DrawInputs draw_inputs{};
    };
""",
         r"""        DrawInputs draw_inputs{};
        // bbport (r62_leaf-stage3): with card_bound_on, what the pixel shader's texture binding
        // of this draw found, image by image (a texture set hit: the set's entries; otherwise its
        // lookups, before any depth redirect), with the image uids, for NoteCardLayer. stage:
        // the pixel shader it is for (null: not known, as when an image took several bindings).
        // 208 bytes a draw context, made for every player; written only with the knob.
        struct CardBound {
            const Shader::Info* stage = nullptr;
            u32 count = 0;
            std::array<VideoCore::ImageId, TextureSet::MaxImages> ids{};
            std::array<u64, TextureSet::MaxImages> uids{};
        } card_bound;
    };
"""),
    ],
    R + "vk_rasterizer.cpp": [
        (r"""    if (!upscaler->Enabled()) {
        DrawnLook::NoSceneHooks();
    }
""",
         r"""    if (!upscaler->Enabled()) {
        DrawnLook::NoSceneHooks();
    }
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the card alpha layers (made here, once);
    // otherwise no CardAlpha is made, RtShadow gets none and no draw calls in. Its debug view
    // runs before the upscaler: without it, the view has no place in the frame (said once).
    if (CardAlpha::Wanted()) {
        card_alpha = std::make_unique<CardAlpha>(instance, scheduler, texture_cache, runtime,
                                                 *scene_targets, *camera_motion, *rt_shadow);
        if (!upscaler->Enabled()) {
            card_alpha->NoSceneHooks();
        }
    }
    card_bound_on = card_alpha && card_alpha->On();
    rt_shadow->SetCardLayers(card_bound_on ? card_alpha.get() : nullptr);
"""),
        (r"""        image_descriptor_array_sizes.push_back(num_bindings);
    }

    if (time_slow) {
        pass1_stamps.push_back(__rdtsc());
    }
""",
         r"""        image_descriptor_array_sizes.push_back(num_bindings);
    }
    // bbport (r62_leaf-stage3): what this pixel shader's lookups found, for its card's layer
    // (NoteCardLayer). Only when every image took one binding: then a binding's index is its
    // image's.
    if (card_bound_on && stage.sw_stage == Shader::SwStage::Fragment) {
        const bool one_each = dc.image_bindings.size() == stage.images.size() &&
                              stage.images.size() <= resolved.size();
        dc.card_bound.stage = one_each ? &stage : nullptr;
        dc.card_bound.count = one_each ? static_cast<u32>(stage.images.size()) : 0u;
        for (u32 i = 0; i < dc.card_bound.count; ++i) {
            dc.card_bound.ids[i] = resolved[i].found;
            dc.card_bound.uids[i] = resolved_uids[i];
        }
    }

    if (time_slow) {
        pass1_stamps.push_back(__rdtsc());
    }
"""),
        (r"""    (void)first_image_idx;
    return true;
}
""",
         r"""    // bbport (r62_leaf-stage3): what the set holds for each image (FindImage's image and its
    // uid), for a pixel shader's card layer (NoteCardLayer): a set hit leaves the binding memo
    // untouched, so its entries are the only record of this draw's images.
    if (card_bound_on && stage.sw_stage == Shader::SwStage::Fragment) {
        dc.card_bound.stage = &stage;
        dc.card_bound.count = count;
        for (u32 i = 0; i < count; ++i) {
            dc.card_bound.ids[i] = set.entries[i].found;
            dc.card_bound.uids[i] = set.found_uids[i];
        }
    }
    (void)first_image_idx;
    return true;
}
"""),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r"""#include "video_core/renderer_vulkan/vk_effect_shaders.h"
""",
         r"""#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)
#include "video_core/renderer_vulkan/vk_effect_shaders.h"
"""),
        (r"""    rt_shadow->OnFrameEnd();
    // bbport (r19_draw-cost): the draws that took each short path, a frame.
""",
         r"""    rt_shadow->OnFrameEnd();
    if (card_alpha) { // bbport (r62_leaf-stage3)
        card_alpha->OnFrameEnd();
    }
    // bbport (r19_draw-cost): the draws that took each short path, a frame.
"""),
        (r"""        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
    }
}
""",
         r"""        volumetric_light->Composite(upscaler->SceneColor(), "the upscaler");
    }
    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.
    if (card_alpha && card_alpha->ViewOn() && compute_hash == upscaler->TriggerHash()) {
        card_alpha->View(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter());
    }
}
"""),
        (r"""void Rasterizer::EffectsCaptureDraw(""",
         FX_LAYER + r"""void Rasterizer::EffectsCaptureDraw("""),
        (r"""        card = ResolveCardDraw(regs, *ps, draw.camera_pass, *memory, buffer_cache);
        draw.card = &*card;
""",
         r"""        card = ResolveCardDraw(regs, *ps, draw.camera_pass, *memory, buffer_cache);
        draw.card = &*card;
        // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA=2: the card's alpha layer
        if (card->valid && card_bound_on) {
            NoteCardLayer(*card, *ps);
        }
"""),
        (r"""    out.mode_v = u8(CardAxisMode(u32(sampler.clamp_y.Value())));
""",
         r"""    out.mode_v = u8(CardAxisMode(u32(sampler.clamp_y.Value())));
    // bbport (r62_leaf-stage3): the raw modes, for the mirror once and border modes the axis
    // modes fold into CLAMP (CardAxisExtra).
    out.clamp_u = u8(u32(sampler.clamp_x.Value()));
    out.clamp_v = u8(u32(sampler.clamp_y.Value()));
"""),
    ],
    R + "vk_pipeline_serialization.cpp": [
        (r"""#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)
""",
         r"""#include "shader_recompiler/ir/passes/cutout_analysis.h" // bbport (r50_leaf-stage1)
#include "video_core/renderer_vulkan/rt_card_layers.h"      // bbport (r62_leaf-stage3): CUT1
#include "video_core/renderer_vulkan/vk_card_alpha.h"       // bbport (r62_leaf-stage3): counts
"""),
        (r"""    if (discards && program->info.sw_stage == Shader::SwStage::Fragment &&
        Shader::Optimization::CutoutAnalysisOn()) {
        Shader::Optimization::NoteCutoutCacheRefusal();
        return false;
    }
""",
         r"""    if (discards && program->info.sw_stage == Shader::SwStage::Fragment &&
        Shader::Optimization::CutoutAnalysisOn()) {
        // bbport (r62_leaf-stage3): with BB_RT_CARD_ALPHA alone a record that brought its
        // cut-out record (the CUT1 part) is taken: ResolveCardDraw reads info.cutout. The log knob
        // still wants the IR (its shader lines); a record without the part compiles once in play
        // and is saved with it.
        if (!Shader::Optimization::CutoutLogOn() &&
            program->info.cutout.verdict != Shader::Info::Cutout::Verdict::NotAnalysed) {
            NoteCardCutoutLoaded();
        } else {
            NoteCardCutoutRefused();
            Shader::Optimization::NoteCutoutCacheRefusal();
            return false;
        }
    }
"""),
        (r"""static constexpr u32 FroyokTag = 0x31525946;
""",
         r"""static constexpr u32 FroyokTag = 0x31525946;
// bbport (r62_leaf-stage3): "CUT1" (Vulkan::CardCutoutTag): a pixel shader's cut-out record, with
// a version and its size (rt_card_layers.h). Its bytes are Info::Cutout's: a change of that
// struct must change Vulkan::CardCutoutFormat (the size check below fails first); a change of
// the matcher, Shader::Optimization::CutoutAnalysisVersion.
static_assert(std::is_trivially_copyable_v<Info::Cutout>);
static_assert(sizeof(Info::Cutout) == 104, "Info::Cutout changed: bump Vulkan::CardCutoutFormat");
static_assert(Vulkan::CardCutoutTag != ToneCurveTag && Vulkan::CardCutoutTag != Gt7CheckedTag &&
              Vulkan::CardCutoutTag != FroyokTag);
static constexpr u32 CutoutPartVersion =
    Vulkan::CardCutoutVersion(Shader::Optimization::CutoutAnalysisVersion);
// Info::Cutout's padding bytes (one byte after layer, num_inputs and samples_screen: clang's
// record layout, checked by the asserts), written as 0 so a record's bytes depend on its values
// alone.
static constexpr std::array<std::size_t, 3> CutoutPadding{offsetof(Info::Cutout, layer) + 1,
                                                          offsetof(Info::Cutout, num_inputs) + 1,
                                                          offsetof(Info::Cutout, samples_screen) + 1};
static_assert(offsetof(Info::Cutout, layer_value) == offsetof(Info::Cutout, layer) + 2 &&
                  offsetof(Info::Cutout, input_default_mask) == offsetof(Info::Cutout, num_inputs) + 2 &&
                  sizeof(Info::Cutout) == offsetof(Info::Cutout, samples_screen) + 2,
              "Info::Cutout's padding moved: update CutoutPadding");
"""),
        (r"""    if (uses_froyok_bloom) {
        Serialization::Writer tail{ar};
        tail.Write(FroyokTag);
    }
}
""",
         r"""    if (uses_froyok_bloom) {
        Serialization::Writer tail{ar};
        tail.Write(FroyokTag);
    }
    // bbport (r62_leaf-stage3): an analysed pixel shader's cut-out record: analysed in a run with
    // BB_RT_CARD_ALPHA or the log knob, or restored from a CUT1 part (a knob-off run re-saving
    // a permutation keeps the part it loaded).
    if (cutout.verdict != Cutout::Verdict::NotAnalysed) {
        std::array<u8, Vulkan::CardCutoutBytes<Cutout>> part{};
        Vulkan::CardCutoutEncode(cutout, CutoutPartVersion, CutoutPadding, part.data());
        Serialization::Writer tail{ar};
        tail.Write(part.data(), part.size());
    }
}
"""),
        (r"""    uses_froyok_bloom = false;
    while (!ar.IsEoS()) {
""",
         r"""    uses_froyok_bloom = false;
    cutout = {}; // bbport (r62_leaf-stage3): unless a CUT1 part restores it
    while (!ar.IsEoS()) {
"""),
        (r"""        } else if (tag == FroyokTag) {
            ar.Advance(sizeof(tag));
            uses_froyok_bloom = true;
""",
         r"""        } else if (tag == FroyokTag) {
            ar.Advance(sizeof(tag));
            uses_froyok_bloom = true;
        } else if (tag == Vulkan::CardCutoutTag) { // bbport (r62_leaf-stage3)
            const u8* payload = nullptr;
            const std::size_t used = Vulkan::CardCutoutPart<Cutout>(
                ar.CurrPtr(), ar.Remaining(), CutoutPartVersion, payload);
            if (used == 0) {
                return false;
            }
            if (payload && Vulkan::CardCutoutBytesValid<Cutout>(payload)) {
                std::memcpy(&cutout, payload, sizeof(cutout));
            }
            ar.Advance(used);
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""    if (FILENAME MATCHES "^rt_card_uv")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
""",
         r"""    if (FILENAME MATCHES "^rt_card_uv")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
    # bbport (r62_leaf-stage3): the card alpha passes' layout and the card test
    if (FILENAME MATCHES "^rt_card_(alpha|view)")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
"""),
        (r"""add_host_shader(rt_card_uv.comp rt_card_uv_comp)
""",
         r"""add_host_shader(rt_card_uv.comp rt_card_uv_comp)
# bbport (r62_leaf-stage3): the card alpha layers' fill and the card debug view (BB_RT_CARD_ALPHA=2)
add_host_shader(rt_card_alpha_fill.comp rt_card_alpha_fill_comp)
add_host_shader(rt_card_view.comp rt_card_view_comp)
"""),
        (r"""target_include_directories(rt-card-uv-test PRIVATE ..)
""",
         r"""target_include_directories(rt-card-uv-test PRIVATE ..)
# bbport (r62_leaf-stage3): the card alpha layers' pure parts (renderer_vulkan/rt_card_layers.h)
add_executable(rt-card-layers-test EXCLUDE_FROM_ALL ../tests/test_rt_card_layers.cpp)
target_compile_options(rt-card-layers-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-card-layers-test PRIVATE ..)
"""),
    ],
    E + "build.sh": [
        (r"""    out/rt-card-uv-test
""",
         r"""    out/rt-card-uv-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_card_layers.cpp -o out/rt-card-layers-test
    out/rt-card-layers-test
"""),
    ],
    DOCS + "rt_card_alpha.md": [
        (r"""# Ray traced foliage shadows: the card UVs (stage 2, BB_RT_CARD_ALPHA)
""",
         r"""# Ray traced foliage shadows: the card UVs and alpha layers (stages 2 and 3, BB_RT_CARD_ALPHA)

Stage 3 (r62, `BB_RT_CARD_ALPHA=2`: alpha layers, card table, debug view, cache tag) is described
at the end of this page.
"""),
        (r"""| `BB_RT_CARD_ALPHA` | unset, `0`: off. `1`: on. Anything else: off, said once in the log. | Read once at start. With `1` the cut-out cards' UVs are captured into a pool (this page). Later stages will take levels above 1. |
""",
         r"""| `BB_RT_CARD_ALPHA` | unset, `0`: off. `1`: on. `2`: on with stage 3. Anything else: off, said once in the log. | Read once at start. With `1` the cut-out cards' UVs are captured into a pool (this page). `2` adds stage 3 (below). |
"""),
        (r"""shaders to compile in play (a short stutter the first time each is drawn). A cache tag (stage 3)
is to remove that before the option is offered to players.
""",
         r"""shaders to compile in play (a short stutter the first time each is drawn). Stage 3's cache part
(CUT1, below) removes that for `BB_RT_CARD_ALPHA` after the first run (and the first run after an
engine update that changes the cache id, see "The cache tag CUT1"); the log knob still compiles
them in play.
"""),
        (r"""## Not done in this stage

The alpha layers and the debug view (stage 3), the lamp rays (stage 4), the decision point for a
lamp card map (4b), characters, hair and cloth (5), the sun and the bounced light (6), and the
cost levers (7).
""",
         DOC_STAGE3),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: (text.replace("\r\n", "\n") if text is not None else None) for path, text in texts.items()}
    ok = True
    if any(foreign(p) for p in list(EDITS) + list(NEW)):
        print("this round would touch a file of another round, the drawn look or the fog")
        ok = False
    # What this patch writes is ASCII (a file it edits may hold other bytes of its own).
    for path, text in list(NEW.items()) + [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in text):
            print("%s: not ASCII" % path)
            ok = False
    # The C escapes kept their backslash on the way into this script.
    for path, needle in ((R + "vk_card_alpha.cpp", "no shadow \"\n                \"reads the layers yet\\n\""),
                         (TESTS + "test_rt_card_layers.cpp", "all passed\\n\");"),
                         (P + "cutout_analysis_pass.cpp", "\"off\\n\",\n"),
                         (R + "rt_card_uv.h", "text[1] == '\\0'")):
        if needle not in texts[path]:
            print("%s: a C escape lost its backslash on the way into the script" % path)
            ok = False
    # The knob: read once, in one place; the level gates every stage 3 piece.
    cut = texts[P + "cutout_analysis_pass.cpp"]
    if cut.count('std::getenv("BB_RT_CARD_ALPHA")') != 1 or cut.count("u32 CardAlphaLevel() {") != 1:
        print("cutout_analysis_pass.cpp: BB_RT_CARD_ALPHA is not read once")
        ok = False
    alpha = texts[R + "vk_card_alpha.cpp"]
    if alpha.count('std::getenv("BB_RT_CARD_ALPHA_VIEW")') != 1 or \
            alpha.find("level = Shader::Optimization::CardAlphaLevel();") > alpha.find("made = Make();"):
        print("vk_card_alpha.cpp: the knobs are not read once before anything is made")
        ok = False
    rt = texts[R + "vk_rt_shadow.cpp"]
    h = texts[R + "vk_rt_shadow.h"]
    if "card_layers_on = " in rt or h.count("card_layers_on = layers != nullptr;") != 1 or \
            rt.count("    if (card_layers_on) {\n        CardRows();\n    }\n") != 1:
        print("vk_rt_shadow: the rows are not gated by a CardAlpha that is on (SetCardLayers)")
        ok = False
    # No extra TLAS build from the rows (a second build in a frame reuses the ring slot).
    rows_fn = rt[rt.find("void RtShadow::CardRows() {"):rt.find("void RtShadow::OnFrameEnd() {")]
    if not rows_fn or "tlas_count" in rows_fn:
        print("vk_rt_shadow.cpp: CardRows forces a TLAS build")
        ok = False
    if "(r54): BB_RT_CARD_ALPHA=1" in rt or "(r54, BB_RT_CARD_ALPHA=1)" in rt:
        print("vk_rt_shadow.cpp: a line still names BB_RT_CARD_ALPHA=1 whatever the level")
        ok = False
    # CardAlpha only with the knob's level 2; every use behind a null test or card_bound_on.
    ras = texts[R + "vk_rasterizer.cpp"]
    if ras.count("    if (CardAlpha::Wanted()) {\n") != 1 or \
            ras.count("    card_bound_on = card_alpha && card_alpha->On();\n") != 1 or \
            ras.count("    if (card_bound_on && stage.sw_stage == Shader::SwStage::Fragment) {\n") != 2 or \
            ras.count("dc.card_bound.stage = ") != 2:
        print("vk_rasterizer.cpp: CardAlpha or the bound images are not made under the knob")
        ok = False
    # The rows come before the TLAS records and the early return; the fills before the readers.
    rows = rt.find("        CardRows();\n")
    early = rt.find("    if (count == tlas_count && (!hold_frames ||")
    custom = rt.find(".instanceCustomIndex = CardCustomIndex(*entry),")
    if not 0 <= rows < early < custom:
        print("vk_rt_shadow.cpp: the rows are not written before the TLAS")
        ok = False
    prep = rt[rt.find("bool RtShadow::PrepareCapture() {"):rt.find("bool RtShadow::PrepareScene() {")]
    if not 0 <= prep.find("RecordBuilds();") < prep.find("card_layers->RecordFills();") < prep.find("return Complete()"):
        print("vk_rt_shadow.cpp: the fills are not recorded in PrepareCapture")
        ok = False
    # The custom index is 0 unless the knob's level is 2 and the slot's row was written.
    if "return card_layers_on && entry.card_uv && entry.card_uv->row_written ? entry.card_uv->slot" not in h:
        print("vk_rt_shadow.h: the custom index is not gated")
        ok = False
    fx = texts[R + "vk_rasterizer_effects.cpp"]
    note = fx.find("            NoteCardLayer(*card, *ps);")
    if fx.count("NoteCardLayer(") != 2 or not 0 <= fx.find("void Rasterizer::NoteCardLayer(") < \
            fx.find("void Rasterizer::EffectsCaptureDraw(") < fx.find("draw.card = &*card;") < note or \
            "        if (card->valid && card_bound_on) {\n" not in fx:
        print("vk_rasterizer_effects.cpp: the layer is not noted once, under the knob, after the card")
        ok = False
    if fx.count("card_alpha->") != fx.count("card_alpha->NoteDraw(") + fx.count("card_alpha->NoteNoSource(") + 3 or \
            "    if (card_alpha) { // bbport (r62_leaf-stage3)\n        card_alpha->OnFrameEnd();" not in fx or \
            "    if (card_alpha && card_alpha->ViewOn() && " not in fx:
        print("vk_rasterizer_effects.cpp: a use of card_alpha without its null test")
        ok = False
    # NoteCardLayer reads the draw's own bound images, not the binding memo or the LRU.
    nl = fx[fx.find("void Rasterizer::NoteCardLayer("):fx.find("void Rasterizer::EffectsCaptureDraw(")]
    if "Dc().card_bound" not in nl:
        print("vk_rasterizer_effects.cpp: NoteCardLayer does not read the draw's bound images")
        ok = False
    for bad in ("image_desc_cache", "CachedImageDescEntry(", "LookupMemoized(", "last_use",
                "found_generation", "GetImage("):
        if bad in nl:
            print("vk_rasterizer_effects.cpp: NoteCardLayer touches the memo or the LRU (%s)" % bad)
            ok = False
    ser = texts[R + "vk_pipeline_serialization.cpp"]
    if ser.count("Vulkan::CardCutoutEncode(cutout, CutoutPartVersion, CutoutPadding, part.data());") != 1 or \
            ser.count("Vulkan::CardCutoutPart<Cutout>(") != 1 or \
            ser.count("Vulkan::CardCutoutBytesValid<Cutout>(payload)") != 1 or \
            "CutoutBytesValid(const" in ser or \
            ser.count("static_assert(sizeof(Info::Cutout) == 104") != 1:
        print("vk_pipeline_serialization.cpp: the CUT1 part is not written and read once")
        ok = False
    load = ser[ser.find("bool PipelineCache::LoadPipelineStage("):]
    if not 0 <= load.find("!Shader::Optimization::CutoutLogOn() &&") < load.find("NoteCutoutCacheRefusal();"):
        print("vk_pipeline_serialization.cpp: the log knob no longer refuses discarding records")
        ok = False
    cm = texts[G + "CMakeLists.txt"]
    for needle in ("add_host_shader(rt_card_alpha_fill.comp rt_card_alpha_fill_comp)",
                   "add_host_shader(rt_card_view.comp rt_card_view_comp)",
                   "add_executable(rt-card-layers-test EXCLUDE_FROM_ALL ../tests/test_rt_card_layers.cpp)"):
        if cm.count(needle) != 1:
            print("CMakeLists.txt: %s is not there once" % needle)
            ok = False
    if texts[E + "build.sh"].count("tests/test_rt_card_layers.cpp -o out/rt-card-layers-test") != 1:
        print("build.sh: the test is not in --test once")
        ok = False
    # The shaders read the layout from the shared headers, not from numbers of their own.
    for name in ("rt_card_alpha_fill.comp", "rt_cards.glsl"):
        if '#include "rt_card_layers_layout.h"' not in texts[H + name]:
            print("%s: does not include the layout" % name)
            ok = False
    if '#include "rt_cards.glsl"' not in texts[H + "rt_card_view.comp"]:
        print("rt_card_view.comp: does not use the shared card test")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts ({path: text}, None for a file to remove), or None with
    the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, text in NEW.items():
        want = fix(text, "\r\n")
        if mode != "revert":
            if os.path.exists(path):
                if not quiet:
                    print("%s is there already" % path)
                return None
            if not os.path.isdir(os.path.dirname(path)):
                if not quiet:
                    print("no such folder: %s" % os.path.dirname(path))
                return None
            out[path] = want
        else:
            if not os.path.isfile(path) or open(path, encoding="utf-8", newline="").read() != want:
                if not quiet:
                    print("%s is not as this script writes it" % path)
                return None
            out[path] = None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r62_leaf-stage3.py check|apply|revert   (the tree: R62_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file); a file to remove is removed last. If a
    # step fails, what was already moved is put back from the texts read at the start, and what
    # was made is removed, so the tree is never left half patched.
    before = {path: open(path, "rb").read() for path in out if os.path.exists(path)}
    done = []
    try:
        for path, t in out.items():
            if t is not None:
                with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                    f.write(t)
        for path, t in out.items():
            if t is not None:
                os.replace(path + TMP, path)
                done.append(path)
        for path, t in out.items():
            if t is None:
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if path in before:
                with open(path, "wb") as f:
                    f.write(before[path])
            elif os.path.exists(path):
                os.remove(path)
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
