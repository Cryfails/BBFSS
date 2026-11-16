# r100e_blood-sheen-visible: FEATURE fix on top of r100d_blood-sheen-gbuffer (branch visual/blood-sheen).
# Applies ON TOP of r100d (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset makes no
# BloodSheen, so nothing of this runs and the frame stays bit-identical (the one null pointer test per
# hook is r100d's own).
#
# Why r100d's film was not visible (build 28, graveyard-blood: 106k to 108k pool pixels were made wet,
# the picture did not change, the pool glints blue under the moon with and without it). Read from the
# code and the pictures; the one fact the pictures cannot give is the pool's own gloss, so this patch
# also logs it:
#  1. The film only RAISES (max with what the pixel has) and its numbers are those of clean water on
#     stone: gloss 0.66, f0 0.04. The pool is painted in the ground's own G-buffer, whose blood was drawn
#     by the game as glossy already (the off picture shows the moon's blue glints on it); where the pixel
#     is at or above the film, the film changes nothing. The gloss 0.66 (exponent 2^(13 x 0.66) = 380) is
#     also a broad lobe on a rough normal map: the highlight is a speckle of the cobbles' bumps, which is
#     what the strength 2 picture shows (glitter, no film).
#  2. A liquid film is smooth: the ground's bumpy normal under it is what the moon and the lamps glint
#     on. Nothing flattened it.
#  3. A wet film darkens and reddens what is under it; the diffuse (albedo) is in an sRGB target the
#     engine cannot write, so nothing did.
#  4. The strength knob only mixed toward 0.66 / 0.2, so strength 2 added a little f0 and nothing else.
# What this patch changes (all in the same four passes; no new pass, no new image):
#  - the film: gloss toward 0.82 (exponent 2^10.7 = 1660: a sharp lobe), specular root toward 0.30 (f0
#    0.09 at strength 1, 0.55 root at most: f0 0.30); the root grows with the square root of the strength.
#  - EDIT also flattens the normal (G-buffer target 0, RGBA8, xyz*2-1; the alpha untouched): each picked
#    pixel's unit normal goes 85% x the strength (at most 1) of the way to the mean normal of the picked
#    pixels of its 8x8 group, where the group holds at least 8 of them and their mean is coherent (the
#    mean's length at least half their count; a slab edge is left alone). The pool's surface becomes a
#    smooth liquid, so the moon's and the lamps' highlights are sheets, not speckle. If target 0 is not
#    RGBA8 or cannot be a storage image, the normal is left alone (said once in the log).
#  - SHOW build, every pass with an EDIT, not in the test view: picked pixels of the lit scene are dimmed
#    and reddened, but only where they are dark (luminance below 0.1 full, none above 0.6): the dim
#    diffuse of the pool goes to 0.7 red, 0.4 green and blue times the DARKEN share, the highlights stay.
#    BB_BLOOD_SHEEN_DARKEN (0..1, default 0.5; 0 turns this pass off) sets the share; the strength (at
#    most 1) scales it too.
#  - BB_BLOOD_SHEEN_PAUSE (a live test knob, only in a build with the live knobs header): 1 stops the film
#    and the dimming at once, for same-view pairs in one game.
#  - EDIT counts what the picked pixels had BEFORE the film: the sum of gloss and of specular root
#    (x255) and how many were already at gloss 0.82 or more; a new log line prints the means.
#
# Cost (estimates, not measured): EDIT +0.03 ms at 1080p internal (a normal read and write on picked
# pixels, a 64-term sum by one thread a group), a SHOW pass every G-buffer pass with a wet ground
# (about 0.05 ms; it ran only in the test view before). No new memory.
#
# Files (anchored edits on r100d's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.h/.cpp,
# tests/test_blood_sheen.cpp, tests/test_effect_pipelines.cpp (the wet ground row gets one more storage
# image), README.md. CMakeLists.txt and build.sh need no edit.
#
# Use: python -I -X utf8 r100e_blood-sheen-visible.py check | apply | revert. Root from R100E_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100e_blood-sheen-visible_backup/ next to
# this script; a mixed state is refused and nothing is written. Revert order: this script, then
# r100d_blood-sheen-gbuffer.py.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100e_blood-sheen-visible"
BASE = "r100d_blood-sheen-gbuffer.py"
ROOT_ENV = "R100E_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100etmp"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
LAYOUT = HS + "blood_sheen_layout.h"
COMP = HS + "blood_sheen.comp"
RULES = RV + "blood_sheen.h"
SHEEN_H = RV + "vk_blood_sheen.h"
SHEEN = RV + "vk_blood_sheen.cpp"
TEST = "engine/tests/test_blood_sheen.cpp"
PIPES = "engine/tests/test_effect_pipelines.cpp"
README = "README.md"

