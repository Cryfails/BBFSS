# r100h_sheen-liquid: FEATURE fix on top of r100g_sheen-sheets (r100f, r100e, r100d; branch visual/blood-sheen).
# Applies ON TOP of r100g (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset makes no
# BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test per hook).
#
# Why r100g's highlights were still textured (build 40, graveyard-blood, zooms _rd_g_off1 / _rd_g_on1):
# the pool is picked pixel by pixel by the albedo rule (dark red). The cobble stones and cracks INSIDE the
# pool are not dark red: they were not picked at all, so they kept the ground's bumpy normal and its own
# gloss and specular colour, and the moon and the torches broke up on them (the high-frequency ripple of the
# glints); and the cover of r100g (16 taps, 4 and 10 px out) fell with every such gap, so the picked pixels
# next to a gap were levelled only to a share, too.
# What this patch changes (EDIT pass only; no new pass, no new image, no new memory, no new counter word):
#  - the mask is BLURRED over the stones' size: the cover is now the share of 24 taps (3 rings of 8 at 6, 14
#    and 28 px at 1080p, scaled by height/1080, each ring turned) whose albedo is dark red; cover =
#    smoothstep(0.25, 0.65, share). A pixel deep in the pool, gaps and all, has a share of 0.65 or more: the
#    weight is 1.0 there (the normal goes all the way to world up, strength permitting); only the rim (share
#    0.25 or less) falls to the edge weight 0.3. (r100g: 16 taps up to 10 px, smoothstep 0.45..0.95.)
#  - the GAPS are filled: a ground pixel that passed the draw key (kept) but whose own albedo is not dark red
#    is made wet and levelled when at least 2 of its 8 taps at 14 px are dark red (a cheap early out: almost
#    all of the frame stops there after 8 fetches) and the share of its 24 taps is high: weight
#    smoothstep(0.5, 0.8, share) times the up weight smoothstep(0.35, 0.6, normal.y) (a wall, a step's side
#    or the hunter's side are left alone). It needs the normal target (the fill reads the normal); the draw
#    key keeps it off the hunter and the props (only pixels the keyed ground draws wrote last); with the
#    albedo rule and NO named draw, an up-facing surface of another object inside a pool could be filled too.
#    The filled pixels are tagged wet, so the dimming after the lighting (darker, richer red) takes them too.
#  - the gloss is SET to the film's 0.86 for every wet pixel (mix by the weight; the ground's own value may go
#    down: 16-23% of the pool's pixels had 0.86 or more, up to a mirror, and a mixture of lobes of different
#    width is speckle on a level surface). 0.86 itself stays: a level surface mirrors the moon and each torch
#    in ONE lobe and a higher gloss would only make that lobe narrower (exponent 2^(13 g): 2320, about 1.4
#    degrees); BLOOD_SHEEN_WET_GLOSS is the one number to lower for broader sheets. The specular root goes
#    0.45 -> 0.55 (f0 0.20 -> 0.30), cap 0.65 -> 0.75 (strength 1.5: 0.67; 2 and more: 0.75): a wet film of
#    dark blood reflects more than the dry cobble, and it is the root, not the diffuse, so the darker richer
#    red of r100g (the dimming, unchanged) stays.
#  - dry cobbles (not picked, not near a pool) and the dream house (nothing is dark red there: the early out
#    of the fill never passes, 0 made wet) are untouched.
#
# Cost: EDIT only. Picked pixels: 24 albedo fetches (was 16) plus the sin and cos of 24 angles (ALU). Gaps:
# every ground pixel that is not dark red and was kept costs 8 fetches (the early out), the few that pass it
# 24 more and one normal load. At the graveyard about 1.1 million such pixels at 1080p internal: about 9
# million fetches, nearly all cache hits on a texture the lighting reads anyway. Estimate, not measured:
# below 0.1 ms at 1080p internal (four times that at 2160p). No new memory, no new pass.
#
# Files (anchored edits on r100g's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp (one log text),
# tests/test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit.
#
# Use: python -I -X utf8 r100h_sheen-liquid.py check | apply | revert. Root from R100H_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100h_sheen-liquid_backup/ next to this
# script; a mixed state is refused and nothing is written. Revert order: this script, then r100g.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100h_sheen-liquid"
BASE = "r100g_sheen-sheets.py"
ROOT_ENV = "R100H_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100htmp"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
LAYOUT = HS + "blood_sheen_layout.h"
COMP = HS + "blood_sheen.comp"
RULES = RV + "blood_sheen.h"
SHEEN = RV + "vk_blood_sheen.cpp"
TEST = "engine/tests/test_blood_sheen.cpp"
README = "README.md"

