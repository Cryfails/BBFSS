// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the card test a ray runs at a candidate of a cut-out card, shared by
// the debug view (rt_card_view.comp) and, in stage 4, the lamp rays. renderer_vulkan/
// rt_card_layers.h's CardTest is the same on the CPU (tests/test_rt_card_layers.cpp).
//
// The including shader defines, before including this file, the bindings it gives them, in set
// CARD_SET (0 unless it defines another; bbport r63_leaf-stage4: the lamp pass's CARDS builds use 1):
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
// bbport (r63_leaf-stage4): a lamp ray reads the level of its footprint (cardTraceShadow below);
// the sun (stage 6) may read level 1, the bounced light level 2 (cardTestLod).
#ifndef RT_CARDS_GLSL
#define RT_CARDS_GLSL

#include "rt_card_uv_layout.h"
#include "rt_card_layers_layout.h"

#ifndef CARD_SET
#define CARD_SET 0
#endif
layout(set = CARD_SET, binding = CARD_BINDING_ROWS, std430) readonly buffer CardRows {
    uvec4 card_rows[];
};
layout(set = CARD_SET, binding = CARD_BINDING_POOL, std430) readonly buffer CardPool {
    uvec4 card_pool[];
};
layout(set = CARD_SET, binding = CARD_BINDING_LAYER_INFO, std430) readonly buffer CardLayerInfo {
    uint card_layer_info[];
};
layout(set = CARD_SET, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;
#ifdef CARD_TRACE_SHADOW
// bbport (r62h_cutout-cards-hit): card_ref_scale: times the reference of a greater or greater-or-equal
// rule (the lamp pass sets it for one ray's reads; 1: the game's rule); card_rescued: the reads kept only
// because of it; card_lod16: the sum of the levels read, in sixteenths. The lamp pass zeroes the counts
// before the ray and takes them after it.
float card_ref_scale = 1.0;
uint card_rescued = 0u;
uint card_lod16 = 0u;
// bbport (r62j_cutout-rule-and-place): card_dilate: a read at level 0 takes the maximum of the bilinear footprint's four
// texels where the row's rule is "above the reference" (greater, greater or equal; a thin blade that touches a texel keeps
// it: the layer is a box mean of a bigger texture; the "below" rules keep the bilinear value); card_wrap_clamped: an axis
// whose mode is a plain clamp wraps instead. Both are set by the lamp pass for one ray's reads (cardReadLampRule and the lamp
// ray) and reset after; the macros below are the old text where CARD_TRACE_SHADOW is not defined.
bool card_dilate = false;
bool card_wrap_clamped = false;
// bbport (r62k_cutout-lit-fence): card_nearest (with card_dilate): the read takes the one texel of the footprint nearest the
// coordinates in place of the maximum of the four (no dilation: BB_RT_CARD_LAMP_GATHER=2)
bool card_nearest = false;
// bbport (r62l_cutout-steady-proof) FEATURE: card_strict_t: a kept read at a hit nearer than this many metres along the ray is taken
// again with the game's own rule (reference scale 1, no dilation, no nearest texel), and dropped if that drops it (0: off);
// card_strict_drops: the reads that did (the lamp pass adds them to a counter and zeroes it).
float card_strict_t = 0.0;
uint card_strict_drops = 0u;
// bbport (r62m_cutout-name-blocker) TOOL: the hit a cardTraceShadow ray kept last: its card slot, BLAS primitive, barycentrics and the
// level it was read at (only meaningful when that ray ended CARD_RAY_KEPT; the lamp pass's blocker book names the slot)
uint card_kept_slot = 0u;
uint card_kept_prim = 0u;
vec2 card_kept_bary = vec2(0.0);
float card_kept_lod = 0.0;
// bbport (r62n_cutout-skinned-blocker) FEATURE: card_skip_from: a card met at a hit farther than this many metres along the ray is passed
// untested (a lamp's own housing or hook: the lamp pass sets it to the ray's length minus CARD_HOUSING; 1e30: never); card_housing_skips:
// the cards passed that way (the lamp pass counts them and zeroes it).
float card_skip_from = 1e30;
uint card_housing_skips = 0u;
// bbport (r128c_lrt-cutout-props) FEATURE (CARD_SUN_SELF is defined by rt_shadow.comp's CARDS builds only; the lamp builds do not define it, so
// their SPIR-V is unchanged): card_skip_below: a card met at a hit nearer than this many metres along the ray is the pixel's own surface and is passed
// untested (0: none); card_self_skips: the cards passed that way (the sun trace counts them and the pass zeroes nothing: one value a pixel).
#ifdef CARD_SUN_SELF
float card_skip_below = 0.0;
uint card_self_skips = 0u;
#endif
float cardTexel(vec2 uv, uint layer, float lod, uint op) {
    if (card_dilate && lod <= 0.0 && (op == CARD_OP_GREATER || op == CARD_OP_GREATER_EQUAL)) {
        const vec4 g = textureGather(card_alpha, vec3(uv, float(layer)), 0);
        if (card_nearest) { // bbport (r62k_cutout-lit-fence): the gather's texels are (i0,j1) (i1,j1) (i1,j0) (i0,j0)
            const vec2 f = fract(uv * vec2(textureSize(card_alpha, 0).xy) - 0.5);
            return f.y >= 0.5 ? (f.x >= 0.5 ? g.y : g.x) : (f.x >= 0.5 ? g.z : g.w);
        }
        return max(max(g.x, g.y), max(g.z, g.w));
    }
    return textureLod(card_alpha, vec3(uv, float(layer)), lod).r;
}
uint cardModeAdjust(uint mode, uint extra) {
    return card_wrap_clamped && mode == CARD_UV_MODE_CLAMP && extra == 0u ? uint(CARD_UV_MODE_WRAP) : mode;
}
#define CARD_TEXEL(uv, layer, lod, op) cardTexel(uv, layer, lod, op)
#define CARD_MODE(m, e) cardModeAdjust(m, e)
#else
#define CARD_TEXEL(uv, layer, lod, op) textureLod(card_alpha, vec3(uv, float(layer)), lod).r
#define CARD_MODE(m, e) (m)
#endif

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
    // bbport (r62b_leaf-stage3-followups): a rule that keeps no alpha in [0, 1] (a reference
    // above 1, used as read): no layer is needed, every candidate is dropped below.
    const bool clear = (a.z & CARD_ROW_CLEAR) != 0u;
    // A row not READY, a layer given to another texture since (its generation moved on) or not
    // filled, a primitive past the entry's records or past the pool: no data, never another
    // card's alpha.
    if ((a.z & CARD_ROW_READY) == 0u ||
        (!clear && (layer >= uint(CARD_LAYER_COUNT) ||
                    card_layer_info[layer] != (b.w | CARD_LAYER_READY))) ||
        primitive >= a.y || a.x + primitive >= uint(card_pool.length())) {
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
    r.uv = vec2(cardRepeatAxis(uv.x, CARD_MODE((a.z >> CARD_ROW_MODE_U_SHIFT) & 3u, (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u),
                               (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u, border),
                cardRepeatAxis(uv.y, CARD_MODE((a.z >> CARD_ROW_MODE_V_SHIFT) & 3u, (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u),
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
    if (clear) { // (r62b) dropped without a sample: alpha 0 (a border's alpha is at most 1 too)
        r.status = CARD_DROPPED;
        return r;
    }
    if (border) {
        return r;
    }
    r.alpha = CARD_TEXEL(r.uv, layer, lod, (a.z >> CARD_ROW_OP_SHIFT) & 7u) * factor; // bbport (r62j_cutout-rule-and-place)
    r.status = cardKeeps(r.alpha, uintBitsToFloat(a.w), (a.z >> CARD_ROW_OP_SHIFT) & 7u,
                         (a.z & CARD_ROW_NONZERO) != 0u)
                   ? CARD_KEPT
                   : CARD_DROPPED;
#ifdef CARD_TRACE_SHADOW
    // bbport (r62h_cutout-cards-hit): the lamp rays keep a texel above card_ref_scale times the reference
    // where the game's rule is "above the reference" (greater, greater or equal): the layer is a
    // resampled copy, thinner than the game's texel at a blade's edge
    if (r.status == CARD_DROPPED && card_ref_scale < 1.0) {
        const uint op = (a.z >> CARD_ROW_OP_SHIFT) & 7u;
        if ((op == CARD_OP_GREATER || op == CARD_OP_GREATER_EQUAL) &&
            cardKeeps(r.alpha, uintBitsToFloat(a.w) * card_ref_scale, op, (a.z & CARD_ROW_NONZERO) != 0u)) {
            r.status = CARD_KEPT;
            ++card_rescued;
        }
    }
#endif
    return r;
}

#ifdef CARD_TRANSMIT
// bbport (r131a_foliage-translucency) FEATURE (compiled only with CARD_TRANSMIT: every other build's SPIR-V is unchanged): a kept leaf texel
// passes a share of the light, tinted by the leaf. The including shader defines CARD_BINDING_COLOUR (the colour layers: a sampler2DArray, rgb the
// square root of the linear leaf colour, a 1 for a layer with colour, 0 for a mask texture: it passes grey). card_pass_share (T, the LUMA share
// passed, 0: the texel blocks as before), card_pass_tint (0 grey to 1 all of the hue) and card_pass_floor (a product below it blocks) are set by
// the caller before a ray; card_pass (the product of what the leaves passed) and the counts are reset by it too.
layout(set = CARD_SET, binding = CARD_BINDING_COLOUR) uniform sampler2DArray card_colour;
float card_pass_share = 0.0;
float card_pass_tint = 1.0;
float card_pass_floor = 0.02;
vec3 card_pass = vec3(1.0);
uint card_pass_n = 0u;       // leaves passed by this ray
uint card_pass_grey = 0u;    // of them (or in many rays, until the caller zeroes it) without colour
uint card_pass_floor_n = 0u; // 1 when this ray ended at the floor
vec3 cardLeafPass(CardResult c) {
    const uint layer = c.flags & CARD_ROW_LAYER_MASK;
    const vec4 t = textureLod(card_colour, vec3(c.uv, float(layer)), 0.0);
    if (t.a < 0.5) {
        ++card_pass_grey;
        return vec3(card_pass_share);
    }
    const vec3 leaf = t.rgb * t.rgb;
    const float l = max(dot(leaf, vec3(0.299, 0.587, 0.114)), 1e-3);
    const vec3 hue = min(leaf / l, vec3(3.0));
    return card_pass_share * mix(vec3(1.0), hue, card_pass_tint);
}
#endif

// The test at the layer's level 0 (the debug view's ray; bbport r63_leaf-stage4: the lamp rays
// read the level of their footprint, cardTraceShadow).
CardResult cardTest(uint slot, uint primitive, vec2 bary) {
    return cardTestLod(slot, primitive, bary, 0.0);
}

#ifdef CARD_TRACE_SHADOW
// bbport (r63_leaf-stage4): a shadow ray that crosses the cut-out cards where the game's alpha
// test drops their texel, for the lamp rays (point_shadow_ray.comp's CARDS builds) and later the
// sun. The including shader enables GL_EXT_ray_query and defines CARD_TRACE_SHADOW. The instances
// of cards with data carry CARD_LAMP_MASK (or another bit the caller's `mask` names) and are built
// FORCE_NO_OPAQUE (RtShadow::PrepareScene): `flags` must not hold gl_RayFlagsOpaqueEXT, which
// would make them opaque again. Every other instance is opaque, so a ray that meets no card does
// what an opaque ray does with the same flags (gl_RayFlagsTerminateOnFirstHitEXT: it ends at its
// first hit) and never enters the loop's body.
// At a card candidate: its row, its record and, unless it has no data or its rule keeps no alpha
// in [0, 1], one layer read at the level of the ray's footprint there (width0 + t * width_per_t
// metres; CARD_RAY_TEXELS_PER_M), tested with the card's rule (cardTestLod). Kept: the candidate
// is confirmed and the ray ends, blocked. Dropped: passed, the ray goes on. No data: passed (the
// lamp rays of before left such a card out). Once `cap` candidates were tested (with data), the
// next candidate of any kind blocks the ray untested; once CARD_RAY_GUARD * cap candidates of any
// kind were met, the next one blocks it too (so a ray through a dense bush reads at most `cap`
// layers and takes at most CARD_RAY_GUARD * cap + 1 candidates; a ray through more than that many
// cards without data is blocked where the lamp rays of before passed). The hit kept is not always
// the nearest (the hardware's order), as with the opaque rays that end at their first hit. A
// dithered row (CARD_ROW_DITHER) is tested without its dither (the game's sun shadow form), a row
// holding the sun pass's rule (CARD_ROW_SUN) as it is. renderer_vulkan/rt_card_layers.h CardRayRun
// is this loop on the CPU (tests/test_rt_card_layers.cpp).
struct CardRay {
    float t;      // the hit kept, along `dir` (below 0: free)
    uint how;     // CARD_RAY_FREE, CARD_RAY_OPAQUE, CARD_RAY_KEPT, CARD_RAY_CAP
    uint seen;    // card candidates met (0: the ray met no card)
    uint tested;  // of them, tested with a layer read
    uint no_data; // of them, without data (passed)
    uint lod_reads;     // bbport (r62g_cutout-shadows-visible): of the tested, read at a level above 0
    uint zero_reads;    // of the tested, texels whose alpha was 0
    uint partial_reads; // of the tested, texels with an alpha above 0 that the rule dropped
};

CardRay cardTraceShadow(accelerationStructureEXT scene, uint flags, uint mask, vec3 origin, float tmin,
                        vec3 dir, float tmax, uint cap, float width0, float width_per_t) {
    CardRay r = CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u, 0u, 0u, 0u); // (r62g: three more counts)
    rayQueryEXT query;
    rayQueryInitializeEXT(query, scene, flags, mask, origin, tmin, dir, tmax);
    while (rayQueryProceedEXT(query)) {
        if (rayQueryGetIntersectionTypeEXT(query, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {
            continue;
        }
        ++r.seen;
        bool block = r.tested >= cap || r.seen > cap * CARD_RAY_GUARD;
        if (block) {
            r.how = CARD_RAY_CAP;
        } else {
            const float t = rayQueryGetIntersectionTEXT(query, false);
            if (t > card_skip_from) { // bbport (r62n_cutout-skinned-blocker) FEATURE: the lamp's own housing casts no shadow
                ++card_housing_skips;
                continue;
            }
#ifdef CARD_SUN_SELF
            if (t < card_skip_below) { // bbport (r128c_lrt-cutout-props) FEATURE: the pixel's own surface
                ++card_self_skips;
                continue;
            }
#endif
            const float texels = max(width0 + t * width_per_t, 0.0) * CARD_RAY_TEXELS_PER_M;
            const float lod = texels > 1.0 ? min(log2(texels), float(CARD_LAYER_MIPS - 1)) : 0.0;
            const uint hit_slot = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false));
            const uint hit_primitive = uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false));
            const vec2 hit_bary = rayQueryGetIntersectionBarycentricsEXT(query, false);
            const uint rescued_before = card_rescued;
            CardResult c = cardTestLod(hit_slot, hit_primitive, hit_bary, lod);
            // bbport (r62l_cutout-steady-proof) FEATURE: near the surface the game's own rule decides (card_strict_t 0: never taken)
            if (c.status == CARD_KEPT && t < card_strict_t) {
                const float scale_was = card_ref_scale;
                const bool dilate_was = card_dilate;
                const bool nearest_was = card_nearest;
                card_ref_scale = 1.0;
                card_dilate = false;
                card_nearest = false;
                const CardResult game = cardTestLod(hit_slot, hit_primitive, hit_bary, lod);
                card_ref_scale = scale_was;
                card_dilate = dilate_was;
                card_nearest = nearest_was;
                if (game.status != CARD_KEPT) {
                    c = game;
                    card_rescued = rescued_before;
                    ++card_strict_drops;
                }
            }
            if (c.status == CARD_NO_DATA) {
                ++r.no_data;
                continue;
            }
            ++r.tested;
            r.lod_reads += lod > 0.0 ? 1u : 0u; // bbport (r62g_cutout-shadows-visible)
            card_lod16 += uint(lod * 16.0 + 0.5); // bbport (r62h_cutout-cards-hit)
            r.zero_reads += c.alpha <= 0.0 ? 1u : 0u;
            r.partial_reads += c.status != CARD_KEPT && c.alpha > 0.0 ? 1u : 0u;
            if (c.status == CARD_KEPT) {
                // bbport (r131a_foliage-translucency) FEATURE (CARD_TRANSMIT builds only): a kept texel passes light and the query goes on (not
                // confirmed), unless what is left falls below the floor: then it blocks as before. The product is order independent.
#ifdef CARD_TRANSMIT
                if (card_pass_share > 0.0) {
                    card_pass *= cardLeafPass(c);
                    ++card_pass_n;
                    if (max(max(card_pass.x, card_pass.y), card_pass.z) >= card_pass_floor) {
                        continue;
                    }
                    ++card_pass_floor_n;
                }
#endif
                r.how = CARD_RAY_KEPT;
                block = true;
                card_kept_slot = hit_slot; // bbport (r62m_cutout-name-blocker) TOOL
                card_kept_prim = hit_primitive;
                card_kept_bary = hit_bary;
                card_kept_lod = lod;
            }
        }
        if (block) {
            rayQueryConfirmIntersectionEXT(query);
            rayQueryTerminateEXT(query);
            break;
        }
    }
    if (rayQueryGetIntersectionTypeEXT(query, true) != gl_RayQueryCommittedIntersectionNoneEXT) {
        r.t = rayQueryGetIntersectionTEXT(query, true);
        if (r.how == CARD_RAY_FREE) {
            r.how = CARD_RAY_OPAQUE;
        }
    }
    return r;
}
#endif

#endif