EDITS = {
LAYOUT: [
(r'''#define BLOOD_SHEEN_FLAG_CLEAR 16u
''',
r'''#define BLOOD_SHEEN_FLAG_CLEAR 16u
// bbport (r100e_blood-sheen-visible): EDIT: the normal target is bound and RGBA8 (the pixels' normals
// are flattened); SHOW (not the test view): the picked pixels are dimmed and reddened (push `darken`).
#define BLOOD_SHEEN_FLAG_NORMAL 32u
'''),
(r'''#define BLOOD_SHEEN_WORD_WET 4u
''',
r'''#define BLOOD_SHEEN_WORD_WET 4u
// bbport (r100e_blood-sheen-visible): EDIT, what the made-wet pixels had before the film: the sum of
// the gloss times 255, the sum of the specular root's red times 255, and how many had a gloss at or
// above BLOOD_SHEEN_WET_GLOSS already.
#define BLOOD_SHEEN_WORD_GLOSS_SUM 5u
#define BLOOD_SHEEN_WORD_ROOT_SUM 6u
#define BLOOD_SHEEN_WORD_GLOSSY 7u
'''),
(r'''// EDIT: the gloss (G-buffer target 1, red; exponent 2^(13 g) in the game's lighting) and the root of
// the specular colour (G-buffer target 3, rgb; f0 = rgb^2) a pixel is raised toward: a water film
// (f0 0.04 at strength 1), gloss capped below the mirror so the game's static cube map does not show a
// wrong sky. Never lowered (max with what the ground has). Target 3's alpha (the lighting record) is
// never written. Above strength 1 the root grows with its square root, at most BLOOD_SHEEN_SPEC_ROOT_MAX.
#define BLOOD_SHEEN_WET_GLOSS 0.66
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.2
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.4
''',
r'''// EDIT: the gloss (G-buffer target 1, red; exponent 2^(13 g) in the game's lighting) and the root of
// the specular colour (G-buffer target 3, rgb; f0 = rgb^2) a pixel is raised toward: a liquid film
// (f0 0.09 at strength 1), gloss kept below the mirror (a sharp lobe, 2^(13 x 0.82) = 1660) so the
// game's static cube map does not show a wrong sky. Never lowered (max with what the ground has).
// Target 3's alpha (the lighting record) is never written. Above strength 1 the root grows with its
// square root, at most BLOOD_SHEEN_SPEC_ROOT_MAX (r100e_blood-sheen-visible: r100d had 0.66, 0.2, 0.4).
#define BLOOD_SHEEN_WET_GLOSS 0.82
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.3
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.55
// EDIT, the normal (target 0, xyz*2-1): a picked pixel's unit normal goes this share (times the
// strength, at most 1) of the way to the mean normal of the picked pixels of its group (one 8x8
// workgroup), where the group has at least BLOOD_SHEEN_NORMAL_MIN of them and the mean vector's length
// is at least BLOOD_SHEEN_NORMAL_COHERENT of their count (else a slab edge or a step is in the group).
#define BLOOD_SHEEN_NORMAL_SMOOTH 0.85
#define BLOOD_SHEEN_NORMAL_MIN 8.0
#define BLOOD_SHEEN_NORMAL_COHERENT 0.5
// SHOW (not the test view): a picked pixel of the lit scene is multiplied by (RED, OTHER, OTHER) times
// the share darken x (1 - smoothstep(LO, HI, luminance)), so dim diffuse goes deeper and redder and a
// bright highlight stays as it is.
#define BLOOD_SHEEN_DARKEN_RED 0.7
#define BLOOD_SHEEN_DARKEN_OTHER 0.4
#define BLOOD_SHEEN_DARKEN_LUMA_LO 0.1
#define BLOOD_SHEEN_DARKEN_LUMA_HI 0.6
'''),
],

COMP: [
(r'''    uint flags;     // BLOOD_SHEEN_FLAG_*
    uint unused;
};
''',
r'''    uint flags;     // BLOOD_SHEEN_FLAG_*
    uint unused;    // SHOW (not the test view): the bits of the dimming share, a float 0..1 (BloodSheenRules::Push::darken)
};
'''),
(r'''layout(binding = 5, std430) buffer Counters {
''',
r'''layout(binding = 5, rgba8) uniform image2D normal_img; // G-buffer target 0: xyz*2-1 world normal, .a kept
layout(binding = 6, std430) buffer Counters {
'''),
(r'''    return c.r >= red_min && c.r >= ratio * c.g && c.r >= ratio * c.b && lum <= lum_max;
}
#endif
''',
r'''    return c.r >= red_min && c.r >= ratio * c.g && c.r >= ratio * c.b && lum <= lum_max;
}
// The picked pixels' unit normals of the group, and their sum (w: how many). r100e_blood-sheen-visible.
shared vec4 group_normal[BLOOD_SHEEN_GROUP * BLOOD_SHEEN_GROUP];
shared vec4 group_mean;
#endif
'''),
(r'''    BeginCounts();
    if (inside) {
        const float depth = texelFetch(depth_tex, p, 0).x;
        const bool surface = depth > 0.0 && depth < 1.0; // not the sky, not cleared
        const bool keyed = (flags & BLOOD_SHEEN_FLAG_KEYED) != 0u;
        const bool rule = (flags & BLOOD_SHEEN_FLAG_RULE_ALBEDO) != 0u;
        bool kept = false;
        if (keyed) {
            const uint tag = imageLoad(tag_img, p).x;
            if (tag != 0u) {
                kept = (Print(p) | 1u) == tag;
                atomicAdd(group_counts[kept ? BLOOD_SHEEN_WORD_KEPT : BLOOD_SHEEN_WORD_LOST], 1u);
            }
        }
        bool picked = surface && (keyed ? kept : rule);
        if (picked && rule) {
            picked = DarkRed(texelFetch(albedo_tex, p, 0).rgb);
            if (picked) {
                atomicAdd(group_counts[BLOOD_SHEEN_WORD_RULE], 1u);
            }
        }
        if (picked) {
            const float w = clamp(strength, 0.0, 1.0);
            const float root = min(BLOOD_SHEEN_WET_SPEC_ROOT * sqrt(max(strength, 1.0)), BLOOD_SHEEN_SPEC_ROOT_MAX);
            vec4 m = imageLoad(material_img, p);
            m.r = max(m.r, mix(m.r, BLOOD_SHEEN_WET_GLOSS, w));
            imageStore(material_img, p, m);
            vec4 s = imageLoad(specular_img, p);
            s.rgb = max(s.rgb, mix(s.rgb, vec3(root), w));
            imageStore(specular_img, p, s); // .a (the lighting record) as it was
            atomicAdd(group_counts[BLOOD_SHEEN_WORD_WET], 1u);
        }
        imageStore(tag_img, p, uvec4(picked ? BLOOD_SHEEN_TAG_WET : (kept ? BLOOD_SHEEN_TAG_LEFT_OUT : 0u)));
    }
    EndCounts();
''',
r'''    BeginCounts();
    bool picked = false;
    bool kept = false;
    if (inside) {
        const float depth = texelFetch(depth_tex, p, 0).x;
        const bool surface = depth > 0.0 && depth < 1.0; // not the sky, not cleared
        const bool keyed = (flags & BLOOD_SHEEN_FLAG_KEYED) != 0u;
        const bool rule = (flags & BLOOD_SHEEN_FLAG_RULE_ALBEDO) != 0u;
        if (keyed) {
            const uint tag = imageLoad(tag_img, p).x;
            if (tag != 0u) {
                kept = (Print(p) | 1u) == tag;
                atomicAdd(group_counts[kept ? BLOOD_SHEEN_WORD_KEPT : BLOOD_SHEEN_WORD_LOST], 1u);
            }
        }
        picked = surface && (keyed ? kept : rule);
        if (picked && rule) {
            picked = DarkRed(texelFetch(albedo_tex, p, 0).rgb);
            if (picked) {
                atomicAdd(group_counts[BLOOD_SHEEN_WORD_RULE], 1u);
            }
        }
    }
    // The picked pixels' mean normal of this group (the flag is a push constant: every invocation
    // takes the barriers or none does).
    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;
    vec4 normal = vec4(0.0);
    if (do_normal) {
        vec4 mine = vec4(0.0);
        if (picked) {
            normal = imageLoad(normal_img, p);
            const vec3 n = normal.xyz * 2.0 - 1.0;
            const float len = length(n);
            if (len > 0.5) {
                mine = vec4(n / len, 1.0);
            }
        }
        group_normal[gl_LocalInvocationIndex] = mine;
        memoryBarrierShared();
        barrier();
        if (gl_LocalInvocationIndex == 0u) {
            vec4 sum = vec4(0.0);
            for (uint i = 0u; i < BLOOD_SHEEN_GROUP * BLOOD_SHEEN_GROUP; ++i) {
                sum += group_normal[i];
            }
            group_mean = sum;
        }
        memoryBarrierShared();
        barrier();
    }
    if (inside) {
        if (picked) {
            const float w = clamp(strength, 0.0, 1.0);
            const float root = min(BLOOD_SHEEN_WET_SPEC_ROOT * sqrt(max(strength, 1.0)), BLOOD_SHEEN_SPEC_ROOT_MAX);
            vec4 m = imageLoad(material_img, p);
            atomicAdd(group_counts[BLOOD_SHEEN_WORD_GLOSS_SUM], uint(m.r * 255.0 + 0.5));
            if (m.r >= BLOOD_SHEEN_WET_GLOSS) {
                atomicAdd(group_counts[BLOOD_SHEEN_WORD_GLOSSY], 1u);
            }
            m.r = max(m.r, mix(m.r, BLOOD_SHEEN_WET_GLOSS, w));
            imageStore(material_img, p, m);
            vec4 s = imageLoad(specular_img, p);
            atomicAdd(group_counts[BLOOD_SHEEN_WORD_ROOT_SUM], uint(s.r * 255.0 + 0.5));
            s.rgb = max(s.rgb, mix(s.rgb, vec3(root), w));
            imageStore(specular_img, p, s); // .a (the lighting record) as it was
            if (do_normal && group_mean.w >= BLOOD_SHEEN_NORMAL_MIN) {
                const float mean_len = length(group_mean.xyz);
                const vec3 n = normal.xyz * 2.0 - 1.0;
                const float len = length(n);
                if (len > 0.5 && mean_len >= BLOOD_SHEEN_NORMAL_COHERENT * group_mean.w) {
                    const vec3 flat_n = normalize(mix(n / len, group_mean.xyz / mean_len, BLOOD_SHEEN_NORMAL_SMOOTH * w));
                    imageStore(normal_img, p, vec4(flat_n * 0.5 + 0.5, normal.a)); // .a as it was
                }
            }
            atomicAdd(group_counts[BLOOD_SHEEN_WORD_WET], 1u);
        }
        imageStore(tag_img, p, uvec4(picked ? BLOOD_SHEEN_TAG_WET : (kept ? BLOOD_SHEEN_TAG_LEFT_OUT : 0u)));
    }
    EndCounts();
'''),
(r'''        if (tag == BLOOD_SHEEN_TAG_WET || tag == BLOOD_SHEEN_TAG_LEFT_OUT) {
            const vec4 c = imageLoad(scene_img, p);
''',
r'''        if ((flags & BLOOD_SHEEN_FLAG_SHOW) == 0u) {
            // Not the test view (r100e_blood-sheen-visible): a wet film darkens and reddens what is
            // under it; the dim diffuse goes deeper, a highlight (bright) stays.
            const float darken = uintBitsToFloat(unused);
            if (tag == BLOOD_SHEEN_TAG_WET && darken > 0.0) {
                const vec4 c = imageLoad(scene_img, p);
                const float luma = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
                const float dim = clamp(darken, 0.0, 1.0) *
                                  (1.0 - smoothstep(BLOOD_SHEEN_DARKEN_LUMA_LO, BLOOD_SHEEN_DARKEN_LUMA_HI, luma));
                const vec3 mult = mix(vec3(1.0), vec3(BLOOD_SHEEN_DARKEN_RED, BLOOD_SHEEN_DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim);
                imageStore(scene_img, p, vec4(c.rgb * mult, c.a));
            }
        } else if (tag == BLOOD_SHEEN_TAG_WET || tag == BLOOD_SHEEN_TAG_LEFT_OUT) {
            const vec4 c = imageLoad(scene_img, p);
'''),
],

RULES: [
(r'''(gloss 0.66, f0 0.04 at strength 1; never lowered; the''',
 r'''(gloss 0.82, f0 0.09 at strength 1, its normal flattened; never lowered; the'''),
(r'''root 0.2 * sqrt(strength), at most 0.4)''', r'''root 0.3 * sqrt(strength), at most 0.55)'''),
(r'''(1..16) and LumMax (0..1). Other text: "draw" (said in the log).
''',
r'''(1..16) and LumMax (0..1). Other text: "draw" (said in the log).
//   BB_BLOOD_SHEEN_DARKEN bbport (r100e): 0..1, default 0.5: how far the lit scene's dark picked pixels are
//                         dimmed and reddened after the lighting (times the strength, at most 1); 0: that
//                         pass does not run (the test view "show" never dims). Unset or other text:
//                         the default.
'''),
(r'''static_assert(Group == 8u && SlotWords == 8u);
static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear) == 31u);
''',
r'''inline constexpr std::uint32_t FlagNormal = BLOOD_SHEEN_FLAG_NORMAL; ///< EDIT: the normal target is bound
static_assert(Group == 8u && SlotWords == 8u);
static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal) == 63u);
'''),
(r'''static_assert(WordKeyed == 0 && WordKept == 1 && WordLost == 2 && WordRule == 3 && WordWet == 4);
''',
r'''static_assert(WordKeyed == 0 && WordKept == 1 && WordLost == 2 && WordRule == 3 && WordWet == 4);
// bbport (r100e_blood-sheen-visible): what the made-wet pixels had before the film.
inline constexpr std::uint32_t WordGlossSum = BLOOD_SHEEN_WORD_GLOSS_SUM, WordRootSum = BLOOD_SHEEN_WORD_ROOT_SUM;
inline constexpr std::uint32_t WordGlossy = BLOOD_SHEEN_WORD_GLOSSY;
static_assert(WordGlossSum == 5 && WordRootSum == 6 && WordGlossy == 7 && WordGlossy < SlotWords);
'''),
(r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.66 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.2 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.4);
''',
r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.82 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.3 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.55);
// bbport (r100e_blood-sheen-visible): the normal's flattening and the dimming, as the shader and the README name them.
inline constexpr float NormalSmooth = float(BLOOD_SHEEN_NORMAL_SMOOTH);
inline constexpr float DarkenRed = float(BLOOD_SHEEN_DARKEN_RED), DarkenOther = float(BLOOD_SHEEN_DARKEN_OTHER);
inline constexpr float DarkenLumaLo = float(BLOOD_SHEEN_DARKEN_LUMA_LO), DarkenLumaHi = float(BLOOD_SHEEN_DARKEN_LUMA_HI);
inline constexpr float DefaultDarken = 0.5f;
static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 0.85 && BLOOD_SHEEN_NORMAL_MIN == 8.0 && BLOOD_SHEEN_NORMAL_COHERENT == 0.5);
static_assert(BLOOD_SHEEN_DARKEN_RED == 0.7 && BLOOD_SHEEN_DARKEN_OTHER == 0.4);
static_assert(BLOOD_SHEEN_DARKEN_LUMA_LO == 0.1 && BLOOD_SHEEN_DARKEN_LUMA_HI == 0.6);
'''),
(r'''    float ratio = DefaultRatio, lum_max = DefaultLumMax;
};
''',
r'''    float ratio = DefaultRatio, lum_max = DefaultLumMax;
    float darken = DefaultDarken; ///< BB_BLOOD_SHEEN_DARKEN, 0..1 (0: no dimming pass)
};
'''),
(r'''/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_DRAW"),
                                    std::getenv("BB_BLOOD_SHEEN_RULE"));
    return knobs;
}
''',
r'''/// BB_BLOOD_SHEEN_DARKEN's text: a number into 0..1; unset, empty or other text: the default.
inline float ReadDarken(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return DefaultDarken;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return DefaultDarken;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, 1.0f) : DefaultDarken;
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs = [] {
        Knobs k = Read(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_DRAW"),
                       std::getenv("BB_BLOOD_SHEEN_RULE"));
        k.darken = ReadDarken(std::getenv("BB_BLOOD_SHEEN_DARKEN"));
        return k;
    }();
    return knobs;
}
'''),
(r'''/// blood_sheen.comp's push block, word for word (8 words).
''',
r'''/// SHOW's dimming share of a pixel of luminance `luma` (the shader's arithmetic): `darken` where it is
/// dark (at or below DarkenLumaLo), 0 where it is bright (at or above DarkenLumaHi); the pixel is then
/// multiplied by (1 - share) + share x (DarkenRed, DarkenOther, DarkenOther).
inline float DimShare(float luma, float darken) {
    const float t = std::clamp((luma - DarkenLumaLo) / (DarkenLumaHi - DarkenLumaLo), 0.0f, 1.0f);
    return std::clamp(darken, 0.0f, 1.0f) * (1.0f - t * t * (3.0f - 2.0f * t));
}

/// blood_sheen.comp's push block, word for word (8 words).
'''),
(r'''    std::uint32_t flags = 0;
    std::uint32_t unused = 0;
};
''',
r'''    std::uint32_t flags = 0;
    float darken = 0.0f; ///< SHOW (not the test view): the share of the dimming, 0..1
};
'''),
],