EDITS = {
LAYOUT: [
(r'''// r100g_sheen-sheets: gloss 0.86 (exponent 1660 -> 2320), root 0.45 (f0 0.20 at strength 1), cap 0.65
// (the numbers above name r100e's 0.82 and 0.3).
#define BLOOD_SHEEN_WET_GLOSS 0.86
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65
''',
r'''// r100h_sheen-liquid: the gloss stays 0.86 (exponent 2320; a level surface mirrors a light in ONE lobe, a
// higher gloss only narrows it) but is SET to it for every wet pixel (the ground's own value may go down:
// one width of lobe, no speckle); root 0.55 (f0 0.30 at strength 1), cap 0.75. (The numbers above name
// r100e's 0.82, 0.3 and 0.55, r100g's 0.86, 0.45 and 0.65.)
#define BLOOD_SHEEN_WET_GLOSS 0.86
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.55
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.75
'''),
(r'''#define BLOOD_SHEEN_COVER_LO 0.45
#define BLOOD_SHEEN_COVER_HI 0.95
#define BLOOD_SHEEN_COVER_NEAR 4
#define BLOOD_SHEEN_COVER_FAR 10
''',
r'''// r100h_sheen-liquid: the cover above is now the share of 24 taps, three rings of 8 at RING0, RING1 and RING2
// pixels (1080p, scaled by height/1080, each ring turned) whose albedo is dark red, so the ripple of the
// mask (a stone, a crack) is smaller than the blur; smoothstep(COVER_LO, COVER_HI, share) (the 16 taps and
// the numbers 0.45, 0.95, 4 and 10 of r100g are gone). FILL: a ground pixel the keyed draw wrote that is
// not dark red itself is made wet when at least FILL_MIN_HITS of the 8 taps of RING1 are dark red and by
// smoothstep(FILL_LO, FILL_HI, share) times the up weight (UP_LO, UP_HI) of its own normal.
#define BLOOD_SHEEN_COVER_LO 0.25
#define BLOOD_SHEEN_COVER_HI 0.65
#define BLOOD_SHEEN_RING0 6
#define BLOOD_SHEEN_RING1 14
#define BLOOD_SHEEN_RING2 28
#define BLOOD_SHEEN_FILL_LO 0.5
#define BLOOD_SHEEN_FILL_HI 0.8
#define BLOOD_SHEEN_FILL_MIN_HITS 2
'''),
],

COMP: [
(r'''// r100g_sheen-sheets: how much of the pixel's surroundings is dark red (the pool): the share of 16 taps,
// 8 directions at NEAR and 8 at FAR pixels (1080p; scaled by height/1080), whose albedo passes DarkRed.
// The albedo target is read only in this pass, so the taps race with nothing.
float PoolShare(ivec2 p) {
    const float scale = size.y / 1080.0;
    const ivec2 hi = ivec2(size) - ivec2(1);
    const ivec2 dirs[8] = ivec2[8](ivec2(1, 0), ivec2(1, 1), ivec2(0, 1), ivec2(-1, 1),
                                   ivec2(-1, 0), ivec2(-1, -1), ivec2(0, -1), ivec2(1, -1));
    int radii[2];
    radii[0] = max(1, int(float(BLOOD_SHEEN_COVER_NEAR) * scale + 0.5));
    radii[1] = max(1, int(float(BLOOD_SHEEN_COVER_FAR) * scale + 0.5));
    float hit = 0.0;
    for (int r = 0; r < 2; ++r) {
        for (int d = 0; d < 8; ++d) {
            const ivec2 q = clamp(p + dirs[d] * radii[r], ivec2(0), hi);
            hit += DarkRed(texelFetch(albedo_tex, q, 0).rgb) ? 1.0 : 0.0;
        }
    }
    return hit * (1.0 / 16.0);
}
''',
r'''// r100h_sheen-liquid: how much of the pixel's surroundings is dark red (the pool). RingHits counts the taps
// of one ring (8 directions at RING0, RING1 or RING2 pixels, 1080p, scaled by height/1080; each ring is
// turned by its own angle so the 24 taps do not line up) whose albedo passes DarkRed; PoolShare is the share
// of all 24. The rings reach 6, 14 and 28 pixels, more than the ripple of the mask (a stone, a crack), so
// the ripple does not show in the share. The albedo target is read only in this pass: the taps race with
// nothing.
int RingHits(ivec2 p, int ring) {
    const float turns[3] = float[3](0.0, 0.3927, 0.19635);
    const float radii[3] = float[3](float(BLOOD_SHEEN_RING0), float(BLOOD_SHEEN_RING1), float(BLOOD_SHEEN_RING2));
    const float radius = max(1.0, radii[ring] * (size.y / 1080.0));
    const ivec2 hi = ivec2(size) - ivec2(1);
    int hit = 0;
    for (int d = 0; d < 8; ++d) {
        const float a = turns[ring] + 0.785398 * float(d);
        const ivec2 q = clamp(p + ivec2(round(vec2(cos(a), sin(a)) * radius)), ivec2(0), hi);
        hit += DarkRed(texelFetch(albedo_tex, q, 0).rgb) ? 1 : 0;
    }
    return hit;
}
float PoolShare(ivec2 p) {
    return float(RingHits(p, 0) + RingHits(p, 1) + RingHits(p, 2)) * (1.0 / 24.0);
}
'''),
(r'''    BeginCounts();
    bool picked = false;
    bool kept = false;
''',
r'''    BeginCounts();
    // r100h_sheen-liquid: the normal flag is read first (the fill of the pool's gaps needs the normal target).
    // r100f_sheen-smooth: no barrier, no shared memory, no group mean.
    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;
    bool picked = false;
    bool kept = false;
    // wet: the pixel's share of the film (1 for a dark red pixel, the fill weight for a gap of the pool);
    // filled: a gap, with pool_share the share of its 24 taps that are dark red.
    float wet = 1.0;
    bool filled = false;
    float pool_share = 0.0;
'''),
(r'''        picked = surface && (keyed ? kept : rule);
        if (picked && rule) {
            picked = DarkRed(texelFetch(albedo_tex, p, 0).rgb);
            if (picked) {
                atomicAdd(group_counts[BLOOD_SHEEN_WORD_RULE], 1u);
            }
        }
    }
    // The normal flag (a push constant). r100f_sheen-smooth: no barrier, no shared memory, no group mean.
    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;
    if (inside) {
        if (picked) {
            const float w = clamp(strength, 0.0, 1.0);
''',
r'''        picked = surface && (keyed ? kept : rule);
        if (picked && rule) {
            if (DarkRed(texelFetch(albedo_tex, p, 0).rgb)) {
                atomicAdd(group_counts[BLOOD_SHEEN_WORD_RULE], 1u);
            } else {
                // r100h_sheen-liquid: a gap of the pool (a stone, a crack the mask leaves out). 8 taps first:
                // almost all of the frame stops here. Then its normal faces up (a wall or a side is left
                // alone) and most of its 24 taps are dark red: wet by the weight. Counted in the wet word
                // only: made wet minus passed the albedo rule is the number filled.
                picked = false;
                if (do_normal) {
                    const int near_hits = RingHits(p, 1);
                    if (near_hits >= BLOOD_SHEEN_FILL_MIN_HITS) {
                        const float share = float(RingHits(p, 0) + near_hits + RingHits(p, 2)) * (1.0 / 24.0);
                        const vec3 gap_n = imageLoad(normal_img, p).xyz * 2.0 - 1.0;
                        const float gap_len = length(gap_n);
                        const float up = gap_len > 0.5 ? gap_n.y / gap_len : 0.0;
                        const float fill = smoothstep(BLOOD_SHEEN_FILL_LO, BLOOD_SHEEN_FILL_HI, share) *
                                           smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, up);
                        if (fill > 0.0) {
                            picked = true;
                            filled = true;
                            wet = fill;
                            pool_share = share;
                        }
                    }
                }
            }
        }
    }
    if (inside) {
        if (picked) {
            const float w = clamp(strength, 0.0, 1.0) * wet;
'''),
(r'''            m.r = max(m.r, mix(m.r, BLOOD_SHEEN_WET_GLOSS, w));
''',
r'''            m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, w); // r100h: the film's value, the ground's may go down
'''),
(r'''                    const float cover = (flags & BLOOD_SHEEN_FLAG_RULE_ALBEDO) != 0u
                        ? smoothstep(BLOOD_SHEEN_COVER_LO, BLOOD_SHEEN_COVER_HI, PoolShare(p)) : 1.0;
                    const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w * mix(BLOOD_SHEEN_NORMAL_EDGE, 1.0, cover) *
                                        smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);
''',
r'''                    // r100h_sheen-liquid: the cover from the 24-tap share (a gap already holds its share and its
                    // up weight: w includes them).
                    const float share = filled ? pool_share
                        : ((flags & BLOOD_SHEEN_FLAG_RULE_ALBEDO) != 0u ? PoolShare(p) : 1.0);
                    const float cover = smoothstep(BLOOD_SHEEN_COVER_LO, BLOOD_SHEEN_COVER_HI, share);
                    const float up_gate = filled ? 1.0
                        : smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);
                    const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w * mix(BLOOD_SHEEN_NORMAL_EDGE, 1.0, cover) *
                                        up_gate;
'''),
],

RULES: [
(r'''(gloss 0.82, f0 0.09 at strength 1, its normal flattened; never lowered; the''',
r'''(gloss 0.86, f0 0.30 at strength 1, its normal levelled, gaps of the pool filled (r100h); its gloss goes to it, the specular colour is never lowered; the'''),
(r'''root 0.3 * sqrt(strength), at most 0.55);''',
r'''root 0.55 * sqrt(strength), at most 0.75);'''),
(r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.45 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.65);
''',
r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.55 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.75);
'''),
(r'''static_assert(BLOOD_SHEEN_NORMAL_EDGE == 0.3 && BLOOD_SHEEN_COVER_LO == 0.45 && BLOOD_SHEEN_COVER_HI == 0.95);
static_assert(BLOOD_SHEEN_COVER_NEAR == 4 && BLOOD_SHEEN_COVER_FAR == 10);
''',
r'''static_assert(BLOOD_SHEEN_NORMAL_EDGE == 0.3 && BLOOD_SHEEN_COVER_LO == 0.25 && BLOOD_SHEEN_COVER_HI == 0.65);
static_assert(BLOOD_SHEEN_RING0 == 6 && BLOOD_SHEEN_RING1 == 14 && BLOOD_SHEEN_RING2 == 28);
static_assert(BLOOD_SHEEN_FILL_LO == 0.5 && BLOOD_SHEEN_FILL_HI == 0.8 && BLOOD_SHEEN_FILL_MIN_HITS == 2);
'''),
(r'''static_assert(BLOOD_SHEEN_DARKEN_RED == 0.7 && BLOOD_SHEEN_DARKEN_OTHER == 0.4);
''',
r'''// bbport (r100h_sheen-liquid): the share of the 24 taps (three rings of 8) that are dark red.
inline float PoolShareOf(int hits0, int hits1, int hits2) {
    return float(hits0 + hits1 + hits2) * (1.0f / 24.0f);
}
// bbport (r100h_sheen-liquid): the film weight of a ground pixel that is NOT dark red itself (a gap of the
// pool; the shader's arithmetic): 0 unless `near_hits` (of the 8 taps of the middle ring) reach the minimum,
// else smoothstep(FILL_LO, FILL_HI, pool_share) times the up weight of its own normal `up`.
inline float FillWeight(float pool_share, float up, int near_hits) {
    if (near_hits < BLOOD_SHEEN_FILL_MIN_HITS) {
        return 0.0f;
    }
    return SmoothStep(float(BLOOD_SHEEN_FILL_LO), float(BLOOD_SHEEN_FILL_HI), pool_share) *
           SmoothStep(float(BLOOD_SHEEN_NORMAL_UP_LO), float(BLOOD_SHEEN_NORMAL_UP_HI), up);
}
// bbport (r100h_sheen-liquid): the share of the way to world up of such a gap pixel (the weight already
// holds the up gate): the film weight times mix(EDGE, 1, cover).
inline float FilledLevelShare(float up, float pool_share, float strength, int near_hits) {
    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);
    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * FillWeight(pool_share, up, near_hits) *
           (edge + (1.0f - edge) * cover);
}
static_assert(BLOOD_SHEEN_DARKEN_RED == 0.7 && BLOOD_SHEEN_DARKEN_OTHER == 0.4);
'''),
(r'''inline Film Wet(float gloss, float root, float strength) {
    const float w = std::clamp(strength, 0.0f, 1.0f);
    const float target = std::min(WetSpecRoot * std::sqrt(std::max(strength, 1.0f)), SpecRootMax);
    return {std::max(gloss, gloss + (WetGloss - gloss) * w), std::max(root, root + (target - root) * w)};
}
''',
r'''inline Film Wet(float gloss, float root, float strength, float weight = 1.0f) {
    // r100h_sheen-liquid: the gloss goes TO the film's (the ground's may go down), the root never lowered;
    // `weight` is the pixel's share of the film (1; a gap of the pool: FillWeight).
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    const float target = std::min(WetSpecRoot * std::sqrt(std::max(strength, 1.0f)), SpecRootMax);
    return {gloss + (WetGloss - gloss) * w, std::max(root, root + (target - root) * w)};
}
'''),
],

SHEEN: [
(r'''    BbReport::Printf("Blood sheen (r100g): the film also levels the normal to world up, per pixel: all the way "
                     "inside the pool, weight %.2f at its rim (largest weight %.2f; gloss %.2f), and, after the "
                     "lighting, dims and reddens the picked pixels' dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
''',
r'''    BbReport::Printf("Blood sheen (r100h): the film also levels the normal to world up, per pixel: all the way "
                     "inside the pool, weight %.2f at its rim (largest weight %.2f; gloss %.2f for every wet pixel), "
                     "fills the pool's gaps (a kept ground pixel not dark red itself whose 24 ring taps at 6, 14 and "
                     "28 px (1080p) are 50-80%% dark red: the wet count minus the albedo rule count), and, after the "
                     "lighting, dims and reddens the picked pixels' dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
'''),
],

TEST: [
(r'''    // e. The wet film: never lowered; strength 1 reaches gloss 0.86 and root 0.45; above 1 the root
    // grows with the square root, at most 0.65; below 1 a share of the way.
''',
r'''    // e. The wet film (r100h_sheen-liquid): the gloss goes TO the film's (a glossier ground comes down), the
    // root is never lowered; strength 1 reaches gloss 0.86 and root 0.55; above 1 the root grows with the
    // square root, at most 0.75; below 1 a share of the way; a weight below 1 is a share again.
'''),
(r'''        const Film keep = Wet(0.9f, 0.5f, 1.0f);
        assert(Near(keep.gloss, 0.9) && Near(keep.root, 0.5));
''',
r'''        const Film keep = Wet(0.95f, 0.7f, 1.0f);
        assert(Near(keep.gloss, 0.86) && Near(keep.root, 0.7)); // the gloss comes down, the root is kept
        assert(Near(Wet(0.5f, 0.0f, 1.0f, 0.5f).gloss, 0.5 + 0.36 * 0.5) && Near(Wet(0.5f, 0.0f, 1.0f, 0.0f).gloss, 0.5));
        assert(Near(Wet(0.95f, 0.0f, 1.0f, 0.5f).gloss, 0.95 - 0.09 * 0.5));
'''),
(r'''        assert(Near(half.gloss, 0.58) && Near(half.root, 0.275));
''',
r'''        assert(Near(half.gloss, 0.58) && Near(half.root, 0.325));
'''),
(r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) &&
               Near(Wet(0.0f, 0.0f, 2.0f).root, WetSpecRoot * std::sqrt(2.0)));
        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.45) && Near(SpecRootMax, 0.65));
        assert(Near(Wet(0.0f, 0.0f, 2.0f).root, 0.45 * std::sqrt(2.0)) && Wet(0.0f, 0.0f, 2.0f).root < SpecRootMax);