SHEEN_H: [
(r'''//    It notes each G-buffer pass's depth and targets 1 (gloss), 2 (albedo) and 3 (specular); before''',
 r'''//    It notes each G-buffer pass's depth and targets 0 (normal), 1 (gloss), 2 (albedo), 3 (specular); before'''),
(r'''//  - EffectsBlendedScene, after the opaque lighting of each G-buffer pass (Show): with "show", SHOW
//    over the lit scene colour, once after each EDIT.''',
 r'''//  - EffectsBlendedScene, after the opaque lighting of each G-buffer pass (Show): SHOW over the lit
//    scene colour, once after each EDIT: with "show" the test view, else (r100e) the dimming of the
//    picked pixels (BB_BLOOD_SHEEN_DARKEN above 0).'''),
(r'''    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_albedo{}, gbuffer_specular{};
''',
r'''    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_albedo{}, gbuffer_specular{};
    VideoCore::ImageId gbuffer_normal{}; ///< target 0 (r100e: flattened under the film)
'''),
(r'''    bool told_unfit = false, told_first = false, told_show = false;
''',
r'''    bool told_unfit = false, told_first = false, told_show = false, told_normal = false;
'''),
(r'''previews = 0, lamps_pending = 0;
''',
r'''previews = 0, lamps_pending = 0, normals = 0;
'''),
],