''',
r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) && Near(Wet(0.0f, 0.0f, 2.0f).root, SpecRootMax));
        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.55) && Near(SpecRootMax, 0.75));
        assert(Near(Wet(0.0f, 0.0f, 1.5f).root, 0.55 * std::sqrt(1.5)) && Wet(0.0f, 0.0f, 1.5f).root < SpecRootMax);
'''),
(r'''        assert(Near(LevelShare(1.0f, 0.0f, 1.0f), 0.3) && Near(LevelShare(1.0f, 0.45f, 1.0f), 0.3));
        assert(Near(LevelShare(1.0f, 0.95f, 1.0f), 1.0) && Near(LevelShare(1.0f, 0.7f, 1.0f), 0.3 + 0.7 * 0.5));
''',
r'''        assert(Near(LevelShare(1.0f, 0.0f, 1.0f), 0.3) && Near(LevelShare(1.0f, 0.25f, 1.0f), 0.3));
        assert(Near(LevelShare(1.0f, 0.65f, 1.0f), 1.0) && Near(LevelShare(1.0f, 0.45f, 1.0f), 0.3 + 0.7 * 0.5));
'''),
(r'''        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(LevelShare(1.0f, f + 0.01f, 1.0f) >= LevelShare(1.0f, f, 1.0f));
        }
''',
r'''        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(LevelShare(1.0f, f + 0.01f, 1.0f) >= LevelShare(1.0f, f, 1.0f));
        }
        // i. bbport (r100h_sheen-liquid): the 24-tap share and the filling of the pool's gaps.
        assert(Near(PoolShareOf(8, 8, 8), 1.0) && Near(PoolShareOf(0, 0, 0), 0.0) && Near(PoolShareOf(4, 6, 8), 0.75));
        assert(FillWeight(1.0f, 1.0f, 8) == 1.0f && FillWeight(0.5f, 1.0f, 8) == 0.0f && FillWeight(0.2f, 1.0f, 8) == 0.0f);
        assert(Near(FillWeight(0.65f, 1.0f, 8), 0.5) && Near(FillWeight(0.8f, 1.0f, 2), 1.0));
        assert(FillWeight(1.0f, 1.0f, 1) == 0.0f && FillWeight(1.0f, 1.0f, 0) == 0.0f); // the early out
        assert(FillWeight(1.0f, 0.35f, 8) == 0.0f && FillWeight(1.0f, -1.0f, 8) == 0.0f);  // a wall or a side
        assert(Near(FillWeight(1.0f, 0.475f, 8), 0.5));                                      // the up gate's middle
        assert(Near(FilledLevelShare(1.0f, 1.0f, 1.0f, 8), 1.0) && FilledLevelShare(1.0f, 1.0f, 0.0f, 8) == 0.0f);
        assert(Near(FilledLevelShare(1.0f, 0.65f, 1.0f, 8), 0.5) && Near(FilledLevelShare(1.0f, 1.0f, 0.5f, 8), 0.5));
        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(FilledLevelShare(1.0f, f + 0.01f, 1.0f, 8) >= FilledLevelShare(1.0f, f, 1.0f, 8));
        }
'''),
],