SHEEN: [
(r'''#include "video_core/texture_cache/texture_cache.h"
''',
r'''#include "video_core/texture_cache/texture_cache.h"
// bbport (r100e_blood-sheen-visible): the same-view A/B of the owner's pair (r84_live-test-knobs, a
// test tool): a build with the live knobs header lets one running game pause the film.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define BLOOD_SHEEN_LIVE_PAUSE 1
#endif
'''),
(r'''constexpr u64 ProfileRow = 100; ///< EffectPass::Mark: the row "Lighting: blood sheen"
''',
r'''constexpr u64 ProfileRow = 100; ///< EffectPass::Mark: the row "Lighting: blood sheen"

#ifdef BLOOD_SHEEN_LIVE_PAUSE
bool PauseParse(const char* text) {
    return text != nullptr && text[0] != '\0' && text[0] != '0';
}
#endif

/// BB_BLOOD_SHEEN_PAUSE (live, a test knob): 1 stops the film and the dimming at once, 0 (or unset)
/// runs them; always false in a build without the live knobs header. Said in the log at each change.
bool Paused() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<bool> knob{"BB_BLOOD_SHEEN_PAUSE", PauseParse};
    static bool last = false;
    const bool now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf("Blood sheen (r100e): %s (BB_BLOOD_SHEEN_PAUSE, a test knob)\n",
                         now ? "paused: no film, no dimming" : "running again");
    }
    return now;
#else
    return false;
#endif
}
'''),
(r'''    if (failed) {
        return;
    }
    const auto& k = R::Load();
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
''',
r'''    if (failed || Paused()) {
        return;
    }
    const auto& k = R::Load();
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
'''),
(r'''    if (!std::exchange(show_due, false) || failed || !scene || !tag_image || lamps_pending) {''',
 r'''    if (!std::exchange(show_due, false) || failed || !scene || !tag_image || lamps_pending || Paused()) {'''),
(r'''                     R::CanPick(k) ? "" : "; NOTHING can be picked: name a draw or use the albedo rule");
}
''',
r'''                     R::CanPick(k) ? "" : "; NOTHING can be picked: name a draw or use the albedo rule");
    BbReport::Printf("Blood sheen (r100e): the film also flattens the normal toward the mean of the picked pixels "
                     "of an 8x8 block (weight %.2f) and, after the lighting, dims and reddens the picked pixels' "
                     "dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
                     double(R::NormalSmooth * std::min(k.strength, 1.0f)), double(k.darken),
                     k.darken > 0.0f ? "on" : "off: no dimming pass");
}
'''),
(r'''                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_EDIT_COMP, "Blood sheen wet ground") &&''',
r'''                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_EDIT_COMP, "Blood sheen wet ground") &&'''),
(r'''        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
''',
r'''        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        gbuffer_normal = (mrt & 1u) ? targets[0] : VideoCore::ImageId{};
'''),
(r'''    const vk::ImageView specular_view = ViewOf(gbuffer_specular, vk::ImageAspectFlagBits::eColor, true, true);
    runtime.FlushBarriers();
''',
r'''    const vk::ImageView specular_view = ViewOf(gbuffer_specular, vk::ImageAspectFlagBits::eColor, true, true);
    // bbport (r100e_blood-sheen-visible): the normal target (0) is flattened where it is RGBA8 and fits
    // as the others do; else its binding stands on the gloss view and the shader leaves it alone.
    bool normal_ok = false;
    vk::ImageView normal_view = material_view;
    if (gbuffer_normal) {
        const auto& normal_image = texture_cache.GetImage(gbuffer_normal);
        normal_ok = normal_image.info.pixel_format == GbufferFormat && normal_image.info.num_samples == 1 &&
                    (scene_targets.Reduced() && scene_targets.EligibleScene(normal_image)) == reduced &&
                    normal_image.info.size.width >= (reduced ? 1u : width) &&
                    normal_image.info.size.height >= (reduced ? 1u : height);
        if (normal_ok) {
            const vk::ImageView view = ViewOf(gbuffer_normal, vk::ImageAspectFlagBits::eColor, true, true);
            normal_ok = static_cast<bool>(view);
            if (normal_ok) {
                normal_view = view;
            }
        }
    }
    if (!normal_ok && !told_normal) {
        told_normal = true;
        BbReport::Printf("Blood sheen (r100e): the normal target cannot be flattened (first time; it is %s): the "
                         "film leaves the normal as it is\n",
                         gbuffer_normal ? "not RGBA8 of the scene's size or not a storage image" : "not written by the G-buffer draws");
    }
    runtime.FlushBarriers();
'''),
(r'''    push.flags = R::Flags(k, step.slot);
    const bool fresh = std::exchange(tag_fresh, false);
    ++stats.edits;
    show_due = k.show;
''',
r'''    push.flags = R::Flags(k, step.slot) | (normal_ok ? R::FlagNormal : 0u);
    const bool fresh = std::exchange(tag_fresh, false);
    ++stats.edits;
    stats.normals += normal_ok ? 1u : 0u;
    show_due = k.show || k.darken > 0.0f; // the test view, or the dimming after the lighting
'''),
(r'''        [push, step, fresh, width, height, albedo_view, depth_view, material_view, specular_view,
         tag_handle''',
r'''        [push, step, fresh, width, height, albedo_view, depth_view, material_view, specular_view, normal_view,
         tag_handle'''),
(r'''            const std::array infos{Info(albedo_view), Info(depth_view), Info(tag), Info(material_view),
                                   Info(specular_view)};
''',
r'''            const std::array infos{Info(albedo_view), Info(depth_view), Info(tag), Info(material_view),
                                   Info(specular_view), Info(normal_view)};
'''),
(r'''                                    ImageWrite(4, eStorageImage, &infos[4]), BufferWrite(5, &counter_info)};''',
r'''                                    ImageWrite(4, eStorageImage, &infos[4]), ImageWrite(5, eStorageImage, &infos[5]),
                                    BufferWrite(6, &counter_info)};'''),
(r'''    push.size = {float(width), float(height)};
    push.flags = R::FlagShow;
    ++stats.shows;
''',
r'''    const auto& k = R::Load();
    push.size = {float(width), float(height)};
    push.flags = k.show ? R::FlagShow : 0u; // r100e: not the test view: the dimming (push.darken)
    push.darken = k.show ? 0.0f : k.darken * std::min(k.strength, 1.0f);
    ++stats.shows;
'''),
(r'''    gbuffer_depth = gbuffer_material = gbuffer_albedo = gbuffer_specular = {};
''',
r'''    gbuffer_depth = gbuffer_material = gbuffer_albedo = gbuffer_specular = gbuffer_normal = {};
'''),
(r'''                     c[R::WordKeyed], c[R::WordKept], c[R::WordLost], c[R::WordRule], c[R::WordWet]);
''',
r'''                     c[R::WordKeyed], c[R::WordKept], c[R::WordLost], c[R::WordRule], c[R::WordWet]);
    // bbport (r100e_blood-sheen-visible): what the made-wet pixels had before the film (the pool's own
    // gloss and specular root: a film at or below them changes nothing) and the passes that flattened.
    const double wet = std::max(1.0, double(c[R::WordWet]));
    BbReport::Printf("Blood sheen (r100e): before the film, the %u made-wet px had mean gloss %.3f and mean specular "
                     "root %.3f (film %.2f and %.2f at strength 1), %u px (%.0f%%) already at gloss >= %.2f; %u of %u "
                     "wet passes flattened the normal\n",
                     c[R::WordWet], double(c[R::WordGlossSum]) / 255.0 / wet, double(c[R::WordRootSum]) / 255.0 / wet,
                     double(R::WetGloss), double(R::WetSpecRoot), c[R::WordGlossy],
                     100.0 * double(c[R::WordGlossy]) / wet, double(R::WetGloss), stats.normals, stats.edits);
'''),
],