README: [
(r'''gloss raised toward 0.86, the specular colour's square root toward 0.45 (f0 0.20), by the strength; never lowered;''',
 r'''gloss set toward 0.86 for every wet pixel (the ground's own gloss may go down, so the pool's gloss is uniform), the specular colour's square root raised toward 0.55 (f0 0.30), by the strength, never lowered;'''),
(r'''(the share of 16 taps around the pixel, 4 and 10 pixels out at 1080p, whose albedo is dark red is at least 0.95; the weight falls to 0.3 where it is 0.45 or less, at the pool's rim, so the rim follows the stones;''',
 r'''(the share of 24 taps around the pixel, three rings of 8 at 6, 14 and 28 pixels out at 1080p, whose albedo is dark red is at least 0.65; the weight falls to 0.3 where it is 0.25 or less, at the pool's rim, so the rim follows the stones;'''),
(r'''; 16 more texel fetches for each picked pixel)''',
 r'''; 24 texel fetches for each picked pixel; a ground pixel of the named draw whose own albedo is not dark red (a stone or a crack the mask leaves out) is made wet and levelled too when at least 2 of its 8 taps at 14 pixels are dark red and the share of its 24 taps is 0.5 to 0.8 (weight smoothstep 0.5 to 0.8, times the up weight of its normal, so walls and sides are left alone; it needs the normal target; 8 fetches for each such pixel, 24 more where the first 8 pass), so the ripple of the albedo mask no longer breaks the highlight; use it with a named draw: with the albedo rule alone an up-facing surface of another object inside a pool could be filled too; the count of filled pixels is the wet count minus the albedo rule count of the log's recent-frame line)'''),
(r'''at most 0.65); `show`''',
 r'''at most 0.75); `show`'''),
],
}

ORDER = list(EDITS)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("REFUSED %s: missing" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def one_state(cur, old, new):
    """An edit's state: a replacement (old not in new) or an insertion (new holds old)."""
    o, n = cur.count(old), cur.count(new)
    inner = new.count(old)
    if n == 1 and o == inner:
        return "applied"
    if n == 0 and o == 1:
        return "clean"
    return None


def edit_state(path, cur):
    states = [one_state(cur, old, new) for old, new in EDITS[path]]
    if None in states:
        bad = EDITS[path][states.index(None)]
        raise SystemExit("REFUSED %s: an edit's text is not found exactly once (before: %d times, after: %d "
                         "times; %s must be applied): %r" % (path, cur.count(bad[0]), cur.count(bad[1]), BASE,
                                                              bad[0][:70]))
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, states.count("applied"), len(states)))


def need(path, text, want, n=1):
    if text.count(want) != n:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), n))


def text_checks(t):
    comp, lay, hdr, cpp = t[COMP], t[LAYOUT], t[RULES], t[SHEEN]
    for want in ("#define BLOOD_SHEEN_WET_GLOSS 0.86\n", "#define BLOOD_SHEEN_WET_SPEC_ROOT 0.55\n",
                 "#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.75\n", "#define BLOOD_SHEEN_NORMAL_SMOOTH 1.0\n",
                 "#define BLOOD_SHEEN_NORMAL_UP_LO 0.35\n", "#define BLOOD_SHEEN_NORMAL_UP_HI 0.6\n",
                 "#define BLOOD_SHEEN_NORMAL_EDGE 0.3\n", "#define BLOOD_SHEEN_COVER_LO 0.25\n",
                 "#define BLOOD_SHEEN_COVER_HI 0.65\n", "#define BLOOD_SHEEN_RING0 6\n",
                 "#define BLOOD_SHEEN_RING1 14\n", "#define BLOOD_SHEEN_RING2 28\n",
                 "#define BLOOD_SHEEN_FILL_LO 0.5\n", "#define BLOOD_SHEEN_FILL_HI 0.8\n",
                 "#define BLOOD_SHEEN_FILL_MIN_HITS 2\n"):
        need(LAYOUT, lay, want)
    need(LAYOUT, lay, "BLOOD_SHEEN_COVER_NEAR", 0)
    need(LAYOUT, lay, "#define BLOOD_SHEEN_COVER_FAR", 0)
    need(COMP, comp, "int RingHits(ivec2 p, int ring)")
    need(COMP, comp, "float PoolShare(ivec2 p)")
    need(COMP, comp, "BLOOD_SHEEN_COVER_NEAR", 0)
    need(COMP, comp, "const bool do_normal =")  # once, before `picked`
    need(COMP, comp, "mix(BLOOD_SHEEN_NORMAL_EDGE, 1.0, cover)")
    need(COMP, comp, "m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, w);")
    need(COMP, comp, "const float w = clamp(strength, 0.0, 1.0) * wet;")
    need(COMP, comp, "barrier()", 2)  # the counter code's two only
    need(RULES, hdr, "inline float FillWeight(float pool_share, float up, int near_hits)")
    need(RULES, hdr, "inline float LevelShare(float up, float pool_share, float strength)")
    need(RULES, hdr, "BLOOD_SHEEN_WET_SPEC_ROOT == 0.55")
    need(RULES, hdr, "BLOOD_SHEEN_COVER_NEAR", 0)
    need(SHEEN, cpp, "Blood sheen (r100h): the film also levels")
    need(SHEEN, cpp, "Blood sheen (r100g)", 0)
    for line in cpp.split("\n"):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)
    added = [new for eds in EDITS.values() for old, new in eds]
    if any(ord(ch) > 127 for text in added for ch in text):
        raise SystemExit("text check: a new text is not plain ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 %s.py check | apply | revert" % NAME)
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set %s)" % (ROOT, ROOT_ENV))
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, edit_state(path, cur)))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()

    def result(forward):
        out = {}
        for path, raw, eol, cur, _ in plan:
            for old, new in EDITS[path]:
                cur = cur.replace(old, new) if forward else cur.replace(new, old)
            want = "applied" if forward else "clean"
            if edit_state(path, cur) != want:
                raise SystemExit("%s: the result does not read as %s; nothing written" % (path, want))
            out[path] = cur
        return out

    def write(texts):
        for path, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            open(full + TMP, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(full + TMP, full)

    edits = sum(len(e) for e in EDITS.values())
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (%d edits in %d files; text checks pass)" % (edits, len(EDITS)))
        else:
            text_checks(result(True))
            print("not applied; would apply (%d edits in %d files; text checks on the result pass)" % (edits, len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = result(True)
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write(texts)
        print("applied (%d edits in %d files)" % (edits, len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    write(result(False))
    print("reverted (%d edits taken out of %d files)" % (edits, len(EDITS)))


main()