TEST: [
(r'''    // e. The wet film: never lowered; strength 1 reaches gloss 0.66 and root 0.2; above 1 the root
    // grows with the square root, at most 0.4; below 1 a share of the way.''',
r'''    // e. The wet film: never lowered; strength 1 reaches gloss 0.82 and root 0.3; above 1 the root
    // grows with the square root, at most 0.55; below 1 a share of the way.'''),
(r'''        assert(Near(half.gloss, 0.48) && Near(half.root, 0.15));
        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) && Near(Wet(0.0f, 0.0f, 2.0f).root, 0.2 * std::sqrt(2.0)));''',
r'''        assert(Near(half.gloss, 0.56) && Near(half.root, 0.2));
        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) &&
               Near(Wet(0.0f, 0.0f, 2.0f).root, WetSpecRoot * std::sqrt(2.0)));
        assert(Near(WetGloss, 0.82) && Near(WetSpecRoot, 0.3) && Near(SpecRootMax, 0.55));'''),
(r'''        static_assert(offsetof(Push, flags) == 24);
''',
r'''        static_assert(offsetof(Push, flags) == 24 && offsetof(Push, darken) == 28);
'''),
(r'''    std::puts("blood sheen: ok");
''',
r'''    // g. bbport (r100e_blood-sheen-visible): BB_BLOOD_SHEEN_DARKEN and the dimming's arithmetic.
    {
        assert(ReadDarken(nullptr) == DefaultDarken && ReadDarken("") == DefaultDarken);
        assert(ReadDarken("0") == 0.0f && ReadDarken("1") == 1.0f && ReadDarken(" 0.25") == 0.25f);
        assert(ReadDarken("7") == 1.0f && ReadDarken("-3") == 0.0f);
        assert(ReadDarken("x") == DefaultDarken && ReadDarken("0.5x") == DefaultDarken);
        assert(ReadDarken("nan") == DefaultDarken);
        assert(Read("1", nullptr, nullptr).darken == DefaultDarken); // Load() sets it from its own knob
        // a dark pixel gets the whole share, a bright one none, in between smoothly
        assert(Near(DimShare(0.02f, 0.5f), 0.5) && Near(DimShare(0.1f, 0.5f), 0.5));
        assert(Near(DimShare(0.6f, 0.5f), 0.0) && Near(DimShare(5.0f, 1.0f), 0.0));
        assert(Near(DimShare(0.35f, 1.0f), 0.5));
        assert(DimShare(0.2f, 1.0f) > DimShare(0.4f, 1.0f) && DimShare(0.3f, 0.0f) == 0.0f);
        // the pool's dim diffuse (luminance 0.02) at strength 1 and darken 0.5 loses a quarter of its
        // red and 30% of its green and blue
        const double share = DimShare(0.02f, 0.5f);
        assert(Near(1.0 - share + share * DarkenRed, 0.85) && Near(1.0 - share + share * DarkenOther, 0.7));
        assert(Flags(Read("1", nullptr, nullptr), 0) == 0u); // the flags the engine adds (normal) are its own
        assert((FlagNormal & (FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear)) == 0u);
    }

    std::puts("blood sheen: ok");
'''),
],

PIPES: [
(r'''        {"blood sheen wet ground",
         BLOOD_SHEEN_EDIT_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage,
          eStorageBuffer},
         32},
''',
r'''        {"blood sheen wet ground",
         BLOOD_SHEEN_EDIT_COMP,
         {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageImage,
          eStorageBuffer},
         32},
'''),
],

README: [
(r'''(gloss raised toward 0.66, the specular colour's square root toward 0.2, by the strength; never lowered; the target the game keeps its lighting record in is not touched)''',
 r'''(gloss raised toward 0.82, the specular colour's square root toward 0.3 (f0 0.09), by the strength; never lowered; the target the game keeps its lighting record in is not touched; the pixel's normal also goes 85% of the way, times the strength (at most 1), to the mean normal of the picked pixels of its 8x8 block when the block holds at least 8 of them and their normals agree, so the film is a smooth surface and its highlights are sheets, not the speckle of the cobbles' bumps)'''),
(r'''above 1 the specular colour's square root grows with the square root of the strength, at most 0.4)''',
 r'''above 1 the specular colour's square root grows with the square root of the strength, at most 0.55)'''),
(r'''pixels that passed the albedo rule, pixels made wet.
''',
r'''pixels that passed the albedo rule, pixels made wet. A second line (`Blood sheen (r100e)`) says what those pixels had before the film (their mean gloss and specular root, and how many were already at the film's gloss: a film at or below the ground's own values changes nothing) and how many wet passes flattened the normal. After the game's opaque lighting, the picked pixels of the lit scene are also dimmed and reddened where they are dark (luminance below 0.1: multiplied by 0.7 red and 0.4 green and blue, times `BB_BLOOD_SHEEN_DARKEN` and the strength up to 1; none above luminance 0.6, so highlights stay), because a wet film darkens what is under it and the game's albedo cannot be written; the test view `show` never dims.
'''),
(r'''Use `show` to see what else the rule would make wet | `draw` |
''',
r'''Use `show` to see what else the rule would make wet | `draw` |
| `BB_BLOOD_SHEEN_DARKEN` | Only with `BB_BLOOD_SHEEN` on. 0 to 1: how far the dark picked pixels of the lit scene are dimmed and reddened after the game's opaque lighting (the film's wet darkening; times the strength, at most 1). `0`: that pass does not run. Unset or other text: the default. Cost: an estimate (not measured) of 0.05 ms at 1080p internal for the pass, once for each G-buffer pass with a wet ground | `0.5` |
| `BB_BLOOD_SHEEN_PAUSE` | A test knob (live, through the live knobs file of the test tools; a build without that header ignores it). `1`: the film and the dimming stop at once (no pass runs), `0` or unset: they run. It lets one running game take the same view with and without the film. The log says each change | `0` |
'''),
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
    # the descriptor lists of the C++, the shader and the pipeline test agree, in order
    need(SHEEN, cpp, "{eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage,\n"
                     "                            eStorageImage, eStorageBuffer},\n")
    need(PIPES, t[PIPES], "BLOOD_SHEEN_EDIT_COMP,\n         {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage, eStorageImage,\n"
                          "          eStorageBuffer},\n         32},\n")
    need(COMP, comp, "layout(binding = 5, rgba8) uniform image2D normal_img;")
    need(COMP, comp, "layout(binding = 6, std430) buffer Counters {")
    need(COMP, comp, "layout(binding = 5, std430) buffer Counters {", 0)
    need(SHEEN, cpp, "ImageWrite(5, eStorageImage, &infos[5])")
    need(SHEEN, cpp, "BufferWrite(6, &counter_info)")
    need(SHEEN, cpp, "BufferWrite(5, &counter_info)", 0)
    need(SHEEN, cpp, "Info(normal_view)")
    # the layout numbers and the C++ asserts agree
    for line in ("#define BLOOD_SHEEN_WET_GLOSS 0.82\n", "#define BLOOD_SHEEN_WET_SPEC_ROOT 0.3\n",
                 "#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.55\n", "#define BLOOD_SHEEN_FLAG_NORMAL 32u\n",
                 "#define BLOOD_SHEEN_WORD_GLOSSY 7u\n", "#define BLOOD_SHEEN_SLOT_WORDS 8u\n"):
        need(LAYOUT, lay, line)
    need(RULES, hdr, "static_assert(sizeof(Push) == 32);")
    need(RULES, hdr, "uint unused", 0)
    need(COMP, comp, "uintBitsToFloat(unused)")
    # every log line of the class starts with "Blood sheen (r100d)" or "(r100e)"
    for line in cpp.split("\n"):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)
    # the barriers are in uniform control flow (the flag is a push constant)
    need(COMP, comp, "    if (do_normal) {\n        vec4 mine = vec4(0.0);\n")
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
